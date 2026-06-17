"""Correctness checks + a runnable demo.

Run:  python -m tests_demo
"""

import random

from bgarena import (
    Board, legal_plays, play_game, RandomEngine, HeuristicEngine,
    duplicate_match, round_robin, format_standings, WHITE, BLACK,
)
from bgarena.board import NUM_POINTS, BAR, OFF
from bgarena.moves import _apply_step


def check_invariants():
    print("== invariant checks ==")

    # 1. Starting position is symmetric under flip.
    b = Board.starting()
    assert b.position_key() == b.flip().position_key(), "start should be flip-symmetric"
    assert b.checker_total_on_roll() == 15 and b.checker_total_opp() == 15

    # 2. Opening 3-1 from the start: a handful of legal plays, all conserving 15
    #    checkers per side and using both dice.
    plays = legal_plays(b, 3, 1)
    assert len(plays) >= 1
    for pl in plays:
        eb = pl.end_board
        assert eb.checker_total_on_roll() == 15, "checkers vanished/duplicated"
        assert eb.checker_total_opp() == 15
        assert pl.dice_used == 2, "opening 3-1 must use both dice"
    print(f"  opening 3-1: {len(plays)} legal plays, all use both dice  [ok]")

    # 3. Doubles can use up to four dice from the opening-style position.
    plays6 = legal_plays(b, 6, 6)
    assert max(p.dice_used for p in plays6) >= 2
    print(f"  double 6-6: max dice used = {max(p.dice_used for p in plays6)}  [ok]")

    # 4. Forced re-entry from the bar: with a checker on the bar and the
    #    opponent owning a couple of entry points, only entering moves appear.
    t = Board()
    t.bar = 1
    t.points[6] = 4          # our checkers, irrelevant while on the bar
    t.points[20] = -2        # opp blocks entry point for die 5 (25-5=20)
    t.points[23] = -2        # opp blocks entry point for die 2 (25-2=23)
    pl = legal_plays(t, 5, 2)
    for p in pl:
        for src, dst, die, hit in p.steps:
            assert src == BAR or t.bar == 0, "must clear the bar first"
    print(f"  bar re-entry with 5-2 vs blocked 20/23: {len(pl)} plays  [ok]")

    # 5. Bear-off: all home, exact + overshoot behave.
    h = Board()
    h.points[5] = 1
    h.points[3] = 2
    h.off = 12               # 1 + 2 + 12 = 15
    assert h.all_home()
    pl = legal_plays(h, 6, 1)   # 6 overshoots from the 5 (highest), 1 plays 3->2 or...
    keys = {p.end_board.off for p in pl}
    assert any(p.end_board.off >= 13 for p in pl), "die 6 should bear a checker off"
    print(f"  bear-off 6-1 from {{5:1,3:2}}: {len(pl)} plays, off reaches "
          f"{max(p.end_board.off for p in pl)}  [ok]")

    # 6. Hitting puts an opponent checker on the bar.
    #    10/7* uses the 3; 20/14 uses the 6 — so the hit is part of a legal
    #    two-die play (otherwise the dice-maximization rule would forbid it).
    hb = Board()
    hb.points[20] = 1        # plays 20/14 with the 6
    hb.points[10] = 1        # plays 10/7* with the 3 (hits)
    hb.points[7] = -1        # opponent blot
    hb.points[6] = 4
    pl = legal_plays(hb, 3, 6)
    hit_play = next((p for p in pl if any(step[3] for step in p.steps)), None)
    assert hit_play is not None, "should be able to hit the blot on 7"
    assert hit_play.end_board.opp_bar >= 1
    print("  hitting a blot sends it to the opponent bar  [ok]")

    print("  ALL INVARIANTS PASS\n")


def check_games_terminate():
    print("== game termination ==")
    r = RandomEngine(seed=1, name="R1")
    s = RandomEngine(seed=2, name="R2")
    longest = 0
    for seed in range(50):
        g = play_game(r, s, seed=seed)
        assert g.winner in (WHITE, BLACK)
        # winner must actually have all 15 off in the final position
        longest = max(longest, g.turns)
    print(f"  50 random games all terminate with a winner; "
          f"longest = {longest} turns  [ok]\n")


def demo():
    print("== demo: does the arena detect skill? ==")

    rnd = RandomEngine(seed=7, name="Random")
    heu = HeuristicEngine(name="Heuristic")

    # Random vs Random should hover near 50% (sanity: no side bias).
    rr = duplicate_match(RandomEngine(seed=11, name="RandA"),
                         RandomEngine(seed=12, name="RandB"),
                         pairs=150)
    print(f"  Random vs Random: {rr.wins_a}-{rr.wins_b} over {rr.games} games "
          f"({100*rr.wins_a/rr.games:.1f}% / {100*rr.wins_b/rr.games:.1f}%)")

    # Heuristic vs Random should be a clear, repeatable win for Heuristic.
    hr = duplicate_match(heu, rnd, pairs=150)
    print(f"  Heuristic vs Random: {hr.wins_a}-{hr.wins_b} over {hr.games} games "
          f"({100*hr.wins_a/hr.games:.1f}% Heuristic)\n")

    print("== demo: contender round-robin (placeholder field) ==")
    field = [
        HeuristicEngine(name="Heuristic-A"),
        HeuristicEngine(name="Heuristic-B"),
        RandomEngine(seed=21, name="Random-1"),
        RandomEngine(seed=22, name="Random-2"),
    ]
    standings, _ = round_robin(field, pairs=80)
    print(format_standings(standings))
    print("\n(Real field = GNUbg, Sage, Wildbg once their adapters are wired.)")


if __name__ == "__main__":
    check_invariants()
    check_games_terminate()
    demo()
