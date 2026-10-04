import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from roku_stream.api import MOVED, PAGES, _UI_FILE, handler_factory
from roku_stream.config import MasterConfig

UI = Path(__file__).resolve().parents[1] / 'roku_stream' / 'static' / 'ui'


class UiTests(unittest.TestCase):
    """Every page is a file in static/ui, loads the shared core first, and asks only for files
    the server serves without a key."""

    def test_every_page_loads_the_core_and_only_ui_assets_that_exist(self):
        for page in PAGES:
            with self.subTest(page=page):
                html = (UI / (page[1:] + '.html')).read_text()
                self.assertIn('<header class="topbar" data-page=', html)
                self.assertRegex(html, r'<header class="topbar"[^>]*></header><script src="static/ui/vv\.js"></script>')
                for asset in re.findall(r'(?:src|href)="(static/[^"]+)"', html):
                    self.assertTrue(_UI_FILE.fullmatch('/' + asset), asset)
                    self.assertTrue((UI.parent / asset[len('static/'):]).is_file(), asset)

    def test_old_addresses_lead_to_the_new_pages(self):
        config = SimpleNamespace(server=SimpleNamespace(api_key='key'), channels=(), master=MasterConfig())
        handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace())
        for path, location in MOVED.items():
            target = location.split('#')[0]
            self.assertIn('/' + target, PAGES)
            handler = object.__new__(handler_type)
            handler.path, handler._authorize = path, Mock(return_value=False)
            handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
            handler.do_GET()
            handler.send_response.assert_called_once_with(307)
            handler.send_header.assert_any_call('Location', location)
            handler._authorize.assert_not_called()


if __name__ == '__main__':
    unittest.main()
