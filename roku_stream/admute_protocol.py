"""Wire format between the master worker and the ad-mute sidecar (admute.service).

Worker -> sidecar, binary frames: a header, then ``length`` bytes of payload.

    header = kind (1 byte) | input key (32 bytes) | pts (int64 ns) | length (uint32)

    S  start   JSON {source_id, lane, title, range, lookahead, fps}
    G  gray    320x180 GRAY8 (the input's luma, limited range)
    R  rgb     224x224 RGB, ~1 fps
    A  audio   F32LE mono 16 kHz, pts of the first sample
    E  end     JSON {}
    O  override JSON {action: mute|unmute|resume|pause, seq}

pts are the input's running time in nanoseconds, the same clock the worker's
volume stage sees. Sidecar -> worker: one JSON object per line, per input:

    {"input": key, "ack": seq, "events": [[pts, level, ramp_ns], ...],
     "lease": pts, "badge": [from_pts, to_pts|null, label, p] | null, "p_ad": float,
     "state": "listening|muted|..."}

``events`` is the whole current gain schedule (it replaces the previous one).
Gain follows the schedule only up to ``lease``; past it the sound comes back.
"""
from __future__ import annotations

import json
import struct

HEADER = struct.Struct("!c32sqI")
KEY_BYTES = 32
GRAY_W, GRAY_H = 320, 180
RGB_SIDE = 224
AUDIO_RATE = 16000
MAX_PAYLOAD = 1 << 20


def key_bytes(key: str) -> bytes:
    return key.encode()[:KEY_BYTES].ljust(KEY_BYTES, b"\0")


def frame(kind: bytes, key: str, pts: int, payload: bytes) -> bytes:
    return HEADER.pack(kind, key_bytes(key), int(pts), len(payload)) + payload


def json_frame(kind: bytes, key: str, pts: int, body: dict) -> bytes:
    return frame(kind, key, pts, json.dumps(body).encode())


def read_frames(buf: bytearray):
    """Pop complete frames from ``buf``: yields (kind, key, pts, payload)."""
    while len(buf) >= HEADER.size:
        kind, key, pts, length = HEADER.unpack_from(buf)
        if length > MAX_PAYLOAD:
            raise ValueError("ad-mute frame too large")
        end = HEADER.size + length
        if len(buf) < end:
            return
        payload = bytes(buf[HEADER.size:end])
        del buf[:end]
        yield kind, key.rstrip(b"\0").decode(), pts, payload
