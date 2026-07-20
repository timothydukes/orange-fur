"""Phase 8 tests.  python3 tests/test_p8.py"""
from __future__ import annotations

import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur.score import Event, apply_window, INSTR_TAU, set_instr_peaks

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


ROOT = str(Path(__file__).resolve().parents[1])
TOKEN_RE = re.compile(r"replay\s+(\d+\.\d+\.\d+:[0-9a-f]{16})")


def run(*extra):
    return subprocess.run(
        [sys.executable, "-m", "orange_fur", "--nodes", "12", "--duration",
         "4", "--draft", *extra],
        capture_output=True, text=True, timeout=600, cwd=ROOT)


def notes(fn):
    out = []
    for l in Path(fn).read_text().splitlines():
        m = re.match(r"i (\d+) ([0-9.]+) ([0-9.]+) (.+)", l)
        if m and m.group(1) not in ("90", "99"):
            out.append((int(m.group(1)), float(m.group(2)),
                        float(m.group(3)), m.group(4)))
    return out


# ------------------------------------------------------------ unit: edge policy
def test_edge_policy():
    set_instr_peaks({}, {701: 0.5}, set())      # 701 is struck, tau=0.5
    ev = [
        Event(instr=700, start=5.0, dur=2.0, index=60, amp=.3, pan=.5,
              send=.4, slew=.3),                       # inside
        Event(instr=700, start=8.0, dur=30.0, index=60, amp=.3, pan=.5,
              send=.4, slew=.3),                       # sustains across `from`
        Event(instr=701, start=8.0, dur=30.0, index=60, amp=.3, pan=.5,
              send=.4, slew=.3),                       # struck 2.0s ago > 3*tau: rung out
        Event(instr=701, start=9.4, dur=30.0, index=60, amp=.3, pan=.5,
              send=.4, slew=.3),                       # struck recently: kept
        Event(instr=700, start=25.0, dur=2.0, index=60, amp=.3, pan=.5,
              send=.4, slew=.3),                       # after `to`: dropped
        Event(instr=700, start=19.0, dur=40.0, index=60, amp=.3, pan=.5,
              send=.4, slew=.3),                       # starts in window, long tail
    ]
    rooms = [(0.0, "SMALL", 1.0, 1.0, 1.0), (7.0, "LARGE", 0.9, 1.2, 1.1),
             (30.0, "MID", 1.0, 1.0, 0.8)]
    kept, wrooms, rep = apply_window(ev, rooms, 10.0, 20.0)

    check("edge: pre-window and post-window notes dropped, three kept",
          rep["kept"] == 3, rep)
    sus = [e for e in kept if e.instr == 700 and e.start == 0.0]
    check("edge: sustaining note clipped to the edge, remainder capped at "
          "the bus close",
          len(sus) == 1 and abs(sus[0].dur - 22.0) < 1e-9,
          [(e.start, e.dur) for e in kept])
    check("edge: struck note past 3*tau skipped, recent one kept",
          rep["rung_out"] == 1
          and sum(1 for e in kept if e.instr == 701) == 1)
    tail = [e for e in kept if abs(e.start - 9.0) < 1e-9]
    check("edge: tails kept past `to`, clamped to the bus close (span+12)",
          len(tail) == 1 and abs(tail[0].dur - 13.0) < 1e-9,
          [(e.start, e.dur) for e in tail])
    check("edge: rooms trimmed -- active-at-from becomes t=0, later shift, "
          "past-to dropped",
          wrooms[0][0] == 0.0 and wrooms[0][1] == "LARGE"
          and len(wrooms) == 1, wrooms)
    set_instr_peaks({}, {}, set())


# --------------------------------------------------------- slice parity via CLI
def test_slice_parity():
    r1 = run("--dry-run", "--out", "/tmp/p8full.wav")
    tok = TOKEN_RE.search(r1.stdout).group(1)
    r2 = run("--dry-run", "--out", "/tmp/p8win.wav", "--replay", tok,
             "--from", "1", "--to", "2")
    check("parity: windowed run reports the window",
          "window" in r2.stdout and r2.returncode == 0, r2.stdout[-200:])
    full = notes("/tmp/p8full.csd")
    win = notes("/tmp/p8win.csd")
    # expected window image of an interior note: shifted, duration clamped to
    # the bus close (the documented tail policy) -- all other p-fields identical
    interior = [(i, s - 60.0, min(d, 72.0 - (s - 60.0)), r)
                for (i, s, d, r) in full if 60.0 <= s < 120.0]
    ok = all(any(i == i2 and abs(s - s2) < 1e-3 and abs(d - d2) < 1e-3
                 and r == r2 for (i2, s2, d2, r2) in win)
             for (i, s, d, r) in interior)
    check("parity: every interior note appears in the window, shifted, "
          "identical p-fields modulo the tail clamp", ok and len(interior) > 5,
          (len(interior), len(win)))
    check("parity: no note from outside the window leaks in (except edge "
          "clips at t=0)",
          all(s < 1e-6 or any(abs(s - s2) < 1e-3 for (_, s2, _, _) in interior)
              for (_, s, _, _) in win))


# ----------------------------------------------------------------- validation
def test_validation():
    r = run("--dry-run", "--from", "1")
    check("validate: --from without --to rejected",
          r.returncode != 0 and "together" in r.stderr, r.stderr[-120:])
    r = run("--dry-run", "--from", "3", "--to", "2")
    check("validate: from >= to rejected", r.returncode != 0)
    r = run("--dry-run", "--from", "1", "--to", "9")
    check("validate: to > duration rejected", r.returncode != 0)


# ------------------------------------------------------------------------- e2e
def test_e2e_render():
    r1 = run("--dry-run", "--out", "/tmp/p8e.wav")
    tok = TOKEN_RE.search(r1.stdout).group(1)
    r = run("--out", "/tmp/p8e.wav", "--replay", tok, "--from", "0.5",
            "--to", "1.5")
    check("e2e: windowed render completes", r.returncode == 0,
          r.stdout[-200:] + r.stderr[-200:])
    b = Path("/tmp/p8e.wav").read_bytes()
    i = 12
    secs = None
    while i < len(b) - 8:
        cid = b[i:i + 4]
        sz = struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"data":
            secs = sz / 8 / 48000
            break
        i += 8 + sz + (sz & 1)
    check("e2e: wav length = window + bus tail (60 + 12 s)",
          secs is not None and 71.0 < secs < 74.0, secs)
    check("e2e: audition-only levels note printed",
          "AUDITION-ONLY" in r.stdout)


if __name__ == "__main__":
    print("edge policy:");   test_edge_policy()
    print("slice parity:");  test_slice_parity()
    print("validation:");    test_validation()
    print("e2e:");           test_e2e_render()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
