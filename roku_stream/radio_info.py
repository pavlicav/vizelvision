"""Cairo radio show and now-playing lines for the off-air card.

Polled on a background thread so a slow or absent station API never delays the
master worker. Lines expire when the station stops answering.
"""
from __future__ import annotations

from datetime import datetime
import json
import logging
import threading
import time
from urllib.request import urlopen

LINE_LIMIT = 64


def _fit(text):
    text = " ".join(str(text).split()).upper()
    return text if len(text) <= LINE_LIMIT else text[:LINE_LIMIT - 1].rstrip() + "…"


def describe(state, show):
    """Card lines for a Cairo /api/state snapshot and the current show name."""
    # Some clocks already end in SHOW ("MORNING SHOW"); don't say it twice.
    lines = [_fit(show if show.upper().rstrip().endswith("SHOW") else show + " SHOW")] if show else []
    now = state.get("now") or {}
    title, artist = (now.get("title") or "").strip(), (now.get("artist") or "").strip()
    kind = now.get("kind") or ""
    # Buffering placeholders ("SPOTIFY BUFFERING") are not program content.
    if title and "buffering" not in kind:
        if artist and kind in ("music", "spotify"):
            # Long credit lists would hide the title: keep the first credited artist.
            if len(f"{artist} — {title}") > LINE_LIMIT:
                artist = artist.split(",")[0].strip()
            title = f"{artist} — {title}"
        lines.append(_fit(title))
    return lines


class RadioInfo:
    INTERVAL = 5
    STALE_SECONDS = 30
    GRID_SECONDS = 600

    def __init__(self, base_url, *, opener=urlopen, clock=time.monotonic, local_now=datetime.now):
        self.base_url = base_url.rstrip("/")
        self.opener, self.clock, self.local_now = opener, clock, local_now
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = None
        self._lines, self._at = [], None
        self.shows = {}
        self.grid, self.grid_at = None, 0.

    def _get(self, path):
        with self.opener(self.base_url + path, timeout=3) as response:
            return json.loads(response.read(4 * 1024 * 1024))

    def show(self, state):
        # The log records the clock each item was scheduled under, which follows
        # overruns; the weekly grid covers items outside the log.
        log_id = (state.get("now") or {}).get("log_id")
        if log_id is not None:
            if log_id not in self.shows:
                self.shows = {entry.get("id"): entry.get("source_slot") for entry in self._get("/api/log").get("entries", [])}
                self.shows.setdefault(log_id, None)
            if self.shows[log_id]:
                return self.shows[log_id]
        if self.grid is None or self.clock() - self.grid_at > self.GRID_SECONDS:
            self.grid, self.grid_at = self._get("/api/grid"), self.clock()
        now = self.local_now()
        return next((cell.get("name") for cell in self.grid
                     if cell.get("dow") == now.weekday() and cell.get("hour") == now.hour), None)

    def refresh(self):
        state = self._get("/api/state")
        lines = describe(state, self.show(state))
        with self.lock:
            self._lines, self._at = lines, self.clock()

    def lines(self):
        with self.lock:
            fresh = self._at is not None and self.clock() - self._at < self.STALE_SECONDS
            return list(self._lines) if fresh else []

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.refresh()
            except Exception as exc:
                logging.getLogger(__name__).debug("Cairo radio info unavailable: %s", exc)
            self.stopping.wait(self.INTERVAL)

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name="radio-info", daemon=True)
            self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(5)
