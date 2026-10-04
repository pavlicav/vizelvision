import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from roku_stream.config import MasterConfig, TvThingConfig, load_config
from roku_stream.errors import ConfigError
from roku_stream.master import MasterStreamError
from roku_stream.master_worker import MasterClient, MasterWorker
from roku_stream.tv_control import Lease, TvControl, target_from


TARGET = {"source_id": "tv-thing-digital", "channel_id": "abc", "quality": "medium"}


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.responses = []
        def opener(request, **kwargs):
            self.calls.append((request.full_url, json.loads(request.data) if request.data else None))
            result = self.responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return io.BytesIO(json.dumps({"api_version": "v1", **result}).encode())
        self.client = TvControl(TvThingConfig(enabled=True, base_url="http://tv.test/tv/"), opener=opener)

    def lock(self, token="private", **extra):
        return {"token": token, "lock": {"expires_at": time.time() + 90}, **extra}

    def test_acquire_is_not_a_tune_and_renew_uses_token(self):
        self.responses = [self.lock(), self.lock(renewed=True), {}]
        lease = self.client.acquire(TARGET)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn("token", self.calls[0][1])
        lease.renew(force=True)
        self.assertEqual(self.calls[1][1]["token"], "private")
        self.assertNotIn("override", self.calls[1][1])
        self.assertTrue(lease.release())
        self.assertTrue(self.calls[-1][0].endswith("/tv/api/v1/tuner/lock/release"))

    def test_reacquisition_during_renew_is_released_and_rejected(self):
        self.responses = [self.lock(), self.lock(token="new", renewed=False), {}]
        lease = self.client.acquire(TARGET)
        with self.assertRaisesRegex(MasterStreamError, "ownership changed"):
            lease.renew(force=True)
        self.assertEqual(self.calls[-1][1]["token"], "new")
        self.assertIsNone(lease.token)

    def test_expiry_never_reacquires_or_tunes(self):
        self.responses = [self.lock()]
        lease = self.client.acquire(TARGET)
        lease.deadline = time.monotonic() - 1
        with self.assertRaisesRegex(MasterStreamError, "expired"):
            lease.renew(force=True)
        self.assertEqual(len(self.calls), 1)

    def test_invalid_expiry_releases_known_token(self):
        self.responses = [{"token": "private", "lock": {"expires_at": "bad"}}, {}]
        with self.assertRaisesRegex(MasterStreamError, "expiry"):
            self.client.acquire(TARGET)
        self.assertEqual(self.calls[-1][1]["token"], "private")

    def test_lost_acquisition_response_is_not_retried(self):
        self.responses = [TimeoutError()]
        with self.assertRaises(MasterStreamError):
            self.client.acquire(TARGET)
        self.assertEqual(len(self.calls), 1)

    def test_selection_generation_and_url_must_match(self):
        self.responses = [self.lock()]
        lease = self.client.acquire(TARGET)
        lease.generation = "generation1"
        lane = {"selection": {"id": "abc"}, "quality": "medium", "stream": {
            "generation": "generation1", "ready": True,
            "playback": [{"protocol": "hls", "url": "stream/digital.m3u8"}]}}
        status = {"locks": {"digital": {"owner": self.client.owner}}, "lanes": {"digital": lane}}
        self.responses = [status]
        self.assertEqual(lease.check(), "http://tv.test/tv/stream/digital.m3u8")
        lane["stream"]["generation"] = "generation2"
        self.responses = [status]
        with self.assertRaisesRegex(MasterStreamError, "generation changed"):
            lease.check()
        lane["stream"]["generation"] = "generation1"
        lane["stream"]["playback"][0]["url"] = "http://other.test/feed.m3u8"
        self.responses = [status]
        with self.assertRaisesRegex(MasterStreamError, "outside"):
            lease.check()

    def locked_status(self, channel="abc", generation="g1"):
        lane = {"selection": {"id": channel, "number": "7.1"}, "quality": "high", "stream": {
            "generation": generation, "ready": True,
            "playback": [{"protocol": "hls", "url": "stream/digital.m3u8"}]}}
        return {"locks": {"digital": {"owner": "VCR", "reason": "recording Jeopardy!"}}, "lanes": {"digital": lane}}

    def refused(self):
        return HTTPError("http://tv.test/tv/api/v1/tuner/lock", 423, "Locked", {}, io.BytesIO(b"{}"))

    def test_locked_lane_on_requested_channel_is_shared_read_only(self):
        self.responses = [self.refused(), self.locked_status(), self.locked_status(), self.locked_status()]
        lease = self.client.acquire(TARGET)
        self.assertEqual((lease.shared_with, lease.generation, lease.target["quality"]), ("VCR", "g1", "high"))
        lease.renew(force=True)
        lease.tune()
        self.assertEqual(lease.check(), "http://tv.test/tv/stream/digital.m3u8")
        self.assertTrue(lease.release())
        paths = [url.rsplit("/api/v1/", 1)[1] for url, _ in self.calls]
        self.assertEqual(paths, ["tuner/lock", "status", "status", "status"])
        self.responses = [self.locked_status(generation="g2")]
        with self.assertRaisesRegex(MasterStreamError, "generation changed"):
            lease.check()

    def test_locked_lane_on_other_channel_names_holder(self):
        self.responses = [self.refused(), self.locked_status(channel="other")]
        with self.assertRaisesRegex(MasterStreamError, r"reserved by VCR \(recording Jeopardy!\) on 7.1") as caught:
            self.client.acquire(TARGET)
        self.assertEqual(caught.exception.details.get("http_status"), 423)
        self.assertEqual(len(self.calls), 2)

    def test_release_failure_does_not_stop_shared_stream(self):
        self.responses = [self.lock(), TimeoutError()]
        lease = self.client.acquire(TARGET)
        self.assertFalse(lease.release())
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(self.calls[-1][0].endswith("release"))


class WorkerTests(unittest.TestCase):
    def setUp(self):
        config = SimpleNamespace(master=MasterConfig(enabled=True), tv_thing=TvThingConfig(enabled=True))
        self.worker = MasterWorker(config, tv=Mock(), status_reader=lambda: {"ready": True, "source": {"id": "publisher"}})
        self.worker.output = Mock()
        self.worker.output.healthy.return_value = True
        self.worker.output.status.return_value = {}
        self.worker.publisher_ready = True
        self.worker.output_started = time.monotonic()
        self.worker._refresh()

    def entry(self, lane="digital"):
        lease = Mock(lane=lane, target=TARGET, generation="generation1")
        lease.check.return_value = "http://tv.test/feed.m3u8"
        decoder = Mock()
        decoder.ready.return_value = True
        decoder.status.return_value = {'video': {'age_seconds': 0.1, 'buffers': 10},
                                       'audio': {'age_seconds': 1.1, 'buffers': 10}}
        return {"lease": lease, "decoder": decoder, "slot": 1, "was_ready": True, "check_at": 0}

    def test_preview_requires_fresh_ready_input_and_is_revoked_on_drop(self):
        entry = self.entry()
        entry['url'] = 'http://tv.test/stream/digital.m3u8'
        self.worker.inputs['next'] = entry
        self.worker.prepared = 'next'
        self.worker._refresh()
        self.assertEqual(self.worker.preview('next')['url'], entry['url'])
        self.assertNotIn('url', self.worker.status()['prepared'])
        self.worker.preview_inputs['next']['expires'] = time.monotonic() - 1
        with self.assertRaises(MasterStreamError):
            self.worker.preview('next')
        self.worker._refresh()
        entry['decoder'].ready.return_value = False
        self.worker._refresh()
        with self.assertRaises(MasterStreamError):
            self.worker.preview('next')
        entry['decoder'].ready.return_value = True
        self.worker._refresh()
        self.worker._drop('next')
        with self.assertRaises(MasterStreamError):
            self.worker.preview('next')

    def test_take_rejects_stale_id_without_switching(self):
        self.worker.prepared = "new"
        self.worker.inputs["new"] = self.entry()
        with self.assertRaisesRegex(MasterStreamError, "changed"):
            self.worker._take({"prepared_id": "old"})
        self.worker.output.take.assert_not_called()

    def test_take_renews_checks_and_releases_old_source(self):
        old, prepared = self.entry("analog"), self.entry()
        self.worker.inputs = {"old": old, "new": prepared}
        self.worker.active, self.worker.prepared = "old", "new"
        self.worker._take({"prepared_id": "new"})
        prepared["lease"].renew.assert_called_once_with(force=True)
        prepared["lease"].check.assert_called_once()
        self.worker.output.take.assert_called_once_with(1)
        old["lease"].release.assert_called_once()
        self.assertEqual(self.worker.active, "new")
        self.assertIsNone(self.worker.prepared)

    def test_take_rejects_lost_readiness_without_switching(self):
        for lease_ready, media_ready in ((False, True), (True, False)):
            with self.subTest(lease_ready=lease_ready, media_ready=media_ready):
                entry = self.entry()
                entry['lease'].check.return_value = lease_ready
                entry['decoder'].ready.return_value = media_ready
                self.worker.inputs['next'] = entry
                self.worker.prepared = 'next'
                with self.assertRaisesRegex(MasterStreamError, 'no longer ready'):
                    self.worker._take({'prepared_id': 'next'})
                self.worker.output.take.assert_not_called()

    def test_generation_loss_returns_to_fallback_and_releases(self):
        entry = self.entry()
        entry["lease"].check.side_effect = MasterStreamError("generation changed")
        self.worker.inputs["live"] = entry
        self.worker.active = "live"
        self.worker._tick()
        self.worker.output.take.assert_called_once_with(0)
        entry["decoder"].close.assert_called_once()
        entry["lease"].release.assert_called_once()
        self.assertIsNone(self.worker.status()["on_air"])

    def test_prepared_failure_preserves_other_lane_on_air(self):
        active, prepared = self.entry("analog"), self.entry()
        prepared["decoder"].poll.side_effect = MasterStreamError("decoder failed")
        self.worker.inputs = {"live": active, "next": prepared}
        self.worker.active, self.worker.prepared = "live", "next"
        self.worker._tick()
        self.worker.output.take.assert_not_called()
        self.assertEqual(self.worker.active, "live")
        self.assertIsNone(self.worker.prepared)

    def test_prepared_input_settling_again_is_kept(self):
        # A fresh Roku capture re-anchored its timestamps 4 s after reading began
        # (2026-09-30): the prepared input briefly reports not ready.
        entry = self.entry()
        self.worker.inputs['next'] = entry
        self.worker.prepared = 'next'
        entry['decoder'].ready.return_value = False
        self.worker._tick()
        self.assertEqual(self.worker.prepared, 'next')
        entry['decoder'].ready.return_value = True
        self.worker._tick()
        self.assertNotIn('unready_since', entry)
        self.assertIsNone(self.worker.status()['error'])
        entry['decoder'].close.assert_not_called()

    def test_prepared_input_unready_past_settle_window_is_dropped(self):
        entry = self.entry()
        self.worker.inputs['next'] = entry
        self.worker.prepared = 'next'
        entry['decoder'].ready.return_value = False
        entry['unready_since'] = time.monotonic() - self.worker.PREPARED_SETTLE_SECONDS
        self.worker._tick()
        self.assertIsNone(self.worker.prepared)
        self.assertIn('stopped arriving', self.worker.status()['error'])
        self.assertFalse(self.worker.status()['last_input_failure']['was_on_air'])
        entry['decoder'].close.assert_called_once()

    def test_busy_rejects_duplicate_prepare_but_accepts_cancel(self):
        self.worker.submit("prepare", TARGET)
        with self.assertRaisesRegex(MasterStreamError, "already running"):
            self.worker.submit("prepare", TARGET)
        self.worker.submit("fallback", {})
        self.assertTrue(self.worker.cancel.is_set())
        self.assertTrue(self.worker.pending_fallback)

    def test_same_lane_prepare_falls_back_before_acquisition(self):
        entry = self.entry()
        self.worker.inputs["live"] = entry
        self.worker.active = "live"
        def refuse(_target):
            self.worker.output.take.assert_called_once_with(0)
            entry["lease"].release.assert_called_once()
            raise MasterStreamError("reserved by another owner")
        self.worker.tv.acquire.side_effect = refuse
        with self.assertRaisesRegex(MasterStreamError, "another owner"):
            self.worker._prepare(TARGET)
        self.assertIsNone(self.worker.active)

    def test_conflicting_other_lane_preserves_active_feed(self):
        self.worker.inputs["live"] = self.entry("analog")
        self.worker.active = "live"
        self.worker.tv.acquire.side_effect = MasterStreamError("locked")
        with self.assertRaisesRegex(MasterStreamError, "locked"):
            self.worker._prepare(TARGET)
        self.worker.output.take.assert_not_called()
        self.assertEqual(self.worker.active, "live")

    def test_decoder_stall_falls_back(self):
        entry = self.entry()
        entry["decoder"].ready.return_value = False
        self.worker.inputs["live"] = entry
        self.worker.active = "live"
        self.worker._tick()
        self.worker.output.take.assert_called_once_with(0)
        self.assertIn("Input paused", self.worker.status()["error"])
        failure = self.worker.status()['last_input_failure']
        self.assertEqual(failure['target']['channel_id'], 'abc')
        self.assertTrue(failure['was_on_air'])
        self.assertEqual(failure['tracks']['audio']['age_seconds'], 1.1)

    def riding_entry(self):
        entry = self.entry()
        entry['url'] = 'http://tv.test/feed.m3u8'
        entry['decoder'].RIDES_OUT_ON_AIR = True
        entry['decoder'].ride_out.return_value = True
        entry['decoder'].reanchors = 0
        entry['decoder'].ready.return_value = False
        self.worker.inputs['live'] = entry
        self.worker.active = 'live'
        self.worker._tick()
        return entry

    def test_a_live_input_that_stalls_on_air_holds_its_picture_and_carries_on(self):
        entry = self.riding_entry()
        self.worker.output.take.assert_not_called()
        entry['decoder'].ride_out.assert_called_once_with(True)
        self.assertEqual(self.worker.active, 'live')
        self.assertEqual(self.worker.status()['stall']['target']['channel_id'], 'abc')
        self.worker._tick()
        self.worker.output.take.assert_not_called()
        entry['decoder'].ready.return_value = True
        self.worker._tick()
        entry['decoder'].ride_out.assert_called_with(False)
        self.assertIsNone(self.worker.status()['stall'])
        self.assertIsNone(self.worker.recovering)
        self.assertIsNone(self.worker.status()['last_input_failure'])

    def test_a_stall_longer_than_the_hold_goes_to_the_test_card_and_recovers_there(self):
        entry = self.riding_entry()
        entry['stalled_since'] -= self.worker.STALL_HOLD_SECONDS
        self.worker._tick()
        self.worker.output.take.assert_called_once_with(0)
        entry['decoder'].ride_out.assert_called_with(False)
        self.assertEqual(self.worker.recovering, 'live')
        self.assertIsNone(self.worker.status()['stall'])
        self.assertTrue(self.worker.status()['last_input_failure']['was_on_air'])

    def test_an_input_failing_during_its_recovery_was_on_air(self):
        # 10:05:55 on 2026-10-04: the failure overwrote "recovering" with was_on_air false
        # between two of the queue's polls, so nothing put the game back on.
        entry = self.recovering_entry()
        entry['decoder'].poll.side_effect = MasterStreamError('Input audio timestamps changed (delta_ms=-42.666666)')
        self.worker._tick()
        failure = self.worker.status()['last_input_failure']
        self.assertEqual((failure['was_on_air'], failure['during_recovery']), (True, True))
        self.assertIsNone(self.worker.recovering)

    def recovering_entry(self):
        entry = self.entry()
        entry['url'] = 'http://tv.test/feed.m3u8'
        entry['decoder'].ready.return_value = False
        self.worker.inputs['live'] = entry
        self.worker.active = 'live'
        self.worker._tick()
        self.assertEqual(self.worker.recovering, 'live')
        entry['decoder'].ready.return_value = True
        entry['recovery_ready_since'] = time.monotonic() - 1
        return entry

    def test_short_stall_recovers_same_source_after_fresh_tracks_and_lease_check(self):
        entry = self.recovering_entry()
        self.worker._tick()
        self.assertEqual(self.worker.active, 'live')
        self.assertIsNone(self.worker.recovering)
        self.assertEqual(self.worker.output.take.call_args_list[-1].args, (1,))
        entry['lease'].renew.assert_called_once_with(force=True)
        entry['lease'].release.assert_not_called()
        self.assertIsNone(self.worker.status()['error'])

    def test_recovery_lease_loss_cannot_return_to_air(self):
        entry = self.recovering_entry()
        entry['lease'].check.side_effect = MasterStreamError('generation changed')
        self.worker._tick()
        self.assertIsNone(self.worker.active)
        self.assertIsNone(self.worker.recovering)
        self.assertEqual(self.worker.output.take.call_count, 1)
        entry['lease'].release.assert_called_once()

    def test_recovery_timeout_discards_input(self):
        entry = self.recovering_entry()
        entry['recovery_deadline'] = time.monotonic() - 1
        self.worker._tick()
        self.assertIsNone(self.worker.recovering)
        self.assertIn('8 seconds', self.worker.status()['error'])
        entry['decoder'].close.assert_called_once()

    def test_pending_manual_command_prevents_recovery_cut(self):
        self.recovering_entry()
        self.worker.busy = True
        self.worker._tick()
        self.assertEqual(self.worker.output.take.call_count, 1)
        self.assertIsNone(self.worker.active)

    def test_repeated_stalls_exhaust_recovery_budget(self):
        entry = self.recovering_entry()
        self.worker._tick()
        entry['recoveries'] = [time.monotonic()] * 3
        entry['decoder'].ready.return_value = False
        self.worker._tick()
        self.assertIsNone(self.worker.active)
        self.assertIsNone(self.worker.recovering)
        self.assertIn('repeatedly stalled', self.worker.status()['error'])

    def test_bad_output_timing_enters_publication_recovery(self):
        self.worker.output.status.return_value = {"audio": {"backwards": 1}}
        with self.assertRaisesRegex(MasterStreamError, "timestamps went backwards"):
            self.worker._tick()

    def test_output_behind_real_time_enters_publication_recovery(self):
        self.worker.output_started = time.monotonic() - 60
        self.worker.output.status.return_value = {"video": {"backwards": 0, "lag_seconds": 3.0},
                                                  "audio": {"backwards": 0, "lag_seconds": 0.1}}
        self.worker.next_status = float("inf")
        self.worker._tick()
        self.worker.output.status.return_value["video"]["lag_seconds"] = 12400.0
        with self.assertRaisesRegex(MasterStreamError, "fell behind real time"):
            self.worker._tick()

    def test_publisher_failure_rebuilds_without_replaying_inputs(self):
        first = self.worker.output
        first.poll.side_effect = MasterStreamError("publisher disconnected")
        entry = self.entry()
        self.worker.inputs["live"] = entry
        self.worker.active = "live"
        second = Mock()
        second.healthy.return_value = True
        second.status.return_value = {}
        second.poll.side_effect = lambda: self.worker.stopping.set()
        self.worker.media_factory = Mock(return_value=second)
        self.worker.run()
        first.close.assert_called_once()
        second.close.assert_called_once()
        entry["lease"].release.assert_called_once()
        self.worker.tv.acquire.assert_not_called()
        self.assertIsNone(self.worker.active)
        self.assertFalse(self.worker.status()["can_take"])

    def test_api_master_routes_use_worker_and_existing_authorization(self):
        from roku_stream.api import handler_factory
        config = SimpleNamespace(master=MasterConfig(), server=SimpleNamespace(api_key="secret"))
        with patch("roku_stream.api.MasterClient") as client:
            handler_type = handler_factory(config, SimpleNamespace(), SimpleNamespace())
            handler = object.__new__(handler_type)
            response = {}
            handler._json = lambda status, payload: response.update(status=status, payload=payload)
            handler._body = lambda: TARGET
            handler.path = "/v1/master/prepare"
            handler.headers = {}
            handler.do_POST()
            self.assertEqual(response["status"], 401)
            client.return_value.request.assert_not_called()
            handler.headers = {"X-API-Key": "secret"}
            handler.do_POST()
            self.assertEqual(response["status"], 202)
            client.return_value.request.assert_called_once_with("prepare", TARGET)

    def test_no_arbitrary_url_or_roku_target(self):
        for body in ({"source_id": "youtube-tv", "channel_id": "ESPN"},
                     {"source_id": "http://example.test", "channel_id": "abc"},
                     {"source_id": "tv-thing-analog", "channel_id": True}):
            with self.assertRaises(ConfigError):
                target_from(body)

    def test_disabled_client_does_not_open_socket(self):
        self.assertEqual(MasterClient(MasterConfig()).request()["state"], "not_configured")
        with self.assertRaises(MasterStreamError):
            MasterClient(MasterConfig()).request("prepare", TARGET)

    def test_legacy_config_and_master_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            def load(master):
                path.write_text(json.dumps({"channels": [{"name": "ABC"}], "master": master}))
                return load_config(path)
            self.assertFalse(load({}).master.enabled)
            self.assertEqual(load({}).master.socket_path, Path(directory) / "state/master.sock")
            for values in ({"enabled": 1}, {"rtsp_url": "rtsp://remote/master"}, {"fps": True}, {"width": 321}):
                with self.assertRaises(ConfigError):
                    load(values)


if __name__ == "__main__":
    unittest.main()
