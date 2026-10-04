"""Speech for the detector: Whisper words with times.

Live, the sidecar transcribes each analysed input's tapped audio (16 kHz mono) in
CHUNK-second pieces on the input's own timeline. Replay transcribes recordings the
same way, so the text evidence the model is fitted on is the evidence it gets live.
A chunk's words are only usable once it has been transcribed: live that is when
Whisper returns; replay assumes LATENCY seconds after the chunk ends.

Offline (cached in state/admute/cache, one file per tape and range):

  python -m admute.speech TAPE [--start S] [--end E] [--model base.en]

Faster-whisper runs on the CPU with INT8 and the models already cached for live
captions (docs/live-captions.md); nothing is downloaded.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
import time

import numpy as np

RATE = 16000
CHUNK = 4.0
LATENCY = 1.5          # replay: seconds from a chunk's end until its words are known
MODEL = "base.en"
QUIET = 0.005          # a chunk this quiet has no speech (and Whisper would invent some)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "state", "admute", "cache")


def load(model=MODEL, threads=1):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from faster_whisper import WhisperModel
    return WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads, num_workers=1,
                        local_files_only=True)


def transcribe(model, audio: np.ndarray, t0: float) -> list:
    """[[start, end, word], ...] on the input's timeline, for one chunk."""
    if not len(audio) or float(np.max(np.abs(audio))) < QUIET:
        return []
    segments, _ = model.transcribe(audio, language="en", beam_size=1, temperature=0,
                                   condition_on_previous_text=False, word_timestamps=True, vad_filter=True,
                                   vad_parameters={"min_silence_duration_ms": 400})
    out = []
    dur = len(audio) / RATE
    for s in segments:
        # The same filters as live captions: drop what is probably not speech.
        if s.no_speech_prob >= .6 or s.avg_logprob <= -1 or s.compression_ratio >= 2.4:
            continue
        for w in s.words or []:
            if 0 <= w.start < w.end <= dur + .1 and w.word.strip():
                out.append([round(t0 + w.start, 2), round(t0 + min(w.end, dur), 2), w.word.strip()])
    return out


# ------------------------------------------------------------------ recordings

def _safe(path):
    from .replay import safe_name
    return safe_name(path)


def cache_glob(path, model=MODEL):
    return os.path.join(CACHE, f"{_safe(path)}.words.{model}.*.json")


def words_for(path, model=MODEL):
    """Every cached chunk of a recording: [(t0, t1, words)] sorted, or None if none."""
    chunks = []
    for f in glob.glob(cache_glob(path, model)):
        with open(f) as fh:
            chunks += [tuple(c) for c in json.load(fh)["chunks"]]
    if not chunks:
        return None
    chunks.sort(key=lambda c: c[0])
    return chunks


def decode_audio(path, start=0.0, end=None):
    # No -ss at 0: ffmpeg would start the audio where the video starts (often ~1 s in)
    # and still number it from 0, so every word would be early by that much.
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error"] + (["-ss", str(start)] if start > 0 else []) + ["-i", path]
    if end is not None:
        cmd += ["-t", str(end - start)]
    cmd += ["-vn", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, check=True, stdout=subprocess.PIPE).stdout
    return np.frombuffer(raw, "<f4")


def transcribe_tape(path, start=0.0, end=None, model_name=MODEL, threads=1):
    start = float(int(start // CHUNK) * CHUNK)         # the live chunk grid starts at t = 0
    audio = decode_audio(path, start, end)
    model = load(model_name, threads)
    step = int(CHUNK * RATE)
    chunks, began = [], time.time()
    for i in range(0, len(audio), step):
        t0 = start + i / RATE
        piece = audio[i:i + step]
        chunks.append([round(t0, 2), round(t0 + len(piece) / RATE, 2), transcribe(model, piece, t0)])
        if len(chunks) % 150 == 0:
            print(f"{os.path.basename(path)}: {t0:.0f}s ({time.time() - began:.0f}s)", file=sys.stderr, flush=True)
    stop = chunks[-1][1] if chunks else start
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f"{_safe(path)}.words.{model_name}.{int(start)}-{int(stop)}.json")
    with open(out, "w") as f:
        json.dump({"tape": os.path.basename(path), "model": model_name, "chunk": CHUNK, "chunks": chunks}, f)
    print(f"wrote {out}: {sum(len(c[2]) for c in chunks)} words in {time.time() - began:.0f}s", file=sys.stderr)
    return out


def main(argv=None):
    from .replay import find_tape
    ap = argparse.ArgumentParser(prog="admute.speech")
    ap.add_argument("tape")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float)
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--threads", type=int, default=1)
    args = ap.parse_args(argv)
    transcribe_tape(find_tape(args.tape), args.start, args.end, args.model, args.threads)


if __name__ == "__main__":
    main()
