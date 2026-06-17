#!/usr/bin/env python3
"""Throwaway protocol probe for GNU Backgammon's external interface.

PURPOSE
    Capture *ground truth* for how gnubg expects a position and how it replies,
    so the parser in ``bgarena/engines.py`` is written against real output rather
    than from memory. SPEC-1 requires this to run FIRST; the captured exchange is
    the authoritative parsing spec recorded in ``docs/gnubg-protocol.md``.

    This file lives under ``scripts/`` and is EXCLUDED FROM CI's normal jobs. The
    gnubg CI job runs it to (re)capture ground truth on the Linux box where a real
    gnubg exists.

WHY IT'S NOT VERIFIED ON THE DEV MACHINE
    The repo was developed on Windows with no runnable gnubg (GTK app; no headless
    Windows build, no Docker/WSL distro available). The encoders in board.py are
    therefore *hypotheses*. Note: ``Board.to_gnubg_position_id()`` already
    reproduces the canonical starting-position ID ``4HPwATDgc/ABMA`` exactly, so
    that encoder is effectively confirmed; the FIBS ``board:`` line (direction /
    colour / home / bar fields) is the part this probe must pin down.

USAGE (Linux/macOS, gnubg >= ~1.06)
    python scripts/gnubg_probe.py                 # auto-launch server + probe
    python scripts/gnubg_probe.py --host H --port P --no-launch   # external server
    python scripts/gnubg_probe.py --gnubg /path/to/gnubg

WHAT IT DOES
    1. Position ID round-trip (does not need the socket): feeds our Position ID to
       `gnubg -t` and reads the position back, asserting gnubg echoes the same ID.
    2. Socket exchange: launches `external <port>`, connects, sends the FIBS board
       for the starting position with dice 3,1, and prints gnubg's raw reply
       VERBATIM (repr) so whitespace/handshake quirks are visible.

After running, paste the captured output into docs/gnubg-protocol.md and adjust
Board.to_fibs_board / GnubgEngine._parse_move if reality differs from the
hypothesis. Do NOT trust the adapter until all three gates in validate_gnubg.py
pass (legality + forced-position + smoke), not legality alone.
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
import time

# Allow running from the repo root without installing the package.
sys.path.insert(0, ".")
from bgarena import Board                          # noqa: E402
from bgarena.engines import DEFAULT_GNUBG_PORT     # noqa: E402


def position_id_round_trip(gnubg: str) -> None:
    """Feed our Position ID into gnubg and read it back; assert they match."""
    b = Board.starting()
    our_id = b.to_gnubg_position_id()
    print("== Position ID round-trip ==")
    print(f"  our starting Position ID : {our_id}")
    print("  (canonical gnubg value   : 4HPwATDgc/ABMA)")

    script = f"set board {our_id}\nshow board\nquit\n"
    try:
        out = subprocess.run(
            [gnubg, "-t", "-q"], input=script, capture_output=True,
            text=True, timeout=60,
        )
    except FileNotFoundError:
        print(f"  SKIP: gnubg not found at {gnubg!r}")
        return
    print("  ---- gnubg stdout (verbatim) ----")
    print(out.stdout)
    if out.stderr.strip():
        print("  ---- gnubg stderr ----")
        print(out.stderr)
    # gnubg's `show board` prints a line like "Position ID: <id>".
    echoed = None
    for line in out.stdout.splitlines():
        if "position id" in line.lower():
            echoed = line.split(":", 1)[1].strip()
            break
    print(f"  echoed Position ID       : {echoed}")
    print(f"  ROUND-TRIP {'OK' if echoed == our_id else 'MISMATCH — fix to_gnubg_position_id'}\n")


def socket_exchange(host: str, port: int, gnubg: str, launch: bool) -> None:
    print("== Socket exchange (external interface) ==")
    proc = None
    if launch:
        cmd = [gnubg, "-t", "-q"]
        print(f"  launching: {' '.join(cmd)}  then  external localhost:{port}")
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
        )
        assert proc.stdin is not None
        proc.stdin.write(f"external localhost:{port}\n")
        proc.stdin.flush()
        time.sleep(2.0)                            # let it bind the port

    b = Board.starting()
    request = b.to_fibs_board((3, 1))
    print(f"  request line (FIBS board):\n    {request!r}")
    try:
        with socket.create_connection((host, port), timeout=30) as s:
            s.settimeout(30)
            s.sendall((request + "\n").encode("ascii"))
            time.sleep(0.5)
            data = s.recv(65536)
        print("  ---- gnubg raw reply (repr) ----")
        print(f"    {data!r}")
        print("  ---- decoded ----")
        print(data.decode("ascii", "replace"))
    except OSError as e:
        print(f"  ERROR connecting/exchanging: {e}")
        print("  (Is the external server up? Try --no-launch with a manually started server.)")
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="gnubg external-interface protocol probe")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=DEFAULT_GNUBG_PORT)
    ap.add_argument("--gnubg", default="gnubg", help="path to the gnubg binary")
    ap.add_argument("--no-launch", action="store_true",
                    help="connect to an already-running external server")
    args = ap.parse_args()

    position_id_round_trip(args.gnubg)
    socket_exchange(args.host, args.port, args.gnubg, launch=not args.no_launch)


if __name__ == "__main__":
    main()
