"""Phase 19 tests.  python3 tests/test_p19.py"""
from __future__ import annotations

import math
import random
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import roughness as RG
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.score import graph_events

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])


# ------------------------------------------------------------------- curve
def test_curve():
    d0 = RG.pair_dissonance(400, 1, 400, 1)
    ds = [(sep, RG.pair_dissonance(400, 1, 400 + sep, 1))
          for sep in range(1, 400, 3)]
    peak_sep, peak = max(ds, key=lambda t: t[1])
    check("curve: unison is zero", abs(d0) < 1e-9)
    check("curve: peak near the critical band (15-45 Hz sep at 400 Hz)",
          15 <= peak_sep <= 45, peak_sep)
    check("curve: monotone falloff past the peak",
          all(b[1] <= a[1] + 1e-12 for a, b in
              zip([d for d in ds if d[0] >= peak_sep][:-1],
                  [d for d in ds if d[0] >= peak_sep][1:])))
    check("curve: amplitude bilinear", abs(
        RG.pair_dissonance(400, 0.5, 425, 0.5)
        - 0.25 * RG.pair_dissonance(400, 1, 425, 1)) < 1e-12)
    # internal roughness excluded: one rich note = zero
    check("curve: a single note has zero sonority roughness (timbre, "
          "not harmony)",
          RG.sonority_roughness([(200, 1, RG.FALLBACK)]) == 0.0)


def test_calibration():
    cal = RG.Calibration([1.0, 2.0, 3.0, 4.0])
    ps = [cal.percentile(x) for x in (0.5, 1.5, 2.5, 3.5, 9.0)]
    check("calib: percentile monotone, endpoints 0/1",
          ps == sorted(ps) and ps[0] == 0.0 and ps[-1] == 1.0, ps)


def test_layouts():
    # tension segment draw layout fixed across prev states + names
    r1, r2 = random.Random(4), random.Random(4)
    RG.draw_tension(r1, "INTRO", None)
    RG.draw_tension(r2, "BREAKDOWN", RG.TensionSeg(0.9, 0.9, "flat"))
    check("layout: draw_tension fixed across chain states",
          r1.random() == r2.random())
    segs = [RG.draw_tension(random.Random(k), "CHORUS", None)
            for k in range(100)]
    check("layout: shape labels truthful (rise up, fall down)",
          all(s.t_end >= s.t_start for s in segs if s.shape == "rise")
          and all(s.t_end <= s.t_start for s in segs if s.shape == "fall"))
    prev, chained = None, []
    r = random.Random(11)
    for name in ("INTRO", "VERSE", "CHORUS"):
        seg = RG.draw_tension(r, name, prev)
        if prev is not None:
            chained.append(abs(seg.t_start - prev.t_end) <= 0.081)
        prev = seg
    check("layout: segments chain (start near previous end)", all(chained))


def test_select():
    sc = [0.3, 0.9, 0.6]
    check("select: x=0 -> candidate 0 (the pre-P19 draw)",
          RG.select(sc, 0.0) == 0)
    check("select: x=1 -> best candidate", RG.select(sc, 1.0) == 1)
    picks = [RG.select(sc, x / 10) for x in range(11)]
    check("select: monotone handover 0 -> best, no draws",
          picks[0] == 0 and picks[-1] == 1
          and all(p in (0, 1) for p in picks))


# --------------------------------------------------------------- pipeline
def _run_events(seed, tension, nodes=20, dur=3, sections=None):
    kw = dict(duration=dur, nodes=nodes, tension=tension)
    if sections:
        kw["sections"] = sections
    cfg = Config(**kw)
    rng = random.Random(seed)
    sol = solve(nodes, rng)
    return graph_events(cfg, sol, rng)


def test_identity_and_skeleton():
    ev0, _ = _run_events(5, 0.0)
    ev0b, _ = _run_events(5, 0.0)
    check("identity: --tension 0 is deterministic",
          [(e.start, e.instr, e.index, e.det) for e in ev0]
          == [(e.start, e.instr, e.index, e.det) for e in ev0b])
    ev1, _ = _run_events(5, 1.0)
    sk0 = [(round(e.start, 6), e.instr, round(e.amp, 6), e.echo)
           for e in ev0 if e.echo == 0]
    sk1 = [(round(e.start, 6), e.instr, round(e.amp, 6), e.echo)
           for e in ev1 if e.echo == 0]
    check("skeleton: tension 0 and 1 share times/instruments/amps "
          "(pitch-realization remix class)", sk0 == sk1)
    check("skeleton: tension 1 actually changes pitches",
          [e.index for e in ev0 if e.echo == 0]
          != [e.index for e in ev1 if e.echo == 0])


def _sep(tension, seeds=8):
    hi, lo = [], []
    for seed in range(seeds):
        _, meta = _run_events(seed, tension, nodes=24, dur=4, sections=5)
        for m in meta["macro"]:
            ach = m.get("tension_ach")
            if ach is None:
                continue
            tgt = (float(m["tension"].split("->")[0])
                   + float(m["tension"].split("->")[1].split()[0])) / 2
            (hi if tgt >= 0.45 else lo).append(ach)
    return hi, lo


def test_achieved_vs_target():
    """The phase's central claim, tested against its own null: at
    --tension 1, sections with high targets measure rougher (windowed
    pc-harmony percentile) than sections with low targets, by a margin
    that clearly exceeds the --tension 0 natural separation. Measured
    during development: null sep ~-0.02, X=1 sep ~+0.20."""
    hi1, lo1 = _sep(1.0)
    hi0, lo0 = _sep(0.0)
    check("achieved: enough measurable sections",
          len(hi1) >= 3 and len(lo1) >= 3, (len(hi1), len(lo1)))
    sep1 = statistics.mean(hi1) - statistics.mean(lo1)
    sep0 = statistics.mean(hi0) - statistics.mean(lo0)
    check("achieved: tension 1 separates high from low targets",
          sep1 > 0.08, round(sep1, 3))
    check("achieved: separation clearly exceeds the tension-0 null",
          sep1 > sep0 + 0.06, (round(sep1, 3), round(sep0, 3)))


def test_repair_bounded():
    ev, meta = _run_events(3, 1.0, nodes=30)
    # bounded means: the run completes and skeleton math held (covered
    # above); here assert the repair could not have touched more than 8
    # terminals/section by construction -- structural, verified by reading
    # the constant. Behavioral proxy: tension 0 vs 1 pitch differences are
    # widespread but not total.
    ev0, _ = _run_events(3, 0.0, nodes=30)
    p0 = [e.index for e in ev0 if e.echo == 0]
    p1 = [e.index for e in ev if e.echo == 0]
    same = sum(1 for a, b in zip(p0, p1) if a == b)
    check("repair/(c): tension changes some pitches, not all "
          "(bounded influence)", 0 < same < len(p0), (same, len(p0)))


def test_perf():
    """Honest bound from measurement at realistic size, not the design
    estimate (which was optimistic by an order of magnitude before the
    pc-domain reduction cut scoring cost)."""
    t0 = time.time()
    for s in (1, 2):
        _run_events(s, 0.0, nodes=40, dur=4)
    base = time.time() - t0
    t0 = time.time()
    for s in (1, 2):
        _run_events(s, 1.0, nodes=40, dur=4)
    tens = time.time() - t0
    check("perf: tension overhead bounded (< 40% at nodes=40)",
          tens < base * 1.40, f"{base:.2f}s -> {tens:.2f}s")


def test_e2e():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "12",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    r = run("--tension", "0.7", "--out", "/tmp/p19a.wav")
    check("e2e: tension report line with truthful shapes",
          re.search(r"tension\s+\w{3}: \d\.\d\d->\d\.\d\d "
                    r"(flat|rise|fall|arch)", r.stdout))
    tok = re.search(r"replay\s+(\S+)", r.stdout).group(1)
    run("--tension", "0.7", "--replay", tok, "--out", "/tmp/p19b.wav")
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p19a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p19b.csd").read_text())
    check("e2e: replay deterministic at tension 0.7", a == b)
    r0 = run("--out", "/tmp/p19c.wav", "--replay", tok)
    check("e2e: same token accepted across tension values (remix class)",
          r0.returncode == 0 and tok.split(":")[1] in r0.stdout)


if __name__ == "__main__":
    print("curve:");     test_curve()
    print("calib:");     test_calibration()
    print("layouts:");   test_layouts()
    print("select:");    test_select()
    print("identity:");  test_identity_and_skeleton()
    print("achieved:");  test_achieved_vs_target()
    print("bounded:");   test_repair_bounded()
    print("perf:");      test_perf()
    print("e2e:");       test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
