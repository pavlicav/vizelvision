"""Local media library: browse files under configured roots and resolve them for playout.

An item ID is "<root id>/<relative path>". It survives restarts, so queue entries
keep working, and it can never name a path outside a configured root. Only
finished files are listed: TV-Thing writes a recording as *.part and renames it
into the library when complete.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path, PurePosixPath

from .errors import ChannelNotFoundError, ConfigError

LIBRARY_SOURCE_ID = 'library'
VIDEO_EXTENSIONS = ('.mp4', '.m4v', '.mkv', '.ts', '.mov', '.webm', '.avi', '.mpg', '.mpeg')
MAX_ITEMS = 20000
MAX_DEPTH = 8
SCAN_SECONDS = 15
PROBE_TIMEOUT = 20

# "Jeopardy! - 7.1 WJLA - 2026-09-24 1930 (2)": TV-Thing's recording name.
_RECORDING = re.compile(r'^(?P<title>.+?) - (?P<channel>\d+\.\d+(?: [^-]+?)?) - '
                        r'(?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{4})(?: \((?P<variant>[^)]{1,20})\))?$')


def library_target(data):
    source, channel = data.get('source_id'), data.get('channel_id')
    if source != LIBRARY_SOURCE_ID:
        raise ConfigError('Library target requires source_id "library"')
    if not isinstance(channel, str) or not 3 <= len(channel) <= 1024 or '\0' in channel:
        raise ConfigError('Library channel_id must be a library item ID')
    parts = PurePosixPath(channel).parts
    if (len(parts) < 2 or channel.startswith('/') or channel != '/'.join(parts)
            or any(p in ('.', '..') or p.startswith('.') for p in parts)
            or PurePosixPath(channel).suffix.lower() not in VIDEO_EXTENSIONS):
        raise ConfigError('Library channel_id must be a library item ID')
    return {'source_id': LIBRARY_SOURCE_ID, 'channel_id': channel}


def resolve(config, channel_id):
    """The real file for an item ID, refusing anything outside its root."""
    channel_id = library_target({'source_id': LIBRARY_SOURCE_ID, 'channel_id': channel_id})['channel_id']
    root_id, relative = channel_id.split('/', 1)
    root = next((r for r in config.roots if r.id == root_id), None)
    if root is None or not config.enabled:
        raise ChannelNotFoundError('Unknown library collection')
    try:
        base = root.path.resolve(strict=True)
        path = (base / relative).resolve(strict=True)
    except OSError as exc:
        raise ChannelNotFoundError('Library file is no longer available') from exc
    if not path.is_relative_to(base) or not path.is_file():
        raise ChannelNotFoundError('Library file is no longer available')
    return path


def describe_name(relative, root_name):
    """Display metadata from a file name; TV-Thing recordings carry title, channel and air time."""
    path = PurePosixPath(relative)
    folder = str(path.parent) if str(path.parent) != '.' else None
    match = _RECORDING.match(path.stem)
    if match:
        try:
            aired = datetime.strptime(match['date'] + ' ' + match['time'], '%Y-%m-%d %H%M').timestamp()
        except ValueError:
            aired = None
        return {'title': match['title'], 'channel': match['channel'], 'aired': aired,
                'variant': match['variant'], 'collection': folder or root_name}
    title = path.stem if ' ' in path.stem else path.stem.replace('_', ' ')
    return {'title': title.strip() or path.name, 'channel': None, 'aired': None, 'variant': None,
            'collection': folder or root_name}


def probe(path, *, runner=subprocess.run):
    """Duration and tracks via ffprobe. The master needs both video and audio."""
    try:
        result = runner(['ffprobe', '-v', 'error', '-show_entries',
                         'format=duration:stream=codec_type,codec_name,width,height',
                         '-of', 'json', str(path)], capture_output=True, timeout=PROBE_TIMEOUT, check=False)
        data = json.loads(result.stdout or b'{}')
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {'probe': 'failed', 'playable': False, 'reason': 'Could not read this file'}
    streams = [s for s in data.get('streams', []) if isinstance(s, dict)]
    video = next((s for s in streams if s.get('codec_type') == 'video'), None)
    audio = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    try:
        duration = float((data.get('format') or {}).get('duration'))
    except (TypeError, ValueError):
        duration = None
    reason = ('No video track' if video is None else 'No audio track' if audio is None
              else 'Could not read this file' if result.returncode else None)
    return {'probe': 'ok' if not result.returncode else 'failed', 'playable': reason is None, 'reason': reason,
            'duration': duration if duration and duration > 0 else None,
            'video': {'codec': video.get('codec_name'), 'width': video.get('width'),
                      'height': video.get('height')} if video else None,
            'audio': {'codec': audio.get('codec_name')} if audio else None}


class MediaLibrary:
    """Cached scans plus a background ffprobe of new or changed files."""

    def __init__(self, config, cache_file=None, *, clock=time.monotonic, prober=probe, start_worker=True):
        self.config = config
        self.cache_file = Path(cache_file) if cache_file else None
        self.clock, self.prober = clock, prober
        self.lock = threading.Condition()
        self.items, self.roots, self.scanned_at, self.next_scan = {}, [], None, 0.
        self.probes = self._load_cache()
        self.thread = None
        self.closed = False
        if config.enabled and start_worker:
            self.thread = threading.Thread(target=self._probe_loop, name='library-probe', daemon=True)
            self.thread.start()

    def _load_cache(self):
        try:
            data = json.loads(self.cache_file.read_text()) if self.cache_file else {}
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_cache_locked(self):
        if not self.cache_file:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_file.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.probes))
            temporary.replace(self.cache_file)
        except OSError as exc:
            logging.getLogger(__name__).warning('Cannot save library probe cache: %s', exc)

    def _scan(self):
        items, roots = {}, []
        for root in self.config.roots:
            summary = {'id': root.id, 'name': root.name, 'available': False, 'count': 0, 'error': None}
            roots.append(summary)
            try:
                base = root.path.resolve(strict=True)
                if not base.is_dir():
                    raise NotADirectoryError(str(base))
            except OSError:
                summary['error'] = 'Folder is unavailable'
                continue
            summary['available'] = True
            for directory, folders, files in os.walk(base):
                depth = len(Path(directory).relative_to(base).parts)
                folders[:] = [] if depth >= MAX_DEPTH else sorted(f for f in folders if not f.startswith('.'))
                for name in files:
                    if name.startswith('.') or Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
                        continue
                    if len(items) >= MAX_ITEMS:
                        summary['error'] = f'Only the first {MAX_ITEMS} files are listed'
                        break
                    path = Path(directory) / name
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    relative = path.relative_to(base).as_posix()
                    item_id = root.id + '/' + relative
                    try:
                        library_target({'source_id': LIBRARY_SOURCE_ID, 'channel_id': item_id})
                    except ConfigError:
                        continue
                    items[item_id] = {'id': item_id, 'root': root.id, 'path': relative, 'bytes': stat.st_size,
                                      'modified': int(stat.st_mtime), 'identity': f'{stat.st_size}:{stat.st_mtime_ns}',
                                      **describe_name(relative, root.name)}
                    summary['count'] += 1
        return items, roots

    def _refresh_locked(self, force=False):
        if force or self.clock() >= self.next_scan:
            self.items, self.roots = self._scan()
            self.scanned_at, self.next_scan = time.time(), self.clock() + SCAN_SECONDS
            self.lock.notify_all()

    def _public(self, item):
        cached = self.probes.get(item['id'])
        info = cached if cached and cached.get('identity') == item['identity'] else {'probe': 'pending'}
        result = {k: v for k, v in item.items() if k != 'identity'}
        result.update({k: v for k, v in info.items() if k != 'identity'})
        result.setdefault('playable', None)
        return result

    def listing(self, force=False):
        with self.lock:
            self._refresh_locked(force)
            return {'source_id': LIBRARY_SOURCE_ID, 'guide': {'available': True, 'kind': 'library'},
                    'channels': [], 'stale': False, 'scanned_at': self.scanned_at, 'roots': list(self.roots),
                    'items': [self._public(i) for i in self.items.values()]}

    def item(self, channel_id):
        with self.lock:
            self._refresh_locked()
            item = self.items.get(channel_id)
            return self._public(item) if item else None

    def target(self, body):
        """Validate a playout target: listed, and not known to be unplayable."""
        target = library_target(body)
        resolve(self.config, target['channel_id'])
        item = self.item(target['channel_id'])
        if item is None:
            raise ChannelNotFoundError('Library file is no longer listed')
        if item.get('playable') is False:
            raise ConfigError(f"This file cannot play on master: {item.get('reason') or 'unsupported'}")
        return target

    def label(self, channel_id):
        item = self.item(channel_id) if self.config.enabled else None
        return item['title'] if item else PurePosixPath(str(channel_id)).stem

    def _probe_loop(self):
        while True:
            with self.lock:
                if self.closed:
                    return
                self._refresh_locked()
                pending = next((i for i in self.items.values()
                                if (self.probes.get(i['id']) or {}).get('identity') != i['identity']), None)
                if pending is None:
                    self.lock.wait(timeout=SCAN_SECONDS)
                    continue
                root = next(r for r in self.config.roots if r.id == pending['root'])
                path = root.path / pending['path']
            info = self.prober(path)  # Never hold the lock during ffprobe.
            with self.lock:
                self.probes[pending['id']] = {**info, 'identity': pending['identity']}
                # Forget files that left the library so the cache stays bounded.
                self.probes = {k: v for k, v in self.probes.items() if k in self.items}
                self._save_cache_locked()

    def close(self):
        with self.lock:
            self.closed = True
            self.lock.notify_all()
        if self.thread:
            self.thread.join(timeout=PROBE_TIMEOUT + 2)


class FileLease:
    """A library file for the master worker. Files are independent: many can be open."""
    lane = 'library'

    def __init__(self, config, target):
        self.target = library_target(target)
        path = resolve(config, self.target['channel_id'])
        stat = path.stat()
        self.generation = f'{stat.st_size}:{stat.st_mtime_ns}'
        self.uri = path.as_uri()

    def tune(self):
        pass

    def check(self):
        # An open file keeps playing even if it is erased; nothing to re-verify.
        return self.uri

    def renew(self, *, force=False):
        pass

    def release(self):
        return True
