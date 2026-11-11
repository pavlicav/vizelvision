"""Programming: the weekly lineup, scheduled shows and game mode -> the master queue.

Modelled on Cairo Radio's log resolution. Precedence: scheduled show > lineup slot
> OFF AIR. Time no slot covers is OFF AIR, and master returns to its test card.

The lineup (lineup.py, since 2026-11-09) is a list of slots: days of the week, a start to
the minute, a length, and what airs. A slot airs a fixed channel, a programme by name that
is looked up in the listings each time (so the channel follows the programme, and its
listed times), or the next file of a library folder. Where slots overlap, the higher
priority has the time, then the one starting later; the other resumes when it ends. Each
airing is a 'block' segment, as the painted grid's were. Until then the lineup was a grid
of half-hour cells naming blocks; such a body is still accepted (save_grid) and becomes
slots. Sports slots ("Monday Night Football") are rules that sports_slots.SportsSlots
turns into game shows.

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
(between normal and high). Of equal priority, what is on air keeps master, as above. A
program show starting inside one that outranks it waits for that one to end.

A favorite's game (favorites.py) at normal ranks a little above normal, the higher on the
favorites list the more, still below a take held by hand: of two favorites' games the
higher one cuts in on the other. One starting with another show starts a second before
it, or a second after one that outranks it, and so goes on first or waits for its final.

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

from . import lineup
from .errors import ConfigError, RokuStreamError
from .lineup import CELLS, DAYS, occurrences, signature
from .scheduler import parse_time, utc_now
from .sports import LEAGUES, YOUTUBE_TV_MARKET

OFF_AIR = {'source_id': 'off-air', 'channel_id': 'off-air'}
SCHEDULE = {'source_id': 'schedule', 'channel_id': 'schedule'}  # A game backup that returns to the grid.
LOOKAHEAD = timedelta(minutes=10)
# An airing is pinned (its source settled, and saved) from this long before it starts: the
# listings may change under an entry already in Up next, and its key must not.
PIN_AHEAD = LOOKAHEAD + timedelta(minutes=5)
PINS_KEPT = timedelta(days=1)
# A slot following a programme takes the listed start and end when they are this close.
FOLLOW = timedelta(minutes=45)
HISTORY = timedelta(days=7)
GAME_CHECK = timedelta(minutes=10)  # How often scheduled games are checked against their feeds.
GONE_AFTER = timedelta(minutes=20)  # Missing from its feed this long, a game was dropped (not a blip).
REMOVED_KEPT = timedelta(days=2)    # How long games removed by their feeds stay listed.
# A show's priority, lowest first; its rank is the index. Grid blocks, OFF AIR and entries
# queued by hand are normal.
PRIORITIES = ('low', 'normal', 'high')
NORMAL = PRIORITIES.index('normal')
# How far above normal the top favorite's game ranks; the last one ranks just above normal.
# A take held by hand ranks normal + 0.5 (source_queue.HELD), above every favorite.
FAVORITE_SPAN = 0.4
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
    """An empty body of the old grid (save_grid): no blocks, nothing painted."""
    return {'version': 1, 'enabled': False, 'blocks': [],
            'grid': {day: [None] * CELLS for day in DAYS}, 'shows': []}


def fresh():
    """Empty programming state. pins: airings whose source is settled ("slot|date").
    cursors: the last file each library slot aired. planned: the games sports slots put on."""
    return {'version': 2, 'enabled': False, 'slots': [], 'sports': [], 'shows': [], 'removed': [],
            'pins': {}, 'cursors': {}, 'planned': {}}


def _natural(value):
    """Sorts 'Season 2' before 'Season 10'."""
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r'(\d+)', str(value))]


def _text(value, name, limit=48):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ConfigError(f'{name} must be a single line of at most {limit} characters')
    return value.strip()


def _priority(value):
    if value not in PRIORITIES:
        raise ConfigError('priority must be one of ' + ', '.join(PRIORITIES))
    return value


def show_rank(show, favorites=()):
    """A show's priority rank: its index in PRIORITIES. favorites is the ranked favorites
    list: a favorite's game at normal ranks above normal by its best favorite's place."""
    rank = PRIORITIES.index(show.get('priority') or 'normal')
    places = [favorites.index(f) for f in show.get('favorites') or () if f in favorites]
    if rank == NORMAL and places:
        rank += FAVORITE_SPAN * (len(favorites) - min(places)) / len(favorites)
    return rank


def target_key(target):
    key = {k: target.get(k) for k in ('source_id', 'channel_id', 'date')}
    if target.get('antenna') is False:
        key['antenna'] = False  # YouTube TV only (networks.py); other targets keep their old keys.
    return json.dumps(key, sort_keys=True)


class Programming:
    def __init__(self, state_file, queue, *, normalize=None, game=None, locate=None, zone=None,
                 poll_seconds=15, start_worker=True, guide=None, library=None):
        """normalize(target) validates a source target; game(league, id, date) returns a game;
        locate(league, id) finds a game on whatever date it is now, or None once its feed no longer lists it.
        guide: the listings by programme (guide_index.GuideIndex), for slots that follow one.
        library(): the media library's items, for slots that air a folder."""
        self.path = Path(state_file)
        self.queue = queue
        self.normalize = normalize or (lambda target: target)
        self.game = game
        self.locate = locate
        self.guide = guide
        self.library = library
        self._targets = {}   # target key -> (checked at, normalized target or None)
        self._files = (None, [])
        self._roots = {}
        # The ranked favorites list, read live (favorites.Favorites.order).
        self.favorites = lambda: []
        # The sports planner's wake, when a sports slot changes (sports_slots.SportsSlots.poke).
        self.sports_changed = lambda: None
        self.zone = zone or system_zone()
        self.poll_seconds = poll_seconds
        self.lock = threading.Lock()
        self.sync_lock = threading.Lock()
        self.follow_lock = threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.closed = False
        self.last_sync = None
        self.last_game_check = None
        self.migrated = False
        self.data = self._load()
        if self.migrated:
            with self.lock:
                self._save_locked()
        self.thread = None
        self.follower = None
        if start_worker:
            self.start()

    # Persistence -----------------------------------------------------------
    def _load(self):
        try:
            raw = json.loads(self.path.read_text())
        except FileNotFoundError:
            return fresh()
        except (OSError, ValueError) as exc:
            raise ConfigError(f'Cannot read programming state {self.path}: {exc}') from exc
        if not isinstance(raw, dict) or raw.get('version') not in (1, 2):
            raise ConfigError('Unsupported programming state')
        data = fresh()
        if raw['version'] == 1:
            # The painted grid becomes slots. The grid as it was is kept beside the state.
            try:
                kept = self.path.with_name(self.path.stem + '.v1.json')
                if not kept.exists():
                    kept.write_text(json.dumps(raw, indent=2) + '\n')
                data.update(enabled=raw.get('enabled') is True, shows=raw.get('shows') or [],
                            removed=raw.get('removed') or [],
                            slots=lineup.from_grid(raw.get('blocks') or [], raw['grid']))
            except (OSError, KeyError, TypeError) as exc:
                raise ConfigError(f'Cannot convert the old schedule grid {self.path}: {exc}') from exc
            self.migrated = True
            log.info('Programming: the painted grid is now %d slots (the grid is kept in %s)',
                     len(data['slots']), kept.name)
            return data
        data.update({key: raw[key] for key in data if key in raw and isinstance(raw[key], type(data[key]))})
        return data

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
        """Validate an old grid body (enabled, blocks, grid) and return it as the lineup:
        {enabled, slots}, one slot per run of cells (lineup.from_grid)."""
        if not isinstance(value, dict):
            raise ConfigError('Programming requires enabled, blocks and grid')
        enabled = value.get('enabled')
        if not isinstance(enabled, bool):
            raise ConfigError('enabled must be true or false')
        blocks = value.get('blocks')
        if not isinstance(blocks, list) or len(blocks) > 64:
            raise ConfigError('blocks must be a list of at most 64 programming blocks')
        known = {}
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
        return {'enabled': enabled, 'slots': lineup.from_grid(result, {d: list(grid[d]) for d in DAYS})}

    def save_grid(self, value):
        """Replace the whole lineup with an old grid body. The Schedule page edits slots
        (add_slot, update_slot); this stays for API clients that still send a grid."""
        value = self.validate_grid(value)
        with self.lock:
            self.data.update(value)
            self._save_locked()
            self.wake.notify_all()
        self.sync()
        return self.describe()

    def set_enabled(self, enabled):
        """The automation switch: off withdraws the schedule's waiting entries from Up next."""
        if not isinstance(enabled, bool):
            raise ConfigError('enabled must be true or false')
        with self.lock:
            self.data['enabled'] = enabled
            self._save_locked()
            self.wake.notify_all()
        self.sync()
        return self.describe()

    # The lineup's slots ------------------------------------------------------
    def slots(self):
        with self.lock:
            return copy.deepcopy(self.data['slots'])

    def add_slot(self, value):
        with self.lock:
            count = len(self.data['slots'])
        if count >= lineup.MAX_SLOTS:
            raise ConfigError(f'The lineup holds at most {lineup.MAX_SLOTS} slots')
        slot = lineup.validate_slot(value, self._target, index=count)
        with self.lock:
            if any(other['id'] == slot['id'] for other in self.data['slots']):
                raise ConfigError('Slot ids must be unique')
            self.data['slots'].append(slot)
            self._save_locked()
            self.wake.notify_all()
        self.sync()
        return copy.deepcopy(slot)

    def update_slot(self, slot_id, changes):
        """Change some of a slot's fields; None if it is unknown."""
        if not isinstance(changes, dict):
            raise ConfigError('A slot change must be an object')
        with self.lock:
            old = copy.deepcopy(next((s for s in self.data['slots'] if s['id'] == slot_id), None))
        if old is None:
            return None
        slot = lineup.validate_slot({**old, **changes}, self._target, old=old)
        with self.lock:
            for index, other in enumerate(self.data['slots']):
                if other['id'] == slot_id:
                    self.data['slots'][index] = slot
                    break
            else:
                return None
            self._save_locked()
            self.wake.notify_all()
        self.sync()
        return copy.deepcopy(slot)

    def remove_slot(self, slot_id):
        """Take a slot off the lineup; returns it (to put back), or None if it is unknown."""
        with self.lock:
            slot = next((s for s in self.data['slots'] if s['id'] == slot_id), None)
            if slot is None:
                return None
            self.data['slots'] = [s for s in self.data['slots'] if s['id'] != slot_id]
            self.data['cursors'].pop(slot_id, None)
            for key in [k for k in self.data['pins'] if k.split('|', 1)[0] == slot_id]:
                del self.data['pins'][key]
            self._save_locked()
            self.wake.notify_all()
        self.sync()
        return copy.deepcopy(slot)

    def skip_slot(self, slot_id, day, skip=True):
        """Leave one airing of a slot out (its local date), or put it back."""
        if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) or not isinstance(skip, bool):
            raise ConfigError('Skipping an airing takes its date, YYYY-MM-DD')
        with self.lock:
            slot = next((s for s in self.data['slots'] if s['id'] == slot_id), None)
            if slot is None:
                return None
            lineup.prune_skips(slot, datetime.now(self.zone).date() - timedelta(days=1))
            days = set(slot.get('skip') or ())
            days.add(day) if skip else days.discard(day)
            if len(days) > lineup.MAX_SKIPS:
                raise ConfigError('Too many skipped airings; remove the slot from those days instead')
            slot['skip'] = sorted(days)
            self._save_locked()
            self.wake.notify_all()
        self.sync()
        return copy.deepcopy(slot)

    # Sports slots (sports_slots.SportsSlots plans their games) ------------------
    def sports_slots(self):
        with self.lock:
            return copy.deepcopy(self.data['sports'])

    def add_sports_slot(self, value):
        slot = lineup.validate_sports(value, LEAGUES)
        with self.lock:
            if len(self.data['sports']) >= lineup.MAX_SPORTS:
                raise ConfigError(f'At most {lineup.MAX_SPORTS} sports slots')
            if any(other['id'] == slot['id'] for other in self.data['sports']):
                raise ConfigError('Sports slot ids must be unique')
            self.data['sports'].append(slot)
            self._save_locked()
        self.sports_changed()
        return copy.deepcopy(slot)

    def update_sports_slot(self, slot_id, changes):
        if not isinstance(changes, dict):
            raise ConfigError('A sports slot change must be an object')
        with self.lock:
            old = copy.deepcopy(next((s for s in self.data['sports'] if s['id'] == slot_id), None))
        if old is None:
            return None
        slot = lineup.validate_sports({**old, **changes}, LEAGUES, old=old)
        with self.lock:
            self.data['sports'] = [slot if s['id'] == slot_id else s for s in self.data['sports']]
            self._save_locked()
        self.sports_changed()
        return copy.deepcopy(slot)

    def remove_sports_slot(self, slot_id):
        with self.lock:
            slot = next((s for s in self.data['sports'] if s['id'] == slot_id), None)
            if slot is None:
                return None
            self.data['sports'] = [s for s in self.data['sports'] if s['id'] != slot_id]
            self._save_locked()
        self.sports_changed()
        return copy.deepcopy(slot)

    def planned(self):
        """The games sports slots scheduled: {"league:id": {show_id, start, slot}}."""
        with self.lock:
            return copy.deepcopy(self.data['planned'])

    def note_planned(self, key, show, slot_id):
        with self.lock:
            self.data['planned'][key] = {'show_id': show['id'], 'start': show['start'], 'slot': slot_id}
            self._save_locked()

    def forget_planned(self, keys):
        with self.lock:
            gone = [key for key in keys if key in self.data['planned']]
            for key in gone:
                del self.data['planned'][key]
            if gone:
                self._save_locked()

    def tag_show(self, show_id, **fields):
        """Set fields of a show (the sports planner's: slot, slot_priority, priority)."""
        with self.lock:
            show = next((s for s in self.data['shows'] if s['id'] == show_id), None)
            if show is None:
                return None
            for key, value in fields.items():
                if value is None:
                    show.pop(key, None)
                else:
                    show[key] = _priority(value) if key == 'priority' else value
            self._save_locked()
        self.sync()
        return copy.deepcopy(show)

    def _order(self):
        try:
            return list(self.favorites())
        except Exception:  # No favorites: every show keeps its own priority.
            return []

    def add_show(self, value, favorites=None, slot=None):
        """favorites: the favorites a game is (favorites.matches), when the favorites planner
        adds it; its rank then follows their place on the list. slot: the sports slot whose
        game this is, when the sports planner adds it (it may be a favorite's too)."""
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
        if favorites is not None or slot is not None:
            if mode != 'game':
                raise ConfigError('Only games come from the favorites and sports slots')
            if favorites:
                show['favorites'] = list(favorites)
            show['added_by'] = 'favorites' if slot is None else 'slot'
            if slot is not None:
                show['slot'], show['slot_priority'] = slot, show['priority']
        order = self._order()
        with self.lock:
            if favorites is not None or slot is not None:
                # Starting with another show: first, or after one that outranks it.
                taken, rank, step = {parse_time(o['start']): o for o in self.data['shows']}, show_rank(show, order), None
                while start in taken:
                    step = step or timedelta(seconds=1 if show_rank(taken[start], order) >= rank else -1)
                    start, end = start + step, end + step
                show['start'], show['end'] = start.isoformat(), end.isoformat()
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
        return show_rank(show, self._order()) if show else NORMAL

    def shows(self):
        """Every scheduled show and game, oldest first."""
        with self.lock:
            return copy.deepcopy(self.data['shows'])

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
        # A Sunday regional NFL game on YouTube TV: its CBS or FOX is its own market's station, and
        # Sunday Ticket has the rest (sports._suggest). Its listings decide, once they reach the
        # game; an antenna or other source chosen for it stays.
        regional, target = game.get('regional_target'), show['target']
        family = (target.get('source_id') == 'youtube-tv' and target.get('channel_id') in ('CBS', 'FOX')) or (
            target.get('source_id') == 'sunday-ticket' and str(target.get('channel_id')) == str(info['game_pk']))
        if regional and family and target_key(regional) != target_key(target):
            show['target'] = dict(regional)
            notes.append(f"Now on NFL Sunday Ticket: not on {YOUTUBE_TV_MARKET}'s station" if regional['source_id'] == 'sunday-ticket'
                         else f"Now on YouTube TV's {regional['channel_id']}: {YOUTUBE_TV_MARKET}'s station has it")
        return ('. '.join(notes) or None), True

    def _clock(self, at, near):
        """'2:00 PM', with the weekday when it is not near's day."""
        at, near = at.astimezone(self.zone), near.astimezone(self.zone)
        text = f'{at.hour % 12 or 12}:{at:%M} {"AM" if at.hour < 12 else "PM"}'
        return text if at.date() == near.date() else f'{at:%a} {text}'

    # Resolution ------------------------------------------------------------
    # Where an airing comes from ------------------------------------------------
    def _normalized(self, target):
        """A found channel as a source target, or None when the station cannot tune it.
        Remembered for ten minutes: the lineup is resolved many times a minute."""
        key = target_key(target)
        cached = self._targets.get(key)
        if cached and time.monotonic() - cached[0] < 600:
            return cached[1]
        try:
            found = self.normalize(dict(target))
        except RokuStreamError:
            found = None
        self._targets[key] = (time.monotonic(), found)
        return found

    def _all_files(self):
        """The media library's items, read at most every 30 seconds."""
        at, items = self._files
        if at is None or time.monotonic() - at > 30:
            try:
                listing = (self.library() or ()) if self.library else []
                if isinstance(listing, dict):   # The library's own listing: items, and its roots' names.
                    self._roots = {root['id']: root.get('name') or root['id'] for root in listing.get('roots') or ()}
                    listing = listing.get('items') or ()
                items = list(listing)
            except Exception as exc:  # The library is away: its slots have nothing to air.
                log.warning('Programming: cannot list the media library: %s', exc)
                items = []
            self._files = (time.monotonic(), items)
        return items

    def _library_files(self, what):
        """The playable files a library slot draws from, in its order."""
        items = self._all_files()
        prefix = what.get('path')
        files = [i for i in items if i.get('root') == what['root'] and i.get('playable') is not False
                 and (not prefix or str(i.get('path') or '').startswith(prefix))
                 and (not what.get('name') or i.get('title') == what['name'])]
        # Of a recording kept twice (as aired, and with its ads cut), the cut one.
        best = {}
        for item in files:
            key = (item.get('title'), item.get('aired')) if item.get('aired') else item['id']
            if key not in best or (item.get('variant') or '') == 'no ads':
                best[key] = item
        files = list(best.values())
        if what['order'] == 'newest':
            return sorted(files, key=lambda i: i.get('aired') or i.get('modified') or 0, reverse=True)
        if all(i.get('aired') for i in files):
            return sorted(files, key=lambda i: i['aired'])
        return sorted(files, key=lambda i: _natural(i.get('path') or i['id']))

    def library_folders(self):
        """What of the library a slot can air: each show or collection (a root's top folder),
        each programme recorded more than once, and each root whole. [{root, path, name,
        label, files, minutes (an average file), breaks (ad breaks found), order (the one
        that suits it)}], the biggest first."""
        groups = {}
        for item in self._all_files():
            if item.get('playable') is False or not isinstance(item.get('duration'), (int, float)):
                continue
            path = str(item.get('path') or '')
            keys = [(item['root'], None, None, item.get('collection') if '/' not in path and not item.get('aired') else None)]
            if item.get('aired') and item.get('title'):
                keys.append((item['root'], None, item['title'], item['title']))
            elif '/' in path:
                top = path.split('/', 1)[0]
                keys.append((item['root'], top + '/', None, top))
            for root, prefix, name, label in keys:
                group = groups.setdefault((root, prefix, name), {'root': root, 'path': prefix, 'name': name, 'label': label,
                                                                 'files': 0, 'seconds': 0, 'breaks': False,
                                                                 'aired': bool(item.get('aired'))})
                group['label'] = group['label'] or label
                group['files'] += 1
                group['seconds'] += item['duration']
                group['breaks'] = group['breaks'] or (item.get('ad_breaks') or {}).get('state') == 'ok'
        result = []
        for group in groups.values():
            if group['name'] and group['files'] < 2:
                continue  # A programme recorded once is not a strip.
            average = group.pop('seconds') / group['files'] / 60
            aired = group.pop('aired')
            whole = not group['path'] and not group['name']
            group.update(minutes=round(average), whole=whole, root_name=self._roots.get(group['root']) or group['root'],
                         label=(self._roots.get(group['root']) if whole else group['label']) or group['label'] or group['root'],
                         order='newest' if aired and not whole else 'shuffle' if average > 50 or whole else 'next')
            result.append(group)
        return sorted(result, key=lambda g: (g['whole'], -g['files'], g['label']))

    def _lookup(self, slot, day, start, end, now):
        """One airing's source, worked out afresh: {target, start, end, by, ...}. target is
        None when it has nothing to air (by: unlisted or empty), with why."""
        what = slot['what']
        if what['kind'] == 'channel':
            return {'target': dict(what['target']), 'start': start, 'end': end, 'by': 'fixed'}
        if what['kind'] == 'program':
            usual = what.get('target')
            found = self.guide.find(what['title'], start, end, match=what.get('match') or 'exact', usual=usual) \
                if self.guide else []
            for airing in found:
                target = self._normalized(airing['target'])
                if target is None:
                    continue
                begins, ends = start, end
                listed = (datetime.fromtimestamp(airing['start'], timezone.utc),
                          datetime.fromtimestamp(airing['end'], timezone.utc))
                if what.get('follow', True) and abs(listed[0] - start) <= FOLLOW and listed[1] > listed[0]:
                    begins, ends = listed[0], min(listed[1], listed[0] + timedelta(hours=8))
                return {'target': target, 'start': begins, 'end': ends, 'by': 'listings', 'label': airing['channel'],
                        'listed': {'title': airing['title'], 'episode_title': airing.get('episode_title'),
                                   'new': airing.get('new') is True, 'live': airing.get('live') is True,
                                   'start': listed[0].isoformat(), 'end': listed[1].isoformat()}}
            reach = self.guide.reach() if self.guide else None
            why = ('No listings to look in' if reach is None else
                   'The listings do not reach this far yet' if start >= reach else 'Not in the listings at this time')
            if usual:
                return {'target': dict(usual), 'start': start, 'end': end, 'by': 'usual', 'why': why,
                        'label': self.guide.label(usual) if self.guide else None}
            return {'target': None, 'start': start, 'end': end, 'by': 'unlisted', 'why': why}
        files = self._library_files(what)
        if not files:
            return {'target': None, 'start': start, 'end': end, 'by': 'empty', 'why': 'No playable files in this folder'}
        if what['order'] == 'shuffle':
            # The same file however often the lineup is worked out: by the slot and the date.
            index = sum(ord(c) * (n + 1) for n, c in enumerate(slot['id'] + day.isoformat())) % len(files)
        elif what['order'] == 'newest':
            index = 0
        else:
            with self.lock:
                last = (self.data['cursors'].get(slot['id']) or {}).get('last')
                pinned = {key for key in self.data['pins'] if key.split('|', 1)[0] == slot['id']}
            ids = [f['id'] for f in files]
            first = ids.index(last) + 1 if last in ids else 0
            # Airings between now and this one each take the next file.
            ahead = sum(1 for other, begins, _ in occurrences(slot, now, start, self.zone)
                        if begins < start and f"{slot['id']}|{other.isoformat()}" not in pinned)
            index = (first + ahead) % len(files)
        item = files[index]
        target = {'source_id': 'library', 'channel_id': item['id']}
        if what.get('ad_breaks') and (item.get('ad_breaks') or {}).get('state') == 'ok':
            target['ad_breaks'] = what['ad_breaks']
        length = item.get('duration') if isinstance(item.get('duration'), (int, float)) else None
        if length and target.get('ad_breaks'):
            length += target['ad_breaks'] * len((item.get('ad_breaks') or {}).get('at') or ())
        # The airing is the file: the time left in its slot is OFF AIR (the queue never cuts a
        # file for that), and a file longer than its slot is cut by whatever starts next.
        ends = min(end, start + timedelta(seconds=round(length))) if length else end
        return {'target': target, 'start': start, 'end': ends, 'by': 'library', 'label': item.get('title'),
                'file': item['id'], 'length': length, 'fits': not length or start + timedelta(seconds=length) <= end}

    def _resolve(self, slot, day, start, end, now):
        """An airing's source: as pinned, else worked out. It is pinned from PIN_AHEAD before
        it starts until it ends, so an entry in Up next keeps its key whatever the listings do."""
        key, sig = f"{slot['id']}|{day.isoformat()}", signature(slot)
        with self.lock:
            pin = self.data['pins'].get(key)
        if pin and pin.get('sig') == sig:
            found = {k: v for k, v in pin.items() if k not in ('sig', 'until')}
            found.update(start=parse_time(pin['start']), end=parse_time(pin['end']), pinned=True)
            return found
        found = self._lookup(slot, day, start, end, now)
        if found['target'] is not None and found['start'] - PIN_AHEAD <= now < found['end']:
            with self.lock:
                pins = self.data['pins']
                pins[key] = {**found, 'start': found['start'].isoformat(), 'end': found['end'].isoformat(),
                             'sig': sig, 'until': found['end'].isoformat()}
                for old in [k for k, v in pins.items() if parse_time(v['until']) < now - PINS_KEPT]:
                    del pins[old]
                if found.get('file') and slot['what'].get('order') == 'next':
                    self.data['cursors'][slot['id']] = {'last': found['file'], 'at': now.isoformat()}
                try:
                    self._save_locked()
                except OSError as exc:  # Still pinned in memory.
                    log.warning('Programming: cannot save a pinned airing: %s', exc)
        return found

    def airings(self, start, end, data=None):
        """Every airing of every slot overlapping [start, end), as the Schedule page draws
        the plan: one per slot and date, with where it comes from. Skipped airings, those of
        slots switched off and those with nothing to air are included, and say so."""
        if data is None:
            with self.lock:
                data = copy.deepcopy(self.data)
        now, result = utc_now(), []
        for slot in data['slots']:
            skipped = set(slot.get('skip') or ())
            for day, begins, ends in occurrences({**slot, 'skip': []}, start - FOLLOW, end + FOLLOW, self.zone):
                off = day.isoformat() in skipped
                found = ({'target': None, 'start': begins, 'end': ends, 'by': 'skipped'} if off
                         else self._resolve(slot, day, begins, ends, now))
                if found['end'] <= start or found['start'] >= end:
                    continue
                result.append({'slot': slot['id'], 'date': day.isoformat(), 'title': slot['title'],
                               'color': slot['color'], 'priority': slot.get('priority') or 'normal',
                               'enabled': slot.get('enabled', True), 'skipped': off, 'kind': slot['what']['kind'],
                               'slot_start': begins.isoformat(), 'slot_end': ends.isoformat(),
                               **{k: v for k, v in found.items() if k not in ('start', 'end')},
                               'start': found['start'].isoformat(), 'end': found['end'].isoformat()})
        return sorted(result, key=lambda a: (a['start'], a['title']))

    def _slot_segments(self, data, start, end):
        """The lineup over [start, end): each slot's airings as 'block' segments, OFF AIR
        between them. Where airings overlap, the higher priority has the time, then the one
        starting later; the other resumes when it ends."""
        now, pieces = utc_now(), []
        for slot in data['slots']:
            if not slot.get('enabled', True):
                continue
            rank = PRIORITIES.index(slot.get('priority') or 'normal')
            for day, begins, ends in occurrences(slot, start - FOLLOW, end + FOLLOW, self.zone):
                found = self._resolve(slot, day, begins, ends, now)
                if found['target'] is None or found['end'] <= start or found['start'] >= end:
                    continue
                piece = {'start': found['start'], 'end': found['end'], 'ref': slot['id'], 'kind': 'block',
                         'title': slot['title'], 'color': slot['color'], 'target': dict(found['target']),
                         'by': found['by'], '_rank': rank}
                for key in ('label', 'listed', 'file', 'length', 'why'):
                    if found.get(key) is not None:
                        piece[key] = found[key]
                pieces.append(piece)
        # Lower priorities are laid down first; within one, earlier starts, then longer airings.
        pieces.sort(key=lambda p: (p['_rank'], p['start'], p['start'] - p['end']))
        laid = []
        for piece in pieces:
            carved = []
            for segment in laid:
                if segment['end'] <= piece['start'] or segment['start'] >= piece['end']:
                    carved.append(segment)
                    continue
                if segment['start'] < piece['start']:
                    carved.append({**segment, 'end': piece['start']})
                if segment['end'] > piece['end']:
                    carved.append({**segment, 'start': piece['end']})
            carved.append(piece)
            laid = carved
        laid.sort(key=lambda s: s['start'])
        segments, at = [], start

        def add(segment):
            segment.pop('_rank', None)
            last = segments[-1] if segments else None
            # One programme through several slots (or one resumed at once) is one segment.
            if (last and last['end'] == segment['start'] and last['kind'] == segment['kind']
                    and last['title'] == segment['title'] and target_key(last['target']) == target_key(segment['target'])):
                last['end'] = segment['end']
            else:
                segments.append(segment)

        def off_air(begins, ends):
            add({'start': begins, 'end': ends, 'ref': None, 'kind': 'off_air', 'title': 'OFF AIR', 'color': None,
                 'target': dict(OFF_AIR)})

        for segment in laid:
            begins, ends = max(segment['start'], start), min(segment['end'], end)
            if ends <= begins:
                continue
            if begins > at:
                off_air(at, begins)
            add({**segment, 'start': begins, 'end': ends})
            at = ends
        if at < end:
            off_air(at, end)
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
        segments = self._slot_segments(data, start, end)
        order = self._order()
        # Lower priorities are laid down first; within one, in start order (a stable sort).
        for show, s_start, s_end in sorted(self._windows(data['shows']), key=lambda w: show_rank(w[0], order)):
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
        """Slot colors by slot id (a 'block' segment's ref)."""
        with self.lock:
            return {slot['id']: slot['color'] for slot in self.data['slots']}

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

    def next_show(self, now=None):
        """The next block, show or game to start after now, OFF AIR passed over: what a take
        played "until the next scheduled show starts" holds until. None while the schedule
        is off or has nothing in the next week."""
        now = now or utc_now()
        if not self.enabled:
            return None
        segment = next((s for s in self.timeline(now, now + HISTORY + timedelta(days=1))
                        if s['start'] > now and s['kind'] != 'off_air'), None)
        return {'title': segment['title'], 'kind': segment['kind'], 'start': segment['start'].isoformat()} if segment else None

    def upcoming_shows(self, now=None, exclude=(), limit=12):
        """Scheduled shows and games that have not started, except those whose id is in exclude."""
        now = now or utc_now()
        with self.lock:
            if not self.data['enabled']:
                return []
            shows = copy.deepcopy(self.data['shows'])
        return [s for s in shows if parse_time(s['start']) > now and s['id'] not in exclude][:limit]

    def describe(self, now=None, hours=24, days=8):
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
        # The plan: every slot's airings from the start of today for `days` days.
        today = datetime.combine(now.astimezone(self.zone).date(), dtime(), self.zone).astimezone(timezone.utc)
        airings = self.airings(today, today + timedelta(days=days), data)
        settings = {key: value for key, value in data.items() if key not in ('pins', 'cursors', 'planned')}
        return {'settings': settings, 'timezone': str(self.zone), 'now': now.isoformat(),
                'airings': airings, 'airings_from': today.isoformat(), 'airings_days': days,
                'guide': self.guide.status() if self.guide else {'available': False, 'error': 'No listings'},
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
