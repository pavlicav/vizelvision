"""The sports-feed gate: while play is live, nothing gets muted.

A broadcast only goes to break between half-innings or for a pitching change (or
an injury, a review...). MLB's live feed says when each half-inning's first and
last pitches were, and when pitchers changed. ``Gate`` turns that into

  'live'   -- inside a half-inning, from LIVE_AFTER s after its first pitch to its
              last pitch, away from pitching changes: muting is not allowed, and a
              mute still running ends (the detector missed the return)
  'break'  -- between half-innings, or around a pitching change
  None     -- before the first pitch, after the last, or no feed: no opinion

The feed runs within about +-30 s of the broadcast, so the margins are generous.
The gate can only stop a mute, never cause one.
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import threading
import time
import urllib.request

LIVE_AFTER = 10.0          # the broadcast is back before the first pitch (it runs ~10 s behind the feed)
SUB_BEFORE, SUB_AFTER = 30.0, 240.0
FEED = "https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"


def _ts(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def halves_from_feed(feed: dict) -> tuple[list[tuple[float, float]], list[float], bool]:
    """([(first pitch, last pitch)] per half-inning in wall seconds, [pitching change
    times], whether the game is over)."""
    halves: dict[tuple, list[float]] = {}
    subs = []
    plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
    for p in plays:
        a = p.get("about", {})
        key = (a.get("inning"), a.get("halfInning"))
        for e in p.get("playEvents", []):
            d = e.get("details", {})
            if d.get("eventType") == "pitching_substitution" or "Pitching Change" in (d.get("description") or ""):
                if e.get("startTime"):
                    subs.append(_ts(e["startTime"]))
            if e.get("isPitch") and e.get("startTime"):
                f = _ts(e["startTime"])
                l = _ts(e.get("endTime") or e["startTime"])
                h = halves.setdefault(key, [f, l])
                h[0], h[1] = min(h[0], f), max(h[1], l)
    state = feed.get("gameData", {}).get("status", {}).get("abstractGameState")
    return sorted((f, l) for f, l in halves.values()), sorted(subs), state == "Final"


class Gate:
    """gate(t) for t on some clock: ``offset`` maps it to wall time (wall = t + offset)."""

    def __init__(self, halves, subs, final=False, offset: float = 0.0, live_now=None):
        self.halves, self.subs, self.final, self.offset = halves, subs, final, offset
        self.live_now = live_now            # the half in progress: its first pitch (wall), if any

    def __call__(self, t: float):
        w = t + self.offset
        i = bisect.bisect_left(self.subs, w - SUB_AFTER)
        if i < len(self.subs) and self.subs[i] <= w + SUB_BEFORE:
            return "break"
        if not self.halves:
            return None
        if w < self.halves[0][0]:
            return None
        for f, l in self.halves:
            if f + LIVE_AFTER <= w <= l:
                return "live"
        if self.live_now is not None and w >= self.live_now + LIVE_AFTER:
            return "live"                   # a half in progress (its last pitch is still to come)
        if self.final and w > self.halves[-1][1]:
            return None
        return "break"

    @classmethod
    def from_feed(cls, feed: dict, offset: float = 0.0) -> "Gate":
        halves, subs, final = halves_from_feed(feed)
        live_now = None
        if not final and halves:
            ls = feed.get("liveData", {}).get("linescore", {})
            if ls.get("inningState") in ("Top", "Bottom") and ls.get("outs", 0) < 3:
                live_now = halves[-1][0]    # the latest half is still going on
                halves = halves[:-1]
        return cls(halves, subs, final, offset, live_now)


class LiveGate:
    """Polls the feed for one game every ``every`` seconds on its own thread.
    Answers on the wall clock (gate(time.time() - broadcast delay))."""

    def __init__(self, game_pk: int, every: float = 5.0, timeout: float = 4.0):
        self.pk, self.every, self.timeout = game_pk, every, timeout
        self.gate: Gate | None = None
        self.error = None
        self.updated = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"admute-gate-{game_pk}", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                req = urllib.request.Request(FEED.format(pk=self.pk), headers={"User-Agent": "VizelVision/0.2"})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    self.gate = Gate.from_feed(json.load(r))
                self.updated, self.error = time.time(), None
            except Exception as exc:          # an outage changes nothing: the gate goes quiet
                self.error = str(exc)
            self._stop.wait(self.every)

    def __call__(self, wall: float):
        if self.gate is None or time.time() - self.updated > 60:
            return None
        return self.gate(wall)

    def stop(self):
        self._stop.set()
