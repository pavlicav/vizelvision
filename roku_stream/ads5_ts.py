"""Ads 5's splicer: MPEG-TS segments of separately encoded clips, joined into one stream.

Every clip Ads 5 airs is encoded alike ahead of time (ads5_prep.py: 1280×720 at 60 fps, H.264
with a key frame every 2 s, AAC 48 kHz stereo, cut into 2 s HLS segments, the same PIDs). Each
clip's timestamps start near zero, so played one after another they would jump back at every
join. Rather than mark each join as a discontinuity (which players and relays handle unevenly),
the channel shifts each clip's timestamps to carry on where the last clip ended: PTS, DTS and
PCR move by one offset, and the continuity counters carry on per PID. The joined stream then
reads as one encoder's output, and no encoder runs while it plays.

Pure Python, about 5 ms for a 2 s segment of 720p.
"""
from __future__ import annotations

PACKET = 188
SYNC = 0x47
WRAP = 1 << 33          # PTS, DTS and the PCR's base count 90 kHz in 33 bits
CLOCK = 90_000


def _read_ts(b, i):
    return (((b[i] >> 1) & 0x07) << 30 | b[i + 1] << 22 | (b[i + 2] >> 1) << 15
            | b[i + 3] << 7 | b[i + 4] >> 1)


def _write_ts(b, i, value):
    value %= WRAP
    marker = b[i] & 0xF1     # keeps the 4-bit prefix and the marker bit
    b[i] = marker | ((value >> 30) & 0x07) << 1
    b[i + 1] = (value >> 22) & 0xFF
    b[i + 2] = ((value >> 15) & 0x7F) << 1 | 1
    b[i + 3] = (value >> 7) & 0xFF
    b[i + 4] = (value & 0x7F) << 1 | 1


def _pes_start(b, p):
    """Where a packet's PES header starts (payload unit start), or None."""
    if not b[p + 1] & 0x40:
        return None
    afc = (b[p + 3] >> 4) & 0x03
    if not afc & 0x01:
        return None
    start = p + 4
    if afc & 0x02:
        start += 1 + b[p + 4]
    if start + 14 > p + PACKET or b[start] or b[start + 1] or b[start + 2] != 1:
        return None
    return start


def first_pts(data):
    """The lowest PTS in a segment (90 kHz), or None."""
    low = None
    for p in range(0, len(data) - PACKET + 1, PACKET):
        if data[p] != SYNC:
            continue
        s = _pes_start(data, p)
        if s is None or not data[s + 7] & 0x80:
            continue
        pts = _read_ts(data, s + 9)
        low = pts if low is None else min(low, pts)
    return low


class Splicer:
    """Rewrites segments clip after clip so the stream runs on. Holds the continuity counters."""

    def __init__(self):
        self.cc = {}

    def shift(self, data, delta):
        """The segment with every PTS, DTS and PCR moved by delta (90 kHz) and the continuity
        counters carried on from the segment before (PAT and PMT too; null packets keep theirs)."""
        b = bytearray(data)
        n = len(b) - len(b) % PACKET
        cc = self.cc
        for p in range(0, n, PACKET):
            if b[p] != SYNC:
                continue
            pid = (b[p + 1] & 0x1F) << 8 | b[p + 2]
            afc = (b[p + 3] >> 4) & 0x03
            if afc & 0x02 and b[p + 4] >= 7 and b[p + 5] & 0x10:      # a PCR
                i = p + 6
                base = b[i] << 25 | b[i + 1] << 17 | b[i + 2] << 9 | b[i + 3] << 1 | b[i + 4] >> 7
                base = (base + delta) % WRAP
                b[i] = (base >> 25) & 0xFF
                b[i + 1] = (base >> 17) & 0xFF
                b[i + 2] = (base >> 9) & 0xFF
                b[i + 3] = (base >> 1) & 0xFF
                b[i + 4] = (b[i + 4] & 0x7F) | (base & 1) << 7
            if pid == 0x1FFF:
                continue
            if afc & 0x01:                                            # carries a payload
                s = _pes_start(b, p)
                if s is not None:
                    flags = b[s + 7] >> 6
                    if flags & 0x02:
                        _write_ts(b, s + 9, _read_ts(b, s + 9) + delta)
                    if flags == 0x03:
                        _write_ts(b, s + 14, _read_ts(b, s + 14) + delta)
                count = (cc.get(pid, -1) + 1) & 0x0F
                cc[pid] = count
                b[p + 3] = (b[p + 3] & 0xF0) | count
        return bytes(b)
