"""One bounded programme delay, shared by ad analysis and live captioning.

Selection and decoding continue on the source timeline. Both output tracks are
released on the same delayed timeline, with their original timestamp and route.
Increasing lookahead fills the gap with a held picture and silence; it never
rewinds a timestamp or blocks decoding. Decreasing it waits for a worker restart.
"""
from collections import deque
import threading

SECOND = 1_000_000_000


def retimable(gst, buffer):
    """A buffer of our own to re-timestamp, sharing the media (no data copied).

    In PyGObject, Gst.Buffer.copy() is g_boxed_copy, which for a GstBuffer only adds a
    reference: setting pts on the "copy" rewrites the original, which other branches
    (a tee's ad-mute tap) or an earlier push may still hold.
    """
    flags = getattr(gst, 'BufferCopyFlags', None)
    if flags is None or not hasattr(buffer, 'copy_region'):
        return buffer.copy()  # the unit tests' stand-in buffers
    return buffer.copy_region(flags.FLAGS | flags.TIMESTAMPS | flags.META | flags.MEMORY, 0, buffer.get_size())


class ProgrammeDelay:
    LEAD = 80_000_000
    MAX_BYTES = 1024 * 1024 * 1024

    def __init__(self, output):
        self.output, self.gst = output, output.gst
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.delay_ns = 0
        self.queues = {k: deque() for k in ('video', 'audio')}
        self.ends = {k: None for k in self.queues}
        self.last_due = {k: None for k in self.queues}
        self.filler = None
        self.bytes = 0
        self.dropped = 0
        self.drop_reasons = {'late': 0, 'overlap': 0, 'backwards': 0, 'capacity': 0}
        self.error = None
        self.thread = threading.Thread(target=self._run, name='programme-delay', daemon=True)

    def require(self, seconds):
        with self.lock:
            self.delay_ns = max(self.delay_ns, int(min(10, max(0, seconds)) * SECOND))

    def start(self):
        self.thread.start()

    def put(self, kind, buffer, pts, route):
        duration = buffer.duration
        if duration == self.gst.CLOCK_TIME_NONE or duration <= 0:
            duration = SECOND // self.output.fps if kind == 'video' else buffer.get_size() * SECOND // (48000 * 8)
        with self.lock:
            due = pts + self.delay_ns
            if self.last_due[kind] is not None and due < self.last_due[kind]:
                self.dropped += 1
                self.drop_reasons['backwards'] += 1
                return
            self.last_due[kind] = due
            copy = buffer.copy_deep()
            if kind == 'video' and self.filler is None:
                self.filler = copy
            self.queues[kind].append((due, duration, pts, route, copy))
            self.bytes += copy.get_size()
            # Hard bounds even if a source goes wild or downstream stops consuming.
            while self.bytes > self.MAX_BYTES or (self.queues[kind] and due - self.queues[kind][0][0] > 11 * SECOND):
                oldest = min((k for k in self.queues if self.queues[k]), key=lambda k: self.queues[k][0][0])
                self.bytes -= self.queues[oldest].popleft()[-1].get_size()
                self.dropped += 1
                self.drop_reasons['capacity'] += 1

    def _next(self, kind, now):
        with self.lock:
            queue = self.queues[kind]
            while queue and queue[0][0] < now - SECOND:
                self.bytes -= queue.popleft()[-1].get_size()
                self.dropped += 1
                self.drop_reasons['late'] += 1
            if queue and queue[0][0] <= now + self.LEAD:
                due, duration, pts, route, buffer = queue.popleft()
                self.bytes -= buffer.get_size()
                end = self.ends[kind]
                if end is not None and due < end - 2_000_000:
                    self.dropped += 1
                    self.drop_reasons['overlap'] += 1
                    return None
                self.ends[kind] = due + duration
                if kind == 'video':
                    self.filler = buffer
                return buffer, due, duration, pts, route
            end = self.ends[kind]
            if self.filler is None or (end is not None and end > now + self.LEAD):
                return None
            if not queue and end is not None and now - end < SECOND:
                return None  # Normal inter-buffer jitter must not insert fake audio/video.
            # Keep publisher and viewers clocked while a new processing window fills.
            due = max(end or 0, now)
            duration = SECOND // self.output.fps if kind == 'video' else 20_000_000
            if queue:
                duration = min(duration, max(0, queue[0][0] - due))
            if duration <= 0:
                return None
            buffer = retimable(self.gst, self.filler) if kind == 'video' else self.gst.Buffer.new_wrapped(
                bytes(max(1, duration * 48000 // SECOND) * 8))
            self.ends[kind] = due + duration
            return buffer, due, duration, None, None

    def _run(self):
        while not self.stopping.wait(.005):
            try:
                now = self.output.running_time()
                for kind in self.queues:
                    item = self._next(kind, now)
                    if item:
                        self.output.release_programme(kind, *item)
            except Exception as exc:
                self.error = str(exc)

    def status(self):
        with self.lock:
            return {'seconds': self.delay_ns / SECOND, 'buffered_bytes': self.bytes,
                    'dropped_buffers': self.dropped, 'drop_reasons': dict(self.drop_reasons), 'error': self.error}

    def close(self):
        self.stopping.set()
        if self.thread.is_alive():
            self.thread.join(timeout=1)
        with self.lock:
            for queue in self.queues.values():
                queue.clear()
            self.bytes = 0
