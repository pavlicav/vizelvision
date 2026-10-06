"""Time & Temperature: the 1970s station-break slide. The Washington skyline at dusk
under a striped retro sun, the brown-and-orange stripes of the era, a cream character-
generator panel that slides up, and the time and temperature, as they are when it airs,
flipping in on the vibraphone's logo. Film grain, gate weave and a slow push on the slide.

The numbers are master's live text (OVERLAYS); the picture leaves their boxes empty.
"""
import math
import random
from functools import lru_cache

import cairo

from common import (INK, TAU, W, H, back_out, clamp, ease_in_out, ease_out, flash, font, grain, inked, mix,  # noqa: F401
                    rounded_rect, span, text_path, to_black, vignette)

ID = 'time-temp'
NAME = 'Time & Temperature'
KIND = 'promo'
ORDER = 1
DESCRIPTION = ('The 1970s station-break slide: the Washington skyline at dusk, and the time and temperature '
               'as they are when it airs, over easy-listening vibes. Voiced by The Daytime Announcer.')
DURATION = 10.0
STILL_AT = 6.0

BROWN = (0.30, 0.16, 0.07)
CREAM = (0.99, 0.94, 0.80)
RUST = (0.86, 0.38, 0.10)
GOLD = (0.96, 0.69, 0.17)
TAN = (0.80, 0.58, 0.34)
DUSK = ((0.10, 0.11, 0.33), (0.55, 0.27, 0.45), (1.0, 0.60, 0.30))
PLUM = (0.16, 0.07, 0.19)
HORIZON = 520

# Hit points (the music's too: promos/music.py).
SLIDE = 0.12          # the slide drops into the gate
PANEL = (0.45, 1.05)  # the panel rises
TIME_IN, TEMP_IN = 1.5, 2.0   # on the vibes' G and A
FADE = (9.2, 9.55)

PANEL_BOX = (240, 286, 800, 310)
TIME_BOX = (256, 398, 370, 140)
TEMP_BOX = (654, 398, 370, 140)
PLACE_BOX = (654, 540, 370, 38)
AMPM_BOX = (530, 356, 92, 38)

_DIGITS = {'font': 'URW Bookman', 'bold': True, 'size': 150, 'min_size': 60, 'color': BROWN,
           'shadow': [5, 5, *GOLD, 1.0]}
OVERLAYS = [
    {'field': 'time', 'box': list(TIME_BOX), 'from': TIME_IN, 'to': FADE[1], 'style': _DIGITS,
     'enter': {'kind': 'flip', 'seconds': 0.35}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
    {'field': 'ampm', 'box': list(AMPM_BOX), 'from': TIME_IN + 0.15, 'to': FADE[1],
     'style': {'font': 'URW Bookman', 'bold': True, 'size': 30, 'min_size': 16, 'color': RUST, 'align': 'right',
               'tracking': 0.1},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
    {'field': 'temperature', 'box': list(TEMP_BOX), 'from': TEMP_IN, 'to': FADE[1], 'style': _DIGITS,
     'enter': {'kind': 'flip', 'seconds': 0.35}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
    {'field': 'place', 'box': list(PLACE_BOX), 'from': TEMP_IN + 0.3, 'to': FADE[1],
     'style': {'font': 'URW Bookman', 'bold': True, 'italic': True, 'size': 26, 'min_size': 14, 'color': RUST,
               'upper': True, 'tracking': 0.08},
     'enter': {'kind': 'fade', 'seconds': 0.4}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
]


# ---------------------------------------------------------------- the slide (it weaves in the gate)

def sky(ctx):
    g = cairo.LinearGradient(0, 0, 0, HORIZON)
    for stop, rgb in zip((0, 0.6, 1), DUSK):
        g.add_color_stop_rgb(stop, *rgb)
    ctx.set_source(g)
    ctx.rectangle(-40, -40, W + 80, HORIZON + 40)
    ctx.fill()


def sun(ctx, t):
    """The retro sun: a low disc, cut by horizontal bands that thicken towards the horizon."""
    cx, cy, r = 640, 330, 190 + 3 * math.sin(t * 1.3)
    ctx.save()
    ctx.rectangle(-40, -40, W + 80, HORIZON + 40)
    ctx.clip()
    glow = cairo.RadialGradient(cx, cy, r * 0.6, cx, cy, r * 1.9)
    glow.add_color_stop_rgba(0, 1, 0.75, 0.35, 0.45)
    glow.add_color_stop_rgba(1, 1, 0.6, 0.3, 0)
    ctx.set_source(glow)
    ctx.paint()
    ctx.new_path()
    ctx.arc(cx, cy, r, 0, TAU)
    for i in range(7):  # the cut bands, moving slowly down
        y = cy - r * 0.15 + i * 34 + (t * 6) % 34
        ctx.rectangle(cx - r - 2, y, 2 * r + 4, 3 + i * 2.2)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    g = cairo.LinearGradient(0, cy - r, 0, cy + r * 0.4)
    g.add_color_stop_rgb(0, 1.0, 0.93, 0.48)
    g.add_color_stop_rgb(1, 1.0, 0.48, 0.18)
    ctx.set_source(g)
    ctx.fill()
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
    ctx.restore()


@lru_cache(maxsize=None)
def buildings():
    rand = random.Random(1976)
    blocks, x = [], -40
    while x < W + 40:
        w = rand.randint(40, 110)
        h = rand.randint(26, 84)
        if 100 < x < 200 or 990 < x < 1340:   # leave the Monument and the Capitol clear
            h = rand.randint(18, 34)
        blocks.append((x, w, h))
        x += w + rand.randint(-8, 6)
    windows = []
    for bx, bw, bh in blocks:
        for wy in range(HORIZON - bh + 8, HORIZON - 6, 11):
            for wx in range(bx + 6, bx + bw - 6, 12):
                if rand.random() < 0.28:
                    windows.append((wx, wy, rand.random() * TAU, rand.uniform(0.4, 1.6)))
    trees = [(rand.uniform(-20, W + 20), rand.uniform(14, 30)) for _ in range(26)]
    return blocks, windows, trees


def skyline(ctx, t):
    blocks, windows, trees = buildings()
    ctx.set_source_rgb(*PLUM)
    for x, w, h in blocks:
        ctx.rectangle(x, HORIZON - h, w, h + 2)
    for x, r in trees:
        ctx.arc(x, HORIZON - r * 0.4, r, 0, TAU)
        ctx.new_sub_path()
    ctx.fill()
    # The Washington Monument: an obelisk with its pyramidion.
    mx, base, top, height = 150, 19, 13, 255
    ctx.move_to(mx - base, HORIZON)
    ctx.line_to(mx - top, HORIZON - height)
    ctx.line_to(mx, HORIZON - height - 22)
    ctx.line_to(mx + top, HORIZON - height)
    ctx.line_to(mx + base, HORIZON)
    ctx.close_path()
    # The Capitol: wings, the drum and colonnade, the dome, the lantern and the statue.
    cx = 1165
    ctx.rectangle(cx - 165, HORIZON - 52, 330, 54)
    ctx.rectangle(cx - 60, HORIZON - 78, 120, 30)
    ctx.rectangle(cx - 48, HORIZON - 120, 96, 44)
    ctx.move_to(cx - 54, HORIZON - 118)
    ctx.curve_to(cx - 54, HORIZON - 190, cx + 54, HORIZON - 190, cx + 54, HORIZON - 118)
    ctx.close_path()
    ctx.rectangle(cx - 9, HORIZON - 204, 18, 22)
    ctx.rectangle(cx - 3, HORIZON - 222, 6, 20)
    ctx.set_source_rgb(*PLUM)
    ctx.fill()
    # Its colonnade and the Monument's lamp catch the last light.
    ctx.set_source_rgba(1, 0.75, 0.45, 0.25)
    for i in range(9):
        ctx.rectangle(cx - 44 + i * 11, HORIZON - 114, 4, 34)
    ctx.fill()
    blink = 0.5 + 0.5 * math.sin(t * 5)
    ctx.set_source_rgba(1, 0.25, 0.2, 0.5 + 0.5 * blink)
    ctx.arc(mx, HORIZON - height - 10, 2.5, 0, TAU)
    ctx.fill()
    for x, y, phase, rate in windows:   # the city lights coming on
        a = clamp(0.55 + 0.45 * math.sin(phase + t * rate))
        ctx.set_source_rgba(1, 0.85, 0.45, 0.85 * a)
        ctx.rectangle(x, y, 4, 5)
        ctx.fill()


def ground(ctx):
    ctx.set_source_rgb(0.12, 0.05, 0.12)
    ctx.rectangle(-40, HORIZON, W + 80, H - HORIZON + 40)
    ctx.fill()
    # The water of the Tidal Basin: the sun's reflection in streaks.
    for i in range(9):
        y = HORIZON + 8 + i * 9
        w = 260 - i * 18
        ctx.set_source_rgba(1, 0.65, 0.3, 0.35 - i * 0.03)
        ctx.rectangle(640 - w / 2 + math.sin(i * 1.7) * 12, y, w, 3)
        ctx.fill()


STRIPES = (CREAM, GOLD, RUST, BROWN)


def stripes(ctx, t):
    """The decade's stripes: four bands along the bottom that turn the corner and run up
    the left edge, sweeping in from the right."""
    p = ease_out(span(t, SLIDE, SLIDE + 0.9))
    cx, cy = 236, 500
    ctx.save()
    ctx.rectangle(W + 40 - (W + 80) * p, -40, (W + 80) * p, H + 80)
    ctx.clip()
    ctx.set_line_width(27)
    for i, colour in enumerate(STRIPES):      # cream innermost, brown outermost
        r = 132 + i * 26
        ctx.move_to(W + 40, cy + r)
        ctx.line_to(cx, cy + r)
        ctx.arc(cx, cy, r, TAU / 4, TAU / 2)
        ctx.line_to(cx - r, -40)
        ctx.set_source_rgb(*colour)
        ctx.stroke()
    ctx.restore()


def slide(ctx, t):
    """Everything on the slide: it drops into the gate, weaves a little and is slowly pushed in."""
    drop = 22 * (1 - ease_out(span(t, SLIDE, SLIDE + 0.25)))
    weave_x = 1.3 * math.sin(t * 13.1) + 0.6 * math.sin(t * 31.7)
    weave_y = 1.1 * math.sin(t * 11.3 + 1.0) + drop
    push = 1 + 0.035 * t / DURATION
    ctx.save()
    ctx.translate(W / 2 + weave_x, H / 2 + weave_y)
    ctx.scale(push, push)
    ctx.translate(-W / 2, -H / 2)
    sky(ctx)
    sun(ctx, t)
    ground(ctx)
    skyline(ctx, t)
    stripes(ctx, t)
    ctx.restore()


# ---------------------------------------------------------------- the panel (the character generator: steady)

def clock_icon(ctx, x, y, r, t):
    ctx.arc(x, y, r, 0, TAU)
    ctx.set_source_rgb(*BROWN)
    ctx.set_line_width(3.5)
    ctx.stroke()
    for angle, length in ((t * 0.6 - TAU / 4, r * 0.55), (t * 6 - TAU / 4, r * 0.8)):
        ctx.move_to(x, y)
        ctx.line_to(x + math.cos(angle) * length, y + math.sin(angle) * length)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()


def sun_icon(ctx, x, y, r, t):
    ctx.arc(x, y, r * 0.5, 0, TAU)
    ctx.set_source_rgb(*RUST)
    ctx.fill()
    ctx.set_line_width(3)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for i in range(8):
        a = i * TAU / 8 + t * 0.5
        ctx.move_to(x + math.cos(a) * r * 0.72, y + math.sin(a) * r * 0.72)
        ctx.line_to(x + math.cos(a) * r, y + math.sin(a) * r)
    ctx.stroke()


def panel(ctx, t):
    p = span(t, *PANEL)
    if p <= 0:
        return
    x, y, w, h = PANEL_BOX
    ctx.save()
    ctx.translate(0, (1 - back_out(p, 1.4)) * 520)
    rounded_rect(ctx, x, y, w, h, 30)
    inked(ctx, CREAM, 7, (10, 10))
    # Header: the station and the slide's title.
    ctx.save()
    rounded_rect(ctx, x, y, w, h, 30)
    ctx.clip()
    ctx.rectangle(x, y, w, 58)
    ctx.set_source_rgb(*RUST)
    ctx.fill()
    for i, colour in enumerate((GOLD, CREAM)):
        ctx.rectangle(x, y + 58 + i * 6, w, 4)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    ctx.restore()
    rounded_rect(ctx, x, y, w, h, 30)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(7)
    ctx.stroke()
    font(ctx, 'URW Bookman', 32, italic=True)
    ctx.set_source_rgb(*CREAM)
    text_path(ctx, 'VizelVision', x + 34, y + 41)
    ctx.fill()
    font(ctx, 'URW Bookman', 24)
    text_path(ctx, 'TIME  &  TEMPERATURE', x + w - 34, y + 39, tracking=3, align='right')
    ctx.fill()
    # The two cells, their labels and icons; the numbers are master's.
    ctx.set_source_rgb(*BROWN)
    ctx.rectangle(x + w / 2 - 3, y + 92, 6, h - 120)
    ctx.fill()
    font(ctx, 'URW Bookman', 30)
    for label, lx, icon in (('TIME', x + 74, clock_icon), ('TEMP', x + w / 2 + 70, sun_icon)):
        ctx.set_source_rgb(*BROWN)
        text_path(ctx, label, lx, y + 104, tracking=4)
        ctx.fill()
        icon(ctx, lx - 26, y + 93, 15, t)
    ctx.restore()


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t < SLIDE or t >= FADE[1]:
        return
    slide(ctx, t)
    panel(ctx, t)
    vignette(ctx, 0.55)
    # Warm the whole slide a touch, as old stock does.
    ctx.set_source_rgba(1.0, 0.7, 0.35, 0.06)
    ctx.paint()
    grain(ctx, frame, 0.55)
    flash(ctx, 0.9 * (1 - span(t, SLIDE, SLIDE + 0.12)))   # the projector lamp on the new slide
    to_black(ctx, t, *FADE)
