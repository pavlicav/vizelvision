"""Ad replacement uses the same original timeline as the delayed programme."""
from array import array
from collections import deque
import threading
from types import SimpleNamespace
import unittest

from roku_stream.master_media import MasterMedia

SECOND = 1_000_000_000


class AudioBuffer:
    def __init__(self, data):
        self.data = data

    def get_size(self):
        return len(self.data)

    def extract_dup(self, offset, size):
        return self.data[offset:offset + size]

    new_wrapped = staticmethod(lambda data: AudioBuffer(data))


class ProgrammeAudioTests(unittest.TestCase):
    def setUp(self):
        self.output = MasterMedia.__new__(MasterMedia)
        self.output.gst = SimpleNamespace(Buffer=AudioBuffer, SECOND=SECOND, CLOCK_TIME_NONE=-1)
        self.output.route_lock = threading.Lock()
        self.output.radio_history = deque()
        self.output.admute_conf = {'mode': 'on', 'sound': 'radio', 'radio_db': 6}
        self.sent = []
        self.output.pipeline = SimpleNamespace(get_by_name=lambda name: SimpleNamespace(
            emit=lambda signal, buffer: self.sent.append((name, buffer))))

    def audio(self, value, frames=480):
        return array('f', [value] * (frames * 2)).tobytes()

    def test_radio_crossfade_uses_source_gain_and_one_delayed_timestamp(self):
        self.output.radio_history.append((2 * SECOND, self.audio(.1)))
        for gain in (0, .5, 1):
            with self.subTest(gain=gain):
                evaluated = []
                def gain_at(pts):
                    evaluated.append(pts)
                    return gain
                tap = SimpleNamespace(gain=gain_at)
                self.output.release_programme('audio', AudioBuffer(self.audio(.2)),
                    8 * SECOND, 10_000_000, 2 * SECOND, (tap, 3 * SECOND, 'source'))
                name, buffer = self.sent[-1]
                self.assertEqual(name, 'delayed_audio')
                self.assertEqual((buffer.pts, buffer.dts, buffer.duration), (8 * SECOND, -1, 10_000_000))
                self.assertTrue(all(5 * SECOND <= p <= 5 * SECOND + 11_000_000 for p in evaluated))
                expected = .2 * gain + .1 * (1 - gain) * 10 ** (6 / 20)
                samples = array('f')
                samples.frombytes(buffer.data)
                self.assertTrue(all(abs(sample - expected) < 1e-6 for sample in samples))

    def test_radio_history_copies_the_matching_window_and_fills_gaps_with_silence(self):
        self.output.radio_history.extend([
            (SECOND, self.audio(.1)), (SECOND + 10_000_000, self.audio(.2))])
        samples = array('f')
        samples.frombytes(self.output._radio_at(SECOND + 5_000_000, 480 * 3 * 8))
        self.assertTrue(all(abs(x - .1) < 1e-6 for x in samples[:480]))
        self.assertTrue(all(abs(x - .2) < 1e-6 for x in samples[480:1440]))
        self.assertEqual(set(samples[1440:]), {0.0})

    def test_silent_mode_and_unavailable_radio_keep_muted_audio_silent(self):
        for sound in ('silence', 'radio'):
            with self.subTest(sound=sound):
                self.output.admute_conf['sound'] = sound
                self.output.release_programme('audio', AudioBuffer(self.audio(.2)),
                    8 * SECOND, 10_000_000, 2 * SECOND,
                    (SimpleNamespace(gain=lambda pts: 0), 0, 'source'))
                self.assertEqual(self.sent[-1][1].data, bytes(480 * 8))


if __name__ == '__main__':
    unittest.main()
