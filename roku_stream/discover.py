"""Discovery: what would make a good schedule, from what there is to air.

``Discovery.ideas()`` reads everything the station could put on and suggests what the
lineup lacks, each idea with the request that adds it (``apply``: method, path, body), so
the Schedule page can add one with a click or open it in the composer first.

- **Sports**: the ready-made sports slots (sports_slots.PRESETS) not on the lineup that
  have a game coming, with the games they would air.
- **Fix-ups**: lineup slots on a fixed channel whose time the listings name. "News 10" on
  YouTube TV's NBC at 6 is *News4 at 6*: rename it and let it follow the listings.
- **Strips**: programmes listed at the same time on several days (the atlas in
  guide_index.py remembers the days the guide no longer shows), scored: first-run episodes,
  the big networks, the evening, and what the station already airs, records and tunes by hand.
- **Soon**: one-off airings in the listings worth a look: live events, premieres, new
  episodes in prime time.
- **Library**: folders of the media library with enough files for a strip, with a free
  half hour to put them in.
- **Habits**: channels put on by hand at the same time on different days.

``draft`` names the ideas that together fill the free time without overlapping the lineup
or each other, best first: a starting week.

Everything here is arithmetic over titles and times: no model, no network but the sports
feeds. It is worked out at most every CACHE seconds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import re
import threading
import time

from . import guide_index, lineup
from .lineup import DAYS
from .scheduler import parse_time, utc_now

CACHE = 300
STRIP_LIMIT = 14
SOON_LIMIT = 10
# The broadcast networks: YouTube TV's own channel of each, and the antenna's stations.
MAJORS = re.compile(r'^YouTube TV (NBC|ABC|CBS|FOX|PBS|The CW)$|\b(WRC|WTTG|WJLA|WUSA|WETA|WDCW|MPT|WHUT)\b')
PRIME = (19 * 60, 23 * 60)
# Live every day, and never an event.
NOT_AN_EVENT = re.compile(r'\bnews\b|\bnoticias\b|\bweather\b|\bgifts?\b|\bshop', re.IGNORECASE)
log = logging.getLogger(__name__)


def _minutes(value):
    hour, minute = lineup.clock(value)
    return hour * 60 + minute


def _clock(minute):
    return f'{minute // 60 % 24:02d}:{minute % 60:02d}'


def _spoken(minute):
    return lineup.spoken_time(_clock(minute))


class Discovery:
    def __init__(self, programming, guide, *, sports_slots=None, library=None, queue=None, clock=utc_now):
        """library(): the media library's items. queue: Up next (its history of takes)."""
        self.programming, self.guide, self.sports_slots = programming, guide, sports_slots
        self.library, self.queue, self.clock = library, queue, clock
        self.lock = threading.Lock()
        self.cached = (None, None)

    # What is already on -------------------------------------------------------
    def _occupied(self, slots):
        """{weekday index: [(start minute, end minute)]} of the lineup, past midnight split."""
        busy = {day: [] for day in range(7)}
        for slot in slots:
            if not slot.get('enabled', True):
                continue
            start = _minutes(slot['start'])
            for day in slot['days']:
                index, end = DAYS.index(day), start + slot['minutes']
                busy[index].append((start, min(end, 1440)))
                if end > 1440:
                    busy[(index + 1) % 7].append((0, end - 1440))
        return busy

    @staticmethod
    def _free(busy, days, start, minutes):
        return all(not any(a < start + minutes and start < b for a, b in busy[DAYS.index(day)]) for day in days)

    @staticmethod
    def _take(busy, days, start, minutes):
        for day in days:
            busy[DAYS.index(day)].append((start, start + minutes))

    def _affinity(self, slots):
        """Titles and channels the station already cares about: the lineup's, recordings'
        titles, and channels taken by hand."""
        titles = {guide_index.normal(slot['title']) for slot in slots}
        titles |= {guide_index.normal(slot['what']['title']) for slot in slots if slot['what']['kind'] == 'program'}
        channels = {(slot['what']['target'].get('source_id'), str(slot['what']['target'].get('channel_id')))
                    for slot in slots if slot['what'].get('target')}
        for folder in self.programming.library_folders():
            if folder['name']:   # A programme recorded more than once.
                titles.add(guide_index.normal(folder['name']))
        return titles, channels

    # Ideas ---------------------------------------------------------------------
    def _sports(self):
        if self.sports_slots is None:
            return []
        from .sports_slots import PRESETS
        taken = {slot.get('preset') for slot in self.programming.sports_slots()}
        ideas = []
        for preset in PRESETS:
            if preset['preset'] in taken:
                continue
            body = {k: v for k, v in preset.items() if k != 'blurb'}
            try:
                games = [g for g in self.sports_slots.preview(body) if g['status'] == 'would']
            except Exception as exc:  # A feed down: no idea, no harm.
                log.info('Discovery: cannot preview %s: %s', preset['title'], exc)
                continue
            if not games:
                continue
            first = games[0]
            ideas.append({'id': 'sports:' + preset['preset'], 'group': 'sports', 'title': preset['title'],
                          'why': preset['blurb'], 'score': 40 + (10 if preset['priority'] == 'high' else 0) - len(ideas),
                          'detail': f"{first['title']} · {', '.join(first['networks'][:2]) or 'channel to choose'}",
                          'when': first['start_time'], 'count': len(games),
                          'games': [{'title': g['title'], 'start_time': g['start_time'], 'networks': g['networks']}
                                    for g in games[:4]],
                          'apply': {'method': 'POST', 'path': 'v1/programming/sports', 'body': body}})
        return ideas

    def _fixups(self, slots, now):
        """Fixed-channel slots whose time the listings name."""
        ideas, zone = [], self.programming.zone
        for slot in slots:
            what = slot['what']
            if what['kind'] != 'channel' or not slot.get('enabled', True) or what['target'].get('source_id') == 'off-air':
                continue
            airing = lineup.next_airing(slot, now, zone, timedelta(days=2))
            if airing is None:
                continue
            _, start, end = airing
            listed = self.guide.on_channel(what['target'], max(start, now) + timedelta(minutes=2))
            if not listed or abs(listed['start'] - start.timestamp()) > 20 * 60:
                continue
            same = guide_index.normal(listed['title']) == guide_index.normal(slot['title'])
            minutes = max(5, round((listed['end'] - listed['start']) / 60))
            body = {'what': {'kind': 'program', 'title': listed['title'], 'target': what['target'], 'follow': True}}
            if not same:
                body['title'] = listed['title'][:48]
            if abs(minutes - slot['minutes']) <= 30 and minutes != slot['minutes'] and len(slot['days']) == 1:
                body['minutes'] = minutes
            ideas.append({'id': 'fix:' + slot['id'], 'group': 'fixups', 'slot': slot['id'],
                          'title': slot['title'] if same else f"{slot['title']} is {listed['title']}",
                          'why': ('It is in the listings: follow it, and its channel and times look after themselves.' if same else
                                  f"{listed['channel']} lists {listed['title']} then. Rename the slot and let it follow the listings."),
                          'detail': f"{lineup.spoken_days(slot['days'])} · {lineup.spoken_time(slot['start'])} · {listed['channel']}",
                          'score': 30 if not same else 24,
                          'apply': {'method': 'POST', 'path': 'v1/programming/slots/' + slot['id'], 'body': body}})
        return ideas

    def _strips(self, slots, busy, affinity, now):
        """Programmes on at the same time on several days."""
        titles, channels = affinity
        zone = self.programming.zone
        scheduled = {guide_index.normal(slot['what']['title']) for slot in slots if slot['what']['kind'] == 'program'}
        scheduled |= {guide_index.normal(slot['title']) for slot in slots}
        upcoming = {}
        for airing in self.guide.airings(now, None):
            key = (airing['target']['source_id'], str(airing['target']['channel_id']), airing['key'])
            upcoming.setdefault(key, airing)
        found = {}
        for entry in self.guide.remembered():
            key = guide_index.normal(entry['title'])
            if not key or key in scheduled or guide_index.JUNK.match(entry['title']):
                continue
            by_time = {}
            for weekday, minute, minutes, count, last in entry['times']:
                group = by_time.setdefault((minute, minutes), {'days': set(), 'dates': 0, 'last': ''})
                group['days'].add(weekday)
                group['dates'] += count
                group['last'] = max(group['last'], last)
            (minute, minutes), best = max(by_time.items(), key=lambda item: (item[1]['dates'], -item[0][0]))
            if best['dates'] < 2 or minutes < 15 or minutes > 240:
                continue
            total = sum(group['dates'] for group in by_time.values())
            # Wall-to-wall reruns (the same title most of the day) are a channel, not a strip.
            if len(by_time) > 6:
                continue
            days = sorted(best['days'])
            if all(day < 5 for day in days) and len(days) >= 2:
                on = list(DAYS[:5])   # Seen on weekdays only: a weekday strip.
            elif len(days) >= 4:
                on = list(DAYS)
            else:
                on = [DAYS[day] for day in days]
            score = min(best['dates'], 7) * 2.0
            new_share = min(entry.get('new', 0) / max(total, 1), 1)
            score += 6 * new_share
            major = bool(MAJORS.search(entry['channel']))
            score += 5 if major else 0
            score += 4 if 17 * 60 <= minute < 24 * 60 else 2 if 6 * 60 <= minute < 10 * 60 else -6 if minute < 5 * 60 else 0
            loved = key in titles
            score += 12 if loved else 0
            score += 3 if (entry['source_id'], entry['channel_id']) in channels else 0
            score -= 4 if minutes > 120 else 0
            score += 1 if entry['source_id'] == 'tv-thing-digital' else 0
            target = {'source_id': entry['source_id'], 'channel_id': entry['channel_id']}
            nxt = upcoming.get((entry['source_id'], entry['channel_id'], key))
            reasons = [f"{lineup.spoken_days(on)} at {_spoken(minute)} on {entry['channel']}"]
            if new_share >= .5:
                reasons.append('new episodes')
            if loved:
                reasons.append('you already air or record it')
            idea = {'id': f"strip:{entry['source_id']}:{entry['channel_id']}:{key}:{minute}", 'group': 'strips',
                    'title': entry['title'], 'why': ' · '.join(reasons), 'score': round(score, 1),
                    'detail': f"{minutes} min · seen on {best['dates']} day{'s' if best['dates'] != 1 else ''}",
                    'when': datetime.fromtimestamp(nxt['start'], timezone.utc).isoformat() if nxt else None,
                    'free': self._free(busy, on, minute, minutes), 'days': on, 'start': _clock(minute), 'minutes': minutes,
                    'part': minute // 360,
                    'apply': {'method': 'POST', 'path': 'v1/programming/slots', 'body': {
                        'title': entry['title'][:48], 'days': on, 'start': _clock(minute), 'minutes': minutes,
                        'what': {'kind': 'program', 'title': entry['title'][:80], 'target': target, 'follow': True}}}}
            # The same programme on the antenna and YouTube TV is one idea: the better scored.
            same = (key, minute)
            if same not in found or found[same]['score'] < idea['score']:
                found[same] = idea
        ranked = sorted(found.values(), key=lambda idea: -idea['score'])
        chosen, per_channel, per_part = [], {}, {}
        for idea in ranked:
            channel = idea['apply']['body']['what']['target']['channel_id']
            if per_channel.get(channel, 0) >= 3 or per_part.get(idea['part'], 0) >= 5:
                continue
            per_channel[channel] = per_channel.get(channel, 0) + 1
            per_part[idea['part']] = per_part.get(idea['part'], 0) + 1
            chosen.append(idea)
            if len(chosen) >= STRIP_LIMIT:
                break
        return chosen

    def _soon(self, slots, affinity, now):
        """One-off airings worth a look: live events, premieres, new prime-time episodes."""
        titles, _ = affinity
        zone = self.programming.zone
        strips = {guide_index.normal(slot['what']['title']) for slot in slots if slot['what']['kind'] == 'program'}
        strips |= {guide_index.normal(slot['title']) for slot in slots}
        shows = self.programming.shows()
        taken = [(parse_time(s['start']), parse_time(s['end'])) for s in shows]
        counts = {}
        daily = {guide_index.normal(entry['title']) for entry in self.guide.remembered()
                 if any(count >= 2 or sum(1 for other in entry['times'] if other[1] == minute) >= 2
                        for _, minute, _, count, _ in entry['times'])}
        airings = self.guide.airings(now + timedelta(minutes=5), now + timedelta(hours=40))
        for airing in airings:
            counts[airing['key']] = counts.get(airing['key'], 0) + 1
        best = {}
        for airing in airings:
            if airing['key'] in strips or airing['start'] < now.timestamp() or NOT_AN_EVENT.search(airing['title']):
                continue
            if airing['key'] in daily and airing['key'] not in titles and not (airing['new'] and airing.get('episode') == 1):
                continue
            local = datetime.fromtimestamp(airing['start'], zone)
            minute = local.hour * 60 + local.minute
            length = (airing['end'] - airing['start']) / 60
            if length < 20 or length > 300:
                continue
            major = bool(MAJORS.search(airing['channel']))
            prime = PRIME[0] <= minute < PRIME[1]
            premiere = airing['new'] and airing.get('episode') == 1
            score, tags = 0, []
            if airing['live'] and major:
                score += 9
                tags.append('live')
            if premiere:
                score += 8
                tags.append('season premiere' if (airing.get('season') or 1) > 1 else 'series premiere')
            if airing['new'] and prime and major:
                score += 6
                tags.append('new tonight' if local.date() == now.astimezone(zone).date() else 'new')
            if airing['key'] in titles:
                score += 8
                tags.append('you record it')
            if counts[airing['key']] > 6:   # On all day: not an event.
                score -= 6
            if score < 6:
                continue
            start, end = (datetime.fromtimestamp(airing[k], timezone.utc) for k in ('start', 'end'))
            if any(a < end and start < b for a, b in taken):
                score -= 3
            if airing['key'] not in best or best[airing['key']]['score'] < score:
                best[airing['key']] = {
                    'id': f"soon:{airing['target']['channel_id']}:{int(airing['start'])}", 'group': 'soon',
                    'title': airing['title'], 'score': score + (1 if airing['target']['source_id'] == 'tv-thing-digital' else 0),
                    'why': ' · '.join(dict.fromkeys(tags)), 'when': start.isoformat(),
                    'detail': ' · '.join(filter(None, (airing['channel'], airing.get('episode_title'),
                                                       f'{round(length)} min'))),
                    'apply': {'method': 'POST', 'path': 'v1/programming/shows', 'body': {
                        'mode': 'program', 'title': airing['title'][:72], 'target': dict(airing['target']),
                        'start': start.isoformat(), 'end': end.isoformat(), 'priority': 'normal'}}}
        return sorted(best.values(), key=lambda idea: (-idea['score'], idea['when']))[:SOON_LIMIT]

    def _library(self, slots, busy):
        """Folders with enough files for a strip, and a free place to put them."""
        used = {(slot['what']['root'], slot['what'].get('path'), slot['what'].get('name'))
                for slot in slots if slot['what']['kind'] == 'library'}
        ideas = []
        folders = self.programming.library_folders()
        # A root of long films (cab rides) is one shelf: all of it, shuffled, before its parts.
        # A root of shows is not: nobody wants an episode of anything at random.
        shelves = {folder['root'] for folder in folders if folder['whole'] and folder['minutes'] > 50}
        for folder in folders:
            key = (folder['root'], folder['path'], folder['name'])
            if folder['files'] < 4 or key in used or (folder['whole'] and folder['root'] not in shelves):
                continue
            minutes = max(30, -(-folder['minutes'] // 30) * 30)   # The half hours an average file needs.
            long_form = folder['minutes'] > 50
            # A free place: evenings for episodes, the afternoon for long films of trains.
            starts = (list(range(13 * 60, 17 * 60, 30)) if long_form
                      else list(range(20 * 60, 23 * 60, 30)) + list(range(17 * 60, 20 * 60, 30)))
            on = list(DAYS)
            start = next((s for s in starts if self._free(busy, on, s, minutes)), None)
            if start is None:
                on = list(DAYS[5:])
                start = next((s for s in starts if self._free(busy, on, s, minutes)), None)
            what = {'kind': 'library', 'root': folder['root'], 'order': folder['order']}
            if folder['path']:
                what['path'] = folder['path']
            if folder['name']:
                what['name'] = folder['name']
            if folder['breaks']:
                what['ad_breaks'] = 120   # Two minutes a break: a 21-minute show with three fills its half hour.
            at = _clock(start if start is not None else starts[0])
            ideas.append({'id': f"library:{folder['root']}:{folder['path'] or folder['name'] or ''}", 'group': 'library',
                          'title': folder['label'],
                          'why': {'next': 'The next episode each time, in order.', 'newest': 'The newest recording each time.',
                                  'shuffle': 'One at random each time.'}[folder['order']],
                          'detail': ' · '.join(filter(None, (None if folder['whole'] else folder['root_name'],
                                                             f"{folder['files']} files", f"about {folder['minutes']} min each"))),
                          'score': 14 + min(folder['files'], 60) / 10 + (4 if folder['breaks'] else 0)
                                   - (8 if folder['root'] in shelves and not folder['whole'] else 0),
                          'free': start is not None, 'days': on, 'start': at, 'minutes': minutes,
                          'apply': {'method': 'POST', 'path': 'v1/programming/slots', 'body': {
                              'title': folder['label'][:48], 'days': on, 'start': at, 'minutes': minutes, 'what': what}}})
        return sorted(ideas, key=lambda idea: -idea['score'])[:8]

    def _habits(self, slots, busy):
        """Channels put on by hand at about the same time on different days."""
        if self.queue is None:
            return []
        zone = self.programming.zone
        takes = {}
        try:
            items = self.queue.list()
        except Exception:
            return []
        for item in items:
            target = item.target or {}
            if (getattr(item, 'origin', None) is not None or item.status != 'succeeded' or not item.completed_at
                    or target.get('source_id') not in ('youtube-tv', 'tv-thing-digital')):
                continue
            local = parse_time(item.completed_at).astimezone(zone)
            half = (local.hour * 60 + local.minute + 10) // 30 * 30   # The half hour it was about.
            takes.setdefault((target['source_id'], str(target['channel_id']), half), set()).add(local.date())
        ideas = []
        for (source, channel, minute), dates in takes.items():
            if len(dates) < 2:
                continue
            on = sorted({DAYS[day.weekday()] for day in dates}, key=DAYS.index)
            target = {'source_id': source, 'channel_id': channel}
            label = self.guide.label(target) or channel
            # What the listings have there at that time today or tomorrow, to name the slot.
            today = datetime.combine(datetime.now(zone).date(), datetime.min.time(), zone)
            listed = next(filter(None, (self.guide.on_channel(target, (today + timedelta(days=ahead, minutes=minute + 5))
                                                              .astimezone(timezone.utc)) for ahead in (0, 1))), None)
            title = listed['title'] if listed else label
            what = ({'kind': 'program', 'title': listed['title'], 'target': target, 'follow': True} if listed
                    else {'kind': 'channel', 'target': target})
            ideas.append({'id': f'habit:{source}:{channel}:{minute}', 'group': 'habits', 'title': title,
                          'why': f"You put {label} on by hand around {_spoken(minute)} on {len(dates)} days.",
                          'detail': f"{lineup.spoken_days(on)} · 30 min", 'score': 12 + 3 * len(dates),
                          'free': self._free(busy, on, minute, 30), 'days': on, 'start': _clock(minute), 'minutes': 30,
                          'apply': {'method': 'POST', 'path': 'v1/programming/slots', 'body': {
                              'title': title[:48], 'days': on, 'start': _clock(minute), 'minutes': 30, 'what': what}}})
        return sorted(ideas, key=lambda idea: -idea['score'])[:6]

    def ideas(self, now=None, force=False):
        now = now or self.clock()
        with self.lock:
            at, cached = self.cached
            if not force and cached is not None and time.monotonic() - at < CACHE:
                return cached
            started = time.monotonic()
            slots = self.programming.slots()
            busy = self._occupied(slots)
            affinity = self._affinity(slots)
            groups = []

            def group(key, title, blurb, build):
                try:
                    ideas = build()
                except Exception:  # One source of ideas failing leaves the others.
                    log.exception('Discovery: %s failed', key)
                    ideas = []
                if ideas:
                    groups.append({'id': key, 'title': title, 'blurb': blurb, 'ideas': ideas})
                return ideas

            group('sports', 'Sports slots', 'Standing appointments: every game the rule finds goes on by itself.', self._sports)
            group('fixups', 'Let these follow the listings',
                  'Slots tied to one channel whose programme the listings know.', lambda: self._fixups(slots, now))
            strips = group('strips', 'On at the same time every day',
                           'From the listings, and what the atlas has seen so far.',
                           lambda: self._strips(slots, busy, affinity, now))
            group('soon', 'Coming up once', 'Live events, premieres and new episodes in the next day or two.',
                  lambda: self._soon(slots, affinity, now))
            shelves = group('library', 'From the library', 'Folders with enough to fill a slot every day.',
                            lambda: self._library(slots, busy))
            habits = group('habits', 'You keep putting these on', 'Taken by hand at the same time on different days.',
                           lambda: self._habits(slots, busy))
            # A starting week: the best ideas that fit beside the lineup and each other.
            draft, taken = [], {day: list(spans) for day, spans in busy.items()}
            for idea in sorted([*strips, *shelves, *habits], key=lambda i: -i['score']):
                start = _minutes(idea['start'])
                days = [day for day in idea['days'] if self._free(taken, [day], start, idea['minutes'])]
                if idea['score'] < 12 or len(days) * 2 < len(idea['days']) or not days:
                    continue
                self._take(taken, days, start, idea['minutes'])
                draft.append({'id': idea['id'], 'days': days})
                if len(draft) >= 10:
                    break
            result = {'generated_at': now.isoformat(), 'seconds': round(time.monotonic() - started, 2),
                      'guide': self.guide.status(), 'groups': groups, 'draft': draft,
                      'count': sum(len(g['ideas']) for g in groups)}
            self.cached = (time.monotonic(), result)
            return result

    def forget(self):
        """The lineup changed: the next ideas are worked out afresh."""
        with self.lock:
            self.cached = (None, None)
