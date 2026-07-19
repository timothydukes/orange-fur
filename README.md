
# Orange Fur

A command-line generative music system. Each run draws a fresh orchestra of
~150 Csound instruments and a bank of ~50 effects, composes a multi-layered
score over it — L-system sections, Euclidean macro-rhythms, gesture playlists
(glissandi, diverging clouds, sweeps, bursts, loops, long decays) — and
renders a stereo 32-bit-float `.wav` offline. Every run is a different piece
by design; the manifest written beside each render is the record of what that
run drew.

Version 0.7.0. Tuning: Werckmeister III "mimafip" by default, any Scala
`.scl` accepted. Output: 48 kHz stereo float WAV (release renders are
synthesized at 96 kHz and decimated).

- `README.md` — this file: installation and setup.
- `USERGUIDE.md` — every flag, organized as parameter territories to explore,
  with recipes and templates.
- `PHASELOG.md` — the development history, phase by phase, with findings.

---

## 1. What you need

| dependency | required? | what for |
|---|---|---|
| Python 3.9+ | yes | the generator itself (stdlib only) |
| Csound 6.18+ | yes | the renderer |
| numpy | recommended | the 96→48 kHz release decimation; drafts don't need it |

Nothing else. No package installation of Orange Fur itself is needed — it
runs directly from the unzipped folder.

## 2. Install, step by step (macOS)

These steps assume nothing is installed yet. Skip any step whose check
already passes.

### 2.1 Check Python 3

Open **Terminal** (Applications → Utilities → Terminal) and type:

```
python3 --version
```

If it prints `Python 3.9` or higher, done — go to 2.2. If it prints
`command not found` or something below 3.9: download the macOS 64-bit
installer from https://www.python.org/downloads/ (any 3.9–3.12 release),
open the `.pkg`, click through the installer, then close and reopen
Terminal and run the check again.

### 2.2 Check Csound

```
csound --version
```

If it prints `Csound version 6.18` (or any 6.x ≥ 6.18), done — go to 2.3.
If not:

1. Go to https://csound.com/download.html
2. Under **macOS**, download the 6.x installer (`.dmg`).
3. Open the `.dmg`, run the installer package inside, click through.
4. Close and reopen Terminal, run `csound --version` again.

If Terminal still says `command not found` after installing, the binary is
usually at `/usr/local/bin/csound` — you can pass it explicitly later with
`--csound /usr/local/bin/csound`, or add it to your PATH.

### 2.3 Install numpy (recommended)

```
pip3 install numpy
```

If `pip3` is not found, use `python3 -m pip install numpy` instead.

Without numpy everything still works, but release renders are delivered at
96 kHz instead of being decimated to 48 kHz (the CLI will say so plainly).
Drafts are unaffected.

## 3. Set up Orange Fur

1. Move `orange_fur_p6.zip` wherever you keep projects and double-click it
   (or `unzip orange_fur_p6.zip` in Terminal). You get a folder
   `orange_fur_p6`.
2. In Terminal:

```
cd ~/Downloads/orange_fur_p6        # adjust to wherever you unzipped it
```

Every command in this README and in `USERGUIDE.md` is run from inside this
folder.

## 4. Verify the install

Run the test suites (each prints `all pass` at the end; the later suites
render audio and take a few minutes):

```
python3 tests/test_p0.py
python3 tests/test_p6.py
```

If `test_p0.py` passes, Python + Csound + the tuning table all work. If
`test_p6.py` passes, the release path (96 kHz render + decimation) works
too. The full battery, if you want it:

```
for t in 0 1 2 3 4 5 6; do python3 tests/test_p$t.py; done
```

## 5. First renders

A fast draft (about a minute of wall time):

```
python3 -m orange_fur --duration 2 --draft --out ~/Desktop/first_draft.wav
```

A full-quality release render of the default piece (5 minutes of music;
expect the render to take noticeably longer than the piece):

```
python3 -m orange_fur --out ~/Desktop/first_release.wav
```

Each render leaves three things: the `.wav`, a `.csd` (the generated Csound
file — deletable, or a curiosity), and a `.txt` **manifest** holding the full
report of what the run drew: the effect-chain topology, the gesture
playlists, the Euclidean macro tracks, cost routing, render statistics.
Because runs are not reproducible by design, the manifest is the only record
of a piece's recipe — keep it with the wav.

## 6. The two render modes

| mode | flag | sr / ksmps | when |
|---|---|---|---|
| draft | `--draft` | 48 kHz / 16 | iteration: structure, density, levels |
| release | *(default)* | 96 kHz / 1 → decimated to 48 kHz | the keeper |

Draft is several times faster but slightly changes the timbre of anything
with a sample-accurate feedback path, so always audition structure in draft
and commit with a release render. On a 2015-class machine, budget roughly:
drafts render in a fraction of the piece's length; release renders take a
low multiple of it; long-form release renders (30+ minutes of music at high
`--nodes`) can take hours. `--dry-run` prints the whole report without
rendering at all, for free.

## 7. Where to go next

`USERGUIDE.md` — the flags, grouped into parameter territories with
suggested ranges, notes on how the parameters interact, and copy-paste
recipe templates.
