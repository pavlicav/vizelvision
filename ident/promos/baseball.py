"""Baseball on VizelVision: a ballpark at night, seen from high behind home plate. The
light banks bang on one by one, the organ plays the open logo, and the PA announces the
batter as the scoreboard spells it: NOW BATTING, No. 19, VIZELVISION. The pitch, the
crack of the bat, and the ball sails out over centre field into the scoreboard, which
bursts into HOME RUN! on the closed logo, with fireworks and the crowd on its feet. The
ribbon board under it carries the game on air (master's live text).

Aired only during an MLB game (LEAGUES). The PA is Jupiter, the Sports ID's baritone, with
the ballpark's echo: "Now batting... number nineteen... Vizzle Vision!"
"""
import math
import random
from functools import lru_cache

import cairo

from common import (INK, PINK, TAU, W, H, WHITE, YELLOW, back_out, clamp, ease_in, ease_in_out, ease_out, font,  # noqa: F401
                    glint, grain, inked, inked_stroke, mix, pulse, rounded_rect, span, vignette, PIXEL_FONT)

ID = 'baseball'
NAME = 'Baseball on VizelVision'
KIND = 'ident'
ORDER = 20
DESCRIPTION = ('Only during baseball: a night ballpark, the organ on the logo, the PA announcing No. 19, '
               'VizelVision, and a home run into the scoreboard on the closed logo, with fireworks. The ribbon '
               'board shows the game on air. Jupiter on the PA.')
DURATION = 10.0
STILL_AT = 8.6
LEAGUES = ('mlb',)

# Hit points (the music's too: promos/music.py).
BANKS_ON = (0.1, 0.3, 0.5, 0.7)                # the four light banks
ORGAN = 1.0                                     # the open logo on the organ
BOARD_ON = 0.9
NOW_BATTING = 1.9                               # the PA, and the board spelling it
NAME_AT = 3.9                                   # "...Vizzle Vision!" (the board's letters)
WINDUP = (4.75, 5.1)
RELEASE = 5.1
CONTACT = 5.5                                   # crack
FLIGHT = (5.5, 7.0)
HOME_RUN = 7.0                                  # the closed logo: into the scoreboard
FIREWORKS = (7.05, 7.3, 7.55, 8.05)
SIGN_OFF = 8.2                                  # VIZELVISION / CHANNEL 19 on the board
FADE = (9.25, 9.6)

HORIZON, CAMERA_H, CAMERA_D, FOCAL = 250, 22.0, 45.0, 900.0
BOARD = (420, 34, 440, 150)                     # the scoreboard: x, y, w, h
RIBBON = (430, 192, 420, 34)                    # the ribbon board under it
AMBER = (1.0, 0.72, 0.2)

OVERLAYS = [
    {'field': 'programme', 'box': [RIBBON[0] + 10, RIBBON[1] + 3, RIBBON[2] - 20, RIBBON[3] - 6],
     'from': BOARD_ON + 0.3, 'to': FADE[0] + 0.1,
     'style': {'font': 'Nimbus Sans Narrow', 'bold': True, 'size': 26, 'min_size': 13, 'color': list(AMBER),
               'upper': True, 'tracking': 0.08},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': 0.3}},
]


# ---------------------------------------------------------------- the camera

def project(u, v, z=0.0):
    """Field feet (u right of home plate, v towards centre field, z up) to the frame."""
    depth = v + CAMERA_D
    return W / 2 + FOCAL * u / depth, HORIZON + FOCAL * (CAMERA_H - z) / depth


def scale_at(v):
    return FOCAL / (v + CAMERA_D)


def polygon(ctx, points):
    ctx.move_to(*project(*points[0]))
    for p in points[1:]:
        ctx.line_to(*project(*p))
    ctx.close_path()


def arc_points(cu, cv, r, a0, a1, n=48):
    return [(cu + r * math.sin(a0 + (a1 - a0) * k / n), cv + r * math.cos(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def wall_distance(angle):
    """The fence: 330 ft down the lines, 400 to centre."""
    return 330 + 70 * math.cos(angle * 2) ** 0.8 if abs(angle) < math.pi / 4 else 330


# ---------------------------------------------------------------- the lights

def bank_level(t, i):
    on = BANKS_ON[i]
    if t < on:
        return 0.0
    p = span(t, on, on + 0.25)
    return 1.0 if p >= 1 else (0.5 + 0.5 * math.sin(p * 41) ** 2) * p ** 0.5


def lit(t):
    return sum(bank_level(t, i) for i in range(4)) / 4


BANK_PLACES = ((80, 74), (196, 104), (1200, 74), (1084, 104))


def sky(ctx, t):
    g = cairo.LinearGradient(0, 0, 0, HORIZON + 40)
    g.add_color_stop_rgb(0, 0.01, 0.015, 0.07)
    g.add_color_stop_rgb(0.7, 0.04, 0.07, 0.2)
    g.add_color_stop_rgb(1, 0.12, 0.13, 0.32)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(4)
    for _ in range(40):
        x, y = rand.uniform(0, W), rand.uniform(0, 160)
        ctx.arc(x, y, rand.uniform(0.6, 1.5), 0, TAU)
        ctx.set_source_rgba(1, 1, 1, rand.uniform(0.2, 0.7) * (1 - 0.7 * lit(t)))
        ctx.fill()
    level = lit(t)
    if level > 0:
        haze = cairo.RadialGradient(W / 2, HORIZON, 50, W / 2, HORIZON, 800)
        haze.add_color_stop_rgba(0, 0.8, 0.85, 1.0, 0.32 * level)
        haze.add_color_stop_rgba(1, 0.8, 0.85, 1.0, 0)
        ctx.set_source(haze)
        ctx.paint()


def towers(ctx, t):
    for i, (x, y) in enumerate(BANK_PLACES):
        if i % 2 == 0:                                   # one mast for each pair of banks
            ctx.move_to(x + (58 if x < W / 2 else -58) - 6, y + 20)
            ctx.line_to(x + (58 if x < W / 2 else -58) - 14, 262)
            ctx.line_to(x + (58 if x < W / 2 else -58) + 14, 262)
            ctx.line_to(x + (58 if x < W / 2 else -58) + 6, y + 20)
            ctx.close_path()
            ctx.set_source_rgb(0.1, 0.11, 0.19)
            ctx.fill()
    for i, (x, y) in enumerate(BANK_PLACES):
        level = bank_level(t, i)
        rounded_rect(ctx, x - 52, y - 22, 104, 44, 6)
        inked(ctx, (0.16, 0.17, 0.26), 4, (4, 4))
        lamp = mix((0.25, 0.26, 0.33), (1.0, 0.97, 0.86), level)
        for r in range(2):
            for c in range(4):
                ctx.arc(x - 36 + c * 24, y - 9 + r * 18, 7, 0, TAU)
                ctx.set_source_rgb(*lamp)
                ctx.fill()
        if level > 0:
            ctx.save()
            ctx.set_operator(cairo.OPERATOR_ADD)
            strike = pulse(t, BANKS_ON[i], 0.5)
            r = 120 + 220 * strike
            g = cairo.RadialGradient(x, y, 0, x, y, r)
            g.add_color_stop_rgba(0, 1, 0.97, 0.9, 0.5 * level + 0.35 * strike)
            g.add_color_stop_rgba(0.4, 1, 0.95, 0.85, 0.12 * level)
            g.add_color_stop_rgba(1, 1, 1, 1, 0)
            ctx.set_source(g)
            ctx.arc(x, y, r, 0, TAU)
            ctx.fill()
            ctx.restore()


# ---------------------------------------------------------------- the park

@lru_cache(maxsize=None)
def crowd_surface():
    """The bleachers beyond the fence: rows of fans, drawn once."""
    w, h = W, 70
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    ctx = cairo.Context(surface)
    rand = random.Random(19)
    shirts = ((0.85, 0.2, 0.25), (0.92, 0.92, 0.95), (0.2, 0.3, 0.75), (0.95, 0.75, 0.25), (0.55, 0.55, 0.65))
    ctx.set_source_rgb(0.1, 0.1, 0.16)
    ctx.paint()
    for row in range(3, h - 2, 5):
        x = rand.uniform(0, 4)
        while x < w:
            value = rand.uniform(0.35, 0.7)
            ctx.arc(x, row + rand.uniform(-1, 1), 1.9, 0, TAU)
            ctx.set_source_rgba(*(c * value for c in rand.choice(shirts)), 1)
            ctx.fill()
            x += rand.uniform(4, 6.5)
    return surface


def fence_points(z):
    n = 60
    return [(wall_distance(a) * math.sin(a), wall_distance(a) * math.cos(a), z)
            for a in (-math.pi / 4 - 0.25 + (math.pi / 2 + 0.5) * k / n for k in range(n + 1))]


def stands(ctx, t, frame):
    top = fence_points(10)
    ctx.save()
    ctx.move_to(0, 196)
    ctx.line_to(W, 196)
    for p in reversed(top):
        ctx.line_to(*project(*p))
    ctx.close_path()
    ctx.clip()
    ctx.set_source_surface(crowd_surface(), 0, 190)
    ctx.paint()
    ctx.set_source_rgba(0.02, 0.02, 0.08, 0.6 * (1 - lit(t)))
    ctx.paint()
    ctx.restore()
    storm = max(pulse(t, HOME_RUN, 1.6), 0.3 * pulse(t, CONTACT, 1.0))
    rand = random.Random(frame)
    for _ in range(int(2 + 40 * storm) if t > BANKS_ON[-1] else 0):
        glint(ctx, rand.uniform(10, W - 10), rand.uniform(200, 250), rand.uniform(4, 7), rand.random(), 0.9)


def field(ctx, t):
    # Outfield grass to the fence, in the mower's stripes (bands across the field).
    stripes = ((0.13, 0.46, 0.18), (0.1, 0.38, 0.15))
    fence = fence_points(0)
    ctx.save()
    ctx.move_to(-10, H + 10)
    for p in fence:
        ctx.line_to(*project(*p))
    ctx.line_to(W + 10, H + 10)
    ctx.close_path()
    ctx.clip()
    ctx.set_source_rgb(*stripes[0])
    ctx.paint()
    for k in range(0, 44, 2):
        v0, v1 = -20 + k * 10, -20 + (k + 1) * 10
        y0, y1 = project(0, v1)[1], project(0, v0)[1]
        ctx.rectangle(0, y0, W, y1 - y0)
    ctx.set_source_rgb(*stripes[1])
    ctx.fill()
    ctx.restore()
    # The fence: padded, with its yellow top and the distance at centre.
    top, bottom = fence_points(10), fence_points(0)
    polygon(ctx, top + list(reversed(bottom)))
    ctx.set_source_rgb(0.06, 0.25, 0.16)
    ctx.fill()
    ctx.move_to(*project(*top[0]))
    for p in top[1:]:
        ctx.line_to(*project(*p))
    ctx.set_source_rgb(*YELLOW)
    ctx.set_line_width(2.5)
    ctx.stroke()
    x, y = project(0, 400, 5)
    pixel_bulbs(ctx, '400', x, y - 6, 2.2, (0.95, 0.95, 0.9), None, align='center')
    # The infield: dirt in a wide arc round the mound, the grass square, the base paths.
    dirt = (0.62, 0.42, 0.26)
    arc = arc_points(0, 60.5, 95, math.pi / 4 + 0.12, -math.pi / 4 - 0.12)
    polygon(ctx, [(72, 56)] + arc + [(-72, 56)])              # the skin beyond the bases, out to the arc
    ctx.set_source_rgb(*dirt)
    ctx.fill()
    polygon(ctx, [(0, 8), (60, 63.6), (0, 119), (-60, 63.6)])
    ctx.set_source_rgb(*stripes[1])
    ctx.fill()
    for side in (-1, 1):                                       # the base paths, home to first and third
        polygon(ctx, [(side * 2.5, 2.5), (side * 64.6, 62.6), (side * 62.6, 64.6), (side * 0.5, 4.5)])
        ctx.set_source_rgb(*dirt)
        ctx.fill()
    for u, v, r in ((0, 59.5, 9), (0, 0, 13)):              # the mound, and round home plate
        polygon(ctx, arc_points(u, v, r, 0, TAU))
        ctx.set_source_rgb(*mix(dirt, (0.8, 0.6, 0.4), 0.25))
        ctx.fill()
    ctx.set_source_rgb(0.95, 0.95, 0.92)
    for side in (-1, 1):                                    # the foul lines
        a, b = project(0, 0), project(side * 330 * math.sin(math.pi / 4), 330 * math.cos(math.pi / 4))
        ctx.move_to(*a)
        ctx.line_to(*b)
        ctx.set_line_width(2)
        ctx.stroke()
    for u, v in ((63.6, 63.6), (0, 127.3), (-63.6, 63.6)):  # the bases
        polygon(ctx, [(u - 1.2, v - 1.2), (u + 1.2, v - 1.2), (u + 1.2, v + 1.2), (u - 1.2, v + 1.2)])
        ctx.fill()
    polygon(ctx, [(-0.7, 0.0), (0.7, 0.0), (0.7, -0.7), (0, -1.4), (-0.7, -0.7)])
    ctx.fill()
    ctx.set_line_width(2)
    for side in (-1, 1):                                    # the batter's boxes
        polygon(ctx, [(side * 1.2, -3), (side * 5.2, -3), (side * 5.2, 3), (side * 1.2, 3)])
        ctx.stroke()
    polygon(ctx, [(-0.9, 59.8), (0.9, 59.8), (0.9, 60.3), (-0.9, 60.3)])   # the rubber
    ctx.fill()


def darkness(ctx, t):
    amount = 0.75 * (1 - lit(t))
    if amount > 0:
        ctx.set_source_rgba(0, 0, 0.03, amount)
        ctx.paint()


# ---------------------------------------------------------------- the scoreboard

def pixel_bulbs(ctx, text, x, y, cell, on, off, align='left'):
    """text in the 5x7 face as bulbs, cell px apart; off bulbs drawn dim (or not, if None)."""
    width = (len(text) * 6 - 1) * cell
    if align == 'center':
        x -= width / 2
    for i, ch in enumerate(text.upper()):
        rows = PIXEL_FONT.get(ch, PIXEL_FONT['?']).split()
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == '1' or off:
                    ctx.arc(x + (i * 6 + c) * cell + cell / 2, y + r * cell + cell / 2, cell * 0.38, 0, TAU)
                    ctx.set_source_rgb(*(on if bit == '1' else off))
                    ctx.fill()
    return width


def board_lines(t):
    """What the scoreboard says now: two lines of up to 13 letters, and a blink."""
    if t < BOARD_ON:
        return '', '', False
    if t < NOW_BATTING:
        return 'VIZELVISION', 'BALLPARK', False
    if t < NAME_AT:
        return 'NOW BATTING', 'NO. 19', False
    if t < RELEASE + 0.42:
        name = 'VIZELVISION'
        return 'NO. 19', name[:max(1, int(len(name) * span(t, NAME_AT, NAME_AT + 0.7) + 0.999))], False
    if t < HOME_RUN:
        return 'VIZELVISION', '97 MPH', False
    if t < SIGN_OFF:
        return 'HOME RUN!', 'HOME RUN!', math.sin((t - HOME_RUN) * 26) < -0.2
    return 'VIZELVISION', 'CHANNEL 19', False


def scoreboard(ctx, t):
    x, y, w, h = BOARD
    for lx in (x + 70, x + w - 90):                          # its legs, down into the bleachers
        ctx.rectangle(lx, y + h, 20, 70)
    ctx.set_source_rgb(0.08, 0.09, 0.14)
    ctx.fill()
    rounded_rect(ctx, x, y, w, h, 8)
    inked(ctx, (0.05, 0.06, 0.1), 5, (5, 5))
    rounded_rect(ctx, x + 10, y + 10, w - 20, h - 20, 4)
    ctx.set_source_rgb(0.02, 0.02, 0.03)
    ctx.fill()
    on = span(t, BOARD_ON, BOARD_ON + 0.2)
    line1, line2, dark = board_lines(t)
    flare = pulse(t, HOME_RUN, 0.5)
    colour = mix(AMBER, WHITE, 0.3 + 0.7 * flare)
    if on > 0 and not dark:
        for text, row in ((line1, 0), (line2, 1)):
            pixel_bulbs(ctx, text, x + w / 2, y + 26 + row * 56, 6.0, mix((0.12, 0.08, 0.04), colour, on),
                        None, align='center')
    rx, ry, rw, rh = RIBBON                                  # the ribbon board: master writes the game on it
    rounded_rect(ctx, rx, ry, rw, rh, 4)
    inked(ctx, (0.02, 0.02, 0.03), 4, (4, 4))
    if flare > 0:
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        g = cairo.RadialGradient(x + w / 2, y + h / 2, 10, x + w / 2, y + h / 2, 400)
        g.add_color_stop_rgba(0, 1, 0.9, 0.7, 0.6 * flare)
        g.add_color_stop_rgba(1, 1, 0.9, 0.7, 0)
        ctx.set_source(g)
        ctx.paint()
        ctx.restore()


# ---------------------------------------------------------------- the players and the ball

def pitch_path(t):
    """The ball from release to the plate, then hit away over centre field: (u, v, z)."""
    if t < RELEASE:
        return None
    if t < CONTACT:
        p = span(t, RELEASE, CONTACT)
        return 1.5 - 1.2 * p, 55 - 54.5 * p, 6.2 - 3.6 * p - 0.6 * math.sin(math.pi * p)
    if t < FLIGHT[1]:
        s = span(t, *FLIGHT)
        return 0.3 + 5.7 * s, 0.5 + 479.5 * s ** 0.85, 2.6 + 241.2 * s - 139.8 * s * s   # a high fly, into the board
    return None


def ball(ctx, t):
    pose = pitch_path(t)
    if pose is None:
        return
    trail = [pitch_path(max(RELEASE, t - k * 0.012)) for k in range(14 if t >= CONTACT else 8)]
    for k, p in enumerate(reversed([p for p in trail if p])):
        x, y = project(*p)
        ctx.arc(x, y, max(1.5, 0.5 * scale_at(p[1])) * 0.9, 0, TAU)
        ctx.set_source_rgba(1, 1, 1, 0.08 + 0.06 * k)
        ctx.fill()
    x, y = project(*pose)
    r = max(3.6, 0.55 * scale_at(pose[1]))
    if t >= CONTACT:                                          # in flight: a glow, so the eye can follow it
        g = cairo.RadialGradient(x, y, 0, x, y, r * 5)
        g.add_color_stop_rgba(0, 1, 1, 0.9, 0.55)
        g.add_color_stop_rgba(1, 1, 1, 0.9, 0)
        ctx.set_source(g)
        ctx.arc(x, y, r * 5, 0, TAU)
        ctx.fill()
    ctx.arc(x, y, r, 0, TAU)
    ctx.set_source_rgb(0.98, 0.97, 0.94)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(max(1.0, r * 0.18))
    ctx.stroke()
    if r > 5:
        ctx.arc(x - r * 0.9, y, r * 0.7, -0.9, 0.9)
        ctx.arc_negative(x + r * 0.9, y, r * 0.7, math.pi + 0.9, math.pi - 0.9)
        ctx.set_source_rgb(0.85, 0.12, 0.15)
        ctx.set_line_width(max(1.0, r * 0.12))
        ctx.stroke()


def pitcher(ctx, t):
    """A small figure on the mound: set, the leg lift, the throw, the follow-through."""
    x, y = project(0.6, 60.5)
    s = scale_at(60.5) / 9.2
    lift = math.sin(math.pi * span(t, *WINDUP))
    throw = span(t, RELEASE - 0.08, RELEASE + 0.25)
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.move_to(-5, 0)                                       # the planted leg
    ctx.line_to(-2, -24)
    ctx.move_to(5 + 4 * lift, -18 * lift)                    # the other, lifted
    ctx.line_to(2, -24)
    inked_stroke(ctx, (0.92, 0.92, 0.9), 7, (0, 0))
    rounded_rect(ctx, -9, -50, 18, 28, 6)                    # the body
    inked(ctx, (0.92, 0.92, 0.9), 2.5, (0, 0))
    arm = -2.4 + 3.8 * ease_in(throw, 2) if t >= RELEASE - 0.08 else -0.4 - 1.6 * lift
    ctx.move_to(6, -44)
    ctx.line_to(6 + 18 * math.sin(arm), -44 - 18 * math.cos(arm))
    inked_stroke(ctx, (0.92, 0.92, 0.9), 5, (0, 0))
    ctx.arc(-9, -40, 5, 0, TAU)                              # the glove
    ctx.set_source_rgb(0.45, 0.25, 0.1)
    ctx.fill()
    ctx.arc(0, -58, 7, 0, TAU)                               # the head and cap
    ctx.set_source_rgb(0.85, 0.65, 0.5)
    ctx.fill()
    ctx.arc(0, -60, 7.5, math.pi, TAU)
    ctx.set_source_rgb(0.1, 0.15, 0.4)
    ctx.fill()
    ctx.restore()


def batter(ctx, t):
    """No. 19, from behind: a right-handed stance, the bat up; the swing through contact."""
    x, y = project(-3.2, 0.4)
    s = scale_at(0) * 6.2 / 127                              # six foot two
    swing = span(t, CONTACT - 0.12, CONTACT + 0.18)
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    turn = ease_in_out(swing)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for lx, foot in ((-14, -20), (12, 16)):                   # legs, apart
        ctx.move_to(lx * 0.4, -46)
        ctx.line_to(foot, 0)
        inked_stroke(ctx, (0.94, 0.94, 0.92), 13, (0, 0))
    for foot in (-20, 16):
        ctx.save()
        ctx.translate(foot, 0)
        ctx.scale(9, 4)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*INK)
        ctx.fill()
    ctx.save()                                               # the body, twisting through the swing
    ctx.translate(0, -70)
    ctx.scale(1 - 0.25 * math.sin(math.pi * turn), 1)
    rounded_rect(ctx, -22, -36, 44, 52, 14)
    inked(ctx, (0.94, 0.94, 0.92), 4, (0, 0))
    if turn < 0.5:
        font(ctx, 'URW Gothic', 26)
        ctx.move_to(-17, 2)
        ctx.text_path('19')
        ctx.set_source_rgb(0.1, 0.15, 0.4)
        ctx.fill()
        font(ctx, 'URW Gothic', 8)
        ctx.move_to(-14, -18)
        ctx.text_path('VIZEL')
        ctx.fill()
    ctx.restore()
    ctx.arc(0, -114, 13, 0, TAU)                             # the helmet
    inked(ctx, (0.1, 0.15, 0.4), 3, (0, 0))
    ctx.arc(-6, -118, 4, 0, TAU)
    ctx.set_source_rgba(1, 1, 1, 0.4)
    ctx.fill()
    # The bat: up behind the right shoulder in the stance, round through the zone, wrapped after.
    angle = -2.2 + (4.6 * ease_in(swing, 1.6) if swing < 1 else 4.6)
    hx, hy = 14 - 10 * turn, -88 + 6 * turn
    ctx.move_to(hx, hy)
    ctx.line_to(hx + 62 * math.sin(angle), hy - 62 * math.cos(angle))
    inked_stroke(ctx, (0.75, 0.5, 0.25), 7, (0, 0))
    ctx.arc(hx, hy, 7, 0, TAU)
    ctx.set_source_rgb(0.1, 0.15, 0.4)
    ctx.fill()
    ctx.restore()
    if 0 < t - CONTACT < 0.25:                                # the crack
        p = span(t, CONTACT, CONTACT + 0.25)
        bx, by = project(0.3, 0.5, 2.6)
        glint(ctx, bx, by, 40 * math.sin(math.pi * p), p * 3, 1 - p)


# ---------------------------------------------------------------- fireworks

@lru_cache(maxsize=None)
def sparks(k):
    rand = random.Random(k * 13 + 1)
    return [(rand.uniform(0, TAU), rand.uniform(0.6, 1.0)) for _ in range(46)]


def fireworks(ctx, t):
    colours = ((1, 0.3, 0.35), (1, 1, 1), (0.4, 0.6, 1), (1, 0.8, 0.3))
    places = ((300, 100), (985, 90), (365, 160), (930, 150))     # either side of the scoreboard
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for k, start in enumerate(FIREWORKS):
        p = span(t, start, start + 1.4)
        if not 0 < p < 1:
            continue
        cx, cy = places[k]
        radius = (90 + 40 * (k == 3)) * ease_out(p)
        fade = 1 - p
        for angle, speed in sparks(k):
            sx = cx + math.cos(angle) * radius * speed
            sy = cy + math.sin(angle) * radius * speed + 70 * p * p
            ctx.arc(sx, sy, 2.4 * (1 - 0.5 * p), 0, TAU)
            ctx.set_source_rgba(*colours[k], 0.9 * fade)
            ctx.fill()
        if p < 0.15:
            g = cairo.RadialGradient(cx, cy, 0, cx, cy, 80)
            g.add_color_stop_rgba(0, *colours[k], 0.6 * (1 - p / 0.15))
            g.add_color_stop_rgba(1, *colours[k], 0)
            ctx.set_source(g)
            ctx.paint()
    ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    sky(ctx, t)
    fireworks(ctx, t)
    towers(ctx, t)
    stands(ctx, t, frame)
    scoreboard(ctx, t)
    field(ctx, t)
    darkness(ctx, t)
    if t >= FLIGHT[0] + 0.7:                                  # far off, the ball flies over the park
        ball(ctx, t)
    pitcher(ctx, t)
    if t < FLIGHT[0] + 0.7:
        ball(ctx, t)
    batter(ctx, t)
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.35)
    opening = 1 - ease_out(span(t, 0.0, 0.3))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
