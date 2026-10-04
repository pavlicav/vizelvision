import copy
import io
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.errors import ConfigError
from roku_stream.master_worker import MasterWorker
from roku_stream.production import DEFAULTS, ProductionSettings


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.master = MasterConfig(socket_path=Path(self.temp.name) / 'master.sock')
        self.settings = ProductionSettings(self.master)

    def test_defaults_and_persistence_across_worker_and_web_instances(self):
        self.assertEqual(self.settings.read(), DEFAULTS)
        body = copy.deepcopy(DEFAULTS)
        body['captions']['master'] = 'TEST <&> MASTER'
        body['audio'] = 'silence'
        body['details'] = ['audio', 'format']
        self.settings.save(body)
        reader = ProductionSettings(self.master)
        self.assertEqual(reader.read(), body)
        card = reader.card('master')
        self.assertEqual(card['caption'], 'TEST <&> MASTER')
        self.assertEqual(card['lines'][0], 'OFF-AIR AUDIO · SILENCE')
        self.assertIn('1280 × 720 / 30 FPS', card['lines'][1])
        self.assertEqual(reader.describe()['format_line'], card['lines'][1])

    def test_cairo_radio_audio(self):
        body = copy.deepcopy(DEFAULTS)
        body['audio'] = 'radio'
        self.settings.save(body)
        card = self.settings.card('master')
        self.assertEqual(card['audio'], 'radio')
        self.assertIn('OFF-AIR AUDIO · CAIRO RADIO', card['lines'])
        radio = ['CLASSICAL SHOW', 'MUSE — STARLIGHT']
        lines = self.settings.card('master', radio=radio)['lines']
        self.assertEqual(lines[lines.index('OFF-AIR AUDIO · CAIRO RADIO') + 1:][:2], radio)
        self.assertNotIn(radio[0], self.settings.card('roku', radio=radio)['lines'])
        body['details'] = ['audio']
        self.settings.save(body)
        self.assertNotIn(radio[0], self.settings.card('master', radio=radio)['lines'])
        body['details'], body['audio'] = DEFAULTS['details'], 'tone'
        self.settings.save(body)
        self.assertNotIn(radio[0], self.settings.card('master', radio=radio)['lines'])

    def test_invalid_save_preserves_last_settings(self):
        self.settings.save(DEFAULTS)
        invalid = []
        for key, value in [('audio', 'noise'), ('audio', []), ('details', ['unknown']), ('details', ['audio', 'audio']),
                           ('details', [{}]), ('note', 'x\ny'), ('note', 'x' * 73), ('captions', {'master': 'x'})]:
            body = copy.deepcopy(DEFAULTS)
            body[key] = value
            invalid.append(body)
        for caption in ('', ' ', 'x' * 49, 42):
            body = copy.deepcopy(DEFAULTS)
            body['captions']['master'] = caption
            invalid.append(body)
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(ConfigError):
                self.settings.save(body)
            self.assertEqual(self.settings.read(), DEFAULTS)

    def test_worker_reloads_settings_without_a_cut_and_keeps_last_card_on_corruption(self):
        worker = MasterWorker(SimpleNamespace(master=self.master, tv_thing=TvThingConfig()),
                              tv=Mock(), status_reader=lambda: {'ready': True, 'source': {'id': 'publisher'}})
        worker.output = Mock()
        worker.output.healthy.return_value = True
        worker.output.status.return_value = {}
        worker.output_started = time.monotonic()
        worker._tick()
        worker.output.set_test_card.assert_called_once_with(self.settings.card('master'))
        body = copy.deepcopy(DEFAULTS)
        body['audio'] = 'silence'
        body['captions']['master'] = 'NEW CAPTION'
        self.settings.save(body)
        worker.production_checked = 0
        worker._tick()
        worker.output.set_test_card.assert_called_with(self.settings.card('master'))
        self.settings.path.write_text('broken json')
        worker.production_checked = 0
        worker._tick()
        self.assertEqual(worker.output.set_test_card.call_count, 2)
        self.assertIn('Cannot load test card settings', worker.status()['production_error'])
        worker.output.take.assert_not_called()
        worker.output.close.assert_not_called()

    def handler(self, path, *, authorized=True):
        config = SimpleNamespace(master=self.master, server=SimpleNamespace(api_key='secret'))
        handler = object.__new__(handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace()))
        handler.path = path
        handler._authorize = Mock(return_value=authorized)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = io.BytesIO()
        handler._json = Mock()
        return handler

    def test_api_save_load_and_authentication(self):
        h = self.handler('/v1/production', authorized=False)
        h._body = Mock(return_value=DEFAULTS)
        h.do_POST()
        h._body.assert_not_called()
        h.do_GET()
        h._json.assert_not_called()
        h._authorize.return_value = True
        h.do_POST()
        self.assertEqual(h._json.call_args.args[0], 200)
        h.do_GET()
        self.assertEqual(h._json.call_args.args[1]['cards']['roku']['caption'], 'ROKU OFF')
        self.assertEqual(ProductionSettings(self.master).read(), DEFAULTS)

    def test_public_page_assets_and_slash_redirect(self):
        for path in ('/presentation', '/static/ui/testcard.js', '/static/ui/testcard.css', '/static/ui/vv.css', '/static/test-pattern.webp'):
            h = self.handler(path, authorized=False)
            h.do_GET()
            h.send_response.assert_called_with(200)
            self.assertTrue(h.wfile.getvalue())
        h = self.handler('/presentation/')
        h.do_GET()
        h.send_header.assert_any_call('Location', '../presentation')
        h = self.handler('/static/ui/nope.js', authorized=False)
        h.do_GET()
        self.assertEqual(h._json.call_args.args[0], 404)
        h = self.handler('/static/ui/../../api.py', authorized=False)
        h._authorize = Mock(return_value=False)
        h.do_GET()
        h._authorize.assert_called_once_with()  # Not a UI file: it needs the key.


if __name__ == '__main__':
    unittest.main()
