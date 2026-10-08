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

It runs only when admute.json's ``judge`` is on, the running model has llm_judge (the
new one), and a key is found: ANTHROPIC_API_KEY in the environment, else in the keys
file (continuity's). Spending stops for the day at ``judge_budget`` dollars. The key is
never logged.
"""
from __future__ import annotations

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
SHOWS = {"mlb": "a live Major League Baseball game broadcast", "nfl": "a live NFL football broadcast"}


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
        self.day, self.usd, self.calls = self._today(), 0.0, 0
        if self.ledger and self.ledger.exists():
            try:
                d = json.loads(self.ledger.read_text())
                if d.get("day") == self.day:
                    self.usd, self.calls = float(d.get("usd", 0.0)), int(d.get("calls", 0))
            except (OSError, ValueError):
                pass

    @staticmethod
    def _today() -> str:
        return dt.date.today().isoformat()

    def _roll(self):
        if self._today() != self.day:
            self.day, self.usd, self.calls = self._today(), 0.0, 0

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
        with self.cond:
            self.jobs.append((time.monotonic(), done, chunks, i, what))
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
                queued, done, chunks, i, what = self.jobs.popleft()
            p = math.nan
            try:
                if time.monotonic() - queued > STALE:
                    with self.cond:
                        self.dropped += 1
                else:
                    p = self.ask(prompt(chunks, i, what))
            except Exception as exc:          # a failed call costs the evidence, nothing else
                with self.cond:
                    self.failed += 1
                    self.error = f"{type(exc).__name__}: {exc}"[:300]
                log.warning("judge call failed: %s", self.error)
            finally:
                done(p)

    def ask(self, user: str) -> float:
        key = read_key(self.keys_file)
        if key is None:
            raise RuntimeError("no key")
        body = {"model": MODEL, "max_tokens": MAX_TOKENS, "system": SYSTEM,
                "messages": [{"role": "user", "content": user}],
                "thinking": {"type": "adaptive"}, "output_config": {"effort": EFFORT}}
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
            self.took.append(took)
            self.error = None
            day, spent, calls = self.day, self.usd, self.calls
        if self.ledger:
            try:
                tmp = self.ledger.with_name("." + self.ledger.name + ".tmp")
                tmp.write_text(json.dumps({"day": day, "usd": round(spent, 6), "calls": calls}))
                os.replace(tmp, self.ledger)
            except OSError as exc:
                log.warning("cannot keep the judge's spend: %s", exc)
        return parse(text)

    def status(self, budget: float) -> dict:
        with self.cond:
            self._roll()
            took = sorted(self.took)
            out = {"model": MODEL, "effort": EFFORT, "calls_today": self.calls, "usd_today": round(self.usd, 6),
                   "budget": budget, "queued": len(self.jobs), "dropped": self.dropped, "failed": self.failed,
                   "error": self.error,
                   "ms_p50": round(1000 * took[len(took) // 2]) if took else None,
                   "ms_p95": round(1000 * took[int(0.95 * (len(took) - 1))]) if took else None}
        out["why_not"] = self.why_not(budget)
        return out
