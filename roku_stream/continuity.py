"""Continuity announcements, in the style of BBC continuity: at each break the duty
announcer says what just played and what is next, over the station ID.

The ID's picture and music stay; for that break its voice-over is replaced by the
announcer's lines, placed in the ID's voice slots and ending before its end card:

    That was {just_played}. / You're watching Vizel Vision. / Coming up: {up_next}. / Stay tuned.

What just played and what is next come from the playback projection (playback.py), so
they follow the queue's rules: a game under way, Up next recordings, or the schedule.
Each line is voiced once with Deepgram Aura in the announcer's voice and kept by voice
and text. ffmpeg levels each line as the ID levels its own, mixes them over the ID's
music bed (ident/build/music.wav), ducking the music 7 dB under the voice, levels the
result to -20 LUFS like the ID, and copies the ID's picture unchanged. The master worker cues that file for the next ID
only (`ident_file`), then returns to the plain ID.

The break before a sporting event is two IDs in one file: first the announcement (or the
plain ID when announcements are off) saying what is next, then the VizelVision Sports ID
("The following... is a presentation of Vizel Vision Sports."). Its end card at 27.9 s
holds while the game's source is prepared, so the Sports ID opens the game once it is
ready. It plays even from the test card, and is cued the same way, from the announcements
folder (sports-<hash>.mp4); the source coordinator starts it from the test card.

Each ID that airs (master's last_station_id) is logged in ident-plays.jsonl, beside the
settings, kind "station" or "sports" (a sports break), for the Idents page's counts.

Nothing here touches another station's code or data: the personalities are settings,
the voices are Deepgram's.
"""
from __future__ import annotations

import copy
from datetime import datetime
import hashlib
import http.client
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import wave

from .errors import ConfigError
from .ident import IDENT_PATH, SPORTS_IDENT_PATH, SPORTS_PREFIX, file_identity
from .my_ads import PlayTally, append_play, read_plays

MUSIC_PATH = IDENT_PATH.parent / 'build' / 'music.wav'
# The ID's voice slots (ident/script.json); the last word ends before its end card (27.9 s).
SLOTS = (7.8, 12.9, 16.9, 21.2)
LAST_WORD = 27.4
GAP = 0.3
LOUDNESS, TRUE_PEAK = -20.0, -2.0   # As the ID (ident/build.py).
# Each line against the music bed, and the music under it, as in the ID (ident/jingle.py):
# its lines measure -19 to -20.4 LUFS over music.wav, which ducks 7 dB under them. Deepgram's
# lines come back anywhere from -19 to -28 LUFS, so each one is measured and levelled.
VOICE_LOUDNESS, DUCK_DB = -20.0, 7.0
MIX_VERSION = 2   # In each announcement's name: a change to the mix remixes those already made.
_LINE = ('aformat=sample_rates=48000:channel_layouts=mono,'
         'silenceremove=start_periods=1:start_threshold=-42dB,highpass=f=85')
DEFAULT_LINES = ("That was {just_played}.", "You're watching Vizel Vision.",
                 "Coming up: {up_next}.", "Stay tuned.")
FRENCH_LINES = ("C'était {just_played}.", "Vous regardez Vizel Vision.", "À suivre : {up_next}.", "Restez avec nous.")
FIELDS = ('just_played', 'up_next')
# Cairo Radio's on-air shifts (its public log, 30 September 2026): the duty roster starts
# from them, so VizelVision's announcer is the one hosting Cairo at that hour.
CAIRO_SHIFTS = ((0, 9, 'low-tide'), (9, 11, 'daytime-announcer'), (11, 13, 'amelie'), (13, 18, 'low-tide'),
                (18, 19, 'daytime-announcer'), (19, 23, 'low-tide'), (23, 24, 'amelie'))
# Deepgram Aura-2 voices when its catalogue cannot be read (Voice.catalogue lists them all).
VOICES = ('aura-2-agathe-fr', 'aura-2-hector-fr', 'aura-2-orpheus-en', 'aura-2-thalia-en', 'aura-2-andromeda-en', 'aura-2-helena-en', 'aura-2-apollo-en',
          'aura-2-arcas-en', 'aura-2-aries-en', 'aura-2-asteria-en', 'aura-2-athena-en', 'aura-2-atlas-en',
          'aura-2-aurora-en', 'aura-2-callista-en', 'aura-2-cora-en', 'aura-2-cordelia-en', 'aura-2-delia-en',
          'aura-2-draco-en', 'aura-2-electra-en', 'aura-2-harmonia-en', 'aura-2-hera-en', 'aura-2-hermes-en',
          'aura-2-hyperion-en', 'aura-2-iris-en', 'aura-2-janus-en', 'aura-2-juno-en', 'aura-2-jupiter-en',
          'aura-2-luna-en', 'aura-2-mars-en', 'aura-2-minerva-en', 'aura-2-neptune-en', 'aura-2-odysseus-en',
          'aura-2-ophelia-en', 'aura-2-orion-en', 'aura-2-pandora-en', 'aura-2-phoebe-en', 'aura-2-pluto-en',
          'aura-2-saturn-en', 'aura-2-selene-en', 'aura-2-theia-en', 'aura-2-vesta-en', 'aura-2-zeus-en')
_MODEL = re.compile(r'^aura(-2)?-[a-z]+-[a-z]{2}$')
_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,39}$')
_FIELD = re.compile(r'\{([^{}]*)\}')
_FILE = re.compile(r'^(sports-)?[0-9a-f]{16,64}\.(mp4|wav)$')
SPORTS_NAME = 'VizelVision Sports'
SPORTS_LINE = 'The following is a presentation of VizelVision Sports.'
SAMPLE = {'en': {'just_played': 'the Phillies and the Braves', 'up_next': 'the White Sox and the Astros'},
          'fr': {'just_played': 'les Phillies et les Braves', 'up_next': 'les White Sox et les Astros'}}


def language(model):
    """A voice's language, from its name: aura-2-agathe-fr is French."""
    return str(model).rsplit('-', 1)[-1]


def defaults():
    """Cairo Radio's three on-air personalities, on a roster that follows Cairo's shifts.
    DJ Low Tide also voices the station ID."""
    roster = [next(who for start, end, who in CAIRO_SHIFTS if start <= hour < end) for hour in range(24)]
    return {'version': 1, 'enabled': False, 'on_duty': 'low-tide', 'duty': 'roster', 'roster': roster,
            'announcers': [
                {'id': 'low-tide', 'name': 'DJ Low Tide', 'model': 'aura-2-orpheus-en',
                 'style': "Cairo Radio's host for The Old Rock Show, Classical and Daytime Alt, and the voice "
                          'of the station ID. Easygoing, late-night warmth.',
                 'lines': list(DEFAULT_LINES)},
                {'id': 'daytime-announcer', 'name': 'The Daytime Announcer', 'model': 'aura-2-zeus-en',
                 'style': "Cairo Radio's Morning Show announcer. Deep, clear and unhurried: classic network "
                          'continuity.',
                 'lines': ["You've been watching {just_played}.", "This is Vizel Vision.",
                           'Next: {up_next}.', 'Stay with us.']},
                {'id': 'amelie', 'name': 'Amélie', 'model': 'aura-2-agathe-fr',
                 'style': "Cairo Radio's host for L'heure québécoise. Speaks French: bright, charming, "
                          'a little mischievous.',
                 'lines': list(FRENCH_LINES)}]}


def _text(value, name, limit):
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ConfigError(f'{name} must be a single line of at most {limit} characters')
    return value.strip()


def validate(value):
    if not isinstance(value, dict) or not isinstance(value.get('enabled'), bool):
        raise ConfigError('Continuity settings need enabled (true or false) and announcers')
    announcers = value.get('announcers')
    if not isinstance(announcers, list) or not 1 <= len(announcers) <= 12:
        raise ConfigError('announcers must list 1 to 12 personalities')
    result = []
    for raw in announcers:
        if not isinstance(raw, dict):
            raise ConfigError('Each announcer must be an object')
        announcer_id = raw.get('id') or re.sub(r'[^a-z0-9]+', '-', str(raw.get('name', '')).lower()).strip('-')[:40]
        if not isinstance(announcer_id, str) or not _ID.match(announcer_id):
            raise ConfigError('Announcer id must be lowercase letters, digits and hyphens')
        model = raw.get('model')
        if not isinstance(model, str) or not _MODEL.match(model):
            raise ConfigError('voice must be a Deepgram Aura voice, such as aura-2-orpheus-en')
        lines = raw.get('lines') or list(DEFAULT_LINES)
        if not isinstance(lines, list) or not 1 <= len(lines) <= len(SLOTS):
            raise ConfigError(f'An announcer has 1 to {len(SLOTS)} lines')
        lines = [_text(line, 'Each line', 120) for line in lines]
        for line in lines:
            unknown = set(_FIELD.findall(line)) - set(FIELDS)
            if unknown:
                raise ConfigError('Lines may use {just_played} and {up_next} only, not {' + sorted(unknown)[0] + '}')
        style = raw.get('style') or ''
        if not isinstance(style, str) or len(style) > 280:
            raise ConfigError('Style notes must be at most 280 characters')
        result.append({'id': announcer_id, 'name': _text(raw.get('name'), 'Announcer name', 40), 'model': model,
                       'style': style.strip(), 'lines': lines})
    ids = [a['id'] for a in result]
    if len(set(ids)) != len(ids):
        raise ConfigError('Announcer names must be different')
    on_duty = value.get('on_duty') or ids[0]
    if on_duty not in ids:
        raise ConfigError('The announcer on duty must be one of the personalities')
    duty = value.get('duty', 'fixed')
    if duty not in ('fixed', 'roster'):
        raise ConfigError('duty must be fixed or roster')
    roster = value.get('roster') or [None] * 24
    if not isinstance(roster, list) or len(roster) != 24:
        raise ConfigError('The roster has one entry for each hour of the day')
    # An hour whose announcer is gone falls back to the one on duty.
    roster = [who if who in ids else None for who in roster]
    return {'version': 1, 'enabled': value['enabled'], 'on_duty': on_duty, 'duty': duty, 'roster': roster,
            'announcers': result}


def is_game(segment):
    """A sporting event in the projection: a game show on the schedule, or an entry that
    carries its game (a game's backup carries only after_game)."""
    return bool(segment) and (segment.get('kind') == 'game' or bool(segment.get('game')))


def off_air(segment):
    return (segment is None or segment.get('kind') == 'off_air'
            or (segment.get('target') or {}).get('source_id') == 'off-air')


def script(lines, just_played, up_next):
    """The lines to say: a line naming something unknown (nothing next) is left out."""
    known = {'just_played': just_played, 'up_next': up_next}
    return [line.format(**known) for line in lines if all(known.get(f) for f in _FIELD.findall(line))]


def place(lengths):
    """Start times for lines of these lengths: on the ID's voice slots when they fit, else
    closer together from the first slot. None when they cannot end before the end card."""
    starts, end = [], 0.0
    for index, length in enumerate(lengths):
        slot = SLOTS[index] if index < len(SLOTS) else SLOTS[-1]
        start = max(slot, end + GAP) if index else slot
        starts.append(start)
        end = start + length
    if end <= LAST_WORD:
        return starts
    starts, end = [], SLOTS[0] - 1.0
    for length in lengths:
        starts.append(end + GAP if starts else end)
        end = starts[-1] + length
    return starts if end <= LAST_WORD else None


def seconds(path):
    """The length of the audio present: Deepgram streams its WAV with a placeholder size."""
    with wave.open(str(path)) as audio:
        frame = audio.getsampwidth() * audio.getnchannels()
        return len(audio.readframes(audio.getnframes())) // frame / audio.getframerate()


class Voice:
    """Deepgram Aura text to speech. Each line is voiced once and kept by voice and text.
    The key comes from DEEPGRAM_API_KEY or the configured keys file; it is never logged."""
    ATTEMPTS = 3

    def __init__(self, cache_dir, keys_file=None, opener=urllib.request.urlopen):
        self.cache_dir, self.keys_file, self.opener = Path(cache_dir), keys_file, opener

    def key(self):
        key = os.environ.get('DEEPGRAM_API_KEY')
        if not key and self.keys_file:
            try:
                for line in Path(self.keys_file).read_text().splitlines():
                    name, _, value = line.strip().removeprefix('export ').partition('=')
                    if name.strip() == 'DEEPGRAM_API_KEY':
                        key = value.strip().strip('"\'')
            except OSError:
                key = None
        return key or None

    def available(self):
        return self.key() is not None

    def catalogue(self):
        """Deepgram's Aura-2 voices with language, accent and character; read once a day."""
        if getattr(self, '_catalogue', None) and time.monotonic() < self._catalogue[0]:
            return self._catalogue[1]
        voices = [{'id': v, 'language': language(v), 'accent': None, 'tags': []} for v in VOICES]
        key = self.key()
        if key:
            try:
                request = urllib.request.Request('https://api.deepgram.com/v1/models',
                                                 headers={'Authorization': f'Token {key}'})
                with self.opener(request, timeout=15) as response:
                    models = json.loads(response.read())
                found = [{'id': m['canonical_name'], 'language': language(m['canonical_name']),
                          'accent': (m.get('metadata') or {}).get('accent'),
                          'tags': list((m.get('metadata') or {}).get('tags') or [])[:5]}
                         for m in models.get('tts', []) if str(m.get('canonical_name', '')).startswith('aura-2-')]
                if found:
                    voices = sorted({v['id']: v for v in found}.values(), key=lambda v: (v['language'] != 'en', v['language'], v['id']))
            except (OSError, ValueError, KeyError, urllib.error.URLError):
                pass  # The built-in list stands in.
        self._catalogue = (time.monotonic() + 86400, voices)
        return voices

    def line(self, model, text):
        path = self.cache_dir / (hashlib.sha256(f'{model}\n{text}'.encode()).hexdigest()[:32] + '.wav')
        if path.exists():
            return path
        key = self.key()
        if not key:
            raise ConfigError('No Deepgram key: set continuity.keys_file or DEEPGRAM_API_KEY')
        request = urllib.request.Request(
            f'https://api.deepgram.com/v1/speak?model={model}&encoding=linear16&container=wav&sample_rate=48000',
            data=json.dumps({'text': text}).encode(),
            headers={'Authorization': f'Token {key}', 'Content-Type': 'application/json'})
        for attempt in range(self.ATTEMPTS):
            try:
                with self.opener(request, timeout=30) as response:
                    audio = response.read()
                    declared = response.headers.get('Content-Length')
                if declared and len(audio) < int(declared):  # A dropped stream cuts a word off.
                    raise http.client.IncompleteRead(audio, int(declared) - len(audio))
                break
            except urllib.error.HTTPError as exc:
                raise ConfigError(f'Deepgram refused the line ({exc.code})') from None
            except (http.client.IncompleteRead, ConnectionResetError, TimeoutError, urllib.error.URLError) as exc:
                if attempt == self.ATTEMPTS - 1:
                    raise ConfigError(f'Deepgram did not answer: {exc}') from None
                time.sleep(1 + attempt)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix('.part')
        partial.write_bytes(audio)
        partial.replace(path)
        return path


def _ffmpeg(*args):
    result = subprocess.run(['ffmpeg', '-hide_banner', '-nostats', *args], capture_output=True, text=True)
    if result.returncode:
        lines = result.stderr.strip().splitlines()
        reason = next((line for line in lines if re.search(r'Cannot|Invalid|Error|No such', line)), lines[-1] if lines else '')
        raise ConfigError('ffmpeg could not mix the announcement: ' + reason.strip()[:200])
    return result.stderr


def loudness(path):
    """A voiced line's loudness (LUFS) as it goes into the mix: trimmed and filtered. A
    line shorter than the meter's 400 ms window is padded so it still reads."""
    report = _ffmpeg('-i', str(path), '-af', f'{_LINE},apad=whole_dur=0.5,ebur128', '-f', 'null', '-')
    found = re.search(r'Integrated loudness:\s*I:\s*(-?[\d.]+|-inf) LUFS', report[report.rfind('Summary:'):])
    if not found or found.group(1) == '-inf' or float(found.group(1)) < -60:
        raise ConfigError('Deepgram returned a silent line')
    return float(found.group(1))


def duck(spans, down=0.3, up=0.45):
    """The music's gain over time, an ffmpeg expression: DUCK_DB under each line
    [(start, end)], easing down to it by the first word and back up after the last."""
    amount = None
    for start, end in spans:
        line = f'clip(min((t-({start - down:.3f}))/{down},({end + up:.3f}-t)/{up}),0,1)'
        amount = line if amount is None else f'max({amount},{line})'
    return f'pow(10,-{DUCK_DB}*(0.5-0.5*cos(PI*{amount}))/20)'


def mix(voiced, out, *, music=MUSIC_PATH, video=None, length=30.0):
    """Lines [(wav, start seconds)] over the ID's music: each line levelled as the ID's
    are, the music ducked under them, the whole levelled to -20 LUFS in two passes like the
    ID. With video, the ID's picture is copied and an .mp4 written; without it, a .wav (a
    preview). length: the music's (the ID's 30 s; a station promo's own, promos.py)."""
    inputs = ['-i', str(music)]
    chains, labels = [], []
    for index, (path, start) in enumerate(voiced, 1):
        inputs += ['-i', str(path)]
        # Both channels at full level, as the ID places its voice.
        chains.append(f'[{index}:a]{_LINE},volume={VOICE_LOUDNESS - loudness(path):.2f}dB,'
                      f'adelay={int(start * 1000)}:all=1,pan=stereo|c0=c0|c1=c0[v{index}]')
        labels.append(f'[v{index}]')
    spans = [(start, start + seconds(path)) for path, start in voiced]
    graph = ';'.join(chains + [
        f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:dropout_transition=0,apad=whole_dur={length:g}[voice]",
        # music.wav is the ID's music at the ID's level, so it goes in as it is. Small
        # frames keep the duck's gain changes smooth.
        '[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,asetnsamples=n=256,'
        f"volume='{duck(spans)}':eval=frame[ducked]",
        f'[ducked][voice]amix=inputs=2:normalize=0,atrim=0:{length:g}[mix]'])
    with tempfile.TemporaryDirectory(prefix='vv-continuity-') as work:
        dry = Path(work) / 'mix.wav'
        _ffmpeg('-y', *inputs, '-filter_complex', graph, '-map', '[mix]', '-c:a', 'pcm_f32le', str(dry))
        report = _ffmpeg('-i', str(dry), '-af', f'loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA=11:print_format=json',
                         '-f', 'null', '-')
        m = json.loads(report[report.rindex('{'):report.rindex('}') + 1])
        level = ('aformat=channel_layouts=stereo,'
                 f"loudnorm=I={LOUDNESS}:TP={TRUE_PEAK}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
                 f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:"
                 'linear=true,aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo')
        partial = Path(out).with_name(Path(out).stem + '.part' + Path(out).suffix)
        if video:
            _ffmpeg('-y', '-i', str(dry), '-i', str(video), '-map', '1:v', '-map', '0:a', '-af', level,
                    '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', '-movflags', '+faststart',
                    str(partial))
        else:
            _ffmpeg('-y', '-i', str(dry), '-af', level, '-c:a', 'pcm_s16le', str(partial))
        partial.replace(out)
    return Path(out)


def join(first, second, out):
    """Two IDs back to back as one file (the break before a game: what is next, then the
    Sports ID). Both have the ID's form and encoding, so the picture is copied; the sound is
    encoded again so the seam is clean."""
    with tempfile.TemporaryDirectory(prefix='vv-continuity-') as work:
        listing = Path(work) / 'parts.txt'
        listing.write_text(''.join("file '{}'\n".format(str(Path(p).resolve()).replace("'", "'\\''"))
                                   for p in (first, second)))
        partial = Path(out).with_name(Path(out).stem + '.part' + Path(out).suffix)
        _ffmpeg('-y', '-f', 'concat', '-safe', '0', '-i', str(listing), '-c:v', 'copy', '-c:a', 'aac',
                '-b:a', '192k', '-movflags', '+faststart', str(partial))
        partial.replace(out)
    return Path(out)


class Continuity:
    """Keeps the next break's announcement cued on master. project() returns the playback
    projection's segments; spoken(segment) names a program as the announcer says it;
    master is the worker client (ident_file, status)."""
    KEEP = 16

    def __init__(self, state_file, work_dir, *, voice, project, spoken, master, video=IDENT_PATH,
                 music=MUSIC_PATH, sports=SPORTS_IDENT_PATH, poll_seconds=20, start_worker=True):
        self.path, self.work_dir = Path(state_file), Path(work_dir)
        self.voice, self.project, self.spoken, self.master = voice, project, spoken, master
        self.video, self.music, self.poll_seconds = Path(video), Path(music), poll_seconds
        self.sports = Path(sports)
        self.lock = threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.closed = False
        self.data = self._load()
        self.next = None      # The announcement cued for the next break.
        self.recent = []      # Announcements rendered, newest first, with when they aired.
        self.error = None
        self.sent = None      # The file the worker was last given.
        self.aired_path = self.path.with_name('ident-plays.jsonl')
        self.tally = PlayTally(self.aired_path, lambda row: row['kind'] if row.get('kind') in ('station', 'sports') else None)
        self.logged = max((row['at'] for row in read_plays(self.aired_path)), default=0.)
        self.thread = None
        if start_worker:
            self.start()

    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='continuity', daemon=True)
            self.thread.start()

    # Settings --------------------------------------------------------------
    def _load(self):
        try:
            return validate(json.loads(self.path.read_text()))
        except FileNotFoundError:
            return defaults()
        except (OSError, ValueError, ConfigError) as exc:
            logging.getLogger(__name__).warning('Continuity settings unreadable, using defaults: %s', exc)
            return defaults()

    def settings(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def save(self, value):
        value = validate(value)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            partial = self.path.with_suffix('.part')
            partial.write_text(json.dumps(value, indent=2) + '\n')
            partial.replace(self.path)
            self.data = value
            self.wake.notify_all()
        return self.status()

    def played(self):
        """How often each ID aired: all time (since the log began) and in the last day. A sports
        break is the station ID then the Sports ID, so it counts for both."""
        counts, since = self.tally.read()
        day = [row['kind'] for row in read_plays(self.aired_path, time.time() - 86400)]
        return {'station': {'total': counts.get('station', 0) + counts.get('sports', 0), 'day': len(day)},
                'sports': {'total': counts.get('sports', 0), 'day': day.count('sports')}, 'since': since}

    def status(self):
        voices = self.voice.catalogue()
        on_duty = self._announcer()
        played = self.played()
        with self.lock:
            return {'settings': copy.deepcopy(self.data), 'next': copy.deepcopy(self.next),
                    'recent': copy.deepcopy(self.recent), 'played': played, 'error': self.error, 'voices': voices,
                    'fields': list(FIELDS), 'default_lines': {'en': list(DEFAULT_LINES), 'fr': list(FRENCH_LINES)},
                    'on_duty_now': on_duty['id'] if on_duty else None, 'hour': time.localtime().tm_hour,
                    'ready': {'key': self.voice.available(), 'music': self.music.is_file(), 'id': self.video.is_file(),
                              'sports': self.sports.is_file()}}

    def _announcer(self, announcer_id=None, at=None):
        """A personality by id, or the one on duty at a moment (now): the roster's for that
        hour, else the announcer on duty."""
        with self.lock:
            wanted = announcer_id
            if wanted is None:
                hour = time.localtime(at).tm_hour if at is not None else time.localtime().tm_hour
                wanted = (self.data['roster'][hour] if self.data.get('duty') == 'roster' else None) or self.data['on_duty']
            return copy.deepcopy(next((a for a in self.data['announcers'] if a['id'] == wanted), None))

    def _names(self, context, announcer):
        """What just played and what is next, as this announcer says them."""
        current, following, _ = context
        lang = language(announcer['model'])
        return self.spoken(current, lang), (self.spoken(following, lang) if following else None)

    # Rendering -------------------------------------------------------------
    def _voiced(self, announcer, just_played, up_next):
        lines = script(announcer['lines'], just_played, up_next)
        if not lines:
            raise ConfigError('Nothing to say: every line needs something unknown')
        paths = [self.voice.line(announcer['model'], line) for line in lines]
        starts = place([seconds(p) for p in paths])
        if starts is None:
            raise ConfigError('The lines are too long to end before the end card; shorten them')
        return lines, list(zip(paths, starts))

    def render(self, announcer, just_played, up_next, *, preview=False):
        """An announcement file: the ID with these lines (.mp4), or its sound alone (.wav)."""
        lines, voiced = self._voiced(announcer, just_played, up_next)
        key = hashlib.sha256(json.dumps([announcer['model'], lines, file_identity(self.video),
                                         file_identity(self.music), preview, MIX_VERSION]).encode()).hexdigest()[:32]
        out = self.work_dir / (key + ('.wav' if preview else '.mp4'))
        if not out.exists():
            self.work_dir.mkdir(parents=True, exist_ok=True)
            mix(voiced, out, music=self.music, video=None if preview else self.video)
        return lines, out

    def preview(self, announcer_id=None, just_played=None, up_next=None):
        """Hear an announcer, saved (an id) or being edited (an object): the lines they would
        say at the next break, or for a sample one, over the music."""
        if isinstance(announcer_id, dict):
            announcer = validate({'enabled': False, 'announcers': [announcer_id]})['announcers'][0]
        else:
            announcer = self._announcer(announcer_id)
        if announcer is None:
            raise ConfigError('Unknown announcer')
        if just_played is None:
            context = self.context()
            sample = SAMPLE.get(language(announcer['model']), SAMPLE['en'])
            just_played, up_next = (self._names(context, announcer) if context
                                    else (sample['just_played'], sample['up_next']))
        lines, out = self.render(announcer, just_played, up_next, preview=True)
        self._tidy()
        return {'announcer': announcer['id'], 'lines': lines, 'audio': out.name}

    def audio(self, name):
        if not isinstance(name, str) or not _FILE.match(name):
            raise ConfigError('Unknown announcement')
        path = self.work_dir / name
        if not path.is_file():
            raise ConfigError('Unknown announcement')
        return path

    def _tidy(self):
        """Keep the newest announcements and previews; the voice cache stays."""
        files = sorted((p for p in self.work_dir.glob('*') if p.is_file() and _FILE.match(p.name)),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        keep = {Path(self.sent).name} if self.sent else set()
        for path in files[self.KEEP:]:
            if path.name not in keep:
                path.unlink(missing_ok=True)

    # The next break -----------------------------------------------------------
    def segments(self):
        """The projection from now, without station IDs; None when it is unavailable."""
        try:
            segments = self.project()
        except Exception as exc:
            logging.getLogger(__name__).warning('Continuity has no projection: %s', exc)
            return None
        return [s for s in segments if s.get('kind') != 'ident']

    @staticmethod
    def _break_at(segment):
        try:
            return datetime.fromisoformat(segment['end']).timestamp()
        except (KeyError, TypeError, ValueError):
            return None

    def context(self, segments=None):
        """(what is on now, what follows or None before OFF AIR, when the break comes as a
        timestamp) from the projection; None when the ID will not play (nothing on air) or
        the projection is unavailable."""
        segments = self.segments() if segments is None else segments
        if not segments or off_air(segments[0]):
            return None
        following = segments[1] if len(segments) > 1 else None
        return segments[0], None if off_air(following) else following, self._break_at(segments[0])

    def step(self):
        """Cue the sports break (what is next, then the Sports ID) when the next break leads
        into a game; else the announcement for the next break, or the plain ID when
        continuity is off."""
        self._check_master()
        segments = self.segments()
        if segments is None:
            return  # Unknown: keep whatever is cued.
        if self._cue_sports(segments):
            return
        with self.lock:
            enabled = self.data['enabled']
        if not enabled:
            if self.sent:
                self._send(None)
            return
        context = self.context(segments)
        # Whoever is on duty when the break comes: a roster follows Cairo Radio's shifts.
        announcer = self._announcer(at=context[2]) if context else None
        names = self._names(context, announcer) if context and announcer else None
        if not names or not names[0]:
            return
        try:
            lines, out = self.render(announcer, *names)
        except (ConfigError, OSError) as exc:
            with self.lock:
                self.error = str(exc)
            return
        with self.lock:
            self.error = None
            if not self.next or self.next['file'] != out.name:
                self.next = {'id': uuid.uuid4().hex, 'file': out.name, 'announcer': announcer['id'],
                             'name': announcer['name'], 'lines': lines, 'just_played': names[0],
                             'up_next': names[1], 'at': time.time(), 'break_at': context[2], 'aired_at': None}
        if self.sent != str(out):
            self._send(out)
        self._tidy()

    # The Sports ID ------------------------------------------------------------
    def _sports_break(self, segments):
        """(what is on now, the game) when the next break leads into a sporting event,
        from a program or from the test card; else None."""
        if len(segments) < 2 or not is_game(segments[1]) or not self.sports.is_file():
            return None
        current, game = segments[0], segments[1]
        same = (current.get('game') or {}).get('game_pk')
        if same is not None and same == (game.get('game') or {}).get('game_pk'):
            return None  # The same game carrying on: no break.
        return current, game

    def _lead_in(self, current, game, break_at):
        """The sports break's first half: (file, announcer or None, lines, problem). With
        announcements on, the announcer on duty says what just played (nothing after the test
        card) and which game is next; otherwise, or when that cannot be voiced, the plain ID."""
        with self.lock:
            enabled = self.data['enabled']
        announcer = self._announcer(at=break_at) if enabled else None
        if announcer is None:
            return self.video, None, [], None
        lang = language(announcer['model'])
        try:
            lines, out = self.render(announcer, None if off_air(current) else self.spoken(current, lang),
                                     self.spoken(game, lang))
        except (ConfigError, OSError) as exc:
            return self.video, None, [], f'The plain ID leads into the Sports ID: {exc}'
        return out, announcer, lines, None

    def _sports_file(self, lead):
        """The sports break: lead (the announcement or the plain ID), then the Sports ID, as one
        file in the announcements folder the worker plays from. Its name changes with either
        part, so a new announcement or a rebuilt ID is joined again."""
        # An announcement's name already says what it is; the plain ID is known by its identity.
        parts = json.dumps([file_identity(lead) if lead == self.video else lead.name, file_identity(self.sports)])
        out = self.work_dir / (SPORTS_PREFIX + hashlib.sha256(parts.encode()).hexdigest()[:16] + '.mp4')
        if not out.exists():
            self.work_dir.mkdir(parents=True, exist_ok=True)
            join(lead, self.sports, out)
        return out

    def _cue_sports(self, segments):
        """Cue the sports break when the next break opens a game. False otherwise (or when it
        cannot be cued), and the break gets its announcement or the plain ID."""
        found = self._sports_break(segments)
        if not found:
            return False
        current, game = found
        break_at = self._break_at(current)
        lead, announcer, lines, problem = self._lead_in(current, game, break_at)
        try:
            out = self._sports_file(lead)
        except (ConfigError, OSError) as exc:
            with self.lock:
                self.error = f'The sports break could not be cued: {exc}'
            return False
        with self.lock:
            self.error = problem
            if not self.next or self.next['file'] != out.name:
                self.next = {'id': uuid.uuid4().hex, 'file': out.name, 'announcer': 'sports',
                             'name': f"{announcer['name']}, then {SPORTS_NAME}" if announcer else SPORTS_NAME,
                             'lines': lines + [SPORTS_LINE], 'kind': 'sports',
                             'just_played': 'OFF AIR' if off_air(current) else self.spoken(current, 'en'),
                             'up_next': self.spoken(game, 'en'), 'at': time.time(),
                             'break_at': break_at, 'aired_at': None}
        if self.sent != str(out):
            self._send(out)
        self._tidy()
        return True

    def _send(self, path):
        try:
            self.master.request('ident_file', {'path': str(path) if path else None})
            self.sent = str(path) if path else None
        except Exception as exc:
            with self.lock:
                self.error = f'Master did not take the announcement: {exc}'

    def _check_master(self):
        """File the cued announcement as aired once the worker names it as the last ID, and
        cue it again if the worker lost it (a restart)."""
        try:
            state = self.master.request()
        except Exception:
            return
        last, ident = state.get('last_station_id') or {}, state.get('ident') or {}
        at = last.get('at')
        if isinstance(at, (int, float)) and at > self.logged:
            kind = 'sports' if str(last.get('file') or '').startswith(SPORTS_PREFIX) else 'station'
            try:
                append_play(self.aired_path, {'kind': kind, 'at': at, 'file': last.get('file')})
                self.logged = at
            except OSError as exc:
                logging.getLogger(__name__).warning('Could not log the ID that aired: %s', exc)
        with self.lock:
            # The same file (the Sports ID, or the same words again) aired before this cue
            # was made: only an airing since then files it.
            if (self.next and last.get('file') == self.next['file'] and not self.next['aired_at']
                    and (last.get('at') or 0) >= self.next['at']):
                self.next['aired_at'] = last.get('at')
                self.recent = [self.next] + self.recent[:19]
                self.next = None
                self.sent = None  # The worker has gone back to the plain ID.
            elif self.sent and not ident.get('on_air') and ident.get('file') not in (None, Path(self.sent).name):
                self.sent = None

    def _run(self):
        while True:
            with self.lock:
                if self.closed:
                    return
            try:
                self.step()
            except Exception:  # Keep continuity alive; the next pass tries again.
                logging.getLogger(__name__).exception('Continuity step failed')
            with self.lock:
                if self.closed:
                    return
                self.wake.wait(self.poll_seconds)

    def close(self):
        with self.lock:
            self.closed = True
            self.wake.notify_all()
        if self.thread:
            self.thread.join(timeout=5)
