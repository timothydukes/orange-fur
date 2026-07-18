"""Phase 6 tests.  python3 tests/test_p6.py   (renders; needs csound + numpy)"""
from __future__ import annotations

import random
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import macro as M
from orange_fur import orchestra as O
from orange_fur import routing as R
from orange_fur.alphabet import Cat
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.decimate import decimate_by_2, _write_wav_f32, _read_wav_f32
from orange_fur.score import (graph_events, set_instr_peaks, fold_index)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ---------------------------------------------------------- register bound
def test_register_bound():
    worst = 0
    for k in range(300):
        plan = M.draw_plan(random.Random(k), 0.0, 900.0)   # 15-min section
        for t in range(0, 900, 5):
            worst = max(worst, abs(plan.register_offset(t)))
    check("register: bounded over 15-minute sections (was 910 unbounded)",
          worst <= 17, worst)

    # still a staircase, not a constant
    plan = M.draw_plan(random.Random(3), 0.0, 300.0)
    vals = {plan.register_offset(t) for t in range(0, 300, 2)}
    check("register: still steps (not flattened by the bound)", len(vals) > 2,
          vals)


def test_fold_index():
    bk, g = 60, 12
    span = 3 * g
    for raw in range(-800, 800, 7):
        f = fold_index(bk + raw, bk, g)
        assert abs(f - bk) <= span, (raw, f)
    check("fold: every index lands within basekey +/- 3 intervals", True)
    # identity inside the window
    check("fold: identity inside the window",
          all(fold_index(bk + d, bk, g) == bk + d
              for d in range(-span, span + 1)))
    # reflection is continuous at the boundary (no jump)
    seq = [fold_index(bk + d, bk, g) for d in range(span - 3, span + 6)]
    steps = {abs(a - b) for a, b in zip(seq, seq[1:])}
    check("fold: continuous at the boundary (reflects, no wrap jump)",
          max(steps) <= 1, seq)


# ---------------------------------------------------------- auto sections
def test_auto_sections():
    import re
    counts = {}
    for mins, lo, hi in ((2, 3, 5), (10, 4, 14), (45, 18, 32)):
        seen = set()
        for k in range(12):
            rng = random.Random(k)
            cfg = Config(nodes=8, duration=mins, draft=True)   # sections=0 auto
            rt = R.generate_routing(rng)
            orch = O.generate(rng, cfg.scale.numgrades,
                              n_buses=rt.n_buses).subset(40, rng)
            set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
            catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
            ev, sm = graph_events(cfg, solve(8, rng), rng, catmap=catmap)
            seen.add(len(sm["seq"]))
        counts[mins] = seen
        check(f"sections: auto count for {mins} min within [{lo},{hi}]",
              all(lo <= n <= hi for n in seen), seen)
    check("sections: longer pieces draw more sections",
          max(counts[2]) <= min(counts[45]), counts)


# ------------------------------------------------------------- decimator
def test_decimator():
    sr = 96000
    t = np.arange(sr * 2) / sr
    x = 0.5 * np.sin(2 * np.pi * 1000 * t) + 0.25 * np.sin(2 * np.pi * 30000 * t)
    _write_wav_f32(Path("/tmp/p6_96.wav"), np.stack([x, x], 1), sr)
    rep = decimate_by_2(Path("/tmp/p6_96.wav"), Path("/tmp/p6_48.wav"))
    y, sr2, _ = _read_wav_f32(Path("/tmp/p6_48.wav"))
    check("decimate: output is 48 kHz, half the frames",
          sr2 == 48000 and abs(rep["out_frames"] - rep["in_frames"] // 2) <= 1)
    Y = np.abs(np.fft.rfft(y[:, 0] * np.hanning(len(y))))
    f = np.fft.rfftfreq(len(y), 1 / sr2)

    def db(freq):
        sel = (f > freq - 60) & (f < freq + 60)
        return 20 * np.log10(Y[sel].max() + 1e-12)

    ref = db(1000)
    check("decimate: 1 kHz passband intact, 30 kHz alias (folds to 18 kHz) "
          ">100 dB down", db(18000) - ref < -100.0,
          f"{db(18000) - ref:.1f} dB")


# ------------------------------------------------------ release e2e + manifest
def test_release_e2e():
    out = Path("/tmp/p6_rel.wav")
    res = subprocess.run(
        [sys.executable, "-m", "orange_fur", "--nodes", "6", "--duration", "2",
         "--subset", "25", "--out", str(out)],
        capture_output=True, text=True, timeout=900,
        cwd=str(Path(__file__).resolve().parents[1]))
    ok = res.returncode == 0 and "decimate" in res.stdout
    check("release: full-quality render decimates and completes", ok,
          res.stdout[-300:] + res.stderr[-200:])
    if ok:
        b = out.read_bytes()[:64]
        fmt = struct.unpack("<HHIIHH", b[20:36])
        check("release: deliverable is 48 kHz 32-bit float stereo",
              fmt == (3, 2, 48000, 48000 * 8, 8, 32), fmt)
        man = out.with_suffix(".txt")
        check("release: manifest written beside the wav",
              man.exists() and "fx bus" in man.read_text()
              and "gestures" in man.read_text())


# --------------------------------------------------------------- long form
def test_long_form_structure():
    rng = random.Random(5)
    cfg = Config(nodes=40, duration=40, draft=True)
    rt = R.generate_routing(rng)
    orch = O.generate(rng, cfg.scale.numgrades,
                      n_buses=rt.n_buses).subset(40, rng)
    set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
    catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
    ev, sm = graph_events(cfg, solve(40, rng), rng, catmap=catmap)
    check("long: 40-minute piece generates", len(ev) > 500, len(ev))
    check("long: many sections", len(sm["seq"]) >= 16, len(sm["seq"]))
    span = 3 * cfg.scale.numgrades
    check("long: every index inside the fold window",
          all(abs(e.index - cfg.scale.basekey) <= span for e in ev))
    check("long: durations within the Phase 2 contract",
          all(0.01 <= e.dur <= 100 for e in ev),
          max(e.dur for e in ev))
    ends = max(e.start + e.dur for e in ev)
    check("long: everything ends before the bus closes",
          ends <= cfg.dur_sec + 12 + 1e-6, ends)


if __name__ == "__main__":
    print("register bound:"); test_register_bound()
    print("index fold:");     test_fold_index()
    print("auto sections:");  test_auto_sections()
    print("decimator:");      test_decimator()
    print("long form:");      test_long_form_structure()
    print("release e2e:");    test_release_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
