"""GUI-phase tests (headless logic layer).  python3 tests/test_gui.py

The widget layer cannot be machine-tested here (no display); it ships with
MANUAL_GUI_CHECKLIST.md instead. Everything decidable without a display is
tested below. No wx import anywhere in this file.
"""
from __future__ import annotations

import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import echocfg
from orange_fur import orchestra as O
from orange_fur.guilib import CATS, GenState, Library, TOKEN_RE, \
    ensure_toml_ext, save_spec, spec_to_toml

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])


# ---------------------------------------------------------- command build
def test_argv():
    s = GenState()
    a = s.display()
    check("argv: defaults build the bare working command",
          a == "python3 -m orange_fur --nodes 24 --duration 5 "
               "--space 0.5 --air 0.25 --wetdry 0.35 --subset 50 --draft",
          a)
    s = GenState(spectral=70, echo=1.5, fields=False,
                 subset_cat={"GONG": 20, "PARTIAL": 80},
                 win_from="2", win_to="4", replay="0.18.0:aaaabbbbccccdddd",
                 tag="try1", out_dir="/tmp")
    a = s.display()
    for frag in ("--spectral 70", "--echo 1.5", "--fields 0",
                 "--subset-cat PARTIAL=80,GONG=20",
                 "--from 2 --to 4", "--replay 0.18.0:aaaabbbbccccdddd",
                 "--seed try1", "--out /tmp/orange_fur_try1.wav"):
        check(f"argv: {frag.split()[0]} serialized", frag in a, a)
    check("argv: subset-cat ordered by category enum",
          a.index("PARTIAL") < a.index("GONG"))


def test_validation():
    check("valid: defaults pass", GenState().validate() == [])
    check("valid: window needs both ends",
          GenState(win_from="2").validate() != [])
    check("valid: window order and bounds",
          GenState(duration=5, win_from="4", win_to="2").validate() != []
          and GenState(duration=5, win_from="1", win_to="6").validate() != []
          and GenState(duration=5, win_from="1", win_to="4").validate() == [])
    check("valid: window rejects non-numbers",
          GenState(win_from="a", win_to="b").validate() != [])
    check("valid: bad token rejected, bare hex accepted",
          GenState(replay="zz").validate() != []
          and GenState(replay="deadbeef").validate() == [])
    check("valid: subset-cat entries checked",
          GenState(subset_cat={"BOGUS": 50}).validate() != []
          and GenState(subset_cat={"GONG": 200}).validate() != [])


# --------------------------------------------------------- spec round-trip
def test_spec_roundtrip():
    ec = echocfg.EchoConfig()
    ec.scale = 1.7
    ec.second_order = "drawn"
    ec.timing = dict(uniform=0.2, multitap=0.3, euclid=0.1, ramp=0.4)
    ec.ramp["ratio"] = [0.82, 0.9]
    ec.ramp["pitch_couple"] = False
    ec.pan = dict(inherit=0.1, pingpong=0.7, rotate=0.2)
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "spec.toml")
        save_spec(ec, path)          # includes round-trip validation
        back = echocfg.load(path)
    check("spec: writer -> P17 loader round-trip preserves every field",
          back.scale == 1.7 and back.second_order == "drawn"
          and back.timing == ec.timing and back.ramp["ratio"] == [0.82, 0.9]
          and back.ramp["pitch_couple"] is False and back.pan == ec.pan)
    check("spec: defaults write and reload as defaults",
          spec_to_toml(echocfg.EchoConfig()).count("schema = 1") == 1)
    check("spec: missing extension completed, existing one respected",
          ensure_toml_ext("/tmp/x/myspec").endswith("myspec.toml")
          and ensure_toml_ext("/tmp/x/a.toml").endswith("a.toml")
          and ensure_toml_ext("/tmp/x/a.txt").endswith("a.txt"))
    with tempfile.TemporaryDirectory() as td:
        # macOS save panels return names without extensions and may point
        # at not-yet-existing folders; save_spec must handle both and
        # return the path it actually wrote
        written = save_spec(echocfg.EchoConfig(),
                            str(Path(td) / "sub" / "noext"))
        check("spec: save_spec completes extension, creates parents, "
              "returns the real path",
              written.endswith("noext.toml") and Path(written).exists())


# ----------------------------------------------------------------- library
def test_library():
    with tempfile.TemporaryDirectory() as td:
        lib = Library(Path(td) / "lib.json")
        e1 = lib.record("0.19.0:" + "a" * 16, "cmd one", "/tmp/a.wav")
        lib.record("0.19.0:" + "b" * 16, "cmd two", "/tmp/b.wav", note="n")
        check("lib: auto-records every render, newest first",
              len(lib.entries) == 2 and lib.entries[0]["token"].endswith("b" * 16))
        lib.set_keep(e1["token"], True)
        lib.set_note(e1["token"], "keeper note")
        lib2 = Library(Path(td) / "lib.json")
        check("lib: persistence round-trip with keep + note",
              lib2.entries[1]["keep"] is True
              and lib2.entries[1]["note"] == "keeper note")
        n = lib2.prune()
        check("lib: prune removes only non-keepers",
              n == 1 and len(lib2.entries) == 1
              and lib2.entries[0]["keep"])
    tok = "0.19.0:0123456789abcdef"
    check("lib: token regex finds tokens in CLI output",
          Library(Path(tempfile.mkdtemp()) / "x.json")
          .find_token(f"  replay     {tok}   (--replay ...)") == tok)


# ------------------------------------------------------------ subset-cat
def test_subset_cat():
    rng = random.Random(5)
    full = O.generate(rng, 12, n_buses=2)
    sub = full.subset(50, random.Random(1),
                      per_cat={"GONG": 100, "CLOUD": 10})
    from orange_fur.alphabet import Cat
    gong_full = len(full.by_cat(Cat.GONG))
    cloud_full = len(full.by_cat(Cat.CLOUD))
    check("subset-cat: per-category percentages honored "
          "(GONG all kept, CLOUD decimated)",
          len(sub.by_cat(Cat.GONG)) == gong_full
          and len(sub.by_cat(Cat.CLOUD)) == max(1, round(cloud_full * 0.1)))
    check("subset-cat: unspecified categories inherit the global",
          abs(len(sub.by_cat(Cat.PLUCK))
              - round(len(full.by_cat(Cat.PLUCK)) * 0.5)) <= 1)

    def run(*extra):
        return subprocess.run(
            [sys.executable, "-m", "orange_fur", "--nodes", "8",
             "--duration", "2", "--draft", "--dry-run", *extra],
            capture_output=True, text=True, timeout=300, cwd=ROOT)
    r = run("--subset-cat", "GONG=100,CLOUD=10")
    check("subset-cat: CLI accepts a valid spec", r.returncode == 0)
    r = run("--subset-cat", "NOPE=50")
    check("subset-cat: CLI rejects unknown categories",
          r.returncode != 0 and "unknown category" in r.stderr + r.stdout)
    r = run("--subset-cat", "GONG=500")
    check("subset-cat: CLI rejects out-of-range percentages",
          r.returncode != 0)


# -------------------------------------------------------------- gui import
def test_gui_import_guard():
    r = subprocess.run([sys.executable, "-c",
                        "import orange_fur.guilib; print('guilib ok')"],
                       capture_output=True, text=True, cwd=ROOT)
    check("import: guilib is wx-free (imports headless)",
          r.returncode == 0 and "guilib ok" in r.stdout, r.stderr[-200:])
    r = subprocess.run([sys.executable, "-m", "orange_fur.gui"],
                       capture_output=True, text=True, cwd=ROOT, timeout=60)
    check("import: gui without wx exits with the install hint",
          r.returncode != 0 and "pip3 install wxPython" in
          r.stderr + r.stdout)




def test_p19_tension_state():
    from orange_fur.guilib import GenState
    g = GenState(); g.tension = 0.6
    check("gui: tension emits --tension in argv",
          "--tension" in g.argv() and "0.6" in g.argv())
    g0 = GenState()
    check("gui: tension 0 omitted from argv (default path)",
          "--tension" not in g0.argv())
    g.tension = 1.5
    check("gui: tension out of range rejected",
          any("tension" in e for e in g.validate()))


def test_p22_state():
    from orange_fur.guilib import GenState
    g = GenState(); g.state = "air,rooms"
    a = g.argv()
    check("gui: state list reaches argv", "--state" in a
          and a[a.index("--state") + 1] == "air,rooms")
    check("gui: valid state passes validation", not g.validate())
    g.state = "bogus"
    check("gui: bad state consumer caught", any("unknown" in e
                                                for e in g.validate()))
    g.state = ""
    check("gui: empty state omitted from argv", "--state" not in g.argv())

def test_p23_morph():
    from orange_fur.guilib import GenState
    g = GenState(); g.morph = 0.5
    a = g.argv()
    check("gui: morph reaches argv", "--morph" in a
          and a[a.index("--morph") + 1] == "0.5")
    check("gui: morph 0 omitted from argv",
          "--morph" not in GenState().argv())
    g.morph = 1.5
    check("gui: out-of-range morph caught",
          any("morph" in e for e in g.validate()))


if __name__ == "__main__":
    print("argv:");         test_argv()
    print("validation:");   test_validation()
    print("spec:");         test_spec_roundtrip()
    print("library:");      test_library()
    print("subset-cat:");   test_subset_cat()
    print("import guard:"); test_gui_import_guard()
    print("tension:");      test_p19_tension_state()
    print("state:");        test_p22_state()
    print("morph:");        test_p23_morph()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
