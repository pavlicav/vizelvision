"""Short-lived verified Roku selection shared by the web app and media worker."""
import json
import re
import time
from urllib.request import urlopen

from .errors import ConfigError
from .master import MasterStreamError


def selection_path(master):
    return master.socket_path.with_name('roku-selection.json')


# Sources played by navigating the shared Roku. NFL source channel IDs are
# ESPN game IDs, for Sunday Ticket or a Prime Video broadcast respectively.
ROKU_SOURCE_IDS = ('youtube-tv', 'mlb', 'sunday-ticket', 'thursday-night-football')


def roku_target(data):
    source, channel = data.get('source_id'), data.get('channel_id')
    if source not in ROKU_SOURCE_IDS or not isinstance(channel, str) or not channel or len(channel) > 200:
        raise ConfigError('Roku preparation requires a source and channel/game ID')
    if source != 'youtube-tv' and (not channel.isascii() or not channel.isdecimal() or int(channel) <= 0):
        raise ConfigError('Game channel_id must be a positive game ID')
    result = {'source_id': source, 'channel_id': channel}
    if data.get('date') is not None:
        from datetime import date
        value = data['date']
        try:
            if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
                raise ValueError()
            date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError('date must use YYYY-MM-DD format') from exc
        result['date'] = value
    return result


def contribution_status(config):
    url = config.feedback.contribution_url
    if not url:
        raise MasterStreamError('Shared Roku capture is not configured')
    endpoint = config.master.status_url.rsplit('/', 1)[0] + '/' + url.rsplit('/', 1)[1]
    try:
        with urlopen(endpoint, timeout=2) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('Oversized response')
        status = json.loads(raw)
        if not status.get('ready') or not {'H264', 'MPEG-4 Audio'}.issubset(status.get('tracks') or []):
            raise ValueError('Both contribution tracks are required')
        publisher = (status.get('source') or {}).get('id')
        if not isinstance(publisher, str) or not publisher:
            raise ValueError('Publisher identity missing')
        return publisher
    except (OSError, ValueError, TypeError) as exc:
        raise MasterStreamError('Roku audio/video contribution is not ready') from exc


class RokuLease:
    """Validate selection and publisher identity; never navigate or open a device."""
    lane = 'roku'

    def __init__(self, config, body, *, publisher_reader=None):
        self.config = config
        self.target = roku_target(body)
        self.generation = body.get('selection_id')
        if not isinstance(self.generation, str) or not self.generation:
            raise MasterStreamError('Roku must be verified by master control before preparation')
        self.publisher_reader = publisher_reader or (lambda: contribution_status(config))

    def check(self):
        try:
            with selection_path(self.config.master).open('rb') as handle:
                raw = handle.read(16385)
            if len(raw) > 16384:
                raise ValueError('Oversized selection')
            claim = json.loads(raw)
            expires = claim.get('expires_at')
            if (type(expires) not in (int, float) or not time.time() < expires <= time.time() + 10
                    or claim.get('selection_id') != self.generation or claim.get('target') != self.target):
                raise ValueError('Selection expired or changed')
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise MasterStreamError('Verified Roku selection expired or changed; prepare again') from exc
        if self.publisher_reader() != claim.get('contribution_id'):
            raise MasterStreamError('Roku capture restarted; prepare again')
        self.resolved_source = claim.get('resolved_source')
        return self.config.feedback.contribution_url

    def tune(self):
        self.check()

    def renew(self, *, force=False):
        self.check()

    def release(self):
        return True
