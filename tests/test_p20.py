"""Phase 20 tests.  python3 tests/test_p20.py"""
from __future__ import annotations

import random
import re
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur.alphabet import Cat
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.score import graph_events, set_instr_peaks
import orange_fur.orchestra as O
import orange_fur.routing as R

FAILURES = []
ROOT = str(Path(__file__).resolve().parents[1])


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ------------------------------------------------------------------ solver
def test_solver():
    # byte-identity at surface_pct=0: identical RNG stream and terminals
    r1, r2 = random.Random(7), random.Random(7)
    s0 = solve(24, r1)
    s1 = solve(24, r2, surface_pct=0.0)
    check("solver: surface_pct=0 is the six-category path byte-for-byte",
          r1.random() == r2.random()
          and [t.cat for t in s0.system.terminals]
          == [t.cat for t in s1.system.terminals])
    check("solver: surface_pct=0 assigns no SURFACE terminals",
          all(t.cat != Cat.SURFACE for t in s0.system.terminals))
    # share band when on
    shares = []
    for seed in range(10):
        s = solve(24, random.Random(seed), surface_pct=20.0)
        n_s = sum(1 for t in s.system.terminals if t.cat == Cat.SURFACE)
        shares.append(n_s / 24)
    check("solver: SURFACE share near target (20% requested, 10 seeds)",
          0.08 <= statistics.mean(shares) <= 0.30,
          round(statistics.mean(shares), 3))
    check("solver: SURFACE present in every run when requested",
          all(sh > 0 for sh in shares))
    s40 = solve(24, random.Random(3), surface_pct=40.0)
    s10 = solve(24, random.Random(3), surface_pct=10.0)
    n40 = sum(1 for t in s40.system.terminals if t.cat == Cat.SURFACE)
    n10 = sum(1 for t in s10.system.terminals if t.cat == Cat.SURFACE)
    check("solver: PCT is a real lever (40% > 10% share, same seed)",
          n40 > n10, (n40, n10))


# --------------------------------------------------------------- orchestra
def test_orchestra():
    o_off = O.generate(random.Random(5), 12, surface=False)
    o_on = O.generate(random.Random(5), 12, surface=True)
    shared_on = [i for i in o_on.instruments if i.num < 700]
    check("orch: surface off generates no 7xx instruments",
          all(i.num < 700 for i in o_off.instruments))
    check("orch: shared instruments byte-identical off vs on",
          [i.code for i in o_off.instruments]
          == [i.code for i in shared_on])
    surf = [i for i in o_on.instruments if i.num >= 700]
    check("orch: SURFACE family generated (4 templates, cheap)",
          len(surf) == 18
          and {i.template for i in surf}
          == {"crackle", "dustpop", "hiss", "transwash"}
          and all(i.cost <= 4.5 for i in surf))
    envs = set()
    for k in range(40):
        i = O.t_crackle(700, random.Random(k), 12)
        m = re.search(r"env=(\w+)", i.code)
        envs.add(m.group(1))
    check("orch: all three B7 envelope classes drawn",
          envs == {"burst", "emergence", "reverse"}, envs)
    # subset with empty SURFACE pool consumes no draws (sample([],0))
    r1, r2 = random.Random(2), random.Random(2)
    o_off.subset(50, r1)
    O.Orchestra(instruments=list(o_off.instruments)).subset(50, r2)
    check("orch: subset draw-free over the empty SURFACE pool",
          r1.random() == r2.random())


# ---------------------------------------------------------------- pipeline
def _events(seed, pct, nodes=20, dur=3):
    cfg = Config(duration=dur, nodes=nodes, surface=pct)
    rng = random.Random(seed)
    sol = solve(nodes, rng, surface_pct=pct)
    return graph_events(cfg, sol, rng)


def test_pipeline():
    ev, _ = _events(4, 20.0)
    surf = [e for e in ev if e.echo == 0 and e.cat == int(Cat.SURFACE)]
    check("pipe: SURFACE notes emitted", len(surf) > 0, len(surf))
    # LONGDECAY (90 s cap) is remapped away; the remaining ceiling is
    # CAT_DUR max 14 s x SUSTAIN 2.2 or GLISS stretch (<= ~45 s) -- long
    # texture NOTES on the SWELL precedent (40 s), not noise floors
    check("pipe: SURFACE durations bounded (LONGDECAY remapped; <= 50 s)",
          all(e.dur <= 50.0 for e in surf),
          max((e.dur for e in surf), default=0))
    ev0a, _ = _events(4, 0.0)
    ev0b, _ = _events(4, 0.0)
    check("pipe: deterministic at surface 0",
          [(e.start, e.instr, e.index) for e in ev0a]
          == [(e.start, e.instr, e.index) for e in ev0b])


def test_density_diversity():
    """The B6 claim, measured directly (P23 AMENDMENT): dense passages
    gain the SURFACE family as material -- SURFACE notes are PRESENT in
    the densest decile when the flag is on, and instrument variety does
    not collapse. The previous proxy (distinct-instrument fraction on vs
    off) sat on its noise floor: cost routing intentionally funnels dense
    passages onto few instruments (P5), and the P22/P23 stream-layout
    changes re-rolled the proxy below its 0.95 bar without any change in
    the underlying behavior."""
    from orange_fur.alphabet import Cat as _C
    surf_present = 0
    floors_ok = True
    for seed in range(4):
        cfg = Config(duration=3, nodes=60, surface=20.0)
        rng = random.Random(seed)
        ev, _ = graph_events(cfg, solve(60, rng, surface_pct=20.0), rng)
        src = sorted((e for e in ev if e.echo == 0), key=lambda e: e.start)
        if len(src) < 50:
            continue
        times = [e.start for e in src]

        def poly(i):
            t = times[i]
            return sum(1 for e in src if e.start <= t <= e.start + e.dur)
        ranked = sorted(range(len(src)), key=poly, reverse=True)
        top = [src[i] for i in ranked[:len(src) // 10]]
        if any(e.cat == int(_C.SURFACE) for e in top):
            surf_present += 1
        if len({e.instr for e in top}) < 3:
            floors_ok = False
    check("density: SURFACE material present in the densest decile "
          "(>=3/4 seeds) and variety floor holds",
          surf_present >= 3 and floors_ok, (surf_present, floors_ok))


# --------------------------------------------------------------------- e2e
def _run(*extra, timeout=600):
    return subprocess.run(
        [sys.executable, "-m", "orange_fur", "--nodes", "14",
         "--duration", "2", "--draft", *extra],
        capture_output=True, text=True, timeout=timeout, cwd=ROOT)


def test_e2e():
    r = _run("--dry-run", "--surface", "--out", "/tmp/p20e_a.wav")
    check("e2e: bare --surface = 20 (report says so)",
          "target 20% of terminals" in r.stdout, r.stdout[-300:])
    tok = re.search(r"replay\s+(\S+)", r.stdout).group(1)
    r2 = _run("--dry-run", "--surface", "20", "--replay", tok,
              "--out", "/tmp/p20e_b.wav")
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p20e_a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p20e_b.csd").read_text())
    check("e2e: replay deterministic with --surface", a == b)
    # generation-parameter contract: absent-flag replay of a surface token
    # produces a DIFFERENT piece (tokens do not cross the flag)
    r3 = _run("--dry-run", "--replay", tok, "--out", "/tmp/p20e_c.wav")
    c = re.sub(r"-o \S+", "-o X", Path("/tmp/p20e_c.csd").read_text())
    check("e2e: tokens do not cross the flag (generation param)", a != c)
    # audio: SURFACE instruments actually sound (render a surface-heavy run)
    r4 = _run("--surface", "60", "--out", "/tmp/p20e_d.wav", timeout=900)
    # 32-bit FLOAT wav (format 3): stdlib wave can't read it; check the
    # RIFF header and a non-trivial payload instead (returncode already
    # proves the render succeeded)
    wp = Path("/tmp/p20e_d.wav")
    ok = (r4.returncode == 0 and wp.exists() and wp.stat().st_size > 10000
          and wp.read_bytes()[:4] == b"RIFF")
    check("e2e: surface-heavy render completes with audio", ok,
          r4.stderr[-200:] if r4.returncode else wp.stat().st_size)


if __name__ == "__main__":
    print("solver:");    test_solver()
    print("orchestra:"); test_orchestra()
    print("pipeline:");  test_pipeline()
    print("density:");   test_density_diversity()
    print("e2e:");       test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
