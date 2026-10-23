"""Have You Heard?: VizelVision's missionaries, on a sunny Saturday in a Washington rowhouse street.

1. Two elders in white short-sleeved shirts, ties and bike helmets ride up the street past the
   painted rowhouses, backpacks on, ties flying. The open logo's first two notes are their bike
   bells, ring, ring, as they pull up at No. 19.
2. On the stoop, from behind: one presses the doorbell, and its chime is the other two notes,
   ding... dong. The teal door opens.
3. From inside, the two of them in the doorway, beaming, name tags on (ELDER NINETEEN, ELDER
   VIZEL, VIZELVISION): "Hi! Have you heard about channel nineteen?" One holds out a pamphlet,
   THE GOOD NEWS ABOUT CHANNEL 19.
4. The living room, from the TV: a family on the couch with channel 19 on (dad, mom, a kid,
   grandma knitting), a green Jell-O ring on the coffee table, a beehive on the throw pillow,
   FAMILIES ARE FOREVER on the wall. The elders come in and squeeze onto the couch with them:
   "Families can watch together..." On the closed logo the sun comes through the window, a
   choir and the organ swell, "Forever.", the wordmark drops in, FAMILIES CAN WATCH TOGETHER
   FOREVER, and the pamphlet on the coffee table gets a sticky note: SEE YOU TUESDAY!

Orion and Hermes, the elders.
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (A, INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    font, grain, mix, rounded_rect, span, text_path, vignette)

ID = 'lds'
NAME = 'Have You Heard?'
KIND = 'ident'
ORDER = 41
DESCRIPTION = ('VizelVision\'s missionaries on a sunny Saturday: two elders ride up a Washington rowhouse street, '
               'their bike bells and the doorbell are the open logo, "Hi! Have you heard about channel nineteen?", '
               'a pamphlet, the family on the couch with a green Jell-O ring, and everyone squeezed onto the couch '
               'on the closed logo: FAMILIES CAN WATCH TOGETHER FOREVER. Orion and Hermes.')
DURATION = 10.0
STILL_AT = 8.6
OVERLAYS = []

# Hit points (the music's too: lds_music.py).
FADE_IN = (0.0, 0.3)
RIDE = (0.0, 1.85)                 # the bikes come up the street and stop at No. 19
BELLS = (1.5, 1.75)                # the open logo's first two notes: ring, ring
DOOR_CUT = 1.88                    # the stoop, from behind
PRESS = 1.96                       # a finger on the doorbell
CHIME = (2.0, 2.5)                 # the open logo's last two notes: ding... dong
DOOR_OPEN = (2.55, 2.85)           # the door swings in
HI = 2.65                          # "Hi! Have you heard about channel nineteen?" (3 s)
INSIDE_CUT = 2.85                  # the doorway, from inside
PAMPHLET = (4.3, 4.75)             # held out to the camera
ROOM_CUT = 5.68                    # the living room, from the TV
TOGETHER = 5.72                    # "Families can watch together..."
SQUEEZE = (5.8, 6.9)               # the elders come in and squeeze onto the couch
CLOSED = 7.0                       # the closed logo: the sun, the choir, the organ
SUNBEAMS = (7.0, 7.6)
LOCKUP = 7.05                      # the wordmark, a letter a sixteenth
FOREVER = 7.45                     # "Forever."
SUBTITLE = (8.0, 8.4)
TUESDAY = 8.3                      # a sticky note on the pamphlet: SEE YOU TUESDAY!
FADE = (9.25, 9.6)

SKY_TOP, SKY_LOW = (0.36, 0.66, 0.96), (0.72, 0.88, 1.0)
CREAM = (0.98, 0.95, 0.86)
SHIRT = (0.98, 0.98, 0.97)
SLACKS = (0.13, 0.13, 0.17)
NAVY = (0.12, 0.2, 0.42)
MAROON = (0.52, 0.12, 0.18)
SKIN_A, SKIN_B = (0.96, 0.78, 0.64), (0.82, 0.6, 0.45)
HAIR_A, HAIR_B = (0.85, 0.66, 0.32), (0.32, 0.2, 0.12)
HELMET_A, HELMET_B = (0.15, 0.55, 0.85), (0.95, 0.45, 0.15)
DOOR = (0.0, 0.6, 0.56)
BRASS = (0.85, 0.68, 0.3)
GREEN = (0.38, 0.62, 0.3)
LEAF = (0.3, 0.55, 0.27)
JELLO = (0.45, 0.85, 0.35)
SAGE = (0.55, 0.66, 0.5)
HONEY = (0.98, 0.76, 0.22)
FACADES = ((0.95, 0.63, 0.62), (0.6, 0.82, 0.72), (0.98, 0.86, 0.46), (0.58, 0.72, 0.9), (0.66, 0.3, 0.22))

ELDERS = ({'skin': SKIN_A, 'hair': HAIR_A, 'tie': NAVY, 'helmet': HELMET_A, 'name': 'ELDER NINETEEN'},
          {'skin': SKIN_B, 'hair': HAIR_B, 'tie': MAROON, 'helmet': HELMET_B, 'name': 'ELDER VIZEL'})


# ---------------------------------------------------------------- small parts

def ink_path(ctx, fill, outline=4, shadow=(4, 4)):
    from common import inked
    inked(ctx, fill, outline, shadow)


def circle(ctx, x, y, r):
    ctx.new_sub_path()
    ctx.arc(x, y, r, 0, TAU)


def ellipse(ctx, x, y, rx, ry):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(rx, ry)
    ctx.new_sub_path()
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()


def label(ctx, text, x, y, size, colour, face='Nimbus Sans', bold=True, tracking=1.0, align='center'):
    font(ctx, face, size, bold)
    text_path(ctx, text, x, y, tracking=tracking, align=align)
    ctx.set_source_rgb(*colour)
    ctx.fill()


def face(ctx, x, y, r, skin, hair, mouth=0.0, look=0.0, side_part=1, smile=1.0, blink=0.0):
    """A friendly round face, front on: neat side-parted hair, dot eyes, a big smile."""
    circle(ctx, x - r * 0.98, y + r * 0.08, r * 0.2)
    circle(ctx, x + r * 0.98, y + r * 0.08, r * 0.2)
    ink_path(ctx, skin, 3, (3, 3))
    circle(ctx, x, y, r)
    ink_path(ctx, skin, 4, (4, 4))
    # hair: a cap with a side part and a little swoop
    ctx.move_to(x - r * 0.98, y - r * 0.05)
    ctx.curve_to(x - r * 1.05, y - r * 1.1, x + r * 1.05, y - r * 1.15, x + r * 0.98, y - r * 0.08)
    ctx.curve_to(x + r * 0.7, y - r * 0.55, x + side_part * r * 0.2, y - r * 0.62, x - r * 0.15 * side_part, y - r * 0.45)
    ctx.curve_to(x - r * 0.55, y - r * 0.62, x - r * 0.85, y - r * 0.35, x - r * 0.98, y - r * 0.05)
    ctx.close_path()
    ink_path(ctx, hair, 3, (2, 2))
    # eyes
    for sx in (-1, 1):
        ex, ey = x + sx * r * 0.36 + look * r * 0.08, y + r * 0.02
        if blink > 0.5:
            ctx.move_to(ex - r * 0.12, ey)
            ctx.line_to(ex + r * 0.12, ey)
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(max(2, r * 0.07))
            ctx.stroke()
        else:
            ellipse(ctx, ex, ey, r * 0.09, r * 0.12)
            ctx.set_source_rgb(*INK)
            ctx.fill()
            circle(ctx, ex + r * 0.03, ey - r * 0.04, r * 0.035)
            ctx.set_source_rgb(1, 1, 1)
            ctx.fill()
    for sx in (-1, 1):
        ellipse(ctx, x + sx * r * 0.62, y + r * 0.32, r * 0.16, r * 0.09)
        ctx.set_source_rgba(1.0, 0.45, 0.45, 0.45)
        ctx.fill()
    # mouth: a wide smile, opening when talking
    if mouth > 0.08:
        ctx.move_to(x - r * 0.42, y + r * 0.32)
        ctx.curve_to(x - r * 0.3, y + r * (0.55 + 0.35 * mouth), x + r * 0.3, y + r * (0.55 + 0.35 * mouth), x + r * 0.42, y + r * 0.32)
        ctx.close_path()
        ctx.set_source_rgb(0.42, 0.1, 0.12)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(max(2, r * 0.06))
        ctx.stroke()
        ctx.rectangle(x - r * 0.3, y + r * 0.33, r * 0.6, r * 0.08)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
    else:
        ctx.move_to(x - r * 0.38, y + r * 0.32)
        ctx.curve_to(x - r * 0.25, y + r * (0.32 + 0.3 * smile), x + r * 0.25, y + r * (0.32 + 0.3 * smile), x + r * 0.38, y + r * 0.32)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(max(2, r * 0.07))
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()


def name_tag(ctx, x, y, s, text):
    rounded_rect(ctx, x, y, 92 * s, 30 * s, 4 * s)
    ctx.set_source_rgb(0.06, 0.06, 0.07)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.5, 0.5, 0.55)
    ctx.set_line_width(max(1, 1.5 * s))
    ctx.stroke()
    label(ctx, text, x + 46 * s, y + 13 * s, 9.6 * s, (1, 1, 1), tracking=0.3 * s)
    label(ctx, 'VIZELVISION', x + 46 * s, y + 25 * s, 7.4 * s, (0.85, 0.85, 0.9), bold=False, tracking=0.6 * s)


# ---------------------------------------------------------------- 1. the street

ROW_W = 1560                       # the street scene is wider than the frame: the camera pans


def rowhouse(ctx, x, w, top, colour, number, seed, turret=False):
    """A painted brick rowhouse: three storeys, a bay, a cornice with brackets, a stoop."""
    rand = random.Random(seed)
    ground = 520
    ctx.rectangle(x, top, w, ground - top)
    ink_path(ctx, colour, 4, (0, 0))
    # brick courses, faintly
    ctx.set_source_rgba(*mix(colour, INK, 0.25), 0.18)
    for y in range(int(top) + 12, ground, 12):
        ctx.rectangle(x + 2, y, w - 4, 1.5)
    ctx.fill()
    # cornice and brackets
    ctx.rectangle(x - 6, top - 26, w + 12, 26)
    ink_path(ctx, CREAM, 4, (0, 4))
    for k in range(5):
        bx = x + 10 + k * (w - 28) / 4
        ctx.rectangle(bx, top - 4, 8, 18)
        ink_path(ctx, CREAM, 2, (0, 0))
    # the bay or turret on the right two thirds
    bx0, bx1 = x + w * 0.42, x + w * 0.94
    if turret:
        ctx.move_to(bx0, ground - 40)
        ctx.line_to(bx0, top + 10)
        ctx.line_to((bx0 + bx1) / 2, top - 70)
        ctx.line_to(bx1, top + 10)
        ctx.line_to(bx1, ground - 40)
        ctx.close_path()
        ink_path(ctx, mix(colour, WHITE, 0.15), 4, (5, 3))
        ctx.move_to(bx0 - 4, top + 12)
        ctx.line_to((bx0 + bx1) / 2, top - 74)
        ctx.line_to(bx1 + 4, top + 12)
        ctx.close_path()
        ink_path(ctx, (0.35, 0.38, 0.45), 3, (0, 0))
    else:
        ctx.rectangle(bx0, top + 6, bx1 - bx0, ground - 40 - top - 6)
        ink_path(ctx, mix(colour, WHITE, 0.15), 4, (5, 3))
    # windows: three floors in the bay, two beside the door
    for floor in range(3):
        wy = top + 24 + floor * ((ground - top - 70) / 3)
        wh = (ground - top - 70) / 3 - 30
        for k in range(2):
            wx = bx0 + 10 + k * ((bx1 - bx0 - 20) / 2)
            ww = (bx1 - bx0 - 20) / 2 - 10
            if floor == 2:
                continue
            rounded_rect(ctx, wx, wy, ww, wh, 6)
            ink_path(ctx, (0.62, 0.8, 0.95), 3, (0, 0))
            ctx.rectangle(wx + ww / 2 - 1.5, wy, 3, wh)
            ctx.set_source_rgb(*CREAM)
            ctx.fill()
            ctx.move_to(wx + 6, wy + wh - 6)
            ctx.line_to(wx + ww * 0.45, wy + 8)
            ctx.set_source_rgba(1, 1, 1, 0.45)
            ctx.set_line_width(4)
            ctx.stroke()
        if floor < 2:
            continue
        ww = w * 0.24
        wx = x + w * 0.1
        rounded_rect(ctx, wx, wy, ww, wh, 6)
        ink_path(ctx, (0.62, 0.8, 0.95), 3, (0, 0))
    for floor in range(2):
        wy = top + 24 + floor * ((ground - top - 70) / 3)
        wh = (ground - top - 70) / 3 - 30
        ww = w * 0.24
        wx = x + w * 0.1
        rounded_rect(ctx, wx, wy, ww, wh, 6)
        ink_path(ctx, (0.62, 0.8, 0.95), 3, (0, 0))
        ctx.rectangle(wx, wy + wh / 2 - 1.5, ww, 3)
        ctx.set_source_rgb(*CREAM)
        ctx.fill()
    # the door at the top of the stoop
    dx, dw = x + w * 0.1, w * 0.24
    rounded_rect(ctx, dx, ground - 150, dw, 104, 8)
    door_colour = DOOR if number == 19 else rand.choice(((0.5, 0.12, 0.15), (0.12, 0.16, 0.3), (0.2, 0.35, 0.25)))
    ink_path(ctx, door_colour, 3, (0, 0))
    if number is not None:
        label(ctx, str(number), dx + dw / 2, ground - 160, 14, BRASS)
    # the stoop: steps down to the sidewalk, iron railings
    for k in range(4):
        ctx.rectangle(dx - 12 + k * 2, ground - 46 + k * 12, dw + 24 - k * 4, 12)
        ink_path(ctx, (0.8, 0.78, 0.74), 2, (0, 0))
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(3)
    for side in (dx - 12, dx + dw + 12):
        ctx.move_to(side, ground - 46)
        ctx.line_to(side, ground + 2)
        ctx.move_to(side, ground - 70)
        ctx.line_to(side, ground - 46)
    ctx.stroke()


def tree(ctx, x, ground, r, seed):
    rand = random.Random(seed)
    ctx.move_to(x - 7, ground)
    ctx.line_to(x - 5, ground - r * 1.6)
    ctx.line_to(x + 5, ground - r * 1.6)
    ctx.line_to(x + 7, ground)
    ctx.close_path()
    ink_path(ctx, (0.45, 0.3, 0.2), 3, (3, 0))
    for k in range(6):
        a = k / 6 * TAU + rand.random() * 0.4
        circle(ctx, x + math.cos(a) * r * 0.55, ground - r * 2.1 + math.sin(a) * r * 0.45, r * (0.55 + rand.random() * 0.2))
    circle(ctx, x, ground - r * 2.15, r * 0.75)
    ink_path(ctx, LEAF, 4, (6, 4))
    for k in range(8):
        a = rand.random() * TAU
        circle(ctx, x + math.cos(a) * r * 0.6, ground - r * 2.25 + math.sin(a) * r * 0.5, r * 0.18)
    ctx.set_source_rgba(0.55, 0.78, 0.4, 0.55)
    ctx.fill()


@lru_cache(maxsize=None)
def street_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, ROW_W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, 420)
    g.add_color_stop_rgb(0, *SKY_TOP)
    g.add_color_stop_rgb(1, *SKY_LOW)
    ctx.set_source(g)
    ctx.paint()
    for cx, cy, s in ((180, 80, 1.0), (760, 50, 0.8), (1300, 95, 1.1)):     # clouds
        for dx, dy, r in ((-40, 6, 26), (-10, -10, 34), (28, 0, 28), (55, 10, 20)):
            circle(ctx, cx + dx * s, cy + dy * s, r * s)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
    x = -40
    numbers = (13, 15, 17, 19, 21, 23)
    for k, number in enumerate(numbers):
        w = 260
        top = 150 + (k % 3) * 18 - (20 if number == 19 else 0)
        rowhouse(ctx, x, w, top, FACADES[k % len(FACADES)], number, k, turret=number in (15, 21))
        x += w
    # sidewalk (brick), curb, the street
    ctx.rectangle(0, 520, ROW_W, 70)
    ctx.set_source_rgb(0.72, 0.42, 0.33)
    ctx.fill()
    ctx.set_source_rgba(*INK, 0.15)
    for xx in range(0, ROW_W, 26):
        for yy in range(526, 590, 13):
            ctx.rectangle(xx + (6 if (yy // 13) % 2 else 0), yy, 24, 1.2)
    ctx.fill()
    ctx.rectangle(0, 586, ROW_W, 12)
    ctx.set_source_rgb(0.82, 0.8, 0.76)
    ctx.fill()
    ctx.rectangle(0, 598, ROW_W, H - 598)
    ctx.set_source_rgb(0.32, 0.33, 0.36)
    ctx.fill()
    ctx.set_source_rgb(0.95, 0.85, 0.3)
    for xx in range(0, ROW_W, 120):
        ctx.rectangle(xx, 690, 60, 6)
    ctx.fill()
    for k, tx in enumerate((110, 480, 870, 1270)):
        tree(ctx, tx, 560, 52, k)
    return surface


def bike(ctx, x, ground, roll, tint):
    """A bike in profile, facing right; roll is the wheels' angle."""
    r = 44
    rear, front = (x - 72, ground - r), (x + 70, ground - r)
    crank = (x - 4, ground - 38)
    seat = (x - 30, ground - 112)
    head = (x + 52, ground - 110)
    for cx, cy in (rear, front):
        circle(ctx, cx, cy, r)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(7)
        ctx.stroke()
        circle(ctx, cx, cy, r - 6)
        ctx.set_source_rgb(0.85, 0.85, 0.88)
        ctx.set_line_width(1.6)
        ctx.stroke()
        for k in range(8):
            a = roll + k * TAU / 8
            ctx.move_to(cx, cy)
            ctx.line_to(cx + math.cos(a) * (r - 6), cy + math.sin(a) * (r - 6))
        ctx.set_line_width(1.4)
        ctx.stroke()
        circle(ctx, cx, cy, 5)
        ctx.set_source_rgb(*INK)
        ctx.fill()
    ctx.move_to(*rear)
    ctx.line_to(*seat)
    ctx.line_to(*crank)
    ctx.close_path()
    ctx.move_to(*seat)
    ctx.line_to(*head)
    ctx.line_to(*crank)
    ctx.move_to(*head)
    ctx.line_to(*front)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(10)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*tint)
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.move_to(head[0], head[1])
    ctx.line_to(head[0] - 6, head[1] - 26)
    ctx.line_to(head[0] - 22, head[1] - 28)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(5)
    ctx.stroke()
    rounded_rect(ctx, seat[0] - 18, seat[1] - 8, 30, 9, 4)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    return {'seat': seat, 'crank': crank, 'grip': (head[0] - 22, head[1] - 28), 'bell': (head[0] - 12, head[1] - 30)}


def limb(ctx, a, b, c, colour, width):
    ctx.move_to(*a)
    ctx.line_to(*b)
    ctx.line_to(*c)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(width + 6)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*colour)
    ctx.set_line_width(width)
    ctx.stroke()


def knee(hip, foot, l1, l2, bend=1):
    dx, dy = foot[0] - hip[0], foot[1] - hip[1]
    d = min(math.hypot(dx, dy), l1 + l2 - 0.01)
    a = math.atan2(dy, dx)
    k = math.acos(max(-1, min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d))))
    return hip[0] + l1 * math.cos(a - bend * k), hip[1] + l1 * math.sin(a - bend * k)


def rider(ctx, x, ground, roll, crank_a, elder, t, ring=0.0):
    pts = bike(ctx, x, ground, roll, (0.95, 0.95, 0.97) if elder is ELDERS[0] else (0.25, 0.75, 0.9))
    hip = (pts['seat'][0] + 4, pts['seat'][1] - 8)
    shoulder = (hip[0] + 34, hip[1] - 70)
    head = (shoulder[0] + 18, shoulder[1] - 34)
    # far leg, then the backpack, body, near leg
    for side, phase in ((-1, math.pi), (1, 0.0)):
        if side == 1:
            continue
        pedal = (pts['crank'][0] + 22 * math.cos(crank_a + phase), pts['crank'][1] + 22 * math.sin(crank_a + phase))
        limb(ctx, hip, knee(hip, pedal, 58, 56, -1), pedal, mix(SLACKS, WHITE, 0.08), 15)
    rounded_rect(ctx, hip[0] - 44, hip[1] - 82, 34, 56, 10)      # backpack
    ink_path(ctx, (0.12, 0.13, 0.18), 3, (2, 2))
    ctx.move_to(hip[0] - 10, hip[1] + 6)
    ctx.line_to(shoulder[0] - 14, shoulder[1] + 4)
    ctx.line_to(shoulder[0] + 16, shoulder[1] + 10)
    ctx.line_to(hip[0] + 14, hip[1] + 6)
    ctx.close_path()
    ink_path(ctx, SHIRT, 4, (3, 3))
    # tie, flying back in the wind
    flap = math.sin(t * 17 + x * 0.01) * 0.4
    ctx.move_to(shoulder[0] + 10, shoulder[1] + 10)
    ctx.curve_to(shoulder[0] - 10, shoulder[1] + 4 + flap * 10, shoulder[0] - 34, shoulder[1] + 2 - flap * 14,
                 shoulder[0] - 52, shoulder[1] + 6 + flap * 12)
    ctx.line_to(shoulder[0] - 46, shoulder[1] + 16 + flap * 10)
    ctx.curve_to(shoulder[0] - 30, shoulder[1] + 14, shoulder[0] - 8, shoulder[1] + 18, shoulder[0] + 10, shoulder[1] + 20)
    ctx.close_path()
    ink_path(ctx, elder['tie'], 2, (1, 1))
    pedal = (pts['crank'][0] + 22 * math.cos(crank_a), pts['crank'][1] + 22 * math.sin(crank_a))
    limb(ctx, hip, knee(hip, pedal, 58, 56, -1), pedal, SLACKS, 16)
    ellipse(ctx, pedal[0] + 6, pedal[1] + 2, 13, 6)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    # arm to the grip; a thumb flick on the bell
    grip = pts['grip']
    thumb = (grip[0] + 10 * ring, grip[1] - 6 * ring)
    limb(ctx, (shoulder[0] + 2, shoulder[1] + 8), ((shoulder[0] + grip[0]) / 2 + 4, (shoulder[1] + grip[1]) / 2 + 14), thumb,
         elder['skin'], 11)
    ctx.move_to(shoulder[0] - 6, shoulder[1] + 2)        # short sleeve
    ctx.line_to(shoulder[0] + 16, shoulder[1] + 4)
    ctx.line_to(shoulder[0] + 14, shoulder[1] + 26)
    ctx.line_to(shoulder[0] - 4, shoulder[1] + 24)
    ctx.close_path()
    ink_path(ctx, SHIRT, 3, (0, 0))
    # head in profile, the helmet over it
    circle(ctx, head[0], head[1], 22)
    ink_path(ctx, elder['skin'], 4, (3, 3))
    circle(ctx, head[0] + 10, head[1] - 2, 3)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.arc(head[0] + 12, head[1] + 8, 7, 0.2, 1.6)
    ctx.set_line_width(2.5)
    ctx.stroke()
    ctx.move_to(head[0] - 26, head[1] - 4)
    ctx.curve_to(head[0] - 22, head[1] - 36, head[0] + 20, head[1] - 38, head[0] + 28, head[1] - 10)
    ctx.line_to(head[0] - 26, head[1] - 4)
    ctx.close_path()
    ink_path(ctx, elder['helmet'], 3, (2, 2))
    for k in range(3):
        ctx.move_to(head[0] - 14 + k * 12, head[1] - 26)
        ctx.line_to(head[0] - 10 + k * 12, head[1] - 12)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(2)
    ctx.stroke()
    if ring > 0.02:                                      # the bell rings
        bx, by = pts['bell']
        for k in range(3):
            ctx.arc(bx, by, 10 + k * 9 + 8 * ring, -2.4, -0.8)
            ctx.set_source_rgba(*INK, 0.85 * ring)
            ctx.set_line_width(3)
            ctx.stroke()
        label(ctx, 'RING!', bx + 14, by - 36 - 10 * ring, 22, YELLOW, face='URW Gothic', tracking=2)


def street(ctx, t):
    pan = -150 * ease_in_out(span(t, 0.0, 1.85))
    ctx.set_source_surface(street_surface(), pan, 0)
    ctx.paint()
    for k, elder in enumerate(ELDERS[::-1]):
        lead = k == 1                                    # the front rider is the second drawn
        start, stop = (-360, 820) if lead else (-620, 470)
        p = ease_out(span(t, *RIDE), 2.2)
        x = start + (stop - start) * p
        dist = (stop - start) * p
        roll = dist / 44
        bell = BELLS[1] if lead else BELLS[0]
        ring = math.exp(-max(0, t - bell) * 5) if t >= bell else 0.0
        ground = 704 if lead else 668
        ctx.save()
        ctx.translate(x, ground)
        ctx.scale(1.42, 1.42)
        ctx.translate(-x, -ground)
        rider(ctx, x, ground, roll, roll * 0.55, elder, t, ring)
        ctx.restore()


# ---------------------------------------------------------------- 2. the stoop, from behind

@lru_cache(maxsize=None)
def stoop_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(*FACADES[3])
    ctx.paint()
    ctx.set_source_rgba(*INK, 0.12)
    for y in range(0, H, 22):
        for x in range(0, W, 64):
            ctx.rectangle(x + (32 if (y // 22) % 2 else 0), y, 62, 20)
    ctx.set_line_width(2)
    ctx.stroke()
    # the door frame, the transom with 19, the sidelights
    ctx.rectangle(440, 40, 400, 560)
    ink_path(ctx, CREAM, 5, (0, 0))
    ctx.rectangle(470, 60, 340, 70)
    ink_path(ctx, (0.62, 0.8, 0.95), 4, (0, 0))
    label(ctx, '19', 640, 112, 46, BRASS, face='C059')
    for sx in (470, 760):
        ctx.rectangle(sx, 150, 50, 430)
        ink_path(ctx, (0.62, 0.8, 0.95), 4, (0, 0))
    ctx.rectangle(520, 150, 240, 430)                    # the dark of the doorway behind the door
    ctx.set_source_rgb(0.28, 0.18, 0.12)
    ctx.fill()
    # doorbell, a mat, potted mums, the top step
    rounded_rect(ctx, 848, 334, 26, 40, 6)
    ink_path(ctx, BRASS, 3, (2, 2))
    ctx.rectangle(0, 590, W, H - 590)
    ink_path(ctx, (0.82, 0.8, 0.76), 4, (0, 0))
    for px in (330, 950):
        ctx.move_to(px - 50, 600)
        ctx.line_to(px - 40, 520)
        ctx.line_to(px + 40, 520)
        ctx.line_to(px + 50, 600)
        ctx.close_path()
        ink_path(ctx, (0.75, 0.38, 0.22), 4, (4, 3))
        rand = random.Random(px)
        for k in range(18):
            circle(ctx, px + rand.uniform(-46, 46), 500 + rand.uniform(-36, 18), rand.uniform(9, 14))
        ink_path(ctx, (0.98, 0.62, 0.15), 2, (0, 0))
    return surface


def back_view(ctx, x, y, s, elder, arm=0.0):
    """An elder from behind, waist up: the backpack, the shirt, the neat hair; arm lifts to the bell."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.move_to(-90, 80)
    ctx.curve_to(-96, -60, -80, -160, 0, -168)
    ctx.curve_to(80, -160, 96, -60, 90, 80)
    ctx.close_path()
    ink_path(ctx, SHIRT, 5, (5, 5))
    ctx.move_to(-20, -168)                                # a crease down the back
    ctx.line_to(-10, 60)
    ctx.set_source_rgba(*INK, 0.15)
    ctx.set_line_width(4)
    ctx.stroke()
    rounded_rect(ctx, -62, -120, 124, 170, 26)            # backpack, straps over the shoulders
    ink_path(ctx, (0.12, 0.13, 0.18), 4, (4, 4))
    rounded_rect(ctx, -44, -40, 88, 60, 14)
    ink_path(ctx, (0.18, 0.2, 0.26), 3, (0, 0))
    circle(ctx, 0, -230, 70)                               # head, all hair from behind, ears
    ink_path(ctx, elder['skin'], 5, (4, 4))
    for sx in (-1, 1):
        ellipse(ctx, sx * 70, -228, 14, 20)
        ink_path(ctx, elder['skin'], 4, (0, 0))
    ctx.arc(0, -232, 71, math.pi * 0.95, TAU + math.pi * 0.05)
    ctx.curve_to(60, -180, -60, -180, -71, -238)
    ctx.close_path()
    ink_path(ctx, elder['hair'], 4, (0, 0))
    if arm > 0:                                           # his near arm, up to the doorbell beside his head
        hand = (-70 - 22 * arm, -110 - 112 * arm)
        limb(ctx, (-74, -128), (-118 + 10 * arm, -120 - 40 * arm), hand, SHIRT if arm < 0.3 else elder['skin'], 24)
        circle(ctx, hand[0], hand[1], 14)
        ink_path(ctx, elder['skin'], 3, (2, 2))
        ctx.move_to(hand[0] + 4, hand[1] - 10)
        ctx.line_to(hand[0] + 10, hand[1] - 26)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(14)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
        ctx.move_to(hand[0] + 4, hand[1] - 10)
        ctx.line_to(hand[0] + 10, hand[1] - 26)
        ctx.set_source_rgb(*elder['skin'])
        ctx.set_line_width(8)
        ctx.stroke()
    ctx.restore()


def stoop(ctx, t):
    ctx.set_source_surface(stoop_surface(), 0, 0)
    ctx.paint()
    # the door: swinging in, narrowing to its hinge on the left
    o = ease_in_out(span(t, *DOOR_OPEN))
    if o > 0:
        glow = cairo.LinearGradient(520, 0, 760, 0)
        glow.add_color_stop_rgb(0, 0.99, 0.85, 0.6)
        glow.add_color_stop_rgb(1, 0.95, 0.7, 0.45)
        ctx.rectangle(520, 150, 240, 430)
        ctx.set_source(glow)
        ctx.fill()
    dw = 240 * (1 - 0.86 * o)
    ctx.rectangle(520, 150, dw, 430)
    ink_path(ctx, mix(DOOR, INK, 0.2 * o), 4, (0, 0))
    if dw > 60:
        for py in (180, 380):
            rounded_rect(ctx, 540 * (1 - o) + 524 * o, py, (dw - 40), 170, 6)
            ctx.set_source_rgba(*INK, 0.25)
            ctx.set_line_width(4)
            ctx.stroke()
        circle(ctx, 520 + dw - 26, 380, 9)
        ink_path(ctx, BRASS, 2, (0, 0))
    # the chime: notes out of the house, the button lit
    press = math.exp(-max(0, t - PRESS) * 3) if t >= PRESS else 0
    if press > 0:
        circle(ctx, 861, 354, 8)
        ctx.set_source_rgba(1.0, 0.95, 0.5, press)
        ctx.fill()
    for when, dx in zip(CHIME, (-120, 120)):
        q = span(t, when, when + 0.9)
        if 0 < q < 1:
            nx, ny = 640 + dx * q, 250 - 120 * q
            ctx.save()
            ctx.translate(nx, ny)
            ctx.rotate(0.3 * math.sin(q * 6))
            ellipse(ctx, 0, 0, 16, 12)
            ink_path(ctx, YELLOW, 3, (3, 3))
            ctx.rectangle(12, -60, 6, 60)
            ink_path(ctx, YELLOW, 3, (3, 3))
            ctx.restore()
            label(ctx, 'DING' if when == CHIME[0] else 'DONG', nx, ny - 76, 34, YELLOW, face='URW Gothic', tracking=3)
    # the two of them from behind, on the top step
    lift = span(t, PRESS - 0.08, PRESS + 0.06) * (1 - span(t, CHIME[1] + 0.1, CHIME[1] + 0.5))
    back_view(ctx, 330, 610, 1.15, ELDERS[0])
    back_view(ctx, 965, 622, 1.2, ELDERS[1], arm=ease_out(lift))


# ---------------------------------------------------------------- 3. the doorway, from inside

@lru_cache(maxsize=None)
def doorway_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    # outside, bright: the street across the way
    g = cairo.LinearGradient(0, 0, 0, 400)
    g.add_color_stop_rgb(0, *SKY_TOP)
    g.add_color_stop_rgb(1, *SKY_LOW)
    ctx.set_source(g)
    ctx.paint()
    ctx.save()
    ctx.translate(-200, -60)
    ctx.scale(1.25, 1.25)
    for k, x in enumerate((0, 260, 520, 780)):
        rowhouse(ctx, x, 260, 170 + (k % 2) * 16, FACADES[(k + 2) % 5], None, 40 + k, turret=k == 2)
    ctx.restore()
    ctx.rectangle(0, 590, W, H)
    ctx.set_source_rgb(0.72, 0.42, 0.33)
    ctx.fill()
    for x in (150, 1100):
        tree(ctx, x, 620, 80, x)
    # inside: the hall wall around the doorway, the open door, a coat hook
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.rectangle(0, 0, W, H)
    ctx.rectangle(270, 40, 740, 720)
    ctx.set_source_rgb(0.93, 0.86, 0.72)
    ctx.fill()
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
    ctx.set_source_rgba(0.6, 0.45, 0.3, 0.25)
    for x in range(0, W, 40):
        ctx.rectangle(x, 0, 20, H)
    ctx.fill()
    ctx.rectangle(270, 40, 740, 720)
    ctx.set_source_rgb(*CREAM)
    ctx.set_line_width(26)
    ctx.stroke()
    ctx.rectangle(255, 27, 770, 720)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.move_to(1010, 40)                                  # the door, swung in against the wall
    ctx.line_to(1150, 0)
    ctx.line_to(1150, H)
    ctx.line_to(1010, H)
    ctx.close_path()
    ink_path(ctx, DOOR, 5, (0, 0))
    return surface


def elder_front(ctx, x, y, s, elder, mouth=0.0, offer=0.0, wave=0.0, t=0.0):
    """An elder from the front, waist up, beaming: white shirt, tie, name tag."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.move_to(-110, 260)                                 # shirt
    ctx.curve_to(-118, 60, -96, -40, 0, -48)
    ctx.curve_to(96, -40, 118, 60, 110, 260)
    ctx.close_path()
    ink_path(ctx, SHIRT, 5, (5, 5))
    for sx in (-1, 1):                                     # sleeves, short
        ctx.move_to(sx * 88, -30)
        ctx.line_to(sx * 132, 40)
        ctx.line_to(sx * 104, 66)
        ctx.line_to(sx * 80, 20)
        ctx.close_path()
        ink_path(ctx, SHIRT, 4, (0, 0))
    ctx.move_to(-22, -46)                                  # collar
    ctx.line_to(0, -12)
    ctx.line_to(22, -46)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.move_to(-11, -26)                                  # tie
    ctx.line_to(11, -26)
    ctx.line_to(16, 120)
    ctx.line_to(0, 142)
    ctx.line_to(-16, 120)
    ctx.close_path()
    ink_path(ctx, elder['tie'], 3, (2, 2))
    ctx.rectangle(-48, 18, 30, 4)                          # pocket
    ctx.set_source_rgba(*INK, 0.3)
    ctx.fill()
    name_tag(ctx, 24, 6, 0.95, elder['name'])
    for sx in (-1, 1):                                     # backpack straps
        ctx.move_to(sx * 70, -40)
        ctx.curve_to(sx * 84, 40, sx * 90, 120, sx * 86, 200)
        ctx.set_source_rgb(0.12, 0.13, 0.18)
        ctx.set_line_width(14)
        ctx.stroke()
    # arms: one out with the pamphlet, or a wave; else at the sides
    for sx in (-1, 1):
        if sx == 1 and offer > 0:
            hand = (60 + 40 * offer, 80 - 40 * offer)
        elif sx == -1 and wave > 0:
            hand = (-150, -60 + 14 * math.sin(t * 16))
        else:
            hand = (sx * 128, 200)
        limb(ctx, (sx * 112, 50), (sx * 128 + (hand[0] - sx * 128) * 0.5, 130 + (hand[1] - 130) * 0.5 + 20), hand,
             elder['skin'], 26)
        circle(ctx, hand[0], hand[1], 18)
        ink_path(ctx, elder['skin'], 3, (2, 2))
    face(ctx, 0, -120, 74, elder['skin'], elder['hair'], mouth=mouth, side_part=1 if elder is ELDERS[0] else -1)
    ctx.restore()


def pamphlet(ctx, x, y, s, rot):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rot)
    ctx.scale(s, s)
    rounded_rect(ctx, -110, -150, 220, 300, 6)
    ink_path(ctx, CREAM, 5, (6, 6))
    ctx.rectangle(-110, -150, 220, 92)
    ink_path(ctx, TEAL, 5, (0, 0))
    label(ctx, 'THE GOOD NEWS', 0, -114, 26, (1, 1, 1), face='URW Gothic', tracking=1.5)
    label(ctx, 'ABOUT', 0, -78, 20, YELLOW, face='URW Gothic', tracking=4)
    label(ctx, 'CHANNEL 19', 0, -18, 34, PINK, face='URW Gothic', tracking=1)
    ctx.save()
    ctx.translate(0, 72)
    ctx.scale(0.36, 0.36)
    A.draw_tv(ctx, 0.0, 1, 0)
    ctx.restore()
    label(ctx, 'VIZELVISION', 0, 138, 15, (0.3, 0.3, 0.35), face='URW Gothic', tracking=3)
    ctx.restore()


def talking(t, start, length, rate=11.0):
    if not start <= t <= start + length:
        return 0.0
    return 0.5 + 0.5 * math.sin((t - start) * rate * 2) * math.sin((t - start) * rate * 0.7 + 1)


def doorway(ctx, t):
    ctx.set_source_surface(doorway_surface(), 0, 0)
    ctx.paint()
    lean = math.sin((t - INSIDE_CUT) * 3) * 4
    offer = ease_out(span(t, *PAMPHLET))
    elder_front(ctx, 480 + lean, 470, 1.0, ELDERS[0], mouth=talking(t, HI, 3.0), wave=span(t, INSIDE_CUT, INSIDE_CUT + 0.15)
                * (1 - span(t, HI + 1.0, HI + 1.2)), t=t)
    elder_front(ctx, 800 - lean, 490, 0.98, ELDERS[1], mouth=0.0, offer=offer, t=t)
    if offer > 0:
        pamphlet(ctx, 900 + 60 * offer, 560 - 120 * offer, 0.5 + 0.55 * offer, -0.12 * (1 - offer) + 0.05)


# ---------------------------------------------------------------- 4. the living room, from the TV

COUCH_Y = 430                                              # the seat's front edge


@lru_cache(maxsize=None)
def room_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.95, 0.88, 0.74)                     # wallpaper: stripes and little flowers
    ctx.paint()
    for x in range(0, W, 48):
        ctx.rectangle(x, 0, 18, H)
    ctx.set_source_rgba(0.85, 0.7, 0.55, 0.35)
    ctx.fill()
    rand = random.Random(7)
    for _ in range(90):
        circle(ctx, rand.uniform(0, W), rand.uniform(0, 330), 3.5)
    ctx.set_source_rgba(0.85, 0.45, 0.45, 0.4)
    ctx.fill()
    # the window, top left (the sun comes through it on the closed logo)
    ctx.rectangle(40, 40, 220, 240)
    ink_path(ctx, (0.68, 0.86, 1.0), 5, (5, 5))
    ctx.rectangle(147, 40, 6, 240)
    ctx.rectangle(40, 157, 220, 6)
    ctx.set_source_rgb(*CREAM)
    ctx.fill()
    for sx in (30, 250):
        ctx.rectangle(sx, 30, 22, 270)
        ink_path(ctx, (0.85, 0.42, 0.35), 3, (3, 3))
    # the sign on the wall
    rounded_rect(ctx, 870, 70, 320, 92, 10)
    ink_path(ctx, (0.58, 0.4, 0.26), 4, (5, 5))
    label(ctx, 'Families', 1030, 112, 34, CREAM, face='Z003', bold=False)
    label(ctx, 'ARE FOREVER', 1030, 146, 20, CREAM, face='URW Gothic', tracking=5)
    # the couch: back and arms (the cushions are drawn with the people)
    rounded_rect(ctx, 130, 200, 1020, 210, 50)
    ink_path(ctx, SAGE, 6, (8, 6))
    for x in (100, 1110):
        rounded_rect(ctx, x, 280, 70, 230, 30)
        ink_path(ctx, mix(SAGE, INK, 0.08), 5, (5, 5))
    ctx.rectangle(0, 560, W, H - 560)                        # the rug
    ctx.set_source_rgb(0.72, 0.36, 0.3)
    ctx.fill()
    return surface


def sitter(ctx, x, s, look, t, colour, pants, hair_style='short', mouth=0.0, extra=None):
    """Someone on the couch, facing the TV (us): body, lap, legs, a face."""
    ctx.save()
    ctx.translate(x, COUCH_Y)
    ctx.scale(s, s)
    for sx in (-1, 1):                                       # shins and feet
        rounded_rect(ctx, sx * 30 - 16, 20, 32, 120, 14)
        ink_path(ctx, pants, 4, (3, 3))
        ellipse(ctx, sx * 30, 142, 24, 12)
        ink_path(ctx, (0.25, 0.2, 0.18), 3, (2, 2))
    rounded_rect(ctx, -66, -30, 132, 60, 26)                   # lap
    ink_path(ctx, pants, 4, (3, 3))
    ctx.move_to(-62, -10)                                    # body
    ctx.curve_to(-70, -120, -50, -160, 0, -164)
    ctx.curve_to(50, -160, 70, -120, 62, -10)
    ctx.close_path()
    ink_path(ctx, colour, 5, (4, 4))
    for sx in (-1, 1):
        limb(ctx, (sx * 56, -130), (sx * 72, -60), (sx * 34, -30), colour, 24)
        circle(ctx, sx * 30, -30, 15)
        ink_path(ctx, look['skin'], 3, (2, 2))
    if extra:
        extra(ctx)
    hair = look['hair']
    if hair_style == 'bun':
        circle(ctx, 0, -290, 30)
        ink_path(ctx, hair, 4, (3, 3))
    if hair_style == 'long':
        rounded_rect(ctx, -62, -270, 124, 140, 40)
        ink_path(ctx, hair, 4, (3, 3))
    face(ctx, 0, -214, 56, look['skin'], hair, mouth=mouth, blink=look.get('blink', 0))
    ctx.restore()


FAMILY = (
    {'skin': (0.86, 0.66, 0.5), 'hair': (0.24, 0.16, 0.1), 'top': (0.3, 0.45, 0.7), 'pants': (0.32, 0.33, 0.4), 'style': 'short', 's': 1.0},
    {'skin': (0.95, 0.78, 0.64), 'hair': (0.7, 0.42, 0.18), 'top': (0.85, 0.35, 0.45), 'pants': (0.3, 0.3, 0.42), 'style': 'long', 's': 0.97},
    {'skin': (0.92, 0.74, 0.6), 'hair': (0.82, 0.62, 0.3), 'top': (0.98, 0.78, 0.2), 'pants': (0.35, 0.5, 0.75), 'style': 'short', 's': 0.72},
    {'skin': (0.95, 0.8, 0.7), 'hair': (0.88, 0.88, 0.9), 'top': (0.55, 0.42, 0.62), 'pants': (0.4, 0.36, 0.38), 'style': 'bun', 's': 0.92},
)


def couch_slots(t):
    """x of each sitter: the family spread out, then shoved up for the elders at the ends."""
    q = ease_in_out(span(t, SQUEEZE[0] + 0.45, SQUEEZE[1]))
    spread = (300, 530, 730, 960)
    tight = (370, 540, 690, 850)
    return [a + (b - a) * q for a, b in zip(spread, tight)], q


def jello(ctx, t):
    """The green Jell-O ring on its plate, wobbling at every hit."""
    wob = 0.0
    for hit in (ROOM_CUT, SQUEEZE[1] - 0.15, CLOSED, CLOSED + 0.25, CLOSED + 0.5, CLOSED + 1.0):
        if t >= hit:
            wob += 0.12 * math.exp(-(t - hit) * 5) * math.sin((t - hit) * 30)
    x, y = 640, 640
    ellipse(ctx, x, y + 34, 150, 30)
    ink_path(ctx, (0.96, 0.96, 0.98), 4, (5, 5))
    ctx.save()
    ctx.translate(x, y + 30)
    ctx.scale(1 + wob, 1 - wob)
    ctx.move_to(-100, 0)
    ctx.curve_to(-104, -70, -60, -96, 0, -96)
    ctx.curve_to(60, -96, 104, -70, 100, 0)
    ctx.close_path()
    g = cairo.LinearGradient(0, -96, 0, 0)
    g.add_color_stop_rgb(0, *mix(JELLO, WHITE, 0.35))
    g.add_color_stop_rgb(1, JELLO[0] * 0.8, JELLO[1] * 0.85, JELLO[2] * 0.8)
    ink_path(ctx, g, 4, (0, 0))
    for k, (fx, fy) in enumerate(((-60, -30), (-20, -60), (30, -40), (66, -24), (-36, -70), (10, -20))):
        circle(ctx, fx, fy, 8)
        ctx.set_source_rgba(*((1.0, 0.55, 0.15) if k % 2 else (0.95, 0.2, 0.3)), 0.75)
        ctx.fill()
    ellipse(ctx, 0, -92, 34, 7)
    ctx.set_source_rgb(0.95, 0.85, 0.8)
    ctx.fill()
    ctx.move_to(-70, -60)
    ctx.curve_to(-60, -82, -30, -88, -10, -88)
    ctx.set_source_rgba(1, 1, 1, 0.65)
    ctx.set_line_width(6)
    ctx.stroke()
    ctx.restore()


def beehive_pillow(ctx, x, y, s):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.rotate(-0.08)
    rounded_rect(ctx, -60, -56, 120, 112, 28)
    ink_path(ctx, HONEY, 4, (4, 4))
    for k in range(4):                                         # a skep: stacked coils
        w = 62 - k * 12
        rounded_rect(ctx, -w / 2, 22 - k * 16, w, 16, 8)
        ink_path(ctx, (0.75, 0.5, 0.15), 2, (0, 0))
    ctx.arc(0, 30, 7, math.pi, TAU)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    for bx, by in ((-34, -30), (32, -36)):
        ellipse(ctx, bx, by, 7, 5)
        ctx.set_source_rgb(*INK)
        ctx.fill()
        ellipse(ctx, bx - 2, by - 6, 5, 3)
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.fill()
    ctx.restore()


def room(ctx, t):
    ctx.set_source_surface(room_surface(), 0, 0)
    ctx.paint()
    # the sun through the window on the closed logo
    sun = ease_out(span(t, *SUNBEAMS))
    if sun > 0:
        for k in range(5):
            ctx.move_to(60 + k * 44, 50)
            ctx.line_to(110 + k * 44, 50)
            ctx.line_to(700 + k * 120, 720)
            ctx.line_to(540 + k * 120, 720)
            ctx.close_path()
        ctx.set_source_rgba(1.0, 0.95, 0.7, 0.22 * sun)
        ctx.fill()
    slots, squeeze = couch_slots(t)
    # cushions
    for k in range(3):
        rounded_rect(ctx, 175 + k * 315, 380 - 14 * squeeze, 300, 90, 26)
        ink_path(ctx, mix(SAGE, WHITE, 0.12), 5, (4, 4))
    beehive_pillow(ctx, 170 + 40 * squeeze, 350, 0.9)
    tv_glow = 0.5 + 0.5 * math.sin(t * 9) * math.sin(t * 3.7)
    # the elders arrive from the ends and sit
    for k, elder in enumerate(ELDERS):
        enter = ease_out(span(t, SQUEEZE[0] + 0.1 * k, SQUEEZE[0] + 0.1 * k + 0.6))
        sit = ease_in_out(span(t, SQUEEZE[0] + 0.6, SQUEEZE[1]))
        if enter <= 0:
            continue
        end_x = 190 if k == 0 else 1090
        from_x = -160 if k == 0 else W + 160
        x = from_x + (end_x - from_x) * enter
        lift = (1 - sit) * -60
        look = {'skin': elder['skin'], 'hair': elder['hair']}

        def tie_and_tag(c, elder=elder):
            c.move_to(-9, -150)
            c.line_to(9, -150)
            c.line_to(12, -40)
            c.line_to(0, -26)
            c.line_to(-12, -40)
            c.close_path()
            inked = __import__('common').inked
            inked(c, elder['tie'], 3, (2, 2))
            name_tag(c, 14, -128, 0.62, elder['name'])

        ctx.save()
        ctx.translate(0, lift)
        mouth = max(talking(t, TOGETHER, 1.7), talking(t, FOREVER + 0.3, 0.5)) if k == 1 else 0
        sitter(ctx, x, 0.98, look, t, SHIRT, SLACKS, mouth=mouth, extra=tie_and_tag)
        ctx.restore()
    for k, (person, x) in enumerate(zip(FAMILY, slots)):
        look = {'skin': person['skin'], 'hair': person['hair'], 'blink': 1 if k == 3 and t > CLOSED + 0.4 else 0}

        def knit(c, k=k):
            if k != 3:
                return
            c.move_to(-26, -40)
            c.line_to(20, -64)
            c.move_to(26, -40)
            c.line_to(-20, -64)
            c.set_source_rgb(*INK)
            c.set_line_width(4)
            c.stroke()
            ellipse(c, 0, -34, 26, 16)
            inked = __import__('common').inked
            inked(c, (0.95, 0.4, 0.5), 3, (2, 2))

        bob = 4 * math.sin(t * 2 + k) + (8 * math.exp(-(t - CLOSED) * 3) * math.sin((t - CLOSED) * 20) if t > CLOSED else 0)
        ctx.save()
        ctx.translate(0, bob)
        sitter(ctx, x, person['s'], look, t, person['top'], person['pants'], hair_style=person['style'],
               mouth=0.3 if t > CLOSED + 0.1 else 0.0, extra=knit)
        ctx.restore()
    # the TV's light on them, flickering
    ctx.rectangle(0, 0, W, H)
    ctx.set_source_rgba(0.55, 0.75, 1.0, 0.05 + 0.04 * tv_glow)
    ctx.fill()
    # the coffee table and the Jell-O, in front
    rounded_rect(ctx, 330, 650, 620, 120, 20)
    ink_path(ctx, (0.55, 0.36, 0.22), 5, (0, -6))
    jello(ctx, t)
    # the pamphlet left on the table, and on the closed logo a sticky note on it
    pamphlet(ctx, 880, 690, 0.32, 0.25)
    n = span(t, TUESDAY, TUESDAY + 0.25)
    if n > 0:
        ctx.save()
        ctx.translate(905, 655)
        ctx.rotate(-0.12)
        ctx.scale(back_out(n), back_out(n))
        ctx.rectangle(-58, -40, 116, 80)
        ink_path(ctx, (1.0, 0.92, 0.35), 3, (3, 3))
        label(ctx, 'SEE YOU', 0, -6, 20, INK, face='Z003', bold=False)
        label(ctx, 'TUESDAY!', 0, 22, 24, INK, face='Z003', bold=False)
        ctx.restore()
    # the closed logo: the wordmark and the line
    neighborhood.lockup(ctx, t, LOCKUP, 150, scale=0.5)
    p = span(t, *SUBTITLE)
    if p > 0:
        ctx.save()
        ctx.translate(640, 196)
        ctx.scale(0.8 + 0.2 * back_out(p), 0.8 + 0.2 * back_out(p))
        rounded_rect(ctx, -330, -22, 660, 44, 22)
        ink_path(ctx, PINK, 4, (4, 4))
        label(ctx, 'FAMILIES CAN WATCH TOGETHER FOREVER', 0, 10, 26, (1, 1, 1), face='URW Gothic', tracking=2)
        ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    if t < DOOR_CUT:
        street(ctx, t)
    elif t < INSIDE_CUT:
        stoop(ctx, t)
    elif t < ROOM_CUT:
        doorway(ctx, t)
    else:
        room(ctx, t)
    vignette(ctx, 0.35)
    grain(ctx, frame, 0.22)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
