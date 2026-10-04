"""Isolated MediaMTX publication workflow and independent subscriber checks."""
from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import struct
import subprocess
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import urlopen
import uuid

from .errors import ConfigError
from .master import MasterStreamError, _gst, smoke_test


@contextmanager
def cancellation_handlers():
    """Make SIGTERM unwind owned pipeline/server cleanup like Ctrl-C does."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    previous = signal.getsignal(signal.SIGTERM)
    def terminate(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def candidate_config(ports: tuple[int, int, int], path: str) -> dict:
    """No catch-all path, UDP, public listener, hooks, or recording."""
    if not re.fullmatch(r"vv-publication-[0-9a-f]{32}", path):
        raise ConfigError("Invalid isolated publication path")
    if len(set(ports)) != 3 or any(isinstance(p, bool) or not isinstance(p, int) or not 1 <= p <= 65535 for p in ports):
        raise ConfigError("Publication ports must be three distinct valid ports")
    rtsp, hls, api = ports
    return {"logLevel": "info", "logDestinations": ["stdout"],
            "rtsp": True, "rtspAddress": f"127.0.0.1:{rtsp}", "rtspTransports": ["tcp"],
            "hls": True, "hlsAddress": f"127.0.0.1:{hls}", "hlsVariant": "fmp4",
            "hlsAlwaysRemux": True, "hlsSegmentCount": 7, "hlsSegmentDuration": "1s",
            "hlsSegmentMaxSize": "2M", "hlsDirectory": "",
            "api": True, "apiAddress": f"127.0.0.1:{api}",
            "rtmp": False, "webrtc": False, "srt": False, "moq": False,
            "playback": False, "metrics": False, "pprof": False,
            "authInternalUsers": [{"user": "any", "ips": ["127.0.0.1"], "permissions": [
                {"action": "publish", "path": path}, {"action": "read", "path": path}, {"action": "api"}]}],
            "paths": {path: {"source": "publisher", "overridePublisher": False, "record": False}}}


def _free_ports() -> tuple[int, int, int]:
    sockets = []
    try:
        for _ in range(3):
            s = socket.socket()
            sockets.append(s)
            s.bind(("127.0.0.1", 0))
        return tuple(s.getsockname()[1] for s in sockets)
    finally:
        for s in sockets:
            s.close()


def _read(url: str, timeout: float = 2.0, limit: int = 3 * 1024 * 1024) -> bytes:
    with urlopen(url, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise MasterStreamError("Publication response exceeded its size limit")
    return data


def _json(url: str) -> dict:
    data = json.loads(_read(url))
    if not isinstance(data, dict):
        raise MasterStreamError("Invalid MediaMTX API response")
    return data


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)


class LocalMediaMtx:
    def __init__(self, executable: Path, directory: Path):
        self.path = "vv-publication-" + uuid.uuid4().hex
        self.ports = _free_ports()
        self.rtsp_url = f"rtsp://127.0.0.1:{self.ports[0]}/{self.path}"
        self.hls_url = f"http://127.0.0.1:{self.ports[1]}/{self.path}/index.m3u8"
        self.api_url = f"http://127.0.0.1:{self.ports[2]}/v3/"
        self.directory = directory
        self.log_path = directory / "mediamtx.log"
        self.log = None
        self.process = None
        self.executable = executable

    def __enter__(self):
        config_path = self.directory / "mediamtx.yml"
        config_path.write_text(json.dumps(candidate_config(self.ports, self.path), indent=2) + "\n")
        self.log = self.log_path.open("wb")
        # Inherited MTX_* variables must not turn this isolated server into a
        # production listener or enable hooks/recording.
        env = {k: v for k, v in os.environ.items() if not k.startswith("MTX_")}
        try:
            self.process = subprocess.Popen([str(self.executable), str(config_path)], cwd=self.directory,
                                            env=env, stdin=subprocess.DEVNULL, stdout=self.log,
                                            stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                self.check()
                try:
                    _json(self.api_url + "paths/list")
                    return self
                except (URLError, OSError, ValueError):
                    time.sleep(.1)
            raise MasterStreamError("Timed out starting isolated MediaMTX")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def check(self):
        if self.process is not None and self.process.poll() is not None:
            raise MasterStreamError("Isolated MediaMTX exited", details={"log": self.log_path.read_text(errors="replace")[-4000:]})

    def status(self) -> dict:
        self.check()
        return _json(self.api_url + "paths/get/" + self.path)

    def sessions(self) -> list:
        return _json(self.api_url + "rtspsessions/list").get("items", [])

    def __exit__(self, *_):
        if self.process is not None:
            _stop(self.process)
        if self.log is not None:
            self.log.close()


class PublicationMonitor:
    """Observe the served feed, not the publisher's local encoder buffers."""
    def __init__(self, server: LocalMediaMtx):
        self.server = server
        self.rtsp_url = server.rtsp_url
        self.gst = _gst()
        self.pipeline = None
        self.lock = threading.Lock()
        self.tracks = {kind: {"buffers": 0, "backwards": 0, "max_pts_gap_seconds": 0.0,
                              "max_arrival_gap_seconds": 0.0, "last_pts": None, "last_at": None,
                              "samples": deque(maxlen=10 if kind == "video" else 20)}
                       for kind in ("video", "audio")}
        self.phases = []
        self.publisher_id = None
        self.reader_id = None
        self.hls_sequences = {}
        self.hls_probe = None
        self.stage = "starting_publisher"

    def _sample(self, _pad, info, kind):
        buffer = info.get_buffer()
        if buffer is None:
            return self.gst.PadProbeReturn.OK
        now = time.monotonic()
        with self.lock:
            track = self.tracks[kind]
            track["buffers"] += 1
            if buffer.pts != self.gst.CLOCK_TIME_NONE:
                previous = track["last_pts"]
                if previous is not None:
                    delta = (buffer.pts - previous) / self.gst.SECOND
                    track["backwards"] += int(delta < 0)
                    track["max_pts_gap_seconds"] = max(track["max_pts_gap_seconds"], delta)
                track["last_pts"] = buffer.pts
            if track["last_at"] is not None:
                track["max_arrival_gap_seconds"] = max(track["max_arrival_gap_seconds"], now - track["last_at"])
            track["last_at"] = now
            raw = buffer.extract_dup(0, min(buffer.get_size(), 3840))
            if kind == "video" and raw:
                track["samples"].append(raw[0])
            elif kind == "audio" and len(raw) >= 8:
                samples = struct.unpack('<' + 'f' * (len(raw) // 4), raw[:len(raw) // 4 * 4])[::2]
                energy = sum(v * v for v in samples) / len(samples)
                crossings = sum(a < 0 <= b for a, b in zip(samples, samples[1:]))
                track["samples"].append((energy, crossings))
        return self.gst.PadProbeReturn.OK

    def started(self, poll_publisher):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            poll_publisher()
            status = self.server.status()
            if status.get("ready"):
                self.publisher_id = status.get("source", {}).get("id")
                break
        else:
            raise MasterStreamError("Publisher never became ready in MediaMTX")
        if not self.publisher_id:
            raise MasterStreamError("MediaMTX did not identify the publisher")
        self.stage = "starting_rtsp_reader"
        graph = ('rtspsrc name=reader protocols=tcp latency=100 tcp-timeout=5000000 '
                 'reader. ! application/x-rtp,media=video ! queue ! decodebin ! videoconvert '
                 '! video/x-raw,format=I420 ! fakesink name=read_video sync=true '
                 'reader. ! application/x-rtp,media=audio ! queue ! decodebin ! audioconvert ! audioresample '
                 '! audio/x-raw,format=F32LE,channels=2,rate=48000,layout=interleaved '
                 '! fakesink name=read_audio sync=true')
        self.pipeline = self.gst.parse_launch(graph)
        self.pipeline.get_by_name("reader").set_property("location", self.rtsp_url)
        for kind in self.tracks:
            self.pipeline.get_by_name("read_" + kind).get_static_pad("sink").add_probe(
                self.gst.PadProbeType.BUFFER, self._sample, kind)
        if self.pipeline.set_state(self.gst.State.PLAYING) == self.gst.StateChangeReturn.FAILURE:
            raise MasterStreamError("Cannot start independent RTSP subscriber")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            poll_publisher()
            with self.lock:
                if all(track["buffers"] >= 10 for track in self.tracks.values()):
                    break
        else:
            raise MasterStreamError("RTSP subscriber did not decode both tracks")
        readers = [s for s in self.server.sessions() if s.get("state") == "read" and s.get("path") == self.server.path]
        if len(readers) != 1:
            raise MasterStreamError("Expected one independent RTSP reader", details={"sessions": readers})
        self.reader_id = readers[0]["id"]

    def poll(self):
        self.server.check()
        if self.pipeline is not None:
            message = self.pipeline.get_bus().pop_filtered(self.gst.MessageType.ERROR | self.gst.MessageType.EOS)
            if message:
                if message.type == self.gst.MessageType.ERROR:
                    error, _debug = message.parse_error()
                    raise MasterStreamError("RTSP subscriber failed: " + error.message)
                raise MasterStreamError("RTSP subscriber ended during publication")

    def _hls(self):
        self.stage = "checking_hls"
        root = self.server.hls_url
        text = _read(root).decode("utf-8")
        if not text.startswith("#EXTM3U"):
            raise MasterStreamError("MediaMTX did not serve an HLS playlist")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if any(line.startswith("#EXT-X-STREAM-INF:") for line in lines):
            video = next(line for line in lines if not line.startswith("#"))
            playlists = {"video": self._hls_url(root, video)}
            # MediaMTX can serve audio in a separate HLS rendition. Validate
            # its complete segments too instead of expecting multiplexed fMP4.
            audio = next((line for line in lines if line.startswith("#EXT-X-MEDIA:")
                          and "TYPE=AUDIO" in line), None)
            if audio:
                uri = re.search(r'URI="([^"]+)"', audio)
                if uri:
                    playlists["audio"] = self._hls_url(root, uri[1])
        else:
            playlists = {"media": root}
        streams = []
        for label, url in playlists.items():
            streams.extend(self._hls_rendition(label, url))
        if {s.get("codec_name") for s in streams} != {"h264", "aac"}:
            raise MasterStreamError("HLS did not contain H.264 and AAC", details={"streams": streams})
        self.hls_probe = [{k: s.get(k) for k in ("codec_name", "codec_type", "width", "height", "sample_rate", "channels")}
                          for s in streams]

    def _hls_rendition(self, label: str, url: str) -> list:
        text = _read(url).decode("utf-8")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        sequence = next((int(line.split(":", 1)[1]) for line in lines if line.startswith("#EXT-X-MEDIA-SEQUENCE:")), None)
        segments = [line for line in lines if not line.startswith("#")]
        init = re.search(r'#EXT-X-MAP:.*?URI="([^"]+)"', text)
        if sequence is None or not segments or init is None or "#EXT-X-ENDLIST" in lines:
            raise MasterStreamError("HLS did not expose a complete live fMP4 segment")
        history = self.hls_sequences.setdefault(label, [])
        if history and sequence < history[-1]:
            raise MasterStreamError("HLS media sequence went backwards across a take")
        history.append(sequence)
        media = _read(self._hls_url(url, init[1])) + _read(self._hls_url(url, segments[-1]))
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", "-i", "pipe:0"],
                                input=media, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if result.returncode:
            raise MasterStreamError("Served HLS segment could not be probed")
        decoded = subprocess.run(["ffmpeg", "-v", "error", "-xerror", "-i", "pipe:0", "-map", "0", "-f", "null", "-"],
                                 input=media, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        if decoded.returncode:
            raise MasterStreamError("Served HLS segment could not be decoded",
                                    details={"decoder_error": decoded.stderr.decode(errors="replace")[-1000:]})
        return json.loads(result.stdout).get("streams", [])

    def _hls_url(self, base: str, path: str) -> str:
        url = urljoin(base, path)
        parsed = urlsplit(url)
        expected = urlsplit(self.server.hls_url)
        if parsed.scheme != "http" or parsed.netloc != expected.netloc or not parsed.path.startswith('/' + self.server.path + '/'):
            raise MasterStreamError("HLS descriptor escaped the isolated master path")
        return url

    def check_phase(self, phase: int):
        self.stage = f"checking_rtsp_phase_{phase}"
        self.poll()
        status = self.server.status()
        if not status.get("ready") or status.get("source", {}).get("id") != self.publisher_id:
            raise MasterStreamError("Master publication changed or became unavailable across a take")
        ids = {s.get("id") for s in self.server.sessions() if s.get("state") == "read"}
        if self.reader_id not in ids:
            raise MasterStreamError("RTSP reader reconnected or disappeared across a take")
        with self.lock:
            video = list(self.tracks["video"]["samples"])
            audio = list(self.tracks["audio"]["samples"])
            if not video or not audio:
                raise MasterStreamError("Subscriber has no content samples")
            if any(time.monotonic() - t["last_at"] > 1.0 for t in self.tracks.values()):
                raise MasterStreamError("Subscriber stopped receiving fresh media")
            luma = sorted(video)[len(video) // 2]
            energy = sum(a[0] for a in audio) / len(audio)
            crossings = sum(a[1] for a in audio) / len(audio)
            counts = {kind: track["buffers"] for kind, track in self.tracks.items()}
        expected_luma = (16, 81, 41, 16)[phase]
        if abs(luma - expected_luma) > 3:
            raise MasterStreamError("RTSP video did not reflect the selected source", details={"phase": phase, "luma": luma})
        if (phase in (0, 3) and energy > .01) or (phase in (1, 2) and energy < .05):
            raise MasterStreamError("RTSP audio did not reflect the selected source", details={"phase": phase, "energy": energy})
        if phase == 2 and crossings < self.phases[1]["audio_crossings"] * 1.5:
            raise MasterStreamError("RTSP subscriber did not receive the higher-frequency tone")
        self.phases.append({"phase": phase, "luma": luma, "audio_energy": energy,
                            "audio_crossings": crossings, "decoded_buffers": counts})
        self._hls()

    def close_reader(self):
        if self.pipeline is not None:
            self.pipeline.set_state(self.gst.State.NULL)
            self.pipeline.get_state(2 * self.gst.SECOND)
            self.pipeline = None

    def finished(self) -> dict:
        self.stage = "checking_release"
        self.close_reader()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if not self.server.status().get("ready") and not self.server.sessions():
                break
            time.sleep(.1)
        else:
            raise MasterStreamError("Publisher/reader session was not released on stop")
        errors = []
        summary = {}
        for kind, track in self.tracks.items():
            summary[kind] = {k: v for k, v in track.items() if k not in ("samples", "last_pts", "last_at")}
            if track["backwards"] or track["max_pts_gap_seconds"] > .5 or track["max_arrival_gap_seconds"] > 1.0:
                errors.append(f"{kind} subscriber continuity failed")
        if not self.hls_sequences or any(len(set(history)) < 2 for history in self.hls_sequences.values()):
            errors.append("HLS media playlist did not advance")
        if errors:
            raise MasterStreamError("Publication validation failed", details={"errors": errors, "tracks": summary})
        return {"ready_verified": True, "publisher_id": self.publisher_id, "reader_id": self.reader_id,
                "reader_reconnects": 0, "tracks": summary, "phases": self.phases,
                "hls_media_sequences": self.hls_sequences, "hls_streams": self.hls_probe,
                "released_on_stop": True}


def publication_test(*, executable: str | Path | None = None, duration: float = 20) -> dict:
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 16 <= duration <= 30:
        raise ConfigError("Publication test duration must be between 16 and 30 seconds")
    # Catch an incompatible Conda/venv interpreter before starting MediaMTX
    # or opening sockets so the diagnostic points to the real prerequisite.
    _gst()
    if executable is None:
        executable = shutil.which("mediamtx") or Path(__file__).resolve().parents[1] / "vendor/mediamtx/1.21.0/mediamtx"
    executable = Path(executable).expanduser().resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ConfigError("MediaMTX executable not found; run deploy/fetch-mediamtx.py or pass --mediamtx")
    if any(shutil.which(name) is None for name in ("ffprobe", "ffmpeg")):
        raise ConfigError("ffprobe and ffmpeg are required to validate HLS segments")
    try:
        with cancellation_handlers(), tempfile.TemporaryDirectory(prefix="vizelvision-publication-", dir="/tmp") as work:
            with LocalMediaMtx(executable, Path(work)) as server:
                monitor = PublicationMonitor(server)
                try:
                    publisher = smoke_test(duration, publication=monitor)
                    publication = monitor.finished()
                    version = subprocess.run([str(executable), "--version"], stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, timeout=3, check=True).stdout.decode().strip()
                    return {"ok": True, "mediamtx_version": version, "master_path": server.path,
                            "publisher": publisher, "publication": publication,
                            "scope": "Isolated loopback server and synthetic feeds; no production service or capture hardware changed."}
                except Exception as exc:
                    details = {"stage": monitor.stage, "server_log": server.log_path.read_text(errors="replace")[-6000:]}
                    if isinstance(exc, MasterStreamError):
                        exc.details.update(details)
                        raise
                    if isinstance(exc, HTTPError):
                        details["http_status"] = exc.code
                        details["http_body"] = exc.read(1000).decode(errors="replace")
                    raise MasterStreamError(f"Publication workflow failed ({type(exc).__name__})", details=details) from exc
                finally:
                    monitor.close_reader()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise MasterStreamError(f"Publication workflow failed ({type(exc).__name__}): {exc}") from exc
