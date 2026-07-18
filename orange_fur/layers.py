"""
layers.py -- Phase 2. What L2..L6 MEAN.

The node graph carries a 7-tuple on every node; Phase 1 only spent L1 (sections)
and L0 (register drift). This module spends the rest.

PAIR = (CONTEXT, CONTENT). As specified: in a pair (a, b), the OUTER node a is
context -- section (L1), tempo (L2), room (L3) -- and the INNER node b is
content -- what is played (L4), how it moves (L5), how each note is shaped (L6).
Outer node a owns pairs [a*N, (a+1)*N), i.e. 1/N of the timeline, and each pair
owns 1/N of that. A note's onset places it in exactly one pair slice, and that
slice's inner node supplies its content. So the same terminal symbol, landing
ten seconds later, can come out a trill instead of a chord -- content is a
property of WHERE IN THE TRAVERSAL the note falls, which is the spec's intent:
traversal order is time order, and the pair is the unit of combination.

WHAT EACH LAYER DOES HERE:

  L2 tempo      warps onset density across the outer node's span.
                accel = the Poisson onsets crowd toward the end of the span,
                decel = toward the beginning, steady = untouched. Implemented
                as u -> u**g on the normalised onset positions (g>1 accel,
                g<1 decel), which preserves the exponential gap character
                while bending the local rate.

  L3 room       resolves PER SECTION -- majority vote over the section's
                nodes' L3 fields -- and CHANGES ONLY AT SECTION BOUNDARIES.
                Clean cuts, as specified: the master bus steps its reverb
                feedback, cutoff, and stereo treatment at the boundary times,
                no crossfade. LEFTRIGHT additionally quantises pans to two
                lanes score-side; MIDSIDE widens the image on the bus.

  L4 content    a selected terminal expands into a PATTERN: chord, sustain,
                ostinato, arpeggio, run, chiptune arp, harmony, trill, slide.
                Pattern notes COUNT AGAINST THE N**2 BUDGET -- selection
                divides each section's share by the expected pattern size, so
                a chiparp-heavy section fires fewer, larger events.

  L5 gesture    shapes the pattern in time and level: swell, stab, burst,
                drift, snap, scatter.

  L6 artic      per-note duration scale, overlap/gap, and slew: legato,
                staccato, tenuto, marcato, plucked, struck.

DURATION, per the spec ("envelope following, smoothing, and pre-computed
kernels; also literally convolving two sequences at low resolution"):

  Each pattern builds a low-resolution ARTICULATION SEQUENCE (one duration
  factor per note, from L6 with jitter) and a GESTURE KERNEL (a short
  precomputed envelope shape per L5). The two are LITERALLY CONVOLVED at low
  resolution, the result is smoothed (a 3-tap moving average -- the "envelope
  following" flavour: each note's duration follows the local energy of the
  convolution), and the final per-note duration multipliers are sampled from
  it. The bitcrushed bus-channel convolution is orchestra-side and belongs to
  Phase 4, as agreed.

L2 x L3 -> L6 CONTOUR (interpretive): tempo and room jointly scale the slew
that L6 proposes. A large or open room slows contours (longer attacks read
better in a long tail); acceleration sharpens them. So the same articulation
is rounder in a large decelerating passage than in a small accelerating one.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from .alphabet import L1, L2, L3, L4, L5, L6

# ------------------------------------------------------------------ L2 tempo
TEMPO_GAMMA = {L2.ACCEL: 1.8, L2.STEADY: 1.0, L2.DECEL: 0.55}


def tempo_warp(u: float, l2: L2) -> float:
    """u in [0,1] within the outer node's span -> warped position."""
    g = TEMPO_GAMMA[l2]
    return u ** g


# ------------------------------------------------------------------ L3 rooms
@dataclass
class Room:
    l3: L3
    fb_scale: float      # multiplies the --space-derived reverb feedback
    cut_scale: float     # multiplies the --space-derived cutoff
    width: float         # stereo width on the bus (1 = untouched, >1 M/S widen)
    lanes: bool          # quantise pans to hard L/R lanes (score-side)


ROOMS: dict[L3, Room] = {
    L3.SMALL:     Room(L3.SMALL,     0.86, 0.75, 0.80, False),
    L3.LARGE:     Room(L3.LARGE,     1.04, 0.65, 1.00, False),
    L3.OPEN:      Room(L3.OPEN,      1.00, 1.30, 1.10, False),
    L3.MIDSIDE:   Room(L3.MIDSIDE,   0.96, 1.00, 1.45, False),
    L3.LEFTRIGHT: Room(L3.LEFTRIGHT, 0.94, 1.00, 1.00, True),
}

PAN_LANES = (0.08, 0.92)


def section_room(nodes, lo: int, hi: int) -> Room:
    """Majority vote over the section's nodes' L3 fields; ties break toward the
    earliest node, so the room is a stable property of the section, not of
    whichever node happens to sort first in a dict."""
    votes = Counter(n.l3 for n in nodes[lo:hi])
    top = max(votes.values())
    for n in nodes[lo:hi]:
        if votes[n.l3] == top:
            return ROOMS[n.l3]
    return ROOMS[L3.LARGE]


# ------------------------------------------------------------------ L4 content
# Pattern shape per L4: (count range, degree step sequence generator, spread)
# `spread` is the pattern's time footprint as a multiple of the base duration.
PATTERN_SIZE = {          # (lo, hi) note counts -- used for budget division too
    L4.CHORD:    (2, 4),
    L4.SUSTAIN:  (1, 1),
    L4.OSTINATO: (3, 6),
    L4.ARPEGGIO: (3, 5),
    L4.RUN:      (4, 8),
    L4.CHIPARP:  (8, 16),
    L4.HARMONY:  (2, 2),
    L4.TRILL:    (6, 12),
    L4.SLIDE:    (3, 5),
    # Phase 5
    L4.GLISS:      (1, 1),
    L4.CLOUDGLISS: (10, 22),
    L4.DIVERGE:    (10, 22),
    L4.SWEEPCLICK: (6, 14),
    L4.BURSTSEQ:   (6, 14),
    L4.LOOP:       (6, 16),
    L4.LONGDECAY:  (1, 2),
}

# Glide specs: (degree range, curve range). A pattern family with an entry here
# emits p10/p11 -- a REAL pitch glide in the instrument, not a stepwise fake.
GLIDE_SPEC = {
    L4.GLISS:      ((5, 19), (-3.0, 3.0)),
    L4.CLOUDGLISS: ((3, 12), (-2.0, 2.0)),
    L4.DIVERGE:    ((4, 16), (-1.5, 1.5)),
    L4.SWEEPCLICK: ((9, 26), (-4.0, 4.0)),
}


def expected_pattern_size(l4_counts: Counter) -> float:
    tot = sum(l4_counts.values()) or 1
    s = 0.0
    for l4, c in l4_counts.items():
        lo, hi = PATTERN_SIZE[l4]
        s += c * (lo + hi) / 2
    return max(1.0, s / tot)


def pattern_degrees(l4: L4, k: int, rng: random.Random) -> list[int]:
    """Degree offsets (in scale degrees, relative to the head note)."""
    if l4 == L4.CHORD:
        base = [0, 2, 4, 7, 9]
        rng.shuffle(base)
        return sorted(base[:k])
    if l4 == L4.SUSTAIN:
        return [0]
    if l4 == L4.OSTINATO:
        return [0] * k
    if l4 == L4.ARPEGGIO:
        step = rng.choice([2, 3, 4])
        seq = [i * step for i in range(k)]
        return seq if rng.random() < 0.5 else seq[::-1]
    if l4 == L4.RUN:
        d = rng.choice([-1, 1])
        return [i * d for i in range(k)]
    if l4 == L4.CHIPARP:
        cell = [0, rng.choice([3, 4]), rng.choice([7, 9])]
        return [cell[i % 3] for i in range(k)]
    if l4 == L4.HARMONY:
        return [0, rng.choice([2, 4, 5])]
    if l4 == L4.TRILL:
        up = rng.choice([1, 2])          # the upper degree is chosen ONCE --
        return [0 if i % 2 == 0 else up  # a trill alternates TWO degrees
                for i in range(k)]
    if l4 == L4.SLIDE:
        d = rng.choice([-1, 1])
        return [i * d for i in range(k)]

    # ---- Phase 5 ----
    if l4 == L4.GLISS or l4 == L4.LONGDECAY:
        return [0] * k
    if l4 == L4.CLOUDGLISS:
        # grains scattered in a narrow band; they all GLIDE together (the glide
        # is p10, set in score.py -- the degrees here are just the cloud's body)
        w = rng.randint(2, 7)
        return [rng.randint(-w, w) for _ in range(k)]
    if l4 == L4.DIVERGE:
        # start clustered, glide targets fan out -- so the BODY is tight
        return [rng.randint(-1, 1) for _ in range(k)]
    if l4 == L4.SWEEPCLICK:
        # index 0 is the sweep; the rest are clicks scattered around it
        return [0] + [rng.randint(-9, 9) for _ in range(k - 1)]
    if l4 == L4.BURSTSEQ:
        cell = [0, rng.choice([1, 2, 3]), rng.choice([-2, -1, 5, 7])]
        return [cell[i % 3] + (12 if rng.random() < 0.12 else 0)
                for i in range(k)]
    if l4 == L4.LOOP:
        lo, hi = LOOP_CELL
        cell = [rng.choice([0, 2, 3, 4, 5, 7, 9])
                for _ in range(rng.randint(lo, hi))]
        return [cell[i % len(cell)] for i in range(k)]   # verbatim repetition
    return [0]


def glide_for(l4: L4, m: int, k: int, rng: random.Random,
              common_dir: int = 1) -> tuple[float, float]:
    """(p10 target offset in scale degrees, p11 transeg curve) for note m of k.

    GLISS        one long slide, drawn direction and depth.
    CLOUDGLISS   every grain glides the SAME direction -- the cloud slides.
    DIVERGE      grain m glides outward, magnitude growing with |m - centre|,
                 sign alternating -- the cloud opens like a fan.
    SWEEPCLICK   note 0 is the sweep (large glide); the clicks do not glide.
    """
    if l4 not in GLIDE_SPEC:
        return 0.0, 0.0
    (dlo, dhi), (clo, chi) = GLIDE_SPEC[l4]
    curve = rng.uniform(clo, chi)

    if l4 == L4.GLISS:
        return rng.choice([-1, 1]) * rng.uniform(dlo, dhi), curve
    if l4 == L4.CLOUDGLISS:
        # THE WHOLE CLOUD GLIDES ONE WAY. common_dir is drawn once per pattern
        # by the caller -- drawing it per grain would give a cloud that smears
        # in both directions, which is a diverging cloud, not a gliding one.
        return common_dir * rng.uniform(dlo, dhi), curve
    if l4 == L4.DIVERGE:
        centre = (k - 1) / 2.0
        off = (m - centre) / max(1.0, centre)          # -1 .. +1
        return off * rng.uniform(dlo, dhi), curve
    if l4 == L4.SWEEPCLICK:
        if m == 0:
            return rng.choice([-1, 1]) * rng.uniform(dlo, dhi), curve
        return 0.0, 0.0
    return 0.0, 0.0


# Simultaneous patterns start together; sequential ones spread in time.
SIMULTANEOUS = {L4.CHORD, L4.HARMONY, L4.SUSTAIN}
PATTERN_SPREAD = {   # time footprint, multiple of the head note's base duration
    L4.OSTINATO: 2.6, L4.ARPEGGIO: 1.6, L4.RUN: 1.2,
    L4.CHIPARP: 1.0, L4.TRILL: 1.1, L4.SLIDE: 1.8,
    L4.GLISS: 1.0, L4.CLOUDGLISS: 3.4, L4.DIVERGE: 3.4,
    L4.SWEEPCLICK: 3.0, L4.BURSTSEQ: 2.2, L4.LOOP: 4.0,
    L4.LONGDECAY: 1.0,
}

# Families whose notes are GRAINS: short, quiet, many. The grain duration is a
# fraction of the slot, not the category's base duration -- a cloud glissando of
# plucks is a cloud of plucks, not a pile of overlapping full-length plucks.
GRAINY = {L4.CLOUDGLISS, L4.DIVERGE, L4.BURSTSEQ}

# LOOP repeats a cell VERBATIM. Drawn cell length and repeat count.
LOOP_CELL = (2, 4)

# SLIDE has no glissando in the placeholder orchestra (a real slide arrives with
# the Phase 3 instruments); it is emulated as overlapping stepwise notes with
# maximum slew, which reads as a smeared pitch movement through the tank.
SLIDE_OVERLAP = 1.9


# ------------------------------------------------------------------ L5 gestures
# Precomputed kernels, 8 samples each: the gesture's energy shape over the
# pattern. These are the "pre-computed kernels" of the spec.
GESTURE_KERNEL: dict[L5, list[float]] = {
    L5.SWELL:   [0.18, 0.32, 0.50, 0.70, 0.88, 1.00, 0.92, 0.70],
    L5.STAB:    [1.00, 0.42, 0.22, 0.14, 0.10, 0.08, 0.06, 0.05],
    L5.BURST:   [1.00, 0.95, 0.85, 0.40, 0.18, 0.10, 0.06, 0.04],
    L5.DRIFT:   [0.55, 0.62, 0.58, 0.66, 0.60, 0.64, 0.58, 0.55],
    L5.SNAP:    [1.00, 0.30, 0.10, 0.05, 0.03, 0.02, 0.02, 0.01],
    L5.SCATTER: [0.70, 0.30, 0.85, 0.25, 0.90, 0.35, 0.75, 0.30],
}

# Timing character: (jitter as fraction of slot, time concentration exponent)
GESTURE_TIME = {
    L5.SWELL:   (0.10, 1.0),
    L5.STAB:    (0.03, 1.6),    # crowded toward the front
    L5.BURST:   (0.05, 2.2),
    L5.DRIFT:   (0.35, 1.0),
    L5.SNAP:    (0.01, 2.8),
    L5.SCATTER: (0.60, 1.0),
}


# ------------------------------------------------------------- L6 articulations
@dataclass
class Artic:
    dur: float       # duration scale
    gap: float       # portion of the slot left silent (<0 = overlap)
    slew: float      # contour proposal (0 sharp .. 1 slow)
    amp: float       # level scale


ARTICS: dict[L6, Artic] = {
    L6.LEGATO:   Artic(1.15, -0.15, 0.65, 1.00),
    L6.STACCATO: Artic(0.35,  0.55, 0.10, 1.00),
    L6.TENUTO:   Artic(1.00,  0.05, 0.45, 1.05),
    L6.MARCATO:  Artic(0.80,  0.20, 0.18, 1.25),
    L6.PLUCKED:  Artic(0.70,  0.30, 0.03, 1.00),
    L6.STRUCK:   Artic(0.90,  0.25, 0.05, 1.18),
}


# --------------------------------------------------- duration by convolution
def convolve(a: list[float], b: list[float]) -> list[float]:
    """Plain full convolution. Low resolution by construction: len(a) is the
    pattern size (<=16) and len(b) is the 8-tap kernel."""
    out = [0.0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def smooth3(x: list[float]) -> list[float]:
    if len(x) < 3:
        return list(x)
    return [x[0]] + [(x[i - 1] + x[i] + x[i + 1]) / 3
                     for i in range(1, len(x) - 1)] + [x[-1]]


def duration_envelope(k: int, l5: L5, l6: L6,
                      rng: random.Random) -> list[float]:
    """Per-note duration multipliers for a k-note pattern.

    The articulation sequence (L6 base factor, jittered per note) is LITERALLY
    CONVOLVED with the gesture kernel (L5), smoothed, normalised to a mean of
    the articulation's own duration scale, and sampled at the k note positions.
    Smoothing is the envelope-follower flavour: each note's duration tracks the
    local energy of the convolution rather than its own tap alone.
    """
    art = ARTICS[l6]
    seq = [art.dur * (1.0 + rng.uniform(-0.18, 0.18)) for _ in range(k)]
    ker = GESTURE_KERNEL[l5]
    conv = smooth3(convolve(seq, ker))
    # sample k positions evenly across the convolution
    if k == 1:
        picks = [conv[len(conv) // 2]]
    else:
        picks = [conv[round(i * (len(conv) - 1) / (k - 1))] for i in range(k)]
    m = sum(picks) / len(picks) or 1.0
    return [art.dur * p / m for p in picks]


# ------------------------------------------------------------------ contour
def contour_scale(l2: L2, room: Room) -> float:
    """L2 x L3 -> L6: how much the context stretches or sharpens the slew.
    (interpretive -- see module docstring)"""
    t = {L2.ACCEL: 0.75, L2.STEADY: 1.0, L2.DECEL: 1.35}[l2]
    r = 0.75 + 0.45 * min(room.width, 1.5) / 1.5 + (0.15 if room.fb_scale > 1 else 0.0)
    return t * r
