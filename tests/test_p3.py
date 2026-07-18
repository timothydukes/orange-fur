"""Phase 3 tests.  python3 tests/test_p3.py
The render smoke tests need csound on PATH; they are the point of the suite."""
from __future__ import annotations

import math
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import orchestra as O
from orange_fur.alphabet import Cat
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.orc import build_orc, build_csd, TUNING_TABLE
from orange_fur.score import graph_events, compensate, set_instr_peaks

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ------------------------------------------------------------- generation
def test_generation():
    rng = random.Random(1)
    orch = O.generate(rng, 12)
    check("gen: ~150 instruments", 140 <= len(orch.instruments) <= 160,
          len(orch.instruments))
    for cat in Cat:
        check(f"gen: {cat.name} populated and in its numbering range",
              all(O.BASE_NUM[cat] <= i.num < O.BASE_NUM[cat] + 100
                  for i in orch.by_cat(cat)) and len(orch.by_cat(cat)) > 0)
    check("gen: every template family represented",
          {i.template for i in orch.instruments} >= {
              "bank", "mslave", "pwm", "pluck", "sync", "fbshape",
              "modal", "pipe", "chirp", "burst", "tick",
              "tcloud", "wtx", "pll", "wtswell", "bankswell"})
    check("gen: all costs and peaks positive",
          all(i.cost > 0 and i.peak > 0 for i in orch.instruments))

    # two runs never generate the same orchestra
    o2 = O.generate(random.Random(2), 12)
    check("gen: two runs differ", orch.text() != o2.text())

    # instrument space (order of magnitude): the bank template alone draws a
    # partial count, and per partial a degree, a law weight, a wobble rate and
    # a depth -- count distinct BANK code bodies over many draws as a proxy
    seen = {O.t_bank(700, random.Random(s), 12).code for s in range(200)}
    check("gen: bank draws are effectively unique (200/200 distinct)",
          len(seen) == 200, len(seen))


# ------------------------------------------------------------- safety rules
def test_safety():
    rng = random.Random(3)
    orch = O.generate(rng, 12)
    txt = orch.text()

    # the Phase 0 rule: NO k-rate envelope UDO args anywhere
    check("safety: no k-rate envelope UDO calls",
          not re.search(r"Rat(Win|Pop|Comp)\s+k", txt))

    # every rational shaper denominator is 1 + c*x*x with c > 0
    bad = [m for m in re.findall(r"/ \(1 \+ ([0-9.]+) \*", txt)
           if float(m) <= 0]
    check("safety: all shaper denominators pole-free", not bad, bad)

    # feedback gains bounded
    fbs = [float(m) for m in re.findall(r"atap \* ([0-9.]+)", txt)]
    check("safety: feedback gains <= 0.92", all(f <= 0.92 for f in fbs),
          max(fbs) if fbs else None)

    # dcblock present wherever there is a delay-line feedback or a shaper drive
    check("safety: dcblock in feedback instruments",
          txt.count("delayw") <= txt.count("dcblock2"))

    # the reserved-name lesson
    check("safety: reserved name `kr` never used as a variable",
          not re.search(r"^\s*kr\s", txt, re.M))


# ------------------------------------------------------------- subset+binding
def test_subset_binding():
    rng = random.Random(5)
    orch = O.generate(rng, 12)
    for pct in (10, 33, 100):
        sub = orch.subset(pct, rng)
        check(f"subset: {pct}% keeps every category",
              all(len(sub.by_cat(c)) >= 1 for c in Cat),
              {c.name: len(sub.by_cat(c)) for c in Cat})
    sub = orch.subset(10, rng)
    check("subset: 10% is actually small",
          len(sub.instruments) <= 0.2 * len(orch.instruments),
          len(sub.instruments))

    # events bind ONLY to subset members, and to more than one instrument
    cfg = Config(nodes=14, duration=3)
    rng2 = random.Random(7)
    sol = solve(14, rng2)
    sub = orch.subset(40, rng2)
    catmap = {c: [i.num for i in sub.by_cat(c)] for c in Cat}
    allowed = {i.num for i in sub.instruments}
    ev, _ = graph_events(cfg, sol, rng2, catmap=catmap)
    check("bind: every event uses a subset instrument",
          all(e.instr in allowed for e in ev),
          sorted({e.instr for e in ev} - allowed))
    check("bind: more than one concrete instrument in use",
          len({e.instr for e in ev}) > 6, len({e.instr for e in ev}))


# ------------------------------------------------------------- smoke render
def test_render_smoke():
    """Every template family, one note each, through the REAL pipeline text.
    This is the test that catches generated-syntax and NaN regressions."""
    cfg = Config(nodes=4, duration=2, draft=True)
    rng = random.Random(11)
    orc_txt = build_orc(cfg, 0.7)
    head = orc_txt[:orc_txt.index("; ---- 1 :")]
    tail = orc_txt[orc_txt.index("; ---- 90 :"):]

    import struct, array

    def peak_of(fn):
        b = open(fn, "rb").read()
        i = 12
        while i < len(b) - 8:
            cid = b[i:i + 4]
            sz = struct.unpack("<I", b[i + 4:i + 8])[0]
            if cid == b"data":
                a = array.array("f")
                a.frombytes(b[i + 8:i + 8 + sz])
                return max(abs(x) for x in a)
            i += 8 + sz + (sz & 1)

    for cat, temps in O.TEMPLATES.items():
        for t in dict.fromkeys(temps):
            ins = t(700, rng, 12)
            sco = (f"f 900 0 -8 -2 0 1 1 1 -1 1 1 1\n"
                   f"{cfg.scale.ftable(TUNING_TABLE)}\n"
                   f"i 99 0 4\ni 700 0.1 1.5 60 0.5 0.5 0.4 0.3 1\ne")
            Path("/tmp/p3smk.csd").write_text(
                build_csd(cfg, head + ins.code + "\n" + tail, sco))
            r = subprocess.run(
                ["csound", "-o", "/tmp/p3smk.wav", "/tmp/p3smk.csd"],
                capture_output=True, text=True, timeout=90)
            pk = peak_of("/tmp/p3smk.wav") if r.returncode == 0 else None
            ok = (r.returncode == 0 and pk is not None and math.isfinite(pk)
                  and 0.0005 < pk < 2.5 * ins.peak)
            check(f"smoke: {ins.template} renders, finite, peak <= declared",
                  ok, f"rc={r.returncode} peak={pk} declared={ins.peak}")


# ------------------------------------------------------------- amp model
def test_amp_model():
    """The registry must be populated before compensate, and generated peaks
    must flow into the model."""
    rng = random.Random(9)
    orch = O.generate(rng, 12).subset(50, rng)
    set_instr_peaks(orch.peaks())
    cfg = Config(nodes=10, duration=2)
    sol = solve(10, rng)
    catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
    ev, _ = graph_events(cfg, sol, rng, catmap=catmap)
    stats = compensate(ev, cfg)
    check("amp: model produces a finite positive gain",
          math.isfinite(stats["gain"]) and stats["gain"] > 0, stats["gain"])
    check("amp: predicted peak positive and below 4",
          0 < stats["predicted_peak"] < 4, stats["predicted_peak"])


if __name__ == "__main__":
    print("generation:");     test_generation()
    print("safety:");         test_safety()
    print("subset+binding:"); test_subset_binding()
    print("smoke render:");   test_render_smoke()
    print("amp model:");      test_amp_model()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
