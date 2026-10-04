"""Pictures for the Ad mute page: one small JPEG per second per analysed input.

The page shows what a quick fix or a review mark is about: the picture on master
now (the operator's own player runs a few seconds behind it) and the pictures at a
break's edges. Files are named by the wall-clock second at which the detector saw
the picture (the page adds the programme delay to get the time it aired):

  admute-frames/<input key>/<wall second>.jpg      256x144, about 6 kB

They are kept for KEEP seconds. Writing never holds up detection: a failure is
logged once and the picture skipped.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import time
from pathlib import Path

import numpy as np

log = logging.getLogger("admute.frames")
KEEP = 3 * 3600
SIZE = (256, 144)
QUALITY = 70
PRUNE_EVERY = 60.0


class FrameStore:
    def __init__(self, root: Path, keep: float = KEEP):
        self.root = Path(root)
        self.keep = keep
        self.next_prune = 0.0
        self.failed = False

    def save(self, key: str, wall: float, rgb: np.ndarray) -> None:
        """rgb: the tap's 224x224x3 picture (the whole 16:9 frame, squeezed)."""
        try:
            from PIL import Image
            folder = self.root / key
            folder.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            Image.fromarray(np.ascontiguousarray(rgb)).resize(SIZE, Image.BILINEAR).save(buf, "JPEG", quality=QUALITY)
            name = folder / f"{int(wall)}.jpg"
            tmp = folder / f".{int(wall)}.tmp"
            tmp.write_bytes(buf.getvalue())
            os.replace(tmp, name)
            self.failed = False
        except Exception as exc:
            if not self.failed:
                log.warning("cannot save a picture for the page: %s", exc)
            self.failed = True

    def prune(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        if now < self.next_prune:
            return
        self.next_prune = now + PRUNE_EVERY
        cutoff = now - self.keep
        try:
            folders = list(self.root.iterdir())
        except FileNotFoundError:
            return
        for folder in folders:
            try:
                if not folder.is_dir():
                    continue
                left = 0
                for f in folder.iterdir():
                    stem = f.name.split(".")[0] or f.name.split(".")[1]
                    if not stem.isdigit() or int(stem) < cutoff:
                        f.unlink(missing_ok=True)
                    else:
                        left += 1
                if not left:
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError as exc:
                log.debug("pruning %s: %s", folder, exc)
