"""Validate the existing Roku contribution through a temporary master.

Does not open hardware or navigate the Roku. The running web app remains the
device owner; this gate also reads its MJPEG preview while consuming both tracks.
"""
import json
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import load_config
from roku_stream.master_media import DecodedInput, MasterMedia
from roku_stream.publication import LocalMediaMtx, PublicationMonitor, cancellation_handlers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=30)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 600:
        parser.error('--seconds must be between 30 and 600')
    config = load_config('config.master.json')
    assert config.feedback.contribution_url, 'Enable the shared capture contribution first'
    status_url = config.master.status_url.rsplit('/', 1)[0] + '/roku'
    web = f'http://127.0.0.1:{config.server.port}'

    def status():
        with urlopen(status_url, timeout=3) as response:
            return json.load(response)

    def owners():
        result = subprocess.run(['fuser', config.feedback.device], capture_output=True, text=True, timeout=3)
        assert result.returncode == 0, result.stderr
        return result.stdout.split()

    original = status()
    original_owners = owners()
    assert original['ready'] and len(original_owners) == 1
    report = {'ok': False, 'roku_navigation_calls': 0, 'device_open_calls': 0,
              'on_air_observation_seconds': args.seconds, 'preview_frames': 0,
              'limitations': 'Current Roku picture only; no channel navigation or lip-sync measurement.'}
    with cancellation_handlers(), tempfile.TemporaryDirectory(prefix='vv-current-roku-') as directory:
        with LocalMediaMtx(Path('vendor/mediamtx/1.21.0/mediamtx').resolve(), Path(directory)) as server:
            output = MasterMedia(server.rtsp_url)
            monitor = PublicationMonitor(server)
            decoder = None
            try:
                def poll():
                    output.poll()
                    monitor.poll()
                    if decoder:
                        decoder.poll()
                    time.sleep(.03)

                monitor.started(poll)
                decoder = DecodedInput(output, 1, config.feedback.contribution_url)
                deadline = time.monotonic() + 30
                while not decoder.ready() and time.monotonic() < deadline:
                    poll()
                assert decoder.ready(), 'Roku audio and video did not decode'
                # Warm an inactive input before taking it.
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    poll()
                output.take(1)
                deadline = time.monotonic() + report['on_air_observation_seconds']
                next_preview = 0
                while time.monotonic() < deadline:
                    poll()
                    assert decoder.ready(), decoder.status()
                    if time.monotonic() >= next_preview:
                        with urlopen(web + '/v1/preview', timeout=10) as response:
                            payload = b''
                            while b'\xff\xd9' not in payload and len(payload) < 2000000:
                                payload += response.read(4096)
                            assert b'\xff\xd8' in payload and b'\xff\xd9' in payload
                        report['preview_frames'] += 1
                        next_preview = time.monotonic() + 5
                assert decoder.ready()
                monitor._hls()
                output.take(0)
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    poll()
                assert server.status()['source']['id'] == monitor.publisher_id
                assert monitor.reader_id in {s['id'] for s in server.sessions() if s['state'] == 'read'}
                with monitor.lock:
                    assert all(not t['backwards'] and t['max_pts_gap_seconds'] < .5
                               and t['max_arrival_gap_seconds'] < 1 for t in monitor.tracks.values())
                    report['tracks'] = {k: {f: v for f, v in t.items()
                                            if f not in ('samples', 'last_at', 'last_pts')}
                                        for k, t in monitor.tracks.items()}
                assert status()['source']['id'] == original['source']['id']
                assert owners() == original_owners
                report.update(ok=True, same_single_device_owner=True, same_contribution_publisher=True,
                              same_master_publisher_and_reader=True, hls_streams=monitor.hls_probe)
            finally:
                if decoder:
                    decoder.close()
                if monitor.pipeline:
                    monitor.pipeline.set_state(monitor.gst.State.NULL)
                output.close()
    Path('docs/current-roku-input-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
