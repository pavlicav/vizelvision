"""The crawl's ledger: every item the crawl could air, by a stable id, and when it aired.

Feeds name their items (eas:<id>, nws:<urn>, rail:<incident>, score:mlb:<game>, …); an
item a feed cannot name is known by its words (<segment>:<hash>). The desk notes an item
each time its segment lists it, and an airing each time a bulletin, the always-on loop or
the worker's important or override layer starts carrying it. From that the Crawl page can
say of each item whether it has aired yet (a first airing or a repeat), how often, and when
last; and the desk's new_now rule asks it which items are news.

What a segment lists the first time the desk looks at it, or while its new_now is off, is
taken in as background, never as news, so turning things on is not a burst of pop-ups.
An item no segment has listed for a day is forgotten, and is news again if it comes back.

It is saved beside crawl.json (debounced), so a web restart forgets neither what aired nor
what was already known.
"""
from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
import threading
import time

from . import crawl

KEEP = 86400        # forget an item no segment has listed for this long
AIRINGS = 12        # airings kept per item
SAVE_EVERY = 20     # seconds between saves of routine changes
CONTENT = ('tag', 'heading', 'text')
META = ('source', 'issued', 'expires', 'severity', 'event', 'areas', 'by', 'routes')


class CrawlLedger:
    def __init__(self, path=None, *, clock=time.time):
        self.path = Path(path) if path else None
        self.clock = clock
        self.lock = threading.RLock()
        self.items = {}
        self.learned = set()
        self.dirty, self.saved_at = False, 0.
        self._load()

    # ------------------------------------------------------------------ storage

    def _load(self):
        if self.path is None:
            return
        try:
            value = json.loads(self.path.read_text())
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            logging.getLogger(__name__).warning('Crawl ledger unreadable, starting afresh: %s', exc)
            return
        if isinstance(value, dict) and value.get('version') == 1:
            self.items = {key: record for key, record in (value.get('items') or {}).items()
                          if isinstance(record, dict) and isinstance(key, str)}
            self.learned = {segment for segment in value.get('learned') or [] if isinstance(segment, str)}

    def save(self, *, force=False):
        if self.path is None:
            return
        with self.lock:
            if not self.dirty or (not force and self.clock() - self.saved_at < SAVE_EVERY):
                return
            value = copy.deepcopy({'version': 1, 'saved_at': self.clock(), 'learned': sorted(self.learned),
                                   'items': self.items})
            self.dirty, self.saved_at = False, self.clock()
        try:
            crawl._atomic_write(self.path, value)
        except OSError as exc:
            logging.getLogger(__name__).warning('Crawl ledger not saved: %s', exc)
            with self.lock:
                self.dirty = True

    # ------------------------------------------------------------------ records

    def _record(self, ident, segment, now, *, background):
        record = self.items.get(ident)
        if record is None:
            record = self.items[ident] = {
                'id': ident, 'segment': segment, 'first_seen': now, 'last_listed': None, 'background': background,
                'first_aired': None, 'last_aired': None, 'air_count': 0, 'airings': [], 'muted': False}
            self.dirty = True
        return record

    def _content(self, record, item):
        changed = False
        for key in CONTENT + META:
            if key in item and record.get(key) != item[key]:
                record[key] = item[key]
                changed = changed or key in CONTENT
        if changed:
            self.dirty = True

    def listed(self, segment, items, *, ready=True, news=True):
        """Notes what a segment lists now. Returns the items that are news: never aired, and
        first seen after the segment's first look, while news counted (its new_now on).

        ready: the segment's feed has answered at least once (until then an empty listing
        says nothing, so the first look waits)."""
        now = self.clock()
        with self.lock:
            first = segment not in self.learned
            if first and not ready:
                return []
            fresh = []
            for item in items:
                record = self._record(item['id'], segment, now, background=first or not news)
                record['last_listed'] = now
                record['segment'] = segment
                self._content(record, item)
                if not record['background'] and record['first_aired'] is None and not record['muted']:
                    fresh.append(item)
            if first:
                self.learned.add(segment)
                self.dirty = True
            return fresh

    def aired(self, items, *, key, context, layer, forced=False, new=False, segment=None):
        """These items started airing (a bulletin's pass, a loop, an important or override layer)."""
        now = self.clock()
        with self.lock:
            for item in items:
                record = self._record(item['id'], segment or item.get('segment') or '', now, background=False)
                self._content(record, item)
                record['first_aired'] = record['first_aired'] or now
                record['last_aired'] = now
                record['air_count'] += 1
                record['airings'] = (record['airings'] + [{
                    'at': now, 'ended': None, 'how': None, 'key': key, 'context': context, 'layer': layer,
                    'forced': forced, 'new': new}])[-AIRINGS:]
            self.dirty = True

    def ended(self, key, how, at=None, ids=None):
        """Airings under this key (or just these items') ended."""
        at = at or self.clock()
        with self.lock:
            for ident, record in self.items.items():
                if ids is not None and ident not in ids:
                    continue
                for airing in record['airings']:
                    if airing['key'] == key and airing['ended'] is None:
                        airing['ended'], airing['how'] = at, how
                        self.dirty = True

    def mute(self, ident, muted, *, segment=''):
        with self.lock:
            record = self._record(ident, segment, self.clock(), background=True)
            record['muted'] = bool(muted)
            self.dirty = True
            return dict(record)

    def muted(self):
        with self.lock:
            return {ident for ident, record in self.items.items() if record.get('muted')}

    def get(self, ident):
        with self.lock:
            record = self.items.get(ident)
            return copy.deepcopy(record) if record else None

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.items)

    def prune(self):
        """Forgets items not listed for a day (muted ones too: a gone alert needs no mute)."""
        now = self.clock()
        with self.lock:
            gone = [ident for ident, record in self.items.items()
                    if now - max(record.get('last_listed') or 0, record.get('last_aired') or 0,
                                 record.get('first_seen') or 0) > KEEP
                    and not any(airing['ended'] is None for airing in record['airings'])]
            for ident in gone:
                del self.items[ident]
            if gone:
                self.dirty = True
