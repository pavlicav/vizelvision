"""My ads on a real master publisher; never contacts source hardware or the sidecar.

Starts a private MediaMTX and a small master, plays a generated programme (test pattern,
1 kHz tone) through DecodedInput with an ad-mute tap whose gain the test controls, and
two "ads" of my own: solid red with a 660 Hz tone and solid blue with 330 Hz, 3 s each,
both limited to once an hour, in list order; the break card is solid green. Every frame
and sound buffer master sends out is recorded (by input time). Checks:

  1. a muted stretch shows ad A, then ad B, then (both over their limit) the card, each
     with the programme in a framed corner and a LIVE tab; A's and B's sound, then silence
  2. outside it, the programme as it was: picture and its tone
  3. the play log: A and B complete and counted, then the card's stretch
  4. a break with nothing left to play is the card from its first frame
  5. "It's the show" one second into an ad (the limit lifted) cuts it short: the
     programme is back at once, and the cut-short play does not count
  6. the output stays real time; what the composite costs per frame

Run: /usr/bin/python3 tests/myads_master_integration.py
"""
from array import array
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.admute_settings import DEFAULTS as ADMUTE
from roku_stream.master_media import DecodedInput, MasterMedia
from roku_stream.my_ads import MyAds, read_plays
from roku_stream.ad_break import Pip
from roku_stream.publication import LocalMediaMtx

W, H, FPS = 640, 360, 30
SECOND = 1_000_000_000
DELAY = 2 * SECOND

# Solid colours by their chroma (ffmpeg's colour sources encode BT.601, the card BT.709).
COLOURS = {'red': lambda y, u, v: v > 200 and u < 140, 'blue': lambda y, u, v: u > 200 and v < 160,
           'green': lambda y, u, v: u < 90 and v < 90}


def wait(check, timeout=30, poll=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if poll:
            poll()
        if check():
            return
        time.sleep(.05)
    raise AssertionError('Timed out')


def make(path, *args):
    subprocess.run(['nice', '-n', '19', 'ffmpeg', '-hide_banner', '-loglevel', 'error', *args, str(path)], check=True)


class Tap:
    def __init__(self):
        self.delay_ns = DELAY
        self.lock = threading.Lock()
        self.newest = None
        self.mutes = []          # [(from_pts, to_pts)]

    def gray(self, pts, data):
        with self.lock:
            self.newest = pts if self.newest is None else max(self.newest, pts)

    def rgb(self, pts, data):
        pass

    def audio(self, pts, data):
        pass

    def gain(self, pts):
        return 0.0 if any(a <= pts < b for a, b in self.mutes) else 1.0


def solid(data):
    """The colour a whole frame is (three points agree), or None."""
    points = [pixel(data, W // 2, H // 4), pixel(data, W // 4, H // 2), pixel(data, 3 * W // 4, H // 8)]
    return next((name for name, test in COLOURS.items() if all(test(*p) for p in points)), None)


def pixel(data, x, y):
    ys, cs = W * H, (W // 2) * (H // 2)
    return data[y * W + x], data[ys + (y // 2) * (W // 2) + x // 2], data[ys + cs + (y // 2) * (W // 2) + x // 2]


def tone(data):
    """(rms, Hz) of a buffer of F32 stereo, from the left channel's zero crossings."""
    a = array('f')
    a.frombytes(data[: len(data) // 8 * 8])
    left = a[0::2]
    if not left:
        return 0., 0.
    rms = (sum(x * x for x in left) / len(left)) ** .5
    crossings = sum(1 for i in range(1, len(left)) if (left[i - 1] < 0) != (left[i] < 0))
    return rms, crossings / 2 / (len(left) / 48000)


def main():
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    with tempfile.TemporaryDirectory(prefix='vv-myads-') as directory:
        d = Path(directory)
        program = d / 'program.mp4'
        make(program, '-f', 'lavfi', '-i', f'testsrc2=size={W}x{H}:rate={FPS}', '-f', 'lavfi', '-i',
             'sine=frequency=1000:sample_rate=48000', '-t', '90', '-af', 'volume=0.5', '-c:v', 'libx264',
             '-preset', 'ultrafast', '-c:a', 'aac', '-ac', '2')
        store = MyAds(d / 'master.sock')
        store.folder.mkdir()
        for ad_id, colour, hz in (('aaaaaaaaaaaa', 'red', 660), ('bbbbbbbbbbbb', 'blue', 330)):
            make(store.folder / f'{ad_id}.mp4', '-f', 'lavfi', '-i', f'color=c={colour}:size=1280x720:rate=25', '-f', 'lavfi',
                 '-i', f'sine=frequency={hz}:sample_rate=44100', '-t', '3', '-af', 'volume=0.5', '-c:v', 'libx264',
                 '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-c:a', 'aac')
        make(store.folder / 'card-own-12345678.png', '-f', 'lavfi', '-i', 'color=c=lime:size=800x600', '-frames:v', '1')
        hour = {'count': 1, 'minutes': 60}
        settings = store.save({'order': 'list', 'card': {'text': 'STAY TUNED', 'image': 'card-own-12345678.png'},
                               'ads': [{'id': 'aaaaaaaaaaaa', 'file': 'aaaaaaaaaaaa.mp4', 'name': 'Ad A', 'duration': 3.0,
                                        'limit': hour},
                                       {'id': 'bbbbbbbbbbbb', 'file': 'bbbbbbbbbbbb.mp4', 'name': 'Ad B', 'duration': 3.0,
                                        'limit': hour}]})
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), d) as server:
            output = MasterMedia(server.rtsp_url, width=W, height=H, fps=FPS, bitrate=1500, encoder='x264')
            tap = Tap()
            frames, sounds = [], []          # (input pts, ...)
            decoder = None
            try:
                wait(output.healthy, poll=output.poll)
                time.sleep(4)
                output.configure_admute({**ADMUTE, 'mode': 'on', 'lookahead': 1.0})
                output.configure_my_ads(settings, store)
                decoder = DecodedInput(output, 1, program.as_uri(), tap=tap)

                def to_input(due):
                    anchor = decoder.anchor
                    return due - output.programme.delay_ns - anchor[1] + anchor[0] if anchor else None

                for kind, log in (('video', frames), ('audio', sounds)):
                    source = output.pipeline.get_by_name('delayed_' + kind)

                    def spy(signal, buffer, emit=source.emit, kind=kind, log=log):
                        if signal == 'push-buffer':
                            data = buffer.extract_dup(0, buffer.get_size())
                            if kind == 'video':
                                pip = output.ad_break.pip
                                log.append((to_input(buffer.pts), solid(data), pixel(data, pip.x - 2, pip.y + pip.h // 2),
                                            pixel(data, pip.x + 6, pip.y + 6)))
                            else:
                                log.append((to_input(buffer.pts), *tone(data)))
                        return emit(signal, buffer)
                    source.emit = spy
                costs, corner = [], []       # the composite's time; (programme centre, the corner's centre)
                picture = output.ad_break.picture

                def timed(live, *args):
                    t = time.perf_counter()
                    result = picture(live, *args)
                    if result is not None:
                        costs.append(time.perf_counter() - t)
                        # An even point of the corner (4:2:0 chroma is shared by 2x2 pixels) and where it comes from.
                        pip = output.ad_break.pip
                        x, y = pip.w // 2 & ~1, pip.h // 2 & ~1
                        corner.append((pixel(live.extract_dup(0, live.get_size()), pip.f * x, pip.f * y),
                                       pixel(result.extract_dup(0, result.get_size()), pip.x + x, pip.y + y)))
                    return result
                output.ad_break.picture = timed

                wait(decoder.ready, timeout=40, poll=decoder.poll)
                output.take(1)
                wait(lambda: output.ad_break.cued is not None and output.ad_break.card is not None, timeout=20)
                time.sleep(2)

                # 1-3. A break of 8 s: A (3 s), B (3 s), the card (2 s).
                start = tap.newest + SECOND
                tap.mutes.append((start, start + 8 * SECOND))
                wait(lambda: frames and frames[-1][0] is not None and frames[-1][0] > start + 9 * SECOND, poll=decoder.poll)

                def span(log, a, b):
                    return [row for row in log if row[0] is not None and start + a * SECOND <= row[0] < start + b * SECOND]
                for (a, b), want, hz, what in (((.15, 2.85), 'red', 660, 'ad A'), ((3.15, 5.85), 'blue', 330, 'ad B'),
                                               ((6.15, 7.85), 'green', None, 'the card')):
                    shown = span(frames, a, b)
                    if not (shown and all(f[1] == want for f in shown)):
                        print('plays', read_plays(store.plays_path))
                        print('frames', [(round((f[0] - start) / SECOND, 3), f[1]) for f in frames if f[0] is not None and f[1]][:12])
                    assert shown and all(f[1] == want for f in shown), (what, [f[1] for f in shown][:5])
                    assert all(all(abs(a - b) < 6 for a, b in zip(f[2], Pip.EDGE)) for f in shown), (what, 'frame', shown[0][2])
                    assert all(f[3][2] > 170 for f in shown), (what, 'LIVE tab', shown[0][3])
                    heard = span(sounds, a + .1, b - .1)
                    if hz:
                        wrong = [(round((p - start) / SECOND, 3), round(r, 3), round(f)) for p, r, f in heard
                                 if not (r > .02 and abs(f - hz) < hz * .12)]
                        assert heard and not wrong, (what, len(heard), wrong[:8])
                    else:
                        assert heard and max(r for _, r, _ in heard) < 1e-4, (what, max(r for _, r, _ in heard))
                    print(f'1. {what}: {len(shown)} frames, framed programme in the corner, '
                          + (f'{hz} Hz' if hz else 'silent'))
                assert corner and all(a == b for a, b in corner), [c for c in corner if c[0] != c[1]][:3]
                print(f'1. the corner is the programme itself ({len(corner)} frames match it pixel for pixel)')
                outside = span(frames, -1.5, -.15) + span(frames, 8.15, 8.9)
                assert outside and all(f[1] is None for f in outside), [f[1] for f in outside][:5]
                heard = span(sounds, -1.5, -.15) + span(sounds, 8.2, 8.9)
                assert heard and all(r > .02 and abs(f - 1000) < 60 for _, r, f in heard), heard[:3]
                print(f'2. outside the break: the programme ({len(outside)} frames, 1 kHz)')
                time.sleep(.6)
                rows = read_plays(store.plays_path)
                assert [(r['kind'], r.get('name'), r.get('complete'), r.get('counted')) for r in rows] == \
                    [('ad', 'Ad A', True, True), ('ad', 'Ad B', True, True), ('card', None, None, None)], rows
                assert 1.7 < rows[2]['seconds'] < 2.3 and all(2.8 < r['seconds'] < 3.2 for r in rows[:2]), rows
                print('3. play log:', [(r['kind'], r.get('name'), r['seconds']) for r in rows])

                # 4. Both over their limit: the card from the first frame.
                start = tap.newest + SECOND
                tap.mutes.append((start, start + 2 * SECOND))
                wait(lambda: frames[-1][0] is not None and frames[-1][0] > start + 3 * SECOND, poll=decoder.poll)
                shown = span(frames, .05, 1.95)
                assert shown and all(f[1] == 'green' for f in shown), [f[1] for f in shown][:4]
                print(f'4. nothing left to play: the card ({len(shown)} frames)')

                # 5. Lift A's limit; mute, and say "It's the show" one second into it.
                settings['ads'][0]['limit'] = None
                settings = store.save(settings)
                output.configure_my_ads(settings, store)
                wait(lambda: output.ad_break.cued is not None, timeout=20)
                start = tap.newest + SECOND
                tap.mutes.append((start, start + 20 * SECOND))
                wait(lambda: frames[-1][0] is not None and frames[-1][0] > start + SECOND // 2, poll=decoder.poll, timeout=10)
                tap.mutes[-1] = (start, start + SECOND)          # the operator's fix: back at 1 s
                wait(lambda: frames[-1][0] is not None and frames[-1][0] > start + 2 * SECOND, poll=decoder.poll)
                assert all(f[1] == 'red' for f in span(frames, .1, .95))
                back = span(frames, 1.04, 1.9)
                assert back and all(f[1] is None for f in back), [f[1] for f in back][:4]
                time.sleep(.6)
                last = read_plays(store.plays_path)[-1]
                assert (last['name'], last['complete'], last['counted']) == ('Ad A', False, False) \
                    and .9 < last['seconds'] < 1.15, last
                print(f'5. cut short at {last["seconds"]} s: programme back on the next frame; not counted')

                # 6.
                lag = max(t.get('lag_seconds') or 0 for t in output.status().values())
                assert output.healthy() and lag < 2, output.status()
                costs.sort()
                print(f'6. healthy, lag {lag:.2f}s; composite median {1000 * costs[len(costs) // 2]:.2f} ms, '
                      f'p95 {1000 * costs[int(len(costs) * .95)]:.2f} ms over {len(costs)} frames at {W}x{H}')
                print('status', json.dumps(output.my_ads_status()))
                print('PASS')
            finally:
                if decoder:
                    decoder.close()
                output.close()


if __name__ == '__main__':
    main()
