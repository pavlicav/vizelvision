"""Ads 5: a channel of nothing but ads, forked from VizelVision's breaks.

It plays My ads' library (the same few hundred ads, the same files) and the station's idents,
picked by the same selector as VizelVision's breaks (ad_mix.Mix, or my_ads.Rotation), but every
setting and every count is its own: which ads are on, their limits, the mix's tuning and shares,
the play log, the queue. Nothing done on Ads 5 reaches VizelVision's breaks, and nothing done
there reaches Ads 5, except the library itself: an ad uploaded, renamed, levelled or given a kind
on VizelVision's Ads page shows up here too (a new one switched on, with Ads 5's default limit).

    the format    an ident every `ident_every` minutes of ads (5 by default; 0: none), the 30 s
                  station ID every `station_id_every` minutes (30; 0: never), and an ident
                  first whenever someone tunes in (`open_with_ident`)
    the stream    one live HLS stream, made only while watched (as Trains is): nobody fetching
                  it for IDLE_SECONDS and it stops; the next viewer starts it again at once.
                  Clips are encoded ahead (ads5_prep.py) and joined as they air (ads5_ts.py),
                  so no encoder runs while it plays.
    the page      /ads5/: the channel, on air, Next up, the format, the library, the mix

Forking: on first start (or POST /ads5/v1/fork) Ads 5 copies VizelVision's settings as they
stand: each ad's switch and limit, the limits switch and default, the order (the mix if on), the
mix's tuning, shares, wear and boosts, each promo's switch and how often they air. From then on
they are separate files:

    state/ads5/settings.json   the format, the order, limits, each ad's and promo's own settings
    state/ads5/mix.json        the mix's tuning, each kind's share and wear, each ad's boost/wear
    state/ads5/plays.jsonl     what aired (rows as my-ads-plays.jsonl's, kinds ad, promo, id)
    state/ads5/queue.json      what was queued by hand
    state/ads5/clips/          the encoded clips (ads5_prep.py); state/ads5/live/ live-text promos

Read, never written: VizelVision's my-ads.json (the ads), my-ads-mix.json (the kinds and which
ad is which kind), promos-now.json (the temperature), ident/promos (the station promos) and the
station ID.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
import os
from pathlib import Path
import queue
import random
import re
import shutil
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlsplit

from . import ad_mix, ads5_prep, my_ads, promos as promos_mod
from .ads5_ts import CLOCK, WRAP, Splicer
from .errors import ConfigError

LOG = logging.getLogger('ads5')
ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / 'static'
PAGE = STATIC / 'ads5'
STATION_ID = ROOT / 'ident' / 'vizelvision-id.mp4'
NAME, NUMBER = 'Ads 5', 5

IDLE_SECONDS = 60          # nobody fetching the stream this long: it stops
PRIME_SEGMENTS = 2         # a start publishes this much at once, so the first viewer waits for nothing
WINDOW = 6                 # segments in the live playlist (12 s)
KEEP_SEGMENTS = 20         # segments kept for a slow player
NEXT_DRAWN = 6             # Next up's length, drawn ahead
MAX_QUEUED = 20
HISTORY = 40               # entries the status lists as aired
LIVE_RENDER_AHEAD = 75     # a live-text promo is drawn this long before it airs, or nearer
ORDERS = ('mix', 'shuffle', 'list')
IDENT_EVERY = (0, 120)
STATION_EVERY = (0, 240)

DEFAULTS = {
    'order': 'mix',               # mix (ad_mix), shuffle or list (my_ads.Rotation)
    'ident_every': 5,             # an ident after this many minutes of ads (0: no idents)
    'station_id_every': 30,       # the 30 s station ID this often (0: never)
    'open_with_ident': True,      # each time the channel starts (someone tunes in), an ident first
    'longest_ad': 0,              # ads longer than this (seconds) sit out (0: any length)
    'idents': True,               # station promos and idents at all
    'limits': True,               # hold each ad to its limit
    'limits_from': None,          # plays before this count towards no limit
    'default_limit': None,        # the limit an ad gets that VizelVision's library adds later
    'always_on': False,           # keep airing with nobody watching (counts plays nobody saw)
    'ads': {},                    # ad id: {enabled, limit, limits_from}
    'promos': {},                 # promo id: {enabled}
    'forked_at': None,
}
MIX_DEFAULTS = {'tuning': {}, 'kinds': {}, 'overrides': {}}


# ---------------------------------------------------------------- settings

def _int(value, lo, hi, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value) or not lo <= value <= hi:
        raise ConfigError(f'{name} is a whole number from {lo} to {hi}')
    return int(value)


def _since(value, name='limits_from'):
    if value is None:
        return None
    if value == 'now':
        return round(time.time(), 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ConfigError(f'{name} is a time (epoch seconds), "now" or null')
    return float(value)


def validate(value, *, lenient=False):
    if not isinstance(value, dict):
        raise ConfigError('Settings must be an object')
    if lenient:
        value = {k: v for k, v in value.items() if k in DEFAULTS}
    elif not set(value) <= set(DEFAULTS):
        raise ConfigError('Settings take ' + ', '.join(DEFAULTS))
    result = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(value)}

    def order(v):
        if v not in ORDERS:
            raise ConfigError('order is ' + ', '.join(ORDERS))
        return v

    def flag(key):
        def check(v):
            if not isinstance(v, bool):
                raise ConfigError(f'{key} must be true or false')
            return v
        return check

    checks = {'order': order,
              'ident_every': lambda v: _int(v, *IDENT_EVERY, 'ident_every (minutes)'),
              'station_id_every': lambda v: _int(v, *STATION_EVERY, 'station_id_every (minutes)'),
              'longest_ad': lambda v: _int(v, 0, my_ads.MAX_SECONDS, 'longest_ad (seconds)'),
              'limits_from': _since,
              'default_limit': lambda v: my_ads.validate_limit(v, 'default_limit'),
              'forked_at': lambda v: _since(v, 'forked_at'),
              **{k: flag(k) for k in ('open_with_ident', 'idents', 'limits', 'always_on')}}
    for key, check in checks.items():
        try:
            result[key] = check(result[key])
        except ConfigError:
            if not lenient:
                raise
            result[key] = copy.deepcopy(DEFAULTS[key])
    ads =result['ads'] if isinstance(result['ads'], dict) else {}
    checked = {}
    for ad_id, own in ads.items():
        if not isinstance(ad_id, str) or not re.fullmatch(r'[0-9a-f]{12}', ad_id) or not isinstance(own, dict):
            if lenient:
                continue
            raise ConfigError('ads maps an ad id to its settings')
        entry = {}
        try:
            if 'enabled' in own:
                if not isinstance(own['enabled'], bool):
                    raise ConfigError('enabled must be true or false')
                entry['enabled'] = own['enabled']
            if 'limit' in own:
                entry['limit'] = my_ads.validate_limit(own['limit'])
            if own.get('limits_from') is not None:
                entry['limits_from'] = _since(own['limits_from'])
        except ConfigError:
            if lenient:
                continue
            raise
        checked[ad_id] = entry
    result['ads'] = checked
    promos = result['promos'] if isinstance(result['promos'], dict) else {}
    result['promos'] = {k: {'enabled': v['enabled']} for k, v in promos.items()
                        if isinstance(k, str) and isinstance(v, dict) and isinstance(v.get('enabled'), bool)}
    return result


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.stem + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=1)
            stream.write('\n')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return copy.deepcopy(default)


class _Cached:
    """A JSON file read again only when it changes."""

    def __init__(self, path, default):
        self.path, self.default, self.stamp, self.value = Path(path), default, None, None

    def read(self):
        try:
            st = self.path.stat()
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
        except OSError:
            return copy.deepcopy(self.default)
        if stamp != self.stamp:
            self.value, self.stamp = _read_json(self.path, self.default), stamp
        return self.value


class Store:
    """Ads 5's own files, and what it reads of VizelVision's."""

    def __init__(self, state, vizelvision, promo_library=None):
        self.state, self.vv = Path(state), Path(vizelvision)
        self.state.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.state / 'settings.json'
        self.mix_path = self.state / 'mix.json'
        self.plays_path = self.state / 'plays.jsonl'
        self.queue_path = self.state / 'queue.json'
        self.clips = self.state / 'clips'
        self.live = self.state / 'live'
        self.lock = threading.RLock()
        self._vv_ads = _Cached(self.vv / 'my-ads.json', {'ads': []})
        self._vv_mix = ad_mix.MixStore(self.vv / 'master.sock', lenient=True)
        self._vv_promos = promos_mod.Promos(self.vv / 'master.sock', lenient=True, library=promo_library)
        self.tally = my_ads.PlayTally(self.plays_path, lambda r: f"{r.get('kind', 'ad')}:{r.get('id')}"
                                      if (r.get('counted') or my_ads.played(r)) else None)
        self._plays = (None, [])
        self._settings = _Cached(self.settings_path, DEFAULTS)
        self._settings_valid = (None, None)
        self._ads = (None, [])
        self._promos = (0., [])
        self._values = (0., {})
        if not self.settings_path.exists():
            self.fork()

    # ---- the fork
    def fork(self):
        """Copies VizelVision's settings as they stand (see the module doc); keeps the play log."""
        vv = self._vv_ads.read()
        vv_mix = self._vv_mix.read()
        vv_promos = self._vv_promos.read()
        order = vv.get('order', 'shuffle')
        settings = {
            'order': 'mix' if vv_mix.get('enabled') and order == 'shuffle' else (order if order in ORDERS else 'shuffle'),
            'ident_every': vv_promos.get('every') or 5,
            'idents': bool(vv_promos.get('enabled', True)),
            'limits': vv.get('limits', True) is not False,
            'default_limit': vv.get('default_limit'),
            'ads': {a['id']: {'enabled': bool(a.get('enabled', True)), 'limit': a.get('limit')}
                    for a in vv.get('ads', []) if isinstance(a, dict) and isinstance(a.get('id'), str)},
            'promos': copy.deepcopy(vv_promos.get('promos', {})),
            'forked_at': round(time.time(), 1),
        }
        old = _read_json(self.settings_path, {}) if self.settings_path.exists() else {}
        for key in ('station_id_every', 'open_with_ident', 'longest_ad', 'always_on'):
            if key in old:
                settings[key] = old[key]
        mix = {'tuning': dict(vv_mix['tuning']),
               'kinds': {c['key']: {'weight': c['weight'], 'wear': c['wear']} for c in vv_mix['categories']},
               'overrides': copy.deepcopy(vv_mix['overrides'])}
        with self.lock:
            _write_json(self.settings_path, validate(settings, lenient=True))
            _write_json(self.mix_path, mix)
        LOG.info('forked from VizelVision: %d ads, order %s', len(settings['ads']), settings['order'])

    # ---- settings
    def settings(self):
        """The settings (cached until the file changes; a copy each time)."""
        raw = self._settings.read()
        if self._settings_valid[0] is not raw:
            self._settings_valid = (raw, validate(raw, lenient=True))
        return copy.deepcopy(self._settings_valid[1])

    def update(self, changes):
        if not isinstance(changes, dict) or not changes:
            raise ConfigError('Send the settings to change')
        if set(changes) & {'ads', 'promos', 'forked_at'}:
            raise ConfigError('Set each ad or promo on its own')
        with self.lock:
            value = {**self.settings(), **changes}
            if 'limits_from' in changes:
                value['limits_from'] = _since(changes['limits_from'])
            value = validate(value)
            _write_json(self.settings_path, value)
            return value

    def set_ad(self, ad_id, changes):
        if not any(a['id'] == ad_id for a in self.vv_ads()):
            raise ConfigError('No such ad')
        if not isinstance(changes, dict) or not changes or not set(changes) <= {'enabled', 'limit', 'limits_from', 'boost', 'wear'}:
            raise ConfigError('An ad takes enabled, limit, limits_from, boost and wear')
        with self.lock:
            value = self.settings()
            own = value['ads'].setdefault(ad_id, {})
            for key in ('enabled', 'limit'):
                if key in changes:
                    own[key] = changes[key]
            if 'limits_from' in changes:
                own['limits_from'] = _since(changes['limits_from'])
            value = validate(value)
            if {'boost', 'wear'} & set(changes):
                self.change_mix({'overrides': {ad_id: {k: changes.get(k, self.mix_own()['overrides'].get(ad_id, {}).get(k, 1.))
                                                       for k in ('boost', 'wear')}}})
            _write_json(self.settings_path, value)
            return value

    def set_promo(self, promo_id, changes):
        if not any(p['id'] == promo_id for p in self.promo_library()):
            raise ConfigError('No such promo')
        if not isinstance(changes, dict) or set(changes) != {'enabled'} or not isinstance(changes['enabled'], bool):
            raise ConfigError('A promo takes enabled (true or false)')
        with self.lock:
            value = self.settings()
            value['promos'][promo_id] = {'enabled': changes['enabled']}
            _write_json(self.settings_path, value)
            return value

    # ---- the mix
    def mix_own(self):
        raw = _read_json(self.mix_path, MIX_DEFAULTS)
        return {k: raw.get(k) if isinstance(raw.get(k), dict) else {} for k in MIX_DEFAULTS}

    def mix(self):
        """The mix as ad_mix reads it: VizelVision's kinds (and which ad is which), with Ads 5's
        tuning, shares, wear and boosts."""
        vv = self._vv_mix.read()
        own = self.mix_own()
        cats = []
        for c in vv['categories']:
            mine = own['kinds'].get(c['key']) or {}
            cats.append({**c, 'weight': mine.get('weight', c['weight']), 'wear': mine.get('wear', c['wear'])})
        tuning = {**vv['tuning'], **own['tuning']}
        if 'unsorted' in own['kinds']:
            tuning['unsorted'] = own['kinds']['unsorted'].get('weight', tuning.get('unsorted', 1.))
        return ad_mix.validate({'enabled': True, 'tuning': tuning, 'categories': cats, 'ads': vv['ads'],
                                'overrides': own['overrides']}, lenient=True)

    def change_mix(self, changes):
        """{tuning: {key: value}, kinds: {key: {weight, wear}}, overrides: {ad id: {boost, wear} or null}}."""
        if not isinstance(changes, dict) or not set(changes) <= set(MIX_DEFAULTS):
            raise ConfigError('The mix takes tuning, kinds and overrides')
        with self.lock:
            own = self.mix_own()
            for key, value in (changes.get('tuning') or {}).items():
                if key not in ad_mix.TUNING:
                    raise ConfigError(f'No tuning {key!r}')
                _, lo, hi = ad_mix.TUNING[key]
                own['tuning'][key] = ad_mix._number(value, lo, hi, key)
            known = {c['key'] for c in self._vv_mix.read()['categories']} | {ad_mix.UNSORTED}
            for key, value in (changes.get('kinds') or {}).items():
                if key not in known or not isinstance(value, dict) or not set(value) <= {'weight', 'wear'}:
                    raise ConfigError(f'A kind ({key}) takes weight and wear')
                mine = own['kinds'].setdefault(key, {})
                if 'weight' in value:
                    mine['weight'] = ad_mix._number(value['weight'], *ad_mix.WEIGHT, 'A kind\'s share')
                if 'wear' in value:
                    mine['wear'] = ad_mix._number(value['wear'], *ad_mix.WEAR, 'A kind\'s wear')
            for ad_id, value in (changes.get('overrides') or {}).items():
                if value is None:
                    own['overrides'].pop(ad_id, None)
                    continue
                if not isinstance(value, dict) or not set(value) <= {'boost', 'wear'}:
                    raise ConfigError('An ad\'s own settings are boost and wear')
                mine = {'boost': ad_mix._number(value.get('boost', 1), *ad_mix.BOOST, 'An ad\'s boost'),
                        'wear': ad_mix._number(value.get('wear', 1), *ad_mix.WEAR, 'An ad\'s wear')}
                if mine == {'boost': 1., 'wear': 1.}:
                    own['overrides'].pop(ad_id, None)
                else:
                    own['overrides'][ad_id] = mine
            _write_json(self.mix_path, own)
            return own

    # ---- the library (VizelVision's)
    def vv_ads(self):
        raw = self._vv_ads.read()
        return [a for a in raw.get('ads', []) if isinstance(a, dict) and isinstance(a.get('id'), str)
                and isinstance(a.get('file'), str) and isinstance(a.get('duration'), (int, float))]

    def ad_file(self, ad):
        return self.vv / 'my-ads' / ad['file']

    def ads(self, settings=None):
        """VizelVision's ads, each with Ads 5's own switch, limit and reset. Cached while
        neither file changes: callers must not change what they get."""
        if settings is None:
            self.settings()
            key = (id(self._settings_valid[1]), id(self._vv_ads.read()))
            if self._ads[0] == key:
                return self._ads[1]
            out = self._merge_ads(self._settings_valid[1])
            self._ads = (key, out)
            return out
        return self._merge_ads(settings)

    def ad(self, ad_id):
        return next((a for a in self.ads() if a['id'] == ad_id), None)

    def _merge_ads(self, settings):
        out = []
        for a in self.vv_ads():
            own = settings['ads'].get(a['id'], {})
            out.append({'id': a['id'], 'name': a.get('name') or a['id'], 'file': a['file'], 'duration': float(a['duration']),
                        'level_db': float(a.get('gain_db') or 0) + float(a.get('trim_db') or 0),
                        'audio': a.get('audio', True) is not False, 'added': a.get('added'), 'pics': a.get('pics', 0),
                        'width': a.get('width'), 'height': a.get('height'),
                        'enabled': own.get('enabled', True),
                        'limit': own['limit'] if 'limit' in own else settings['default_limit'],
                        'limits_from': own.get('limits_from'),
                        'vv_enabled': bool(a.get('enabled', True))})
        return out

    def promo_library(self):
        """The station promos (re-read at most every 5 s)."""
        if time.monotonic() - self._promos[0] > 5:
            self._promos = (time.monotonic(), self._vv_promos.library.read())
        return self._promos[1]

    def promo_values(self):
        """The live values Ads 5's promos draw: VizelVision's temperature, and Ads 5 as the programme."""
        if time.monotonic() - self._values[0] > 5:
            values = dict(promos_mod.fresh(self._vv_promos.values()))
            values['programme'] = {'title': NAME, 'spoken': None, 'variants': {}}
            self._values = (time.monotonic(), values)
        return self._values[1]

    # ---- the play log and the queue
    def plays(self, days=8):
        """The play log's last days (cached until it grows)."""
        try:
            size = self.plays_path.stat().st_size
        except OSError:
            return []
        if self._plays[0] != size:
            self._plays = (size, my_ads.read_plays(self.plays_path, time.time() - days * 86400))
        return self._plays[1]

    def log(self, row):
        with self.lock:
            my_ads.append_play(self.plays_path, row)

    def queued(self):
        raw = _read_json(self.queue_path, [])
        return [q for q in raw if isinstance(q, dict) and q.get('kind') in ('ad', 'promo', 'id')
                and isinstance(q.get('id'), str)][:MAX_QUEUED] if isinstance(raw, list) else []

    def save_queue(self, entries):
        _write_json(self.queue_path, [{'kind': e['kind'], 'id': e['id']} for e in entries])


# ---------------------------------------------------------------- the clips

class Clips:
    """Which clips are encoded, and the workers that encode the rest (ads5_prep.encode): one for
    what is about to air, two for the library, all at the lowest priority."""

    def __init__(self, store, workers=2):
        self.store = store
        self.lock = threading.Lock()
        self.jobs = queue.PriorityQueue()
        self.pending = {}          # folder: priority queued at
        self.working = {}          # folder: (name, since)
        self.failed = {}           # folder: (message, at)
        self.ready = {}            # folder: meta
        self.seq = 0
        self.threads = [threading.Thread(target=self._work, args=(urgent,), daemon=True, name=f'ads5-prep-{i}')
                        for i, urgent in enumerate([True] + [False] * workers)]

    def start(self):
        for folder in (self.store.clips, self.store.live):
            folder.mkdir(parents=True, exist_ok=True)
            ads5_prep.clear_unfinished(folder)
        for t in self.threads:
            t.start()

    # what a clip is
    def spec(self, kind, item_id, *, start=None, ad=None):
        """{folder, src, duration, level_db, audio, overlay?, name} for an entry, or None (unknown)."""
        s = self.store
        if kind == 'ad':
            ad = ad or s.ad(item_id)
            path = s.ad_file(ad) if ad else None
            if not ad or not path.is_file():
                return None
            return {'folder': s.clips / ads5_prep.clip_key('ad', item_id, path, ad['level_db']), 'src': path,
                    'duration': ad['duration'], 'level_db': ad['level_db'], 'audio': ad['audio'], 'name': ad['name']}
        if kind == 'id':
            if not STATION_ID.is_file():
                return None
            return {'folder': s.clips / ads5_prep.clip_key('id', 'station', STATION_ID), 'src': STATION_ID,
                    'duration': 30.0, 'level_db': 0.0, 'audio': True, 'name': 'Station ID'}
        promo = next((p for p in s.promo_library() if p['id'] == item_id), None)
        if not promo or not promo.get('present'):
            return None
        src = s._vv_promos.library.folder / promo['file']
        spec = {'src': src, 'duration': promo['duration'], 'level_db': 0.0, 'audio': True, 'name': promo['name']}
        if promo['overlays']:
            if start is None:
                return {**spec, 'folder': None, 'live': True}
            spec['overlay'] = {'overlays': promo['overlays'], 'values': s.promo_values(), 'start': start,
                               'size': (ads5_prep.WIDTH, ads5_prep.HEIGHT)}
            spec['folder'] = s.live / f'{item_id}-{int(start)}'
            spec['live'] = True
            return spec
        spec['folder'] = s.clips / ads5_prep.clip_key('promo', item_id, src)
        return spec

    def meta(self, folder):
        if folder is None:
            return None
        key = str(folder)
        with self.lock:
            if key in self.ready:
                return self.ready[key]
        meta = ads5_prep.read_meta(folder)
        if meta:
            with self.lock:
                self.ready[key] = meta
        return meta

    def state(self, folder):
        key = str(folder)
        with self.lock:
            if key in self.ready:
                return 'ready'
            if key in self.working:
                return 'working'
            if key in self.failed:
                return 'failed'
            if key in self.pending:
                return 'queued'
        return 'ready' if self.meta(folder) else 'new'

    def want(self, spec, priority):
        """Asks for a clip (0: about to air … 9: the library, some day). Failed clips wait an hour."""
        folder = spec.get('folder')
        if folder is None or self.meta(folder):
            return
        key = str(folder)
        with self.lock:
            if key in self.working:
                return
            failed = self.failed.get(key)
            if failed and time.time() - failed[1] < 3600:
                return
            if key in self.pending and self.pending[key] <= priority:
                return
            self.pending[key] = priority
            self.seq += 1
            self.jobs.put((priority, self.seq, key, spec))

    def _work(self, urgent):
        while True:
            priority, _, key, spec = self.jobs.get()
            if urgent and priority > 1:          # the urgent worker leaves the library to the others
                self.jobs.put((priority, _, key, spec))
                time.sleep(0.5)
                continue
            with self.lock:
                if self.pending.get(key) != priority or key in self.working:
                    continue
                del self.pending[key]
                self.working[key] = (spec['name'], time.time())
            try:
                if not ads5_prep.read_meta(spec['folder']):
                    ads5_prep.encode(spec['src'], spec['folder'], duration=spec['duration'], level_db=spec['level_db'],
                                     audio=spec['audio'], overlay=spec.get('overlay'))
                meta = ads5_prep.read_meta(spec['folder'])
                with self.lock:
                    self.ready[key] = meta
                    self.failed.pop(key, None)
            except Exception as exc:   # noqa: BLE001 - a bad file never stops the others
                LOG.warning('could not encode %s: %s', spec['name'], exc)
                with self.lock:
                    self.failed[key] = (str(exc)[:300], time.time())
            finally:
                with self.lock:
                    self.working.pop(key, None)

    def summary(self):
        with self.lock:
            return {'working': [{'name': n, 'since': t} for n, t in self.working.values()],
                    'queued': len(self.pending), 'failed': len(self.failed)}

    def sweep_live(self, keep):
        """Deletes live-text renders no longer wanted (keep: folders still in use)."""
        keep = {str(k) for k in keep}
        for folder in self.store.live.glob('*'):
            if str(folder) not in keep and folder.is_dir() and time.time() - folder.stat().st_mtime > 120:
                shutil.rmtree(folder, ignore_errors=True)
                with self.lock:
                    self.ready.pop(str(folder), None)


# ---------------------------------------------------------------- the channel

def _uid():
    return os.urandom(4).hex()


class Channel:
    """The live stream and what it airs: on air, Next up, the play log (see the module doc)."""

    def __init__(self, store, clips, *, rng=None):
        self.store, self.clips = store, clips
        self.rng = rng or random.Random()
        self.lock = threading.RLock()
        self.mix = ad_mix.Mix(store.plays_path, self.rng)
        self.rotation = my_ads.Rotation(self.rng)
        self.promo_bag = []
        self.splicer = Splicer()
        self.running = False
        self.last_view = 0.
        self.started_at = None
        self.segments = []           # published: {seq, start, seconds, data, key}
        self.seq = 0
        self.clock = 0.              # wall time where the last published segment ends
        self.pts = 10 * CLOCK        # the next clip's first timestamp
        self.current = None          # {entry, meta, index, delta, start}
        self.next = []               # Next up: entries {key, kind, id, by, name, seconds, ...}
        self.history = []            # aired entries, newest last: {key, kind, id, name, by, start, end, ...}
        self.problem = None
        self.settings = store.settings()
        self.changed = 0
        for q in store.queued():
            entry = self._entry(q['kind'], q['id'], 'you')
            if entry:
                self.next.append(entry)

    # ---- entries
    def _entry(self, kind, item_id, by):
        spec = self.clips.spec(kind, item_id)
        if spec is None:
            return None
        entry = {'key': _uid(), 'kind': kind, 'id': item_id, 'by': by, 'name': spec['name'],
                 'seconds': float(spec['duration']), 'live': bool(spec.get('live'))}
        if not entry['live']:
            entry['folder'] = str(spec['folder'])
        return entry

    def _meta(self, entry):
        return self.clips.meta(Path(entry['folder'])) if entry.get('folder') else None

    # ---- the selector
    def _draw_rows(self):
        """The play log, plus what is on air and drawn ahead as plays at their projected times."""
        rows = list(self.store.plays())
        at = self.clock if self.running else time.time()
        if self.current:
            e = self.current['entry']
            rows.append({'kind': e['kind'], 'id': e['id'], 'at': self.current['start'], 'counted': True,
                         'seconds': e['seconds'], 'length': e['seconds']})
            at = self.current['start'] + self.current['meta']['seconds']
        for e in self.next:
            rows.append({'kind': e['kind'], 'id': e['id'], 'at': at, 'counted': True,
                         'seconds': e['seconds'], 'length': e['seconds']})
            at += e['seconds']
        return rows, at

    def _ad_settings(self, settings):
        ads = self.store.ads()
        longest = settings['longest_ad']
        return {'ads': [a for a in ads if not longest or a['duration'] <= longest] if longest else ads,
                'order': 'list' if settings['order'] == 'list' else 'shuffle',
                'limits': settings['limits'], 'limits_from': settings['limits_from']}

    def _pick_ad(self, settings, rows, at):
        ad_settings = self._ad_settings(settings)
        present = {a['id'] for a in ad_settings['ads'] if self.store.ad_file(a).is_file()}
        ad_settings['ads'] = [a for a in ad_settings['ads'] if a['id'] in present]
        drawn = {e['id'] for e in self.next if e['kind'] == 'ad'}
        if self.current and self.current['entry']['kind'] == 'ad':
            drawn.add(self.current['entry']['id'])
        unready = set()
        for a in ad_settings['ads']:
            spec = self.clips.spec('ad', a['id'], ad=a)
            if spec and not self.clips.meta(spec['folder']):
                unready.add(a['id'])
        mix = self.store.mix() if settings['order'] == 'mix' else None
        for skip in (drawn | unready, drawn, set()):
            if settings['order'] == 'mix':
                ad = self.mix.pick(ad_settings, rows, at, skip, mix)
            else:
                ad = self.rotation.pick(ad_settings, rows, at, skip)
            if ad:
                (self.mix if settings['order'] == 'mix' else self.rotation).played(ad['id'])
                return ad
        return None

    def promo_reasons(self, settings=None):
        """{promo id: why it cannot air on Ads 5 now, or None}."""
        settings = settings or self.settings
        values = self.store.promo_values()
        out = {}
        for p in self.store.promo_library():
            why = None
            if not promos_mod.switched_on(settings, p['id']):
                why = 'switched off on Ads 5'
            else:
                why = promos_mod.readiness(p, values)
            out[p['id']] = why
        return out

    def _pick_promo(self, settings, ready_only=False):
        reasons = self.promo_reasons(settings)
        ok = [i for i, why in reasons.items() if why is None]
        if ready_only:
            ok = [i for i in ok if (spec := self.clips.spec('promo', i)) and spec.get('folder')
                  and self.clips.meta(spec['folder'])]
            return self.rng.choice(ok) if ok else None
        if not ok:
            return None
        drawn = {e['id'] for e in self.next if e['kind'] == 'promo'}
        self.promo_bag = [i for i in self.promo_bag if i in ok and i not in drawn]
        if not self.promo_bag:
            self.promo_bag = [i for i in ok if i not in drawn] or list(ok)
            self.rng.shuffle(self.promo_bag)
        return self.promo_bag.pop(0)

    def _last(self, rows, kinds):
        return max((r['at'] for r in rows if r.get('kind') in kinds and (r.get('counted') or my_ads.played(r))),
                   default=None)

    def _fill(self):
        """Draws Next up out to NEXT_DRAWN: the station ID when due, an ident when due, an ad."""
        s = self.settings
        while sum(1 for e in self.next if e['by'] != 'you') < NEXT_DRAWN and len(self.next) < NEXT_DRAWN + MAX_QUEUED:
            rows, at = self._draw_rows()
            last_id = self._last(rows, ('id',))
            last_ident = self._last(rows, ('id', 'promo'))
            base = s['forked_at'] or at
            entry = None
            if s['station_id_every'] and at - (last_id or base) >= s['station_id_every'] * 60:
                entry = self._entry('id', 'station', 'clock')
            if entry is None and s['idents'] and s['ident_every'] and at - (last_ident or base) >= s['ident_every'] * 60:
                promo = self._pick_promo(s)
                entry = promo and self._entry('promo', promo, 'clock')
            if entry is None:
                ad = self._pick_ad(s, rows, at)
                entry = ad and self._entry('ad', ad['id'], 'rotation')
            if entry is None and s['idents']:
                promo = self._pick_promo(s)
                entry = promo and self._entry('promo', promo, 'rotation')
            if entry is None:
                break
            self.next.append(entry)

    def redraw(self):
        """Draws the rotation's part of Next up again (the settings changed), keeping what was queued by hand."""
        with self.lock:
            self.settings = self.store.settings()
            kept = [e for e in self.next if e['by'] == 'you']
            dropped = [e['id'] for e in self.next if e['by'] != 'you' and e['kind'] == 'ad']
            last = self.current['entry']['id'] if self.current and self.current['entry']['kind'] == 'ad' else None
            self.mix.undraw(dropped, last)
            self.rotation.undraw(dropped, last)
            self.next = kept
            self._fill()
            self.changed = time.time()

    # ---- the stream
    def viewed(self):
        """A viewer fetched the stream: starts it if stopped."""
        with self.lock:
            self.last_view = time.time()
            if not self.running:
                self._start()

    def _start(self):
        now = time.time()
        self.settings = self.store.settings()
        self.problem = None
        self.running, self.started_at = True, now
        self.clock = now - PRIME_SEGMENTS * ads5_prep.SEGMENT
        self.segments = []
        if self.settings['open_with_ident'] and self.settings['idents']:
            promo = self._pick_promo(self.settings, ready_only=True)
            entry = promo and self._entry('promo', promo, 'tune-in')
            if entry and not entry['live'] and self._meta(entry):
                self.next.insert(0, entry)
        self._fill()
        self._publish(now)
        LOG.info('on air')

    def _stop(self, why):
        self._finish(self.clock)
        self.running = False
        self.segments = []
        self.current = None
        self.next = [e for e in self.next if e['by'] in ('you', 'rotation', 'clock')]
        LOG.info('off air: %s', why)

    def _finish(self, end):
        cur = self.current
        if not cur:
            return
        e = cur['entry']
        aired = max(0., end - cur['start'])
        length = cur['meta']['seconds']
        complete = cur['index'] >= len(cur['meta']['segments']) and not cur.get('skipped')
        row = {'kind': e['kind'], 'id': e['id'], 'name': e['name'], 'at': round(cur['start'], 2),
               'seconds': round(aired, 2), 'length': round(length, 2), 'complete': complete,
               'counted': my_ads.counts(aired, length) if e['kind'] == 'ad' else aired >= length / 2,
               'by': e['by']}
        if cur.get('skipped'):
            row['skipped'] = True
        self.store.log(row)
        for h in reversed(self.history):
            if h['key'] == e['key']:
                h['end'] = end
                h['seconds'] = aired
                break
        self.current = None
        if e['by'] == 'you':
            self.store.save_queue([x for x in self.next if x['by'] == 'you'])

    def _take(self):
        """The next entry ready to air: Next up's first that is encoded (a live-text promo drawn
        for now); with none, any encoded ident, or ad. Returns (entry, meta) or (None, None)."""
        for i, e in enumerate(self.next[:NEXT_DRAWN + MAX_QUEUED]):
            meta = self._meta(e)
            if meta:
                del self.next[i]
                return e, meta
            if e['live'] and i < 2:
                continue
        fallback = []
        for kind, items in (('promo', [p['id'] for p in self.store.promo_library() if not p['overlays']]),
                            ('id', ['station'])):
            for item in items:
                entry = self._entry(kind, item, 'fill')
                if entry and self._meta(entry):
                    fallback.append(entry)
        if not fallback:
            for a in self.store.ads():
                entry = self._entry('ad', a['id'], 'fill')
                if entry and self._meta(entry):
                    fallback.append(entry)
        if fallback:
            e = self.rng.choice(fallback)
            return e, self._meta(e)
        return None, None

    def _advance(self, at):
        self._finish(at)
        self._fill()
        entry, meta = self._take()
        if entry is None:
            self.problem = 'Nothing is encoded yet to air'
            return False
        start = at
        self.current = {'entry': entry, 'meta': meta, 'index': 0, 'delta': (self.pts - meta['start']) % WRAP,
                        'start': start}
        self.pts = (self.pts + meta['span']) % WRAP
        self.history.append({'key': entry['key'], 'kind': entry['kind'], 'id': entry['id'], 'name': entry['name'],
                             'by': entry['by'], 'start': start, 'end': start + meta['seconds'], 'seconds': meta['seconds']})
        del self.history[:-HISTORY]
        if entry['by'] == 'you':
            self.store.save_queue([x for x in self.next if x['by'] == 'you'])
        self._fill()
        return True

    def _publish(self, now):
        """Publishes every segment whose time has come (each once its end has passed, as a live
        encoder would)."""
        guard = 0
        while self.running and guard < 50:
            guard += 1
            cur = self.current
            if cur is None or cur['index'] >= len(cur['meta']['segments']):
                if self.clock < now - 5 * ads5_prep.SEGMENT:
                    self.clock = now - ads5_prep.SEGMENT      # stalled (nothing to air): carry on from now
                if not self._advance(self.clock):
                    if not self.segments:
                        self._stop(self.problem)
                    return
                cur = self.current
            seg = cur['meta']['segments'][cur['index']]
            if self.clock + seg['seconds'] > now:
                return
            try:
                raw = (Path(cur['entry']['folder']) / seg['name']).read_bytes()
            except OSError as exc:
                LOG.warning('segment missing (%s): skipping %s', exc, cur['entry']['name'])
                self.clips.ready.pop(cur['entry']['folder'], None)
                cur['index'] = len(cur['meta']['segments'])
                cur['skipped'] = True
                continue
            data = self.splicer.shift(raw, cur['delta'])
            self.segments.append({'seq': self.seq, 'start': self.clock, 'seconds': seg['seconds'], 'data': data,
                                  'key': cur['entry']['key']})
            self.seq += 1
            self.clock += seg['seconds']
            cur['index'] += 1
            del self.segments[:-KEEP_SEGMENTS]

    def _prepare_ahead(self, now):
        """Asks for Next up's clips, nearest first; draws live-text promos as they near air."""
        at = self.clock if self.running else now
        if self.current:
            cur = self.current
            at = cur['start'] + cur['meta']['seconds']
        for i, e in enumerate(self.next):
            if e['live']:
                if (self.running and at - now < LIVE_RENDER_AHEAD) and (
                        e.get('render_at') is None or abs(e['render_at'] - at) > 30):
                    spec = self.clips.spec('promo', e['id'], start=at)
                    if spec:
                        e['folder'], e['render_at'] = str(spec['folder']), at
                        self.clips.want(spec, 0)
            elif not self._meta(e):
                spec = self.clips.spec(e['kind'], e['id'])
                if spec:
                    self.clips.want(spec, 0 if i < 3 else 1)
            at += e['seconds']

    def tick(self):
        with self.lock:
            now = time.time()
            if self.running and not self.settings['always_on'] and now - self.last_view > IDLE_SECONDS:
                self._stop('nobody watching')
            if self.running:
                self._publish(now)
            elif self.settings['always_on'] and now - (self.started_at or 0) > 10:
                self._start()
            self._fill()
            self._prepare_ahead(now)

    def run(self):
        sweep = 0
        while True:
            try:
                self.tick()
                if time.time() - sweep > 60:
                    sweep = time.time()
                    self.background()
            except Exception:   # noqa: BLE001 - the channel keeps going
                LOG.exception('tick failed')
            time.sleep(0.2)

    def background(self):
        """The library's clips not encoded yet (idents first), and live renders done with."""
        settings = self.settings
        if STATION_ID.is_file():
            self.clips.want(self.clips.spec('id', 'station'), 2)
        for p in self.store.promo_library():
            if not p['overlays'] and p.get('present'):
                spec = self.clips.spec('promo', p['id'])
                if spec:
                    self.clips.want(spec, 3)
        for a in self.store.ads():
            spec = self.clips.spec('ad', a['id'], ad=a)
            if spec:
                self.clips.want(spec, 5 if a['enabled'] else 7)
        with self.lock:
            keep = [e['folder'] for e in self.next if e.get('folder')]
            if self.current:
                keep.append(self.current['entry'].get('folder'))
        self.clips.sweep_live([k for k in keep if k])

    # ---- the playlist
    def playlist(self):
        with self.lock:
            window = self.segments[-WINDOW:]
            if not window:
                return None
            lines = ['#EXTM3U', '#EXT-X-VERSION:3', f'#EXT-X-TARGETDURATION:{ads5_prep.SEGMENT}',
                     f'#EXT-X-MEDIA-SEQUENCE:{window[0]["seq"]}', '#EXT-X-INDEPENDENT-SEGMENTS']
            for seg in window:
                stamp = datetime.fromtimestamp(seg['start'], timezone.utc).isoformat(timespec='milliseconds')
                lines += [f'#EXT-X-PROGRAM-DATE-TIME:{stamp.replace("+00:00", "Z")}',
                          f'#EXTINF:{seg["seconds"]:.3f},', f'seg/{seg["seq"]}.ts']
            return '\n'.join(lines) + '\n'

    def segment(self, seq):
        with self.lock:
            for seg in reversed(self.segments):
                if seg['seq'] == seq:
                    return seg['data']
        return None

    # ---- Next up by hand
    def queue_add(self, kind, item_id, first=False):
        if kind not in ('ad', 'promo', 'id'):
            raise ConfigError('kind is ad, promo or id')
        with self.lock:
            if sum(1 for e in self.next if e['by'] == 'you') >= MAX_QUEUED:
                raise ConfigError(f'At most {MAX_QUEUED} wait in the queue')
            if kind == 'promo':
                why = promos_mod.readiness(next((p for p in self.store.promo_library() if p['id'] == item_id), {}),
                                           self.store.promo_values(), by_hand=True)
                if why:
                    raise ConfigError(f'That ident cannot air now: {why}')
            entry = self._entry(kind, item_id, 'you')
            if entry is None:
                raise ConfigError('Nothing to air by that name')
            mine = [i for i, e in enumerate(self.next) if e['by'] == 'you']
            self.next.insert(0 if first or not mine else mine[-1] + 1, entry)
            self.store.save_queue([e for e in self.next if e['by'] == 'you'])
            spec = self.clips.spec(kind, item_id)
            if spec and spec.get('folder'):
                self.clips.want(spec, 0)
            return entry

    def skip(self, key):
        """Takes an entry out of Next up, or cuts what is on air ('on-air') at the next segment."""
        with self.lock:
            if key == 'on-air' or (self.current and self.current['entry']['key'] == key):
                if not self.current:
                    raise ConfigError('Nothing is on air')
                self.current['skipped'] = True
                self.current['index'] = len(self.current['meta']['segments'])
                return 'on-air'
            for i, e in enumerate(self.next):
                if e['key'] == key:
                    del self.next[i]
                    if e['by'] == 'you':
                        self.store.save_queue([x for x in self.next if x['by'] == 'you'])
                    self._fill()
                    return 'skipped'
            raise ConfigError('That is no longer in Next up')

    def move(self, key, offset):
        with self.lock:
            index = next((i for i, e in enumerate(self.next) if e['key'] == key), None)
            if index is None:
                raise ConfigError('That is no longer in Next up')
            target = max(0, min(len(self.next) - 1, index + offset))
            entry = self.next.pop(index)
            entry['by'] = 'you'
            self.next.insert(target, entry)
            self.store.save_queue([e for e in self.next if e['by'] == 'you'])
            return target

    # ---- what the page reads
    def status(self):
        with self.lock:
            now = time.time()
            at = self.clock if self.running else now
            on_air = None
            if self.current:
                cur = self.current
                at = cur['start'] + cur['meta']['seconds']
                on_air = {**self._public(cur['entry']), 'start': cur['start'], 'end': at,
                          'skipping': bool(cur.get('skipped'))}
            upcoming = []
            for e in self.next:
                upcoming.append({**self._public(e), 'at': at, 'ready': self._ready(e)})
                at += e['seconds']
            return {'now': now, 'name': NAME, 'number': NUMBER, 'running': self.running,
                    'started_at': self.started_at, 'last_view': self.last_view,
                    'idle_in': max(0, IDLE_SECONDS - (now - self.last_view)) if self.running else None,
                    'live_edge': self.clock if self.running else None, 'problem': self.problem,
                    'on_air': on_air, 'next': upcoming,
                    'history': [dict(h) for h in self.history[-HISTORY:]],
                    'changed': self.changed}

    def _ready(self, e):
        if e['live']:
            return 'ready' if self._meta(e) else ('working' if e.get('folder') else 'live')
        return self.clips.state(Path(e['folder']))

    @staticmethod
    def _public(e):
        return {k: e[k] for k in ('key', 'kind', 'id', 'by', 'name', 'seconds', 'live')}


# ---------------------------------------------------------------- the library, as the page shows it

def library_view(store, channel, clips):
    """Every ad and ident with Ads 5's own settings and counts, the kinds, the clips' progress."""
    settings = store.settings()
    now = time.time()
    day = now - 86400
    rows = store.plays(days=8)
    counts, first = store.tally.read()
    mix = store.mix()
    ads = store.ads()
    kind = ad_mix.kinds_of(mix, ads)
    wear, boost = ad_mix.own(mix, kind)
    times = channel.mix.exposure.read()
    since = my_ads.limits_since({'limits': settings['limits'], 'limits_from': settings['limits_from']})
    by_id, last_at = {}, {}
    for r in rows:
        if r.get('kind', 'ad') == 'ad' and isinstance(r.get('id'), str):
            by_id.setdefault(r['id'], []).append(r)
            last_at[r['id']] = max(last_at.get(r['id'], 0), r['at'])
    longest = settings['longest_ad']
    out_ads = []
    for a in ads:
        mine = times.get(a['id'], [])
        own_rows = by_id.get(a['id'], [])
        spec = clips.spec('ad', a['id'], ad=a)
        allowed = my_ads.allowed(a, own_rows, now, since)
        out_ads.append({
            'id': a['id'], 'name': a['name'], 'duration': a['duration'], 'enabled': a['enabled'],
            'limit': a['limit'], 'limits_from': a['limits_from'], 'pics': a['pics'], 'added': a['added'],
            'kind': kind[a['id']], 'boost': boost[a['id']], 'wear': mix['overrides'].get(a['id'], {}).get('wear', 1.),
            'chance': round(ad_mix.chance(ad_mix.seen(mine, now, mix['tuning']['half_life_days']),
                                          max(mine) if mine else None, now, mix['tuning'],
                                          wear=wear[a['id']], boost=boost[a['id']], added=a['added']), 4),
            'plays_day': sum(1 for r in own_rows if r['at'] >= day and my_ads.played(r)),
            'plays_all': counts.get(f"ad:{a['id']}", 0), 'last': last_at.get(a['id']),
            'allowed': allowed and not (longest and a['duration'] > longest),
            'again': None if allowed or not a['enabled'] else my_ads.allowed_again(a, own_rows, now, since),
            'too_long': bool(longest and a['duration'] > longest),
            'clip': clips.state(spec['folder']) if spec else 'missing', 'vv_enabled': a['vv_enabled']})
    reasons = channel.promo_reasons(settings)
    out_promos = []
    for p in store.promo_library():
        spec = clips.spec('promo', p['id'])
        out_promos.append({'id': p['id'], 'name': p['name'], 'kind': p['kind'], 'duration': p['duration'],
                           'description': p['description'], 'enabled': promos_mod.switched_on(settings, p['id']),
                           'why': reasons.get(p['id']), 'live': bool(p['overlays']), 'still': bool(p.get('still')),
                           'plays_all': counts.get(f"promo:{p['id']}", 0),
                           'clip': 'live' if p['overlays'] else (clips.state(spec['folder']) if spec else 'missing')})
    station = clips.spec('id', 'station')
    recent = Counter(kind.get(r['id']) for i in by_id.values() for r in i if r['at'] >= day and my_ads.played(r))
    kinds = []
    for c in mix['categories'] + [{'key': ad_mix.UNSORTED, 'name': 'Unsorted', 'weight': mix['tuning']['unsorted'],
                                   'wear': 1.0, 'about': 'Ads with no kind'}]:
        members = sum(1 for a in ads if kind[a['id']] == c['key'])
        if not members and c['key'] == ad_mix.UNSORTED:
            continue
        kinds.append({'key': c['key'], 'name': c['name'], 'weight': c['weight'], 'wear': c['wear'],
                      'about': c.get('about', ''), 'ads': members, 'day': recent.get(c['key'], 0)})
    ready = sum(1 for a in out_ads if a['clip'] == 'ready') + sum(1 for p in out_promos if p['clip'] == 'ready')
    return {'settings': {k: v for k, v in settings.items() if k not in ('ads', 'promos')},
            'ads': out_ads, 'promos': out_promos, 'kinds': kinds,
            'station_id': {'clip': clips.state(station['folder']) if station else 'missing',
                           'plays_all': counts.get('id:station', 0)},
            'tuning': mix['tuning'], 'tuning_ranges': {k: list(v) for k, v in ad_mix.TUNING.items()},
            'clips': {**clips.summary(), 'ready': ready,
                      'total': len(out_ads) + sum(1 for p in out_promos if p['clip'] != 'live')},
            'plays': {'first': first, 'day': sum(recent.values())},
            'recent': rows[-60:][::-1]}


# ---------------------------------------------------------------- HTTP

_FILES = {
    '': ('ads5/index.html', 'text/html; charset=utf-8'),
    'ads5.css': ('ads5/ads5.css', 'text/css; charset=utf-8'),
    'ads5.js': ('ads5/ads5.js', 'text/javascript; charset=utf-8'),
    'hls.js': ('vendor/hls-1.7.2.min.js', 'text/javascript; charset=utf-8'),
}
_FONT = re.compile(r'fonts/([a-z0-9-]+\.woff2)')
_PICTURE = re.compile(r'pic/([0-9a-f]{12}-[0-3]\.jpg)')
_STILL = re.compile(r'still/([a-z0-9][a-z0-9-]{0,39})\.png')


def make_handler(store, channel, clips):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'Ads5/1'

        def log_message(self, fmt, *args):  # quiet: segments come every 2 s
            pass

        def _send(self, status, body, ctype, cache='no-store'):
            if isinstance(body, str):
                body = body.encode()
            self.send_response(status)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', cache)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)

        def _json(self, status, value):
            self._send(status, json.dumps(value), 'application/json')

        def _error(self, status, message):
            self._json(status, {'ok': False, 'error': message})

        def _path(self):
            path = urlsplit(self.path).path
            if path in ('/', '/ads5'):
                return None
            return path[len('/ads5/'):] if path.startswith('/ads5/') else path.lstrip('/')

        def do_HEAD(self):  # noqa: N802
            self.do_GET()

        def do_GET(self):  # noqa: N802
            path = self._path()
            if path is None:
                self.send_response(HTTPStatus.MOVED_PERMANENTLY)
                self.send_header('Location', '/ads5/')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            try:
                if path in _FILES:
                    name, ctype = _FILES[path]
                    self._send(HTTPStatus.OK, (STATIC / name).read_bytes(), ctype,
                               'no-cache' if path in ('', 'ads5.js', 'ads5.css') else 'max-age=86400')
                elif path == 'index.m3u8':
                    self._send(HTTPStatus.OK, '#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-INDEPENDENT-SEGMENTS\n'
                               '#EXT-X-STREAM-INF:BANDWIDTH=3500000,AVERAGE-BANDWIDTH=2000000,RESOLUTION=1280x720,'
                               'FRAME-RATE=60.000,CODECS="avc1.64002a,mp4a.40.2"\nlive.m3u8\n',
                               'application/vnd.apple.mpegurl')
                elif path == 'live.m3u8':
                    channel.viewed()
                    body = None
                    for _ in range(40):
                        body = channel.playlist()
                        if body:
                            break
                        time.sleep(0.1)
                    if body:
                        self._send(HTTPStatus.OK, body, 'application/vnd.apple.mpegurl')
                    else:
                        self._error(HTTPStatus.SERVICE_UNAVAILABLE,
                                    channel.problem or 'Ads 5 is getting its first clips ready')
                elif path.startswith('seg/') and path.endswith('.ts') and path[4:-3].isdigit():
                    channel.last_view = time.time()
                    data = channel.segment(int(path[4:-3]))
                    if data is None:
                        self._error(HTTPStatus.NOT_FOUND, 'That segment is gone')
                    else:
                        self._send(HTTPStatus.OK, data, 'video/mp2t', 'max-age=60')
                elif path == 'v1/status':
                    self._json(HTTPStatus.OK, channel.status())
                elif path == 'v1/library':
                    self._json(HTTPStatus.OK, library_view(store, channel, clips))
                elif path in ('guide.json', 'v1/guide'):
                    hours = parse_qs(urlsplit(self.path).query).get('hours', ['24'])[0]
                    self._json(HTTPStatus.OK, guide(int(hours) if hours.isdigit() else 24))
                elif _FONT.fullmatch(path):
                    self._file(STATIC / 'fonts' / _FONT.fullmatch(path)[1], 'font/woff2')
                elif _PICTURE.fullmatch(path):
                    self._file(store.vv / 'my-ads' / _PICTURE.fullmatch(path)[1], 'image/jpeg')
                elif _STILL.fullmatch(path):
                    name = _STILL.fullmatch(path)[1]
                    file = STATION_ID.with_suffix('.png') if name == 'station' else store._vv_promos.library.path(name + '.png')
                    self._file(file, 'image/png')
                else:
                    self._error(HTTPStatus.NOT_FOUND, 'Not here')
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _file(self, path, ctype):
            if path is None or not Path(path).is_file():
                self._error(HTTPStatus.NOT_FOUND, 'No such file')
                return
            self._send(HTTPStatus.OK, Path(path).read_bytes(), ctype, 'max-age=3600')

        def do_POST(self):  # noqa: N802
            path = self._path() or ''
            try:
                length = int(self.headers.get('Content-Length') or 0)
                body = json.loads(self.rfile.read(length) or b'{}') if length else {}
            except (ValueError, OSError):
                return self._error(HTTPStatus.BAD_REQUEST, 'Send JSON')
            try:
                result = self._post(path, body)
            except ConfigError as exc:
                return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            if result is None:
                return self._error(HTTPStatus.NOT_FOUND, 'Not here')
            self._json(HTTPStatus.OK, {'ok': True, **result})

        def _post(self, path, body):
            if path == 'v1/settings':
                settings = store.update(body)
                channel.redraw()
                return {'settings': {k: v for k, v in settings.items() if k not in ('ads', 'promos')}}
            if path == 'v1/fork':
                store.fork()
                channel.redraw()
                return {'settings': store.settings()}
            if path == 'v1/mix':
                store.change_mix(body)
                channel.redraw()
                return {'mix': store.mix_own()}
            if path.startswith('v1/ads/'):
                store.set_ad(path[len('v1/ads/'):], body)
                channel.redraw()
                return {}
            if path.startswith('v1/promos/'):
                store.set_promo(path[len('v1/promos/'):], body)
                channel.redraw()
                return {}
            if path == 'v1/next':
                op = body.get('op')
                if op == 'add':
                    entry = channel.queue_add(body.get('kind'), body.get('id'), bool(body.get('next')))
                    return {'entry': channel._public(entry), 'status': channel.status()}
                if op == 'skip':
                    return {'result': channel.skip(body.get('key')), 'status': channel.status()}
                if op == 'move':
                    return {'result': channel.move(body.get('key'), int(body.get('by') or 0)), 'status': channel.status()}
                if op == 'redraw':
                    channel.redraw()
                    return {'status': channel.status()}
                raise ConfigError('op is add, skip, move or redraw')
            return None

    return Handler


def guide(hours=24):
    """Listings for TV Thing's guide: Ads 5 all day, in half hours."""
    start = int(time.time() // 1800 * 1800)
    return {'channel': NAME, 'events': [
        {'start': start + i * 1800, 'duration': 1800, 'title': NAME,
         'description': 'Nothing but ads: the station\'s whole library of commercials, its idents and the odd station ID.'}
        for i in range(max(1, min(hours, 72) * 2))]}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Ads 5: a channel of nothing but ads')
    parser.add_argument('--host', default=os.environ.get('ADS5_HOST', '0.0.0.0'))
    parser.add_argument('--port', type=int, default=int(os.environ.get('ADS5_PORT', '6975')))
    parser.add_argument('--state', default=os.environ.get('ADS5_STATE', str(ROOT / 'state' / 'ads5')))
    parser.add_argument('--vizelvision', default=os.environ.get('ADS5_VIZELVISION', str(ROOT / 'state' / 'master-candidate')))
    parser.add_argument('--workers', type=int, default=int(os.environ.get('ADS5_WORKERS', '2')))
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
    store = Store(args.state, args.vizelvision)
    clips = Clips(store, workers=args.workers)
    channel = Channel(store, clips)
    clips.start()
    channel.background()
    threading.Thread(target=channel.run, daemon=True, name='ads5-channel').start()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(store, channel, clips))
    server.daemon_threads = True
    LOG.info('Ads 5 on http://%s:%d/ads5/', args.host, args.port)
    server.serve_forever()


if __name__ == '__main__':
    main()
