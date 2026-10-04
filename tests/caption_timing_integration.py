"""Measure caption/audio sync with deterministic speech markers and real GStreamer.

One private stream, generated tone bursts, a timestamp-returning recognizer, and a
controlled ad mute. Does not access production, hardware or external services.
Real Whisper is separately covered by captions_integration.py.
"""
from array import array
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.caption_settings import DEFAULTS
from roku_stream.master_media import MasterMedia, DecodedInput
from roku_stream.publication import LocalMediaMtx

SECOND = 1_000_000_000


class Recognizer:
    def __init__(self, _settings):
        pass

    def transcribe(self, pcm):
        samples = array('f')
        samples.frombytes(pcm)
        # Return the precise bounds of each audible burst, to 10 ms resolution.
        rows, start = [], None
        for i in range(0, len(samples) + 160, 160):
            loud = max((abs(x) for x in samples[i:i + 160]), default=0) > .01
            if loud and start is None:
                start = i / 16000
            if not loud and start is not None:
                rows.append({'start': start, 'end': min(i, len(samples)) / 16000, 'text': 'Speech marker'})
                start = None
        return rows

    def close(self):
        pass

    cancel = close


class Tap:
    delay_ns = 4 * SECOND

    def gray(self, *_): pass
    def rgb(self, *_): pass
    def audio(self, *_): pass

    def gain(self, pts):
        return 0.0 if 12 * SECOND <= pts < 16 * SECOND else 1.0


def edges(rows, rising=True):
    before, result = False, []
    for pts, flag in rows:
        if flag != before and flag == rising:
            result.append(pts / SECOND)
        before = flag
    return result


def main():
    with tempfile.TemporaryDirectory(prefix='vv-caption-timing-') as directory:
        root = Path(directory)
        clip = root / 'bursts.mkv'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=30:d=26',
                        '-f', 'lavfi', '-i', 'aevalsrc=if(between(mod(t\,4)\,1\,2)\,0.2*sin(2*PI*440*t)\,0):s=48000:d=26',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'pcm_f32le', '-ac', '2', str(clip)],
                       check=True, timeout=20)
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), root) as server:
            output = MasterMedia(server.rtsp_url, width=640, height=360, fps=30, encoder='x264')
            source = None
            try:
                output.captions.factory = Recognizer
                output.configure_captions({**DEFAULTS, 'enabled': True})
                source = DecodedInput(output, 1, clip.as_uri(), tap=Tap())
                until = time.monotonic() + 10
                while not (source.ready() and output.healthy()):
                    output.poll(); source.poll()
                    assert time.monotonic() < until
                    time.sleep(.02)
                self_delay = output.programme.delay_ns / SECOND
                assert source.delay == 0 and self_delay == 6, (source.delay, self_delay)
                output.take(1)
                cut = output.running_time() / SECOND
                audio, video, offsets = [], [], []
                sink = output.pipeline.get_by_name('delayed_audio')
                emit = sink.emit
                def record_audio(signal, buf):
                    if signal == 'push-buffer':
                        samples = array('f')
                        samples.frombytes(buf.extract_dup(0, buf.get_size()))
                        audio.append((buf.pts, max((abs(x) for x in samples), default=0) > .01))
                    return emit(signal, buf)
                sink.emit = record_audio
                release = output.release_programme
                def record_delay(kind, buffer, due, duration, pts, route):
                    if pts is not None:
                        offsets.append((due - pts) / SECOND)
                    return release(kind, buffer, due, duration, pts, route)
                output.release_programme = record_delay
                def record_frame(_pad, info):
                    video.append((info.get_buffer().pts, bool(output.caption_text)))
                    return output.gst.PadProbeReturn.OK
                output.pipeline.get_by_name('live_captions').get_static_pad('src').add_probe(
                    output.gst.PadProbeType.BUFFER, record_frame)
                until = time.monotonic() + 22
                while time.monotonic() < until:
                    output.poll(); source.poll()
                    time.sleep(.02)
                # Ignore the off-air fill and choose only fully observed phrases.
                minimum = cut + self_delay + .5
                sound = [p for p in edges(audio) if p > minimum]
                captions = [p for p in edges(video) if p > minimum]
                assert len(sound) >= 3 and len(sound) == len(captions), (sound, captions)
                errors = [abs(a - b) for a, b in zip(sound, captions)]
                assert max(errors) < .10, errors
                assert offsets and max(abs(x - 6) for x in offsets) < .001
                assert output.programme.dropped <= 2, output.programme.status()
                # The burst at input 13 seconds is muted, with no leaked subtitle.
                muted_at = source.to_master(13 * SECOND) / SECOND + self_delay
                assert not any(abs(p - muted_at) < 1 for p in captions), (muted_at, captions)
                assert all(t['backwards'] == 0 for t in output.status().values())
                print(json.dumps({'ok': True, 'shared_delay_seconds': self_delay, 'input_delay_seconds': source.delay,
                                  'caption_onset_errors_seconds': errors, 'muted_ad_caption_suppressed': True,
                                  'programme': output.programme.status(), 'tracks': output.status()}, indent=2))
            finally:
                if source: source.close()
                output.close()


if __name__ == '__main__':
    main()
