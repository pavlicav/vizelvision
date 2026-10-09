"""Live ad-break detection: seams, per-second evidence, and a fixed-lag decision.

The offline stripper (~/scratch/ad_detection/rec_detect.py) labels a whole tape at
once. This is its causal form. Everything here uses only media that has arrived:

1. Seams: runs of black frames, hard cuts, and digital silence at a cut. Kept
   pending for a moment, so a black run can replace a nearby cut or silence seam
   (and a cut a silence one), then frozen. Black is the cheapest place for a break
   to begin, but not the only one: WJLA marks every programme<->break seam with
   black, while cable feeds (TBS on YouTube TV) often cut straight into an ad.

2. Per-second evidence, frozen once the second is complete:
   * bug       -- share of the station/score bug's outline present. The outline is
                  learnt from the last 15 min of edge maps (pixels that are edges
                  often, but not always, near the frame border). Unknown -> neutral.
   * cut_rate  -- hard cuts per second over the last 15 s
   * recurrence, colour -- how much this second looks like the *programme so
                  far*: past seconds labelled show, 3-45 min ago
   * ad_match  -- the best match among seconds already labelled ad (ads repeat)
   * txt_*     -- what is being said, from Whisper's words (admute/text.py). Words
                  arrive a few seconds late, so a second's text evidence is revised
                  as they come, and the second is frozen once its words are in (or
                  TEXT_HOLD after the edge, if transcription falls behind).
   * fp_*      -- audio fingerprints (admute/fingerprint.py): a known ad's sound, a
                  repeat of sound this broadcast already called an ad, known show sound.
                  Like words, they come a moment late and are revised until frozen.
   * ov_*      -- overlays (admute/overlays.py), up where they sit: a score bug or a
                  network/station logo argues for the programme, YouTube TV's ad label
                  ("Sponsored") for an ad. 1 while up, nothing otherwise: a break is
                  called once the programme's graphics have gone.
   These combine in a logistic model (``model.json``, from admute.train).

3. Decision: a two-state Viterbi over "cut points" -- seams, and every whole second.
   show -> ad switches only at a black seam or a hard cut; ad -> show switches at a
   seam or, at a price, at any second (so the sound can always come back). The forward pass runs
   incrementally over frozen evidence; each tick a short backward pass from the
   analysis edge gives the max-marginal P(ad) for the moment about to air.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from . import features as F
from . import fingerprint as FP
from . import overlays as OV
from . import text as T

BLACK_LUMA_MAX, BLACK_LUMA_MEAN = 45, 25
SILENCE_DB, SILENCE_DEEP_DB, SILENCE_CUT = -60.0, -70.0, 30.0
CUT_THRESH = 12.0
CUT_SEAM = 30.0           # a hard cut (step difference, a local peak) is a seam where a break may begin
SEAM_MERGE = 1.0          # seams closer than this are one seam (black wins, then a cut)
SEAM_RANK = {"black": 2, "cut": 1, "silence": 0}
SEAM_PENDING = 2.5        # seconds before the edge where seams and evidence freeze
MASK_WINDOW = 900.0       # bug outline learnt from this much history
MASK_EVERY = 10.0
MIN_OVERLAY_PIECE = 50   # pixels of outline (320x180) for a piece to count as an overlay
                         # (wide pieces count too: leaving them out on 10/5 cost TBS its game strip,
                         # and returns from breaks came late)
MEMORY = 2700.0           # programme memory: 45 min ...
FAR = 180.0               # ... but not the last 3 min
MIN_MEMORY = 120          # seconds of memory before recurrence says anything
FINAL_LAG = 60.0          # a second's label is settled (for the memories) this long after
BLACK_PER_HOUR = 6
RECENTER = 300            # seconds between re-centring the embedding memory
TEXT_HOLD = 10.0          # evidence waits at most this long behind the edge for its words
SCRIPT_MEMORY = 1800.0    # words kept this long, for the scripts of breaks learnt later
TEXT_FEATURES = tuple("txt_" + n for n in T.NAMES)
PRINT_FEATURES = ("fp_known", "fp_repeat", "fp_show")
OVERLAY_FEATURES = OV.FEATURES
# Per-second evidence served by the source: img_ picture scores (admute/clip.py, the new
# detector), and in the lab captions, sound and LLM answers.
EXTRA_PREFIXES = ("img_", "cc_", "aud_", "llm_")
CARRY = os.environ.get("ADMUTE_CARRY") == "1"       # lab: score pending llm_ seconds with the last answer
CARRY_SECONDS = 12
KNOWN_CLEAR = 0.18        # a known ad this clear may start a mute without a seam (re-airings match ~0.18-0.31)
BUG_AFTER = 6             # seconds after a moment in which the programme's score bug must be up for it to be the game

DEFAULT_MODEL = {
    "features": ["bug", "cut_rate", "recurrence", "colour", "ad_match"],
    "mean": [0.5, 1.5, -4.0, -2.5, 0.5],
    "scale": [0.3, 1.2, 1.5, 1.2, 0.2],
    "coef": [-1.5, 0.8, -1.5, -1.0, 0.0],
    "intercept": -0.5,
    # Cost of a switch, by direction and where it happens. Asymmetric on purpose:
    # going quiet needs a seam -- black, cheapest (WJLA marks every programme<->break
    # seam with it), or a hard cut (cable feeds often cut straight into an ad) --
    # while coming back is cheap anywhere.
    "show_ad": {"black": 4.0, "cut": 24.0, "silence": 200.0},
    "ad_show": {"black": 2.0, "cut": 8.0, "silence": 8.0, "second": 12.0},
    "cut_seam": CUT_SEAM,       # 0: hard cuts are not seams (before 2026-10-03)
    "start_ad": 10.0,           # a stream starts as show
}
MODEL_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model.json")


def load_model(path: str = MODEL_JSON) -> dict:
    model = dict(DEFAULT_MODEL)
    if os.path.exists(path):
        with open(path) as f:
            model.update(json.load(f))
    return model


@dataclass
class Seam:
    t: float
    kind: str              # 'black' | 'cut' | 'silence'


@dataclass
class Segment:
    start: float
    end: float
    p_ad: float
    seam: str | None       # the kind of seam at its start, if any
    post_z: float | None = None  # mean per-second ad logit from its start to the edge (what follows it)
    known: bool = False    # a known ad's sound, clearly (audio fingerprints)
    overlay: str | None = None   # a trusted score bug up as it begins (its name)
    ad_overlay: str | None = None   # a trusted ad label up as it begins (YouTube TV's "Sponsored")
    bug_after: bool | None = None   # a score bug seen in this programme is up within BUG_AFTER s of it (None: none seen)


class Grow:
    """A row array that grows by doubling (amortised appends)."""

    def __init__(self, width: int):
        self.buf = np.zeros((1024, width), np.float32)
        self.n = 0

    def extend(self, rows):
        if not len(rows):
            return
        while self.n + len(rows) > len(self.buf):
            self.buf = np.concatenate([self.buf, np.zeros_like(self.buf)])
        self.buf[self.n:self.n + len(rows)] = rows
        self.n += len(rows)

    @property
    def a(self) -> np.ndarray:
        return self.buf[: self.n]

    def __len__(self):
        return self.n


class ArraySource:
    """Signals already in memory (replay), served up to the replay clock. Transcribed
    chunks [(t0, t1, words)], if given, become known ``latency`` seconds after they end."""

    def __init__(self, sig: dict, chunks=None, latency: float = 1.5, prints=None, images=None):
        self.sig = sig
        self._chunks = list(chunks or [])
        self._ready = [t1 + latency for _, t1, _ in self._chunks]
        self._prints = None if prints is None else np.asarray(prints, np.float64).reshape(-1, 2)
        # Extra per-second evidence (img_, cc_, aud_, llm_ features): name -> values, or
        # name -> (values, known_at) for evidence that arrives after its second. Picture
        # scores the Signals kept (img_*, admute/clip.py) come with the signals.
        self._images = {**{k: v for k, v in sig.items() if k.startswith("img_")}, **(images or {})}

    def image(self, name: str, s: int, edge: float = math.inf) -> float:
        """An extra per-second score, if it is known by ``edge``."""
        v = self._images.get(name)
        if isinstance(v, tuple):
            v, ready = v
            if s < len(ready) and ready[s] > edge:
                return math.nan
        return float(v[s]) if v is not None and s < len(v) else math.nan

    def late_extras(self) -> bool:
        return any(isinstance(v, tuple) for v in self._images.values())

    def extras_pending(self, names, edge: float) -> float:
        """The first second whose late extra evidence is still on its way at ``edge`` (inf: none)."""
        first = math.inf
        for name in names:
            v = self._images.get(name)
            if isinstance(v, tuple):
                vals, ready = v
                k = np.flatnonzero(~np.isnan(vals) & (ready > edge) & (ready < math.inf))
                if len(k):
                    first = min(first, float(k[0]))
        return first

    def landmarks(self, i: int, edge: float):
        """Fingerprint landmarks known by the replay clock (FP.LATENCY after their time)."""
        if self._prints is None:
            return [], None
        j = int(np.searchsorted(self._prints[:, 0], edge - FP.LATENCY, "right"))
        return self._prints[i:max(i, j)].tolist(), edge - FP.LATENCY

    def chunks(self, i: int, edge: float):
        j = i
        while j < len(self._chunks) and self._ready[j] <= edge:
            j += 1
        return self._chunks[i:j]

    def frames(self, a: int, t_end: float):
        t = self.sig["frame_t"]
        b = int(np.searchsorted(t, t_end, "left"))
        return t[a:b], self.sig["frame_mean"][a:b], self.sig["frame_max"][a:b]

    def steps(self, kind: str, a: int, b: int):
        return self.sig[kind][a:b]

    def edge_maps(self, a: int, b: int):
        return self.sig["edges"][a:b]

    def seconds(self, a: int, b: int):
        return self.sig["emb"][a:b], self.sig["hist"][a:b]

    def pics(self, a: int, b: int):
        return self.sig["pic"][a:b] if "pic" in self.sig else []

    def available(self) -> float:
        s = self.sig
        return min(len(s["cut"]) / F.STEP_HZ, len(s["rms_db"]) / F.STEP_HZ, float(len(s["emb"])))


class Detector:
    def __init__(self, model: dict | None = None, start: float = 0.0, library: T.AdLibrary | None = None,
                 prints: FP.PrintDB | None = None, overlays: OV.Library | None = None, channel: str | None = None):
        self.m = model or load_model()
        self.start = start
        # consumed positions (absolute indices)
        self.n_frames = 0
        self.n_steps = 0
        self.n_edges = 0
        self.n_sec = 0
        # seams
        self.black_run = None                   # (start, last) of an open black run
        self.pending: list[Seam] = []
        self.seams: list[Seam] = []             # frozen
        self.next_silence_step = 5
        self.cut: list[float] = []
        self.rms: list[float] = []
        # bug outline
        self.edge_hist: list[np.ndarray] = []   # packed maps in the mask window
        self.edge_hist_t0 = 0                   # absolute index of edge_hist[0]
        self.edge_count = np.zeros((F.tap.H, F.tap.W), np.int32)
        self.mask = None
        self.mask_at = -1e9
        self.bug_scores: list[float] = []       # per edge map, with the mask of its time
        # per-second evidence
        self.image_features = tuple(k for k in self.m["features"] if k.startswith(EXTRA_PREFIXES))
        self.judge_off = False        # the transcript judge cannot be asked: score without it (weights())
        self.feats: dict[str, list[float]] = {k: [] for k in ("bug", "cut_rate", "recurrence", "colour", "ad_match")
                                              + TEXT_FEATURES + PRINT_FEATURES + OVERLAY_FEATURES + self.image_features}
        self.src = None
        # model.json "overlays": false switches overlays off (no evidence, no score-bug veto,
        # no ad label): nothing is matched or learnt.
        self.overlays = OV.Tracker(overlays if self.m.get("overlays", True) else OV.Library(catalogue=None), channel)
        if not self.m.get("overlays", True):
            self.overlays.next_learn = math.inf
        text = self.m.get("text") or {}
        if library is None:
            library = T.AdLibrary(text.get("ads") or ())
        else:
            library.seed |= {tuple(s.split()) for s in text.get("ads") or ()}
        self.text = T.TextEvidence(text.get("lexicon"), library)
        self.n_chunks = 0
        self.text_done = 0                      # seconds before this have their final text evidence
        self.heard: list[tuple] = []            # transcribed chunks (t0, t1, words), for scripts
        self.prints = FP.PrintEvidence(prints)
        self.prints.words = self.words_in
        self.learn_pods = True                  # store pod spots (the sidecar turns this off with learning)
        self.pod_meta = {}
        self.pod_log = []
        self.n_prints = 0
        self.fp_done = 0                        # ... and their final fingerprint evidence
        self.cutc: list[int] = []
        self.emb_raw = Grow(1000)
        self.cen = Grow(1000)                   # centred, unit-length embeddings
        self.hist = Grow(64)
        self.emb_sum = None
        self.label: list[int] = []              # settled label per second (-1 unknown)
        self.lp_ad: list[float] = []            # per-second log P(evidence | ad), show
        self.lp_show: list[float] = []
        self.cum_ad = [0.0]
        self.cum_show = [0.0]
        # forward Viterbi over frozen cut points
        self.cuts = [start]                     # cut point times; segment j = [cuts[j], cuts[j+1])
        self.cut_kind = ["start"]
        self.fwd: list[tuple[float, float]] = []  # (show, ad) best score of a path ending in segment j
        self.frozen_to = start
        self.edge_t = start
        self.settled = 0                        # next second to settle
        self.warm_from = math.inf               # first second whose recurrence could be measured

    # ------------------------------------------------------------- evidence
    def _consume(self, src, edge: float):
        t, mean, mx = src.frames(self.n_frames, edge)
        for ti, me, ma in zip(t, mean, mx):
            black = ma < BLACK_LUMA_MAX and me < BLACK_LUMA_MEAN
            if black:
                self.black_run = (self.black_run[0], ti) if self.black_run else (ti, ti)
            elif self.black_run:
                a, b = self.black_run
                self.black_run = None
                self._add_seam(Seam((a + b) / 2, "black"))
        self.n_frames += len(t)

        n = int(edge * F.STEP_HZ)
        self.cut.extend(src.steps("cut", self.n_steps, n).tolist())
        self.rms.extend(src.steps("rms_db", self.n_steps, n).tolist())
        self.n_steps = len(self.cut)
        cut_seam = float(self.m.get("cut_seam") or 0)
        while self.next_silence_step + 5 < min(len(self.cut), len(self.rms)):
            i = self.next_silence_step
            db = self.rms[i]
            if db == min(self.rms[i - 5:i + 6]) and (
                    db < SILENCE_DEEP_DB or (db < SILENCE_DB and max(self.cut[max(0, i - 3):i + 4]) > SILENCE_CUT)):
                self._add_seam(Seam(i / F.STEP_HZ, "silence"))
            c = self.cut[i]
            if cut_seam and c > cut_seam and c == max(self.cut[i - 3:i + 4]):
                self._add_seam(Seam(i / F.STEP_HZ, "cut"))
            self.next_silence_step += 1

        n = int(edge * F.EDGE_HZ)
        for packed in src.edge_maps(self.n_edges, n):
            t_map = self.n_edges / F.EDGE_HZ
            if t_map - self.mask_at >= MASK_EVERY:
                self._update_mask(t_map)
            emap = F.unpack(packed)
            self.edge_hist.append(packed)
            self.edge_count += emap
            while (self.edge_hist_t0 + 1) / F.EDGE_HZ < t_map - MASK_WINDOW:
                self.edge_count -= F.unpack(self.edge_hist.pop(0))
                self.edge_hist_t0 += 1
            if self.mask is None:
                self.bug_scores.append(math.nan)
            else:
                flat = emap.ravel()
                self.bug_scores.append(max(float(flat[idx].mean()) for idx in self.mask))
            self.overlays.see(emap, packed)
            self.n_edges += 1

        n = int(edge)
        emb, hist = src.seconds(self.n_sec, n)
        pics = src.pics(self.n_sec, self.n_sec + len(emb)) if hasattr(src, "pics") else []
        for k in range(len(emb)):
            self.overlays.see_pic(F.unpack_pic(pics[k]) if k < len(pics) else None)
        self.emb_raw.extend(emb)
        self.hist.extend(hist)
        self.n_sec += len(emb)

    def _add_seam(self, seam: Seam):
        near = [s for s in self.pending + self.seams[-1:] if abs(s.t - seam.t) < SEAM_MERGE]
        if not near:
            self.pending.append(seam)
            return
        for s in near:          # one seam: the stronger kind (black, then a cut) and its time
            if SEAM_RANK[seam.kind] > SEAM_RANK[s.kind] and s in self.pending:
                s.t, s.kind = seam.t, seam.kind
                return

    def _update_mask(self, t_map: float):
        self.mask_at = t_map
        n = len(self.edge_hist)
        if n < 120:                       # a minute of maps at least
            return
        freq = self.edge_count / n
        h, w = freq.shape
        border = np.zeros_like(freq, bool)
        border[: h // 4], border[-h // 4:] = True, True
        border[:, : w // 5], border[:, -w // 5:] = True, True
        logo = border & (freq > 0.35) & (freq < 0.97)
        pieces, n = ndimage.label(logo, structure=np.ones((3, 3)))
        # Overlays (score bug, network bug) are solid pieces; a 1-px line along the frame
        # edge is not. Each piece is judged on its own, so the network bug still counts
        # while the score bug is hidden (NBC drops it for booth and crowd shots).
        keep = []
        for i, sl in enumerate(ndimage.find_objects(pieces), 1):
            if sl is None:
                continue
            size = int((pieces[sl] == i).sum())
            if size >= MIN_OVERLAY_PIECE and sl[0].stop - sl[0].start >= 4 and sl[1].stop - sl[1].start >= 4:
                keep.append(np.flatnonzero((pieces == i).ravel()))
        self.mask = keep or None

    def _revise_overlays(self, s: int):
        """Second s's overlay evidence again, now the pictures after it are in (whether an
        overlay was up, not a flash, looks a picture ahead), unless it is frozen."""
        if not 0 <= s < len(self.lp_ad) or s < math.ceil(self.frozen_to):
            return
        changed = False
        for name, v in self.overlays.features(s).items():
            changed |= self._set(name, s, v)
        if changed:
            self.lp_ad[s], self.lp_show[s] = self._score(s)
            if s == len(self.lp_ad) - 1:
                self.cum_ad[s + 1] = self.cum_ad[s] + self.lp_ad[s]
                self.cum_show[s + 1] = self.cum_show[s] + self.lp_show[s]
            else:
                for k in range(s, len(self.lp_ad)):
                    self.cum_ad[k + 1] = self.cum_ad[k] + self.lp_ad[k]
                    self.cum_show[k + 1] = self.cum_show[k] + self.lp_show[k]

    def _second_features(self, s: int):
        self._revise_overlays(s - 1)
        bug = self.bug_scores[2 * s:2 * s + 2]
        bug = [b for b in bug if not math.isnan(b)]
        self.feats["bug"].append(float(np.mean(bug)) if bug else math.nan)
        self.cutc.append(int(sum(c > CUT_THRESH for c in self.cut[10 * s:10 * s + 10])))
        # Cut rate since the last black seam (at most 15 s): a break's fast cutting must
        # not spill into the programme after it.
        since = max([sm.t for sm in self.seams[-3:] + self.pending if sm.kind == "black" and sm.t <= s + 1] or [0.0])
        first = max(int(since), s - 14)
        self.feats["cut_rate"].append(float(np.mean(self.cutc[first:s + 1])))

        e = self.emb_raw.a[s]
        self.emb_sum = e.astype(np.float64) if self.emb_sum is None else self.emb_sum + e
        mu = (self.emb_sum / (s + 1)).astype(np.float32)
        x = e - mu
        x = x / (np.linalg.norm(x) + 1e-9)
        self.cen.extend(x[None])
        if s and s % RECENTER == 0:           # re-centre the memory on today's mean
            c = self.emb_raw.a[: s + 1] - mu
            self.cen.buf[: s + 1] = c / (np.linalg.norm(c, axis=1, keepdims=True) + 1e-9)
        cen, hist_all = self.cen.a, self.hist.a
        lo, hi = max(0, int(s - MEMORY)), max(0, int(s - FAR))
        rec = col = am = math.nan
        if hi > lo:
            show = np.array(self.label[lo:hi], np.int8) == 0
            n = int(show.sum())
            if n >= MIN_MEMORY:
                rec = math.log(float(((cen[lo:hi] @ x > 0.6) & show).sum()) / n + 0.002)
                col = math.log(float(((hist_all[lo:hi] @ hist_all[s] > 0.8) & show).sum()) / n + 0.002)
        h = max(0, s - 60)
        if h:
            ads = np.array(self.label[:h], np.int8) == 1
            if ads.any():
                am = float((cen[:h] @ x)[ads].max())
        self.feats["recurrence"].append(rec)
        if not math.isnan(rec):
            self.warm_from = min(self.warm_from, s)
        self.feats["colour"].append(col)
        self.feats["ad_match"].append(am)
        for name in TEXT_FEATURES + PRINT_FEATURES:
            self.feats[name].append(math.nan)       # filled in as the words and prints arrive
        for name, v in self.overlays.features(s).items():
            self.feats[name].append(v)
        for name in self.image_features:
            self.feats[name].append(self.src.image(name, s, self.edge_t) if hasattr(self.src, "image") else math.nan)
        self.label.append(-1)
        lp_ad, lp_show = self._score(s)
        self.lp_ad.append(lp_ad)
        self.lp_show.append(lp_show)
        self.cum_ad.append(self.cum_ad[-1] + lp_ad)
        self.cum_show.append(self.cum_show[-1] + lp_show)

    def weights(self, s: int) -> dict:
        """The weights deciding second s. While the transcript judge cannot be asked (no key,
        the day's budget spent, switched off: ``judge_off``), the model's own fit without it,
        since the judge took weight from the rest. Warm-up: until the programme memory exists
        (recurrence still unknown), weights fitted without the memory features, so the
        evidence that is there carries its full weight."""
        m = self.m
        if self.judge_off and m.get("nojudge"):
            m = m["nojudge"]
        if m.get("warm") and math.isnan(self.feats["recurrence"][s]):
            m = m["warm"]
        return m

    def _score(self, s: int) -> tuple[float, float]:
        m = self.weights(s)
        z = m["intercept"]
        for name, mean, scale, coef in zip(m["features"], m["mean"], m["scale"], m["coef"]):
            v = self.feats[name][s]
            if math.isnan(v) and CARRY and name.startswith("llm_"):
                v = self._carried(name, s)
            if not math.isnan(v) and scale:
                z += coef * (v - mean) / scale
        return -float(np.logaddexp(0, -z)), -float(np.logaddexp(0, z))

    def evidence(self, s: int) -> dict:
        """Second s's logit term by term, under the weights deciding it ("bias": the intercept)."""
        m = self.weights(s)
        out = {"bias": m["intercept"]}
        for name, mean, scale, coef in zip(m["features"], m["mean"], m["scale"], m["coef"]):
            v = self.feats[name][s] if s < len(self.feats[name]) else math.nan
            if not math.isnan(v) and scale:
                out[name] = coef * (v - mean) / scale
        return out

    def _carried(self, name: str, s: int) -> float:
        """While a late answer is on its way, the latest one from the seconds before (provisional:
        the second is scored again when its own answer arrives)."""
        vals = self.feats[name]
        for k in range(s - 1, max(-1, s - CARRY_SECONDS - 1), -1):
            if not math.isnan(vals[k]):
                return vals[k]
        return math.nan

    def _late(self, src, edge: float) -> None:
        """Evidence that arrives after its second (words, fingerprints): revise unfrozen
        seconds, then score them again."""
        changed = [f for f in (self._text(src, edge), self._prints(src, edge), self._extras(src, edge)) if f is not None]
        if changed:
            for k in range(min(changed), len(self.lp_ad)):
                self.lp_ad[k], self.lp_show[k] = self._score(k)
                self.cum_ad[k + 1] = self.cum_ad[k] + self.lp_ad[k]
                self.cum_show[k + 1] = self.cum_show[k] + self.lp_show[k]

    def _extras(self, src, edge: float):
        """Extra evidence that arrives late (llm_ scores): fill unfrozen seconds now known."""
        if not self.image_features or not getattr(src, "late_extras", lambda: False)():
            return None
        first = None
        for s in range(int(math.ceil(self.frozen_to)), len(self.lp_ad)):
            for name in self.image_features:
                if math.isnan(self.feats[name][s]) and self._set(name, s, src.image(name, s, edge)):
                    first = s if first is None else first
        return first

    def _set(self, name: str, s: int, v: float) -> bool:
        old = self.feats[name][s]
        if v == old or (math.isnan(v) and math.isnan(old)):
            return False
        self.feats[name][s] = v
        return True

    def _prints(self, src, edge: float):
        if not hasattr(src, "landmarks"):
            return None
        got, known = src.landmarks(self.n_prints, edge)
        self.n_prints += len(got)
        if known is None:
            return None
        before = self.prints.known
        self.prints.add(got, known)
        self.prints.learn(self.settled, self.label)
        if self.learn_pods:
            blacks = sorted(s.t for s in self.seams if s.kind == "black")
            got_pods = self.prints.pods(blacks, self.frozen_to - 1.0, self.pod_meta)
            if got_pods:
                self.pod_log.append(got_pods)
        first = None
        # Only seconds whose window just received landmarks can change.
        lo = max(self.fp_done, int(math.ceil(self.frozen_to)),
                 int((before or 0) - FP.WINDOW - 1) if before is not None else 0)
        blacks = sorted(sm.t for sm in self.seam_list() if sm.kind == "black")
        for s in range(lo, len(self.lp_ad)):
            for name, v in self.prints.features(s, blacks).items():
                if self._set("fp_" + name, s, v):
                    first = s if first is None else first
        self.fp_done = max(self.fp_done, min(len(self.lp_ad), int(self.prints.known - FP.WINDOW - 1)))
        # (an airing's words reach 2 s past its last matched second)
        self.prints.scribe(min(self.fp_done, self.text_done - 3) if self.text.known is not None else self.fp_done)
        return first

    def _text(self, src, edge: float):
        """Take in transcribed chunks and revise the text evidence of unfrozen seconds."""
        chunks = src.chunks(self.n_chunks, edge) if hasattr(src, "chunks") else []
        for t0, t1, words in chunks:
            self.text.add(t0, t1, words)
            self.heard.append((t0, t1, words))
        self.n_chunks += len(chunks)
        while self.heard and self.heard[0][1] < edge - SCRIPT_MEMORY:
            self.heard.pop(0)
        if self.text.known is None:
            return None
        self.text.learn(self.settled, self.label)
        blacks = sorted(sm.t for sm in self.seam_list() if sm.kind == "black")
        first = None
        for s in range(max(self.text_done, int(math.ceil(self.frozen_to))), len(self.lp_ad)):
            for name, v in self.text.features(s, blacks).items():
                if self._set("txt_" + name, s, v):
                    first = s if first is None else first
        # A second is final once its whole window has been transcribed.
        self.text_done = max(self.text_done, min(len(self.lp_ad), int(self.text.known - T.WINDOW - 1)))
        return first

    def words_in(self, a: float, b: float):
        """What was said in [a, b): [[start, word]], or None unless Whisper heard (almost)
        all of it -- a chunk dropped while it was behind says nothing about the words."""
        got, heard = [], 0.0
        for t0, t1, words in self.heard:
            if t1 <= a or t0 >= b:
                continue
            heard += min(t1, b) - max(t0, a)
            got += [[w[0], w[2]] for w in words if a <= (w[0] + w[1]) / 2 < b]
        return got if heard >= 0.9 * (b - a) else None

    def logit(self, s: int) -> float:
        return self.lp_ad[s] - self.lp_show[s]

    # ------------------------------------------------------------- decision
    def _integral(self, t: float, lab: int) -> float:
        """Evidence for ``lab`` from the start to time t (seconds without evidence: 0)."""
        cum = self.cum_ad if lab else self.cum_show
        k = int(t)
        n = len(cum) - 1
        if k >= n:
            return cum[n]
        vals = self.lp_ad if lab else self.lp_show
        return cum[k] + (t - k) * vals[k]

    def _seg(self, a: float, b: float, lab: int) -> float:
        return self._integral(b, lab) - self._integral(a, lab)

    def _uses_black(self, t: float) -> bool:
        hour = [s for s in self.seams if s.kind == "black" and s.t > t - 3600]
        span = min(3600.0, t - self.start)
        return len(hour) >= max(3, BLACK_PER_HOUR * span / 3600)

    def _cost(self, kind: str, frm: int, to: int, weak: float = 0.0) -> float:
        table = self.m["ad_show"] if frm == 1 else self.m["show_ad"]
        return table.get(kind, math.inf)

    def _cut_points(self, a: float, b: float, seams: list[Seam]):
        """Cut points in (a, b]: whole seconds and seams, sorted, seams winning ties."""
        pts = {float(k): "second" for k in range(int(math.floor(a)) + 1, int(math.floor(b)) + 1)}
        for s in seams:
            if a < s.t <= b:
                pts[s.t] = s.kind
        return sorted(pts.items())

    def _forward_step(self, prev, a, b, kind, weak):
        out = []
        for lab in (0, 1):
            stay = prev[lab]
            switch = prev[1 - lab] - self._cost(kind, 1 - lab, lab, weak)
            out.append(max(stay, switch) + self._seg(a, b, lab))
        top = max(out)
        return (out[0] - top, out[1] - top)

    def update(self, src, edge: float) -> None:
        """Take in media up to input time ``edge`` (the analysis edge)."""
        self.src = src
        self._consume(src, edge)
        self.edge_t = edge
        complete = min(int(edge), self.n_sec, len(self.cut) // 10, len(self.rms) // 10, len(self.bug_scores) // 2)
        while len(self.lp_ad) < complete:
            self._second_features(len(self.lp_ad))
        self._late(src, edge)
        self.overlays.learn(edge)
        freeze = min(edge - SEAM_PENDING, float(len(self.lp_ad)))
        waits = ([self.text_done] if self.text.known is not None else []) + \
                ([self.fp_done] if self.prints.known is not None else [])
        if self.image_features and getattr(src, "late_extras", lambda: False)():
            waits.append(src.extras_pending(self.image_features, edge))     # LLM answers still coming
        if waits:
            freeze = min(freeze, max(float(min(waits)), edge - TEXT_HOLD))
        keep = []
        for s in self.pending:
            (self.seams if s.t <= freeze else keep).append(s)
        self.pending = keep
        self.seams.sort(key=lambda s: s.t)
        if freeze <= self.frozen_to:
            return
        weak = 0.0
        for t, kind in self._cut_points(self.frozen_to, freeze, self.seams):
            a = self.cuts[-1]
            if not self.fwd:
                first = (self._seg(a, t, 0), self._seg(a, t, 1) - self.m["start_ad"])
                top = max(first)
                self.fwd.append((first[0] - top, first[1] - top))
            else:
                self.fwd.append(self._forward_step(self.fwd[-1], a, t, self.cut_kind[-1], weak))
            self.cuts.append(t)
            self.cut_kind.append(kind)
        self.frozen_to = self.cuts[-1]

    def decide(self, frm: float, to: float, settle: bool = True) -> list[Segment]:
        """P(ad) for each piece of (frm, to] (the stretch about to air), from all
        evidence up to the edge. Also settles the label of seconds FINAL_LAG old."""
        weak = 0.0
        # Tail: frozen cut points, then provisional ones up to the edge.
        tail_pts = self._cut_points(self.frozen_to, self.edge_t, self.pending)
        cuts = list(self.cuts) + [t for t, _ in tail_pts] + [self.edge_t]
        kinds = list(self.cut_kind) + [k for _, k in tail_pts]
        fwd = list(self.fwd)
        for j in range(len(fwd), len(cuts) - 1):
            a, b = cuts[j], cuts[j + 1]
            if j == 0:
                first = (self._seg(a, b, 0), self._seg(a, b, 1) - self.m["start_ad"])
                fwd.append((first[0] - max(first), first[1] - max(first)))
            else:
                fwd.append(self._forward_step(fwd[-1], a, b, kinds[j], weak))
        # Backward from the edge down to the earliest segment we need.
        lo_t = min(frm, self.edge_t - FINAL_LAG) if settle else frm
        j_lo = max(0, int(np.searchsorted(cuts, lo_t, "right")) - 1)
        bwd = {len(fwd) - 1: (0.0, 0.0)}
        for j in range(len(fwd) - 2, j_lo - 1, -1):
            nb = bwd[j + 1]
            a, b = cuts[j + 1], cuts[j + 2]
            kind = kinds[j + 1]
            vals = []
            for lab in (0, 1):
                stay = nb[lab] + self._seg(a, b, lab)
                switch = nb[1 - lab] + self._seg(a, b, 1 - lab) - self._cost(kind, lab, 1 - lab, weak)
                vals.append(max(stay, switch))
            top = max(vals)
            bwd[j] = (vals[0] - top, vals[1] - top)

        def p_ad(j):
            d = (fwd[j][1] + bwd[j][1]) - (fwd[j][0] + bwd[j][0])
            return 1 / (1 + math.exp(-max(-50.0, min(50.0, d))))

        if settle:
            s_final = min(int(self.edge_t - FINAL_LAG), len(self.label) - 1)
            for s in range(self.settled, s_final + 1):
                j = int(np.searchsorted(cuts, s + 0.5, "right")) - 1
                if j_lo <= j < len(fwd):
                    self.label[s] = int(p_ad(j) > 0.5)
                elif 0 <= j < len(fwd):               # older than this tick's backward pass
                    self.label[s] = int(fwd[j][1] > fwd[j][0])
                # A known ad's sound says "ad" without looking at the picture (a programme
                # overlay up then is not the programme's), known show sound "the programme"
                # (an ad label up then is no ad label): overlays.Tracker.settle.
                known, show = self.feats["fp_known"][s], self.feats["fp_show"][s]
                self.overlays.settle(s, self.label[s], clear_ad=known == known and known >= KNOWN_CLEAR,
                                     clear_show=show == show and show >= KNOWN_CLEAR,
                                     cut=max(self.cut[10 * s:10 * s + 10] or [0.0]) > CUT_SEAM)
            self.settled = max(self.settled, s_final + 1)
        out = []
        bug_here = self.overlays.score_here()
        j = max(0, int(np.searchsorted(cuts, frm, "right")) - 1)
        while j < len(fwd) and cuts[j] < to:
            a, b = max(cuts[j], frm), min(cuts[j + 1], to)
            if b > a:
                kind = kinds[j] if kinds[j] in SEAM_RANK and cuts[j] >= frm else None
                zs = [self.lp_ad[k] - self.lp_show[k] for k in range(int(math.ceil(a)), min(len(self.lp_ad), int(self.edge_t)))]
                post = float(np.mean(zs)) if zs else None
                known = self.known_ad(a)
                inside = int(a) < len(self.lp_ad)
                over = self.overlays.showing(int(a), "score") if inside else None
                label = self.overlays.showing(int(a), "ad") if inside else None
                back = (any(self.overlays.showing(k, "score") for k in range(int(a), min(int(a) + BUG_AFTER, len(self.lp_ad))))
                        if bug_here else None)
                out.append(Segment(a, b, p_ad(j), kind, post_z=post, known=known, overlay=over, ad_overlay=label,
                                   bug_after=back))
            j += 1
        return out

    def mark(self, side: str, a: float, b: float):
        """The operator says [a, b) is an ad (side 'ad': a programme overlay up then is not
        the programme's) or the programme ('show': an ad label up then is no ad label)."""
        self.overlays.mark(side, a, b)

    def known_ad(self, t: float, span: int = 3) -> bool:
        """A known ad's sound, clearly, over the seconds from t: a mute may start there without a seam."""
        vals = [v for v in self.feats["fp_known"][int(t):int(t) + span] if not math.isnan(v)]
        return len(vals) >= 2 and float(np.mean(vals)) >= KNOWN_CLEAR

    SPOT_NEED = {True: 2, False: 3}   # airings before a spot counts: wedged between ads, or at an edge

    def learn_break(self, start: float, end: float, span_id: str | None = None, src: str | None = None,
                    known: bool = False) -> dict:
        """A confirmed break's wording and sound, for the libraries (live: after a delay).
        The sound is learnt spot by spot (cut at black seams): a spot counts once heard in
        SPOT_NEED airings, so an ad is learnt even though breaks never repeat as a whole.
        ``known``: the break is certain some other way (MLB's feed): its spots count at once."""
        self.text.library.learn(T.break_shingles(self.text, start, end, self.label))
        blacks = sorted(s.t for s in self.seam_list() if s.kind == "black")
        clips = []
        for t, h, interior, (a, b) in self.prints.spots(start, end, blacks):
            meta = {"src": src or "break", "need": self.SPOT_NEED[interior],
                    **({"spans": [span_id]} if span_id else {})}
            if known:
                meta["seed"] = known if isinstance(known, str) else "certain"
            cid = self.prints.remember("ad", t, h, meta, a, b)
            if cid:
                clips.append(cid)
        return {"clip": clips[0] if clips else None, "clips": clips}

    def seam_list(self) -> list[Seam]:
        return self.seams + self.pending

    def trim(self, before: float):
        """Live: forget evidence not needed any more (bounded memory)."""
        # The memories need MEMORY of embeddings and ~3 h of ad seconds; the forward
        # pass needs nothing old. Kept simple for now: replay runs whole tapes.
        pass
