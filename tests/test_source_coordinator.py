import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from roku_stream.config import FeedbackConfig, MasterConfig, TvThingConfig
from roku_stream.errors import ConfigError, ControlBusyError, CueCancelledError
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
