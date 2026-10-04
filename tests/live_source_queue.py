"""Opt-in real NBC queue take. Requires operator authorization; leaves NBC on master."""
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
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
        with urlopen(Request(base+path, data=None if body is None else json.dumps(body).encode(),
                             headers={**headers, 'Content-Type': 'application/json'}), timeout=5) as response:
            return json.load(response)
    def media(path):
        with urlopen(api+path, timeout=3) as response:
            return json.load(response)
    server = SimpleNamespace(rtsp_url=config.master.rtsp_url, hls_url=config.master.hls_url+'index.m3u8',
        path='master', check=lambda: None, status=lambda: media('paths/get/master'),
        sessions=lambda: media('rtspsessions/list')['items'])
    report = {'ok': False, 'target': {'source_id': 'youtube-tv', 'channel_id': 'NBC'},
              'observation_seconds': 30, 'limitations': 'NBC only; no physical MLB or analog test, no lip-sync measurement.'}
    monitor = PublicationMonitor(server)
    item_id = None
    with cancellation_handlers():
        try:
            q = request('v1/queue')
            assert q.get('master_queue'), 'New master queue is not deployed'
            assert not any(i['status'] in ('queued', 'running', 'blocked') for i in q['items']), 'Existing pending work must be preserved'
            assert not request('v1/operation').get('active'), 'Roku is busy'
            assert (request('v1/master').get('operation') or {}).get('state') != 'pending', 'Master is busy'
            monitor.started(lambda: time.sleep(.03))
            item = request('v1/queue', {'target': report['target'], 'release_type': 'at_time',
                           'run_at': (datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat()})
            item_id = item['id']
            report['queue_item_id'] = item_id
            request('v1/queue/resume', {})
            started, deadline, next_progress = time.monotonic(), time.monotonic()+420, 0
            while time.monotonic() < deadline:
                monitor.poll()
                current = next(i for i in request('v1/queue')['items'] if i['id'] == item_id)
                if current['status'] in ('succeeded', 'blocked', 'skipped'):
                    report['queue_result'] = current
                    assert current['status'] == 'succeeded', current
                    break
                if time.monotonic() >= next_progress:
                    cue = request('v1/operation')
                    print(json.dumps({'queue_status': current['status'], 'phase': cue.get('phase'),
                                      'message': cue.get('message')}), flush=True)
                    next_progress = time.monotonic()+15
                time.sleep(.2)
            else:
                raise AssertionError('Queue did not finish within 420 seconds')
            report['release_and_prepare_seconds'] = round(time.monotonic()-started, 2)
            state = request('v1/master')
            assert state['on_air']['source_id'] == 'youtube-tv' and state['on_air']['channel_id'] == 'NBC'
            request('v1/queue/pause', {})
            key = state['on_air']['id']
            deadline = time.monotonic()+30
            while time.monotonic() < deadline:
                monitor.poll()
                assert (request('v1/master').get('on_air') or {}).get('id') == key, 'On-air input changed or stalled'
                time.sleep(.25)
            monitor._hls()
            assert server.status()['source']['id'] == monitor.publisher_id
            assert monitor.reader_id in {s['id'] for s in server.sessions() if s['state'] == 'read'}
            owners = subprocess.run(['fuser', config.feedback.device], capture_output=True, text=True, timeout=3)
            assert len(owners.stdout.split()) == 1
            with monitor.lock:
                assert all(not t['backwards'] and t['max_pts_gap_seconds'] < .5
                           and t['max_arrival_gap_seconds'] < 1 for t in monitor.tracks.values())
                report['tracks'] = {k: {f: v for f, v in t.items() if f not in ('samples', 'last_at', 'last_pts')}
                                    for k, t in monitor.tracks.items()}
            report.update(ok=True, same_publisher_and_reader=True, one_capture_owner=True, hls_streams=monitor.hls_probe)
        except BaseException as exc:
            report['error'] = str(exc)
            raise
        finally:
            if item_id:
                request('v1/queue/pause', {})
                state = request('v1/master')
                if (state.get('operation') or {}).get('queue_item_id') == item_id and state['operation']['state'] == 'pending':
                    request('v1/master/cancel', {})
            if monitor.pipeline:
                monitor.pipeline.set_state(monitor.gst.State.NULL)
            Path('docs/live-source-queue-validation.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
