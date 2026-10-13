"""VizelVision '76: the station in its Bicentennial year, as a 1976 station break looked.
Night over the Mall: the Washington Monument and the Capitol's dome against a deep blue
sky. The picture opens out of slit-scan streaks; on the open logo four fireworks burst
over the Monument, red, white, blue and gold; a ribbon of red, white and blue stripes
sweeps across, Avant Garde style, and the wordmark rides in on it with the triple outline
of the day, a star turning before it. 1776 · 1976 · CHANNEL 19. On the closed logo the
finale: every firework at once, and the star spins.

Saturn, the period announcer: "Happy birthday, America." / "From Vizzle Vision nineteen."
"""
import math
import random
from functools import lru_cache

import cairo

from common import (TAU, W, H, WHITE, back_out, clamp, ease_in, ease_in_out, ease_out, glint, grain, mix,  # noqa: F401
                    pulse, span, text_path, vignette)

ID = 'seventy-six'
NAME = "VizelVision '76"
KIND = 'ident'
ORDER = 12
DESCRIPTION = ("1976, the Bicentennial: fireworks over the Monument and the Capitol on the logo, a red, white and "
               'blue ribbon sweeping in with the wordmark in Avant Garde, 1776 · 1976. Fife and drum into seventies '
               'brass and strings. Saturn.')
DURATION = 10.0
STILL_AT = 8.4
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
STREAKS = (0.0, 0.9)                           # slit-scan streaks resolve into the night sky
BURSTS = (1.0, 1.25, 1.5, 2.0)                 # the open logo: a firework each
RIBBON = (2.4, 3.2)                            # the stripes sweep in
WORDMARK = (2.9, 3.5)
STAR_IN = 3.3
DATES = (4.4, 4.9)                             # 1776 · 1976
FINALE = (7.0, 7.25, 7.5, 8.0)                 # the closed logo: everything at once
FADE = (9.25, 9.6)

RED = (0.86, 0.12, 0.16)
BLUE = (0.1, 0.22, 0.6)
CREAM = (1.0, 0.96, 0.86)
GOLD = (1.0, 0.78, 0.25)
GROUND = 610


# ---------------------------------------------------------------- the Mall at night

def sky(ctx, t):
    g = cairo.LinearGradient(0, 0, 0, GROUND)
    g.add_color_stop_rgb(0, 0.02, 0.03, 0.12)
    g.add_color_stop_rgb(0.7, 0.06, 0.1, 0.3)
    g.add_color_stop_rgb(1, 0.18, 0.18, 0.36)
    ctx.set_source(g)
    ctx.paint()
    glow = max((pulse(t, b, 0.8) for b in BURSTS + FINALE), default=0.0)
    if glow > 0:
        g = cairo.RadialGradient(640, 200, 50, 640, 200, 800)
        g.add_color_stop_rgba(0, 1, 0.85, 0.7, 0.18 * glow)
        g.add_color_stop_rgba(1, 1, 0.85, 0.7, 0)
        ctx.set_source(g)
        ctx.paint()


def skyline(ctx, t):
    """The Monument in the middle distance, the Capitol's dome beyond it, trees, the Mall."""
    glow = max((pulse(t, b, 0.8) for b in BURSTS + FINALE), default=0.0)
    lit = mix((0.1, 0.1, 0.2), (0.45, 0.4, 0.45), 0.5 * glow)
    ctx.move_to(940, GROUND)                                       # the Capitol: wings, drum, dome, lantern
    for x, y in ((940, 520), (1010, 520), (1010, 500), (1060, 500), (1060, 470), (1075, 470), (1080, 430)):
        ctx.line_to(x, y)
    ctx.curve_to(1082, 392, 1100, 372, 1118, 368)
    ctx.line_to(1118, 352)
    ctx.line_to(1124, 340)
    ctx.line_to(1130, 352)
    ctx.line_to(1130, 368)
    ctx.curve_to(1148, 372, 1166, 392, 1168, 430)
    for x, y in ((1173, 470), (1188, 470), (1188, 500), (1238, 500), (1238, 520), (1300, 520), (1300, GROUND)):
        ctx.line_to(x, y)
    ctx.close_path()
    ctx.set_source_rgb(*lit)
    ctx.fill()
    ctx.set_source_rgba(1, 0.9, 0.6, 0.5 + 0.3 * glow)               # its lit colonnade
    for k in range(9):
        ctx.rectangle(1086 + k * 9, 440, 3, 24)
    ctx.fill()
    base, top = GROUND - 6, 120                                     # the Monument: a tapering shaft, its pyramid
    ctx.move_to(612, base)
    ctx.line_to(624, top + 22)
    ctx.line_to(640, top)
    ctx.line_to(656, top + 22)
    ctx.line_to(668, base)
    ctx.close_path()
    g = cairo.LinearGradient(612, 0, 668, 0)
    g.add_color_stop_rgb(0, *mix((0.55, 0.52, 0.55), (1, 0.95, 0.85), glow))
    g.add_color_stop_rgb(0.5, *mix((0.8, 0.78, 0.78), (1, 1, 0.95), glow))
    g.add_color_stop_rgb(1, *mix((0.35, 0.33, 0.4), (0.8, 0.7, 0.7), glow))
    ctx.set_source(g)
    ctx.fill()
    for x in (626, 650):                                            # its red aircraft lights, blinking
        ctx.arc(x, top + 26, 3, 0, TAU)
        ctx.set_source_rgba(1, 0.1, 0.1, 0.4 + 0.6 * (math.sin(t * 5) > 0))
        ctx.fill()
    rand = random.Random(1976)
    ctx.move_to(0, GROUND)                                          # the trees along the Mall
    x = 0
    while x < W:
        ctx.line_to(x, GROUND - rand.uniform(18, 46))
        x += rand.uniform(18, 40)
    ctx.line_to(W, GROUND)
    ctx.close_path()
    ctx.set_source_rgb(0.03, 0.05, 0.08)
    ctx.fill()
    ctx.rectangle(0, GROUND, W, H - GROUND)
    g = cairo.LinearGradient(0, GROUND, 0, H)
    g.add_color_stop_rgb(0, 0.05, 0.06, 0.1)
    g.add_color_stop_rgb(1, 0.01, 0.01, 0.03)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(0, GROUND + 26, W, 40)                            # the Reflecting Pool, catching the sky
    ctx.set_source_rgba(0.3, 0.35, 0.6, 0.25 + 0.4 * glow)
    ctx.fill()


# ---------------------------------------------------------------- fireworks

@lru_cache(maxsize=None)
def shells(k):
    rand = random.Random(76 + k)
    return [(rand.uniform(0, TAU), rand.uniform(0.55, 1.0), rand.random()) for _ in range(60)]


def firework(ctx, t, start, cx, cy, colour, size, k):
    p = span(t, start, start + 1.6)
    if not 0 < p < 1:
        return
    if p < 0.12:                                                    # the shell going up
        ctx.arc(cx, cy + 260 * (1 - p / 0.12), 3, 0, TAU)
        ctx.set_source_rgba(1, 0.9, 0.7, 0.9)
        ctx.fill()
        return
    q = (p - 0.12) / 0.88
    radius = size * ease_out(q, 2.5)
    fade = (1 - q) ** 1.3
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for angle, speed, twinkle in shells(k):
        for trail in range(3):
            r = radius * speed * (1 - 0.07 * trail)
            x, y = cx + math.cos(angle) * r, cy + math.sin(angle) * r + 90 * q * q
            a = fade * (1 - 0.35 * trail) * (0.6 + 0.4 * math.sin(t * 30 + twinkle * 9))
            ctx.arc(x, y, 2.6 - 0.6 * trail, 0, TAU)
            ctx.set_source_rgba(*colour, max(0.0, a))
            ctx.fill()
    if q < 0.15:
        g = cairo.RadialGradient(cx, cy, 0, cx, cy, size * 0.9)
        g.add_color_stop_rgba(0, *colour, 0.5 * (1 - q / 0.15))
        g.add_color_stop_rgba(1, *colour, 0)
        ctx.set_source(g)
        ctx.paint()
    ctx.restore()


def fireworks(ctx, t):
    colours = (RED, (1, 1, 1), (0.35, 0.55, 1.0), GOLD)
    for k, (when, (x, y)) in enumerate(zip(BURSTS, ((470, 170), (800, 130), (640, 210), (960, 190)))):
        firework(ctx, t, when, x, y, colours[k], 150, k)
    for k, (when, (x, y)) in enumerate(zip(FINALE, ((320, 150), (960, 120), (520, 90), (760, 160)))):
        firework(ctx, t, when, x, y, colours[(k + 1) % 4], 190, 10 + k)
        if k == 3:
            firework(ctx, t, when + 0.08, 180, 230, RED, 140, 20)
            firework(ctx, t, when + 0.16, 1100, 230, (0.35, 0.55, 1.0), 140, 21)


# ---------------------------------------------------------------- slit-scan, the ribbon, the type

def streaks(ctx, t):
    """The slit-scan opening: coloured light stretched sideways, closing up to nothing."""
    p = span(t, *STREAKS)
    if p >= 1:
        return
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    rand = random.Random(7)
    for k in range(40):
        y = rand.uniform(40, H - 40)
        colour = (RED, (1, 1, 1), (0.35, 0.55, 1.0), GOLD)[k % 4]
        length = rand.uniform(300, 1400) * (1 - ease_in(p, 2))
        x = rand.uniform(-200, W) + 600 * p * (1 if k % 2 else -1)
        g = cairo.LinearGradient(x, 0, x + length, 0)
        g.add_color_stop_rgba(0, *colour, 0)
        g.add_color_stop_rgba(0.5, *colour, 0.5 * (1 - p))
        g.add_color_stop_rgba(1, *colour, 0)
        ctx.set_source(g)
        ctx.rectangle(x, y, length, rand.uniform(2, 7))
        ctx.fill()
    ctx.restore()


def ribbon(ctx, t):
    """Three stripes, red, cream and blue, sweeping in a long curve under the wordmark."""
    p = ease_in_out(span(t, *RIBBON))
    if p <= 0:
        return
    def centre(u):
        return -60 + 1400 * u, 470 - 70 * math.sin(math.pi * u * 0.9) + 40 * u
    n = int(80 * p)
    if n < 2:
        return
    for k, colour in enumerate((RED, CREAM, BLUE)):
        offset = (k - 1) * 22
        pts = [centre(i / 80) for i in range(n + 1)]
        ctx.move_to(pts[0][0], pts[0][1] + offset)
        for x, y in pts[1:]:
            ctx.line_to(x, y + offset)
        ctx.set_source_rgb(*colour)
        ctx.set_line_width(20)
        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.stroke()


def outlined(ctx, path, colours, widths):
    """The seventies' triple outline: strokes from widest to narrowest, then the face."""
    for colour, width in zip(colours[:-1], widths):
        ctx.new_path()
        ctx.append_path(path)
        ctx.set_source_rgb(*colour)
        ctx.set_line_width(width)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()
    ctx.new_path()
    ctx.append_path(path)
    ctx.set_source_rgb(*colours[-1])
    ctx.fill()


def five_point(ctx, r, inner=0.42):
    for i in range(10):
        a = -TAU / 4 + i * TAU / 10
        rr = r if i % 2 == 0 else r * inner
        ctx.line_to(math.cos(a) * rr, math.sin(a) * rr)
    ctx.close_path()


def wordmark(ctx, t):
    p = span(t, *WORDMARK)
    if p <= 0:
        return
    ctx.save()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(122)
    x = W / 2 + 50 + 900 * (1 - ease_out(p))
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', x, 405, tracking=-2, align='center')
    path = ctx.copy_path()
    outlined(ctx, path, (BLUE, RED, CREAM, BLUE), (26, 17, 8))
    ctx.restore()
    q = span(t, STAR_IN, STAR_IN + 0.5)                             # the star, turning beside it
    if q > 0:
        spin = 0.6 * t + TAU * ease_in_out(span(t, FINALE[0], FINALE[0] + 1.0))
        ctx.save()
        ctx.translate(178, 352)
        ctx.rotate(spin * 0.2)
        k = back_out(q, 2.2) * (1 + 0.08 * pulse(t, FINALE[0], 0.5))
        ctx.scale(k, k)
        ctx.new_path()
        five_point(ctx, 62)
        path = ctx.copy_path()
        outlined(ctx, path, (BLUE, RED, CREAM, BLUE), (22, 14, 6))
        ctx.restore()


def dates(ctx, t):
    p = span(t, *DATES)
    if p <= 0:
        return
    ctx.save()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(36)
    ctx.new_path()
    text_path(ctx, '1776 · 1976  ·  CHANNEL 19', W / 2, 560, tracking=8, align='center')
    path = ctx.copy_path()
    ctx.push_group()
    outlined(ctx, path, (BLUE, CREAM), (9,))
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(ease_out(p))
    ctx.restore()


def film(ctx, t, frame):
    """Seventies videotape: a slight warmth, soft lines, the odd dropout."""
    ctx.set_source_rgba(1, 0.75, 0.4, 0.05)
    ctx.paint()
    ctx.set_source_rgba(0, 0, 0, 0.1)
    for y in range(0, H, 3):
        ctx.rectangle(0, y, W, 1)
    ctx.fill()
    rand = random.Random(frame // 3)
    if rand.random() < 0.08:
        y = rand.uniform(0, H)
        ctx.rectangle(rand.uniform(0, W * 0.6), y, rand.uniform(80, 400), 2)
        ctx.set_source_rgba(1, 1, 1, 0.35)
        ctx.fill()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    sky(ctx, t)
    fireworks(ctx, t)
    skyline(ctx, t)
    ribbon(ctx, t)
    wordmark(ctx, t)
    dates(ctx, t)
    streaks(ctx, t)
    film(ctx, t, frame)
    vignette(ctx, 0.55)
    grain(ctx, frame, 0.5)
    opening = 1 - ease_out(span(t, 0.0, 0.5))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening * 0.85)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
