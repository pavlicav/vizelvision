"""Ad mute on a real master publisher; never contacts source hardware or the sidecar.

Starts a private MediaMTX and a 720p30 master, then plays a generated programme (test
pattern, 1 kHz tone) through DecodedInput with an ad-mute tap whose gain the test
controls, with a generated 440 Hz "radio" standing in for Cairo radio. Checks:

  1. the tap gets 320x180 GRAY8 frames, ~1 fps 224x224 RGB and 16 kHz mono audio
  2. the programme plays the delay behind the tapped copy
  3. a muted stretch of the schedule silences exactly that programme audio
  4. the AD badge is drawn top left (amber) on the master output, and goes away
  5. the break bed: audio slot 4 carries the radio at the set level; back to the
     programme afterwards, with the output real time throughout

Run: /usr/bin/python3 tests/admute_master_integration.py [screenshot.png]
"""
from array import array
from pathlib import Path
import math
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.master_media import DecodedInput, MasterMedia
from roku_stream.publication import LocalMediaMtx

W, H, FPS = 1280, 720, 30
SECOND = 1_000_000_000
DELAY = 2 * SECOND


def wait(check, timeout=30, poll=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if poll:
            poll()
        if check():
            return
        time.sleep(.05)
    raise AssertionError('Timed out')


def pixel(url, x, y, screenshot=None):
    with tempfile.NamedTemporaryFile(suffix='.png') as frame:
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-rtsp_transport', 'tcp', '-i', url,
                        '-frames:v', '1', '-update', '1', '-y', frame.name], check=True, timeout=20)
        if screenshot:
            Path(screenshot).write_bytes(Path(frame.name).read_bytes())
        raw = subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-i', frame.name, '-vf',
                              f'crop=1:1:{x}:{y}', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                             check=True, capture_output=True, timeout=10).stdout
        return tuple(raw)


def mean_volume(url, seconds=1.5):
    out = subprocess.run(['ffmpeg', '-hide_banner', '-rtsp_transport', 'tcp', '-i', url, '-t', str(seconds), '-vn',
                          '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True, timeout=30).stderr
    for line in out.splitlines():
        if 'mean_volume' in line:
            return float(line.split('mean_volume:')[1].split('dB')[0])
    raise AssertionError(out[-500:])


class Tap:
    def __init__(self):
        self.delay_ns = DELAY
        self.lock = threading.Lock()
        self.audio_n = 0
        self.sizes = set()
        self.newest = None
        self.mute = None          # (from_pts, to_pts)

    def _seen(self, pts):
        with self.lock:
            self.newest = pts if self.newest is None else max(self.newest, pts)

    def gain(self, pts):
        m = self.mute
        return 0.0 if m and m[0] <= pts < m[1] else 1.0


class CountingTap(Tap):
    """Also the largest step between a kind's timestamps: the tap must stay on the input's
    timeline (2026-10-02: master retimed the buffer the tap shares, so some frames arrived
    on master's clock instead)."""
    def _step(self, kind, pts):
        last = getattr(self, 'last_' + kind, None)
        if last is not None:
            self.worst_step = max(getattr(self, 'worst_step', 0), abs(pts - last))
        setattr(self, 'last_' + kind, pts)

    def gray(self, pts, data):
        self._seen(pts)
        with self.lock:
            self._step('G', pts)
            self.gray_n = getattr(self, 'gray_n', 0) + 1
            self.sizes.add(('G', len(data)))

    def rgb(self, pts, data):
        with self.lock:
            self._step('R', pts)
            self.rgb_n = getattr(self, 'rgb_n', 0) + 1
            self.sizes.add(('R', len(data)))

    def audio(self, pts, data):
        with self.lock:
            self._step('A', pts)
            self.audio_n += len(data) // 4


def main(screenshot=None):
    with tempfile.TemporaryDirectory(prefix='vv-admute-') as directory:
        d = Path(directory)
        program, radio = d / 'program.mp4', d / 'radio.ogg'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        f'testsrc2=size={W}x{H}:rate={FPS}', '-f', 'lavfi', '-i', 'sine=frequency=1000:sample_rate=48000',
                        '-t', '60', '-af', 'volume=0.5', '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac',
                        '-ac', '2', str(program)], check=True)
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=48000', '-t', '120', '-af', 'volume=0.5', '-ac', '2',
                        '-c:a', 'libvorbis', str(radio)], check=True)
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), d) as server:
            output = MasterMedia(server.rtsp_url, width=W, height=H, fps=FPS, bitrate=4000,
                                 radio_url=radio.as_uri(), radio_gain_db=0.0)
            tap = CountingTap()
            pushed = []                          # (input pts, rms) of programme audio sent to master
            decoder = None
            try:
                wait(output.healthy, poll=output.poll)
                time.sleep(6)                    # master's clock well ahead of the input's
                decoder = DecodedInput(output, 1, program.as_uri(), tap=tap)
                source = output.pipeline.get_by_name('delayed_audio')
                emit = source.emit

                def spy(signal, buffer):
                    if signal == 'push-buffer':
                        data = buffer.extract_dup(0, buffer.get_size())
                        a = array('f')
                        a.frombytes(data[: len(data) // 4 * 4])
                        rms = math.sqrt(sum(x * x for x in a) / max(1, len(a)))
                        anchor = decoder.anchor  # _sample holds the decoder's lock while it pushes
                        pushed.append((buffer.pts - output.programme.delay_ns - anchor[1] + anchor[0] if anchor else None, rms))
                    return emit(signal, buffer)
                source.emit = spy
                wait(decoder.ready, timeout=40, poll=decoder.poll)
                output.take(1)

                # 1. The tap.
                time.sleep(3)
                with tap.lock:
                    assert getattr(tap, 'gray_n', 0) > 60 and getattr(tap, 'rgb_n', 0) >= 2 and tap.audio_n > 16000 * 2, \
                        (getattr(tap, 'gray_n', 0), getattr(tap, 'rgb_n', 0), tap.audio_n)
                    assert tap.sizes == {('G', 320 * 180), ('R', 224 * 224 * 3)}, tap.sizes
                print('1. tap: gray', tap.gray_n, 'rgb', tap.rgb_n, 'audio samples', tap.audio_n)

                # 2. The programme runs the delay behind the tap.
                assert decoder.delay == 0 and output.programme.delay_ns == DELAY
                program_pts = decoder.from_master(output.running_time() - output.programme.delay_ns)
                lead = (tap.newest - program_pts) / SECOND
                assert 1.5 < lead < 3.5, lead
                print(f'2. programme {lead:.2f}s behind the tap (delay {DELAY / SECOND:.1f}s)')

                # 3. Mute a stretch the programme has not reached yet.
                start = tap.newest + SECOND // 2
                tap.mute = (start, start + 2 * SECOND)
                wait(lambda: pushed and pushed[-1][0] is not None and pushed[-1][0] > start + 3 * SECOND,
                     poll=decoder.poll)
                inside = [r for p, r in pushed if p is not None and start + SECOND // 10 <= p < start + 19 * SECOND // 10]
                before = [r for p, r in pushed if p is not None and start - SECOND <= p < start - SECOND // 10]
                after = [r for p, r in pushed if p is not None and start + 21 * SECOND // 10 <= p < start + 3 * SECOND]
                assert inside and max(inside) < 1e-6, max(inside or [1])
                assert before and min(before) > .01 and after and min(after) > .01, (before[:3], after[:3])
                print(f'3. muted stretch silent ({len(inside)} buffers), sound before and after')

                # 4. The badge.
                now = output.running_time()
                output.set_badge([(now, now + 30 * SECOND, 'AD', 'SHADOW · 97%')])
                time.sleep(1.5)
                rgb = pixel(server.rtsp_url, output.badge.x + 6, output.badge.y + output.badge.size // 2, screenshot)
                assert rgb[0] > 200 and 140 < rgb[1] < 230 and rgb[2] < 80, rgb
                output.set_badge([])
                time.sleep(1.5)
                rgb2 = pixel(server.rtsp_url, output.badge.x + 6, output.badge.y + output.badge.size // 2)
                assert not (rgb2[0] > 200 and 140 < rgb2[1] < 230 and rgb2[2] < 80), rgb2
                print('4. badge drawn', rgb, 'and cleared', rgb2)

                # 5. The bed.
                output.want_bed(True)
                wait(lambda: output.radio.pipeline is not None, poll=output.poll)
                time.sleep(1.5)
                output.set_bed(0.0)
                output.take_audio(4)
                time.sleep(DELAY / SECOND + 1)
                quiet = mean_volume(server.rtsp_url)
                output.set_bed(1.0)
                time.sleep(DELAY / SECOND + 1)
                loud = mean_volume(server.rtsp_url)
                output.take_audio(1)
                time.sleep(DELAY / SECOND + 1)
                back = mean_volume(server.rtsp_url)
                assert quiet < -60 and loud > -40 and back > -40, (quiet, loud, back)
                lag = max(t.get('lag_seconds') or 0 for t in output.status().values())
                assert output.healthy() and lag < 2, (output.status())
                with tap.lock:
                    print('tap timeline: largest step', round(tap.worst_step / 1e9, 3), 's')
                    assert tap.worst_step < 1.5e9, 'the tap left the input timeline'  # R is 1 per second
                print(f'5. bed: silent {quiet:.0f} dB, radio {loud:.0f} dB, programme back {back:.0f} dB; lag {lag:.2f}s')
                print('PASS')
            finally:
                if decoder:
                    decoder.close()
                output.close()


if __name__ == '__main__':
    main(*sys.argv[1:2])
