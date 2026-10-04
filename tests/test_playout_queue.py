import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path

from roku_stream.playout_queue import PlayoutQueue
from roku_stream.scheduler import utc_now
from roku_stream.errors import ControlBusyError


class PlayoutQueueTests(unittest.TestCase):
    def test_busy_controller_keeps_queue_item_for_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            completed = threading.Event()
            calls = []
            def execute(channel):
                calls.append(channel)
                if len(calls) == 1:
                    raise ControlBusyError("manual cue running")
                completed.set()
                return {"channel": channel}
            queue = PlayoutQueue(Path(directory) / "queue.json", execute, lambda *args: {"finished": True}, poll_seconds=.01)
            try:
                item = queue.add_after_game("NBC", game_pk=123, game_date="2026-09-05", game_title="Game")
                self.assertTrue(completed.wait(1))
                queue.close()
                self.assertEqual(queue.get(item.id).status, "succeeded")
                self.assertEqual(calls, ["NBC", "NBC"])
            finally:
                queue.close()

    def test_items_are_persisted_and_can_be_reordered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "queue.json"
            queue = PlayoutQueue(
                state,
                lambda channel: {"channel": channel},
                lambda game_pk, game_date: {"finished": False},
                start_worker=False,
            )
            try:
                first = queue.add_at_time("ESPN", utc_now() + timedelta(hours=2))
                second = queue.add_after_game(
                    "TBS",
                    game_pk=123,
                    game_date="2026-09-02",
                    game_title="Away at Home",
                )

                queue.move(second.id, "up")

                self.assertTrue(state.is_file())
                self.assertEqual(
                    [item.channel for item in queue.list()[:2]], ["TBS", "ESPN"]
                )
                removed = queue.remove(first.id)
                self.assertEqual(removed.channel, "ESPN")
            finally:
                queue.close()

    def test_after_game_releases_head_when_mlb_reports_final(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = threading.Event()
            calls: list[str] = []
            checks = {"count": 0}

            def status(game_pk, game_date):
                checks["count"] += 1
                finished = checks["count"] >= 2
                return {
                    "state": "Final" if finished else "Live",
                    "status": "Final" if finished else "In Progress",
                    "finished": finished,
                }

            def execute(channel):
                calls.append(channel)
                completed.set()
                return {"channel": channel}

            queue = PlayoutQueue(
                Path(directory) / "queue.json",
                execute,
                status,
                poll_seconds=0.01,
            )
            try:
                item = queue.add_after_game(
                    "ESPN",
                    game_pk=456,
                    game_date="2026-09-02",
                    game_title="Away at Home",
                )

                self.assertTrue(completed.wait(timeout=1))
                self.assertEqual(calls, ["ESPN"])
                self.assertEqual(queue.get(item.id).status, "succeeded")
                self.assertGreaterEqual(checks["count"], 2)
            finally:
                queue.close()


if __name__ == "__main__":
    unittest.main()
