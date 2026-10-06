import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig
from roku_stream.playout_queue import QueueItem
from roku_stream.scheduler import utc_now


class ApiTests(unittest.TestCase):
    def test_take_route_passes_only_the_requested_prepared_selection(self):
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        coordinator = Mock()
        coordinator.request.return_value = {'id': 'take-1', 'action': 'take', 'state': 'pending'}
        handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                       coordinator=coordinator)
        handler = object.__new__(handler_type)
        handler.path = '/v1/master/take'
        handler._authorize = lambda: False
        handler._body = Mock(return_value={'prepared_id': 'verified-input'})
        handler._json = Mock()
        handler.do_POST()
        coordinator.request.assert_not_called()
        handler._authorize = lambda: True
        handler.do_POST()
        coordinator.request.assert_called_once_with('take', {'prepared_id': 'verified-input'})
        handler._json.assert_called_once_with(202, coordinator.request.return_value)

    def test_prepare_take_route_passes_the_target_to_the_coordinator(self):
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        coordinator = Mock()
        coordinator.request.return_value = {'id': 'op-1', 'action': 'prepare-take', 'state': 'pending'}
        handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(),
                                       coordinator=coordinator)
        handler = object.__new__(handler_type)
        handler.path = '/v1/master/prepare-take'
        handler._authorize = lambda: True
        target = {'source_id': 'tv-thing-digital', 'channel_id': 'wjla_7_1'}
        handler._body = Mock(return_value=target)
        handler._json = Mock()
        handler.do_POST()
        coordinator.request.assert_called_once_with('prepare-take', target)
        handler._json.assert_called_once_with(202, coordinator.request.return_value)

    def test_legacy_entry_points_redirect_to_on_air(self):
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace())
        for path, location in [('/', 'air'), ('/cue-sheet', 'air'), ('/cue-sheet/', '../air'), ('/production', 'presentation'),
                               ('/production/', '../presentation'), ('/continuity', 'presentation#continuity')]:
            handler = object.__new__(handler_type)
            handler.path = path
            handler._authorize = lambda: True
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.do_GET()
            handler.send_response.assert_called_once_with(307)
            handler.send_header.assert_any_call('Location', location)

    def test_source_media_route_is_authorized_and_not_cached(self):
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        with patch('roku_stream.api.InputPreview') as proxy:
            proxy.return_value.read.return_value = (b'#EXTM3U', 'application/vnd.apple.mpegurl')
            handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace())
            handler = object.__new__(handler_type)
            handler.path = '/v1/inputs/' + 'a'*32 + '/media/index.m3u8'
            handler._authorize = lambda: False
            handler.do_GET()
            proxy.return_value.read.assert_not_called()
            handler._authorize = lambda: True
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            handler.wfile = io.BytesIO()
            handler.do_GET()
            proxy.return_value.read.assert_called_once_with('a'*32, 'index.m3u8')
            handler.send_header.assert_any_call('Cache-Control', 'no-store')
            self.assertEqual(handler.wfile.getvalue(), b'#EXTM3U')

    def test_queue_route_includes_items_and_confirmed_on_air_source(self) -> None:
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        controller = SimpleNamespace(snapshot=lambda: {
            "target": {"source_id": "mlb", "channel_id": "123", "date": "2026-09-02"}, "reusable": True})
        item = QueueItem(
            id="item-1",
            position=0,
            channel="ESPN",
            release_type="after_game",
            created_at=utc_now().isoformat(),
            after_game_pk=123,
            after_game_date="2026-09-02",
            after_game_title="Away at Home",
        )
        playout = SimpleNamespace(list=lambda: [item])
        handler_type = handler_factory(
            config, controller, SimpleNamespace(), playout=playout
        )
        handler = object.__new__(handler_type)
        handler.path = "/v1/queue"
        handler._authorize = lambda: True
        response = {}
        handler._json = lambda status, payload: response.update(
            status=status, payload=payload
        )

        handler.do_GET()

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["payload"]["items"][0]["channel"], "ESPN")
        self.assertEqual(response["payload"]["on_air"]["target"]["channel_id"], "123")

if __name__ == "__main__":
    unittest.main()


class RokuMovedTests(unittest.TestCase):
    """The source Roku is TV Thing's Roku lane since 2026-10-06: the routes of the controller
    vizelVision ran answer 410 and say where it went; its status and cue progress come from TV Thing."""

    def handler(self, roku=None, path='/', body=None, coordinator=None):
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        handler = object.__new__(handler_factory(config, roku, SimpleNamespace(), coordinator=coordinator))
        handler.path = path
        handler._authorize = lambda: True
        handler._body = Mock(return_value=body or {})
        response = {}
        handler._json = lambda status, payload: response.update(status=status, payload=payload)
        return handler, response

    def test_controller_routes_point_at_tv_thing(self):
        for method, path in (('GET', '/v1/preview'), ('GET', '/v1/state'), ('GET', '/v1/roku/signal'),
                             ('GET', '/v1/operations/abc'), ('POST', '/v1/play'),
                             ('POST', '/v1/thursday-night-football/play'), ('POST', '/v1/calibrate'),
                             ('POST', '/v1/baseball/play'), ('POST', '/v1/sunday-ticket/find')):
            with self.subTest(path):
                handler, response = self.handler(path=path)
                handler.do_GET() if method == 'GET' else handler.do_POST()
                self.assertEqual(response['status'], 410)
                self.assertEqual(response['payload']['error']['code'], 'moved_to_tv_thing')
                self.assertIn('/tv/roku.html', response['payload']['error']['message'])

    def test_operation_is_tv_things_navigation(self):
        lane = {'selection': None, 'roku': {'operation': {
            'active': True, 'state': 'running', 'phase': 'live_guide', 'message': 'Finding NBC',
            'target': {'source_id': 'youtube-tv', 'channel_id': 'NBC'}}}}
        handler, response = self.handler(SimpleNamespace(lane=lambda: (lane, {'owner': 'VizelVision master'})),
                                         '/v1/operation')
        handler.do_GET()
        self.assertEqual(response['status'], 200)
        self.assertTrue(response['payload']['active'])
        self.assertEqual(response['payload']['channel'], 'NBC')
        self.assertEqual(response['payload']['message'], 'Finding NBC')

    def test_stop_goes_through_master_control(self):
        coordinator = Mock(enabled=True)
        coordinator.request.return_value = {'accepted': True}
        handler, response = self.handler(path='/v1/operation/cancel', coordinator=coordinator)
        handler.do_POST()
        coordinator.request.assert_called_once_with('cancel', {})
        self.assertEqual(response['status'], 200)
