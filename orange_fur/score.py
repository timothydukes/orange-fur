"""
score.py -- event model, polyphony-aware amplitude compensation, .sco emission.

The amplitude machinery here IS final (it is the "normalization baked into
0dbfs discipline" from the spec).  The note stream is a PHASE 0 PLACEHOLDER --
in Phase 1 it is replaced by the graph traversal, in Phase 2 by the layer
system.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .config import Config
from .orc import TUNING_TABLE
from .alphabet import Cat

GRID_HZ = 100.0   # concurrency-analysis resolution (10 ms bins)


@dataclass
class Event:
    instr: int
    start: float
    dur: float
    index: int       # scale-degree index -> cpstuni
    amp: float       # pre-compensation, "musical" weight in 0..1
    pan: float
    send: float
    slew: float
    cat: int = 0
    wave: int = 0
    glide: float = 0.0   # p10: target offset in scale degrees (0 = no glide)
    gcurve: float = 0.0  # p11: transeg curve


# ---------------------------------------------------------------------------
# Amplitude compensation
# ---------------------------------------------------------------------------
#
# INTERPRETIVE DECISION -- "normalization automatically reduces the amplitude
# of notes when the number of simultaneous notes increases."
#
# Implemented as a two-stage, entirely score-time (Python) computation:
#
#   Stage 1, LOCAL: each event is scaled by  c(t)^-alpha  where c(t) is the
#     mean concurrent-voice count over that event's own span and alpha=0.5.
#     alpha=0.5 is the incoherent (power-sum) assumption: N uncorrelated
#     voices each at 1/sqrt(N) hold total RMS constant. alpha=1.0 would be the
#     coherent (worst-case phase-aligned) assumption and would make dense
#     passages far too quiet. Non-harmonic sine banks and microsound clouds
#     are near-uncorrelated, so 0.5 is the right model for this material.
#
#   Stage 2, GLOBAL: predict the peak envelope of the whole mix as
#     sqrt(sum of active amp^2) per bin, add a reverb-energy allowance derived
#     from --wetdry, and apply one scalar so the predicted peak lands on the
#     --normalize ceiling (dBFS).
#
# The clip() in instr 99 is a backstop, not the mechanism. render.py reports
# the true measured peak so any divergence between prediction and reality is
# visible rather than silently squashed.


# Per-instrument peak factor: the amplitude actually produced by the instrument
# when driven with p5 = 1.0, measured from the orchestra's own summing.
# Phase 3 will compute these automatically from the generated instrument graph;
# in Phase 0 they are hand-derived and must be kept in sync with orc.py.
# Per-instrument worst-case peak for p5=1. Phase 3: the orchestra is generated
# per run, so this is a REGISTRY the CLI fills from Orchestra.peaks() before
# compensate() runs. 90/99 never appear as note instruments.
INSTR_PEAK: dict[int, float] = {}


def set_instr_peaks(peaks: dict[int, float],
                    taus: dict[int, float] | None = None,
                    comps: set[int] | None = None) -> None:
    INSTR_PEAK.clear()
    INSTR_PEAK.update(peaks)
    INSTR_TAU.clear()
    if taus:
        INSTR_TAU.update(taus)
    INSTR_COMP.clear()
    if comps:
        INSTR_COMP.update(comps)


def _beta_window(slew: float, n: int) -> list[float]:
    """The same rational window the orchestra uses (RatWin in orc.py), sampled
    at bin resolution. Kept in sync with orc.py by hand in Phase 0; Phase 3
    generates both from one source."""
    a = 0.02 + 3.0 * slew
    b = 3.0 - 2.6 * slew
    pk = ((a / (a + b)) ** a) * ((b / (a + b)) ** b)
    out = []
    for i in range(n):
        t = (i + 0.5) / n
        out.append(((t ** a) * ((1 - t) ** b)) / (pk + 1e-6))
    return out


def _power_envelope(events: list[Event], total: float) -> list[float]:
    """Sum of (peak-factored, window-shaped) amp^2 of active events per bin.

    INTERPRETIVE DECISION: the earlier rectangular model treated every note as
    if it held full amplitude for its whole duration, which under-predicted the
    global gain by several dB (measured -7.6 dBFS against a -1 dBFS target).
    Integrating the actual window closes that gap without needing a second
    render pass -- which is the whole point, since a full-quality pass can take
    hours.
    """
    nbins = max(1, int(math.ceil(total * GRID_HZ)) + 2)
    env = [0.0] * nbins

    # Cost guard: windowed accumulation is O(sum of event spans in bins).
    span_total = sum(int(e.dur * GRID_HZ) + 1 for e in events)
    if span_total > 40_000_000:
        # Degrade to the rectangular model rather than stall.
        for e in events:
            p = (e.amp * INSTR_PEAK.get(e.instr, 1.0)) ** 2
            a = max(0, min(int(e.start * GRID_HZ), nbins - 1))
            b = max(a + 1, min(int((e.start + e.dur) * GRID_HZ) + 1, nbins))
            for i in range(a, b):
                env[i] += p
        return env

    wincache: dict[tuple[int, int], list[float]] = {}
    for e in events:
        a = max(0, min(int(e.start * GRID_HZ), nbins - 1))
        b = max(a + 1, min(int((e.start + e.dur) * GRID_HZ) + 1, nbins))
        n = b - a
        key = (round(e.slew, 2), n)
        w = wincache.get(key)
        if w is None:
            w = _beta_window(round(e.slew, 2), n)
            if len(wincache) < 4096:
                wincache[key] = w
        p = (e.amp * INSTR_PEAK.get(e.instr, 1.0)) ** 2
        for i in range(n):
            env[a + i] += p * w[i] * w[i]
    return env


def _count_envelope(events: list[Event], total: float) -> list[float]:
    nbins = max(1, int(math.ceil(total * GRID_HZ)) + 2)
    diff = [0.0] * (nbins + 1)
    for e in events:
        a = max(0, min(int(e.start * GRID_HZ), nbins))
        b = max(0, min(int((e.start + e.dur) * GRID_HZ) + 1, nbins))
        diff[a] += 1.0
        diff[b] -= 1.0
    env = [0.0] * nbins
    acc = 0.0
    for i in range(nbins):
        acc += diff[i]
        env[i] = acc
    return env


# Crest model. sqrt(sum of squared amplitudes) is the COHERENT peak of the bin
# (all partials phase-aligned). Real material is not phase-aligned, and a real
# sample peak is crest * RMS. Calibrated against measured renders (see
# tools/calibrate.py); CREST_A is the single-voice case (exact: peak == amp),
# CREST_B the growth with concurrency.
CAL = 0.794      # empirical calibration of the analytic model. Fitted over a
                 # grid of 60 draft renders (nodes 20, space 0..1, wetdry
                 # 0.2..0.8, 3 repeats). RESIDUAL SPREAD IS ~4 dB run-to-run --
                 # unavoidable, since every run is a different score. CAL is set
                 # so the mean lands ~1 dB BELOW the ceiling, not on it, so the
                 # worst case does not clip. Use --calibrate for a tight fit.
                 # modelled and measured peak (fitted over 16 renders spanning
                 # nodes 5..90, space 0.2/0.8, wetdry 0.15/0.6; spread +-0.35 dB)
CREST_A = 1.00
CREST_B = 0.55
REVP = 0.80      # reverb power-accumulation exponent, fitted on the same grid.
                 # The theoretical steady-state value is 1.0; 0.80 fits better
                 # because reverbsc is internally normalised and because a
                 # sparse score never drives the tank to steady state.


def _crest(n: float) -> float:
    """1.0 at n=1, growing sub-linearly with the number of concurrent voices."""
    return CAL * (CREST_A + CREST_B * math.log(max(1.0, n)))


def cost_route(events: list[Event], cfg: Config, orch, cap: float) -> dict:
    """DENSITY -> COST ROUTING. The Phase 3/4 render-cost problem, solved.

    Every instrument reports a cost in oscili units. The estimated render work
    is sum(cost * duration). At N=300 that reached 2.48 MILLION oscili-seconds
    -- hours of render for one draft.

    The fix is the spec's own instinct made mechanical: dense passages get
    CHEAP instruments. Notes are ranked by the LOCAL POLYPHONY at their onset
    (densest first) and rebound, one by one, to the cheapest instrument IN
    THEIR OWN CATEGORY, until the estimate falls under the cap.

    Two things this deliberately does NOT do:
      * it never changes a note's CATEGORY. A gong stays a gong. The category
        contract (gongs rare, partials clustered, clouds dispersed) survives
        untouched -- only the concrete voice within the category changes, and
        that binding was already a per-section redraw.
      * it never thins the score. Culling is the density track's job and it is
        a compositional decision; this is a rendering-cost decision, and the
        two are kept apart on purpose.

    The audible consequence is the one you want anyway: the thickest passages
    are made of the simplest voices, which is how they stay legible.
    """
    costs = orch.costs()
    by_cat: dict[int, list] = {}
    for i in orch.instruments:
        by_cat.setdefault(int(i.cat), []).append(i)
    cheapest = {c: min(v, key=lambda i: i.cost).num for c, v in by_cat.items()}

    def total() -> float:
        return sum(costs.get(e.instr, 1.0) * e.dur for e in events)

    before = total()
    if cap <= 0 or before <= cap:
        return {"before": before, "after": before, "rerouted": 0, "cap": cap}

    counts = _count_envelope(events, cfg.dur_sec)
    nbins = len(counts)

    def density(e):
        b = max(0, min(int(e.start * GRID_HZ), nbins - 1))
        return counts[b]

    order = sorted(range(len(events)), key=lambda i: -density(events[i]))
    cur = before
    rerouted = 0
    for i in order:
        if cur <= cap:
            break
        e = events[i]
        tgt = cheapest.get(e.cat)
        if tgt is None or tgt == e.instr:
            continue
        old = costs.get(e.instr, 1.0)
        new = costs.get(tgt, 1.0)
        if new >= old:
            continue
        cur -= (old - new) * e.dur
        e.instr = tgt
        rerouted += 1

    # The cap can be UNREACHABLE: once every note is on the cheapest voice of
    # its category, the floor is the score itself. Reported honestly; the two
    # remaining levers -- fewer notes, shorter piece -- are compositional
    # decisions and stay in the user's hands.
    return {"before": before, "after": cur, "rerouted": rerouted, "cap": cap,
            "at_floor": cur > cap}


def compensate(events: list[Event], cfg: Config, alpha: float = 0.5,
               routing=None) -> dict:
    total = cfg.dur_sec
    counts = _count_envelope(events, total)
    nbins = len(counts)

    # ---- Stage 1: local polyphony compensation --------------------------
    for e in events:
        a = max(0, min(int(e.start * GRID_HZ), nbins - 1))
        b = max(a + 1, min(int((e.start + e.dur) * GRID_HZ) + 1, nbins))
        span = counts[a:b]
        c = max(1.0, sum(span) / len(span)) if span else 1.0
        e.amp = e.amp / (c ** alpha)

    # ---- Stage 2: model the actual signal chain, per channel -------------
    #
    # INTERPRETIVE DECISION: the first model summed raw note amplitudes and was
    # ~6 dB off, because it ignored (a) constant-power panning splitting each
    # note across two channels, (b) the send fraction diverting energy out of
    # the dry path, (c) the reverb smearing that energy across seconds rather
    # than delivering it instantaneously, and (d) the equal-power wet/dry
    # crossfade. All four are modelled here. This must stay in sync with
    # instr 99 in orc.py; Phase 4 will generate both from one routing struct.
    dryL = _chain_power(events, cfg, nbins, chan=0, leg="dry")
    dryR = _chain_power(events, cfg, nbins, chan=1, leg="dry")
    sndL = _chain_power(events, cfg, nbins, chan=0, leg="send")
    sndR = _chain_power(events, cfg, nbins, chan=1, leg="send")

    # Reverb: energy-preserving leaky integrator with the tank's own RT.
    ifb = 0.68 + 0.30 * cfg.space
    rt60 = _rt60_from_feedback(ifb)
    # INTERPRETIVE DECISION: a feedback tank does not merely SMEAR the send
    # energy, it ACCUMULATES it. Steady-state power gain of a feedback loop with
    # gain g is 1/(1 - g**2); reverbsc's --space maps to g in 0.68..0.98, i.e. a
    # power gain from ~1.9 to ~25. Ignoring this made every large-room/high-wet
    # render clip by ~3 dB while small-room renders sat 3 dB low. REVP softens
    # the theoretical exponent to account for reverbsc's internal normalisation
    # and for the fact that the tank is never in steady state with sparse input.
    accum = (1.0 / (1.0 - ifb * ifb)) ** REVP
    # Phase 4/5: the wet path is a GENERATED chain topology, not one reverbsc.
    # The Routing struct -- the same one the master-bus Csound text is generated
    # from -- reports the wet path's power gain, applying the accumulation term
    # only to the chains that actually contain a feedback tank.
    grev = (routing.wet_power_gain(accum) if routing is not None else accum)
    wetL = [v * grev for v in _smear(sndL, rt60)]
    wetR = [v * grev for v in _smear(sndR, rt60)]

    idry = math.cos(cfg.wetdry * math.pi / 2)
    iwet = math.sin(cfg.wetdry * math.pi / 2)

    # Air bed: instr 90's contribution, modelled at its worst case.
    air_base = cfg.air * 0.012
    air_pow = (air_base * 1.0) ** 2 * ((iwet * 1.0) ** 2 + (idry * 0.25) ** 2)

    predicted = 0.0
    peak_bin = 0
    for i in range(nbins):
        pL = dryL[i] * idry * idry + wetL[i] * iwet * iwet + air_pow
        pR = dryR[i] * idry * idry + wetR[i] * iwet * iwet + air_pow
        p = max(pL, pR)
        v = math.sqrt(p) * _crest(counts[i])
        if v > predicted:
            predicted = v
            peak_bin = i

    ceiling = 10 ** (cfg.normalize / 20.0)
    gain = (ceiling / predicted) if predicted > 1e-9 else 1.0

    for e in events:
        e.amp *= gain

    return {
        "ceiling": ceiling,
        "gain": gain,
        "predicted_peak": predicted,
        "peak_at": peak_bin / GRID_HZ,
        "max_concurrency": int(max(counts)) if counts else 0,
        "mean_concurrency": (sum(counts) / len(counts)) if counts else 0.0,
        "rt60": rt60,
        "alpha": alpha,
    }


def _rt60_from_feedback(fb: float) -> float:
    """reverbsc's feedback maps roughly to RT60 = -3 * meanDelay / log10(fb).
    The mean delay of its 8 delay lines is about 40 ms."""
    fb = min(max(fb, 0.01), 0.999)
    return max(0.05, -3.0 * 0.040 / math.log10(fb))


def _smear(power: list[float], rt60: float) -> list[float]:
    """One-pole leaky integrator, unity steady-state gain: models the reverb
    spreading a note's send energy over its decay time rather than delivering
    it all in the note's own bin."""
    tau = rt60 / 6.908  # RT60 -> exponential time constant
    a = math.exp(-1.0 / (GRID_HZ * max(tau, 1e-4)))
    out = [0.0] * len(power)
    y = 0.0
    for i, x in enumerate(power):
        y = a * y + (1 - a) * x
        out[i] = y
    return out


# PER-CATEGORY DRIVE (Phase 5). The categories do not share an envelope, and
# pretending they do was a real error the moment gestures got long.
#
# PLUCK and GONG are STRUCK: RatPop fires a few-millisecond excitation into a
# resonator (a pluck filter, a mode bank, a waveguide) which then rings down on
# its own Q. Their energy is front-loaded and their audible length has almost
# nothing to do with p3. CLOUD is mostly ticks: shorter still.
#
# PARTIAL, TCLOUD and SWELL are SUSTAINED: RatWin / RatComp really do shape the
# whole note, so the beta window is right for them.
#
# Applying the sustained window to a struck category is harmless while notes are
# short -- which is why it survived Phases 0-4 -- and becomes an 11 dB
# over-prediction the moment a LONGDECAY gesture stretches a gong to 60 seconds
# and the model believes it is still sounding at full power a minute in.
INSTR_TAU: dict[int, float] = {}     # per-run, filled by set_instr_peaks
INSTR_COMP: set[int] = set()         # per-run: RatComp-enveloped instruments


def _decay_window(tau: float, n: int) -> list[float]:
    """Fast attack, exponential ring-down. Independent of note length."""
    if n <= 1:
        return [1.0]
    atk = max(1, int(0.01 * n))
    out = []
    for i in range(n):
        t = i / GRID_HZ
        a = min(1.0, (i + 1) / atk)
        out.append(a * math.exp(-t / tau))
    return out


def _ratcomp_window(slew: float, n: int) -> list[float]:
    """Mirror of the RatComp UDO (orc.py): the product of two RatWins, the
    second spanning idur * (0.6 + 0.4 * islew). Sampled on the model grid."""
    w1 = _beta_window(slew, n)
    n2 = max(1, int(n * (0.6 + 0.4 * slew)))
    w2 = _beta_window(0.5 + slew * 0.5, n2)
    return [w1[i] * (w2[i] if i < n2 else 0.0) for i in range(n)]


def fold_index(index: int, basekey: int, grades: int) -> int:
    """Reflect a pitch index into basekey +/- 3 repeat-intervals (degrees).

    A guard, not a feature: the layered offsets (base degree + pattern degree
    + register) are individually sane, but their SUM can wander in a long
    piece, and cpstun happily extrapolates any integer into a frequency that
    then pins against the sr/2.2 clamp. Reflection (not clamping -- clamping
    piles notes onto the boundary pitch) keeps the audible register while
    preserving contour. +/- 3 intervals around 1/1 = 261.6 Hz spans ~33 Hz to
    ~2.1 kHz fundamentals, which is the useful register anyway."""
    span = 3 * grades
    rel = index - basekey
    if -span <= rel <= span:
        return index
    period = 4 * span
    x = abs(rel) % period
    folded = x if x <= span else (2 * span - x if x <= 3 * span else x - period)
    return basekey + (folded if rel >= 0 else -folded)


def _chain_power(events, cfg, nbins, chan: int, leg: str) -> list[float]:
    """Windowed power envelope for one channel of one leg (dry or send)."""
    env = [0.0] * nbins
    wincache: dict[tuple, list[float]] = {}
    for e in events:
        a = max(0, min(int(e.start * GRID_HZ), nbins - 1))
        b = max(a + 1, min(int((e.start + e.dur) * GRID_HZ) + 1, nbins))
        n = b - a
        pan = math.sqrt(e.pan) if chan == 1 else math.sqrt(1.0 - e.pan)
        legf = e.send if leg == "send" else (1.0 - e.send)
        amp = e.amp * INSTR_PEAK.get(e.instr, 1.0) * pan * legf
        p = amp * amp
        if p < 1e-12:
            continue
        tau = INSTR_TAU.get(e.instr)
        comp = e.instr in INSTR_COMP
        key = (tau, comp, round(e.slew, 2), n)
        w = wincache.get(key)
        if w is None:
            w = (_decay_window(tau, n) if tau is not None
                 else _ratcomp_window(round(e.slew, 2), n) if comp
                 else _beta_window(round(e.slew, 2), n))
            if len(wincache) < 8192:
                wincache[key] = w
        for i in range(n):
            env[a + i] += p * w[i] * w[i]
    return env


# ---------------------------------------------------------------------------
# Graph-driven note stream (Phase 1)
# ---------------------------------------------------------------------------
def graph_events(cfg, sol, rng: random.Random,
                 catmap: dict | None = None) -> tuple[list[Event], dict]:
    """Turn the derived string into notes. Phase 2: pairs carry the layers.

    PHASE 3: `catmap` maps each category to the ordered list of generated
    instrument numbers that survived --subset. A terminal's per-section
    phenotype reading carries `voice` (0..1); the concrete instrument is
    catmap[cat][voice * len] -- so the binding is REDRAWN PER SECTION like the
    rest of the reading, and the same symbol is a different bank in the next
    section. Without a catmap (tests, dry paths) the Phase 1/2 placeholder
    numbering applies.

    SELECTION (unchanged from Phase 1): section-weighted, contiguous slice of
    the terminal sequence, strided when the slice outruns the budget, Poisson
    onsets within the section.

    NEW IN PHASE 2 -- the pair is the unit of combination:

      outer node  = context: L1 section (via the partition), L2 tempo (warps
                    onset density across the node's 1/N of the timeline),
                    L3 room (majority vote per section, stepped at boundaries)
      inner node  = content: a note's onset lands in one pair slice; that
                    slice's inner node supplies L4 (the pattern the terminal
                    expands into), L5 (the gesture shaping it), L6 (the
                    articulation of each note in it).

    BUDGET: pattern notes count against N**2, so each section's terminal count
    is its budget share divided by the expected pattern size of its inner
    nodes' L4 distribution. A chiparp-heavy section fires fewer, larger events.

    DURATION: per-note multipliers come from literally convolving the pattern's
    articulation sequence with the gesture's precomputed kernel at low
    resolution, then smoothing (layers.duration_envelope).
    """
    from collections import Counter
    from .alphabet import Cat, CAT_TO_INSTR, is_nonterminal, terminal_index
    from .sections import gen_sections, partition_nodes
    from . import phenotype as P
    from . import layers as L
    from . import macro as M

    sysm = sol.system
    n = sysm.n
    total = cfg.dur_sec

    # AUTO SECTION COUNT (Phase 6, long-form): with a fixed count of 5, a
    # 45-minute piece has 9-minute sections and the L1 grammar stops meaning
    # anything. Auto draws a target section length of 45-150 s and derives the
    # count, so a 4-minute piece still gets 3-5 sections and a 45-minute piece
    # gets 18-32. An explicit --sections N is honoured untouched.
    n_secs = cfg.sections
    if n_secs <= 0:
        n_secs = max(3, min(32, round(cfg.dur_sec / rng.uniform(45.0, 150.0))))
    secs, trace = gen_sections(n_secs, rng)
    parts = partition_nodes(n, secs, rng)

    terms = [terminal_index(x, n) for x in sysm.string if not is_nonterminal(x, n)]
    T = len(terms)

    events: list[Event] = []
    cursor = 0
    seclog = []
    macro_log = []
    rooms = []           # (t0, Room) per section, for the master bus table

    for (lo, hi, sec) in parts:
        frac = (hi - lo) / n
        t0 = total * (lo / n)
        t1 = total * (hi / n)
        span = max(1e-6, t1 - t0)

        room = L.section_room(sysm.nodes, lo, hi)
        rooms.append((t0, room))

        slice_len = max(1, int(round(T * frac)))
        chunk = terms[cursor:cursor + slice_len]
        cursor += slice_len
        if not chunk:
            continue

        # budget share, divided by the expected pattern size of this section's
        # inner-node L4 distribution (inner nodes of a pair (a,b) with a in
        # [lo,hi) range over ALL nodes, so the expectation is over all N)
        l4c = Counter(nd.l4 for nd in sysm.nodes)
        mean_pat = L.expected_pattern_size(l4c)
        want = max(1, int(round(sol.budget * frac / mean_pat)))
        if want < len(chunk):
            stride = len(chunk) / want
            picked = [chunk[int(i * stride)] for i in range(want)]
        else:
            picked = chunk
        k = len(picked)

        l0 = sysm.nodes[lo].l0
        smap = P.draw(n, sec, l0, rng)

        # PHASE 5: the macro plan -- four slow Euclidean tracks steering this
        # section. It does not replace the layers; it decides which of their
        # decisions is currently in force.
        plan = M.draw_plan(rng, t0, span)
        macro_log.append({
            "section": sec.name, "t0": t0,
            "playlist": [g.name for g in plan.playlist],
            "accent": "".join(str(x) for x in plan.accent.accent_pat()),
            "gesture": "".join(str(x) for x in plan.gesture.pattern),
            "density": "".join(str(x) for x in plan.density.pattern),
            "register": "".join(str(x) for x in plan.register.pattern),
            "periods": (round(plan.accent.period, 1), round(plan.gesture.period, 1),
                        round(plan.density.period, 1), round(plan.register.period, 1)),
        })

        # Poisson onsets across the section, then per-outer-node L2 tempo warp
        gaps = [rng.expovariate(1.0) for _ in range(k)]
        gsum = sum(gaps) or 1.0
        onsets = []
        acc = 0.0
        for g in gaps:
            u = acc / gsum                        # 0..1 across the section
            # which outer node of this section does u fall in?
            a = min(hi - 1, lo + int(u * (hi - lo)))
            ua = (u * (hi - lo)) % 1.0            # 0..1 within that node's span
            uw = L.tempo_warp(ua, sysm.nodes[a].l2)
            node_t0 = t0 + span * ((a - lo) / (hi - lo))
            node_span = span / (hi - lo)
            onsets.append((node_t0 + node_span * uw, a))
            acc += g
        onsets.sort(key=lambda x: x[0])

        # Hard note budget for the section: patterns are truncated against it
        # (head always emitted). Without this, tiny N overshoots wildly -- at
        # N=5 a single chiparp is 16 notes against a 25-note budget.
        sec_budget = max(1, int(round(sol.budget * frac)))
        notes_emitted = 0
        for j, t in enumerate(picked):
            if notes_emitted >= sec_budget:
                break
            term = sysm.terminals[t]
            rd = smap.readings[t]
            cat = term.cat
            start, a = onsets[j]

            # inner node: which pair slice inside outer node a?
            node_t0 = t0 + span * ((a - lo) / (hi - lo))
            node_span = span / (hi - lo)
            b = min(n - 1, int(((start - node_t0) / node_span) * n))
            inner = sysm.nodes[b]

            # ----- content: L4 pattern ---------------------------------
            # THE MACRO GESTURE TRACK OVERRIDES the inner node's L4 while its
            # playlist entry is in force. This is how the requested vocabulary
            # (glissandi, cloud glissandi, diverging clouds, sweeps and clicks,
            # bursts, loops, ostinati, trills, long decays) actually gets
            # SEQUENCED, rather than merely being available.
            l4 = plan.gesture_at(start) or inner.l4
            plo, phi = L.PATTERN_SIZE[l4]
            kp = rng.randint(plo, phi)
            degs = L.pattern_degrees(l4, kp, rng)
            kp = len(degs)
            # a gliding cloud glides ONE way: the direction is drawn per
            # pattern, not per grain (per grain would be a diverging cloud)
            common_dir = rng.choice([-1, 1])

            art = L.ARTICS[inner.l6]
            durmul = L.duration_envelope(kp, inner.l5, inner.l6, rng)
            kern = L.GESTURE_KERNEL[inner.l5]
            jit, conc = L.GESTURE_TIME[inner.l5]
            cscale = L.contour_scale(sysm.nodes[a].l2, room)

            u = (start - t0) / span
            base_deg = rd.degree + int(round(smap.drift * u))
            base_dur = P.lerp(P.CAT_DUR[cat], rd.dur_bias)
            base_amp = P.lerp(P.CAT_AMP[cat], rd.amp_bias)
            send = P.lerp(P.CAT_SEND[cat], rd.send_bias)
            send = min(1.0, send * (0.55 + 0.65 * cfg.space))

            if catmap:
                pool = catmap[cat]
                voice_i = pool[min(len(pool) - 1, int(rd.voice * len(pool)))]
            else:
                voice_i = CAT_TO_INSTR[cat]

            simul = l4 in L.SIMULTANEOUS
            spread = L.PATTERN_SPREAD.get(l4, 1.0) * base_dur
            slot = spread / max(1, kp)

            for m, dg in enumerate(degs):
                if m > 0 and notes_emitted >= sec_budget:
                    break                     # truncate the pattern, keep the head
                if simul:
                    nstart = start
                else:
                    pos = (m / max(1, kp - 1)) ** conc if kp > 1 else 0.0
                    nstart = start + spread * pos + rng.uniform(-jit, jit) * slot
                    nstart = max(t0, nstart)
                # CONTRACT (amended for patterns, interpretive): the HEAD of a
                # pattern starts inside the duration (Poisson onsets guarantee
                # that); CONTINUATION notes may spill to +4 s -- a final
                # arpeggio ringing out past the last bar is the outro working,
                # not a bug -- and everything still ends before the master bus
                # closes at +12 s.
                nstart = min(nstart, total + 4.0)
                # gesture kernel also shapes level across the pattern
                gk = kern[round(m * (len(kern) - 1) / max(1, kp - 1))] if kp > 1 else 1.0
                amp = base_amp * art.amp * (0.45 + 0.55 * gk)

                dur = base_dur * durmul[m]
                if l4 == L.L4.SUSTAIN:
                    dur *= 2.2
                if l4 == L.L4.SLIDE:
                    dur = slot * L.SLIDE_OVERLAP
                if l4 in (L.L4.CHIPARP, L.L4.TRILL, L.L4.RUN):
                    dur = min(dur, slot * (1.0 - max(0.0, art.gap)))
                # grains are GRAINS: short and quiet, whatever the category's
                # base duration says. A cloud glissando of plucks must be a
                # cloud of plucks, not a pile of overlapping full-length ones.
                if l4 in L.GRAINY:
                    # floored: a slot can be arbitrarily short, a grain cannot
                    dur = max(0.02, min(dur, slot * rng.uniform(0.5, 1.4)))
                if l4 == L.L4.GLISS:
                    dur = max(dur, base_dur * rng.uniform(1.6, 3.2))
                if l4 == L.L4.LONGDECAY:
                    # capped: 7x a gong's base duration can exceed the Phase 2
                    # duration contract (<= 100 s); 90 s of decay is enough
                    dur = min(90.0, max(dur, base_dur * rng.uniform(3.0, 7.0)))
                if l4 == L.L4.SWEEPCLICK:
                    dur = (min(90.0, spread * rng.uniform(0.7, 1.0)) if m == 0
                           else max(0.02, min(dur, 0.06)))
                dur = max(0.015, min(dur, max(0.02, total + 10.0 - nstart)))

                slew = max(0.0, min(1.0,
                    (art.slew if cat not in (Cat.SWELL,) else max(art.slew, 0.75))
                    * cscale * (0.6 + 0.8 * rd.slew)))

                pan = rd.pan
                if room.lanes:
                    pan = L.PAN_LANES[0] if pan < 0.5 else L.PAN_LANES[1]

                # ---- macro modulation ----
                if plan.culled(nstart, rng):
                    continue                       # DENSITY track opens/closes
                amp *= plan.gain_at(nstart)        # ACCENT contour
                reg = plan.register_offset(nstart)  # REGISTER staircase

                gl, gc = L.glide_for(l4, m, kp, rng, common_dir=common_dir)
                if l4 == L.L4.LONGDECAY:
                    amp *= 0.6
                    send = min(1.0, send * 1.25)

                # the Phase 2 duration contract (<= 100 s) is now an explicit
                # emission invariant: long-form sections stretch base durations
                # through several independent paths, and a note past 100 s is
                # indistinguishable from its own reverb tail anyway
                dur = min(dur, 100.0)
                events.append(Event(
                    instr=voice_i, start=nstart, dur=dur,
                    index=fold_index(cfg.scale.basekey + base_deg + dg + reg,
                                     cfg.scale.basekey, cfg.scale.numgrades),
                    amp=amp, pan=pan, send=send, slew=slew,
                    cat=int(cat), wave=int(term.wave) if term.wave is not None else 0,
                    glide=gl, gcurve=gc,
                ))
                notes_emitted += 1

        # TOP-UP: pattern-size draws are variable, so a section can land well
        # under its note budget (measured: 37% under at N=10 in a bad draw).
        # Fill toward the budget with SINGLE notes from terminal occurrences
        # the stride skipped -- plain notes, no patterns, so the top-up cannot
        # itself overshoot.
        skipped = [c for i, c in enumerate(chunk)
                   if want < len(chunk) and i % max(1, int(len(chunk) / want))]
        ti = 0
        while notes_emitted < int(sec_budget * 0.92) and ti < len(skipped):
            t = skipped[ti]
            ti += 1
            term = sysm.terminals[t]
            rd = smap.readings[t]
            cat = term.cat
            start = t0 + rng.random() * span
            if catmap:
                pool = catmap[cat]
                vi = pool[min(len(pool) - 1, int(rd.voice * len(pool)))]
            else:
                vi = CAT_TO_INSTR[cat]
            dur = P.lerp(P.CAT_DUR[cat], rd.dur_bias)
            dur = max(0.015, min(dur, max(0.02, total + 10.0 - start)))
            send = min(1.0, P.lerp(P.CAT_SEND[cat], rd.send_bias)
                       * (0.55 + 0.65 * cfg.space))
            events.append(Event(
                instr=vi, start=start, dur=dur,
                index=cfg.scale.basekey + rd.degree,
                amp=P.lerp(P.CAT_AMP[cat], rd.amp_bias), pan=rd.pan,
                send=send, slew=P.lerp(P.CAT_SLEW[cat], rd.slew),
                cat=int(cat), wave=int(term.wave) if term.wave is not None else 0,
            ))
            notes_emitted += 1

        seclog.append({
            "section": sec.name, "nodes": (lo, hi), "t0": t0, "t1": t1,
            "notes": notes_emitted, "patterns": k, "slice": len(chunk),
            "l0": int(l0), "room": room.l3.name,
        })

    # THE CARRIER IS GUARANTEED. The strided selection can miss every
    # swell-category terminal at small N (it did: N=5, and N=12 in Phase 1
    # before the assignment fix). The swell is what makes a sparse score
    # legible, so if selection produced none, one is injected: a long swell in
    # the largest section, degree from that section's own phenotype. An
    # injected carrier is reported in the section log.
    if not any(e.cat == int(Cat.SWELL) for e in events):
        sw = [t for t in sysm.terminals if t.cat == Cat.SWELL]
        if sw and seclog:
            big = max(seclog, key=lambda s_: s_["t1"] - s_["t0"])
            t = sw[0]
            start = big["t0"] + 0.15 * (big["t1"] - big["t0"])
            dur = min(30.0, max(10.0, (big["t1"] - big["t0"]) * 0.5))
            swi = (catmap[Cat.SWELL][0] if catmap else CAT_TO_INSTR[Cat.SWELL])
            events.append(Event(
                instr=swi, start=start, dur=dur,
                index=cfg.scale.basekey - 7, amp=0.4, pan=0.5,
                send=min(1.0, 0.8 * (0.55 + 0.65 * cfg.space)),
                slew=0.9, cat=int(Cat.SWELL), wave=0))
            big["carrier_injected"] = True

    events.sort(key=lambda e: e.start)
    # ---- GAP BRIDGING (Phase 5, interpretive) --------------------------
    # The macro density track culls, the gesture track stretches slots, and
    # occasionally the two align into a 15-25 second hole with nothing but the
    # air bed in it. Holes are legitimate; DEAD AIR is not. In the spirit of
    # the Phase 2 carrier guarantee (and of the requested "long decays"), any
    # gap between consecutive note STARTS longer than max(8 s, 5% of the
    # piece) gets ONE quiet, long, wet swell spanning it -- a floor to the
    # silence, not a filler texture. Bridges are counted in the metadata and
    # deliberately bypass the density cull (a bridge that can be culled is
    # not a guarantee).
    bridges = 0
    if catmap is not None and len(events) > 1:
        swells = catmap.get(Cat.SWELL) or []
        if swells:
            # COVERAGE, not note starts: a note starting at t with dur 0.05
            # leaves a hole right after it. Sweep the events in start order,
            # track the furthest sounding end, and bridge every uncovered
            # stretch longer than the threshold. Struck categories ring down
            # rather than sustain, so their coverage is capped at a few
            # seconds regardless of p3.
            # bounded above: 3.3% of a 45-minute piece would allow 89 s of
            # dead air, which is not a hole, it is an ending. 20 s is the cap.
            gap_min = min(20.0, max(8.0, cfg.dur_sec * 0.033))
            spans = []
            for e in sorted(events, key=lambda e: e.start):
                tau = INSTR_TAU.get(e.instr)
                cov = e.dur if tau is None else min(e.dur, 3.0 * tau)
                spans.append((e.start, e.start + cov))
            cur_end = spans[0][1]
            holes = []
            for st, en in spans[1:]:
                if st - cur_end > gap_min:
                    holes.append((cur_end, st))
                cur_end = max(cur_end, en)
            for a, b in holes:
                t0 = max(0.0, a - 0.5)
                dur = (b - t0) + 0.5
                events.append(Event(
                    instr=rng.choice(swells), start=t0, dur=dur,
                    index=cfg.scale.basekey + rng.choice([-12, -5, 0]),
                    amp=rng.uniform(0.08, 0.16), pan=rng.uniform(0.35, 0.65),
                    send=rng.uniform(0.5, 0.75), slew=rng.uniform(0.3, 0.6),
                    cat=int(Cat.SWELL), wave=0,
                ))
                bridges += 1

    return events, {"sections": seclog, "trace": trace,
                    "seq": [s.name for s in secs], "macro": macro_log,
                    "bridges": bridges,
                    "rooms": [(t, r.l3.name, r.fb_scale, r.cut_scale, r.width)
                              for t, r in rooms]}


# ---------------------------------------------------------------------------
# Emission
# ---------------------------------------------------------------------------
def rooms_table(rooms: list) -> str:
    """giRooms: rows of (t_start, fb_scale, cut_scale, width), terminated by a
    t=-1 row. Built score-side because only the score knows the section
    boundaries; sized to the next power-of-2-ish GEN-2 requirement."""
    rows = []
    for (t, _name, fbs, cuts, wid) in rooms:
        rows += [f"{t:.4f}", f"{fbs:.4f}", f"{cuts:.4f}", f"{wid:.4f}"]
    rows += ["-1", "1", "1", "1"]
    vals = " ".join(rows)
    size = len(rows)
    return f"f 900 0 -{size} -2 {vals}"


def build_sco(cfg: Config, events: list[Event], stats: dict) -> str:
    lines = [
        "; ---- Orange Fur score ------------------------------------------",
        f"; seed tag {cfg.seed}   nodes {cfg.nodes}   notes {len(events)}",
        f"; amp compensation: alpha={stats['alpha']}, global gain "
        f"{stats['gain']:.5f}, predicted peak {stats['predicted_peak']:.4f}",
        f"; max concurrency {stats['max_concurrency']}, "
        f"mean {stats['mean_concurrency']:.1f}",
        "",
        "; tuning table (GEN -2, for cpstuni)",
        cfg.scale.ftable(TUNING_TABLE),
        "",
        "; room table: (t, fb_scale, cut_scale, width) per section, t=-1 ends",
        rooms_table(stats.get("rooms", [])),
        "",
        f"i 90 0 {cfg.dur_sec + 8:.3f}          ; air bed",
        f"i 99 0 {cfg.dur_sec + 12:.3f}         ; master bus (+ reverb tail)",
        "",
    ]
    for e in events:
        lines.append(
            f"i {e.instr} {e.start:.4f} {e.dur:.4f} {e.index} "
            f"{e.amp:.6f} {e.pan:.4f} {e.send:.4f} {e.slew:.4f} {e.wave} "
            f"{e.glide:.4f} {e.gcurve:.4f}"
        )
    lines.append("")
    lines.append("e")
    return "\n".join(lines)
