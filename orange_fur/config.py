"""
config.py -- the single run-configuration object passed to every generator.

Everything downstream (graph, layers, orchestra, score, routing, render) reads
this and nothing else, so a run is fully described by one struct.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from .tuning import Scale, load_scl, DEFAULT_BASEFREQ, DEFAULT_BASEKEY

# Render quality presets.
#   full : the target format. ksmps=1 is required for the single-sample
#          feedback / PLL / dirty-sync chains planned for Phase 3-4.
#   draft: iteration only. ksmps=16 will AUDIBLY change any instrument whose
#          feedback loop is sample-accurate, so draft is for structure/level
#          checking, not for judging timbre.
QUALITY = {
    "full":  {"sr": 96000, "ksmps": 1,  "format": "float"},
    "draft": {"sr": 48000, "ksmps": 16, "format": "float"},
}

DURATION_MIN = 2.0
DURATION_MAX = None    # no cap, per spec
NODES_MIN = 2
NODES_MAX = 300
SUBSET_MIN = 10.0
SUBSET_MAX = 100.0


@dataclass
class Config:
    duration: float = 5.0          # minutes
    nodes: int = 10                # graph nodes; note count == nodes**2
    space: float = 0.5             # 0..1  room size macro
    air: float = 0.25              # 0..1  noise floor + noise/insect swells
    wetdry: float = 0.35           # 0..1  global dry<->effects-return crossfade
    subset: float = 50.0           # 10..100 percent of the generated orchestra used
    sections: int = 0              # L1 section count; 0 = auto (drawn from duration)
    cost_cap: float = 0.0          # oscili-seconds; 0 = auto (1200 * duration)
    echo: float = 1.0              # Phase 9: echo probability scale; 0 = off
    fields: int = 1                # Phase 13: harmonic-field snapping; 0 = off
    normalize: float = -3.0        # target peak ceiling, dBFS (see note in score.py)
    draft: bool = False
    seed: str = ""                 # FILENAME TAG ONLY -- does not constrain the RNG
    scl: Path | None = None
    basefreq: float = DEFAULT_BASEFREQ
    basekey: int = DEFAULT_BASEKEY
    out: Path | None = None
    keep_csd: bool = True
    csound: str = "csound"
    replay: int | None = None      # Phase 7: inject a prior run's entropy

    # derived
    scale: Scale = field(init=False)
    entropy: int = field(init=False)

    def __post_init__(self) -> None:
        self.scale = load_scl(self.scl, self.basefreq, self.basekey)

        # INTERPRETIVE DECISION: `seed` is a label, not a seed. Per spec the
        # program is non-deterministic; generators always draw from OS entropy.
        # If the user supplies --seed it is used ONLY in the output filename.
        # PHASE 7: --replay injects a previous run's 64-bit entropy and
        # regenerates that piece exactly (same code version required -- any
        # change to the RNG draw order changes what a seed means). The value
        # is printed in the report/manifest as version:hex, the replay token.
        self.entropy = (self.replay if self.replay is not None
                        else int.from_bytes(os.urandom(8), "big"))
        if not self.seed:
            # the default tag derives from the entropy: a replayed piece gets
            # the same default filename family, and the run's one 64-bit seed
            # is the program's ONLY entropy source
            self.seed = f"{self.entropy:016x}"[:8]

        if self.out is None:
            self.out = Path(f"orange_fur_{self.seed}.wav")
        self.out = Path(self.out)

    @property
    def sr(self) -> int:
        return QUALITY["draft" if self.draft else "full"]["sr"]

    @property
    def ksmps(self) -> int:
        return QUALITY["draft" if self.draft else "full"]["ksmps"]

    @property
    def kr(self) -> float:
        return self.sr / self.ksmps

    @property
    def dur_sec(self) -> float:
        return self.duration * 60.0

    @property
    def note_count(self) -> int:
        """Strictly N**2 per spec: the lexicographic traversal of all ordered
        node pairs, each pair emitting its rewritten string."""
        return self.nodes ** 2

    @property
    def csd_path(self) -> Path:
        return self.out.with_suffix(".csd")

    def summary(self) -> str:
        density = self.note_count / self.dur_sec
        return (
            f"orange fur / seed {self.seed}\n"
            f"  duration   {self.duration:g} min ({self.dur_sec:.0f} s)\n"
            f"  nodes      {self.nodes}  ->  {self.note_count} notes"
            f"  ({density:.1f} notes/s mean)\n"
            f"  scale      {self.scale.name} [{self.scale.source}]"
            f"  {self.scale.numgrades} grades, 1/1 = {self.scale.basefreq:.3f} Hz"
            f" @ key {self.scale.basekey}\n"
            f"  space {self.space:g}  air {self.air:g}  wet/dry {self.wetdry:g}"
            f"  subset {self.subset:g}%\n"
            f"  render     "
            f"{'DRAFT' if self.draft else 'RELEASE (96 kHz oversampled -> 48 kHz)'}"
            f"  sr={self.sr} ksmps={self.ksmps} 32-bit float\n"
            f"  output     {self.out}"
        )
