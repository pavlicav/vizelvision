import io
import unittest

from roku_stream.config import MasterConfig
from roku_stream.errors import ConfigError
from roku_stream.master import MasterStreamError
from roku_stream.master_preview import LOCAL_WINDOW, MasterPreview, live_window, nearby


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


def media_playlist(first, count, extra=None):
    """A MediaMTX-shaped fMP4 media playlist; ``extra`` maps a sequence number to tag lines before it."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:10", "#EXT-X-TARGETDURATION:1", f"#EXT-X-MEDIA-SEQUENCE:{first}",
             '#EXT-X-MAP:URI="ab_video1_init.mp4?session=s"']
    for number in range(first, first + count):
        lines += (extra or {}).get(number, [])
        lines += ["#EXTINF:1.00000,", f"ab_video1_seg{number}.mp4?session=s"]
    return ("\n".join(lines) + "\n").encode()


class LiveWindowTests(unittest.TestCase):
    def test_keeps_the_newest_segments_and_moves_the_sequence_on(self):
        raw = media_playlist(407, 30, {420: ["#EXT-X-PROGRAM-DATE-TIME:2026-11-21T23:58:00.52-05:00"],
                                       435: ["#EXT-X-PROGRAM-DATE-TIME:2026-11-21T23:58:22.52-05:00"]})
        out = live_window(raw, 7).decode()
        self.assertEqual(out.count("#EXTINF"), 7)
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:430\n", out)
        self.assertNotIn("seg429.mp4", out)
        self.assertIn("seg430.mp4", out)
        self.assertIn("seg436.mp4", out)
        self.assertIn('#EXT-X-MAP:URI="ab_video1_init.mp4?session=s"', out)       # MAP carries on
        self.assertNotIn("23:58:00", out)                                          # its segment's tag went with it
        self.assertIn("23:58:22", out)
        self.assertTrue(out.startswith("#EXTM3U\n#EXT-X-VERSION:10\n#EXT-X-TARGETDURATION:1\n"))

    def test_a_dropped_discontinuity_is_counted(self):
        raw = media_playlist(10, 10, {12: ["#EXT-X-DISCONTINUITY"], 18: ["#EXT-X-DISCONTINUITY"]})
        out = live_window(raw, 3).decode()
        self.assertIn("#EXT-X-MEDIA-SEQUENCE:17\n#EXT-X-DISCONTINUITY-SEQUENCE:1\n", out)
        self.assertEqual(out.count("#EXT-X-DISCONTINUITY\n"), 1)                  # 18's is kept

    def test_short_multivariant_and_unusual_playlists_come_back_whole(self):
        short = media_playlist(5, 7)
        self.assertIs(live_window(short, 7), short)
        index = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=8270920\nvideo1_stream.m3u8?session=s\nother.m3u8\n'
        self.assertIs(live_window(index, 1), index)
        for tag in ("#EXT-X-ENDLIST", '#EXT-X-PART:DURATION=0.2,URI="p.mp4"', "#EXT-X-SKIP:SKIPPED-SEGMENTS=3"):
            raw = media_playlist(1, 20) + tag.encode() + b"\n"
            self.assertIs(live_window(raw, 7), raw)

    def test_nearby_is_this_host_and_its_lan_not_the_tailnet(self):
        for address in ("127.0.0.1", "::1", "::ffff:127.0.0.1", "10.0.0.240", "192.168.1.5", "172.16.0.9"):
            self.assertTrue(nearby(address), address)
        for address in ("100.70.6.82", "fd7a:115c:a1e0::1", "8.8.8.8", "", None, "not an address"):
            self.assertFalse(nearby(address), address)

    def test_read_trims_media_playlists_for_nearby_viewers_only(self):
        raw = media_playlist(100, 30)
        preview = MasterPreview(MasterConfig(enabled=True), opener=lambda *a, **k: io.BytesIO(raw))
        near, _ = preview.read("video1_stream.m3u8", "session=s", client="127.0.0.1")
        self.assertEqual(near.count(b"#EXTINF"), LOCAL_WINDOW)
        self.assertIn(b"#EXT-X-VERSION:7", near)
        far, _ = preview.read("video1_stream.m3u8", "session=s", client="100.70.6.82")
        self.assertEqual(far, raw.replace(b"VERSION:10", b"VERSION:7"))
        self.assertEqual(preview.read("video1_stream.m3u8", "session=s")[0], far)   # unknown: whole
        segment = b"#EXTINF:1.0,\nx.mp4\n" * 10
        preview = MasterPreview(MasterConfig(enabled=True), opener=lambda *a, **k: io.BytesIO(segment))
        self.assertEqual(preview.read("video1_seg1.mp4", client="127.0.0.1")[0], segment)
