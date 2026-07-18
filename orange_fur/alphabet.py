"""
alphabet.py -- the symbol alphabet, the instrument categories the constraints
are written against, and the L0-L6 layer vocabularies.

ALPHABET. Exactly 2N symbols for N nodes:
    non-terminals  NT_0 .. NT_(N-1)   one per node; the node's rewriting rule
    terminals      T_0  .. T_(N-1)    emit notes; never rewritten

Encoding: a symbol is a plain int. Non-terminal i is `i`; terminal i is
`N + i`. So `sym < N` tests for a non-terminal. This keeps the working string a
flat list of ints, which matters -- at N=300 it holds several hundred thousand
entries and gets rewritten 180,000 times.

CATEGORIES. The constraints you specified ("gongs are rare", "partials are
together", "clouds are sparse") are about instrument CATEGORIES, not about
individual instruments. So the category is the durable abstraction and the
instrument is not: in Phase 1 a category maps to one of six placeholder
instruments; in Phase 3 it will map to a family of generated instruments. The
solver, the constraints, and the score generator only ever speak in categories.
"""

from __future__ import annotations

from enum import IntEnum


class Cat(IntEnum):
    """Instrument categories. The score layer never names an instrument."""
    PARTIAL = 0     # one sine of a non-harmonic bank; these CLUSTER (see below)
    TCLOUD = 1      # tuned partial cloud: saw/pulse/triangle emulated with
                    #   partials snapped to the scale, not to a harmonic series
    CLOUD = 2       # microsound: quiet clicks and chirps; these SPREAD
    PLUCK = 3       # quiet plucks, often straight into a long reverb tank
    GONG = 4        # gongs and metal pipes; RARE
    SWELL = 5       # slow swell, long release. The sparse-score carrier.


# Placeholder mapping, Phase 1 only. Phase 3 replaces this with the generated
# orchestra's instrument families and this table disappears.
CAT_TO_INSTR = {
    Cat.PARTIAL: 1,
    Cat.PLUCK: 2,
    Cat.GONG: 3,
    Cat.CLOUD: 4,
    Cat.TCLOUD: 5,
    Cat.SWELL: 6,
}

# The prior the solver draws category assignments from, before constraints.
# Deliberately NOT uniform: it encodes the piece's stated character (gongs rare,
# swells always available to carry sparse passages). The constraint scorer then
# pushes the realised distribution toward the targets in constraints.py.
CAT_PRIOR = {
    Cat.PARTIAL: 0.30,
    Cat.TCLOUD: 0.14,
    Cat.CLOUD: 0.22,
    Cat.PLUCK: 0.20,
    Cat.GONG: 0.05,
    Cat.SWELL: 0.09,
}


class Waveform(IntEnum):
    """For Cat.TCLOUD: which wave the tuned partial cloud emulates."""
    SAW = 0
    PULSE = 1
    TRIANGLE = 2


# ---------------------------------------------------------------- layers
class L0(IntEnum):
    DOWN = -1
    FLAT = 0
    UP = 1


class L1(IntEnum):
    INTRO = 0
    VERSE = 1
    CHORUS = 2
    BREAKDOWN = 3
    OUTRO = 4


class L2(IntEnum):
    DECEL = -1
    STEADY = 0
    ACCEL = 1


class L3(IntEnum):
    SMALL = 0
    LARGE = 1
    OPEN = 2
    MIDSIDE = 3
    LEFTRIGHT = 4


class L4(IntEnum):
    CHORD = 0
    SUSTAIN = 1
    OSTINATO = 2
    ARPEGGIO = 3
    RUN = 4
    CHIPARP = 5      # chiptune arpeggio
    HARMONY = 6
    TRILL = 7
    SLIDE = 8
    # Phase 5 gesture vocabulary. These are sequenced by the macro Euclidean
    # gesture track (macro.py), which overrides the inner node's L4 while its
    # playlist entry is in force.
    GLISS = 9        # one long note, real pitch glide (p10/p11)
    CLOUDGLISS = 10  # a cloud of grains all gliding the same direction
    DIVERGE = 11     # a cloud whose glide targets fan out symmetrically
    SWEEPCLICK = 12  # one long swept note with clicks scattered along it
    BURSTSEQ = 13    # a sequence of rapid retriggered bursts
    LOOP = 14        # a short cell repeated verbatim
    LONGDECAY = 15   # very long, quiet, deep into the tanks


class L5(IntEnum):        # gestures
    SWELL = 0
    STAB = 1
    BURST = 2
    DRIFT = 3
    SNAP = 4
    SCATTER = 5


class L6(IntEnum):        # articulations
    LEGATO = 0
    STACCATO = 1
    TENUTO = 2
    MARCATO = 3
    PLUCKED = 4
    STRUCK = 5


LAYER_TYPES = (L0, L1, L2, L3, L4, L5, L6)


def is_nonterminal(sym: int, n: int) -> bool:
    return sym < n


def terminal_index(sym: int, n: int) -> int:
    """Terminal symbol -> its 0..N-1 index."""
    return sym - n


def make_terminal(i: int, n: int) -> int:
    return n + i
