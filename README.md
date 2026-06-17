# bgarena

A **backgammon engine arena**: a referee and tournament harness that pits backgammon engines against each other under fair, reproducible conditions.

<!-- Replace OWNER/REPO after you push, then this badge goes live: -->
[![CI](https://github.com/matefeher17/bg-arena/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/REPO/actions/workflows/ci.yml)

## The idea

One engine — **eXtreme Gammon (XG)** — is treated as the standing champion: it isn't a contender, it's the yardstick. The open engines fight a **contender round-robin**, and the winner earns a later title match against the champion. XG also serves as the neutral PR judge, which is legitimate precisely because it doesn't compete in the qualifier.

The referee owns all game state (dice, board, score) and treats each engine as a stateless *"given this position, what's your move?"* oracle. Adding an engine is one small adapter.

## How it works

- **Format (v1):** cubeless, 1-point games — pure checker play, the fairest and most directly comparable starting point, and the place engines differ least in cube handling.
- **Variance reduction:** *duplicate dice* — each pairing is played twice with colors swapped and identical dice, cancelling most of backgammon's luck.
- **Reproducible:** every game is seeded; the same seed yields the same game on any machine, so results can be replayed and audited.
- **Metric now:** head-to-head win rate. **Metric next:** PR (Performance Rating) from XG/rollout analysis of the logged games.

The move generator is **cross-validated against Sage's independent C++ generator** (0 mismatches over 400 sampled positions), so the rules the matches run under are trustworthy.

## Engines

| Engine | License | Status |
| --- | --- | --- |
| Random, Heuristic | — | Built in, zero dependencies (baselines) |
| **Sage** (`bgsage`) | AGPL-3.0 | **Working** — neural net, configurable ply |
| Wildbg | MIT/Apache | Adapter written; confirm JSON schema vs a live server |
| GNUbg | GPL-3.0 | Adapter written (external socket); **quarantined** until the Linux CI gates pass — see below |
| XG | proprietary | Champion + PR judge; later, via a Windows worker |

### Running GNUbg

The GNUbg adapter talks to [GNU Backgammon](https://www.gnu.org/software/gnubg/)
over its **external interface** (a TCP socket), so a long-running arena reuses one
server process.

```bash
# install (gnubg >= 1.06, validated version recorded in docs/gnubg-protocol.md)
sudo apt-get install -y gnubg      # Linux
brew install gnubg                 # macOS

# start the external server on the arena's default port (8888):
printf 'external localhost:8888\n' | gnubg -t -q
```

```python
from bgarena import GnubgEngine, HeuristicEngine, duplicate_match

with GnubgEngine() as gnu:          # connects lazily; close()/context-manager tears down
    m = duplicate_match(gnu, HeuristicEngine(), pairs=10)
    print(f"{m.a} {m.wins_a} - {m.wins_b} {m.b}")
```

> **Quarantine status.** The arena was developed on Windows, which can't run
> gnubg, so the wire format is coded as a *hypothesis* (the Position ID encoder is
> already confirmed against gnubg's canonical starting ID; the FIBS `board:` line
> is the unverified part). The adapter is trusted only once all three gates in
> `validate_gnubg.py` — legality **and** forced-position sanity **and** smoke
> matches — pass on Linux CI. Capture real ground truth first with
> `python scripts/gnubg_probe.py` and see [docs/gnubg-protocol.md](docs/gnubg-protocol.md).

## Quickstart

```bash
# clone your repo, then from its root:
python tests_demo.py        # core smoke test + demo tournament (no dependencies)

# to include the Sage engine:
pip install bgsage          # 64-bit CPython 3.10-3.14
python validate_sage.py     # cross-check the rules engine + a real Sage match
```

Run your own match:

```python
from bgarena import SageEngine, HeuristicEngine, RandomEngine, duplicate_match, round_robin, format_standings

m = duplicate_match(SageEngine(level="1ply"), RandomEngine(seed=3), pairs=100)
print(f"{m.a} {m.wins_a} - {m.wins_b} {m.b}")

standings, _ = round_robin([SageEngine(level="1ply"), HeuristicEngine(), RandomEngine()], pairs=100)
print(format_standings(standings))
```

Optionally install the package itself:

```bash
pip install -e .            # or:  pip install -e ".[sage]"
```

## Layout

```
bgarena/
  board.py        position state, flip, serialization (Wildbg- and Sage-compatible coords)
  moves.py        legal play generation (hitting, bear-off, dice-maximization)
  game.py         one game: opening roll, turn loop, win/gammon detection
  engines.py      Engine interface + Random/Heuristic baselines + Sage/Wildbg/GNUbg adapters
  tournament.py   duplicate-dice match + round-robin standings
tests_demo.py     correctness checks + demo tournament (no deps)
validate_sage.py  cross-validation against bgsage + sample matches
validate_gnubg.py GNUbg adapter gates: legality + forced-position + smoke matches
scripts/          gnubg_probe.py (protocol ground-truth capture; excluded from CI core)
docs/             gnubg-protocol.md (the captured/hypothesised gnubg wire format)
```

## Adding an engine

Subclass `Engine` and implement one method. The board is always handed to you from your own perspective; return one of the supplied legal plays:

```python
from bgarena import Engine

class MyEngine(Engine):
    name = "MyEngine"
    def choose(self, board, dice, plays, context):
        return max(plays, key=lambda p: my_eval(p.end_board))
```

## Roadmap

1. Wire **Wildbg** (confirm its response schema) and **GNUbg**.
2. **PR judging**: export matches and batch-analyze with XG (or rollouts) for a strength metric that converges faster than win rate.
3. **XG title match**: a Windows worker driving XG via GUI automation, run offline.
4. **Web frontend**: live leaderboard and game replay (boards rendered from logged position IDs).

## License

Released under **AGPL-3.0** (see [LICENSE](LICENSE)). The arena integrates engines under copyleft licenses — GNUbg (GPL-3.0) and Sage (AGPL-3.0) — and AGPL is the compatible choice that also satisfies AGPL's network clause when the arena is hosted with Sage. Wildbg (MIT/Apache) is permissive and combines freely.

This is not legal advice. If you intend to host or distribute this commercially, confirm the licensing of the combined work with a professional.

## Credits

Built on the work of the computer-backgammon community: [GNU Backgammon](https://www.gnu.org/software/gnubg/), [wildbg](https://github.com/carsten-wenderdel/wildbg), [Open Sage / bgsage](https://github.com/markbgsage/bgsage), and eXtreme Gammon.
