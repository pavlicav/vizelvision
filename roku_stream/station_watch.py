"""Tell someone when the station is stuck.

On 2026-10-08 a failed entry blocked Up next from Thursday night until Monday morning, and
nobody knew. Every minute this looks for what an operator would notice at a glance: Up next
paused, an entry blocked, the test card while the schedule wants a program, master not
answering. A problem that lasts its grace period is logged ("Station watch: ...") and, when
alerts.json names an ntfy topic, pushed to a phone; again when it clears.

alerts.json (beside queue.json, read at every check, so no restart is needed):
    {"ntfy": "https://ntfy.sh/<a long private topic name>"}
"""
from __future__ import annotations

import json
import logging
import threading
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .source_queue import HOLD_REASON, RETURNING

CHECK_SECONDS = 60
# How long each kind of problem lasts before it is reported.
GRACE_SECONDS = {'paused': 15 * 60, 'blocked': 10 * 60, 'test_card': 5 * 60, 'master': 2 * 60}
# Pauses that are part of running: a held take, and the hand-back after it.
ROUTINE_PAUSES = (HOLD_REASON, RETURNING)

LOG = logging.getLogger(__name__)


def _title(item):
    target = item.get('target') or {}
    return item.get('title') or (item.get('program') or {}).get('title') or target.get('channel_id') or 'An entry'


class StationWatch:
    def __init__(self, queue_status, on_air, on_now, settings_path, *, clock=time.monotonic, send=None):
        """queue_status() is Up next's status; on_air() master's input on air (None for the
        test card; raises when master does not answer); on_now() the schedule's program now
        (None for OFF AIR); send(url, text, cleared) pushes one alert."""
        self.queue_status, self.on_air, self.on_now = queue_status, on_air, on_now
        self.settings_path, self.clock = settings_path, clock
        self.send = send or self._ntfy
        self._seen = {}       # problem key -> {'since': monotonic, 'text', 'reported'}
        self._lock = threading.Lock()
        self._stopping = threading.Event()

    # -- what is wrong ------------------------------------------------------
    def problems(self):
        """{key: text} of what is wrong now. A blocked entry's key carries its id."""
        found = {}
        try:
            status = self.queue_status()
        except Exception as exc:
            status = None
            found['master'] = f'Up next does not answer ({exc})'
        if status:
            if status.get('paused') and status.get('pause_reason') not in ROUTINE_PAUSES:
                found['paused'] = f"Up next is paused ({status.get('pause_reason') or 'by an operator'})"
            for item in status.get('items') or ():
                if item.get('status') == 'blocked':
                    why = item.get('gate_detail') or (item.get('error') or {}).get('message') or 'failed'
                    found['blocked:' + item['id']] = f'{_title(item)} is blocked: {why}'
        try:
            on_air = self.on_air()
        except Exception as exc:
            found['master'] = f'Master does not answer ({exc})'
        else:
            if not on_air or on_air.get('source_id') == 'off-air':
                wanted = self._wanted(status)
                if wanted:
                    found['test_card'] = f'The test card is on, but {wanted} should be'
        return found

    def _wanted(self, status):
        hold = (status or {}).get('hold')
        if hold:
            target = hold.get('target') or {}
            return (hold.get('game') or {}).get('title') or target.get('channel_id') or 'a held take'
        try:
            now = self.on_now()
        except Exception:
            return None
        return (now.get('title') or 'the scheduled program') if now else None

    # -- reporting ----------------------------------------------------------
    def check(self):
        """One pass: report problems past their grace, and those that cleared."""
        found, now = self.problems(), self.clock()
        due, cleared = [], []
        with self._lock:
            for key, text in found.items():
                seen = self._seen.setdefault(key, {'since': now, 'text': text, 'reported': False})
                seen['text'] = text
                if not seen['reported'] and now - seen['since'] >= GRACE_SECONDS[key.split(':')[0]]:
                    seen['reported'] = True
                    due.append(text)
            for key in [k for k in self._seen if k not in found]:
                seen = self._seen.pop(key)
                if seen['reported']:
                    cleared.append(seen['text'])
        for text in due:
            self._report(text, cleared=False)
        for text in cleared:
            self._report(text, cleared=True)

    def view(self):
        """For GET /v1/alerts: what is wrong now, for how long, and whether pushes go out."""
        now = self.clock()
        with self._lock:
            problems = [{'key': key, 'text': seen['text'], 'seconds': round(now - seen['since']),
                         'reported': seen['reported']} for key, seen in self._seen.items()]
        return {'problems': problems, 'push': bool(self._url())}

    def _report(self, text, cleared):
        LOG.warning('Station watch: %s%s', 'cleared: ' if cleared else '', text)
        url = self._url()
        if not url:
            return
        try:
            self.send(url, text, cleared)
        except Exception as exc:
            LOG.warning('Station watch could not send its alert: %s', exc)

    def _url(self):
        try:
            url = json.loads(self.settings_path.read_text()).get('ntfy')
        except (OSError, ValueError, AttributeError):
            return None
        return url if isinstance(url, str) and urlsplit(url).scheme in ('http', 'https') else None

    @staticmethod
    def _ntfy(url, text, cleared):
        request = Request(url, data=text.encode(), method='POST', headers={
            'Title': 'VizelVision: ' + ('all clear' if cleared else 'needs a look'),
            'Priority': 'default' if cleared else 'high',
            'Tags': 'white_check_mark' if cleared else 'warning'})
        with urlopen(request, timeout=10) as response:
            response.read(1024)

    # -- the thread ---------------------------------------------------------
    def run(self):
        while not self._stopping.wait(CHECK_SECONDS):
            try:
                self.check()
            except Exception as exc:  # The watch must not die.
                LOG.warning('Station watch: %s', exc)

    def start(self):
        thread = threading.Thread(target=self.run, name='station-watch', daemon=True)
        thread.start()
        return thread

    def stop(self):
        self._stopping.set()
