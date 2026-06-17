# GNU Backgammon external-interface protocol (SPEC-1)

> ## ✅ STATUS: VERIFIED
>
> Wire format confirmed on `ubuntu-latest`, gnubg 1.07.001, commit `ddb6fcf`.
> All three probe cases respond in move mode; the forced-dance case returns an
> empty move correctly. The FIBS encoder in `Board.to_fibs_board` and the move
> parser in `GnubgEngine._parse_move` are trusted. `validate_gnubg.py` gates
> are the next step before the engine is enabled in production matches.

---

## Target

| | |
| --- | --- |
| gnubg version targeted | `1.07.001 20240331` |
| Platform validated on | `ubuntu-latest` (GitHub Actions), `apt-get install -y gnubg` |
| Default arena port | **8888** (`bgarena.engines.DEFAULT_GNUBG_PORT`) — gnubg has no registered default; the arena fixes one |

## Launch command

gnubg's `external` command makes it listen and answer move/cube queries from a
client. Headless, no GUI:

```sh
# one-liner used by CI and the adapter's launch_cmd hint:
printf 'external localhost:8888\n' | gnubg -t -q
```

or interactively:

```
$ gnubg -t -q
(No game) external localhost:8888
```

`-t` = tty interface (no GTK), `-q` = quiet. The process then blocks, serving
one client connection at a time over TCP. The arena's `GnubgEngine` can also
spawn this itself via `launch_cmd=[...]`.

## Request: FIBS `board:` line (PRIMARY path — HYPOTHESIS)

The older/most-broadly-supported external protocol accepts a FIBS-style
`board:` state line and replies with the chosen move. Produced by
`Board.to_fibs_board(dice)`. For `Board.starting()` with dice `3,1` the adapter
currently emits:

```
board:gnubg:arena:1:0:0:0:-2:0:0:0:0:5:0:3:0:0:0:-5:5:0:0:0:-3:0:-5:0:0:0:0:2:0:-1:3:1:0:0:1:0:0:0:-1:-1:0:25:0:0:0:0:3:1:0
```

### Field meanings relied on (HYPOTHESIS — the fiddly part)

The encoder is built so **gnubg's point numbering matches the arena's 1:1**, so
that move tokens in the reply can be applied directly in arena coordinates
(`bgarena/board.py` was designed for this).

| Field(s) | Value | Meaning / assumption |
| --- | --- | --- |
| `board` | literal | message type |
| player / opponent | `gnubg` / `arena` | names; irrelevant to the move |
| match length | `1` | cubeless 1-pointer |
| scores | `0:0` | irrelevant cubeless |
| board[0..25] | 26 ints | **on-roll perspective**: `[0]=-opp_bar`, `[1..24]=points` (`+`=on-roll, `-`=opp), `[25]=+bar` |
| turn | `-1` | on-roll player's colour / it is their move |
| dice | `3:1` then `0:0` | on-roll player's dice, then opponent's (none) |
| cube value | `1` | SPEC-2 territory; neutral here |
| may-double ×2, was-doubled | `0:0:0` | cube fields, unused in SPEC-1 |
| colour | `-1` | on-roll player is "X" |
| direction | `-1` | plays from the high end (24) toward the low end (1) |
| home index | `0` | bears off past the low end |
| bar index | `25` | enters from the bar at the high end (on `25 − die`) |
| trailing (on-home/on-bar/pip/roll/redoubles) | neutral | gnubg recomputes from the board |

> The **direction / colour / home / bar quartet** is the classic source of FIBS
> board bugs and is exactly what the probe must confirm. If the captured reply
> can't be reconciled, this quartet (and the `[0]`/`[25]` bar placement) is the
> first thing to re-check.

## What fixed it (field corrections, both required)

Two fields in `Board.to_fibs_board` were wrong relative to gnubg's
`ParseFIBSBoard` in `drawboard.c`. Both corrections are committed in
`ddb6fcf`.

| Field | Hypothesis | Confirmed value | Root cause |
|---|---|---|---|
| `turn` / `colour` | `-1` | `1` | gnubg negates board ints on read and picks side-to-move via `nColor = nTurn>0 ? 1 : -1`. Sending `-1` selected the opponent's checkers. |
| `may-double` (both flags) | `0, 0` | `1, 1` | gnubg's heuristic treats `was-doubled==0 && both may-double==0` as "cube was turned", forcing a cube decision (`take`). Sending a centred cube (`1, 1`) bypasses it. |

The `direction`, `home`, and `bar` fields (`-1`, `0`, `25`) were correct as
hypothesised.

## Response (HYPOTHESIS — confirm verbatim with the probe)

Expected: a single line naming the chosen move in the board's point numbering,
e.g.

```
8/5 6/5
```

`GnubgEngine._parse_move` tolerates: an optional leading `move`/`play` keyword;
hit marks `*`; chained hops `13/7/2`; multipliers `24/18(2)` (doubles);
`bar`/`off` and numeric `25`/`0` for bar/off. The move is applied to a copy of
the board and reconciled to a legal `Play` **by resulting position** — so a
wrong guess raises loudly rather than misplaying.

**"No move" (dance):** representation TBD from the probe. `_parse_move` currently
treats an empty line / `no move` / `cannot move` as the no-op, which the adapter
maps to the referee's single no-op `Play`. **Confirm the exact token.**

## Captured exchange (commit `ddb6fcf`, gnubg 1.07.001, ubuntu-latest)

### Case A — `Board.starting()`, dice 3-1

request:
```
board:gnubg:arena:1:0:0:0:-2:0:0:0:0:5:0:3:0:0:0:-5:5:0:0:0:-3:0:-5:0:0:0:0:2:0:1:3:1:0:0:1:1:1:0:1:-1:0:25:0:0:0:0:3:1:0
```
raw reply: `b'8/5 6/5 \n'`  
decoded: `8/5 6/5 ` (trailing space before newline — handled by `.strip()`)

### Case B — `Board.starting()`, dice 6-6

raw reply: `b'24/18 24/18 13/7 13/7 \n'`  
decoded: `24/18 24/18 13/7 13/7 `

### Case C — bar position, dice 5-2 (both entry points blocked)

Bar position: `b.bar=1`, `b.points[20]=-2`, `b.points[23]=-2`  
raw reply: `b'\n'`  
decoded: `` (empty — forced dance, no legal entry; correct)

### Position ID round-trip

`Board.starting().to_gnubg_position_id()` == `4HPwATDgc/ABMA` ✓  
(gnubg tty `set board` / `show board` path requires an active game;
round-trip confirmed via the canonical ID match instead.)

## Position ID (CLI fallback + round-trip verification)

`Board.to_gnubg_position_id()` implements the documented GNU Position ID: the
14-char base64 of an 80-bit (10-byte) key. For each player (on-roll first), walk
25 slots — the 24 points from that player's ace point outward, then the bar —
writing `count` 1-bits then a 0-bit separator; pack LSB-first into 10 bytes;
base64 and strip padding.

**Confidence: high.** It already reproduces the canonical gnubg starting-position
ID exactly:

```
Board.starting().to_gnubg_position_id() == "4HPwATDgc/ABMA"   # ✓ canonical
```

Format reference: GNU Backgammon manual, *"Technical notes → Position ID"*
(<https://www.gnu.org/software/gnubg/manual/html_node/A-technical-description-of-the-Position-ID.html>).
The probe's `position_id_round_trip` additionally feeds the ID to gnubg and reads
it back via `show board` as an independent check on the verifying box.

## CLI fallback (`hint`)

Only if the socket interface proves unworkable on the target build: drive
`gnubg -t -q` with `set board <PositionID>`, set the dice, `hint`, and parse the
top line — gated behind the same reconcile-by-position + loud-failure logic.
Not implemented as the primary path; the Position ID encoder above is what it
would rely on.
