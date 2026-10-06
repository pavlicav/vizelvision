"""The legal ID: "This is VizelVision 19, Cable 70." The emblem and a chrome 19 over navy
and slow rays, CABLE 70 in its red box, and along the bottom, plainly, as a legal ID has
them, the call letters and city of license. Five seconds.
"""
import math

import cairo

from common import (A, INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, chrome, clamp, ease_in, ease_in_out,  # noqa: F401
                    ease_out, elastic_out, flash, font, glint, grain, inked, mix, pulse, rounded_rect, scanlines,
                    span, star, text_path, to_black, vignette)

ID = 'legal'
NAME = 'Legal ID'
KIND = 'ident'
ORDER = 4
DESCRIPTION = ('"This is VizelVision 19, Cable 70." The emblem, a chrome 19 and CABLE 70, with the call letters '
               'and city of license, WVHZ-DB Washington, along the bottom as a legal ID has them. Voiced by Jupiter.')
DURATION = 5.0
STILL_AT = 4.1
OVERLAYS = []

NAVY = ((0.02, 0.03, 0.12), (0.05, 0.10, 0.32))
GOLD = (1.0, 0.80, 0.30)
GOLD_DEEP = (0.62, 0.42, 0.08)
RED = (0.86, 0.10, 0.16)
MARBLE = (0.06, 0.06, 0.07)

# Hit points (the music's too).
EMBLEM_IN = (0.05, 0.55)
NINETEEN = 0.35
CABLE = 1.75            # "Cable" in the line
LINE_IN = (2.9, 3.4)     # the call letters fade up on a quiet chord
FADE = (4.55, 4.8)
CALL = 'WVHZ-DB'
CITY = 'WASHINGTON'


def background(ctx, t):
    g = cairo.LinearGradient(0, 0, 0, H)
    g.add_color_stop_rgb(0, *NAVY[1])
    g.add_color_stop_rgb(1, *NAVY[0])
    ctx.set_source(g)
    ctx.paint()
    # Slow gold rays from behind the emblem.
    cx, cy = 400, 250
    ctx.save()
    for i in range(18):
        a = 0.08 * t + i * TAU / 18
        ctx.move_to(cx, cy)
        ctx.line_to(cx + math.cos(a) * 1600, cy + math.sin(a) * 1600)
        ctx.line_to(cx + math.cos(a + TAU / 36) * 1600, cy + math.sin(a + TAU / 36) * 1600)
        ctx.close_path()
    ctx.set_source_rgba(*GOLD, 0.06)
    ctx.fill()
    glow = cairo.RadialGradient(cx, cy, 0, cx, cy, 420)
    glow.add_color_stop_rgba(0, 0.6, 0.75, 1.0, 0.25)
    glow.add_color_stop_rgba(1, 0.6, 0.75, 1.0, 0)
    ctx.set_source(glow)
    ctx.paint()
    ctx.restore()
    for i in range(40):       # stars, twinkling
        x, y = (i * 389) % W, (i * 211) % 470
        a = 0.35 + 0.35 * math.sin(t * 3 + i)
        ctx.set_source_rgba(1, 1, 1, a)
        ctx.arc(x, y, 1.4 + (i % 3) * 0.6, 0, TAU)
        ctx.fill()


def emblem(ctx, t):
    p = span(t, *EMBLEM_IN)
    if p <= 0:
        return
    scale = 0.78 * (0.2 + 0.8 * elastic_out(p))
    ctx.save()
    ctx.translate(400, 255 + math.sin(t * 2.2) * 4)
    ctx.rotate((1 - ease_out(p)) * -0.6)
    ctx.scale(scale, scale)
    A.draw_tv(ctx, t, 1, 0.0)
    ctx.restore()


def nineteen(ctx, t):
    p = span(t, NINETEEN, NINETEEN + 0.25)
    if p <= 0:
        return
    zoom = 1 + 1.6 * (1 - ease_in(p, 2))
    impact = pulse(t, NINETEEN + 0.25, 0.2)
    ctx.save()
    ctx.translate(770, 300)
    ctx.scale(zoom * (1 + 0.1 * impact), zoom * (1 - 0.14 * impact))
    font(ctx, 'URW Gothic', 300)
    ext = ctx.text_extents('19')
    ctx.move_to(-ext.width / 2 - ext.x_bearing, 105)
    ctx.text_path('19')
    if p < 1:
        ctx.push_group()
    inked(ctx, chrome(105 - ext.height, 105, 0.4), 6, (10, 10), fatten=8)
    if p < 1:
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_out(clamp(p * 2.5)))
    ctx.restore()
    # A glint on the chrome as it lands.
    life = span(t, NINETEEN + 0.3, NINETEEN + 0.8)
    if 0 < life < 1:
        glint(ctx, 850, 210, 34 * math.sin(life * math.pi), life * 2)


def cable(ctx, t):
    p = span(t, CABLE, CABLE + 0.35)
    if p <= 0:
        return
    x = 1095 + (1 - back_out(p, 1.8)) * 420
    ctx.save()
    ctx.translate(x, 200)
    ctx.rotate(-0.06)
    rounded_rect(ctx, -110, -46, 220, 92, 14)
    inked(ctx, RED, 6, (8, 8))
    ctx.set_source_rgb(*WHITE)
    font(ctx, 'Nimbus Sans', 26, italic=True)
    text_path(ctx, 'CABLE', 0, -8, tracking=6, align='center')
    ctx.fill()
    font(ctx, 'URW Gothic', 50)
    text_path(ctx, '70', 0, 38, tracking=2, align='center')
    ctx.fill()
    ctx.restore()


def wordmark(ctx, t):
    p = span(t, 0.9, 1.4)
    if p <= 0:
        return
    font(ctx, 'URW Gothic', 64)
    ctx.save()
    ctx.translate(0, (1 - ease_out(p)) * 30)
    widths = [ctx.text_extents(ch).x_advance + 4 for ch in 'VIZELVISION']
    x = 770 - (sum(widths) - 4) / 2
    for i, (ch, wd) in enumerate(zip('VIZELVISION', widths)):
        ctx.move_to(x, 470)
        ctx.text_path(ch)
        x += wd
    inked(ctx, chrome(420, 470, 0.4) if p >= 1 else (0.9, 0.92, 1.0), 4, (5, 5))
    ctx.restore()


def legal_line(ctx, t):
    """The call letters and city of license, as a legal ID has them: small, plain, letter-
    spaced white caps under a hairline rule, fading up and staying put."""
    p = ease_in_out(span(t, *LINE_IN))
    if p <= 0:
        return
    y = 628
    ctx.save()
    ctx.translate(0, 8 * (1 - p))
    rule = 300 * ease_out(span(t, LINE_IN[0], LINE_IN[0] + 0.5))
    ctx.rectangle(W / 2 - rule, y - 40, 2 * rule, 1.5)
    ctx.set_source_rgba(1, 1, 1, 0.55 * p)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 30, bold=False)
    ctx.set_source_rgba(1, 1, 1, 0.92 * p)
    text_path(ctx, CALL + '   ' + CITY, W / 2, y, tracking=9, align='center')
    ctx.fill()
    ctx.restore()


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.save()
    background(ctx, t)
    emblem(ctx, t)
    nineteen(ctx, t)
    cable(ctx, t)
    wordmark(ctx, t)
    legal_line(ctx, t)
    ctx.restore()
    flash(ctx, 0.9 * (1 - span(t, 0, 0.25)))
    scanlines(ctx, 0.1)
    vignette(ctx, 0.5)
    grain(ctx, frame, 0.5)
    to_black(ctx, t, *FADE)
