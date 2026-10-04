"""Broadcast networks VizelVision can take from YouTube TV or over the air.

NBC, FOX, ABC, CBS and The CW reach VizelVision two ways: YouTube TV carries the
Washington stations through the Roku, and TV-Thing's antenna tunes the same stations
directly. A channel change on the Roku takes from 20 s to over 2 min; the antenna
tunes in a few seconds. So a queue entry for one of these networks on YouTube TV
(a channel, or an MLB game YouTube TV carries there) plays from YouTube TV when it
is ready by its release, and otherwise from the antenna. A target with
`'antenna': False` stays on YouTube TV, however long it takes.

Feed recovery (source_queue) also goes the other way: a station whose antenna feed keeps
failing goes back on from YouTube TV, and a game the antenna carries (the guide names its
teams, or sports.local_simulcast) goes back on from the antenna.
"""
from __future__ import annotations

import re
import time

from .errors import ChannelNotFoundError, RokuStreamError

# YouTube TV channel name -> the call sign of the Washington station carrying it on air.
NETWORKS = {'NBC': 'WRC', 'FOX': 'WTTG', 'ABC': 'WJLA', 'CBS': 'WUSA', 'The CW': 'WDCW'}
ANTENNA_SOURCE = 'tv-thing-digital'


def teams(title):
    """The two teams' last words in "Indianapolis Colts at Washington Commanders" (or "vs"),
    which a guide listing such as "NFL on CBS: Titans at Ravens" names; None otherwise."""
    sides = re.split(r'\s+(?:at|vs\.?|@)\s+', str(title or '').strip(), maxsplit=1, flags=re.IGNORECASE)
    if len(sides) != 2 or not all(side.split() for side in sides):
        return None
    return tuple(side.split()[-1].casefold() for side in sides)


def call_sign(name):
    """WTTG-DT, WRC-HD and "WUSA 9" are WTTG, WRC and WUSA."""
    return re.split(r'[-\s.]', str(name or '').strip())[0].upper()


def _order(number):
    return tuple(int(part) if part.isdigit() else 0 for part in number.split('.'))


def youtube_only(target):
    """The operator chose YouTube TV alone for this target."""
    return (target or {}).get('antenna') is False


class Networks:
    def __init__(self, config, tv):
        """tv is the read-only TvThingClient: its cached digital catalog names the stations."""
        self.config, self.tv = config, tv

    def network(self, channel):
        """The network a YouTube TV channel (name or alias) is, if the antenna also has it."""
        try:
            name = self.config.resolve_channel(str(channel or ''))[1].name
        except (ChannelNotFoundError, ValueError):
            return None
        return name if name in NETWORKS else None

    def _stations(self):
        """{call sign: TV-Thing digital channel}, the main channel of each station."""
        if self.tv is None or not self.tv.config.enabled:
            return {}
        try:
            items = self.tv.get('digital')['data']['items']
        except (RokuStreamError, KeyError, TypeError):
            return {}  # TV-Thing unreachable: YouTube TV waits as before.
        found = {}
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id']:
                continue
            sign, number = call_sign(item.get('name')), str(item.get('number') or '')
            # 5.1 over 5.2 (BUZZR): a station's subchannels carry other networks.
            if sign in NETWORKS.values() and (sign not in found or _order(number) < _order(found[sign]['number'])):
                found[sign] = {'source_id': ANTENNA_SOURCE, 'channel_id': item['id'], 'number': number,
                               'name': str(item.get('name') or sign)}
        return found

    def station(self, network):
        """TV-Thing's antenna channel for a network: {source_id, channel_id, number, name}, or None."""
        return self._stations().get(NETWORKS.get(network)) if network in NETWORKS else None

    def station_for(self, sign):
        """TV-Thing's antenna channel for a station's call sign (WTTG), or None."""
        return self._stations().get(call_sign(sign)) if sign else None

    def network_of(self, channel_id):
        """The YouTube TV channel carrying the same station as an antenna channel (WTTG's 5.1
        is FOX), when YouTube TV is configured with it; None otherwise."""
        sign = next((s for s, station in self._stations().items() if station['channel_id'] == channel_id), None)
        network = next((n for n, s in NETWORKS.items() if s == sign), None)
        return network if network and self.network(network) == network else None

    def carrying(self, title, now=None):
        """The antenna channel whose guide listing on air now names both teams of a game
        ("NFL on CBS: Tennessee Titans at Baltimore Ravens"), or None. Stations that send no
        listings (WTTG on 2026-10-04) are never found this way."""
        wanted = teams(title)
        if not wanted or self.tv is None or not self.tv.config.enabled:
            return None
        try:
            channels = self.tv.get('guide')['data']['channels']
        except (RokuStreamError, KeyError, TypeError):
            return None
        now = time.time() if now is None else now
        for channel in (channels.values() if isinstance(channels, dict) else ()):
            if not isinstance(channel, dict) or not isinstance(channel.get('id'), str):
                continue
            for event in channel.get('events') or ():
                try:
                    airing = event['start'] <= now < event['start'] + event['duration']
                except (KeyError, TypeError):
                    continue
                words = set(re.findall(r'\w+', str(event.get('title') or '').casefold()))
                if airing and all(team in words for team in wanted):
                    return {'source_id': ANTENNA_SOURCE, 'channel_id': channel['id'],
                            'number': str(channel.get('number') or ''), 'name': str(channel.get('name') or channel['id'])}
        return None

    def channel(self, target, game=None):
        """The YouTube TV channel a Roku target plays: its channel, or the channel YouTube TV
        carries its MLB game on (game is the resolved MLB game, with its preferred source)."""
        source = (target or {}).get('source_id')
        if source == 'youtube-tv':
            return target.get('channel_id')
        if source == 'mlb':
            preferred = (game or {}).get('preferred_source') or {}
            return preferred.get('channel') if preferred.get('provider') == 'youtube_tv' else None
        return None

    def antenna(self, target, game=None):
        """The station that takes over target when YouTube TV is not ready in time, or None."""
        if youtube_only(target):
            return None
        network = self.network(self.channel(target, game))
        return self.station(network) if network else None

    def listing(self):
        """Each network, its YouTube TV channel and its antenna station (None when TV-Thing
        does not list it), for the pages' source choices."""
        stations = self._stations()
        result = []
        for network, sign in NETWORKS.items():
            try:
                configured = self.config.resolve_channel(network)[1].name == network
            except (ChannelNotFoundError, ValueError):
                configured = False
            result.append({'network': network, 'call_sign': sign, 'youtube_tv': network if configured else None,
                           'antenna': stations.get(sign)})
        return result
