import copy
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.ecp import RokuApp
from roku_stream.errors import ConfigError, ControlBusyError, EcpError, RokuStreamError
from roku_stream.master import MasterStreamError
from roku_stream.production_monitor import DEFAULTS, ProductionMonitor, capture_return


class FakeTv:
    def __init__(self):
        self.owner = 'fixture'
        self.config = TvThingConfig(enabled=True, base_url='http://tv.test/')
        self.calls = []
        self.refuse_lock = False
        self.snapshot = {'locks': {'analog': None, 'digital': None}, 'lanes': {
            'analog': {'quality': 'medium', 'selection': None,
                       'stream': {'active': False, 'ready': False, 'generation': None}}}}

    def request(self, path, body=None):
        self.calls.append((path, copy.deepcopy(body)))
        if body:
            assert 'override' not in body
        if path == 'status':
            return copy.deepcopy(self.snapshot)
        if path == 'tuner/lock':
            if self.refuse_lock:
                raise MasterStreamError('Locked', details={'http_status': 423})
            self.snapshot['locks']['analog'] = {'owner': self.owner}
            return {'token': 'test-token', 'renewed': bool(body.get('token')),
                    'lock': {'expires_at': time.time()+90}}
        if path == 'tuner/lock/release':
            self.snapshot['locks']['analog'] = None
            return {}
        if path == 'tune':
            self.snapshot['lanes']['analog'] = {
                'selection': {'channel': body['channel']}, 'quality': body['quality'],
                'stream': {'generation': 'g1', 'active': True, 'ready': True,
                           'playback': [{'protocol': 'hls', 'url': 'stream/analog.m3u8'}]}}
            return copy.deepcopy(self.snapshot['lanes']['analog'])
        if path == 'stop':
            self.snapshot['lanes']['analog']['stream']['active'] = False
            return {}
        raise AssertionError(path)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = SimpleNamespace(master=MasterConfig(socket_path=Path(self.tmp.name)/'master.sock'),
                                      tv_thing=TvThingConfig(enabled=True), server=SimpleNamespace(api_key=None))
        self.tv = FakeTv()
        self.ecp = Mock()
        self.ecp.device_info.return_value = {'model-name': 'Roku Express+'}
        self.ecp.apps.return_value = [RokuApp('dev', 'VizelVision')]
        self.ecp.active_app.return_value = RokuApp('dev', 'VizelVision')
        self.ecp.media_player.return_value = {'state': 'play', 'plugin': {'id': 'dev'}, 'error': 'false'}
        self.factory = Mock(return_value=self.ecp)
        self.capture = Mock(return_value={'comparison': {'matches_master': True}, 'video_received': True})
        self.now = 1000
        self.monitor = ProductionMonitor(self.config, tv=self.tv, ecp_factory=self.factory,
                                         capture=self.capture, clock=lambda: self.now, sleeper=lambda _: None)

    def run_check(self):
        self.monitor.request_check()
        self.monitor.tick()
        return self.monitor.status()['last_check']

    def test_healthy_and_cleanup_of_temporary_cable_stream(self):
        result = self.run_check()
        self.assertEqual(result['status'], 'healthy')
        self.assertTrue(result['roku']['playing'])
        self.factory.assert_called_once_with('http://10.0.0.111:8060', launch_timeout=20)
        self.ecp.launch.assert_not_called()
        self.capture.assert_called_once_with('http://tv.test/stream/analog.m3u8',
                                             self.config.master.hls_url + 'index.m3u8')
        self.assertIn(('stop', {'lane': 'analog', 'token': 'test-token'}), self.tv.calls)
        self.assertEqual(self.tv.calls[-1][0], 'tuner/lock/release')

    def test_missing_or_stopped_app_recovers_once_and_verifies_playback(self):
        for app in ('home', 'dev'):
            with self.subTest(app=app):
                self.ecp.launch.reset_mock()
                self.ecp.active_app.return_value = RokuApp(app, 'Home' if app == 'home' else 'VizelVision')
                self.ecp.media_player.return_value = {'state': 'close'}
                def recover(_):
                    self.ecp.active_app.return_value = RokuApp('dev', 'VizelVision')
                    self.ecp.media_player.return_value = {'state': 'play', 'plugin': {'id': 'dev'}}
                self.ecp.launch.side_effect = recover
                result = self.run_check()
                self.assertEqual(result['status'], 'recovered')
                self.assertFalse(result['roku_before']['playing'])
                self.ecp.launch.assert_called_once_with('dev')

    def test_failed_recovery_never_claims_healthy_or_repeats_launch(self):
        self.ecp.media_player.return_value = {'state': 'close'}
        result = self.run_check()
        self.assertEqual(result['status'], 'unhealthy')
        self.ecp.launch.assert_called_once_with('dev')
        self.capture.assert_not_called()

    def test_wrong_plugin_is_not_playback(self):
        self.ecp.media_player.return_value = {'state': 'play', 'plugin': {'id': 'other'}}
        self.assertEqual(self.run_check()['status'], 'unhealthy')

    def test_buffering_settles_without_launch(self):
        self.ecp.media_player.side_effect = [{'state': 'buffer'}, {'state': 'play', 'plugin': {'id': 'dev'}},
                                            {'state': 'play', 'plugin': {'id': 'dev'}}]
        self.assertEqual(self.run_check()['status'], 'healthy')
        self.ecp.launch.assert_not_called()

    def test_every_existing_lock_defers_without_contacting_roku_or_mutation(self):
        for lane in ('analog', 'digital'):
            with self.subTest(lane=lane):
                self.tv.calls.clear()
                self.tv.snapshot['locks'] = {'analog': None, 'digital': None}
                self.tv.snapshot['locks'][lane] = {'owner': 'VCR'}
                self.assertEqual(self.run_check()['status'], 'deferred')
                self.assertEqual(self.tv.calls, [('status', None)])
                self.factory.assert_not_called()

    def test_lock_race_fails_closed(self):
        self.tv.refuse_lock = True
        self.assertEqual(self.run_check()['status'], 'deferred')
        self.factory.assert_not_called()
        self.assertFalse(any(path == 'tune' for path, _ in self.tv.calls))

    def test_incomplete_lock_status_and_unknown_locks_defer(self):
        for locks in ({}, {'analog': None}, {'analog': False, 'digital': None}):
            self.tv.snapshot['locks'] = locks
            self.assertEqual(self.run_check()['status'], 'deferred')
        self.factory.assert_not_called()

    def test_do_not_interrupt_other_cable_channel(self):
        self.tv.snapshot['lanes']['analog'].update(selection={'channel': 42}, stream={'active': True})
        self.assertEqual(self.run_check()['status'], 'deferred')
        self.assertEqual(self.tv.calls, [('status', None)])

    def test_existing_channel_stream_is_not_stopped(self):
        self.tv.snapshot['lanes']['analog'].update(selection={'channel': 70}, stream={'active': True})
        self.assertEqual(self.run_check()['status'], 'healthy')
        self.assertFalse(any(path == 'stop' for path, _ in self.tv.calls))

    def test_lost_lease_during_capture_never_stops_other_owner(self):
        def capture(*_):
            self.tv.snapshot['locks']['analog'] = {'owner': 'VCR'}
            return {'picture_has_detail': True}
        self.capture.side_effect = capture
        result = self.run_check()
        self.assertEqual(result['status'], 'deferred')
        self.assertFalse(any(path == 'stop' for path, _ in self.tv.calls))
        self.assertIn('cleanup_error', result)

    def test_unreachable_roku_or_wrong_app_never_launches(self):
        self.ecp.apps.return_value = [RokuApp('dev', 'Someone else')]
        self.assertEqual(self.run_check()['status'], 'error')
        self.ecp.apps.side_effect = EcpError('Unreachable')
        self.assertEqual(self.run_check()['status'], 'error')
        self.ecp.launch.assert_not_called()

    def test_blank_return_is_inconclusive_without_recovery(self):
        self.capture.return_value = {'picture_has_detail': False}
        self.assertEqual(self.run_check()['status'], 'inconclusive')
        self.ecp.launch.assert_not_called()

    def test_capture_failure_releases_and_stops_only_owned_stream(self):
        self.capture.side_effect = RuntimeError('No video')
        self.assertEqual(self.run_check()['status'], 'error')
        self.assertEqual([p for p, _ in self.tv.calls][-2:], ['stop', 'tuner/lock/release'])

    def test_schedule_and_restart_preserve_deadline(self):
        self.monitor.save({**DEFAULTS, 'enabled': True})
        self.monitor.tick()
        self.assertEqual(self.monitor.status()['next_check_at'], 22600)
        self.now += 21599
        self.monitor.tick()
        self.assertEqual(self.capture.call_count, 1)
        reader = ProductionMonitor(self.config, tv=self.tv, clock=lambda: self.now)
        self.assertEqual(reader.status()['next_check_at'], 22600)
        reader.tick()
        self.now += 1
        self.monitor.tick()
        self.assertEqual(self.capture.call_count, 2)
        self.assertEqual(len(self.monitor.status()['history']), 2)

    def test_deferred_checks_retry_after_fifteen_minutes(self):
        self.monitor.save({**DEFAULTS, 'enabled': True})
        self.tv.snapshot['locks']['analog'] = {'owner': 'VCR'}
        self.monitor.tick()
        self.assertEqual(self.monitor.status()['next_check_at'], 1900)

    def test_settings_validation_and_persistence(self):
        self.monitor.save(DEFAULTS)
        for field, value in [('enabled', 1), ('roku_ip', '8.8.8.8'), ('roku_ip', '127.0.0.1'),
                             ('roku_ip', '10.0.0.111:8060'), ('roku_ip', 'bad'),
                             ('cable_channel', True), ('cable_channel', 136), ('cable_channel', 0),
                             ('app_id', '../launch'), ('interval_hours', float('nan')), ('interval_hours', 0)]:
            with self.subTest(field=field, value=value), self.assertRaises(ConfigError):
                self.monitor.save({**DEFAULTS, field: value})
        self.assertEqual(json.loads(self.monitor.path.read_text())['settings'], DEFAULTS)
        self.monitor.path.write_text('bad')
        reader = ProductionMonitor(self.config, tv=self.tv)
        self.assertFalse(reader.status()['settings']['enabled'])
        self.assertTrue(reader.status()['storage_error'])

    def test_manual_checks_coalesce_and_settings_cannot_change_mid_check(self):
        self.monitor.request_check()
        with self.assertRaises(ControlBusyError):
            self.monitor.request_check()
        with self.assertRaises(ControlBusyError):
            self.monitor.save(DEFAULTS)
        self.monitor.tick()
        self.assertFalse(self.monitor.status()['running'])

    def test_failed_attempt_persistence_prevents_device_commands(self):
        with patch.object(self.monitor, '_persist', side_effect=OSError('full')):
            self.monitor.request_check()
            with self.assertRaises(OSError):
                self.monitor.tick()
        self.assertFalse(self.monitor.status()['running'])
        self.factory.assert_not_called()
        self.assertEqual(self.tv.calls, [])

    def test_api_monitor_auth_validation_and_async_check(self):
        handler = object.__new__(handler_factory(self.config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                                production_monitor=self.monitor))
        handler.path = '/v1/production/monitor'
        handler._authorize = Mock(return_value=False)
        handler._json = Mock()
        handler._body = Mock(return_value={**DEFAULTS, 'enabled': True})
        handler.do_GET()
        handler.do_POST()
        handler._json.assert_not_called()
        handler._body.assert_not_called()
        handler._authorize.return_value = True
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0], 200)
        handler.do_GET()
        self.assertTrue(handler._json.call_args.args[1]['settings']['enabled'])
        handler.path += '/check'
        handler._body.return_value = {}
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0], 202)
        self.assertTrue(handler._json.call_args.args[1]['pending'])
        self.factory.assert_not_called()

    def test_manual_launch_ignores_tv_thing_locks_and_verifies_app(self):
        self.tv.snapshot['locks'] = {'analog': {'owner': 'someone'}, 'digital': {'owner': 'else'}}
        result = self.monitor.launch_app()
        self.assertTrue(result['launched'])
        self.ecp.launch.assert_called_once_with('dev')
        self.assertEqual(self.tv.calls, [])
        self.ecp.launch.reset_mock()
        self.ecp.apps.return_value = [RokuApp('dev', 'Someone else')]
        with self.assertRaises(RokuStreamError):
            self.monitor.launch_app()
        self.ecp.launch.assert_not_called()
        self.monitor.running = True
        with self.assertRaises(ControlBusyError):
            self.monitor.launch_app()

    def test_api_launch_route(self):
        handler = object.__new__(handler_factory(self.config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                                production_monitor=self.monitor))
        handler.path = '/v1/production/monitor/launch'
        handler._authorize = Mock(return_value=True)
        handler._json = Mock()
        handler._body = Mock(return_value={})
        handler.do_POST()
        self.assertEqual(handler._json.call_args.args[0], 200)
        self.ecp.launch.assert_called_once_with('dev')

    def test_wrong_picture_is_unhealthy_even_when_roku_reports_play(self):
        self.capture.return_value = {'video_received': True, 'picture_has_detail': True,
                                     'comparison': {'matches_master': False}}
        result = self.run_check()
        self.assertEqual(result['status'], 'unhealthy')
        self.assertTrue(result['roku']['playing'])
        self.ecp.launch.assert_not_called()

    def test_relaunch_does_not_count_as_recovered_without_picture_match(self):
        self.ecp.media_player.return_value = {'state': 'close'}
        def recover(_):
            self.ecp.media_player.return_value = {'state': 'play', 'plugin': {'id': 'dev'}}
        self.ecp.launch.side_effect = recover
        self.capture.return_value = {'comparison': {'matches_master': False}}
        result = self.run_check()
        self.assertTrue(result['recovery_attempted'])
        self.assertEqual(result['status'], 'unhealthy')

    def test_missing_reference_is_inconclusive(self):
        self.capture.return_value = {'comparison': {'matches_master': None,
                                                    'reason': 'reference_unavailable'}}
        self.assertEqual(self.run_check()['status'], 'inconclusive')
        self.ecp.launch.assert_not_called()

    def test_old_green_result_requires_reverification_after_restart(self):
        self.run_check()
        saved = json.loads(self.monitor.path.read_text())
        saved['last_check']['cable'] = {'picture_has_detail': True}
        self.monitor.path.write_text(json.dumps(saved))
        reader = ProductionMonitor(self.config, tv=self.tv)
        self.assertEqual(reader.status()['last_check']['status'], 'inconclusive')


if __name__ == '__main__':
    unittest.main()
