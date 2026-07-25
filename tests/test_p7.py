"""Phase 7 tests.  python3 tests/test_p7.py   (dry-runs only; fast)"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur import __version__
from orange_fur.config import Config

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])


def run(*extra):
    return subprocess.run(
        [sys.executable, "-m", "orange_fur", "--nodes", "6", "--duration",
         "2", "--draft", "--dry-run", *extra],
        capture_output=True, text=True, timeout=300, cwd=ROOT)


TOKEN_RE = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")


def _strip(csd: str) -> str:
    """Remove the two things that legitimately differ between a run and its
    replay: the output path in CsOptions and nothing else -- the seed tag now
    derives from the entropy, so even filenames must agree."""
    return re.sub(r"-o \S+", "-o X", csd)


def test_config_injection():
    a = Config(nodes=6, duration=2, replay=0xDEADBEEF)
    b = Config(nodes=6, duration=2, replay=0xDEADBEEF)
    check("config: replay injects the entropy",
          a.entropy == b.entropy == 0xDEADBEEF)
    check("config: default tag derives from entropy",
          a.seed == f"{a.entropy:016x}"[:8], a.seed)
    c = Config(nodes=6, duration=2)
    d = Config(nodes=6, duration=2)
    check("config: without replay, entropy still differs per run",
          c.entropy != d.entropy)


def test_replay_exact():
    r1 = run("--out", "/tmp/p7a.wav")
    m = TOKEN_RE.search(r1.stdout)
    check("replay: report prints a version:hex token", m is not None,
          r1.stdout[-200:])
    if not m:
        return
    tok = m.group(1)
    check("replay: token carries the current version",
          tok.startswith(__version__ + ":"), tok)

    r2 = run("--out", "/tmp/p7b.wav", "--replay", tok)
    a = Path("/tmp/p7a.csd").read_text()
    b = Path("/tmp/p7b.csd").read_text()
    check("replay: regenerated csd is identical (modulo output path)",
          _strip(a) == _strip(b))
    m2 = TOKEN_RE.search(r2.stdout)
    check("replay: replayed run reprints the same token",
          m2 is not None and m2.group(1) == tok,
          m2.group(1) if m2 else None)

    # a different fresh run differs (the test would be vacuous otherwise)
    r3 = run("--out", "/tmp/p7c.wav")
    c = Path("/tmp/p7c.csd").read_text()
    check("replay: a fresh entropy run differs", _strip(a) != _strip(c))


def test_bare_hex_and_warning():
    r = run("--out", "/tmp/p7d.wav", "--replay", "00000000deadbeef")
    check("replay: bare hex accepted, no version warning",
          r.returncode == 0 and "WARNING" not in r.stdout, r.stdout[-200:])
    r2 = run("--out", "/tmp/p7e.wav", "--replay", "0.0.1:00000000deadbeef")
    check("replay: version mismatch warns but proceeds",
          r2.returncode == 0 and "WARNING" in r2.stdout)
    # identical seed via bare hex and via mismatched-version token: same piece
    d = Path("/tmp/p7d.csd").read_text()
    e = Path("/tmp/p7e.csd").read_text()
    check("replay: the seed alone determines the piece",
          _strip(d) == _strip(e))
    r3 = run("--replay", "not-a-token")
    check("replay: bad token rejected with a clear error",
          r3.returncode != 0 and "bad --replay token" in r3.stderr,
          r3.stderr[-120:])


if __name__ == "__main__":
    print("config injection:"); test_config_injection()
    print("exact replay:");     test_replay_exact()
    print("token handling:");   test_bare_hex_and_warning()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
