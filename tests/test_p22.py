"""Phase 22 tests.  python3 tests/test_p22.py"""
from __future__ import annotations

import random
import re
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import state as ST
from orange_fur.config import Config
from orange_fur.constraints import solve
from orange_fur.layers import ROOMS, L3, section_room
from orange_fur.score import graph_events

FAILURES = []
ROOT = str(Path(__file__).resolve().parents[1])


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ------------------------------------------------------------------- state
def test_state():
    a = ST.draw_state(random.Random(3)); a.integrate(600, [0, 200, 400])
    b = ST.draw_state(random.Random(3)); b.integrate(600, [0, 200, 400])
    check("state: deterministic", a.obs_at(123.4) == b.obs_at(123.4))
    obs = [a.obs_at(t) for t in range(0, 600, 5)]
    flat = [o for row in obs for o in row]
    check("state: observables in [0, 1]", all(0 <= o <= 1 for o in flat))
    d = [abs(obs[i + 1][k] - obs[i][k])
         for i in range(len(obs) - 1) for k in range(4)]
    check("state: slow (mean 5 s delta < 0.15)",
          statistics.fmean(d) < 0.15, round(statistics.fmean(d), 4))
    moved = [max(o[k] for o in obs) - min(o[k] for o in obs)
             for k in range(4)]
    check("state: not frozen (every dim moves over 10 min)",
          all(m > 0.1 for m in moved), [round(m, 2) for m in moved])
    r1, r2 = random.Random(8), random.Random(8)
    ST.draw_state(r1); ST.draw_state(r2)
    check("state: fixed draw layout", r1.random() == r2.random())
    check("state: parse all / list / off",
          ST.parse_state("all") == frozenset(ST.CONSUMERS)
          and ST.parse_state("air,rooms") == frozenset({"air", "rooms"})
          and ST.parse_state(None) == frozenset())
    try:
        ST.parse_state("nonsense")
        check("state: unknown consumer rejected", False)
    except ValueError:
        check("state: unknown consumer rejected", True)


# ------------------------------------------------------------------- rooms
def test_rooms_tilt():
    class N:
        def __init__(self, l3): self.l3 = l3
    # clear majority: tilt must not change the winner
    nodes = [N(L3.SMALL)] * 5 + [N(L3.LARGE)]
    for t in (0.0, 0.3, 0.7, 0.99):
        if section_room(nodes, 0, 6, tilt=t) is not ROOMS[L3.SMALL]:
            check("rooms: clear majorities immune to tilt", False, t)
            break
    else:
        check("rooms: clear majorities immune to tilt", True)
    # near-tie: tilt selects among candidates deterministically
    nodes = [N(L3.SMALL)] * 3 + [N(L3.LARGE)] * 3
    r_lo = section_room(nodes, 0, 6, tilt=0.05)
    r_hi = section_room(nodes, 0, 6, tilt=0.95)
    check("rooms: tilt rotates near-tie selection", r_lo is not r_hi,
          (r_lo.l3, r_hi.l3))
    check("rooms: tilt=None is the original rule",
          section_room(nodes, 0, 6) is ROOMS[nodes[0].l3])


# ---------------------------------------------------------------- pipeline
def _events(seed, state, nodes=16, dur=3):
    cfg = Config(duration=dur, nodes=nodes, state=state)
    rng = random.Random(seed)
    return graph_events(cfg, solve(nodes, rng), rng)


def test_pipeline():
    # zero draw-stream difference across --state values
    r1, r2 = random.Random(3), random.Random(3)
    graph_events(Config(duration=3, nodes=16, state=None),
                 solve(16, r1), r1)
    graph_events(Config(duration=3, nodes=16, state="all"),
                 solve(16, r2), r2)
    check("pipe: --state adds zero draws (RNG-state equality on vs off)",
          r1.random() == r2.random())
    ev_off, m_off = _events(5, None)
    ev_air, m_air = _events(5, "air")
    check("pipe: air-only leaves the event skeleton identical",
          [(e.start, e.instr, e.amp) for e in ev_off]
          == [(e.start, e.instr, e.amp) for e in ev_air])
    check("pipe: air rows all-ones off, modulated on",
          all(m == 1.0 for _, m in m_off["air_rows"])
          and any(m != 1.0 for _, m in m_air["air_rows"]))
    check("pipe: air multipliers in band 0.35-1.65",
          all(0.34 <= m <= 1.66 for _, m in m_air["air_rows"]),
          m_air["air_rows"])
    # density consumer: culled note count varies with the state across
    # seeds (same seed on/off differ when o1 pulls the fraction down/up)
    diffs = 0
    for seed in range(6):
        a, _ = _events(seed, None)
        b, _ = _events(seed, "density")
        na = sum(1 for e in a if e.echo == 0)
        nb = sum(1 for e in b if e.echo == 0)
        if na != nb:
            diffs += 1
    check("pipe: density consumer changes source-note counts (>=3/6 seeds)",
          diffs >= 3, diffs)
    # register consumer: pitch ambit tracks o2
    amb = []
    for seed in range(6):
        a, _ = _events(seed, None)
        b, _ = _events(seed, "register")
        span = lambda ev: (max(e.index for e in ev if e.echo == 0)
                           - min(e.index for e in ev if e.echo == 0))
        amb.append(span(a) != span(b))
    check("pipe: register consumer moves the ambit (>=2/6 seeds)",
          sum(amb) >= 2, sum(amb))
    # fields consumer: field selection shifts vs off in at least some seeds
    fdiff = 0
    for seed in range(6):
        _, ma = _events(seed, None)
        _, mb = _events(seed, "fields")
        if ma["sec_fields"] != mb["sec_fields"]:
            fdiff += 1
    check("pipe: fields consumer shifts field selection (>=2/6 seeds)",
          fdiff >= 2, fdiff)
    # macro_log carries observables
    check("pipe: macro log carries per-section observables",
          all(len(m.get("state", [])) == 4 for m in m_air["macro"]))


# --------------------------------------------------------------------- e2e
def _run(*extra, timeout=900):
    return subprocess.run(
        [sys.executable, "-m", "orange_fur", "--nodes", "12",
         "--duration", "2", "--draft", *extra],
        capture_output=True, text=True, timeout=timeout, cwd=ROOT)


def test_e2e():
    r = _run("--dry-run", "--out", "/tmp/p22a.wav")
    tok = re.search(r"replay\s+(\S+)", r.stdout).group(1)
    r2 = _run("--dry-run", "--replay", tok, "--state", "--out",
              "/tmp/p22b.wav")
    check("e2e: bare --state = all (report lists all five)",
          "air,density,fields,register,rooms" in r2.stdout,
          r2.stdout[-300:])
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p22a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p22b.csd").read_text())
    check("e2e: one token, state on and off (remix knob; csd differs "
          "with state on)", a != b)
    r3 = _run("--dry-run", "--replay", tok, "--state", "all",
              "--out", "/tmp/p22c.wav")
    c = re.sub(r"-o \S+", "-o X", Path("/tmp/p22c.csd").read_text())
    check("e2e: --state and --state all identical", b == c)
    check("e2e: instr 90 reads the air table (giAir scan in csd)",
          "giAir" in a and "f 903" in a)
    r4 = _run("--state", "--out", "/tmp/p22d.wav", timeout=900)
    wp = Path("/tmp/p22d.wav")
    check("e2e: full render with --state completes",
          r4.returncode == 0 and wp.exists() and wp.stat().st_size > 10000
          and wp.read_bytes()[:4] == b"RIFF",
          r4.stderr[-200:] if r4.returncode else "")
    r5 = _run("--dry-run", "--state", "bogus", "--out", "/tmp/p22e.wav")
    check("e2e: unknown consumer is a clear error", r5.returncode != 0
          and "unknown --state consumer" in (r5.stderr + r5.stdout))


if __name__ == "__main__":
    print("state:");    test_state()
    print("rooms:");    test_rooms_tilt()
    print("pipeline:"); test_pipeline()
    print("e2e:");      test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
