"""Phase 13 tests.  python3 tests/test_p13.py"""
from __future__ import annotations

import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import fields as FI
from orange_fur import orchestra as O
from orange_fur import routing as R
from orange_fur.alphabet import Cat
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.score import graph_events, set_instr_peaks

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])


# -------------------------------------------------------------------- snap
def test_snap():
    # Phase 15: snap returns (index, cents); lattice fields carry cents 0
    f = FI.Field(pcs=frozenset({0, 2, 6}), grades=12)
    sn = lambda i: f.snap(i, 60)[0]
    check("snap: identity when already on the field",
          sn(62) == 62 and f.snap(62, 60)[1] == 0.0)
    check("snap: nearest field degree",
          sn(63) == 62 and sn(65) == 66)
    check("snap: ties resolve downward",
          sn(64) == 62)                  # pc 4: pc2 and pc6 both 2 away
    check("snap: works across octaves",
          sn(85) == 84 and ((sn(37) - 60) % 12) in f.pcs,
          (sn(85), sn(37)))
    out = [sn(i) for i in range(30, 90)]
    check("snap: every output lands on the field",
          all(((o - 60) % 12) in f.pcs for o in out))


def test_draw_field():
    rng = random.Random(4)
    f1 = FI.draw_field(rng, 12)
    check("draw: size within band, distinct, anchored on pc 0",
          FI.SIZE[0] <= len(f1.pcs) <= FI.SIZE[1] and 0 in f1.pcs)
    f2 = FI.draw_field(rng, 12, prev=f1)
    common = (f1.pcs & f2.pcs) - {0}
    prev_non0 = len(f1.pcs) - 1
    check("draw: successive fields keep about half their tones",
          abs(len(common) - prev_non0 * FI.KEEP_FRAC) <= 1.0,
          (sorted(f1.pcs), sorted(f2.pcs)))
    small = FI.draw_field(random.Random(1), 5)
    check("draw: small tunings respected (size <= grades)",
          len(small.pcs) <= 5 and all(0 <= p < 5 for p in small.pcs))


# -------------------------------------------------------------- integration
def _gen(fields_on, seed=42):
    rng = random.Random(seed)
    cfg = Config(nodes=12, duration=3, draft=True, fields=fields_on)
    rt = R.generate_routing(rng)
    orch = O.generate(rng, cfg.scale.numgrades,
                      n_buses=rt.n_buses).subset(cfg.subset, rng)
    set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
    catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
    ev, sm = graph_events(cfg, solve(12, rng), rng, catmap=catmap)
    return ev, sm, cfg


def test_conformance():
    for seed in (42, 7, 99):
        ev, sm, cfg = _gen(1, seed)
        g = cfg.scale.numgrades
        bounds = [(m["t0"], set(int(x) for x in
                                m["field"].strip("{}").split(",")))
                  for m in sm["macro"]]
        union = set().union(*(p for _, p in bounds))

        def fat(t):
            f = bounds[0][1]
            for (t0, pcs) in bounds:
                if t0 <= t:
                    f = pcs
            return f
        pcs = [((e.index - cfg.scale.basekey) % g, e.start) for e in ev]
        check(f"conform: seed {seed} every pitch class lies in SOME "
              "section's field", all(pc in union for pc, _ in pcs))
        off = sum(1 for pc, t in pcs if pc not in fat(t))
        # cross-boundary spill notes conform to their EMITTING section --
        # suspensions, documented in fields.py. Band aligned with test_p15:
        # slow patterns carry deep past boundaries, and the exact fraction
        # re-rolls whenever the draw layout changes upstream (P17 did).
        check(f"conform: seed {seed} >=85% conform to the wall-clock field "
              "(rest carry their emitting section's harmony)",
              off / len(pcs) < 0.15, off / len(pcs))
        # sub-degree glides are ornamental bends and exempt by design.
        # P23 AMENDMENT: arrivals from cross-boundary SPILL conform to
        # their EMITTING section (the documented suspension semantics the
        # wall-clock check above already tolerates); notes starting within
        # 8 s after a boundary may therefore match the PREVIOUS field
        # instead. The new P23 stream layout produced the first
        # spill-heavy boundary (seed 42, 25 suspended arrivals at
        # 76-80 s) and exposed that this check was measuring suspensions
        # as failures.
        def fprev(t):
            prev = bounds[0][1]
            for k in range(1, len(bounds)):
                if bounds[k][0] <= t < bounds[k][0] + 8.0:
                    prev = bounds[k - 1][1]
                    return prev
            return None
        def arr_ok(e):
            pc = (e.index + int(round(e.glide)) - cfg.scale.basekey) % g
            if pc in fat(e.start):
                return True
            fp = fprev(e.start)
            return fp is not None and pc in fp
        gbad = [e for e in ev if e.glide and abs(e.glide) >= 1.0
                and not arr_ok(e)]
        check(f"conform: seed {seed} whole-degree glide arrivals on the "
              "field (modulo suspensions)",
              len(gbad) / max(1, len(ev)) < 0.02, len(gbad))


def test_off_switch_shares_stream():
    ev1, _, _ = _gen(1)
    ev0, _, cfg = _gen(0)
    k = lambda e: (e.instr, round(e.start, 6), round(e.dur, 6),
                   round(e.amp, 9), e.echo)
    check("off: --fields 0 shares the event skeleton (same stream, "
          "pitches free)",
          len(ev0) == len(ev1)
          and sorted(map(k, ev0)) == sorted(map(k, ev1)))
    g = cfg.scale.numgrades
    diff = sum(1 for a, b in zip(sorted(ev0, key=k), sorted(ev1, key=k))
               if a.index != b.index)
    check("off: snapping actually moved pitches (fields do something)",
          diff > 0, diff)


def test_e2e():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "10",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p13a.wav")
    check("e2e: fields report line printed", "fields" in r1.stdout)
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p13b.wav", "--replay", tok)
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p13a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p13b.csd").read_text())
    check("e2e: replay determinism with field draws in the stream", a == b)
    r0 = run("--out", "/tmp/p13c.wav", "--replay", tok, "--fields", "0")
    check("e2e: --fields 0 accepted and un-reported",
          r0.returncode == 0 and "fields" not in r0.stdout)


if __name__ == "__main__":
    print("snap:");          test_snap()
    print("draw:");          test_draw_field()
    print("conformance:");   test_conformance()
    print("off switch:");    test_off_switch_shares_stream()
    print("e2e:");           test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
