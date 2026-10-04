"""Audio fingerprints: is this sound something heard before, and was that an ad?

Ads air again and again with the same soundtrack; the programme's talk, crowd and
commentary do not repeat. Landmark hashing (as Shazam does): the loudest points of the
spectrogram are paired into hashes (frequency, frequency, time between), each with its
time. The same recording, aired again, gives many of the same hashes at one constant
time offset, through re-encoding and level changes; different sound does not.

  Printer      -- 16 kHz mono in, (time, hash) out, as it streams
  PrintIndex   -- one broadcast's landmarks, searchable (sorted numpy arrays)
  PrintDB      -- known clips kept across days: ads, and show sounds that repeat, each
                  with its script (the words heard over it, on the clip's own clock)
  PrintEvidence-- per second for the detector:
                    known  -- matches a known ad (one heard in two confirmed breaks, or a
                              labelled recording's)
                    repeat -- repeats audio this broadcast already settled as an ad (not just
                              any repeat: themes, stingers and goal songs repeat too)
                    show   -- matches known show sound (the Jeopardy theme, the Think music):
                              it can only argue for sound, never for a mute

Only a consistent quarter of the hashes is kept (KEEP), so a 30 s ad is about 600
hashes (5 kB) and the same quarter is compared on every airing.
"""
from __future__ import annotations

import json
import os
import threading
import time

import numpy as np
from scipy import ndimage

RATE = 16000
NFFT = 1024
HOP = 256                    # 16 ms
F_LO, F_HI = 8, 256          # bins: 125 Hz - 4 kHz
PEAK_T, PEAK_F = 15, 15      # neighbourhood of a peak (frames, bins)
PEAKS_PER_SEC = 30
FAN = 5                      # each peak pairs with this many later ones
DT_MIN, DT_MAX = 2, 64       # frames between the paired peaks
DF_MAX = 64
HOPS_PER_SEC = RATE / HOP
WINDOW = 2.0                 # a second is judged by the landmarks within this either side
MIN_LANDMARKS = 8            # fewer (near silence): no evidence
STOP = 400                   # a hash this common says nothing
LATENCY = 2.5                # replay: landmarks known this long after their time


class Printer:
    """Streaming landmarks. push(samples) returns [(t, hash)] for the audio now settled.
    Frames keep PEAK_T frames of context either side, so a block boundary changes nothing."""

    def __init__(self, t0: float = 0.0):
        self.t0 = t0
        self.buf = np.zeros(0, np.float32)
        self.frame0 = 0                # absolute frame index of buf[0]
        self.upto = 0                  # peaks are final before this frame
        self.window = np.hanning(NFFT).astype(np.float32)
        self.peaks = []                # (frame, bin), waiting for partners

    @property
    def known(self) -> float:
        """Landmarks are complete before this time."""
        return self.t0 + max(0, self.upto - DT_MAX) * HOP / RATE

    def push(self, samples: np.ndarray) -> list:
        self.buf = np.concatenate([self.buf, np.asarray(samples, np.float32)])
        n = (len(self.buf) - NFFT) // HOP + 1
        done = self.frame0 + n - PEAK_T // 2 - 1     # neighbourhoods complete before this
        if done - self.upto < int(HOPS_PER_SEC):
            return []
        frames = np.lib.stride_tricks.sliding_window_view(self.buf[: (n - 1) * HOP + NFFT], NFFT)[::HOP]
        spec = np.abs(np.fft.rfft(frames * self.window, axis=1))[:, F_LO:F_HI]
        logs = np.log(spec + 1e-6)
        # Peaks: local maxima clearly above the frame's level, the strongest per second.
        local = ndimage.maximum_filter(logs, size=(PEAK_T, PEAK_F), mode="nearest") == logs
        local &= logs > (np.median(logs, axis=1, keepdims=True) + 1.5)
        local &= spec > 1e-3
        fi, bi = np.nonzero(local)
        absf = fi + self.frame0
        ok = (absf >= self.upto) & (absf < done)
        fi, bi, absf = fi[ok], bi[ok], absf[ok]
        if len(fi):
            strength = logs[fi, bi]
            sec = absf // int(HOPS_PER_SEC)
            for s_ in np.unique(sec):
                idx = np.flatnonzero(sec == s_)
                idx = idx[np.argsort(-strength[idx])[:PEAKS_PER_SEC]]
                self.peaks += [(int(absf[i]), int(bi[i])) for i in idx]
            self.peaks.sort()
        self.upto = done
        out = []
        for k, (f1, b1) in enumerate(self.peaks):
            if f1 >= done - DT_MAX:
                break
            fan = 0
            for f2, b2 in self.peaks[k + 1:]:
                dt = f2 - f1
                if dt > DT_MAX:
                    break
                if dt < DT_MIN or abs(b2 - b1) > DF_MAX:
                    continue
                out.append((self.t0 + f1 * HOP / RATE, (b1 << 16) | (b2 << 7) | dt))
                fan += 1
                if fan >= FAN:
                    break
        self.peaks = [p for p in self.peaks if p[0] >= done - DT_MAX]
        keep_from = max(0, done - PEAK_T - self.frame0)          # context for the next block
        self.buf = self.buf[keep_from * HOP:]
        self.frame0 += keep_from
        return out


def prints(audio: np.ndarray, t0: float = 0.0, block: float = 4.0) -> list:
    """All landmarks of a recording, as live would produce them."""
    p = Printer(t0)
    out = []
    step = int(block * RATE)
    for i in range(0, len(audio), step):
        out += p.push(audio[i:i + step])
    return out


def keep(hashes: np.ndarray) -> np.ndarray:
    """The consistent quarter of hashes that is stored and compared."""
    h = np.asarray(hashes, np.uint64)
    return ((h * np.uint64(2654435761)) & np.uint64(0xFFFFFFFF)) >> np.uint64(30) == 0


def _votes(qt, qh, h, t, key=None, gap=None):
    """Best aligned vote: query landmarks (qt, qh) against sorted hashes h with times t
    (and clip keys). Returns (votes, best key or None, offset)."""
    if not len(qh) or not len(h):
        return 0, None, None
    lo, hi = np.searchsorted(h, qh, "left"), np.searchsorted(h, qh, "right")
    n = hi - lo
    use = (n > 0) & (n <= STOP)
    if not use.any():
        return 0, None, None
    q = np.repeat(np.flatnonzero(use), n[use])
    rows = np.concatenate([np.arange(a, b) for a, b in zip(lo[use], hi[use])])
    d = qt[q] - t[rows]
    if gap is not None:
        ok = d >= gap
        d, rows = d[ok], rows[ok]
        if not len(d):
            return 0, None, None
    bins = np.round(d * 4).astype(np.int64) + 5_000_000      # offsets of up to +-14 days
    k = key[rows].astype(np.int64) if key is not None else np.zeros(len(bins), np.int64)
    pair = k * 10_000_000 + bins                     # (clip, offset bin)
    u, c = np.unique(pair, return_counts=True)
    # an airing's timing wobbles a little: count neighbouring offset bins together
    pos = np.searchsorted(u, u - 1), np.searchsorted(u, u + 1)
    near = c.copy()
    for p, delta in zip(pos, (-1, 1)):
        hit = (p < len(u)) & (u[np.minimum(p, len(u) - 1)] == u + delta)
        near[hit] += c[p[hit]]
    best = int(np.argmax(near))
    return (int(near[best]), int(u[best] // 10_000_000) if key is not None else None,
            (u[best] % 10_000_000 - 5_000_000) / 4)


def _union(spans) -> list:
    """Overlapping [a, b] ranges, merged."""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + 0.5:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [[round(a, 1), round(b, 1)] for a, b in out]


LINE_GAP = 1.2               # a pause this long between words starts a new line of a script
LINE_WORDS = 18


def script_view(c: dict) -> dict:
    """A clip's script for the page: lines of text, and how much of the clip it covers."""
    sc = c.get("script")
    if not sc:
        return {"script": None}
    lines, cur, last = [], [], None
    for t, w in sc["words"]:
        if cur and (t - last >= LINE_GAP or len(cur) >= LINE_WORDS):
            lines.append([round(start, 1), " ".join(cur)])
            cur = []
        if not cur:
            start = t
        cur.append(w)
        last = t
    if cur:
        lines.append([round(start, 1), " ".join(cur)])
    dur = float(c.get("dur") or 0.0)
    cover = sum(b - a for a, b in sc.get("cover") or ()) / (dur + 2.0) if dur else 1.0
    return {"script": lines, "script_cover": round(min(1.0, cover), 2), "script_from": sc.get("from"),
            "script_at": sc.get("at")}


class PrintIndex:
    """Landmarks of one broadcast, (time, hash). Additions become searchable in batches
    (re-sorting every second would cost too much): at most REBUILD seconds late."""

    REBUILD = 30

    def __init__(self):
        self._t, self._h = [], []
        self.t = np.zeros(0, np.float32)
        self.h = np.zeros(0, np.uint32)
        self.dirty = False

    def add(self, t: np.ndarray, h: np.ndarray) -> None:
        if len(h):
            self._t.append(np.asarray(t, np.float32))
            self._h.append(np.asarray(h, np.uint32))
            self.dirty = True

    def _build(self):
        if self.dirty and (len(self._h) >= self.REBUILD or not len(self.h)):
            t = np.concatenate([self.t] + self._t)
            h = np.concatenate([self.h] + self._h)
            order = np.argsort(h, kind="stable")
            self.t, self.h = t[order], h[order]
            self._t, self._h, self.dirty = [], [], False

    def votes(self, qt, qh, gap=None) -> int:
        self._build()
        return _votes(np.asarray(qt, np.float64), np.asarray(qh, np.uint32), self.h, self.t, gap=gap)[0]

    def __len__(self):
        return len(self.h) + sum(len(x) for x in self._h)


class PrintDB:
    """Known clips, kept across days: kind 'ad' or 'show'. An ad clip counts once heard
    in KNOWN_BREAKS separate breaks (or seeded from labelled recordings); a show clip
    counts at once (it can only ever argue for sound)."""

    KNOWN_BREAKS = 2
    MERGE = 0.25                 # a new clip this much like a stored one is that clip again
    MAX_CLIPS = {"ad": 3000, "show": 500}

    def __init__(self, path: str | None = None):
        self.path = path
        self.lock = threading.Lock()
        self.clips: dict[int, dict] = {}
        self.h = np.zeros(0, np.uint32)
        self.off = np.zeros(0, np.float32)
        self.clip = np.zeros(0, np.uint32)
        self.next_id = 1
        self.dirty = False
        self.version = 0
        self._views = {}
        self.seeds: list[str] = []       # seeds merged (tags)
        if path and os.path.exists(path):
            self.load(path)

    # storage -----------------------------------------------------------------------
    def load(self, path):
        with np.load(path, allow_pickle=False) as d:
            self.h, self.off, self.clip = d["h"].astype(np.uint32), d["off"].astype(np.float32), d["clip"].astype(np.uint32)
            meta = json.loads(str(d["meta"]))
        self.clips = {int(k): v for k, v in meta["clips"].items()}
        self.next_id = int(meta.get("next_id", max(self.clips, default=0) + 1))
        self.seeds = list(meta.get("seeds", []))
        self.version += 1

    def save(self, path=None):
        path = path or self.path
        if not path or not self.dirty:
            return
        with self.lock:
            h, off, clip = self.h.copy(), self.off.copy(), self.clip.copy()
            meta = json.dumps({"clips": self.clips, "next_id": self.next_id, "seeds": self.seeds})
            self.dirty = False
        tmp = path + ".tmp.npz"
        np.savez_compressed(tmp, h=h, off=off, clip=clip, meta=np.array(meta))
        os.replace(tmp, path)

    def merge_seed(self, seed: "PrintDB", tag: str) -> int:
        """Add a seed (labelled recordings) once, by its tag. A clip already known is the
        same clip heard again; the rest are added. Returns how many clips were new."""
        with self.lock:
            if tag in self.seeds:
                return 0
        new = 0
        for cid, c in seed.clips.items():
            rows = seed.clip == cid
            h, off = seed.h[rows], seed.off[rows]
            votes, got, offset = self.match(off, h, c["kind"], known_only=False)
            if got is not None and votes >= self.MERGE * len(h):
                with self.lock:
                    mine = self.clips.get(got)
                    if mine is not None:
                        mine["breaks"] += 1
                        mine.setdefault("seed", tag)
                        self.version += 1
                        self.dirty = True
                sc = c.get("script")
                if sc:               # the seed's words, moved onto this clip's clock
                    for a, b in sc.get("cover") or ():
                        self.set_script(got, [w for w in sc["words"] if a <= w[0] < b], offset, sc.get("from", "recording"),
                                        (a, b))
                continue
            self._insert(c["kind"], off, h, {**c, "seed": tag})
            new += 1
        with self.lock:
            self.seeds.append(tag)
            self.dirty = True
        return new

    # clips -------------------------------------------------------------------------
    def _insert(self, kind, off, h, meta) -> int:
        with self.lock:
            cid = self.next_id
            self.next_id += 1
            self.clips[cid] = {"kind": kind, "breaks": 1, "first": time.time(), "last": time.time(), **meta}
            h = np.asarray(h, np.uint32)
            allh = np.concatenate([self.h, h])
            order = np.argsort(allh, kind="stable")
            self.h = allh[order]
            self.off = np.concatenate([self.off, np.asarray(off, np.float32)])[order]
            self.clip = np.concatenate([self.clip, np.full(len(h), cid, np.uint32)])[order]
            self.dirty = True
            self.version += 1
            self._trim(kind)
            return cid

    def _trim(self, kind):
        mine = [cid for cid, c in self.clips.items() if c["kind"] == kind and not c.get("seed")]
        over = len([c for c in self.clips.values() if c["kind"] == kind]) - self.MAX_CLIPS[kind]
        if over > 0:
            for cid in sorted(mine, key=lambda c: self.clips[c]["last"])[:over]:
                self._drop(cid)

    def _drop(self, cid):
        rows = self.clip != cid
        self.h, self.off, self.clip = self.h[rows], self.off[rows], self.clip[rows]
        self.clips.pop(cid, None)
        self.dirty = True
        self.version += 1

    def clips_of(self, span_ids) -> list:
        """Clips learnt from these breaks."""
        with self.lock:
            return [cid for cid, c in self.clips.items() if set(c.get("spans") or ()) & set(span_ids)]

    def remove(self, ids) -> list:
        with self.lock:
            gone = [cid for cid in ids if cid in self.clips]
            for cid in gone:
                self._drop(cid)
            return gone

    def add_clip(self, kind: str, t: np.ndarray, h: np.ndarray, meta: dict | None = None, words=None,
                 span=None, how: str = "broadcast") -> int | None:
        """A stretch of audio (kept landmarks): the same clip heard again, or a new one.
        ``words`` [[t, word]] heard over ``span`` (a, b) on the same clock become its script
        (None: not transcribed)."""
        t, h = np.asarray(t, np.float64), np.asarray(h, np.uint32)
        if len(h) < 4 * MIN_LANDMARKS:
            return None
        if span is None:
            span = (float(t[0]), float(t[-1]))
        votes, cid, offset = self.match(t, h, kind, known_only=False)
        if cid is not None and votes >= self.MERGE * len(h):
            with self.lock:
                c = self.clips.get(cid)
                if c is not None:
                    c["breaks"] += 1
                    c["last"] = time.time()
                    for k, v in (meta or {}).items():
                        if k == "spans":
                            c["spans"] = (c.get("spans") or []) + list(v)
                        else:
                            c.setdefault(k, v)
                    self.dirty = True
                    self.version += 1
            self.set_script(cid, words, offset, how, span)
            return cid
        cid = self._insert(kind, t - t[0], h, dict(meta or {}, dur=round(float(t[-1] - t[0]), 1)))
        self.set_script(cid, words, float(t[0]), how, span)
        return cid

    def set_script(self, cid, words, offset: float, how: str, span) -> bool:
        """Words heard over an airing of a clip: ``words`` [[t, word]] over ``span`` (a, b) of
        the airing's clock, on which the clip's 0 fell at ``offset``. They fill the part of
        the clip's script they cover, unless that part is scripted already and these are no
        fuller (a 30 s ad is scripted once; a stored break, a spot at a time). None: the
        airing was not transcribed, which says nothing."""
        if words is None or cid is None or offset is None:
            return False
        with self.lock:
            c = self.clips.get(cid)
            if c is None:
                return False
            dur = float(c.get("dur") or 0.0)
            a, b = max(-1.0, span[0] - offset), min(dur + 1.0, span[1] - offset)
            if b - a < 2.0:
                return False
            new = [[round(float(t) - offset, 1), str(w)] for t, w in words if a <= float(t) - offset < b]
            sc = c.get("script") or {"words": [], "cover": []}
            old = [w for w in sc["words"] if a <= w[0] < b]
            covered = sum(max(0.0, min(b, y) - max(a, x)) for x, y in sc["cover"])
            if covered >= 0.8 * (b - a) and len(new) < 1.25 * len(old) + 2:
                return False
            rest = [w for w in sc["words"] if not a <= w[0] < b]
            c["script"] = {"words": sorted(rest + new, key=lambda w: w[0]), "cover": _union(sc["cover"] + [[a, b]]),
                           "from": how, "at": round(time.time())}
            self.dirty = True
            self.version += 1
            return True

    def rename(self, cid, name: str) -> bool:
        with self.lock:
            c = self.clips.get(cid)
            if c is None:
                return False
            name = " ".join(str(name).split())[:80]
            if name:
                c["name"] = name
            else:
                c.pop("name", None)
            self.dirty = True
            self.version += 1
            return True

    def known(self, cid) -> bool:
        c = self.clips.get(cid)
        return bool(c) and (c["kind"] == "show" or c.get("seed") is not None
                            or c["breaks"] >= c.get("need", self.KNOWN_BREAKS))

    def evidence(self, cid) -> bool:
        """Does matching this clip count as hearing an ad? A known clip does; so does a
        spot heard once that needs only one more airing: matching it *is* that airing."""
        c = self.clips.get(cid)
        if not c:
            return False
        return self.known(cid) or (bool(c.get("spot")) and c["breaks"] >= c.get("need", self.KNOWN_BREAKS) - 1)

    def match(self, t, h, kind, known_only=True):
        """(votes, clip id, offset) of the best clip of this kind for landmarks (t, h)."""
        with self.lock:
            view = self._views.get((kind, known_only))
            if view is None or view[0] != self.version:
                ids = np.array([cid for cid, c in self.clips.items()
                                if c["kind"] == kind and (not known_only or self.evidence(cid))], np.uint32)
                sel = np.isin(self.clip, ids)
                view = (self.version, self.h[sel], self.off[sel], self.clip[sel])
                self._views[(kind, known_only)] = view
            _, hh, oo, cc = view
        return _votes(np.asarray(t, np.float64), np.asarray(h, np.uint32), hh, oo, key=cc)

    def catalogue(self) -> list:
        """Every clip's description, for the page (no landmarks)."""
        with self.lock:
            n = {}
            for cid in self.clip.tolist():
                n[cid] = n.get(cid, 0) + 1
            return [{"id": cid, "kind": c["kind"], "known": self.known(cid), "breaks": c.get("breaks", 1),
                     "need": c.get("need", self.KNOWN_BREAKS), "spot": c.get("spot") or ("spot" if c.get("need") else None),
                     "first": round(c.get("first", 0)), "last": round(c.get("last", 0)), "dur": c.get("dur"),
                     "src": c.get("src"), "seed": c.get("seed"), "hashes": n.get(cid, 0), "name": c.get("name"),
                     **script_view(c)}
                    for cid, c in self.clips.items()]

    def summary(self):
        with self.lock:
            ads = [c for c in self.clips.values() if c["kind"] == "ad"]
            return {"ads": sum(self.known(cid) for cid, c in self.clips.items() if c["kind"] == "ad"),
                    "ad_candidates": len(ads), "seeded": sum(1 for c in ads if c.get("seed")),
                    "show": sum(1 for c in self.clips.values() if c["kind"] == "show"),
                    "hashes": int(len(self.h))}


class PrintEvidence:
    """A broadcast's landmarks, judged second by second against what is known."""

    REPEAT_RUN = 4               # seconds of show that repeats earlier show, to learn it as show sound
    SHOW_CLEAR = 30              # ... at least this far from anything settled as ad
    SHOW_REPEAT = 0.12           # share of a second's landmarks that must agree to call it a repeat

    def __init__(self, db: PrintDB | None = None):
        self.db = db if db is not None else PrintDB()
        self.t = np.zeros(0, np.float64)
        self.h = np.zeros(0, np.uint32)
        self._pending = []
        self.known = None            # landmarks complete up to this time
        self.ads = PrintIndex()      # this broadcast's audio settled as ad
        self.show = PrintIndex()     # ... and as show
        self.learnt_to = 0
        self.show_run = []           # consecutive settled show seconds that repeat earlier show
        self.session = None          # which broadcast this is (to tell its own spots from repeats)
        self.pods_done = set()
        self.words = None            # callable(a, b) -> [[t, word]] said then, or None (not transcribed)
        self.aired = []              # (clip id, start, end) stored or heard here, for their pictures
        self.hits = {}               # second -> (clip id, offset): the known ad it matched
        self.scribed_to = 0
        self.runs = {}               # clip id -> [first second, last second, offset] of its airing now

    def add(self, landmarks, known_upto: float) -> None:
        if landmarks:
            a = np.asarray(landmarks, np.float64)
            t, h = a[:, 0], a[:, 1].astype(np.uint32)
            k = keep(h)
            self._pending.append((t[k], h[k]))
        self.known = known_upto if self.known is None else max(self.known, known_upto)

    def _flush(self):
        if self._pending:
            self.t = np.concatenate([self.t] + [p[0] for p in self._pending])
            self.h = np.concatenate([self.h] + [p[1] for p in self._pending])
            order = np.argsort(self.t, kind="stable")
            self.t, self.h = self.t[order], self.h[order]
            self._pending = []

    def span(self, a: float, b: float):
        self._flush()
        i, j = np.searchsorted(self.t, a), np.searchsorted(self.t, b)
        return self.t[i:j], self.h[i:j]

    def features(self, s: int, blacks=()) -> dict:
        """Evidence for second s from the landmarks around it, never across a black seam:
        an ad's sound must not reach into the programme next to it (nor the reverse)."""
        lo, hi = s - WINDOW + 0.5, s + WINDOW + 0.5
        k = int(np.searchsorted(blacks, s + 0.5, "right")) if len(blacks) else 0
        if k:
            lo = max(lo, blacks[k - 1])
        if k < len(blacks):
            hi = min(hi, blacks[k])
        qt, qh = self.span(lo, hi)
        out = {"known": np.nan, "repeat": np.nan, "show": np.nan}
        if len(qh) < MIN_LANDMARKS:
            return out
        n = len(qh)
        votes, cid, offset = self.db.match(qt, qh, "ad")
        own = self.db.clips.get(cid, {}) if cid is not None else {}
        if own.get("session") == self.session and offset is not None and abs(offset - own.get("at", -1e9)) < 3:
            votes = 0                          # this very airing, stored a moment ago: not a repeat
        out["known"] = votes / n
        if votes >= self.SHOW_REPEAT * n:
            self.hits[s] = (cid, offset)
        else:
            self.hits.pop(s, None)
        out["show"] = self.db.match(qt, qh, "show")[0] / n
        out["repeat"] = self.ads.votes(qt, qh) / n if len(self.ads) else 0.0
        return out

    def learn(self, upto: int, labels) -> None:
        """Seconds the detector has settled go into this broadcast's ad or show index. Show
        that repeats earlier show, well clear of any ad, becomes known show sound."""
        while self.learnt_to < upto:
            s = self.learnt_to
            lab = labels[s] if s < len(labels) else -1
            t, h = self.span(s, s + 1)
            if lab == 1:
                self.ads.add(t, h)
            elif lab == 0:
                qt, qh = self.span(s - WINDOW + 0.5, s + WINDOW + 0.5)
                clear = all(labels[k] == 0 for k in range(max(0, s - self.SHOW_CLEAR), min(len(labels), s + 1)))
                rep = len(qh) >= MIN_LANDMARKS and self.show.votes(qt, qh, gap=60) >= self.SHOW_REPEAT * len(qh)
                if rep and clear:
                    self.show_run.append(s)
                else:
                    self._show_clip()
                self.show.add(t, h)
            self.learnt_to += 1

    def _show_clip(self):
        if len(self.show_run) >= self.REPEAT_RUN:
            t, h = self.span(self.show_run[0], self.show_run[-1] + 1)
            self.db.add_clip("show", t, h, {"src": "repeat"})
        self.show_run = []

    def remember(self, kind, t, h, meta, a: float, b: float):
        """Store [a, b) of this broadcast as a clip (or count it as a clip heard again), with
        the words said over it as its script."""
        cid = self.db.add_clip(kind, t, h, meta, words=self.words(a, b) if self.words else None, span=(a, b))
        if cid:
            self.aired.append((cid, a, b))
        return cid

    def scribe(self, upto: int) -> None:
        """Known ads heard again, once each airing is over (seconds before ``upto`` are
        final): the words said over it fill in its script where it has none (clips learnt
        before scripts were kept, or a stored break a spot at a time), and its pictures."""
        while self.scribed_to < upto:
            s = self.scribed_to
            hit = self.hits.pop(s, None)
            for cid, run in list(self.runs.items()):
                if s - run[1] > 3 or (hit and hit[0] == cid and abs(hit[1] - run[2]) > 1.5):
                    self._heard(cid, *self.runs.pop(cid))
            if hit:
                cid, offset = hit
                run = self.runs.get(cid)
                if run:
                    run[1] = s
                else:
                    self.runs[cid] = [s, s, offset]
            self.scribed_to += 1
        for k in [k for k in self.hits if k < upto - 600]:
            del self.hits[k]

    def _heard(self, cid, first: int, last: int, offset: float):
        c = self.db.clips.get(cid)
        if c is None or last - first < 3:
            return
        dur = float(c.get("dur") or 0.0)
        a, b = max(offset - 0.5, first - 1.0), min(offset + dur + 0.5, last + 2.0)
        if b - a < 3:
            return
        if self.words:
            self.db.set_script(cid, self.words(a, b), offset, "broadcast", (a, b))
        self.aired.append((cid, a, b))

    def ad_clip(self, start: float, end: float, labels=None, trim=(2.0, 5.0)):
        """The landmarks of a confirmed break worth remembering: its uncertain edges
        trimmed, only seconds settled as ad (labels None: all of them, the break being
        known some other way), and none that sound like known show."""
        keep_t, keep_h = [], []
        for s in range(int(np.ceil(start + trim[0])), int(end - trim[1])):
            if labels is not None and (s >= len(labels) or labels[s] != 1):
                continue
            qt, qh = self.span(s - WINDOW + 0.5, s + WINDOW + 0.5)
            if len(qh) >= MIN_LANDMARKS and (self.db.match(qt, qh, "show")[0] >= self.SHOW_REPEAT * len(qh)
                                             or self.show.votes(qt, qh) >= self.SHOW_REPEAT * len(qh)):
                continue                       # sounds like the programme: never an ad
            t, h = self.span(s, s + 1)
            keep_t.append(t)
            keep_h.append(h)
        if not keep_h:
            return np.zeros(0), np.zeros(0, np.uint32)
        return np.concatenate(keep_t), np.concatenate(keep_h)

    SPOT = (4.0, 95.0)           # a spot between black seams: 15, 30, 60 s ads (NBC: often two together)

    def spots(self, start: float, end: float, blacks, trim=(2.0, 5.0), edge=0.5):
        """A break cut into spots at its black seams: [(t, h, interior, (a, b))]. Fragments
        shorter than a spot join the next; the break's own edges are trimmed more than a
        spot's. An interior spot is wedged between two others, so it is an ad's own sound.
        (a, b) is the spot untrimmed, for its words."""
        cuts = [start] + [b for b in blacks if start + 1 < b < end - 1] + [end]
        pieces, cur = [], cuts[0]
        for b in cuts[1:]:
            if b - cur >= self.SPOT[0] or b == end:
                pieces.append((cur, b))
                cur = b
        out = []
        for i, (a, b) in enumerate(pieces):
            if not self.SPOT[0] <= b - a <= self.SPOT[1]:
                continue
            lo = a + (trim[0] if i == 0 else edge)
            hi = b - (trim[1] if i == len(pieces) - 1 else edge)
            if hi - lo < self.SPOT[0] - 1:
                continue
            t, h = self.ad_clip(lo, hi, None, trim=(0.0, 0.0))
            if len(h):
                out.append((t, h, 0 < i < len(pieces) - 1, (a, b)))
        return out

    def pods(self, blacks, upto: float, meta=None) -> list:
        """Spots wedged in a pod: a stretch of SPOT length between black seams, with spots
        of SPOT length on both sides -- the shape of an ad break, whatever the detector
        made of it. Each is stored once, heard once; its next airing makes it an ad.
        Only black seams before ``upto`` (settled) are used. Returns the new clip ids."""
        cuts = [b for b in blacks if b < upto]
        pieces, cur = [], cuts[0] if cuts else None
        for b in cuts[1:]:
            if b - cur >= self.SPOT[0]:
                pieces.append((cur, b))
                cur = b
        new = []
        for (a0, b0), (a, b), (a2, b2) in zip(pieces, pieces[1:], pieces[2:]):
            if a in self.pods_done or not all(self.SPOT[0] <= y - x <= self.SPOT[1] for x, y in ((a0, b0), (a, b), (a2, b2))):
                continue
            self.pods_done.add(a)
            t, h = self.ad_clip(a + 0.5, b - 0.5, None, trim=(0.0, 0.0))
            if len(h) < 4 * MIN_LANDMARKS:
                continue
            cid = self.remember("ad", t, h, {"spot": "pod", "need": 2, "session": self.session, "at": float(t[0]),
                                             **(meta or {})}, a, b)
            if cid:
                new.append(cid)
        return new

    def matched_ads(self, a: float, b: float) -> list:
        """Known ad clips playing in [a, b): what "it's the show" there unlearns."""
        qt, qh = self.span(a, b)
        if len(qh) < MIN_LANDMARKS:
            return []
        votes, cid, _ = self.db.match(qt, qh, "ad", known_only=False)
        return [cid] if cid is not None and votes >= self.SHOW_REPEAT * len(qh) else []


def landmarks_of(path: str) -> np.ndarray:
    """A recording's landmarks [(t, hash)], decoded as live (16 kHz mono, streamed)."""
    import subprocess
    proc = subprocess.Popen(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path, "-vn", "-ac", "1",
                             "-ar", str(RATE), "-f", "f32le", "-"], stdout=subprocess.PIPE)
    p, out = Printer(), []
    while True:
        raw = proc.stdout.read(RATE * 4 * 8)
        if not raw:
            break
        out += p.push(np.frombuffer(raw, "<f4"))
    proc.wait()
    return np.array(out, np.float64).reshape(-1, 2)


def cache_path(path: str) -> str:
    from .replay import CACHE, safe_name
    return os.path.join(CACHE, f"{safe_name(path)}.prints.npy")


def prints_for(path: str, compute: bool = True):
    """Cached landmarks of a recording, or None."""
    cp = cache_path(path)
    if os.path.exists(cp):
        return np.load(cp)
    if not compute:
        return None
    lm = landmarks_of(path)
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    np.save(cp, lm)
    return lm


def main(argv=None):
    import argparse
    from .replay import find_tape
    ap = argparse.ArgumentParser(prog="admute.fingerprint", description="cache a recording's landmarks")
    ap.add_argument("tape")
    args = ap.parse_args(argv)
    lm = prints_for(find_tape(args.tape))
    print(f"{len(lm)} landmarks")


if __name__ == "__main__":
    main()
