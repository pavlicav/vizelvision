"""The crawl's rotation, in the web app: which segment runs as a bulletin, and when.

Every two seconds the desk reads the crawl settings and master's status, works out
the context (a program, a live game, the off-air card, the station ID) and does what
that context's rule says:

- always: one bulletin that loops every segment's items, renewed while it applies;
- popups: one segment at a time, one pass, then the bar slides away. A segment is due
  `every` minutes (with changed_only, only if its items changed); at most `per_hour`
  pop-ups an hour, at least `gap_minutes` apart, the most overdue first;
- quiet: no bulletins.

Feed options (crawl.FeedSettings, crawl-feeds.json) add per segment: the contexts it may
air in at all; repeat (off: no timer); and new_now, which pops up items that are news at
once (one pass, only those items), ahead of the timer, the hourly limit and the gap,
though never over a running pop-up or important news.

Every item has an id (crawl_feeds.py; the worker's alerts by their EAS or NWS id), and the
ledger (crawl_ledger.py) keeps when each was first seen and each time it aired, including
in the worker's important and override layers. That is what makes an item news, and what
the Crawl page's register shows: per item, a first airing or a repeat, and when it airs next
(plan() plays the rules forward over the coming hour and a half, following the schedule's
games and off-air card).

The worker runs the important and override layers itself and refuses bulletins while
they run. A bulletin carries a lease, so a stopped desk never leaves one on air.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import logging
import statistics
import threading
import time
import uuid

from . import crawl
from .crawl_ledger import CrawlLedger
from .errors import ConfigError

LOOP_LEASE, LOOP_RENEW, BULLETIN_LEASE = 30, 10, 600
HISTORY = 40
HORIZON = 3 * 3600  # how far plan() looks ahead: past a game, usually
PLAN_SLOTS = 40
# What kind of thing each segment carries: alerts lead the register.
ALERT_SEGMENTS = ('alerts', 'transit', 'dc_alerts', 'manual')
SOURCE_NAMES = {'eas': 'EAS', 'nws': 'NWS', 'rail': 'Metrorail', 'bus': 'Metrobus', 'alertdc': 'AlertDC',
                'manual': 'Manual', 'weather': 'Weather', 'score': 'Scores', 'coming': 'Coming up',
                'cairo': 'Cairo Radio', 'msg': 'Station message'}
STATUS_ORDER = ('on_air', 'looping', 'next', 'held', 'muted', 'duplicate')
SUMMARY_META = ('severity', 'issued', 'expires', 'event', 'areas', 'by')
AFTER = {'game': ', after the game', 'off_air': ', once a program is on', 'ident': ', after the station ID'}


def _fingerprint(items):
    return hashlib.sha1('|'.join(item['tag'] + item['text'] for item in items).encode()).hexdigest()[:12]


def _item_key(item):
    return hashlib.sha1((item['tag'] + '|' + item['text']).encode()).hexdigest()[:12]


def _air(item):
    """An item as master takes it: the worker refuses any other key."""
    return {key: item.get(key) or '' for key in ('tag', 'heading', 'text')}


def _summary_id(summary):
    return f"{summary['source']}:{summary['id']}"


def _epoch(value):
    try:
        moment = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).timestamp()


class CrawlDesk:
    TICK = 2

    def __init__(self, settings, master, *, feeds=None, production=None, projector=None, feed_options=None,
                 ledger=None, clock=time.time):
        self.settings, self.master = settings, master
        self.feed_options = feed_options or (lambda: crawl.FeedSettings.validate({}))
        self.feeds = feeds or {}
        self.production, self.projector = production, projector
        self.clock = clock
        self.ledger = ledger if ledger is not None else CrawlLedger(clock=clock)
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.thread = None
        self.last_aired, self.fingerprints = {}, {}
        self.cycle = 0
        self.history = []
        self.running = None
        self.last_end = 0.
        self.forced = None
        self.view = {'context': None, 'mode': None, 'error': None}
        self.game_checked, self.game_on = 0., False
        self.loop_ids = set()                                # what the running loop carries
        self.layer_ids = {'important': set(), 'override': set()}  # what the worker's layers carry
        self.snapshot = None                                 # the last tick's view, for plan() and register()
        self.spans_cache = (0., None, None)
        self.pruned_at = 0.

    # ------------------------------------------------------------------ context

    def _game(self, now):
        """Whether the schedule projection says a game holds master now (cached 15 s)."""
        if self.projector is None:
            return False
        if now - self.game_checked > 15:
            self.game_checked = now
            try:
                moment = datetime.fromtimestamp(now, timezone.utc)
                segments = self.projector.describe(moment, moment + timedelta(hours=1)).get('segments') or []
                self.game_on = bool(segments) and segments[0].get('kind') == 'game'
            except Exception as exc:
                logging.getLogger(__name__).debug('Crawl desk cannot read the schedule: %s', exc)
                self.game_on = False
        return self.game_on

    def context(self, state, now):
        if (state.get('ident') or {}).get('on_air'):
            return 'ident'
        if not state.get('on_air'):
            return 'off_air'
        return 'game' if self._game(now) else 'program'

    def _radio(self):
        try:
            return bool(self.production and self.production.read()['audio'] == 'radio')
        except Exception:
            return False

    # ------------------------------------------------------------------ items

    @staticmethod
    def alert_summaries(crawl_state):
        """The worker's alert summaries that run in the rotation, and those in the important
        layer. alert_layers() builds rotation_alerts (and the important items) in the same
        order as its summaries, so the n-th rotation alert is the n-th summary that is neither
        dismissed, important nor a duplicate: that is how its items get their EAS or NWS id."""
        summaries = crawl_state.get('alerts') or []
        live = [s for s in summaries if not s.get('dismissed') and not s.get('duplicate')]
        return [s for s in live if not s.get('important')], [s for s in live if s.get('important')]

    @staticmethod
    def _meta(summary):
        return {'source': summary['source'], **{key: summary.get(key) for key in SUMMARY_META}}

    def _named(self, segment, items):
        named = []
        for item in items:
            item = dict(item)
            item.setdefault('id', f'{segment}:{_item_key(item)}')
            item['segment'] = segment
            named.append(item)
        return named

    def listing(self, segment, settings, crawl_state):
        """Everything a segment has now, by id, wherever and whenever it may air (muted items too)."""
        if segment == 'alerts':
            rotation, _ = self.alert_summaries(crawl_state)
            items = []
            for index, item in enumerate(crawl_state.get('rotation_alerts') or []):
                item = dict(item)
                if 'id' not in item and index < len(rotation):
                    item.update(id=_summary_id(rotation[index]), **self._meta(rotation[index]))
                items.append(item)
        elif segment == 'messages':
            now = datetime.fromtimestamp(self.clock(), timezone.utc)
            items = [{'tag': m['tag'], 'heading': '', 'text': m['text'], 'id': 'msg:' + m['id']}
                     for m in settings['messages'] if crawl.message_active(m, now)]
        else:
            feed = self.feeds.get(segment)
            items = feed.items() if feed else []
        return self._named(segment, items)

    def items(self, segment, settings, crawl_state, context, *, rotate=False):
        """What a segment would say now ([] when it has nothing or does not apply); muted items are left out."""
        if segment == 'cairo' and (context != 'off_air' or not self._radio()):
            return []  # Only while viewers hear Cairo Radio under the off-air card.
        muted = self.ledger.muted()
        items = [item for item in self.listing(segment, settings, crawl_state) if item['id'] not in muted]
        if segment == 'messages' and items and settings['cycle_messages'] and rotate:
            items = [items[self.cycle % len(items)]]
        return items

    def layer_items(self, settings, crawl_state):
        """What the worker's important or override layer carries now, by id."""
        kind, now = crawl_state.get('kind'), datetime.fromtimestamp(self.clock(), timezone.utc)
        if kind == 'override':
            layer = settings['override']
            return [{'id': 'manual:override', 'segment': 'manual', 'source': 'manual', 'tag': '',
                     'heading': '', 'text': layer['text'], 'expires': layer['until']}]
        if kind != 'important':
            return []
        items, named = list(crawl_state.get('items') or []), []
        manual = settings['important']
        if crawl.layer_active(manual, now) and items and items[0].get('text') == manual['text']:
            named.append({**items.pop(0), 'id': 'manual:important', 'segment': 'manual', 'source': 'manual',
                          'expires': manual['until']})
        for index, summary in enumerate(self.alert_summaries(crawl_state)[1]):
            item = items[index] if index < len(items) else {'tag': '', 'heading': str(summary.get('event') or '').upper(),
                                                             'text': ''}
            named.append({**item, 'id': _summary_id(summary), 'segment': 'alerts', **self._meta(summary)})
        return named

    def _content(self, segment, items, *, loop=False):
        name, label, _ = crawl.SEGMENTS[segment] if segment in crawl.SEGMENTS else ('', 'VIZELVISION', 0)
        return {'key': (f'loop-{segment}' if loop else f'{segment}-{uuid.uuid4().hex[:10]}'),
                'label': label, 'style': 'watch' if segment == 'alerts' else 'station',
                'passes': 0 if loop else 1, 'lease': LOOP_LEASE if loop else BULLETIN_LEASE,
                'items': [_air(item) for item in items[:40]]}

    def allowed(self, segment, settings, options, context):
        return settings['segments'][segment]['enabled'] and context in options['segments'][segment]['contexts']

    def _loop_items(self, settings, options, crawl_state, context):
        items = []
        for segment, (_, label, _) in crawl.SEGMENTS.items():
            if self.allowed(segment, settings, options, context):
                listed = self.items(segment, settings, crawl_state, context)
                items += [{**item, 'tag': item['tag'] or label} for item in listed]
        return items

    def _ready(self, segment):
        feed = self.feeds.get(segment)
        return feed is None or feed.status().get('fetched_at') is not None

    # ------------------------------------------------------------------ sending

    def _send(self, segment, items, context, *, forced=False, new=False, loop=False, key=None):
        items = items[:40]
        content = self._content(segment, items, loop=loop)
        if key:
            content['key'] = key
        result = self.master.request('crawl', {'bulletin': content})
        if not result.get('accepted'):
            return False
        now = self.clock()
        fingerprint = _fingerprint(content['items'])
        if self.running and self.running['key'] != content['key']:
            self._ended(self.running['key'], 'replaced', now)
        if not loop or not self.running or self.running['key'] != content['key']:
            self.history = (self.history + [{
                'key': content['key'], 'segment': segment, 'label': content['label'], 'context': context,
                'started': now, 'ended': None, 'how': None, 'forced': forced, 'loop': loop, 'new': new,
                'ids': [item['id'] for item in items], 'text': crawl.plain(content)[:240]}])[-HISTORY:]
        ids = {item['id'] for item in items}
        if loop:
            # A loop runs for as long as it applies: an item airs once while it stays in it.
            added = [item for item in items if item['id'] not in self.loop_ids]
            if added:
                self.ledger.aired(added, key=content['key'], context=context, layer='loop')
            if self.loop_ids - ids:
                self.ledger.ended(content['key'], 'dropped', now, ids=self.loop_ids - ids)
            self.loop_ids = ids
        else:
            self.ledger.aired(items, key=content['key'], context=context, layer='rotation', forced=forced, new=new,
                              segment=segment)
        self.running = {'key': content['key'], 'segment': segment, 'loop': loop, 'renewed': now,
                        'fingerprint': fingerprint, 'started': now, 'ids': sorted(ids)}
        if not loop:
            if not new:  # A new item's pop-up leaves the segment's timer alone.
                self.last_aired[segment] = now
                self.fingerprints[segment] = fingerprint
            if segment == 'messages':
                self.cycle += 1
        return True

    def _clear(self):
        if self.running:
            self.master.request('crawl', {'bulletin': None})
            self._ended(self.running['key'], 'cleared', self.clock())

    def _ended(self, key, how, at):
        for entry in self.history:
            if entry['key'] == key and entry['ended'] is None:
                entry['ended'], entry['how'] = at, how
        self.ledger.ended(key, how, at)
        if self.running and self.running['key'] == key:
            if self.running['loop']:
                self.loop_ids = set()
            else:
                self.last_end = at
            self.running = None

    def _observe_layers(self, settings, crawl_state, context):
        """The worker's important and override layers air items too: the ledger notes them."""
        current = self.layer_items(settings, crawl_state)
        kind = crawl_state.get('kind')
        for layer in ('important', 'override'):
            carried = current if kind == layer else []
            ids = {item['id'] for item in carried}
            added = [item for item in carried if item['id'] not in self.layer_ids[layer]]
            if added:
                self.ledger.aired(added, key=layer, context=context, layer=layer)
            if self.layer_ids[layer] - ids:
                self.ledger.ended(layer, 'cleared', ids=self.layer_ids[layer] - ids)
            self.layer_ids[layer] = ids
        return current

    # ------------------------------------------------------------------ the rotation

    def due(self, settings, crawl_state, context, now, feed_options=None):
        """Segments that could pop up, most overdue first: [(segment, seconds overdue, items)]."""
        feed_options = feed_options or self.feed_options()
        found = []
        for segment, options in settings['segments'].items():
            if not self.allowed(segment, settings, feed_options, context) or not feed_options['segments'][segment]['repeat']:
                continue
            wait = options['every'] * 60
            overdue = now - self.last_aired.get(segment, 0) - wait
            if overdue < 0:
                continue
            items = self.items(segment, settings, crawl_state, context, rotate=True)
            if not items:
                continue
            if options['changed_only'] and self.fingerprints.get(segment) == _fingerprint(items):
                continue
            found.append((segment, overdue / wait, items))
        found.sort(key=lambda entry: -entry[1])
        return found

    def tick(self):
        inputs = self._tick()
        if inputs is not None:
            self.snapshot = {**inputs, 'last_aired': dict(self.last_aired), 'fingerprints': dict(self.fingerprints),
                             'last_end': self.last_end, 'cycle': self.cycle,
                             'running': dict(self.running) if self.running else None,
                             'loop_ids': set(self.loop_ids), 'layer_ids': {k: set(v) for k, v in self.layer_ids.items()},
                             'history': [dict(entry) for entry in self.history]}
        now = self.clock()
        if now - self.pruned_at > 60:
            self.pruned_at = now
            self.ledger.prune()
        self.ledger.save()

    def _tick(self):
        settings = self.settings.read()
        for segment, feed in self.feeds.items():
            feed.want(settings['segments'][segment]['enabled'])
        state = self.master.request()
        crawl_state = state.get('crawl')
        now = self.clock()
        if crawl_state is None or 'bulletins_ended' not in crawl_state:
            # No worker, or one from before the rotation: it would refuse the crawl command.
            self.view = {'context': None, 'mode': None,
                         'error': 'Master is not running the crawl rotation (restart vizelvision-master)'}
            return None
        for ended in crawl_state.get('bulletins_ended') or []:
            if any(entry['key'] == ended['key'] and entry['ended'] is None for entry in self.history):
                self._ended(ended['key'], ended['how'], ended['at'])
        on_master = (crawl_state.get('bulletin') or {}).get('key')
        if self.running and on_master != self.running['key']:
            self._ended(self.running['key'], 'lost', now)  # The worker restarted or refused it.
        context = self.context(state, now)
        mode = settings['rules'][context]
        higher = crawl_state.get('kind') in ('important', 'override')
        recent = [e for e in self.history if not e['loop'] and not e['forced'] and now - e['started'] < 3600]
        self.view = {'context': context, 'mode': mode, 'error': None, 'higher': crawl_state.get('kind') if higher else None,
                     'popups_this_hour': len(recent)}
        with self.lock:
            forced, self.forced = self.forced, None
        options = self.feed_options()
        layered = self._observe_layers(settings, crawl_state, context)
        new, listings = {}, {}
        for segment in crawl.SEGMENTS:
            if not settings['segments'][segment]['enabled']:
                continue
            listings[segment] = listed = self.listing(segment, settings, crawl_state)
            news = options['segments'][segment]['new_now']
            fresh = self.ledger.listed(segment, listed, ready=self._ready(segment), news=news)
            if fresh and news and context in options['segments'][segment]['contexts']:
                applicable = {item['id'] for item in self.items(segment, settings, crawl_state, context)}
                found = [item for item in fresh if item['id'] in applicable]
                if found:
                    new[segment] = found
        self.view['new'] = {segment: len(items) for segment, items in new.items()}
        inputs = {'now': now, 'settings': settings, 'options': options, 'crawl_state': crawl_state,
                  'context': context, 'mode': mode, 'higher': self.view['higher'], 'new': new, 'listings': listings,
                  'layered': layered, 'radio': self._radio()}
        if higher:
            return inputs
        if forced:
            if isinstance(forced, tuple):  # air(): these items, from one segment
                segment, ids = forced
                items = [item for item in self.listing(segment, settings, crawl_state) if item['id'] in ids]
            else:
                segment, items = forced, self.items(forced, settings, crawl_state, context, rotate=True)
            if items:
                self._send(segment, items, context, forced=True)
            return inputs
        if self.running and not self.running['loop']:
            return inputs  # A pop-up is running its pass.
        if mode == 'always':
            items = self._loop_items(settings, options, crawl_state, context)
            if not items:
                self._clear()
                return inputs
            key = 'loop-' + context
            if (not self.running or self.running['key'] != key
                    or self.running['fingerprint'] != _fingerprint([_air(item) for item in items[:40]])
                    or now - self.running['renewed'] >= LOOP_RENEW):
                self._send('loop', items, context, loop=True, key=key)
            return inputs
        if self.running:
            self._clear()  # A loop from another context.
        if mode == 'quiet':
            return inputs
        for segment, items in new.items():  # New items first, at once.
            if self._send(segment, items, context, new=True):
                return inputs
        rules = settings['rules']
        if now - self.last_end < rules['gap_minutes'] * 60 or len(recent) >= rules['per_hour']:
            return inputs
        for segment, _, items in self.due(settings, crawl_state, context, now, options):
            if self._send(segment, items, context):
                return inputs
        return inputs

    # ------------------------------------------------------------------ control

    def run_now(self, segment):
        if segment not in crawl.SEGMENTS:
            raise ConfigError('Unknown segment')
        with self.lock:
            self.forced = segment
        return {'accepted': True}

    def find(self, ident):
        """An item the crawl lists now, by id: (segment, item) or (None, None)."""
        snap = self.snapshot or {}
        for item in snap.get('layered') or []:
            if item['id'] == ident:
                return item['segment'], item
        for segment, items in (snap.get('listings') or {}).items():
            for item in items:
                if item['id'] == ident:
                    return segment, item
        return None, None

    def air(self, ids):
        """Airs these items now as one pop-up, whatever the rules (like run_now)."""
        if (not isinstance(ids, list) or not 1 <= len(ids) <= 40 or len(set(ids)) != len(ids)
                or any(not isinstance(ident, str) for ident in ids)):
            raise ConfigError('Air takes a list of 1 to 40 item ids')
        snap = self.snapshot or {}
        if snap.get('higher'):
            raise ConfigError('Important news or the override holds the bar; nothing else airs until it ends')
        found = [self.find(ident) for ident in ids]
        if any(segment is None for segment, _ in found):
            raise ConfigError('That item is no longer listed')
        segments = {segment for segment, _ in found}
        if len(segments) != 1 or 'manual' in segments:
            raise ConfigError('Air items from one segment at a time (the important and override layers already run)')
        if any(item['id'] in (snap.get('layer_ids') or {}).get('important', ()) for _, item in found):
            raise ConfigError('That alert already runs in the important layer')
        with self.lock:
            self.forced = (segments.pop(), list(ids))
        return {'accepted': True}

    def mute(self, ident, muted):
        """Takes an item out of the crawl (or puts it back). EAS and NWS alerts are dismissed in
        crawl.json, which the worker honours; anything else is muted in the ledger."""
        if not isinstance(ident, str) or not isinstance(muted, bool):
            raise ConfigError('Mute takes an item id and true or false')
        source, _, rest = ident.partition(':')
        if source == 'manual':
            raise ConfigError('Clear the important or override message instead')
        if source == 'eas':
            if not rest.isdigit():
                raise ConfigError('An EAS alert id is a number')
            self.settings.dismiss('eas', int(rest), muted)
        elif source == 'nws':
            self.settings.dismiss('nws', rest, muted)
        else:
            segment, _ = self.find(ident)
            self.ledger.mute(ident, muted, segment=segment or '')
        return {'accepted': True}

    # ------------------------------------------------------------------ the plan

    def _duration(self, segment, items, history):
        """How long a pop-up of these items runs: what this segment's last passes took, else
        from its length (Nimbus Sans Bold at 720p is about 16 px a character, at 120 px/s)."""
        runs = [entry['ended'] - entry['started'] for entry in history
                if entry['segment'] == segment and entry['how'] == 'done' and entry['ended'] and not entry['loop']][-5:]
        if runs:
            return max(5., statistics.median(runs))
        chars = sum(len(item.get('tag') or '') + len(item.get('heading') or '') + len(item.get('text') or '') + 6
                    for item in items)
        return round((1280 + 160 + chars * 16) / 120 + 2, 1)

    def spans(self, snap, end):
        """Contexts from now to end: [{start, end, context, mode}]. Now's is master's actual
        context; after that the schedule projection's (games, the off-air card, programs)."""
        now, context, rules = snap['now'], snap['context'], snap['settings']['rules']
        cuts = []
        cached_at, cached_end, cached = self.spans_cache
        if self.projector is not None:
            if cached is not None and now - cached_at < 30 and cached_end >= end:
                cuts = cached
            else:
                try:
                    segments = self.projector.describe(datetime.fromtimestamp(now, timezone.utc),
                                                       datetime.fromtimestamp(end, timezone.utc)).get('segments') or []
                    for segment in segments:
                        start, stop = _epoch(segment.get('start')), _epoch(segment.get('end'))
                        if start is None or stop is None:
                            continue
                        kind = segment.get('kind')
                        cuts.append((start, stop, 'game' if kind == 'game' or segment.get('game')
                                     else 'off_air' if kind == 'off_air' else 'program'))
                except Exception as exc:
                    logging.getLogger(__name__).debug('Crawl plan cannot read the schedule: %s', exc)
                self.spans_cache = (now, end, cuts)
        spans = []
        for start, stop, kind in cuts:
            start, stop = max(start, now), min(stop, end)
            if stop <= start:
                continue
            if not spans:
                start, kind = now, context  # What master shows now beats the projection.
            if spans and spans[-1]['context'] == kind and abs(spans[-1]['end'] - start) < 1:
                spans[-1]['end'] = stop
            else:
                spans.append({'start': start, 'end': stop, 'context': kind})
        if not spans:
            spans = [{'start': now, 'end': end, 'context': context}]
        elif spans[-1]['end'] < end:
            spans.append({'start': spans[-1]['end'], 'end': end, 'context': spans[-1]['context']})
        for span in spans:
            span['mode'] = rules.get(span['context'], 'quiet')
        return spans

    def plan(self, snap=None, horizon=HORIZON):
        """Plays the rotation's rules forward: {spans, slots}, where each slot is a pop-up
        [{at, segment, ids, duration, context, new}] and a loop span lists what it carries.
        It assumes the items stay as they are and nothing new arrives."""
        snap = snap or self.snapshot
        if not snap:
            return {'spans': [], 'slots': [], 'until': None}
        settings, options = snap['settings'], snap['options']
        rules, segments = settings['rules'], settings['segments']
        now = snap['now']
        end = now + horizon
        spans = self.spans(snap, end)
        last_aired, fingerprints = dict(snap['last_aired']), dict(snap['fingerprints'])
        history = snap['history']
        recent = sorted(e['started'] for e in history if not e['loop'] and not e['forced'] and now - e['started'] < 3600)
        last_end, cycle = snap['last_end'], snap['cycle']
        crawl_state = snap['crawl_state']
        higher_until = None
        if snap['higher'] == 'important':
            higher_until = end  # Until its alerts expire or it is cleared: beyond what we can see.
        elif snap['higher'] == 'override':
            higher_until = min(end, _epoch(settings['override']['until']) or end)
        t = now
        running = snap['running']
        if running and not running['loop']:
            started = next((e['started'] for e in history if e['key'] == running['key']), now)
            items = [i for i in snap['listings'].get(running['segment'], []) if i['id'] in running['ids']]
            t = max(now + 3, started + self._duration(running['segment'], items, history))
            last_end = t
        muted = self.ledger.muted()
        radio = snap['radio']

        def applicable(segment, context):
            if not segments[segment]['enabled'] or context not in options['segments'][segment]['contexts']:
                return []
            if segment == 'cairo' and (context != 'off_air' or not radio):
                return []
            return [i for i in snap['listings'].get(segment, []) if i['id'] not in muted]

        records = self.ledger.snapshot()
        aired = {ident for ident, record in records.items() if record.get('first_aired')}
        # News still waiting: new_now segments' items that have never aired and are not background.
        pending = {}
        for segment, listed in snap['listings'].items():
            if options['segments'][segment]['new_now']:
                waiting = [i for i in listed if i['id'] not in aired and i['id'] not in muted
                           and not (records.get(i['id']) or {}).get('background', True)]
                if waiting:
                    pending[segment] = waiting
        slots, loops = [], []
        span_index = 0
        while t < end and len(slots) < PLAN_SLOTS:
            while span_index < len(spans) and spans[span_index]['end'] <= t:
                span_index += 1
            if span_index >= len(spans):
                break
            span = spans[span_index]
            if higher_until and t < higher_until:
                t = higher_until
                continue
            context, mode = span['context'], span['mode']
            if mode == 'always':  # The loop carries everything allowed here, news included.
                carried = [i for segment in crawl.SEGMENTS for i in applicable(segment, context)]
                if carried:
                    loops.append({'start': max(t, span['start']), 'end': span['end'], 'context': context,
                                  'ids': [i['id'] for i in carried]})
                ids = {i['id'] for i in carried}
                pending = {k: [i for i in v if i['id'] not in ids] for k, v in pending.items()}
                pending = {k: v for k, v in pending.items() if v}
                t = span['end']
                continue
            if mode != 'popups':
                t = span['end']
                continue
            news = None
            for segment, items in pending.items():
                here = {i['id'] for i in applicable(segment, context)}
                if any(i['id'] in here for i in items):
                    news = segment, [i for i in items if i['id'] in here]
                    break
            if news:
                segment, items = news
                duration = self._duration(segment, items, history)
                slots.append({'at': t, 'segment': segment, 'ids': [i['id'] for i in items], 'duration': duration,
                              'context': context, 'new': True})
                sent = {i['id'] for i in items}
                pending[segment] = [i for i in pending[segment] if i['id'] not in sent]
                pending = {k: v for k, v in pending.items() if v}
                recent.append(t)
                last_end = t = t + duration
                continue
            earliest = max(t, last_end + rules['gap_minutes'] * 60)
            window = [start for start in recent if start > earliest - 3600]
            if len(window) >= rules['per_hour']:
                earliest = max(earliest, window[-rules['per_hour']] + 3600)
            if earliest >= span['end']:
                t = span['end']
                continue
            candidates = []
            for segment, seg in segments.items():
                if not options['segments'][segment]['repeat']:
                    continue
                items = applicable(segment, context)
                if segment == 'messages' and items and settings['cycle_messages']:
                    items = [items[cycle % len(items)]]
                if not items or (seg['changed_only'] and fingerprints.get(segment) == _fingerprint(items)):
                    continue
                due = last_aired.get(segment, 0) + seg['every'] * 60
                candidates.append((max(due, earliest), segment, items))
            if not candidates:
                t = span['end']
                continue
            at = min(entry[0] for entry in candidates)
            if at >= span['end']:
                t = span['end']
                continue
            wait = lambda segment: segments[segment]['every'] * 60
            _, segment, items = max((entry for entry in candidates if entry[0] <= at),
                                    key=lambda entry: (at - last_aired.get(entry[1], 0) - wait(entry[1])) / wait(entry[1]))
            duration = self._duration(segment, items, history)
            slots.append({'at': at, 'segment': segment, 'ids': [i['id'] for i in items], 'duration': duration,
                          'context': context, 'new': False})
            last_aired[segment], fingerprints[segment] = at, _fingerprint(items)
            if segment == 'messages':
                cycle += 1
            recent.append(at)
            last_end = t = at + duration
        return {'spans': spans, 'slots': slots, 'loops': loops, 'until': end, 'higher_until': higher_until}

    # ------------------------------------------------------------------ the register

    def _why_held(self, segment, item, snap, aired):
        settings, options = snap['settings'], snap['options']
        seg, opt = settings['segments'][segment], options['segments'][segment]
        context = snap['context']
        where = crawl.CONTEXTS.get(context, context).lower()
        if not seg['enabled']:
            return 'The segment is off'
        if snap['higher'] == 'important':
            return 'Important news holds the bar'
        if snap['higher'] == 'override':
            return 'The override holds the bar'
        if segment == 'cairo' and (context != 'off_air' or not snap['radio']):
            return 'Airs only over the off-air card, while its audio is Cairo Radio'
        if not opt['repeat']:
            return 'Aired; repeat is off' if aired else 'Repeat is off, and it was listed before it counted as new'
        if seg['changed_only'] and aired and snap['fingerprints'].get(segment) == _fingerprint(
                snap['listings'].get(segment) or []):
            return 'Repeats when the segment changes'
        if context not in opt['contexts']:
            return f'Not set to air during {where}'
        if settings['rules'][context] == 'quiet':
            return f'Quiet during {where}'
        if segment == 'messages' and settings['cycle_messages']:
            return 'Waits its turn among the station messages'
        return f'Not within the next {HORIZON // 3600} hours'

    def register(self):
        """Every item the crawl lists now, alerts first, each with its airing status:
        on air, looping, next (a first airing or a repeat, and when), held (and why),
        muted or duplicate; plus the plan, the layers and items that ended lately."""
        snap = self.snapshot
        if not snap:
            return {'ready': False, 'error': self.view.get('error'), 'items': [], 'plan': self.plan(None), 'gone': []}
        now, settings, options = snap['now'], snap['settings'], snap['options']
        crawl_state = snap['crawl_state']
        plan = self.plan(snap)
        records = self.ledger.snapshot()
        running = snap['running'] or {}
        on_pass = set(running.get('ids') or []) if running and not running.get('loop') else set()
        looping = snap['loop_ids'] if running and running.get('loop') else set()
        layer_ids = snap['layer_ids']
        entries, listed_ids = [], set()

        def entry(item, segment, layer='rotation'):
            record = records.get(item['id']) or {}
            name, label, _ = crawl.SEGMENTS.get(segment, ('Manual', 'VIZELVISION', 0))
            source = item.get('source') or item['id'].split(':', 1)[0]
            listed_ids.add(item['id'])
            return {
                'id': item['id'], 'segment': segment, 'segment_name': name, 'label': label,
                'source': source, 'source_name': SOURCE_NAMES.get(source, name),
                'kind': 'alert' if segment in ALERT_SEGMENTS else 'info', 'layer': layer,
                'tag': item.get('tag') or '', 'heading': item.get('heading') or '', 'text': item.get('text') or '',
                **{key: item.get(key) for key in SUMMARY_META},
                'air_count': record.get('air_count', 0), 'first_seen': record.get('first_seen'),
                'first_aired': record.get('first_aired'), 'last_aired': record.get('last_aired'),
                'airings': (record.get('airings') or [])[-6:], 'muted': bool(record.get('muted')),
                'airing': 'repeat' if record.get('air_count') else 'first',
                'status': None, 'next_at': None, 'next_how': None, 'why': '', 'new': False,
            }

        # The worker's alerts first: severe ones run in the important layer, lesser ones in the
        # rotation's weather alerts; dismissed ones and duplicates are listed so they can come back.
        layered = {item['id']: item for item in snap['layered']}
        in_rotation = {item['id'] for item in snap['listings'].get('alerts', [])}
        for summary in crawl_state.get('alerts') or []:
            ident = _summary_id(summary)
            if ident in in_rotation:
                continue  # A rotation alert: placed with its segment below.
            item = layered.get(ident)
            known = records.get(ident) or {}
            item = item or {'id': ident, 'tag': known.get('tag', ''), 'text': known.get('text', ''),
                            'heading': known.get('heading') or str(summary.get('event') or '').upper()}
            item = {**item, **self._meta(summary)}
            if not item.get('text'):
                item['text'] = f"{summary.get('event')} for {summary.get('areas') or 'the area'}"
            e = entry(item, 'alerts', 'important' if summary.get('important') else 'rotation')
            if summary.get('dismissed'):
                e.update(status='muted', why='Dismissed: taken out of the crawl')
            elif summary.get('duplicate'):
                e.update(status='duplicate', why='The NWS alert for the same event airs instead (official wording)')
            elif summary.get('important'):
                if ident in layer_ids['important']:
                    e.update(status='looping', why='Important: runs continuously over everything until it expires')
                else:
                    e.update(status='held', why='Important, but not running yet: the worker has not picked it up')
            entries.append(e)
        manual = settings['important']
        moment = datetime.fromtimestamp(now, timezone.utc)
        if crawl.layer_active(manual, moment):
            e = entry(layered.get('manual:important') or {'id': 'manual:important', 'tag': '', 'heading': '',
                                                           'text': manual['text'], 'source': 'manual'}, 'manual', 'important')
            e.update(label=manual['label'].upper() or 'IMPORTANT', expires=manual['until'])
            on = 'manual:important' in layer_ids['important']
            e.update(status='looping' if on else 'held',
                     why=('Important message: runs continuously' + (' until it ends' if manual['until'] else ' until cleared'))
                     if on else 'Waiting for the worker to pick it up')
            entries.append(e)
        override = settings['override']
        if crawl.layer_active(override, moment):
            e = entry({'id': 'manual:override', 'tag': '', 'heading': '', 'text': override['text'], 'source': 'manual'},
                      'manual', 'override')
            e.update(label=override['label'].upper() or 'UPDATE', expires=override['until'])
            if 'manual:override' in layer_ids['override']:
                e.update(status='looping', why='Override: holds the bar' + (' until it ends' if override['until'] else ' until cleared'))
            else:
                e.update(status='held', why='Waits: important news runs first' if snap['higher'] == 'important'
                         else 'Waiting for the worker to pick it up')
            entries.append(e)

        first_slot = {}
        for slot in plan['slots']:
            for ident in slot['ids']:
                first_slot.setdefault(ident, slot)
        first_loop = {}
        for loop in plan['loops']:
            for ident in loop['ids']:
                first_loop.setdefault(ident, loop)
        news = {item['id'] for items in snap['new'].values() for item in items}
        for segment in crawl.SEGMENTS:
            for item in snap['listings'].get(segment, []):
                if item['id'] in listed_ids:
                    continue
                e = entry(item, segment)
                ident = item['id']
                e['new'] = ident in news
                slot, loop = first_slot.get(ident), first_loop.get(ident)
                if e['muted']:
                    e.update(status='muted', why='Muted: taken out of the crawl')
                elif ident in on_pass:
                    e.update(status='on_air', why='In the pop-up on air now')
                elif ident in looping:
                    e.update(status='looping', why=f"In the {crawl.CONTEXTS.get(snap['context'], '').lower()} loop")
                elif slot and (not loop or slot['at'] <= loop['start']):
                    how = 'new' if slot['new'] else 'popup'
                    if slot['new']:
                        why = 'New: pops up at once, ahead of the timer'
                    elif e['airing'] == 'first':
                        why = f"First airing, in {e['segment_name']}'s next pop-up"
                    else:
                        why = f"Repeats with {e['segment_name']} every {settings['segments'][segment]['every']} min"
                    if slot['context'] != snap['context'] and snap['context'] in AFTER:
                        why += AFTER[snap['context']]
                    e.update(status='next', next_at=slot['at'], next_how=how, why=why)
                elif loop:
                    e.update(status='next', next_at=loop['start'], next_how='loop',
                             why=f"In the {crawl.CONTEXTS.get(loop['context'], '').lower()} loop from then")
                else:
                    e.update(status='held', why=self._why_held(segment, item, snap, bool(e['air_count'])))
                entries.append(e)
        if not settings['segments']['alerts']['enabled']:
            for e in entries:
                if e['segment'] == 'alerts' and e['layer'] == 'rotation' and e['status'] is None:
                    e.update(status='held', why='The weather alerts segment is off')
        for e in entries:
            if e['status'] is None:  # A rotation alert the worker lists beyond its ten.
                e.update(status='held', why='Beyond the ten alerts the rotation carries')
            # The airing on air now, or the next one: an item's first, or a repeat.
            current = e['status'] in ('on_air', 'looping')
            e['airing'] = 'first' if e['air_count'] - (1 if current else 0) <= 0 else 'repeat'
        rank = {status: index for index, status in enumerate(STATUS_ORDER)}
        severity = {'national': 0, 'warning': 1, 'extreme': 0, 'severe': 1, 'watch': 2, 'moderate': 2, 'advisory': 3}
        entries.sort(key=lambda e: (e['kind'] != 'alert', rank.get(e['status'], 9),
                                    severity.get(str(e.get('severity') or '').casefold(), 5),
                                    e['next_at'] or float('inf'), -(e['first_seen'] or 0)))
        gone = sorted(({'id': ident, 'segment': record.get('segment'), 'tag': record.get('tag', ''),
                        'heading': record.get('heading', ''), 'text': record.get('text', ''),
                        'source': record.get('source') or ident.split(':', 1)[0],
                        'air_count': record.get('air_count', 0), 'first_seen': record.get('first_seen'),
                        'last_aired': record.get('last_aired'), 'last_listed': record.get('last_listed')}
                       for ident, record in records.items()
                       if ident not in listed_ids and record.get('last_listed') and now - record['last_listed'] < 6 * 3600),
                      key=lambda g: -(g['last_listed'] or 0))[:40]
        counts = {status: sum(1 for e in entries if e['status'] == status) for status in STATUS_ORDER}
        return {'ready': True, 'now': now, 'context': snap['context'], 'mode': snap['mode'], 'higher': snap['higher'],
                'running': running or None, 'items': entries, 'counts': counts, 'plan': plan, 'gone': gone,
                'horizon': HORIZON, 'error': self.view.get('error')}

    def status(self, settings=None, crawl_state=None):
        settings = settings or self.settings.read()
        crawl_state = crawl_state or {}
        context = self.view.get('context') or 'program'
        now = self.clock()
        planned = {}
        try:
            for slot in self.plan()['slots']:
                planned.setdefault(slot['segment'], slot['at'])
        except Exception as exc:  # The plan is a forecast: never a reason to fail the status.
            logging.getLogger(__name__).debug('Crawl plan failed: %s', exc)
        segments = {}
        for segment, options in settings['segments'].items():
            feed = self.feeds.get(segment)
            items = self.items(segment, settings, crawl_state, context)
            last = self.last_aired.get(segment)
            segments[segment] = {
                'feed': feed.status() if feed else None, 'last_aired': last,
                'next_due': (last or 0) + options['every'] * 60 if last else now, 'next_planned': planned.get(segment),
                'preview': [{**item, 'text': item['text'][:240]} for item in items[:8]], 'count': len(items)}
        return {**self.view, 'running': dict(self.running) if self.running else None, 'segments': segments,
                'history': list(reversed(self.history))[:25], 'last_end': self.last_end or None}

    def _run(self):
        while not self.stopping.is_set():
            try:
                self.tick()
            except Exception as exc:
                self.view = {**self.view, 'error': f'Crawl rotation paused: {exc}'}
                logging.getLogger(__name__).warning('Crawl desk tick failed: %s', exc)
            self.stopping.wait(self.TICK)

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='crawl-desk', daemon=True)
            self.thread.start()

    def stop(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(5)
        for feed in self.feeds.values():
            feed.stop()
        self.ledger.save(force=True)
