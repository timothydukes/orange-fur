"""Fit REVP / CAL by rendering a grid and averaging over repeats.
Phase 0 development tooling; not part of the shipped runtime path."""
import itertools, math, random, statistics, sys
from pathlib import Path

from orange_fur import score as S
from orange_fur.config import Config
from orange_fur.orc import build_orc, build_csd
from orange_fur import render as R

OUT = Path("out"); OUT.mkdir(exist_ok=True)


def one(nodes, dur, space, wet, air, tag):
    cfg = Config(duration=dur, nodes=nodes, space=space, air=air, wetdry=wet,
                 draft=True, out=OUT / f"fit_{tag}.wav", seed=tag)
    rng = random.Random(cfg.entropy)
    ev = S.placeholder_events(cfg, rng)
    st = S.compensate(ev, cfg)
    csd = build_csd(cfg, build_orc(cfg, st["ceiling"]),
                    S.build_sco(cfg, ev, st))
    p = R.write_csd(cfg, csd)
    R.run(cfg, p)
    m = R.measure_peak(OUT / cfg.out.name)
    peak = m["peak"]
    return 20 * math.log10(peak) if peak > 0 else -99.0


CONFIGS = [(20, 2, s, w, 0.3) for s, w in
           [(0.0, 0.2), (0.0, 0.8), (0.5, 0.5), (1.0, 0.2), (1.0, 0.8)]]
REPEATS = 3

for revp in [0.5, 0.65, 0.8, 1.0]:
    S.REVP = revp
    S.CAL = 1.0
    rows = []
    for i, c in enumerate(CONFIGS):
        errs = [one(*c, f"r{revp}_{i}_{k}") + 1.0 for k in range(REPEATS)]
        rows.append((c[2], c[3], statistics.mean(errs), max(errs)))
    allerr = [r[2] for r in rows]
    spread = max(r[3] for r in rows) - min(allerr)
    print(f"REVP={revp:.2f}  " + "  ".join(
        f"s{r[0]:.1f}/w{r[1]:.1f}:{r[2]:+5.1f}" for r in rows) +
        f"   | mean {statistics.mean(allerr):+.2f}  spread {spread:.1f} dB")
