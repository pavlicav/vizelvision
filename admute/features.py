"""Per-step signals from the tap, computed as media arrives (causal).

The maths follows the offline stripper (~/scratch/ad_detection/rec_features.py):

  frame   luma mean and 3rd-brightest of a 32x18 area thumbnail: black frames,
          judged at the full frame rate (a break's black gap is 2-4 frames)
  step    10/s: mean abs difference to the previous step (cuts), and every 5th
          step a 320x180 edge map (the station / score bug)
  audio   10/s: RMS level in dB
  second  1/s: MobileNet embedding (content identity), a 64-bin colour histogram, and
          the edges of the 224x224 picture (overlays drawn on it: YouTube TV's ad label)

Everything lives on grids anchored at input time 0: step k is at k/10 s, second s
at s. ``trim`` drops what live detection no longer needs; replay keeps it all.
"""
from __future__ import annotations

import threading

import numpy as np

from . import tap

STEP_HZ = 10
EDGE_EVERY = 5            # an edge map every 5th step (2/s)
EDGE_HZ = STEP_HZ / EDGE_EVERY
EDGE_THRESH = 24          # gradient magnitude that counts as an edge (0..255 grey)
SILENT_DB = -120.0
AUDIO_SLACK = 32          # samples (2 ms) of timestamp jitter taken as continuous
# Limited-range luma (GStreamer GRAY8 from I420: black 16, white 235) to full range.
LIMITED_TO_FULL = np.clip((np.arange(256) - 16) * 255 / 219, 0, 255).round().astype(np.uint8)


def edges(g: np.ndarray) -> np.ndarray:
    gx = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
    gy = np.abs(np.diff(g, axis=0, prepend=g[:1, :]))
    return (gx + gy) > EDGE_THRESH


def pic_edges(rgb: np.ndarray) -> np.ndarray:
    """Edges of the 224x224 colour picture (bool [224, 224]): admute.overlays' "pic" space.
    The page's pictures are made from the same picture, so overlays drawn from them match."""
    a = rgb.astype(np.float32)
    return edges((0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]).astype(np.int16))


def unpack_pic(packed: np.ndarray) -> np.ndarray:
    side = tap.RGB_SIDE
    return np.unpackbits(packed)[: side * side].reshape(side, side).astype(bool)


def colour_hist(rgb: np.ndarray) -> np.ndarray:
    """64-bin RGB histogram of a 224x224 picture (56x56 area thumbnail), square-rooted
    so a dot product is the Bhattacharyya coefficient."""
    small = rgb.reshape(56, 4, 56, 4, 3).mean((1, 3))
    q = (small // 64).astype(np.int32)
    code = q[..., 0] * 16 + q[..., 1] * 4 + q[..., 2]
    h = np.bincount(code.ravel(), minlength=64).astype(np.float32)
    return np.sqrt(h / h.sum())


class Signals:
    """Growing arrays of signals for one input. Each push_* is called from one
    thread per kind; readers take ``lock`` and use the ``*_since`` offsets."""

    def __init__(self, embed=None, limited_range=False):
        self.lock = threading.Lock()
        self.embed = embed                 # callable(rgb224) -> vector, or None
        self.lut = LIMITED_TO_FULL if limited_range else None
        self.frame_t: list[float] = []
        self.frame_mean: list[float] = []
        self.frame_max: list[float] = []
        self.frames_since = 0              # index of frame_t[0] (after trims)
        self.cut: list[float] = []
        self.steps_since = 0
        self.edge_maps: list[np.ndarray] = []   # packed bits, one per EDGE_EVERY steps
        self.edges_since = 0
        self.rms_db: list[float] = []
        self.audio_since = 0
        self.emb: list[np.ndarray] = []
        self.hist: list[np.ndarray] = []
        self.pics: list[np.ndarray] = []   # packed pic_edges per second (live only: not in snapshots)
        self.seconds_since = 0
        self._prev = None
        self._next_step = 0
        self._audio_buf = np.zeros(0, np.float32)
        self._next_second = 0

    # ------------------------------------------------------------------ input
    def push_gray(self, times, frames):
        """frames: uint8 [k, 180, 320], times: their input times (s)."""
        if self.lut is not None:
            frames = self.lut[frames]
        thumbs = frames.reshape(len(frames), 18, 10, 32, 10).mean((2, 4)).reshape(len(frames), -1)
        top = np.sort(thumbs, 1)
        new_cut, new_edges = [], []
        for t, f in zip(times, frames):
            while self._next_step / STEP_HZ <= t + 1e-6:
                g = f.astype(np.int16)
                new_cut.append(0.0 if self._prev is None else float(np.abs(g - self._prev).mean()))
                if self._next_step % EDGE_EVERY == 0:
                    new_edges.append(np.packbits(edges(g)))
                self._prev = g
                self._next_step += 1
        with self.lock:
            self.frame_t.extend(float(t) for t in times)
            self.frame_mean.extend(thumbs.mean(1).tolist())
            self.frame_max.extend(top[:, -3].tolist())
            self.cut.extend(new_cut)
            self.edge_maps.extend(new_edges)

    def push_rgb(self, times, frames):
        """frames: uint8 [k, 224, 224, 3] at about 1 fps."""
        for t, f in zip(times, frames):
            s = int(round(t))
            if s < self._next_second:
                continue
            vec = self.embed(f) if self.embed else np.zeros(1, np.float32)
            hist = colour_hist(f)
            pic = np.packbits(pic_edges(f))
            with self.lock:
                while self._next_second <= s:      # a missing second repeats the next one
                    self.emb.append(vec)
                    self.hist.append(hist)
                    self.pics.append(pic)
                    self._next_second += 1

    def push_audio(self, t0: float, samples: np.ndarray):
        """Mono 16 kHz float samples starting at input time t0.

        The level grid stays on input time: holes and overlaps are measured against the
        samples already on it, so neither shifts what follows. (Measured from the last
        chunk's end, each hole once cost the edge its length for good: on 2026-10-03 a
        4 s gap in TBS left detection 4.8 s behind, past its lookahead, so nothing muted.)"""
        rate = tap.AUDIO_RATE
        hop = rate // STEP_HZ
        with self.lock:
            have = (self.audio_since + len(self.rms_db)) * hop + len(self._audio_buf)
        offset = int(round(t0 * rate)) - have
        if offset > AUDIO_SLACK:                      # a hole: silence
            samples = np.concatenate([np.zeros(offset, np.float32), samples])
        elif offset < -AUDIO_SLACK:                   # overlap: drop what we have
            samples = samples[-offset:]
        buf = np.concatenate([self._audio_buf, samples])
        k = len(buf) // hop
        if k:
            fr = buf[: k * hop].reshape(k, hop).astype(np.float64)
            db = 10 * np.log10((fr ** 2).mean(1) + 1e-12)
            with self.lock:
                self.rms_db.extend(db.astype(np.float32).tolist())
        self._audio_buf = buf[k * hop:]

    # ------------------------------------------------------------------ output
    def trim(self, before: float):
        """Forget signals older than input time ``before`` (live memory bound)."""
        with self.lock:
            n = max(0, int(before * STEP_HZ) - self.steps_since)
            if n:
                del self.cut[:n]
                self.steps_since += n
            n = max(0, int(before * STEP_HZ) - self.audio_since)
            if n:
                del self.rms_db[:n]
                self.audio_since += n
            n = max(0, int(before * EDGE_HZ) - self.edges_since)
            if n:
                del self.edge_maps[:n]
                self.edges_since += n
            n = 0
            while n < len(self.frame_t) and self.frame_t[n] < before:
                n += 1
            if n:
                del self.frame_t[:n], self.frame_mean[:n], self.frame_max[:n]
                self.frames_since += n

    def trim_seconds(self, before: float):
        with self.lock:
            n = max(0, int(before) - self.seconds_since)
            if n:
                del self.emb[:n], self.hist[:n], self.pics[:n]
                self.seconds_since += n

    def snapshot(self) -> dict:
        """Arrays of everything held now (copies), with their grid offsets."""
        with self.lock:
            return {"frame_t": np.array(self.frame_t), "frame_mean": np.array(self.frame_mean, np.float32),
                    "frame_max": np.array(self.frame_max, np.float32),
                    "cut": np.array(self.cut, np.float32), "steps_since": self.steps_since,
                    "edges": np.array(self.edge_maps, np.uint8).reshape(len(self.edge_maps), -1),
                    "edges_since": self.edges_since,
                    "rms_db": np.array(self.rms_db, np.float32), "audio_since": self.audio_since,
                    "emb": np.array(self.emb, np.float32), "hist": np.array(self.hist, np.float32),
                    "seconds_since": self.seconds_since}

    def edge(self) -> float:
        """Input time up to which every kind of signal is complete."""
        return min(self.edge_parts())

    def edge_parts(self) -> tuple[float, float, float]:
        """How far video steps, audio levels and per-second pictures each reach."""
        with self.lock:
            v = (self.steps_since + len(self.cut)) / STEP_HZ
            a = (self.audio_since + len(self.rms_db)) / STEP_HZ
            s = self.seconds_since + len(self.emb)
            return v, a, float(s)


def unpack(packed: np.ndarray) -> np.ndarray:
    bits = np.unpackbits(packed, axis=-1)[..., : tap.W * tap.H]
    return bits.reshape(*packed.shape[:-1], tap.H, tap.W).astype(bool)
