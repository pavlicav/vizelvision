"""Opt-in LIVE NBC prepare/take gate. Navigates the real Roku and leaves NBC on master.

Run only with operator authorization: /usr/bin/python3 tests/live_roku_master.py
"""
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import load_config
from roku_stream.publication import PublicationMonitor, cancellation_handlers


def main():
    config = load_config('config.master.json')
    base = f'http://127.0.0.1:{config.server.port}/'
    api = config.master.status_url.rsplit('paths/get/', 1)[0]
    headers = {'X-API-Key': config.server.api_key} if config.server.api_key else {}

    def request(path, body=None):
        with urlopen(Request(base + path, data=None if body is None else json.dumps(body).encode(),
                             headers={**headers, 'Content-Type': 'application/json'}), timeout=5) as response:
            return json.load(response)

    def media(path):
        with urlopen(api + path, timeout=3) as response:
            return json.load(response)

    server = SimpleNamespace(rtsp_url=config.master.rtsp_url, hls_url=config.master.hls_url + 'index.m3u8',
                             path=config.master.rtsp_url.rsplit('/', 1)[1], check=lambda: None,
                             status=lambda: media('paths/get/master'), sessions=lambda: media('rtspsessions/list')['items'])
    monitor = PublicationMonitor(server)
    report = {'ok': False, 'target': {'source_id': 'youtube-tv', 'channel_id': 'NBC'},
              'on_air_observation_seconds': 30, 'limitations': 'NBC only; no real MLB game or lip-sync measurement.'}
    pending = False
    with cancellation_handlers():
        try:
            assert not request('v1/operation').get('active'), 'Roku is busy'
            assert (request('v1/master').get('operation') or {}).get('state') != 'pending', 'Master is busy'
            monitor.started(lambda: time.sleep(.03))

            def wait_operation(operation, timeout):
                deadline = time.monotonic() + timeout
                next_progress = 0
                while time.monotonic() < deadline:
                    monitor.poll()
                    state = request('v1/master')
                    current = state.get('operation') or {}
                    assert current.get('id') == operation['id'], 'Another operator changed the current operation'
                    if current.get('state') != 'pending':
                        assert current.get('state') == 'succeeded', state
                        return state
                    if time.monotonic() >= next_progress:
                        cue = request('v1/operation')
                        print(json.dumps({'master': state['state'], 'action': current.get('action'),
                                          'roku_phase': cue.get('phase'), 'message': cue.get('message')}), flush=True)
                        next_progress = time.monotonic() + 15
                    time.sleep(.2)
                raise AssertionError('Timed out waiting for source operation')

            started = time.monotonic()
            operation = request('v1/master/prepare', report['target'])
            pending = True
            state = wait_operation(operation, 420)
            pending = False
            report['prepare_seconds'] = round(time.monotonic() - started, 2)
            assert state['on_air'] is None and state['prepared']['source_id'] == 'youtube-tv'
            assert state['prepared']['channel_id'] == 'NBC' and state['can_take']
            cue = request('v1/operation')
            assert cue.get('phase') == 'complete' and cue.get('channel') == 'NBC'
            report['verification_operation_id'] = cue['id']
            operation = request('v1/master/take', {'prepared_id': state['prepared']['id']})
            pending = True
            state = wait_operation(operation, 30)
            pending = False
            assert state['on_air']['source_id'] == 'youtube-tv' and state['on_air']['channel_id'] == 'NBC'
            print('NBC is on master; checking 30 seconds of subscriber continuity', flush=True)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                monitor.poll()
                state = request('v1/master')
                assert state['on_air'] and state['on_air']['channel_id'] == 'NBC', state
                time.sleep(.15)
            monitor._hls()
            assert server.status()['source']['id'] == monitor.publisher_id
            assert monitor.reader_id in {s['id'] for s in server.sessions() if s['state'] == 'read'}
            with monitor.lock:
                assert all(not t['backwards'] and t['max_pts_gap_seconds'] < .5
                           and t['max_arrival_gap_seconds'] < 1 for t in monitor.tracks.values())
                report['tracks'] = {k: {f: v for f, v in t.items() if f not in ('samples', 'last_at', 'last_pts')}
                                    for k, t in monitor.tracks.items()}
            owners = subprocess.run(['fuser', config.feedback.device], capture_output=True, text=True, timeout=3)
            assert owners.returncode == 0 and len(owners.stdout.split()) == 1
            report.update(ok=True, same_master_publisher_and_reader=True, single_capture_owner=True,
                          hls_streams=monitor.hls_probe, left_on_air=state['on_air'])
        finally:
            if pending:
                request('v1/master/cancel', {})
            if monitor.pipeline:
                monitor.pipeline.set_state(monitor.gst.State.NULL)
    Path('docs/live-roku-master-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
