"""
dynamics.py -- Phase 21. `--dynamics {default, quiet, mid, limited}`.

Every preset is a PURE MAPPING applied to already-drawn values -- zero
draws added or removed -- which makes --dynamics a REMIX KNOB in the
--wetdry/--space class: one token, four dynamic readings of the same
piece. `default` is the identity, csd-identical to the flag being absent.

The no-limiter axiom holds by construction: "limited" is score-time
amplitude-range compression plus the exact post-render normalization --
no dynamics processing anywhere in the audio path.

Application sites (all mappings, no draws):
  1. apply_dynamics(events, preset): post-generation transform (the
     apply_window precedent) -- every event's amp is mapped
         a' = clamp((m + (a - m) * var) * scale, 0.005, 2.0)
     with m = the piece's own mean SOURCE-note amp (piece-relative).
     Uniform over source/echo/loops/quotes: echo trains' fb^k decay
     compresses under var < 1, which is exactly what "limited" means;
     P10's rule that dynamics apply to protected processes carries over.
  2. The macro ACCENT contour's applied depth is scaled by `accent`
     (plan.accent_depth *= accent after the plan draw -- the drawn
     contour is untouched, only its application).
  3. The post-render normalization target moves to `norm_db` unless an
     explicit --normalize overrides it.

Preset numbers are provisional and LISTENING-TUNABLE (the arc table's
own words); retuning is an edit to the table below and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DynPreset:
    name: str
    scale: float        # overall level multiplier
    var: float          # dynamic-range compression toward the piece mean
    accent: float       # macro ACCENT applied-depth multiplier
    norm_db: float | None   # normalization target; None = leave default


DYNAMICS: dict[str, DynPreset] = {
    "default": DynPreset("default", 1.00, 1.00, 1.0, None),
    "quiet":   DynPreset("quiet",   0.45, 1.00, 0.9, -12.0),
    "mid":     DynPreset("mid",     0.80, 0.60, 0.7, -3.0),
    "limited": DynPreset("limited", 0.95, 0.25, 0.3, -1.0),
}


def apply_dynamics(events: list, preset: DynPreset) -> None:
    """In-place amp mapping. Identity at `default` (early return -- the
    byte path). Piece-relative mean over SOURCE notes only, so decoration
    density doesn't move the anchor."""
    if preset.name == "default":
        return
    src = [e.amp for e in events if e.echo == 0]
    m = (sum(src) / len(src)) if src else 0.3
    lo, hi = 0.005, 2.0
    for e in events:
        a = (m + (e.amp - m) * preset.var) * preset.scale
        e.amp = lo if a < lo else (hi if a > hi else a)
