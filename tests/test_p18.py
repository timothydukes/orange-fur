"""Phase 18 tests.  python3 tests/test_p18.py"""
from __future__ import annotations

import math
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import echocfg
from orange_fur import varispeed as VS
from orange_fur.alphabet import Cat
from orange_fur.guilib import spec_to_toml
from orange_fur.score import Event

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])
VON = dict(enabled=True, prob=1.0, depth=[300.0, 300.0], segments=[3, 6])


def _plan(segs):
    return VS.VsPlan(active=True, depth_cents=300.0, segments=segs)


def _ev(start, dur=1.0, echo=1):
    return Event(instr=200, start=start, dur=dur, index=60, amp=.3, pan=.5,
                 send=.4, slew=.3, cat=int(Cat.PLUCK), echo=echo)


# ---------------------------------------------------------------- physics
def test_physics():
    p = _plan([VS.Segment(0, 10, "hold", 2.0, 2.0)])
    check("physics: constant s=2 halves time and adds +1200c",
          abs(p.warp_time(8.0) - 4.0) < 1e-6
          and abs(p.cents_at(3.0) - 1200.0) < 1e-9)
    p = _plan([VS.Segment(0, 10, "hold", 0.5, 0.5)])
    check("physics: s=1/2 doubles time, -1200c",
          abs(p.warp_time(4.0) - 8.0) < 1e-6
          and abs(p.cents_at(1.0) + 1200.0) < 1e-9)
    p = _plan([VS.Segment(0, 4, "hold", 1.0, 1.0),
               VS.Segment(4, 8, "jump", 2.0, 2.0)])
    check("physics: jump integrates piecewise (4 + 2/2 = 5 at t=6)",
          abs(p.warp_time(6.0) - 5.0) < 1e-3, p.warp_time(6.0))
    p = _plan([VS.Segment(0, 8, "sweep", 1.0, 2.0)])
    mid = p.speed_at(4.0)
    check("physics: sweep is log-linear (midpoint = sqrt(2))",
          abs(mid - math.sqrt(2)) < 1e-9, mid)


def test_warp_events():
    p = _plan([VS.Segment(0, 20, "hold", 2.0, 2.0)])
    e = _ev(105.0, dur=2.0)
    VS.warp_events([e], p, t0=100.0, dur_total=600.0)
    check("warp: start remaps through the integrator, dur scales, "
          "pitch +1200c",
          abs(e.start - 102.5) < 1e-6 and abs(e.dur - 1.0) < 1e-6
          and abs(e.det - 1200.0) < 1e-9 and e.detg == 0.0)
    p = _plan([VS.Segment(0, 10, "sweep", 1.0, 2.0)])
    e = _ev(100.0, dur=10.0)
    VS.warp_events([e], p, t0=100.0, dur_total=600.0)
    check("warp: a note riding a sweep carries the speed change on p13",
          abs(e.det - 0.0) < 1e-6 and abs(e.detg - 1200.0) < 1.0,
          (e.det, e.detg))
    p = _plan([VS.Segment(0, 5, "hold", 1.0, 1.0),
               VS.Segment(5, 10, "jump", 2.0, 2.0)])
    e = _ev(103.0, dur=4.0)          # spans the jump at tau=5
    VS.warp_events([e], p, t0=100.0, dur_total=600.0)
    check("warp: silent-jump -- a note spanning a jump keeps its own "
          "trajectory (no detg ride)",
          e.detg == 0.0 and abs(e.det - 0.0) < 1e-9)
    p = VS.VsPlan(active=False, depth_cents=0, segments=[])
    e = _ev(105.0)
    st, du, de = e.start, e.dur, e.det
    VS.warp_events([e], p, 100.0, 600.0)
    check("warp: inactive plan is a no-op",
          (e.start, e.dur, e.det) == (st, du, de))


def test_draw_discipline():
    on = dict(VON)
    off = dict(enabled=False, prob=0.4, depth=[100.0, 500.0],
               segments=[3, 6])
    for seed in (1, 9, 33):
        r1, r2 = random.Random(seed), random.Random(seed)
        VS.draw_plan(r1, 60.0, off)
        VS.draw_plan(r2, 60.0, on)
        if r1.random() != r2.random():
            check("draws: identical layout across configs", False, seed)
            return
    check("draws: identical layout across configs", True)
    check("draws: disabled config never activates",
          not any(VS.draw_plan(random.Random(k), 60.0, off).active
                  for k in range(50)))
    plans = [VS.draw_plan(random.Random(k), 60.0, VON) for k in range(50)]
    check("draws: enabled prob=1 always activates; depth honored",
          all(p.active and abs(p.depth_cents - 300.0) < 1e-9
              for p in plans))
    # symmetric log targets: mean log-speed over many segments ~ 0
    logs = [math.log(s.s1) for p in plans for s in p.segments]
    check("draws: speed targets symmetric in log (no systematic drift)",
          abs(sum(logs) / len(logs)) < 0.08, sum(logs) / len(logs))


def test_config_and_spec():
    c = echocfg.load(None)
    check("cfg: varispeed default disabled",
          c.varispeed["enabled"] is False)
    Path("/tmp/p18.toml").write_text(
        "schema = 1\n[echo.varispeed]\nenabled = true\nprob = 0.9\n"
        "depth = [200.0, 400.0]\nsegments = [3, 5]\n")
    c2 = echocfg.load("/tmp/p18.toml")
    check("cfg: [echo.varispeed] loads (additive to schema 1)",
          c2.varispeed["enabled"] is True and c2.varispeed["prob"] == 0.9)
    Path("/tmp/p18bad.toml").write_text(
        "schema = 1\n[echo.varispeed]\nenbaled = true\n")
    try:
        echocfg.load("/tmp/p18bad.toml")
        check("cfg: varispeed typos rejected", False)
    except SystemExit:
        check("cfg: varispeed typos rejected", True)
    check("cfg: GUI writer includes the varispeed table",
          "[echo.varispeed]" in spec_to_toml(echocfg.EchoConfig()))
    old = echocfg.load(str(Path(ROOT) / "examples" / "echo-spec.toml"))
    check("cfg: pre-P18 spec files still valid",
          old.varispeed["enabled"] is False)


def test_e2e():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "10",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    spec = "/tmp/p18e.toml"
    Path(spec).write_text("schema = 1\n[echo.varispeed]\nenabled = true\n"
                          "prob = 1.0\n")
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p18a.wav", "--echo-spec", spec)
    check("e2e: varispeed report line printed", "varispeed" in r1.stdout)
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p18b.wav", "--echo-spec", spec, "--replay", tok)
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p18a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p18b.csd").read_text())
    check("e2e: deterministic under replay", a == b)
    # token shared with a varispeed-off run: SOURCE identical (echo 0 strips
    # all tape-domain material under both)
    run("--out", "/tmp/p18c.wav", "--replay", tok, "--echo", "0")
    run("--out", "/tmp/p18d.wav", "--replay", tok, "--echo", "0",
        "--echo-spec", spec)
    c = re.sub(r"-o \S+", "-o X", Path("/tmp/p18c.csd").read_text())
    d = re.sub(r"-o \S+", "-o X", Path("/tmp/p18d.csd").read_text())
    check("e2e: token shared across varispeed on/off (source invariant)",
          c == d)


if __name__ == "__main__":
    print("physics:");     test_physics()
    print("warp:");        test_warp_events()
    print("draws:");       test_draw_discipline()
    print("config/spec:"); test_config_and_spec()
    print("e2e:");         test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
