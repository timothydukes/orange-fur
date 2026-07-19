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
- **Every run is a different piece.** The RNG is entropy-seeded; `--seed` is
  a filename tag only. The `.txt` manifest written beside each render is the
  only record of what a run drew — archive it with the wav.
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
| `--seed TAG` | filename/manifest tag ONLY. Does not reproduce anything. |
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

Because runs aren't reproducible, step 3 is a *new piece* in the same
territory, not a re-render of the draft you liked. Render release keepers in
small batches (2–3) and keep the best.

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
