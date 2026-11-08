"""Orange Cat Behavior No. 7, The Leaf Pile: a nature documentary, on a gold November
afternoon in a Washington back yard (a board fence, the backs of the rowhouses, a maple
letting go of its leaves, a rake). The orange cat sits before a freshly raked pile. On the
open logo four leaves drift down onto it, the cat's head following each; a wiggle; the
pounce. The pile goes up like a firework and comes down again, and the orange cat is now
the leaf pile: only its tail sticks out, swishing. A wild turkey wanders in from next door
to see what the fuss is. The cat's head pops out, a leaf on it. On the closed logo the
turkey spreads its tail, the leaves still in the air swirl up and VIZELVISION drops in over
the sky: HAPPY THANKSGIVING. Cat and turkey trade a slow blink, as friends do.

Draco: "The orange cat... has found the leaf pile." / "The orange cat... is now the leaf
pile." / "Happy Thanksgiving."
"""
import math
import random
from functools import lru_cache

import cairo

import cats
import neighborhood
import only_on as O
import turkeys
from common import (INK, TAU, W, H, WHITE, back_out, clamp, ease_in, ease_in_out, ease_out, font,  # noqa: F401
                    grain, inked, inked_stroke, iris, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'cat-leaf-pile'
NAME = 'Orange Cat Behavior: The Leaf Pile'
KIND = 'ident'
ORDER = 51
DESCRIPTION = ('A nature documentary for Thanksgiving: in a gold November back yard the orange cat considers '
               'a freshly raked leaf pile while four leaves drift onto it, wiggles, pounces, and becomes the '
               'leaf pile (only its tail sticks out). A wild turkey wanders over to see; the cat pops out '
               'wearing a leaf; the turkey spreads its tail and VIZELVISION drops in over the sky. They trade '
               'a slow blink. Narrated by Draco.')
DURATION = 10.0
STILL_AT = 8.55
OVERLAYS = []

# Hit points (the music's too: cat_leaf_pile_music.py).
IRIS_OPEN = (0.0, 0.5)
CAPTION = (0.4, 3.0)
LEAVES = (3.0, 3.25, 3.5, 4.0)               # the open logo: a leaf lands on the pile on each note
WIGGLE = (4.15, 4.45)
POUNCE = (4.45, 4.8)
BURST = 4.8                                  # into the pile; it goes up
SETTLE = (4.8, 6.2)                          # the leaves coming back down
TAIL = (5.3, 6.55)                           # only the tail sticks out
TURKEY_WALK = (5.4, 6.6)                     # the turkey wanders in from the right
TURKEY_STEPS = 5
POP_OUT = 6.6                                # the cat's head pops out, a leaf on it
PUTT = 6.85                                  # the turkey's putt: hello
LOGO = (7.2, 7.45, 7.7, 8.2)                 # the closed logo
FAN = (7.2, 7.6)                             # the turkey spreads its tail
BLINK = (8.65, 9.05)                         # both of them, slowly
IRIS_CLOSE = (9.25, 9.6)

FLOOR = O.FLOOR
SEAT = (400, FLOOR)
PILE = (790, FLOOR + 6, 210, 150)            # centre x, base y, half-width, height
TURKEY_FROM, TURKEY_AT = 1420, 1130
TURKEY_SCALE = 0.78
FENCE = (420, 585)                           # top and bottom of the boards
LEAF_COLOURS = ((0.95, 0.42, 0.1), (0.86, 0.2, 0.1), (0.98, 0.7, 0.16), (0.78, 0.36, 0.1), (0.95, 0.55, 0.12),
                (0.66, 0.16, 0.12))


# ---------------------------------------------------------------- leaves

def maple(ctx, size):
    """A maple leaf's outline at the origin, stem down, size its height."""
    s = size / 100
    pts = ((0, 30), (-8, 22), (-40, 30), (-34, 12), (-50, 2), (-40, -4), (-46, -26), (-26, -20), (-22, -34),
           (-10, -24), (0, -50), (10, -24), (22, -34), (26, -20), (46, -26), (40, -4), (50, 2), (34, 12),
           (40, 30), (8, 22))
    ctx.move_to(pts[0][0] * s, pts[0][1] * s)
    for x, y in pts[1:]:
        ctx.line_to(x * s, y * s)
    ctx.close_path()


def leaf(ctx, x, y, size, angle, colour, flip=1.0, outline=2.0):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(angle)
    ctx.scale(max(0.15, abs(flip)), 1)
    maple(ctx, size)
    shade = colour if flip >= 0 else mix(colour, INK, 0.25)
    inked(ctx, shade, outline, (0, 0))
    ctx.move_to(0, 30 * size / 100)                            # the stem and veins
    ctx.line_to(0, -36 * size / 100)
    for a in (-0.9, 0.9):
        ctx.move_to(0, 6 * size / 100)
        ctx.line_to(math.sin(a) * 34 * size / 100, -math.cos(a) * 24 * size / 100)
    ctx.set_source_rgba(*mix(colour, INK, 0.45), 0.8)
    ctx.set_line_width(1.2)
    ctx.stroke()
    ctx.restore()


@lru_cache(maxsize=1)
def pile_leaves():
    rand = random.Random(77)
    cx, base, hw, h = PILE
    out = []
    for _ in range(170):
        u = rand.uniform(-1, 1)
        top = h * math.sqrt(max(0.0, 1 - u * u)) * (0.9 + 0.1 * math.sin(u * 9))
        v = rand.random() ** 0.6
        out.append((u * hw, -top * v, rand.uniform(26, 40), rand.uniform(0, TAU), rand.choice(LEAF_COLOURS),
                    rand.choice((1.0, 0.7, -0.8))))
    out.sort(key=lambda p: p[1])
    return out


def pile_outline(ctx, cx, base, hw, h):
    ctx.move_to(cx - hw - 20, base)
    for k in range(41):
        u = -1 + k / 20
        top = h * math.sqrt(max(0.0, 1 - u * u)) * (0.9 + 0.1 * math.sin(u * 9))
        ctx.line_to(cx + u * hw, base - top)
    ctx.line_to(cx + hw + 20, base)
    ctx.close_path()


@lru_cache(maxsize=1)
def pile_surface():
    """The pile, drawn once: a dark mound under a few hundred leaves."""
    cx, base, hw, h = PILE
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(s)
    pile_outline(ctx, cx, base, hw, h)
    g = cairo.LinearGradient(0, base - h, 0, base)
    g.add_color_stop_rgb(0, 0.82, 0.38, 0.1)
    g.add_color_stop_rgb(1, 0.45, 0.18, 0.06)
    inked(ctx, g, 4, (7, 5))
    for x, y, size, angle, colour, flip in pile_leaves():
        leaf(ctx, cx + x, base + y, size, angle, colour, flip)
    return s


def pile_height(t):
    """1 as raked; it flattens as the cat dives in, and recovers as the leaves come down."""
    dive = ease_out(span(t, BURST - 0.05, BURST + 0.12))
    back = ease_in_out(span(t, BURST + 0.3, SETTLE[1]))
    return 1 - 0.38 * dive + 0.38 * dive * back - 0.04 * pulse(t, POP_OUT, 0.3)


def draw_pile(ctx, t):
    cx, base, hw, h = PILE
    k = pile_height(t)
    ctx.save()
    ctx.translate(cx, base)
    ctx.scale(1 + 0.06 * (1 - k), k)
    ctx.translate(-cx, -base)
    ctx.set_source_surface(pile_surface(), 0, 0)
    ctx.paint()
    ctx.restore()


def falling_leaf(t, i, start, x0, y0=-40, fall=None):
    """Where a leaf drifting down from the maple is at t: (x, y, angle, flip) or None."""
    rand = random.Random(i * 31 + 5)
    speed = rand.uniform(70, 110)
    sway = rand.uniform(30, 70)
    rate = rand.uniform(1.3, 2.2)
    age = t - start
    if age < 0:
        return None
    y = y0 + speed * age
    if fall is not None and y > fall:
        return None
    x = x0 + sway * math.sin(age * rate) - 18 * age
    return x, y, 0.6 * math.sin(age * rate + 1), math.cos(age * rate * 1.5)


@lru_cache(maxsize=1)
def drifters():
    """Leaves drifting down all the while from the maple, over the whole yard."""
    rand = random.Random(9)
    return [(rand.uniform(-8, 10), rand.uniform(40, 1300), rand.uniform(20, 30), rand.choice(LEAF_COLOURS))
            for _ in range(26)]


def the_drift(ctx, t):
    for i, (start, x0, size, colour) in enumerate(drifters()):
        place = falling_leaf(t, i, start, x0, fall=FLOOR + 50)
        if place:
            x, y, a, flip = place
            leaf(ctx, x, y, size, a, colour, flip)


def logo_leaves(ctx, t):
    """The open logo: four leaves let go above the pile and land on it, a note each."""
    cx, base, hw, h = PILE
    for k, when in enumerate(LEAVES):
        land_x = cx - 90 + k * 60
        land_y = base - h * 0.95 + 18 * abs(k - 1.5)
        fall_time = 1.25
        p = span(t, when - fall_time, when)
        if p <= 0 or t > BURST:
            continue
        rand = random.Random(k)
        x = land_x + (1 - p) * rand.uniform(-60, 60) + 26 * math.sin(p * 7 + k) * (1 - p)
        y = land_y - (1 - ease_out(p, 1.6)) * 320
        a = (1 - p) * math.sin(p * 9 + k) * 0.9 + 0.3 * (k - 1.5)
        leaf(ctx, x, y, 46, a, (LEAF_COLOURS[2], LEAF_COLOURS[1], LEAF_COLOURS[2], LEAF_COLOURS[1])[k], 1.0 if p >= 1 else math.cos(p * 8), 2.6)


@lru_cache(maxsize=1)
def burst_leaves():
    rand = random.Random(19)
    out = []
    for _ in range(90):
        a = rand.uniform(-math.pi * 0.92, -math.pi * 0.08)
        v = rand.uniform(320, 820)
        out.append((rand.uniform(-150, 150), rand.uniform(-120, -20), math.cos(a) * v, math.sin(a) * v,
                    rand.uniform(24, 40), rand.choice(LEAF_COLOURS), rand.uniform(0, TAU), rand.uniform(-9, 9),
                    rand.uniform(1.4, 2.6)))
    return out


def burst(ctx, t):
    """The pile going up: leaves thrown out, braking in the air, fluttering back down. On the
    closed logo the ones still up swirl."""
    age = t - BURST
    if age <= 0:
        return
    cx, base, hw, h = PILE
    swirl = ease_in_out(span(t, LOGO[0], LOGO[3] + 0.6))
    for i, (dx, dy, vx, vy, size, colour, a0, spin, rate) in enumerate(burst_leaves()):
        drag = 3.2
        e = (1 - math.exp(-drag * age)) / drag
        x = cx + dx + vx * e
        terminal = 85
        y = base + dy + vy * e + terminal * max(0.0, age - 0.25) * ease_in(min(1.0, age / 0.8))
        x += 30 * math.sin(age * rate + i) * clamp(age - 0.3)
        if swirl > 0:                                            # caught in the closed logo's gust
            ang = swirl * 2.2 + i
            x += math.cos(ang) * 120 * swirl
            y -= 260 * swirl * (0.6 + 0.4 * math.sin(i))
        if y > base - 20 and x > cx - hw - 40 and x < cx + hw + 40 and swirl == 0:
            continue                                             # back on the pile
        if y > FLOOR + 60 or y < -60:
            continue
        leaf(ctx, x, y, size, a0 + spin * e + 0.4 * math.sin(age * rate), colour, math.cos(age * rate * 2 + i))


# ---------------------------------------------------------------- the yard

@lru_cache(maxsize=1)
def yard_surface():
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(s)
    g = cairo.LinearGradient(0, 0, 0, FENCE[0])
    g.add_color_stop_rgb(0, 0.48, 0.62, 0.86)
    g.add_color_stop_rgb(0.6, 0.86, 0.78, 0.7)
    g.add_color_stop_rgb(1, 1.0, 0.82, 0.55)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(3)
    # the backs of the rowhouses over the fence: brick, sash windows, a porch or two
    x = -30
    for k in range(8):
        w = rand.choice((150, 170, 190))
        top = rand.choice((170, 190, 205, 220))
        brick = rand.choice(((0.66, 0.3, 0.22), (0.58, 0.26, 0.2), (0.72, 0.4, 0.28), (0.52, 0.3, 0.28)))
        ctx.rectangle(x, top, w, FENCE[0] - top + 20)
        inked(ctx, brick, 3, (0, 0))
        ctx.rectangle(x - 4, top - 10, w + 8, 12)
        inked(ctx, mix(brick, INK, 0.35), 2, (0, 0))
        for row in range(2):
            for col in range(2):
                wx, wy = x + 30 + col * (w - 90), top + 30 + row * 90
                ctx.rectangle(wx, wy, 32, 52)
                lit = rand.random() < 0.35
                inked(ctx, (1.0, 0.85, 0.5) if lit else (0.32, 0.38, 0.5), 2.5, (0, 0))
                ctx.rectangle(wx, wy + 24, 32, 3)
                ctx.set_source_rgb(0.95, 0.92, 0.85)
                ctx.fill()
        x += w
    # the fence
    ctx.rectangle(0, FENCE[0], W, FENCE[1] - FENCE[0])
    ctx.set_source_rgb(0.56, 0.42, 0.3)
    ctx.fill()
    for bx in range(0, W, 44):
        ctx.move_to(bx, FENCE[0] - 10 + 6 * (bx // 44 % 2))
        ctx.line_to(bx + 40, FENCE[0] - 10 + 6 * (bx // 44 % 2))
        ctx.line_to(bx + 40, FENCE[1])
        ctx.line_to(bx, FENCE[1])
        ctx.close_path()
        shade = 0.9 + 0.1 * rand.random()
        inked(ctx, (0.62 * shade, 0.48 * shade, 0.34 * shade), 2.5, (0, 0))
    for y in (FENCE[0] + 26, FENCE[1] - 40):                   # the rails
        ctx.rectangle(0, y, W, 12)
        ctx.set_source_rgba(0.3, 0.2, 0.12, 0.35)
        ctx.fill()
    # the lawn
    ctx.rectangle(0, FENCE[1], W, H - FENCE[1])
    g = cairo.LinearGradient(0, FENCE[1], 0, H)
    g.add_color_stop_rgb(0, 0.5, 0.58, 0.24)
    g.add_color_stop_rgb(1, 0.38, 0.48, 0.18)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(0, FENCE[1], W, 18)
    ctx.set_source_rgba(0, 0, 0, 0.18)
    ctx.fill()
    for _ in range(60):                                        # leaves already down
        leaf(ctx, rand.uniform(0, W), rand.uniform(FENCE[1] + 20, H - 6), rand.uniform(16, 26),
             rand.uniform(0, TAU), rand.choice(LEAF_COLOURS), rand.choice((1.0, 0.6, -0.7)), 1.4)
    # the rake, against the fence
    ctx.move_to(1000, FENCE[1] + 4)
    ctx.line_to(1062, 330)
    inked_stroke(ctx, (0.75, 0.55, 0.3), 9, (4, 4))
    ctx.save()
    ctx.translate(1062, 330)
    ctx.rotate(0.24)
    ctx.move_to(-36, -6)
    ctx.line_to(36, -6)
    ctx.line_to(30, 6)
    ctx.line_to(-30, 6)
    ctx.close_path()
    inked(ctx, (0.25, 0.55, 0.3), 3, (3, 3))
    for k in range(9):
        ctx.move_to(-30 + k * 7.5, -6)
        ctx.line_to(-34 + k * 8.5, -40)
    ctx.set_source_rgb(0.25, 0.55, 0.3)
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.restore()
    # the maple: its trunk on the left and a crown of orange
    ctx.move_to(70, H)
    ctx.curve_to(90, 500, 80, 360, 110, 180)
    ctx.line_to(170, 180)
    ctx.curve_to(170, 360, 190, 520, 230, H)
    ctx.close_path()
    g = cairo.LinearGradient(70, 0, 230, 0)
    g.add_color_stop_rgb(0, 0.3, 0.2, 0.14)
    g.add_color_stop_rgb(1, 0.45, 0.32, 0.22)
    inked(ctx, g, 4, (6, 6))
    for x0, y0, x1, y1, wd in ((140, 260, 300, 120, 18), (130, 220, 20, 90, 16), (150, 200, 210, 40, 12)):
        ctx.move_to(x0, y0)
        ctx.line_to(x1, y1)
        inked_stroke(ctx, (0.36, 0.25, 0.18), wd, (4, 4))
    for _ in range(46):
        bx, by, r = rand.uniform(-60, 420), rand.uniform(-60, 220), rand.uniform(40, 80)
        ctx.arc(bx, by, r, 0, TAU)
        ctx.set_source_rgb(*mix(rand.choice(LEAF_COLOURS), (1, 0.8, 0.4), rand.uniform(0, 0.25)))
        ctx.fill()
    for _ in range(90):
        leaf(ctx, rand.uniform(-40, 440), rand.uniform(-40, 260), rand.uniform(22, 36), rand.uniform(0, TAU),
             rand.choice(LEAF_COLOURS), 1.0, 1.2)
    # the low sun's glow from the right
    sun = cairo.RadialGradient(1200, 160, 20, 1200, 160, 700)
    sun.add_color_stop_rgba(0, 1.0, 0.9, 0.6, 0.45)
    sun.add_color_stop_rgba(1, 1.0, 0.8, 0.5, 0)
    ctx.set_source(sun)
    ctx.paint()
    return s


# ---------------------------------------------------------------- the cat

def look_at_pile(t):
    """Head following each leaf as it lands, then fixed on the pile."""
    bob = sum(pulse(t, w, 0.25) for w in LEAVES)
    return 0.85 + 0.15 * bob


def cat(ctx, t):
    if t < POUNCE[0]:
        crouch = 0.65 * ease_out(span(t, LEAVES[3] - 0.1, LEAVES[3] + 0.15))
        wiggle = math.sin(TAU * 2 * span(t, *WIGGLE)) if WIGGLE[0] <= t <= WIGGLE[1] else 0.0
        ctx.save()
        ctx.translate(SEAT[0], SEAT[1])
        ctx.rotate(0.05 * wiggle)
        ctx.translate(-SEAT[0] + 7 * wiggle, -SEAT[1])
        blink = math.sin(math.pi * span(t, 1.9, 2.05))
        O.sitting(ctx, t, *SEAT, look_at_pile(t), 0.0, 'wide' if t > LEAVES[0] - 0.4 else 'open', blink, 0.0, crouch)
        ctx.restore()
        return
    if t < POUNCE[1]:
        p = span(t, *POUNCE)
        cx, base, _, h = PILE
        x = SEAT[0] + (cx - SEAT[0]) * p
        y = SEAT[1] - 70 - 200 * math.sin(math.pi * p) + (base - h * 0.5 - SEAT[1] + 70) * p
        O.leaping(ctx, t, x, y, -0.4 + 0.9 * p)


def tail(ctx, t):
    """Only the tail, sticking up out of the pile, swishing."""
    p = ease_out(span(t, TAIL[0], TAIL[0] + 0.3)) * (1 - ease_in(span(t, TAIL[1] - 0.15, TAIL[1])))
    if p <= 0:
        return
    cx, base, _, h = PILE
    top = base - h * pile_height(t)
    sw = math.sin(t * 5.5) * 26
    ctx.save()
    ctx.translate(cx + 60, top + 30)
    ctx.scale(O.SIZE, O.SIZE)
    ctx.move_to(0, 20)
    ctx.curve_to(4, -30 * p, sw * 0.5, -70 * p, sw, -96 * p)
    O.striped(ctx, O.FUR, 20)
    ctx.restore()


def popped(ctx, t):
    """The head out of the top of the pile, a leaf on it; then the pile's front over its chin."""
    if t < POP_OUT:
        return False
    cx, base, _, h = PILE
    p = back_out(span(t, POP_OUT, POP_OUT + 0.3), 2.4)
    top = base - h * pile_height(t)
    hy = top + 46 - 70 * p
    look = 0.9 * ease_in_out(span(t, POP_OUT + 0.35, POP_OUT + 0.6))   # at the turkey
    look -= 0.9 * ease_in_out(span(t, BLINK[1] + 0.05, BLINK[1] + 0.35))
    blink = (ease_in_out(span(t, BLINK[0], BLINK[0] + 0.16)) - ease_in_out(span(t, BLINK[1] - 0.14, BLINK[1])))
    ctx.save()
    ctx.rectangle(0, 0, W, top + 40)                           # inside the pile below this
    ctx.clip()
    ctx.save()
    ctx.translate(cx - 10, hy)
    ctx.scale(O.SIZE, O.SIZE)
    O.head(ctx, 0, 0, look, 'open', blink, 0.0, pulse(t, POP_OUT + 0.3, 0.3))
    ctx.restore()
    ctx.restore()
    ctx.save()                                                 # the leaf on its head, settling
    wob = math.sin((t - POP_OUT) * 10) * math.exp(-(t - POP_OUT) * 3)
    leaf(ctx, cx - 10 + 14, hy - 62 * O.SIZE + 8, 36, 0.35 + 0.4 * wob, LEAF_COLOURS[2], 1.0, 2.2)
    ctx.restore()
    for x, y, size, angle, colour, flip in pile_leaves()[-26:]:   # a few of the pile's leaves in front of its chin
        if abs(x + 10) < 80:
            leaf(ctx, cx + x, base + y * pile_height(t) + 12, size, angle, colour, flip)
    return True


# ---------------------------------------------------------------- the turkey

def turkey(ctx, t):
    if t < TURKEY_WALK[0]:
        return
    p = span(t, *TURKEY_WALK)
    x = TURKEY_FROM + (TURKEY_AT - TURKEY_FROM) * ease_out(p, 2)
    step = TURKEY_STEPS * p if p < 1 else None
    bob = 4 * math.sin((step or 0) * TAU)
    peer = ease_in_out(span(t, TURKEY_WALK[1] - 0.2, TURKEY_WALK[1] + 0.2)) * (1 - ease_in_out(span(t, POP_OUT + 0.1, POP_OUT + 0.4)))
    gob = 0.4 * math.sin(math.pi * span(t, PUTT, PUTT + 0.2)) if PUTT <= t <= PUTT + 0.2 else 0.0
    fan = ease_out(span(t, *FAN), 2)
    blink = (ease_in_out(span(t, BLINK[0], BLINK[0] + 0.16)) - ease_in_out(span(t, BLINK[1] - 0.14, BLINK[1])))
    turkeys.side(ctx, t, x, FLOOR - 4, TURKEY_SCALE, -1, step=step, fan=fan, gobble=gob, blink=blink,
                 bob=bob + 30 * peer, peck=0.12 * peer)


# ---------------------------------------------------------------- the closed logo

def title(ctx, t):
    if t < LOGO[0] - 0.1:
        return
    neighborhood.lockup(ctx, t, LOGO[0], 168, scale=0.62, step=(LOGO[3] - LOGO[0]) / 10)
    q = ease_out(span(t, LOGO[3], LOGO[3] + 0.4))
    if q > 0:
        font(ctx, 'Nimbus Sans', 26)
        for dx, dy, colour, a in ((2, 2, INK, 0.5), (0, 0, WHITE, 1.0)):
            ctx.new_path()
            text_path(ctx, 'HAPPY THANKSGIVING', W / 2 + dx, 226 + dy, tracking=10, align='center')
            ctx.set_source_rgba(*colour, a * q)
            ctx.fill()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    ctx.set_source_surface(yard_surface(), 0, 0)
    ctx.paint()
    turkey(ctx, t)
    draw_pile(ctx, t)
    tail(ctx, t)
    popped(ctx, t)
    logo_leaves(ctx, t)
    cat(ctx, t)
    burst(ctx, t)
    the_drift(ctx, t)
    title(ctx, t)
    cats.caption(ctx, t, 7, 'The Leaf Pile', *CAPTION)
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.6)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        iris(ctx, SEAT[0], SEAT[1] - 150, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        cx, base, _, h = PILE
        hy = base - h * pile_height(t) + 46 - 70
        iris(ctx, cx - 10, hy, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 110 * (1 - closing) / .3)
