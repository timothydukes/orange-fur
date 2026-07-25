"""
motifs.py -- Phase 12. MOTIF RECURRENCE.

The system has always morphed forward without looking back; this module
gives a piece a MEMORY. Early in the run, the first few qualifying phrases
the score emits are captured as motifs -- degree cells with their rhythm --
and later sections RE-QUOTE them, transformed: transposed, inverted,
retrograded, augmented. Recurrence is what turns a stream of events into a
form; a listener who hears the opening cell return inverted in the outro has
been given a reason to believe the piece knew where it was going.

CAPTURE IS DETERMINISTIC. The bank is the first MAX_BANK patterns that
qualify (3-6 notes, span under 8 s) -- no draws consumed, so the RNG stream
is untouched and replay-stable by construction. What the piece remembers is
simply what it said first.

QUOTATION IS L1-DRIVEN. Section types that mean "return" quote more:
CHORUS and OUTRO lean on the bank, INTRO cannot quote (nothing exists yet),
BREAKDOWN mostly abstains. The per-section quote count and each quote's
transform are drawn with a FIXED number of draws (stream discipline).

QUOTES ARE PROTECTED PROCESSES -- the Phase 10 rule, inherited exactly as
planned: a quotation that loses notes to the density cull or transposes
mid-cell under the register staircase stops being a quotation. Quote notes
bypass both, carry a proc id (cost routing moves a quote atomically), and
take the accent contour (dynamics don't threaten identity). Marked
echo = -3: outside the N^2 source budget, like all decoration.

THE TAPE MACHINERY PREFERS REMEMBERED MATERIAL. When a bank exists, a
section's tape loop draws its cell FROM A MOTIF (rhythm compressed into the
loop period) about half the time -- and quotes themselves pass through the
ordinary echo-decoration draw, so a remembered phrase can return as a
phasing loop, a klangfarben cascade, or a cents-drifted train. The tape arc
stops processing arbitrary material and starts processing the piece's own
past.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

MAX_BANK = 4
QUALIFY_LEN = (3, 6)
QUALIFY_SPAN = 8.0

# quotes-per-section weights by L1 section name: (w0, w1, w2) for 0/1/2
L1_QUOTE_W = {
    "INTRO":     (1.0, 0.0, 0.0),      # nothing to remember yet, structurally
    "VERSE":     (0.55, 0.35, 0.10),
    "CHORUS":    (0.15, 0.45, 0.40),   # the returning section returns things
    "BREAKDOWN": (0.75, 0.25, 0.0),
    "OUTRO":     (0.25, 0.45, 0.30),   # the piece remembers itself at the end
}
DEFAULT_W = (0.55, 0.35, 0.10)


@dataclass
class Motif:
    degrees: list[int]        # relative to the captured pattern's first note
    iois: list[float]         # inter-onset intervals, len == len(degrees)-1
    durs: list[float]
    cat: int
    sec: str                  # where it was captured (report only)


@dataclass
class Quote:
    motif: int                # bank index
    transpose: int            # scale degrees
    invert: bool
    retro: bool
    augment: float            # 1.0 = none; >1 stretches rhythm and durations

    def tag(self) -> str:
        t = [f"T{self.transpose:+d}"] if self.transpose else []
        if self.invert:
            t.append("inv")
        if self.retro:
            t.append("retro")
        if self.augment != 1.0:
            t.append(f"aug{self.augment:.1f}")
        return "+".join(t) or "verbatim"


def qualifies(degs: list[int], starts: list[float]) -> bool:
    return (QUALIFY_LEN[0] <= len(degs) <= QUALIFY_LEN[1]
            and starts[-1] - starts[0] < QUALIFY_SPAN)


def capture(bank: list[Motif], degs: list[int], starts: list[float],
            durs: list[float], cat: int, sec: str) -> None:
    """Deterministic: append if the bank has room and the pattern qualifies."""
    if len(bank) >= MAX_BANK or not qualifies(degs, starts):
        return
    d0 = degs[0]
    bank.append(Motif(
        degrees=[d - d0 for d in degs],
        iois=[b - a for a, b in zip(starts, starts[1:])],
        durs=list(durs), cat=cat, sec=sec))


def draw_quotes(rng: random.Random, sec_name: str, bank_size: int
                ) -> list[Quote]:
    """Fixed draw count per section: one count draw + 5 draws per possible
    quote slot (2), consumed whether or not the bank can honour them."""
    w = L1_QUOTE_W.get(sec_name, DEFAULT_W)
    r = rng.random()
    nq = 0 if r < w[0] else (1 if r < w[0] + w[1] else 2)
    quotes = []
    for _ in range(2):                       # always 2 slots of draws
        m = rng.random()
        tr = rng.choice([-7, -5, -2, 0, 0, 2, 4, 5, 7])
        inv = rng.random() < 0.25
        retro = rng.random() < 0.25
        aug = rng.choice([1.0, 1.0, 1.0, 1.5, 2.0, 2.5])
        quotes.append(Quote(motif=int(m * max(1, bank_size)) % max(1, bank_size),
                            transpose=tr, invert=inv, retro=retro,
                            augment=aug))
    return quotes[:nq] if bank_size else []


def realize(q: Quote, motif: Motif) -> tuple[list[int], list[float],
                                             list[float]]:
    """Quote -> (degrees, onsets-from-0, durations)."""
    degs = list(motif.degrees)
    iois = list(motif.iois)
    durs = list(motif.durs)
    if q.invert:
        degs = [-d for d in degs]
    if q.retro:
        degs = degs[::-1]
        iois = iois[::-1]
        durs = durs[::-1]
    degs = [d + q.transpose for d in degs]
    iois = [i * q.augment for i in iois]
    durs = [d * q.augment for d in durs]
    onsets = [0.0]
    for i in iois:
        onsets.append(onsets[-1] + i)
    return degs, onsets, durs
