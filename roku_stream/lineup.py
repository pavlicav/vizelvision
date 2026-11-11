"""The lineup: what the station airs each week, as slots (since 2026-11-09).

A slot is a recurring programme: the days of the week it airs, a start to the minute, a
length, and what it airs:

- ``channel``: a fixed source target, as the painted grid's blocks were.
- ``program``: a programme by name. Each airing is looked up in the listings
  (guide_index.GuideIndex), so the channel follows the programme: Jeopardy! is wherever the
  listings have it that night. A usual channel can be named for when the listings do not
  reach that far, or do not name it.
- ``library``: a folder of the media library, one file per airing: the next episode, the
  newest recording, or one at random.

Until 2026-11-09 the schedule was a grid of 48 half-hour cells a day, each naming a block
with one fixed channel. ``from_grid`` turns such a grid into slots: one per run of cells,
days that share a run sharing a slot. Programming still accepts the old body through it.

A sports slot (``validate_sports``) is not a programme but a rule: "Monday Night Football"
is the NFL game starting on a Monday evening on ESPN or ABC. sports_slots.SportsSlots puts
the games each rule finds on the schedule as game shows.
"""
from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta, timezone
import re
import uuid

from .errors import ConfigError

DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
CELLS = 48  # Half-hour cells per day in the old grid.
PRIORITIES = ('low', 'normal', 'high')
KINDS = ('channel', 'program', 'library')
ORDERS = ('next', 'newest', 'shuffle')
MAX_SLOTS = 160
MAX_SPORTS = 40
MAX_SKIPS = 60
PALETTE = ('#3a6f8f', '#7a4f9a', '#2f7d5b', '#a0582f', '#8f3a4f', '#5a6f2f', '#2f5f9a', '#9a8a2f')
_COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')
_ID = re.compile(r'[0-9a-zA-Z_-]{1,40}')
_CLOCK = re.compile(r'([01]\d|2[0-3]):([0-5]\d)')
_DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
OFF_AIR = {'source_id': 'off-air', 'channel_id': 'off-air'}


def text(value, name, limit=48):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ConfigError(f'{name} must be a single line of at most {limit} characters')
    return value.strip()


def priority(value):
    value = value or 'normal'
    if value not in PRIORITIES:
        raise ConfigError('priority must be one of ' + ', '.join(PRIORITIES))
    return value


def clock(value, name='start'):
    """'19:30' -> (19, 30)."""
    match = _CLOCK.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ConfigError(f'{name} must be a time of day, HH:MM')
    return int(match[1]), int(match[2])


def days(value):
    if (not isinstance(value, list) or not value or len(set(value)) != len(value)
            or any(day not in DAYS for day in value)):
        raise ConfigError('days must list at least one of ' + ', '.join(DAYS))
    return [day for day in DAYS if day in value]


def new_id():
    return uuid.uuid4().hex[:12]


def _id(value, name):
    if value is None:
        return new_id()
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ConfigError(f'Invalid {name} id')
    return value


def _color(value, index=0):
    value = value or PALETTE[index % len(PALETTE)]
    if not isinstance(value, str) or not _COLOR.match(value):
        raise ConfigError('color must be #rrggbb')
    return value.lower()


def _skips(value):
    value = value or []
    if (not isinstance(value, list) or len(value) > MAX_SKIPS
            or any(not isinstance(day, str) or not _DATE.fullmatch(day) for day in value)):
        raise ConfigError(f'skip must list at most {MAX_SKIPS} dates, YYYY-MM-DD')
    return sorted(set(value))


def signature(slot):
    """What decides an airing's source: a pinned airing is resolved again when it changes."""
    what = slot['what']
    return '|'.join(str(part) for part in (
        slot['start'], slot['minutes'], what['kind'], what.get('title'), what.get('match'), what.get('follow'),
        sorted((what.get('target') or {}).items()), what.get('root'), what.get('path'), what.get('name'),
        what.get('order'), what.get('ad_breaks')))


def validate_what(value, target, old=None):
    """What a slot airs. target(value) validates a source target; an unchanged one (old's)
    is not resolved again, so a slot can be moved while its source is away."""
    if not isinstance(value, dict) or value.get('kind') not in KINDS:
        raise ConfigError('what.kind must be one of ' + ', '.join(KINDS))
    kind = value['kind']

    def kept(given):
        before = (old or {}).get('target')
        same = isinstance(given, dict) and before and all(
            given.get(k) == before.get(k) for k in ('source_id', 'channel_id', 'date', 'antenna'))
        return dict(before) if same else target(given)

    if kind == 'channel':
        return {'kind': kind, 'target': kept(value.get('target'))}
    if kind == 'program':
        match = value.get('match') or 'exact'
        if match not in ('exact', 'contains'):
            raise ConfigError('what.match must be exact or contains')
        result = {'kind': kind, 'title': text(value.get('title'), 'The programme', 80), 'match': match,
                  'follow': value.get('follow') is not False}
        if value.get('target') is not None:
            usual = kept(value['target'])
            if usual.get('source_id') == OFF_AIR['source_id']:
                raise ConfigError('The usual channel must be a channel, not OFF AIR')
            result['target'] = usual
        return result
    root, order = value.get('root'), value.get('order') or 'next'
    if not isinstance(root, str) or not _ID.fullmatch(root):
        raise ConfigError('what.root must be a library folder id')
    if order not in ORDERS:
        raise ConfigError('what.order must be one of ' + ', '.join(ORDERS))
    result = {'kind': kind, 'root': root, 'order': order}
    for key, limit in (('path', 300), ('name', 120)):
        if value.get(key):
            result[key] = text(value[key], f'what.{key}', limit)
    seconds = value.get('ad_breaks')
    if seconds:
        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 15 <= seconds <= 180 or seconds % 15:
            raise ConfigError('ad_breaks must be 15-180 seconds, in steps of 15')
        result['ad_breaks'] = seconds
    return result


def validate_slot(value, target, old=None, index=0):
    """A whole slot. old: the slot it replaces (its id, and its unchanged target, are kept)."""
    if not isinstance(value, dict):
        raise ConfigError('A slot must be an object')
    minutes = value.get('minutes')
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not 5 <= minutes <= 24 * 60:
        raise ConfigError('minutes must be from 5 through 1440')
    hour, minute = clock(value.get('start'))
    enabled = value.get('enabled', True)
    if not isinstance(enabled, bool):
        raise ConfigError('enabled must be true or false')
    return {'id': old['id'] if old else _id(value.get('id'), 'slot'),
            'title': text(value.get('title'), 'The title'), 'color': _color(value.get('color'), index),
            'days': days(value.get('days')), 'start': f'{hour:02d}:{minute:02d}', 'minutes': minutes,
            'priority': priority(value.get('priority')), 'enabled': enabled, 'skip': _skips(value.get('skip')),
            'what': validate_what(value.get('what'), target, (old or {}).get('what'))}


def validate_sports(value, leagues, old=None):
    """A sports slot: the games of a league that start on these days, between two times of
    day, on these networks (any when empty), with these teams (any when empty)."""
    if not isinstance(value, dict):
        raise ConfigError('A sports slot must be an object')
    league = value.get('league')
    if league not in leagues:
        raise ConfigError('league must be one of ' + ', '.join(leagues))
    start, end = clock(value.get('from') or '00:00', 'from'), clock(value.get('to') or '23:59', 'to')
    pick = value.get('pick') or 'all'
    if pick not in ('all', 'best'):
        raise ConfigError('pick must be all or best')

    def names(key, limit, each):
        given = value.get(key) or []
        if (not isinstance(given, list) or len(given) > limit
                or any(not isinstance(item, str) or not 0 < len(item) <= each for item in given)):
            raise ConfigError(f'{key} must list at most {limit} names')
        return list(dict.fromkeys(item.strip() for item in given))

    lead = value.get('lead_minutes') or 0
    if isinstance(lead, bool) or not isinstance(lead, int) or not 0 <= lead <= 120:
        raise ConfigError('lead_minutes must be from 0 through 120')
    enabled = value.get('enabled', True)
    if not isinstance(enabled, bool):
        raise ConfigError('enabled must be true or false')
    return {'id': old['id'] if old else _id(value.get('id'), 'sports slot'),
            'title': text(value.get('title'), 'The title'), 'league': league, 'days': days(value.get('days')),
            'from': '%02d:%02d' % start, 'to': '%02d:%02d' % end, 'networks': names('networks', 12, 40),
            'teams': names('teams', 40, 24), 'pick': pick, 'priority': priority(value.get('priority')),
            'lead_minutes': lead, 'enabled': enabled, 'preset': value.get('preset') if isinstance(value.get('preset'), str)
            and _ID.fullmatch(value.get('preset') or '') else None}


def occurrences(slot, start, end, zone):
    """(local date, start, end) of each airing of a slot that overlaps [start, end), in UTC.
    A slot's length is real time, so an airing across a clock change keeps its length."""
    hour, minute = clock(slot['start'])
    length = timedelta(minutes=slot['minutes'])
    skip = set(slot.get('skip') or ())
    day = start.astimezone(zone).date() - timedelta(days=2)
    result = []
    while True:
        begins = datetime.combine(day, dtime(hour, minute), zone).astimezone(timezone.utc)
        if begins >= end:
            return result
        if DAYS[day.weekday()] in slot['days'] and day.isoformat() not in skip and begins + length > start:
            result.append((day, begins, begins + length))
        day += timedelta(days=1)


def next_airing(slot, now, zone, limit=timedelta(days=8)):
    found = occurrences(slot, now, now + limit, zone)
    return found[0] if found else None


def from_grid(blocks, grid):
    """Slots for an old grid: blocks [{id, name, color, target}], grid {day: 48 block ids or
    None}. One slot per run of cells; days sharing a run share the slot. A run through
    midnight into the same block is one airing."""
    by_id = {block['id']: block for block in blocks}
    runs = {day: [] for day in DAYS}
    for day in DAYS:
        cells, index = grid[day], 0
        while index < CELLS:
            block = cells[index]
            stop = index
            while stop < CELLS and cells[stop] == block:
                stop += 1
            if block is not None:
                runs[day].append([block, index, stop - index])
            index = stop
    # Join a run ending at midnight to the same block starting the next day.
    for position, day in enumerate(DAYS):
        following = DAYS[(position + 1) % len(DAYS)]
        last = runs[day][-1] if runs[day] else None
        first = runs[following][0] if runs[following] else None
        if (last and first and last[0] == first[0] and last[1] + last[2] == CELLS and first[1] == 0
                and last is not first and last[2] + first[2] < CELLS):
            last[2] += first[2]
            runs[following].pop(0)
    grouped = {}
    for day in DAYS:
        for block, index, count in runs[day]:
            grouped.setdefault((block, index, count), []).append(day)
    slots = []
    for (block_id, index, count), on in sorted(grouped.items(), key=lambda item: (item[0][1], DAYS.index(item[1][0]))):
        block = by_id[block_id]
        slots.append({'id': new_id(), 'title': block['name'], 'color': block['color'], 'days': on,
                      'start': f'{index // 2:02d}:{30 * (index % 2):02d}', 'minutes': count * 30,
                      'priority': 'normal', 'enabled': True, 'skip': [],
                      'what': {'kind': 'channel', 'target': dict(block['target'])}})
    return slots


def prune_skips(slot, today):
    """Dates passed are forgotten."""
    kept = [day for day in slot.get('skip') or () if day >= today.isoformat()]
    changed = kept != (slot.get('skip') or [])
    slot['skip'] = kept
    return changed


def spoken_days(on):
    """'Weekdays', 'Every day', 'Mon, Wed, Fri'."""
    on = [day for day in DAYS if day in on]
    if len(on) == 7:
        return 'Every day'
    if on == list(DAYS[:5]):
        return 'Weekdays'
    if on == list(DAYS[5:]):
        return 'Weekends'
    return ', '.join(day.capitalize() for day in on)


def spoken_time(value):
    hour, minute = clock(value)
    return f'{hour % 12 or 12}:{minute:02d} {"AM" if hour < 12 else "PM"}'


def local_day(value):
    return date.fromisoformat(value)
