"""Orange Cat Behavior No. 2, The Remote: a nature documentary. The cat from Only on
VizelVision sits on an ottoman beside the remote. It considers the remote, considers you,
and lies down on it. Its weight presses Channel Up once on each note of the open logo, and
the set flips 15, 16, 17, 18 (colour bars, snow, a shopping channel, snow) to 19:
VizelVision, the TV emblem on its sunburst. The cat, satisfied, loafs on. VIZELVISION 19
wipes in on the closed logo, a mrrp, a slow blink, the iris.

The narrator is Draco: "The orange cat selects its channel." / "Vizzle Vision nineteen." /
"A fine choice." (on the closed logo).
"""
import math
import random

import cairo

import cats
import only_on as O
from common import (A, INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, clamp, ease_in, ease_in_out,  # noqa: F401
                    ease_out, font, glint, grain, inked, iris, mix, pixel_text, pulse, rounded_rect, span,
                    vignette)

ID = 'cat-remote'
NAME = 'Orange Cat Behavior: The Remote'
KIND = 'ident'
ORDER = 10
DESCRIPTION = ('A nature documentary: the orange cat lies down on the remote, and its weight changes the channel '
               'once on each note of the logo, 15, 16, 17, 18, to VizelVision 19. "A fine choice." Narrated by Draco.')
DURATION = 10.0
STILL_AT = 7.9
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
IRIS_OPEN = (0.0, 0.45)
CAPTION = (0.4, 2.6)
LOOKS = ((0.6, 1.0), (1.3, 0.0), (1.75, 1.0))     # (when, gaze): the remote, you, the remote
HOP = (2.0, 2.45)                                 # from beside the remote onto it
PRESSES = (3.0, 3.25, 3.5, 4.0)                   # the open logo: Channel Up, four times
PLEASED = (4.15, 6.6)
BANNER = 7.0                                      # the closed logo
MRRP = 8.0
BLINK = (8.35, 8.9)
IRIS_CLOSE = (9.2, 9.6)

TOP = 520                                         # the ottoman's top
OTTOMAN = (440, 330)                              # centre, width
SEAT = (345, TOP)                                 # where it sits, then where it loafs
LOAF = (478, TOP)
REMOTE = (446, 606)                               # its left and right ends; the infrared eye is on the right
CHANNELS = (15, 16, 17, 18, 19)


# ---------------------------------------------------------------- the remote

def remote(ctx, t):
    x0, x1 = REMOTE
    y = TOP + 2
    ctx.save()
    ctx.translate(0, 3 * max((pulse(t, p, 0.12) for p in PRESSES), default=0))
    rounded_rect(ctx, x0, y - 20, x1 - x0, 22, 9)
    g = cairo.LinearGradient(0, y - 20, 0, y + 2)
    g.add_color_stop_rgb(0, 0.28, 0.28, 0.32)
    g.add_color_stop_rgb(1, 0.1, 0.1, 0.12)
    inked(ctx, g, 4, (4, 4))
    for i, colour in enumerate(((0.9, 0.2, 0.2), (0.85, 0.85, 0.9), (0.85, 0.85, 0.9), (0.2, 0.75, 0.3),
                                (0.85, 0.85, 0.9), (0.95, 0.8, 0.2))):
        rounded_rect(ctx, x0 + 18 + i * 22, y - 24, 14, 6, 3)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    lit = max((pulse(t, p, 0.14) for p in PRESSES), default=0)
    ctx.arc(x1 - 4, y - 10, 4, 0, TAU)
    ctx.set_source_rgb(0.4 + 0.6 * lit, 0.05, 0.08)
    ctx.fill()
    ctx.restore()


def infrared(ctx, t):
    """Each press: a dotted beam from the remote's eye to the set, travelling fast."""
    sx, sy = REMOTE[1] - 4, TOP - 8
    tx, ty = O.CABINET[0] + 30, O.CABINET[1] + 214
    for p in PRESSES:
        q = span(t, p, p + 0.16)
        if not 0 < q < 1:
            continue
        head = ease_out(q)
        tail = max(0.0, head - 0.45)
        for k in range(14):
            u = tail + (head - tail) * k / 13
            x = sx + (tx - sx) * u
            y = sy + (ty - sy) * u - 70 * math.sin(math.pi * u)
            ctx.arc(x, y, 2.4 + 1.6 * k / 13, 0, TAU)
            ctx.set_source_rgba(1, 0.2, 0.25, 0.25 + 0.6 * k / 13)
            ctx.fill()
        if q > 0.8:
            glint(ctx, tx, ty, 14 * math.sin(math.pi * (q - 0.8) / 0.2), q * 3, 0.9)


# ---------------------------------------------------------------- the screen

def channel(t):
    """The channel showing, and how long since it came on."""
    shown, since = CHANNELS[0], -1.0
    for p, number in zip(PRESSES, CHANNELS[1:]):
        if t >= p:
            shown, since = number, p
    return shown, t - since


def bars(ctx, x, y, w, h):
    for i, colour in enumerate(((0.75, 0.75, 0.75), (0.75, 0.75, 0), (0, 0.75, 0.75), (0, 0.75, 0),
                                (0.75, 0, 0.75), (0.75, 0, 0), (0, 0, 0.75))):
        ctx.rectangle(x + w * i / 7, y, w / 7 + 1, h * 0.72)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    for i, colour in enumerate(((0, 0.1, 0.35), (1, 1, 1), (0.2, 0, 0.4), (0.05, 0.05, 0.05))):
        ctx.rectangle(x + w * i / 4, y + h * 0.72, w / 4 + 1, h * 0.28)
        ctx.set_source_rgb(*colour)
        ctx.fill()


_SNOW = {}


def snow(ctx, frame, x, y, w, h):
    key = frame % 6
    if key not in _SNOW:
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 136, 114)
        data = surface.get_data()
        rand = random.Random(key * 31 + 5)
        noise = rand.randbytes(136 * 114)
        for i, v in enumerate(noise):
            data[4 * i:4 * i + 3] = bytes((v, v, v))
        surface.mark_dirty()
        _SNOW[key] = surface
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(w / 136, h / 114)
    ctx.set_source_surface(_SNOW[key], 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_NEAREST)
    ctx.paint()
    ctx.restore()


def shopping(ctx, t, x, y, w, h):
    """Channel 17: a shopping channel's CALL NOW, blinking, and a price in a starburst."""
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, 0.12, 0.2, 0.75)
    g.add_color_stop_rgb(1, 0.02, 0.05, 0.3)
    ctx.set_source(g)
    ctx.rectangle(x, y, w, h)
    ctx.fill()
    ctx.rectangle(x, y + h - 62, w, 44)
    ctx.set_source_rgb(0.85, 0.08, 0.1)
    ctx.fill()
    if math.sin(t * 22) > -0.3:
        pixel_text(ctx, 'CALL NOW!', x + w / 2, y + h - 54, 4, YELLOW, align='center')
    ctx.save()
    ctx.translate(x + w / 2, y + 74)
    ctx.rotate(-0.15)
    ctx.move_to(62, 0)
    for k in range(1, 28):
        r = 62 if k % 2 == 0 else 46
        ctx.line_to(math.cos(k * TAU / 28) * r, math.sin(k * TAU / 28) * r * 0.75)
    ctx.close_path()
    ctx.set_source_rgb(*YELLOW)
    ctx.fill()
    pixel_text(ctx, '19.95', 0, -10, 4, (0.8, 0.05, 0.1), align='center')
    ctx.restore()


def station(ctx, t, x, y, w, h):
    """Channel 19: VizelVision, the emblem on a turning sunburst."""
    cx, cy = x + w / 2, y + h / 2 + 8
    g = cairo.RadialGradient(cx, cy, 10, cx, cy, w * 0.7)
    g.add_color_stop_rgb(0, 1.0, 0.55, 0.75)
    g.add_color_stop_rgb(1, 0.45, 0.1, 0.5)
    ctx.set_source(g)
    ctx.rectangle(x, y, w, h)
    ctx.fill()
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(t * 0.4)
    for i in range(14):
        a = i * TAU / 14
        ctx.move_to(0, 0)
        ctx.arc(0, 0, w, a, a + TAU / 28)
        ctx.close_path()
    ctx.set_source_rgba(*YELLOW, 0.3)
    ctx.fill()
    ctx.restore()
    since = t - PRESSES[-1]
    k = back_out(span(since, 0.0, 0.4), 2.2) * (1 + 0.05 * pulse(t, BANNER, 0.4))
    if k <= 0.001:
        return
    ctx.save()
    ctx.translate(cx, cy + 14)
    ctx.scale(0.5 * k, 0.5 * k)
    A.draw_tv(ctx, t, 1, 0.0)
    ctx.restore()


def screen(ctx, t, x, y, w, h):
    number, since = channel(t)
    if number == 15:
        bars(ctx, x, y, w, h)
    elif number in (16, 18):
        snow(ctx, int(t * 60), x, y, w, h)
    elif number == 17:
        shopping(ctx, t, x, y, w, h)
    else:
        station(ctx, t, x, y, w, h)
    if 0 <= since < 0.05:                                 # the change: a black blink
        ctx.set_source_rgb(0, 0, 0)
        ctx.rectangle(x, y, w, h)
        ctx.fill()
    if number != 19 and since < 1.6 or number == 19:      # the on-screen channel number
        text = f'CH {number}' if number != 19 else '19'
        cell = 5 if number != 19 else 7
        pixel_text(ctx, text, x + w - 22, y + 18, cell, (0.35, 1.0, 0.35), align='right', shadow=(1, 1, (0, 0.1, 0)))


# ---------------------------------------------------------------- the cat

def gaze(t):
    look = 0.0
    for when, target in LOOKS:
        look += (target - look) * ease_in_out(span(t, when, when + 0.16))
    return look


def cat(ctx, t):
    if t < HOP[1]:
        squash = 0.8 * math.sin(math.pi * span(t, HOP[0] - 0.25, HOP[0]))
        p = span(t, *HOP)
        x = SEAT[0] + (LOAF[0] - SEAT[0]) * ease_in_out(p)
        y = SEAT[1] - 70 * math.sin(math.pi * p)
        blink = math.sin(math.pi * span(t, 1.05, 1.2))
        O.sitting(ctx, t, x, y, gaze(t), 0.0, 'open', blink, 0.0, squash)
        return
    land = t - HOP[1]
    squash = max(0.0, math.exp(-land * 9) * math.cos(land * 22) * 0.8)
    squash = max(squash, max(0.35 * pulse(t, p, 0.18) for p in PRESSES))     # kneading: one press each
    eyes = 'squint' if PLEASED[0] <= t < PLEASED[1] else 'open'
    mouth = math.sin(math.pi * span(t, MRRP, MRRP + 0.28))
    blink = (ease_in_out(span(t, BLINK[0], BLINK[0] + 0.18)) - ease_in_out(span(t, BLINK[1] - 0.15, BLINK[1])))
    O.loaf(ctx, t, LOAF[0], LOAF[1], eyes, blink, mouth, squash)     # the tail down the ottoman's left


def hearts(ctx, t):
    for k, start in enumerate((BLINK[0] + 0.1, BLINK[0] + 0.35)):
        p = span(t, start, start + 0.9)
        if not 0 < p < 1:
            continue
        x, y = LOAF[0] - 60 + 30 * k, LOAF[1] - 215 - 50 * p
        s = 13 * math.sin(math.pi * min(1.0, p * 1.5))
        ctx.save()
        ctx.translate(x, y)
        ctx.move_to(0, s * 0.9)
        ctx.curve_to(-s * 1.4, -s * 0.2, -s * 0.6, -s * 1.3, 0, -s * 0.5)
        ctx.curve_to(s * 0.6, -s * 1.3, s * 1.4, -s * 0.2, 0, s * 0.9)
        inked(ctx, PINK, 3, (3, 3))
        ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    O.room(ctx, t)
    cats.tv_set(ctx, t, screen, 0.012 * pulse(t, PRESSES[-1], 0.5) * math.sin(t * 40))
    cats.ottoman(ctx, OTTOMAN[0], TOP, OTTOMAN[1])
    remote(ctx, t)
    cat(ctx, t)
    infrared(ctx, t)
    hearts(ctx, t)
    cats.banner(ctx, t, 'VIZELVISION 19', BANNER, cx=900, cy=676)
    cats.caption(ctx, t, 2, 'The Remote', *CAPTION)
    vignette(ctx, 0.4)
    grain(ctx, frame, 0.45)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        iris(ctx, SEAT[0], SEAT[1] - 120, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        iris(ctx, LOAF[0] - 30, LOAF[1] - 70, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 90 * (1 - closing) / .3)
