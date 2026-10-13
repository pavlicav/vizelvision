"""VizelVision '86: the station as it promoted itself in 1986. A striped sunset over a neon
grid rolling towards us, wireframe mountains, stars. On the open logo four laser beams
fire from the sun; the wordmark flies in from the distance as a cyan wireframe, turning,
and on the downbeat it is solid chrome, sky above its horizon line and earth below,
extruded in magenta, with a glint running through it. GET THE PICTURE! wipes in in hot
pink with a neon 19 buzzing on beside it; on the closed logo the grid pulses with each
note and sparkles land on the chrome.

Hermes, the promo voice: "Vizzle Vision nineteen..." / "Get the picture!"
"""
import math
import random
from functools import lru_cache

import cairo

from common import (TAU, W, H, back_out, clamp, ease_in, ease_in_out, ease_out, glint, grain, mix, pulse, span,  # noqa: F401
                    text_path, vignette)

ID = 'eighty-six'
NAME = "VizelVision '86"
KIND = 'ident'
ORDER = 13
DESCRIPTION = ("1986: a striped sunset over a neon grid, laser beams on the logo, the wordmark flying in as a "
               'wireframe and turning to extruded chrome, GET THE PICTURE! and a neon 19. FM bells, gated '
               'snares, an orchestra hit. Hermes.')
DURATION = 10.0
STILL_AT = 8.5
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
GRID_IN = (0.0, 0.8)
SUN_UP = (0.2, 1.4)
LASERS = (1.0, 1.25, 1.5, 2.0)                 # the open logo: a beam each
FLY = (2.0, 3.0)                               # the wireframe flies in, turning
CHROME = 3.0                                   # solid chrome: the orchestra hit
GLINT = (3.1, 3.7)
TAGLINE = (4.9, 5.3)                           # GET THE PICTURE! ("Get the picture!" at 5.0)
NEON = 5.4                                     # the 19 buzzes on
LIFT = 7.0                                     # the closed logo: the grid pulses on each note
SPARKLES = (7.0, 7.25, 7.5, 8.0)
FADE = (9.25, 9.6)

HORIZON = 420
SUN = (640, HORIZON, 175)
BASELINE = 300
HOT_PINK = (1.0, 0.16, 0.62)
NEON_CYAN = (0.2, 0.95, 1.0)


# ---------------------------------------------------------------- the world

def sky(ctx, t):
    g = cairo.LinearGradient(0, 0, 0, HORIZON)
    g.add_color_stop_rgb(0, 0.02, 0.0, 0.08)
    g.add_color_stop_rgb(0.65, 0.16, 0.02, 0.3)
    g.add_color_stop_rgb(1, 0.55, 0.06, 0.42)
    ctx.set_source(g)
    ctx.rectangle(0, 0, W, HORIZON)
    ctx.fill()
    rand = random.Random(86)
    for k in range(70):
        x, y = rand.uniform(0, W), rand.uniform(0, HORIZON - 120)
        a = 0.3 + 0.7 * (0.5 + 0.5 * math.sin(t * rand.uniform(2, 5) + k))
        ctx.arc(x, y, rand.uniform(0.7, 1.6), 0, TAU)
        ctx.set_source_rgba(1, 1, 1, a * 0.8)
        ctx.fill()


def sun(ctx, t):
    cx, cy, r = SUN
    rise = ease_out(span(t, *SUN_UP))
    cy = cy + r * 1.1 * (1 - rise)
    ctx.save()
    ctx.rectangle(0, 0, W, HORIZON)
    ctx.clip()
    glow = cairo.RadialGradient(cx, cy, r * 0.8, cx, cy, r * 2.4)
    glow.add_color_stop_rgba(0, 1, 0.3, 0.5, 0.45)
    glow.add_color_stop_rgba(1, 1, 0.3, 0.5, 0)
    ctx.set_source(glow)
    ctx.paint()
    ctx.new_path()
    ctx.arc(cx, cy, r, 0, TAU)
    for k in range(6):                                   # the stripes, wider towards the horizon
        y = cy - r * (0.62 - 0.12 * k) + (t * 10) % (r * 0.12)
        gap = 2 + 2.6 * k
        ctx.rectangle(cx - r - 2, y, 2 * r + 4, gap)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    g = cairo.LinearGradient(0, cy - r, 0, cy + r)
    g.add_color_stop_rgb(0, 1.0, 0.95, 0.35)
    g.add_color_stop_rgb(0.45, 1.0, 0.55, 0.15)
    g.add_color_stop_rgb(1, 1.0, 0.1, 0.55)
    ctx.set_source(g)
    ctx.fill()
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
    ctx.restore()


@lru_cache(maxsize=None)
def ridge(seed, base, height):
    rand = random.Random(seed)
    pts, x = [], -20
    while x < W + 40:
        pts.append((x, base - rand.uniform(0.25, 1.0) * height))
        x += rand.uniform(40, 90)
    return pts


def mountains(ctx):
    for seed, height, colour in ((3, 120, (0.15, 0.85, 1.0)), (5, 70, (0.9, 0.3, 1.0))):
        pts = ridge(seed, HORIZON, height)
        ctx.move_to(-20, HORIZON)
        for i, (x, y) in enumerate(pts):
            if 380 < x < 900:                            # a valley for the sun
                y = HORIZON - 12 - 10 * (i % 2)
            ctx.line_to(x, y)
        ctx.line_to(W + 40, HORIZON)
        ctx.close_path()
        ctx.set_source_rgb(0.04, 0.0, 0.1)
        ctx.fill_preserve()
        ctx.set_source_rgba(*colour, 0.85)
        ctx.set_line_width(2)
        ctx.stroke()


def grid(ctx, t):
    """The neon floor, rolling towards us; brighter on each note of the closed logo."""
    reach = ease_out(span(t, *GRID_IN))
    beat = max((pulse(t, s, 0.35) for s in SPARKLES), default=0.0) + 0.8 * pulse(t, CHROME, 0.6)
    ctx.rectangle(0, HORIZON, W, H - HORIZON)
    g = cairo.LinearGradient(0, HORIZON, 0, H)
    g.add_color_stop_rgb(0, 0.12, 0.0, 0.2)
    g.add_color_stop_rgb(1, 0.02, 0.0, 0.05)
    ctx.set_source(g)
    ctx.fill()
    if reach <= 0:
        return
    scroll = (t * 1.6) % 1.0
    ctx.save()
    ctx.rectangle(0, HORIZON, W, (H - HORIZON) * reach + 2)
    ctx.clip()
    ctx.set_line_cap(cairo.LINE_CAP_BUTT)
    for width, alpha in ((7, 0.18), (2, 0.95)):
        for k in range(1, 40):                           # across: closer together towards the horizon
            z = k - scroll
            if z <= 0.2:
                continue
            y = HORIZON + 300 / z
            if y > H + 10:
                continue
            ctx.move_to(0, y)
            ctx.line_to(W, y)
        for i in range(-22, 23):                         # along: to the vanishing point
            ctx.move_to(W / 2 + i * 14, HORIZON)
            ctx.line_to(W / 2 + i * 260, H + 300)
        ctx.set_source_rgba(*mix(HOT_PINK, (1, 0.85, 1), 0.5 * beat), alpha * (0.75 + 0.25 * beat))
        ctx.set_line_width(width)
        ctx.stroke()
    ctx.restore()
    haze = cairo.LinearGradient(0, HORIZON - 30, 0, HORIZON + 60)
    haze.add_color_stop_rgba(0, 1, 0.3, 0.7, 0)
    haze.add_color_stop_rgba(0.4, 1, 0.3, 0.7, 0.55)
    haze.add_color_stop_rgba(1, 1, 0.3, 0.7, 0)
    ctx.set_source(haze)
    ctx.rectangle(0, HORIZON - 30, W, 90)
    ctx.fill()


def lasers(ctx, t):
    colours = (NEON_CYAN, HOT_PINK, (1.0, 0.95, 0.3), (0.4, 1.0, 0.4))
    angles = (-2.45, -0.7, -2.0, -1.15)
    cx, cy = SUN[0], SUN[1] - 40
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for when, colour, angle in zip(LASERS, colours, angles):
        p = span(t, when, when + 0.7)
        if not 0 < p < 1:
            continue
        a = angle + 0.25 * ease_out(p) * (1 if angle < -1.57 else -1)
        strength = (1 - p) ** 1.5
        ex, ey = cx + math.cos(a) * 1600, cy + math.sin(a) * 1600
        for width, alpha in ((26, 0.12), (8, 0.35), (2.5, 1.0)):
            ctx.move_to(cx, cy)
            ctx.line_to(ex, ey)
            ctx.set_source_rgba(*colour, alpha * strength)
            ctx.set_line_width(width)
            ctx.stroke()
        if p < 0.3:
            glint(ctx, cx, cy, 60 * (1 - p / 0.3), p * 4, 1.0)
    ctx.restore()


# ---------------------------------------------------------------- the chrome wordmark

@lru_cache(maxsize=None)
def word_size():
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 8, 8))
    ctx.select_font_face('Nimbus Sans', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(100)
    ext = ctx.text_extents('VIZELVISION')
    return 100 * 940 / ext.x_advance


def word_path(ctx, dx=0.0, dy=0.0):
    size = word_size()
    ctx.select_font_face('Nimbus Sans', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', W / 2 + dx, BASELINE + dy, tracking=2, align='center')


def chrome_face(top, bottom):
    """The eighties chrome: a blue sky above a hard horizon, dark earth below glowing pink."""
    g = cairo.LinearGradient(0, top, 0, bottom)
    g.add_color_stop_rgb(0, 0.15, 0.3, 0.75)
    g.add_color_stop_rgb(0.3, 0.65, 0.85, 1.0)
    g.add_color_stop_rgb(0.52, 1.0, 1.0, 1.0)
    g.add_color_stop_rgb(0.53, 0.25, 0.12, 0.08)
    g.add_color_stop_rgb(0.75, 0.6, 0.3, 0.2)
    g.add_color_stop_rgb(1, 1.0, 0.55, 0.7)
    return g


def wordmark(ctx, t):
    if t < FLY[0]:
        return
    size = word_size()
    top, bottom = BASELINE - size * 0.73, BASELINE
    cx, cy = W / 2, BASELINE - size * 0.36
    p = span(t, *FLY)
    ctx.save()
    if p < 1:                                           # flying in from the distance, turning to face us
        k = 0.12 + 0.88 * ease_in(p, 2)
        turn = math.cos((1 - ease_out(p)) * 1.2)
        ctx.translate(cx, cy - 90 * (1 - p))
        ctx.scale(k * turn, k)
        ctx.translate(-cx, -cy)
        for dx, dy, alpha in ((14, 18, 0.45), (0, 0, 1.0)):
            word_path(ctx, dx, dy)
            ctx.set_source_rgba(*NEON_CYAN, alpha)
            ctx.set_line_width(2.2 / max(k, 0.3))
            ctx.stroke()
        ctx.restore()
        return
    settle = 1 + 0.06 * math.exp(-(t - CHROME) * 8) * math.cos((t - CHROME) * 30)
    ctx.translate(cx, cy)
    ctx.scale(settle, settle)
    ctx.translate(-cx, -cy)
    for k in range(16, 0, -1):                          # the extrusion, down and to the right
        word_path(ctx, k * 0.9, k * 1.3)
        ctx.set_source_rgb(*mix((0.95, 0.15, 0.6), (0.25, 0.0, 0.3), k / 16))
        ctx.fill()
    word_path(ctx)
    ctx.set_source(chrome_face(top, bottom))
    ctx.fill_preserve()
    ctx.set_source_rgb(1, 1, 1)
    ctx.set_line_width(2)
    ctx.stroke()
    for when in (GLINT, (LIFT + 0.1, LIFT + 0.8)):      # a band of light through the chrome
        q = span(t, *when)
        if 0 < q < 1:
            ctx.save()
            word_path(ctx)
            ctx.clip()
            x = 100 + 1100 * ease_in_out(q)
            g = cairo.LinearGradient(x - 70, 0, x + 70, 0)
            g.add_color_stop_rgba(0, 1, 1, 1, 0)
            g.add_color_stop_rgba(0.5, 1, 1, 1, 0.85)
            g.add_color_stop_rgba(1, 1, 1, 1, 0)
            ctx.set_source(g)
            ctx.paint()
            ctx.restore()
    ctx.restore()
    flash = 1 - span(t, CHROME, CHROME + 0.35)
    if flash > 0:
        ctx.set_source_rgba(1, 0.9, 1, 0.55 * flash)
        ctx.paint()
    letters = (150, 420, 640, 880, 1100)
    for i, when in enumerate(SPARKLES):
        q = span(t, when, when + 0.45)
        if 0 < q < 1:
            glint(ctx, letters[i % 5] + 30 * i, top + 10 + 25 * (i % 2), 34 * math.sin(math.pi * q), q * 3, 1)


# ---------------------------------------------------------------- the tagline and the neon 19

def tagline(ctx, t):
    p = span(t, *TAGLINE)
    if p <= 0:
        return
    text = 'GET THE PICTURE!'
    ctx.save()
    ctx.select_font_face('Nimbus Sans', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(58)
    width = ctx.text_extents(text).x_advance + 3 * len(text)
    x0, y = 600 - width / 2, 505
    ctx.rectangle(0, 0, x0 - 20 + (width + 60) * ease_out(p), H)
    ctx.clip()
    ctx.move_to(x0 - 10, y + 16)                        # the brush swoosh under it
    ctx.curve_to(x0 + width * 0.3, y + 30, x0 + width * 0.7, y + 4, x0 + width + 20, y + 12)
    ctx.set_source_rgba(0.35, 0.95, 1.0, 0.9)
    ctx.set_line_width(7)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    ctx.new_path()
    text_path(ctx, text, x0, y, tracking=3)
    path = ctx.copy_path()
    ctx.save()
    ctx.translate(4, 5)
    ctx.set_source_rgb(0.1, 0.0, 0.15)
    ctx.fill()
    ctx.restore()
    ctx.new_path()
    ctx.append_path(path)
    g = cairo.LinearGradient(0, y - 44, 0, y)
    g.add_color_stop_rgb(0, 1.0, 0.85, 0.3)
    g.add_color_stop_rgb(1, *HOT_PINK)
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.1, 0.0, 0.15)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.restore()


def neon(ctx, t, frame):
    """A neon 19, buzzing on: two flickers, then lit, flaring on each note of the closed logo."""
    if t < NEON:
        return
    flicker = (0.15, 1, 0.1, 0.1, 1, 0.3, 1)
    i = int((t - NEON) / 0.05)
    level = flicker[i] if i < len(flicker) else 1.0
    level *= 0.92 + 0.08 * math.sin(frame * 2.7)
    level += 0.4 * max((pulse(t, s, 0.3) for s in SPARKLES), default=0)
    ctx.save()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(110)
    ctx.new_path()
    text_path(ctx, '19', 1040, 545, align='center')
    path = ctx.copy_path()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for width, alpha in ((22, 0.12), (10, 0.3), (4, 1.0)):
        ctx.new_path()
        ctx.append_path(path)
        ctx.set_source_rgba(*mix(NEON_CYAN, (1, 1, 1), 0.3 if width < 5 else 0), alpha * min(1.0, level))
        ctx.set_line_width(width)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()
    ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    sky(ctx, t)
    sun(ctx, t)
    mountains(ctx)
    grid(ctx, t)
    lasers(ctx, t)
    wordmark(ctx, t)
    tagline(ctx, t)
    neon(ctx, t, frame)
    vignette(ctx, 0.5)
    grain(ctx, frame, 0.3)
    opening = 1 - ease_out(span(t, 0.0, 0.3))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
