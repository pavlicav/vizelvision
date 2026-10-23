"""The mix: which of my ads next, keeping kinds of ads in balance and resting the ones seen most.

The plain shuffle (my_ads.Rotation) treats every ad alike, so an ad that has aired a hundred
times comes round as often as one uploaded today. The mix picks in two steps, every knob of
it set on the page (Ads › Mix) and kept in the tuning (TUNING has each one's range):

1. A kind of ad (a category). Each kind has a share (its weight; ads with no kind share
   `unsorted`'s). The rotation's last `window` ads are counted by kind, and the kind furthest
   behind its share goes next. The kind that just aired must be `again` plays further behind
   to go again, so kinds take turns. A kind whose best chance is under `tired` of the best of
   all sits that pick out, so a small or worn kind takes less than its share instead of
   looping its few ads.
2. An ad of that kind, by chance:
       seen    its plays from the whole play log, each worth half as much every
               `half_life_days`, times how fast it wears (its kind's wear × its own; 0: never)
       worn    floor + (1 − floor) / (1 + seen / familiar) ^ curve
       rest    (hours since it aired / rest_hours)², at most 1
       new     × new_boost for new_days after its upload
       chance  worn × rest × new × its own boost (0 leaves it out of the mix)
   A new ad's chance is 1. With the defaults, one seen 40 times lately has about 1/60 of
   that: it still airs now and then, and comes back as its plays fade.

The ads' limits and switches hold as always: the mix only chooses among the ads allowed now.
Same interface as Rotation (pick, played, undraw), so master's Next up draws ahead the same
way. simulate() replays the days ahead, with the same chance() and choose(), for the page's
preview.

Beside my-ads.json:
    my-ads-mix.json   {enabled, tuning: {…}, categories: [{key, name, weight, wear, about}],
                       ads: {ad id: key}, overrides: {ad id: {boost, wear}}}
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, deque
import copy
import json
import os
from pathlib import Path
import random
import statistics
import tempfile
import threading

from .errors import ConfigError
from .my_ads import allowed, played

UNSORTED = 'unsorted'
# key: (default, lowest, highest), as the page's sliders run.
TUNING = {
    'half_life_days': (14.0, 1.0, 90.0),   # a play counts half as much this many days on
    'familiar': (6.0, 1.0, 60.0),          # plays (fading) at which an ad starts to feel worn
    'curve': (2.0, 0.0, 4.0),              # how hard worn ads are held back (0: never)
    'floor': (0.0, 0.0, 0.5),              # the chance a worn ad never drops under
    'rest_hours': (24.0, 0.0, 168.0),      # after a play, its full chance again this much later
    'new_days': (0.0, 0.0, 30.0),          # new uploads' boost lasts this long (0: no boost)
    'new_boost': (2.0, 1.0, 5.0),          # ... and multiplies their chance by this
    'window': (30.0, 6.0, 200.0),          # the rotation's ads the balance counts (about 5 breaks)
    'again': (0.25, 0.0, 3.0),             # how far behind the kind just aired must be to go again
    'tired': (0.25, 0.0, 1.0),             # a kind sits a pick out under this share of the best chance
    'unsorted': (1.0, 0.0, 10.0),          # the share of the ads with no kind
}
WEIGHT = (0.0, 10.0)        # a kind's share
WEAR = (0.0, 3.0)           # how fast a kind, or an ad, wears (1: as tuned; 0: never)
BOOST = (0.0, 5.0)          # an ad's own chance, times (0: out of the mix)
MAX_CATEGORIES = 12
# Until 20 October 2026 one setting, rest, stood for familiar and curve.
LEGACY_REST = {'off': {'curve': 0.0}, 'gentle': {'familiar': 12.0}, 'normal': {}, 'strong': {'familiar': 3.0}}
_KEY = 'abcdefghijklmnopqrstuvwxyz0123456789-'
DEFAULTS = {'enabled': False, 'tuning': {k: v[0] for k, v in TUNING.items()}, 'categories': [], 'ads': {}, 'overrides': {}}


def _number(value, lo, hi, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ConfigError(f'{name} is a number from {lo:g} to {hi:g}')
    return float(value)


def validate(value, *, lenient=False, ad_ids=None):
    """The mix as kept: strict for the web app; lenient for master (what it cannot read, it
    leaves at the default). ad_ids: the ads there are (the others' entries are dropped)."""
    if not isinstance(value, dict):
        raise ConfigError('The mix must be an object')
    value = dict(value)
    legacy = LEGACY_REST.get(value.pop('rest', None), {})
    if lenient:
        value = {k: v for k, v in value.items() if k in DEFAULTS}
    elif not set(value) <= set(DEFAULTS):
        raise ConfigError('The mix takes ' + ', '.join(DEFAULTS))
    result = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(value)}
    if not isinstance(result['enabled'], bool):
        raise ConfigError('enabled must be true or false')

    tuning = value.get('tuning', {})
    if not isinstance(tuning, dict) or (not lenient and not set(tuning) <= set(TUNING)):
        raise ConfigError('tuning takes ' + ', '.join(TUNING))
    result['tuning'] = {}
    for key, (default, lo, hi) in TUNING.items():
        try:
            result['tuning'][key] = _number(tuning.get(key, legacy.get(key, default)), lo, hi, key)
        except ConfigError:
            if not lenient:
                raise
            result['tuning'][key] = default
    result['tuning']['window'] = float(round(result['tuning']['window']))

    cats = result['categories']
    if not isinstance(cats, list) or len(cats) > MAX_CATEGORIES:
        raise ConfigError(f'The mix has at most {MAX_CATEGORIES} kinds')
    checked, keys = [], set()
    for c in cats:
        if not isinstance(c, dict) or not {'key', 'name'} <= set(c) or not set(c) <= {'key', 'name', 'weight', 'wear', 'about'}:
            raise ConfigError('A kind takes key, name, weight, wear and about')
        key = c['key']
        if (not isinstance(key, str) or not 1 <= len(key) <= 24 or set(key) - set(_KEY)
                or key == UNSORTED or key in keys):
            raise ConfigError('A kind needs its own short key (a-z, 0-9, -)')
        name, about = c['name'], c.get('about', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
            raise ConfigError('A kind\'s name is 1 to 40 characters')
        if not isinstance(about, str) or len(about) > 600:
            raise ConfigError('A kind\'s description is at most 600 characters')
        keys.add(key)
        checked.append({'key': key, 'name': name.strip(), 'weight': _number(c.get('weight', 1), *WEIGHT, 'A kind\'s share'),
                        'wear': _number(c.get('wear', 1), *WEAR, 'A kind\'s wear'), 'about': about.strip()})
    result['categories'] = checked

    ads = result['ads']
    if not isinstance(ads, dict):
        raise ConfigError('ads maps ad ids to kinds')
    result['ads'] = {}
    for ad_id, key in ads.items():
        if key not in keys:
            if lenient:
                continue
            raise ConfigError(f'No kind {key!r}')
        if ad_ids is None or ad_id in ad_ids:
            result['ads'][ad_id] = key

    overrides = result['overrides']
    if not isinstance(overrides, dict):
        raise ConfigError('overrides maps ad ids to their boost and wear')
    result['overrides'] = {}
    for ad_id, own in overrides.items():
        try:
            if not isinstance(own, dict) or not set(own) <= {'boost', 'wear'}:
                raise ConfigError('An ad\'s own settings are boost and wear')
            own = {'boost': _number(own.get('boost', 1), *BOOST, 'An ad\'s boost'),
                   'wear': _number(own.get('wear', 1), *WEAR, 'An ad\'s wear')}
        except ConfigError:
            if lenient:
                continue
            raise
        if own != {'boost': 1., 'wear': 1.} and (ad_ids is None or ad_id in ad_ids):
            result['overrides'][ad_id] = own
    return result


class MixStore:
    """my-ads-mix.json, read by master (lenient, cached until it changes) and written by the web app."""

    def __init__(self, socket_path, *, lenient=False):
        self.path = Path(socket_path).with_name('my-ads-mix.json')
        self.lenient = lenient
        self.lock = threading.RLock()
        self._cache = (None, None)

    def read(self):
        try:
            st = self.path.stat()
            stamp = (st.st_mtime_ns, st.st_ino, st.st_size)   # every save is a new file
        except OSError:
            return copy.deepcopy(DEFAULTS)
        if self._cache[0] != stamp:
            try:
                value = validate(json.loads(self.path.read_text()), lenient=self.lenient)
            except (OSError, ValueError, ConfigError):
                if not self.lenient:
                    raise
                value = copy.deepcopy(DEFAULTS)
            self._cache = (stamp, value)
        return copy.deepcopy(self._cache[1])

    def save(self, value, ad_ids=None):
        value = validate(value, ad_ids=ad_ids)
        with self.lock:
            fd, name = tempfile.mkstemp(prefix='.my-ads-mix-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(value, stream, indent=1)
                    stream.write('\n')
                os.chmod(name, 0o660)
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
        return value

    def change(self, change, ad_ids=None):
        with self.lock:
            value = self.read()
            change(value)
            return self.save(value, ad_ids)


class Exposure:
    """Every counted play of each ad, from the whole play log: read once, then only what was
    appended (a line still being written waits for the next read)."""

    def __init__(self, path):
        self.path = Path(path)
        self.offset, self.times, self.newest = 0, {}, 0.
        self.lock = threading.Lock()

    def read(self):
        with self.lock:
            try:
                with open(self.path, 'rb') as f:
                    size = f.seek(0, 2)
                    if size < self.offset:
                        self.offset, self.times, self.newest = 0, {}, 0.
                    f.seek(self.offset)
                    chunk = f.read(size - self.offset)
            except OSError:
                return self.times
            end = chunk.rfind(b'\n') + 1
            for line in chunk[:end].splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if (isinstance(row, dict) and row.get('kind', 'ad') == 'ad' and isinstance(row.get('at'), (int, float))
                        and isinstance(row.get('id'), str) and played(row)):
                    self.times.setdefault(row['id'], []).append(row['at'])
                    self.newest = max(self.newest, row['at'])
            self.offset += end
            return self.times


# ---------------------------------------------------------------- an ad's chance

def seen(times, now, half_life_days=TUNING['half_life_days'][0]):
    """Its plays, each worth half as much every half_life_days."""
    half_life = half_life_days * 86400
    return sum(0.5 ** (max(0., now - t) / half_life) for t in times)


def chance(seen_plays, last, now, tuning, *, wear=1., boost=1., added=None):
    """An ad's chance to be picked within its kind (a new ad's: 1). seen_plays: seen();
    last: when it last aired (None: never); wear: its kind's × its own; boost: its own."""
    t = tuning
    worn = 1.
    if t['curve'] > 0:
        worn = 1 / (1 + seen_plays * wear / t['familiar']) ** t['curve']
    worn = t['floor'] + (1 - t['floor']) * worn
    rest = 1.
    if last is not None and t['rest_hours'] > 0:
        rest = min(1., max(0., now - last) / 3600 / t['rest_hours']) ** 2
    new = t['new_boost'] if t['new_days'] > 0 and added and now - added < t['new_days'] * 86400 else 1.
    return max(worn * rest * new * boost, 1e-6)


def kinds_of(mix, ads):
    """{ad id: its kind}: its own, or unsorted (none, or one since removed)."""
    known = {c['key'] for c in mix['categories']}
    return {a['id']: mix['ads'].get(a['id']) if mix['ads'].get(a['id']) in known else UNSORTED for a in ads}


def own(mix, kind):
    """({ad id: how fast it wears: its kind's wear × its own}, {ad id: its boost}), for the ads in kind."""
    kind_wear = {c['key']: c['wear'] for c in mix['categories']}
    over = mix['overrides']
    return ({i: kind_wear.get(k, 1.) * over.get(i, {}).get('wear', 1.) for i, k in kind.items()},
            {i: over.get(i, {}).get('boost', 1.) for i in kind})


def choose(mix, ok, kind, recent, chances, last_kind, rng):
    """The pick: a kind (see the module doc), then an ad of it by chance. ok: the ads that may
    air (boost over 0); kind: {ad id: kind}; recent: the kinds of the last ads, oldest first."""
    t = mix['tuning']
    shares = {c['key']: c['weight'] for c in mix['categories']}
    shares[UNSORTED] = t['unsorted']
    present = {kind[a['id']] for a in ok}
    shares = {k: w for k, w in shares.items() if k in present and w > 0}
    if not shares:
        return None
    recent = list(recent)[-int(t['window']):]
    counts, total, n = Counter(recent), sum(shares.values()), len(recent) + 1
    behind = {k: w / total * n - counts.get(k, 0) for k, w in shares.items()}
    order = sorted(behind, key=lambda k: (-(behind[k] - t['again'] * (k == last_kind)), rng.random()))
    pools = {k: [] for k in order}
    for a in ok:
        if kind[a['id']] in pools:
            pools[kind[a['id']]].append(a)
    best = {k: max(chances[a['id']] for a in pool) for k, pool in pools.items()}
    top = max(best.values())
    pick = next((k for k in order if best[k] >= t['tired'] * top), order[0])
    pool = pools[pick]
    return rng.choices(pool, [chances[a['id']] for a in pool])[0]


class Mix:
    """Which ad next (see the module doc). pick() only looks; played() commits a draw (Next up
    draws ahead); undraw() puts draws back."""

    def __init__(self, plays_path, rng=None):
        self.exposure = Exposure(plays_path)
        self.rng = rng or random.Random()
        self.last = None

    def pick(self, settings, plays, now, skip=(), mix=None):
        mix = mix or DEFAULTS
        t = mix['tuning']
        everyone = settings['ads']
        kind = kinds_of(mix, everyone)
        wear, boost = own(mix, kind)
        ok = [a for a in everyone if a['id'] not in skip and boost[a['id']] > 0
              and allowed(a, plays, now, settings.get('limits_from'))]
        recent = [kind[p['id']] for p in sorted(plays, key=lambda p: p.get('at', 0))
                  if p.get('kind', 'ad') == 'ad' and p.get('id') in kind]
        times = self.exposure.read()
        extra = {}
        for p in plays:               # drawn ahead, or on air: not in the log yet
            if p.get('kind', 'ad') == 'ad' and p.get('at', 0) > self.exposure.newest and isinstance(p.get('id'), str):
                extra.setdefault(p['id'], []).append(p['at'])
        chances = {}
        for a in ok:
            mine = times.get(a['id'], []) + extra.get(a['id'], [])
            chances[a['id']] = chance(seen(mine, now, t['half_life_days']), max(mine) if mine else None, now, t,
                                      wear=wear[a['id']], boost=boost[a['id']], added=a.get('added'))
        last_kind = kind.get(self.last) if self.last else None
        return choose(mix, ok, kind, recent, chances, last_kind, self.rng)

    def played(self, ad_id):
        self.last = ad_id

    def undraw(self, ids, last):
        self.last = last


# ---------------------------------------------------------------- the days ahead (the page's preview)

def pace(rows, now, days=7):
    """How the breaks have run lately: (breaks a day, ads a break), from the play log's rows."""
    times = sorted(r['at'] for r in rows if r.get('kind', 'ad') == 'ad' and isinstance(r.get('at'), (int, float))
                   and now - days * 86400 <= r['at'] <= now)
    if len(times) < 12:
        return 40., 6
    breaks, size = [], 1
    for a, b in zip(times, times[1:]):
        if b - a > 120:
            breaks.append(size)
            size = 1
        else:
            size += 1
    breaks.append(size)
    span = max(1., min(days, (now - times[0]) / 86400))
    return max(1., len(breaks) / span), max(1, round(statistics.median(breaks)))


class _Air:
    """What a replay keeps of each ad: how much it has been seen (decaying from `at`), when it
    last aired, and the plays its limit can see."""

    def __init__(self, settings, rows, now, half_life_days):
        self.half_life = half_life_days * 86400
        self.since = settings.get('limits_from') or 0
        self.seen, self.last, self.recent = {}, {}, {}
        horizon = max((a['limit']['minutes'] for a in settings['ads'] if a.get('limit')), default=0) * 60
        for r in rows:
            if r.get('kind', 'ad') != 'ad' or not isinstance(r.get('at'), (int, float)) or not played(r) or r['at'] > now:
                continue
            i, at = r.get('id'), r['at']
            s, ref = self.seen.get(i, (0., now))
            self.seen[i] = (s + 0.5 ** ((now - at) / self.half_life), now)
            self.last[i] = max(self.last.get(i, at), at)
            if at >= now - horizon:
                self.recent.setdefault(i, []).append(at)
        for times in self.recent.values():
            times.sort()

    def seen_now(self, ad_id, now):
        s, ref = self.seen.get(ad_id, (0., now))
        return s * 0.5 ** ((now - ref) / self.half_life)

    def air(self, ad_id, now):
        self.seen[ad_id] = (self.seen_now(ad_id, now) + 1, now)
        self.last[ad_id] = now
        self.recent.setdefault(ad_id, []).append(now)

    def allowed(self, ad, now):
        if not ad.get('enabled'):
            return False
        limit = ad.get('limit')
        if not limit:
            return True
        times = self.recent.get(ad['id'], [])
        start = max(now - limit['minutes'] * 60, self.since, ad.get('limits_from') or 0)
        return len(times) - bisect_left(times, start) < limit['count']


def simulate(settings, rows, mix, now, *, days=3., seed=7):
    """The next `days` as master would air them, with this mix and, to compare, the plain
    shuffle: breaks at the play log's own pace. Returns what the page shows: each kind's share,
    each ad's plays, and how the most seen fare."""
    breaks_a_day, per_break = pace(rows, now)
    ads = settings['ads']
    kind = kinds_of(mix, ads)
    wear, boost = own(mix, kind)
    lifetime = Counter(r.get('id') for r in rows if r.get('kind', 'ad') == 'ad' and played(r))
    worn = [i for i, _ in lifetime.most_common() if i in kind][:30]
    seldom = {a['id'] for a in ads if lifetime[a['id']] < 3}

    def replay(pick):
        clock, rng = random.Random(seed), random.Random(seed + 1)   # the same breaks for the mix and the shuffle
        air = _Air(settings, rows, now, mix['tuning']['half_life_days'])
        aired, t, end = [], now, now + days * 86400
        while t < end:
            t += clock.uniform(.6, 1.4) * 86400 / breaks_a_day
            for _ in range(per_break):
                ad = pick(air, t, rng, aired)
                if ad is None:
                    break
                air.air(ad['id'], t)
                aired.append((ad['id'], t))
                t += ad['duration']
        return aired

    def by_mix(air, t, rng, aired):
        tuning = mix['tuning']
        ok = [a for a in ads if boost[a['id']] > 0 and air.allowed(a, t)]
        chances = {a['id']: chance(air.seen_now(a['id'], t), air.last.get(a['id']), t, tuning,
                                   wear=wear[a['id']], boost=boost[a['id']], added=a.get('added')) for a in ok}
        recent = [kind[i] for i, _ in aired[-int(tuning['window']):]]
        return choose(mix, ok, kind, recent, chances, kind[aired[-1][0]] if aired else None, rng)

    bag, last = [], [None]

    def by_shuffle(air, t, rng, aired):
        ok = {a['id']: a for a in ads if air.allowed(a, t)}
        if not ok:
            return None
        bag[:] = [i for i in bag if i in ok]
        if not bag:
            bag.extend(ok)
            rng.shuffle(bag)
            if len(bag) > 1 and bag[0] == last[0]:
                bag.append(bag.pop(0))
        last[0] = bag.pop(0)
        return ok[last[0]]

    def summary(aired):
        n = max(1, len(aired))
        plays = Counter(i for i, _ in aired)
        per_day = Counter((i, int((t - now) // 86400)) for i, t in aired)
        gaps, prev = [], {}
        for i, t in aired:
            if i in prev:
                gaps.append((t - prev[i]) / 3600)
            prev[i] = t
        kinds = Counter(kind[i] for i, _ in aired)
        return {'plays': len(aired), 'distinct': len(plays), 'ads': dict(plays),
                'kinds': {k: round(v / n, 4) for k, v in kinds.items()},
                'worn_share': round(sum(plays[i] for i in worn) / n, 4),
                'seldom_share': round(sum(plays[i] for i in seldom) / n, 4),
                'most_in_a_day': max(per_day.values(), default=0),
                'gap_hours': round(statistics.median(gaps), 1) if gaps else None}

    return {'days': days, 'breaks_a_day': round(breaks_a_day, 1), 'per_break': per_break, 'worn': worn,
            'mix': summary(replay(by_mix)), 'shuffle': summary(replay(by_shuffle))}
