"""The VizelVision Sports ID picture, drawn frame by frame with cairo.

The station ID's world (animation.py) taken to the ballpark at night: the channel-change
snow; a dark stadium whose floodlight banks come on one by one; the stands, with camera
flashes going off; a turf field striped by the mower in place of the neon grid; sports
balls popping in, Memphis-style; the same chrome-and-teal TV emblem and wordmark; a
scoreboard marquee that spells out the line as it is read; a SPORTS banner that slams
in; the key change's shift to a golden, floodlit evening; and the iris-out.

    python3 sports_animation.py --still 17.7 frame.png     one frame, for checking
Frames for the encoder come from render(frame) (BGRx bytes); see build.py.
"""
import argparse
import math
import random
import sys
from functools import lru_cache
from pathlib import Path

import cairo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import animation as A  # noqa: E402  The ID's emblem, wordmark, ring, flare, iris and helpers.
import sports_timeline as T  # noqa: E402
from animation import (H, HORIZON, INK, ORANGE, TAU, W, WHITE, YELLOW, clamp, colour_shift, ease_in,  # noqa: E402
                       ease_in_out, ease_out, font, inked, inked_stroke, mix, pulse, rounded_rect, span)

RED = (0.93, 0.12, 0.22)
GOLD = (1.0, 0.76, 0.18)
LEATHER = (0.6, 0.29, 0.1)
AMBER = (1.0, 0.64, 0.12)
SKY_NIGHT = ((0.01, 0.015, 0.07), (0.03, 0.06, 0.2), (0.14, 0.15, 0.4))
SKY_GOLD = ((0.03, 0.04, 0.16), (0.12, 0.12, 0.4), (0.98, 0.56, 0.18))  # After the key change.
TURF = ((0.12, 0.44, 0.17), (0.09, 0.34, 0.13))  # The mower's two stripes.
TURF_GOLD = ((0.3, 0.46, 0.12), (0.24, 0.36, 0.09))
STANDS_TOP = HORIZON - 84

# The floodlight banks, in the order they come on: x, y, tilt.
BANKS = ((150, 74, 0.1), (1130, 74, -0.1), (420, 44, 0.05), (860, 44, -0.05))

BALLS = (  # x, y, kind, size, turn, spin, beat it pops on
    (115, 255, 'baseball', 42, 0.3, 0.4, 1),
    (1165, 250, 'football', 50, -0.5, -0.25, 3),
    (250, 400, 'basketball', 38, 0.0, 0.5, 5),
    (1035, 398, 'soccer', 36, 0.0, -0.45, 7),
    (95, 600, 'pennant', 58, 0.15, 0.08, 6.5),
    (1190, 605, 'puck', 34, 0.25, 0.0, 7.5),
    (300, 205, 'star', 24, 0.0, 0.7, 2),
    (985, 210, 'star', 20, 0.4, -0.6, 6),
)

# A 5x7 scoreboard face, for the marquee.
GLYPHS = {
    'A': ('01110', '10001', '10001', '11111', '10001', '10001', '10001'),
    'E': ('11111', '10000', '10000', '11110', '10000', '10000', '11111'),
    'F': ('11111', '10000', '10000', '11110', '10000', '10000', '10000'),
    'G': ('01110', '10001', '10000', '10111', '10001', '10001', '01111'),
    'H': ('10001', '10001', '10001', '11111', '10001', '10001', '10001'),
    'I': ('01110', '00100', '00100', '00100', '00100', '00100', '01110'),
    'L': ('10000', '10000', '10000', '10000', '10000', '10000', '11111'),
    'N': ('10001', '11001', '10101', '10011', '10001', '10001', '10001'),
    'O': ('01110', '10001', '10001', '10001', '10001', '10001', '01110'),
    'P': ('11110', '10001', '10001', '11110', '10000', '10000', '10000'),
    'R': ('11110', '10001', '10001', '11110', '10100', '10010', '10001'),
    'S': ('01111', '10000', '10000', '01110', '00001', '00001', '11110'),
    'T': ('11111', '00100', '00100', '00100', '00100', '00100', '00100'),
    'W': ('10001', '10001', '10001', '10101', '10101', '10101', '01010'),
}
MARQUEE_WORDS = 6  # THE FOLLOWING IS A PRESENTATION OF; the rest of the line is the wordmark and banner.
PITCH = 4.4        # Marquee dot spacing.
MARQUEE_Y = 642
BANNER_Y = 642


# ---------------------------------------------------------------- the lights

def bank_level(t, i):
    """0 before bank i comes on, then a flickering warm-up to 1."""
    on = T.LIGHTS[i]
    if t < on:
        return 0.0
    p = span(t, on, on + 0.3)
    return 1.0 if p >= 1 else (0.55 + 0.45 * math.sin(p * 37) ** 2) * p ** 0.5


def lit(t):
    return sum(bank_level(t, i) for i in range(len(BANKS))) / len(BANKS)


def sky(ctx, t):
    k = colour_shift(t)
    top, middle, horizon = (mix(a, b, k) for a, b in zip(SKY_NIGHT, SKY_GOLD))
    g = cairo.LinearGradient(0, 0, 0, HORIZON)
    g.add_color_stop_rgb(0, *top)
    g.add_color_stop_rgb(0.6, *middle)
    g.add_color_stop_rgb(1, *horizon)
    ctx.set_source(g)
    ctx.rectangle(0, 0, W, HORIZON)
    ctx.fill()
    # The floodlights' glow in the haze over the stadium, and behind the emblem.
    for x, y, r, a in ((W / 2, HORIZON - 40, 700, 0.3), (*A.EMBLEM, 380, 0.22)):
        glow = cairo.RadialGradient(x, y, 0, x, y, r)
        glow.add_color_stop_rgba(0, *mix((0.75, 0.85, 1.0), (1.0, 0.85, 0.55), k), a * lit(t))
        glow.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(glow)
        ctx.paint()


def towers(ctx):
    """The lattice masts under the banks, down behind the stands."""
    ctx.set_line_cap(cairo.LINE_CAP_BUTT)
    for x, y, _ in BANKS:
        top, bottom = y + 30, STANDS_TOP + 6
        half = 7
        ctx.move_to(x - half, top)
        ctx.line_to(x - half - 6, bottom)
        ctx.move_to(x + half, top)
        ctx.line_to(x + half + 6, bottom)
        steps = int((bottom - top) / 22)
        for s in range(steps):
            y0, y1 = top + s * 22, top + (s + 1) * 22
            w0, w1 = half + 6 * s / steps, half + 6 * (s + 1) / steps
            ctx.move_to(x - w0, y0)
            ctx.line_to(x + w1, y1)
        ctx.set_source_rgba(0.12, 0.13, 0.22, 1)
        ctx.set_line_width(3)
        ctx.stroke()


def banks(ctx, t):
    for i, (x, y, tilt) in enumerate(BANKS):
        level = bank_level(t, i)
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(tilt)
        rounded_rect(ctx, -78, -34, 156, 68, 10)
        inked(ctx, (0.16, 0.17, 0.26), 5, (5, 5))
        lamp = mix((0.24, 0.25, 0.32), (1.0, 0.97, 0.86), level)
        for r in range(3):
            for c in range(5):
                ctx.arc(-56 + c * 28, -18 + r * 18, 8, 0, TAU)
                ctx.set_source_rgb(*lamp)
                ctx.fill()
        ctx.restore()
        if level <= 0:
            continue
        # Bloom: strong as the bank strikes, then a steady halo.
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        strike = pulse(t, T.LIGHTS[i], 0.6)
        r = 150 + 260 * strike
        halo = cairo.RadialGradient(x, y, 0, x, y, r)
        halo.add_color_stop_rgba(0, 1, 0.97, 0.9, 0.55 * level + 0.35 * strike)
        halo.add_color_stop_rgba(0.35, 1, 0.95, 0.85, 0.18 * level)
        halo.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(halo)
        ctx.arc(x, y, r, 0, TAU)
        ctx.fill()
        ctx.restore()


def beams(ctx, t):
    """Each bank's light falling across the field, swaying a little."""
    k = colour_shift(t)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for i, (x, y, _) in enumerate(BANKS):
        level = bank_level(t, i)
        if level <= 0:
            continue
        aim = W / 2 - (x - W / 2) * 0.35 + 50 * math.sin(0.45 * t + i * 1.9)
        spread = 190 + 25 * math.sin(0.3 * t + i)
        ctx.move_to(x - 30, y + 20)
        ctx.line_to(x + 30, y + 20)
        ctx.line_to(aim + spread, H + 40)
        ctx.line_to(aim - spread, H + 40)
        ctx.close_path()
        g = cairo.LinearGradient(x, y, aim, H)
        g.add_color_stop_rgba(0, *mix((0.8, 0.88, 1.0), (1.0, 0.9, 0.6), k), 0.16 * level)
        g.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(g)
        ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the stadium

@lru_cache(maxsize=None)
def stands_surface():
    """The bowl behind the field: three tiers of fans, drawn once."""
    h = HORIZON - STANDS_TOP
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, h)
    ctx = cairo.Context(surface)
    rand = random.Random(1958)
    shirts = ((0.85, 0.25, 0.3), (0.9, 0.9, 0.95), (0.25, 0.35, 0.8), (0.95, 0.75, 0.3), (0.6, 0.6, 0.7))
    for y0, y1, shade in ((0, 26, 0.09), (28, 54, 0.12), (56, h, 0.16)):
        ctx.rectangle(0, y0, W, y1 - y0)
        ctx.set_source_rgb(shade * 0.8, shade * 0.8, shade * 1.5)
        ctx.fill()
        for row in range(y0 + 4, y1 - 1, 5):
            x = rand.uniform(0, 4)
            while x < W:
                value = rand.uniform(0.3, 0.65)
                ctx.arc(x, row + rand.uniform(-1, 1), 1.9, 0, TAU)
                ctx.set_source_rgba(*(c * value for c in rand.choice(shirts)), 0.95)
                ctx.fill()
                x += rand.uniform(4.2, 6.5)
    ctx.set_line_width(2)
    for y in (27, 55, h - 1):  # The tiers' rails.
        ctx.move_to(0, y)
        ctx.line_to(W, y)
    ctx.set_source_rgba(0.75, 0.8, 1.0, 0.4)
    ctx.stroke()
    return surface


def stands(ctx):
    ctx.set_source_surface(stands_surface(), 0, STANDS_TOP)
    ctx.paint()


def flashbulbs(ctx, t, frame):
    """Camera flashes in the stands: a few always, a storm on the hits."""
    if t < T.LIGHTS[0]:
        return
    storm = max(pulse(t, T.HIT, 1.4), pulse(t, T.BANNER, 1.2), pulse(t, T.KEY_CHANGE, 1.2), pulse(t, T.BUTTON, 1.6))
    rate = 5 + 70 * storm  # Flashes a second.
    for age in range(3):
        rand = random.Random(frame - age)
        count = int(rate / T.FPS) + (rand.random() < (rate / T.FPS) % 1)
        for _ in range(count):
            x, y = rand.uniform(10, W - 10), rand.uniform(STANDS_TOP + 4, HORIZON - 4)
            A.glint(ctx, x, y, rand.uniform(5, 9), rand.uniform(0, 1), (1.0, 0.55, 0.2)[age])


def scroll(t):
    """How far the field has rolled towards us: steady, faster through the build, never jumping."""
    p = span(t, T.BUILD, T.KEY_CHANGE)
    return 1.6 * t + 2.5 * ((T.KEY_CHANGE - T.BUILD) / 3 * p ** 3 + max(0.0, t - T.KEY_CHANGE))


def field(ctx, t):
    """Turf with the mower's stripes and chalk lines, rolling towards the camera."""
    k = colour_shift(t)
    stripes = [mix(a, b, k) for a, b in zip(TURF, TURF_GOLD)]
    s = scroll(t)
    whole, frac = math.floor(s), s % 1.0
    ctx.rectangle(0, HORIZON, W, H - HORIZON)
    ctx.set_source_rgb(*mix(stripes[1], (0.35, 0.4, 0.5), 0.5))
    ctx.fill()
    lines = []
    for j in range(60, -1, -1):  # Far to near.
        z = j + 1 - frac
        if z < 0.8:
            continue
        lines.append((HORIZON + 250 / z, j + whole, z))
    lines.append((H + 40, None, 0.8))
    for (y0, index, z), (y1, _, _) in zip(lines, lines[1:]):
        if y0 > H:
            break
        fog = clamp(1 - 6 / z)  # Distant stripes fade into the haze.
        ctx.rectangle(0, y0, W, y1 - y0)
        ctx.set_source_rgb(*mix(stripes[index % 2], (0.45, 0.5, 0.55), 0.6 * fog))
        ctx.fill()
    for y, index, z in lines[:-1]:
        if y > H + 4:
            continue
        ctx.move_to(0, y)
        ctx.line_to(W, y)
        ctx.set_source_rgba(1, 1, 1, clamp(0.7 / z ** 0.6) * (1.0 if index % 5 == 0 else 0.45))
        ctx.set_line_width(max(1.0, (4.5 if index % 5 == 0 else 2.6) / z))
        ctx.stroke()
    ctx.set_line_cap(cairo.LINE_CAP_BUTT)
    for i in range(-14, 15):  # The ID's neon grid, faint, as the field's lanes.
        ctx.move_to(W / 2 + i * 22, HORIZON)
        ctx.line_to(W / 2 + i * 190, H + 40)
    ctx.set_source_rgba(*mix((0.6, 1.0, 0.45), (1.0, 0.9, 0.5), k), 0.16)
    ctx.set_line_width(2)
    ctx.stroke()
    haze = cairo.LinearGradient(0, HORIZON - 20, 0, HORIZON + 50)
    haze.add_color_stop_rgba(0, 1, 1, 1, 0)
    haze.add_color_stop_rgba(0.3, *mix((0.85, 0.9, 1.0), (1, 0.9, 0.6), k), 0.5)
    haze.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(haze)
    ctx.rectangle(0, HORIZON - 20, W, 70)
    ctx.fill()


def darkness(ctx, t):
    """Before the floodlights, the stadium is dark."""
    amount = 0.78 * (1 - lit(t))
    if amount > 0:
        ctx.set_source_rgba(0.0, 0.0, 0.02, amount)
        ctx.paint()


# ---------------------------------------------------------------- the balls

def pentagon(ctx, x, y, r, rotation=-TAU / 4):
    for i in range(5):
        a = rotation + i * TAU / 5
        (ctx.move_to if i == 0 else ctx.line_to)(x + math.cos(a) * r, y + math.sin(a) * r)
    ctx.close_path()


def star5(ctx, r, inner=0.45):
    for i in range(10):
        a = -TAU / 4 + i * TAU / 10
        radius = r if i % 2 == 0 else r * inner
        (ctx.move_to if i == 0 else ctx.line_to)(math.cos(a) * radius, math.sin(a) * radius)
    ctx.close_path()


def stitches(ctx, side, s):
    """A baseball's seam: a curve with its red stitches."""
    p = ((side * 0.42 * s, -0.88 * s), (side * 0.02 * s, -0.32 * s), (side * 0.02 * s, 0.32 * s),
         (side * 0.42 * s, 0.88 * s))
    ctx.move_to(*p[0])
    ctx.curve_to(*p[1], *p[2], *p[3])
    ctx.set_source_rgb(*RED)
    ctx.set_line_width(2.5)
    ctx.stroke()
    for k in range(1, 9):
        u = k / 9
        x = sum(c * pt[0] for c, pt in zip(((1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3), p))
        y = sum(c * pt[1] for c, pt in zip(((1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3), p))
        dx = 3 * ((1 - u) ** 2 * (p[1][0] - p[0][0]) + 2 * u * (1 - u) * (p[2][0] - p[1][0]) + u * u * (p[3][0] - p[2][0]))
        dy = 3 * ((1 - u) ** 2 * (p[1][1] - p[0][1]) + 2 * u * (1 - u) * (p[2][1] - p[1][1]) + u * u * (p[3][1] - p[2][1]))
        length = math.hypot(dx, dy) or 1
        tx, ty = dx / length, dy / length
        for n in (-1, 1):
            nx, ny = -ty * n, tx * n
            ctx.move_to(x + nx * 1.5, y + ny * 1.5)
            ctx.line_to(x + nx * 7 - tx * 3, y + ny * 7 - ty * 3)
    ctx.set_line_width(2.2)
    ctx.stroke()


def ball(ctx, kind, s):
    if kind == 'baseball':
        ctx.arc(0, 0, s, 0, TAU)
        inked(ctx, (0.98, 0.97, 0.92), 5, (6, 6))
        for side in (-1, 1):
            stitches(ctx, side, s)
    elif kind == 'football':
        ctx.save()
        ctx.scale(1, 0.6)
        ctx.arc(0, 0, s, 0, TAU)
        ctx.restore()
        inked(ctx, LEATHER, 5, (6, 6))
        ctx.set_source_rgb(*WHITE)
        for x in (-0.62 * s, 0.62 * s):  # The stripes near the tips.
            ctx.move_to(x, -0.36 * s)
            ctx.line_to(x, 0.36 * s)
        ctx.set_line_width(5)
        ctx.stroke()
        ctx.move_to(-0.32 * s, 0)
        ctx.line_to(0.32 * s, 0)
        for k in range(5):
            x = -0.24 * s + k * 0.12 * s
            ctx.move_to(x, -0.1 * s)
            ctx.line_to(x, 0.1 * s)
        ctx.set_line_width(3)
        ctx.stroke()
    elif kind == 'basketball':
        ctx.arc(0, 0, s, 0, TAU)
        inked(ctx, ORANGE, 5, (6, 6))
        ctx.save()
        ctx.arc(0, 0, s, 0, TAU)
        ctx.clip()
        ctx.move_to(0, -s)
        ctx.line_to(0, s)
        ctx.move_to(-s, 0)
        ctx.line_to(s, 0)
        for side in (-1, 1):
            ctx.new_sub_path()
            ctx.arc(side * 1.25 * s, 0, 0.85 * s, 0, TAU)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(3.5)
        ctx.stroke()
        ctx.restore()
    elif kind == 'soccer':
        ctx.arc(0, 0, s, 0, TAU)
        inked(ctx, (0.98, 0.98, 0.98), 5, (6, 6))
        ctx.save()
        ctx.arc(0, 0, s, 0, TAU)
        ctx.clip()
        ctx.set_source_rgb(*INK)
        pentagon(ctx, 0, 0, 0.34 * s)
        ctx.fill()
        for i in range(5):
            # Each seam runs out from a corner of the middle patch to a patch at the rim,
            # with the seams between the white hexagons either side of it.
            a = -TAU / 4 + i * TAU / 5
            ctx.move_to(math.cos(a) * 0.34 * s, math.sin(a) * 0.34 * s)
            ctx.line_to(math.cos(a) * 0.7 * s, math.sin(a) * 0.7 * s)
            for side in (-1, 1):
                b = a + side * TAU / 10
                ctx.move_to(math.cos(a) * 0.7 * s, math.sin(a) * 0.7 * s)
                ctx.line_to(math.cos(b) * 0.82 * s, math.sin(b) * 0.82 * s)
                ctx.line_to(math.cos(b) * 1.1 * s, math.sin(b) * 1.1 * s)
            ctx.set_line_width(3)
            ctx.stroke()
            pentagon(ctx, math.cos(a) * 1.02 * s, math.sin(a) * 1.02 * s, 0.34 * s, a + math.pi)
            ctx.fill()
        ctx.restore()
        ctx.arc(0, 0, s, 0, TAU)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(5)
        ctx.stroke()
    elif kind == 'puck':
        h, squash = 0.38 * s, 0.42
        ctx.move_to(-s, 0)
        ctx.line_to(-s, h)
        ctx.save()
        ctx.translate(0, h)
        ctx.scale(1, squash)
        ctx.arc_negative(0, 0, s, math.pi, 0)
        ctx.restore()
        ctx.line_to(s, 0)
        ctx.save()
        ctx.scale(1, squash)
        ctx.arc_negative(0, 0, s, 0, -math.pi)
        ctx.restore()
        ctx.close_path()
        inked(ctx, (0.13, 0.13, 0.17), 5, (6, 6))
        ctx.save()
        ctx.scale(1, squash)
        ctx.arc(0, 0, s, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(0.26, 0.26, 0.32)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(4)
        ctx.stroke()
        ctx.save()
        ctx.scale(1, squash)
        ctx.arc(0, 0, 0.7 * s, TAU * 0.55, TAU * 0.8)
        ctx.restore()
        ctx.set_source_rgba(1, 1, 1, 0.5)
        ctx.set_line_width(3)
        ctx.stroke()
    elif kind == 'pennant':
        ctx.move_to(-0.7 * s, -0.95 * s)
        ctx.line_to(-0.7 * s, 0.95 * s)
        inked_stroke(ctx, (0.85, 0.86, 0.92), 5, (4, 4))
        ctx.move_to(-0.66 * s, -0.88 * s)
        ctx.line_to(0.98 * s, -0.46 * s)
        ctx.line_to(-0.66 * s, -0.04 * s)
        ctx.close_path()
        inked(ctx, RED, 5, (6, 6))
        ctx.move_to(-0.44 * s, -0.8 * s)
        ctx.line_to(-0.44 * s, -0.12 * s)
        ctx.set_source_rgb(*GOLD)
        ctx.set_line_width(8)
        ctx.stroke()
    elif kind == 'star':
        star5(ctx, s)
        inked(ctx, YELLOW, 4, (5, 5))


def balls(ctx, t):
    build = max(0.0, min(t, T.KEY_CHANGE) - T.BUILD) ** 2 / 4 + max(0.0, t - T.KEY_CHANGE)
    for i, (x, y, kind, size, turn, spin, beat) in enumerate(BALLS):
        pop = span(t, T.beat(beat), T.beat(beat) + 0.45)
        if pop <= 0:
            continue
        scale = A.back_out(pop, 2.6) * (1 + 0.1 * max(pulse(t, T.CLAPS[0] + 0.5 * (i % 4) * T.BEAT, 0.25),
                                                       pulse(t, T.CLAPS[1] + 0.5 * (i % 4) * T.BEAT, 0.25)))
        ctx.save()
        ctx.translate(x + 14 * math.sin(0.7 * t + i * 1.7), y + 10 * math.cos(0.9 * t + i * 2.3))
        ctx.rotate(turn + spin * t + 1.4 * spin * build + (1 - pop) * 2.5)
        ctx.scale(scale, scale)
        ball(ctx, kind, size)
        ctx.restore()


# ---------------------------------------------------------------- the marquee and banner

@lru_cache(maxsize=None)
def marquee_layout():
    """(column, row, word) for each dot of the marquee's words, and its width in columns."""
    dots, col = [], 0
    for word_index, (word, _, _) in enumerate(T.WORDS[:MARQUEE_WORDS]):
        for letter_index, ch in enumerate(word):
            for row, bits in enumerate(GLYPHS[ch]):
                dots.extend((col + c, row, word_index, letter_index) for c, bit in enumerate(bits) if bit == '1')
            col += 6
        col += 3
    return dots, col - 4


def letter_lit(t, word_index, letter_index):
    """When a marquee letter lights: through its word as it is said."""
    word, start, end = T.WORDS[word_index]
    return start + (end - start) * 0.8 * letter_index / len(word)


def marquee(ctx, t):
    """A scoreboard panel spelling out the line, word by word as it is read."""
    if t < T.MARQUEE or t >= T.BANNER:
        return
    dots, columns = marquee_layout()
    width, height = columns * PITCH, 7 * PITCH
    rise = ease_out(span(t, T.MARQUEE, T.MARQUEE + 0.35))
    fold = 1 - ease_in(span(t, T.BANNER - 0.14, T.BANNER))
    ctx.save()
    ctx.translate(W / 2, MARQUEE_Y + 50 * (1 - rise))
    ctx.scale(1, fold)
    ctx.push_group()
    rounded_rect(ctx, -width / 2 - 20, -height / 2 - 12, width + 40, height + 24, 10)
    inked(ctx, (0.07, 0.06, 0.1), 5, (6, 6))
    x0, y0 = -width / 2 + PITCH / 2, -height / 2 + PITCH / 2
    ctx.set_source_rgba(*AMBER, 0.13)
    for c in range(columns):
        for r in range(7):
            ctx.new_sub_path()
            ctx.arc(x0 + c * PITCH, y0 + r * PITCH, 1.5, 0, TAU)
    ctx.fill()
    flash = pulse(t, T.WORDS[-1][1], 0.5)  # "Sports": the whole board flashes.
    lit_dots, fresh = [], []
    for c, r, word_index, letter_index in dots:
        when = letter_lit(t, word_index, letter_index)
        if t >= when:
            (fresh if t - when < 0.12 else lit_dots).append((x0 + c * PITCH, y0 + r * PITCH))
    for points, colour, radius, glow in ((lit_dots, mix(AMBER, WHITE, flash * 0.7), 1.8, 0.28),
                                         (fresh, (1, 0.95, 0.8), 2.0, 0.45)):
        if not points:
            continue
        ctx.set_source_rgba(*colour, glow)
        for x, y in points:
            ctx.new_sub_path()
            ctx.arc(x, y, radius * 2.2, 0, TAU)
        ctx.fill()
        ctx.set_source_rgb(*colour)
        for x, y in points:
            ctx.new_sub_path()
            ctx.arc(x, y, radius, 0, TAU)
        ctx.fill()
    # Chase lights round the frame once the brand is said.
    chase = t >= T.WORDS[MARQUEE_WORDS][1]
    perimeter = []
    left, top, right, bottom = -width / 2 - 10, -height / 2 - 4, width / 2 + 10, height / 2 + 4
    for k in range(int((right - left) / 16) + 1):
        perimeter.append((left + k * 16, top - 2))
    for k in range(int((right - left) / 16) + 1):
        perimeter.append((right - k * 16, bottom + 2))
    for k, (x, y) in enumerate(perimeter):
        on = chase and (k + int(t * 24)) % 4 == 0
        ctx.arc(x, y, 1.8, 0, TAU)
        ctx.set_source_rgba(*(WHITE if on else AMBER), 1.0 if on else 0.2)
        ctx.fill()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(ease_out(clamp(rise * 1.5)))
    ctx.restore()


def banner(ctx, t):
    """SPORTS, on a slanted red banner with gold piping, slamming in under the wordmark."""
    p = span(t, T.BANNER - 0.2, T.BANNER)
    if p <= 0:
        return
    font(ctx, 'Nimbus Sans Narrow', 82, italic=True)
    text, tracking = 'SPORTS', 9
    advances = [ctx.text_extents(ch).x_advance + tracking for ch in text]
    text_width = sum(advances) - tracking
    half_w, half_h, skew = text_width / 2 + 50, 37, 16
    zoom = 1 + 2.4 * (1 - ease_in(p, 2))
    impact = pulse(t, T.BANNER, 0.2)
    bounce = (math.sin(clamp((t - T.KEY_CHANGE - 0.3) / 0.32) * math.pi) * 14
              + math.sin(clamp((t - T.BUTTON - 0.2) / 0.4) * math.pi) * 22)
    ctx.save()
    ctx.translate(W / 2, BANNER_Y - bounce)
    ctx.scale(zoom * (1 + 0.1 * impact), zoom * (1 - 0.16 * impact))
    ctx.rotate((1 - p) * -0.3)
    if p < 1:
        ctx.push_group()
    # Speed lines trailing off to the left as it lands.
    trail = 1 - span(t, T.BANNER, T.BANNER + 0.6)
    if trail > 0 and p >= 1:
        for k, dy in enumerate((-22, 0, 22)):
            ctx.move_to(-half_w - 30 - 20 * k, dy)
            ctx.line_to(-half_w - 30 - 20 * k - 160 * trail, dy)
        inked_stroke(ctx, WHITE, 6, (4, 4))
    k = colour_shift(t)
    ctx.move_to(-half_w + skew, -half_h)
    ctx.line_to(half_w + skew, -half_h)
    ctx.line_to(half_w - skew, half_h)
    ctx.line_to(-half_w - skew, half_h)
    ctx.close_path()
    face = cairo.LinearGradient(0, -half_h, 0, half_h)
    face.add_color_stop_rgb(0, *mix(mix(RED, WHITE, 0.25), (1.0, 0.45, 0.3), k * 0.3))
    face.add_color_stop_rgb(0.55, *RED)
    face.add_color_stop_rgb(1, *mix(RED, INK, 0.3))
    inked(ctx, face, 6, (8, 8))
    for y in (-half_h + 8, half_h - 8):  # Gold piping.
        offset = skew * y / half_h
        ctx.move_to(-half_w + 12 + offset, y)
        ctx.line_to(half_w - 12 + offset, y)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(4)
    ctx.stroke()
    x = -text_width / 2
    for ch, advance in zip(text, advances):
        ctx.move_to(x, 29)
        ctx.text_path(ch)
        x += advance
    shine = cairo.LinearGradient(0, -30, 0, 29)
    shine.add_color_stop_rgb(0, 1, 1, 1)
    shine.add_color_stop_rgb(1, *mix(WHITE, GOLD, 0.35))
    inked(ctx, shine, 4, (5, 5), fatten=4)
    sweep = span(t, T.BUTTON + 0.1, T.BUTTON + 0.8)
    if 0 < sweep < 1:  # A glint runs across the banner on the button.
        sx = -half_w + 2 * half_w * ease_in_out(sweep)
        ctx.save()
        ctx.move_to(-half_w + skew, -half_h)
        ctx.line_to(half_w + skew, -half_h)
        ctx.line_to(half_w - skew, half_h)
        ctx.line_to(-half_w - skew, half_h)
        ctx.close_path()
        ctx.clip()
        band = cairo.LinearGradient(sx - 50, 0, sx + 50, 0)
        band.add_color_stop_rgba(0, 1, 1, 1, 0)
        band.add_color_stop_rgba(0.5, 1, 1, 1, 0.6)
        band.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(band)
        ctx.paint()
        ctx.restore()
    if p < 1:
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_out(clamp(p * 2.5)))
    ctx.restore()


# ---------------------------------------------------------------- frames

def camera(ctx, t):
    """The ID's camera: shake on the hits (and on SPORTS), a slow push through the build."""
    shake = max(pulse(t, T.HIT, 0.3), 0.7 * pulse(t, T.BANNER, 0.25), pulse(t, T.KEY_CHANGE, 0.25),
                pulse(t, T.BUTTON, 0.35))
    zoom = 1 + 0.045 * ease_in_out(span(t, T.BUILD, T.KEY_CHANGE)) \
        - 0.045 * ease_in_out(span(t, T.KEY_CHANGE, T.KEY_CHANGE + 0.8))
    ctx.translate(W / 2 + math.sin(t * 91) * 9 * shake, H / 2 + math.cos(t * 77) * 7 * shake)
    ctx.scale(zoom, zoom)
    ctx.translate(-W / 2, -H / 2)


def flash(ctx, t):
    amount = max(0.85 * pulse(t, T.HIT, 0.35), 0.45 * pulse(t, T.BANNER, 0.25),
                 0.55 * pulse(t, T.KEY_CHANGE, 0.3), 0.9 * pulse(t, T.BUTTON, 0.4))
    if amount > 0:
        ctx.set_source_rgba(1, 1, 1, amount)
        ctx.paint()


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= T.BLACK:
        return
    ctx.save()
    camera(ctx, t)
    ctx.rectangle(-40, -40, W + 80, H + 80)
    ctx.clip()
    sky(ctx, t)
    towers(ctx)
    stands(ctx)
    field(ctx, t)
    darkness(ctx, t)
    flashbulbs(ctx, t, frame)
    beams(ctx, t)
    banks(ctx, t)
    balls(ctx, t)
    A.ring(ctx, t, front=False)
    A.emblem(ctx, t)
    A.ring(ctx, t, front=True)
    A.wordmark(ctx, t)
    marquee(ctx, t)
    banner(ctx, t)
    A.flare(ctx, t)
    A.burst(ctx, t)
    ctx.restore()
    flash(ctx, t)
    ctx.set_source_surface(A.overlay(), 0, 0)
    ctx.paint()
    A.static(ctx, t, frame)
    A.iris(ctx, t)


def frames():
    return round(T.DURATION * T.FPS)


def render(frame):
    """One frame as raw BGRx bytes (ffmpeg pix_fmt bgr0)."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    draw(cairo.Context(surface), frame / T.FPS, frame)
    surface.flush()
    return bytes(surface.get_data())


def still(t, path):
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    draw(cairo.Context(surface), t, int(t * T.FPS))
    surface.write_to_png(str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Draw one frame of the Sports ID')
    parser.add_argument('--still', type=float, required=True, metavar='SECONDS')
    parser.add_argument('out', type=Path)
    args = parser.parse_args(argv)
    still(args.still, args.out)


if __name__ == '__main__':
    main()
