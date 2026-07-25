"""Phase 15 tests.  python3 tests/test_p15.py"""
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

from orange_fur import fields as FI
from orange_fur import orchestra as O
from orange_fur import routing as R
from orange_fur.alphabet import Cat
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.orc import build_orc, build_csd, TUNING_TABLE
from orange_fur.score import graph_events, set_instr_peaks, reso_table

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])
CFG = Config(nodes=4, duration=1)
CPS = CFG.scale.freq
BK = CFG.scale.basekey
NG = CFG.scale.numgrades


# ------------------------------------------------------------- target math
def test_targets():
    cap = FI._half_step_cap(CPS, BK, NG)
    check("targets: half-step cap derived from the tuning (50-65c band "
          "for Werckmeister)", 50.0 < cap < 65.0, cap)
    # a true frequency inverts exactly: cps(idx)*2^(c/1200) == freq
    for freq in (301.7, 523.25, 111.9, 887.3):
        t = FI._freq_to_target(freq, CPS, BK, NG)
        check_ok = t is not None
        if t:
            pc, c = t
            # reconstruct: find the index in-register with that pc nearest
            best = min((abs(1200 * math.log2(freq / CPS(BK + pc + o * NG)))
                        for o in range(-3, 4)), default=999)
            check_ok = abs(best - abs(c)) < 0.01 and abs(c) <= cap
        check(f"targets: {freq} Hz inverts to a degree+cents within the cap",
              check_ok, t)
    check("targets: sub-register frequency rejected, not mis-filed",
          FI._freq_to_target(3.0, CPS, BK, NG) is None)
    for k in range(200):
        f, _ = FI.draw_section_field(random.Random(k), NG, BK, CPS,
                                     None, 100.0)
        assert all(abs(c) <= cap + 1e-9 for c in f.cents.values())
    check("targets: 200 spectral fields, every residual within the cap",
          True)


def test_snap_contract():
    lat = FI.draw_field(random.Random(3), NG)
    i, c = lat.snap(BK + 5, BK)
    check("snap: lattice fields return cents 0.0 (pre-P15 contract)",
          isinstance(i, int) and c == 0.0)
    f, _ = FI.draw_section_field(random.Random(0), NG, BK, CPS, None, 100.0)
    for probe in range(BK - 15, BK + 15):
        i, c = f.snap(probe, BK)
        pc = (i - BK) % NG
        check_ok = pc in f.pcs and abs(c - f.cents.get(pc, 0.0)) < 1e-9
        if not check_ok:
            check("snap: spectral snap returns the target's own cents",
                  False, (probe, i, c))
            return
    check("snap: spectral snap returns the target's own cents", True)


# --------------------------------------------------------- skeleton sharing
def _gen(spectral, seed=42):
    rng = random.Random(seed)
    cfg = Config(nodes=12, duration=3, draft=True, spectral=spectral)
    rt = R.generate_routing(rng)
    orch = O.generate(rng, cfg.scale.numgrades,
                      n_buses=rt.n_buses).subset(cfg.subset, rng)
    set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
    catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
    ev, sm = graph_events(cfg, solve(12, rng), rng, catmap=catmap)
    return ev, sm, cfg


def test_sharing_and_conformance():
    ev0, sm0, _ = _gen(0.0)
    ev1, sm1, cfg = _gen(100.0)
    k = lambda e: (e.instr, round(e.start, 6), round(e.dur, 6),
                   round(e.amp, 9), e.echo)
    check("share: --spectral 0 and 100 share the event skeleton "
          "(one token, two harmonic worlds)",
          sorted(map(k, ev0)) == sorted(map(k, ev1)))
    check("share: --spectral 0 leaves every field det at zero "
          "(pre-P15 behavior)",
          all(abs(e.det) < 1e-9 for e in ev0 if e.echo <= 0))
    carried = sum(1 for e in ev1 if e.echo == 0 and abs(e.det) > 0.5)
    check("share: --spectral 100 puts field cents on source notes",
          carried > 10, carried)
    check("share: lattice sections still appear in the report grammar",
          all("field" in m for m in sm1["macro"]))
    # conformance: each source note's (pc, det) realizes a field target
    bounds = [(m["t0"], m["field"]) for m in sm1["macro"]]
    # parse describe(): {0,4+2c,7+6c} vf(harm)
    def parse(desc):
        body = desc.split("}")[0].strip("{")
        out = {}
        for tokn in body.split(","):
            m = re.match(r"(\d+)([+-]\d+)?c?", tokn)
            out[int(m.group(1))] = float(m.group(2) or 0)
        return out
    def field_at(t):
        f = parse(bounds[0][1])
        for (t0, d) in bounds:
            if t0 <= t:
                f = parse(d)
        return f
    # STRONG check: every source (pc, det) pair matches SOME section's
    # target exactly -- an arbitrary detune cannot pass this. WALL-CLOCK
    # check is looser: notes conform to their EMITTING section (P13
    # semantics), and slow patterns carry deep into the next section, more
    # visibly now that spectral fields are small sets.
    union = {}
    for _, d in bounds:
        for pc, c in parse(d).items():
            union.setdefault(pc, set()).add(round(c))
    bad_u = bad_w = 0
    nsrc = 0
    for e in ev1:
        if e.echo != 0:
            continue
        nsrc += 1
        pc = (e.index - cfg.scale.basekey) % cfg.scale.numgrades
        if pc not in union or all(abs(e.det - c) > 1.0 for c in union[pc]):
            bad_u += 1
        fmap = field_at(e.start)
        if pc not in fmap or abs(e.det - fmap[pc]) > 1.0:
            bad_w += 1
    check("conform: every source (pc, det) is an exact target of some "
          "section's field", bad_u == 0, bad_u)
    # P19 AMENDMENT: band 0.15 -> 0.22. The P19 stream shift re-rolled this
    # seed's piece; the suspension fraction at nodes=12/--spectral 100 was
    # measured 0.00-0.165 across 8 seeds (mean 0.062) with seed 42 at the
    # observed max. Union-exactness above stays strict; this band only
    # says suspensions remain a minority.
    check("conform: most notes conform to the wall-clock field (rest carry "
          "their emitting section's harmony)", bad_w / nsrc < 0.22,
          bad_w / nsrc)


# ------------------------------------------------------------- f901 + tank
def test_reso_table_and_tank():
    t = reso_table([(0.0, [(0, 0.0), (4, 12.3), (7, -8.0)])])
    vals = t.split()
    check("table: 9-column rows (t, d1..d4, c1..c4), cyclic padding",
          "0.0000 0 4 7 0 0.0 12.3 -8.0 0.0" in t, t)
    check("table: terminator is 9 wide",
          t.rstrip().endswith("-1 0 0 0 0 0 0 0 0"))

    # tank rings shifted by the cents column
    u = R.u_modes(random.Random(1))
    cfg = Config(nodes=4, duration=1, draft=True, wetdry=0.95)
    rt = R.Routing(n_buses=1, chains=[R.Chain(bus=1, units=[u], ret=1.0)],
                   room_chain=0, pool_size=1)
    ins = O.t_pwm(700, random.Random(3), 12)
    code = (ins.code.replace("gaSendL", "gaSend1L")
                    .replace("gaSendR", "gaSend1R"))
    orc = build_orc(cfg, 0.7, code, routing=rt)
    CENTS = 40.0
    sco = ("f 900 0 -8 -2 0 1 1 1 -1 1 1 1\n"
           f"f 901 0 -18 -2 0 0 4 7 9 {CENTS} {CENTS} {CENTS} {CENTS} "
           "-1 0 0 0 0 0 0 0 0\n"
           f"{cfg.scale.ftable(TUNING_TABLE)}\ni 99 0 8\n"
           "i 700 0.05 0.03 66 0.9 0.5 1.0 0.05 0 0 0 0\ne")
    Path("/tmp/p15t.csd").write_text(build_csd(cfg, orc, sco))
    r = subprocess.run(["csound", "-o", "/tmp/p15t.wav", "/tmp/p15t.csd"],
                       capture_output=True, timeout=180)
    b = Path("/tmp/p15t.wav").read_bytes()
    i = 12
    w = None
    while i < len(b) - 8:
        cid = b[i:i + 4]
        sz = struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"data":
            a = array("f")
            a.frombytes(b[i + 8:i + 8 + sz])
            w = np.array(a, dtype=float)[0::2]
            break
        i += 8 + sz + (sz & 1)
    sr = 48000
    seg = w[int(0.09 * sr):int(0.45 * sr)]
    m = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=1 << 19))
    fr = np.fft.rfftfreq(1 << 19, 1 / sr)
    sel = (fr > 60) & (fr < 3000)
    pk = float(fr[sel][int(np.argmax(m[sel]))])
    ratio = 2 ** (CENTS / 1200)
    cands = [CPS(BK + [0, 4, 7, 9][v] + u.params["oct"][v] * NG) * ratio
             for v in range(4)]
    hit = any(abs(pk - c * h) / (c * h) < 0.012
              for c in cands for h in (1, 2, 3))
    check("tank: resonator ring shifted by the f901 cents column",
          r.returncode == 0 and hit,
          (pk, [round(c, 1) for c in cands]))


# ------------------------------------------------------------ determinism
def test_determinism():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "8",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p15a.wav", "--spectral", "70")
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p15b.wav", "--spectral", "70", "--replay", tok)
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p15a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p15b.csd").read_text())
    check("determinism: replay identical with spectral draws in the stream",
          a == b)
    r0 = run("--out", "/tmp/p15c.wav", "--replay", tok)
    check("determinism: same token at --spectral 0 renders (remix-class)",
          r0.returncode == 0)


if __name__ == "__main__":
    print("target math:");     test_targets()
    print("snap contract:");   test_snap_contract()
    print("sharing/conform:"); test_sharing_and_conformance()
    print("f901/tank:");       test_reso_table_and_tank()
    print("determinism:");     test_determinism()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
