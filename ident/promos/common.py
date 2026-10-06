"""What the station promos' pictures share: the station ID's drawing kit (animation.py:
the inked Memphis look, the chrome, the TV emblem and the wordmark), film grain, an iris,
a fade, and a 5x7 pixel face.

Every promo module has: ID, NAME, KIND, ORDER, DESCRIPTION, DURATION, STILL_AT, OVERLAYS
(live text master draws as it airs; see roku_stream/promo_overlay.py), optionally VOICE
(a copy voiced for the programme on air; see roku_stream/promos.py), and draw(ctx, t, frame).
"""
import math
import random
import sys
from functools import lru_cache
from pathlib import Path

import cairo

HERE = Path(__file__).resolve().parent
IDENT = HERE.parent
sys.path.insert(0, str(IDENT))
import animation as A  # noqa: E402,F401  The ID's kit.
from animation import (CYAN, H, INK, LIME, ORANGE, PINK, TAU, TEAL, W, WHITE, YELLOW, back_out, chrome,  # noqa: E402,F401
                       clamp, ease_in, ease_in_out, ease_out, elastic_out, font, glint, inked, inked_stroke, mix,
                       pulse, rounded_rect, span, star)

FPS = 60


def frames(duration):
    return round(duration * FPS)


@lru_cache(maxsize=None)
def grain_surface(index, strength):
    """Film or tape grain at half size: grey specks, mostly transparent."""
    rand = random.Random(index * 7919 + 17)
    w, h = W // 2, H // 2
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    stride = surface.get_stride()
    data = surface.get_data()
    for y in range(h):
        row = y * stride
        noise = rand.randbytes(w)
        for x in range(w):
            v = noise[x]
            if v < 70:          # dark specks
                a = int((70 - v) * strength)
                data[row + 4 * x:row + 4 * x + 4] = bytes((0, 0, 0, a))
            elif v > 205:       # light specks (premultiplied)
                a = int((v - 205) * strength)
                data[row + 4 * x:row + 4 * x + 4] = bytes((a, a, a, a))
    surface.mark_dirty()
    return surface


def grain(ctx, frame, strength=0.9, every=2):
    ctx.save()
    ctx.scale(2, 2)
    ctx.set_source_surface(grain_surface((frame // every) % 8, strength), 0, 0)
    ctx.paint()
    ctx.restore()


@lru_cache(maxsize=None)
def vignette_surface(amount):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    g = cairo.RadialGradient(W / 2, H / 2, H * 0.38, W / 2, H / 2, W * 0.75)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0, 0, 0, amount)
    ctx.set_source(g)
    ctx.paint()
    return surface


def vignette(ctx, amount=0.5):
    ctx.set_source_surface(vignette_surface(amount), 0, 0)
    ctx.paint()


def scanlines(ctx, alpha=0.12, step=3):
    ctx.set_source_rgba(0, 0, 0, alpha)
    for y in range(0, H, step):
        ctx.rectangle(0, y, W, 1)
    ctx.fill()


def to_black(ctx, t, start, end):
    """A fade to black from start to end, and black after."""
    amount = span(t, start, end)
    if amount > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(amount))
        ctx.paint()


def iris(ctx, x, y, radius):
    """Black everywhere but a circle (the ID's iris)."""
    ctx.save()
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.rectangle(-20, -20, W + 40, H + 40)
    if radius > 0.5:
        ctx.arc(x, y, radius, 0, TAU)
    ctx.set_source_rgb(0, 0, 0)
    ctx.fill()
    ctx.restore()


def flash(ctx, amount, colour=WHITE):
    if amount > 0:
        ctx.set_source_rgba(*colour, min(1.0, amount))
        ctx.paint()


def text_path(ctx, text, x, y, tracking=0.0, align='left'):
    """Letters along a baseline with extra tracking (px); returns the width."""
    advances = [ctx.text_extents(ch).x_advance for ch in text]
    width = sum(advances) + tracking * (len(text) - 1)
    if align == 'center':
        x -= width / 2
    elif align == 'right':
        x -= width
    for ch, advance in zip(text, advances):
        ctx.move_to(x, y)
        ctx.text_path(ch)
        x += advance + tracking
    return width


# ---------------------------------------------------------------- a 5x7 pixel face

PIXEL_FONT = {
    'A': '01110 10001 10001 11111 10001 10001 10001', 'B': '11110 10001 10001 11110 10001 10001 11110',
    'C': '01110 10001 10000 10000 10000 10001 01110', 'D': '11110 10001 10001 10001 10001 10001 11110',
    'E': '11111 10000 10000 11110 10000 10000 11111', 'F': '11111 10000 10000 11110 10000 10000 10000',
    'G': '01110 10001 10000 10111 10001 10001 01111', 'H': '10001 10001 10001 11111 10001 10001 10001',
    'I': '01110 00100 00100 00100 00100 00100 01110', 'J': '00111 00010 00010 00010 00010 10010 01100',
    'K': '10001 10010 10100 11000 10100 10010 10001', 'L': '10000 10000 10000 10000 10000 10000 11111',
    'M': '10001 11011 10101 10101 10001 10001 10001', 'N': '10001 11001 10101 10011 10001 10001 10001',
    'O': '01110 10001 10001 10001 10001 10001 01110', 'P': '11110 10001 10001 11110 10000 10000 10000',
    'Q': '01110 10001 10001 10001 10101 10010 01101', 'R': '11110 10001 10001 11110 10100 10010 10001',
    'S': '01111 10000 10000 01110 00001 00001 11110', 'T': '11111 00100 00100 00100 00100 00100 00100',
    'U': '10001 10001 10001 10001 10001 10001 01110', 'V': '10001 10001 10001 10001 10001 01010 00100',
    'W': '10001 10001 10001 10101 10101 10101 01010', 'X': '10001 10001 01010 00100 01010 10001 10001',
    'Y': '10001 10001 01010 00100 00100 00100 00100', 'Z': '11111 00001 00010 00100 01000 10000 11111',
    '0': '01110 10001 10011 10101 11001 10001 01110', '1': '00100 01100 00100 00100 00100 00100 01110',
    '2': '01110 10001 00001 00010 00100 01000 11111', '3': '11110 00001 00001 01110 00001 00001 11110',
    '4': '00010 00110 01010 10010 11111 00010 00010', '5': '11111 10000 11110 00001 00001 10001 01110',
    '6': '00110 01000 10000 11110 10001 10001 01110', '7': '11111 00001 00010 00100 01000 01000 01000',
    '8': '01110 10001 10001 01110 10001 10001 01110', '9': '01110 10001 10001 01111 00001 00010 01100',
    '+': '00000 00100 00100 11111 00100 00100 00000', '-': '00000 00000 00000 11111 00000 00000 00000',
    '!': '00100 00100 00100 00100 00100 00000 00100', '.': '00000 00000 00000 00000 00000 01100 01100',
    ':': '00000 01100 01100 00000 01100 01100 00000', '?': '01110 10001 00001 00010 00100 00000 00100',
    ' ': '00000 00000 00000 00000 00000 00000 00000', '©': '01110 10001 10111 11001 10111 10001 01110',
}


def pixel_text(ctx, text, x, y, cell, colour, align='left', shadow=None):
    """text in the 5x7 face, each dot cell px square, top-left at (x, y). Returns its width."""
    width = (len(text) * 6 - 1) * cell
    if align == 'center':
        x -= width / 2
    elif align == 'right':
        x -= width
    if shadow:       # (dx, dy, colour), in dots
        _dots(ctx, text, x + shadow[0] * cell, y + shadow[1] * cell, cell, shadow[2])
    _dots(ctx, text, x, y, cell, colour)
    return width


def _dots(ctx, text, x, y, cell, colour):
    for i, ch in enumerate(text.upper()):
        rows = PIXEL_FONT.get(ch, PIXEL_FONT['?']).split()
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == '1':
                    ctx.rectangle(x + (i * 6 + c) * cell, y + r * cell, cell, cell)
    ctx.set_source_rgb(*colour)
    ctx.fill()


def still(module, t, path):
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    module.draw(cairo.Context(surface), t, int(t * FPS))
    surface.write_to_png(str(path))


def render_frame(module, frame):
    """One frame as raw BGRx bytes (ffmpeg pix_fmt bgr0)."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    module.draw(cairo.Context(surface), frame / FPS, frame)
    surface.flush()
    return bytes(surface.get_data())
