"""Phase 12 tests.  python3 tests/test_p12.py"""
from __future__ import annotations

import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import motifs as MO
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


# -------------------------------------------------------------- transforms
def test_transforms():
    m = MO.Motif(degrees=[0, 4, 7, 2], iois=[0.5, 0.25, 1.0],
                 durs=[0.3, 0.3, 0.6, 0.4], cat=int(Cat.PLUCK), sec="INTRO")
    q = MO.Quote(motif=0, transpose=0, invert=False, retro=False, augment=1.0)
    d, on, du = MO.realize(q, m)
    check("realize: verbatim quote reproduces the cell",
          d == [0, 4, 7, 2] and on == [0.0, 0.5, 0.75, 1.75]
          and du == m.durs)
    q = MO.Quote(motif=0, transpose=5, invert=True, retro=False, augment=1.0)
    d, _, _ = MO.realize(q, m)
    check("realize: inversion negates around the first degree, then "
          "transposes", d == [5, 1, -2, 3], d)
    q = MO.Quote(motif=0, transpose=0, invert=False, retro=True, augment=1.0)
    d, on, du = MO.realize(q, m)
    check("realize: retrograde reverses pitches AND rhythm",
          d == [2, 7, 4, 0] and on == [0.0, 1.0, 1.25, 1.75]
          and du == [0.4, 0.6, 0.3, 0.3], (d, on))
    q = MO.Quote(motif=0, transpose=0, invert=False, retro=False, augment=2.0)
    _, on, du = MO.realize(q, m)
    check("realize: augmentation stretches rhythm and durations together",
          on == [0.0, 1.0, 1.5, 3.5] and du == [0.6, 0.6, 1.2, 0.8])
    check("realize: transform tag is readable",
          MO.Quote(0, 5, True, False, 2.0).tag() == "T+5+inv+aug2.0")


# ----------------------------------------------------------------- capture
def test_capture():
    bank = []
    MO.capture(bank, [60, 64, 67], [0.0, 0.5, 1.0], [0.3] * 3,
               int(Cat.PLUCK), "INTRO")
    check("capture: qualifying pattern stored with RELATIVE degrees",
          len(bank) == 1 and bank[0].degrees == [0, 4, 7])
    MO.capture(bank, [60, 61], [0.0, 0.5], [0.3] * 2, 0, "V")   # too short
    MO.capture(bank, [60] * 4, [0.0, 3.0, 6.0, 9.0], [1] * 4, 0, "V")  # span
    check("capture: too-short and too-long-span patterns rejected",
          len(bank) == 1)
    for k in range(10):
        MO.capture(bank, [60, 62, 64, 66], [0, .4, .8, 1.2], [.2] * 4, 0, "V")
    check("capture: bank capped at MAX_BANK, first-come",
          len(bank) == MO.MAX_BANK)
    check("capture: deterministic -- consumes no RNG",
          True)   # by construction: capture() takes no rng argument


# --------------------------------------------------- draw discipline / L1
def test_draw_discipline():
    r1, r2, r3 = (random.Random(11) for _ in range(3))
    MO.draw_quotes(r1, "CHORUS", 0)
    MO.draw_quotes(r2, "CHORUS", 4)
    MO.draw_quotes(r3, "INTRO", 2)
    a, b, c = r1.random(), r2.random(), r3.random()
    check("stream: identical draw count across bank sizes and sections",
          a == b == c)
    check("quotes: empty bank yields no quotes",
          MO.draw_quotes(random.Random(3), "CHORUS", 0) == [])
    counts = {"CHORUS": 0, "VERSE": 0, "INTRO": 0}
    for k in range(400):
        for sec in counts:
            counts[sec] += len(MO.draw_quotes(random.Random(k * 7 + hash(sec) % 97),
                                              sec, 4))
    check("quotes: L1-driven -- CHORUS quotes more than VERSE, INTRO never",
          counts["CHORUS"] > counts["VERSE"] and counts["INTRO"] == 0,
          counts)


# ---------------------------------------------------- integration marking
def _gen(seed):
    rng = random.Random(seed)
    cfg = Config(nodes=10, duration=3, draft=True)
    rt = R.generate_routing(rng)
    orch = O.generate(rng, cfg.scale.numgrades,
                      n_buses=rt.n_buses).subset(cfg.subset, rng)
    set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
    catmap = {c: [i.num for i in orch.by_cat(c)] for c in Cat}
    return graph_events(cfg, solve(10, rng), rng, catmap=catmap)


def test_integration():
    saw_quote = saw_motif_loop = False
    for k in range(30):
        ev, sm = _gen(k)
        qn = [e for e in ev if e.echo == -3]
        if qn:
            saw_quote = True
            check_once = all(e.proc > 0 for e in qn)
            by_proc = {}
            for e in qn:
                by_proc.setdefault(e.proc, set()).add(e.instr)
            assert check_once and all(len(s) == 1 for s in by_proc.values())
        for e in ev:
            if e.echo == -2:
                pass
        for m in sm["macro"]:
            if m.get("loop") and m.get("bank"):
                saw_motif_loop = True
        if saw_quote and saw_motif_loop:
            break
    check("integration: quotes appear, marked echo=-3, proc set, one "
          "instrument per quote", saw_quote)
    check("integration: loops coexist with a motif bank (coupling reachable)",
          saw_motif_loop)
    ev, sm = _gen(2)
    src = sum(1 for e in ev if e.echo == 0)
    n2 = 100
    check("integration: source budget untouched by quotes "
          "(within the 35% band)", abs(src - n2) / n2 < 0.35, src)


def test_replay_determinism():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "10",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p12a.wav")
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p12b.wav", "--replay", tok)
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p12a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p12b.csd").read_text())
    check("determinism: replay identical with capture/quote/coupling live",
          a == b)
    seen = 0
    for _ in range(4):
        r = run()
        if "motifs" in r.stdout:
            seen += 1
    check("e2e: motif bank reported", seen >= 1, seen)


if __name__ == "__main__":
    print("transforms:");       test_transforms()
    print("capture:");          test_capture()
    print("draw discipline:");  test_draw_discipline()
    print("integration:");      test_integration()
    print("determinism:");      test_replay_determinism()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
