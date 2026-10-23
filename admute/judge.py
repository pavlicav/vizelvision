"""The transcript judge (the new detector): Claude Haiku reads the last half minute of
what was said and calls the newest piece an ad or the programme.

Each chunk Whisper finishes (with words) goes to Anthropic's Messages API with the last
CONTEXT seconds of transcript, the newest piece marked, and what is on (an MLB or NFL
game, or the programme's title). The answer, P(ad) as 0-100, becomes ``llm_judge`` (its
logit) for the chunk's seconds. It is late evidence, like the words: seconds not yet
frozen are scored again when it arrives, and the detector waits for it at most
detector.TEXT_HOLD. Calls run on their own threads.

Lab (2026-10-07, lab.judge on the 14 labelled tapes, 1200 balanced chunks, this prompt):
Haiku 5.5 at medium effort AUC 0.978, low 0.965, no thinking 0.962; Luna (gpt-6-luna)
0.953-0.958. 1.3 s typical, 2.5 s at p95; about 660 calls and 6 cents an hour of TV.

Pictures (``llm_picture``): where the detector is unsure of the newest second (its
per-second logit within UNSURE) or a black frame went by in the last AFTER_BLACK seconds
(not in a muted break that still looks like one),
Haiku also gets the last three of the page's pictures (256x144, 2 s apart) and calls the
newest one an ad or the programme, at most once every PICTURE_EVERY seconds per input. A
new spot has no words for ~10 s after its black frame; its pictures are there at once.
On 32 frames from 2026-10-08 (TBS and NBC, labelled by eye) it got 26 of the 27 clear
ones right at low effort (medium no better): $0.00012 a call, 1.3 s typical, 2.4 s at p90.
The traces put the detector unsure in 5-24% of seconds: ~2-5 cents an hour.

Not every chunk is sent. Once the detector has the chunk's own words, a chunk whose
seconds it is already sure of without the judge (every second's logit at least SURE, one
way) is skipped: its seconds count as no evidence (the weights' mean, so the answer before
is not carried over them). On the 10/18-10/20 traces the judge never turned such a second
(0 of 18,844, 74% of the judged seconds); between 3 and 4 it turned 6 of 3,075.

It runs only when admute.json's ``judge`` is on, the running model has llm_judge (the
new one), and a key is found: ANTHROPIC_API_KEY in the environment, else in the keys
file (continuity's). Spending stops for the day at ``judge_budget`` dollars. The key is
never logged.
"""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("admute.judge")

FEATURE = "llm_judge"
MODEL = "claude-haiku-5-5"
EFFORT = "medium"
PRICE = (0.10, 0.50)        # $ per million tokens (input, output), Anthropic's list price
URL = "https://api.anthropic.com/v1/messages"
CONTEXT = 32.0              # seconds of transcript the judge sees
MAX_TOKENS = 2000           # thinking and the answer
TIMEOUT = 20.0
STALE = 15.0                # a chunk queued this long ago is skipped: its seconds have frozen
BACKLOG = 12                # chunks waiting at most (older ones are dropped)
THREADS = 3
SYSTEM = ("You watch a live US TV channel through its speech transcript (automatic, so expect errors). "
          "Decide whether the newest piece of speech belongs to an advertisement - a commercial, a promo for "
          "another show or the network, a station or news promo, a political ad - or to the programme itself "
          "(including its hosts, commentators, players and in-show segments). A sponsor mention or promo read "
          "by the programme's own commentators or host while the programme carries on (\"this drive brought to "
          "you by...\", \"presented by...\", \"stick around for...\") counts as the programme. "
          "Reply with only an integer from 0 to 100, where 0 means the newest piece is certainly the programme "
          "and 100 means it is certainly an advertisement.")
SURE = 4.0                  # a chunk the detector is this sure of without the judge is not sent
WAIT_WORDS = 3.0            # ... judged once the detector has its words, or after this long anyway
PICTURE = "llm_picture"
PICTURE_EFFORT = "low"
PICTURE_EVERY = 2           # seconds between asks, per input
UNSURE = 2.2                # |per-second logit| below this: unsure (P(ad) 0.1-0.9)
AFTER_BLACK = 10.0          # ... or this soon after a black frame (a new spot, not yet heard)
PICTURE_SYSTEM = ("You watch a live US TV channel through a few low-resolution frames, oldest first. Decide "
                  "whether the newest frame belongs to an advertisement - a commercial, a promo for another show "
                  "or the network, a station or news promo, a political ad - or to the programme itself (its live "
                  "action, studio, hosts, replays, in-show graphics and segments). A split screen that still shows "
                  "the programme, a sponsor's logo or \"presented by\" graphic over the programme's own pictures, and "
                  "a news tease from the programme's own anchors count as the programme. Reply with only an integer "
                  "from 0 to 100, where 0 means the newest frame is certainly the programme and 100 means it is "
                  "certainly an advertisement.")
SHOWS = {"mlb": "a live Major League Baseball game broadcast", "nfl": "a live NFL football broadcast",
         "nba": "a live NBA basketball broadcast", "wnba": "a live WNBA basketball broadcast"}


def show(game: dict | None, title: str | None) -> str:
    """What is on, as the prompt says it (the lab's wording for its sports)."""
    league = (game or {}).get("league")
    if league in SHOWS:
        return SHOWS[league]
    return f"the TV programme {title}" if title else "a US TV channel"


def prompt(chunks: list, i: int, what: str) -> str:
    """The user message for chunk i of [(t0, t1, words)]: the chunks of the last CONTEXT
    seconds, oldest first, times relative to the newest's end (lab.judge.prompt)."""
    t_end = chunks[i][1]
    lines = []
    for t0, t1, words in chunks:
        if t1 <= t_end - CONTEXT or t0 > chunks[i][0]:
            continue
        text = " ".join(w[2] for w in words).strip() or "(no speech)"
        mark = ">>> NEWEST: " if t0 == chunks[i][0] else ""
        lines.append(f"[{t0 - t_end:+.0f}s] {mark}{text}")
    return f"Programme: {what}.\nTranscript, oldest first:\n" + "\n".join(lines)


def picture_content(jpegs: list, what: str) -> list:
    """The user message for pictures (JPEG bytes, oldest first, PICTURE_EVERY s apart)."""
    blocks = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                           "data": base64.b64encode(j).decode()}} for j in jpegs]
    return blocks + [{"type": "text", "text": f"Programme: {what}.\nFrames {PICTURE_EVERY} s apart, oldest first; "
                                              "the last is now."}]


def parse(text: str) -> float:
    """P(ad) from the answer: its last number (a model that explains first ends with it)."""
    found = re.findall(r"\d+(?:\.\d+)?", text or "")
    return min(100.0, max(0.0, float(found[-1]))) / 100 if found else math.nan


def logit(p: float) -> float:
    p = min(0.99, max(0.01, p))
    return math.log(p / (1 - p))


def read_key(keys_file=None) -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key and keys_file:
        try:
            for line in Path(keys_file).read_text().splitlines():
                name, _, value = line.strip().removeprefix("export ").partition("=")
                if name.strip() == "ANTHROPIC_API_KEY":
                    key = value.strip().strip("\"'")
        except OSError:
            key = None
    return key or None


class Judge:
    """The calls, for every input: a queue, THREADS workers, the day's spend (kept in
    ``ledger`` across restarts) and the page's numbers."""

    def __init__(self, keys_file=None, ledger=None, opener=urllib.request.urlopen):
        self.keys_file, self.ledger, self.opener = keys_file, Path(ledger) if ledger else None, opener
        self.cond = threading.Condition()
        self.jobs: collections.deque = collections.deque()
        self.took = collections.deque(maxlen=200)
        self.error = None
        self.dropped = self.failed = 0
        self.day, self.usd, self.calls, self.pictures, self.skipped = self._today(), 0.0, 0, 0, 0
        if self.ledger and self.ledger.exists():
            try:
                d = json.loads(self.ledger.read_text())
                if d.get("day") == self.day:
                    self.usd, self.calls = float(d.get("usd", 0.0)), int(d.get("calls", 0))
                    self.pictures = int(d.get("pictures", 0))
                    self.skipped = int(d.get("skipped", 0))
            except (OSError, ValueError):
                pass

    @staticmethod
    def _today() -> str:
        return dt.date.today().isoformat()

    def _roll(self):
        if self._today() != self.day:
            self.day, self.usd, self.calls, self.pictures, self.skipped = self._today(), 0.0, 0, 0, 0

    def why_not(self, budget: float) -> str | None:
        """Why no call can be made now (None: they can)."""
        with self.cond:
            self._roll()
            if self.usd >= budget:
                return f"today's budget (${budget:.2f}) is spent"
        if read_key(self.keys_file) is None:
            return "no ANTHROPIC_API_KEY (environment or keys file)"
        return None

    def submit(self, done, chunks: list, i: int, what: str):
        """Judge chunk i of ``chunks`` (a copy); ``done(p)`` gets P(ad), or NaN on failure."""
        self._queue(done, SYSTEM, prompt(chunks, i, what), EFFORT)

    def skip(self):
        """A chunk not sent: the detector was sure without it (SURE)."""
        with self.cond:
            self._roll()
            self.skipped += 1

    def submit_picture(self, done, jpegs: list, what: str):
        """Judge the newest of these pictures (JPEG bytes, oldest first)."""
        self._queue(done, PICTURE_SYSTEM, picture_content(jpegs, what), PICTURE_EFFORT)

    def _queue(self, done, system, content, effort):
        with self.cond:
            self.jobs.append((time.monotonic(), done, system, content, effort))
            while len(self.jobs) > BACKLOG:
                self.jobs.popleft()[1](math.nan)
                self.dropped += 1
            self.cond.notify()

    def run(self, stopping: threading.Event):
        while not stopping.is_set():
            with self.cond:
                if not self.jobs:
                    self.cond.wait(1)
                    continue
                queued, done, system, content, effort = self.jobs.popleft()
            p = math.nan
            try:
                if time.monotonic() - queued > STALE:
                    with self.cond:
                        self.dropped += 1
                else:
                    p = self.ask(content, system, effort)
            except Exception as exc:          # a failed call costs the evidence, nothing else
                with self.cond:
                    self.failed += 1
                    self.error = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("judge call failed: %s", self.error)
            finally:
                done(p)

    def ask(self, user, system: str = SYSTEM, effort: str = EFFORT) -> float:
        key = read_key(self.keys_file)
        if key is None:
            raise RuntimeError("no key")
        body = {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system,
                "messages": [{"role": "user", "content": user}],
                "thinking": {"type": "adaptive"}, "output_config": {"effort": effort}}
        req = urllib.request.Request(URL, json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "x-api-key": key,
                                      "anthropic-version": "2023-06-01"})
        began = time.monotonic()
        try:
            with self.opener(req, timeout=TIMEOUT) as r:
                out = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read()[:200]!r}") from None
        took = time.monotonic() - began
        u = out.get("usage") or {}
        usd = (u.get("input_tokens", 0) * PRICE[0] + u.get("output_tokens", 0) * PRICE[1]) / 1e6
        text = "".join(b.get("text", "") for b in out.get("content") or [] if b.get("type") == "text")
        with self.cond:
            self._roll()
            self.usd += usd
            self.calls += 1
            self.pictures += system == PICTURE_SYSTEM
            self.took.append(took)
            self.error = None
            day, spent, calls, pictures, skipped = self.day, self.usd, self.calls, self.pictures, self.skipped
        if self.ledger:
            try:
                tmp = self.ledger.with_name("." + self.ledger.name + ".tmp")
                tmp.write_text(json.dumps({"day": day, "usd": round(spent, 6), "calls": calls, "pictures": pictures,
                                        "skipped": skipped}))
                os.replace(tmp, self.ledger)
            except OSError as exc:
                log.warning("cannot keep the judge's spend: %s", exc)
        return parse(text)

    def status(self, budget: float) -> dict:
        with self.cond:
            self._roll()
            took = sorted(self.took)
            out = {"model": MODEL, "effort": EFFORT, "calls_today": self.calls, "pictures_today": self.pictures, "skipped_today": self.skipped, "usd_today": round(self.usd, 6),
                   "budget": budget, "queued": len(self.jobs), "dropped": self.dropped, "failed": self.failed,
                   "error": self.error,
                   "ms_p50": round(1000 * took[len(took) // 2]) if took else None,
                   "ms_p95": round(1000 * took[int(0.95 * (len(took) - 1))]) if took else None}
        out["why_not"] = self.why_not(budget)
        return out
