"""The low rendition: a lighter copy of the master output on its own MediaMTX path.

MasterMedia hands this the finished picture (after every overlay, at the low frame rate)
and the AAC it already encoded, from leaky branches of its graph. Scaling, the second video
encode and the second RTSP publisher run here, in a pipeline of their own: a failure (a
MediaMTX without the path, an encoder that will not open) is logged and retried, and never
stops or stalls the full output. A phone on a cell network asks for it (master_preview.py).
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)


class LowRendition:
    RETRY_FIRST, RETRY_MAX = 5.0, 60.0
    # No buffer out of the encoder this long after starting, or since the last one: restart.
    STALL_SECONDS = 10.0

    def __init__(self, gst, rtsp_url, *, width, height, fps, video_caps, encoder):
        """``video_caps``: what MasterMedia sends, at ``fps``; ``encoder``: a launch fragment."""
        self.gst, self.rtsp_url = gst, rtsp_url
        self.description = (
            f'appsrc name=video is-live=true format=time block=false max-buffers=4 max-bytes=0 max-time=0 '
            f'leaky-type=downstream caps="{video_caps}" '
            "! queue leaky=downstream max-size-buffers=4 max-size-bytes=0 max-size-time=0 "
            f"! videoscale ! video/x-raw,width={width},height={height},pixel-aspect-ratio=1/1 "
            f"! {encoder} ! h264parse ! identity name=video_out ! publisher.sink_0 "
            "appsrc name=audio is-live=true format=time block=false max-buffers=32 max-bytes=0 max-time=0 "
            "leaky-type=downstream ! queue leaky=downstream max-size-buffers=32 max-size-bytes=0 max-size-time=0 "
            "! identity name=audio_out ! publisher.sink_1 "
            "rtspclientsink name=publisher protocols=tcp latency=100 tcp-timeout=5000000")
        self.lock = threading.Lock()
        self.pipeline = self.sources = None
        self.audio_caps = None
        self.timing = None
        self.state, self.error, self.restarts = "starting", None, 0
        self.started_at = self.last_out = 0.
        self.out = {"video": 0, "audio": 0}
        self.stopping = threading.Event()
        self.thread = None

    def start(self, timing=None):
        """``timing()``: the master pipeline's (clock, base time), to run on alike."""
        self.timing = timing
        self.thread = threading.Thread(target=self._run, name="master-low", daemon=True)
        self.thread.start()

    def push(self, kind, sample):
        """A sample from MasterMedia's ``low_video``/``low_audio`` appsink (a streaming thread)."""
        with self.lock:
            sources = self.sources
            if sources is None:
                if kind == "audio":
                    self.audio_caps = sample.get_caps()
                return
            source = sources[kind]
            if kind == "audio":
                caps = sample.get_caps()
                if caps is not None and (self.audio_caps is None or not caps.is_equal(self.audio_caps)):
                    self.audio_caps = caps
                    source.set_property("caps", caps)
        gst = self.gst
        buffer = sample.get_buffer()
        if buffer.pts != gst.CLOCK_TIME_NONE:
            running = sample.get_segment().to_running_time(gst.Format.TIME, buffer.pts)
            if running == gst.CLOCK_TIME_NONE:
                return
            if running != buffer.pts:
                buffer = buffer.copy()   # the full output holds this one too: restamp a copy
                buffer.pts, buffer.dts = running, gst.CLOCK_TIME_NONE
        source.emit("push-buffer", buffer)

    def status(self):
        with self.lock:
            return {"state": self.state, "error": self.error, "restarts": self.restarts, "url": self.rtsp_url,
                    "buffers": dict(self.out),
                    "age_seconds": round(time.monotonic() - self.last_out, 3) if self.last_out else None}

    def close(self):
        self.stopping.set()
        if self.thread is not None:
            self.thread.join(10)

    def _run(self):
        retry = self.RETRY_FIRST
        while not self.stopping.is_set():
            began = time.monotonic()
            reason = self._publish()
            if self.stopping.is_set():
                break
            if time.monotonic() - began > 300:   # it ran a good while: back off from the start
                retry = self.RETRY_FIRST
            with self.lock:
                self.state, self.error, self.restarts = "retrying", reason, self.restarts + 1
            log.warning("Low rendition stopped (%s); retrying in %.0f s", reason, retry)
            if self.stopping.wait(retry):
                break
            retry = min(retry * 2, self.RETRY_MAX)
        with self.lock:
            self.state = "stopped"

    def _publish(self):
        """Run one low pipeline until it fails or close(); returns why it stopped."""
        gst = self.gst
        try:
            pipeline = gst.parse_launch(self.description)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        try:
            pipeline.get_by_name("publisher").set_property("location", self.rtsp_url)
            pipeline.get_by_name("publisher").get_static_pad("sink_1").set_property(
                "payloader", gst.ElementFactory.make("rtpmp4gpay"))
            for kind in ("video", "audio"):
                pipeline.get_by_name(kind + "_out").get_static_pad("sink").add_probe(
                    gst.PadProbeType.BUFFER, self._observe, kind)
            clock, base_time = self.timing() if self.timing else (None, None)
            if clock is not None:
                pipeline.use_clock(clock)
                pipeline.set_start_time(gst.CLOCK_TIME_NONE)
                pipeline.set_base_time(base_time)
            sources = {kind: pipeline.get_by_name(kind) for kind in ("video", "audio")}
            with self.lock:
                if self.audio_caps is not None:
                    sources["audio"].set_property("caps", self.audio_caps)
                self.out = {"video": 0, "audio": 0}
                self.started_at, self.last_out = time.monotonic(), 0.
            if pipeline.set_state(gst.State.PLAYING) == gst.StateChangeReturn.FAILURE:
                return "the pipeline would not start"
            with self.lock:
                self.pipeline, self.sources = pipeline, sources
                self.state, self.error = "publishing", None
            bus = pipeline.get_bus()
            while not self.stopping.is_set():
                message = bus.timed_pop_filtered(gst.SECOND // 2, gst.MessageType.ERROR | gst.MessageType.EOS)
                if message is not None:
                    if message.type == gst.MessageType.EOS:
                        return "unexpected EOS"
                    error, debug = message.parse_error()
                    log.debug("Low rendition error detail: %s", debug)
                    return error.message
                with self.lock:
                    since = self.last_out or self.started_at
                if time.monotonic() - since > self.STALL_SECONDS:
                    return "stalled"
            return "closed"
        finally:
            with self.lock:
                self.pipeline = self.sources = None
            pipeline.set_state(gst.State.NULL)
            pipeline.get_state(2 * gst.SECOND)

    def _observe(self, _pad, info, kind):
        if info.get_buffer() is not None:
            with self.lock:
                self.out[kind] += 1
                if kind == "video":
                    self.last_out = time.monotonic()
        return self.gst.PadProbeReturn.OK
