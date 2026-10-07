"""Ad-mute settings, shared by the web app (strict), the master worker and the
ad-mute sidecar (both lenient: a newer web app's keys never stop them).

Stored as admute.json beside the master socket. Pure Python: the sidecar imports
it under the conda Python, the worker under the system one.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import threading

from .errors import ConfigError

MODES = ('off', 'shadow', 'on')
SOUNDS = ('silence', 'radio')
BADGES = ('off', 'shadow', 'always')
# Whisper models the sidecar can use, cheapest first (admute/speech.py). Only cached
# models load: one that does not falls back to base.en.
SPEECH_MODELS = ('tiny.en', 'base.en', 'small.en', 'distil-large-v3')
DETECTORS = ('classic', 'new')
DEFAULTS = {
    # off: nothing is analysed (and no delay). shadow: the detector runs and the AD badge
    # shows what it would mute; the sound is never touched. on: breaks go quiet.
    'mode': 'off',
    # Which inputs are analysed (TV-Thing channels, Roku apps). Applies at the next prepare.
    'sources': {'tv_thing': True, 'roku': True},
    # Seconds the programme plays behind the detector (applies at the next prepare).
    'lookahead': 3.0,
    # classic: the detector as it was. new: the classic evidence plus a CLIP picture score
    # (admute/clip.py) and memoryless warm-up weights for the first minutes after a take.
    # Both use the known-ads database. A change starts each input's analysis over.
    'detector': 'classic',
    # 0 = cautious (mutes only when sure), 1 = eager.
    'sensitivity': 0.5,
    'max_mute': 300,
    'sound': 'silence',
    # The Cairo radio bed, relative to the off-air radio level.
    'radio_db': -6.0,
    'badge': 'shadow',
    # With a game held on air, MLB's live feed vetoes mutes while play is live.
    'sports_gate': True,
    # Corrections become training labels.
    'learn': True,
    # Whisper transcribes analysed inputs; what is said is evidence too (admute/text.py).
    'speech': True,
    # Which Whisper. small.en hears more but costs about four times the CPU of base.en,
    # and the sidecar may use 1.5 cores in all (its unit's CPUQuota).
    'speech_model': 'base.en',
    # Audio fingerprints: recognise ads heard before (admute/fingerprint.py).
    'known_ads': True,
    # Breaks it confirms teach the known ads (a clip counts once heard in two breaks).
    'learn_ads': True,
    # An MLB game's breaks, from its play-by-play, teach the known ads as the game goes.
    'learn_games': True,
    # The AD badge shows each mute's confidence and source (shown whatever 'badge' says).
    'diagnostic': False,
    # Games on over-the-air networks are recorded on TV-Thing for training (admute/recordings.py).
    'record_games': True,
    # Programme titles never muted (case-insensitive substrings).
    'exceptions': [],
    # "Pause for this program": no muting of this input (the one on air then) until this
    # wall time (epoch seconds). The next input is analysed as usual.
    'paused_until': None,
    'paused_input': None,
}
LIMITS = {'lookahead': (1.0, 8.0), 'sensitivity': (0.0, 1.0), 'max_mute': (60, 600), 'radio_db': (-30.0, 6.0)}
EXCEPTIONS_LIMIT = 50


def validate(value, *, lenient=False):
    if not isinstance(value, dict):
        raise ConfigError('Ad-mute settings must be an object')
    if lenient:
        value = {k: v for k, v in value.items() if k in DEFAULTS}
    elif not set(value) <= set(DEFAULTS):
        raise ConfigError('Ad-mute settings take ' + ', '.join(DEFAULTS))
    result = {**copy.deepcopy(DEFAULTS), **copy.deepcopy(value)}
    for key, choices in (('mode', MODES), ('sound', SOUNDS), ('badge', BADGES), ('speech_model', SPEECH_MODELS),
                         ('detector', DETECTORS)):
        if result[key] not in choices:
            raise ConfigError(f'{key} must be one of ' + ', '.join(choices))
    sources = result['sources']
    if not isinstance(sources, dict) or not set(sources) <= set(DEFAULTS['sources']) \
            or not all(isinstance(v, bool) for v in sources.values()):
        raise ConfigError('sources takes tv_thing and roku, each true or false')
    result['sources'] = {**DEFAULTS['sources'], **sources}
    for key, (lo, hi) in LIMITS.items():
        v = result[key]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            raise ConfigError(f'{key} must be a number from {lo} to {hi}')
    for key in ('sports_gate', 'learn', 'speech', 'known_ads', 'learn_ads', 'learn_games', 'diagnostic', 'record_games'):
        if not isinstance(result[key], bool):
            raise ConfigError(f'{key} must be true or false')
    ex = result['exceptions']
    if (not isinstance(ex, list) or len(ex) > EXCEPTIONS_LIMIT
            or any(not isinstance(s, str) or not s.strip() or len(s) > 80 for s in ex)):
        raise ConfigError(f'exceptions must list at most {EXCEPTIONS_LIMIT} titles of up to 80 characters')
    result['exceptions'] = [s.strip() for s in ex]
    p = result['paused_until']
    if p is not None and (isinstance(p, bool) or not isinstance(p, (int, float))):
        raise ConfigError('paused_until must be a time or null')
    k = result['paused_input']
    if k is not None and (not isinstance(k, str) or not 0 < len(k) <= 64):
        raise ConfigError('paused_input must be an input ID or null')
    return result


def paused(settings, key, now):
    """Is ad mute paused for this input (by "pause for this program")?"""
    until = settings.get('paused_until')
    return bool(until and until > now and settings.get('paused_input') in (None, key))


class AdMuteSettings:
    def __init__(self, socket_path, *, lenient=False):
        self.path = Path(socket_path).with_name('admute.json')
        self.lenient = lenient
        self.lock = threading.Lock()

    def read(self):
        try:
            return validate(json.loads(self.path.read_text()), lenient=self.lenient)
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)

    def save(self, value):
        value = validate(value)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.admute-', dir=self.path.parent)
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

    def update(self, changes):
        """Merge changes into the saved settings (web only)."""
        if not isinstance(changes, dict):
            raise ConfigError('Ad-mute settings must be an object')
        with self.lock:
            current = self.read()
        merged = {**current, **changes}
        if isinstance(changes.get('sources'), dict):
            merged['sources'] = {**current['sources'], **changes['sources']}
        return self.save(merged)


def lane_enabled(settings, lane):
    """Does ad mute analyse an input on this lane (digital/analog/roku/library)?"""
    if settings['mode'] == 'off':
        return False
    if lane in ('digital', 'analog'):
        return settings['sources']['tv_thing']
    if lane == 'roku':
        return settings['sources']['roku']
    return False
