"""
varispeed.py -- Phase 18. TAPE-SPEED AUTOMATION.

A per-section speed curve s(t) -- built from three gestures on a Bjorklund
segment grid -- warps the section's ECHO TRAINS. Source notes never move,
and TAPE LOOPS ARE PROTECTED (P10 rule: protected processes bypass
decoration, and the transport is a decoration-layer treatment -- a warped
loop's printed realignment time would be a lie). So the N^2 budget and
every timing contract hold by construction, --echo 0 strips everything
warpable, and any two echo-specs share a replay token exactly as P17
promised.

GESTURES (drawn per segment):
  hold        s stays where it is
  sweep       s glides to a drawn target across the segment -- pitch and
              time smear together, the classic hand-on-the-reel move
  jump        s steps to the target AT the segment boundary -- the
              "silent" jump: boundaries fall between repeats far more often
              than inside notes, and a note that does span one simply keeps
              its own segment's trajectory (no mid-note discontinuity)

PHYSICS. Tape at speed s plays tape-time dtau in real-time dtau/s and
transposes by 1200*log2(s) cents. Times remap through the integrator
T(tau) = integral 0..tau of dtau'/s; durations through the same map; pitch
adds 1200*log2(s(start)) cents of p12 and the within-note speed change
rides p13 (detg += cents(end) - cents(start)). Speed targets are drawn
symmetrically in LOG space, so a section's warped material neither runs
systematically long nor short.

Gated by [echo.varispeed] in the echo-spec (additive to schema 1; existing
spec files remain valid). Absent or enabled = false: never applied -- but
the draws are consumed unconditionally (fixed layout, MAXSEG slots), the
house pattern, so enabling varispeed does not re-roll the piece.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .macro import bjorklund

MAXSEG = 7


@dataclass
class Segment:
    t0: float          # section-relative start (seconds)
    t1: float
    kind: str          # hold | sweep | jump
    s0: float          # speed at t0
    s1: float          # speed at t1 (== s0 for hold; jump: s1 from t0 on)

    def speed_at(self, t: float) -> float:
        if self.kind == "sweep" and self.t1 > self.t0:
            u = min(1.0, max(0.0, (t - self.t0) / (self.t1 - self.t0)))
            # linear in LOG speed: constant cents/second, the tape feel
            return math.exp(math.log(self.s0)
                            + u * (math.log(self.s1) - math.log(self.s0)))
        return self.s1 if self.kind == "jump" else self.s0


@dataclass
class VsPlan:
    active: bool
    depth_cents: float
    segments: list

    def describe(self) -> str:
        if not self.active:
            return ""
        kinds = " ".join(s.kind for s in self.segments)
        return (f"depth ±{self.depth_cents:.0f}c, "
                f"{len(self.segments)} segs ({kinds})")

    # -------- the physics --------
    def speed_at(self, t: float) -> float:
        for s in self.segments:
            if s.t0 <= t < s.t1:
                return s.speed_at(t)
        return self.segments[-1].s1 if self.segments else 1.0

    def cents_at(self, t: float) -> float:
        return 1200.0 * math.log2(self.speed_at(t))

    def warp_time(self, t: float) -> float:
        """T(t) = integral 0..t d tau / s(tau), EXACT piecewise: holds and
        jumps are plateaus (dt/s); a log-linear sweep s(u) = s0*e^(uL)
        integrates in closed form to (t1-t0)*(1 - e^-L)/(s0*L). No grid, no
        discontinuity error (the trapezoid draft lost 12.5 ms per jump)."""
        if t <= 0 or not self.segments:
            return t
        acc = 0.0
        for s in self.segments:
            if t <= s.t0:
                break
            hi = min(t, s.t1)
            w = hi - s.t0
            if w <= 0:
                continue
            if s.kind == "sweep" and s.t1 > s.t0 and s.s1 != s.s0:
                L_full = math.log(s.s1 / s.s0)
                L = L_full * (w / (s.t1 - s.t0))
                acc += w * (1.0 - math.exp(-L)) / (s.s0 * L)
            else:
                acc += w / (s.s1 if s.kind == "jump" else s.s0)
        if t > self.segments[-1].t1:
            acc += (t - self.segments[-1].t1) / self.segments[-1].s1
        return acc


def draw_plan(rng: random.Random, span: float, vcfg: dict) -> VsPlan:
    """FIXED DRAW LAYOUT: gate, grid, and all MAXSEG slots consumed every
    section regardless of the config -- enabling varispeed never re-rolls
    the piece. Config supplies enabled/prob/depth/segment ranges."""
    gate = rng.random()
    pulses = rng.randint(int(vcfg["segments"][0]), int(vcfg["segments"][1]))
    steps = rng.randint(8, 16)
    depth = rng.uniform(vcfg["depth"][0], vcfg["depth"][1])
    slot = [(rng.random(), rng.uniform(-1.0, 1.0)) for _ in range(MAXSEG)]

    active = bool(vcfg["enabled"]) and gate < float(vcfg["prob"])
    pulses = min(pulses, steps, MAXSEG)
    pat = bjorklund(pulses, steps)
    bounds = [i / steps * span for i, h in enumerate(pat) if h] + [span]
    if bounds[0] > 0:
        bounds.insert(0, 0.0)

    segs = []
    s_cur = 1.0
    smax = 2 ** (depth / 1200.0)
    for i in range(len(bounds) - 1):
        kind_r, tgt_r = slot[i % MAXSEG]
        kind = ("hold" if kind_r < 0.34
                else "sweep" if kind_r < 0.75 else "jump")
        target = smax ** tgt_r          # symmetric in log speed
        if kind == "hold":
            s0 = s1 = s_cur
        elif kind == "sweep":
            s0, s1 = s_cur, target
        else:
            s0 = s1 = target
        segs.append(Segment(t0=bounds[i], t1=bounds[i + 1],
                            kind=kind, s0=s0, s1=s1))
        s_cur = s1
    return VsPlan(active=active, depth_cents=depth, segments=segs)


def warp_events(events: list, plan: VsPlan, t0: float,
                dur_total: float) -> None:
    """Apply the automation IN PLACE to a section's tape-domain notes.
    `t0` is the section start; times inside are section-relative. Pitch
    adds p12 cents at the note's tape position; p13 accumulates the
    within-note speed change; times and durations remap through the
    integrator. Piece-level clamps (spill +4 s, bus close +12 s) are the
    caller's contract and re-applied here."""
    if not plan.active:
        return
    for e in events:
        tau = e.start - t0
        c0 = plan.cents_at(tau)
        new_start = t0 + plan.warp_time(tau)
        tau_end = tau + e.dur
        new_end = t0 + plan.warp_time(tau_end)
        c1 = plan.cents_at(min(tau_end, plan.segments[-1].t1 - 1e-9)
                           if plan.segments else tau_end)
        e.start = new_start
        e.dur = max(0.02, new_end - new_start)
        e.det = e.det + c0
        # a jump inside the note is NOT ridden (silent-jump semantics);
        # only sweep motion within the note's own trajectory is
        if abs(c1 - c0) > 0.01 and _same_sweep(plan, tau, tau_end):
            e.detg = e.detg + (c1 - c0)


def _same_sweep(plan: VsPlan, a: float, b: float) -> bool:
    seg = None
    for s in plan.segments:
        if s.t0 <= a < s.t1:
            seg = s
            break
    return seg is not None and seg.kind == "sweep" and b <= seg.t1
