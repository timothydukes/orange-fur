"""Phase 21 tests.  python3 tests/test_p21.py"""
from __future__ import annotations

import random
import re
import statistics
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.dynamics import DYNAMICS, apply_dynamics
from orange_fur.score import graph_events

FAILURES = []
ROOT = str(Path(__file__).resolve().parents[1])


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ------------------------------------------------------------------- unit
def test_mapping():
    class E:
        def __init__(self, amp, echo=0):
            self.amp, self.echo = amp, echo
    evs = [E(a) for a in (0.1, 0.2, 0.4, 0.8)] + [E(0.02, echo=1)]
    ref = [e.amp for e in evs]
    apply_dynamics(evs, DYNAMICS["default"])
    check("map: default is the identity", [e.amp for e in evs] == ref)
    apply_dynamics(evs, DYNAMICS["quiet"])
    check("map: quiet scales every amp down",
          all(a < b for a, b in zip([e.amp for e in evs], ref)))
    evs2 = [E(a) for a in (0.1, 0.2, 0.4, 0.8)]
    apply_dynamics(evs2, DYNAMICS["limited"])
    m = statistics.fmean((0.1, 0.2, 0.4, 0.8))
    spread0 = 0.8 - 0.1
    spread1 = evs2[3].amp - evs2[0].amp
    check("map: limited compresses range toward the piece mean",
          spread1 < spread0 * 0.35, (round(spread1, 3), spread0))
    check("map: monotone (never reorders amplitudes)",
          evs2[0].amp <= evs2[1].amp <= evs2[2].amp <= evs2[3].amp)
    evs3 = [E(1.9), E(0.001)]
    apply_dynamics(evs3, DYNAMICS["limited"])
    check("map: clamped to the drive rail [0.005, 2.0]",
          all(0.005 <= e.amp <= 2.0 for e in evs3))


# --------------------------------------------------------------- pipeline
def _events(seed, preset):
    cfg = Config(duration=3, nodes=20, dynamics=preset)
    rng = random.Random(seed)
    sol = solve(20, rng)
    ev, _ = graph_events(cfg, sol, rng)
    apply_dynamics(ev, DYNAMICS[preset])
    return ev


def test_pipeline():
    a = _events(5, "default")
    d2 = _events(5, "default")
    check("pipe: deterministic", [(e.start, e.amp) for e in a]
          == [(e.start, e.amp) for e in d2])
    # zero added draws: RNG state equality across presets
    r1, r2 = random.Random(3), random.Random(3)
    cfg1 = Config(duration=3, nodes=16, dynamics="default")
    cfg2 = Config(duration=3, nodes=16, dynamics="limited")
    graph_events(cfg1, solve(16, r1), r1)
    graph_events(cfg2, solve(16, r2), r2)
    check("pipe: presets add zero draws (RNG-state equality)",
          r1.random() == r2.random())
    lim = _events(5, "limited")
    qt = _events(5, "quiet")
    check("pipe: skeleton identical across presets (times/instruments)",
          [(round(e.start, 6), e.instr) for e in a]
          == [(round(e.start, 6), e.instr) for e in lim]
          == [(round(e.start, 6), e.instr) for e in qt])
    sa = [e.amp for e in a if e.echo == 0]
    sl = [e.amp for e in lim if e.echo == 0]
    sq = [e.amp for e in qt if e.echo == 0]
    check("pipe: variance ordering limited < mid-free default",
          statistics.pstdev(sl) < statistics.pstdev(sa) * 0.6,
          (round(statistics.pstdev(sl), 4), round(statistics.pstdev(sa), 4)))
    check("pipe: quiet mean level well below default",
          statistics.fmean(sq) < statistics.fmean(sa) * 0.6,
          (round(statistics.fmean(sq), 4), round(statistics.fmean(sa), 4)))
    # accent flattening: limited scales applied depth by 0.3 -- measured as
    # reduced spread of the accent-driven gain differences is already folded
    # into the variance check above; assert the mid ordering too
    md = _events(5, "mid")
    sm = [e.amp for e in md if e.echo == 0]
    check("pipe: mid sits between default and limited in variance",
          statistics.pstdev(sl) <= statistics.pstdev(sm)
          <= statistics.pstdev(sa) * 1.01,
          tuple(round(statistics.pstdev(x), 4) for x in (sl, sm, sa)))


# --------------------------------------------------------------------- e2e
def _peak_db(path):
    raw = Path(path).read_bytes()
    # 32-bit float WAV: find 'data' chunk, scan floats
    i = raw.find(b"data")
    body = raw[i + 8:]
    n = len(body) // 4
    import math
    pk = 0.0
    vals = struct.unpack(f"<{n}f", body[:n * 4])
    pk = max(abs(v) for v in vals) or 1e-9
    return 20 * math.log10(pk)


def _run(*extra, timeout=900):
    return subprocess.run(
        [sys.executable, "-m", "orange_fur", "--nodes", "12",
         "--duration", "2", "--draft", *extra],
        capture_output=True, text=True, timeout=timeout, cwd=ROOT)


def test_e2e():
    r = _run("--dry-run", "--out", "/tmp/p21a.wav")
    tok = re.search(r"replay\s+(\S+)", r.stdout).group(1)
    r2 = _run("--dry-run", "--replay", tok, "--dynamics", "default",
              "--out", "/tmp/p21b.wav")
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p21a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p21b.csd").read_text())
    check("e2e: --dynamics default csd-identical to flag absent", a == b)
    # rendered normalization targets honored
    r3 = _run("--replay", tok, "--dynamics", "quiet", "--out", "/tmp/p21q.wav")
    r4 = _run("--replay", tok, "--dynamics", "limited", "--out",
              "/tmp/p21l.wav")
    ok3 = r3.returncode == 0 and Path("/tmp/p21q.wav").exists()
    ok4 = r4.returncode == 0 and Path("/tmp/p21l.wav").exists()
    check("e2e: quiet and limited renders complete", ok3 and ok4,
          (r3.stderr[-120:], r4.stderr[-120:]))
    if ok3 and ok4:
        pq, pl = _peak_db("/tmp/p21q.wav"), _peak_db("/tmp/p21l.wav")
        check("e2e: normalization targets honored (quiet ~-12, "
              "limited ~-1 dBFS)",
              abs(pq - (-12.0)) < 0.5 and abs(pl - (-1.0)) < 0.5,
              (round(pq, 2), round(pl, 2)))
    # explicit --normalize overrides the preset
    r5 = _run("--replay", tok, "--dynamics", "quiet", "--normalize", "-6",
              "--out", "/tmp/p21n.wav")
    if r5.returncode == 0:
        pn = _peak_db("/tmp/p21n.wav")
        check("e2e: explicit --normalize overrides the preset target",
              abs(pn - (-6.0)) < 0.5, round(pn, 2))
    else:
        check("e2e: explicit --normalize overrides the preset target",
              False, r5.stderr[-120:])


if __name__ == "__main__":
    print("mapping:");  test_mapping()
    print("pipeline:"); test_pipeline()
    print("e2e:");      test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
