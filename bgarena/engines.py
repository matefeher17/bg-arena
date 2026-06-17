"""Engine adapters.

Every competitor implements one method: given the position (always from its own
perspective), the dice, and the list of legal plays, return the play it wants.
The referee owns all state, so engines can be completely stateless — which is
exactly how Wildbg's API already works and makes the whole arena parallelisable.
"""

from __future__ import annotations

import json
import random
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod

from .board import Board, NUM_POINTS
from .moves import Play


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


class GnubgEngine(Engine):
    """STUB. Two viable integrations:

    1. Drive the CLI: `set board <PositionID>` then `hint`, parse the top move.
    2. Use gnubg's external socket mode (send a FIBS-format board, read the
       decision) — cleaner for a long-running arena.
    """

    name = "GNUbg"

    def choose(self, board, dice, plays, context):
        raise NotImplementedError("Wire gnubg via CLI `hint` or its external socket.")
