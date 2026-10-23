"""All Are Welcome: VizelVision as an Episcopal parish, on an old 16 mm parish film (faded,
weaving in the gate, dust and a scratch), played straight and warm.

1. Evening at a Gothic Revival church: grey stone, a tower with battlements, the red
   doors, a progress Pride flag by them and BLACK LIVES MATTER on the churchyard wall. On
   the lawn, the famous blue sign, its shield bearing the station's TV: THE VIZELVISION
   CHANNEL / WELCOMES / YOU. The tower bell swings the open logo; on its last note the
   red doors open and the light spills out.
2. Inside, from the back pew: the arcade, the gilt pipes of the organ, the choir in red
   cassocks and white surplices, ALL ARE WELCOME across the chancel arch on a rainbow, the
   hymn board (19 and 70, the channel and the cable), and the Rev. Mother in a rainbow
   stole, hands raised: "VizzleVision be with you." The people (a couple leaning together,
   a wheelchair by the aisle, and a golden retriever turned round in the front pew; it is
   blessing-of-the-animals season) answer: "And also with you." The dog tilts its head.
3. The title page of an old prayer book, printed in red and black, on the closed logo:
   THE BOOK OF COMMON VIEWING, and Administration of the Programmes and Other Rites and
   Ceremonies of the Channel, According to the use of VizelVision (an illuminated V in
   gold), CHANNEL 19 · CABLE 70; and the rubric in red as she reads it: "¶ Coffee hour to
   follow in the Parish Hall. All are welcome."

The voices: Pandora, the Rev. Mother; eight more, the people.
"""
import math
import random
from functools import lru_cache

import cairo

from common import (A, INK, TAU, W, H, WHITE, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    font, glint, grain, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'all-are-welcome'
NAME = 'All Are Welcome'
KIND = 'ident'
ORDER = 33
DESCRIPTION = ('VizelVision as an Episcopal parish on old parish film: the blue sign (THE VIZELVISION CHANNEL '
               'WELCOMES YOU), a Pride flag by the red doors, the organ and the choir, a priest in a rainbow stole, '
               '"VizzleVision be with you" / "And also with you", a dog in the front pew, and The Book of Common '
               'Viewing. Coffee hour to follow. Pandora and the people.')
DURATION = 10.0
STILL_AT = 9.3
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
FADE_IN = (0.0, 0.5)
BELL = (1.0, 1.25, 1.5, 2.0)                     # the open logo: the tower bell
DOORS = (2.0, 2.5)                               # the red doors swing open
PUSH = (1.2, 2.9)                                # the camera walks up the path
INSIDE = (2.5, 2.9)                              # the dissolve inside
ORGAN = (2.5, 3.0, 3.5, 4.0, 4.5, 6.35)          # the organ's chords inside (the people answer unaccompanied)
ORANS = (2.85, 3.2)                              # the priest raises her hands...
SALUTATION = 3.0                                 # "VizzleVision be with you."
RESPONSE = 5.0                                   # the people: "And also with you."
LOWER = (4.85, 5.2)                              # ...and lowers them
TILT = (5.0, 5.4)                                # the dog tilts its head
PAGE_IN = (6.45, 6.95)                           # the dissolve to the title page
CLOSED = 7.0                                     # the closed logo: the title prints
VIZELVISION = 8.0                                # the name, its initial in gold
RUBRIC = (8.15, 9.25)                            # the rubric, as she reads it
AMEN = (8.4, 8.9)                                # the organ's plagal cadence
FADE = (9.4, 9.65)

# The outside.
GROUND = 560
CX = 790                                         # the facade's centre
STONE = (0.56, 0.55, 0.53)
DOOR_RED = (0.66, 0.1, 0.1)
NAVY = (0.08, 0.16, 0.38)
LAMP = (1.0, 0.82, 0.5)
# The nave: a camera in the back pew's aisle, looking east.
FOCAL, EYE, HORIZON_Y = 760.0, 1.5, 410.0
ARCADE = 3.2                                     # the arcade's columns, either side
COLUMNS = (2.0, 4.0, 6.0, 8.0)
CHANCEL = 8.3                                    # the chancel arch and its step
EAST = 11.0                                      # the east wall
PEWS = (2.4, 3.1, 3.8, 4.5, 5.2, 5.9, 6.6, 7.3)
PRIEST = (0.0, 8.8)
DOG = (-1.35, 2.4)                               # front pew, turned round to look at us
GOLD = (0.95, 0.75, 0.32)
CREAM = (0.97, 0.93, 0.82)
RED = (0.72, 0.08, 0.1)
OAK = (0.32, 0.2, 0.11)
PRIDE = ((0.89, 0.01, 0.01), (1.0, 0.55, 0.0), (1.0, 0.93, 0.0), (0.0, 0.5, 0.15), (0.14, 0.25, 0.85),
         (0.45, 0.03, 0.53))
PROGRESS = ((1.0, 1.0, 1.0), (0.96, 0.66, 0.72), (0.36, 0.81, 0.98), (0.38, 0.22, 0.08), (0.0, 0.0, 0.0))


# ---------------------------------------------------------------- 1. the church at evening

def sky(ctx):
    g = cairo.LinearGradient(0, 0, 0, GROUND)
    g.add_color_stop_rgb(0, 0.1, 0.12, 0.3)
    g.add_color_stop_rgb(0.55, 0.36, 0.3, 0.5)
    g.add_color_stop_rgb(0.85, 0.85, 0.55, 0.45)
    g.add_color_stop_rgb(1, 0.98, 0.72, 0.48)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(11)
    for _ in range(40):                                              # the first stars
        x, y = rand.uniform(0, W), rand.uniform(0, 230)
        ctx.arc(x, y, rand.uniform(0.6, 1.4), 0, TAU)
        ctx.set_source_rgba(1, 0.97, 0.9, rand.uniform(0.3, 0.8))
        ctx.fill()
    ctx.arc(1150, 92, 22, 0, TAU)                                    # the moon, a crescent
    ctx.set_source_rgb(0.98, 0.95, 0.85)
    ctx.fill()
    ctx.arc(1160, 86, 20, 0, TAU)
    ctx.set_source_rgb(0.12, 0.14, 0.32)
    ctx.fill()


def trees(ctx):
    rand = random.Random(3)
    for x0, top, spread in ((40, 250, 170), (300, 330, 120), (1240, 230, 190), (1080, 330, 110)):
        for _ in range(26):
            x = x0 + rand.gauss(0, spread * 0.35)
            y = top + abs(rand.gauss(0, 90)) + 40
            ctx.arc(x, y, rand.uniform(30, 60), 0, TAU)
            ctx.set_source_rgb(*mix((0.1, 0.13, 0.12), (0.25, 0.2, 0.3), rand.random() * 0.3))
            ctx.fill()


def ashlar(ctx, x0, y0, x1, y1, seed, light):
    """Dressed stone: courses of blocks, each a shade apart, with mortar lines."""
    rand = random.Random(seed)
    ctx.save()
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.clip()
    y = y0
    row = 0
    while y < y1:
        h = 22
        x = x0 - (row % 2) * 24
        while x < x1:
            w = rand.choice((40, 48, 56))
            ctx.rectangle(x, y, w - 1.5, h - 1.5)
            ctx.set_source_rgb(*mix(STONE, (0.42, 0.4, 0.42) if rand.random() < 0.5 else (0.66, 0.62, 0.56),
                                    rand.random() * 0.5 + 0.1))
            ctx.fill()
            x += w
        y += h
        row += 1
    g = cairo.LinearGradient(x0, 0, x1, 0)                           # the evening light from the west
    g.add_color_stop_rgba(0, 1, 0.75, 0.5, 0.18 * light)
    g.add_color_stop_rgba(1, 0.1, 0.1, 0.3, 0.35)
    ctx.set_source(g)
    ctx.paint()
    ctx.restore()


def pointed(ctx, x, bottom, width, spring, apex):
    """A pointed (lancet) arch's outline: sides up to spring, the two arcs to apex."""
    half = width / 2
    ctx.move_to(x - half, bottom)
    ctx.line_to(x - half, spring)
    ctx.curve_to(x - half, spring - (spring - apex) * 0.6, x - half * 0.3, apex + 4, x, apex)
    ctx.curve_to(x + half * 0.3, apex + 4, x + half, spring - (spring - apex) * 0.6, x + half, spring)
    ctx.line_to(x + half, bottom)
    ctx.close_path()


def west_window(ctx, x, bottom, width, top):
    """The great west window over the doors: tracery, lit from inside."""
    spring = top + width * 0.55
    pointed(ctx, x, bottom, width + 16, spring, top - 8)
    ctx.set_source_rgb(*mix(STONE, INK, 0.25))
    ctx.fill()
    pointed(ctx, x, bottom, width, spring, top)
    path = ctx.copy_path()
    ctx.save()
    ctx.clip()
    rand = random.Random(19)
    for gx in range(int(x - width / 2), int(x + width / 2), 9):     # the glass, warm from within
        for gy in range(int(top), int(bottom), 9):
            ctx.rectangle(gx, gy, 9, 9)
            ctx.set_source_rgb(*mix(LAMP, rand.choice(((0.85, 0.2, 0.2), (0.2, 0.35, 0.8), (0.95, 0.75, 0.3),
                                                        (0.3, 0.6, 0.4))), 0.45))
            ctx.fill()
    ctx.set_source_rgb(0.2, 0.17, 0.15)
    ctx.set_line_width(4)
    for k in (-1, 0, 1):                                             # mullions
        ctx.move_to(x + k * width / 3 * 0.9, bottom)
        ctx.line_to(x + k * width / 3 * 0.9, spring + 10)
    ctx.stroke()
    ctx.arc(x, spring - 18, width * 0.2, 0, TAU)                     # the tracery's circle
    ctx.stroke()
    ctx.restore()
    ctx.append_path(path)
    ctx.set_line_width(3)
    ctx.stroke()


@lru_cache(maxsize=None)
def churchyard():
    """The sky, the trees, the church (but its doors, bell and flag), the lawn and the wall:
    once."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    sky(ctx)
    trees(ctx)
    ctx.move_to(0, GROUND)                                           # the lawn
    ctx.line_to(W, GROUND - 10)
    ctx.line_to(W, H)
    ctx.line_to(0, H)
    ctx.close_path()
    g = cairo.LinearGradient(0, GROUND, 0, H)
    g.add_color_stop_rgb(0, 0.2, 0.28, 0.16)
    g.add_color_stop_rgb(1, 0.08, 0.12, 0.07)
    ctx.set_source(g)
    ctx.fill()
    # The nave's side, going back, and its roof.
    ctx.move_to(CX + 170, 330)
    ctx.line_to(CX + 330, 360)
    ctx.line_to(CX + 330, GROUND - 6)
    ctx.line_to(CX + 170, GROUND)
    ctx.close_path()
    ctx.save()
    ctx.clip()
    ashlar(ctx, CX + 170, 300, CX + 340, GROUND, 5, 0.2)
    ctx.restore()
    for k in range(3):
        wx = CX + 200 + k * 42
        pointed(ctx, wx, 470 - k * 2, 20, 420, 396 + k * 2)
        ctx.set_source_rgb(*mix(LAMP, (0.8, 0.3, 0.2), 0.3))
        ctx.fill()
    ctx.move_to(CX + 170, 330)
    ctx.line_to(CX, 168)
    ctx.line_to(CX + 150, 196)
    ctx.line_to(CX + 330, 360)
    ctx.close_path()
    ctx.set_source_rgb(0.24, 0.24, 0.3)
    ctx.fill()
    # The west front: a steep gable.
    ctx.move_to(CX - 170, GROUND)
    ctx.line_to(CX - 170, 330)
    ctx.line_to(CX, 168)
    ctx.line_to(CX + 170, 330)
    ctx.line_to(CX + 170, GROUND)
    ctx.close_path()
    ctx.save()
    ctx.clip()
    ashlar(ctx, CX - 170, 160, CX + 170, GROUND, 7, 1.0)
    ctx.restore()
    ctx.move_to(CX - 182, 334)                                       # the gable's coping and its cross
    ctx.line_to(CX, 160)
    ctx.line_to(CX + 182, 334)
    ctx.set_source_rgb(*mix(STONE, WHITE, 0.15))
    ctx.set_line_width(9)
    ctx.stroke()
    ctx.rectangle(CX - 3, 118, 6, 46)
    ctx.rectangle(CX - 15, 130, 30, 6)
    ctx.fill()
    for bx in (CX - 176, CX + 166):                                  # buttresses
        ctx.rectangle(bx, 340, 12, GROUND - 340)
        ctx.set_source_rgb(*mix(STONE, INK, 0.2))
        ctx.fill()
    west_window(ctx, CX, 410, 120, 230)
    pointed(ctx, CX, GROUND, 150, 470, 418)                          # the doorway's stone surround
    ctx.set_source_rgb(*mix(STONE, WHITE, 0.1))
    ctx.fill()
    pointed(ctx, CX, GROUND, 122, 478, 434)                          # the doorway, warm (the doors on top)
    ctx.set_source_rgb(1.0, 0.86, 0.55)
    ctx.fill()
    ctx.rectangle(CX - 90, GROUND, 180, 8)                           # the step
    ctx.set_source_rgb(0.7, 0.68, 0.64)
    ctx.fill()
    # The tower, left: a belfry and battlements, pinnacles at the corners.
    tx0, tx1, ttop = CX - 330, CX - 186, 96
    ashlar(ctx, tx0, ttop, tx1, GROUND, 9, 0.9)
    for k in range(5):
        ctx.rectangle(tx0 - 6 + k * 34, ttop - 22, 20, 24)
    ctx.set_source_rgb(*mix(STONE, WHITE, 0.08))
    ctx.fill()
    for px in (tx0 - 8, tx1 - 6):
        ctx.move_to(px, ttop - 20)
        ctx.line_to(px + 7, ttop - 66)
        ctx.line_to(px + 14, ttop - 20)
        ctx.close_path()
        ctx.fill()
    ctx.rectangle(tx0 - 8, ttop, tx1 - tx0 + 16, 8)
    ctx.fill()
    pointed(ctx, (tx0 + tx1) / 2, 236, 56, 170, 128)                 # the belfry's opening
    ctx.set_source_rgb(0.08, 0.07, 0.09)
    ctx.fill()
    pointed(ctx, (tx0 + tx1) / 2, 420, 26, 384, 362)                 # a stair window, lit
    ctx.set_source_rgb(*LAMP)
    ctx.fill()
    # The path to the doors.
    ctx.move_to(CX - 66, GROUND + 8)
    ctx.line_to(CX + 66, GROUND + 8)
    ctx.line_to(CX + 210, H)
    ctx.line_to(CX - 210, H)
    ctx.close_path()
    g = cairo.LinearGradient(0, GROUND, 0, H)
    g.add_color_stop_rgb(0, 0.62, 0.55, 0.45)
    g.add_color_stop_rgb(1, 0.3, 0.27, 0.24)
    ctx.set_source(g)
    ctx.fill()
    churchyard_wall(ctx)
    lamp_post(ctx, 600, 650)
    return surface


def churchyard_wall(ctx):
    """A low stone wall along the front, right, and its banner."""
    x0, x1, top, bottom = 900, W + 10, 610, 680
    ashlar(ctx, x0, top, x1, bottom + 40, 13, 0.6)
    ctx.rectangle(x0 - 4, top - 8, x1 - x0 + 8, 10)
    ctx.set_source_rgb(*mix(STONE, WHITE, 0.15))
    ctx.fill()
    bx, by, bw, bh = 925, 618, 300, 56                               # the banner, tied on
    ctx.rectangle(bx, by, bw, bh)
    ctx.set_source_rgb(0.04, 0.04, 0.04)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 27)
    ctx.new_path()
    text_path(ctx, 'BLACK LIVES MATTER', bx + bw / 2, by + 38, tracking=1.2, align='center')
    ctx.set_source_rgb(1, 0.92, 0.2)
    ctx.fill()
    for gx in (bx + 3, bx + bw - 3):                                 # its grommets
        for gy in (by + 4, by + bh - 4):
            ctx.new_sub_path()
            ctx.arc(gx, gy, 2.5, 0, TAU)
    ctx.set_source_rgb(0.7, 0.7, 0.7)
    ctx.fill()


def lamp_post(ctx, x, y):
    glow = cairo.RadialGradient(x, y - 150, 2, x, y - 150, 90)
    glow.add_color_stop_rgba(0, 1, 0.9, 0.6, 0.6)
    glow.add_color_stop_rgba(1, 1, 0.8, 0.5, 0)
    ctx.set_source(glow)
    ctx.paint()
    ctx.rectangle(x - 3, y - 140, 6, 140)
    ctx.set_source_rgb(0.08, 0.08, 0.1)
    ctx.fill()
    ctx.move_to(x - 12, y - 140)
    ctx.line_to(x + 12, y - 140)
    ctx.line_to(x + 8, y - 166)
    ctx.line_to(x - 8, y - 166)
    ctx.close_path()
    ctx.set_source_rgb(*LAMP)
    ctx.fill()


def doors(ctx, t):
    """The red doors: two leaves in the pointed doorway, swinging in on the last note."""
    p = ease_in_out(span(t, *DOORS))
    pointed(ctx, CX, GROUND, 122, 478, 434)
    ctx.save()
    ctx.clip()
    if p > 0:                                                        # the light inside, and someone in it
        glow = cairo.RadialGradient(CX, 500, 4, CX, 500, 90)
        glow.add_color_stop_rgb(0, 1, 0.97, 0.85)
        glow.add_color_stop_rgb(1, 1, 0.8, 0.5)
        ctx.set_source(glow)
        ctx.paint()
    width = 61 * (1 - 0.85 * p)                                     # each leaf, foreshortened as it swings in
    for side in (-1, 1):
        hinge = CX + side * 61
        inner = hinge - side * width
        ctx.rectangle(min(hinge, inner), 420, width, GROUND - 420)
        ctx.set_source_rgb(*mix(DOOR_RED, INK, (0.15 if side < 0 else 0.05) + 0.4 * p))
        ctx.fill()
        ctx.set_source_rgb(0.1, 0.02, 0.02)
        ctx.set_line_width(2)
        for hy in (452, 500, 540):                                   # the iron strap hinges
            ctx.move_to(hinge, hy)
            ctx.line_to(inner + side * 6, hy)
        ctx.stroke()
        if p < 0.3:
            ctx.arc(inner + side * 9, 505, 3.5, 0, TAU)              # the ring handles
            ctx.set_source_rgb(0.12, 0.1, 0.08)
            ctx.fill()
    ctx.restore()
    if p > 0:                                                        # the light spills down the path
        ctx.move_to(CX - 61 * p, GROUND)
        ctx.line_to(CX + 61 * p, GROUND)
        ctx.line_to(CX + 230 * p, H)
        ctx.line_to(CX - 230 * p, H)
        ctx.close_path()
        ctx.set_source_rgba(1, 0.85, 0.55, 0.35 * p)
        ctx.fill()


def bell(ctx, t):
    """The tower bell, swinging one way then the other, on each note of the open logo."""
    swing = 0.0
    for k, when in enumerate(BELL):
        p = span(t, when - 0.1, when + 0.35)
        if 0 < p < 1:
            swing += (0.55 if k % 2 == 0 else -0.55) * math.sin(math.pi * p) * (1.3 if k == 3 else 1)
    ctx.save()
    ctx.translate(CX - 258, 150)
    ctx.rotate(swing)
    ctx.move_to(-16, 44)
    ctx.curve_to(-16, 14, -11, 6, 0, 6)
    ctx.curve_to(11, 6, 16, 14, 16, 44)
    ctx.line_to(21, 52)
    ctx.line_to(-21, 52)
    ctx.close_path()
    g = cairo.LinearGradient(-21, 0, 21, 0)
    g.add_color_stop_rgb(0, 0.45, 0.32, 0.12)
    g.add_color_stop_rgb(0.4, 0.95, 0.8, 0.45)
    g.add_color_stop_rgb(1, 0.4, 0.28, 0.1)
    ctx.set_source(g)
    ctx.fill()
    ctx.restore()


@lru_cache(maxsize=None)
def flag_surface():
    """The progress Pride flag, flat: the six stripes and the chevron at the hoist."""
    fw, fh = 150, 96
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, fw, fh)
    ctx = cairo.Context(surface)
    for k, colour in enumerate(PRIDE):
        ctx.rectangle(0, k * fh / 6, fw, fh / 6 + 0.5)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    for k, colour in reversed(list(enumerate(PROGRESS))):
        depth = (k + 1) * 11
        ctx.move_to(0, 0)
        ctx.line_to(depth - 11, 0)
        ctx.line_to(depth - 11 + fh / 2 * 0.75, fh / 2)
        ctx.line_to(depth - 11, fh)
        ctx.line_to(0, fh)
        ctx.close_path()
        ctx.set_source_rgb(*colour)
        ctx.fill()
    return surface


def pride_flag(ctx, t):
    """On a pole out from the wall by the doors, rippling: drawn in strips, each lifted and
    shaded by the wave."""
    ox, oy = CX + 104, 420                                           # the pole's bracket on the wall
    ctx.move_to(ox, oy)
    ctx.line_to(ox + 96, oy - 70)
    ctx.set_source_rgb(0.85, 0.82, 0.75)
    ctx.set_line_width(4)
    ctx.stroke()
    surface = flag_surface()
    fw, fh = surface.get_width(), surface.get_height()
    angle = math.atan2(-70, 96)
    ctx.save()
    ctx.translate(ox + 6, oy - 4)
    ctx.rotate(angle + 0.62)
    for x in range(0, fw, 3):
        phase = x / 26 - t * 5.5
        lift = math.sin(phase) * 5 * (x / fw) ** 0.8
        shade = 0.82 + 0.18 * math.cos(phase)
        ctx.save()
        ctx.rectangle(x, lift - 2, 3.4, fh + 4)
        ctx.clip()
        ctx.set_source_surface(surface, 0, lift)
        ctx.paint()
        ctx.set_source_rgba(0, 0, 0, 1 - shade)
        ctx.paint()
        ctx.restore()
    ctx.restore()


def shield(ctx, x, y, s):
    """The sign's shield, as the church's: white, a red cross, the blue canton; on it,
    where the crosslets would be, the station's TV."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.move_to(-1, -1.15)
    ctx.line_to(1, -1.15)
    ctx.line_to(1, 0.15)
    ctx.curve_to(1, 0.75, 0.45, 1.1, 0, 1.3)
    ctx.curve_to(-0.45, 1.1, -1, 0.75, -1, 0.15)
    ctx.close_path()
    outline = ctx.copy_path()
    ctx.set_source_rgb(0.98, 0.98, 0.96)
    ctx.fill()
    ctx.append_path(outline)
    ctx.save()
    ctx.clip()
    ctx.rectangle(-0.17, -1.2, 0.34, 2.6)
    ctx.rectangle(-1.1, -0.42, 2.2, 0.34)
    ctx.set_source_rgb(0.8, 0.1, 0.12)
    ctx.fill()
    ctx.rectangle(-1.1, -1.2, 0.93, 0.78)
    ctx.set_source_rgb(0.12, 0.26, 0.62)
    ctx.fill()
    ctx.restore()
    ctx.save()                                                       # the TV, in white
    ctx.translate(-0.62, -0.8)
    ctx.scale(0.0022, 0.0022)
    rounded_rect(ctx, -150, -110, 300, 220, 36)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    rounded_rect(ctx, -110, -80, 220, 150, 22)
    ctx.set_source_rgb(0.12, 0.26, 0.62)
    ctx.fill()
    ctx.restore()
    ctx.append_path(outline)
    ctx.set_source_rgb(0.75, 0.62, 0.3)
    ctx.set_line_width(0.07)
    ctx.stroke()
    ctx.restore()


def sign(ctx, t):
    """The blue sign on its white post and arm, hung on two chains, swaying a little."""
    px, py = 120, 300                                                # the post's top
    ctx.rectangle(px - 6, py, 12, GROUND + 50 - py)
    ctx.set_source_rgb(0.92, 0.9, 0.86)
    ctx.fill()
    ctx.rectangle(px - 6, py, 330, 10)                               # the arm
    ctx.fill()
    ctx.arc(px, py - 4, 9, 0, TAU)                                   # the finial
    ctx.fill()
    sway = 0.012 * math.sin(t * 2.1)
    ctx.save()
    ctx.translate(px + 170, py + 10)
    ctx.rotate(sway)
    for cx in (-120, 120):                                           # the chains
        ctx.move_to(cx, 0)
        ctx.line_to(cx, 22)
    ctx.set_source_rgb(0.3, 0.3, 0.32)
    ctx.set_line_width(2.5)
    ctx.set_dash([4, 2])
    ctx.stroke()
    ctx.set_dash([])
    x, y, w, h = -150, 22, 300, 172
    rounded_rect(ctx, x, y, w, h, 6)
    ctx.set_source_rgb(0.95, 0.95, 0.93)
    ctx.fill()
    rounded_rect(ctx, x + 6, y + 6, w - 12, h - 12, 4)
    ctx.set_source_rgb(*NAVY)
    ctx.fill()
    shield(ctx, x + 50, y + 70, 30)
    ctx.set_source_rgb(0.96, 0.96, 0.94)
    font(ctx, 'C059', 15)
    for k, line in enumerate(('THE', 'VIZELVISION', 'CHANNEL')):
        ctx.new_path()
        text_path(ctx, line, x + 186, y + 38 + k * 20, tracking=1.5, align='center')
        ctx.fill()
    font(ctx, 'C059', 31)
    ctx.new_path()
    text_path(ctx, 'WELCOMES', x + w / 2 + 2, y + 132, tracking=2, align='center')
    ctx.fill()
    font(ctx, 'C059', 22)
    ctx.new_path()
    text_path(ctx, 'YOU', x + w / 2 + 2, y + 158, tracking=4, align='center')
    ctx.fill()
    ctx.restore()


def outside(ctx, t):
    push = 1.0 + 0.16 * ease_in(span(t, *PUSH), 1.6)
    ctx.save()
    ctx.translate(CX, 500)
    ctx.scale(push, push)
    ctx.translate(-CX, -500)
    ctx.set_source_surface(churchyard(), 0, 0)
    ctx.paint()
    bell(ctx, t)
    doors(ctx, t)
    pride_flag(ctx, t)
    sign(ctx, t)
    ctx.restore()


# ---------------------------------------------------------------- 2. the nave

def project(x, y, z):
    """A point in the nave (metres: x across, y up from the floor, z away) on the screen."""
    return W / 2 + FOCAL * x / z, HORIZON_Y + FOCAL * (EYE - y) / z


def poly(ctx, points):
    ctx.move_to(*project(*points[0]))
    for p in points[1:]:
        ctx.line_to(*project(*p))
    ctx.close_path()


def arch_points(x0, x1, spring, apex, z, n=10):
    """A pointed arch across the nave's plane at z, from x0 to x1: its intrados."""
    mid = (x0 + x1) / 2
    pts = []
    for k in range(n + 1):
        u = k / n
        side = x0 if u < 0.5 else x1
        v = abs(u - 0.5) * 2                                         # 1 at the springing, 0 at the apex
        pts.append((mid + (side - mid) * math.sin(v * math.pi / 2) ** 0.8, spring + (apex - spring) * (1 - v ** 1.6), z))
    return pts


def side_arch(ctx, side, z0, z1, spring, apex, colour):
    """An arcade arch in the side plane x = side * ARCADE, from column z0 to z1, filled."""
    x = side * ARCADE
    pts = [(x, 0, z0)]
    for k in range(13):
        u = k / 12
        v = abs(u - 0.5) * 2
        z = (z0 + z1) / 2 + (z1 - z0) / 2 * (math.sin(v * math.pi / 2) ** 0.8) * (1 if u > 0.5 else -1)
        pts.append((x, spring + (apex - spring) * (1 - v ** 1.6), z))
    pts.append((x, 0, z1))
    poly(ctx, pts)
    ctx.set_source_rgb(*colour)
    ctx.fill()


@lru_cache(maxsize=None)
def nave():
    """The stone, the arcade, the aisles' windows, the chancel and its east window, the
    organ's case, the banner and the hymn board: once."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.2, 0.17, 0.15)
    ctx.paint()
    # The side aisles behind the arcade: dim, their windows glowing.
    for side in (-1, 1):
        poly(ctx, ((side * 5.5, 0, 1.0), (side * 5.5, 0, EAST), (side * 5.5, 9, EAST), (side * 5.5, 9, 1.0)))
        ctx.set_source_rgb(0.3, 0.26, 0.22)
        ctx.fill()
        for z in (3.0, 5.0, 7.0):
            pts = [(side * 5.5, 1.6, z - 0.35), (side * 5.5, 1.6, z + 0.35)]
            pts += [(side * 5.5, 3.6 + 0.6 * math.sin(math.pi * k / 6), z + 0.35 - 0.7 * k / 6) for k in range(7)]
            poly(ctx, pts)
            ctx.set_source_rgb(*mix((0.9, 0.7, 0.5), (0.3, 0.4, 0.8) if side > 0 else (0.85, 0.35, 0.3), 0.4))
            ctx.fill()
    poly(ctx, ((-6, 0, 1.0), (6, 0, 1.0), (6, 0, EAST), (-6, 0, EAST)))   # the floor: flagstones
    ctx.set_source_rgb(0.5, 0.45, 0.4)
    ctx.fill()
    for k, z in enumerate((1.5, 2.0, 2.6, 3.3, 4.1, 5.0, 6.0, 7.1, 8.3)):
        poly(ctx, ((-6, 0.001, z), (6, 0.001, z), (6, 0.001, z + 0.03), (-6, 0.001, z + 0.03)))
        ctx.set_source_rgb(0.36, 0.32, 0.28)
        ctx.fill()
    poly(ctx, ((-0.55, 0.002, 1.0), (0.55, 0.002, 1.0), (0.55, 0.002, CHANCEL), (-0.55, 0.002, CHANCEL)))
    ctx.set_source_rgb(0.55, 0.1, 0.12)                              # the red runner
    ctx.fill()
    chancel(ctx)
    # The clerestory wall over the arcade, and the arches cut through it.
    for side in (-1, 1):
        poly(ctx, ((side * ARCADE, 0, 1.0), (side * ARCADE, 0, CHANCEL), (side * ARCADE, 10, CHANCEL),
                   (side * ARCADE, 10, 1.0)))
        ctx.set_source_rgb(*mix(STONE, (0.75, 0.65, 0.5), 0.35))
        ctx.fill()
        for z0, z1 in zip(COLUMNS, COLUMNS[1:]):
            side_arch(ctx, side, z0 + 0.25, z1 - 0.25, 3.4, 5.2, (0.27, 0.23, 0.2))
            for k, z in enumerate((z0 + 0.6, (z0 + z1) / 2, z1 - 0.6)):   # the clerestory's lancets
                x = side * ARCADE
                pts = [(x, 6.2, z - 0.18), (x, 6.2, z + 0.18), (x, 7.4, z + 0.18), (x, 7.7, z), (x, 7.4, z - 0.18)]
                poly(ctx, pts)
                ctx.set_source_rgb(*mix((1.0, 0.85, 0.6), PRIDE[(k + int(z)) % 6], 0.3))
                ctx.fill()
        for z in COLUMNS:                                            # the columns, drum by drum
            for dz, shade in ((-0.22, 0.85), (0.0, 1.0), (0.22, 0.8)):
                x0, y0 = project(side * (ARCADE - 0.05), 0, z + dz)
                x1, y1 = project(side * (ARCADE - 0.05), 3.5, z + dz)
                half = FOCAL * 0.13 / (z + dz)
                ctx.rectangle(x0 - half, y1, half * 2, y0 - y1)
                ctx.set_source_rgb(*mix(STONE, (0.8, 0.72, 0.6), 0.3 * shade))
                ctx.fill()
            x, y = project(side * (ARCADE - 0.05), 3.5, z)           # the capital
            half = FOCAL * 0.3 / z
            ctx.rectangle(x - half, y - FOCAL * 0.18 / z, half * 2, FOCAL * 0.18 / z)
            ctx.set_source_rgb(*mix(STONE, WHITE, 0.2))
            ctx.fill()
    banner(ctx)
    hymn_board(ctx)
    return surface


def chancel(ctx):
    """Up the step: the choir's stalls, the altar in its green (Ordinary Time), the east
    window over it, the organ's gilt pipes on the right, and the chancel arch round it all."""
    poly(ctx, ((-2.6, 0, CHANCEL), (2.6, 0, CHANCEL), (2.6, 0.3, CHANCEL), (-2.6, 0.3, CHANCEL)))
    ctx.set_source_rgb(0.62, 0.58, 0.52)                             # the step
    ctx.fill()
    poly(ctx, ((-2.6, 0.3, CHANCEL), (2.6, 0.3, CHANCEL), (2.6, 0.3, EAST), (-2.6, 0.3, EAST)))
    ctx.set_source_rgb(0.42, 0.12, 0.12)
    ctx.fill()
    for side in (-1, 1):
        poly(ctx, ((side * 2.6, 0.3, CHANCEL), (side * 2.6, 0.3, EAST), (side * 2.6, 8, EAST), (side * 2.6, 8, CHANCEL)))
        ctx.set_source_rgb(*mix(STONE, (0.8, 0.7, 0.5), 0.45))
        ctx.fill()
    poly(ctx, ((-2.6, 0.3, EAST), (2.6, 0.3, EAST), (2.6, 9, EAST), (-2.6, 9, EAST)))
    ctx.set_source_rgb(*mix(STONE, (0.85, 0.75, 0.55), 0.5))
    ctx.fill()
    east_window(ctx)
    poly(ctx, ((-1.1, 0.3, EAST - 0.6), (1.1, 0.3, EAST - 0.6), (1.1, 1.3, EAST - 0.6), (-1.1, 1.3, EAST - 0.6)))
    ctx.set_source_rgb(0.12, 0.38, 0.22)                             # the altar's green frontal
    ctx.fill()
    poly(ctx, ((-1.1, 1.22, EAST - 0.6), (1.1, 1.22, EAST - 0.6), (1.1, 1.3, EAST - 0.6), (-1.1, 1.3, EAST - 0.6)))
    ctx.set_source_rgb(*CREAM)
    ctx.fill()
    for k in range(3):                                               # gold orphreys
        x = -0.6 + k * 0.6
        poly(ctx, ((x - 0.05, 0.3, EAST - 0.61), (x + 0.05, 0.3, EAST - 0.61), (x + 0.05, 1.22, EAST - 0.61),
                   (x - 0.05, 1.22, EAST - 0.61)))
        ctx.set_source_rgb(*GOLD)
        ctx.fill()
    cx, cy = project(0, 1.3, EAST - 0.6)                             # the brass cross
    s = FOCAL / (EAST - 0.6)
    ctx.rectangle(cx - 0.03 * s, cy - 0.75 * s, 0.06 * s, 0.75 * s)
    ctx.rectangle(cx - 0.2 * s, cy - 0.58 * s, 0.4 * s, 0.06 * s)
    ctx.set_source_rgb(*GOLD)
    ctx.fill()
    organ_case(ctx)
    for side in (-1, 1):                                             # the choir stalls
        for row, x in enumerate((1.9, 1.45)):
            poly(ctx, ((side * x, 0.3, 8.7), (side * x, 0.3, 10.2), (side * x, 1.2, 10.2), (side * x, 1.2, 8.7)))
            ctx.set_source_rgb(*mix(OAK, INK, 0.2 * row))
            ctx.fill()
    # The chancel arch, framing it all: the wall around a pointed opening.
    ctx.save()
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    poly(ctx, ((-ARCADE, 0, CHANCEL - 0.05), (ARCADE, 0, CHANCEL - 0.05), (ARCADE, 10, CHANCEL - 0.05),
               (-ARCADE, 10, CHANCEL - 0.05)))
    for k, p in enumerate(arch_points(-2.6, 2.6, 4.0, 6.6, CHANCEL - 0.05, 24)):
        if k == 0:
            ctx.move_to(*project(-2.6, 0.0, CHANCEL - 0.05))
        ctx.line_to(*project(*p))
    ctx.line_to(*project(2.6, 0.0, CHANCEL - 0.05))
    ctx.close_path()
    ctx.set_source_rgb(*mix(STONE, (0.75, 0.65, 0.5), 0.35))
    ctx.fill()
    ctx.restore()
    ctx.new_path()
    for k, p in enumerate(arch_points(-2.6, 2.6, 4.0, 6.6, CHANCEL - 0.06, 24)):
        (ctx.move_to if k == 0 else ctx.line_to)(*project(*p))
    ctx.set_source_rgb(*mix(STONE, WHITE, 0.25))
    ctx.set_line_width(FOCAL * 0.12 / CHANCEL)
    ctx.stroke()


def east_window(ctx):
    """Three lancets of jewel glass, and a small rose over them, the station's TV at its heart."""
    rand = random.Random(23)
    for k, x in enumerate((-0.95, 0.0, 0.95)):
        wide = 0.34 if k != 1 else 0.42
        top = 6.2 if k == 1 else 5.5
        pts = [(x - wide, 1.9, EAST - 0.01), (x + wide, 1.9, EAST - 0.01), (x + wide, top, EAST - 0.01),
               (x, top + 0.7, EAST - 0.01), (x - wide, top, EAST - 0.01)]
        poly(ctx, pts)
        outline = ctx.copy_path()
        ctx.save()
        ctx.clip()
        for gy in range(14):
            for gx in range(4):
                y0 = 1.9 + gy * (top + 0.7 - 1.9) / 14
                x0 = x - wide + gx * wide / 2
                poly(ctx, ((x0, y0, EAST - 0.01), (x0 + wide / 2, y0, EAST - 0.01),
                           (x0 + wide / 2, y0 + 0.36, EAST - 0.01), (x0, y0 + 0.36, EAST - 0.01)))
                ctx.set_source_rgb(*rand.choice(((0.15, 0.3, 0.75), (0.75, 0.15, 0.2), (0.95, 0.75, 0.25),
                                                  (0.2, 0.55, 0.35), (0.55, 0.25, 0.6))))
                ctx.fill()
        ctx.restore()
        ctx.append_path(outline)
        ctx.set_source_rgb(0.2, 0.17, 0.14)
        ctx.set_line_width(3)
        ctx.stroke()
    cx, cy = project(0, 7.6, EAST - 0.01)                            # the rose
    r = FOCAL * 0.55 / EAST
    for k in range(8):
        ctx.move_to(cx, cy)
        ctx.arc(cx, cy, r, k * TAU / 8, (k + 1) * TAU / 8)
        ctx.close_path()
        ctx.set_source_rgb(*((0.15, 0.3, 0.8), (0.85, 0.2, 0.3))[k % 2])
        ctx.fill()
    ctx.arc(cx, cy, r * 0.5, 0, TAU)
    ctx.set_source_rgb(0.95, 0.9, 0.7)
    ctx.fill()
    ctx.save()
    ctx.translate(cx, cy + 1)
    ctx.scale(r / 360, r / 360)
    A.draw_tv(ctx, 0.0, 1, 0.0)
    ctx.restore()
    ctx.arc(cx, cy, r, 0, TAU)
    ctx.set_source_rgb(0.2, 0.17, 0.14)
    ctx.set_line_width(3)
    ctx.stroke()


# The organ's facade: the pipes' heights across the flat, tallest in the middle.
PIPES = [3.0 - 0.9 * abs(k - 6) / 6 for k in range(13)]


def organ_case(ctx):
    """On the chancel's right wall: an oak case and its flat of gilt pipes."""
    x = 2.58
    z0, z1 = 8.7, 10.5
    poly(ctx, ((x, 1.2, z0), (x, 1.2, z1), (x, 5.4, z1), (x, 5.9, (z0 + z1) / 2), (x, 5.4, z0)))
    ctx.set_source_rgb(*OAK)
    ctx.fill()
    for k, height in enumerate(PIPES):
        z = z0 + 0.12 + k * (z1 - z0 - 0.24) / (len(PIPES) - 1)
        bottom = 2.0 + (3.0 - height) * 0.3
        foot_x, foot_y = project(x - 0.02, bottom, z)
        top_x, top_y = project(x - 0.02, bottom + height, z)
        half = FOCAL * 0.055 / z
        g = cairo.LinearGradient(foot_x - half, 0, foot_x + half, 0)
        g.add_color_stop_rgb(0, 0.55, 0.42, 0.18)
        g.add_color_stop_rgb(0.45, 1.0, 0.9, 0.6)
        g.add_color_stop_rgb(1, 0.5, 0.36, 0.14)
        ctx.rectangle(foot_x - half, top_y, half * 2, foot_y - top_y)
        ctx.set_source(g)
        ctx.fill()
        ctx.move_to(foot_x - half, foot_y)                           # the foot, a cone
        ctx.line_to(foot_x, foot_y + FOCAL * 0.35 / z)
        ctx.line_to(foot_x + half, foot_y)
        ctx.close_path()
        ctx.fill()
        _, mouth_y = project(x, bottom + 0.22, z)                    # the mouth
        ctx.move_to(foot_x - half * 0.7, mouth_y)
        ctx.line_to(foot_x, mouth_y - half * 0.8)
        ctx.line_to(foot_x + half * 0.7, mouth_y)
        ctx.close_path()
        ctx.set_source_rgb(0.15, 0.1, 0.05)
        ctx.fill()


def banner(ctx):
    """Across the chancel arch: ALL ARE WELCOME on the rainbow."""
    z = CHANCEL - 0.15
    x0, y0 = project(-2.0, 4.15, z)
    x1, y1 = project(2.0, 3.55, z)
    for k, colour in enumerate(PRIDE):
        ctx.rectangle(x0, y0 + k * (y1 - y0) / 6, x1 - x0, (y1 - y0) / 6 + 0.5)
        ctx.set_source_rgb(*mix(colour, WHITE, 0.08))
        ctx.fill()
    ctx.move_to(x0, y0)                                              # its cords
    ctx.line_to(*project(-2.6, 4.9, z))
    ctx.move_to(x1, y0)
    ctx.line_to(*project(2.6, 4.9, z))
    ctx.set_source_rgb(0.85, 0.8, 0.7)
    ctx.set_line_width(1.5)
    ctx.stroke()
    font(ctx, 'C059', (y1 - y0) * 0.62)
    ctx.new_path()
    text_path(ctx, 'ALL ARE WELCOME', (x0 + x1) / 2, y0 + (y1 - y0) * 0.76, tracking=3, align='center')
    ctx.set_source_rgb(0.1, 0.06, 0.06)
    ctx.set_line_width(3.5)
    ctx.stroke_preserve()
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()


def hymn_board(ctx):
    """On the left-hand column: the hymn board, with today's numbers."""
    z = 6.0
    x0, y0 = project(-ARCADE + 0.12, 2.75, z)
    x1, y1 = project(-ARCADE + 0.72, 1.55, z)
    ctx.move_to(x0, y0 + 12)
    ctx.line_to((x0 + x1) / 2, y0 - 6)
    ctx.line_to(x1, y0 + 12)
    ctx.line_to(x1, y1)
    ctx.line_to(x0, y1)
    ctx.close_path()
    ctx.set_source_rgb(*OAK)
    ctx.fill()
    ctx.rectangle(x0 + 6, y0 + 16, x1 - x0 - 12, y1 - y0 - 22)
    ctx.set_source_rgb(0.12, 0.08, 0.05)
    ctx.fill()
    for k, number in enumerate(('19', '70')):
        font(ctx, 'C059', (y1 - y0) * 0.3)
        ctx.new_path()
        text_path(ctx, number, (x0 + x1) / 2, y0 + 16 + (y1 - y0 - 22) * (0.44 + 0.44 * k), align='center')
        ctx.set_source_rgb(*CREAM)
        ctx.fill()


# The people, back to front: who sits where (x, pew), and what is on their heads.
HAIR = {'grey': (0.72, 0.72, 0.74), 'black': (0.08, 0.06, 0.05), 'brown': (0.3, 0.18, 0.1), 'red': (0.6, 0.25, 0.1),
        'blond': (0.82, 0.68, 0.4), 'white': (0.92, 0.92, 0.9)}
SKIN = ((0.95, 0.78, 0.66), (0.78, 0.56, 0.4), (0.55, 0.36, 0.24), (0.36, 0.23, 0.16), (0.88, 0.7, 0.55))
STYLES = ('short', 'bob', 'afro', 'bald', 'bun', 'hat', 'braids', 'short', 'curls', 'bob', 'kufi', 'short')
HAIRS = tuple(HAIR[k] for k in ('black', 'brown', 'black', 'red', 'blond', 'brown', 'grey', 'black', 'brown'))


def seated(ctx, x, z, style, hair, skin, coat, t, seed, lean=0.0):
    """Someone in a pew, from behind: shoulders, the back of a head and its hair. They
    say the response with everyone (a nod), and lean as they lean."""
    talk = math.sin(math.pi * span(t, RESPONSE, RESPONSE + 1.2)) * 0.02 * (1 + seed % 3) / 3
    sx, sy = project(x, 1.02, z)
    s = FOCAL / z
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(s, s)
    ctx.save()
    ctx.scale(0.24, 0.14)
    ctx.arc(0, 0.9, 1, math.pi, 0)                                   # the shoulders
    ctx.restore()
    ctx.set_source_rgb(*coat)
    ctx.fill()
    ctx.translate(lean * 0.1, -0.13 + talk)
    ctx.rotate(lean * 0.35)
    ctx.rectangle(-0.045, 0.02, 0.09, 0.08)                          # the neck
    ctx.set_source_rgb(*skin)
    ctx.fill()
    if style == 'afro':
        ctx.arc(0, -0.02, 0.15, 0, TAU)
        ctx.set_source_rgb(*hair)
        ctx.fill()
    elif style == 'bald':
        ctx.arc(0, 0, 0.105, 0, TAU)
        ctx.set_source_rgb(*mix(skin, WHITE, 0.08))
        ctx.fill()
        ctx.arc(0.03, -0.04, 0.03, 0, TAU)                           # the shine
        ctx.set_source_rgba(1, 1, 1, 0.25)
        ctx.fill()
    else:
        ctx.arc(0, 0, 0.108, 0, TAU)
        ctx.set_source_rgb(*hair)
        ctx.fill()
        if style == 'bob':
            ctx.rectangle(-0.11, -0.01, 0.22, 0.1)
            ctx.fill()
        elif style == 'bun':
            ctx.arc(0, -0.1, 0.05, 0, TAU)
            ctx.fill()
        elif style == 'braids':
            for bx in (-0.06, 0.06):
                ctx.rectangle(bx - 0.02, 0.0, 0.04, 0.22)
            ctx.fill()
        elif style == 'curls':
            for a in range(8):
                ctx.arc(0.1 * math.cos(a * TAU / 8), 0.1 * math.sin(a * TAU / 8) - 0.01, 0.035, 0, TAU)
                ctx.fill()
        elif style == 'kufi':
            ctx.arc(0, -0.02, 0.105, math.pi, 0)
            ctx.set_source_rgb(0.95, 0.93, 0.88)
            ctx.fill()
        elif style == 'hat':                                         # a Sunday hat, with flowers
            ctx.save()
            ctx.scale(0.24, 0.05)
            ctx.arc(0, -1.2, 1, 0, TAU)
            ctx.restore()
            ctx.set_source_rgb(0.55, 0.22, 0.45)
            ctx.fill()
            ctx.arc(0, -0.07, 0.1, math.pi, 0)
            ctx.fill()
            for k, colour in enumerate(((1, 0.85, 0.3), (1, 0.5, 0.6), (0.95, 0.95, 0.95))):
                ctx.arc(-0.08 + 0.06 * k, -0.11, 0.025, 0, TAU)
                ctx.set_source_rgb(*colour)
                ctx.fill()
    ctx.restore()


def pew(ctx, z):
    for side in (-1, 1):
        x0, x1 = side * 0.72, side * 2.95
        poly(ctx, ((x0, 0.0, z + 0.05), (x1, 0.0, z + 0.05), (x1, 0.92, z + 0.05), (x0, 0.92, z + 0.05)))
        ctx.set_source_rgb(*mix(OAK, (0.6, 0.45, 0.3), 0.3))
        ctx.fill()
        poly(ctx, ((x0, 0.92, z + 0.05), (x1, 0.92, z + 0.05), (x1, 0.88, z), (x0, 0.88, z)))
        ctx.set_source_rgb(*mix(OAK, WHITE, 0.25))
        ctx.fill()
        sx, sy0 = project(x0, 0.0, z + 0.05)                         # the pew end: a poppyhead
        _, sy1 = project(x0, 1.12, z + 0.05)
        w = side * 0.07 * FOCAL / z
        ctx.rectangle(sx - w, sy1, w, sy0 - sy1)
        ctx.set_source_rgb(*mix(OAK, INK, 0.15))
        ctx.fill()
        ctx.arc(sx - w / 2, sy1, abs(w) * 0.6, 0, TAU)
        ctx.fill()


def wheelchair(ctx, x, z):
    """By the aisle, at a pew's end: the chair's big wheel, and its pusher handles."""
    cx, cy = project(x, 0.33, z + 0.3)
    s = FOCAL / (z + 0.3)
    ctx.set_source_rgb(0.25, 0.27, 0.3)
    ctx.set_line_width(max(1.0, 0.025 * s))
    ctx.arc(cx, cy, 0.3 * s, 0, TAU)
    ctx.stroke()
    for k in range(8):
        a = k * TAU / 8
        ctx.move_to(cx, cy)
        ctx.line_to(cx + 0.3 * s * math.cos(a), cy + 0.3 * s * math.sin(a))
    ctx.set_line_width(max(0.6, 0.008 * s))
    ctx.stroke()
    hx, hy = project(x - 0.05, 1.0, z + 0.45)
    ctx.move_to(hx, cy)
    ctx.line_to(hx, hy)
    ctx.line_to(hx - 0.1 * s, hy)
    ctx.set_line_width(max(1.0, 0.02 * s))
    ctx.stroke()


def congregation(ctx, t):
    """The pews and the people, far to near; in the front pew, the couple and the dog."""
    rand = random.Random(29)
    for z in reversed(PEWS):
        for side in (-1, 1):
            for k in range(4):
                x = side * (0.95 + k * 0.55)
                if rand.random() > 0.78:
                    continue
                if z == PEWS[0] and (side > 0 and k < 2 or side < 0 and abs(x - DOG[0]) < 0.4):
                    continue                                         # the couple's and the dog's places
                seed = rand.randrange(1000)
                style = STYLES[seed % len(STYLES)]
                hair = HAIRS[seed % len(HAIRS)]
                seated(ctx, x + rand.uniform(-0.08, 0.08), z + 0.35, style, hair, SKIN[seed % len(SKIN)],
                       ((0.22, 0.25, 0.4), (0.45, 0.18, 0.2), (0.3, 0.3, 0.32), (0.18, 0.35, 0.28), (0.5, 0.4, 0.3),
                        (0.55, 0.5, 0.45))[seed % 6], t, seed)
        pew(ctx, z)
        if z == 3.8:
            wheelchair(ctx, 0.62, z)
    z = PEWS[0] + 0.35                                               # the couple, leaning together
    seated(ctx, 1.05, z, 'short', HAIR['grey'], SKIN[0], (0.3, 0.32, 0.45), t, 7, lean=0.0)
    seated(ctx, 1.48, z, 'braids', HAIR['black'], SKIN[3], (0.55, 0.3, 0.2), t, 8, lean=-0.6)
    sx, sy = project(1.05, 1.02, z)                                  # an arm round her shoulders
    s = FOCAL / z
    ctx.move_to(sx, sy - 0.01 * s)
    ctx.curve_to(sx + 0.2 * s, sy - 0.08 * s, sx + 0.38 * s, sy - 0.06 * s, sx + 0.52 * s, sy + 0.02 * s)
    ctx.set_source_rgb(0.3, 0.32, 0.45)
    ctx.set_line_width(0.07 * s)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    dog(ctx, t)


def dog(ctx, t):
    """A golden retriever, turned round in the front pew, looking at us over its back: the
    head tilts when the people answer."""
    x, z = DOG
    sx, sy = project(x, 1.02, z + 0.05)
    s = FOCAL / (z + 0.05)
    tilt = 0.32 * ease_out(span(t, *TILT)) * (1 - ease_in_out(span(t, TILT[1] + 0.6, TILT[1] + 1.0)))
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(s, s)
    fur, dark = (0.86, 0.6, 0.3), (0.68, 0.42, 0.18)
    ctx.save()
    ctx.scale(0.17, 0.1)
    ctx.arc(0, 0.6, 1, math.pi, 0)                                   # its chest over the pew back
    ctx.restore()
    ctx.set_source_rgb(*fur)
    ctx.fill()
    ctx.translate(0, -0.12)
    ctx.rotate(tilt)
    for side in (-1, 1):                                             # the ears
        ctx.save()
        ctx.translate(side * 0.1, -0.04)
        ctx.rotate(side * 0.25)
        ctx.scale(0.055, 0.1)
        ctx.arc(0, 0.5, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*dark)
        ctx.fill()
    ctx.save()
    ctx.scale(0.115, 0.105)
    ctx.arc(0, 0, 1, 0, TAU)                                         # the head
    ctx.restore()
    ctx.set_source_rgb(*fur)
    ctx.fill()
    ctx.save()
    ctx.scale(0.06, 0.045)
    ctx.arc(0, 1.3, 1, 0, TAU)                                       # the muzzle
    ctx.restore()
    ctx.set_source_rgb(*mix(fur, WHITE, 0.25))
    ctx.fill()
    ctx.arc(0, 0.035, 0.022, 0, TAU)                                 # the nose
    ctx.set_source_rgb(0.12, 0.08, 0.06)
    ctx.fill()
    for side in (-1, 1):                                             # the eyes
        ctx.arc(side * 0.042, -0.025, 0.014, 0, TAU)
        ctx.fill()
    ctx.save()                                                       # the tongue, out
    ctx.scale(0.022, 0.03)
    ctx.arc(0, 3.1, 1, 0, math.pi)
    ctx.restore()
    ctx.set_source_rgb(0.9, 0.45, 0.5)
    ctx.fill()
    ctx.restore()


def choir(ctx, t):
    """In the stalls, either side, facing in: red cassocks, white surplices and ruffs."""
    for side in (-1, 1):
        for row, x in enumerate((1.75, 1.3)):
            for k in range(4):
                z = 8.9 + k * 0.36 + row * 0.1
                sx, sy = project(side * x, 1.45 + 0.08 * row, z)
                s = FOCAL / z
                ctx.rectangle(sx - 0.12 * s, sy, 0.24 * s, 0.35 * s)
                ctx.set_source_rgb(0.62, 0.08, 0.1)
                ctx.fill()
                ctx.move_to(sx - 0.15 * s, sy + 0.2 * s)
                ctx.line_to(sx - 0.11 * s, sy - 0.05 * s)
                ctx.line_to(sx + 0.11 * s, sy - 0.05 * s)
                ctx.line_to(sx + 0.15 * s, sy + 0.2 * s)
                ctx.close_path()
                ctx.set_source_rgb(0.97, 0.96, 0.92)
                ctx.fill()
                ctx.arc(sx, sy - 0.06 * s, 0.06 * s, 0, TAU)         # the ruff
                ctx.fill()
                ctx.arc(sx - side * 0.01 * s, sy - 0.15 * s, 0.075 * s, 0, TAU)
                ctx.set_source_rgb(*SKIN[(k + row * 2 + (side > 0)) % len(SKIN)])
                ctx.fill()
                ctx.arc(sx + side * 0.01 * s, sy - 0.18 * s, 0.07 * s, math.pi, 0)
                ctx.set_source_rgb(*list(HAIR.values())[(k * 3 + row + (side > 0)) % len(HAIR)])
                ctx.fill()


def priest(ctx, t):
    """The Rev. Mother on the chancel step, facing us: a white surplice, the rainbow stole,
    short grey hair and spectacles; hands raised for the salutation, then lowered."""
    x, z = PRIEST
    sx, sy = project(x, 1.48, z)
    s = FOCAL / z * 1.35                                             # drawn a little large: she leads
    up = ease_out(span(t, *ORANS)) * (1 - ease_in_out(span(t, *LOWER)))
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(s, s)
    ctx.move_to(-0.3, 0.95)                                          # the surplice
    ctx.line_to(-0.2, -0.2)
    ctx.curve_to(-0.12, -0.3, 0.12, -0.3, 0.2, -0.2)
    ctx.line_to(0.3, 0.95)
    ctx.close_path()
    ctx.set_source_rgb(0.97, 0.96, 0.92)
    ctx.fill()
    for side in (-1, 1):                                             # the stole: the rainbow, down each side
        for k, colour in enumerate(PRIDE):
            ctx.rectangle(side * 0.075 - 0.035, -0.2 + k * 0.13, 0.07, 0.135)
            ctx.set_source_rgb(*colour)
            ctx.fill()
    ctx.rectangle(-0.045, -0.3, 0.09, 0.07)                          # the collar
    ctx.set_source_rgb(0.1, 0.1, 0.12)
    ctx.fill()
    ctx.rectangle(-0.018, -0.28, 0.036, 0.03)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    ctx.arc(0, -0.42, 0.11, 0, TAU)                                  # the face
    ctx.set_source_rgb(0.9, 0.74, 0.62)
    ctx.fill()
    ctx.arc(0, -0.45, 0.115, math.pi * 1.05, math.pi * 1.95)         # short grey hair
    ctx.set_source_rgb(0.78, 0.78, 0.8)
    ctx.set_line_width(0.06)
    ctx.stroke()
    for side in (-1, 1):                                             # spectacles
        ctx.arc(side * 0.045, -0.43, 0.03, 0, TAU)
    ctx.set_source_rgb(0.2, 0.15, 0.1)
    ctx.set_line_width(0.01)
    ctx.stroke()
    ctx.move_to(-0.03, -0.36)                                        # a kind, level mouth
    ctx.line_to(0.03, -0.36)
    ctx.set_line_width(0.012)
    ctx.stroke()
    for side in (-1, 1):                                             # the arms: at rest, or raised (the orans)
        shoulder = (side * 0.19, -0.18)
        elbow = (side * (0.26 + 0.12 * up), 0.12 - 0.22 * up)
        hand = (side * (0.2 + 0.24 * up), 0.3 - 0.62 * up)
        ctx.move_to(*shoulder)
        ctx.line_to(*elbow)
        ctx.line_to(*hand)
        ctx.set_source_rgb(0.97, 0.96, 0.92)
        ctx.set_line_width(0.1)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()
        ctx.arc(hand[0], hand[1] - 0.02, 0.04, 0, TAU)
        ctx.set_source_rgb(0.9, 0.74, 0.62)
        ctx.fill()
    ctx.restore()


def candles(ctx, t):
    """On the altar: two candles, flickering."""
    for k, x in enumerate((-0.75, 0.75)):
        bx, by = project(x, 1.3, EAST - 0.6)
        s = FOCAL / (EAST - 0.6)
        ctx.rectangle(bx - 0.03 * s, by - 0.45 * s, 0.06 * s, 0.45 * s)
        ctx.set_source_rgb(*CREAM)
        ctx.fill()
        flicker = 1 + 0.15 * math.sin(t * 23 + k * 2) + 0.1 * math.sin(t * 37 + k)
        fx, fy = bx, by - 0.5 * s
        glow = cairo.RadialGradient(fx, fy, 0, fx, fy, 24 * flicker)
        glow.add_color_stop_rgba(0, 1, 0.9, 0.6, 0.7)
        glow.add_color_stop_rgba(1, 1, 0.8, 0.4, 0)
        ctx.set_source(glow)
        ctx.arc(fx, fy, 24 * flicker, 0, TAU)
        ctx.fill()
        ctx.save()
        ctx.translate(fx, fy)
        ctx.scale(2.2, 5 * flicker)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(1, 0.95, 0.75)
        ctx.fill()


def light_shafts(ctx, t):
    """Evening light through the clerestory, slanting down across the nave, dust in it."""
    for k, z in enumerate((3.0, 5.0, 7.0)):
        top0, top1 = project(-ARCADE, 7.2, z - 0.15), project(-ARCADE, 7.2, z + 0.25)
        bottom0, bottom1 = project(1.2, 0.0, z + 1.4), project(1.2, 0.0, z + 1.8)
        ctx.move_to(*top0)
        ctx.line_to(*top1)
        ctx.line_to(*bottom1)
        ctx.line_to(*bottom0)
        ctx.close_path()
        g = cairo.LinearGradient(*top0, *bottom0)
        g.add_color_stop_rgba(0, 1, 0.85, 0.6, 0.2)
        g.add_color_stop_rgba(1, 1, 0.85, 0.6, 0.0)
        ctx.set_source(g)
        ctx.fill()
    rand = random.Random(31)
    for _ in range(40):                                              # dust, drifting
        x = rand.uniform(200, 900) + 14 * math.sin(t * 0.7 + rand.random() * 6)
        y = rand.uniform(80, 520) + (t * 9 * rand.uniform(0.5, 1.5)) % 60
        ctx.arc(x, y, rand.uniform(0.7, 1.6), 0, TAU)
        ctx.set_source_rgba(1, 0.95, 0.8, rand.uniform(0.15, 0.4))
        ctx.fill()


def pipes_speaking(ctx, t):
    """The organ's pipes brighten a moment as each chord sounds."""
    level = max(pulse(t, when, 0.5) for when in ORGAN)
    if level <= 0:
        return
    x0, y0 = project(2.56, 5.2, 8.7)
    x1, y1 = project(2.56, 2.0, 10.5)
    g = cairo.LinearGradient(0, y0, 0, y1)
    g.add_color_stop_rgba(0, 1, 0.95, 0.7, 0.0)
    g.add_color_stop_rgba(0.5, 1, 0.95, 0.7, 0.22 * level)
    g.add_color_stop_rgba(1, 1, 0.95, 0.7, 0.0)
    ctx.rectangle(min(x0, x1) - 6, y0, abs(x1 - x0) + 12, y1 - y0)
    ctx.set_source(g)
    ctx.fill()


def inside(ctx, t):
    look = 0.04 * ease_in_out(span(t, INSIDE[0], PAGE_IN[1]))       # a slow push up the aisle
    ctx.save()
    ctx.translate(W / 2, HORIZON_Y)
    ctx.scale(1 + look, 1 + look)
    ctx.translate(-W / 2, -HORIZON_Y)
    ctx.set_source_surface(nave(), 0, 0)
    ctx.paint()
    pipes_speaking(ctx, t)
    candles(ctx, t)
    choir(ctx, t)
    priest(ctx, t)
    congregation(ctx, t)
    light_shafts(ctx, t)
    ctx.restore()


# ---------------------------------------------------------------- 3. the title page

@lru_cache(maxsize=None)
def paper():
    """An old page: cream, darker at the edges, foxed, with the double red rule."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.2, 0.12, 0.08)
    ctx.paint()
    g = cairo.RadialGradient(W / 2, H / 2, 120, W / 2, H / 2, 760)
    g.add_color_stop_rgb(0, 0.97, 0.93, 0.83)
    g.add_color_stop_rgb(0.7, 0.92, 0.85, 0.7)
    g.add_color_stop_rgb(1, 0.78, 0.66, 0.48)
    rounded_rect(ctx, 34, 14, W - 68, H - 28, 4)
    ctx.set_source(g)
    ctx.fill()
    rand = random.Random(37)
    for _ in range(70):                                              # foxing
        x, y, r = rand.uniform(40, W - 40), rand.uniform(20, H - 20), rand.uniform(1, 7)
        ctx.arc(x, y, r, 0, TAU)
        ctx.set_source_rgba(0.6, 0.38, 0.18, rand.uniform(0.05, 0.25))
        ctx.fill()
    for inset, width in ((48, 3), (56, 1.2)):                        # the double rule
        ctx.rectangle(inset + 34, inset + 2, W - 2 * inset - 68, H - 2 * inset - 4)
        ctx.set_source_rgb(*RED)
        ctx.set_line_width(width)
        ctx.stroke()
    return surface


def printed(ctx, t, when, draw):
    """Something printing: in with a faint spread of the ink, then still."""
    p = span(t, when, when + 0.16)
    if p <= 0:
        return
    ctx.save()
    ctx.push_group()
    draw()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(ease_out(p))
    ctx.restore()


def line_of(ctx, text, y, family, size, colour, tracking=0.0, italic=False, bold=False):
    font(ctx, family, size, bold=bold, italic=italic)
    ctx.new_path()
    text_path(ctx, text, W / 2, y, tracking=tracking, align='center')
    ctx.set_source_rgb(*colour)
    ctx.fill()


def ornament(ctx, y):
    """A rule, a lozenge and a rule."""
    ctx.set_source_rgb(*RED)
    ctx.rectangle(W / 2 - 150, y - 0.75, 120, 1.5)
    ctx.rectangle(W / 2 + 30, y - 0.75, 120, 1.5)
    ctx.fill()
    ctx.move_to(W / 2, y - 9)
    ctx.line_to(W / 2 + 12, y)
    ctx.line_to(W / 2, y + 9)
    ctx.line_to(W / 2 - 12, y)
    ctx.close_path()
    ctx.fill()


def initial(ctx, x, y, size, t):
    """The illuminated initial: a gold V on a blue and red ground, white penwork round it,
    a glint once it is laid."""
    ctx.save()
    ctx.translate(x, y)
    rounded_rect(ctx, 0, 0, size, size, 3)
    ctx.set_source_rgb(0.12, 0.22, 0.55)
    ctx.fill()
    ctx.move_to(0, size)
    ctx.line_to(size, 0)
    ctx.line_to(size, size)
    ctx.close_path()
    ctx.set_source_rgb(*mix(RED, INK, 0.15))
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.8)                                # the penwork
    ctx.set_line_width(1.2)
    for k in range(6):
        a = k * TAU / 6
        ctx.arc(size / 2 + size * 0.38 * math.cos(a), size / 2 + size * 0.38 * math.sin(a), size * 0.05, 0, TAU)
        ctx.new_sub_path()
    ctx.stroke()
    font(ctx, 'P052', size * 0.86)
    ext = ctx.text_extents('V')
    ctx.move_to(size / 2 - ext.x_advance / 2, size * 0.8)
    ctx.text_path('V')
    g = cairo.LinearGradient(0, 0, size, size)
    g.add_color_stop_rgb(0, 1.0, 0.92, 0.6)
    g.add_color_stop_rgb(0.5, 0.85, 0.62, 0.2)
    g.add_color_stop_rgb(1, 1.0, 0.88, 0.5)
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.45, 0.3, 0.08)
    ctx.set_line_width(1.5)
    ctx.stroke()
    rounded_rect(ctx, 0, 0, size, size, 3)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.restore()
    life = span(t, VIZELVISION + 0.15, VIZELVISION + 0.75)
    if 0 < life < 1:
        glint(ctx, x + size * 0.72, y + size * 0.22, 26 * math.sin(life * math.pi), life * 2)


def title_page(ctx, t):
    push = 1 + 0.03 * ease_out(span(t, PAGE_IN[0], DURATION))
    ctx.save()
    ctx.translate(W / 2, H / 2)
    ctx.scale(push, push)
    ctx.translate(-W / 2, -H / 2)
    ctx.set_source_surface(paper(), 0, 0)
    ctx.paint()
    ink = (0.1, 0.07, 0.06)
    printed(ctx, t, CLOSED, lambda: (line_of(ctx, 'THE BOOK OF', 120, 'P052', 26, ink, tracking=9),
                                     line_of(ctx, 'COMMON VIEWING', 196, 'P052', 68, RED, tracking=4, bold=True)))
    printed(ctx, t, CLOSED + 0.25, lambda: (
        line_of(ctx, 'and Administration of the Programmes', 248, 'P052', 25, ink, italic=True, bold=False),
        line_of(ctx, 'and Other Rites and Ceremonies of the Channel', 282, 'P052', 25, ink, italic=True, bold=False)))
    printed(ctx, t, CLOSED + 0.5, lambda: (ornament(ctx, 318),
                                           line_of(ctx, 'According to the use of', 360, 'P052', 23, ink, italic=True,
                                                   bold=False)))

    def name():
        font(ctx, 'P052', 84, bold=True)
        width = ctx.text_extents('izelVision').x_advance
        size = 92
        x = W / 2 - (width + size + 8) / 2
        initial(ctx, x, 380, size, t)
        ctx.new_path()
        ctx.move_to(x + size + 8, 458)
        ctx.text_path('izelVision')
        ctx.set_source_rgb(*ink)
        ctx.fill()
    printed(ctx, t, VIZELVISION, name)
    printed(ctx, t, VIZELVISION + 0.12, lambda: line_of(ctx, 'CHANNEL 19   ·   CABLE 70', 512, 'P052', 20, RED, tracking=5))
    rubric = '¶ Coffee hour to follow in the Parish Hall. All are welcome.'
    shown = int(len(rubric) * span(t, *RUBRIC))                     # set as she reads it
    if shown:
        font(ctx, 'P052', 25, bold=False, italic=True)
        full = ctx.text_extents(rubric).x_advance
        ctx.new_path()
        ctx.move_to(W / 2 - full / 2, 580)
        ctx.text_path(rubric[:shown])
        ctx.set_source_rgb(*RED)
        ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the old film

def weave(frame):
    """The gate weave: the picture drifts a pixel or two, frame to frame (24 fps film)."""
    rand = random.Random(frame // 2.5)
    return rand.uniform(-1.6, 1.6), rand.uniform(-2.2, 2.2)


def film(ctx, t, frame):
    """Faded colour, a warm cast, flicker, dust and hairs, a scratch, the gate's round
    corners, and grain."""
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_HSL_SATURATION)                 # faded dyes
    ctx.set_source_rgb(0.5, 0.5, 0.5)
    ctx.paint_with_alpha(0.32)
    ctx.restore()
    warm = cairo.LinearGradient(0, 0, 0, H)
    warm.add_color_stop_rgba(0, 1, 0.78, 0.45, 0.1)
    warm.add_color_stop_rgba(1, 0.55, 0.3, 0.12, 0.14)
    ctx.set_source(warm)
    ctx.paint()
    rand = random.Random(frame // 2.5 + 101)
    ctx.set_source_rgba(0, 0, 0, rand.uniform(0.0, 0.06))            # flicker
    ctx.paint()
    for _ in range(rand.randint(2, 7)):                              # dust
        x, y = rand.uniform(0, W), rand.uniform(0, H)
        ctx.arc(x, y, rand.uniform(0.8, 3.0), 0, TAU)
        ctx.set_source_rgba(*((0.05, 0.04, 0.03) if rand.random() < 0.6 else (1, 0.97, 0.9)), rand.uniform(0.4, 0.85))
        ctx.fill()
    if rand.random() < 0.18:                                         # a hair
        x, y = rand.uniform(100, W - 100), rand.uniform(80, H - 80)
        ctx.move_to(x, y)
        ctx.curve_to(x + rand.uniform(-40, 40), y + rand.uniform(-40, 40), x + rand.uniform(-60, 60),
                     y + rand.uniform(10, 60), x + rand.uniform(-30, 30), y + rand.uniform(40, 90))
        ctx.set_source_rgba(0.05, 0.04, 0.03, 0.6)
        ctx.set_line_width(1.2)
        ctx.stroke()
    sx = 300 + 40 * math.sin(t * 0.9) + 8 * math.sin(t * 7.3)        # the scratch, wandering
    ctx.rectangle(sx, 0, 1.4, H)
    ctx.set_source_rgba(1, 0.97, 0.9, 0.18 + 0.1 * math.sin(t * 13))
    ctx.fill()
    vignette(ctx, 0.62)
    grain(ctx, frame, 0.7)
    ctx.save()                                                       # the gate's rounded corners
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.rectangle(-10, -10, W + 20, H + 20)
    rounded_rect(ctx, 4, 4, W - 8, H - 8, 34)
    ctx.set_source_rgb(0.02, 0.02, 0.02)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    dx, dy = weave(frame)
    ctx.save()
    ctx.translate(W / 2 + dx, H / 2 + dy)
    ctx.scale(1.012, 1.012)                                         # a little over, so the weave shows no edge
    ctx.translate(-W / 2, -H / 2)
    a, b = span(t, *INSIDE), span(t, *PAGE_IN)
    if t < INSIDE[1]:
        outside(ctx, t)
    if a > 0 and t < PAGE_IN[1]:
        ctx.push_group()
        inside(ctx, t)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_in_out(a) if t < INSIDE[1] else 1.0)
    if b > 0:
        ctx.push_group()
        title_page(ctx, t)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_in_out(b))
    ctx.restore()
    film(ctx, t, frame)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
