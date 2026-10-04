"""Continuously drain decoded frames, retaining only the newest image."""

import subprocess
import threading
import time

from .errors import NavigationError
from .feedback import PpmFrame


def contribution_output(url):
    """A second output on the existing device reader, isolated from PPM capture.

    FIFO owns the network writer thread and drops packets instead of blocking the
    verification branch. Recovery resumes at a keyframe. Video stays compressed;
    audio is normalized to AAC for the private RTSP contribution.
    """
    return ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
            "-flags:a", "+global_header", "-f", "fifo", "-fifo_format", "rtsp",
            "-format_opts", "rtsp_transport=tcp", "-queue_size", "60",
            "-drop_pkts_on_overflow", "1", "-attempt_recovery", "1",
            "-recover_any_error", "1", "-recovery_wait_time", "1",
            "-restart_with_keyframe", "1", url]


class CaptureStream:
    def __init__(self, command):
        self.condition = threading.Condition()
        self.sequence = 0
        self.frame = None
        self.error = None
        self.last_frame_at = None
        self.max_frame_gap = 0.
        self.last_long_gap = None
        self.stderr_tail = b''
        self.process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stderr_reader = threading.Thread(target=self._read_stderr, daemon=True)
        self.stderr_reader.start()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read_stderr(self):
        try:
            while chunk := self.process.stderr.read1(4096):
                with self.condition:
                    self.stderr_tail = (self.stderr_tail + chunk)[-8192:]
        except OSError:
            pass

    def status(self):
        with self.condition:
            return {'pid': self.process.pid, 'returncode': self.process.poll(), 'frames': self.sequence,
                    'frame_age_seconds': round(time.monotonic() - self.last_frame_at, 3) if self.last_frame_at else None,
                    'max_frame_gap_seconds': round(self.max_frame_gap, 3),
                    'last_gap_over_second': self.last_long_gap,
                    'error': self.error, 'ffmpeg_stderr': self.stderr_tail.decode(errors='replace')}

    def _read(self):
        try:
            pipe = self.process.stdout
            while True:
                # FFmpeg's PPM encoder emits these three header lines.
                if pipe.readline(32) != b"P6\n":
                    raise ValueError("Capture stream ended or returned an invalid image")
                width, height = map(int, pipe.readline(64).split())
                if not (0 < width <= 4096 and 0 < height <= 2160):
                    raise ValueError("Invalid capture dimensions")
                if pipe.readline(32) != b"255\n":
                    raise ValueError("Invalid capture pixel format")
                rgb = pipe.read(width * height * 3)
                if len(rgb) != width * height * 3:
                    raise ValueError("Capture stream returned a truncated image")
                with self.condition:
                    now = time.monotonic()
                    if self.last_frame_at:
                        gap = now - self.last_frame_at
                        self.max_frame_gap = max(self.max_frame_gap, gap)
                        if gap >= 1:
                            self.last_long_gap = {'at': time.time(), 'seconds': round(gap, 3)}
                    self.last_frame_at = now
                    self.frame = PpmFrame(width, height, rgb)
                    self.sequence += 1
                    self.condition.notify_all()
        except (OSError, ValueError) as exc:
            with self.condition:
                self.error = str(exc)
                self.condition.notify_all()

    def next_frame(self, timeout, check_cancelled):
        deadline = time.monotonic() + timeout
        with self.condition:
            # Pass two decoded frames after the request barrier, matching the
            # startup discard used by one-shot capture. Never return a cache hit.
            target = self.sequence + 3
            while True:
                check_cancelled(0)
                if self.error or self.process.poll() is not None:
                    raise NavigationError(self.error or "Capture stream stopped")
                if self.sequence >= target:
                    return self.frame
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NavigationError("Direct Roku capture timed out waiting for a fresh frame")
                self.condition.wait(min(.1, remaining))

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        self.reader.join(timeout=2)
        self.stderr_reader.join(timeout=2)
        self.process.stdout.close()
        self.process.stderr.close()
