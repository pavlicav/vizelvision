import io
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

from roku_stream.api import handler_factory
from roku_stream.config import MasterConfig
from roku_stream.config import TvThingConfig, load_config
from roku_stream.errors import ChannelNotFoundError, ConfigError
from roku_stream.sources import SourceCatalog, normalize_events
from roku_stream.tv_thing import SourceUnavailableError, TvThingClient


class TvThingTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.calls = []
        self.response = {"api_version": "v1", "sources": []}
        self.failure = False
        self.client = TvThingClient(TvThingConfig(enabled=True, base_url="http://tv.test/tv/"),
                                   opener=self.open, clock=lambda: self.now, wall_clock=lambda: self.now)

    def open(self, request, timeout):
        self.calls.append((request.full_url, request.get_method(), timeout))
        if self.failure:
            raise URLError("offline")
        return io.BytesIO(json.dumps(self.response).encode())

    def test_prefix_get_only_and_immutable_cache(self):
        self.client.get("sources")["data"]["sources"].append("changed")
        result = self.client.get("sources")
        self.assertEqual(result["data"]["sources"], [])
        self.assertEqual(self.calls, [("http://tv.test/tv/api/v1/sources", "GET", 4.0)])
        with self.assertRaises(ValueError):
            self.client.get("guide/refresh/stream")
        self.assertEqual(len(self.calls), 1)

    def test_disabled_does_not_request(self):
        self.client.config = TvThingConfig()
        with self.assertRaises(SourceUnavailableError):
            self.client.get("sources")
        self.assertFalse(self.calls)

    def test_outage_keeps_snapshot_with_backoff_then_recovers(self):
        self.client.get("sources")
        self.now += 301
        self.failure = True
        result = self.client.get("sources")
        self.assertTrue(result["stale"])
        self.assertEqual(result["fetched_at"], 1000)
        self.now += 1
        self.client.get("sources")
        self.assertEqual(len(self.calls), 2)
        self.now += 15
        self.failure = False
        self.assertFalse(self.client.get("sources")["stale"])
        self.assertEqual(len(self.calls), 3)

    def test_initial_outage_backoff_and_version_validation(self):
        self.response = {"api_version": "v2", "sources": []}
        for _ in range(2):
            with self.assertRaises(SourceUnavailableError):
                self.client.get("sources")
        self.assertEqual(len(self.calls), 1)

    def test_bad_schema_does_not_replace_good_cache(self):
        self.client.get("sources")
        self.now += 301
        self.response = {"api_version": "v1", "sources": None}
        result = self.client.get("sources")
        self.assertTrue(result["stale"])
        self.assertEqual(result["data"]["sources"], [])

    def test_response_size_limit(self):
        self.client.MAX_BYTES = 10
        with self.assertRaises(SourceUnavailableError):
            self.client.get("sources")

    def test_concurrent_requests_coalesce(self):
        barrier = threading.Barrier(4)
        def read():
            barrier.wait(timeout=2)
            return self.client.get("sources")
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: read(), range(4)))
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(all(not result["stale"] for result in results))


class SourceCatalogTests(unittest.TestCase):
    def setUp(self):
        self.payloads = {
            "digital": {"items": [{"id": "abc", "number": "7.1", "name": "WJLA"},
                                   {"id": "other", "number": "7.2", "name": "Other"}]},
            "analog": {"items": [{"number": 3, "name": "Cable 3"}]},
            "guide": {"available": True, "generated_at": 900, "horizon": 4600,
                      "channels": {"7.1": {"id": "abc", "events": [
                          {"event_id": 1, "title": "Ended", "start": 800, "duration": 200},
                          {"event_id": 1, "title": "Next", "start": 1100, "duration": 100},
                          {"event_id": 1, "title": "Now", "start": 1000, "duration": 100}]},
                          "7.2": {"id": "wrong", "events": [
                              {"event_id": 2, "title": "Wrong", "start": 1000, "duration": 100}]}}},
            "sources": {"sources": [{"id": "digital", "available": True, "count": 2},
                                     {"id": "cable", "available": True, "count": 135}]},
            "status": {"lanes": {"digital": {"selection": {"name": "WJLA"}, "stream": {"state": "ready"}}}},
        }
        self.stale = set()
        self.offline = set()
        channels = (SimpleNamespace(name="ESPN"),)
        self.config = SimpleNamespace(tv_thing=TvThingConfig(enabled=True), channels=channels,
                                      youtube_tv_channels=lambda: channels)
        self.catalog = SourceCatalog(self.config, tv=SimpleNamespace(get=self.get), clock=lambda: 1000)

    def get(self, key):
        if key in self.offline:
            raise SourceUnavailableError("offline")
        return {"data": self.payloads[key], "stale": key in self.stale,
                "fetched_at": 900, "error": "offline" if key in self.stale else None}

    def test_guide_join_clock_boundaries_and_repeated_event_ids(self):
        result = self.catalog.programs("tv-thing-digital")
        channel = result["channels"][0]
        self.assertEqual(channel["now"]["title"], "Now")
        self.assertEqual([e["title"] for e in channel["upcoming"]], ["Next"])
        self.assertNotEqual(channel["now"]["id"], channel["upcoming"][0]["id"])
        self.assertIsNone(result["channels"][1]["now"])
        self.assertEqual(result["guide"]["age_seconds"], 100)
        self.assertEqual(result["guide"]["coverage_hours"], 1)

    def test_missing_guide_preserves_channels(self):
        self.offline.add("guide")
        result = self.catalog.programs("tv-thing-digital")
        self.assertEqual(len(result["channels"]), 2)
        self.assertFalse(result["guide"]["available"])
        self.assertTrue(result["warnings"])

    def test_stale_guide_is_labeled_and_recomputed(self):
        self.stale.add("guide")
        self.catalog.clock = lambda: 5000
        result = self.catalog.programs("tv-thing-digital")
        self.assertTrue(result["stale"])
        self.assertIsNone(result["channels"][0]["now"])
        self.assertEqual(result["guide"]["coverage_hours"], 0)

    def test_analog_and_youtube_do_not_invent_programs(self):
        self.offline.add("guide")
        for source in ("tv-thing-analog", "youtube-tv"):
            result = self.catalog.programs(source)
            self.assertFalse(result["guide"]["available"])
            self.assertIsNone(result["channels"][0]["now"])
        self.assertEqual(self.catalog.programs("tv-thing-analog")["channels"][0]["id"], 3)

    def test_youtube_tv_listings_come_from_tv_things_guide(self):
        self.payloads["guide"]["youtube_tv"] = {"available": True, "generated_at": 400, "coverage_hours": 36.0,
                                                "last_error": None}
        self.payloads["guide"]["channels"]["youtube-tv/ESPN"] = {
            "key": "youtube-tv/ESPN", "kind": "roku", "source_id": "youtube-tv", "channel_id": "ESPN", "events": [
                {"title": "Earlier", "start": 700, "duration": 200},
                {"title": "SportsCenter", "start": 900, "duration": 200, "live": True},
                {"title": "NFL Live", "start": 1100, "duration": 1800}]}
        result = self.catalog.programs("youtube-tv")
        channel = result["channels"][0]
        self.assertEqual((channel["id"], channel["now"]["title"], channel["now"]["end"]), ("ESPN", "SportsCenter", 1100))
        self.assertEqual(channel["now"]["id"], "youtube-tv:ESPN:None:900")
        self.assertEqual([e["title"] for e in channel["upcoming"]], ["NFL Live"])
        self.assertEqual((result["guide"]["available"], result["guide"]["age_seconds"], result["guide"]["coverage_hours"]),
                         (True, 600, 36.0))
        # The antenna's rows are not YouTube TV's, and the antenna keeps its own ids.
        self.assertTrue(self.catalog.programs("tv-thing-digital")["channels"][0]["now"]["id"].startswith("tv-thing-digital:"))

    def test_youtube_tv_without_listings_keeps_its_channels(self):
        result = self.catalog.programs("youtube-tv")
        self.assertEqual([(c["id"], c["now"], c["upcoming"]) for c in result["channels"]], [("ESPN", None, [])])
        self.assertFalse(result["guide"]["available"])

    def test_sources_degrade_independently_and_no_stale_selection(self):
        self.stale.add("status")
        result = self.catalog.list()
        self.assertEqual(result["sources"][0]["availability"], "available")
        self.assertIsNone(result["sources"][0]["selection"])
        self.assertFalse(result["master"]["can_take"])
        self.offline.update(("sources", "status"))
        self.assertEqual(len(self.catalog.list()["sources"]), 7)

    def test_unknown_source(self):
        with self.assertRaises(ChannelNotFoundError):
            self.catalog.programs("made-up")

    def test_malformed_events_and_nonfinite_times_are_ignored(self):
        events = [None, {"start": True, "duration": 200}, {"start": float('nan'), "duration": 200},
                  {"start": 1000, "duration": -1}, {"start": 1000, "duration": float('inf')}]
        self.assertEqual(normalize_events("abc", events, 1000), [])

    def test_baseball_uses_status_without_guessing_end_or_provider(self):
        game = {"game_pk": 12, "title": "Away at Home", "start_time": "2026-09-10T23:00:00Z",
                "state": "Live", "status": "In Progress", "sources": [{"provider": "youtube_tv"}],
                "preferred_source": {"provider": "youtube_tv", "label": "FOX"}}
        self.catalog.baseball = SimpleNamespace(games=lambda day: {"date": day, "games": [game]})
        result = self.catalog.programs("mlb", "2026-09-10")
        now = result["channels"][0]["now"]
        self.assertEqual(now["preferred_source"]["label"], "FOX")
        self.assertIsNone(now["end"])
        self.assertEqual(result["date"], "2026-09-10")

    def test_api_source_routes_and_errors(self):
        config = SimpleNamespace(server=SimpleNamespace(api_key=None), master=MasterConfig())
        handler_type = handler_factory(config, SimpleNamespace(), SimpleNamespace(), sources=self.catalog)
        for path, expected in (("/v1/sources", 200), ("/v1/sources/tv-thing-digital/programs", 200),
                               ("/v1/sources/unknown/programs", 404)):
            handler = object.__new__(handler_type)
            handler.path = path
            handler._authorize = lambda: True
            response = {}
            handler._json = lambda status, payload: response.update(status=status, payload=payload)
            handler.do_GET()
            self.assertEqual(response["status"], expected)
        self.offline.add("digital")
        handler.path = "/v1/sources/tv-thing-digital/programs"
        handler.do_GET()
        self.assertEqual(response["status"], 503)


class TvThingConfigTests(unittest.TestCase):
    def test_settings_validation_and_legacy_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            def load(value):
                path.write_text(json.dumps({"channels": [{"name": "ESPN"}], "tv_thing": value}))
                return load_config(path)
            self.assertFalse(load({}).tv_thing.enabled)
            self.assertEqual(load({"enabled": True, "base_url": "http://host/tv"}).tv_thing.base_url, "http://host/tv/")
            for value in ({"enabled": "yes"}, {"base_url": "file:///tmp/x"}, {"base_url": "http://host:bad/"},
                          {"base_url": "http://user:pass@host/"}, {"base_url": "http://host/?x=1"},
                          {"request_timeout_seconds": 0}, {"guide_cache_seconds": float('nan')},
                          {"retry_seconds": float('inf')}):
                with self.subTest(value=value), self.assertRaises(ConfigError):
                    load(value)
