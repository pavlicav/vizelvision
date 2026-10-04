import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.api import handler_factory
from roku_stream.calibration import calibration_status, device_diagnostics
from roku_stream.config import FeedbackConfig, MasterConfig
from roku_stream.direct_capture import DirectCaptureFeedback


class CalibrationTests(unittest.TestCase):
    def feedback(self):
        feedback = DirectCaptureFeedback(FeedbackConfig(
            backend='direct', device='/dev/v4l/by-id/usb-AMBA_Hauppauge_HD_PVR_SERIAL-video-index0',
            input_format='mpegts'))
        self.addCleanup(feedback.close)
        return feedback

    def test_target_requires_detected_progressive_720_and_60_fps(self):
        feedback = self.feedback()
        good = dict(state='locked', width=1280, height=720, scan='progressive', rate=60)
        for difference, matches in [({}, True), ({'rate': 59.94}, True), ({'rate': 30}, False),
                                    ({'rate': None}, False), ({'scan': 'interlaced'}, False),
                                    ({'width': 1920, 'height': 1080}, False),
                                    ({'state': 'no_signal'}, False)]:
            with self.subTest(difference=difference):
                feedback.input_signal = Mock(return_value={**good, **difference})
                with patch('roku_stream.calibration.device_diagnostics', return_value={}):
                    self.assertEqual(calibration_status(feedback)['target']['matches'], matches)

    def test_missing_node_distinguishes_matching_usb_and_unbound_driver(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            device = root / 'usb-AMBA_Hauppauge_HD_PVR_SERIAL-video-index0'
            usb = root / 'usb'
            unit = usb / '2-4'
            unit.mkdir(parents=True)
            (unit / 'serial').write_text('DIFFERENT')
            (unit / 'product').write_text('Hauppauge HD PVR')
            self.assertEqual(device_diagnostics(device, usb)['state'], 'missing')
            (unit / 'serial').write_text('SERIAL')
            interface = unit / '2-4:1.0'
            interface.mkdir()
            result = device_diagnostics(device, usb)
            self.assertEqual(result['state'], 'driver_missing')
            self.assertEqual(result['usb']['port'], '2-4')
            driver = root / 'hdpvr'
            driver.mkdir()
            (interface / 'driver').symlink_to(driver)
            result = device_diagnostics(device, usb)
            self.assertEqual(result['state'], 'node_missing')
            self.assertEqual(result['usb']['drivers'], ['hdpvr'])

    def test_permissions_and_invalid_paths_are_separate_from_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'ordinary-file'
            path.touch()
            self.assertEqual(device_diagnostics(path, root)['state'], 'invalid')
            with patch('roku_stream.calibration.os.access', return_value=False):
                self.assertEqual(device_diagnostics(Path('/dev/null'), root)['state'], 'permission_denied')
            self.assertEqual(device_diagnostics(Path('/dev/null'), root)['state'], 'ready')

    def test_fast_queries_are_coalesced_and_expire_without_capture_lock(self):
        feedback = self.feedback()
        feedback._query_input_signal = Mock(side_effect=[
            {'state': 'locked', 'width': 1280}, {'state': 'no_signal'}])
        # A navigation capture can be waiting on a frame while diagnostics proceed.
        with feedback._capture_lock, patch('roku_stream.direct_capture.time.monotonic', side_effect=[10, 10.1, 10.3, 10.3]):
            first = feedback.input_signal()
            first['state'] = 'changed by caller'
            second = feedback.input_signal()
            third = feedback.input_signal()
        self.assertEqual(second['state'], 'locked')
        self.assertEqual(third['state'], 'no_signal')
        self.assertIn('observed_at', third)
        self.assertEqual(feedback._query_input_signal.call_count, 2)

    def test_timeout_clears_old_resolution(self):
        import subprocess
        feedback = self.feedback()
        feedback.status = Mock(return_value={'ready': True})
        with patch('roku_stream.direct_capture.subprocess.run', side_effect=subprocess.TimeoutExpired('v4l2', 2)):
            signal = feedback.input_signal()
        self.assertEqual(signal['state'], 'unknown')
        self.assertNotIn('width', signal)
        self.assertIn('timed out', signal['label'])

    def test_page_is_public_but_diagnostics_require_authorization(self):
        config = SimpleNamespace(server=SimpleNamespace(api_key='test-key'), channels=(), master=MasterConfig())
        feedback = self.feedback()
        handler_type = handler_factory(config, SimpleNamespace(feedback=feedback), SimpleNamespace())
        handler = object.__new__(handler_type)
        handler._authorize = Mock(return_value=False)
        handler._page = Mock()
        handler.path = '/calibration'
        handler.do_GET()
        handler._page.assert_called_once()
        handler._authorize.assert_not_called()
        handler.path = '/v1/roku/calibration'
        with patch('roku_stream.api.calibration_status', return_value={'signal': 'example'}) as probe:
            handler.do_GET()
            probe.assert_not_called()
            handler._authorize.return_value = True
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = io.BytesIO()
            handler.do_GET()
            probe.assert_called_once_with(feedback)
            handler.send_response.assert_called_once_with(200)
            handler.send_header.assert_any_call('Cache-Control', 'no-store')
            self.assertIn(b'example', handler.wfile.getvalue())

    def test_calibration_trailing_slash_redirect_is_prefix_safe(self):
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        handler = object.__new__(handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace()))
        handler.path = '/calibration/'
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.do_GET()
        handler.send_header.assert_any_call('Location', '../calibration')


if __name__ == '__main__':
    unittest.main()
