"""Compare the cable picture with the published master, allowing playout delay.

Use coarse spatial structure so analog noise and compression don't dominate.
An aligned sequence must match, not just one lucky frame or an ECP play state.
This is deliberately conservative: uncertain reception must not turn green.
"""
from concurrent.futures import ThreadPoolExecutor
import base64
import math
import struct
import subprocess
import zlib

from .errors import RokuStreamError

WIDTH, HEIGHT = 160, 120
FPS, SAMPLE_COUNT, MAX_LAG = 2, 60, 40
MIN_PAIRS = 20


def _decode(url):
    try:
        result = subprocess.run(
            ['ffmpeg', '-nostdin', '-v', 'error', '-rw_timeout', '10000000',
             '-live_start_index', '-1', '-i', url, '-an', '-vf',
             f'fps={FPS},scale={WIDTH}:{HEIGHT}', '-frames:v', str(SAMPLE_COUNT),
             '-pix_fmt', 'rgb24', '-f', 'rawvideo', 'pipe:1'],
            capture_output=True, timeout=55, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RokuStreamError(f'Video decode failed ({type(exc).__name__})') from exc
    size = WIDTH * HEIGHT * 3
    if len(result.stdout) != size * SAMPLE_COUNT:
        raise RokuStreamError('Stream did not deliver a complete comparison window')
    return [result.stdout[i:i+size] for i in range(0, len(result.stdout), size)]


def _png(frame):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    rows = b''.join(b'\0' + frame[i:i+WIDTH*3] for i in range(0, len(frame), WIDTH*3))
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('!2I5B', WIDTH, HEIGHT, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))
    return base64.b64encode(png).decode('ascii')


def _feature(frame, crop):
    """16x12 block averages, excluding borders after the geometry correction."""
    left, top, right, bottom = crop
    values, colors = [], [0., 0., 0.]
    for row in range(12):
        y0, y1 = top + row*(bottom-top)//12, top + (row+1)*(bottom-top)//12
        for col in range(16):
            x0, x1 = left + col*(right-left)//16, left + (col+1)*(right-left)//16
            channels = [0, 0, 0]
            for y in range(y0, y1):
                for x in range(x0, x1):
                    pos = (y*WIDTH + x)*3
                    for c in range(3):
                        channels[c] += frame[pos+c]
            count = (y1-y0)*(x1-x0)
            rgb = [v/count for v in channels]
            values.append((77*rgb[0] + 150*rgb[1] + 29*rgb[2])/256)
            for c in range(3):
                colors[c] += rgb[c]/192
    mean = sum(values)/len(values)
    centered = [v-mean for v in values]
    norm = math.sqrt(sum(v*v for v in centered))
    return values, centered, norm, colors


def _score(a, b):
    # Snow has plenty of pixel contrast but little coherent coarse structure.
    if min(a[2], b[2])/math.sqrt(192) < 8:
        return 0.
    if max(abs(x-y) for x, y in zip(a[3], b[3])) > 50:
        return 0.
    return sum(x*y for x, y in zip(a[1], b[1])) / (a[2]*b[2])


def _change(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a[0], b[0]))/192)


def compare_frames(cable, reference):
    if min(len(cable), len(reference)) < MIN_PAIRS:
        return {'matches_master': None, 'reason': 'insufficient_samples'}
    # The 4:3 analog path may stretch 16:9, letterbox it, or overscan it.
    full, letterbox, overscan = (4, 3, 156, 117), (4, 17, 156, 103), (12, 9, 148, 111)
    cable_features = {crop: [_feature(f, crop) for f in cable] for crop in (full, letterbox)}
    master_features = {crop: [_feature(f, crop) for f in reference] for crop in (full, overscan)}
    best = None
    for name, ccrop, mcrop in [('full', full, full), ('letterbox', letterbox, full),
                               ('overscan', full, overscan), ('letterbox_overscan', letterbox, overscan)]:
        cf, mf = cable_features[ccrop], master_features[mcrop]
        # The return must follow the master. Do not accept a negative offset
        # that discards the newest cable frames and hides a recent failure.
        for lag in range(MAX_LAG+1):
            pairs = [(cf[i], mf[i-lag]) for i in range(len(cf)) if 0 <= i-lag < len(mf)]
            if len(pairs) < MIN_PAIRS:
                continue
            scores = [_score(c, m) for c, m in pairs]
            matched = sum(s >= .88 for s in scores)
            # A held return must not match a changing master just because the
            # background/graphics stay similar throughout a shot.
            moving = followed = 0
            for (c0, m0), (c1, m1) in zip(pairs, pairs[1:]):
                change = _change(m0, m1)
                if change >= 5:
                    moving += 1
                    followed += _change(c0, c1) >= change*.3
            progression = not moving or followed/moving >= .8
            fraction = matched/len(pairs)
            latest_matches = all(s >= .88 for s in scores[-3:])
            matches = fraction >= .8 and progression and latest_matches
            rank = (matches, fraction, sum(scores)/len(scores), len(pairs))
            if best is None or rank > best[0]:
                best = (rank, {'matches_master': matches,
                               'reason': 'matched' if matches else 'picture_mismatch',
                               'matched_samples': matched, 'compared_samples': len(pairs),
                               'match_fraction': round(fraction, 3),
                               'mean_similarity': round(sum(scores)/len(scores), 3),
                               'sample_offset_seconds': lag/FPS, 'geometry': name,
                               'motion_consistent': progression,
                               'latest_samples_match': latest_matches})
    return best[1]


def capture_return(url, reference_url):
    """Sample both live streams concurrently; no reference means no verdict."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        cable_future = pool.submit(_decode, url)
        master_future = pool.submit(_decode, reference_url)
        cable = cable_future.result()
        result = {'video_received': True, 'sample_count': len(cable),
                  'image_base64': _png(cable[-1])}
        try:
            master = master_future.result()
        except RokuStreamError as exc:
            result['comparison'] = {'matches_master': None, 'reason': 'reference_unavailable',
                                    'error': str(exc)}
            return result
    result['comparison'] = compare_frames(cable, master)
    return result
