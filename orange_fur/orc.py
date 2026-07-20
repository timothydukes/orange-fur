"""
orc.py -- PHASE 0 PLACEHOLDER ORCHESTRA.

This is deliberately tiny: three sounding instruments, one air bed, one master
bus. Its only jobs are (a) prove the .csd assembly / subprocess / 32-bit-float
render path, (b) make the cpstuni tuning audible so the .scl mapping can be
verified by ear, (c) exercise the 0dbfs + amp-compensation discipline at real
note densities.

Everything here is REPLACED in Phase 3-4 by the combinatorial generator.
Nothing in this file should be treated as final timbre.

Instrument map (Phase 0):
   1  PARTIAL  sine partial -- the atom of the non-harmonic banks
   2  PLUCK    pluck
   3  GONG     crude 6-mode t-network stand-in
   4  CLOUD    microsound click / chirp
   5  TCLOUD   tuned partial cloud: saw/pulse/triangle emulated with partials
                SNAPPED TO THE SCALE, not to a harmonic series
   6  SWELL    slow swell, long release -- the sparse-score carrier
  90  air bed           -- noise floor + slow swells   (--air)
  99  master bus        -- reverb return, wet/dry crossfade, output (--wetdry, --space)

p-field convention, fixed for the whole project so the score generator never
has to special-case an instrument:
   p1 instr   p2 start   p3 dur
   p4 pitch index (scale degree index, fed to cpstuni)
   p5 amp     (already polyphony-compensated by score.py; 0..1 of 0dbfs)
   p6 pan     (0 = L, 1 = R)
   p7 send    (0..1 amount into the effects bus)
   p8 slew    (0..1 attack/contour shape; see rational window note below)
   p9 wave    (Cat.TCLOUD only: 0 saw, 1 pulse, 2 triangle)
   p10 glide  (Phase 5: pitch-glide target as an OFFSET IN SCALE DEGREES.
               0 = no glide, and every pre-Phase-5 score is bit-identical.)
   p11 curve  (transeg curve for the glide: 0 linear, +/- convex/concave)
   p12 det    (Phase 9: detune in CENTS, applied after the tuning lookup --
               the first officially off-scale pitch. 0 = on the scale, and
               every pre-Phase-9 score is bit-identical. Baked-partial
               templates ride it rigidly via kgl.)
"""

from __future__ import annotations

from .config import Config

TUNING_TABLE = 1
SINE_TABLE = 2

HEADER = """\
sr     = {sr}
ksmps  = {ksmps}
nchnls = 2
0dbfs  = 1

; ---- macros baked in from the CLI -------------------------------------
#define SPACE   #{space:.4f}#     ; room size          (--space)
#define AIR     #{air:.4f}#       ; noise floor / swells (--air)
#define WETDRY  #{wetdry:.4f}#    ; global dry<->wet crossfade (--wetdry)

; ---- global buses -----------------------------------------------------
gaDryL   init 0
gaDryR   init 0
gaSendL  init 0
gaSendR  init 0

giTun    =     {tun_tab}                    ; GEN -2 table, defined in the score
giSine   ftgen {sine_tab}, 0, 65537, 10, 1
giRooms  =     900                          ; room table, written by the score
giReso   =     901                          ; Phase 14: per-section field degrees
                                            ; (t, d1..d4 rows), written by the score
giGrades =     {grades}                     ; scale degrees per repeat interval
gibasekey =    {basekey}                    ; Phase 14: resonators map degrees
"""

INSTRUMENTS = """
; =======================================================================
; INTERPRETIVE DECISION -- "envelopes are rational approximations of
; interesting windows".  Phase 0 uses a single rational window:
;
;     w(t) = t^a * (1-t)^b  normalised to unit peak
;
; which is a Beta window; a,b are derived from p8 (slew).  slew=0 gives a
; percussive (a small, b large) contour, slew=1 gives a swell (a large,
; b small).  This is a stand-in.  Phase 3 replaces it with the real
; library of rational Kaiser/Tukey/Blackman approximations.
; =======================================================================
;
;
; RATE DISCIPLINE -- this cost a render. RatWin originally took k-rate inputs
; (`opcode RatWin, a, kk`) and then read them at i-time with i(kDur). K-rate UDO
; arguments are NOT reliably populated at init, so i(kDur) read 0, the phasor
; frequency became 1/0, and pow() got a NaN base. Csound 6.18 (Apr 2024) let it
; slide; Csound 6.18 (Nov 2022) raised "NaN in pow" and then segfaulted.
; Slew and duration are i-rate quantities (p8, p3). They are declared i-rate.
; Any future envelope UDO in this project takes i-rate args for the same reason.
;
opcode RatWin, a, ii
  iSlew, iDur  xin
  ; Guard: a zero or negative duration would make the phasor frequency
  ; infinite. Score events are always > 0, but the orchestra must not be able
  ; to produce a NaN no matter what the score says.
  iDur =  (iDur < 0.001 ? 0.001 : iDur)
  iSlew = (iSlew < 0 ? 0 : (iSlew > 1 ? 1 : iSlew))
  ia   =  0.02 + 3.0 * iSlew         ; rise exponent
  ib   =  3.0  - 2.6 * iSlew         ; fall exponent
  at   phasor  1 / iDur              ; normalised time, strictly in [0,1)
  at   limit   at, 0.000001, 0.999999
  aw   =  (at ^ ia) * ((1 - at) ^ ib)
  ; unit-peak normalisation: peak of t^a(1-t)^b is at t = a/(a+b)
  ipk  =  ((ia/(ia+ib)) ^ ia) * ((ib/(ia+ib)) ^ ib)
  xout aw / (ipk + 0.000001)
endop

; RatPop -- the popping exponential VCA's shape: instant (rational) attack,
; rational decay. iatk is the attack time in seconds. i-RATE ARGS ONLY (the
; Phase 0 rule; k-rate UDO args read at i-time are unpopulated -> NaN).
opcode RatPop, a, ii
  iatk, idur  xin
  idur  =  idur < 0.001 ? 0.001 : idur
  iatk  =  iatk < 0.0005 ? 0.0005 : (iatk > idur * 0.5 ? idur * 0.5 : iatk)
  aph   phasor  1 / idur
  ax    =  aph * idur
  aat   =  ax / (ax + iatk)                       ; rational rise, ~1 past iatk
  adc   =  1 / (1 + 12 * aph * aph)               ; rational decay window
  aout  =  aat * adc
  xout  aout
endop

; RatComp -- the spec's COMPOUND envelope: the PRODUCT of two rational windows
; with different effective durations, one slow (the swell), one full-length
; (the container). islew stretches the slow one. i-RATE ARGS ONLY.
opcode RatComp, a, ii
  islew, idur  xin
  idur  =  idur < 0.001 ? 0.001 : idur
  a1    RatWin  islew, idur
  a2    RatWin  0.5 + islew * 0.5, idur * (0.6 + 0.4 * islew)
  aout  =  a1 * a2
  xout  aout
endop


; ---- 1 : sine partial --------------------------------------------------
instr 1
  icps  =  cpstuni(p4, giTun)
  iamp  =  p5
  ipan  =  p6
  isend =  p7
  aenv  RatWin  p8, p3
  a1    oscili  iamp * aenv, icps, giSine
  aL    =  a1 * sqrt(1 - ipan)          ; constant-power pan
  aR    =  a1 * sqrt(ipan)
  gaDryL  +=  aL * (1 - isend)
  gaDryR  +=  aR * (1 - isend)
  gaSendL +=  aL * isend
  gaSendR +=  aR * isend
endin

; ---- 2 : pluck ---------------------------------------------------------
instr 2
  icps  =  cpstuni(p4, giTun)
  iamp  =  p5
  ipan  =  p6
  isend =  p7
  a1    pluck  iamp, icps, icps, 0, 1
  aenv  RatWin  p8, p3
  a1    =  a1 * aenv
  aL    =  a1 * sqrt(1 - ipan)
  aR    =  a1 * sqrt(ipan)
  gaDryL  +=  aL * (1 - isend)
  gaDryR  +=  aR * (1 - isend)
  gaSendL +=  aL * isend
  gaSendR +=  aR * isend
endin

; ---- 3 : gong (crude modal stand-in) -----------------------------------
instr 3
  icps  =  cpstuni(p4, giTun)
  iamp  =  p5
  ipan  =  p6
  isend =  p7
  ; six inharmonic modes; Phase 3 replaces with a real t-network
  a1  oscili 1.00, icps * 1.000, giSine
  a2  oscili 0.62, icps * 2.756, giSine
  a3  oscili 0.41, icps * 5.404, giSine
  a4  oscili 0.28, icps * 8.933, giSine
  a5  oscili 0.19, icps * 13.35, giSine
  a6  oscili 0.11, icps * 18.64, giSine
  amix = (a1+a2+a3+a4+a5+a6) * 0.32
  aenv RatWin 0.02, p3          ; struck: fast rise, long tail
  amix = amix * aenv * iamp
  aL   = amix * sqrt(1 - ipan)
  aR   = amix * sqrt(ipan)
  gaDryL  +=  aL * (1 - isend)
  gaDryR  +=  aR * (1 - isend)
  gaSendL +=  aL * isend
  gaSendR +=  aR * isend
endin

; ---- 4 : CLOUD -- microsound click / chirp -----------------------------
; Quiet individual events, 10-90 ms. These are the "clouds of quiet clicks and
; chirps". Cheap by construction: at 300 nodes the score is 90,000 notes and the
; dense material MUST be cheap or the render never finishes.
instr 4
  icps  =  cpstuni(p4, giTun)
  iamp  =  p5
  ipan  =  p6
  isend =  p7
  ichirp = icps * (1 + rnd(1.4) - 0.35)          ; chirp glides
  acps  expon  icps, p3, ichirp
  a1    oscili iamp, acps, giSine
  aenv  RatWin  p8, p3
  a1    =  a1 * aenv
  aL    =  a1 * sqrt(1 - ipan)
  aR    =  a1 * sqrt(ipan)
  gaDryL  +=  aL * (1 - isend)
  gaDryR  +=  aR * (1 - isend)
  gaSendL +=  aL * isend
  gaSendR +=  aR * isend
endin

; ---- 5 : TCLOUD -- tuned partial cloud --------------------------------
; A saw / pulse / triangle emulated ADDITIVELY, but with every partial snapped
; to the nearest degree of the scale instead of sitting on an exact harmonic.
;
; INTERPRETIVE DECISION. This is the "partials match tuning" constraint made
; literal, and it is the reason the instrument exists. A real saw has partials
; at n*f0 with amplitude 1/n. Here partial n is pulled to the nearest scale
; degree above f0, so the spectrum keeps the ENVELOPE of a saw (1/n rolloff,
; odd-only for pulse, 1/n^2 odd for triangle) while its FREQUENCIES belong to
; Werckmeister III. It reads as a familiar waveform that has been retuned from
; the inside, which is what makes the noise sound tuned rather than merely dense.
;
; The snapping is done in the score generator (Python), which knows the scale;
; here we just take the base degree and walk up the table. p9 picks the wave.
instr 5
  ideg  =  p4
  iamp  =  p5
  ipan  =  p6
  isend =  p7
  iwave =  p9

  amix  =  0
  isum  =  0
  ip    =  1
loop:
  ; harmonic number ip -> the scale degree nearest to log2(ip) octaves up
  ioct  =  log(ip) / log(2)
  idg   =  ideg + round(ioct * giGrades)
  icps  =  cpstuni(idg, giTun)

  ; amplitude law by waveform, on the true harmonic number
  if iwave == 1 then
    iamp_n = (ip % 2 == 1 ? 1 / ip : 0)          ; pulse / square: odd only, 1/n
  elseif iwave == 2 then
    iamp_n = (ip % 2 == 1 ? 1 / (ip * ip) : 0)   ; triangle: odd only, 1/n^2
  else
    iamp_n = 1 / ip                              ; saw: all, 1/n
  endif

  if icps < sr / 2.2 && iamp_n > 0 then
    apart oscili iamp_n, icps, giSine
    amix  =  amix + apart
    isum  =  isum + iamp_n
  endif
  ip = ip + 1
  if ip <= 16 igoto loop

  amix  =  amix / (isum + 0.0001) * iamp
  aenv  RatWin  p8, p3
  amix  =  amix * aenv
  aL    =  amix * sqrt(1 - ipan)
  aR    =  amix * sqrt(ipan)
  gaDryL  +=  aL * (1 - isend)
  gaDryR  +=  aR * (1 - isend)
  gaSendL +=  aL * isend
  gaSendR +=  aR * isend
endin

; ---- 6 : SWELL -- the sparse-score carrier ----------------------------
; Slow attack, very long release, mostly into the tank. You said sparse scores
; (100 notes across 40 minutes) must be as legible as dense ones, and that the
; reverb tails and slow swells with long release are what carry them. This is
; that instrument. It is why a 40-minute, 100-note render is not 40 minutes of
; silence with occasional events in it.
instr 6
  icps  =  cpstuni(p4, giTun)
  iamp  =  p5
  ipan  =  p6
  isend =  p7
  a1    oscili  iamp, icps, giSine
  a2    oscili  iamp * 0.42, icps * 1.4983, giSine   ; the tempered fifth
  a3    oscili  iamp * 0.20, icps * 2.0, giSine
  amix  =  (a1 + a2 + a3) * 0.62
  aenv  RatWin  p8, p3                 ; p8 is high for swells -> long rise
  amix  =  amix * aenv
  aL    =  amix * sqrt(1 - ipan)
  aR    =  amix * sqrt(ipan)
  gaDryL  +=  aL * (1 - isend)
  gaDryR  +=  aR * (1 - isend)
  gaSendL +=  aL * isend
  gaSendR +=  aR * isend
endin

; ---- 90 : air bed ------------------------------------------------------
; noise floor plus slow low-level swells.  Insect/frog layer is Phase 5.
instr 90
  if $AIR. <= 0 igoto skip
  aswell  randi  0.5, 0.07, 2          ; slow amplitude drift
  aswell  =  0.5 + aswell
  anL     pinkish  1
  anR     pinkish  1
  anL     butterlp  anL, 1400
  anR     butterlp  anR, 1400
  ibase   =  $AIR. * 0.012             ; conservative: air must not eat headroom
  gaSendL +=  anL * ibase * aswell
  gaSendR +=  anR * ibase * aswell
  gaDryL  +=  anL * ibase * 0.25
  gaDryR  +=  anR * ibase * 0.25
skip:
endin

; ---- 99 : master bus ---------------------------------------------------
; PHASE 0 chain: one reverbsc.  Phase 4 replaces this with the generated
; send/bus topology (shimmer, spring, tanks, phaser, ping-pong, ...).
instr 99
  ; --space maps to reverb feedback and cutoff: small room -> short, dark;
  ; open room -> long, bright. Phase 2: the L3 ROOM of the current section
  ; scales both, plus a stereo width, STEPPED AT SECTION BOUNDARIES -- clean
  ; cuts, per spec, no crossfade. giRooms holds rows of
  ; (t_start, fb_scale, cut_scale, width); f0 rows terminate with t=-1.
  ifb0  =  0.68 + 0.30 * $SPACE.       ; 0.68 .. 0.98
  icut0 =  3000 + 9000 * $SPACE.

  ktime  timeinsts
  kfbs   init 1
  kcuts  init 1
  kwid   init 1
  kidx   init 0
  kt     table  kidx * 4, giRooms
  if kt >= 0 && ktime >= kt then
    kfbs  table  kidx * 4 + 1, giRooms
    kcuts table  kidx * 4 + 2, giRooms
    kwid  table  kidx * 4 + 3, giRooms
    kidx = kidx + 1
  endif

  ; parameter clamps as ternaries, NOT the `limit` opcode: the test suite
  ; greps the master chain for limiter/clipper opcodes as a hard guard (see
  ; Phase 0 findings), and that guard stays strict. These clamp k-rate
  ; PARAMETERS, never audio.
  kfb   =  ifb0 * kfbs
  kfb   =  kfb > 0.985 ? 0.985 : (kfb < 0.30 ? 0.30 : kfb)
  kcut  =  icut0 * kcuts
  kcut  =  kcut > 16000 ? 16000 : (kcut < 800 ? 800 : kcut)
  awL, awR  reverbsc  gaSendL, gaSendR, kfb, kcut

  ; single global dry<->wet crossfade (equal-power)
  iwet  =  sin($WETDRY. * 1.5707963)
  idry  =  cos($WETDRY. * 1.5707963)

  aL  =  gaDryL * idry + awL * iwet
  aR  =  gaDryR * idry + awR * iwet

  ; stereo width, mid-side, stepped with the room. width 1 = untouched;
  ; MIDSIDE rooms widen (>1), SMALL narrows (<1). Clean cut at the boundary.
  aM  =  (aL + aR) * 0.5
  aS  =  (aL - aR) * 0.5
  aL  =  aM + aS * kwid
  aR  =  aM - aS * kwid

  ; NO LIMITER, NO CLIPPER, DELIBERATELY.
  ;
  ; An earlier version put `clip aL, 0, ceiling` here as a "backstop". Csound's
  ; clip method 0 is Bram de Jong SOFT clipping: it starts saturating at
  ; ilimit*0.5 and asymptotes to (ilimit + ilimit*0.5)/2. Every render came out
  ; at exactly -3.50 dBFS because the saturator was engaging continuously --
  ; which both coloured the sound and hid the true peak, making the score-time
  ; model impossible to calibrate. The whole point of the score-time
  ; compensation is that nothing downstream needs to catch anything. If the
  ; peak overshoots, that is a bug in score.py to be fixed there, and render.py
  ; will report it. Target ceiling for this run: {ceiling:.6f}
  outs  aL, aR
  gaDryL = 0
  gaDryR = 0
  gaSendL = 0
  gaSendR = 0
endin
"""


def build_orc(cfg: Config, ceiling: float, orch_text: str | None = None,
              routing=None) -> str:
    head = HEADER.format(
        sr=cfg.sr,
        ksmps=cfg.ksmps,
        space=cfg.space,
        air=cfg.air,
        wetdry=cfg.wetdry,
        tun_tab=TUNING_TABLE,
        sine_tab=SINE_TABLE,
        grades=cfg.scale.numgrades,
        basekey=cfg.scale.basekey,
    )
    body = INSTRUMENTS.format(ceiling=ceiling)
    if routing is not None and orch_text is not None:
        # Phase 4: preamble UDOs + generated orchestra + air bed (rewired to
        # bus 1) + the master bus GENERATED FROM THE ROUTING STRUCT. The old
        # fixed instr 99 is gone in this arm.
        from .routing import UDO_TEXT, master_text
        pre = body[:body.index("; ---- 1 :")]
        air = body[body.index("; ---- 90 :"):body.index("; ---- 99 :")]
        air = air.replace("gaSendL", "gaSend1L").replace("gaSendR", "gaSend1R")
        decl, master = master_text(cfg, routing)
        return (head + decl + "\n" + UDO_TEXT + pre + orch_text
                + "\n\n" + air + "\n" + master + "\n")
    if orch_text is not None:
        # Phase 3: replace the placeholder instruments 1-6 with the generated
        # orchestra. THREE pieces survive: the preamble BEFORE instr 1 (the
        # envelope UDOs live there -- dropping it was a parse error found on
        # the first integrated render), the generated instruments, and the
        # fixed 90 (air) / 99 (master bus) verbatim.
        pre = body[:body.index("; ---- 1 :")]
        fixed = body[body.index("; ---- 90 :"):]
        body = pre + orch_text + "\n\n" + fixed
    return head + body


def build_csd(cfg: Config, orc_text: str, sco_text: str) -> str:
    fmt = "-f" if True else ""  # 32-bit float
    # -+rtaudio=null / -+rtmidi=null : this is an OFFLINE renderer. Without
    # these, Csound loads PortAudio and PortMIDI and probes for a JACK library
    # it does not need, which on some macOS builds emits a librtjack warning and
    # can take the process down on teardown. Nothing here ever touches realtime
    # I/O, so the modules are disabled outright.
    flags = (f"-W {fmt} -o {cfg.out.name} -d -m0 "
             f"-+rtaudio=null -+rtmidi=null")
    return (
        "<CsoundSynthesizer>\n"
        "<CsOptions>\n"
        f"{flags}\n"
        "</CsOptions>\n"
        "<CsInstruments>\n"
        f"{orc_text}\n"
        "</CsInstruments>\n"
        "<CsScore>\n"
        f"{sco_text}\n"
        "</CsScore>\n"
        "</CsoundSynthesizer>\n"
    )
