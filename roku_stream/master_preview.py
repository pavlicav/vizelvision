"""Bounded same-origin access to the configured MediaMTX HLS path."""
from __future__ import annotations

import re
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode
from urllib.request import urlopen

from .errors import ConfigError
from .master import MasterStreamError


class MasterPreview:
    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, config, *, opener=urlopen):
        self.config, self.opener = config, opener
        self.readers = threading.BoundedSemaphore(6)

    def read(self, name, query=""):
        if not self.config.enabled:
            raise MasterStreamError("Master preview is disabled")
        # MediaMTX's playlists reference sibling files. Never accept paths,
        # absolute URLs, traversal, or encoded slashes from the request.
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}\.(?:m3u8|mp4|m4s|ts)", name):
            raise ConfigError("Unknown master media file")
        if len(query) > 512:
            raise ConfigError("Master media query is too long")
        try:
            params = parse_qsl(query, keep_blank_values=True, max_num_fields=8)
        except ValueError as exc:
            raise ConfigError("Too many master media query fields") from exc
        if any(k not in ("_HLS_msn", "_HLS_part", "_HLS_skip", "session", "mtx_session") or
               not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", v) for k, v in params):
            raise ConfigError("Unsupported master media query")
        if not self.readers.acquire(blocking=False):
            raise MasterStreamError("Master preview is busy; retry shortly")
        try:
            url = self.config.hls_url + name + ("?" + urlencode(params) if params else "")
            try:
                with self.opener(url, timeout=5) as response:
                    raw = response.read(self.MAX_BYTES + 1)
                if len(raw) > self.MAX_BYTES:
                    raise MasterStreamError("Master media exceeded the response limit")
                if name.endswith(".m3u8"):
                    if not raw.startswith(b"#EXTM3U"):
                        raise MasterStreamError("Master did not return an HLS playlist")
                    # MediaMTX declares version 10, which Roku rejects ("HLS playlist
                    # unsupported version"). Its non-low-latency playlists need only v7.
                    raw = re.sub(rb"^#EXT-X-VERSION:(?:[89]|\d{2,})$", b"#EXT-X-VERSION:7", raw, flags=re.M)
                    content_type = "application/vnd.apple.mpegurl"
                else:
                    content_type = "video/mp2t" if name.endswith(".ts") else "video/mp4"
                return raw, content_type
            except HTTPError as exc:
                exc.close()
                raise MasterStreamError("Master media is not ready", details={"http_status": exc.code}) from exc
            except (URLError, OSError) as exc:
                raise MasterStreamError("Master media is unavailable") from exc
        finally:
            self.readers.release()
