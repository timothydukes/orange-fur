"""
orchestra.py -- Phase 3. The orchestra generator.

THE SHAPE OF IT. The orchestra is regenerated every run: a fixed collection of
INGREDIENTS (synthesis templates, one family per sound in the spec) is
instantiated ~150 times with parameters drawn per instance and BAKED INTO THE
GENERATED CSOUND TEXT as i-time constants. Two runs never contain the same
instruments; the parameter space is combinatorial (a bank template alone draws
a partial count, a degree offset per partial, a spectral law, a wobble rate and
depth per instrument -- conservatively >1e9 distinct instantiations before the
other nine templates are counted).

CATEGORY CONTRACT (unchanged from Phase 1): the score speaks only in the six
categories. Each category owns a numbering range and a set of templates:

    1xx PARTIAL  dense non-harmonic banks on scale degrees; master/slave sync
                 pairs; stereo PWM
    2xx PLUCK    pluck variants; dirty sync/reset; feedback + rational shaper
    3xx GONG     modal banks (t-network snaps, drawn stretch); waveguide pipes
    4xx CLOUD    click/chirp; burst generators with popping exponential VCAs;
                 filtered ticks
    5xx TCLOUD   tuned partial clouds (from Phase 1, generalised); wavetable
                 crossfades
    6xx SWELL    PLL octave-down distortion swells; wavetable-crossfade swells;
                 staggered banks with compound envelopes

    90 air bed and 99 master bus are fixed and live in orc.py.

P-FIELD CONTRACT (fixed project-wide, every template obeys it):
    p1 instr  p2 start  p3 dur  p4 pitch index (cpstuni)  p5 amp (compensated)
    p6 pan    p7 send   p8 slew (0..1)  p9 wave (TCLOUD only)

ENVELOPES are rational approximations of windows, per spec. RatWin is the
Phase 0 primitive; this phase adds RatPop (instant attack, rational decay --
the popping exponential VCA's shape) and RatComp (the PRODUCT of two offset
RatWins -- the spec's compound envelope). ALL take i-rate arguments: k-rate
UDO args read at i-time are unpopulated, which produced a NaN -> segfault on
the Nov 2022 Csound 6.18 build (Phase 0 finding). test_p0's scan enforces this
on the generated text too.

SAFETY RULES the templates obey, so generated code cannot blow up:
  * every rational waveshaper has the form x*(a + b*x)/(1 + c*x*x) with c > 0:
    the denominator has no real roots, so no poles, no NaN;
  * every feedback path has gain <= 0.92 and a `dcblock`;
  * every oscillator frequency is clamped below sr/2.2 at i-time;
  * division denominators carry a +1e-4 floor.

COST MODEL. Each instantiation reports a cost in units of one plain `oscili`
(=1.0). The CLI multiplies event durations by their instrument's cost to
estimate total render work, and --subset (live as of this phase) draws a
per-category random subset -- at least one instrument per category survives
any percentage, or the category contract breaks.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .alphabet import Cat

BASE_NUM = {Cat.PARTIAL: 100, Cat.PLUCK: 200, Cat.GONG: 300,
            Cat.CLOUD: 400, Cat.TCLOUD: 500, Cat.SWELL: 600}

# instruments per category per run (sums to ~150)
COUNT = {Cat.PARTIAL: 30, Cat.PLUCK: 28, Cat.GONG: 20,
         Cat.CLOUD: 26, Cat.TCLOUD: 22, Cat.SWELL: 24}


@dataclass
class Instrument:
    num: int
    cat: Cat
    template: str
    cost: float          # in oscili units
    peak: float          # worst-case output peak for p5=1 (drives the amp model)
    code: str
    bus: int = 1         # which send bus this instrument is wired to (Phase 4)
    tau: float | None = None
    comp: bool = False   # True = RatComp-enveloped (SWELL family); see taus()
    # PHASE 5, for the amp model. The ENVELOPE CLASS is a property of the
    # TEMPLATE, not of the category -- CLOUD contains both `burst` (RatWin,
    # sustained) and `tick` (RatPop, struck), so a per-category rule is too
    # coarse and mispredicts both. tau = ring-down time constant in seconds for
    # STRUCK instruments (a RatPop VCA, or a resonator left to decay on its own
    # Q); None for SUSTAINED instruments, whose RatWin/RatComp envelope really
    # does shape the whole note and for which the beta window is correct.


@dataclass
class Orchestra:
    instruments: list[Instrument] = field(default_factory=list)

    def by_cat(self, cat: Cat) -> list[Instrument]:
        return [i for i in self.instruments if i.cat == cat]

    def peaks(self) -> dict[int, float]:
        return {i.num: i.peak for i in self.instruments}

    def costs(self) -> dict[int, float]:
        return {i.num: i.cost for i in self.instruments}

    def taus(self) -> dict[int, float]:
        """Ring-down constants of the STRUCK instruments (see Instrument.tau)."""
        return {i.num: i.tau for i in self.instruments if i.tau is not None}

    def comps(self) -> set[int]:
        """Instruments enveloped by RatComp (the SWELL family). The amp model
        mirrors the actual UDO: RatComp is the PRODUCT of two RatWins, the
        second spanning only 60-100%% of the note, so it peaks earlier and
        lower than a plain RatWin and decays into the tail. Modelling these
        with the plain beta window over-predicted long swells by up to 10 dB
        -- a 30-second swell is nowhere near its envelope peak for most of
        those 30 seconds."""
        return {i.num for i in self.instruments if i.comp}

    def text(self) -> str:
        return "\n".join(i.code for i in self.instruments)

    def subset(self, pct: float, rng: random.Random) -> "Orchestra":
        """--subset: keep pct% of each category, AT LEAST ONE per category.
        Drawn per run; a 10% orchestra is ~15 instruments and every category
        still answers."""
        keep: list[Instrument] = []
        for cat in Cat:
            pool = self.by_cat(cat)
            k = max(1, round(len(pool) * pct / 100.0))
            keep.extend(rng.sample(pool, min(k, len(pool))))
        keep.sort(key=lambda i: i.num)
        return Orchestra(instruments=keep)


# ---------------------------------------------------------------- helpers
def _bus_out(sig_l: str = "aL", sig_r: str = "aR") -> str:
    return f"""  gaDryL  +=  {sig_l} * (1 - isend)
  gaDryR  +=  {sig_r} * (1 - isend)
  gaSendL +=  {sig_l} * isend
  gaSendR +=  {sig_r} * isend
endin"""


def _head(num: int, comment: str) -> str:
    """Common instrument preamble.

    PHASE 5 -- GLIDE. p10 is a glide target as an OFFSET IN SCALE DEGREES and
    p11 is the transeg curve (0 = linear, +/- = convex/concave). The fundamental
    becomes a k-rate `kcps` that transegs from the note's pitch to the target
    over its full duration; when p10 is 0 the target equals the start and kcps
    is constant, so every pre-Phase-5 score behaves identically.

    `kgl` = kcps / icps is the GLIDE RATIO, and it is the reason a gliding bank
    still sounds like itself: templates with baked partial frequencies (banks,
    tuned clouds, mode banks) multiply every partial by kgl, so the whole
    spectrum slides rigidly. Gliding only the fundamental would smear a tuned
    bank into an inharmonic mess halfway through the slide."""
    return f"""; ---- {num} : {comment}
instr {num}
  icps  =  cpstuni(p4, giTun)
  icps  =  icps > sr / 2.2 ? sr / 2.2 : icps
  icps  =  icps < 8 ? 8 : icps
  igl   =  p10                       ; glide target, offset in scale degrees
  icur  =  p11                       ; transeg curve (0 = linear)
  ; PHASE 9 -- p12 is DETUNE IN CENTS, the first officially off-scale pitch in
  ; the system. idetr multiplies the tuning lookup, and kgl is computed
  ; against the RAW lookup (icps0) so it carries BOTH glide and detune: every
  ; baked-partial template (banks, tuned clouds, mode banks) rides p12 the
  ; same way it rides p10 -- the whole spectrum detunes rigidly. p12 = 0 gives
  ; idetr = 1 and pre-Phase-9 behaviour exactly.
  idetr =  2 ^ (p12 / 1200)
  icps0 =  icps
  icps  =  icps * idetr
  icps  =  icps > sr / 2.2 ? sr / 2.2 : icps
  icps2 =  cpstuni(p4 + igl, giTun) * idetr
  icps2 =  icps2 > sr / 2.2 ? sr / 2.2 : icps2
  icps2 =  icps2 < 8 ? 8 : icps2
  kcps  transeg  icps, p3, icur, icps2
  kgl   =  kcps / icps0
  iamp  =  p5
  ipan  =  p6
  isend =  p7
  islew =  p8 < 0 ? 0 : (p8 > 1 ? 1 : p8)"""


def _pan(sig: str = "amix") -> str:
    return f"""  aL    =  {sig} * sqrt(1 - ipan)
  aR    =  {sig} * sqrt(ipan)"""


def _shaper(x: str, a: float, b: float, c: float) -> str:
    """Rational waveshaper, pole-free by construction (c > 0)."""
    return (f"({x} * ({a:.4f} + {b:.4f} * {x}) "
            f"/ (1 + {c:.4f} * {x} * {x}))")


# ---------------------------------------------------------------- PARTIAL
def t_bank(num: int, rng: random.Random, grades: int) -> Instrument:
    """Dense non-harmonic sine bank. K partials, each at a DRAWN SCALE-DEGREE
    OFFSET (this is 'partials match tuning' for the banks: inharmonic relative
    to a harmonic series, but every frequency is a Werckmeister degree), with a
    drawn spectral law and a slow independent amp wobble per partial."""
    k = rng.randint(6, 22)
    law = rng.choice(["invn", "flat", "bump"])
    bump = rng.uniform(0.2, 0.8)
    lines = [_head(num, f"PARTIAL bank k={k} law={law} (generated)")]
    lines.append("  amix  =  0")
    total = 0.0
    for i in range(k):
        deg = rng.randint(0, 3 * grades)             # up to 3 octaves of degrees
        if law == "invn":
            w = 1.0 / (i + 1)
        elif law == "flat":
            w = rng.uniform(0.4, 1.0)
        else:
            w = max(0.05, 1.0 - abs(i / max(1, k - 1) - bump) * 2)
        total += w
        wob = rng.uniform(0.03, 0.4)
        dep = rng.uniform(0.0, 0.5)
        lines.append(f"  k{i}  oscili  {dep:.3f}, {wob:.4f}, giSine")
        lines.append(f"  a{i}  oscili  {w:.4f} * (1 - {dep:.3f} + k{i}), "
                     f"cpstuni(p4 + {deg}, giTun) * kgl, giSine")
    mix = " + ".join(f"a{i}" for i in range(k))
    lines.append(f"  amix  =  ({mix}) / {total:.4f}")
    lines.append("  aenv  RatWin  islew, p3")
    lines.append("  amix  =  amix * aenv * iamp")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.PARTIAL, "bank", cost=1.6 * k,
                      peak=1.0, code="\n".join(lines))


def t_mslave(num: int, rng: random.Random, grades: int) -> Instrument:
    """Master/slave oscillator: slave hard-synced to the master via syncphasor,
    at a drawn (possibly non-integer) ratio -- the classic sync spectrum, tuned
    at the root."""
    ratio = rng.choice([1.5, 2.0, 2.5, 3.0, 3.5, 4.0]) * rng.uniform(0.98, 1.02)
    lines = [_head(num, f"PARTIAL master/slave sync ratio={ratio:.3f} (generated)")]
    # SYNC WIRING (a real bug, inherited from Phase 3 and only exposed by glide):
    # the master must NOT receive its own sync output. Feeding syncphasor's
    # sync-out back into its own sync-in makes it reset itself every cycle and
    # FREEZES its frequency -- measured shift 1.00 against a full octave glide.
    # It was inaudible while every note held a fixed pitch, because the frozen
    # frequency happened to be the note's own. The master takes a(0); only the
    # SLAVE takes the master's sync pulse. That is what "hard sync" means.
    lines.append(f"""  amst, asyn  syncphasor  kcps, a(0)
  aslv, adm2  syncphasor  kcps * {ratio:.4f}, asyn
  a1    tablei  aslv, giSine, 1
  a2    tablei  amst, giSine, 1
  amix  =  a1 * 0.75 + a2 * 0.25
  aenv  RatWin  islew, p3
  amix  =  amix * aenv * iamp""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.PARTIAL, "mslave", cost=4.0,
                      peak=1.0, code="\n".join(lines))


def t_pwm(num: int, rng: random.Random, grades: int) -> Instrument:
    """Stereo PWM (interpretive placement under PARTIAL: a dense sustained
    texture role). Two band-limited pulses, pulse width swept by LFOs that are
    DEPHASED between channels -- the stereo movement is the point."""
    rate = rng.uniform(0.05, 0.9)
    dep = rng.uniform(0.15, 0.42)
    ph = rng.uniform(0.2, 0.5)
    lines = [_head(num, f"PARTIAL stereo PWM rate={rate:.3f} (generated)")]
    lines.append(f"""  kwL   oscili  {dep:.3f}, {rate:.4f}, giSine
  kwR   oscili  {dep:.3f}, {rate:.4f}, giSine, {ph:.3f}
  aLp   vco2  iamp * 0.5, kcps, 2, 0.5 + kwL
  aRp   vco2  iamp * 0.5, kcps, 2, 0.5 + kwR
  aenv  RatWin  islew, p3
  aL    =  aLp * aenv * sqrt(1 - ipan) * 2
  aR    =  aRp * aenv * sqrt(ipan) * 2""")
    lines.append(_bus_out())
    return Instrument(num, Cat.PARTIAL, "pwm", cost=6.0,
                      peak=1.1, code="\n".join(lines))


# ---------------------------------------------------------------- PLUCK
def t_pluck(num: int, rng: random.Random, grades: int) -> Instrument:
    # pluck param legality (smoke-test finding): methods 4 and 6 require a
    # STRETCH factor >= 1 in iparm2; below 1 is an init error and the note dies.
    meth = rng.choice([1, 4, 6])
    par1 = rng.uniform(0.05, 0.6) if meth in (4, 6) else 0
    par2 = rng.uniform(1.0, 2.5) if meth in (4, 6) else 0
    lines = [_head(num, f"PLUCK pluck meth={meth} (generated)")]
    lines.append(f"""  a1    pluck  iamp, kcps, icps, 0, {meth}, {par1:.3f}, {par2:.3f}
  aenv  RatPop  0.004, p3
  amix  =  a1 * aenv""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.PLUCK, "pluck", tau=1.2, cost=2.0,
                      peak=1.0, code="\n".join(lines))


def t_sync_pluck(num: int, rng: random.Random, grades: int) -> Instrument:
    """Dirty sync/reset pluck: synced slave whose ratio GLIDES over the note --
    the reset point sweeps through the waveform -- through a rational shaper."""
    r0 = rng.uniform(1.2, 4.0)
    r1 = r0 * rng.uniform(0.5, 1.6)
    a, b, c = rng.uniform(0.8, 1.6), rng.uniform(-0.4, 0.4), rng.uniform(0.4, 2.5)
    lines = [_head(num, f"PLUCK dirty sync {r0:.2f}->{r1:.2f} (generated)")]
      # NB: `kr` is a RESERVED Csound global (the control rate); using it as a
    # variable name is a parse error. Found by the template smoke test.
    lines.append(f"""  krat  expseg  {r0:.4f}, p3, {r1:.4f}
  amst, asyn  syncphasor  kcps, a(0)     ; master takes NO sync in (see t_mslave)
  aslv, adm2  syncphasor  kcps * krat, asyn
  araw  tablei  aslv, giSine, 1
  ash   =  {_shaper('araw', a, b, c)}
  aenv  RatPop  0.003, p3
  amix  =  ash * aenv * iamp""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.PLUCK, "sync", tau=1.0, cost=5.0,
                      peak=1.1, code="\n".join(lines))


def t_fb_shaper(num: int, rng: random.Random, grades: int) -> Instrument:
    """Feedback + rational waveshaper: oscillator into a short feedback delay
    through the shaper. Feedback <= 0.92, dcblocked; the shaper is pole-free."""
    fb = rng.uniform(0.4, 0.92)
    dms = rng.uniform(3.0, 30.0)
    a, b, c = rng.uniform(0.9, 1.8), rng.uniform(-0.5, 0.5), rng.uniform(0.6, 3.0)
    lines = [_head(num, f"PLUCK feedback+rational shaper fb={fb:.2f} (generated)")]
    lines.append(f"""  a1    oscili  iamp, kcps, giSine
  adel  delayr  0.05
  atap  deltapi {dms / 1000.0:.5f}
  ain   =  a1 + atap * {fb:.3f}
  ash   =  {_shaper('ain', a, b, c)}
  ash   dcblock2  ash
        delayw  ash
  aenv  RatPop  0.005, p3
  amix  =  ash * aenv * 0.8""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.PLUCK, "fbshape", tau=1.0, cost=5.0,
                      peak=1.2, code="\n".join(lines))


# ---------------------------------------------------------------- GONG
def t_modal(num: int, rng: random.Random, grades: int) -> Instrument:
    """Modal gong: a t-network-snap-style excitation (short noise burst through
    a popping VCA) into a drawn bank of mode filters. Ratios are a stretched
    inharmonic series -- stretch drawn per instrument, gong vs pipe character."""
    k = rng.randint(5, 10)
    stretch = rng.uniform(1.35, 1.9)
    qbase = rng.uniform(60, 400)
    lines = [_head(num, f"GONG modal k={k} stretch={stretch:.3f} (generated)")]
    lines.append("""  aex   rand  iamp
  aeg   RatPop  0.001, 0.012
  aex   =  aex * aeg
  amix  =  0""")
    total = 0.0
    for i in range(k):
        ratio = (i + 1) ** stretch * rng.uniform(0.99, 1.01)
        w = 1.0 / (i + 1) ** rng.uniform(0.5, 1.1)
        q = qbase * rng.uniform(0.6, 1.6)
        total += w
        lines.append(f"  kfq{i}  =  kcps * {ratio:.4f}")
        lines.append(f"  kfq{i}  =  kfq{i} > sr / 2.2 ? sr / 2.2 : kfq{i}")
        lines.append(f"  am{i}  mode  aex, kfq{i}, {q:.1f}")
        lines.append(f"  amix  =  amix + am{i} * {w:.4f}")
    # CALIBRATION, not dynamics: mode-bank gain depends on Q, pitch, AND the
    # draw, and an open-loop constant was wrong by 7x across the real score's
    # register (solo-render finding: GONG category peaked at 9.9 while every
    # other category modelled fine). `balance` here computes the gain that
    # makes the bank's RMS equal a reference sine at the note's own iamp --
    # a self-normalisation local to the instrument. The master chain remains
    # free of limiters/compressors; the no-limiter rule is about not hiding
    # the mix peak, and this hides nothing (peak is declared 1.4 = measured worst
    # ratio across pitch x Q x draws, was 7x spread open-loop).
    lines.append(f"""  amix  =  amix / {total:.4f}
  aref  oscili  iamp, 300, giSine
  amix  balance  amix, aref
  aenv  RatWin  0.02, p3
  amix  =  amix * aenv""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.GONG, "modal", tau=2.5, cost=3.0 * k,
                      peak=1.4, code="\n".join(lines))


def t_pipe(num: int, rng: random.Random, grades: int) -> Instrument:
    """Metal pipe: burst-excited waveguide (wguide1), bright and clangy, with a
    drawn damping. Cheap relative to the mode bank."""
    cut = rng.uniform(2000, 9000)
    fb = rng.uniform(0.55, 0.90)
    lines = [_head(num, f"GONG waveguide pipe fb={fb:.2f} (generated)")]
    lines.append(f"""  aex   rand  iamp
  aeg   RatPop  0.001, 0.02
  aex   =  aex * aeg
  a1    wguide1  aex, kcps, {cut:.0f}, {fb:.3f}
  aenv  RatWin  0.03, p3
  amix  =  a1 * aenv * 2.2""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.GONG, "pipe", tau=2.0, cost=4.0,
                      peak=0.9, code="\n".join(lines))


# ---------------------------------------------------------------- CLOUD
def t_click(num: int, rng: random.Random, grades: int) -> Instrument:
    up = rng.random() < 0.5
    spread = rng.uniform(1.1, 2.4)
    lines = [_head(num, f"CLOUD chirp {'up' if up else 'down'} (generated)")]
    tgt = f"icps * {spread:.3f}" if up else f"icps / {spread:.3f}"
    lines.append(f"""  acps  expon  icps, p3, {tgt}
  a1    oscili  iamp, acps * kgl, giSine
  aenv  RatWin  islew, p3
  amix  =  a1 * aenv""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.CLOUD, "chirp", cost=1.5,
                      peak=1.0, code="\n".join(lines))


def t_burst(num: int, rng: random.Random, grades: int) -> Instrument:
    """Burst generator: a retrigger phasor at a drawn rate drives a POPPING
    EXPONENTIAL VCA (exp(-k*phase), snapped open at each cycle) on a filtered
    noise + sine source. Rapid re-triggering, per spec."""
    rate = rng.uniform(8, 70)
    decay = rng.uniform(4, 18)
    mix = rng.uniform(0.2, 0.8)
    lines = [_head(num, f"CLOUD burst rate={rate:.0f}Hz pop={decay:.0f} (generated)")]
    lines.append(f"""  aph   phasor  {rate:.2f}
  apop  =  exp(-{decay:.2f} * aph)
  an    rand  1
  an    reson  an, kcps, kcps * 0.4, 1
  as1   oscili  1, kcps, giSine
  asrc  =  an * {mix:.3f} + as1 * {1 - mix:.3f}
  aenv  RatWin  islew, p3
  amix  =  asrc * apop * aenv * iamp""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.CLOUD, "burst", cost=4.5,
                      peak=1.1, code="\n".join(lines))


def t_tick(num: int, rng: random.Random, grades: int) -> Instrument:
    bw = rng.uniform(0.08, 0.5)
    lines = [_head(num, f"CLOUD filtered tick bw={bw:.2f} (generated)")]
    lines.append(f"""  an    rand  iamp
  an    reson  an, kcps, kcps * {bw:.3f}, 1
  aenv  RatPop  0.0015, p3
  amix  =  an * aenv * 1.4""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.CLOUD, "tick", tau=0.3, cost=2.0,
                      peak=1.0, code="\n".join(lines))


# ---------------------------------------------------------------- TCLOUD
def t_tcloud(num: int, rng: random.Random, grades: int) -> Instrument:
    """The Phase 1 tuned partial cloud, generalised: drawn partial count, drawn
    per-partial detune jitter (in CENTS, small -- the cloud shimmers around the
    scale degrees without leaving them)."""
    k = rng.randint(8, 20)
    jit = rng.uniform(0.0, 6.0)     # cents
    lines = [_head(num, f"TCLOUD tuned partial cloud k={k} jitter={jit:.1f}c (generated)")]
    lines.append("  iwave =  p9")
    lines.append("  amix  =  0")
    body = []
    total_est = sum(1.0 / n for n in range(1, k + 1))
    for n in range(1, k + 1):
        det = rng.uniform(-jit, jit)
        ratio = 2 ** (det / 1200.0)
        body.append(f"""  ioct{n}  =  log({n}) / log(2)
  idg{n}   =  p4 + round(ioct{n} * giGrades)
  icf{n}   =  cpstuni(idg{n}, giTun) * {ratio:.6f}
  iw{n}    =  iwave == 1 ? ({n} % 2 == 1 ? {1.0/n:.5f} : 0) : (iwave == 2 ? ({n} % 2 == 1 ? {1.0/(n*n):.5f} : 0) : {1.0/n:.5f})
  ; the whole cloud rides the glide, and each partial is Nyquist-clamped at
  ; k-rate -- an i-time guard is not enough once the spectrum can slide upward
  kcf{n}   =  icf{n} * kgl
  kmute{n} =  kcf{n} > sr / 2.2 ? 0 : 1
  kcf{n}   =  kcf{n} > sr / 2.2 ? sr / 2.2 : kcf{n}
  ap{n}  oscili  iw{n} * kmute{n}, kcf{n}, giSine
  amix  =  amix + ap{n}""")
    lines.extend(body)
    lines.append(f"""  amix  =  amix / {total_est:.4f} * iamp
  aenv  RatWin  islew, p3
  amix  =  amix * aenv""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.TCLOUD, "tcloud", cost=1.4 * k,
                      peak=0.95, code="\n".join(lines))


def t_wtx(num: int, rng: random.Random, grades: int) -> Instrument:
    """Wavetable crossfade: two drawn GEN10 recipes, crossfaded over the note by
    a rational window -- the crossfade IS the timbre envelope."""
    def recipe():
        return [round(rng.uniform(0, 1) ** rng.uniform(0.8, 2.5), 3)
                for _ in range(rng.randint(4, 9))]
    r1, r2 = recipe(), recipe()
    lines = [_head(num, f"TCLOUD wavetable crossfade (generated)")]
    lines.append(f"""  it1   ftgenonce  0, 0, 8193, 10, {', '.join(str(x) for x in r1)}
  it2   ftgenonce  0, 0, 8193, 10, {', '.join(str(x) for x in r2)}
  a1    oscili  1, kcps, it1
  a2    oscili  1, kcps, it2
  ax    RatWin  0.5, p3
  amix  =  (a1 * (1 - ax) + a2 * ax) * iamp * 0.7
  aenv  RatWin  islew, p3
  amix  =  amix * aenv""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.TCLOUD, "wtx", cost=3.5,
                      peak=1.0, code="\n".join(lines))


# ---------------------------------------------------------------- SWELL
def t_pll(num: int, rng: random.Random, grades: int) -> Instrument:
    """PLL octave-down distortion swell. The PLL is emulated: a square-wave
    slave whose frequency LAG-LOCKS onto half the master's (portk with a drawn
    time constant -- the lock is sloppy, which is the character), mixed with
    the master and driven through a rational shaper."""
    lag = rng.uniform(0.05, 0.6)
    drive = rng.uniform(1.2, 3.0)
    a, b, c = drive, rng.uniform(-0.3, 0.3), rng.uniform(0.8, 2.2)
    lines = [_head(num, f"SWELL PLL octave-down lag={lag:.2f} drive={drive:.1f} (generated)")]
    lines.append(f"""  ktgt  init  1
  ktgt  =  kcps * 0.5
  kslv  portk  ktgt, {lag:.3f}
  asq   vco2  0.6, kslv, 10
  amst  oscili  0.4, kcps, giSine
  ain   =  asq + amst
  ash   =  {_shaper('ain', a, b, c)}
  ash   dcblock2  ash
  aenv  RatComp  islew, p3
  amix  =  ash * aenv * iamp * 0.7""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.SWELL, "pll", comp=True, cost=5.0,
                      peak=1.1, code="\n".join(lines))


def t_wtswell(num: int, rng: random.Random, grades: int) -> Instrument:
    def recipe():
        return [round(rng.uniform(0, 1) ** rng.uniform(1.0, 3.0), 3)
                for _ in range(rng.randint(3, 7))]
    r1, r2 = recipe(), recipe()
    lines = [_head(num, f"SWELL wavetable crossfade swell (generated)")]
    lines.append(f"""  it1   ftgenonce  0, 0, 8193, 10, {', '.join(str(x) for x in r1)}
  it2   ftgenonce  0, 0, 8193, 10, {', '.join(str(x) for x in r2)}
  a1    oscili  1, kcps, it1
  a2    oscili  1, kcps * 1.0005, it2
  ax    RatWin  0.5, p3
  amix  =  (a1 * (1 - ax) + a2 * ax) * iamp * 0.7
  aenv  RatComp  islew, p3
  amix  =  amix * aenv""")
    lines.append(_pan())
    lines.append(_bus_out())
    return Instrument(num, Cat.SWELL, "wtswell", comp=True, cost=3.5,
                      peak=1.0, code="\n".join(lines))


def t_bankswell(num: int, rng: random.Random, grades: int) -> Instrument:
    """Staggered bank swell: a few scale-degree partials whose compound
    envelopes are OFFSET from each other -- the bank blooms one partial at a
    time. The tempered fifth is always among the degrees (the Phase 1 swell's
    character, kept)."""
    k = rng.randint(3, 7)
    degs = [0, 7] + [rng.randint(0, 2 * grades) for _ in range(k - 2)]
    lines = [_head(num, f"SWELL staggered bank k={k} (generated)")]
    lines.append("  amix  =  0")
    for i, d in enumerate(degs):
        off = i / max(1, k)
        w = 1.0 / (i + 1) ** 0.7
        lines.append(f"  ist{i}  =  p3 * {off:.3f} * 0.5")
        lines.append(f"  ae{i}  RatComp  islew, p3 - ist{i}")
        lines.append(f"  ae{i}  delayk?  ae{i}")     # placeholder marker
        lines.append(f"  ap{i}  oscili  {w:.4f}, cpstuni(p4 + {d}, giTun) * kgl, giSine")
        lines.append(f"  amix  =  amix + ap{i} * ae{i}")
    total = sum(1.0 / (i + 1) ** 0.7 for i in range(k))
    lines.append(f"""  amix  =  amix / {total:.4f} * iamp
  aenv  RatWin  0.85, p3
  amix  =  amix * aenv""")
    lines.append(_pan())
    lines.append(_bus_out())
    code = "\n".join(l for l in lines if "delayk?" not in l)
    return Instrument(num, Cat.SWELL, "bankswell", comp=True, cost=1.5 * k,
                      peak=0.95, code=code)


# ---------------------------------------------------------------- generator
TEMPLATES = {
    Cat.PARTIAL: [t_bank, t_bank, t_mslave, t_pwm],
    Cat.PLUCK:   [t_pluck, t_pluck, t_sync_pluck, t_fb_shaper],
    Cat.GONG:    [t_modal, t_modal, t_pipe],
    Cat.CLOUD:   [t_click, t_burst, t_tick],
    Cat.TCLOUD:  [t_tcloud, t_tcloud, t_wtx],
    Cat.SWELL:   [t_pll, t_wtswell, t_bankswell],
}


def generate(rng: random.Random, grades: int, n_buses: int = 1) -> Orchestra:
    """~150 instruments, drawn fresh. Template choice cycles through the
    category's list (weighted by repetition in TEMPLATES) so every template
    family is represented every run.

    Phase 4: each instrument is WIRED TO ONE SEND BUS at generation time (the
    templates emit gaSendL/R; the wiring is a rewrite to gaSend{b}L/R). This
    keeps the p-field contract fixed -- p7 remains the single send amount --
    and per-section instrument rebinding moves material between tanks."""
    orch = Orchestra()
    for cat in Cat:
        base = BASE_NUM[cat]
        temps = TEMPLATES[cat]
        for j in range(COUNT[cat]):
            t = temps[j % len(temps)] if j < len(temps) else rng.choice(temps)
            ins = t(base + j, rng, grades)
            if n_buses > 1:
                b = rng.randint(1, n_buses)
                ins.bus = b
                ins.code = (ins.code
                            .replace("gaSendL", f"gaSend{b}L")
                            .replace("gaSendR", f"gaSend{b}R"))
            orch.instruments.append(ins)
    return orch
