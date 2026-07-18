"""Phase 2 tests.  python3 tests/test_p2.py"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import layers as L
from orange_fur import constraints as C
from orange_fur.alphabet import Cat, L2, L3, L4, L5, L6
from orange_fur.config import Config
from orange_fur.score import graph_events

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ------------------------------------------------------------------ L2 tempo
def test_tempo():
    for l2 in L2:
        pts = [L.tempo_warp(u / 20, l2) for u in range(21)]
        check(f"tempo: {l2.name} endpoints fixed",
              abs(pts[0]) < 1e-9 and abs(pts[-1] - 1) < 1e-9)
        check(f"tempo: {l2.name} monotone",
              all(pts[i] <= pts[i + 1] + 1e-12 for i in range(20)))
    # accel crowds onsets late (warped positions sit BELOW the diagonal, so
    # equal mass in u maps to positions compressed toward 1)
    check("tempo: ACCEL mass moves late",
          L.tempo_warp(0.5, L2.ACCEL) < 0.5 - 0.05)
    check("tempo: DECEL mass moves early",
          L.tempo_warp(0.5, L2.DECEL) > 0.5 + 0.05)
    check("tempo: STEADY is the identity",
          abs(L.tempo_warp(0.37, L2.STEADY) - 0.37) < 1e-12)


# ------------------------------------------------------------------ L3 rooms
def test_rooms():
    check("rooms: every L3 has a room", set(L.ROOMS) == set(L3))
    check("rooms: only LEFTRIGHT quantises pans",
          [r.l3 for r in L.ROOMS.values() if r.lanes] == [L3.LEFTRIGHT])

    # rooms change ONLY at section boundaries: the rooms list from a real
    # generation must have one entry per section, at the section start times
    cfg = Config(nodes=20, duration=4)
    rng = random.Random(3)
    sol = C.solve(20, rng)
    ev, meta = graph_events(cfg, sol, rng)
    check("rooms: one room per section",
          len(meta["rooms"]) == len(meta["sections"]))
    check("rooms: room times are exactly the section boundaries",
          all(abs(meta["rooms"][i][0] - meta["sections"][i]["t0"]) < 1e-6
              for i in range(len(meta["rooms"]))))

    # LEFTRIGHT lanes reach the events
    for i, s in enumerate(meta["sections"]):
        if s["room"] == "LEFTRIGHT":
            evs = [e for e in ev
                   if s["t0"] <= e.start < s["t1"] and e.cat != int(Cat.SWELL)]
            if evs:
                # a pattern whose HEAD started in the previous section may
                # spill continuation notes across the boundary, and they carry
                # their origin's pan -- the note belongs to the section it
                # began in. So: the large majority on lanes, not all.
                on = sum(1 for e in evs
                         if abs(e.pan - L.PAN_LANES[0]) < 1e-6
                         or abs(e.pan - L.PAN_LANES[1]) < 1e-6)
                check("rooms: LEFTRIGHT pans quantised to lanes (>=80%)",
                      on >= 0.8 * len(evs),
                      f"{on}/{len(evs)}")
            break


# ---------------------------------------------------------------- L4 patterns
def test_patterns():
    rng = random.Random(7)
    for l4 in L4:
        lo, hi = L.PATTERN_SIZE[l4]
        for _ in range(20):
            k = rng.randint(lo, hi)
            degs = L.pattern_degrees(l4, k, rng)
            check(f"patterns: {l4.name} size in bounds",
                  lo <= len(degs) <= hi, len(degs)) if _ == 0 else None
    check("patterns: OSTINATO repeats one degree",
          set(L.pattern_degrees(L4.OSTINATO, 5, rng)) == {0})
    check("patterns: TRILL alternates two degrees",
          len(set(L.pattern_degrees(L4.TRILL, 8, rng))) == 2)
    run = L.pattern_degrees(L4.RUN, 6, rng)
    check("patterns: RUN is stepwise",
          all(abs(run[i + 1] - run[i]) == 1 for i in range(5)), run)
    check("patterns: expected size sanity",
          1.0 <= L.expected_pattern_size(Counter({L4.SUSTAIN: 1})) <= 1.0
          and L.expected_pattern_size(Counter({L4.CHIPARP: 1})) == 12.0)


# ------------------------------------------------------------ convolution
def test_convolution():
    check("conv: definition on a known pair",
          L.convolve([1, 2], [3, 4]) == [3, 10, 8])
    check("conv: identity kernel",
          L.convolve([5, 6, 7], [1]) == [5, 6, 7])
    rng = random.Random(9)
    for l5 in L5:
        for l6 in L6:
            for k in (1, 2, 5, 16):
                env = L.duration_envelope(k, l5, l6, rng)
                check(f"conv: {l5.name}x{l6.name} k={k} positive, right length",
                      len(env) == k and all(x > 0 for x in env)) \
                      if (k == 5 and l6 == L6.LEGATO) else None
                assert len(env) == k and all(x > 0 for x in env)
    # mean duration multiplier tracks the articulation's own scale
    env = L.duration_envelope(8, L5.DRIFT, L6.STACCATO, random.Random(1))
    m = sum(env) / len(env)
    check("conv: mean tracks articulation dur scale",
          abs(m - L.ARTICS[L6.STACCATO].dur) < 0.15, m)
    check("conv: smoothing preserves length",
          len(L.smooth3([1, 2, 3, 4])) == 4)


# ------------------------------------------------------------ end to end
def test_end_to_end():
    for nodes, dur in ((5, 2), (14, 3), (40, 5)):
        cfg = Config(nodes=nodes, duration=dur)
        rng = random.Random(nodes)
        sol = C.solve(nodes, rng)
        ev, meta = graph_events(cfg, sol, rng)

        check(f"e2e: N={nodes} count within 35% of budget",
              abs(len(ev) - sol.budget) <= max(12, 0.35 * sol.budget),
              (len(ev), sol.budget))
        check(f"e2e: N={nodes} heads inside, spill <= +4s, end <= +12s",
              all(0 <= e.start <= cfg.dur_sec + 4.0 for e in ev)
              and all(e.start + e.dur <= cfg.dur_sec + 12.0 + 1e-6 for e in ev))
        check(f"e2e: N={nodes} carrier present (guaranteed)",
              any(e.cat == int(Cat.SWELL) for e in ev))
        check(f"e2e: N={nodes} durations positive and sane",
              all(0.01 <= e.dur <= 100 for e in ev))
        check(f"e2e: N={nodes} slew in [0,1], pan in [0,1]",
              all(0 <= e.slew <= 1 and 0 <= e.pan <= 1 for e in ev))

    # contour: same articulation is rounder in a DECEL/LARGE context than an
    # ACCEL/SMALL one
    check("contour: DECEL+wide > ACCEL+narrow",
          L.contour_scale(L2.DECEL, L.ROOMS[L3.MIDSIDE])
          > L.contour_scale(L2.ACCEL, L.ROOMS[L3.SMALL]))


if __name__ == "__main__":
    print("tempo:");       test_tempo()
    print("rooms:");       test_rooms()
    print("patterns:");    test_patterns()
    print("convolution:"); test_convolution()
    print("end to end:");  test_end_to_end()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
