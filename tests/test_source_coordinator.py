"""Master control and the source Roku, which is TV Thing's Roku lane since 2026-10-06.

FakeTvRoku simulates TV Thing's side: its selection and generation, the reuse window,
the still-playing check, its lock, and its controller (``controller``, a Mock whose
play* methods are the navigation; a navigation runs while the coordinator polls, and
is stopped with cancel_operation, as TV Thing stops it).
"""
import contextlib
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.errors import ConfigError, ControlBusyError, CueCancelledError
from roku_stream.master import MasterStreamError
from roku_stream.source_coordinator import SourceCoordinator
from roku_stream.tv_control import ROKU_OWNER, RokuLease
from roku_stream.tv_roku import RokuHold, TvRoku


TARGET = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}
VERIFIED = {'ok': True, 'operation_id': 'cue', 'verification': {
    'player_state': 'play', 'visible_channel_template': {'matched': True},
    'playback_evidence': 'roku_player_play_after_verified_selection'}}


class FakeMaster:
    def __init__(self):
        self.calls = []
        self.state = {'state': 'fallback', 'publisher_ready': True, 'roku_enabled': True,
                      'can_prepare': True, 'can_take': False, 'on_air': None, 'prepared': None}
        self.hook = lambda action, body: None

    def request(self, action='status', body=None):
        if action == 'status':
            return copy.deepcopy(self.state)
        body = body or {}
        self.calls.append((action, body))
        self.hook(action, body)
        operation = {'id': str(len(self.calls)), 'state': 'succeeded', 'action': action}
        self.state['operation'] = operation
        if action == 'fallback':
            self.state.update(state='fallback', on_air=None, prepared=None, can_take=False)
        if action == 'cancel':
            self.state.update(prepared=None, can_take=False)
        if action == 'prepare':
            # The worker keeps the target and the generation it verified, not the handoff.
            target = {k: v for k, v in body.items() if k not in ('roku', 'selection_id')}
            generation = (body.get('roku') or {}).get('generation') or body.get('selection_id')
            self.state.update(prepared={'id': 'prepared', **target, 'generation': generation}, can_take=True)
        if action == 'take':
            if body.get('prepared_id') != (self.state['prepared'] or {}).get('id'):
                raise MasterStreamError('Prepared input changed')
            self.state.update(state='live', on_air=self.state['prepared'], prepared=None, can_take=False)
        return operation


class FakeTvRoku:
    """TV Thing's Roku lane and its controller, as master control sees them through TvRoku."""

    def __init__(self, controller):
        self.controller = controller
        self.selection = None
        self.verified_at = None
        self.verified_capture = None
        self.capture = 'cap-1'
        self.serial = 0
        self.max_age = 900
        self.still_plays = True
        self.checks = 0
        self.locked_by = None
        self.navigations = []
        self.hold = SimpleNamespace(in_use=lambda: False, release=Mock(), token='token')

    def generation(self):
        return f'{self.capture}.{self.serial}'

    @contextlib.contextmanager
    def navigating(self):
        """Something moves the Roku (a navigation, a person at the remote)."""
        self.selection = None
        self.serial += 1
        yield

    def lapse(self, seconds=901):
        """The verification is old, as for any game by its second quarter."""
        self.verified_at -= seconds

    def _same(self, target):
        return bool(self.selection) and all(self.selection.get(k) == target.get(k)
                                            for k in ('source_id', 'channel_id', 'date'))

    def _reusable(self):
        return bool(self.selection and self.verified_capture == self.capture
                    and time.time() - self.verified_at <= self.max_age)

    def ready(self, target):
        return self._same(target) and self._reusable()

    def _check(self):
        self.checks += 1
        if self.still_plays:
            self.verified_at, self.verified_capture = time.time(), self.capture
        return self.still_plays

    def playing(self, target):
        return self._same(target) and self._check()

    def snapshot(self):
        if not self.selection:
            return None
        return {'target': dict(self.selection), 'prepared_at': self.verified_at, 'selection_id': self.generation(),
                'resolved_source': {'provider': 'youtube_tv', 'label': self.selection['channel_id']},
                'age_seconds': round(time.time() - self.verified_at, 1), 'max_age_seconds': self.max_age,
                'reusable': self._reusable(), 'reason': None if self._reusable() else 'old'}

    def lane(self):
        return {'selection': self.selection, 'stream': {'generation': self.generation()}}, None

    def _handoff(self):
        return {'generation': self.generation(), 'resolved_source': {'provider': 'youtube_tv'}}

    def prepare(self, target, *, force=False, navigate=True, resume=True, stop=lambda: None):
        if self.locked_by:
            raise ControlBusyError(f'The Roku is locked by {self.locked_by} in TV-Thing')
        if not force and self._same(target) and self._reusable():
            return self._handoff()
        if not force and resume and self._same(target) and self._check():
            return self._handoff()
        if not navigate:
            raise MasterStreamError('No recent matching Roku preparation; prepare it first')
        source = target['source_id']
        call = {'sunday-ticket': lambda: self.controller.play_sunday_ticket(target),
                'thursday-night-football': lambda: self.controller.play_prime_game(target),
                'mlb': lambda: self.controller.play_baseball_game(target)}.get(
            source, lambda: self.controller.play(target['channel_id']))
        outcome = {}

        def run():
            try:
                with self.navigating():
                    outcome['result'] = call()
            except BaseException as exc:
                outcome['error'] = exc
        self.navigations.append(dict(target))
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        stopped = None
        while thread.is_alive():
            reason = stop()
            if reason and not stopped:
                stopped = reason
                self.controller.cancel_operation()
            thread.join(.01)
        if stopped or isinstance(outcome.get('error'), CueCancelledError):
            raise CueCancelledError(f'Roku navigation stopped ({stopped or "cancelled"})')
        if 'error' in outcome:
            raise MasterStreamError(f"The Roku could not find it: {outcome['error']}")
        verification = (outcome.get('result') or {}).get('verification') or {}
        selected = verification.get('selected_prime_event') if source == 'thursday-night-football' \
            else verification.get('visible_channel_template') or verification.get('selected_game_card')
        if (verification.get('player_state') != 'play' or not isinstance(selected, dict)
                or selected.get('matched') is not True or not verification.get('playback_evidence')):
            raise MasterStreamError('The Roku could not find it: Roku selection lacks visual verification')
        self.selection = {k: target[k] for k in ('source_id', 'channel_id', 'date') if k in target}
        self.verified_at, self.verified_capture = time.time(), self.capture
        self.serial += 1
        return self._handoff()


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = SimpleNamespace(
            master=MasterConfig(enabled=True, socket_path=Path(self.directory.name) / 'master.sock'),
            tv_thing=TvThingConfig(enabled=True),
            resolve_channel=lambda name: (0, SimpleNamespace(name=name if name in ('NBC', 'FOX') else 'NBC')))
        self.master = FakeMaster()
        self.controller = Mock()
        self.roku = FakeTvRoku(self.controller)
        self.baseball = Mock()
        self.coordinator = SourceCoordinator(self.config, self.roku, self.baseball, master=self.master)
        self.addCleanup(self.coordinator.close)
        self.result = copy.deepcopy(VERIFIED)

        def play(*_):
            self.assertIsNone(self.master.state['on_air'], 'a Roku feed goes to fallback before the Roku moves')
            return self.result
        for method in ('play', 'play_baseball_game', 'play_sunday_ticket', 'play_prime_game'):
            getattr(self.controller, method).side_effect = play

    def finish(self):
        self.coordinator.thread.join(timeout=3)
        self.assertFalse(self.coordinator.thread.is_alive())
        return self.coordinator.status()

    def prepare(self):
        self.coordinator.request('prepare', TARGET)
        return self.finish()

    def roku_handoff(self, action='prepare'):
        return next(body['roku'] for name, body in self.master.calls if name == action and 'roku' in body)

    def test_prime_game_prepares_its_exact_target(self):
        from tests.test_prime_video import GAME
        target = {'source_id': 'thursday-night-football', 'channel_id': str(GAME['game_id']), 'date': '2026-10-01'}
        self.coordinator.sports = Mock()
        self.coordinator.sports.game.return_value = GAME
        self.result['verification'] = {'player_state': 'play', 'selected_prime_event': {'matched': True},
                                       'playback_evidence': 'two_live_matchup_overlays_with_prime_video_playback'}
        self.coordinator.request('prepare', target)
        self.assertEqual(self.finish()['operation']['state'], 'succeeded')
        self.controller.play_prime_game.assert_called_once_with(target)
        self.controller.play_baseball_game.assert_not_called()
        self.assertEqual(self.roku.selection, target)
        self.coordinator.sports.game.return_value = {**GAME, 'broadcasts': [{'name': 'NBC'}]}
        self.coordinator.request('prepare', {**target, 'force': True})
        self.assertIn('not listed on Prime Video', self.finish()['operation']['error'])

    def test_navigation_is_followed_by_media_preparation_of_that_generation_then_explicit_take(self):
        self.master.state.update(state='live', on_air={'source_id': 'tv-thing-digital'})
        state = self.prepare()
        self.assertEqual(state['operation']['state'], 'succeeded')
        self.assertIsNone(state['on_air'])
        self.assertEqual([a for a, _ in self.master.calls], ['fallback', 'prepare'])
        self.assertEqual(self.roku_handoff()['generation'], self.roku.generation())
        self.assertEqual(state['prepared']['generation'], self.roku.generation())
        self.assertNotIn('roku', state['prepared'])
        self.coordinator.request('take', {'prepared_id': state['prepared']['id']})
        self.assertEqual(self.finish()['on_air']['source_id'], 'youtube-tv')

    def test_failed_or_unverified_selection_never_prepares_media(self):
        for verification in ({}, {'player_state': 'play', 'visible_channel_template': {'matched': False},
                                  'playback_evidence': 'test'}):
            self.result['verification'] = verification
            self.master.calls.clear()
            state = self.prepare()
            self.assertEqual(state['operation']['state'], 'failed')
            self.assertNotIn('prepare', [a for a, _ in self.master.calls])
            self.assertIsNone(self.roku.selection)

    def test_a_roku_that_changed_since_preparation_is_never_taken(self):
        state = self.prepare()
        self.roku.capture = 'cap-2'   # TV Thing restarted its capture: a new generation.
        self.assertFalse(self.coordinator.status()['can_take'])
        self.master.calls.clear()
        self.coordinator.request('take', {'prepared_id': state['prepared']['id']})
        self.assertIn('expired or changed', self.finish()['operation']['error'])
        self.assertEqual(self.master.calls, [])

    def test_someone_elses_lock_is_never_overridden(self):
        self.roku.locked_by = 'Web remote'
        state = self.prepare()
        self.assertEqual(state['operation']['state'], 'failed')
        self.assertIn('Web remote', state['operation']['error'])
        self.assertEqual(self.roku.navigations, [])
        self.assertNotIn('prepare', [a for a, _ in self.master.calls])

    def test_cancel_stops_the_navigation_on_tv_thing_and_never_prepares(self):
        started, released = threading.Event(), threading.Event()
        self.addCleanup(released.set)

        def play(*_):
            started.set()
            self.assertTrue(released.wait(2))
            raise CueCancelledError('Stopped')
        self.controller.play.side_effect = play
        self.controller.cancel_operation.side_effect = released.set
        self.coordinator.request('prepare', TARGET)
        self.assertTrue(started.wait(1))
        with self.assertRaises(ControlBusyError):
            self.coordinator.request('prepare', {'source_id': 'youtube-tv', 'channel_id': 'FOX'})
        self.coordinator.request('cancel')
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.controller.cancel_operation.assert_called_once()
        self.assertNotIn('prepare', [a for a, _ in self.master.calls])

    def test_close_stops_a_running_navigation(self):
        started, released = threading.Event(), threading.Event()
        self.addCleanup(released.set)

        def play(*_):
            started.set()
            self.assertTrue(released.wait(2))
            raise CueCancelledError('Stopped')
        self.controller.play.side_effect = play
        self.controller.cancel_operation.side_effect = released.set
        self.coordinator.request('prepare', TARGET)
        self.assertTrue(started.wait(1))
        self.coordinator.close()
        self.controller.cancel_operation.assert_called_once()
        self.assertFalse(self.coordinator.thread.is_alive())

    def test_cancellation_at_readiness_boundary_removes_prepared_input(self):
        self.master.hook = lambda action, _: self.coordinator.request('cancel') if action == 'prepare' else None
        state = self.prepare()
        self.assertEqual(state['operation']['state'], 'failed')
        self.assertIsNone(state['prepared'])

    def test_baseball_resolves_exact_game_before_navigation(self):
        game = {'game_pk': 123, 'preferred_source': {'provider': 'mlb'}}
        self.baseball.game.return_value = game
        target = {'source_id': 'mlb', 'channel_id': '123', 'date': '2026-09-12'}
        self.coordinator.request('prepare', target)
        self.assertEqual(self.finish()['operation']['state'], 'succeeded')
        self.baseball.game.assert_called_once_with(123, '2026-09-12')
        self.controller.play_baseball_game.assert_called_once_with(target)

    def test_invalid_game_or_no_roku_never_navigates(self):
        with self.assertRaises(ConfigError):
            self.coordinator.request('prepare', {'source_id': 'mlb', 'channel_id': 'bad'})
        self.coordinator.roku_enabled = False
        with self.assertRaises(ConfigError):
            self.coordinator.request('prepare', TARGET)
        self.assertEqual(self.roku.navigations, [])

    def test_the_lock_is_wanted_while_a_roku_input_is_prepared_or_on_air(self):
        self.assertFalse(self.coordinator.roku_in_use())
        state = self.prepare()
        self.assertTrue(self.coordinator.roku_in_use())
        self.coordinator.request('take', {'prepared_id': state['prepared']['id']})
        self.finish()
        self.assertTrue(self.coordinator.roku_in_use())
        self.coordinator.request('fallback')
        self.finish()
        self.assertFalse(self.coordinator.roku_in_use())

    def test_queue_prepares_then_takes_exact_verified_input(self):
        item = SimpleNamespace(id='queue-item', target=TARGET)
        self.coordinator.queue = Mock()
        self.coordinator.queue.take_guard = lambda _: contextlib.nullcontext()
        result = self.coordinator.execute_queue(item)
        self.assertEqual(result['on_air']['channel_id'], 'NBC')
        self.assertEqual([action for action, _ in self.master.calls], ['fallback', 'prepare', 'take'])
        self.coordinator.queue.pause.assert_not_called()
        self.coordinator.queue.check_before_take.assert_called_once_with('queue-item')

    def test_queue_pause_during_preparation_prevents_take(self):
        self.coordinator.queue = Mock()
        self.coordinator.queue.check_before_take.side_effect = MasterStreamError('Queue paused')
        with self.assertRaisesRegex(MasterStreamError, 'Queue paused'):
            self.coordinator.execute_queue(SimpleNamespace(id='q', target=TARGET))
        self.assertNotIn('take', [action for action, _ in self.master.calls])

    def test_prepare_take_takes_the_verified_roku_input_once_ready(self):
        self.coordinator.queue = Mock()
        self.coordinator.request('prepare-take', TARGET)
        state = self.finish()
        self.assertEqual(state['operation']['state'], 'succeeded')
        self.assertEqual(state['on_air']['channel_id'], 'NBC')
        self.assertEqual([a for a, _ in self.master.calls], ['fallback', 'prepare', 'take'])
        self.assertEqual(self.master.calls[-1], ('take', {'prepared_id': 'prepared'}))
        self.coordinator.queue.pause.assert_called_once()     # manual control, like take
        self.coordinator.queue.check_before_take.assert_not_called()

    def test_prepare_take_works_for_a_tv_channel(self):
        target = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla_7_1'}
        self.coordinator.request('prepare-take', target)
        state = self.finish()
        self.assertEqual(state['on_air']['channel_id'], 'wjla_7_1')
        self.assertEqual([a for a, _ in self.master.calls], ['prepare', 'take'])
        self.assertEqual(self.roku.navigations, [])

    def test_prepare_take_never_takes_a_source_that_is_not_ready(self):
        target = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla_7_1'}
        original = self.master.request

        def not_ready(action='status', body=None):
            result = original(action, body)
            if action == 'prepare':
                self.master.state['can_take'] = False
            return result
        self.master.request = not_ready
        self.coordinator.request('prepare-take', target)
        state = self.finish()
        self.assertEqual(state['operation']['state'], 'failed')
        self.assertIn('no longer ready', state['operation']['error'])
        self.assertNotIn('take', [a for a, _ in self.master.calls])
        self.assertEqual(self.master.calls[-1][0], 'cancel')   # preview released
        self.assertIsNone(state['on_air'])

    def test_cancel_while_preparing_prevents_the_take(self):
        target = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla_7_1'}

        def cancel_during_prepare(action, body):
            if action == 'prepare':
                self.coordinator.request('cancel', {})
        self.master.hook = cancel_during_prepare
        self.coordinator.request('prepare-take', target)
        state = self.finish()
        self.assertEqual(state['operation']['state'], 'failed')
        self.assertNotIn('take', [a for a, _ in self.master.calls])
        self.assertIsNone(state['on_air'])

    def test_manual_master_command_pauses_queue(self):
        self.coordinator.queue = Mock()
        self.prepare()
        self.coordinator.queue.pause.assert_called_once()

    def test_manual_take_pauses_queue_without_preparing_again(self):
        state = self.prepare()
        self.coordinator.queue = Mock()
        self.master.calls.clear()
        self.coordinator.request('take', {'prepared_id': state['prepared']['id']})
        self.assertEqual(self.finish()['on_air']['channel_id'], 'NBC')
        self.assertEqual(self.master.calls, [('take', {'prepared_id': 'prepared'})])
        self.coordinator.queue.pause.assert_called_once()
        self.controller.play.assert_called_once()

    def test_stale_manual_take_never_takes_a_replacement(self):
        self.prepare()
        self.master.calls.clear()
        self.coordinator.request('take', {'prepared_id': 'old-preview'})
        state = self.finish()
        self.assertEqual(state['operation']['state'], 'failed')
        self.assertIsNone(state['on_air'])
        self.assertEqual(state['prepared']['id'], 'prepared')
        self.assertEqual(self.master.calls, [('take', {'prepared_id': 'old-preview'})])

    def test_manual_take_requires_prepared_id_not_channel_target(self):
        for body in (TARGET, {}, {'prepared_id': ''}, {'prepared_id': 123}):
            with self.subTest(body=body), self.assertRaises(ConfigError):
                self.coordinator.request('take', body)
        self.assertEqual(self.master.calls, [])
        self.controller.play.assert_not_called()

    def test_recent_matching_prepare_reuses_without_navigation_or_worker_reprepare(self):
        self.prepare()
        timestamp = self.coordinator.status()['roku_last_prepared']['prepared_at']
        self.master.calls.clear()
        state = self.prepare()
        self.assertEqual(self.master.calls, [])
        self.controller.play.assert_called_once()
        self.assertTrue(state['operation']['reused'])
        self.assertEqual(state['roku_last_prepared']['prepared_at'], timestamp)

    def test_force_prepare_navigates_again(self):
        self.prepare()
        self.coordinator.request('prepare', {**TARGET, 'force': True})
        self.assertEqual(self.finish()['operation']['state'], 'succeeded')
        self.assertEqual(self.controller.play.call_count, 2)

    def test_take_known_reattaches_after_fallback_without_navigation(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        self.master.calls.clear()
        self.coordinator.request('take-known', TARGET)
        state = self.finish()
        self.assertEqual(state['on_air']['channel_id'], 'NBC')
        self.assertEqual([action for action, _ in self.master.calls], ['prepare', 'take'])
        self.controller.play.assert_called_once()
        self.coordinator.request('take-known', TARGET)
        self.assertEqual(self.finish()['operation']['state'], 'succeeded')
        self.assertEqual(len(self.master.calls), 2, 'already on air does not cut or prepare again')

    def test_take_known_rejects_missing_expired_changed_and_wrong_game_states(self):
        game = {'game_pk': 123, 'preferred_source': {'provider': 'mlb'}}
        self.baseball.game.return_value = game
        target = {'source_id': 'mlb', 'channel_id': '123', 'date': '2026-09-23'}
        self.coordinator.request('take-known', target)
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertEqual(self.master.calls, [])
        self.coordinator.request('prepare', target)
        self.finish()
        self.master.calls.clear()
        for change in ({'channel_id': '124'}, {'date': '2026-09-22'}):
            self.coordinator.request('take-known', {**target, **change})
            self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.roku.lapse()
        self.coordinator.request('take-known', target)
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertFalse(self.coordinator.status()['can_take'])
        self.assertEqual(self.master.calls, [])
        self.controller.play_baseball_game.assert_called_once()

    def test_a_capture_restart_revokes_reuse(self):
        self.prepare()
        self.roku.capture = 'cap-2'
        self.coordinator.request('take-known', TARGET)
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertFalse(self.coordinator.status()['roku_last_prepared']['reusable'])
        self.assertNotIn('take', [action for action, _ in self.master.calls])

    def test_queue_reuses_recent_game_without_schedule_lookup_or_navigation(self):
        target = {'source_id': 'mlb', 'channel_id': '123', 'date': '2026-09-23'}
        self.baseball.game.return_value = {'game_pk': 123, 'preferred_source': {'provider': 'mlb'}}
        self.coordinator.request('prepare', target)
        self.finish()
        self.baseball.game.reset_mock()
        self.master.calls.clear()
        self.coordinator.queue = Mock()
        self.coordinator.queue.take_guard = lambda _: contextlib.nullcontext()
        result = self.coordinator.execute_queue(SimpleNamespace(id='q', target=target))
        self.assertEqual(result['on_air']['channel_id'], '123')
        self.assertEqual(self.master.calls, [('take', {'prepared_id': 'prepared'})])
        self.baseball.game.assert_not_called()
        self.controller.play_baseball_game.assert_called_once()
        self.coordinator.queue.check_before_take.assert_called_once_with('q')

    def test_baseball_lookup_is_async_and_cancel_prevents_navigation(self):
        entered, released = threading.Event(), threading.Event()
        self.addCleanup(released.set)

        def lookup(*args):
            entered.set()
            self.assertTrue(released.wait(2))
            return {'preferred_source': {'provider': 'mlb'}}
        self.baseball.game.side_effect = lookup
        accepted = self.coordinator.request('prepare', {'source_id': 'mlb', 'channel_id': '123'})
        self.assertEqual(accepted['state'], 'pending')
        self.assertTrue(entered.wait(1))
        self.coordinator.request('cancel')
        released.set()
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.controller.play_baseball_game.assert_not_called()

    def test_expired_queue_target_prepares_again_when_the_roku_no_longer_plays(self):
        self.prepare()
        self.roku.lapse()
        self.roku.still_plays = False
        result = self.coordinator.execute_queue(SimpleNamespace(id='q', target=TARGET))
        self.assertEqual(result['on_air']['channel_id'], 'NBC')
        self.assertEqual(self.controller.play.call_count, 2)
        self.assertTrue(self.coordinator.status()['roku_last_prepared']['reusable'])

    def test_a_change_during_the_reattach_prevents_take(self):
        self.prepare()
        self.master.state.update(prepared=None, can_take=False)

        def change(action, body):
            if action == 'prepare':
                self.roku.capture = 'cap-2'
        self.master.hook = change
        self.coordinator.request('take-known', TARGET)
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertNotIn('take', [action for action, _ in self.master.calls])


class StillPlayingTests(unittest.TestCase):
    """A Roku feed that fails is nearly always a blip in the capture card, not the Roku
    (2026-10-04 13:35: Sunday Ticket went back to a 2-minute navigation because its
    verification was over 15 minutes old, and was off the air for 5 minutes). What the Roku
    was verified playing goes back on without navigating, after TV Thing's brief check."""

    setUp, finish, prepare = CoordinatorTests.setUp, CoordinatorTests.finish, CoordinatorTests.prepare

    def queue(self, action='execute_queue'):
        self.coordinator.queue = Mock()
        self.coordinator.queue.take_guard = lambda _: contextlib.nullcontext()
        return getattr(self.coordinator, action)(SimpleNamespace(id='q', target=TARGET))

    def test_a_lapsed_verification_goes_back_on_without_navigating_while_the_roku_plays(self):
        self.prepare()
        generation = self.roku.generation()
        self.coordinator.request('fallback')
        self.finish()
        self.roku.lapse()
        self.master.calls.clear()
        with self.assertLogs('roku_stream.source_coordinator', 'WARNING') as logs:
            result = self.queue()
        self.assertEqual(result['on_air']['channel_id'], 'NBC')
        self.controller.play.assert_called_once()
        self.assertEqual([a for a, _ in self.master.calls], ['prepare', 'take'])
        self.assertEqual(self.master.calls[0][1]['roku']['generation'], generation, 'the same verified feed')
        self.assertTrue(self.coordinator.status()['roku_last_prepared']['reusable'])
        self.assertTrue(any('goes back on without navigating' in line for line in logs.output), logs.output)

    def test_a_restarted_capture_gets_a_new_generation_of_the_same_feed(self):
        self.prepare()
        old = self.roku.generation()
        self.coordinator.request('fallback')
        self.finish()
        self.roku.capture = 'cap-2'
        self.master.calls.clear()
        self.assertEqual(self.queue()['on_air']['channel_id'], 'NBC')
        self.controller.play.assert_called_once()
        self.assertNotEqual(self.master.calls[0][1]['roku']['generation'], old)

    def test_a_roku_that_stopped_playing_is_navigated_again(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        self.roku.lapse()
        self.roku.still_plays = False
        self.assertEqual(self.queue()['on_air']['channel_id'], 'NBC')
        self.assertEqual(self.controller.play.call_count, 2)

    def test_any_navigation_since_means_navigating_again_without_a_check(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        with self.roku.navigating():
            pass  # someone moved the Roku in TV Thing
        self.queue()
        self.assertEqual(self.controller.play.call_count, 2)
        self.assertEqual(self.roku.checks, 0)

    def test_a_reattach_that_fails_is_retried_without_navigating(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        self.roku.lapse()

        def once(action, body):
            if action == 'prepare':
                self.master.hook = lambda *_: None
                raise MasterStreamError('Input audio timestamps changed (delta_ms=-42.666666); prepare the source again')
        self.master.hook = once
        with self.assertRaises(MasterStreamError):
            self.queue()
        self.assertEqual(self.queue()['on_air']['channel_id'], 'NBC')
        self.controller.play.assert_called_once()

    def test_feed_recovery_asks_briefly_and_the_answer_holds_for_the_reattach(self):
        self.assertFalse(self.coordinator.roku_playing(TARGET), 'nothing verified yet')
        self.prepare()
        self.assertFalse(self.coordinator.roku_playing({**TARGET, 'channel_id': 'FOX'}))
        self.coordinator.request('fallback')
        self.finish()
        self.roku.lapse()
        self.assertTrue(self.coordinator.roku_playing({**TARGET, 'antenna': False}))
        self.assertEqual(self.roku.checks, 1)
        self.queue()
        self.assertEqual(self.roku.checks, 1, 'the check just passed renewed the verification')
        self.controller.play.assert_called_once()

    def test_a_manual_take_known_still_needs_a_recent_preparation(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        self.roku.lapse()
        self.coordinator.request('take-known', TARGET)
        self.assertEqual(self.finish()['operation']['state'], 'failed')

    def test_the_way_back_to_youtube_tv_reattaches_without_navigating(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        self.roku.lapse()
        self.master.state.update(state='live', on_air={'id': 'antenna', 'source_id': 'tv-thing-digital'})
        self.assertEqual(self.queue('preroll_queue'), 'prepared')
        self.assertEqual(self.queue('upgrade_queue')['on_air']['channel_id'], 'NBC')
        self.controller.play.assert_called_once()


class FakeTvControl:
    """TV Thing's HTTP API for TvRoku and RokuHold: locks, tunes, status, cancel."""

    def __init__(self):
        self.calls = []
        self.lock = None   # {"owner", "token"}
        self.lane = {'available': True, 'selection': None, 'stream': {'generation': 'cap-1.1', 'ready': True},
                     'roku': {'operation': None, 'reuse_max_age_seconds': 900}}
        self.tune_response = None
        self.on_poll = lambda: None

    def request(self, path, body=None):
        self.calls.append((path, copy.deepcopy(body)))
        if path == 'tuner/lock':
            if self.lock and body.get('token') != self.lock['token']:
                raise MasterStreamError('locked', details={'http_status': 423})
            renewed = bool(self.lock)
            self.lock = self.lock or {'owner': body['owner'], 'token': f'token-{len(self.calls)}'}
            return {'token': self.lock['token'], 'renewed': renewed,
                    'lock': {'owner': self.lock['owner'], 'expires_at': time.time() + 90}}
        if path == 'tuner/lock/release':
            if self.lock and body.get('token') == self.lock['token']:
                self.lock = None
            return {'released': True}
        if path == 'tune':
            return self.tune_response(body)
        if path == 'roku/cancel':
            operation = self.lane['roku']['operation']
            operation.update(state='cancelled', active=False)
            return {'cancelled': True}
        if path == 'roku/check':
            return {'playing': True}
        if path == 'status':
            self.on_poll()
            return {'lanes': {'roku': copy.deepcopy(self.lane)},
                    'locks': {'roku': {'owner': self.lock['owner']} if self.lock else None}}
        raise AssertionError(path)


class TvRokuTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.control = FakeTvControl()
        self.token_path = Path(self.directory.name) / 'roku-lock.json'
        self.hold = RokuHold(self.control, self.token_path)
        self.roku = TvRoku(self.control, self.hold, sleep=lambda _: None)

    def navigation(self, polls_until_done=2, state='succeeded'):
        operation = {'id': 'op1', 'state': 'running', 'active': True, 'message': 'Finding NBC'}
        polls = {'n': 0}

        def tune(body):
            self.control.lane['roku']['operation'] = operation
            self.control.lane['selection'] = None
            return {'ok': True, 'reused': False, 'operation': dict(operation)}

        def poll():
            polls['n'] += 1
            if polls['n'] >= polls_until_done and operation['active']:
                operation.update(state=state, active=False, message='done' if state == 'succeeded' else 'not found')
                if state == 'succeeded':
                    self.control.lane['selection'] = {**TARGET, 'reusable': True,
                                                     'resolved_source': {'provider': 'youtube_tv'}}
                    self.control.lane['stream']['generation'] = 'cap-1.2'
        self.control.tune_response = tune
        self.control.on_poll = poll

    def test_prepare_holds_the_lock_navigates_and_hands_over_the_generation(self):
        self.navigation()
        handoff = self.roku.prepare(TARGET)
        self.assertEqual(handoff['generation'], 'cap-1.2')
        tune = next(body for path, body in self.control.calls if path == 'tune')
        self.assertEqual(tune['token'], self.hold.token)
        self.assertEqual(self.control.lock['owner'], ROKU_OWNER)
        self.assertEqual(json.loads(self.token_path.read_text())['token'], self.hold.token)
        self.assertEqual(self.token_path.stat().st_mode & 0o777, 0o600)

    def test_a_failed_navigation_raises_with_its_reason(self):
        self.navigation(state='failed')
        with self.assertRaisesRegex(MasterStreamError, 'not found'):
            self.roku.prepare(TARGET)

    def test_stop_cancels_the_navigation_on_tv_thing(self):
        self.navigation(polls_until_done=1000)
        stops = iter([None, None, 'late'])
        with self.assertRaises(CueCancelledError):
            self.roku.prepare(TARGET, stop=lambda: next(stops, 'late'))
        self.assertIn('roku/cancel', [path for path, _ in self.control.calls])

    def test_someone_elses_lock_is_busy_never_overridden(self):
        self.control.lock = {'owner': 'Web remote', 'token': 'theirs'}
        with self.assertRaises(ControlBusyError):
            self.roku.prepare(TARGET)
        self.assertNotIn('tune', [path for path, _ in self.control.calls])
        self.assertTrue(all(not (body or {}).get('override') for _, body in self.control.calls))

    def test_the_lock_is_kept_while_in_use_released_when_idle_and_survives_a_restart(self):
        in_use = {'value': True}
        clock = {'now': 0.}
        self.hold = RokuHold(self.control, self.token_path, in_use=lambda: in_use['value'],
                             clock=lambda: clock['now'])
        token = self.hold.hold()
        # A web restart: the new process picks the same lock up again.
        restarted = RokuHold(self.control, self.token_path, in_use=lambda: True)
        self.assertEqual(restarted.token, token)
        restarted.keep()
        self.assertEqual(self.control.lock['token'], token)
        in_use['value'] = False
        self.hold.keep()
        self.assertIsNotNone(self.control.lock)
        clock['now'] += 61
        self.hold.keep()
        self.assertIsNone(self.control.lock)
        self.assertFalse(self.token_path.exists())

    def test_ready_playing_and_snapshot_read_tv_thing(self):
        self.control.lane['selection'] = {**TARGET, 'reusable': True, 'verified_at': 100, 'age_seconds': 5}
        self.assertTrue(self.roku.ready(TARGET))
        self.assertFalse(self.roku.ready({**TARGET, 'channel_id': 'FOX'}))
        self.assertTrue(self.roku.playing(TARGET))
        snapshot = self.roku.snapshot()
        self.assertEqual(snapshot['target'], TARGET)
        self.assertEqual(snapshot['selection_id'], 'cap-1.1')
        self.control.lane['roku']['operation'] = {'active': True}
        self.assertFalse(self.roku.ready(TARGET), 'not while the Roku navigates')

    def test_player_reads_what_tv_thing_last_saw_without_asking_the_roku(self):
        # 2026-10-12 20:21, the Roku City screensaver on air as Dodgers–Brewers: TV Thing
        # read YouTube TV still open, its player closed.
        yttv = {'id': '195316', 'name': 'YouTube TV'}
        self.control.lane['selection'] = {**TARGET, 'app': yttv}

        def reading(app=yttv, state='play', age=5.1, **player):
            self.control.lane['roku']['player'] = {
                'data': {'app': app, 'media_player': {'state': state, 'error': 'false', 'plugin': app}},
                'error': None, 'age_seconds': age, **player}
            return self.roku.player()

        self.assertEqual(reading(), {'playing': True, 'reason': None})
        self.assertEqual(reading(state='close'), {'playing': False, 'reason': 'its player is close'})
        self.assertEqual(reading(app={'id': '562859', 'name': 'Roku Dynamic Menu'}),
                         {'playing': False, 'reason': 'the Roku is in Roku Dynamic Menu'})
        self.assertIsNone(reading(state='close', age=45), 'an old reading says nothing')
        self.assertIsNone(reading(state='close', error='timed out'))
        self.control.lane['roku']['operation'] = {'active': True}
        self.assertIsNone(reading(state='close'), 'not while the Roku navigates')
        self.control.lane['roku']['operation'] = None
        self.control.lane['selection']['manual'] = True
        self.assertIsNone(reading(state='close'), 'not once someone moved it by hand')
        self.assertNotIn('roku/check', [path for path, _ in self.control.calls])


class RokuLeaseTests(unittest.TestCase):
    """The worker's lease: checks only; it never locks, renews or releases."""

    def setUp(self):
        self.control = FakeTvControl()
        self.control.config = TvThingConfig(enabled=True)
        self.control.owner = 'VizelVision master worker'
        self.control.lock = {'owner': ROKU_OWNER, 'token': 't'}
        self.control.lane['selection'] = dict(TARGET)
        self.control.lane['stream'].update(generation='cap-1.2', state='ready',
                                           playback=[{'protocol': 'hls', 'url': 'stream/roku.m3u8'}])

    def lease(self):
        return RokuLease.adopt(self.control, dict(TARGET), {'generation': 'cap-1.2'})

    def test_check_returns_the_lane_playlist_while_nothing_changed(self):
        lease = self.lease()
        lease.tune()
        self.assertEqual(lease.check(), 'http://127.0.0.1:8080/stream/roku.m3u8')
        self.assertEqual([p for p, _ in self.control.calls if p.startswith('tuner')], [])
        self.assertTrue(lease.release())
        self.assertEqual([p for p, _ in self.control.calls if p.startswith('tuner')], [])

    def test_a_new_generation_selection_or_lock_owner_fails_closed(self):
        changes = {'generation': lambda: self.control.lane['stream'].update(generation='cap-2.2'),
                   'selection': lambda: self.control.lane.update(selection={**TARGET, 'channel_id': 'FOX'}),
                   'manual': lambda: self.control.lane.update(selection={'manual': True}),
                   'owner': lambda: setattr(self.control, 'lock', {'owner': 'Web remote', 'token': 'x'}),
                   'released': lambda: setattr(self.control, 'lock', None)}
        for name, change in changes.items():
            with self.subTest(name):
                self.setUp()
                lease = self.lease()
                change()
                with self.assertRaises(MasterStreamError):
                    lease.check()

    def test_a_handoff_without_a_generation_is_refused(self):
        for handoff in (None, {}, {'generation': ''}):
            with self.assertRaises(MasterStreamError):
                RokuLease.adopt(self.control, dict(TARGET), handoff)


if __name__ == '__main__':
    unittest.main()
