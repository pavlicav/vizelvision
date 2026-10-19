"""Orange Cat Behavior No. 4, The Field Goal: a nature documentary. Game day in the living
room. A football stands on its kicking tee on the rug beside the orange cat; across the
room, the teal TV's rabbit ears make a fine pair of uprights. The cat considers the ball,
considers you, and lines up the kick. It taps the ball once on each of the first three
notes of the open logo (it rocks on the tee), and on the fourth swats it: end over end,
across the room, between the rabbit ears and down behind the set. The screen: IT'S GOOD!
The cat sits up with both paws raised, a referee's signal. Somewhere behind the TV,
something breaks. VIZELVISION FOOTBALL wipes in on the closed logo, a mrrp, a slow blink.

Aired only during an NFL or college game (LEAGUES). The narrator is Draco: "The orange
cat... attempts the field goal." / "It is good."
"""
import math

import cairo

import cats
import only_on as O
from common import (INK, PINK, TAU, W, WHITE, YELLOW, A, back_out, ease_in, ease_in_out, ease_out, glint,  # noqa: F401
                    grain, inked, iris, mix, pixel_text, pulse, span, vignette)

ID = 'cat-field-goal'
NAME = 'Orange Cat Behavior: The Field Goal'
KIND = 'ident'
ORDER = 23
DESCRIPTION = ('Only during football, a nature documentary: the orange cat taps a football on its tee once on '
               "each note of the logo, then kicks it through the TV's rabbit ears. It is good; the cat signals it, "
               'paws up. Narrated by Draco.')
DURATION = 10.0
STILL_AT = 5.9
LEAGUES = ('nfl', 'ncaaf')
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
IRIS_OPEN = (0.0, 0.45)
CAPTION = (0.4, 2.6)
LOOKS = ((0.6, 1.0), (1.35, 0.0), (2.2, 1.0))    # (when, gaze): the ball, you, the uprights
TAPS = (3.0, 3.25, 3.5)                          # the open logo's first three notes: a tap each
KICK = 4.0                                       # the fourth: the swat
FLIGHT = (4.02, 4.72)                            # end over end, through the ears, behind the set
THROUGH = 4.6                                    # between the rabbit ears
GOOD = 4.65                                      # the screen: IT'S GOOD!
ARMS = (4.95, 5.25)                              # paws up...
CRASH = 5.75                                     # something, behind the TV
GLANCE = (5.9, 6.25)                             # a look that way, and back
ARMS_DOWN = (6.45, 6.75)                         # ...and down
BANNER = 7.0                                     # the closed logo
MRRP = 8.0
BLINK = (8.35, 8.9)
IRIS_CLOSE = (9.2, 9.6)

SEAT = (330, O.FLOOR)
TEE = (468, O.FLOOR + 6)                         # the tee's foot
CABINET = O.CABINET                              # (755, 334, 390, 270)
EARS = (CABINET[0] + CABINET[2] - 75, CABINET[1] - 4)    # where the rabbit ears meet
# The kick: a quadratic Bezier from the tee, through the ears, down behind the set.
ARC = ((468, O.FLOOR - 54), (1020, -160), (1120, 440))
BEHIND = 0.86                                    # how far along it the ball is past the ears
LEATHER = (0.55, 0.27, 0.12)


# ---------------------------------------------------------------- the ball

def bezier(u):
    (x0, y0), (x1, y1), (x2, y2) = ARC
    return ((1 - u) ** 2 * x0 + 2 * (1 - u) * u * x1 + u * u * x2,
            (1 - u) ** 2 * y0 + 2 * (1 - u) * u * y1 + u * u * y2)


def flight(t):
    """(x, y, angle, scale) of the ball in the air, or None."""
    if not FLIGHT[0] <= t < FLIGHT[1]:
        return None
    u = span(t, *FLIGHT)
    x, y = bezier(u)
    return x, y, -TAU / 4 + 0.08 + TAU * 2 * u, 0.86 - 0.46 * u     # end over end, and away from us


def football(ctx, x, y, angle, scale):
    """A cartoon football, long axis along angle: the leather, its stripes and laces."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(angle)
    ctx.scale(scale, scale)
    ctx.move_to(-46, 0)
    ctx.curve_to(-26, -30, 26, -30, 46, 0)
    ctx.curve_to(26, 30, -26, 30, -46, 0)
    ctx.close_path()
    g = cairo.LinearGradient(0, -26, 0, 26)
    g.add_color_stop_rgb(0, *mix(LEATHER, WHITE, 0.25))
    g.add_color_stop_rgb(0.5, *LEATHER)
    g.add_color_stop_rgb(1, *mix(LEATHER, INK, 0.35))
    inked(ctx, g, 5, (5, 5))
    ctx.set_source_rgb(*WHITE)
    for sx in (-30, 26):                         # the stripes near the tips
        ctx.move_to(sx, -16)
        ctx.curve_to(sx + 3, -6, sx + 3, 6, sx, 16)
        ctx.line_to(sx + 6, 16)
        ctx.curve_to(sx + 9, 6, sx + 9, -6, sx + 6, -16)
        ctx.close_path()
    ctx.fill()
    ctx.set_line_width(3.5)
    ctx.move_to(-14, -10)
    ctx.line_to(14, -10)
    for k in range(5):
        ctx.move_to(-11 + k * 5.5, -16)
        ctx.line_to(-11 + k * 5.5, -4)
    ctx.stroke()
    ctx.restore()


def tee(ctx):
    """The kicking tee, orange plastic, on the rug."""
    x, y = TEE
    ctx.move_to(x - 36, y)
    ctx.line_to(x - 18, y - 26)
    ctx.line_to(x + 18, y - 26)
    ctx.line_to(x + 36, y)
    ctx.close_path()
    inked(ctx, (1.0, 0.45, 0.1), 4, (4, 4))


def ball_on_tee(ctx, t):
    if t >= KICK:
        return
    rock = 0.0
    for k, when in enumerate(TAPS):          # each tap rocks it a little further
        p = span(t, when, when + 0.45)
        if 0 < p < 1:
            rock += (0.12 + 0.06 * k) * math.sin(p * TAU * 1.5) * (1 - p)
    x, y = TEE[0], TEE[1] - 22
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rock)
    football(ctx, 0, -38, -TAU / 4 + 0.08, 0.86)
    ctx.restore()


def rug(ctx):
    ctx.save()
    ctx.translate(560, O.FLOOR + 30)
    ctx.scale(380, 34)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, (0.25, 0.55, 0.32), 4, (0, 6))
    ctx.save()
    ctx.translate(560, O.FLOOR + 30)
    ctx.scale(330, 24)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(1, 1, 1, 0.55)
    ctx.set_line_width(3)
    ctx.set_dash([14, 10])
    ctx.stroke()
    ctx.set_dash([])


def swish(ctx, t):
    """A sparkle between the uprights as it goes through, and a trail behind the ball."""
    p = span(t, THROUGH, THROUGH + 0.45)
    if 0 < p < 1:
        glint(ctx, EARS[0], EARS[1] - 62, 26 * math.sin(math.pi * p), p * 2, 1)
    if FLIGHT[0] <= t < FLIGHT[1] + 0.1:
        u = span(t, *FLIGHT)
        for k in range(10):
            v = u - 0.025 * (k + 1)
            if v <= 0:
                break
            x, y = bezier(v)
            ctx.arc(x, y, 7 * (1 - k / 10) * (1 - 0.4 * v), 0, TAU)
            ctx.set_source_rgba(1, 1, 1, 0.35 * (1 - k / 10))
            ctx.fill()


# ---------------------------------------------------------------- the TV

def screen(ctx, t, x, y, w, h):
    """The game on before the kick (a field and its posts), IT'S GOOD! after it, then
    VizelVision on its sunburst for the closed logo."""
    if t < GOOD:
        g = cairo.LinearGradient(0, y, 0, y + h)
        g.add_color_stop_rgb(0, 0.12, 0.45, 0.2)
        g.add_color_stop_rgb(1, 0.05, 0.3, 0.12)
        ctx.set_source(g)
        ctx.rectangle(x, y, w, h)
        ctx.fill()
        ctx.set_source_rgba(1, 1, 1, 0.75)
        for k in range(-3, 4):                    # yard lines, toward the posts
            ctx.move_to(x + w / 2 + k * 14, y + 70)
            ctx.line_to(x + w / 2 + k * 70, y + h)
        ctx.set_line_width(3)
        ctx.stroke()
        posts(ctx, x + w / 2, y + 96, 1.0)
        return
    if t < BANNER:
        ctx.set_source_rgb(0.05, 0.08, 0.3)
        ctx.rectangle(x, y, w, h)
        ctx.fill()
        posts(ctx, x + w / 2, y + 126, 1.3)
        k = back_out(span(t, GOOD, GOOD + 0.3), 2.4)
        if k > 0.01 and math.sin((t - GOOD) * 18) > -0.6:
            ctx.save()
            ctx.translate(x + w / 2, y + h - 52)
            ctx.scale(k, k)
            pixel_text(ctx, "IT'S GOOD!", 0, -14, 4,
                       YELLOW, align='center', shadow=(1, 1, (0.6, 0.1, 0.0)))
            ctx.restore()
        return
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
    k = back_out(span(t, BANNER, BANNER + 0.4), 2.2)
    if k > 0.001:
        ctx.save()
        ctx.translate(cx, cy + 14)
        ctx.scale(0.5 * k, 0.5 * k)
        A.draw_tv(ctx, t, 1, 0.0)
        ctx.restore()


def posts(ctx, cx, base, k):
    """Goalposts: the crossbar and two uprights, yellow."""
    ctx.save()
    ctx.translate(cx, base)
    ctx.scale(k, k)
    ctx.move_to(0, 40)
    ctx.line_to(0, 0)
    ctx.move_to(-46, 0)
    ctx.line_to(46, 0)
    ctx.move_to(-46, 0)
    ctx.line_to(-46, -70)
    ctx.move_to(46, 0)
    ctx.line_to(46, -70)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_source_rgb(*YELLOW)
    ctx.set_line_width(6)
    ctx.stroke()
    ctx.restore()


# ---------------------------------------------------------------- the cat

def gaze(t):
    look = 0.0
    for when, target in LOOKS:
        look += (target - look) * ease_in_out(span(t, when, when + 0.16))
    return look


def cat(ctx, t):
    look = gaze(t)
    if t >= KICK:                                     # following the ball, then back to you
        u = span(t, *FLIGHT)
        look = 1.0 - ease_in_out(span(t, FLIGHT[1] + 0.2, FLIGHT[1] + 0.4)) if u < 1 or t < FLIGHT[1] + 0.4 else 0.0
        look += ease_in_out(span(t, GLANCE[0], GLANCE[0] + 0.1)) - ease_in_out(span(t, GLANCE[1], GLANCE[1] + 0.1))
    reach = 0.0
    for when in TAPS:
        reach = max(reach, 0.75 * math.sin(math.pi * span(t, when - 0.1, when + 0.12)))
    reach = max(reach, math.sin(math.pi * span(t, KICK - 0.14, KICK + 0.2)))
    arms = ease_out(span(t, *ARMS)) * (1 - ease_in_out(span(t, *ARMS_DOWN)))
    squash = 0.5 * math.sin(math.pi * span(t, KICK - 0.05, KICK + 0.25))
    eyes = 'wide' if 2.2 <= t < KICK + 0.6 or GLANCE[0] <= t < GLANCE[1] else (
        'squint' if FLIGHT[1] + 0.6 <= t < GLANCE[0] or ARMS_DOWN[1] <= t < BANNER else 'open')
    mouth = math.sin(math.pi * span(t, MRRP, MRRP + 0.28))
    blink = (ease_in_out(span(t, BLINK[0], BLINK[0] + 0.18)) - ease_in_out(span(t, BLINK[1] - 0.15, BLINK[1])))
    blink = max(blink, math.sin(math.pi * span(t, 0.95, 1.1)))
    O.sitting(ctx, t, *SEAT, look, reach, eyes, blink, mouth, squash, arms=arms)


def crash(ctx, t):
    """Behind the set: a puff, a few shards over its top, and a wobble."""
    p = span(t, CRASH, CRASH + 0.5)
    if not 0 < p < 1:
        return
    x, y = CABINET[0] + CABINET[2] + 30, CABINET[1] + 40
    for k in range(7):
        a = -TAU / 4 + (k - 3) * 0.32
        r = 40 + 120 * ease_out(p)
        sx, sy = x + math.cos(a) * r, y + math.sin(a) * r + 160 * p * p
        ctx.save()
        ctx.translate(sx, sy)
        ctx.rotate(p * 9 + k)
        ctx.move_to(-9, -6)
        ctx.line_to(10, -3)
        ctx.line_to(-2, 9)
        ctx.close_path()
        ctx.restore()
        inked(ctx, (0.96, 0.9, 0.8), 3, (2, 2))
    ctx.save()
    ctx.translate(x - 10, y - 30)
    k = back_out(min(1.0, p * 3), 2.4) * (1 - span(p, 0.6, 1.0))
    ctx.scale(k, k)
    for i in range(10):
        a = i * TAU / 10
        ctx.line_to(math.cos(a) * (44 if i % 2 else 24), math.sin(a) * (44 if i % 2 else 24))
    ctx.close_path()
    inked(ctx, YELLOW, 4, (4, 4))
    ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    O.room(ctx, t)
    rug(ctx)
    ball = flight(t)
    behind = span(t, *FLIGHT) > BEHIND
    if ball and behind:                              # past the ears: behind the set
        football(ctx, *ball)
    wobble = 0.02 * pulse(t, THROUGH, 0.5) * math.sin(t * 50) + 0.03 * pulse(t, CRASH, 0.6) * math.sin(t * 45)
    cats.tv_set(ctx, t, screen, wobble)
    crash(ctx, t)
    tee(ctx)
    ball_on_tee(ctx, t)
    cat(ctx, t)
    if ball and not behind:
        football(ctx, *ball)
    swish(ctx, t)
    cats.banner(ctx, t, 'VIZELVISION FOOTBALL', BANNER, cx=880, cy=676)
    cats.caption(ctx, t, 4, 'The Field Goal', *CAPTION)
    vignette(ctx, 0.4)
    grain(ctx, frame, 0.45)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        iris(ctx, SEAT[0] + 60, SEAT[1] - 130, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        iris(ctx, SEAT[0], SEAT[1] - 170, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 90 * (1 - closing) / .3)
