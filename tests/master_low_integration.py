"""Both renditions from a real MasterMedia, published to an isolated MediaMTX running
deploy/mediamtx-master.yml on free ports; then the low one pointed at a path MediaMTX
refuses, which must leave the full output healthy. Needs GStreamer (and NVENC: the low
rendition's "auto" is NVENC or nothing). Run by hand: /usr/bin/python3 tests/master_low_integration.py
(MEDIAMTX=<binary> where vendor/ is not checked out, as in a worktree).
"""
import contextlib
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
MEDIAMTX = os.environ.get("MEDIAMTX", str(ROOT / "vendor/mediamtx/1.21.0/mediamtx"))
sys.path.insert(0, str(ROOT))
from roku_stream.config import MasterLowConfig
from roku_stream.master_media import MasterMedia, DecodedInput
from roku_stream.publication import _free_ports


@contextlib.contextmanager
def mediamtx():
    """(rtsp port, hls base URL) of MediaMTX with the production config on free ports."""
    rtsp, hls, api = _free_ports()
    config = (ROOT / "deploy/mediamtx-master.yml").read_text()
    for old, new in ((":18554", f":{rtsp}"), (":18888", f":{hls}"), (":19997", f":{api}")):
        config = config.replace(old, new)
    with tempfile.TemporaryDirectory(prefix="vv-master-low-") as directory:
        (Path(directory) / "mediamtx.yml").write_text(config)
        env = {k: v for k, v in os.environ.items() if not k.startswith("MTX_")}
        server = subprocess.Popen([MEDIAMTX, "mediamtx.yml"], cwd=directory,
                                  env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        try:
            time.sleep(1.5)
            yield rtsp, f"http://127.0.0.1:{hls}"
        finally:
            server.terminate()
            server.wait(5)


@contextlib.contextmanager
def on_air(rtsp, low_path, seconds):
    """A 720p60 MasterMedia with its low rendition on ``low_path``, a moving pattern on air
    for ``seconds``."""
    low = MasterLowConfig(rtsp_url=f"rtsp://127.0.0.1:{rtsp}/{low_path}")
    output = MasterMedia(f"rtsp://127.0.0.1:{rtsp}/master", fps=60, bitrate=8000, low=low)
    decoder = DecodedInput(output, 1, "", test_pattern=18)
    try:
        deadline = time.monotonic() + 15
        while not (output.healthy() and decoder.ready()) and time.monotonic() < deadline:
            output.poll(); decoder.poll(); time.sleep(.05)
        output.take(1)
        for _ in range(seconds):
            output.poll(); decoder.poll(); time.sleep(1)
        yield output
    finally:
        decoder.close()
        output.close()


def segments(hls, path):
    """(multivariant playlist, video segment durations) of one path."""
    with urlopen(f"{hls}/{path}/index.m3u8", timeout=5) as response:
        index = response.read().decode()
    with urlopen(f"{hls}/{path}/" + re.search(r"^(video\S+)$", index, re.M).group(1), timeout=5) as response:
        media = response.read().decode()
    return index, [float(d) for d in re.findall(r"^#EXTINF:([\d.]+),", media, re.M)]


def main():
    with mediamtx() as (rtsp, hls), on_air(rtsp, "master_low", 14) as output:
        assert output.healthy() and output.low_status()["state"] == "publishing", output.low_status()
        full_index, full = segments(hls, "master")
        low_index, low = segments(hls, "master_low")
        assert "RESOLUTION=1280x720" in full_index and "FRAME-RATE=60.000" in full_index, full_index
        assert "RESOLUTION=960x540" in low_index and "FRAME-RATE=30.000" in low_index, low_index
        assert all(abs(d - 1) < .05 for d in full[-4:]), full
        assert all(abs(d - 2) < .05 for d in low[-4:]), low
        print(f"full: 1280x720@60, {len(full)} x 1 s segments; low: 960x540@30, {len(low)} x 2 s segments")
    with mediamtx() as (rtsp, hls), on_air(rtsp, "master_nope", 12) as output:
        low = output.low_status()
        assert output.healthy(), "a refused low path took the full output down"
        assert low["state"] == "retrying" and low["restarts"] >= 1, low
        print(f"refused low path: full output healthy; low {low['state']} after {low['restarts']} restarts")


if __name__ == "__main__":
    main()
