import io
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.errors import ConfigError
from roku_stream.internet import StreamLease, internet_target
from roku_stream.master import MasterStreamError
from roku_stream.master_worker import MasterWorker
from roku_stream.sources import SourceCatalog
from roku_stream.tv_control import TvControl

PENTULIVE = {"source_id": "internet", "channel_id": "pentulive"}
URL = "http://tv.test/tv/stream/internet/pentulive/index.m3u8"
MASTER = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=4094887,AUDIO="a"\n1.m3u8\n'


class TargetTests(unittest.TestCase):
    def test_a_target_is_a_tv_thing_stream_id(self):
        self.assertEqual(internet_target({**PENTULIVE, "quality": "high", "date": "2026-10-23"}), PENTULIVE)
        for channel in ("", "Pentulive", "../digital", "pentu live", "-pentulive", 29, None, "a" * 201):
            with self.subTest(channel=channel), self.assertRaises(ConfigError):
                internet_target({"source_id": "internet", "channel_id": channel})
        with self.assertRaises(ConfigError):
            internet_target({"source_id": "tv-thing-digital", "channel_id": "pentulive"})


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.requests, self.answers = [], []

        def opener(request, timeout):
            self.requests.append((request.full_url, request.get_method(), timeout))
            answer = self.answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return io.BytesIO(answer)
        self.client = TvControl(TvThingConfig(enabled=True, base_url="http://tv.test/tv/"), opener=opener)

    def test_the_relay_is_asked_once_and_its_url_is_the_feed(self):
        self.answers = [MASTER]
        lease = StreamLease(self.client, PENTULIVE)
        lease.tune()
        self.assertEqual(self.requests, [(URL, "GET", 15)])
        self.assertEqual((lease.check(), lease.lane, lease.release()), (URL, "internet", True))
        lease.renew(force=True)
        self.assertEqual(len(self.requests), 1, "checks and renewals never ask TV Thing")

    def test_a_stream_that_is_not_live_says_why_in_tv_things_words(self):
        self.answers = [HTTPError(URL, 503, "Unavailable", {}, io.BytesIO(json.dumps(
                            {"error": "Yle Areena has nothing live for 1-78104441"}).encode())),
                        HTTPError(URL, 502, "Bad Gateway", {}, io.BytesIO(b"<html>")),
                        URLError("refused"),
                        b"<html>not a playlist</html>"]
        lease = StreamLease(self.client, PENTULIVE)
        with self.assertRaisesRegex(MasterStreamError, "^TV-Thing cannot play pentulive: Yle Areena has nothing live"):
            lease.tune()
        with self.assertRaisesRegex(MasterStreamError, r"^TV-Thing cannot play pentulive \(HTTP 502\)$"):
            lease.tune()
        with self.assertRaisesRegex(MasterStreamError, "internet stream failed"):
            lease.tune()
        with self.assertRaisesRegex(MasterStreamError, "with HLS"):
            lease.tune()

    def test_disabled_tv_thing_is_never_asked(self):
        self.client.config = TvThingConfig()
        with self.assertRaisesRegex(MasterStreamError, "disabled"):
            StreamLease(self.client, PENTULIVE).tune()
        self.assertFalse(self.requests)


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"sources": [{"id": "digital", "available": True, "count": 2}],
                        "lineup": {"internet": [
                            {"tv_number": 29, "tv_name": "Pentulive", "channel_id": "pentulive", "name": "Pentulive",
                             "note": "Yle's puppy cam", "stream_path": "/stream/internet/pentulive/index.m3u8"},
                            {"tv_number": 370, "channel_id": "../digital", "name": "Not a stream id"}]}}
        self.stale = False
        payloads = {"sources": lambda: self.sources, "status": lambda: {"lanes": {}}}
        self.catalog = SourceCatalog(SimpleNamespace(tv_thing=TvThingConfig(enabled=True)), tv=SimpleNamespace(
            get=lambda key: {"data": payloads[key](), "stale": self.stale, "fetched_at": 900,
                             "error": "offline" if self.stale else None}), clock=lambda: 1000)

    def internet(self):
        return next(s for s in self.catalog.list()["sources"] if s["id"] == "internet")

    def test_tv_things_streams_are_channels_numbered_as_in_its_lineup(self):
        result = self.catalog.programs("internet")
        self.assertEqual(result["channels"], [{"id": "pentulive", "number": "29", "name": "Pentulive",
                                               "note": "Yle's puppy cam", "now": None, "upcoming": []}])
        self.assertEqual(result["guide"]["kind"], "streams")
        self.assertFalse(result["guide"]["available"])
        source = self.internet()
        self.assertEqual((source["name"], source["availability"], source["count"], source["configured"]),
                         ("Internet streams", "available", 1, True))

    def test_without_streams_or_a_fresh_catalog(self):
        self.sources = {"sources": []}  # A TV Thing from before 2026-10-23 lists none.
        self.assertEqual(self.catalog.programs("internet")["channels"], [])
        self.assertEqual(self.internet()["availability"], "unavailable")
        self.stale = True
        self.assertEqual(self.internet()["availability"], "unknown")


class FakeDecoder:
    def __init__(self, output, slot, url):
        self.slot, self.url, self.closed = slot, url, False

    def poll(self):
        pass

    def ready(self):
        return True

    def status(self):
        return {}

    def close(self):
        self.closed = True


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.requests = []

        def opener(request, timeout):
            self.requests.append(request.full_url)
            return io.BytesIO(MASTER)
        config = SimpleNamespace(master=MasterConfig(enabled=True), tv_thing=TvThingConfig(enabled=True))
        self.opened = []

        def decoder(output, slot, url, **kwargs):
            self.opened.append((slot, url, kwargs))
            return FakeDecoder(output, slot, url)
        self.tv = TvControl(TvThingConfig(enabled=True, base_url="http://tv.test/tv/"), opener=opener)
        self.worker = MasterWorker(config, tv=self.tv, decoder_factory=decoder,
                                   status_reader=lambda: {"ready": True, "source": {"id": "publisher"}})
        self.worker.output = Mock()
        self.worker.output.healthy.return_value = True
        self.worker.output.status.return_value = {}
        self.worker.publisher_ready = True
        self.worker.output_started = time.monotonic()

    def on_air(self, lane, target):
        lease = Mock(lane=lane, target=target, generation="g1")
        lease.check.return_value = "http://tv.test/tv/stream/feed.m3u8"
        self.worker.inputs["live"] = {"lease": lease, "decoder": FakeDecoder(None, 1, None), "slot": 1,
                                      "was_ready": True, "check_at": 0, "url": "x"}
        self.worker.active = "live"
        return lease

    def test_a_stream_prepares_beside_what_is_on_air_without_a_tuner(self):
        for lane, target in (("internet", {"source_id": "internet", "channel_id": "other-cam"}),
                             ("digital", {"source_id": "tv-thing-digital", "channel_id": "abc", "quality": "medium"})):
            with self.subTest(on_air=lane):
                self.requests.clear()
                self.opened.clear()
                live = self.on_air(lane, target)
                self.worker._prepare(dict(PENTULIVE))
                self.worker.output.take.assert_not_called()
                live.release.assert_not_called()
                self.assertEqual(self.worker.active, "live")
                self.assertEqual(self.requests, [URL])  # The relay, never a lock or a tune.
                self.assertEqual(self.opened, [(2, URL, {})])  # No ad-mute tap: nothing to analyse.
                prepared = self.worker._public(self.worker.prepared)
                self.assertEqual({k: prepared[k] for k in ("source_id", "channel_id", "generation")},
                                 {**PENTULIVE, "generation": None})
                self.worker._drop(self.worker.prepared)
                self.worker.prepared = None

    def test_the_worker_only_takes_stream_ids(self):
        with self.assertRaises(ConfigError):
            self.worker.submit("prepare", {"source_id": "internet", "channel_id": "http://example.test/x.m3u8"})
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main()
