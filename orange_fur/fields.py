"""
fields.py -- Phase 13 harmonic fields, extended in Phase 15 with SPECTRAL
field families: fields whose targets are TRUE PARTIALS, off the lattice.

Phase 13 gave sections harmonic identity as pitch-class subsets of the
tuning. Phase 15 lets a drawn fraction of sections (--spectral PCT) derive
their field from a SPECTRUM instead:

  sumdiff  Ring-modulation harmony (Grisey/Murail): two generator degrees;
           the field is their sum and difference tones (and low-harmonic
           sums/differences). Simple generator intervals give consonant
           complexes; complex ones give rough, bell-like fields.

  vf       Instrumental synthesis: a virtual fundamental with a partial
           model -- harmonic (n*f0), stretched (n^s, s>1), or compressed
           (s<1) -- realized as the section's harmony. The section is a
           chord that is a timbre.

Both families compute target FREQUENCIES, then express each as the nearest
lattice degree PLUS A CENTS RESIDUAL. The residual rides p12, so the
sonority is the true spectrum, exactly -- the .scl lattice becomes the grid
the spectrum is measured against, not the pitch authority. Lattice fields
(the Phase 13 draw) remain the default and carry zero cents everywhere,
preserving pre-P15 behavior at --spectral 0.

STREAM DISCIPLINE: every section draws BOTH a lattice field and a full set
of spectral parameters, unconditionally; --spectral only gates which one
becomes the section's field. Consequence: --spectral 0 and --spectral 100
share a replay token -- the same piece skeleton, harmony realized on or off
the lattice.

The snap contract is now (index, cents): lattice pcs snap with cents 0,
spectral targets snap with their residual. Sub-degree ornamental bends and
echo cents drift ride ON TOP of the field cents, as p12 always has.

SUSPENSIONS (Phase 13 semantics) are unchanged: a note conforms to the
field of the section that emitted it.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field as dfield

SIZE = (3, 7)         # lattice field size band
KEEP_FRAC = 0.5       # tones carried into the next lattice field
def _half_step_cap(cps, basekey: int, grades: int) -> float:
    """Half the tuning's largest adjacent step, in cents, plus slack. A
    legitimate nearest-degree residual can never exceed this; anything
    bigger means the frequency fell outside the searched register (e.g. a
    very low difference tone) and snapped to a boundary index -- reject it
    rather than file a wrong target. (Found the hard way: sub-span
    difference tones produced pc 0 at +111 cents.)"""
    steps = [1200.0 * math.log2(cps(basekey + i + 1) / cps(basekey + i))
             for i in range(grades)]
    return max(steps) / 2.0 + 5.0


def _freq_to_target(freq: float, cps, basekey: int, grades: int,
                    span: int = 3, cap: float | None = None
                    ) -> tuple[int, float] | None:
    """Frequency -> (pitch class, cents residual vs the nearest degree).
    Searches indices within `span` repeat-intervals of the basekey; returns
    None when the frequency lies outside that register (residual > cap)."""
    if freq <= 0:
        return None
    if cap is None:
        cap = _half_step_cap(cps, basekey, grades)
    best = None
    for idx in range(basekey - span * grades, basekey + span * grades + 1):
        c = cps(idx)
        if c <= 0:
            continue
        cents = 1200.0 * math.log2(freq / c)
        if best is None or abs(cents) < abs(best[1]):
            best = (idx, cents)
    if best is None or abs(best[1]) > cap:
        return None
    pc = (best[0] - basekey) % grades
    return pc, best[1]


@dataclass
class Field:
    pcs: frozenset          # pitch classes with a target (lattice: all c=0)
    grades: int
    cents: dict = dfield(default_factory=dict)   # pc -> cents residual
    family: str = "lattice"                      # lattice | sumdiff | vf
    label: str = ""                              # extra report detail

    def describe(self) -> str:
        def one(p):
            c = self.cents.get(p, 0.0)
            return f"{p}{c:+.0f}c" if abs(c) >= 0.5 else str(p)
        body = "{" + ",".join(one(p) for p in sorted(self.pcs)) + "}"
        tag = "" if self.family == "lattice" else f" {self.family}{self.label}"
        return body + tag

    def snap(self, idx: int, basekey: int) -> tuple[int, float]:
        """Nearest index whose pitch class is in the field, plus that pitch
        class's cents residual. Ties resolve downward. Lattice fields return
        cents 0.0 everywhere -- the pre-P15 contract exactly."""
        pc = (idx - basekey) % self.grades
        if pc in self.pcs:
            return idx, self.cents.get(pc, 0.0)
        for d in range(1, self.grades):
            for cand in (idx - d, idx + d):        # downward first: tie->down
                cpc = (cand - basekey) % self.grades
                if cpc in self.pcs:
                    return cand, self.cents.get(cpc, 0.0)
        return idx, 0.0


def draw_field(rng: random.Random, grades: int,
               prev: Field | None = None) -> Field:
    """The Phase 13 LATTICE draw, unchanged: always contains pc 0, chains
    ~half its tones from the previous lattice field."""
    size = rng.randint(SIZE[0], min(SIZE[1], grades))
    pcs = {0}
    if prev is not None:
        keep = [p for p in sorted(prev.pcs) if p != 0]
        rng.shuffle(keep)
        pcs.update(keep[:int(round(len(keep) * KEEP_FRAC))])
    pool = [p for p in range(1, grades) if p not in pcs]
    rng.shuffle(pool)
    for p in pool:
        if len(pcs) >= size:
            break
        pcs.add(p)
    return Field(pcs=frozenset(pcs), grades=grades)


def draw_sumdiff(rng: random.Random, grades: int, basekey: int, cps) -> Field:
    """Ring-modulation field: generators g1 < g2 within ~1.5 repeat
    intervals; targets are the generators, their sum and difference tones,
    and first-harmonic sums/differences, folded to pitch classes with cents
    residuals. Generator interval simplicity is the drawn consonance knob."""
    g1 = basekey + rng.randint(-grades // 2, grades // 2)
    step = rng.choice([3, 4, 5, 7, 7, 9, 12, 14, 16])   # small = consonant
    g2 = g1 + step
    f1, f2 = cps(g1), cps(g2)
    freqs = [f1, f2, f1 + f2, abs(f2 - f1),
             2 * f1 + f2, abs(2 * f1 - f2), f1 + 2 * f2, abs(f1 - 2 * f2)]
    cap = _half_step_cap(cps, basekey, grades)
    pcs, cents = set(), {}
    for fr in freqs:
        t = _freq_to_target(fr, cps, basekey, grades, cap=cap)
        if t is None:
            continue
        pc, c = t
        if pc not in pcs:
            pcs.add(pc)
            cents[pc] = c
        if len(pcs) >= 7:
            break
    if 0 not in pcs:
        pcs.add(0)
        cents[0] = 0.0
    return Field(pcs=frozenset(pcs), grades=grades, cents=cents,
                 family="sumdiff", label=f"({g1 - basekey:+d},{step:+d})")


def draw_vf(rng: random.Random, grades: int, basekey: int, cps) -> Field:
    """Virtual-fundamental field: f0 from a drawn low degree; partials
    n = 1..K under a model -- harmonic (s = 1), stretched (s > 1),
    compressed (s < 1): f_n = f0 * n^s. The section is a chord that is a
    timbre."""
    f0 = cps(basekey + rng.choice([-24, -19, -12, -12, -7]))
    s = rng.choice([1.0, 1.0, 1.0,
                    rng.uniform(1.01, 1.08),
                    rng.uniform(0.93, 0.99)])
    kmax = rng.randint(5, 9)
    cap = _half_step_cap(cps, basekey, grades)
    pcs, cents = set(), {}
    for n in range(1, kmax + 1):
        t = _freq_to_target(f0 * (n ** s), cps, basekey, grades, cap=cap)
        if t is None:
            continue
        pc, c = t
        if pc not in pcs:
            pcs.add(pc)
            cents[pc] = c
        if len(pcs) >= 7:
            break
    if 0 not in pcs:
        pcs.add(0)
        cents[0] = 0.0
    return Field(pcs=frozenset(pcs), grades=grades, cents=cents,
                 family="vf", label=f"(s={s:.2f})" if s != 1.0 else "(harm)")


def draw_section_candidates(rng: random.Random, grades: int, basekey: int,
                            cps, prev_lattice: Field | None,
                            spectral_pct: float, n: int = 4) -> list:
    """Phase 19: n independent candidate draws of the SAME shape (each its
    own gate + families, all chained from the same prev_lattice). Fixed
    layout: n identical blocks. The tension machinery selects one; at
    --tension 0 candidate 0 is taken unconditionally, which is the pre-P19
    single draw bit-for-bit."""
    return [draw_section_field(rng, grades, basekey, cps,
                               prev_lattice, spectral_pct)
            for _ in range(n)]


def draw_section_field(rng: random.Random, grades: int, basekey: int, cps,
                       prev_lattice: Field | None, spectral_pct: float
                       ) -> tuple[Field, Field]:
    """The per-section draw. ALL parameters for lattice AND both spectral
    families are drawn unconditionally; spectral_pct gates only which field
    the section uses. Returns (field, lattice) -- the lattice chain advances
    regardless, so --spectral 0/100 share a token AND the lattice world is
    identical whenever a section falls back to it."""
    lattice = draw_field(rng, grades, prev_lattice)
    gate = rng.random()
    fam = rng.random()
    sd = draw_sumdiff(rng, grades, basekey, cps)
    vf = draw_vf(rng, grades, basekey, cps)
    if gate < spectral_pct / 100.0:
        return (sd if fam < 0.5 else vf), lattice
    return lattice, lattice
