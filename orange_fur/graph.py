"""
graph.py -- the node graph, the rewriting system, and the traversal.

STRUCTURE (all of this is from the spec, restated so the code can be checked
against it):

  * N nodes, 2 <= N <= unbounded (300 is the stated working ceiling).
  * The graph is COMPLETE and edges are inert: all data lives in the nodes.
    So "graph" here means an ordered list of nodes plus a double loop.
  * Each node carries a 7-tuple (L0..L6) and one rewriting rule.
  * Alphabet is exactly 2N: N non-terminals (one per node) + N terminals.
  * Traversal is lexicographic over all N*N ordered pairs, INCLUDING self-pairs.
    Traversal order IS time order.
  * A pair (a, b) applies node a's rule, then node b's rule.
  * A rule application rewrites the LEFTMOST occurrence of its non-terminal.
    One occurrence, not all of them -- so the string grows ADDITIVELY.
  * The working string NEVER resets.
  * N**2 is a BUDGET, not the string length. The string is unconstrained; the
    notes are selected from it (section-weighted -- see score.py).

GROWTH ARITHMETIC. Each application replaces 1 symbol with len(rhs), so it adds
(len(rhs) - 1). There are 2*N**2 applications. Final length is therefore about

    |axiom| + 2*N**2 * (mean_rhs_len - 1)

At N=300 with mean RHS 3, that is ~360,000 symbols and 180,000 rewrites. Fine.
Had rewriting been parallel (all occurrences), the same run would be 1.05^180000
symbols, which is why the single-occurrence rule matters so much.

PRODUCTIVITY. For node i's rule to fire all 2N times it is called, NT_i must be
present in the string each time. A rule whose RHS never reintroduces NT_i
consumes its own supply and the node goes dead. The generator therefore has a
strong prior toward SELF-REFERENTIAL rules (NT_i appears in its own RHS) -- the
classic fractal L-system shape, e.g. F -> F+F-F -- which guarantees the symbol
is never exhausted. The solver's "no dead nodes" constraint checks this by
actually running the traversal, not by inspecting the rules.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from .alphabet import (
    Cat, CAT_PRIOR, Waveform, L0, L1, L2, L3, L4, L5, L6,
    is_nonterminal, make_terminal,
)


@dataclass
class Node:
    index: int
    rule: list[int]              # RHS: the string NT_index rewrites to
    # the 7-tuple
    l0: L0
    l1: L1
    l2: L2
    l3: L3
    l4: L4
    l5: L5
    l6: L6

    @property
    def tuple7(self) -> tuple:
        return (self.l0, self.l1, self.l2, self.l3, self.l4, self.l5, self.l6)


@dataclass
class Terminal:
    """What a terminal symbol IS, independent of how a section reads it.

    The category and waveform are fixed for the whole run (they are properties
    of the alphabet). The per-section phenotype map decides the rest -- see
    phenotype.py -- so the same terminal is a quiet pluck in the intro and
    something else entirely in the breakdown.
    """
    index: int
    cat: Cat
    wave: Waveform | None = None     # only for Cat.TCLOUD


@dataclass
class System:
    n: int
    axiom: list[int]
    nodes: list[Node]
    terminals: list[Terminal]
    # filled by run()
    string: list[int] = field(default_factory=list)
    fired: list[int] = field(default_factory=list)      # per node: times its rule fired
    pair_marks: list[int] = field(default_factory=list) # per pair: string length after it
    capped: bool = False                                # hit max_len

    @property
    def budget(self) -> int:
        return self.n * self.n

    def terminal_count(self) -> int:
        return sum(1 for s in self.string if not is_nonterminal(s, self.n))

    def dead_nodes(self) -> list[int]:
        return [i for i, f in enumerate(self.fired) if f == 0]


# ---------------------------------------------------------------- generation
def gen_rule(i: int, n: int, rng: random.Random) -> list[int]:
    """One node's RHS.

    Shape: a short string mixing terminals and non-terminals, with a strong bias
    toward including NT_i itself (self-reference -> the node never starves).
    Length 2..5; the mean sets the growth rate, and the solver's expansion-band
    constraint is what actually keeps it honest.
    """
    length = rng.choice([2, 2, 3, 3, 3, 4, 4, 5])
    rhs: list[int] = []

    self_ref = rng.random() < 0.82
    for _ in range(length):
        r = rng.random()
        if r < 0.45:
            rhs.append(make_terminal(rng.randrange(n), n))     # a note
        elif r < 0.72:
            rhs.append(rng.randrange(n))                        # some non-terminal
        else:
            rhs.append(i if self_ref else rng.randrange(n))     # usually itself

    if self_ref and i not in rhs:
        rhs[rng.randrange(len(rhs))] = i
    # A rule must emit something, or the string is all scaffolding and no notes.
    if all(is_nonterminal(s, n) for s in rhs):
        rhs[rng.randrange(len(rhs))] = make_terminal(rng.randrange(n), n)
    return rhs


def gen_axiom(n: int, rng: random.Random) -> list[int]:
    """The axiom. Generated fresh each run.

    IT CONTAINS EVERY NON-TERMINAL. This is the structural reason "no dead
    nodes" holds. A node's rule can only fire while its symbol is present in the
    string; if NT_i is never seeded and no other rule happens to introduce it,
    node i never fires and its 7-tuple never reaches the score. A first version
    seeded only min(N, 64) symbols and 166 of 300 nodes went dead -- more than
    half the graph silently did nothing.

    Seeding all N, plus the strong self-reference prior in gen_rule (a rule that
    reintroduces its own symbol can never starve), makes the constraint hold by
    construction rather than by luck. The solver still CHECKS it, by running the
    derivation -- construction arguments are how you get bugs.

    Terminals are sprinkled in so the piece has material from the first bar.
    """
    order = list(range(n))
    rng.shuffle(order)
    ax: list[int] = []
    for nt in order:
        ax.append(nt)
        if rng.random() < 0.35:
            ax.append(make_terminal(rng.randrange(n), n))
    return ax


def gen_terminals(n: int, rng: random.Random) -> list[Terminal]:
    cats = list(CAT_PRIOR.keys())
    weights = [CAT_PRIOR[c] for c in cats]
    out = []
    for i in range(n):
        c = rng.choices(cats, weights=weights, k=1)[0]
        w = rng.choice(list(Waveform)) if c == Cat.TCLOUD else None
        out.append(Terminal(index=i, cat=c, wave=w))
    return out


def gen_nodes(n: int, rng: random.Random) -> list[Node]:
    """Nodes carry the 7-tuple.

    L1 (section) is NOT drawn per node -- sections are a SEQUENCE generated by
    the section grammar and then laid over the node index (sections.py). The L1
    field here is a placeholder that assign_sections() overwrites, so that a
    node's tuple7 is complete and self-describing once the run is set up.
    """
    nodes = []
    for i in range(n):
        nodes.append(Node(
            index=i,
            rule=gen_rule(i, n, rng),
            l0=rng.choice(list(L0)),
            l1=L1.VERSE,                     # overwritten by assign_sections()
            l2=rng.choice(list(L2)),
            l3=rng.choice(list(L3)),
            l4=rng.choice(list(L4)),
            l5=rng.choice(list(L5)),
            l6=rng.choice(list(L6)),
        ))
    return nodes


def gen_system(n: int, rng: random.Random) -> System:
    return System(
        n=n,
        axiom=gen_axiom(n, rng),
        nodes=gen_nodes(n, rng),
        terminals=gen_terminals(n, rng),
    )


# ---------------------------------------------------------------- derivation
BLOCK = 256      # elements per block
SB = 32          # blocks per superblock


def run_reference(sys: System, max_len: int = 20_000_000) -> System:
    """The obvious implementation. O(applications x length) and far too slow at
    N=300 (measured: 116 s, and 232 s once the axiom covered every node), but it
    is unmistakably correct. run() must agree with it exactly; test_p1.py checks
    that on identical RNG streams.
    """
    n = sys.n
    string = list(sys.axiom)
    fired = [0] * n
    marks: list[int] = []
    for a in range(n):
        for b in range(n):
            for i in (a, b):
                rhs = sys.nodes[i].rule
                if len(string) + len(rhs) - 1 > max_len:
                    continue
                try:
                    p = string.index(i)
                except ValueError:
                    continue
                string[p:p + 1] = rhs
                fired[i] += 1
            marks.append(len(string))
    sys.string = string
    sys.fired = fired
    sys.pair_marks = marks
    return sys


def run(sys: System, max_len: int = 20_000_000) -> System:
    """Lexicographic traversal of all N*N ordered pairs, leftmost derivation.

    THE PROBLEM. Two things make the naive version quadratic, and they pull in
    opposite directions:

      1. Leftmost derivation always splices near the FRONT of the string, so a
         flat list pays a full O(L) memmove on every one of the 2*N**2 rewrites.
      2. Finding the leftmost NT_i is an O(L) scan when that symbol's leftmost
         occurrence happens to sit deep in the string.

    Blocking the string fixes (1) but not (2), which turns out to be the larger
    cost: at N=300, L reaches 343k and there are 180k applications.

    THE TRAP. The obvious fix for (2) -- a per-symbol index of occurrence
    positions -- does not work. Leftmost derivation inserts the RHS to the LEFT
    of every remaining occurrence of the symbol it just consumed, so an
    append-ordered occurrence list stops being in string order after the first
    self-referential rewrite, and "leftmost" quietly starts returning an
    occurrence that is not leftmost. Positions shift under insertion, so a
    position-keyed heap goes stale too. Doing it properly needs order
    maintenance under arbitrary insertion.

    WHAT THIS DOES INSTEAD. Never track positions; track PRESENCE.

      * the string is a list of blocks of ~BLOCK elements  -> splices are O(BLOCK)
      * each block carries a bitmask of which non-terminals it contains, kept
        incrementally (a Python int is a perfectly good 300-bit mask)
      * blocks are grouped into superblocks whose mask is the OR of their members

    Leftmost NT_i is then: scan superblock masks, descend into the first hit,
    scan its block masks, and run list.index inside the one block that has it.
    That is ~74 cheap Python steps worst case instead of a 343k-element scan,
    and no ordering information is ever maintained -- so the trap above cannot
    be sprung. Correctness is checked against run_reference().
    """
    n = sys.n

    blocks: list[list[int]] = [list(sys.axiom[i:i + BLOCK])
                              for i in range(0, len(sys.axiom), BLOCK)] or [[]]
    bcount: list[dict[int, int]] = []
    bmask: list[int] = []
    for blk in blocks:
        c: dict[int, int] = {}
        m = 0
        for sym in blk:
            if sym < n:
                c[sym] = c.get(sym, 0) + 1
                m |= 1 << sym
        bcount.append(c)
        bmask.append(m)

    def rebuild_sb() -> list[int]:
        out = []
        for g in range(0, len(blocks), SB):
            m = 0
            for k in range(g, min(g + SB, len(blocks))):
                m |= bmask[k]
            out.append(m)
        return out

    sb = rebuild_sb()

    fired = [0] * n
    marks: list[int] = []
    length = len(sys.axiom)
    capped = False

    for a in range(n):
        for b in range(n):
            for i in (a, b):
                rhs = sys.nodes[i].rule
                if length + len(rhs) - 1 > max_len:
                    capped = True
                    continue

                bit = 1 << i
                k = -1
                for g, gm in enumerate(sb):
                    if gm & bit:
                        lo = g * SB
                        for kk in range(lo, min(lo + SB, len(blocks))):
                            if bmask[kk] & bit:
                                k = kk
                                break
                        if k >= 0:
                            break
                if k < 0:
                    continue                       # symbol exhausted: no-op

                blk = blocks[k]
                off = blk.index(i)
                blk[off:off + 1] = rhs
                length += len(rhs) - 1
                fired[i] += 1

                c = bcount[k]
                c[i] -= 1
                cleared = False
                if c[i] == 0:
                    del c[i]
                    bmask[k] &= ~bit
                    cleared = True
                for sym in rhs:
                    if sym < n:
                        c[sym] = c.get(sym, 0) + 1
                        bmask[k] |= 1 << sym

                g = k // SB
                if cleared:
                    m = 0
                    for kk in range(g * SB, min(g * SB + SB, len(blocks))):
                        m |= bmask[kk]
                    sb[g] = m
                else:
                    sb[g] |= bmask[k]

                if len(blk) > 2 * BLOCK:
                    half = len(blk) // 2
                    left, right = blk[:half], blk[half:]
                    blocks[k:k + 1] = [left, right]
                    for j, part in ((k, left), (k + 1, right)):
                        cc: dict[int, int] = {}
                        mm = 0
                        for sym in part:
                            if sym < n:
                                cc[sym] = cc.get(sym, 0) + 1
                                mm |= 1 << sym
                        if j == k:
                            bcount[k] = cc
                            bmask[k] = mm
                        else:
                            bcount.insert(k + 1, cc)
                            bmask.insert(k + 1, mm)
                    sb = rebuild_sb()
            marks.append(length)

    string: list[int] = []
    for blk in blocks:
        string.extend(blk)

    sys.string = string
    sys.fired = fired
    sys.pair_marks = marks
    sys.capped = capped
    return sys


def occurrence_lists_ok(sys: System) -> bool:
    """Cheap self-check: the materialised length must match the arithmetic."""
    expected = len(sys.axiom) + sum(
        (len(sys.nodes[i].rule) - 1) * sys.fired[i] for i in range(sys.n)
    )
    return len(sys.string) == expected
