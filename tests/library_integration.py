"""Opt-in real-media gate for library playout. Uses generated clips and isolated MediaMTX.

Run from the repository root with /usr/bin/python3 tests/library_integration.py [--hd] [--real FILE].
Checks: a prepared file waits at its start, take plays it from the start, a file armed
after it cuts in when it ends with the same publisher, and the last one ends on fallback.
--real also plays the first 20 seconds of an actual recording. No production listeners,
hardware or state files are used.
"""
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import LibraryConfig, LibraryRoot, MasterConfig, TvThingConfig
from roku_stream.master_worker import MasterWorker, MasterClient, control_socket
from roku_stream.publication import LocalMediaMtx


def wait_for(check, timeout=45, what=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Timed out waiting for " + (what or repr(check)))


def clip(path, seconds, color, tone):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency={tone}:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)], check=True)


def main():
    hd = "--hd" in sys.argv
    real = Path(sys.argv[sys.argv.index("--real") + 1]) if "--real" in sys.argv else None
    report = {"ok": False, "phases": []}
    class Phases(list):
        def append(self, value):
            print("phase:", json.dumps(value), file=sys.stderr, flush=True)
            super().append(value)
    report["phases"] = Phases()
    executable = Path("vendor/mediamtx/1.21.0/mediamtx").resolve()
    with tempfile.TemporaryDirectory(prefix="vv-library-gate-") as directory:
        root = Path(directory)
        media = root / "media"
        (media / "Show").mkdir(parents=True)
        clip(media / "Show" / "first.mp4", 6, "red", 440)
        clip(media / "Show" / "second.mp4", 5, "blue", 880)
        roots = [LibraryRoot("gate", "Gate", media)]
        if real:
            roots.append(LibraryRoot("real", "Real", real.parent))
        (root / "output").mkdir()
        with LocalMediaMtx(executable, root / "output") as output:
            config = SimpleNamespace(
                master=MasterConfig(enabled=True, socket_path=root / "master.sock", rtsp_url=output.rtsp_url,
                                    status_url=output.api_url + "paths/get/" + output.path,
                                    width=1280 if hd else 320, height=720 if hd else 180,
                                    fps=30 if hd else 10, bitrate=2500 if hd else 256, off_air_radio_info_url=None),
                tv_thing=TvThingConfig(enabled=False), library=LibraryConfig(True, tuple(roots)))
            worker = MasterWorker(config)
            client = MasterClient(config.master)
            publishers = set()
            def observe():
                status = client.request()
                assert not any(t.get("backwards") for t in (status.get("tracks") or {}).values()), status
                return status
            with control_socket(worker):
                thread = threading.Thread(target=worker.run, daemon=True)
                thread.start()
                try:
                    wait_for(lambda: observe().get("can_prepare"), what="publisher")
                    publishers.add(worker.publisher_id)
                    def operation(action, body):
                        op = client.request(action, body)
                        return wait_for(lambda: (lambda s: s if (s.get("operation") or {}).get("id") == op["id"]
                                                 and s["operation"]["state"] != "pending" else None)(observe()),
                                        what=action)
                    first = {"source_id": "library", "channel_id": "gate/Show/first.mp4"}
                    state = operation("prepare", first)
                    assert state["operation"]["state"] == "succeeded", state
                    time.sleep(1.5)
                    cued = observe()["prepared"]
                    assert cued["media"]["position_seconds"] < .5, cued  # Parked at its start.
                    report["phases"].append({"phase": "cued", "position": cued["media"]["position_seconds"]})
                    state = operation("take", {"prepared_id": cued["id"]})
                    assert state["on_air"]["id"] == cued["id"], state
                    start = state["on_air"]["media"]["position_seconds"]
                    assert start < 1.5, state
                    report["phases"].append({"phase": "taken", "position": start})
                    state = operation("prepare", {"source_id": "library", "channel_id": "gate/Show/second.mp4",
                                                  "after_input_id": cued["id"]})
                    armed = state["prepared"]
                    assert armed["after_input_id"] == cued["id"], armed
                    state = wait_for(lambda: (lambda s: s if (s.get("on_air") or {}).get("id") == armed["id"] else None)(observe()),
                                     timeout=15, what="automatic cut to the next file")
                    assert state["last_completed"]["input_id"] == cued["id"], state
                    assert state["on_air"]["media"]["position_seconds"] < 1.5, state
                    report["phases"].append({"phase": "next file cut in", "position": state["on_air"]["media"]["position_seconds"]})
                    publishers.add(worker.publisher_id)
                    state = wait_for(lambda: (lambda s: s if s.get("state") == "fallback" and not s.get("on_air") else None)(observe()),
                                     timeout=15, what="fallback after the last file")
                    assert state["last_completed"]["input_id"] == armed["id"], state
                    assert worker.output.healthy()
                    report["phases"].append({"phase": "fallback after last file"})
                    if real:
                        state = operation("prepare", {"source_id": "library", "channel_id": "real/" + real.name})
                        assert state["operation"]["state"] == "succeeded", state
                        state = operation("take", {"prepared_id": state["prepared"]["id"]})
                        time.sleep(20)
                        state = observe()
                        assert state["on_air"]["media"]["position_seconds"] > 15, state
                        report["phases"].append({"phase": "real recording", "media": state["on_air"]["media"],
                                                 "tracks": state.get("input_tracks", {}).get("on_air")})
                        operation("fallback", {})
                    publishers.add(worker.publisher_id)
                    assert len(publishers) == 1, publishers
                    report["publisher_unchanged"] = True
                    report["ok"] = True
                finally:
                    worker.stopping.set()
                    thread.join(timeout=20)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
