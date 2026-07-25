"""
decimate.py -- Phase 6. The oversampled release master: 96 kHz -> 48 kHz.

WHY OVERSAMPLE AT ALL. The orchestra is full of nonlinearities -- rational
shapers, feedback loops, hard sync, the bitcrushed bus convolution -- and every
one of them generates energy above the audio band. At sr=48k that energy
aliases back down DURING synthesis and is baked into the file. Rendering at
96k gives the junk an octave of headroom to live in, and this module then
removes it with a linear-phase lowpass before taking every second sample.
The deliverable is a 48 kHz file whose top octave is clean instead of folded.

THE FILTER. Windowed-sinc FIR, Kaiser window, cutoff at 0.45 of the TARGET
Nyquist band (21.6 kHz), 255 taps at 96k: ~90 dB stopbandm transition well
inside the discarded octave, exactly linear phase (the group delay is trimmed).
Convolution is FFT overlap-add in large blocks -- pure numpy, a couple of
minutes for an hour of stereo on an old machine.

NUMPY IS OPTIONAL. This is the only module that wants it. If numpy is not
importable the release render is still written -- at 96 kHz, undecimated --
and the CLI says so plainly rather than failing a 40-minute render at the
last step.
"""

from __future__ import annotations

import math
import struct
from pathlib import Path

TAPS = 255
CUTOFF = 0.45          # fraction of the TARGET (post-decimation) Nyquist
KAISER_BETA = 10.0


def have_numpy() -> bool:
    try:
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


def _read_wav_f32(path: Path):
    import numpy as np
    b = path.read_bytes()
    assert b[:4] == b"RIFF" and b[8:12] == b"WAVE", "not a WAV"
    i = 12
    fmt = None
    while i < len(b) - 8:
        cid = b[i:i + 4]
        sz = struct.unpack("<I", b[i + 4:i + 8])[0]
        if cid == b"fmt ":
            fmt = struct.unpack("<HHIIHH", b[i + 8:i + 24])
        elif cid == b"data":
            assert fmt is not None, "data before fmt"
            audio, nch, sr, _, _, bits = fmt
            assert audio == 3 and bits == 32, "expected 32-bit float WAV"
            x = np.frombuffer(b[i + 8:i + 8 + sz], dtype="<f4")
            return x.reshape(-1, nch).astype(np.float64), sr, nch
        i += 8 + sz + (sz & 1)
    raise ValueError("no data chunk")


def _write_wav_f32(path: Path, x, sr: int) -> None:
    import numpy as np
    nch = x.shape[1]
    data = x.astype("<f4").tobytes()
    hdr = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    hdr += b"fmt " + struct.pack("<IHHIIHH", 16, 3, nch, sr,
                                 sr * nch * 4, nch * 4, 32)
    hdr += b"data" + struct.pack("<I", len(data))
    path.write_bytes(hdr + data)


def _kaiser_sinc(taps: int, fc: float, beta: float):
    """Linear-phase lowpass prototype. fc = cutoff as a fraction of the
    SOURCE sample rate (0..0.5)."""
    import numpy as np
    n = np.arange(taps) - (taps - 1) / 2.0
    h = 2 * fc * np.sinc(2 * fc * n)
    h *= np.kaiser(taps, beta)
    return h / h.sum()


def decimate_by_2(src: Path, dst: Path) -> dict:
    """96k float WAV in, 48k float WAV out. Linear phase, delay-compensated.
    Returns a small report dict."""
    import numpy as np
    x, sr, nch = _read_wav_f32(src)
    fc = CUTOFF * 0.5 * 0.5          # 0.45 * target-Nyquist, as fraction of src sr
    h = _kaiser_sinc(TAPS, fc, KAISER_BETA)

    # FFT overlap-add per channel
    block = 1 << 18
    nfft = 1 << 19
    H = np.fft.rfft(h, nfft)
    out = np.zeros((x.shape[0] + TAPS - 1, nch))
    for c in range(nch):
        pos = 0
        while pos < x.shape[0]:
            seg = x[pos:pos + block, c]
            y = np.fft.irfft(np.fft.rfft(seg, nfft) * H, nfft)[:len(seg) + TAPS - 1]
            out[pos:pos + len(y), c] += y
            pos += block

    d = (TAPS - 1) // 2                       # trim the group delay
    out = out[d:d + x.shape[0]]
    y2 = out[::2].copy()
    _write_wav_f32(dst, y2, sr // 2)
    return {"in_sr": sr, "out_sr": sr // 2, "taps": TAPS,
            "in_frames": int(x.shape[0]), "out_frames": int(y2.shape[0])}
