"""Opt-in real-media worker gate. Uses generated HLS and a fake tuner API.

Run from the repository root with /usr/bin/python3 tests/master_worker_integration.py.
No production listeners, hardware, tuner APIs, or state files are used.
"""
import json
import resource
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.master_media import MasterMedia, DecodedInput
from roku_stream.master_worker import MasterWorker, MasterClient, control_socket
from roku_stream.publication import LocalMediaMtx, PublicationMonitor


def wait_for(check, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Timed out waiting for " + repr(check))


def main():
    hd = "--hd" in sys.argv
    cpu_started = time.process_time()
    wall_started = time.monotonic()
    executable = Path("vendor/mediamtx/1.21.0/mediamtx").resolve()
    report = {"ok": False, "phases": [], "limitations": "Generated HLS and fake tuner API; no reception, hardware sync, Roku capture, or long-duration resource soak tested."}
    with tempfile.TemporaryDirectory(prefix="vv-worker-gate-") as directory:
        root = Path(directory)
        (root / "upstream").mkdir()
        (root / "output").mkdir()
        with LocalMediaMtx(executable, root / "upstream") as upstream, LocalMediaMtx(executable, root / "output") as output:
            source = MasterMedia(upstream.rtsp_url, width=320, height=180, fps=10, bitrate=256)
            generated = DecodedInput(source, 1, "", test_pattern=4)
            worker = monitor = server = thread = None
            try:
                wait_for(lambda: source.healthy() and generated.ready())
                source.take(1)
                state = {"token": None, "owner": None, "expiry": 0, "generation": "fixture-generation-1",
                         "channel": None, "calls": [], "quality": "medium"}
                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, *_):
                        pass
                    def reply(self, data, status=200):
                        raw = json.dumps({"api_version": "v1", **data}).encode()
                        self.send_response(status)
                        self.send_header("Content-Length", str(len(raw)))
                        self.end_headers()
                        self.wfile.write(raw)
                    def lane(self):
                        return {"selection": {"id": state["channel"]}, "quality": state["quality"],
                                "stream": {"generation": state["generation"], "ready": True, "state": "ready",
                                           "playback": [{"protocol": "hls", "url": "stream/index.m3u8"}]}}
                    def do_GET(self):
                        if self.path == "/tv/api/v1/status":
                            return self.reply({"lanes": {"digital": self.lane()}, "locks": {"digital": {
                                "owner": state["owner"], "expires_at": state["expiry"]} if state["token"] else None}})
                        if self.path.startswith("/tv/stream/"):
                            suffix = self.path[len("/tv/stream/"):]
                            assert ".." not in suffix
                            with urlopen(upstream.hls_url.rsplit("/", 1)[0] + "/" + suffix, timeout=3) as response:
                                raw = response.read(3 * 1024 * 1024)
                            self.send_response(200)
                            self.send_header("Content-Length", str(len(raw)))
                            self.send_header("Content-Type", "application/vnd.apple.mpegurl" if ".m3u8" in suffix else "video/mp4")
                            self.end_headers()
                            try:
                                self.wfile.write(raw)
                            except (BrokenPipeError, ConnectionResetError):
                                pass  # The decoder cancels pending reads when dropped.
                            return
                        self.reply({"error": "not found"}, 404)
                    def do_POST(self):
                        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                        assert not body.get("override")
                        state["calls"].append(self.path.rsplit("/", 1)[-1])
                        if self.path.endswith("/tuner/lock"):
                            if state["token"] and body.get("token") != state["token"]:
                                return self.reply({"error": "locked"}, 423)
                            renewed = bool(state["token"])
                            state.update(token="fixture-secret", owner=body["owner"], expiry=time.time()+90)
                            return self.reply({"token": state["token"], "renewed": renewed, "lock": {"expires_at": state["expiry"]}})
                        if body.get("token") != state["token"] or not state["token"]:
                            return self.reply({"error": "not owner"}, 403)
                        if self.path.endswith("/tune"):
                            state.update(channel=body["channel_id"], quality=body["quality"])
                            return self.reply(self.lane())
                        if self.path.endswith("/release"):
                            state.update(token=None, owner=None)
                            return self.reply({"ok": True})
                        self.reply({"error": "not found"}, 404)
                server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
                server.daemon_threads = True
                threading.Thread(target=server.serve_forever, daemon=True).start()
                config = SimpleNamespace(master=MasterConfig(enabled=True, socket_path=root / "master.sock", rtsp_url=output.rtsp_url,
                                                              status_url=output.api_url+"paths/get/"+output.path,
                                                              width=1280 if hd else 320, height=720 if hd else 180,
                                                              fps=30 if hd else 10, bitrate=2500 if hd else 256),
                                         tv_thing=TvThingConfig(enabled=True, base_url=f"http://127.0.0.1:{server.server_port}/tv/"))
                worker = MasterWorker(config)
                client = MasterClient(config.master)
                with control_socket(worker):
                    thread = threading.Thread(target=worker.run)
                    thread.start()
                    wait_for(lambda: client.request().get("can_prepare"))
                    monitor = PublicationMonitor(output)
                    monitor.started(lambda: (monitor.poll(), time.sleep(.02)))
                    def phase(label, luma, expected_energy):
                        time.sleep(1.2)
                        monitor.poll()
                        assert output.status()["source"]["id"] == monitor.publisher_id
                        assert monitor.reader_id in {s["id"] for s in output.sessions() if s["state"] == "read"}
                        with monitor.lock:
                            samples = {kind: list(track["samples"]) for kind, track in monitor.tracks.items()}
                        # Video samples are luma levels; audio are (energy, crossings).
                        assert all(abs(v-luma) <= 3 for v in samples["video"][-5:]), samples
                        energy = sum(s[0] for s in samples["audio"]) / len(samples["audio"])
                        assert abs(energy - expected_energy) < max(.002, expected_energy * .15), energy
                        monitor._hls()
                        report["phases"].append({"phase": label, "luma": samples["video"][-1], "audio_energy": round(energy, 4)})
                        print(label, flush=True)
                    phase("startup fallback", 103, .005)
                    for n in range(2):
                        client.request("prepare", {"source_id": "tv-thing-digital", "channel_id": "fixture"})
                        def prepared():
                            status = client.request()
                            if status.get("operation", {}).get("state") == "failed":
                                raise AssertionError(status)
                            return status.get("prepared") if status.get("can_take") else None
                        target = wait_for(prepared)
                        # Preparation must not change the on-air selector.
                        assert client.request()["on_air"] is None
                        client.request("take", {"prepared_id": target["id"]})
                        wait_for(lambda: client.request().get("on_air"))
                        phase(f"HLS input take {n+1}", 63, .32)
                        if n == 0:
                            client.request("fallback", {})
                        else:
                            state["generation"] = "unexpected-new-generation"
                        wait_for(lambda: client.request().get("state") == "fallback" and client.request().get("on_air") is None)
                        phase("manual fallback" if n == 0 else "generation-loss fallback", 103, .005)
                    assert state["token"] is None
                    public = json.dumps(client.request())
                    assert "fixture-secret" not in public
                    assert all(t["backwards"] == 0 for t in monitor.tracks.values())
                    assert all(t["max_pts_gap_seconds"] < .5 for t in monitor.tracks.values()), monitor.tracks
                    report.update(ok=True, same_publisher_and_reader=True, tuner_released=True,
                                  hls_streams=monitor.hls_probe, hls_sequences=monitor.hls_sequences,
                                  tracks={k: {field: value for field, value in t.items() if field not in ("samples", "last_pts", "last_at")}
                                          for k, t in monitor.tracks.items()}, api_calls=state["calls"])
                    monitor.pipeline.set_state(monitor.gst.State.NULL)
                    monitor.pipeline = None
                    before_calls = list(state["calls"])
                    output.__exit__(None, None, None)
                    wait_for(lambda: client.request().get("state") == "reconnecting", timeout=20)
                    output.__enter__()
                    wait_for(lambda: client.request().get("can_prepare"), timeout=30)
                    assert client.request()["on_air"] is None
                    assert output.status()["source"]["id"] != monitor.publisher_id
                    assert state["calls"] == before_calls, "Recovery must not retune"
                    report["publisher_restart_recovered_to_fallback_without_retune"] = True
                    print("publisher restart recovery", flush=True)
                    worker.stopping.set()
                    thread.join(10)
                    assert not thread.is_alive()
                assert not config.master.socket_path.exists()
            finally:
                if worker:
                    worker.stopping.set()
                    worker.cancel.set()
                if thread:
                    thread.join(12)
                if monitor and monitor.pipeline:
                    monitor.pipeline.set_state(monitor.gst.State.NULL)
                if server:
                    server.shutdown()
                    server.server_close()
                generated.close()
                source.close()
    report["process_observations"] = {"peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                                      "cpu_seconds": round(time.process_time() - cpu_started, 2),
                                      "elapsed_seconds": round(time.monotonic() - wall_started, 2),
                                      "scope": "Python process and its GStreamer threads, excluding MediaMTX/ffmpeg children; short test, not a soak"}
    Path("docs/master-worker-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
