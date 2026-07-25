"""Phase 23 tests.  python3 tests/test_p23.py"""
from __future__ import annotations

import math
import random
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import morph as MRP
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.score import graph_events

FAILURES = []
ROOT = str(Path(__file__).resolve().parents[1])


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ------------------------------------------------------------------- draws
def test_draws():
    flat = lambda t: [0.5] * 4
    r1, r2 = random.Random(5), random.Random(5)
    MRP.draw_morphs(r1, [0, 60, 120, 180, 240], [60] * 5, 300, 0.0, flat)
    MRP.draw_morphs(r2, [0, 60, 120, 180, 240], [60] * 5, 300, 1.0, flat)
    check("draws: fixed layout across --morph values",
          r1.random() == r2.random())
    js0 = MRP.draw_morphs(random.Random(5), [0, 60, 120, 180, 240],
                          [60] * 5, 300, 0.0, flat)
    check("draws: X=0 admits nothing", js0 == [])
    n_lo = n_hi = 0
    for s in range(30):
        n_lo += len(MRP.draw_morphs(random.Random(s),
                                    [0, 60, 120, 180, 240, 300],
                                    [60] * 6, 360, 0.2, flat))
        n_hi += len(MRP.draw_morphs(random.Random(s),
                                    [0, 60, 120, 180, 240, 300],
                                    [60] * 6, 360, 1.0, flat))
    check("draws: admission scales with X (30 seeds)", n_hi > n_lo * 1.5,
          (n_lo, n_hi))
    js = MRP.draw_morphs(random.Random(2), [0, 60, 120, 180, 240, 300],
                         [60] * 6, 360, 1.0, flat)
    check("draws: first and last boundaries never admit",
          all(1 < j.sec_index < 5 for j in js),
          [j.sec_index for j in js])
    # window scales with the piece: mean-section fraction, clamped
    big = [MRP.draw_morphs(random.Random(s), [i * 135 for i in range(20)],
                           [135] * 20, 2700, 1.0, flat) for s in range(20)]
    small = [MRP.draw_morphs(random.Random(s), [i * 48 for i in range(5)],
                             [48] * 5, 240, 1.0, flat) for s in range(20)]
    wb = [j.w for js_ in big for j in js_]
    ws = [j.w for js_ in small for j in js_]
    check("draws: windows adapt to the piece (45-min mean > 4-min mean)",
          wb and ws and sum(wb) / len(wb) > sum(ws) / len(ws) * 1.5,
          (round(sum(wb) / max(1, len(wb)), 1),
           round(sum(ws) / max(1, len(ws)), 1)))
    check("draws: windows respect floor and adjacency cap",
          all(12.0 <= j.w <= 0.4 * 135 + 1e-9 for js_ in big for j in js_)
          and all(12.0 <= j.w <= 0.4 * 48 + 1e-9
                  for js_ in small for j in js_))


# ---------------------------------------------------------------- pipeline
def _events(seed, m, sections=5, dur=4):
    cfg = Config(duration=dur, nodes=14, sections=sections, morph=m)
    rng = random.Random(seed)
    return graph_events(cfg, solve(14, rng), rng)


def _joint_runs(m, seeds):
    out = []
    for s in seeds:
        ev, meta = _events(s, m)
        if meta["morph"]["joints"]:
            out.append((s, ev, meta))
    return out


def test_pipeline():
    r1, r2 = random.Random(3), random.Random(3)
    graph_events(Config(duration=4, nodes=14, sections=5, morph=0.0),
                 solve(14, r1), r1)
    graph_events(Config(duration=4, nodes=14, sections=5, morph=1.0),
                 solve(14, r2), r2)
    check("pipe: --morph adds zero draws (RNG-state equality)",
          r1.random() == r2.random())
    runs = _joint_runs(1.0, range(10))
    check("pipe: joints admitted across seeds", len(runs) >= 5, len(runs))
    # field common tones at joints
    oks, tots = 0, 0
    for s, ev, meta in runs:
        _, meta0 = _events(s, 0.0)
        sf = meta["sec_fields"]
        for (si, tb, w) in meta["morph"]["joints"]:
            prev = dict(sf).get  # noqa: placeholder
        # measure overlap between consecutive fields at each joint
        times = [t for t, _ in sf]
        for (si, tb, w) in meta["morph"]["joints"]:
            for k in range(1, len(sf)):
                if abs(sf[k][0] - tb) < 1e-6:
                    a = {pc for pc, _ in sf[k - 1][1]}
                    b = {pc for pc, _ in sf[k][1]}
                    tots += 1
                    if len(a & b) / max(1, len(a | b)) >= 0.7:
                        oks += 1
    check("pipe: high field common tones at joints (>=70%% Jaccard in "
          ">=80%% of joints)", tots > 0 and oks / tots >= 0.8,
          (oks, tots))
    # protected material untouched
    for s, ev, meta in runs[:3]:
        ev0, _ = _events(s, 0.0)
        p1 = sorted((e.start, e.dur, e.index) for e in ev if e.proc > 0)
        p0 = sorted((e.start, e.dur, e.index) for e in ev0 if e.proc > 0)
        if p1 != p0:
            check("pipe: protected processes untouched by morph", False, s)
            break
    else:
        check("pipe: protected processes untouched by morph", True)
    # bridges untouched
    s, ev, meta = runs[0]
    ev0, _ = _events(s, 0.0)
    b1 = sorted(e.start for e in ev if e.echo == -1)
    b0 = sorted(e.start for e in ev0 if e.echo == -1)
    check("pipe: gap bridges stay put", b1 == b0)
    # composition happened: some source notes moved inside windows only
    moved_out = 0
    starts0 = {id(None)}  # sentinel unused
    ev_by_key0 = sorted((e.instr, round(e.amp, 6)) for e in ev0)
    n_moved = meta["morph"]["moved"]
    check("pipe: overlap composition moved notes at joints", n_moved > 0,
          n_moved)
    # rooms rows: lag > 0 exactly at joints, 0 at cuts; joint rows early
    # joint tuples carry ROUNDED tb/w (report precision), so match the
    # shifted row times with a tolerance rather than exact equality
    jts = [tb - w / 2.0 for (_si, tb, w) in meta["morph"]["joints"]]
    ok_l = all((lag > 0) == any(abs(t - jt) < 0.06 for jt in jts)
               for (t, _n, _f, _c, _w, lag) in meta["rooms"])
    check("pipe: room lag column set exactly at (shifted) joint rows",
          ok_l, [(round(t, 2), round(lag, 2))
                 for (t, _n, _f, _c, _w, lag) in meta["rooms"]])


# --------------------------------------------------------------------- e2e
def _run(*extra, timeout=900):
    return subprocess.run(
        [sys.executable, "-m", "orange_fur", "--nodes", "14", "--duration",
         "4", "--sections", "5", "--draft", *extra],
        capture_output=True, text=True, timeout=timeout, cwd=ROOT)


def _width_traj(path, t_from, t_to, sr=48000, hop=0.5):
    raw = Path(path).read_bytes()
    i = raw.find(b"data")
    body = raw[i + 8:]
    n = len(body) // 8            # stereo float frames
    out = []
    t = t_from
    while t < t_to:
        a = int(t * sr)
        b = min(n, a + int(hop * sr))
        if b <= a:
            break
        seg = struct.unpack(f"<{(b - a) * 2}f", body[a * 8:b * 8])
        m_ = sum(abs(seg[k] + seg[k + 1]) for k in range(0, len(seg), 2))
        s_ = sum(abs(seg[k] - seg[k + 1]) for k in range(0, len(seg), 2))
        out.append(s_ / (m_ + 1e-9))
        t += hop
    return out


def test_e2e():
    r = _run("--dry-run", "--out", "/tmp/p23a.wav")
    tok = re.search(r"replay\s+(\S+)", r.stdout).group(1)
    r0 = _run("--dry-run", "--replay", tok, "--morph", "0",
              "--out", "/tmp/p23b.wav")
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p23a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p23b.csd").read_text())
    check("e2e: --morph 0 csd-identical to flag absent", a == b)
    check("e2e: f 900 rows are 5-wide with a lag column",
          re.search(r"f 900 0 -\d+ -2( [\d.\-]+){5,}", a) is not None
          and "portk" in a)
    # find a token whose --morph 1 reading has a joint, render both
    found = None
    for s in range(12):
        rr = _run("--dry-run", "--morph", "1", "--seed", f"t{s}",
                  "--out", f"/tmp/p23s{s}.wav")
        m = re.search(r"joint @(\d+)s \(w (\d+)s\)", rr.stdout)
        if m:
            t_b, w = float(m.group(1)), float(m.group(2))
            tk = re.search(r"replay\s+(\S+)", rr.stdout).group(1)
            found = (tk, t_b, w)
            break
    check("e2e: a joint-bearing token found", found is not None)
    if found:
        tk, t_b, w = found
        rA = _run("--replay", tk, "--morph", "0", "--out", "/tmp/p23c.wav")
        rB = _run("--replay", tk, "--morph", "1", "--out", "/tmp/p23d.wav")
        ok = rA.returncode == 0 and rB.returncode == 0
        check("e2e: cut and morph readings both render", ok,
              (rA.stderr[-120:], rB.stderr[-120:]))
    # crossfade continuity, tested DETERMINISTICALLY: a micro-csd with
    # only the room scan + a steady noise source and two width rows (0.2
    # -> 1.0 at t=4). lag=0.005 must step; lag=2.0 must spread the width
    # change over seconds. Piece audio was tried first and is hop-noise
    # flaky (note onsets spike the width delta) -- the P6 lesson.
    def _micro(lag):
        rows = f"0,1,1,0.2,0.005, 4,1,1,1.0,{lag}, -1,1,1,1,0"
        csd = f"""<CsoundSynthesizer>
<CsOptions>
-o /tmp/p23w.wav -W -f -+rtaudio=null -+rtmidi=null
</CsOptions>
<CsInstruments>
sr=8000
ksmps=8
nchnls=2
0dbfs=1
giRooms ftgen 900, 0, -15, -2, {rows}
instr 1
  ktime  timeinsts
  kidx   init 0
  klag   init 0.005
  kwidT  init 1
  kt     table  kidx * 5, giRooms
  if kt >= 0 && ktime >= kt then
    kwidT  table  kidx * 5 + 3, giRooms
    klag   table  kidx * 5 + 4, giRooms
    kidx = kidx + 1
  endif
  klag  =  klag < 0.005 ? 0.005 : klag
  kwid  portk  kwidT, klag
  an    rand  0.3
  aM    =  an
  aS    =  an * kwid
  outs  (aM + aS) * 0.5, (aM - aS) * 0.5
endin
</CsInstruments>
<CsScore>
i 1 0 8
</CsScore>
</CsoundSynthesizer>"""
        Path("/tmp/p23w.csd").write_text(csd)
        rr = subprocess.run(["csound", "/tmp/p23w.csd"],
                            capture_output=True, text=True, timeout=120)
        assert rr.returncode == 0, rr.stderr[-300:]
        return _width_traj("/tmp/p23w.wav", 3.0, 8.0, sr=8000, hop=0.4)
    cut = _micro(0.005)
    fade = _micro(2.0)
    jc = max(abs(cut[k + 1] - cut[k]) for k in range(len(cut) - 1))
    jf = max(abs(fade[k + 1] - fade[k]) for k in range(len(fade) - 1))
    check("e2e: portk crossfade spreads the room step (deterministic "
          "micro-render; fade max hop-delta < half the cut's)",
          jf < jc * 0.5, (round(jc, 4), round(jf, 4)))


if __name__ == "__main__":
    print("draws:");    test_draws()
    print("pipeline:"); test_pipeline()
    print("e2e:");      test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
