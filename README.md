# orange fur — Phase 6

Graph engine. The node graph, the rewriting system, the constraint solver, the
L1 section grammar, and section-weighted note selection. The orchestra is still
a placeholder (six instruments, one per category); Phase 3 replaces it.

---

## 1. Install and run (do this first)

You already have Csound and Python from Phase 0. In Terminal:

```
cd ~/Downloads
unzip -o orange_fur_p6.zip
cd orange_fur_p6
python3 -m orange_fur --nodes 16 --duration 2 --draft --out ~/Desktop/of1.wav
```

That renders in well under a minute and writes `~/Desktop/of1.wav`. Open it in
whatever you normally use. If it plays, Phase 1 is working on your machine.

Then run the tests:

```
python3 tests/test_p0.py && python3 tests/test_p1.py && python3 tests/test_p2.py && python3 tests/test_p3.py && python3 tests/test_p4.py && python3 tests/test_p5.py && python3 tests/test_p6.py
```

test_p3 includes render smoke tests for every synthesis template and takes a
minute or two.

Last line of each should be `all pass`. If it is not, stop and send me the output.

### The three runs I want you to listen to

```
# 1. mid density, the normal case
python3 -m orange_fur --nodes 24 --duration 4 --draft --out ~/Desktop/of_mid.wav

# 2. the sparse extreme: 100 notes across 12 minutes
python3 -m orange_fur --nodes 10 --duration 12 --draft --out ~/Desktop/of_sparse.wav

# 3. more sections than usual -- more room cuts, more content turnover
python3 -m orange_fur --nodes 20 --duration 5 --sections 9 --draft --out ~/Desktop/of_sec9.wav
```

Things to listen FOR in Phase 2: the room changing character at section
boundaries (width and reverb length step, no crossfade); onset density bending
within a section (tempo); terminals arriving as chords, trills, runs, and
chiptune arpeggios rather than single notes; and articulation — staccato
passages against legato ones.

Run 2 is the one that matters most. 100 notes across 12 minutes is the case that
tests whether the swells and reverb tails actually carry a sparse score, or
whether it is 12 minutes of silence with occasional events in it. Measured here:
zero near-silent windows across the whole 12 minutes. Confirm that by ear.

### New flag

`--sections K` (default 5) — how many sections the L1 grammar emits.

### Do NOT yet run

```
python3 -m orange_fur --nodes 300 --duration 10      # full quality
```

See §4.

---

## 2. What Phase 1 actually built

**Alphabet.** Exactly 2N symbols: N non-terminals (one per node) and N
terminals. Terminals emit notes and are never rewritten.

**Derivation.** Lexicographic traversal of all N×N ordered pairs, self-pairs
included. Traversal order is time order. Pair (a,b) applies node a's rule then
node b's. Each application rewrites the **leftmost** occurrence, **one**
occurrence, so the string grows additively. The string never resets.

**N² is a budget, not a length.** At N=300 the string reaches ~364,000 symbols
holding ~229,000 terminals, and 90,000 notes are selected from it.

**Selection is section-weighted.** A section is a contiguous run of outer nodes,
so it owns a contiguous span of the piece. Each section claims a share of the
timeline, a slice of the terminal sequence, and a share of the budget, all
proportional to its node count. Onsets within a section are a Poisson process
(exponential inter-onset gaps).

**Phenotype is redrawn per section.** Category and waveform are fixed for the
run (a gong stays a gong, or "gongs are rare" would mean nothing). Pitch class,
articulation, slew, and pan are a fresh random draw in each section — the same
string, read differently.

**Constraints are solved, and the relaxation ladder is reported.** See §3.

---

## 3. Findings — five things that were wrong, and one design inversion

**(a) More than half the graph was doing nothing.** At N=300, 166 of 300 nodes
never fired. A node's rule can only fire while its symbol is present in the
string; the first axiom seeded only 64 distinct non-terminals, and the rest were
never introduced, so their rules never ran and their 7-tuples never reached the
score. The axiom now contains **every** non-terminal. Dead nodes: 0 at every N
tested.

**(b) The derivation was quadratic — 232 seconds at N=300.** Two costs pull in
opposite directions: leftmost derivation always splices near the *front* of the
string (so a flat list pays a full memmove on each of 180,000 rewrites), and
finding the leftmost NT_i is a full scan when that symbol sits deep.

The obvious fix — a per-symbol index of occurrence positions — **does not work**,
and it fails silently. Leftmost derivation inserts the RHS to the *left* of every
remaining occurrence of the symbol it just consumed, so an append-ordered
occurrence list stops being in string order after the first self-referential
rewrite, and "leftmost" quietly starts returning an occurrence that is not
leftmost.

The fix tracks **presence, not position**: a blocked string where each block
carries a bitmask of which non-terminals it contains, with superblocks above
that. No ordering information is maintained, so the trap cannot be sprung.
**N=300: 232 s → 1.58 s.** The result is byte-identical to a brute-force oracle
at every N from 2 to 60, and `test_p1.py` checks that on every run.

**(c) Gongs were rare to the point of not existing.** The solver handed GONG to
the rarest symbols, and the rarest symbols were ones that never occur. Runs came
out with 0% gongs. That is not "gongs are rare," it is "there are no gongs," and
you specified gongs as ever-present. There is now a floor as well as a ceiling
(1.2%–6% of note events). Every run now has gongs.

**(d) The swell carrier could be selected away.** SWELL was assigned to leftover
symbols in index order, so it could land on symbols that barely occur — and at
N=12 the selection picked *zero* swells. Since the swells and reverb tails are
the entire reason a sparse score is legible, the carrier is not allowed to be a
rounding error. SWELL is now taken from the remaining symbols that occur *most*.

**(e) The solver lied about relaxing.** It kept the first candidate that passed
the hard constraints and never replaced it, so a later candidate that passed both
hard *and* soft was thrown away, and the run was reported as unrelaxed while
quietly violating its soft constraints.

**The design inversion.** The constraints split in two, and seeing this is what
made the solver cheap. Terminal supply, dead nodes, and the expansion band depend
on the rules, so testing one costs a full derivation. But "gongs are rare",
"partials are together", "clouds are sparse" do **not** depend on the rules — the
derivation hands us a sequence of terminal occurrences, and the only question is
which *category* each of the N terminal symbols gets. That is a separate
assignment problem, evaluated against a fixed sequence, with no re-derivation.

And it inverts: we do not assign PARTIAL and hope its occurrences cluster. We
**measure** each symbol's occurrence burstiness in the derived string, then hand
the clustered symbols to PARTIAL and the dispersed ones to CLOUD. The constraints
hold by construction rather than by rejection sampling.

**The ladder works, and says so.** At N=2 there are two terminal symbols, which
cannot carry six categories — it is structurally impossible. The solver climbs
to `homogeneous` and reports:

```
RELAXED    more_notes, partials_free, gongs_common, clouds_free, homogeneous
```

Any run that had to relax something prints that line. A compromised run tells
you it was compromised.

---

## 4. Render cost — read this before running N=300

Score generation is now fast (2.2 s at N=300). The render is not.

At N=300 / 10 min the score is 90,000 notes with **mean polyphony 848 and peak
polyphony 1782**. That is the dense corner behaving exactly as designed, and it
is very expensive. On top of that, the current orchestra has six *trivial*
instruments; Phase 3 and 4 replace them with the real ones, which will cost
10–50× more per note.

Working rules, unchanged from Phase 0:

- **`--draft` is the working mode.** Always. Full quality is for a final render
  you are prepared to leave running.
- Your 2015 MacBook Pro is roughly 2–4× slower than the machine these timings
  came from.
- Nothing routes density to cheaper instruments yet. That is Phase 5
  (`dynamics and density`), and it is what will make the dense corner tractable.
  Until then, high `--nodes` at full quality is a machine-hours proposition.

Measured, draft mode, in the sandbox:

| run | score gen | render |
|---|---|---|
| N=16 / 2 min | <0.1 s | 8 s |
| N=10 / 12 min (sparse) | <0.1 s | 8 s |
| N=300 / 10 min | 2.2 s | not attempted — see above |

---

## 5. What is real and what is still a placeholder

**Real, and permanent:**
`graph.py` (derivation, and the oracle it is tested against), `constraints.py`
(solver + ladder), `sections.py` (L1 grammar), `phenotype.py` (per-section
redraw), section-weighted selection and Poisson onsets in `score.py`, plus
everything from Phase 0 (tuning, .csd assembly, subprocess, exact normalization).

**Placeholder, replaced in Phase 3–4:**
The six instruments in `orc.py`. One per category. They exist to make the graph
audible and to prove the p-field contract, not to sound like the piece.

One of them is worth a listen anyway: **instr 5, the tuned partial cloud.** It
emulates saw / pulse / triangle additively, but every partial is snapped to the
nearest degree of Werckmeister III instead of sitting on an exact harmonic. The
spectrum keeps the *envelope* of the waveform (1/n for saw, odd-only 1/n for
pulse, odd 1/n² for triangle) while its *frequencies* belong to the scale. This
is "partials match tuning" made literal, and it is the mechanism by which the
dense material sounds tuned rather than merely dense. It carries forward.

**Inert until Phase 2:** L0 currently only drifts the register across a section.
L2–L6 are generated and carried on every node but do not yet reach the score.

---

## 6. Phase 2 — what was added

**The pair is now the unit of combination.** Outer node = context (L1 section,
L2 tempo, L3 room). Inner node = content (L4 pattern, L5 gesture, L6
articulation). A note's onset places it in one pair slice; that slice's inner
node decides what the terminal becomes. The same symbol, landing ten seconds
later, comes out a trill instead of a chord.

**L2 tempo** warps onset density across each outer node's 1/N of the timeline
(accel crowds late, decel early, steady untouched — u→u^γ on the Poisson
positions, preserving the exponential gap character).

**L3 rooms** resolve per section by majority vote over the section's nodes and
change ONLY at section boundaries — clean cuts, no crossfade. The master bus
steps reverb feedback, cutoff, and mid-side width from a score-built table
(f 900). Measured on a real render: side/mid energy 0.03 in SMALL → 0.79 in
MIDSIDE → back down at the next cut. LEFTRIGHT additionally quantises pans to
hard lanes score-side.

**L4 content**: chord, sustain, ostinato, arpeggio, run, chiparp, harmony,
trill, slide. Pattern notes count against the N² budget — selection divides
each section's share by the expected pattern size, and emission truncates
against a hard per-section note budget (heads always survive). SLIDE is
emulated as overlapping max-slew stepwise notes until the Phase 3 instruments
bring a real glissando.

**L5 gestures** (swell/stab/burst/drift/snap/scatter) are 8-tap precomputed
kernels shaping level and timing across the pattern.

**L6 articulations** (legato/staccato/tenuto/marcato/plucked/struck) set
duration scale, gap/overlap, slew, and level.

**Duration by literal convolution**, as specified: each pattern's articulation
sequence (L6 factor per note, jittered) is convolved with the gesture kernel at
low resolution, smoothed (3-tap follower), normalised to the articulation's
scale, and sampled per note. The bitcrushed bus-channel convolution is
orchestra-side and remains Phase 4.

**L2×L3 → L6 contour** (interpretive): tempo and room jointly scale slew — the
same articulation is rounder in a large decelerating passage than in a small
accelerating one.

**Contract amendments** (both interpretive, both in the tests):
pattern HEADS start inside the duration; continuation notes may spill to +4 s
(a final arpeggio ringing past the last bar is the outro working); everything
ends before the bus closes at +12 s. Event count sits within 35% of N² (pattern
quantisation), not exactly on it. The swell carrier is now GUARANTEED — if
strided selection misses every swell terminal (it can at small N), one is
injected into the largest section and the section log says so.

**Phase 2 side effect worth knowing:** pattern budgeting cut the N=300 dense
corner from mean polyphony 848 to 471.

## 7. Phase 3 — the orchestra generator

**~150 instruments per run, never the same twice.** Sixteen synthesis templates
(the spec's fixed ingredients) are instantiated with parameters BAKED INTO THE
GENERATED CSOUND TEXT: the bank template alone draws a partial count, a scale
degree per partial, a spectral law, and a wobble per partial — 200 consecutive
draws produced 200 distinct instruments (tested). Numbering: 1xx PARTIAL,
2xx PLUCK, 3xx GONG, 4xx CLOUD, 5xx TCLOUD, 6xx SWELL.

Templates: non-harmonic scale-degree banks (every partial a Werckmeister
degree), master/slave sync pairs, stereo PWM (dephased pulse-width LFOs L/R);
pluck variants, dirty gliding-sync plucks, feedback + rational waveshapers;
modal gongs with drawn inharmonic stretch (t-network-snap excitation) and
waveguide metal pipes; chirps, burst generators with popping exponential VCAs
(a retrigger phasor through exp(−k·phase)), filtered ticks; generalised tuned
partial clouds (cent-scale jitter drawn per partial) and wavetable crossfades;
PLL octave-down distortion swells (lag-locked sub through a rational shaper),
wavetable-crossfade swells, staggered bank swells with compound envelopes.

**New envelope UDOs**, still rational windows per spec: RatPop (the popping
VCA's shape) and RatComp (the product of two offset windows — the compound
envelope). All i-rate args; the Phase 0 scan test covers generated code.

**Safety rules the generator enforces** (tested by grepping its own output):
rational shaper denominators are 1 + c·x² with c > 0 — pole-free, no NaN;
feedback gains ≤ 0.92, dcblocked; frequencies clamped below sr/2.2; and the
reserved name `kr` is never used as a variable (a real parse error the smoke
test caught).

**--subset is live.** Per-category random subset, at least one instrument per
category at any percentage — a 10% orchestra is ~15 instruments and every
category still answers. The terminal→instrument binding joins the per-section
phenotype redraw: the same symbol is a different bank in the next section.

**Cost model.** Every instrument reports a cost in oscili units; the CLI prints
the estimated total (Σ cost × duration) and warns when a full-quality render
would be heavy.

### Findings

**The mode bank could not be normalised open-loop.** Solo-rendering each
category against the same score showed GONG peaking at 9.9 while everything
else obeyed the model — mode-filter gain depends on Q, pitch, and the draw,
and a constant calibrated at middle C was 7× wrong across the score's real
register. Fix: `balance` against a reference sine at the note's own amplitude
— self-calibration local to the instrument, verified 0.73–1.23× across
pitch × Q × draws. The master chain remains free of limiters; nothing about
the mix peak is hidden.

**pluck methods 4/6 require stretch ≥ 1** in iparm2; below that the note dies
with an init error. **`kr` is reserved.** Both caught by the per-template
smoke harness before integration — that harness is now test_p3.

**Budget top-up.** Pattern-size variance could leave a section 37% under its
note budget in a bad draw; sections now top up with single notes from
terminal occurrences the stride skipped. Max deviation measured after: 9%.

### Render cost (updated numbers)

Real instruments cost ~5× the placeholders. Measured, draft, sandbox:
N=40/4min/15% subset = 51 s (0.21× realtime). The N=300/10 min corner
estimates at **2.48 million oscili-seconds** — do not attempt at full quality
before Phase 5 density routing exists. `--draft` remains the working mode;
your machine is 2–4× slower than these numbers.

## 8. Phase 4 — effects and routing

**One routing struct.** Phase 0 left a comment saying the amp model "must stay
in sync with instr 99". That hazard is gone: `Routing` is the single
description of the signal chain, and both the generated master-bus Csound text
and the amp model's chain gain derive from it. There is no second description
to keep in sync.

**Topology, drawn per run:** 2–4 send buses, each feeding a chain of 1–4
effect units drawn from a 50-unit generated pool, each chain with its own
return gain, all returns summing into one wet bus — and `--wetdry` remains the
single global dry↔wet crossfade, per spec. Each instrument is wired to one
send bus at generation time (interpretive: the p-field contract stays fixed —
p7 is still the one send amount — and per-section instrument rebinding is what
moves material between tanks). Chain 1 always begins with a room-class reverb:
the room-bearing unit, whose feedback and cutoff the L3 room table steps at
section boundaries exactly as before. The CLI prints the drawn topology.

**Effect families:** shimmer reverb (reverbsc with an octave-up feedback loop
through a two-tap crossfading delay-line shifter UDO), spring reverb
(dispersive allpass cascade with a resonant boing band), phaser, flanger,
resonant bandpass sweep, tape-stop interpolated delay (the read pointer
decelerates and snaps back on a drawn cycle), and the **bitcrushed bus-channel
convolution**, literal per spec: channel R is decimated (900–4000 Hz) and
quantised (5–8 bit) into a cyclically-refreshing kernel table, and channel L
is `dconv`-ed against it.

**The no-limiter guard now greps the entire generated master text.**

### Findings

**The pitch shifter was shifting to DC.** Output rate = 1 − d′(t); an octave
up needs the tap delay to *shrink* at one second per second, and the first
version's tap grew instead (rate 0). Caught by a test that measures 2·f0
energy in the tail of a rendered sine — not by ear, not by eye. The shimmer
now provably produces octave-up energy.

**Hot-corner behaviour verified:** `--space 1 --wetdry 1` with shimmer
feedback at maximum renders within the model's normal error band. Feedback
figures are capped at 0.92 and dcblocked throughout.

### Listening runs

```
python3 -m orange_fur --nodes 24 --duration 4 --draft --out ~/Desktop/of_p4.wav
python3 -m orange_fur --nodes 24 --duration 4 --wetdry 0.85 --space 0.9 --draft --out ~/Desktop/of_p4_wet.wav
python3 -m orange_fur --nodes 10 --duration 12 --draft --out ~/Desktop/of_p4_sparse.wav
```

The CLI prints the drawn fx chains for each run — listen with the printout in
hand. The wet run is where the shimmer, tape-stops, and bus convolution are
most audible.

## 9. Phase 5 — gestures, macro-dynamics, glide, density→cost routing

**The p-field contract grows two fields, additively** (p1–p9 unchanged;
every pre-Phase-5 score renders identically):

    p10 glide   pitch-glide target as an OFFSET IN SCALE DEGREES (0 = none)
    p11 curve   transeg curve for the glide (0 linear, ± convex/concave)

Every instrument's fundamental is now a k-rate glide, and templates with baked
partial frequencies (banks, tuned clouds, mode banks) multiply their whole
spectrum by the glide ratio `kgl = kcps/icps` — a gliding bank slides rigidly
and stays in tune with itself. Tuned-cloud partials get a k-rate Nyquist clamp,
since an i-time guard stops meaning anything once the spectrum can slide up.

**The gesture vocabulary** (new L4 families): `GLISS`, `CLOUDGLISS` (all grains
glide one common direction — the cloud slides), `DIVERGE` (glide targets fan
out symmetrically — the cloud opens), `SWEEPCLICK` (one long swept note,
non-gliding clicks scattered along it), `BURSTSEQ`, `LOOP` (a cell repeated
verbatim), `LONGDECAY`, plus the strengthened `OSTINATO` and `TRILL`. Grains
use the terminal's *own* category instrument — a cloud glissando of plucks is a
cloud of plucks — so the category contract survives untouched.

**Slow Euclidean rhythms as higher-order control** (`macro.py`). Bjorklund
E(k,n) patterns at periods of seconds, four concurrent tracks per section:
ACCENT (a macro-dynamic gain contour rising into each accent), GESTURE (its
onsets advance a drawn playlist of the families above, overriding the inner
node's L4 — this is what actually *sequences* the vocabulary), DENSITY (culls a
drawn fraction on off-slots, opening and closing the texture), REGISTER (steps
the tessitura on a slow staircase). Maximally even, never regular unless k
divides n: it organises without gridding. The CLI prints all four patterns and
the per-section gesture playlists.

**Density → cost routing** (`--cost-cap`, default auto = 1200 × duration).
Notes are ranked by local polyphony and rebound, densest first, to the cheapest
instrument in their *own category* until the estimated render cost fits the
cap. It never changes a category and never culls — culling is the density
track's compositional job; this is a rendering-cost decision, kept apart on
purpose. N=300/10 min drops ~2.9M → ~0.86M oscili-seconds (the floor: every
note on its category's cheapest voice — reported honestly when the cap is
unreachable). Expect roughly an hour of draft render in that corner on this
machine class; `--cost-cap -1` disables routing.

**Gap bridging.** The density track and gesture slots can align into a 15–25 s
hole with nothing but the air bed in it. Holes are legitimate; dead air is not:
any uncovered stretch longer than max(8 s, 3.3% of the piece) — coverage
computed from actual ring-down, not p3 — gets one quiet long swell spanning it.
Bridges are reported.

### Findings

**A Phase 3 bug, exposed only by glide.** The sync templates fed the master
oscillator's own sync output back into its sync input, so it reset itself every
cycle and its frequency was frozen — inaudible while every note held a fixed
pitch, because the frozen frequency was the note's own. A one-octave glide
measured a pitch shift of exactly 1.00. The master now takes no sync input;
only the slave takes the master's pulse. That is what hard sync means.

**Measuring glide is harder than implementing it.** Spectral centroid lies
(bandlimited oscillators lose harmonics as f0 rises); spectral peak lies (it
jumps between partials); a log-spectral-shift correlator locks onto burst's AM
comb. test_p5 uses two metrics with disjoint blind spots — energy migration
f0→2f0, and the log-shift correlator — and every one of the 16 templates is
verified to glide *in the rendered audio*.

**Per-template drive in the amp model.** The envelope class is a property of
the template, not the category: CLOUD contains both a sustained `burst` and a
struck `tick`. Struck templates (RatPop excitation, resonators ringing down on
their own Q) are modelled with their ring-down constants; RatComp swells are
modelled with the actual RatComp shape (the product of two RatWins, peaking
early and decaying). Mispredicting this was invisible at Phase-4 note lengths
and became an 11 dB error the moment LONGDECAY stretched a gong to a minute.

### Listening runs

```
python3 -m orange_fur --nodes 24 --duration 4 --draft --out ~/Desktop/of_p5.wav
python3 -m orange_fur --nodes 24 --duration 5 --wetdry 0.7 --space 0.8 --draft --out ~/Desktop/of_p5_wet.wav
python3 -m orange_fur --nodes 60 --duration 6 --subset 60 --draft --out ~/Desktop/of_p5_big.wav
```

Listen with the printout in hand: the `gestures` line is the piece's
sequence of glissandi, diverging clouds, sweeps, loops and long decays, and the
`macro` line is the slow clock they run on.

## 10. Phase 6 — integration: long form, release master, final surface

**Two render modes, and that is the whole surface now:**

    --draft      48 kHz, ksmps=16. Iteration. Feedback-loop timbre is
                 approximate (ksmps=16 changes any sample-accurate loop).
    (default)    RELEASE: renders at 96 kHz with ksmps=1, then decimates to a
                 48 kHz deliverable with a 255-tap linear-phase half-band FIR.

Why oversample: the orchestra is full of nonlinearities — rational shapers,
hard sync, feedback, the bitcrushed bus convolution — and at 48 kHz their
harmonics alias back into the band *during synthesis*, baked in permanently.
At 96 kHz the junk lands in the top octave, and the decimator removes it
(passband intact, folded content measured >100 dB down; test_p6 proves it on a
synthetic alias). The decimation needs numpy; without it the render still
completes and the file is honestly left at 96 kHz with a note.

**Long-form mode.** `--sections 0` (now the default) draws the section count
from the duration — a 4-minute piece gets 3–5 sections, a 45-minute piece
18–32 — so the L1 grammar keeps meaning something at any length. An explicit
`--sections N` is honoured untouched. The note budget is N² *by contract* and
does not scale with duration; the CLI now prints a `density` line
(notes/minute) so the nodes choice for a long piece is an informed one — a
45-minute piece wants nodes 60–150, not 24.

**The manifest.** Every run writes its full report — drawn fx topology,
gesture playlists, macro tracks, cost routing, render stats — to a `.txt`
beside the `.wav`. On a 45-minute render the printout is the documentation of
what was drawn; it no longer dies with the terminal.

**Defaults after the sweep:** nodes 24, duration 5 min, wetdry 0.35,
space 0.5, subset 50%, sections auto, cost cap auto. Ten-corner sweep
(nodes 4–100, wetdry and space at both extremes, 12 explicit sections,
8-minute drafts): every corner completes, model error within ±5.7 dB, and the
N=4 corner correctly reports its constraint relaxation rather than failing.

### Findings

**The register staircase was unbounded** — dir × step × pulse-count reached
910 scale degrees by the end of an 8-minute section, ~75 octaves up, where
every note pins against the sr/2.2 guard. Invisible at Phase 5 lengths,
catastrophic long-form. The walk now reflects at a drawn ±7–17 degree span
(triangle fold): it still climbs and falls on the Euclidean clock, it just
stays on the scale. Belt-and-braces, the emitted pitch index also reflects
into basekey ± 3 repeat-intervals (~33 Hz to ~2.1 kHz fundamentals), and the
Phase 2 duration contract (≤ 100 s) is now an explicit emission invariant
instead of an accident of short pieces.

### Listening runs

```
# the default is now a release render:
python3 -m orange_fur --out ~/Desktop/of_p6.wav

# a long-form draft first, to hear the shape before committing hours:
python3 -m orange_fur --nodes 80 --duration 30 --subset 60 --draft --out ~/Desktop/of_p6_long_draft.wav

# then the long-form release (expect several hours on this machine class):
python3 -m orange_fur --nodes 80 --duration 30 --subset 60 --out ~/Desktop/of_p6_long.wav
```

Each render leaves its manifest (`.txt`) beside the file — the drawn topology,
the gesture sequence, the macro clocks. That text plus the tag in the filename
is the piece's identity; the RNG is entropy-seeded by spec, so the manifest is
the only record of what this run drew.
