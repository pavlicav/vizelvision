"""The listings, indexed by programme: where and when a programme is on.

TV Thing's guide lists the antenna's channels and YouTube TV's a day or two ahead. A slot
that airs a programme by name (lineup.py) asks ``find`` for its airing, so the channel
follows the programme. The schedule's discovery (discover.py) asks what is on at all.

The guide reaches only a day or two, and a weekly schedule needs to know what is on every
Thursday. So each read is also noted in the **atlas** (``guide-atlas.json`` beside
programming.json): per channel and programme, the weekdays and times it was listed, how
many different dates, and when last. After a week it knows the week. Nothing but titles and
times is kept, and a programme not listed for four weeks is forgotten.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import re
import tempfile
import threading
import time

# The guide is indexed again after this long, or as soon as TV Thing has a newer one.
REFRESH_SECONDS = 300
# An airing counts as a slot's when it starts this close to the slot's start.
NEAR = timedelta(minutes=45)
ATLAS_KEPT_DAYS = 28
ATLAS_LIMIT = 9000
# Never a programme worth a slot.
JUNK = re.compile(r'^(paid program(ming)?|programa pagado|infomercial|off air|sign off|to be announced|tba|'
                  r'no (program )?information.*|local programming|shop.*|qvc.*|hsn.*)$', re.IGNORECASE)
# The antenna's channels tune in seconds and leave the Roku free; YouTube TV needs it.
SOURCE_ORDER = {'tv-thing-digital': 0, 'youtube-tv': 1}
log = logging.getLogger(__name__)


def normal(title):
    """'Jeopardy!' and 'JEOPARDY' are one programme: letters and digits, lower case."""
    words = re.sub(r"[^\w\s]", '', str(title or '').casefold().replace('&', ' and '))
    words = re.sub(r'\s+', ' ', words).strip()
    return words[4:] if words.startswith('the ') else words


def _target(row):
    """The source target of a guide row, and its label; None for rows nothing can tune."""
    if row.get('kind') == 'digital' and isinstance(row.get('id'), str) and row['id']:
        name = ' '.join(filter(None, (str(row.get('number') or ''), str(row.get('name') or ''))))
        return {'source_id': 'tv-thing-digital', 'channel_id': row['id']}, name or row['id']
    if row.get('source_id') == 'youtube-tv' and isinstance(row.get('channel_id'), str) and row['channel_id']:
        return {'source_id': 'youtube-tv', 'channel_id': row['channel_id']}, 'YouTube TV ' + row['channel_id']
    return None, None


class GuideIndex:
    def __init__(self, fetch, atlas_file=None, *, zone=timezone.utc, clock=time.monotonic, wall=time.time):
        """fetch() returns TV Thing's guide ({'channels': {key: row}}), or raises when there
        is none. zone: the station's, for the atlas's weekdays and times of day."""
        self.fetch, self.zone, self.clock, self.wall = fetch, zone, clock, wall
        self.atlas_path = Path(atlas_file) if atlas_file else None
        self.lock = threading.Lock()
        self.read_at = None
        self.stamp = None
        self.error = None
        self.events = []      # Every airing, by start.
        self.by_title = {}    # normal title -> its airings.
        self.channels = {}    # (source, channel) -> label.
        self.atlas = self._load_atlas()

    # The index ---------------------------------------------------------------
    def _refresh_locked(self):
        now = self.clock()
        if self.read_at is not None and now - self.read_at < REFRESH_SECONDS:
            return
        self.read_at = now
        try:
            data = self.fetch()
        except Exception as exc:  # No guide: the last index stays, and slots use their usual channel.
            self.error = str(exc)
            return
        rows = data.get('channels') if isinstance(data, dict) else None
        if not isinstance(rows, dict):
            self.error = 'The guide has no channels'
            return
        self.error = None
        stamp = (data.get('generated_at'), (data.get('youtube_tv') or {}).get('generated_at'), len(rows))
        if stamp == self.stamp and self.events:
            return
        events, by_title, channels = [], {}, {}
        for row in rows.values():
            if not isinstance(row, dict):
                continue
            target, label = _target(row)
            if target is None:
                continue
            channels[(target['source_id'], target['channel_id'])] = label
            for event in row.get('events') or ():
                try:
                    start = float(event['start'])
                    end = start + float(event['duration'])
                    title = str(event['title']).strip()
                except (KeyError, TypeError, ValueError):
                    continue
                if not title or end <= start or JUNK.match(title):
                    continue
                airing = {'title': title, 'key': normal(title), 'start': start, 'end': end, 'target': target,
                          'channel': label, 'new': event.get('new') is True, 'live': event.get('live') is True,
                          'episode_title': event.get('episode_title') or None,
                          'season': event.get('season'), 'episode': event.get('episode'),
                          'rating': event.get('rating') or None,
                          'description': event.get('description') or None}
                events.append(airing)
                by_title.setdefault(airing['key'], []).append(airing)
        events.sort(key=lambda e: e['start'])
        self.events, self.by_title, self.channels, self.stamp = events, by_title, channels, stamp
        self._note_locked(events)

    def available(self):
        with self.lock:
            self._refresh_locked()
            return bool(self.events)

    def status(self):
        with self.lock:
            self._refresh_locked()
            reach = max((e['end'] for e in self.events), default=None)
            return {'available': bool(self.events), 'error': self.error, 'airings': len(self.events),
                    'programmes': len(self.by_title), 'channels': len(self.channels),
                    'reaches': datetime.fromtimestamp(reach, timezone.utc).isoformat() if reach else None,
                    'atlas_programmes': len(self.atlas['seen']), 'atlas_since': self.atlas.get('since')}

    def reach(self):
        """How far the listings go (a UTC time), or None without any."""
        with self.lock:
            self._refresh_locked()
            reach = max((e['end'] for e in self.events), default=None)
        return datetime.fromtimestamp(reach, timezone.utc) if reach else None

    def airings(self, start=None, end=None):
        """Every listed airing overlapping [start, end) (UTC datetimes), by start."""
        with self.lock:
            self._refresh_locked()
            events = self.events
        low = start.timestamp() if start else float('-inf')
        high = end.timestamp() if end else float('inf')
        return [e for e in events if e['end'] > low and e['start'] < high]

    def find(self, title, start, end, *, match='exact', usual=None):
        """The airings of a programme that a slot from start to end would be, best first:
        on the usual channel, then the antenna before YouTube TV, then nearest the slot's
        start. Only airings starting within NEAR of it, or covering half of it."""
        key = normal(title)
        if not key:
            return []
        with self.lock:
            self._refresh_locked()
            if match == 'contains':
                found = [e for name, group in self.by_title.items() if key in name for e in group]
            else:
                found = list(self.by_title.get(key, ()))
        begin, finish = start.timestamp(), end.timestamp()
        length = max(finish - begin, 1)
        near = NEAR.total_seconds()
        wanted = (usual or {}).get('source_id'), str((usual or {}).get('channel_id'))
        result = []
        for airing in found:
            overlap = min(airing['end'], finish) - max(airing['start'], begin)
            close = abs(airing['start'] - begin) <= near
            if not (close and airing['end'] > begin) and overlap < length / 2:
                continue
            same = (airing['target']['source_id'], str(airing['target']['channel_id'])) == wanted
            result.append(((not same, not close, SOURCE_ORDER.get(airing['target']['source_id'], 9),
                            abs(airing['start'] - begin), not airing['new']), airing))
        return [airing for _, airing in sorted(result, key=lambda item: item[0])]

    def on_channel(self, target, at):
        """What a channel has listed at a moment (a UTC datetime), or None."""
        moment = at.timestamp()
        wanted = target.get('source_id'), str(target.get('channel_id'))
        with self.lock:
            self._refresh_locked()
            events = self.events
        return next((e for e in events if e['start'] <= moment < e['end']
                     and (e['target']['source_id'], str(e['target']['channel_id'])) == wanted), None)

    def label(self, target):
        with self.lock:
            return self.channels.get((target.get('source_id'), target.get('channel_id')))

    def search(self, query, limit=30):
        """Programmes whose title has every word of query: listed ones with their next
        airing, then ones only the atlas remembers. Most-aired first."""
        words = normal(query).split()
        if not words:
            return []
        now = self.wall()
        with self.lock:
            self._refresh_locked()
            listed = {name: group for name, group in self.by_title.items() if all(w in name for w in words)}
            remembered = {key: entry for key, entry in self.atlas['seen'].items()
                          if all(w in normal(entry['t']) for w in words)}
        found = {}
        for name, group in listed.items():
            upcoming = [e for e in group if e['end'] > now]
            if not upcoming:
                continue
            first = min(upcoming, key=lambda e: e['start'])
            found[name] = {'title': first['title'], 'airings': len(upcoming), 'next': public(first),
                           'channels': sorted({e['channel'] for e in upcoming})[:6],
                           'new': any(e['new'] for e in upcoming)}
        for key, entry in remembered.items():
            name = normal(entry['t'])
            if name in found:
                continue
            found[name] = {'title': entry['t'], 'airings': 0, 'next': None, 'channels': [entry['n']],
                           'new': False, 'remembered': True}
        ranked = sorted(found.values(), key=lambda p: (-(p['airings'] > 0), normal(p['title']) != ' '.join(words),
                                                       -p['airings'], p['title']))
        return ranked[:limit]

    # The atlas ---------------------------------------------------------------
    def _load_atlas(self):
        empty = {'version': 1, 'since': None, 'seen': {}}
        if self.atlas_path is None:
            return empty
        try:
            raw = json.loads(self.atlas_path.read_text())
        except (OSError, ValueError):
            return empty
        if not isinstance(raw, dict) or raw.get('version') != 1 or not isinstance(raw.get('seen'), dict):
            return empty
        return raw

    def _note_locked(self, events):
        """Note each airing's weekday and time once per date, and forget the long unseen."""
        seen, changed = self.atlas['seen'], False
        for airing in events:
            local = datetime.fromtimestamp(airing['start'], self.zone)
            day = local.date().isoformat()
            key = '|'.join((airing['target']['source_id'], str(airing['target']['channel_id']), airing['key']))
            entry = seen.get(key)
            if entry is None:
                entry = seen[key] = {'t': airing['title'], 'n': airing['channel'], 'o': {}, 'new': 0}
            when = f"{local.weekday()}:{local.hour * 60 + local.minute}:{round((airing['end'] - airing['start']) / 60)}"
            count, last = entry['o'].get(when, (0, ''))
            if day > last:
                entry['o'][when] = [count + 1, day]
                entry['new'] = entry.get('new', 0) + (1 if airing['new'] else 0)
                entry['t'], entry['n'] = airing['title'], airing['channel']
                changed = True
        if not changed:
            return
        today = datetime.fromtimestamp(self.wall(), self.zone).date()
        cutoff = (today - timedelta(days=ATLAS_KEPT_DAYS)).isoformat()
        for key in [k for k, entry in seen.items() if max((o[1] for o in entry['o'].values()), default='') < cutoff]:
            del seen[key]
        if len(seen) > ATLAS_LIMIT:  # The least-seen go first.
            for key in sorted(seen, key=lambda k: sum(o[0] for o in seen[k]['o'].values()))[:len(seen) - ATLAS_LIMIT]:
                del seen[key]
        self.atlas['since'] = self.atlas.get('since') or today.isoformat()
        self._save_atlas_locked()

    def _save_atlas_locked(self):
        if self.atlas_path is None:
            return
        try:
            self.atlas_path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.guide-atlas-', dir=self.atlas_path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(self.atlas, stream, separators=(',', ':'))
                os.replace(name, self.atlas_path)
            finally:
                Path(name).unlink(missing_ok=True)
        except OSError as exc:  # The atlas is a convenience: the index works without it.
            log.warning('Cannot save the guide atlas: %s', exc)

    def remembered(self):
        """The atlas: [{source_id, channel_id, title, channel, new, times: [(weekday,
        minute of day, minutes, dates seen, last date)]}]."""
        with self.lock:
            self._refresh_locked()
            seen = json.loads(json.dumps(self.atlas['seen']))
        result = []
        for key, entry in seen.items():
            source, channel, _ = key.split('|', 2)
            times = []
            for when, (count, last) in entry['o'].items():
                weekday, minute, minutes = (int(part) for part in when.split(':'))
                times.append((weekday, minute, minutes, count, last))
            result.append({'source_id': source, 'channel_id': channel, 'title': entry['t'], 'channel': entry['n'],
                           'new': entry.get('new', 0), 'times': times})
        return result


def public(airing):
    """An airing for the pages: ISO times, no description."""
    return {'title': airing['title'], 'target': dict(airing['target']), 'channel': airing['channel'],
            'start': datetime.fromtimestamp(airing['start'], timezone.utc).isoformat(),
            'end': datetime.fromtimestamp(airing['end'], timezone.utc).isoformat(),
            'new': airing['new'], 'live': airing['live'], 'episode_title': airing['episode_title'],
            'season': airing['season'], 'episode': airing['episode']}
