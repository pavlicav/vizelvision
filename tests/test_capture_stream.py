import sys
import unittest

from roku_stream.capture_stream import CaptureStream
from roku_stream.errors import CueCancelledError, NavigationError


class CaptureStreamTests(unittest.TestCase):
    def stream(self, script):
        stream = CaptureStream([sys.executable, '-u', '-c', script])
        self.addCleanup(stream.close)
        return stream

    def test_continuous_reader_discards_old_frames_and_keeps_same_process(self):
        stream = self.stream(
            "import sys,time\n"
            "for n in range(200):\n"
            " sys.stdout.buffer.write(b'P6\\n1 1\\n255\\n'+bytes([n])*3)\n"
            " sys.stdout.buffer.flush()\n"
            " time.sleep(.01)\n")
        first = stream.next_frame(3, lambda _: None)
        second = stream.next_frame(3, lambda _: None)
        self.assertGreaterEqual(second.rgb[0], first.rgb[0] + 3)
        self.assertIsNone(stream.process.poll())

    def test_stalled_stream_cannot_return_cached_frame(self):
        stream = self.stream(
            "import sys,time\n"
            "sys.stdout.buffer.write(b'P6\\n1 1\\n255\\nabc')\n"
            "sys.stdout.buffer.flush()\n"
            "time.sleep(30)\n")
        with self.assertRaisesRegex(NavigationError, 'timed out'):
            stream.next_frame(.2, lambda _: None)

    def test_truncated_frame_fails(self):
        stream = self.stream("import sys;sys.stdout.buffer.write(b'P6\\n1 1\\n255\\na')")
        with self.assertRaises(NavigationError):
            stream.next_frame(3, lambda _: None)

    def test_cancelled_wait_leaves_capture_running(self):
        stream = self.stream('import time;time.sleep(30)')
        def cancel(_):
            raise CueCancelledError('stop')
        with self.assertRaises(CueCancelledError):
            stream.next_frame(3, cancel)
        self.assertIsNone(stream.process.poll())

    def test_stderr_is_drained_and_bounded_without_blocking_frames(self):
        stream = self.stream(
            "import sys,time\n"
            "sys.stderr.write('x'*200000+'capture diagnostic\\n');sys.stderr.flush()\n"
            "for n in range(100):\n"
            " sys.stdout.buffer.write(b'P6\\n1 1\\n255\\nabc');sys.stdout.buffer.flush();time.sleep(.01)\n")
        stream.next_frame(3, lambda _: None)
        status = stream.status()
        self.assertIn('capture diagnostic', status['ffmpeg_stderr'])
        self.assertLessEqual(len(status['ffmpeg_stderr']), 8192)
        self.assertLess(status['frame_age_seconds'], 1)
        self.assertGreater(status['frames'], 0)
