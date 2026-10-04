import stat
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.config import FeedbackConfig
from roku_stream.direct_capture import DirectCaptureFeedback
from roku_stream.errors import CueCancelledError, NavigationError
from roku_stream.feedback import PpmFrame


class DirectCaptureTests(unittest.TestCase):
    def test_slow_encoder_receives_entire_frame_after_polling_timeout(self):
        feedback = self.feedback()
        self.addCleanup(feedback.close)
        payload = b'frame' * 300_000
        result = feedback._run([
            sys.executable, '-c',
            'import sys,time; time.sleep(.4); print(len(sys.stdin.buffer.read()))',
        ], input_data=payload)
        self.assertEqual(int(result), len(payload))

    def test_input_resolution_uses_detected_timings_and_rejects_stale_size(self):
        output = ('Active width: 1920\nActive height: 1080\nFrame format: interlaced\n'
                  'Pixelclock: 74250000 Hz (60.00 fields per second)\n')
        signal = DirectCaptureFeedback._parse_input_signal(0, output)
        self.assertEqual(signal['label'], '1920 × 1080 · interlaced · 60.00 fields/s')
        self.assertEqual(signal['width'], 1920)
        # The driver can print old dimensions even when the query fails.
        missing = DirectCaptureFeedback._parse_input_signal(
            1, output + 'VIDIOC_QUERY_DV_TIMINGS: failed: No locks available')
        self.assertEqual(missing['state'], 'no_signal')
        self.assertNotIn('width', missing)
        progressive = DirectCaptureFeedback._parse_input_signal(
            0, 'Active width: 1280\nActive height: 720\nFrame format: progressive\n')
        self.assertEqual(progressive['label'], '1280 × 720 · progressive')

    def feedback(self):
        return DirectCaptureFeedback(FeedbackConfig(
            backend="direct", device="/dev/v4l/by-id/roku", ocr_enabled=False))

    def test_capture_never_uses_http_and_preview_cannot_replace_cue_evidence(self):
        feedback = self.feedback()
        feedback._run = Mock(return_value=b'P6\n1 1\n255\nabc')
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=81, st_ino=1)
        with patch('pathlib.Path.stat', return_value=info), patch('os.access', return_value=True), \
                patch('urllib.request.urlopen', side_effect=AssertionError('Unexpected HTTP')):
            first = feedback.capture()
            metadata = dict(feedback.last_capture)
            feedback._capture(record=False)
            self.assertIs(feedback.last_frame, first)
            self.assertEqual(feedback.last_capture, metadata)
            feedback.capture()
            self.assertEqual(feedback.last_capture['sequence'], metadata['sequence'] + 1)
            self.assertEqual(feedback.last_capture['stream_id'], metadata['stream_id'])
            self.assertTrue(feedback.last_capture['fresh'])

    def test_timeout_or_cancel_kills_and_reaps_capture_process(self):
        for cancelled in (False, True):
            with self.subTest(cancelled=cancelled):
                feedback = self.feedback()
                process = Mock()
                process.poll.return_value = None
                if cancelled:
                    feedback.wait = Mock(side_effect=CueCancelledError('stop'))
                with patch('subprocess.Popen', return_value=process), \
                        patch('roku_stream.direct_capture.time.monotonic', side_effect=[0, 99]):
                    with self.assertRaises(CueCancelledError if cancelled else NavigationError):
                        feedback._run(['ffmpeg'])
                process.kill.assert_called_once()
                process.communicate.assert_called_once()

    def test_preview_continues_during_navigation_without_replacing_evidence(self):
        feedback = self.feedback()
        self.addCleanup(feedback.close)
        feedback.preview_allowed = lambda: False  # An active Roku cue.
        feedback._run = Mock(side_effect=lambda command, **kwargs:
                             b'jpeg' if kwargs.get('input_data') else b'P6\n1 1\n255\nabc')
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=81, st_ino=1)
        with patch('pathlib.Path.stat', return_value=info), patch('os.access', return_value=True), \
                patch('roku_stream.direct_capture.time.sleep'):
            evidence_frame = feedback.capture()
            evidence = dict(feedback.last_capture)
            frames = feedback.preview_frames()
            try:
                self.assertEqual(next(frames), b'jpeg')
                self.assertEqual(next(frames), b'jpeg')
                self.assertIs(feedback.last_frame, evidence_frame)
                self.assertEqual(feedback.last_capture, evidence)
            finally:
                frames.close()

    def test_replaced_capture_device_invalidates_observation(self):
        feedback = self.feedback()
        feedback.assert_ready = Mock()
        feedback._run = Mock(return_value=b'P6\n1 1\n255\nabc')
        with patch('pathlib.Path.stat', side_effect=[
            SimpleNamespace(st_rdev=81, st_ino=1), SimpleNamespace(st_rdev=81, st_ino=2)
        ]):
            with self.assertRaisesRegex(NavigationError, 'changed during observation'):
                feedback.capture()
        self.assertIsNone(feedback.last_capture)

    def test_hdpvr_selects_component_and_decodes_transport_stream(self):
        feedback = DirectCaptureFeedback(FeedbackConfig(
            backend="direct", device="/dev/video1", input_format="mpegts",
            input_index=0, source_name="Hauppauge HD PVR — Component"))
        feedback._run = Mock(return_value=b'')
        stream = Mock()
        stream.next_frame.return_value = PpmFrame(1, 1, b'abc')
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=81, st_ino=1)
        with patch('pathlib.Path.stat', return_value=info), patch('os.access', return_value=True), \
                patch('roku_stream.direct_capture.CaptureStream', return_value=stream) as factory:
            self.assertEqual(feedback.capture().rgb, b'abc')
            evidence = dict(feedback.last_capture)
            feedback._capture(record=False)
            self.assertEqual(feedback.last_capture, evidence)
            feedback.capture()
            self.assertEqual(feedback.last_capture['stream_id'], evidence['stream_id'])
            self.assertEqual(feedback.last_capture['sequence'], evidence['sequence'] + 1)
            factory.assert_called_once()
            self.assertEqual(feedback.source_catalog()['sources'][0]['name'],
                             'Hauppauge HD PVR — Component')
        control, = feedback._run.call_args_list
        self.assertIn('--set-input=0', control.args[0])
        self.assertTrue(control.kwargs['allow_empty'])
        command = factory.call_args.args[0]
        self.assertEqual(command[command.index('-f') + 1], 'mpegts')
        self.assertNotIn('-video_size', command)
        self.assertNotIn('-standard', command)
        self.assertNotIn('-frames:v', command)
        feedback.close()
        stream.close.assert_called_once()

    def test_stopped_stream_is_closed_and_restarted_on_next_request(self):
        feedback = DirectCaptureFeedback(FeedbackConfig(
            backend='direct', device='/dev/video1', input_format='mpegts'))
        first, second = Mock(), Mock()
        first.next_frame.side_effect = [PpmFrame(1, 1, b'abc'), NavigationError('stopped')]
        second.next_frame.return_value = PpmFrame(1, 1, b'def')
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=81, st_ino=1)
        with patch('pathlib.Path.stat', return_value=info), patch('os.access', return_value=True), \
                patch('roku_stream.direct_capture.CaptureStream', side_effect=[first, second]):
            feedback.capture()
            stream_id = feedback.last_capture['stream_id']
            with self.assertRaises(NavigationError):
                feedback.capture()
            first.close.assert_called_once()
            self.assertEqual(feedback.capture().rgb, b'def')
            self.assertNotEqual(feedback.last_capture['stream_id'], stream_id)
        feedback.close()

    def test_contribution_and_verification_share_one_device_reader(self):
        feedback = DirectCaptureFeedback(FeedbackConfig(
            backend='direct', device='/dev/video1', input_format='mpegts',
            contribution_url='rtsp://127.0.0.1:18554/roku'))
        self.addCleanup(feedback.close)
        stream = Mock()
        stream.next_frame.return_value = PpmFrame(1, 1, b'abc')
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=81, st_ino=1)
        with patch('pathlib.Path.stat', return_value=info), patch('os.access', return_value=True), \
                patch('roku_stream.direct_capture.CaptureStream', return_value=stream) as factory:
            feedback.capture()
            feedback.capture()
        factory.assert_called_once()
        command = factory.call_args.args[0]
        self.assertEqual(command.count('-i'), 1)
        self.assertEqual(command.count('/dev/video1'), 1)
        self.assertIn('pipe:1', command)
        self.assertEqual(command[-1], feedback.config.contribution_url)
        self.assertIn('0:a:0?', command)

    def test_contribution_retries_without_replacing_cue_evidence_and_stops(self):
        feedback = DirectCaptureFeedback(FeedbackConfig(
            backend='direct', device='/dev/video1', input_format='mpegts',
            contribution_url='rtsp://127.0.0.1:18554/roku'))
        self.addCleanup(feedback.close)
        calls = []
        def capture(*, record):
            calls.append(record)
            if len(calls) == 1:
                raise NavigationError('device disconnected')
            feedback._contribution_stop.set()
        feedback._capture = capture
        with patch.object(feedback._contribution_stop, 'wait', return_value=False):
            feedback.start_contribution()
            feedback._contribution_thread.join(timeout=1)
        self.assertFalse(feedback._contribution_thread.is_alive())
        self.assertEqual(calls, [False, False])
        self.assertIsNone(feedback.last_capture)

    def test_unconfigured_contribution_does_not_open_capture_in_background(self):
        feedback = self.feedback()
        feedback._capture = Mock()
        feedback.start_contribution()
        self.assertIsNone(feedback._contribution_thread)
        feedback._capture.assert_not_called()
        feedback.close()

    def test_missing_device_closes_persistent_capture(self):
        feedback = self.feedback()
        stream = Mock()
        feedback._stream = stream
        with patch('pathlib.Path.stat', side_effect=FileNotFoundError):
            with self.assertRaises(NavigationError):
                feedback.capture()
        stream.close.assert_called_once()
        self.assertIsNone(feedback._stream)

    def test_first_signal_query_preserves_existing_capture_and_selection_identity(self):
        feedback = DirectCaptureFeedback(FeedbackConfig(
            backend='direct', device='/dev/video1', input_format='mpegts'))
        self.addCleanup(feedback.close)
        stream = Mock()
        stream.next_frame.return_value = PpmFrame(1, 1, b'abc')
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=81, st_ino=1)
        probe = SimpleNamespace(returncode=0, stderr='', stdout=
            'Active width: 1280\nActive height: 720\nFrame format: progressive\n')
        with patch('pathlib.Path.stat', return_value=info), patch('os.access', return_value=True), \
                patch('roku_stream.direct_capture.CaptureStream', return_value=stream) as factory, \
                patch('roku_stream.direct_capture.subprocess.run', return_value=probe):
            feedback.capture()
            identity = feedback.status()['stream_id']
            feedback.input_signal()
            feedback.capture()
            self.assertEqual(factory.call_count, 1)
            stream.close.assert_not_called()
            self.assertEqual(feedback.status()['stream_id'], identity)

    def test_converter_resolution_change_reopens_decoder(self):
        feedback = DirectCaptureFeedback(FeedbackConfig(
            backend='direct', device='/dev/video1', input_format='mpegts'))
        first, second = Mock(), Mock()
        first.next_frame.return_value = PpmFrame(1, 1, b'abc')
        second.next_frame.return_value = PpmFrame(1, 1, b'def')
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=81, st_ino=1)
        with patch('pathlib.Path.stat', return_value=info), patch('os.access', return_value=True), \
                patch('roku_stream.direct_capture.CaptureStream', side_effect=[first, second]):
            feedback._input_signature = ('locked', 720, 480, 'interlaced', 59.94)
            feedback.capture()
            feedback._input_signature = ('locked', 1280, 720, 'progressive', 60)
            self.assertEqual(feedback.capture().rgb, b'def')
            first.close.assert_called_once()
        feedback.close()

    def test_cancelled_observation_does_not_power_cycle_card(self):
        feedback = DirectCaptureFeedback(FeedbackConfig(
            backend='direct', device='/dev/video1', input_format='mpegts'))
        stream = Mock()
        stream.next_frame.side_effect = CueCancelledError('stop')
        info = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=81, st_ino=1)
        with patch('pathlib.Path.stat', return_value=info), patch('os.access', return_value=True), \
                patch('roku_stream.direct_capture.CaptureStream', return_value=stream):
            with self.assertRaises(CueCancelledError):
                feedback.capture()
        stream.close.assert_not_called()
        self.assertIsNone(feedback.last_capture)
        feedback.close()


if __name__ == '__main__':
    unittest.main()
