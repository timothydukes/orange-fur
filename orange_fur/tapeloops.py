"""
tapeloops.py -- Phase 10. LOOPING TAPE DELAY, made of score.

Tape-music imitation, part B: two (occasionally three) tape loops of the same
short cell, running at NOT QUITE identical periods -- T and T(1+eps), eps a
fraction of a percent -- at near-100% feedback. The accumulating offset IS the
phasing: after k repetitions the second loop trails the first by k*T*eps, the
cell slides against itself through every intermediate canon, and after 1/eps
repetitions the loops REALIGN. That realignment time, T/eps, is computable at
generation time and is printed in the manifest -- the piece's formal event,
predicted in text. This is the It's-Gonna-Rain / Piano-Phase mechanism, in
whatever tuning system the run is using.

Everything is microtiming: no audio delay, no tempo grid -- each loop voice is
a stream of notes whose starts drift apart by arithmetic.

THE PROTECTED-PROCESS RULE (established here; motif recurrence inherits it).
A phasing loop only reads as phasing if the repeated cell is PERCEPTUALLY
IDENTICAL every pass. Three machineries would ordinarily break that:

  * the macro DENSITY track culls notes -- a culled repetition is a gap in
    the pattern, not a phase relationship. Loop notes bypass the cull.
  * the macro REGISTER staircase steps pitch -- a cell that transposes mid-
    process is a sequence, not a loop. Loop notes ignore the register offset.
  * density->cost ROUTING rebinds notes to cheap voices -- a loop whose
    repetitions change instrument mid-stream loses its identity. Loop notes
    carry a process id, and cost_route moves a process ATOMICALLY: all of a
    loop's notes rebind together or not at all.

The macro ACCENT contour still applies -- macro-dynamics sequencing the
loop's loudness is wanted, and dynamics do not threaten identity.

RARITY. Gong-class: a phasing section is polarizing and must not happen every
run. The per-section probability is drawn low; the draw itself is
unconditional (stream discipline).

Loop notes are marked echo = -2 (excluded from the N^2 source-budget
accounting, like echo decoration) and proc = <id> (the atomic-routing handle).
Cells never use GONG instruments (the gongs-rare contract outranks the loop).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .alphabet import Cat

LOOP_CATS = [Cat.PLUCK, Cat.PARTIAL, Cat.TCLOUD, Cat.CLOUD]
DECAY = (0.985, 0.999)        # per-repetition amplitude factor: near-100% fb
PROB = (0.10, 0.22)           # per-section probability band (drawn)


@dataclass
class CellNote:
    off: float                # offset within the cell, seconds
    dur: float
    degree: int               # offset from the section's base degree
    amp: float


@dataclass
class LoopPlan:
    prob: float
    cell: list[CellNote]
    cat: Cat
    voices: int               # 2, occasionally 3
    period: float             # T of voice 0, seconds
    eps: float                # fractional period offset per voice
    decay: float
    span_frac: float          # fraction of the section the loop occupies
    pans: list[float] = field(default_factory=list)

    @property
    def realign(self) -> float:
        """Seconds until voice 1 has slipped one full period against voice 0."""
        return self.period / self.eps

    def describe(self, t0: float, span: float) -> str:
        r = self.realign
        run = span * self.span_frac
        inside = "inside the loop" if r <= run else "beyond it"
        return (f"{len(self.cell)}-note cell x{self.voices} voices  "
                f"T={self.period:.2f}s  eps={self.eps * 100:.2f}%  "
                f"realign at +{r:.1f}s ({inside})")


def draw_plan(rng: random.Random, span: float = 60.0) -> LoopPlan:
    """Drawn unconditionally per section (stream discipline); prob gates
    whether the loop is emitted.

    EPS IS DRAWN AGAINST THE SECTION. The first version drew eps blind
    (0.2-2%), and every realignment landed 160-200 s out -- past the end of
    every loop, so the payoff moment never arrived. Now 65% of draws pick
    the REALIGNMENT TIME directly, inside the loop's run (realign = run *
    0.6..1.25, eps = T/realign): the loops audibly slip, pass through the
    intermediate canons, and lock again before the section ends. The other
    35% keep the slow-smear band (eps 0.4-1.5%), where the drift is felt
    rather than resolved -- both are real tape musics."""
    ncell = rng.randint(2, 5)
    period = rng.uniform(1.0, 4.0)
    # cell offsets: sorted within the period, first at 0 (the downbeat of
    # the loop -- phasing needs an anchor to slide against)
    offs = sorted([0.0] + [rng.uniform(0.06, period * 0.92)
                           for _ in range(ncell - 1)])
    cell = [CellNote(off=o,
                     dur=rng.uniform(0.08, min(0.6, period * 0.45)),
                     degree=rng.choice([0, 2, 3, 4, 5, 7, 9, 12]),
                     amp=rng.uniform(0.5, 1.0))
            for o in offs]
    voices = 3 if rng.random() < 0.18 else 2
    pans = {2: [0.18, 0.82], 3: [0.12, 0.5, 0.88]}[voices]
    span_frac = rng.uniform(0.55, 0.92)
    run = max(8.0, span * span_frac)
    if rng.random() < 0.65:
        realign = run * rng.uniform(0.55, 0.95)
        eps = max(0.002, min(0.12, period / realign))
    else:
        eps = rng.uniform(0.004, 0.015)
    return LoopPlan(prob=rng.uniform(*PROB), cell=cell,
                    cat=rng.choice(LOOP_CATS), voices=voices,
                    period=period, eps=eps,
                    decay=rng.uniform(*DECAY),
                    span_frac=span_frac, pans=pans)


def emit(plan: LoopPlan, t0: float, span: float, base_index: int,
         instr: int, send: float, accent_gain, fold, proc_id: int,
         dur_cap: float) -> list:
    """Emit the loop's notes. `accent_gain(t)` is the macro accent contour
    (dynamics ARE applied); density culling and register stepping are NOT
    (the protected-process rule). `fold` bounds pitch; `dur_cap` is the
    absolute end (piece bus close) every note must respect."""
    from .score import Event      # local import: score imports this module
    run = span * plan.span_frac
    out = []
    for v in range(plan.voices):
        tv = plan.period * (1.0 + plan.eps * v)
        k = 0
        while t0 + k * tv < t0 + run:
            rep_start = t0 + k * tv
            g = plan.decay ** k
            for cn in plan.cell:
                st = rep_start + cn.off * (tv / plan.period)   # cell scales
                if st >= t0 + run:
                    continue
                out.append(Event(
                    instr=instr, start=st,
                    dur=min(cn.dur, max(0.02, dur_cap - st)),
                    index=fold(base_index + cn.degree),
                    amp=cn.amp * g * accent_gain(st),
                    pan=plan.pans[v], send=send,
                    slew=0.12, cat=int(plan.cat), wave=0,
                    echo=-2, proc=proc_id,
                ))
            k += 1
    return out
