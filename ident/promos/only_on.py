"""Only on VizelVision: a living room after dark, an orange cat on a side table beside a
mug. It looks at the mug, at you, at the mug, and pushes it to the edge, a nudge on each
of the logo's notes. It teeters, the cat stares you down, one last tap, and the mug falls:
KRSSH. Satisfied, the cat leaps onto the TV, settles into a loaf with its tail down the
side, and the set comes on with the programme on air. ONLY ON VIZELVISION, a "mrrp" and a
slow blink, and the iris closes on the cat.

The programme's name is master's live text on the screen (OVERLAYS). The web app also
has it voiced, "{name}... only on Vizel Vision.", in a copy of this promo (VOICE).
"""
import math
import random

import cairo

from common import (INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, clamp, ease_in, ease_in_out,  # noqa: F401
                    ease_out, flash, font, glint, grain, inked, inked_stroke, iris, mix, pulse, rounded_rect,
                    span, star, text_path, vignette)

ID = 'only-on'
NAME = 'Only on VizelVision'
KIND = 'promo'
ORDER = 3
DESCRIPTION = ('An orange cat pushes a mug off the table, leaps onto the TV and loafs there while the set shows '
               'the programme on air: "...only on VizelVision." The name is said aloud for each programme. Ophelia.')
DURATION = 10.0
STILL_AT = 7.6

# Hit points (the music's too).
IRIS_OPEN = (0.0, 0.5)
LOOK_UP = 0.6                      # from the mug to you
NUDGES = (1.0, 1.25, 1.5)          # C, E, G: one nudge each
TEETER = 2.0                       # A, held: it hangs on the edge
GLANCE = (2.55, 2.85)              # a look at the mug and back
TAP = 3.0
FALL = (3.05, 3.5)
CRASH = 3.5
PLEASED = (3.7, 4.3)
LEAP = (4.4, 4.9)                  # from the table to the TV
LAND = 4.9
TV_ON = (5.15, 5.42)
NAME_IN = 5.5
BANNER = 7.0                       # the closed logo, sung
MRRP = 8.0
BLINK = (8.3, 8.85)
IRIS_CLOSE = (9.2, 9.6)

FUR, FUR_DARK, BELLY = (0.97, 0.56, 0.17), (0.80, 0.35, 0.08), (1.0, 0.92, 0.78)
NOSE, EYE = (0.95, 0.52, 0.56), (0.66, 0.85, 0.22)
WALL, WALL_STRIPE = (0.93, 0.80, 0.56), (0.90, 0.75, 0.50)
WOOD, WOOD_DARK = (0.56, 0.33, 0.16), (0.40, 0.22, 0.10)
FLOOR = 650
TABLE = (200, 560, 432)            # left, right, top
MUG_START = 500
SEAT = (360, TABLE[2])             # where the cat sits
CABINET = (755, 334, 390, 270)
SCREEN = (780, 356, 270, 226)
LOAF = (868, CABINET[1])           # where it loafs (bottom centre)
SIZE = 1.15                        # the cat's scale

OVERLAYS = [
    {'field': 'programme', 'box': [SCREEN[0] + 16, SCREEN[1] + 18, SCREEN[2] - 32, SCREEN[3] - 36],
     'from': NAME_IN, 'to': IRIS_CLOSE[0] + 0.05,
     'style': {'font': 'URW Gothic', 'bold': True, 'size': 54, 'min_size': 20, 'color': [0.93, 1.0, 1.0],
               'shadow': [3, 3, 0.0, 0.05, 0.22, 0.9], 'lines': 2, 'upper': True, 'tracking': 0.02},
     'enter': {'kind': 'flip', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': 0.15}},
]
# The programme's name, said for each programme (roku_stream/promos.py PromoDesk).
VOICE = {'model': 'aura-2-ophelia-en', 'template': '{name}... only on Vizel Vision.', 'music': 'only-on-music.wav',
         'earliest': 5.2, 'start': 5.6, 'end': 9.1}


# ---------------------------------------------------------------- the room

def room(ctx, t):
    ctx.set_source_rgb(*WALL)
    ctx.paint()
    ctx.set_source_rgb(*WALL_STRIPE)
    for x in range(0, W, 64):
        ctx.rectangle(x, 0, 22, FLOOR)
    ctx.fill()
    rand = random.Random(7)
    for i in range(16):   # faded Memphis squiggles in the wallpaper
        x, y = rand.uniform(0, W), rand.uniform(20, FLOOR - 60)
        ctx.move_to(x - 16, y)
        for k in range(1, 9):
            ctx.line_to(x - 16 + 4 * k, y + (5 if k % 2 else -5))
        ctx.set_source_rgba(*(PINK if i % 2 else TEAL), 0.22)
        ctx.set_line_width(3)
        ctx.stroke()
    window(ctx, t)
    frame_on_wall(ctx)
    ctx.set_source_rgb(0.98, 0.94, 0.86)          # the skirting board
    ctx.rectangle(0, FLOOR - 14, W, 14)
    ctx.fill()
    g = cairo.LinearGradient(0, FLOOR, 0, H)
    g.add_color_stop_rgb(0, *WOOD)
    g.add_color_stop_rgb(1, *WOOD_DARK)
    ctx.set_source(g)
    ctx.rectangle(0, FLOOR, W, H - FLOOR)
    ctx.fill()
    ctx.set_source_rgba(0, 0, 0, 0.18)
    for x in range(-200, W, 150):
        ctx.move_to(x, FLOOR)
        ctx.line_to(x + 60, H)
    ctx.set_line_width(2)
    ctx.stroke()


def window(ctx, t):
    x, y, w, h = 120, 80, 220, 240
    rounded_rect(ctx, x, y, w, h, 10)
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, 0.05, 0.07, 0.25)
    g.add_color_stop_rgb(1, 0.18, 0.18, 0.45)
    inked(ctx, g, 6, (6, 6))
    ctx.arc(x + 160, y + 60, 24, 0, TAU)      # the moon
    ctx.set_source_rgb(1, 0.97, 0.8)
    ctx.fill()
    for i in range(9):
        a = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 2 + i))
        ctx.set_source_rgba(1, 1, 1, a)
        ctx.arc(x + 20 + (i * 53) % (w - 40), y + 25 + (i * 37) % (h - 60), 1.6, 0, TAU)
        ctx.fill()
    ctx.set_source_rgb(*INK)
    ctx.rectangle(x + w / 2 - 3, y, 6, h)
    ctx.rectangle(x, y + h / 2 - 3, w, 6)
    ctx.fill()
    for side in (-1, 1):                        # curtains
        cx = x - 18 if side < 0 else x + w + 18
        ctx.move_to(cx - 30, y - 20)
        ctx.line_to(cx + 30, y - 20)
        ctx.curve_to(cx + 10 * side, y + 100, cx + 30 * side, y + 200, cx + 22, y + h + 30)
        ctx.line_to(cx - 22, y + h + 30)
        ctx.curve_to(cx - 30 * side, y + 200, cx - 10 * side, y + 100, cx - 30, y - 20)
        ctx.close_path()
        inked(ctx, (0.92, 0.42, 0.55), 5, (5, 5))


def frame_on_wall(ctx):
    x, y, w, h = 560, 120, 130, 100
    rounded_rect(ctx, x, y, w, h, 6)
    inked(ctx, (0.98, 0.95, 0.9), 6, (6, 6))
    ctx.rectangle(x + 14, y + 14, w - 28, h - 28)
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, 0.95, 0.4, 0.6)
    g.add_color_stop_rgb(1, 1.0, 0.75, 0.3)
    ctx.set_source(g)
    ctx.fill()
    font(ctx, 'URW Gothic', 46)
    ctx.move_to(x + 46, y + 70)
    ctx.text_path('V')
    inked(ctx, (0.25, 0.85, 0.8), 3, (3, 3))


def table(ctx):
    left, right, top = TABLE
    for lx in (left + 26, right - 46):
        ctx.rectangle(lx, top + 10, 20, FLOOR - top - 10)
        inked(ctx, WOOD_DARK, 5, (5, 5))
    rounded_rect(ctx, left - 10, top, right - left + 20, 22, 6)
    inked(ctx, WOOD, 6, (7, 7))
    ctx.rectangle(left + 20, top + 80, right - left - 40, 12)   # a lower shelf
    inked(ctx, WOOD_DARK, 4, (4, 4))


# ---------------------------------------------------------------- the mug

def mug_pose(t):
    """(x of its centre, bottom y, tilt) of the mug, or None once it has smashed."""
    if t >= CRASH:
        return None
    x = MUG_START + sum(17 * ease_out(span(t, n, n + 0.12)) for n in NUDGES)
    x += 6 * ease_out(span(t, TAP, TAP + 0.1))
    top = TABLE[2]
    if t < TEETER:
        return x, top, 0.0
    if t < FALL[0]:     # teetering over the edge
        wobble = math.sin((t - TEETER) * 14) * 0.09 * (1 - 0.5 * span(t, TEETER, TAP))
        return x, top, max(0.0, wobble)
    p = span(t, *FALL)
    return x + 70 * p, top + (FLOOR - top) * p * p, 0.3 + 2.4 * p


def mug(ctx, t):
    pose = mug_pose(t)
    if pose is None:
        return
    x, bottom, tilt = pose
    ctx.save()
    ctx.translate(TABLE[1], TABLE[2]) if tilt and t < FALL[0] else ctx.translate(x, bottom)
    ctx.rotate(tilt)
    if tilt and t < FALL[0]:
        ctx.translate(x - TABLE[1], bottom - TABLE[2])
    ctx.scale(1.2, 1.2)
    ctx.arc(22, -26, 13, -TAU / 4, TAU / 4)         # handle
    inked_stroke(ctx, WHITE, 7, (4, 4))
    rounded_rect(ctx, -22, -50, 44, 50, 8)
    inked(ctx, WHITE, 5, (5, 5))
    ctx.rectangle(-22, -40, 44, 9)
    ctx.set_source_rgb(*PINK)
    ctx.fill()
    ctx.set_source_rgba(0.55, 0.32, 0.18, 0.9)       # the coffee, steaming a little
    ctx.rectangle(-17, -48, 34, 4)
    ctx.fill()
    ctx.restore()


def smash(ctx, t):
    p = span(t, CRASH, CRASH + 0.75)
    if not 0 < p < 1:
        return
    x, y = MUG_START + 3 * 17 + 6 + 70, FLOOR - 6
    for i in range(7):                                 # shards
        a = -TAU / 4 + (i - 3) * 0.42
        v = 260 + 40 * (i % 3)
        sx = x + math.cos(a) * v * p
        sy = y + math.sin(a) * v * p + 600 * p * p
        ctx.save()
        ctx.translate(sx, sy)
        ctx.rotate(p * 9 + i)
        ctx.move_to(-7, 5)
        ctx.line_to(0, -8)
        ctx.line_to(8, 6)
        ctx.close_path()
        inked(ctx, WHITE if i % 3 else PINK, 2, (2, 2))
        ctx.restore()
    pop = back_out(span(t, CRASH, CRASH + 0.15), 2.2) * (1 - ease_in(span(t, CRASH + 0.5, CRASH + 0.75)))
    if pop <= 0:
        return
    ctx.save()
    ctx.translate(x + 40, y - 70)
    ctx.scale(pop, pop)
    ctx.rotate(-0.12)
    ctx.move_to(95, 0)
    for k in range(1, 24):
        r = 95 if k % 2 == 0 else 52
        ctx.line_to(math.cos(k * TAU / 24) * r * 1.25, math.sin(k * TAU / 24) * r * 0.8)
    ctx.close_path()
    inked(ctx, YELLOW, 5, (6, 6))
    font(ctx, 'URW Gothic', 40, italic=True)
    ext = ctx.text_extents('KRSSH!')
    ctx.move_to(-ext.width / 2 - ext.x_bearing, 14)
    ctx.text_path('KRSSH!')
    inked(ctx, PINK, 3, (3, 3))
    ctx.restore()


# ---------------------------------------------------------------- the cat

def head(ctx, cx, cy, look=0.0, eyes='open', blink=0.0, mouth=0.0, ear=0.0):
    """The cat's head, facing you, centred on (cx, cy). look -1..1 shifts its gaze (left/right)."""
    fx = cx + 6 * look
    for side in (-1, 1):            # ears, the right one twitching
        twitch = ear * 0.25 if side > 0 else 0
        ctx.save()
        ctx.translate(cx + side * 34, cy - 30)
        ctx.rotate(side * (0.2 + twitch))
        ctx.move_to(-18, 10)
        ctx.line_to(side * 4, -40)
        ctx.line_to(18, 10)
        ctx.close_path()
        inked(ctx, FUR, 5, (5, 5))
        ctx.move_to(-9, 4)
        ctx.line_to(side * 3, -26)
        ctx.line_to(9, 4)
        ctx.close_path()
        ctx.set_source_rgb(*NOSE)
        ctx.fill()
        ctx.restore()
    ctx.save()                      # the head: wide, with cheek tufts
    ctx.translate(cx, cy)
    ctx.move_to(-56, 4)
    ctx.curve_to(-60, -40, -30, -48, 0, -48)
    ctx.curve_to(30, -48, 60, -40, 56, 4)
    ctx.line_to(64, 14)
    ctx.line_to(50, 18)
    ctx.curve_to(36, 42, -36, 42, -50, 18)
    ctx.line_to(-64, 14)
    ctx.close_path()
    inked(ctx, FUR, 5, (6, 6))
    ctx.set_source_rgb(*FUR_DARK)   # the tabby M
    ctx.set_line_width(5)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for dx, h in ((-14, 16), (0, 20), (14, 16)):
        ctx.move_to(dx + 6 * look, -44)
        ctx.line_to(dx + 6 * look, -44 + h)
    ctx.stroke()
    ctx.restore()
    for side in (-1, 1):            # muzzle
        ctx.arc(fx + side * 11, cy + 18, 13, 0, TAU)
        ctx.set_source_rgb(*BELLY)
        ctx.fill()
    ctx.move_to(fx - 6, cy + 8)
    ctx.line_to(fx + 6, cy + 8)
    ctx.line_to(fx, cy + 15)
    ctx.close_path()
    ctx.set_source_rgb(*NOSE)
    ctx.fill()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(2.5)
    if mouth > 0.05:
        ctx.save()
        ctx.translate(fx, cy + 27)
        ctx.scale(1, max(.2, mouth))
        ctx.arc(0, 0, 7, 0, TAU)
        ctx.restore()
        ctx.fill()
    else:
        ctx.move_to(fx - 9, cy + 22)
        ctx.curve_to(fx - 5, cy + 27, fx - 1, cy + 25, fx, cy + 19)
        ctx.curve_to(fx + 1, cy + 25, fx + 5, cy + 27, fx + 9, cy + 22)
        ctx.stroke()
    ctx.set_source_rgba(1, 1, 1, 0.85)  # whiskers
    ctx.set_line_width(2)
    for side in (-1, 1):
        for k, dy in enumerate((-6, 0, 6)):
            ctx.move_to(fx + side * 18, cy + 18 + dy / 2)
            ctx.line_to(fx + side * 64, cy + 12 + dy * 2.2 - k)
    ctx.stroke()
    for side in (-1, 1):            # eyes
        ex, ey = fx + side * 22, cy - 8
        if eyes == 'squint':
            ctx.move_to(ex - 12, ey + 3)
            ctx.curve_to(ex - 6, ey - 9, ex + 6, ey - 9, ex + 12, ey + 3)
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(4.5)
            ctx.stroke()
            continue
        open_ = max(0.0, 1 - blink)
        if open_ < 0.12:
            ctx.move_to(ex - 12, ey)
            ctx.curve_to(ex - 6, ey + 5, ex + 6, ey + 5, ex + 12, ey)
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(4)
            ctx.stroke()
            continue
        ctx.save()
        ctx.translate(ex, ey)
        ctx.scale(1, open_)
        ctx.arc(0, 0, 13 if eyes != 'wide' else 15, 0, TAU)
        ctx.restore()
        inked(ctx, EYE, 3, (0, 0))
        ctx.save()
        ctx.translate(ex + 4 * look, ey)
        ctx.scale(1, open_)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.save()
        ctx.translate(ex + 4 * look, ey)
        ctx.scale(7 if eyes == 'wide' else 3.6, 11 * open_)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*INK)
        ctx.fill()
        ctx.arc(ex + 4 * look - 4, ey - 5 * open_, 3, 0, TAU)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()


def striped(ctx, colour, width):
    """Strokes the current path as a tabby tail: inked, then banded."""
    path = ctx.copy_path()
    inked_stroke(ctx, colour, width, (5, 5))
    ctx.append_path(path)
    ctx.set_source_rgb(*FUR_DARK)
    ctx.set_line_width(width)
    ctx.set_line_cap(cairo.LINE_CAP_BUTT)
    ctx.set_dash([7, 15], 4)
    ctx.stroke()
    ctx.set_dash([])


def sitting(ctx, t, x, y, look, reach, eyes, blink, mouth, squash=0.0):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(SIZE * (1 + 0.12 * squash), SIZE * (1 - 0.18 * squash))
    swish = math.sin(t * 2.6)
    ctx.move_to(-40, -12)           # tail, behind, away from the mug
    ctx.curve_to(-110, -10, -128, -60, -112 - 14 * swish, -112)
    striped(ctx, FUR, 20)
    for side in (-1, 1):            # haunches
        ctx.save()
        ctx.translate(side * 40, -26)
        ctx.scale(34, 28)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        inked(ctx, FUR, 5, (5, 5))
    ctx.move_to(-50, 0)             # body
    ctx.curve_to(-60, -60, -36, -110, 0, -112)
    ctx.curve_to(36, -110, 60, -60, 50, 0)
    ctx.close_path()
    inked(ctx, FUR, 5, (6, 6))
    ctx.save()
    ctx.move_to(-50, 0)
    ctx.curve_to(-60, -60, -36, -110, 0, -112)
    ctx.curve_to(36, -110, 60, -60, 50, 0)
    ctx.close_path()
    ctx.clip()
    ctx.save()
    ctx.translate(0, -60)
    ctx.scale(24, 36)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*BELLY)
    ctx.fill()
    ctx.set_source_rgb(*FUR_DARK)
    ctx.set_line_width(6)
    for i in range(3):
        for side in (-1, 1):
            ctx.move_to(side * 56, -28 - i * 24)
            ctx.curve_to(side * 44, -32 - i * 24, side * 40, -24 - i * 24, side * 34, -16 - i * 24)
    ctx.stroke()
    ctx.restore()
    # Front legs: the left down to its paw; the right reaching out to the mug.
    ctx.move_to(-18, -70)
    ctx.line_to(-18, -10)
    inked_stroke(ctx, FUR, 16, (4, 4))
    ctx.save()
    ctx.translate(-18, -6)
    ctx.scale(13, 9)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, BELLY, 4, (3, 3))
    angle = TAU / 4 - reach * (TAU / 4 - 0.1)
    length = 64 + 34 * reach
    px, py = 18 + math.cos(angle) * length, -72 + math.sin(angle) * length
    ctx.move_to(18, -72)
    ctx.line_to(px, py)
    inked_stroke(ctx, FUR, 16, (4, 4))
    ctx.save()
    ctx.translate(px, py)
    ctx.rotate(angle - TAU / 4)
    ctx.scale(13, 9)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, BELLY, 4, (3, 3))
    head(ctx, 0, -150 + 8 * squash, look, eyes, blink, mouth, ear=pulse(t, 1.9, 0.3))
    ctx.restore()


def leaping(ctx, t, x, y, angle):
    """Mid-leap: stretched out along the arc, front paws reaching, tail streaming."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(SIZE, SIZE)
    ctx.rotate(angle)
    ctx.move_to(-70, 0)
    ctx.curve_to(-110, 4, -140, -10, -160, 4 + 10 * math.sin(t * 20))
    striped(ctx, FUR, 18)
    for sx, rot in ((-55, 0.9), (-35, 1.2), (45, -0.9), (62, -1.2)):   # legs
        ctx.move_to(sx, 4)
        ctx.line_to(sx + math.cos(TAU / 4 + rot) * -38 * (1 if sx > 0 else -1), 4 + 34)
        inked_stroke(ctx, FUR, 14, (3, 3))
    ctx.save()
    ctx.scale(80, 30)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, FUR, 5, (6, 6))
    ctx.set_source_rgb(*FUR_DARK)
    ctx.set_line_width(6)
    for i in range(4):
        ctx.move_to(-40 + i * 22, -29)
        ctx.line_to(-46 + i * 22, -12)
    ctx.stroke()
    ctx.restore()
    ctx.save()
    ctx.translate(x + SIZE * (math.cos(angle) * 78 + math.sin(angle) * 12), y + SIZE * (math.sin(angle) * 78 - 26))
    ctx.scale(SIZE, SIZE)
    head(ctx, 0, 0, 0.6, 'wide', 0, 0.4)
    ctx.restore()


def loaf(ctx, t, x, y, eyes, blink, mouth, squash=0.0):
    """A loaf on top of the TV, facing you, paws tucked, tail down the TV's left side."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(SIZE, SIZE)
    sway = math.sin(t * 2.2) * 5
    flick = math.sin(t * 7) * 5 * (0.5 + 0.5 * math.sin(t * 0.9))
    ctx.move_to(-76, -24)           # the tail, hanging down the TV's side, clear of the screen
    ctx.curve_to(-118, -18, -114, 30, -112 + sway, 80)
    ctx.curve_to(-111 + sway, 104, -110 + flick, 122, -106 + flick, 132)
    striped(ctx, FUR, 19)
    breathe = 1 + 0.015 * math.sin(t * 3)
    ctx.save()
    ctx.scale(1 + 0.12 * squash, (1 - 0.2 * squash) * breathe)
    rounded_rect(ctx, -88, -76, 176, 78, 38)
    inked(ctx, FUR, 5, (6, 6))
    ctx.set_source_rgb(*FUR_DARK)
    ctx.set_line_width(6)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for i in range(4):
        ctx.move_to(-6 + i * 24, -74)
        ctx.curve_to(0 + i * 24, -60, -2 + i * 24, -50, 6 + i * 24, -40)
    ctx.stroke()
    for px in (-52, -18):           # tucked paws
        ctx.save()
        ctx.translate(px, -4)
        ctx.scale(15, 8)
        ctx.arc(0, 0, 1, TAU / 2, TAU)
        ctx.restore()
        inked(ctx, BELLY, 3, (2, 2))
    ctx.restore()
    head(ctx, -40, -92 + 10 * squash, 0.0, eyes, blink, mouth)
    ctx.restore()


def cat(ctx, t):
    if t < LEAP[0] - 0.12:
        look = 1.0 - 1.0 * ease_in_out(span(t, LOOK_UP, LOOK_UP + 0.15))
        look += 1.0 * (ease_in_out(span(t, GLANCE[0], GLANCE[0] + 0.1)) - ease_in_out(span(t, GLANCE[1], GLANCE[1] + 0.1)))
        reach = 0.0
        for n in NUDGES + (TAP,):
            reach = max(reach, math.sin(math.pi * span(t, n - 0.12, n + 0.14)))
        eyes = 'squint' if PLEASED[0] <= t < PLEASED[1] else 'wide' if TEETER <= t < TAP + 0.4 else 'open'
        blink = math.sin(math.pi * span(t, 0.85, 1.0))
        squash = math.sin(math.pi * span(t, LEAP[0] - 0.3, LEAP[0] - 0.12)) * 0.8
        sitting(ctx, t, *SEAT, look, reach, eyes, blink, 0.0, squash)
        return
    if t < LAND:
        p = span(t, LEAP[0] - 0.12, LAND)
        x = SEAT[0] + (LOAF[0] - SEAT[0]) * p
        y = SEAT[1] - 60 + (LOAF[1] - 50 - SEAT[1] + 60) * p - 230 * math.sin(math.pi * p)
        angle = -0.5 + 0.9 * p
        leaping(ctx, t, x, y, angle)
        return
    squash = math.exp(-(t - LAND) * 9) * math.cos((t - LAND) * 22) * 0.9
    mouth = math.sin(math.pi * span(t, MRRP, MRRP + 0.28))
    blink = (ease_in_out(span(t, BLINK[0], BLINK[0] + 0.18))
             - ease_in_out(span(t, BLINK[1] - 0.15, BLINK[1])))
    loaf(ctx, t, *LOAF, 'open', blink, mouth, max(0.0, squash))


# ---------------------------------------------------------------- the TV

def tv_wobble(t):
    return math.exp(-max(0.0, t - LAND) * 10) * math.sin(max(0.0, t - LAND) * 30) * 0.03 if t >= LAND else 0.0


def tv(ctx, t):
    x, y, w, h = CABINET
    ctx.rectangle(x - 35, y + h, w + 70, 16)              # the stand
    inked(ctx, WOOD, 5, (6, 6))
    for lx in (x - 20, x + w + 2):
        ctx.rectangle(lx, y + h + 16, 18, FLOOR - y - h - 16)
        inked(ctx, WOOD_DARK, 4, (4, 4))
    ctx.save()
    ctx.translate(x + w / 2, y + h)
    ctx.rotate(tv_wobble(t))
    ctx.translate(-(x + w / 2), -(y + h))
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for tip, ball in (((x + w - 120, y - 92), PINK), ((x + w - 30, y - 104), YELLOW)):
        ctx.move_to(x + w - 75, y - 4)
        ctx.line_to(*tip)
        inked_stroke(ctx, (0.85, 0.88, 0.95), 5, (4, 4))
        ctx.arc(*tip, 10, 0, TAU)
        inked(ctx, ball, 4, (4, 4))
    rounded_rect(ctx, x, y, w, h, 34)
    cabinet = cairo.LinearGradient(0, y, 0, y + h)
    cabinet.add_color_stop_rgb(0, 0.35, 1.0, 0.92)
    cabinet.add_color_stop_rgb(0.35, *TEAL)
    cabinet.add_color_stop_rgb(1, 0.0, 0.36, 0.48)
    inked(ctx, cabinet, 7, (10, 10))
    for ky, colour in ((y + 60, YELLOW), (y + 120, PINK)):
        ctx.arc(x + w - 48, ky, 16, 0, TAU)
        inked(ctx, colour, 4, (3, 3))
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(5)
    for gy in range(y + 170, y + 250, 14):
        ctx.move_to(x + w - 66, gy)
        ctx.line_to(x + w - 30, gy)
    ctx.stroke()
    screen(ctx, t)
    ctx.restore()


def screen(ctx, t):
    sx, sy, sw, sh = SCREEN
    rounded_rect(ctx, sx, sy, sw, sh, 26)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(10)
    ctx.stroke_preserve()
    on = span(t, *TV_ON)
    ctx.save()
    ctx.clip()
    off = cairo.LinearGradient(sx, sy, sx + sw, sy + sh)
    off.add_color_stop_rgb(0, 0.16, 0.2, 0.2)
    off.add_color_stop_rgb(1, 0.05, 0.07, 0.08)
    ctx.set_source(off)
    ctx.paint()
    if on > 0:
        glow = cairo.RadialGradient(sx + sw / 2, sy + sh / 2, 10, sx + sw / 2, sy + sh / 2, sw * 0.75)
        glow.add_color_stop_rgb(0, 0.16, 0.42, 0.82)
        glow.add_color_stop_rgb(1, 0.03, 0.08, 0.26)
        flicker = 0.92 + 0.08 * math.sin(t * 47)
        if on < 1:     # the CRT comes on: a line that opens up
            band = sh * ease_out(on, 2)
            ctx.rectangle(sx, sy + sh / 2 - band / 2 - 2, sw, band + 4)
            ctx.set_source_rgb(0.85, 0.95, 1.0)
            ctx.fill()
        else:
            ctx.set_source(glow)
            ctx.paint_with_alpha(flicker)
            ctx.set_source_rgba(0, 0, 0, 0.22)
            for ly in range(int(sy), int(sy + sh), 4):
                ctx.rectangle(sx, ly, sw, 1.6)
            ctx.fill()
            font(ctx, 'URW Gothic', 18)
            ctx.set_source_rgba(1, 1, 1, 0.35)
            ctx.move_to(sx + sw - 46, sy + sh - 16)
            ctx.text_path('VV')
            ctx.fill()
    ctx.move_to(sx, sy + 40)                     # the glass's reflection
    ctx.line_to(sx, sy)
    ctx.line_to(sx + 110, sy)
    ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.1)
    ctx.fill()
    ctx.restore()


def banner(ctx, t):
    p = span(t, BANNER, BANNER + 0.35)
    if p <= 0:
        return
    text = 'ONLY ON VIZELVISION'
    font(ctx, 'Nimbus Sans', 34, italic=True)
    widths = [ctx.text_extents(ch).x_advance + 6 for ch in text]
    width = sum(widths) - 6
    cx, cy, h = 470, 690, 48
    x0, x1 = cx - width / 2 - 30, cx + width / 2 + 30
    ctx.save()
    ctx.rectangle(0, 0, x0 + (x1 - x0 + 30) * ease_out(p), H)
    ctx.clip()
    ctx.move_to(x0 + 14, cy - h / 2)
    ctx.line_to(x1 + 14, cy - h / 2)
    ctx.line_to(x1 - 14, cy + h / 2)
    ctx.line_to(x0 - 14, cy + h / 2)
    ctx.close_path()
    inked(ctx, PINK, 5, (6, 6))
    ctx.restore()
    x = cx - width / 2
    for i, (ch, wd) in enumerate(zip(text, widths)):
        q = span(t, BANNER + 0.12 + i * 0.02, BANNER + 0.26 + i * 0.02)
        if q > 0:
            ctx.save()
            ctx.translate(x, cy + 12)
            ctx.scale(1, back_out(q))
            ctx.move_to(0, 0)
            ctx.text_path(ch)
            ctx.set_source_rgb(*WHITE)
            ctx.fill()
            ctx.restore()
        x += wd
    for i in range(6):
        life = span(t, BANNER + 0.2 + i * 0.12, BANNER + 0.6 + i * 0.12)
        if 0 < life < 1:
            glint(ctx, x0 + 40 + i * (x1 - x0 - 80) / 5, cy - 34 + 14 * (i % 2), 18 * math.sin(life * math.pi), i)


def hearts(ctx, t):
    """A little heart over the cat as it slow-blinks."""
    p = span(t, BLINK[0] + 0.1, BLINK[1] + 0.5)
    if not 0 < p < 1:
        return
    x, y = LOAF[0] - 46, LOAF[1] - 215 - 40 * p
    s = 14 * math.sin(math.pi * min(1.0, p * 1.5))
    ctx.save()
    ctx.translate(x, y)
    ctx.move_to(0, s * 0.9)
    ctx.curve_to(-s * 1.4, -s * 0.2, -s * 0.6, -s * 1.3, 0, -s * 0.5)
    ctx.curve_to(s * 0.6, -s * 1.3, s * 1.4, -s * 0.2, 0, s * 0.9)
    inked(ctx, PINK, 3, (3, 3))
    ctx.restore()


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    room(ctx, t)
    table(ctx)
    tv(ctx, t)
    mug(ctx, t)
    cat(ctx, t)
    smash(ctx, t)
    banner(ctx, t)
    hearts(ctx, t)
    vignette(ctx, 0.4)
    grain(ctx, frame, 0.45)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        iris(ctx, SEAT[0], SEAT[1] - 110, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        iris(ctx, LOAF[0] - 40, LOAF[1] - 70, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 90 * (1 - closing) / .3)
