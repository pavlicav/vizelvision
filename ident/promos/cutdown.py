"""What the 5-second cutdowns share: a 10-second promo's picture, re-timed.

A cutdown module names its SOURCE (a promo id) and PIECES, the stretches of the source it
plays, in order, as (from, to) in the source's seconds; they add up to its DURATION. Cut
on the beat (multiples of half a second), so the music's splices land in time. LINES are
the source's voice lines it keeps, each (line id, at), at their times in the cut; music.py
(excerpt) cuts the source's music without its voice the same way and lays them back over it.
"""
import importlib

from common import FPS, ease_in_out, span


def source(promo_id):
    return importlib.import_module(promo_id.replace('-', '_'))


def source_time(pieces, t):
    """Where in the source the cut is at t."""
    at = 0.0
    for a, b in pieces:
        if t < at + (b - a):
            return a + (t - at)
        at += b - a
    return pieces[-1][1]


def cut_time(pieces, s):
    """Where a source time falls in the cut: the next piece's start if it is cut out, None
    if it comes after the last piece."""
    at = 0.0
    for a, b in pieces:
        if s < a:
            return at
        if s <= b:
            return at + s - a
        at += b - a
    return None


def overlays(source_id, pieces, duration):
    """The source's live text, re-timed to the cut (only what falls inside it)."""
    out = []
    for item in source(source_id).OVERLAYS:
        start, end = cut_time(pieces, item['from']), cut_time(pieces, item['to'])
        if start is None or (end is not None and end <= start):
            continue
        out.append({**item, 'from': round(start, 3), 'to': round(duration if end is None else end, 3)})
    return out


def drawer(source_id, pieces, fade_in=0.2, fade_out=None):
    """draw(ctx, t, frame) for the cutdown: the source's frame for t, faded up from black
    over fade_in seconds (a cut that starts mid-scene), and down over fade_out (a pair)."""
    picture = source(source_id)

    def draw(ctx, t, frame):
        s = source_time(pieces, t)
        picture.draw(ctx, s, int(round(s * FPS)))
        black = 1 - ease_in_out(span(t, 0.0, fade_in)) if fade_in else 0.0
        if fade_out:
            black = max(black, ease_in_out(span(t, *fade_out)))
        if black > 0:
            ctx.set_source_rgba(0, 0, 0, black)
            ctx.paint()
    return draw
