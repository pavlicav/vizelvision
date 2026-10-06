"""A real station promo through master's PromoReel (ad_break.py): the built Time &
Temperature promo decoded at master's size, with its live text blended in by GStreamer's
overlaycomposition, against the same promo decoded without it.

    nice -n 19 /usr/bin/python3 tests/promos_master_integration.py

Checks: the promo cues; frames after the time flips in differ from the plain decode inside
the time's box (by a lot) and barely elsewhere (the decodes may sit a frame apart, and the
grain moves); the temperature box stays empty without a reading; sound comes through.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from roku_stream.master import _gst  # noqa: E402
from roku_stream import ad_break, promos  # noqa: E402

Gst = _gst()
W, H = 1280, 720
VIDEO = f'video/x-raw,format=I420,width={W},height={H},framerate=60/1,colorimetry=bt709'
AUDIO = 'audio/x-raw,format=F32LE,rate=48000,channels=2,layout=interleaved'


def frame_at(reel, t):
    """The reel's Y plane at promo time t (seconds), waiting for the decoder."""
    deadline = time.monotonic() + 20
    ns = int(t * 1e9)
    while time.monotonic() < deadline:
        buffer = reel.frame(ns)
        reel.poll()
        if reel.failed:
            raise SystemExit(f'decode failed: {reel.failed}')
        if buffer is not None and reel.shown and reel.shown[0] + reel.shown[2] > ns - 20_000_000 and (
                reel.pending is not None or reel.shown[0] >= ns - 20_000_000):
            return buffer.extract_dup(0, W * H)
        time.sleep(.005)
    raise SystemExit(f'no frame at {t} s')


def mean_difference(a, b, box):
    x, y, w, h = box
    total = count = 0
    for row in range(y, y + h, 2):
        line_a, line_b = a[row * W + x:row * W + x + w], b[row * W + x:row * W + x + w]
        total += sum(abs(p - q) for p, q in zip(line_a[::2], line_b[::2]))
        count += len(line_a[::2])
    return total / count


def main():
    library = promos.Library()
    promo = next((p for p in library.read() if p['id'] == 'time-temp'), None)
    if promo is None or not promo['present']:
        raise SystemExit('Build the time-temp promo first: ident/promos/build.py time-temp')
    path = library.folder / promo['file']
    values = {}                                            # no temperature: only the time and AM/PM
    live = ad_break.PromoReel(Gst, promo, path, VIDEO, AUDIO, values)
    plain = ad_break.Reel(Gst, promo, path, VIDEO, AUDIO)
    try:
        assert live.cue() and plain.cue(), 'both cue'
        boxes = {o['field']: o['box'] for o in promo['overlays']}
        t = 4.0
        a, b = frame_at(live, t), frame_at(plain, t)
        time_box, temp_box = boxes['time'], boxes['temperature']
        inside = mean_difference(a, b, time_box)
        empty = mean_difference(a, b, temp_box)
        away = mean_difference(a, b, (40, 40, 160, 120))
        print(f'at {t} s: time box differs by {inside:.1f}, temperature box {empty:.1f}, a corner {away:.1f} (Y levels)')
        # The two decodes may sit a frame apart, and the build's grain moves every frame: a few levels.
        assert inside > 12 and inside > 4 * max(empty, away), 'the time is drawn'
        assert empty < 8 and away < 8, 'nothing else changes (no reading: no temperature)'
        sound = live.sound(int(t * 1e9), 4800 * 8)
        level = max(abs(int.from_bytes(sound[i:i + 4], 'little', signed=True)) for i in range(0, len(sound), 400))
        assert level > 0, 'sound comes through'
        assert live.draw_failed is None, live.draw_failed
        print('OK: the live text is blended into the promo as it decodes')
    finally:
        live.close()
        plain.close()


if __name__ == '__main__':
    main()
