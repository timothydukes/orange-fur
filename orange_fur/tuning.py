"""
tuning.py -- Scala (.scl) parsing and conversion to a Csound cpstuni table.

INTERPRETIVE DECISION (scl -> cpstun mapping):
  A Scala file lists `count` pitches ABOVE an implicit 1/1, where the LAST
  entry is the interval of repetition (here 2/1).  Csound's cpstun/cpstuni
  GEN -2 table wants:

      f N 0 size -2  numgrades  interval  basefreq  basekey  r1 r2 ... rG

  where r1..rG are the ratios of the grades INCLUDING the 1/1 and EXCLUDING
  the repeat interval.  So we map:

      numgrades = count                       (12 for werck3_mim)
      interval  = last scl entry              (2.0)
      ratios    = [1.0] + entries[:-1]        (12 values: 1/1 .. 1080.45c)

  This is the standard reading and round-trips: index basekey -> basefreq,
  index basekey+12 -> basefreq*2.

INTERPRETIVE DECISION (base freq / base key):
  Defaults are basekey = 60 (MIDI middle C) and basefreq = 261.6255653
  (12-TET middle C).  Both are overridable from the CLI so a user can
  anchor the scale to A440 or anything else without editing the .scl.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASEKEY = 60
DEFAULT_BASEFREQ = 261.6255653005986  # 12-TET middle C

DATA_DIR = Path(__file__).parent / "data"
DEFAULT_SCL = DATA_DIR / "werck3_mim.scl"


@dataclass(frozen=True)
class Scale:
    name: str
    ratios: tuple[float, ...]   # length == numgrades, starts at 1.0
    interval: float             # repeat interval (2.0 for an octave)
    basefreq: float
    basekey: int
    source: str                 # filename, for provenance comments

    @property
    def numgrades(self) -> int:
        return len(self.ratios)

    def freq(self, index: int) -> float:
        """Python-side mirror of cpstuni(index, table). Used for score-time
        pitch reasoning (spectral routing, bank spacing) without a Csound
        round-trip. Must stay in sync with cpstun's algorithm."""
        g = self.numgrades
        rel = index - self.basekey
        octave, grade = divmod(rel, g)
        return self.basefreq * (self.interval ** octave) * self.ratios[grade]

    def ftable(self, tabnum: int) -> str:
        """Emit the GEN -2 f-statement. Size is rounded up to a power of two;
        GEN -2 does not interpolate, so extra slots are harmless zeros."""
        vals = [
            float(self.numgrades),
            float(self.interval),
            float(self.basefreq),
            float(self.basekey),
            *self.ratios,
        ]
        size = 1
        while size < len(vals):
            size *= 2
        body = " ".join(f"{v:.10g}" for v in vals)
        return f"f {tabnum} 0 {size} -2 {body}"


def _parse_pitch(tok: str) -> float:
    """Scala pitch -> ratio. A token containing '.' is CENTS; a token with
    '/' or a bare integer is a RATIO. This is the Scala spec's rule."""
    tok = tok.strip()
    if "/" in tok:
        num, den = tok.split("/", 1)
        return float(num) / float(den)
    if "." in tok:
        cents = float(tok)
        return 2.0 ** (cents / 1200.0)
    return float(int(tok))  # bare integer ratio, e.g. "2" == 2/1


def load_scl(
    path: str | Path | None = None,
    basefreq: float = DEFAULT_BASEFREQ,
    basekey: int = DEFAULT_BASEKEY,
) -> Scale:
    path = Path(path) if path else DEFAULT_SCL
    text = path.read_text(encoding="utf-8", errors="replace")

    lines: list[str] = []
    for raw in text.splitlines():
        if raw.lstrip().startswith("!"):   # comment
            continue
        lines.append(raw.strip())

    # First non-comment line = description (may be empty but must exist).
    if not lines:
        raise ValueError(f"{path}: empty scale file")
    name = lines[0] or path.stem

    # Second = number of pitches.
    idx = 1
    while idx < len(lines) and not lines[idx]:
        idx += 1
    count = int(re.split(r"\s+", lines[idx])[0])
    idx += 1

    entries: list[float] = []
    for line in lines[idx:]:
        if not line:
            continue
        tok = re.split(r"[\s]+", line)[0]  # trailing text after the value is ignored per spec
        entries.append(_parse_pitch(tok))
        if len(entries) == count:
            break

    if len(entries) != count:
        raise ValueError(
            f"{path}: header declares {count} pitches, found {len(entries)}"
        )

    interval = entries[-1]
    ratios = tuple([1.0] + entries[:-1])

    if interval <= 1.0:
        raise ValueError(f"{path}: repeat interval {interval} must be > 1")
    if any(r <= 0 for r in ratios):
        raise ValueError(f"{path}: non-positive ratio")

    return Scale(
        name=name,
        ratios=ratios,
        interval=interval,
        basefreq=basefreq,
        basekey=basekey,
        source=path.name,
    )


def cents(ratio: float) -> float:
    return 1200.0 * math.log2(ratio)
