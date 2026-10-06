"""Scripts and pictures for the known-ads database, from recordings.

  python -m admute.scripts backfill [--dry-run]   every known clip without a full script or
                                                  pictures, looked for in the library's
                                                  recordings (those with cached fingerprints)
  python -m admute.scripts scan TAPE...           the same, in these recordings only
                                                  (admute.recordings runs it on each game)

Live, the sidecar keeps the words said over each clip as it learns it, and fills in a
clip's script when the clip airs again (admute/fingerprint.py). This finds the clips in
recordings instead: by their fingerprints, window by window, since a stored break may
hold an ad that a recording has on its own. The words come from where the clip aired:
the recording's cached Whisper words, or Whisper run on just that stretch.

Scripts go to the sidecar's inbox (admute-seeds/<name>.scripts.json), merged within a
minute; pictures straight to admute-ads/<clip>-<i>.jpg (the sidecar never overwrites
them). The database itself is read from the sidecar's last save.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

import numpy as np

from . import fingerprint as FP, replay, speech

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state", "master-candidate")
DB_PATH = os.path.join(STATE, "admute-prints.npz")
ADS = os.path.join(STATE, "admute-ads")
INBOX = os.path.join(STATE, "admute-seeds")
WINDOW = 8.0                 # a clip is looked for this many seconds at a time
MATCH = 0.2                  # share of a window's landmarks that must agree
MIN_VOTES = 10
PICTURES = (0.15, 0.4, 0.65, 0.9)   # as the sidecar's (admute.service.PICTURES)
MEDIA = (".mp4", ".ts", ".mkv")


def library(paths=None) -> list[str]:
    """Recordings to look in: these, or every one in the library with cached fingerprints."""
    if paths:
        return [replay.find_tape(p) for p in paths]
    cached = {os.path.basename(f)[:-len(".prints.npy")] for f in glob.glob(os.path.join(replay.CACHE, "*.prints.npy"))}
    out = []
    for name in sorted(os.listdir(replay.LIBRARY)):
        path = os.path.join(replay.LIBRARY, name)
        if name.endswith(MEDIA) and "(no ads)" not in name and replay.safe_name(path) in cached:
            out.append(path)
    return out


def wanted(db: FP.PrintDB, have_pictures: set) -> dict:
    """Clips worth looking for: no full script, or no pictures. {id: (kind, dur, t, h)}."""
    out = {}
    for cid, c in db.clips.items():
        sc = FP.script_view(c)
        if (sc["script"] is not None and sc["script_cover"] >= 0.8) and cid in have_pictures:
            continue
        rows = db.clip == cid
        order = np.argsort(db.off[rows], kind="stable")
        out[cid] = (c["kind"], float(c.get("dur") or 0.0), db.off[rows][order].astype(np.float64), db.h[rows][order])
    return out


def find(clip_t, clip_h, tape_t, tape_h):
    """Where a clip aired in a recording: [(clip a, clip b, tape time of the clip's 0)],
    from WINDOW-second pieces of the clip that match at one offset."""
    hits = []
    if not len(clip_t):
        return []
    for a in np.arange(clip_t[0], clip_t[-1] + 1e-6, WINDOW):
        k = (clip_t >= a) & (clip_t < a + WINDOW)
        n = int(k.sum())
        if n < MIN_VOTES:
            continue
        votes, _, d = FP._votes(clip_t[k], clip_h[k], tape_h, tape_t)
        if votes >= max(MIN_VOTES, MATCH * n):
            hits.append((float(a), float(min(a + WINDOW, clip_t[-1])), -d))
    found = []
    for a, b, at in sorted(hits, key=lambda x: (round(x[2]), x[0])):
        if found and abs(found[-1][2] - at) <= 1.0 and a <= found[-1][1] + WINDOW:
            found[-1][1] = b
        else:
            found.append([a, b, at])
    return [tuple(f) for f in found]


class Words:
    """A recording's words: its cached Whisper chunks, or Whisper on just a stretch."""

    def __init__(self, path):
        self.path = path
        self.chunks = speech.words_for(path, legacy=True) or []
        self.model = None

    def between(self, a, b):
        heard = sum(max(0.0, min(t1, b) - max(t0, a)) for t0, t1, _ in self.chunks)
        if heard >= 0.9 * (b - a):
            return [[w[0], w[2]] for t0, t1, ws in self.chunks if t1 > a and t0 < b
                    for w in ws if a <= (w[0] + w[1]) / 2 < b]
        if self.model is None:
            self.model = speech.load(speech.MODEL, threads=2)
        start = max(0.0, a - 1.0)
        audio = speech.decode_audio(self.path, start, b + 1.0)
        return [[w[0], w[2]] for w in speech.transcribe(self.model, audio, start) if a <= (w[0] + w[1]) / 2 < b]


def picture(path, at, out):
    """One 256x144 frame of a recording at ``at`` seconds."""
    tmp = out + ".tmp.jpg"
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{max(0.0, at):.2f}", "-i", path,
                    "-frames:v", "1", "-vf", "scale=256:144", "-q:v", "5", tmp], check=True)
    os.replace(tmp, out)


def run(paths=None, dry_run=False, db_path=DB_PATH, quiet=False) -> dict:
    db = FP.PrintDB(db_path)
    os.makedirs(ADS, exist_ok=True)
    have = {int(f.split("-")[0]) for f in os.listdir(ADS) if f.endswith(".jpg") and f.split("-")[0].isdigit()}
    todo = wanted(db, have)
    say = (lambda *a: None) if quiet else (lambda *a: print(*a, file=sys.stderr, flush=True))
    say(f"{len(todo)} of {len(db.clips)} clips want a script or pictures")
    scripts, pictured, sent = {}, set(), {}
    for path in library(paths):
        if not todo:
            break
        lm = FP.prints_for(path, compute=False)
        if lm is None:
            continue
        t, h = lm[:, 0], lm[:, 1].astype(np.uint32)
        k = FP.keep(h)
        order = np.argsort(h[k], kind="stable")
        tape_t, tape_h = t[k][order], h[k][order]
        words = None
        for cid, (kind, dur, ct, ch) in list(todo.items()):
            for a, b, at in find(ct, ch, tape_t, tape_h):
                lo, hi = max(-1.0, a - 1.0), min(dur + 1.0, b + 1.0)
                say(f"  clip {cid} ({kind}, {dur:.0f} s): {lo:.0f}-{hi:.0f} s of it at {at + lo:.0f} s in "
                    f"{os.path.basename(path)}")
                if dry_run:
                    continue
                sc = scripts.setdefault(cid, {"words": [], "cover": [], "from": "recording"})
                done = FP._union(sc["cover"])
                if sum(max(0.0, min(hi, y) - max(lo, x)) for x, y in done) >= 0.8 * (hi - lo):
                    continue                     # scripted already, from another recording
                words = words or Words(path)
                got = words.between(at + lo, at + hi)
                sc["words"] += [[round(w - at, 1), text] for w, text in got
                                if not any(x <= w - at < y for x, y in done)]
                sc["words"].sort(key=lambda w: w[0])
                sc["cover"] = FP._union(done + [[round(lo, 1), round(hi, 1)]])
                if cid not in have and cid not in pictured and kind == "ad" and hi - lo >= 0.6 * dur:
                    try:
                        for i, f in enumerate(PICTURES):
                            picture(path, at + lo + (hi - lo) * f, os.path.join(ADS, f"{cid}-{i}.jpg"))
                        pictured.add(cid)
                    except (OSError, subprocess.CalledProcessError) as exc:
                        say(f"  no pictures for clip {cid}: {exc}")
            sc = scripts.get(cid)
            if sc and sum(b - a for a, b in FP._union(sc["cover"])) >= 0.8 * (dur + 2) and (cid in have or cid in pictured
                                                                                         or kind != "ad"):
                del todo[cid]
        # Each recording's finds go to the sidecar at once: an interrupted run keeps its work.
        new = {cid: sc for cid, sc in scripts.items() if sent.get(cid) != len(sc["words"]) + len(sc["cover"])}
        if new and not dry_run:
            os.makedirs(INBOX, exist_ok=True)
            out = os.path.join(INBOX, time.strftime("scripts-%Y%m%d-%H%M%S-") + replay.safe_name(path)[:40] + ".scripts.json")
            with open(out + ".tmp", "w") as f:
                json.dump({"clips": new}, f)
            os.replace(out + ".tmp", out)
            sent.update({cid: len(sc["words"]) + len(sc["cover"]) for cid, sc in new.items()})
            say(f"wrote {out} ({len(new)} clips)")
    result = {"scripted": len(scripts), "pictured": len(pictured), "still_wanted": len(todo)}
    say(json.dumps(result))
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="admute.scripts", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("scan")
    s.add_argument("tapes", nargs="+")
    s.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    run(args.tapes if args.cmd == "scan" else None, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
