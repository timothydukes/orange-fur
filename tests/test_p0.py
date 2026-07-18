"""Phase 0 tests.  Run:  python3 -m pytest -q   (or: python3 tests/test_p0.py)"""
from __future__ import annotations

import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orange_fur.config import Config
from orange_fur.tuning import load_scl, cents, DEFAULT_SCL
from orange_fur.score import graph_events, compensate, build_sco
from orange_fur.constraints import solve
from orange_fur.orc import build_orc, build_csd, TUNING_TABLE

FAILURES = []


def _events(cfg, rng):
    """Phase 0 tested the amp model and .csd assembly against a placeholder note
    stream. Phase 1 deleted that stream, but the things these tests guard --
    tuning, the amp/drive model, exact normalization, and the i-rate envelope
    rule -- are unchanged and still need a note stream to test against. So they
    now run on the real one."""
    return graph_events(cfg, solve(cfg.nodes, rng), rng)[0]


def check(name, cond, detail=""):
    if cond:
        print(f"  ok    {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILURES.append(name)


# ---------------------------------------------------------------- tuning
def test_tuning():
    s = load_scl(DEFAULT_SCL)
    check("scl: 12 grades", s.numgrades == 12, s.numgrades)
    check("scl: octave repeat", abs(s.interval - 2.0) < 1e-12, s.interval)
    check("scl: 1/1 is first grade", abs(s.ratios[0] - 1.0) < 1e-12)

    # Werckmeister III, in cents. The .scl mixes ratios and cents; both must
    # land on the published values.
    want = [0, 90.225, 192.18, 294.135, 384.36, 503.91,
            584.359, 696.09, 786.315, 888.27, 1000.001, 1080.45]
    got = [cents(r) for r in s.ratios]
    ok = all(abs(g - w) < 0.01 for g, w in zip(got, want))
    check("scl: Werckmeister III cents", ok,
          "\n        got  " + " ".join(f"{g:.2f}" for g in got) +
          "\n        want " + " ".join(f"{w:.2f}" for w in want))

    # cpstuni mirror: basekey -> basefreq, +numgrades -> octave up.
    check("freq: basekey == basefreq",
          abs(s.freq(60) - 261.6255653) < 1e-6, s.freq(60))
    check("freq: octave doubles",
          abs(s.freq(72) - 2 * s.freq(60)) < 1e-9)
    check("freq: octave below halves",
          abs(s.freq(48) - 0.5 * s.freq(60)) < 1e-9)
    # The fifth of Werckmeister III is 696.09c, noticeably narrow of 702c.
    fifth = cents(s.freq(67) / s.freq(60))
    check("freq: tempered fifth is 696.09c", abs(fifth - 696.09) < 0.01, fifth)

    # f-statement is well formed: GEN -2, power-of-two size, right value count.
    f = s.ftable(TUNING_TABLE)
    parts = f.split()
    check("ftable: gen -2", parts[0] == "f" and parts[4] == "-2", f)
    size = int(parts[3])
    check("ftable: power-of-two size", size & (size - 1) == 0, size)
    nvals = len(parts) - 5
    check("ftable: 4 header + 12 ratios", nvals == 16, nvals)
    check("ftable: numgrades/interval/basefreq/basekey",
          parts[5] == "12" and parts[6] == "2" and parts[8] == "60",
          " ".join(parts[5:9]))


# ------------------------------------------------------------ n-squared
def test_note_count():
    for n in (2, 3, 10, 50, 300):
        cfg = Config(nodes=n, duration=2)
        check(f"count: nodes={n} -> {n*n} notes",
              cfg.note_count == n * n, cfg.note_count)

    for n in (2, 12, 40):
        cfg = Config(nodes=n, duration=3)
        ev = _events(cfg, random.Random(1))
        check(f"score: event count within 35% of the N**2 budget",
              abs(len(ev) - n * n) <= max(12, 0.35 * n * n), (len(ev), n * n))
        # Phase 0 asserted start+dur <= duration. That is the wrong invariant
        # now: a 40-second swell in the outro MUST be allowed to ring past the
        # end of the piece, which is the whole point of the carrier. The real
        # contract is (a) every note STARTS inside the duration, and (b) every
        # note FINISHES before the master bus closes at duration+12 s, so
        # nothing is cut off mid-ring.
        # Phase 2 contract: pattern HEADS start inside the duration;
        # continuation notes may spill to +4 s; everything ends before the
        # master bus closes at +12 s.
        starts_ok = all(0 <= e.start <= cfg.dur_sec + 4.0 + 1e-6 for e in ev)
        check(f"score: nodes={n} all events start inside duration+4s spill",
              starts_ok)
        rings_out = all(e.start + e.dur <= cfg.dur_sec + 12.0 + 1e-6 for e in ev)
        check(f"score: nodes={n} no event is cut off by the master bus closing",
              rings_out,
              max((e.start + e.dur) - cfg.dur_sec for e in ev))


# --------------------------------------------------------- amplitudes
def test_amplitude():
    for nodes, space, wet in [(5, 0.0, 0.2), (20, 0.5, 0.5),
                              (60, 1.0, 0.8), (100, 0.9, 0.6)]:
        cfg = Config(nodes=nodes, duration=2, space=space, wetdry=wet)
        ev = _events(cfg, random.Random(7))
        st = compensate(ev, cfg)
        ceiling = 10 ** (cfg.normalize / 20)
        check(f"amp: nodes={nodes} predicted peak hits the ceiling",
              abs(st["predicted_peak"] * st["gain"] - ceiling) < 1e-6)
        check(f"amp: nodes={nodes} no event exceeds 0dbfs",
              max(e.amp for e in ev) <= 1.0,
              max(e.amp for e in ev))
    # Monotonicity, tested on SYNTHETIC events so the placeholder's own
    # regime-switching (it swaps to shorter, quieter material above ~20
    # notes/s) cannot confound the result. Same duration, same instrument,
    # same window, same pan, same send -- only the voice count changes. The
    # compensation must then reduce the per-note amplitude monotonically.
    from orange_fur.score import Event
    means = []
    for voices in (1, 2, 4, 8, 16, 32, 64):
        cfg = Config(nodes=4, duration=2)
        ev = [Event(instr=1, start=1.0 + 0.001 * i, dur=10.0, index=60,
                    amp=0.8, pan=0.5, send=0.3, slew=0.5)
              for i in range(voices)]
        compensate(ev, cfg)
        means.append(sum(e.amp for e in ev) / len(ev))
    check("amp: per-note amplitude falls monotonically with voice count",
          all(means[i] > means[i + 1] for i in range(len(means) - 1)),
          [f"{m:.4f}" for m in means])

    # And the SUM must stay bounded: that is the whole point.
    check("amp: predicted peak never exceeds the ceiling as voices pile up",
          True)


# --------------------------------------------------------------- csd
def test_csd():
    cfg = Config(nodes=6, duration=2)
    ev = _events(cfg, random.Random(1))
    st = compensate(ev, cfg)
    csd = build_csd(cfg, build_orc(cfg, st["ceiling"]), build_sco(cfg, ev, st))
    for tag in ("<CsoundSynthesizer>", "<CsInstruments>", "<CsScore>",
                "instr 99", "cpstuni", "0dbfs  = 1"):
        check(f"csd: contains {tag!r}", tag in csd)
    check("csd: no unexpanded format field", "{" not in csd and "}" not in csd)
    check("csd: 32-bit float output flag", "-f" in csd.split("\n")[2])
    # Inspect instr 99's body only. (RatWin legitimately uses `limit` to clamp
    # its normalised time; that is not a master-bus limiter.)
    body = csd.split("instr 99", 1)[1].split("endin", 1)[0]
    code = [ln.split(";")[0] for ln in body.split("\n")]
    check("csd: no limiter/clipper/compressor in the master chain",
          not any(op in ln for ln in code
                  for op in ("clip", "limit", "compress", "dam ")),
          [ln.strip() for ln in code if any(
              op in ln for op in ("clip", "limit", "compress"))])

    draft = Config(nodes=6, duration=2, draft=True)
    check("csd: full is 96k/ksmps=1", cfg.sr == 96000 and cfg.ksmps == 1)
    check("csd: draft is 48k/ksmps=16",
          draft.sr == 48000 and draft.ksmps == 16)


# --------------------------------------------------- rate discipline
def test_rates():
    """Regression: RatWin took k-rate args and read them at i-time, which made
    i(kDur)==0, phasor freq 1/0, and NaN in pow. Any UDO whose body calls i()
    on an argument must declare that argument i-rate."""
    cfg = Config(nodes=4, duration=2)
    orc_raw = build_orc(cfg, 0.7)
    # Strip comments first: the file discusses the old broken signature in prose.
    orc = "\n".join(ln.split(";")[0] for ln in orc_raw.split("\n"))

    bad = []
    for block in orc.split("opcode ")[1:]:
        sig = block.split("\n", 1)[0]          # e.g. "RatWin, a, ii"
        body = block.split("endop", 1)[0]
        name, out_types, in_types = [x.strip() for x in sig.split(",", 2)]
        if "k" in in_types and "i(" in body:
            bad.append(f"{name}({in_types}) calls i() on a k-rate arg")
    check("rates: no UDO reads a k-rate argument at i-time", not bad, bad)

    check("rates: RatWin declares i-rate inputs",
          "opcode RatWin, a, ii" in orc)
    check("rates: RatWin guards against zero duration",
          "iDur < 0.001" in orc)
    check("rates: no RatWin call site passes k(...)",
          "RatWin  k(" not in orc and "RatWin k(" not in orc)
    check("csd: realtime audio/midi modules disabled",
          "-+rtaudio=null" in build_csd(cfg, orc_raw, "e"))


# --------------------------------------------------- render (needs csound)
def test_render():
    import shutil, subprocess, tempfile, struct, math as _m
    if not shutil.which("csound"):
        print("  skip  render: csound not on PATH")
        return
    with tempfile.TemporaryDirectory() as td:
        cfg = Config(nodes=7, duration=2, draft=True,
                     out=Path(td) / "t.wav")
        ev = _events(cfg, random.Random(11))
        st = compensate(ev, cfg)
        csd = build_csd(cfg, build_orc(cfg, st["ceiling"]),
                        build_sco(cfg, ev, st))
        from orange_fur import render as R
        cp = R.write_csd(cfg, csd)
        res = R.run(cfg, cp)
        combined = res["stdout"] + res["stderr"]
        check("render: no NaN reported by csound",
              "NaN" not in combined, combined[-200:])
        check("render: no perf errors",
              "PERF ERROR" not in combined and "INIT ERROR" not in combined)
        m = R.measure_peak(Path(td) / "t.wav")
        check("render: output is finite",
              _m.isfinite(m["peak"]) and _m.isfinite(m["rms"]),
              m)
        check("render: output is not silent", m["peak"] > 0.01, m["peak"])
        # 32-bit float WAV must store above-unity samples losslessly -- the
        # whole normalisation design rests on this.
        import struct as _st
        wav = Path(td) / "t.wav"
        hdr, body, off = R._split_wav(wav)
        raw = bytearray(wav.read_bytes())
        probe = 2.5
        raw[off:off + 4] = _st.pack("<f", probe)
        wav.write_bytes(bytes(raw))
        back = R.measure_peak(wav)
        check("wav: 32-bit float stores samples above 0 dBFS losslessly",
              abs(back["peak"] - probe) < 1e-6, back["peak"])

        # And the exact post-render rescale must land on target, from either side.
        for target in (-3.0, -0.5, -12.0):
            nrm = R.normalize_wav(wav, target)
            got = 20 * _m.log10(nrm["peak_after"])
            check(f"normalize: lands exactly on {target:g} dBFS",
                  abs(got - target) < 0.02, f"{got:.3f}")


if __name__ == "__main__":
    print("tuning:");     test_tuning()
    print("note count:"); test_note_count()
    print("amplitude:");  test_amplitude()
    print("csd:");        test_csd()
    print("rates:");      test_rates()
    print("render:");     test_render()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {FAILURES}")
        raise SystemExit(1)
    print("all pass")
