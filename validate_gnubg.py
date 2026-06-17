"""Validate the GNUbg adapter — the quarantine gate for SPEC-1.

The FIBS-board encoder and move parser in the GNUbg adapter are coded against a
*hypothesised* wire format (the dev box can't run gnubg; see
docs/gnubg-protocol.md). This script is what lifts the quarantine: the adapter is
trusted only when ALL THREE gates below pass on a real (Linux) gnubg —

    1. legality cross-check   (every returned move is a legal Play)
    2. forced-position sanity (gnubg makes the obviously-correct play)
    3. smoke matches          (full games terminate vs Heuristic and Sage)

Legality ALONE is intentionally insufficient: a consistent coordinate flip can
yield legal-but-wrong moves that pass membership while losing every game. Gates
2 and 3 catch that. The process exits non-zero if any gate fails, and exits 0
with a clear message (no failure) if gnubg simply isn't installed/reachable, so
contributors without gnubg aren't blocked.

Run:  python validate_gnubg.py
"""

from __future__ import annotations

import random
import sys
import time

from bgarena import (
    Board, legal_plays, RandomEngine, HeuristicEngine, GnubgEngine,
    duplicate_match,
)
from bgarena.engines import DEFAULT_GNUBG_PORT


# --------------------------------------------------------------------------
# Connectivity / graceful skip
# --------------------------------------------------------------------------
def connect_or_skip() -> GnubgEngine | None:
    """Return a connected GnubgEngine, or None (with a message) to skip."""
    eng = GnubgEngine(connect_timeout=3)  # short: a fast skip for contributors w/o gnubg
    b = Board.starting()
    plays = legal_plays(b, 3, 1)          # a position with many legal plays
    try:
        eng.choose(b, (3, 1), plays, {})  # forces the lazy connect + one exchange
    except ConnectionError as e:
        print("== GNUbg validation SKIPPED (not installed / unreachable) ==")
        print(f"  {e}".replace("\n", "\n  "))
        print("\n  This is not a failure — install gnubg and start the external")
        print(f"  server on port {DEFAULT_GNUBG_PORT} to run the GNUbg gates.")
        eng.close()
        return None
    return eng


# --------------------------------------------------------------------------
# Gate 1: legality cross-check (mirrors validate_sage's random-game walker)
# --------------------------------------------------------------------------
def legality_cross_check(engine: GnubgEngine, n_positions: int = 300, seed: int = 0) -> bool:
    print("== gate 1: legality cross-check ==")
    rng = random.Random(seed)
    advance = RandomEngine(seed=99)       # advance the walk randomly; TEST with gnubg
    checked = 0
    illegal = 0

    while checked < n_positions:
        board = Board.starting()
        d1, d2 = _nondouble_roll(rng)
        for _ in range(400):
            plays = legal_plays(board, d1, d2)
            if len(plays) > 1:
                chosen = engine.choose(board, (d1, d2), plays, {})
                legal_keys = {p.end_board.position_key() for p in plays}
                if chosen.end_board.position_key() not in legal_keys:
                    illegal += 1
                    if illegal <= 3:
                        print(f"  ILLEGAL at dice={d1},{d2}: {chosen.notation()}")
                checked += 1
                if checked >= n_positions:
                    break
            # advance one random ply
            nxt = advance.choose(board, (d1, d2), plays, {}) if len(plays) > 1 else plays[0]
            board = nxt.end_board
            if board.off >= 15:
                break
            board = board.flip()
            d1, d2 = rng.randint(1, 6), rng.randint(1, 6)

    ok = illegal == 0
    print(f"  checked {checked} positions, {illegal} illegal  [{'ok' if ok else 'FAIL'}]\n")
    return ok


def _nondouble_roll(rng: random.Random) -> tuple[int, int]:
    d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
    while d1 == d2:
        d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
    return d1, d2


# --------------------------------------------------------------------------
# Gate 2: forced-position sanity (obviously-correct play, NOT gnubg==Sage)
# --------------------------------------------------------------------------
def _bear_off_two_race() -> tuple[Board, tuple[int, int], str]:
    """Pure race, all home: with 6-5 gnubg must bear two checkers off."""
    b = Board()
    b.points[6] = 2
    b.points[5] = 2
    b.off = 11                                   # 2 + 2 + 11 = 15
    b.points[20] = -2                            # opponent far away: no contact
    b.opp_off = 13                               # 2 + 13 = 15
    return b, (6, 5), "bear off two in a pure race"


def _double_hit() -> tuple[Board, tuple[int, int], str]:
    """Two opponent blots in our home reachable with 4-3: gnubg must double-hit."""
    b = Board()
    b.points[24] = 2
    b.points[13] = 5
    b.points[8] = 3
    b.points[7] = 1
    b.points[6] = 1
    b.points[5] = 3                              # on-roll total = 15
    b.points[4] = -1                             # opponent blot (hit with 7/4, die 3)
    b.points[2] = -1                             # opponent blot (hit with 6/2, die 4)
    b.points[1] = -2
    b.points[12] = -5
    b.points[17] = -3
    b.points[20] = -3                            # opponent total = 15
    return b, (4, 3), "double hit two blots in the home board"


def forced_positions(engine: GnubgEngine) -> bool:
    print("== gate 2: forced-position sanity ==")
    ok = True

    # (a) bear off two
    b, dice, desc = _bear_off_two_race()
    plays = legal_plays(b, *dice)
    assert len(plays) > 1, "test position should offer a real choice"
    chosen = engine.choose(b, dice, plays, {})
    best_off = max(p.end_board.off for p in plays)
    passed = chosen.end_board.off == best_off == 13
    ok &= passed
    print(f"  {desc}: chose {chosen.notation()} (off={chosen.end_board.off}) "
          f"[{'ok' if passed else 'FAIL'}]")

    # (b) double hit
    b, dice, desc = _double_hit()
    plays = legal_plays(b, *dice)
    assert len(plays) > 1, "test position should offer a real choice"
    assert any(p.end_board.opp_bar == 2 for p in plays), "double hit must be legal here"
    chosen = engine.choose(b, dice, plays, {})
    passed = chosen.end_board.opp_bar == 2
    ok &= passed
    print(f"  {desc}: chose {chosen.notation()} (opp_bar={chosen.end_board.opp_bar}) "
          f"[{'ok' if passed else 'FAIL'}]")

    print(f"  forced-position sanity  [{'ok' if ok else 'FAIL'}]\n")
    return ok


# --------------------------------------------------------------------------
# Gate 3: smoke matches (full games terminate; small pairs for gnubg latency)
# --------------------------------------------------------------------------
def smoke_matches(engine: GnubgEngine) -> bool:
    print("== gate 3: smoke matches ==")
    ok = True

    t = time.time()
    m = duplicate_match(engine, HeuristicEngine(name="Heuristic"), pairs=10)
    dt = time.time() - t
    print(f"  {m.a} vs {m.b}: {m.wins_a}-{m.wins_b} over {m.games} games  [{dt:.1f}s]")
    ok &= m.games == 20

    try:
        from bgarena import SageEngine
        sage = SageEngine(level="1ply")
        t = time.time()
        m2 = duplicate_match(engine, sage, pairs=10)
        dt = time.time() - t
        print(f"  {m2.a} vs {m2.b}: {m2.wins_a}-{m2.wins_b} over {m2.games} games  [{dt:.1f}s]")
        ok &= m2.games == 20
    except ImportError:
        print("  (Sage smoke skipped: bgsage not installed)")

    print(f"  smoke matches  [{'ok' if ok else 'FAIL'}]\n")
    return ok


# --------------------------------------------------------------------------
def main() -> None:
    engine = connect_or_skip()
    if engine is None:
        sys.exit(0)                              # skip is not a failure

    try:
        g1 = legality_cross_check(engine)
        g2 = forced_positions(engine)
        g3 = smoke_matches(engine)
    finally:
        engine.close()

    print("== summary ==")
    print(f"  legality cross-check  : {'ok' if g1 else 'FAIL'}")
    print(f"  forced-position sanity: {'ok' if g2 else 'FAIL'}")
    print(f"  smoke matches         : {'ok' if g3 else 'FAIL'}")
    if not (g1 and g2 and g3):
        raise SystemExit("GNUbg validation FAILED — adapter stays quarantined "
                         "(see docs/gnubg-protocol.md)")
    print("\n  ALL GATES PASS — GNUbg adapter verified.")


if __name__ == "__main__":
    main()
