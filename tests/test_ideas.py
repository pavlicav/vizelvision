"""The ideas board: its store (ideas.json beside master.sock) and its routes."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig
from roku_stream.errors import ConfigError
from roku_stream.ideas import IdeaStore, MAX_TITLE


class IdeaStoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.now = [1_800_000_000.0]
        self.store = IdeaStore(Path(self.dir.name) / 'master.sock', clock=lambda: self.now[0])

    def tearDown(self):
        self.dir.cleanup()

    def test_empty_board(self):
        view = self.store.read()
        self.assertEqual(view['ideas'], [])
        self.assertIn('tv-thing', view['areas'])
        self.assertEqual(view['statuses'], ['idea', 'next', 'doing', 'done', 'dropped'])

    def test_add_edit_remove(self):
        idea = self.store.add({'title': '  More tuners ', 'area': 'tv-thing'})
        self.assertEqual((idea['title'], idea['note'], idea['area'], idea['status']), ('More tuners', '', 'tv-thing', 'idea'))
        self.assertEqual(json.loads(self.store.path.read_text())['ideas'], [idea])
        self.now[0] += 60
        edited = self.store.edit(idea['id'], {'status': 'next', 'note': 'Depends on the feed split.'})
        self.assertEqual((edited['status'], edited['note'], edited['created'], edited['updated']),
                         ('next', 'Depends on the feed split.', 1_800_000_000.0, 1_800_000_060.0))
        self.assertEqual(self.store.read()['ideas'][0]['status'], 'next')
        self.assertEqual(self.store.remove(idea['id'])['id'], idea['id'])
        self.assertEqual(self.store.read()['ideas'], [])

    def test_unknown_ideas(self):
        self.assertIsNone(self.store.edit('nope', {'status': 'done'}))
        self.assertIsNone(self.store.remove('nope'))

    def test_validation(self):
        for bad in ({}, {'title': ' '}, {'title': 'x' * (MAX_TITLE + 1)}, {'title': 'x', 'area': 'space'},
                    {'title': 'x', 'status': 'someday'}, {'title': 'x', 'priority': 'high'}, {'title': 'x', 'note': 5}):
            with self.subTest(bad=bad), self.assertRaises(ConfigError):
                self.store.add(bad)
        idea = self.store.add({'title': 'x'})
        with self.assertRaises(ConfigError):
            self.store.edit(idea['id'], {'title': ''})

    def test_concurrent_adds_keep_every_idea(self):
        threads = [threading.Thread(target=self.store.add, args=({'title': f'idea {n}'},)) for n in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self.store.read()['ideas']), 20)


class IdeasApiTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), channels=(),
                                 master=MasterConfig(socket_path=Path(self.dir.name) / 'master.sock'),
                                 tv_thing=SimpleNamespace(base_url='http://127.0.0.1:8080/'))
        with patch('roku_stream.api.MasterClient', return_value=Mock()):
            self.handler_type = handler_factory(config, SimpleNamespace(feedback=None), SimpleNamespace(), coordinator=Mock())

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

    def test_routes(self):
        status, view = self.call('POST', '/v1/ideas', {'title': 'Break desk', 'area': 'ads'})
        self.assertEqual(status, 200)
        added = view['added']
        self.assertEqual([i['title'] for i in view['ideas']], ['Break desk'])
        self.assertEqual(self.call('POST', f'/v1/ideas/{added}', {'status': 'doing'})[1]['ideas'][0]['status'], 'doing')
        self.assertEqual(self.call('GET', '/v1/ideas')[1]['ideas'][0]['id'], added)
        self.assertEqual(self.call('POST', '/v1/ideas/nope', {'status': 'done'})[0], 404)
        self.assertEqual(self.call('POST', '/v1/ideas', {'title': ''})[0], 400)
        self.assertEqual(self.call('DELETE', f'/v1/ideas/{added}')[1]['ideas'], [])
        self.assertEqual(self.call('DELETE', f'/v1/ideas/{added}')[0], 404)


if __name__ == '__main__':
    unittest.main()
