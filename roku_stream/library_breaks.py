"""Ad breaks for library files: where a show faded to black and silence for its commercials.

A show made for commercial TV still carries its act breaks after the ads are gone: the
picture fades to black and the sound goes quiet at the same moment. An ordinary edit is a
hard cut with the narration or music running on, so it is never one. Some copies (the
newer How It's Made web files) even keep a slug of about six seconds of black and silence
where the network spliced its ads.

Finding them is cheap: one pass over the sound alone for its quiet moments (seconds for an
episode), then a look at the picture just around each one for black (a fraction of a
second of decoding each). A full decode of a 22-minute HEVC episode takes minutes.

Picking them (choose):
  - candidates: black and silence together (or within GAP of each other);
  - slugs (both over SLUG seconds): when a file has any, they are its breaks, exactly;
  - otherwise candidates closer than CLUSTER seconds belong to one transition (the fade,
    the show's return bumper, the next segment's title), and the break goes at the first:
    where the segment ended, before the bumper;
  - none in the first LEAD_IN or the last LEAD_OUT seconds (the open and the credits);
  - about one break every SPACING seconds (3 in a half hour), the transitions nearest
    evenly spaced points, none closer than MIN_APART.

A break is {'at': seconds, 'resume': seconds, 'kind': 'slug'|'fade', 'score'}: the file
pauses at `at` (a dark, quiet frame) and plays on from `resume` (past a slug's black).
"""
from __future__ import annotations

import json
import re
import subprocess

SILENCE_DB = -45
SILENCE_MIN = .2
BLACK_MIN = .1
BLACK_PIXEL = .10
GAP = .25
SLUG = 2.
CLUSTER = 45.
LEAD_IN = 90.
LEAD_OUT = 90.
SPACING = 420.
MIN_APART = 150.
WINDOW_PAD = 1.
WINDOW_LONGEST = 14.
RESUME_BEFORE = .25
PASS_TIMEOUT = 600
WINDOW_TIMEOUT = 60
VERSION = 1   # a cached result from another version is found again

_SILENCE = re.compile(r'silence_(start|end): (-?[\d.]+)')
_BLACK = re.compile(r'black_start:\s*(-?[\d.]+)\s+black_end:\s*(-?[\d.]+)')


def _nice():
    return ['nice', '-n', '19', 'ionice', '-c', '3']


def tracks(path, *, runner=subprocess.run):
    """(video stream index, audio stream index, audio track count): the file's picture (not
    cover art) and its English sound, else its default or first."""
    result = runner(['ffprobe', '-v', 'error', '-show_entries',
                     'stream=index,codec_type:stream_tags=language:stream_disposition=default,attached_pic',
                     '-of', 'json', str(path)], capture_output=True, timeout=30, check=False)
    streams = [s for s in json.loads(result.stdout or b'{}').get('streams', []) if isinstance(s, dict)]
    video = next((s['index'] for s in streams if s.get('codec_type') == 'video'
                  and not (s.get('disposition') or {}).get('attached_pic')), None)
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    english = next((s for s in audio if (s.get('tags') or {}).get('language', '').lower() in ('en', 'eng')), None)
    chosen = english or (audio[0] if audio else None)
    return video, chosen['index'] if chosen else None, len(audio)


def silences(path, audio, *, runner=subprocess.run):
    """[(start, end)] of the quiet moments of one sound track."""
    result = runner([*_nice(), 'ffmpeg', '-hide_banner', '-nostats', '-v', 'info', '-i', str(path),
                     '-map', f'0:{audio}', '-vn', '-sn', '-dn',
                     '-af', f'silencedetect=n={SILENCE_DB}dB:d={SILENCE_MIN}', '-f', 'null', '-'],
                    capture_output=True, timeout=PASS_TIMEOUT, check=False)
    if result.returncode:
        raise RuntimeError('Could not read the sound')
    found, start = [], None
    for kind, value in _SILENCE.findall(result.stderr.decode('utf-8', 'replace')):
        if kind == 'start':
            start = max(0., float(value))
        elif start is not None:
            found.append((start, float(value)))
            start = None
    return found


def windows(quiet, duration):
    """The stretches of picture worth decoding: around each quiet moment, merged when close."""
    spans = []
    for start, end in quiet:
        if end - start > WINDOW_LONGEST:   # a long silence: only its edges can hold a fade
            spans += [(start - WINDOW_PAD, start + WINDOW_PAD), (end - WINDOW_PAD, end + WINDOW_PAD)]
        else:
            spans.append((start - WINDOW_PAD, end + WINDOW_PAD))
    merged = []
    for start, end in sorted((max(0., a), min(duration, b) if duration else b) for a, b in spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [(a, b) for a, b in merged if b > a]


def blacks(path, video, spans, *, runner=subprocess.run):
    """[(start, end)] of black picture inside the given stretches."""
    found = []
    for start, end in spans:
        result = runner([*_nice(), 'ffmpeg', '-hide_banner', '-nostats', '-v', 'info', '-threads', '2',
                         '-ss', f'{start:.3f}', '-t', f'{end - start:.3f}', '-i', str(path),
                         '-map', f'0:{video}', '-an', '-sn', '-dn',
                         '-vf', f'scale=320:-2,blackdetect=d={BLACK_MIN}:pix_th={BLACK_PIXEL}:pic_th=0.98',
                         '-f', 'null', '-'], capture_output=True, timeout=WINDOW_TIMEOUT, check=False)
        if result.returncode:
            continue
        for a, b in _BLACK.findall(result.stderr.decode('utf-8', 'replace')):
            found.append((start + max(0., float(a)), start + float(b)))
    return found


def candidates(black, quiet):
    """Moments of black and silence together, strongest evidence first in score."""
    found = []
    for b0, b1 in black:
        for s0, s1 in quiet:
            if b0 > s1 + GAP or s0 > b1 + GAP:
                continue
            o0, o1 = max(b0, s0), min(b1, s1)
            at = o0 + min(.1, max(0., o1 - o0) / 2) if o1 > o0 else (b0 + b1) / 2
            slug = b1 - b0 >= SLUG and s1 - s0 >= SLUG
            found.append({'at': round(at, 3), 'resume': round(max(at, b1 - RESUME_BEFORE) if slug else at, 3),
                          'kind': 'slug' if slug else 'fade',
                          'score': round(max(0., o1 - o0) + .25 * min(s1 - s0, 2.) + .25 * min(b1 - b0, 2.), 3)})
            break
    found.sort(key=lambda c: c['at'])
    return found


def choose(found, duration):
    """The breaks among the candidates (see the module doc)."""
    if not duration or duration < LEAD_IN + LEAD_OUT + 60:
        return []
    inside = [c for c in found if LEAD_IN <= c['at'] <= duration - LEAD_OUT]
    slugs = [c for c in inside if c['kind'] == 'slug']
    if slugs:
        return _apart(slugs)
    clusters = []
    for c in inside:
        if clusters and c['at'] - clusters[-1][-1]['at'] <= CLUSTER:
            clusters[-1].append(c)
        else:
            clusters.append([c])
    firsts = [group[0] for group in clusters]
    wanted = max(1, round(duration / SPACING))
    if len(firsts) <= wanted:
        return _apart(firsts)
    picked = []
    for k in range(1, wanted + 1):
        ideal = duration * k / (wanted + 1)
        free = [c for c in firsts if c not in picked and all(abs(c['at'] - p['at']) >= MIN_APART for p in picked)]
        if free:
            picked.append(min(free, key=lambda c: abs(c['at'] - ideal)))
    return sorted(picked, key=lambda c: c['at'])


def _apart(found):
    kept = []
    for c in found:
        if not kept or c['at'] - kept[-1]['at'] >= MIN_APART:
            kept.append(c)
    return kept


def detect(path, duration, *, runner=subprocess.run):
    """{'state': 'ok'|'none'|'failed', 'breaks': [...], 'version', 'reason'?} for one file."""
    try:
        video, audio, _ = tracks(path, runner=runner)
        if video is None or audio is None:
            return {'state': 'failed', 'breaks': [], 'version': VERSION, 'reason': 'No picture or sound to look at'}
        quiet = silences(path, audio, runner=runner)
        black = blacks(path, video, windows(quiet, duration), runner=runner)
        breaks = choose(candidates(black, quiet), duration)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {'state': 'failed', 'breaks': [], 'version': VERSION, 'reason': str(exc)[:200] or 'Could not look at this file'}
    return {'state': 'ok' if breaks else 'none', 'breaks': breaks, 'version': VERSION}
