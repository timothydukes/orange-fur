"""Phase 14 tests.  python3 tests/test_p14.py   (renders several short csds)"""
from __future__ import annotations

import random
import re
import struct
import subprocess
import sys
from array import array
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import orchestra as O
from orange_fur import routing as R
from orange_fur.config import Config
from orange_fur.orc import build_orc, build_csd, TUNING_TABLE
from orange_fur.score import reso_table, trim_timed

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])
SR = 48000


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


def _tuning(cfg):
    tok = cfg.scale.ftable(200).split()[5:]
    ng = int(float(tok[0]))
    intv, bf, bk = float(tok[1]), float(tok[2]), int(float(tok[3]))
    ratios = [float(x) for x in tok[4:4 + ng]]
    return lambda idx: bf * (intv ** ((idx - bk) // ng)) * ratios[(idx - bk) % ng], ng, bk


def _render(unit, f901_rows, note_lines, dur=8):
    cfg = Config(nodes=4, duration=1, draft=True, wetdry=0.95)
    rt = R.Routing(n_buses=1, chains=[R.Chain(bus=1, units=[unit], ret=1.0)],
                   room_chain=0, pool_size=1)
    ins = O.t_pwm(700, random.Random(3), 12)
    code = (ins.code.replace("gaSendL", "gaSend1L")
                    .replace("gaSendR", "gaSend1R"))
    orc = build_orc(cfg, 0.7, code, routing=rt)
    sco = ("f 900 0 -8 -2 0 1 1 1 -1 1 1 1\n"
           f"{f901_rows}\n{cfg.scale.ftable(TUNING_TABLE)}\n"
           f"i 99 0 {dur}\n" + note_lines + "\ne")
    Path("/tmp/p14.csd").write_text(build_csd(cfg, orc, sco))
    r = subprocess.run(["csound", "-o", "/tmp/p14.wav", "/tmp/p14.csd"],
                       capture_output=True, timeout=180)
    return (None if r.returncode else _read("/tmp/p14.wav")[0::2]), cfg


def _peak_hz(w, t0, t1, lo=60, hi=3000):
    seg = w[int(t0 * SR):int(t1 * SR)]
    m = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=1 << 19))
    f = np.fft.rfftfreq(1 << 19, 1 / SR)
    sel = (f > lo) & (f < hi)
    return float(f[sel][int(np.argmax(m[sel]))])


CLICK = "i 700 0.05 0.03 66 0.9 0.5 1.0 0.05 0 0 0 0"


# ---------------------------------------------------------------- the table
def test_table():
    t = reso_table([(0.0, [0, 2, 5]), (30.0, [0, 1, 4, 7, 9])])
    vals = t.split()
    check("table: f 901, GEN-2, exact negative size",
          vals[1] == "901" and vals[4] == "-2" and int(vals[3]) < 0)
    check("table: small fields pad cyclically",
          "0.0000 0 2 5 0" in t, t)
    check("table: rows end with the -1 terminator",
          t.rstrip().endswith("-1 0 0 0 0"))
    w = trim_timed([(0.0, [0, 2]), (30.0, [0, 5]), (80.0, [0, 7])],
                   40.0, 70.0)
    check("table: window trimming shares the rooms helper",
          w == [(0.0, [0, 5])], w)


# ---------------------------------------------- ring alignment (both kinds)
def test_ring_alignment():
    f901 = "f 901 0 -10 -2 0 0 4 7 9 -1 0 0 0 0"
    for kind, mk in (("streson", R.u_streson), ("modes", R.u_modes)):
        u = mk(random.Random(1))
        w, cfg = _render(u, f901, CLICK)
        check(f"ring: {kind} renders, finite, bounded",
              w is not None and bool(np.all(np.isfinite(w)))
              and float(np.abs(w).max()) < 2.0,
              None if w is None else float(np.abs(w).max()))
        if w is None:
            continue
        cps, ng, bk = _tuning(cfg)
        if kind == "streson":
            cands = [cps(bk + [0, 4, 7, 9][u.params["sel"][v]]
                         + u.params["oct"][v] * ng)
                     for v in range(u.params["nv"])]
        else:
            cands = [cps(bk + [0, 4, 7, 9][v] + u.params["oct"][v] * ng)
                     for v in range(4)]
        pk = _peak_hz(w, 0.09, 0.45)
        hit = any(abs(pk - c * h) / (c * h) < 0.01
                  for c in cands for h in (1, 2, 3))
        check(f"ring: {kind} rings on a tuned field degree (or harmonic)",
              hit, (pk, [round(c, 1) for c in cands]))


# -------------------------------------------------------------- retuning
def test_retune():
    # section 2 (t>=3.5s) moves the field up; the SAME unit must ring
    # higher. The second click waits 2 s past the boundary so the port
    # glide (half-time up to 0.25 s) has fully converged -- exciting
    # mid-glide measures the transitional frequency, which is correct
    # behavior but the wrong assertion.
    f901 = "f 901 0 -15 -2 0 0 4 7 9 3.5 5 9 14 16 -1 0 0 0 0"
    u = R.u_modes(random.Random(1))
    notes = CLICK + "\ni 700 5.5 0.03 66 0.9 0.5 1.0 0.05 0 0 0 0"
    w, cfg = _render(u, f901, notes, dur=9)
    cps, ng, bk = _tuning(cfg)
    p1 = _peak_hz(w, 0.09, 0.45)
    p2 = _peak_hz(w, 5.54, 5.90)
    c2 = [cps(bk + [5, 9, 14, 16][v] + u.params["oct"][v] * ng)
          for v in range(4)]
    hit2 = any(abs(p2 - c * h) / (c * h) < 0.015
               for c in c2 for h in (1, 2, 3))
    check("retune: the ring moves with the section's field",
          abs(p2 - p1) / p1 > 0.05 and hit2,
          (p1, p2, [round(c, 1) for c in c2]))


# ------------------------------------------------------- feedback safety
def test_feedback_safety():
    for _ in range(400):
        u = R.u_streson(random.Random(_))
        assert u.params["fb"] <= 0.92
    check("safety: streson feedback capped at 0.92 across draws", True)
    # worst-case fb, long tail: energy must decay, not grow
    u = R.u_streson(random.Random(1))
    u.params["fb"] = 0.92
    w, _ = _render(u, "f 901 0 -10 -2 0 0 4 7 9 -1 0 0 0 0", CLICK, dur=14)
    a1 = float(np.abs(w[int(0.1 * SR):int(0.5 * SR)]).max())    # the ring
    a2 = float(np.abs(w[int(10 * SR):int(13 * SR)]).max())      # long after
    check("safety: worst-case tank decays over time (no runaway)",
          w is not None and np.all(np.isfinite(w)) and a1 > 1e-4
          and a2 < a1 * 1e-3, (a1, a2))


# ------------------------------------------------------------------ pool
def test_pool():
    kinds = []
    for k in range(40):
        rt = R.generate_routing(random.Random(k))
        for ch in rt.chains:
            kinds += [u.kind for u in ch.units]
    ns = kinds.count("streson")
    nm = kinds.count("modes")
    check("pool: resonators drawn into chains at plausible rates",
          ns > 0 and nm > 0, (ns, nm))
    check("pool: streson is room-class (may lead the room chain)",
          "streson" in R.ROOMY)


def test_replay_determinism():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "8",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p14a.wav")
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p14b.wav", "--replay", tok)
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p14a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p14b.csd").read_text())
    check("determinism: replay identical with resonators in the pool",
          a == b)
    check("e2e: f 901 present in every csd", "f 901" in a)


if __name__ == "__main__":
    print("table:");         test_table()
    print("ring alignment:"); test_ring_alignment()
    print("retune:");        test_retune()
    print("safety:");        test_feedback_safety()
    print("pool:");          test_pool()
    print("determinism:");   test_replay_determinism()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
