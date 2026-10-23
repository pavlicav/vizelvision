"""VizelVision Jinja: the station as a Shinto shrine, whose kami is the TV.

1. Late afternoon in the cedars: the camera walks up the stone path between the stone
   lanterns and through a vermilion torii, its tablet reading 十九 (nineteen).
2. The shrine: a straw shimenawa with zigzag shide over the front, the bell on its braided
   rope, the offering box, two stone kitsune (the left one holds a TV remote in its mouth
   where the key should be; the right one a rolled programme listing). Behind the open doors,
   on the altar between sakaki branches and a round mirror: the station's TV. The worshipper
   is the open logo: a five-yen coin into the box (チャリン), the bell rope shaken (ガラガラ),
   clap (パン), clap (パン); on the second clap the TV lights and its pink ring comes round.
   A bow.
3. The omikuji: a fortune slip unrolls: No. 19, 大吉, great blessing ("だいきち！"), and the
   details (lucky channel, lost item: the remote, adverts: none).
4. The ema rack: wooden wishes ("May the game not cut to commercial", "More cat"), and the
   fortune slips tied on the line in front.
5. Dusk at the torii: the stone lanterns lit, fireflies, four paper lanterns lighting on the
   closed logo, the wordmark dropping in under the torii, ヴィズルヴィジョン and CHANNEL 19.

Voices: Uzume, delighted: "だいきち！"; Izanami: "ヴィズルヴィジョン、十九チャンネル。"
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (A, INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    font, glint, grain, inked, inked_stroke, mix, pulse, rounded_rect, span, star, text_path, vignette)

ID = 'shinto'
NAME = 'VizelVision Jinja'
KIND = 'ident'
ORDER = 39
DESCRIPTION = ('VizelVision as a Shinto shrine whose kami is the TV: up the path through the torii, a coin, the bell '
               'and two claps on the open logo, a kitsune with the remote in its mouth, an omikuji that reads 大吉, '
               'the ema rack ("May the game not cut to commercial"), and the wordmark under the torii at dusk as '
               'the lanterns light on the closed logo. Uzume and Izanami, in Japanese.')
DURATION = 10.0
STILL_AT = 8.6
OVERLAYS = []

# Hit points (the music's too: shinto_music.py).
FADE_IN = (0.0, 0.35)
APPROACH = (0.0, 1.35)                           # up the path and through the torii
FOOTSTEPS = (0.12, 0.5, 0.88)                    # on the gravel
SHRINE_IN = (1.1, 1.35)                          # the dissolve to the shrine front
COIN_FLIGHT = (1.22, 1.5)                        # the coin, flipped into the box
LOGO = 1.5                                       # the open logo: coin, bell, clap, clap
COIN, BELL, CLAPS = 1.5, 1.75, (2.0, 2.5)
KAMI = 2.5                                       # the TV wakes on the second clap
BOW = (2.75, 3.3)
SLIP_IN = (3.2, 3.45)                            # the dissolve to the fortune
UNROLL = (3.45, 4.05)
DAIKICHI = 4.1                                   # 大吉 pops; "だいきち！"
EMA_IN = (5.1, 5.35)
PAN = (5.1, 6.4)
DUSK_IN = (6.05, 6.35)
NAME_LINE = 6.3                                  # "ヴィズルヴィジョン、十九チャンネル。"
CLOSED = 7.0                                     # the closed logo: four lanterns, the wordmark
LANTERNS = (7.0, 7.25, 7.5, 8.0)
KATAKANA = (8.05, 8.45)
FADE = (9.25, 9.6)

VERMILION = (0.9, 0.27, 0.13)
VERM_DARK = (0.62, 0.15, 0.08)
LACQUER = (0.1, 0.08, 0.08)
BARK = (0.42, 0.26, 0.17)
CEDAR = (0.12, 0.25, 0.17)
STONE = (0.63, 0.61, 0.56)
STONE_DARK = (0.44, 0.43, 0.4)
STRAW = (0.86, 0.75, 0.47)
PAPER = (0.98, 0.97, 0.92)
GOLD = (0.93, 0.75, 0.3)
WOOD = (0.62, 0.44, 0.27)
SKIN = (0.93, 0.76, 0.62)
SLEEVE = (0.16, 0.2, 0.36)
RED = (0.8, 0.1, 0.12)
BELL_X = 815                                     # the bell hangs to the right, clear of the altar

# The walk up the path: a pinhole camera, FOCAL px, the eye EYE m up, the horizon at HORIZON.
FOCAL, EYE, HORIZON = 700.0, 1.6, 360.0
TORII_Z = 30.0
WALK = 27.0                                      # how far the camera walks (m)


def jp(ctx, size, bold=False):
    ctx.select_font_face('Droid Sans Fallback', cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)


def centred(ctx, text, x, y):
    ext = ctx.text_extents(text)
    ctx.move_to(x - ext.width / 2 - ext.x_bearing, y)
    ctx.text_path(text)


# ---------------------------------------------------------------- the torii

def torii(ctx, cx, gy, s, ink=3.0, tablet=True):
    """A vermilion myojin torii, s px per metre, its feet on gy."""
    ctx.save()
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)

    def box(x0, y0, x1, y1, colour):
        ctx.rectangle(cx + x0 * s, gy - y1 * s, (x1 - x0) * s, (y1 - y0) * s)
        ctx.set_source_rgb(*colour)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(ink)
        ctx.stroke()

    for side in (-1, 1):                                             # the pillars, black at the foot
        x = side * 2.2
        ctx.move_to(cx + (x - 0.26) * s, gy)
        ctx.line_to(cx + (x - 0.21) * s, gy - 5.45 * s)
        ctx.line_to(cx + (x + 0.21) * s, gy - 5.45 * s)
        ctx.line_to(cx + (x + 0.26) * s, gy)
        ctx.close_path()
        shade = cairo.LinearGradient(cx + (x - 0.26) * s, 0, cx + (x + 0.26) * s, 0)
        shade.add_color_stop_rgb(0, *mix(VERMILION, WHITE, 0.15))
        shade.add_color_stop_rgb(0.55, *VERMILION)
        shade.add_color_stop_rgb(1, *VERM_DARK)
        ctx.set_source(shade)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(ink)
        ctx.stroke()
        box(x - 0.3, 0, x + 0.3, 0.45, LACQUER)
    box(-2.95, 4.15, 2.95, 4.55, VERMILION)                          # the nuki
    box(-3.3, 5.4, 3.3, 5.75, VERMILION)                             # the shimaki
    # The kasagi: black, curving up at both ends.
    ctx.move_to(cx - 3.75 * s, gy - 6.12 * s)
    ctx.curve_to(cx - 2.2 * s, gy - 5.68 * s, cx + 2.2 * s, gy - 5.68 * s, cx + 3.75 * s, gy - 6.12 * s)
    ctx.line_to(cx + 3.82 * s, gy - 6.5 * s)
    ctx.curve_to(cx + 2.2 * s, gy - 6.05 * s, cx - 2.2 * s, gy - 6.05 * s, cx - 3.82 * s, gy - 6.5 * s)
    ctx.close_path()
    ctx.set_source_rgb(*LACQUER)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(ink)
    ctx.stroke()
    box(-0.15, 4.55, 0.15, 5.4, VERMILION)                           # the gakuzuka
    if tablet and s > 12:                                            # the tablet: 十九
        box(-0.42, 4.62, 0.42, 5.36, LACQUER)
        ctx.rectangle(cx - 0.34 * s, gy - 5.28 * s, 0.68 * s, 0.58 * s)
        ctx.set_source_rgb(*mix(LACQUER, GOLD, 0.15))
        ctx.fill()
        jp(ctx, 0.27 * s, bold=True)
        ctx.set_source_rgb(*GOLD)
        centred(ctx, '十', cx, gy - 4.98 * s)
        centred(ctx, '九', cx, gy - 4.71 * s)
        ctx.fill()
    ctx.restore()


def shimenawa(ctx, x0, x1, y, sag, thick, t=0.0, shide=4):
    """A twisted straw rope, sagging, with zigzag paper shide hanging from it."""
    ctx.save()
    n = 40
    pts = [(x0 + (x1 - x0) * k / n, y + sag * math.sin(math.pi * k / n)) for k in range(n + 1)]
    for k in range(n + 1):
        x, yy = pts[k]
        w = thick * (0.55 + 0.45 * math.sin(math.pi * k / n))
        ctx.arc(x, yy, w, 0, TAU)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    for k in range(n + 1):
        x, yy = pts[k]
        w = thick * (0.55 + 0.45 * math.sin(math.pi * k / n)) - 2.5
        ctx.arc(x, yy, max(1, w), 0, TAU)
    ctx.set_source_rgb(*STRAW)
    ctx.fill()
    ctx.set_source_rgba(*mix(STRAW, INK, 0.5), 0.8)              # the twist
    ctx.set_line_width(2.5)
    for k in range(0, n * 3):
        u = k / (n * 3)
        x = x0 + (x1 - x0) * u
        yy = y + sag * math.sin(math.pi * u)
        w = thick * (0.55 + 0.45 * math.sin(math.pi * u))
        ctx.move_to(x - w * 0.4, yy - w * 0.8)
        ctx.line_to(x + w * 0.4, yy + w * 0.8)
    ctx.stroke()
    for k in range(shide):
        u = (k + 0.5) / shide
        x = x0 + (x1 - x0) * u
        yy = y + sag * math.sin(math.pi * u) + thick * 0.6
        sway = 0.06 * math.sin(t * 2.3 + k * 1.7)
        ctx.save()
        ctx.translate(x, yy)
        ctx.rotate(sway)
        z = thick * 0.9
        ctx.move_to(-z * 0.3, 0)
        for j, (dx, dy) in enumerate(((z * 0.3, 0), (z * 0.3, z), (-z * 0.3, z), (-z * 0.3, 2 * z), (z * 0.3, 2 * z),
                                       (z * 0.3, 3 * z), (-z * 0.3, 3 * z), (-z * 0.3, 4 * z), (z * 0.0, 4 * z))):
            ctx.line_to(dx + (z * 0.25 if j > 1 else 0), dy)
        ctx.line_to(-z * 0.05, 4 * z)
        ctx.line_to(-z * 0.55, 3 * z)
        ctx.line_to(-z * 0.05, 3 * z)
        ctx.line_to(-z * 0.55, 2 * z)
        ctx.line_to(-z * 0.05, 2 * z)
        ctx.line_to(-z * 0.55, z)
        ctx.line_to(-z * 0.05, z)
        ctx.close_path()
        inked(ctx, PAPER, 2, (2, 2))
        ctx.restore()
    ctx.restore()


def stone_lantern(ctx, x, gy, s, lit=0.0):
    """A toro: base, post, the firebox with its window, a curved roof, the jewel on top."""
    ctx.save()
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)

    def part(path, colour):
        path()
        inked(ctx, colour, max(1.0, s * 0.03), (max(1, s * 0.04), max(1, s * 0.04)))

    part(lambda: rounded_rect(ctx, x - 0.45 * s, gy - 0.3 * s, 0.9 * s, 0.3 * s, 0.05 * s), STONE_DARK)
    part(lambda: ctx.rectangle(x - 0.16 * s, gy - 1.2 * s, 0.32 * s, 0.9 * s), STONE)
    part(lambda: rounded_rect(ctx, x - 0.38 * s, gy - 1.38 * s, 0.76 * s, 0.2 * s, 0.04 * s), STONE)
    part(lambda: ctx.rectangle(x - 0.3 * s, gy - 1.85 * s, 0.6 * s, 0.47 * s), STONE)
    ctx.rectangle(x - 0.14 * s, gy - 1.76 * s, 0.28 * s, 0.3 * s)            # the window
    ctx.set_source_rgb(*mix((0.12, 0.1, 0.08), (1.0, 0.72, 0.3), lit))
    ctx.fill()

    def roof():
        ctx.move_to(x - 0.62 * s, gy - 1.85 * s)
        ctx.curve_to(x - 0.3 * s, gy - 1.95 * s, x - 0.12 * s, gy - 2.2 * s, x, gy - 2.3 * s)
        ctx.curve_to(x + 0.12 * s, gy - 2.2 * s, x + 0.3 * s, gy - 1.95 * s, x + 0.62 * s, gy - 1.85 * s)
        ctx.close_path()
    part(roof, STONE_DARK)
    part(lambda: ctx.arc(x, gy - 2.38 * s, 0.1 * s, 0, TAU), STONE)
    if lit > 0:
        ctx.set_operator(cairo.OPERATOR_ADD)
        g = cairo.RadialGradient(x, gy - 1.6 * s, 0, x, gy - 1.6 * s, 1.4 * s)
        g.add_color_stop_rgba(0, 1.0, 0.7, 0.3, 0.55 * lit)
        g.add_color_stop_rgba(1, 1.0, 0.5, 0.2, 0)
        ctx.set_source(g)
        ctx.arc(x, gy - 1.6 * s, 1.4 * s, 0, TAU)
        ctx.fill()
    ctx.restore()


def cedar(ctx, x, gy, s, top=-200, colour=BARK):
    """A tall sugi trunk from the ground out of the top of the frame."""
    w = 0.9 * s
    g = cairo.LinearGradient(x - w / 2, 0, x + w / 2, 0)
    g.add_color_stop_rgb(0, *mix(colour, WHITE, 0.12))
    g.add_color_stop_rgb(0.6, *colour)
    g.add_color_stop_rgb(1, *mix(colour, INK, 0.45))
    ctx.move_to(x - w * 0.62, gy)
    ctx.line_to(x - w * 0.5, top)
    ctx.line_to(x + w * 0.5, top)
    ctx.line_to(x + w * 0.62, gy)
    ctx.close_path()
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.set_source_rgba(*INK, 0.9)
    ctx.set_line_width(max(1, s * 0.03))
    ctx.stroke()
    ctx.set_source_rgba(*INK, 0.25)                                 # the bark's stringy lines
    ctx.set_line_width(max(1, s * 0.015))
    for k in range(4):
        ox = x - w * 0.3 + k * w * 0.2
        ctx.move_to(ox, gy)
        ctx.line_to(ox + w * 0.02, top)
    ctx.stroke()


# ---------------------------------------------------------------- 1. the approach

@lru_cache(maxsize=None)
def approach_back():
    """The sky through the canopy and the far forest, which the walk doesn't move."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, HORIZON + 20)
    g.add_color_stop_rgb(0, 0.95, 0.83, 0.55)
    g.add_color_stop_rgb(0.7, 0.98, 0.75, 0.45)
    g.add_color_stop_rgb(1, 0.85, 0.6, 0.38)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(9)
    for k in range(70):                                              # the far cedars, in haze
        x = rand.uniform(-40, W + 40)
        h = rand.uniform(120, 260)
        ctx.move_to(x, HORIZON - h)
        ctx.line_to(x - h * 0.22, HORIZON + 10)
        ctx.line_to(x + h * 0.22, HORIZON + 10)
        ctx.close_path()
        ctx.set_source_rgb(*mix((0.3, 0.38, 0.3), (0.85, 0.68, 0.45), rand.uniform(0.35, 0.6)))
        ctx.fill()
    ctx.rectangle(0, HORIZON, W, H - HORIZON)                       # the forest floor
    ctx.set_source_rgb(0.24, 0.27, 0.17)
    ctx.fill()
    for k in range(260):                                             # canopy masses at the top
        x, y = rand.uniform(-60, W + 60), rand.uniform(-60, 90) + abs(rand.gauss(0, 30))
        ctx.arc(x, y, rand.uniform(30, 70), 0, TAU)
        ctx.set_source_rgb(*mix(CEDAR, (0.05, 0.12, 0.08), rand.random()))
        ctx.fill()
    return surface


def project(x, y, z, cz):
    d = max(z - cz, 0.05)
    return W / 2 + FOCAL * x / d, HORIZON - FOCAL * (y - EYE) / d, FOCAL / d


@lru_cache(maxsize=None)
def light_shafts():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    rand = random.Random(4)
    for k in range(7):
        x = 300 + k * 150 + rand.uniform(-40, 40)
        w = rand.uniform(30, 80)
        ctx.move_to(x, -20)
        ctx.line_to(x + w, -20)
        ctx.line_to(x + w - 420, H)
        ctx.line_to(x - 420, H)
        ctx.close_path()
        g = cairo.LinearGradient(0, 0, 0, H)
        g.add_color_stop_rgba(0, 1.0, 0.85, 0.55, rand.uniform(0.12, 0.2))
        g.add_color_stop_rgba(1, 1.0, 0.85, 0.55, 0)
        ctx.set_source(g)
        ctx.fill()
    return surface


def approach(ctx, t):
    cz = WALK * ease_in_out(span(t, *APPROACH))
    bob = 3 * math.sin(t * TAU * 2.6)                                # the walk
    ctx.save()
    ctx.translate(0, bob)
    ctx.set_source_surface(approach_back(), 0, -bob)
    ctx.paint()
    # The gravel and the path's stone slabs.
    near, far = cz + 0.6, 60.0
    a, b = project(-4.2, 0, near, cz), project(4.2, 0, near, cz)
    c, d = project(4.2, 0, far, cz), project(-4.2, 0, far, cz)
    ctx.move_to(a[0], a[1])
    ctx.line_to(b[0], b[1])
    ctx.line_to(c[0], c[1])
    ctx.line_to(d[0], d[1])
    ctx.close_path()
    ctx.set_source_rgb(0.66, 0.62, 0.52)
    ctx.fill()
    z = math.floor(cz) + 1.0
    while z < 48:
        p0, p1 = project(-1.2, 0, z, cz), project(1.2, 0, z, cz)
        p2, p3 = project(1.2, 0, z + 0.85, cz), project(-1.2, 0, z + 0.85, cz)
        ctx.move_to(p0[0], min(H + 50, p0[1]))
        ctx.line_to(p1[0], min(H + 50, p1[1]))
        ctx.line_to(p2[0], p2[1])
        ctx.line_to(p3[0], p3[1])
        ctx.close_path()
        shade = 0.5 + 0.5 * ((int(z) * 7) % 5) / 5
        ctx.set_source_rgb(*mix(STONE_DARK, STONE, shade))
        ctx.fill_preserve()
        ctx.set_source_rgba(*INK, 0.5)
        ctx.set_line_width(max(0.5, FOCAL / max(z - cz, 0.1) * 0.02))
        ctx.stroke()
        z += 1.0
    # Back to front: cedars, lanterns, and the torii at TORII_Z.
    things = []
    rand = random.Random(21)
    for k in range(18):
        zz = 4 + k * 2.4 + rand.uniform(-0.6, 0.6)
        for side in (-1, 1):
            things.append((zz + rand.uniform(-0.5, 0.5), 'cedar', side * rand.uniform(5.5, 8.5)))
    for zz in (8, 14, 20, 26, 36, 42):
        for side in (-1, 1):
            things.append((zz, 'lantern', side * 2.6))
    things.append((TORII_Z, 'torii', 0))
    things.append((46, 'shrine', 0))
    for zz, kind, x in sorted(things, key=lambda thing: -thing[0]):
        if zz <= cz + 0.25:
            continue
        sx, gy, s = project(x, 0, zz, cz)
        if kind == 'cedar':
            cedar(ctx, sx, gy, s, top=-50)
        elif kind == 'lantern':
            stone_lantern(ctx, sx, gy, s)
        elif kind == 'torii':
            torii(ctx, sx, gy, s, ink=max(1.5, s * 0.05))
            shimenawa(ctx, sx - 2.0 * s, sx + 2.0 * s, gy - 4.05 * s, 0.35 * s, 0.11 * s, t, shide=3)
        else:                                                        # the shrine, far up the path
            ctx.move_to(sx - 4.5 * s, gy - 3.4 * s)
            ctx.line_to(sx, gy - 5.2 * s)
            ctx.line_to(sx + 4.5 * s, gy - 3.4 * s)
            ctx.close_path()
            ctx.set_source_rgb(0.25, 0.2, 0.18)
            ctx.fill()
            ctx.rectangle(sx - 3.0 * s, gy - 3.4 * s, 6.0 * s, 3.4 * s)
            ctx.set_source_rgb(*VERM_DARK)
            ctx.fill()
            ctx.rectangle(sx - 0.8 * s, gy - 2.6 * s, 1.6 * s, 1.6 * s)
            ctx.set_source_rgb(0.5, 0.95, 0.95)
            ctx.fill()
    ctx.set_source_surface(light_shafts(), 0, 0)
    ctx.paint()
    ctx.restore()


# ---------------------------------------------------------------- 2. the shrine

def tv(ctx, x, y, scale, t, lit=1.0):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(scale, scale)
    A.draw_tv(ctx, t, 1, 0.0)
    if lit < 1:
        rounded_rect(ctx, -128, -88, 198, 176, 28)
        ctx.set_source_rgba(0.02, 0.03, 0.08, 0.85 * (1 - lit))
        ctx.fill()
    ctx.restore()


def kitsune(ctx, x, gy, facing, holding):
    """A stone fox on its plinth, red bib on, something in its mouth."""
    ctx.save()
    ctx.translate(x, gy)
    ctx.scale(facing, 1)
    rounded_rect(ctx, -95, -120, 190, 120, 6)                        # the plinth
    inked(ctx, STONE_DARK, 4, (5, 5))
    rounded_rect(ctx, -80, -150, 160, 34, 5)
    inked(ctx, STONE, 4, (5, 5))
    stone = mix(STONE, WHITE, 0.15)
    # Tail, a big brush up behind.
    ctx.move_to(-40, -160)
    ctx.curve_to(-120, -200, -110, -330, -60, -380)
    ctx.curve_to(-70, -320, -40, -250, -10, -200)
    ctx.close_path()
    inked(ctx, stone, 4, (5, 5))
    # Body, sitting.
    ctx.move_to(-55, -150)
    ctx.curve_to(-70, -230, -40, -300, 0, -320)
    ctx.curve_to(35, -300, 50, -240, 55, -150)
    ctx.close_path()
    inked(ctx, stone, 4, (5, 5))
    # Forelegs.
    for lx in (8, 32):
        rounded_rect(ctx, lx, -250, 18, 100, 9)
        inked(ctx, stone, 3, (3, 3))
    # The bib.
    ctx.move_to(-8, -300)
    ctx.curve_to(10, -275, 45, -270, 62, -290)
    ctx.line_to(48, -240)
    ctx.curve_to(30, -228, 10, -235, 0, -255)
    ctx.close_path()
    inked(ctx, RED, 3, (3, 3))
    # Head: pointed snout, tall ears.
    ctx.move_to(-20, -310)
    ctx.curve_to(-25, -350, 0, -370, 20, -365)
    ctx.line_to(80, -340)
    ctx.curve_to(70, -320, 30, -305, -20, -310)
    ctx.close_path()
    inked(ctx, stone, 4, (5, 5))
    for ex, lean in ((-8, -0.2), (14, 0.15)):
        ctx.move_to(ex - 10, -358)
        ctx.line_to(ex + 2 + lean * 40, -410)
        ctx.line_to(ex + 14, -360)
        ctx.close_path()
        inked(ctx, stone, 4, (4, 4))
    ctx.arc(28, -347, 4, 0, TAU)                                     # the eye
    ctx.set_source_rgb(*INK)
    ctx.fill()
    if holding == 'remote':                                          # a TV remote, crosswise in its mouth
        ctx.save()
        ctx.translate(62, -330)
        ctx.rotate(0.2)
        rounded_rect(ctx, -46, -11, 92, 22, 8)
        inked(ctx, (0.15, 0.15, 0.17), 3, (3, 3))
        for k, colour in enumerate((RED, (0.3, 0.8, 0.4), (0.9, 0.85, 0.2), (0.3, 0.5, 0.95))):
            ctx.arc(-28 + k * 12, 0, 3.5, 0, TAU)
            ctx.set_source_rgb(*colour)
            ctx.fill()
        for k in range(3):
            ctx.rectangle(16 + k * 8, -4, 5, 8)
        ctx.set_source_rgb(0.7, 0.7, 0.72)
        ctx.fill()
        ctx.restore()
    else:                                                            # a rolled programme listing
        ctx.save()
        ctx.translate(66, -330)
        ctx.rotate(0.2)
        rounded_rect(ctx, -40, -12, 80, 24, 12)
        inked(ctx, PAPER, 3, (3, 3))
        jp(ctx, 15, bold=True)
        ctx.set_source_rgb(*RED)
        centred(ctx, '番組表', 0, 6)
        ctx.fill()
        ctx.restore()
    ctx.restore()


@lru_cache(maxsize=None)
def shrine_back():
    """The shrine front, everything that doesn't move."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, H)
    g.add_color_stop_rgb(0, 0.86, 0.72, 0.5)
    g.add_color_stop_rgb(1, 0.5, 0.42, 0.3)
    ctx.set_source(g)
    ctx.paint()
    for x in (-30, 70, 1190, 1290, 150, 1110):                        # cedars behind
        cedar(ctx, x, 560, 90, top=-20, colour=mix(BARK, INK, 0.25))
    rand = random.Random(2)
    for k in range(160):
        ctx.arc(rand.uniform(-50, W + 50), rand.uniform(-50, 120), rand.uniform(30, 70), 0, TAU)
        ctx.set_source_rgb(*mix(CEDAR, (0.04, 0.1, 0.07), rand.random()))
        ctx.fill()
    # The gravel court and the steps up.
    ctx.rectangle(0, 560, W, 160)
    ctx.set_source_rgb(0.66, 0.62, 0.52)
    ctx.fill()
    for k in range(900):
        ctx.arc(rand.uniform(0, W), rand.uniform(565, H), rand.uniform(0.8, 2.0), 0, TAU)
        ctx.set_source_rgba(*mix(STONE_DARK, WHITE, rand.random()), 0.6)
        ctx.fill()
    # The building: posts, walls, the open doors and the altar inside.
    ctx.rectangle(330, 230, 620, 300)
    ctx.set_source_rgb(0.18, 0.12, 0.09)
    ctx.fill()
    inner = cairo.RadialGradient(640, 360, 20, 640, 360, 340)
    inner.add_color_stop_rgb(0, 0.42, 0.3, 0.18)
    inner.add_color_stop_rgb(1, 0.1, 0.07, 0.05)
    ctx.rectangle(470, 250, 340, 270)
    ctx.set_source(inner)
    ctx.fill()
    ctx.rectangle(470, 455, 340, 30)                                 # the altar: white cloth
    ctx.set_source_rgb(*PAPER)
    ctx.fill()
    for vx in (515, 765):                                            # sakaki in white vases
        rounded_rect(ctx, vx - 12, 410, 24, 46, 8)
        inked(ctx, PAPER, 2, (2, 2))
        for k in range(9):
            a = -math.pi / 2 + (k - 4) * 0.22
            ctx.save()
            ctx.translate(vx + math.cos(a) * 30, 400 + math.sin(a) * 34)
            ctx.rotate(a + math.pi / 2)
            ctx.scale(0.45, 1)
            ctx.arc(0, 0, 16, 0, TAU)
            ctx.restore()
            inked(ctx, (0.15, 0.42, 0.2), 2, (1, 1))
    for wx in (570, 710):                                            # sake bottles (heishi)
        ctx.move_to(wx - 9, 455)
        ctx.curve_to(wx - 16, 430, wx - 6, 425, wx - 5, 410)
        ctx.line_to(wx + 5, 410)
        ctx.curve_to(wx + 6, 425, wx + 16, 430, wx + 9, 455)
        ctx.close_path()
        inked(ctx, PAPER, 2, (2, 2))
    # The platform, posts, the doors folded back.
    for x0, x1 in ((330, 470), (810, 950)):
        ctx.rectangle(x0, 250, x1 - x0, 270)
        ctx.set_source_rgb(*WOOD)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(3)
        ctx.stroke()
        for k in range(6):                                           # lattice doors
            x = x0 + 12 + k * (x1 - x0 - 24) / 5
            ctx.move_to(x, 262)
            ctx.line_to(x, 508)
        for k in range(9):
            y = 262 + k * 30
            ctx.move_to(x0 + 12, y)
            ctx.line_to(x1 - 12, y)
        ctx.set_source_rgba(*INK, 0.55)
        ctx.set_line_width(2)
        ctx.stroke()
    for x in (330, 470, 810, 950):                                   # vermilion posts
        ctx.rectangle(x - 14, 220, 28, 320)
        inked(ctx, VERMILION, 3, (4, 0))
    rounded_rect(ctx, 290, 515, 700, 30, 6)                          # the veranda
    inked(ctx, mix(WOOD, INK, 0.2), 3, (0, 5))
    for k in range(4):                                               # steps
        rounded_rect(ctx, 400 - k * 30, 545 + k * 20, 480 + k * 60, 22, 4)
        inked(ctx, mix(WOOD, WHITE, 0.05 * k), 3, (0, 4))
    # The roof: cypress-bark eaves, the ridge with katsuogi, chigi crossed at the gables.
    ctx.move_to(170, 250)
    ctx.curve_to(330, 215, 450, 160, 520, 95)
    ctx.line_to(760, 95)
    ctx.curve_to(830, 160, 950, 215, 1110, 250)
    ctx.line_to(1110, 268)
    ctx.curve_to(950, 240, 640, 236, 170, 268)
    ctx.close_path()
    roof = cairo.LinearGradient(0, 95, 0, 268)
    roof.add_color_stop_rgb(0, 0.36, 0.26, 0.2)
    roof.add_color_stop_rgb(1, 0.2, 0.14, 0.11)
    inked(ctx, roof, 4, (0, 6))
    ctx.set_source_rgba(*INK, 0.3)
    ctx.set_line_width(1.5)
    for k in range(30):
        u = k / 29
        ctx.move_to(520 + 240 * u, 100)
        ctx.line_to(170 + 940 * u, 255)
    ctx.stroke()
    rounded_rect(ctx, 500, 78, 280, 22, 6)                           # the ridge
    inked(ctx, (0.22, 0.17, 0.14), 3, (0, 3))
    for k in range(5):                                               # katsuogi
        rounded_rect(ctx, 528 + k * 52, 60, 30, 20, 8)
        inked(ctx, GOLD, 3, (0, 3))
    for side in (-1, 1):                                             # chigi
        x = 640 + side * 135
        for lean in (-1, 1):
            ctx.save()
            ctx.translate(x, 92)
            ctx.rotate(lean * 0.45)
            ctx.rectangle(-6, -70, 12, 80)
            ctx.restore()
            inked(ctx, (0.22, 0.17, 0.14), 3, (0, 2))
    # Hanging lanterns at the corners of the eaves.
    for lx in (300, 980):
        ctx.move_to(lx, 252)
        ctx.line_to(lx, 290)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(2)
        ctx.stroke()
        ctx.save()
        ctx.translate(lx, 330)
        ctx.scale(1, 1.3)
        ctx.arc(0, 0, 30, 0, TAU)
        ctx.restore()
        inked(ctx, (0.97, 0.9, 0.75), 3, (3, 3))
        jp(ctx, 22, bold=True)
        ctx.set_source_rgb(*RED)
        centred(ctx, '奉', lx, 330)
        ctx.fill()
        for yy in (290, 368):
            rounded_rect(ctx, lx - 18, yy, 36, 9, 3)
            inked(ctx, LACQUER, 2, (0, 0))
    # The offering box.
    ctx.move_to(450, 600)
    ctx.line_to(830, 600)
    ctx.line_to(850, 720)
    ctx.line_to(430, 720)
    ctx.close_path()
    box = cairo.LinearGradient(0, 600, 0, 720)
    box.add_color_stop_rgb(0, 0.58, 0.38, 0.22)
    box.add_color_stop_rgb(1, 0.36, 0.22, 0.12)
    inked(ctx, box, 4, (0, 0))
    ctx.move_to(440, 600)
    ctx.line_to(840, 600)
    ctx.line_to(800, 572)
    ctx.line_to(480, 572)
    ctx.close_path()
    inked(ctx, mix(WOOD, WHITE, 0.15), 4, (0, 0))
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    for k in range(9):                                               # the slats
        y = 576 + k * 3
        ctx.move_to(486 - k * 4, y)
        ctx.line_to(794 + k * 4, y)
    ctx.stroke()
    jp(ctx, 46, bold=True)
    ctx.set_source_rgb(*GOLD)
    centred(ctx, '奉納', 640, 680)
    ctx.fill()
    # The two kitsune.
    kitsune(ctx, 150, 700, 1, 'remote')
    kitsune(ctx, 1130, 700, -1, 'listing')
    return surface


def bell_rope_angle(t):
    if t < BELL - 0.05:
        return 0.015 * math.sin(t * 1.7)
    u = t - (BELL - 0.05)
    return 0.22 * math.sin(u * 15) * math.exp(-u * 2.6) + 0.015 * math.sin(t * 1.7)


def bell_and_rope(ctx, t):
    a = bell_rope_angle(t)
    bx, by = BELL_X, 300
    ctx.save()
    ctx.translate(bx, by)
    ctx.rotate(a)
    # The braided rope, red, white and purple, hanging to hand height.
    for k, colour in enumerate((RED, PAPER, (0.45, 0.2, 0.55))):
        ctx.move_to(-10 + k * 10, 20)
        for j in range(1, 16):
            ctx.line_to(-10 + k * 10 + 5 * math.sin(j * 1.3 + k * 2.1), 20 + j * 15)
        inked_stroke(ctx, colour, 8, (2, 2))
    ctx.move_to(0, 245)                                              # the tassel
    ctx.line_to(-18, 290)
    ctx.line_to(18, 290)
    ctx.close_path()
    inked(ctx, RED, 3, (2, 2))
    ctx.restore()
    # The bell itself, jiggling.
    jig = 4 * math.sin((t - BELL) * 40) * math.exp(-max(0, t - BELL) * 5) if t > BELL - 0.02 else 0
    ctx.arc(bx + jig, by, 30, 0, TAU)
    g = cairo.RadialGradient(bx - 10 + jig, by - 12, 4, bx + jig, by, 34)
    g.add_color_stop_rgb(0, 1.0, 0.95, 0.65)
    g.add_color_stop_rgb(0.5, *GOLD)
    g.add_color_stop_rgb(1, 0.55, 0.38, 0.1)
    inked(ctx, g, 4, (4, 4))
    ctx.move_to(bx - 22 + jig, by + 8)
    ctx.line_to(bx + 22 + jig, by + 8)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(5)
    ctx.stroke()
    shake = pulse(t, BELL, 0.45)
    if shake > 0:                                                    # motion marks
        ctx.set_line_width(5)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        for side in (-1, 1):
            for k in range(3):
                r = 46 + k * 12
                ctx.arc(bx, by, r, (-0.35 if side > 0 else math.pi - 0.35), (0.35 if side > 0 else math.pi + 0.35))
                ctx.set_source_rgba(*INK, shake)
                ctx.stroke()


def hand(ctx, x, y, angle, mirror=1, open_=1.0):
    """A hand, palm towards the middle, fingers up, a sleeve below."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(angle)
    ctx.scale(mirror, 1)
    rounded_rect(ctx, -46, 110, 92, 200, 20)                         # the sleeve
    inked(ctx, SLEEVE, 4, (4, 4))
    rounded_rect(ctx, -34, -110, 62, 225, 30)                        # palm and fingers
    inked(ctx, SKIN, 4, (4, 4))
    ctx.set_source_rgba(*INK, 0.35)
    ctx.set_line_width(2.5)
    for k in range(3):
        ctx.move_to(-20 + k * 15, -105)
        ctx.line_to(-20 + k * 15, -40)
    ctx.stroke()
    ctx.save()                                                       # the thumb
    ctx.translate(26, 10)
    ctx.rotate(-0.5 * open_)
    rounded_rect(ctx, -12, -70, 26, 80, 13)
    ctx.restore()
    inked(ctx, SKIN, 4, (3, 3))
    ctx.restore()


def sound_word(ctx, t, when, text, x, y, colour, size=64, tilt=-0.12):
    """A manga sound effect, popping in at when."""
    p = span(t, when - 0.02, when + 0.12)
    life = span(t, when, when + 0.42)
    if p <= 0 or life >= 1:
        return
    ctx.save()
    ctx.translate(x, y - 30 * life)
    ctx.rotate(tilt)
    k = back_out(p) * (1 + 0.1 * (1 - life))
    ctx.scale(k, k)
    jp(ctx, size, bold=True)
    centred(ctx, text, 0, size * 0.35)
    ctx.push_group()
    inked(ctx, colour, 5, (5, 5), fatten=6)
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(1 - ease_in(span(life, 0.6, 1.0)))
    ctx.restore()


def coin(ctx, t):
    if t < COIN_FLIGHT[0] - 0.12:
        return
    p = span(t, *COIN_FLIGHT)
    if p >= 1:
        return
    # The flicking hand, bottom right.
    lift = ease_out(span(t, COIN_FLIGHT[0] - 0.12, COIN_FLIGHT[0])) * (1 - ease_in(span(t, COIN_FLIGHT[0] + 0.05,
                                                                                      COIN_FLIGHT[0] + 0.3)))
    if lift > 0:
        hand(ctx, 1010, 850 - 200 * lift, -0.5, -1, 0.3)
    x0, y0, x1, y1 = 960, 610, 640, 585
    x = x0 + (x1 - x0) * p
    y = y0 + (y1 - y0) * p - 280 * 4 * p * (1 - p)
    spin = math.cos(p * TAU * 3.5)
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(max(0.08, abs(spin)), 1)
    ctx.arc(0, 0, 22, 0, TAU)
    ctx.arc_negative(0, 0, 6, TAU, 0)
    inked(ctx, GOLD if spin > 0 else mix(GOLD, INK, 0.25), 3, (2, 2))
    ctx.restore()


def claps(ctx, t):
    """Two hands come up, clap, clap, and stay together for the bow."""
    up = ease_out(span(t, 1.8, 1.95)) * (1 - ease_in(span(t, BOW[1] - 0.05, BOW[1] + 0.2)))
    if up <= 0:
        return
    gap = 120
    for when in CLAPS:
        gap = min(gap, 120 * ease_in_out(min(1, abs(t - when) / 0.14)) if t < when else gap)
    if t >= CLAPS[0]:
        gap = 100 * math.sin(math.pi * span(t, CLAPS[0] + 0.04, CLAPS[1])) if t < CLAPS[1] else 0
    if t < CLAPS[0]:
        gap = 30 + 90 * span(CLAPS[0] - t, 0, 0.12)
    y = 610 + 360 * (1 - up)
    ctx.save()
    ctx.translate(640, y)
    ctx.scale(1.15, 1.15)
    hand(ctx, -32 - gap / 2, 0, 0.12, 1)
    hand(ctx, 32 + gap / 2, 0, -0.12, -1)
    ctx.restore()
    for when in CLAPS:                                               # the burst on contact
        b = span(t, when, when + 0.16)
        if 0 < b < 1:
            ctx.save()
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            for k in range(10):
                a = -math.pi * (0.05 + 0.9 * k / 9)
                r0, r1 = 150 + 40 * b, 190 + 90 * b
                ctx.move_to(640 + math.cos(a) * r0, 540 + math.sin(a) * r0 * 0.7)
                ctx.line_to(640 + math.cos(a) * r1, 540 + math.sin(a) * r1 * 0.7)
            ctx.set_source_rgba(1, 1, 1, 1 - b)
            ctx.set_line_width(7)
            ctx.stroke()
            ctx.restore()


def kami(ctx, t):
    """The mirror behind, and the TV on the altar, waking on the second clap."""
    wake = ease_out(span(t, KAMI, KAMI + 0.35))
    mirror = cairo.RadialGradient(640, 340, 10, 640, 340, 108)
    mirror.add_color_stop_rgb(0, *mix((0.85, 0.82, 0.7), WHITE, wake))
    mirror.add_color_stop_rgb(0.8, *mix((0.6, 0.55, 0.4), (1.0, 0.9, 0.7), wake))
    mirror.add_color_stop_rgb(1, 0.4, 0.32, 0.18)
    ctx.arc(640, 340, 104, 0, TAU)
    inked(ctx, mirror, 4, (0, 0))
    ctx.arc(640, 340, 112, 0, TAU)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(8)
    ctx.stroke()
    if wake > 0:                                                     # rays
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        for k in range(16):
            a = k * TAU / 16 + t * 0.4
            ctx.move_to(640, 380)
            ctx.line_to(640 + math.cos(a - 0.06) * 330, 380 + math.sin(a - 0.06) * 330)
            ctx.line_to(640 + math.cos(a + 0.06) * 330, 380 + math.sin(a + 0.06) * 330)
            ctx.close_path()
        g = cairo.RadialGradient(640, 380, 40, 640, 380, 330)
        g.add_color_stop_rgba(0, 1.0, 0.9, 0.6, 0.35 * wake)
        g.add_color_stop_rgba(1, 1.0, 0.9, 0.6, 0)
        ctx.set_source(g)
        ctx.fill()
        ctx.restore()
    bob = 3 * math.sin(t * 2.2) * wake
    tv(ctx, 640, 392 + bob, 0.48, t, lit=0.25 + 0.75 * wake)
    if wake > 0:                                                     # its ring comes round
        ctx.save()
        ctx.translate(640, 402 + bob)
        ctx.rotate(-0.16)
        sweep = TAU * wake
        ctx.arc(0, 0, 1, 0, 0)
        ctx.new_path()
        for k in range(0, 61):
            a = -math.pi / 2 + sweep * k / 60
            px, py = math.cos(a) * 150, math.sin(a) * 38
            if k == 0:
                ctx.move_to(px, py)
            else:
                ctx.line_to(px, py)
        inked_stroke(ctx, PINK, 6, (3, 3))
        ctx.restore()
        for k, (gx, gy, when) in enumerate(((545, 320, 0.1), (735, 340, 0.25), (650, 285, 0.4))):
            life = span(t, KAMI + when, KAMI + when + 0.5)
            if 0 < life < 1:
                glint(ctx, gx, gy, 22 * math.sin(life * math.pi), life * 3)


def shrine(ctx, t):
    bow = math.sin(math.pi * span(t, *BOW)) if BOW[0] < t < BOW[1] else 0.0
    ctx.save()
    ctx.translate(W / 2, 0)                                          # the bow: a dip and a lean in
    ctx.scale(1 + 0.12 * bow, 1 + 0.12 * bow)
    ctx.translate(-W / 2, -36 * bow)
    ctx.set_source_surface(shrine_back(), 0, 0)
    ctx.paint()
    kami(ctx, t)
    shimenawa(ctx, 300, 980, 258, 34, 22, t, shide=4)
    bell_and_rope(ctx, t)
    ctx.restore()
    coin(ctx, t)
    # The hand on the bell rope.
    grab = ease_out(span(t, BELL - 0.15, BELL - 0.05)) * (1 - ease_in(span(t, BELL + 0.08, BELL + 0.22)))
    if grab > 0:
        a = bell_rope_angle(t)
        rx = BELL_X - math.sin(a) * 250
        hand(ctx, rx + 20, 650 + 260 * (1 - grab), -0.1, -1, 0.0)
    claps(ctx, t)
    sound_word(ctx, t, COIN, 'チャリン', 760, 520, YELLOW, 58, -0.15)
    sound_word(ctx, t, BELL, 'ガラガラ', 850, 250, YELLOW, 66, 0.1)
    sound_word(ctx, t, CLAPS[0], 'パン', 420, 430, WHITE, 84, -0.18)
    sound_word(ctx, t, CLAPS[1], 'パン', 860, 420, WHITE, 96, 0.14)
    if bow > 0:
        ctx.set_source_rgba(0, 0, 0, 0.25 * bow)
        ctx.paint()


# ---------------------------------------------------------------- 3. the omikuji

SLIP_W, SLIP_H = 380, 600
FORTUNES = (('LUCKY CHANNEL', '19, obviously.'), ('LOST ITEM', 'The remote. Check the couch.'),
            ('SPORTS', 'Your team, in overtime.'), ('ADVERTS', 'None. Very fortunate.'))


@lru_cache(maxsize=None)
def slip_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, SLIP_W, SLIP_H)
    ctx = cairo.Context(surface)
    ctx.rectangle(0, 0, SLIP_W, SLIP_H)
    ctx.set_source_rgb(*PAPER)
    ctx.fill()
    rand = random.Random(19)
    for k in range(500):                                             # washi fibres
        x, y = rand.uniform(0, SLIP_W), rand.uniform(0, SLIP_H)
        a = rand.uniform(0, math.pi)
        ctx.move_to(x, y)
        ctx.line_to(x + math.cos(a) * 9, y + math.sin(a) * 9)
    ctx.set_source_rgba(0.75, 0.68, 0.55, 0.25)
    ctx.set_line_width(0.8)
    ctx.stroke()
    for inset, width in ((12, 4), (20, 1.5)):
        ctx.rectangle(inset, inset, SLIP_W - 2 * inset, SLIP_H - 2 * inset)
        ctx.set_source_rgb(*RED)
        ctx.set_line_width(width)
        ctx.stroke()
    jp(ctx, 22, bold=True)
    ctx.set_source_rgb(*RED)
    centred(ctx, '第十九番   おみくじ', SLIP_W / 2, 62)
    ctx.fill()
    ctx.move_to(50, 84)
    ctx.line_to(SLIP_W - 50, 84)
    ctx.set_line_width(1.5)
    ctx.stroke()
    font(ctx, 'Nimbus Sans', 15)
    ctx.set_source_rgb(*RED)
    text_path(ctx, 'DAIKICHI  ·  GREAT BLESSING', SLIP_W / 2, 252, tracking=2.0, align='center')
    ctx.fill()
    ctx.move_to(50, 272)
    ctx.line_to(SLIP_W - 50, 272)
    ctx.set_line_width(1.5)
    ctx.stroke()
    font(ctx, 'URW Gothic', 32)
    ctx.set_source_rgb(*INK)
    text_path(ctx, 'VIZELVISION 19', SLIP_W / 2, 314, tracking=1.0, align='center')
    ctx.fill()
    y = 350
    for label, text in FORTUNES:
        font(ctx, 'Nimbus Sans', 14)
        ctx.set_source_rgb(*RED)
        text_path(ctx, label, 46, y, tracking=2.0)
        ctx.fill()
        font(ctx, 'URW Bookman', 19, bold=False, italic=True)
        ctx.set_source_rgb(*INK)
        text_path(ctx, text, 46, y + 26)
        ctx.fill()
        y += 52
    jp(ctx, 18)
    ctx.set_source_rgb(*RED)
    centred(ctx, 'ヴィズルヴィジョン神社', SLIP_W / 2, SLIP_H - 36)
    ctx.fill()
    return surface


@lru_cache(maxsize=None)
def counter_back():
    """Behind the slip: the shrine's dim interior, out of focus, warm lanterns."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, H)
    g.add_color_stop_rgb(0, 0.3, 0.17, 0.1)
    g.add_color_stop_rgb(1, 0.14, 0.08, 0.05)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(8)
    for k in range(26):                                              # bokeh
        x, y, r = rand.uniform(0, W), rand.uniform(0, H), rand.uniform(30, 90)
        b = cairo.RadialGradient(x, y, 0, x, y, r)
        colour = rand.choice(((1.0, 0.7, 0.35), (1.0, 0.45, 0.25), (1.0, 0.85, 0.6)))
        b.add_color_stop_rgba(0, *colour, 0.35)
        b.add_color_stop_rgba(0.85, *colour, 0.25)
        b.add_color_stop_rgba(1, *colour, 0)
        ctx.set_source(b)
        ctx.arc(x, y, r, 0, TAU)
        ctx.fill()
    return surface


def omikuji(ctx, t):
    ctx.set_source_surface(counter_back(), 0, 0)
    ctx.paint()
    drift = 8 * math.sin(t * 1.3)
    x0, y0 = W / 2 - SLIP_W / 2, 60 + drift
    shown = SLIP_H * ease_in_out(span(t, *UNROLL)) + 40
    shown = min(SLIP_H, shown)
    ctx.save()                                                       # its shadow, then the paper
    ctx.rectangle(x0 + 10, y0 + 10, SLIP_W, shown)
    ctx.set_source_rgba(0, 0, 0, 0.4)
    ctx.fill()
    ctx.rectangle(x0, y0, SLIP_W, shown)
    ctx.clip()
    ctx.set_source_surface(slip_surface(), x0, y0)
    ctx.paint()
    ctx.restore()
    # 大吉, stamped in big on the beat.
    p = span(t, DAIKICHI - 0.06, DAIKICHI + 0.12)
    if p > 0:
        k = back_out(p) * (1 + 0.6 * (1 - ease_out(p)))
        ctx.save()
        ctx.translate(W / 2, y0 + 160)
        ctx.scale(k, k)
        jp(ctx, 140, bold=True)
        centred(ctx, '大吉', 0, 50)
        ctx.set_source_rgb(*RED)
        ctx.fill()
        ctx.restore()
        burst = span(t, DAIKICHI, DAIKICHI + 0.7)
        if burst < 1:                                                # a ring of the station's confetti
            rand = random.Random(19)
            for j in range(18):
                a = j * TAU / 18 + rand.uniform(-0.1, 0.1)
                r = 120 + 330 * ease_out(burst) * rand.uniform(0.8, 1.2)
                x, y = W / 2 + math.cos(a) * r, y0 + 160 + math.sin(a) * r * 0.8
                colour = (PINK, TEAL, YELLOW, WHITE)[j % 4]
                ctx.save()
                ctx.translate(x, y)
                ctx.rotate(a + burst * 4)
                if j % 3 == 0:
                    star(ctx, 0, 0, 18)
                elif j % 3 == 1:
                    ctx.arc(0, 0, 10, 0, TAU)
                else:
                    ctx.rectangle(-12, -5, 24, 10)
                ctx.push_group()
                inked(ctx, colour, 3, (3, 3))
                ctx.pop_group_to_source()
                ctx.paint_with_alpha(1 - ease_in(burst))
                ctx.restore()
    # The roll at the bottom edge while it unrolls, and the hands holding the top.
    if shown < SLIP_H:
        rounded_rect(ctx, x0 - 6, y0 + shown - 14, SLIP_W + 12, 28, 14)
        roll = cairo.LinearGradient(0, y0 + shown - 14, 0, y0 + shown + 14)
        roll.add_color_stop_rgb(0, *PAPER)
        roll.add_color_stop_rgb(1, 0.75, 0.7, 0.6)
        inked(ctx, roll, 2, (3, 3))
    hold_y = y0 + max(140, shown) - 40                               # thumbs on the front, at the lower corners
    for side in (-1, 1):
        ctx.save()
        ctx.translate(W / 2 + side * (SLIP_W / 2 + 8), hold_y)
        ctx.rotate(side * 0.35)
        rounded_rect(ctx, -34, -20, 68, 300, 22)                    # the sleeve, down out of frame
        ctx.translate(0, 0)
        ctx.restore()
        ctx.save()
        ctx.translate(W / 2 + side * (SLIP_W / 2 + 14), hold_y + 60)
        ctx.rotate(side * 0.3)
        rounded_rect(ctx, -40, 30, 80, 320, 20)
        inked(ctx, SLEEVE, 4, (4, 4))
        rounded_rect(ctx, -34, -60, 68, 110, 30)
        inked(ctx, SKIN, 4, (4, 4))
        ctx.restore()
        ctx.save()                                                   # the thumb over the paper's edge
        ctx.translate(W / 2 + side * (SLIP_W / 2 - 14), hold_y - 4)
        ctx.rotate(-side * 0.5)
        rounded_rect(ctx, -12, -30, 26, 62, 13)
        inked(ctx, SKIN, 3, (3, 3))
        ctx.restore()


# ---------------------------------------------------------------- 4. the ema rack

WISHES = (('May the game not cut to commercial', 'tv'), ('More cat', 'cat'), ('Commanders win (just once)', 'ball'),
          ('Good captions for Grandma', 'tv'), ('Please find the remote', 'remote'), ('No more mattress ads', 'tv'),
          ('Pass my driving test', 'cat'), ('VizelVision forever', 'heart'), ('Snow day on Monday', 'ball'))


@lru_cache(maxsize=None)
def ema_surface(index):
    text, picture = WISHES[index]
    w, h = 250, 170
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w + 20, h + 20)
    ctx = cairo.Context(surface)
    ctx.translate(6, 6)
    ctx.move_to(0, 40)
    ctx.line_to(w / 2, 0)
    ctx.line_to(w, 40)
    ctx.line_to(w, h)
    ctx.line_to(0, h)
    ctx.close_path()
    g = cairo.LinearGradient(0, 0, 0, h)
    g.add_color_stop_rgb(0, 0.9, 0.76, 0.55)
    g.add_color_stop_rgb(1, 0.78, 0.6, 0.4)
    inked(ctx, g, 3, (5, 5))
    ctx.arc(w / 2, 26, 5, 0, TAU)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.save()                                                       # its little picture
    ctx.translate(w / 2, 68)
    if picture == 'tv':
        ctx.scale(0.13, 0.13)
        A.draw_tv(ctx, 0.0, 1, 0.0)
    elif picture == 'cat':
        ctx.arc(0, 4, 22, 0, TAU)
        for side in (-1, 1):
            ctx.move_to(side * 20, -6)
            ctx.line_to(side * 16, -32)
            ctx.line_to(side * 4, -16)
        inked(ctx, (1.0, 0.6, 0.2), 3, (2, 2))
        for side in (-1, 1):
            ctx.arc(side * 8, 2, 3, 0, TAU)
            ctx.set_source_rgb(*INK)
            ctx.fill()
    elif picture == 'ball':
        ctx.save()
        ctx.scale(1.5, 1)
        ctx.arc(0, 0, 16, 0, TAU)
        ctx.restore()
        inked(ctx, (0.55, 0.28, 0.14), 3, (2, 2))
        ctx.move_to(-10, 0)
        ctx.line_to(10, 0)
        ctx.set_source_rgb(*WHITE)
        ctx.set_line_width(2)
        ctx.stroke()
    elif picture == 'remote':
        rounded_rect(ctx, -12, -28, 24, 56, 6)
        inked(ctx, (0.18, 0.18, 0.2), 3, (2, 2))
        ctx.arc(0, -16, 4, 0, TAU)
        ctx.set_source_rgb(*RED)
        ctx.fill()
    else:
        ctx.move_to(0, 22)
        ctx.curve_to(-40, -6, -18, -36, 0, -14)
        ctx.curve_to(18, -36, 40, -6, 0, 22)
        inked(ctx, PINK, 3, (2, 2))
    ctx.restore()
    font(ctx, 'Z003', 23, bold=False)
    ctx.set_source_rgb(0.12, 0.1, 0.18)
    words = text.split()
    lines, line = [], ''
    for word in words:
        trial = (line + ' ' + word).strip()
        if ctx.text_extents(trial).x_advance > w - 30 and line:
            lines.append(line)
            line = word
        else:
            line = trial
    lines.append(line)
    for k, ln in enumerate(lines[:2]):
        text_path(ctx, ln, w / 2, 128 + k * 24, align='center')
    ctx.fill()
    return surface


@lru_cache(maxsize=None)
def rack_back():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W + 400, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, H)
    g.add_color_stop_rgb(0, 0.82, 0.68, 0.48)
    g.add_color_stop_rgb(1, 0.48, 0.38, 0.26)
    ctx.set_source(g)
    ctx.paint()
    for x in (60, 330, 900, 1250, 1560):
        cedar(ctx, x, 720, 70, top=-20, colour=mix(BARK, (0.85, 0.7, 0.5), 0.35))
    for y in (120, 360):                                             # the rack's rails, under a little roof
        rounded_rect(ctx, -20, y, W + 440, 18, 4)
        inked(ctx, WOOD, 3, (0, 5))
    ctx.move_to(-20, 100)
    ctx.line_to(W + 420, 100)
    ctx.line_to(W + 420, 80)
    ctx.line_to(-20, 80)
    ctx.close_path()
    inked(ctx, (0.25, 0.18, 0.13), 3, (0, 5))
    for x in range(40, W + 400, 300):
        ctx.rectangle(x, 80, 18, 640)
        inked(ctx, WOOD, 3, (5, 0))
    return surface


def ema(ctx, t):
    pan = -380 * ease_in_out(span(t, *PAN))
    ctx.set_source_surface(rack_back(), pan, 0)
    ctx.paint()
    for k in range(len(WISHES) * 2):
        index = k % len(WISHES)
        row = k % 2
        x = 40 + k * 104 + pan + row * 30
        if x < -300 or x > W + 50:
            continue
        y = 128 if row == 0 else 368
        sway = 0.05 * math.sin(t * 1.8 + k * 1.3)
        ctx.save()
        ctx.translate(x + 125, y + 6)
        ctx.rotate(sway)
        ctx.move_to(0, 0)
        ctx.line_to(0, 26)
        ctx.set_source_rgb(*RED)
        ctx.set_line_width(2.5)
        ctx.stroke()
        ctx.set_source_surface(ema_surface(index), -131, 14)
        ctx.paint()
        ctx.restore()
    # In front: the line of tied fortunes, nearer, panning faster.
    near = -620 * ease_in_out(span(t, *PAN))
    ctx.move_to(-20, 618)
    ctx.line_to(W + 20, 618)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(5)
    ctx.stroke()
    rand = random.Random(6)
    for k in range(40):
        x = 10 + k * 46 + near + rand.uniform(-8, 8)
        if x < -60 or x > W + 60:
            continue
        ctx.save()
        ctx.translate(x, 618)
        ctx.rotate(rand.uniform(-0.25, 0.25))
        rounded_rect(ctx, -9, -34, 18, 68, 4)
        inked(ctx, PAPER, 2.5, (3, 3))
        ctx.rectangle(-11, -6, 22, 12)
        ctx.set_source_rgb(*mix(PAPER, INK, 0.12))
        ctx.fill()
        ctx.restore()


# ---------------------------------------------------------------- 5. dusk at the torii

DUSK_S, DUSK_GY, DUSK_CX = 95.0, 640.0, 640.0
CHOCHIN = (-1.65, -0.55, 0.55, 1.65)                 # paper lanterns along the nuki, m from the middle


@lru_cache(maxsize=None)
def dusk_back():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, 470)
    g.add_color_stop_rgb(0, 0.1, 0.1, 0.28)
    g.add_color_stop_rgb(0.55, 0.42, 0.24, 0.42)
    g.add_color_stop_rgb(0.85, 0.95, 0.52, 0.35)
    g.add_color_stop_rgb(1, 1.0, 0.72, 0.42)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(12)
    for k in range(50):
        ctx.arc(rand.uniform(0, W), rand.uniform(0, 220), rand.uniform(0.6, 1.5), 0, TAU)
        ctx.set_source_rgba(1, 0.97, 0.9, rand.uniform(0.3, 0.9))
        ctx.fill()
    ctx.arc(1090, 110, 34, 0, TAU)                                   # the moon
    ctx.set_source_rgb(1.0, 0.96, 0.82)
    ctx.fill()
    for k in range(60):                                              # cedars in silhouette
        x = rand.uniform(-40, W + 40)
        if 300 < x < 980 and rand.random() < 0.7:
            continue
        h = rand.uniform(200, 420)
        ctx.move_to(x, 470 - h)
        ctx.line_to(x - h * 0.2, 480)
        ctx.line_to(x + h * 0.2, 480)
        ctx.close_path()
        ctx.set_source_rgb(*mix((0.05, 0.06, 0.12), (0.2, 0.15, 0.25), rand.random() * 0.5))
        ctx.fill()
    ctx.rectangle(0, 470, W, H - 470)
    ctx.set_source_rgb(0.12, 0.11, 0.16)
    ctx.fill()
    # The path to the torii, and the shrine glowing far beyond.
    ctx.move_to(560, 470)
    ctx.line_to(720, 470)
    ctx.line_to(980, H)
    ctx.line_to(300, H)
    ctx.close_path()
    path = cairo.LinearGradient(0, 470, 0, H)
    path.add_color_stop_rgb(0, 0.42, 0.36, 0.36)
    path.add_color_stop_rgb(1, 0.25, 0.22, 0.25)
    ctx.set_source(path)
    ctx.fill()
    ctx.rectangle(612, 430, 56, 40)
    ctx.set_source_rgb(0.2, 0.12, 0.14)
    ctx.fill()
    ctx.move_to(600, 432)
    ctx.line_to(640, 412)
    ctx.line_to(680, 432)
    ctx.close_path()
    ctx.fill()
    ctx.rectangle(630, 442, 20, 18)
    ctx.set_source_rgb(0.4, 0.95, 0.95)
    ctx.fill()
    return surface


def chochin(ctx, x, y, lit, hang=330):
    ctx.save()
    ctx.move_to(x, hang)
    ctx.line_to(x, y - 34)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(2)
    ctx.stroke()
    ctx.translate(x, y)
    ctx.save()
    ctx.scale(1, 1.25)
    ctx.arc(0, 0, 26, 0, TAU)
    ctx.restore()
    body = cairo.RadialGradient(0, -4, 2, 0, 0, 34)
    body.add_color_stop_rgb(0, *mix((0.55, 0.12, 0.1), (1.0, 0.95, 0.7), lit))
    body.add_color_stop_rgb(1, *mix((0.38, 0.06, 0.06), (0.95, 0.35, 0.15), lit))
    inked(ctx, body, 3, (3, 3))
    for yy in (-30, 25):
        rounded_rect(ctx, -15, yy, 30, 8, 3)
        inked(ctx, LACQUER, 2, (0, 0))
    jp(ctx, 20, bold=True)
    ctx.set_source_rgb(*mix((0.3, 0.05, 0.05), INK, lit * 0.5))
    centred(ctx, '十九', 0, 8)
    ctx.fill()
    if lit > 0:
        ctx.set_operator(cairo.OPERATOR_ADD)
        g = cairo.RadialGradient(0, 0, 0, 0, 0, 120)
        g.add_color_stop_rgba(0, 1.0, 0.6, 0.25, 0.45 * lit)
        g.add_color_stop_rgba(1, 1.0, 0.4, 0.1, 0)
        ctx.set_source(g)
        ctx.arc(0, 0, 120, 0, TAU)
        ctx.fill()
    ctx.restore()


def fireflies(ctx, t):
    rand = random.Random(33)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for k in range(26):
        x0, y0 = rand.uniform(0, W), rand.uniform(380, 700)
        fx, fy, ph = rand.uniform(0.2, 0.6), rand.uniform(0.3, 0.8), rand.uniform(0, TAU)
        x = x0 + 40 * math.sin(t * fx + ph)
        y = y0 + 25 * math.sin(t * fy + ph * 2)
        glow = 0.5 + 0.5 * math.sin(t * rand.uniform(2, 4) + ph)
        g = cairo.RadialGradient(x, y, 0, x, y, 14)
        g.add_color_stop_rgba(0, 0.85, 1.0, 0.45, 0.9 * glow)
        g.add_color_stop_rgba(1, 0.6, 1.0, 0.3, 0)
        ctx.set_source(g)
        ctx.arc(x, y, 14, 0, TAU)
        ctx.fill()
    ctx.restore()


def dusk(ctx, t):
    ctx.set_source_surface(dusk_back(), 0, 0)
    ctx.paint()
    lit_path = ease_out(span(t, DUSK_IN[0], DUSK_IN[1] + 0.5))
    for side in (-1, 1):                                             # stone lanterns either side of the path
        stone_lantern(ctx, 640 + side * 520, 700, 95, lit_path)
        stone_lantern(ctx, 640 + side * 380, 560, 55, lit_path)
    s, gy = DUSK_S, DUSK_GY
    torii(ctx, DUSK_CX, gy, s, ink=3.5)
    shimenawa(ctx, DUSK_CX - 2.1 * s, DUSK_CX + 2.1 * s, gy - 4.06 * s, 0.32 * s, 0.1 * s, t, shide=4)
    hang = gy - 3.25 * s                                             # a line strung between the pillars
    ctx.move_to(DUSK_CX - 2.0 * s, hang - 6)
    ctx.curve_to(DUSK_CX - 0.7 * s, hang + 10, DUSK_CX + 0.7 * s, hang + 10, DUSK_CX + 2.0 * s, hang - 6)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(2.5)
    ctx.stroke()
    for k, mx in enumerate(CHOCHIN):
        lit = ease_out(span(t, LANTERNS[k] - 0.02, LANTERNS[k] + 0.12))
        flicker = 1 - 0.06 * (0.5 + 0.5 * math.sin(t * 13 + k * 2)) if lit > 0 else 1
        swing = 2 * math.sin(t * 1.6 + k)
        chochin(ctx, DUSK_CX + mx * s + swing, hang + 52 + (6 if k in (1, 2) else 0), lit * flicker, hang + 4)
    fireflies(ctx, t)
    neighborhood.lockup(ctx, t, CLOSED, 555, scale=0.62)
    k = ease_out(span(t, *KATAKANA))
    if k > 0:
        rise = 12 * (1 - k)
        ctx.save()
        for dx, dy, colour in ((3, 3, (*INK, 0.9 * k)), (0, 0, (1.0, 1.0, 1.0, k))):
            jp(ctx, 42, bold=True)
            centred(ctx, 'ヴィズルヴィジョン', W / 2 + dx, 616 + rise + dy)
            ctx.set_source_rgba(*colour)
            ctx.fill()
            font(ctx, 'Nimbus Sans', 22)
            text_path(ctx, 'CHANNEL 19', W / 2 + dx, 660 + rise + dy, tracking=8, align='center')
            ctx.set_source_rgba(*(colour if dx else (*YELLOW, k)))
            ctx.fill()
        ctx.restore()


# ---------------------------------------------------------------- the frame

def scene(ctx, t, draw, alpha):
    if alpha <= 0:
        return
    if alpha >= 1:
        draw(ctx, t)
        return
    ctx.push_group()
    draw(ctx, t)
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(alpha)


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    # Each scene dissolves in over the one before; once it is opaque, the one before stops.
    if t < SHRINE_IN[1]:
        approach(ctx, t)
    if t < SLIP_IN[1]:
        scene(ctx, t, shrine, ease_in_out(span(t, *SHRINE_IN)))
    if t < EMA_IN[1]:
        scene(ctx, t, omikuji, ease_in_out(span(t, *SLIP_IN)))
    if t < DUSK_IN[1]:
        scene(ctx, t, ema, ease_in_out(span(t, *EMA_IN)))
    scene(ctx, t, dusk, ease_in_out(span(t, *DUSK_IN)))
    vignette(ctx, 0.35)
    grain(ctx, frame, 0.2)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
