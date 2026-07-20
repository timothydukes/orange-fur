"""
cli.py -- Orange Fur command line interface.
"""

from __future__ import annotations

import argparse
import math
import time
import random
import sys
from pathlib import Path

from . import __version__
from .config import (
    Config, DURATION_MIN, DURATION_MAX, NODES_MIN, NODES_MAX,
    SUBSET_MIN, SUBSET_MAX,
)
from .orc import build_orc, build_csd
from .score import (graph_events, compensate, build_sco, set_instr_peaks,
                    apply_window,
                    cost_route)
from .orchestra import generate as gen_orchestra
from .constraints import solve
from . import render as R


def _ranged(lo, hi, cast=float):
    def f(s):
        v = cast(s)
        if v < lo or (hi is not None and v > hi):
            raise argparse.ArgumentTypeError(
                f"must be >= {lo}" if hi is None else f"must be in [{lo}, {hi}]")
        return v
    return f


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="orange-fur",
        description="Generate a Csound orchestra + score and render a .wav offline.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--duration", type=_ranged(DURATION_MIN, None),
                   default=5.0, metavar="MIN",
                   help="length in minutes (no upper cap)")
    p.add_argument("--nodes", type=_ranged(NODES_MIN, NODES_MAX, int),
                   default=24, metavar="N",
                   help="graph nodes; the score contains exactly N**2 notes")
    p.add_argument("--cost-cap", type=float, default=0.0, metavar="OSC_SEC",
                   dest="cost_cap",
                   help="render-cost cap in oscili-seconds; 0 = auto "
                        "(1200 x duration), negative = disable routing")
    p.add_argument("--echo", type=_ranged(0.0, 3.0), default=1.0,
                   metavar="SCALE",
                   help="score-domain delay density: scales each section's "
                        "drawn echo probability (0 disables; the piece is "
                        "otherwise identical -- same replay token)")
    p.add_argument("--fields", type=_ranged(0, 1, int), default=1,
                   metavar="0|1",
                   help="harmonic fields: each section draws a pitch-class "
                        "subset all pitched material conforms to (1, "
                        "default). 0 disables snapping; same replay token, "
                        "harmonically free")
    p.add_argument("--sections", type=_ranged(0, 64, int), default=0,
                   metavar="K",
                   help="how many sections the L1 grammar emits; "
                        "0 = auto, drawn from the duration")
    p.add_argument("--space", type=_ranged(0.0, 1.0), default=0.5,
                   help="room size (0 = tight, 1 = open)")
    p.add_argument("--air", type=_ranged(0.0, 1.0), default=0.25,
                   help="noise floor and low-level noise swells")
    p.add_argument("--wetdry", type=_ranged(0.0, 1.0), default=0.35,
                   help="global dry <-> effects-return crossfade")
    p.add_argument("--subset", type=_ranged(SUBSET_MIN, SUBSET_MAX), default=50.0,
                   metavar="PCT",
                   help="percent of the generated orchestra used in this score")
    p.add_argument("--normalize", type=float, default=-3.0, metavar="DBFS",
                   help="target peak ceiling; amplitudes are scaled at score "
                        "time to land here")
    p.add_argument("--scl", type=Path, default=None,
                   help="Scala tuning file (default: bundled werck3_mim.scl)")
    p.add_argument("--basefreq", type=float, default=None, metavar="HZ",
                   help="frequency of the scale's 1/1 (default: middle C)")
    p.add_argument("--basekey", type=int, default=None, metavar="KEY",
                   help="note index at which the scale's 1/1 sounds (default: 60)")
    p.add_argument("--no-normalize", dest="do_normalize", action="store_false",
                   help="skip the exact post-render rescale and ship whatever "
                        "the score-time model produced. Only useful for "
                        "auditing the model itself.")
    p.add_argument("--draft", action="store_true",
                   help="fast iteration render: 48 kHz, ksmps=16. Changes the "
                        "sound of any sample-rate-sensitive chain.")
    p.add_argument("--from", dest="win_from", type=float, default=None,
                   metavar="MIN",
                   help="audition window start (minutes into the piece); the "
                        "full piece is generated identically and this window "
                        "of it is rendered")
    p.add_argument("--to", dest="win_to", type=float, default=None,
                   metavar="MIN",
                   help="audition window end (minutes); requires --from")
    p.add_argument("--replay", type=str, default=None, metavar="TOKEN",
                   help="replay token from a previous run's report "
                        "(VERSION:HEX, or bare hex); regenerates that piece "
                        "exactly if the code version matches")
    p.add_argument("--seed", default="", metavar="TAG",
                   help="filename tag only; does NOT make the run reproducible")
    p.add_argument("--out", type=Path, default=None, metavar="WAV",
                   help="output path (default: orange_fur_<tag>.wav)")
    p.add_argument("--no-keep-csd", dest="keep_csd", action="store_false",
                   help="delete the generated .csd after rendering")
    p.add_argument("--dry-run", action="store_true",
                   help="write the .csd and print the report, but do not render")
    p.add_argument("--csound", default="csound",
                   help="csound executable")
    p.add_argument("--version", action="version", version=f"orange-fur {__version__}")
    return p


MANIFEST: list[str] = []
_print = print


def print(*args, **kw):        # noqa: A001 -- deliberate module-local shadow
    """Every CLI line is both printed and captured, so the full drawn-parameter
    report (topology, gesture playlists, macro tracks, cost routing) can be
    written next to the .wav as a manifest. On a 45-minute render the printout
    IS the documentation of what was drawn; losing it to a closed terminal
    makes the render unrepeatable in spirit."""
    MANIFEST.append(" ".join(str(a) for a in args))
    _print(*args, **kw)


def _parse_replay(token: str) -> tuple[int, str | None]:
    """Replay token -> (seed, version-or-None). Accepts 'VERSION:HEX16' as
    printed in the report, or a bare hex seed."""
    ver = None
    if ":" in token:
        ver, token = token.rsplit(":", 1)
    try:
        seed = int(token, 16)
    except ValueError:
        raise SystemExit(f"orange-fur: bad --replay token {token!r} "
                         "(expected VERSION:HEX or hex)")
    if not (0 <= seed < 1 << 64):
        raise SystemExit("orange-fur: --replay seed out of 64-bit range")
    return seed, ver


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    replay_seed, replay_ver = (None, None)
    if args.replay is not None:
        replay_seed, replay_ver = _parse_replay(args.replay)

    win = None
    if (args.win_from is None) != (args.win_to is None):
        raise SystemExit("orange-fur: --from and --to must be given together")
    if args.win_from is not None:
        if not (0 <= args.win_from < args.win_to <= args.duration):
            raise SystemExit("orange-fur: need 0 <= --from < --to <= --duration")
        win = (args.win_from * 60.0, args.win_to * 60.0)

    kw = dict(
        duration=args.duration, nodes=args.nodes, space=args.space,
        air=args.air, wetdry=args.wetdry, subset=args.subset,
        normalize=args.normalize, draft=args.draft, seed=args.seed,
        sections=args.sections, cost_cap=args.cost_cap, echo=args.echo,
        fields=args.fields,
        scl=args.scl, out=args.out, keep_csd=args.keep_csd,
        csound=args.csound, replay=replay_seed,
    )
    if args.basefreq is not None:
        kw["basefreq"] = args.basefreq
    if args.basekey is not None:
        kw["basekey"] = args.basekey

    cfg = Config(**kw)
    print(cfg.summary())
    print(f"  replay     {__version__}:{cfg.entropy:016x}"
          + ("" if args.replay is not None else
             "   (pass to --replay to regenerate this piece)"))
    if replay_ver is not None and replay_ver != __version__:
        print(f"  WARNING    replay token is from v{replay_ver}, this is "
              f"v{__version__}: the RNG stream may have changed and the "
              f"regenerated piece may not match the original")
    print()

    # Phase 7: --replay overrides the entropy draw; otherwise unchanged spec
    # of --seed.
    rng = random.Random(cfg.entropy)

    t0 = time.time()
    sol = solve(cfg.nodes, rng)

    # ---- Phase 4: routing first (instruments need to know the bus count) ----
    from .routing import generate_routing
    routing = generate_routing(rng)

    # ---- Phase 3: the orchestra is generated per run, then --subset ----
    full = gen_orchestra(rng, cfg.scale.numgrades, n_buses=routing.n_buses)
    orch = full.subset(cfg.subset, rng)
    set_instr_peaks(orch.peaks(), orch.taus(), orch.comps())
    from .alphabet import Cat as _Cat
    catmap = {c: [i.num for i in orch.by_cat(c)] for c in _Cat}

    events, smeta = graph_events(cfg, sol, rng, catmap=catmap)
    gen_s = time.time() - t0

    rep = sol.report
    print(f"  graph      {cfg.nodes} nodes, alphabet {2 * cfg.nodes} "
          f"({cfg.nodes} non-terminal + {cfg.nodes} terminal)")
    print(f"  derivation |string| {len(sol.system.string)}, "
          f"terminals {rep['terminals']} "
          f"(x{rep['ratio']:.2f} budget), dead nodes {rep['dead']}, "
          f"{gen_s:.2f} s")
    print(f"  sections   {' -> '.join(smeta['seq'])}")
    print(f"  grammar    {' '.join(smeta['trace'])}")
    cats = rep["by_cat"]
    tot = sum(cats.values()) or 1
    print("  categories " + "  ".join(
        f"{k.lower()} {100 * v / tot:.0f}%" for k, v in cats.items() if v))
    if sol.relaxed:
        print(f"  RELAXED    {', '.join(sol.relaxed)}  "
              f"(constraints could not all be met; character is compromised)")

    # ---- Phase 5: density -> cost routing, before the amp model ----
    cap = cfg.cost_cap if cfg.cost_cap != 0 else 1200.0 * cfg.dur_sec
    if cfg.cost_cap < 0:
        cap = 0.0
    croute = cost_route(events, cfg, orch, cap)

    # amp gains from the FULL piece -- the window sounds as this passage will
    # sound in the keeper render, not as a re-levelled excerpt
    stats = compensate(events, cfg, routing=routing)
    stats["rooms"] = smeta["rooms"]
    stats["sec_fields"] = smeta["sec_fields"]

    score_dur = None
    if win is not None:
        events, wrooms, wrep = apply_window(events, smeta["rooms"],
                                            win[0], win[1])
        stats["rooms"] = wrooms
        from .score import trim_timed
        stats["sec_fields"] = trim_timed(stats.get("sec_fields", []),
                                         win[0], win[1])
        score_dur = win[1] - win[0]
        print(f"  window     {win[0]/60:g}-{win[1]/60:g} min of the piece: "
              f"{wrep['kept']} notes ({wrep['clipped']} clipped at the edge, "
              f"{wrep['rung_out']} struck notes already rung out)")
        print( "             note: post-render normalization is AUDITION-ONLY"
              " here; the full piece normalizes on its own global peak")

    mac = smeta["macro"]
    if mac:
        m0 = mac[0]
        print(f"  macro      accent {m0['accent']}  gesture {m0['gesture']}  "
              f"density {m0['density']}  register {m0['register']}  "
              f"(periods {m0['periods']} s)")
        print("  echoes     " + " | ".join(
            f"{m['section'][:3]}: {m['echo']}" for m in mac))
        totech = sum(sl.get("echo_notes", 0) for sl in smeta["sections"])
        if totech:
            print(f"             {totech} echo notes "
                  f"({totech / max(1, len(events)):.0%} of the score)")
        if getattr(cfg, "fields", 1):
            print("  fields     " + " | ".join(
                f"{m['section'][:3]}: {m.get('field', '?')}" for m in mac))
        bank = max((m.get("bank", 0) for m in mac), default=0)
        qlines = [(m["section"], m["quotes"]) for m in mac if m.get("quotes")]
        if bank:
            print(f"  motifs     bank of {bank} captured; " + (" | ".join(
                f"{sn}: {', '.join(qs)}" for sn, qs in qlines)
                if qlines else "no quotes drawn"))
        loops = [(m["section"], m["loop"]) for m in mac if m.get("loop")]
        for sname, ldesc in loops:
            print(f"  tape loop  [{sname}] {ldesc}")
        print("  gestures   " + " | ".join(
            f"{m['section'][:3]}: {'>'.join(g.lower() for g in m['playlist'])}"
            for m in mac))

    for ci, ch in enumerate(routing.chains):
        tag = "  [room]" if ci == routing.room_chain else ""
        print(f"  fx bus {ch.bus}   {' -> '.join(u.kind for u in ch.units)}"
              f"  (return {ch.ret:.2f}){tag}")
    print(f"  fx cost    {routing.cost():.0f} oscili units (always-on)")

    from collections import Counter as _Counter
    tmix = _Counter(i.template for i in orch.instruments)
    costs = orch.costs()
    print(f"  orchestra  {len(full.instruments)} generated, "
          f"{len(orch.instruments)} in subset ({cfg.subset:.0f}%)")
    print("  templates  " + "  ".join(f"{k} {v}" for k, v in sorted(tmix.items())))
    if croute["rerouted"]:
        floor = ("  [cap unreachable: every note is already on its "
                 "category's cheapest voice]" if croute.get("at_floor") else "")
        print(f"  cost route {croute['before']:,.0f} -> {croute['after']:,.0f} "
              f"oscili-sec (cap {croute['cap']:,.0f}); "
              f"{croute['rerouted']:,} of {len(events):,} notes moved to the "
              f"cheapest voice in their own category{floor}")
    elif cfg.cost_cap < 0:
        print(f"  est. cost  {croute['after']:,.0f} oscili-seconds "
              f"(cost routing disabled)")
    else:
        print(f"  est. cost  {croute['after']:,.0f} oscili-seconds "
              f"(cap {croute['cap']:,.0f}, no routing needed)")

    roomseq = " -> ".join(f"{name}@{t:.0f}s" for t, name, *_ in smeta["rooms"])
    print(f"  rooms      {roomseq}")
    if smeta.get("bridges"):
        print(f"  bridges    {smeta['bridges']} quiet swell(s) spanning "
              f"note-start gaps > max(8 s, 5% of the piece)")

    orc_text = build_orc(cfg, stats["ceiling"], orch.text(), routing=routing)
    sco_text = build_sco(cfg, events, stats, score_dur=score_dur)
    csd_text = build_csd(cfg, orc_text, sco_text)
    csd_path = R.write_csd(cfg, csd_text)

    print(f"  events     {len(events)}")
    print(f"  density    {len(events) / (cfg.dur_sec / 60.0):.0f} notes/min "
          f"(the note budget scales with nodes^2, not duration -- long pieces "
          f"want more nodes)")
    print(f"  polyphony  max {stats['max_concurrency']}, "
          f"mean {stats['mean_concurrency']:.1f}")
    print(f"  amp gain   {stats['gain']:.5f}  "
          f"(predicted peak {stats['predicted_peak']:.4f} -> "
          f"{cfg.normalize:g} dBFS)")
    print(f"  csd        {csd_path}")

    if args.dry_run:
        print("\n  --dry-run: not rendering.")
        return 0

    # Render-time reality check, printed BEFORE the render starts.
    est = _render_estimate(cfg, stats)
    print(f"\n  render     starting; rough estimate {est}")
    sys.stdout.flush()

    res = R.run(cfg, csd_path)
    wav = csd_path.parent / cfg.out.name

    raw = R.measure_peak(wav)
    raw_peak = raw["peak"]
    raw_db = 20 * math.log10(raw_peak) if raw_peak > 0 else -999

    rt = res["elapsed"] / cfg.dur_sec
    print(f"\n  rendered   {res['elapsed']:.1f} s wall ({rt:.2f}x realtime)")
    print(f"  wav        {wav}  "
          f"{raw.get('channels')}ch {raw.get('bits')}-bit float")

    # How hard the internal mix ran. This is the number that matters for the
    # nonlinear stages (reverb tanks now; waveshapers and fuzz from Phase 3).
    # It is NOT the output level -- see render.normalize_wav.
    model_err = raw_db - cfg.normalize
    print(f"  mix peak   {raw_peak:.4f} ({raw_db:+.2f} dBFS)   "
          f"model error {model_err:+.2f} dB")
    if raw_peak > 1.0:
        print("             (above 0 dBFS -- harmless in 32-bit float, but the "
              "reverb tanks ran hot)")

    # ---- Phase 6: the oversampled release master ----
    # Non-draft renders run at 96 kHz (they always have; ksmps=1 needs it for
    # the sample-accurate feedback paths and the nonlinear stages want the
    # alias headroom). The deliverable is 48 kHz: a linear-phase half-band
    # decimation, done here. Draft stays 48 kHz end to end.
    if not cfg.draft:
        from . import decimate as D
        if D.have_numpy():
            tmp = wav.with_suffix(".96k.wav")
            wav.rename(tmp)
            rep = D.decimate_by_2(tmp, wav)
            tmp.unlink()
            print(f"  decimate   96 kHz -> 48 kHz, {rep['taps']}-tap "
                  f"linear-phase half-band ({rep['out_frames']:,} frames)")
        else:
            print("  decimate   SKIPPED: numpy not importable -- the file is "
                  "96 kHz. (pip install numpy, or accept the 96k master.)")

    if args.do_normalize:
        nrm = R.normalize_wav(wav, cfg.normalize)
        if nrm["skipped"]:
            print("  normalize  skipped: render is silent")
        else:
            print(f"  normalize  {20 * math.log10(nrm['gain']):+.2f} dB  ->  "
                  f"peak {nrm['peak_after']:.4f} "
                  f"({20 * math.log10(nrm['peak_after']):+.2f} dBFS, "
                  f"target {cfg.normalize:g})")
    else:
        print("  normalize  SKIPPED (--no-normalize)")

    man = cfg.out.with_suffix(".txt")
    try:
        man.write_text("\n".join(MANIFEST) + "\n", encoding="utf-8")
        print(f"  manifest   {man}")
    except OSError as e:
        print(f"  manifest   not written ({e})")

    if not cfg.keep_csd:
        csd_path.unlink(missing_ok=True)

    return 0


def _render_estimate(cfg, stats) -> str:
    """Crude, honest: this is a sighting shot, not a promise."""
    if cfg.draft:
        return "draft mode -- seconds to a couple of minutes"
    load = stats["mean_concurrency"] * (cfg.sr / 44100) * (1.0 / cfg.ksmps if cfg.ksmps else 1)
    if cfg.ksmps == 1 and cfg.nodes > 150:
        return ("MINUTES TO HOURS. ksmps=1 at 96 kHz with "
                f"{cfg.note_count} notes is the expensive corner of the "
                "parameter space. Use --draft while iterating.")
    if cfg.ksmps == 1:
        return "ksmps=1 at 96 kHz is slow; expect well over realtime"
    return "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
