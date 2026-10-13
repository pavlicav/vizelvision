"""From Dupont Circle: a summer afternoon in the circle. The fountain's jet spurts the
open logo, a knight hops on a chess table and the pigeons peck. "From Dupont Circle...
this is VizelVision." On the closed logo the jet climbs four times, the pigeons take off
and the wordmark drops in over the rowhouses.

The fountain: the white marble basin on its shaft of three figures (the sea, the stars,
the wind), water falling from the rim all round into the pool. Rowhouses with bays and
turrets ring the circle behind the elms.
"""
import math
import random
from functools import lru_cache

import cairo

from common import (INK, PINK, TAU, W, H, WHITE, back_out, clamp, ease_in, ease_in_out, ease_out, glint, grain,  # noqa: F401
                    inked, mix, pulse, rounded_rect, span, vignette)
import neighborhood

ID = 'dupont'
NAME = 'From Dupont Circle'
KIND = 'ident'
ORDER = 7
DESCRIPTION = ('A summer afternoon at the Dupont Circle fountain: the jet spurts the logo, a knight hops on a chess '
               'table, the pigeons take off on the closed logo. "From Dupont Circle... this is VizelVision." '
               'Voiced by Delia.')
DURATION = 10.0
STILL_AT = 8.6
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
OPEN_SPURTS = ((1.0, 70), (1.25, 92), (1.5, 116), (2.0, 150))        # the open logo: (time, height)
CLOSED_SPURTS = ((7.0, 110), (7.25, 140), (7.5, 175), (8.0, 230))    # the closed logo, higher
KNIGHT = (2.55, 2.95)        # the knight's hop; it lands with a click
TAG = (0.6, 6.7)             # the place tag in, out
TAKE_OFF = 7.0               # the pigeons
LOCKUP = 7.0
BUTTON = 9.0
FADE = (9.2, 9.55)

CX = 640
POOL_Y, POOL_RX, POOL_RY, RIM_H = 545, 330, 62, 24
BOWL_Y, BOWL_RX, BOWL_RY = 350, 196, 30
GRAVITY = 900.0
MARBLE = (0.95, 0.93, 0.88)
WATER = (0.3, 0.64, 0.74)
LAWN = (0.36, 0.62, 0.24)
PAVING = (0.86, 0.82, 0.74)
SKY = ((0.36, 0.62, 0.92), (0.66, 0.84, 0.97), (0.9, 0.95, 0.97))


def camera(ctx, t):
    """A slow push in on the fountain."""
    k = 1 + 0.045 * ease_in_out(span(t, 0, DURATION))
    ctx.translate(CX, 420)
    ctx.scale(k, k)
    ctx.translate(-CX, -420)


# ---------------------------------------------------------------- the sky and the circle (static, drawn once)

def sky(ctx, t):
    g = cairo.LinearGradient(0, 0, 0, 430)
    for stop, rgb in zip((0, 0.6, 1), SKY):
        g.add_color_stop_rgb(stop, *rgb)
    ctx.set_source(g)
    ctx.paint()
    for cx, cy, s, speed in ((180, 80, 1.0, 9), (560, 52, 0.7, 6), (930, 96, 1.2, 8), (1250, 60, 0.8, 7)):
        x = (cx + speed * t) % (W + 400) - 200
        for dx, dy, r in ((-60, 10, 34), (-22, -12, 46), (24, -4, 40), (62, 12, 30), (0, 16, 38)):
            ctx.new_sub_path()
            ctx.arc(x + dx * s, cy + dy * s, r * s, 0, TAU)
        ctx.set_source_rgba(1, 1, 1, 0.85)
        ctx.fill()
        ctx.rectangle(x - 90 * s, cy + 14 * s, 180 * s, 16 * s)
        ctx.set_source_rgba(0.75, 0.84, 0.95, 0.5)
        ctx.fill()


HOUSE_COLOURS = ((0.69, 0.31, 0.24), (0.58, 0.26, 0.2), (0.62, 0.8, 0.7), (0.78, 0.7, 0.88), (0.95, 0.8, 0.45),
                 (0.93, 0.88, 0.78), (0.45, 0.58, 0.72), (0.86, 0.5, 0.42))


def house(ctx, rand, x, w, top, base):
    colour = rand.choice(HOUSE_COLOURS)
    ctx.rectangle(x, top, w, base - top)
    ctx.set_source_rgb(*colour)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.rectangle(x - 4, top, w + 8, 14)                       # the cornice
    ctx.set_source_rgb(*mix(colour, INK, 0.35))
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.stroke()
    bay = rand.random() < 0.55
    if bay:                                                     # a bay, maybe under a turret
        bx, bw = x + w * 0.12, w * 0.42
        ctx.rectangle(bx, top + 22, bw, base - top - 22)
        ctx.set_source_rgb(*mix(colour, WHITE, 0.12))
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.stroke()
        if rand.random() < 0.6:
            ctx.move_to(bx - 4, top + 2)
            ctx.line_to(bx + bw / 2, top - 52)
            ctx.line_to(bx + bw + 4, top + 2)
            ctx.close_path()
            ctx.set_source_rgb(0.32, 0.36, 0.42)
            ctx.fill_preserve()
            ctx.set_source_rgb(*INK)
            ctx.stroke()
    cols = 2 if w < 120 else 3
    for row in range(4):
        wy = top + 30 + row * 52
        if wy + 34 > base:
            break
        for c in range(cols):
            wx = x + 12 + c * (w - 24) / cols + ((w - 24) / cols - 22) / 2
            ctx.rectangle(wx, wy, 22, 34)
            ctx.set_source_rgb(*WHITE)
            ctx.fill()
            ctx.rectangle(wx + 3, wy + 3, 16, 28)
            g = cairo.LinearGradient(0, wy, 0, wy + 34)
            g.add_color_stop_rgb(0, 0.55, 0.72, 0.88)
            g.add_color_stop_rgb(1, 0.2, 0.26, 0.36)
            ctx.set_source(g)
            ctx.fill()


def canopy(ctx, blobs, colour):
    """A tree's crown: ink round the whole cluster, then the leaves, then the light on them."""
    for x, y, r in blobs:
        ctx.new_sub_path()
        ctx.arc(x, y, r, 0, TAU)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(10)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*colour)
    ctx.fill()
    for x, y, r in blobs:
        ctx.new_sub_path()
        ctx.arc(x - r * 0.25, y - r * 0.3, r * 0.55, 0, TAU)
    ctx.set_source_rgba(*mix(colour, (0.85, 0.95, 0.4), 0.5), 0.5)
    ctx.fill()


def tree(ctx, rand, x, base, size):
    ctx.move_to(x - 12 * size, base)
    ctx.line_to(x - 7 * size, base - 120 * size)
    ctx.line_to(x + 7 * size, base - 120 * size)
    ctx.line_to(x + 12 * size, base)
    ctx.close_path()
    inked(ctx, (0.4, 0.28, 0.2), 3, (0, 0))
    blobs = [(x + rand.uniform(-90, 90) * size, base - (150 + rand.uniform(-50, 70)) * size, rand.uniform(45, 75) * size)
             for _ in range(9)]
    canopy(ctx, blobs, (0.22, 0.48, 0.2))


@lru_cache(maxsize=None)
def backdrop():
    """The rowhouses round the circle, the elms, the lawn and the fountain's plaza."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    rand = random.Random(1882)
    x = -30
    while x < W + 30:
        w = rand.randint(96, 150)
        house(ctx, rand, x, w, rand.randint(200, 262), 450)
        x += w
    ctx.rectangle(0, 430, W, H - 430)                           # the lawn
    g = cairo.LinearGradient(0, 430, 0, H)
    g.add_color_stop_rgb(0, *mix(LAWN, (0.2, 0.4, 0.15), 0.3))
    g.add_color_stop_rgb(1, LAWN[0], LAWN[1], LAWN[2])
    ctx.set_source(g)
    ctx.fill()
    for x, size in ((40, 1.25), (250, 1.0), (1030, 1.0), (1240, 1.3)):
        tree(ctx, rand, x, 470, size)
    for x in range(380, 900, 46):                               # hedges behind the plaza
        ctx.new_sub_path()
        ctx.arc(x, 452, 26, 0, TAU)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(8)
    ctx.stroke_preserve()
    ctx.set_source_rgb(0.25, 0.5, 0.2)
    ctx.fill()
    ctx.save()                                                  # the plaza, and its joints
    ctx.translate(CX, 575)
    ctx.scale(1, 0.26)
    ctx.arc(0, 0, 560, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*PAVING)
    ctx.fill_preserve()
    ctx.set_source_rgb(*mix(PAVING, INK, 0.4))
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.save()
    ctx.translate(CX, 575)
    ctx.scale(1, 0.26)
    for i in range(24):
        a = i * TAU / 24
        ctx.move_to(math.cos(a) * 360, math.sin(a) * 360)
        ctx.line_to(math.cos(a) * 556, math.sin(a) * 556)
    for r in (420, 490):
        ctx.new_sub_path()
        ctx.arc(0, 0, r, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(*mix(PAVING, INK, 0.3), 0.5)
    ctx.set_line_width(1.5)
    ctx.stroke()
    return surface


# ---------------------------------------------------------------- the fountain

def ellipse(ctx, cx, cy, rx, ry):
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(rx, ry)
    ctx.new_sub_path()
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()


def front(cx, cy, rx, ry, x):
    """y on the front half of an ellipse, at x."""
    u = clamp((x - cx) / rx, -1, 1)
    return cy + ry * math.sqrt(1 - u * u)


def pool(ctx, t):
    ellipse(ctx, CX, POOL_Y + RIM_H, POOL_RX, POOL_RY)          # the rim's face
    ctx.rectangle(CX - POOL_RX, POOL_Y, 2 * POOL_RX, RIM_H)
    ctx.set_source_rgb(*mix(MARBLE, INK, 0.2))
    ctx.fill()
    ellipse(ctx, CX, POOL_Y + RIM_H, POOL_RX, POOL_RY)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    ellipse(ctx, CX, POOL_Y, POOL_RX, POOL_RY)                  # the rim's top
    ctx.set_source_rgb(*MARBLE)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.stroke()
    ellipse(ctx, CX, POOL_Y, POOL_RX - 18, POOL_RY - 8)         # the water
    g = cairo.LinearGradient(0, POOL_Y - POOL_RY, 0, POOL_Y + POOL_RY)
    g.add_color_stop_rgb(0, *mix(WATER, INK, 0.35))
    g.add_color_stop_rgb(1, *mix(WATER, WHITE, 0.25))
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.save()
    ctx.clip()
    for k in range(4):                                          # rings spreading from the falling water
        r = ((t * 0.6 + k / 4) % 1)
        ellipse(ctx, CX, POOL_Y + 4, 200 + 130 * r, 34 + 26 * r)
        ctx.set_source_rgba(1, 1, 1, 0.35 * (1 - r))
        ctx.set_line_width(2.5)
        ctx.stroke()
    ctx.restore()


def figure(ctx, x, base, height, shade):
    """One of the shaft's three draped figures, in relief."""
    w = height * 0.36
    ctx.move_to(x - w * 0.55, base)
    ctx.curve_to(x - w * 0.6, base - height * 0.5, x - w * 0.42, base - height * 0.72, x - w * 0.3, base - height * 0.8)
    ctx.line_to(x + w * 0.3, base - height * 0.8)
    ctx.curve_to(x + w * 0.42, base - height * 0.72, x + w * 0.6, base - height * 0.5, x + w * 0.55, base)
    ctx.close_path()
    g = cairo.LinearGradient(x - w, 0, x + w, 0)
    g.add_color_stop_rgb(0, *mix(MARBLE, INK, 0.12 + shade))
    g.add_color_stop_rgb(0.4, *mix(MARBLE, WHITE, 0.3 - shade))
    g.add_color_stop_rgb(1, *mix(MARBLE, INK, 0.25 + shade))
    inked(ctx, g, 3, (0, 0))
    ctx.arc(x, base - height * 0.88, height * 0.1, 0, TAU)
    inked(ctx, mix(MARBLE, INK, 0.05 + shade), 3, (0, 0))
    ctx.set_source_rgba(*INK, 0.3)
    ctx.set_line_width(1.5)
    for k in (-1, 0, 1):                                         # the drapery's folds
        ctx.move_to(x + k * w * 0.18, base - height * 0.74)
        ctx.curve_to(x + k * w * 0.3, base - height * 0.5, x + k * w * 0.2, base - height * 0.25, x + k * w * 0.32, base)
    ctx.stroke()


def shaft(ctx):
    ctx.rectangle(CX - 62, POOL_Y - 34, 124, 36)                # the plinth
    inked(ctx, mix(MARBLE, INK, 0.08), 3, (0, 0))
    ctx.rectangle(CX - 34, BOWL_Y + 40, 68, POOL_Y - BOWL_Y - 70)
    inked(ctx, mix(MARBLE, INK, 0.15), 3, (0, 0))
    figure(ctx, CX - 48, POOL_Y - 32, 96, 0.18)
    figure(ctx, CX + 48, POOL_Y - 32, 96, 0.18)
    figure(ctx, CX, POOL_Y - 30, 108, 0.0)


def bowl(ctx, t):
    ctx.move_to(CX - BOWL_RX, BOWL_Y)                           # the bowl's underside
    ctx.curve_to(CX - BOWL_RX + 20, BOWL_Y + 44, CX - 70, BOWL_Y + 58, CX - 30, BOWL_Y + 62)
    ctx.line_to(CX + 30, BOWL_Y + 62)
    ctx.curve_to(CX + 70, BOWL_Y + 58, CX + BOWL_RX - 20, BOWL_Y + 44, CX + BOWL_RX, BOWL_Y)
    ctx.close_path()
    g = cairo.LinearGradient(0, BOWL_Y, 0, BOWL_Y + 62)
    g.add_color_stop_rgb(0, *MARBLE)
    g.add_color_stop_rgb(1, *mix(MARBLE, INK, 0.35))
    inked(ctx, g, 4, (0, 0))
    ellipse(ctx, CX, BOWL_Y, BOWL_RX, BOWL_RY)
    inked(ctx, MARBLE, 4, (0, 0))
    ellipse(ctx, CX, BOWL_Y - 1, BOWL_RX - 12, BOWL_RY - 6)
    ctx.set_source_rgb(*mix(WATER, WHITE, 0.2))
    ctx.fill()
    ctx.rectangle(CX - 8, BOWL_Y - 18, 16, 16)                  # the finial the jet leaves from
    inked(ctx, MARBLE, 3, (0, 0))


def curtain(ctx, t):
    """The water falling from the bowl's rim all round into the pool: a sheet, streaks
    running down it, foam where it lands."""
    xs = [CX - BOWL_RX + 6 + i * (2 * BOWL_RX - 12) / 40 for i in range(41)]
    top = [front(CX, BOWL_Y, BOWL_RX, BOWL_RY, x) + 2 for x in xs]
    bottom = [front(CX, POOL_Y, POOL_RX - 60, POOL_RY - 22, x) for x in xs]
    ctx.move_to(xs[0], top[0])
    for x, y in zip(xs, top):
        ctx.line_to(x, y)
    for x, y in zip(reversed(xs), reversed(bottom)):
        ctx.line_to(x, y)
    ctx.close_path()
    g = cairo.LinearGradient(0, BOWL_Y, 0, POOL_Y)
    g.add_color_stop_rgba(0, 0.9, 0.97, 1, 0.5)
    g.add_color_stop_rgba(1, 0.85, 0.95, 1, 0.22)
    ctx.set_source(g)
    ctx.fill()
    ctx.set_line_width(2)
    for k in range(3):
        for i in range(k, len(xs), 3):
            ctx.move_to(xs[i], top[i])
            ctx.line_to(xs[i], bottom[i])
        ctx.set_dash([16 + 6 * k, 22], -(t * 320 + k * 13))
        ctx.set_source_rgba(1, 1, 1, 0.5)
        ctx.stroke()
    ctx.set_dash([])
    rand = random.Random(int(t * 30))
    for x, y in zip(xs, bottom):
        ctx.new_sub_path()
        ctx.arc(x + rand.uniform(-3, 3), y - 2, rand.uniform(4, 9), 0, TAU)
    ctx.set_source_rgba(1, 1, 1, 0.75)
    ctx.fill()


SPURTS = OPEN_SPURTS + CLOSED_SPURTS


def jet_height(t):
    h = 26 + 4 * math.sin(t * 9)
    for at, height in SPURTS:
        if t >= at:
            rise = ease_out(span(t, at, at + 0.12))
            fall = ease_in_out(span(t, at + 0.12, at + (1.0 if at == SPURTS[-1][0] else 0.5)))
            h = max(h, 26 + height * rise * (1 - fall))
    return h


def jet(ctx, t):
    top = BOWL_Y - 18
    h = jet_height(t)
    halo = cairo.RadialGradient(CX, top - h * 0.6, 0, CX, top - h * 0.6, 26 + h * 0.4)
    halo.add_color_stop_rgba(0, 1, 1, 1, 0.35 * clamp((h - 30) / 80))
    halo.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(halo)
    ctx.paint()
    ctx.move_to(CX - 10, top)
    ctx.curve_to(CX - 8, top - h * 0.6, CX - 5, top - h * 0.9, CX, top - h - 6)
    ctx.curve_to(CX + 5, top - h * 0.9, CX + 8, top - h * 0.6, CX + 10, top)
    ctx.close_path()
    g = cairo.LinearGradient(0, top - h, 0, top)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.95)
    g.add_color_stop_rgba(1, 0.8, 0.93, 1, 0.75)
    ctx.set_source(g)
    ctx.fill()
    # Each spurt's crown of drops, falling back into the bowl.
    for k, (at, height) in enumerate(SPURTS):
        tau = t - at - 0.1
        if tau <= 0 or tau > 1.4:
            continue
        rand = random.Random(k * 31 + 7)
        v0 = math.sqrt(2 * GRAVITY * height)
        for _ in range(34):
            vx = rand.uniform(-110, 110)
            vy = -v0 * rand.uniform(0.75, 1.0)
            x = CX + vx * tau
            y = top + vy * tau + 0.5 * GRAVITY * tau * tau
            if y > BOWL_Y + 4:
                continue
            ctx.new_sub_path()
            ctx.arc(x, y, rand.uniform(2.5, 4.5), 0, TAU)
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.fill()


def fountain(ctx, t):
    pool(ctx, t)
    shaft(ctx)
    bowl(ctx, t)
    jet(ctx, t)
    curtain(ctx, t)


# ---------------------------------------------------------------- the chess table and the bench

BOARD = ((152, 612), (318, 612), (346, 664), (124, 664))       # the inlaid board's corners


def board_point(u, v):
    """A point on the board, u across, v towards us, both 0..8."""
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = BOARD
    a = (x0 + (x1 - x0) * u / 8, y0 + (y1 - y0) * u / 8)
    b = (x3 + (x2 - x3) * u / 8, y3 + (y2 - y3) * u / 8)
    return a[0] + (b[0] - a[0]) * v / 8, a[1] + (b[1] - a[1]) * v / 8


@lru_cache(maxsize=None)
def table_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    for sx, sy in ((50, 700), (420, 706)):                      # the stools
        ellipse(ctx, sx, sy, 50, 16)
        inked(ctx, (0.6, 0.58, 0.55), 3, (4, 4))
    ctx.rectangle(205, 650, 60, 80)                              # the pedestal
    inked(ctx, (0.55, 0.53, 0.5), 3, (0, 0))
    ellipse(ctx, 235, 648, 172, 50)                             # the top, its edge, the board
    ctx.rectangle(63, 638, 344, 16)
    ellipse(ctx, 235, 654, 172, 50)
    ctx.set_source_rgb(0.5, 0.48, 0.46)
    ctx.fill()
    ellipse(ctx, 235, 638, 172, 50)
    inked(ctx, (0.72, 0.7, 0.67), 4, (0, 0))
    for v in range(8):
        for u in range(8):
            corners = [board_point(u, v), board_point(u + 1, v), board_point(u + 1, v + 1), board_point(u, v + 1)]
            ctx.move_to(*corners[0])
            for c in corners[1:]:
                ctx.line_to(*c)
            ctx.close_path()
            ctx.set_source_rgb(*((0.93, 0.9, 0.82) if (u + v) % 2 == 0 else (0.25, 0.22, 0.22)))
            ctx.fill()
    ctx.move_to(*BOARD[0])
    for c in BOARD[1:]:
        ctx.line_to(*c)
    ctx.close_path()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(3)
    ctx.stroke()
    return surface


PIECES = (('pawn', 1, 1, 'b'), ('pawn', 2, 2, 'b'), ('king', 4, 0.5, 'b'), ('pawn', 5, 1, 'b'), ('rook', 0.5, 0.5, 'b'),
          ('pawn', 3, 5, 'w'), ('king', 3.5, 7.4, 'w'), ('pawn', 5, 6, 'w'), ('rook', 7.5, 7.5, 'w'))
KNIGHT_FROM, KNIGHT_TO = (6.5, 7.5), (5.5, 5.5)


def piece(ctx, kind, x, y, side):
    fill = (0.97, 0.95, 0.9) if side == 'w' else (0.16, 0.14, 0.15)
    h = {'pawn': 18, 'rook': 22, 'king': 30, 'knight': 24}[kind]
    ellipse(ctx, x, y, 8, 3)
    ctx.move_to(x - 7, y)
    ctx.line_to(x - 4, y - h * 0.6)
    ctx.line_to(x + 4, y - h * 0.6)
    ctx.line_to(x + 7, y)
    ctx.close_path()
    if kind == 'knight':
        ctx.move_to(x - 5, y - h * 0.55)
        ctx.line_to(x - 6, y - h * 0.9)
        ctx.line_to(x + 1, y - h * 1.05)
        ctx.line_to(x + 8, y - h * 0.8)
        ctx.line_to(x + 4, y - h * 0.7)
        ctx.close_path()
    else:
        ctx.new_sub_path()
        ctx.arc(x, y - h * 0.72, 5 if kind != 'rook' else 6, 0, TAU)
    if kind == 'king':
        ctx.rectangle(x - 1.5, y - h - 6, 3, 9)
        ctx.rectangle(x - 4, y - h - 3, 8, 3)
    inked(ctx, fill, 2, (2, 2))


def chess(ctx, t):
    ctx.set_source_surface(table_surface(), 0, 0)
    ctx.paint()
    for kind, u, v, side in sorted(PIECES, key=lambda p: p[2]):
        piece(ctx, kind, *board_point(u, v), side)
    p = ease_in_out(span(t, *KNIGHT))
    u = KNIGHT_FROM[0] + (KNIGHT_TO[0] - KNIGHT_FROM[0]) * p
    v = KNIGHT_FROM[1] + (KNIGHT_TO[1] - KNIGHT_FROM[1]) * p
    x, y = board_point(u, v)
    piece(ctx, 'knight', x, y - 34 * math.sin(math.pi * p), 'w')


@lru_cache(maxsize=None)
def bench_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    x0, x1, seat = 1010, 1300, 640
    for lx in (x0 + 18, x1 - 30):
        ctx.rectangle(lx, seat - 8, 10, 74)
        inked(ctx, (0.12, 0.12, 0.13), 2, (3, 3))
    for i in range(3):                                          # the back
        rounded_rect(ctx, x0, seat - 92 + i * 22, x1 - x0, 15, 4)
        inked(ctx, (0.18, 0.38, 0.24), 3, (4, 4))
    for i in range(2):                                          # the seat
        rounded_rect(ctx, x0 - 6 + i * 6, seat - 14 + i * 16, x1 - x0, 13, 4)
        inked(ctx, (0.2, 0.42, 0.26), 3, (4, 4))
    return surface


# ---------------------------------------------------------------- the pigeons

FLOCK = ((440, 668, 1.0, 1, 0.0), (530, 706, 1.15, -1, 0.2), (770, 674, 1.0, -1, 0.35), (868, 712, 1.2, 1, 0.1),
         (965, 662, 0.95, 1, 0.42), (1120, 650, 0.9, -1, 0.27))


def pigeon(ctx, t, x, y, s, facing, peck, flap=None):
    """A pigeon, feet at (x, y): grey, with its green-and-purple neck. flap (a phase) when flying."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s * facing, s)
    if flap is None:
        for fx in (-4, 4):                                      # feet
            ctx.move_to(fx, -12)
            ctx.line_to(fx, 0)
        ctx.set_source_rgb(0.9, 0.45, 0.5)
        ctx.set_line_width(3)
        ctx.stroke()
    else:
        ctx.rotate(-0.35)
    ctx.move_to(-38, -26)                                        # tail
    ctx.line_to(-22, -18)
    ctx.line_to(-22, -30)
    ctx.close_path()
    inked(ctx, (0.3, 0.32, 0.38), 2.5, (0, 0))
    ctx.save()                                                   # body
    ctx.translate(-2, -24)
    ctx.scale(26, 15)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, (0.58, 0.6, 0.66), 2.5, (0, 0))
    if flap is None:                                             # the folded wing and its bars
        ctx.save()
        ctx.translate(-6, -26)
        ctx.scale(17, 9)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        inked(ctx, (0.5, 0.52, 0.58), 2, (0, 0))
        for bx in (-10, -3):
            ctx.move_to(bx, -30)
            ctx.line_to(bx + 3, -21)
        ctx.set_source_rgb(0.18, 0.18, 0.22)
        ctx.set_line_width(2.5)
        ctx.stroke()
    else:
        for side in (-1, 1):                                     # both wings, beating
            lift = math.sin(flap + (0.4 if side < 0 else 0)) * (0.55 + 0.45 * side)
            tip = (-24, -30 - 44 * lift)
            ctx.move_to(-12, -27)
            ctx.curve_to(-20, -30 - 20 * lift, tip[0] - 8, tip[1] + 6, *tip)
            ctx.curve_to(tip[0] + 10, tip[1] + 10, 2, -32 - 18 * lift, 6, -29)
            ctx.close_path()
            inked(ctx, (0.5, 0.52, 0.58) if side > 0 else (0.4, 0.42, 0.48), 2, (0, 0))
    dip = peck * 14
    ctx.save()
    ctx.translate(16, -30 + dip)
    ctx.rotate(0.5 * peck)
    neck = cairo.LinearGradient(-8, 0, 8, 10)
    neck.add_color_stop_rgb(0, 0.36, 0.62, 0.42)
    neck.add_color_stop_rgb(1, 0.55, 0.36, 0.62)
    ctx.arc(0, 0, 10, 0, TAU)
    inked(ctx, neck, 2.5, (0, 0))
    ctx.arc(6, -10, 8, 0, TAU)                                    # head
    inked(ctx, (0.5, 0.52, 0.58), 2.5, (0, 0))
    ctx.move_to(13, -10)
    ctx.line_to(20, -8)
    ctx.line_to(13, -6)
    ctx.close_path()
    ctx.set_source_rgb(0.25, 0.22, 0.22)
    ctx.fill()
    ctx.arc(8, -12, 2.2, 0, TAU)
    ctx.set_source_rgb(0.95, 0.5, 0.1)
    ctx.fill()
    ctx.restore()
    ctx.restore()


def pigeons(ctx, t):
    for i, (x, y, s, facing, phase) in enumerate(FLOCK):
        go = TAKE_OFF + 0.07 * i
        if t < go:
            beat = (t + phase) % 1.0                              # a peck a second, each to its own time
            peck = math.sin(math.pi * span(beat, 0.0, 0.25))
            walk = 6 * math.sin(TAU * (t + phase) * 0.3) * facing
            pigeon(ctx, t, x + walk, y, s, facing, peck)
            continue
        tau = t - go
        dx = facing * (260 * tau + 120 * tau * tau)
        dy = -(140 * tau + 380 * tau * tau)
        if y + dy < -80:
            continue
        pigeon(ctx, t, x + dx, y + dy, s * (1 + 0.5 * tau), facing, 0.0, flap=tau * TAU * 7 + i)


# ---------------------------------------------------------------- the frame

def sparkle(ctx, t):
    p = span(t, BUTTON, BUTTON + 0.6)
    if 0 < p < 1:
        for i, (x, y) in enumerate(((CX - 150, POOL_Y - 10), (CX + 120, POOL_Y + 6), (CX - 40, BOWL_Y - 4),
                                    (CX + 90, BOWL_Y - 10), (CX, BOWL_Y - 160))):
            q = span(p, i * 0.08, i * 0.08 + 0.6)
            if 0 < q < 1:
                glint(ctx, x, y, 18 * math.sin(math.pi * q), q * 3, math.sin(math.pi * q))


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.save()
    camera(ctx, t)
    sky(ctx, t)
    ctx.set_source_surface(backdrop(), 0, 0)
    ctx.paint()
    fountain(ctx, t)
    ctx.set_source_surface(bench_surface(), 0, 0)
    ctx.paint()
    chess(ctx, t)
    pigeons(ctx, t)
    sparkle(ctx, t)
    ctx.restore()
    neighborhood.tag(ctx, t, 'Dupont Circle', 'NORTHWEST  ·  WASHINGTON', *TAG)
    neighborhood.lockup(ctx, t, LOCKUP, 168)
    vignette(ctx, 0.35)
    ctx.set_source_rgba(1.0, 0.85, 0.55, 0.05)
    ctx.paint()
    grain(ctx, frame, 0.4)
    opening = 1 - ease_out(span(t, 0.0, 0.4))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    fade = span(t, *FADE)
    if fade > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(fade))
        ctx.paint()
