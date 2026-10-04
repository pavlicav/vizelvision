import io
import re
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError

from roku_stream.errors import ConfigError
from roku_stream.input_preview import InputPreview
from roku_stream.master import MasterStreamError

KEY = 'a'*32
ROOT = 'http://tv.test/stream/digital.m3u8'


class InputPreviewTests(unittest.TestCase):
    def setUp(self):
        self.master = Mock()
        self.master.request.return_value = {'input_id': KEY, 'url': ROOT}
        self.calls = []
        self.content = b'#EXTM3U\n#EXTINF:1,\ndigitalseg_generation_123.ts\n'
        def opener(url, **kwargs):
            self.calls.append(url)
            return io.BytesIO(self.content if url.endswith('.m3u8') else b'segment')
        self.preview = InputPreview(self.master, opener=opener)

    def test_manifest_is_rewritten_and_only_known_segments_can_be_read(self):
        raw, mime = self.preview.read(KEY, 'index.m3u8')
        token = raw.decode().splitlines()[-1]
        self.assertRegex(token, r'^[a-f0-9]{32}\.ts$')
        self.assertNotIn('tv.test', raw.decode())
        self.assertEqual(self.preview.read(KEY, token)[0], b'segment')
        self.assertEqual(self.calls[-1], 'http://tv.test/stream/digitalseg_generation_123.ts')
        with self.assertRaises(MasterStreamError):
            self.preview.read(KEY, 'f'*32+'.ts')

    def test_audio_renditions_and_init_uri_attributes_are_rewritten(self):
        self.content = b'#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,URI="audio.m3u8?session=abc"\n#EXT-X-MAP:URI="init.mp4"\nvideo.m3u8\n'
        raw, _ = self.preview.read(KEY, 'index.m3u8')
        self.assertEqual(len(re.findall(rb'[a-f0-9]{32}\.', raw)), 3)
        self.assertNotIn(b'session=', raw)

    def test_replacement_during_fetch_rejects_response(self):
        self.master.request.side_effect = [{'input_id': KEY, 'url': ROOT}, MasterStreamError('expired')]
        with self.assertRaisesRegex(MasterStreamError, 'expired'):
            self.preview.read(KEY, 'index.m3u8')

    def test_cross_input_tokens_and_path_escape_are_rejected(self):
        token = self.preview.read(KEY, 'index.m3u8')[0].decode().splitlines()[-1]
        with self.assertRaises(MasterStreamError):
            self.preview.read('b'*32, token)
        for reference in ['http://evil.test/a.ts', '../secret.ts', '%2e%2e/secret.ts', '/secret.ts']:
            self.content = ('#EXTM3U\n'+reference+'\n').encode()
            with self.assertRaises(MasterStreamError):
                self.preview.read(KEY, 'index.m3u8')
        for name in ['../index.m3u8', 'http://evil.test/x.ts', 'arbitrary.ts']:
            with self.assertRaises(ConfigError):
                self.preview.read(KEY, name)

    def test_redirects_allow_sessions_but_reject_other_hosts_and_loops(self):
        def redirect(location):
            return HTTPError(ROOT, 302, 'Found', {'Location': location}, io.BytesIO())
        self.preview.opener = Mock(side_effect=[redirect('?session=abc'), io.BytesIO(self.content)])
        raw, _ = self.preview.read(KEY, 'index.m3u8')
        self.assertTrue(raw.startswith(b'#EXTM3U'))
        self.assertEqual(self.preview.opener.call_args.args[0], ROOT + '?session=abc')
        self.preview.opener = Mock(side_effect=redirect('http://evil.test/feed.m3u8'))
        with self.assertRaisesRegex(MasterStreamError, 'outside'):
            self.preview.read(KEY, 'index.m3u8')
        self.preview.opener = Mock(side_effect=lambda *a, **k: (_ for _ in ()).throw(redirect('?again=1')))
        with self.assertRaisesRegex(MasterStreamError, 'unavailable'):
            self.preview.read(KEY, 'index.m3u8')
        self.assertEqual(self.preview.opener.call_count, 4)

    def test_size_and_concurrency_are_bounded(self):
        self.preview.MAX_BYTES = 2
        for _ in range(8):
            with self.assertRaisesRegex(MasterStreamError, 'limit'):
                self.preview.read(KEY, 'index.m3u8')
        for _ in range(6):
            self.preview.readers.acquire(False)
        with self.assertRaisesRegex(MasterStreamError, 'busy'):
            self.preview.read(KEY, 'index.m3u8')
