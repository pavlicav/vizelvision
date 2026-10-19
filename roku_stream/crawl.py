"""The crawl: a bar of scrolling text along the bottom of master output.

Three layers can use it, highest first:

1. Important: severe weather (EAS warnings for the watched area, NWS Severe or Extreme
   alerts that are immediate or expected) and the one manual important message. It
   runs continuously, over everything.
2. Override: the operator's message, continuously, until cleared or its end time.
3. Bulletins: the rotation (crawl_desk.py, in the web app) sends one segment at a time
   (transit, scores, …). A bulletin runs its passes and the bar slides away.

The worker owns layers 1 and 2, so emergency alerts air even if the web app is down.
Settings live in crawl.json beside production.json: the web app writes it, the worker
reads it every second. crawl_render.py draws the pixels.
"""
from __future__ import annotations

import copy
from datetime import date, datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .errors import ConfigError
from .sports import LEAGUES

# The rotation's segments: name, label box, default minutes between bulletins.
SEGMENTS = {
    'alerts': ('Weather alerts', 'WEATHER', 10),
    'transit': ('Metro and bus', 'METRO & BUS', 15),
    'dc_alerts': ('AlertDC', 'DC ALERTS', 30),
    'weather': ('Weather', 'WEATHER', 30),
    'scores': ('Scores', 'SCORES', 20),
    'coming_up': ('Coming up', 'COMING UP', 30),
    'cairo': ('Now on Cairo Radio', 'CAIRO RADIO', 15),
    'messages': ('Station messages', 'VIZELVISION', 20),
}
# What the rotation does in each context: always on, pop-ups, or quiet (important and
# override only; they are never held back).
CONTEXTS = {'program': 'Programs', 'game': 'Live games', 'off_air': 'Off-air card', 'ident': 'Station ID'}
MODES = ('always', 'popups', 'quiet')
DEFAULTS = {
    'eas': True,             # EAS alerts for the watched area
    'eas_tests': False,      # include required weekly/monthly tests (as rotation alerts)
    'eas_transcript': True,  # follow an EAS alert's summary with its spoken message
    'dismissed': [],         # EAS event IDs taken out of the crawl
    'nws': True,             # NWS alerts for the watched zones
    'nws_dismissed': [],     # NWS alert IDs taken out of the crawl
    'important': {'text': '', 'label': 'IMPORTANT', 'until': None},
    'override': {'text': '', 'label': '', 'style': 'station', 'until': None},
    'rules': {'program': 'popups', 'game': 'quiet', 'off_air': 'always', 'ident': 'quiet',
              'per_hour': 4, 'gap_minutes': 5},
    'segments': {key: {'enabled': True, 'every': every, 'changed_only': False}
                 for key, (_, _, every) in SEGMENTS.items()},
    'cycle_messages': True,  # one station message per bulletin, in turn
    'messages': [],
    'teams': [],             # followed teams until 2026-10-17; favorites.json has them now (favorites.py)
}
STYLES = ('station', 'urgent')
TEXT_LIMIT, LABEL_LIMIT, TAG_LIMIT, DISMISSED_LIMIT = 500, 24, 20, 50
MESSAGE_LIMIT, TEAM_LIMIT = 50, 80
# The decoder's own severity words, most urgent first.
SEVERITY_RANK = {'national': 0, 'warning': 1, 'watch': 2, 'advisory': 3, 'unknown': 4, 'test': 5}
# How an EAS encoder words the originator in its crawl.
ORIGINATORS = {'WXR': 'The National Weather Service', 'CIV': 'A civil authority',
               'EAS': 'A broadcast station or cable system', 'PEP': 'The Primary Entry Point System'}
TRANSCRIPT_LIMIT = 1500
DESCRIPTION_LIMIT = 700
# Names for the Crawl tab; the decoder names an alert's own areas.
AREA_NAMES = {'011001': 'District of Columbia', '000000': 'All of the United States'}
NWS_UA = 'VizelVision local station (crawl)'


def _line(value, name, limit, *, required=False):
    if (not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or (required and not value.strip())):
        raise ConfigError(f'{name} must be a single line of at most {limit} characters')
    return ' '.join(value.split())


def _when(value):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _until(value, name):
    if value is None:
        return None
    if _when(value) is None:
        raise ConfigError(f'{name} must be an ISO time or null')
    return _when(value).isoformat()


def _flag(value, name):
    if not isinstance(value, bool):
        raise ConfigError(f'{name} must be true or false')
    return value


def _clock_text(value, name):
    if value == '':
        return ''
    if not isinstance(value, str) or not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value):
        raise ConfigError(f'{name} must be HH:MM or empty')
    return value


def _day_text(value, name):
    if value == '':
        return ''
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError) as exc:
        raise ConfigError(f'{name} must be YYYY-MM-DD or empty') from exc


def _message(value):
    if not isinstance(value, dict) or not {'text'} <= set(value) <= {'id', 'text', 'tag', 'enabled', 'days', 'start',
                                                                       'end', 'from', 'until'}:
        raise ConfigError('A station message has text, and may have tag, enabled, days, start, end, from and until')
    days = value.get('days', list(range(7)))
    if (not isinstance(days, list) or not days or len(days) != len(set(days))
            or any(type(day) is not int or not 0 <= day <= 6 for day in days)):
        raise ConfigError('days must list weekdays 0 (Monday) to 6')
    ident = value.get('id') or os.urandom(6).hex()
    if not isinstance(ident, str) or not re.fullmatch(r'[0-9a-f]{6,32}', ident):
        raise ConfigError('A message id is 6 to 32 hex digits')
    return {'id': ident, 'text': _line(value['text'], 'A station message', 300, required=True),
            'tag': _line(value.get('tag', ''), 'A message tag', TAG_LIMIT).upper(),
            'enabled': _flag(value.get('enabled', True), 'enabled'), 'days': sorted(days),
            'start': _clock_text(value.get('start', ''), 'start'), 'end': _clock_text(value.get('end', ''), 'end'),
            'from': _day_text(value.get('from', ''), 'from'), 'until': _day_text(value.get('until', ''), 'until')}


def message_active(message, now):
    """A station message is on today, now, and within its dates. Local time of this host."""
    local = now.astimezone()
    day = local.date().isoformat()
    if not message['enabled'] or local.weekday() not in message['days']:
        return False
    if (message['from'] and day < message['from']) or (message['until'] and day > message['until']):
        return False
    clock = local.strftime('%H:%M')
    start, end = message['start'] or '00:00', message['end'] or '24:00'
    return start <= clock < end if start <= end else (clock >= start or clock < end)


def _atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.crawl-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class CrawlSettings:
    def __init__(self, master, *, lenient=False):
        self.path = Path(master.socket_path).with_name('crawl.json')
        self.lock = threading.Lock()
        # The worker reads leniently: keys a newer web app added are ignored, never a reason
        # to stop crawling severe weather.
        self.lenient = lenient

    @staticmethod
    def validate(value):
        if not isinstance(value, dict):
            raise ConfigError('Crawl settings must be an object')
        value = copy.deepcopy(value)
        # Before the rotation, the operator's message ran whenever no alert did: it is the override now.
        if {'message', 'label', 'style'} & set(value):
            old = {key: value.pop(key) for key in ('message', 'label', 'style') if key in value}
            value.setdefault('override', {'text': old.get('message', ''), 'label': old.get('label', ''),
                                          'style': old.get('style', 'station'), 'until': None})
        if not set(value) <= set(DEFAULTS):
            raise ConfigError('Crawl settings take ' + ', '.join(DEFAULTS))
        result = {**copy.deepcopy(DEFAULTS), **value}
        for flag in ('eas', 'eas_tests', 'eas_transcript', 'nws', 'cycle_messages'):
            _flag(result[flag], flag)
        if (not isinstance(result['dismissed'], list) or len(result['dismissed']) > DISMISSED_LIMIT
                or any(type(item) is not int for item in result['dismissed'])):
            raise ConfigError(f'dismissed must list at most {DISMISSED_LIMIT} EAS event IDs')
        if (not isinstance(result['nws_dismissed'], list) or len(result['nws_dismissed']) > DISMISSED_LIMIT
                or any(not isinstance(item, str) or len(item) > 200 for item in result['nws_dismissed'])):
            raise ConfigError(f'nws_dismissed must list at most {DISMISSED_LIMIT} NWS alert IDs')
        for layer in ('important', 'override'):
            given = result[layer]
            if not isinstance(given, dict) or not set(given) <= set(DEFAULTS[layer]):
                raise ConfigError(f'{layer} takes ' + ', '.join(DEFAULTS[layer]))
            given = {**DEFAULTS[layer], **given}
            given['text'] = _line(given['text'], f'The {layer} text', TEXT_LIMIT)
            given['label'] = _line(given['label'], f'The {layer} label', LABEL_LIMIT)
            given['until'] = _until(given['until'], f'{layer}.until')
            if layer == 'override' and given['style'] not in STYLES:
                raise ConfigError('The override style must be station or urgent')
            result[layer] = given
        rules = result['rules']
        if not isinstance(rules, dict) or not set(rules) <= set(DEFAULTS['rules']):
            raise ConfigError('rules take ' + ', '.join(DEFAULTS['rules']))
        rules = result['rules'] = {**DEFAULTS['rules'], **rules}
        for context in CONTEXTS:
            if rules[context] not in MODES:
                raise ConfigError(f'rules.{context} must be always, popups or quiet')
        for key, low, high in (('per_hour', 1, 60), ('gap_minutes', 0, 120)):
            if type(rules[key]) is not int or not low <= rules[key] <= high:
                raise ConfigError(f'rules.{key} must be a whole number from {low} to {high}')
        segments = result['segments']
        if not isinstance(segments, dict) or not set(segments) <= set(SEGMENTS):
            raise ConfigError('segments are ' + ', '.join(SEGMENTS))
        merged = {}
        for key in SEGMENTS:
            segment = segments.get(key, {})
            if not isinstance(segment, dict) or not set(segment) <= {'enabled', 'every', 'changed_only'}:
                raise ConfigError(f'segments.{key} takes enabled, every and changed_only')
            segment = {**DEFAULTS['segments'][key], **segment}
            _flag(segment['enabled'], f'segments.{key}.enabled')
            _flag(segment['changed_only'], f'segments.{key}.changed_only')
            if type(segment['every']) is not int or not 2 <= segment['every'] <= 240:
                raise ConfigError(f'segments.{key}.every must be 2 to 240 minutes')
            merged[key] = segment
        result['segments'] = merged
        if not isinstance(result['messages'], list) or len(result['messages']) > MESSAGE_LIMIT:
            raise ConfigError(f'messages must be a list of at most {MESSAGE_LIMIT}')
        result['messages'] = [_message(message) for message in result['messages']]
        if len({m['id'] for m in result['messages']}) != len(result['messages']):
            raise ConfigError('Message ids must be unique')
        teams = result['teams']
        if (not isinstance(teams, list) or len(teams) > TEAM_LIMIT or len(set(teams)) != len(teams)
                or any(not isinstance(team, str) or not re.fullmatch(r'[a-z]+:\d{1,8}', team)
                       or team.split(':')[0] not in LEAGUES for team in teams)):
            raise ConfigError(f'teams must list at most {TEAM_LIMIT} unique "league:id" teams')
        return result

    def read(self):
        try:
            value = json.loads(self.path.read_text())
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)
        if self.lenient and isinstance(value, dict):
            value = {key: given for key, given in value.items() if key in DEFAULTS or key in ('message', 'label', 'style')}
            if isinstance(value.get('segments'), dict):
                value['segments'] = {key: {k: v for k, v in options.items() if k in ('enabled', 'every', 'changed_only')}
                                     if isinstance(options, dict) else options
                                     for key, options in value['segments'].items() if key in SEGMENTS}
        return self.validate(value)

    def _write(self, value):
        _atomic_write(self.path, value)

    def update(self, changes):
        """Merges changed top-level settings (rules and segments key by key); dismissals
        change only through dismiss()."""
        if not isinstance(changes, dict) or {'dismissed', 'nws_dismissed'} & set(changes):
            raise ConfigError('Send changed crawl settings without dismissals; use the dismiss endpoint')
        with self.lock:
            value = self.read()
            for key, given in changes.items():
                if key in ('rules', 'segments') and isinstance(given, dict) and isinstance(value.get(key), dict):
                    for name, part in given.items():
                        current = value[key].get(name)
                        value[key][name] = {**current, **part} if isinstance(current, dict) and isinstance(part, dict) else part
                else:
                    value[key] = given
            value = self.validate(value)
            self._write(value)
        return value

    def dismiss(self, source, event_id, dismissed=True):
        key = {'eas': 'dismissed', 'nws': 'nws_dismissed'}.get(source)
        if (key is None or not isinstance(dismissed, bool)
                or (source == 'eas' and type(event_id) is not int) or (source == 'nws' and not isinstance(event_id, str))):
            raise ConfigError('Dismiss takes source eas (integer id) or nws (string id), and dismissed true or false')
        with self.lock:
            value = self.read()
            ids = [item for item in value[key] if item != event_id]
            value[key] = (ids + [event_id] if dismissed else ids)[-DISMISSED_LIMIT:]
            self._write(value)
        return value


# Options for the rotation's feeds. They live in crawl-feeds.json, which only the web app
# reads, so changing what a feed fetches never needs the master worker restarted.
FEED_DEFAULTS = {
    'transit': {'rail': True, 'bus': True, 'routes': []},  # no routes: every bus route
    'weather': {'zip': '', 'place': '', 'latitude': None, 'longitude': None},  # no ZIP: config's station
    # Per segment: new items pop up at once (one pass, only the new ones); repeat on the
    # segment's timer (crawl.json's every); and the contexts it may air in at all.
    'segments': {key: {'new_now': key in ('alerts', 'dc_alerts'), 'repeat': True, 'contexts': list(CONTEXTS)}
                 for key in SEGMENTS},
}
ROUTE_LIMIT = 60


class FeedSettings:
    def __init__(self, master):
        self.path = Path(master.socket_path).with_name('crawl-feeds.json')
        self.lock = threading.Lock()

    @staticmethod
    def validate(value):
        if not isinstance(value, dict) or not set(value) <= set(FEED_DEFAULTS):
            raise ConfigError('Feed options are transit, weather and segments')
        result = copy.deepcopy(FEED_DEFAULTS)
        for name, given in value.items():
            if not isinstance(given, dict) or not set(given) <= set(FEED_DEFAULTS[name]):
                raise ConfigError(f'{name} takes ' + ', '.join(FEED_DEFAULTS[name]))
            if name == 'segments':
                for key, options in given.items():
                    if key not in SEGMENTS:
                        raise ConfigError('segments are ' + ', '.join(SEGMENTS))
                    if not isinstance(options, dict) or not set(options) <= {'new_now', 'repeat', 'contexts'}:
                        raise ConfigError(f'segments.{key} takes new_now, repeat and contexts')
                    result['segments'][key].update(options)
            else:
                result[name].update(given)
        for key, options in result['segments'].items():
            _flag(options['new_now'], f'segments.{key}.new_now')
            _flag(options['repeat'], f'segments.{key}.repeat')
            contexts = options['contexts']
            if (not isinstance(contexts, list) or not contexts or len(set(contexts)) != len(contexts)
                    or any(context not in CONTEXTS for context in contexts)):
                raise ConfigError(f'segments.{key}.contexts must list one or more of ' + ', '.join(CONTEXTS))
            options['contexts'] = [context for context in CONTEXTS if context in contexts]
        transit = result['transit']
        _flag(transit['rail'], 'transit.rail')
        _flag(transit['bus'], 'transit.bus')
        routes = transit['routes']
        if (not isinstance(routes, list) or len(routes) > ROUTE_LIMIT
                or any(not isinstance(r, str) or not re.fullmatch(r'[A-Za-z0-9]{1,6}', r) for r in routes)):
            raise ConfigError(f'transit.routes must list up to {ROUTE_LIMIT} bus routes such as D60')
        transit['routes'] = list(dict.fromkeys(route.upper() for route in routes))
        weather = result['weather']
        if not isinstance(weather['zip'], str) or not re.fullmatch(r'(\d{5})?', weather['zip']):
            raise ConfigError('weather.zip must be a five-digit ZIP code, or empty for the default station')
        weather['place'] = _line(weather['place'], 'weather.place', 60)
        for key, limit in (('latitude', 90), ('longitude', 180)):
            number = weather[key]
            if number is not None and (isinstance(number, bool) or not isinstance(number, (int, float)) or abs(number) > limit):
                raise ConfigError(f'weather.{key} must be a number or null')
        if weather['zip'] and (weather['latitude'] is None or weather['longitude'] is None):
            raise ConfigError('A weather ZIP needs its location; save it through the Crawl tab')
        return result

    def read(self):
        try:
            return self.validate(json.loads(self.path.read_text()))
        except FileNotFoundError:
            return copy.deepcopy(FEED_DEFAULTS)

    def save(self, value):
        value = self.validate(value)
        with self.lock:
            _atomic_write(self.path, value)
        return value


def layer_active(layer, now):
    return bool(layer['text']) and (layer['until'] is None or _when(layer['until']) > now)


# --------------------------------------------------------------------- EAS alerts

def covers(code, area):
    """A SAME PSSCCC location covers the area: the same county (any part of it), its
    whole state (county 000), or the whole country (000000)."""
    code = str(code)
    return code == '000000' or (len(code) == 6 and code[1:3] == area[1:3] and code[3:] in (area[3:], '000'))


def _clock(moment, now):
    """4:45 PM today; 11 AM Friday on another day. Local time of this host."""
    local, today = moment.astimezone(), now.astimezone()
    text = local.strftime('%-I:%M %p').replace(':00 ', ' ')
    return text if local.date() == today.date() else text + local.strftime(' %A')


def _article(words):
    return 'an' if words[:1].lower() in 'aeiou' else 'a'


def _cut(text, limit):
    text = ' '.join(str(text or '').split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind('. ')
    return cut[:end + 1] if end > limit // 2 else cut.rstrip() + '…'


def _transcript(event):
    return _cut(event.get('transcript'), TRANSCRIPT_LIMIT)


def describe(event, areas, now, transcript=True):
    """One EAS alert's crawl item: its event name, then the summary an EAS encoder would
    crawl, then (optionally) the decoder's transcript of the spoken message."""
    name = event.get('event_desc') or f"EAS {event.get('event_code', 'alert')}"
    who = ORIGINATORS.get(event.get('originator')) or (event.get('originator_desc') or 'An authority')
    places = [(item.get('code'), item.get('name')) for item in event.get('locations_detail') or []
              if item.get('name') and not item.get('marine')]
    if not places:
        places = list(zip(event.get('locations') or [], event.get('location_names') or []))
    # The watched area first: viewers look for their own name.
    places.sort(key=lambda place: not any(covers(place[0], area) for area in areas))
    summary = f'{who} has issued {_article(name)} {name}'
    if places:
        summary += ' for ' + '; '.join(dict.fromkeys(name for _, name in places))
    expires = _when(event.get('expires_utc'))
    if expires:
        summary += ' until ' + _clock(expires, now)
    item = {'tag': '', 'heading': name.upper(), 'text': summary + '.'}
    spoken = _transcript(event) if transcript else ''
    if spoken:
        item['text'] += ' ' + spoken
    return item


def active_alerts(events, areas, now, *, tests=False):
    """Decoded, unexpired events covering an area, most urgent first, then newest."""
    alerts = []
    for event in events:
        expires = _when(event.get('expires_utc'))
        severity = event.get('severity') or 'unknown'
        test = severity == 'test' or event.get('origin') == 'selftest'
        if (not event.get('valid') or expires is None or expires <= now or (test and not tests)
                or type(event.get('id')) is not int
                or not any(covers(code, area) for code in event.get('locations') or [] for area in areas)):
            continue
        alerts.append({**event, 'severity': 'test' if test else severity})
    alerts.sort(key=lambda e: (SEVERITY_RANK.get(e['severity'], 4), -(_when(e.get('issued_utc')) or now).timestamp()))
    return alerts


class _Poller:
    """Polls a feed on its own thread. An outage keeps what was last read, so an alert
    stays in the crawl until it expires even if its source stops answering."""
    INTERVAL = 5
    NAME = 'feed'

    def __init__(self, *, opener=urlopen, clock=time.time):
        self.opener, self.clock = opener, clock
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = None
        self.events, self.checked_at, self.error = [], None, None

    def fetch(self):
        raise NotImplementedError

    def refresh(self):
        try:
            events = self.fetch()
        except Exception as exc:
            with self.lock:
                self.error = f'{self.NAME} unavailable: {exc}'
            raise
        with self.lock:
            self.events = events
            self.checked_at, self.error = self.clock(), None

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.refresh()
            except Exception as exc:
                logging.getLogger(__name__).debug('%s unavailable: %s', self.NAME, exc)
            self.stopping.wait(self.INTERVAL)

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name=self.NAME, daemon=True)
            self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(5)


class EasAlerts(_Poller):
    """The EAS decoder's event log, every 5 s."""
    LIMIT = 100
    NAME = 'EAS decoder'

    def __init__(self, base_url, areas, **kwargs):
        super().__init__(**kwargs)
        self.base_url = base_url.rstrip('/')
        self.areas = tuple(areas)

    def fetch(self):
        with self.opener(f'{self.base_url}/api/events?valid=1&limit={self.LIMIT}', timeout=3) as response:
            events = json.loads(response.read(16 * 1024 * 1024))['events']
        if not isinstance(events, list):
            raise ValueError('events is not a list')
        return [event for event in events if isinstance(event, dict)]

    def alerts(self, *, tests=False):
        with self.lock:
            events = list(self.events)
        return active_alerts(events, self.areas, datetime.fromtimestamp(self.clock(), timezone.utc), tests=tests)

    def status(self):
        with self.lock:
            return {'url': self.base_url, 'areas': list(self.areas), 'checked_at': self.checked_at, 'error': self.error}


# --------------------------------------------------------------------- NWS alerts

def nws_alert(feature):
    """An active-alerts GeoJSON feature, normalized, or None if it is not a live alert."""
    p = feature.get('properties') if isinstance(feature, dict) else None
    if not isinstance(p, dict) or p.get('status') != 'Actual' or not isinstance(p.get('id'), str):
        return None
    headline = ((p.get('parameters') or {}).get('NWSheadline') or [None])[0] or p.get('headline') or ''
    return {'id': p['id'], 'event': str(p.get('event') or 'Weather alert'), 'severity': p.get('severity') or 'Unknown',
            'urgency': p.get('urgency') or 'Unknown', 'headline': str(headline),
            'description': str(p.get('description') or ''), 'sent': p.get('sent'),
            'expires': p.get('ends') or p.get('expires'), 'area': str(p.get('areaDesc') or ''),
            'sender': str(p.get('senderName') or 'NWS')}


def nws_important(alert):
    """Genuinely severe: warnings are Severe or Extreme and Immediate or Expected; watches are Future."""
    return alert['severity'] in ('Extreme', 'Severe') and alert['urgency'] in ('Immediate', 'Expected')


def nws_item(alert, now, *, long=True):
    headline = alert['headline'].strip().rstrip('.')
    text = (headline[:1].upper() + headline[1:].lower() if headline.isupper() else headline) or alert['event']
    expires = _when(alert.get('expires'))
    if expires and ' until ' not in text.lower():
        text += ' until ' + _clock(expires, now)
    text += '.'
    if long and alert['description']:
        # "HAZARD...60 mph wind gusts." reads as "Hazard: 60 mph wind gusts."
        body = re.sub(r'\b([A-Z][A-Z ]{2,})\.\.\.', lambda m: m.group(1).title() + ': ', alert['description'])
        text += ' ' + _cut(body.replace('...', ', '), DESCRIPTION_LIMIT)
    return {'tag': '', 'heading': alert['event'].upper(), 'text': text}


class NwsAlerts(_Poller):
    """api.weather.gov active alerts for the watched zones, every minute."""
    INTERVAL = 60
    NAME = 'NWS alerts'
    URL = 'https://api.weather.gov/alerts/active?zone={zones}'

    def __init__(self, zones, **kwargs):
        super().__init__(**kwargs)
        self.zones = tuple(zones)

    def fetch(self):
        request = Request(self.URL.format(zones=','.join(self.zones)),
                          headers={'User-Agent': NWS_UA, 'Accept': 'application/geo+json'})
        with self.opener(request, timeout=10) as response:
            features = json.loads(response.read(16 * 1024 * 1024)).get('features')
        if not isinstance(features, list):
            raise ValueError('features is not a list')
        return [alert for alert in map(nws_alert, features) if alert]

    def alerts(self):
        now = datetime.fromtimestamp(self.clock(), timezone.utc)
        with self.lock:
            alerts = list(self.events)
        return [alert for alert in alerts if (_when(alert['expires']) or now) > now or not alert['expires']]

    def status(self):
        with self.lock:
            return {'zones': list(self.zones), 'checked_at': self.checked_at, 'error': self.error}


# --------------------------------------------------------------------- layers

def alert_layers(settings, eas, nws, now, areas):
    """Splits the alerts into the important layer and the rotation's weather alerts.

    eas: active_alerts() output; nws: NwsAlerts.alerts(). Returns (important items,
    important label, rotation items, summaries) where summaries list every alert for
    the Crawl tab with its dismissal and where it runs. An NWS alert and the EAS alert
    for the same event are one alert: the NWS text runs (it is the official wording).
    """
    nws = nws if settings['nws'] else []
    nws_events = {alert['event'].casefold() for alert in nws}
    important, rotation, summaries, label = [], [], [], None
    for alert in nws:
        dismissed = alert['id'] in settings['nws_dismissed']
        severe = nws_important(alert)
        summaries.append({'source': 'nws', 'id': alert['id'], 'event': alert['event'], 'severity': alert['severity'],
                          'important': severe, 'dismissed': dismissed, 'issued': alert['sent'],
                          'expires': alert['expires'], 'areas': alert['area'], 'by': alert['sender']})
        if not dismissed:
            (important if severe else rotation).append(nws_item(alert, now, long=severe))
            label = label or ('WEATHER ALERT' if severe else None)
    for alert in eas if settings['eas'] else []:
        dismissed = alert['id'] in settings['dismissed']
        severe = alert['severity'] in ('national', 'warning')
        duplicate = alert.get('event_desc', '').casefold() in nws_events
        summaries.append({'source': 'eas', 'id': alert['id'], 'event': alert.get('event_desc') or alert.get('event_code'),
                          'severity': alert['severity'], 'important': severe, 'dismissed': dismissed,
                          'duplicate': duplicate, 'issued': alert.get('issued_utc'), 'expires': alert.get('expires_utc'),
                          'areas': '; '.join(alert.get('location_names') or []), 'by': alert.get('originator_desc')})
        if dismissed or duplicate:
            continue
        if severe:
            important.append(describe(alert, areas, now, settings['eas_transcript']))
            label = label or ('WEATHER ALERT' if alert.get('originator') == 'WXR' else 'EMERGENCY ALERT')
        else:
            rotation.append(describe(alert, areas, now, transcript=False))
    return important, label, rotation, summaries


def _key(kind, parts):
    return kind + '-' + hashlib.sha1('|'.join(parts).encode()).hexdigest()[:12]


def compose(settings, important_items, important_label, now):
    """The worker's own layers: important, else the override, else None (bulletins may run).

    The key names what runs: an alert by its event and summary's start, so its transcript
    arriving keeps the key (and follows the running pass), while a new alert or an edit
    changes it (and cuts in)."""
    manual = settings['important']
    if layer_active(manual, now):
        important_items = [{'tag': '', 'heading': '', 'text': manual['text']}] + important_items
        important_label = important_label or manual['label'].upper()
    if important_items:
        identity = [item['heading'] + ':' + (item['text'] if not item['heading'] else item['text'][:60])
                    for item in important_items]
        return {'kind': 'important', 'key': _key('important', identity), 'label': important_label or 'IMPORTANT',
                'style': 'warning', 'passes': 0, 'items': important_items}
    override = settings['override']
    if layer_active(override, now):
        return {'kind': 'override', 'key': _key('override', [override['text'], override['label'], override['style']]),
                'label': override['label'].upper(), 'style': override['style'], 'passes': 0,
                'items': [{'tag': '', 'heading': '', 'text': override['text']}]}
    return None


def validate_bulletin(value):
    """A bulletin from the rotation, as the worker accepts it."""
    if not isinstance(value, dict) or set(value) != {'key', 'label', 'style', 'passes', 'items', 'lease'}:
        raise ConfigError('A bulletin has key, label, style, passes, items and lease')
    if not isinstance(value['key'], str) or not re.fullmatch(r'[a-z0-9_-]{1,64}', value['key']):
        raise ConfigError('A bulletin key is up to 64 lowercase letters, digits, - and _')
    if value['style'] not in ('station', 'urgent', 'warning', 'watch', 'advisory', 'test'):
        raise ConfigError('Unknown bulletin style')
    if type(value['passes']) is not int or not 0 <= value['passes'] <= 5:
        raise ConfigError('passes must be 0 (until replaced) to 5')
    if type(value['lease']) is not int or not 5 <= value['lease'] <= 900:
        raise ConfigError('lease must be 5 to 900 seconds')
    items = value['items']
    if not isinstance(items, list) or not 1 <= len(items) <= 40:
        raise ConfigError('A bulletin has 1 to 40 items')
    clean = []
    for item in items:
        if not isinstance(item, dict) or not {'text'} <= set(item) <= {'tag', 'heading', 'text'}:
            raise ConfigError('A bulletin item has text, and may have tag and heading')
        clean.append({'tag': _line(item.get('tag', ''), 'A tag', TAG_LIMIT),
                      'heading': _line(item.get('heading', ''), 'A heading', 80),
                      'text': _line(item['text'], 'Bulletin text', 2000, required=True)})
    return {'kind': 'bulletin', 'key': value['key'], 'label': _line(value['label'], 'The label', LABEL_LIMIT),
            'style': value['style'], 'passes': value['passes'], 'items': clean, 'lease': value['lease']}


def plain(content):
    """The crawl as one line of text, for logs."""
    if not content:
        return ''
    return '  ◆  '.join(' '.join(filter(None, (item.get('tag'), item.get('heading'), item['text'])))
                        for item in content['items'])


def summary(event):
    """Kept for callers of the first version: an EAS alert as the Crawl tab listed it."""
    return {key: event.get(key) for key in ('id', 'event_code', 'event_desc', 'severity', 'originator_desc',
                                            'issued_utc', 'expires_utc', 'location_names', 'station')}


def valid_eas_url(value):
    parsed = urlsplit(value) if isinstance(value, str) else None
    return bool(parsed and parsed.scheme in ('http', 'https') and parsed.hostname
                and not parsed.username and not parsed.password)
