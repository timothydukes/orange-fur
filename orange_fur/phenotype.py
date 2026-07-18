"""
phenotype.py -- how a terminal symbol is READ, which depends on the section.

The string never resets. The map from string to phenotype does. Each section
draws a FRESH map, so symbol 17 is a quiet pluck at the top of the piece and
something else entirely in the breakdown -- the same material, read differently.
That is where a lot of the piece's sense of "the same thing, changed" has to
come from, because the string itself is a single monotonic object.

What is FIXED for the whole run (a property of the alphabet, decided by the
constraint solver):
    the terminal's CATEGORY, and its waveform if it is a tuned partial cloud.
    A gong stays a gong -- otherwise "gongs are rare" would mean nothing.

What is REDRAWN per section (the 5-tuple, minus the category):
    pitch-class, articulation, slew, pan.

INTERPRETIVE DECISION -- octave. You said section and gesture choose the octave,
and that register is directed by L0. Gestures (L5) are Phase 2, so in Phase 1 the
octave comes from a per-section register BAND plus L0 pushing a drift up or down
across the section. The band is a contour, not a per-note draw: a section sits
somewhere in the register and moves.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .alphabet import Cat, L0, L1

# Register bands, in scale degrees relative to the base key, per section type.
# Intros and outros sit low and wide; choruses sit high; breakdowns spread out.
SECTION_BAND: dict[L1, tuple[int, int]] = {
    L1.INTRO:     (-14, 6),
    L1.VERSE:     (-10, 14),
    L1.CHORUS:    (-4, 26),
    L1.BREAKDOWN: (-24, 20),
    L1.OUTRO:     (-20, 4),
}

# Category defaults. The per-section map jitters around these; it does not
# override them, because a pluck that lasts 30 seconds is not a pluck.
CAT_DUR: dict[Cat, tuple[float, float]] = {
    Cat.PARTIAL: (0.8, 9.0),
    Cat.TCLOUD:  (0.5, 5.0),
    Cat.CLOUD:   (0.01, 0.09),     # microsound: clicks and chirps
    Cat.PLUCK:   (0.25, 2.5),
    Cat.GONG:    (5.0, 22.0),
    Cat.SWELL:   (8.0, 40.0),      # the sparse-score carrier: long, slow, patient
}
CAT_AMP: dict[Cat, tuple[float, float]] = {
    Cat.PARTIAL: (0.10, 0.35),     # banks are made of many quiet things
    Cat.TCLOUD:  (0.12, 0.40),
    Cat.CLOUD:   (0.04, 0.16),     # quiet individual clicks
    Cat.PLUCK:   (0.15, 0.55),
    Cat.GONG:    (0.35, 0.90),
    Cat.SWELL:   (0.20, 0.60),
}
CAT_SEND: dict[Cat, tuple[float, float]] = {
    Cat.PARTIAL: (0.25, 0.70),
    Cat.TCLOUD:  (0.20, 0.60),
    Cat.CLOUD:   (0.35, 0.95),     # clouds live in the room
    Cat.PLUCK:   (0.45, 0.95),     # "plucks into reverb tanks with long decays"
    Cat.GONG:    (0.40, 0.85),
    Cat.SWELL:   (0.55, 1.00),     # swells are mostly room
}
CAT_SLEW: dict[Cat, tuple[float, float]] = {
    Cat.PARTIAL: (0.30, 0.80),
    Cat.TCLOUD:  (0.15, 0.60),
    Cat.CLOUD:   (0.00, 0.10),     # a click has no swell
    Cat.PLUCK:   (0.00, 0.12),
    Cat.GONG:    (0.01, 0.08),     # struck
    Cat.SWELL:   (0.75, 1.00),     # all swell
}


@dataclass
class Reading:
    """One section's reading of one terminal symbol."""
    degree: int          # scale degree offset (pitch-class + octave handled at use)
    slew: float
    pan: float
    dur_bias: float      # 0..1 within the category's duration range
    amp_bias: float      # 0..1 within the category's amplitude range
    send_bias: float
    voice: float = 0.0   # 0..1 -> which concrete instrument of the category's
                         # subset this terminal binds to, THIS SECTION


@dataclass
class SectionMap:
    section: L1
    band: tuple[int, int]
    readings: dict[int, Reading]     # terminal index -> reading
    drift: int                       # L0-driven register drift across the section


def draw(n: int, section: L1, l0: L0, rng: random.Random) -> SectionMap:
    """A fresh random draw, per section, as specified."""
    band = SECTION_BAND[section]
    span = band[1] - band[0]
    readings = {}
    for t in range(n):
        readings[t] = Reading(
            degree=rng.randrange(band[0], band[1] + 1),
            slew=rng.random(),
            pan=rng.random(),
            dur_bias=rng.random(),
            amp_bias=rng.random(),
            send_bias=rng.random(),
            voice=rng.random(),
        )
    # L0 pushes the whole register band across the section.
    drift = int(l0) * rng.randint(0, max(1, span // 3))
    return SectionMap(section=section, band=band, readings=readings, drift=drift)


def lerp(rng_pair: tuple[float, float], x: float) -> float:
    return rng_pair[0] + (rng_pair[1] - rng_pair[0]) * x
