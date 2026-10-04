"""Master-stream dependency inspection and bounded synthetic switching graph.

This module deliberately has no tuner/capture/control endpoints. The bench
proves the installed selectors and continuous encoders can run before real
inputs are connected. The publication observer verifies MediaMTX readers.
"""
from __future__ import annotations

import math
import shutil
import struct
import sys
import threading
import time

from .errors import ConfigError, RokuStreamError


class MasterStreamError(RokuStreamError):
    code = "master_stream_error"


BENCH_ELEMENTS = (
    "input-selector", "queue", "videotestsrc", "audiotestsrc", "capsfilter",
    "videoconvert", "audioconvert", "audioresample", "audiorate", "identity", "x264enc", "h264parse",
    "avenc_aac", "aacparse", "fakesink",
)
LIVE_ELEMENTS = ("uridecodebin", "deinterlace", "videoscale", "videorate",
                 "appsrc", "appsink", "rtspclientsink", "rtpmp4gpay", "gdkpixbufoverlay", "textoverlay", "clockoverlay")


_GLIB_LOGS_IN_C = False


def _glib_logs_without_python():
    """GLib's own warnings and criticals go straight to stderr, never through Python.

    PyGObject turns them into Python warnings, which need the GIL, and GLib can log while
    holding its global signal lock: decodebin's delayed links race and log "has no handler
    with id" from inside pad-added. A Python thread that holds the GIL and emits a signal
    (push-buffer, pull-sample) then waits for that lock, and the whole worker stops
    (10/3 14:26, preparing TBS). A handler set later wins for its domain."""
    global _GLIB_LOGS_IN_C
    if _GLIB_LOGS_IN_C:
        return
    import ctypes
    try:
        glib = ctypes.CDLL("libglib-2.0.so.0")
        glib.g_log_set_handler.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
        glib.g_log_set_handler.restype = ctypes.c_uint
        default = ctypes.cast(glib.g_log_default_handler, ctypes.c_void_p)
        for domain in (b"GLib", b"GLib-GObject", b"GLib-GIO", b"GThread"):   # those PyGObject redirects
            glib.g_log_set_handler(domain, 8 | 16, default, None)               # CRITICAL | WARNING
        _GLIB_LOGS_IN_C = True
    except (OSError, AttributeError):
        pass


def _gst():
    try:
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        _glib_logs_without_python()
        return Gst
    except (ImportError, ValueError) as exc:
        raise MasterStreamError(
            f"GStreamer Python bindings are unavailable in {sys.executable}. "
            "On this Debian host, use /usr/bin/python3 instead of Conda/virtualenv Python: "
            "/usr/bin/python3 -m roku_stream master-check. "
            "If system Python also fails, install python3-gi and gir1.2-gstreamer-1.0.",
            details={"python_executable": sys.executable, "binding_error": str(exc)},
        ) from exc


def diagnostics() -> dict:
    result = {"state": "not_configured", "can_take": False,
              "python_executable": sys.executable,
              "mediamtx_on_path": shutil.which("mediamtx") is not None,
              "note": "Dependency inspection only; no media, devices or publisher are started."}
    try:
        gst = _gst()
    except MasterStreamError as exc:
        return {**result, "gstreamer": None, "bench_available": False, "error": str(exc),
                "error_details": exc.details}
    elements = {name: gst.ElementFactory.find(name) is not None for name in BENCH_ELEMENTS + LIVE_ELEMENTS}
    return {**result, "gstreamer": gst.version_string(), "elements": elements,
            "bench_available": all(elements[name] for name in BENCH_ELEMENTS),
            "missing_live_elements": [name for name in LIVE_ELEMENTS if not elements[name]],
            "supports_drop_backwards": gst.version()[:2] >= (1, 22)}


def _description(publish: bool = False) -> str:
    # All inputs use identical raw caps and the same live pipeline clock.
    # 320x180 at 10 fps keeps this bounded bench cheap on the production host.
    queue = "queue max-size-buffers=8 max-size-bytes=0 max-size-time=500000000"
    video_out = 'identity name=video_out ! publisher.sink_0' if publish else 'fakesink name=video_out sync=true'
    audio_out = 'identity name=audio_out ! publisher.sink_1' if publish else 'fakesink name=audio_out sync=true'
    graph = [
        'input-selector name=video sync-streams=true sync-mode=clock cache-buffers=true '
        f'! {queue} ! x264enc speed-preset=ultrafast tune=zerolatency bitrate=256 key-int-max=10 '
        f'! h264parse ! {video_out}',
        'input-selector name=audio sync-streams=true sync-mode=clock cache-buffers=true '
        f'! {queue} ! identity single-segment=true ! audiorate name=audio_clock skip-to-first=true '
        f'! audioconvert ! avenc_aac ! aacparse ! {audio_out}',
    ]
    for index, (pattern, wave, frequency) in enumerate(((2, 4, 440), (4, 0, 440), (6, 0, 880))):
        graph.append(f'videotestsrc is-live=true pattern={pattern} '
                     '! video/x-raw,format=I420,width=320,height=180,framerate=10/1 '
                     f'! {queue} ! video.sink_{index}')
        graph.append(f'audiotestsrc is-live=true wave={wave} freq={frequency} samplesperbuffer=480 '
                     '! audio/x-raw,format=F32LE,rate=48000,channels=2 '
                     f'! {queue} ! audio.sink_{index}')
    if publish:
        graph.append('rtspclientsink name=publisher protocols=tcp latency=100 tcp-timeout=5000000')
    return ' '.join(graph)


def smoke_test(duration: float = 8, *, publication=None) -> dict:
    """Run bounded synthetic A/V, optionally with a publication observer."""
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 8 <= duration <= 30:
        raise ConfigError("master-smoke duration must be between 8 and 30 seconds")
    gst = _gst()
    missing = [name for name in BENCH_ELEMENTS if gst.ElementFactory.find(name) is None]
    if missing:
        raise MasterStreamError("Missing GStreamer bench elements", details={"missing": missing})
    if publication is not None and gst.ElementFactory.find("rtspclientsink") is None:
        raise MasterStreamError("Missing GStreamer RTSP publishing plugin")
    if publication is not None and gst.ElementFactory.find("rtpmp4gpay") is None:
        raise MasterStreamError("Missing MPEG4-GENERIC AAC RTP payloader")
    pipeline = gst.parse_launch(_description(publish=publication is not None))
    if publication is not None:
        # Set the URL as a property, never interpolate it into pipeline code.
        pipeline.get_by_name("publisher").set_property("location", publication.rtsp_url)
        # GStreamer's automatic AAC selection uses LATM, which this MediaMTX
        # version rejects when remuxing HLS. Send RFC 3640 MPEG4-GENERIC AAC.
        pipeline.get_by_name("publisher").get_static_pad("sink_1").set_property(
            "payloader", gst.ElementFactory.make("rtpmp4gpay"))
    bus = pipeline.get_bus()
    selectors = [pipeline.get_by_name(name) for name in ("video", "audio")]
    metrics_lock = threading.Lock()
    metrics = {kind: {"buffers": 0, "bytes": 0, "backwards": 0, "max_gap_seconds": 0.0,
                      "last_pts": None} for kind in ("video", "audio")}
    errors = []
    cuts = []
    phase = 0
    phase_started = time.monotonic()
    content = [{"video_levels": {}, "audio_buffers": 0, "audio_energy": 0.0,
                "audio_crossings": 0} for _ in range(4)]

    def observe_content(_pad, info, kind):
        buffer = info.get_buffer()
        if buffer is not None:
            raw = buffer.extract_dup(0, min(buffer.get_size(), 3840))
            with metrics_lock:
                # Content checks sample the settled signal after queued pre-cut
                # audio has drained. Encoded timing checks above include EVERY
                # buffer, including this transition interval.
                if time.monotonic() - phase_started < .25:
                    return gst.PadProbeReturn.OK
                sample = content[phase]
                if kind == "video" and raw:
                    level = raw[0]  # First I420 luma sample from the solid-color source.
                    sample["video_levels"][level] = sample["video_levels"].get(level, 0) + 1
                elif kind == "audio" and len(raw) >= 8:
                    samples = struct.unpack('<' + 'f' * (len(raw) // 4), raw[:len(raw) // 4 * 4])[::2]
                    sample["audio_buffers"] += 1
                    sample["audio_energy"] += sum(value * value for value in samples) / len(samples)
                    sample["audio_crossings"] += sum(a < 0 <= b for a, b in zip(samples, samples[1:]))
        return gst.PadProbeReturn.OK

    def observe(_pad, info, kind):
        buffer = info.get_buffer()
        if buffer is not None:
            with metrics_lock:
                track = metrics[kind]
                track["buffers"] += 1
                track["bytes"] += buffer.get_size()
                if buffer.pts != gst.CLOCK_TIME_NONE:
                    previous = track["last_pts"]
                    if previous is not None:
                        delta = (buffer.pts - previous) / gst.SECOND
                        track["backwards"] += int(delta < 0)
                        track["max_gap_seconds"] = max(track["max_gap_seconds"], delta)
                    track["last_pts"] = buffer.pts
        return gst.PadProbeReturn.OK

    def poll():
        message = bus.timed_pop_filtered(20 * gst.MSECOND, gst.MessageType.ERROR | gst.MessageType.EOS)
        if message:
            if message.type == gst.MessageType.ERROR:
                error, _debug = message.parse_error()
                raise MasterStreamError(f"Synthetic pipeline failed: {error.message}")
            raise MasterStreamError("Synthetic pipeline ended unexpectedly")
        if publication is not None:
            publication.poll()

    def take(index):
        nonlocal phase, phase_started
        # Hold both outputs idle before changing either active-pad. Probe
        # callbacks run on streaming threads; all graph changes stay here.
        probes = []
        try:
            for selector in selectors:
                idle = threading.Event()
                pad = selector.get_static_pad("src")
                def blocked(_pad, _info, event=idle):
                    event.set()
                    return gst.PadProbeReturn.OK
                probe = pad.add_probe(gst.PadProbeType.IDLE, blocked)
                probes.append((pad, probe, idle))
            deadline = time.monotonic() + 1.0
            for _pad, _probe, event in probes:
                if not event.wait(max(0, deadline - time.monotonic())):
                    raise MasterStreamError("Timed out synchronizing the synthetic A/V cut")
            for selector in selectors:
                selector.set_property("active-pad", selector.get_static_pad(f"sink_{index}"))
            with metrics_lock:
                phase += 1
                phase_started = time.monotonic()
        finally:
            for pad, probe, _event in probes:
                pad.remove_probe(probe)

    started = time.monotonic()
    try:
        for kind in metrics:
            pipeline.get_by_name(kind + "_out").get_static_pad("sink").add_probe(
                gst.PadProbeType.BUFFER, observe, kind)
        selectors[0].get_static_pad("src").add_probe(gst.PadProbeType.BUFFER, observe_content, "video")
        # Observe normalized audio on the encoder side, including any samples
        # inserted/dropped to make a continuous clock across the take.
        pipeline.get_by_name("audio_clock").get_static_pad("src").add_probe(
            gst.PadProbeType.BUFFER, observe_content, "audio")
        for selector in selectors:
            if selector.find_property("drop-backwards"):
                selector.set_property("drop-backwards", True)
            selector.set_property("active-pad", selector.get_static_pad("sink_0"))
        if pipeline.set_state(gst.State.PLAYING) == gst.StateChangeReturn.FAILURE:
            raise MasterStreamError("Cannot start synthetic pipeline")
        if publication is not None:
            publication.started(poll)
            started = time.monotonic()
        for index in (1, 2, 0):
            cut_at = started + duration * (len(cuts) + 1) / 4
            while time.monotonic() < cut_at:
                poll()
            if publication is not None:
                publication.check_phase(phase)
            take(index)
            with metrics_lock:
                counts = {kind: track["buffers"] for kind, track in metrics.items()}
            cuts.append({"input": index, "elapsed_seconds": round(time.monotonic() - started, 3),
                         "encoded_buffers": counts})
        while time.monotonic() < started + duration:
            poll()
        if publication is not None:
            publication.check_phase(phase)
    finally:
        pipeline.set_state(gst.State.NULL)
        pipeline.get_state(2 * gst.SECOND)
    for kind, track in metrics.items():
        if track["buffers"] < 20 or not track["bytes"]:
            errors.append(f"{kind}: insufficient encoded output")
        if track["backwards"] or track["max_gap_seconds"] > 0.5:
            errors.append(f"{kind}: timestamp continuity failed")
        counts = [0] + [cut["encoded_buffers"][kind] for cut in cuts] + [track["buffers"]]
        if any(after <= before for before, after in zip(counts, counts[1:])):
            errors.append(f"{kind}: output stalled between takes")
        del track["last_pts"]
    levels = []
    for sample in content:
        histogram = sample.pop("video_levels")
        sample["video_luma"] = max(histogram, key=histogram.get) if histogram else None
        levels.append(sample["video_luma"])
        count = sample["audio_buffers"]
        sample["mean_audio_energy"] = sample.pop("audio_energy") / max(count, 1)
        sample["mean_audio_crossings"] = sample.pop("audio_crossings") / max(count, 1)
        if count < 10 or sum(histogram.values()) < 5:
            errors.append("Too few content samples to verify a synthetic take")
    if None in levels or len(set(levels[:3])) != 3 or levels[0] != levels[3]:
        errors.append("Video did not switch from fallback through both colors and back")
    if (content[0]["mean_audio_energy"] > .01 or content[3]["mean_audio_energy"] > .01
            or min(content[i]["mean_audio_energy"] for i in (1, 2)) < .05
            or content[2]["mean_audio_crossings"] < content[1]["mean_audio_crossings"] * 1.5):
        errors.append("Audio did not switch from silence through both tones and back")
    result = {"ok": not errors, "mode": "synthetic_rtsp_publish" if publication else "synthetic_encode_and_discard", "duration_seconds": duration,
              "cuts": cuts, "tracks": metrics, "content_phases": content,
              "content_settle_seconds": .25, "errors": errors,
              "limitations": ("Synthetic feeds only; no tuner, capture or real-input A/V sync was tested." if publication else
                              "No tuner, capture, RTSP publish, MediaMTX subscriber, or real-input A/V sync was tested.")}
    if errors:
        raise MasterStreamError("Synthetic switching checks failed", details=result)
    return result
