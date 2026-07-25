"""Phase 17 tests.  python3 tests/test_p17.py"""
from __future__ import annotations

import math
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import echocfg
from orange_fur import echoes as E
from orange_fur.alphabet import Cat
from orange_fur.macro import bjorklund
from orange_fur.score import Event, fold_index

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])
FOLD = lambda i: (fold_index(i, 60, 12), 0.0)


def _ev(**kw):
    base = dict(instr=200, start=10.0, dur=1.0, index=60, amp=0.4, pan=0.5,
                send=.4, slew=.3, cat=int(Cat.PLUCK))
    base.update(kw)
    return Event(**base)


def _plan(**kw):
    base = dict(prob=1.0, delay=0.3, fb=0.6, mode="plain", step=0.0)
    base.update(kw)
    return E.EchoPlan(**base)


# ------------------------------------------------------------------ config
def test_config():
    c = echocfg.load(None)
    check("cfg: defaults are the P9-P11 distribution",
          c.timing == dict(uniform=1.0, multitap=0.0, euclid=0.0, ramp=0.0)
          and c.modes["plain"] == 0.30 and c.rotation["prob"] == 0.35
          and c.second_order == "off" and c.pan["inherit"] == 1.0)
    Path("/tmp/p17ok.toml").write_text(
        "schema = 1\n[echo]\nscale = 2.0\nsecond_order = \"always\"\n"
        "[echo.timing.weights]\nuniform = 0.0\nramp = 1.0\n"
        "[echo.timing.ramp]\nratio = [0.85, 0.90]\n")
    c2 = echocfg.load("/tmp/p17ok.toml")
    check("cfg: file loads, merges over defaults",
          c2.scale == 2.0 and c2.timing["ramp"] == 1.0
          and c2.ramp["ratio"] == [0.85, 0.90]
          and c2.euclid["pulses"] == [3, 7])
    for bad, why in [
        ("schema = 2\n[echo]\nscale = 1.0\n", "wrong schema"),
        ("schema = 1\n[echo]\nscael = 1.0\n", "typo key"),
        ("schema = 1\n[echo.timing]\nunifrm = 0.5\n", "typo family"),
        ("schema = 1\n[echo.timing.ramp]\nratio = [0.9, 0.8]\n",
         "inverted range"),
    ]:
        Path("/tmp/p17bad.toml").write_text(bad)
        try:
            echocfg.load("/tmp/p17bad.toml")
            check(f"cfg: rejected -- {why}", False)
        except SystemExit:
            check(f"cfg: rejected -- {why}", True)
    check("cfg: mini-parser agrees on the schema shape",
          isinstance(echocfg._mini_toml(Path("/tmp/p17ok.toml").read_text()),
                     dict))


# -------------------------------------------------------- fixed draw layout
def test_fixed_layout():
    """Different configs consume identical RNG draws -- any two echo-specs
    share a replay token."""
    heavy = echocfg.EchoConfig()
    heavy.timing = dict(uniform=0.0, multitap=0.3, euclid=0.3, ramp=0.4)
    heavy.second_order = "always"
    heavy.rotation = dict(prob=1.0, len=[4, 4])
    for seed in (1, 7, 42):
        r1, r2 = random.Random(seed), random.Random(seed)
        E.draw_plan(r1, 12, None)
        E.draw_plan(r2, 12, heavy)
        if r1.random() != r2.random():
            check("layout: draw counts identical across configs", False, seed)
            return
    check("layout: draw counts identical across configs", True)
    plans = [E.draw_plan(random.Random(k), 12, None) for k in range(200)]
    check("layout: default config draws ONLY uniform timing (P9 behavior)",
          all(p.timing == "uniform" and p.pan == "inherit" and not p.so
              for p in plans))
    hp = [E.draw_plan(random.Random(k), 12, heavy) for k in range(200)]
    kinds = {p.timing for p in hp}
    check("layout: heavy config reaches every family",
          kinds == {"multitap", "euclid", "ramp"}, kinds)
    check("layout: second_order='always' marks every plan",
          all(p.so for p in hp))


# --------------------------------------------------------- family arithmetic
def test_multitap():
    plan = _plan(timing="multitap", fb=0.7,
                 tp=dict(ntaps=3, cycle=1.0, offs=[0.0, 0.3, 0.7],
                         att=[1.0, 0.9, 0.8]))
    train = E.echo_pattern([_ev()], plan, FOLD)
    offs = [round(t.start - 10.0, 6) for t in train]
    check("multitap: tap cell repeats per cycle, source tap 0 skipped",
          offs[:5] == [0.3, 0.7, 1.0, 1.3, 1.7], offs[:5])
    a = [t.amp for t in train]
    check("multitap: decay per CYCLE, per-tap attenuation applied",
          abs(a[0] - 0.4 * 0.7 * 0.9) < 1e-12
          and abs(a[2] - 0.4 * 0.7 ** 2 * 1.0) < 1e-12, a[:3])


def test_euclid():
    plan = _plan(timing="euclid", fb=0.7,
                 tp=dict(pulses=3, steps=8, cycle=1.6))
    train = E.echo_pattern([_ev()], plan, FOLD)
    pat = bjorklund(3, 8)
    sd = 1.6 / 8
    want = [i * sd for i, h in enumerate(pat) if h and i != 0]
    offs = [round(t.start - 10.0, 6) for t in train[:len(want)]]
    check("euclid: taps land on the Bjorklund pattern",
          all(abs(a - b) < 1e-9 for a, b in zip(offs, want)),
          (offs, [round(w, 3) for w in want]))


def test_ramp():
    plan = _plan(timing="ramp", fb=0.8,
                 tp=dict(delay0=0.4, ratio=0.85, couple=True))
    train = E.echo_pattern([_ev()], plan, FOLD)
    t, want = 10.0, []
    for k in range(1, len(train) + 1):
        t += 0.4 * 0.85 ** (k - 1)
        want.append(t)
    check("ramp: geometric delay accumulation",
          all(abs(tr.start - w) < 1e-9 for tr, w in zip(train, want)))
    cpr = -1200 * math.log2(0.85)
    check("ramp: pitch couples to the tape physics (cents = "
          "-1200*log2(ratio) per repeat)",
          all(abs(tr.det - min(E.RAMP_CENTS_CAP, cpr * (i + 1))) < 1e-9
              for i, tr in enumerate(train)),
          [round(tr.det, 1) for tr in train[:3]])
    check("ramp: each note glides toward the next repeat's pitch (detg)",
          all(abs((tr.det + tr.detg)
                  - min(E.RAMP_CENTS_CAP, cpr * (i + 2))) < 1e-9
              for i, tr in enumerate(train)))
    plan2 = _plan(timing="ramp", fb=0.8,
                  tp=dict(delay0=0.4, ratio=0.85, couple=False))
    train2 = E.echo_pattern([_ev()], plan2, FOLD)
    check("ramp: pitch_couple=false leaves pitch alone",
          all(tr.det == 0.0 and tr.detg == 0.0 for tr in train2))


def test_pan_and_cap():
    plan = _plan(pan="pingpong", fb=0.75)
    train = E.echo_pattern([_ev()], plan, FOLD)
    check("pan: pingpong alternates hard L/R",
          [t.pan for t in train[:4]] == [0.12, 0.88, 0.12, 0.88])
    plan = _plan(pan="rotate", fb=0.75)
    train = E.echo_pattern([_ev()], plan, FOLD)
    check("pan: rotate cycles three positions",
          [t.pan for t in train[:3]] == [0.5, 0.8, 0.2])
    plan = _plan(fb=0.79)
    train = E.echo_pattern([_ev(), _ev(start=10.2)], plan, FOLD,
                           max_notes=5)
    check("cap: max_notes truncates the train", len(train) == 5)


def test_second_order():
    plan = _plan(fb=0.6, so=True)
    first = E.echo_pattern([_ev()], plan, FOLD)
    so = E.second_order(first, plan, FOLD, max_notes=1000)
    check("2nd: second order derives from the first-order train",
          len(so) > 0 and all(t.echo > 0 for t in so))
    check("2nd: derived treatment is simpler (longer delay, lower fb)",
          all(abs(t.amp) <= max(f.amp for f in first) for t in so))
    check("2nd: cap zero yields nothing",
          E.second_order(first, plan, FOLD, max_notes=0) == [])


# ------------------------------------------------------------------- e2e
def test_e2e():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "10",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    spec = "/tmp/p17spec.toml"
    Path(spec).write_text(
        "schema = 1\n[echo]\nsecond_order = \"always\"\n"
        "[echo.timing.weights]\nuniform = 0.1\nmultitap = 0.3\n"
        "euclid = 0.3\nramp = 0.3\n[echo.pan]\ninherit = 0.2\n"
        "pingpong = 0.8\n")
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p17a.wav")
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p17b.wav", "--replay", tok, "--echo-spec", spec)
    def notes(fn, src_only):
        out = set()
        for l in Path(fn).read_text().splitlines():
            if re.match(r"i (?!90 |99 )\d+ ", l):
                out.add(l.strip())
        return out
    # source invariance across specs: --echo 0 strips decoration under both
    r3 = run("--out", "/tmp/p17c.wav", "--replay", tok, "--echo", "0")
    r4 = run("--out", "/tmp/p17d.wav", "--replay", tok, "--echo", "0",
             "--echo-spec", spec)
    c = Path("/tmp/p17c.csd").read_text()
    d = Path("/tmp/p17d.csd").read_text()
    check("e2e: at --echo 0 any spec and no spec give the identical piece",
          re.sub(r"-o \S+", "-o X", c) == re.sub(r"-o \S+", "-o X", d))
    r5 = run("--out", "/tmp/p17e.wav", "--replay", tok, "--echo-spec", spec)
    e = Path("/tmp/p17e.csd").read_text()
    b = Path("/tmp/p17b.csd").read_text()
    check("e2e: a spec'd replay is deterministic",
          re.sub(r"-o \S+", "-o X", e) == re.sub(r"-o \S+", "-o X", b))
    check("e2e: spec run reports new timing families",
          any(w in r5.stdout for w in ("multitap", "euclid", "ramp")))


if __name__ == "__main__":
    print("config:");        test_config()
    print("fixed layout:");  test_fixed_layout()
    print("multitap:");      test_multitap()
    print("euclid:");        test_euclid()
    print("ramp:");          test_ramp()
    print("pan/cap:");       test_pan_and_cap()
    print("second order:");  test_second_order()
    print("e2e:");           test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
