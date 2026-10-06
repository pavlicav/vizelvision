"""Speech for the detector: Whisper words with times.

Live, the sidecar transcribes each analysed input's tapped audio (16 kHz mono) on the
input's own timeline, in WINDOW-second windows every STEP seconds (Windower). Each
word is heard by two windows; a window gives only the words that are its own (from
where the window before stopped to GUARD before its end), so a word cut off at one
window's edge comes from the window that heard it whole (Committer). Replay
transcribes recordings the same way, so the text evidence the model is fitted on is
the evidence it gets live. A window's words are usable once it has been transcribed:
live that is when Whisper returns; replay assumes LATENCY seconds after the window
ends, which is GUARD after the stretch it gives.

Detection keeps what live captions throw away: speech over music, i.e. most ads,
passes unless Whisper itself would call it silence (speech_like). The programme's
names (its title, an MLB game's teams and players) go to Whisper as a prompt, so it
spells them the same way every time and the programme vocabulary recognises them.

Offline (cached in state/admute/cache, one file per tape, range, model and SCHEME):

  python -m admute.speech TAPE [--start S] [--end E] [--model base.en]

Faster-whisper runs on the CPU with INT8 and the models already cached for live
captions (docs/live-captions.md); nothing is downloaded.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

import numpy as np

RATE = 16000
WINDOW = 8.0           # seconds Whisper hears at once ...
STEP = 4.0             # ... every STEP seconds: each word is heard twice
GUARD = 1.0            # a word this close to a window's end waits for the next window, which has it whole
JITTER = 0.5           # the same word, timed by two windows, lands this close
GAP = 0.1              # audio this far from where the stream had got to starts a new run
LATENCY = 1.5          # replay: seconds from a window's end until its words are known
MODEL = "base.en"       # the default; live, admute.json's speech_model
SCHEME = "w8"          # how transcripts are made (in cache names); before 10/4, 4 s chunks with captions' filters
QUIET = 0.005          # a window this quiet has no speech (and Whisper would invent some)
PROMPT_CHARS = 600     # Whisper keeps the last 223 tokens of a prompt; this stays under that
# Whisper's own test for "not speech" needs both no speech and low confidence; live
# captions drop either, which loses speech over music. Garbage and loops still go.
NO_SPEECH, UNSURE, GARBAGE, LOOPING = 0.6, -1.0, -1.5, 2.4
VAD = {"min_silence_duration_ms": 400, "threshold": 0.35}   # silero's 0.5 misses voices under music
# What Whisper says over music or silence when nobody speaks (a whole segment of just this).
HALLUCINATIONS = frozenset({"you", "thank you", "thank you very much", "thanks for watching",
                            "thank you for watching", "thank you so much for watching", "please subscribe",
                            "bye", "so", "okay", "oh", "music", "applause"})

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "state", "admute", "cache")


def load(model=MODEL, threads=1, workers=1):
    """``workers``: how many threads may transcribe at once (each runs ``threads`` deep)."""
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    from faster_whisper import WhisperModel
    return WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=threads, num_workers=workers,
                        local_files_only=True)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9' ]", " ", text.lower()).split())


def speech_like(seg) -> bool:
    if seg.avg_logprob <= GARBAGE or seg.compression_ratio >= LOOPING:
        return False
    if seg.no_speech_prob >= NO_SPEECH and seg.avg_logprob <= UNSURE:
        return False
    return _norm(seg.text) not in HALLUCINATIONS


def prompt(title=None, names=()) -> str | None:
    """What Whisper is told before each window: the programme's title and names."""
    text = (title or "").strip()
    if text and text[-1] not in ".!?":
        text += "."
    names = [n.strip() for n in dict.fromkeys(names) if n and n.strip()]
    if names:
        room = PROMPT_CHARS - len(text) - 1
        kept = []
        for n in names:
            if sum(len(k) + 2 for k in kept) + len(n) > room:
                break
            kept.append(n)
        if kept:
            text = (text + " " if text else "") + ", ".join(kept) + "."
    return text or None


def transcribe(model, audio: np.ndarray, t0: float, prompt: str | None = None) -> list:
    """[[start, end, word], ...] on the input's timeline: every word heard in ``audio``."""
    if not len(audio) or float(np.max(np.abs(audio))) < QUIET:
        return []
    segments, _ = model.transcribe(audio, language="en", beam_size=1, temperature=0, initial_prompt=prompt or None,
                                   condition_on_previous_text=False, word_timestamps=True, vad_filter=True,
                                   vad_parameters=VAD)
    out = []
    dur = len(audio) / RATE
    for s in segments:
        if not speech_like(s):
            continue
        for w in s.words or []:
            if 0 <= w.start < w.end <= dur + .1 and w.word.strip():
                out.append([round(t0 + w.start, 2), round(t0 + min(w.end, dur), 2), w.word.strip()])
    return out


# ------------------------------------------------------------------ windows

class Windower:
    """Cuts audio on the input's timeline into windows for Whisper. push() returns
    [(t0, audio, upto)]: a window starting at t0 whose words before ``upto`` are its
    to give. Windows end every STEP seconds from the start of a run (the first ones
    are shorter: all the audio there is). A gap ends the run, and its last window
    gives everything up to the gap (flush)."""

    def __init__(self):
        self.start = None       # time of the run's first sample
        self.buf = np.zeros(0, np.float32)
        self.pos = 0            # run sample index of buf[0]
        self.n = 0              # samples in the run so far
        self.next = 0           # run sample index at which the next window ends
        self.given = 0          # run sample index up to which windows give words

    @property
    def end(self):
        return None if self.start is None else self.start + self.n / RATE

    def push(self, t: float, samples) -> list:
        jobs = []
        if self.start is not None and abs(t - self.end) > GAP:
            jobs += self.flush()
        if self.start is None:
            self.start, self.buf, self.pos, self.n = t, np.zeros(0, np.float32), 0, 0
            self.next, self.given = int(STEP * RATE), 0
        self.buf = np.concatenate([self.buf, np.asarray(samples, np.float32)])
        self.n += len(samples)
        win, step, guard = int(WINDOW * RATE), int(STEP * RATE), int(GUARD * RATE)
        while self.n >= self.next:
            jobs.append(self._job(max(self.pos, self.next - win), self.next, self.next - guard))
            self.next += step
            drop = max(0, self.next - win - self.pos)
            self.buf, self.pos = self.buf[drop:], self.pos + drop
        return jobs

    def _job(self, lo, hi, upto):
        self.given = upto
        return (self.start + lo / RATE, self.buf[lo - self.pos:hi - self.pos].copy(), self.start + upto / RATE)

    def flush(self) -> list:
        """The run ends: a last window gives what the windows so far held back."""
        jobs = []
        if self.start is not None and self.n - self.given > int(0.2 * RATE):
            jobs.append(self._job(max(self.pos, self.n - int(WINDOW * RATE)), self.n, self.n))
        self.start = None
        return jobs


def _mid(w):
    return (w[0] + w[1]) / 2


class Committer:
    """Windows' words in, contiguous chunks (t0, t1, words) out, every word once. A
    window gives the words from where the window before stopped (``upto``) to its own
    ``upto``. Two windows may time a word near that boundary a little differently, so
    a word within JITTER of it is given unless the window before gave the same word."""

    def __init__(self):
        self.upto = None
        self.last = []          # the words given last, near its end

    def take(self, t0: float, upto: float, words) -> tuple | None:
        if self.upto is not None and upto <= self.upto:
            return None
        if self.upto is not None and t0 <= self.upto:
            lo, before = self.upto, self.last
        else:                   # the first window of a run, or the ones before it were dropped
            lo, before = t0, []
        got = []
        for w in words:
            m = _mid(w)
            if not lo - JITTER <= m < upto:
                continue
            if m < lo + JITTER and any(_norm(w[2]) == _norm(b[2]) and abs(m - _mid(b)) < 2 * JITTER for b in before):
                continue
            got.append(w)
        self.upto = upto
        self.last = [w for w in got if _mid(w) >= upto - 3 * JITTER]
        return (lo, upto, got)


# ------------------------------------------------------------------ recordings

def _safe(path):
    from .replay import safe_name
    return safe_name(path)


def cache_glob(path, model=MODEL, scheme=SCHEME):
    """Cached transcripts made with ``scheme`` (None: the 4 s chunks from before 10/4)."""
    if scheme is None:
        return os.path.join(CACHE, f"{_safe(path)}.words.{model}.[0-9]*.json")
    return os.path.join(CACHE, f"{_safe(path)}.words.{model}.{scheme}.*.json")


def words_for(path, model=MODEL, scheme=SCHEME, legacy=False):
    """Every cached chunk of a recording: [(t0, t1, words)] sorted, or None if none.
    ``legacy``: the old 4 s chunks will do when there is nothing newer (for an ad's
    script, which only needs the words; not for fitting or scoring the model)."""
    chunks = []
    for f in glob.glob(cache_glob(path, model, scheme)):
        with open(f) as fh:
            chunks += [tuple(c) for c in json.load(fh)["chunks"]]
    if not chunks:
        return words_for(path, model, None) if legacy and scheme is not None else None
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


def transcribe_tape(path, start=0.0, end=None, model_name=MODEL, threads=1, title=None, names=()):
    """``title``, ``names``: the prompt, as live (a game's title, and its teams and players)."""
    start = float(int(start // STEP) * STEP)          # the live window grid starts at t = 0
    audio = decode_audio(path, start, end)
    model = load(model_name, threads)
    hint = prompt(title, names)
    windows, committer = Windower(), Committer()
    chunks, began = [], time.time()

    def run(jobs):
        for t0, piece, upto in jobs:
            got = committer.take(t0, upto, transcribe(model, piece, t0, hint))
            if got is not None:
                chunks.append([round(got[0], 2), round(got[1], 2), got[2]])
                if len(chunks) % 150 == 0:
                    print(f"{os.path.basename(path)}: {got[1]:.0f}s ({time.time() - began:.0f}s)",
                          file=sys.stderr, flush=True)

    for i in range(0, len(audio), RATE):
        run(windows.push(start + i / RATE, audio[i:i + RATE]))
    run(windows.flush())
    stop = chunks[-1][1] if chunks else start
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, f"{_safe(path)}.words.{model_name}.{SCHEME}.{int(start)}-{int(stop)}.json")
    with open(out, "w") as f:
        json.dump({"tape": os.path.basename(path), "model": model_name, "scheme": SCHEME, "window": WINDOW,
                   "step": STEP, "guard": GUARD, "prompt": hint, "chunks": chunks}, f)
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
    ap.add_argument("--title", help="the programme's title, as Whisper's prompt")
    args = ap.parse_args(argv)
    transcribe_tape(find_tape(args.tape), args.start, args.end, args.model, args.threads, args.title)


if __name__ == "__main__":
    main()
