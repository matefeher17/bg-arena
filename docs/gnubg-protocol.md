# GNU Backgammon external-interface protocol (SPEC-1)

> ## ⚠ STATUS: UNVERIFIED / QUARANTINED
>
> This document records the **hypothesised** wire format the `GnubgEngine`
> adapter is coded against. It was written on a Windows dev machine with **no
> runnable gnubg** (GTK app; no headless Windows build, no Docker, no WSL
> distro), so the socket exchange below has **not been captured from a live
> server yet**.
>
> The adapter is not considered working until, on Linux CI, **all three** gates
> in `validate_gnubg.py` pass — **legality cross-check AND forced-position
> sanity AND the smoke matches**. Legality alone is *not* sufficient: a
> consistent coordinate flip could produce legal-but-wrong moves that pass a
> membership check while losing every game.
>
> **To verify:** run `python scripts/gnubg_probe.py` on a box with gnubg, paste
> the captured request/response into the "Captured exchange" section below,
> reconcile it with the hypothesis, fix `Board.to_fibs_board` /
> `GnubgEngine._parse_move` if they differ, then run `validate_gnubg.py`.

---

## Target

| | |
| --- | --- |
| gnubg version targeted | **TBD — fill in from `gnubg --version` on the verifying box** (spec assumes ≥ 1.06, the external/extended-protocol era) |
| Platform validated on | TBD (CI: `ubuntu-latest`, `apt-get install -y gnubg`) |
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

## Captured exchange (PASTE PROBE OUTPUT HERE)

```
TODO: paste the verbatim output of `python scripts/gnubg_probe.py` here:
  - gnubg --version
  - the request line sent
  - gnubg's raw reply (repr, to show handshake/whitespace)
  - the Position ID round-trip result
```

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
