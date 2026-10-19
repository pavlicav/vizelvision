"""The VizelVision Forecast: a nineties local-news weather map of the Washington area,
the Potomac winding down to the Bay, the Beltway round the city. The weather pops onto it
on the notes of the open logo: a sun in sunglasses over Frederick, a cloud over
Baltimore, a cloud over Annapolis, and on the fourth note the temperature in Dupont
Circle (master's live text: the reading and its place). "Scattered sports": the Annapolis
cloud rains baseballs and footballs. "...with a hundred percent chance": the Doppler sweeps
round from the city and paints a storm the shape of the emblem's V, green to red at its
heart, 100%. On the closed logo, the extended forecast, a tile a note: TODAY, TONIGHT,
TOMORROW and FOREVER, each a little TV at 19 degrees.

The forecaster is Asteria: "Here's your Vizzle Vision forecast." / "Scattered sports...
with a hundred percent chance of Vizzle Vision."
"""
import math
import random
from functools import lru_cache

import cairo

from common import (A, CYAN, INK, ORANGE, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, chrome, ease_in,  # noqa: F401
                    ease_in_out, ease_out, font, glint, grain, inked, mix, pulse, rounded_rect, scanlines, span,
                    text_path, vignette)

ID = 'forecast'
NAME = 'The VizelVision Forecast'
KIND = 'ident'
ORDER = 26
DESCRIPTION = ('A nineties weather map: a sun in sunglasses, clouds, scattered sports raining on Annapolis, the '
               'temperature now in the corner of the city, and a 100% chance of VizelVision on the Doppler. The '
               'extended forecast: TODAY, TONIGHT, TOMORROW, FOREVER. Asteria.')
DURATION = 10.0
STILL_AT = 8.6

# Hit points (the music's too: promos/music.py).
FADE_IN = (0.0, 0.3)
TITLE = (0.15, 0.6)
ICONS = (1.0, 1.25, 1.5, 2.0)                    # the open logo: sun, cloud, cloud, the temperature
RAIN = (3.0, 5.4)                                # "Scattered sports"
SWEEP = (4.9, 6.7)                               # the Doppler, one and a half turns
HUNDRED = 6.2                                    # 100%
TILES = (7.0, 7.25, 7.5, 8.0)                    # the closed logo: the extended forecast, a tile a note
FADE = (9.3, 9.6)

CITY = (610, 330)                                # Washington, under the star
TEMP_BOX = (790, 262, 230, 92)                   # right of the storm, east of the city
PLACE_BOX = (796, 354, 300, 30)
SPOTS = {'sun': (330, 215), 'cloud': (780, 160), 'sports': (985, 450)}
LAND = (0.36, 0.55, 0.3)
WATER = (0.16, 0.36, 0.72)
NAVY = (0.03, 0.06, 0.22)
RADAR = ((0.1, 0.85, 0.2), (0.95, 0.9, 0.1), (1.0, 0.45, 0.05), (0.95, 0.1, 0.15))
TILE_NAMES = ('TODAY', 'TONIGHT', 'TOMORROW', 'FOREVER')

OVERLAYS = [
    {'field': 'temperature', 'box': list(TEMP_BOX), 'from': ICONS[3], 'to': FADE[1],
     'style': {'font': 'Nimbus Sans', 'bold': True, 'size': 84, 'min_size': 40, 'color': [1.0, 1.0, 1.0],
               'outline': [0.02, 0.05, 0.25], 'outline_width': 5, 'shadow': [4, 4, 0.0, 0.0, 0.1, 0.8]},
     'enter': {'kind': 'pop', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
    {'field': 'place', 'box': list(PLACE_BOX), 'from': ICONS[3] + 0.2, 'to': FADE[1],
     'style': {'font': 'Nimbus Sans', 'bold': True, 'size': 24, 'min_size': 13, 'color': [1.0, 0.92, 0.4],
               'upper': True, 'tracking': 0.06, 'shadow': [2, 2, 0.0, 0.0, 0.1, 0.8]},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': FADE[1] - FADE[0]}},
]


# ---------------------------------------------------------------- the map

@lru_cache(maxsize=None)
def basemap():
    """Land, the Bay, the Potomac, the Beltway and the towns: drawn once."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, W, H)
    g.add_color_stop_rgb(0, *mix(LAND, WHITE, 0.08))
    g.add_color_stop_rgb(1, *mix(LAND, INK, 0.2))
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(3)
    for _ in range(40):                                        # relief: soft hills to the west
        x, y, r = rand.uniform(0, 520), rand.uniform(80, H), rand.uniform(40, 120)
        hill = cairo.RadialGradient(x - r * 0.3, y - r * 0.3, 0, x, y, r)
        hill.add_color_stop_rgba(0, 1, 1, 0.8, 0.12)
        hill.add_color_stop_rgba(1, 0, 0, 0, 0)
        ctx.set_source(hill)
        ctx.paint()
    ctx.move_to(1040, -10)                                     # the Chesapeake Bay
    ctx.curve_to(1010, 140, 1080, 260, 1020, 380)
    ctx.curve_to(980, 470, 1060, 600, 1030, H + 10)
    ctx.line_to(W + 10, H + 10)
    ctx.line_to(W + 10, -10)
    ctx.close_path()
    ctx.set_source_rgb(*WATER)
    ctx.fill_preserve()
    ctx.set_source_rgba(1, 1, 1, 0.6)
    ctx.set_line_width(3)
    ctx.stroke()
    river = ((-20, 150), (120, 190), (230, 160), (330, 230), (440, 250), (520, 300), (585, 345), (600, 420),
             (650, 470), (700, 560), (820, 640), (960, 670), (1040, 700))
    for width, colour in ((14, (1, 1, 1)), (9, WATER)):          # the Potomac, widening
        for k, (a, b) in enumerate(zip(river, river[1:])):
            ctx.move_to(*a)
            ctx.line_to(*b)
            ctx.set_line_width(width * (1 + 1.6 * k / len(river)))
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_source_rgb(*colour)
            ctx.stroke()
    ctx.save()                                                 # the Beltway
    ctx.translate(*CITY)
    ctx.scale(1.15, 1)
    ctx.arc(0, 8, 118, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(1, 0.95, 0.85, 0.75)
    ctx.set_line_width(5)
    ctx.set_dash([18, 8])
    ctx.stroke()
    ctx.set_dash([])
    for name, x, y in (('FREDERICK', 110, 112), ('BALTIMORE', 880, 120), ('ANNAPOLIS', 960, 380),
                       ('BETHESDA', 470, 250), ('ARLINGTON', 455, 400), ('ALEXANDRIA', 560, 520),
                       ('SILVER SPRING', 690, 225)):
        ctx.arc(x, y, 6, 0, TAU)
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
        font(ctx, 'Nimbus Sans', 17)
        ctx.new_path()
        text_path(ctx, name, x + 12, y + 6, tracking=1.5)
        ctx.set_source_rgba(0, 0, 0, 0.55)
        ctx.set_line_width(4)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
    return surface


def city_star(ctx, t):
    k = back_out(span(t, ICONS[3] - 0.1, ICONS[3] + 0.2), 2.6)
    if k <= 0:
        return
    ctx.save()
    ctx.translate(*CITY)
    ctx.scale(k, k)
    A.star(ctx, 0, 0, 24, 0.0, 0.42)
    inked(ctx, (0.95, 0.15, 0.2), 4, (3, 3))
    ctx.restore()


# ---------------------------------------------------------------- the weather

def sun(ctx, t):
    k = back_out(span(t, ICONS[0], ICONS[0] + 0.3), 2.4)
    if k <= 0:
        return
    x, y = SPOTS['sun']
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(k, k)
    ctx.save()
    ctx.rotate(t * 0.6)
    for i in range(12):
        ctx.rotate(TAU / 12)
        ctx.move_to(-10, -62)
        ctx.line_to(0, -92)
        ctx.line_to(10, -62)
        ctx.close_path()
    inked(ctx, ORANGE, 4, (3, 3))
    ctx.restore()
    ctx.arc(0, 0, 60, 0, TAU)
    g = cairo.RadialGradient(-18, -18, 4, 0, 0, 64)
    g.add_color_stop_rgb(0, 1, 1, 0.7)
    g.add_color_stop_rgb(1, *YELLOW)
    inked(ctx, g, 5, (5, 5))
    for side in (-1, 1):                                       # the shades
        rounded_rect(ctx, side * 26 - 21, -16, 42, 26, 10)
        ctx.set_source_rgb(*INK)
        ctx.fill()
        ctx.move_to(side * 26 - 12, -10)
        ctx.line_to(side * 26 - 2, -10)
        ctx.set_source_rgba(1, 1, 1, 0.7)
        ctx.set_line_width(3)
        ctx.stroke()
    ctx.move_to(-6, -6)
    ctx.line_to(6, -6)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.arc(0, 18, 22, 0.25, math.pi - 0.25)                   # and the grin
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.restore()


def cloud_shape(ctx, scale):
    ctx.save()
    ctx.scale(scale, scale)
    for cx, cy, r in ((-50, 10, 34), (-14, -14, 44), (30, -2, 38), (58, 16, 26), (0, 22, 30)):
        ctx.new_sub_path()
        ctx.arc(cx, cy, r, 0, TAU)
    ctx.restore()


def cloud(ctx, t, spot, start, grey=0.0):
    k = back_out(span(t, start, start + 0.3), 2.4)
    if k <= 0:
        return
    x, y = SPOTS[spot]
    ctx.save()
    ctx.translate(x + 6 * math.sin(t * 0.9 + start), y)
    ctx.push_group()
    cloud_shape(ctx, k)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(10)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*mix(WHITE, (0.6, 0.62, 0.7), grey))
    ctx.fill()
    ctx.pop_group_to_source()
    ctx.paint()
    ctx.restore()


def sports(ctx, t, frame):
    """Scattered sports: baseballs and footballs falling from the Annapolis cloud."""
    if not RAIN[0] <= t < RAIN[1] + 0.8:
        return
    x0, y0 = SPOTS['sports']
    rand = random.Random(23)
    for k in range(44):
        start = RAIN[0] + (RAIN[1] - RAIN[0]) * k / 44 + rand.uniform(0, 0.05)
        p = span(t, start, start + 0.8)
        if not 0 < p < 1:
            continue
        x = x0 + rand.uniform(-80, 80)
        y = y0 + 30 + 260 * p
        alpha = 1 - span(p, 0.7, 1.0)
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(rand.uniform(-1, 1) + p * rand.uniform(-3, 3))
        ctx.push_group()
        if k % 2:                                              # a baseball
            ctx.arc(0, 0, 14, 0, TAU)
            inked(ctx, WHITE, 3, (0, 0))
            for side in (-1, 1):
                ctx.arc(side * 19, 0, 11, math.pi / 2 + 0.5 if side < 0 else -math.pi / 2 - 0.5 + math.pi,
                        3 * math.pi / 2 - 0.5 if side < 0 else math.pi / 2 + 0.5 + math.pi)
                ctx.set_source_rgb(0.9, 0.15, 0.15)
                ctx.set_line_width(1.6)
                ctx.stroke()
        else:                                                  # a football
            ctx.scale(1.6, 1)
            ctx.arc(0, 0, 11, 0, TAU)
            inked(ctx, (0.55, 0.27, 0.12), 3, (0, 0))
            ctx.move_to(-4, -2)
            ctx.line_to(4, -2)
            ctx.set_source_rgb(*WHITE)
            ctx.set_line_width(1.5)
            ctx.stroke()
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(alpha)
        ctx.restore()


def sweep_angle(t):
    return -TAU / 4 + 1.5 * TAU * ease_in_out(span(t, *SWEEP))


def radar(ctx, t):
    """The Doppler: a sweep line from the city, and behind it a storm in the shape of the
    emblem's V, painted in as the line passes (all of it once it has gone round)."""
    if t < SWEEP[0]:
        return
    painted = 1.5 * TAU * ease_in_out(span(t, *SWEEP))
    ctx.save()
    if painted < TAU:
        ctx.move_to(*CITY)
        ctx.arc(CITY[0], CITY[1], 900, -TAU / 4, -TAU / 4 + painted)
        ctx.close_path()
        ctx.clip()
    for k, colour in enumerate(RADAR):                         # the V, green to red at its heart
        ctx.save()
        ctx.translate(CITY[0], CITY[1] + 40)
        ctx.scale(1 - 0.17 * k, 1 - 0.17 * k)
        font(ctx, 'URW Gothic', 560)
        ext = ctx.text_extents('V')
        ctx.move_to(-ext.width / 2 - ext.x_bearing, ext.height * 0.45)
        ctx.text_path('V')
        ctx.restore()
        ctx.set_source_rgba(*colour, 0.55 if k == 0 else 0.7)
        ctx.fill()
    ctx.restore()
    if t < SWEEP[1] + 0.3:                                     # the line itself
        a = sweep_angle(t)
        fade = 1 - span(t, SWEEP[1], SWEEP[1] + 0.3)
        for k in range(14):
            ctx.move_to(*CITY)
            ctx.arc(CITY[0], CITY[1], 900, a - 0.03 * (k + 1), a - 0.03 * k)
            ctx.close_path()
            ctx.set_source_rgba(0.6, 1, 0.6, 0.18 * (1 - k / 14) * fade)
            ctx.fill()
        ctx.move_to(*CITY)
        ctx.line_to(CITY[0] + math.cos(a) * 900, CITY[1] + math.sin(a) * 900)
        ctx.set_source_rgba(0.8, 1, 0.8, 0.9 * fade)
        ctx.set_line_width(3)
        ctx.stroke()


def hundred(ctx, t):
    """100%, stamped beside the storm."""
    k = back_out(span(t, HUNDRED, HUNDRED + 0.3), 3.0)
    if k <= 0:
        return
    out = 1 - ease_in_out(span(t, TILES[0] - 0.1, TILES[0] + 0.2))
    if out <= 0:
        return
    ctx.save()
    ctx.translate(1060, 185)
    ctx.rotate(-0.12)
    ctx.scale(k * (0.6 + 0.4 * out), k * (0.6 + 0.4 * out))
    font(ctx, 'Nimbus Sans', 120, italic=True)
    ctx.new_path()
    text_path(ctx, '100%', 0, 40, align='center')
    inked(ctx, chrome(-50, 40, 0.0), 6, (8, 8))
    font(ctx, 'Nimbus Sans', 26)
    ctx.new_path()
    text_path(ctx, 'CHANCE OF', 0, -64, tracking=4, align='center')
    inked(ctx, YELLOW, 3, (3, 3))
    ctx.restore()


# ---------------------------------------------------------------- the frame's furniture

def title(ctx, t):
    """The bar along the top: 19 in its box, VIZELVISION FORECAST."""
    p = ease_out(span(t, *TITLE))
    if p <= 0:
        return
    y = -90 + 112 * p
    rounded_rect(ctx, 40, y, 640, 64, 12)
    g = cairo.LinearGradient(0, y, 0, y + 64)
    g.add_color_stop_rgb(0, 0.2, 0.35, 0.95)
    g.add_color_stop_rgb(1, 0.05, 0.1, 0.45)
    inked(ctx, g, 4, (5, 5))
    rounded_rect(ctx, 52, y + 8, 76, 48, 8)
    g = cairo.LinearGradient(0, y + 8, 0, y + 56)
    g.add_color_stop_rgb(0, 1.0, 0.35, 0.3)
    g.add_color_stop_rgb(1, 0.7, 0.05, 0.1)
    ctx.set_source(g)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 40, italic=True)
    ctx.new_path()
    text_path(ctx, '19', 90, y + 47, align='center')
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 34, italic=True)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION FORECAST', 146, y + 45, tracking=2)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    shine = span(t, TITLE[1], TITLE[1] + 0.6)               # a glint runs along it
    if 0 < shine < 1:
        glint(ctx, 146 + 500 * shine, y + 12, 14, shine * 3, 0.9)


def tiny_tv(ctx, x, y, s, t):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    A.draw_tv(ctx, t, 1, 0.0)
    ctx.restore()


def tiles(ctx, t):
    """The extended forecast, along the bottom, a tile on each note of the closed logo."""
    p = ease_out(span(t, TILES[0] - 0.25, TILES[0]))
    if p <= 0:
        return
    y0 = H - 168 * p
    ctx.rectangle(0, y0, W, 168)
    g = cairo.LinearGradient(0, y0, 0, H)
    g.add_color_stop_rgba(0, *NAVY, 0.9)
    g.add_color_stop_rgba(1, 0, 0, 0.05, 0.95)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(0, y0, W, 4)
    ctx.set_source_rgb(*YELLOW)
    ctx.fill()
    for i, (name, when) in enumerate(zip(TILE_NAMES, TILES)):
        k = back_out(span(t, when, when + 0.3), 2.6)
        if k <= 0:
            continue
        cx = 175 + i * 310
        ctx.save()
        ctx.translate(cx, y0 + 84)
        ctx.scale(k, k)
        rounded_rect(ctx, -140, -70, 280, 140, 14)
        g = cairo.LinearGradient(0, -70, 0, 70)
        g.add_color_stop_rgb(0, 0.25, 0.45, 1.0)
        g.add_color_stop_rgb(1, 0.08, 0.15, 0.55)
        inked(ctx, g, 4, (5, 5))
        font(ctx, 'Nimbus Sans', 24)
        ctx.new_path()
        text_path(ctx, name, 0, -38, tracking=3, align='center')
        ctx.set_source_rgb(*YELLOW)
        ctx.fill()
        tiny_tv(ctx, -56, 22, 0.19, t)
        font(ctx, 'Nimbus Sans', 52)
        ctx.new_path()
        text_path(ctx, '19°', 60, 44, align='center')
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
        ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.set_source_surface(basemap(), 0, 0)
    ctx.paint()
    radar(ctx, t)
    city_star(ctx, t)
    sports(ctx, t, frame)
    cloud(ctx, t, 'cloud', ICONS[1])
    cloud(ctx, t, 'sports', ICONS[2], grey=0.45)
    sun(ctx, t)
    hundred(ctx, t)
    title(ctx, t)
    tiles(ctx, t)
    scanlines(ctx, 0.06)
    vignette(ctx, 0.4)
    grain(ctx, frame, 0.3)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
