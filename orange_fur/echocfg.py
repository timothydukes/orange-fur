"""
echocfg.py -- Phase 17. The echo control surface.

`--echo-spec file.toml` gives fine-grained control of the score-domain echo
machinery. ONE DEVIATION from the approved draft, forced by TOML itself:
timing-family WEIGHTS live in [echo.timing.weights], because a scalar key
`uniform` and a table [echo.timing.uniform] cannot coexist in one table
(TOML key-redefinition). Family parameter tables keep their names.

`--echo-spec` controls: timing families (uniform / multitap / euclid / ramp), pitch-mode
weights, pan behavior, rotation, decay-time gestures, and second-order
echoes. The schema is versioned (schema = 1) and validated STRICTLY --
unknown keys are rejected, not ignored, so a typo cannot silently disable
the thing it misspells. The GUI writes this same format.

NO CONFIG = the exact Phase 9-11 distribution: DEFAULTS below reproduce the
previous constants (timing always uniform, modes 30/30/15/25, rotation 35%%
len 2-4, gestures 45/20/20/15, pan inherited, no second order).

TOKEN SHARING ACROSS CONFIGS: echo draws consume a FIXED layout of RNG
values per section regardless of what the config says (every family's
parameters are drawn, selection happens after) -- so any two configs, or a
config and no config, share a replay token: the same piece, a different
echo treatment. This is the strictest application of the house pattern yet.

Parsing uses stdlib tomllib on Python >= 3.11 and a bundled minimal parser
below it -- no new dependency on the target machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = 1


# ------------------------------------------------------------ minimal TOML
def _mini_toml(text: str) -> dict:
    """Enough TOML for this schema: [dotted.tables], key = value with
    strings, numbers, booleans, and flat arrays. Not a general parser."""
    root: dict = {}
    cur = root
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("["):
            if not line.endswith("]"):
                raise ValueError(f"line {ln}: bad table header")
            cur = root
            for part in line[1:-1].strip().split("."):
                cur = cur.setdefault(part.strip(), {})
            continue
        if "=" not in line:
            raise ValueError(f"line {ln}: expected key = value")
        k, v = (x.strip() for x in line.split("=", 1))
        cur[k] = _mini_val(v, ln)
    return root


def _mini_val(v: str, ln: int):
    if v.startswith("["):
        if not v.endswith("]"):
            raise ValueError(f"line {ln}: unterminated array")
        inner = v[1:-1].strip()
        return [_mini_val(x.strip(), ln) for x in inner.split(",")] \
            if inner else []
    if v in ("true", "false"):
        return v == "true"
    if v.startswith('"') and v.endswith('"'):
        return v[1:-1]
    try:
        return int(v)
    except ValueError:
        try:
            return float(v)
        except ValueError:
            raise ValueError(f"line {ln}: bad value {v!r}")


def _load_toml(path: Path) -> dict:
    try:
        import tomllib
        return tomllib.loads(path.read_text())
    except ImportError:
        return _mini_toml(path.read_text())


# ---------------------------------------------------------------- defaults
@dataclass
class EchoConfig:
    scale: float = 1.0
    max_notes_per_pattern: int = 96
    second_order: str = "off"            # off | drawn | always
    modes: dict = field(default_factory=lambda: dict(
        plain=0.30, degrees=0.30, octave=0.15, cents=0.25))
    timing: dict = field(default_factory=lambda: dict(     # the WEIGHTS
        uniform=1.0, multitap=0.0, euclid=0.0, ramp=0.0))
    uniform: dict = field(default_factory=lambda: dict(
        delay=[0.10, 1.00], fb=[0.40, 0.80]))
    multitap: dict = field(default_factory=lambda: dict(
        taps=[2, 5], cycle=[0.3, 1.6], fb=[0.45, 0.80]))
    euclid: dict = field(default_factory=lambda: dict(
        pulses=[3, 7], steps=[8, 16], cycle=[0.8, 2.4], fb=[0.45, 0.80]))
    ramp: dict = field(default_factory=lambda: dict(
        delay0=[0.12, 0.70], ratio=[0.78, 1.28], fb=[0.50, 0.85],
        pitch_couple=True))
    pan: dict = field(default_factory=lambda: dict(
        inherit=1.0, pingpong=0.0, rotate=0.0))
    rotation: dict = field(default_factory=lambda: dict(
        prob=0.35, len=[2, 4]))
    gestures: dict = field(default_factory=lambda: dict(
        flat=0.45, up=0.20, down=0.20, arch=0.15))
    varispeed: dict = field(default_factory=lambda: dict(
        enabled=False, prob=0.4, depth=[100.0, 500.0],
        segments=[3, 6]))          # Phase 18: additive to schema 1
    source: str = "(defaults: P9-P11 distribution)"


_RANGE_KEYS = {"delay", "fb", "taps", "cycle", "pulses", "steps",
               "delay0", "ratio", "len", "depth", "segments"}


def _merge(dst: dict, src: dict, path: str) -> None:
    for k, v in src.items():
        if k not in dst:
            raise ValueError(f"echo-spec: unknown key {path}{k}")
        if isinstance(dst[k], dict):
            if not isinstance(v, dict):
                raise ValueError(f"echo-spec: {path}{k} must be a table")
            _merge(dst[k], v, f"{path}{k}.")
        else:
            if k in _RANGE_KEYS:
                if (not isinstance(v, list) or len(v) != 2
                        or v[0] > v[1]):
                    raise ValueError(
                        f"echo-spec: {path}{k} must be [lo, hi]")
            dst[k] = v


def load(path: str | None) -> EchoConfig:
    cfg = EchoConfig()
    if path is None:
        return cfg
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"orange-fur: --echo-spec file not found: {path}")
    try:
        data = _load_toml(p)
    except ValueError as e:
        raise SystemExit(f"orange-fur: --echo-spec parse error: {e}")
    if data.get("schema") != SCHEMA:
        raise SystemExit(
            f"orange-fur: --echo-spec schema must be {SCHEMA} "
            f"(got {data.get('schema')!r})")
    echo = data.get("echo", {})
    if not isinstance(echo, dict):
        raise SystemExit("orange-fur: --echo-spec [echo] must be a table")
    try:
        for k in echo:
            if k in ("scale", "max_notes_per_pattern", "second_order"):
                setattr(cfg, k, echo[k])
            elif k in ("modes", "pan", "rotation", "gestures", "varispeed"):
                _merge(getattr(cfg, k), echo[k], f"echo.{k}.")
            elif k == "timing":
                tim = echo[k]
                if not isinstance(tim, dict):
                    raise ValueError("echo-spec: echo.timing must be a table")
                for tk in tim:
                    if tk == "weights":
                        _merge(cfg.timing, tim[tk], "echo.timing.weights.")
                    elif tk in ("uniform", "multitap", "euclid", "ramp"):
                        _merge(getattr(cfg, tk), tim[tk],
                               f"echo.timing.{tk}.")
                    else:
                        raise ValueError(
                            f"echo-spec: unknown key echo.timing.{tk}")
            else:
                raise ValueError(f"echo-spec: unknown key echo.{k}")
    except ValueError as e:
        raise SystemExit(f"orange-fur: {e}")
    if cfg.second_order not in ("off", "drawn", "always"):
        raise SystemExit("orange-fur: echo.second_order must be "
                         "off | drawn | always")
    cfg.source = path
    return cfg
