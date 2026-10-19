"""Feeds for the crawl's rotation (crawl_desk.py): each turns a public source into items.

An item is {tag, heading, text}: the tag is the small box in front of it (RED LINE,
BUS D50, NHL), the heading an optional highlighted lead. It also carries an id that
stays the same while the source means the same thing (rail:<incident>, score:nhl:<game>),
so the ledger (crawl_ledger.py) can tell a repeat from a first airing even when the words
change, and may carry issued/expires times for the Crawl page. The desk sends only tag,
heading and text to master. Every feed polls on its own
thread only while its segment is on, keeps what it last read through an outage, and
drops it once it is older than STALE seconds, so a dead feed goes quiet instead of
airing old delays.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from html import unescape
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .baseball import scoreline
from .favorites import matches
from .radio_info import RadioInfo

EASTERN = ZoneInfo('America/New_York')
UA = 'VizelVision local station (crawl)'


def _fit(text, limit):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= limit else text[:limit - 1].rsplit(' ', 1)[0] + '…'


def _hash(*parts):
    return hashlib.sha1('|'.join(str(part) for part in parts).encode()).hexdigest()[:10]


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat() if epoch else None


def read_key(name, keys_file):
    """An API key from the environment, else a KEY=value file. Never logged."""
    if os.environ.get(name):
        return os.environ[name]
    if keys_file:
        try:
            for line in Path(keys_file).read_text().splitlines():
                key, _, value = line.partition('=')
                if key.strip() == name and value.strip():
                    return value.strip().strip('"\'')
        except OSError:
            return None
    return None


class Feed:
    INTERVAL = 60
    STALE = 900
    LIMIT = 8

    def __init__(self, *, opener=urlopen, clock=time.time):
        self.opener, self.clock = opener, clock
        self.lock = threading.Lock()
        self.wanted = threading.Event()
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self._items, self.fetched_at, self.checked_at, self.error = [], None, None, None

    def fetch(self):
        raise NotImplementedError

    def _get(self, url, headers=None, limit=8 * 1024 * 1024):
        with self.opener(Request(url, headers={'User-Agent': UA, **(headers or {})}), timeout=10) as response:
            return response.read(limit)

    def refresh(self):
        try:
            items = self.fetch()[:self.LIMIT]
        except Exception as exc:
            with self.lock:
                self.checked_at, self.error = self.clock(), _fit(str(exc), 200)
            raise
        with self.lock:
            self._items, self.fetched_at, self.checked_at, self.error = items, self.clock(), self.clock(), None

    def items(self):
        with self.lock:
            fresh = self.fetched_at is not None and self.clock() - self.fetched_at < self.STALE
            return [dict(item) for item in self._items] if fresh else []

    def status(self):
        with self.lock:
            return {'checked_at': self.checked_at, 'fetched_at': self.fetched_at, 'error': self.error,
                    'running': self.wanted.is_set()}

    def want(self, wanted):
        (self.wanted.set if wanted else self.wanted.clear)()
        if wanted and self.thread is None:
            self.thread = threading.Thread(target=self._run, name=type(self).__name__, daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stopping.is_set():
            self.wanted.wait(5)
            if self.stopping.is_set() or not self.wanted.is_set():
                continue
            try:
                self.refresh()
            except Exception as exc:
                logging.getLogger(__name__).debug('%s unavailable: %s', type(self).__name__, exc)
            self.wake.wait(self.INTERVAL)
            self.wake.clear()

    def poke(self):
        """Fetch again now (its options changed)."""
        self.wake.set()

    def stop(self):
        self.stopping.set()
        self.wanted.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(5)


# --------------------------------------------------------------------- WMATA

def _varint(data, i):
    value = shift = 0
    while True:
        byte = data[i]
        i += 1
        value |= (byte & 0x7f) << shift
        if byte < 0x80:
            return value, i
        shift += 7


def protobuf_fields(data):
    """(field, value) pairs of one protobuf message: ints for varints, bytes otherwise."""
    i, fields = 0, []
    while i < len(data):
        key, i = _varint(data, i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = _varint(data, i)
        elif wire == 2:
            size, i = _varint(data, i)
            value, i = data[i:i + size], i + size
        elif wire == 1:
            value, i = data[i:i + 8], i + 8
        elif wire == 5:
            value, i = data[i:i + 4], i + 4
        else:
            raise ValueError(f'Unsupported protobuf wire type {wire}')
        fields.append((field, value))
    return fields


def _translated(data):
    texts = []
    for field, translation in protobuf_fields(data):
        if field == 1:
            parts = dict(protobuf_fields(translation))
            if parts.get(2, b'en').decode() in ('en', 'en-US'):
                texts.append(parts.get(1, b'').decode('utf-8', 'replace'))
    return texts[0] if texts else ''


def gtfs_alerts(data, now):
    """GTFS-realtime service alerts in effect now: [{routes, header, description}]."""
    alerts = []
    for field, entity in protobuf_fields(data):
        if field != 2:
            continue
        parts = protobuf_fields(entity)
        alert = next((value for number, value in parts if number == 5), None)
        if alert is None:
            continue
        ident = next((value for number, value in parts if number == 1), b'')
        ident = ident.decode('utf-8', 'replace') if isinstance(ident, bytes) else str(ident)
        periods, routes, header, description = [], [], '', ''
        for number, value in protobuf_fields(alert):
            if number == 1:
                period = dict(protobuf_fields(value))
                periods.append((period.get(1, 0), period.get(2, 0)))
            elif number == 5:
                route = dict(protobuf_fields(value)).get(2)
                if route:
                    routes.append(route.decode('utf-8', 'replace'))
            elif number == 10:
                header = _translated(value)
            elif number == 11:
                description = _translated(value)
        if periods and not any((start or 0) <= now and (not end or now < end) for start, end in periods):
            continue
        alerts.append({'id': ident, 'routes': list(dict.fromkeys(routes)), 'header': header, 'description': description,
                       'start': max((start for start, _ in periods), default=0),
                       'end': max((end for _, end in periods), default=0) if all(end for _, end in periods) else 0})
    return alerts


LINES = {'RD': 'RED', 'OR': 'ORANGE', 'SV': 'SILVER', 'BL': 'BLUE', 'YL': 'YELLOW', 'GR': 'GREEN'}


class TransitFeed(Feed):
    """WMATA: rail incidents, then bus service alerts (GTFS-realtime), newest first.

    Everything is fetched and kept; options() (crawl.FeedSettings' transit) chooses what
    shows: rail, bus, and which bus routes (none listed: every route), applied as items are
    read, so a change shows at once."""
    INTERVAL = 120
    LIMIT = 400
    SHOW = 8
    RAIL = 'https://api.wmata.com/Incidents.svc/json/Incidents'
    BUS = 'https://api.wmata.com/gtfs/bus-gtfsrt-alerts.pb'
    ROUTES = 'https://api.wmata.com/Bus.svc/json/jRoutes'

    def __init__(self, keys_file=None, options=None, **kwargs):
        super().__init__(**kwargs)
        self.keys_file = keys_file
        self.options = options or (lambda: {'rail': True, 'bus': True, 'routes': []})
        self._routes, self._routes_at = None, 0.

    def items(self):
        options = self.options()
        wanted = set(options['routes'])
        shown = []
        for item in super().items():
            kind, routes = item.pop('kind'), item.pop('routes')
            if kind == 'rail':
                if options['rail']:
                    shown.append(item)
            elif options['bus'] and (not wanted or wanted & set(routes)):
                # The routes you follow lead the tag: BUS D60/D6X.
                routes = sorted(routes, key=lambda route: route not in wanted)[:3]
                shown.append({**item, 'tag': _fit('BUS ' + '/'.join(routes) if routes else 'METROBUS', 20)})
        return shown[:self.SHOW]

    def routes(self):
        """WMATA's bus routes [{id, name}], for choosing which to show (cached a day)."""
        if self._routes is None or self.clock() - self._routes_at > 86400:
            key = read_key('WMATA_API_KEY', self.keys_file)
            if not key:
                raise ValueError('No WMATA_API_KEY in the environment or crawl.keys_file')
            routes = json.loads(self._get(self.ROUTES, {'api_key': key})).get('Routes') or []
            self._routes = [{'id': r['RouteID'], 'name': ' - '.join(str(r.get('Name') or '').split(' - ')[1:]) or r['RouteID']}
                            for r in routes if isinstance(r, dict) and r.get('RouteID')]
            self._routes_at = self.clock()
        return list(self._routes)

    def fetch(self):
        key = read_key('WMATA_API_KEY', self.keys_file)
        if not key:
            raise ValueError('No WMATA_API_KEY in the environment or crawl.keys_file')
        items = []
        rail = json.loads(self._get(self.RAIL, {'api_key': key})).get('Incidents') or []
        for incident in rail:
            codes = [code.strip() for code in str(incident.get('LinesAffected') or '').split(';') if code.strip()]
            names = [LINES.get(code, code) for code in codes]
            tag = (names[0] + ' LINE') if len(names) == 1 else '/'.join(names) + ' LINES' if names else 'METRORAIL'
            if len(tag) > 20:
                tag = '/'.join(codes) + ' LINES'  # OR/BL/SV LINES: the names do not fit the tag
            ident = incident.get('IncidentID') or _hash(incident.get('Description'))
            items.append({'tag': _fit(tag, 20), 'heading': '', 'text': _fit(incident.get('Description'), 300),
                          'id': f'rail:{ident}', 'issued': incident.get('DateUpdated'), 'kind': 'rail', 'routes': []})
        seen = set()
        bus = sorted(gtfs_alerts(self._get(self.BUS, {'api_key': key}), int(self.clock())), key=lambda a: -a['start'])
        for alert in bus:
            # The header is terse ("Reduced Service - P32"); the description says where and
            # why. A kind other than plain delays leads it.
            kind = alert['header'].split(' - ')[0].strip() if ' - ' in alert['header'] else ''
            text = alert['description'] or alert['header']
            if kind and alert['description'] and kind.casefold() not in ('delay', 'delays'):
                text = f'{kind}. {text}'
            text = _fit(text, 300)
            if not text or text in seen:
                continue
            seen.add(text)
            items.append({'tag': '', 'heading': '', 'text': text, 'id': 'bus:' + (alert['id'] or _hash(text)),
                          'issued': _iso(alert['start']), 'expires': _iso(alert['end']),
                          'kind': 'bus', 'routes': alert['routes']})
        return items


# --------------------------------------------------------------------- AlertDC

ROW = re.compile(r'<td[^>]*class="head"[^>]*>\s*([^<]+?)\s*</td>\s*<td[^>]*class="head"[^>]*>\s*<b>\s*<a[^>]*>(.*?)</a>'
                 r'\s*</b>\s*(?:<br\s*/?>)?(.*?)</td>', re.S)


def alertdc_rows(page):
    rows = []
    for when, title, body in ROW.findall(page):
        try:
            at = datetime.strptime(when.strip(), '%m/%d/%Y %I:%M %p').replace(tzinfo=EASTERN)
        except ValueError:
            continue
        clean = lambda text: ' '.join(unescape(re.sub(r'<[^>]+>', ' ', text)).replace('[AlertDC]', '').split())
        rows.append({'at': at, 'title': clean(title), 'body': clean(body)})
    return rows


class AlertDcFeed(Feed):
    """DC HSEMA's AlertDC list: road closures, events, government notices of the last day.

    Police crime alerts (suspect lookouts) are left out: they are not for a TV crawl."""
    INTERVAL = 300
    STALE = 3600
    LIMIT = 3
    URL = 'https://trainingtrack.hsema.dc.gov/NRss/RssFeed/AlertDCList'
    WITHIN = timedelta(hours=24)

    def fetch(self):
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        rows = [row for row in alertdc_rows(self._get(self.URL).decode('utf-8', 'replace'))
                if now - row['at'] < self.WITHIN and not row['title'].casefold().startswith('crime alert')]
        items = []
        for row in rows:
            body = row['body']
            first = re.split(r'(?<=[.!?])\s', body, maxsplit=2)
            items.append({'tag': 'ALERTDC', 'heading': '', 'text': _fit(row['title'] + ': ' + ' '.join(first[:2]), 300),
                          'id': 'alertdc:' + _hash(row['at'].isoformat(), row['title']), 'issued': row['at'].isoformat()})
        return items


# --------------------------------------------------------------------- weather

def lookup_zip(code, opener=urlopen):
    """A US ZIP code's place and location: {place, latitude, longitude} (Zippopotam.us)."""
    try:
        with opener(Request(f'https://api.zippopotam.us/us/{code}', headers={'User-Agent': UA}), timeout=10) as response:
            places = json.loads(response.read(1024 * 1024)).get('places') or []
    except HTTPError as exc:
        if exc.code == 404:
            raise ValueError(f'{code} is not a US ZIP code') from exc
        raise
    if not places:
        raise ValueError(f'{code} is not a US ZIP code')
    first = places[0]
    return {'place': f"{first['place name']}, {first['state abbreviation']}",
            'latitude': round(float(first['latitude']), 4), 'longitude': round(float(first['longitude']), 4)}


def station_name(name):
    """'Washington/Reagan National Airport, DC' reads 'Reagan National'."""
    name = re.sub(r',\s*[A-Z]{2}$', '', name.split('/')[-1].strip())
    return re.sub(r'\s+(International\s+)?Airport$', '', name).strip() or name


class WeatherFeed(Feed):
    """api.weather.gov: the latest observation and the next two forecast periods.

    With a ZIP in options() (crawl.FeedSettings' weather), the forecast is for that ZIP and
    the observation from the nearest station reporting; otherwise both come from the config."""
    INTERVAL = 600
    STALE = 3 * 3600

    def __init__(self, station='KDCA', point=(38.8951, -77.0364), place='Reagan National', options=None, **kwargs):
        super().__init__(**kwargs)
        self.station, self.point, self.place = station, point, place
        self.options = options or (lambda: {'zip': ''})
        self.resolved = None  # (where, forecast URL, [(station id, name)])
        # The latest reading as numbers, for the time-and-temperature promo (promos.py):
        # {f, c, place, station, observed_at}.
        self.observation = None

    def _json(self, url):
        return json.loads(self._get(url, {'Accept': 'application/geo+json'}))

    def where(self):
        weather = self.options()
        if weather.get('zip'):
            return weather['zip'], (weather['latitude'], weather['longitude']), weather['place']
        return '', self.point, self.place

    def status(self):
        code, _, place = self.where()
        stations = self.resolved[2] if self.resolved else []
        return {**super().status(), 'zip': code, 'place': place, 'station': stations[0][1] if stations else None}

    def fetch(self):
        code, point, _ = self.where()
        if self.resolved is None or self.resolved[0] != (code, point):
            properties = self._json('https://api.weather.gov/points/%.4f,%.4f' % point)['properties']
            stations = ([(f['properties']['stationIdentifier'], station_name(f['properties']['name']))
                         for f in self._json(properties['observationStations'])['features'][:3]]
                        if code else [(self.station, self.place)])
            self.resolved = ((code, point), properties['forecast'], stations)
        _, forecast, stations = self.resolved
        items = []
        for ident, name in stations:  # The nearest station that has reported a temperature.
            observed = self._json(f'https://api.weather.gov/stations/{ident}/observations/latest')['properties']
            celsius = (observed.get('temperature') or {}).get('value')
            if celsius is None:
                continue
            text = f'{name}: {observed.get("textDescription") or "Conditions"}, {round(celsius * 9 / 5 + 32)}°F'
            try:
                observed_at = datetime.fromisoformat(str(observed.get('timestamp'))).timestamp()
            except ValueError:
                observed_at = self.clock()
            self.observation = {'f': round(celsius * 9 / 5 + 32), 'c': round(celsius, 1), 'place': name,
                                'station': ident, 'observed_at': observed_at}
            wind = (observed.get('windSpeed') or {}).get('value')
            direction = (observed.get('windDirection') or {}).get('value')
            if wind:
                compass = 'N NE E SE S SW W NW'.split()[round((direction or 0) / 45) % 8] if direction is not None else ''
                text += f', wind {compass} {round(wind / 1.609)} mph'.replace('  ', ' ')
            items.append({'tag': 'NOW', 'heading': '', 'text': text + '.', 'id': 'weather:now'})
            break
        for period in self._json(forecast)['properties']['periods'][:2]:
            low = not period.get('isDaytime', True)
            name = str(period.get('name', ''))
            items.append({'tag': name.upper()[:20], 'heading': '',
                          'text': f'{period.get("shortForecast", "")}, {"low" if low else "high"} '
                                  f'{period.get("temperature")}°{period.get("temperatureUnit", "F")}.',
                          'id': 'weather:' + (re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-') or 'forecast')})
        return items


# --------------------------------------------------------------------- sports

# ESPN's short network labels, as viewers know them.
NETWORK_NAMES = {'USA Net': 'USA Network', 'NHL Net': 'NHL Network', 'NFL Net': 'NFL Network'}


def score_item(league, game, now):
    """A followed team's game: live score, final, or when and where it starts."""
    state = str(game.get('state') or '').casefold()
    away, home = game.get('away') or {}, game.get('home') or {}
    name = lambda team: team.get('nickname') or team.get('name') or '?'
    if state in ('in', 'live'):
        text = scoreline(game)
    elif state in ('post', 'final'):
        detail = game.get('detail') or 'Final'
        text = f'{detail}: {name(away)} {away.get("score")}, {name(home)} {home.get("score")}'
        if detail.casefold().startswith(('postponed', 'canceled', 'cancelled')):
            text = f'{name(away)} at {name(home)}: {detail}'
    else:
        try:
            start = datetime.fromisoformat(str(game.get('start_time')).replace('Z', '+00:00')).astimezone(EASTERN)
        except ValueError:
            start = None
        when = start.strftime('%-I:%M %p').replace(':00 ', ' ') if start else 'Time TBD'
        if start and start.date() != now.astimezone(EASTERN).date():
            when = start.strftime('%A ') + when
        networks = [NETWORK_NAMES.get(b['name'], b['name']) for b in game.get('broadcasts') or []
                    if b.get('market') in (None, 'national')][:2]
        text = f'{name(away)} at {name(home)}, {when}' + (' on ' + ' and '.join(networks) if networks else '')
    item = {'tag': league.upper(), 'heading': '', 'text': text}
    if game.get('game_id'):
        item['id'] = f'score:{league}:{game["game_id"]}'
    return item


class ScoresFeed(Feed):
    """Today's games (and last night's finals before 10 AM) for the favorites (favorites.py),
    from ESPN: their teams' and, for "league:playoffs", every postseason game. Live games
    first, each part by the best favorite's place on the list."""
    INTERVAL = 60
    STALE = 600
    LIMIT = 12

    def __init__(self, scoreboard, teams, **kwargs):
        super().__init__(**kwargs)
        self.scoreboard, self.teams = scoreboard, teams

    def fetch(self):
        order = list(self.teams())
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        today = now.astimezone(EASTERN)
        days = [today.date()] + ([today.date() - timedelta(days=1)] if today.hour < 10 else [])
        found = []
        for league in dict.fromkeys(f.partition(':')[0] for f in order):
            for day in days:
                for game in self.scoreboard.games(league, day.isoformat()):
                    sides = [str((game.get(side) or {}).get('id')) for side in ('away', 'home')]
                    places = [order.index(f) for f in matches(league, game, sides) if f in order]
                    if places:
                        live = str(game.get('state')).casefold() in ('in', 'live')
                        found.append((not live, min(places), score_item(league, game, now)))
        return [item for *_, item in sorted(found, key=lambda f: f[:2])]


# --------------------------------------------------------------------- station

class ComingUpFeed(Feed):
    """The next programs from the schedule projection (what will actually air), leaving out
    what carries on the program on air from another source: its game, anywhere ahead (a
    channel put on by hand, then the schedule's slot for the same game), or the same title
    right after it. game_on(target) is the game a channel carries now (a dict with game_pk
    and title), or None."""
    INTERVAL = 60
    STALE = 600
    LIMIT = 2

    def __init__(self, projector, game_on=None, **kwargs):
        super().__init__(**kwargs)
        self.projector, self.game_on = projector, game_on

    def _airing(self, segment):
        """What is on now, by (league, game) and by title."""
        games, titles = set(), {str(segment.get('title') or '').casefold()} - {''}
        game = segment.get('game') or None
        if not (game and game.get('game_pk') is not None) and self.game_on and segment.get('kind') not in ('off_air', 'recording'):
            try:
                game = self.game_on({k: v for k, v in (segment.get('target') or {}).items() if k in ('source_id', 'channel_id')})
            except Exception:  # Unknown: every later program is coming up.
                game = None
        if game and game.get('game_pk') is not None:
            games.add((game.get('league') or 'mlb', game['game_pk']))
            titles |= {str(game.get('title') or '').casefold()} - {''}
        return games, titles

    def fetch(self):
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        segments = self.projector.describe(now, now + timedelta(hours=12)).get('segments') or []
        games, titles = self._airing(segments[0]) if segments else (set(), set())
        items, carrying_on = [], True
        for segment in segments[1:]:
            game = segment.get('game') or {}
            if game.get('game_pk') is not None and ((game.get('league') or 'mlb'), game['game_pk']) in games:
                continue
            carrying_on = carrying_on and str(segment.get('title') or '').casefold() in titles
            if carrying_on:
                continue
            if segment.get('kind') in ('off_air', 'backup') or not segment.get('title'):
                continue
            start = datetime.fromisoformat(str(segment['start']).replace('Z', '+00:00')).astimezone(EASTERN)
            when = start.strftime('%-I:%M %p').replace(':00 ', ' ')
            if start.date() != now.astimezone(EASTERN).date():
                when = start.strftime('%A ') + when
            items.append({'tag': 'AT ' + when.upper(), 'heading': '', 'text': _fit(segment['title'], 120),
                          'id': 'coming:' + _hash(segment['start']), 'issued': None, 'expires': segment['start']})
        return items


class CairoFeed(Feed):
    """What Cairo Radio, the off-air audio, is playing (its public API, as the master card shows it)."""
    INTERVAL = 15
    STALE = 60
    LIMIT = 1

    def __init__(self, url, **kwargs):
        super().__init__(**kwargs)
        self.radio = RadioInfo(url) if url else None

    def fetch(self):
        if self.radio is None:
            raise ValueError('master.off_air_radio_info_url is not set')
        self.radio.refresh()
        lines = self.radio.lines()
        return [{'tag': 'NOW ON CAIRO RADIO', 'heading': '', 'text': ' · '.join(lines), 'id': 'cairo:now'}] if lines else []
