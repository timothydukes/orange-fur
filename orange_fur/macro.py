"""
macro.py -- Phase 5. Slow Euclidean rhythms as a HIGHER-ORDER CONTROL INPUT.

These are not note rhythms. They are slow control patterns -- periods measured
in SECONDS, often tens of seconds -- that sit ABOVE the layer system and steer
it. The layers still decide what a note is; the macro tracks decide which of
those decisions is currently in force.

FOUR TRACKS, drawn per section, each an independent Euclidean pattern E(k, n)
with its own slow pulse period:

  ACCENT    its onsets place macro-dynamic accents: a slow gain contour that
            rises into each accent and falls away. This is the piece breathing
            at a scale above the phrase. NOT a compressor -- it is score-time
            gain, and it is in the amp model.

  GESTURE   its onsets ADVANCE A PLAYLIST. Each section draws an ordered
            playlist of gesture families (glissando, cloud glissando, diverging
            cloud, sweep-and-click, burst, loop, ostinato, trill, long decay),
            and every gesture pulse steps to the next entry. Notes landing
            while entry X is current are built as X, OVERRIDING the inner
            node's L4. This is the mechanism by which the requested vocabulary
            actually gets sequenced rather than merely existing.

  DENSITY   gates dense against sparse: during an off-beat of the density
            pattern, a drawn fraction of notes is culled, so the texture opens
            up and closes on a slow pulse independent of the sections.

  REGISTER  its onsets step the register band up or down by a drawn interval,
            walking the tessitura on a slow clock. (L0 still supplies the
            long-run direction; this is the staircase inside it.)

WHY EUCLIDEAN. E(k, n) distributes k pulses as evenly as possible over n slots
-- maximally even, never regular unless k divides n. At slow periods that reads
as a cycle that keeps almost-but-not-quite lining up with the sections, which is
exactly the "higher-order" behaviour wanted: it organises without gridding.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .alphabet import L4


def bjorklund(k: int, n: int) -> list[int]:
    """Euclidean rhythm E(k, n): k pulses distributed as evenly as possible
    over n slots. Returns a list of n 0/1s.

    Standard Bjorklund. E(3,8) -> 10010010, E(5,8) -> 10110110,
    E(2,5) -> 10100, E(4,4) -> 1111. Tested against those.
    """
    if n <= 0:
        return []
    k = max(0, min(k, n))
    if k == 0:
        return [0] * n
    if k == n:
        return [1] * n

    groups = [[1] for _ in range(k)] + [[0] for _ in range(n - k)]
    while True:
        a = k
        b = n - k
        m = min(a, b)
        if m <= 1:
            break
        for i in range(m):
            groups[i].extend(groups[-1])
            groups.pop()
        k = m
        n = len(groups)
    return [x for g in groups for x in g]


# The gesture vocabulary the playlist draws from. These are L4 families; the
# gesture track selects WHICH is in force, the layers still shape it.
GESTURE_PALETTE = [
    L4.GLISS, L4.CLOUDGLISS, L4.DIVERGE, L4.SWEEPCLICK,
    L4.BURSTSEQ, L4.LOOP, L4.OSTINATO, L4.TRILL, L4.LONGDECAY,
]


@dataclass
class Track:
    pattern: list[int]
    period: float        # seconds per SLOT (slow: 0.7 .. 9 s)
    t0: float

    def slot_at(self, t: float) -> int:
        if not self.pattern or self.period <= 0:
            return 0
        i = int((t - self.t0) / self.period)
        return i % len(self.pattern)

    def on_at(self, t: float) -> bool:
        return bool(self.pattern[self.slot_at(t)]) if self.pattern else False

    def pulse_index(self, t: float) -> int:
        """How many pulses (1s) have elapsed at time t -- the playlist cursor."""
        if not self.pattern or self.period <= 0:
            return 0
        raw = int((t - self.t0) / self.period)
        if raw < 0:
            return 0
        full, rem = divmod(raw, len(self.pattern))
        return full * sum(self.pattern) + sum(self.pattern[:rem + 1])

    def accent_pat(self) -> list[int]:
        return self.pattern

    def phase_in_slot(self, t: float) -> float:
        if self.period <= 0:
            return 0.0
        return ((t - self.t0) / self.period) % 1.0


@dataclass
class MacroPlan:
    accent: Track
    gesture: Track
    density: Track
    register: Track
    playlist: list[L4]
    accent_depth: float      # how much the accent contour swings the gain
    cull: float              # fraction culled on density off-slots
    reg_step: int            # scale degrees per register pulse
    reg_dir: int
    reg_span: int            # the walk REFLECTS at +/- this bound (degrees)

    def gain_at(self, t: float) -> float:
        """Macro-dynamic contour: rise into an accent slot, fall away after.
        A raised-cosine bump on the accent slots, floor elsewhere."""
        import math
        on = self.accent.on_at(t)
        ph = self.accent.phase_in_slot(t)
        bump = 0.5 - 0.5 * math.cos(2 * math.pi * ph) if on else 0.0
        return (1.0 - self.accent_depth) + self.accent_depth * (0.35 + 0.65 * bump)

    def gesture_at(self, t: float) -> L4 | None:
        if not self.playlist:
            return None
        return self.playlist[self.gesture.pulse_index(t) % len(self.playlist)]

    def culled(self, t: float, rng: random.Random) -> bool:
        if self.density.on_at(t):
            return False
        return rng.random() < self.cull

    def register_offset(self, t: float) -> int:
        """BOUNDED register staircase. The raw walk (dir * step * pulses) grows
        without limit -- by the end of an 8-minute section it measured 910
        degrees, i.e. ~75 octaves above the table, where every note pins
        against the sr/2.2 guard. Long-form is exactly where that shows up.
        The walk now REFLECTS at +/- reg_span (a triangle fold): it still
        climbs and falls on the Euclidean clock, it just stays on the scale."""
        raw = self.reg_dir * self.reg_step * self.register.pulse_index(t)
        span = max(1, self.reg_span)
        period = 4 * span
        x = abs(raw) % period
        folded = x if x <= span else (2 * span - x if x <= 3 * span else x - period)
        return folded if raw >= 0 else -folded


def _draw_track(rng: random.Random, t0: float, span: float,
                lo_slots: int, hi_slots: int,
                lo_per: float, hi_per: float) -> Track:
    n = rng.randint(lo_slots, hi_slots)
    k = rng.randint(1, max(1, n - 1))
    per = rng.uniform(lo_per, hi_per)
    # keep the cycle SLOW relative to the section but not longer than it
    if per * n > span * 1.6:
        per = max(0.7, span * 1.6 / n)
    return Track(pattern=bjorklund(k, n), period=per, t0=t0)


def draw_plan(rng: random.Random, t0: float, span: float) -> MacroPlan:
    """One macro plan per section."""
    playlist = rng.sample(GESTURE_PALETTE, k=rng.randint(3, 6))
    return MacroPlan(
        accent=_draw_track(rng, t0, span, 5, 13, 1.2, 6.0),
        gesture=_draw_track(rng, t0, span, 3, 11, 2.0, 9.0),
        density=_draw_track(rng, t0, span, 4, 12, 1.5, 7.0),
        register=_draw_track(rng, t0, span, 3, 9, 2.5, 9.0),
        playlist=playlist,
        accent_depth=rng.uniform(0.25, 0.65),
        cull=rng.uniform(0.25, 0.7),
        reg_step=rng.choice([2, 3, 4, 5, 7]),
        reg_dir=rng.choice([-1, 1]),
        reg_span=rng.randint(7, 17),
    )
