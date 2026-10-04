"""Opt-in test of the CURRENT digital TV-Thing feed. Never calls tune or stop.

Temporarily leases the selected tuner; aborts on conflict/selection change.
Publishes only to a temporary loopback MediaMTX instance, then releases the lease.
Run: /usr/bin/python3 tests/current_tv_input_integration.py
"""
import argparse
import json
from contextlib import ExitStack
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import load_config
from roku_stream.master import MasterStreamError
from roku_stream.master_media import MasterMedia, DecodedInput
from roku_stream.publication import LocalMediaMtx, PublicationMonitor, cancellation_handlers
from roku_stream.tv_control import TvControl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=15, help='On-air observation duration (15–600 seconds)')
    args = parser.parse_args()
    if not 15 <= args.seconds <= 600:
        parser.error('--seconds must be between 15 and 600')
    config = load_config("config.master.json")
    client = TvControl(config.tv_thing)
    current = client.request("status")["lanes"]["digital"]
    if not current["stream"].get("ready") or not current.get("selection"):
        raise MasterStreamError("Current digital feed is not ready; no tuner changes were made")
    target = {"source_id": "tv-thing-digital", "channel_id": current["selection"]["id"], "quality": current["quality"]}
    lease = None
    output = decoder = monitor = None
    report = {"ok": False, "channel": target["channel_id"], "quality": target["quality"],
              "generation": current["stream"]["generation"], "tune_calls": 0, "stop_calls": 0,
              "observation_seconds": args.seconds,
              "limitations": "Current digital feed only; no analog/Roku test or lip-sync measurement."}
    with cancellation_handlers(), tempfile.TemporaryDirectory(prefix="vv-current-tv-") as directory:
        try:
            lease = client.acquire(target)
            lease.generation = current["stream"]["generation"]
            # Selection could have changed between the initial read and lock.
            # check() aborts instead of returning the tuner to an old selection.
            url = lease.check()
            if not url:
                raise MasterStreamError("Current feed stopped being ready")
            with LocalMediaMtx(Path("vendor/mediamtx/1.21.0/mediamtx").resolve(), Path(directory)) as server, ExitStack() as cleanup:
                output = MasterMedia(server.rtsp_url)
                cleanup.callback(output.close)
                monitor = PublicationMonitor(server)
                cleanup.callback(lambda: monitor.pipeline.set_state(monitor.gst.State.NULL) if monitor.pipeline else None)
                cleanup.callback(lambda: decoder.close() if decoder else None)
                next_check = 0
                watching = False
                def poll():
                    nonlocal next_check
                    output.poll()
                    monitor.poll()
                    if decoder:
                        decoder.poll()
                        if watching and not decoder.ready():
                            raise MasterStreamError('Input freshness failed', details=decoder.status())
                    if time.monotonic() >= next_check:
                        if not lease.check():
                            raise MasterStreamError("TV-Thing feed is no longer ready")
                        next_check = time.monotonic() + 2
                    time.sleep(.03)
                def hold(seconds):
                    deadline = time.monotonic() + seconds
                    while time.monotonic() < deadline:
                        poll()
                monitor.started(poll)
                decoder = DecodedInput(output, 1, url)
                deadline = time.monotonic() + 40
                while not decoder.ready() and time.monotonic() < deadline:
                    poll()
                if not decoder.ready():
                    raise MasterStreamError("Current TV-Thing feed did not decode both tracks within 40 seconds")
                lease.renew(force=True)
                output.take(1)
                watching = True
                hold(args.seconds)
                if not decoder.ready():
                    raise MasterStreamError("Current TV-Thing input stalled on air")
                with monitor.lock:
                    report["live_video_luma_samples"] = list(monitor.tracks["video"]["samples"])
                    report["live_audio_mean_energy"] = sum(s[0] for s in monitor.tracks["audio"]["samples"]) / len(monitor.tracks["audio"]["samples"])
                monitor._hls()
                output.take(0)
                hold(3)
                if server.status()["source"]["id"] != monitor.publisher_id:
                    raise MasterStreamError("Master publisher changed across takes")
                if monitor.reader_id not in {s["id"] for s in server.sessions() if s["state"] == "read"}:
                    raise MasterStreamError("Master viewer disconnected across takes")
                with monitor.lock:
                    if any(t["backwards"] or t["max_pts_gap_seconds"] > .5 or t["max_arrival_gap_seconds"] > 1 for t in monitor.tracks.values()):
                        raise MasterStreamError("Master subscriber continuity failed")
                    report["tracks"] = {k: {f: v for f, v in track.items() if f not in ("samples", "last_at", "last_pts")}
                                        for k, track in monitor.tracks.items()}
                report.update(ok=True, hls_streams=monitor.hls_probe, same_publisher_and_reader=True)
        finally:
            if lease:
                report["lease_released"] = lease.release()
    report["selection_unchanged"] = client.request("status")["lanes"]["digital"]["stream"]["generation"] == report["generation"]
    if not report.get("lease_released") or not report["selection_unchanged"]:
        raise MasterStreamError("Cleanup/selection verification failed", details=report)
    Path("docs/current-tv-input-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
