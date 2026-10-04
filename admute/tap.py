"""The tap format: what the master sends the detector for each input, and the same
media decoded from a recording for replay.

  gray   GRAY8 320x180 at the source frame rate (black frames, cuts, edges)
  rgb    RGB 224x224 at 1 fps, squeezed (embeddings, colour)
  audio  F32 mono 16 kHz

Every piece carries its input timestamp in seconds. Live, that is the input's
running time; from a file, it is container time (frame i of an ``fps`` grid
anchored at 0 is at i / fps, as in the offline stripper's rec_features).
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from fractions import Fraction

import numpy as np

W, H = 320, 180
RGB_SIDE = 224
AUDIO_RATE = 16000
GRAY_BYTES = W * H
RGB_BYTES = RGB_SIDE * RGB_SIDE * 3
FFMPEG = "/usr/bin/ffmpeg"
FFPROBE = "/usr/bin/ffprobe"


def probe(path: str) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                          "stream=codec_type,r_frame_rate:format=duration", "-of", "json", path],
                         capture_output=True, check=True, text=True).stdout
    info = json.loads(out)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    return {"fps": Fraction(video["r_frame_rate"]), "duration": float(info["format"]["duration"])}


def _reader(pipe, size: int, chunk: int, emit, errors: list):
    try:
        while True:
            buf = pipe.read(size * chunk)
            k = len(buf) // size
            if k and not errors:
                emit(np.frombuffer(buf[: k * size], np.uint8).reshape(k, size))
            if len(buf) < size * chunk:
                break
    except Exception as exc:          # keep draining nothing; ffmpeg sees a broken pipe and stops
        errors.append(exc)
    finally:
        pipe.close()


def decode_file(path: str, on_gray, on_rgb, on_audio, *, limit: float | None = None,
                thumbs=None, threads: int = 2):
    """Decode ``path`` into the tap format, calling the handlers in time order per
    stream: on_gray(times[k], frames[k,H,W]), on_rgb(times[k], frames[k,224,224,3]),
    on_audio(t0, samples). Full-range luma. ``thumbs(t, rgb[k,108,192,3])``, if given, gets 1 fps
    192x108 pictures for contact sheets. Handlers run on reader threads.
    """
    info = probe(path)
    fps = info["fps"]
    lim = ["-t", str(limit)] if limit else []
    pipes = {}
    outs = [("gray", f"fps={fps}:start_time=0,scale={W}:{H}:flags=area,format=gray", GRAY_BYTES),
            ("rgb", f"fps=1:start_time=0,scale={RGB_SIDE}:{RGB_SIDE}:flags=area,format=rgb24", RGB_BYTES)]
    if thumbs is not None:
        outs.append(("thumb", "fps=1:start_time=0,scale=192:108:flags=area,format=rgb24", 192 * 108 * 3))
    graph = f"[0:v]split={len(outs)}" + "".join(f"[s{i}]" for i in range(len(outs))) + ";" + ";".join(
        f"[s{i}]{chain}[o{i}]" for i, (_, chain, _) in enumerate(outs))
    cmd = [FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", "-threads", str(threads), *lim,
           "-i", path, "-an", "-filter_complex", graph]
    fds = []
    for i, (name, _, _) in enumerate(outs):
        r, w = os.pipe()
        pipes[name] = r
        fds.append(w)
        cmd += ["-map", f"[o{i}]", "-f", "rawvideo", f"pipe:{w}"]
    video = subprocess.Popen(cmd, pass_fds=fds)
    for w in fds:
        os.close(w)
    audio = subprocess.Popen([FFMPEG, "-nostdin", "-hide_banner", "-loglevel", "error", *lim, "-i", path,
                              "-vn", "-ac", "1", "-ar", str(AUDIO_RATE), "-f", "f32le", "-"],
                             stdout=subprocess.PIPE)

    counts = {"gray": 0, "rgb": 0, "thumb": 0}

    def gray(a):
        on_gray((counts["gray"] + np.arange(len(a))) / float(fps), a.reshape(-1, H, W))
        counts["gray"] += len(a)

    def rgb(a):
        on_rgb(counts["rgb"] + np.arange(len(a), dtype=float), a.reshape(-1, RGB_SIDE, RGB_SIDE, 3))
        counts["rgb"] += len(a)

    def thumb(a):
        thumbs(counts["thumb"] + np.arange(len(a), dtype=float), a.reshape(-1, 108, 192, 3))
        counts["thumb"] += len(a)

    errors: list = []

    def aud():
        n = 0
        try:
            while True:
                buf = audio.stdout.read(4 * AUDIO_RATE)          # 0.25 s
                if not buf:
                    break
                buf = buf[: len(buf) // 4 * 4]
                s = np.frombuffer(buf, np.float32)
                on_audio(n / AUDIO_RATE, s)
                n += len(s)
        except Exception as exc:
            errors.append(exc)
        finally:
            audio.stdout.close()

    handlers = {"gray": (GRAY_BYTES, 32, gray), "rgb": (RGB_BYTES, 4, rgb), "thumb": (192 * 108 * 3, 16, thumb)}
    threads_ = [threading.Thread(target=_reader, args=(os.fdopen(pipes[name], "rb"), *handlers[name], errors))
                for name in pipes]
    threads_.append(threading.Thread(target=aud))
    for t in threads_:
        t.start()
    for t in threads_:
        t.join()
    if errors:
        video.kill(), audio.kill()
        raise errors[0]
    if video.wait() != 0 or audio.wait() != 0:
        raise RuntimeError(f"ffmpeg decode failed for {path}")
    return {"fps": float(fps), "duration": info["duration"]}
