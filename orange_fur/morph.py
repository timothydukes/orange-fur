"""
morph.py -- Phase 23 (C8). CONTINUOUS-MORPH FORM FAMILY: the arc capstone.

Every interior section boundary draws, UNCONDITIONALLY with a fixed
layout (2 draws per boundary, always consumed), whether it is a MORPH
JOINT instead of a clean cut. `--morph X` scales the admission threshold
(0 = never, the current world byte-for-byte), so all values share a
replay token -- the remix-knob class. The first and last boundaries never
admit (the piece still begins and ends cleanly); they still draw.

A morphed boundary gets a WINDOW scaled to the piece: a drawn fraction
(0.25-0.6, modulated by the P22 state's o2) of the MEAN section length
(total / n_sections), clamped to [12 s, 0.4 x the shorter adjacent
section] -- short pieces seam in ~15-35 s, 45-minute pieces in ~35-80 s.

Inside the window, five mechanisms replace the cut (all no-draw):
  1. rooms crossfade -- the one sanctioned L3 exception: the f 900 row
     moves to t_b - w/2 and carries a portk lag (score.py/routing.py).
  2. ~90% field common tones -- an overlap term dominates the incoming
     field's candidate scoring (score.py, the P19 select mechanism).
  3. minute-scale glides -- window notes' glide targets redirect toward
     the incoming field, durations stretch (post-pass here).
  4. stretched macro periods -- adjacent sections' Euclidean tracks
     decelerate into the seam (score.py post-draw mutation).
  5. composed overlap joints -- drawn onsets remap so A's tail and B's
     head interleave (post-pass here).

Protected processes (loops, quotes: e.proc > 0) are untouched inside
windows -- identity outranks the seam (the P10 rule). The P22 state is
read regardless of --state (it is drawn in every piece): o0 at the
boundary modulates admission, o2 the window length.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

WIN_FRAC = (0.25, 0.60)      # of mean section length, pre-state-modulation
WIN_FLOOR = 12.0             # s
WIN_ADJ_CAP = 0.40           # of the shorter adjacent section
GLIDE_STRETCH_MAX = 2.0      # duration multiplier at the boundary itself


@dataclass
class MorphJoint:
    sec_index: int           # index of the INCOMING section
    t_b: float               # boundary time
    w: float                 # full window length, centered on t_b


def draw_morphs(rng: random.Random, t0s: list, spans: list, total: float,
                morph_x: float, obs_at) -> list:
    """Fixed layout: 2 draws per interior boundary, ALWAYS consumed.
    t0s/spans are per-section; boundary i sits at t0s[i] (start of
    section i), for i in 1..n-1. First and last boundaries draw but
    never admit."""
    n = len(t0s)
    mean_sec = total / max(1, n)
    joints = []
    for i in range(1, n):
        u_adm = rng.random()
        u_w = rng.random()
        first_or_last = (i == 1 or i == n - 1)
        t_b = t0s[i]
        o = obs_at(t_b)
        thr = morph_x * (0.30 + 0.70 * o[0])
        if morph_x <= 0 or first_or_last or u_adm >= thr:
            continue
        frac = (WIN_FRAC[0] + (WIN_FRAC[1] - WIN_FRAC[0]) * u_w) \
            * (0.70 + 0.60 * o[2])
        w = frac * mean_sec
        w = max(WIN_FLOOR, min(w, WIN_ADJ_CAP * min(spans[i - 1], spans[i])))
        if w <= 0:
            continue
        joints.append(MorphJoint(sec_index=i, t_b=t_b, w=w))
    return joints


def _affine(x, a0, a1, b0, b1):
    if a1 <= a0:
        return x
    return b0 + (x - a0) * (b1 - b0) / (a1 - a0)


def apply_morph(events: list, joints: list, sec_starts: list,
                sec_fields: list, basekey: int) -> dict:
    """The event post-pass (the apply_window precedent; zero draws):
    overlap remap + glide redirection inside each window. sec_fields is
    the LIVE per-section (t0, Field) list. Returns a small report dict."""
    moved = 0
    reglided = 0
    for j in joints:
        wa, wb = j.w / 2.0, j.w / 2.0
        a0, a1 = j.t_b - wa, j.t_b
        b0, b1 = j.t_b, j.t_b + wb
        fld = None
        for t0f, f in sec_fields:
            if abs(t0f - j.t_b) < 1e-6:
                fld = f
        for e in events:
            if getattr(e, "proc", 0) or e.echo == -1:
                continue    # protected processes and gap bridges: untouched
            s = e.start
            if a0 <= s < a1:
                # A's tail leans FORWARD across the boundary
                e.start = _affine(s, a0, a1, a0, j.t_b + wb * 0.5)
                moved += 1
            elif b0 <= s < b1:
                # B's head reaches BACK into A
                e.start = _affine(s, b0, b1, j.t_b - wa * 0.5, b1)
                moved += 1
            else:
                continue
            # minute-scale glide: redirect the note's arrival toward the
            # INCOMING field's nearest tone and stretch its duration by
            # closeness to the boundary (clamped to the 100 s contract)
            if fld is not None and e.echo == 0:
                close = 1.0 - min(1.0, abs(e.start - j.t_b) / max(wa, wb))
                # every window source note SUSTAINS into the seam
                # (minute-scale material; clamped to the 100 s contract)
                e.dur = min(100.0, e.dur * (1.0 + (GLIDE_STRETCH_MAX - 1.0)
                                            * close))
                # off-field notes additionally GLIDE to the incoming
                # field's nearest tone -- the audible voice-leading
                tgt_i, _tc = fld.snap(e.index, basekey)
                gl = tgt_i - e.index
                if gl != 0:
                    e.glide = gl
                    reglided += 1
    return {"n_joints": len(joints), "moved": moved, "reglided": reglided}
