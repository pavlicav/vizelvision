import io
import json
import unittest
from datetime import datetime

from roku_stream.radio_info import RadioInfo, describe


def state(**now):
    return {"now": {"log_id": None, "title": "", "artist": "", "kind": "music", **now}}


class RadioInfoTests(unittest.TestCase):
    def setUp(self):
        self.responses = {}
        self.calls = []
        self.time = 100.

        def opener(url, **kwargs):
            path = url.removeprefix("http://127.0.0.1:1894")
            self.calls.append(path)
            if isinstance(self.responses[path], Exception):
                raise self.responses[path]
            return io.BytesIO(json.dumps(self.responses[path]).encode())

        # Wednesday 14:xx local.
        self.info = RadioInfo("http://127.0.0.1:1894/", opener=opener, clock=lambda: self.time,
                              local_now=lambda: datetime(2026, 9, 23, 14, 30))
        self.responses["/api/grid"] = [{"dow": 2, "hour": 14, "name": "CLASSICAL"}, {"dow": 2, "hour": 15, "name": "OLD ROCK"}]
        self.responses["/api/log"] = {"entries": [{"id": 7, "source_slot": "DAYTIME ALT"}]}

    def test_describe_formats_track_and_skips_buffering(self):
        self.assertEqual(describe(state(title="Starlight", artist="Muse", kind="spotify"), "OLD ROCK"),
                         ["OLD ROCK SHOW", "MUSE — STARLIGHT"])
        self.assertEqual(describe(state(title="TOP OF THE HOUR (NIGHT)", kind="timed_segment"), None),
                         ["TOP OF THE HOUR (NIGHT)"])
        self.assertEqual(describe(state(), "Morning Show"), ["MORNING SHOW"])
        self.assertEqual(describe(state(title="SPOTIFY BUFFERING", artist="emergency holding bed",
                                        kind="spotify_buffering"), "CLASSICAL"), ["CLASSICAL SHOW"])
        long = describe(state(title="Piano Concerto No. 3 in D Minor, Op. 30: I. Allegro · Allegro ma non tanto",
                              artist="Sergei Rachmaninoff, Earl Wild, Royal Philharmonic Orchestra", kind="spotify"), None)[0]
        self.assertTrue(long.startswith("SERGEI RACHMANINOFF — PIANO CONCERTO NO. 3 IN D MINOR, OP. 30"))
        self.assertLessEqual(len(long), 64)
        self.assertTrue(long.endswith("…"))

    def test_show_prefers_logged_slot_then_grid(self):
        self.responses["/api/state"] = state(log_id=7, title="Song", artist="Band")
        self.info.refresh()
        self.assertEqual(self.info.lines(), ["DAYTIME ALT SHOW", "BAND — SONG"])
        self.responses["/api/state"] = state(log_id=8, title="Song", artist="Band")
        self.info.refresh()
        self.info.refresh()
        self.assertEqual(self.info.lines()[0], "CLASSICAL SHOW")
        # An unknown log id is looked up once, and the grid is cached.
        self.assertEqual(self.calls.count("/api/log"), 2)
        self.assertEqual(self.calls.count("/api/grid"), 1)

    def test_lines_expire_when_station_stops_answering(self):
        self.responses["/api/state"] = state(title="Song", artist="Band")
        self.info.refresh()
        self.assertEqual(len(self.info.lines()), 2)
        self.responses["/api/state"] = OSError("connection refused")
        with self.assertRaises(OSError):
            self.info.refresh()
        self.time += 29
        self.assertEqual(len(self.info.lines()), 2)
        self.time += 2
        self.assertEqual(self.info.lines(), [])
