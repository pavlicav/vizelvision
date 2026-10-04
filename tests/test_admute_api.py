"""The ad-mute routes: settings, the worker override (straight to the worker), pause, labels."""
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig


class AdMuteApiTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.state = Path(self.dir.name)
        self.config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(),
                                      master=MasterConfig(socket_path=self.state / 'master.sock'),
                                      tv_thing=SimpleNamespace(base_url='http://127.0.0.1:8080/'))
        self.coordinator = Mock()
        self.coordinator.request.return_value = {'state': 'live', 'on_air': {'id': 'k1'},
                                                 'admute': {'connected': True, 'mode': 'shadow'}}
        self.worker = Mock()
        with patch('roku_stream.api.MasterClient', return_value=self.worker):
            self.handler_type = handler_factory(self.config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                                coordinator=self.coordinator)

    def tearDown(self):
        self.dir.cleanup()

    def call(self, method, path, body=None):
        handler = object.__new__(self.handler_type)
        handler.path = path
        handler._authorize = lambda: True
        handler._body = Mock(return_value=body or {})
        handler._json = Mock()
        getattr(handler, 'do_' + method)()
        status, payload = handler._json.call_args[0]
        return int(status), payload

    def get_raw(self, path):
        handler = object.__new__(self.handler_type)
        handler.path = path
        handler._authorize = lambda: True
        handler._json = Mock()
        handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
        handler.wfile = io.BytesIO()
        handler.do_GET()
        if handler._json.called:
            return int(handler._json.call_args[0][0]), None, None
        headers = dict(c[0] for c in handler.send_header.call_args_list)
        return int(handler.send_response.call_args[0][0]), headers, handler.wfile.getvalue()

    def test_pictures_for_the_page(self):
        key = 'ab' * 16
        folder = self.state / 'admute-frames' / key
        folder.mkdir(parents=True)
        (folder / '1790960000.jpg').write_bytes(b'\xff\xd8exact')
        (folder / '1790960010.jpg').write_bytes(b'\xff\xd8later')
        status, headers, body = self.get_raw(f'/v1/admute/frame/{key}/1790960000.jpg')
        self.assertEqual((status, headers['Content-Type'], body), (200, 'image/jpeg', b'\xff\xd8exact'))
        self.assertEqual(self.get_raw(f'/v1/admute/frame/{key}/1790960008.jpg')[2], b'\xff\xd8later', 'nearest second')
        self.assertEqual(self.get_raw(f'/v1/admute/frame/{key}/1790960005.jpg')[0], 404)
        self.assertEqual(self.get_raw(f'/v1/admute/frame/{key}/../../x.jpg')[0], 400)
        self.assertEqual(self.get_raw('/v1/admute/frame/nothex/1790960000.jpg')[0], 400)

    def test_view_carries_the_programme_delay(self):
        self.assertEqual(self.call('GET', '/v1/admute')[1]['delay'], 4.0, 'lookahead + 1 without the shared delay')
        self.coordinator.request.return_value = {'state': 'live', 'on_air': None, 'admute': {},
                                                 'captions': {'programme_delay': {'seconds': 6.0}}}
        self.assertEqual(self.call('GET', '/v1/admute')[1]['delay'], 6.0)

    def test_known_ads_listed_and_forgotten(self):
        (self.state / 'admute-prints.json').write_text(json.dumps({'updated': 1.0, 'clips': [
            {'id': 3, 'kind': 'ad', 'last': 10}, {'id': 7, 'kind': 'show', 'last': 20}]}))
        status, known = self.call('GET', '/v1/admute/known')
        self.assertEqual((status, [c['id'] for c in known['clips']]), (200, [7, 3]), 'most recently heard first')
        status, _ = self.call('POST', '/v1/admute/forget', {'clips': [3]})
        self.assertEqual(status, 200)
        line = json.loads((self.state / 'admute-commands.jsonl').read_text().splitlines()[-1])
        self.assertEqual(line['forget'], [3])
        for bad in ({'clips': []}, {'clips': ['3']}, {'clips': [True]}, {'clips': [1], 'all': True}, {'clips': list(range(1, 102))}):
            self.assertEqual(self.call('POST', '/v1/admute/forget', bad)[0], 400, bad)

    def test_ads_named_and_pictured(self):
        status, _ = self.call('POST', '/v1/admute/name', {'clip': 3, 'name': 'GEICO camel'})
        self.assertEqual(status, 200)
        line = json.loads((self.state / 'admute-commands.jsonl').read_text().splitlines()[-1])
        self.assertEqual(line['name'], {'clip': 3, 'name': 'GEICO camel'})
        for bad in ({'clip': 3}, {'clip': '3', 'name': 'x'}, {'clip': True, 'name': 'x'}, {'clip': 3, 'name': 'x' * 81},
                    {'clip': 3, 'name': 'x', 'more': 1}):
            self.assertEqual(self.call('POST', '/v1/admute/name', bad)[0], 400, bad)
        (self.state / 'admute-ads').mkdir()
        (self.state / 'admute-ads' / '3-0.jpg').write_bytes(b'\xff\xd8ad')
        status, headers, body = self.get_raw('/v1/admute/ad/3-0.jpg')
        self.assertEqual((status, headers['Content-Type'], body), (200, 'image/jpeg', b'\xff\xd8ad'))
        self.assertEqual(self.get_raw('/v1/admute/ad/3-1.jpg')[0], 404)
        self.assertEqual(self.get_raw('/v1/admute/ad/../admute.json')[0], 400)
        self.assertEqual(self.get_raw('/v1/admute/ad/x-0.jpg')[0], 400)

    def test_training_recordings_listed_and_cancelled(self):
        (self.state / 'admute-recordings.json').write_text(json.dumps({'updated': 1.0, 'recordings': {
            'mlb-1': {'title': 'A at B (ad training)', 'channel': 'WTTG-DT', 'start': 100, 'status': 'scheduled', 'timer': 't1',
                      'game': {'title': 'A at B'}},
            'mlb-2': {'title': 'mine', 'channel': 'WRC-HD', 'start': 200, 'status': 'scheduled', 'timer': 't2', 'adopted': True,
                      'game': {'title': 'C at D'}},
            'mlb-3': {'title': 'done', 'channel': 'WRC-HD', 'start': 50, 'status': 'processed', 'timer': 't3',
                      'steps': {'known_ads': 12}, 'game': {'title': 'E at F'}}},
            'skipped': {'mlb-9': {'title': 'G at H', 'start': 300, 'why': 'on TBS: cable only'}}}))
        status, view = self.call('GET', '/v1/admute/recordings')
        self.assertEqual([r['game'] for r in view['recordings']], ['mlb-2', 'mlb-1', 'mlb-3'], 'newest first')
        self.assertEqual(view['skipped'][0]['why'], 'on TBS: cable only')
        with patch('urllib.request.urlopen') as urlopen:
            self.assertEqual(self.call('POST', '/v1/admute/recordings/cancel', {'game': 'mlb-2'})[0], 200)
            urlopen.assert_not_called()                     # the operator's own timer stays in TV-Thing
            self.assertEqual(self.call('POST', '/v1/admute/recordings/cancel', {'game': 'mlb-1'})[0], 200)
            req = urlopen.call_args[0][0]
            self.assertTrue(req.full_url.endswith('/api/v1/recordings/cancel'))
            self.assertEqual(json.loads(req.data), {'id': 't1'})
        skip = json.loads((self.state / 'admute-recordings-skip.json').read_text())
        self.assertEqual(skip['games'], ['mlb-1', 'mlb-2'])
        self.assertEqual(self.call('POST', '/v1/admute/recordings/cancel', {'game': 'mlb-3'})[0], 400, 'already processed')
        self.assertEqual(self.call('POST', '/v1/admute/recordings/cancel', {'game': 'nope'})[0], 400)

    def test_view_without_a_detector(self):
        status, view = self.call('GET', '/v1/admute')
        self.assertEqual(status, 200)
        self.assertEqual(view['settings']['mode'], 'off')
        self.assertTrue(view['detector_stale'])
        self.assertEqual(view['worker'], {'connected': True, 'mode': 'shadow'})
        (self.state / 'admute-state.json').write_text(json.dumps({'updated': time.time(), 'inputs': []}))
        self.assertFalse(self.call('GET', '/v1/admute')[1]['detector_stale'])

    def test_settings_merge_and_validate(self):
        status, view = self.call('POST', '/v1/admute', {'mode': 'on', 'sources': {'roku': False}, 'speech': False,
                                                         'known_ads': False, 'learn_ads': False, 'learn_games': False,
                                                         'diagnostic': True, 'record_games': False})
        self.assertEqual(status, 200)
        self.assertEqual(view['settings']['mode'], 'on')
        self.assertIs(view['settings']['speech'], False)
        self.assertIs(view['settings']['known_ads'], False)
        self.assertEqual(view['settings']['sources'], {'tv_thing': True, 'roku': False})
        status, error = self.call('POST', '/v1/admute', {'mode': 'loud'})
        self.assertEqual(status, 400)

    def test_override_goes_straight_to_the_worker(self):
        self.worker.request.return_value = {'accepted': True}
        status, view = self.call('POST', '/v1/admute/override', {'action': 'unmute'})
        self.assertEqual(status, 200)
        self.worker.request.assert_called_once_with('admute', {'action': 'unmute'})
        self.coordinator.request.assert_any_call()  # status only: the coordinator never sees it
        self.worker.request.return_value = {'accepted': False, 'reason': 'Nothing analysed is on air'}
        self.assertEqual(self.call('POST', '/v1/admute/override', {'action': 'mute'})[0], 409)
        self.assertEqual(self.call('POST', '/v1/admute/override', {'action': 'louder'})[0], 400)

    def test_pause_is_for_the_input_on_air(self):
        _, view = self.call('POST', '/v1/admute/pause', {'hours': 2})
        self.assertEqual(view['settings']['paused_input'], 'k1')
        self.assertAlmostEqual(view['settings']['paused_until'], time.time() + 7200, delta=5)
        _, view = self.call('POST', '/v1/admute/pause', {'resume': True})
        self.assertIsNone(view['settings']['paused_until'])
        self.assertEqual(self.call('POST', '/v1/admute/pause', {'hours': 99})[0], 400)

    def test_labels_are_appended_and_listed(self):
        status, view = self.call('POST', '/v1/admute/label', {'span_id': 'k1-100', 'label': 'show', 'start': 1.0, 'end': 9.0})
        self.assertEqual(status, 200)
        self.assertEqual(view['labels'][-1]['span_id'], 'k1-100')
        self.assertEqual(self.call('POST', '/v1/admute/label', {'label': 'maybe'})[0], 400)
        self.assertEqual(self.call('POST', '/v1/admute/label', {'label': 'ad', 'evil': 1})[0], 400)


if __name__ == '__main__':
    unittest.main()
