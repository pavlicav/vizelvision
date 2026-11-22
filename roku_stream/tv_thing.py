"""Read-only TV-Thing v1 client. Browsing never reserves or tunes a lane."""
from __future__ import annotations

import copy
import json
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import TvThingConfig
from .errors import RokuStreamError


class SourceUnavailableError(RokuStreamError):
    code = "source_unavailable"


@dataclass
class _Entry:
    data: dict | None = None
    fetched_at: float | None = None
    next_attempt: float = 0
    error: str | None = None


class TvThingClient:
    # Deliberate allowlist: some upstream GET endpoints scan/refresh hardware.
    _PATHS = {
        "sources": "api/v1/sources",
        "digital": "api/v1/sources/digital",
        "analog": "api/v1/sources/cable",
        "guide": "api/v1/guide?hours=24",
        # As far as the listings go (a day or two), for the schedule's lineup and discovery.
        "guide-long": "api/v1/guide?hours=168",
        "status": "api/v1/status",
        # The source Roku is TV Thing's Roku lane: its YouTube TV channels.
        "youtube-tv": "api/v1/sources/youtube-tv",
        # Every channel, whatever carries it: other markets' antenna channels for "digital".
        "channels": "api/v1/channels",
        # The tuner pool, with each tuner's reception verdict by RF channel (networks.reception).
        "tuners": "api/v1/tuners",
    }
    MAX_BYTES = 4 * 1024 * 1024

    def __init__(self, config: TvThingConfig, *, opener: Callable = urlopen,
                 clock: Callable = time.monotonic, wall_clock: Callable = time.time):
        self.config = config
        self._opener = opener
        self._clock = clock
        self._wall_clock = wall_clock
        self._cache: dict[str, _Entry] = {}
        self._locks = {key: threading.Lock() for key in self._PATHS}

    @staticmethod
    def _validate(key: str, data: object) -> dict:
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object")
        if key not in ("guide", "guide-long") and data.get("api_version") != "v1":
            raise ValueError("Unsupported or missing TV-Thing API version")
        field = {"sources": "sources", "digital": "items", "analog": "items",
                 "guide": "channels", "guide-long": "channels", "status": "lanes", "youtube-tv": "items",
                 "channels": "channels", "tuners": "tuners"}[key]
        expected = list if field in ("sources", "items") or key in ("channels", "tuners") else dict
        if not isinstance(data.get(field), expected):
            raise ValueError(f"Invalid {field} in TV-Thing response")
        if key in ("digital", "analog", "youtube-tv") and not isinstance(data.get("source"), dict):
            raise ValueError("Missing source metadata")
        return data

    def get(self, key: str) -> dict:
        found = self._get(key)
        return self._with_other_markets(found) if key == "digital" else found

    def _with_other_markets(self, found: dict) -> dict:
        """Another market's antenna channels, which TV Thing's tuner pool plays over the relay
        (viviserv2's Lansing ones since 2026-11-21). TV Thing's digital catalog lists them itself
        since 2026-11-22, each ``relayed`` with its market and node. Before that it listed only
        its own antenna's: they are taken from its channel list then, after them, in the same
        shape. Without the channel list the catalog is as it was."""
        items = found["data"]["items"]
        if any(isinstance(item, dict) and item.get("relayed") for item in items):
            return found
        try:
            rows = self._get("channels")["data"]["channels"]
        except SourceUnavailableError:
            return found
        have = {item.get("id") for item in items if isinstance(item, dict)}
        for row in rows:
            if not isinstance(row, dict) or row.get("source_id") != "digital" or not row.get("market"):
                continue
            channel_id = row.get("channel_id")
            if not isinstance(channel_id, str) or not channel_id or channel_id in have:
                continue
            detail = row.get("detail") if isinstance(row.get("detail"), dict) else {}
            items.append({"id": channel_id, "name": detail.get("source_name") or row.get("name"),
                          "number": detail.get("antenna_number"), "rf_channel": detail.get("rf_channel"),
                          "market": str(row["market"]), "node": row.get("node"), "tv_number": row.get("number"),
                          "tv_name": row.get("name"), "tv_section": row.get("section")})
            have.add(channel_id)
        return found

    def _get(self, key: str) -> dict:
        if not self.config.enabled:
            raise SourceUnavailableError("TV-Thing is not configured")
        if key not in self._PATHS:
            raise ValueError("Unsupported TV-Thing read operation")
        ttl = (self.config.guide_cache_seconds if key in ("guide", "guide-long") else
               2.0 if key == "status" else 60.0 if key == "tuners" else self.config.catalog_cache_seconds)
        # Per-endpoint lock coalesces simultaneous refreshes without serializing
        # guide/status/catalog requests behind one another.
        with self._locks[key]:
            entry = self._cache.setdefault(key, _Entry())
            now = self._clock()
            if now >= entry.next_attempt:
                request = Request(self.config.base_url + self._PATHS[key],
                                  headers={"Accept": "application/json", "User-Agent": "VizelVision/0.3"})
                try:
                    with self._opener(request, timeout=self.config.request_timeout_seconds) as response:
                        raw = response.read(self.MAX_BYTES + 1)
                    if len(raw) > self.MAX_BYTES:
                        raise ValueError("TV-Thing response exceeded 4 MiB")
                    data = self._validate(key, json.loads(raw))
                except (URLError, OSError, TimeoutError, ValueError) as exc:
                    # Do not expose response bodies, URLs or future credentials.
                    entry.error = f"TV-Thing {key} request failed ({type(exc).__name__})"
                    entry.next_attempt = self._clock() + self.config.retry_seconds
                else:
                    entry.data = data
                    entry.fetched_at = self._wall_clock()
                    entry.next_attempt = self._clock() + ttl
                    entry.error = None
            if entry.data is None:
                raise SourceUnavailableError(entry.error or "TV-Thing has no cached data")
            return {"data": copy.deepcopy(entry.data), "fetched_at": entry.fetched_at,
                    "stale": entry.error is not None, "error": entry.error}


class TvThingChannels:
    """YouTube TV's channels, as TV Thing's Roku lane lists them, in guide order.

    The last good list is kept on disk, so a TV Thing restart never empties the
    channels that queue entries, schedules and sports suggestions resolve.
    """

    def __init__(self, config: TvThingConfig, cache_path, *, client: TvThingClient | None = None):
        self.client = client or TvThingClient(config)
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._items = None

    def _load_cache(self):
        try:
            items = json.loads(self.cache_path.read_text())
            return items if isinstance(items, list) else []
        except (OSError, ValueError):
            return []

    def _current(self):
        with self._lock:
            try:
                items = [item for item in self.client.get("youtube-tv")["data"]["items"]
                         if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]]
            except SourceUnavailableError:
                if self._items is None:
                    self._items = self._load_cache()
                return self._items
            if items != self._items:
                self._items = items
                try:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = self.cache_path.with_suffix(".tmp")
                    temporary.write_text(json.dumps(items))
                    temporary.replace(self.cache_path)
                except OSError:
                    pass  # Only costs the fallback after a later outage.
            return self._items

    def channels(self):
        from .config import ChannelConfig
        return tuple(ChannelConfig(name=item["id"],
                                   aliases=tuple(a for a in item.get("aliases") or () if isinstance(a, str)),
                                   guide_index=item.get("guide_index") if isinstance(item.get("guide_index"), int)
                                   else index)
                     for index, item in enumerate(self._current()))

    def resolve(self, requested):
        from .config import normalize_channel_name
        from .errors import ChannelNotFoundError
        channels = self.channels()
        key = normalize_channel_name(str(requested))
        for index, channel in enumerate(channels):
            if key and key in {normalize_channel_name(name) for name in (channel.name, *channel.aliases)}:
                return index, channel
        raise ChannelNotFoundError(f"Unknown YouTube TV channel: {requested!r}",
                                   details={"available": [channel.name for channel in channels]})
