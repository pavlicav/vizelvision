"""Orange Cat Behavior No. 6, The Witching Hour: a nature documentary, after dark on
Halloween. The room is lit by a jack-o'-lantern on the floor and, now and then, lightning
through the window. The orange cat sits staring hard at the far corner, where, in the
blackness, two pale eyes open. On the open logo: the pumpkin's flame flares, lightning (the
eyes in the corner are gone), the cat's huge shadow on the wall opens glowing eyes of its own,
and the cat turns, slowly, to look at you, its eyes catching the light. On the closed logo
VIZELVISION glows onto the wall like carved pumpkin light, HAPPY HALLOWEEN, lightning on the
last note. The cat gives you a slow blink. Its shadow does not blink. The iris closes on
the shadow's eyes.

Draco: "The orange cat... is watching something." / "It is no longer watching the corner."
/ "Happy Halloween."
"""
import math
import random
from functools import lru_cache

import cairo

import cats
import only_on as O
from common import (INK, TAU, W, H, back_out, clamp, ease_in, ease_in_out, ease_out, font,  # noqa: F401
                    grain, inked, iris, pulse, rounded_rect, span, text_path, vignette)

ID = 'cat-witching-hour'
NAME = 'Orange Cat Behavior: The Witching Hour'
KIND = 'ident'
ORDER = 30
DESCRIPTION = ("A nature documentary for Halloween: by jack-o'-lantern light the orange cat stares at a dark "
               'corner where something opens its eyes; lightning; the cat turns to look at you, and its huge '
               'shadow on the wall opens glowing eyes of its own. VIZELVISION glows onto the wall; the cat '
               'blinks, the shadow does not. Narrated by Draco.')
DURATION = 10.0
STILL_AT = 8.45
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
IRIS_OPEN = (0.0, 0.6)
CAPTION = (0.4, 3.0)
CORNER_EYES = (1.9, 3.55)                    # open in the dark; gone in the lightning
NOTES = (3.3, 3.55, 3.8, 4.3)                # the open logo
FLARE = 3.3                                  # the pumpkin's flame jumps
LIGHTNING = (3.55, 8.2)
SHADOW_EYES = 3.8                            # the shadow opens its eyes
TURN = (4.3, 4.75)                           # the cat turns to you
SHADOW_GROW = (4.3, 6.2)
LOGO = (7.2, 7.45, 7.7, 8.2)                 # the closed logo
BLINK = (8.7, 9.1)                           # the cat blinks; the shadow does not
IRIS_CLOSE = (9.25, 9.6)

FLOOR = 650
SEAT = (600, FLOOR)
PUMPKIN = (900, FLOOR)
LIGHT = (900, 600)                           # the candle, for the shadow
CORNER = (78, 352)
WINDOW = (990, 70, 210, 250)
WALL = (0.20, 0.13, 0.22)
GLOW = (1.0, 0.55, 0.1)
EYE_GLOW = (0.72, 1.0, 0.25)


def candle(t):
    """How bright the candle is: a restless flicker, and the flare on the first note."""
    f = 0.82 + 0.08 * math.sin(t * 13.1) + 0.06 * math.sin(t * 29.3 + 1) + 0.04 * math.sin(t * 47.9 + 2)
    return f + 0.6 * pulse(t, FLARE, 0.5)


def lightning(t):
    return max(pulse(t, LIGHTNING[0], 0.35) + 0.6 * pulse(t, LIGHTNING[0] + 0.12, 0.25),
               pulse(t, LIGHTNING[1], 0.45) + 0.5 * pulse(t, LIGHTNING[1] + 0.15, 0.3))


# ---------------------------------------------------------------- the room

@lru_cache(maxsize=1)
def room_surface():
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(s)
    ctx.set_source_rgb(*WALL)
    ctx.paint()
    ctx.set_source_rgb(WALL[0] * 0.85, WALL[1] * 0.85, WALL[2] * 0.85)
    for x in range(0, W, 64):                                # faded stripes
        ctx.rectangle(x, 0, 22, FLOOR)
    ctx.fill()
    rand = random.Random(31)                                 # cobwebs in the corner, up high
    ctx.set_source_rgba(0.8, 0.8, 0.85, 0.22)
    ctx.set_line_width(1.2)
    for k in range(7):
        a = k * (TAU / 4) / 6
        ctx.move_to(0, 0)
        ctx.line_to(math.cos(a) * 190, math.sin(a) * 190)
    for r in range(30, 190, 32):
        ctx.move_to(r, 0)
        for k in range(1, 7):
            a = k * (TAU / 4) / 6
            mid = a - (TAU / 4) / 12
            ctx.curve_to(math.cos(mid) * r * 0.8, math.sin(mid) * r * 0.8, math.cos(mid) * r * 0.8,
                         math.sin(mid) * r * 0.8, math.cos(a) * r, math.sin(a) * r)
    ctx.stroke()
    ctx.rectangle(0, FLOOR, W, H - FLOOR)                    # floorboards
    ctx.set_source_rgb(0.22, 0.13, 0.08)
    ctx.fill()
    ctx.set_source_rgba(0.1, 0.05, 0.03, 0.8)
    ctx.set_line_width(2)
    for x in range(-300, W + 300, 70):
        ctx.move_to(x, FLOOR)
        ctx.line_to(x + 0.5 * (x - 640), H)
    ctx.stroke()
    ctx.rectangle(0, FLOOR - 14, W, 14)                      # the skirting board
    ctx.set_source_rgb(0.12, 0.08, 0.1)
    ctx.fill()
    return s


def window(ctx, t):
    """Night through the glass: a full moon, cloud, and a bare branch swaying."""
    x, y, w, h = WINDOW
    flash = lightning(t)
    ctx.save()
    rounded_rect(ctx, x, y, w, h, 8)
    ctx.clip()
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, 0.05 + 0.6 * flash, 0.06 + 0.6 * flash, 0.16 + 0.7 * flash)
    g.add_color_stop_rgb(1, 0.12 + 0.5 * flash, 0.1 + 0.5 * flash, 0.22 + 0.6 * flash)
    ctx.set_source(g)
    ctx.paint()
    mx, my = x + 140, y + 70
    halo = cairo.RadialGradient(mx, my, 20, mx, my, 110)
    halo.add_color_stop_rgba(0, 0.95, 0.93, 0.8, 0.5)
    halo.add_color_stop_rgba(1, 0.95, 0.93, 0.8, 0)
    ctx.set_source(halo)
    ctx.paint()
    ctx.arc(mx, my, 34, 0, TAU)
    ctx.set_source_rgb(0.96, 0.94, 0.82)
    ctx.fill()
    for cx, cy, r in ((mx - 40 + 12 * math.sin(t * 0.3), my + 22, 28), (mx + 10 + 12 * math.sin(t * 0.3), my + 30, 22)):
        ctx.arc(cx, cy, r, 0, TAU)
        ctx.set_source_rgba(0.1, 0.09, 0.16, 0.75)
        ctx.fill()
    sway = 0.04 * math.sin(t * 1.7)                          # the branch
    ctx.save()
    ctx.translate(x - 10, y + h - 40)
    ctx.rotate(sway)
    ctx.set_source_rgb(0.02, 0.02, 0.04)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for (x0, y0, x1, y1, wd) in ((0, 0, 150, -90, 9), (70, -42, 110, -140, 5), (110, -66, 190, -70, 4),
                                 (130, -78, 170, -150, 3), (40, -24, 60, -90, 4), (150, -90, 230, -130, 3)):
        ctx.move_to(x0, y0)
        ctx.line_to(x1, y1)
        ctx.set_line_width(wd)
        ctx.stroke()
    ctx.restore()
    ctx.restore()
    rounded_rect(ctx, x, y, w, h, 8)                         # the frame and its cross
    ctx.set_source_rgb(0.08, 0.05, 0.07)
    ctx.set_line_width(12)
    ctx.stroke()
    ctx.rectangle(x + w / 2 - 4, y, 8, h)
    ctx.rectangle(x, y + h / 2 - 4, w, 8)
    ctx.fill()
    ctx.rectangle(x - 18, y + h, w + 36, 14)                 # the sill
    ctx.set_source_rgb(0.12, 0.08, 0.1)
    ctx.fill()


def darkness(ctx, t):
    """Night everywhere the candle does not reach."""
    k = candle(t)
    g = cairo.RadialGradient(*LIGHT, 30, *LIGHT, 980)
    g.add_color_stop_rgba(0, 0.02, 0.01, 0.05, 0.12)
    g.add_color_stop_rgba(0.35 * k, 0.02, 0.01, 0.05, 0.55)
    g.add_color_stop_rgba(1, 0.02, 0.01, 0.05, 0.9)
    ctx.set_source(g)
    ctx.paint()
    warm = cairo.RadialGradient(*LIGHT, 10, *LIGHT, 520 * k)  # the candle's warmth on the floor and the cat
    warm.add_color_stop_rgba(0, 1.0, 0.55, 0.15, 0.32 * k)
    warm.add_color_stop_rgba(1, 1.0, 0.45, 0.1, 0)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_source(warm)
    ctx.paint()
    ctx.restore()
    flash = lightning(t)
    if flash:
        ctx.set_source_rgba(0.75, 0.8, 1.0, min(0.42, 0.35 * flash))
        ctx.paint()


# ---------------------------------------------------------------- the jack-o'-lantern

def pumpkin(ctx, t):
    x, y = PUMPKIN
    k = candle(t)
    ctx.save()
    ctx.translate(x, y)
    for dx, rx in ((-38, 44), (38, 44), (-18, 46), (18, 46), (0, 44)):    # the ribs
        ctx.save()
        ctx.translate(dx, -50)
        ctx.scale(rx, 50)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        g = cairo.RadialGradient(-20, -70, 10, 0, -50, 90)
        g.add_color_stop_rgb(0, 0.98, 0.55, 0.12)
        g.add_color_stop_rgb(1, 0.62, 0.26, 0.04)
        inked(ctx, g, 4, (0, 0))
    ctx.move_to(-4, -98)                                      # the stem
    ctx.curve_to(-6, -118, 4, -128, 14, -126)
    ctx.line_to(12, -116)
    ctx.curve_to(6, -114, 6, -104, 6, -98)
    ctx.close_path()
    inked(ctx, (0.3, 0.32, 0.12), 3, (0, 0))
    ctx.move_to(-46, -70)                                     # the face, carved out
    ctx.line_to(-18, -78)
    ctx.line_to(-30, -52)
    ctx.close_path()
    ctx.move_to(46, -70)
    ctx.line_to(18, -78)
    ctx.line_to(30, -52)
    ctx.close_path()
    ctx.move_to(-6, -52)
    ctx.line_to(6, -52)
    ctx.line_to(0, -40)
    ctx.close_path()
    ctx.move_to(-56, -34)
    for i, px in enumerate(range(-44, 57, 12)):
        ctx.line_to(px, -34 + (10 if i % 2 == 0 else 0) - 2)
    ctx.curve_to(40, -6, -40, -6, -56, -34)
    ctx.close_path()
    g = cairo.RadialGradient(0, -50, 4, 0, -50, 60)
    g.add_color_stop_rgb(0, 1.0, 0.95 * min(1, k), 0.55)
    g.add_color_stop_rgb(1, 1.0, 0.55 * min(1, k), 0.05)
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(2.5)
    ctx.stroke()
    ctx.restore()
    ctx.save()                                                # the glow around it
    ctx.set_operator(cairo.OPERATOR_ADD)
    g = cairo.RadialGradient(x, y - 50, 20, x, y - 50, 170 * k)
    g.add_color_stop_rgba(0, 1.0, 0.6, 0.15, 0.28 * k)
    g.add_color_stop_rgba(1, 1.0, 0.5, 0.1, 0)
    ctx.set_source(g)
    ctx.paint()
    ctx.restore()


# ---------------------------------------------------------------- the watchers

def eyes_at(ctx, points, r, colour, alpha, slit=0.0):
    """Glowing eyes: a halo and a bright almond, optionally a dark slit pupil."""
    if alpha <= 0:
        return
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for x, y in points:
        g = cairo.RadialGradient(x, y, 0, x, y, r * 3.2)
        g.add_color_stop_rgba(0, *colour, 0.55 * alpha)
        g.add_color_stop_rgba(1, *colour, 0)
        ctx.set_source(g)
        ctx.arc(x, y, r * 3.2, 0, TAU)
        ctx.fill()
    ctx.restore()
    for x, y in points:
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(r, r * 0.62)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(min(1, colour[0] + 0.3), min(1, colour[1] + 0.2), min(1, colour[2] + 0.4), alpha)
        ctx.fill()
        if slit:
            ctx.save()
            ctx.translate(x, y)
            ctx.scale(r * 0.18, r * 0.6 * slit)
            ctx.arc(0, 0, 1, 0, TAU)
            ctx.restore()
            ctx.set_source_rgba(0, 0, 0, alpha)
            ctx.fill()


def corner(ctx, t):
    """Something in the corner opens its eyes, blinks once, and is gone in the lightning."""
    p = ease_in_out(span(t, CORNER_EYES[0], CORNER_EYES[0] + 0.6)) * (1 - span(t, CORNER_EYES[1], CORNER_EYES[1] + 0.05))
    blink = math.sin(math.pi * span(t, 2.75, 2.95))
    if p <= 0:
        return
    x, y = CORNER
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(1, max(0.05, 1 - blink))
    eyes_at(ctx, ((-16, 0), (16, 0)), 7, (0.85, 0.85, 0.7), 0.85 * p)
    ctx.restore()


def look(t):
    """At the corner (hard left), then, slowly, at you."""
    return -1.0 + ease_in_out(span(t, *TURN))


def cat_pose(t):
    blink = (ease_in_out(span(t, BLINK[0], BLINK[0] + 0.16)) - ease_in_out(span(t, BLINK[1] - 0.14, BLINK[1])))
    return look(t), ('wide' if t >= TURN[0] else 'open'), blink


def shadow_scale(t):
    return 1.35 + 0.85 * ease_in_out(span(t, *SHADOW_GROW)) + 0.04 * (candle(t) - 0.85)


def shadow(ctx, t):
    """The cat, thrown up the wall by the candle: huge, black, a little soft."""
    s = shadow_scale(t)
    lx, ly = LIGHT
    looking, _, _ = cat_pose(t)
    ctx.save()
    ctx.rectangle(0, 0, W, FLOOR - 14)
    ctx.clip()
    ctx.push_group()
    ctx.translate(lx, ly)
    ctx.scale(s, s)
    ctx.translate(-lx, -ly)
    O.sitting(ctx, t, *SEAT, looking, 0.0, 'open', 0.0, 0.0)
    shape = ctx.pop_group()
    ctx.set_source_rgba(0.0, 0.0, 0.02, 0.72)
    ctx.mask(shape)
    ctx.restore()


def cat_eyes(t, sc=1.0):
    """Where the sitting cat's eyes are, in the frame."""
    looking, _, _ = cat_pose(t)
    x, y = SEAT
    return [(x + O.SIZE * (6 * looking + side * 22), y + O.SIZE * (-150 - 8)) for side in (-1, 1)]


def shadow_eyes(t):
    s = shadow_scale(t)
    lx, ly = LIGHT
    return [(lx + (ex - lx) * s, ly + (ey - ly) * s) for ex, ey in cat_eyes(t)]


def cat(ctx, t):
    looking, eyes, blink = cat_pose(t)
    O.sitting(ctx, t, *SEAT, looking, 0.0, eyes, blink, 0.0)


def catch_light(ctx, t):
    """Once it faces you its eyes catch the candle: eyeshine."""
    p = ease_out(span(t, TURN[1] - 0.1, TURN[1] + 0.3))
    _, _, blink = cat_pose(t)
    if p > 0:
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        for x, y in cat_eyes(t):
            g = cairo.RadialGradient(x, y, 0, x, y, 34)
            g.add_color_stop_rgba(0, *EYE_GLOW, 0.5 * p * (1 - blink))
            g.add_color_stop_rgba(1, *EYE_GLOW, 0)
            ctx.set_source(g)
            ctx.arc(x, y, 34, 0, TAU)
            ctx.fill()
        ctx.restore()


# ---------------------------------------------------------------- the closed logo

def title(ctx, t):
    """VIZELVISION glowing onto the wall a letter at a time, like light through carved
    pumpkin; drips; HAPPY HALLOWEEN under it."""
    if t < LOGO[0] - 0.05:
        return
    word = 'VIZELVISION'
    font(ctx, 'URW Gothic', 92)
    widths = [ctx.text_extents(ch).x_advance + 4 for ch in word]
    x = 640 - sum(widths) / 2
    flick = candle(t)
    for i, (ch, wd) in enumerate(zip(word, widths)):
        when = LOGO[0] + i * (LOGO[3] - LOGO[0]) / 10
        p = span(t, when - 0.05, when + 0.2)
        if p > 0:
            ctx.save()
            ctx.translate(x, 196)
            s = back_out(p, 2.0)
            ctx.translate(wd / 2, 0)
            ctx.scale(s, s)
            ctx.translate(-wd / 2, 0)
            ctx.move_to(0, 0)
            ctx.text_path(ch)
            path = ctx.copy_path()
            ctx.save()
            ctx.set_operator(cairo.OPERATOR_ADD)
            for width, alpha in ((22, 0.08), (10, 0.18)):
                ctx.new_path()
                ctx.append_path(path)
                ctx.set_source_rgba(*GLOW, alpha * flick)
                ctx.set_line_width(width)
                ctx.set_line_join(cairo.LINE_JOIN_ROUND)
                ctx.stroke()
            ctx.restore()
            ctx.new_path()
            ctx.append_path(path)
            g = cairo.LinearGradient(0, -70, 0, 0)
            g.add_color_stop_rgb(0, 1.0, 0.92 * min(1, flick), 0.5)
            g.add_color_stop_rgb(1, 1.0, 0.45, 0.05)
            ctx.set_source(g)
            ctx.fill()
            drip = ease_in(span(t, when + 0.15, when + 1.4))          # a drip or two runs down
            rand = random.Random(i)
            for k in range(1 + i % 2):
                dx = rand.uniform(8, wd - 14)
                length = drip * rand.uniform(12, 30)
                if length > 1:
                    rounded_rect(ctx, dx, -4, 6, length + 4, 3)
                    ctx.arc(dx + 3, length, 4.5, 0, TAU)
                    ctx.set_source_rgb(1.0, 0.5, 0.06)
                    ctx.fill()
            ctx.restore()
        x += wd
    p = ease_out(span(t, LOGO[3], LOGO[3] + 0.4))
    if p > 0:
        font(ctx, 'Nimbus Sans', 26)
        ctx.new_path()
        text_path(ctx, 'HAPPY HALLOWEEN', 640, 270, tracking=9, align='center')
        ctx.set_source_rgba(*EYE_GLOW, p * 0.9)
        ctx.fill()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    ctx.set_source_surface(room_surface(), 0, 0)
    ctx.paint()
    window(ctx, t)
    shadow(ctx, t)
    cat(ctx, t)
    darkness(ctx, t)
    pumpkin(ctx, t)
    corner(ctx, t)
    if t >= SHADOW_EYES:                                      # the shadow's eyes, over the dark (they never blink)
        p = ease_out(span(t, SHADOW_EYES, SHADOW_EYES + 0.35))
        eyes_at(ctx, shadow_eyes(t), 9 * shadow_scale(t) / 1.35, (1.0, 0.35, 0.05), p * (0.85 + 0.15 * math.sin(t * 9)))
    catch_light(ctx, t)
    title(ctx, t)
    cats.caption(ctx, t, 6, 'The Witching Hour', *CAPTION)
    vignette(ctx, 0.6)
    grain(ctx, frame, 0.6)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        iris(ctx, SEAT[0], SEAT[1] - 150, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        (ax, ay), (bx, by) = shadow_eyes(t)
        x, y = (ax + bx) / 2, (ay + by) / 2
        iris(ctx, x, y, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 110 * (1 - closing) / .3)
