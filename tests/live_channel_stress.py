"""Explicitly invoked live test: changes Roku channels; never unittest-discovered."""
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = 'http://localhost:6969'
OUT = Path('state/stress-720p/results.json')
results = {}


def request(path, data=None):
    start = time.monotonic()
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            status, payload = response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        status, payload = exc.code, json.load(exc)
    return {'status': status, 'seconds': round(time.monotonic() - start, 4), 'body': payload}


def save():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2) + '\n')


def burst(name, calls):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda call: request(*call), calls))
    results[name] = rows
    counts = {code: sum(r['status'] == code for r in rows) for code in {r['status'] for r in rows}}
    times = sorted(r['seconds'] for r in rows)
    print(name, counts, 'median', statistics.median(times), 'p95', times[int(.95*(len(times)-1))], flush=True)
    save()
    return rows


def wait_operation(operation_id, limit=300):
    start = time.monotonic()
    phase = None
    while time.monotonic() - start < limit:
        row = request('/v1/operations/' + operation_id)
        op = row['body']
        if op.get('phase') != phase:
            phase = op.get('phase')
            print(operation_id, round(time.monotonic()-start, 1), phase, op.get('message'), flush=True)
        if not op.get('active'):
            return {'elapsed_seconds': round(time.monotonic()-start, 2), 'operation': op}
        time.sleep(2)
    request('/v1/operations/' + operation_id + '/cancel', {})
    row = wait_operation(operation_id, 25) if limit != 25 else {'operation': request('/v1/operations/' + operation_id)['body']}
    return {'deadline_exceeded': True, **row}


def main(channels=('ESPN', 'ESPN2', 'FOX')):
    results['signal'] = request('/v1/roku/signal')
    initial = request('/v1/operation')['body']
    if initial.get('active'):
        raise SystemExit('An existing operation is active; do not run the live test over it')
    burst('dry_run', [('/v1/play', {'channel': c, 'dry_run': True}) for c in ['ESPN', 'ESPN2', 'FOX', 'ABC'] * 10])
    burst('invalid', [('/v1/play', body) for body in [{'channel': 'NOT A CHANNEL', 'wait': False}, {'channel': 'ESPN', 'wait': 'false'}, {}] * 4])
    rows = burst('admission', [('/v1/play', {'channel': 'ESPN', 'wait': False})] * 24)
    accepted = [row['body']['operation_id'] for row in rows if row['status'] == 202]
    if len(accepted) != 1:
        raise RuntimeError(f'Expected one accepted cue, got {len(accepted)}')
    operation_id = accepted[0]
    results['stale_cancel'] = request('/v1/operations/' + '0'*32 + '/cancel', {})
    burst('status_under_cue', [('/v1/operation', None)] * 40)
    results['cancel'] = request('/v1/operations/' + operation_id + '/cancel', {})
    results['cancel_completion'] = wait_operation(operation_id, 25)
    save()
    results['switches'] = []
    for channel in channels:
        admitted = request('/v1/play', {'channel': channel, 'wait': False})
        entry = {'channel': channel, 'admission': admitted}
        results['switches'].append(entry)
        save()
        if admitted['status'] != 202:
            break
        entry.update(wait_operation(admitted['body']['operation_id']))
        if entry.get('operation', {}).get('phase') == 'complete':
            time.sleep(5)
            try:
                with urllib.request.urlopen(BASE + '/v1/preview', timeout=25) as response:
                    response.readline()
                    headers = {}
                    while True:
                        line = response.readline().strip()
                        if not line:
                            break
                        key, value = line.decode().split(':', 1)
                        headers[key.lower()] = value.strip()
                    picture = response.read(int(headers['content-length']))
                path = OUT.parent / (channel.lower().replace(' ', '-') + '-playing.jpg')
                path.write_bytes(picture)
                entry['preview_frame'] = str(path)
            except Exception as exc:
                entry['preview_error'] = str(exc)
        save()
        if entry.get('operation', {}).get('active'):
            break
    results['final_signal'] = request('/v1/roku/signal')
    results['final_status'] = request('/v1/roku/status')
    save()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True, help='Authorize real channel changes')
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--channels', nargs='+', default=['ESPN', 'ESPN2', 'FOX'])
    args = parser.parse_args()
    OUT = args.output
    main(args.channels)
