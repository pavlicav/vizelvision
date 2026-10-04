#!/usr/bin/python3
"""Wait for the running web app, master publisher, and served HLS playlist."""
import json
from pathlib import Path
import sys
import socket
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import load_config


def main():
    config = load_config(Path(__file__).resolve().parents[1] / "config.master.json")
    base = f"http://127.0.0.1:{config.server.port}/"
    browser_base = f"http://{socket.gethostname()}:{config.server.port}/" if config.server.host == "0.0.0.0" else base
    headers = {"X-API-Key": config.server.api_key} if config.server.api_key else {}
    deadline = time.monotonic() + 40
    last_error = "Waiting for services"
    while time.monotonic() < deadline:
        try:
            with urlopen(Request(base + "v1/master", headers=headers), timeout=2) as response:
                state = json.loads(response.read(65536))
            if not state.get("publisher_ready") or state.get("state") not in ("fallback", "live"):
                raise ValueError("Master publisher is not ready")
            with urlopen(Request(base + "v1/master/media/index.m3u8", headers=headers), timeout=3) as response:
                playlist = response.read(256 * 1024)
            if not playlist.startswith(b"#EXTM3U"):
                raise ValueError("Master HLS playlist is not ready")
            print(json.dumps({"ok": True, "web_url": browser_base + "air", "master_state": state["state"],
                              "publisher_ready": True, "hls_ready": True}, indent=2))
            return
        except (OSError, URLError, ValueError) as exc:
            last_error = str(exc)
            time.sleep(.5)
    print(json.dumps({"ok": False, "error": last_error}), file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
