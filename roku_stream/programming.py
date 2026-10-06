"""Programming blocks: a weekly grid, scheduled shows and game mode -> the master queue.

Modelled on Cairo Radio's log resolution. Precedence: scheduled show > grid block
> OFF AIR. Unpainted grid time is OFF AIR, and master returns to its test card.

The engine does not cut master itself. A few minutes before each change it adds
an entry to the source queue, so Pause, Retry/Skip and the startup review still
apply. A scheduled entry that is released after its segment has ended is
skipped as superseded rather than aired for a moment.

Game mode airs a game (any league in sports.LEAGUES), then a backup once the game is final.
The backup is a fixed program, or SCHEDULE: whatever the weekly grid and program
shows have at that moment, so a game preempts the grid (priority 2 over the
grid's 3) and hands back to it. An overrunning game holds the queue (the backup
waits on the game) and the backup is skipped if the game ends after its reserved window.

Shows may overlap, but not start at the same time. A later show takes over from
its start. A game's window ends where the next show starts: the queue keeps the
game on air until it is final, then joins the next show or game in progress.

Each show has a priority (low, normal, high). A show that outranks what holds master
cuts in at its start: a game on air before its final, or a take held to an end time
(normal). Of equal priority, what is on air keeps master, as above. A program show
starting inside one that outranks it waits for that one to end.

Scheduled games follow MLB and ESPN until they start (follow_games): a moved game
takes its window with it, a series winner replaces "ATL/PHI" in the title, and a
cancelled game, or one its feed stops listing (an if-necessary game), is removed.
"""
from __future__ import annotations

import copy
from datetime import datetime, time as dtime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .errors import ConfigError
from .scheduler import parse_time, utc_now
from .sports import LEAGUES

OFF_AIR = {'source_id': 'off-air', 'channel_id': 'off-air'}
SCHEDULE = {'source_id': 'schedule', 'channel_id': 'schedule'}  # A game backup that returns to the grid.
CELLS = 48  # Half-hour cells per day.
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
LOOKAHEAD = timedelta(minutes=10)
HISTORY = timedelta(days=7)
GAME_CHECK = timedelta(minutes=10)  # How often scheduled games are checked against their feeds.
GONE_AFTER = timedelta(minutes=20)  # Missing from its feed this long, a game was dropped (not a blip).
REMOVED_KEPT = timedelta(days=2)    # How long games removed by their feeds stay listed.
# A show's priority, lowest first; its rank is the index. Grid blocks, OFF AIR and entries
# queued by hand are normal.
PRIORITIES = ('low', 'normal', 'high')
NORMAL = PRIORITIES.index('normal')
_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
log = logging.getLogger(__name__)


def system_zone():
    key = os.environ.get('TZ', '').lstrip(':')
    if not key:
        try:
            key = Path('/etc/timezone').read_text().strip()
        except OSError:
            try:
                key = os.readlink('/etc/localtime').split('zoneinfo/', 1)[1]
            except (OSError, IndexError):
                key = 'UTC'
    try:
        return ZoneInfo(key)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo('UTC')


def empty():
    return {'version': 1, 'enabled': False, 'blocks': [],
            'grid': {day: [None] * CELLS for day in DAYS}, 'shows': []}


def _text(value, name, limit=48):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ConfigError(f'{name} must be a single line of at most {limit} characters')
    return value.strip()


def _priority(value):
    if value not in PRIORITIES:
        raise ConfigError('priority must be one of ' + ', '.join(PRIORITIES))
    return value


def show_rank(show):
    return PRIORITIES.index(show.get('priority') or 'normal')


def target_key(target):
    key = {k: target.get(k) for k in ('source_id', 'channel_id', 'date')}
    if target.get('antenna') is False:
        key['antenna'] = False  # YouTube TV only (networks.py); other targets keep their old keys.
    return json.dumps(key, sort_keys=True)


class Programming:
    def __init__(self, state_file, queue, *, normalize=None, game=None, locate=None, zone=None,
                 poll_seconds=15, start_worker=True):
        """normalize(target) validates a source target; game(league, id, date) returns a game;
        locate(league, id) finds a game on whatever date it is now, or None once its feed no longer lists it."""
        self.path = Path(state_file)
        self.queue = queue
        self.normalize = normalize or (lambda target: target)
        self.game = game
        self.locate = locate
        self.zone = zone or system_zone()
        self.poll_seconds = poll_seconds
        self.lock = threading.Lock()
        self.sync_lock = threading.Lock()
        self.follow_lock = threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.closed = False
        self.last_sync = None
        self.last_game_check = None
        self.data = self._load()
        self.thread = None
        self.follower = None
        if start_worker:
            self.start()

    # Persistence -----------------------------------------------------------
    def _load(self):
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            return empty()
        except (OSError, ValueError) as exc:
            raise ConfigError(f'Cannot read programming state {self.path}: {exc}') from exc
        if not isinstance(raw, dict) or raw.get('version') != 1:
            raise ConfigError('Unsupported programming state')
        return raw

    def _save_locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.programming-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(self.data, stream, indent=2)
                stream.write('\n')
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)

    # Validation ------------------------------------------------------------
    def _target(self, value):
        if not isinstance(value, dict):
            raise ConfigError('target must be an object')
        if value.get('source_id') == OFF_AIR['source_id']:
            return dict(OFF_AIR)
        return self.normalize(dict(value))

    def validate_grid(self, value):
        """Validate blocks and grid; unchanged block targets are not re-resolved."""
        if not isinstance(value, dict):
            raise ConfigError('Programming requires enabled, blocks and grid')
        enabled = value.get('enabled')
        if not isinstance(enabled, bool):
            raise ConfigError('enabled must be true or false')
        blocks = value.get('blocks')
        if not isinstance(blocks, list) or len(blocks) > 64:
            raise ConfigError('blocks must be a list of at most 64 programming blocks')
        with self.lock:
            known = {b['id']: b for b in self.data['blocks']}
        result = []
        for block in blocks:
            if not isinstance(block, dict):
                raise ConfigError('Invalid programming block')
            block_id = block.get('id') or uuid.uuid4().hex
            if not isinstance(block_id, str) or not re.fullmatch(r'[0-9a-zA-Z_-]{1,40}', block_id):
                raise ConfigError('Invalid block id')
            color = block.get('color') or '#3a6f8f'
            if not isinstance(color, str) or not _COLOR.match(color):
                raise ConfigError('Block color must be #rrggbb')
            old = known.get(block_id)
            target = (old['target'] if old and isinstance(block.get('target'), dict)
                      and target_key(old['target']) == target_key(block['target']) else self._target(block.get('target')))
            result.append({'id': block_id, 'name': _text(block.get('name'), 'Block name'),
                           'color': color.lower(), 'target': target})
        ids = [b['id'] for b in result]
        if len(set(ids)) != len(ids):
            raise ConfigError('Block ids must be unique')
        grid = value.get('grid')
        if not isinstance(grid, dict) or set(grid) != set(DAYS):
            raise ConfigError('grid requires mon through sun')
        for day, cells in grid.items():
            if (not isinstance(cells, list) or len(cells) != CELLS
                    or any(cell is not None and cell not in ids for cell in cells)):
                raise ConfigError(f'grid.{day} must list {CELLS} half-hour cells of block ids or null')
        return {'enabled': enabled, 'blocks': result, 'grid': {d: list(grid[d]) for d in DAYS}}

    def save_grid(self, value):
        value = self.validate_grid(value)
        with self.lock:
            self.data.update(value)
            self._save_locked()
            self.wake.notify_all()
        self.sync()
        return self.describe()

    def add_show(self, value):
        if not isinstance(value, dict):
            raise ConfigError('A show must be an object')
        mode = value.get('mode', 'program')
        if mode not in ('program', 'game'):
            raise ConfigError('mode must be program or game')
        start, end = value.get('start'), value.get('end')
        if not isinstance(start, str) or not isinstance(end, str):
            raise ConfigError('start and end must be ISO-8601 timestamps with a timezone')
        start, end = parse_time(start), parse_time(end)
        if end <= start or end - start > timedelta(hours=12):
            raise ConfigError('A show must end after it starts and last at most 12 hours')
        if end <= utc_now():
            raise ConfigError('This show has already ended')
        show = {'id': uuid.uuid4().hex, 'mode': mode, 'start': start.isoformat(), 'end': end.isoformat(),
                'priority': _priority(value.get('priority') or 'normal')}
        if mode == 'game':
            game = value.get('game')
            if not isinstance(game, dict):
                raise ConfigError('Game mode requires a game')
            league = game.get('league', 'mlb')
            if league not in LEAGUES:
                raise ConfigError('league must be one of ' + ', '.join(LEAGUES))
            pk, day = game.get('game_pk'), game.get('game_date')
            if isinstance(pk, bool) or not isinstance(pk, int) or not isinstance(day, str):
                raise ConfigError('game requires integer game_pk and game_date')
            if self.game is None:
                raise ConfigError('Sports schedules are not configured')
            info = self.game(league, pk, day)
            title = str(info.get('title') or f'{league.upper()} game {pk}')
            show['game'] = {'league': league, 'game_pk': pk, 'game_date': day, 'title': title}
            if info.get('start_time') and not info.get('start_time_tbd'):
                # The window may open before the first pitch; a move shifts it by as much as the game.
                show['game_start'] = parse_time(info['start_time']).isoformat()
            # MLB can route itself (national channel or MLB.TV). Other leagues need
            # the channel carrying the game: YouTube TV or an over-the-air TV-Thing station.
            target = value.get('target')
            if target is None and league != 'mlb':
                raise ConfigError('Choose the source carrying this game')
            show['target'] = self._target(target or {'source_id': 'mlb', 'channel_id': str(pk), 'date': day})
            if show['target']['source_id'] == 'off-air':
                raise ConfigError('A game needs a source, not OFF AIR')
            backup = value.get('backup')
            if isinstance(backup, dict) and backup.get('source_id') == SCHEDULE['source_id']:
                show['backup'], show['backup_title'] = dict(SCHEDULE), 'Schedule'
            else:
                show['backup'] = self._target(backup)
                show['backup_title'] = _text(value.get('backup_title') or 'Backup program', 'Backup title')
            show['title'] = _text(value.get('title') or title, 'Show title', 72)
        else:
            show['target'] = self._target(value.get('target'))
            show['title'] = _text(value.get('title'), 'Show title', 72)
        with self.lock:
            for other in self.data['shows']:
                if parse_time(other['start']) == start:
                    raise ConfigError(f'"{other["title"]}" starts at the same time. Start this one later '
                                      'and it follows when that one ends')
                if mode == 'game' and other.get('game') and (
                        (other['game']['league'], other['game']['game_pk']) == (show['game']['league'], show['game']['game_pk'])):
                    raise ConfigError(f'{show["game"]["title"]} is already scheduled')
            cutoff = utc_now() - timedelta(days=7)
            self.data['shows'] = sorted([s for s in self.data['shows'] if parse_time(s['end']) > cutoff] + [show],
                                        key=lambda s: s['start'])
            self._save_locked()
        self.sync()
        return copy.deepcopy(show)

    def set_priority(self, show_id, priority):
        """Change a show's priority; None if it is unknown. Up next reads it live, so a game
        already on air is cut, or kept, from now on."""
        priority = _priority(priority)
        with self.lock:
            show = next((s for s in self.data['shows'] if s['id'] == show_id), None)
            if show is None:
                return None
            show['priority'] = priority
            self._save_locked()
        self.sync()
        return self.describe()

    def rank(self, key):
        """The priority rank of an Up next entry from its schedule key: its show's (a game's
        return to the schedule has the game's), else normal (grid blocks, OFF AIR)."""
        parts = (key or '').split('|', 3)
        if len(parts) != 4 or parts[1] not in ('show', 'game', 'backup'):
            return NORMAL
        show_id = parts[2].split(':', 1)[0]
        with self.lock:
            show = next((s for s in self.data['shows'] if s['id'] == show_id), None)
        return show_rank(show) if show else NORMAL

    def remove_show(self, show_id):
        with self.lock:
            shows = [s for s in self.data['shows'] if s['id'] != show_id]
            if len(shows) == len(self.data['shows']):
                return None
            self.data['shows'] = shows
            self._save_locked()
        self.sync()
        return self.describe()

    # Following the sports feeds ----------------------------------------------
    def follow_games(self, now=None):
        """Bring scheduled games that have not started in line with MLB and ESPN.
        A feed that cannot be reached changes nothing. Returns what changed."""
        now = now or utc_now()
        if self.locate is None:
            return []
        with self.follow_lock:
            with self.lock:
                pending = [(s['id'], s['game']['league'], s['game']['game_pk']) for s in self.data['shows']
                           if s['mode'] == 'game' and parse_time(s['start']) > now]
            found = {}
            for show_id, league, pk in pending:
                try:
                    found[show_id] = self.locate(league, pk)
                except Exception as exc:  # Retried at the next check.
                    log.warning('Could not check %s game %s: %s', league.upper(), pk, exc)
            changes, kept, saved = [], [], False
            with self.lock:
                before = json.dumps(self.data['shows'], sort_keys=True)
                for show in self.data['shows']:
                    note, keep = (self._follow(show, found[show['id']], now)
                                  if show['id'] in found and parse_time(show['start']) > now else (None, True))
                    if keep:
                        kept.append(show)
                    if note:
                        changes.append({'at': now.isoformat(), 'show_id': show['id'], 'title': show['title'],
                                        'start': show['start'], 'league': show['game']['league'], 'text': note,
                                        'removed': not keep})
                        if keep:
                            show['update'] = {'at': now.isoformat(), 'text': note}
                self.data['shows'] = sorted(kept, key=lambda s: s['start'])
                removed = [c for c in changes if c['removed']] + self.data.get('removed', [])
                self.data['removed'] = [c for c in removed if now - parse_time(c['at']) < REMOVED_KEPT][:20]
                if changes or json.dumps(self.data['shows'], sort_keys=True) != before:
                    self._save_locked()
                    saved = True
                self.last_game_check = now.isoformat()
        for change in changes:
            log.info('%s: %s', change['title'], change['text'])
        if saved:
            self.sync(now)
        return changes

    def _follow(self, show, game, now):
        """Apply a game's current listing to its show: (what changed or None, keep the show)."""
        info, league = show['game'], show['game']['league'].upper()
        if game is None:
            since = parse_time(show.setdefault('missing_since', now.isoformat()))
            return (f'No longer on the {league} schedule', False) if now - since >= GONE_AFTER else (None, True)
        show.pop('missing_since', None)
        if game.get('cancelled'):
            return f'Cancelled on the {league} schedule', False
        notes = []
        if game.get('title') and game['title'] != info['title']:
            if show['title'] == info['title']:
                show['title'] = game['title'][:72]
            notes.append(f'Was {info["title"]}')
            info['title'] = game['title']
        if game.get('game_date') and game['game_date'] != info['game_date']:
            info['game_date'] = game['game_date']
            if show['target'].get('date') and str(show['target'].get('channel_id')) == str(info['game_pk']):
                show['target']['date'] = game['game_date']  # MLB and Sunday Ticket targets name the game's date.
        if game.get('start_time') and not game.get('start_time_tbd'):
            new = parse_time(game['start_time'])
            old = parse_time(show.get('game_start') or show['start'])
            if new != old:
                was, start, end = parse_time(show['start']), parse_time(show['start']) + (new - old), parse_time(show['end']) + (new - old)
                start = max(start, now + timedelta(minutes=1))  # Moved earlier and under way: air it now.
                show['start'], show['end'] = start.isoformat(), max(end, start + timedelta(minutes=30)).isoformat()
                notes.insert(0, f'Moved from {self._clock(was, start)}')
            show['game_start'] = new.isoformat()
        return ('. '.join(notes) or None), True

    def _clock(self, at, near):
        """'2:00 PM', with the weekday when it is not near's day."""
        at, near = at.astimezone(self.zone), near.astimezone(self.zone)
        text = f'{at.hour % 12 or 12}:{at:%M} {"AM" if at.hour < 12 else "PM"}'
        return text if at.date() == near.date() else f'{at:%a} {text}'

    # Resolution ------------------------------------------------------------
    def _grid_segments(self, data, start, end):
        blocks = {b['id']: b for b in data['blocks']}
        segments = []
        day = start.astimezone(self.zone).date() - timedelta(days=1)
        while True:
            midnight = datetime.combine(day, dtime(), self.zone)
            if midnight >= end:
                break
            cells = data['grid'][DAYS[day.weekday()]]
            for index, block_id in enumerate(cells):
                cell_start = datetime.combine(day, dtime(index // 2, 30 * (index % 2)), self.zone)
                cell_end = (datetime.combine(day + timedelta(days=1), dtime(), self.zone) if index == CELLS - 1
                            else datetime.combine(day, dtime((index + 1) // 2, 30 * ((index + 1) % 2)), self.zone))
                cell_start, cell_end = cell_start.astimezone(timezone.utc), cell_end.astimezone(timezone.utc)
                if cell_end <= start or cell_start >= end:
                    continue
                block = blocks.get(block_id)
                ref = block['id'] if block else None
                if segments and segments[-1]['ref'] == ref and segments[-1]['end'] == cell_start:
                    segments[-1]['end'] = cell_end
                    continue
                segments.append({'start': cell_start, 'end': cell_end, 'ref': ref,
                                 'kind': 'block' if block else 'off_air',
                                 'title': block['name'] if block else 'OFF AIR',
                                 'color': block['color'] if block else None,
                                 'target': block['target'] if block else dict(OFF_AIR)})
            day += timedelta(days=1)
        for segment in segments:
            segment['start'], segment['end'] = max(segment['start'], start), min(segment['end'], end)
        return segments

    @staticmethod
    def _windows(shows):
        """(show, start, end) in start order. A game's window ends where the next show starts:
        the queue holds the game until it is final, then joins that show in progress.
        Of two shows starting together, a game its feed has stopped listing gives way."""
        shows = sorted(shows, key=lambda s: (parse_time(s['start']), 'missing_since' not in s))
        result = []
        for index, show in enumerate(shows):
            s_start, s_end = parse_time(show['start']), parse_time(show['end'])
            if show['mode'] == 'game':
                s_end = min([s_end, *(parse_time(o['start']) for o in shows[index + 1:]
                                      if s_start < parse_time(o['start']) < s_end)])
            result.append((show, s_start, s_end))
        return result

    def timeline(self, start, end, data=None):
        """Segments covering [start, end): OFF AIR is populated wherever nothing is scheduled.
        A later show overrides an earlier one from its start, unless the earlier one outranks it."""
        with self.lock:
            data = copy.deepcopy(data or self.data)
        segments = self._grid_segments(data, start, end)
        # Lower priorities are laid down first; within one, in start order (a stable sort).
        for show, s_start, s_end in sorted(self._windows(data['shows']), key=lambda w: show_rank(w[0])):
            if s_end <= start or s_start >= end:
                continue
            carved = []
            for segment in segments:
                if segment['end'] <= s_start or segment['start'] >= s_end:
                    carved.append(segment)
                    continue
                if segment['start'] < s_start:
                    carved.append({**segment, 'end': s_start})
                if segment['end'] > s_end:
                    carved.append({**segment, 'start': s_end})
            carved.append({'start': max(s_start, start), 'end': min(s_end, end), 'ref': show['id'],
                           'kind': 'game' if show['mode'] == 'game' else 'show', 'title': show['title'],
                           'color': None, 'target': show['target'], 'show': show})
            segments = sorted(carved, key=lambda s: s['start'])
        return segments

    def transitions(self, start, end):
        """Queue entries implied by the timeline for changes within [start, end)."""
        # A wide window gives every segment its real start and end.
        with self.lock:
            data = copy.deepcopy(self.data)
        segments = self.timeline(start - timedelta(days=1), end + timedelta(days=8), data)
        runs = []
        for segment in segments:
            # Consecutive segments on the same source need no cut. A game always
            # starts its own run because its backup must follow it in the queue.
            last = runs[-1][-1] if runs else None
            if (last and 'game' not in (last['kind'], segment['kind'])
                    and target_key(last['target']) == target_key(segment['target'])):
                runs[-1].append(segment)
            else:
                runs.append([segment])
        result = []
        for run in runs:
            first = run[0]
            if start <= first['start'] < end:
                result.extend(self._entries(first, run[-1]['end'], data))
        return result

    def _entries(self, segment, run_end, data):
        show = segment.get('show')
        if not show or show['mode'] != 'game':
            return [self._transition(segment, segment['target'], segment['title'], skip_after=run_end)]
        # The game itself is never superseded: an overrun keeps it on air.
        entries = [{**self._transition(segment, segment['target'], segment['title'], skip_after=None),
                    'game': dict(show['game'])}]
        if show['backup'].get('source_id') == SCHEDULE['source_id']:
            # One gated entry per schedule change in the game's window (up to the next show):
            # after the final, the one whose slot is current airs and the rest follow at their
            # times. The schedule here is the grid and program shows, never another game.
            parts = []
            programs = {**data, 'shows': [s for s in data['shows'] if s['mode'] != 'game']}
            # From where the game airs: a show that outranks it may hold it back past its start.
            for part in self.timeline(segment['start'], run_end, programs):
                if parts and target_key(parts[-1]['target']) == target_key(part['target']):
                    parts[-1]['end'] = part['end']
                else:
                    parts.append({**part, 'ref': f"{show['id']}:{part['ref']}"})
            backups = [self._transition(p, p['target'], p['title'], skip_after=p['end'], kind='backup') for p in parts]
        else:
            backups = [self._transition(segment, show['backup'], show['backup_title'],
                                        skip_after=run_end, kind='backup')]
        for backup in backups:
            backup['after_game'] = dict(show['game'])
        return entries + backups

    @staticmethod
    def _transition(segment, target, title, *, skip_after, kind=None):
        kind, at = kind or segment['kind'], segment['start']
        return {'key': '|'.join((at.isoformat(), kind, str(segment['ref']), target_key(target))),
                'run_at': at.isoformat(), 'target': dict(target), 'title': title, 'kind': kind,
                'skip_after': skip_after.isoformat() if skip_after else None}

    # Queue synchronisation -------------------------------------------------
    def sync(self, now=None):
        now = now or utc_now()
        with self.lock:
            enabled = self.data['enabled']
        with self.sync_lock:
            return self._sync_locked(now, enabled)

    def _sync_locked(self, now, enabled):
        wanted = {t['key']: t for t in self.transitions(now - HISTORY, now + LOOKAHEAD)} if enabled else {}
        items = self.queue.list()
        present = {i.schedule_key for i in items if getattr(i, 'schedule_key', None)}
        for item in items:
            # Waiting entries from an edited or disabled schedule are withdrawn.
            # Blocked entries stay for the operator to Retry or Skip.
            if getattr(item, 'origin', None) == 'programming' and item.status == 'queued' and item.schedule_key not in wanted:
                try:
                    self.queue.remove(item.id)
                except ConfigError:
                    pass  # Released since it was listed.
        added = []
        for key, transition in sorted(wanted.items(), key=lambda kv: kv[1]['run_at']):
            if key in present or parse_time(transition['run_at']) <= now:
                continue
            added.append(self.queue.add_scheduled(transition))
        with self.lock:
            self.last_sync = now.isoformat()
        return added

    def colors(self):
        """Block colors by block id."""
        with self.lock:
            return {b['id']: b['color'] for b in self.data['blocks']}

    def segment_at(self, at):
        """The schedule's segment at a moment, or None while the schedule is off."""
        if not self.enabled:
            return None
        return next(iter(self.timeline(at, at + timedelta(minutes=1))), None)

    @property
    def enabled(self):
        with self.lock:
            return self.data['enabled']

    def take_current(self, now=None, first=False):
        """Queue whatever the schedule says should be on air now, releasing in two seconds.
        first puts it at the head of Up next, in front of entries waiting on a game."""
        now = now or utc_now()
        with self.sync_lock:
            at = (now + timedelta(seconds=2)).isoformat()
            wanted = [{**t, 'run_at': at} for t in self._current(now)]
            # At the head, the last one goes in first so the game stays ahead of its backups.
            added = [self.queue.add_scheduled(t, first=first) for t in (reversed(wanted) if first else wanted)]
            return added[::-1] if first else added

    def _current(self, now):
        """The schedule's transitions on now that Up next does not already have, game first."""
        past = [t for t in self.transitions(now - HISTORY, now + timedelta(seconds=1))
                if parse_time(t['run_at']) <= now]
        if not past:
            raise ConfigError('Nothing has been scheduled in the last week')
        # A game and its backup share one start time.
        current = [t for t in past if t['run_at'] == past[-1]['run_at']]
        present = {i.schedule_key for i in self.queue.list()
                   if getattr(i, 'schedule_key', None) and i.status in ('queued', 'blocked', 'running')}
        return [t for t in current if t['key'] not in present]

    def on_now(self, now=None):
        """What take_back would put on air now if a manual take ended with nothing waiting
        (a transition: target, title, key), or None: OFF AIR, the schedule off, or its entry
        already in Up next. The queue asks, to prepare it early; it takes no sync lock."""
        now = now or utc_now()
        if not self.enabled:
            return None
        try:
            wanted = self._current(now)
        except ConfigError:
            return None
        return wanted[0] if wanted else None

    def take_back(self, hold, now=None):
        """A manual take's end has come: queue the current block at the head of Up next,
        or OFF AIR when the schedule is off. Nothing is added when Up next already has
        an entry ready to follow the take."""
        now = now or utc_now()
        if self.queue.follows_hold(hold, now):
            return []
        if self.enabled:
            try:
                return self.take_current(now, first=True)
            except ConfigError:
                pass  # Nothing scheduled this week: OFF AIR.
        return [self.queue.add_scheduled({'target': dict(OFF_AIR), 'title': 'End of manual take',
                                          'run_at': (now + timedelta(seconds=2)).isoformat()},
                                         origin='manual_end', first=True)]

    def next_program(self, now=None, exclude=()):
        """The next scheduled change whose entry is not already queued, OFF AIR included:
        Up next shows the test card coming up where the schedule has nothing."""
        now = now or utc_now()
        with self.lock:
            if not self.data['enabled']:
                return None
        return next((t for t in self.transitions(now, now + HISTORY + timedelta(days=1))
                     if t['kind'] != 'backup' and t['key'] not in exclude
                     and parse_time(t['run_at']) > now), None)

    def upcoming_shows(self, now=None, exclude=(), limit=12):
        """Scheduled shows and games that have not started, except those whose id is in exclude."""
        now = now or utc_now()
        with self.lock:
            if not self.data['enabled']:
                return []
            shows = copy.deepcopy(self.data['shows'])
        return [s for s in shows if parse_time(s['start']) > now and s['id'] not in exclude][:limit]

    def describe(self, now=None, hours=24):
        now = now or utc_now()
        with self.lock:
            data = copy.deepcopy(self.data)
            last_sync, last_game_check = self.last_sync, self.last_game_check

        def public(segment):
            result = {k: v for k, v in segment.items() if k not in ('show',)}
            result['start'], result['end'] = segment['start'].isoformat(), segment['end'].isoformat()
            if segment.get('show', {}).get('mode') == 'game':
                show = segment['show']
                result.update(game=show['game'], backup=show['backup'], backup_title=show['backup_title'])
            return result

        timeline = [public(s) for s in self.timeline(now, now + timedelta(hours=hours), data)]
        return {'settings': data, 'timezone': str(self.zone), 'now': now.isoformat(),
                'on_now': timeline[0] if timeline else None, 'timeline': timeline,
                'lookahead_minutes': int(LOOKAHEAD.total_seconds() // 60), 'last_sync': last_sync,
                'games_checked_at': last_game_check, 'game_check_minutes': int(GAME_CHECK.total_seconds() // 60),
                'game_gone_minutes': int(GONE_AFTER.total_seconds() // 60),
                'upcoming_transitions': self.transitions(now, now + timedelta(hours=hours)) if data['enabled'] else []}

    # Worker ------------------------------------------------------------------
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='programming', daemon=True)
            self.thread.start()
        if self.follower is None and self.locate is not None:
            # Its own thread: a slow feed must not hold up queueing the next change.
            self.follower = threading.Thread(target=self._follow_run, name='programming-games', daemon=True)
            self.follower.start()

    def _run(self):
        while True:
            with self.lock:
                if self.closed:
                    return
            try:
                self.sync()
            except Exception:  # Keep scheduling alive; the next pass retries.
                log.exception('Programming sync failed')
            with self.lock:
                if self.closed:
                    return
                self.wake.wait(self.poll_seconds)

    def _follow_run(self):
        while True:
            try:
                self.follow_games()
            except Exception:
                log.exception('Following scheduled games failed')
            deadline = time.monotonic() + GAME_CHECK.total_seconds()
            with self.lock:
                while not self.closed and time.monotonic() < deadline:
                    self.wake.wait(deadline - time.monotonic())
                if self.closed:
                    return

    def close(self):
        with self.lock:
            self.closed = True
            self.wake.notify_all()
        for thread in (self.thread, self.follower):
            if thread:
                thread.join(timeout=5)
