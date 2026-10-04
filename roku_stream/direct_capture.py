from __future__ import annotations

import atexit
import json
import logging
import os
import re
import stat
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import FeedbackConfig
from .capture_stream import CaptureStream, contribution_output
from .errors import CueCancelledError, NavigationError
from .feedback import PpmFrame, VisualFeedback


class DirectCaptureFeedback(VisualFeedback):
    """Read bounded frames from the Roku's local V4L2 capture device."""

    def __init__(self, config: FeedbackConfig) -> None:
        super().__init__(config)
        if not config.device:
            raise ValueError("Direct capture requires a device")
        self.device = Path(config.device)
        self._capture_lock = threading.Lock()
        self._stream_id = uuid.uuid4().hex
        self._identity = None
        self._sequence = 0
        self._stream = None
        self.last_stream_failure = None
        self._input_signature = None
        self._stream_signature = None
        self._signal_lock = threading.Lock()
        self._signal_cache = None
        self._signal_checked = 0.0
        self.preview_allowed = lambda: True
        self._contribution_stop = threading.Event()
        self._contribution_thread = None
        atexit.register(self.close)

    def start_contribution(self) -> None:
        """Keep the shared capture alive without a browser or active cue."""
        if not self.config.contribution_url or self._contribution_thread is not None:
            return
        self._contribution_thread = threading.Thread(target=self._maintain_contribution,
                                                     name="roku-contribution", daemon=True)
        self._contribution_thread.start()

    def _maintain_contribution(self) -> None:
        while not self._contribution_stop.is_set():
            if self.preview_allowed():
                try:
                    # Non-recording observations never replace cue evidence.
                    # _capture handles stale processes and device replacement.
                    self._capture(record=False)
                except (NavigationError, CueCancelledError):
                    pass  # Retry after a bounded pause; source status stays truthful.
            self._contribution_stop.wait(2)

    def close(self) -> None:
        self._contribution_stop.set()
        if self._contribution_thread is not None:
            self._contribution_thread.join(timeout=self.config.capture_timeout_seconds + 2)
        with self._capture_lock:
            self._close_stream()

    def _close_stream(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def status(self) -> dict[str, object]:
        try:
            info = self.device.stat()
            ready = stat.S_ISCHR(info.st_mode) and os.access(self.device, os.R_OK | os.W_OK)
        except OSError:
            ready = False
        stream = self._stream
        return {"backend": "direct", "device": str(self.device), "ready": ready,
                "stream_id": self._stream_id, "last_capture": self.last_capture,
                "capture": stream.status() if stream else None,
                "last_stream_failure": self.last_stream_failure}

    def input_signal(self) -> dict[str, object]:
        """Query the incoming signal, not the driver's last configured size."""
        # Several calibration tabs must not queue concurrent USB timing queries.
        # Keep this independent of the capture/navigation lock and its deadlines.
        with self._signal_lock:
            if self._signal_cache is not None and time.monotonic() - self._signal_checked < .25:
                return dict(self._signal_cache)
            result = self._query_input_signal()
            result['observed_at'] = datetime.now(timezone.utc).isoformat()
            self._signal_cache = result
            self._signal_checked = time.monotonic()
            return dict(result)

    def _query_input_signal(self) -> dict[str, object]:
        if not self.status()['ready']:
            result = {"state": "unavailable", "label": "Capture device unavailable"}
        elif self.config.input_format != 'mpegts':
            result = {"state": "unknown", "label": "Input resolution unavailable"}
        else:
            try:
                probe = subprocess.run(
                    ['/usr/bin/v4l2-ctl', '--device', str(self.device), '--query-dv-timings'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2,
                )
                result = self._parse_input_signal(probe.returncode, probe.stdout + probe.stderr)
            except subprocess.TimeoutExpired:
                result = {"state": "unknown", "label": "Input timing query timed out"}
            except OSError as exc:
                result = {"state": "unknown", "label": "Input resolution unavailable", "error": str(exc)}
        signature = (result['state'], result.get('width'), result.get('height'),
                     result.get('scan'), result.get('rate'))
        # The first diagnostic query establishes a baseline, not evidence of a
        # format change. Restarting here would revoke an otherwise valid Roku
        # selection merely because an operator opened the source controls.
        if self._input_signature is None and self._stream_signature is None:
            self._stream_signature = signature
        self._input_signature = signature
        return result

    @staticmethod
    def _parse_input_signal(returncode: int, output: str) -> dict[str, object]:
        if returncode:
            if 'No locks available' in output or 'Link has been severed' in output:
                return {"state": "no_signal", "label": "No component signal"}
            if 'No such device' in output or 'No such file' in output:
                return {"state": "unavailable", "label": "Capture device disconnected"}
            if 'Device or resource busy' in output:
                return {"state": "busy", "label": "Capture device busy"}
            return {"state": "unknown", "label": "Input resolution unavailable", "error": output.strip()[-1000:]}
        width = re.search(r'Active width:\s*(\d+)', output)
        height = re.search(r'Active height:\s*(\d+)', output)
        scan = re.search(r'Frame format:\s*(interlaced|progressive)', output)
        rate = re.search(r'\(([\d.]+) (fields|frames) per second\)', output)
        if not width or not height or not scan or not int(width[1]) or not int(height[1]):
            return {"state": "unknown", "label": "Input resolution unavailable"}
        label = f'{width[1]} × {height[1]} · {scan[1]}'
        if rate:
            label += f' · {rate[1]} {rate[2]}/s'
        return {"state": "locked", "width": int(width[1]), "height": int(height[1]),
                "scan": scan[1], "rate": float(rate[1]) if rate else None, "label": label}

    def assert_ready(self) -> dict[str, object]:
        status = self.status()
        if not status["ready"]:
            raise NavigationError("The Roku capture device is missing or inaccessible", details=status)
        return status

    def source_catalog(self) -> dict[str, object]:
        status = self.status()
        key = f"direct:{self.device}"
        return {"sources": [{"key": key, "source": "direct", "source_id": key,
                             "name": self.config.source_name, "detail": str(self.device),
                             "available": status["ready"]}],
                "selected": key, "required": key, "ready": status["ready"]}

    def select_source(self, key: str) -> dict[str, object]:
        if key != f"direct:{self.device}":
            raise NavigationError("Only the configured direct Roku capture input is available")
        self.capture()
        return self.source_catalog()

    def _run(self, command: list[str], *, input_data: bytes | None = None,
             allow_empty: bool = False) -> bytes:
        """Bound subprocess lifetime and reap it even when a cue is cancelled."""
        input_file = None
        try:
            if input_data is not None:
                # Python 3.11 communicate(input=None) after a timeout does not
                # resume a partially written stdin pipe. Give the encoder a
                # complete, seekable frame so cancellation polling cannot
                # strand it waiting for the remainder of a large PPM image.
                input_file = tempfile.TemporaryFile()
                input_file.write(input_data)
                input_file.seek(0)
            process = subprocess.Popen(command, stdin=input_file if input_file is not None else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            raise NavigationError(f"Cannot start direct Roku capture: {exc}") from exc
        finally:
            if input_file is not None:
                input_file.close()  # The child owns its inherited descriptor.
        deadline = time.monotonic() + self.config.capture_timeout_seconds
        try:
            while True:
                self.wait(0)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NavigationError("Direct Roku capture timed out", details={"device": str(self.device)})
                try:
                    stdout, stderr = process.communicate(timeout=min(.25, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode or (not stdout and not allow_empty):
                raise NavigationError("Cannot read the Roku capture input; check its connection and whether another app is using it",
                                      details={"device": str(self.device), "ffmpeg": stderr.decode(errors="replace")[-1000:]})
            return stdout
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate()

    def _capture(self, *, record: bool) -> PpmFrame:
        deadline = time.monotonic() + self.config.capture_timeout_seconds
        while not self._capture_lock.acquire(timeout=.25):
            self.wait(0)
            if time.monotonic() >= deadline:
                raise NavigationError("The Roku capture input is busy with another observation")
        try:
            try:
                self.assert_ready()
            except NavigationError:
                self._close_stream()
                raise
            info = self.device.stat()
            identity = (info.st_rdev, info.st_ino)
            if self._identity != identity:
                self._close_stream()
                self._identity = identity
                self._stream_id = uuid.uuid4().hex
            barrier = datetime.now(timezone.utc).isoformat()
            input_options = []
            if self.config.video_standard:
                input_options += ["-standard", self.config.video_standard]
            if self.config.input_index is not None:
                input_options += ["-channel", str(self.config.input_index)]
            if self.config.input_format == "mpegts":
                if self._stream_signature != self._input_signature:
                    self._close_stream()
                    self._stream_signature = self._input_signature
                # HD PVR exposes a read-only MPEG transport stream rather than
                # the streaming-buffer interface used by FFmpeg's V4L2 input.
                controls = []
                if self.config.input_index is not None:
                    controls += [f"--set-input={self.config.input_index}"]
                if self.config.video_standard:
                    controls += [f"--set-standard={self.config.video_standard}"]
                if controls and self._stream is None:
                    self._run(["/usr/bin/v4l2-ctl", "--device", str(self.device), *controls],
                              allow_empty=True)
                capture_options = ["-f", "mpegts"]
            else:
                capture_options = ["-f", "v4l2", *input_options,
                                   "-input_format", self.config.input_format,
                                   "-video_size", "720x480"]
            command = [self.config.ffmpeg_path, "-hide_banner", "-loglevel", "error",
                       *capture_options, "-i", str(self.device), "-an",
                       "-vf", "bwdif=mode=send_frame:parity=auto:deint=interlaced,select=gte(n\\,2)",
                       "-frames:v", "1", "-f", "image2pipe", "-vcodec", "ppm", "pipe:1"]
            if self.config.input_format == "mpegts":
                if self._stream is None:
                    # Keep the HD PVR awake and drain output even when no UI is
                    # watching. The reader stores one image, not a frame queue.
                    # A newly opened transport stream can start before its
                    # codec headers. Allow enough probe data to reach them;
                    # 32 KiB can exit with "unknown codec" after a restart.
                    continuous = [self.config.ffmpeg_path, "-hide_banner", "-loglevel", "error",
                                  "-probesize", "2097152", "-analyzeduration", "3000000",
                                  *capture_options, "-i", str(self.device), "-an",
                                  "-vf", "bwdif=mode=send_frame:parity=auto:deint=interlaced",
                                  "-f", "image2pipe", "-vcodec", "ppm", "-flush_packets", "1", "pipe:1"]
                    if self.config.contribution_url:
                        continuous += contribution_output(self.config.contribution_url)
                    self._stream = CaptureStream(continuous)
                    self._stream_id = uuid.uuid4().hex
                try:
                    frame = self._stream.next_frame(self.config.capture_timeout_seconds, self.wait)
                except NavigationError as exc:
                    self.last_stream_failure = {'at': datetime.now(timezone.utc).isoformat(),
                        'stream_id': self._stream_id, 'error': str(exc), 'capture': self._stream.status()}
                    logging.getLogger(__name__).warning('Roku capture failed: %s', json.dumps(self.last_stream_failure, default=str))
                    self._close_stream()
                    raise
            else:
                frame = PpmFrame.parse(self._run(command))
            current = self.device.stat()
            if (current.st_rdev, current.st_ino) != identity:
                self._close_stream()
                raise NavigationError("Roku capture device changed during observation")
            if record:
                self._sequence += 1
                self.last_frame = frame
                self.last_capture = {"backend": "direct", "device": str(self.device),
                                     "fresh": True, "stream_id": self._stream_id,
                                     "sequence": self._sequence, "barrier_at": barrier,
                                     "observed_at": datetime.now(timezone.utc).isoformat()}
                if self.on_capture:
                    self.on_capture(dict(self.last_capture))
            return frame
        except OSError as exc:
            self._close_stream()
            raise NavigationError(f"Cannot access the Roku capture input: {exc}") from exc
        finally:
            self._capture_lock.release()

    def capture(self) -> PpmFrame:
        # Encoded inputs stay open; every observation waits for new frames.
        return self._capture(record=True)

    def preview_frames(self) -> Iterator[bytes]:
        # Share the serialized capture reader with navigation. Non-recording
        # frames cannot replace the evidence used to verify a channel/game.
        while True:
            frame = self._capture(record=False)
            payload = f"P6\n{frame.width} {frame.height}\n255\n".encode() + frame.rgb
            yield self._run([self.config.ffmpeg_path, "-hide_banner", "-loglevel", "error",
                             "-f", "image2pipe", "-vcodec", "ppm", "-i", "pipe:0",
                             "-frames:v", "1", "-q:v", "5", "-f", "mjpeg", "pipe:1"], input_data=payload)
            time.sleep(.5)
