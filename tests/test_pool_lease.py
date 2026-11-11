"""Digital tunes go through TV Thing's tuner pool: it picks this box's tuner or its peer's."""
import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from roku_stream import tv_control
from roku_stream.config import TvThingConfig
from roku_stream.master import MasterStreamError
from roku_stream.tv_control import (PEER_SETTLE_SECONDS, PoolLease, PoolSharedLease, SharedLease, TvControl,
                                    TvThingUnavailable)

TARGET = {"source_id": "tv-thing-digital", "channel_id": "wttg_5_1", "quality": "medium"}
HERE, PEER = "viviserv:digital", "viviserv2:digital"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def time(self):
        return 1_800_000_000.0 + self.now


def refused(code, **body):
    payload = {"api_version": "v1", "ok": False, "error": {"code": "locked", "message": "Every tuner is locked"}, **body}
    return HTTPError("http://tv.test/tv/api/v1/x", code, "Locked", {}, io.BytesIO(json.dumps(payload).encode()))


class PoolLeaseTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        patcher = patch.object(tv_control, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls, self.responses = [], []

        def opener(request, timeout=None):
            self.calls.append((request.full_url.rsplit("/api/v1/", 1)[1], json.loads(request.data) if request.data else None))
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return io.BytesIO(json.dumps({"api_version": "v1", **result}).encode())
        self.client = TvControl(TvThingConfig(enabled=True, base_url="http://tv.test/tv/"), opener=opener)

    # TV Thing's answers.
    def tuned(self, tuner=HERE, generation="g1", quality="medium", channel="wttg_5_1"):
        peer = not tuner.startswith("viviserv:")
        path = "/stream/peer/digital.m3u8" if peer else "/stream/digital.m3u8"
        return {"ok": True, "lane": tuner if peer else "digital", "tuner": tuner, "relayed": peer,
                "selection": {"id": channel}, "quality": quality,
                "stream": {"generation": generation, "playlist_path": path,
                           "playback": [{"protocol": "hls", "url": path.lstrip("/")}]}}

    def lock(self, **extra):
        return {"token": "private", "lock": {"expires_at": self.clock.time() + 90}, **extra}

    def tuner(self, tuner=HERE, generation="g1", owner=None, channel="wttg_5_1", ready=True, quality="medium",
              reachable=True, reason=None):
        local = tuner.startswith("viviserv:")
        lock = None if owner is False else {"owner": owner or self.client.owner, "lane": tuner,
                                             **({"reason": reason} if reason else {})}
        return {"id": tuner, "local": local, "reachable": reachable, "selection": {"id": channel, "number": "5.1"},
                "quality": quality, "lock": lock,
                "stream": {"id": generation, "state": "ready", "active": True, "ready": ready,
                           "playlist_path": "/stream/digital.m3u8" if local else "/stream/peer/digital.m3u8",
                           # The pool listing leaves a peer's playback as the peer wrote it.
                           "playback": [{"protocol": "hls", "url": "stream/digital.m3u8"}]}}

    def listing(self, *tuners):
        return {"tuners": list(tuners)}

    def test_a_tune_on_this_boxs_tuner(self):
        self.responses = [self.tuned(), self.lock()]
        lease = self.client.acquire(TARGET)
        self.assertIsInstance(lease, PoolLease)
        self.assertEqual(self.calls[0], ("tune", {"source": "digital", "channel_id": "wttg_5_1", "quality": "medium"}))
        self.assertEqual(self.calls[1][1]["lane"], HERE)
        self.assertEqual((lease.lane, lease.tuner, lease.generation), ("digital", HERE, "g1"))
        lease.tune()                       # the pool tuned it already
        self.assertEqual(len(self.calls), 2)
        self.responses = [self.listing(self.tuner(PEER, owner=False), self.tuner())]
        self.assertEqual(lease.check(), "http://tv.test/tv/stream/digital.m3u8")
        self.responses = [self.lock(renewed=True), {}]
        lease.renew(force=True)
        self.assertEqual(self.calls[-1][1], {"lane": HERE, "owner": self.client.owner, "duration_seconds": 90,
                                             "until": "duration", "token": "private"})
        self.assertTrue(lease.release())
        self.assertEqual(self.calls[-1], ("tuner/lock/release", {"lane": HERE, "token": "private"}))

    def test_a_tune_relayed_from_the_peers_tuner(self):
        self.responses = [self.tuned(PEER), self.lock()]
        lease = self.client.acquire(TARGET)
        self.assertEqual((lease.tuner, lease.local), (PEER, False))
        # Control reads its peer every couple of seconds: at first the listing shows the
        # peer's tuner as it was, before this tune and lock. That is not ready yet, not a fault.
        self.responses = [self.listing(self.tuner(PEER, generation="g0", owner=False))]
        self.assertIsNone(lease.check())
        self.responses = [self.listing(self.tuner(PEER))]
        self.assertEqual(lease.check(), "http://tv.test/tv/stream/peer/digital.m3u8")
        # Once settled, a change is a change.
        self.clock.now += PEER_SETTLE_SECONDS
        self.responses = [self.listing(self.tuner(PEER, generation="g2"))]
        with self.assertRaisesRegex(MasterStreamError, "generation changed"):
            lease.check()
        self.responses = [self.listing(self.tuner(PEER, owner="Watch page"))]
        with self.assertRaisesRegex(MasterStreamError, "ownership was lost"):
            lease.check()

    def test_this_boxs_tuner_never_settles(self):
        """This box's own listing is current: a mismatch fails at once."""
        self.responses = [self.tuned(), self.lock()]
        lease = self.client.acquire(TARGET)
        self.responses = [self.listing(self.tuner(generation="g0"))]
        with self.assertRaisesRegex(MasterStreamError, "generation changed"):
            lease.check()

    def test_the_peer_not_answering_is_ridden_out(self):
        self.responses = [self.tuned(PEER), self.lock(), self.listing(self.tuner(PEER))]
        lease = self.client.acquire(TARGET)
        url = lease.check()
        self.responses = [self.listing(self.tuner(PEER, reachable=False))]
        self.assertEqual(lease.check(), url)
        self.assertIsNotNone(lease.outage_since)
        self.clock.now += tv_control.OUTAGE_GRACE_SECONDS
        self.responses = [{"lanes": {}, "locks": {}}, self.lock(renewed=True),
                          self.listing(self.tuner(PEER, reachable=False))]
        with self.assertRaises(TvThingUnavailable):
            lease.check()

    def test_watching_along_a_tuner_someone_else_holds(self):
        self.responses = [self.tuned(PEER, generation="v1", quality="high"), refused(423),
                          self.listing(self.tuner(PEER, generation="v1", owner="VCR", quality="high"))]
        lease = self.client.acquire(TARGET)
        self.assertIsInstance(lease, PoolSharedLease)
        self.assertIsInstance(lease, SharedLease)
        self.assertEqual((lease.tuner, lease.shared_with, lease.generation, lease.target["quality"]),
                         (PEER, "VCR", "v1", "high"))
        self.responses = [self.listing(self.tuner(PEER, generation="v1", owner="VCR", quality="high"))] * 2
        lease.renew(force=True)
        lease.tune()
        self.assertEqual(lease.check(), "http://tv.test/tv/stream/peer/digital.m3u8")
        self.assertTrue(lease.release())
        self.assertEqual([c[0] for c in self.calls], ["tune", "tuner/lock", "tuners", "tuners", "tuners"])

    def test_every_tuner_locked_names_the_holder(self):
        self.responses = [refused(423, tuner=HERE),
                          self.listing(self.tuner(channel="wjla_7_1", owner="VCR", reason="recording Jeopardy!"))]
        with self.assertRaisesRegex(MasterStreamError,
                                    r"tuner viviserv:digital is reserved by VCR \(recording Jeopardy!\) on 5.1") as caught:
            self.client.acquire(TARGET)
        self.assertEqual(caught.exception.details.get("http_status"), 423)

    def test_a_stream_reused_at_another_quality_is_tuned_as_asked(self):
        self.responses = [self.tuned(quality="high"), self.lock()]
        lease = self.client.acquire(TARGET)
        self.responses = [self.tuned(generation="g2")]
        lease.tune()
        self.assertEqual(self.calls[-1], ("tune", {"source": "digital", "channel_id": "wttg_5_1", "quality": "medium",
                                                   "token": "private", "tuner": HERE}))
        self.assertEqual(lease.generation, "g2")

    def test_a_tv_thing_from_before_the_pool(self):
        """No tuner in the tune's answer: its one digital lane, checked by status as before."""
        tuned = self.tuned()
        for key in ("tuner", "relayed"):
            tuned.pop(key)
        self.responses = [tuned, self.lock()]
        lease = self.client.acquire(TARGET)
        self.assertEqual((lease.tuner, self.calls[1][1]["lane"]), ("digital", "digital"))
        status = {"locks": {"digital": {"owner": self.client.owner}},
                  "lanes": {"digital": {"selection": {"id": "wttg_5_1"}, "quality": "medium", "stream": {
                      "generation": "g1", "ready": True, "playback": [{"protocol": "hls", "url": "stream/digital.m3u8"}]}}}}
        self.responses = [{"tuners": []}, status]
        self.assertEqual(lease.check(), "http://tv.test/tv/stream/digital.m3u8")

    def test_a_failed_lock_after_the_tune_leaves_no_token(self):
        self.responses = [self.tuned(), refused(500)]
        with self.assertRaises(MasterStreamError):
            self.client.acquire(TARGET)
        self.assertEqual([c[0] for c in self.calls], ["tune", "tuner/lock"])


if __name__ == "__main__":
    unittest.main()
