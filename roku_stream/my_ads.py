"""My ads: the operator's own ads, shown in place of the breaks ad mute takes off air.

While ad mute has a programme muted (mode On), master shows one of these ads with its
sound, then the next; with none left that may play, the break card. The programme stays
on screen small, picture in picture, so its return is seen and can be fixed at once
("It's the show"). The master side is ad_break.py.

Shared by the web app (strict, and the only writer of the settings) and the master
worker (lenient: a newer web app's keys never stop it). Pure Python, apart from what the
web app runs on an upload (ffprobe, ffmpeg) and the break card's renderer (cairo,
through the station ID's own drawing code).

Beside the master socket:
    my-ads.json          settings and the list of ads, in their order
    my-ads/              the ads (<id>.<ext>), their pictures (<id>-<n>.jpg), the break card
    my-ads-plays.jsonl   what aired: each ad, and each stretch of break card (the worker)
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from .errors import ConfigError

ORDERS = ('shuffle', 'list')
CORNERS = ('bottom-right', 'bottom-left', 'top-right', 'top-left')
SIZES = ('small', 'medium', 'large')
DEFAULTS = {
    # Show my ads (or the break card) over muted breaks. Ad mute must be On.
    'enabled': True,
    # shuffle: a random order, every ad once before any plays again. list: top to bottom.
    'order': 'shuffle',
    # The muted programme, small, in a corner of the ad or card.
    'pip': {'enabled': True, 'corner': 'bottom-right', 'size': 'medium'},
    # The break card: the station ID's end card with these words, or an image of your own.
    'card': {'text': 'STAY TUNED', 'image': None},
    # The limit a new upload gets: None, or at most count plays in any minutes.
    'default_limit': None,
    # A reset of the limits: plays before this time (epoch seconds) do not count towards any
    # ad's limit (they stay in the play log and its counts). None: every play counts.
    'limits_from': None,
    'ads': [],
}
AD_DEFAULTS = {'name': '', 'enabled': True, 'limit': None, 'trim_db': 0.0, 'audio': True, 'lufs': None,
               'gain_db': 0.0, 'pics': 0, 'width': None, 'height': None, 'bytes': None, 'added': None,
               'source_name': None, 'converted': False, 'limits_from': None}
VIDEO_EXT = ('.mp4', '.m4v', '.mov', '.mkv', '.webm', '.ts', '.mts', '.m2ts', '.avi', '.mpg', '.mpeg', '.wmv', '.flv')
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.webp')
MAX_BYTES = 4_000_000_000
MAX_IMAGE_BYTES = 25_000_000
MAX_SECONDS = 15 * 60
MAX_ADS = 500                  # 200 until 10/19 (~7.5 MB an ad on disk: ~3.8 GB at 500)
LIMIT_COUNT = (1, 50)
LIMIT_MINUTES = (5, 7 * 24 * 60)
TRIM_DB = (-12.0, 12.0)
# A play counts towards an ad's limit once this much of it has aired (half of a shorter ad):
# breaks often end mid-ad, the programme's return cutting it short.
COUNTS_AFTER = 10.0
CARD_TEXT = 32
# Ads are levelled to the station's loudness (the station ID and the TV recordings, ident/sonic.py),
# and never pushed past -1 dB true peak.
LOUDNESS = -20.0
TRUE_PEAK = -1.0
GAIN_DB = (-20.0, 12.0)
PICTURES = (.15, .40, .65, .90)
# Pixels a second master's ad decoder is sure to keep up with, beside a live programme. Heavier
# uploads (4K, 1080p60 from a phone) are converted once, on upload, to 720p H.264.
HEAVY = 1920 * 1080 * 30
PICTURE_SIZE = (256, 144)
# The break card: the station ID's end card (ident/animation.py), its banner reading the card's text.
IDENT = Path(__file__).resolve().parent.parent / 'ident'
CARD_AT = 27.0
_ID = re.compile(r'[0-9a-f]{12}')


def _number(value, lo, hi, name, integer=False):
    if isinstance(value, bool) or not isinstance(value, int if integer else (int, float)) or not lo <= value <= hi:
        raise ConfigError(f'{name} must be {"a whole number" if integer else "a number"} from {lo} to {hi}')
    return value


def validate_limit(value, name='limit'):
    """None, or {count, minutes}: at most count plays in any stretch of that many minutes."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'count', 'minutes'}:
        raise ConfigError(f'{name} takes count and minutes, or null for no limit')
    return {'count': _number(value['count'], *LIMIT_COUNT, f'{name} count', True),
            'minutes': _number(value['minutes'], *LIMIT_MINUTES, f'{name} minutes', True)}


def validate_name(value):
    if not isinstance(value, str) or len(value.strip()) > 80:
        raise ConfigError('name must be text of up to 80 characters')
    return value.strip()


def validate_card_text(value):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > CARD_TEXT:
        raise ConfigError(f'The card says 1 to {CARD_TEXT} characters')
    return ' '.join(value.split()).upper()


def _validate_ad(ad, lenient):
    if not isinstance(ad, dict):
        raise ConfigError('Each ad must be an object')
    if lenient:
        ad = {k: v for k, v in ad.items() if k in AD_DEFAULTS or k in ('id', 'file', 'duration')}
    result = {**AD_DEFAULTS, **copy.deepcopy(ad)}
    if not isinstance(result.get('id'), str) or not _ID.fullmatch(result['id']):
        raise ConfigError('An ad has no id')
    file = result.get('file')
    if (not isinstance(file, str) or not file.startswith(result['id'] + '.')
            or not file.lower().endswith(VIDEO_EXT) or '/' in file):
        raise ConfigError('An ad has no file')
    result['duration'] = float(_number(result.get('duration'), .5, MAX_SECONDS + 60, 'duration'))
    result['name'] = validate_name(result['name'])
    result['limit'] = validate_limit(result['limit'])
    if result['limits_from'] is not None:                # this ad's own reset (settings' limits_from: all)
        result['limits_from'] = float(_number(result['limits_from'], 0, 4e9, 'limits_from'))
    result['trim_db'] = float(_number(result['trim_db'], *TRIM_DB, 'trim_db'))
    result['gain_db'] = float(_number(result['gain_db'], *GAIN_DB, 'gain_db'))
    for key in ('enabled', 'audio'):
        if not isinstance(result[key], bool):
            raise ConfigError(f'{key} must be true or false')
    return result


def validate(value, *, lenient=False):
    if not isinstance(value, dict):
        raise ConfigError('My ads settings must be an object')
    if lenient:
        value = {k: v for k, v in value.items() if k in DEFAULTS}
    elif not set(value) <= set(DEFAULTS):
        raise ConfigError('My ads settings take ' + ', '.join(DEFAULTS))
    result = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(value)}
    if not isinstance(result['enabled'], bool):
        raise ConfigError('enabled must be true or false')
    if result['order'] not in ORDERS:
        raise ConfigError('order must be one of ' + ', '.join(ORDERS))
    pip = result['pip']
    if not isinstance(pip, dict) or not set(pip) <= set(DEFAULTS['pip']):
        raise ConfigError('pip takes enabled, corner and size')
    pip = result['pip'] = {**DEFAULTS['pip'], **pip}
    if not isinstance(pip['enabled'], bool) or pip['corner'] not in CORNERS or pip['size'] not in SIZES:
        raise ConfigError('pip: enabled is true or false, corner one of ' + ', '.join(CORNERS)
                          + ', size one of ' + ', '.join(SIZES))
    card = result['card']
    if not isinstance(card, dict) or not set(card) <= set(DEFAULTS['card']):
        raise ConfigError('card takes text and image')
    card = result['card'] = {**DEFAULTS['card'], **card}
    card['text'] = validate_card_text(card['text'])
    image = card['image']
    if image is not None and (not isinstance(image, str) or not re.fullmatch(r'card-own-[0-9a-f]{8}\.(png|jpe?g|webp)', image)):
        raise ConfigError('card image must be an uploaded card')
    result['default_limit'] = validate_limit(result['default_limit'], 'default_limit')
    if result['limits_from'] is not None:
        result['limits_from'] = float(_number(result['limits_from'], 0, 4e9, 'limits_from'))
    ads = result['ads']
    if not isinstance(ads, list) or len(ads) > MAX_ADS:
        raise ConfigError(f'ads must list at most {MAX_ADS} ads')
    checked, seen = [], set()
    for ad in ads:
        try:
            ad = _validate_ad(ad, lenient)
        except ConfigError:
            if lenient:
                continue  # the worker plays the ads it can read
            raise
        if ad['id'] in seen:
            raise ConfigError('An ad is listed twice')
        seen.add(ad['id'])
        checked.append(ad)
    result['ads'] = checked
    return result


# ---------------------------------------------------------------- the rotation

def counted(plays, ad_id, since):
    """Plays of this ad since then that count towards its limit, oldest first."""
    return sorted(p['at'] for p in plays if p.get('kind', 'ad') == 'ad' and p.get('id') == ad_id
                  and played(p) and p.get('at', 0) >= since)


def allowed(ad, plays, now, since=None):
    """May this ad air now: switched on, and under its limit? since: the limits' reset
    (settings' limits_from); plays before it do not count."""
    if not ad.get('enabled'):
        return False
    limit = ad.get('limit')
    since = max(since or 0, ad.get('limits_from') or 0)
    return not limit or len(counted(plays, ad['id'], max(now - limit['minutes'] * 60, since))) < limit['count']


def allowed_again(ad, plays, now, since=None):
    """When an ad held back by its limit may air again (epoch seconds); None if it may now."""
    limit = ad.get('limit')
    if not limit:
        return None
    window = limit['minutes'] * 60
    times = counted(plays, ad['id'], max(now - window, since or 0, ad.get('limits_from') or 0))
    return times[len(times) - limit['count']] + window if len(times) >= limit['count'] else None


def counts(play_seconds, length):
    """A play counts towards a limit once 10 s of it has aired, or half of an ad under 20 s."""
    return play_seconds >= min(COUNTS_AFTER, length / 2)


def played(row):
    """Does a logged play count: as it was logged, or by the rule now (until 8 October 2026
    a play counted from half the ad), from what aired of it."""
    if row.get('counted'):
        return True
    seconds, length = row.get('seconds'), row.get('length')
    return (isinstance(seconds, (int, float)) and isinstance(length, (int, float)) and length > 0
            and counts(seconds, length))


class Rotation:
    """Which ad next. In list order: the one after the last that aired. Shuffled: a random
    order, each ad once before any airs again (a bag, refilled when empty, never starting
    with the ad that just aired). pick() only looks; played() commits. Master draws ahead
    (Next up, ad_break.py): played() as an ad is drawn, undraw() to put them back."""

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.bag = []
        self.last = None

    def pick(self, settings, plays, now, skip=()):
        ads = settings['ads']
        ok = {a['id']: a for a in ads if a['id'] not in skip and allowed(a, plays, now, settings.get('limits_from'))}
        if not ok:
            return None
        if settings['order'] == 'list':
            order = [a['id'] for a in ads]
            start = order.index(self.last) + 1 if self.last in order else 0
            return next(ok[order[(start + i) % len(order)]] for i in range(len(order))
                        if order[(start + i) % len(order)] in ok)
        self.bag = [i for i in self.bag if i in ok]
        if not self.bag:
            self.bag = [a['id'] for a in ads if a['id'] in ok]
            self.rng.shuffle(self.bag)
            if len(self.bag) > 1 and self.bag[0] == self.last:
                self.bag.append(self.bag.pop(0))
        return ok[self.bag[0]]

    def played(self, ad_id):
        self.last = ad_id
        if ad_id in self.bag:
            self.bag.remove(ad_id)

    def undraw(self, ids, last):
        """Puts ads drawn ahead (played, not aired) back: first in the bag, and list order
        resuming after last, the last that aired."""
        self.bag = list(ids) + [i for i in self.bag if i not in ids]
        self.last = last


# ---------------------------------------------------------------- the play log

def read_plays(path, since=0.):
    """Rows of my-ads-plays.jsonl from since on (epoch seconds), oldest first."""
    rows = []
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            start = max(0, size - 4 * 1024 * 1024)
            f.seek(start)
            lines = f.read().splitlines()[1 if start else 0:]
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get('at'), (int, float)) and row['at'] >= since:
            rows.append(row)
    return rows


def append_play(path, row):
    with open(path, 'a') as f:
        f.write(json.dumps(row) + '\n')


# ---------------------------------------------------------------- the store

def card_file(settings):
    """The break card's file in my-ads/: an uploaded image, or the station card for its text."""
    card = settings['card']
    if card['image']:
        return card['image']
    return 'card-' + hashlib.sha1(card['text'].encode()).hexdigest()[:10] + '.png'


class MyAds:
    def __init__(self, socket_path, *, lenient=False):
        base = Path(socket_path)
        self.path = base.with_name('my-ads.json')
        self.folder = base.with_name('my-ads')
        self.plays_path = base.with_name('my-ads-plays.jsonl')
        self.lenient = lenient
        self.lock = threading.RLock()

    def read(self):
        try:
            return validate(json.loads(self.path.read_text()), lenient=self.lenient)
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)

    def save(self, value):
        value = validate(value)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.my-ads-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(value, stream, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
        return value

    def _change(self, change):
        with self.lock:
            value = self.read()
            result = change(value)
            return self.save(value), result

    def update(self, changes):
        """Settings (not the ads): enabled, order, pip, card text, default_limit, limits_from
        ("now" resets the limits from this moment)."""
        if not isinstance(changes, dict) or not set(changes) <= set(DEFAULTS) - {'ads'}:
            raise ConfigError('Settings take ' + ', '.join(k for k in DEFAULTS if k != 'ads'))
        if changes.get('limits_from') == 'now':
            changes = {**changes, 'limits_from': round(time.time(), 1)}
        if 'card' in changes and (not isinstance(changes['card'], dict) or set(changes['card']) - {'text'}):
            raise ConfigError('Set the card text here; upload an image for a card of your own')

        def merge(value):
            for key, v in changes.items():
                value[key] = {**value[key], **v} if isinstance(value[key], dict) and isinstance(v, dict) else v
        return self._change(merge)[0]

    def _find(self, value, ad_id):
        ad = next((a for a in value['ads'] if a['id'] == ad_id), None)
        if ad is None:
            raise ConfigError('No such ad')
        return ad

    def edit(self, ad_id, changes):
        """One ad's name, enabled, limit, trim_db or limits_from ("now" resets its limit: plays
        before now stop counting)."""
        if (not isinstance(changes, dict) or not changes
                or not set(changes) <= {'name', 'enabled', 'limit', 'trim_db', 'limits_from'}):
            raise ConfigError('An ad takes name, enabled, limit, trim_db and limits_from')
        if changes.get('limits_from') == 'now':
            changes = {**changes, 'limits_from': round(time.time(), 1)}
        return self._change(lambda value: self._find(value, ad_id).update(changes))[0]

    def reorder(self, ids):
        def apply(value):
            if not isinstance(ids, list) or sorted(ids) != sorted(a['id'] for a in value['ads']):
                raise ConfigError('order takes every ad id, once each')
            by_id = {a['id']: a for a in value['ads']}
            value['ads'] = [by_id[i] for i in ids]
        return self._change(apply)[0]

    def shuffle(self, rng=random):
        """Puts the list in a random order (once; the rotation's own shuffle is the order setting)."""
        return self._change(lambda value: rng.shuffle(value['ads']))[0]

    def remove(self, ad_id):
        def apply(value):
            ad = self._find(value, ad_id)
            value['ads'].remove(ad)
            return ad
        value, ad = self._change(apply)
        (self.folder / ad['file']).unlink(missing_ok=True)
        for i in range(len(PICTURES)):
            (self.folder / f'{ad_id}-{i}.jpg').unlink(missing_ok=True)
        return value

    def add(self, upload, original_name, *, examine=None, pictures=None):
        """Takes an uploaded file (moved into my-ads/), checks it plays, takes its pictures and
        measures its loudness. A file that is not an ad is refused and deleted."""
        upload = Path(upload)
        ext = Path(original_name or '').suffix.lower()
        try:
            if ext not in VIDEO_EXT:
                raise ConfigError('Upload a video: ' + ' '.join(VIDEO_EXT))
            with self.lock:
                if len(self.read()['ads']) >= MAX_ADS:
                    raise ConfigError(f'My ads holds {MAX_ADS} ads at most')
            info = (examine or examine_video)(upload)
            ad_id = secrets.token_hex(6)
            self.folder.mkdir(parents=True, exist_ok=True)
            if info.get('heavy'):
                fitted = self.folder / f'.fit-{ad_id}.mp4'
                try:
                    fit(upload, fitted, info['duration'])
                    info = {**(examine or examine_video)(fitted), 'converted': True}
                except BaseException:
                    fitted.unlink(missing_ok=True)
                    raise
                upload.unlink(missing_ok=True)
                upload, ext = fitted, '.mp4'
            final = self.folder / (ad_id + ext)
            os.replace(upload, final)
        except BaseException:
            upload.unlink(missing_ok=True)
            raise
        stem = Path(original_name).stem
        name = ' '.join(re.sub(r'[_]+', ' ', stem).split())[:80]
        pics = (pictures or take_pictures)(final, info['duration'], self.folder, ad_id)
        ad = {**AD_DEFAULTS, 'id': ad_id, 'file': final.name, 'name': name, 'source_name': (original_name or '')[-120:],
              'duration': info['duration'], 'width': info['width'], 'height': info['height'], 'audio': info['audio'],
              'lufs': info.get('lufs'), 'gain_db': info.get('gain_db', 0.0), 'bytes': final.stat().st_size,
              'converted': bool(info.get('converted')),
              'added': round(time.time(), 1), 'pics': pics}
        try:
            def apply(value):
                ad['limit'] = value['default_limit']
                value['ads'].append(ad)
            return self._change(apply)[0], ad
        except BaseException:
            final.unlink(missing_ok=True)
            raise

    def set_card_image(self, upload, original_name):
        upload = Path(upload)
        ext = Path(original_name or '').suffix.lower()
        try:
            if ext not in IMAGE_EXT:
                raise ConfigError('The card must be a picture: ' + ' '.join(IMAGE_EXT))
            info = examine_image(upload)
            name = f'card-own-{secrets.token_hex(4)}{".jpg" if ext == ".jpeg" else ext}'
            self.folder.mkdir(parents=True, exist_ok=True)
            os.replace(upload, self.folder / name)
        except BaseException:
            upload.unlink(missing_ok=True)
            raise

        def apply(value):
            old = value['card']['image']
            value['card']['image'] = name
            return old
        value, old = self._change(apply)
        if old:
            (self.folder / old).unlink(missing_ok=True)
        return value, info

    def clear_card_image(self):
        def apply(value):
            old = value['card']['image']
            value['card']['image'] = None
            return old
        value, old = self._change(apply)
        if old:
            (self.folder / old).unlink(missing_ok=True)
        return value

    def card(self, settings=None):
        """The break card's file, rendered first if it is the station card and not drawn yet."""
        settings = settings or self.read()
        path = self.folder / card_file(settings)
        if not settings['card']['image'] and not path.exists():
            with self.lock:
                if not path.exists():
                    self.folder.mkdir(parents=True, exist_ok=True)
                    render_card(settings['card']['text'], path)
                    for old in self.folder.glob('card-*.png'):  # earlier wordings
                        if old != path and not old.name.startswith('card-own-'):
                            old.unlink(missing_ok=True)
        return path

    def plays(self, since=0.):
        return read_plays(self.plays_path, since)


# ---------------------------------------------------------------- upload checks (web app)

def _run(args, timeout):
    # Upload checks share the machine with master: lowest priority, one thread.
    return subprocess.run(['nice', '-n', '19', *args], capture_output=True, text=True, timeout=timeout)


def examine_video(path):
    """{duration, width, height, audio, lufs, gain_db} of a playable video, or ConfigError."""
    try:
        out = _run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_format', '-show_streams', str(path)], 60)
        data = json.loads(out.stdout or '{}')
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(f'Could not read that file: {exc}') from exc
    streams = data.get('streams') or []
    video = next((s for s in streams if s.get('codec_type') == 'video'
                  and not (s.get('disposition') or {}).get('attached_pic')), None)
    if video is None:
        raise ConfigError('That file has no picture' if streams else 'That is not a video file')
    try:
        duration = float((data.get('format') or {}).get('duration') or video.get('duration') or 0)
    except ValueError:
        duration = 0
    if duration < 1:
        raise ConfigError('That video is shorter than a second')
    if duration > MAX_SECONDS:
        raise ConfigError(f'Ads are at most {MAX_SECONDS // 60} minutes long')
    width, height = video.get('width') or 0, video.get('height') or 0
    info = {'duration': round(duration, 3), 'width': width or None, 'height': height or None,
            'audio': any(s.get('codec_type') == 'audio' for s in streams), 'lufs': None, 'gain_db': 0.0,
            'heavy': width * height * min(_rate(video), 120) > HEAVY}
    if info['audio']:
        info.update(measure_loudness(path, duration))
    return info


def _rate(stream):
    for key in ('avg_frame_rate', 'r_frame_rate'):
        try:
            n, d = (stream.get(key) or '0/0').split('/')
            if float(n) and float(d):
                return float(n) / float(d)
        except ValueError:
            pass
    return 30.


def fit(path, out, duration):
    """A copy master decodes easily: at most 1280x720, H.264 and AAC, its own frame rate."""
    try:
        result = _run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-threads', '2', '-i', str(path),
                       '-map', '0:v:0', '-map', '0:a:0?', '-vf',
                       'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2',
                       '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
                       '-c:a', 'aac', '-b:a', '192k', '-ac', '2', '-movflags', '+faststart', '-y', str(out)],
                      max(180, duration * 30))
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(f'Could not convert that video to 720p: {exc}') from exc
    if result.returncode or not out.exists():
        raise ConfigError('Could not convert that video to 720p: ' + (result.stderr or '').strip()[-200:])


def measure_loudness(path, duration):
    """Integrated loudness and true peak (EBU R 128) -> the gain that levels it to LOUDNESS."""
    try:  # framelog=verbose: the per-frame lines stay below ffmpeg's log level, the summary does not
        result = _run(['ffmpeg', '-hide_banner', '-nostats', '-threads', '1', '-i', str(path), '-vn',
                       '-af', 'ebur128=peak=true:framelog=verbose', '-f', 'null', '-'], max(60, duration * 2))
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode:
        return {}       # unmeasured: aired as it is
    out = result.stderr
    summary = out[out.rfind('Summary:'):] if 'Summary:' in out else ''
    lufs = re.search(r'I:\s+(-?[\d.]+) LUFS', summary)
    peak = re.search(r'Peak:\s+(-?[\d.]+|-inf) dBFS', summary)
    if not lufs or float(lufs[1]) <= -69:
        return {}       # silent: nothing to level
    gain = LOUDNESS - float(lufs[1])
    if peak and peak[1] != '-inf':
        gain = min(gain, TRUE_PEAK - float(peak[1]))
    return {'lufs': round(float(lufs[1]), 1), 'gain_db': round(min(GAIN_DB[1], max(GAIN_DB[0], gain)), 1)}


def take_pictures(path, duration, folder, ad_id):
    """Four pictures through the ad, as the Ad database has: <id>-<n>.jpg."""
    w, h = PICTURE_SIZE
    count = 0
    for i, at in enumerate(PICTURES):
        out = folder / f'{ad_id}-{i}.jpg'
        try:
            _run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-threads', '1', '-ss', f'{duration * at:.2f}',
                  '-i', str(path), '-frames:v', '1', '-vf',
                  f'scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2',
                  '-q:v', '4', '-y', str(out)], 30)
        except (OSError, subprocess.TimeoutExpired):
            pass
        if out.exists() and out.stat().st_size:
            count = i + 1
        else:
            break
    return count


def examine_image(path):
    try:
        out = _run(['ffprobe', '-v', 'error', '-print_format', 'json', '-show_streams', str(path)], 30)
        streams = json.loads(out.stdout or '{}').get('streams') or []
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ConfigError(f'Could not read that picture: {exc}') from exc
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    if not video or not video.get('width'):
        raise ConfigError('That is not a picture')
    return {'width': video['width'], 'height': video.get('height')}


# ---------------------------------------------------------------- the station card (web app)

_ANIMATION = None
_ANIMATION_LOCK = threading.Lock()


def render_card(text, out):
    """The station ID's end card, its banner reading text, as a 1280x720 PNG."""
    global _ANIMATION
    with _ANIMATION_LOCK:
        if _ANIMATION is None:
            saved = list(sys.path)
            try:  # animation.py finds its timeline beside it (and puts ident/ on sys.path for that)
                spec = importlib.util.spec_from_file_location('vizelvision_ident_animation', IDENT / 'animation.py')
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            finally:
                sys.path[:] = saved
            _ANIMATION = module
        _ANIMATION.TAGLINE_TEXT = text
        out = Path(out)
        part = out.with_name('.' + out.name)
        _ANIMATION.still(CARD_AT, part)
        os.replace(part, out)


def copy_upload(stream, length, folder, suffix, limit):
    """Streams a request body of length bytes into a temporary file in folder."""
    if length <= 0 or length > limit:
        raise ConfigError(f'Uploads are 1 byte to {limit // 1_000_000:,} MB')
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < length + 2 * 1024 ** 3:
        raise ConfigError('Not enough disk space for that upload')
    fd, name = tempfile.mkstemp(prefix='.upload-', suffix=suffix, dir=folder)
    try:
        with os.fdopen(fd, 'wb') as f:
            left = length
            while left:
                chunk = stream.read(min(1 << 20, left))
                if not chunk:
                    raise ConfigError('The upload stopped before the end')
                f.write(chunk)
                left -= len(chunk)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)
