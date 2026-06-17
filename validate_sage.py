"""Validate bgarena's move generator against Sage's, then play real matches."""

import random
import time

import bgsage
from bgarena import (
    Board, legal_plays, play_game, RandomEngine, HeuristicEngine, SageEngine,
    duplicate_match, WHITE, BLACK,
)


def cross_validate(n_positions=400, seed=0):
    """For many (position, dice) samples, the SET of legal resulting boards
    must be identical between bgarena and bgsage. This independently checks
    both move generators at once."""
    print("== cross-validating move generation vs bgsage ==")
    rng = random.Random(seed)
    r1, r2 = RandomEngine(seed=1), RandomEngine(seed=2)
    checked = 0
    mismatches = 0

    # Walk random games and test the live roll at each position.
    while checked < n_positions:
        board = Board.starting()
        # random opening
        d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
        while d1 == d2:
            d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
        on_roll_engine = r1
        for _ in range(200):
            mine = {tuple(p.end_board.to_sage()) for p in legal_plays(board, d1, d2)}
            sage = {tuple(b) for b in bgsage.possible_moves(board.to_sage(), d1, d2)}
            if not sage:                       # bgsage: empty == dance
                sage = {tuple(board.to_sage())}  # ours: a single no-op play
            if mine != sage:
                mismatches += 1
                if mismatches <= 3:
                    print(f"  MISMATCH dice={d1},{d2}")
                    print(f"    only in bgarena: {mine - sage}")
                    print(f"    only in bgsage : {sage - mine}")
            checked += 1
            if checked >= n_positions:
                break
            # advance the game one (random) ply
            plays = legal_plays(board, d1, d2)
            board = on_roll_engine.choose(board, (d1, d2), plays, {}) if len(plays) > 1 else plays[0]
            board = board.end_board if hasattr(board, "end_board") else board
            if board.off >= 15:
                break
            board = board.flip()
            on_roll_engine = r2 if on_roll_engine is r1 else r1
            d1, d2 = rng.randint(1, 6), rng.randint(1, 6)

    print(f"  checked {checked} positions, {mismatches} mismatches  "
          f"[{'ok' if mismatches == 0 else 'FAIL'}]\n")
    return mismatches == 0


def real_matches():
    print("== Sage in the arena (real games) ==")
    sage = SageEngine(level="1ply")
    print(f"  engine ready: {sage.name}")

    t = time.time()
    m = duplicate_match(sage, RandomEngine(seed=5, name="Random"), pairs=25)
    dt = time.time() - t
    print(f"  {m.a} vs {m.b}: {m.wins_a}-{m.wins_b} over {m.games} games "
          f"({100*m.wins_a/m.games:.1f}% Sage)  [{dt:.1f}s]")

    t = time.time()
    m2 = duplicate_match(sage, HeuristicEngine(name="Heuristic"), pairs=25)
    dt = time.time() - t
    print(f"  {m2.a} vs {m2.b}: {m2.wins_a}-{m2.wins_b} over {m2.games} games "
          f"({100*m2.wins_a/m2.games:.1f}% Sage)  [{dt:.1f}s]")


if __name__ == "__main__":
    ok = cross_validate()
    real_matches()
    if not ok:
        raise SystemExit("move-generation mismatch detected")
