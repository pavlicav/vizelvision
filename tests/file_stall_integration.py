"""A library file on air survives a stall of its decoder; never contacts source hardware.

Reproduces 2026-10-01 16:50, when a host-wide stall of a few seconds failed a Jeopardy
rerun off the air: a 30 s clip is taken to a real master worker, then its decoder is
frozen for 3 s mid-air. With the fix the worker holds the test card, takes the same file
back, and the file plays on; with --without-fix the file fails as it did that day.

Run: /usr/bin/python3 tests/file_stall_integration.py [--without-fix]
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import LibraryConfig, LibraryRoot, MasterConfig, TvThingConfig
from roku_stream.master_media import FileInput
from roku_stream.master_worker import MasterWorker, MasterClient, control_socket
from roku_stream.publication import LocalMediaMtx


def wait_for(check, timeout=20, what=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError('Timed out waiting for ' + (what or repr(check)))


def main():
    if '--without-fix' in sys.argv:
        FileInput.RIDES_OUT_STALLS = False
    with tempfile.TemporaryDirectory(prefix='vv-file-stall-') as directory:
        root = Path(directory)
        media = root / 'media' / 'Show'
        media.mkdir(parents=True)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=s=640x360:r=30:d=30',
                        '-f', 'lavfi', '-i', 'sine=frequency=440:duration=30', '-c:v', 'libx264', '-preset', 'ultrafast',
                        '-c:a', 'aac', '-shortest', str(media / 'rerun.mp4')], check=True)
        (root / 'output').mkdir()
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), root / 'output') as output:
            config = SimpleNamespace(
                master=MasterConfig(enabled=True, socket_path=root / 'master.sock', rtsp_url=output.rtsp_url,
                                    status_url=output.api_url + 'paths/get/' + output.path, width=640, height=360,
                                    fps=30, bitrate=1200, off_air_radio_info_url=None, eas_url=None, nws_zones=()),
                tv_thing=TvThingConfig(enabled=False),
                library=LibraryConfig(True, (LibraryRoot('gate', 'Gate', root / 'media'),)))
            worker = MasterWorker(config)
            client = MasterClient(config.master)
            with control_socket(worker):
                threading.Thread(target=worker.run, daemon=True).start()
                wait_for(lambda: client.request().get('can_prepare'), what='publisher')

                def operation(action, body):
                    op = client.request(action, body)
                    return wait_for(lambda: (lambda s: s if (s.get('operation') or {}).get('id') == op['id']
                                             and s['operation']['state'] != 'pending' else None)(client.request()), what=action)
                state = operation('prepare', {'source_id': 'library', 'channel_id': 'gate/Show/rerun.mp4'})
                cued = state['prepared']
                time.sleep(1)
                operation('take', {'prepared_id': cued['id']})
                time.sleep(5)
                decoder = worker.inputs[cued['id']]['decoder']
                frozen = {'video': True, 'audio': True}

                def stall(pad, info, kind):  # The whole host stops for three seconds, once.
                    if frozen[kind]:
                        frozen[kind] = False
                        time.sleep(3)
                    return decoder.gst.PadProbeReturn.OK
                for kind in ('video', 'audio'):
                    decoder.pipeline.get_by_name(kind).get_static_pad('sink').add_probe(decoder.gst.PadProbeType.BUFFER, stall, kind)
                time.sleep(12)
                status = client.request()
                on_air = (status.get('on_air') or {}).get('id')
                failure = status.get('last_input_failure')
                result = {'on_air_is_the_file': on_air == cued['id'],
                          'position': (status.get('on_air') or {}).get('media', {}).get('position_seconds'),
                          'last_input_failure': failure and failure.get('error'),
                          'recovered': status.get('last_recovery') is not None,
                          'late_dropped': decoder.late if hasattr(decoder, 'late') else None}
                print(json.dumps(result))
                if '--without-fix' in sys.argv:
                    assert not result['on_air_is_the_file'] and failure, result
                    print('REPRODUCED: without the fix the file fails off the air:', failure['error'])
                else:
                    # The stall itself is logged as a recovery ("stopped arriving"), never a failure.
                    assert result['on_air_is_the_file'] and result['recovered'], result
                    assert not failure or failure['error'] == 'Input audio/video stopped arriving', result
                    assert result['position'] and result['position'] > 10, result
                    print('PASS: the file rode out a 3 s stall and is still on air at', result['position'], 's')
                worker.stopping.set()


if __name__ == '__main__':
    main()
