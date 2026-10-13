"""The VizelVision Line: a Washington Metro platform. Under the coffered vault the
platform-edge lights start to blink, a train pulls in and stops, and the door chime plays
the open logo. The TV emblem hops off onto the platform. The operator: "This is a
VizelVision train." "Step back, doors closing." The closed logo chimes, the doors close and the train
pulls out, leaving the station's name on the wall behind it: VizelVision.

The next-train sign, the brown pylon (a V where the M would be) and the hexagonal tile
are all part of it. The camera stays still and the train is motion-blurred.
"""
import math
import random
from functools import lru_cache

import cairo

import beats
from common import (A, CYAN, INK, ORANGE, PINK, PIXEL_FONT, TAU, TEAL, W, H, WHITE, YELLOW, clamp,  # noqa: F401
                    ease_in, ease_in_out, ease_out, font, grain, mix, pulse, rounded_rect, span, vignette)

ID = 'metro'
NAME = 'The VizelVision Line'
KIND = 'ident'
ORDER = 6
DESCRIPTION = ('A Metro platform under the coffered vault: the edge lights blink, a train pulls in, the door chime '
               'plays the logo and the TV emblem hops off. "This is a VizelVision train." "Step back, doors closing." '
               'Voiced by Mars, the operator.')
DURATION = 10.0
STILL_AT = 4.8
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
ARRIVE = beats.TRAIN_ARRIVE  # pulls in, braking all the way
LIGHTS_IN = (0.15, 2.4)      # the platform-edge lights blink while a train comes in...
OPEN_CHIME = 2.5             # the open logo on the door chime
DOORS_OPEN = (2.55, 2.9)
HOP = (3.05, 3.55)           # the emblem hops off
CLOSE_CHIME = 6.5            # the closed logo on the chime, after "Step back, doors closing"; its last note at 7.5
DOORS_CLOSE = (6.75, 7.1)
DEPART = beats.TRAIN_DEPART
LIGHTS_OUT = (6.8, 8.25)     # ...and while it leaves
BUTTON = 8.5                 # the sign lights up, the emblem hops
FADE = (9.2, 9.55)

# The scene, side on across the tracks.
WALL_BASE = 462              # where the vault meets the trackbed
EDGE = 558                   # the platform's edge
ROOF, SILL, SKIRT = 236, 548, 584
CAR, GAP, DOORS, STOP_X = beats.CAR, beats.GAP, beats.DOORS, beats.STOP_X   # the train (its motion: beats.py)
DOOR_W, DOOR_TOP = 160, 304
WINDOWS = ((36, 196), (404, 646), (854, 1096), (1304, 1464))
MIDDLE = 640
LANDING = (560, 672)         # the emblem's feet on the platform
SIGN = (322, 326, 636, 84)

CONCRETE = (0.70, 0.64, 0.56)
BRONZE = (0.31, 0.19, 0.11)
TILE = (0.56, 0.26, 0.16)
GRANITE = (0.75, 0.73, 0.69)
AMBER = (1.0, 0.68, 0.12)
STRIPE = (PINK, WHITE, TEAL)


# ---------------------------------------------------------------- the station (static, drawn once)

def _quad(ctx, pts):
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)
    ctx.close_path()


@lru_cache(maxsize=None)
def far_surface():
    """The vault, its coffers lit from below, the station sign, the trackbed."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, WALL_BASE)
    g.add_color_stop_rgb(0, *mix(CONCRETE, INK, 0.62))
    g.add_color_stop_rgb(1, *mix(CONCRETE, WHITE, 0.08))
    ctx.set_source(g)
    ctx.paint()
    # The coffers: rows growing and fanning out as the vault curves over towards us.
    y, k = WALL_BASE - 12, 0
    while y > -120:
        h = 70 + 9 * k
        top = y - h
        fan_b, fan_t = 1 + 0.08 * k, 1 + 0.08 * (k + 1)
        light = clamp(1 - 0.12 * k)
        for c in range(-12, 13):
            xb0, xb1 = W / 2 + (c * 96 - 48) * fan_b, W / 2 + (c * 96 + 48) * fan_b
            xt0, xt1 = W / 2 + (c * 96 - 48) * fan_t, W / 2 + (c * 96 + 48) * fan_t
            if max(xb1, xt1) < -40 or min(xb0, xt0) > W + 40:
                continue

            def at(u, v):    # u across the cell, v up it (0 bottom, 1 top)
                xl, xr = xb0 + (xt0 - xb0) * v, xb1 + (xt1 - xb1) * v
                return xl + (xr - xl) * u, y - h * v

            rib = 0.09
            outer = [at(rib, rib), at(1 - rib, rib), at(1 - rib, 1 - rib), at(rib, 1 - rib)]
            inner = [at(0.27, 0.22), at(0.73, 0.22), at(0.73, 0.66), at(0.27, 0.66)]
            base = mix(mix(CONCRETE, INK, 0.62), CONCRETE, light)
            faces = ((outer[2], outer[3], inner[3], inner[2], mix(base, (1, 0.9, 0.72), 0.45)),   # top: lit
                     (outer[0], outer[1], inner[1], inner[0], mix(base, INK, 0.5)),               # bottom: shade
                     (outer[3], outer[0], inner[0], inner[3], mix(base, INK, 0.22)),
                     (outer[1], outer[2], inner[2], inner[1], mix(base, INK, 0.3)))
            for *pts, colour in faces:
                _quad(ctx, pts)
                ctx.set_source_rgb(*colour)
                ctx.fill()
            _quad(ctx, inner)
            ctx.set_source_rgb(*mix(base, INK, 0.35))
            ctx.fill()
        y, k = top, k + 1
    # The uplight's warm wash along the bottom of the vault.
    g = cairo.LinearGradient(0, WALL_BASE - 260, 0, WALL_BASE)
    g.add_color_stop_rgba(0, 1, 0.85, 0.6, 0)
    g.add_color_stop_rgba(1, 1, 0.85, 0.6, 0.22)
    ctx.set_source(g)
    ctx.rectangle(0, WALL_BASE - 260, W, 260)
    ctx.fill()
    sign(ctx, 0.0)
    # The trackbed: the third rail under its cover, ties, rails.
    ctx.rectangle(0, WALL_BASE, W, EDGE - WALL_BASE + 40)
    ctx.set_source_rgb(0.13, 0.11, 0.1)
    ctx.fill()
    ctx.rectangle(0, WALL_BASE, W, 6)
    ctx.set_source_rgb(0.3, 0.26, 0.22)
    ctx.fill()
    rand = random.Random(7019)
    for _ in range(900):
        ctx.rectangle(rand.uniform(0, W), rand.uniform(WALL_BASE + 6, EDGE), 2, 2)
    ctx.set_source_rgba(0.45, 0.4, 0.35, 0.5)
    ctx.fill()
    for x in range(-10, W + 40, 44):
        ctx.rectangle(x, 496, 18, 48)
    ctx.set_source_rgb(0.22, 0.18, 0.15)
    ctx.fill()
    for x in range(30, W, 160):
        ctx.rectangle(x, 474, 8, 14)
    ctx.set_source_rgb(0.2, 0.2, 0.2)
    ctx.fill()
    ctx.rectangle(0, 472, W, 9)
    ctx.set_source_rgb(0.86, 0.82, 0.68)
    ctx.fill()
    for y0 in (500, 534):
        ctx.rectangle(0, y0, W, 6)
        ctx.set_source_rgb(0.25, 0.23, 0.22)
        ctx.fill()
        ctx.rectangle(0, y0, W, 2)
        ctx.set_source_rgb(0.85, 0.85, 0.88)
        ctx.fill()
    return surface


def sign(ctx, glow):
    """The station's name on the track wall, white on bronze, and the lines that stop here."""
    x, y, w, h = SIGN
    if glow <= 0:
        rounded_rect(ctx, x + 6, y + 8, w, h, 10)
        ctx.set_source_rgba(0, 0, 0, 0.35)
        ctx.fill()
        rounded_rect(ctx, x, y, w, h, 10)
        ctx.set_source_rgb(*BRONZE)
        ctx.fill_preserve()
        ctx.set_source_rgb(*mix(BRONZE, WHITE, 0.25))
        ctx.set_line_width(3)
        ctx.stroke()
    font(ctx, 'Nimbus Sans', 58)
    ctx.move_to(x + 34, y + h / 2 + 21)
    ctx.text_path('VizelVision')
    if glow > 0:
        ctx.set_source_rgba(1, 0.93, 0.75, 0.55 * glow)
        ctx.set_line_width(10)
        ctx.stroke_preserve()
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    for i, colour in enumerate((PINK, YELLOW, TEAL, ORANGE, CYAN)):
        cx = x + w - 196 + i * 38
        ctx.arc(cx, y + h / 2, 14, 0, TAU)
        ctx.set_source_rgb(*colour)
        ctx.fill_preserve()
        ctx.set_source_rgb(*WHITE)
        ctx.set_line_width(2.5)
        ctx.stroke()


@lru_cache(maxsize=None)
def near_surface():
    """The platform: its granite edge (the lights' housings) and the hexagonal quarry tile."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    ctx.rectangle(0, EDGE, W, H - EDGE)
    ctx.set_source_rgb(*TILE)
    ctx.fill()
    rand = random.Random(1976)
    y, r = 600, 0
    while y < H:
        hh = 15 + 4.5 * r
        tw = hh * 2.1
        offset = (tw * 0.75) * (r % 2)
        x = -tw - offset
        while x < W + tw:
            cx, cy = x + tw / 2, y + hh / 2
            ctx.move_to(cx - tw / 2, cy)
            ctx.line_to(cx - tw / 4, cy - hh / 2)
            ctx.line_to(cx + tw / 4, cy - hh / 2)
            ctx.line_to(cx + tw / 2, cy)
            ctx.line_to(cx + tw / 4, cy + hh / 2)
            ctx.line_to(cx - tw / 4, cy + hh / 2)
            ctx.close_path()
            ctx.set_source_rgb(*mix(TILE, (0.7, 0.36, 0.22) if rand.random() < 0.5 else (0.42, 0.18, 0.11),
                                    rand.uniform(0, 0.35)))
            ctx.fill_preserve()
            ctx.set_source_rgb(0.3, 0.16, 0.1)
            ctx.set_line_width(1.5 + 0.25 * r)
            ctx.stroke()
            x += tw * 1.5
        y += hh / 2
        r += 1
    # The granite edge, its bullnose and a shadow under it.
    ctx.rectangle(0, EDGE, W, 44)
    ctx.set_source_rgb(*GRANITE)
    ctx.fill()
    for _ in range(1400):
        ctx.rectangle(rand.uniform(0, W), rand.uniform(EDGE, EDGE + 44), 2, 2)
        ctx.set_source_rgba(*((0.35, 0.33, 0.3) if rand.random() < 0.6 else (1, 1, 1)), 0.5)
        ctx.fill()
    ctx.rectangle(0, EDGE, W, 5)
    ctx.set_source_rgb(0.93, 0.92, 0.88)
    ctx.fill()
    ctx.rectangle(0, EDGE + 44, W, 4)
    ctx.set_source_rgba(0, 0, 0, 0.3)
    ctx.fill()
    for x in LIGHT_XS:
        ctx.arc(x, LIGHT_Y, 10, 0, TAU)
        ctx.set_source_rgb(0.32, 0.31, 0.3)
        ctx.fill()
        ctx.arc(x, LIGHT_Y, 7, 0, TAU)
        ctx.set_source_rgb(0.62, 0.58, 0.5)
        ctx.fill()
    return surface


LIGHT_XS = tuple(range(44, W, 88))
LIGHT_Y = EDGE + 22


def lights(ctx, t):
    """The edge lights: a soft blink while a train comes in or goes out."""
    level = 0.0
    for a, b in (LIGHTS_IN, LIGHTS_OUT):
        if a <= t < b:
            level = (0.5 + 0.5 * math.cos(TAU * (t - a) * 1.5)) * min(1.0, (b - t) / 0.3)
    if level <= 0.02:
        return
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for x in LIGHT_XS:
        g = cairo.RadialGradient(x, LIGHT_Y, 0, x, LIGHT_Y, 34)
        g.add_color_stop_rgba(0, 1, 0.9, 0.6, 0.9 * level)
        g.add_color_stop_rgba(0.25, 1, 0.75, 0.35, 0.35 * level)
        g.add_color_stop_rgba(1, 1, 0.7, 0.3, 0)
        ctx.set_source(g)
        ctx.arc(x, LIGHT_Y, 34, 0, TAU)
        ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the train

def interior(ctx, x, y, w, h):
    """Inside a car, seen through a doorway: the light strip, the far side's windows (the
    tunnel), the seats' ends, a pole and the carpet."""
    g = cairo.LinearGradient(0, y, 0, y + h)
    for stop, rgb in ((0, (1.0, 0.97, 0.88)), (0.2, (0.92, 0.86, 0.72)), (0.7, (0.8, 0.72, 0.58)), (1, (0.55, 0.46, 0.36))):
        g.add_color_stop_rgb(stop, *rgb)
    ctx.rectangle(x, y, w, h)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(x, y + 6, w, 9)
    ctx.set_source_rgb(1, 1, 0.97)
    ctx.fill()
    ctx.rectangle(x, y + 44, w, 64)
    ctx.set_source_rgb(0.07, 0.08, 0.11)
    ctx.fill()
    for sx, sw in ((x - 10, 46), (x + w - 36, 46)):
        rounded_rect(ctx, sx, y + 120, sw, 92, 10)
        ctx.set_source_rgb(0.78, 0.33, 0.17)
        ctx.fill()
        rounded_rect(ctx, sx, y + 196, sw, 22, 6)
        ctx.set_source_rgb(0.6, 0.24, 0.13)
        ctx.fill()
    ctx.rectangle(x, y + h - 22, w, 22)
    ctx.set_source_rgb(0.5, 0.24, 0.18)
    ctx.fill()
    ctx.rectangle(x + w * 0.66, y + 15, 6, h - 37)
    ctx.set_source_rgb(0.86, 0.87, 0.9)
    ctx.fill()


def window(ctx, x0, x1, y0=316, y1=420):
    rounded_rect(ctx, x0, y0, x1 - x0, y1 - y0, 12)
    ctx.save()
    ctx.clip_preserve()
    g = cairo.LinearGradient(0, y0, 0, y1)
    g.add_color_stop_rgb(0, 1.0, 0.95, 0.8)
    g.add_color_stop_rgb(0.25, 0.9, 0.84, 0.68)
    g.add_color_stop_rgb(1, 0.7, 0.6, 0.46)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(x0, y0 + 20, x1 - x0, 46)                       # the far side's windows: the tunnel
    ctx.set_source_rgb(0.08, 0.09, 0.13)
    ctx.fill()
    for sx in range(int(x0) + 8, int(x1) - 20, 58):              # seat backs
        rounded_rect(ctx, sx, y1 - 34, 48, 40, 8)
        ctx.set_source_rgb(*((0.78, 0.33, 0.17) if (sx // 58) % 2 else (0.62, 0.24, 0.14)))
        ctx.fill()
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)                       # the glass, and a reflection
    ctx.set_source_rgba(0.12, 0.2, 0.32, 0.28)
    ctx.fill()
    ctx.move_to(x0 + 20, y1)
    ctx.line_to(x0 + 70, y0)
    ctx.line_to(x0 + 105, y0)
    ctx.line_to(x0 + 55, y1)
    ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.12)
    ctx.fill()
    ctx.restore()
    ctx.set_source_rgb(0.2, 0.2, 0.22)
    ctx.set_line_width(5)
    ctx.stroke()


def leaf(ctx, x):
    """One door leaf, 80 wide, with its window."""
    ctx.rectangle(x, DOOR_TOP, DOOR_W / 2, SILL - DOOR_TOP)
    g = cairo.LinearGradient(0, DOOR_TOP, 0, SILL)
    g.add_color_stop_rgb(0, 0.8, 0.82, 0.85)
    g.add_color_stop_rgb(1, 0.62, 0.64, 0.67)
    ctx.set_source(g)
    ctx.fill()
    window(ctx, x + 14, x + DOOR_W / 2 - 14, 318, 414)
    ctx.rectangle(x, DOOR_TOP, DOOR_W / 2, SILL - DOOR_TOP)
    ctx.set_source_rgb(0.3, 0.3, 0.32)
    ctx.set_line_width(2)
    ctx.stroke()


def door(ctx, dc, opening, inside=None):
    """A doorway, its two leaves sliding apart into the wall. Drawn live (open, or with
    someone inside), the car's inside shows through the gap and the leaves' glass."""
    x0 = dc - DOOR_W / 2
    live = opening > 0 or inside is not None
    if live:
        interior(ctx, x0, DOOR_TOP, DOOR_W, SILL - DOOR_TOP)
        if inside:
            ctx.save()
            ctx.rectangle(x0, DOOR_TOP, DOOR_W, SILL - DOOR_TOP)
            ctx.clip()
            inside()
            ctx.restore()
    ctx.save()
    ctx.rectangle(x0, DOOR_TOP, DOOR_W, SILL - DOOR_TOP)
    ctx.clip()
    for side in (-1, 1):
        (leaf_glass if live else leaf)(ctx, (x0 if side < 0 else dc) + side * (DOOR_W / 2 - 4) * opening)
    ctx.restore()
    rounded_rect(ctx, x0 - 4, DOOR_TOP - 4, DOOR_W + 8, SILL - DOOR_TOP + 4, 6)
    ctx.set_source_rgb(0.18, 0.18, 0.2)
    ctx.set_line_width(5)
    ctx.stroke()


def led_text(ctx, text, x, y, cell, colour, dim=0.08):
    """Text in the 5x7 face as round LEDs, unlit dots faintly showing."""
    lit, unlit = [], []
    for i, ch in enumerate(text.upper()):
        rows = PIXEL_FONT.get(ch, PIXEL_FONT['?']).split()
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                (lit if bit == '1' else unlit).append((x + (i * 6 + c) * cell + cell / 2, y + r * cell + cell / 2))
    for dots, alpha in ((unlit, dim), (lit, 1.0)):
        for px, py in dots:
            ctx.new_sub_path()
            ctx.arc(px, py, cell * 0.42, 0, TAU)
        ctx.set_source_rgba(*colour, alpha)
        ctx.fill()


@lru_cache(maxsize=None)
def car_surface(number, headsign):
    """A car with its doors shut, drawn once; the train is these, blitted (and blurred)."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, CAR + 20, SKIRT - ROOF + 40)
    ctx = cairo.Context(surface)
    ctx.translate(10, -(ROOF - 20))
    ctx.rectangle(16, SILL - 4, CAR - 32, SKIRT - SILL + 4)        # the underframe
    ctx.set_source_rgb(0.14, 0.14, 0.15)
    ctx.fill()
    rounded_rect(ctx, 0, ROOF, CAR, SILL - ROOF + 4, 24)
    g = cairo.LinearGradient(0, ROOF, 0, SILL)
    for stop, rgb in ((0, (0.62, 0.64, 0.67)), (0.06, (0.9, 0.91, 0.93)), (0.5, (0.8, 0.82, 0.85)),
                      (1, (0.6, 0.62, 0.65))):
        g.add_color_stop_rgb(stop, *rgb)
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.save()
    ctx.clip()
    for y in range(ROOF + 30, SILL, 7):                            # brushed aluminium
        ctx.rectangle(0, y, CAR, 1)
    ctx.set_source_rgba(1, 1, 1, 0.12)
    ctx.fill()
    ctx.restore()
    ctx.rectangle(0, ROOF + 14, CAR, 3)                             # the roof line
    ctx.set_source_rgba(0.3, 0.3, 0.33, 0.6)
    ctx.fill()
    for x0, x1 in WINDOWS:
        window(ctx, x0, x1)
    for i, colour in enumerate(STRIPE):                             # the line's stripe
        ctx.rectangle(0, 432 + i * 8, CAR, 7)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    x0, x1 = WINDOWS[1]                                              # the headsign, in a window
    rounded_rect(ctx, x0 + 18, 326, x1 - x0 - 36, 36, 5)
    ctx.set_source_rgb(0.04, 0.04, 0.05)
    ctx.fill()
    width = (len(headsign) * 6 - 1) * 2.9
    led_text(ctx, headsign, (x0 + x1) / 2 - width / 2, 334, 2.9, AMBER, 0.06)
    for dc in DOORS:
        door(ctx, dc, 0.0)
    font(ctx, 'Nimbus Sans', 22)
    ctx.set_source_rgb(0.15, 0.15, 0.17)
    ctx.move_to(CAR - 112, 480)
    ctx.show_text(number)
    ctx.move_to(40, 480)
    ctx.show_text(number)
    rounded_rect(ctx, 0, ROOF, CAR, SILL - ROOF + 4, 24)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    return surface


CARS = (('7019', 'VIZELVISION'), ('7070', 'VIZELVISION'))


train_x = beats.train_x


def door_opening(t):
    return ease_in_out(span(t, *DOORS_OPEN)) * (1 - ease_in_out(span(t, *DOORS_CLOSE)))


def cars(ctx, x):
    for k, (number, headsign) in enumerate(CARS):
        x0 = x + k * (CAR + GAP)
        if x0 > W + 20 or x0 + CAR < -20:
            continue
        ctx.set_source_surface(car_surface(number, headsign), x0 - 10, ROOF - 20)
        ctx.paint()
    gap = x + CAR                                                    # the gangway between cars
    if -GAP < gap < W:
        ctx.rectangle(gap - 2, ROOF + 40, GAP + 4, SILL - ROOF - 40)
        ctx.set_source_rgb(0.08, 0.08, 0.09)
        ctx.fill()


def train(ctx, t, x):
    """The train, blurred over half a frame's travel (a 180-degree shutter)."""
    dt = 1 / 240
    before, after = train_x(t - dt), train_x(t + dt)
    speed = abs((after if after is not None else x) - (before if before is not None else x)) / (2 * dt)
    travel = speed / 60 * 0.5
    samples = min(8, 1 + int(travel / 4))
    if samples == 1:
        cars(ctx, x)
        return
    ctx.push_group()
    for k in range(samples):
        ctx.push_group()
        cars(ctx, x + travel * (k / (samples - 1) - 0.5))
        ctx.pop_group_to_source()
        ctx.set_operator(cairo.OPERATOR_ADD)
        ctx.paint_with_alpha(1 / samples)
        ctx.set_operator(cairo.OPERATOR_OVER)
    ctx.pop_group_to_source()
    ctx.paint()


def stopped(ctx, t):
    """The train at the platform: its doors drawn live, and the emblem aboard until it hops."""
    x = STOP_X + CAR + GAP
    opening = door_opening(t)
    for dc in DOORS:
        aboard = x + dc == MIDDLE and t < HOP[0]
        if opening > 0 or aboard:
            door(ctx, x + dc, opening, (lambda: tv(ctx, t, MIDDLE, SILL - 2, 0.42)) if aboard else None)


def leaf_glass(ctx, x):
    """A leaf with its window as tinted glass (what is behind shows through)."""
    ctx.save()
    ctx.rectangle(x, DOOR_TOP, DOOR_W / 2, SILL - DOOR_TOP)
    ctx.rectangle(x + 14, 318, DOOR_W / 2 - 28, 96)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    g = cairo.LinearGradient(0, DOOR_TOP, 0, SILL)
    g.add_color_stop_rgb(0, 0.8, 0.82, 0.85)
    g.add_color_stop_rgb(1, 0.62, 0.64, 0.67)
    ctx.set_source(g)
    ctx.fill()
    ctx.restore()
    rounded_rect(ctx, x + 14, 318, DOOR_W / 2 - 28, 96, 12)
    ctx.set_source_rgba(0.12, 0.2, 0.32, 0.3)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.2, 0.2, 0.22)
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.rectangle(x, DOOR_TOP, DOOR_W / 2, SILL - DOOR_TOP)
    ctx.set_source_rgb(0.3, 0.3, 0.32)
    ctx.set_line_width(2)
    ctx.stroke()


# ---------------------------------------------------------------- the emblem, the pylon, the next-train sign

def tv(ctx, t, x, feet, scale, squash=0.0, shadow=0.0):
    """The ID's TV emblem standing with its feet at (x, feet)."""
    if shadow:
        ctx.save()
        ctx.translate(x, feet + 2)
        ctx.scale(1, 0.22)
        ctx.arc(0, 0, 150 * scale, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(0, 0, 0, 0.35 * shadow)
        ctx.fill()
    ctx.save()
    ctx.translate(x, feet)
    ctx.scale(scale * (1 + 0.12 * squash), scale * (1 - 0.15 * squash))
    ctx.translate(0, -132)
    A.draw_tv(ctx, t, 1, 0)
    ctx.restore()


def emblem(ctx, t):
    """Off the train and onto the platform, a step closer; a hop on the button."""
    if t < HOP[0]:
        return
    p = span(t, *HOP)
    x = MIDDLE + (LANDING[0] - MIDDLE) * ease_in_out(p)
    feet = SILL - 2 + (LANDING[1] - SILL + 2) * p - 120 * math.sin(math.pi * p)
    scale = 0.42 + 0.14 * ease_in_out(p)
    hop = math.sin(math.pi * span(t, BUTTON, BUTTON + 0.4)) * 40
    squash = pulse(t, HOP[1], 0.3) + pulse(t, BUTTON + 0.4, 0.25)
    tv(ctx, t, x, feet - hop, scale, squash, shadow=p * (1 - 0.5 * hop / 40))


def pylon(ctx, t):
    """The brown pylon: a V where the M would be, over the stripes of the lines."""
    x, top, w, side = 1150, 112, 74, 20
    ctx.move_to(x + w, top)
    ctx.line_to(x + w + side, top + 10)
    ctx.line_to(x + w + side, H + 10)
    ctx.line_to(x + w, H + 10)
    ctx.close_path()
    ctx.set_source_rgb(*mix(BRONZE, INK, 0.35))
    ctx.fill()
    ctx.rectangle(x, top, w, H - top + 10)
    g = cairo.LinearGradient(x, 0, x + w, 0)
    g.add_color_stop_rgb(0, *mix(BRONZE, WHITE, 0.12))
    g.add_color_stop_rgb(1, BRONZE[0], BRONZE[1], BRONZE[2])
    ctx.set_source(g)
    ctx.fill()
    glow = 0.75 + 0.25 * pulse(t, BUTTON, 0.8)
    rounded_rect(ctx, x + 8, top + 14, w - 16, 74, 6)               # the lit V panel
    ctx.set_source_rgba(1, 0.97, 0.88, 0.12 * glow)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 66)
    ext = ctx.text_extents('V')
    ctx.move_to(x + w / 2 - ext.width / 2 - ext.x_bearing, top + 78)
    ctx.text_path('V')
    ctx.set_source_rgb(*mix(WHITE, (1, 0.95, 0.8), 1 - glow))
    ctx.fill()
    for i, colour in enumerate((PINK, YELLOW, TEAL, ORANGE, CYAN)):
        ctx.rectangle(x, top + 100 + i * 9, w, 7)
        ctx.set_source_rgb(*colour)
        ctx.fill()
        ctx.move_to(x + w, top + 100 + i * 9 + 1)
        ctx.line_to(x + w + side, top + 100 + i * 9 + 3)
        ctx.line_to(x + w + side, top + 100 + i * 9 + 9)
        ctx.line_to(x + w, top + 100 + i * 9 + 7)
        ctx.close_path()
        ctx.set_source_rgb(*mix(colour, INK, 0.35))
        ctx.fill()
    ctx.rectangle(x, top, w, H - top + 10)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(3)
    ctx.stroke()


PIDS = (40, 34, 556, 128)


def board(t):
    """The next-train sign's rows: the line in its colour, the rest amber."""
    header = 'LN CAR DEST        MIN'
    if t < ARRIVE[1]:
        first = 'VV  8  VIZELVISION ARR'
    elif t < DEPART[1]:
        first = 'VV  8  VIZELVISION BRD'
    else:
        first = 'VV  6  VIZELVISION  19'
    second = 'VV  6  VIZELVISION  19' if t < DEPART[1] else ''
    return header, first, second


@lru_cache(maxsize=None)
def board_surface(rows):
    x, y, w, h = PIDS
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w + 20, h + 40)
    ctx = cairo.Context(surface)
    ctx.translate(10 - x, 30 - y)
    for rx in (x + 90, x + w - 90):                                 # hung from the vault
        ctx.rectangle(rx - 3, y - 40, 6, 42)
    ctx.set_source_rgb(0.2, 0.2, 0.22)
    ctx.fill()
    rounded_rect(ctx, x, y, w, h, 8)
    ctx.set_source_rgb(0.12, 0.12, 0.13)
    ctx.fill()
    rounded_rect(ctx, x + 10, y + 10, w - 20, h - 20, 4)
    ctx.set_source_rgb(0.01, 0.01, 0.015)
    ctx.fill()
    cell = 3.9
    for i, row in enumerate(rows):
        ry = y + 18 + i * 34
        rx = x + w / 2 - 22 * 6 * cell / 2
        if not row:
            led_text(ctx, ' ' * 22, rx, ry, cell, AMBER)
            continue
        led_text(ctx, row, rx, ry, cell, mix(AMBER, (1, 0.4, 0.1), 0.25) if i == 0 else AMBER)
        if i and row.startswith('VV'):
            ctx.rectangle(rx, ry, 2 * 6 * cell, 7 * cell)
            ctx.set_source_rgb(0.01, 0.01, 0.015)
            ctx.fill()
            led_text(ctx, 'VV', rx, ry, cell, PINK)
    return surface


def pids(ctx, t):
    x, y, _, _ = PIDS
    ctx.set_source_surface(board_surface(board(t)), x - 10, y - 30)
    ctx.paint()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.set_source_surface(far_surface(), 0, 0)
    ctx.paint()
    glow = ease_out(span(t, BUTTON, BUTTON + 0.5))
    if glow > 0:
        sign(ctx, glow)
    x = train_x(t)
    if x is not None:
        train(ctx, t, x)
        if ARRIVE[1] <= t < DEPART[0]:
            stopped(ctx, t)
    ctx.set_source_surface(near_surface(), 0, 0)
    ctx.paint()
    lights(ctx, t)
    emblem(ctx, t)
    pylon(ctx, t)
    pids(ctx, t)
    vignette(ctx, 0.5)
    ctx.set_source_rgba(1.0, 0.8, 0.5, 0.04)
    ctx.paint()
    grain(ctx, frame, 0.45)
    opening = 1 - ease_out(span(t, 0.0, 0.35))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    fade = span(t, *FADE)
    if fade > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(fade))
        ctx.paint()
