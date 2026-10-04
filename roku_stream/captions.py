"""Bounded, disposable live transcription. No inference or pipe I/O on a media thread."""
from collections import deque
import json
import math
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import textwrap
import threading
import time

from .caption_settings import DEFAULTS

RATE = 16000
CHUNK_BYTES = RATE * 4 * 4  # Four seconds, mono float32.
MAX_AGE = 12.0
LOOKAHEAD_SECONDS = 6.0  # Shared programme delay, not added to ad lookahead.


class WhisperProcess:
    def __init__(self, settings):
        python = os.environ.get('VIZELVISION_WHISPER_PYTHON', sys.executable)
        self.process = subprocess.Popen(
            [python, '-u', str(Path(__file__).with_name('caption_transcriber.py')),
             '--model', settings['model'], '--language', settings['language']],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0, env={**os.environ, 'OMP_NUM_THREADS': '2'})
        for pipe in (self.process.stdin, self.process.stdout):
            os.set_blocking(pipe.fileno(), False)
        self.ready = False
        self.pending = bytearray()

    def _read(self, deadline):
        while b'\n' not in self.pending:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.process.stdout], [], [], left)[0]:
                raise TimeoutError('Whisper timed out; captions will retry')
            data = os.read(self.process.stdout.fileno(), 4096)
            if not data:
                raise RuntimeError('Whisper stopped; check the caption Python and model installation')
            self.pending.extend(data)
            if len(self.pending) > 16384:
                raise RuntimeError('Whisper returned an oversized response')
        line, _, rest = self.pending.partition(b'\n')
        self.pending = bytearray(rest)
        result = json.loads(line)
        if result.get('error'):
            raise RuntimeError(result['error'])
        return result

    def transcribe(self, pcm):
        deadline = time.monotonic() + 30
        if not self.ready:
            if not self._read(deadline).get('ready'):
                raise RuntimeError('Whisper did not become ready')
            self.ready = True
        data = memoryview(struct.pack('!I', len(pcm)) + pcm)
        while data:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([], [self.process.stdin], [], left)[1]:
                raise TimeoutError('Whisper input timed out')
            size = os.write(self.process.stdin.fileno(), data)
            data = data[size:]
        return self._read(deadline).get('segments', [])

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()

    def cancel(self):
        """Wake blocked pipe I/O without making the master wait for process shutdown."""
        if self.process.poll() is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass


def caption_lines(text):
    """Keep the current two lines legible at television size; no markup or controls."""
    clean = ' '.join(''.join(c for c in text if c.isprintable() or c.isspace()).split())
    return '\n'.join(textwrap.wrap(clean, width=64)[-2:])


def timed_cues(segments, origin, duration):
    """Short readable phrases, anchored to Whisper's word times in source audio.

    Invalid or out-of-window timestamps cannot put a caption on unrelated video.
    Word timing survives VAD's removal of silence (faster-whisper restores it).
    """
    cues, group = [], []
    def finish():
        if group:
            text = caption_lines(' '.join(w['text'].strip() for w in group))
            if text:
                cues.append((origin + group[0]['start'], origin + min(duration, group[-1]['end'] + .15), text))
            group.clear()
    for segment in segments:
        for word in segment.get('words') or [segment]:
            start, end, text = word.get('start'), word.get('end'), word.get('text')
            if (isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, (int, float))
                    or not isinstance(end, (int, float)) or not math.isfinite(start) or not math.isfinite(end)
                    or not 0 <= start < end <= duration + .1 or not isinstance(text, str)):
                continue
            if group and (start < group[-1]['start'] or start - group[-1]['end'] > .4
                          or end - group[0]['start'] > 2.2
                          or sum(len(w['text']) for w in group) + len(text) > 64):
                finish()
            group.append({'start': start, 'end': min(end, duration), 'text': text})
            if text.rstrip().endswith(('.', '!', '?')):
                finish()
        finish()
    return cues


class LiveCaptions:
    def __init__(self, *, factory=WhisperProcess, clock=time.monotonic):
        self.factory, self.clock = factory, clock
        self.condition = threading.Condition()
        self.settings = dict(DEFAULTS)
        self.generation = 0
        self.revision = 0
        self.buffer = bytearray()
        self.pending = deque(maxlen=2)
        self.thread = None
        self.worker = None
        self.stopped = False
        self.text = ''
        self.cues = deque(maxlen=160)
        self.played_pts = None
        self.buffer_pts = None
        self.route = None
        self.late_cues = 0
        self.last_audio = None
        self.error = None
        self.state = 'off'
        self.dropped = 0
        self.latency = None
        self.last_pts = None

    def _reset(self):
        self.generation += 1
        self.buffer.clear()
        self.pending.clear()
        self.text = ''
        self.cues.clear()
        self.buffer_pts = self.played_pts = self.route = None
        self.last_pts = self.last_audio = None
        self.latency = None

    def configure(self, settings):
        with self.condition:
            if settings == self.settings:
                return
            self.settings = dict(settings)
            self.revision += 1
            self._reset()
            if self.worker:
                self.worker.cancel()
            self.error = None
            self.state = 'listening' if settings['enabled'] else 'off'
            if settings['enabled'] and self.thread is None:
                self.thread = threading.Thread(target=self._run, name='live-captions', daemon=True)
                self.thread.start()
            self.condition.notify_all()

    def reset(self):
        """A take, mute/bed transition or discontinuity invalidates queued/in-flight text."""
        with self.condition:
            self._reset()
            self.state = 'listening' if self.settings['enabled'] else 'off'
            self.condition.notify_all()

    def _queue_audio(self):
        if self.buffer_pts is not None and len(self.buffer) >= RATE * 4 // 5:
            if len(self.pending) == self.pending.maxlen:
                self.dropped += 1
            self.pending.append((self.generation, self.clock(), self.buffer_pts, bytes(self.buffer)))
            self.condition.notify_all()
        self.buffer.clear()
        self.buffer_pts = None

    def feed(self, pcm, pts=None, route=None):
        with self.condition:
            if not self.settings['enabled'] or self.stopped or pts is None:
                return
            if self.last_pts is not None and (pts < self.last_pts - .01 or pts - self.last_pts > .15):
                self._queue_audio()
            if route != self.route:
                # Finish the previous source without discarding cues for its buffered tail.
                self._queue_audio()
                self.route = route
            if self.buffer_pts is None:
                self.buffer_pts = pts
            self.last_pts = pts
            self.last_audio = self.clock()
            self.buffer.extend(pcm)
            while len(self.buffer) >= CHUNK_BYTES:
                if len(self.pending) == self.pending.maxlen:
                    self.dropped += 1
                self.pending.append((self.generation, self.clock(), self.buffer_pts, bytes(self.buffer[:CHUNK_BYTES])))
                del self.buffer[:CHUNK_BYTES]
                self.buffer_pts += CHUNK_BYTES / (RATE * 4)
                self.condition.notify_all()
            self.last_pts = pts + len(pcm) / (RATE * 4)

    def text_at(self, pts, *, audible=True):
        """Called for each delayed video frame using its ORIGINAL audio timestamp."""
        with self.condition:
            self.played_pts = pts
            while self.cues and pts is not None and self.cues[0][1] <= pts:
                self.cues.popleft()
            self.text = next((text for start, end, text in self.cues if start <= pts < end), '') \
                if pts is not None and self.settings['enabled'] and audible else ''
            return self.text

    def status(self):
        with self.condition:
            text = self.text if self.settings['enabled'] else ''
            state = self.state
            if self.settings['enabled'] and not self.error and (self.last_audio is None or self.clock() - self.last_audio > 2):
                state = 'waiting_for_audio'
            return {'enabled': self.settings['enabled'], 'state': state, 'text': text,
                    'error': self.error, 'dropped_chunks': self.dropped,
                    'latency_seconds': self.latency, 'model': self.settings['model'],
                    'late_cues': self.late_cues, 'queued_cues': len(self.cues), 'timing': 'audio_timestamps'}

    def _run(self):
        worker, model_key = None, None
        try:
            while True:
                with self.condition:
                    if self.stopped:
                        break
                    settings = dict(self.settings)
                    revision = self.revision
                    generation = self.generation
                    job = self.pending.popleft() if self.pending and settings['enabled'] else None
                    if job:
                        generation, captured, origin, pcm = job
                        self.state = 'transcribing' if worker else 'loading'
                if not settings['enabled'] and worker:
                    worker.close()
                    worker, model_key = None, None
                    with self.condition:
                        self.worker = None
                try:
                    key = (settings['model'], settings['language'], revision)
                    if settings['enabled'] and key != model_key:
                        if worker:
                            worker.close()
                        # Start loading while the first audio chunk is still filling.
                        worker = self.factory(settings)
                        model_key = key
                        with self.condition:
                            self.worker = worker
                            if self.stopped or generation != self.generation:
                                worker.cancel()
                    if not job:
                        with self.condition:
                            self.condition.wait(.25)
                        continue
                    if self.clock() - captured > MAX_AGE:
                        with self.condition:
                            self.dropped += 1
                        continue
                    cues = timed_cues(worker.transcribe(pcm), origin, len(pcm) / (RATE * 4))
                    with self.condition:
                        if generation == self.generation and self.settings['enabled']:
                            age = self.clock() - captured
                            self.error, self.state = None, 'listening'
                            self.latency = round(len(pcm) / (RATE * 4) + age, 2)
                            if age <= MAX_AGE:
                                for cue in cues:
                                    if self.played_pts is not None and cue[0] < self.played_pts:
                                        self.late_cues += 1
                                    if self.played_pts is None or cue[1] > self.played_pts:
                                        self.cues.append(cue)
                                self.cues = deque(sorted(self.cues), maxlen=160)
                            else:
                                self.dropped += 1
                except Exception as exc:
                    if worker:
                        worker.close()
                    worker, model_key = None, None
                    with self.condition:
                        self.worker = None
                        if generation == self.generation:
                            self.error, self.state = str(exc)[:500], 'error'
                            self.text = ''
                            # Bounded backoff. Disabling or changing the source wakes us.
                            self.condition.wait(5)
        finally:
            if worker:
                worker.close()

    def close(self):
        with self.condition:
            self.stopped = True
            if self.worker:
                self.worker.cancel()
            self.settings = {**self.settings, 'enabled': False}
            self._reset()
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=.1)  # Pipe I/O has a deadline; shutdown never holds the master.
