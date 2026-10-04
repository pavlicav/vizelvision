"""Opt-in real-media gate for the station ID. Uses generated clips and isolated MediaMTX.

Run from the repository root with /usr/bin/python3 tests/ident_integration.py [--ident FILE].
Checks, with the real ID file in the real master graph (slot 3):
  the ID is decoded and parked at its start without going on air;
  a program with the next file armed behind it plays to its very end, then the ID;
  the ID plays in full, then the armed file follows it on the same publisher;
  the last program plays to its end, then the ID, then fallback.
No production listeners, hardware or state files are used.
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
from roku_stream.ident import IDENT_PATH
from roku_stream.master_worker import MasterWorker, MasterClient, control_socket
from roku_stream.publication import LocalMediaMtx
from tests.library_integration import clip, wait_for


def main():
    ident = Path(sys.argv[sys.argv.index("--ident") + 1]) if "--ident" in sys.argv else IDENT_PATH
    report = {"ok": False, "ident": str(ident), "phases": []}

    def phase(**value):
        value["at"] = round(time.monotonic() - started, 2)
        print("phase:", json.dumps(value), file=sys.stderr, flush=True)
        report["phases"].append(value)

    executable = Path("vendor/mediamtx/1.21.0/mediamtx").resolve()
    with tempfile.TemporaryDirectory(prefix="vv-ident-gate-") as directory:
        root = Path(directory)
        media = root / "media"
        media.mkdir()
        clip(media / "first.mp4", 40, "red", 440)
        clip(media / "second.mp4", 6, "blue", 880)
        (root / "output").mkdir()
        with LocalMediaMtx(executable, root / "output") as output:
            config = SimpleNamespace(
                master=MasterConfig(enabled=True, socket_path=root / "master.sock", rtsp_url=output.rtsp_url,
                                    status_url=output.api_url + "paths/get/" + output.path, width=320, height=180,
                                    fps=10, bitrate=256, off_air_radio_info_url=None),
                tv_thing=TvThingConfig(enabled=False), library=LibraryConfig(True, (LibraryRoot("gate", "Gate", media),)))
            worker = MasterWorker(config, ident_path=ident)
            client = MasterClient(config.master)
            publishers = set()

            def observe():
                status = client.request()
                assert not any(t.get("backwards") for t in (status.get("tracks") or {}).values()), status
                return status

            def until(check, timeout, what):
                return wait_for(lambda: (lambda s: s if check(s) else None)(observe()), timeout=timeout, what=what)

            def operation(action, body):
                op = client.request(action, body)
                return until(lambda s: (s.get("operation") or {}).get("id") == op["id"]
                             and s["operation"]["state"] != "pending", 45, action)

            with control_socket(worker):
                thread = threading.Thread(target=worker.run, daemon=True)
                started = time.monotonic()
                thread.start()
                try:
                    until(lambda s: s.get("can_prepare"), 45, "publisher")
                    publishers.add(worker.publisher_id)
                    state = until(lambda s: (s.get("ident") or {}).get("ready"), 45, "station ID cued")
                    assert state["on_air"] is None and state["state"] == "fallback", state
                    phase(phase="ID cued", ident=state["ident"])
                    first = {"source_id": "library", "channel_id": "gate/first.mp4"}
                    state = operation("prepare", first)
                    state = operation("take", {"prepared_id": state["prepared"]["id"]})
                    program = state["on_air"]["id"]
                    state = operation("prepare", {"source_id": "library", "channel_id": "gate/second.mp4",
                                                  "after_input_id": program})
                    armed = state["prepared"]["id"]
                    phase(phase="program on air, next file armed")
                    state = until(lambda s: (s.get("on_air") or {}).get("source_id") == "ident", 50,
                                  "the ID after the program's end")
                    completed = state["last_completed"]
                    assert completed["input_id"] == program and not completed.get("cut_for_station_id"), state
                    left = completed["target"]["media"]
                    assert left["duration_seconds"] - left["position_seconds"] <= 1, completed
                    assert state["prepared"]["after_input_id"] == state["on_air"]["id"], state
                    phase(phase="ID followed the program's end", program_left=round(
                        left["duration_seconds"] - left["position_seconds"], 1))
                    aired = time.monotonic()
                    state = until(lambda s: (s.get("on_air") or {}).get("id") == armed, 40, "the armed file after the ID")
                    phase(phase="armed file followed the ID", id_seconds=round(time.monotonic() - aired, 1),
                          position=state["on_air"]["media"]["position_seconds"])
                    assert 28.5 <= time.monotonic() - aired <= 31.5, "the ID did not play in full"
                    state = until(lambda s: (s.get("on_air") or {}).get("source_id") == "ident", 15,
                                  "the ID after the last program")
                    assert state["last_completed"]["input_id"] == armed, state
                    phase(phase="ID followed the last program")
                    state = until(lambda s: s.get("state") == "fallback" and not s.get("on_air"), 40, "fallback")
                    phase(phase="fallback after the ID")
                    state = until(lambda s: (s.get("ident") or {}).get("ready"), 45, "a fresh ID cued")
                    assert worker.output.healthy()
                    publishers.add(worker.publisher_id)
                    assert len(publishers) == 1, publishers
                    report.update(ok=True, publisher_unchanged=True, tracks=state.get("tracks"))
                finally:
                    worker.stopping.set()
                    thread.join(timeout=20)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
