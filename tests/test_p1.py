"""Phase 1 tests.  python3 tests/test_p1.py"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import graph as G
from orange_fur import constraints as C
from orange_fur.alphabet import Cat, L1, is_nonterminal
from orange_fur.config import Config
from orange_fur.score import graph_events, compensate
from orange_fur.sections import gen_sections, partition_nodes

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ---------------------------------------------------------- derivation
def test_derivation():
    # The fast presence-indexed derivation must agree EXACTLY with the obvious
    # one. This is the test that earns the right to use the fast one.
    for n in (2, 3, 5, 10, 25, 40, 60):
        a = G.run(G.gen_system(n, random.Random(n)))
        b = G.run_reference(G.gen_system(n, random.Random(n)))
        check(f"derivation: N={n} fast == reference",
              a.string == b.string and a.fired == b.fired
              and a.pair_marks == b.pair_marks,
              f"|fast|={len(a.string)} |ref|={len(b.string)}")

    for n in (4, 17, 50):
        s = G.run(G.gen_system(n, random.Random(n + 100)))
        check(f"alphabet: N={n} is exactly 2N symbols",
              max(s.string) < 2 * n and len(s.terminals) == n)
        check(f"traversal: N={n} visits all N**2 pairs (self-pairs included)",
              len(s.pair_marks) == n * n, len(s.pair_marks))
        check(f"growth: N={n} length matches the additive arithmetic",
              G.occurrence_lists_ok(s))
        check(f"growth: N={n} string is not multiplicative",
              len(s.string) < len(s.axiom) + 2 * n * n * 6)


# ---------------------------------------------------------- constraints
def test_constraints():
    for n in (2, 6, 20, 60):
        sol = C.solve(n, random.Random(n * 7))
        rep = sol.report
        # HARD
        check(f"hard: N={n} no dead nodes",
              rep["dead"] == 0 or "dead_nodes" in sol.relaxed, rep["dead"])
        check(f"hard: N={n} terminal supply exceeds the N**2 budget",
              rep["terminals"] >= sol.budget, (rep["terminals"], sol.budget))
        check(f"hard: N={n} expansion factor inside the band",
              C.EXPANSION_BAND[0] <= rep["ratio"] <= C.EXPANSION_BAND[1],
              rep["ratio"])
        # SOFT
        check(f"soft: N={n} gongs are RARE but PRESENT",
              (rep["gong_share"] > 0 and rep["gong_share"] <= C.GONG_MAX_SHARE)
              or "gongs_common" in sol.relaxed,
              rep["gong_share"])
        check(f"soft: N={n} terminal diversity (>= {C.MIN_CATS_PRESENT} cats)",
              rep["cats_present"] >= C.MIN_CATS_PRESENT
              or "homogeneous" in sol.relaxed,
              rep["cats_present"])
        # N=2 is the degenerate corner: 2 terminal symbols cannot carry 6
        # categories, so the ladder MUST be climbed and MUST be reported.
        if n == 2:
            check("relax: N=2 is impossible and the ladder says so",
                  len(sol.relaxed) > 0, sol.relaxed)
        check(f"soft: N={n} partials cluster more tightly than clouds",
              rep["partial_burst"] > rep["cloud_burst"]
              or "partials_free" in sol.relaxed,
              f"partial={rep['partial_burst']:.3f} cloud={rep['cloud_burst']:.3f}")

    # The relaxation ladder must be climbed in the specified order.
    check("relax: ladder order is as specified",
          C.RELAXATIONS == ["more_notes", "partials_free", "gongs_common",
                            "clouds_free", "homogeneous", "dead_nodes"],
          C.RELAXATIONS)


# ------------------------------------------------------------ sections
def test_sections():
    for k in (1, 2, 3, 5, 9, 17):
        for trial in range(6):
            seq, trace = gen_sections(k, random.Random(k * 100 + trial))
            check(f"sections: k={k} emits exactly k",
                  len(seq) == k, len(seq)) if trial == 0 else None
            if k >= 2:
                assert seq[0] == L1.INTRO and seq[-1] == L1.OUTRO
    check("sections: anchored intro first, outro last (all k>=2, 6 trials)", True)

    for n, k in ((2, 5), (7, 5), (300, 5), (12, 12)):
        seq, _ = gen_sections(k, random.Random(1))
        parts = partition_nodes(n, seq, random.Random(2))
        covered = sum(hi - lo for lo, hi, _ in parts)
        contiguous = all(parts[i][1] == parts[i + 1][0]
                         for i in range(len(parts) - 1))
        check(f"sections: N={n} k={k} partition is contiguous and covers all nodes",
              covered == n and contiguous and parts[0][0] == 0,
              (covered, n, contiguous))
        check(f"sections: N={n} k={k} no empty section",
              all(hi > lo for lo, hi, _ in parts))


# ------------------------------------------------------------ selection
def test_selection():
    for nodes, dur, secs in ((10, 40, 5), (12, 3, 5), (40, 5, 7), (5, 2, 3)):
        cfg = Config(nodes=nodes, duration=dur, sections=secs)
        rng = random.Random(nodes)
        sol = C.solve(nodes, rng)
        ev, meta = graph_events(cfg, sol, rng)

        check(f"select: N={nodes} note count within 35% of the N**2 budget",
              abs(len(ev) - sol.budget) <= max(12, 0.35 * sol.budget),
              (len(ev), sol.budget))
        check(f"select: N={nodes} onsets sorted; heads inside, spill <= +4s",
              all(0 <= e.start <= cfg.dur_sec + 4.0 for e in ev)
              and all(ev[i].start <= ev[i + 1].start for i in range(len(ev) - 1)))
        check(f"select: N={nodes} every section produced notes",
              all(s["notes"] > 0 for s in meta["sections"]))
        check(f"select: N={nodes} section spans tile the timeline in order",
              all(abs(meta["sections"][i]["t1"] - meta["sections"][i + 1]["t0"]) < 1e-6
                  for i in range(len(meta["sections"]) - 1)))

        cats = {e.cat for e in ev}
        check(f"select: N={nodes} the swell carrier is present (sparse-score rule)",
              int(Cat.SWELL) in cats)

    # The sparse extreme: 100 notes across 40 minutes must still be carried.
    cfg = Config(nodes=10, duration=40)
    rng = random.Random(5)
    sol = C.solve(10, rng)
    ev, _ = graph_events(cfg, sol, rng)
    compensate(ev, cfg)
    swell = [e for e in ev if e.cat == int(Cat.SWELL)]
    longest = max(e.dur for e in ev)
    check("sparse: 100 notes / 40 min has swells with long release",
          len(swell) > 0 and longest > 6.0,
          f"{len(swell)} swells, longest note {longest:.1f}s")


if __name__ == "__main__":
    print("derivation:");  test_derivation()
    print("constraints:"); test_constraints()
    print("sections:");    test_sections()
    print("selection:");   test_selection()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
