"""From Meridian Hill Park: the cascade, thirteen basins stepping down the hill, fills
from the top on a drum roll, a basin a sixteenth. The Sunday drum circle plays the logo's
clap and settles into a groove. "From Meridian Hill Park... this is VizelVision." The
drums play the closed logo together, light runs down the water and the wordmark drops in
over the terrace.

The drum hits come from beats.py, which the music reads too, so every hand lands on its
sound.
"""
import bisect
import math
import random
from functools import lru_cache

import cairo

import beats
from common import (INK, TAU, W, H, WHITE, clamp, ease_in, ease_in_out, ease_out, glint, grain, inked,  # noqa: F401
                    inked_stroke, mix, pulse, rounded_rect, span, vignette)
import neighborhood

ID = 'meridian-hill'
NAME = 'From Meridian Hill Park'
KIND = 'ident'
ORDER = 8
DESCRIPTION = ('Meridian Hill Park on a Sunday: the cascade fills basin by basin on a drum roll, the drum circle plays '
               'the logo\'s clap and a groove. "From Meridian Hill Park... this is VizelVision." Voiced by Aries.')
DURATION = 10.0
STILL_AT = 8.6
OVERLAYS = []

# Hit points (the music's too: promos/music.py, and beats.py).
TAG = (0.6, 6.7)
LOCKUP = beats.CLOSED
SHINE = beats.CLOSED          # light runs down the cascade
BUTTON = beats.BUTTON
FADE = (9.2, 9.55)

CX = 640
TOP_Y, BOTTOM_Y = 238, 548
POOL = (CX, 586, 340, 30)
STONE = (0.82, 0.7, 0.57)     # the park's exposed-aggregate concrete
WATER = (0.33, 0.6, 0.72)
SKY = ((0.45, 0.62, 0.86), (0.78, 0.78, 0.8), (0.99, 0.83, 0.58))
FOLIAGE = (0.2, 0.42, 0.2)


# ---------------------------------------------------------------- the cascade's geometry

def basin(k):
    """(y of its back edge, half-width, depth of its lip's curve, its lip's face) for basin k, 0 the top."""
    f = (k / (beats.BASINS - 1)) ** 1.15
    y = TOP_Y + (BOTTOM_Y - TOP_Y) * f
    nxt = TOP_Y + (BOTTOM_Y - TOP_Y) * ((k + 1) / (beats.BASINS - 1)) ** 1.15 if k < beats.BASINS - 1 else y + 32
    gap = nxt - y
    return y, 58 + 200 * (k / (beats.BASINS - 1)) ** 1.1, 0.95 * gap, 0.3 * gap, gap


def half_width(y):
    """The cascade's half-width at height y (for the walls and stairs)."""
    f = clamp((y - TOP_Y) / (BOTTOM_Y - TOP_Y))
    return 58 + 200 * f ** (1.1 / 1.15)


def arc_path(ctx, y, w, d, steps=24, start=True):
    """The lower half of an ellipse, left to right."""
    for i in range(steps + 1):
        a = math.pi - math.pi * i / steps
        x, py = CX + w * math.cos(a), y + d * math.sin(a)
        if i == 0 and start:
            ctx.move_to(x, py)
        else:
            ctx.line_to(x, py)


# ---------------------------------------------------------------- the park (static, drawn once)

def canopy(ctx, blobs, colour):
    for x, y, r in blobs:
        ctx.new_sub_path()
        ctx.arc(x, y, r, 0, TAU)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(10)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*colour)
    ctx.fill()
    for x, y, r in blobs:
        ctx.new_sub_path()
        ctx.arc(x + r * 0.2, y - r * 0.3, r * 0.5, 0, TAU)
    ctx.set_source_rgba(1.0, 0.85, 0.4, 0.3)
    ctx.fill()


@lru_cache(maxsize=None)
def park():
    """The sky, the upper terrace and its balustrade, the trees, the stairs and walls either
    side of the cascade, the channel the basins sit in, and the pool at the foot."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, 240)
    for stop, rgb in zip((0, 0.55, 1), SKY):
        g.add_color_stop_rgb(stop, *rgb)
    ctx.set_source(g)
    ctx.paint()
    sun = cairo.RadialGradient(1040, 150, 0, 1040, 150, 420)
    sun.add_color_stop_rgba(0, 1, 0.92, 0.7, 0.8)
    sun.add_color_stop_rgba(1, 1, 0.85, 0.6, 0)
    ctx.set_source(sun)
    ctx.paint()
    rand = random.Random(1936)
    canopy(ctx, [(x, rand.uniform(150, 185), rand.uniform(40, 60)) for x in range(300, 1000, 55)],
           mix(FOLIAGE, (0.3, 0.45, 0.35), 0.4))
    ctx.rectangle(0, 205, W, H - 205)                            # the lawn the stairs climb
    ctx.set_source_rgb(0.32, 0.5, 0.22)
    ctx.fill()
    # The terrace: its balustrade along the top of the cascade.
    ctx.rectangle(300, 222, 680, 18)
    inked(ctx, STONE, 3, (0, 0))
    for x in range(312, 970, 16):
        ctx.move_to(x, 222)
        ctx.curve_to(x - 4, 214, x - 4, 206, x, 200)
        ctx.line_to(x + 7, 200)
        ctx.curve_to(x + 11, 206, x + 11, 214, x + 7, 222)
        ctx.close_path()
    ctx.set_source_rgb(*mix(STONE, WHITE, 0.15))
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.rectangle(296, 192, 688, 10)
    inked(ctx, mix(STONE, WHITE, 0.25), 3, (0, 0))
    # The stairs either side, between the cascade's walls and the parapets.
    for side in (-1, 1):
        def edge(y, extra):
            return CX + side * (half_width(y) * extra[0] + extra[1])
        inner, outer = (1.0, 34), (2.05, 96)
        ctx.move_to(edge(240, inner), 240)
        ctx.line_to(edge(BOTTOM_Y + 40, inner), BOTTOM_Y + 40)
        ctx.line_to(edge(BOTTOM_Y + 40, outer), BOTTOM_Y + 40)
        ctx.line_to(edge(240, outer), 240)
        ctx.close_path()
        ctx.set_source_rgb(*mix(STONE, INK, 0.25))
        ctx.fill()
        y = 240.0
        while y < BOTTOM_Y + 40:
            step = 5 + 9 * (y - 240) / (BOTTOM_Y - 200)
            ctx.move_to(edge(y, inner), y)
            ctx.line_to(edge(y, outer), y)
            ctx.line_to(edge(y + step * 0.55, outer), y + step * 0.55)
            ctx.line_to(edge(y + step * 0.55, inner), y + step * 0.55)
            ctx.close_path()
            ctx.set_source_rgb(*mix(STONE, WHITE, 0.12))
            ctx.fill()
            y += step
        for extra, width in ((inner, 14), (outer, 22)):         # the walls' copings
            ctx.move_to(edge(236, extra), 236)
            ctx.line_to(edge(BOTTOM_Y + 40, extra), BOTTOM_Y + 40)
            inked_stroke(ctx, mix(STONE, WHITE, 0.2), width * 0.6, (3, 3))
    for x0, x1 in ((-60, 330), (950, W + 60)):                   # the old trees either side
        blobs = [(rand.uniform(x0, x1), rand.uniform(60, 420), rand.uniform(70, 120)) for _ in range(12)]
        for x, _, _ in blobs[:3]:
            ctx.rectangle(x - 10, 300, 20, 300)
            ctx.set_source_rgb(0.32, 0.22, 0.16)
            ctx.fill()
        canopy(ctx, blobs, FOLIAGE)
    # The channel the basins sit in.
    ctx.move_to(CX - half_width(TOP_Y) - 22, TOP_Y - 6)
    ctx.line_to(CX + half_width(TOP_Y) + 22, TOP_Y - 6)
    ctx.line_to(CX + half_width(BOTTOM_Y) + 30, BOTTOM_Y + 40)
    ctx.line_to(CX - half_width(BOTTOM_Y) - 30, BOTTOM_Y + 40)
    ctx.close_path()
    ctx.set_source_rgb(*mix(STONE, INK, 0.38))
    ctx.fill()
    for _ in range(2500):                                        # the aggregate's pebbles
        x, y = rand.uniform(0, W), rand.uniform(190, BOTTOM_Y + 40)
        ctx.rectangle(x, y, 2, 2)
    ctx.set_source_rgba(0.35, 0.28, 0.22, 0.25)
    ctx.fill()
    # The pool at the foot.
    cx, cy, rx, ry = POOL
    ctx.save()
    ctx.translate(cx, cy + 14)
    ctx.scale(rx + 14, ry + 8)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*mix(STONE, INK, 0.2))
    ctx.fill()
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(rx + 14, ry + 8)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, STONE, 3, (0, 0))
    ctx.rectangle(0, POOL[1] + 40, W, H)                          # the ground the drummers sit on
    ctx.set_source_rgb(0.42, 0.36, 0.28)
    ctx.fill()
    return surface


# ---------------------------------------------------------------- the water

FILLS = beats.fill_times()


def cascade(ctx, t):
    """The basins top to bottom: each dry until its moment, then full, its sheet of water
    falling over the lip onto the next."""
    for k in range(beats.BASINS):
        y, w, d, face, gap = basin(k)
        full = ease_out(span(t, FILLS[k] - 0.06, FILLS[k] + 0.1))
        ctx.move_to(CX - w, y)
        arc_path(ctx, y, w, d, start=False)
        ctx.close_path()
        ctx.set_source_rgb(*mix(mix(STONE, INK, 0.3), mix(WATER, WHITE, 0.1 + 0.25 * k / 12), full))
        ctx.fill()
        arc_path(ctx, y, w, d)                                     # the lip's face
        for i in range(24, -1, -1):
            a = math.pi - math.pi * i / 24
            ctx.line_to(CX + w * math.cos(a), y + d * math.sin(a) + face)
        ctx.close_path()
        ctx.set_source_rgb(*mix(STONE, WHITE, 0.1))
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(2)
        ctx.stroke()
        flow = span(t, FILLS[k] + 0.04, FILLS[k] + 0.14)
        if flow <= 0:
            continue
        ctx.save()                                                 # the sheet, over the lip
        arc_path(ctx, y + face, w - 2, d)
        drop = (gap + 10) * flow
        for i in range(24, -1, -1):
            a = math.pi - math.pi * i / 24
            ctx.line_to(CX + (w - 2) * math.cos(a), y + face + d * math.sin(a) + drop)
        ctx.close_path()
        ctx.clip_preserve()
        ctx.set_source_rgba(0.95, 0.98, 1, 0.55)
        ctx.fill()
        ctx.set_line_width(2)
        for i in range(-int(w), int(w), 7):
            a = math.acos(clamp(i / w, -1, 1))
            ctx.move_to(CX + i, y + face + d * math.sin(a) - 2)
            ctx.line_to(CX + i, y + face + d * math.sin(a) + gap + 12)
        ctx.set_dash([6, 7], -(t * 90 + k * 3))
        ctx.set_source_rgba(1, 1, 1, 0.75)
        ctx.stroke()
        ctx.set_dash([])
        ctx.restore()
    cx, cy, rx, ry = POOL                                          # the pool's water
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(rx, ry)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*mix(WATER, WHITE, 0.15))
    ctx.fill_preserve()
    ctx.save()
    ctx.clip()
    for i in range(4):
        r = (t * 0.5 + i / 4) % 1
        ctx.save()
        ctx.translate(cx, cy - 6)
        ctx.scale(230 + 110 * r, 14 + 14 * r)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(1, 1, 1, 0.4 * (1 - r) * span(t, FILLS[-1], FILLS[-1] + 0.3))
        ctx.set_line_width(2)
        ctx.stroke()
    ctx.restore()


def shine(ctx, t):
    """Light running down the cascade on the closed logo, and over the pool on the button."""
    for k in range(beats.BASINS):
        y, w, d, face, _ = basin(k)
        for at in (SHINE, BUTTON):
            q = span(t, at + k * 0.045, at + k * 0.045 + 0.5)
            if 0 < q < 1:
                glint(ctx, CX + (0.3 if k % 2 else -0.3) * w, y + d + face, (10 + k) * math.sin(math.pi * q), q * 2,
                      math.sin(math.pi * q))


# ---------------------------------------------------------------- the drum circle

# x, the head's centre y, scale, kind, the drummer's skin and sleeve.
SEATS = ((140, 640, 1.4, (0.42, 0.28, 0.19), (0.95, 0.75, 0.15)),
         (362, 612, 1.15, (0.86, 0.66, 0.52), (0.2, 0.55, 0.62)),
         (552, 598, 1.05, (0.6, 0.4, 0.28), (0.85, 0.25, 0.3)),
         (728, 598, 1.05, (0.34, 0.22, 0.16), (0.35, 0.6, 0.25)),
         (918, 612, 1.15, (0.72, 0.52, 0.38), (0.55, 0.3, 0.65)),
         (1140, 640, 1.4, (0.5, 0.34, 0.24), (0.95, 0.45, 0.15)))
HITS = beats.meridian_hits()


@lru_cache(maxsize=None)
def hand_times(drum, hand):
    times = [at for at, d, h, _ in HITS if d == drum and h in (hand, beats.BOTH)]
    return times


@lru_cache(maxsize=None)
def drum_times(drum):
    return [(at, vel) for at, d, _, vel in HITS if d == drum]


def strike(t, times):
    """0 at rest above the head, 1 on it: down over 90 ms into each hit, back up over 160."""
    i = bisect.bisect_left(times, t)
    best = 0.0
    if i < len(times):
        best = ease_in(span(t, times[i] - 0.09, times[i]), 2)
    if i > 0:
        best = max(best, 1 - ease_out(span(t, times[i - 1], times[i - 1] + 0.16), 2))
    return best


def drum(ctx, t, i):
    x, y, s, _, _ = SEATS[i]
    kind = beats.DRUMS[i]
    rx, ry = (60 if kind == 'djembe' else 50) * s, (19 if kind == 'djembe' else 16) * s
    if kind == 'djembe':
        ctx.move_to(x - rx, y)
        ctx.curve_to(x - rx * 0.95, y + 70 * s, x - rx * 0.5, y + 100 * s, x - rx * 0.55, y + 140 * s)
        ctx.line_to(x - rx * 0.8, H + 20)
        ctx.line_to(x + rx * 0.8, H + 20)
        ctx.line_to(x + rx * 0.55, y + 140 * s)
        ctx.curve_to(x + rx * 0.5, y + 100 * s, x + rx * 0.95, y + 70 * s, x + rx, y)
        ctx.close_path()
        wood = cairo.LinearGradient(x - rx, 0, x + rx, 0)
        wood.add_color_stop_rgb(0, 0.36, 0.2, 0.1)
        wood.add_color_stop_rgb(0.4, 0.7, 0.44, 0.22)
        wood.add_color_stop_rgb(1, 0.3, 0.16, 0.08)
        inked(ctx, wood, 3, (0, 0))
        for k in range(12):                                       # the rope's zigzag
            u0, u1 = -1 + 2 * k / 12, -1 + 2 * (k + 0.5) / 12
            ctx.move_to(x + rx * 0.98 * u0, y + 12 * s)
            ctx.line_to(x + rx * 0.8 * u1, y + 64 * s)
            ctx.line_to(x + rx * 0.98 * (u0 + 2 / 12), y + 12 * s)
        ctx.set_source_rgb(0.95, 0.9, 0.8)
        ctx.set_line_width(2 * s)
        ctx.stroke()
        ctx.rectangle(x - rx * 0.86, y + 62 * s, rx * 1.72, 6 * s)
        ctx.set_source_rgb(0.95, 0.9, 0.8)
        ctx.fill()
    else:
        ctx.move_to(x - rx, y)
        ctx.curve_to(x - rx * 1.2, y + 90 * s, x - rx * 1.05, y + 160 * s, x - rx * 0.95, H + 20)
        ctx.line_to(x + rx * 0.95, H + 20)
        ctx.curve_to(x + rx * 1.05, y + 160 * s, x + rx * 1.2, y + 90 * s, x + rx, y)
        ctx.close_path()
        shell = cairo.LinearGradient(x - rx, 0, x + rx, 0)
        shell.add_color_stop_rgb(0, 0.45, 0.08, 0.05)
        shell.add_color_stop_rgb(0.45, 0.92, 0.42, 0.14)
        shell.add_color_stop_rgb(1, 0.4, 0.07, 0.04)
        inked(ctx, shell, 3, (0, 0))
        for lx in (-0.75, -0.25, 0.25, 0.75):                      # the tuning lugs
            rounded_rect(ctx, x + lx * rx - 4 * s, y + 8 * s, 8 * s, 36 * s, 3 * s)
            ctx.set_source_rgb(0.78, 0.78, 0.82)
            ctx.fill()
    ctx.save()                                                     # the rim and the head
    ctx.translate(x, y)
    ctx.scale(rx, ry)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    hit = 0.0
    for at, vel in drum_times(i):
        if at <= t:
            hit = max(hit, vel * pulse(t, at, 0.22))
    skin = cairo.RadialGradient(x - rx * 0.2, y - ry * 0.3, 0, x, y, rx)
    skin.add_color_stop_rgb(0, *mix((0.95, 0.88, 0.72), WHITE, 0.35 * hit))
    skin.add_color_stop_rgb(1, 0.76, 0.62, 0.44)
    inked(ctx, skin, 4 if kind == 'djembe' else 6, (0, 0))
    if hit > 0.05:                                                  # the stroke's ring
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(rx * (0.5 + 0.5 * (1 - hit)), ry * (0.5 + 0.5 * (1 - hit)))
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(1, 1, 1, 0.6 * hit)
        ctx.set_line_width(2.5)
        ctx.stroke()


def hands(ctx, t, i):
    """The drummer's arms in from the bottom of the frame, hands striking on the hits."""
    x, y, s, skin, sleeve = SEATS[i]
    for hand in (0, 1):
        side = -1 if hand == 0 else 1
        down = strike(t, hand_times(i, hand))
        idle = 3 * math.sin(TAU * t * 0.9 + i + hand)
        hx = x + side * 28 * s
        hy = y + 4 * s - (30 * s + idle) * (1 - down)
        ax, ay = x + side * 80 * s, H + 60
        ctx.move_to(ax, ay)
        ctx.curve_to(ax, ay - 80, hx + side * 26 * s, hy + 70 * s, hx + side * 4 * s, hy + 18 * s)
        inked_stroke(ctx, sleeve, 26 * s, (0, 0))
        palm(ctx, hx, hy, 1.15 * s, side, down, skin)


def palm(ctx, x, y, s, side, down, skin):
    """A hand seen from behind, fingers towards the drum's middle; flatter as it lands."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(side * 0.18)
    ctx.scale(s, s * (1 - 0.25 * down))
    ctx.rectangle(-8, 6, 16, 18)                                    # the wrist
    for fx, length in ((-9, 15), (-3, 18), (3, 18), (9, 14)):       # the fingers
        rounded_rect(ctx, fx - 3.2, -10 - length, 6.4, length + 8, 3.2)
    rounded_rect(ctx, -13, -14, 26, 25, 9)                          # the back of the hand
    ctx.save()
    ctx.translate(-side * 12, 0)                                    # the thumb, on the inside
    ctx.rotate(side * 0.8)
    rounded_rect(ctx, -3.6, -14, 7.2, 16, 3.6)
    ctx.restore()
    inked(ctx, skin, 2.2, (0, 0))
    ctx.move_to(-10, -9)                                            # the knuckles
    ctx.line_to(10, -9)
    ctx.set_source_rgba(*mix(skin, INK, 0.4), 0.6)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.restore()


def circle(ctx, t):
    for i in sorted(range(len(SEATS)), key=lambda i: SEATS[i][1]):
        drum(ctx, t, i)
        hands(ctx, t, i)


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.set_source_surface(park(), 0, 0)
    ctx.paint()
    cascade(ctx, t)
    shine(ctx, t)
    circle(ctx, t)
    neighborhood.tag(ctx, t, 'Meridian Hill Park', 'NORTHWEST  ·  WASHINGTON', *TAG)
    neighborhood.lockup(ctx, t, LOCKUP, 128, tint=0.6)
    ctx.set_source_rgba(1.0, 0.78, 0.4, 0.07)                     # the golden hour
    ctx.paint()
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.45)
    opening = 1 - ease_out(span(t, 0.0, 0.4))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    fade = span(t, *FADE)
    if fade > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(fade))
        ctx.paint()
