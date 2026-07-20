"""Phase 11 tests.  python3 tests/test_p11.py"""
from __future__ import annotations

import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import echoes as E
from orange_fur.alphabet import Cat
from orange_fur.score import Event, fold_index

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])
FOLD = lambda i: fold_index(i, 60, 12)


def _ev(instr=200, cat=Cat.PLUCK, amp=0.4):
    return Event(instr=instr, start=0.0, dur=1.0, index=60, amp=amp,
                 pan=.5, send=.4, slew=.3, cat=int(cat))


def _plan(**kw):
    base = dict(prob=1.0, delay=0.3, fb=0.6, mode="plain", step=0.0)
    base.update(kw)
    return E.EchoPlan(**base)


def test_rotation():
    plan = _plan(rotlen=3)
    cycles = {int(Cat.PLUCK): [201, 202, 203]}
    peaks = {200: 1.0, 201: 0.5, 202: 2.0, 203: 1.0}
    train = E.echo_pattern([_ev()], plan, FOLD, cycles=cycles, peaks=peaks)
    seq = [t.instr for t in train]
    n = len(seq)
    check("rot: generation k sounds on cycle[(k-1) % len]",
          seq == [[201, 202, 203][(k - 1) % 3] for k in range(1, n + 1)],
          seq)
    check("rot: source instrument never reappears unless in the cycle",
          200 not in seq)
    amps = [t.amp for t in train]
    # peak compensation: heard decay follows fb^k -> amp*peak(tgt) == fb^k*peak(src)*amp0
    heard = [a * peaks[i] for a, i in zip(amps, seq)]
    want = [0.4 * plan.fb ** k * peaks[200] for k in range(1, n + 1)]
    check("rot: INSTR_PEAK compensation -- heard decay follows the feedback "
          "curve across timbres",
          all(abs(h - w) < 1e-9 for h, w in zip(heard, want)),
          list(zip(heard, want))[:3])
    train0 = E.echo_pattern([_ev()], _plan(rotlen=0), FOLD,
                            cycles={}, peaks=peaks)
    check("rot: rotlen=0 keeps the source timbre",
          all(t.instr == 200 for t in train0))
    check("rot: category untouched by rotation",
          all(t.cat == int(Cat.PLUCK) for t in train))


def test_rotation_category_isolation():
    """A category with no cycle entry keeps its timbre even in a rotating
    section (e.g. GONG excluded from a drawn pool)."""
    plan = _plan(rotlen=2)
    cycles = {int(Cat.PLUCK): [201, 202]}          # nothing for CLOUD
    train = E.echo_pattern([_ev(instr=400, cat=Cat.CLOUD)], plan, FOLD,
                           cycles=cycles, peaks={})
    check("rot: uncovered category keeps its source instrument",
          all(t.instr == 400 for t in train))


def test_decay_gestures():
    for dg, a, b in (("up", 0.0, 1.0), ("down", 1.0, 0.0)):
        plan = _plan(fb=0.75, dgest=dg)
        early = len(E.echo_pattern([_ev()], plan, FOLD, u=a))
        late = len(E.echo_pattern([_ev()], plan, FOLD, u=b))
        check(f"gesture: '{dg}' trains lengthen toward the right end",
              late > early, (early, late))
    plan = _plan(fb=0.75, dgest="arch")
    mid = len(E.echo_pattern([_ev()], plan, FOLD, u=0.5))
    edge = len(E.echo_pattern([_ev()], plan, FOLD, u=0.0))
    check("gesture: 'arch' peaks mid-section", mid > edge, (edge, mid))
    check("gesture: 'flat' is the Phase 9 behavior",
          len(E.echo_pattern([_ev()], _plan(fb=0.75), FOLD, u=0.7))
          == E.n_repeats(_plan(fb=0.75)))
    plan = _plan(fb=0.42, dgest="down")     # tiny trains stay >= 1
    check("gesture: repeat count clamped to [1, MAX]",
          1 <= len(E.echo_pattern([_ev()], plan, FOLD, u=1.0))
          <= E.MAX_REPEATS)


def test_stream_discipline():
    """draw_cycles consumes an identical number of draws whatever the pools
    contain -- the RNG stream cannot depend on emitted content."""
    plan = _plan(rotlen=3)
    full = {Cat.PLUCK: [201, 202], Cat.CLOUD: [400], Cat.GONG: [300]}
    empty = {Cat.PLUCK: [], Cat.CLOUD: [], Cat.GONG: []}
    r1, r2 = random.Random(5), random.Random(5)
    E.draw_cycles(r1, plan, full)
    E.draw_cycles(r2, plan, empty)
    check("stream: cycle draws independent of pool contents",
          r1.random() == r2.random())
    r3, r4 = random.Random(9), random.Random(9)
    E.draw_cycles(r3, _plan(rotlen=0), full)
    E.draw_cycles(r4, _plan(rotlen=0), empty)
    check("stream: non-rotating sections consume the same (zero) draws",
          r3.random() == r4.random())


def test_e2e():
    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "10",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    tok_re = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")
    r1 = run("--out", "/tmp/p11a.wav")
    tok = tok_re.search(r1.stdout).group(1)
    run("--out", "/tmp/p11b.wav", "--replay", tok)
    a = re.sub(r"-o \S+", "-o X", Path("/tmp/p11a.csd").read_text())
    b = re.sub(r"-o \S+", "-o X", Path("/tmp/p11b.csd").read_text())
    check("e2e: replay determinism with rotation draws in the stream", a == b)
    # rotation reaches the report in a reasonable fraction of sections
    seen = 0
    for _ in range(6):
        r = run()
        seen += len(re.findall(r"rot\(\d\)", r.stdout))
    check("e2e: rotating sections appear in reports (~35% of sections)",
          seen >= 1, seen)


if __name__ == "__main__":
    print("rotation:");         test_rotation()
    print("category isolation:"); test_rotation_category_isolation()
    print("decay gestures:");   test_decay_gestures()
    print("stream discipline:"); test_stream_discipline()
    print("e2e:");              test_e2e()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
