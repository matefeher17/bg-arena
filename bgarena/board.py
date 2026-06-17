"""Backgammon board state.

Representation conventions (chosen to map 1:1 onto Wildbg's HTTP API and
GNU Backgammon's Position ID, so engine adapters stay thin):

* The board is ALWAYS stored from the perspective of the player on roll.
* points[1..24]: > 0  -> checkers belonging to the player on roll
                  < 0  -> checkers belonging to the opponent
                  == 0 -> empty
* The player on roll moves from HIGH points to LOW points (24 -> 1) and
  bears off past point 1. Their home board is points 1..6.
* A checker entering from the bar enters on point (25 - die), i.e. into the
  high end (points 19..24).
* Sentinels used by move steps: BAR = 25 (a source), OFF = 0 (a destination).

After a turn is complete the board is flipped (`flip()`) so the opponent
becomes the player on roll, keeping all of the above invariants.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

NUM_POINTS = 24
CHECKERS = 15
BAR = 25   # sentinel: source point meaning "from the bar"
OFF = 0    # sentinel: destination meaning "borne off"


@dataclass
class Board:
    # index 0 is unused so that points[p] reads naturally for p in 1..24
    points: list[int] = field(default_factory=lambda: [0] * (NUM_POINTS + 1))
    bar: int = 0        # player-on-roll checkers on the bar
    opp_bar: int = 0    # opponent checkers on the bar
    off: int = 0        # player-on-roll checkers borne off
    opp_off: int = 0    # opponent checkers borne off

    # ---- construction ---------------------------------------------------
    @classmethod
    def starting(cls) -> "Board":
        b = cls()
        # player on roll (positive)
        b.points[24] = 2
        b.points[13] = 5
        b.points[8] = 3
        b.points[6] = 5
        # opponent (negative), mirror image
        b.points[1] = -2
        b.points[12] = -5
        b.points[17] = -3
        b.points[19] = -5
        return b

    def copy(self) -> "Board":
        return replace(self, points=self.points[:])

    # ---- turn handover --------------------------------------------------
    def flip(self) -> "Board":
        """Return the same position from the opponent's perspective."""
        nb = Board()
        for i in range(1, NUM_POINTS + 1):
            nb.points[i] = -self.points[NUM_POINTS + 1 - i]
        nb.bar, nb.opp_bar = self.opp_bar, self.bar
        nb.off, nb.opp_off = self.opp_off, self.off
        return nb

    # ---- queries --------------------------------------------------------
    def all_home(self) -> bool:
        """True if every player-on-roll checker is in the home board (1..6)."""
        if self.bar:
            return False
        return all(self.points[p] <= 0 for p in range(7, NUM_POINTS + 1))

    def pip_count(self) -> int:
        pips = self.bar * 25
        for p in range(1, NUM_POINTS + 1):
            if self.points[p] > 0:
                pips += self.points[p] * p
        return pips

    def opp_pip_count(self) -> int:
        # opponent travels the other way: a checker on point p is (25 - p) pips out
        pips = self.opp_bar * 25
        for p in range(1, NUM_POINTS + 1):
            if self.points[p] < 0:
                pips += (-self.points[p]) * (NUM_POINTS + 1 - p)
        return pips

    def borne_off(self) -> int:
        return self.off

    def checker_total_on_roll(self) -> int:
        return self.bar + self.off + sum(v for v in self.points if v > 0)

    def checker_total_opp(self) -> int:
        return self.opp_bar + self.opp_off + sum(-v for v in self.points if v < 0)

    def position_key(self):
        """Hashable identity of the position (for dedup / replay / caching)."""
        return (tuple(self.points), self.bar, self.opp_bar, self.off, self.opp_off)

    # ---- serialization for engine adapters ------------------------------
    def to_sage(self) -> list[int]:
        """26-element board in bgsage's representation.

        Indices 1..24 are the points (same sign convention as ours: positive =
        player on roll). Index 25 = on-roll bar, index 0 = opponent bar. Both
        bars are stored as positive counts (the index, not the sign, marks the
        owner). Borne-off checkers are implicit (15 minus those on board).
        """
        arr = [0] * 26
        for p in range(1, NUM_POINTS + 1):
            arr[p] = self.points[p]
        arr[25] = self.bar
        arr[0] = self.opp_bar
        return arr

    def to_wildbg_params(self) -> dict:
        """Query params for Wildbg's /move endpoint (signed point counts).

        NOTE: Wildbg's exact encoding of the bar is assumed here (p25 = on-roll
        bar, p0 = opponent bar). Verify against a live instance before trusting
        bar positions; the rest of the arena does not depend on this.
        """
        params = {f"p{p}": self.points[p] for p in range(1, NUM_POINTS + 1) if self.points[p]}
        if self.bar:
            params["p25"] = self.bar
        if self.opp_bar:
            params["p0"] = -self.opp_bar
        return params

    def to_fibs_board(self, dice: tuple[int, int],
                      player: str = "gnubg", opponent: str = "arena") -> str:
        """FIBS-style ``board:`` line for gnubg's external interface (PRIMARY path).

        ⚠ QUARANTINED / UNVERIFIED ENCODER. The exact FIBS field order and the
        direction/colour/home/bar quartet are notoriously fiddly and vary in how
        builds tolerate them. This implementation is a documented *hypothesis*;
        it is NOT trusted until the Linux probe (``scripts/gnubg_probe.py``) plus
        the forced-position and smoke-match gates in ``validate_gnubg.py`` pass.
        See ``docs/gnubg-protocol.md``. Reconciliation-by-resulting-position in
        ``GnubgEngine`` means a wrong guess here fails loudly rather than cheats.

        Hypothesis (chosen so gnubg's point numbering matches ours 1:1, which the
        board.py header was already designed for):

        * The 26-int board array is sent in ON-ROLL perspective:
            arr[1..24] = self.points[1..24]  (positive = on roll, negative = opp)
            arr[25]    = +self.bar           (on-roll bar, high end)
            arr[0]     = -self.opp_bar       (opponent bar, low end)
          So FIBS point i == our point i, and the on-roll player moves 24 -> 1,
          enters from the bar on 25-die, and bears off past point 1.
        * Fields after the board: turn, our two dice, opponent's two dice (0,0),
          cube value (1), may-double flags (0), was-doubled (0), then the
          colour/direction/home/bar quartet describing a player who moves from
          the high end (24) to the low end (1): colour=-1, direction=-1,
          home=0, bar=25. Trailing FIBS fields (on-home / on-bar / pip / can-move
          / forced / did-crawford / redoubles) are filled with neutral values;
          gnubg recomputes what it needs from the board.

        ``off``/``opp_off`` are implicit (15 minus checkers on the board+bar) and
        are not part of the FIBS board line.
        """
        d1, d2 = dice
        arr = [0] * 26
        for p in range(1, NUM_POINTS + 1):
            arr[p] = self.points[p]
        arr[25] = self.bar
        arr[0] = -self.opp_bar

        fields = [
            "board",
            player,
            opponent,
            1,                       # match length (cubeless 1-pointer)
            0, 0,                    # scores (player, opponent)
            *arr,                    # 26 board ints, indices 0..25
            1,                       # turn: on-roll player to move (1 == O, cube not offered)
            d1, d2,                  # on-roll player's dice
            0, 0,                    # opponent's dice (not their turn)
            1,                       # cube value
            0, 0,                    # may double (player, opponent) — SPEC-2
            0,                       # was doubled
            1,                       # colour of player on roll (must match turn)
            -1,                      # direction of play (high -> low)
            0,                       # home board index (off end)
            25,                      # bar index (entry end)
            0, 0,                    # checkers on home (player, opponent)
            0, 0,                    # checkers on bar (player, opponent)
            d1, d2,                  # the roll (echo)
            0,                       # redoubles
        ]
        return ":".join(str(f) for f in fields)

    def to_gnubg_position_id(self) -> str:
        """GNU Backgammon Position ID — 14-char base64 of the 80-bit position key.

        ⚠ QUARANTINED / UNVERIFIED ENCODER (CLI ``hint`` fallback + the probe's
        round-trip verification). Per the spec, the bit layout must NOT be trusted
        without a round-trip check (feed the ID to gnubg, read the position back,
        assert equality) — ``scripts/gnubg_probe.py`` does exactly that. Format
        reference cited in ``docs/gnubg-protocol.md``.

        Documented algorithm (gnubg ``positionid.c`` / PositionKey): two players'
        boards are written as a bitstream, player on roll first. For each player,
        walk 25 slots (their 24 points from the ace point outward, then the bar),
        writing ``count`` 1-bits followed by a single 0-bit separator. Bits are
        packed LSB-first into 10 bytes (80 bits); base64 of those 10 bytes, with
        padding stripped, yields the 14-char ID.

        Point-numbering hypothesis:
          * on-roll player's slot j (0..23) = our point (j+1); slot 24 = on-roll bar.
          * opponent's slot j (0..23) = our point (24-j); slot 24 = opponent bar.
        """
        on_roll = [0] * 25
        opp = [0] * 25
        for p in range(1, NUM_POINTS + 1):
            v = self.points[p]
            if v > 0:
                on_roll[p - 1] = v
            elif v < 0:
                opp[NUM_POINTS - p] = -v
        on_roll[24] = self.bar
        opp[24] = self.opp_bar

        bits: list[int] = []
        for slots in (on_roll, opp):       # player on roll first
            for count in slots:
                bits.extend([1] * count)
                bits.append(0)             # separator
        # Pad to 80 bits and pack LSB-first into 10 bytes.
        bits += [0] * (80 - len(bits))
        key = bytearray(10)
        for i, bit in enumerate(bits[:80]):
            if bit:
                key[i >> 3] |= 1 << (i & 7)

        import base64
        return base64.b64encode(bytes(key)).decode("ascii").rstrip("=")

    # ---- display --------------------------------------------------------
    def __str__(self) -> str:
        def cell(p: int) -> str:
            v = self.points[p]
            if v == 0:
                return " . "
            who = "O" if v > 0 else "X"  # O = on roll, X = opponent
            return f"{who}{abs(v):>2}"
        top = " ".join(cell(p) for p in range(13, 25))
        bot = " ".join(cell(p) for p in range(12, 0, -1))
        return (
            f"13..24: {top}\n"
            f"12.. 1: {bot}\n"
            f"bar O={self.bar} X={self.opp_bar}   off O={self.off} X={self.opp_off}   "
            f"pip O={self.pip_count()} X={self.opp_pip_count()}"
        )
