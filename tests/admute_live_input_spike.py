"""Ad-mute tap and delay on the real live inputs; read-only (never tunes, never locks).

Reads the running TV-Thing digital HLS feed and/or the Roku capture's RTSP path as an
extra viewer into a private MediaMTX + master (720p30), with an ad-mute tap and a
3.75 s delay, for SECONDS each. Reports whether the input settles, the programme's lead
behind the tap, A/V alignment of the programme, timeline faults, the worker process's
memory growth, and output lag.

Run: /usr/bin/python3 tests/admute_live_input_spike.py [hls|roku|both] [seconds]
"""
from pathlib import Path
import resource
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.master_media import DecodedInput, MasterMedia
from roku_stream.publication import LocalMediaMtx

SECOND = 1_000_000_000
URLS = {'hls': 'http://127.0.0.1:8080/stream/digital.m3u8', 'roku': 'rtsp://127.0.0.1:18554/roku'}


class Tap:
    delay_ns = int(3.75 * SECOND)

    def __init__(self):
        self.lock = threading.Lock()
        self.newest = {'G': None, 'A': None}
        self.count = {'G': 0, 'R': 0, 'A': 0}

    def _see(self, kind, pts):
        with self.lock:
            self.count[kind] += 1
            if kind in self.newest:
                self.newest[kind] = pts if self.newest[kind] is None else max(self.newest[kind], pts)

    def gray(self, pts, data): self._see('G', pts)
    def rgb(self, pts, data): self._see('R', pts)
    def audio(self, pts, data): self._see('A', pts)
    def gain(self, pts): return 1.0


def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def trial(output, name, seconds):
    tap = Tap()
    decoder = DecodedInput(output, 1, URLS[name], tap=tap)
    started = time.monotonic()
    try:
        while not decoder.ready():
            decoder.poll()
            if time.monotonic() - started > 45:
                raise AssertionError(f'{name}: not ready after 45 s: {decoder.status()}')
            time.sleep(.05)
        ready_after = time.monotonic() - started
        output.take(1)
        base_rss, leads, skews, worst_lag = rss_mb(), [], [], 0.
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            decoder.poll()
            time.sleep(1)
            with decoder.lock:
                v, a = decoder.last['video']['pts'], decoder.last['audio']['pts']
            with tap.lock:
                g = tap.newest['G']
            if v is not None and g is not None:
                leads.append((g - decoder.from_master(v)) / SECOND)
            if v is not None and a is not None:
                skews.append((v - a) / SECOND)
            worst_lag = max(worst_lag, max(t.get('lag_seconds') or 0 for t in output.status().values()))
        output.take(0)
        print(f'{name}: ready after {ready_after:.1f}s; tap frames {tap.count}; '
              f'lead {min(leads):.2f}-{max(leads):.2f}s (delay {Tap.delay_ns / SECOND}s); '
              f'programme video-audio {min(skews):+.2f}..{max(skews):+.2f}s; '
              f'late-dropped {decoder.late}; error {decoder.error}; '
              f'max RSS +{rss_mb() - base_rss:.0f} MB (now {rss_mb():.0f} MB); worst output lag {worst_lag:.2f}s')
        assert decoder.error is None, decoder.error
        assert 3.0 < min(leads) and max(leads) < 6.0, leads
        assert max(abs(s) for s in skews) < .6, skews
        assert worst_lag < 2, worst_lag
    finally:
        decoder.close()


def main(which='both', seconds='60'):
    with tempfile.TemporaryDirectory(prefix='vv-admute-live-') as d:
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), Path(d)) as server:
            output = MasterMedia(server.rtsp_url, width=1280, height=720, fps=30, bitrate=4000)
            try:
                deadline = time.monotonic() + 30
                while not output.healthy():
                    output.poll()
                    assert time.monotonic() < deadline, 'master never healthy'
                    time.sleep(.05)
                for name in (('hls', 'roku') if which == 'both' else (which,)):
                    trial(output, name, float(seconds))
                print('PASS')
            finally:
                output.close()


if __name__ == '__main__':
    main(*sys.argv[1:3])
