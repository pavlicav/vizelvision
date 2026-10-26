"""Leases ride out TV Thing not answering (its control service restarting), and nothing else."""
import io
import json
import unittest
from http.client import IncompleteRead
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from roku_stream import tv_control
from roku_stream.config import TvThingConfig
from roku_stream.master import MasterStreamError
from roku_stream.tv_control import (OUTAGE_GRACE_SECONDS, OUTAGE_PROBE_SECONDS, OUTAGE_RETRY_SECONDS,
                                    RokuLease, TvControl, TvThingUnavailable)

TARGET = {"source_id": "tv-thing-digital", "channel_id": "abc", "quality": "medium"}
URL = "http://tv.test/tv/stream/digital.m3u8"


class Clock:
    """tv_control's time: monotonic and wall clock move together, by hand."""
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def time(self):
        return 1_800_000_000.0 + self.now


def unavailable(code=503):
    return HTTPError("http://tv.test/tv/api/v1/status", code, "Unavailable", {}, io.BytesIO(b"<html>busy</html>"))


class OutageTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        patcher = patch.object(tv_control, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls, self.responses = [], []

        def opener(request, timeout=None):
            self.calls.append((request.full_url.rsplit("/api/v1/", 1)[1], json.loads(request.data) if request.data else None, timeout))
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return io.BytesIO(json.dumps({"api_version": "v1", **result}).encode())
        self.client = TvControl(TvThingConfig(enabled=True, base_url="http://tv.test/tv/"), opener=opener)

    # TV Thing's answers.
    def lock(self, **extra):
        return {"token": "private", "lock": {"expires_at": self.clock.time() + 90}, **extra}

    def status(self, generation="g1", owner=None, ready=True, lane="digital", selection=None):
        stream = {"generation": generation, "ready": ready,
                  "playback": [{"protocol": "hls", "url": f"stream/{lane}.m3u8"}]}
        return {"locks": {lane: {"owner": owner or self.client.owner}},
                "lanes": {lane: {"selection": selection or {"id": "abc"}, "quality": "medium", "stream": stream}}}

    def lease(self):
        self.responses = [self.lock()]
        lease = self.client.acquire(TARGET)
        lease.generation = "g1"
        self.responses = [self.status()]
        self.assertEqual(lease.check(), URL)
        self.calls.clear()
        return lease

    def test_the_kinds_of_no_answer(self):
        for error in (unavailable(503), unavailable(502), unavailable(504), URLError("refused"),
                      ConnectionRefusedError(), TimeoutError(), IncompleteRead(b"")):
            with self.subTest(error=type(error).__name__):
                self.responses = [error]
                with self.assertRaises(TvThingUnavailable):
                    self.client.request("status")
        for error in (unavailable(500), unavailable(409), unavailable(423)):
            with self.subTest(code=error.code):
                self.responses = [error]
                with self.assertRaises(MasterStreamError) as caught:
                    self.client.request("status")
                self.assertNotIsInstance(caught.exception, TvThingUnavailable)

    def test_an_outage_under_the_grace_keeps_the_feed(self):
        lease = self.lease()
        self.clock.now += 2
        self.responses = [unavailable()]
        self.assertEqual(lease.check(), URL)
        # Between probes it does not ask at all.
        self.clock.now += OUTAGE_RETRY_SECONDS - 1
        self.assertEqual(lease.check(), URL)
        self.assertEqual(len(self.calls), 1)
        # Then one short probe at a time.
        self.clock.now += 1
        self.responses = [ConnectionRefusedError()]
        self.assertEqual(lease.check(), URL)
        self.assertEqual(self.calls[-1], ("status", None, OUTAGE_PROBE_SECONDS))
        # Back (its lock renewal now due): it probes, renews, confirms, and carries on.
        self.clock.now += OUTAGE_RETRY_SECONDS + 20
        self.assertGreater(self.clock.now, lease.renew_at)
        self.responses = [self.status(), self.lock(renewed=True), self.status()]
        self.assertEqual(lease.check(), URL)
        self.assertEqual([c[0] for c in self.calls[-3:]], ["status", "tuner/lock", "status"])
        self.assertIsNone(lease.outage_since)

    def test_an_outage_past_the_grace_fails(self):
        lease = self.lease()
        self.clock.now += 2
        self.responses = [unavailable()]
        lease.check()
        self.clock.now += OUTAGE_GRACE_SECONDS
        self.responses = [unavailable()]
        with self.assertRaisesRegex(TvThingUnavailable, f"has not answered for {OUTAGE_GRACE_SECONDS} s"):
            lease.check()

    def test_the_grace_also_ends_between_probes(self):
        lease = self.lease()
        self.responses = [unavailable()]
        lease.check()
        lease.retry_at = float("inf")
        self.clock.now += OUTAGE_GRACE_SECONDS
        with self.assertRaises(TvThingUnavailable):
            lease.check()

    def test_refusals_fail_at_once(self):
        for refusal in (unavailable(423), unavailable(409), unavailable(400)):
            with self.subTest(code=refusal.code):
                lease = self.lease()
                self.responses = [refusal]
                with self.assertRaises(MasterStreamError) as caught:
                    lease.check()
                self.assertNotIsInstance(caught.exception, TvThingUnavailable)

    def test_a_change_seen_when_it_answers_again_fails(self):
        lease = self.lease()
        self.responses = [unavailable()]
        lease.check()
        self.clock.now += OUTAGE_RETRY_SECONDS
        self.responses = [self.status(generation="g2"), self.status(generation="g2")]
        with self.assertRaisesRegex(MasterStreamError, "generation changed"):
            lease.check()
        lease = self.lease()
        self.responses = [unavailable()]
        lease.check()
        self.clock.now += OUTAGE_RETRY_SECONDS
        self.responses = [self.status(owner="VCR"), self.status(owner="VCR")]
        with self.assertRaisesRegex(MasterStreamError, "ownership was lost"):
            lease.check()

    def test_a_lease_never_ready_does_not_ride_out(self):
        self.responses = [self.lock()]
        lease = self.client.acquire(TARGET)
        lease.generation = "g1"
        self.responses = [self.status(ready=False)]
        self.assertIsNone(lease.check())
        self.responses = [unavailable()]
        with self.assertRaises(TvThingUnavailable):
            lease.check()

    def test_the_lock_outlasts_the_grace(self):
        """An outage that starts just before a renewal still ends inside the lock: renewals come a
        third of the way in, so a 90 s lock leaves 60 s, and the lease's own deadline is not reached."""
        self.responses = [self.lock()]
        lease = self.client.acquire(TARGET)
        lease.generation = "g1"
        self.assertEqual(lease.renew_at, self.clock.now + 30)
        self.clock.now += 29
        self.responses = [self.status()]
        lease.check()
        self.clock.now += 0.5
        self.responses = [unavailable()]
        lease.check()
        self.clock.now += OUTAGE_GRACE_SECONDS - 1
        self.assertLess(self.clock.now, lease.deadline)
        self.responses = [self.status(), self.lock(renewed=True), self.status()]
        self.assertEqual(lease.check(), URL)

    def test_the_roku_lease_rides_out_too(self):
        target = {"source_id": "youtube-tv", "channel_id": "NBC"}
        lease = RokuLease.adopt(self.client, target, {"generation": "r1"})
        status = lambda generation="r1": self.status(generation=generation, owner="VizelVision master", lane="roku",
                                                     selection=target)
        self.responses = [status()]
        self.assertEqual(lease.check(), "http://tv.test/tv/stream/roku.m3u8")
        self.responses = [unavailable()]
        self.assertEqual(lease.check(), "http://tv.test/tv/stream/roku.m3u8")
        self.clock.now += OUTAGE_RETRY_SECONDS
        self.responses = [status(generation="r2"), status(generation="r2")]
        with self.assertRaisesRegex(MasterStreamError, "changed since it was verified"):
            lease.check()


if __name__ == "__main__":
    unittest.main()
