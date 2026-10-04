"""Persist the last verified Roku selection, separately from live authority."""
import copy
import json
import math
import os
import time

from .roku_input import ROKU_SOURCE_IDS


class RokuPreparation:
    def __init__(self, master):
        self.path = master.socket_path.with_name('roku-last-prepared.json')
        self.max_age = master.roku_prepare_max_age_seconds
        self.record = None
        try:
            record = json.loads(self.path.read_text())
            if (isinstance(record, dict) and isinstance(record.get('target'), dict)
                    and isinstance(record.get('selection_id'), str) and record['selection_id']
                    and record['target'].get('source_id') in ROKU_SOURCE_IDS
                    and isinstance(record['target'].get('channel_id'), str)
                    and type(record.get('prepared_at')) in (int, float)
                    and math.isfinite(record['prepared_at'])):
                self.record = record
        except (OSError, ValueError):
            pass

    def remember(self, target, claim):
        record = {'target': copy.deepcopy(target), 'prepared_at': time.time(),
                  'selection_id': claim['selection_id'],
                  'resolved_source': copy.deepcopy(claim.get('resolved_source'))}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(record, handle)
        os.replace(temporary, self.path)
        self.record = record

    def snapshot(self, claim):
        if not self.record:
            return None
        age = time.time() - self.record['prepared_at']
        current = bool(claim and claim.get('selection_id') == self.record['selection_id']
                       and claim.get('target') == self.record['target'])
        recent = 0 <= age <= self.max_age
        return {**copy.deepcopy(self.record), 'age_seconds': round(age, 1),
                'max_age_seconds': self.max_age, 'reusable': current and recent,
                'reason': None if current and recent else
                    'Roku changed or service restarted; prepare again' if not current else
                    'Last preparation expired; prepare again'}
