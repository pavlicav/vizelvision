import random
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from roku_stream.errors import RokuStreamError
from roku_stream.feed_match import (
    WIDTH, HEIGHT, SAMPLE_COUNT, _decode, capture_return, compare_frames,
)


def picture(phase=0, *, brightness=0, noise=0, letterbox=False):
    """Moving, nonuniform content with analog distortion, independent of matcher."""
    rng = random.Random(phase + 42)
    frame = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            yy = (y-15)*HEIGHT//90 if letterbox else y
            if not 0 <= yy < HEIGHT:
                value = 0
            else:
                value = 35 + (x//32)*14 + (yy//24)*13
                if (x-phase*13) % WIDTH < 35 and 20 <= yy < 95:
                    value = 230
                value += brightness + rng.randint(-noise, noise)
            frame.extend([min(255, max(0, value))]*3)
    return bytes(frame)


class FeedComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.master = [picture(i) for i in range(24)]

    def test_matching_analog_picture_with_delay_brightness_and_noise(self):
        cable = [picture(i, brightness=12, noise=20) for i in range(-4, 20)]
        result = compare_frames(cable, self.master)
        self.assertTrue(result['matches_master'], result)
        self.assertEqual(result['sample_offset_seconds'], 2)

    def test_letterboxed_picture_matches(self):
        result = compare_frames([picture(i, letterbox=True) for i in range(24)], self.master)
        self.assertTrue(result['matches_master'], result)
        self.assertEqual(result['geometry'], 'letterbox')

    def test_snow_is_not_a_healthy_picture(self):
        rng = random.Random(70)
        snow = [rng.randbytes(WIDTH*HEIGHT*3) for _ in range(24)]
        self.assertFalse(compare_frames(snow, self.master)['matches_master'])

    def test_unrelated_detailed_video_does_not_match(self):
        # Mirroring preserves contrast, color, detail, and motion, not content.
        other = [b''.join(frame[y*WIDTH*3:(y+1)*WIDTH*3][::-1]
                          for y in range(HEIGHT)) for frame in self.master]
        self.assertFalse(compare_frames(other, self.master)['matches_master'])

    def test_blank_and_identical_snow_are_not_evidence_of_a_match(self):
        for frame in (bytes(WIDTH*HEIGHT*3), random.Random(1).randbytes(WIDTH*HEIGHT*3)):
            with self.subTest(blank=not any(frame)):
                self.assertFalse(compare_frames([frame]*20, [frame]*20)['matches_master'])

    def test_frozen_return_against_moving_master_fails(self):
        self.assertFalse(compare_frames([self.master[0]]*24, self.master)['matches_master'])

    def test_motion_check_rejects_freeze_even_when_background_still_matches(self):
        frames = []
        for i in range(20):
            frame = bytearray(self.master[0])
            for y in range(35, 55):
                for x in range(65, 85):
                    pos = (y*WIDTH+x)*3
                    frame[pos:pos+3] = bytes([160 if i % 2 else 80])*3
            frames.append(bytes(frame))
        result = compare_frames([frames[0]]*20, frames)
        self.assertGreaterEqual(result['match_fraction'], .8)
        self.assertFalse(result['motion_consistent'])
        self.assertFalse(result['matches_master'])

    def test_modest_overscan_matches(self):
        cable = []
        for frame in self.master[:20]:
            cropped = bytearray()
            for y in range(HEIGHT):
                for x in range(WIDTH):
                    pos = ((6+y*108//HEIGHT)*WIDTH + 8+x*144//WIDTH)*3
                    cropped.extend(frame[pos:pos+3])
            cable.append(bytes(cropped))
        result = compare_frames(cable, self.master[:20])
        self.assertTrue(result['matches_master'], result)

    def test_still_programming_that_matches_can_pass(self):
        self.assertTrue(compare_frames([self.master[0]]*20, [self.master[0]]*20)['matches_master'])

    def test_single_matching_frame_cannot_make_wrong_programming_pass(self):
        cable = [self.master[0]] + [bytes([127])*(WIDTH*HEIGHT*3)]*23
        self.assertFalse(compare_frames(cable, self.master)['matches_master'])

    def test_match_earlier_in_window_cannot_hide_static_at_the_end(self):
        rng = random.Random(70)
        cable = self.master[:22] + [rng.randbytes(WIDTH*HEIGHT*3) for _ in range(2)]
        result = compare_frames(cable, self.master)
        self.assertFalse(result['matches_master'])
        self.assertFalse(result['latest_samples_match'])

    def test_short_capture_is_inconclusive(self):
        self.assertIsNone(compare_frames(self.master[:2], self.master)['matches_master'])

    def test_missing_reference_retains_cable_image_without_healthy_result(self):
        def decode(url):
            if url == 'master':
                raise RokuStreamError('Reference unavailable')
            return self.master
        with patch('roku_stream.feed_match._decode', side_effect=decode):
            result = capture_return('cable', 'master')
        self.assertIsNone(result['comparison']['matches_master'])
        self.assertEqual(result['comparison']['reason'], 'reference_unavailable')
        self.assertTrue(result['image_base64'].startswith('iVBOR'))

    def test_capture_uses_both_streams_and_exposes_comparison(self):
        with patch('roku_stream.feed_match._decode', return_value=[self.master[0]]*20) as decode:
            result = capture_return('cable', 'master')
        self.assertEqual({c.args[0] for c in decode.call_args_list}, {'cable', 'master'})
        self.assertTrue(result['comparison']['matches_master'])

    def test_decoder_requires_complete_frames_and_has_bounded_timeout(self):
        raw = self.master[0]*SAMPLE_COUNT
        with patch('subprocess.run', return_value=SimpleNamespace(stdout=raw)) as run:
            self.assertEqual(len(_decode('test')), SAMPLE_COUNT)
        self.assertEqual(run.call_args.kwargs['timeout'], 55)
        with patch('subprocess.run', return_value=SimpleNamespace(stdout=raw[:-1])):
            with self.assertRaises(RokuStreamError):
                _decode('test')
        with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('ffmpeg', 55)):
            with self.assertRaises(RokuStreamError):
                _decode('test')


if __name__ == '__main__':
    unittest.main()
