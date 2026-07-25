"""Phase 5 tests.  python3 tests/test_p5.py   (renders; needs csound + numpy)"""
from __future__ import annotations

import random
import struct
import subprocess
import sys
from array import array
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import layers as L
from orange_fur import macro as M
from orange_fur import orchestra as O
from orange_fur import routing as R
from orange_fur.alphabet import Cat, L4
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.orc import build_orc, build_csd, TUNING_TABLE
from orange_fur.score import graph_events, cost_route, set_instr_peaks

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# --------------------------------------------------------------- euclidean
def test_euclidean():
    # canonical Euclidean rhythms
    known = {
        (3, 8): "10010010",
        (5, 8): "10110110",
        (2, 5): "10100",
        (4, 4): "1111",
        (1, 4): "1000",
        (0, 5): "00000",
    }
    for (k, n), want in known.items():
        got = "".join(str(x) for x in M.bjorklund(k, n))
        check(f"euclid: E({k},{n})", got == want, f"{got} != {want}")

    for k in range(0, 13):
        for n in range(1, 13):
            p = M.bjorklund(k, n)
            assert len(p) == n and sum(p) == min(k, n)
    check("euclid: length n, exactly min(k,n) pulses (all k,n <= 12)", True)


def test_macro_tracks():
    rng = random.Random(4)
    plan = M.draw_plan(rng, 0.0, 120.0)
    check("macro: playlist drawn from the gesture palette",
          all(g in M.GESTURE_PALETTE for g in plan.playlist)
          and 3 <= len(plan.playlist) <= 6)
    # the gesture pointer ADVANCES over time (it must actually sequence)
    seen = {plan.gesture_at(t) for t in np.arange(0, 120, 0.5)}
    check("macro: gesture track sequences more than one family",
          len(seen) > 1, seen)
    # accent contour swings but never goes negative or above 1
    g = [plan.gain_at(t) for t in np.arange(0, 120, 0.25)]
    check("macro: accent gain in (0, 1] and actually varies",
          all(0 < x <= 1.0001 for x in g) and (max(g) - min(g)) > 0.05,
          (min(g), max(g)))
    # register walks
    offs = {plan.register_offset(t) for t in np.arange(0, 120, 0.5)}
    check("macro: register staircase actually steps", len(offs) > 1, len(offs))


# ------------------------------------------------------------------ gestures
def test_gestures():
    rng = random.Random(11)
    # every new family has a size, spread and pattern
    for l4 in (L4.GLISS, L4.CLOUDGLISS, L4.DIVERGE, L4.SWEEPCLICK,
               L4.BURSTSEQ, L4.LOOP, L4.LONGDECAY):
        lo, hi = L.PATTERN_SIZE[l4]
        degs = L.pattern_degrees(l4, rng.randint(lo, hi), rng)
        check(f"gesture: {l4.name} produces a pattern", len(degs) >= 1)

    # LOOP repeats its cell VERBATIM
    degs = L.pattern_degrees(L4.LOOP, 12, random.Random(2))
    period = None
    for p in range(2, 5):
        if all(degs[i] == degs[i % p] for i in range(len(degs))):
            period = p
            break
    check("gesture: LOOP is a verbatim repetition of a short cell",
          period is not None, degs)

    # CLOUDGLISS: all grains glide the SAME direction
    for d in (-1, 1):
        gl = [L.glide_for(L4.CLOUDGLISS, m, 16, random.Random(m), common_dir=d)[0]
              for m in range(16)]
        check(f"gesture: CLOUDGLISS all grains glide one way (dir={d})",
              all((x > 0) == (d > 0) for x in gl), gl[:4])

    # DIVERGE: glide targets fan OUT -- sign follows position, magnitude grows
    k = 16
    gl = [L.glide_for(L4.DIVERGE, m, k, random.Random(7))[0] for m in range(k)]
    lo_half = [x for x in gl[:k // 2]]
    hi_half = [x for x in gl[k // 2:]]
    check("gesture: DIVERGE fans out (first half down, second half up)",
          all(x <= 0 for x in lo_half) and all(x >= 0 for x in hi_half),
          gl)
    check("gesture: DIVERGE magnitude grows toward the edges",
          abs(gl[0]) > abs(gl[k // 2 - 1]) and abs(gl[-1]) > abs(gl[k // 2]))

    # SWEEPCLICK: note 0 sweeps, the clicks do not
    k = 10
    gl = [L.glide_for(L4.SWEEPCLICK, m, k, random.Random(3))[0] for m in range(k)]
    check("gesture: SWEEPCLICK sweeps on note 0, clicks do not glide",
          abs(gl[0]) > 4 and all(x == 0 for x in gl[1:]), gl)

    # families without a glide spec never emit one
    for l4 in (L4.CHORD, L4.TRILL, L4.OSTINATO, L4.LOOP, L4.LONGDECAY):
        assert L.glide_for(l4, 0, 4, rng) == (0.0, 0.0)
    check("gesture: non-glide families emit no glide", True)


# --------------------------------------------------- GLIDE, MEASURED IN AUDIO
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


def _band(x, sr, f, w=0.06):
    W = x * np.hanning(len(x))
    m = np.abs(np.fft.rfft(W, n=1 << 17))
    fr = np.fft.rfftfreq(1 << 17, 1 / sr)
    sel = (fr > f * (1 - w)) & (fr < f * (1 + w))
    return float(m[sel].sum())


def _logshift(a, b, sr, fmin=60, fmax=12000, nlog=1400):
    """Best log-frequency shift aligning spectrum a onto b -> frequency ratio.
    Robust to WHICH partial is loudest, because it correlates whole spectra."""
    def ls(x):
        w = x * np.hanning(len(x))
        m = np.abs(np.fft.rfft(w, n=1 << 16))
        f = np.fft.rfftfreq(1 << 16, 1 / sr)
        lg = np.geomspace(fmin, fmax, nlog)
        sp = np.interp(lg, f, m)
        sp = np.log1p(sp / (sp.max() + 1e-12) * 100)
        return sp - sp.mean()
    A, B = ls(a), ls(b)
    c = np.correlate(B, A, mode="full")
    k = int(np.argmax(c)) - (len(A) - 1)
    return float(np.exp(k * (np.log(fmax) - np.log(fmin)) / (nlog - 1)))


def test_glide_in_audio():
    """Every template must ACTUALLY glide when p10 is set -- measured in the
    rendered audio, not asserted from the source.

    MEASURING THIS IS HARDER THAN IT LOOKS, and the wrong metric hides real
    bugs. Spectral centroid lies: bandlimited oscillators lose harmonics as f0
    rises, so the centroid barely moves. Spectral peak lies: it jumps between
    partials. Two metrics with DISJOINT blind spots are used, and a template
    passes if either one sees the glide:

      A. ENERGY MIGRATION -- with a +12 degree (one octave) glide, energy must
         move from f0 to 2*f0 by the end of the note. Blind spot: instruments
         where f0 is not dominant anyway (sync's slave dominates; the chirp
         sweeps off f0 by design).

      B. LOG-SPECTRAL SHIFT -- correlate whole log-frequency spectra, early vs
         late, and read off the shift; normalise against a no-glide control.
         Blind spot: burst's fixed-rate AM comb and tick's fast decay, which
         the correlator locks onto instead of the carrier.

    This is the test that caught the syncphasor self-feedback bug -- inherited
    from Phase 3, where it was inaudible because every note held a fixed pitch.
    """
    cfg = Config(nodes=4, duration=2, draft=True)
    rt = R.Routing(n_buses=1,
                   chains=[R.Chain(bus=1,
                                   units=[R.u_phaser(random.Random(0))],
                                   ret=0.02)],
                   room_chain=0, pool_size=1)
    sr, f0, dur = 48000, 261.626, 2.5

    templates = [("bank", O.t_bank), ("mslave", O.t_mslave), ("pwm", O.t_pwm),
                 ("pluck", O.t_pluck), ("sync", O.t_sync_pluck),
                 ("fbshape", O.t_fb_shaper), ("modal", O.t_modal),
                 ("pipe", O.t_pipe), ("chirp", O.t_click), ("burst", O.t_burst),
                 ("tick", O.t_tick), ("tcloud", O.t_tcloud), ("wtx", O.t_wtx),
                 ("pll", O.t_pll), ("wtswell", O.t_wtswell),
                 ("bankswell", O.t_bankswell)]

    for name, tf in templates:
        ins = tf(700, random.Random(3), 12)
        code = (ins.code.replace("gaSendL", "gaSend1L")
                        .replace("gaSendR", "gaSend1R"))
        orc = build_orc(cfg, 0.7, code, routing=rt)
        ratios, shifts = {}, {}
        for g in (0, 12):
            sco = (f"f 900 0 -8 -2 0 1 1 1 -1 1 1 1\n"
                   f"{cfg.scale.ftable(TUNING_TABLE)}\n"
                   f"i 99 0 {dur + 2}\n"
                   f"i 700 0.05 {dur} 60 0.6 0.5 0.0 0.05 0 {g} 0\ne")
            Path("/tmp/p5g.csd").write_text(build_csd(cfg, orc, sco))
            r = subprocess.run(["csound", "-o", "/tmp/p5g.wav", "/tmp/p5g.csd"],
                               capture_output=True, timeout=120)
            if r.returncode != 0:
                ratios[g] = shifts[g] = None
                continue
            w = _read("/tmp/p5g.wav")[0::2]
            early = w[int(0.06 * sr):int(0.06 * sr + 0.30 * sr)]
            late = w[int((dur - 0.35) * sr):int((dur - 0.02) * sr)]
            ratios[g] = _band(late, sr, f0) / max(_band(late, sr, 2 * f0), 1e-9)
            shifts[g] = _logshift(early, late, sr)

        migrated = (ratios[0] and ratios[12]
                    and ratios[12] < 0.45 * ratios[0])          # metric A
        shifted = (shifts[0] and shifts[12]
                   and shifts[12] > 1.5 * shifts[0])            # metric B
        how = "migration" if migrated else ("log-shift" if shifted else "-")
        check(f"glide: {name} glides in the rendered audio ({how})",
              bool(migrated or shifted),
              f"f0/2f0 flat={ratios[0]:.3f} glided={ratios[12]:.3f}; "
              f"shift flat={shifts[0]:.2f} glided={shifts[12]:.2f}")


# --------------------------------------------------------------- cost routing
def test_cost_routing():
    rng = random.Random(8)
    rt = R.generate_routing(rng)
    orch = O.generate(rng, 12, n_buses=rt.n_buses).subset(60, rng)
    set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
    catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}

    cfg = Config(nodes=40, duration=3)
    sol = solve(40, rng)
    ev, _ = graph_events(cfg, sol, rng, catmap=catmap)

    cats_before = [e.cat for e in ev]
    costs = orch.costs()
    before = sum(costs[e.instr] * e.dur for e in ev)

    cap = before * 0.4
    rep = cost_route(ev, cfg, orch, cap)
    after = sum(costs[e.instr] * e.dur for e in ev)

    if rep.get("at_floor"):
        # the honest case: every note is already on its category's cheapest
        # voice and the floor is above the cap. Verify the claim.
        on_cheapest = all(
            costs[e.instr] <= min(costs[i] for i in catmap[Cat(e.cat)])
            + 1e-9
            for e in ev)
        check("cost: at-floor reported and every note on its category's "
              "cheapest voice", on_cheapest)
    else:
        check("cost: routing reaches the cap", after <= cap * 1.02,
              (after, cap))
    check("cost: reported figures match the real recomputed cost",
          abs(rep["after"] - after) < max(1.0, 0.01 * after),
          (rep["after"], after))
    check("cost: CATEGORY is never changed (the contract survives)",
          [e.cat for e in ev] == cats_before)
    check("cost: every note still on an instrument of its own category",
          all(e.instr in catmap[Cat(e.cat)] for e in ev))
    check("cost: no notes were culled by cost routing",
          len(ev) == len(cats_before))
    check("cost: rerouting reported", rep["rerouted"] > 0, rep)

    # a cap above the cost is a no-op
    rep2 = cost_route(ev, cfg, orch, after * 10)
    check("cost: slack cap is a no-op", rep2["rerouted"] == 0)


def test_bridging():
    """Macro culling and gesture slots can align into a 15-25 s hole; the gap
    bridge must cover every one. Deterministic: graph_events is driven with a
    fixed Random directly (the CLI is entropy-seeded BY SPEC, so this cannot
    be tested through it)."""
    from orange_fur.score import graph_events, INSTR_TAU
    from orange_fur.routing import generate_routing

    def coverage_gaps(events, gap_min):
        spans = []
        for e in sorted(events, key=lambda e: e.start):
            tau = INSTR_TAU.get(e.instr)
            cov = e.dur if tau is None else min(e.dur, 3.0 * tau)
            spans.append((e.start, e.start + cov))
        cur = spans[0][1]
        holes = []
        for st, en in spans[1:]:
            if st - cur > gap_min:
                holes.append((cur, st))
            cur = max(cur, en)
        return holes

    bridged_runs = 0
    for k in range(20):
        rng = random.Random(k)
        cfg = Config(nodes=24, duration=4, draft=True)
        rt = R.generate_routing(rng)
        orch = O.generate(rng, cfg.scale.numgrades,
                          n_buses=rt.n_buses).subset(cfg.subset, rng)
        set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
        catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
        ev, sm = graph_events(cfg, solve(24, rng), rng, catmap=catmap)
        holes = coverage_gaps(ev, min(20.0, max(8.0, cfg.dur_sec * 0.033)))
        if holes:
            check("bridge: uncovered gap survived", False, (k, holes))
            return
        bridged_runs += 1 if sm["bridges"] else 0
    check("bridge: 20 runs, no uncovered coverage gap anywhere", True)
    check("bridge: the bridge actually fires on some runs", bridged_runs > 0,
          bridged_runs)


if __name__ == "__main__":
    print("euclidean:");    test_euclidean()
    print("macro tracks:"); test_macro_tracks()
    print("gestures:");     test_gestures()
    print("glide (audio):");test_glide_in_audio()
    print("cost routing:"); test_cost_routing()
    print("gap bridging:"); test_bridging()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
