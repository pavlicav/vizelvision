"""Roku targets: the sources played by putting the source Roku on a channel or game.

The Roku itself is TV Thing's Roku lane (tv_roku.py, tv_control.RokuLease).
"""
import re

from .errors import ConfigError


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
