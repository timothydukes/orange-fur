"""
render.py -- write the .csd, invoke csound via subprocess, verify the result.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

from .config import Config


def check_csound(cfg: Config) -> str:
    exe = shutil.which(cfg.csound)
    if not exe:
        raise SystemExit(
            f"csound not found on PATH (looked for '{cfg.csound}').\n"
            f"Install it, or pass --csound /full/path/to/csound"
        )
    return exe


def write_csd(cfg: Config, csd_text: str) -> Path:
    p = cfg.csd_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(csd_text, encoding="utf-8")
    return p


def run(cfg: Config, csd_path: Path) -> dict:
    exe = check_csound(cfg)
    # csound writes the output next to its cwd; we set cwd to the output dir and
    # the CsOptions -o uses the bare filename, so the .wav lands beside the .csd.
    cwd = csd_path.parent.resolve()
    t0 = time.time()
    proc = subprocess.run(
        [exe, csd_path.name],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    elapsed = time.time() - t0
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"csound failed (exit {proc.returncode})")
    return {"elapsed": elapsed, "stderr": proc.stderr, "stdout": proc.stdout}


def normalize_wav(path: Path, target_dbfs: float) -> dict:
    """Scale the rendered 32-bit float WAV so its true peak lands exactly on
    target_dbfs. Returns the pre- and post-normalisation peaks.

    WHY THIS IS THE RIGHT PLACE TO NORMALISE, and why there is no limiter and no
    probe render:

      A 32-bit IEEE-float WAV does not clip. Samples above 1.0 are stored
      exactly -- we have measured a render reading back at +2.41 dBFS with full
      fidelity. So the final gain can be applied AFTER the render, losslessly,
      as a single scalar. That is exact by construction: no model, no estimate,
      no second pass, no coloration.

      The score-time amplitude compensation in score.py is therefore NOT what
      sets the output level. It still matters, and it matters more as the
      project grows: it governs how hard the signal drives the REVERB TANKS and
      (from Phase 3) the waveshapers, octave fuzz, and feedback chains, which
      are nonlinear and do care about absolute level. Getting that wrong changes
      the sound. Getting the output ceiling wrong does not -- it is just a
      number we can fix here for free.

      The one thing this cannot rescue is a nonlinear stage that was driven into
      an ugly place inside the orchestra. That is why the pre-normalisation peak
      is reported: it tells you how hot the internal mix ran.
    """
    before = measure_peak(path)
    peak = before["peak"]
    target = 10 ** (target_dbfs / 20.0)
    if not (peak > 1e-12) or not math.isfinite(peak):
        return {"gain": 1.0, "peak_before": peak, "peak_after": peak,
                "skipped": True}
    gain = target / peak

    hdr, samples, offset = _split_wav(path)
    try:
        import numpy as np
        a = np.frombuffer(samples, dtype="<f4").astype("<f4") * np.float32(gain)
        scaled = a.tobytes()
    except ImportError:
        import array
        a = array.array("f")
        a.frombytes(samples)
        for i in range(len(a)):
            a[i] *= gain
        if sys.byteorder != "little":
            a.byteswap()
        scaled = a.tobytes()

    raw = bytearray(path.read_bytes())
    raw[offset:offset + len(scaled)] = scaled
    path.write_bytes(bytes(raw))

    after = measure_peak(path)
    return {"gain": gain, "peak_before": peak, "peak_after": after["peak"],
            "skipped": False}


def _split_wav(path: Path):
    data = path.read_bytes()
    pos = 12
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        csize = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        if cid == b"data":
            return data[:pos + 8], data[pos + 8:pos + 8 + csize], pos + 8
        pos += 8 + csize + (csize & 1)
    raise ValueError(f"{path}: no data chunk")


def measure_peak(path: Path) -> dict:
    """Read back the 32-bit float WAV and report true peak + RMS.

    The `wave` module refuses IEEE-float WAVs, so parse the chunks directly.
    """
    data = path.read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a RIFF/WAVE file")
    pos = 12
    fmt_tag = bits = channels = None
    samples = b""
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        csize = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + csize]
        if cid == b"fmt ":
            fmt_tag, channels = struct.unpack("<HH", body[0:4])
            bits = struct.unpack("<H", body[14:16])[0]
        elif cid == b"data":
            samples = body
        pos += 8 + csize + (csize & 1)

    if fmt_tag not in (3, 0xFFFE) or bits != 32:
        return {"peak": float("nan"), "rms": float("nan"),
                "note": f"unexpected format tag={fmt_tag} bits={bits}"}

    n = len(samples) // 4
    try:
        import numpy as np
        a = np.frombuffer(samples[: n * 4], dtype="<f4")
        peak = float(np.abs(a).max()) if n else 0.0
        rms = float(np.sqrt((a.astype("f8") ** 2).mean())) if n else 0.0
    except ImportError:
        vals = struct.unpack(f"<{n}f", samples[: n * 4])
        peak = max((abs(v) for v in vals), default=0.0)
        rms = (sum(v * v for v in vals) / n) ** 0.5 if n else 0.0
    return {
        "peak": peak,
        "rms": rms,
        "channels": channels,
        "bits": bits,
        "frames": n // max(1, channels or 1),
    }
