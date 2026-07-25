# Orange Fur — User Guide

Every flag, organized as **territories to explore** rather than an
alphabetical list. Each territory gives the flags, sensible ranges, notes on
interaction, and example commands. Recipes and templates are at the end.

All commands run from inside the `orange_fur_p6` folder. Append `--draft`
while exploring; drop it for the keeper.

A useful habit for every territory: add `--dry-run` first. It prints the
entire report — sections, gesture playlists, macro tracks, fx topology,
density, cost — without rendering a sample.

---

## 0. The invariants (what no flag changes)

- **The score is exactly `nodes²` notes** (before density-track culling and
  the occasional bridge swell). Duration does not add notes; it spreads them.
- **Every fresh run is a different piece — and every piece is recoverable.**
  One 64-bit entropy seed governs all draws; the report and manifest print it
  as a replay token (`VERSION:HEX`), and `--replay TOKEN` regenerates that
  exact piece under the same code version. `--seed` remains a filename tag
  only. Archive the manifest with the wav: it is the piece's recipe.
- **Output level is exact.** Peak is set post-render to `--normalize`
  (default −3 dBFS) by a single lossless float rescale. No limiter, no
  clipper, anywhere.
- Six instrument categories are always in play — PARTIAL, TCLOUD, CLOUD,
  PLUCK, GONG, SWELL — with fixed structural roles (gongs rare but present,
  partials clustered, clouds dispersed).

---

## 1. Density and scale — `--nodes`, `--duration`

The territory that defines the piece more than any other.

| flag | range | default | notes |
|---|---|---|---|
| `--nodes N` | 2–300 | 24 | note count = N². Also alphabet size, graph size, structural richness. |
| `--duration MIN` | ≥ 2, no cap | 5.0 | minutes. Spreads the same N² notes over more or less time. |

Density = N² / duration. The CLI prints it as a `density` line (notes/min).
Rough bands:

| notes/min | character |
|---|---|
| < 15 | pointillist, silence-dominated (bridging keeps a floor under it) |
| 15–60 | sparse chamber texture |
| 60–200 | the default-ish middle: phrases, gestures legible |
| 200–800 | dense weave; cost routing starts moving notes to cheap voices |
| > 800 | mass/cloud music; individual notes stop existing |

Explorations:

```
# same duration, rising density: hear the texture change class
python3 -m orange_fur --nodes 8  --duration 3 --draft --out ~/Desktop/dens_a.wav
python3 -m orange_fur --nodes 24 --duration 3 --draft --out ~/Desktop/dens_b.wav
python3 -m orange_fur --nodes 60 --duration 3 --draft --out ~/Desktop/dens_c.wav

# same nodes, stretching time: same material, thinner air
python3 -m orange_fur --nodes 24 --duration 12 --draft --out ~/Desktop/stretch.wav
```

Notes:
- N=2–5 is structurally degenerate on purpose: the constraint solver will
  print a `RELAXED` line naming what it gave up. Interesting, not broken.
- N ≥ 150 with long durations is where `--cost-cap` (territory 5) matters.
- Long-form pieces want the density line consulted: 30–60 min sits well at
  nodes 60–150.

---

## 1b. Echo — `--echo`

The score-domain delay line. Each section draws a delay treatment — mode
(plain repeat, degree cascade, octave spiral, cents drift), delay time
(100–1000 ms), feedback — and a drawn fraction of its phrases spawn decaying
echo trains: every echo is a fresh *note*, on the tuning (or deliberately a
few cents off it, via the new p12 detune field), visible to the amp model,
the cost router, and the manifest.

| flag | range | default | notes |
|---|---|---|---|
| `--echo SCALE` | 0–3 | 1.0 | scales each section's drawn echo probability. **Remix-class flag**: the source composition is identical at every setting under the same replay token — 0 strips the echoes, 2–3 saturates them. |

```
# the same piece, three densities of its own echo
python3 -m orange_fur --replay TOKEN --echo 0 --draft --out dry.wav
python3 -m orange_fur --replay TOKEN            --draft --out asdrawn.wav
python3 -m orange_fur --replay TOKEN --echo 2.5 --draft --out saturated.wav
```

Notes: echo trains are where the piece acquires a pulse — 100–1000 ms is the
rhythm band. The `echoes` report line names each section's treatment; cents
mode is a delay whose feedback path is a microscopic transposer, beating
against the dry notes. Echoes multiply the event count (they are decoration
on top of the N² source budget); cost routing absorbs the render cost.

### `--echo-spec file.toml` — the echo control surface (Phase 17)

Fine-grained control of everything below: **timing families** — `uniform`
(the classic train), `multitap` (a non-uniform tap cell, repeated and
decaying: the delay is itself a rhythm), `euclid` (taps on a Bjorklund
pattern — echo rhythm and macro accent speak the same language), and `ramp`
(accelerating or decelerating trains whose pitch follows tape physics,
cents/repeat = −1200·log₂(ratio), each note gliding toward the next
repeat — neither rhythm nor glissando but both); **pan** (inherit /
ping-pong / rotate); **second-order echoes** (echoes of echoes, derived and
capped); plus the mode, rotation, and gesture weights that were previously
constants. See `examples/echo-spec.toml` for the schema. No file = the
pre-P17 distribution exactly, and **any two specs share a replay token** —
the same piece under different echo treatments. One TOML technicality:
family *weights* live under `[echo.timing.weights]`.

**Varispeed** (`[echo.varispeed]` in the spec, Phase 18): a per-section
tape-speed automation — hold / slow-sweep / silent-jump gestures on a
Euclidean segment grid — warps the section's echo trains: times through
the tape integrator, pitch at 1200·log₂(speed) cents, within-note speed
changes riding p13. Tape loops are protected from the transport (their
printed realignment arithmetic stays true). Additive to schema 1;
disabled by default; enabling it never re-rolls the piece.

Two further drawn properties (no flags): about a third of sections carry a
**rotating-timbre delay** — `rot(3)` in the report — where each echo
generation cycles to the next instrument of a drawn cycle from the source's
own category, INSTR_PEAK-compensated so the heard decay still follows the
feedback curve. Pitch and rhythm stay strict while the color rotates: a
klangfarben echo, which no audio delay can do. And a drawn **decay-time
gesture** (`tails:up` / `down` / `arch`) shapes train length across the
section — echo tails lengthen toward a climax or dry out with the phrase.

## 1c. Tape loops (no flag — drawn)

Rarely — gong-class rarity, roughly one section in six — a section carries a
**phasing tape-loop process**: two (occasionally three) loop voices of the
same 2–5-note cell at periods T and T(1+ε), near-100% feedback, panned
apart. The accumulating offset is the phasing: the cell slides against
itself through every intermediate canon, and when the drawn ε permits, the
voices audibly realign before the loop ends. The report predicts the
moment: `tape loop [VERSE] … realign at +38.7s (inside the loop)`.

Loops are *protected processes*: density culling, register stepping, and
per-note voice rebinding do not touch them (a loop's identity is its
unvarying cell); the macro accent contour still shapes their loudness, and
cost routing moves a whole loop atomically if it moves at all. There is no
flag: loops are part of the composition and ride the replay token.

## 1d. Motifs (no flag — drawn)

The piece now has a memory. The first few qualifying phrases it emits (3–6
notes, under 8 s) are captured as **motifs**, and later sections re-quote
them transformed — transposed, inverted, retrograded, augmented. Quotation
is L1-driven: CHORUS and OUTRO sections lean on the bank, INTRO can't (there
is nothing to remember yet). The report names every quote:
`motifs  bank of 3 captured; OUTRO: T+7+inv@m0, aug2.0@m2`.

Quotes are protected processes like tape loops (nothing culls or transposes
a quotation mid-cell; cost routing moves one atomically), and the tape
machinery prefers remembered material: about half of tape loops build their
cell from a motif, and quotes themselves can be echo-decorated — the
opening phrase may return as a phasing loop or a klangfarben cascade. All
of it rides the replay token.

## 1e. Harmonic fields — `--fields`

Each section draws a **pitch-class field** — a 3–7-degree subset of the
tuning, always anchored on the base degree — and every pitched emission in
the section conforms to it: patterns, glide arrivals, bridges, echo
cascades, tape-loop cells, motif quotes. Successive fields keep about half
their tones, so sections move by voice-leading rather than teleportation.
The report shows the harmony: `fields  INT: {0,2,5,7,9} | VER: {0,2,4,7,9}`.

| flag | values | default | notes |
|---|---|---|---|
| `--fields 0\|1` | 0 or 1 | 1 | 0 disables snapping. Same replay token either way — the same composition, harmonically constrained or free. |
| `--spectral PCT` | 0–100 | 0 | percent of sections drawing a **spectral field**: sum/difference-tone complexes (`sumdiff` — ring-modulation harmony from two generator degrees; small intervals = consonant, large = bell-like) or virtual-fundamental partial models (`vf` — harmonic, stretched, or compressed; the section is a chord that is a timbre). Targets are true frequencies, realized as lattice degree + cents (p12); the resonators ring on the exact partials. 0 = pure lattice, the pre-P15 behavior. Any two settings share a replay token: same piece, harmony on or off the lattice. |

Glides in spectral sections arrive on the target's exact frequency —
degree and cents together (p13, Phase 16).

Spectral report entries show the true targets: `{0,4+2c,7+6c} vf(harm)` is
the 4th and 5th harmonics of a virtual fundamental, each a few cents off the
Werckmeister degrees they are measured against.

Notes: motif quotes conform by design — contour and rhythm carry the
memory, pitch content joins the present harmony (a verbatim quote against a
changed field reads as a wrong note, not a memory). Sub-degree ornamental
bends and p12 cents detune ride *above* the field: the field constrains the
degree lattice, not the microtones. Notes spilling across a section
boundary keep the field they were conceived in — suspensions, and audibly
so.

## 1f. Scale-tuned resonators (no flag — drawn)

Two resonator effects join the drawn bus pool: **string resonators**
(`streson` voices, room-class — one may lead the reverb chain) and a
**modal bank** (four `mode` filters). Both are tuned at runtime to the
current section's harmonic-field degrees via a score-written table, so the
tank always rings on the harmony that is playing — send-heavy material
excites sympathetic resonance on the same degrees the score-domain delays
and field-conformant patterns are using, and the ringing *retunes at
section boundaries* with a short portamento. Feedback is bounded at build
time (0.92) and resonance gain is calibrated; there is nothing to blow up
and nothing to set. Whether a piece draws them is part of the composition
and rides the replay token.

## 1g. GUI and per-category subsets

`python3 -m orange_fur.gui` — see README for install. Two CLI additions
shipped with the GUI phase:

| flag | values | notes |
|---|---|---|
| `--subset-cat SPEC` | `NAME=PCT,...` | per-category subset percentages, e.g. `GONG=100,CLOUD=10`; unnamed categories inherit `--subset`. **Generation parameter**: must match for `--replay`, like `--subset` itself. Categories: PARTIAL, PLUCK, GONG, CLOUD, TCLOUD, SWELL. |

The GUI's echo tab reads and writes the `--echo-spec` schema-1 TOML —
GUI-written and hand-written files are one format.

## 1h. Tension — `--tension` (Phase 19)

`--tension X` (0-1, default 0) runs a per-section ROUGHNESS TRAJECTORY
(flat / rise / fall / arch, chained across sections) and biases three
levers toward it: which harmonic field a section selects (the dominant
lever), phenotype repair of the most frequent terminals, and note-level
base-degree choice. Everything is measured and scored in one pc-harmony
domain against a per-run calibration. At 0 the selection path is exactly
the pre-P19 draw; all values share a replay token (same piece, harmony
steered or free). The report prints per-section intent vs achieved:
`tension INT: 0.18->0.06 fall (ach 0.11)`.

## 1i. Surface — `--surface [PCT]` (Phase 20)

A seventh instrument category: surface noise — crackle (logistic-map
chaos), dust-pop impulse trains, band-filtered hiss, swept filtered
transients — synthesized from core opcodes, cheap by construction, with
drawn envelope classes (burst / emergence: the sound arrives over
85-98% of the note then cuts / reverse: a rational rise into an instant
terminus). Pitch is a COLORATION CENTER: resonant filtering tracks the
note's tuned frequency, not an oscillator fundamental.

`--surface PCT` (0-100) is the target share of terminal symbols assigned
to SURFACE; bare `--surface` = 20. The category enters the SOLVER — the
clustered occurrence slice lands on it, so dense passages get cheap
textured variety by assignment. Absent/0 = the six-category solver
byte-for-byte. UNLIKE the other flags in this file, `--surface` is a
GENERATION parameter (with `--nodes`/`--subset`): it must match for
replay, and tokens do not cross the flag.

## 1j. Dynamics — `--dynamics` (Phase 21)

`--dynamics {default, quiet, mid, limited}`. Pure remapping of drawn
amplitudes — zero draws, so one replay token gives four dynamic readings
of the same piece. `default` = identity, csd-identical to the flag being
absent. quiet: everything down ~x0.45, full dynamic range, normalize
-12 dBFS. mid: moderate level, range compressed x0.6 toward the piece
mean, -3 dBFS. limited: range x0.25, accent contour flattened x0.3,
-1 dBFS — the "mastered loud" reading with NO limiter anywhere
(score-time mapping plus the exact post-render rescale). Presets move
the normalization target; an explicit `--normalize` wins. `limited`
lifts echo-train tails toward the ensemble mean — fb^k decay compresses;
that is the preset's character. Preset numbers are listening-tunable in
`orange_fur/dynamics.py`.

## 1k. State — `--state [LIST]` (Phase 22)

A hidden 4-dimensional coupled-oscillator system — slow weather at
1-8-minute periods — is drawn in EVERY piece (fixed draws, so all
`--state` values share a replay token). The flag chooses who reads it: a
comma list from `fields` (harmony brightness drifts on the state, even
at tension 0; composes with `--tension`), `density` (the cull fraction
AND the section emission cap breathe), `register` (the staircase's ambit
expands and contracts), `air` (the noise floor swells and recedes),
`rooms` (near-tie room votes rotate with the state; clear majorities and
the clean-cut rule untouched). Bare `--state` = `all`; absent = off,
byte-identical. The report prints the per-section observables:
`state [all] INT: o=[0.37 0.90 0.99 0.05] | ...`.

## 1l. Morph — `--morph [X]` (Phase 23)

The continuous-morph form family, the arc capstone. Interior section
boundaries draw whether they become MORPH JOINTS instead of clean cuts;
X (0-1) scales admission (bare `--morph` = 0.5; 0/absent = the clean-cut
world byte-for-byte; all values share a token). A joint's window scales
with the piece — a drawn fraction of the mean section length, clamped to
[12 s, 40% of the shorter neighbor] — and the Phase-22 state modulates
admission and window length whether or not `--state` is given. Inside
the window: the ROOM CROSSFADES (the one sanctioned exception to
clean-cut room changes, scoped to joints); the incoming FIELD keeps
~90% common tones; window notes SUSTAIN into the seam and off-field
notes GLIDE to the incoming field; the accent/density/register macro
tracks DECELERATE (the gesture sequencer keeps its clock); and the two
sections' onsets COMPOSE across the boundary. Loops, quotes, and gap
bridges are untouched; first and last boundaries never morph. The
report names each joint: `morph joint @135s (w 27s) [94 notes composed,
18 reglided]`. Joint-friendly runs: >= 6 minutes, >= 5 sections.

## 2. Space and wet — `--space`, `--wetdry`, `--air`

The room the piece happens in.

| flag | range | default | notes |
|---|---|---|---|
| `--space` | 0–1 | 0.5 | room size: drives the room-bearing reverb's feedback and cutoff. The L3 layer steps it per section on top. |
| `--wetdry` | 0–1 | 0.35 | the single global dry ↔ effects crossfade (equal-power). |
| `--air` | 0–1 | 0.25 | the noise floor and its slow swells — the piece's atmosphere between events. |

Each run draws 2–4 effect buses with chains from a 50-unit pool (shimmer,
spring, phaser, flanger, resonant sweep, tape-stop, bitcrushed bus
convolution). The manifest's `fx bus` lines say what this run drew; listen
with them in hand. `--wetdry` is the one knob over all of it.

Landmarks:

```
# bone dry: the instruments themselves, nothing else
python3 -m orange_fur --wetdry 0 --draft --out ~/Desktop/dry.wav

# default room
python3 -m orange_fur --draft --out ~/Desktop/room.wav

# the effects ARE the piece: source material as fuel for the tanks
python3 -m orange_fur --wetdry 0.9 --space 0.9 --draft --out ~/Desktop/cavern.wav

# tight dead space, effects present but small
python3 -m orange_fur --wetdry 0.5 --space 0.1 --draft --out ~/Desktop/closet.wav
```

Notes:
- `--wetdry` past ~0.8 lets shimmer/tape-stop chains dominate; with sparse
  nodes this is a drone machine.
- `--air 0` gives true silence between events (bridge swells still prevent
  long dead stretches); `--air` up toward 0.6+ makes the floor a participant.
- Since topology is drawn per run, the same settings sound different run to
  run. Render a few; keep the manifests.

---

## 3. Orchestra and form — `--subset`, `--sections`

| flag | range | default | notes |
|---|---|---|---|
| `--subset PCT` | 10–100 | 50 | percent of the ~150 generated instruments this score uses. Every category keeps ≥ 1 voice. |
| `--sections K` | 0–64 | 0 = auto | L1 section count. Auto draws from duration (4 min → 3–5, 45 min → 18–32). |

`--subset` is a coherence knob: low subset = few voices doing much
(chamber-like, motivic); high subset = maximal timbral variety (every phrase
a new instrument). Instruments rebind to graph terminals per section either
way, so form changes color at section boundaries.

`--sections` is pacing: few long sections = slow states; many short ones =
restless cutting (room and stereo-width changes step exactly at boundaries).

```
# six voices, twelve minutes: motivic minimalism
python3 -m orange_fur --nodes 16 --duration 12 --subset 10 --draft --out ~/Desktop/chamber.wav

# everything the generator drew, changing constantly
python3 -m orange_fur --subset 100 --sections 12 --draft --out ~/Desktop/kaleido.wav

# one continuous state (sections still exist minimally: 3 is the floor auto respects)
python3 -m orange_fur --sections 3 --duration 8 --draft --out ~/Desktop/slab.wav
```

---

## 4. Tuning — `--scl`, `--basefreq`, `--basekey`

| flag | default | notes |
|---|---|---|
| `--scl FILE` | bundled `werck3_mim.scl` | any Scala `.scl` file. |
| `--basefreq HZ` | 261.626 (middle C) | frequency of the scale's 1/1. |
| `--basekey KEY` | 60 | pitch index at which 1/1 sounds. |

This is deep water, cheaply. The whole system speaks in scale degrees —
banks place partials on degrees, glides slide in degrees, the register
staircase steps in degrees — so swapping the `.scl` retunes *everything
coherently*, including the inharmonic spectra.

```
# your scale
python3 -m orange_fur --scl ~/scales/my_19edo.scl --draft --out ~/Desktop/edo19.wav

# darker: same scale, 1/1 dropped a fourth
python3 -m orange_fur --basefreq 196.0 --draft --out ~/Desktop/dark.wav
```

Notes:
- Scales with many grades (19-, 31-EDO, 43-tone JI) make the gesture
  vocabulary finer-grained: glissandi of ±12 degrees become smaller sweeps,
  clusters get tighter. Fewer grades = wider, leapier behavior. Same flags,
  different music.
- Pitch is reflected into basekey ± 3 repeat-intervals, so `--basefreq`
  moves that whole window (~33 Hz–2.1 kHz of fundamentals at the default).

---

## 5. Cost and level — `--cost-cap`, `--normalize`, `--no-normalize`

| flag | default | notes |
|---|---|---|
| `--cost-cap OSC_SEC` | 0 = auto | render-cost ceiling in oscili-seconds. Negative disables routing. |
| `--normalize DBFS` | −3.0 | exact post-render peak target. |
| `--no-normalize` | off | ship the raw pre-normalize mix (model auditing only). |

Auto cap is 1200 × the duration in seconds. When the estimated cost exceeds
it, notes in the densest passages are moved to the cheapest instrument *of
their own category* until it fits — never changing a note's category, never
deleting notes. The audible effect is the one you'd choose anyway: the
thickest passages are made of the simplest voices. The manifest reports what
moved; if the cap is unreachable (everything already on the cheapest voice),
it says so honestly.

```
# force heavy routing: hear thick passages simplify
python3 -m orange_fur --nodes 120 --duration 3 --cost-cap 100000 --draft --out ~/Desktop/routed.wav

# disable routing entirely and accept the render time
python3 -m orange_fur --nodes 120 --duration 3 --cost-cap -1 --draft --out ~/Desktop/unrouted.wav
```

`--normalize` is only the output ceiling; internal drive (what hits the
shapers and tanks) is set by the score-time model regardless. −3 dBFS
default; −1 for something hotter; −12 if it will sit under other material.

---

## 6. Workflow — `--draft`, `--dry-run`, `--seed`, `--out`, `--no-keep-csd`, `--csound`

| flag | notes |
|---|---|
| `--draft` | 48 kHz / ksmps 16. Several times faster. Feedback-heavy timbres differ slightly from release: audition structure here, not final color. |
| *(no flag)* | release: 96 kHz / ksmps 1, decimated to 48 kHz (needs numpy; without it the file stays at 96 kHz and the CLI says so). |
| `--dry-run` | full report, no render. Free. Use it constantly. |
| `--from MIN --to MIN` | audition a time window of the piece. The full piece is generated identically (same token, same routing, same levels) and only the window renders — minutes instead of hours. Notes sounding at the edge enter clipped; struck notes that have rung out are skipped; tails end at window + 12 s; the room active at the edge carries in. Window normalization is audition-only. |
| `--replay TOKEN` | regenerate a previous piece from its manifest's replay token. Flags that feed generation (nodes, duration, sections, subset, tuning) must match the original; mix-side flags (`--wetdry`, `--space`, `--normalize`, draft/release) may differ — same composition, different mix. Version-specific: a token from another version warns and may not match. |
| `--seed TAG` | filename/manifest tag ONLY. Does not reproduce anything (use `--replay`). |
| `--out WAV` | output path. The manifest lands beside it as `.txt`. |
| `--no-keep-csd` | delete the generated `.csd` after rendering. |
| `--csound PATH` | point at the csound binary if it isn't on PATH. |

The working loop:

```
python3 -m orange_fur <flags> --dry-run                      # 1. shape check: sections, gestures, density
python3 -m orange_fur <flags> --draft --out try1.wav         # 2. listen
# repeat 1-2, varying one territory at a time
python3 -m orange_fur <flags> --out keeper.wav               # 3. commit at release quality
```

Step 3 re-renders the draft you liked as the *same piece*: take the replay
token from the draft's report (or its manifest) and pass it back:

```
python3 -m orange_fur <same flags> --draft --out try1.wav      # token printed
python3 -m orange_fur <same flags> --replay 0.8.0:9f3a... --out keeper.wav
```

The generation flags must match the draft's; the mix flags (`--wetdry`,
`--space`, `--normalize`) and draft/release may differ — that makes replay a
remix knob: same composition, different room.

For long pieces, add the window to the loop: spot-check a passage at release
quality before committing hours to the whole —

```
python3 -m orange_fur --nodes 80 --duration 30 --replay TOKEN --from 12 --to 15 --out check.wav
```


---

## 7. Recipes

Copy, paste, adjust. All are drafts; drop `--draft` for keepers.

**Default territory, just explore**
```
python3 -m orange_fur --draft --out ~/Desktop/of_$(date +%H%M%S).wav
```

**Pointillist miniature** — silence as material
```
python3 -m orange_fur --nodes 6 --duration 4 --subset 15 --wetdry 0.5 --space 0.7 --air 0.1 --draft --out ~/Desktop/point.wav
```

**Chamber minimalism** — few voices, long time, dry
```
python3 -m orange_fur --nodes 16 --duration 12 --subset 10 --wetdry 0.15 --space 0.2 --draft --out ~/Desktop/chamber.wav
```

**Gesture showcase** — mid density, sections cutting fast, room shifts audible
```
python3 -m orange_fur --nodes 32 --duration 5 --sections 10 --subset 70 --wetdry 0.45 --draft --out ~/Desktop/gestures.wav
```

**Cavern drone** — the tanks are the instrument
```
python3 -m orange_fur --nodes 10 --duration 10 --wetdry 0.9 --space 0.95 --air 0.5 --subset 25 --draft --out ~/Desktop/cavern.wav
```

**Mass music** — cloud of simple voices, cost routing doing its job
```
python3 -m orange_fur --nodes 150 --duration 4 --subset 40 --wetdry 0.3 --draft --out ~/Desktop/mass.wav
```

**Long-form** — draft the shape, then commit hours
```
python3 -m orange_fur --nodes 80 --duration 30 --subset 60 --draft --out ~/Desktop/long_draft.wav
python3 -m orange_fur --nodes 80 --duration 30 --subset 60 --out ~/Desktop/long_keeper.wav
```

**Retuned** — same machine, different universe
```
python3 -m orange_fur --scl ~/scales/partch_43.scl --nodes 40 --duration 8 --subset 30 --draft --out ~/Desktop/partch.wav
```

### The full arc on one token (v0.25.0)

```
python3 -m orange_fur --nodes 24 --duration 6 --sections 6 --draft \
    --out cut.wav
# note the replay token from the report, then:
python3 -m orange_fur --replay TOKEN --draft --morph 1 --state \
    --tension 0.6 --dynamics mid --out morphed.wav
```

Same piece, two readings: clean cuts vs crossfaded joints with the
hidden weather, a steered roughness trajectory, and narrowed dynamics.
Every flag on the second line is a remix knob — the token carries the
piece.

## 8. Template: a session skeleton

```
mkdir -p ~/Music/orangefur/session_$(date +%Y%m%d) && cd ~/Music/orangefur/session_$(date +%Y%m%d)

# survey the territory (free)
python3 -m orange_fur --nodes 32 --duration 6 --dry-run
python3 -m orange_fur --nodes 32 --duration 6 --dry-run
python3 -m orange_fur --nodes 32 --duration 6 --dry-run

# drafts, one variable at a time
python3 -m orange_fur --nodes 32 --duration 6 --draft --out a_base.wav
python3 -m orange_fur --nodes 32 --duration 6 --wetdry 0.7 --draft --out b_wet.wav
python3 -m orange_fur --nodes 32 --duration 6 --subset 15 --draft --out c_thin.wav

# keepers in the winning territory
python3 -m orange_fur --nodes 32 --duration 6 --wetdry 0.7 --out keeper1.wav
python3 -m orange_fur --nodes 32 --duration 6 --wetdry 0.7 --out keeper2.wav
```

Every wav has its manifest beside it. The manifest plus the flags you ran
are the complete description of the session.
