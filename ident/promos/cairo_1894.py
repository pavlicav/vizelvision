"""The Cairo, 1894: a silent film. Sepia, flickering, scratched, the picture weaving in
the gate and moving at sixteen frames a second. Q Street: The Cairo towers over its
three-storey neighbours, and a horse-drawn ladder wagon pulls up. Its ladder runs up the
front a section on each note of the open logo and stops, well short, at the seventh
floor; the fireman at the top looks up at the five more above him, and shrugs.

Title cards: "TOO TALL!" said the Fire Chief. / And so, in 1899, Congress capped the city.
Back on Q Street a mast sprouts from the roof with a spark, and on the closed logo the
last card: VIZELVISION, still on top since 1894. Channel 19. The iris closes.

No voice, as befits it: a ragtime piano and the projector.
"""
import math
import random
from functools import lru_cache

import cairo

from common import (TAU, W, H, back_out, clamp, ease_in, ease_in_out, ease_out, grain, iris, span,  # noqa: F401
                    text_path)

ID = 'cairo-1894'
NAME = 'The Cairo, 1894'
KIND = 'ident'
ORDER = 17
DESCRIPTION = ('A sepia silent film: the fire ladder runs up The Cairo a section a note and stops at the seventh '
               'floor; "TOO TALL!" said the Fire Chief, and Congress capped the city in 1899. VizelVision, still on '
               'top since 1894. Ragtime piano, no voice.')
DURATION = 10.0
STILL_AT = 8.2
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
LEADER = (0.0, 0.35)                           # the film's leader flashes through
WAGON = (0.35, 0.95)                           # the ladder wagon trots in
LADDER = (1.0, 1.25, 1.5, 2.0)                 # the open logo: a section each
CLIMB = (2.15, 2.6)                            # the fireman climbs to the top
SHRUG = (2.7, 3.05)
CARD_1 = (3.2, 4.9)                            # "TOO TALL!" said the Fire Chief.
CARD_2 = (4.9, 6.6)                            # And so, in 1899, Congress capped the city.
MAST = 6.75                                    # back on the street: the mast sprouts, a spark
FINAL = 7.0                                    # the closed logo: the last card
IRIS = (9.0, 9.45)

FPS_FILM = 16
STREET = 610
CAIRO = (520, 820)                             # its front's edges
CAIRO_TOP = 120
FLOOR_PX = (STREET - CAIRO_TOP - 40) / 12
SECTION = 50                                   # each ladder section, in px along the ladder


def sepia(v, a=1.0):
    """A grey (0 black .. 1 white) as the film's brown-cream."""
    return (min(1.0, v * 1.04 + 0.02), v * 0.88 + 0.02, v * 0.68 + 0.02, a)


def fill(ctx, v):
    ctx.set_source_rgba(*sepia(v))
    ctx.fill()


# ---------------------------------------------------------------- Q Street, 1894

def street(ctx, t):
    g = cairo.LinearGradient(0, 0, 0, STREET)
    g.add_color_stop_rgba(0, *sepia(0.82))
    g.add_color_stop_rgba(1, *sepia(0.68))
    ctx.set_source(g)
    ctx.paint()
    for x0, x1, storeys in ((0, 170, 3), (170, 345, 3), (345, 520, 4), (820, 980, 3), (980, 1140, 4), (1140, W, 3)):
        top = STREET - storeys * 48 - 20
        ctx.rectangle(x0, top, x1 - x0, STREET - top)
        fill(ctx, 0.48 + 0.06 * ((x0 // 170) % 2))
        ctx.rectangle(x0 - 4, top - 10, x1 - x0 + 8, 12)
        fill(ctx, 0.3)
        for s in range(storeys):
            for k in range(3):
                ctx.rectangle(x0 + 24 + k * (x1 - x0 - 60) / 2, top + 22 + s * 48, 24, 30)
                fill(ctx, 0.2)
    left, right = CAIRO
    ctx.rectangle(left, CAIRO_TOP, right - left, STREET - CAIRO_TOP)
    fill(ctx, 0.4)
    ctx.rectangle(left, STREET - 2 * FLOOR_PX - 30, right - left, 2 * FLOOR_PX + 30)   # the stone floors
    fill(ctx, 0.66)
    for floor in range(12):
        y = STREET - 30 - (floor + 1) * FLOOR_PX
        for k in range(7):
            ctx.rectangle(left + 20 + k * 40, y + 8, 22, FLOOR_PX - 18)
            fill(ctx, 0.18)
    ctx.move_to(left + 90, STREET)                                    # the arch
    ctx.line_to(left + 90, STREET - 50)
    ctx.curve_to(left + 90, STREET - 92, right - 90, STREET - 92, right - 90, STREET - 50)
    ctx.line_to(right - 90, STREET)
    ctx.close_path()
    fill(ctx, 0.12)
    ctx.move_to(left - 34, CAIRO_TOP + 6)                             # the projecting cap
    ctx.line_to(right + 34, CAIRO_TOP + 6)
    ctx.line_to(right + 18, CAIRO_TOP - 22)
    ctx.line_to(left - 18, CAIRO_TOP - 22)
    ctx.close_path()
    fill(ctx, 0.22)
    ctx.rectangle(0, STREET, W, H - STREET)                           # cobbles
    fill(ctx, 0.56)
    rand = random.Random(94)
    for _ in range(140):
        ctx.arc(rand.uniform(0, W), rand.uniform(STREET + 6, H), rand.uniform(3, 6), 0, TAU)
        ctx.set_source_rgba(*sepia(0.42, 0.5))
        ctx.fill()
    for lx in (120, 1160):                                            # gas lamps
        ctx.rectangle(lx - 3, STREET - 120, 6, 120)
        fill(ctx, 0.12)
        ctx.rectangle(lx - 10, STREET - 140, 20, 24)
        fill(ctx, 0.85)


def wagon_x(t):
    return -360 + 1020 * ease_out(span(t, *WAGON))   # stopping at the door


def wagon(ctx, t):
    """A ladder wagon and its horse, trotting in from the left and stopping by the door."""
    x = wagon_x(t)
    trot = math.sin(t * 22) * (1 - span(t, WAGON[1] - 0.1, WAGON[1]))
    ctx.save()
    ctx.translate(x, STREET)
    ctx.rectangle(-150, -64, 180, 30)                                 # the wagon's bed
    fill(ctx, 0.25)
    for wx in (-130, 10):
        ctx.arc(wx, -22, 22, 0, TAU)
        ctx.set_source_rgba(*sepia(0.15))
        ctx.set_line_width(5)
        ctx.stroke()
        for k in range(6):
            a = k * TAU / 6 + (x / 22)
            ctx.move_to(wx, -22)
            ctx.line_to(wx + 22 * math.cos(a), -22 + 22 * math.sin(a))
        ctx.set_line_width(2)
        ctx.stroke()
    ctx.rectangle(60, -78 + 2 * trot, 110, 38)                        # the horse: body, legs, neck, head
    fill(ctx, 0.3)
    for lx, phase in ((68, 0), (88, 1.5), (148, 0.7), (164, 2.2)):
        swing = 8 * math.sin(t * 22 + phase) * (1 - span(t, WAGON[1] - 0.1, WAGON[1]))
        ctx.move_to(lx, -44)
        ctx.line_to(lx + swing, 0)
        ctx.set_source_rgba(*sepia(0.3))
        ctx.set_line_width(8)
        ctx.stroke()
    look = ease_in_out(span(t, CLIMB[1], CLIMB[1] + 0.3))             # the horse looks up too
    ctx.save()
    ctx.translate(166, -74)
    ctx.rotate(-0.6 - 0.5 * look)
    ctx.rectangle(0, -10, 50, 20)
    fill(ctx, 0.3)
    ctx.rectangle(40, -14, 30, 22)
    fill(ctx, 0.32)
    ctx.restore()
    ctx.move_to(0, -64)                                               # the driver on his seat
    ctx.line_to(0, -96)
    ctx.set_source_rgba(*sepia(0.15))
    ctx.set_line_width(10)
    ctx.stroke()
    ctx.arc(0, -106, 9, 0, TAU)
    fill(ctx, 0.15)
    ctx.restore()


def ladder_length(t):
    n = sum(ease_out(span(t, when, when + 0.18)) for when in LADDER)
    return 32 + SECTION * n                         # the seventh floor, and no further


def ladder(ctx, t):
    """Leaning from the wagon to the front, longer by a section on each note."""
    if t < LADDER[0] - 0.4:
        return None
    foot = (wagon_x(t) - 60, STREET - 64)
    angle = -1.48                                                     # up the front, leaning a little
    length = ladder_length(t)
    top = (foot[0] + math.cos(angle) * length, foot[1] + math.sin(angle) * length)
    ctx.save()
    for side in (-9, 9):
        ctx.move_to(foot[0] + side, foot[1])
        ctx.line_to(top[0] + side, top[1])
    ctx.set_source_rgba(*sepia(0.12))
    ctx.set_line_width(5)
    ctx.stroke()
    steps = int(length / 18)
    for k in range(1, steps):
        u = k / steps
        x, y = foot[0] + (top[0] - foot[0]) * u, foot[1] + (top[1] - foot[1]) * u
        ctx.move_to(x - 9, y)
        ctx.line_to(x + 9, y)
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.restore()
    return foot, top


def fireman(ctx, t, ends):
    """Up the ladder; at the top he looks up at the floors still above him, and shrugs."""
    if ends is None or t < CLIMB[0]:
        return
    foot, top = ends
    u = ease_in_out(span(t, *CLIMB))
    x = foot[0] + (top[0] - foot[0]) * (0.25 + 0.68 * u)
    y = foot[1] + (top[1] - foot[1]) * (0.25 + 0.68 * u)
    shrug = math.sin(math.pi * span(t, *SHRUG))
    ctx.save()
    ctx.translate(x, y)
    ctx.move_to(0, 0)
    ctx.line_to(0, 34)
    ctx.set_source_rgba(*sepia(0.1))
    ctx.set_line_width(9)
    ctx.stroke()
    for side in (-1, 1):                                              # arms: on the rungs, then up and out
        ctx.move_to(0, 6 - 6 * shrug)
        ctx.line_to(side * (10 + 14 * shrug), -8 - 10 * shrug)
        ctx.set_line_width(5)
        ctx.stroke()
    ctx.arc(0, -10 - 4 * shrug, 8, 0, TAU)
    fill(ctx, 0.15)
    ctx.move_to(-12, -14 - 4 * shrug)                                 # the helmet's long brim
    ctx.line_to(14, -16 - 4 * shrug)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.restore()
    p = span(t, SHRUG[0] - 0.4, SHRUG[1] + 0.2)                       # a dotted look up to the cap
    if 0 < p < 1:
        ctx.set_dash([4, 8])
        ctx.move_to(x + 4, y - 20)
        ctx.line_to(CAIRO[0] + 120, CAIRO_TOP + 20)
        ctx.set_source_rgba(*sepia(0.1, 0.6 * math.sin(math.pi * p)))
        ctx.set_line_width(2)
        ctx.stroke()
        ctx.set_dash([])


def mast(ctx, t):
    """Back on Q Street, years on: a mast pushes up out of the roof, and sparks."""
    p = span(t, MAST, MAST + 0.2)
    if p <= 0:
        return
    x, base = (CAIRO[0] + CAIRO[1]) / 2, CAIRO_TOP - 22
    height = 64 * back_out(p, 2)
    ctx.move_to(x - 10, base)
    ctx.line_to(x, base - height)
    ctx.line_to(x + 10, base)
    ctx.set_source_rgba(*sepia(0.1))
    ctx.set_line_width(4)
    ctx.stroke()
    q = span(t, MAST + 0.1, MAST + 0.45)
    if 0 < q < 1:
        for k in range(8):
            a = k * TAU / 8
            ctx.move_to(x + math.cos(a) * 8, base - height + math.sin(a) * 8)
            ctx.line_to(x + math.cos(a) * (14 + 30 * q), base - height + math.sin(a) * (14 + 30 * q))
        ctx.set_source_rgba(*sepia(1.0, 1 - q))
        ctx.set_line_width(3)
        ctx.stroke()


# ---------------------------------------------------------------- the title cards

def card_frame(ctx):
    ctx.set_source_rgba(*sepia(0.05))
    ctx.paint()
    for inset, width in ((60, 3), (74, 1.5)):                         # a double rule with corner flourishes
        ctx.rectangle(inset, inset, W - 2 * inset, H - 2 * inset)
        ctx.set_source_rgba(*sepia(0.85))
        ctx.set_line_width(width)
        ctx.stroke()
    for cx, cy in ((90, 90), (W - 90, 90), (90, H - 90), (W - 90, H - 90)):
        for r in (10, 18):
            ctx.arc(cx, cy, r, 0, TAU)
            ctx.set_line_width(1.5)
            ctx.stroke()
        ctx.arc(cx, cy, 4, 0, TAU)
        ctx.fill()


def card_text(ctx, lines, y0, size, step, italic=(), weight=()):
    for k, line in enumerate(lines):
        ctx.select_font_face('C059', cairo.FONT_SLANT_ITALIC if k in italic else cairo.FONT_SLANT_NORMAL,
                             cairo.FONT_WEIGHT_BOLD if k in weight else cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(size[k] if isinstance(size, tuple) else size)
        ctx.new_path()
        text_path(ctx, line, W / 2, y0 + k * step, tracking=1.5, align='center')
        ctx.set_source_rgba(*sepia(0.92))
        ctx.fill()


def card(ctx, t):
    if CARD_1[0] <= t < CARD_1[1]:
        card_frame(ctx)
        card_text(ctx, ('"TOO TALL!"', 'said the Fire Chief.'), 330, (84, 48), 90, italic=(1,), weight=(0,))
        return True
    if CARD_2[0] <= t < CARD_2[1]:
        card_frame(ctx)
        card_text(ctx, ('And so, in 1899,', 'Congress capped the city.'), 330, 54, 84, italic=(0,))
        return True
    if t >= FINAL:
        card_frame(ctx)
        p = span(t, FINAL, FINAL + 0.3)
        ctx.save()
        ctx.translate(W / 2, 300)
        k = 0.9 + 0.1 * ease_out(p)
        ctx.scale(k, k)
        ctx.translate(-W / 2, -300)
        card_text(ctx, ('VIZELVISION',), 300, 104, 0, weight=(0,))
        ctx.restore()
        ctx.set_source_rgba(*sepia(0.85))                             # an ornament
        ctx.rectangle(W / 2 - 160, 338, 320, 2)
        ctx.fill()
        for dx in (-170, 170):
            ctx.arc(W / 2 + dx, 339, 4, 0, TAU)
            ctx.fill()
        q = span(t, FINAL + 0.5, FINAL + 0.8)
        if q > 0:
            ctx.push_group()
            card_text(ctx, ('Still on top since 1894.',), 410, 46, 0, italic=(0,))
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(q)
        q = span(t, FINAL + 1.0, FINAL + 1.3)
        if q > 0:
            ctx.push_group()
            card_text(ctx, ('~ CHANNEL 19 ~',), 500, 30, 0)
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(q)
        return True
    return False


# ---------------------------------------------------------------- the film itself

@lru_cache(maxsize=None)
def scratches(reel):
    rand = random.Random(reel)
    return [(rand.uniform(0, W), rand.uniform(0.3, 1.0), rand.random() < 0.5) for _ in range(rand.randint(1, 3))]


def damage(ctx, frame):
    rand = random.Random(frame)
    for x, alpha, dark in scratches(frame // 5):
        ctx.rectangle(x + rand.uniform(-2, 2), 0, 1.5, H)
        ctx.set_source_rgba(*(sepia(0.05, 0.35 * alpha) if dark else sepia(1.0, 0.4 * alpha)))
        ctx.fill()
    for _ in range(rand.randint(2, 7)):                               # dust and hair
        x, y = rand.uniform(0, W), rand.uniform(0, H)
        if rand.random() < 0.8:
            ctx.arc(x, y, rand.uniform(1, 3.5), 0, TAU)
            ctx.set_source_rgba(*sepia(0.0 if rand.random() < 0.6 else 1.0, 0.7))
            ctx.fill()
        else:
            ctx.move_to(x, y)
            ctx.curve_to(x + 20, y + 10, x - 10, y + 30, x + 14, y + 44)
            ctx.set_source_rgba(*sepia(0.05, 0.6))
            ctx.set_line_width(1.2)
            ctx.stroke()
    flicker = rand.uniform(-0.06, 0.06)
    ctx.set_source_rgba(*(sepia(1.0, flicker) if flicker > 0 else sepia(0.0, -flicker)))
    ctx.paint()
    g = cairo.RadialGradient(W / 2, H / 2, H * 0.3, W / 2, H / 2, W * 0.62)     # the old lens's falloff
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0.05, 0.03, 0.0, 0.85)
    ctx.set_source(g)
    ctx.paint()


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS[1]:
        return
    film_t = math.floor(t * FPS_FILM) / FPS_FILM                       # the picture moves at sixteen a second
    rand = random.Random(int(t * FPS_FILM))
    ctx.save()
    ctx.translate(rand.uniform(-2, 2), rand.uniform(-3, 3))          # weave in the gate
    if not card(ctx, film_t):
        if film_t < CARD_1[0]:                                       # closer in on the ladder
            ctx.translate(670, 560)
            ctx.scale(1.15, 1.15)
            ctx.translate(-670, -560)
            street(ctx, film_t)
            wagon(ctx, film_t)
            fireman(ctx, film_t, ladder(ctx, film_t))
        else:
            street(ctx, film_t)
            mast(ctx, film_t)
    ctx.restore()
    damage(ctx, int(t * FPS_FILM))
    grain(ctx, frame, 1.2)
    lead = span(t, *LEADER)
    if lead < 1:
        ctx.set_source_rgba(*sepia(1.0, (1 - lead) * (0.6 + 0.4 * math.sin(t * 90))))
        ctx.paint()
    closing = span(t, *IRIS)
    if closing > 0:
        iris(ctx, W / 2, 330, 760 * (1 - ease_in(closing, 2)))
