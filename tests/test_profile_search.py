import json
import random
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from roku_stream.errors import NavigationError
from roku_stream.feedback import PpmFrame, VisualFeedback
from roku_stream.controller import RokuStreamController
from roku_stream.states import AppState

from tests import test_controller
from tests.test_controller import FakeEcp, FakeFeedback

WIDTH, HEIGHT = 320, 180


def chooser(tile_x, *, ring=True):
    """A dark chooser with one textured 'Vivian' tile whose left edge is at tile_x."""
    rng = random.Random(7)
    texture = [[rng.randrange(40, 220) for _ in range(40)] for _ in range(50)]
    rgb = bytearray(b'\x10' * (WIDTH * HEIGHT * 3))
    for y in range(int(HEIGHT * .37), int(HEIGHT * .70)):
        for x in range(tile_x, tile_x + 40):
            value = texture[(y - int(HEIGHT * .37)) % 50][x - tile_x]
            if not ring and (x - tile_x < 4 or x - tile_x > 35):
                value = 16  # Unfocused: no bright focus ring around the tile.
            elif ring and (x - tile_x < 4 or x - tile_x > 35):
                value = 250
            offset = (y * WIDTH + x) * 3
            rgb[offset:offset + 3] = bytes((value,)) * 3
    return PpmFrame(WIDTH, HEIGHT, bytes(rgb))


class ProfileSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.feedback = object.__new__(VisualFeedback)
        self.feedback.config = SimpleNamespace(template_dir=Path(self.tmp.name), profile_template='profile.json',
                                               template_difference_threshold=12.0)
        calibrated = chooser(int(WIDTH * .13))  # The position used when the template was saved.
        template = self.feedback.selected_first_profile(calibrated)
        Path(self.tmp.name, 'profile.json').write_text(json.dumps(
            {'width': template.width, 'height': template.height, 'pixels': list(template.pixels)}))

    def test_search_scores_equal_the_fixed_downsample(self):
        frame = chooser(90)
        templates = self.feedback._template_variants(json.loads(Path(self.tmp.name, 'profile.json').read_text()))
        x0, y0, x1, y1 = self.feedback._profile_box(frame)
        score, position = self.feedback._search_profile(frame, templates)
        direct = min(t.difference(self.feedback._downsample(frame, position, y0, position + x1 - x0, y1,
                                                            width=40, height=40)) for t in templates)
        self.assertEqual(score, direct)

    def test_calibrated_position_still_matches_without_search(self):
        result = self.feedback.verify_vivian_profile(chooser(int(WIDTH * .13)), search=False)
        self.assertEqual(result['difference'], 0)

    def test_tile_moved_by_a_new_family_member_is_found(self):
        moved = chooser(int(WIDTH * .05))
        with self.assertRaises(NavigationError):
            self.feedback.verify_vivian_profile(moved, search=False)
        result = self.feedback.verify_vivian_profile(moved)
        self.assertTrue(result['matched'])
        self.assertAlmostEqual(result['position'], .05, delta=.02)
        self.assertTrue(self.feedback.verify_vivian_profile(chooser(int(WIDTH * .30)))['matched'])

    def test_unfocused_tile_is_rejected_anywhere(self):
        for x in (int(WIDTH * .05), int(WIDTH * .13)):
            with self.subTest(x=x), self.assertRaises(NavigationError):
                self.feedback.verify_vivian_profile(chooser(x, ring=False))


class ChooserBoundTests(unittest.TestCase):
    def controller(self, directory, feedback):
        return RokuStreamController(test_controller.ControllerTests.config(None, Path(directory)), ecp=self.ecp,
                                    feedback=feedback, sleeper=lambda _: None)

    def test_unrecognized_chooser_fails_fast_instead_of_pressing_left_for_minutes(self):
        self.ecp = FakeEcp()

        class Unverified(FakeFeedback):
            def detect_youtube_tv_state(self, frame, channels, media_player):
                return {'state': AppState.YOUTUBE_TV_USER_SELECT, 'evidence': 'ocr_profile_chooser',
                        'profile_verified': False, 'verification': {'difference': 44.0}}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(NavigationError, 'calibrate-profile') as raised:
                self.controller(directory, Unverified())._drive_to_live_guide('195316', [])
        self.assertEqual(self.ecp.keys, ['Left'] * 3)
        self.assertEqual(raised.exception.details['profile_verification'], {'difference': 44.0})

    def test_found_profile_is_selected(self):
        self.ecp = FakeEcp()
        feedback = FakeFeedback()
        feedback.states = [AppState.YOUTUBE_TV_USER_SELECT, AppState.LIVE_GUIDE]
        with tempfile.TemporaryDirectory() as directory:
            observed = self.controller(directory, feedback)._drive_to_live_guide('195316', [])
        self.assertEqual(observed['state'], AppState.LIVE_GUIDE)
        self.assertEqual(self.ecp.keys, ['Select'])


if __name__ == '__main__':
    unittest.main()
