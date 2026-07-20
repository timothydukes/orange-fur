"""Phase 9 tests.  python3 tests/test_p9.py"""
from __future__ import annotations

import random
import re
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import echoes as E
from orange_fur import orchestra as O
from orange_fur import routing as R
from orange_fur.alphabet import Cat
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.orc import build_orc, build_csd, TUNING_TABLE
from orange_fur.score import (Event, graph_events, set_instr_peaks,
                              fold_index)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])


# ------------------------------------------------------------------ engine
def _ev(start=0.0, index=60, det=0.0, amp=0.4, dur=1.0):
    return Event(instr=100, start=start, dur=dur, index=index, amp=amp,
                 pan=.5, send=.4, slew=.3, cat=int(Cat.PARTIAL), det=det)


def test_engine():
    fold = lambda i: fold_index(i, 60, 12)

    plan = E.EchoPlan(prob=1.0, delay=0.25, fb=0.5, mode="plain", step=0)
    train = E.echo_pattern([_ev(), _ev(start=0.1, index=62)], plan, fold)
    reps = E.n_repeats(plan)
    check("engine: plain train, every source note echoed each generation",
          len(train) == 2 * reps and reps >= 3, (len(train), reps))
    check("engine: delays uniform multiples of d",
          all(abs(t.start - (s + plan.delay * t.echo)) < 1e-9
              for t, s in zip(train, [0.0, 0.1] * reps)))
    check("engine: amplitude decays geometrically",
          all(abs(t.amp - 0.4 * plan.fb ** t.echo) < 1e-12 for t in train))
    check("engine: train ends above the amplitude floor",
          0.5 ** reps >= E.AMP_FLOOR > 0.5 ** (reps + 1))

    plan = E.EchoPlan(prob=1.0, delay=0.3, fb=0.6, mode="degrees", step=3)
    train = E.echo_pattern([_ev()], plan, fold)
    check("engine: degree cascade steps and stays folded",
          [t.index for t in train][:3] == [63, 66, 69]
          and all(abs(t.index - 60) <= 36 for t in train))

    plan = E.EchoPlan(prob=1.0, delay=0.3, fb=0.7, mode="octave", step=12)
    train = E.echo_pattern([_ev()], plan, fold)
    check("engine: octave spiral folds at the boundary",
          all(abs(t.index - 60) <= 36 for t in train)
          and len({t.index for t in train}) > 1,
          [t.index for t in train])

    plan = E.EchoPlan(prob=1.0, delay=0.3, fb=0.7, mode="cents", step=20.0)
    train = E.echo_pattern([_ev()], plan, fold)
    check("engine: cents mode accumulates detune, capped",
          [round(t.det, 1) for t in train][:3] == [20.0, 40.0, 60.0]
          and all(abs(t.det) <= E.CENTS_CAP for t in train))
    check("engine: pitch index untouched in cents mode",
          all(t.index == 60 for t in train))


# ------------------------------------------------- source-invariance / remix
def _gen(echo, seed=777):
    rng = random.Random(seed)
    cfg = Config(nodes=12, duration=3, draft=True, echo=echo)
    rt = R.generate_routing(rng)
    orch = O.generate(rng, cfg.scale.numgrades,
                      n_buses=rt.n_buses).subset(cfg.subset, rng)
    set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
    catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
    ev, sm = graph_events(cfg, solve(12, rng), rng, catmap=catmap)
    return ev, sm


def test_source_invariance():
    def key(e):
        return (e.instr, round(e.start, 6), round(e.dur, 6), e.index,
                round(e.amp, 9), round(e.det, 4))
    seen = []
    counts = []
    for x in (0.0, 1.0, 2.0):
        ev, _ = _gen(x)
        seen.append({key(e) for e in ev if e.echo == 0})
        counts.append((sum(1 for e in ev if e.echo == 0),
                       sum(1 for e in ev if e.echo > 0)))
    check("remix: source composition identical at --echo 0 / 1 / 2",
          seen[0] == seen[1] == seen[2], [len(s) for s in seen])
    check("remix: --echo 0 emits no echo notes, higher scales emit more",
          counts[0][1] == 0 and counts[1][1] > 0
          and counts[2][1] >= counts[1][1], counts)
    ev1, _ = _gen(1.0)
    # Phase 11 amendment: rotating sections cycle the echo INSTRUMENT within
    # the source's category, so the contract is category-level -- an echo
    # never leaves its source's category, but need not keep its instrument.
    check("remix: echo notes stay in the source's category (contract intact)",
          all(any(s.cat == e.cat for s in ev1 if s.echo == 0)
              for e in ev1 if e.echo > 0))


# --------------------------------------------------------------- p12 in audio
def _read(fn):
    b = open(fn, "rb").read()
    i = 12
    while i < len(b) - 8:
        cid = b[i:i + 4]
        sz = struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"data":
            from array import array
            a = array("f")
            a.frombytes(b[i + 8:i + 8 + sz])
            return np.array(a, dtype=float)
        i += 8 + sz + (sz & 1)


def test_p12_in_audio():
    """+100 cents must move the rendered pitch by exactly 2^(100/1200) --
    including the BAKED-PARTIAL templates, whose whole spectrum must ride
    the detune via kgl."""
    cfg = Config(nodes=4, duration=2, draft=True)
    rt = R.Routing(n_buses=1,
                   chains=[R.Chain(bus=1, units=[R.u_phaser(random.Random(0))],
                                   ret=0.02)], room_chain=0, pool_size=1)
    sr = 48000
    for name, tf in (("pwm", O.t_pwm), ("bank", O.t_bank)):
        ins = tf(700, random.Random(3), 12)
        code = (ins.code.replace("gaSendL", "gaSend1L")
                        .replace("gaSendR", "gaSend1R"))
        orc = build_orc(cfg, 0.7, code, routing=rt)
        hz = {}
        for det in (0, 100):
            sco = (f"f 900 0 -8 -2 0 1 1 1 -1 1 1 1\n"
                   f"{cfg.scale.ftable(TUNING_TABLE)}\n"
                   f"i 99 0 4\ni 700 0.05 2.5 60 0.6 0.5 0.0 0.4 0 0 0 {det}\ne")
            Path("/tmp/p9d.csd").write_text(build_csd(cfg, orc, sco))
            r = subprocess.run(["csound", "-o", "/tmp/p9d.wav", "/tmp/p9d.csd"],
                               capture_output=True, timeout=90)
            if r.returncode:
                hz[det] = None
                continue
            w = _read("/tmp/p9d.wav")[0::2]
            seg = w[int(0.4 * sr):int(2.3 * sr)]
            m = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=1 << 19))
            f = np.fft.rfftfreq(1 << 19, 1 / sr)
            sel = (f > 200) & (f < 340)
            hz[det] = float(f[sel][int(np.argmax(m[sel]))])
        ok = (hz[0] and hz[100]
              and abs(hz[100] / hz[0] - 2 ** (100 / 1200)) < 0.002)
        check(f"p12: {name} +100 cents = ratio 1.0595 in rendered audio",
              ok, hz)


# ----------------------------------------------------------------------- e2e
def test_e2e():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "12",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p9a.wav")
    tok = tok_re.search(r1.stdout).group(1)
    check("e2e: echo report printed", "echoes" in r1.stdout)
    r2 = run("--out", "/tmp/p9b.wav", "--replay", tok)
    check("e2e: replay determinism holds with echoes in the stream",
          re.sub(r"-o \S+", "-o X", Path("/tmp/p9a.csd").read_text())
          == re.sub(r"-o \S+", "-o X", Path("/tmp/p9b.csd").read_text()))
    r3 = run("--out", "/tmp/p9c.wav", "--replay", tok, "--echo", "0")
    check("e2e: --echo 0 run reports no echo notes",
          "echo notes" not in r3.stdout)
    n_lines = lambda fn: sum(1 for l in Path(fn).read_text().splitlines()
                             if re.match(r"i (?!90 |99 )\d+ ", l))
    check("e2e: --echo 0 score is smaller",
          n_lines("/tmp/p9c.csd") < n_lines("/tmp/p9a.csd"),
          (n_lines("/tmp/p9c.csd"), n_lines("/tmp/p9a.csd")))
    check("e2e: score lines carry 12 p-fields",
          all(len(l.split()) == 13 for l in Path("/tmp/p9a.csd").read_text()
              .splitlines() if re.match(r"i (?!90 |99 )\d+ ", l)))


if __name__ == "__main__":
    print("engine:");            test_engine()
    print("source invariance:"); test_source_invariance()
    print("p12 in audio:");      test_p12_in_audio()
    print("e2e:");               test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
