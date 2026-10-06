"""Inputs on air ride out stalls instead of failing.

On 2026-10-01 at 16:50 the whole host stalled for a few seconds and a Jeopardy rerun was
failed off the air 141 s in, because its frames reached master more than a second late.
On 2026-10-04 the Colts at Commanders game was failed off the air eight times in 25 minutes,
from YouTube TV and then FOX 5 over the antenna, although the picture looked fine: a
second without audio cut to the test card, and a 43 ms audio rewind failed the feed
outright. Live inputs on air now drop late and repeated frames and hold their picture.
These drive DecodedInput._sample with a fake clock and fake GStreamer objects.
"""
import collections
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from roku_stream.master import MasterStreamError
from roku_stream.master_media import CLOCK_WINDOW, DRIFTED, DecodedInput, FileInput

SECOND, FRAME = 1_000_000_000, 33_333_333


class Buffer:
    def __init__(self, pts, duration=FRAME):
        self.pts, self.dts, self.duration = pts, None, duration

    def copy(self):
        return Buffer(self.pts, self.duration)


class FakeGst:
    SECOND, MSECOND, CLOCK_TIME_NONE = SECOND, 1_000_000, 2 ** 64 - 1
    FlowReturn = SimpleNamespace(OK='ok')
    Format = SimpleNamespace(TIME='time')
    Buffer = SimpleNamespace(new_wrapped=lambda data: Buffer(None))


def sink(pts, duration=FRAME):
    sample = SimpleNamespace(get_buffer=lambda: Buffer(pts, duration),
                             get_segment=lambda: SimpleNamespace(to_running_time=lambda fmt, value: value))
    return SimpleNamespace(emit=lambda name: sample)


def make(kind, clock, active=True, started=True):
    feed = object.__new__(kind)
    feed.started = started
    feed.output = SimpleNamespace(active=1 if active else 0, running_time=lambda: clock[0], fps=30)
    feed.slot, feed.gst, feed.lock = 1, FakeGst, threading.Lock()
    feed.closed, feed.error, feed.anchor, feed.floor, feed.resyncs = False, None, None, 0, 0
    feed.resync_times = collections.deque()
    feed.last = {k: {'pts': None, 'at': 0., 'count': 0, 'end': None} for k in ('video', 'audio')}
    feed.late = {k: 0 for k in feed.last}
    feed.last_frame = None
    feed.sources = {k: Mock(**{'emit.return_value': 'ok'}) for k in feed.last}
    feed.riding, feed.filler, feed.reanchors = False, None, 0
    feed.late_since = {k: None for k in feed.last}
    feed.arrived = {k: 0. for k in feed.last}
    feed.filled = {k: 0 for k in feed.last}
    feed.overlap = {k: 0 for k in feed.last}
    return feed


def play(feed, clock, start, frames, *, clock_step=FRAME, kind='video'):
    """Delivers frames from content time start; the master clock moves clock_step a frame."""
    for n in range(frames):
        feed._sample(sink(start + n * FRAME), kind)
        clock[0] += clock_step


def pushed(feed, kind='video'):
    return [c.args[1].pts for c in feed.sources[kind].emit.call_args_list]


def in_step(feed, clock, start, frames, *, video=0):
    """Audio on time from content time start; video (unless None) video seconds behind it."""
    for n in range(frames):
        feed._sample(sink(start + n * FRAME), 'audio')
        if video is not None:
            feed._sample(sink(start + n * FRAME - video), 'video')
        clock[0] += FRAME


def backdate(feed, kind, seconds, content=0):
    """kind has been late for seconds, and its content moved on content ns meanwhile."""
    started, mapped = feed.late_since[kind]
    feed.late_since[kind] = (started - seconds, mapped - content)


class StallTests(unittest.TestCase):
    def test_a_file_on_air_drops_late_frames_and_carries_on(self):
        clock = [600 * SECOND]
        feed = make(FileInput, clock)
        play(feed, clock, 0, 30)
        pushed = feed.sources['video'].emit.call_count
        self.assertEqual((pushed, feed.error), (30, None))
        clock[0] += 3 * SECOND  # the host stalls: the next frames are three seconds late
        play(feed, clock, 30 * FRAME, 60, clock_step=0)  # the decoder catches up in a burst
        self.assertIsNone(feed.error)
        self.assertGreater(feed.late['video'], 0)
        self.assertEqual(feed.sources['video'].emit.call_count - pushed, 60 - feed.late['video'])
        play(feed, clock, 90 * FRAME, 30)  # back in step with master: no "timestamps changed"
        self.assertIsNone(feed.error)
        self.assertEqual(feed.sources['video'].emit.call_count, pushed + 60 - feed.late['video'] + 30)

    def test_a_live_input_on_air_drops_late_frames_and_carries_on(self):
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock)
        play(feed, clock, 0, 30)
        anchor = feed.anchor
        clock[0] += 3 * SECOND
        play(feed, clock, 30 * FRAME, 1)
        self.assertEqual((feed.error, feed.late['video'], feed.anchor), (None, 1, anchor))
        # The source delivers its backlog and catches up with the clock: on time again, it airs.
        play(feed, clock, 31 * FRAME, 89, clock_step=0)
        play(feed, clock, 120 * FRAME, 10)
        self.assertIsNone(feed.error)
        self.assertEqual(len(pushed(feed)), 30 + 90 + 10 - feed.late['video'])

    def test_a_small_audio_rewind_on_air_is_dropped_not_failed(self):
        # YouTube TV's NFL Network, 10:05:55: "Input audio timestamps changed (delta_ms=-42.666666)".
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock)
        chunk = 21_333_333
        for n in range(40):
            feed._sample(sink(n * chunk, chunk), 'audio')
            clock[0] += chunk
        for n in (37, 38, 39, 40):  # two chunks again, 42.67 ms back
            feed._sample(sink(n * chunk, chunk), 'audio')
        self.assertEqual((feed.error, feed.overlap['audio']), (None, 3))
        self.assertEqual(len(pushed(feed, 'audio')), 41)

    def test_small_audio_rewinds_while_preparing_are_dropped_not_re_anchored_until_it_fails(self):
        # The Roku feed going back on, 2026-10-04 13:39:22 and 13:41:24: "Input audio
        # timestamps changed (delta_ms=-12.03 / -42.67)" 5 s into preparation, every time.
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock, active=False)
        chunk = 21_333_333
        n = 0
        for _ in range(DecodedInput.MAX_RESYNCS + 3):
            for _ in range(10):
                feed._sample(sink(n * chunk, chunk), 'audio')
                feed._sample(sink(n * chunk, FRAME), 'video')
                clock[0] += chunk
                n += 1
            feed._sample(sink((n - 2) * chunk, chunk), 'audio')  # 42.67 ms back
            feed._sample(sink((n - 1) * chunk, chunk), 'audio')  # the same again
        self.assertEqual((feed.error, feed.resyncs, feed.overlap['audio']), (None, 0, 2 * (DecodedInput.MAX_RESYNCS + 3)))
        self.assertEqual(len(pushed(feed, 'audio')), n)

    def test_a_rewind_over_a_second_while_preparing_still_re_anchors(self):
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock, active=False)
        play(feed, clock, 0, 60)
        play(feed, clock, 60 * FRAME - 2 * SECOND, 1)
        self.assertEqual((feed.error, feed.resyncs, feed.overlap['video']), (None, 1, 0))

    def test_a_live_rewind_over_a_second_is_late_but_a_jump_ahead_still_fails(self):
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock)
        play(feed, clock, 0, 60)
        play(feed, clock, 60 * FRAME - 2 * SECOND, 1)
        self.assertEqual((feed.error, feed.late['video']), (None, 1))
        play(feed, clock, 61 * FRAME + 3 * SECOND, 1)  # content three seconds ahead
        self.assertEqual(feed.error, CLOCK_WINDOW)

    def test_live_inputs_off_air_re_anchor_a_few_times_a_minute_not_a_few_times_ever(self):
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock, active=False)
        feed.resync_times.extend([time.monotonic() - 120] * DecodedInput.MAX_RESYNCS)  # hours ago, say
        play(feed, clock, 0, 30)
        clock[0] += 3 * SECOND
        play(feed, clock, 30 * FRAME, 5)
        self.assertEqual((feed.error, feed.resyncs), (None, 1))
        feed.resync_times.extend([time.monotonic()] * DecodedInput.MAX_RESYNCS)
        clock[0] += 3 * SECOND
        play(feed, clock, 35 * FRAME, 1)
        self.assertEqual(feed.error, CLOCK_WINDOW)

    def test_a_stalled_live_input_holds_its_picture_until_media_arrives_again(self):
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock)
        play(feed, clock, 0, 30)
        feed.last_frame = Buffer(0)
        feed.arrived = {k: time.monotonic() - 1 for k in feed.arrived}
        clock[0] += SECOND  # a second with nothing from the source
        self.assertTrue(feed.ride_out(True))
        time.sleep(.1)
        with feed.lock:
            video, audio = pushed(feed), pushed(feed, 'audio')
        self.assertGreater(feed.filled['video'], 10)
        self.assertGreater(feed.filled['audio'], 10)
        self.assertEqual(video, sorted(video))
        self.assertGreaterEqual(video[-1], clock[0] + 100 * FakeGst.MSECOND - FRAME)
        self.assertGreaterEqual(video[30], clock[0] - 400 * FakeGst.MSECOND)
        # The source comes back with the frames it did not deliver: late, so dropped; the picture
        # stays held while they go on, then the input re-anchors past it and airs again.
        for n in range(30, 40):
            feed._sample(sink(n * FRAME), 'video')
        self.assertEqual((feed.error, feed.anchor is not None), (None, True))
        feed.late_since['video'] = (time.monotonic() - DecodedInput.LATE_REANCHOR, feed.late_since['video'][1])
        held = feed.last['video']['end']
        feed._sample(sink(40 * FRAME), 'video')
        self.assertEqual((feed.error, feed.reanchors), (None, 1))
        self.assertGreater(pushed(feed)[-1], held)
        feed.ride_out(False)
        self.assertFalse(feed.riding)

    def test_video_left_behind_its_audio_fails_at_once_instead_of_holding(self):
        # 2026-10-04 12:10:53, YouTube TV's NFL Network: the video came out over a second behind
        # the clock while its audio stayed on time. Every frame was dropped as late and the
        # picture was held 8 s; recovery could not anchor both tracks and failed in 0.1 s.
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock)
        in_step(feed, clock, 0, 30)
        in_step(feed, clock, 30 * FRAME, 45, video=None)  # the video stops for 1.5 s; audio goes on
        feed.riding = True  # the worker holds the picture
        in_step(feed, clock, 75 * FRAME, 1, video=45 * FRAME)  # it comes back, 1.5 s behind
        self.assertEqual((feed.error, feed.late['video']), (None, 1))
        backdate(feed, 'video', DecodedInput.LATE_REANCHOR, content=int(1.5 * SECOND))  # real time
        in_step(feed, clock, 76 * FRAME, 1, video=45 * FRAME)
        self.assertEqual(feed.error, DRIFTED.format('video', 'audio'))
        self.assertEqual(feed.reanchors, 0)

    def test_a_backlog_catching_up_behind_on_time_audio_is_left_to_catch_up(self):
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock)
        in_step(feed, clock, 0, 30)
        anchor = feed.anchor
        in_step(feed, clock, 30 * FRAME, 45, video=None)
        feed.riding = True
        in_step(feed, clock, 75 * FRAME, 1, video=45 * FRAME)
        backdate(feed, 'video', DecodedInput.LATE_REANCHOR, content=3 * SECOND)  # twice real time
        in_step(feed, clock, 76 * FRAME, 1, video=45 * FRAME)
        # Neither failed nor re-anchored (that would put the audio a second ahead): still dropping.
        self.assertEqual((feed.error, feed.reanchors, feed.anchor), (None, 0, anchor))
        self.assertEqual(feed.late['video'], 2)
        in_step(feed, clock, 77 * FRAME, 10)  # caught up: both tracks air
        self.assertIsNone(feed.error)
        self.assertEqual(len(pushed(feed)), 30 + 10)

    def test_one_tracks_on_time_frames_do_not_reset_the_others_lateness(self):
        clock = [600 * SECOND]
        feed = make(DecodedInput, clock)
        in_step(feed, clock, 0, 30)
        in_step(feed, clock, 30 * FRAME, 45, video=None)
        in_step(feed, clock, 75 * FRAME, 5, video=45 * FRAME)
        self.assertIsNone(feed.late_since['audio'])
        self.assertIsNotNone(feed.late_since['video'])

    def test_frames_ahead_of_the_clock_still_fail(self):
        clock = [600 * SECOND]
        feed = make(FileInput, clock)
        play(feed, clock, 0, 30)
        play(feed, clock, 30 * FRAME + 3 * SECOND, 1)  # content jumps three seconds ahead
        self.assertEqual(feed.error, CLOCK_WINDOW)

    def test_a_playing_file_cut_away_for_recovery_keeps_its_timeline(self):
        # After a second without frames the worker cuts to the test card, so the late frames
        # find the file off air. Re-anchoring on them is what failed the rerun.
        clock = [600 * SECOND]
        feed = make(FileInput, clock, active=False)
        play(feed, clock, 0, 30)
        anchor = feed.anchor
        clock[0] += 3 * SECOND
        play(feed, clock, 30 * FRAME, 60, clock_step=0)
        self.assertEqual((feed.error, feed.resyncs, feed.anchor), (None, 0, anchor))
        self.assertGreater(feed.late['video'], 0)

    def test_a_file_being_prepared_still_reanchors(self):
        clock = [600 * SECOND]
        feed = make(FileInput, clock, active=False, started=False)
        play(feed, clock, 0, 30)
        clock[0] += 3 * SECOND
        play(feed, clock, 30 * FRAME, 5)
        self.assertEqual((feed.error, feed.resyncs, feed.late['video']), (None, 1, 0))


if __name__ == '__main__':
    unittest.main()
