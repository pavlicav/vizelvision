"""Real Whisper + master video smoke test, on an isolated MediaMTX with the local ID.

VIZELVISION_WHISPER_PYTHON=/path/to/python /usr/bin/python3 tests/captions_integration.py
Never contacts source hardware or changes the production stream. Requires cached base.en.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.caption_settings import DEFAULTS
from roku_stream.master_media import MasterMedia, FileInput
from roku_stream.publication import LocalMediaMtx


def wait(check, poll, timeout=25):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        poll()
        if check():
            return
        time.sleep(.05)
    raise AssertionError('Timed out')


def main():
    with tempfile.TemporaryDirectory(prefix='vv-captions-') as directory:
        root = Path(directory)
        # A black canvas makes subtitle pixels directly inspectable after decoding.
        clip = root / 'speech.mp4'
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
                        'color=c=black:s=1280x720:r=30:d=16', '-ss', '12', '-i', 'ident/vizelvision-sports.mp4',
                        '-map', '0:v', '-map', '1:a', '-t', '16', '-c:v', 'libx264', '-preset', 'ultrafast',
                        '-c:a', 'aac', str(clip)], check=True, timeout=20)
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), root) as server:
            output = MasterMedia(server.rtsp_url, width=1280, height=720, fps=30, encoder='x264')
            source = None
            try:
                wait(output.healthy, output.poll)
                assert output.captions.thread is None
                source = FileInput(output, 1, clip.as_uri())
                wait(source.ready, source.poll)
                source.cue()
                source.start()
                wait(source.ready, source.poll)
                output.take(1)
                output.configure_captions({**DEFAULTS, 'enabled': True})
                def poll():
                    output.poll()
                    source.poll()
                    status = output.caption_status()
                    assert not status['error'], status
                wait(lambda: bool(output.caption_status()['text']), poll)
                status = output.caption_status()
                assert status['programme_delay']['seconds'] == 6
                assert status['programme_delay']['dropped_buffers'] <= 2, status
                assert status['timing'] == 'audio_timestamps'
                overlay = output.pipeline.get_by_name('live_captions')
                assert not overlay.get_property('silent'), status
                assert output.caption_text == status['text']
                print('Whisper:', json.dumps(status), flush=True)
                # Keep polling on another thread while the independent RTSP reader connects.
                import threading
                done = threading.Event()
                def refresh():
                    while not done.wait(.05):
                        output.poll()
                thread = threading.Thread(target=refresh)
                thread.start()
                try:
                    frame = subprocess.run(['ffmpeg', '-v', 'error', '-rtsp_transport', 'tcp', '-i', server.rtsp_url,
                                            '-frames:v', '1', '-vf', 'crop=1100:180:90:420', '-pix_fmt', 'gray',
                                            '-f', 'rawvideo', '-'], capture_output=True, check=True, timeout=15).stdout
                    assert sum(p > 180 for p in frame) > 100, 'Decoded stream contains no caption glyphs'
                finally:
                    done.set()
                    thread.join()
                output.configure_captions(DEFAULTS)
                assert overlay.get_property('silent') and not output.caption_status()['text']
                wait(lambda: output.captions.worker is None, output.poll, timeout=3)
                output.take(0)
                wait(output.healthy, output.poll)
                lag = max(t['lag_seconds'] or 0 for t in output.status().values())
                assert lag < 1, output.status()
                assert all(t['backwards'] == 0 for t in output.status().values())
                print(f'PASS: local speech -> timed Whisper cues -> encoded captions; one shared 6s delay; '
                      f'toggle cleared text; master lag {lag:.2f}s')
            finally:
                if source:
                    source.close()
                output.close()


if __name__ == '__main__':
    main()
