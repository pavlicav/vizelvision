import io
import unittest
from email.message import Message
from urllib.error import HTTPError

from roku_stream.config import MasterConfig, MasterLowConfig
from roku_stream.errors import ConfigError
from roku_stream.master import MasterStreamError
from roku_stream.master_preview import LOCAL_WINDOW, MasterPreview, live_window, nearby, with_quality


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
        for query in ("url=http://remote.test", "_HLS_msn=../x", "&".join(["_HLS_msn=1"] * 10),
                      "quality=medium", "quality=", "quality=low&quality=full", "quality=../x"):
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


INDEX = (b'#EXTM3U\n#EXT-X-VERSION:10\n#EXT-X-INDEPENDENT-SEGMENTS\n\n'
         b'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",NAME="audio2",AUTOSELECT=YES,DEFAULT=YES,URI="audio2_stream.m3u8?session=s"\n\n'
         b'#EXT-X-STREAM-INF:BANDWIDTH=2400000,CODECS="avc1.4d401f,mp4a.40.2",RESOLUTION=960x540,FRAME-RATE=30.000,AUDIO="audio"\n'
         b'video1_stream.m3u8?session=s\n')
FULL, LOW = "http://127.0.0.1:18888/master/", "http://127.0.0.1:18888/master_low/"


def low_playlist(first, count):
    """The low path's media playlist: 2 s segments."""
    return media_playlist(first, count).replace(b"TARGETDURATION:1", b"TARGETDURATION:2").replace(b"#EXTINF:1.00000", b"#EXTINF:2.00000")


class Upstream:
    """MediaMTX: bodies by URL prefix; an int is an HTTP error status."""
    def __init__(self, **bodies):
        self.bodies, self.calls = bodies, []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        body = self.bodies["low" if url.startswith(LOW) else "full"]
        if isinstance(body, int):
            raise HTTPError(url, body, "nope", Message(), io.BytesIO(b""))
        return io.BytesIO(body)


class QualityTests(unittest.TestCase):
    def preview(self, settings=MasterLowConfig(), **bodies):
        upstream = Upstream(**bodies)
        return MasterPreview(MasterConfig(enabled=True, low=settings), opener=upstream), upstream

    def test_everyone_gets_the_full_rendition_unless_they_ask(self):
        preview, upstream = self.preview(full=INDEX, low=INDEX)
        for client in ("127.0.0.1", "100.70.6.82", "8.8.8.8", None):   # Michigan's relay keeps 60 fps
            raw, _ = preview.read("index.m3u8", "", client=client)
            self.assertEqual(raw, INDEX.replace(b"VERSION:10", b"VERSION:7"))
        self.assertTrue(all(url.startswith(FULL) for url in upstream.calls), upstream.calls)

    def test_quality_low_reads_the_low_path_and_names_it_in_every_uri(self):
        preview, upstream = self.preview(low=INDEX)
        raw, mime = preview.read("index.m3u8", "quality=low", client="100.66.124.86")
        self.assertEqual(upstream.calls, [LOW + "index.m3u8"])
        self.assertEqual(mime, "application/vnd.apple.mpegurl")
        self.assertIn(b'URI="audio2_stream.m3u8?session=s&quality=low"', raw)
        self.assertIn(b"\nvideo1_stream.m3u8?session=s&quality=low\n", raw)
        preview.read("video1_stream.m3u8", "session=s&quality=low")
        self.assertEqual(upstream.calls[-1], LOW + "video1_stream.m3u8?session=s")   # quality is ours, not MediaMTX's

    def test_a_low_media_playlist_names_its_init_and_segments(self):
        preview, _ = self.preview(low=low_playlist(50, 4))
        raw, _ = preview.read("video1_stream.m3u8", "session=s&quality=low")
        self.assertIn(b'#EXT-X-MAP:URI="ab_video1_init.mp4?session=s&quality=low"', raw)
        self.assertEqual(raw.count(b".mp4?session=s&quality=low\n"), 4)

    def test_low_segments_come_from_the_low_path_untouched(self):
        preview, upstream = self.preview(low=b"\x00\x00\x00\x18ftyp")
        raw, mime = preview.read("ab_video1_seg51.mp4", "session=s&quality=low")
        self.assertEqual((raw, mime, upstream.calls), (b"\x00\x00\x00\x18ftyp", "video/mp4", [LOW + "ab_video1_seg51.mp4?session=s"]))

    def test_quality_full_is_named_too(self):
        preview, upstream = self.preview(full=INDEX)
        raw, _ = preview.read("index.m3u8", "quality=full", client="100.70.6.82")
        self.assertEqual(upstream.calls, [FULL + "index.m3u8"])
        self.assertIn(b"video1_stream.m3u8?session=s&quality=full", raw)

    def test_no_low_rendition_on_air_falls_back_to_full_and_says_so(self):
        for status in (404, 500):   # 404: no publisher on master_low; 500: MediaMTX lacks the path
            with self.subTest(status=status):
                preview, upstream = self.preview(full=INDEX, low=status)
                raw, _ = preview.read("index.m3u8", "quality=low")
                self.assertEqual(upstream.calls, [LOW + "index.m3u8", FULL + "index.m3u8"])
                self.assertIn(b"video1_stream.m3u8?session=s&quality=full", raw)
                self.assertNotIn(b"quality=low", raw)

    def test_a_missing_low_segment_is_not_swapped_for_a_full_one(self):
        preview, upstream = self.preview(full=b"other", low=404)
        with self.assertRaisesRegex(MasterStreamError, "not ready"):
            preview.read("ab_video1_seg51.mp4", "quality=low")
        self.assertEqual(upstream.calls, [LOW + "ab_video1_seg51.mp4"])

    def test_low_turned_off_serves_full(self):
        preview, upstream = self.preview(MasterLowConfig(encoder="off"), full=INDEX)
        raw, _ = preview.read("index.m3u8", "quality=low")
        self.assertEqual(upstream.calls, [FULL + "index.m3u8"])
        self.assertIn(b"&quality=full", raw)

    def test_far_viewers_keep_thirty_seconds_of_two_second_segments(self):
        preview, _ = self.preview(low=low_playlist(200, 30))
        far, _ = preview.read("video1_stream.m3u8", "session=s&quality=low", client="100.66.124.86")
        self.assertEqual(far.count(b"#EXTINF"), 15)
        self.assertIn(b"#EXT-X-MEDIA-SEQUENCE:215\n", far)
        near, _ = preview.read("video1_stream.m3u8", "session=s&quality=low", client="10.0.0.240")
        self.assertEqual(near.count(b"#EXTINF"), LOCAL_WINDOW)


class WithQualityTests(unittest.TestCase):
    def test_tags_relative_uris_only_and_keeps_line_endings(self):
        playlist = (b'#EXTM3U\r\n#EXT-X-MAP:URI="init.mp4"\r\nseg1.mp4\r\nseg2.mp4?session=s\r\n'
                    b'https://example.test/seg3.mp4\r\n/abs/seg4.mp4\r\n\r\n')
        self.assertEqual(with_quality(playlist, "low"),
                         b'#EXTM3U\r\n#EXT-X-MAP:URI="init.mp4?quality=low"\r\nseg1.mp4?quality=low\r\n'
                         b'seg2.mp4?session=s&quality=low\r\nhttps://example.test/seg3.mp4\r\n/abs/seg4.mp4\r\n\r\n')

    def test_a_tagged_playlist_reads_back_through_the_allowlist(self):
        preview = MasterPreview(MasterConfig(enabled=True), opener=lambda *a, **k: io.BytesIO(b"#EXTM3U\n"))
        for line in with_quality(INDEX, "low").split(b"\n"):
            for uri in ([line] if line and not line.startswith(b"#") else []):
                name, query = uri.decode().split("?", 1)
                preview.read(name, query)   # no ConfigError

