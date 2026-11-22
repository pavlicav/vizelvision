"""Broadcast networks VizelVision can take from YouTube TV or over the air.

NBC, FOX, ABC, CBS and The CW reach VizelVision two ways: YouTube TV carries them
through the Roku from its market's stations (Washington's again since 2026-11-07; Lansing's
WILX, WSYM, WLAJ and WLNS from 10-25 until then), and TV-Thing's antenna tunes Washington's directly. Their network programs are the same; their local news is
not, and nor are Sunday's regional NFL games, which only go from one to the other when
both markets carry the game (sports.markets). A channel change on the Roku takes from 20 s to over 2 min; the antenna
tunes in a few seconds. So a queue entry for one of these networks on YouTube TV
(a channel, or an MLB game YouTube TV carries there) plays from YouTube TV when it
is ready by its release, and otherwise from the antenna. A target with
`'antenna': False` stays on YouTube TV, however long it takes.

Feed recovery (source_queue) also goes the other way: a station whose antenna feed keeps
failing goes back on from YouTube TV, and a game the antenna carries (the guide names its
teams, or sports.local_simulcast) goes back on from the antenna.

Since 2026-11-22 a game on one of these networks is suggested over the air (Networks.over_air,
sports._suggest): Washington's station, or another market's (TV Thing's viviserv2 in Lansing)
for its own teams' regional games, unless TV Thing rates that station's reception below good.
"""
from __future__ import annotations

import re
import time

from .errors import ChannelNotFoundError, RokuStreamError

# YouTube TV channel name -> the call sign of the Washington station carrying it on air.
NETWORKS = {'NBC': 'WRC', 'FOX': 'WTTG', 'ABC': 'WJLA', 'CBS': 'WUSA', 'The CW': 'WDCW'}
# Networks only the antenna has, not YouTube TV -> their virtual channel on it (TV Thing's networks.json).
ANTENNA_ONLY = {'ION': '66.1'}
ANTENNA_SOURCE = 'tv-thing-digital'
# The antenna's own market: the Washington stations above. TV Thing's second node is in another
# (viviserv2, mid-Michigan since 2026-11-21); its tuner pool plays that market's channels over
# the relay, and the digital catalog lists them with their market (tv_thing.py). Its network
# stations by virtual channel, best first: Lansing's, then Flint-Saginaw's, which it also gets.
# Numbers, not call signs: their PSIP names are brands ("FOX 47").
HOME_MARKET = 'dc'
MARKET_STATIONS = {'lansing': {'NBC': ('10.1', '25.1'), 'CBS': ('6.1', '5.1'), 'FOX': ('47.1', '66.1'),
                               'ABC': ('53.1', '12.1')}}
MARKET_NAMES = {'dc': 'Washington', 'lansing': 'Lansing'}
# TV Thing's reception verdicts (its signal_health.py) a station is the antenna default with:
# 'fair' (10-30% of samples errored) and 'poor' stutter. None: not rated yet.
CLEAN_RECEPTION = (None, 'good')


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

    def _items(self, market=HOME_MARKET):
        """The digital catalog's channels of one market (the home one's: market 'dc', or none)."""
        if self.tv is None or not self.tv.config.enabled:
            return []
        try:
            items = self.tv.get('digital')['data']['items']
        except (RokuStreamError, KeyError, TypeError):
            return []  # TV-Thing unreachable: YouTube TV waits as before.
        return [item for item in (items if isinstance(items, list) else ()) if isinstance(item, dict)
                and isinstance(item.get('id'), str) and item['id'] and (item.get('market') or HOME_MARKET) == market]

    def _stations(self):
        """{call sign: TV-Thing digital channel}, the main channel of each station."""
        found = {}
        for item in self._items():
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

    def antenna_only(self, network):
        """TV-Thing's antenna channel for a network YouTube TV does not carry (ION):
        {source_id, channel_id, number, name}, or None. Its digital catalog names ION "ION", not WPXW."""
        number = ANTENNA_ONLY.get(str(network or '').strip().upper())
        if number is None:
            return None
        # The home market's: Lansing's 66.1 is FOX 66.
        for item in self._items():
            if str(item.get('number')) == number:
                return {'source_id': ANTENNA_SOURCE, 'channel_id': item['id'], 'number': number,
                        'name': str(item.get('name') or network)}
        return None

    def reception(self, market, rf_channel):
        """How TV Thing's tuners in a market play an RF channel: 'good', 'fair' or 'poor', the
        best of them; None when none has rated it yet or TV Thing does not answer."""
        if rf_channel is None or self.tv is None or not self.tv.config.enabled:
            return None
        try:
            tuners = self.tv.get('tuners')['data']['tuners']
        except (RokuStreamError, KeyError, TypeError):
            return None
        verdicts = {(t.get('health') or {}).get(str(rf_channel)) for t in tuners
                    if isinstance(t, dict) and t.get('market') == market and isinstance(t.get('health') or {}, dict)}
        return next((v for v in ('good', 'fair', 'poor') if v in verdicts), None)

    def over_air(self, network, market=HOME_MARKET):
        """A market's antenna station for a network (NBC, FOX, ABC, CBS, The CW), with how it is
        received: {source_id, channel_id, number, name, market, reception}, or None when the
        catalog has none. Another market's: its best-received in MARKET_STATIONS order."""
        if market == HOME_MARKET:
            station = self.station(network)
            items = [item for item in self._items() if station and item['id'] == station['channel_id']]
        else:
            numbers = MARKET_STATIONS.get(market, {}).get(network, ())
            listed = {str(item.get('number')): item for item in self._items(market)}
            items = [listed[n] for n in numbers if n in listed]
        found = [{'source_id': ANTENNA_SOURCE, 'channel_id': item['id'], 'number': str(item.get('number') or ''),
                  'name': str(item.get('name') or network), 'market': market,
                  'reception': self.reception(market, item.get('rf_channel'))} for item in items]
        return next((s for s in found if s['reception'] in CLEAN_RECEPTION), found[0] if found else None)

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
