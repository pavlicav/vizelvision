"""Isolated encoded test-card/tone check; never contacts source hardware.

Run: /usr/bin/python3 tests/off_air_integration.py
"""
import copy
import functools
import http.server
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import MasterConfig
from roku_stream.master_media import MasterMedia, DecodedInput
from roku_stream.production import DEFAULTS, ProductionSettings
from roku_stream.publication import LocalMediaMtx, PublicationMonitor


def wait(check, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.05)
    raise AssertionError('Media readiness timed out')


def main():
    with tempfile.TemporaryDirectory(prefix='vv-off-air-') as directory:
        root = Path(directory)
        # A local MP3 "station" stands in for Cairo radio: mono 44.1 kHz like the real one.
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:sample_rate=44100:duration=60', '-ac', '1', '-b:a', '128k',
                        str(root / 'radio.mp3')], check=True, timeout=30)
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        radio = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(root)))
        threading.Thread(target=radio.serve_forever, daemon=True).start()
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), root) as server:
            output = MasterMedia(server.rtsp_url, radio_url=f'http://127.0.0.1:{radio.server_port}/radio.mp3')
            monitor = source = None
            try:
                wait(output.healthy)
                monitor = PublicationMonitor(server)
                monitor.started(lambda: (monitor.poll(), time.sleep(.02)))
                publisher = monitor.publisher_id
                settings = ProductionSettings(MasterConfig(socket_path=root / 'master.sock'))
                def sample(label, expected_energy, expected_crossings, bars):
                    time.sleep(1.5)
                    monitor.poll()
                    with monitor.lock:
                        audio = list(monitor.tracks['audio']['samples'])
                        video = list(monitor.tracks['video']['samples'])
                    energy = sum(s[0] for s in audio) / len(audio)
                    crossings = sum(s[1] for s in audio) / len(audio)
                    assert abs(energy-expected_energy) < max(.002, expected_energy*.15), (label, energy)
                    assert abs(crossings-expected_crossings) < 1.5, (label, crossings)
                    assert all(abs(v-103) < 4 for v in video) if bars else all(abs(v-63) < 4 for v in video), (label, video)
                    assert server.status()['source']['id'] == publisher
                    assert monitor.reader_id in {s['id'] for s in server.sessions() if s['state']=='read'}
                    print(json.dumps({'phase': label, 'energy': energy, 'frequency_hz': round(crossings*100), 'luma': video[-1]}), flush=True)

                sample('uploaded bars and 1 kHz default', .005, 10, True)
                monitor._hls()
                subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-rtsp_transport', 'tcp',
                                '-i', server.rtsp_url, '-frames:v', '1', '-update', '1', '-y',
                                '/tmp/vizelvision-encoded-test-card.png'], check=True, timeout=15)
                body = copy.deepcopy(DEFAULTS)
                body['audio'] = 'silence'
                body['captions']['master'] = 'ENGINEERING <&> CHECK'
                settings.save(body)
                output.set_test_card(settings.card('master'))
                sample('saved caption and silence', 0, 0, True)
                body['audio'] = 'radio'
                settings.save(body)
                output.set_test_card(settings.card('master'))
                for _ in range(40):
                    output.poll()
                    time.sleep(.05)
                sample('off-air radio replaces tone', .0070, 4.4, True)
                output.radio.url = f'http://127.0.0.1:{radio.server_port}/missing.mp3'
                output.radio.set_enabled(False)
                output.radio.set_enabled(True)
                for _ in range(40):
                    output.poll()
                    time.sleep(.05)
                sample('unreachable radio is silent without failing master', 0, 0, True)
                assert output.radio.pipeline is None and output.radio.retry_at > time.monotonic()
                body['audio'] = 'tone'
                settings.save(body)
                output.set_test_card(settings.card('master'))
                source = DecodedInput(output, 1, '', test_pattern=4)
                wait(source.ready)
                output.take(1)
                sample('live source replaces test card and tone', .32, 4.4, False)
                output.take(0)
                sample('fallback restores bars and 1 kHz', .005, 10, True)
                assert all(t['backwards']==0 for t in monitor.tracks.values())
                monitor._hls()
                print('PASS: stable publisher and reader, continuous timestamps, HLS A/V, caption reload, silence, radio, radio failure, and tone switching.', flush=True)
            except Exception:
                print(server.log_path.read_text()[-6000:], file=sys.stderr)
                raise
            finally:
                if source:
                    source.close()
                if monitor and monitor.pipeline:
                    monitor.pipeline.set_state(monitor.gst.State.NULL)
                output.close()
                radio.shutdown()


if __name__ == '__main__':
    main()
