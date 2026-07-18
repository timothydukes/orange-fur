"""
constraints.py -- the axiom/rule solver and the category solver.

THE KEY FACTORISATION. The constraints split cleanly into two groups that must
be solved in two different places, and seeing this is what makes the solver
cheap:

  DERIVATION constraints  -- terminal supply, no dead nodes, expansion band.
    These depend on the rules and the axiom, so testing one costs a full
    derivation (1.6 s at N=300). Few attempts affordable.

  CATEGORY constraints    -- "gongs are rare", "partials are together",
    "clouds are sparse", terminal diversity.
    These look like they depend on the string, but they do not depend on the
    RULES. The derivation hands us a sequence of terminal OCCURRENCES; the
    question is only which CATEGORY each of the N terminal symbols gets. That is
    a separate assignment problem over N symbols, evaluated against a fixed
    sequence -- no re-derivation, thousands of trials affordable.

  And it inverts nicely. We do not assign a category and then hope its
  occurrences cluster. We MEASURE each terminal symbol's occurrence pattern in
  the derived string, and then hand the clustered symbols to PARTIAL and the
  dispersed ones to CLOUD. "Partials are together" and "clouds are sparse" then
  hold by construction rather than by rejection sampling.

RELAXATION LADDER, in the order specified:
  1. increase the number of note events (budget may exceed N**2)
  2. partials may be arbitrary   (drop the clustering requirement)
  3. gongs may be common         (drop the rarity requirement)
  4. clouds may be arbitrary     (drop the dispersion requirement)
  5. terminal homogeneity        (drop the diversity requirement)
  6. dead nodes allowed, OR double N and halve note density
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field

from .alphabet import Cat, Waveform, is_nonterminal, terminal_index
from .graph import System, Terminal, gen_system, run

# Targets.
GONG_MIN_SHARE = 0.012       # ...but gongs are EVER PRESENT: rare != absent
GONG_MAX_SHARE = 0.06        # gongs are rare: <= 6% of note events
MIN_CATS_PRESENT = 5         # terminal diversity: at least this many categories
TERMINAL_SUPPLY_MIN = 1.05   # terminals must exceed the budget
EXPANSION_BAND = (1.2, 12.0) # terminals / budget must land in here

RELAXATIONS = [
    "more_notes",        # 1
    "partials_free",     # 2
    "gongs_common",      # 3
    "clouds_free",       # 4
    "homogeneous",       # 5
    "dead_nodes",        # 6
]


@dataclass
class Solution:
    system: System
    budget: int
    relaxed: list[str] = field(default_factory=list)
    report: dict = field(default_factory=dict)


# ------------------------------------------------------------------ metrics
def occurrence_stats(sys: System) -> dict[int, dict]:
    """Per terminal symbol: how many times it occurs and how BURSTY it is.

    Burstiness B = (sd - mean) / (sd + mean) over the gaps between successive
    occurrences (Goh & Barabasi). B -> +1 is clustered/bursty, B -> -1 is
    regular, B ~ 0 is Poisson. This is the number that decides which symbols
    become partials (clustered) and which become clouds (dispersed).
    """
    n = sys.n
    pos: dict[int, list[int]] = {}
    for idx, sym in enumerate(sys.string):
        if not is_nonterminal(sym, n):
            pos.setdefault(terminal_index(sym, n), []).append(idx)

    out: dict[int, dict] = {}
    for t in range(n):
        p = pos.get(t, [])
        if len(p) < 3:
            out[t] = {"count": len(p), "burst": 0.0, "pos": p}
            continue
        gaps = [p[i + 1] - p[i] for i in range(len(p) - 1)]
        m = statistics.fmean(gaps)
        sd = statistics.pstdev(gaps)
        burst = (sd - m) / (sd + m) if (sd + m) > 0 else 0.0
        out[t] = {"count": len(p), "burst": burst, "pos": p}
    return out


# --------------------------------------------------------- category solver
def solve_categories(sys: System, rng: random.Random,
                     relaxed: list[str]) -> list[Terminal]:
    """Assign a category to each of the N terminal symbols.

    Solved BY CONSTRUCTION from the measured occurrence statistics, not by
    rejection sampling:

      GONG    -> the RAREST symbols, so gongs are rare no matter what the string
                 did. (Rarity is a property of occurrence count, so we pick the
                 symbols that already occur least.)
      PARTIAL -> the most CLUSTERED symbols, so partials arrive together.
      TCLOUD  -> also clustered (a tuned partial cloud is a bank too).
      CLOUD   -> the most DISPERSED symbols, so clouds stay sparse.
      SWELL   -> mid-frequency, long-gap symbols: the sparse-score carrier.
      PLUCK   -> whatever is left.
    """
    n = sys.n
    st = occurrence_stats(sys)
    order_by_count = sorted(range(n), key=lambda t: st[t]["count"])
    order_by_burst = sorted(range(n), key=lambda t: -st[t]["burst"])

    cats: dict[int, Cat] = {}

    # ---- gongs: the rarest symbols ------------------------------------
    total_occ = sum(st[t]["count"] for t in range(n)) or 1
    if "gongs_common" in relaxed:
        n_gong = max(1, int(0.20 * n))
        for t in rng.sample(range(n), n_gong):
            cats[t] = Cat.GONG
    else:
        # Rare, but PRESENT. The first version took the rarest symbols outright
        # and produced runs with 0% gongs -- which is not "gongs are rare", it is
        # "there are no gongs", and the spec says gongs and metal pipes are ever
        # present. So we walk up from the rarest symbols that actually OCCUR
        # until the gong share reaches the floor, and stop before it passes the
        # ceiling.
        budgeted = 0.0
        for t in order_by_count:
            c = st[t]["count"]
            if c == 0:
                continue                   # a symbol that never occurs is not a gong
            share = c / total_occ
            if budgeted >= GONG_MIN_SHARE and budgeted + share > GONG_MAX_SHARE:
                break
            cats[t] = Cat.GONG
            budgeted += share
            if budgeted >= GONG_MAX_SHARE:
                break
        if not cats:                       # degenerate: one gong, the commonest
            cats[order_by_count[-1]] = Cat.GONG

    # ---- partials + tuned clouds: the most clustered -------------------
    free = [t for t in range(n) if t not in cats]
    if "partials_free" in relaxed:
        rng.shuffle(free)
        clustered = free
    else:
        clustered = [t for t in order_by_burst if t in set(free)]

    n_partial = max(1, int(0.34 * len(free)))
    n_tcloud = max(1, int(0.16 * len(free)))
    for t in clustered[:n_partial]:
        cats[t] = Cat.PARTIAL
    for t in clustered[n_partial:n_partial + n_tcloud]:
        cats[t] = Cat.TCLOUD

    # ---- clouds: the most dispersed ------------------------------------
    free = [t for t in range(n) if t not in cats]
    if "clouds_free" in relaxed:
        rng.shuffle(free)
        dispersed = free
    else:
        dispersed = sorted(free, key=lambda t: st[t]["burst"])
    n_cloud = max(1, int(0.42 * len(free)))
    for t in dispersed[:n_cloud]:
        cats[t] = Cat.CLOUD

    # ---- swells and plucks --------------------------------------------
    # SWELL is taken from the remaining symbols that occur MOST, not from
    # whatever happens to be left in index order. The swell is the carrier: it is
    # what makes a 100-note, 40-minute score legible rather than 40 minutes of
    # silence with events in it. An earlier version handed SWELL the leftovers
    # and produced runs where the section-weighted selection picked no swells at
    # all. The carrier is not allowed to be a rounding error.
    free = [t for t in range(n) if t not in cats]
    free.sort(key=lambda t: -st[t]["count"])
    n_swell = max(1, int(0.35 * len(free))) if free else 0
    for t in free[:n_swell]:
        cats[t] = Cat.SWELL
    for t in free[n_swell:]:
        cats[t] = Cat.PLUCK

    for t in range(n):
        cats.setdefault(t, Cat.PLUCK)

    return [
        Terminal(index=t, cat=cats[t],
                 wave=rng.choice(list(Waveform)) if cats[t] == Cat.TCLOUD else None)
        for t in range(n)
    ]


# ------------------------------------------------------------------ checks
def check(sys: System, budget: int, relaxed: list[str]) -> dict:
    n = sys.n
    tc = sys.terminal_count()
    dead = sys.dead_nodes()
    ratio = tc / budget if budget else 0.0

    st = occurrence_stats(sys)
    total_occ = sum(st[t]["count"] for t in range(n)) or 1
    by_cat: dict[Cat, int] = {}
    for t in sys.terminals:
        by_cat[t.cat] = by_cat.get(t.cat, 0) + st[t.index]["count"]
    gong_share = by_cat.get(Cat.GONG, 0) / total_occ
    cats_present = sum(1 for c in Cat if by_cat.get(c, 0) > 0)

    part_burst = statistics.fmean(
        [st[t.index]["burst"] for t in sys.terminals if t.cat == Cat.PARTIAL]
        or [0.0])
    cloud_burst = statistics.fmean(
        [st[t.index]["burst"] for t in sys.terminals if t.cat == Cat.CLOUD]
        or [0.0])

    hard = {
        "terminal_supply": tc >= budget * TERMINAL_SUPPLY_MIN,
        "no_dead_nodes": (not dead) or ("dead_nodes" in relaxed),
        "expansion_band": EXPANSION_BAND[0] <= ratio <= EXPANSION_BAND[1],
    }
    soft = {
        # "terminal homogeneity" (rung 5) is what gives up on having one of
        # every category, so the swell carrier is released on that rung too --
        # at N=2 there are two terminal symbols and you cannot have a swell AND
        # a gong AND partials. Without this the ladder could never terminate at
        # small N: it would climb every rung and still report failure.
        "swell_present": by_cat.get(Cat.SWELL, 0) > 0
                         or "homogeneous" in relaxed,
        "gongs_rare": (GONG_MIN_SHARE <= gong_share <= GONG_MAX_SHARE)
                      or "gongs_common" in relaxed,
        "diversity": cats_present >= MIN_CATS_PRESENT or "homogeneous" in relaxed,
        "partials_clustered": part_burst > cloud_burst or "partials_free" in relaxed,
        "clouds_dispersed": cloud_burst < part_burst or "clouds_free" in relaxed,
    }
    return {
        "hard": hard, "soft": soft,
        "hard_ok": all(hard.values()), "soft_ok": all(soft.values()),
        "terminals": tc, "budget": budget, "ratio": ratio,
        "dead": len(dead), "gong_share": gong_share,
        "cats_present": cats_present,
        "partial_burst": part_burst, "cloud_burst": cloud_burst,
        "by_cat": {c.name: by_cat.get(c, 0) for c in Cat},
    }


def solve(n: int, rng: random.Random, max_attempts: int = 6) -> Solution:
    """Generate-and-test on the derivation; solve categories by construction.

    The relaxation ladder is climbed only when the hard constraints cannot be
    met. Each rung that gets used is recorded and reported -- a run that had to
    relax something is a run whose character was compromised, and you should be
    told, not have it hidden.
    """
    budget = n * n
    relaxed: list[str] = []
    best: Solution | None = None

    rung = 0
    for attempt in range(max_attempts * (len(RELAXATIONS) + 1)):
        sys_ = run(gen_system(n, rng))
        sys_.terminals = solve_categories(sys_, rng, relaxed)
        rep = check(sys_, budget, relaxed)

        cand = Solution(system=sys_, budget=budget, relaxed=list(relaxed),
                        report=rep)
        if rep["hard_ok"] and rep["soft_ok"]:
            return cand

        # Keep the best candidate seen. Rank by (hard, soft, fewest relaxations)
        # -- an earlier version kept the first hard-passing candidate and never
        # replaced it, so a later candidate that passed BOTH hard and soft was
        # thrown away, and the run was reported as unrelaxed while quietly
        # violating its soft constraints.
        def rank(x: Solution) -> tuple:
            return (x.report["hard_ok"], x.report["soft_ok"], -len(x.relaxed))

        if best is None or rank(cand) > rank(best):
            best = cand

        if (attempt + 1) % max_attempts == 0 and rung < len(RELAXATIONS):
            # Climb one rung. "more_notes" is first: if the string simply cannot
            # supply N**2 terminals, take the notes it can supply rather than
            # forcing the rules into a shape that satisfies arithmetic and
            # nothing else.
            relaxed.append(RELAXATIONS[rung])
            if RELAXATIONS[rung] == "more_notes":
                budget = min(budget, max(1, sys_.terminal_count() - 1))
            rung += 1

    assert best is not None
    return best
