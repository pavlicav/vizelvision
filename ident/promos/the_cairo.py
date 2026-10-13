"""From atop The Cairo: VizelVision's home, 1615 Q Street's twelve-storey apartment house
(Thomas Franklin Schneider, 1894), at dusk, in the neighbourhood idents' inked style.

We start at the door: the wide, low, deep arch in its carved Moorish band, gas lamps
either side, and the two stone elephant heads at its corners with their trunks
interlocked. On the open logo the elephants lift their trunks and trumpet it, one note
each, then both. The camera tilts up the rock-faced limestone and the brown brick, past
the bays and the balconies on their winged gargoyles, the windows lighting a floor at a
time as we pass, a ruler counting the feet beside it, the dashed line of the 90 feet
the law has allowed on a residential street since 1899, and on up to 164 feet and the
projecting cornice with its griffins. Above the roof garden, VizelVision's mast; beyond,
the city at dusk, held low by the law this building caused, the Monument and the Capitol
far off. On the closed logo the mast sends out its rings and the wordmark drops in: SO
TALL THEY CHANGED THE LAW.

Athena: "From atop The Cairo, this is Vizzle Vision."
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (INK, TAU, W, H, WHITE, YELLOW, back_out, clamp, ease_in, ease_in_out, ease_out, font, glint,  # noqa: F401
                    grain, inked, inked_stroke, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'the-cairo'
NAME = 'From atop The Cairo'
KIND = 'ident'
ORDER = 16
DESCRIPTION = ("VizelVision's home, The Cairo (1894) on Q Street, at dusk: its stone elephants trumpet the logo, "
               'and we rise twelve storeys past the 90-foot line to the roof and the mast, the city held low beyond. '
               '"So tall they changed the law." Athena.')
DURATION = 10.0
STILL_AT = 8.6
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
TRUNKS_UP = (0.55, 0.95)                       # the elephants let go and lift their trunks
TRUMPETS = (1.0, 1.25, 1.5, 2.0)               # the open logo: left, right, left, both
RISE = (2.35, 5.75)                            # the tilt up the facade
TAG = (5.6, 6.8)                               # the place tag, gone before the wordmark
LIMIT_PASSES = 4.0                             # the 90-foot line crosses mid-frame (the music's gavel)
LIFT = 7.0                                     # the closed logo: the mast's rings, the wordmark
RINGS = (7.0, 7.25, 7.5, 8.0)
LAW = (7.9, 8.4)                               # SO TALL THEY CHANGED THE LAW
FADE = (9.25, 9.6)

PX_PER_FT = 12.0
STREET = 652                                   # street level on screen before the tilt
HEIGHT_FT = 164
FLOORS = 12
GROUND_FT, FLOOR_FT = 18.0, 12.5               # the ground floor's height, then each floor's
CORNICE_FT = GROUND_FT + 11 * FLOOR_FT         # where the cornice starts (155.5)
FACADE = (300, 980)                            # the front's left and right edges
LIMESTONE = (0.8, 0.76, 0.66)
BRICK = (0.5, 0.29, 0.19)
LIMIT_FT = 90
CAMERA_END = HEIGHT_FT * PX_PER_FT - (STREET - 430)   # the roof line ends at y = 430


# ---------------------------------------------------------------- the camera

def camera(t):
    """How far the camera has risen, in px."""
    return CAMERA_END * ease_in_out(span(t, *RISE))


def sy(ft, cam):
    """Screen y of a height in feet."""
    return STREET - ft * PX_PER_FT + cam


def floor_base(k):
    """The height in feet where floor k (0 = the ground floor) starts."""
    return 0.0 if k == 0 else GROUND_FT + (k - 1) * FLOOR_FT


# ---------------------------------------------------------------- the sky, the city, the neighbours

def sky(ctx, t, cam):
    g = cairo.LinearGradient(0, -400 + cam * 0.3, 0, H + cam * 0.3)
    g.add_color_stop_rgb(0, 0.09, 0.08, 0.3)
    g.add_color_stop_rgb(0.5, 0.35, 0.22, 0.5)
    g.add_color_stop_rgb(0.8, 0.95, 0.5, 0.45)
    g.add_color_stop_rgb(1, 1.0, 0.75, 0.45)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(1894)
    for _ in range(50):
        x, y = rand.uniform(0, W), rand.uniform(-300, 300) + cam * 0.3
        ctx.arc(x, y, rand.uniform(0.6, 1.4), 0, TAU)
        ctx.set_source_rgba(1, 1, 1, rand.uniform(0.2, 0.7) * clamp((360 - y) / 300))
        ctx.fill()


def city(ctx, cam):
    """The skyline far off, flat-topped under the law, the Monument and the Capitol above it;
    it rises into view slowly (parallax) as the camera climbs."""
    horizon = STREET - 70 + cam * 0.22 - CAMERA_END * 0.22 + 120 * (1 - cam / CAMERA_END)
    horizon = min(horizon, STREET + 40)
    rand = random.Random(19)
    ctx.move_to(-10, H + 10)
    x = -10
    while x < W + 10:
        top = horizon - rand.uniform(14, 38)
        ctx.line_to(x, top)
        x += rand.uniform(26, 70)
        ctx.line_to(x, top)
    ctx.line_to(W + 10, H + 10)
    ctx.close_path()
    ctx.set_source_rgb(0.3, 0.2, 0.38)
    ctx.fill()
    rand = random.Random(20)
    for _ in range(70):                                   # lit windows far off
        ctx.rectangle(rand.uniform(0, W), horizon - rand.uniform(4, 30), 2.5, 2.5)
        ctx.set_source_rgba(1, 0.85, 0.5, 0.7)
        ctx.fill()
    mx, top = 1150, horizon - 120                         # the Monument
    ctx.move_to(mx - 8, horizon - 20)
    ctx.line_to(mx - 5, top + 9)
    ctx.line_to(mx, top)
    ctx.line_to(mx + 5, top + 9)
    ctx.line_to(mx + 8, horizon - 20)
    ctx.close_path()
    ctx.set_source_rgb(0.85, 0.72, 0.7)
    ctx.fill()
    ctx.arc(mx, top + 10, 1.6, 0, TAU)
    ctx.set_source_rgb(1, 0.15, 0.15)
    ctx.fill()
    cx, base = 1030, horizon - 30                         # the Capitol's dome
    ctx.move_to(cx - 26, base)
    ctx.curve_to(cx - 24, base - 30, cx - 8, base - 40, cx, base - 40)
    ctx.curve_to(cx + 8, base - 40, cx + 24, base - 30, cx + 26, base)
    ctx.close_path()
    ctx.rectangle(cx - 2, base - 50, 4, 12)
    ctx.set_source_rgb(0.85, 0.75, 0.75)
    ctx.fill()


def rowhouses(ctx, cam):
    """Q Street's rowhouses either side: three and four storeys, bay fronts, a turret."""
    colours = ((0.62, 0.3, 0.22), (0.78, 0.66, 0.42), (0.5, 0.36, 0.5), (0.7, 0.42, 0.28))
    for side, edges in ((-1, (0, 120, 300)), (1, (980, 1130, 1280))):
        for k, (x0, x1) in enumerate(zip(edges, edges[1:])):
            storeys = (3, 4)[(k + (side > 0)) % 2]
            top = sy(storeys * 12 + 6, cam)
            ctx.rectangle(x0, top, x1 - x0, STREET - top + cam + 40)
            inked(ctx, colours[(k * 2 + (side > 0)) % 4], 4, (0, 0))
            if (k + (side > 0)) % 2 == 0:                 # a turret
                tx = x0 + (x1 - x0) / 2
                ctx.move_to(tx - 34, top)
                ctx.line_to(tx, top - 60)
                ctx.line_to(tx + 34, top)
                ctx.close_path()
                inked(ctx, (0.3, 0.32, 0.38), 4, (0, 0))
            for s in range(storeys):
                y = sy(s * 12 + 4, cam) - 80
                for wx in (x0 + 26, x0 + (x1 - x0) / 2 - 16, x1 - 58):
                    rounded_rect(ctx, wx, y, 32, 60, 4)
                    inked(ctx, (1, 0.85, 0.5) if (s + k + int(wx)) % 3 else (0.25, 0.25, 0.4), 3, (0, 0))


# ---------------------------------------------------------------- the facade

@lru_cache(maxsize=None)
def brick_pattern():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 64, 24)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(*BRICK)
    ctx.paint()
    ctx.set_source_rgb(*mix(BRICK, (0, 0, 0), 0.25))
    for y in (0, 12):
        ctx.rectangle(0, y, 64, 1.5)
        ctx.fill()
        for x in ((0, 32) if y == 0 else (16, 48)):
            ctx.rectangle(x, y, 1.5, 12)
            ctx.fill()
    pattern = cairo.SurfacePattern(surface)
    pattern.set_extend(cairo.EXTEND_REPEAT)
    return pattern


@lru_cache(maxsize=None)
def stone_blocks():
    rand = random.Random(1615)
    return [(rand.uniform(-6, 6), rand.uniform(0.9, 1.08)) for _ in range(200)]


def window(ctx, x, y, w, h, lit, arched=False):
    if arched:                                            # a Moorish horseshoe arch, for the top floor
        ctx.move_to(x, y + h)
        ctx.line_to(x, y + w * 0.55)
        ctx.arc(x + w / 2, y + w * 0.55, w * 0.58, math.pi - 0.3, 0.3)
        ctx.line_to(x + w, y + h)
        ctx.close_path()
    else:
        ctx.rectangle(x, y, w, h)
    glow = mix((0.18, 0.18, 0.32), (1.0, 0.82, 0.45), lit)
    inked(ctx, glow, 3, (0, 0))
    ctx.set_source_rgba(*INK, 0.7)
    ctx.set_line_width(2)
    ctx.move_to(x + w / 2, y + (w * 0.2 if arched else 0))
    ctx.line_to(x + w / 2, y + h)
    ctx.move_to(x, y + h * 0.45)
    ctx.line_to(x + w, y + h * 0.45)
    ctx.stroke()


def lit_level(t, floor, column):
    """A window's light: some lit at dusk already; the rest come on as the camera passes."""
    rand = random.Random(floor * 31 + column)
    if rand.random() < 0.35:
        return 1.0
    passing = floor_base(floor) * PX_PER_FT / CAMERA_END
    at = RISE[0] + (RISE[1] - RISE[0]) * clamp(passing * 0.95 - 0.08) + rand.uniform(0, 0.25)
    return ease_out(span(t, at, at + 0.15))


def gargoyle(ctx, x, y, side):
    """A spread-winged gargoyle under a balcony's corner."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(side, 1)
    ctx.move_to(0, 0)
    ctx.curve_to(-10, 6, -26, 2, -34, -6)                 # the wing
    ctx.curve_to(-26, 10, -14, 16, -4, 22)
    ctx.curve_to(2, 16, 4, 8, 0, 0)
    inked(ctx, mix(LIMESTONE, (0, 0, 0), 0.15), 3, (0, 0))
    ctx.arc(2, 20, 6, 0, TAU)                             # the head
    inked(ctx, mix(LIMESTONE, (0, 0, 0), 0.2), 3, (0, 0))
    ctx.restore()


def facade(ctx, t, cam):
    left, right = FACADE
    top_y, base_y = sy(HEIGHT_FT - 6, cam), sy(0, cam)
    stone_top = sy(floor_base(2), cam)
    ctx.rectangle(left, top_y, right - left, stone_top - top_y)
    bricks = brick_pattern()
    bricks.set_matrix(cairo.Matrix(y0=-(cam % 24)))            # the courses move with the building
    ctx.set_source(bricks)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.rectangle(left, stone_top, right - left, base_y - stone_top)       # rock-faced limestone below
    ctx.set_source_rgb(*LIMESTONE)
    ctx.fill()
    blocks = stone_blocks()
    i = 0
    for row in range(int((base_y - stone_top) / 30) + 1):
        y = stone_top + row * 30
        x = left + (0 if row % 2 else 34)
        while x < right:
            jitter, shade = blocks[i % len(blocks)]
            i += 1
            ctx.rectangle(x + 2, y + 2, 64, 26)
            ctx.set_source_rgb(*(c * shade for c in LIMESTONE))
            ctx.fill()
            x += 68 + jitter
    ctx.rectangle(left, stone_top, right - left, base_y - stone_top)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    bays = ((360, 500), (780, 920))                         # two bays projecting, all the way up
    for floor in range(2, FLOORS):
        y0, y1 = sy(floor_base(floor) + FLOOR_FT, cam), sy(floor_base(floor), cam)
        if y1 < -40 or y0 > H + 40:
            continue
        top_floor = floor == FLOORS - 1
        for b, (bx0, bx1) in enumerate(bays):
            ctx.rectangle(bx0 - 10, y0, bx1 - bx0 + 20, y1 - y0)
            ctx.set_source_rgb(*mix(BRICK, (1, 1, 1), 0.08))
            ctx.fill()
            ctx.rectangle(bx0 - 10, y0, 10, y1 - y0)       # the bay's shaded return
            ctx.set_source_rgb(*mix(BRICK, (0, 0, 0), 0.3))
            ctx.fill()
            for c in range(3):
                window(ctx, bx0 + 8 + c * 44, y0 + 30, 34, 90, lit_level(t, floor, b * 10 + c), top_floor)
        for c, wx in enumerate((316, 540, 600, 680, 740, 940)):
            if wx in (600, 680) and floor in (4, 7, 10):
                continue                                   # the balconies' doors are drawn with them
            window(ctx, wx - 6 if wx > 900 else wx, y0 + 30, 28, 90, lit_level(t, floor, 20 + c), top_floor)
        ctx.rectangle(left, y1 - 6, right - left, 6)      # a string course at each floor
        ctx.set_source_rgb(*mix(BRICK, (0, 0, 0), 0.2))
        ctx.fill()
        if floor in (4, 7, 10):                           # a balcony on its gargoyles, its doors behind
            for dx in (600, 680):
                window(ctx, dx - 4, y0 + 22, 30, 104, lit_level(t, floor, 40 + dx), False)
            by = y1 - 18
            ctx.rectangle(570, by - 46, 170, 8)
            ctx.rectangle(570, by, 170, 12)
            inked(ctx, mix(LIMESTONE, (0, 0, 0), 0.1), 3, (0, 0))
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(2.5)
            for k in range(14):
                ctx.move_to(576 + k * 12, by - 38)
                ctx.line_to(576 + k * 12, by)
            ctx.stroke()
            gargoyle(ctx, 572, by + 12, -1)
            gargoyle(ctx, 738, by + 12, 1)
        if floor == 3:                                    # a carved band above the stone
            ctx.rectangle(left, y1 - 16, right - left, 12)
            ctx.set_source_rgb(*mix(LIMESTONE, (0, 0, 0), 0.08))
            ctx.fill()
            for k in range(int((right - left) / 24)):
                ctx.move_to(left + 12 + k * 24, y1 - 15)
                ctx.line_to(left + 18 + k * 24, y1 - 10)
                ctx.line_to(left + 12 + k * 24, y1 - 5)
                ctx.line_to(left + 6 + k * 24, y1 - 10)
                ctx.close_path()
            ctx.set_source_rgba(*INK, 0.5)
            ctx.fill()
    for floor in (0, 1):                                  # the limestone floors' windows
        y0, y1 = sy(floor_base(floor + 1) if floor else GROUND_FT, cam), sy(floor_base(floor), cam)
        for c, wx in enumerate((330, 420, 820, 910)):
            window(ctx, wx, y0 + (40 if floor == 0 else 26), 40, 100 if floor == 0 else 86,
                   lit_level(t, floor, c), False)
    cornice(ctx, t, cam)


def cornice(ctx, t, cam):
    """The perilously projecting cap: a deep cornice on brackets, griffins at its corners."""
    left, right = FACADE
    y = sy(CORNICE_FT + 1, cam)
    if y > H + 80:
        return
    ctx.rectangle(left - 10, y - 30, right - left + 20, 30)          # the frieze
    ctx.set_source_rgb(*mix(LIMESTONE, (0, 0, 0), 0.05))
    ctx.fill()
    for k in range(int((right - left) / 30) + 1):
        ctx.arc(left + 10 + k * 30, y - 15, 7, 0, TAU)
    ctx.set_source_rgba(*INK, 0.35)
    ctx.fill()
    for k in range(int((right - left + 60) / 40) + 1):                # its brackets
        bx = left - 30 + k * 40
        ctx.move_to(bx, y - 30)
        ctx.line_to(bx + 16, y - 30)
        ctx.line_to(bx + 16, y - 52)
        ctx.curve_to(bx + 8, y - 52, bx, y - 40, bx, y - 30)
        inked(ctx, mix(LIMESTONE, (0, 0, 0), 0.12), 2.5, (0, 0))
    ctx.move_to(left - 60, y - 52)                                   # the cap, projecting
    ctx.line_to(right + 60, y - 52)
    ctx.line_to(right + 40, y - 84)
    ctx.line_to(left - 40, y - 84)
    ctx.close_path()
    inked(ctx, (0.35, 0.3, 0.32), 4, (6, 6))
    for side, gx in ((-1, left - 52), (1, right + 52)):               # griffins staring down
        ctx.save()
        ctx.translate(gx, y - 52)
        ctx.scale(side, 1)
        ctx.move_to(0, 0)
        ctx.curve_to(10, 16, 4, 34, -8, 36)
        ctx.curve_to(-6, 26, -16, 18, -24, 22)
        ctx.curve_to(-20, 8, -10, 0, 0, 0)
        inked(ctx, mix(LIMESTONE, (0, 0, 0), 0.25), 3, (0, 0))
        ctx.move_to(-2, 4)
        ctx.curve_to(8, -14, 22, -16, 30, -30)
        ctx.curve_to(22, -6, 12, 2, -2, 10)
        inked(ctx, mix(LIMESTONE, (0, 0, 0), 0.15), 3, (0, 0))
        ctx.restore()
    roof(ctx, t, y - 84)


def roof(ctx, t, y):
    """The roof garden's railing and planters, and VizelVision's mast."""
    left, right = FACADE
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(2.5)
    ctx.move_to(left - 20, y - 26)
    ctx.line_to(right + 20, y - 26)
    for k in range(int((right - left + 40) / 18) + 1):
        ctx.move_to(left - 20 + k * 18, y - 26)
        ctx.line_to(left - 20 + k * 18, y)
    ctx.stroke()
    for px in (360, 470, 820, 930):                                   # planters and their shrubs
        ctx.rectangle(px - 22, y - 22, 44, 22)
        inked(ctx, (0.55, 0.32, 0.2), 3, (0, 0))
        ctx.arc(px, y - 34, 22, 0, TAU)
        inked(ctx, (0.2, 0.45, 0.25), 3, (0, 0))
    mx, top = 640, y - 230                                            # the mast: a red and white lattice
    ctx.move_to(mx - 22, y)
    ctx.line_to(mx - 4, top)
    ctx.line_to(mx + 4, top)
    ctx.line_to(mx + 22, y)
    ctx.close_path()
    ctx.set_source_rgba(*INK, 0.15)
    ctx.fill()
    for k in range(10):
        a, b = y - k * 23, y - (k + 1) * 23
        wa, wb = 22 - 18 * k / 10, 22 - 18 * (k + 1) / 10
        ctx.move_to(mx - wa, a)
        ctx.line_to(mx + wb, b)
        ctx.move_to(mx + wa, a)
        ctx.line_to(mx - wb, b)
        ctx.set_source_rgb(*((0.9, 0.15, 0.15) if k % 2 else (0.95, 0.95, 0.95)))
        ctx.set_line_width(3)
        ctx.stroke()
    for sx in (-1, 1):
        ctx.move_to(mx + sx * 22, y)
        ctx.line_to(mx + sx * 4, top)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(3)
    ctx.stroke()
    rounded_rect(ctx, mx - 30, y - 150, 60, 44, 10)                   # its little TV badge
    inked(ctx, (0.0, 0.8, 0.74), 3, (3, 3))
    font(ctx, 'URW Gothic', 30)
    ctx.move_to(mx - 11, y - 117)
    ctx.text_path('V')
    inked(ctx, (1, 0.2, 0.58), 2, (0, 0))
    blink = 0.5 + 0.5 * math.sin(t * 4)
    ctx.arc(mx, top - 4, 6, 0, TAU)
    ctx.set_source_rgb(1, 0.15 + 0.2 * blink, 0.15)
    ctx.fill()
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for when in RINGS:                                                # the signal on the closed logo
        p = span(t, when, when + 1.3)
        if 0 < p < 1:
            ctx.arc(mx, top - 4, 30 + 520 * ease_out(p), 0, TAU)
            ctx.set_source_rgba(0.5, 0.9, 1.0, 0.6 * (1 - p))
            ctx.set_line_width(5 * (1 - p) + 1)
            ctx.stroke()
    g = cairo.RadialGradient(mx, top - 4, 0, mx, top - 4, 40)
    g.add_color_stop_rgba(0, 1, 0.3, 0.3, 0.6 * blink)
    g.add_color_stop_rgba(1, 1, 0.3, 0.3, 0)
    ctx.set_source(g)
    ctx.arc(mx, top - 4, 40, 0, TAU)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the entrance and its elephants

def entrance(ctx, t, cam):
    base = sy(0, cam)
    if base - 300 > H:
        return
    cx = 640
    band = (cx - 170, base - 260, 340, 260)
    x, y, w, h = band
    ctx.rectangle(x, y, w, h)                                         # the carved band
    inked(ctx, mix(LIMESTONE, (1, 1, 1), 0.1), 4, (0, 0))
    ctx.save()
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.rectangle(x + 6, y + 6, w - 12, h - 6)
    ctx.rectangle(x + 30, y + 30, w - 60, h - 30)
    ctx.clip()
    for row in range(int(h / 24) + 1):                               # its Moorish lattice of eight-point stars
        for col in range(int(w / 24) + 1):
            sx_, sy_ = x + 12 + col * 24, y + 12 + row * 24
            for rot in (0, math.pi / 4):
                ctx.save()
                ctx.translate(sx_, sy_)
                ctx.rotate(rot)
                ctx.rectangle(-6, -6, 12, 12)
                ctx.restore()
    ctx.set_source_rgba(*INK, 0.35)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.restore()
    ax0, ax1, spring = cx - 115, cx + 115, base - 80                  # the arch: wide, low and deep
    ctx.move_to(ax0, base)
    ctx.line_to(ax0, spring)
    ctx.curve_to(ax0, spring - 110, ax1, spring - 110, ax1, spring)
    ctx.line_to(ax1, base)
    ctx.close_path()
    g = cairo.LinearGradient(0, spring - 90, 0, base)
    g.add_color_stop_rgb(0, 0.25, 0.14, 0.1)
    g.add_color_stop_rgb(1, 0.85, 0.6, 0.3)
    inked(ctx, g, 5, (0, 0))
    ctx.rectangle(cx - 60, base - 120, 120, 120)                      # the lobby doors, lit
    inked(ctx, (1.0, 0.82, 0.5), 3, (0, 0))
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(3)
    ctx.move_to(cx, base - 120)
    ctx.line_to(cx, base)
    ctx.stroke()
    font(ctx, 'C059', 22)
    ctx.new_path()
    text_path(ctx, 'THE CAIRO', cx, y + 22, tracking=6, align='center')
    ctx.set_source_rgb(*INK)
    ctx.fill()
    for side in (-1, 1):                                              # gas lamps
        lx = cx + side * 205
        ctx.move_to(lx, base)
        ctx.line_to(lx, base - 120)
        inked_stroke(ctx, INK, 5, (0, 0))
        rounded_rect(ctx, lx - 14, base - 156, 28, 38, 6)
        inked(ctx, (1, 0.9, 0.55), 3, (0, 0))
        g = cairo.RadialGradient(lx, base - 137, 0, lx, base - 137, 90)
        g.add_color_stop_rgba(0, 1, 0.85, 0.5, 0.45)
        g.add_color_stop_rgba(1, 1, 0.85, 0.5, 0)
        ctx.set_source(g)
        ctx.arc(lx, base - 137, 90, 0, TAU)
        ctx.fill()
    for side in (-1, 1):
        elephant(ctx, t, cx + side * 140, spring - 52, side)
    ctx.rectangle(0, base, W, 60)                                     # the sidewalk
    inked(ctx, (0.55, 0.53, 0.55), 3, (0, 0))
    ctx.rectangle(0, base + 60, W, 200)                               # Q Street
    ctx.set_source_rgb(0.2, 0.2, 0.24)
    ctx.fill()


def trunk_lift(t, side):
    """0 interlocked, 1 raised high and trumpeting."""
    up = ease_in_out(span(t, *TRUNKS_UP)) * 0.55
    for k, when in enumerate(TRUMPETS):
        mine = (k == 3) or (k % 2 == 0) == (side < 0)
        if mine:
            up = max(up, 0.55 + 0.45 * math.sin(math.pi * span(t, when - 0.06, when + 0.22)))
    down = ease_in_out(span(t, 2.3, 2.7))
    return up * (1 - down)


def elephant(ctx, t, x, y, side):
    """A stone elephant's head in profile, facing in towards the arch (side -1 on the left);
    its trunk hangs to meet the other's, or lifts to trumpet."""
    lift = trunk_lift(t, side)
    stone = mix(LIMESTONE, (1, 1, 1), 0.15)
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(-side, 1)                                               # drawn facing left, flipped as needed
    ctx.move_to(14, -40)                                              # the ear, a fan behind the head
    ctx.curve_to(52, -50, 56, 14, 22, 26)
    ctx.close_path()
    inked(ctx, mix(stone, (0, 0, 0), 0.12), 3, (0, 0))
    ctx.arc(0, -8, 30, 0, TAU)                                        # the head
    inked(ctx, stone, 3, (0, 0))
    ctx.arc(-12, -16, 3.5, 0, TAU)                                    # the eye
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.move_to(-14, 10)                                              # a tusk
    ctx.curve_to(-26, 18, -34, 14, -38, 6)
    inked_stroke(ctx, (1, 0.97, 0.9), 5, (0, 0))
    # The trunk: down and curling in to its twin, or up and out, trumpeting.
    hang = ((-24, 6), (-34, 40), (-58, 58), (-60, 40))
    raised = ((-24, -4), (-50, -20), (-58, -56), (-80, -70))
    pts = [(a[0] + (b[0] - a[0]) * lift, a[1] + (b[1] - a[1]) * lift) for a, b in zip(hang, raised)]
    ctx.move_to(*pts[0])
    ctx.curve_to(*pts[1], *pts[2], *pts[3])
    inked_stroke(ctx, stone, 13, (0, 0))
    ctx.restore()
    if lift > 0.6:                                                    # the toot
        for k, when in enumerate(TRUMPETS):
            mine = (k == 3) or (k % 2 == 0) == (side < 0)
            p = span(t, when, when + 0.35)
            if mine and 0 < p < 1:
                tx, ty = x + side * 80, y - 70
                for r in (10, 18, 26):
                    ctx.arc(tx + side * 30 * p, ty - 20 * p, r * (0.6 + p), -0.6 if side > 0 else math.pi - 0.6,
                            0.6 if side > 0 else math.pi + 0.6)
                    ctx.new_sub_path()
                ctx.set_source_rgba(1, 1, 1, 0.8 * (1 - p))
                ctx.set_line_width(3)
                ctx.stroke()


# ---------------------------------------------------------------- the ruler and the law

def ruler(ctx, t, cam):
    """Feet up the right edge, and the 90-foot line across everything."""
    x = 1210
    shown = clamp(span(t, RISE[0] - 0.3, RISE[0])) * (1 - span(t, LIFT - 0.4, LIFT))
    if shown <= 0:
        return
    ctx.save()
    ctx.push_group()
    ctx.set_source_rgb(1, 1, 1)
    ctx.set_line_width(2)
    ctx.move_to(x, sy(0, cam))
    ctx.line_to(x, sy(HEIGHT_FT, cam))
    ctx.stroke()
    for ft in range(0, HEIGHT_FT + 1, 10):
        y = sy(ft, cam)
        if -20 < y < H + 20:
            ctx.move_to(x - (14 if ft % 50 == 0 else 7), y)
            ctx.line_to(x, y)
            ctx.stroke()
            if ft % 50 == 0:
                font(ctx, 'Nimbus Sans', 16)
                ctx.new_path()
                text_path(ctx, f'{ft} FT', x - 18, y + 6, align='right')
                ctx.fill()
    y = sy(HEIGHT_FT, cam)
    font(ctx, 'Nimbus Sans', 18)
    ctx.new_path()
    text_path(ctx, '164 FT', x - 18, y + 6, align='right')
    ctx.fill()
    y = sy(LIMIT_FT, cam)                                             # the law's line
    ctx.set_source_rgb(1, 0.3, 0.3)
    ctx.set_dash([14, 9])
    ctx.set_line_width(3)
    ctx.move_to(0, y)
    ctx.line_to(W, y)
    ctx.stroke()
    ctx.set_dash([])
    rounded_rect(ctx, 34, y - 34, 330, 28, 6)
    ctx.set_source_rgb(1, 0.3, 0.3)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 16)
    ctx.new_path()
    text_path(ctx, '90 FT: THE LIMIT SINCE 1899', 46, y - 14, tracking=1.5)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(shown)
    ctx.restore()


def finale(ctx, t):
    if t < LIFT - 0.05:
        return
    neighborhood.lockup(ctx, t, LIFT, 130, scale=0.62)
    p = span(t, *LAW)
    if p > 0:
        font(ctx, 'Nimbus Sans', 24)
        ctx.new_path()
        text_path(ctx, 'SO TALL THEY CHANGED THE LAW', W / 2, 178, tracking=5, align='center')
        ctx.set_source_rgba(1, 1, 1, ease_out(p))
        ctx.fill()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    cam = camera(t)
    sky(ctx, t, cam)
    city(ctx, cam)
    rowhouses(ctx, cam)
    facade(ctx, t, cam)
    entrance(ctx, t, cam)
    ruler(ctx, t, cam)
    finale(ctx, t)
    neighborhood.tag(ctx, t, 'The Cairo', 'DUPONT CIRCLE · 1894', *TAG)
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.4)
    opening = 1 - ease_out(span(t, 0.0, 0.4))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
