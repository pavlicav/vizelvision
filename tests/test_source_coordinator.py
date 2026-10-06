import contextlib
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock
from unittest.mock import Mock

from roku_stream.config import FeedbackConfig, MasterConfig, TvThingConfig
from roku_stream.errors import ConfigError, ControlBusyError, CueCancelledError, NavigationError
from roku_stream.feedback import PpmFrame
from roku_stream.master import MasterStreamError
from roku_stream.roku_input import RokuLease, selection_path
from roku_stream.source_coordinator import SourceCoordinator


TARGET = {'source_id': 'youtube-tv', 'channel_id': 'NBC'}


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
            self.state.update(prepared={'id': 'prepared', **body, 'generation': body.get('selection_id')}, can_take=True)
        if action == 'take':
            if body.get('prepared_id') != (self.state['prepared'] or {}).get('id'):
                raise MasterStreamError('Prepared input changed')
            self.state.update(state='live', on_air=self.state['prepared'], prepared=None, can_take=False)
        return operation


class CoordinatorTests(unittest.TestCase):
    def test_prime_game_preparation_creates_a_game_specific_claim(self):
        from tests.test_prime_video import GAME, EVENT
        target = {'source_id': 'thursday-night-football', 'channel_id': str(GAME['game_id']), 'date': EVENT['date']}
        self.coordinator.sports = Mock()
        self.coordinator.sports.game.return_value = GAME
        self.controller.play_prime_game.return_value = {'ok': True, 'provider': 'prime_video', 'source': 'Prime Video',
            'verification': {'player_state': 'play', 'selected_prime_event': {'matched': True, **EVENT},
                             'playback_evidence': 'two_live_matchup_overlays_with_prime_video_playback'}}
        self.coordinator.request('prepare', target)
        state = self.finish()
        self.assertEqual(state['operation']['state'], 'succeeded')
        self.controller.play_prime_game.assert_called_once_with(GAME)
        self.controller.play_baseball_game.assert_not_called()
        self.assertEqual(self.coordinator.claim['target'], target)
        self.assertEqual(self.coordinator.claim['resolved_source']['provider'], 'prime_video')
        self.controller.play_prime_game.return_value['verification'].pop('selected_prime_event')
        self.controller.play_prime_game.return_value['verification']['visible_channel_template'] = {'matched': True}
        self.coordinator.request('prepare', {**target, 'force': True})
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertIsNone(self.coordinator.claim)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = SimpleNamespace(
            master=MasterConfig(enabled=True, socket_path=Path(self.directory.name) / 'master.sock'),
            feedback=FeedbackConfig(backend='direct', device='/dev/video1', input_format='mpegts',
                                    contribution_url='rtsp://127.0.0.1:18554/roku'),
            tv_thing=TvThingConfig(enabled=True),
            resolve_channel=lambda name: (0, SimpleNamespace(name='NBC')))
        self.master = FakeMaster()
        self.feedback = Mock(last_capture={'fresh': True, 'stream_id': 'capture'})
        self.feedback.status.return_value = {'ready': True, 'stream_id': 'capture'}
        self.feedback._stream.process.poll.return_value = None
        self.controller = Mock(feedback=self.feedback)
        self.baseball = Mock()
        self.coordinator = SourceCoordinator(self.config, self.controller, self.baseball,
                                             master=self.master, publisher_reader=lambda: 'publisher')
        self.addCleanup(self.coordinator.close)
        self.result = {'ok': True, 'operation_id': 'cue', 'verification': {
            'player_state': 'play', 'visible_channel_template': {'matched': True},
            'playback_evidence': 'roku_player_play_after_verified_selection'}}
        def play(*_):
            with self.coordinator.navigation_guard():
                self.assertIsNone(self.master.state['on_air'])
                self.assertFalse(selection_path(self.config.master).exists())
                return self.result
        self.controller.play.side_effect = play
        self.controller.play_baseball_game.side_effect = play

    def finish(self):
        self.coordinator.thread.join(timeout=3)
        self.assertFalse(self.coordinator.thread.is_alive())
        return self.coordinator.status()

    def prepare(self):
        self.coordinator.request('prepare', TARGET)
        return self.finish()

    def test_navigation_is_followed_by_validated_media_preparation_then_explicit_take(self):
        self.master.state.update(state='live', on_air={'source_id': 'tv-thing-digital'})
        def check(action, body):
            if action == 'prepare':
                lease = RokuLease(self.config, body, publisher_reader=lambda: 'publisher')
                self.assertEqual(lease.check(), self.config.feedback.contribution_url)
        self.master.hook = check
        state = self.prepare()
        self.assertEqual(state['operation']['state'], 'succeeded')
        self.assertIsNone(state['on_air'])
        self.assertEqual([a for a, _ in self.master.calls], ['fallback', 'prepare'])
        self.coordinator.request('take', {'prepared_id': state['prepared']['id']})
        self.assertEqual(self.finish()['on_air']['source_id'], 'youtube-tv')

    def test_failed_or_unverified_selection_never_prepares_media(self):
        for verification in ({}, {'player_state': 'play', 'visible_channel_template': {'matched': False},
                                  'playback_evidence': 'test'}):
            self.result['verification'] = verification
            self.master.calls.clear()
            self.assertEqual(self.prepare()['operation']['state'], 'failed')
            self.assertNotIn('prepare', [a for a, _ in self.master.calls])
            self.assertFalse(self.coordinator.path.exists())

    def test_changed_capture_invalidates_verification(self):
        self.feedback.status.return_value['stream_id'] = 'replacement'
        self.assertIn('capture changed', self.prepare()['operation']['error'])
        self.assertFalse(self.coordinator.path.exists())

    def test_legacy_navigation_invalidates_selection_and_confirms_fallback_first(self):
        self.prepare()
        self.coordinator.request('take', {'prepared_id': 'prepared'})
        self.finish()
        with self.coordinator.navigation_guard():
            self.assertEqual(self.master.state['state'], 'fallback')
            self.assertIsNone(self.master.state['prepared'])
            self.assertFalse(self.coordinator.path.exists())

    def test_worker_unavailable_blocks_legacy_navigation(self):
        self.master.state['state'] = 'unavailable'
        with self.assertRaisesRegex(MasterStreamError, 'Cannot confirm'):
            with self.coordinator.navigation_guard():
                self.fail('Navigation must not start')

    def test_legacy_navigation_excludes_master_actions(self):
        errors = []
        with self.coordinator.navigation_guard():
            def competing():
                try:
                    self.coordinator.request('prepare', TARGET)
                except ControlBusyError as exc:
                    errors.append(str(exc))
            thread = threading.Thread(target=competing)
            thread.start(); thread.join(timeout=1)
        self.assertEqual(len(errors), 1)
        self.controller.play.assert_not_called()

    def test_cancel_navigation_reaches_owned_cue_and_never_prepares(self):
        started, released = threading.Event(), threading.Event()
        self.addCleanup(released.set)
        def play(*_):
            with self.coordinator.navigation_guard():
                started.set()
                self.assertTrue(released.wait(2))
                raise CueCancelledError('Stopped')
        self.controller.play.side_effect = play
        self.controller.cancel_operation.side_effect = released.set
        self.coordinator.request('prepare', TARGET)
        self.assertTrue(started.wait(1))
        with self.assertRaises(ControlBusyError):
            with self.coordinator.navigation_guard():
                self.fail('Competing navigation was admitted')
        self.coordinator.request('cancel')
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertNotIn('prepare', [a for a, _ in self.master.calls])

    def test_cancellation_at_readiness_boundary_removes_prepared_input(self):
        self.master.hook = lambda action, _: self.coordinator.request('cancel') if action == 'prepare' else None
        state = self.prepare()
        self.assertEqual(state['operation']['state'], 'failed')
        self.assertIsNone(state['prepared'])
        self.assertFalse(self.coordinator.path.exists())

    def test_baseball_resolves_exact_game_before_navigation(self):
        game = {'game_pk': 123, 'preferred_source': {'provider': 'mlb'}}
        self.baseball.game.return_value = game
        self.coordinator.request('prepare', {'source_id': 'mlb', 'channel_id': '123', 'date': '2026-09-12'})
        self.assertEqual(self.finish()['operation']['state'], 'succeeded')
        self.baseball.game.assert_called_once_with(123, '2026-09-12')
        self.controller.play_baseball_game.assert_called_once_with(game)

    def test_invalid_game_or_disabled_capture_never_navigates(self):
        with self.assertRaises(ConfigError):
            self.coordinator.request('prepare', {'source_id': 'mlb', 'channel_id': 'bad'})
        self.coordinator.roku_enabled = False
        with self.assertRaises(ConfigError):
            self.coordinator.request('prepare', TARGET)
        self.controller.play.assert_not_called()

    def test_capture_restart_expires_claim_without_browser_polling(self):
        self.prepare()
        self.feedback.status.return_value['stream_id'] = 'replacement'
        deadline = time.monotonic() + 1
        while self.coordinator.path.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertFalse(self.coordinator.path.exists())

    def test_close_invalidates_selection(self):
        self.prepare()
        self.coordinator.close()
        self.assertFalse(self.coordinator.path.exists())


    def test_queue_prepares_then_takes_exact_verified_input(self):
        item = SimpleNamespace(id='queue-item', target=TARGET)
        self.coordinator.queue = Mock()
        self.coordinator.queue.take_guard = lambda _: __import__('contextlib').nullcontext()
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
        self.assertFalse(self.coordinator.path.exists())

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
        self.controller.play.assert_not_called()

    def test_prepare_take_never_takes_a_source_that_is_not_ready(self):
        target = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla_7_1'}
        self.master.hook = lambda action, body: None
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
        self.coordinator.last_prepared.record['prepared_at'] -= 901
        self.coordinator.request('take-known', target)
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertFalse(self.coordinator.status()['can_take'])
        self.assertEqual(self.master.calls, [])
        self.controller.play_baseball_game.assert_called_once()

    def test_capture_and_publisher_replacement_revoke_reuse(self):
        self.prepare()
        self.coordinator.publisher_reader = lambda: 'replacement'
        self.coordinator.request('take-known', TARGET)
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertFalse(self.coordinator.status()['roku_last_prepared']['reusable'])
        self.coordinator.publisher_reader = lambda: 'publisher'
        self.prepare()
        self.feedback.status.return_value['stream_id'] = 'new-capture'
        self.coordinator.request('take-known', TARGET)
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertNotIn('take', [action for action, _ in self.master.calls])

    def test_last_known_history_survives_restart_without_restoring_authority(self):
        from roku_stream.roku_preparation import RokuPreparation
        self.prepare()
        old = self.coordinator.status()['roku_last_prepared']
        restored = RokuPreparation(self.config.master).snapshot(None)
        self.assertEqual(restored['target'], TARGET)
        self.assertEqual(restored['prepared_at'], old['prepared_at'])
        self.assertFalse(restored['reusable'])

    def test_queue_reuses_recent_game_without_schedule_lookup_or_navigation(self):
        target = {'source_id': 'mlb', 'channel_id': '123', 'date': '2026-09-23'}
        self.baseball.game.return_value = {'game_pk': 123, 'preferred_source': {'provider': 'mlb'}}
        self.coordinator.request('prepare', target)
        self.finish()
        self.baseball.game.reset_mock()
        self.master.calls.clear()
        self.coordinator.queue = Mock()
        self.coordinator.queue.take_guard = lambda _: __import__('contextlib').nullcontext()
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

    def test_expired_queue_target_prepares_again_before_taking(self):
        self.prepare()
        self.coordinator.last_prepared.record['prepared_at'] -= 901
        result = self.coordinator.execute_queue(SimpleNamespace(id='q', target=TARGET))
        self.assertEqual(result['on_air']['channel_id'], 'NBC')
        self.assertEqual(self.controller.play.call_count, 2)
        self.assertTrue(self.coordinator.status()['roku_last_prepared']['reusable'])

    def test_expiry_during_cached_media_reattach_prevents_take(self):
        self.prepare()
        self.master.state.update(prepared=None, can_take=False)
        def expire(action, body):
            if action == 'prepare':
                self.coordinator.last_prepared.record['prepared_at'] -= 901
        self.master.hook = expire
        self.coordinator.request('take-known', TARGET)
        self.assertEqual(self.finish()['operation']['state'], 'failed')
        self.assertNotIn('take', [action for action, _ in self.master.calls])

    def test_invalid_persisted_history_does_not_break_status(self):
        from roku_stream.roku_preparation import RokuPreparation
        path = self.coordinator.last_prepared.path
        path.parent.mkdir(parents=True, exist_ok=True)
        for raw in ('broken', '[]', '{"target":{},"prepared_at":123}',
                    '{"target":{},"prepared_at":NaN,"selection_id":"abc"}'):
            path.write_text(raw)
            self.assertIsNone(RokuPreparation(self.config.master).snapshot(None))

    def test_expired_mismatched_and_missing_claims_are_rejected(self):
        self.prepare()
        original = json.loads(self.coordinator.path.read_text())
        body = {**TARGET, 'selection_id': original['selection_id']}
        self.coordinator.stopping.set()
        self.coordinator.heartbeat.join(timeout=1)
        for change in ({'expires_at': time.time() - 1}, {'expires_at': time.time()+100},
                       {'selection_id': 'old'}, {'target': {**TARGET, 'channel_id': 'FOX'}}):
            self.coordinator.path.write_text(json.dumps({**original, **change}))
            with self.assertRaises(MasterStreamError):
                RokuLease(self.config, body, publisher_reader=lambda: 'publisher').check()
        self.coordinator.path.unlink()
        with self.assertRaises(MasterStreamError):
            RokuLease(self.config, body).check()

    def test_contribution_replacement_invalidates_selection(self):
        self.prepare()
        claim = json.loads(self.coordinator.path.read_text())
        with self.assertRaisesRegex(MasterStreamError, 'capture restarted'):
            RokuLease(self.config, {**TARGET, 'selection_id': claim['selection_id']},
                      publisher_reader=lambda: 'replacement').check()


class StillPlayingTests(unittest.TestCase):
    """A Roku feed that fails is nearly always a blip in the capture card, not the Roku
    (2026-10-04 13:35: Sunday Ticket went back to a 2-minute navigation because its
    verification was over 15 minutes old, and was off the air for 5 minutes). What the Roku
    was verified playing goes back on without navigating, after a brief check."""

    finish, prepare = CoordinatorTests.finish, CoordinatorTests.prepare

    def setUp(self):
        CoordinatorTests.setUp(self)
        self.controller.ecp.active_app.return_value = SimpleNamespace(id='195316', name='YouTube TV')
        self.player = {'state': 'play', 'error': 'false', 'plugin': {'id': '195316', 'name': 'YouTube TV'}}
        self.controller.ecp.media_player.side_effect = lambda: dict(self.player)
        self.frozen = False
        self.frames = 0
        def capture():
            self.frames += 1
            self.feedback.last_capture = {'fresh': True, 'stream_id': self.feedback.status.return_value['stream_id']}
            return PpmFrame(64, 36, bytes([0 if self.frozen or self.frames % 2 else 200]) * (64 * 36 * 3))
        self.feedback.capture.side_effect = capture

    def lapse(self):
        """The verification is over 15 minutes old, as for any game by its second quarter."""
        self.coordinator.last_prepared.record['prepared_at'] -= 901

    def queue(self, action='execute_queue'):
        self.coordinator.queue = Mock()
        self.coordinator.queue.take_guard = lambda _: contextlib.nullcontext()
        return getattr(self.coordinator, action)(SimpleNamespace(id='q', target=TARGET))

    def test_a_lapsed_verification_goes_back_on_without_navigating_while_the_roku_plays(self):
        self.prepare()
        selection = self.coordinator.claim['selection_id']
        self.coordinator.request('fallback')
        self.finish()
        self.lapse()
        self.master.calls.clear()
        with self.assertLogs('roku_stream.source_coordinator', 'WARNING') as logs:
            result = self.queue()
        self.assertEqual(result['on_air']['channel_id'], 'NBC')
        self.controller.play.assert_called_once()
        self.assertEqual([a for a, _ in self.master.calls], ['prepare', 'take'])
        self.assertEqual(self.master.calls[0][1]['selection_id'], selection, 'the selection an input may hold')
        self.assertTrue(self.coordinator.status()['roku_last_prepared']['reusable'])
        self.assertTrue(any('goes back on without navigating' in line for line in logs.output), logs.output)

    def test_a_restarted_capture_gets_a_new_selection_of_the_same_feed(self):
        self.prepare()
        old = self.coordinator.claim['selection_id']
        self.coordinator.request('fallback')
        self.finish()
        self.feedback.status.return_value['stream_id'] = 'new-capture'
        self.coordinator.publisher_reader = lambda: 'replacement'
        def check(action, body):
            if action == 'prepare':
                lease = RokuLease(self.config, body, publisher_reader=lambda: 'replacement')
                self.assertEqual(lease.check(), self.config.feedback.contribution_url)
        self.master.hook = check
        self.master.calls.clear()
        self.assertEqual(self.queue()['on_air']['channel_id'], 'NBC')
        self.controller.play.assert_called_once()
        self.assertNotEqual(self.master.calls[0][1]['selection_id'], old)

    def test_a_roku_that_stopped_playing_is_navigated_again(self):
        changes = {'paused': lambda: self.player.update(state='pause'),
                   'another app': lambda: self.controller.ecp.active_app.configure_mock(
                       return_value=SimpleNamespace(id='12', name='Netflix')),
                   'frozen': lambda: setattr(self, 'frozen', True),
                   'no picture': lambda: self.feedback.capture.configure_mock(
                       side_effect=NavigationError('Capture stream stopped'))}
        for name, change in changes.items():
            with self.subTest(name), mock.patch('roku_stream.source_coordinator.PLAYING_SECONDS', .3):
                self.setUp()
                self.prepare()
                self.coordinator.request('fallback')
                self.finish()
                self.lapse()
                change()
                with self.assertLogs('roku_stream.source_coordinator', 'WARNING') as logs:
                    self.assertEqual(self.queue()['on_air']['channel_id'], 'NBC')
                self.assertEqual(self.controller.play.call_count, 2)
                self.assertTrue(any('no longer plays' in line for line in logs.output), logs.output)

    def test_any_navigation_since_means_navigating_again_without_a_check(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        with self.coordinator.navigation_guard():
            pass  # an operator's channel change
        self.lapse()
        self.controller.ecp.media_player.reset_mock()
        self.queue()
        self.assertEqual(self.controller.play.call_count, 2)
        self.controller.ecp.media_player.assert_not_called()

    def test_a_reattach_that_fails_is_retried_without_navigating(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        self.lapse()
        def once(action, body):
            if action == 'prepare':
                self.master.hook = lambda *_: None
                raise MasterStreamError('Input audio timestamps changed (delta_ms=-42.666666); prepare the source again')
        self.master.hook = once
        with self.assertRaises(MasterStreamError):
            self.queue()
        self.assertIsNone(self.coordinator.claim)
        self.assertEqual(self.queue()['on_air']['channel_id'], 'NBC')
        self.controller.play.assert_called_once()

    def test_feed_recovery_asks_briefly_and_the_answer_holds_for_the_reattach(self):
        self.assertFalse(self.coordinator.roku_playing(TARGET), 'nothing verified yet')
        self.prepare()
        self.assertFalse(self.coordinator.roku_playing({**TARGET, 'channel_id': 'FOX'}))
        self.assertTrue(self.coordinator.roku_playing({**TARGET, 'antenna': False}))
        self.coordinator.request('fallback')
        self.finish()
        self.lapse()
        self.controller.ecp.media_player.reset_mock()
        self.queue()
        self.controller.ecp.media_player.assert_not_called()
        self.controller.play.assert_called_once()

    def test_a_manual_take_known_still_needs_a_recent_preparation(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        self.lapse()
        self.coordinator.request('take-known', TARGET)
        self.assertEqual(self.finish()['operation']['state'], 'failed')

    def test_the_way_back_to_youtube_tv_reattaches_without_navigating(self):
        self.prepare()
        self.coordinator.request('fallback')
        self.finish()
        self.lapse()
        self.master.state.update(state='live', on_air={'id': 'antenna', 'source_id': 'tv-thing-digital'})
        self.assertEqual(self.queue('preroll_queue'), 'prepared')
        self.assertEqual(self.queue('upgrade_queue')['on_air']['channel_id'], 'NBC')
        self.controller.play.assert_called_once()
