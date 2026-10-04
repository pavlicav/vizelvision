"""Shared, persistent off-air presentation for the publisher and control room."""
import copy
import json
import os
from pathlib import Path
import tempfile
import threading

from .errors import ConfigError

PATTERN = Path(__file__).with_name('static') / 'test-pattern.webp'
DEFAULTS = {
    'captions': {'master': 'VIZELVISION MASTER OFF-AIR', 'tv-thing': 'TV-THING OFF', 'roku': 'ROKU OFF'},
    'details': ['format', 'audio', 'now_playing', 'route'],
    'note': 'NO PROGRAM LIVE',
    'audio': 'tone',
    'clock': {'enabled': False, 'seconds': False},
}
# Settings saved before the clock existed remain valid.
OPTIONAL = {'clock'}
AUDIO = {'tone': '1 kHz SINE · −20 dBFS PEAK · 48 kHz STEREO',
         'silence': 'OFF-AIR AUDIO · SILENCE',
         'radio': 'OFF-AIR AUDIO · CAIRO RADIO'}
DETAILS = {'format': 'Master output format', 'audio': 'Off-air audio',
           'now_playing': 'Cairo radio show and now playing', 'route': 'Source / output identification'}


class ProductionSettings:
    def __init__(self, master):
        self.master = master
        self.path = Path(master.socket_path).with_name('production.json')
        self.lock = threading.Lock()

    @staticmethod
    def validate(value):
        if not isinstance(value, dict) or not set(DEFAULTS) - OPTIONAL <= set(value) <= set(DEFAULTS):
            raise ConfigError('Production settings require captions, details, note and audio')
        value = {**copy.deepcopy(DEFAULTS), **value}
        clock = value['clock']
        if (not isinstance(clock, dict) or set(clock) != set(DEFAULTS['clock'])
                or not all(isinstance(flag, bool) for flag in clock.values())):
            raise ConfigError('clock requires enabled and seconds, each true or false')
        if not isinstance(value['audio'], str) or value['audio'] not in AUDIO:
            raise ConfigError('Off-air audio must be tone, silence or radio')
        captions = value['captions']
        if not isinstance(captions, dict) or set(captions) != set(DEFAULTS['captions']):
            raise ConfigError('Provide master, tv-thing and roku captions')
        for name, text in [*captions.items(), ('note', value['note'])]:
            limit = 48 if name != 'note' else 72
            if (not isinstance(text, str) or len(text) > limit
                    or any(ord(c) < 32 or ord(c) == 127 for c in text)
                    or (name != 'note' and not text.strip())):
                raise ConfigError(f'{name} must be a single line of at most {limit} characters')
        details = value['details']
        if (not isinstance(details, list) or len(details) > len(DETAILS)
                or any(not isinstance(item, str) or item not in DETAILS for item in details)
                or len(set(details)) != len(details)):
            raise ConfigError('Choose unique supported technical details')
        return copy.deepcopy(value)

    def read(self):
        try:
            return self.validate(json.loads(self.path.read_text()))
        except FileNotFoundError:
            return copy.deepcopy(DEFAULTS)

    def save(self, value):
        value = self.validate(value)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.production-', dir=self.path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(value, stream, indent=2)
                    stream.write('\n')
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
            finally:
                Path(name).unlink(missing_ok=True)
        return self.describe(value)

    def card(self, kind, settings=None, radio=()):
        """radio: live show/now-playing lines, shown on the master card while Cairo radio is the off-air audio."""
        settings = settings if settings is not None else self.read()
        m = self.master
        values = {
            'format': f'MASTER {m.width} × {m.height} / {m.fps} FPS · H.264 {m.bitrate} kb/s',
            'audio': AUDIO[settings['audio']],
            'route': {'master': 'VIZELVISION · MASTER OUTPUT', 'tv-thing': 'TV-THING · SOURCE', 'roku': 'ROKU · SOURCE'}[kind],
        }
        lines = []
        for key in settings['details']:
            if key != 'now_playing':
                lines.append(values[key])
            elif kind == 'master' and settings['audio'] == 'radio':
                lines.extend(radio)
        return {'caption': settings['captions'][kind], 'audio': settings['audio'],
                'lines': lines + ([settings['note']] if settings['note'] else [])}

    def describe(self, settings=None):
        settings = settings if settings is not None else self.read()
        return {'settings': settings, 'detail_options': DETAILS,
                'format_line': self.card('master', {**settings, 'details': ['format'], 'note': ''})['lines'][0],
                'cards': {kind: self.card(kind, settings) for kind in DEFAULTS['captions']}}
