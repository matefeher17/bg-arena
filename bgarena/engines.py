"""Engine adapters.

Every competitor implements one method: given the position (always from its own
perspective), the dice, and the list of legal plays, return the play it wants.
The referee owns all state, so engines can be completely stateless — which is
exactly how Wildbg's API already works and makes the whole arena parallelisable.
"""

from __future__ import annotations

import json
import random
import socket
import subprocess
import time
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from .board import Board, NUM_POINTS, BAR, OFF
from .moves import Play, _apply_step


class Engine(ABC):
    name: str = "engine"

    @abstractmethod
    def choose(self, board: Board, dice: tuple[int, int], plays: list[Play], context: dict) -> Play:
        ...


class RandomEngine(Engine):
    """Plays a uniformly random legal move. The bottom of the ladder."""

    def __init__(self, seed: int = 0, name: str = "Random"):
        self.name = name
        self._rng = random.Random(seed)

    def choose(self, board, dice, plays, context):
        return self._rng.choice(plays)


class HeuristicEngine(Engine):
    """A tiny hand-rolled evaluator. Not strong, but reliably beats Random —
    useful as a sanity baseline that proves the arena can detect skill."""

    def __init__(self, name: str = "Heuristic"):
        self.name = name

    @staticmethod
    def _score(b: Board) -> float:
        pip = b.pip_count()
        blots = sum(1 for p in range(1, NUM_POINTS + 1) if b.points[p] == 1)
        made = sum(1 for p in range(1, NUM_POINTS + 1) if b.points[p] >= 2)
        return 100.0 * b.off - pip - 4.0 * blots + 1.0 * made

    def choose(self, board, dice, plays, context):
        return max(plays, key=lambda pl: self._score(pl.end_board))


class WildbgEngine(Engine):
    """Calls a Wildbg HTTP server. Run one locally with:

        docker run -p 8082:8082 wildbg

    The arena coordinate system matches Wildbg's, so a returned move maps
    directly. The exact response schema is assumed below and flagged — verify
    against your instance's /swagger-ui the first time you wire it up.
    """

    def __init__(self, base_url: str = "http://localhost:8082", name: str = "Wildbg"):
        self.name = name
        self.base_url = base_url.rstrip("/")

    def choose(self, board, dice, plays, context):
        d1, d2 = dice
        params = board.to_wildbg_params()
        params["die1"], params["die2"] = d1, d2
        url = f"{self.base_url}/move?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read().decode())

        # ASSUMPTION: response contains a ranked list whose top entry describes
        # the resulting point counts or the from/to steps. We match Wildbg's
        # chosen move to one of our legal plays by resulting position.
        target = self._infer_end_key(data, board, plays)
        for pl in plays:
            if pl.end_board.position_key() == target:
                return pl
        # If we could not reconcile the schema, fail loudly rather than cheat.
        raise ValueError(
            "Could not match Wildbg's response to a legal play — inspect the "
            f"JSON shape and adjust WildbgEngine._infer_end_key. Got: {data!r}"
        )

    @staticmethod
    def _infer_end_key(data, board, plays):
        # Placeholder reconciliation: when only one legal play exists this is
        # trivially correct; otherwise raise so the schema gets verified.
        if len(plays) == 1:
            return plays[0].end_board.position_key()
        raise NotImplementedError(
            "Wire WildbgEngine._infer_end_key to your instance's JSON schema."
        )


class SageEngine(Engine):
    """Open Sage (`pip install bgsage`), a neural-network engine.

    Asks Sage's checker-play analytics for the ranked moves and plays the
    top-equity one. The arena board converts directly to Sage's 26-int format,
    and Sage returns the resulting board, so the chosen move maps back to one of
    our legal plays by board equality.

    Evaluation level follows Sage's XG-style numbering: '1ply' is the raw net
    (fast); each extra ply is ~20x slower. We model a cubeless 1-pointer with
    away1=away2=1, where the cube is dead and the engine optimizes win
    probability — exactly the v1 comparison.
    """

    def __init__(self, level: str = "1ply", name: str | None = None):
        from bgsage import create_analyzer  # lazy: core arena needs no bgsage
        self.level = level
        self.name = name or f"Sage-{level}"
        self._az = create_analyzer(level=level)

    def choose(self, board, dice, plays, context):
        d1, d2 = dice
        res = self._az.checker_play(board.to_sage(), d1, d2, away1=1, away2=1)
        if not res.moves:
            raise ValueError("Sage returned no moves for a position with legal plays")
        target = res.moves[0].board                       # best move's resulting board
        for pl in plays:
            if pl.end_board.to_sage() == target:
                return pl
        raise ValueError(
            "Sage's chosen move did not match any legal play — check board "
            f"conversion. Sage board: {target}"
        )


# Default TCP port for gnubg's external server. gnubg has no registered
# default — you choose it when you run `external <port>` — so the arena fixes
# one and documents it (README "Running GNUbg", docs/gnubg-protocol.md).
DEFAULT_GNUBG_PORT = 8888

# How to start the server, embedded in connection errors so a contributor who
# hits "connection refused" gets the fix immediately (mirrors WildbgEngine's
# `docker run` hint).
_GNUBG_LAUNCH_HELP = (
    "Could not reach a gnubg external server at {host}:{port}.\n"
    "Start one (Linux/macOS; gnubg >= 1.06) with, e.g.:\n"
    "    printf 'external localhost:{port}\\n' | gnubg -t -q\n"
    "or launch gnubg and run  `external localhost:{port}`  at its prompt.\n"
    "Install: apt-get install gnubg  /  brew install gnubg.\n"
    "Or pass launch_cmd=[...] to GnubgEngine to have it spawn the server.\n"
    "Underlying error: {err}"
)


class GnubgEngine(Engine):
    """Adapter for GNU Backgammon via its external (socket) interface.

    Wire format confirmed on gnubg 1.07.001 / ubuntu-latest (commit ``ddb6fcf``).
    See ``docs/gnubg-protocol.md`` for the confirmed field layout and captured
    exchange. Run ``validate_gnubg.py`` before using in production matches.

    Safety: every reply is reconciled back to one of the referee's legal plays by
    *resulting position* (``end_board.position_key()``), exactly like Sage/Wildbg.
    A wrong coordinate guess therefore raises loudly rather than playing an
    illegal or substituted move — "fail loudly rather than cheat."

    Running the server (default port {port}):

        printf 'external localhost:{port}\\n' | gnubg -t -q

    Usage::

        with GnubgEngine() as gnu:
            duplicate_match(gnu, HeuristicEngine(), pairs=10)

    The engine is stateless w.r.t. the game (the referee owns board/dice/score);
    it holds only the socket (and optionally a spawned server process).
    """.format(port=DEFAULT_GNUBG_PORT)

    name = "GNUbg"

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_GNUBG_PORT,
                 name: str = "GNUbg", *, launch_cmd: list[str] | None = None,
                 connect_timeout: float = 30.0, io_timeout: float = 30.0):
        self.name = name
        self.host = host
        self.port = port
        self.launch_cmd = launch_cmd
        self.connect_timeout = connect_timeout
        self.io_timeout = io_timeout
        self._sock: socket.socket | None = None
        self._proc: subprocess.Popen | None = None

    # ---- connection (lazy: import bgarena never needs gnubg) -------------
    def _ensure_connected(self) -> None:
        if self._sock is not None:
            return
        if self.launch_cmd is not None and self._proc is None:
            # Spawn the server ourselves; it needs a moment to bind the port.
            self._proc = subprocess.Popen(self.launch_cmd)

        deadline = time.time() + self.connect_timeout
        last_err: Exception | None = None
        while time.time() < deadline:
            try:
                s = socket.create_connection((self.host, self.port), timeout=self.io_timeout)
                s.settimeout(self.io_timeout)
                self._sock = s
                return
            except OSError as e:                 # refused / not up yet -> retry
                last_err = e
                time.sleep(0.5)
        raise ConnectionError(_GNUBG_LAUNCH_HELP.format(
            host=self.host, port=self.port, err=last_err))

    def _send_line(self, line: str) -> None:
        assert self._sock is not None
        self._sock.sendall((line + "\n").encode("ascii"))

    def _read_line(self) -> str:
        """Read one newline-terminated reply from the server."""
        assert self._sock is not None
        buf = bytearray()
        while True:
            chunk = self._sock.recv(4096)
            if not chunk:                        # server closed mid-reply
                break
            buf.extend(chunk)
            if b"\n" in chunk:
                break
        return buf.split(b"\n", 1)[0].decode("ascii", "replace").strip()

    # ---- the one required method ----------------------------------------
    def choose(self, board, dice, plays, context):
        # game.py never calls choose() for a single play, but be correct if
        # called directly: short-circuit without bothering gnubg (documented).
        if len(plays) == 1:
            return plays[0]

        self._ensure_connected()
        d1, d2 = dice
        request = board.to_fibs_board((d1, d2))
        self._send_line(request)
        reply = self._read_line()

        target = self._reconcile_key(board, reply)

        # Dance: gnubg signalled "no move" -> referee's single no-op play.
        if target is None:
            for pl in plays:
                if not pl.steps:                 # the no-op play
                    return pl
            raise ValueError(
                "gnubg signalled no move but the referee offered real plays.\n"
                f"  request: {request!r}\n  reply  : {reply!r}"
            )

        for pl in plays:
            if pl.end_board.position_key() == target:
                return pl

        # Could not reconcile -> fail loudly with everything the maintainer needs
        # to re-check the coordinate conversion (do NOT substitute a move).
        raise ValueError(
            "gnubg's move did not match any legal play — re-check the FIBS "
            "coordinate/direction conversion in Board.to_fibs_board and the move "
            "parser (GnubgEngine._reconcile_key). See docs/gnubg-protocol.md.\n"
            f"  request    : {request!r}\n"
            f"  raw reply  : {reply!r}\n"
            f"  reconciled : {target}\n"
            f"  legal keys : {[pl.end_board.position_key() for pl in plays]!r}"
        )

    def _reconcile_key(self, board, reply: str):
        """Apply gnubg's move to a copy of `board`; return the resulting
        position_key, or None if gnubg signalled no legal move.

        The board was sent so that gnubg's point numbering matches ours, so move
        tokens are applied directly in arena coordinates. Returns None only for
        an explicit "no move" so the caller can map it to the no-op play.
        """
        steps = self._parse_move(reply)
        if steps is None:
            return None
        b = board.copy()
        for src, dst in steps:
            b, _ = _apply_step(b, src, dst)
        return b.position_key()

    @staticmethod
    def _parse_move(reply: str):
        """Parse a gnubg move reply into a list of (src, dst) steps in arena
        coordinates, or None for "no move".

        Handles the move shapes gnubg emits over the external interface:
          * an optional leading 'move' keyword
          * space-separated tokens like '24/18', 'bar/20', '6/off'
          * hit marks '*' (ignored; _apply_step recomputes hits)
          * chained hops '13/7/2'  -> 13->7, 7->2
          * multipliers '24/18(2)' -> the hop played twice (doubles)
        The exact reply wording is confirmed by the probe; unrecognised tokens
        raise so a format drift fails loudly instead of silently misplaying.

        Confirmed gnubg 1.07.001 reply formats (commit ``ddb6fcf``):
          move:    ``'8/5 6/5 '``      — trailing space before \\n, stripped by .strip()
          double:  ``'24/18 24/18 13/7 13/7 '``
          dance:   ``''``              — empty string after strip(); maps to None
        """
        text = reply.strip()
        low = text.lower()
        # Explicit "no move" representations (confirm exact token via the probe).
        if low in ("", "no move", "cannot move", "0", "()") or low.startswith("no move"):
            return None
        toks = text.split()
        if toks and toks[0].lower() in ("move", "play"):
            toks = toks[1:]
        if not toks:
            return None

        steps: list[tuple[int, int]] = []
        for tok in toks:
            mult = 1
            if "(" in tok and tok.endswith(")"):
                base, _, n = tok[:-1].partition("(")
                tok = base
                mult = int(n)
            tok = tok.replace("*", "")
            hops = tok.split("/")
            if len(hops) < 2:
                raise ValueError(f"Unparseable gnubg move token: {tok!r} in {reply!r}")
            pairs = []
            for a, b in zip(hops, hops[1:]):
                pairs.append((GnubgEngine._point(a), GnubgEngine._point(b)))
            for _ in range(mult):
                steps.extend(pairs)
        return steps

    @staticmethod
    def _point(s: str) -> int:
        s = s.strip().lower()
        if s in ("bar", "b"):
            return BAR
        if s in ("off", "o"):
            return OFF
        n = int(s)
        # FIBS/our shared numbering: 25 == bar (source), 0 == off (destination).
        if n == 25:
            return BAR
        if n == 0:
            return OFF
        return n

    # ---- lifecycle ------------------------------------------------------
    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
