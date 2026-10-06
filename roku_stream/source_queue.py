"""Ordered master takes. Startup and ambiguous operations require operator review.

Two lanes share Up next. The timed rundown (everything with a time or a game gate,
and the schedule's entries) releases in order. Recordings queued to follow what is
on air ("after_current") fill time: they play when master is free (the test card,
the end of a recording, a game gone final, or a schedule gap) and a timed live entry
cuts in at its start even when recordings were queued ahead of it.

A game holds master until it is final. Then an in-progress game follows, else
waiting recordings, else the regular schedule: a schedule entry that is OFF AIR, or
already under way when it releases, gives way to those.

A scheduled show that outranks what holds master (programming.PRIORITIES) cuts in at
its start instead: a held take ends then, and a game's return waiting for its final is
skipped. A take held by hand, and an entry with no scheduled show, are normal.
"""
from dataclasses import asdict, dataclass, replace
from contextlib import contextmanager
import copy
from datetime import timedelta
import json
import logging
from pathlib import Path
import threading
import time
import uuid

from .errors import ConfigError, ControlBusyError
from .master import MasterStreamError
from .roku_input import ROKU_SOURCE_IDS
from .ident import IDENT_SECONDS, IDENT_SOURCE_ID
from .library import LIBRARY_SOURCE_ID
from .playout_queue import PlayoutQueue, QueueItem
from .scheduler import ScheduledJob, parse_time, utc_now
from .tv_thing import SourceUnavailableError


@dataclass
class SourceQueueItem(QueueItem):
    target: dict | None = None
    program: dict | None = None
    schedule_id: str | None = None
    late: bool = False
    tune_anyway: bool = False
    after_program: dict | None = None
    origin: str | None = None
    schedule_key: str | None = None
    skip_after: str | None = None
    title: str | None = None
    after_game_league: str | None = None
    prerolled_at: str | None = None
    preroll_attempts: int = 0
    preroll_retry_at: str | None = None
    prepare_attempts: int = 0
    retry_at: str | None = None
    prepared_input_id: str | None = None
    ident_at: str | None = None
    kind: str | None = None
    game: dict | None = None
    # How long an entry queued by hand holds master once taken: {'until': ISO, 'program'?}
    # or {'game': {...}}. None: a game on its channel still holds until the final.
    hold_end: dict | None = None
    # Put back on after its feed failed on air (feed recovery): a failed preparation is
    # retried for any live source, not only a Roku, since a tuner may still be restarting.
    recovery: bool = False
    # The program's own target, when feed recovery may put it back on from another source
    # (the antenna for YouTube TV, or the reverse): later recoveries choose from it again.
    program_target: dict | None = None


ROKU_SOURCES = ROKU_SOURCE_IDS
PREPARE_FAILED = 'source_prepare_failed'
# A game-gated backup is only superseded once its game is final; past this it is abandoned.
GAME_EXPIRY = timedelta(hours=12)
# A Sunday Ticket row reads "Upcoming" until its feed goes live, which can be
# minutes after the listed start, so it keeps trying longer than a channel.
SLOW_START_ATTEMPTS = {'sunday-ticket': 10}
# A manual take held "until the game ends" gives master back after this at the latest.
HOLD_LIMIT = timedelta(hours=12)
HOLD_REASON = 'On air until its end time'
RETURNING = 'Manual take ended · returning to the schedule'
# A held take whose feed dropped (the test card this long, past master's own 8 s recovery)
# has left master, and goes straight back on at the head of Up next. When master names its
# input as failed, it goes back on at once (2026-10-04 12:11: 22 s of test card otherwise).
HOLD_LOST_SECONDS = 20
# Feed recovery: a live program whose input fails on air goes back on, at most this many
# times in this window from one source and channel. The antenna and YouTube TV each have
# their own budget, so a program both carry can go back on from the other; once every source
# has used its budget, the program is left to the operator.
RECOVERY_LIMIT = 3
RECOVERY_WINDOW = timedelta(minutes=15)
# A scheduled program this close to the end of its slot is not put back: what follows is due.
RECOVERY_MIN_LEFT = timedelta(seconds=60)
# The station ID only plays whole: an entry queued inside its last 30 s goes without.
IDENT_WINDOW = 3
# An entry queued "now" releases this soon, at the head of Up next.
NOW_DELAY = timedelta(seconds=2)
# A schedule entry released this long after its start is joined in progress (a game ran over).
LATE = timedelta(seconds=60)
# Master's on-air state could not be read: recordings wait.
UNKNOWN = {'source_id': None}
# A game stays on this long after the feeds call it final: the picture runs behind them, and
# the last out or whistle, then the final score, airs after the status changes.
FINAL_BUFFER_SECONDS = 180
# A warm-up prepares the Roku entry that follows a program about to end while another source
# finishes it: a recording, or a show held to an end time, in its last ENDING_SECONDS; a game
# in its closing stretch (sports.closing: the 9th inning, the last 2 minutes, overtime).
ENDING_SECONDS = 180
# A warm-up that keeps failing for one channel is left to the cut after this many tries.
WARM_ATTEMPTS = 3
# How often the schedule is asked what it would put back on after a held take.
SCHEDULE_CHECK_SECONDS = 15
# Back to YouTube TV: a program it carries, on air from the antenna in its place (feed
# recovery, or the antenna taking over at release), goes back to YouTube TV (the better
# picture) once the Roku is ready, prepared beside the antenna, which stays on air until the
# cut. It starts once the antenna has aired this long, tries again this long after a failed
# preparation, at most this many times for one airing, and never for a source whose feed
# recovery budget is used up. Not in a game's closing stretch, nor in a slot's last minutes:
# the Roku is then the warm-up's, for what follows.
UPGRADE_SETTLE_SECONDS = 30
UPGRADE_RETRY_SECONDS = 120
UPGRADE_ATTEMPTS = 3
# It leaves YouTube TV one feed recovery in its window: a feed that keeps failing there
# stays on the antenna, and the antenna keeps its own budget for its own failures.
UPGRADE_LIMIT = RECOVERY_LIMIT - 1
# What follows a held take is the schedule's block, which joins Up next only when the take ends.
SCHEDULE = object()
# The priority rank of a held take, and of an entry without a scheduled show (programming.NORMAL).
NORMAL = 1


class SourceQueue(PlayoutQueue):
    def __init__(self, state_file, executor, game_status, *, validate_program=None,
                 schedules_file=None, poll_seconds=2, start_worker=True, preroll=None,
                 preroll_seconds=300, retry_seconds=20, prepare_attempts=3, media_gate=None, on_pause=None,
                 on_hold_end=None, hold_poll_seconds=15, ident=None, ident_seconds=IDENT_SECONDS,
                 on_air=None, game_on=None, hold_lost_seconds=HOLD_LOST_SECONDS, input_failure=None,
                 final_buffer_seconds=FINAL_BUFFER_SECONDS, ready=None, stop_preroll=None, schedule_now=None,
                 alternates=None, upgrade=None, roku_playing=None, rank=None):
        """preroll(item) prepares a Roku or library entry without taking it: 'prepared', or
        'skipped' when the Roku is on air; a library cue returns {'outcome', 'input_id'}.
        A failed Roku preparation is retried before blocking.
        media_gate(item) opens 'after_current' entries once the on-air file has ended.
        on_pause() disarms a file cued to follow the on-air one.
        on_hold_end(hold) queues what follows a manual take once its end time or game end
        arrives (final_buffer_seconds after the feeds call the game final); the queue resumes
        afterwards. A game-gated entry waits out the same buffer. A take that drops to the test card for
        hold_lost_seconds ends its hold too, and goes back on first if it had aired a while.
        ident(target) puts the station ID on air over the end of what is on air: 30 s before a
        timed entry or a manual take's end time, and when a held game ends.
        on_air() returns master's on-air target, None for the test card.
        game_on(item) returns the game a just-taken entry carries (live or starting within the
        hour), or None; that game then holds master until it is final.
        input_failure() returns master's last input failure ({'target': {'id', ...}, 'error',
        'was_on_air'}): when the live input the queue put on air fails there, the program goes
        back on at the head of Up next (feed recovery). alternates(target, game) names the other
        sources carrying it ({'antenna', 'roku'} targets, either None): recovery takes the antenna
        first (it tunes in seconds), and the other source once one has failed too often.
        roku_playing(target) briefly checks that the Roku still plays a failed Roku program
        without navigating; its feed then goes back on from the Roku first, as fast.
        Warm-ups (_warm_step) prepare through preroll too. ready(target) says whether the Roku
        holds a fresh preparation of target, so none is needed; stop_preroll(item_id) stops a
        warm-up still running when something else is due; schedule_now() is the schedule's
        transition a held take would hand back to now ({'target', 'title', 'key'}) or None.
        upgrade(item) cuts to item's Roku target once preroll has prepared it beside the
        antenna on air, without navigating (_upgrade_step): back to YouTube TV.
        rank(schedule_key) is a schedule entry's priority rank (Programming.rank), read live."""
        self.preroll = preroll
        self.upgrade = upgrade
        self.ready, self.stop_preroll, self.schedule_now = ready, stop_preroll, schedule_now
        # The warm-up running: its entry id and target key. The last target warmed (used when
        # there is no ready()), failures per target (count, monotonic retry time), whether the
        # running one was stopped, a line for Up next, and the schedule's last answer.
        self._warming = self._warm_key = self._warmed = None
        self._warm_failures = {}
        self._warm_stopped = False
        self._warm_note = None
        self._schedule_cache = None
        # Back to YouTube TV (_upgrade_step): the antenna input on air and when it was first
        # seen, failed preparations per antenna input (count, monotonic retry time), and a
        # line for Up next. A running one holds _warming (the Roku) under an 'upgrade:' id.
        self._upgrade_seen = None
        self._upgrade_failures = {}
        self._upgrade_note = None
        self.media_gate = media_gate or (lambda item: {'finished': True})
        self.on_pause = on_pause
        self.on_hold_end = on_hold_end
        self.rank = rank
        self.ident, self.ident_seconds = ident, ident_seconds
        self.preroll_seconds, self.retry_seconds = preroll_seconds, retry_seconds
        self.prepare_attempts = prepare_attempts
        self.hold_poll_seconds = hold_poll_seconds
        self.on_air = on_air or (lambda: None)
        self.game_on = game_on
        self.input_failure = input_failure
        self.alternates = alternates
        self.roku_playing = roku_playing
        # The live entry the queue last put on air without a hold: {'item_id', 'input_id'}.
        self._airing = None
        # (source_id, channel_id) -> monotonic times its feed was put back on.
        self._recoveries = {}
        # What is on air has ended (a game went final, the schedule moved on): recordings may start.
        self._free = False
        # The latest score line of each game the queue checks, for Up next.
        self._scores = {}
        # "league:game_pk" -> monotonic time the queue first saw that game final.
        self.final_buffer_seconds = final_buffer_seconds
        self._finals = {}
        self.paused = True
        self.pause_reason = 'Review the queue and resume after startup'
        # A manual take's end. Not persisted: a restart always pauses for review.
        self.hold = None
        self._hold_checked = 0.0
        self.hold_lost_seconds = hold_lost_seconds
        self._hold_lost = None  # (hold id, monotonic time master was first seen on the test card)
        self.imported_schedules = set()
        self.validate_program = validate_program or (lambda item: None)
        super().__init__(state_file, executor, game_status, poll_seconds=poll_seconds, start_worker=False)
        if schedules_file:
            self._import_schedules(schedules_file)
        with self._condition:
            self._save_locked()
        if start_worker:
            self.start()

    def start(self):
        with self._condition:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name='source-queue', daemon=True)
                self._thread.start()

    def _load(self):
        if not self.state_file.exists():
            return {}
        raw = json.loads(self.state_file.read_text())
        if isinstance(raw, list):
            backup = self.state_file.with_suffix('.pre-master.json')
            if not backup.exists():
                with backup.open('x') as handle:
                    handle.write(self.state_file.read_text())
            values = raw
        elif isinstance(raw, dict) and raw.get('version') == 2:
            values = raw['items']
            self.imported_schedules = set(raw.get('imported_schedules', []))
        else:
            raise ConfigError('Unsupported source queue state')
        items = {}
        for value in values:
            item = SourceQueueItem(**value)
            item.target = item.target or {'source_id': 'youtube-tv', 'channel_id': item.channel}
            if self._library(item):
                item.prerolled_at = item.prepared_input_id = None  # The worker restarts on fallback.
            if item.status == 'running':
                item.status = 'blocked'
                item.gate_status = 'interrupted'
                item.gate_detail = 'Switch outcome is unknown after restart. Check master, then Retry or Skip.'
            items[item.id] = item
        return items

    def _import_schedules(self, path):
        path = Path(path)
        if not path.exists():
            return
        for job in sorted(json.loads(path.read_text()), key=lambda v: v['run_at']):
            if job['id'] in self.imported_schedules:
                continue
            item = SourceQueueItem(**job, position=self._next_position_locked(), release_type='at_time',
                                   target={'source_id': 'youtube-tv', 'channel_id': job['channel']},
                                   schedule_id=job['id'])
            item.id = 'schedule-' + job['id']
            if item.status == 'running':
                item.status, item.gate_status = 'blocked', 'interrupted'
                item.gate_detail = 'Interrupted schedule: check master, then Retry or Skip.'
            self._items[item.id] = item
            self.imported_schedules.add(job['id'])

    def _save_locked(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 2, 'paused': self.paused,
            'pause_reason': self.pause_reason, 'imported_schedules': sorted(self.imported_schedules),
            'items': [asdict(item) for item in self._ordered_locked()]}, indent=2) + '\n')
        temporary.replace(self.state_file)

    @staticmethod
    def _copy(item):
        return SourceQueueItem(**asdict(item))

    def _queued_locked(self):
        return sorted((i for i in self._items.values() if i.status in ('queued', 'blocked')),
                      key=lambda i: (i.position, i.created_at))

    def _ordered_locked(self):
        return ([i for i in self._items.values() if i.status == 'running'] + self._queued_locked()
                + sorted((i for i in self._items.values() if i.status not in ('queued', 'blocked', 'running')),
                         key=lambda i: i.completed_at or i.created_at, reverse=True))

    @staticmethod
    def _fills(item):
        """Queued to follow what is on air: it fills time around the timed rundown."""
        return item.release_type == 'after_current'

    def _lanes_locked(self):
        """(timed rundown, recordings filling time), each in queue order."""
        pending = self._queued_locked()
        return [i for i in pending if not self._fills(i)], [i for i in pending if self._fills(i)]

    @staticmethod
    def _schedule_kind(item):
        """(kind, ref) of a programming entry from its key "run_at|kind|ref|target"."""
        parts = (item.schedule_key or '').split('|', 3)
        return (item.kind or parts[1], parts[2]) if item.origin == 'programming' and len(parts) == 4 else (None, None)

    def _game_entry(self, item):
        return self._schedule_kind(item)[0] == 'game'

    def _regular(self, item):
        """The regular schedule: a grid block, a program show, OFF AIR, or a game's return to
        the schedule. Unlike a game, a fixed backup or an entry queued by hand, it gives way."""
        if item.origin == 'manual_end':
            return True
        kind, ref = self._schedule_kind(item)
        return kind in ('block', 'show', 'off_air') or (kind == 'backup' and ':' in ref)

    def _rank(self, item):
        """An entry's priority rank: its scheduled show's, else normal."""
        if self.rank is None or item.origin != 'programming':
            return NORMAL
        try:
            return self.rank(item.schedule_key)
        except Exception:  # The schedule cannot answer: nothing is cut on its account.
            return NORMAL

    def _cutter_locked(self, timed, after, above):
        """The first waiting timed entry starting after `after` that outranks `above`, or None."""
        return min((i for i in timed if i.status == 'queued' and i.release_type == 'at_time' and i.run_at
                    and parse_time(i.run_at) > after and self._rank(i) > above),
                   key=lambda i: parse_time(i.run_at), default=None)

    def _cut_hold_locked(self, hold):
        """A scheduled show that outranks a held take ends it at its start, through the take's
        own end time (its station ID, warm-up and hand-back); undone if that show goes or
        drops its priority. Only shows starting after the take: Play now stays on air."""
        cut = hold.get('cut')
        own = cut['until'] if cut else hold.get('until')
        cutter = self._cutter_locked(self._lanes_locked()[0], parse_time(hold['started_at']), NORMAL)
        if cutter is not None and (own is None or parse_time(cutter.run_at) < parse_time(own)):
            new = {'item_id': cutter.id, 'title': cutter.title, 'target': dict(cutter.target or {}), 'until': own}
            if cut == new and hold.get('until') == cutter.run_at:
                return
            hold['cut'], hold['until'] = new, cutter.run_at
        elif cut is not None:
            hold['until'] = own
            del hold['cut']
        else:
            return
        self._save_locked()
        self._condition.notify_all()

    def _cut_locked(self, timed):
        """A scheduled show cuts in at its start in front of what it outranks: while the lane is
        held up (by a game's return waiting for its final, or a held take), the entries ahead
        of it are skipped once it is due, if each has a lower priority and is waiting on a
        game or overdue. True when it acted."""
        if not timed or (self.hold is None and timed[0].release_type != 'after_game'):
            return False  # The lane flows: each entry releases at its own time.
        now = utc_now()
        for index, item in enumerate(timed):
            if (index == 0 or item.status != 'queued' or item.release_type != 'at_time' or not item.run_at
                    or not self._due(item)):
                continue
            ahead, rank = timed[:index], self._rank(item)
            if self.hold is not None and rank <= NORMAL:
                continue
            if not all(self._rank(i) < rank and (i.release_type == 'after_game'
                                                  or (i.run_at and parse_time(i.run_at) <= now)) for i in ahead):
                continue
            for other in ahead:
                other.status, other.gate_status, other.completed_at = 'skipped', 'cut', now.isoformat()
                other.gate_detail = f'{item.title or "A show"} cut in at its start (higher priority)'
                other.prerolled_at = other.prepared_input_id = None
            self._save_locked()
            self._condition.notify_all()
            return True
        return False

    def _master_free(self, on_air):
        """Whether recordings may start: the test card, a file or the station ID is on air
        (a file is followed when it ends), or what is on air has ended."""
        if on_air is UNKNOWN:
            return False
        return self._free or not on_air or on_air.get('source_id') in ('off-air', LIBRARY_SOURCE_ID, IDENT_SOURCE_ID)

    def _gives_way_locked(self, item, timed, fill, on_air, now):
        """What a due regular entry gives way to: 'game' (one already under way follows it),
        'recordings' (waiting, or one playing), or None. Only OFF AIR, or a block already
        under way (joined late after a game), gives way; a live show starting now cuts in."""
        if not self._regular(item):
            return None
        off_air = (item.target or {}).get('source_id') == 'off-air'
        if not (off_air or (item.run_at and now - parse_time(item.run_at) > LATE)):
            return None
        if any(self._game_entry(i) and i.status == 'queued' and i.run_at and parse_time(i.run_at) <= now
               for i in timed if i.id != item.id):
            return 'game'
        if (fill and fill[0].status == 'queued') or (on_air or {}).get('source_id') == LIBRARY_SOURCE_ID:
            return 'recordings'
        return None

    def _due(self, item):
        """The timed head needs the worker now: its time (less the station ID's lead) has
        come, or its early preparation is due. A scheduled game's return is due from its
        start, so the game on air holds recordings too. An entry queued by hand to follow
        a game has its game checked now and then while recordings fill."""
        if item.run_at:
            delay = (parse_time(item.run_at) - utc_now()).total_seconds()
            return (delay <= max(self.ident_seconds, NOW_DELAY.total_seconds())
                    or self._preroll_due_locked(item, delay))
        if item.release_type == 'after_game':
            every = max(self.hold_poll_seconds, 5 * self.poll_seconds)
            return not item.gate_checked_at or utc_now() - parse_time(item.gate_checked_at) > timedelta(seconds=every)
        return False

    def _next_locked(self, timed, fill, on_air):
        """The entry to work on: the timed rundown's head, unless it is not due (or is
        blocked) and recordings can fill the time now."""
        head = timed[0] if timed and timed[0].status == 'queued' else None
        filler = fill[0] if fill and fill[0].status == 'queued' else None
        if filler and self._master_free(on_air) and (head is None or not self._due(head)):
            return filler
        return head

    def _read_on_air(self):
        try:
            return self.on_air()
        except Exception:  # Master unavailable: nothing may assume it is free.
            return UNKNOWN

    def _check_game(self, league, game_pk, game_date):
        status = (self.game_status(game_pk, game_date, league) if league and league != 'mlb'
                  else self.game_status(game_pk, game_date))
        with self._condition:
            self._scores[f'{league or "mlb"}:{game_pk}'] = {
                'title': status.get('title'), 'summary': status.get('summary') or status.get('status'),
                'finished': status.get('finished') is True, 'closing': status.get('closing') is True}
        return status

    def _game_over(self, league, game_pk, game_date):
        """A game's status for handing master on: final only final_buffer_seconds after the
        queue first sees it final, so viewers see the end and the final score."""
        status = self._check_game(league, game_pk, game_date)
        key, now = f'{league or "mlb"}:{game_pk}', time.monotonic()
        with self._condition:
            if status.get('finished') is not True:
                self._finals.pop(key, None)
                return status
            left = self.final_buffer_seconds - (now - self._finals.setdefault(key, now))
        if left <= 0:
            return status
        minutes = max(1, round(left / 60))
        return {**status, 'finished': False,
                'summary': f"{status.get('summary') or status.get('status') or 'Final'} · "
                           f"on for the final score, {minutes} more min"}

    def status(self):
        with self._condition:
            self._expire_locked()
            return {'paused': self.paused, 'pause_reason': self.pause_reason, 'hold': copy.deepcopy(self.hold),
                    'master_queue': True, 'items': [asdict(i) for i in self._ordered_locked()],
                    'games': copy.deepcopy(self._scores), 'warm': copy.deepcopy(self._warm_note),
                    'upgrade': copy.deepcopy(self._upgrade_note)}

    def _forget_cues_locked(self):
        for item in self._queued_locked():
            if self._library(item) and item.prerolled_at:
                item.prerolled_at = item.prepared_input_id = None
                item.gate_status, item.gate_detail = 'waiting', 'Paused · cues again when resumed'

    def pause(self, reason='Paused by operator', keep_hold=False):
        """keep_hold leaves a manual take's end in place, for actions that do not
        change what is on air, such as preparing the next source."""
        with self._condition:
            if not (keep_hold and self.hold):
                self.hold = None
                self.paused, self.pause_reason = True, reason
            self._forget_cues_locked()
            self._save_locked()
            self._condition.notify_all()
            status = self.status()
        if self.on_pause:
            self.on_pause()
        return status

    def resume(self):
        with self._condition:
            if self.hold:
                # Ends the manual take now; the worker hands master back first.
                self.hold['ending'] = True
            else:
                self.paused, self.pause_reason = False, None
            self._save_locked()
            self._condition.notify_all()
            return self.status()

    def hold_for(self, target, end):
        """A manual take owns master until end: {'until': ISO, 'program'?} or {'game': {...}}.
        The queue stays paused until then, and on_hold_end queues what follows.
        end None keeps the take on air with the queue paused, as before."""
        with self._condition:
            self._free = False  # Something new is on air.
            self._airing = None  # A held take recovers through its hold.
            if end is None:
                self.hold = None
                self.paused, self.pause_reason = True, 'Paused by manual master control'
            else:
                now = utc_now()
                shown = {k: v for k, v in (target or {}).items()
                         if k in ('source_id', 'channel_id', 'date', 'resolved_source') and v is not None}
                self.hold = {'id': uuid.uuid4().hex, 'target': shown, 'input_id': (target or {}).get('id'),
                             'started_at': now.isoformat(),
                             'until': end.get('until'), 'game': copy.deepcopy(end.get('game')),
                             'program': copy.deepcopy(end.get('program')), 'detail': None,
                             'limit': (now + HOLD_LIMIT).isoformat() if end.get('game') else None}
                self.paused, self.pause_reason = True, HOLD_REASON
                self._hold_checked = 0.0
            self._save_locked()
            self._condition.notify_all()
            return self.status()

    def follows_hold(self, hold, now=None):
        """Whether Up next already has an entry ready to follow a take (or game) that just
        ended, so the schedule need not be queued in front of it: a game already under way,
        then recordings, then the timed head when it is due."""
        now = now or utc_now()
        with self._condition:
            timed, fill = self._lanes_locked()
            if any(self._game_entry(i) and i.status == 'queued' and i.run_at and parse_time(i.run_at) <= now
                   for i in timed):
                return True
            if any(i.status == 'queued' for i in fill):
                return True  # Recordings play until the next live show starts.
            head = timed[0] if timed else None
            if head is None or head.status == 'blocked':
                return False
            if head.release_type == 'after_game':
                # The take was held for this same game, which has just ended.
                game = (hold or {}).get('game') or {}
                return (head.after_game_pk, head.after_game_date) == (game.get('game_pk'), game.get('game_date'))
            return bool(head.run_at and parse_time(head.run_at) <= now + timedelta(seconds=5))

    def admitted(self, item_id, preroll=False):
        with self._condition:
            if (preroll or str(item_id).startswith('upgrade:')) and item_id == self._warming:
                # A warm-up: what follows a program about to end, even behind a held take.
                item = self._items.get(item_id)
                if self._closed or (self.paused and self.hold is None) or (item is not None and item.status != 'queued'):
                    raise ControlBusyError('Queue paused before source preparation')
                return
            # An early preparation runs while its entry is still waiting at the head of its lane.
            heads = [lane[0] for lane in self._lanes_locked() if lane]
            ready = any(h.id == item_id and h.status == 'queued' for h in heads) if preroll \
                else self._items[item_id].status == 'running'
            if self._closed or self.paused or not ready:
                raise ControlBusyError('Queue paused before source preparation')

    def check_before_take(self, item_id):
        with self._condition:
            item = self._copy(self._items[item_id])
            if self.paused or self._closed:
                raise MasterStreamError('Queue paused during preparation; Retry or Skip this entry')
        if item.program and not item.tune_anyway:
            if item.program.get('end') and utc_now().timestamp() >= item.program['end']:
                raise MasterStreamError('Queued program ended during preparation')
            detail = self.validate_program(item)
            if detail:
                raise MasterStreamError(detail)

    @contextmanager
    def take_guard(self, item_id):
        with self._condition:
            if str(item_id).startswith('upgrade:'):
                # Back to YouTube TV: what it replaces must still be on air as it was.
                if self._closed or item_id != self._warming or self._upgrade_note is None \
                        or self._upgrade_program_locked(self._upgrade_note['input_id']) is None:
                    raise MasterStreamError('What was on air changed; staying on the antenna')
                yield
                return
            if self.paused or self._closed or self._items[item_id].status != 'running':
                raise MasterStreamError('Queue paused before take; Retry or Skip this entry')
            yield

    def add_target(self, target, release_type, *, run_at=None, program=None, after_game=None, schedule_id=None,
                   after_program=None, hold_end=None):
        """release_type 'now' puts the entry at the head of Up next, due in two seconds;
        'after_current' adds it after everything waiting to fill time. hold_end keeps it on
        air until then once taken (see SourceQueueItem)."""
        first = release_type == 'now'
        if first:
            if program and program.get('start', 0) > utc_now().timestamp():
                raise ConfigError('This program has not started yet; queue it for its start time')
            release_type, run_at = 'at_time', (utc_now() + NOW_DELAY).isoformat()
        if release_type in ('at_time', 'scheduled_end'):
            if not isinstance(run_at, str) or parse_time(run_at) <= utc_now():
                raise ConfigError('run_at must be in the future and include a timezone')
            run_at = parse_time(run_at).isoformat()
        elif release_type == 'after_game':
            if not after_game:
                raise ConfigError('An exact game is required for the release condition')
        elif release_type == 'after_current':
            run_at = None
        else:
            raise ConfigError('release_type must be now, at_time, scheduled_end, after_game, or after_current')
        with self._condition:
            item = SourceQueueItem(id=uuid.uuid4().hex, position=self._next_position_locked(),
                channel=target['channel_id'], target=dict(target), program=program, schedule_id=schedule_id,
                after_program=after_program,
                release_type=release_type, created_at=utc_now().isoformat(), run_at=run_at,
                after_game_pk=after_game['game_pk'] if after_game else None,
                after_game_date=after_game['game_date'] if after_game else None,
                after_game_title=after_game['title'] if after_game else None,
                hold_end=copy.deepcopy(hold_end))
            if first:
                self._insert_locked(item, 0)
            self._items[item.id] = item
            self._save_locked()
            self._condition.notify_all()
            return self._copy(item)

    def _insert_locked(self, item, index=None):
        """Place item among the waiting entries at index (None: last) and renumber them."""
        queued = self._queued_locked()
        queued.insert(len(queued) if index is None else index, item)
        for position, other in enumerate(queued):
            other.position = position

    def add_at_time(self, channel, run_at):
        return self.add_target({'source_id': 'youtube-tv', 'channel_id': channel}, 'at_time', run_at=run_at.isoformat())

    def add_after_game(self, channel, *, game_pk, game_date, game_title):
        return self.add_target({'source_id': 'youtube-tv', 'channel_id': channel}, 'after_game',
                               after_game={'game_pk': game_pk, 'game_date': game_date, 'title': game_title})

    def add_scheduled(self, transition, *, origin='programming', first=False):
        """Insert a programming entry among waiting entries in release-time order,
        or at the head (first) when it follows a manual take that has ended."""
        game = transition.get('after_game')
        with self._condition:
            item = SourceQueueItem(id=uuid.uuid4().hex, position=0, channel=transition['target']['channel_id'],
                target=dict(transition['target']), release_type='after_game' if game else 'at_time',
                created_at=utc_now().isoformat(), run_at=parse_time(transition['run_at']).isoformat(),
                after_game_pk=game['game_pk'] if game else None,
                after_game_date=game['game_date'] if game else None,
                after_game_title=game['title'] if game else None,
                after_game_league=game.get('league') if game else None,
                origin=origin, schedule_key=transition.get('key'),
                skip_after=transition.get('skip_after'), title=transition.get('title'),
                kind=transition.get('kind'), game=copy.deepcopy(transition.get('game')))
            at = parse_time(item.run_at)
            index = 0 if first else next((i for i, other in enumerate(self._queued_locked())
                                          if other.run_at and parse_time(other.run_at) > at), None)
            self._insert_locked(item, index)
            self._items[item.id] = item
            self._save_locked()
            self._condition.notify_all()
            return self._copy(item)

    @staticmethod
    def _slot_ended(item, now):
        return bool(item.skip_after and now >= parse_time(item.skip_after))

    @staticmethod
    def _supersede(item, now):
        item.status, item.gate_status = 'skipped', 'superseded'
        item.gate_detail = 'Its scheduled slot ended before it could air'
        item.completed_at = now.isoformat()

    def _superseded_locked(self, item):
        now = utc_now()
        if self._slot_ended(item, now):
            self._supersede(item, now)
            self._save_locked()
            return True
        return False

    def _expire_locked(self):
        """Skip every waiting entry whose slot has ended, even while paused, so the
        queue does not fill with schedule entries that can no longer air. An entry
        being cued is left to the worker, which disarms it."""
        now = utc_now()
        expired = [i for i in self._queued_locked() if i.status == 'queued'
                   and i.gate_status != 'preparing' and self._slot_ended(i, now - (
                       GAME_EXPIRY if i.release_type == 'after_game' else timedelta()))]
        for item in expired:
            self._supersede(item, now)
        if expired:
            self._save_locked()
        return bool(expired)

    def action(self, item_id, action):
        with self._condition:
            item = self._items.get(item_id)
            if item is None:
                return None
            if item.status not in ('queued', 'blocked'):
                raise ConfigError('Only waiting or blocked entries can be changed')
            disarm = False
            if action == 'skip':
                # A recording already cued to follow the on-air file must not play anyway.
                disarm = bool(item.prerolled_at)
                item.status = 'skipped'
                item.completed_at = utc_now().isoformat()
                item.prerolled_at = item.prepared_input_id = None
            elif action in ('retry', 'tune-anyway'):
                if item.status != 'blocked':
                    raise ConfigError('Only blocked entries can be retried')
                if action == 'tune-anyway':
                    item.tune_anyway = True
                item.status, item.gate_status = 'queued', 'waiting'
                item.error = None
                item.gate_detail = None
                item.prepare_attempts, item.retry_at = 0, None
            else:
                raise ConfigError('Unknown queue action')
            self._save_locked()
            self._condition.notify_all()
            result = self._copy(item)
        if disarm and self.on_pause:
            self.on_pause()
        return result

    # Entries the schedule machinery adds; Clear leaves them, Remove keeps their record.
    SYSTEM_ORIGINS = ('programming', 'manual_end')

    def _remove_locked(self, item):
        """Takes a waiting or blocked entry out of Up next; True if a cued file must be disarmed.
        A schedule entry stays listed as skipped: the schedule's next sync would add it back."""
        disarm = bool(item.prerolled_at)
        if item.origin in self.SYSTEM_ORIGINS:
            item.status, item.completed_at = 'skipped', utc_now().isoformat()
            item.gate_detail = 'Removed from Up next'
            item.prerolled_at = item.prepared_input_id = None
        else:
            del self._items[item.id]
        for position, queued in enumerate(self._queued_locked()):
            queued.position = position
        return disarm

    def remove_entry(self, item_id):
        """The operator's Remove for one waiting or blocked entry; None if it is unknown."""
        with self._condition:
            item = self._items.get(item_id)
            if item is None:
                return None
            if item.status not in ('queued', 'blocked'):
                raise ConfigError('Only waiting or blocked entries can be removed')
            removed = self._copy(item)
            disarm = self._remove_locked(item)
            if item.id in self._items:
                removed = self._copy(item)
            self._save_locked()
            self._condition.notify_all()
        if disarm and self.on_pause:
            self.on_pause()
        return removed

    def clear_added(self):
        """Removes every waiting or blocked entry added with Play now or Add to queue;
        scheduled programs stay. Returns how many came out."""
        with self._condition:
            items = [i for i in list(self._items.values())
                     if i.status in ('queued', 'blocked') and i.origin not in self.SYSTEM_ORIGINS]
            disarm = False
            for item in items:
                disarm = self._remove_locked(item) or disarm
            self._save_locked()
            self._condition.notify_all()
        if disarm and self.on_pause:
            self.on_pause()
        return len(items)

    def _block_locked(self, item, gate, detail):
        item.status, item.gate_status, item.gate_detail = 'blocked', gate, detail
        self._save_locked()

    @staticmethod
    def _roku(item):
        return (item.target or {}).get('source_id') in ROKU_SOURCES

    @staticmethod
    def _library(item):
        return (item.target or {}).get('source_id') == LIBRARY_SOURCE_ID

    def _game_status(self, item):
        return self._game_over(item.after_game_league, item.after_game_pk, item.after_game_date)

    def _preroll_due_locked(self, item, delay):
        """delay is None for 'after_current', which can end at any moment: a recording is cued
        right away. A Roku entry is prepared in the last minutes of the recording on air
        instead (_warm_step), so its preparation is still fresh when it is taken."""
        timely = (item.release_type == 'after_current' and self._library(item) if delay is None
                  else item.release_type == 'at_time' and delay <= self.preroll_seconds)
        return bool(self.preroll and (self._roku(item) or self._library(item)) and timely
                    and not item.prerolled_at
                    and not (item.preroll_retry_at and utc_now() < parse_time(item.preroll_retry_at)))

    def _run_preroll(self, candidate):
        """Prepare a Roku entry ahead of its release so the cut lands on time."""
        busy = False
        try:
            outcome, error = self.preroll(candidate), None
        except ControlBusyError as exc:
            outcome, error, busy = None, str(exc), True
        except Exception as exc:
            outcome, error = None, str(exc)
        cue = outcome if isinstance(outcome, dict) else None
        if cue:
            outcome = cue.get('outcome')
        disarm = False
        with self._condition:
            item = self._items.get(candidate.id)
            if item is None or item.status != 'queued' or (cue and self.paused):
                # Paused while cueing: the worker must not cut to it when the file ends.
                disarm = bool(cue and outcome == 'prepared')
                item = None
            if item is not None:
                self._preroll_outcome_locked(item, outcome, error, busy, cue)
        if disarm and self.on_pause:
            self.on_pause()

    def _preroll_outcome_locked(self, item, outcome, error, busy, cue):
        now = utc_now()
        release = parse_time(item.run_at).astimezone().strftime('%-H:%M') if item.run_at else None
        if outcome == 'prepared':
            item.prerolled_at, item.preroll_retry_at = now.isoformat(), None
            item.prepared_input_id = cue.get('input_id') if cue else None
            detail = ('Cued; plays ' + (f'at {release}' if release else
                      'when the current file ends' if cue.get('after_input_id') else 'next')) if cue \
                else 'Prepared early; cuts ' + (f'at {release}' if release else 'when the current file ends')
            item.gate_status, item.gate_detail = 'prepared', detail
        else:
            item.preroll_retry_at = (now + timedelta(seconds=self.retry_seconds)).isoformat()
            item.gate_status = 'waiting'
            if outcome == 'skipped':
                item.gate_detail = 'Roku is on air; will prepare when it is free' + (f' or at {release}' if item.run_at else '')
            elif busy:
                item.gate_detail = f'Master control is busy; retrying early preparation. {error}'
            else:
                item.preroll_attempts += 1
                item.gate_detail = (f'Early preparation failed (attempt {item.preroll_attempts}): {error}. '
                                    'Retrying; it also prepares again at release.')
        self._save_locked()
        self._condition.notify_all()

    def _hold_lost_locked(self, hold, on_air, failed=False):
        """Whether the held take has left master: master names its input as failed on air
        (its own stall recovery is over), or the test card, read for hold_lost_seconds."""
        if on_air is UNKNOWN or on_air:
            self._hold_lost = None
            return False
        if failed:
            return True
        if not self._hold_lost or self._hold_lost[0] != hold['id']:
            self._hold_lost = (hold['id'], time.monotonic())
        return time.monotonic() - self._hold_lost[1] >= self.hold_lost_seconds

    def _hold_failure(self, on_air):
        """Master's failure of the held take's input, once master has given up on it (not
        while it waits for the input on the test card), else None. Read without the lock."""
        hold = self.hold
        if (hold is None or not hold.get('input_id') or self.input_failure is None
                or on_air is UNKNOWN or on_air):
            return None
        try:
            failure = self.input_failure() or {}
        except Exception:  # Master unavailable: the test card's own timer still applies.
            return None
        if (failure.get('was_on_air') and not failure.get('recovering')
                and (failure.get('target') or {}).get('id') == hold['input_id']):
            return failure
        return None

    def _hold_step(self, on_air=UNKNOWN):
        """End a manual take whose time has come or whose feed has left master, or check
        its game. True when it acted."""
        failure = self._hold_failure(on_air)
        with self._condition:
            hold = self.hold
            if hold is None or self._closed:
                return False
            now = utc_now()
            if not hold.get('ending'):
                self._cut_hold_locked(hold)
            failed = bool(failure) and (failure.get('target') or {}).get('id') == hold.get('input_id')
            ends = hold.get('ending') or any(hold.get(k) and now >= parse_time(hold[k]) for k in ('until', 'limit'))
            if not ends and self._hold_lost_locked(hold, on_air, failed):
                hold['ending'] = hold['lost'] = ends = True
                logging.getLogger(__name__).warning('Held take left master%s: %s',
                                                    f" ({failure.get('error')})" if failed else '',
                                                    json.dumps(hold['target']))
            if ends:
                # Still paused while what follows is queued, so nothing releases in between.
                self.hold, self.pause_reason = None, RETURNING
                self._free = True  # What was held on air has ended.
                self._save_locked()
                ended, game = hold, None
            elif hold.get('game') and time.monotonic() >= self._hold_checked:
                self._hold_checked = time.monotonic() + self.hold_poll_seconds
                ended, game = None, dict(hold['game'])
            elif (self.ident and hold.get('until') and not hold.get('ident')
                  and now >= parse_time(hold['until']) - timedelta(seconds=self.ident_seconds)):
                hold['ident'] = True  # The take's last 30 s go to the station ID.
                ended = game = None
                cutter = (hold.get('cut') or {}).get('target')
            else:
                return False
        if ended is None and game is None:
            self._run_ident(cutter)
            return True
        if game:
            try:
                status = self._game_over(game['league'], game['game_pk'], game['game_date'])
            except Exception as exc:
                status = {'finished': False, 'status': f'Game status unavailable: {exc}'}
            with self._condition:
                if self.hold and self.hold['id'] == hold['id']:
                    self.hold['detail'] = str(status.get('summary') or status.get('status') or '') or None
                    if status.get('finished') is True:
                        self.hold['ending'] = True
                    self._condition.notify_all()
            return True
        if ended.get('lost'):
            self._reair(ended)
        elif ended.get('game') and not ended.get('ident'):
            self._run_ident(None)  # The game is over: the ID, then what follows.
        try:
            if self.on_hold_end:
                self.on_hold_end(ended)
        except Exception:  # Resume anyway: Up next and the schedule carry on from here.
            logging.getLogger(__name__).exception('Could not queue what follows a manual take')
        with self._condition:
            # A manual action or a new take while returning keeps the queue paused.
            if self.hold is None and self.paused and self.pause_reason == RETURNING:
                self.paused, self.pause_reason = False, None
                self._save_locked()
            self._condition.notify_all()
        return True

    def _reair(self, hold):
        """A held take dropped off master before its end: queue the same source at the head
        of Up next, where it follows at once (and holds again for its game). A game already
        final, or a feed put back too often lately, is not put back."""
        game = hold.get('game')
        if game:
            try:
                if self._check_game(game.get('league'), game['game_pk'], game['game_date']).get('finished') is True:
                    return
            except Exception:
                pass  # Score unavailable: the game was live a moment ago.
        failed = {k: v for k, v in hold['target'].items() if k != 'resolved_source'}
        program = hold.get('program_target') or failed
        choices = self._recovery_choices(program, game)
        with self._condition:
            target = self._recovery_pick_locked(choices, failed)
            if target is None:
                return
        # Its own end time: a show that outranks it cuts the take put back on as it did this one.
        own = {**hold, 'until': hold['cut']['until']} if hold.get('cut') else hold
        end = {k: copy.deepcopy(own[k]) for k in ('until', 'program', 'game') if own.get(k)} or None
        try:
            item = self.add_target(target, 'now', hold_end=end)
        except ConfigError as exc:
            logging.getLogger(__name__).warning('Could not put the held take back on: %s', exc)
            return
        with self._condition:
            self._items[item.id].gate_detail = 'Its feed dropped; going back on' + self._from(target, failed)
            self._items[item.id].recovery = True
            self._items[item.id].program_target = dict(program)
            self._save_locked()

    @staticmethod
    def _live(target):
        """A feed that can fail on air and be tuned again: a tuner or a Roku."""
        return (target or {}).get('source_id') not in (None, 'off-air', LIBRARY_SOURCE_ID, IDENT_SOURCE_ID)

    def _recovery_allowed_locked(self, target, quiet=False):
        """Whether a channel's feed may go back on now, counting this time against its budget."""
        key = ((target or {}).get('source_id'), (target or {}).get('channel_id'))
        now = time.monotonic()
        recent = [t for t in self._recoveries.get(key, ()) if now - t < RECOVERY_WINDOW.total_seconds()]
        if len(recent) >= RECOVERY_LIMIT:
            self._recoveries[key] = recent
            if not quiet:
                logging.getLogger(__name__).warning(
                    'Feed failed again; not put back (%d times in %d minutes): %s', len(recent),
                    RECOVERY_WINDOW.total_seconds() // 60, json.dumps(target))
            return False
        self._recoveries[key] = recent + [now]
        return True

    def _recovery_choices(self, program, game):
        """The targets a failed program may go back on from, in order: the antenna first when
        it carries the program (it tunes in seconds; YouTube TV takes 20 s to 2 min), then
        YouTube TV alone. The Roku comes first when it still plays the program: its feed goes
        back on without navigating, as fast, in the better picture. Without alternates, only
        the program's own target."""
        alternates = {}
        if self.alternates is not None:
            try:
                alternates = self.alternates(program, game) or {}
            except Exception as exc:  # Only narrows the choice to the program's own source.
                logging.getLogger(__name__).warning('Could not look up another source: %s', exc)
        antenna, roku = alternates.get('antenna'), alternates.get('roku')
        if (program or {}).get('source_id') in ROKU_SOURCES:
            choices = ([roku or program, antenna] if antenna and self._roku_still_playing(program)
                       else [antenna, roku or program])
        elif antenna is not None:  # The program is an antenna station: YouTube TV is its other source.
            choices = [program, roku]
        else:
            choices = [program]
        return [dict(c) for c in choices if c]

    def _roku_still_playing(self, program):
        if self.roku_playing is None:
            return False
        try:
            return self.roku_playing(program) is True
        except Exception as exc:  # The antenna goes first, as without the check.
            logging.getLogger(__name__).warning('Could not check what the Roku plays: %s', exc)
            return False

    def _recovery_pick_locked(self, choices, failed):
        """The first choice whose source has budget left (counting it), or None, logged."""
        log = logging.getLogger(__name__)
        for target in choices:
            if self._recovery_allowed_locked(target, quiet=True):
                log.warning('Feed recovery: putting it back on%s (%d of %d in %d minutes from that source): %s',
                            self._from(target, failed),
                            len(self._recoveries[(target.get('source_id'), target.get('channel_id'))]), RECOVERY_LIMIT,
                            RECOVERY_WINDOW.total_seconds() // 60, json.dumps(target))
                return target
        log.warning('Feed failed again; not put back: every source carrying it went back on %d times '
                    'in %d minutes: %s', RECOVERY_LIMIT, RECOVERY_WINDOW.total_seconds() // 60, json.dumps(choices))
        return None

    @staticmethod
    def _from(target, failed):
        """Where a recovery goes back on from, when that is not the source that failed."""
        if (target.get('source_id'), target.get('channel_id')) == ((failed or {}).get('source_id'), (failed or {}).get('channel_id')):
            return ''
        if str(target.get('source_id')).startswith('tv-thing-'):
            return f" from the antenna ({target.get('channel_id')})"
        return f" from YouTube TV ({target.get('channel_id')})" if target.get('source_id') == 'youtube-tv' \
            else f" from {target.get('source_id')}"

    def _recover_step(self, on_air):
        """Feed recovery: the live program the queue put on air failed on master (the test
        card, and master names that input as failed on air). Put it back on at the head of Up
        next, unless its slot is ending or its game is over. True when it acted."""
        if self._airing is None or self.input_failure is None:
            return False  # Nothing watched: no lock taken, so a pass reads master as it did.
        with self._condition:
            airing = self._airing
            if (airing is None or self.input_failure is None or on_air is UNKNOWN or on_air
                    or self.paused or self.hold is not None or self._closed):
                return False
        try:
            failure = self.input_failure() or {}
        except Exception:  # Master unavailable: try again on the next pass.
            return False
        if not failure.get('was_on_air') or (failure.get('target') or {}).get('id') != airing['input_id']:
            return False
        with self._condition:
            if self._airing is not airing:
                return False
            self._airing = None  # One failure, one recovery.
            item = self._items.get(airing['item_id'])
            item = self._copy(item) if item else None
        if item is None:
            return True
        log = logging.getLogger(__name__)
        failed = {k: v for k, v in (failure.get('target') or {}).items() if k in ('source_id', 'channel_id', 'quality')}
        log.warning('Feed failed on air (%s): %s', failure.get('error'), json.dumps(failed or item.target))
        if item.skip_after and parse_time(item.skip_after) - utc_now() < RECOVERY_MIN_LEFT:
            log.warning('Feed not put back: its slot ends at %s, and what follows is due', item.skip_after)
            return True  # Its slot is ending: what follows airs at its time.
        if item.game and item.game.get('game_pk') is not None:
            try:
                if self._check_game(item.game.get('league'), item.game['game_pk'], item.game.get('game_date')).get('finished') is True:
                    log.warning('Feed not put back: %s is final', item.game.get('title') or item.game['game_pk'])
                    return True
            except Exception:
                pass  # Score unavailable: the game was live a moment ago.
        program = item.program_target or item.target
        choices = self._recovery_choices(program, item.game)
        with self._condition:
            if self._closed:
                return True
            target = self._recovery_pick_locked(choices, failed or item.target)
            if target is None:
                return True
            now = utc_now()
            again = replace(item, id=uuid.uuid4().hex, status='queued', gate_status='waiting',
                            gate_detail=f"Its feed dropped ({failure.get('error') or 'input failed'}); going back on"
                                        + self._from(target, failed or item.target),
                            target=target, channel=str(target.get('channel_id')), program_target=dict(program),
                            gate_checked_at=None, started_at=None, completed_at=None, result=None, error=None,
                            created_at=now.isoformat(), run_at=(now + NOW_DELAY).isoformat(), release_type='at_time',
                            late=False, prerolled_at=None, preroll_attempts=0, preroll_retry_at=None,
                            prepare_attempts=0, retry_at=None, prepared_input_id=None, ident_at=None, recovery=True)
            self._insert_locked(again, 0)
            self._items[again.id] = again
            self._save_locked()
            self._condition.notify_all()
        return True

    def _ident_due_locked(self, item, delay, gives_way=False):
        """The station ID airs in the last 30 s before a timed entry releases, unless the
        entry will give way (OFF AIR while recordings play on)."""
        return bool(self.ident and not item.ident_at and item.release_type in ('at_time', 'scheduled_end')
                    and not gives_way and self.ident_seconds - IDENT_WINDOW <= delay <= self.ident_seconds)

    def _waiting_fill_locked(self, fill, on_air):
        """Say why the first recording waits while a live program owns master."""
        head = fill[0] if fill and fill[0].status == 'queued' else None
        if (head is None or self._master_free(on_air) or head.gate_status == 'preparing'
                or (head.gate_status == 'prepared' and self._roku(head))):  # Warmed up (_warm_step).
            return
        detail = ('Waits for master' if on_air is UNKNOWN else
                  'Plays when what is on air ends: a game when it is final, a live show at the next gap in the schedule')
        if (head.gate_status, head.gate_detail) != ('waiting', detail):
            head.gate_status, head.gate_detail = 'waiting', detail
            self._save_locked()

    def _run_ident(self, target):
        if not self.ident:
            return
        try:
            self.ident(target)
        except Exception as exc:  # The ID is a nicety: never hold up the queue for it.
            logging.getLogger(__name__).warning('Station ID was not played: %s', exc)

    # Warm-ups: the Roku entry that follows a program about to end ------------------------
    @staticmethod
    def _target_key(target):
        return tuple((target or {}).get(k) for k in ('source_id', 'channel_id', 'date'))

    def _closing(self, league, game_pk):
        """Whether the queue's latest check of a game found it in its closing stretch or over."""
        return (self._scores.get(f'{league or "mlb"}:{game_pk}') or {}).get('closing') is True

    def _under_way_locked(self, timed, at):
        """A scheduled game started by at: it follows a game's final before anything else."""
        return next((i for i in timed if self._game_entry(i) and i.status == 'queued' and i.run_at
                     and parse_time(i.run_at) <= at), None)

    def _warm_candidate_locked(self, on_air, now):
        """(entry, ready_by, ends) while what is on air ends soon: the entry that takes master
        then (SCHEDULE: the block the schedule hands a held take back to), the wall time it
        must be ready by (None for a game, whose final has no time), and what is ending."""
        timed, fill = self._lanes_locked()
        head = timed[0] if timed and timed[0].status == 'queued' else None
        filler = fill[0] if fill and fill[0].status == 'queued' else None
        hold = self.hold
        if hold is not None:
            game = hold.get('game')
            if hold.get('ending'):
                return None
            if hold.get('until') and parse_time(hold['until']) - now <= timedelta(seconds=ENDING_SECONDS):
                # A take held to a time, or a game a show that outranks it cuts at its start.
                at = ready_by = parse_time(hold['until'])
                ends = (hold.get('program') or {}).get('title') or (game or {}).get('title') or 'what is on air'
            elif game:
                if not self._closing(game.get('league'), game.get('game_pk')):
                    return None
                at, ready_by, ends = now, None, game.get('title') or 'the game'
            else:
                return None
            # As follows_hold and take_back: the show cutting in, a game under way, recordings,
            # the head when it is due or waits on this game, else the schedule.
            cutter = self._items.get((hold.get('cut') or {}).get('item_id'))
            entry = ((cutter if cutter is not None and cutter.status == 'queued' else None)
                     or self._under_way_locked(timed, at) or filler)
            if entry is None and head is not None:
                if head.release_type == 'after_game':
                    same = game and (head.after_game_pk, head.after_game_date) == (game.get('game_pk'), game.get('game_date'))
                    entry = head if same else None
                elif head.run_at and parse_time(head.run_at) <= at + timedelta(seconds=5):
                    entry = head
            return entry or SCHEDULE, ready_by, ends
        if self.paused:
            return None
        if head is not None and head.release_type == 'after_game':
            # A game's return: a game under way follows its final, then recordings when the
            # return gives way to them, then the first return whose slot is still on.
            if not self._closing(head.after_game_league, head.after_game_pk):
                return None
            game = (head.after_game_pk, head.after_game_date)
            entry = (self._under_way_locked(timed, now) or (filler if self._regular(head) else None)
                     or next((i for i in timed if i.status == 'queued' and (i.after_game_pk, i.after_game_date) == game
                              and not self._slot_ended(i, now)), None))
            return (entry, None, head.after_game_title or 'the game') if entry else None
        if (on_air or {}).get('source_id') != LIBRARY_SOURCE_ID or filler is None or not self._roku(filler):
            return None
        media = on_air.get('media') or {}
        position, duration = media.get('position_seconds'), media.get('duration_seconds')
        left = max(0., duration - position) if position is not None and duration else None
        if left is not None and left > ENDING_SECONDS:
            return None
        end = now + timedelta(seconds=left or 0)
        if head is not None and head.run_at and parse_time(head.run_at) <= end + timedelta(seconds=self.preroll_seconds):
            return None  # A timed entry due by then is prepared 5 minutes ahead itself.
        return filler, end if left is not None else None, 'the recording'

    def _scheduled_entry(self):
        """The block the schedule hands a held take back to, as a stand-in entry (it joins Up
        next only when the take ends), or None. Asked at most every SCHEDULE_CHECK_SECONDS."""
        if self.schedule_now is None:
            return None
        cached = self._schedule_cache
        if cached and time.monotonic() - cached[0] < SCHEDULE_CHECK_SECONDS:
            return cached[1]
        try:
            transition = self.schedule_now()
        except Exception as exc:
            logging.getLogger(__name__).warning('Could not read what the schedule puts on next: %s', exc)
            transition = None
        entry = None
        if transition and isinstance(transition.get('target'), dict):
            target = dict(transition['target'])
            entry = SourceQueueItem(id='schedule:' + str(transition.get('key')), position=-1,
                                    channel=str(target.get('channel_id')), release_type='at_time',
                                    created_at=utc_now().isoformat(), target=target, title=transition.get('title'),
                                    origin='programming', schedule_key=transition.get('key'))
        self._schedule_cache = (time.monotonic(), entry)
        return entry

    def _is_ready(self, target):
        if self.ready is None:
            return self._warmed == self._target_key(target)
        try:
            return bool(self.ready(target))
        except Exception:
            return False

    def _warm_step(self, on_air):
        """Warm-up: while another source is on air, prepare the Roku entry that follows a program
        about to end (a game in its closing stretch; a recording, or a show held to an end time,
        in its last three minutes), so the cut does not wait for YouTube TV to change channel.
        It runs beside the queue; a release due meanwhile waits for it, or stops it when the
        release is for another channel."""
        if self.preroll is None:
            return
        source = (on_air or {}).get('source_id') if on_air is not UNKNOWN else None
        with self._condition:
            if self._closed or self._warming:
                return
            found = (self._warm_candidate_locked(on_air, utc_now())
                     if source and source not in ROKU_SOURCES + (IDENT_SOURCE_ID, 'off-air') else None)
            if found is None:
                self._warm_note = None
                self._warm_failures.clear()  # Each ending gets its own tries.
                return
            entry, ready_by, ends = found
            entry = entry if entry is SCHEDULE else self._copy(entry)
        if entry is SCHEDULE:
            entry = self._scheduled_entry()
        if entry is None or not self._roku(entry) or self._is_ready(entry.target):
            return
        key = self._target_key(entry.target)
        with self._condition:
            item = self._items.get(entry.id)
            count, retry_at = self._warm_failures.get(key, (0, 0.))
            if (self._closed or self._warming or (item is not None and item.status != 'queued')
                    or count >= WARM_ATTEMPTS or time.monotonic() < retry_at):
                return
            self._warming, self._warm_key, self._warm_stopped = entry.id, key, False
            if item is not None:
                item.gate_status, item.gate_detail = 'preparing', f'Preparing early, while {ends} finishes'
                self._save_locked()
            self._warm_note = {'target': dict(entry.target), 'title': entry.title, 'ends': ends,
                               'state': 'preparing', 'error': None}
        candidate = replace(entry, run_at=ready_by.isoformat() if ready_by else None)
        threading.Thread(target=self._warm, args=(candidate, ends), name='source-warm', daemon=True).start()

    def _warm(self, candidate, ends):
        log = logging.getLogger(__name__)
        log.info('Preparing %s early, while %s finishes', json.dumps(candidate.target), ends)
        busy = False
        try:
            outcome, error = self.preroll(candidate), None
        except ControlBusyError as exc:
            outcome, error, busy = None, str(exc), True
        except Exception as exc:
            outcome, error = None, str(exc)
        if isinstance(outcome, dict):
            outcome = outcome.get('outcome')
        key = self._target_key(candidate.target)
        with self._condition:
            stopped = self._warm_stopped or busy or outcome == 'skipped'
            self._warming = self._warm_key = None
            self._warm_stopped = False
            item = self._items.get(candidate.id)
            item = item if item is not None and item.status == 'queued' else None
            note = self._warm_note if self._warm_note and self._target_key(self._warm_note['target']) == key else None
            if outcome == 'prepared':
                self._warmed = key
                self._warm_failures.pop(key, None)
                if item is not None:
                    item.prerolled_at, item.preroll_retry_at = utc_now().isoformat(), None
                    item.gate_status, item.gate_detail = 'prepared', f'Prepared early; goes on when {ends} ends'
                if note:
                    note['state'] = 'ready'
            else:
                count = self._warm_failures.get(key, (0, 0.))[0] + (0 if stopped else 1)
                self._warm_failures[key] = (count, time.monotonic() + self.retry_seconds)
                if item is not None:
                    item.gate_status = 'waiting'
                    item.gate_detail = None if stopped else f'Early preparation failed ({error}); it prepares when it goes on'
                if note:
                    note.update(state='stopped' if stopped else 'failed', error=error)
            if item is not None:
                self._save_locked()
            self._condition.notify_all()
        if outcome == 'prepared':
            log.info('Prepared %s early: it goes on when %s ends', json.dumps(candidate.target), ends)
        else:
            log.warning('Early preparation of %s %s: %s', json.dumps(candidate.target),
                        'stopped' if stopped else 'failed', error or outcome)

    def _stop_warm_for(self, item):
        """A release found master control busy: a warm-up for another channel gives way to it.
        One for the same channel finishes, and the release reuses it."""
        with self._condition:
            warming = self._warming
            if (warming is None or self.stop_preroll is None
                    or self._warm_key == self._target_key(item.target)):
                return
            self._warm_stopped = True
        logging.getLogger(__name__).info('Stopping an early preparation: %s is due', json.dumps(item.target))
        try:
            self.stop_preroll(warming)
        except Exception as exc:
            logging.getLogger(__name__).warning('Could not stop the early preparation: %s', exc)

    # Back to YouTube TV: a program on air from the antenna in its place -----------------
    @staticmethod
    def _roku_choice(program):
        """The program from YouTube TV alone, as feed recovery's alternates name it."""
        plain = {k: v for k, v in program.items() if k != 'antenna'}
        return {**plain, 'antenna': False} if plain.get('source_id') in ('youtube-tv', 'mlb') else plain

    def _upgrade_program_locked(self, input_id, now=None):
        """The Roku program the antenna input input_id is on air in place of (a held take,
        or the live entry watched for feed recovery), while it may still go back there, or
        None: no such program, or the Roku is the warm-up's (a game's closing stretch, a
        slot's last minutes)."""
        now, hold = now or utc_now(), self.hold
        if hold is not None:
            if hold.get('ending') or not input_id or hold.get('input_id') != input_id:
                return None
            if hold.get('until') and parse_time(hold['until']) - now <= timedelta(seconds=ENDING_SECONDS):
                return None
            program, game = hold.get('program_target'), hold.get('game')
        else:
            airing = self._airing
            if self.paused or not airing or not input_id or airing.get('input_id') != input_id:
                return None
            item = self._items.get(airing['item_id'])
            if item is None or (item.skip_after and parse_time(item.skip_after) - now <= timedelta(seconds=ENDING_SECONDS)):
                return None
            program, game = airing.get('program_target'), item.game
        if game and self._closing(game.get('league'), game.get('game_pk')):
            return None
        return program if (program or {}).get('source_id') in ROKU_SOURCES else None

    def _upgrade_left_locked(self, target):
        """Whether going back to target leaves its source a feed recovery (UPGRADE_LIMIT)."""
        now = time.monotonic()
        recent = [t for t in self._recoveries.get((target.get('source_id'), target.get('channel_id')), ())
                  if now - t < RECOVERY_WINDOW.total_seconds()]
        return len(recent) < UPGRADE_LIMIT

    def _upgrade_step(self, on_air):
        """Back to YouTube TV: while the antenna carries a program in YouTube TV's place, prepare
        it on the Roku beside the antenna (which stays on air), then cut to it once ready."""
        if self.preroll is None or self.upgrade is None:
            return
        input_id = (on_air or {}).get('id') if on_air is not UNKNOWN else None
        antenna = bool(input_id) and str(on_air.get('source_id')).startswith('tv-thing-')
        with self._condition:
            if self._closed or self._warming:
                return
            program = self._upgrade_program_locked(input_id) if antenna else None
            if program is None:
                self._upgrade_seen = None
                self._upgrade_failures.clear()  # Each airing from the antenna gets its own tries.
                if self._upgrade_note and self._upgrade_note.get('input_id') != input_id:
                    self._upgrade_note = None
                return
            if not self._upgrade_seen or self._upgrade_seen[0] != input_id:
                self._upgrade_seen = (input_id, time.monotonic())
                return
            target = self._roku_choice(program)
            count, retry_at = self._upgrade_failures.get(input_id, (0, 0.))
            if (time.monotonic() - self._upgrade_seen[1] < UPGRADE_SETTLE_SECONDS or count >= UPGRADE_ATTEMPTS
                    or time.monotonic() < retry_at or not self._upgrade_left_locked(target)):
                return
            candidate = SourceQueueItem(id='upgrade:' + uuid.uuid4().hex, position=-1,
                                        channel=str(target.get('channel_id')), release_type='at_time',
                                        created_at=utc_now().isoformat(), target=target)
            self._warming, self._warm_key, self._warm_stopped = candidate.id, self._target_key(target), False
            self._upgrade_note = {'target': dict(target), 'input_id': input_id, 'state': 'preparing', 'error': None,
                                  'from': {k: on_air.get(k) for k in ('source_id', 'channel_id')}, 'attempt': count + 1}
        threading.Thread(target=self._upgrade, args=(candidate, input_id), name='source-upgrade', daemon=True).start()

    def _upgrade(self, candidate, input_id):
        log, target = logging.getLogger(__name__), candidate.target
        result = error = None
        busy = False
        try:
            if not self._is_ready(target):
                log.info('Preparing %s on the Roku beside the antenna, to go back to YouTube TV', json.dumps(target))
                outcome = self.preroll(candidate)
                outcome = outcome.get('outcome') if isinstance(outcome, dict) else outcome
                if outcome != 'prepared':
                    raise MasterStreamError(f'Roku preparation {outcome or "failed"}')
            with self._condition:
                if self._upgrade_note and self._upgrade_note.get('input_id') == input_id:
                    self._upgrade_note['state'] = 'switching'
            result = self.upgrade(candidate)
        except ControlBusyError as exc:  # Something due took master control: not a failure.
            error, busy = str(exc), True
        except Exception as exc:
            error = str(exc) or type(exc).__name__
        on_air = (result or {}).get('on_air') or {}
        switched = error is None and bool(on_air.get('id')) and self._target_key(on_air) == self._target_key(target)
        with self._condition:
            stopped = self._warm_stopped or busy
            self._warming = self._warm_key = None
            self._warm_stopped = False
            note = self._upgrade_note if (self._upgrade_note or {}).get('input_id') == input_id else None
            if switched:
                self._recoveries.setdefault((target.get('source_id'), target.get('channel_id')), []).append(time.monotonic())
                self._upgrade_failures.pop(input_id, None)
                shown = {k: v for k, v in on_air.items()
                         if k in ('source_id', 'channel_id', 'date', 'resolved_source') and v is not None}
                item_id = None
                if self.hold is not None and self.hold.get('input_id') == input_id:
                    self.hold.update(target=shown, input_id=on_air['id'])
                    item_id = self.hold.get('item_id')
                elif self._airing and self._airing.get('input_id') == input_id:
                    self._airing['input_id'] = on_air['id']
                    item_id = self._airing['item_id']
                item = self._items.get(item_id) if item_id else None
                if item is not None:
                    item.gate_detail = (item.gate_detail + ' · ' if item.gate_detail else '') + \
                        'back on YouTube TV at ' + utc_now().astimezone().strftime('%-H:%M')
                if note:
                    note.update(state='switched', input_id=on_air['id'], error=None)
            else:
                count = self._upgrade_failures.get(input_id, (0, 0.))[0] + (0 if stopped else 1)
                self._upgrade_failures[input_id] = (count, time.monotonic() + UPGRADE_RETRY_SECONDS)
                if note:
                    note.update(state='stopped' if stopped else 'failed', error=error,
                                retry=count < UPGRADE_ATTEMPTS)
            self._save_locked()
            self._condition.notify_all()
        if switched:
            log.warning('Back on YouTube TV from the antenna: %s', json.dumps(target))
        else:
            log.warning('Could not go back to YouTube TV (%s); staying on the antenna: %s',
                        error or 'the take was not confirmed', json.dumps(target))

    def _run(self):
        while True:
            on_air = self._read_on_air()
            if self._hold_step(on_air) or self._recover_step(on_air):
                continue
            self._warm_step(on_air)
            self._upgrade_step(on_air)
            preroll = ident = None
            with self._condition:
                if self._closed:
                    return
                self._expire_locked()
                timed, fill = self._lanes_locked()
                if (not self.paused or self.hold is not None) and self._cut_locked(timed):
                    timed, fill = self._lanes_locked()
                item = None if self.paused else self._next_locked(timed, fill, on_air)
                if item is not None and item is not (fill[0] if fill else None):
                    self._waiting_fill_locked(fill, on_air)
                if item is None:
                    # Timed wake-ups keep expiring ended slots while nothing can release.
                    if not self.paused:
                        self._waiting_fill_locked(fill, on_air)
                    self._condition.wait(timeout=self.poll_seconds)
                    continue
                # A game backup waits for the final even past its slot, holding what
                # follows, so an overrunning game is not cut off.
                if item.release_type != 'after_game' and self._superseded_locked(item):
                    continue
                program = item.program if not item.tune_anyway else None
                if program and program.get('end') and utc_now().timestamp() >= program['end']:
                    self._block_locked(item, 'missed', 'This program has ended. Skip or Tune channel anyway.')
                    continue
                if item.release_type == 'after_current' and self._preroll_due_locked(item, None):
                    item.gate_status, item.gate_detail = 'preparing', 'Cueing ahead of release'
                    self._save_locked()
                    preroll = self._copy(item)
                elif item.run_at:
                    delay = (parse_time(item.run_at) - utc_now()).total_seconds()
                    gives_way = bool(self._gives_way_locked(item, timed, fill, on_air, parse_time(item.run_at)))
                    if delay > 0 and self._ident_due_locked(item, delay, gives_way):
                        item.ident_at = utc_now().isoformat()
                        self._save_locked()
                        ident = self._copy(item)
                    elif delay > 0 and self._preroll_due_locked(item, delay):
                        item.gate_status, item.gate_detail = 'preparing', 'Preparing 5 minutes ahead'
                        self._save_locked()
                        preroll = self._copy(item)
                    elif delay > 0:
                        # Wake exactly when the station ID is due, then again at release.
                        to_ident = delay - self.ident_seconds if self.ident and not item.ident_at else 0
                        self._condition.wait(timeout=min(to_ident if to_ident > 0 else delay, self.poll_seconds))
                        continue
                if ident is None and preroll is None and item.retry_at:
                    remaining = (parse_time(item.retry_at) - utc_now()).total_seconds()
                    if remaining > 0:
                        self._condition.wait(timeout=min(remaining, self.poll_seconds))
                        continue
                if ident is None and preroll is None and program and program['start'] > utc_now().timestamp():
                    item.gate_status = 'waiting'
                    item.gate_detail = 'Waiting for the queued program to start'
                    self._save_locked()
                    self._condition.wait(timeout=self.poll_seconds)
                    continue
                candidate = self._copy(item)
            if ident is not None:
                self._run_ident(ident.target)
                with self._condition:
                    item = self._items.get(ident.id)
                    if item is not None and item.status == 'queued' and not item.prerolled_at:
                        item.preroll_retry_at = None  # The ID freed the Roku: prepare now, under the ID.
                continue
            if preroll is not None:
                self._run_preroll(preroll)
                continue
            # Catalog/network work never holds the queue mutex. Recheck head and pause afterwards.
            try:
                detail = self.validate_program(candidate) if program else None
                gate = (self._game_status(candidate) if candidate.release_type == 'after_game'
                        else self.media_gate(candidate) if candidate.release_type == 'after_current'
                        else {'finished': True})
                unavailable = None
            except Exception as exc:
                detail, gate, unavailable = None, {}, str(exc)
            with self._condition:
                if self._closed:
                    return
                timed, fill = self._lanes_locked()
                item = None if self.paused else self._next_locked(timed, fill, on_air)
                if item is None or item.id != candidate.id:
                    continue
                item.gate_checked_at = utc_now().isoformat()
                if detail:
                    self._block_locked(item, 'changed', detail)
                    continue
                if unavailable or gate.get('finished') is not True:
                    warming = item.id == self._warming
                    item.gate_status = ('unavailable' if unavailable else 'preparing' if warming else
                                        'prepared' if item.prerolled_at and item.release_type in ('after_current', 'after_game')
                                        else 'waiting')
                    item.gate_detail = unavailable or str(gate.get('summary') or gate.get('status') or 'Waiting for game to finish')
                    if not unavailable and self._roku(item) and (warming or item.prerolled_at):
                        item.gate_detail += ' · preparing early' if warming else ' · prepared early'
                    self._save_locked()
                    self._condition.wait(timeout=self.poll_seconds)
                    continue
                if program and program.get('end') and utc_now().timestamp() >= program['end']:
                    self._block_locked(item, 'missed', 'This program has ended. Skip or Tune channel anyway.')
                    continue
                if self._superseded_locked(item):
                    continue
                until = (item.hold_end or {}).get('until')
                if until and utc_now() >= parse_time(until):
                    item.status, item.gate_status, item.completed_at = 'skipped', 'superseded', utc_now().isoformat()
                    item.gate_detail = 'Its end time passed before it could air'
                    self._save_locked()
                    self._condition.notify_all()
                    continue
                gives_way = self._gives_way_locked(item, timed, fill, on_air, utc_now())
                if gives_way:
                    # What it would have replaced has ended: the game or recordings take master.
                    item.status, item.gate_status, item.completed_at = 'skipped', 'gave_way', utc_now().isoformat()
                    item.gate_detail = ('The game already under way airs instead' if gives_way == 'game'
                                        else 'Recordings from Up next play instead')
                    self._free = True
                    self._save_locked()
                    self._condition.notify_all()
                    continue
                item.late = bool(program and utc_now().timestamp() > program['start'])
                self._mark_running_locked(item)
                candidate = self._copy(item)
            try:
                result = self.executor(candidate)
                error = None
            except ControlBusyError:
                self._stop_warm_for(candidate)
                with self._condition:
                    item.status, item.gate_status = 'queued', 'waiting'
                    item.started_at = None
                    item.gate_detail = 'Waiting for master control'
                    self._save_locked()
                    self._condition.wait(timeout=self.poll_seconds)
                continue
            except Exception as exc:
                result = None
                error = {'code': getattr(exc, 'code', 'internal_error'), 'message': str(exc)}
                attempts = max(self.prepare_attempts, SLOW_START_ATTEMPTS.get((item.target or {}).get('source_id'), 0))
                if (error['code'] == PREPARE_FAILED and (self._roku(item) or item.recovery)
                        and item.prepare_attempts + 1 < attempts):
                    with self._condition:
                        item.prepare_attempts += 1
                        item.status, item.gate_status, item.started_at = 'queued', 'retrying', None
                        item.retry_at = (utc_now() + timedelta(seconds=self.retry_seconds)).isoformat()
                        item.gate_detail = (f'Preparation failed (attempt {item.prepare_attempts} of '
                                            f'{attempts}): {exc}. Retrying in {self.retry_seconds:g} s')
                        self._save_locked()
                        self._condition.notify_all()
                    continue
            game, end = None, candidate.hold_end
            if not error and not end and self.game_on and candidate.origin is None:
                try:  # An entry queued by hand that carries a game holds master until the final.
                    game = self.game_on(candidate)
                except Exception as exc:
                    logging.getLogger(__name__).warning('Could not check for a game on air: %s', exc)
            if game:
                end = {'game': dict(game)}
            with self._condition:
                item.result, item.error = result, error
                item.completed_at = utc_now().isoformat()
                if error:
                    self._block_locked(item, 'failed', error['message'])
                else:
                    item.status, item.gate_status = 'succeeded', 'taken'
                    antenna = (result or {}).get('antenna')
                    if antenna:
                        item.gate_detail = (f"{antenna.get('reason')}: on air from the antenna, "
                                            f"{antenna.get('number')} {antenna.get('name')}")
                    self._free = False
                    on_air = (result or {}).get('on_air') or {}
                    # The program's own target, when another source carries it in its place: put
                    # back from there (feed recovery), or the antenna taking over at release.
                    program = item.program_target or (dict(item.target) if antenna and self._roku(item) else None)
                    # A live program without a hold is watched for a failed feed (feed recovery).
                    self._airing = ({'item_id': item.id, 'input_id': on_air['id'], 'program_target': program}
                                    if not end and self._live(item.target) and on_air.get('id') else None)
                    if end:
                        if end.get('game'):
                            item.game = dict(end['game'])
                        self.hold_for((result or {}).get('on_air') or item.target, copy.deepcopy(end))
                        if self.hold is not None:
                            self.hold['item_id'] = item.id
                            if program:
                                self.hold['program_target'] = dict(program)
                    self._save_locked()
                self._condition.notify_all()


class QueueSchedules:
    """Legacy schedule API backed by the same queue; no second execution thread."""
    def __init__(self, queue):
        self.queue = queue

    @staticmethod
    def _job(item):
        fields = {key: getattr(item, key) for key in ScheduledJob.__dataclass_fields__}
        fields['id'] = item.schedule_id
        if fields['status'] == 'skipped':
            fields['status'] = 'cancelled'
        return ScheduledJob(**fields)

    def list(self):
        return [self._job(i) for i in self.queue.list() if i.schedule_id]

    def get(self, job_id):
        return next((j for j in self.list() if j.id == job_id), None)

    def add(self, channel, run_at):
        item = self.queue.add_target({'source_id': 'youtube-tv', 'channel_id': channel}, 'at_time',
                                    run_at=run_at.isoformat(), schedule_id=uuid.uuid4().hex)
        return self._job(item)

    def cancel(self, job_id):
        item = next((i for i in self.queue.list() if i.schedule_id == job_id), None)
        return self._job(self.queue.action(item.id, 'skip')) if item else None

    def close(self):
        pass


class QueuePrograms:
    def __init__(self, sources):
        self.sources = sources

    def snapshot(self, target, program_id):
        data = self.sources.programs(target['source_id'], target.get('date'))
        if data.get('stale') or data.get('error'):
            raise SourceUnavailableError('Fresh listings are unavailable; retry when the guide recovers')
        channel = next((c for c in data.get('channels', []) if str(c['id']) == str(target['channel_id'])), None)
        if not channel:
            raise ConfigError('Channel is no longer listed')
        candidates = [channel.get('now'), channel.get('game'), *channel.get('upcoming', [])]
        program = next((p for p in candidates if p and p['id'] == program_id), None)
        if program is None:
            raise ConfigError('Program is no longer listed; review the queue entry')
        return {k: program.get(k) for k in ('id', 'title', 'start', 'end', 'state')}

    def validate(self, item):
        try:
            current = self.snapshot(item.target, item.program['id'])
        except ConfigError as exc:
            return str(exc)
        if current.get('state') not in (None, 'current', 'upcoming', 'live', 'preview'):
            return 'Game is no longer live or upcoming. Skip or review this entry.'
        if any(current.get(k) != item.program.get(k) for k in ('start', 'end', 'title')):
            return 'Program listing changed. Skip or explicitly Tune channel anyway.'
        return None
