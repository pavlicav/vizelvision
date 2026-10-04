import io
import json
import tempfile
import unittest
from pathlib import Path

from roku_stream.baseball import BaseballCatalog, MlbScheduleClient
from roku_stream.config import load_config


class BaseballTests(unittest.TestCase):
    def test_game_status_marks_final_as_finished(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            catalog = self.catalog(self.config(Path(directory)), state="Final")
            status = catalog.game_status(42, "2026-09-02")

        self.assertTrue(status["finished"])
        self.assertEqual(status["state"], "Final")

    def test_game_status_carries_the_score_and_inning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            live = self.catalog(config, linescore={"inningState": "Top", "currentInningOrdinal": "8th"})
            self.assertEqual(live.game_status(42, "2026-09-02")["summary"], "Mariners 4, Red Sox 1 · Top 8th")
            final = self.catalog(config, state="Final")
            self.assertEqual(final.game_status(42, "2026-09-02")["summary"], "Mariners 4, Red Sox 1 · Final")
            scheduled = self.catalog(config, state="Preview")
            self.assertEqual(scheduled.game_status(42, "2026-09-02")["summary"], "Preview")

    def config(self, root: Path):
        path = root / "config.json"
        path.write_text(
            json.dumps(
                {
                    "channels": [
                        {"name": "ESPN", "guide_index": 0},
                        {"name": "TBS", "guide_index": 1},
                    ]
                }
            ),
            encoding="utf-8",
        )
        return load_config(path)

    @staticmethod
    def response(state="Live", linescore=None):
        return {
            "dates": [
                {
                    "games": [
                        {
                            "gamePk": 42,
                            "officialDate": "2026-09-02",
                            "gameDate": "2026-09-02T23:00:00Z",
                            "status": {
                                "abstractGameState": state,
                                "detailedState": state,
                            },
                            "teams": {
                                "away": {"team": {"id": 136, "name": "Seattle Mariners"}, "score": 4},
                                "home": {"team": {"id": 111, "name": "Boston Red Sox"}, "score": 1},
                            },
                            **({"linescore": linescore} if linescore else {}),
                            "broadcasts": [
                                {
                                    "name": "ESPN",
                                    "callSign": "ESPN",
                                    "type": "TV",
                                    "isNational": True,
                                    "availableForStreaming": True,
                                    "homeAway": "away",
                                    "mediaId": "espn-media",
                                },
                                {
                                    "name": "NESN",
                                    "callSign": "NESN",
                                    "type": "TV",
                                    "isNational": False,
                                    "availableForStreaming": True,
                                    "homeAway": "home",
                                    "mediaId": "nesn-media",
                                },
                            ],
                        }
                    ]
                }
            ]
        }

    def catalog(self, config, state="Live", linescore=None):
        body = json.dumps(self.response(state, linescore)).encode("utf-8")

        def opener(request, timeout):
            self.assertIn("sportId=1", request.full_url)
            self.assertIn("linescore", request.full_url)
            self.assertEqual(timeout, 10.0)
            return io.BytesIO(body)

        client = MlbScheduleClient(
            config.mlb.schedule_url,
            opener=opener,
            cache_seconds=60,
        )
        return BaseballCatalog(config, client)

    def test_live_national_game_prefers_verified_youtube_tv_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = self.catalog(self.config(Path(directory)))
            game = catalog.games("2026-09-02")["games"][0]

            self.assertEqual(game["game_pk"], 42)
            self.assertEqual(game["preferred_source"]["provider"], "youtube_tv")
            self.assertEqual(game["preferred_source"]["channel"], "ESPN")
            self.assertEqual(game["sources"][1]["provider"], "mlb")

    def test_shared_postseason_carriage_maps_each_part_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"channels": [
                {"name": "NBC", "guide_index": 0}, {"name": "FOX", "guide_index": 1},
                {"name": "FS1", "guide_index": 2}, {"name": "NBC Sports Network", "aliases": ["NBCSN"], "guide_index": 3}]}))
            catalog = BaseballCatalog(load_config(path), client=None)

            def channels(name, call_sign, national=True):
                return catalog._yttv_channels({"name": name, "call_sign": call_sign, "is_national": national})
            self.assertEqual(channels("NBC/Peacock", "NBC"), ["NBC"])
            self.assertEqual(channels("Peacock/NBCSN", "Peacock"), ["NBC Sports Network"])
            self.assertEqual(channels("FOX / FS1", "FOX/FS1"), ["FOX", "FS1"])
            self.assertEqual(channels("Fox Deportes / FOX ONE", "FOX Dep."), [])
            self.assertEqual(channels("NBC/Peacock", "NBC", national=False), [])

    def test_range_reports_postseason_series_and_tbd_start(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            response = self.response()
            game = response["dates"][0]["games"][0]
            game.update(seriesDescription="AL Division Series", seriesGameNumber=2, ifNecessary="Y")
            game["status"]["startTimeTBD"] = True
            urls = []

            def opener(request, timeout):
                urls.append(request.full_url)
                return io.BytesIO(json.dumps(response).encode())
            catalog = BaseballCatalog(config, MlbScheduleClient(config.mlb.schedule_url, opener=opener))
            [result] = catalog.range("2026-10-01", "2026-10-10")
            self.assertIn("startDate=2026-10-01", urls[0])
            self.assertIn("endDate=2026-10-10", urls[0])
            self.assertEqual((result["series"], result["series_game"], result["if_necessary"], result["start_time_tbd"]),
                             ("AL Division Series", 2, True, True))
            self.assertEqual(result["preferred_source"]["channel"], "ESPN")

    def test_final_game_prefers_mlb_archive_over_linear_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog = self.catalog(self.config(Path(directory)), state="Final")
            game = catalog.games("2026-09-02")["games"][0]

            self.assertEqual(game["preferred_source"]["provider"], "mlb")

    def test_schedule_response_is_cached_by_date(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            calls = 0
            body = json.dumps(self.response()).encode("utf-8")

            def opener(request, timeout):
                nonlocal calls
                calls += 1
                return io.BytesIO(body)

            client = MlbScheduleClient(config.mlb.schedule_url, opener=opener)
            client.games("2026-09-02")
            client.games("2026-09-02")
            self.assertEqual(calls, 1)

    def test_locate_finds_a_game_by_id_on_its_new_date_or_reports_it_gone(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.config(Path(directory))
            response = self.response(state="Preview")
            postponed = response["dates"][0]["games"][0]
            postponed["status"]["detailedState"] = "Postponed"
            moved = json.loads(json.dumps(postponed))
            moved.update(officialDate="2026-09-03", gameDate="2026-09-03T17:05:00Z")
            moved["status"]["detailedState"] = "Scheduled"
            response["dates"].append({"games": [moved]})
            bodies, urls = [response, {"totalGames": 0, "dates": []}], []

            def opener(request, timeout):
                urls.append(request.full_url)
                return io.BytesIO(json.dumps(bodies.pop(0)).encode())
            catalog = BaseballCatalog(config, MlbScheduleClient(config.mlb.schedule_url, opener=opener))
            game = catalog.locate(42)
            self.assertIn("gamePk=42", urls[0])
            self.assertEqual((game["official_date"], game["start_time"], game["status"]),
                             ("2026-09-03", "2026-09-03T17:05:00Z", "Scheduled"))
            # An if-necessary game that was not needed is no longer listed at all.
            self.assertIsNone(catalog.locate(43))


if __name__ == "__main__":
    unittest.main()
