"""Single game of backgammon between two engines.

Cubeless to start (the right first step: it isolates pure checker play, is the
fairest comparison across engines, and avoids the doubling cube where the
engines differ most). A 1-point match is exactly one game.

Duplicate dice: pass the same `seed` to two games with the engines swapped and
both games see identical dice on each turn index, cancelling most of the luck.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .board import Board
from .moves import legal_plays, Play

WHITE = "white"
BLACK = "black"


@dataclass
class GameResult:
    winner: str          # WHITE or BLACK
    value: int           # 1 = single, 2 = gammon, 3 = backgammon
    turns: int
    history: list        # list of (player, (d1, d2), notation, position_key)


def _terminal_value(board_after_move: Board) -> int | None:
    """If the player who just moved has won, return the point value, else None.

    `board_after_move` is in that player's perspective (pre-flip).
    """
    if board_after_move.off < 15:
        return None
    loser_off = board_after_move.opp_off
    if loser_off > 0:
        return 1  # single
    # loser has borne nothing off -> gammon, or backgammon if still trapped
    backgammon = board_after_move.opp_bar > 0 or any(
        board_after_move.points[p] < 0 for p in range(1, 7)
    )
    return 3 if backgammon else 2


def play_game(engine_white, engine_black, seed: int, context: dict | None = None,
              max_turns: int = 100_000) -> GameResult:
    rng = random.Random(seed)
    context = context or {}
    engines = {WHITE: engine_white, BLACK: engine_black}

    board = Board.starting()

    # Opening roll: both cast one die, higher starts and plays both dice.
    while True:
        d1, d2 = rng.randint(1, 6), rng.randint(1, 6)
        if d1 != d2:
            break
    on_roll = WHITE if d1 > d2 else BLACK
    # Order the opening dice high-low purely for tidy notation.
    d1, d2 = max(d1, d2), min(d1, d2)

    history = []
    turns = 0
    while turns < max_turns:
        turns += 1
        plays = legal_plays(board, d1, d2)
        engine = engines[on_roll]
        if len(plays) == 1:
            chosen = plays[0]
        else:
            chosen = engine.choose(board, (d1, d2), plays, {**context, "on_roll": on_roll})
            if chosen.end_board.position_key() not in {p.end_board.position_key() for p in plays}:
                raise ValueError(f"{engine.name} returned an illegal play: {chosen.notation()}")

        history.append((on_roll, (d1, d2), chosen.notation(), chosen.end_board.position_key()))
        board = chosen.end_board

        value = _terminal_value(board)
        if value is not None:
            return GameResult(winner=on_roll, value=value, turns=turns, history=history)

        board = board.flip()
        on_roll = BLACK if on_roll == WHITE else WHITE
        d1, d2 = rng.randint(1, 6), rng.randint(1, 6)

    raise RuntimeError("game exceeded max_turns (possible move-generation bug)")
