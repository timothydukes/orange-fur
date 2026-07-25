"""Phase 16 tests.  python3 tests/test_p16.py   (renders several short csds)"""
from __future__ import annotations

import math
import random
import re
import struct
import subprocess
import sys
from array import array
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import echoes as E
from orange_fur import fields as FI
from orange_fur import orchestra as O
from orange_fur import routing as R
from orange_fur.alphabet import Cat
from orange_fur.config import Config
from orange_fur.orc import build_orc, build_csd, TUNING_TABLE
from orange_fur.score import Event

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])
SR = 48000
CFG = Config(nodes=4, duration=1, draft=True)


def _read(fn):
    b = open(fn, "rb").read()
    i = 12
    while i < len(b) - 8:
        cid = b[i:i + 4]
        sz = struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"data":
            a = array("f")
            a.frombytes(b[i + 8:i + 8 + sz])
            return np.array(a, dtype=float)
        i += 8 + sz + (sz & 1)


def _render(tf, line):
    rng = random.Random(0)
    rt = R.Routing(n_buses=1,
                   chains=[R.Chain(bus=1, units=[R.u_phaser(rng)], ret=0.02)],
                   room_chain=0, pool_size=1)
    ins = tf(700, random.Random(3), 12)
    code = (ins.code.replace("gaSendL", "gaSend1L")
                    .replace("gaSendR", "gaSend1R"))
    orc = build_orc(CFG, 0.7, code, routing=rt)
    sco = ("f 900 0 -8 -2 0 1 1 1 -1 1 1 1\n"
           "f 901 0 -18 -2 0 0 0 0 0 0 0 0 0 -1 0 0 0 0 0 0 0 0\n"
           f"{CFG.scale.ftable(TUNING_TABLE)}\ni 99 0 8\n{line}\ne")
    Path("/tmp/p16.csd").write_text(build_csd(CFG, orc, sco))
    r = subprocess.run(["csound", "-o", "/tmp/p16.wav", "/tmp/p16.csd"],
                       capture_output=True, timeout=120)
    return None if r.returncode else _read("/tmp/p16.wav")[0::2]


def _peak(w, t0, t1, lo, hi):
    seg = w[int(t0 * SR):int(t1 * SR)]
    m = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=1 << 18))
    f = np.fft.rfftfreq(1 << 18, 1 / SR)
    sel = (f > lo) & (f < hi)
    return float(f[sel][int(np.argmax(m[sel]))])


def _transeg_lin(f0, f1, u):
    """Linear transeg evaluates in FREQUENCY: the expected value at note-
    relative time u. The measurement windows sit mid-note, so assertions
    compare against the trajectory AT THE WINDOW, not the endpoint -- the
    first draft compared endpoints and 'failed' a correct implementation."""
    return f0 + (f1 - f0) * u


# --------------------------------------------------------------- audio
def test_cents_glide_audio():
    base = CFG.scale.freq(60)
    for name, tf in (("pwm", O.t_pwm), ("bank", O.t_bank)):
        w = _render(tf, "i 700 0.05 6 60 0.6 0.5 0.0 0.4 0 0 0 0 100")
        e = _peak(w, 0.3, 1.0, base * 0.9, base * 1.15)
        l = _peak(w, 5.1, 5.9, base * 0.95, base * 1.2)
        # window centers at (0.65-0.05)/6 and (5.5-0.05)/6 of the note
        f0, f1 = base, base * 2 ** (100 / 1200)
        want = (_transeg_lin(f0, f1, (5.5 - 0.05) / 6)
                / _transeg_lin(f0, f1, (0.65 - 0.05) / 6))
        check(f"audio: {name} p13=+100 glides (window-predicted ratio)",
              abs(l / e - want) < 0.004, (l / e, want))

        w = _render(tf, "i 700 0.05 6 60 0.6 0.5 0.0 0.4 0 0 0 40 0")
        e = _peak(w, 0.3, 1.0, base * 0.9, base * 1.15)
        l = _peak(w, 5.1, 5.9, base * 0.9, base * 1.15)
        check(f"audio: {name} p13=0 holds p12 static (P15 bit-behaviour)",
              abs(1200 * math.log2(l / e)) < 2.5,
              1200 * math.log2(max(l, 1) / max(e, 1)))

    # combined degree + cents glide: value at the late window
    w = _render(O.t_pwm, "i 700 0.05 6 60 0.6 0.5 0.0 0.4 0 2 0 0 30")
    f0 = CFG.scale.freq(60)
    f1 = CFG.scale.freq(62) * 2 ** (30 / 1200)
    want = _transeg_lin(f0, f1, (5.55 - 0.05) / 6)
    l = _peak(w, 5.2, 5.9, want * 0.93, want * 1.07)
    check("audio: combined degree+cents glide follows one trajectory",
          abs(1200 * math.log2(l / want)) < 4.0,
          (l, want))


# ------------------------------------------------------------- emission
def test_spectral_arrival():
    """In a spectral section, a whole-degree glide's arrival carries the
    target's cents: detg = target_cents - start_cents. This closes the
    Phase 15 flagged limitation."""
    f, _ = FI.draw_section_field(random.Random(0), 12, CFG.scale.basekey,
                                 CFG.scale.freq, None, 100.0)
    bk = CFG.scale.basekey
    ffold = lambda i: f.snap(i, bk)
    found = False
    for probe in range(bk - 8, bk + 8):
        i0, c0 = ffold(probe)
        i1, c1 = ffold(i0 + 3)
        if i1 != i0 and abs(c1 - c0) > 1.0:
            found = True
            break
    check("arrival: a spectral field offers distinct start/end cents",
          found)
    # mirror of the emission-site computation
    _gl = i1 - i0
    _dg = c1 - c0
    end = CFG.scale.freq(i0 + _gl) * 2 ** ((c0 + _dg) / 1200)
    want = CFG.scale.freq(i1) * 2 ** (c1 / 1200)
    check("arrival: start det + detg lands exactly on the target frequency",
          abs(1200 * math.log2(end / want)) < 1e-9)


def test_echo_cascade_detg():
    f, _ = FI.draw_section_field(random.Random(0), 12, CFG.scale.basekey,
                                 CFG.scale.freq, None, 100.0)
    bk = CFG.scale.basekey
    fold = lambda i: f.snap(i, bk)
    i0, c0 = fold(bk + 2)
    src = Event(instr=100, start=0.0, dur=1.0, index=i0, det=c0, glide=3.0,
                amp=.4, pan=.5, send=.4, slew=.3, cat=int(Cat.PARTIAL))
    plan = E.EchoPlan(prob=1.0, delay=0.3, fb=0.6, mode="degrees", step=2)
    train = E.echo_pattern([src], plan, fold)
    ok = True
    for t in train:
        ti, tc = fold(t.index + int(round(t.glide)))
        end = CFG.scale.freq(t.index + int(round(t.glide))) \
            * 2 ** ((t.det + t.detg) / 1200)
        want = CFG.scale.freq(ti) * 2 ** (tc / 1200)
        if abs(1200 * math.log2(end / want)) > 1e-9:
            ok = False
            break
    check("echo: cascade glide arrivals re-derive detg onto their own "
          "stepped target", ok and len(train) > 3)


# ------------------------------------------------------------------ e2e
def test_e2e():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "8",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p16a.wav", "--spectral", "60")
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p16b.wav", "--spectral", "60", "--replay", tok)
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p16a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p16b.csd").read_text())
    check("e2e: replay determinism with p13 in the contract", a == b)
    check("e2e: score lines carry 13 p-fields (14 columns)",
          all(len(l.split()) == 14 for l in a.splitlines()
              if re.match(r"i (?!90 |99 )\d+ ", l)))


if __name__ == "__main__":
    print("audio:");    test_cents_glide_audio()
    print("arrival:");  test_spectral_arrival()
    print("echo:");     test_echo_cascade_detg()
    print("e2e:");      test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
