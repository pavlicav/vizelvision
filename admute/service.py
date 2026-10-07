"""The ad-mute sidecar: live detection for the master worker.

  python -m admute.service --config config.master.json

Listens on admute.sock beside the master socket. The worker streams each analysed
input's tap (roku_stream/admute_protocol.py); per input, the same Signals ->
Detector -> Policy chain that admute.replay scores runs every TICK seconds and
answers with a gain schedule, a lease and the AD badge. It also:

  * transcribes each analysed input with Whisper (Speech: a lane per input, overlapping
    windows), so what is being said counts as evidence (admute/text.py); the words also
    go to master, whose live captions use them instead of transcribing again
  * fingerprints each analysed input's sound against a database of known ads (and of
    show sound that repeats), which confirmed breaks keep teaching (admute/fingerprint.py);
    each ad keeps its script (the words said over it) and a few pictures (admute-ads/),
    for the Ad database page
  * watches for the programme's overlays -- score bugs, network and station logos -- from
    the catalogue and as learnt live, kept per channel in admute-overlays.json
    (admute/overlays.py)
  * looks as far ahead as the programme delay allows: with live captions on, master
    holds the programme 6 s, not lookahead + 1 (docs/live-captions.md)

  * reads admute.json (the web app's settings) every second, including which detector
    runs: classic, or new (classic plus a CLIP picture score and warm-up weights,
    admute/model_new.json); a change starts each input's analysis over
  * asks the web app's queue what is airing: its title (exceptions) and, for a
    game, the gamePk (the MLB sports gate)
  * appends operator corrections to admute-labels.jsonl (training data)
  * writes admute-state.json for the Ad mute page (status, breaks, timeline), and
    a small picture per second (admute/frames.py) so the page can show what a fix
    or a review mark is about

Nothing here can make the programme quieter on its own: the worker only follows a
schedule while its lease runs, and only in mode 'on'.
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import math
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from roku_stream import admute_protocol as proto  # noqa: E402
from roku_stream.admute_settings import AdMuteSettings, paused  # noqa: E402
from roku_stream.caption_settings import CaptionSettings  # noqa: E402
from roku_stream.captions import LOOKAHEAD_SECONDS as CAPTION_DELAY  # noqa: E402

from . import clip, detector as D, features, fingerprint as FP, overlays as OV, speech as W, sports, text as T  # noqa: E402
from .frames import FrameStore  # noqa: E402
from .policy import Policy, PolicyConfig  # noqa: E402

log = logging.getLogger("admute")
TICK = 0.5
LEASE_AHEAD = 1.0          # seconds of schedule the worker may follow past the decision horizon
FADE_DOWN, FADE_UP = 150_000_000, 250_000_000
SECOND = 1_000_000_000
QUEUE_EVERY = 15.0
STATE_EVERY = 1.0
TIMELINE = 3600            # seconds of P(ad) kept for the page
DRIFT = 0.001              # the wall-clock mapping may creep later by this much per second
MARGIN = 1.0               # seconds between a decision and its audio leaving master's delay (admute_link.MARGIN)
SPEECH_BACKLOG = 2         # windows waiting for Whisper per input; older ones are dropped (their seconds freeze soon)
SPEECH_WORKERS = 2         # inputs transcribed at once (one model; bigger models: one at a time, for memory)
SPEECH_THREADS = 1         # threads per transcription. 2 bought nothing on 10/4 (3.0 s a window either way:
                           # the box is saturated) and leaned on master's hyperthreads
SPEECH_RETRY = 600.0       # a model that would not load is tried again after this long
LEARN_AFTER = 600.0        # a break's wording joins the ad library this long after it ends (time to mark it)
JUMP_BACK, JUMP_AHEAD = SECOND // 2, 10 * SECOND   # a frame this far off its kind's timeline is off it
NEW_TIMELINE = 3.0         # seconds a source must stay off its timeline before analysis starts over
FAILURES = 5               # consecutive failed ticks before an input's analysis starts over
GAME_EVERY = 60.0          # how often a game's completed breaks are looked for in its feed
USE_CAPTION_DELAY = True   # look as far ahead as live captions' 6 s programme delay allows
BEHIND_WARN = 1.5          # seconds the analysis may trail the media received before mutes land late
RESUME_WITHIN = 120.0      # an input analysed this recently before a restart is resumed: no take grace
PICTURES = (0.15, 0.4, 0.65, 0.9)   # where in an ad its pictures are taken (admute-ads/<clip>-<i>.jpg)
NEW_MODEL_JSON = ROOT / "admute" / "model_new.json"   # the new detector's weights (lab.prod_model)


class Source:
    """Signals (live, trimmed) as the detector's source: absolute indices. Speech is
    the session's transcribed chunks, in order, appended by the Speech thread."""

    def __init__(self, sig: features.Signals, speech: list, session=None):
        self.sig = sig
        self.speech = speech
        self.session = session

    def chunks(self, i, edge):
        return self.speech[i:]

    def landmarks(self, i, edge):
        s = self.session
        return s.landmarks[i:], s.print_known

    def frames(self, a, t_end):
        s = self.sig
        with s.lock:
            i0 = max(0, a - s.frames_since)
            t = np.array(s.frame_t[i0:])
            keep = int(np.searchsorted(t, t_end, "left"))
            return (t[:keep], np.array(s.frame_mean[i0:i0 + keep], np.float32),
                    np.array(s.frame_max[i0:i0 + keep], np.float32))

    def steps(self, kind, a, b):
        s = self.sig
        with s.lock:
            arr, since = (s.cut, s.steps_since) if kind == "cut" else (s.rms_db, s.audio_since)
            return np.array(arr[max(0, a - since):max(0, b - since)], np.float32)

    def edge_maps(self, a, b):
        s = self.sig
        with s.lock:
            maps = s.edge_maps[max(0, a - s.edges_since):max(0, b - s.edges_since)]
            if not maps:          # nothing new this tick (numpy cannot reshape an empty list)
                return np.zeros((0, 0), np.uint8)
            return np.array(maps, np.uint8).reshape(len(maps), -1)

    def image(self, name, s, edge=math.inf):
        """A picture score (admute/clip.py) of second s, or NaN where none was scored."""
        sig = self.sig
        with sig.lock:
            vals, i = sig.img.get(name), s - sig.seconds_since
            return float(vals[i]) if vals is not None and 0 <= i < len(vals) else math.nan

    def seconds(self, a, b):
        s = self.sig
        with s.lock:
            i, j = max(0, a - s.seconds_since), max(0, b - s.seconds_since)
            return (np.array(s.emb[i:j], np.float32).reshape(-1, 1000) if j > i else np.zeros((0, 1000), np.float32),
                    np.array(s.hist[i:j], np.float32).reshape(-1, 64) if j > i else np.zeros((0, 64), np.float32))

    def pics(self, a, b):
        s = self.sig
        with s.lock:
            return list(s.pics[max(0, a - s.seconds_since):max(0, b - s.seconds_since)])


class Session:
    """Detection for one input."""

    def __init__(self, service, key, info):
        self.service, self.key, self.info = service, key, info
        self.lookahead = float(info.get("lookahead", 3.0))
        self.lock = threading.Lock()
        self.ack = 0
        self.gen = 0
        self.game_learnt = set()     # breaks of this game learnt from MLB's feed (by start)
        self.game_lag = None         # how far the broadcast runs behind the feed
        self.game_next = 0.0
        self.game_stats = {"breaks": 0, "new": 0}
        self.off_since = None        # monotonic time frames started arriving off the timeline
        self.off_count = 0
        self.failures = 0
        self.title = info.get("title")
        self.game = None
        self.gate = None
        self.started = time.time()
        self._reset()
        resumed = getattr(service, "resumed", None)
        if resumed and key in resumed:
            # On air before the detector restarted: not a take, so no grace (the restart
            # at 22:29 on 10/5 left the rest of a break audible).
            resumed.discard(key)
            self.pol.start = -math.inf

    def _reset(self):
        self.base = None
        self.last = {}
        self.engine = self.service.engine        # which detector: classic or new
        self.sig = features.Signals(embed=self.service.embed, limited_range=self.info.get("range") == "limited",
                                    scorer=self.service.score if self.engine == "new" else None)
        self.gen += 1                # Whisper results for an earlier timeline are dropped
        self.speech = []             # [(t0, t1, words)] transcribed, in order
        self.windows = W.Windower()  # the sound, cut into Whisper's windows
        self.words_sent = 0          # chunks of self.speech whose words went to master (live captions)
        self.landmarks = []          # [(t, hash)] from the fingerprinter, in order
        self.print_known = None      # landmarks are complete before this input time
        self.printer = None
        self.src = Source(self.sig, self.speech, self)
        self.det = D.Detector(self.service.models[self.engine], library=self.service.library, prints=self.service.prints,
                              overlays=self.service.overlays, channel=self.info.get("channel_id"))
        self.det.prints.session = f"{self.key[:8]}-{self.gen}-{int(time.time())}"
        self.learnt = set()          # breaks whose wording has been offered to the ad library
        self.pol = Policy(self.service.policy_config(self.lookahead, engine=self.engine), gate=self._gate)
        self.aired = 0.0
        self.edge = 0.0
        self.behind = 0.0          # how far the analysis edge trails the newest media received
        self.behind_warned = False
        self.edge_wall = time.time()
        self.p_ad = None
        self._why_for = None                    # (span start, confirmed) the badge reason is for
        self.timeline = collections.deque(maxlen=TIMELINE)
        self.wall_off = None       # wall clock - input time, from the earliest-arriving frames
        self.wall_off_t = 0.0

    # time --------------------------------------------------------------------
    def t(self, pts):
        return (pts - self.base) / SECOND

    def pts(self, t):
        return int(self.base + t * SECOND)

    def wall(self, t):
        """Wall time at which input time t arrived. Steady even when a feed arrives in
        bursts, so the page's pictures and break times line up."""
        if self.wall_off is not None:
            return t + self.wall_off
        return self.edge_wall - (self.edge - t)

    def _note_arrival(self, t):
        off = time.time() - t
        if self.wall_off is None:
            self.wall_off = off
        else:
            self.wall_off = min(off, self.wall_off + DRIFT * max(0.0, t - self.wall_off_t))
        self.wall_off_t = t

    def _gate(self, t):
        """The sports feed's view of input time t, read as it comes. (Reading it as far
        behind as the broadcast runs, tried on 10/5, held a TBS mute 15 s into the game.)"""
        if self.gate is None or not self.service.settings.get("sports_gate", True):
            return None
        return self.gate(self.wall(t))

    # media -------------------------------------------------------------------
    def push(self, kind, pts, payload):
        with self.lock:
            last = self.last.get(kind)
            if last is not None and (pts < last - JUMP_BACK or pts > last + JUMP_AHEAD):
                # A frame off its timeline is dropped. Only a source that stays off it (it
                # restarted) starts the analysis over: that costs the programme memory (~5 min
                # before recurrence speaks again).
                now = time.monotonic()
                if self.off_since is None:
                    self.off_since, self.off_count = now, 0
                    log.info("input %s: %s frame %+.2f s off the timeline; dropping such frames",
                             self.key[:8], kind.decode(), (pts - last) / SECOND)
                self.off_count += 1
                if now - self.off_since < NEW_TIMELINE:
                    return
                log.info("input %s: timeline restarted (%d frames off it for %.1f s); starting over",
                         self.key[:8], self.off_count, now - self.off_since)
                self._reset()
                self.off_since = None
            elif kind == b"G" and self.off_since is not None:
                log.info("input %s: back on the timeline after %d frames off it", self.key[:8], self.off_count)
                self.off_since = None
            if self.base is None:
                self.base = pts
            self.last[kind] = pts
            t = self.t(pts)
            if t < 0:
                return
            sig = self.sig
            if kind == b"G":
                self._note_arrival(t)
            wall = self.wall(t)
        if kind == b"G" and len(payload) == proto.GRAY_W * proto.GRAY_H:
            sig.push_gray(np.array([t]), np.frombuffer(payload, np.uint8).reshape(1, proto.GRAY_H, proto.GRAY_W))
        elif kind == b"R" and len(payload) == proto.RGB_SIDE * proto.RGB_SIDE * 3:
            rgb = np.frombuffer(payload, np.uint8).reshape(1, proto.RGB_SIDE, proto.RGB_SIDE, 3)
            sig.push_rgb(np.array([t]), rgb)
            self.service.frames.save(self.key, wall, rgb[0])
        elif kind == b"A":
            samples = np.frombuffer(payload[: len(payload) // 4 * 4], np.float32)
            sig.push_audio(t, samples)
            if self.service.settings.get("speech", True) and self.service.speech.usable:
                self._hear(t, samples)
            if self.service.settings.get("known_ads", True):
                self._print(t, samples)

    def _print(self, t, samples):
        """Fingerprint the sound as it comes (a gap starts the fingerprinter over)."""
        p = self.printer
        if p is None or abs(t - (p.t0 + p.pushed / FP.RATE)) > 0.1:
            p = self.printer = FP.Printer(t0=t)
            p.pushed = 0
        got = p.push(samples)
        p.pushed += len(samples)
        with self.lock:
            if self.printer is p:
                self.landmarks.extend(got)
                self.print_known = p.known

    def _hear(self, t, samples):
        """Cut the sound into Whisper's overlapping windows (speech.Windower)."""
        with self.lock:
            jobs, gen = self.windows.push(t, samples), self.gen
        for t0, audio, upto in jobs:
            self.service.speech.submit(self, gen, t0, audio, upto)

    def heard(self, gen, t0, t1, words):
        with self.lock:
            if gen == self.gen:
                self.speech.append((t0, t1, words))

    def hint(self):
        """Whisper's prompt: the programme's title and, for an MLB game, its teams and players."""
        game = self.game or {}
        return W.prompt(game.get("title") or self.title, getattr(self.gate, "names", None) or ())

    def override(self, pts, action, seq):
        with self.lock:
            if self.base is None:
                self.ack = max(self.ack, seq)
                return
            t = self.t(pts)
            if action == "unmute":
                self.pol.override_unmute(t)
                self.det.mark("show", t - 5, t + 15)
                # A known ad playing as the operator says "it's the show" was learnt wrongly.
                gone = self.service.prints.remove(self.det.prints.matched_ads(t - 10, t))
                if gone:
                    self.service.note("forgot", clips=gone, why="it's the show")
                    log.info("%s: unlearnt ad clip(s) %s (it's the show)", self.key[:8], gone)
            elif action == "mute":
                self.pol.override_mute(t)
                self.det.mark("ad", t, t + self.pol.cfg.min_hold)
            self.ack = max(self.ack, seq)
            self.service.label({"input": self.key, "title": self.title, "source": self.info.get("source_id"),
                                "action": action, "t": round(t, 2), "wall": round(self.wall(t), 2),
                                "p_ad": self.p_ad, "label": "show" if action == "unmute" else "ad"})

    # decisions ---------------------------------------------------------------
    def tick(self):
        with self.lock:
            if self.base is None:
                return None
            edge = self.sig.edge()
            self._check_behind(edge)
            if edge <= self.edge:
                return self._message()
            self.edge, self.edge_wall = edge, time.time()
            if not (self.service.settings.get("speech", True) and self.service.speech.usable):
                self.det.text.known = None       # no words coming: nothing waits for them
            self.det.update(self.src, edge)
            self.sig.trim(edge - 20)
            self.sig.trim_seconds(edge - 10)
            self.lookahead = self.service.lookahead(self.info)
            self.pol.cfg = self.service.policy_config(self.lookahead, game=bool(self.game), engine=self.engine)
            a = edge - self.lookahead
            if a > self.aired:
                segs = self.det.decide(self.aired, a)
                quiet = self.service.quiet(self.title, self.key)
                if quiet and self.pol.muted:
                    self.pol._close(self.aired, "paused")
                if not quiet:
                    self.pol.step(segs, edge, ahead=self.det.decide(a, edge, settle=False))
                for seg in segs:
                    self.p_ad = seg.p_ad
                for s in range(int(math.ceil(self.aired)), int(math.ceil(a))):
                    self.timeline.append((round(self.wall(s), 1), round(self.p_ad or 0, 3), int(self.pol.muted)))
                self.aired = a
                self._learn()
        try:
            self.learn_game()
        except Exception:
            log.exception("learning the game's breaks failed")
        self._pictures()
        with self.lock:
            return self._message()

    def _pictures(self):
        """Pictures of each ad stored or heard here that has none yet, from the page's
        pictures of this input (kept 3 h): admute-ads/<clip>-<i>.jpg."""
        with self.lock:
            aired, self.det.prints.aired = self.det.prints.aired, []
            walls = [(cid, [self.wall(a + (b - a) * k) for k in PICTURES]) for cid, a, b in aired]
        for cid, times in walls:
            self.service.save_pictures(cid, self.key, times)

    def _check_behind(self, edge):
        """Every kind of signal must keep up: the lookahead only covers the analysis if
        its edge is where the media is. Past BEHIND_WARN, decisions reach master after
        their moment has aired; the lease has lapsed by then, so nothing is muted."""
        if not self.last:
            return
        self.behind = max(0.0, self.t(max(self.last.values())) - edge)
        if self.behind > BEHIND_WARN and not self.behind_warned:
            parts = self.sig.edge_parts()
            log.warning("%s: analysis is %.1f s behind the media (edges: video %.1f, audio %.1f, "
                        "pictures %.1f); mutes land late or not at all", self.key[:8], self.behind, *parts)
            self.behind_warned = True
        elif self.behind < BEHIND_WARN / 2 and self.behind_warned:
            log.info("%s: analysis caught up (%.1f s behind)", self.key[:8], self.behind)
            self.behind_warned = False

    def _learn(self):
        """Confirmed breaks teach the ad libraries (wording, sound), unless they were cut
        short as the programme ("it's the show", a retraction) or marked "Was the show"."""
        settings = self.service.settings
        for sp in self.pol.learnable(self.aired, self.learnt, LEARN_AFTER):
            span_id = f"{self.key[:8]}-{int(sp.start)}"
            if not settings.get("learn_ads", True) or self.service.marked_show(span_id):
                continue
            if not settings.get("known_ads", True):
                self.det.prints.db, db = FP.PrintDB(), self.det.prints.db   # learn words only
                self.det.learn_break(sp.start, sp.end, span_id)
                self.det.prints.db = db
                continue
            got = self.det.learn_break(sp.start, sp.end, span_id, src=self.title or self.info.get("channel_id"))
            clips = got.get("clips") or []
            if clips:
                db = self.service.prints
                known = [cid for cid in clips if db.known(cid)]
                self.service.note("break", clips=clips, src=self.title or self.info.get("channel_id"),
                                  at=round(self.wall(sp.start)), dur=round(sp.end - sp.start),
                                  spots=len(clips), known=len(known))
                log.info("break %s: %d spots learnt (%d now known ads)", span_id, len(clips), len(known))

    def learn_game(self, final=False):
        """An MLB game on air: each break, once complete, is learnt from the feed (between
        a half-inning's last pitch and the next's first; admute.seed.align_breaks), with
        no recording: the black seams, the detector's own evidence and the fingerprints are
        all here. Breaks found this way count as known ads at once."""
        from . import seed as SEED
        settings = self.service.settings
        gate = getattr(self.gate, "gate", None)
        if gate is None or not settings.get("learn_games", True) or not settings.get("known_ads", True):
            return
        if not final and time.monotonic() < self.game_next:
            return
        self.game_next = time.monotonic() + GAME_EVERY
        with self.lock:
            if self.base is None or self.wall_off is None:
                return
            halves = list(gate.halves)
            edges = [(a1 - self.wall_off, b0 - self.wall_off) for (_, a1), (b0, _) in zip(halves, halves[1:])
                     if b0 - a1 >= 90]
            settled = self.det.frozen_to
            margin = (self.game_lag if self.game_lag is not None else SEED.LAG_RANGE[1]) + 15
            edges = [(a, b) for a, b in edges if a > 0 and b + margin < settled]
            if len(edges) < 2:
                return
            blacks = sorted(s.t for s in self.det.seam_list() if s.kind == "black")
            logit = np.array(self.det.lp_ad) - np.array(self.det.lp_show)
            spans, lag, lags, rejected = SEED.align_breaks(edges, blacks, logit)
            self.game_lag = lag
            title = (self.game or {}).get("title") or self.title
            pk = (self.game or {}).get("game_pk")
            new, clips = [], []
            for a, b, _ in spans:
                if round(a) in self.game_learnt:
                    continue
                self.game_learnt.add(round(a))
                before = set(self.service.prints.clips)
                got = self.det.learn_break(a, b, f"{self.key[:8]}-{int(a)}", src=title, known=f"game-{pk}")
                for cid in got.get("clips") or []:
                    new.append(cid not in before)
                    clips.append(cid)
        if new:
            self.game_stats["breaks"] += len(new)
            self.game_stats["new"] += sum(new)
            self.service.note("game", src=title, breaks=len(new), new=sum(new), lag=lag, clips=clips)
            log.info("%s: %d breaks learnt from MLB's feed (%d new ads; broadcast %d s behind)",
                     title, len(new), sum(new), lag)

    # ------------------------------------------------------------------ diagnostics
    GROUPS = {"picture": ("bug", "cut_rate", "recurrence", "colour", "ad_match") + D.OVERLAY_FEATURES + clip.FEATURES,
              "words": D.TEXT_FEATURES, "sound": ("fp_known", "fp_repeat", "fp_show")}
    PLAIN = {"bug": "no station or score bug", "cut_rate": "fast cutting", "recurrence": "unlike the programme",
             "colour": "unlike the programme's colours", "ad_match": "looks like earlier ads",
             "txt_lexicon": "ad words", "txt_known_ad": "ad wording heard before", "txt_repeat": "repeated words",
             "txt_show_vocab": "not the programme's words", "txt_ad_vocab": "ads' words", "txt_you": "talks to you",
             "fp_known": "a known ad", "fp_repeat": "repeats an earlier ad", "fp_show": "show sound",
             "ov_score": "score bug on screen", "ov_logo": "network logo on screen", "ov_ad": "an ad label on screen",
             "img_zeroshot2": "looks like an ad", "img_split": "split-screen"}

    def why(self, span=None) -> list:
        """[headline, detail] for the moment about to air: how sure, and what says so."""
        det, m = self.det, self.det.m
        s = min(int(self.aired), len(det.lp_ad) - 1)
        p = self.p_ad if self.p_ad is not None else 0.0
        pct = f"{int(5 * round(20 * p))}%"
        if span is not None and span.start_reason == "override":
            return ["YOU · it's an ad", f"detector: {pct} ad"]
        if s < 0:
            return [pct, ""]
        if m.get("warm") and math.isnan(det.feats["recurrence"][s]):
            m = m["warm"]                                 # warming up: these weights are the ones deciding
        contrib = {}
        for k in range(max(0, s - 2), s + 1):             # the last three seconds, together
            for name, mean, scale, coef in zip(m["features"], m["mean"], m["scale"], m["coef"]):
                v = det.feats.get(name, [])[k] if k < len(det.feats.get(name, [])) else math.nan
                if v == v and scale:
                    contrib[name] = contrib.get(name, 0.0) + coef * (v - mean) / scale
        label = det.overlays.showing(s, "ad")
        if label:
            return [f"{pct} · AD LABEL", f"{label} on screen"[:48]]
        known = det.feats["fp_known"][s] if s < len(det.feats["fp_known"]) else math.nan
        if known == known and known >= 0.12:
            qt, qh = det.prints.span(s - 1.5, s + 2.5)
            _, cid, _ = det.prints.db.match(qt, qh, "ad")
            c = det.prints.db.clips.get(cid, {}) if cid is not None else {}
            seed = c.get("seed") or ""
            where = (c.get("src") or "an earlier airing") if not seed.startswith("extra") else "the recordings"
            heard = c.get("breaks", 1) + (0 if self.service.prints.known(cid) else 1) if cid is not None else None
            detail = f"{where} · heard {heard}x" if heard and not seed else f"from {where}"
            return [f"{pct} · KNOWN AD", detail[:40]]
        groups = {g: sum(v for n, v in contrib.items() if n in names) for g, names in self.GROUPS.items()}
        top = max(groups, key=groups.get) if groups else "picture"
        lead = sorted((v, n) for n, v in contrib.items() if v > 0.3)[::-1][:2]
        detail = " + ".join(self.PLAIN.get(n, n) for _, n in lead) or "the evidence together"
        if span is not None and span.seam in ("black", "cut"):
            detail += " · black frame" if span.seam == "black" else " · at a cut"
        gate = self._gate(self.aired) if self.base is not None else None
        if gate == "break":
            detail += " · between innings"
        return [f"{pct} · {top.upper()}", detail[:48]]

    def _message(self):
        cur = self.pol.current
        # The reason is fixed per mute: worked out when it starts and once more when it
        # confirms, so the badge doesn't change its words every half second.
        if cur is not None and (cur.why is None or self._why_for != (cur.start, cur.confirmed)):
            cur.why = self.why(cur)
            self._why_for = (cur.start, cur.confirmed)
        events = []
        for span in self.pol.all_spans()[-4:]:
            if span.end is not None and span.end < self.aired - 60:
                continue
            events.append([self.pts(span.start), 0.0, FADE_DOWN])
            if span.end is not None:
                events.append([self.pts(span.end), 1.0, FADE_UP])
        badge, why = None, None
        if cur is not None:
            badge = [self.pts(cur.start), None, "AD" if cur.confirmed else "AD?", round(cur.peak, 3)]
            why = cur.why
        elif self.pol.spans and self.pol.spans[-1].end > self.aired - 2:
            sp = self.pol.spans[-1]
            badge = [self.pts(sp.start), self.pts(sp.end), "AD" if sp.confirmed else "AD?", round(sp.peak, 3)]
            why = sp.why
        # "why" is a field of its own: a worker that predates it ignores it, while badge
        # keeps the four items every worker unpacks. So are "speech" (this input is being
        # transcribed) and "words" (new ones, on the input's timeline): live captions use
        # them rather than running a Whisper of their own (docs/live-captions.md).
        msg = {"input": self.key, "ack": self.ack, "events": events,
               "lease": self.pts(self.aired + LEASE_AHEAD), "badge": badge, "p_ad": self.p_ad,
               "why": why, "state": self.state(),
               "speech": bool(self.service.settings.get("speech", True) and self.service.speech.usable)}
        if self.words_sent < len(self.speech):
            new, self.words_sent = self.speech[self.words_sent:], len(self.speech)
            msg["words"] = [[self.pts(a), self.pts(b), w] for _, _, ws in new for a, b, w in ws]
        return msg

    def state(self):
        if self.service.quiet(self.title, self.key):
            return "paused"
        if self.pol.current is not None:
            return "held" if self.pol.held else "muted"
        return "listening"

    def describe(self):
        with self.lock:
            known = self.det.feats["fp_known"]

            def known_in(a, b):
                vals = [v for v in known[max(0, int(a)):int(b) + 1] if v == v]
                return round(max(vals), 2) if vals else None

            spans = [{"id": f"{self.key[:8]}-{int(sp.start)}", "start": round(self.wall(sp.start), 1),
                      "end": round(self.wall(sp.end), 1) if sp.end is not None else None,
                      "confirmed": sp.confirmed, "end_reason": sp.end_reason, "start_reason": sp.start_reason,
                      "peak": round(sp.peak, 3), "seam": sp.seam, "why": sp.why,
                      "known": known_in(sp.start, sp.end if sp.end is not None else self.aired)}
                     for sp in self.pol.all_spans()[-40:]]
            now = int(self.aired)
            known_now = self.det.known_ad(max(0, now - 2), span=4) if now < len(known) else False
            seams = [[round(self.wall(s.t), 1), s.kind] for s in self.det.seam_list()
                     if s.t > self.edge - 3600 and s.kind != "cut"]       # (cuts: several a minute)
            return {"input": self.key, "title": self.title, "source_id": self.info.get("source_id"),
                    "channel_id": self.info.get("channel_id"), "lane": self.info.get("lane"),
                    "lookahead": self.lookahead, "state": self.state(), "p_ad": self.p_ad, "detector": self.engine,
                    "muted": self.pol.muted, "warm": math.isfinite(self.det.warm_from) and self.aired >= self.det.warm_from,
                    "game": self.game, "gate": self._gate(self.aired) if self.base is not None else None,
                    "since": round(self.started, 1), "analysed_seconds": round(self.edge, 1),
                    "behind": round(self.behind, 1),
                    "heard": self._heard(), "known_now": known_now,
                    "overlays": self.det.overlays.describe(now),
                    "overlay_events": list(self.det.overlays.events)[-8:],
                    "why": self.why(self.pol.current) if self.pol.current is not None else None,
                    "game_learning": ({**self.game_stats, "lag": self.game_lag} if self.gate is not None else None),
                    "spans": spans, "seams": seams[-200:], "timeline": list(self.timeline)}

    def _heard(self):
        """The last few words transcribed, for the page: [wall time, text]."""
        words = [w for _, _, ws in self.speech[-4:] for w in ws][-16:]
        if not words or words[-1][1] < self.edge - 30:
            return None
        return [round(self.wall(words[0][0]), 1), " ".join(w[2] for w in words)]


class Service:
    def __init__(self, config_path: str):
        cfg = json.loads(Path(config_path).read_text())
        sock = Path(cfg["master"]["socket_path"])
        if not sock.is_absolute():
            sock = Path(config_path).resolve().parent / sock
        self.dir = sock.parent
        self.path = sock.with_name("admute.sock")
        self.state_path = sock.with_name("admute-state.json")
        self.labels_path = sock.with_name("admute-labels.jsonl")
        self.frames = FrameStore(sock.with_name("admute-frames"))
        self.captions = CaptionSettings(sock)
        self.captions_on = False
        self.speech = Speech(self)
        self.library = T.AdLibrary(path=str(sock.with_name("admute-adtext.json")))
        self.prints = FP.PrintDB(path=str(sock.with_name("admute-prints.npz")))
        self.overlays = OV.Library(path=str(sock.with_name("admute-overlays.json")))
        self.resumed = set()        # inputs on air when the detector last stopped (no take grace for them)
        try:
            old = json.loads(self.state_path.read_text())
            if time.time() - float(old.get("updated", 0)) < RESUME_WITHIN:
                self.resumed = {i["input"] for i in old.get("inputs", []) if i.get("input")}
        except (OSError, ValueError, TypeError):
            pass
        self.catalogue_path = sock.with_name("admute-prints.json")
        self.catalogue_version = None
        self.ads_dir = sock.with_name("admute-ads")          # pictures of each ad, for the Ad database
        self.ads_pruned = 0.0
        self.commands_path = sock.with_name("admute-commands.jsonl")
        try:
            self.commands_at = self.commands_path.stat().st_size     # only commands sent from now on
        except OSError:
            self.commands_at = 0
        self.prints_log = collections.deque(maxlen=60)
        self.show_marks = (None, set())    # (labels file mtime, span ids marked "Was the show")
        self.settings_store = AdMuteSettings(sock, lenient=True)
        self.settings = self.settings_store.read()
        server = cfg.get("server", {})
        self.web = f"http://127.0.0.1:{server.get('port', 6969)}"
        self.api_key = server.get("api_key")
        self.model = D.load_model()
        self.models = {"classic": self.model}
        if NEW_MODEL_JSON.exists():
            self.models["new"] = D.load_model(str(NEW_MODEL_JSON))
        self.engine, self.engine_error = "classic", None   # the detector running, and why not the one asked for
        self.scorer, self.scorer_error = None, None        # CLIP, loaded when the new detector first runs
        self.clip_took = collections.deque(maxlen=120)     # seconds per frame, for the page
        self.clip_failures = 0
        seed = self.model.get("prints") or {}
        if seed.get("seed"):
            try:   # the labelled recordings' ads, once (a newer seed is added beside the old)
                self.prints.merge_seed(FP.PrintDB(str(ROOT / "admute" / seed["seed"])), seed.get("tag") or seed["seed"])
            except (OSError, ValueError, KeyError) as exc:
                log.warning("cannot load the known-ads seed: %s", exc)
        self.embed = None
        self.sessions: dict[str, Session] = {}
        self.lock = threading.Lock()
        self.conn = None
        self.conn_lock = threading.Lock()
        self.stopping = threading.Event()
        self.gates: dict[int, sports.LiveGate] = {}

    def lookahead(self, info):
        """How far behind the analysis edge the moment about to air is. Master delays the
        programme lookahead + MARGIN, or 6 s with live captions on (one shared delay,
        which never shrinks while master runs). Erring long only lets the lease lapse,
        and then the sound comes back."""
        own = float(info.get("lookahead", 3.0))
        return max(own, CAPTION_DELAY - MARGIN) if self.captions_on and USE_CAPTION_DELAY else own

    def policy_config(self, lookahead, game=False, engine="classic"):
        """Outside games a mute starts only at a seam -- a black frame or a hard cut -- or on a
        known ad: on the recordings that removed early starts. (Black alone, before 10/3:
        WJLA fades to black at every break, but cable feeds often cut straight to an ad.)
        NBC's games flash black inside breaks, not always at their edges, so a game's mute
        may start where the detector is sure."""
        s = self.settings
        cfg = PolicyConfig.from_sensitivity(s["sensitivity"], lookahead=lookahead, max_mute=float(s["max_mute"]),
                                            open_at="any" if game else "seam")
        # The new detector was tested with a 5 s grace after a take: its warm-up weights
        # judge the first minutes without the programme memory.
        grace = (self.models.get(engine) or {}).get("policy", {}).get("grace")
        if grace is not None:
            cfg.grace = float(grace)
        return cfg

    def score(self, rgb):
        """CLIP's picture scores of one frame (Signals calls this once a second per input)."""
        began = time.perf_counter()
        try:
            out = self.scorer(rgb)
        except Exception as exc:       # never in the reader's way: the second just has no score
            if not self.clip_failures:
                log.warning("CLIP failed on a frame: %s", exc)
            self.clip_failures += 1
            return {}
        self.clip_took.append(time.perf_counter() - began)
        return out

    def choose_engine(self):
        """Run the detector the settings ask for, if it can run: the new one needs its model and
        CLIP's. If it can't, the classic one runs and the page says why. A change starts every
        input's analysis over (as when a source restarts): each detector keeps its own memory."""
        want = self.settings.get("detector", "classic")
        error = None
        if want == "new":
            if "new" not in self.models:
                error = "its model (admute/model_new.json) is missing"
            elif self.scorer is None and self.scorer_error is None:
                try:
                    self.scorer = clip.Scorer(threads=1)
                    log.info("CLIP loaded from %s", clip.MODEL)
                except Exception as exc:
                    self.scorer_error = f"CLIP cannot load: {exc}"[:300]
                    log.warning("%s; the classic detector runs", self.scorer_error)
            error = error or self.scorer_error
        else:
            self.scorer_error = None          # asking for the new one again tries CLIP again
        running = want if error is None else "classic"
        self.engine_error = error
        if running == self.engine:
            return
        log.info("detector: %s (was %s); every input starts over", running, self.engine)
        self.engine = running
        with self.lock:
            sessions = list(self.sessions.values())
        for session in sessions:
            with session.lock:
                session._reset()
                session.pol.start = -math.inf     # not a take: no grace (as for an input resumed after a restart)

    def quiet(self, title, key=None):
        s = self.settings
        if paused(s, key, time.time()):
            return True
        t = (title or "").lower()
        return bool(t) and any(x.lower() in t for x in s.get("exceptions", []))

    def _last_breaks(self, session):
        try:
            session.learn_game(final=True)
        except Exception:
            log.exception("learning the game's last breaks failed")

    def note(self, what, **info):
        """Something the known-ads database learnt or forgot, for the page."""
        self.prints_log.append({"t": round(time.time(), 1), "what": what, **info})

    def _commands(self):
        """Requests from the page (the web app appends to admute-commands.jsonl): forget clips."""
        try:
            with open(self.commands_path) as f:
                f.seek(self.commands_at)
                lines = f.readlines()
                self.commands_at = f.tell()
        except OSError:
            return
        for line in lines:
            try:
                cmd = json.loads(line)
            except ValueError:
                continue
            ids = [int(c) for c in cmd.get("forget", []) if isinstance(c, int)]
            gone = self.prints.remove(ids)
            if gone:
                self.note("forgot", clips=gone, why="you")
                log.info("forgot clip(s) %s (from the page)", gone)
            name = cmd.get("name")
            if isinstance(name, dict) and isinstance(name.get("clip"), int) and isinstance(name.get("name"), str):
                if self.prints.rename(name["clip"], name["name"]):
                    log.info("clip %d named %r (from the page)", name["clip"], name["name"])

    def _catalogue(self):
        if self.prints.version == self.catalogue_version:
            return
        self.catalogue_version = self.prints.version
        pics = self._pictures_held()
        clips = self.prints.catalogue()
        for c in clips:
            c["pics"] = pics.get(c["id"], 0)
        tmp = self.catalogue_path.with_name(".admute-prints.tmp")
        try:
            tmp.write_text(json.dumps({"updated": round(time.time(), 1), "clips": clips}))
            os.replace(tmp, self.catalogue_path)
        except OSError as exc:
            log.warning("cannot write the known-ads list: %s", exc)

    def _seed_inbox(self):
        """New known ads fingerprinted from recordings (admute.seed --inbox), and scripts
        found for known ads in recordings (admute.scripts): merged once each, while running."""
        inbox = self.dir / "admute-seeds"
        try:
            files = sorted(inbox.glob("*.npz"))
            scripts = sorted(inbox.glob("*.scripts.json"))
        except OSError:
            return
        for f in scripts:
            try:
                got = json.loads(f.read_text())
                n = 0
                for cid, sc in (got.get("clips") or {}).items():
                    for a, b in sc.get("cover") or ():
                        n += self.prints.set_script(int(cid), [w for w in sc["words"] if a <= w[0] < b], 0.0,
                                                    sc.get("from", "recording"), (a, b))
                self.catalogue_version = None
                log.info("scripts from %s: %d clips filled in", f.name, n)
            except Exception as exc:
                log.warning("cannot merge %s: %s", f.name, exc)
            try:
                (inbox / "done").mkdir(exist_ok=True)
                f.replace(inbox / "done" / f.name)
            except OSError:
                pass
        for f in files:
            try:
                new = self.prints.merge_seed(FP.PrintDB(str(f)), f.stem)
                self.note("seed", src=f.stem, new=new)
                log.info("merged known ads from %s: %d new clips", f.name, new)
            except Exception as exc:
                log.warning("cannot merge %s: %s", f.name, exc)
            try:
                (inbox / "done").mkdir(exist_ok=True)
                f.replace(inbox / "done" / f.name)
            except OSError:
                pass

    # pictures of each ad (admute-ads/<clip>-<i>.jpg) ------------------------------------
    def save_pictures(self, cid, key, walls) -> int:
        """Copy the page's pictures of input ``key`` at these wall times as clip ``cid``'s,
        unless it has some already."""
        if (self.ads_dir / f"{cid}-0.jpg").exists():
            return 0
        saved = 0
        try:
            self.ads_dir.mkdir(exist_ok=True)
            for i, wall in enumerate(walls):
                for near in (0, -1, 1, -2, 2):
                    src = self.frames.root / key / f"{int(wall) + near}.jpg"
                    if src.exists():
                        tmp = self.ads_dir / f".{cid}-{saved}.tmp"
                        tmp.write_bytes(src.read_bytes())
                        os.replace(tmp, self.ads_dir / f"{cid}-{saved}.jpg")
                        saved += 1
                        break
        except OSError as exc:
            log.warning("cannot keep pictures of clip %s: %s", cid, exc)
        if saved:
            self.catalogue_version = None
        return saved

    def _pictures_held(self) -> dict:
        held = {}
        try:
            for f in self.ads_dir.glob("*.jpg"):
                cid = f.name.split("-")[0]
                if cid.isdigit():
                    held[int(cid)] = held.get(int(cid), 0) + 1
        except OSError:
            pass
        return held

    def _prune_pictures(self):
        """Pictures of clips no longer known go (forgotten, or dropped as old)."""
        if time.monotonic() < self.ads_pruned:
            return
        self.ads_pruned = time.monotonic() + 300
        keep = set(self.prints.clips)
        try:
            for f in self.ads_dir.glob("*.jpg"):
                cid = f.name.split("-")[0]
                if cid.isdigit() and int(cid) not in keep:
                    f.unlink(missing_ok=True)
        except OSError:
            pass

    def marked_show(self, span_id):
        try:
            mtime = self.labels_path.stat().st_mtime
        except OSError:
            return False
        if mtime != self.show_marks[0]:
            old = self.show_marks[1]
            marks = set()
            try:
                with open(self.labels_path) as f:
                    for line in f:
                        try:
                            row = json.loads(line)
                        except ValueError:
                            continue
                        if row.get("label") == "show" and row.get("span_id"):
                            marks.add(row["span_id"])
            except OSError:
                pass
            self.show_marks = (mtime, marks)
            gone = self.prints.remove(self.prints.clips_of(marks - old))
            if gone:
                self.note("forgot", clips=gone, why="was the show")
                log.info("unlearnt ad clip(s) %s (marked: was the show)", gone)
        return span_id in self.show_marks[1]

    def label(self, row):
        if not self.settings.get("learn", True):
            return
        try:
            with open(self.labels_path, "a") as f:
                f.write(json.dumps(row) + "\n")
        except OSError as exc:
            log.warning("cannot record a label: %s", exc)

    # socket ------------------------------------------------------------------
    def serve(self):
        from .embed import Embedder
        self.embed = Embedder(threads=1)
        self.choose_engine()
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.path))
        os.chmod(self.path, 0o600)
        server.listen(2)
        for target in (self._ticker, self._housekeeping) + (self.speech.run,) * SPEECH_WORKERS:
            threading.Thread(target=target, daemon=True).start()
        log.info("ad-mute detector listening on %s", self.path)
        while not self.stopping.is_set():
            conn, _ = server.accept()
            with self.conn_lock:
                if self.conn is not None:
                    try:
                        self.conn.close()
                    except OSError:
                        pass
                self.conn = conn
            threading.Thread(target=self._read, args=(conn,), daemon=True).start()

    def _read(self, conn):
        buf = bytearray()
        log.info("master worker connected")
        try:
            while True:
                chunk = conn.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
                for kind, key, pts, payload in proto.read_frames(buf):
                    self._frame(kind, key, pts, payload)
        except (OSError, ValueError) as exc:
            log.warning("worker connection failed: %s", exc)
        finally:
            log.info("master worker disconnected")
            with self.conn_lock:
                if self.conn is conn:
                    self.conn = None
            with self.lock:
                self.sessions.clear()
            self.speech.forget()

    def _frame(self, kind, key, pts, payload):
        if kind == b"S":
            info = json.loads(payload)
            with self.lock:
                if key not in self.sessions:
                    self.sessions[key] = Session(self, key, info)
                    log.info("analysing %s (%s %s)", key[:8], info.get("source_id"), info.get("channel_id"))
            return
        with self.lock:
            session = self.sessions.get(key)
        if session is None:
            return
        if kind == b"E":
            with self.lock:
                ended = self.sessions.pop(key, None)
            log.info("input %s ended", key[:8])
            if ended is not None:
                self.speech.forget(ended)
            if ended is not None and ended.gate is not None:
                # a game's last breaks: learnt from the feed once it has caught up
                threading.Thread(target=self._last_breaks, args=(ended,), daemon=True).start()
        elif kind == b"O":
            body = json.loads(payload)
            session.override(pts, body.get("action"), int(body.get("seq", 0)))
        else:
            session.push(kind, pts, payload)

    def _send(self, msg):
        data = (json.dumps(msg) + "\n").encode()
        with self.conn_lock:
            if self.conn is None:
                return
            try:
                self.conn.sendall(data)
            except OSError:
                pass

    def _ticker(self):
        while not self.stopping.wait(TICK):
            with self.lock:
                sessions = list(self.sessions.values())
            for session in sessions:
                try:
                    msg = session.tick()
                    session.failures = 0
                except Exception:
                    # Nothing is sent, so the worker's lease runs out and the sound comes back.
                    # Starting over costs the programme memory, so only when it keeps failing.
                    session.failures += 1
                    if session.failures == 1:
                        log.exception("detection failed for %s", session.key[:8])
                    if session.failures >= FAILURES:
                        log.warning("detection for %s failed %d times running; starting it over",
                                    session.key[:8], session.failures)
                        with session.lock:
                            session._reset()
                        session.failures = 0
                    continue
                if msg:
                    self._send(msg)

    # settings, queue, page ---------------------------------------------------------
    def _housekeeping(self):
        next_queue = next_save = 0.
        while not self.stopping.wait(STATE_EVERY):
            try:
                self.settings = self.settings_store.read()
            except Exception as exc:
                log.warning("cannot read ad-mute settings: %s", exc)
            self.choose_engine()
            try:
                self.captions_on = bool(self.captions.read()["enabled"])
            except Exception as exc:
                log.debug("cannot read caption settings: %s", exc)
            if time.monotonic() >= next_queue:
                next_queue = time.monotonic() + QUEUE_EVERY
                self._follow_queue()
            self._commands()
            self._write_state()
            self._catalogue()
            self.frames.prune()
            self._prune_pictures()
            if time.monotonic() >= next_save:
                next_save = time.monotonic() + 60
                with self.lock:
                    sessions = list(self.sessions.values())
                for session in sessions:
                    with session.lock:
                        session.det.overlays.flush()
                try:
                    self.library.save()
                    self.prints.save()
                    self.overlays.save()
                except OSError as exc:
                    log.warning("cannot save the ad libraries: %s", exc)
                self.marked_show("")      # picks up new "Was the show" marks
                self._seed_inbox()

    def _get(self, path):
        req = urllib.request.Request(self.web + path, headers={"Accept": "application/json",
                                                               **({"X-API-Key": self.api_key} if self.api_key else {})})
        with urllib.request.urlopen(req, timeout=4) as r:
            return json.load(r)

    def _follow_queue(self):
        with self.lock:
            sessions = list(self.sessions.values())
        if not sessions:
            return
        try:
            queue = self._get("/v1/queue")
        except Exception as exc:
            log.debug("queue unavailable: %s", exc)
            return
        items = queue.get("items") or []
        hold = queue.get("hold") or {}
        for session in sessions:
            item = next((i for i in items if ((i.get("result") or {}).get("on_air") or {}).get("id") == session.key), None)
            if item:
                session.title = item.get("title") or session.title
                game = item.get("game") or ((item.get("hold_end") or {}).get("game"))
            else:
                game = None
            game = game or (hold.get("game") if hold and item else None)
            if game and (game.get("league") in (None, "mlb")) and isinstance(game.get("game_pk"), int):
                pk = game["game_pk"]
                if pk not in self.gates:
                    self.gates[pk] = sports.LiveGate(pk)
                session.game, session.gate = game, self.gates[pk]
            else:
                session.game, session.gate = game, None
        wanted = {s.game["game_pk"] for s in sessions if s.game and s.gate}
        for pk in [pk for pk in self.gates if pk not in wanted]:
            self.gates.pop(pk).stop()

    def _write_state(self):
        with self.lock:
            sessions = list(self.sessions.values())
        with self.conn_lock:
            connected = self.conn is not None
        took = sorted(self.clip_took)
        model = self.models[self.engine]
        state = {"updated": round(time.time(), 1), "connected": connected,
                 "model": {k: model.get(k) for k in ("features", "coef", "trained_on")},
                 "detector": {"selected": self.settings.get("detector", "classic"), "running": self.engine,
                              "error": self.engine_error, "available": sorted(self.models),
                              "clip_ms": round(1000 * took[len(took) // 2]) if took and self.engine == "new" else None},
                 "speech": self.speech.status(),
                 "prints": self.prints.summary(), "prints_log": list(self.prints_log)[-30:],
                 "overlays": self.overlays.summary(),
                 "library": {"seed": len(self.library.seed), "learnt": len(self.library.learnt),
                             "known": sum(v[0] >= T.KNOWN_MIN for v in self.library.learnt.values())},
                 "inputs": [s.describe() for s in sessions]}
        tmp = self.state_path.with_name(".admute-state.tmp")
        try:
            tmp.write_text(json.dumps(state))
            os.replace(tmp, self.state_path)
        except OSError as exc:
            log.warning("cannot write the ad-mute state: %s", exc)


class Lane:
    """One input's windows, in order: one worker at a time takes them."""

    def __init__(self):
        self.jobs = collections.deque()     # (gen, t0, audio, upto, queued at)
        self.busy = False
        self.gen = None
        self.committer = W.Committer()
        self.lag = None                     # seconds from a window's end to its words


class Speech:
    """Whisper for every analysed input. Each input has a lane of windows (at most
    SPEECH_BACKLOG waiting; older ones are dropped), and SPEECH_WORKERS lanes are
    transcribed at once, SPEECH_THREADS deep each, by one model: admute.json's
    speech_model. A model that cannot load falls back to base.en; with neither,
    detection carries on without words (usable goes False until a retry)."""

    def __init__(self, service):
        self.service = service
        self.cond = threading.Condition()
        self.lanes: dict[Session, Lane] = {}
        self.load_lock = threading.Lock()
        self.model = None
        self.model_name = None
        self.failed: dict[str, float] = {}  # model -> when it would not load
        self.error = None
        self.dropped = 0
        self.done = 0
        self.busy = collections.deque(maxlen=120)    # (finished at, seconds of work, seconds of new audio)

    def wanted(self):
        return self.service.settings.get("speech_model") or W.MODEL

    def _failed(self, name):
        at = self.failed.get(name)
        return at is not None and time.monotonic() - at < SPEECH_RETRY

    @property
    def usable(self):
        return not (self._failed(self.wanted()) and self._failed(W.MODEL))

    def submit(self, session, gen, t0, audio, upto):
        with self.cond:
            lane = self.lanes.get(session)
            if lane is None:
                lane = self.lanes[session] = Lane()
            lane.jobs.append((gen, t0, audio, upto, time.monotonic()))
            while len(lane.jobs) > SPEECH_BACKLOG:
                lane.jobs.popleft()
                self.dropped += 1
            self.cond.notify()

    def forget(self, session=None):
        """An input ended (None: all of them)."""
        with self.cond:
            if session is None:
                self.lanes.clear()
            else:
                self.lanes.pop(session, None)

    def _next(self):
        """The idle lane whose oldest window has waited longest."""
        ready = [(lane.jobs[0][4], id(lane), session, lane) for session, lane in self.lanes.items()
                 if lane.jobs and not lane.busy]
        return min(ready)[2:] if ready else None

    def run(self):
        while not self.service.stopping.is_set():
            with self.cond:
                got = self._next()
                if got is None:
                    self.cond.wait(1)
                    continue
                session, lane = got
                job = lane.jobs.popleft()
                lane.busy = True
            try:
                self._work(session, lane, *job)
            except Exception:
                log.exception("transcription failed")
            finally:
                with self.cond:
                    lane.busy = False
                    self.cond.notify()

    def _work(self, session, lane, gen, t0, audio, upto, queued):
        if lane.gen is not None and gen < lane.gen:
            return                                  # for an earlier timeline
        model = self._model()
        if model is None:
            return
        began = time.monotonic()
        try:
            words = W.transcribe(model, audio, t0, session.hint())
        except Exception as exc:
            self.error = f"transcription failed: {exc}"[:300]
            log.warning(self.error)
            return
        if self.error and self.error.startswith("transcription failed"):
            self.error = None
        if gen != lane.gen:
            lane.gen, lane.committer = gen, W.Committer()
        got = lane.committer.take(t0, upto, words)
        if got is None:
            return
        now = time.monotonic()
        # The stretch's first word was said this long ago (the window ended when it was queued).
        lane.lag = round(now - queued + t0 + len(audio) / W.RATE - got[0], 1)
        with self.cond:
            self.done += 1
            self.busy.append((now, now - began, got[1] - got[0]))
        session.heard(gen, *got)

    def _model(self):
        want = self.wanted()
        with self.load_lock:
            for name in dict.fromkeys([want, W.MODEL]):
                if self._failed(name):
                    continue
                if self.model is not None and self.model_name == name:
                    return self.model
                workers = SPEECH_WORKERS if name in ("tiny.en", "base.en") else 1
                try:
                    self.model = W.load(name, threads=SPEECH_THREADS, workers=workers)
                except Exception as exc:
                    self.failed[name] = time.monotonic()
                    self.error = f"Whisper {name} is unavailable: {exc}"[:300]
                    log.warning("%s", self.error)
                    continue
                self.model_name = name
                self.error = None if name == want else f"Whisper {want} is unavailable; using {name}"
                log.info("Whisper %s loaded (%d at once, %d threads each)", name, workers, SPEECH_THREADS)
                return self.model
            log.warning("no Whisper model loads; detecting without words")
            self.model = self.model_name = None
            return None

    def status(self):
        with self.cond:
            busy = list(self.busy)
            lags = [lane.lag for lane in self.lanes.values() if lane.lag is not None]
            queued = sum(len(lane.jobs) for lane in self.lanes.values())
            inputs = len(self.lanes)
        work = sum(b[1] for b in busy)
        audio = sum(b[2] for b in busy)
        return {"model": self.model_name or self.wanted(), "wanted": self.wanted(), "usable": self.usable,
                "error": self.error, "chunks": self.done, "dropped": self.dropped, "queued": queued,
                "inputs": inputs, "threads": SPEECH_THREADS,
                # Time Whisper spends per second of sound, and how late words come after they are said.
                "load": round(work / audio, 2) if audio else None, "lag": max(lags) if lags else None}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="admute.service")
    ap.add_argument("--config", default=str(ROOT / "config.master.json"))
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    Service(args.config).serve()


if __name__ == "__main__":
    main()
