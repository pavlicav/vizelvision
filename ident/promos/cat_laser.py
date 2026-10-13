"""Orange Cat Behavior No. 3, The Dot: a nature documentary. Evening in the living room;
a red laser dot darts about the floor and the orange cat follows it with its whole head.
The dot stops. The cat crouches and wiggles its rear once on each note of the open logo,
pounces, and lands exactly where the dot was. The dot is now on its forehead. A question
mark. The dot climbs the wall and, on the closed logo, writes VIZELVISION there in red
light while the cat watches it go. A mrrp, a slow blink, the iris.

The narrator is Draco: "The orange cat... a patient hunter." / "Rarely successful."
"""
import math
from functools import lru_cache

import cairo

import cats
import only_on as O
from common import (INK, TAU, W, H, WHITE, YELLOW, back_out, clamp, ease_in, ease_in_out, ease_out, font,  # noqa: F401
                    glint, grain, inked, iris, mix, pulse, span, vignette)

ID = 'cat-laser'
NAME = 'Orange Cat Behavior: The Dot'
KIND = 'ident'
ORDER = 11
DESCRIPTION = ('A nature documentary: the orange cat stalks a laser dot, wiggles once on each note of the logo, '
               'pounces, and ends up with the dot on its own head; the dot writes VIZELVISION on the wall. '
               'Narrated by Draco.')
DURATION = 10.0
STILL_AT = 8.75
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
IRIS_OPEN = (0.0, 0.45)
CAPTION = (0.4, 2.6)
# The dot's darts about the floor: (when it arrives, x, y).
DARTS = ((0.45, 760, 690), (0.85, 560, 676), (1.15, 1000, 702), (1.45, 850, 668), (1.8, 1110, 694),
         (2.05, 700, 706), (2.45, 960, 684), (2.75, 905, 684))
CROUCH = 2.75
WIGGLES = (3.0, 3.25, 3.5, 4.0)                  # the open logo: one wiggle each
POUNCE = (4.4, 4.85)
ON_HEAD = 5.0                                    # the dot hops onto its forehead
PUZZLED = 5.25                                   # a question mark
CLIMB = (6.4, 6.95)                              # the dot runs up the wall
WRITE = (7.0, 8.5)                               # the closed logo: it writes the wordmark
GLOW = 8.5
MRRP = 8.55
BLINK = (8.75, 9.15)
IRIS_CLOSE = (9.2, 9.6)

SEAT = (330, O.FLOOR)
LANDED = (905, O.FLOOR)
HEAD_Y = O.FLOOR - 205 * O.SIZE / 1.15           # the forehead, sitting
WORD_X, WORD_BASE, WORD_W = 470, 354, 740
RED = (1.0, 0.1, 0.12)


# ---------------------------------------------------------------- the dot

@lru_cache(maxsize=None)
def word_points():
    """The wordmark's outline as one run of points (letter by letter), where each loop
    starts, and the run's length."""
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 8, 8))
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(100)
    size = 100 * WORD_W / ctx.text_extents('VIZELVISION').x_advance
    ctx.set_font_size(size)
    ctx.move_to(WORD_X, WORD_BASE)
    ctx.text_path('VIZELVISION')
    runs, run = [], []
    for kind, pts in ctx.copy_path_flat():
        if kind == cairo.PATH_MOVE_TO:
            if run:
                runs.append(run)
            run = [pts]
        elif kind == cairo.PATH_LINE_TO:
            run.append(pts)
        elif kind == cairo.PATH_CLOSE_PATH and run:
            run.append(run[0])
    if run:
        runs.append(run)
    points, lengths, starts, total = [], [], set(), 0.0
    for r in runs:                    # the dot travels between loops too, but leaves no line there
        starts.add(len(points))
        for p in r:
            if points:
                total += math.dist(points[-1], p)
            points.append(p)
            lengths.append(total)
    return points, lengths, frozenset(starts), total


def written(t):
    """How many of the wordmark's points are drawn, and the dot's place on it."""
    points, lengths, _, total = word_points()
    reach = total * ease_in_out(span(t, *WRITE)) if t >= WRITE[0] else -1
    n = 0
    while n < len(points) and lengths[n] <= reach:
        n += 1
    return n, points[max(0, n - 1)] if n else points[0]


def dot_place(t):
    """Where the dot is (x, y), or None when it is off."""
    if t < DARTS[0][0] - 0.25:
        return None
    if t < DARTS[0][0]:                                  # it appears, sliding in from the right
        p = span(t, DARTS[0][0] - 0.25, DARTS[0][0])
        return 1300 + (DARTS[0][1] - 1300) * ease_out(p), DARTS[0][2]
    for (t0, x0, y0), (t1, x1, y1) in zip(DARTS, DARTS[1:]):
        if t < t1:
            p = ease_in_out(span(t, t0, t1))
            return x0 + (x1 - x0) * p, y0 + (y1 - y0) * p - 18 * math.sin(math.pi * p)
    last = DARTS[-1][1:]
    if t < POUNCE[1]:
        return last
    head = (LANDED[0] + 4, HEAD_Y)
    if t < ON_HEAD:
        return None if t < ON_HEAD - 0.08 else head      # gone for a blink as the paws come down, then there
    if t < CLIMB[0]:
        return head
    start = written(WRITE[0] + 1e-6)[1]
    if t < CLIMB[1]:
        p = ease_in_out(span(t, *CLIMB))
        return head[0] + (start[0] - head[0]) * p, head[1] + (start[1] - head[1]) * p - 120 * math.sin(math.pi * p)
    if t < WRITE[1]:
        return written(t)[1]
    return None


def dot(ctx, t, frame):
    place = dot_place(t)
    if place is None:
        return
    x, y = place
    x += 1.4 * math.sin(frame * 1.7)                     # a hand is holding the pointer
    y += 1.2 * math.cos(frame * 2.3)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    g = cairo.RadialGradient(x, y, 0, x, y, 32)
    g.add_color_stop_rgba(0, 1, 0.3, 0.3, 0.95)
    g.add_color_stop_rgba(0.3, 1, 0.05, 0.05, 0.5)
    g.add_color_stop_rgba(1, 1, 0, 0, 0)
    ctx.set_source(g)
    ctx.arc(x, y, 32, 0, TAU)
    ctx.fill()
    ctx.restore()
    ctx.arc(x, y, 5.5, 0, TAU)
    ctx.set_source_rgb(1, 0.85, 0.85)
    ctx.fill()


def wordmark(ctx, t):
    """The wordmark in red light, as far as the dot has written it; it flares when done."""
    if t < WRITE[0]:
        return
    points, _, starts, _ = word_points()
    n = len(points) if t >= WRITE[1] else written(t)[0]
    if n < 2:
        return
    fade = 1 - span(t, IRIS_CLOSE[0], IRIS_CLOSE[1])
    flare = pulse(t, GLOW, 0.6)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for width, alpha, colour in ((16 + 10 * flare, 0.12, RED), (6, 0.45, RED), (2.2, 0.9, (1, 0.75, 0.7))):
        for i in range(n):
            if i in starts:
                ctx.move_to(*points[i])
            else:
                ctx.line_to(*points[i])
        ctx.set_source_rgba(*colour, alpha * (1 + 0.6 * flare) * fade)
        ctx.set_line_width(width)
        ctx.stroke()
    ctx.restore()


# ---------------------------------------------------------------- the cat

def tracking(t):
    """Where it looks: after the dot, a beat behind."""
    place = dot_place(max(0.0, t - 0.08)) or (SEAT[0] + 300, 0)
    return clamp((place[0] - SEAT[0]) / 260, -1, 1)


def cat(ctx, t):
    if t < POUNCE[0]:
        crouch = 0.65 * ease_out(span(t, CROUCH, CROUCH + 0.2)) * (1 - span(t, POUNCE[0] - 0.05, POUNCE[0]))
        wiggle = sum(math.sin(TAU * span(t, w, w + 0.22)) for w in WIGGLES)
        ctx.save()
        ctx.translate(SEAT[0], SEAT[1])
        ctx.rotate(0.05 * wiggle)
        ctx.translate(-SEAT[0] + 7 * wiggle, -SEAT[1])
        blink = math.sin(math.pi * span(t, 2.2, 2.32))
        O.sitting(ctx, t, *SEAT, tracking(t), 0.0, 'wide', blink, 0.0, crouch)
        ctx.restore()
        return
    if t < POUNCE[1]:
        p = span(t, *POUNCE)
        x = SEAT[0] + (LANDED[0] - SEAT[0]) * p
        y = SEAT[1] - 70 - 240 * math.sin(math.pi * p) + 40 * p
        O.leaping(ctx, t, x, y, -0.45 + 0.8 * p)
        return
    land = t - POUNCE[1]
    squash = max(0.0, math.exp(-land * 9) * math.cos(land * 22) * 0.9)
    if t < CLIMB[0]:
        look = 0.0                                       # at you, the dot on its head
    elif t < WRITE[1]:                                   # after the dot, up the wall and along the letters
        x = (dot_place(max(0.0, t - 0.08)) or written(WRITE[1] - 1e-6)[1])[0]
        look = clamp((x - LANDED[0]) / 260, -1, 1) * ease_in_out(span(t, CLIMB[0], CLIMB[0] + 0.2))
    else:                                                # and back to you
        look = clamp((written(WRITE[1] - 1e-6)[1][0] - LANDED[0]) / 260, -1, 1) \
            * (1 - ease_in_out(span(t, WRITE[1] + 0.3, WRITE[1] + 0.6)))
    eyes = 'wide' if t < CLIMB[0] else 'open'
    mouth = math.sin(math.pi * span(t, MRRP, MRRP + 0.28))
    blink = (ease_in_out(span(t, BLINK[0], BLINK[0] + 0.16)) - ease_in_out(span(t, BLINK[1] - 0.14, BLINK[1])))
    O.sitting(ctx, t, *LANDED, look, 0.0, eyes, blink, mouth, squash)


def question(ctx, t):
    p = span(t, PUZZLED, PUZZLED + 0.3)
    if p <= 0 or t > CLIMB[0] + 0.2:
        return
    k = back_out(p, 2.4) * (1 - span(t, CLIMB[0], CLIMB[0] + 0.2))
    if k <= 0.001:
        return
    ctx.save()
    ctx.translate(LANDED[0] + 95, HEAD_Y - 40)
    ctx.rotate(0.15)
    ctx.scale(k, k)
    font(ctx, 'URW Gothic', 84)
    ext = ctx.text_extents('?')
    ctx.move_to(-ext.width / 2 - ext.x_bearing, ext.height / 2)
    ctx.text_path('?')
    inked(ctx, YELLOW, 4, (5, 5))
    ctx.restore()


# ---------------------------------------------------------------- the frame

def evening(ctx):
    """The room after dark: the lamp's off, the wall's blue."""
    ctx.set_source_rgba(0.04, 0.03, 0.16, 0.42)
    ctx.paint()


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    O.room(ctx, t)
    evening(ctx)
    wordmark(ctx, t)
    cat(ctx, t)
    dot(ctx, t, frame)
    question(ctx, t)
    cats.caption(ctx, t, 3, 'The Dot', *CAPTION)
    vignette(ctx, 0.5)
    grain(ctx, frame, 0.5)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        iris(ctx, SEAT[0], SEAT[1] - 140, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        iris(ctx, LANDED[0], LANDED[1] - 170, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 90 * (1 - closing) / .3)
