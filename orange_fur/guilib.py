"""
guilib.py -- GUI phase. The HEADLESS logic layer.

The GUI is a front-end to the CLI, not a second implementation: it builds a
command line (shown to the user verbatim), runs `python3 -m orange_fur ...`
as a subprocess, and records the result. Everything decidable without a
display lives here -- command construction, echo-spec TOML serialization
(read back through the Phase 17 loader, so GUI files and hand-edited files
are one format), and the render library -- and is covered by test_gui. The
widget layer (gui.py) contains no logic beyond wiring widgets to this
module; the sandbox has no display, so the widget layer ships with a manual
checklist instead of machine tests.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .alphabet import Cat
from . import echocfg

TOKEN_RE = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")

CATS = [c.name for c in Cat]


# ------------------------------------------------------------ command build
@dataclass
class GenState:
    """Everything the Generate + Advanced tabs control. Defaults match the
    CLI's defaults so an untouched GUI builds the same command as a bare
    invocation."""
    nodes: int = 24
    duration: float = 5.0
    sections: int = 0
    space: float = 0.5
    air: float = 0.25
    wetdry: float = 0.35
    subset: float = 50.0
    subset_cat: dict = field(default_factory=dict)   # NAME -> pct
    spectral: float = 0.0
    tension: float = 0.0
    surface: float = 0.0
    dynamics: str = "default"
    state: str = ""
    morph: float = 0.0
    fields: bool = True
    echo: float = 1.0
    echo_spec: str = ""            # path or ""
    draft: bool = True             # the GUI's working default IS draft
    normalize: float = -3.0
    out_dir: str = ""
    tag: str = ""
    replay: str = ""
    win_from: str = ""             # minutes, as text -- "" = full piece
    win_to: str = ""
    scl: str = ""
    basefreq: str = ""
    basekey: str = ""
    cost_cap: str = ""
    csound: str = ""

    def validate(self) -> list[str]:
        errs = []
        f, t = self.win_from.strip(), self.win_to.strip()
        if bool(f) != bool(t):
            errs.append("preview window: set both minute-in and minute-out")
        if f and t:
            try:
                lo, hi = float(f), float(t)
                if not (0 <= lo < hi <= self.duration):
                    errs.append("preview window: need 0 <= in < out <= "
                                "duration")
            except ValueError:
                errs.append("preview window: minutes must be numbers")
        if self.replay and not re.fullmatch(
                r"(\d+\.\d+\.\d+:)?[0-9a-f]{1,16}", self.replay.strip()):
            errs.append("replay token: expected VERSION:HEX or hex")
        for name, pct in self.subset_cat.items():
            if name not in CATS or not (1 <= pct <= 100):
                errs.append(f"subset-cat: bad entry {name}={pct}")
        if not (0.0 <= self.tension <= 1.0):
            errs.append("tension must be 0-1")
        if not (0.0 <= self.surface <= 100.0):
            errs.append("surface must be 0-100")
        if self.dynamics not in ("default", "quiet", "mid", "limited"):
            errs.append("dynamics must be one of default/quiet/mid/limited")
        if not (0.0 <= self.morph <= 1.0):
            errs.append("morph must be 0-1")
        if self.state.strip():
            from .state import parse_state
            try:
                parse_state(self.state)
            except ValueError as e:
                errs.append(str(e))
        return errs

    def argv(self) -> list[str]:
        a = [sys.executable, "-m", "orange_fur",
             "--nodes", str(self.nodes),
             "--duration", f"{self.duration:g}"]
        if self.sections:
            a += ["--sections", str(self.sections)]
        a += ["--space", f"{self.space:g}", "--air", f"{self.air:g}",
              "--wetdry", f"{self.wetdry:g}",
              "--subset", f"{self.subset:g}"]
        if self.subset_cat:
            spec = ",".join(f"{k}={self.subset_cat[k]:g}"
                            for k in CATS if k in self.subset_cat)
            a += ["--subset-cat", spec]
        if self.spectral:
            a += ["--spectral", f"{self.spectral:g}"]
        if self.tension:
            a += ["--tension", f"{self.tension:g}"]
        if self.surface:
            a += ["--surface", f"{self.surface:g}"]
        if self.dynamics and self.dynamics != "default":
            a += ["--dynamics", self.dynamics]
        if self.state.strip():
            a += ["--state", self.state.strip()]
        if self.morph:
            a += ["--morph", f"{self.morph:g}"]
        if not self.fields:
            a += ["--fields", "0"]
        if self.echo != 1.0:
            a += ["--echo", f"{self.echo:g}"]
        if self.echo_spec:
            a += ["--echo-spec", self.echo_spec]
        if self.draft:
            a += ["--draft"]
        if self.normalize != -3.0:
            a += ["--normalize", f"{self.normalize:g}"]
        if self.replay.strip():
            a += ["--replay", self.replay.strip()]
        if self.win_from.strip() and self.win_to.strip():
            a += ["--from", self.win_from.strip(),
                  "--to", self.win_to.strip()]
        if self.tag.strip():
            a += ["--seed", self.tag.strip()]
        if self.out_dir.strip():
            name = (f"orange_fur_{self.tag.strip()}.wav" if self.tag.strip()
                    else "orange_fur_gui.wav")
            a += ["--out", str(Path(self.out_dir.strip()) / name)]
        if self.scl.strip():
            a += ["--scl", self.scl.strip()]
        if self.basefreq.strip():
            a += ["--basefreq", self.basefreq.strip()]
        if self.basekey.strip():
            a += ["--basekey", self.basekey.strip()]
        if self.cost_cap.strip():
            a += ["--cost-cap", self.cost_cap.strip()]
        if self.csound.strip():
            a += ["--csound", self.csound.strip()]
        return a

    def display(self) -> str:
        tail = self.argv()[3:]
        return "python3 -m orange_fur " + " ".join(
            p if " " not in p else f"'{p}'" for p in tail)


# ------------------------------------------------------- echo spec writing
def spec_to_toml(ec: echocfg.EchoConfig) -> str:
    """EchoConfig -> schema-1 TOML, loadable by echocfg.load. The GUI edits
    an EchoConfig in memory and round-trips through this writer + the P17
    loader, so a GUI-written file and a hand-written file are one format."""
    L = ["# written by orange-fur GUI", "", "schema = 1", "", "[echo]",
         f"scale = {ec.scale:g}",
         f"max_notes_per_pattern = {ec.max_notes_per_pattern}",
         f'second_order = "{ec.second_order}"', ""]

    def table(name, d):
        L.append(f"[{name}]")
        for k, v in d.items():
            if isinstance(v, bool):
                L.append(f"{k} = {'true' if v else 'false'}")
            elif isinstance(v, list):
                L.append(f"{k} = [{v[0]:g}, {v[1]:g}]")
            else:
                L.append(f"{k} = {v:g}")
        L.append("")

    table("echo.modes", ec.modes)
    table("echo.timing.weights", ec.timing)
    table("echo.timing.uniform", ec.uniform)
    table("echo.timing.multitap", ec.multitap)
    table("echo.timing.euclid", ec.euclid)
    table("echo.timing.ramp", ec.ramp)
    table("echo.pan", ec.pan)
    table("echo.rotation", ec.rotation)
    table("echo.varispeed", ec.varispeed)
    table("echo.gestures", ec.gestures)
    return "\n".join(L)


def ensure_toml_ext(path: str) -> str:
    """macOS save panels routinely return the typed name without an
    extension; the spec loader and the CLI don't care, but the user's
    Finder does. Headless so it's testable."""
    p = Path(path)
    return str(p) if p.suffix else str(p.with_suffix(".toml"))


def save_spec(ec: echocfg.EchoConfig, path: str) -> str:
    """Write + round-trip-validate a spec. Returns the (possibly
    extension-completed) path actually written. Writer bugs fail HERE, at
    save time, not at render time."""
    path = ensure_toml_ext(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(spec_to_toml(ec))
    echocfg.load(path)
    return path


# -------------------------------------------------------------- the library
def default_library_path() -> Path:
    return Path.home() / ".orange_fur" / "library.json"


class Library:
    """Auto-records EVERY render; keepers get a marker. JSON on disk,
    newest first."""

    def __init__(self, path: Path | None = None):
        self.path = path or default_library_path()
        self.entries: list[dict] = []
        if self.path.exists():
            try:
                self.entries = json.loads(self.path.read_text())
            except (json.JSONDecodeError, OSError):
                self.entries = []

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.entries, indent=1))

    def record(self, token: str, display_cmd: str, out_path: str,
               note: str = "") -> dict:
        e = dict(token=token, cmd=display_cmd, out=out_path, note=note,
                 keep=False,
                 date=datetime.datetime.now().isoformat(timespec="seconds"))
        self.entries.insert(0, e)
        self._save()
        return e

    def set_keep(self, token: str, keep: bool) -> None:
        for e in self.entries:
            if e["token"] == token:
                e["keep"] = keep
        self._save()

    def set_note(self, token: str, note: str) -> None:
        for e in self.entries:
            if e["token"] == token:
                e["note"] = note
        self._save()

    def prune(self) -> int:
        """Drop everything not marked keep. Returns removed count."""
        n = len(self.entries)
        self.entries = [e for e in self.entries if e["keep"]]
        self._save()
        return n - len(self.entries)

    def find_token(self, text: str) -> str | None:
        m = TOKEN_RE.search(text)
        return m.group(1) if m else None
