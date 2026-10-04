"""Opt-in real-media check: the station ID holds its end card, then plays on, with an
unbroken timeline. Uses the real ID file and FileInput; the master output is a small
stand-in (appsrc -> fakesink), so no encoder, publisher or hardware is used.

Run from the repository root with: nice -n 19 /usr/bin/python3 tests/ident_hold_integration.py
Checks: while held, both tracks keep arriving just ahead of the clock (a frame repeats,
audio is silent) and the file does not advance; after the hold the file resumes at its
end card and plays to the end; timestamps never go backwards, and no gap exceeds 150 ms
(the master output's videorate and audiorate fill small gaps).
"""
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from roku_stream.ident import IDENT_HOLD_AT, IDENT_PATH
from roku_stream.master_media import FileInput, _gst

HOLD_SECONDS = 5


class Output:
    """What FileInput needs from MasterMedia: its slot's appsrcs, caps, clock and fps."""

    def __init__(self):
        self.gst = gst = _gst()
        self.fps = 30
        self.video_caps = ("video/x-raw,format=I420,width=320,height=180,framerate=30/1,pixel-aspect-ratio=1/1,"
                           "interlace-mode=progressive,colorimetry=bt709,chroma-site=mpeg2")
        self.audio_caps = "audio/x-raw,format=F32LE,rate=48000,channels=2,layout=interleaved"
        graph = " ".join(f'appsrc name={kind}_3 is-live=true format=time block=false max-buffers=8 max-bytes=0 '
                         f'max-time=500000000 leaky-type=downstream caps="{caps}" ! fakesink name={kind}_sink sync=false'
                         for kind, caps in (("video", self.video_caps), ("audio", self.audio_caps)))
        self.pipeline = gst.parse_launch(graph)
        self.active = 3
        self.seen = {"video": [], "audio": []}
        self.lock = threading.Lock()
        for kind in self.seen:
            self.pipeline.get_by_name(kind + "_sink").get_static_pad("sink").add_probe(
                gst.PadProbeType.BUFFER, self._seen, kind)
        self.pipeline.set_state(gst.State.PLAYING)

    def _seen(self, _pad, info, kind):
        buffer = info.get_buffer()
        with self.lock:
            self.seen[kind].append((buffer.pts, buffer.duration, time.monotonic()))
        return self.gst.PadProbeReturn.OK

    def running_time(self):
        return max(0, self.pipeline.get_clock().get_time() - self.pipeline.get_base_time())


def wait(check, seconds, what):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(.02)
    raise AssertionError("Timed out: " + what)


def main():
    output = Output()
    gst = output.gst
    ident = FileInput(output, 3, IDENT_PATH.resolve().as_uri(), start_seconds=25)
    report = {"ok": False}
    try:
        wait(ident.ready, 20, "ID decodes")
        ident.cue()
        ident.start()
        wait(lambda: (ident.progress().get("position_seconds") or 0) >= IDENT_HOLD_AT, 10, "the end card")
        started = time.monotonic()
        report["freeze_at_s"] = 0.0
        assert ident.freeze(), "freeze refused"
        held_at, counts = ident.progress()["position_seconds"], {k: len(v) for k, v in output.seen.items()}
        time.sleep(HOLD_SECONDS)
        ident.poll()
        assert ident.ready(), "a held ID must stay ready (fresh buffers on both tracks)"
        position = ident.progress()["position_seconds"]
        assert abs(position - held_at) < .2, f"the file advanced while held: {held_at} -> {position}"
        grew = {k: len(v) - counts[k] for k, v in output.seen.items()}
        assert grew["video"] >= HOLD_SECONDS * output.fps * .9, f"held video frames: {grew}"
        assert grew["audio"] >= HOLD_SECONDS * 50 * .9, f"held audio chunks: {grew}"
        report["thaw_at_s"] = round(time.monotonic() - started, 2)
        ident.thaw()
        wait(lambda: (ident.poll() or ident.finished), 10, "the ID plays to its end after the hold")
        assert ident.error is None, ident.error
        with output.lock:
            seen = {k: list(v) for k, v in output.seen.items()}
        for kind, buffers in seen.items():
            pts = [p for p, _, _ in buffers]
            backwards = sum(b < a for a, b in zip(pts, pts[1:]))
            gaps = [(b - (a + max(d, 0))) / gst.MSECOND for (a, d, _), (b, _, _) in zip(buffers, buffers[1:])
                    if d != gst.CLOCK_TIME_NONE]
            worst = max(range(len(gaps)), key=gaps.__getitem__) if gaps else None
            report[kind] = {"buffers": len(pts), "backwards": backwards, "max_gap_ms": round(max(gaps, default=0), 1),
                            "worst_at_s": round((buffers[worst][2] - started) , 2) if worst is not None else None}
        for kind in seen:
            assert report[kind]["backwards"] == 0, f"{kind} timestamps went backwards: {report[kind]}"
            assert report[kind]["max_gap_ms"] < 150, f"{kind} timeline gap: {report[kind]}"
        report.update(ok=True, held_at=held_at, hold_seconds=HOLD_SECONDS)
    finally:
        ident.close()
        output.pipeline.set_state(gst.State.NULL)
        print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
