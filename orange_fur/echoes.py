"""
echoes.py -- Phase 9. A DELAY LINE MADE OF SCORE.

Tape-music imitation, part A: trains of repeated notes with decaying volume,
generated entirely in the score. No audio delay is involved -- every echo is a
fresh note, which is exactly the point:

  * every echo is ON THE TUNING. An audio pitch-shifter's octave is 2.000; a
    score-domain "pitch-shifted feedback" steps in SCALE DEGREES, so a
    cascading echo walks the actual scale (and the octave-wrap variant folds
    with the same fold_index machinery the register uses).
  * every echo is a note the amp model, the cost router, the category
    contract, and the manifest can see. The delay is a compositional object.
  * effects impossible on tape are trivial: the DETUNED variant steps each
    repeat by a few CENTS (p12, new in this phase) -- a delay line whose
    feedback path is a microscopic transposer, beating against the dry note.

WHAT ECHOES. The delay processes PHRASES, not samples: a drawn fraction of
emitted patterns is decorated, and every note of the pattern gets the same
(delay, feedback, pitch-step) treatment -- the whole gesture repeats and
decays, which is the Frippertronics / echoplex idiom the request names.

BUDGET AND REPLAY -- a genuine design fork, resolved for replay. Counting
echo notes against the N^2 budget (first implementation) made a section that
echoes emit fewer source patterns -- "more repetitive, not bigger", the tape
aesthetic -- but it also made --echo a GENERATION parameter: changing it
changed the source composition, so a replay token no longer named one piece.
The remix-knob property won: the N^2 budget governs SOURCE notes only, echo
notes are decoration on top (reported separately, bounded by MAX_REPEATS and
the amplitude floor), and --echo joins the wetdry class of flags -- the same
piece, with more, less, or no echo. The event count grows when echoing;
density-cost routing absorbs the render cost as it does any density.

MODES, drawn per section:
  plain     repeats at the same pitch, decaying               (echoplex)
  degrees   each repeat steps +/-1..4 scale degrees, folded   (cascade)
  octave    each repeat steps a full repeat-interval, folded  (spiral)
  cents     each repeat accumulates a few cents of detune     (tape chorus)

ROTATION (Phase 11) is orthogonal to mode: ~35% of sections draw a rotating-
timbre delay, where each echo GENERATION cycles to the next instrument of a
drawn 2-4-voice cycle -- klangfarben echo, the thing no audio delay can do,
and the reason to build a delay out of score in the first place. The cycle
is drawn PER CATEGORY (fixed draw count -- stream discipline) and only ever
from the source's own category pool, so the category contract holds: a gong
never appears as echo #3 of a pluck. Amplitudes are INSTR_PEAK-compensated
so the ACOUSTIC decay follows the feedback curve even as the timbre rotates;
pitch and rhythm stay strict while color cycles -- keeping the echo identity
is what separates a klangfarben echo from a mere note sequence.

DECAY-TIME GESTURES (Phase 11): the section's train length is shaped by a
drawn contour -- up / down / arch / flat -- over section time: echo tails
audibly lengthen toward a climax, or shorten as a phrase dries out. The
gesture scales the repeat count; the amplitude floor still applies.

Delay times 100-1000 ms per the spec -- the rhythm band. The piece has had no
pulse until now; the echo train is where it gets one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace

AMP_FLOOR = 0.02          # a repeat quieter than this (relative) is dropped
MAX_REPEATS = 12
DUR_SHRINK = 0.88         # tape echoes shorten slightly per generation
CENTS_CAP = 150.0         # accumulated detune stays within +/- 1.5 semitones


@dataclass
class EchoPlan:
    prob: float           # fraction of patterns decorated in this section
    delay: float          # seconds, 0.1 .. 1.0
    fb: float             # per-repeat amplitude factor, 0.4 .. 0.8
    mode: str             # plain | degrees | octave | cents
    step: float           # degrees (degrees/octave) or cents (cents mode)
    rotlen: int = 0       # Phase 11: 0 = fixed timbre; 2-4 = cycle length
    dgest: str = "flat"   # Phase 11: train-length contour over the section

    def describe(self) -> str:
        unit = {"plain": "", "degrees": f" step {self.step:+.0f} deg",
                "octave": f" step {self.step:+.0f} deg (octave fold)",
                "cents": f" step {self.step:+.1f} c"}[self.mode]
        rot = f"  rot({self.rotlen})" if self.rotlen else ""
        dg = f"  tails:{self.dgest}" if self.dgest != "flat" else ""
        return (f"{self.mode}{unit}  d={self.delay * 1000:.0f}ms "
                f"fb={self.fb:.2f}  p={self.prob:.2f}{rot}{dg}")


def gest_scale(dgest: str, u: float) -> float:
    """Train-length factor at section-relative time u in [0,1]."""
    if dgest == "up":
        return 0.4 + 1.2 * u
    if dgest == "down":
        return 1.6 - 1.2 * u
    if dgest == "arch":
        return 0.4 + 1.2 * (1.0 - abs(2.0 * u - 1.0))
    return 1.0


def draw_plan(rng: random.Random, grades: int) -> EchoPlan:
    mode = rng.choices(["plain", "degrees", "octave", "cents"],
                       weights=[0.30, 0.30, 0.15, 0.25])[0]
    if mode == "degrees":
        step = rng.choice([-4, -3, -2, -1, 1, 2, 3, 4])
    elif mode == "octave":
        step = rng.choice([-1, 1]) * grades
    elif mode == "cents":
        step = rng.choice([-1, 1]) * rng.uniform(3.0, 25.0)
    else:
        step = 0.0
    rotlen = rng.choice([2, 3, 4]) if rng.random() < 0.35 else 0
    dgest = rng.choices(["flat", "up", "down", "arch"],
                        weights=[0.45, 0.2, 0.2, 0.15])[0]
    return EchoPlan(prob=rng.uniform(0.15, 0.45),
                    delay=rng.uniform(0.10, 1.00),
                    fb=rng.uniform(0.40, 0.80),
                    mode=mode, step=step, rotlen=rotlen, dgest=dgest)


def draw_cycles(rng: random.Random, plan: EchoPlan, catmap: dict) -> dict:
    """Per-category instrument cycles for a rotating section. A FIXED number
    of draws is consumed for every category in a fixed order, whether or not
    the category's pool exists or the section ever echoes that category --
    the RNG stream must not depend on what happens to be emitted."""
    cycles: dict = {}
    for cat in sorted(catmap.keys(), key=int):
        pool = catmap[cat]
        picks = [rng.random() for _ in range(plan.rotlen or 0)]
        if plan.rotlen and pool:
            cycles[int(cat)] = [pool[int(r * len(pool)) % len(pool)]
                                for r in picks]
    return cycles


def n_repeats(plan: EchoPlan) -> int:
    """Repeats until the train falls under the amplitude floor."""
    n, a = 0, 1.0
    while n < MAX_REPEATS:
        a *= plan.fb
        if a < AMP_FLOOR:
            break
        n += 1
    return n


def echo_pattern(pattern_events: list, plan: EchoPlan, fold,
                 cycles: dict | None = None, peaks: dict | None = None,
                 u: float = 0.0) -> list:
    """Derive the echo train for one pattern's events. `fold` is
    score.fold_index partially applied (basekey and grades bound).

    Phase 11: `cycles` maps category -> instrument cycle for rotating
    sections; generation k sounds on cycle[(k-1) %% len]. `peaks` is the
    INSTR_PEAK registry: when the timbre rotates, amp is scaled by
    peak(source)/peak(target) (clamped 0.25-4) so the heard decay follows
    the feedback curve, not the instruments' calibration spread. `u` is
    section-relative time for the decay-time gesture."""
    out = []
    reps = max(1, min(MAX_REPEATS,
                      int(round(n_repeats(plan)
                                * gest_scale(plan.dgest, u)))))
    for k in range(1, reps + 1):
        for e in pattern_events:
            idx, det = e.index, e.det
            if plan.mode in ("degrees", "octave"):
                idx = fold(e.index + int(round(plan.step * k)))
            elif plan.mode == "cents":
                det = max(-CENTS_CAP, min(CENTS_CAP,
                                          e.det + plan.step * k))
            instr = e.instr
            amp = e.amp * (plan.fb ** k)
            cyc = cycles.get(e.cat) if cycles else None
            if cyc:
                instr = cyc[(k - 1) % len(cyc)]
                if peaks and instr != e.instr:
                    src = peaks.get(e.instr, 1.0) or 1.0
                    tgt = peaks.get(instr, 1.0) or 1.0
                    amp *= max(0.25, min(4.0, src / tgt))
            # an inherited glide offset is relative to the SOURCE index; a
            # cascade that shifted idx must re-derive it through the fold
            # (which carries the harmonic field when one is active), or the
            # echo's arrival lands off-field
            gl = e.glide
            if gl and abs(gl) >= 1.0:
                gl = fold(idx + int(round(gl))) - idx
            out.append(replace(
                e, start=e.start + plan.delay * k, instr=instr,
                amp=amp,
                dur=max(0.02, e.dur * (DUR_SHRINK ** k)),
                index=idx, det=det, glide=gl, echo=k))
    return out
