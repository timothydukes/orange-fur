"""
sections.py -- the L1 layer: a SEQUENCE of sections laid over the node index.

Sections are not drawn per node. The grammar generates a sequence, and the N
outer nodes are partitioned among it in order -- so a section is a contiguous
run of outer nodes, which (because traversal order is time order) is a
contiguous span of the piece. Node i owns pairs [i*N, (i+1)*N), i.e. 1/N of the
timeline; a section owns however many consecutive nodes it was given.

The grammar operates on section TYPES with the five operators specified:

  repetition  take the previous section again
  novelty     introduce a type not yet used
  omission    drop a type from the pool for the rest of the run
  reversal    reverse the sequence built so far and continue from its end
  complement  take the "opposite" of the previous type (intro<->outro,
              verse<->chorus, breakdown is its own complement)

INTERPRETIVE DECISION: intro and outro are anchored. Whatever the grammar does
in the middle, a piece that "evolves from beginning to end" should begin at a
beginning and end at an end, so section 0 is forced to INTRO and the last to
OUTRO. Everything between is the grammar's.
"""

from __future__ import annotations

import random

from .alphabet import L1

COMPLEMENT = {
    L1.INTRO: L1.OUTRO,
    L1.OUTRO: L1.INTRO,
    L1.VERSE: L1.CHORUS,
    L1.CHORUS: L1.VERSE,
    L1.BREAKDOWN: L1.BREAKDOWN,
}

OPS = ["repetition", "novelty", "omission", "reversal", "complement"]


def gen_sections(count: int, rng: random.Random) -> tuple[list[L1], list[str]]:
    """Returns the section sequence and the operator trace that produced it."""
    if count <= 1:
        return [L1.INTRO], ["seed"]
    if count == 2:
        return [L1.INTRO, L1.OUTRO], ["seed", "anchor"]

    pool = set(L1)
    used: set[L1] = set()
    seq: list[L1] = [L1.INTRO]
    used.add(L1.INTRO)
    trace = ["seed:intro"]

    # The interior. The last slot is reserved for the OUTRO anchor.
    while len(seq) < count - 1:
        op = rng.choice(OPS)
        prev = seq[-1]

        if op == "repetition":
            seq.append(prev)
            trace.append(f"repetition:{prev.name.lower()}")

        elif op == "novelty":
            fresh = [s for s in pool if s not in used and s != L1.OUTRO]
            if not fresh:
                fresh = [s for s in pool if s != prev and s != L1.OUTRO]
            if not fresh:
                fresh = [prev]
            s = rng.choice(fresh)
            seq.append(s)
            used.add(s)
            trace.append(f"novelty:{s.name.lower()}")

        elif op == "omission":
            # Drop a type from the pool for the rest of the run. Never drop what
            # we need to keep going, and never drop the anchors.
            droppable = [s for s in pool
                         if s not in (L1.INTRO, L1.OUTRO, prev)]
            if len(pool) > 3 and droppable:
                d = rng.choice(droppable)
                pool.discard(d)
                trace.append(f"omission:{d.name.lower()}")
            else:
                trace.append("omission:declined")
            continue                      # omission consumes an op, not a slot

        elif op == "reversal":
            body = list(reversed(seq))
            take = min(len(body), count - 1 - len(seq))
            if take > 0:
                seq.extend(body[:take])
                trace.append(f"reversal:+{take}")
            else:
                trace.append("reversal:declined")

        elif op == "complement":
            c = COMPLEMENT[prev]
            if c == L1.OUTRO:             # do not spend the outro early
                c = L1.BREAKDOWN
            if c in pool:
                seq.append(c)
                used.add(c)
                trace.append(f"complement:{c.name.lower()}")
            else:
                seq.append(prev)
                trace.append("complement:blocked->repeat")

    seq.append(L1.OUTRO)
    trace.append("anchor:outro")
    return seq[:count], trace


def partition_nodes(n: int, sections: list[L1],
                    rng: random.Random) -> list[tuple[int, int, L1]]:
    """Split the N outer nodes into contiguous runs, one per section.

    Spans are uneven -- an intro is not the same length as a chorus -- but every
    section gets at least one node, which is what stops a 5-section run at N=2
    from producing empty sections.
    """
    k = len(sections)
    if k >= n:
        # More sections than nodes: one node each, truncate.
        return [(i, i + 1, sections[i]) for i in range(n)]

    weights = [rng.uniform(0.6, 1.6) for _ in sections]
    total = sum(weights)
    raw = [max(1, round(n * w / total)) for w in weights]

    # Repair to exactly n.
    while sum(raw) > n:
        i = max(range(k), key=lambda j: raw[j])
        if raw[i] > 1:
            raw[i] -= 1
        else:
            break
    while sum(raw) < n:
        raw[rng.randrange(k)] += 1

    out = []
    start = 0
    for i, w in enumerate(raw):
        out.append((start, start + w, sections[i]))
        start += w
    return out
