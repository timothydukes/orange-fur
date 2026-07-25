"""
roughness.py -- Phase 19. SENSORY DISSONANCE AS A COMPOSITIONAL DIMENSION.

Plomp-Levelt pairwise roughness in the Sethares parameterization, computed
from the DRAWN ORCHESTRA'S OWN SPECTRA -- the system knows what its
instruments sound like, so tension can be a measured quantity, not a
metaphor. Four templates carry their literal partial lists (bank, modal,
tcloud, bankswell -- annotated at construction); the rest use template-
class spectra below, an honest approximation stated as such.

CALIBRATION: raw roughness scales with amplitude^2 and partial count and
means nothing as an absolute. Each run samples K reference sonorities from
its own orchestra and fields (fixed draw count) and maps roughness through
their empirical CDF -- "tension 0.8" means "rougher than 80% of what this
orchestra does to itself," transferable across tunings and subsets.

TENSION TRAJECTORY: each section draws a target segment (start, end, shape)
with L1-name-driven ranges, chained so the piece has one continuous
contour realized in segments. The three insertion points in fields.py /
score.py select among candidates to approach the target; `--tension X`
scales how strongly (0 = candidate 0 always = the pre-P19 draw).
"""

from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass

# Sethares 1993 constants
B1, B2 = 3.5, 5.75
S1, S2, XSTAR = 0.0207, 18.96, 0.24

# template-class spectra for templates without literal partial lists:
# (ratio, weight) pairs, weights ~normalized. Approximations, documented.
TEMPLATE_SPECTRA = {
    "pwm":        [(n, 1.0 / n) for n in (1, 3, 5, 7, 9, 11)],
    "mslave":     [(n, 1.0 / n) for n in range(1, 9)],
    "pluck":      [(n, 1.0 / n ** 1.5) for n in range(1, 11)],
    "sync_pluck": [(n, 1.0 / n ** 1.2) for n in range(1, 11)],
    "fb_shaper":  [(n, 1.0 / n ** 0.8) for n in range(1, 9)],
    "pipe":       [(n ** 1.4, 1.0 / n) for n in range(1, 8)],
    "wtx":        [(n, 1.0 / n) for n in range(1, 10)],
    "pll":        [(0.5, 0.5)] + [(n, 1.0 / n) for n in range(1, 7)],
    "wtswell":    [(n, 1.0 / n) for n in range(1, 8)],
    # broadband click material: sparse proxy; roughness contribution small
    "click":      [(1.0, 0.4), (2.7, 0.2), (5.3, 0.1)],
    "burst":      [(1.0, 0.4), (3.1, 0.2), (6.9, 0.1)],
    "tick":       [(1.0, 0.3), (4.2, 0.15)],
    # Phase 20 SURFACE family: broadband proxies (resonant-colored noise);
    # small roughness contributions by design
    "crackle":    [(1.0, 0.35), (2.3, 0.15), (5.1, 0.08)],
    "dustpop":    [(1.0, 0.4), (3.4, 0.12)],
    "hiss":       [(1.0, 0.25), (1.9, 0.2), (3.7, 0.1)],
    "transwash":  [(1.0, 0.3), (2.6, 0.18)],
}


def _norm(parts):
    t = sum(w for _, w in parts) or 1.0
    return [(r, w / t) for r, w in parts]


TEMPLATE_SPECTRA = {k: _norm(v) for k, v in TEMPLATE_SPECTRA.items()}
FALLBACK = _norm([(n, 1.0 / n) for n in range(1, 7)])


def spectrum_of(instr) -> list:
    if getattr(instr, "partials", None):
        return instr.partials
    return TEMPLATE_SPECTRA.get(getattr(instr, "template", ""), FALLBACK)


def pair_dissonance(f1: float, a1: float, f2: float, a2: float) -> float:
    """Plomp-Levelt roughness of two partials (Sethares model)."""
    if f2 < f1:
        f1, f2, a1, a2 = f2, f1, a2, a1
    s = XSTAR / (S1 * f1 + S2)
    df = f2 - f1
    return a1 * a2 * (math.exp(-B1 * s * df) - math.exp(-B2 * s * df))


SCORE_TOP = 6      # partials per spectrum used in SCORING paths (cost);
                   # full spectra remain available for offline analysis


def top_partials(spec: list, k: int = SCORE_TOP) -> list:
    return sorted(spec, key=lambda t: -t[1])[:k]


def sonority_roughness(notes: list) -> float:
    """notes: [(cps, amp, spectrum)] with spectrum = [(ratio, w)]. Sum of
    pairwise partial roughness ACROSS notes (a note's internal roughness is
    timbre, not harmony -- excluded so a single gong isn't 'tense')."""
    expanded = []
    for cps, amp, spec in notes:
        expanded.append([(cps * r, amp * w) for r, w in spec])
    total = 0.0
    for i in range(len(expanded)):
        for j in range(i + 1, len(expanded)):
            for f1, a1 in expanded[i]:
                for f2, a2 in expanded[j]:
                    total += pair_dissonance(f1, a1, f2, a2)
    return total


# ---------------------------------------------------------------- calibration
K_CAL = 64


class Calibration:
    """Empirical CDF of the run's own roughness. Percentile in [0, 1]."""

    def __init__(self, samples: list):
        self.samples = sorted(samples)

    def percentile(self, r: float) -> float:
        """Linearly interpolated empirical CDF -- the step CDF's 1/K
        granularity tied 35%% of 3-candidate scoring calls (identical
        percentile for distinct roughness), leaving selection inert."""
        if not self.samples:
            return 0.5
        K = len(self.samples)
        if K == 1:
            return 0.0 if r < self.samples[0] else 1.0
        i = bisect.bisect_right(self.samples, r)
        if i == 0:
            return 0.0
        if i >= K:
            return 1.0
        a, b = self.samples[i - 1], self.samples[i]
        frac = (r - a) / (b - a) if b > a else 0.0
        return ((i - 1) + frac) / (K - 1)


def calibrate(rng: random.Random, insts: list, cps, basekey: int,
              grades: int) -> Calibration:
    """K_CAL reference sonorities of 2-8 notes -- MATCHING the polyphony
    range the achieved-measurement and note scoring read (a 2-5 calibration
    saturated busy sections at percentile ~1 regardless of harmony). FIXED
    draw count: K_CAL * (1 + 8*2) regardless of orchestra size."""
    out = []
    for _ in range(K_CAL):
        n = 2 + int(rng.random() * 7)
        notes = []
        for k in range(8):                       # 8 slots always drawn
            ri = rng.random()
            rd = rng.random()
            if k >= n:
                continue
            inst = insts[int(ri * len(insts)) % len(insts)]
            deg = basekey + int((rd - 0.5) * 3 * grades)
            notes.append((cps(deg), 0.4, spectrum_of(inst)))
        out.append(sonority_roughness(notes))
    return Calibration(out)


# ------------------------------------------------------------ tension targets
L1_TENSION = {
    "INTRO":     (0.05, 0.35),
    "VERSE":     (0.25, 0.60),
    "CHORUS":    (0.45, 0.80),
    "BREAKDOWN": (0.60, 0.95),
    "OUTRO":     (0.05, 0.45),
}
SHAPES = ["flat", "rise", "fall", "arch"]


@dataclass
class TensionSeg:
    t_start: float      # tension value at section start
    t_end: float
    shape: str

    def at(self, u: float) -> float:
        u = min(1.0, max(0.0, u))
        if self.shape == "flat":
            return self.t_start
        if self.shape == "arch":
            peak = max(self.t_start, self.t_end) + 0.15
            return (self.t_start + (peak - self.t_start) * (u * 2)
                    if u < 0.5 else
                    peak + (self.t_end - peak) * ((u - 0.5) * 2))
        return self.t_start + (self.t_end - self.t_start) * u

    def describe(self) -> str:
        return f"{self.t_start:.2f}->{self.t_end:.2f} {self.shape}"


def draw_tension(rng: random.Random, sec_name: str,
                 prev: "TensionSeg | None") -> TensionSeg:
    """Chained: a section starts near where the last ended. Fixed draws."""
    lo, hi = L1_TENSION.get(sec_name, (0.25, 0.60))
    r_shape = rng.random()
    r_end = rng.uniform(lo, hi)
    r_jit = rng.uniform(-0.08, 0.08)
    r_start0 = rng.uniform(lo, min(hi, lo + 0.2))   # drawn unconditionally
    start = (min(1.0, max(0.0, prev.t_end + r_jit)) if prev is not None
             else r_start0)
    shape = SHAPES[int(r_shape * len(SHAPES)) % len(SHAPES)]
    if shape == "flat":
        r_end = start
    elif shape == "rise":       # truthful labels WITHOUT breaking the
        r_end = max(r_end, start)      # chain: the start stays where the
    elif shape == "fall":              # previous section left it; the END
        r_end = min(r_end, start)      # moves to honor the label
    return TensionSeg(t_start=start, t_end=r_end, shape=shape)


# ------------------------------------------------------------- selection rule
def select(scores: list, x: float) -> int:
    """scores[i] = closeness of candidate i to the target (higher = better).
    x = --tension. Deterministic, no draws: candidate 0 at x = 0 (the
    pre-P19 draw), the best at x = 1, a monotone blend between --
    eff_i = x * score_i + (1 - x) * [i == 0]."""
    best, bi = -1e18, 0
    for i, sc in enumerate(scores):
        eff = x * sc + (1.0 - x) * (1.0 if i == 0 else 0.0)
        if eff > best:
            best, bi = eff, i
    return bi
