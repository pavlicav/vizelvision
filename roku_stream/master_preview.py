"""Bounded same-origin access to the configured MediaMTX HLS path."""
from __future__ import annotations

import ipaddress
import re
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode
from urllib.request import urlopen

from .errors import ConfigError
from .master import MasterStreamError

# MediaMTX keeps 30 one-second segments (deploy/mediamtx-master.yml) so that a viewer
# across the tailnet, such as TV Thing's viviserv2 in Michigan, whose segments take about a
# second each to arrive, never asks for one that has already gone. A Roku starts back in
# the window, so a long one is a delay for nearby viewers: those on this host or its LAN get
# the newest LOCAL_WINDOW segments, as MediaMTX served everyone before 2026-11-21.
LOCAL_WINDOW = 7
_TAILNET = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
# Tags that belong to the one segment they precede. (MAP and KEY carry on to the segments
# after it, so they stay.)
_SEGMENT_TAGS = (b"#EXTINF:", b"#EXT-X-PROGRAM-DATE-TIME:", b"#EXT-X-BYTERANGE:",
                 b"#EXT-X-GAP", b"#EXT-X-BITRATE:")


def nearby(client):
    """Whether ``client`` (an address) is on this host or its LAN: not the tailnet, not the internet."""
    try:
        address = ipaddress.ip_address(client)
    except (TypeError, ValueError):
        return False
    address = getattr(address, "ipv4_mapped", None) or address
    if any(address in network for network in _TAILNET):
        return False
    return address.is_loopback or address.is_private or address.is_link_local


def live_window(playlist, keep):
    """A media playlist with only its newest ``keep`` segments, its sequence numbers moved
    on to match. A multivariant, finished, low-latency or delta playlist comes back whole."""
    if b"#EXTINF:" not in playlist or re.search(rb"^#EXT-X-(?:PART|SKIP|ENDLIST)", playlist, re.M):
        return playlist
    lines = playlist.split(b"\n")
    uris = [index for index, line in enumerate(lines) if line.strip() and not line.startswith(b"#")]
    drop = len(uris) - keep
    if drop <= 0:
        return playlist
    cut, dropped, discontinuities = uris[drop - 1], set(uris[:drop]), 0
    for index in range(cut + 1):
        line = lines[index].rstrip(b"\r")
        if line.startswith(_SEGMENT_TAGS):
            dropped.add(index)
        elif line == b"#EXT-X-DISCONTINUITY":
            dropped.add(index)
            discontinuities += 1
    lines = [line for index, line in enumerate(lines) if index not in dropped]

    def advance(tag, by, after):
        for index, line in enumerate(lines):
            if line.startswith(tag):
                lines[index] = tag + str(int(line[len(tag):].strip()) + by).encode()
                return
        at = next((i + 1 for i, line in enumerate(lines) if line.startswith(after)), 1)
        lines.insert(at, tag + str(by).encode())

    advance(b"#EXT-X-MEDIA-SEQUENCE:", drop, b"#EXT-X-TARGETDURATION:")
    if discontinuities:
        advance(b"#EXT-X-DISCONTINUITY-SEQUENCE:", discontinuities, b"#EXT-X-MEDIA-SEQUENCE:")
    return b"\n".join(lines)


class MasterPreview:
    MAX_BYTES = 16 * 1024 * 1024

    def __init__(self, config, *, opener=urlopen):
        self.config, self.opener = config, opener
        self.readers = threading.BoundedSemaphore(6)

    def read(self, name, query="", client=None):
        """``(body, content type)`` of one master media file. ``client``: the asker's address;
        one nearby gets a short live window (LOCAL_WINDOW)."""
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
                    if nearby(client):
                        raw = live_window(raw, LOCAL_WINDOW)
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
