"""Now in HD: VizelVision as a network would have promoted itself in 2006. An aurora in
the Vista colours behind floating bokeh, a light streak, and a piano-black flat panel
flipping round on a wet floor and powering on. The wordmark in glossy lowercase, two-tone,
with a shine across it ("VizelVision."), an orange gel HD pill, a starburst (ALL NEW 720p,
master's own resolution), the tagline
("Now in high definition."). On the closed logo, vector swirls with butterflies grow from
the corners and a lens flare crosses the frame.

No ink outlines here: everything is glass, gel and gloss, as it was then.
"""
import math
import random
from functools import lru_cache

import cairo

from common import (A, TAU, W, H, back_out, chrome, clamp, ease_in, ease_in_out, ease_out, glint, grain, mix,  # noqa: F401
                    pulse, rounded_rect, span, text_path)

ID = 'now-in-hd'
NAME = 'Now in HD'
KIND = 'promo'
ORDER = 9
DESCRIPTION = ('Peak 2006: a Vista-blue aurora, bokeh, a glossy flat panel flipping in on a wet floor, the wordmark in '
               'glossy lowercase with an orange HD pill and a 720p starburst, swirls, butterflies and a lens flare. '
               '"VizelVision. Now in high definition." Voiced by Atlas.')
DURATION = 10.0
STILL_AT = 8.7
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
STREAK = (0.3, 1.0)           # a light streak whooshes across
FLIP = (0.6, 1.8)             # the panel flips round to face us
POWER = 2.0                   # it powers on; the beat drops
WORDMARK = (2.5, 3.0)         # slides in; "VizelVision." at 3.0
SHINE = (3.0, 3.55)
PILL = 4.5                    # the HD pill pops
STARBURST = 5.0               # "Now in high definition." from 5.1
TAGLINE = (5.4, 6.2)
LIFT = 7.0                    # the closed logo: swirls, butterflies, the flare
FLARE = (7.0, 8.3)
BUTTON = 9.0
FADE = (9.2, 9.55)

FLOOR = 470
TV = (360, 262)               # the panel's centre
TEXT_X, BASELINE = 628, 300
AQUA = (0.1, 0.62, 0.95)
GEL_ORANGE = (1.0, 0.5, 0.05)


# ---------------------------------------------------------------- the background: aurora, bokeh, the floor

def background(ctx, t):
    g = cairo.RadialGradient(640, 300, 40, 640, 330, 900)
    g.add_color_stop_rgb(0, 0.06, 0.32, 0.5)
    g.add_color_stop_rgb(0.5, 0.02, 0.12, 0.26)
    g.add_color_stop_rgb(1, 0.0, 0.02, 0.08)
    ctx.set_source(g)
    ctx.paint()
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_SCREEN)
    for y0, amp, height, speed, phase, colour in ((230, 60, 70, 0.35, 0.0, (0.2, 0.9, 0.85)),
                                                  (300, 80, 50, -0.25, 1.7, (0.25, 0.6, 1.0)),
                                                  (180, 50, 40, 0.2, 3.1, (0.5, 1.0, 0.45))):
        xs = range(-40, W + 41, 20)
        mid = [y0 + amp * math.sin(x * 0.004 + t * speed + phase) + 0.4 * amp * math.sin(x * 0.011 - t * speed * 1.7)
               for x in xs]
        half = [height * (0.6 + 0.4 * math.sin(x * 0.007 + t * 0.5 + phase)) for x in xs]
        ctx.move_to(xs[0], mid[0] - half[0])
        for x, m, h in zip(xs, mid, half):
            ctx.line_to(x, m - h)
        for x, m, h in zip(reversed(xs), reversed(mid), reversed(half)):
            ctx.line_to(x, m + h)
        ctx.close_path()
        band = cairo.LinearGradient(0, y0 - amp - height, 0, y0 + amp + height)
        band.add_color_stop_rgba(0, *colour, 0)
        band.add_color_stop_rgba(0.5, *colour, 0.32)
        band.add_color_stop_rgba(1, *colour, 0)
        ctx.set_source(band)
        ctx.fill()
    ctx.restore()
    for x0, y0, r, alpha, drift, tint in orbs():
        x = x0 + 12 * math.sin(t * 0.4 + x0)
        y = (y0 - drift * t) % (H + 2 * r) - r
        g = cairo.RadialGradient(x, y, 0, x, y, r)
        g.add_color_stop_rgba(0, *tint, alpha)
        g.add_color_stop_rgba(0.7, *tint, alpha * 0.6)
        g.add_color_stop_rgba(1, *tint, 0)
        ctx.set_source(g)
        ctx.arc(x, y, r, 0, TAU)
        ctx.fill()
    # The floor: darker, with a glow along the horizon.
    g = cairo.LinearGradient(0, FLOOR, 0, H)
    g.add_color_stop_rgba(0, 0.0, 0.05, 0.12, 0.55)
    g.add_color_stop_rgba(1, 0.0, 0.01, 0.04, 0.9)
    ctx.set_source(g)
    ctx.rectangle(0, FLOOR, W, H - FLOOR)
    ctx.fill()
    g = cairo.LinearGradient(0, 0, W, 0)
    g.add_color_stop_rgba(0, 0.3, 0.8, 1, 0)
    g.add_color_stop_rgba(0.5, 0.5, 0.9, 1, 0.7)
    g.add_color_stop_rgba(1, 0.3, 0.8, 1, 0)
    ctx.set_source(g)
    ctx.rectangle(0, FLOOR - 1, W, 2)
    ctx.fill()


@lru_cache(maxsize=None)
def orbs():
    rand = random.Random(2006)
    return [(rand.uniform(0, W), rand.uniform(0, H), rand.uniform(12, 70), rand.uniform(0.06, 0.22),
             rand.uniform(8, 30), rand.choice(((0.6, 0.95, 1), (0.8, 1, 0.8), (1, 1, 1), (0.5, 0.75, 1))))
            for _ in range(28)]


def streak(ctx, t):
    """A light streak swooping across, its bright head leading a fading tail."""
    p = span(t, *STREAK)
    if not 0 < p < 1:
        return
    pts = [(-100 + 1480 * u, 520 - 330 * u + 140 * math.sin(math.pi * u)) for u in (i / 60 for i in range(61))]
    head = int(ease_in_out(p) * 60)
    tail = max(0, head - 22)
    for width, alpha in ((22, 0.08), (8, 0.3), (2.5, 0.95)):
        for i in range(tail, head):
            ctx.move_to(*pts[i])
            ctx.line_to(*pts[i + 1])
            ctx.set_source_rgba(0.8, 0.97, 1, alpha * (i - tail + 1) / (head - tail + 1))
            ctx.set_line_width(width)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.stroke()
    if head < 60:
        glint(ctx, *pts[head], 26, p * 4, 0.9)


# ---------------------------------------------------------------- the flat panel

def gloss(ctx, x, y, w, h, alpha, shape=None):
    """The 2006 gloss: a white sheen over the top half with a curved lower edge, kept
    inside shape() when given."""
    ctx.save()
    if shape:
        ctx.new_path()
        shape()
        ctx.clip()
    ctx.new_path()
    ctx.move_to(x, y)
    ctx.line_to(x + w, y)
    ctx.line_to(x + w, y + h * 0.42)
    ctx.curve_to(x + w * 0.7, y + h * 0.56, x + w * 0.3, y + h * 0.56, x, y + h * 0.46)
    ctx.close_path()
    g = cairo.LinearGradient(0, y, 0, y + h * 0.55)
    g.add_color_stop_rgba(0, 1, 1, 1, alpha)
    g.add_color_stop_rgba(1, 1, 1, 1, alpha * 0.15)
    ctx.set_source(g)
    ctx.fill()
    ctx.restore()


def screen(ctx, t, x, y, w, h):
    """What the panel shows: dark until it powers on, then Aero blue, an orb and the chrome V."""
    on = span(t, POWER, POWER + 0.25)
    ctx.rectangle(x, y, w, h)
    ctx.set_source_rgb(0.02, 0.03, 0.05)
    ctx.fill()
    if on <= 0:
        return
    ctx.save()
    open_h = h * ease_out(on)
    ctx.rectangle(x, y + h / 2 - max(open_h, 3) / 2, w, max(open_h, 3))
    ctx.clip()
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, 0.0, 0.25, 0.6)
    g.add_color_stop_rgb(0.6, 0.0, 0.5, 0.85)
    g.add_color_stop_rgb(1, 0.3, 0.85, 1.0)
    ctx.set_source(g)
    ctx.paint()
    cx, cy = x + w / 2, y + h / 2
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(t * 0.15)
    for i in range(12):
        a = i * TAU / 12
        ctx.move_to(0, 0)
        ctx.arc(0, 0, w, a, a + TAU / 28)
        ctx.close_path()
    ctx.restore()
    ctx.set_source_rgba(1, 1, 1, 0.07)
    ctx.fill()
    orb = cairo.RadialGradient(cx - 18, cy - 30, 4, cx, cy, 92)
    orb.add_color_stop_rgba(0, 1, 1, 1, 0.95)
    orb.add_color_stop_rgba(0.35, 0.55, 0.9, 1, 0.75)
    orb.add_color_stop_rgba(1, 0.0, 0.3, 0.8, 0.0)
    ctx.set_source(orb)
    ctx.arc(cx, cy, 92, 0, TAU)
    ctx.fill()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(150)
    ext = ctx.text_extents('V')
    ctx.move_to(cx - ext.width / 2 - ext.x_bearing, cy + ext.height / 2)
    ctx.text_path('V')
    ctx.set_source(chrome(cy - ext.height / 2, cy + ext.height / 2, 0.0))
    ctx.fill_preserve()
    ctx.set_source_rgba(1, 1, 1, 0.8)
    ctx.set_line_width(2)
    ctx.stroke()
    flash = 1 - span(t, POWER + 0.2, POWER + 0.7)
    ctx.set_source_rgba(1, 1, 1, 0.8 * flash)
    ctx.paint()
    ctx.restore()


def panel(ctx, t):
    """The flat panel on its stand: piano black, a silver chin, a blue power light."""
    x, y = TV
    w, h = 470, 284
    ctx.move_to(x - 16, y + h / 2 + 24)                            # the stand's neck and foot
    ctx.line_to(x + 16, y + h / 2 + 24)
    ctx.line_to(x + 22, FLOOR - 8)
    ctx.line_to(x - 22, FLOOR - 8)
    ctx.close_path()
    ctx.set_source_rgb(0.08, 0.08, 0.1)
    ctx.fill()
    ctx.save()
    ctx.translate(x, FLOOR - 6)
    ctx.scale(130, 14)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    foot = cairo.LinearGradient(0, FLOOR - 20, 0, FLOOR + 8)
    foot.add_color_stop_rgb(0, 0.3, 0.32, 0.36)
    foot.add_color_stop_rgb(1, 0.02, 0.02, 0.03)
    ctx.set_source(foot)
    ctx.fill()
    rounded_rect(ctx, x - w / 2, y - h / 2, w, h, 14)              # the bezel
    g = cairo.LinearGradient(0, y - h / 2, 0, y + h / 2)
    g.add_color_stop_rgb(0, 0.22, 0.23, 0.27)
    g.add_color_stop_rgb(0.1, 0.07, 0.07, 0.09)
    g.add_color_stop_rgb(1, 0.02, 0.02, 0.03)
    ctx.set_source(g)
    ctx.fill()
    screen(ctx, t, x - w / 2 + 20, y - h / 2 + 18, w - 40, h - 40)
    rounded_rect(ctx, x - w / 2, y + h / 2 - 4, w, 30, 8)          # the silver chin
    g = cairo.LinearGradient(0, y + h / 2, 0, y + h / 2 + 26)
    g.add_color_stop_rgb(0, 0.92, 0.93, 0.95)
    g.add_color_stop_rgb(0.5, 0.7, 0.72, 0.76)
    g.add_color_stop_rgb(1, 0.85, 0.86, 0.9)
    ctx.set_source(g)
    ctx.fill()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(15)
    ctx.set_source_rgb(0.3, 0.32, 0.36)
    text_path(ctx, 'vizelvision', x, y + h / 2 + 16, tracking=1.5, align='center')
    ctx.fill()
    led = span(t, POWER, POWER + 0.1)
    for r, alpha in ((14, 0.25 * led), (4, 0.4 + 0.6 * led)):
        ctx.arc(x + w / 2 - 26, y + h / 2 + 11, r, 0, TAU)
        ctx.set_source_rgba(0.2 + 0.2 * led, 0.5 + 0.4 * led, 1, alpha)
        ctx.fill()
    gloss(ctx, x - w / 2 + 4, y - h / 2 + 4, w - 8, h - 8, 0.2, lambda: rounded_rect(ctx, x - w / 2, y - h / 2, w, h, 14))
    sweep(ctx, t, (POWER + 0.3, POWER + 0.9), lambda: rounded_rect(ctx, x - w / 2, y - h / 2, w, h + 26, 14))


def sweep(ctx, t, when, path):
    """A band of light crossing whatever path() outlines, left to right."""
    p = span(t, *when)
    if not 0 < p < 1:
        return
    ctx.save()
    path()
    ctx.clip()
    x = -300 + (W + 600) * ease_in_out(p)
    g = cairo.LinearGradient(x - 120, 0, x + 120, 0)
    g.add_color_stop_rgba(0, 1, 1, 1, 0)
    g.add_color_stop_rgba(0.5, 1, 1, 1, 0.55)
    g.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_source(g)
    ctx.paint()
    ctx.restore()


def flipped_panel(ctx, t):
    """The panel flipping round from edge-on to face us, overshooting a little."""
    if t < FLIP[0]:
        return
    p = span(t, *FLIP)
    angle = (1 - back_out(p, 1.2)) * math.pi / 2
    k = math.cos(angle)
    x, y = TV
    ctx.save()
    ctx.translate(x, 0)
    ctx.scale(max(abs(k), 0.02), 1)
    ctx.translate(-x, 0)
    panel(ctx, t)
    ctx.restore()
    side = math.sin(angle)
    if side > 0.02:                                                 # its edge, while it turns
        ex = x + 235 * max(abs(k), 0.02)
        ctx.rectangle(ex, y - 142, 18 * side, 284)
        ctx.set_source_rgb(0.5, 0.52, 0.56)
        ctx.fill()


# ---------------------------------------------------------------- the type, the pill, the starburst

@lru_cache(maxsize=None)
def wordmark_size():
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 8, 8))
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(100)
    width = ctx.text_extents('vizelvision').x_advance
    size = 100 * 450 / width
    ctx.set_font_size(size)
    return size, ctx.text_extents('vizel').x_advance, ctx.text_extents('vizelvision').x_advance


def face(top, bottom, colours):
    """A glossy two-band fill: lighter above the hard midline, deeper below, bright at the foot."""
    g = cairo.LinearGradient(0, top, 0, bottom)
    a, b, c, d = colours
    g.add_color_stop_rgb(0, *a)
    g.add_color_stop_rgb(0.5, *b)
    g.add_color_stop_rgb(0.5, *c)
    g.add_color_stop_rgb(1, *d)
    return g


SILVER = ((1, 1, 1), (0.82, 0.86, 0.92), (0.6, 0.66, 0.75), (0.92, 0.95, 1))
GEL = ((0.6, 0.93, 1), (0.15, 0.65, 0.98), (0.0, 0.45, 0.85), (0.35, 0.8, 1))


def wordmark(ctx, t):
    p = span(t, *WORDMARK)
    if p <= 0:
        return
    size, split, total = wordmark_size()
    top = BASELINE - size * 0.72
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)

    def letters(dx):
        ctx.move_to(TEXT_X + dx, BASELINE)
        ctx.text_path('vizel')
        first = ctx.copy_path()
        ctx.new_path()
        ctx.move_to(TEXT_X + split + dx, BASELINE)
        ctx.text_path('vision')
        second = ctx.copy_path()
        ctx.new_path()
        return first, second

    for ghost, alpha in ((0.5, 0.15), (0.25, 0.3), (0.0, 1.0)):     # a motion trail as it slides in
        q = clamp(p - ghost * 0.4 * (1 - p))
        dx = 140 * (1 - ease_out(q))
        a = alpha * ease_out(q) if ghost else ease_out(q)
        if ghost and p >= 1:
            continue
        first, second = letters(dx)
        ctx.push_group()
        for path, colours in ((first, SILVER), (second, GEL)):
            ctx.new_path()
            ctx.append_path(path)
            ctx.save()
            ctx.translate(2, 5)
            ctx.set_source_rgba(0, 0, 0, 0.4)
            ctx.fill()
            ctx.restore()
            ctx.new_path()
            ctx.append_path(path)
            ctx.set_source(face(top, BASELINE, colours))
            ctx.fill_preserve()
            ctx.set_source_rgba(1, 1, 1, 0.6)
            ctx.set_line_width(1.2)
            ctx.stroke()
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(a)
    first, second = letters(0)

    def outline():
        ctx.append_path(first)
        ctx.append_path(second)
    sweep(ctx, t, SHINE, outline)
    sweep(ctx, t, (LIFT + 0.2, LIFT + 0.8), outline)


def pill(ctx, t):
    p = span(t, PILL, PILL + 0.45)
    if p <= 0:
        return
    size, _, total = wordmark_size()
    x, y, w, h = TEXT_X + total + 14, BASELINE - size * 0.78, 98, 54
    ctx.save()
    ctx.translate(x + w / 2, y + h / 2)
    k = back_out(p, 2.2)
    ctx.scale(k, k)
    ctx.translate(-w / 2, -h / 2)
    rounded_rect(ctx, 3, 5, w, h, h / 2)
    ctx.set_source_rgba(0, 0, 0, 0.4)
    ctx.fill()
    rounded_rect(ctx, 0, 0, w, h, h / 2)
    ctx.set_source(face(0, h, ((1, 0.85, 0.4), (1, 0.6, 0.12), (0.95, 0.42, 0.0), (1, 0.7, 0.3))))
    ctx.fill_preserve()
    ctx.set_source_rgb(1, 1, 1)
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(36)
    ext = ctx.text_extents('HD')
    ctx.move_to(w / 2 - ext.width / 2 - ext.x_bearing, h / 2 + ext.height / 2)
    ctx.text_path('HD')
    ctx.set_source_rgba(0.6, 0.2, 0, 0.5)
    ctx.save()
    ctx.translate(0, 2)
    ctx.fill_preserve()
    ctx.restore()
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    gloss(ctx, 4, 3, w - 8, h - 6, 0.5, lambda: rounded_rect(ctx, 3, 3, w - 6, h - 6, (h - 6) / 2))
    ctx.restore()
    for at in (PILL, BUTTON):
        q = span(t, at + 0.1, at + 0.7)
        if 0 < q < 1:
            glint(ctx, x + w - 10, y + 6, 22 * math.sin(math.pi * q), q * 3, math.sin(math.pi * q))


def starburst(ctx, t):
    p = span(t, STARBURST, STARBURST + 0.5)
    if p <= 0:
        return
    cx, cy, outer, inner, points = 600, 148, 86, 72, 20
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(-0.22 + 0.05 * math.sin(t * 2.2) + 0.15 * pulse(t, BUTTON, 0.5))
    k = back_out(p, 2.4)
    ctx.scale(k, k)
    def star_path():
        for i in range(points * 2):
            a = i * math.pi / points
            r = outer if i % 2 == 0 else inner
            ctx.line_to(math.cos(a) * r, math.sin(a) * r)
        ctx.close_path()

    for shadow in (True, False):
        ctx.save()
        if shadow:
            ctx.translate(4, 7)
        ctx.new_path()
        star_path()
        if shadow:
            ctx.set_source_rgba(0, 0, 0, 0.4)
            ctx.fill()
        else:
            g = cairo.RadialGradient(-20, -30, 5, 0, 0, outer)
            g.add_color_stop_rgb(0, 1, 1, 0.6)
            g.add_color_stop_rgb(1, 0.55, 0.88, 0.1)
            ctx.set_source(g)
            ctx.fill_preserve()
            ctx.set_source_rgb(1, 1, 1)
            ctx.set_line_width(4)
            ctx.stroke()
        ctx.restore()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    for text, size, y in (('ALL NEW', 19, -18), ('720p', 40, 24)):
        ctx.set_font_size(size)
        ctx.new_path()
        text_path(ctx, text, 0, y, tracking=1 if size < 30 else 0, align='center')
        ctx.set_source_rgb(1, 1, 1)
        ctx.set_line_width(5)
        ctx.stroke_preserve()
        ctx.set_source_rgb(0.82, 0.08, 0.12)
        ctx.fill()
    gloss(ctx, -outer, -outer, outer * 2, outer * 2, 0.28, star_path)
    ctx.restore()


def tagline(ctx, t):
    p = span(t, *TAGLINE)
    if p <= 0:
        return
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(27)
    text = 'now in high definition'
    shown = text[:max(1, int(len(text) * ease_out(p)))]
    ctx.new_path()
    text_path(ctx, shown, TEXT_X + 6, BASELINE + 58, tracking=4)
    ctx.set_source_rgba(0.8, 0.92, 1, 0.9)
    ctx.fill()
    ctx.move_to(TEXT_X + 6, BASELINE + 22)                          # the swoosh under the wordmark
    reach = 520 * ease_out(p)
    ctx.curve_to(TEXT_X + reach * 0.3, BASELINE + 34, TEXT_X + reach * 0.7, BASELINE + 30, TEXT_X + reach, BASELINE + 14)
    ctx.curve_to(TEXT_X + reach * 0.7, BASELINE + 24, TEXT_X + reach * 0.3, BASELINE + 26, TEXT_X + 6, BASELINE + 22)
    ctx.close_path()
    g = cairo.LinearGradient(TEXT_X, 0, TEXT_X + 520, 0)
    g.add_color_stop_rgba(0, 0.3, 0.8, 1, 0)
    g.add_color_stop_rgba(0.6, 0.4, 0.9, 1, 0.9)
    g.add_color_stop_rgba(1, 0.9, 1, 1, 1)
    ctx.set_source(g)
    ctx.fill()


# ---------------------------------------------------------------- the lift: swirls, butterflies, the flare

def curl(x, y, angle, length, turn, n=80):
    """A flourish: a stem that curls tighter and tighter at its end."""
    pts = [(x, y)]
    step = length / n
    for i in range(n):
        f = i / n
        angle += turn * (0.15 + 5.5 * f ** 2.4) / n * 5
        s = step * (1 - 0.7 * f)
        x += math.cos(angle) * s
        y += math.sin(angle) * s
        pts.append((x, y))
    return pts


@lru_cache(maxsize=None)
def swirls():
    """[(points, width, delay)]: the corners' flourishes, each with two branches."""
    out = []
    for x, y, angle, length, turn in ((-20, 712, -0.62, 760, 1.0), (1300, 8, math.pi - 0.5, 640, 1.0)):
        stem = curl(x, y, angle, length, turn)
        out.append((stem, 6.5, 0.0))
        for at, scale, sign in ((0.25, 0.5, -1), (0.5, 0.38, 1), (0.7, 0.24, -1)):
            i = int(len(stem) * at)
            (x0, y0), (x1, y1) = stem[i], stem[i + 1]
            heading = math.atan2(y1 - y0, x1 - x0)
            out.append((curl(x0, y0, heading + sign * 0.5, length * scale, -sign * turn * 1.2), 4.0, at * 0.6))
    return out


def flourishes(ctx, t):
    p0 = span(t, LIFT, LIFT + 1.3)
    if p0 <= 0:
        return
    for pts, width, delay in swirls():
        p = clamp((p0 - delay) / (1 - delay))
        n = int(len(pts) * ease_out(p))
        if n < 2:
            continue
        for w, alpha, colour in ((width + 8, 0.12, (0.4, 0.9, 1)), (width, 0.8, (1, 1, 1))):
            for i in range(n - 1):
                ctx.move_to(*pts[i])
                ctx.line_to(*pts[i + 1])
                ctx.set_line_width(w * (1 - 0.65 * i / len(pts)))
                ctx.set_line_cap(cairo.LINE_CAP_ROUND)
                ctx.set_source_rgba(*colour, alpha)
                ctx.stroke()
        tip = pts[n - 1]
        if p >= 1:
            ctx.arc(*tip, width * 1.4, 0, TAU)
            ctx.set_source_rgba(1, 1, 1, 0.9)
            ctx.fill()
        for k in range(3, n - 8, 14):                                # leaves along the way
            (ax, ay), (bx, by) = pts[k], pts[k + 1]
            heading = math.atan2(by - ay, bx - ax) + (0.9 if k % 28 else -0.9)
            ctx.save()
            ctx.translate(ax, ay)
            ctx.rotate(heading)
            grow = clamp((n - k) / 10)
            ctx.scale(grow, grow)
            ctx.move_to(0, 0)
            ctx.curve_to(8, -9, 22, -7, 28, 0)
            ctx.curve_to(22, 7, 8, 9, 0, 0)
            ctx.set_source_rgba(0.75, 1, 0.55, 0.75)
            ctx.fill()
            ctx.restore()


def butterfly(ctx, x, y, size, flap, colour, heading):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(heading)
    for side in (-1, 1):
        ctx.save()
        ctx.scale(side * (0.25 + 0.75 * abs(math.cos(flap))), 1)
        for (wx, wy, rx, ry, rot) in ((size * 0.55, -size * 0.4, size * 0.62, size * 0.45, -0.5),
                                      (size * 0.42, size * 0.35, size * 0.42, size * 0.3, 0.6)):
            ctx.save()
            ctx.translate(wx, wy)
            ctx.rotate(rot)
            ctx.scale(rx, ry)
            ctx.arc(0, 0, 1, 0, TAU)
            ctx.restore()
            g = cairo.RadialGradient(wx, wy, 0, wx, wy, rx)
            g.add_color_stop_rgba(0, 1, 1, 1, 0.95)
            g.add_color_stop_rgba(1, *colour, 0.85)
            ctx.set_source(g)
            ctx.fill()
        ctx.restore()
    ctx.rectangle(-1.5, -size * 0.6, 3, size * 1.1)
    ctx.set_source_rgb(0.05, 0.1, 0.2)
    ctx.fill()
    ctx.restore()


def butterflies(ctx, t):
    for k, (x0, y0, x1, y1, colour, at) in enumerate(((150, 640, 520, 470, (0.3, 0.85, 1.0), 7.5),
                                                      (1150, 110, 900, 230, (0.6, 1.0, 0.3), 7.8))):
        p = span(t, at, at + 1.6)
        if p <= 0:
            continue
        u = ease_out(p)
        x = x0 + (x1 - x0) * u + 30 * math.sin(t * 3 + k)
        y = y0 + (y1 - y0) * u + 18 * math.sin(t * 4.3 + k)
        butterfly(ctx, x, y, 22, t * 22 + k, colour, 0.3 * math.sin(t * 2 + k))


def flare(ctx, t):
    """A lens flare crossing the frame: the source, its anamorphic streak, the ghosts."""
    p = span(t, *FLARE)
    if not 0 < p < 1:
        return
    strength = math.sin(math.pi * p)
    sx, sy = -120 + 1520 * ease_in_out(p), 120 + 60 * p
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    g = cairo.RadialGradient(sx, sy, 0, sx, sy, 160)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.9 * strength)
    g.add_color_stop_rgba(0.2, 0.7, 0.9, 1, 0.35 * strength)
    g.add_color_stop_rgba(1, 0.3, 0.6, 1, 0)
    ctx.set_source(g)
    ctx.arc(sx, sy, 160, 0, TAU)
    ctx.fill()
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(700, 5)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    g = cairo.LinearGradient(sx - 700, 0, sx + 700, 0)
    g.add_color_stop_rgba(0, 0.4, 0.7, 1, 0)
    g.add_color_stop_rgba(0.5, 0.8, 0.95, 1, 0.6 * strength)
    g.add_color_stop_rgba(1, 0.4, 0.7, 1, 0)
    ctx.set_source(g)
    ctx.fill()
    cx, cy = W / 2, H / 2
    for k, r, colour in ((0.5, 30, (0.4, 1, 0.6)), (0.9, 60, (0.3, 0.6, 1)), (1.3, 22, (1, 0.6, 0.3)),
                         (1.7, 90, (0.5, 0.4, 1)), (2.1, 40, (0.3, 1, 0.9))):
        gx, gy = sx + (cx - sx) * k, sy + (cy - sy) * k
        ctx.new_path()
        for i in range(6):
            a = i * TAU / 6 + 0.3
            ctx.line_to(gx + math.cos(a) * r, gy + math.sin(a) * r)
        ctx.close_path()
        ctx.set_source_rgba(*colour, 0.12 * strength)
        ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the frame

def objects(ctx, t):
    """What stands on (or floats over) the wet floor, and so is reflected in it."""
    flipped_panel(ctx, t)
    wordmark(ctx, t)
    pill(ctx, t)


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    background(ctx, t)
    ctx.push_group()
    objects(ctx, t)
    things = ctx.pop_group()
    ctx.save()                                                       # the wet floor's reflection
    ctx.rectangle(0, FLOOR, W, H - FLOOR)
    ctx.clip()
    ctx.translate(0, 2 * FLOOR)
    ctx.scale(1, -1)
    ctx.set_source(things)
    fade = cairo.LinearGradient(0, FLOOR, 0, FLOOR - 170)
    fade.add_color_stop_rgba(0, 0, 0, 0, 0.4)
    fade.add_color_stop_rgba(1, 0, 0, 0, 0)
    ctx.mask(fade)
    ctx.restore()
    ctx.set_source(things)
    ctx.paint()
    tagline(ctx, t)
    starburst(ctx, t)
    streak(ctx, t)
    flourishes(ctx, t)
    butterflies(ctx, t)
    flare(ctx, t)
    grain(ctx, frame, 0.2)
    opening = 1 - ease_out(span(t, 0.0, 0.3))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
