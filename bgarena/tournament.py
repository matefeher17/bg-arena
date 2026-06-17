"""Contender tournament.

The standings metric is win rate from head-to-head play. PR (Performance
Rating, the standard backgammon skill number) is the better metric and slots in
once XG or a rollout judge is wired up — the per-game position logs are already
captured for exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .game import play_game, WHITE, BLACK


@dataclass
class MatchResult:
    a: str
    b: str
    wins_a: int = 0
    wins_b: int = 0

    @property
    def games(self) -> int:
        return self.wins_a + self.wins_b


def duplicate_match(engine_a, engine_b, pairs: int, base_seed: int = 1) -> MatchResult:
    """Play `pairs` duplicate-dice game pairs (so 2 * pairs games total).

    For each pair the same dice are dealt to both orientations, with the
    engines swapping colours — cancelling most of backgammon's variance.
    """
    res = MatchResult(a=engine_a.name, b=engine_b.name)
    for k in range(pairs):
        seed = base_seed + k

        g1 = play_game(engine_a, engine_b, seed=seed)          # A=white, B=black
        if g1.winner == WHITE:
            res.wins_a += 1
        else:
            res.wins_b += 1

        g2 = play_game(engine_b, engine_a, seed=seed)          # B=white, A=black
        if g2.winner == WHITE:
            res.wins_b += 1
        else:
            res.wins_a += 1
    return res


@dataclass
class Standing:
    name: str
    wins: int = 0
    games: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0


def round_robin(engines: list, pairs: int, base_seed: int = 1):
    """Every engine plays every other; returns standings sorted by win rate."""
    table = {e.name: Standing(name=e.name) for e in engines}
    results = []
    for i in range(len(engines)):
        for j in range(i + 1, len(engines)):
            m = duplicate_match(engines[i], engines[j], pairs=pairs, base_seed=base_seed)
            results.append(m)
            table[m.a].wins += m.wins_a
            table[m.a].games += m.games
            table[m.b].wins += m.wins_b
            table[m.b].games += m.games
    standings = sorted(table.values(), key=lambda s: s.win_rate, reverse=True)
    return standings, results


def format_standings(standings) -> str:
    lines = [f"{'rank':<5}{'engine':<14}{'games':>7}{'wins':>7}{'win%':>8}"]
    lines.append("-" * 41)
    for rank, s in enumerate(standings, 1):
        lines.append(f"{rank:<5}{s.name:<14}{s.games:>7}{s.wins:>7}{100*s.win_rate:>7.1f}%")
    return "\n".join(lines)
