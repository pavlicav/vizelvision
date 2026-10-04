"""Labelling helpers for recordings (lab only, not used live).

  python -m admute.lab seams TAPE                       black-frame and silence seams
  python -m admute.lab sheet TAPE START END [--step 10] contact sheet of 1 fps thumbnails

Thumbnails come from ``python -m admute.replay extract TAPE --thumbs``. Sheets are
written to state/admute/sheets/ and print their path.
"""
from __future__ import annotations

import argparse
import os

import numpy as np

from . import replay

SHEETS = os.path.join(replay.ROOT, "state", "admute", "sheets")


def black_runs(sig) -> list[tuple[float, float]]:
    t, mean, mx = sig["frame_t"], sig["frame_mean"], sig["frame_max"]
    blk = (mx < 45) & (mean < 25)
    d = np.diff(np.concatenate([[0], blk.astype(np.int8), [0]]))
    starts, ends = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    out = []
    for a, b in zip(starts, ends):
        ta, tb = t[a], t[b - 1] + (t[1] - t[0])
        if out and ta - out[-1][1] < 0.1:
            out[-1] = (out[-1][0], tb)
        else:
            out.append((ta, tb))
    return out


def silences(sig, db_max=-60.0) -> list[tuple[float, float]]:
    db = sig["rms_db"]
    quiet = db < db_max
    d = np.diff(np.concatenate([[0], quiet.astype(np.int8), [0]]))
    return [(a / 10, b / 10) for a, b in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1))]


def thumbs(tape: str, start: float, end: float):
    """1 fps thumbnails for part of a tape (when it was extracted without --thumbs)."""
    import subprocess
    from . import tap
    tdir = os.path.join(replay.THUMBS, replay.safe_name(tape))
    os.makedirs(tdir, exist_ok=True)
    raw = subprocess.run([tap.FFMPEG, "-nostdin", "-v", "error", "-ss", str(start), "-t", str(end - start),
                          "-i", tape, "-an", "-vf", "fps=1:start_time=0,scale=192:108:flags=area,format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    from PIL import Image
    n = len(raw) // (192 * 108 * 3)
    for i in range(n):
        f = np.frombuffer(raw[i * 192 * 108 * 3:(i + 1) * 192 * 108 * 3], np.uint8).reshape(108, 192, 3)
        Image.fromarray(f).save(os.path.join(tdir, f"{int(start) + i:05d}.jpg"), quality=70)


def sheet(tape: str, start: float, end: float, step: float = 10.0, cols: int = 8) -> str:
    from PIL import Image, ImageDraw
    have = os.path.exists(replay.cache_path(tape))       # seams once extraction has finished
    sig = replay.extract(tape) if have else None
    blacks = black_runs(sig) if sig else []
    quiet = silences(sig) if sig else []
    tdir = os.path.join(replay.THUMBS, replay.safe_name(tape))
    times = np.arange(start, end, step)
    rows = int(np.ceil(len(times) / cols))
    w, h, lab = 192, 108, 16
    img = Image.new("RGB", (cols * w, rows * (h + lab)), (20, 20, 20))
    draw = ImageDraw.Draw(img)
    for i, t in enumerate(times):
        x, y = (i % cols) * w, (i // cols) * (h + lab)
        path = os.path.join(tdir, f"{int(t):05d}.jpg")
        if os.path.exists(path):
            img.paste(Image.open(path), (x, y + lab))
        marks = ""
        if any(t - step / 2 <= (a + b) / 2 < t + step / 2 for a, b in blacks):
            marks += " B"
        if any(t - step / 2 <= a < t + step / 2 for a, _ in quiet):
            marks += " S"
        draw.text((x + 3, y + 2), f"{replay.fmt(float(t))[:-2]}{marks}", fill=(255, 230, 120) if marks else (230, 230, 230))
    os.makedirs(SHEETS, exist_ok=True)
    out = os.path.join(SHEETS, f"{replay.safe_name(tape)[:24]}_{int(start)}_{int(end)}_{int(step)}.jpg")
    img.save(out, quality=80)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="admute.lab")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seams")
    s.add_argument("tape")
    s.add_argument("--from", dest="frm", type=float, default=0)
    s.add_argument("--to", type=float, default=1e9)
    c = sub.add_parser("sheet")
    c.add_argument("tape")
    c.add_argument("start", type=float)
    c.add_argument("end", type=float)
    c.add_argument("--step", type=float, default=10)
    c.add_argument("--cols", type=int, default=8)
    c.add_argument("--make-thumbs", action="store_true")
    args = ap.parse_args(argv)
    tape = replay.find_tape(args.tape)
    if args.cmd == "seams":
        sig = replay.extract(tape)
        for a, b in black_runs(sig):
            if args.frm <= a <= args.to:
                print(f"black   {replay.fmt(a)}  {b - a:5.2f}s")
        for a, b in silences(sig):
            if args.frm <= a <= args.to and b - a >= 0.2:
                print(f"silence {replay.fmt(a)}  {b - a:5.2f}s")
    else:
        if args.make_thumbs:
            thumbs(tape, args.start, args.end)
        print(sheet(tape, args.start, args.end, args.step, args.cols))


if __name__ == "__main__":
    main()
