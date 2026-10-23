"""Here I Stand: VizelVision as a Midwestern Lutheran congregation (ELCA), in winter.

1. Snowy dusk at Our Savior's: red brick, a white steeple, the lit windows, the letter board
   by the road (HERE WE STAND / HOTDISH SUN 5 PM), station wagons in the lot with snow on
   their roofs, and somebody in a purple parka crossing it with a quilted casserole carrier.
2. The oak doors, close. A sleeve in a black gown holds up a page, 19 THESES (on the
   Watching of Channel 19), and a hammer nails its four corners on the open logo, a nail a
   note, the page jolting and snow shaking off the arch. "Here I stand. I can do no other..."
   as the camera reads down the theses.
3. The fellowship hall downstairs: a drop ceiling, cinderblock, TASTE AND SEE on a felt
   banner, the coffee urn, a 9x13 of tater-tot hotdish, a green jello ring, the bars, the
   freewill offering basket, and the church's TV cart showing Channel 19. "...than watch
   Vizzle Vision." A hand takes a bar.
4. On the closed logo, a Luther rose on a winter night, a part a note: the gold ring and the
   blue field, the white rose, the red heart, and at its heart the station's TV. The wordmark
   drops in under it, EVANGELICAL LUTHERAN CHANNEL 19, and a sign in marker: BARS DOWNSTAIRS.

Hera, the pastor: "Here I stand. I can do no other..." / "...than watch Vizzle Vision." /
"There's bars downstairs."
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    font, glint, grain, mix, rounded_rect, span, text_path, vignette)

ID = 'elca'
NAME = 'Here I Stand'
KIND = 'ident'
ORDER = 37
DESCRIPTION = ('VizelVision as a Minnesota Lutheran church (ELCA) in the snow: 19 THESES nailed to the door on the '
               'open logo, "Here I stand. I can do no other... than watch Vizzle Vision", the fellowship hall\'s '
               'hotdish, jello and bars, and a Luther rose with the station\'s TV at its heart on the closed logo. '
               'There\'s bars downstairs. Hera.')
DURATION = 10.0
STILL_AT = 8.7
OVERLAYS = []

# Hit points (the music's too: elca_music.py).
FADE_IN = (0.0, 0.4)
PUSH = (0.3, 1.3)                                # the camera walks toward the church
TO_DOOR = (1.12, 1.3)                            # the dissolve to the doors
PAGE_UP = (1.25, 1.42)                           # the page goes up against the oak
HOLD = (1.3, 1.95)                               # the other hand holds it there
HAMMER = (1.5, 1.75, 2.0, 2.5)                   # the open logo: a nail a note
HAMMER_OUT = (2.72, 3.0)                         # the hammer leaves
READ = (2.9, 4.75)                               # the camera reads down the theses
STAND = 2.95                                     # "Here I stand. I can do no other..."
HYMN = (2.75, 3.25, 3.75, 4.25, 4.75, 5.25, 5.75, 6.25, 6.75)   # the organ: "A mighty fortress is our God"
HALL = (4.6, 4.9)                                # downstairs
WATCH = 5.15                                     # "...than watch Vizzle Vision."
BAR = (5.85, 6.35)                               # a hand takes a bar
SEAL_IN = (6.45, 6.95)                           # out into the snow again
CLOSED = 7.0                                     # the closed logo
ROSE = (7.0, 7.25, 7.5, 8.0)                     # ring and field, rose, heart, the TV
LOCKUP = 7.05                                    # the wordmark, a letter a sixteenth
SUBTITLE = (8.05, 8.45)
BARS = 7.8                                       # "There's bars downstairs."
SIGN = 7.95                                      # the marker sign
FADE = (9.25, 9.6)

BRICK = (0.55, 0.2, 0.15)
OAK = (0.4, 0.23, 0.12)
IRON = (0.13, 0.12, 0.12)
PARCH = (0.93, 0.86, 0.7)
INKBROWN = (0.22, 0.13, 0.07)
LAMP = (1.0, 0.8, 0.47)
SNOW = (0.92, 0.94, 0.99)
NIGHT = (0.06, 0.08, 0.2)
PURPLE = (0.36, 0.18, 0.55)
GOLD = (0.93, 0.74, 0.3)
CREAM = (0.97, 0.93, 0.82)
ROSE_BLUE = (0.36, 0.6, 0.88)
HEART_RED = (0.78, 0.1, 0.12)

THESES = ('1. Thou shalt watch Channel 19.', '2. Commercials are not a means of grace.', '3. Coffee is.',
          '4. The remote is held in common.', '5. Hotdish is not a sacrament. Yet.', '6. Lutefisk is optional.')
NAILS = ((205, 152), (575, 152), (205, 590), (575, 590))   # where the hammer drives them (the page's corners)


# ---------------------------------------------------------------- shared bits

def snowfall(ctx, t, seed, count, size, speed, alpha=0.9, drift=18.0):
    rand = random.Random(seed)
    for _ in range(count):
        x0, y0, r = rand.uniform(-40, W + 40), rand.uniform(0, H), rand.uniform(0.6, 1.0) * size
        sp = rand.uniform(0.7, 1.3) * speed
        ph = rand.uniform(0, TAU)
        y = (y0 + t * sp) % (H + 40) - 20
        x = x0 + drift * math.sin(t * 0.9 + ph)
        ctx.arc(x, y, r, 0, TAU)
        ctx.set_source_rgba(*SNOW, alpha * rand.uniform(0.55, 1.0))
        ctx.fill()


def bricks(ctx, x0, y0, x1, y1, seed, base=BRICK, row=16, length=40):
    rand = random.Random(seed)
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.set_source_rgb(*mix(base, (0.75, 0.7, 0.65), 0.35))      # mortar
    ctx.fill()
    y, k = y0, 0
    while y < y1:
        x = x0 - (length / 2 if k % 2 else 0)
        while x < x1:
            ctx.rectangle(max(x, x0) + 1.2, y + 1.2, min(x + length, x1) - max(x, x0) - 2.4, min(row, y1 - y) - 2.4)
            ctx.set_source_rgb(*mix(base, (0.25, 0.08, 0.06), rand.uniform(-0.25, 0.35)))
            ctx.fill()
            x += length
        y += row
        k += 1


# ---------------------------------------------------------------- 1. the church at dusk

def car(ctx, x, y, colour, roofbox=False):
    """A station wagon, snow on its roof, seen from the side."""
    ctx.save()
    ctx.translate(x, y)
    rounded_rect(ctx, 0, -30, 150, 32, 9)
    ctx.set_source_rgb(*colour)
    ctx.fill()
    ctx.move_to(14, -30)
    ctx.line_to(30, -56)
    ctx.line_to(136, -56)
    ctx.line_to(144, -30)
    ctx.close_path()
    ctx.set_source_rgb(*mix(colour, (0, 0, 0), 0.15))
    ctx.fill()
    for wx0, wx1 in ((34, 76), (82, 132)):                          # windows
        ctx.move_to(wx0 - (6 if wx0 < 40 else 0), -33)
        ctx.line_to(wx0 + (6 if wx0 < 40 else 0), -51)
        ctx.line_to(wx1, -51)
        ctx.line_to(wx1 + 3, -33)
        ctx.close_path()
        ctx.set_source_rgb(0.14, 0.18, 0.3)
        ctx.fill()
    rounded_rect(ctx, 26, -63, 114, 9, 4)                           # snow on the roof
    ctx.set_source_rgb(*SNOW)
    ctx.fill()
    if roofbox:
        rounded_rect(ctx, 46, -78, 76, 16, 7)
        ctx.set_source_rgb(0.12, 0.12, 0.14)
        ctx.fill()
        rounded_rect(ctx, 48, -84, 72, 8, 4)
        ctx.set_source_rgb(*SNOW)
        ctx.fill()
    for wx in (30, 118):
        ctx.arc(wx, 2, 14, 0, TAU)
        ctx.set_source_rgb(0.06, 0.06, 0.07)
        ctx.fill()
        ctx.arc(wx, 2, 6, 0, TAU)
        ctx.set_source_rgb(0.5, 0.52, 0.55)
        ctx.fill()
    ctx.restore()


@lru_cache(maxsize=None)
def exterior_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, 440)
    g.add_color_stop_rgb(0, 0.07, 0.09, 0.23)
    g.add_color_stop_rgb(0.5, 0.25, 0.25, 0.46)
    g.add_color_stop_rgb(0.85, 0.75, 0.5, 0.52)
    g.add_color_stop_rgb(1, 0.98, 0.68, 0.5)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(4)
    for _ in range(36):
        ctx.arc(rand.uniform(0, W), rand.uniform(0, 200), rand.uniform(0.6, 1.3), 0, TAU)
        ctx.set_source_rgba(1, 0.97, 0.9, rand.uniform(0.3, 0.8))
        ctx.fill()
    for k in range(70):                                              # the pines across the field
        x = k * 19 + rand.uniform(-6, 6)
        h = rand.uniform(26, 62)
        ctx.move_to(x - h * 0.32, 446)
        ctx.line_to(x, 446 - h)
        ctx.line_to(x + h * 0.32, 446)
        ctx.close_path()
        ctx.set_source_rgb(*mix((0.08, 0.13, 0.17), (0.25, 0.22, 0.35), rand.random() * 0.3))
        ctx.fill()
    g = cairo.LinearGradient(0, 440, 0, H)                         # the snow
    g.add_color_stop_rgb(0, 0.78, 0.76, 0.86)
    g.add_color_stop_rgb(1, 0.6, 0.64, 0.82)
    ctx.rectangle(0, 440, W, H - 440)
    ctx.set_source(g)
    ctx.fill()
    # the church: a brick front with a gable, the steeple rising from it
    bricks(ctx, 520, 270, 880, 478, 7)
    ctx.move_to(500, 276)
    ctx.line_to(700, 150)
    ctx.line_to(900, 276)
    ctx.close_path()
    ctx.set_source_rgb(0.95, 0.94, 0.92)
    ctx.fill()
    ctx.move_to(530, 276)
    ctx.line_to(700, 170)
    ctx.line_to(870, 276)
    ctx.close_path()
    ctx.save()
    ctx.clip()
    bricks(ctx, 520, 160, 880, 280, 8)
    ctx.restore()
    for side in (-1, 1):                                             # snow on the eaves
        ctx.move_to(700, 146)
        ctx.line_to(700 + side * 206, 276)
        ctx.line_to(700 + side * 196, 284)
        ctx.line_to(700, 158)
        ctx.close_path()
        ctx.set_source_rgb(*SNOW)
        ctx.fill()
    ctx.rectangle(655, 40, 90, 120)                                  # the steeple
    ctx.set_source_rgb(0.94, 0.93, 0.9)
    ctx.fill()
    for lx in (672, 712):                                            # louvres
        rounded_rect(ctx, lx, 70, 16, 46, 7)
        ctx.set_source_rgb(0.18, 0.18, 0.24)
        ctx.fill()
    ctx.move_to(645, 42)
    ctx.line_to(700, -70)
    ctx.line_to(755, 42)
    ctx.close_path()
    ctx.set_source_rgb(0.9, 0.9, 0.88)
    ctx.fill()
    ctx.move_to(700, -70)
    ctx.line_to(755, 42)
    ctx.line_to(700, 42)
    ctx.close_path()
    ctx.set_source_rgba(0.3, 0.3, 0.45, 0.25)
    ctx.fill()
    for wx in (570, 790):                                            # the lit windows, arched
        ctx.move_to(wx, 440)
        ctx.line_to(wx, 330)
        ctx.arc(wx + 20, 330, 20, math.pi, 0)
        ctx.line_to(wx + 40, 440)
        ctx.close_path()
        ctx.set_source_rgb(*LAMP)
        ctx.fill()
        ctx.rectangle(wx + 19, 315, 2, 125)
        ctx.rectangle(wx, 382, 40, 2)
        ctx.set_source_rgb(0.4, 0.25, 0.12)
        ctx.fill()
        g = cairo.RadialGradient(wx + 20, 390, 10, wx + 20, 390, 110)
        g.add_color_stop_rgba(0, *LAMP, 0.35)
        g.add_color_stop_rgba(1, *LAMP, 0)
        ctx.set_source(g)
        ctx.arc(wx + 20, 390, 110, 0, TAU)
        ctx.fill()
    ctx.arc(700, 230, 26, 0, TAU)                                    # the round window in the gable
    ctx.set_source_rgb(*LAMP)
    ctx.fill()
    ctx.arc(700, 230, 26, 0, TAU)
    ctx.set_source_rgb(0.95, 0.94, 0.9)
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.move_to(660, 478)                                            # the doors, arched oak
    ctx.line_to(660, 380)
    ctx.arc(700, 380, 40, math.pi, 0)
    ctx.line_to(740, 478)
    ctx.close_path()
    ctx.set_source_rgb(*OAK)
    ctx.fill()
    ctx.rectangle(699, 345, 2, 133)
    ctx.set_source_rgb(1, 0.82, 0.5)
    ctx.fill()
    for k in range(3):                                               # snowy steps
        ctx.rectangle(640 - k * 14, 478 + k * 9, 120 + k * 28, 9)
        ctx.set_source_rgb(*mix(SNOW, (0.6, 0.62, 0.78), 0.2 + 0.1 * k))
        ctx.fill()
    for lx in (612, 788):                                            # lamp posts by the door
        ctx.rectangle(lx - 2, 420, 4, 80)
        ctx.set_source_rgb(0.1, 0.1, 0.12)
        ctx.fill()
        g = cairo.RadialGradient(lx, 414, 2, lx, 414, 60)
        g.add_color_stop_rgba(0, 1, 0.9, 0.6, 0.9)
        g.add_color_stop_rgba(1, 1, 0.8, 0.5, 0)
        ctx.set_source(g)
        ctx.arc(lx, 414, 60, 0, TAU)
        ctx.fill()
    # the letter board by the road
    ctx.rectangle(232, 450, 8, 70)
    ctx.rectangle(412, 450, 8, 70)
    ctx.set_source_rgb(0.25, 0.2, 0.18)
    ctx.fill()
    rounded_rect(ctx, 214, 392, 224, 100, 6)
    ctx.set_source_rgb(0.97, 0.96, 0.92)
    ctx.fill()
    rounded_rect(ctx, 222, 416, 208, 68, 3)
    ctx.set_source_rgb(0.08, 0.08, 0.1)
    ctx.fill()
    ctx.set_source_rgb(0.15, 0.25, 0.45)
    font(ctx, 'C059', 15)
    text_path(ctx, "OUR SAVIOR'S LUTHERAN", 326, 410, tracking=1.0, align='center')
    ctx.fill()
    ctx.set_source_rgb(0.98, 0.98, 0.96)
    font(ctx, 'Nimbus Sans Narrow', 21)
    text_path(ctx, 'HERE WE STAND', 326, 444, tracking=2.0, align='center')
    text_path(ctx, 'HOTDISH SUN 5 PM', 326, 472, tracking=1.5, align='center')
    ctx.fill()
    rounded_rect(ctx, 210, 386, 232, 12, 5)                          # snow on the sign
    ctx.set_source_rgb(*SNOW)
    ctx.fill()
    # the lot: wagons with snow on their roofs
    for x, y, colour, box in ((930, 548, (0.12, 0.3, 0.22), True), (1100, 556, (0.62, 0.64, 0.68), False),
                              (1010, 610, (0.45, 0.12, 0.14), False)):
        car(ctx, x, y, colour, box)
    for x, y, r in ((60, 742, 190), (1240, 748, 200), (560, 770, 210)):   # snowbanks, plowed to the edges
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(1, 0.32)
        ctx.arc(0, 0, r, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*mix(SNOW, (0.66, 0.68, 0.85), 0.12))
        ctx.fill()
    return surface


def parishioner(ctx, t):
    """Somebody in a purple parka crossing the lot with a quilted casserole carrier."""
    p = span(t, 0.0, 1.3)
    x, y = 1180 - 330 * p, 532 + 18 * p
    step = math.sin(t * 9)
    ctx.save()
    ctx.translate(x, y)
    for k, sx in enumerate((-6, 6)):                                 # legs
        ctx.move_to(sx, 0)
        ctx.line_to(sx + (step if k else -step) * 6, 30)
        ctx.set_source_rgb(0.12, 0.12, 0.16)
        ctx.set_line_width(7)
        ctx.stroke()
    rounded_rect(ctx, -16, -46, 32, 50, 12)                          # the parka
    ctx.set_source_rgb(*PURPLE)
    ctx.fill()
    ctx.arc(0, -56, 11, 0, TAU)                                      # the hood
    ctx.set_source_rgb(*mix(PURPLE, INK, 0.2))
    ctx.fill()
    ctx.arc(-3, -55, 7, 0, TAU)
    ctx.set_source_rgb(0.92, 0.75, 0.62)
    ctx.fill()
    ctx.arc(1, -64, 9, math.pi, 0)                                   # a knit cap, gold
    ctx.set_source_rgb(*GOLD)
    ctx.fill()
    rounded_rect(ctx, -36, -24, 30, 18, 4)                           # the carrier
    ctx.set_source_rgb(0.75, 0.2, 0.25)
    ctx.fill()
    for qx in range(-34, -6, 7):
        ctx.move_to(qx, -24)
        ctx.line_to(qx + 4, -6)
    ctx.set_source_rgba(1, 1, 1, 0.35)
    ctx.set_line_width(1)
    ctx.stroke()
    ctx.restore()


def exterior(ctx, t):
    z = 1 + 0.22 * ease_in_out(span(t, *PUSH))
    ctx.save()
    ctx.translate(700, 430)
    ctx.scale(z, z)
    ctx.translate(-700, -430)
    ctx.set_source_surface(exterior_surface(), 0, 0)
    ctx.paint()
    parishioner(ctx, t)
    snowfall(ctx, t, 1, 160, 2.2, 55)
    ctx.restore()


# ---------------------------------------------------------------- 2. the door and the theses

@lru_cache(maxsize=None)
def door_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    bricks(ctx, 0, 0, W, H, 21, row=30, length=78)
    ctx.move_to(110, H)                                              # the opening, round-arched
    ctx.line_to(110, 260)
    ctx.curve_to(110, 20, 1170, 20, 1170, 260)
    ctx.line_to(1170, H)
    ctx.close_path()
    ctx.set_source_rgb(0.86, 0.84, 0.8)                              # a limestone surround
    ctx.set_line_width(36)
    ctx.stroke_preserve()
    ctx.clip()
    rand = random.Random(9)
    for k, x in enumerate(range(110, 1171, 66)):                     # oak planks
        ctx.rectangle(x, 0, 66, H)
        ctx.set_source_rgb(*mix(OAK, (0.2, 0.1, 0.05), rand.uniform(-0.25, 0.3)))
        ctx.fill()
        for _ in range(9):                                           # grain
            gx = x + rand.uniform(6, 60)
            ctx.move_to(gx, 0)
            ctx.curve_to(gx + rand.uniform(-8, 8), 240, gx + rand.uniform(-8, 8), 480, gx + rand.uniform(-5, 5), H)
            ctx.set_source_rgba(0.12, 0.06, 0.02, rand.uniform(0.15, 0.4))
            ctx.set_line_width(rand.uniform(0.8, 2.2))
            ctx.stroke()
        ctx.rectangle(x, 0, 2, H)
        ctx.set_source_rgba(0, 0, 0, 0.45)
        ctx.fill()
    g = cairo.LinearGradient(632, 0, 648, 0)                         # the seam, warm light behind
    g.add_color_stop_rgba(0, 1, 0.8, 0.45, 0)
    g.add_color_stop_rgba(0.5, 1, 0.82, 0.5, 0.9)
    g.add_color_stop_rgba(1, 1, 0.8, 0.45, 0)
    ctx.rectangle(630, 0, 20, H)
    ctx.set_source(g)
    ctx.fill()
    for y in (210, 640):                                             # strap hinges
        for side in (-1, 1):
            x0, x1 = 640 + side * 520, 640 + side * 110
            ctx.move_to(x0, y - 16)
            ctx.line_to(x1, y - 9)
            ctx.line_to(x1, y + 9)
            ctx.line_to(x0, y + 16)
            ctx.close_path()
            ctx.arc(x1, y, 15, 0, TAU)                                # the strap's round end
            ctx.set_source_rgb(*IRON)
            ctx.fill()
            for bx in range(int(min(x0, 640 + side * 140)) + 20, int(max(x0, 640 + side * 140)), 70):
                ctx.arc(bx, y, 4.5, 0, TAU)
                ctx.set_source_rgb(0.32, 0.3, 0.3)
                ctx.fill()
    ctx.arc(820, 420, 46, 0, TAU)                                    # the ring pull
    ctx.set_source_rgb(*IRON)
    ctx.set_line_width(10)
    ctx.stroke()
    ctx.arc(820, 374, 14, 0, TAU)
    ctx.fill()
    ctx.reset_clip()
    g = cairo.LinearGradient(0, 0, W, 0)                             # dusk light from the left
    g.add_color_stop_rgba(0, 0.45, 0.5, 0.9, 0.18)
    g.add_color_stop_rgba(1, 0.0, 0.0, 0.1, 0.3)
    ctx.set_source(g)
    ctx.paint()
    ctx.move_to(70, 250)                                             # snow on the arch
    ctx.curve_to(70, -10, 1210, -10, 1210, 250)
    ctx.set_source_rgb(*SNOW)
    ctx.set_line_width(14)
    ctx.stroke()
    ctx.rectangle(0, 676, W, 44)                                     # the threshold, drifted
    ctx.set_source_rgb(0.62, 0.6, 0.58)
    ctx.fill()
    for k in range(9):
        ctx.save()
        ctx.translate(k * 160 + 30, 690)
        ctx.scale(1, 0.3)
        ctx.arc(0, 0, 110, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*mix(SNOW, (0.7, 0.72, 0.88), 0.2))
        ctx.fill()
    return surface


@lru_cache(maxsize=None)
def page_surface():
    """The theses, on a ragged page."""
    pw, ph = 440, 500
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, pw + 20, ph + 20)
    ctx = cairo.Context(surface)
    ctx.translate(10, 10)
    rand = random.Random(95)
    ctx.move_to(0, 0)
    for k in range(1, 23):
        ctx.line_to(k * pw / 22, rand.uniform(-3, 3))
    for k in range(1, 27):
        ctx.line_to(pw + rand.uniform(-3, 3), k * ph / 26)
    for k in range(21, -1, -1):
        ctx.line_to(k * pw / 22, ph + rand.uniform(-3, 3))
    for k in range(25, 0, -1):
        ctx.line_to(rand.uniform(-3, 3), k * ph / 26)
    ctx.close_path()
    g = cairo.RadialGradient(pw / 2, ph / 2, 60, pw / 2, ph / 2, 360)
    g.add_color_stop_rgb(0, *PARCH)
    g.add_color_stop_rgb(1, 0.82, 0.7, 0.5)
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.45, 0.3, 0.15, 0.5)
    ctx.set_line_width(1.5)
    ctx.stroke()
    for _ in range(30):
        ctx.arc(rand.uniform(10, pw - 10), rand.uniform(10, ph - 10), rand.uniform(1, 6), 0, TAU)
        ctx.set_source_rgba(0.6, 0.4, 0.2, rand.uniform(0.04, 0.15))
        ctx.fill()
    ctx.set_source_rgb(*INKBROWN)
    font(ctx, 'C059', 50)
    text_path(ctx, '19 THESES', pw / 2, 84, tracking=2, align='center')
    ctx.fill()
    font(ctx, 'C059', 18, bold=False, italic=True)
    text_path(ctx, 'on the Watching of Channel 19', pw / 2, 114, align='center')
    ctx.fill()
    ctx.rectangle(60, 128, pw - 120, 1.5)
    ctx.fill()
    font(ctx, 'C059', 19, bold=False)
    for k, line in enumerate(THESES):
        text_path(ctx, line, 34, 162 + k * 31)
        ctx.fill()
    for k in range(7):                                               # the rest, in a hurried hand
        y = 162 + (len(THESES) + k) * 26 + 4
        ctx.move_to(34, y)
        x = 34
        while x < pw - 40 - rand.uniform(0, 120):
            x += 6
            ctx.line_to(x, y + rand.uniform(-3, 3))
        ctx.set_source_rgba(*INKBROWN, 0.55)
        ctx.set_line_width(1.3)
        ctx.stroke()
    ctx.set_source_rgb(*INKBROWN)
    font(ctx, 'C059', 16, bold=False, italic=True)
    text_path(ctx, 'Wittenberg, Minn.', pw - 34, ph - 26, align='right')
    ctx.fill()
    return surface


def nail_head(ctx, x, y):
    ctx.arc(x, y, 7, 0, TAU)
    ctx.set_source_rgb(0.2, 0.2, 0.22)
    ctx.fill()
    ctx.arc(x - 2, y - 2, 3, 0, TAU)
    ctx.set_source_rgba(0.85, 0.85, 0.9, 0.8)
    ctx.fill()


def jolt(t):
    """The page and the door jump at each blow, settling."""
    dx = dy = 0.0
    for k, s in enumerate(HAMMER):
        if t >= s:
            a = math.exp(-(t - s) * 18) * (9 if k == 3 else 5)
            dx += a * math.sin((t - s) * 70)
            dy += a * 0.5 * math.cos((t - s) * 61)
    return dx, dy


def hammer_pose(t):
    """Where the wrist is and the handle's angle (0 = the face on the nail)."""
    targets = list(NAILS)
    k = 0
    while k < 3 and t > HAMMER[k] + 0.06:
        k += 1
    nx, ny = targets[k]
    if k > 0 and t < HAMMER[k] - 0.13:                               # carrying over to the next nail
        px, py = targets[k - 1]
        p = ease_in_out(span(t, HAMMER[k - 1] + 0.06, HAMMER[k] - 0.13))
        nx, ny = px + (nx - px) * p, py + (ny - py) * p
    s = HAMMER[k]
    if t < s:
        angle = 0.95 * (1 - ease_in(span(t, s - 0.13, s), 2)) if t > s - 0.13 else 0.95
    else:
        angle = 0.95 * ease_out(span(t, s, s + 0.16)) if k < 3 else 0.25 * ease_out(span(t, s, s + 0.3))
    reach = 1 - ease_out(span(t, PAGE_UP[0], HAMMER[0] - 0.14))
    leave = ease_in(span(t, *HAMMER_OUT))
    return nx, ny, angle, 520 * reach + 700 * leave


def hammer(ctx, t):
    if t < PAGE_UP[0] or t > HAMMER_OUT[1]:
        return
    nx, ny, angle, away = hammer_pose(t)
    ctx.save()
    ctx.translate(nx + 46 + away, ny + 18 + away * 0.15)              # the head's face meets the nail
    ctx.rotate(-angle)
    # the handle runs from the head down-right to the hand
    ctx.save()
    ctx.rotate(0.62)
    rounded_rect(ctx, 0, -9, 250, 18, 8)
    ctx.set_source_rgb(0.62, 0.42, 0.22)
    ctx.fill()
    ctx.rectangle(10, -4, 220, 2)
    ctx.set_source_rgba(1, 1, 1, 0.18)
    ctx.fill()
    ctx.translate(250, 0)                                            # the hand and the gown's sleeve
    ctx.arc(-14, 0, 24, 0, TAU)
    ctx.set_source_rgb(0.9, 0.72, 0.6)
    ctx.fill()
    ctx.move_to(-2, -30)
    ctx.curve_to(120, -46, 240, -52, 330, -56)
    ctx.line_to(330, 64)
    ctx.curve_to(240, 58, 120, 50, -2, 30)
    ctx.close_path()
    ctx.set_source_rgb(0.07, 0.07, 0.09)
    ctx.fill()
    ctx.move_to(-2, -30)
    ctx.line_to(-2, 30)
    ctx.set_source_rgb(0.95, 0.95, 0.95)                             # a white cuff
    ctx.set_line_width(8)
    ctx.stroke()
    ctx.restore()
    ctx.save()                                                       # the head
    ctx.rotate(0.62 - math.pi / 2)
    rounded_rect(ctx, -46, -20, 92, 30, 6)
    ctx.set_source_rgb(0.25, 0.25, 0.28)
    ctx.fill()
    ctx.rectangle(-44, -18, 88, 6)
    ctx.set_source_rgba(1, 1, 1, 0.25)
    ctx.fill()
    ctx.restore()
    ctx.restore()


def holding_hand(ctx, t):
    """The other hand holds the page flat till the top is nailed."""
    p = ease_out(span(t, PAGE_UP[0], PAGE_UP[1])) * (1 - ease_in(span(t, HOLD[1] - 0.2, HOLD[1])))
    if p <= 0:
        return
    x, y = 250 - 420 * (1 - p), 520
    ctx.save()
    ctx.translate(x, y)
    ctx.move_to(-30, -30)                                            # the gown's sleeve, from off left
    ctx.line_to(-330, -70)
    ctx.line_to(-330, 70)
    ctx.line_to(-30, 30)
    ctx.close_path()
    ctx.set_source_rgb(0.07, 0.07, 0.09)
    ctx.fill()
    rounded_rect(ctx, -36, -32, 9, 64, 3)
    ctx.set_source_rgb(0.95, 0.95, 0.95)
    ctx.fill()
    ctx.move_to(-28, -24)                                            # the hand, flat, fingers spread
    ctx.curve_to(10, -40, 40, -34, 52, -20)
    for k, (fx, fy) in enumerate(((92, -30), (104, -8), (100, 14), (84, 32))):
        ctx.line_to(fx, fy)
        ctx.line_to(48, -12 + k * 12)
    ctx.curve_to(40, 40, 0, 44, -28, 24)
    ctx.close_path()
    ctx.set_source_rgb(0.86, 0.64, 0.52)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.35, 0.18, 0.1, 0.9)
    ctx.set_line_width(2.5)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()
    ctx.move_to(30, -34)                                             # the thumb
    ctx.curve_to(44, -56, 62, -60, 66, -50)
    ctx.curve_to(60, -40, 50, -32, 44, -24)
    ctx.set_source_rgb(0.86, 0.64, 0.52)
    ctx.fill_preserve()
    ctx.set_source_rgba(0.35, 0.18, 0.1, 0.9)
    ctx.stroke()
    ctx.restore()


def snow_puffs(ctx, t):
    """Snow shaken off the arch at each blow."""
    for k, s in enumerate(HAMMER):
        if not s <= t < s + 1.1:
            continue
        rand = random.Random(40 + k)
        u = t - s
        for _ in range(26 + 10 * (k == 3)):
            x = rand.uniform(220, 1060)
            y = 40 + abs(x - 640) * 0.18 + rand.uniform(-10, 10) + 300 * u * u + rand.uniform(20, 90) * u
            r = rand.uniform(1.5, 4)
            ctx.arc(x + rand.uniform(-20, 20) * u, y, r, 0, TAU)
            ctx.set_source_rgba(*SNOW, 0.9 * (1 - u / 1.1))
            ctx.fill()


def impact(ctx, t):
    for k, (s, (x, y)) in enumerate(zip(HAMMER, NAILS)):
        p = span(t, s, s + 0.12)
        if 0 < p < 1:
            ctx.save()
            ctx.translate(x, y)
            for j in range(8):
                a = j * TAU / 8 + 0.3
                r0, r1 = 12 + 20 * p, 24 + 34 * p
                ctx.move_to(math.cos(a) * r0, math.sin(a) * r0)
                ctx.line_to(math.cos(a) * r1, math.sin(a) * r1)
            ctx.set_source_rgba(1, 0.95, 0.7, 1 - p)
            ctx.set_line_width(4)
            ctx.stroke()
            ctx.restore()


def door(ctx, t):
    zoom = 1 + 0.04 * span(t, PAGE_UP[0], READ[0]) + 0.34 * ease_in_out(span(t, *READ))
    cx, cy = 640 + (395 - 640) * ease_in_out(span(t, *READ)), 360 + (330 - 360) * ease_in_out(span(t, *READ))
    dx, dy = jolt(t)
    ctx.save()
    ctx.translate(640, 360)
    ctx.scale(zoom, zoom)
    ctx.translate(-cx + dx * 0.3, -cy + dy * 0.3)
    ctx.set_source_surface(door_surface(), 0, 0)
    ctx.paint()
    up = ease_out(span(t, *PAGE_UP))
    if up > 0:
        ctx.save()
        ctx.translate(170 + dx + 60 * (1 - up), 112 + dy - 30 * (1 - up))
        ctx.rotate(-0.05 * (1 - up) + 0.006)
        ctx.set_source_rgba(0, 0, 0, 0.35)                           # its shadow on the oak
        ctx.rectangle(14, 14, 440, 500)
        ctx.fill()
        ctx.set_source_surface(page_surface(), -10, -10)
        ctx.paint_with_alpha(min(1.0, up * 2))
        ctx.restore()
    for s, (x, y) in zip(HAMMER, NAILS):
        if t >= s:
            nail_head(ctx, x + dx, y + dy)
    impact(ctx, t)
    holding_hand(ctx, t)
    hammer(ctx, t)
    snow_puffs(ctx, t)
    ctx.restore()
    snowfall(ctx, t, 2, 40, 3.2, 70, alpha=0.7)


# ---------------------------------------------------------------- 3. the fellowship hall

@lru_cache(maxsize=None)
def hall_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.rectangle(0, 0, W, 118)                                      # the drop ceiling
    ctx.set_source_rgb(0.88, 0.87, 0.82)
    ctx.fill()
    for x in range(-40, W + 40, 120):
        ctx.move_to(x, 0)
        ctx.line_to(640 + (x - 640) * 1.25, 118)
    for y in (30, 64, 96):
        ctx.move_to(0, y)
        ctx.line_to(W, y)
    ctx.set_source_rgb(0.7, 0.69, 0.64)
    ctx.set_line_width(2)
    ctx.stroke()
    for x0 in (300, 860):                                            # fluorescent panels
        ctx.move_to(x0, 34)
        ctx.line_to(x0 + 120, 34)
        ctx.line_to(x0 + 132, 62)
        ctx.line_to(x0 - 12, 62)
        ctx.close_path()
        ctx.set_source_rgb(1, 1, 0.97)
        ctx.fill()
    ctx.rectangle(0, 118, W, 330)                                    # cinderblock, painted cream
    ctx.set_source_rgb(0.9, 0.86, 0.74)
    ctx.fill()
    y, k = 118, 0
    while y < 448:
        ctx.move_to(0, y)
        ctx.line_to(W, y)
        for x in range(-60 if k % 2 else 0, W, 120):
            ctx.move_to(x, y)
            ctx.line_to(x, y + 40)
        y += 40
        k += 1
    ctx.set_source_rgba(0.55, 0.5, 0.4, 0.5)
    ctx.set_line_width(1.5)
    ctx.stroke()
    # the felt banner: TASTE AND SEE, a loaf and a fish
    ctx.move_to(170, 140)
    ctx.line_to(400, 140)
    ctx.line_to(400, 360)
    ctx.line_to(285, 392)
    ctx.line_to(170, 360)
    ctx.close_path()
    ctx.set_source_rgb(0.12, 0.42, 0.28)
    ctx.fill()
    ctx.rectangle(160, 132, 250, 10)
    ctx.set_source_rgb(0.45, 0.3, 0.15)
    ctx.fill()
    ctx.set_source_rgb(0.98, 0.86, 0.35)
    font(ctx, 'URW Gothic', 34)
    text_path(ctx, 'TASTE', 285, 190, tracking=3, align='center')
    font(ctx, 'URW Gothic', 22)
    text_path(ctx, 'AND', 285, 220, tracking=3, align='center')
    font(ctx, 'URW Gothic', 34)
    text_path(ctx, 'SEE', 285, 258, tracking=3, align='center')
    ctx.fill()
    ctx.save()                                                       # the loaf
    ctx.translate(240, 316)
    ctx.scale(1, 0.62)
    ctx.arc(0, 0, 30, math.pi, 0)
    ctx.restore()
    ctx.close_path()
    ctx.set_source_rgb(0.85, 0.6, 0.3)
    ctx.fill()
    ctx.move_to(300, 310)                                            # the fish
    ctx.curve_to(320, 290, 350, 290, 362, 310)
    ctx.curve_to(350, 330, 320, 330, 300, 310)
    ctx.move_to(362, 310)
    ctx.line_to(378, 296)
    ctx.line_to(378, 324)
    ctx.close_path()
    ctx.set_source_rgb(0.95, 0.95, 0.98)
    ctx.fill()
    # the bulletin board
    rounded_rect(ctx, 470, 170, 230, 150, 4)
    ctx.set_source_rgb(0.72, 0.55, 0.38)
    ctx.fill()
    rand = random.Random(12)
    for k, (label, colour) in enumerate((('QUILTING TUES', (1, 1, 0.9)), ('LEFSE SIGN-UP', (0.9, 0.95, 1)),
                                         ('LUTEFISK DINNER', (1, 0.9, 0.9)), ('CONFIRMATION', (0.95, 1, 0.9)))):
        x, y = 482 + (k % 2) * 110, 182 + (k // 2) * 66
        ctx.save()
        ctx.translate(x + 50, y + 28)
        ctx.rotate(rand.uniform(-0.06, 0.06))
        ctx.rectangle(-50, -28, 100, 58)
        ctx.set_source_rgb(*colour)
        ctx.fill()
        ctx.set_source_rgb(0.2, 0.2, 0.25)
        font(ctx, 'Nimbus Sans Narrow', 11)
        text_path(ctx, label, 0, -12, align='center')
        ctx.fill()
        for j in range(3):
            ctx.rectangle(-38, -2 + j * 8, 76 - j * 14, 2)
        ctx.set_source_rgba(0.3, 0.3, 0.35, 0.5)
        ctx.fill()
        ctx.arc(0, -24, 3, 0, TAU)
        ctx.set_source_rgb(0.8, 0.1, 0.1)
        ctx.fill()
        ctx.restore()
    # the kitchen pass-through, its shutter half up
    rounded_rect(ctx, 760, 176, 220, 150, 3)
    ctx.set_source_rgb(0.6, 0.6, 0.6)
    ctx.fill()
    ctx.rectangle(770, 186, 200, 130)
    ctx.set_source_rgb(0.95, 0.93, 0.85)
    ctx.fill()
    for y in range(186, 248, 8):
        ctx.rectangle(770, y, 200, 6)
        ctx.set_source_rgb(0.75, 0.75, 0.78)
        ctx.fill()
    for x, colour in ((800, (0.85, 0.2, 0.2)), (850, (0.2, 0.5, 0.75)), (900, (0.9, 0.85, 0.75))):   # mugs on the counter
        rounded_rect(ctx, x, 284, 26, 28, 4)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    # the floor: checkered linoleum
    ctx.rectangle(0, 448, W, H - 448)
    ctx.set_source_rgb(0.85, 0.83, 0.72)
    ctx.fill()
    for row in range(8):
        y0 = 448 + row * row * 5 + row * 6
        y1 = 448 + (row + 1) ** 2 * 5 + (row + 1) * 6
        for col in range(-12, 14):
            if (row + col) % 2:
                continue
            xa, xb = 640 + col * 70 * (1 + row * 0.2), 640 + (col + 1) * 70 * (1 + row * 0.2)
            xc, xd = 640 + (col + 1) * 70 * (1 + (row + 1) * 0.2), 640 + col * 70 * (1 + (row + 1) * 0.2)
            ctx.move_to(xa, y0)
            ctx.line_to(xb, y0)
            ctx.line_to(xc, y1)
            ctx.line_to(xd, y1)
            ctx.close_path()
            ctx.set_source_rgb(0.38, 0.55, 0.4)
            ctx.fill()
    # the TV cart, right
    ctx.rectangle(1030, 420, 10, 230)
    ctx.rectangle(1220, 420, 10, 230)
    ctx.rectangle(1020, 520, 220, 10)
    ctx.rectangle(1020, 640, 220, 10)
    ctx.set_source_rgb(0.12, 0.12, 0.14)
    ctx.fill()
    rounded_rect(ctx, 1012, 404, 236, 22, 3)
    ctx.fill()
    for wx in (1035, 1225):
        ctx.arc(wx, 662, 10, 0, TAU)
        ctx.fill()
    rounded_rect(ctx, 1030, 232, 200, 176, 14)                       # the set
    ctx.set_source_rgb(0.22, 0.2, 0.2)
    ctx.fill()
    rounded_rect(ctx, 1050, 252, 150, 116, 18)
    ctx.set_source_rgb(0.05, 0.06, 0.08)
    ctx.fill()
    for k in range(2):
        ctx.arc(1214, 280 + k * 34, 7, 0, TAU)
        ctx.set_source_rgb(0.6, 0.6, 0.6)
        ctx.fill()
    ctx.move_to(1110, 232)                                           # rabbit ears
    ctx.line_to(1070, 150)
    ctx.move_to(1150, 232)
    ctx.line_to(1196, 156)
    ctx.set_source_rgb(0.7, 0.7, 0.72)
    ctx.set_line_width(4)
    ctx.stroke()
    # the long folding table, its paper cloth
    ctx.move_to(30, 520)
    ctx.line_to(990, 520)
    ctx.line_to(1010, 610)
    ctx.line_to(10, 610)
    ctx.close_path()
    ctx.set_source_rgb(0.97, 0.97, 0.95)
    ctx.fill()
    ctx.rectangle(10, 610, 1000, 26)
    ctx.set_source_rgb(0.88, 0.88, 0.86)
    ctx.fill()
    for lx in (60, 960):
        ctx.rectangle(lx, 636, 10, 84)
        ctx.set_source_rgb(0.3, 0.3, 0.32)
        ctx.fill()
    # the coffee urn
    g = cairo.LinearGradient(70, 0, 190, 0)
    for stop, v in ((0, 0.55), (0.3, 0.92), (0.55, 0.75), (1, 0.5)):
        g.add_color_stop_rgb(stop, v, v, v + 0.03)
    rounded_rect(ctx, 70, 330, 120, 220, 16)
    ctx.set_source(g)
    ctx.fill()
    rounded_rect(ctx, 64, 316, 132, 24, 10)
    ctx.set_source(g)
    ctx.fill()
    ctx.arc(130, 312, 12, math.pi, 0)
    ctx.set_source_rgb(0.15, 0.15, 0.16)
    ctx.fill()
    for hx in (62, 198):
        ctx.rectangle(hx - 4, 360, 8, 44)
        ctx.set_source_rgb(0.15, 0.15, 0.16)
        ctx.fill()
    rounded_rect(ctx, 118, 500, 24, 14, 3)                            # the spigot
    ctx.set_source_rgb(0.15, 0.15, 0.16)
    ctx.fill()
    ctx.rectangle(90, 390, 80, 40)                                   # a strip of masking tape
    ctx.set_source_rgb(0.93, 0.88, 0.7)
    ctx.fill()
    ctx.set_source_rgb(0.15, 0.15, 0.4)
    font(ctx, 'Nimbus Sans Narrow', 20)
    text_path(ctx, 'REGULAR', 130, 417, align='center')
    ctx.fill()
    for k in range(5):                                               # styrofoam cups
        ctx.move_to(212, 520 - k * 9)
        ctx.line_to(244, 520 - k * 9)
        ctx.line_to(240, 476 - k * 9)
        ctx.line_to(216, 476 - k * 9)
        ctx.close_path()
        ctx.set_source_rgb(0.98, 0.98, 0.97)
        ctx.fill_preserve()
        ctx.set_source_rgba(0.6, 0.6, 0.6, 0.6)
        ctx.set_line_width(1)
        ctx.stroke()
    # the hotdish, a 9x13 of tater tots
    ctx.move_to(280, 540)
    ctx.line_to(480, 540)
    ctx.line_to(492, 590)
    ctx.line_to(268, 590)
    ctx.close_path()
    ctx.set_source_rgb(0.75, 0.75, 0.78)
    ctx.fill()
    ctx.move_to(288, 544)
    ctx.line_to(472, 544)
    ctx.line_to(482, 584)
    ctx.line_to(278, 584)
    ctx.close_path()
    ctx.set_source_rgb(0.55, 0.38, 0.2)
    ctx.fill()
    for row in range(4):
        for col in range(12):
            x = 290 + col * 16 + row * -3 + 2
            y = 549 + row * 10
            rounded_rect(ctx, x, y, 13, 8, 3)
            ctx.set_source_rgb(*mix((0.93, 0.68, 0.3), (0.75, 0.45, 0.15), ((row * 5 + col * 3) % 7) / 7))
            ctx.fill()
    # the bars: lemon, dusted, cut in squares
    ctx.move_to(770, 540)
    ctx.line_to(950, 540)
    ctx.line_to(962, 590)
    ctx.line_to(758, 590)
    ctx.close_path()
    ctx.set_source_rgb(0.75, 0.75, 0.78)
    ctx.fill()
    for row in range(3):
        for col in range(7):
            x, y = 776 + col * 25 - row * 3, 546 + row * 13
            ctx.rectangle(x, y, 22, 11)
            ctx.set_source_rgb(0.98, 0.9, 0.55)
            ctx.fill()
            ctx.rectangle(x, y, 22, 4)
            ctx.set_source_rgb(1, 1, 0.97)
            ctx.fill()
    # the freewill offering basket
    ctx.save()
    ctx.translate(600, 588)
    ctx.scale(1, 0.4)
    ctx.arc(0, 0, 44, 0, math.pi)
    ctx.restore()
    ctx.close_path()
    ctx.set_source_rgb(0.62, 0.45, 0.25)
    ctx.fill()
    rounded_rect(ctx, 560, 600, 80, 22, 3)
    ctx.set_source_rgb(1, 1, 0.97)
    ctx.fill()
    ctx.set_source_rgb(0.2, 0.2, 0.25)
    font(ctx, 'Nimbus Sans Narrow', 12)
    text_path(ctx, 'FREEWILL OFFERING', 600, 615, align='center')
    ctx.fill()
    # a crockpot
    rounded_rect(ctx, 650, 520, 90, 64, 18)
    ctx.set_source_rgb(0.92, 0.88, 0.78)
    ctx.fill()
    ctx.rectangle(650, 548, 90, 12)
    ctx.set_source_rgb(0.55, 0.38, 0.2)
    ctx.fill()
    ctx.save()
    ctx.translate(695, 520)
    ctx.scale(1, 0.32)
    ctx.arc(0, 0, 46, math.pi, 0)
    ctx.restore()
    ctx.set_source_rgba(0.8, 0.88, 0.95, 0.8)
    ctx.fill()
    ctx.arc(695, 504, 7, 0, TAU)
    ctx.set_source_rgb(0.1, 0.1, 0.1)
    ctx.fill()
    return surface


def tv_picture(ctx, t):
    """The cart's set, showing Channel 19."""
    ctx.save()
    rounded_rect(ctx, 1050, 252, 150, 116, 18)
    ctx.clip()
    g = cairo.LinearGradient(0, 252, 0, 368)
    g.add_color_stop_rgb(0, 0.1, 0.35, 0.85)
    g.add_color_stop_rgb(1, 0.05, 0.15, 0.45)
    ctx.set_source(g)
    ctx.paint()
    p = back_out(span(t, WATCH + 0.6, WATCH + 1.0))
    ctx.translate(1125, 300)
    ctx.scale(0.4 + 0.6 * p, 0.4 + 0.6 * p)
    rounded_rect(ctx, -34, -26, 68, 50, 10)
    ctx.set_source_rgb(*TEAL)
    ctx.fill()
    rounded_rect(ctx, -26, -19, 40, 36, 7)
    ctx.set_source_rgb(0.18, 0.35, 0.9)
    ctx.fill()
    ctx.set_source_rgb(1, 1, 1)
    font(ctx, 'URW Gothic', 30)
    text_path(ctx, 'V', -6, 11, align='center')
    ctx.fill()
    ctx.restore()
    ctx.set_source_rgb(1, 1, 1)
    font(ctx, 'URW Gothic', 15)
    text_path(ctx, 'VIZELVISION 19', 1125, 356, tracking=1.5, align='center')
    ctx.fill()
    ctx.save()
    rounded_rect(ctx, 1050, 252, 150, 116, 18)
    ctx.clip()
    for y in range(252, 368, 3):
        ctx.rectangle(1050, y, 150, 1)
    ctx.set_source_rgba(0, 0, 0, 0.18)
    ctx.fill()
    g = cairo.RadialGradient(1105, 280, 5, 1105, 280, 120)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.22)
    g.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(g)
    ctx.paint()
    ctx.restore()


def steam(ctx, t, x, y, seed, strength=1.0):
    rand = random.Random(seed)
    for k in range(6):
        u = (t * 0.5 + k / 6 + rand.random() * 0.1) % 1
        sx = x + math.sin(u * 7 + k) * 10 * u
        ctx.arc(sx, y - u * 90, 8 + 18 * u, 0, TAU)
        ctx.set_source_rgba(1, 1, 1, 0.16 * math.sin(u * math.pi) * strength)
        ctx.fill()


def jello(ctx, t):
    """A green jello ring with fruit in it, wobbling."""
    wob = 0.04 * math.sin(t * 13) * math.exp(-((t - HALL[0]) % 2.0) * 1.2) + 0.015 * math.sin(t * 9)
    ctx.save()
    ctx.translate(520, 586)
    ctx.save()
    ctx.scale(1, 0.3)
    ctx.arc(0, 0, 60, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.95, 0.95, 0.97)
    ctx.fill()
    ctx.scale(1 + wob, 1 - wob)
    ctx.move_to(-46, 0)
    ctx.curve_to(-48, -44, -20, -58, 0, -58)
    ctx.curve_to(20, -58, 48, -44, 46, 0)
    ctx.close_path()
    g = cairo.LinearGradient(-46, 0, 46, 0)
    g.add_color_stop_rgba(0, 0.15, 0.6, 0.15, 0.95)
    g.add_color_stop_rgba(0.4, 0.45, 0.9, 0.35, 0.9)
    g.add_color_stop_rgba(1, 0.12, 0.5, 0.12, 0.95)
    ctx.set_source(g)
    ctx.fill()
    for (fx, fy, colour) in ((-26, -18, (1, 0.6, 0.3)), (8, -30, (0.95, 0.2, 0.3)), (24, -12, (1, 0.85, 0.5)),
                             (-6, -10, (1, 0.6, 0.3)), (-18, -38, (0.95, 0.95, 0.85))):
        ctx.arc(fx, fy, 5, 0, TAU)
        ctx.set_source_rgba(*colour, 0.75)
        ctx.fill()
    ctx.save()
    ctx.scale(1, 0.3)
    ctx.arc(0, -195, 14, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.98, 0.98, 0.96)
    ctx.fill()
    ctx.move_to(-30, -44)
    ctx.curve_to(-20, -54, -8, -56, 2, -55)
    ctx.set_source_rgba(1, 1, 1, 0.6)
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.restore()


def bar_hand(ctx, t):
    """Somebody's hand takes a bar."""
    p = span(t, *BAR)
    if p <= 0 or p >= 1:
        return
    reach = math.sin(p * math.pi)
    x, y = 935 + 30 * (1 - reach), 760 - 200 * reach
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(-0.25)
    rounded_rect(ctx, -26, 0, 52, 200, 20)
    ctx.set_source_rgb(*PURPLE)
    ctx.fill()
    ctx.arc(0, -6, 26, 0, TAU)
    ctx.set_source_rgb(0.92, 0.75, 0.62)
    ctx.fill()
    if p > 0.5:                                                      # with the bar
        ctx.rectangle(-12, -40, 24, 13)
        ctx.set_source_rgb(0.98, 0.9, 0.55)
        ctx.fill()
        ctx.rectangle(-12, -40, 24, 4)
        ctx.set_source_rgb(1, 1, 0.97)
        ctx.fill()
    ctx.restore()


def hall(ctx, t):
    z = 1 + 0.05 * span(t, HALL[0], SEAL_IN[1])
    ctx.save()
    ctx.translate(640, 400)
    ctx.scale(z, z)
    ctx.translate(-640, -400)
    ctx.set_source_surface(hall_surface(), 0, 0)
    ctx.paint()
    if t > BAR[0] + 0.25:                                            # a gap in the bars
        ctx.rectangle(926 - 6, 546, 22, 11)
        ctx.set_source_rgb(0.75, 0.75, 0.78)
        ctx.fill()
    tv_picture(ctx, t)
    jello(ctx, t)
    steam(ctx, t, 130, 306, 3, 1.0)
    steam(ctx, t, 380, 540, 4, 0.6)
    flick = 0.9 + 0.1 * math.sin(t * 50)                             # the urn's ready light
    ctx.arc(162, 470, 6, 0, TAU)
    ctx.set_source_rgb(1, 0.2 * flick, 0.1)
    ctx.fill()
    bar_hand(ctx, t)
    ctx.restore()
    g = cairo.LinearGradient(0, 0, 0, H)                             # fluorescent wash
    g.add_color_stop_rgba(0, 1, 1, 0.92, 0.08)
    g.add_color_stop_rgba(1, 0.2, 0.25, 0.1, 0.12)
    ctx.set_source(g)
    ctx.paint()


# ---------------------------------------------------------------- 4. the rose, on the closed logo

def petal(ctx, a, r0, r1, width):
    ctx.save()
    ctx.rotate(a)
    ctx.move_to(0, -r0)
    ctx.curve_to(width, -r0 - (r1 - r0) * 0.2, width * 1.1, -r1, 0, -r1)
    ctx.curve_to(-width * 1.1, -r1, -width, -r0 - (r1 - r0) * 0.2, 0, -r0)
    ctx.restore()


def heart(ctx, s):
    ctx.move_to(0, 0.95 * s)
    ctx.curve_to(-1.25 * s, 0.05 * s, -0.95 * s, -0.95 * s, 0, -0.42 * s)
    ctx.curve_to(0.95 * s, -0.95 * s, 1.25 * s, 0.05 * s, 0, 0.95 * s)
    ctx.close_path()


def rose(ctx, t):
    """The Luther rose, a part on each note of the closed logo."""
    cx, cy, R = 640, 268, 172
    ring, petals, hrt, tv = (back_out(span(t, s, s + 0.3)) for s in ROSE)
    ctx.save()
    ctx.translate(cx, cy)
    if ring > 0:
        g = cairo.RadialGradient(0, 0, 40, 0, 0, R * 1.9)             # a glow behind it
        g.add_color_stop_rgba(0, 1, 0.9, 0.6, 0.35 * min(1, ring))
        g.add_color_stop_rgba(1, 1, 0.9, 0.6, 0)
        ctx.set_source(g)
        ctx.arc(0, 0, R * 1.9, 0, TAU)
        ctx.fill()
        ctx.save()
        ctx.scale(ring, ring)
        ctx.arc(0, 0, R, 0, TAU)
        g = cairo.LinearGradient(0, -R, 0, R)
        g.add_color_stop_rgb(0, 1, 0.9, 0.55)
        g.add_color_stop_rgb(0.5, *GOLD)
        g.add_color_stop_rgb(1, 0.7, 0.5, 0.15)
        ctx.set_source(g)
        ctx.fill()
        ctx.arc(0, 0, R - 16, 0, TAU)
        g = cairo.RadialGradient(0, -30, 10, 0, 0, R)
        g.add_color_stop_rgb(0, 0.55, 0.78, 1.0)
        g.add_color_stop_rgb(1, *ROSE_BLUE)
        ctx.set_source(g)
        ctx.fill()
        ctx.arc(0, 0, R, 0, TAU)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(5)
        ctx.stroke()
        ctx.arc(0, 0, R - 16, 0, TAU)
        ctx.set_line_width(3)
        ctx.stroke()
        ctx.restore()
    if petals > 0:
        ctx.save()
        ctx.scale(petals, petals)
        ctx.rotate(0.6 * (1 - petals))
        for k in range(5):
            petal(ctx, k * TAU / 5, 30, 138, 74)
            ctx.set_source_rgb(0.99, 0.98, 0.96)
            ctx.fill_preserve()
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(4)
            ctx.stroke()
            petal(ctx, k * TAU / 5, 40, 120, 30)                      # a crease of shade down each
            ctx.set_source_rgba(0.75, 0.78, 0.9, 0.35)
            ctx.fill()
        for k in range(5):                                            # the sepals between, green
            ctx.save()
            ctx.rotate(k * TAU / 5 + TAU / 10)
            ctx.move_to(0, -120)
            ctx.line_to(9, -146)
            ctx.line_to(0, -158)
            ctx.line_to(-9, -146)
            ctx.close_path()
            ctx.set_source_rgb(0.2, 0.55, 0.25)
            ctx.fill()
            ctx.restore()
        ctx.restore()
    if hrt > 0:
        ctx.save()
        ctx.translate(0, 8)
        ctx.scale(hrt, hrt)
        heart(ctx, 86)
        g = cairo.LinearGradient(0, -80, 0, 80)
        g.add_color_stop_rgb(0, 0.95, 0.25, 0.25)
        g.add_color_stop_rgb(1, *HEART_RED)
        ctx.set_source(g)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(4)
        ctx.stroke()
        ctx.restore()
    if tv > 0:                                                       # the TV at its heart
        ctx.save()
        ctx.translate(0, 4)
        ctx.scale(tv, tv)
        ctx.rotate(0.15 * (1 - min(1, tv)))
        for side in (-1, 1):
            ctx.move_to(side * 6, -30)
            ctx.line_to(side * 24, -54)
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(4)
            ctx.stroke()
            ctx.arc(side * 24, -56, 5, 0, TAU)
            ctx.set_source_rgb(*PINK)
            ctx.fill()
        rounded_rect(ctx, -44, -32, 88, 64, 13)
        ctx.set_source_rgb(*TEAL)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(4)
        ctx.stroke()
        rounded_rect(ctx, -36, -24, 52, 48, 9)
        ctx.set_source_rgb(0.18, 0.38, 0.92)
        ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        font(ctx, 'URW Gothic', 40)
        text_path(ctx, 'V', -10, 14, align='center')
        ctx.fill()
        for k, colour in enumerate((YELLOW, PINK)):
            ctx.arc(30, -12 + k * 16, 5, 0, TAU)
            ctx.set_source_rgb(*colour)
            ctx.fill()
        ctx.restore()
        g_t = span(t, ROSE[3] + 0.1, ROSE[3] + 0.6)
        if 0 < g_t < 1:
            glint(ctx, 30, -30, 30 * math.sin(g_t * math.pi), 0.4)
    ctx.restore()


@lru_cache(maxsize=None)
def night_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, H)
    g.add_color_stop_rgb(0, 0.04, 0.05, 0.15)
    g.add_color_stop_rgb(1, 0.13, 0.16, 0.36)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(6)
    for _ in range(60):
        ctx.arc(rand.uniform(0, W), rand.uniform(0, 420), rand.uniform(0.5, 1.3), 0, TAU)
        ctx.set_source_rgba(1, 1, 1, rand.uniform(0.2, 0.7))
        ctx.fill()
    return surface


def marker_sign(ctx, t):
    """A sheet of printer paper, taped up: BARS DOWNSTAIRS, an arrow."""
    p = back_out(span(t, SIGN, SIGN + 0.28))
    if p <= 0:
        return
    ctx.save()
    ctx.translate(1120, 652)
    ctx.rotate(0.07)
    ctx.scale(0.85, 0.85)
    ctx.scale(p, p)
    ctx.rectangle(-120, -52, 240, 104)
    ctx.set_source_rgb(0.99, 0.99, 0.97)
    ctx.fill()
    for tx in (-100, 100):                                           # tape
        ctx.save()
        ctx.translate(tx, -52)
        ctx.rotate(-0.4 if tx < 0 else 0.4)
        ctx.rectangle(-20, -8, 40, 16)
        ctx.set_source_rgba(0.95, 0.9, 0.7, 0.75)
        ctx.fill()
        ctx.restore()
    ctx.set_source_rgb(0.1, 0.1, 0.12)
    font(ctx, 'Z003', 40, bold=False)
    text_path(ctx, 'Bars downstairs', 0, -4, align='center')
    ctx.fill()
    ctx.move_to(-40, 26)
    ctx.line_to(40, 26)
    ctx.line_to(40, 36)
    ctx.move_to(32, 28)
    ctx.line_to(40, 40)
    ctx.line_to(48, 28)
    ctx.set_line_width(4)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke()
    ctx.restore()


def seal(ctx, t):
    ctx.set_source_surface(night_surface(), 0, 0)
    ctx.paint()
    snowfall(ctx, t, 3, 130, 2.0, 40, alpha=0.75)
    rose(ctx, t)
    neighborhood.lockup(ctx, t, LOCKUP, 552, scale=0.6)
    p = span(t, *SUBTITLE)
    if p > 0:
        ctx.set_source_rgba(*CREAM, ease_out(p))
        font(ctx, 'C059', 22)
        text_path(ctx, 'EVANGELICAL LUTHERAN CHANNEL 19', 640, 616, tracking=5, align='center')
        ctx.fill()
    marker_sign(ctx, t)
    snowfall(ctx, t, 4, 20, 3.4, 60, alpha=0.8)


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    a, b, c = span(t, *TO_DOOR), span(t, *HALL), span(t, *SEAL_IN)
    if t < TO_DOOR[1]:
        exterior(ctx, t)
    if a > 0 and t < HALL[1]:
        ctx.push_group()
        door(ctx, t)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_in_out(a) if t < TO_DOOR[1] else 1.0)
    if b > 0 and t < SEAL_IN[1]:
        ctx.push_group()
        hall(ctx, t)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_in_out(b) if t < HALL[1] else 1.0)
    if c > 0:
        ctx.push_group()
        seal(ctx, t)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_in_out(c))
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.3)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
