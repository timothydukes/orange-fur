"""
routing.py -- Phase 4. Effects, buses, and the ONE ROUTING STRUCT.

THE POINT OF THE STRUCT. Phase 0 left a landmine in a comment: the amp model in
score.py "must stay in sync with instr 99 in orc.py". Two descriptions of the
same signal chain, maintained by hand, in two languages. Phase 4 removes it:
`Routing` is the single description, and BOTH the generated master-bus Csound
text (master_text) AND the amp model's wet-path gain (wet_power_gain) are
derived from it. There is nothing to keep in sync because there is only one
thing.

TOPOLOGY, drawn per run:

    notes --> gaDryL/R ------------------------------------+
    notes --> gaSend1L/R --> [chain: unit, unit, ...] --+  |
    notes --> gaSend2L/R --> [chain: ...] --------------+--+--> wetdry --> out
    ...       (K = 2..4 buses)                          |
              each chain = 1..4 effect units in series,
              each with a drawn return gain

  * --wetdry stays a SINGLE GLOBAL dry<->wet crossfade, per spec. The buses
    multiply the variety of what "wet" means, not the number of knobs.
  * Each INSTRUMENT is wired to one send bus at generation time (interpretive:
    this keeps the p-field contract fixed -- p7 is still the one send amount --
    and the per-section instrument rebinding moves material between tanks
    section by section, which is where the movement should come from anyway).
  * At least one chain starts with a room-class reverb; the FIRST such unit is
    the ROOM-BEARING unit, and the L3 room table (f 900) steps ITS feedback
    and cutoff at section boundaries, exactly as instr 99 did in Phase 2-3.
  * ~50 effect units are generated per run; --subset does not apply to
    effects (the spec's subset is "percent of the generated orchestra"), but
    only the drawn chains are ever instantiated -- the rest of the pool
    exists so that two runs draw different chains.

EFFECT FAMILIES (the spec's list):
    shimmer   reverbsc with an OCTAVE-UP feedback loop: the tank's return is
              pitch-shifted up an octave (two-tap crossfading delay-line
              shifter, UDO OctUp) and fed back into the tank input
    spring    dispersive allpass cascade with a resonant "boing" band
    phaser    phaser2 bank swept by a slow LFO
    flanger   modulated delay with feedback (flanger opcode)
    resbp     resonant bandpass sweep (moogladder-ish center sweep on resonz)
    tapestop  interpolated delay whose read pointer periodically DECELERATES
              to a stop and snaps back -- drawn cycle and droop
    buscONV   the spec's "literally convolving two bus channels at a
              bitcrushed sample rate": channel B is snapshotted into a table
              at a decimated rate (samphold + tablew at kdec Hz, quantised to
              idepth bits), and channel A is dconv-ed against that table.
              The kernel refreshes every icyc seconds. It IS a literal
              convolution of the two channels, at low resolution, windowed.

SAFETY: every feedback figure <= 0.92 and dcblocked; no `limit`/`clip`/`compress`
anywhere in the master text (the no-limiter guard now greps ALL of it); all
denominators floored.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

# ------------------------------------------------------------------ UDOs
UDO_TEXT = r"""
; OctUp -- delay-line pitch shifter, ratio 2 (octave up), for shimmer feedback.
; Two read taps sweep a short window half a cycle apart, each windowed by a
; raised cosine, crossfaded -- the classic granular shifter. iwin is the sweep
; window in seconds. a-rate in/out; i-rate params only.
opcode OctUp, a, ai
  ain, iwin  xin
  ; PITCH MATH (this was wrong once): output rate = 1 - d'(t) where d is the
  ; tap delay. For an OCTAVE UP we need rate 2, i.e. d' = -1: the delay must
  ; SHRINK at one second per second. tap = (1 - phase) * iwin does that. The
  ; first version used tap = phase * iwin (d' = +1, rate 0): a pitch-to-DC
  ; shifter, caught by the octave-energy test, not by ear or by eye.
  irate =  1 / iwin
  abuf  delayr  iwin * 2 + 0.01
  aph1  phasor  irate
  aph2  phasor  irate, 0.5
  atap1 deltapi  (1 - aph1) * iwin + 0.0006   ; floor: deltapi needs >= 1 sample
  atap2 deltapi  (1 - aph2) * iwin + 0.0006
        delayw  ain
  ; window = sin(pi * phase): read the HALF sine -- a 0..1..0 bump, zero at the
  ; splice points, which is what hides the tap jumps
  awin1 tablei  aph1 * 0.5, giSine, 1, 0, 1
  awin2 tablei  aph2 * 0.5, giSine, 1, 0, 1
  xout  atap1 * awin1 + atap2 * awin2
endop
"""


@dataclass
class Unit:
    kind: str
    params: dict
    gain: float          # small-signal through-gain estimate (for the model)
    smear: float         # how much the unit spreads energy in time (reverb ~ big)
    cost: float          # oscili units
    code_l: str = ""     # generated later (stereo: two mono lines or one block)


@dataclass
class Chain:
    bus: int             # 1-based send bus index
    units: list[Unit]
    ret: float           # return gain into the wet sum

    def gain(self) -> float:
        """Small-signal THROUGH-gain of the chain. Note what is NOT here:
        `smear`. Smear is not a gain -- it describes how a unit spreads energy
        in TIME, and the amp model already accounts for that separately (it
        convolves the send envelope with the tank's RT). Multiplying by
        (1 + smear) here as well double-counted the reverbs and biased every
        wet render about 3-4 dB low."""
        g = self.ret
        for u in self.units:
            g *= u.gain
        return g

    def has_reverb(self) -> bool:
        """Does this chain ACCUMULATE energy? Only a feedback tank does. A
        phaser -> flanger chain passes energy through; applying the reverb
        accumulation term to it (as Phase 4 did, globally) inflates it."""
        return any(u.kind in ROOMY for u in self.units)

    def cost(self) -> float:
        return sum(u.cost for u in self.units)


@dataclass
class Routing:
    n_buses: int
    chains: list[Chain]
    room_chain: int      # index into chains of the room-bearing chain
    pool_size: int       # how many units were generated (reporting)

    def wet_power_gain(self, accum: float) -> float:
        """Power gain of the whole wet path, given the reverb ACCUMULATION
        factor `accum` that the amp model computes from --space.

        Each instrument is wired to exactly ONE send bus, so a chain receives
        roughly its share of the total send energy -- the chains are averaged,
        not summed. A chain that contains a feedback tank accumulates (accum);
        a chain of phasers and flangers does not.

        This governs DRIVE into the nonlinear stages; the output level itself is
        set exactly, after the render, by normalisation."""
        if not self.chains:
            return 1.0
        tot = 0.0
        for c in self.chains:
            g = c.gain()
            tot += g * g * (accum if c.has_reverb() else 1.0)
        return max(0.05, tot / len(self.chains))

    def cost(self) -> float:
        return sum(c.cost() for c in self.chains)


# ------------------------------------------------------------- unit draws
def u_shimmer(rng) -> Unit:
    return Unit("shimmer",
                dict(fb=rng.uniform(0.72, 0.90), cut=rng.uniform(6000, 12000),
                     shim=rng.uniform(0.18, 0.45), win=rng.uniform(0.04, 0.09)),
                gain=1.0, smear=rng.uniform(2.0, 4.5), cost=14.0)


def u_spring(rng) -> Unit:
    return Unit("spring",
                dict(n=rng.randint(4, 6), t0=rng.uniform(0.003, 0.011),
                     fb=rng.uniform(0.55, 0.85), boing=rng.uniform(900, 3200)),
                gain=0.9, smear=rng.uniform(0.8, 1.8), cost=6.0)


def u_phaser(rng) -> Unit:
    return Unit("phaser",
                dict(ord=rng.choice([4, 6, 8]), rate=rng.uniform(0.03, 0.5),
                     depth=rng.uniform(0.3, 0.9), sep=rng.uniform(0.5, 3.0),
                     fb=rng.uniform(0.0, 0.6)),
                gain=1.0, smear=0.05, cost=5.0)


def u_flanger(rng) -> Unit:
    return Unit("flanger",
                dict(rate=rng.uniform(0.05, 0.8), dep=rng.uniform(0.001, 0.006),
                     fb=rng.uniform(0.2, 0.7)),
                gain=1.0, smear=0.1, cost=4.0)


def u_resbp(rng) -> Unit:
    return Unit("resbp",
                dict(lo=rng.uniform(180, 500), hi=rng.uniform(1200, 5200),
                     rate=rng.uniform(0.02, 0.35), bw=rng.uniform(0.15, 0.6)),
                gain=0.8, smear=0.05, cost=3.0)


def u_tapestop(rng) -> Unit:
    return Unit("tapestop",
                dict(cyc=rng.uniform(3.0, 14.0), droop=rng.uniform(0.35, 0.95),
                     dmax=rng.uniform(0.08, 0.35), mix=rng.uniform(0.4, 1.0)),
                gain=0.9, smear=0.4, cost=5.0)


def u_streson(rng) -> Unit:
    """Phase 14: FIELD-TUNED STRING RESONATORS. Two or three streson voices
    per channel, each tracking one of the section's four field degrees (from
    giReso, written by the score) at a drawn octave. Near-unity small-signal
    gain via the classic (1 - fb) makeup; fb bounded at 0.92 (P3's feedback-
    safety lesson: rails at build time, not hope at render time). The tank
    RINGS on the harmony of whatever section is playing -- score-domain
    delays and field-conformant material feed a tank tuned to the same
    degrees, which is the compound payoff this arc was pointed at."""
    nv = rng.choice([2, 2, 3])
    return Unit("streson",
                dict(nv=nv,
                     sel=[rng.randrange(4) for _ in range(3)],
                     oct=[rng.choice([-1, 0, 0, 1]) for _ in range(3)],
                     fb=min(0.92, rng.uniform(0.70, 0.92)),
                     port=rng.uniform(0.08, 0.30)),
                gain=1.1, smear=0.5, cost=6.0)


def u_modes(rng) -> Unit:
    """Phase 14: FIELD-TUNED MODAL BANK. Four mode filters on the section's
    field degrees across drawn octaves. mode's resonance gain scales with Q,
    so each voice is scaled by 1/Q (calibrated; see test_p14) -- P3's
    balance-calibration lesson applied at construction."""
    return Unit("modes",
                dict(q=rng.uniform(60.0, 180.0),
                     oct=[rng.choice([-1, 0, 0, 1]) for _ in range(4)],
                     port=rng.uniform(0.08, 0.25)),
                gain=1.0, smear=0.35, cost=5.0)


def u_busconv(rng) -> Unit:
    return Unit("busconv",
                dict(size=rng.choice([128, 256, 512]),
                     dec=rng.uniform(900, 4000), bits=rng.choice([5, 6, 8]),
                     cyc=rng.uniform(2.0, 9.0), mix=rng.uniform(0.25, 0.7)),
                gain=0.7, smear=0.6, cost=18.0)


UNIT_DRAWS = [u_shimmer, u_spring, u_phaser, u_flanger,
              u_resbp, u_tapestop, u_busconv,
              u_streson, u_modes]          # Phase 14: field-tuned resonators

# streson at fb 0.9 accumulates energy like a small tank; modes ring
# briefly (Q/(pi*f) ~ a quarter second) and pass through
ROOMY = {"shimmer", "spring", "streson"}


def generate_routing(rng: random.Random) -> Routing:
    """~50 units drawn into a pool; K buses; each bus draws a chain of 1..4
    from the pool without replacement. Chain 0 is guaranteed to start with a
    room-class reverb (the room-bearing unit)."""
    pool = [rng.choice(UNIT_DRAWS)(rng) for _ in range(50)]
    # make sure the pool has at least one roomy unit
    if not any(u.kind in ROOMY for u in pool):
        pool[0] = u_shimmer(rng)

    n_buses = rng.randint(2, 4)
    chains: list[Chain] = []
    used: set[int] = set()

    def take(pred=None):
        cand = [i for i in range(len(pool))
                if i not in used and (pred is None or pred(pool[i]))]
        if not cand:
            cand = [i for i in range(len(pool)) if i not in used]
        i = rng.choice(cand)
        used.add(i)
        return pool[i]

    for b in range(1, n_buses + 1):
        k = rng.randint(1, 4)
        units = []
        if b == 1:
            units.append(take(lambda u: u.kind in ROOMY))   # room-bearing first
            for _ in range(k - 1):
                units.append(take())
        else:
            for _ in range(k):
                units.append(take())
        chains.append(Chain(bus=b, units=units, ret=rng.uniform(0.5, 1.0)))

    return Routing(n_buses=n_buses, chains=chains, room_chain=0,
                   pool_size=len(pool))


# --------------------------------------------------------- code generation
def _reso_scan(cid: str) -> str:
    """k-rate scan of giReso (rows: t, d1..d4) -- the exact giRooms idiom.
    Each resonator instance keeps its own row cursor."""
    return f"""
  kd0_{cid} init 0
  kd1_{cid} init 0
  kd2_{cid} init 0
  kd3_{cid} init 0
  kri_{cid} init 0
  krt_{cid} table kri_{cid} * 5, giReso
  if krt_{cid} >= 0 && ktime >= krt_{cid} then
    kd0_{cid} table kri_{cid} * 5 + 1, giReso
    kd1_{cid} table kri_{cid} * 5 + 2, giReso
    kd2_{cid} table kri_{cid} * 5 + 3, giReso
    kd3_{cid} table kri_{cid} * 5 + 4, giReso
    kri_{cid} = kri_{cid} + 1
  endif"""


def _unit_code(u: Unit, cid: str, inl: str, inr: str,
               is_room: bool) -> tuple[str, str, str]:
    """Csound block for one unit. Returns (code, outL, outR). cid is a unique
    suffix for variable names. If is_room, the unit's feedback/cutoff are the
    k-rate room-stepped kfb/kcut computed in the master preamble."""
    p = u.params
    ol, orr = f"a{cid}L", f"a{cid}R"
    if u.kind == "shimmer":
        fb = "kfb" if is_room else f"{p['fb']:.3f}"
        cut = "kcut" if is_room else f"{p['cut']:.0f}"
        code = f"""; shimmer (reverbsc + octave-up feedback){' [ROOM-BEARING]' if is_room else ''}
  ash{cid}L  init 0
  ash{cid}R  init 0
  ain{cid}L  =  {inl} + ash{cid}L * {p['shim']:.3f}
  ain{cid}R  =  {inr} + ash{cid}R * {p['shim']:.3f}
  {ol}, {orr}  reverbsc  ain{cid}L, ain{cid}R, {fb}, {cut}
  ash{cid}L  OctUp  {ol}, {p['win']:.4f}
  ash{cid}R  OctUp  {orr}, {p['win']:.4f}
  ash{cid}L  dcblock2  ash{cid}L
  ash{cid}R  dcblock2  ash{cid}R"""
    elif u.kind == "spring":
        n = p["n"]
        lines = [f"; spring (dispersive allpass cascade){' [ROOM-BEARING]' if is_room else ''}"]
        curl, curr = inl, inr
        for i in range(n):
            t = p["t0"] * (1.0 + 0.6 * i)
            fb = "kfb * 0.9" if is_room else f"{p['fb']:.3f}"
            lines.append(f"  asp{cid}{i}L  alpass  {curl}, {fb}, {t:.5f}")
            lines.append(f"  asp{cid}{i}R  alpass  {curr}, {fb}, {t * 1.07:.5f}")
            curl, curr = f"asp{cid}{i}L", f"asp{cid}{i}R"
        lines.append(f"  {ol}  reson  {curl}, {p['boing']:.0f}, {p['boing']:.0f} * 0.5, 1")
        lines.append(f"  {orr}  reson  {curr}, {p['boing'] * 1.03:.0f}, {p['boing']:.0f} * 0.5, 1")
        lines.append(f"  {ol}  =  {ol} * 0.7 + {curl} * 0.5")
        lines.append(f"  {orr}  =  {orr} * 0.7 + {curr} * 0.5")
        code = "\n".join(lines)
    elif u.kind == "phaser":
        code = f"""; phaser
  klf{cid}  oscili  {p['depth']:.3f}, {p['rate']:.4f}, giSine
  kcf{cid}  =  800 + 700 * klf{cid}
  {ol}  phaser2  {inl}, kcf{cid}, 0.5, {p['ord']}, 1, {p['sep']:.3f}, {p['fb']:.3f}
  {orr}  phaser2  {inr}, kcf{cid} * 1.02, 0.5, {p['ord']}, 1, {p['sep']:.3f}, {p['fb']:.3f}
  {ol}  =  {ol} * 0.5 + {inl} * 0.5
  {orr}  =  {orr} * 0.5 + {inr} * 0.5"""
    elif u.kind == "flanger":
        code = f"""; flanger
  klf{cid}  oscili  {p['dep']:.5f}, {p['rate']:.4f}, giSine
  adl{cid}  =  a(klf{cid}) + {p['dep'] + 0.0015:.5f}
  {ol}  flanger  {inl}, adl{cid}, {p['fb']:.3f}
  {orr}  flanger  {inr}, adl{cid} * 1.05, {p['fb']:.3f}
  {ol}  dcblock2  {ol}
  {orr}  dcblock2  {orr}"""
    elif u.kind == "resbp":
        code = f"""; resonant bandpass sweep
  klf{cid}  oscili  0.5, {p['rate']:.4f}, giSine
  kcf{cid}  =  {p['lo']:.0f} * exp(log({p['hi']:.0f} / {p['lo']:.0f}) * (0.5 + klf{cid}))
  {ol}  resonz  {inl}, kcf{cid}, kcf{cid} * {p['bw']:.3f}, 1
  {orr}  resonz  {inr}, kcf{cid} * 1.01, kcf{cid} * {p['bw']:.3f}, 1"""
    elif u.kind == "tapestop":
        # read pointer velocity droops to (1-droop) then snaps back each cycle
        code = f"""; tape-stop interpolated delay
  kph{cid}  phasor  {1.0 / p['cyc']:.5f}
  kvel{cid} =  1 - {p['droop']:.3f} * kph{cid}
  kdt{cid}  =  {p['dmax']:.4f} * (1 - kvel{cid})   ; lag grows as the tape slows
  adt{cid}  interp  kdt{cid}
  abf{cid}L delayr  {p['dmax'] + 0.05:.3f}
  atp{cid}L deltapi adt{cid}
            delayw  {inl}
  abf{cid}R delayr  {p['dmax'] + 0.05:.3f}
  atp{cid}R deltapi adt{cid} * 1.02
            delayw  {inr}
  {ol}  =  atp{cid}L * {p['mix']:.3f} + {inl} * {1 - p['mix']:.3f}
  {orr}  =  atp{cid}R * {p['mix']:.3f} + {inr} * {1 - p['mix']:.3f}"""
    elif u.kind == "streson":
        nv = p["nv"]
        fb = p["fb"]
        scan = _reso_scan(cid)
        vl, vr = [], []
        for v in range(nv):
            sel, octv = p["sel"][v], p["oct"][v]
            code_v = f"""
  kix{cid}v{v}  =  gibasekey + kd{sel}_{cid} + {octv} * giGrades
  kcp{cid}v{v}  cpstun 1, kix{cid}v{v}, giTun
  ; port half-time ramps from 0: instant tracking at init (portk otherwise
  ; glides every resonator up from silence for seconds), drawn value after
  kht{cid}v{v}  linseg 0, 0.08, {p['port']:.3f}
  kcp{cid}v{v}  portk  kcp{cid}v{v}, kht{cid}v{v}
  asl{cid}v{v}  streson {inl}, kcp{cid}v{v}, {fb:.3f}
  asr{cid}v{v}  streson {inr}, kcp{cid}v{v}, {fb:.3f}"""
            scan += code_v
            vl.append(f"asl{cid}v{v}")
            vr.append(f"asr{cid}v{v}")
        mk = (1.0 - fb) / nv          # classic streson makeup, averaged
        code = scan + f"""
  {ol}   =  ({' + '.join(vl)}) * {mk:.4f}
  {orr}  =  ({' + '.join(vr)}) * {mk:.4f}
  {ol}   dcblock2 {ol}
  {orr}  dcblock2 {orr}
  {ol}   buthp  {ol}, 45
  {orr}  buthp  {orr}, 45"""
        return code, ol, orr

    elif u.kind == "modes":
        q = p["q"]
        scan = _reso_scan(cid)
        vl, vr = [], []
        for v in range(4):
            octv = p["oct"][v]
            code_v = f"""
  kix{cid}v{v}  =  gibasekey + kd{v}_{cid} + {octv} * giGrades
  kcp{cid}v{v}  cpstun 1, kix{cid}v{v}, giTun
  kht{cid}v{v}  linseg 0, 0.08, {p['port']:.3f}
  kcp{cid}v{v}  portk  kcp{cid}v{v}, kht{cid}v{v}
  aml{cid}v{v}  mode  {inl}, kcp{cid}v{v}, {q:.1f}
  amr{cid}v{v}  mode  {inr}, kcp{cid}v{v}, {q:.1f}"""
            scan += code_v
            vl.append(f"aml{cid}v{v}")
            vr.append(f"amr{cid}v{v}")
        # mode's gain AT resonance ~ Q, so unity makeup is 1/Q per voice;
        # the extra /2 is summing headroom for 4 voices (calibrated by the
        # click test in test_p14: 1/sqrt(Q) left ~ +5 dB at Q 150)
        mk = 1.0 / (2.0 * max(1.0, q))
        code = scan + f"""
  {ol}   =  ({' + '.join(vl)}) * {mk:.5f}
  {orr}  =  ({' + '.join(vr)}) * {mk:.5f}
  {ol}   dcblock2 {ol}
  {orr}  dcblock2 {orr}"""
        return code, ol, orr

    elif u.kind == "busconv":
        size = p["size"]
        q = float(2 ** (p["bits"] - 1))
        code = f"""; bus-channel convolution at a bitcrushed sample rate (literal, per spec):
; channel R is decimated ({p['dec']:.0f} Hz) and quantised ({p['bits']} bit), written
; cyclically into a {size}-point kernel table; channel L is dconv-ed against it.
; The kernel refreshes as it is overwritten every {size / p['dec']:.2f} s of decimated time.
  itb{cid}  ftgen  0, 0, {size}, -2, 0
  kks{cid}  init  0
  ksm{cid}  downsamp  {inr}
  ktk{cid}  metro  {p['dec']:.1f}
  if ktk{cid} == 1 then
    kqz{cid}  =  round(ksm{cid} * {q:.0f}) / {q:.0f}
    tablew  kqz{cid}, kks{cid}, itb{cid}
    kks{cid}  =  kks{cid} + 1 > {size - 1} ? 0 : kks{cid} + 1
  endif
  acv{cid}  dconv  {inl} * {1.0 / size:.6f}, {size}, itb{cid}
  acv{cid}  dcblock2  acv{cid}
  {ol}  =  acv{cid} * {p['mix']:.3f} + {inl} * {1 - p['mix']:.3f}
  {orr}  =  acv{cid} * {p['mix']:.3f} + {inr} * {1 - p['mix']:.3f}"""
    else:
        code = f"  {ol} = {inl}\n  {orr} = {inr}"
    return code, ol, orr


def master_text(cfg, routing: Routing) -> str:
    """Generate instr 99 (and the bus declarations) FROM THE STRUCT."""
    K = routing.n_buses
    decl = "\n".join(f"gaSend{b}L init 0\ngaSend{b}R init 0"
                     for b in range(1, K + 1))

    body = [f"""instr 99
  ; generated from the Routing struct -- {K} send buses, {len(routing.chains)} chains
  ifb0  =  0.68 + 0.30 * $SPACE.
  icut0 =  3000 + 9000 * $SPACE.
  ktime  timeinsts
  kfbs   init 1
  kcuts  init 1
  kwid   init 1
  kidx   init 0
  kt     table  kidx * 4, giRooms
  if kt >= 0 && ktime >= kt then
    kfbs  table  kidx * 4 + 1, giRooms
    kcuts table  kidx * 4 + 2, giRooms
    kwid  table  kidx * 4 + 3, giRooms
    kidx = kidx + 1
  endif
  kfb   =  ifb0 * kfbs
  kfb   =  kfb > 0.985 ? 0.985 : (kfb < 0.30 ? 0.30 : kfb)
  kcut  =  icut0 * kcuts
  kcut  =  kcut > 16000 ? 16000 : (kcut < 800 ? 800 : kcut)

  awetL  =  0
  awetR  =  0"""]

    for ci, ch in enumerate(routing.chains):
        inl, inr = f"gaSend{ch.bus}L", f"gaSend{ch.bus}R"
        body.append(f"\n  ; ---- chain {ci} on bus {ch.bus} "
                    f"({' -> '.join(u.kind for u in ch.units)}) ----")
        for ui, u in enumerate(ch.units):
            cid = f"c{ci}u{ui}"
            code, ol, orr = _unit_code(
                u, cid, inl, inr,
                is_room=(ci == routing.room_chain and ui == 0))
            body.append(code)
            inl, inr = ol, orr
        body.append(f"  awetL  +=  {inl} * {ch.ret:.3f}")
        body.append(f"  awetR  +=  {inr} * {ch.ret:.3f}")

    zero = "\n".join(f"  gaSend{b}L = 0\n  gaSend{b}R = 0"
                     for b in range(1, K + 1))
    body.append(f"""
  ; single global dry<->wet crossfade (equal-power), per spec
  iwet  =  sin($WETDRY. * 1.5707963)
  idry  =  cos($WETDRY. * 1.5707963)
  aL  =  gaDryL * idry + awetL * iwet
  aR  =  gaDryR * idry + awetR * iwet

  ; stereo width, mid-side, stepped with the room. Clean cut at the boundary.
  aM  =  (aL + aR) * 0.5
  aS  =  (aL - aR) * 0.5
  aL  =  aM + aS * kwid
  aR  =  aM - aS * kwid

  ; NO LIMITER, NO CLIPPER, DELIBERATELY (see Phase 0 findings). The peak is
  ; the score model's job; render.py verifies and normalisation is exact.
  outs  aL, aR
  gaDryL = 0
  gaDryR = 0
{zero}
endin""")
    return decl, "\n".join(body)
