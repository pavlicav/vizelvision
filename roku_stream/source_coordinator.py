"""Serialize master actions with every application-controlled Roku navigation."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import copy
import json
import logging
import os
import threading
import time
import uuid

from .errors import ConfigError, ControlBusyError, CueCancelledError
from .sports import LEAGUES
from .master import MasterStreamError
from .master_worker import MasterClient
from .roku_input import ROKU_SOURCE_IDS, roku_target
from .scheduler import parse_time, utc_now
from .tv_control import target_from
from .ident import IDENT_HOLD_AT, IDENT_SECONDS, IDENT_SOURCE_ID, IDENT_TAIL_SECONDS, is_sports_ident
from .library import LIBRARY_SOURCE_ID
from .networks import ANTENNA_SOURCE, youtube_only

TAKES = ('take', 'take-known', 'prepare-take')
# The latest a manual take can be held on air before the schedule takes back.
MAX_HOLD = timedelta(hours=12)
# YouTube TV has never changed channel on the Roku in under 8 s (20 s to over 2 min is usual):
# with less time than this before an entry is due, the antenna goes straight on.
ROKU_FASTEST = 10
# A Roku feed that fails is nearly always a blip in the capture card, not the Roku. TV Thing
# (which owns the Roku since 2026-10-06) puts what it was verified playing back on without
# navigating, after a brief check: the same app, its player playing, and a moving picture.
# Queue actions that reattach a Roku still playing their target instead of navigating.
RESUMES = ('_queue', '_preroll', '_upgrade')


class SourcePrepareError(MasterStreamError):
    """Preparation failed before anything was cut; the queue may retry it."""
    code = 'source_prepare_failed'


class NotReadyInTime(SourcePrepareError):
    """YouTube TV was not ready when its queue entry was due: the antenna takes over."""


def hold_end(value):
    """A manual take's end: {'kind': 'time', 'at': ISO} or
    {'kind': 'game', 'league', 'game_pk', 'game_date'}. None leaves it open-ended.
    {'kind': 'program', 'program_id'} is resolved from listings by SourceCoordinator."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError('until must be an object')
    if value.get('kind') == 'time':
        try:
            at = parse_time(value.get('at'))
        except (ConfigError, AttributeError) as exc:
            raise ConfigError('until.at must be an ISO-8601 time with a timezone') from exc
        now = utc_now()
        if at <= now:
            raise ConfigError('That end time has already passed')
        if at > now + MAX_HOLD:
            raise ConfigError('Choose an end time within 12 hours')
        return {'until': at.isoformat()}
    if value.get('kind') == 'game':
        league, pk, day = value.get('league', 'mlb'), value.get('game_pk'), value.get('game_date')
        if league not in LEAGUES:
            raise ConfigError('until.league must be one of ' + ', '.join(LEAGUES))
        if isinstance(pk, bool) or not isinstance(pk, int):
            raise ConfigError('until.game_pk must be an integer')
        try:
            day = date.fromisoformat(day).isoformat()
        except (TypeError, ValueError) as exc:
            raise ConfigError('until.game_date must use YYYY-MM-DD') from exc
        return {'game': {'league': league, 'game_pk': pk, 'game_date': day}}
    raise ConfigError("until.kind must be 'time' or 'game'")


class SourceCoordinator:
    def __init__(self, config, roku, baseball, *, master=None):
        # roku: TvRoku, the source Roku as TV Thing's Roku lane; None without one.
        self.config, self.roku, self.baseball = config, roku, baseball
        self.master = master or MasterClient(config.master)
        self.enabled = config.master.enabled
        self.roku_enabled = self.enabled and roku is not None
        self.lock = threading.RLock()
        self.state_lock = threading.Lock()
        self.cancel = threading.Event()
        self.stopping = threading.Event()
        self.busy = False
        self.operation = None
        self.thread = None
        self.navigating = False
        self.force = False  # The running operation was asked to navigate again regardless.
        self.queue = None
        self.programs = None  # QueuePrograms; a take can end with its listed program.
        self.sports = None  # SportsCatalog; resolves NFL games for Roku providers.
        self.library = None  # MediaLibrary; validates library file targets.
        self.networks = None  # Networks; the antenna's station for a network YouTube TV is late with.
        # A queue entry's YouTube TV navigation is stopped at this wall time (None: no limit).
        self.deadline = None
        self.late = threading.Event()

    def status(self):
        state = self.master.request()
        with self.state_lock:
            if self.operation:
                state['operation'] = copy.deepcopy(self.operation)
                if self.operation.get('error'):
                    state['error'] = self.operation['error']
            if self.busy:
                state['can_prepare'] = state['can_take'] = False
            state['roku_enabled'] = self.roku_enabled and state.get('roku_enabled', False)
        known = self.roku.snapshot() if self.roku_enabled else None
        state['roku_last_prepared'] = known
        prepared = state.get('prepared') or {}
        if prepared.get('source_id') in ROKU_SOURCE_IDS and not self._still_selected(prepared, known):
            state['can_take'] = False
        return state

    @staticmethod
    def _same_target(left, right):
        return all(left.get(key) == right.get(key) for key in ('source_id', 'channel_id', 'date'))

    @staticmethod
    def _still_selected(target, known):
        """Whether the Roku still shows target, as prepared (same generation), verified recently.
        A lapsed verification is renewed by TV Thing's still-playing check before a take."""
        return bool(known and known.get('reusable')
                    and SourceCoordinator._same_target(known.get('target') or {}, target)
                    and (not target.get('generation') or known.get('selection_id') == target.get('generation')))

    def roku_ready(self, target):
        """Whether the Roku holds a fresh verified preparation of target, which a take reuses."""
        return self.roku_enabled and self.roku.ready(target)

    def stop_preroll(self, item_id):
        """Stop an early preparation still running for queue entry item_id, because something
        else is due: the navigation stops and the half-prepared input is dropped. Nothing on
        air changes, and the queue is not paused."""
        with self.state_lock:
            operation = self.operation or {}
            if self.busy and operation.get('action') == '_preroll' and operation.get('queue_item_id') == item_id:
                self.cancel.set()

    def _stop_reason(self):
        """Why a Roku navigation must stop now ('cancelled', 'late'), or None. A queue entry's
        YouTube TV navigation is stopped at self.deadline (see _racing)."""
        if self.cancel.is_set() or self.stopping.is_set():
            return 'cancelled'
        if self.deadline is not None and time.time() >= self.deadline:
            self.late.set()
            return 'late'
        return None

    def _check_cancel(self):
        if self.cancel.is_set() or self.stopping.is_set():
            raise CueCancelledError('Master preparation cancelled')

    def _worker(self, action, body=None, *, cancellable=True, queue_item=None):
        if queue_item and self.queue:
            # The short IPC submission and Pause are ordered by the same mutex.
            # A cut already submitted when Pause returns is allowed to complete.
            with self.queue.take_guard(queue_item.id):
                operation = self.master.request(action, body or {})
        else:
            operation = self.master.request(action, body or {})
        deadline = time.monotonic() + 65
        cancelled = False
        while time.monotonic() < deadline:
            if cancellable and (self.cancel.is_set() or self.stopping.is_set()) and not cancelled:
                self.master.request('cancel', {})
                cancelled = True
            state = self.master.request()
            if state.get('state') in ('unavailable', 'not_configured', 'stopped'):
                raise MasterStreamError('Master worker is unavailable')
            current = state.get('operation') or {}
            if current.get('id') != operation.get('id'):
                raise MasterStreamError('Master operation changed; refresh before retrying')
            if current.get('state') != 'pending':
                if cancelled:
                    raise CueCancelledError('Master preparation cancelled')
                if current.get('state') != 'succeeded':
                    error_type = ControlBusyError if current.get('error_code') == ControlBusyError.code else MasterStreamError
                    raise error_type(current.get('error') or 'Master operation failed')
                return state
            time.sleep(.05)
        raise MasterStreamError('Timed out waiting for the master worker')

    def normalize_target(self, body, *, resolve_game=True):
        game = None
        if body.get('source_id') == LIBRARY_SOURCE_ID:
            if self.library is None or not self.library.config.enabled:
                raise ConfigError('The media library is not configured')
            return self.library.target(body), None
        if body.get('source_id') in ROKU_SOURCE_IDS:
            if not self.roku_enabled:
                raise ConfigError('Shared Roku capture is not configured')
            if not isinstance(body.get('antenna', True), bool):
                raise ConfigError('antenna must be true or false')
            youtube_only = body.get('antenna') is False and body['source_id'] in ('youtube-tv', 'mlb')
            body = roku_target(body)
            if youtube_only:
                body['antenna'] = False  # The operator chose YouTube TV alone (see networks.py).
            if body['source_id'] == 'youtube-tv':
                _, channel = self.config.resolve_channel(body['channel_id'])
                body['channel_id'] = channel.name
            elif body['source_id'] in ('sunday-ticket', 'thursday-night-football'):
                body.setdefault('date', date.today().isoformat())
                if resolve_game:
                    if self.sports is None:
                        raise ConfigError('Sports schedules are not configured')
                    game = self.sports.game('nfl', int(body['channel_id']), body['date'])
                    if body['source_id'] == 'thursday-night-football':
                        from .prime_video import prime_nfl_game
                        if not prime_nfl_game(game):
                            raise ConfigError('This NFL game is not listed on Prime Video')
            else:
                body.setdefault('date', date.today().isoformat())
                if resolve_game:
                    game = self.baseball.game(int(body['channel_id']), body['date'])
                    source = game.get('preferred_source') or {}
                    if source.get('provider') not in ('youtube_tv', 'mlb'):
                        raise ConfigError('No controllable source is listed for this game')
        else:
            body = target_from(body)
        return body, game

    def request(self, action='status', body=None, *, queue_item=None, completion=None):
        if action == 'status':
            return self.status()
        body = body or {}
        if not self.enabled:
            return self.master.request(action, body)
        if (action not in ('prepare', 'prepare-take', 'take', 'take-known', 'fallback', 'cancel', '_queue', '_preroll', '_upgrade')
                or (action in ('_queue', '_preroll', '_upgrade') and queue_item is None)):
            raise ConfigError('Unknown master command')
        game = None
        force = body.get('force', False)
        if not isinstance(force, bool):
            raise ConfigError('force must be true or false')
        end = None
        if action in TAKES:
            until = body.get('until')
            body = {k: v for k, v in body.items() if k != 'until'}
            if isinstance(until, dict) and until.get('kind') == 'program':
                target = self.master.request().get('prepared') if action == 'take' else body
                end = self._program_end(until.get('program_id'), target)
            else:
                end = hold_end(until)
        if action in ('prepare', 'prepare-take', '_queue', '_preroll', '_upgrade', 'take-known'):
            # Resolve remote game metadata in the operation thread, after
            # admission, so acceptance and cancellation do not wait on MLB.
            body, game = self.normalize_target(body, resolve_game=False)
        if action == 'take-known' and body.get('source_id') not in ROKU_SOURCE_IDS:
            raise ConfigError('Take known state requires a Roku channel or game')
        if action == 'take' and (not isinstance(body.get('prepared_id'), str) or not body['prepared_id']):
            raise ConfigError('Take requires the current prepared_id')
        with self.state_lock:
            if self.busy:
                if action in ('cancel', 'fallback'):
                    if self.queue:
                        self.queue.pause('Paused by manual master control', keep_hold=action == 'cancel')
                    self.cancel.set()
                    self.pending_fallback = self.pending_fallback or action == 'fallback'
                    return {'accepted': True, 'state': 'cancelling'}
                raise ControlBusyError('A master operation is already running')
            if not self.lock.acquire(blocking=False):
                raise ControlBusyError('Roku navigation is already running')
            self.lock.release()
            if self.queue:
                if action in ('_queue', '_preroll', '_upgrade'):
                    self.queue.admitted(queue_item.id, preroll=action == '_preroll')
                else:
                    # What is on air keeps its end until a take succeeds or fallback clears it.
                    self.queue.pause('Paused by manual master control', keep_hold=action != 'fallback')
            self.busy = True
            self.pending_fallback = False
            self.cancel.clear()
            self.deadline = None
            self.late.clear()
            self.operation = {'id': uuid.uuid4().hex, 'action': action, 'state': 'pending', 'error': None}
            if action in ('prepare', 'prepare-take', 'take-known'):
                self.operation['target'] = body
            if queue_item:
                self.operation.update(queue_item_id=queue_item.id, target=body)
            accepted = copy.deepcopy(self.operation)
            self.thread = threading.Thread(target=self._run, args=(action, body, game, queue_item, completion, force, end),
                                           name='source-prepare', daemon=True)
            self.thread.start()
            return accepted

    def _hold(self, end):
        """Name the game a take is held for, so Up next can show it."""
        if not end or 'game' not in end:
            return end
        game = dict(end['game'])
        try:
            found = (self.sports.game(game['league'], game['game_pk'], game['game_date']) if self.sports
                     else self.baseball.game(game['game_pk'], game['game_date']))
            game['title'] = str(found.get('title') or '')
        except Exception:
            pass  # The end-of-game check reports lookup problems while it waits.
        game['title'] = game.get('title') or f"{game['league'].upper()} game {game['game_pk']}"
        return {'game': game}

    def _program_end(self, program_id, target):
        """End a take with its program's listed end, read from the catalog, not the browser."""
        if self.programs is None or not isinstance(program_id, str) or not target:
            raise ConfigError('This source has no program listing to end with')
        program = self.programs.snapshot(target, program_id)
        if not program.get('end'):
            raise ConfigError('This program has no scheduled end')
        end = hold_end({'kind': 'time', 'at': datetime.fromtimestamp(program['end'], timezone.utc).isoformat()})
        end['program'] = {'id': program['id'], 'title': program['title']}
        return end

    def queue_end(self, until, target):
        """How long target holds master once taken, from a "plays until" choice
        ({'kind': 'time' | 'program' | 'game', ...}; None is open-ended), named for Up next."""
        end = (self._program_end(until.get('program_id'), target)
               if isinstance(until, dict) and until.get('kind') == 'program' else hold_end(until))
        return self._hold(end)

    def set_hold(self, until):
        """Change when what is on air ends and the schedule takes back master."""
        if self.queue is None:
            raise ConfigError('The master queue is not configured')
        on_air = self.master.request().get('on_air')
        if not on_air:
            raise ConfigError('Nothing is on air')
        end = self.queue_end(until, on_air)
        if end is None:
            raise ConfigError('Choose when this should end')
        return self.queue.hold_for(on_air, end)

    def _handoff(self, target, prepared):
        """Give the worker the Roku lane to decode and take: the generation TV Thing verified.
        The lock stays the web app's (tv_roku.RokuHold), renewed while the Roku is in use."""
        return self._worker('prepare', {**target, 'roku': prepared})

    def roku_in_use(self):
        """Whether master wants the Roku: an operation running, or a Roku input prepared or on air."""
        with self.state_lock:
            if self.busy:
                return True
        try:
            state = self.master.request()
        except Exception:
            return True  # Unknown: keep the lock rather than drop a feed on air.
        return any((state.get(name) or {}).get('source_id') in ROKU_SOURCE_IDS for name in ('on_air', 'prepared'))

    def _prepare_roku(self, target, game, *, keep_air=False):
        """Put target on the Roku through TV Thing (it navigates unless it already shows target,
        recently verified), then hand the lane to the worker."""
        # The worker and the verified selection name a channel, not the operator's source choice.
        target = {k: v for k, v in target.items() if k != 'antenna'}
        # Early preparation keeps a non-Roku program on air and only drops a stale prepared
        # input; otherwise a Roku feed on air goes to fallback before the Roku moves.
        self._worker('cancel' if keep_air else 'fallback')
        self._check_cancel()
        with self.state_lock:
            self.navigating = True
        try:
            prepared = self.roku.prepare(target, force=self.force, resume=False, stop=self._stop_reason)
        finally:
            with self.state_lock:
                self.navigating = False
        self._check_cancel()
        return self._handoff(target, prepared)

    def _reuse_roku(self, target):
        """The Roku already shows target, verified recently: what the worker has of it, or the
        lane handed over again. Sends the Roku no key."""
        if not self.roku.ready(target):
            return None
        state, known = self.master.request(), self.roku.snapshot() or {}
        with self.state_lock:
            self.operation['reused'] = True
        for name in ('prepared', 'on_air'):
            current = state.get(name) or {}
            if (self._same_target(current, target) and current.get('generation') == known.get('selection_id')
                    and (state.get('can_take') if name == 'prepared' else state.get('publisher_ready'))):
                return state
        # Reattach decoded media from the same verified selection.
        plain = {k: v for k, v in target.items() if k != 'antenna'}
        try:
            prepared = self.roku.prepare(plain, navigate=False, resume=False, stop=self._stop_reason)
        except MasterStreamError:
            return None  # It changed meanwhile: prepare it normally.
        return self._handoff(plain, prepared)

    def roku_playing(self, target):
        """Feed recovery: whether the Roku still plays target as it was verified, briefly
        checked. Its feed then goes back on in seconds (_resume_roku), sooner than the antenna
        and in the better picture. Never navigates."""
        return self.roku_enabled and self.roku.playing({k: v for k, v in target.items() if k != 'antenna'})

    def _resume_roku(self, target):
        """The Roku still plays target, though its verification lapsed or the capture
        restarted. A feed that failed is nearly always a blip in the capture card, not the
        Roku: TV Thing checks it briefly and renews the verification without navigating.
        None when the Roku navigated since or fails the check: it navigates."""
        plain = {k: v for k, v in target.items() if k != 'antenna'}
        try:
            prepared = self.roku.prepare(plain, navigate=False, resume=True, stop=self._stop_reason)
        except MasterStreamError:
            return None
        logging.getLogger(__name__).warning(
            'The Roku still plays %s; its feed goes back on without navigating', json.dumps(plain))
        return self._handoff(plain, prepared)

    # The antenna: a network YouTube TV is not ready with in time ---------------------------
    def _antenna(self, target, game):
        """The antenna station carrying target's network ({source_id, channel_id, number,
        name}), or None: not a network, YouTube TV only, or TV-Thing has no such station."""
        if self.networks is None:
            return None
        try:
            return self.networks.antenna(target, game)
        except Exception as exc:  # The listing is a convenience: YouTube TV waits as before.
            logging.getLogger(__name__).warning('Could not look up the antenna station: %s', exc)
            return None

    def _ident_media(self):
        """(position, duration) of the station ID on air, None when no ID is on air; either
        can be None while the worker has not said."""
        on_air = self.master.request().get('on_air') or {}
        if on_air.get('source_id') != IDENT_SOURCE_ID:
            return None
        media = on_air.get('media') or {}
        return media.get('position_seconds'), media.get('duration_seconds')

    def _ident_left(self):
        """Seconds until the station ID on air no longer covers a source being prepared; None
        when no ID is on air, 0 when it holds its end card. That is its tail, where a take
        lands, or for a sports break its first end card: the Sports ID after it only plays
        once the game is ready, so a source ready later holds the break there."""
        media = self._ident_media()
        if media is None:
            return None
        position, duration = media
        if position is None or not duration:
            return 0
        if duration > IDENT_SECONDS + 1 and position < IDENT_HOLD_AT:
            return IDENT_HOLD_AT - position
        return max(0., duration - position - IDENT_TAIL_SECONDS)

    def _ident_can_hold(self):
        """Whether the station ID on air can still hold its end card for a source being
        prepared: a sports break holds only in its first half, never in the Sports ID."""
        media = self._ident_media()
        return media is not None and (media[0] is None or media[0] < IDENT_SECONDS)

    def _ready_by(self, action, queue_item):
        """When a queue entry's source must be ready (wall time; None: no limit). An early
        preparation has until the entry's release time; a release has until the station ID
        covering the change reaches its tail, or no time at all."""
        if action == '_preroll':
            run_at = getattr(queue_item, 'run_at', None)
            return parse_time(run_at).timestamp() if run_at else None
        return time.time() + (self._ident_left() or 0)

    @contextmanager
    def _racing(self, deadline):
        """YouTube TV's navigation is stopped at deadline (wall time; None: no limit), and
        whatever that stop raises becomes NotReadyInTime."""
        with self.state_lock:
            self.deadline = deadline
            self.late.clear()
        try:
            yield
        except Exception as exc:
            if (isinstance(exc, NotReadyInTime) or not self.late.is_set()
                    or self.cancel.is_set() or self.stopping.is_set()):
                raise
            at = datetime.fromtimestamp(deadline).strftime('%-H:%M:%S')
            raise NotReadyInTime(f'YouTube TV was not ready by {at}') from exc
        finally:
            with self.state_lock:
                self.deadline = None
                self.late.clear()

    def _prepare_antenna(self, station, why):
        """Prepare the antenna's station in YouTube TV's place: (master state, target), or
        (None, None) when the antenna cannot (its tuner is busy on another channel)."""
        log = logging.getLogger(__name__)
        log.warning('%s: the antenna takes over (%s %s)', why, station['number'], station['name'])
        try:
            target = target_from({'source_id': station['source_id'], 'channel_id': station['channel_id']})
            return self._worker('prepare', target), target
        except CueCancelledError:
            raise
        except Exception as exc:
            log.warning('The antenna could not take over (%s); waiting for YouTube TV', exc)
            return None, None

    def _prepare_live(self, action, body, game, queue_item):
        """Prepare a Roku target by navigating. A queue entry on a network the antenna also
        carries plays from YouTube TV when it is ready in time, else from the antenna.
        Returns (master state, the target prepared, the antenna station with the reason it
        took over, or None)."""
        keep_air = action == '_preroll' or self._station_id_on_air()
        station = (self._antenna(body, game)
                   if queue_item is not None and action in ('_queue', '_preroll') else None)
        deadline = self._ready_by(action, queue_item) if station else None
        if deadline is not None and deadline - time.time() < ROKU_FASTEST:
            why = 'YouTube TV could not be ready in time'
            if action == '_preroll':
                raise NotReadyInTime(why)
            result, target = self._prepare_antenna(station, why)
            if result is not None:
                return result, target, {**station, 'reason': why}
            deadline = None  # The antenna failed: YouTube TV, however long it takes.
        try:
            with self._racing(deadline):
                return self._prepare_roku(body, game, keep_air=keep_air), body, None
        except CueCancelledError:
            raise
        except Exception as exc:
            # Out of time, or YouTube TV failed outright: at release the antenna takes over. An
            # early preparation fails instead; its release follows and takes the antenna then.
            if action != '_queue' or deadline is None:
                raise
            why = str(exc) if isinstance(exc, NotReadyInTime) else f'YouTube TV failed ({exc})'
            result, target = self._prepare_antenna(station, why)
            if result is None:
                raise
            return result, target, {**station, 'reason': why}

    def alternates(self, target, game=None):
        """The ways a live program can go back on when its feed keeps failing (feed recovery):
        {'antenna': the TV-Thing station carrying it, 'roku': the same program from YouTube TV
        alone}, either None. game is the queue entry's {'league', 'game_pk', 'game_date',
        'title'}: the antenna carries a game its guide names, or a local simulcast."""
        target, log = dict(target or {}), logging.getLogger(__name__)
        if self.networks is None:
            return {}
        source = target.get('source_id')
        try:
            if source == ANTENNA_SOURCE:
                network = self.networks.network_of(target.get('channel_id'))
                return {'antenna': target,
                        'roku': {'source_id': 'youtube-tv', 'channel_id': network, 'antenna': False} if network else None}
            if source not in ROKU_SOURCE_IDS:
                return {}
            plain = {k: v for k, v in target.items() if k != 'antenna'}
            roku = {**plain, 'antenna': False} if source in ('youtube-tv', 'mlb') else plain
            if youtube_only(target):
                return {'antenna': None, 'roku': roku}
            mlb = None
            if source == 'mlb':
                mlb = self.baseball.game(int(target['channel_id']), target.get('date'))
            station = self.networks.antenna(plain, mlb)
            if station is None and game:
                station = self.networks.carrying(game.get('title'))
            if station is None and game and self.sports is not None:
                station = self.networks.station_for(
                    self.sports.local_simulcast(game.get('league'), game.get('game_pk'), game.get('game_date')))
        except Exception as exc:  # A lookup failing only narrows the choice: the same source goes back on.
            log.warning('Could not look up another source for %s: %s', json.dumps(target), exc)
            return {}
        antenna = {'source_id': station['source_id'], 'channel_id': station['channel_id']} if station else None
        return {'antenna': antenna, 'roku': roku}

    def on_air(self):
        """What master shows, for the queue: None for the test card."""
        return self.master.request().get('on_air')

    def input_failure(self):
        """Master's last input failure, for the queue's feed recovery: {'target': {'id', ...},
        'error', 'at', 'was_on_air', 'recovering'}, or None. 'recovering': master is still
        waiting for that input on the test card (its stall recovery), not done with it."""
        state = self.master.request()
        failure = state.get('last_input_failure')
        if not failure:
            return failure
        recovering = ((state.get('recovery') or {}).get('target') or {}).get('id')
        return {**failure, 'recovering': bool(recovering) and recovering == (failure.get('target') or {}).get('id')}

    def game_on(self, item):
        """The game a queue entry just taken carries, live or starting within the hour:
        the game itself for MLB or Sunday Ticket, else a national game on its channel."""
        target = item.target or {}
        if self.sports is None or target.get('source_id') in (LIBRARY_SOURCE_ID, IDENT_SOURCE_ID, 'off-air'):
            return None
        name = None
        if str(target.get('source_id')).startswith('tv-thing-') and self.programs is not None:
            try:  # An over-the-air station matches a network by its name (WTTG-HD is FOX).
                listing = self.programs.sources.programs(target['source_id'])
                name = next((c.get('name') for c in listing.get('channels', [])
                             if str(c.get('id')) == str(target.get('channel_id'))), None)
            except Exception:
                pass
        games, _ = self.sports.games_on(target, channel_name=name)
        return {k: games[0][k] for k in ('league', 'game_pk', 'game_date', 'title')} if games else None

    def media_gate(self, item):
        """Release condition 'after_current': open once no library file is on air.
        A file cued for this entry may already have been cut in by the worker."""
        state = self.master.request()
        on_air = state.get('on_air') or {}
        if item.prepared_input_id and on_air.get('id') == item.prepared_input_id:
            return {'finished': True, 'status': 'Started when the previous file ended'}
        prepared = state.get('prepared') or {}
        armed = bool(item.prepared_input_id and prepared.get('id') == item.prepared_input_id
                     and prepared.get('after_input_id') == on_air.get('id'))
        if on_air.get('source_id') == IDENT_SOURCE_ID:
            if armed:
                return {'finished': False, 'status': 'Plays when the station ID ends'}
            return {'finished': True}  # Prepares during the ID; the take waits for its end.
        if on_air.get('source_id') != LIBRARY_SOURCE_ID:
            return {'finished': True}
        media = on_air.get('media') or {}
        position, duration = media.get('position_seconds'), media.get('duration_seconds')
        left = ''
        if position is not None and duration:
            remaining = max(0, int(duration - position))
            left = f' · {remaining // 3600}:{remaining // 60 % 60:02d}:{remaining % 60:02d} left' if remaining >= 3600 \
                else f' · {remaining // 60}:{remaining % 60:02d} left'
        title = self.library.label(on_air.get('channel_id')) if self.library else on_air.get('channel_id')
        return {'finished': False, 'status': f'Plays when {title} ends{left}'}

    def disarm(self):
        """A paused queue must not advance when the on-air file ends."""
        try:
            self.master.request('disarm', {})
        except MasterStreamError:
            pass  # Worker unavailable: nothing is armed there.
        self._hold_ident(False)  # Nothing will follow: the ID irises out.

    def _hold_ident(self, hold):
        """Hold the station ID's end card while the next source is prepared, or let it end."""
        try:
            self.master.request('ident_hold', {'hold': hold})
        except (MasterStreamError, ConfigError):
            pass  # An older worker: the ID ends on its own and fallback covers the rest.

    def station_id(self, target=None):
        """Put the station ID on air now, over the end of what is on air: called 30 s before a
        timed entry releases, or before a manual take's end. Nothing on air, the ID already
        on air, or the next entry being what is on air all mean no ID; but the Sports ID,
        cued because a game is next, plays from the test card too: it opens the game."""
        state = self.master.request()
        on_air, ident = state.get('on_air') or {}, state.get('ident') or {}
        from_test_card = not on_air and is_sports_ident(ident.get('file'))
        reason = ('nothing on air' if not on_air and not from_test_card
                  else 'the ID is already on air' if on_air.get('source_id') == IDENT_SOURCE_ID
                  else f"the ID is not ready ({ident.get('error') or 'not cued'})" if not ident.get('ready')
                  else 'the next entry is already on air' if target and self._same_target(on_air, target) else None)
        if reason:
            logging.getLogger(__name__).info('Station ID skipped: %s', reason)
            return 'skipped'
        self.master.request('ident', {'from_test_card': True} if from_test_card else {})
        # Wait for the cut, so the source it replaced is free: a Roku can start preparing
        # the next program at once, while the ID covers the change.
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and not self._station_id_on_air():
            time.sleep(.05)
        if not self._station_id_on_air():
            logging.getLogger(__name__).warning('Station ID was asked for but did not go on air within a second')
        return 'requested'

    @staticmethod
    def _due_soon(item):
        """A queue entry releasing within a few seconds, whose take follows its preparation."""
        try:
            return bool(item and item.run_at and
                        datetime.fromisoformat(item.run_at) <= datetime.now(timezone.utc) + timedelta(seconds=5))
        except (TypeError, ValueError):
            return False

    def _station_id_on_air(self):
        return (self.master.request().get('on_air') or {}).get('source_id') == IDENT_SOURCE_ID

    def _after_station_id(self, cancellable=True):
        """A queued take lets the station ID finish instead of cutting into it. A held end
        card is released first: the next source is ready, so the ID irises out."""
        if self._station_id_on_air():
            self._hold_ident(False)
        # A sports break is two IDs long: wait for what is left of it, not one ID's length.
        position, duration = self._ident_media() or (None, None)
        left = duration - (position or 0) if duration else IDENT_SECONDS
        deadline = time.monotonic() + max(left, 0) + 5
        while time.monotonic() < deadline:
            if cancellable:
                self._check_cancel()
            elif self.stopping.is_set():
                return
            on_air = self.master.request().get('on_air') or {}
            if on_air.get('source_id') != IDENT_SOURCE_ID:
                return
            media = on_air.get('media') or {}
            position, duration = media.get('position_seconds'), media.get('duration_seconds')
            if position is not None and duration and duration - position <= IDENT_TAIL_SECONDS:
                return
            time.sleep(.05)

    def _reuse_library(self, queue_item):
        """The file this entry cued early: already on air, or still ready to take."""
        cued = queue_item.prepared_input_id if queue_item else None
        if not cued:
            return None
        state = self.master.request()
        if (state.get('on_air') or {}).get('id') == cued and state.get('publisher_ready'):
            with self.state_lock:
                self.operation['reused'] = True
            return state
        if (state.get('prepared') or {}).get('id') == cued and state.get('can_take'):
            return state
        return None

    def execute_queue(self, item):
        if (item.target or {}).get('source_id') == 'off-air':
            return self._queue_off_air(item)
        return self._queue_request('_queue', item)

    def preroll_queue(self, item):
        """Prepare a waiting Roku entry without taking it. The later take reuses this
        verified selection instead of navigating again. One Roku cannot prepare a new
        channel while it is on air, so that case waits for release time."""
        source = (item.target or {}).get('source_id')
        if source == LIBRARY_SOURCE_ID:
            # Files are independent of whatever is on air; cueing never interrupts it.
            state = self._queue_request('_preroll', item)
            prepared = state.get('prepared') or {}
            return {'outcome': 'prepared', 'input_id': prepared.get('id'), 'after_input_id': prepared.get('after_input_id')}
        if source not in ROKU_SOURCE_IDS:
            raise ConfigError('Only Roku and library sources prepare early')
        if ((self.master.request().get('on_air') or {}).get('source_id')) in ROKU_SOURCE_IDS:
            return 'skipped'
        self._queue_request('_preroll', item)
        return 'prepared'

    def upgrade_queue(self, item):
        """Back to YouTube TV: cut to item's target, already prepared on the Roku beside the
        antenna on air (preroll_queue), with no navigation and no change to the queue's hold.
        Raises when it is not prepared any more; what is on air then stays."""
        return self._queue_request('_upgrade', item)

    def _queue_request(self, action, item):
        done, outcome = threading.Event(), {}
        self.request(action, item.target, queue_item=item, completion=(done, outcome))
        done.wait()
        if outcome.get('error'):
            error_type = {ControlBusyError.code: ControlBusyError,
                          SourcePrepareError.code: SourcePrepareError}.get(outcome.get('error_code'), MasterStreamError)
            raise error_type(outcome['error'])
        return outcome['result']

    def _queue_off_air(self, item):
        """A scheduled OFF AIR entry: return master to its test card."""
        with self.state_lock:
            if self.busy:
                raise ControlBusyError('A master operation is already running')
            if not self.lock.acquire(blocking=False):
                raise ControlBusyError('Roku navigation is already running')
        try:
            self.queue.admitted(item.id)
            self._after_station_id(cancellable=False)  # Signing off: the ID ends before the test card.
            state = self._worker('fallback', cancellable=False, queue_item=item)
            if state.get('on_air'):
                raise MasterStreamError('Fallback could not be confirmed')
            return state
        finally:
            self.lock.release()

    def _run(self, action, body, game, queue_item=None, completion=None, force=False, end=None):
        error = None
        error_code = None
        result = None
        antenna = None  # The antenna station that took over from YouTube TV, if it did.
        handoff = False  # An early preparation ran out of time: the antenna follows at once.
        preparing = action in ('_queue', '_preroll')
        # The station ID on air holds its end card until this source is ready, instead of
        # ending on the test card while a Roku or tuner changes channel.
        holding = action in ('_queue', '_preroll', 'prepare-take', 'take-known') and self._ident_can_hold()
        self.force = force
        if holding:
            self._hold_ident(True)
        with self.lock:
            try:
                library = body.get('source_id') == LIBRARY_SOURCE_ID
                if action == '_preroll' and body.get('source_id') not in ROKU_SOURCE_IDS and not library:
                    raise ConfigError('Only Roku and library sources prepare early')
                if action in ('prepare', 'prepare-take', '_queue', '_preroll', '_upgrade', 'take-known') \
                        and body.get('source_id') in ROKU_SOURCE_IDS:
                    result = None if force else self._reuse_roku(body)
                    if result is None and not force and action in RESUMES:
                        result = self._resume_roku(body)
                    if result is None:
                        if action == 'take-known':
                            raise MasterStreamError('No recent matching Roku preparation; prepare the selected channel or game first')
                        if action == '_upgrade':  # Never navigates: that would take the antenna off air.
                            raise MasterStreamError('YouTube TV is no longer prepared')
                        body, game = self.normalize_target(body)
                        self._check_cancel()
                        # The station ID on air is no Roku feed: keep it on air while navigating.
                        result, body, antenna = self._prepare_live(action, body, game, queue_item)
                elif library and action == '_preroll':
                    on_air = self.master.request().get('on_air') or {}
                    after = on_air.get('id') if (queue_item.release_type == 'after_current' and on_air.get('source_id')
                                                 in (LIBRARY_SOURCE_ID, IDENT_SOURCE_ID)) else None
                    result = self._worker('prepare', {**body, 'after_input_id': after})
                elif library and action == '_queue' and (reused := self._reuse_library(queue_item)):
                    result = reused
                else:
                    if action == 'take':
                        prepared = (self.master.request().get('prepared') or {})
                        if prepared.get('source_id') in ROKU_SOURCE_IDS \
                                and not self._still_selected(prepared, self.roku.snapshot()):
                            raise MasterStreamError('Roku preparation expired or changed; prepare again')
                    result = self._worker('prepare' if action in ('_queue', 'prepare-take') else action, body)
                preparing = False
                # The worker's prepare returns only once audio and video are
                # verified, so "prepare and take" takes as soon as it is ready.
                if action in ('_queue', '_upgrade', 'prepare-take', 'take-known'):
                    self._check_cancel()
                    if queue_item and self.queue and action == '_queue':
                        self.queue.check_before_take(queue_item.id)
                    if body.get('source_id') in ROKU_SOURCE_IDS \
                            and not self._still_selected(result.get('prepared') or result.get('on_air') or body,
                                                         self.roku.snapshot()):
                        raise MasterStreamError('Roku preparation expired or changed before take')
                    prepared = result.get('prepared') or {}
                    already_live = (self._same_target(result.get('on_air') or {}, body)
                                    and result.get('publisher_ready') and self.operation.get('reused'))
                    if not already_live:
                        if not result.get('can_take') or not prepared.get('id'):
                            raise MasterStreamError('Source is no longer ready')
                        if queue_item and action == '_queue':
                            self._after_station_id()
                        # A queued take (or the way back to YouTube TV) is ordered with Pause by
                        # the queue's take guard.
                        result = self._worker('take', {'prepared_id': prepared['id']}, queue_item=queue_item)
                        if (result.get('on_air') or {}).get('id') != prepared['id']:
                            raise MasterStreamError('Take could not be confirmed')
                if action in TAKES and self.queue:
                    self.queue.hold_for(result.get('on_air'), self._hold(end))
                if antenna:
                    result = {**result, 'antenna': antenna}
            except Exception as exc:
                error = str(exc)
                error_code = getattr(exc, 'code', None)
                handoff = isinstance(exc, NotReadyInTime) and action == '_preroll'
                if (preparing and not self.cancel.is_set() and not self.stopping.is_set()
                        and not isinstance(exc, (ControlBusyError, CueCancelledError))):
                    error_code = SourcePrepareError.code  # Nothing was cut; safe to retry.
                if action in ('prepare', 'prepare-take', '_queue', '_preroll'):
                    try:
                        self.master.request('cancel', {})
                    except Exception:
                        pass  # The worker releases what it held; no replay or automatic take.
            finally:
                if holding and not (action == '_preroll' and (not error or handoff) and self._due_soon(queue_item)):
                    self._hold_ident(False)  # Its take follows at once and releases the hold.
                # Drain a fallback request accepted during cleanup before releasing admission.
                cancel_handled = False
                while True:
                    with self.state_lock:
                        fallback = self.pending_fallback
                        self.pending_fallback = False
                        cancel_cleanup = self.cancel.is_set() and not cancel_handled
                        if not fallback and not cancel_cleanup:
                            self.operation.update(state='failed' if error else 'succeeded', error=error)
                            self.busy = False
                            if completion:
                                completion[1].update(result=result, error=error, error_code=error_code)
                                completion[0].set()
                            break
                    try:
                        cancel_handled = True
                        if fallback:
                            self._worker('fallback', cancellable=False)
                        elif cancel_cleanup:
                            self._worker('cancel', cancellable=False)
                            error = error or 'Master preparation cancelled'
                    except Exception as exc:
                        error = str(exc)

    def close(self):
        # A navigation in progress sees stopping and is stopped on TV Thing.
        self.cancel.set()
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=25)
