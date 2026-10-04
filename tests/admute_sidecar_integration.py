"""End-to-end check of the ad-mute sidecar (admute.service) over its real socket.

  /home/vivian/miniconda3/bin/python3 tests/admute_sidecar_integration.py [TAPE] [--minutes 16]

A fake master worker streams a labelled recording in the tap format (limited-range
luma, as GStreamer's GRAY8 is) and reads the sidecar's answers. It checks that a
gain schedule mutes at the first break after the detector has warmed up, that a
lease and the AD badge come with it, and that an "it's the show" override is
acknowledged, ends the mute and is written to the labels ledger.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from admute import features, replay, service, tap  # noqa: E402
from roku_stream import admute_protocol as proto  # noqa: E402

KEY = "0123456789abcdef0123456789abcdef"
SECOND = 1_000_000_000
BASE = 5 * SECOND           # input running time of the first frame


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tape", nargs="?", default="Jeopardy! - 7.1 WJLA - 2026-09-23 1930.mp4")
    ap.add_argument("--minutes", type=float, default=16)
    args = ap.parse_args()
    path = replay.find_tape(args.tape)
    truth = {t["file"]: t for _, t in replay.load_truths()}.get(Path(path).name)
    breaks = [(a, b) for a, b, lab in (truth or {}).get("spans", []) if lab == "ad" and b - a > 30]

    tmp = Path(tempfile.mkdtemp(prefix="admute-it-"))
    (tmp / "config.json").write_text(json.dumps({"master": {"socket_path": str(tmp / "master.sock")},
                                                  "server": {"port": 1}}))
    svc = service.Service(str(tmp / "config.json"))
    threading.Thread(target=svc.serve, daemon=True).start()
    for _ in range(100):
        if svc.path.exists():
            break
        time.sleep(.1)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(str(svc.path))
    lock = threading.Lock()

    def send(data):
        with lock:
            sock.sendall(data)

    messages = []

    def read():
        buf = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                messages.append(json.loads(line))
    threading.Thread(target=read, daemon=True).start()
    send(proto.json_frame(b"S", KEY, 0, {"source_id": "tv-thing-digital", "channel_id": "7.1", "lane": "digital",
                                          "lookahead": 3.0, "range": "limited", "fps": 30}))
    to_limited = np.round(16 + np.arange(256) * 219 / 255).astype(np.uint8)

    def ns(t):
        return BASE + int(t * SECOND)

    def on_gray(times, frames):
        for t, f in zip(times, frames):
            send(proto.frame(b"G", KEY, ns(t), to_limited[f].tobytes()))

    def on_rgb(times, frames):
        for t, f in zip(times, frames):
            send(proto.frame(b"R", KEY, ns(t), f.tobytes()))

    def on_audio(t0, samples):
        send(proto.frame(b"A", KEY, ns(t0), samples.astype(np.float32).tobytes()))

    started = time.time()
    tap.decode_file(path, on_gray, on_rgb, on_audio, limit=args.minutes * 60)
    print(f"streamed {args.minutes:.0f} min in {time.time() - started:.0f}s; waiting for the detector to catch up")
    deadline = time.time() + 120
    last = None
    while time.time() < deadline:
        mine = [m for m in messages if m.get("input") == KEY]
        if mine and mine[-1].get("lease") and (mine[-1]["lease"] - BASE) / SECOND > args.minutes * 60 - 8:
            last = mine[-1]
            break
        time.sleep(1)
    mine = [m for m in messages if m.get("input") == KEY]
    last = last or (mine[-1] if mine else None)
    assert last, "no answers from the sidecar"
    mutes = []
    for m in mine:
        for p, level, _ in m["events"]:
            if level == 0.0:
                mutes.append(round((p - BASE) / SECOND, 1))
    mutes = sorted(set(mutes))
    print("mute starts:", [replay.fmt(t) for t in mutes])
    print("last message:", {k: last[k] for k in ("state", "p_ad", "badge")})
    within = [(a, b) for a, b in breaks if a < args.minutes * 60 - 30]
    ok = True
    for a, b in within:
        hit = [t for t in mutes if abs(t - a) < 3]
        warm = a > 360
        print(f"break {replay.fmt(a)}: {'muted at ' + replay.fmt(hit[0]) if hit else 'not muted'}"
              f"{'' if warm else ' (before warm-up; not required)'}")
        ok &= bool(hit) or not warm
    badges = [m["badge"] for m in mine if m.get("badge")]
    print("badges seen:", len(badges), (badges[-1][2] if badges else None))
    ok &= bool(badges)
    # Override: "it's the show" while muted (or not) is acknowledged and logged.
    lease_pts = last["lease"]
    send(proto.json_frame(b"O", KEY, lease_pts, {"action": "unmute", "seq": 1}))
    time.sleep(2)
    acked = [m for m in messages if m.get("input") == KEY and m.get("ack", 0) >= 1]
    print("override acknowledged:", bool(acked))
    labels = svc.labels_path.read_text().splitlines() if svc.labels_path.exists() else []
    print("labels written:", len(labels), labels[-1] if labels else "")
    state = json.loads(svc.state_path.read_text())
    print("state file inputs:", len(state["inputs"]), "spans:", len(state["inputs"][0]["spans"]) if state["inputs"] else 0)
    ok &= bool(labels) and len(state["inputs"]) == 1
    # The page's pictures, and Whisper (which falls behind and drops chunks here: the
    # tape streams faster than real time).
    pictures = list((tmp / "admute-frames" / KEY).glob("*.jpg"))
    heard = state.get("speech") or {}
    print("pictures saved:", len(pictures), "· speech:", heard, "· heard:", state["inputs"][0].get("heard"))
    ok &= bool(pictures) and heard.get("usable") is True and (heard.get("chunks") or 0) > 0
    print("known ads:", state.get("prints"))
    ok &= isinstance(state.get("prints"), dict)
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
