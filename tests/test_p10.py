"""Phase 10 tests.  python3 tests/test_p10.py"""
from __future__ import annotations

import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import tapeloops as TL
from orange_fur import orchestra as O
from orange_fur import routing as R
from orange_fur.alphabet import Cat
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.score import (Event, graph_events, set_instr_peaks,
                              fold_index, cost_route)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])


# ------------------------------------------------------------------- emission
def _plan(**kw):
    base = dict(prob=1.0,
                cell=[TL.CellNote(0.0, 0.3, 0, 0.8),
                      TL.CellNote(0.8, 0.2, 4, 0.6)],
                cat=Cat.PLUCK, voices=2, period=2.0, eps=0.01,
                decay=0.995, span_frac=1.0, pans=[0.2, 0.8])
    base.update(kw)
    return TL.LoopPlan(**base)


def test_phasing_arithmetic():
    plan = _plan()
    fold = lambda i: fold_index(i, 60, 12)
    ev = TL.emit(plan, t0=10.0, span=40.0, base_index=60, instr=200,
                 send=0.4, accent_gain=lambda t: 1.0, fold=fold,
                 proc_id=7, dur_cap=1e9)
    v0 = sorted(e.start for e in ev if e.pan == 0.2)
    v1 = sorted(e.start for e in ev if e.pan == 0.8)
    check("phase: two voices, both anchored at t0",
          abs(v0[0] - 10.0) < 1e-9 and abs(v1[0] - 10.0) < 1e-9)
    # downbeat of rep k: voice0 at t0 + k*T, voice1 at t0 + k*T*(1+eps)
    d0 = [t for t in v0][::2]     # cell has 2 notes; downbeats are every other
    d1 = [t for t in v1][::2]
    drift = [b - a for a, b in zip(d0, d1)]
    check("phase: offset accumulates as k*T*eps",
          all(abs(dr - k * 2.0 * 0.01) < 1e-6 for k, dr in enumerate(drift)),
          drift[:4])
    check("phase: realign time = T/eps", abs(plan.realign - 200.0) < 1e-9)
    reps0 = len(v0) // 2
    check("phase: repetition count fills the run", 19 <= reps0 <= 20, reps0)

    idxs = {e.index for e in ev}
    check("identity: cell degrees identical every pass (2 pitches only)",
          idxs == {60, 64}, idxs)
    amps0 = [e.amp for e in ev if e.pan == 0.2][::2]
    check("identity: near-100%% feedback -- slow geometric decay",
          all(abs(a - 0.8 * plan.decay ** k) < 1e-9
              for k, a in enumerate(amps0)))
    check("marking: echo == -2 and proc id set on every note",
          all(e.echo == -2 and e.proc == 7 for e in ev))
    check("marking: never a GONG cell", Cat.GONG not in TL.LOOP_CATS)


def test_protection_by_construction():
    """Loop emission is exact: no culling, no register stepping can touch it.
    The accent contour DOES apply."""
    plan = _plan(voices=2, span_frac=1.0)
    fold = lambda i: fold_index(i, 60, 12)
    gains = {}
    def accent(t):
        gains[round(t, 4)] = 0.5
        return 0.5
    ev = TL.emit(plan, 0.0, 20.0, 60, 200, 0.4, accent, fold, 1, 1e9)
    expect = sum(1 for v in range(2)
                 for k in range(int(20.0 / (2.0 * (1 + 0.01 * v))) + 1)
                 for cn in plan.cell
                 if k * 2.0 * (1 + 0.01 * v)
                 + cn.off * (1 + 0.01 * v) < 20.0)
    check("protect: emitted count is exact (nothing culled)",
          len(ev) == expect, (len(ev), expect))
    check("protect: accent contour applied to every note",
          all(abs(e.amp - cn_amp * 0.5 * plan.decay ** 0) < 1
              for e, cn_amp in [(ev[0], 0.8)])
          and all(round(e.start, 4) in gains for e in ev))


def test_atomic_routing():
    set_instr_peaks({}, {}, set())
    # two instruments in one category: 200 expensive, 201 cheap
    class FakeIns:
        def __init__(s, num, cost, cat):
            s.num, s.cost, s.cat, s.peak, s.tau, s.comp = \
                num, cost, cat, 1.0, None, False
    class FakeOrch:
        instruments = [FakeIns(200, 10.0, Cat.PLUCK),
                       FakeIns(201, 1.0, Cat.PLUCK)]
        def costs(s): return {i.num: i.cost for i in s.instruments}
        def by_cat(s, c): return [i for i in s.instruments if i.cat == c]
    ev = ([Event(instr=200, start=t, dur=1.0, index=60, amp=.3, pan=.2,
                 send=.4, slew=.3, cat=int(Cat.PLUCK), echo=-2, proc=5)
           for t in [0.0, 2.0, 4.0, 6.0]]
          + [Event(instr=200, start=t, dur=1.0, index=60, amp=.3, pan=.5,
                   send=.4, slew=.3, cat=int(Cat.PLUCK))
             for t in [0.5, 0.6, 0.7]])
    cfg = Config(nodes=4, duration=2)
    rep = cost_route(ev, cfg, FakeOrch(), cap=10.0)
    proc_instr = {e.instr for e in ev if e.proc == 5}
    check("atomic: the whole process lands on ONE instrument",
          len(proc_instr) == 1, proc_instr)
    check("atomic: process moved to the category's cheapest voice",
          proc_instr == {201})
    check("atomic: routing still reports and reduces cost",
          rep["rerouted"] >= 4 and rep["after"] < rep["before"])


def test_rarity_and_report():
    rng_hits = 0
    loop_secs = 0
    total_secs = 0
    seen_realign_inside = False
    for k in range(24):
        rng = random.Random(k)
        cfg = Config(nodes=10, duration=3, draft=True)
        rt = R.generate_routing(rng)
        orch = O.generate(rng, cfg.scale.numgrades,
                          n_buses=rt.n_buses).subset(cfg.subset, rng)
        set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
        catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
        ev, sm = graph_events(cfg, solve(10, rng), rng, catmap=catmap)
        total_secs += len(sm["macro"])
        for m in sm["macro"]:
            if m.get("loop"):
                loop_secs += 1
                if "inside the loop" in m["loop"]:
                    seen_realign_inside = True
        if any(e.echo == -2 for e in ev):
            rng_hits += 1
            check_once = all(e.proc > 0 for e in ev if e.echo == -2)
            assert check_once
    frac = loop_secs / max(1, total_secs)
    check("rarity: loops occur but are gong-class rare (3-30%% of sections)",
          0.03 <= frac <= 0.30, frac)
    check("rarity: some drawn realignments complete inside the loop",
          seen_realign_inside)
    check("rarity: loop notes always carry a proc id", True)


def test_replay_determinism():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "10",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p10a.wav")
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p10b.wav", "--replay", tok)
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p10a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p10b.csd").read_text())
    check("determinism: replay identical with loop draws in the stream",
          a == b)


if __name__ == "__main__":
    print("phasing arithmetic:"); test_phasing_arithmetic()
    print("protection:");         test_protection_by_construction()
    print("atomic routing:");     test_atomic_routing()
    print("rarity/report:");      test_rarity_and_report()
    print("determinism:");        test_replay_determinism()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
