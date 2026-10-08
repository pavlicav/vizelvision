"""Overlays: the score bug, the network's logo, a station's bug -- and YouTube TV's ad label.

Over the programme a broadcast keeps a few graphics on screen: the score bug in a game
(TBS and NBC top left in MLB, FOX bottom right, NBC's NFL bottom centre, CBS's along the
top), the network's logo (NBC's peacock and FOX's bug top right) and sometimes the
station's bug (WJLA's abc7, bottom right). The detector's generic ``bug`` feature learns
"whatever stays put near the border" afresh each programme; overlays are specific, sit
where they belong, and are remembered. Some overlays mean the opposite: YouTube TV puts
its own ad player over the ads it inserts (a "Sponsored" pill top left, "Send to phone"
bottom right), and that is an ad for sure.

  template   in a box where the graphic sits, the pixels that are edges while it is up
             ("on") and the pixels by them that are not ("off"). A picture shows it when
             its on pixels are edges and its off pixels are not, within SLACK px of where
             it was learnt. Two kinds of picture (``space``):
               edge  the tap's 320x180 edge maps, twice a second (admute.features)
               pic   edges of the 224x224 colour picture, once a second: the page's
                     pictures (admute-frames) are made from it, so a template drawn from
                     them sees the same picture live (YouTube TV's ad label). Their JPEG
                     round trip softens it (live has ~30% more edges), but not where the
                     contrast is high: every JPEG edge on text is an edge live too, and a
                     label's on pixels are its text.
  catalogue  admute/overlays.json: learnt from labelled recordings (``python -m
             admute.overlays learn TAPE``) or from the page's pictures (``... frames``).
  live       admute-overlays.json beside the other state: a graphic that stays put in the
             programme (the detector's settled seconds of the last 15 min) but not in its
             breaks, learnt as it airs and kept for the next time. (Only programme
             overlays are learnt live: a wrongly learnt ad label would mute the programme.)

Not everything that stays put is a graphic: a programme's set (Jeopardy's podiums) is in
the same place in every shot from one camera. A graphic stays up across the programme's
hard cuts while the picture changes under it; the set goes with the shot. On the labelled
tapes the score bugs and network logos stayed up across 88-95% of the cuts they were up
before, Jeopardy's set pieces across 0-17%. So a live overlay must keep up across CUT_KEPT.

A graphic that stays put is not always the programme's:

  * a ticker keeps running through the breaks of a sports talk show. Anything spanning
    most of the frame's width is a band (tickers, crawls), never an overlay.
  * a station may leave its bug up over some ads: WJLA kept abc7 up over Jeopardy's
    national spots on 2026-10-05, and dropped it only for its local ones.
  * a network puts its logo on its own promos in a break: NBC's peacock was up for a 43 s
    promo in the 10/1 game's first break. So a network logo weighs less than a score bug.

So a live overlay counts only once it has been seen up in the programme and down in its
breaks, and any programme overlay seen up during clear ads -- a known ad's sound, or "it's
an ad" -- stops counting for the session; after STRIKES such sessions, for good. Mirrored,
an ad label seen up during clear programme -- known show sound, or "it's the show" -- stops
counting.

A programme's graphic is that channel's. Each overlay has a ``home``: the channels it has
proved itself on (learnt there, or the catalogue's). Elsewhere it starts out checking, and
counts only once it passes the same test as a new one on this channel; failing it there
says nothing about it at home (no strike, no rejection). On 2026-10-07 every overlay
counted on every channel: FS1's top-right score bug, up in none of TBS's game and 14% of
its ads, matched a ro ad's corner text, called it the programme (and barred the mute) for
29 s. ``channels`` (where it has been watched) had grown to every channel it was carried
to, so it could not tell.

The evidence (detector.Detector), per second, 1 while a trusted overlay is up and nothing
otherwise:
  ov_score  a score bug: the programme, strongly (and no mute may start: admute.policy)
  ov_logo   a network or station logo: the programme
  ov_ad     an ad label: an ad, strongly (a mute may start at once, without a seam)
Absence says nothing (replays and crowd shots drop the score bug), so a break is called
once the programme's graphics have gone.
"""
from __future__ import annotations

import argparse
import base64
import collections
import datetime
import glob
import json
import logging
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from . import features as F

log = logging.getLogger("admute.overlays")
W, H = F.tap.W, F.tap.H
PIC = F.tap.RGB_SIDE
SPACES = {"edge": (W, H), "pic": (PIC, PIC)}
SLACK = 2                 # px an overlay may sit off where it was learnt (scaling, cropping)
ON_FREQ = 0.55            # an "on" pixel is an edge in at least this share of the pictures it is up in
OFF_FREQ = 0.15           # an "off" pixel (away from the on ones) in at most this share
SEED_FREQ = 0.3           # a candidate's pixels are edges this often in the programme ...
AD_SHARE = 0.4            # ... and in its breaks at most this share of that
BAND = 0.75               # a piece this share of the frame's width or wider is a band: a ticker
MIN_ON = 25               # pixels of outline for an overlay (NBC's peacock is ~40)
MIN_H = 6                 # px tall at least: a line along the frame's edge is no overlay
MAX_AREA = 0.15 * W * H   # a box bigger than this is a picture, not an overlay
SCORE_AREA = 700          # a live overlay this big (px of box) is taken for a score bug, smaller for a logo
UP_MIN, UP_MAX = 0.3, 0.6  # bounds of a template's threshold (on minus off rate)
WINDOW = 900.0            # seconds of settled maps the live learner looks at
LEARN_EVERY = 60.0
MIN_SHOW_MAPS = 600       # settled programme maps (5 min) before anything is learnt live
MIN_AD_MAPS = 60          # settled break maps (30 s) before an overlay can be judged against breaks
PROMOTE_SHOW = 0.25       # a live overlay counts once up in this share of the programme ...
PROMOTE_AD = 0.03         # ... and at most this share of its breaks ...
CUT_MIN = 8               # ... and it was up before this many hard cuts ...
CUT_KEPT = 0.6            # ... and stayed up across this share of them (a set's piece goes with the shot)
REJECT_AD = 0.10          # up in more of the breaks than this: not the programme's (a ticker, a bug left on)
CLEAR_MIN = 20            # samples (pictures) of clear ads/programme before an overlay can lose trust ...
CLEAR_SHARE = 0.2         # ... when up in this share of them (and at least CLEAR_UP)
CLEAR_UP = 6
STRIKES = 2               # sessions an overlay lost trust in before it is rejected for good
LIVE_PER_CHANNEL = 8      # live overlays kept per channel (the least recently seen go)
REJECTED_PER_CHANNEL = 20  # rejected places remembered per channel (so they are not proposed again)
KINDS = ("score", "network", "channel", "logo", "ad")
FEATURES = ("ov_score", "ov_logo", "ov_ad")
CATALOGUE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "overlays.json")

_BORDER = np.zeros((H, W), bool)
_BORDER[: H // 4], _BORDER[-H // 4:] = True, True
_BORDER[:, : W // 5], _BORDER[:, -W // 5:] = True, True


def feature_for(kind: str) -> str:
    return {"score": "ov_score", "ad": "ov_ad"}.get(kind, "ov_logo")


pic_edges = F.pic_edges


def _pack(mask: np.ndarray) -> str:
    return base64.b64encode(np.packbits(mask.ravel()).tobytes()).decode()


def _unpack(text: str, shape) -> np.ndarray:
    bits = np.unpackbits(np.frombuffer(base64.b64decode(text), np.uint8))[: shape[0] * shape[1]]
    return bits.reshape(shape).astype(bool)


def crop(packed: np.ndarray, box) -> np.ndarray:
    """The box of packed edge maps [n, W*H/8] as bool [n, h, w], unpacking only its rows."""
    x0, y0, x1, y1 = box
    rows = packed.reshape(len(packed), H, W // 8)[:, y0:y1, x0 // 8:(x1 + 7) // 8]
    bits = np.unpackbits(rows, axis=-1)
    a = x0 - (x0 // 8) * 8
    return bits[:, :, a:a + (x1 - x0)].astype(bool)


def iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union else 0.0


def where(box, space: str = "edge") -> str:
    """'top left', 'bottom centre', ... for names."""
    w, h = SPACES[space]
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
    v = "top" if cy < 0.4 else "bottom" if cy > 0.6 else "middle"
    hz = "left" if cx < 0.35 else "right" if cx > 0.65 else "centre"
    return f"{v} {hz}"


@dataclass
class Overlay:
    id: str
    name: str
    kind: str                     # score | network | channel | logo (the programme's) | ad
    box: tuple                    # x0, y0, x1, y1 in its space
    on: np.ndarray                # bool [h, w]: edges while it is up
    off: np.ndarray               # bool [h, w]: no edges while it is up
    thresh: float = 0.45          # on rate minus off rate at which it is up ...
    strong: float | None = None   # ... if this is set: only next to a picture this clear (hysteresis)
    space: str = "edge"           # edge (320x180 maps, 2/s) | pic (224x224 picture, 1/s)
    origin: str = "catalogue"     # catalogue | live
    status: str = "active"        # active | pending (not yet seen against breaks) | rejected
    channels: list = field(default_factory=list)   # where it has been watched
    strikes: int = 0              # sessions it was seen up where it should not be
    home: list = field(default_factory=list)       # where it counts at once (proved itself); none: everywhere
    note: str = ""
    stats: dict = field(default_factory=dict)

    def __post_init__(self):
        self.box = tuple(int(v) for v in self.box)
        w, h = SPACES[self.space]
        x0, y0, x1, y1 = self.box
        ys, xs = np.nonzero(self.on)
        self._on = (ys + y0) * w + xs + x0
        ys, xs = np.nonzero(self.off)
        self._off = (ys + y0) * w + xs + x0
        self._shifts = np.array([dy * w + dx for dy in range(-SLACK, SLACK + 1) for dx in range(-SLACK, SLACK + 1)
                                 if 0 <= x0 + dx and x1 + dx <= w and 0 <= y0 + dy and y1 + dy <= h], np.int64)

    @property
    def feature(self) -> str:
        return feature_for(self.kind)

    @property
    def side(self) -> str:
        """Whose it is: 'show' (the programme's graphics) or 'ad' (an ad player's label)."""
        return "ad" if self.kind == "ad" else "show"

    def score(self, picture: np.ndarray) -> float:
        """How clearly it is up on one picture of its space (bool edges): on rate minus
        off rate, at the best of the shifts within SLACK."""
        flat = picture.ravel()
        on = flat[self._on[None, :] + self._shifts[:, None]].mean(1)
        if len(self._off):
            on = on - flat[self._off[None, :] + self._shifts[:, None]].mean(1)
        return float(on.max())

    def level(self, picture: np.ndarray) -> int:
        """0 down, 1 up, 2 up clearly (at ``strong``, or at the threshold without one)."""
        s = self.score(picture)
        return 0 if s < self.thresh else 2 if self.strong is None or s >= self.strong else 1

    def up(self, picture: np.ndarray) -> bool:
        return self.score(picture) >= self.thresh

    def scores(self, crops: np.ndarray) -> np.ndarray:
        """Scores of crops of its own box (no shifts): learning and checking."""
        on = crops[:, self.on].mean(1)
        return on - crops[:, self.off].mean(1) if self.off.any() else on

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "kind": self.kind, "box": list(self.box), "space": self.space,
                "on": _pack(self.on), "off": _pack(self.off), "thresh": round(float(self.thresh), 3),
                **({"strong": round(float(self.strong), 3)} if self.strong is not None else {}),
                "origin": self.origin, "status": self.status, "channels": list(self.channels),
                **({"home": list(self.home)} if self.home else {}),
                "strikes": self.strikes, "note": self.note, "stats": self.stats}

    @classmethod
    def from_json(cls, d: dict) -> "Overlay":
        x0, y0, x1, y1 = d["box"]
        shape = (y1 - y0, x1 - x0)
        return cls(id=d["id"], name=d.get("name") or d["id"], kind=d.get("kind", "logo"), box=tuple(d["box"]),
                   on=_unpack(d["on"], shape), off=_unpack(d["off"], shape), thresh=float(d.get("thresh", 0.45)),
                   strong=float(d["strong"]) if d.get("strong") is not None else None, space=d.get("space", "edge"), origin=d.get("origin", "catalogue"),
                   status=d.get("status", "active"), channels=list(d.get("channels") or []),
                   strikes=int(d.get("strikes", 0)), note=d.get("note", ""), stats=dict(d.get("stats") or {}),
                   home=list(d.get("home") or _home_of(d)))


def _slug(channel: str) -> str:
    return channel.lower().replace(" ", "")


def at_home(channel: str | None, home: list) -> bool:
    """Whether ``channel`` is one of ``home``: the same id, or a catalogue's call sign as a
    word of it (WTTG: wttg_dt_5_1 over the antenna; FOX: YouTube TV's FOX)."""
    if not channel or not home:
        return True
    words = set(re.split(r"[^a-z0-9]+", channel.lower()))
    return any(h == channel or _slug(h) == _slug(channel) or h.lower() in words for h in home)


def _home_of(d: dict) -> list:
    """Where an overlay saved before ``home`` proved itself: a live one, the channel in its
    id (it was learnt there); a catalogue one, its channels (the catalogue's own)."""
    channels = list(d.get("channels") or [])
    if d.get("origin") == "live":
        return [c for c in channels if d["id"].startswith(f"live-{_slug(c)}-")][:1]
    return channels


# ---------------------------------------------------------------- learning
def candidates(freq: np.ndarray, freq_ad: np.ndarray | None = None, n_ad: int = 0) -> list[tuple]:
    """Boxes where a programme overlay may sit on the edge maps: pixels near the frame's
    border that are edges often but not always in the programme, and (once enough
    breaks are known) much less often in its breaks. Bands (tickers), lines along the
    frame's edge and big pieces of picture are left out."""
    seed = _BORDER & (freq >= SEED_FREQ)
    if freq_ad is not None and n_ad >= MIN_AD_MAPS:
        seed &= freq_ad <= AD_SHARE * freq
    # A line along the frame (the picture's edge, a letterbox, a ticker's rule) would join
    # every overlay near it into one band: rows and columns it mostly fills go first.
    seed[seed.mean(1) >= BAND, :] = False
    seed[:, seed.mean(0) >= BAND] = False
    pieces, _ = ndimage.label(ndimage.binary_dilation(seed, iterations=2), structure=np.ones((3, 3)))
    out = []
    for sl in ndimage.find_objects(pieces):
        if sl is None:
            continue
        y0, y1, x0, x1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        w, h = x1 - x0, y1 - y0
        if w >= BAND * W or w < 4 or h < MIN_H or w * h > MAX_AREA or int(seed[sl].sum()) < MIN_ON:
            continue
        out.append((x0, y0, x1, y1))
    return out


def template(crops: np.ndarray, seed: np.ndarray, rounds: int = 3, min_up: int = 20):
    """(on, off, up) of the graphic in crops (bool [n, h, w]) starting from seed pixels:
    the pictures it is up in are found, and its on/off pixels re-learnt from those only
    (a score bug is hidden for replays; averaging those in would blur it). None if no
    clear, stable graphic is there."""
    on = seed
    up = None
    for _ in range(rounds):
        if on.sum() < MIN_ON:
            return None
        off = ~ndimage.binary_dilation(on, iterations=1)
        s = crops[:, on].mean(1) - (crops[:, off].mean(1) if off.any() else 0)
        hi = np.quantile(s, 0.9)
        if hi < UP_MIN:
            return None
        up = s >= max(UP_MIN, 0.5 * hi)
        if up.sum() < min_up:
            return None
        f = crops[up].mean(0)
        on = f >= ON_FREQ
        off = (f <= OFF_FREQ) & ~ndimage.binary_dilation(on, iterations=1)
    if on.sum() < MIN_ON:
        return None
    return on, off, up


def threshold(up_scores: np.ndarray, down_scores: np.ndarray | None = None) -> float:
    """Where 'up' begins: half the typical score while up, above (almost) every score
    of pictures it should be down in, if any are known."""
    t = 0.5 * float(np.median(up_scores)) if len(up_scores) else UP_MAX
    if down_scores is not None and len(down_scores):
        t = max(t, float(np.quantile(down_scores, 0.99)) + 0.05)
    return min(UP_MAX, max(UP_MIN, t))


def cut_maps(cut: np.ndarray, seam: float = 30.0) -> np.ndarray:
    """Map indices of hard cuts: steps (10/s) whose picture change is over ``seam`` and a
    local peak (as detector.CUT_SEAM)."""
    c = np.asarray(cut, np.float32)
    if len(c) < 7:
        return np.zeros(0, int)
    peak = ndimage.maximum_filter1d(c, 7) == c
    return np.unique(np.flatnonzero((c > seam) & peak) // F.EDGE_EVERY)


def kept(up: np.ndarray, cuts: np.ndarray) -> tuple[int, int]:
    """(cuts it was up before, of those it was still up after): before = the map ahead of
    the cut's, after = the map past it."""
    cuts = cuts[(cuts >= 1) & (cuts < len(up) - 1)]
    before = up[cuts - 1]
    return int(before.sum()), int((before & up[cuts + 1]).sum())


def learn(packed: np.ndarray, labels: np.ndarray, *, cut: np.ndarray | None = None) -> list[dict]:
    """Programme overlays of one labelled recording: packed edge maps [n, ...], a label
    per map (0 programme, 1 ad, -1 unknown) and the step picture change (``cut``, 10/s)
    if known. Returns [{overlay, show, ad, cuts}]: each one's up rate in the programme and
    in the ads, and (cuts it was up before, kept up across). Left out: any up in more than
    PROMOTE_AD of the ads, and (with ``cut``) any that goes with the shot."""
    sums = {0: np.zeros((H, W)), 1: np.zeros((H, W))}
    n = {0: 0, 1: 0}
    for i in range(0, len(packed), 1000):
        u = F.unpack(packed[i:i + 1000])
        for c in (0, 1):
            m = labels[i:i + 1000] == c
            if m.any():
                sums[c] += u[m].sum(0)
                n[c] += int(m.sum())
    if not n[0]:
        return []
    fs = sums[0] / n[0]
    fa = sums[1] / n[1] if n[1] else None
    out = []
    for box in candidates(fs, fa, n[1]):
        crops = crop(packed, box)
        x0, y0, x1, y1 = box
        got = template(crops[labels == 0], fs[y0:y1, x0:x1] >= SEED_FREQ)
        if got is None:
            continue
        on, off, up = got
        ov = Overlay(id="", name="", kind="logo", box=box, on=on, off=off)
        s = ov.scores(crops)
        ov.thresh = threshold(s[labels == 0][up], s[labels == 1])
        show = float((s[labels == 0] >= ov.thresh).mean())
        ad = float((s[labels == 1] >= ov.thresh).mean()) if n[1] else None
        if ad is not None and ad > PROMOTE_AD:
            log.info("%s: up in %.0f%% of the ads; not an overlay", where(box), 100 * ad)
            continue
        cuts = None
        if cut is not None:
            cuts = kept(s >= ov.thresh, cut_maps(cut))
            if cuts[0] >= CUT_MIN and cuts[1] < CUT_KEPT * cuts[0]:
                log.info("%s: stayed up across %d of %d cuts; part of the picture, not an overlay",
                         where(box), cuts[1], cuts[0])
                continue
        ov.kind = "score" if (x1 - x0) * (y1 - y0) >= SCORE_AREA else "logo"
        ov.stats = {"show": round(show, 3), "ad": None if ad is None else round(ad, 3),
                    **({"cuts": list(cuts)} if cuts else {})}
        out.append({"overlay": ov, "show": show, "ad": ad, "cuts": cuts})
    return out


def from_pictures(pictures: np.ndarray, box, kind: str) -> Overlay | None:
    """A "pic" overlay drawn from pictures it is known to be up in (bool edges [n, 224,
    224]): its on pixels are the ones that are edges in most of them, whatever is behind
    it. (YouTube TV's pill is a translucent grey: its outline is lost over a dark picture,
    its white "Sponsored" never is.)"""
    x0, y0, x1, y1 = box
    crops = pictures[:, y0:y1, x0:x1]
    f = crops.mean(0)
    on = f >= ON_FREQ
    if on.sum() < MIN_ON:
        return None
    off = (f <= OFF_FREQ) & ~ndimage.binary_dilation(on, iterations=1)
    ov = Overlay(id="", name="", kind=kind, box=box, on=on, off=off, space="pic")
    ov.thresh = threshold(ov.scores(crops))
    return ov


# ---------------------------------------------------------------- library
class Library:
    """The overlays: the catalogue (read-only, in the package) and what was learnt
    live or happened to catalogue entries (``path``: admute-overlays.json). Shared by
    every input's detector; saved by the sidecar's housekeeping."""

    def __init__(self, path: str | None = None, catalogue: str | None = CATALOGUE):
        self.path = path
        self.lock = threading.Lock()
        self.items: dict[str, Overlay] = {}
        self.dirty = False
        if catalogue and os.path.exists(catalogue):
            with open(catalogue) as f:
                for d in json.load(f).get("overlays", []):
                    ov = Overlay.from_json(d)
                    self.items[ov.id] = ov
        if path and os.path.exists(path):
            try:
                with open(path) as f:
                    saved = json.load(f).get("overlays", [])
            except (OSError, ValueError) as exc:
                log.warning("cannot read %s: %s", path, exc)
                saved = []
            for d in saved:
                if d.get("origin") == "live":
                    ov = Overlay.from_json(d)
                    self.items[ov.id] = ov
                elif d.get("id") in self.items:          # what happened to a catalogue entry
                    ov = self.items[d["id"]]
                    ov.status = d.get("status", ov.status)
                    ov.strikes = int(d.get("strikes", ov.strikes))
                    ov.note = d.get("note", ov.note)
                    ov.channels = list(d.get("channels") or ov.channels)
                    ov.home = list(dict.fromkeys(ov.home + list(d.get("home") or [])))
                    ov.stats = {**ov.stats, **(d.get("stats") or {})}

    def watched(self) -> list[Overlay]:
        with self.lock:
            return [ov for ov in self.items.values() if ov.status != "rejected"]

    def rejected(self) -> list[Overlay]:
        with self.lock:
            return [ov for ov in self.items.values() if ov.status == "rejected"]

    def add(self, ov: Overlay):
        with self.lock:
            self.items[ov.id] = ov
            if ov.origin == "live" and ov.status in ("active", "rejected"):
                mine = [o for o in self.items.values() if o.origin == "live" and o.status == ov.status
                        and set(o.channels) == set(ov.channels)]
                if ov.status == "active":
                    mine.sort(key=lambda o: o.stats.get("last", 0))
                keep = LIVE_PER_CHANNEL if ov.status == "active" else REJECTED_PER_CHANNEL
                for old in mine[:max(0, len(mine) - keep)]:
                    if old is not ov:
                        del self.items[old.id]
            self.dirty = True

    def update(self, oid: str, **changes):
        with self.lock:
            ov = self.items.get(oid)
            if ov is None:
                return
            for k, v in changes.items():
                if k == "stats":
                    ov.stats = {**ov.stats, **v}
                elif k == "channel":
                    if v and v not in ov.channels:
                        ov.channels.append(v)
                else:
                    setattr(ov, k, v)
            self.dirty = True

    def strike(self, oid: str, why: str) -> bool:
        """It was up where it should not be, for a session's worth: True if now rejected."""
        with self.lock:
            ov = self.items.get(oid)
            if ov is None:
                return False
            ov.strikes += 1
            ov.note = why
            if ov.strikes >= STRIKES:
                ov.status = "rejected"
            self.dirty = True
            return ov.status == "rejected"

    def save(self):
        if not self.path or not self.dirty:
            return
        with self.lock:
            out = [ov.to_json() if ov.origin == "live" else
                   {"id": ov.id, "origin": ov.origin, "status": ov.status, "strikes": ov.strikes,
                    "note": ov.note, "channels": ov.channels, "home": ov.home, "stats": ov.stats}
                   for ov in self.items.values()]
            self.dirty = False
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"version": 1, "overlays": out}, f)
        os.replace(tmp, self.path)

    def summary(self) -> dict:
        with self.lock:
            items = list(self.items.values())
        return {"active": sum(o.status == "active" for o in items), "pending": sum(o.status == "pending" for o in items),
                "rejected": sum(o.status == "rejected" for o in items),
                "live": sum(o.origin == "live" and o.status != "rejected" for o in items)}


# ---------------------------------------------------------------- per input
class Tracker:
    """Overlays on one input, for its detector: which are up, the evidence per second,
    the live learner, and the trust each overlay keeps.

    Samples are edge maps (2/s: map i at i / EDGE_HZ s, second s holds maps 2s and 2s+1)
    for "edge" overlays, and seconds for "pic" ones."""

    def __init__(self, library: Library | None = None, channel: str | None = None):
        self.lib = library if library is not None else Library()
        self.channel = channel
        self.watch: dict[str, Overlay] = {}
        self.up: dict[str, bytearray] = {}
        self.first: dict[str, int] = {}
        self.count: dict[str, dict] = {}
        self.trusted: set[str] = set()
        self.distrusted: dict[str, str] = {}
        self.foreign: set[str] = set()         # programme overlays from other channels, checking here
        self.game = True                       # a game is on (the session says): only then is a score bug one
        self.n = {"edge": 0, "pic": 0}           # samples seen, per space
        self.maps = collections.deque()          # (index, packed) in the learning window
        self.settled = collections.deque()       # (index, label, packed): settled maps in the window
        self.sums = {0: np.zeros((H, W), np.int32), 1: np.zeros((H, W), np.int32)}
        self.n_lab = {0: 0, 1: 0}
        self.clear = {"ad": [], "show": []}      # [(a, b)]: the operator said so
        self.next_learn = LEARN_EVERY
        self.events = collections.deque(maxlen=20)
        # Places rejected on this channel are not proposed again (a ticker's piece, a bug
        # left on in breaks); another channel may well have a real overlay there.
        self.rejected_boxes = [ov.box for ov in self.lib.rejected()
                               if ov.space == "edge" and (not ov.channels or channel in ov.channels)]
        for ov in self.lib.watched():
            if ov.side == "show" and not self._at_home(ov):
                self.foreign.add(ov.id)
            self._watch(ov, trusted=ov.status == "active" and ov.id not in self.foreign)

    def _at_home(self, ov: Overlay) -> bool:
        return at_home(self.channel, ov.home)

    def _watch(self, ov: Overlay, trusted: bool):
        self.watch[ov.id] = ov
        self.up[ov.id] = bytearray()
        self.first[ov.id] = self.n[ov.space]
        self.count[ov.id] = {"show": [0, 0], "ad": [0, 0], "clear": [0, 0], "cuts": [0, 0]}
        if trusted:
            self.trusted.add(ov.id)

    def _level(self, oid: str, i: int) -> int:
        k = i - self.first[oid]
        arr = self.up[oid]
        return arr[k] if 0 <= k < len(arr) else 0

    def _up(self, oid: str, i: int) -> bool:
        return self._level(oid, i) >= 1

    # ------------------------------------------------------------ input
    def see(self, edge_map: np.ndarray, packed: np.ndarray):
        """The next edge map (bool [H, W]) and its packed form."""
        for oid, ov in self.watch.items():
            if ov.space == "edge":
                self.up[oid].append(ov.level(edge_map))
        self.maps.append((self.n["edge"], packed))
        self.n["edge"] += 1
        while self.maps and self.maps[0][0] < self.n["edge"] - WINDOW * F.EDGE_HZ:
            self.maps.popleft()

    def see_pic(self, picture: np.ndarray | None):
        """The next second's picture edges (bool [224, 224], pic_edges), or None where
        there is none (a replay of cached signals): nothing is up then."""
        for oid, ov in self.watch.items():
            if ov.space == "pic":
                self.up[oid].append(0 if picture is None else ov.level(picture))
        self.n["pic"] += 1

    def mark(self, side: str, a: float, b: float):
        """The operator says [a, b) is an ad (side 'ad') or the programme ('show')."""
        self.clear[side].append((a, b))

    # ------------------------------------------------------------ evidence
    def up_in(self, oid: str, s: int) -> bool:
        """Up in second s, and not as a flash: an edge overlay on a map of the second and
        the map next to it, a pic overlay in the second and the one before or after. One
        with a ``strong`` level must also be clearly up in or by the second (hysteresis:
        on 10/5 TBS's own graphics in the same corner reached 0.43, the label 0.5 or more
        within a second of every pod's start)."""
        if self.watch[oid].space == "pic":
            return (self._up(oid, s) and (self._up(oid, s - 1) or self._up(oid, s + 1))
                    and any(self._level(oid, k) == 2 for k in (s - 2, s - 1, s, s + 1)))
        i, j = 2 * s, 2 * s + 1
        return (self._up(oid, i) and (self._up(oid, i - 1) or self._up(oid, j))) or \
               (self._up(oid, j) and (self._up(oid, i) or self._up(oid, j + 1)))

    def _counts(self, oid: str) -> bool:
        return oid in self.trusted and oid not in self.distrusted

    def _showing(self, s: int) -> dict:
        """{kind: name} of the trusted overlays up in second s. An ad label up with a
        programme score bug is not counted (the score bug wins: the sound stays). With no game
        on, a "score bug" is a station graphic (live overlays are called score bugs by size):
        it counts as a logo, and bars no mute. On 2026-10-08 a WJLA one, learnt from the noon
        news, matched a Zepbound ad's fine print on The View and held 11 s of it audible."""
        out = {}
        for oid in sorted(self.trusted):
            ov = self.watch[oid]
            kind = "logo" if ov.kind == "score" and not self.game else ov.kind
            if oid not in self.distrusted and kind not in out and self.up_in(oid, s):
                out[kind] = ov.name
        if "score" in out:
            out.pop("ad", None)
        return out

    def score_here(self) -> bool:
        """A trusted score bug has been up in a tenth of this programme's settled seconds:
        where it is down, this is not (yet) the game. (NBC's bug on TBS never is.)"""
        for oid in self.trusted:
            ov = self.watch[oid]
            n, up = self.count[oid]["show"]
            if ov.kind == "score" and oid not in self.distrusted and n >= 2 * MIN_AD_MAPS and up >= 0.1 * n:
                return True
        return False

    def features(self, s: int) -> dict:
        out = {name: math.nan for name in FEATURES}
        for kind in self._showing(s):
            out[feature_for(kind)] = 1.0
        return out

    def showing(self, s: int, kind: str | None = None) -> str | None:
        """The name of a trusted overlay (of ``kind``) up in second s, if any."""
        up = self._showing(s)
        return up.get(kind) if kind else next(iter(up.values()), None)

    # ------------------------------------------------------------ settling
    def settle(self, s: int, label: int, clear_ad: bool = False, clear_show: bool = False, cut: bool = False):
        """Second s settled as ``label`` (0 programme, 1 ad, -1 unknown). ``clear_ad`` /
        ``clear_show``: it is that by evidence that never looks at the picture (a known
        ad's sound, known show sound). ``cut``: a hard cut in it."""
        clear_ad = clear_ad or any(a <= s + 0.5 < b for a, b in self.clear["ad"])
        clear_show = clear_show or any(a <= s + 0.5 < b for a, b in self.clear["show"])
        first = self.maps[0][0] if self.maps else 0
        maps = {i: self.maps[i - first][1] for i in (2 * s, 2 * s + 1) if 0 <= i - first < len(self.maps)}
        for oid, ov in self.watch.items():
            samples = (2 * s, 2 * s + 1) if ov.space == "edge" else (s,)
            c = self.count[oid]
            for i in samples:
                if i < self.first[oid]:
                    continue
                up = self._up(oid, i) if ov.space == "edge" else self.up_in(oid, i)
                if label in (0, 1):
                    k = c["show" if label == 0 else "ad"]
                    k[0] += 1
                    k[1] += up
                if clear_ad if ov.side == "show" else clear_show:
                    c["clear"][0] += 1
                    c["clear"][1] += up
            if cut and label == 0:          # across the programme's cuts: before it, after it
                before, after = (2 * s - 1, 2 * s + 2) if ov.space == "edge" else (s - 1, s + 1)
                if before >= self.first[oid] and self._up(oid, before):
                    c["cuts"][0] += 1
                    c["cuts"][1] += self._up(oid, after)
        if label in (0, 1):
            for i, packed in maps.items():
                self.sums[label] += F.unpack(packed)
                self.n_lab[label] += 1
                self.settled.append((i, label, packed))
        while self.settled and self.settled[0][0] < self.n["edge"] - WINDOW * F.EDGE_HZ:
            i, lab, packed = self.settled.popleft()
            self.sums[lab] -= F.unpack(packed)
            self.n_lab[lab] -= 1
        for oid in list(self.watch):
            self._judge(oid)

    def _judge(self, oid: str):
        ov, c = self.watch[oid], self.count[oid]
        if self._counts(oid):
            n, up = c["clear"]
            if n >= CLEAR_MIN and up >= max(CLEAR_UP, CLEAR_SHARE * n):
                why = f"up during {up} of {n} pictures of clear {'ads' if ov.side == 'show' else 'programme'}"
                self.distrusted[oid] = why
                gone = self.lib.strike(oid, why)
                self.events.append({"t": time.time(), "what": "distrusted", "id": oid, "name": ov.name,
                                    "why": why, "rejected": gone})
                log.info("overlay %s (%s) no longer counts: %s%s", oid, ov.name, why, "; rejected" if gone else "")
            return
        if oid in self.trusted or oid in self.distrusted or ov.side != "show":
            return
        (ns, us), (na, ua), (nc, kc) = c["show"], c["ad"], c["cuts"]
        if oid in self.foreign:              # another channel's: the same test, its verdict only here
            if na >= MIN_AD_MAPS and ua > REJECT_AD * na:
                self.distrusted[oid] = f"not this channel's: up in {100 * ua / na:.0f}% of its breaks"
            elif nc >= CUT_MIN and kc < CUT_KEPT * nc:
                self.distrusted[oid] = f"not this channel's: went with the shot at {nc - kc} of {nc} cuts"
            elif (ns >= MIN_SHOW_MAPS and na >= MIN_AD_MAPS and nc >= CUT_MIN
                  and us >= PROMOTE_SHOW * ns and ua <= PROMOTE_AD * na):
                self._promote(oid, us / ns, ua / na)
            return
        if na >= MIN_AD_MAPS and ua > REJECT_AD * na:
            self._reject(oid, f"up in {100 * ua / na:.0f}% of breaks")
        elif nc >= CUT_MIN and kc < CUT_KEPT * nc:
            self._reject(oid, f"went with the shot at {nc - kc} of {nc} cuts")
        elif (ns >= MIN_SHOW_MAPS and na >= MIN_AD_MAPS and nc >= CUT_MIN
              and us >= PROMOTE_SHOW * ns and ua <= PROMOTE_AD * na):
            self._promote(oid, us / ns, ua / na)

    def _promote(self, oid, show, ad):
        ov = self.watch[oid]
        ov.status = "active"
        ov.stats = {**ov.stats, "show": round(show, 3), "ad": round(ad, 3), "last": round(time.time())}
        if self.channel and self.channel not in ov.channels:
            ov.channels.append(self.channel)
        if self.channel and self.channel not in ov.home:
            ov.home.append(self.channel)
        self.lib.add(ov)
        self.trusted.add(oid)
        self.events.append({"t": time.time(), "what": "learnt", "id": oid, "name": ov.name})
        log.info("overlay %s (%s) learnt: up in %.0f%% of the programme, %.1f%% of breaks",
                 oid, ov.name, 100 * show, 100 * ad)

    def _reject(self, oid, why):
        ov = self.watch.pop(oid)
        ov.status, ov.note = "rejected", why
        self.lib.add(ov)
        if ov.space == "edge":
            self.rejected_boxes.append(ov.box)
        self.events.append({"t": time.time(), "what": "rejected", "id": oid, "name": ov.name, "why": why})
        log.info("overlay %s (%s) is not the programme's: %s", oid, ov.name, why)

    # ------------------------------------------------------------ live learning
    def _explains(self, oid: str) -> bool:
        """An overlay already accounts for its place here: it is this channel's, or it has
        been up in a tenth of this programme. (NBC's MLB score bug sits where TBS's does;
        never matching on TBS, it must not stop TBS's from being learnt.)"""
        ov = self.watch[oid]
        if ov.space != "edge":
            return False
        if self.channel and ov.home and at_home(self.channel, ov.home):
            return True
        n, up = self.count[oid]["show"]
        return n >= MIN_AD_MAPS and up >= 0.1 * n

    def learn(self, t: float):
        """Every LEARN_EVERY s: graphics that stayed put in the programme's settled seconds
        of the last WINDOW, and are not overlays already, start being watched (pending)."""
        if t < self.next_learn:
            return
        self.next_learn = t + LEARN_EVERY
        if self.n_lab[0] < MIN_SHOW_MAPS:
            return
        fs = self.sums[0] / self.n_lab[0]
        fa = self.sums[1] / self.n_lab[1] if self.n_lab[1] else None
        known = [ov.box for oid, ov in self.watch.items() if self._explains(oid)] + self.rejected_boxes
        packed = lab = None
        for box in candidates(fs, fa, self.n_lab[1]):
            if any(iou(box, k) > 0.3 for k in known):
                continue
            if packed is None:
                items = list(self.settled)
                packed = np.array([p for _, _, p in items], np.uint8).reshape(len(items), -1)
                lab = np.array([y for _, y, _ in items])
            crops = crop(packed, box)
            x0, y0, x1, y1 = box
            got = template(crops[lab == 0], fs[y0:y1, x0:x1] >= SEED_FREQ)
            if got is None:
                continue
            on, off, up = got
            kind = "score" if (x1 - x0) * (y1 - y0) >= SCORE_AREA else "logo"
            chan = self.channel or "this channel"
            ov = Overlay(id=f"live-{(self.channel or 'x').lower().replace(' ', '')}-{x0}-{y0}-{int(time.time()) % 100000}",
                         name=f"{chan} · {where(box)} {'score bug' if kind == 'score' else 'logo'}", kind=kind,
                         box=box, on=on, off=off, origin="live", status="pending",
                         channels=[self.channel] if self.channel else [], home=[self.channel] if self.channel else [])
            s = ov.scores(crops)
            ov.thresh = threshold(s[lab == 0][up], s[lab == 1] if (lab == 1).sum() >= MIN_AD_MAPS else None)
            known.append(box)
            self._watch(ov, trusted=False)
            # What the window already says about it (its labels never heard of it). Cuts
            # are counted from now on.
            c = self.count[ov.id]
            c["show"] = [int((lab == 0).sum()), int((s[lab == 0] >= ov.thresh).sum())]
            c["ad"] = [int((lab == 1).sum()), int((s[lab == 1] >= ov.thresh).sum())]
            self.events.append({"t": time.time(), "what": "watching", "id": ov.id, "name": ov.name})
            log.info("overlay candidate %s at %s: up in %d of %d programme maps, %d of %d break maps",
                     ov.id, box, c["show"][1], c["show"][0], c["ad"][1], c["ad"][0])
            self._judge(ov.id)

    # ------------------------------------------------------------ page
    def describe(self, s: int) -> list[dict]:
        out = []
        for oid, ov in self.watch.items():
            c = self.count[oid]
            rate = lambda k: round(c[k][1] / c[k][0], 3) if c[k][0] else None   # noqa: E731
            out.append({"id": oid, "name": ov.name, "kind": ov.kind, "origin": ov.origin,
                        "state": "ignored" if oid in self.distrusted else "counts" if oid in self.trusted else "checking",
                        "up": self.up_in(oid, s) if s >= 0 else False, "show": rate("show"), "ad": rate("ad"),
                        "why": self.distrusted.get(oid)})
        out.sort(key=lambda o: (not o["up"], o["state"] != "counts", o["name"]))
        return out

    def flush(self):
        """Per-session numbers into the library (the page shows them; live overlays age out by them)."""
        for oid in self.trusted:
            c = self.count[oid]
            if c["show"][0] or c["ad"][0]:
                self.lib.update(oid, stats={"show": round(c["show"][1] / c["show"][0], 3) if c["show"][0] else None,
                                            "ad": round(c["ad"][1] / c["ad"][0], 3) if c["ad"][0] else None,
                                            "last": round(time.time())}, channel=self.channel)


# ---------------------------------------------------------------- tools
def _labels_per_map(truth: dict, n: int) -> np.ndarray:
    lab = np.full(n, -1, np.int8)
    for a, b, l in truth["spans"]:
        lab[int(a * F.EDGE_HZ):int(b * F.EDGE_HZ)] = {"ad": 1, "show": 0}.get(l, -1)
    return lab


def _tape(name: str, decode: bool):
    from . import replay
    path = replay.find_tape(name)
    if not decode and not os.path.exists(replay.cache_path(path)):
        sys.exit(f"{os.path.basename(path)}: no cached signals (python -m admute.replay extract, off air)")
    sig = replay.extract(path)
    truth = next((t for _, t in replay.load_truths() if os.path.basename(t["file"]) == os.path.basename(path)), None)
    return path, sig, truth


def _page_pictures(folder: str, a: int | None = None, b: int | None = None):
    """[(wall second, path)] of the page's pictures of one input (admute-frames/<key>)."""
    out = []
    for p in glob.glob(os.path.join(folder, "*.jpg")):
        stem = os.path.basename(p).split(".")[0]
        if stem.isdigit() and (a is None or a <= int(stem) <= b):
            out.append((int(stem), p))
    return sorted(out)


def _picture(path: str) -> np.ndarray:
    """A page picture (256x144 JPEG of the tap's 224x224 picture) back in the pic space."""
    from PIL import Image
    return pic_edges(np.asarray(Image.open(path).convert("RGB").resize((PIC, PIC), Image.BILINEAR)))


def _when(text: str) -> int:
    return int(datetime.datetime.fromisoformat(text).timestamp())


def main(argv=None):
    ap = argparse.ArgumentParser(prog="admute.overlays")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("learn", help="find the programme overlays of recordings (cached signals)")
    p.add_argument("tapes", nargs="+")
    p.add_argument("--prefix", required=True, help="id prefix, e.g. nbc-mlb")
    p.add_argument("--channel", action="append", default=[], help="channels it airs on (repeat)")
    p.add_argument("--write", action="store_true", help=f"add them to {os.path.basename(CATALOGUE)}")
    p.add_argument("--decode", action="store_true", help="decode a tape that is not cached (heavy: off air only)")
    p.add_argument("--unlabelled", action="store_true",
                   help="no truth: everything is taken for the programme, and they wait (pending) to be "
                        "seen against breaks live")
    p = sub.add_parser("frames", help="draw a pic overlay from the page's pictures of one input")
    p.add_argument("folder", nargs="+", help="admute-frames/<input key> (the spans are looked for in each)")
    p.add_argument("--up", action="append", required=True, metavar="FROM/TO",
                   help="a span it is up in throughout, ISO local times (repeat)")
    p.add_argument("--box", required=True, help="x0,y0,x1,y1 on the 224x224 picture")
    p.add_argument("--id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--kind", choices=KINDS, required=True)
    p.add_argument("--channel", action="append", default=[])
    p.add_argument("--strong", type=float, help="the clear level (hysteresis), above the programme's best score there")
    p.add_argument("--check", action="append", default=[], help="folders of pictures to look for it in (repeat)")
    p.add_argument("--write", action="store_true")
    p = sub.add_parser("check", help="up rates of the catalogue's edge overlays in a labelled recording")
    p.add_argument("tapes", nargs="+")
    p.add_argument("--decode", action="store_true")
    p = sub.add_parser("name", help="name a catalogue overlay")
    p.add_argument("id")
    p.add_argument("name")
    p.add_argument("--kind", choices=KINDS)
    p = sub.add_parser("picture", help="draw the catalogue's templates (PNG)")
    p.add_argument("out")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    def load():
        if not os.path.exists(CATALOGUE):
            return {"version": 1, "overlays": []}
        with open(CATALOGUE) as f:
            return json.load(f)

    def store(cat):
        with open(CATALOGUE, "w") as f:
            json.dump(cat, f, indent=1)
        print("wrote", CATALOGUE)

    if args.cmd == "learn":
        cat = load()
        n = 0
        for name in args.tapes:
            path, sig, truth = _tape(name, args.decode)
            maps = sig["edges"]
            if truth is None and not args.unlabelled:
                sys.exit(f"{os.path.basename(path)}: no truth file (or pass --unlabelled)")
            lab = np.zeros(len(maps), np.int8) if truth is None else _labels_per_map(truth, len(maps))
            for got in learn(maps, lab, cut=sig.get("cut")):
                ov = got["overlay"]
                n += 1
                ov.id = f"{args.prefix}-{ov.kind}-{where(ov.box).replace(' ', '-')}"
                ov.name = f"{args.prefix} {where(ov.box)} {'score bug' if ov.kind == 'score' else 'logo'}"
                ov.channels = list(args.channel)
                ov.status = "pending" if truth is None else "active"
                ov.stats = {**ov.stats, "learnt_from": os.path.basename(path)}
                print(f"{ov.id:40s} box {ov.box}  on {int(ov.on.sum()):4d} off {int(ov.off.sum()):4d}  "
                      f"thresh {ov.thresh:.2f}  up: programme {got['show']:.1%}"
                      + (f", ads {got['ad']:.2%}" if got["ad"] is not None else "")
                      + (f", across cuts {got['cuts'][1]}/{got['cuts'][0]}" if got["cuts"] else ""))
                cat["overlays"] = [d for d in cat["overlays"] if d["id"] != ov.id] + [ov.to_json()]
        if args.write and n:
            store(cat)
    elif args.cmd == "frames":
        spans = [tuple(_when(x) for x in s.split("/")) for s in args.up]
        pics = [(t, p) for folder in args.folder for a, b in spans for t, p in _page_pictures(folder, a, b)]
        if len(pics) < 20:
            sys.exit(f"only {len(pics)} pictures in those spans")
        ov = from_pictures(np.array([_picture(p) for _, p in pics]), tuple(int(v) for v in args.box.split(",")),
                           args.kind)
        if ov is None:
            sys.exit("no clear graphic in that box")
        ov.id, ov.name, ov.channels, ov.strong = args.id, args.name, list(args.channel), args.strong
        ov.stats = {"learnt_from": f"{len(pics)} page pictures"}
        print(f"{ov.id}: box {ov.box} on {int(ov.on.sum())} off {int(ov.off.sum())} thresh {ov.thresh:.2f}"
              + (f" strong {ov.strong:.2f}" if ov.strong else ""))
        for folder in args.check:
            got = _page_pictures(folder)
            tr = Tracker(Library(catalogue=None))
            tr._watch(ov, trusted=True)
            for _, p in got:
                tr.see_pic(_picture(p))
            hits = [t for k, (t, p) in enumerate(got) if tr.up_in(ov.id, k)]
            inside = [t for t in hits if any(a <= t <= b for a, b in spans)]
            print(f"  {folder}: up in {len(hits)} of {len(got)} pictures ({len(inside)} in the given spans)")
            runs = []
            for t in hits:
                if runs and t - runs[-1][1] <= 2:
                    runs[-1][1] = t
                else:
                    runs.append([t, t])
            for a, b in runs[:40]:
                print("    ", datetime.datetime.fromtimestamp(a).strftime("%H:%M:%S"), f"{b - a + 1:4d} s")
        if args.write:
            cat = load()
            cat["overlays"] = [d for d in cat["overlays"] if d["id"] != ov.id] + [ov.to_json()]
            store(cat)
    elif args.cmd == "check":
        lib = Library(catalogue=CATALOGUE)
        for name in args.tapes:
            path, sig, truth = _tape(name, args.decode)
            maps = sig["edges"]
            lab = np.zeros(len(maps), np.int8) if truth is None else _labels_per_map(truth, len(maps))
            print(os.path.basename(path))
            for ov in lib.watched():
                if ov.space != "edge":
                    continue
                up = np.zeros(len(maps), bool)
                for i in range(0, len(maps), 1000):
                    u = F.unpack(maps[i:i + 1000])
                    up[i:i + len(u)] = [ov.up(m) for m in u]
                show = up[lab == 0].mean() if (lab == 0).any() else math.nan
                ad = up[lab == 1].mean() if (lab == 1).any() else math.nan
                print(f"  {ov.id:40s} programme {show:6.1%}  ads {ad:6.2%}")
    elif args.cmd == "name":
        cat = load()
        for d in cat["overlays"]:
            if d["id"] == args.id:
                d["name"] = args.name
                if args.kind:
                    d["kind"] = args.kind
                store(cat)
                return
        sys.exit(f"no overlay {args.id}")
    elif args.cmd == "picture":
        from PIL import Image, ImageDraw
        items = Library(catalogue=CATALOGUE).watched()
        tile_w, tile_h = W * 3 // 2, H * 3 // 2 + 16
        img = Image.new("RGB", (tile_w * 2, tile_h * max(1, (len(items) + 1) // 2)), "black")
        draw = ImageDraw.Draw(img)
        for k, ov in enumerate(items):
            w, h = SPACES[ov.space]
            pic = np.zeros((h, w, 3), np.uint8)
            x0, y0, x1, y1 = ov.box
            pic[y0:y1, x0:x1][ov.on] = (255, 255, 255)
            pic[y0:y1, x0:x1][ov.off] = (40, 70, 160)
            ox, oy = (k % 2) * tile_w, (k // 2) * tile_h
            sx, sy = (tile_w - 4) / w, (tile_h - 16) / h
            img.paste(Image.fromarray(pic).resize((tile_w - 4, tile_h - 16), Image.NEAREST), (ox, oy))
            draw.rectangle([ox + x0 * sx, oy + y0 * sy, ox + x1 * sx, oy + y1 * sy], outline=(255, 200, 0))
            draw.text((ox + 4, oy + tile_h - 14), f"{ov.id} ({ov.kind}, {ov.space}, {ov.status})", fill=(255, 255, 0))
        img.save(args.out)
        print("wrote", args.out)


if __name__ == "__main__":
    main()
