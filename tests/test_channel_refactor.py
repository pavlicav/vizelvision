import json
import tempfile
import unittest
import urllib.error
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from roku_stream.config import ChannelConfig
from roku_stream.controller import RokuStreamController
from roku_stream.ecp import EcpClient, RokuApp
from roku_stream.errors import ControlBusyError, NavigationError
from roku_stream.feedback import PpmFrame, TvThingFeedback
from roku_stream.operations import OperationStore
from tests import test_controller as fixtures


class ChannelRefactorTests(unittest.TestCase):
    def test_lineup_changes_and_dropped_keys_do_not_skip_target_during_positioning(self):
        # NFL moved above its saved offset. Previously the unchecked initial
        # burst passed it, then searched only the rows below it. Cover both
        # directions, a target farther away, and acknowledged but dropped keys.
        for start, target, dropped in [(0, 23, 0), (44, 39, 0), (0, 30, 0), (0, 23, 2)]:
            with self.subTest(start=start, target=target, dropped=dropped), tempfile.TemporaryDirectory() as directory:
                controller = self.controller(Path(directory))
                anchor = ChannelConfig('NBC' if start == 0 else 'SEC Network', guide_index=start)
                channel = ChannelConfig('NFL Network', guide_index=27)
                controller.config = replace(controller.config, channels=(anchor, channel))
                feedback = TvThingFeedback(controller.config.feedback)
                controller.feedback = feedback
                position, sequence = start, 0
                strong = {'matched': True, 'correlation': .99, 'correlation_margin': .20}

                def keypress(key):
                    nonlocal position
                    controller.ecp.keys.append(key)
                    if len(controller.ecp.keys) > dropped:
                        position += 1 if key == 'Down' else -1

                def capture():
                    nonlocal sequence
                    sequence += 1
                    feedback.last_capture = {'fresh': True, 'stream_id': 'test', 'sequence': sequence}
                    feedback.last_frame = PpmFrame(1, 1, bytes([position, 0, 0]))
                    return feedback.last_frame

                def verify(name, *, configured_path=None, frame=None):
                    frame = frame or capture()
                    if frame.rgb[0] != target:
                        raise NavigationError('Wrong guide row', details={'visual_verification': {'matched': False}})
                    return strong.copy()

                controller.ecp.keypress = keypress
                feedback.capture = capture
                feedback.verify_selected = verify
                feedback.assert_current_program_focus = Mock(return_value={'matched': True})
                feedback.identify_selected = Mock(side_effect=NavigationError('Unconfigured neighbor'))
                events = []
                result = controller._open_channel_row(channel, events, guide_observation={
                    'channel': anchor.name, 'guide_index': start, 'focus': 'program', 'verification': strong})
                direction = 'Down' if target > start else 'Up'
                self.assertEqual(controller.ecp.keys, [direction] * (abs(target - start) + dropped))
                self.assertEqual(position, target)
                self.assertEqual(result['method'], 'two_fresh_guide_observations')
                self.assertEqual(len(result['observations']), 2)
                if abs(target - start) + dropped <= abs(27 - start):
                    self.assertTrue(any(e['event'] == 'guide_target_observed_during_positioning' for e in events))

    def test_home_recommendations_must_reach_tab_focus_before_selecting_live(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller._observe_state = Mock(side_effect=[
                {'state': 'youtube_tv_home', 'evidence': 'ocr_home_recommendations'},
                {'state': 'youtube_tv_home', 'evidence': 'ocr_top_navigation'},
                {'state': 'youtube_tv_home', 'evidence': 'home_focus_geometry'},
                {'state': 'live_guide', 'focus': 'program', 'channel': 'NBC'},
            ])
            controller._drive_to_live_guide('195316', [])
            self.assertEqual(controller.ecp.keys, ['Up', 'Up', *controller.config.navigation.open_live_guide_keys])

    def test_resume_banner_moves_down_to_navigation_without_selecting_playback(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller._observe_state = Mock(side_effect=[
                {'state': 'youtube_tv_home', 'navigation_tab': 'resume', 'evidence': 'resume_banner_focus_geometry'},
                {'state': 'youtube_tv_home', 'evidence': 'home_focus_geometry'},
                {'state': 'live_guide', 'focus': 'program', 'channel': 'NBC'},
            ])
            controller._drive_to_live_guide('195316', [])
            self.assertEqual(controller.ecp.keys, ['Down', *controller.config.navigation.open_live_guide_keys])

    def test_live_entry_passes_toolbar_before_accepting_guide_focus(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller._observe_state = Mock(side_effect=[
                {'state': 'youtube_tv_home', 'navigation_tab': 'live', 'evidence': 'live_tab_focus_geometry'},
                {'state': 'live_guide', 'focus': None, 'evidence': 'ocr_guide_time_grid'},
                {'state': 'live_guide', 'focus': 'program', 'channel': 'NBC'},
            ])
            observed = controller._drive_to_live_guide('195316', [])
            self.assertEqual(observed['channel'], 'NBC')
            self.assertEqual(controller.ecp.keys, ['Down', 'Down', 'Down'])

    def test_navigation_exhaustion_persists_failure_without_circular_event_log(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller._observe_state = Mock(return_value={
                'state': 'youtube_tv_user_select', 'profile_verified': False})
            with self.assertRaises(NavigationError):
                controller.play('ESPN')
            operation = controller.operation_status()
            self.assertFalse(operation['active'])
            self.assertEqual(operation['phase'], 'error')
            json.dumps(controller.get_operation(operation['id']))

    def controller(self, root, feedback=None):
        config = fixtures.ControllerTests().config(root)
        config = replace(config, feedback=replace(config.feedback, fresh_segments=True, network_page_fallback=True))
        return RokuStreamController(config, ecp=fixtures.FakeEcp(), feedback=feedback or fixtures.FakeFeedback(), sleeper=lambda _: None)

    def test_delayed_launch_is_polled_without_reposting(self):
        client = EcpClient('http://roku.test', sleeper=lambda _: None)
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError(TimeoutError())) as post:
            with patch.object(client, 'active_app', side_effect=[RokuApp('home', 'Home'), RokuApp('home', 'Home'), RokuApp('195316', 'YouTube TV')]) as active:
                client.launch('195316')
        self.assertEqual(post.call_count, 1)
        self.assertEqual(active.call_count, 3)

    def test_segment_capture_skips_inflight_segment_and_rejects_stream_change(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.controller(Path(directory)).config.feedback
            feedback = TvThingFeedback(config)
            feedback.wait = lambda _: None
            feedback._latest_segment = Mock(side_effect=[(10, 'old'), (10, 'old'), (11, 'inflight'), (12, 'fresh')])
            feedback._decode_frame = Mock(return_value=PpmFrame(1, 1, b'abc'))
            feedback.assert_ready = Mock(return_value={'stream_id': 'one'})
            feedback._capture_fresh_segment({'stream_id': 'one'})
            feedback._decode_frame.assert_called_once_with('fresh')
            self.assertEqual(feedback.last_capture['sequence'], 12)
            feedback._latest_segment = Mock(side_effect=[(12, 'old'), (14, 'fresh')])
            feedback.assert_ready.return_value = {'stream_id': 'two'}
            with self.assertRaisesRegex(NavigationError, 'stream changed'):
                feedback._capture_fresh_segment({'stream_id': 'one'})

    def test_short_route_requires_separate_frames_and_strong_logo_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            feedback = TvThingFeedback(controller.config.feedback)
            controller.feedback = feedback
            def capture():
                feedback.last_capture = {'fresh': True, 'stream_id': 'one', 'sequence': next(sequences)}
                return PpmFrame(1, 1, b'abc')
            feedback.capture = capture
            feedback.assert_current_program_focus = Mock(return_value={'matched': True})
            feedback.verify_selected = Mock(return_value={'matched': True, 'correlation': .99, 'correlation_margin': .04})
            channel = controller.config.channels[0]
            sequences = iter([10, 12])
            result = controller._verify_direct_selection(channel, [])
            self.assertEqual(result['method'], 'two_fresh_guide_observations')
            sequences = iter([12, 12])
            with self.assertRaisesRegex(NavigationError, 'distinct fresh frames'):
                controller._verify_direct_selection(channel, [])
            sequences = iter([14])
            feedback.verify_selected.return_value['correlation_margin'] = .001
            self.assertIsNone(controller._verify_direct_selection(channel, []))
            feedback.capture = Mock(side_effect=AssertionError('ambiguous affiliate must not use short route'))
            self.assertIsNone(controller._verify_direct_selection(replace(channel, anchor_safe=False), []))

    def test_async_reservation_rejects_overlap_and_preserves_early_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            with patch('roku_stream.controller.threading.Thread') as thread:
                accepted = controller.submit_play('ESPN')
                with self.assertRaises(ControlBusyError):
                    controller.submit_play('ESPN')
                with self.assertRaises(ControlBusyError):
                    controller.cancel_operation(expected_id='0' * 32)
                self.assertFalse(controller._cancel.is_set())
                controller.cancel_operation()
                thread.call_args.kwargs['target']()
            operation = controller.get_operation(accepted['id'])
            self.assertEqual(operation['phase'], 'cancelled')
            self.assertFalse(operation['active'])
            self.assertEqual(controller.ecp.keys, [])
            self.assertTrue(controller._lock.acquire(False))
            controller._lock.release()

    def test_unfamiliar_sunday_ticket_logo_cannot_reverse_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            controller.feedback = TvThingFeedback(controller.config.feedback)
            self.assertFalse(controller._reliable_guide_anchor({
                'channel': 'SEC Network', 'guide_index': 29,
                'verification': {'correlation': .933, 'correlation_margin': .025}}))
            self.assertTrue(controller._reliable_guide_anchor({
                'channel': 'ESPN', 'guide_index': 2,
                'verification': {'correlation': .998, 'correlation_margin': .025}}))

    def test_failed_cue_keeps_events_and_terminal_record(self):
        with tempfile.TemporaryDirectory() as directory:
            feedback = fixtures.FakeFeedback()
            feedback.verify_network_page = Mock(side_effect=NavigationError('wrong network page'))
            controller = self.controller(Path(directory), feedback)
            with self.assertRaises(NavigationError):
                controller.play('ESPN')
            operation = controller.operation_status()
            self.assertEqual(operation['phase'], 'error')
            self.assertIsNotNone(operation['completed_at'])
            trace = (controller._operations.directory / (operation['id'] + '.jsonl')).read_text()
            events = [json.loads(line) for line in trace.splitlines()]
            self.assertEqual(events[-1]['event'], 'cue_failed')
            self.assertTrue(all('at' in event for event in events))
            self.assertEqual(controller.get_operation(operation['id'])['error']['type'], 'NavigationError')

    def test_restart_marks_unfinished_operations_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OperationStore(Path(directory))
            store.save({'id': 'a' * 32, 'active': True, 'phase': 'accepted'})
            restarted = OperationStore(Path(directory))
            self.assertTrue(restarted.get('a' * 32)['active'])
            restarted.recover_interrupted()
            self.assertFalse(restarted.get('a' * 32)['active'])
            self.assertEqual(restarted.get('a' * 32)['error']['code'], 'operation_interrupted')
            self.assertIsNone(restarted.get('../config'))


if __name__ == '__main__':
    unittest.main()
