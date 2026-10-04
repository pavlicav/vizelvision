import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from roku_stream.scheduler import Scheduler, utc_now


class SchedulerTests(unittest.TestCase):
    def test_future_job_is_persisted_and_can_be_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "jobs.json"
            scheduler = Scheduler(state, lambda channel: {"channel": channel})
            try:
                job = scheduler.add("ESPN", utc_now() + timedelta(hours=1))
                self.assertTrue(state.is_file())
                self.assertEqual(scheduler.get(job.id).status, "queued")
                cancelled = scheduler.cancel(job.id)
                self.assertEqual(cancelled.status, "cancelled")
            finally:
                scheduler.close()


if __name__ == "__main__":
    unittest.main()
