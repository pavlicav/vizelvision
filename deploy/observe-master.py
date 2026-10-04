#!/usr/bin/env python3
"""Bounded, read-only observation of master, capture and contribution health."""
import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.config import load_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=7200)
    parser.add_argument('--interval', type=float, default=2)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 86400 or not 1 <= args.interval <= 60:
        parser.error('seconds must be 1–86400 and interval 1–60')
    config = load_config(Path(__file__).resolve().parents[1] / 'config.master.json')
    directory = config.state_file.parent
    headers = {'X-API-Key': config.server.api_key} if config.server.api_key else {}
    log = logging.getLogger('master-observer')
    log.setLevel(logging.INFO)
    log.addHandler(RotatingFileHandler(directory / 'master-observation.jsonl', maxBytes=4_000_000, backupCount=2))
    base = f'http://127.0.0.1:{config.server.port}/'
    def read(url, private=False):
        try:
            with urlopen(Request(url, headers=headers if private else {}), timeout=2) as response:
                return json.load(response)
        except Exception as exc:
            return {'observation_error': str(exc)}
    started = time.time()
    deadline = time.monotonic() + args.seconds
    records = 0
    try:
        while time.monotonic() < deadline:
            master = read(base+'v1/master', True)
            capture = read(base+'v1/roku/capture', True)
            contribution = read(config.master.status_url.rsplit('/', 1)[0]+'/roku')
            record = {'at': time.time(), 'master': {k: master.get(k) for k in
                ('state', 'on_air', 'recovery', 'last_input_failure', 'last_recovery', 'input_tracks', 'error', 'observation_error')},
                'capture': {k: capture.get(k) for k in ('stream_id', 'capture', 'last_stream_failure', 'observation_error')},
                'contribution': {k: contribution.get(k) for k in
                    ('ready', 'source', 'inboundBytes', 'inboundFramesInError', 'observation_error')}}
            log.info(json.dumps(record))
            records += 1
            time.sleep(min(args.interval, max(0, deadline-time.monotonic())))
    finally:
        (directory / 'master-observation-summary.json').write_text(json.dumps(
            {'started_at': started, 'finished_at': time.time(), 'records': records,
             'log': str(directory / 'master-observation.jsonl')}, indent=2)+'\n')


if __name__ == '__main__':
    main()
