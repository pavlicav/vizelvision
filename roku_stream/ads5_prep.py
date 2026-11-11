"""Ads 5's clips, made ready to air: each ad and ident encoded once, alike, and cut into segments.

An ad from My ads' library can be any size, rate and codec. Ads 5 airs every clip as one
stream (ads5_ts.py joins them), so each is encoded the same way first:

    1280×720 (letterboxed or pillarboxed, its pixel aspect respected), 60 fps
    H.264 High, a key frame every 2 s exactly; AAC 48 kHz stereo, 160 kb/s
    levelled as master levels it (the ad's gain_db + trim_db: −20 LUFS), silence if it has none
    2 s MPEG-TS segments (HLS, as a VOD playlist), with meta.json

A clip is encoded once, at the lowest priority, and kept (state/ads5/clips/<key>/, the key
naming the source file, its level and this recipe), so the library is ready for good after the
first pass: about 4 GB for 380 ads. A station promo with live text (the time, the temperature)
is encoded again for each airing, its text drawn as it will air (promo_overlay.draw, frame by
frame, the same drawing master does), into state/ads5/live/, and cleared after.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time

from .ads5_ts import CLOCK, first_pts

RECIPE = 1
WIDTH, HEIGHT, FPS = 1280, 720, 60
SEGMENT = 2
THREADS = 4
MAX_SECONDS = 15 * 60


class PrepError(RuntimeError):
    pass


def _die_with_parent():
    """An encoder outlives no service: the kernel stops it when Ads 5 stops (PR_SET_PDEATHSIG)."""
    try:
        import ctypes
        import signal
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)
    except Exception:   # noqa: BLE001 - not Linux: the encoder just runs to its end
        pass


def clear_unfinished(folder):
    """Deletes encodings a stopped service left half done (.<key>-* folders)."""
    for path in Path(folder).glob('.*'):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)


def clip_key(kind, name, path, level_db=0.0):
    """The folder a clip's encoding is kept in: its kind and name, and a hash of the source
    file (size and time), its level and the recipe, so a changed file or level is encoded anew."""
    st = Path(path).stat()
    digest = hashlib.sha1(f'{st.st_size}:{st.st_mtime_ns}:{level_db:.2f}:{RECIPE}'.encode()).hexdigest()[:10]
    return f'{kind}-{name}-{digest}'


def _video_filter():
    return (f"[0:v:0]scale='trunc(iw*sar/2)*2':ih,setsar=1,"
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:black,setsar=1,fps={FPS},setpts=PTS-STARTPTS")


def _overlay_frames(stream, overlays, values, start, duration, size):
    """Writes the overlay's frames (premultiplied BGRA at the promo's size) into ffmpeg."""
    import cairo
    from . import promo_overlay
    w, h = size
    blank = bytes(w * h * 4)
    cache = {}
    try:
        for i in range(int(round(duration * FPS))):
            t = i / FPS
            if any(promo_overlay.place(spec, t) for spec in overlays):
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
                promo_overlay.draw(cairo.Context(surface), overlays, values, t, now=start + t, cache=cache)
                surface.flush()
                stream.write(bytes(surface.get_data()))
            else:
                stream.write(blank)
    except (BrokenPipeError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def encode(src, out, *, duration, level_db=0.0, audio=True, overlay=None, threads=THREADS, nice=19):
    """Encodes src into the folder out (made here, replacing any) and returns its meta.json.
    overlay: {overlays, values, start, size} to draw live text into it."""
    src, out = Path(src), Path(out)
    if not src.is_file():
        raise PrepError(f'{src.name} is missing')
    if not duration or duration <= 0 or duration > MAX_SECONDS:
        raise PrepError('its length is not known')
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='.' + out.name + '-', dir=out.parent))
    try:
        cmd = ['nice', '-n', str(nice), 'ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
               '-i', str(src)]
        inputs = 1
        if not audio:
            cmd += ['-f', 'lavfi', '-t', f'{duration:.3f}', '-i', 'anullsrc=r=48000:cl=stereo']
            silence = inputs
            inputs += 1
        graph = _video_filter()
        if overlay:
            w, h = overlay['size']
            cmd +=['-f', 'rawvideo', '-pix_fmt', 'bgra', '-s', f'{w}x{h}', '-framerate', str(FPS), '-i', 'pipe:0']
            graph += (f"[b];[{inputs}:v]scale={WIDTH}:{HEIGHT},setpts=PTS-STARTPTS[o];"
                      f"[b][o]overlay=0:0:alpha=premultiplied:eof_action=pass,format=yuv420p[v]")
            inputs += 1
        else:
            graph += ',format=yuv420p[v]'
        a_in = f'[{silence}:a:0]' if not audio else '[0:a:0]'
        graph += (f';{a_in}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,'
                  f'volume={level_db:.2f}dB,apad[a]')
        cmd += ['-filter_complex', graph, '-map', '[v]', '-map', '[a]', '-t', f'{duration:.3f}', '-shortest',
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-maxrate', '4500k', '-bufsize', '9000k',
                '-profile:v', 'high', '-level:v', '4.2', '-pix_fmt', 'yuv420p',
                '-g', str(FPS * SEGMENT), '-keyint_min', str(FPS * SEGMENT), '-sc_threshold', '0',
                '-force_key_frames', f'expr:gte(t,n_forced*{SEGMENT})', '-threads', str(threads),
                '-c:a', 'aac', '-b:a', '160k', '-ar', '48000', '-ac', '2',
                '-f', 'hls', '-hls_time', str(SEGMENT), '-hls_playlist_type', 'vod',
                '-hls_flags', 'independent_segments', '-hls_segment_type', 'mpegts',
                '-hls_segment_filename', str(work / 's%04d.ts'), str(work / 'index.m3u8')]
        log = work / 'ffmpeg.log'
        with open(log, 'wb') as errors:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if overlay else subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL, stderr=errors, preexec_fn=_die_with_parent)
            writer = None
            if overlay:
                writer = threading.Thread(target=_overlay_frames, daemon=True,
                                          args=(proc.stdin, overlay['overlays'], overlay['values'], overlay['start'],
                                                duration, overlay['size']))
                writer.start()
            try:
                code = proc.wait(timeout=max(120, duration * 6))
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise PrepError('ffmpeg took too long')
            if writer:
                writer.join(5)
        if code:
            raise PrepError('ffmpeg: ' + (log.read_text(errors='replace').strip().splitlines() or ['failed'])[-1][:300])
        meta = describe(work)
        log.unlink(missing_ok=True)
        (work / 'meta.json').write_text(json.dumps(meta))
        if out.exists():
            shutil.rmtree(out, ignore_errors=True)
        os.replace(work, out)
        return meta
    finally:
        if work.exists():
            shutil.rmtree(work, ignore_errors=True)


_EXTINF = re.compile(r'#EXTINF:([0-9.]+),\s*\n([^\n#]+)')


def describe(folder):
    """A clip's meta: its segments with their lengths, its first PTS and how long it runs, from
    its first timestamp to the end of its last frame or sound (90 kHz). The last segment's
    length is stretched to match, so the playlist's clock and the timestamps agree."""
    folder = Path(folder)
    text = (folder / 'index.m3u8').read_text()
    segments = [{'name': name.strip(), 'seconds': float(seconds)} for seconds, name in _EXTINF.findall(text)]
    if not segments:
        raise PrepError('no segments came out')
    start = first_pts((folder / segments[0]['name']).read_bytes())
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'packet=pts,duration', '-of', 'csv=p=0',
                            str(folder / segments[-1]['name'])], capture_output=True, text=True, timeout=60)
    end = None
    for line in probe.stdout.splitlines():
        parts = line.split(',')
        try:
            value = int(parts[0]) + int(parts[1] or 0)
        except (ValueError, IndexError):
            continue
        end = value if end is None else max(end, value)
    if start is None or end is None or end <= start:
        raise PrepError('its timestamps could not be read')
    span = end - start
    head = sum(s['seconds'] for s in segments[:-1])
    segments[-1]['seconds'] = max(0.05, span / CLOCK - head)
    return {'recipe': RECIPE, 'start': start, 'span': span, 'seconds': span / CLOCK, 'segments': segments,
            'bytes': sum((folder / s['name']).stat().st_size for s in segments), 'built_at': time.time()}


def read_meta(folder):
    try:
        meta = json.loads((Path(folder) / 'meta.json').read_text())
    except (OSError, ValueError):
        return None
    return meta if isinstance(meta, dict) and meta.get('recipe') == RECIPE and meta.get('segments') else None
