"""Persistent live-caption controls, independent of the off-air card's captions."""
import json
import os
from pathlib import Path
import tempfile
import threading

from .errors import ConfigError

DEFAULTS = {'enabled': False, 'model': 'base.en', 'language': 'en'}
MODELS = ('tiny.en', 'base.en', 'small.en', 'tiny', 'base', 'small')
LANGUAGES = {'auto': 'Detect language', 'en': 'English', 'es': 'Spanish', 'fr': 'French',
             'de': 'German', 'it': 'Italian', 'pt': 'Portuguese', 'ja': 'Japanese'}


class CaptionSettings:
    def __init__(self, socket_path):
        self.path = Path(socket_path).with_name('captions.json')
        self.lock = threading.Lock()

    @staticmethod
    def validate(value):
        if not isinstance(value, dict) or not set(value) <= set(DEFAULTS):
            raise ConfigError('Caption settings take enabled, model and language')
        value = {**DEFAULTS, **value}
        if not isinstance(value['enabled'], bool):
            raise ConfigError('enabled must be true or false')
        if value['model'] not in MODELS:
            raise ConfigError('Choose a supported Whisper model')
        if not isinstance(value['language'], str) or value['language'] not in LANGUAGES:
            raise ConfigError('Choose a supported caption language')
        if value['model'].endswith('.en') and value['language'] != 'en':
            raise ConfigError('English-only models require English; choose a multilingual model for other languages')
        return value

    def read(self):
        try:
            return self.validate(json.loads(self.path.read_text()))
        except FileNotFoundError:
            return dict(DEFAULTS)

    def update(self, changes):
        if not isinstance(changes, dict):
            raise ConfigError('Caption settings must be an object')
        with self.lock:
            value = self.validate({**self.read(), **changes})
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.captions-', dir=self.path.parent)
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
