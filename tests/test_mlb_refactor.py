import gzip
import shutil
import tempfile
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from roku_stream.controller import RokuStreamController
from roku_stream.ecp import RokuApp
from roku_stream.errors import ControlBusyError, EcpError, NavigationError
from roku_stream.feedback import PpmFrame, TvThingFeedback, VisualFeedback
from roku_stream.states import AppState
from tests import test_controller as fixtures


class MlbRefactorTests(unittest.TestCase):
    def controller(self, root, observations=(), media_format=None):
        ecp = fixtures.FakeEcp()
        ecp.active_app = lambda: RokuApp('14', 'MLB')
        ecp.media_player = lambda: {'state': 'play', 'plugin': {'id': '14'}, 'format': media_format or {'video': 'h264'}}
        feedback = fixtures.FakeFeedback()
        remaining = list(observations)
        feedback.detect_mlb_state = lambda *args: remaining.pop(0) if len(remaining) > 1 else remaining[0]
        controller = RokuStreamController(fixtures.ControllerTests().config(root), ecp=ecp, feedback=feedback, sleeper=lambda _: None)
        return controller

    def test_live_game_after_midnight_uses_lineup(self):
        game = {'official_date': (date.today() - timedelta(days=1)).isoformat(), 'state': 'Live'}
        self.assertTrue(RokuStreamController._prefer_mlb_lineup(game))
        self.assertFalse(RokuStreamController._prefer_mlb_lineup({**game, 'state': 'Final'}))

    def test_real_loading_screen_cannot_become_feed_picker(self):
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            for name, state in [('mlb-loading', AppState.MLB_GAMES_LOADING), ('mlb-home-hero', AppState.MLB_HOME), ('mlb-feed-picker', AppState.MLB_FEED_PICKER), ('mlb-single-video-picker', AppState.MLB_FEED_PICKER), ('mlb-live-prompt', AppState.JOIN_LIVE_OR_START_FROM_BEGINNING), ('mlb-playing-video', AppState.FULL_PROGRAM), ('mlb-resume-prompt', AppState.JOIN_LIVE_OR_START_FROM_BEGINNING)]:
                with self.subTest(name=name):
                    raw = gzip.decompress((Path(__file__).parent / 'fixtures' / f'{name}.ppm.gz').read_bytes())
                    result = feedback.detect_mlb_state(PpmFrame.parse(raw), {'state': 'play', 'plugin': {'id': '14'}}, '14')
                    self.assertEqual(result['state'], state)
                    if state == AppState.FULL_PROGRAM:
                        with self.assertRaises(NavigationError):
                            feedback.mlb_home_lineup_cursor(PpmFrame.parse(raw))
                    if state == AppState.MLB_FEED_PICKER:
                        self.assertEqual(result['selection']['selected'], 'video')

    def test_live_badge_survives_missing_ocr_label(self):
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            feedback.ocr = Mock()
            observation = feedback.ocr.read.return_value
            observation.text = 'Braves Phillies'
            observation.contains_phrase.return_value = False
            observation.find_names.side_effect = lambda names: [names[0]]
            raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-live-card.ppm.gz').read_bytes())
            frame = PpmFrame.parse(raw)
            result = feedback.verify_mlb_home_lineup_game(('Braves',), ('Phillies',), frame)
            self.assertTrue(result['matched'])
            self.assertTrue(result['live'])
            # Removing color preserves card focus and team logos, while
            # ensuring the same card cannot claim live from brightness alone.
            gray = bytes(value for offset in range(0, len(frame.rgb), 3)
                         for value in [sum(frame.rgb[offset:offset + 3]) // 3] * 3)
            result = feedback.verify_mlb_home_lineup_game(
                ('Braves',), ('Phillies',), PpmFrame(frame.width, frame.height, gray))
            self.assertTrue(result['matched'])
            self.assertFalse(result['live'])

    def test_home_watch_live_label_is_not_a_playback_dialog(self):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-home-watch-live.ppm.gz').read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            feedback.ocr = Mock()
            feedback.ocr.read.return_value.text = 'Home Games Shows Watch Live Today’s Lineup'
            feedback.ocr.read.return_value.contains_phrase.side_effect = lambda text: text == 'Watch Live'
            result = feedback.detect_mlb_state(PpmFrame.parse(raw), {'state': 'close', 'plugin': {'id': '14'}}, '14')
            self.assertEqual(result['state'], AppState.MLB_HOME)

    def test_grid_live_badge_survives_misread_inning_without_using_team_logo(self):
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            feedback.ocr = Mock()
            feedback.ocr.read.return_value.text = 'BOT? 0-0 2 OUT Nationals Tigers'
            feedback.ocr.read.return_value.contains_phrase.return_value = False
            feedback.ocr.read.return_value.find_names.side_effect = lambda names: [names[0]]
            feedback.mlb_grid_cursor = Mock(return_value={'bounds': (57, 176, 441, 489)})
            for badge_y, expected in ((210, True), (265, False)):
                pixels = bytearray([220, 220, 220] * 1280 * 720)
                for y in range(badge_y, badge_y + 22):
                    for x in range(90, 128):
                        offset = (y * 1280 + x) * 3
                        pixels[offset:offset+3] = bytes((200, 40, 30))
                result = feedback.verify_mlb_selected_game(('Nationals',), ('Tigers',), PpmFrame(1280,720,bytes(pixels)))
                self.assertTrue(result['matched'])
                self.assertEqual(result['live'], expected)

    def test_tigers_hd_picker_confirms_detroit_video_and_starts_playback(self):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-tigers-hd-picker.ppm.gz').read_bytes())
        frame = PpmFrame.parse(raw)
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            # The actual failed cue recognized the labels but returned no
            # selection. Geometry must also work when OCR misses the labels.
            feedback.ocr = None
            picker = feedback.detect_mlb_state(frame, {'state': 'play', 'plugin': {'id': '14'}}, '14')
            self.assertEqual(picker['state'], AppState.MLB_FEED_PICKER)
            self.assertEqual(picker['selection']['selected'], 'video')
            self.assertEqual(picker['selection']['column'], 1)
            self.assertEqual(picker['selection']['layout'], 'hd')
            self.assertEqual(len(picker['selection']['buttons']), 5)
            controller = self.controller(Path(directory), [picker, picker,
                {'state': AppState.FULL_PROGRAM}, {'state': AppState.FULL_PROGRAM}])
            self.assertEqual(controller._wait_for_mlb_playback('14', [])['state'], 'play')
            self.assertEqual(controller.ecp.keys, ['Select'])

    def test_hd_picker_requires_outlines_and_unambiguous_focus(self):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-tigers-hd-picker.ppm.gz').read_bytes())
        frame = PpmFrame.parse(raw)
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            for missing in ('audio_outlines', 'focus'):
                rgb = bytearray(frame.rgb)
                if missing == 'audio_outlines':
                    x0, y0, x1, y1 = 425, 430, 835, 478
                else:
                    x0, y0, x1, y1 = 640, 345, 830, 369
                for y in range(y0, y1):
                    start, end = (y * frame.width + x0) * 3, (y * frame.width + x1) * 3
                    rgb[start:end] = bytes([45]) * (end - start)
                with self.subTest(missing=missing), self.assertRaises(NavigationError):
                    feedback.mlb_feed_picker_selection(PpmFrame(frame.width, frame.height, bytes(rgb)))

    def test_condensed_game_picker_moves_to_broadcast_instead_of_opening_highlights(self):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-condensed-picker.ppm.gz').read_bytes())
        frame = PpmFrame.parse(raw)
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            feedback.ocr = None
            picker = feedback.detect_mlb_state(frame, {'state': 'close', 'plugin': {'id': '14'}}, '14')
            self.assertEqual(picker['state'], AppState.MLB_FEED_PICKER)
            self.assertEqual(picker['selection']['selected'], 'condensed')
            self.assertEqual(picker['selection']['layout'], 'hd-condensed')
            video = {**picker, 'selection': {**picker['selection'], 'selected': 'video'}}
            controller = self.controller(Path(directory), [picker, video,
                {'state': AppState.FULL_PROGRAM}, {'state': AppState.FULL_PROGRAM}])
            self.assertEqual(controller._wait_for_mlb_playback('14', [])['state'], 'play')
            self.assertEqual(controller.ecp.keys, ['Down', 'Select'])
            # Focus alone is insufficient: still require broadcast/audio outlines.
            rgb = bytearray(frame.rgb)
            for y in range(460, 503):
                start, end = (y * frame.width + 425) * 3, (y * frame.width + 835) * 3
                rgb[start:end] = bytes([45]) * (end - start)
            with self.assertRaises(NavigationError):
                feedback.mlb_feed_picker_selection(PpmFrame(frame.width, frame.height, bytes(rgb)))

    def test_delayed_picker_and_live_prompt_precede_two_playback_observations(self):
        observations = [
            {'state': AppState.UNKNOWN},
            {'state': AppState.MLB_FEED_PICKER, 'evidence': 'feed_button_layout', 'selection': {'selected': 'video'}},
            {'state': AppState.MLB_FEED_PICKER, 'evidence': 'feed_button_layout', 'selection': {'selected': 'video'}},
            {'state': AppState.JOIN_LIVE_OR_START_FROM_BEGINNING, 'selection': {'selected': 'catch_up'}},
            {'state': AppState.JOIN_LIVE_OR_START_FROM_BEGINNING, 'selection': {'selected': 'resume'}},
            {'state': AppState.JOIN_LIVE_OR_START_FROM_BEGINNING, 'selection': {'selected': 'watch_live'}},
            {'state': AppState.JOIN_LIVE_OR_START_FROM_BEGINNING, 'selection': {'selected': 'watch_live'}},
            {'state': AppState.FULL_PROGRAM},
            {'state': AppState.FULL_PROGRAM},
        ]
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory), observations)
            events = []
            result = controller._wait_for_mlb_playback('14', events)
            self.assertEqual(result['state'], 'play')
            self.assertEqual(controller.ecp.keys, ['Select', 'Down', 'Down', 'Select'])
            self.assertEqual(len([e for e in events if e['event'] == 'mlb_playback_state']), 9)

    def test_two_choice_postgame_prompt_confirms_watch_live_without_ocr(self):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-two-choice-live-prompt.ppm.gz').read_bytes())
        frame = PpmFrame.parse(raw)
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            feedback.ocr = None
            prompt = feedback.detect_mlb_state(frame, {'state': 'close', 'plugin': {'id': '14'}}, '14')
            self.assertEqual(prompt['state'], AppState.JOIN_LIVE_OR_START_FROM_BEGINNING)
            self.assertEqual(prompt['selection']['selected'], 'watch_live')
            self.assertEqual(prompt['selection']['button_count'], 2)
            controller = self.controller(Path(directory), [prompt,
                {'state': AppState.FULL_PROGRAM}, {'state': AppState.FULL_PROGRAM}])
            self.assertEqual(controller._wait_for_mlb_playback('14', [])['state'], 'play')
            self.assertEqual(controller.ecp.keys, ['Select'])
            rgb = bytearray(frame.rgb)
            for y in range(418, 467):
                start, end = (y * frame.width + 430) * 3, (y * frame.width + 840) * 3
                rgb[start:end] = bytes([45]) * (end - start)
            with self.assertRaises(NavigationError):
                feedback.mlb_live_prompt_selection(PpmFrame(frame.width, frame.height, bytes(rgb)), require_outline=True)

    def test_hd_resume_dialog_from_failed_cue_reaches_watch_live(self):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-hd-resume-prompt.ppm.gz').read_bytes())
        frame = PpmFrame.parse(raw)
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            feedback.ocr = None
            prompt = feedback.detect_mlb_state(frame, {'state': 'play', 'plugin': {'id': '14'}}, '14')
            self.assertEqual(prompt['state'], AppState.JOIN_LIVE_OR_START_FROM_BEGINNING)
            self.assertEqual(prompt['selection']['selected'], 'catch_up')
            self.assertEqual(prompt['selection']['button_count'], 4)
            controller = self.controller(Path(directory), [prompt,
                {**prompt, 'selection': {'selected': 'resume'}},
                {**prompt, 'selection': {'selected': 'watch_live'}},
                {'state': AppState.FULL_PROGRAM}, {'state': AppState.FULL_PROGRAM}])
            self.assertEqual(controller._wait_for_mlb_playback('14', [])['state'], 'play')
            self.assertEqual(controller.ecp.keys, ['Down', 'Down', 'Select'])
            rgb = bytearray(frame.rgb)
            for y in range(487, 538):
                start, end = (y * frame.width + 430) * 3, (y * frame.width + 840) * 3
                rgb[start:end] = bytes([45]) * (end - start)
            with self.assertRaises(NavigationError):
                feedback.mlb_live_prompt_selection(PpmFrame(frame.width, frame.height, bytes(rgb)), require_outline=True)

    def test_hd_resume_dialog_without_catch_up_reaches_watch_live(self):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-hd-resume-no-catch-up-prompt.ppm.gz').read_bytes())
        frame = PpmFrame.parse(raw)
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(fixtures.ControllerTests().config(Path(directory)).feedback)
            feedback.ocr = None
            prompt = feedback.detect_mlb_state(frame, {'state': 'close', 'plugin': {'id': '14'}}, '14')
            self.assertEqual(prompt['state'], AppState.JOIN_LIVE_OR_START_FROM_BEGINNING)
            self.assertEqual(prompt['selection']['selected'], 'resume')
            self.assertEqual(prompt['selection']['button_count'], 3)
            controller = self.controller(Path(directory), [prompt,
                {**prompt, 'selection': {'selected': 'watch_live'}},
                {'state': AppState.FULL_PROGRAM}, {'state': AppState.FULL_PROGRAM}])
            self.assertEqual(controller._wait_for_mlb_playback('14', [])['state'], 'play')
            self.assertEqual(controller.ecp.keys, ['Down', 'Select'])
            rgb = bytearray(frame.rgb)
            for y in range(452, 502):
                start, end = (y * frame.width + 430) * 3, (y * frame.width + 840) * 3
                rgb[start:end] = bytes([45]) * (end - start)
            with self.assertRaises(NavigationError):
                feedback.mlb_live_prompt_selection(PpmFrame(frame.width, frame.height, bytes(rgb)), require_outline=True)

    def test_stale_playback_without_a_verified_playback_action_cannot_succeed(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory), [{'state': AppState.FULL_PROGRAM}])
            with patch('roku_stream.controller.time.monotonic', side_effect=[0, 1, 2, 3, 40]):
                with self.assertRaises(EcpError) as failed:
                    controller._wait_for_mlb_playback('14', [])
            self.assertFalse(failed.exception.details['video_feed_confirmed'])
            self.assertFalse(failed.exception.details['watch_live_confirmed'])
            self.assertEqual(controller.ecp.keys, [])

    def test_archive_request_cannot_select_todays_matching_teams(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            game = {'game_pk': 123, 'title': 'Nationals at Dodgers', 'state': 'Final',
                    'official_date': (date.today() - timedelta(days=1)).isoformat()}
            with self.assertRaisesRegex(NavigationError, 'archive date selection is not verified'):
                controller.play_mlb_game(game)
            self.assertEqual(controller.ecp.keys, [])
            self.assertEqual(controller.operation_status()['phase'], 'error')

    def test_audio_only_player_is_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory), [{'state': AppState.FULL_PROGRAM}], {'video': 'none', 'audio': 'aac'})
            with self.assertRaisesRegex(NavigationError, 'audio without video'):
                controller._wait_for_mlb_playback('14', [])

    @unittest.skipUnless(shutil.which('tesseract'), 'Local OCR is required for end-card recognition')
    def test_ended_broadcast_is_not_verified_as_live_even_when_roku_reports_play(self):
        raw = gzip.decompress((Path(__file__).parent / 'fixtures' / 'mlb-broadcast-ended.ppm.gz').read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            config = fixtures.ControllerTests().config(Path(directory))
            feedback = VisualFeedback(replace(config.feedback, ocr_enabled=True))
            ended = feedback.detect_mlb_state(PpmFrame.parse(raw), {'state': 'play', 'plugin': {'id': '14'}}, '14')
            self.assertEqual(ended['state'], AppState.MLB_BROADCAST_ENDED)
            controller = self.controller(Path(directory), [ended])
            with self.assertRaisesRegex(NavigationError, 'broadcast has ended'):
                controller._wait_for_mlb_playback('14', [])
            self.assertEqual(controller.ecp.keys, [])

    def test_changed_matchup_or_non_live_card_cannot_confirm_game(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            verifier = Mock(return_value={'matched': False})
            self.assertIsNone(controller._confirm_mlb_game({'state': 'Live'}, {'matched': True}, verifier, []))
            verifier.return_value = {'matched': True, 'live': False}
            with self.assertRaisesRegex(NavigationError, 'not confirmed live'):
                controller._confirm_mlb_game({'state': 'Live'}, {'matched': True, 'live': True}, verifier, [])
            self.assertEqual(controller.ecp.keys, [])

    def test_baseball_admission_and_cancellation_share_operation_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = self.controller(Path(directory))
            game = {'game_pk': 123, 'title': 'Nationals at Dodgers', 'preferred_source': {'provider': 'mlb'}}
            with patch('roku_stream.controller.threading.Thread') as thread:
                accepted = controller.submit_baseball_game(game)
                with self.assertRaises(ControlBusyError):
                    controller.submit_play('ESPN')
                controller.cancel_operation(expected_id=accepted['id'])
                thread.call_args.kwargs['target']()
            operation = controller.get_operation(accepted['id'])
            self.assertEqual(operation['phase'], 'cancelled')
            self.assertEqual(operation['game_pk'], 123)
            self.assertTrue(operation['completed_at'])
            self.assertEqual(controller.ecp.keys, [])


if __name__ == '__main__':
    unittest.main()
