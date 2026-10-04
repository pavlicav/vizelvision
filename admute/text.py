"""Text evidence: what is being said, from Whisper's words (admute/speech.py).

Words come late (a chunk at a time, after transcription), so a second's text
features are recomputed as words arrive, until the detector freezes the second.
Each second is judged by the words spoken around it (WINDOW seconds either side),
never across a black seam, so a break's first seconds are not judged by the
programme's last words. With no words around a second, its features are NaN, and
the model treats them as neutral.

  lexicon   -- mean of each word's ad/show log-odds, from labelled recordings
               (the "text" section of model.json; fitted by admute.train)
  repeat    -- share of the words that repeat, word for word, something said at
               least REPEAT_GAP earlier: ads air again and again, talk does not
  show_vocab -- share of the content words that the programme itself used 1-45 min
               ago (seconds the detector settled as show): names, the game's words
  ad_vocab  -- share of the content words that only seconds settled as ads used
  you       -- second person ("you", "your") per word: ads talk to the viewer
  known_ad  -- share of the words in wording already known as an ad (AdLibrary): ads
               run for weeks, and on two Jeopardy nights 12-18% of one night's ad
               wording was in the other's ads, while none of the show's was
"""
from __future__ import annotations

import bisect
import collections
import json
import math
import os
import re
import threading
import time

WINDOW = 3.0
REPEAT_N = 4             # words in a shingle
REPEAT_GAP = 90.0        # a repeat must be at least this much older
MEMORY = 2700.0          # programme vocabulary: the last 45 min ...
MIN_VOCAB = 600          # ... once it has this many content words (about 10 min of talk): a
                         # young memory knows too few words, and low overlap would read as ads
LEX_CLIP = 3.0
NAMES = ("lexicon", "repeat", "show_vocab", "ad_vocab", "you", "known_ad")
KNOWN_MIN = 2            # a learnt shingle counts once heard in this many separate breaks
LIBRARY_MAX = 200_000
LIBRARY_DAYS = 60
YOU = {"you", "your", "you're", "yours", "yourself", "you'll", "you've"}
STOP = frozenset("""a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having
he her here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not
now of off on once only or other our ours ourselves out over own same she should so some such than that the their
theirs them themselves then there these they this those through to too under until up very was we were what when
where which while who whom why will with would yet you your yours yourself yourselves it's that's i'm we're they're
don't can't won't isn't there's he's she's let's oh yeah okay ok uh um gonna got get go going one two three""".split())

_CLEAN = re.compile(r"[^a-z0-9$%'&]")


def token(word: str) -> str | None:
    w = _CLEAN.sub("", word.lower().replace("’", "'")).strip("'")
    if not w:
        return None
    if "$" in w:
        return "<money>"
    if any(c.isdigit() for c in w):
        return "<num>"
    return w


def content(tok: str) -> bool:
    return tok not in STOP and len(tok) >= 3 and not tok.startswith("<")


def shingles(tokens) -> set:
    return {tuple(tokens[i:i + REPEAT_N]) for i in range(len(tokens) - REPEAT_N + 1)}


class AdLibrary:
    """Ad wording heard before, as REPEAT_N-word shingles: seeded from labelled
    recordings (model.json), and learnt live from confirmed breaks (kept in ``path``
    across restarts). A learnt shingle counts once it has been heard in KNOWN_MIN
    separate breaks, so one wrong call cannot teach it the programme's words."""

    def __init__(self, seed=(), path=None):
        self.seed = {tuple(s.split()) for s in seed}
        self.path = path
        self.learnt: dict[tuple, list] = {}     # shingle -> [breaks heard in, last heard (epoch)]
        self.dirty = False
        self.lock = threading.Lock()            # sessions learn on the ticker; housekeeping saves
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    self.learnt = {tuple(k.split()): v for k, v in json.load(f)["shingles"].items()}
            except (OSError, ValueError, KeyError):
                self.learnt = {}

    def known(self, sh: tuple) -> bool:
        return sh in self.seed or self.learnt.get(sh, (0,))[0] >= KNOWN_MIN

    def learn(self, heard: set, now: float | None = None) -> None:
        """The shingles of one confirmed break."""
        now = time.time() if now is None else now
        with self.lock:
            for sh in heard:
                entry = self.learnt.setdefault(sh, [0, now])
                entry[0] += 1
                entry[1] = now
            if len(self.learnt) > LIBRARY_MAX:
                for sh, _ in sorted(self.learnt.items(), key=lambda kv: kv[1][1])[: len(self.learnt) - LIBRARY_MAX]:
                    del self.learnt[sh]
            self.dirty = self.dirty or bool(heard)

    def save(self, now: float | None = None) -> None:
        if not self.path or not self.dirty:
            return
        now = time.time() if now is None else now
        with self.lock:
            keep = {" ".join(k): list(v) for k, v in self.learnt.items() if v[1] > now - LIBRARY_DAYS * 86400}
            self.dirty = False
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"shingles": keep}, f)
        os.replace(tmp, self.path)


class TextEvidence:
    def __init__(self, lexicon: dict | None = None, library: AdLibrary | None = None):
        self.lex = lexicon or {}
        self.library = library or AdLibrary()
        self.t: list[float] = []          # word mid-times, sorted
        self.tok: list[str] = []
        self.known = None                 # words are complete up to this input time
        self.shingles: dict[tuple, list[float]] = collections.defaultdict(list)
        self.vocab = {0: collections.Counter(), 1: collections.Counter()}   # by settled label
        self.vocab_q: collections.deque = collections.deque()             # (t, label, token)
        self.vocab_to = 0                 # seconds whose words are in the vocabularies

    # words ---------------------------------------------------------------------------
    def add(self, t0: float, t1: float, words) -> None:
        """One transcribed chunk [t0, t1): words [[start, end, text], ...]."""
        for start, end, text in words:
            tok = token(text)
            if tok is None:
                continue
            mid = (start + end) / 2
            i = bisect.bisect_right(self.t, mid)
            self.t.insert(i, mid)
            self.tok.insert(i, tok)
            # Shingles ending at this word (words arrive almost always in order).
            if i == len(self.t) - 1 and i + 1 >= REPEAT_N:
                self.shingles[tuple(self.tok[i - REPEAT_N + 1:i + 1])].append(mid)
        self.known = t1 if self.known is None else max(self.known, t1)

    def learn(self, upto: int, labels) -> None:
        """Add the words of seconds the detector has settled (labels[s] = 0 show, 1 ad)."""
        while self.vocab_to < upto:
            s = self.vocab_to
            lab = labels[s] if s < len(labels) else -1
            if lab in (0, 1):
                i, j = bisect.bisect_left(self.t, s), bisect.bisect_left(self.t, s + 1)
                for tok in self.tok[i:j]:
                    if content(tok):
                        self.vocab[lab][tok] += 1
                        self.vocab_q.append((s, lab, tok))
            self.vocab_to += 1
        while self.vocab_q and self.vocab_q[0][0] < upto - MEMORY:
            _, lab, tok = self.vocab_q.popleft()
            self.vocab[lab][tok] -= 1
            if self.vocab[lab][tok] <= 0:
                del self.vocab[lab][tok]

    # evidence --------------------------------------------------------------------------
    def window(self, s: int, blacks: list[float]) -> tuple[int, int]:
        lo, hi = s - WINDOW, s + 1 + WINDOW
        k = bisect.bisect_right(blacks, s + 0.5)
        if k:
            lo = max(lo, blacks[k - 1])
        if k < len(blacks):
            hi = min(hi, blacks[k])
        return bisect.bisect_left(self.t, lo), bisect.bisect_left(self.t, hi)

    def features(self, s: int, blacks: list[float]) -> dict:
        i, j = self.window(s, blacks)
        out = dict.fromkeys(NAMES, math.nan)
        if j <= i:
            return out
        toks = self.tok[i:j]
        out["lexicon"] = sum(max(-LEX_CLIP, min(LEX_CLIP, self.lex.get(t, 0.0))) for t in toks) / len(toks)
        out["you"] = sum(t in YOU for t in toks) / len(toks)
        # Repeats: a word is repeated if some shingle through it was heard REPEAT_GAP
        # before; known if some shingle through it is in the ad library.
        rep, known = [False] * (j - i), [False] * (j - i)
        for k in range(max(i, REPEAT_N - 1), j + REPEAT_N - 1):
            if k >= len(self.tok):
                break
            sh = tuple(self.tok[k - REPEAT_N + 1:k + 1])
            seen = self.shingles.get(sh)
            r, kn = bool(seen) and seen[0] < self.t[k] - REPEAT_GAP, self.library.known(sh)
            if r or kn:
                for m in range(k - REPEAT_N + 1, k + 1):
                    if i <= m < j:
                        rep[m - i] = rep[m - i] or r
                        known[m - i] = known[m - i] or kn
        if j - i >= REPEAT_N:
            out["repeat"] = sum(rep) / len(rep)
            out["known_ad"] = sum(known) / len(known)
        words = [t for t in toks if content(t)]
        show, ad = self.vocab[0], self.vocab[1]
        if words and sum(show.values()) >= MIN_VOCAB:
            out["show_vocab"] = sum(t in show for t in words) / len(words)
            out["ad_vocab"] = sum(t in ad and t not in show for t in words) / len(words)
        return out


def break_shingles(ev: TextEvidence, start: float, end: float, labels) -> set:
    """The shingles spoken in [start, end) within seconds settled as ad."""
    i, j = bisect.bisect_left(ev.t, start), bisect.bisect_left(ev.t, end)
    toks = [tok for t, tok in zip(ev.t[i:j], ev.tok[i:j]) if int(t) < len(labels) and labels[int(t)] == 1]
    return shingles(toks)
