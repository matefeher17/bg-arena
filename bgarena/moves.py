"""Legal play generation for backgammon.

The hard part of a correct arena is enforcing the real movement rules so that
engines are never handed an illegal position:

* You must enter from the bar before doing anything else.
* You may bear off a checker on point n with a die of exactly n, or with a
  higher die if no checker sits on a higher home point.
* You must play as many dice as legally possible. For a non-double, if only
  one die can be played, you must play the higher one when that is possible.

A "play" is a complete legal turn: a sequence of single-die steps plus the
resulting board (in on-roll perspective, before the turn is handed over).
"""

from __future__ import annotations

from dataclasses import dataclass

from .board import Board, BAR, OFF, NUM_POINTS


@dataclass
class Play:
    steps: list[tuple]      # list of (src, dst, die, hit) in the order played
    end_board: Board        # resulting position, on-roll perspective (pre-flip)

    @property
    def dice_used(self) -> int:
        return len(self.steps)

    def notation(self) -> str:
        if not self.steps:
            return "(cannot move)"
        parts = []
        for src, dst, die, hit in self.steps:
            s = "bar" if src == BAR else str(src)
            d = "off" if dst == OFF else str(dst)
            parts.append(f"{s}/{d}" + ("*" if hit else ""))
        return " ".join(parts)


def _single_die_steps(b: Board, die: int) -> list[tuple]:
    """All legal single-checker steps for one die from board `b`."""
    steps: list[tuple] = []

    # 1) Must enter from the bar first.
    if b.bar > 0:
        dst = (NUM_POINTS + 1) - die  # 25 - die  -> 19..24
        if b.points[dst] >= -1:       # empty, ours, or a lone opponent blot
            steps.append((BAR, dst))
        return steps

    # 2) Normal moves (high -> low, landing on a point).
    for src in range(1, NUM_POINTS + 1):
        if b.points[src] >= 1:
            dst = src - die
            if dst >= 1 and b.points[dst] >= -1:
                steps.append((src, dst))

    # 3) Bearing off (only when every checker is home).
    if b.all_home():
        if 1 <= die <= 6 and b.points[die] >= 1:
            steps.append((die, OFF))                 # exact
        else:
            highest = max((p for p in range(1, 7) if b.points[p] >= 1), default=0)
            if highest >= 1 and die > highest:
                steps.append((highest, OFF))         # overshoot

    return steps


def _apply_step(b: Board, src: int, dst: int) -> tuple[Board, bool]:
    nb = b.copy()
    hit = False
    if src == BAR:
        nb.bar -= 1
    else:
        nb.points[src] -= 1
    if dst == OFF:
        nb.off += 1
    else:
        if nb.points[dst] == -1:     # hit a lone opponent blot
            nb.points[dst] = 0
            nb.opp_bar += 1
            hit = True
        nb.points[dst] += 1
    return nb, hit


def _explore(b: Board, dice_left: list[int]):
    """Return every maximal line as (end_board, steps).

    A line is maximal when no remaining die can be played from its end.
    """
    results = []
    any_playable = False
    seen_values = set()
    for i, die in enumerate(dice_left):
        if die in seen_values:        # identical dice (doubles) -> one branch
            continue
        seen_values.add(die)
        for (src, dst) in _single_die_steps(b, die):
            any_playable = True
            nb, hit = _apply_step(b, src, dst)
            rest = dice_left[:i] + dice_left[i + 1:]
            for (end_b, tail) in _explore(nb, rest):
                results.append((end_b, [(src, dst, die, hit)] + tail))
    if not any_playable:
        return [(b, [])]
    return results


def legal_plays(b: Board, d1: int, d2: int) -> list[Play]:
    """All legal complete turns for the roll (d1, d2)."""
    dice = [d1, d1, d1, d1] if d1 == d2 else [d1, d2]
    lines = _explore(b, dice)

    max_used = max(len(steps) for _, steps in lines)
    best = [(eb, steps) for (eb, steps) in lines if len(steps) == max_used]

    # Non-double, only one die playable -> must use the higher die if possible.
    if d1 != d2 and max_used == 1:
        higher = max(d1, d2)
        with_higher = [(eb, steps) for (eb, steps) in best if steps[0][2] == higher]
        if with_higher:
            best = with_higher

    # Distinct end positions only (orderings reaching the same spot are equal
    # for evaluation); keep one representative step sequence each.
    seen = {}
    for end_b, steps in best:
        key = end_b.position_key()
        if key not in seen:
            seen[key] = Play(steps=steps, end_board=end_b)
    return list(seen.values())
