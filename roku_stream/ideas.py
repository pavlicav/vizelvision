"""The ideas board (Engineering › Ideas): future improvements, kept small on purpose.

One file, ideas.json beside master.sock, written only by the web app. Each idea has a title,
a note (dependencies go here too), an area and a status.
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path

from .errors import ConfigError

AREAS = ('tv-thing', 'vizelvision', 'ads', 'channels', 'streams', 'ui', 'other')
STATUSES = ('idea', 'next', 'doing', 'done', 'dropped')
FIELDS = ('title', 'note', 'area', 'status')
MAX_IDEAS = 500
MAX_TITLE = 120
MAX_NOTE = 4000


class IdeaStore:
    def __init__(self, socket_path, *, clock=time.time):
        self.path = Path(socket_path).with_name('ideas.json')
        self.lock = threading.Lock()
        self.clock = clock

    @staticmethod
    def validate(changes, *, new=False):
        if not isinstance(changes, dict) or not set(changes) <= set(FIELDS):
            raise ConfigError('An idea takes title, note, area and status')
        if new and 'title' not in changes:
            raise ConfigError('An idea needs a title')
        value = dict(changes)
        if 'title' in value:
            if not isinstance(value['title'], str) or not value['title'].strip():
                raise ConfigError('title must be a non-empty string')
            if len(value['title'].strip()) > MAX_TITLE:
                raise ConfigError(f'title must be at most {MAX_TITLE} characters')
            value['title'] = value['title'].strip()
        if 'note' in value:
            if not isinstance(value['note'], str) or len(value['note']) > MAX_NOTE:
                raise ConfigError(f'note must be a string of at most {MAX_NOTE} characters')
            value['note'] = value['note'].strip()
        if 'area' in value and value['area'] not in AREAS:
            raise ConfigError('area must be one of ' + ', '.join(AREAS))
        if 'status' in value and value['status'] not in STATUSES:
            raise ConfigError('status must be one of ' + ', '.join(STATUSES))
        return value

    def read(self):
        try:
            ideas = json.loads(self.path.read_text()).get('ideas')
        except FileNotFoundError:
            ideas = []
        return {'ideas': ideas if isinstance(ideas, list) else [], 'areas': list(AREAS), 'statuses': list(STATUSES)}

    def add(self, data):
        value = self.validate(data, new=True)
        with self.lock:
            ideas = self.read()['ideas']
            if len(ideas) >= MAX_IDEAS:
                raise ConfigError(f'The board holds at most {MAX_IDEAS} ideas')
            now = self.clock()
            idea = {'id': secrets.token_hex(6), 'title': value['title'], 'note': value.get('note', ''),
                    'area': value.get('area', 'other'), 'status': value.get('status', 'idea'),
                    'created': now, 'updated': now}
            self._write(ideas + [idea])
            return idea

    def edit(self, idea_id, changes):
        """The idea with its changes, or None if there is no such idea."""
        value = self.validate(changes)
        with self.lock:
            ideas = self.read()['ideas']
            idea = next((i for i in ideas if i.get('id') == idea_id), None)
            if idea is None:
                return None
            if value:
                idea.update(value, updated=self.clock())
                self._write(ideas)
            return idea

    def remove(self, idea_id):
        """The removed idea, or None if there is no such idea."""
        with self.lock:
            ideas = self.read()['ideas']
            idea = next((i for i in ideas if i.get('id') == idea_id), None)
            if idea is not None:
                self._write([i for i in ideas if i is not idea])
            return idea

    def _write(self, ideas):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix='.ideas-', dir=self.path.parent)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump({'ideas': ideas}, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
