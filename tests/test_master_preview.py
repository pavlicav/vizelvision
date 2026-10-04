import io
import unittest

from roku_stream.config import MasterConfig
from roku_stream.errors import ConfigError
from roku_stream.master import MasterStreamError
from roku_stream.master_preview import MasterPreview


class MasterPreviewTests(unittest.TestCase):
    def test_scoped_media_and_session_query(self):
        calls = []
        def opener(url, **kwargs):
            calls.append(url)
            return io.BytesIO(b"#EXTM3U\n")
        preview = MasterPreview(MasterConfig(enabled=True), opener=opener)
        raw, mime = preview.read("video1_stream.m3u8", "session=abc-123")
        self.assertEqual(mime, "application/vnd.apple.mpegurl")
        self.assertEqual(calls, ["http://127.0.0.1:18888/master/video1_stream.m3u8?session=abc-123"])

    def test_playlist_version_lowered_for_roku(self):
        playlist = b"#EXTM3U\n#EXT-X-VERSION:10\n#EXT-X-INDEPENDENT-SEGMENTS\nvideo1_stream.m3u8\n"
        preview = MasterPreview(MasterConfig(enabled=True), opener=lambda *a, **k: io.BytesIO(playlist))
        raw, _ = preview.read("index.m3u8")
        self.assertEqual(raw, playlist.replace(b"VERSION:10", b"VERSION:7"))
        preview = MasterPreview(MasterConfig(enabled=True), opener=lambda *a, **k: io.BytesIO(b"#EXTM3U\n#EXT-X-VERSION:6\n"))
        self.assertEqual(preview.read("index.m3u8")[0], b"#EXTM3U\n#EXT-X-VERSION:6\n")
        segment = b"#EXT-X-VERSION:10"
        preview = MasterPreview(MasterConfig(enabled=True), opener=lambda *a, **k: io.BytesIO(segment))
        self.assertEqual(preview.read("video1_seg1.mp4")[0], segment)

    def test_no_traversal_arbitrary_urls_or_unbounded_queries(self):
        preview = MasterPreview(MasterConfig(enabled=True))
        for name in ("../index.m3u8", "%2e%2e%2findex.m3u8", "http://example.test/x.mp4", "other/index.m3u8", "x.txt"):
            with self.assertRaises(ConfigError):
                preview.read(name)
        for query in ("url=http://remote.test", "_HLS_msn=../x", "&".join(["_HLS_msn=1"] * 10)):
            with self.assertRaises(ConfigError):
                preview.read("index.m3u8", query)

    def test_capacity_and_size_are_bounded_and_slot_is_released(self):
        preview = MasterPreview(MasterConfig(enabled=True), opener=lambda *a, **k: io.BytesIO(b"x"*10))
        preview.MAX_BYTES = 5
        for _ in range(8):
            with self.assertRaisesRegex(MasterStreamError, "limit"):
                preview.read("video1_init.mp4")
        for _ in range(6):
            self.assertTrue(preview.readers.acquire(False))
        with self.assertRaisesRegex(MasterStreamError, "busy"):
            preview.read("video1_init.mp4")

    def test_disabled_and_invalid_playlist(self):
        with self.assertRaises(MasterStreamError):
            MasterPreview(MasterConfig()).read("index.m3u8")
        preview = MasterPreview(MasterConfig(enabled=True), opener=lambda *a, **k: io.BytesIO(b"<html>error"))
        with self.assertRaisesRegex(MasterStreamError, "HLS playlist"):
            preview.read("index.m3u8")
