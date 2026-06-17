"""Run a head-to-head round-robin between Sage, GNUbg, and Heuristic.

Prints standings plus per-matchup results. Expects a gnubg external server
already listening on the arena default port (the CI job starts it with
``printf 'external localhost:8888\\n' | gnubg -t -q &``).
"""

import sys
import time

# Allow running from the repo root without installing the package.
sys.path.insert(0, ".")

from bgarena import (                                          # noqa: E402
    GnubgEngine, SageEngine, HeuristicEngine, round_robin, format_standings,
)

PAIRS = 50  # 50 duplicate-dice pairs = 100 games per matchup


def main() -> None:
    print("== contender round-robin ==")
    print("   pairs per matchup : 50 (100 games)")
    print("   engines           : Sage-1ply, GNUbg, Heuristic")
    print()

    field = [
        SageEngine(level="1ply", name="Sage-1ply"),
        GnubgEngine(name="GNUbg"),
        HeuristicEngine(name="Heuristic"),
    ]

    t0 = time.time()
    standings, results = round_robin(field, pairs=PAIRS)
    dt = time.time() - t0

    print(format_standings(standings))
    print(f"\ntotal time: {dt:.1f}s")

    print("\n== head-to-head results ==")
    for m in results:
        pct = 100.0 * m.wins_a / m.games
        print(f"  {m.a:<12} vs {m.b:<12}  {m.wins_a}-{m.wins_b}  ({pct:.1f}% {m.a})")

    for e in field:
        if hasattr(e, "close"):
            e.close()


if __name__ == "__main__":
    main()
