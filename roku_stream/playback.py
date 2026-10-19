"""What master will actually air: Up next and the schedule played forward under the
queue's rules (source_queue), for the Schedule page.

- A game holds master until its (estimated) final; entries due meanwhile wait, unless
  one outranks it (a show of higher priority), which cuts in at its start.
- At a final: a game already under way joins in progress, else recordings waiting in
  Up next play back to back, else what is due airs (the schedule's block under way).
- Otherwise a timed entry cuts in at its time. OFF AIR gives way to recordings.
- Recordings fill time: at once on the test card, after the one playing, or in a gap.
  A live channel queued to fill time stays on until the next timed entry (or the end
  it was given); OFF AIR gives way only to recordings still waiting.

Each segment names its Up next entry (item), and describe() lists what never airs
(dropped): a slot that ends while a game runs on, OFF AIR giving way, an entry outranked.

A projection, not a promise: game ends are estimates, and preparation time, station
IDs, failures and pauses are not modelled.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

# A recording of unknown length is assumed to run this long.
UNKNOWN_LENGTH = timedelta(minutes=30)
# An entry released this long after it was due joins in progress (source_queue.LATE).
LATE = timedelta(seconds=60)
OFF_AIR = {'source_id': 'off-air', 'channel_id': 'off-air'}
# Sources whose channel id is a game's id (NFL on ESPN, MLB gamePk).
GAME_SOURCES = {'thursday-night-football': 'nfl', 'sunday-ticket': 'nfl', 'mlb': 'mlb'}
# A show's priority rank (programming.PRIORITIES); a take held by hand ranks above normal
# and favorites' games, below high (source_queue.HELD).
NORMAL = 1
HELD = NORMAL + .5


@dataclass
class Entry:
    due: datetime | None      # When it releases, a game gate folded in; None never does.
    title: str
    kind: str                 # game, block, show, off_air, backup, manual
    target: dict
    order: int = 0
    skip_after: datetime | None = None
    regular: bool = False     # The regular schedule: it gives way.
    game: dict | None = None  # The game a game entry carries.
    color: str | None = None
    source: str = 'schedule'  # schedule (not yet in Up next) or queue
    start: datetime | None = None  # Its scheduled time, before any game gate (default: due).
    rank: float = NORMAL      # Its show's priority: one that outranks a held game cuts in.
    item: str | None = None   # Its Up next entry, once queued.
    key: str | None = None    # Its schedule key (programming), if it comes from the schedule.

    @property
    def scheduled(self):
        return self.start or self.due


@dataclass
class Program:
    """On air from start. until is a natural end: a file ends, or a held game's final."""
    title: str
    kind: str                 # game, block, show, off_air, backup, manual, recording, ident
    target: dict | None
    start: datetime
    until: datetime | None = None
    holds: bool = False       # Nothing timed cuts in before until.
    game: dict | None = None
    color: str | None = None
    source: str = 'schedule'
    notes: list = field(default_factory=list)
    rank: float = NORMAL
    item: str | None = None   # The Up next entry it aired from.


@dataclass
class Fill:
    """An entry of Up next's fill lane. A recording runs its length (None: unknown); a live
    channel (live) stays on until the next timed entry, or holds until `until` when it was
    given an end (a time, or its game's estimated final: then game names it)."""
    title: str
    target: dict
    length: timedelta | None = None
    item: str | None = None
    live: bool = False
    until: datetime | None = None
    game: dict | None = None
    started: datetime | None = None   # Its game's start, for "Joins in progress".


def project(now, horizon, current, entries, recordings, *, game_end, schedule_at, dropped=None):
    """Segments of what airs from now to horizon.

    current: the Program on air now. entries: timed entries (Up next's timed lane, and
    schedule changes not yet queued). recordings: Up next's fill lane in order, each a Fill
    or (title, target, length or None). game_end(game) estimates a final. schedule_at(t) is
    the schedule's Entry for t (None when it is off), which follows a held take nothing else
    follows. dropped, a list, gets (entry or Fill, why) for each one that never airs."""
    pending = sorted((e for e in entries if e.due is not None), key=lambda e: (e.due, e.order))
    fill = [f if isinstance(f, Fill) else Fill(*f) for f in recordings]
    segments = []
    state = {'cur': current}

    def drop(entry, why):
        if dropped is not None:
            dropped.append((entry, why))

    def emit(program, end):
        start, end = max(program.start, now), min(end, horizon)
        if end > start:
            segments.append({'start': start.isoformat(), 'end': end.isoformat(), 'title': program.title,
                             'kind': program.kind, 'target': program.target, 'game': program.game,
                             'color': program.color, 'source': program.source, 'estimated': program.holds
                             and program.kind == 'game', 'notes': list(program.notes), 'item': program.item})

    def cut_by(cur, end):
        """The first entry starting after cur and due by end that outranks it (not a game's return)."""
        return next((e for e in pending if cur.start < e.due <= end and e.rank > cur.rank and e.kind != 'backup'), None)

    def recording(at):
        """The next of the fill lane, or None when every one left has had its end pass."""
        while fill:
            entry = fill.pop(0)
            if not entry.live:
                return Program(entry.title, 'recording', entry.target, at, at + (entry.length or UNKNOWN_LENGTH),
                               source='recording', notes=[] if entry.length else ['Length unknown'], item=entry.item)
            if entry.until is not None and entry.until <= at:
                drop(entry, 'Its end time passes before it could air')
                continue
            return Program(entry.title, 'game' if entry.game else 'manual', entry.target, at, entry.until,
                           entry.until is not None, entry.game, source='queue', item=entry.item,
                           notes=['Joins in progress'] if entry.started and entry.started < at - LATE else [])
        return None

    def enter(entry, at):
        game = entry.kind == 'game' and entry.game
        return Program(entry.title, entry.kind, entry.target, at, game_end(game, entry.due) if game else None, bool(game),
                       entry.game, entry.color, entry.source,
                       ['Joins in progress'] if entry.scheduled < at - LATE and entry.target.get('source_id') != 'off-air' else [],
                       entry.rank, entry.item)

    def off_air(at):
        return Program('OFF AIR', 'off_air', dict(OFF_AIR), at)

    def after_final(at, ended):
        """A game under way, else recordings, else what is due (entries queued by hand and
        fixed backups do not give way), else the schedule's block now. ended: what held
        master until at, for the reasons the others never air."""
        due = []
        while pending and pending[0].due <= at:
            entry = pending.pop(0)
            if entry.skip_after and entry.skip_after <= at:  # Superseded while the game ran.
                drop(entry, f'Its slot ends before {ended or "what is on before it"} does')
            else:
                due.append(entry)
        games = [e for e in due if e.kind == 'game']
        if games:
            for entry in due:
                if entry is not games[0]:
                    drop(entry, f'{games[0].title or "The game under way"} airs instead')
            return enter(games[0], at)
        firm = [e for e in due if not e.regular]
        if fill and not firm:
            program = recording(at)
            if program is not None:
                for entry in due:
                    drop(entry, 'Up next fills the time instead')
                if due:
                    program.notes.append('Instead of ' + due[-1].title)
                return program
        if firm or due:
            chosen = (firm or due)[-1]
            for entry in due:
                if entry is not chosen:
                    drop(entry, f'{chosen.title or "A later entry"} replaces it')
            return enter(chosen, at)
        now_on = schedule_at(at)
        return enter(now_on, at) if now_on else off_air(at)

    t = now
    while state['cur'] is not None and t < horizon:
        cur = state['cur']
        if cur.holds:
            end = max(cur.until or horizon, t)
            cutter = cut_by(cur, end)
            if cutter is not None:
                at = max(cutter.due, t)
                emit(replace(cur, holds=False, notes=cur.notes + [f'Cut when {cutter.title or "the next show"} starts']), at)
                # What it outranks and was waiting meanwhile never airs.
                for e in pending:
                    if e is not cutter and e.due <= at and e.rank < cutter.rank:
                        drop(e, f'{cutter.title or "A show of higher priority"} cuts in instead')
                pending[:] = [e for e in pending if e is not cutter and not (e.due <= at and e.rank < cutter.rank)]
                t = at
                state['cur'] = enter(cutter, t)
                continue
            emit(cur, end)
            if end >= horizon:
                break
            t = end
            state['cur'] = after_final(t, cur.title)
            continue
        if cur.kind == 'off_air' and fill:  # Recordings play at once on the test card.
            emit(cur, t)
            state['cur'] = recording(t) or cur
            continue
        ends = cur.kind in ('recording', 'ident') and cur.until is not None
        limit = cur.until if ends else horizon
        nxt, gap = None, None
        while pending and pending[0].due < limit:
            entry = pending.pop(0)
            if entry.skip_after and entry.skip_after <= max(entry.due, t):
                drop(entry, 'Its slot ends before it could air')
                continue
            if entry.regular and entry.target.get('source_id') == 'off-air' and (fill or ends):
                if ends:
                    cur.notes.append('OFF AIR gives way')  # The recording plays on.
                    drop(entry, 'OFF AIR gives way to the recording playing')
                    continue
                gap = entry  # The live program ends at the gap and recordings take it.
                break
            nxt = entry
            break
        if gap is not None:
            following = recording(max(gap.due, t))
            if following is None:  # Nothing left to fill it: OFF AIR goes on after all.
                nxt = gap
            else:
                emit(cur, gap.due)
                t = max(gap.due, t)
                drop(gap, 'OFF AIR gives way to Up next')
                state['cur'] = following
                following.notes.append('Instead of OFF AIR')
                continue
        if nxt is None:
            if ends and limit < horizon:
                emit(cur, limit)
                t = limit
                state['cur'] = (recording(t) if fill else None) or off_air(t)
                continue
            emit(cur, horizon)
            break
        if ends and cur.until > nxt.due:
            cur.notes.append('Cut when ' + (nxt.title or 'the next entry') + ' starts')
        emit(cur, nxt.due)
        t = max(nxt.due, t)
        state['cur'] = enter(nxt, t)
    return segments


def queue_inputs(queue, items, game_end, colors):
    """Up next's waiting timed entries, and its recordings in order, as projection inputs."""
    entries, recordings = [], []
    rank = getattr(queue, '_rank', lambda item: NORMAL)
    for order, item in enumerate(items):
        if item.status not in ('queued', 'blocked'):
            continue
        if queue._fills(item):
            recordings.append(item)
            continue
        kind, ref = queue._schedule_kind(item)
        due = datetime.fromisoformat(item.run_at) if item.run_at else None
        if item.release_type == 'after_game':
            final = game_end({'league': item.after_game_league or 'mlb', 'game_pk': item.after_game_pk,
                              'game_date': item.after_game_date, 'title': item.after_game_title})
            due = max(due, final) if due and final else final
        entries.append(Entry(due, item.title or (item.program or {}).get('title') or '',
                             'off_air' if (item.target or {}).get('source_id') == 'off-air' else kind or 'manual',
                             dict(item.target or {}), order,
                             datetime.fromisoformat(item.skip_after) if item.skip_after else None,
                             # A game queued by hand carries its game in hold_end until taken.
                             queue._regular(item), item.game or (item.hold_end or {}).get('game'),
                             colors.get(ref), 'queue',
                             datetime.fromisoformat(item.run_at) if item.run_at else None, rank(item),
                             item.id, item.schedule_key))
    return entries, recordings


def schedule_inputs(transitions, game_end, colors, queued_keys, first_order, rank=lambda key: NORMAL):
    """Schedule changes not yet in Up next, as the queue would hold them. rank(key) is a
    change's priority rank (Programming.rank)."""
    entries = []
    for order, change in enumerate(transitions, first_order):
        if change['key'] in queued_keys:
            continue
        kind, ref = change['kind'], change['key'].split('|', 3)[2]
        due = datetime.fromisoformat(change['run_at'])
        if change.get('after_game'):
            final = game_end({'league': 'mlb', **change['after_game']})
            due = max(due, final) if final else None
        entries.append(Entry(due, change['title'], kind, dict(change['target']), order,
                             datetime.fromisoformat(change['skip_after']) if change.get('skip_after') else None,
                             kind in ('block', 'show', 'off_air') or (kind == 'backup' and ':' in ref),
                             change.get('game'), colors.get(ref), 'schedule', datetime.fromisoformat(change['run_at']),
                             rank(change['key']), key=change['key']))
    return entries


def describe(now, horizon, *, queue, programming, on_air, game_info, length, label):
    """The projection as the Schedule page shows it. game_info(game) returns the sports
    catalog's game (start, state, inning or quarter) or None; length(channel_id) a
    library file's seconds; label(channel_id) its title."""
    from .sports import TYPICAL, estimated_end

    finals = {}

    def game_end(game, start=None):
        if not game or game.get('game_pk') is None:
            return None
        league = game.get('league') or 'mlb'
        key = (league, game['game_pk'])
        if key not in finals:
            found = game_info({**game, 'league': league}) or {}
            if not found.get('start_time') and start:
                found = {**found, 'start_time': start.isoformat()}
            finals[key] = estimated_end(league, found, now) if found else (start or now) + TYPICAL.get(league, TYPICAL['mlb'])
        return finals[key]

    status = queue.status()
    items = queue.list()
    colors = programming.colors()
    entries, fills = queue_inputs(queue, items, game_end, colors)
    queued = {i.schedule_key for i in items if i.schedule_key}
    changes = programming.transitions(now, horizon) if programming.enabled else []
    entries += schedule_inputs(changes, game_end, colors, queued, len(items), programming.rank)
    recordings = [_fill(i, length, label, game_end, game_info) for i in fills]

    def schedule_at(at):
        segment = programming.segment_at(at)
        if segment is None:
            return None
        return Entry(segment['start'], segment['title'], segment['kind'], dict(segment['target']),
                     color=segment.get('color'))

    current = _current(now, status, items, on_air, game_end, length, label, colors, queue)
    dropped = []
    segments = project(now, horizon, current, entries, recordings, game_end=game_end, schedule_at=schedule_at,
                       dropped=dropped)
    return {'now': now.isoformat(), 'until': horizon.isoformat(), 'paused': status['paused'],
            'pause_reason': status['pause_reason'], 'hold': status['hold'], 'segments': segments,
            'dropped': [_dropped(entry, why) for entry, why in dropped]}


def _fill(item, length, label, game_end, game_info=lambda game: None):
    """An entry of the fill lane as the projection plays it: a library file runs its length;
    anything else is live, held until the end it was given (a time, or its game's final)."""
    target = dict(item.target or {})
    if target.get('source_id') == 'library':
        return Fill(label(target['channel_id']), target, _seconds(length(target['channel_id'])), item.id)
    end = item.hold_end or {}
    game = end.get('game') or item.game
    until = (datetime.fromisoformat(end['until']) if end.get('until')
             else game_end(game) if end.get('game') else None)
    started = None
    if end.get('game'):
        found = game_info({**game, 'league': game.get('league') or 'mlb'}) or {}
        try:
            started = datetime.fromisoformat(str(found['start_time']).replace('Z', '+00:00'))
        except (KeyError, TypeError, ValueError):
            started = None
    return Fill(item.title or (item.program or {}).get('title') or (game or {}).get('title') or '', target,
                None, item.id, True, until, game if end.get('game') else None, started)


def _dropped(entry, why):
    """An entry that never airs, for the page: its Up next entry (or schedule key), title, time."""
    due = getattr(entry, 'start', None) or getattr(entry, 'due', None)
    return {'item': entry.item, 'key': getattr(entry, 'key', None), 'title': entry.title,
            'kind': getattr(entry, 'kind', 'recording'), 'target': entry.target,
            'due': due.isoformat() if due else None, 'why': why}


def _seconds(value):
    return timedelta(seconds=value) if isinstance(value, (int, float)) and value > 0 else None


def _same(a, b):
    return bool(a and b) and all((a.get(k) or None) == (b.get(k) or None) for k in ('source_id', 'channel_id', 'date'))


def _current(now, status, items, on_air, game_end, length, label, colors, queue):
    """What is on master now, and how it ends: a held game or take, a file, or live."""
    hold = status.get('hold')
    aired = next((i for i in items if i.status == 'succeeded' and _same(i.target, on_air)), None) if on_air else None
    since = datetime.fromisoformat(aired.completed_at) if aired and aired.completed_at else now
    mine = aired.id if aired else None
    if hold and hold.get('game'):
        return Program(hold['game'].get('title') or '', 'game', hold.get('target'), since,
                       game_end(hold['game']), True, hold['game'], source='queue', rank=HELD, item=mine)
    if hold and hold.get('until'):
        return Program(aired.title if aired and aired.title else '', 'manual', hold.get('target'), since,
                       datetime.fromisoformat(hold['until']), True, source='queue', rank=HELD, item=mine)
    if not on_air:
        return Program('OFF AIR', 'off_air', dict(OFF_AIR), now)
    source = on_air.get('source_id')
    media = on_air.get('media') or {}
    left = None
    if media.get('duration_seconds') and media.get('position_seconds') is not None:
        left = timedelta(seconds=max(0, media['duration_seconds'] - media['position_seconds']))
    if source == 'ident':
        return Program('Station ID', 'ident', on_air, now, now + (left or timedelta(seconds=30)), source='queue')
    if source == 'library':
        known = _seconds(length(on_air.get('channel_id')))
        return Program(label(on_air.get('channel_id')), 'recording', on_air, since,
                       now + (left or known or UNKNOWN_LENGTH), source='recording', item=mine)
    kind, ref = queue._schedule_kind(aired) if aired else (None, None)
    if aired and aired.game:  # A scheduled game, or a game queued by hand: on until its final.
        return Program(aired.title or aired.game.get('title') or '', 'game', on_air, since,
                       game_end(aired.game, since), True, aired.game, source='queue',
                       rank=getattr(queue, '_rank', lambda item: NORMAL)(aired), item=mine)
    return Program((aired.title or (aired.program or {}).get('title') or '') if aired else '', kind or 'manual',
                   on_air, since, color=colors.get(ref), source='queue' if aired else 'schedule', item=mine)


class Projector:
    """The projection over live inputs: Up next, the schedule, what master shows, the
    sports catalog (games cached briefly) and the media library."""

    def __init__(self, *, queue, programming, master, sports=None, library=None):
        self.queue, self.programming, self.master = queue, programming, master
        self.sports, self.library = sports, library
        self.games = {}  # (league, game_pk) -> (expires, catalog game)

    def game_info(self, game):
        """A game's start, live progress and teams; cached briefly."""
        import time
        key = (game['league'], game['game_pk'])
        cached = self.games.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        try:
            found = self.sports.game(game['league'], game['game_pk'], game.get('game_date')) if self.sports else None
        except Exception:  # Unlisted or unreachable: the projection uses a typical length.
            found = None
        live = str((found or {}).get('state') or '').casefold() in ('live', 'in')
        self.games[key] = (time.monotonic() + (30 if live else 300), found)
        return found

    def describe(self, now, horizon):
        try:
            on_air = self.master.request().get('on_air')
        except Exception:  # Master unavailable: project from the test card.
            on_air = None
        library = self.library
        return describe(now, horizon, queue=self.queue, programming=self.programming, on_air=on_air,
                        game_info=self.game_info,
                        length=lambda channel: (library.item(channel) or {}).get('duration') if library else None,
                        label=lambda channel: library.label(channel) if library else channel)

    PAIRS = {'en': 'the {away} and the {home}', 'fr': 'les {away} et les {home}', 'es': 'los {away} y los {home}',
             'it': 'i {away} e i {home}', 'de': 'die {away} und die {home}', 'nl': 'de {away} en de {home}'}

    def spoken(self, segment, language='en'):
        """A program as an announcer says it: "the Phillies and the Braves" for a game ("les
        Phillies et les Braves" in French), else its title, else its channel."""
        game, target = segment.get('game'), segment.get('target') or {}
        # A game queued by hand may carry no game: on these sources its channel is the game's id.
        league = GAME_SOURCES.get(target.get('source_id'))
        if not (game and game.get('game_pk') is not None) and league and str(target.get('channel_id') or '').isdigit():
            game = {'league': league, 'game_pk': int(target['channel_id']), 'game_date': target.get('date')}
        info = {}
        if game and game.get('game_pk') is not None:
            info = self.game_info({**game, 'league': game.get('league') or 'mlb'}) or {}
            away, home = info.get('away') or {}, info.get('home') or {}
            if away.get('nickname') and home.get('nickname'):
                return self.PAIRS.get(language, self.PAIRS['en']).format(away=away['nickname'], home=home['nickname'])
        return segment.get('title') or info.get('title') or str(target.get('channel_id') or '') or None
