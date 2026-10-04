import unittest
from types import SimpleNamespace

from roku_stream.programme_delay import ProgrammeDelay, SECOND


class Buffer:
    duration = 100_000_000

    def copy_deep(self):
        return Buffer()

    copy = copy_deep

    def get_size(self):
        return 100


class ProgrammeDelayTests(unittest.TestCase):
    def delay(self):
        return ProgrammeDelay(SimpleNamespace(fps=10, gst=SimpleNamespace(CLOCK_TIME_NONE=-1)))

    def test_lookahead_is_maximum_not_sum_and_never_rewinds(self):
        delay = self.delay()
        delay.require(4)  # Ad lookahead plus its existing margin.
        delay.require(6)  # Whisper.
        self.assertEqual(delay.delay_ns, 6 * SECOND)
        delay.require(9)
        delay.require(0)
        self.assertEqual(delay.delay_ns, 9 * SECOND)

    def test_both_tracks_keep_original_time_and_share_the_same_delay(self):
        delay = self.delay()
        delay.require(6)
        for kind in ('audio', 'video'):
            delay.put(kind, Buffer(), SECOND, 'source')
            packet = delay._next(kind, 7 * SECOND)
            self.assertEqual(packet[1:], (7 * SECOND, 100_000_000, SECOND, 'source'))

    def test_normal_decoder_latency_does_not_generate_fill_or_drop_real_frames(self):
        delay = self.delay()
        delay.put('video', Buffer(), 0, 'source')
        self.assertEqual(delay._next('video', 200_000_000)[1], 0)
        self.assertIsNone(delay._next('video', 205_000_000))
        delay.put('video', Buffer(), 100_000_000, 'source')
        self.assertEqual(delay._next('video', 300_000_000)[1], 100_000_000)
        self.assertEqual(delay.dropped, 0)

    def test_fill_stops_at_the_first_delayed_frame_without_overlap(self):
        delay = self.delay()
        delay.require(6)
        delay.put('video', Buffer(), 0, 'source')
        for tick in range(61):
            packet = delay._next('video', tick * 100_000_000)
            if packet and packet[3] is not None:
                self.assertEqual(packet[1], 6 * SECOND)
                break
        else:
            self.fail('Real media was never released')
        self.assertEqual(delay.dropped, 0)

    def test_hard_memory_bound_keeps_recent_media(self):
        delay = self.delay()
        delay.MAX_BYTES = 250
        delay.require(6)
        for index in range(10):
            delay.put('video', Buffer(), index * 100_000_000, 'source')
        self.assertLessEqual(delay.bytes, 250)
        self.assertEqual(delay.dropped, 8)


if __name__ == '__main__':
    unittest.main()
