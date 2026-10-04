import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig
from roku_stream.playout_queue import QueueItem
from roku_stream.scheduler import utc_now


class ApiTests(unittest.TestCase):
    def test_prime_play_route_resolves_the_espn_game_and_checks_authorization(self):
        from tests.test_prime_video import GAME
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        controller, sports = Mock(feedback=None), Mock()
        sports.game.return_value = GAME
        controller.play_prime_game.return_value = {'ok': True, 'events': []}
        handler = object.__new__(handler_factory(config, controller, SimpleNamespace(), sports=sports))
        handler.path = '/v1/thursday-night-football/play'
        handler._body = Mock(return_value={'game_id': GAME['game_id'], 'date': '2026-10-01'})
        handler._json = Mock()
        handler._authorize = lambda: False
        handler.do_POST()
        controller.play_prime_game.assert_not_called()
        handler._authorize = lambda: True
        handler.do_POST()
        sports.game.assert_called_once_with('nfl', GAME['game_id'], '2026-10-01')
        controller.play_prime_game.assert_called_once_with(GAME)
        handler._json.assert_called_once_with(200, {'ok': True})

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
        controller = SimpleNamespace(
            feedback=None,
            on_air_source=lambda: {
                "type": "baseball",
                "game_pk": 123,
                "title": "Away at Home",
            },
        )
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
        self.assertEqual(response["payload"]["on_air"]["game_pk"], 123)

    def test_state_route_returns_controller_observation(self) -> None:
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        controller = SimpleNamespace(
            feedback=None,
            current_state=lambda: {"ok": True, "state": "live_guide"},
        )
        handler_type = handler_factory(config, controller, SimpleNamespace())
        handler = object.__new__(handler_type)
        handler.path = "/v1/state"
        handler._authorize = lambda: True
        response = {}
        handler._json = lambda status, payload: response.update(
            status=status, payload=payload
        )

        handler.do_GET()

        self.assertEqual(response["status"], 200)
        self.assertEqual(response["payload"]["state"], "live_guide")

    def test_operation_route_does_not_require_the_controller_play_lock(self) -> None:
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(), master=MasterConfig())
        controller = SimpleNamespace(
            feedback=None,
            operation_status=lambda: {
                "active": True,
                "channel": "NBC",
                "app_state": "live_guide",
            },
        )
        handler_type = handler_factory(config, controller, SimpleNamespace())
        handler = object.__new__(handler_type)
        handler.path = "/v1/operation"
        handler._authorize = lambda: True
        response = {}
        handler._json = lambda status, payload: response.update(
            status=status, payload=payload
        )

        handler.do_GET()

        self.assertEqual(response["status"], 200)
        self.assertTrue(response["payload"]["active"])
        self.assertEqual(response["payload"]["app_state"], "live_guide")

    def test_preview_stream_is_same_origin_mjpeg(self) -> None:
        first = b"\xff\xd8first\xff\xd9"
        second = b"\xff\xd8second\xff\xd9"

        class Feedback:
            def preview_frames(self):
                yield first
                yield second

        config = SimpleNamespace(
            server=SimpleNamespace(api_key=None),
            channels=(),
            master=MasterConfig(),
        )
        controller = SimpleNamespace(feedback=Feedback())
        handler_type = handler_factory(config, controller, SimpleNamespace())
        handler = object.__new__(handler_type)
        handler.wfile = io.BytesIO()
        response = {}
        headers = {}
        handler.send_response = lambda status: response.update(status=status)
        handler.send_header = lambda name, value: headers.update({name: value})
        handler.end_headers = lambda: None

        handler._preview()

        body = handler.wfile.getvalue()
        self.assertEqual(response["status"], 200)
        self.assertIn("multipart/x-mixed-replace", headers["Content-Type"])
        self.assertIn(first, body)
        self.assertIn(second, body)
        self.assertIn(b"--vizelvision-frame", body)


if __name__ == "__main__":
    unittest.main()
