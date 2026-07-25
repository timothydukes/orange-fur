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

import math
import random
from dataclasses import dataclass, field, replace

from .macro import bjorklund
from . import echocfg

AMP_FLOOR = 0.02          # a repeat quieter than this (relative) is dropped
MAX_REPEATS = 12
DUR_SHRINK = 0.88         # tape echoes shorten slightly per generation
CENTS_CAP = 150.0         # accumulated detune stays within +/- 1.5 semitones


RAMP_CENTS_CAP = 700.0    # varispeed smear saturates here, not at the
                          # ordinary drift cap -- tape physics is steep


@dataclass
class EchoPlan:
    prob: float           # fraction of patterns decorated in this section
    delay: float          # seconds (uniform family), 0.1 .. 1.0
    fb: float             # per-repeat amplitude factor
    mode: str             # plain | degrees | octave | cents
    step: float           # degrees (degrees/octave) or cents (cents mode)
    rotlen: int = 0       # Phase 11: 0 = fixed timbre; 2-4 = cycle length
    dgest: str = "flat"   # Phase 11: train-length contour over the section
    timing: str = "uniform"          # Phase 17: uniform|multitap|euclid|ramp
    tp: dict = field(default_factory=dict)   # timing-family parameters
    pan: str = "inherit"             # Phase 17: inherit|pingpong|rotate
    so: bool = False                 # Phase 17: second-order echoes

    def describe(self) -> str:
        unit = {"plain": "", "degrees": f" step {self.step:+.0f} deg",
                "octave": f" step {self.step:+.0f} deg (octave fold)",
                "cents": f" step {self.step:+.1f} c"}[self.mode]
        if self.timing == "multitap":
            t = f"multitap[{self.tp['ntaps']}] c={self.tp['cycle']:.2f}s"
        elif self.timing == "euclid":
            t = (f"euclid({self.tp['pulses']},{self.tp['steps']}) "
                 f"c={self.tp['cycle']:.2f}s")
        elif self.timing == "ramp":
            cpr = -1200.0 * math.log2(self.tp["ratio"])
            t = f"ramp r={self.tp['ratio']:.2f} {cpr:+.0f}c/rep"
        else:
            t = f"d={self.delay * 1000:.0f}ms"
        rot = f"  rot({self.rotlen})" if self.rotlen else ""
        dg = f"  tails:{self.dgest}" if self.dgest != "flat" else ""
        pn = {"inherit": "", "pingpong": "  pp", "rotate": "  rot-pan"}[self.pan]
        so = "  +2nd" if self.so else ""
        return (f"{self.mode}{unit}  {t} "
                f"fb={self.fb:.2f}  p={self.prob:.2f}{rot}{dg}{pn}{so}")


def gest_scale(dgest: str, u: float) -> float:
    """Train-length factor at section-relative time u in [0,1]."""
    if dgest == "up":
        return 0.4 + 1.2 * u
    if dgest == "down":
        return 1.6 - 1.2 * u
    if dgest == "arch":
        return 0.4 + 1.2 * (1.0 - abs(2.0 * u - 1.0))
    return 1.0


MAXTAPS = 5


def draw_plan(rng: random.Random, grades: int,
              ecfg: "echocfg.EchoConfig | None" = None) -> EchoPlan:
    """Phase 17: FIXED DRAW LAYOUT. Every family's parameters, all MAXTAPS
    tap slots, pan and second-order draws are consumed EVERY section
    regardless of the config's weights; selection happens after. Config-
    driven VALUES may differ between configs; draw COUNTS may not -- that is
    what lets any two echo-specs (or none) share a replay token."""
    ec = ecfg or echocfg.EchoConfig()

    mode_r = rng.random()
    deg_step = rng.choice([-4, -3, -2, -1, 1, 2, 3, 4])
    oct_sign = rng.choice([-1, 1])
    cents_sign = rng.choice([-1, 1])
    cents_mag = rng.uniform(3.0, 25.0)
    prob = rng.uniform(0.15, 0.45)
    rot_gate = rng.random()
    rot_len = rng.randint(ec.rotation["len"][0], ec.rotation["len"][1])
    dgest_r = rng.random()
    timing_r = rng.random()
    u_delay = rng.uniform(*ec.uniform["delay"])
    u_fb = rng.uniform(*ec.uniform["fb"])
    mt_ntaps = rng.randint(ec.multitap["taps"][0], ec.multitap["taps"][1])
    mt_cycle = rng.uniform(*ec.multitap["cycle"])
    mt_fb = rng.uniform(*ec.multitap["fb"])
    mt_offs = [rng.uniform(0.05, 0.95) for _ in range(MAXTAPS)]
    mt_att = [rng.uniform(0.7, 1.0) for _ in range(MAXTAPS)]
    eu_pulses = rng.randint(ec.euclid["pulses"][0], ec.euclid["pulses"][1])
    eu_steps = rng.randint(ec.euclid["steps"][0], ec.euclid["steps"][1])
    eu_cycle = rng.uniform(*ec.euclid["cycle"])
    eu_fb = rng.uniform(*ec.euclid["fb"])
    rp_delay0 = rng.uniform(*ec.ramp["delay0"])
    rp_ratio = rng.uniform(*ec.ramp["ratio"])
    rp_fb = rng.uniform(*ec.ramp["fb"])
    pan_r = rng.random()
    so_gate = rng.random()

    def pick(r, table):
        tot = sum(max(0.0, w) for w in table.values()) or 1.0
        acc = 0.0
        for k, w in table.items():
            acc += max(0.0, w) / tot
            if r < acc:
                return k
        return list(table)[-1]

    mode = pick(mode_r, ec.modes)
    step = {"plain": 0.0, "degrees": float(deg_step),
            "octave": float(oct_sign * grades),
            "cents": cents_sign * cents_mag}[mode]
    rotlen = rot_len if rot_gate < ec.rotation["prob"] else 0
    dgest = pick(dgest_r, ec.gestures)
    timing = pick(timing_r, ec.timing)
    pan = pick(pan_r, ec.pan)
    so = (ec.second_order == "always"
          or (ec.second_order == "drawn" and so_gate < 0.25))
    eu_pulses = min(eu_pulses, eu_steps)

    tp = {"uniform": dict(),
          "multitap": dict(ntaps=mt_ntaps, cycle=mt_cycle,
                           offs=sorted([0.0] + mt_offs[:mt_ntaps - 1]),
                           att=[1.0] + mt_att[:mt_ntaps - 1]),
          "euclid": dict(pulses=eu_pulses, steps=eu_steps, cycle=eu_cycle),
          "ramp": dict(delay0=rp_delay0, ratio=rp_ratio,
                       couple=bool(ec.ramp["pitch_couple"])),
          }[timing]
    fb = {"uniform": u_fb, "multitap": mt_fb, "euclid": eu_fb,
          "ramp": rp_fb}[timing]

    return EchoPlan(prob=prob, delay=u_delay, fb=fb, mode=mode, step=step,
                    rotlen=rotlen, dgest=dgest, timing=timing, tp=tp,
                    pan=pan, so=so)


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


def _timing(plan: EchoPlan, reps: int):
    """Yield (k, offset_seconds, decay_pow, att, extra_cents) for each echo
    generation. k numbers generations 1..N for pitch modes and rotation;
    decay_pow feeds fb**decay_pow; extra_cents is the ramp family's
    accumulated varispeed detune (tape physics: cents/rep =
    -1200*log2(ratio), saturating at RAMP_CENTS_CAP)."""
    if plan.timing == "multitap":
        cyc, offs, att = plan.tp["cycle"], plan.tp["offs"], plan.tp["att"]
        k = 0
        c = 0
        while k < reps:
            for j, (o, a) in enumerate(zip(offs, att)):
                if c == 0 and j == 0:
                    continue          # tap 0 of cycle 0 is the source itself
                k += 1
                if k > reps:
                    return
                yield k, c * cyc + o * cyc, c + 1, a, 0.0
            c += 1
    elif plan.timing == "euclid":
        pat = bjorklund(plan.tp["pulses"], plan.tp["steps"])
        cyc = plan.tp["cycle"]
        sd = cyc / plan.tp["steps"]
        k = 0
        c = 0
        while k < reps:
            for i, hit in enumerate(pat):
                if not hit or (c == 0 and i == 0):
                    continue
                k += 1
                if k > reps:
                    return
                yield k, c * cyc + i * sd, c + 1, 1.0, 0.0
            c += 1
    elif plan.timing == "ramp":
        d0, r = plan.tp["delay0"], plan.tp["ratio"]
        cpr = (-1200.0 * math.log2(r)) if plan.tp["couple"] else 0.0
        t = 0.0
        for k in range(1, reps + 1):
            t += d0 * (r ** (k - 1))
            ec = max(-RAMP_CENTS_CAP, min(RAMP_CENTS_CAP, cpr * k))
            yield k, t, k, 1.0, ec
    else:
        for k in range(1, reps + 1):
            yield k, plan.delay * k, k, 1.0, 0.0


def _pan(plan: EchoPlan, k: int, src_pan: float) -> float:
    if plan.pan == "pingpong":
        return 0.12 if k % 2 else 0.88
    if plan.pan == "rotate":
        return (0.2, 0.5, 0.8)[k % 3]
    return src_pan


def echo_pattern(pattern_events: list, plan: EchoPlan, fold,
                 cycles: dict | None = None, peaks: dict | None = None,
                 u: float = 0.0, max_notes: int = 10 ** 9) -> list:
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
    for k, offset, dpow, att, ramp_cents in _timing(plan, reps):
        for e in pattern_events:
            if len(out) >= max_notes:
                return out
            idx, det = e.index, e.det
            if plan.mode in ("degrees", "octave"):
                # Phase 15: fold returns (index, FIELD cents) -- a cascade
                # step lands on the stepped degree's own spectral target
                idx, det = fold(e.index + int(round(plan.step * k)))
            elif plan.mode == "cents":
                det = max(-CENTS_CAP, min(CENTS_CAP,
                                          e.det + plan.step * k))
            det = det + ramp_cents          # varispeed smear rides on top
            instr = e.instr
            amp = e.amp * (plan.fb ** dpow) * att
            cyc = cycles.get(e.cat) if cycles else None
            if cyc:
                instr = cyc[(k - 1) % len(cyc)]
                if peaks and instr != e.instr:
                    src = peaks.get(e.instr, 1.0) or 1.0
                    tgt = peaks.get(instr, 1.0) or 1.0
                    amp *= max(0.25, min(4.0, src / tgt))
            # an inherited glide offset is relative to the SOURCE index; a
            # cascade that shifted idx must re-derive it through the fold
            gl, dg = e.glide, e.detg
            if gl and abs(gl) >= 1.0:
                # Phase 16: the re-derived arrival carries the stepped
                # target's cents as well as its degree
                _ti, _tc = fold(idx + int(round(gl)))
                gl = _ti - idx
                dg = _tc - det
            if plan.timing == "ramp" and plan.tp["couple"]:
                # Phase 17: each echo note GLIDES toward the next repeat's
                # pitch -- the train is neither rhythm nor glissando but
                # both. detg becomes the varispeed delta in this family.
                nxt = max(-RAMP_CENTS_CAP,
                          min(RAMP_CENTS_CAP,
                              -1200.0 * math.log2(plan.tp["ratio"])
                              * (k + 1)))
                dg = nxt - ramp_cents
            out.append(replace(
                e, start=e.start + offset, instr=instr,
                amp=amp,
                dur=max(0.02, e.dur * (DUR_SHRINK ** k)),
                index=idx, det=det, detg=dg, glide=gl,
                pan=_pan(plan, k, e.pan), echo=k))
    return out


def second_order(train: list, plan: EchoPlan, fold, max_notes: int) -> list:
    """Echoes of echoes: the first-order train re-processed through a
    derived, simpler treatment -- longer delay, lower feedback, plain
    pitch, no rotation -- and capped. The derivation is deterministic from
    the plan (no draws): second order is a CONSEQUENCE, not a new voice."""
    if not train or max_notes <= 0:
        return []
    d = (plan.tp.get("cycle") or plan.tp.get("delay0") or plan.delay)
    so_plan = EchoPlan(prob=1.0, delay=min(2.5, d * 2.7),
                       fb=max(0.30, plan.fb * 0.75),
                       mode="plain", step=0.0, dgest="flat",
                       timing="uniform", tp={}, pan=plan.pan, so=False)
    return echo_pattern(train, so_plan, fold, max_notes=max_notes)
