"""Teach the known-ads database from recordings, without waiting for them to air again.

  python -m admute.seed recording TAPE...     ad blocks from a truth file or the offline
                                              stripper's "(no ads).json" (the last block,
                                              if it runs to the end, may be the next show:
                                              left out)
  python -m admute.seed game TAPE --game-pk N --tape-start ISO
                                              an MLB game: the breaks between half-innings
                                              (MLB's feed), edges snapped to black seams
  python -m admute.seed build [--inbox]       write the seed: admute/known_ads_extra.npz, or
                                              (--inbox) a file the running sidecar merges
                                              within a minute

Games recorded on TV-Thing are learnt from by admute.recordings, which uses this.

Every ad block is trimmed at its edges, and any second whose sound matches show sound
(of any recording: themes, stingers) is left out. Show sound heard in two recordings
becomes known show sound, which can never be an ad. Results are collected in
state/admute/seed/ (one file of landmarks per recording) until "build".
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

from . import fingerprint as FP, replay

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(ROOT, "state", "admute", "seed")
EXTRA = os.path.join(ROOT, "admute", "known_ads_extra.npz")
INBOX = os.path.join(ROOT, "state", "master-candidate", "admute-seeds")
TRIM = (2.0, 5.0)
MIN_CONFIDENCE = 0.8


def _kept(path):
    lm = FP.prints_for(path)
    t, h = lm[:, 0], lm[:, 1].astype(np.uint32)
    k = FP.keep(h)
    return t[k], h[k]


def _spans_from_json(path):
    """[(start, end, label)] from a truth file or the stripper's (no ads).json."""
    base = os.path.basename(path)
    for truth_path in replay.truth_files():
        with open(truth_path) as f:
            truth = json.load(f)
        if truth.get("file") == base:
            return [(a, b, lab) for a, b, lab in truth["spans"]], "truth"
    stripped = os.path.splitext(path)[0] + " (no ads).json"
    if os.path.exists(stripped):
        with open(stripped) as f:
            d = json.load(f)
        blocks = d["blocks"]
        spans = []
        for i, b in enumerate(blocks):
            lab = b["label"]
            if lab == "ad" and (b.get("confidence", 1) < MIN_CONFIDENCE
                                or (i == len(blocks) - 1 and b["end"] >= d["duration"] - 1)):
                lab = "unsure"                      # low confidence, or perhaps the next show
            spans.append((b["start"], b["end"], lab))
        return spans, "stripper"
    return None, None


def save_recording(path, spans, how):
    """Keep a recording's landmarks with its ad/show spans, for build()."""
    t, h = _kept(path)
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(WORK, replay.safe_name(path) + ".npz")
    np.savez_compressed(out, t=t, h=h, spans=np.array(json.dumps({"spans": spans, "how": how, "file": os.path.basename(path)})))
    ads = sum(b - a for a, b, lab in spans if lab == "ad")
    print(f"{os.path.basename(path)}: {how}, {sum(1 for s in spans if s[2] == 'ad')} ad blocks ({ads / 60:.1f} min)")


def cmd_recording(tapes):
    for name in tapes:
        path = replay.find_tape(name)
        spans, how = _spans_from_json(path)
        if spans is None:
            print(f"{os.path.basename(path)}: no truth or stripper file; skipped")
            continue
        save_recording(path, spans, how)


LAG_RANGE = (-90, 300)        # seconds the broadcast may run behind MLB's feed (a paused Roku: more)
LAG_LOCAL = 45                # ... and how far one break's lag may wander from the game's
EDGE = 40                     # a break's black seam this close to the feed's last out / first pitch
AD_LIKE = 0.6                 # share of a break's seconds the detector must also call ad-like


def _feed(game_pk):
    from . import sports
    feed_path = os.path.join(replay.FEEDS, f"{game_pk}.json")
    if not os.path.exists(feed_path) or "Final" not in open(feed_path).read(200000):
        import urllib.request
        os.makedirs(replay.FEEDS, exist_ok=True)
        with urllib.request.urlopen(sports.FEED.format(pk=game_pk), timeout=20) as r:
            open(feed_path, "wb").write(r.read())
    with open(feed_path) as f:
        return json.load(f)


def align_breaks(edges, blacks, logit, lag=None):
    """Breaks from a game's feed, on a recording's (or a live broadcast's) own clock.

    edges: [(last pitch, next first pitch)] already on that clock (lag not applied);
    blacks: its black seams; logit: the detector's per-second ad evidence (> 0: ad-like).
    The lag is found as the shift that puts black seams at the most edges (unless given),
    then again for each break within LAG_LOCAL. A break runs from the first black seam
    after its last out to the last one before its first pitch, and is kept only if the
    detector finds at least AD_LIKE of it ad-like. Returns ([(start, end, "ad")], lag,
    [lag per break], how many were rejected as not ad-like).
    """
    blacks = np.asarray(blacks, float)
    logit = np.asarray(logit, float)

    def near(lo, hi):
        return blacks[(blacks >= lo) & (blacks <= hi)]

    def span_at(a, b, d):
        first, last = near(a + d, a + d + EDGE), near(b + d - EDGE, b + d + 5)
        if not len(first) or not len(last) or not 60 <= last[-1] - first[0] <= 300:
            return None
        x, y = int(first[0]), int(last[-1])
        seen = logit[x:min(y, len(logit))]
        return float(first[0]), float(last[-1]), float(np.mean(seen > 0)) if len(seen) else 0.0

    if lag is None:
        lag = max(range(LAG_RANGE[0], LAG_RANGE[1] + 1, 2),
                  key=lambda d: sum(span_at(a, b, d) is not None for a, b in edges))
    spans, lags, rejected = [], [], 0
    for a, b in edges:
        found = [(r[2], d, r) for d in range(lag - LAG_LOCAL, lag + LAG_LOCAL + 1) if (r := span_at(a, b, d))]
        if not found:
            continue
        like, d, (x, y, _) = max(found, key=lambda f: (f[0], -abs(f[1] - lag)))
        if like < AD_LIKE:
            rejected += 1
            continue
        if spans and x < spans[-1][1]:
            continue
        spans.append((round(x, 1), round(y, 1), "ad"))
        lags.append(d)
    return spans, lag, lags, rejected


def game_spans(path, game_pk, tape_start, length, halves=None, info=None):
    """Breaks of an MLB game, from its feed: between a half-inning's last pitch and the
    next one's first.

    The feed's times are real; the recording's are our clock, and the broadcast arrives
    late by a lag nobody tells us (YouTube TV: tens of seconds; a paused Roku: minutes),
    which can drift as the stream rebuffers. So:
      1. the game's lag is the shift that puts black seams at the most inning edges;
      2. each break's own lag is found again within LAG_LOCAL of that (drift);
      3. a break runs from the first black seam after its last out to the last one before
         its first pitch, so its edges are the broadcast's own, not the feed's;
      4. it is kept only if the detector, which knows nothing of the feed, also finds most
         of it ad-like (no score bug, an ad's look) -- a misplaced span fails this.
    """
    from . import sports
    from .detector import ArraySource, Detector
    offset = sports._ts(tape_start)
    if halves is None:
        halves, _, _ = sports.halves_from_feed(_feed(game_pk))   # [(first pitch, last pitch)] wall times
    edges = [(a1 - offset, b0 - offset) for (_, a1), (b0, _) in zip(halves, halves[1:]) if b0 - a1 >= 90]
    sig = replay.extract(path)
    det, src, t = Detector(), ArraySource(sig), 1.0
    end = src.available()
    while t <= end:
        det.update(src, t)
        t += 10.0
    blacks = np.array(sorted(s.t for s in det.seam_list() if s.kind == "black"))
    logit = np.array(det.lp_ad) - np.array(det.lp_show)

    spans, lag, lags, rejected = align_breaks(edges, blacks, logit)
    if info is not None:
        info.update(lag=lag, lags=lags, rejected=rejected, halves=len(edges))
    print(f"game {game_pk}: broadcast {lag} s behind the feed (per break {min(lags, default=lag)}..{max(lags, default=lag)} s); "
          f"{len(spans)} of {len(edges)} breaks kept, {rejected} not ad-like enough")
    out, cur = [], 0.0
    start_game = halves[0][0] - offset + lag if halves else 0.0
    for a, b, lab in spans:
        if a > cur:
            out.append((cur, a, "show" if cur >= start_game else "unsure"))
        out.append((a, b, lab))
        cur = b
    out.append((cur, length, "unsure"))
    return out


def cmd_game(tape, game_pk, tape_start):
    path = replay.find_tape(tape)
    length = float(replay.extract(path)["emb"].shape[0])
    save_recording(path, game_spans(path, game_pk, tape_start, length), f"mlb feed {game_pk}")


def build(out=EXTRA, only=None):
    """Collected recordings -> one seed of known ads (and known show sound). ``only``:
    take ads from these recordings (file names) alone; every recording's show still vetoes."""
    recs = []
    for f in sorted(os.listdir(WORK)) if os.path.isdir(WORK) else []:
        if f.endswith(".npz"):
            d = np.load(os.path.join(WORK, f))
            recs.append((d["t"], d["h"], json.loads(str(d["spans"]))))
    if not recs:
        print("nothing collected")
        return None
    # Show sound, every recording: the veto, and the source of known show sound.
    show = FP.PrintIndex()
    show.REBUILD = 0
    owner = []
    for i, (t, h, meta) in enumerate(recs):
        for a, b, lab in meta["spans"]:
            if lab == "show":
                k = (t >= a + 5) & (t < b - 5)
                show.add(t[k] + i * 1e6, h[k])              # recordings apart in time
    db = FP.PrintDB()
    stats = {"ad_blocks": 0, "ad_seconds": 0, "vetoed_seconds": 0, "show_clips": 0}
    for i, (t, h, meta) in enumerate(recs):
        if only is not None and meta["file"] not in only:
            continue
        words = _words(meta["file"])
        for a, b, lab in meta["spans"]:
            if lab != "ad" or b - a < 10:
                continue
            keep_t, keep_h = [], []
            for s in range(int(np.ceil(a + TRIM[0])), int(b - TRIM[1])):
                w = (t >= s - FP.WINDOW + 0.5) & (t < s + FP.WINDOW + 0.5)
                if w.sum() >= FP.MIN_LANDMARKS and show.votes(t[w] + i * 1e6, h[w]) >= 0.12 * w.sum():
                    stats["vetoed_seconds"] += 1        # sounds like a programme: never an ad
                    continue
                one = (t >= s) & (t < s + 1)
                keep_t.append(t[one])
                keep_h.append(h[one])
            if not keep_h:
                continue
            ct, ch = np.concatenate(keep_t), np.concatenate(keep_h)
            if db.add_clip("ad", ct, ch, {"seed": "extra", "src": meta["file"], "span": [a, b]},
                           words=words(a, b), span=(a, b), how="recording") is not None:
                stats["ad_blocks"] += 1
                stats["ad_seconds"] += len(keep_h)
    # Known show sound: show seconds of one recording heard (time-aligned) in another's show.
    for i, (t, h, meta) in enumerate(recs):
        if only is not None and meta["file"] not in only:
            continue
        others = FP.PrintIndex()
        others.REBUILD = 0
        for j, (t2, h2, meta2) in enumerate(recs):
            if j != i:
                for a, b, lab in meta2["spans"]:
                    if lab == "show":
                        k = (t2 >= a + 5) & (t2 < b - 5)
                        others.add(t2[k] + j * 1e6, h2[k])
        if not len(others):
            continue
        run = []
        for a, b, lab in meta["spans"] + [(0, 0, "end")]:
            for s in (range(int(a + 5), int(b - 5)) if lab == "show" else ()):
                w = (t >= s - 1.5) & (t < s + 2.5)
                if w.sum() >= FP.MIN_LANDMARKS and others.votes(t[w] + i * 1e6, h[w]) >= 0.12 * w.sum():
                    run.append(s)
                    continue
                run = _show_run(db, t, h, run, meta, stats)
            run = _show_run(db, t, h, run, meta, stats)
    db.dirty = True
    db.save(out)
    print(json.dumps({**stats, **db.summary(), "file": out}))
    return out


def _words(file):
    """A recording's cached Whisper words, as [[t, word]] for a span (None: not transcribed)."""
    from . import speech
    chunks = speech.words_for(replay.find_tape(file)) or []

    def between(a, b):
        heard = sum(max(0.0, min(t1, b) - max(t0, a)) for t0, t1, _ in chunks)
        if heard < 0.9 * (b - a):
            return None
        return [[w[0], w[2]] for t0, t1, ws in chunks if t1 > a and t0 < b for w in ws if a <= (w[0] + w[1]) / 2 < b]
    return between


def _show_run(db, t, h, run, meta, stats):
    if len(run) >= 4:
        k = (t >= run[0]) & (t < run[-1] + 1)
        if db.add_clip("show", t[k], h[k], {"seed": "extra", "src": meta["file"]}) is not None:
            stats["show_clips"] += 1
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(prog="admute.seed", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recording")
    r.add_argument("tapes", nargs="+")
    g = sub.add_parser("game")
    g.add_argument("tape")
    g.add_argument("--game-pk", type=int, required=True)
    g.add_argument("--tape-start", required=True, help="wall time of the recording's start (ISO)")
    b = sub.add_parser("build")
    b.add_argument("--inbox", action="store_true", help="for the running sidecar (state/master-candidate/admute-seeds)")
    args = ap.parse_args(argv)
    if args.cmd == "recording":
        cmd_recording(args.tapes)
    elif args.cmd == "game":
        cmd_game(args.tape, args.game_pk, args.tape_start)
    else:
        if args.inbox:
            inbox = os.path.join(ROOT, "state", "master-candidate", "admute-seeds")
            os.makedirs(inbox, exist_ok=True)
            tmp = build(os.path.join(WORK, "inbox.tmp.npz"))
            if tmp:
                os.replace(tmp, os.path.join(inbox, time.strftime("seed-%Y%m%d-%H%M%S.npz")))
        else:
            build()


if __name__ == "__main__":
    sys.exit(main())
