"""Training recordings on TV-Thing (admute/recordings.py): planning, cancelling, following.

  /home/vivian/miniconda3/bin/python3 -m unittest tests.test_admute_recordings
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import numpy  # noqa: F401  (admute needs it)
except ImportError:
    raise unittest.SkipTest("needs numpy: run with /home/vivian/miniconda3/bin/python3")

from admute import recordings as R

HOUR = 3600


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(t))


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        (d / "config.json").write_text(json.dumps({"master": {"socket_path": str(d / "master.sock")},
                                                   "server": {"port": 1}, "tv_thing": {"base_url": "http://tv/"}}))
        self.rec = R.Recordings(str(d / "config.json"))
        self.now = time.time()
        self.posted = []
        self.timers = []
        self.segments = []
        self.rec.playback = lambda: self.segments
        self.rec.tv_recordings = lambda: {"timers": self.timers, "history": [],
                                          "storage": {"directory": "/lib"}}
        self.rec.channels = lambda: {"WTTG": {"id": "wttg_dt_5_1", "name": "WTTG-DT"},
                                     "WRC": {"id": "wrc_hd_4_1", "name": "WRC-HD"}}

        def post(url, body):
            self.posted.append((url, body))
            return {"timer": {"id": f"t{len(self.posted)}"}}
        self.rec._post = post

    def tearDown(self):
        self.dir.cleanup()

    def game(self, pk, channel, start, source="youtube-tv", hours=3):
        return {"kind": "game", "start": iso(start), "end": iso(start + hours * HOUR),
                "game": {"league": "mlb", "game_pk": pk, "title": f"Game {pk}"},
                "target": {"source_id": source, "channel_id": channel}}

    def test_an_over_the_air_game_is_booked_and_cable_is_not(self):
        self.segments = [self.game(1, "FOX", self.now + HOUR), self.game(2, "TBS", self.now + 2 * HOUR)]
        self.rec.plan()
        url, body = self.posted[0]
        self.assertTrue(url.endswith("/api/v1/recordings"))
        self.assertEqual(body["channel_id"], "wttg_dt_5_1")
        self.assertEqual(body["end"] - body["start"], R.LEAD + R.LENGTH)
        self.assertIn("(ad training)", body["title"])
        self.assertIs(body["from_live"], True, "copies the live stream, no second encode")
        self.assertEqual(self.rec.state["recordings"]["mlb-1"]["status"], "scheduled")
        self.assertIn("cable only", self.rec.state["skipped"]["mlb-2"]["why"])
        self.rec.plan()
        self.assertEqual(len(self.posted), 1, "booked once")

    def test_an_existing_timer_on_that_channel_is_learnt_from(self):
        start = self.now + HOUR
        self.timers = [{"id": "mine", "channel_id": "wttg_dt_5_1", "start": start - 600, "end": start + 4 * HOUR,
                        "status": "scheduled", "title": "my recording"}]
        self.segments = [self.game(1, "FOX", start)]
        self.rec.plan()
        self.assertEqual(self.posted, [])
        rec = self.rec.state["recordings"]["mlb-1"]
        self.assertEqual((rec["timer"], rec["adopted"]), ("mine", True))

    def test_one_channel_at_a_time(self):
        start = self.now + HOUR
        self.timers = [{"id": "nfl", "channel_id": "wrc_hd_4_1", "channel_name": "WRC-HD", "start": start, "end": start + 3 * HOUR,
                        "status": "scheduled", "title": "football"}]
        self.segments = [self.game(1, "FOX", start)]
        self.rec.plan()
        self.assertEqual(self.posted, [])
        self.assertIn("recording WRC-HD", self.rec.state["skipped"]["mlb-1"]["why"])

    def test_not_while_vizelvision_airs_another_tv_thing_channel(self):
        start = self.now + HOUR
        self.segments = [self.game(1, "FOX", start),
                         {"kind": "show", "start": iso(start + HOUR), "end": iso(start + 2 * HOUR),
                          "target": {"source_id": "tv-thing-digital", "channel_id": "wrc_hd_4_1"}}]
        self.rec.plan()
        self.assertEqual(self.posted, [])
        self.assertIn("airs wrc_hd_4_1 from TV-Thing", self.rec.state["skipped"]["mlb-1"]["why"])

    def test_cancelled_on_the_page(self):
        self.segments = [self.game(1, "FOX", self.now + HOUR)]
        self.rec.plan()
        self.rec.skip_path.write_text(json.dumps({"games": ["mlb-1"]}))
        self.rec.cancelled()
        self.assertEqual(self.posted[-1], ("http://tv/api/v1/recordings/cancel", {"id": "t1"}))
        self.assertEqual(self.rec.state["recordings"]["mlb-1"]["status"], "cancelled")
        self.rec.plan()
        self.assertEqual(len(self.posted), 2, "and not booked again")

    def test_finished_recordings_are_picked_up(self):
        self.segments = [self.game(1, "FOX", self.now + HOUR)]
        self.rec.plan()
        self.rec.tv_recordings = lambda: {"timers": [], "storage": {"directory": "/lib"}, "history": [
            {"id": "t1", "status": "done", "file": "Game 1 - 5.1 WTTG-DT.mp4", "started_at": 123, "bytes": 9}]}
        self.assertEqual(self.rec.follow(), ["mlb-1"])
        rec = self.rec.state["recordings"]["mlb-1"]
        self.assertEqual((rec["status"], rec["path"], rec["started_at"]), ("recorded", "/lib/Game 1 - 5.1 WTTG-DT.mp4", 123))

    def test_training_labels_cover_the_tape_without_overlaps(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(R, "AUTO_TRUTH", Path(d)):
            start = 1_000_000.0
            halves = [(start + 100, start + 400), (start + 600, start + 900)]
            ads = [(430.0, 590.0, "ad")]
            R.Recordings.truth("/lib/g.mp4", {"game_pk": 7}, iso(start), ads, halves, 0.0, 1000.0)
            spans = json.loads((Path(d) / "g.json").read_text())["spans"]
            self.assertEqual(spans[0], [0.0, 110.0, "ignore"])
            self.assertIn([110.0, 400.0, "show"], spans)
            self.assertIn([430.0, 590.0, "ad"], spans)
            for (a, b, _), (c, _, _) in zip(spans, spans[1:]):
                self.assertLessEqual(b, c)
            self.assertEqual(spans[-1][1], 1000.0)


if __name__ == "__main__":
    unittest.main()
