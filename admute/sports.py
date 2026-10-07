"""The sports-feed gate: while play is live, nothing gets muted.

A broadcast only goes to break between half-innings or for a pitching change (or
an injury, a review...). MLB's live feed says when each half-inning's first and
last pitches were, and when pitchers changed. ``Gate`` turns that into

  'live'   -- inside a half-inning, from LIVE_AFTER s after its first pitch to its
              last pitch, away from pitching changes, while pitches are coming (no
              more than GAP apart; with no later pitch yet, the last one no more than
              LIVE_TAIL ago): muting is not allowed, and a mute still running ends (the
              detector missed the return)
  'break'  -- between half-innings, or around a pitching change
  None     -- before the first pitch, after the last, a pause inside a half (a gap
              between pitches over GAP), no feed, or a feed gone stale (no pitch for
              STALE: no break is that long, so the feed is stuck or is another game's):
              no opinion

A pause inside a half-inning is no proof of play: TBS went to a break mid-inning on
2026-10-05 (bottom 6th) before the feed had any pitching change, and the gate, calling
it live, ended two mutes while the ads ran. Live, the gap is still open: the feed only
has the pitches so far. On 2026-10-07 (bottom 1st, TBS) the break for a pitching change
began 72 s after the last pitch and 9 s before the feed had the change, and a gate that
waited GAP for the next pitch held the first 14 s of ads audible. So a pitch more than
LIVE_TAIL overdue ends "live" (95% of pitches come within 51 s of the one before).
``realtime`` reads a finished feed as it stood at each moment, as the lab's replays should.

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
GAP = 90.0                 # seconds between pitches beyond which play has paused (pitching change, review, injury)
LIVE_TAIL = 45.0           # ... and, with no later pitch yet, since the last one
STALE = 360.0              # no pitch for this long (the longest break is ~4-5 min): the feed is not to be believed
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


def pitches_from_feed(feed: dict) -> list[float]:
    """Every pitch's time (wall seconds), sorted."""
    out = []
    for p in feed.get("liveData", {}).get("plays", {}).get("allPlays", []):
        for e in p.get("playEvents", []):
            if e.get("isPitch") and e.get("startTime"):
                out.append(_ts(e["startTime"]))
    return sorted(out)


def names_from_feed(feed: dict) -> list[str]:
    """The game's names, for Whisper's prompt: the teams, then who is in the lineups and
    has pitched, then the rest of both rosters."""
    data = feed.get("gameData", {})
    names = []
    for side in ("away", "home"):
        team = data.get("teams", {}).get(side, {})
        names += [team.get("name"), team.get("teamName")]
    players = data.get("players", {})
    box = feed.get("liveData", {}).get("boxscore", {}).get("teams", {})
    first = [pid for side in ("away", "home") for key in ("battingOrder", "pitchers")
             for pid in box.get(side, {}).get(key, [])]
    names += [players.get(f"ID{pid}", {}).get("fullName") for pid in first]
    names += [p.get("fullName") for p in players.values()]
    return [n for n in dict.fromkeys(names) if n]


class Gate:
    """gate(t) for t on some clock: ``offset`` maps it to wall time (wall = t + offset)."""

    def __init__(self, halves, subs, final=False, offset: float = 0.0, live_now=None, pitches=None,
                 realtime: bool = False):
        self.halves, self.subs, self.final, self.offset = halves, subs, final, offset
        self.live_now = live_now            # the half in progress: its first pitch (wall), if any
        self.pitches = pitches              # every pitch (wall), sorted; None: the halves alone decide
        self.realtime = realtime            # a finished feed read as it stood at w: nothing after w is known
        self._resumed = [p for i, p in enumerate(pitches or []) if not i or p - pitches[i - 1] > GAP]

    def _playing(self, w: float) -> bool:
        """Pitches are coming at w: the pitches either side of it are at most GAP apart (with
        no later pitch yet, the last one at most LIVE_TAIL before it), and since play resumed
        after a pause, LIVE_AFTER has passed (as at a half's first pitch, the broadcast is
        back before it)."""
        if self.pitches is None:
            return True
        j = bisect.bisect_right(self.pitches, w)
        if not j:
            return False
        before = self.pitches[j - 1]
        if j < len(self.pitches) and not self.realtime:
            if self.pitches[j] - before > GAP:
                return False
        elif w - before > LIVE_TAIL:
            return False
        k = bisect.bisect_right(self._resumed, before)
        return w >= self._resumed[k - 1] + LIVE_AFTER

    def __call__(self, t: float):
        w = t + self.offset
        if self.pitches and not self.final and w - self._last_pitch(w) > STALE:
            return None                     # stuck, or another game's: fail towards the detector alone
        i = bisect.bisect_left(self.subs, w - SUB_AFTER)
        if i < len(self.subs) and self.subs[i] <= w + (0.0 if self.realtime else SUB_BEFORE):
            return "break"
        if not self.halves:
            return None
        if w < self.halves[0][0]:
            return None
        for f, l in self.halves:
            if f + LIVE_AFTER <= w <= l:
                return "live" if self._playing(w) else None
        if self.live_now is not None and w >= self.live_now + LIVE_AFTER:
            return "live" if self._playing(w) else None     # a half in progress (its last pitch is still to come)
        if self.final and w > self.halves[-1][1]:
            return None
        return "break"

    def _last_pitch(self, w: float) -> float:
        if not self.realtime:
            return self.pitches[-1]
        j = bisect.bisect_right(self.pitches, w)
        return self.pitches[j - 1] if j else -float("inf")

    @classmethod
    def from_feed(cls, feed: dict, offset: float = 0.0, realtime: bool = False) -> "Gate":
        halves, subs, final = halves_from_feed(feed)
        live_now = None
        if not final and halves:
            ls = feed.get("liveData", {}).get("linescore", {})
            # The half the linescore is in is going on only once it has a pitch: it turns to
            # "Bottom 8, 0 outs" as soon as the top ends, and taking the top's pitches for
            # it said "live" through the break's ads (TBS, 2026-10-05 22:56).
            plays = feed.get("liveData", {}).get("plays", {}).get("allPlays", [])
            pitched = [p.get("about", {}) for p in plays
                       if any(e.get("isPitch") for e in p.get("playEvents", []))]
            last = pitched[-1] if pitched else {}
            if (ls.get("inningState") in ("Top", "Bottom") and ls.get("outs", 0) < 3
                    and last.get("inning") == ls.get("currentInning")
                    and (last.get("halfInning") or "").lower() == ls["inningState"].lower()):
                live_now = halves[-1][0]    # the latest half is still going on
                halves = halves[:-1]
        return cls(halves, subs, final, offset, live_now, pitches_from_feed(feed), realtime)


class LiveGate:
    """Polls the feed for one game every ``every`` seconds on its own thread.
    Answers on the wall clock (gate(time.time() - broadcast delay))."""

    def __init__(self, game_pk: int, every: float = 5.0, timeout: float = 4.0):
        self.pk, self.every, self.timeout = game_pk, every, timeout
        self.gate: Gate | None = None
        self.names: list[str] = []          # teams and players (names_from_feed)
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
                    feed = json.load(r)
                self.gate = Gate.from_feed(feed)
                self.names = names_from_feed(feed)
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
