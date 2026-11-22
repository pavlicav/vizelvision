"""The low rendition's taps and its restarts, without GStreamer (master_low.py)."""
import types
import unittest

from roku_stream.master_low import LowRendition


class FakeGst:
    CLOCK_TIME_NONE = 2 ** 64 - 1
    Format = types.SimpleNamespace(TIME="time")


class Buffer:
    def __init__(self, pts):
        self.pts, self.dts = pts, pts

    def copy(self):
        return Buffer(self.pts)


class Caps:
    def __init__(self, text):
        self.text = text

    def is_equal(self, other):
        return self.text == other.text


class Sample:
    def __init__(self, pts, offset=0, caps=None):
        self.buffer, self.offset, self.caps = Buffer(pts), offset, caps

    def get_buffer(self):
        return self.buffer

    def get_caps(self):
        return self.caps

    def get_segment(self):
        offset = self.offset
        return types.SimpleNamespace(
            to_running_time=lambda fmt, pts: FakeGst.CLOCK_TIME_NONE if pts < offset else pts - offset)


class Source:
    def __init__(self):
        self.pushed, self.props = [], {}

    def emit(self, signal, buffer):
        assert signal == "push-buffer"
        self.pushed.append(buffer)

    def set_property(self, name, value):
        self.props[name] = value


def rendition():
    return LowRendition(FakeGst(), "rtsp://127.0.0.1:18554/master_low", width=960, height=540, fps=30,
                        video_caps="video/x-raw,framerate=30/1", encoder="nvh264enc bitrate=2000 gop-size=60")


class PushTests(unittest.TestCase):
    def setUp(self):
        self.low = rendition()
        self.low.sources = {"video": Source(), "audio": Source()}

    def test_a_buffer_already_on_running_time_is_passed_on_as_is(self):
        sample = Sample(5_000)
        self.low.push("video", sample)
        self.assertIs(self.low.sources["video"].pushed[0], sample.buffer)

    def test_an_offset_buffer_is_restamped_on_a_copy(self):
        sample = Sample(3_600_000_005_000, offset=3_600_000_000_000)   # an encoder's 1000 h offset
        self.low.push("audio", sample)
        pushed = self.low.sources["audio"].pushed[0]
        self.assertIsNot(pushed, sample.buffer)
        self.assertEqual((pushed.pts, pushed.dts), (5_000, FakeGst.CLOCK_TIME_NONE))
        self.assertEqual(sample.buffer.pts, 3_600_000_005_000)        # the full output's buffer is untouched

    def test_a_buffer_before_its_segment_is_dropped(self):
        self.low.push("video", Sample(1, offset=10))
        self.assertEqual(self.low.sources["video"].pushed, [])

    def test_audio_caps_follow_the_aac_and_are_kept_while_stopped(self):
        aac = Caps("audio/mpeg,mpegversion=4")
        self.low.push("audio", Sample(1, caps=aac))
        self.assertIs(self.low.sources["audio"].props["caps"], aac)
        self.low.sources["audio"].props.clear()
        self.low.push("audio", Sample(2, caps=Caps("audio/mpeg,mpegversion=4")))
        self.assertEqual(self.low.sources["audio"].props, {})             # same caps: not set again
        self.low.sources = None
        other = Caps("audio/mpeg,rate=44100")
        self.low.push("audio", Sample(3, caps=other))                     # between pipelines
        self.assertIs(self.low.audio_caps, other)


class RestartTests(unittest.TestCase):
    def test_failures_back_off_and_close_stops(self):
        low = rendition()
        waits, reasons = [], iter(["Could not read from resource.", "stalled", "Could not read from resource."])
        low._publish = lambda: next(reasons, "closed")

        def wait(seconds):
            waits.append(seconds)
            if len(waits) == 3:
                return True    # close() during the third wait
            return False
        low.stopping = types.SimpleNamespace(is_set=lambda: len(waits) >= 3, wait=wait, set=lambda: None)
        with self.assertLogs("roku_stream.master_low", "WARNING") as logs:
            low._run()
        self.assertEqual(waits, [5.0, 10.0, 20.0])
        self.assertEqual(low.status()["restarts"], 3)
        self.assertEqual(low.status()["state"], "stopped")
        self.assertIn("Low rendition stopped (stalled); retrying in 10 s", logs.output[1])

    def test_status_before_any_output(self):
        status = rendition().status()
        self.assertEqual((status["state"], status["buffers"], status["age_seconds"]), ("starting", {"video": 0, "audio": 0}, None))

    def test_the_launch_line_scales_encodes_and_publishes_both_tracks(self):
        description = rendition().description
        for piece in ("videoscale ! video/x-raw,width=960,height=540", "nvh264enc bitrate=2000 gop-size=60",
                      "publisher.sink_0", "publisher.sink_1", "rtspclientsink name=publisher protocols=tcp",
                      'caps="video/x-raw,framerate=30/1"', "leaky-type=downstream"):
            self.assertIn(piece, description)


if __name__ == "__main__":
    unittest.main()
