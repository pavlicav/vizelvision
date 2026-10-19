"""Now With More God: a send-up of the old-school Sunday-football beer commercial (the
Wisconsin brewery's, with its church, its golden light and its slogan about God's Country),
played completely straight by a reverent baritone.

1. Golden hour over rolling farm country: a white clapboard church, its steeple topped
   with a football for a weathervane, and the letter board on the lawn: SUNDAY 1 PM
   SERMON: / WHY HAS THE O-LINE / FORSAKEN US. The bell in the belfry swings the open
   logo; the swallows take off.
2. Inside, down the aisle: the faithful in their Sunday best (a cheese wedge, a helmet, a
   foam finger), the station's TV at the heart of the rose window, a haloed referee in the
   stained glass, and on the hymn board the spread and the over/under. The pastor, in a
   referee-striped stole, throws a Hail Mary the length of the nave, and Doris, in a
   flowered hat in the back pew, pulls it in. The congregation is on its feet, arms up.
3. The label, as a brewery's would be: VizelVision in red script on cream, the blue
   ribbon SUNDAY FOOTBALL, Pure Broadcast in God's Country*, CHANNEL 19 . FULLY
   KRAEUSENED**, and the fine print: *GOD HAS NOT ENDORSED THIS CHANNEL. / **NOBODY KNOWS
   WHAT THIS MEANS. On the closed logo, with the choir and the organ.

Aired only during an NFL or college game (LEAGUES). The voice is Pluto, deadpan: "Some say
football... is a religion." / "Doris has never dropped one." / "Now with more God."
"""
import math
import random
from functools import lru_cache

import cairo

from common import (A, INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    font, glint, grain, inked, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'hail-mary'
NAME = 'Now With More God'
KIND = 'ident'
ORDER = 22
DESCRIPTION = ('Only during football, a send-up of the old beer ads: a country church, a sermon on the '
               'offensive line, the spread on the hymn board, a Hail Mary down the aisle caught by Doris, and a '
               'label whose fine print says God has not endorsed this channel. "Now with more God." Pluto.')
DURATION = 10.0
STILL_AT = 8.8
LEAGUES = ('nfl', 'ncaaf')
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
FADE_IN = (0.0, 0.5)
BELL = (1.0, 1.25, 1.5, 2.0)                     # the open logo: the bell swings
BIRDS = 1.0
INSIDE = (2.6, 3.0)                              # the dissolve inside
RAISE = (3.3, 3.8)                               # the pastor raises the ball...
WIND_UP = (3.9, 4.3)
THROW = 4.3                                      # ...and lets it go
FLIGHT = (4.3, 5.3)
CATCH = 5.3                                      # the church lady pulls it in
STAND = (5.32, 5.6)                              # everyone up
LABEL_IN = (6.55, 6.95)                          # the dissolve to the label
CLOSED = 7.0                                     # the closed logo
RIBBON = 7.25
TAGLINE = 7.5
FOOTER = 8.0
FINE_PRINT = 8.45
SHINE = 8.3
FADE = (9.35, 9.65)

# The exterior.
GROUND = 470
CHURCH = 520                                     # the facade's centre
SUN = (1040, 270)
# The nave: a camera in the back pew's aisle looking toward the altar.
FOCAL, EYE, HORIZON_Y = 620.0, 2.6, 200.0     # an usher's eye, standing at the back
FAR = 9.0                                        # the altar wall
NAVE = 4.2                                       # half its width
ROOF = 6.5
PEWS = (2.6, 3.2, 3.8, 4.4, 5.0, 5.6, 6.2, 6.8)  # distances of the pews
PULPIT = (0.0, 7.8)                              # the pastor (x, z), on the chancel step
LADY = (1.25, 2.6)                               # the church lady, back pew, by the aisle

GOLD = (1.0, 0.78, 0.38)
CREAM = (0.98, 0.94, 0.82)
RED = (0.78, 0.07, 0.12)
BLUE = (0.1, 0.2, 0.55)
WOOD = (0.45, 0.27, 0.13)
WHITEWASH = (0.97, 0.95, 0.9)


# ---------------------------------------------------------------- 1. the church in the country

def hills(ctx):
    sky = cairo.LinearGradient(0, 0, 0, GROUND + 40)
    sky.add_color_stop_rgb(0, 0.22, 0.32, 0.6)
    sky.add_color_stop_rgb(0.55, 0.98, 0.72, 0.5)
    sky.add_color_stop_rgb(1, 1.0, 0.86, 0.55)
    ctx.set_source(sky)
    ctx.paint()
    glow = cairo.RadialGradient(*SUN, 10, *SUN, 520)
    glow.add_color_stop_rgba(0, 1, 0.97, 0.8, 1)
    glow.add_color_stop_rgba(0.12, 1, 0.9, 0.6, 0.9)
    glow.add_color_stop_rgba(1, 1, 0.8, 0.5, 0)
    ctx.set_source(glow)
    ctx.paint()
    rand = random.Random(6)
    for k, (base, amp, colour) in enumerate(((GROUND - 50, 30, (0.55, 0.6, 0.55)), (GROUND - 10, 36, (0.47, 0.58, 0.33)),
                                             (GROUND + 40, 40, (0.55, 0.6, 0.25)))):
        ctx.move_to(0, H)
        phase = rand.uniform(0, TAU)
        for x in range(0, W + 41, 40):
            ctx.line_to(x, base - amp * math.sin(x / (260 - 50 * k) + phase) - 10 * math.sin(x / 90 + phase))
        ctx.line_to(W, H)
        ctx.close_path()
        g = cairo.LinearGradient(0, base - amp, 0, H)
        g.add_color_stop_rgb(0, *mix(colour, GOLD, 0.35))
        g.add_color_stop_rgb(1, *mix(colour, INK, 0.25))
        ctx.set_source(g)
        ctx.fill()
    ctx.set_source_rgba(0.35, 0.3, 0.1, 0.35)                     # rows in the far fields
    ctx.set_line_width(1.5)
    for k in range(14):
        ctx.move_to(700 + k * 40, GROUND - 6)
        ctx.line_to(640 + k * 70, GROUND + 60)
    ctx.stroke()
    barn(ctx, 900, GROUND - 22)
    for tx, ty, r in ((760, GROUND - 6, 42), (820, GROUND + 4, 34), (250, GROUND + 6, 46), (322, GROUND + 18, 30)):
        ctx.arc(tx, ty - r, r, 0, TAU)
        ctx.set_source_rgb(*mix((0.25, 0.4, 0.18), GOLD, 0.2))
        ctx.fill()
        ctx.rectangle(tx - 4, ty - 6, 8, 14)
        ctx.set_source_rgb(0.3, 0.2, 0.1)
        ctx.fill()


def barn(ctx, x, y):
    ctx.move_to(x - 40, y)
    ctx.line_to(x - 40, y - 34)
    ctx.line_to(x - 20, y - 52)
    ctx.line_to(x + 20, y - 52)
    ctx.line_to(x + 40, y - 34)
    ctx.line_to(x + 40, y)
    ctx.close_path()
    ctx.set_source_rgb(0.68, 0.16, 0.12)
    ctx.fill()
    rounded_rect(ctx, x + 48, y - 70, 20, 70, 9)                   # the silo
    ctx.set_source_rgb(0.75, 0.75, 0.72)
    ctx.fill()


@lru_cache(maxsize=None)
def countryside():
    """The hills and the church without its bell, its birds or its sign's letters: once."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    hills(ctx)
    cx = CHURCH
    ctx.move_to(cx + 100, 330)                                     # the side, going back
    ctx.line_to(cx + 250, 352)
    ctx.line_to(cx + 250, 548)
    ctx.line_to(cx + 100, 570)
    ctx.close_path()
    ctx.set_source_rgb(*mix(WHITEWASH, (0.55, 0.45, 0.4), 0.3))
    ctx.fill()
    ctx.move_to(cx + 100, 330)                                     # its roof
    ctx.line_to(cx, 248)
    ctx.line_to(cx + 140, 278)
    ctx.line_to(cx + 250, 352)
    ctx.close_path()
    ctx.set_source_rgb(0.32, 0.22, 0.2)
    ctx.fill()
    for k in range(3):                                             # side windows, lit
        wx = cx + 128 + k * 40
        rounded_rect(ctx, wx, 392 + k * 3, 20, 70 - k * 4, 10)
        ctx.set_source_rgb(1.0, 0.82, 0.45)
        ctx.fill()
    ctx.move_to(cx - 100, 570)                                     # the facade
    ctx.line_to(cx - 100, 330)
    ctx.line_to(cx, 248)
    ctx.line_to(cx + 100, 330)
    ctx.line_to(cx + 100, 570)
    ctx.close_path()
    g = cairo.LinearGradient(cx - 100, 0, cx + 100, 0)
    g.add_color_stop_rgb(0, *mix(WHITEWASH, (0.6, 0.55, 0.6), 0.25))
    g.add_color_stop_rgb(1, *mix(WHITEWASH, GOLD, 0.35))
    ctx.set_source(g)
    ctx.fill()
    ctx.set_source_rgba(0, 0, 0, 0.08)                             # clapboards
    for y in range(338, 570, 9):
        ctx.rectangle(cx - 100, y, 200, 1.5)
    ctx.fill()
    for wx in (cx - 74, cx + 46):                                  # facade windows
        ctx.move_to(wx, 470)
        ctx.line_to(wx, 400)
        ctx.arc(wx + 14, 400, 14, math.pi, 0)
        ctx.line_to(wx + 28, 470)
        ctx.close_path()
        ctx.set_source_rgb(1.0, 0.8, 0.42)
        ctx.fill()
    ctx.move_to(cx - 26, 570)                                      # the red doors
    ctx.line_to(cx - 26, 500)
    ctx.arc(cx, 500, 26, math.pi, 0)
    ctx.line_to(cx + 26, 570)
    ctx.close_path()
    ctx.set_source_rgb(0.62, 0.1, 0.1)
    ctx.fill()
    ctx.rectangle(cx - 1, 478, 2, 92)
    ctx.set_source_rgb(0.3, 0.05, 0.05)
    ctx.fill()
    ctx.rectangle(cx - 36, 570, 72, 8)                             # the step
    ctx.set_source_rgb(0.8, 0.78, 0.72)
    ctx.fill()
    ctx.rectangle(cx - 34, 150, 68, 140)                           # the tower
    ctx.set_source_rgb(*mix(WHITEWASH, GOLD, 0.2))
    ctx.fill()
    ctx.move_to(cx - 34, 150)                                      # its belfry's arch (dark)
    ctx.rectangle(cx - 22, 172, 44, 56)
    ctx.set_source_rgb(0.18, 0.12, 0.12)
    ctx.fill()
    ctx.move_to(cx - 42, 150)                                      # the spire
    ctx.line_to(cx, 54)
    ctx.line_to(cx + 42, 150)
    ctx.close_path()
    g = cairo.LinearGradient(cx - 42, 0, cx + 42, 0)
    g.add_color_stop_rgb(0, 0.82, 0.8, 0.78)
    g.add_color_stop_rgb(1, *mix(WHITEWASH, GOLD, 0.4))
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(cx - 1.5, 26, 3, 30)                             # the weathervane's rod
    ctx.set_source_rgb(0.3, 0.25, 0.2)
    ctx.fill()
    return surface


def weathervane(ctx, t):
    """A gilt football, turning a little in the breeze."""
    turn = math.sin(t * 1.3) * 0.5
    ctx.save()
    ctx.translate(CHURCH, 30)
    ctx.scale(math.cos(turn), 1)
    ctx.move_to(-20, 0)
    ctx.curve_to(-10, -11, 10, -11, 20, 0)
    ctx.curve_to(10, 11, -10, 11, -20, 0)
    ctx.close_path()
    ctx.set_source_rgb(*mix(GOLD, (0.8, 0.5, 0.1), 0.4))
    ctx.fill()
    ctx.move_to(-6, -2)
    ctx.line_to(6, -2)
    ctx.set_source_rgb(1, 0.95, 0.75)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.restore()


def bell(ctx, t):
    """In the belfry: the bell swinging one way, then the other, on each note."""
    swing = 0.0
    for k, when in enumerate(BELL):
        p = span(t, when - 0.12, when + 0.35)
        if 0 < p < 1:
            swing += (0.5 if k % 2 == 0 else -0.5) * math.sin(math.pi * p) * (1.3 if k == 3 else 1)
    ctx.save()
    ctx.translate(CHURCH, 176)
    ctx.rotate(swing)
    ctx.move_to(-14, 36)
    ctx.curve_to(-14, 10, -10, 4, 0, 4)
    ctx.curve_to(10, 4, 14, 10, 14, 36)
    ctx.line_to(18, 42)
    ctx.line_to(-18, 42)
    ctx.close_path()
    g = cairo.LinearGradient(-18, 0, 18, 0)
    g.add_color_stop_rgb(0, 0.55, 0.38, 0.12)
    g.add_color_stop_rgb(0.4, 0.98, 0.82, 0.45)
    g.add_color_stop_rgb(1, 0.5, 0.33, 0.1)
    ctx.set_source(g)
    ctx.fill()
    ctx.restore()


def sign(ctx, t):
    """The letter board on the lawn."""
    x, y, w, h = 52, 470, 336, 124
    for px in (x + 30, x + w - 40):
        ctx.rectangle(px, y + h, 10, 46)
        ctx.set_source_rgb(0.85, 0.83, 0.78)
        ctx.fill()
    rounded_rect(ctx, x - 8, y - 8, w + 16, h + 16, 6)
    ctx.set_source_rgb(*WHITEWASH)
    ctx.fill()
    ctx.rectangle(x, y, w, h)
    ctx.set_source_rgb(0.08, 0.08, 0.09)
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.07)
    for ly in range(y + 6, y + h, 10):
        ctx.rectangle(x, ly, w, 1)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 21)
    for k, line in enumerate(('SUNDAY 1 PM SERMON:', 'WHY HAS THE O-LINE', 'FORSAKEN US')):
        ctx.new_path()
        text_path(ctx, line, x + w / 2, y + 34 + k * 36, tracking=1.5, align='center')
        ctx.set_source_rgb(0.96, 0.96, 0.92)
        ctx.fill()


def birds(ctx, t):
    if t < BIRDS:
        return
    rand = random.Random(4)
    for k in range(7):
        p = (t - BIRDS - k * 0.06) * 0.9
        if p <= 0:
            continue
        x = CHURCH + rand.uniform(-20, 20) + 240 * p * rand.uniform(0.6, 1.3)
        y = 160 - 130 * p * rand.uniform(0.7, 1.2) + 18 * math.sin(p * 9 + k)
        flap = math.sin(t * 26 + k) * 5
        ctx.move_to(x - 9, y - flap)
        ctx.line_to(x, y)
        ctx.line_to(x + 9, y - flap)
        ctx.set_source_rgb(0.15, 0.1, 0.12)
        ctx.set_line_width(2.2)
        ctx.stroke()


def flare(ctx, t, strength=1.0):
    """The sun's flare across the lens: rings along the line through the centre."""
    sx, sy = SUN
    for k, (along, r, colour, a) in enumerate(((0.4, 34, (1, 0.8, 0.5), 0.18), (0.75, 18, (0.7, 1, 0.8), 0.15),
                                               (1.25, 56, (1, 0.6, 0.4), 0.12), (1.6, 24, (0.8, 0.8, 1), 0.14))):
        x = sx + (W / 2 - sx) * along * 2 + 6 * math.sin(t + k)
        y = sy + (H / 2 - sy) * along * 2
        g = cairo.RadialGradient(x, y, 0, x, y, r)
        g.add_color_stop_rgba(0, *colour, a * strength)
        g.add_color_stop_rgba(0.7, *colour, a * 0.6 * strength)
        g.add_color_stop_rgba(1, *colour, 0)
        ctx.set_source(g)
        ctx.arc(x, y, r, 0, TAU)
        ctx.fill()


def outside(ctx, t, frame):
    push = 1.0 + 0.07 * ease_in_out(span(t, 0.0, INSIDE[1]))
    ctx.save()
    ctx.translate(CHURCH, 300)
    ctx.scale(push, push)
    ctx.translate(-CHURCH, -300)
    ctx.set_source_surface(countryside(), 0, 0)
    ctx.paint()
    bell(ctx, t)
    weathervane(ctx, t)
    sign(ctx, t)
    birds(ctx, t)
    ctx.restore()
    flare(ctx, t)


# ---------------------------------------------------------------- 2. the nave

def project(x, y, z):
    """A point in the nave (metres: x across, y up from the floor, z away) on the screen."""
    return W / 2 + FOCAL * x / z, HORIZON_Y + FOCAL * (EYE - y) / z


def quad(ctx, points):
    ctx.move_to(*project(*points[0]))
    for p in points[1:]:
        ctx.line_to(*project(*p))
    ctx.close_path()


@lru_cache(maxsize=None)
def nave():
    """The walls, the windows, the ceiling's beams, the floor and the runner, the altar and
    the rose window: once."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.3, 0.22, 0.16)
    ctx.paint()
    near = 1.0
    quad(ctx, ((-NAVE, 0, near), (NAVE, 0, near), (NAVE, 0, FAR), (-NAVE, 0, FAR)))          # the floor
    ctx.set_source_rgb(0.42, 0.28, 0.16)
    ctx.fill()
    quad(ctx, ((-0.55, 0.001, near), (0.55, 0.001, near), (0.55, 0.001, FAR), (-0.55, 0.001, FAR)))   # the runner
    ctx.set_source_rgb(0.55, 0.08, 0.1)
    ctx.fill()
    for side in (-1, 1):                                                                       # the walls
        quad(ctx, ((side * NAVE, 0, near), (side * NAVE, 0, FAR), (side * NAVE, ROOF, FAR), (side * NAVE, ROOF, near)))
        g = cairo.LinearGradient(*project(side * NAVE, 3, near), *project(side * NAVE, 3, FAR))
        g.add_color_stop_rgb(0, *mix(WHITEWASH, (0.5, 0.42, 0.36), 0.45))
        g.add_color_stop_rgb(1, *mix(WHITEWASH, GOLD, 0.25))
        ctx.set_source(g)
        ctx.fill()
        for k, z in enumerate((2.2, 4.4, 6.6)):                                                # stained glass
            stained_window(ctx, side, z, k)
    quad(ctx, ((-NAVE, ROOF, near), (NAVE, ROOF, near), (NAVE, ROOF, FAR), (-NAVE, ROOF, FAR)))  # the ceiling
    ctx.set_source_rgb(0.36, 0.24, 0.15)
    ctx.fill()
    for z in (1.5, 2.6, 3.7, 4.8, 5.9, 7.0, 8.1):                                              # its beams
        quad(ctx, ((-NAVE, ROOF, z), (NAVE, ROOF, z), (NAVE, ROOF - 0.35, z), (-NAVE, ROOF - 0.35, z)))
        ctx.set_source_rgb(0.24, 0.15, 0.08)
        ctx.fill()
    quad(ctx, ((-NAVE, 0, FAR), (NAVE, 0, FAR), (NAVE, ROOF, FAR), (-NAVE, ROOF, FAR)))         # the altar wall
    ctx.set_source_rgb(*mix(WHITEWASH, GOLD, 0.3))
    ctx.fill()
    quad(ctx, ((-1.6, 0, FAR - 0.05), (1.6, 0, FAR - 0.05), (1.6, 0.35, FAR - 0.05), (-1.6, 0.35, FAR - 0.05)))
    ctx.set_source_rgb(0.5, 0.32, 0.18)                                                        # the chancel step
    ctx.fill()
    rose(ctx)
    hymn_board(ctx)
    quad(ctx, ((-1.0, 0.35, 8.6), (1.0, 0.35, 8.6), (1.0, 1.25, 8.6), (-1.0, 1.25, 8.6)))       # the altar
    ctx.set_source_rgb(*CREAM)
    ctx.fill()
    quad(ctx, ((-0.3, 0.5, 8.58), (0.3, 0.5, 8.58), (0.3, 1.25, 8.58), (-0.3, 1.25, 8.58)))     # its runner
    ctx.set_source_rgb(*RED)
    ctx.fill()
    return surface


def stained_window(ctx, side, z, k):
    """A tall arched window in the side wall: lead lines and jewel colours, an icon each."""
    x = side * NAVE
    bottom, top, depth = 1.8, 4.6, 0.9
    pts = [(x, bottom, z), (x, bottom, z + depth), (x, top, z + depth)]
    for a in range(1, 8):                                          # the arch
        u = a / 8
        pts.append((x, top + 0.45 * math.sin(math.pi * u), z + depth * (1 - u)))
    pts.append((x, top, z))
    quad(ctx, pts)
    path = ctx.copy_path()
    colours = ((0.15, 0.3, 0.75), (0.8, 0.15, 0.2), (0.95, 0.75, 0.2), (0.15, 0.6, 0.35), (0.6, 0.2, 0.65))
    ctx.save()
    ctx.clip()
    rand = random.Random(k * 7 + (side > 0))
    for row in range(8):                                           # the panes
        for col in range(2):
            y0 = bottom + row * (top + 0.45 - bottom) / 8
            quad(ctx, ((x, y0, z + col * depth / 2), (x, y0, z + (col + 1) * depth / 2),
                       (x, y0 + (top + 0.45 - bottom) / 8, z + (col + 1) * depth / 2),
                       (x, y0 + (top + 0.45 - bottom) / 8, z + col * depth / 2)))
            ctx.set_source_rgb(*mix(rand.choice(colours), WHITE, 0.25))
            ctx.fill_preserve()
            ctx.set_source_rgb(0.1, 0.08, 0.06)
            ctx.set_line_width(max(1.0, 9 / z))
            ctx.stroke()
    cx, cy = project(x, (bottom + top) / 2 - 0.2, z + depth / 2)   # the icon: a football, St. Referee, a TV
    s = 150 / z
    ctx.translate(cx, cy)
    ctx.scale(s * 0.45, s)
    if k == 0:
        ctx.move_to(-1, 0)
        ctx.curve_to(-0.5, -0.6, 0.5, -0.6, 1, 0)
        ctx.curve_to(0.5, 0.6, -0.5, 0.6, -1, 0)
        ctx.set_source_rgb(0.55, 0.28, 0.1)
    elif k == 2:
        rounded_rect(ctx, -0.8, -0.6, 1.6, 1.2, 0.25)
        ctx.set_source_rgb(0.1, 0.8, 0.75)
    else:                                                         # St. Referee: stripes and a halo
        ctx.save()
        ctx.scale(1 / 0.45, 1)
        ctx.arc(0, -0.95, 0.32, 0, TAU)
        ctx.set_source_rgb(1.0, 0.85, 0.2)
        ctx.set_line_width(0.1)
        ctx.stroke()
        ctx.arc(0, -0.62, 0.22, 0, TAU)
        ctx.set_source_rgb(0.95, 0.8, 0.65)
        ctx.fill()
        ctx.rectangle(-0.42, -0.4, 0.84, 1.1)
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
        for stripe in range(3):
            ctx.rectangle(-0.42 + 0.06 + stripe * 0.28, -0.4, 0.13, 1.1)
        ctx.set_source_rgb(0.05, 0.05, 0.05)
        ctx.fill()
        ctx.restore()
    ctx.restore()
    ctx.append_path(path)
    ctx.set_source_rgb(0.18, 0.12, 0.08)
    ctx.set_line_width(max(2.0, 30 / z))
    ctx.stroke()


def rose(ctx):
    """The round window over the altar, with the emblem at its heart."""
    cx, cy = project(0, 3.9, FAR - 0.01)
    r = FOCAL * 1.25 / FAR
    for k in range(12):
        a0 = k * TAU / 12
        ctx.move_to(cx, cy)
        ctx.arc(cx, cy, r, a0, a0 + TAU / 12)
        ctx.close_path()
        ctx.set_source_rgb(*((0.15, 0.3, 0.8), (0.85, 0.2, 0.3), (0.95, 0.8, 0.25))[k % 3])
        ctx.fill()
    ctx.set_source_rgb(0.15, 0.1, 0.08)
    ctx.set_line_width(3)
    for k in range(12):
        a = k * TAU / 12
        ctx.move_to(cx, cy)
        ctx.line_to(cx + r * math.cos(a), cy + r * math.sin(a))
    ctx.stroke()
    ctx.arc(cx, cy, r, 0, TAU)
    ctx.set_line_width(6)
    ctx.stroke()
    ctx.arc(cx, cy, r * 0.5, 0, TAU)
    ctx.set_source_rgb(0.95, 0.9, 0.7)
    ctx.fill()
    ctx.save()
    ctx.translate(cx, cy + 4)
    ctx.scale(r / 330, r / 330)
    A.draw_tv(ctx, 0.0, 1, 0.0)
    ctx.restore()


def hymn_board(ctx):
    """On the altar wall, left: the hymn board, with today's numbers: the spread, the total."""
    x0, y0 = project(-3.45, 3.2, FAR - 0.02)
    x1, y1 = project(-2.0, 1.6, FAR - 0.02)
    rounded_rect(ctx, x0, y0, x1 - x0, y1 - y0, 4)
    ctx.set_source_rgb(0.32, 0.2, 0.1)
    ctx.fill()
    font(ctx, 'C059', (y1 - y0) / 9)
    ctx.new_path()
    text_path(ctx, 'HYMNS', (x0 + x1) / 2, y0 + (y1 - y0) * 0.2, tracking=2, align='center')
    ctx.set_source_rgb(*mix(CREAM, GOLD, 0.5))
    ctx.fill()
    font(ctx, 'C059', (y1 - y0) / 5.2)
    for k, number in enumerate(('-3.5', 'O/U 44')):
        ctx.new_path()
        text_path(ctx, number, (x0 + x1) / 2, y0 + (y1 - y0) * (0.52 + 0.3 * k), align='center')
        ctx.set_source_rgb(*CREAM)
        ctx.fill()


# The faithful: what each seat has on its head. (A hat for every few.)
HATS = ('hair', 'hair', 'cap', 'hair', 'wedge', 'hair', 'helmet', 'hair', 'bald', 'hair', 'finger', 'bun')
HAIR = ((0.25, 0.16, 0.08), (0.1, 0.08, 0.06), (0.75, 0.6, 0.35), (0.6, 0.6, 0.62), (0.45, 0.2, 0.1))


def people_up(t):
    return ease_out(span(t, *STAND))


def person(ctx, x, z, kind, hair, t, seed):
    """Someone in a pew, from behind: shoulders, a head and whatever is on it; up on their
    feet, arms high, once the ball is caught."""
    up = people_up(t)
    bounce = abs(math.sin((t - STAND[0]) * 9 + seed)) * 0.06 if t > STAND[1] else 0.0
    y = 1.0 + 0.45 * up + bounce
    look = 0.0
    if FLIGHT[0] <= t < CATCH + 0.3:                                  # heads tip up after the ball
        look = 0.05 * math.sin(math.pi * span(t, FLIGHT[0], CATCH + 0.3))
    sx, sy = project(x, y, z)
    s = FOCAL / z
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(s, s)
    jacket = ((0.2, 0.25, 0.45), (0.45, 0.15, 0.15), (0.3, 0.3, 0.32), (0.15, 0.35, 0.25), (0.5, 0.42, 0.3))[seed % 5]
    if up > 0.05:                                                     # arms up
        for side in (-1, 1):
            ctx.move_to(side * 0.17, 0.05)
            ctx.line_to(side * (0.17 + 0.08 * up), 0.05 - 0.5 * up)
            ctx.set_source_rgb(*jacket)
            ctx.set_line_width(0.075)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.stroke()
            ctx.arc(side * (0.17 + 0.08 * up), 0.05 - 0.5 * up, 0.045, 0, TAU)
            ctx.set_source_rgb(0.95, 0.78, 0.65)
            ctx.fill()
    ctx.save()
    ctx.scale(0.24, 0.13)
    ctx.arc(0, 0.9, 1, math.pi, 0)                                    # the shoulders
    ctx.restore()
    ctx.set_source_rgb(*jacket)
    ctx.fill()
    hy = -0.13 - look
    ctx.arc(0, hy, 0.11, 0, TAU)
    ctx.set_source_rgb(*(hair if kind not in ('bald',) else (0.93, 0.72, 0.6)))
    ctx.fill()
    if kind == 'cap':
        ctx.arc(0, hy - 0.02, 0.115, math.pi, 0)
        ctx.set_source_rgb(0.15, 0.3, 0.7)
        ctx.fill()
    elif kind == 'wedge':                                             # a cheese wedge
        ctx.move_to(-0.17, hy - 0.04)
        ctx.line_to(0.17, hy - 0.04)
        ctx.line_to(0.0, hy - 0.22)
        ctx.close_path()
        ctx.set_source_rgb(1.0, 0.8, 0.15)
        ctx.fill()
        for hx, hh in ((-0.06, -0.09), (0.05, -0.12)):
            ctx.arc(hx, hy + hh, 0.018, 0, TAU)
            ctx.set_source_rgb(0.85, 0.62, 0.1)
            ctx.fill()
    elif kind == 'helmet':
        ctx.arc(0, hy, 0.13, 0, TAU)
        ctx.set_source_rgb(0.1, 0.25, 0.55)
        ctx.fill()
        ctx.rectangle(-0.018, hy - 0.13, 0.036, 0.24)
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
    elif kind == 'finger':                                            # a foam finger, held up
        rounded_rect(ctx, 0.12, hy - 0.2 - 0.3 * up, 0.13, 0.14, 0.03)
        ctx.set_source_rgb(1.0, 0.25, 0.55)
        ctx.fill()
        rounded_rect(ctx, 0.16, hy - 0.33 - 0.3 * up, 0.05, 0.15, 0.02)
        ctx.fill()
    elif kind == 'bun':
        ctx.arc(0, hy - 0.1, 0.05, 0, TAU)
        ctx.set_source_rgb(*hair)
        ctx.fill()
    ctx.restore()


def pew(ctx, z):
    for side in (-1, 1):
        x0, x1 = side * 0.75, side * 3.9
        quad(ctx, ((x0, 0.0, z + 0.05), (x1, 0.0, z + 0.05), (x1, 0.95, z + 0.05), (x0, 0.95, z + 0.05)))
        ctx.set_source_rgb(*mix(WOOD, GOLD, 0.15))
        ctx.fill()
        quad(ctx, ((x0, 0.95, z + 0.05), (x1, 0.95, z + 0.05), (x1, 0.9, z), (x0, 0.9, z)))
        ctx.set_source_rgb(*mix(WOOD, WHITE, 0.25))
        ctx.fill()
        sx, sy0 = project(x0, 0.0, z + 0.05)                          # the pew end, by the aisle
        _, sy1 = project(x0, 1.1, z + 0.05)
        ctx.rectangle(sx - side * 0.06 * FOCAL / z, sy1, side * 0.06 * FOCAL / z, sy0 - sy1)
        ctx.set_source_rgb(*mix(WOOD, INK, 0.2))
        ctx.fill()


def congregation(ctx, t):
    """Pews and people, far to near (the back pew is the lady's: drawn by lady())."""
    rand = random.Random(12)
    for row, z in enumerate(reversed(PEWS)):
        seats = []
        for side in (-1, 1):
            for k in range(5):
                if rand.random() < 0.82:
                    seats.append(side * (1.15 + k * 0.62))
        for x in seats:
            if z == PEWS[0] and abs(x - LADY[0]) < 0.3:
                continue
            seed = rand.randrange(1000)
            person(ctx, x, z + 0.35, HATS[seed % len(HATS)], HAIR[seed % len(HAIR)], t, seed)
        pew(ctx, z)


def pastor(ctx, t):
    """In white, the striped stole round his neck: raises the ball, winds up, throws, and
    signals the touchdown."""
    x, z = PULPIT
    sx, sy = project(x, 1.45, z)
    s = FOCAL / z * 1.5                                               # drawn large: he's the star
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(s, s)
    ctx.move_to(-0.32, 0.55)                                          # the robe
    ctx.line_to(-0.2, -0.3)
    ctx.line_to(0.2, -0.3)
    ctx.line_to(0.32, 0.55)
    ctx.close_path()
    ctx.set_source_rgb(*WHITEWASH)
    ctx.fill()
    for side in (-1, 1):                                              # the stole, a referee's stripes
        for k in range(6):
            ctx.rectangle(side * 0.1 - 0.035, -0.3 + k * 0.12, 0.07, 0.06)
        ctx.set_source_rgb(0.08, 0.08, 0.08)
        ctx.fill()
    ctx.arc(0, -0.42, 0.11, 0, TAU)                                   # the head
    ctx.set_source_rgb(0.92, 0.75, 0.62)
    ctx.fill()
    ctx.arc(0, -0.47, 0.11, math.pi, 0)
    ctx.set_source_rgb(0.75, 0.75, 0.78)
    ctx.fill()
    raise_ = ease_out(span(t, *RAISE))
    wind = ease_in_out(span(t, *WIND_UP))
    follow = ease_out(span(t, THROW, THROW + 0.25))
    td = ease_out(span(t, STAND[0], STAND[1]))
    # Each arm's angle from hanging straight down (0) to straight up (pi), outward.
    right = 0.3 + (math.pi - 0.7) * raise_ + 0.5 * wind - (math.pi - 0.2) * follow
    right = right * (1 - td) + (math.pi - 0.15) * td
    left = 0.25 + 0.6 * raise_ * (1 - follow)
    left = left * (1 - td) + (math.pi - 0.15) * td
    for side, angle in ((1, right), (-1, left)):
        ax, ay = side * 0.2, -0.26
        hx, hy = ax + side * math.sin(angle) * 0.42, ay + math.cos(angle) * 0.42
        ctx.move_to(ax, ay)
        ctx.line_to(hx, hy)
        ctx.set_source_rgb(*WHITEWASH)
        ctx.set_line_width(0.1)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
        if side > 0 and t < THROW:                                   # the ball, in hand
            ctx.save()
            ctx.translate(hx, hy - 0.04)
            ctx.rotate(-0.5)
            ctx.scale(0.13, 0.08)
            ctx.arc(0, 0, 1, 0, TAU)
            ctx.restore()
            ctx.set_source_rgb(0.55, 0.28, 0.12)
            ctx.fill()
    ctx.restore()


def the_ball(ctx, t):
    """The Hail Mary: from the pastor's hand, high under the beams, down into the lady's."""
    if not FLIGHT[0] <= t < CATCH + 0.02:
        return
    p = span(t, *FLIGHT)
    z = PULPIT[1] + (LADY[1] + 0.2 - PULPIT[1]) * p
    x = 0.25 + (LADY[0] - 0.25) * p ** 2
    y = 2.0 + (1.9 - 2.0) * p + 1.9 * math.sin(math.pi * p)
    sx, sy = project(x, y, z)
    s = FOCAL / z
    ctx.save()
    ctx.translate(sx, sy)
    ctx.rotate(-0.5 + 0.4 * p)
    ctx.scale(s * 0.22, s * 0.13)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    g = cairo.LinearGradient(sx, sy - s * 0.13, sx, sy + s * 0.13)
    g.add_color_stop_rgb(0, 0.75, 0.42, 0.2)
    g.add_color_stop_rgb(1, 0.4, 0.18, 0.06)
    ctx.set_source(g)
    ctx.fill()
    spin = math.sin(t * 40) * s * 0.03                                # the laces, spinning past
    ctx.move_to(sx - s * 0.07, sy - s * 0.03 + spin)
    ctx.line_to(sx + s * 0.07, sy - s * 0.03 + spin)
    ctx.set_source_rgb(*WHITE)
    ctx.set_line_width(max(1.0, s * 0.012))
    ctx.stroke()


def lady(ctx, t):
    """The church lady, back pew by the aisle: a flowered hat; her hands come up and pull
    the ball in."""
    x, z = LADY
    up = people_up(t)
    reach = ease_out(span(t, CATCH - 0.35, CATCH - 0.05))
    sx, sy = project(x, 1.02 + 0.3 * up, z + 0.35)
    s = FOCAL / (z + 0.35)
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(s, s)
    hx, hy = -0.02 - 0.03 * reach, -0.55 * reach - 0.5 * up * (1 - reach)
    for side in (-1, 1):                                              # her arms, up for it
        ctx.move_to(side * 0.17, 0.05)
        ctx.line_to(hx + side * 0.08, 0.05 + (hy - 0.05) * max(reach, up))
        ctx.set_source_rgb(0.55, 0.25, 0.55)
        ctx.set_line_width(0.08)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    if t >= CATCH:                                                    # the ball, hers
        ctx.save()
        ctx.translate(hx, 0.05 + (hy - 0.05) * max(reach, up) - 0.06)
        ctx.rotate(-0.2)
        ctx.scale(0.15, 0.09)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(0.55, 0.28, 0.12)
        ctx.fill()
    ctx.save()
    ctx.scale(0.25, 0.14)
    ctx.arc(0, 0.9, 1, math.pi, 0)
    ctx.restore()
    ctx.set_source_rgb(0.55, 0.25, 0.55)
    ctx.fill()
    ctx.arc(0, -0.13, 0.11, 0, TAU)
    ctx.set_source_rgb(0.85, 0.85, 0.88)
    ctx.fill()
    ctx.save()                                                        # the hat: a wide brim, flowers
    ctx.translate(0, -0.2 - 0.06 * pulse(t, CATCH, 0.3))
    ctx.rotate(-0.08 + 0.1 * pulse(t, CATCH, 0.4))
    ctx.save()
    ctx.scale(0.3, 0.07)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.95, 0.8, 0.85)
    ctx.fill()
    ctx.arc(0, -0.04, 0.13, math.pi, 0)
    ctx.fill()
    for k, colour in enumerate(((1.0, 0.3, 0.45), (1.0, 0.85, 0.2), (0.6, 0.3, 0.9), (1.0, 0.5, 0.2))):
        ctx.arc(-0.12 + k * 0.075, -0.07 - 0.03 * math.sin(k * 2), 0.04, 0, TAU)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    ctx.restore()
    ctx.restore()


def light_beams(ctx, t):
    """Sun through the left-hand windows, slanting down across the nave, dust in it."""
    for k, z in enumerate((2.2, 4.4, 6.6)):
        top0 = project(-NAVE, 4.6, z)
        top1 = project(-NAVE, 4.6, z + 0.9)
        bottom0 = project(1.5, 0.0, z + 1.6)
        bottom1 = project(1.5, 0.0, z + 2.5)
        ctx.move_to(*top0)
        ctx.line_to(*top1)
        ctx.line_to(*bottom1)
        ctx.line_to(*bottom0)
        ctx.close_path()
        g = cairo.LinearGradient(*top0, *bottom0)
        g.add_color_stop_rgba(0, 1, 0.92, 0.7, 0.22)
        g.add_color_stop_rgba(1, 1, 0.92, 0.7, 0.0)
        ctx.set_source(g)
        ctx.fill()


def inside(ctx, t, frame):
    ctx.set_source_surface(nave(), 0, 0)
    ctx.paint()
    pastor(ctx, t)
    congregation(ctx, t)
    the_ball(ctx, t)
    lady(ctx, t)
    light_beams(ctx, t)
    if CATCH <= t < CATCH + 0.6:                                      # a burst of light on the catch
        x, y = project(LADY[0], 1.7, LADY[1] + 0.35)
        glint(ctx, x, y, 40 * math.sin(math.pi * span(t, CATCH, CATCH + 0.6)), t * 2, 1)


# ---------------------------------------------------------------- 3. the label

@lru_cache(maxsize=None)
def script_path():
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8))
    ctx.select_font_face('Z003', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(150)
    ext = ctx.text_extents('VizelVision')
    ctx.move_to(-ext.x_advance / 2, 0)
    ctx.text_path('VizelVision')
    return ctx.copy_path(), ext.x_advance


def label(ctx, t):
    """The cream label with its scalloped edge: the ribbon, the script, the slogan."""
    k = back_out(span(t, LABEL_IN[0] + 0.1, CLOSED + 0.2), 1.6)
    if k <= 0:
        return
    ctx.save()
    ctx.translate(W / 2, H / 2 + 4)
    ctx.scale(k, k)
    rx, ry = 470, 250
    ctx.save()                                                       # the scalloped edge
    ctx.scale(rx + 24, ry + 24)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*mix(GOLD, (0.6, 0.4, 0.1), 0.3))
    ctx.fill()
    for i in range(72):
        a = i * TAU / 72
        ctx.arc((rx + 24) * math.cos(a), (ry + 24) * math.sin(a), 13, 0, TAU)
        ctx.close_path()
    ctx.fill()
    ctx.save()
    ctx.scale(rx, ry)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    g = cairo.RadialGradient(-80, -80, 40, 0, 0, rx)
    g.add_color_stop_rgb(0, 1.0, 0.98, 0.9)
    g.add_color_stop_rgb(1, *mix(CREAM, GOLD, 0.35))
    ctx.set_source(g)
    ctx.fill()
    ctx.save()
    ctx.scale(rx - 16, ry - 16)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*RED)
    ctx.set_line_width(3)
    ctx.stroke()
    # The script, written in left to right.
    path, width = script_path()
    p = ease_in_out(span(t, CLOSED, CLOSED + 0.6))
    ctx.save()
    ctx.rectangle(-width / 2 - 20, -200, (width + 40) * p, 300)
    ctx.clip()
    ctx.save()
    ctx.translate(6, 26)
    ctx.append_path(path)
    ctx.set_source_rgba(*BLUE, 0.85)
    ctx.set_line_width(10)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke_preserve()
    ctx.fill()
    ctx.restore()
    ctx.translate(0, 20)
    ctx.append_path(path)
    ctx.set_source_rgb(*RED)
    ctx.set_line_width(7)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.stroke_preserve()
    ctx.fill()
    ctx.restore()
    # The blue ribbon, unfurling across the top.
    q = ease_out(span(t, RIBBON, RIBBON + 0.4))
    if q > 0:
        ctx.save()
        ctx.rectangle(-300 * q - 60, -260, 600 * q + 120, 140)
        ctx.clip()
        for side in (-1, 1):                                         # the tails
            ctx.move_to(side * 250, -176)
            ctx.line_to(side * 320, -176)
            ctx.line_to(side * 296, -150)
            ctx.line_to(side * 320, -124)
            ctx.line_to(side * 250, -124)
            ctx.close_path()
            ctx.set_source_rgb(*mix(BLUE, INK, 0.35))
            ctx.fill()
        ctx.move_to(-270, -190)
        ctx.curve_to(-100, -214, 100, -214, 270, -190)
        ctx.line_to(270, -138)
        ctx.curve_to(100, -162, -100, -162, -270, -138)
        ctx.close_path()
        ctx.set_source_rgb(*BLUE)
        ctx.fill_preserve()
        ctx.set_source_rgb(*GOLD)
        ctx.set_line_width(3)
        ctx.stroke()
        font(ctx, 'C059', 30)
        ctx.new_path()
        text_path(ctx, 'SUNDAY FOOTBALL', 0, -162, tracking=6, align='center')
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
        ctx.restore()
    # The slogan and the footer.
    r = ease_out(span(t, TAGLINE, TAGLINE + 0.5))
    if r > 0:
        ctx.select_font_face('C059', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(30)
        ctx.new_path()
        text_path(ctx, "Pure Broadcast in God's Country*", 0, 108, tracking=1, align='center')
        ctx.set_source_rgba(*BLUE, r)
        ctx.fill()
    f = ease_out(span(t, FOOTER, FOOTER + 0.4))
    if f > 0:
        font(ctx, 'C059', 17)
        ctx.new_path()
        text_path(ctx, 'CHANNEL 19   •   FULLY KRAEUSENED**', 0, 152, tracking=5, align='center')
        ctx.set_source_rgba(*RED, f)
        ctx.fill()
        for side in (-1, 1):
            A.star(ctx, side * 306, 146, 9, 0.0, 0.42)
            ctx.set_source_rgba(*RED, f)
            ctx.fill()
    fine = ease_out(span(t, FINE_PRINT, FINE_PRINT + 0.3))           # the fine print, as ads have it
    if fine > 0:
        font(ctx, 'C059', 11.5, bold=False)
        for k, line in enumerate(('*GOD HAS NOT ENDORSED THIS CHANNEL.', '**NOBODY KNOWS WHAT THIS MEANS.')):
            ctx.new_path()
            text_path(ctx, line, 0, 182 + 16 * k, tracking=1.5, align='center')
            ctx.set_source_rgba(*mix(BLUE, INK, 0.3), 0.85 * fine)
            ctx.fill()
    ctx.restore()
    s = span(t, SHINE, SHINE + 0.7)                                  # a shine across it
    if 0 < s < 1:
        x = W / 2 - 520 + 1040 * ease_in_out(s)
        g = cairo.LinearGradient(x - 90, 0, x + 90, 0)
        g.add_color_stop_rgba(0, 1, 1, 1, 0)
        g.add_color_stop_rgba(0.5, 1, 1, 1, 0.35)
        g.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.save()
        ctx.translate(W / 2, H / 2 + 4)
        ctx.scale(rx, ry)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source(g)
        ctx.fill()


def card(ctx, t, frame):
    """The label over the country, gone to dusk and soft."""
    ctx.set_source_surface(countryside(), 0, 0)
    ctx.paint()
    ctx.set_source_rgba(0.35, 0.12, 0.05, 0.45)
    ctx.paint()
    g = cairo.RadialGradient(W / 2, H / 2, 60, W / 2, H / 2, 760)
    g.add_color_stop_rgba(0, 1, 0.85, 0.5, 0.55)
    g.add_color_stop_rgba(1, 1, 0.6, 0.3, 0.0)
    ctx.set_source(g)
    ctx.paint()
    ctx.save()                                                       # slow rays behind the label
    ctx.translate(W / 2, H / 2)
    ctx.rotate(t * 0.08)
    for i in range(18):
        a = i * TAU / 18
        ctx.move_to(0, 0)
        ctx.arc(0, 0, 900, a, a + TAU / 36)
        ctx.close_path()
    ctx.set_source_rgba(1, 0.9, 0.6, 0.12)
    ctx.fill()
    ctx.restore()
    label(ctx, t)
    flare(ctx, t, 0.6)


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    a = span(t, *INSIDE)
    b = span(t, *LABEL_IN)
    if t < INSIDE[1]:
        outside(ctx, t, frame)
    if a > 0 and t < LABEL_IN[1]:
        ctx.push_group()
        inside(ctx, t, frame)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_in_out(a) if t < INSIDE[1] else 1.0)
    if b > 0:
        ctx.push_group()
        card(ctx, t, frame)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_in_out(b))
    warm = cairo.LinearGradient(0, 0, 0, H)                          # the commercial's golden grade
    warm.add_color_stop_rgba(0, 1, 0.75, 0.4, 0.08)
    warm.add_color_stop_rgba(1, 0.5, 0.2, 0.05, 0.12)
    ctx.set_source(warm)
    ctx.paint()
    vignette(ctx, 0.55)
    grain(ctx, frame, 0.55)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
