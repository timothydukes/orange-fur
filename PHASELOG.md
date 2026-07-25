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

## 10a. Phase 7 — replay (v0.8.0)

One 64-bit seed, drawn from OS entropy at startup, now governs every draw in
a run and is printed in the report/manifest as `VERSION:HEX` — the replay
token. `--replay TOKEN` injects it and regenerates the identical piece
(csd-identical, verified in test_p7); a token from a different version warns,
since any change to RNG draw order changes what a seed means. The default
filename tag now derives from the seed, making the seed the program's only
entropy source. `--seed` remains a pure label. Consequences: draft→release
renders the *same piece*, manifests are recipes rather than descriptions, and
mix-side flags become remix knobs over a fixed composition. Every phase from
here inherits RNG stream discipline: new draws are appended at defined points
and documented per phase.

## 10b. Phase 8 — time window (v0.9.0)

`--from MIN --to MIN` renders a window of the piece. The full piece is
generated first — identical RNG stream, cost routing, and amp gains — and the
window is a post-generation transform, so a `--replay` token windows the
composition it names (slice parity is tested: every interior note appears
shifted with identical p-fields). Edge policy: notes sounding at `from` enter
with start clamped and remainder duration; struck notes whose attack lies
more than 3·tau before the edge have rung out and are skipped; all tails end
at window + 12 s, inheriting the full-piece bus-close contract (the first
implementation let a 40-second tail keep the performance alive past the
closed bus — half a minute of rendered silence on every audition). The room
active at the edge carries in as the t=0 room. Levels come from the
full-piece model; post-render normalization still applies but is labeled
audition-only. Long-form workflow: spot-check minute 12–15 at release
quality without rendering the other 27.

## 11d. Phase 18 — varispeed (v0.20.0)

Tape-speed automation, gated by `[echo.varispeed]` (additive to schema 1 —
existing spec files stay valid; disabled by default; fixed draw layout, so
enabling it never re-rolls a piece). A per-section speed curve from three
gestures on a Bjorklund segment grid: hold, slow sweep (log-linear — the
hand-on-the-reel move, constant cents per second), and silent jump (speed
steps at the boundary; a note spanning one keeps its own trajectory). The
physics is the tape's: times remap through T(τ)=∫dτ′/s — EXACT piecewise
closed form, after the trapezoid draft lost 12.5 ms per jump discontinuity —
pitch at 1200·log₂(s) cents on p12, within-note speed change on p13. Speed
targets drawn symmetrically in log, so warped material neither runs long
nor short systematically.

One scope error found by the tests and worth remembering: the first draft
warped tape loops too. Loops are PROTECTED PROCESSES (P10), and the
transport is a decoration-layer treatment — a warped loop's printed
realignment time would be a lie and its phasing identity bent. Varispeed
now touches echo trains only; the `--echo 0` csd-identity test (which loops
survive) is what caught it, and it doubles as the proof that any two specs
still share a replay token exactly as P17 promised.

## 11c-1. GUI 0.19.1 — spec-save fix (found by the manual checklist)

Tim's checklist pass caught exactly the class of bug the widget/logic split
predicted would hide from machine tests: "Save .toml + use" opened the
panel, then silently did nothing. Cause: the file dialogs used a bare
`"*.toml"` wildcard — wx requires "description|pattern", and wxOSX asserts
when applying the malformed filter, killing the handler AFTER the native
panel closes; wx swallows handler exceptions, so no file, no flag, no
error. Three fixes: proper wildcard strings on both dialogs; both handlers
now surface ANY exception in a message dialog (a silent no-op is itself a
bug, and the checklist says so); and `ensure_toml_ext`/hardened `save_spec`
in the HEADLESS layer (macOS panels return extension-less names; parents
created; the written path returned) — so the fix's logic is machine-tested
even though its trigger was not machine-testable.

## 11c. GUI phase (v0.19.0)

A wxPython front-end that is deliberately NOT a second implementation: it
builds a command line, shows it verbatim, and runs the CLI as a subprocess
— GUI and CLI cannot disagree, tokens travel in both directions, cancel is
a process kill. One window, four tabs; the preview window (`--from`/`--to`)
is the FIRST group on the Generate tab, per its priority for spot-checking
long pieces. Every render is auto-recorded in a JSON library with its
token, command, and output path; keepers get a marker, prune removes the
rest; any entry loads back into the Generate tab for remixing. The Echo tab
edits an EchoConfig and round-trips through the Phase 17 loader — a
GUI-written spec and a hand-written spec are one format, enforced by
save-time validation. New CLI flag `--subset-cat NAME=PCT,...` (per-category
subset percentages; a generation parameter like `--subset`). wxPython is
optional — guilib (the logic layer: command building, validation, TOML
writer, library) is wx-free and fully machine-tested; the widget layer
ships with MANUAL_GUI_CHECKLIST.md, since the development sandbox has no
display. That split is the honest testing boundary.

## 11b. Phase 17 — echo expansion (v0.18.0)

"More echo": the liminal space between instrument and score, where rhythm
emerges from delay arithmetic. Four timing families — uniform (P9),
multitap (a drawn tap cell repeating and decaying: the delay is a composed
rhythm), euclid (taps on a Bjorklund pattern, reusing the macro machinery,
so echo rhythm and accent rhythm share a language), and ramp (geometric
delay contraction/dilation with pitch coupled to the tape physics,
cents/repeat = −1200·log₂(ratio) — the Phase 4 sign-error equation now on
the right side of the ledger — and each echo note's p13 gliding toward the
next repeat's pitch: a train that is neither rhythm nor glissando but
both). Pan modes (ping-pong, rotate), second-order echoes (deterministic
consequence of the plan, capped), and every previously-hardcoded weight,
all governed by a versioned, strictly-validated TOML `--echo-spec` (unknown
keys rejected; stdlib tomllib with a bundled fallback; the GUI writes the
same format). One schema deviation from the approved draft, forced by
TOML: family weights live in [echo.timing.weights], since a scalar and a
table cannot share a key.

The strictest stream-discipline application yet: draw_plan consumes a
FIXED layout of draws per section — every family's parameters, all tap
slots, pan, second order — regardless of the config, so ANY two specs (or
none) share a replay token, verified by RNG-state equality and by
csd-identity at --echo 0 under different specs. No config = the P9–P11
distribution, verified distributionally over 200 seeded draws.

## 11a. Phase 16 — p13 cents glide (v0.17.0)

The last p-field: **p13 = cents glide, a DELTA** — a note's detune travels
from p12 to p12 + p13 over its duration, sharing the p11 curve with the
degree glide (one frequency trajectory, one transeg). Delta encoding is the
compatibility doctrine applied to a contract: an absolute end-cents p13
would have made 0 mean "glide back to the lattice," silently changing every
detuned note; as a delta, p13 = 0 is Phase 15 bit-exactly, and the change
lives in the one shared _head block.

The phase closes Phase 15's flagged limitation in both places it lived: a
whole-degree glide arrival in a spectral section now carries its target's
cents (detg = target cents − start cents), and echo-cascade arrivals
re-derive detg onto their own stepped target. Verified in rendered audio
against the transeg evaluated AT THE MEASUREMENT WINDOW: pure cents glide
matched the window-predicted ratio within 0.4%%, static p13 = 0 held within
2.5 cents, and a combined degree+cents glide followed the single predicted
trajectory — the first test draft compared endpoints and "failed" a correct
implementation, a measurement lesson worth recording. Unlocks: exact
spectral voice-leading now; the P17/P18 echo and varispeed machinery next.

## 11. Phase 15 — spectral fields (v0.16.0)

The new arc opens with its foundation: fields may now be SPECTRA. Two drawn
families join the Phase 13 lattice draw — `sumdiff`, ring-modulation harmony
after Grisey/Murail (two generator degrees; the field is their sum and
difference tones and low-harmonic combinations; generator-interval
simplicity is the consonance knob), and `vf`, instrumental synthesis (a
virtual fundamental under a harmonic, stretched, or compressed partial
model; the section is a chord that is a timbre). Both compute target
FREQUENCIES and express each as nearest lattice degree + cents residual
riding p12 — the sonority is the true spectrum exactly (verified in
rendered audio to 0.3 cents through the full snap→p12→render path), and
the .scl lattice becomes the grid the spectrum is measured against rather
than the pitch authority.

The snap contract is now (index, cents) at every emission site; f 901 grew
cents columns and the resonator units multiply cpstun by 2^(c/1200), so
the tanks ring on true partials (click-test verified). One found bug:
sub-register difference tones snapped to boundary indices with impossible
residuals (+111c) — a target's residual can never exceed half the tuning's
largest step, and that cap is now derived from the scale and enforced.

Compatibility per the doctrine: `--spectral 0` (the default) draws every
section on the lattice with zero cents everywhere — pre-P15 behavior — and
because lattice AND spectral parameters are drawn unconditionally each
section with the lattice chain advancing regardless, any two `--spectral`
settings share a replay token: the same piece skeleton, harmony realized
on or off the lattice. Known limitation, flagged: glide targets land on
the field degree but cannot yet glide to its cents — p13 (Phase 16)
closes it.

## 10h. Phase 14 — scale-tuned resonators (v0.15.0)

The arc's final phase, and its compound payoff: effect units that ring on
the harmony. Two new pool units — `streson` string resonators (2–3 voices,
room-class, may lead the reverb chain) and a 4-voice `mode` bank — tuned at
runtime from `f 901`, a score-written table of each section's field degrees
(the exact `f 900` rooms mechanism: k-rate row scan by time, per-unit
cursor, `cpstun` into the tuning table, portamento on retune). Routing is
drawn before the score exists; the table indirection is what lets a
pre-drawn chain ring on fields that haven't been drawn yet.

Phase 3's lessons applied at construction, and verified in audio: feedback
railed at 0.92 across all draws with a worst-case 14 s decay test (no
runaway); `mode`'s resonance gain scales with Q, so makeup is 1/(2Q) per
voice (the 1/√Q seed left +5 dB at Q 150 in the click test); classic
(1−fb)/n makeup on streson; dcblock + 45 Hz highpass hygiene. The click
test pins the ring to a tuned field degree (or harmonic) within 1%, and the
retune test proves the ring MOVES at a section boundary and lands on the
new field. One found-and-fixed: `portk`'s state initializes at zero, so
every resonator glided up from silence for its first seconds — the
half-time now ramps from 0 (instant tracking at init) to its drawn value.
The windowed-render path trims `f 901` with the same helper as the room
table. New table in every csd; no flags; presence rides the replay token.

## 10g. Phase 13 — harmonic fields (v0.14.0)

Sections acquire harmonic identity: a per-section pitch-class field (3–7
degrees, anchored on 0, chained so ~half the tones carry over — voice-
leading, not teleportation), enforced by ONE composed snap(fold(i)) applied
at every pitched emission site. Enumerating those sites was the phase's real
work: patterns, budget top-ups, the guaranteed SWELL carrier, gap bridges
(snapped by the field active at their own start, not the last drawn one —
the closure would otherwise leak the final section's field), glide
arrivals, echo cascades, tape-loop cells, motif quotes. Two findings: (1)
echo trains inherited glide offsets relative to their SOURCE index, so a
degree-cascade echo's arrival left the field until the offset was re-derived
through the fold; (2) notes spilling across a section boundary conform to
the field that EMITTED them — suspensions, documented as semantics rather
than patched as leaks (a few per cent of events at boundaries; the tests
assert union-membership always and ≥95%% wall-clock conformance).

Interpretive decision, flagged at the gate: motif quotes and loop cells
CONFORM — contour and rhythm carry the memory, pitch content joins the
present harmony. The opposite policy (quotation fidelity) is one line.
Sub-degree ornamental bends and p12 cents ride above the field: the field
constrains the degree lattice, not the microtones. `--fields 0/1` share a
replay token — snapping consumes no draws.

## 10f. Phase 12 — motif recurrence (v0.13.0)

The system has always morphed forward without looking back; now a piece has
a MEMORY. Capture is deterministic — the first MAX_BANK (4) qualifying
phrases become the bank, consuming zero RNG draws, so replay stability holds
by construction: what the piece remembers is what it said first. Quotation
is L1-driven (CHORUS and OUTRO quote most; INTRO structurally cannot) with a
fixed draw count per section; transforms are transpose / invert (around the
first degree) / retrograde (pitches AND rhythm) / augment (rhythm and
durations together), and every quote is named in the report
(`T+7+inv@m0`). Quotes inherit the Phase 10 protected-process rule exactly
as planned — echo = −3, proc id, atomic cost routing, cull/register bypass,
accent applies.

The promised coupling lands: about half of tape loops build their cell from
a motif (rhythm compressed into the loop period), and quotes pass through
the ordinary echo-decoration draw — so the tape machinery stops processing
arbitrary material and starts processing the piece's own past. A remembered
phrase can return as a phasing loop, a klangfarben cascade, or a
cents-drifted train.

## 10e. Phase 11 — rotating-timbre delay (v0.12.0)

Tape-music arc C, built on the Phase 9 emitter. About 35%% of sections draw a
ROTATION: each echo generation k sounds on instrument cycle[(k−1) mod len] of
a drawn 2–4-voice cycle — klangfarben echo, the clearest case where the
score-domain delay beats the audio-domain one, since no audio delay can
rotate through an orchestra. The cycle is drawn per category, up-front, with
a fixed draw count whatever the pools contain (stream discipline, tested by
comparing RNG state across full and empty pools), and only ever from the
source's own category — the contract is now category-level: an echo never
leaves its source's category but need not keep its instrument (test_p9
amended accordingly). Amplitudes are INSTR_PEAK-compensated (clamped 0.25–4)
so the heard decay follows the feedback curve while the calibration spread
of the rotating instruments cancels; pitch and rhythm stay strict while
color cycles, which is what keeps the echo an echo. Decay-time gestures
(up / down / arch / flat, drawn) scale each pattern's repeat count by
section-relative time: tails lengthen toward a climax or shorten as a
phrase dries out. No new flags; both properties ride the replay token.

## 10d. Phase 10 — tape loops (v0.11.0)

Tape-music arc B: looping tape delay with phase drift, 100%% in the score.
Per section (drawn unconditionally, emitted at gong-class rarity) two or
three loop voices repeat a 2–5-note cell at periods T and T(1+ε): the
accumulating offset is the phasing mechanism — microtiming as a first-class
score dimension — and the realignment time T/ε is computed at generation and
printed in the report, the piece's formal event predicted in text. The first
eps draw was blind (0.2–2%%) and every realignment landed minutes past the
loop's end; ε is now drawn against the section — 65%% of draws pick the
realignment time directly (0.55–0.95 of the loop's run, so the canon
completes inside it), 35%% keep the slow-smear band where drift is felt, not
resolved.

**The protected-process rule** (established here; motif recurrence inherits
it): a phasing loop reads only if its cell is perceptually identical every
pass, so loop notes bypass the macro density cull and the register
staircase, are excluded from echo decoration, and carry a process id that
**cost routing honors atomically** — all of a loop's notes rebind to the
same instrument together or not at all. The accent contour still applies:
macro-dynamics sequencing a loop's loudness is musical; dynamics don't
threaten identity. Loop notes are marked echo = −2 (outside the N² source
budget, like decoration); cells never draw GONG (the gongs-rare contract
outranks the loop). No flag: loops are composition, not mix, and ride the
replay token.

## 10c. Phase 9 — score-domain delay + p12 (v0.10.0)

The tape-music arc begins. **p12 = detune in cents** enters the p-field
contract — the first officially off-scale pitch. It multiplies the tuning
lookup, and `kgl` is computed against the raw lookup so baked-partial
templates (banks, tuned clouds, mode banks) ride detune rigidly, exactly as
they ride glide; measured in rendered audio at ratio 1.0595 for +100 c on
sine, PWM, and bank templates alike. p12 = 0 is bit-identical to Phase 8.

**echoes.py**: a delay line made of score. Per section a treatment is drawn —
plain repeat, degree cascade (steps in *scale degrees*, folded), octave
spiral, or cents drift (a feedback path that is a microscopic transposer) —
with delay 100–1000 ms and feedback 0.4–0.8, and a drawn fraction of phrases
spawn decaying trains: the delay processes phrases, not samples, and every
echo is a note the whole system can see.

**A design fork, resolved for replay.** Counting echoes against the N²
budget ("more repetitive, not bigger") made `--echo` a generation parameter —
changing it changed the source composition, and a replay token no longer
named one piece. The remix-knob property won: the budget governs source
notes, echoes are decoration on top, and `--echo 0/1/2` provably leaves the
source composition untouched (tested at the Event level; bridges and cost
routing legitimately adapt). Echo draws are made unconditionally so the RNG
stream is identical whether or not trains are emitted.

**The amp model met coherence for real this time.** Same-pitch echoes of
tonal notes put partials at identical frequencies; the incoherent model
under-predicted echoed pieces by ~8 dB, the full amplitude-sum bound
over-predicted by as much (183.1 cycles of delay is not phase alignment).
The model now sums tonal notes sharing (instr, pitch, detune) as
COH·(amp sum)² + (1−COH)·(power sum), COH = 0.6, deliberately biased toward
over-prediction — the safe direction, since normalization is exact.

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

## Phase 19 (v0.21.0) -- roughness -> rewriting (`--tension`)

- `roughness.py`: Plomp-Levelt pair dissonance (Sethares constants,
  verified against the published curve: unison 0, peak ~25 Hz separation
  at 400 Hz, monotone falloff); sonority roughness sums CROSS-NOTE partial
  pairs only (a note's internal roughness is timbre, not harmony).
  `Instrument.partials` annotated inline where templates hold literal
  partial lists (bank, modal, tcloud, bankswell); template-class spectra
  for the rest.
- Per-run calibration: K=64 reference sonorities -> interpolated empirical
  CDF; all targets/scores/reports are percentiles of the run's own
  roughness. The step CDF's 1/64 granularity tied 35% of scoring calls;
  interpolation fixed it.
- Tension segments per section (flat/rise/fall/arch), chained; rise/fall
  enforce their direction by moving the END only, preserving the chain.
- Three levers: (a) field selection among 8 same-shape candidates;
  (b) phenotype repair, <= min(8, 25% of vocabulary) most-frequent
  terminals; (c) note-level base-degree choice among 3 candidates vs the
  sounding set. Selection is deterministic and draw-free:
  eff = x*score + (1-x)*[candidate 0], so `--tension 0` IS the pre-P19
  path and all values share a token.
- THE CHAIN ADVANCES ON CANDIDATE 0: `draw_field`'s shuffles consume
  draws proportional to the previous lattice's size, so chaining on the
  SELECTED field made the next section's draw layout depend on
  `--tension` and broke token sharing (found by the skeleton test -- 750
  echo notes vanished; located by RNG call-site forensics). P15 precedent
  extended: the lattice chain is skeleton domain.
- PC-HARMONY DOMAIN (design reversal, measured): the approved design
  scored (b) with each terminal's own instrument spectrum. Three
  calibration/scoring domains later, the closed loop only worked with
  calibration, scoring, and measurement in ONE domain: distinct sounding
  pitch classes at the basekey octave, common spectrum, measured over a
  +/-1.5 s window. Mixed-register/mixed-spectrum scoring left the
  mechanism statistically inert (lever ceiling 0.08); the pc-domain +
  windowed measurement reaches separation +0.20 at `--tension 1` vs
  -0.02 natural. Per-instrument partials remain on `Instrument` as
  analysis infrastructure.
- P18 BUG FIXED (shipped in v0.20.0): the varispeed warp block sat BEFORE
  the section's pattern-emission loop, so it only ever warped QUOTE echo
  trains -- pattern echo trains were never warped. The warp, the tension
  measurement, and the macro log now run after emission. Unit tests had
  verified `warp_events` in isolation; the e2e suite checked determinism
  and token sharing, not which notes moved. Lesson recorded: code
  placement relative to emission loops must be verified against the loop,
  not assumed from adjacency.
- Test amendments: test_p15 wall-clock conformance band 0.15 -> 0.22
  (P19 stream shift re-rolled the fixed seed to the observed cross-seed
  maximum 0.165; measured 0.00-0.165 over 8 seeds, union-exactness still
  strict). Perf bound set from measurement: +21% generation-time overhead
  at nodes=40 (`--tension 1` vs 0), bounded < 40% in tests -- the design
  estimate of 15% was optimistic before the pc-domain reduction cut
  scoring cost.

## Phase 20 (v0.22.0) -- SURFACE category (`--surface`)

- Seventh solver category, flag-gated per the compatibility doctrine: at
  `--surface 0` the solver runs the six-category P1 path byte-for-byte
  (RNG-state + terminal-assignment equality tested), and `generate()`
  skips the family entirely (SURFACE is the last enum member, so no
  numbering shifts). `--surface PCT` = target terminal share (bare flag =
  20); a GENERATION parameter -- tokens do not cross the flag (tested).
- Assignment: the clustered occurrence slice after PARTIAL/TCLOUD -- dense
  clusters land on cheap surface noise BY ASSIGNMENT, the honest
  resolution of the node~100 sameness problem. Measured: densest-decile
  instrument diversity does not degrade and typically improves at
  nodes=60.
- Orchestra 7xx, 18 instruments/run over four templates (core opcodes
  only; the dust opcode is NOT relied on): crackle (logistic map gating
  tuned reson noise), dustpop (jittered impulse train, popping VCA,
  tuned reson), hiss (butbp noise floor, wobble, ticks), transwash
  (noise burst through a swept butbp, i-rate expseg endpoints x kgl --
  expseg args are i-rate, the sweep tracks glide via the ratio).
- B7 envelope classes drawn per instrument: burst / emergence / reverse;
  new RatRev UDO (rational rise, instant terminus), i-rate args per the
  Phase 0 rule. Amp-model approximation: emergence/reverse are tail-heavy
  vs the sustained-window assumption; absorbed by the model band, stated
  here rather than hidden.
- Plumbing: phenotype rows (long-ish, quiet, roomy); LOOP_CATS gains
  SURFACE only when the flag is on (a 5-element rng.choice changes
  OUTCOMES at off -- the list is conditional, draw count unchanged);
  motif capture excludes SURFACE-only phrases; LONGDECAY remapped to
  SUSTAIN for SURFACE (duration ceiling ~45 s on the SWELL precedent,
  noise floors remain --air's job); P19 spectra proxies; GUI Surface
  spinner; placeholder CAT_TO_INSTR maps SURFACE to the CLOUD placeholder
  for catmap=None paths.
- test_p3 amended: default-orchestra category checks cover the six
  always-on categories (SURFACE is flag-gated, own suite in test_p20).

## Phase 21 (v0.23.0) -- dynamics presets (`--dynamics`)

- {default, quiet, mid, limited}: every preset a PURE MAPPING of drawn
  values (zero draws -- RNG-state equality tested), so --dynamics is a
  remix knob: one token, four readings; skeleton identity across presets
  tested. `default` = identity, csd-identical to flag absent.
- One application site (the apply_window precedent): post-generation
  in-place amp map a' = clamp((m + (a-m)*var)*scale, 0.005, 2.0), m =
  the piece's mean source amp. Uniform over source/echo/loops/quotes:
  echo fb^k decay compresses under var < 1 (the "limited" percept);
  P10's dynamics-apply-to-protected-processes rule carries over.
- Accent contour: applied depth scaled per preset by post-draw mutation
  of plan.accent_depth (drawn contour untouched).
- Normalization target per preset (-12/-3/-1) unless --normalize is
  explicit (sentinel default None; -3 restored when absent). Rendered
  peaks verified within 0.5 dB of targets in e2e.
- No limiter anywhere -- "limited" is score-time range compression +
  exact rescale. Preset numbers provisional, listening-tunable in
  dynamics.py (the arc table's own caveat).

## Phase 22 (v0.24.0) -- slow dynamical macro-state (`--state`, D11)

- state.py: 4-D Kuramoto system, macro periods 60-480 s, drawn
  UNCONDITIONALLY with fixed layout (P9 house pattern) and integrated
  deterministically (Euler dt=0.25 s); observables 0.5+0.5*sin(theta),
  interpolated. All --state values share a token (remix class); absent
  = off = csd-identical.
- Five consumers, all no-draw modulations: fields (state term joins the
  P19 candidate scoring: eff = X*t + S*s + (1-max(X,S))*[cand0]);
  density (cull fraction x(0.4+1.2*o1) AND emission cap x(0.5+0.9*o1));
  register (reg_step/span x(0.5+o2), post-draw mutation); air (f 903
  (t, mul) table + instr 90 k-rate scan, all-ones when off); rooms
  (section_room near-tie tilt -- clear majorities immune, clean-cut
  rule intact).
- STREAM-DISCIPLINE HARDENING (found by CountingRandom forensics, the
  P19 tool): three budget gates made draw counts depend on
  notes_emitted, which the cull moves -- the density consumer desynced
  --state values. All budget gates are now EMISSION-ONLY: every draw
  (pattern jitter, glide, top-up starts) is consumed unconditionally;
  heads keep the old no-new-heads-past-budget rule. Discarded draws
  change no distribution; base-layout shift version-gated as always.
- Report: "state [consumers] SEC: o=[...]" per section; macro_log
  carries the observables into the manifest.
- Window path: air rows trimmed with trim_timed like rooms/sec_fields.

## Phase 23 (v0.25.0) -- continuous-morph form family (`--morph`, C8)

- morph.py: interior boundaries draw joints UNCONDITIONALLY (2 fixed
  draws each; first/last never admit); --morph X scales admission
  (state o0 modulates); windows = drawn 0.25-0.6 x mean section length
  (o2-modulated), clamped [12 s, 0.4 x shorter neighbor] -- Tim's
  requirement that windows adapt to total duration and section count.
  Remix knob: all values share a token; 0 = csd-identical to absent.
- Rooms crossfade (mechanism b, approved): f 900 rows widened by a LAG
  column (5-wide; 0 at cuts -- inaudible at --morph 0, the f 901
  precedent); joint rows start at t_b - w/2 with lag w/4; BOTH f 900
  readers (routing master + orc fallback) scan stride 5 and drive
  portk toward SEPARATE stepped targets (feeding portk its own output
  back compounds the lag -- caught in review). portk's internal state
  still starts at 0 (P14), so the first ~30 ms rise from narrow --
  inaudible at piece start, stated here. Verified by a DETERMINISTIC
  micro-render (piece-audio smoothness comparison was hop-noise flaky
  -- the P6 lesson; -W needs -f for float, ftgen args need commas).
- Field common tones: overlap term dominates candidate scoring at
  joints (x rises to 1; the no-draw P19 select); measured >=70%
  Jaccard at >=80% of joints.
- Overlap composition + seam glides: post-pass after ALL draws
  (bridges included -- coverage computed pre-morph; seam neighborhoods
  are dense); A's tail leans forward, B's head reaches back (affine
  onset remap); window source notes sustain (dur x up to 2, 100 s
  contract clamped); off-field notes glide to the incoming field's
  nearest tone. proc>0 and echo==-1 untouched.
- Macro deceleration: accent/density/register periods x1.5-2.5 at
  joint-adjacent sections. GESTURE EXCLUDED: its playlist advance
  selects L4 pattern types whose builders consume different draw
  counts -- stretching it desynced --morph values.
- TWO MORE STREAM-DISCIPLINE FINDINGS (CountingRandom forensics):
  (1) macro.culled() drew only on density-track off-slots -- a
  conditional draw hiding in a two-line method; now unconditional.
  (2) the gesture-period dependence above. With these, --tension,
  --dynamics, --state, and --morph are all proven stream-safe by
  RNG-state equality in the suites.
- Test amendments (justified in-file): test_p13 arrival conformance
  now honors the documented suspension semantics (spill arrivals may
  match the previous field within 8 s of a boundary; the new layout
  produced the first spill-heavy boundary); test_p20 density claim
  measured directly (SURFACE present in the densest decile) instead
  of the noise-floor distinct-instrument proxy.
- GUI: Morph spinner; Generate tab now a ScrolledWindow (right-hand
  scrollbar; the render log keeps its height); State field gained
  helper text listing the consumer options.
