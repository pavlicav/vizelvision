"""Station promos: VizelVision's own 5- and 10-second bumpers (idents and promos, built by
ident/promos/build.py), aired in the breaks ad mute takes off air, beside My ads.

- **At least one every `every` minutes** (15 by default). Once that long has passed since
  the last promo aired, the next break opens with one, as breaks allow. A promo that
  the programme's return cuts short before half of it airs does not count, so the next
  break tries again. **`every` 0: every break** opens with one (master plays it only before
  anything else in the break, so they never run back to back).
- **Fill** (off by default): when My ads has nothing left to show, promos stand in before
  the break card, each once a break.
- With My ads switched off, a promo still opens the break when one is due; the break then
  carries on as ad mute has it (the muted programme under the break sound).
- **Live text.** Some promos carry text that master draws as they air (promo_overlay.py):
  the time and the temperature, or the programme on air. A promo whose text is not known
  sits out (no temperature reading, no programme name).
- **Sports.** A promo with `leagues` in its manifest (baseball: mlb; football: nfl, ncaaf;
  basketball: nba, wnba; hockey: nhl) airs only while a game of one of them is on air.
  Otherwise it sits out.
- **A voiced name.** 'only-on' also says the programme's name: the web app has it voiced
  (Deepgram, as the continuity announcements are) and mixed into a copy of the promo
  whenever the programme changes (PromoDesk). Until that copy is ready, the promo airs
  as built, with its own line.

Shared by the web app (strict; the only writer of the settings and of the live values)
and the master worker (lenient: a newer web app's keys never stop it). The master side
is ad_break.py.

    ident/promos/<id>.mp4, .png, .json   the promos, a still of each, their manifests (the build's)
    promos.json        settings (beside the master socket)
    promos-now.json    live values: the temperature, the programme on air (and its league, for a
                       game), its voiced copies
    promos/            those copies (<promo>-<hash>.mp4)
Plays are logged with My ads' plays (my-ads-plays.jsonl), kind "promo"; the page counts
each promo's plays that counted, all time.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time

from .errors import ConfigError
from .my_ads import PlayTally, read_plays
from . import promo_overlay

LIBRARY = Path(__file__).resolve().parent.parent / 'ident' / 'promos'
DEFAULTS = {
    # Play promos in the breaks ad mute takes off air (its mode On).
    'enabled': True,
    # At least one every this many minutes: the first break after that opens with one.
    # 0: every break opens with one.
    'every': 15,
    # When My ads has nothing left, promos stand in (each once a break) before the break card.
    'fill': False,
    # Each promo by id: {"enabled": true|false}. A promo not listed is on.
    'promos': {},
}
EVERY = (5, 240)
EVERY_BREAK = 0
EVERY_CHOICES = (EVERY_BREAK, 5, 10, 15, 20, 30, 45, 60, 90, 120)
# The web app writes the live values every minute; older ones are not trusted (it is down).
FRESH_VALUES = 300
# Weather stations report hourly; the crawl's weather goes stale after the same.
FRESH_TEMPERATURE = 3 * 3600
NEEDS = {'temperature': 'temperature', 'celsius': 'temperature', 'place': 'temperature', 'programme': 'programme'}
_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
_VARIANT = re.compile(r'^([a-z0-9][a-z0-9-]{0,39})-([0-9a-f]{16})\.mp4$')
LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------- settings

def validate(value, *, lenient=False):
    if not isinstance(value, dict):
        raise ConfigError('Promo settings must be an object')
    if lenient:
        value = {k: v for k, v in value.items() if k in DEFAULTS}
    elif not set(value) <= set(DEFAULTS):
        raise ConfigError('Promo settings take ' + ', '.join(DEFAULTS))
    result = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(value)}
    for key in ('enabled', 'fill'):
        if not isinstance(result[key], bool):
            raise ConfigError(f'{key} must be true or false')
    every = result['every']
    if (isinstance(every, bool) or not isinstance(every, int)
            or not (every == EVERY_BREAK or EVERY[0] <= every <= EVERY[1])):
        raise ConfigError(f'every is a whole number of minutes from {EVERY[0]} to {EVERY[1]}, or 0 for every break')
    promos = result['promos']
    if not isinstance(promos, dict) or len(promos) > 100:
        raise ConfigError('promos maps a promo id to its settings')
    checked = {}
    for promo_id, entry in promos.items():
        if not isinstance(promo_id, str) or not _ID.match(promo_id):
            if lenient:
                continue
            raise ConfigError('A promo id is lowercase letters, digits and hyphens')
        if lenient and isinstance(entry, dict):
            entry = {k: v for k, v in entry.items() if k == 'enabled'}
        if not isinstance(entry, dict) or set(entry) != {'enabled'} or not isinstance(entry['enabled'], bool):
            if lenient:
                continue
            raise ConfigError('A promo takes enabled (true or false)')
        checked[promo_id] = {'enabled': entry['enabled']}
    result['promos'] = checked
    return result


def switched_on(settings, promo_id):
    return (settings['promos'].get(promo_id) or {}).get('enabled', True)


# ---------------------------------------------------------------- the library (the build's manifests)

def _manifest(raw, folder, name):
    """A manifest, checked. ValueError when the promo cannot be aired at all."""
    if not isinstance(raw, dict) or raw.get('id') != name or not _ID.match(name):
        raise ValueError('its id does not match its file name')
    if raw.get('file') != name + '.mp4':
        raise ValueError(f'its file must be {name}.mp4')
    duration = raw.get('duration')
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 1 <= duration <= 60:
        raise ValueError('its duration must be 1 to 60 seconds')
    overlays, problems = promo_overlay.validate_all(raw.get('overlays') or [])
    if problems:
        raise ValueError('an overlay cannot be drawn: ' + problems[0])
    voice = raw.get('voice')
    if voice is not None:
        if (not isinstance(voice, dict) or not isinstance(voice.get('model'), str)
                or not re.match(r'^aura(-2)?-[a-z]+-[a-z]{2}$', voice['model'])
                or not isinstance(voice.get('template'), str) or '{name}' not in voice['template']
                or not isinstance(voice.get('music'), str) or '/' in voice['music']
                or not all(isinstance(voice.get(k), (int, float)) for k in ('start', 'earliest', 'end'))
                or not 0 <= voice['earliest'] <= voice['start'] < voice['end'] <= duration):
            raise ValueError('its voice needs model, template (with {name}), music, earliest, start and end')
    leagues = raw.get('leagues') or []
    if (not isinstance(leagues, list) or len(leagues) > 10
            or not all(isinstance(league, str) and _ID.match(league) for league in leagues)):
        raise ValueError('its leagues are a list of league ids (mlb, nfl, ...)')
    still = raw.get('still')
    still = still if isinstance(still, str) and still == name + '.png' else None
    return {'id': name, 'name': str(raw.get('name') or name)[:60], 'kind': raw.get('kind') if raw.get('kind') in ('ident', 'promo') else 'promo',
            'description': str(raw.get('description') or '')[:400], 'order': raw.get('order') if isinstance(raw.get('order'), int) else 99,
            'duration': float(duration), 'file': raw['file'], 'still': still,
            'still_at': float(raw.get('still_at') or duration / 2), 'overlays': overlays, 'voice': voice,
            'leagues': list(leagues),
            'needs': sorted({NEEDS[o['field']] for o in overlays if o['field'] in NEEDS} | ({'league'} if leagues else set())),
            'built_at': raw.get('built_at'), 'present': (folder / raw['file']).is_file()}


class Library:
    """The promos the build made (ident/promos/*.json), in their order. Re-read only when a
    manifest changes; whether each video is present is checked on every read."""

    def __init__(self, folder=LIBRARY):
        self.folder = Path(folder)
        self.lock = threading.Lock()
        self.key, self.promos, self.problems = None, [], {}

    def read(self):
        try:
            files = sorted(p for p in self.folder.glob('*.json') if _ID.match(p.stem))
            key = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in files)
        except OSError:
            files, key = [], ()
        with self.lock:
            if key != self.key:
                promos, problems = [], {}
                for path in files:
                    try:
                        promos.append(_manifest(json.loads(path.read_text()), self.folder, path.stem))
                    except (OSError, ValueError) as exc:
                        problems[path.stem] = str(exc)[:200]
                self.key, self.promos, self.problems = key, sorted(promos, key=lambda p: (p['order'], p['id'])), problems
            promos = copy.deepcopy(self.promos)
        for promo in promos:
            promo['present'] = (self.folder / promo['file']).is_file()
        return promos

    def path(self, name):
        """A file of the library (a promo, its still or its music) by name; None if unknown."""
        if not isinstance(name, str) or not re.match(r'^[a-z0-9][a-z0-9-]{0,39}(-music)?\.(mp4|png|wav)$', name):
            return None
        path = self.folder / name
        return path if path.is_file() else None


# ---------------------------------------------------------------- live values

def fresh(values, now=None):
    """The live values master may use now: the temperature while it is recent, the
    programme while the web app keeps writing; {} when the web app has gone quiet."""
    now = time.time() if now is None else now
    if not isinstance(values, dict) or not isinstance(values.get('at'), (int, float)) or now - values['at'] > FRESH_VALUES:
        return {}
    result = {}
    reading = values.get('temperature')
    if (isinstance(reading, dict) and isinstance(reading.get('f'), (int, float))
            and isinstance(reading.get('observed_at'), (int, float)) and now - reading['observed_at'] <= FRESH_TEMPERATURE):
        result['temperature'] = reading
    programme = values.get('programme')
    if isinstance(programme, dict) and isinstance(programme.get('title'), str) and programme['title'].strip():
        variants = programme.get('variants') if isinstance(programme.get('variants'), dict) else {}
        result['programme'] = {'title': programme['title'].strip()[:120], 'spoken': programme.get('spoken'),
                               'variants': {k: v for k, v in variants.items() if isinstance(v, str) and _VARIANT.match(v)}}
        if isinstance(programme.get('league'), str) and _ID.match(programme['league']):
            result['programme']['league'] = programme['league']
    return result


def readiness(promo, values):
    """Why a promo cannot air with these (fresh) values, or None if it can."""
    if not promo.get('present'):
        return 'its video is not built'
    if 'temperature' in promo['needs'] and not values.get('temperature'):
        return 'no recent temperature reading'
    if 'programme' in promo['needs'] and not values.get('programme'):
        return 'no programme name on air'
    leagues = promo.get('leagues')
    if leagues and (values.get('programme') or {}).get('league') not in leagues:
        return 'only during ' + ' or '.join(league.upper() for league in leagues) + ' games'
    return None


def counted_promo(row):
    """A play log row's promo, if it is a promo's play that counted."""
    return row.get('id') if row.get('kind') == 'promo' and row.get('counted') else None


def last_promo(plays):
    """When the last promo that counted started (epoch seconds), or None."""
    return max((p['at'] for p in plays if p.get('kind') == 'promo' and p.get('counted')), default=None)


def due(settings, last, now):
    """Is a promo due: none counted yet, or none for `every` minutes (with 0, always: master
    then opens each break with one)."""
    return last is None or now - last >= settings['every'] * 60


class Promos:
    """The settings and the live values, beside the master socket."""

    def __init__(self, socket_path, *, lenient=False, library=None):
        base = Path(socket_path)
        self.path = base.with_name('promos.json')
        self.values_path = base.with_name('promos-now.json')
        self.folder = base.with_name('promos')
        self.plays_path = base.with_name('my-ads-plays.jsonl')
        self.tally = PlayTally(self.plays_path, counted_promo)
        self.library = library or Library()
        self.lenient = lenient
        self.lock = threading.RLock()

    def read(self):
        try:
            return validate(json.loads(self.path.read_text()), lenient=self.lenient)
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)

    def _write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.' + path.stem + '-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream, indent=2)
                stream.write('\n')
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)

    def save(self, value):
        value = validate(value)
        with self.lock:
            self._write(self.path, value)
        return value

    def update(self, changes):
        """Settings: enabled, every, fill."""
        if not isinstance(changes, dict) or not changes or not set(changes) <= {'enabled', 'every', 'fill'}:
            raise ConfigError('Settings take enabled, every and fill; set each promo on its own')
        with self.lock:
            return self.save({**self.read(), **changes})

    def set_promo(self, promo_id, changes):
        """One promo: {"enabled": true|false}."""
        if not any(p['id'] == promo_id for p in self.library.read()):
            raise ConfigError('No such promo')
        if not isinstance(changes, dict) or set(changes) != {'enabled'}:
            raise ConfigError('A promo takes enabled (true or false)')
        with self.lock:
            value = self.read()
            value['promos'][promo_id] = {'enabled': changes['enabled']}
            return self.save(value)

    def values(self):
        try:
            value = json.loads(self.values_path.read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def write_values(self, values):
        with self.lock:
            self._write(self.values_path, values)

    def plays(self, since=0.):
        return [p for p in read_plays(self.plays_path, since) if p.get('kind') == 'promo']

    def snapshot(self):
        """For master, once a second: the settings, the fresh live values, the promos, and the
        folders of the promos and of their voiced copies."""
        return {'settings': self.read(), 'values': fresh(self.values()), 'promos': self.library.read(),
                'library': self.library.folder, 'variants': self.folder}


# ---------------------------------------------------------------- the web app's desk

def display_name(segment, game_info=None):
    """A programme as the screen shows it: "Lions at Panthers" for a game, else its
    title. None for what has no name to show (a bare channel, OFF AIR, the ID)."""
    if not segment or segment.get('kind') in ('off_air', 'ident'):
        return None
    if (segment.get('target') or {}).get('source_id') == 'off-air':
        return None
    game = segment.get('game')
    if game and game.get('game_pk') is not None and game_info:
        try:
            info = game_info({**game, 'league': game.get('league') or 'mlb'}) or {}
        except Exception:
            info = {}
        away, home = (info.get('away') or {}).get('nickname'), (info.get('home') or {}).get('nickname')
        if away and home:
            return f'{away} at {home}'
    title = (segment.get('title') or (game or {}).get('title') or '').strip()
    return title[:120] or None


def league_of(segment):
    """The league of the game a segment airs ("mlb", "nfl", ...), or None if it is not a game."""
    game = (segment or {}).get('game')
    if not isinstance(game, dict) or game.get('game_pk') is None:
        return None
    league = game.get('league') or 'mlb'
    return league if isinstance(league, str) and _ID.match(league) else None


def spoken_line(template, spoken):
    """The voiced line: the template with the programme's name, capitalised to start."""
    name = ' '.join(str(spoken).split())
    return template.format(name=name[:1].upper() + name[1:])


class PromoDesk:
    """Keeps promos-now.json fresh for master (every minute, and at once on a change): the
    temperature (an api.weather.gov reading, fetched only while a promo needs it), and the
    programme on air with, for a promo that says its name, a copy voiced and mixed for it,
    and the league of the game on air (for the sports promos). Also builds the page's view.

    programme() returns the segment on air (playback projection) or None; name(segment)
    gives (shown, spoken) for it; weather is a crawl_feeds.WeatherFeed of its own (its
    `observation`); voice a continuity.Voice; master the worker client; mix continuity.mix."""
    POLL = 20
    HEARTBEAT = 60
    KEEP = 12
    RETRY = 600

    def __init__(self, store, *, programme=None, name=None, weather=None, voice=None, master=None, mix=None,
                 clock=time.time, start_worker=True):
        self.store, self.library = store, store.library
        self.programme, self.name, self.weather = programme, name, weather
        self.voice, self.master, self.mix, self.clock = voice, master, mix, clock
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.values = {}
        self.written = None          # what was last written (without its time), and when
        self.written_at = 0.
        self.errors = {}
        self.variants = {}           # (promo id, spoken, built) -> (file name or '!why', when)
        self.thread = None
        if start_worker:
            self.start()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='promo-desk', daemon=True)
            self.thread.start()

    def poke(self):
        self.wake.set()

    def close(self):
        self.stopping.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join(5)
        if self.weather is not None:
            self.weather.stop()

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.step()
            except Exception:
                LOG.exception('Promo desk step failed')
            self.wake.wait(self.POLL)
            self.wake.clear()

    def wanted(self, settings=None, promos=None):
        settings = settings or self.store.read()
        promos = self.library.read() if promos is None else promos
        return [p for p in promos if settings['enabled'] and switched_on(settings, p['id']) and p['present']]

    def step(self):
        now = self.clock()
        wanted = self.wanted()
        needs = {need for p in wanted for need in p['needs']}
        values, errors = {'at': round(now, 1)}, {}
        if self.weather is not None:
            self.weather.want('temperature' in needs)
            reading = getattr(self.weather, 'observation', None)
            if 'temperature' in needs:
                if reading and now - reading.get('observed_at', 0) <= FRESH_TEMPERATURE:
                    values['temperature'] = reading
                else:
                    errors['temperature'] = (self.weather.status().get('error')
                                             or ('The last reading is over 3 hours old' if reading else 'No reading yet'))
        if needs & {'programme', 'league'} and self.programme is not None:
            try:
                segment = self.programme()
                shown, spoken = self.name(segment) if segment else (None, None)
            except Exception as exc:
                segment, shown, spoken = None, None, None
                errors['programme'] = f'The playback projection is unavailable: {exc}'
            if shown:
                programme = {'title': shown, 'spoken': spoken or shown, 'variants': {}}
                league = league_of(segment)
                if league:
                    programme['league'] = league
                for promo in wanted:
                    if promo.get('voice'):
                        made = self._variant(promo, programme['spoken'])
                        if made and not made.startswith('!'):
                            programme['variants'][promo['id']] = made
                        elif made:
                            errors['voice'] = made[1:]
                values['programme'] = programme
        with self.lock:
            self.values, self.errors = values, errors
        same = {k: v for k, v in values.items() if k != 'at'} == self.written
        if not same or now - self.written_at >= self.HEARTBEAT:
            self.store.write_values(values)
            self.written, self.written_at = {k: v for k, v in values.items() if k != 'at'}, now

    def _variant(self, promo, spoken):
        """The file name of promo voiced for spoken (made if need be), or '!why' if it cannot be.
        A failure (Deepgram unreachable) is tried again after RETRY seconds."""
        key, now = (promo['id'], spoken, promo.get('built_at')), self.clock()
        known = self.variants.get(key)
        if known and (not known[0].startswith('!') or now - known[1] < self.RETRY):
            return known[0]
        try:
            made = self.render_variant(promo, spoken).name
        except (ConfigError, OSError) as exc:
            made = '!' + f'{promo["name"]} airs with its own line: {exc}'[:240]
        self.variants = {k: v for k, v in self.variants.items() if k[0] != promo['id']}
        self.variants[key] = (made, now)
        return made

    def render_variant(self, promo, spoken):
        """A copy of promo whose voice says spoken's name: the line voiced (and kept), placed in
        the promo's voice slot (earlier if it is long), mixed over its music and levelled as
        continuity's announcements are, with the promo's picture copied."""
        from .continuity import seconds
        from .ident import file_identity
        spec = promo['voice']
        if self.voice is None or self.mix is None:
            raise ConfigError('nothing to voice it with')
        base, music = self.library.folder / promo['file'], self.library.folder / spec['music']
        if not music.is_file():
            raise ConfigError(f'its music ({spec["music"]}) is not built')
        text = spoken_line(spec['template'], spoken)
        line = self.voice.line(spec['model'], text)
        length = seconds(line)
        start = spec['start'] if spec['start'] + length <= spec['end'] else max(spec['earliest'], spec['end'] - length)
        if start + length > spec['end'] + .25:
            raise ConfigError(f'"{text}" is too long to say in time ({length:.1f} s)')
        digest = hashlib.sha256(json.dumps([spec['model'], text, round(start, 2), file_identity(base),
                                            file_identity(music), 1]).encode()).hexdigest()[:16]
        out = self.store.folder / f'{promo["id"]}-{digest}.mp4'
        if not out.exists():
            self.store.folder.mkdir(parents=True, exist_ok=True)
            self.mix([(line, start)], out, music=music, video=base, length=promo['duration'])
            self._tidy(out)
        return out

    def _tidy(self, keep):
        files = sorted((p for p in self.store.folder.glob('*.mp4') if _VARIANT.match(p.name)),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        current = {v for p in [self.values.get('programme') or {}] for v in (p.get('variants') or {}).values()}
        for path in files[self.KEEP:]:
            if path != keep and path.name not in current:
                path.unlink(missing_ok=True)

    # ------------------------------------------------------------ the page
    def status(self):
        settings, promos, now = self.store.read(), self.library.read(), self.clock()
        plays = self.store.plays(now - 7 * 86400)
        totals, since = self.store.tally.read()
        values = fresh(self.store.values(), now)
        with self.lock:
            errors = dict(self.errors)
        try:
            state = self.master.request() if self.master is not None else {}
            worker = state.get('my_ads') or {}
            if state.get('state') in ('unavailable', 'not_configured'):
                worker = {'error': state.get('error') or 'The master worker is not running'}
        except Exception as exc:
            worker = {'error': f'Master is unavailable: {exc}'}
        listed = []
        for promo in promos:
            mine = [p for p in plays if p.get('id') == promo['id']]
            why = readiness(promo, values)
            listed.append({**promo, 'enabled': switched_on(settings, promo['id']), 'ready': why is None, 'why': why,
                           'played': {'day': sum(1 for p in mine if p.get('counted') and p['at'] >= now - 86400),
                                      'week': sum(1 for p in mine if p.get('counted')),
                                      'total': totals.get(promo['id'], 0),
                                      'last': max((p['at'] for p in mine), default=None)}})
        last = last_promo(plays)
        return {'settings': settings, 'promos': listed, 'problems': dict(self.library.problems), 'values': values,
                'errors': errors, 'master': worker, 'recent': plays[-40:][::-1], 'last': last, 'counted_since': since,
                'next_due': None if last is None else last + settings['every'] * 60,
                'due': due(settings, last, now), 'every_choices': list(EVERY_CHOICES), 'now': round(now, 1)}

    def overlay_png(self, promo_id, index):
        """One of a promo's overlays as it would read now (a PNG of its box size), for the
        page's preview player; sample words where a value is not known."""
        promo = next((p for p in self.library.read() if p['id'] == promo_id), None)
        if promo is None or not 0 <= index < len(promo['overlays']):
            raise ConfigError('No such overlay')
        spec = promo['overlays'][index]
        text = promo_overlay.field_text(spec['field'], self._sample(), self.clock())
        surface = promo_overlay.render(spec['style'], text or '', spec['box'][2], spec['box'][3])
        buffer = io.BytesIO()
        surface.write_to_png(buffer)
        return buffer.getvalue()

    def still_png(self, promo_id):
        """A promo's still with its live text as it would read now."""
        import cairo
        promo = next((p for p in self.library.read() if p['id'] == promo_id), None)
        if promo is None or not promo['still'] or not (self.library.folder / promo['still']).is_file():
            raise ConfigError('No still for that promo')
        surface = cairo.ImageSurface.create_from_png(str(self.library.folder / promo['still']))
        promo_overlay.draw(cairo.Context(surface), promo['overlays'], self._sample(), promo['still_at'], self.clock())
        buffer = io.BytesIO()
        surface.write_to_png(buffer)
        return buffer.getvalue()

    def _sample(self):
        """The live values, or stand-ins for the page where one is not known yet."""
        values = fresh(self.store.values(), self.clock())
        place = (self.weather.status().get('place') if self.weather is not None else None) or 'Reagan National'
        values.setdefault('temperature', {'f': 72, 'place': place})
        values.setdefault('programme', {'title': 'Jeopardy!'})
        return values
