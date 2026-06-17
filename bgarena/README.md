# bgarena — a backgammon engine arena

A referee + tournament harness for pitting backgammon engines against each
other. The referee owns all game state (dice, board, score) and treats every
engine as a stateless "given this position, what's your move?" oracle, so
adding an engine means writing one small adapter.

## Design (v1)

* **Format:** cubeless, 1-point games (pure checker play — the fairest first
  comparison and the place the engines are most directly comparable).
* **Variance reduction:** *duplicate dice* — each pairing is played twice with
  colours swapped and identical dice, cancelling most of the luck.
* **Champion model:** the open engines (GNUbg, Sage, Wildbg, +a 4th slot) fight
  a contender round-robin; the winner earns a later title match against XG. XG
  also serves as the neutral PR judge (legitimate, because it is not a
  contender). Both XG roles run on a separate Windows worker and are added
  later.
* **Metric now:** head-to-head win rate. **Metric next:** PR (Performance
  Rating) from XG/rollout analysis of the logged games.

## Layout

    bgarena/
      board.py        position state, flip, serialization (Wildbg-compatible coords)
      moves.py        legal play generation (hitting, bear-off, dice-maximization)
      game.py         one game: opening roll, turn loop, win/gammon detection
      engines.py      Engine interface + Random/Heuristic baselines + adapter stubs
      tournament.py   duplicate-dice match + round-robin standings
    tests_demo.py     correctness checks + a runnable demo

## Run the demo

    cd <dir containing the bgarena package>
    python -m tests_demo

## Add an engine

Subclass `Engine` and implement one method. The board is always handed to you
from your own perspective; you receive the legal plays and return the one you
want:

```python
from bgarena import Engine

class MyEngine(Engine):
    name = "MyEngine"
    def choose(self, board, dice, plays, context):
        # board: your-perspective Board; dice: (d1, d2)
        # plays: list[Play]; return one of them
        return max(plays, key=lambda p: my_eval(p.end_board))
```

Then drop it into a `round_robin([...])` call.

## Status

* Core arena, rules engine, duplicate-dice tournament: **working & tested.**
* `WildbgEngine`: written; needs its JSON response schema confirmed against a
  live instance (`docker run -p 8082:8082 wildbg`).
* `SageEngine` (`pip install bgsage`) and `GnubgEngine` (CLI `hint` or external
  socket): documented stubs, next to be wired.
* XG worker (Windows GUI automation) and PR judging: later track.
