"""The master worker's side of ad muting.

The worker taps each analysed input (DecodedInput with ``tap``) and streams it to
the ad-mute sidecar over a Unix socket; the sidecar answers with a gain schedule per
input. This module never blocks the media path and never makes anything quieter on
its own:

  * frames are queued without blocking and dropped when the sidecar is slow or gone
  * gain follows the sidecar's schedule only up to its lease; past it, or with no
    sidecar at all, the sound fades back up
  * operator overrides apply here at once and hold until the sidecar acknowledges
    them, so "it's the show" works even with the sidecar down
  * only mode 'on' touches the sound; 'shadow' only draws the badge
  * the words the sidecar's Whisper hears on an input come along, for live captions
    (take_words), so the on-air input is not transcribed twice

Pure Python (the worker's interpreter has no numpy).
"""
from __future__ import annotations

from array import array
from collections import deque
import json
import logging
import socket
import threading
import time

from . import admute_protocol as proto

SECOND = 1_000_000_000
MARGIN = 1.0             # seconds between the sidecar's decision and its audio leaving the delay line
LEASE_FADE = 250_000_000
OVERRIDE_FADE = 150_000_000
QUEUE_BYTES = 12 << 20   # about 6 s of tapped media
WORDS_KEPT = 400         # words heard on an input that live captions have not taken yet
RECONNECT = 2.0


def _schedule(events, pts):
    """Gain at pts from [(pts, level, ramp_ns)] (sorted); 1.0 before the first."""
    level = 1.0
    for at, target, ramp in events:
        if pts < at:
            break
        if ramp > 0 and pts < at + ramp:
            return level + (target - level) * (pts - at) / ramp
        level = target
    return level


class InputState:
    def __init__(self, key, info):
        self.key, self.info = key, info
        self.events = []
        self.lease = None
        self.badge = None            # [from_pts, to_pts|None, label, p]
        self.why = None              # [headline, detail]: the mute's confidence and evidence
        self.p_ad = None
        self.state = 'starting'
        self.ack = 0
        self.seq = 0
        self.override = None         # (seq, action, pts)
        self.last_pts = None         # newest programme audio pts seen by the worker
        self.speech = False          # the sidecar is transcribing this input
        self.words = deque(maxlen=WORDS_KEPT)   # (start pts, end pts, word) not yet taken
        self.updated = 0.


class AdMuteLink:
    def __init__(self, socket_path):
        self.path = str(socket_path)
        self.lock = threading.Lock()
        self.inputs: dict[str, InputState] = {}
        self.queue = deque()
        self.queued = 0
        self.dropped = 0
        self.mode = 'off'
        self.connected = False
        self.error = None
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.sock = None
        self.thread = None

    # ---------------------------------------------------------------- lifecycle
    def start(self):
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, name='admute-link', daemon=True)
            self.thread.start()

    def stop(self):
        self.stopping.set()
        self.wake.set()
        sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def set_mode(self, mode):
        self.mode = mode

    # ---------------------------------------------------------------- inputs
    def open_input(self, key, info):
        with self.lock:
            self.inputs[key] = InputState(key, info)
        self._send(proto.json_frame(b'S', key, 0, info))
        return InputTap(self, key, int((info['lookahead'] + MARGIN) * SECOND))

    def close_input(self, key):
        with self.lock:
            existed = self.inputs.pop(key, None) is not None
        if existed:
            self._send(proto.json_frame(b'E', key, 0, {}))

    def override(self, key, action):
        """mute | unmute: applies now, here; the sidecar learns of it too."""
        with self.lock:
            st = self.inputs.get(key)
            if st is None:
                return False
            st.seq += 1
            pts = (st.last_pts or 0) + 50_000_000
            st.override = (st.seq, action, pts)
            seq = st.seq
        self._send(proto.json_frame(b'O', key, pts, {'action': action, 'seq': seq}))
        return True

    # ---------------------------------------------------------------- media path
    def gain(self, key, pts):
        """Programme gain for an audio sample at input running time pts."""
        with self.lock:
            st = self.inputs.get(key)
            if st is None:
                return 1.0
            st.last_pts = pts if st.last_pts is None else max(st.last_pts, pts)
            if self.mode != 'on':
                return 1.0
            if st.override is not None and st.ack < st.override[0]:
                _, action, at = st.override
                before = _schedule(st.events, at) if st.lease is not None and at <= st.lease else 1.0
                target = 1.0 if action == 'unmute' else 0.0
                if pts < at:
                    return before
                return before + (target - before) * min(1.0, (pts - at) / OVERRIDE_FADE)
            if st.lease is None:
                return 1.0
            if pts <= st.lease:
                return _schedule(st.events, pts)
            # Past the lease: whatever the schedule says, the sound comes back.
            at_lease = _schedule(st.events, st.lease)
            return at_lease + (1.0 - at_lease) * min(1.0, (pts - st.lease) / LEASE_FADE)

    def peek(self, key, pts):
        """The gain the programme has at pts (without noting pts as heard)."""
        with self.lock:
            st = self.inputs.get(key)
            last = st.last_pts if st else None
        g = self.gain(key, pts)
        with self.lock:
            if st is not None:
                st.last_pts = last
        return g

    def status(self, key):
        with self.lock:
            st = self.inputs.get(key)
            if st is None:
                return None
            override = st.override if st.override and st.ack < st.override[0] else None
            return {'state': st.state, 'p_ad': st.p_ad, 'badge': st.badge, 'why': st.why, 'events': list(st.events),
                    'lease': st.lease, 'override': override[1] if override else None,
                    'fresh': time.monotonic() - st.updated < 3}

    def take_words(self, key):
        """Words heard on this input since the last call, [(start pts, end pts, word)], or
        None when the sidecar is not transcribing it (down, Whisper off, an older sidecar):
        then live captions transcribe it themselves."""
        with self.lock:
            st = self.inputs.get(key)
            if st is None or not st.speech or time.monotonic() - st.updated > 3:
                return None
            words = list(st.words)
            st.words.clear()
            return words

    def summary(self):
        with self.lock:
            return {'connected': self.connected, 'error': self.error, 'mode': self.mode,
                    'inputs': len(self.inputs), 'dropped': self.dropped}

    # ---------------------------------------------------------------- socket
    def _send(self, data):
        with self.lock:
            if not self.connected:
                return
            while self.queue and self.queued + len(data) > QUEUE_BYTES:
                self.queued -= len(self.queue.popleft())
                self.dropped += 1
            self.queue.append(data)
            self.queued += len(data)
        self.wake.set()

    def _run(self):
        while not self.stopping.is_set():
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                sock.settimeout(2)
                sock.connect(self.path)
            except OSError as exc:
                sock.close()
                self.error = f'ad-mute detector not reachable: {exc.strerror or exc}'
                self.stopping.wait(RECONNECT)
                continue
            self.sock = sock
            with self.lock:
                self.connected, self.error = True, None
                self.queue.clear()
                self.queued = 0
                hello = [proto.json_frame(b'S', st.key, 0, st.info) for st in self.inputs.values()]
            for frame in hello:
                self._send(frame)
            reader = threading.Thread(target=self._read, args=(sock,), name='admute-link-read', daemon=True)
            reader.start()
            try:
                while not self.stopping.is_set() and reader.is_alive():
                    self.wake.wait(.5)
                    self.wake.clear()
                    while True:
                        with self.lock:
                            if not self.queue:
                                break
                            data = self.queue.popleft()
                            self.queued -= len(data)
                        sock.sendall(data)
            except OSError as exc:
                self.error = f'ad-mute detector connection lost: {exc}'
            finally:
                with self.lock:
                    self.connected = False
                try:
                    sock.close()
                except OSError:
                    pass
                self.sock = None
            self.stopping.wait(RECONNECT)

    def _read(self, sock):
        buf = b''
        try:
            sock.settimeout(None)
            while not self.stopping.is_set():
                chunk = sock.recv(65536)
                if not chunk:
                    return
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    if line.strip():
                        self._message(json.loads(line))
        except (OSError, ValueError) as exc:
            self.error = f'ad-mute detector stream failed: {exc}'

    def _message(self, msg):
        with self.lock:
            st = self.inputs.get(msg.get('input'))
            if st is None:
                return
            events = msg.get('events') or []
            st.events = sorted((int(p), float(min(1.0, max(0.0, lvl))), int(max(0, r))) for p, lvl, r in events)
            st.lease = int(msg['lease']) if msg.get('lease') is not None else None
            st.badge = msg.get('badge')
            why = msg.get('why')
            st.why = [str(x)[:60] for x in why[:2]] if isinstance(why, list) else None
            st.p_ad = msg.get('p_ad')
            st.state = msg.get('state') or st.state
            st.ack = max(st.ack, int(msg.get('ack') or 0))
            st.speech = msg.get('speech') is True
            for word in msg.get('words') or ():
                if (isinstance(word, list) and len(word) == 3 and all(isinstance(x, int) for x in word[:2])
                        and isinstance(word[2], str) and word[0] < word[1]):
                    st.words.append((word[0], word[1], word[2][:40]))
            st.updated = time.monotonic()


class InputTap:
    """What one DecodedInput needs: where to send its tapped media, how long to hold
    the programme back, and the gain for its programme audio."""

    def __init__(self, link, key, delay_ns):
        self.link, self.key, self.delay_ns = link, key, delay_ns

    def gray(self, pts, data):
        self.link._send(proto.frame(b'G', self.key, pts, data))

    def rgb(self, pts, data):
        self.link._send(proto.frame(b'R', self.key, pts, data))

    def audio(self, pts, data):
        self.link._send(proto.frame(b'A', self.key, pts, data))

    def gain(self, pts):
        return self.link.gain(self.key, pts)


BADGE_SETTLE = 300_000_000   # a mute's fade down: until then the badge may not call the sound up


def badge_words(status, conf, at, gain):
    """The AD badge at input time ``at``: (label, caption), or None for no badge.

    In mode 'on' the badge says what the sound is doing: a call master is not
    following (past its lease: the detector is late, or down) reads NOT MUTED, never
    MUTED. (2026-10-03: a badge sat over a whole unmuted break.)"""
    event = status and status.get('badge')
    mode, diagnostic = conf.get('mode'), conf.get('diagnostic') is True
    show = diagnostic or conf.get('badge') == 'always' or (conf.get('badge') == 'shadow' and mode == 'shadow')
    if not event or not show or mode == 'off':
        return None
    start, end, label, probability = event
    if at < start or (end is not None and at >= end):
        return None
    unmuted = mode == 'on' and gain >= .5 and at >= start + BADGE_SETTLE
    why = status.get('why') if diagnostic else None
    if why:   # diagnostic: how sure, and what says so (admute/service.py, why())
        head = 'SHADOW · ' if mode == 'shadow' else 'NOT MUTED · ' if unmuted else ''
        return label, head + why[0] + (f'\n{why[1]}' if why[1:] and why[1] else '')
    if mode == 'shadow' and probability is not None:
        return label, f'SHADOW · {round(100 * probability)}%'
    return label, 'NOT MUTED' if unmuted else 'MUTED'


def apply_gain(data: bytes, pts: int, rate: int, channels: int, gain_at) -> bytes | None:
    """Scale interleaved F32 audio by gain_at(pts of each frame). None: unchanged."""
    frames = len(data) // (4 * channels)
    if not frames:
        return None
    end = pts + frames * SECOND // rate
    g0, g1 = gain_at(pts), gain_at(end)
    if g0 >= .9999 and g1 >= .9999 and gain_at((pts + end) // 2) >= .9999:
        return None
    if g0 <= 1e-4 and g1 <= 1e-4 and gain_at((pts + end) // 2) <= 1e-4:
        return bytes(len(data))
    samples = array('f')
    samples.frombytes(data[: frames * 4 * channels])
    step = 64                                   # the gain is evaluated every 64 frames
    knots = [gain_at(pts + i * SECOND // rate) for i in range(0, frames + step, step)]
    for i in range(frames):
        k, f = divmod(i, step)
        g = knots[k] + (knots[min(k + 1, len(knots) - 1)] - knots[k]) * f / step
        base = i * channels
        for c in range(channels):
            samples[base + c] *= g
    return samples.tobytes() + data[frames * 4 * channels:]
