"""Run recordings through the live detector, causally, and score it.

  python -m admute.replay extract TAPE [--thumbs]   decode once into cached signals
  python -m admute.replay run TAPE [--lookahead 3]  detector + policy -> mute spans
  python -m admute.replay score [--lookahead 3]     every tape with a truth file

Extraction decodes the tape into exactly the live tap format (admute.tap) and
feeds admute.features, so replay sees what the master would send. The detector
then steps through the cached signals in 0.5 s ticks, seeing only what had
arrived by each tick.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time

import numpy as np

from . import features, tap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "state", "admute", "cache")
THUMBS = os.path.join(ROOT, "state", "admute", "thumbs")
LIBRARY = "/mnt/sda1/media/TV Recordings"
TRUTH_DIRS = [os.path.join(ROOT, "admute", "truth"), os.path.join(ROOT, "admute", "truth", "auto"),
              os.path.expanduser("~/scratch/ad_detection/data/truth")]   # auto: admute.recordings, from play-by-play


def _key(path: str, limit) -> str:
    st = os.stat(path)
    return hashlib.sha1(f"v1|{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}|{limit}".encode()).hexdigest()[:12]


def safe_name(path: str) -> str:
    base = os.path.splitext(os.path.basename(path))[0]
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in base)


def cache_path(path: str, limit=None) -> str:
    return os.path.join(CACHE, f"{safe_name(path)}.{_key(path, limit)}.npz")


def extract(path: str, *, limit=None, thumbs=False, use_cache=True) -> dict:
    cp = cache_path(path, limit)
    if use_cache and os.path.exists(cp):
        d = np.load(cp)
        return {k: d[k] for k in d.files}
    from .embed import Embedder
    sig = features.Signals(embed=Embedder(threads=2))
    thumb_dir = os.path.join(THUMBS, safe_name(path)) if thumbs else None
    on_thumb = None
    if thumb_dir:
        from PIL import Image
        os.makedirs(thumb_dir, exist_ok=True)

        def on_thumb(times, frames):
            for t, f in zip(times, frames):
                Image.fromarray(f).save(os.path.join(thumb_dir, f"{int(t):05d}.jpg"), quality=70)
    started = time.time()
    info = tap.decode_file(path, sig.push_gray, sig.push_rgb, sig.push_audio, limit=limit, thumbs=on_thumb)
    out = sig.snapshot()
    out.update(fps=np.array(info["fps"]), duration=np.array(info["duration"] if not limit else min(limit, info["duration"])))
    os.makedirs(CACHE, exist_ok=True)
    np.savez_compressed(cp, **out)
    print(f"extracted {path}: {len(out['cut']) / features.STEP_HZ:.0f}s in {time.time() - started:.0f}s",
          file=sys.stderr)
    return out


def run(sig: dict, *, model=None, cfg=None, gate=None, tick: float = 1.0, words=None, latency=None,
        prints=None, db=None, learn: bool = True, overlays=None) -> dict:
    """The live loop over a recording: at each tick the detector sees media up to
    the tick (and the words and fingerprints known by then), and the policy acts on
    the stretch ``lookahead`` behind it. Confirmed breaks teach the ad libraries as
    live (``db``: the known-ads database to start from; ``overlays``: an overlays.Library,
    by default the catalogue's)."""
    from .detector import ArraySource, Detector
    from .policy import Policy, PolicyConfig
    from .speech import GUARD, LATENCY
    cfg = cfg or PolicyConfig()
    det = Detector(model, prints=db, overlays=overlays)
    pol = Policy(cfg, gate=gate)
    # (a window's words come LATENCY after it ends, which is GUARD after the stretch it gives)
    src = ArraySource(sig, words, LATENCY + GUARD if latency is None else latency, prints=prints)
    learnt = set()
    end = src.available()
    aired, t = 0.0, tick
    timeline = []
    while t <= end + 1e-9:
        det.update(src, t)
        a = t - cfg.lookahead
        if a > aired:
            segs = det.decide(aired, a)
            pol.step(segs, t, ahead=det.decide(a, t, settle=False))
            for seg in segs:
                timeline.append((seg.start, seg.p_ad, int(pol.muted)))
            aired = a
            if learn:
                for sp in pol.learnable(aired, learnt):
                    det.learn_break(sp.start, sp.end)
        t += tick
    pol.finish(aired)
    return {"spans": pol.all_spans(), "timeline": np.array(timeline), "seams": det.seam_list(),
            "feats": {k: np.array(v) for k, v in det.feats.items()},
            "logit": np.array(det.lp_ad) - np.array(det.lp_show), "label": np.array(det.label),
            "duration": end}


def truth_steps(truth: dict, n: int) -> np.ndarray:
    """Per 0.1 s: 1 = ad, 0 = show, -1 = the next programme in a tape's post-roll
    (left out of the scores: live, a programme boundary is handled by the guide)."""
    y = np.zeros(n, np.int8)
    for a, b, lab in truth["spans"]:
        y[int(round(a * 10)):int(round(b * 10))] = {"ad": 1, "next": -1, "ignore": -1}.get(lab, 0)
    return y


def _runs(mask: np.ndarray):
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def score(result: dict, truth: dict) -> dict:
    n = int(result["duration"] * 10)
    y = truth_steps(truth, n)
    muted = np.zeros(n, bool)
    for sp in result["spans"]:
        muted[int(sp.start * 10):int((sp.end if sp.end is not None else result["duration"]) * 10)] = True
    hours = float((y >= 0).sum()) / 36000
    prog_muted = float((muted & (y == 0)).sum()) / 10
    ad_total = float((y == 1).sum()) / 10
    ad_muted = float((muted & (y == 1)).sum()) / 10
    breaks = []
    for a, b in _runs(y == 1):
        if b - a < 200:
            continue
        inside = np.flatnonzero(muted[a:b])
        onset = (inside[0] / 10) if len(inside) else None
        # programme muted straight after the break (clipped return)
        after = 0
        while b + after < n and muted[b + after] and y[b + after] == 0:
            after += 1
        breaks.append({"start": a / 10, "end": b / 10, "onset": onset,
                       "coverage": len(inside) / (b - a), "clipped": after / 10})
    false = [(a / 10, b / 10) for a, b in _runs(muted & (y == 0)) if b - a >= 5]
    return {"hours": hours, "program_muted": prog_muted, "program_muted_per_hour": prog_muted / max(hours, 1e-9),
            "ad_total": ad_total, "coverage": ad_muted / ad_total if ad_total else None,
            "retracted": sum(sp.end_reason == "retracted" for sp in result["spans"]),
            "spans": len(result["spans"]), "breaks": breaks, "false_mutes": false}


def fmt(t) -> str:
    return "--" if t is None else f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:04.1f}"


def report(name: str, sc: dict, result: dict, verbose: bool = True):
    print(f"== {name}")
    if verbose:
        for sp in result["spans"]:
            print(f"   mute {fmt(sp.start)} - {fmt(sp.end)} {(sp.end or 0) - sp.start:6.1f}s "
                  f"{'confirmed' if sp.confirmed else 'provisional'} -> {sp.end_reason}  peak {sp.peak:.3f}"
                  f"  seam {sp.seam}")
        for b in sc["breaks"]:
            print(f"   break {fmt(b['start'])} - {fmt(b['end'])} ({b['end'] - b['start']:.0f}s): "
                  f"onset +{b['onset'] if b['onset'] is not None else '--'}s  "
                  f"coverage {b['coverage']:.0%}  clipped {b['clipped']:.1f}s")
        for a, b in sc["false_mutes"]:
            print(f"   FALSE MUTE {fmt(a)} - {fmt(b)} ({b - a:.1f}s)")
    cov = sc["coverage"]
    print(f"   show muted {sc['program_muted']:.1f}s ({sc['program_muted_per_hour']:.1f}/h)   "
          f"ad coverage {cov:.1%}   spans {sc['spans']}  retracted {sc['retracted']}" if cov is not None else
          f"   show muted {sc['program_muted']:.1f}s   spans {sc['spans']}")


def load_truths() -> list[tuple[str, dict]]:
    out = []
    for f in truth_files():
        with open(f) as fh:
            out.append((f, json.load(fh)))
    return out


FEEDS = os.path.join(ROOT, "state", "admute", "feeds")


def gate_for(truth: dict | None):
    """The sports gate for a tape whose truth names its game (feed cached on disk)."""
    if not truth or not truth.get("feed"):
        return None
    from . import sports
    info = truth["feed"]
    path = os.path.join(FEEDS, f"{info['game_pk']}.json")
    if not os.path.exists(path):
        import urllib.request
        os.makedirs(FEEDS, exist_ok=True)
        with urllib.request.urlopen(sports.FEED.format(pk=info["game_pk"]), timeout=20) as r:
            open(path, "wb").write(r.read())
    with open(path) as f:
        feed = json.load(f)
    return sports.Gate.from_feed(feed, offset=sports._ts(info["tape_start"]))


def find_tape(name: str) -> str:
    if os.path.exists(name):
        return name
    return os.path.join(LIBRARY, name)


def truth_files() -> list[str]:
    return sorted(f for d in TRUTH_DIRS for f in glob.glob(os.path.join(d, "*.json")))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="admute.replay")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("tape")
    e.add_argument("--limit", type=float)
    e.add_argument("--thumbs", action="store_true")
    e.add_argument("--no-cache", action="store_true")
    r = sub.add_parser("run")
    r.add_argument("tape")
    r.add_argument("--lookahead", type=float, default=3.0)
    r.add_argument("--sensitivity", type=float)
    r.add_argument("--no-gate", action="store_true")
    r.add_argument("--no-text", action="store_true", help="leave out the transcript")
    r.add_argument("--no-prints", action="store_true", help="leave out the audio fingerprints")
    sc = sub.add_parser("score")
    sc.add_argument("--no-gate", action="store_true")
    sc.add_argument("--no-text", action="store_true", help="leave out the transcripts")
    sc.add_argument("--no-prints", action="store_true", help="leave out the audio fingerprints")
    sc.add_argument("--legacy-words", action="store_true",
                    help="the 4 s chunk transcripts from before 10/4 (words known 1.5 s after a chunk)")
    sc.add_argument("--lookahead", type=float, default=3.0)
    sc.add_argument("--sensitivity", type=float)
    sc.add_argument("-q", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd in ("run", "score"):
        from .policy import PolicyConfig
        cfg = (PolicyConfig.from_sensitivity(args.sensitivity, lookahead=args.lookahead)
               if args.sensitivity is not None else PolicyConfig(lookahead=args.lookahead))
        truths = {t["file"]: t for _, t in load_truths()}
        tapes = [find_tape(args.tape)] if args.cmd == "run" else [find_tape(f) for f in truths]
        for path in tapes:
            sig = extract(path)
            truth = truths.get(os.path.basename(path))
            from .speech import LATENCY, SCHEME, words_for
            legacy = getattr(args, "legacy_words", False)
            words = None if args.no_text else words_for(path, scheme=None if legacy else SCHEME)
            from .fingerprint import prints_for
            prints = None if args.no_prints else prints_for(path, compute=False)
            res = run(sig, cfg=cfg, gate=None if args.no_gate else gate_for(truth), words=words, prints=prints,
                      latency=LATENCY if legacy else None)
            if truth:
                report(os.path.basename(path), score(res, truth), res, verbose=not getattr(args, "q", False))
            else:
                print(f"== {os.path.basename(path)} (no truth)")
                for sp in res["spans"]:
                    print(f"   mute {fmt(sp.start)} - {fmt(sp.end)} {(sp.end or 0) - sp.start:6.1f}s "
                          f"{'confirmed' if sp.confirmed else 'provisional'} -> {sp.end_reason}  peak {sp.peak:.3f}")
        return
    if args.cmd == "extract":
        sig = extract(find_tape(args.tape), limit=args.limit, thumbs=args.thumbs, use_cache=not args.no_cache)
        print(json.dumps({k: list(np.shape(v)) for k, v in sig.items()}))


if __name__ == "__main__":
    main()
