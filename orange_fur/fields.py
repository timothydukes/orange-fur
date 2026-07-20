"""
fields.py -- Phase 13. HARMONIC FIELDS.

A per-section subset of the scale's degrees -- a pitch-class field -- that
every pitched emission conforms to. The tuning table defines what pitches
EXIST; the field decides which of them a section is ABOUT. Sections stop
being merely denser or sparser regions of the same total chromatic and
acquire harmonic identity: this section lives on {0,2,5,7,9}, the next
moves three of those tones and keeps the rest.

MECHANISM. One composed function, snap(fold(i)), applied at every pitched
emission site -- patterns, budget top-ups, glide targets, gap bridges, echo
cascades, tape-loop cells, motif quotes. snap() maps a degree index to the
nearest index whose pitch class lies in the field (ties resolve DOWNWARD --
leading-tone-resolves-down is as good a convention as any, and determinism
is what matters). Conformance costs no RNG draws, so --fields 0/1 share a
replay token: the same composition, harmonically constrained or free.

FIELD CHANGES AT SECTION BOUNDARIES, like rooms -- the precedent for clean
cuts. Successive fields keep roughly half their tones (drawn), so motion
between sections is voice-leading rather than teleportation: common tones
sustain their meaning, moved tones re-color it.

SUSPENSIONS. A note conforms to the field of the section that EMITTED it. A
slow pattern conceived late in one section can place notes past the
boundary; those carry their own harmony into the new field -- suspensions,
in the old sense -- and are correct, not leaks. In practice they are a few
per cent of events at boundaries.

INTERPRETIVE DECISION (flagged): motif quotes and loop cells CONFORM to the
field they land in -- contour and rhythm carry the memory; pitch content
joins the present harmony. A verbatim quote against a changed field reads
as a wrong note, not a memory. The opposite policy (quotation fidelity) is
one line: stop composing snap into the fold passed to those emitters.

p12 cents detune is untouched: the field constrains the DEGREE lattice; the
microtonal offsets ride on top of whatever degree the note lands on.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

SIZE = (3, 7)         # field size band (of numgrades pitch classes)
KEEP_FRAC = 0.5       # tones carried into the next section's field


@dataclass
class Field:
    pcs: frozenset          # pitch classes, 0 <= pc < grades
    grades: int

    def describe(self) -> str:
        return "{" + ",".join(str(p) for p in sorted(self.pcs)) + "}"

    def snap(self, idx: int, basekey: int) -> int:
        """Nearest index (in degrees) whose pitch class is in the field.
        Ties resolve downward. Identity when already conformant."""
        pc = (idx - basekey) % self.grades
        if pc in self.pcs:
            return idx
        best = None
        for d in range(1, self.grades):
            for cand in (idx - d, idx + d):        # downward first: tie->down
                if ((cand - basekey) % self.grades) in self.pcs:
                    best = cand
                    break
            if best is not None:
                break
        return best if best is not None else idx


def draw_field(rng: random.Random, grades: int,
               prev: Field | None = None) -> Field:
    """Drawn per section. Always contains pc 0 (the basekey anchor). When a
    previous field exists, about half its tones are kept -- drawn common
    tones -- and the rest are fresh. Draw counts depend only on drawn sizes,
    never on emitted content (stream discipline)."""
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
