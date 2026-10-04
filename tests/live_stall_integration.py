"""A live feed on air rides out a stall of its decoder; never contacts source hardware.

Reproduces 2026-10-04, when the Colts at Commanders game was failed off the air eight
times in 25 minutes (YouTube TV, then FOX 5 over the antenna) although its picture looked
fine: a second without media cut to the test card. A live RTSP feed (an isolated MediaMTX,
fed by ffmpeg, standing in for a tuner) is taken to a real master worker, then its decoder
is frozen for 3 s mid-air. With the fix master holds the feed's picture and carries on
with the same input; with --without-fix it cuts to the test card and recovers there.

With --source-pause the feed itself stops for 3 s instead (its sender is suspended) and
then carries on 3 s behind the clock for good: master holds the picture, then re-anchors
the feed on air.

Run: nice -n 19 taskset -c 6,7 /usr/bin/python3 tests/live_stall_integration.py [--without-fix] [--source-pause]
"""
import signal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import MasterConfig, TvThingConfig
from roku_stream.master_media import DecodedInput
from roku_stream.master_worker import MasterWorker, MasterClient, control_socket
from roku_stream.publication import LocalMediaMtx

MEDIAMTX = Path('vendor/mediamtx/1.21.0/mediamtx').resolve()


class FakeLease:
    lane = 'digital'

    def __init__(self, target, url):
        self.target, self.url, self.generation = dict(target), url, 'integration'

    def tune(self):
        pass

    def renew(self, *, force=False):
        pass

    def check(self):
        return self.url

    def release(self):
        return True


class FakeTv:
    def __init__(self, url):
        self.url = url

    def acquire(self, target):
        return FakeLease(target, self.url)


def wait_for(check, timeout=30, what=None):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError('Timed out waiting for ' + (what or repr(check)))


def main():
    without = '--without-fix' in sys.argv
    if without:
        DecodedInput.RIDES_OUT_ON_AIR = False
    with tempfile.TemporaryDirectory(prefix='vv-live-stall-') as directory:
        root = Path(directory)
        (root / 'output').mkdir()
        (root / 'source').mkdir()
        with LocalMediaMtx(MEDIAMTX, root / 'output') as output, LocalMediaMtx(MEDIAMTX, root / 'source') as source:
            feed = subprocess.Popen(
                ['ffmpeg', '-v', 'error', '-re', '-f', 'lavfi', '-i', 'testsrc=s=640x360:r=30',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-c:v', 'libx264', '-preset', 'ultrafast',
                 '-tune', 'zerolatency', '-g', '30', '-c:a', 'aac', '-f', 'rtsp', '-rtsp_transport', 'tcp',
                 source.rtsp_url], stdin=subprocess.DEVNULL)
            try:
                config = SimpleNamespace(
                    master=MasterConfig(enabled=True, socket_path=root / 'master.sock', rtsp_url=output.rtsp_url,
                                        status_url=output.api_url + 'paths/get/' + output.path, width=640, height=360,
                                        fps=30, bitrate=1200, off_air_radio_info_url=None, eas_url=None, nws_zones=(),
                                        encoder='x264'),
                    tv_thing=TvThingConfig(enabled=True))
                worker = MasterWorker(config, tv=FakeTv(source.rtsp_url))
                client = MasterClient(config.master)
                with control_socket(worker):
                    threading.Thread(target=worker.run, daemon=True).start()
                    wait_for(lambda: client.request().get('can_prepare'), what='publisher')

                    def operation(action, body):
                        op = client.request(action, body)
                        return wait_for(lambda: (lambda s: s if (s.get('operation') or {}).get('id') == op['id']
                                                 and s['operation']['state'] != 'pending' else None)(client.request()),
                                        what=action)
                    state = operation('prepare', {'source_id': 'tv-thing-digital', 'channel_id': 'test_5_1'})
                    prepared = state['prepared']
                    assert prepared, state
                    operation('take', {'prepared_id': prepared['id']})
                    time.sleep(5)
                    decoder = worker.inputs[prepared['id']]['decoder']
                    frozen = {'video': True, 'audio': True}

                    def stall(pad, info, kind):  # The feed stops for three seconds, once.
                        if frozen[kind]:
                            frozen[kind] = False
                            time.sleep(3)
                        return decoder.gst.PadProbeReturn.OK
                    if '--source-pause' in sys.argv:
                        feed.send_signal(signal.SIGSTOP)
                        threading.Timer(3, feed.send_signal, (signal.SIGCONT,)).start()
                    else:
                        for kind in ('video', 'audio'):
                            decoder.pipeline.get_by_name(kind).get_static_pad('sink').add_probe(
                                decoder.gst.PadProbeType.BUFFER, stall, kind)
                    seen, deadline = set(), time.monotonic() + 15
                    while time.monotonic() < deadline:  # what master shows, through and after the stall
                        status = client.request()
                        seen.add('feed' if (status.get('on_air') or {}).get('id') == prepared['id'] else 'test card')
                        if status.get('stall'):
                            seen.add('held picture')
                        time.sleep(.05)
                    status = client.request()
                    failure = status.get('last_input_failure')
                    result = {'seen': sorted(seen), 'on_air_is_the_feed': (status.get('on_air') or {}).get('id') == prepared['id'],
                              'last_input_failure': failure and failure.get('error'),
                              'recovered_on_the_test_card': status.get('last_recovery') is not None,
                              'output_tracks': {k: v.get('age_seconds') for k, v in (status.get('tracks') or {}).items()},
                              'input': decoder.status(), 'reanchors': getattr(decoder, 'reanchors', None)}
                    print(json.dumps(result))
                    if without:
                        assert 'test card' in seen, result
                        print('REPRODUCED: without the fix the stall cuts to the test card')
                    else:
                        assert seen == {'feed', 'held picture'} and result['on_air_is_the_feed'], result
                        assert not failure and not result['recovered_on_the_test_card'], result
                        assert all(v['filled'] > 0 for v in result['input'].values()), result
                        print('PASS: the feed held its picture through a 3 s stall and stayed on air')
                    worker.stopping.set()
            finally:
                feed.terminate()
                feed.wait(5)


if __name__ == '__main__':
    main()
