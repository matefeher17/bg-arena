#!/usr/bin/env python3
"""Throwaway protocol probe for GNU Backgammon's external interface.

PURPOSE
    Capture *ground truth* for how gnubg expects a position and how it replies,
    so ``Board.to_fibs_board`` and ``GnubgEngine._parse_move`` can be verified
    (or corrected) before ``validate_gnubg.py`` is run. SPEC-1 requires this to
    run FIRST; the captured exchange is the authoritative parsing spec recorded
    in ``docs/gnubg-protocol.md``.

    This file lives under ``scripts/`` and is EXCLUDED FROM CI's normal jobs.
    The gnubg CI job runs it to (re)capture ground truth on the Linux box where
    a real gnubg exists.

WHY IT'S NOT VERIFIED ON THE DEV MACHINE
    The repo was developed on Windows with no runnable gnubg (GTK app; no
    headless Windows build, no Docker/WSL distro available). The encoders in
    board.py are therefore *hypotheses*. ``Board.to_gnubg_position_id()`` already
    reproduces the canonical starting-position ID ``4HPwATDgc/ABMA`` exactly, so
    that encoder is effectively confirmed; the FIBS ``board:`` line is the part
    this probe must pin down.

USAGE (Linux/macOS, gnubg >= ~1.06)
    python scripts/gnubg_probe.py

    Everything is auto-detected (gnubg via PATH) and fixed by the constants
    below. The script never parses gnubg's reply and never modifies a file — it
    only prints, verbatim, to stdout. Paste its output into the
    ``## Captured exchange`` section of ``docs/gnubg-protocol.md``.

OUTPUT CONTRACT
    stdout must be self-contained: someone reading it offline (without running
    anything) should be able to verify correctness by eye. Every raw byte string
    is shown with ``repr()``; nothing is pretty-printed or truncated.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Prerequisites (checked at IMPORT time, not runtime). Any failure prints a
# clear error and exits 1. Nothing here is swallowed silently.
# ---------------------------------------------------------------------------

if sys.version_info < (3, 10):
    print(f"ERROR: Python >= 3.10 required; running {sys.version.split()[0]}.")
    sys.exit(1)

GNUBG = shutil.which("gnubg")
if GNUBG is None:
    print("ERROR: 'gnubg' not found on PATH.")
    print("Install it with:  apt-get install gnubg   /   brew install gnubg")
    sys.exit(1)
print(f"gnubg binary: {GNUBG}")

# Allow running from the repo root without installing the package.
sys.path.insert(0, ".")
try:
    from bgarena import Board                          # noqa: E402
    from bgarena.engines import _GNUBG_LAUNCH_HELP     # noqa: E402
except ImportError as e:
    print(f"ERROR: cannot import bgarena ({e!r}).")
    print("Install it with:  pip install -e .   (from the repo root)")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HOST = "127.0.0.1"
PORT = 8889          # one above the arena default to avoid colliding with a
                     # running GnubgEngine during development
CONNECT_TIMEOUT = 30.0   # seconds to wait for gnubg to bind the port
IO_TIMEOUT = 10.0        # per send/recv

EXPECTED_PID = "4HPwATDgc/ABMA"   # canonical gnubg starting-position ID


# ---------------------------------------------------------------------------
# Section 1 — version banner
# ---------------------------------------------------------------------------

def section_version() -> None:
    print("== gnubg version ==")
    out = subprocess.run(
        [GNUBG, "--version"], capture_output=True, text=True, timeout=IO_TIMEOUT,
    )
    if out.stdout:
        print(out.stdout, end="" if out.stdout.endswith("\n") else "\n")
    if out.stderr:
        print(out.stderr, end="" if out.stderr.endswith("\n") else "\n")
    print()


# ---------------------------------------------------------------------------
# Section 2 — Position ID round-trip
# ---------------------------------------------------------------------------

def section_position_id() -> tuple[bool, str]:
    """Confirm our Position ID is accepted by gnubg; return (ok, computed)."""
    print("== Position ID round-trip ==")
    pid = Board.starting().to_gnubg_position_id()
    print(f"computed: {pid}")
    ok = pid == EXPECTED_PID
    print("[ok]" if ok else f"[FAIL — expected {EXPECTED_PID}]")

    script = f"set board {pid}\nshow board\nquit\n"
    out = subprocess.run(
        [GNUBG, "-t", "-q"], input=script, capture_output=True, text=True,
        timeout=CONNECT_TIMEOUT,
    )
    # Print verbatim with repr() so whitespace / CR / LF is visible. We do NOT
    # parse this — the operator reads it and reconciles by eye.
    print("gnubg output (repr):")
    print(repr(out.stdout))
    if out.stderr:
        print("gnubg stderr (repr):")
        print(repr(out.stderr))
    print()
    return ok, pid


# ---------------------------------------------------------------------------
# Section 3 — FIBS socket exchange
# ---------------------------------------------------------------------------

def _bar_position() -> Board:
    """The bar position from tests_demo.py invariant check 4 (forced re-entry).

    Bar checker, blocked entry on die 5 (point 20) and die 2 (point 23).
    """
    b = Board()
    b.bar = 1
    b.points[6] = 4
    b.points[20] = -2   # blocks entry with die 5 (25 - 5 = 20)
    b.points[23] = -2   # blocks entry with die 2 (25 - 2 = 23)
    return b


# (id, description, board factory, dice)
TEST_CASES = [
    ("A", "starting, 3-1", Board.starting, (3, 1)),
    ("B", "starting, 6-6", Board.starting, (6, 6)),
    ("C", "bar, 5-2", _bar_position, (5, 2)),
]


def _spawn_and_connect() -> tuple[subprocess.Popen, socket.socket]:
    """Spawn a fresh gnubg, ask it to serve `external HOST:PORT`, and connect.

    Polls create_connection every 0.5 s up to CONNECT_TIMEOUT. Raises on
    failure (after cleaning up the process) so the caller can print the
    launch-help string.
    """
    proc = subprocess.Popen(
        [GNUBG, "-t", "-q"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True,
    )
    assert proc.stdin is not None
    proc.stdin.write(f"external {HOST}:{PORT}\n")
    proc.stdin.flush()

    deadline = time.time() + CONNECT_TIMEOUT
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            s = socket.create_connection((HOST, PORT), timeout=0.5)
            s.settimeout(IO_TIMEOUT)
            return proc, s
        except OSError as e:                 # not bound yet / refused -> retry
            last_err = e
            time.sleep(0.5)

    _terminate(proc)
    raise ConnectionError(
        f"gnubg never bound {HOST}:{PORT} within {CONNECT_TIMEOUT}s "
        f"(last error: {last_err!r})"
    )


def _recv_until_newline(sock: socket.socket) -> bytes:
    """Read raw bytes until the first '\\n' or the socket closes."""
    buf = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:                        # server closed
            break
        buf.extend(chunk)
        if b"\n" in chunk:
            break
    return bytes(buf)


def _terminate(proc: subprocess.Popen | None) -> None:
    """SIGTERM, wait up to 5 s, then SIGKILL."""
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_socket_case(case_id: str, desc: str, factory, dice) -> Exception | None:
    """Run one test case with a FRESH gnubg process + FRESH socket.

    Returns None on success, or the exception that was raised (also printed
    inline, never suppressed).
    """
    print(f"-- case {case_id} ({desc}) --")
    proc: subprocess.Popen | None = None
    sock: socket.socket | None = None
    try:
        proc, sock = _spawn_and_connect()

        board = factory()
        request = board.to_fibs_board(dice)
        print(f"request: {request}")
        sock.sendall((request + "\n").encode("ascii"))

        raw = _recv_until_newline(sock)
        print(f"raw reply (repr): {raw!r}")
        print(f"decoded reply: {raw.decode('ascii', 'replace')}")
        print()
        return None
    except Exception as e:
        # Connection failures get the exact launch fix; everything is printed.
        if isinstance(e, (ConnectionError, OSError, TimeoutError)):
            print(_GNUBG_LAUNCH_HELP.format(host=HOST, port=PORT, err=repr(e)))
        print(f"[FAIL: {e!r}]")
        print()
        return e
    finally:
        if sock is not None:
            sock.close()
        _terminate(proc)


# ---------------------------------------------------------------------------
# Section 4 — summary
# ---------------------------------------------------------------------------

def main() -> int:
    # Each section is wrapped so a failure in one does not stop the others.
    try:
        section_version()
    except Exception as e:
        print(f"[FAIL: {e!r}]\n")

    pid_ok = False
    pid_value = "?"
    pid_err: Exception | None = None
    try:
        pid_ok, pid_value = section_position_id()
    except Exception as e:
        pid_err = e
        print(f"[FAIL: {e!r}]\n")

    print("== FIBS socket exchange ==")
    case_errs: dict[str, Exception | None] = {}
    for case_id, desc, factory, dice in TEST_CASES:
        try:
            case_errs[case_id] = run_socket_case(case_id, desc, factory, dice)
        except Exception as e:                # belt-and-braces; case owns its own
            print(f"[FAIL: {e!r}]\n")
            case_errs[case_id] = e
    print()

    # ---- summary ----
    print("== summary ==")
    all_ok = True
    for case_id, desc, _factory, _dice in TEST_CASES:
        err = case_errs.get(case_id, RuntimeError("case did not run"))
        ok = err is None
        all_ok = all_ok and ok
        label = f"case {case_id} ({desc}):"
        status = "[ok]" if ok else f"[FAIL: {err!r}]"
        print(f"{label:<23}  request sent, reply captured  {status}")

    pid_label = "Position ID round-trip:"
    if pid_err is not None:
        all_ok = False
        print(f"{pid_label:<23}  [FAIL: {pid_err!r}]")
    elif pid_ok:
        print(f"{pid_label:<23}  computed {pid_value}  [ok]")
    else:
        all_ok = False
        print(f"{pid_label:<23}  computed {pid_value}  [FAIL — expected {EXPECTED_PID}]")

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
