"""
state.py -- Phase 22 (D11). SLOW DYNAMICAL MACRO-STATE: hidden weather.

A 4-dimensional Kuramoto-style coupled-oscillator system, drawn
UNCONDITIONALLY at generation start with a FIXED draw count (the P9 house
pattern) and integrated deterministically across the piece. Four
observables o0..o3 in [0, 1] are sampled at section boundaries and
interpolated where a consumer wants continuity. `--state` selects which
of five consumers READ the state (fields, density, register, air,
rooms); reading is always a no-draw modulation of already-drawn values,
so every `--state` value shares a replay token -- the --tension remix
class.

Coupled oscillators over a CA because the spec's timescale ("slow",
"integrated per-section") wants smooth quasi-periodic drift, not
discrete flicker; the coupling makes the observables correlated but
non-identical weather.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

NDIM = 4
CONSUMERS = ("fields", "density", "register", "air", "rooms")


@dataclass
class StateSystem:
    omega: list          # natural frequencies, rad/s (macro periods 1-8 min)
    K: list              # coupling matrix NDIM x NDIM
    theta0: list         # initial phases
    trajectory: list = field(default_factory=list)   # (t, [o0..o3])

    def integrate(self, duration: float, section_t0s: list) -> None:
        """Fixed-step RK-free Euler at dt small vs the fastest period
        (deterministic; the system is smooth and slow, Euler at dt <= 0.5 s
        against 60 s+ periods has error orders below audibility). Samples
        stored at every dt; observables read via obs_at()."""
        dt = 0.25
        th = list(self.theta0)
        t = 0.0
        self.trajectory = []
        steps = int(duration / dt) + 2
        for _ in range(steps):
            obs = [0.5 + 0.5 * math.sin(x) for x in th]
            self.trajectory.append((t, obs))
            new = []
            for i in range(NDIM):
                coup = sum(self.K[i][j] * math.sin(th[j] - th[i])
                           for j in range(NDIM))
                new.append(th[i] + dt * (self.omega[i] + coup))
            th = new
            t += dt
        self._t0s = list(section_t0s)

    def obs_at(self, t: float) -> list:
        """Linear interpolation on the stored trajectory."""
        traj = self.trajectory
        if not traj:
            return [0.5] * NDIM
        i = min(len(traj) - 1, max(0, int(t / 0.25)))
        if i + 1 >= len(traj):
            return traj[-1][1]
        (ta, oa), (tb, ob) = traj[i], traj[i + 1]
        f = 0.0 if tb <= ta else (t - ta) / (tb - ta)
        f = min(1.0, max(0.0, f))
        return [a + (b - a) * f for a, b in zip(oa, ob)]


def draw_state(rng: random.Random) -> StateSystem:
    """FIXED draw count: NDIM omegas + NDIM^2 couplings + NDIM phases,
    always drawn (the state exists in every piece; --state chooses who
    listens)."""
    omega = [2 * math.pi / rng.uniform(60.0, 480.0) for _ in range(NDIM)]
    K = [[rng.uniform(-0.004, 0.009) for _ in range(NDIM)]
         for _ in range(NDIM)]
    theta0 = [rng.uniform(0, 2 * math.pi) for _ in range(NDIM)]
    return StateSystem(omega=omega, K=K, theta0=theta0)


def parse_state(spec: str | None) -> frozenset:
    """--state LIST -> the enabled consumer set. None/absent = off;
    'all' = every consumer. Unknown names raise ValueError."""
    if not spec:
        return frozenset()
    names = [x.strip().lower() for x in spec.split(",") if x.strip()]
    if "all" in names:
        return frozenset(CONSUMERS)
    bad = [x for x in names if x not in CONSUMERS]
    if bad:
        raise ValueError(f"unknown --state consumer(s): {', '.join(bad)}; "
                         f"choose from {', '.join(CONSUMERS)} or 'all'")
    return frozenset(names)
