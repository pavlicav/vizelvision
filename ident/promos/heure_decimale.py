"""L'Heure Décimale: Time & Temperature for the République. The Horloge Républicaine's navy
and gold: a tricolour wipe opens on LIBERTÉ · ÉGALITÉ · FRATERNITÉ over a ten-hour dial
turning slowly in the background, and on the open logo the decimal time flips in on the
left (live, to the decimal second, so it ticks as it airs) and the temperature in Celsius
on the right, with its place. A cockade between them. On the closed logo, VizelVision ·
CANAL XIX; the fade.

The numbers are master's live text (OVERLAYS: decimal_time, celsius, place); the picture
leaves their boxes empty. DJ Low Tide: "Vizzle Vision decimal time, and temperature." /
"In Celsius. Naturellement."
"""
import math
from functools import lru_cache

import cairo

from common import (TAU, W, H, back_out, ease_in_out, ease_out, font, glint, grain, pulse, span,  # noqa: F401
                    text_path, to_black, vignette)

ID = 'heure-decimale'
NAME = "L'Heure Décimale"
KIND = 'promo'
ORDER = 29
DESCRIPTION = ('Time & Temperature for the République: navy and gold, a ten-hour dial turning behind, the '
               'decimal time (ticking by the decimal second) and the temperature in Celsius as they are when it '
               'airs. Voiced by DJ Low Tide.')
DURATION = 10.0
STILL_AT = 6.0

# Hit points (the music's too: promos/music.py).
WIPE = (0.0, 0.55)
LABELS = (1.0, 1.25)                         # C, E: the two labels
TIME_IN, TEMP_IN = 1.5, 2.0                  # G, A: the numbers flip in
LOGO = (7.5, 7.75, 8.0, 8.5)                 # the closed logo
FADE = (9.2, 9.55)

NAVY = (0.063, 0.082, 0.18)
NAVY_HI = (0.11, 0.14, 0.29)
GOLD = (0.86, 0.72, 0.42)
CREAM = (0.96, 0.93, 0.85)
ROUGE = (0.86, 0.33, 0.36)
BLEU = (0.10, 0.16, 0.56)
TRI_RED = (0.78, 0.18, 0.20)
SERIF = 'P052'

TIME_BOX = (120, 282, 470, 150)
TEMP_BOX = (690, 282, 470, 150)
PLACE_BOX = (690, 440, 470, 38)
DIAL = (640, 380, 300)

_DIGITS = {'font': SERIF, 'bold': False, 'size': 132, 'min_size': 60, 'color': CREAM,
           'shadow': [0, 4, 0.02, 0.03, 0.08, 0.8]}
OVERLAYS = [
    {'field': 'decimal_time', 'box': list(TIME_BOX), 'from': TIME_IN, 'to': FADE[1], 'style': _DIGITS,
     'enter': {'kind': 'flip', 'seconds': 0.35}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
    {'field': 'celsius', 'box': list(TEMP_BOX), 'from': TEMP_IN, 'to': FADE[1], 'style': _DIGITS,
     'enter': {'kind': 'flip', 'seconds': 0.35}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
    {'field': 'place', 'box': list(PLACE_BOX), 'from': TEMP_IN + 0.3, 'to': FADE[1],
     'style': {'font': SERIF, 'bold': False, 'italic': True, 'size': 28, 'min_size': 14, 'color': GOLD},
     'enter': {'kind': 'fade', 'seconds': 0.4}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
]


def say(ctx, text, x, y, size, colour, alpha=1.0, italic=False, tracking=0.0, align='left'):
    font(ctx, SERIF, size, bold=False, italic=italic)
    ctx.new_path()
    text_path(ctx, text, x, y, tracking, align)
    ctx.set_source_rgba(*colour, alpha)
    ctx.fill()


def tricolour(ctx, y, h=7):
    for k, colour in enumerate((BLEU, (0.97, 0.97, 0.97), TRI_RED)):
        ctx.rectangle(k * W / 3, y, W / 3 + 0.5, h)
        ctx.set_source_rgb(*colour)
        ctx.fill()


@lru_cache(maxsize=1)
def ground():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(*NAVY)
    ctx.paint()
    g = cairo.RadialGradient(640, 360, 40, 640, 360, 760)
    g.add_color_stop_rgba(0, *NAVY_HI, 1)
    g.add_color_stop_rgba(1, *NAVY, 0)
    ctx.set_source(g)
    ctx.paint()
    return surface


def dial(ctx, t):
    """The ten-hour dial, large and faint behind everything, turning a little."""
    cx, cy, r = DIAL
    draw = ease_in_out(span(t, 0.3, 1.4))
    if draw <= 0:
        return
    turn = 0.012 * t
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(turn)
    ctx.set_source_rgba(*GOLD, 0.22)
    for radius, width in ((r, 2.5), (r - 16, 1.0), (r - 44, 1.0)):
        ctx.new_path()
        ctx.arc(0, 0, radius, -TAU / 4, -TAU / 4 + TAU * draw)
        ctx.set_line_width(width)
        ctx.stroke()
    for k in range(100):
        if k / 100 > draw:
            break
        a = -TAU / 4 + TAU * k / 100
        inner = r - (44 if k % 10 == 0 else 30 if k % 5 == 0 else 22)
        ctx.move_to(math.cos(a) * (r - 16), math.sin(a) * (r - 16))
        ctx.line_to(math.cos(a) * inner, math.sin(a) * inner)
        ctx.set_line_width(3.5 if k % 10 == 0 else 1.2)
        ctx.set_source_rgba(*GOLD, 0.26 if k % 10 == 0 else 0.18)
        ctx.stroke()
    font(ctx, SERIF, 46, bold=False)
    for n in range(1, 11):
        p = span(t, 0.6 + 0.07 * n, 0.9 + 0.07 * n)
        if p <= 0:
            continue
        a = -TAU / 4 + TAU * (n % 10) / 10
        ext = ctx.text_extents(str(n))
        ctx.move_to(math.cos(a) * (r - 84) - ext.width / 2 - ext.x_bearing, math.sin(a) * (r - 84) + ext.height / 2)
        ctx.text_path(str(n))
        ctx.set_source_rgba(*CREAM, 0.1 * p)
        ctx.fill()
    ctx.restore()


def cockade(ctx, t):
    p = back_out(span(t, TEMP_IN + 0.1, TEMP_IN + 0.45), 2.4)
    rule = ease_out(span(t, LABELS[0], LABELS[0] + 0.6))
    ctx.rectangle(639.25, 360 - 130 * rule, 1.5, 260 * rule)
    ctx.set_source_rgba(*GOLD, 0.7)
    ctx.fill()
    if p <= 0:
        return
    ctx.save()
    ctx.translate(640, 360)
    ctx.scale(p, p)
    ctx.rotate(0.3 * math.sin(t * 0.7))
    for k in range(20):                                   # a pleated rosette
        a = TAU * k / 20
        ctx.move_to(0, 0)
        ctx.arc(0, 0, 30, a, a + TAU / 40)
        ctx.close_path()
    ctx.set_source_rgb(*BLEU)
    ctx.fill()
    ctx.arc(0, 0, 30, 0, TAU)
    ctx.set_source_rgba(*BLEU, 0.6)
    ctx.fill()
    for r, colour in ((20, (0.97, 0.97, 0.97)), (10, TRI_RED)):
        ctx.arc(0, 0, r, 0, TAU)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    ctx.arc(0, 0, 30, 0, TAU)
    ctx.set_source_rgba(*GOLD, 0.9)
    ctx.set_line_width(2)
    ctx.stroke()
    ctx.restore()
    flare = pulse(t, TEMP_IN + 0.3, 0.5)
    if flare:
        glint(ctx, 672, 330, 18 * flare, 3)


def labels(ctx, t):
    for when, text, cx, gloss in ((LABELS[0], "L'HEURE DÉCIMALE", TIME_BOX[0] + TIME_BOX[2] / 2, 'heures · minutes · secondes'),
                                  (LABELS[1], 'LA TEMPÉRATURE', TEMP_BOX[0] + TEMP_BOX[2] / 2, None)):
        p = ease_out(span(t, when, when + 0.4))
        if p <= 0:
            continue
        say(ctx, text, cx, 262 - 10 * (1 - p), 23, GOLD, p, tracking=7, align='center')
        if gloss:
            say(ctx, gloss, cx, 470, 24, (0.78, 0.78, 0.86), ease_out(span(t, TIME_IN + 0.3, TIME_IN + 0.7)),
                italic=True, align='center')


def header(ctx, t):
    p = ease_out(span(t, WIPE[1], WIPE[1] + 0.6))
    say(ctx, 'LIBERTÉ · ÉGALITÉ · FRATERNITÉ', 640, 92, 22, GOLD, p, tracking=7, align='center')
    ctx.rectangle(640 - 300 * p, 112, 600 * p, 1.2)
    ctx.set_source_rgba(*GOLD, 0.5)
    ctx.fill()


def lockup(ctx, t):
    """VizelVision, a letter at a time across the closed logo, and CANAL XIX."""
    font(ctx, SERIF, 64, bold=False)
    word = 'VizelVision'
    widths = [ctx.text_extents(ch).x_advance for ch in word]
    x = 640 - sum(widths) / 2 - 90
    for i, (ch, wd) in enumerate(zip(word, widths)):
        when = LOGO[0] + i * (LOGO[3] - LOGO[0]) / 10
        s = span(t, when - 0.05, when + 0.18)
        if s > 0:
            ctx.save()
            ctx.translate(x, 616)
            ctx.scale(1, back_out(s, 2.4))
            ctx.move_to(0, 0)
            ctx.text_path(ch)
            ctx.set_source_rgb(*CREAM)
            ctx.fill()
            ctx.restore()
        x += wd
    p = ease_out(span(t, LOGO[3], LOGO[3] + 0.4))
    say(ctx, 'CANAL XIX', x + 26, 612, 26, GOLD, p, tracking=6)
    rule = ease_out(span(t, LOGO[0], LOGO[3]))
    ctx.rectangle(640 - 340 * rule, 545, 680 * rule, 1.2)
    ctx.set_source_rgba(*GOLD, 0.5)
    ctx.fill()
    flare = pulse(t, LOGO[3], 0.6)
    if flare:
        glint(ctx, x + 10, 568, 22 * flare, 5)


def wipe(ctx, t):
    """Bleu, blanc, rouge panels sweep off to the right, uncovering the card."""
    p = ease_in_out(span(t, *WIPE))
    if p >= 1:
        return
    band = W / 3
    for k, colour in enumerate((BLEU, (0.97, 0.97, 0.97), TRI_RED)):
        ctx.rectangle(k * band + (W + 20) * p, 0, band + 1, H)
        ctx.set_source_rgb(*colour)
        ctx.fill()


def draw(ctx, t, frame):
    ctx.set_source_surface(ground(), 0, 0)
    ctx.paint()
    dial(ctx, t)
    tricolour(ctx, 0)
    tricolour(ctx, H - 7)
    header(ctx, t)
    labels(ctx, t)
    cockade(ctx, t)
    lockup(ctx, t)
    vignette(ctx, 0.35)
    grain(ctx, frame, 0.45)
    wipe(ctx, t)
    to_black(ctx, t, *FADE)
