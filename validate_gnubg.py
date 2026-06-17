"""Three-gate validation for GnubgEngine: legal, correct, and competitive.

All three gates must pass before ``continue-on-error: true`` is removed from
the ``gnubg`` CI job and ``GnubgEngine`` joins the contender round-robin:

    gate 1  legality cross-check   — every move gnubg plays is one the referee
                                      considers legal (membership by resulting
                                      position).
    gate 2  forced-position sanity — on positions with a single unambiguous
                                      best play, gnubg plays the *right* move,
                                      not merely a legal one. Catches a
                                      consistent coordinate flip that would
                                      sail through gate 1 while losing.
    gate 3  smoke matches          — gnubg beats Random clearly and stays
                                      competitive with Heuristic.

Mirrors the structure of ``validate_sage.py`` (cross-validate + real matches).
Expects a gnubg external server already listening on the arena default port
(the CI job starts ``printf 'external localhost:8888\\n' | gnubg -t -q &``).
"""

from __future__ import annotations

import random
import shutil
import sys
import time

# ---------------------------------------------------------------------------
# Prerequisites (checked at IMPORT time, same as scripts/gnubg_probe.py). Any
# failure prints a clear message and exits 1.
# ---------------------------------------------------------------------------

if sys.version_info < (3, 10):
    print(f"ERROR: Python >= 3.10 required; running {sys.version.split()[0]}.")
    sys.exit(1)

GNUBG = shutil.which("gnubg")
if GNUBG is None:
    print("ERROR: 'gnubg' not found on PATH.")
    print("Install it with:  apt-get install gnubg   /   brew install gnubg")
    sys.exit(1)

# Allow running from the repo root without installing the package.
sys.path.insert(0, ".")
try:
    from bgarena import (                                   # noqa: E402
        Board, legal_plays, RandomEngine, HeuristicEngine, GnubgEngine,
        duplicate_match,
    )
except ImportError as e:
    print(f"ERROR: cannot import bgarena ({e!r}).")
    print("Install it with:  pip install -e .   (from the repo root)")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAIRS        = 25     # duplicate-dice pairs per match (50 games)
BASE_SEED    = 42
LEGALITY_N   = 200    # positions to cross-check in gate 1


# ---------------------------------------------------------------------------
# Gate 1 — legality cross-check
# ---------------------------------------------------------------------------

def gate1_legality() -> bool:
    """Every move gnubg returns must be one of the referee's legal plays."""
    print("== gate 1: legality cross-check ==")
    try:
        rng = random.Random(BASE_SEED)
        r1, r2 = RandomEngine(seed=1), RandomEngine(seed=2)
        checked = 0
        violations = 0

        with GnubgEngine() as gnu:
            # Walk random games and test the live roll at each position (same
            # walk as validate_sage.py::cross_validate).
            while checked < LEGALITY_N:
                board = Board.starting()
                d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
                while d1 == d2:                       # legal opening is non-double
                    d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
                on_roll_engine = r1
                for _ in range(200):
                    plays = legal_plays(board, d1, d2)
                    legal_keys = {p.end_board.position_key() for p in plays}

                    chosen = gnu.choose(board, (d1, d2), plays, {})
                    if chosen.end_board.position_key() not in legal_keys:
                        violations += 1
                        if violations <= 3:
                            print(f"  VIOLATION at dice={d1},{d2}")
                            print(f"    board       : {board.position_key()}")
                            print(f"    returned key: {chosen.end_board.position_key()}")
                            print(f"    legal keys  : {legal_keys}")

                    checked += 1
                    if checked >= LEGALITY_N:
                        break

                    # advance the game one (random) ply
                    nxt = (on_roll_engine.choose(board, (d1, d2), plays, {})
                           if len(plays) > 1 else plays[0])
                    board = nxt.end_board
                    if board.off >= 15:
                        break
                    board = board.flip()
                    on_roll_engine = r2 if on_roll_engine is r1 else r1
                    d1, d2 = rng.randint(1, 6), rng.randint(1, 6)

        ok = violations == 0
        print(f"  checked {checked} positions, {violations} violations  "
              f"[{'ok' if ok else 'FAIL'}]\n")
        return ok
    except Exception as e:
        print(f"  [FAIL: {e!r}]\n")
        return False


# ---------------------------------------------------------------------------
# Gate 2 — forced-position sanity
# ---------------------------------------------------------------------------

def _forced_bear_off() -> Board:
    """One checker on the ace point, 14 already off. Dice 1-1 -> 1/off; game over."""
    b = Board()
    b.points[1] = 1
    b.off = 14
    return b


def _forced_hit() -> Board:
    """Our checker on 20, a lone opponent blot on 14, the rest of our checkers
    parked. Dice 6-6 forces 20/14* (the only legal six) so the blot is hit."""
    b = Board()
    b.points[20] = 1     # our checker
    b.points[14] = -1    # lone opponent blot
    b.points[6] = 14     # rest of our checkers (irrelevant to the forced six)
    return b


def _forced_bar_entry() -> Board:
    """Checker on the bar; die 5 blocked (point 20), point 23 open so die 2
    must enter. Dice 5-2 -> the checker comes in off the bar."""
    b = Board()
    b.bar = 1
    b.points[6] = 4
    b.points[20] = -2    # blocks entry with die 5 (25 - 5 = 20)
    # point 23 is open — die 2 can enter
    return b


def gate2_forced() -> bool:
    """gnubg must pick the *right* move on three single-answer positions."""
    print("== gate 2: forced-position sanity ==")

    # (label, board factory, dice, check(end_board)->bool, value(end_board)->str)
    cases = [
        ("2a (forced bear-off):",
         _forced_bear_off, (1, 1),
         lambda eb: eb.off == 15,
         lambda eb: f"off={eb.off}"),
        ("2b (forced hit):",
         _forced_hit, (6, 6),
         lambda eb: eb.opp_bar >= 1,
         lambda eb: f"opp_bar={eb.opp_bar}"),
        ("2c (forced bar entry):",
         _forced_bar_entry, (5, 2),
         lambda eb: eb.bar == 0,
         lambda eb: f"bar={eb.bar}"),
    ]

    all_ok = True
    try:
        with GnubgEngine() as gnu:
            for label, factory, dice, check, value_of in cases:
                try:
                    board = factory()
                    plays = legal_plays(board, *dice)
                    chosen = gnu.choose(board, dice, plays, {})
                    eb = chosen.end_board
                    ok = check(eb)
                    status = "[ok]" if ok else "[FAIL]"
                    print(f"  {label:<22} {value_of(eb):<14} {status}")
                    all_ok = all_ok and ok
                except Exception as e:
                    all_ok = False
                    print(f"  {label:<22} [FAIL: {e!r}]")
    except Exception as e:
        print(f"  [FAIL: {e!r}]")
        all_ok = False

    print()
    return all_ok


# ---------------------------------------------------------------------------
# Gate 3 — smoke matches
# ---------------------------------------------------------------------------

def _run_match(opponent, threshold: float) -> tuple[bool, str]:
    """Play one duplicate match GNUbg vs `opponent`; return (passed, line)."""
    t = time.time()
    with GnubgEngine() as gnu:
        m = duplicate_match(gnu, opponent, pairs=PAIRS, base_seed=BASE_SEED)
    dt = time.time() - t

    rate = 100.0 * m.wins_a / m.games if m.games else 0.0
    ok = rate > threshold
    score = f"{m.wins_a}-{m.wins_b}"
    pct = f"{rate:.1f}%"
    label = f"GNUbg vs {m.b}:"
    line = (f"  {label:<19} {score:<5} over {m.games} games "
            f"({pct:<6} GNUbg)  [{'ok' if ok else 'FAIL'}]   [{dt:.1f}s]")
    return ok, line


def gate3_matches() -> bool:
    """GNUbg must beat Random clearly and stay competitive with Heuristic."""
    print("== gate 3: smoke matches ==")
    try:
        ok_random, line_random = _run_match(RandomEngine(seed=5, name="Random"), 70.0)
        print(line_random)
        ok_heur, line_heur = _run_match(HeuristicEngine(name="Heuristic"), 55.0)
        print(line_heur)
        print()
        return ok_random and ok_heur
    except Exception as e:
        print(f"  [FAIL: {e!r}]\n")
        return False


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(ok1: bool, ok2: bool, ok3: bool) -> None:
    print("== summary ==")
    for label, ok in (
        ("gate 1 (legality):", ok1),
        ("gate 2 (forced positions):", ok2),
        ("gate 3 (smoke matches):", ok3),
    ):
        print(f"{label:<27}{'[ok]' if ok else '[FAIL]'}")

    if ok1 and ok2 and ok3:
        print("All gates passed. GnubgEngine is ready for the contender round-robin.")
        print("Remove `continue-on-error` from the gnubg CI job.")
    else:
        n_failed = sum(1 for ok in (ok1, ok2, ok3) if not ok)
        print(f"{n_failed} gate(s) failed. Do not promote GnubgEngine.")


if __name__ == "__main__":
    ok1 = gate1_legality()
    ok2 = gate2_forced()
    ok3 = gate3_matches()
    print_summary(ok1, ok2, ok3)
    sys.exit(0 if (ok1 and ok2 and ok3) else 1)
