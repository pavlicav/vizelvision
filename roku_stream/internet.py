"""Internet streams: live HLS from the web, as TV Thing relays them (its internet_streams.py).

TV Thing lists them in its source catalog (`lineup.internet`) and relays each at
`stream/internet/<id>/index.m3u8`, a URL that stays put while the upstream one and its
CDN token change underneath. Every stream TV Thing lists is offered, numbered as in its
lineup; nothing here names one, so a stream added to TV Thing's internet_streams.json airs
with no change here. Channel 29, Pentulive (Yle Areena's puppy cam), was the first, on
2026-10-23. A target is {"source_id": "internet", "channel_id": "<id>"}.

No tuner, lock or encoder is involved: the master decodes the relay as it decodes an
antenna channel's HLS, and any number of streams may be open at once, beside the
antenna and the Roku, like library files.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .errors import ConfigError
from .master import MasterStreamError

SOURCE_ID = 'internet'
_STREAM_ID = re.compile(r'[a-z0-9][a-z0-9-]{0,199}')
# The relay may look the stream up on its first request (Yle Areena's: its player API, then
# the playlist).
OPEN_TIMEOUT = 15


def internet_target(data):
    source, channel = data.get('source_id'), data.get('channel_id')
    if source != SOURCE_ID:
        raise ConfigError('Internet stream target requires source_id "internet"')
    if not isinstance(channel, str) or not _STREAM_ID.fullmatch(channel):
        raise ConfigError('Internet stream channel_id must be a TV-Thing stream ID')
    return {'source_id': SOURCE_ID, 'channel_id': channel}


def stream_url(base_url, channel_id):
    return f'{base_url}stream/internet/{channel_id}/index.m3u8'


class StreamLease:
    """A TV-Thing internet stream for the master worker: its relay URL, nothing to hold."""
    lane = 'internet'
    generation = None

    def __init__(self, client, target):
        self.client = client
        self.target = internet_target(target)
        self.url = stream_url(client.config.base_url, self.target['channel_id'])

    def tune(self):
        """Ask the relay once, so a stream that is not live says why (TV Thing's words)
        instead of the decoder timing out."""
        if not self.client.config.enabled:
            raise MasterStreamError('TV-Thing is disabled in the worker configuration')
        request = Request(self.url, headers={'Accept': 'application/vnd.apple.mpegurl'})
        try:
            with self.client.opener(request, timeout=OPEN_TIMEOUT) as response:
                head = response.read(64 * 1024)
        except HTTPError as exc:
            try:
                reason = json.loads(exc.read(64 * 1024)).get('error')
            except (OSError, ValueError, AttributeError):
                reason = None
            exc.close()
            reason = reason.get('message') if isinstance(reason, dict) else reason
            raise MasterStreamError(f'TV-Thing cannot play {self.target["channel_id"]}: {reason}'
                                    if isinstance(reason, str) and reason else
                                    f'TV-Thing cannot play {self.target["channel_id"]} (HTTP {exc.code})',
                                    details={'http_status': exc.code}) from exc
        except (URLError, OSError) as exc:
            raise MasterStreamError(f'TV-Thing internet stream failed ({type(exc).__name__})') from exc
        if not head.lstrip().startswith(b'#EXTM3U'):
            raise MasterStreamError(f'TV-Thing did not answer {self.target["channel_id"]} with HLS')

    def check(self):
        # The decoder notices a stream that stops; the queue's feed recovery puts it back on.
        return self.url

    def renew(self, *, force=False):
        pass

    def release(self):
        return True
