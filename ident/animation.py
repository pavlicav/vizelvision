"""The VizelVision station ID picture, drawn frame by frame with cairo.

A 1990s network ID: channel-change snow, a sunburst over a neon grid floor,
Memphis-style confetti, a chrome-and-teal TV emblem that spins in and lands on
the orchestra hit, a wordmark that slams in letter by letter, a lens flare, a
key-change colour shift, and an iris-out to black.

    python3 animation.py --still 5.0 frame.png     one frame, for checking
Frames for the encoder come from render(frame) (BGRx bytes); see build.py.
"""
import argparse
import math
import random
import sys
from functools import lru_cache
from pathlib import Path

import cairo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import timeline as T  # noqa: E402

W, H = T.WIDTH, T.HEIGHT
TAU = math.tau
HORIZON = 470
EMBLEM = (640, 272)

INK = (0.07, 0.02, 0.13)
PINK = (1.0, 0.2, 0.58)
YELLOW = (1.0, 0.86, 0.12)
TEAL = (0.0, 0.8, 0.74)
CYAN = (0.25, 0.8, 1.0)
ORANGE = (1.0, 0.5, 0.12)
LIME = (0.62, 0.95, 0.22)
WHITE = (1.0, 1.0, 1.0)

# The end card's banner. My ads' break card draws the same frame with other words (roku_stream/my_ads.py).
TAGLINE_TEXT = 'STAY TUNED'

SKY_A = ((0.07, 0.03, 0.2), (0.24, 0.07, 0.45), (0.8, 0.1, 0.5))    # Indigo to magenta.
SKY_B = ((0.02, 0.08, 0.24), (0.04, 0.3, 0.48), (0.98, 0.65, 0.1))  # After the key change: navy to gold.


# ---------------------------------------------------------------- easing

def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def span(t, a, b):
    return clamp((t - a) / (b - a))


def ease_out(x, power=3):
    return 1 - (1 - x) ** power


def ease_in(x, power=3):
    return x ** power


def ease_in_out(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def back_out(x, s=1.9):
    x -= 1
    return 1 + x * x * ((s + 1) * x + s)


def elastic_out(x):
    if x <= 0 or x >= 1:
        return clamp(x)
    return 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * TAU / 3) + 1


def mix(a, b, k):
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def pulse(t, at, length):
    """1 at `at`, decaying to 0 over `length` seconds; 0 before."""
    return 0.0 if t < at else max(0.0, 1 - (t - at) / length) ** 2


def colour_shift(t):
    return ease_in_out(span(t, T.BUILD + 1.0, T.KEY_CHANGE))


# ---------------------------------------------------------------- paths

def rounded_rect(ctx, x, y, w, h, r):
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -TAU / 4, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, TAU / 4)
    ctx.arc(x + r, y + h - r, r, TAU / 4, TAU / 2)
    ctx.arc(x + r, y + r, r, TAU / 2, 3 * TAU / 4)
    ctx.close_path()


def star(ctx, x, y, r, rotation=0.0, pinch=0.16):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rotation)
    ctx.move_to(0, -r)
    for i in range(4):
        a = i * TAU / 4
        ctx.line_to(math.cos(a - TAU / 8) * r * pinch, math.sin(a - TAU / 8) * r * pinch)
        ctx.line_to(math.cos(a) * r, math.sin(a) * r)
    ctx.close_path()
    ctx.restore()


def inked(ctx, fill, outline=6, shadow=(7, 7), fatten=0):
    """Flat colour, black outline and a hard drop shadow: the Memphis look.
    fatten thickens the face with its own colour, keeping the outline outside it."""
    path = ctx.copy_path()
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    edge = fatten + 2 * outline if fatten else outline
    for dx, dy, rgba in ((*shadow, (*INK, 0.85)), (0, 0, (*INK, 1))):
        ctx.save()
        ctx.translate(dx, dy)
        ctx.new_path()
        ctx.append_path(path)
        ctx.set_source_rgba(*rgba)
        ctx.set_line_width(edge)
        ctx.fill_preserve()
        ctx.stroke()
        ctx.restore()
    ctx.new_path()
    ctx.append_path(path)
    if isinstance(fill, cairo.Pattern):
        ctx.set_source(fill)
    else:
        ctx.set_source_rgb(*fill)
    if fatten:
        ctx.set_line_width(fatten)
        ctx.fill_preserve()
        ctx.stroke()
        return
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(outline)
    ctx.stroke()


def inked_stroke(ctx, colour, width, shadow=(6, 6)):
    path = ctx.copy_path()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    for dx, dy, rgba, w in ((*shadow, (*INK, 0.85), width + 8), (0, 0, (*INK, 1), width + 8),
                            (0, 0, (*colour, 1), width)):
        ctx.save()
        ctx.translate(dx, dy)
        ctx.new_path()
        ctx.append_path(path)
        ctx.set_source_rgba(*rgba)
        ctx.set_line_width(w)
        ctx.stroke()
        ctx.restore()
    ctx.new_path()


def chrome(y0, y1, tint=0.0):
    """The eighties-into-nineties chrome: bright sky, hard horizon, warm floor."""
    g = cairo.LinearGradient(0, y0, 0, y1)
    for stop, rgb in ((0.0, (1, 1, 1)), (0.42, (0.62, 0.78, 0.98)), (0.5, (0.12, 0.13, 0.36)),
                      (0.56, (0.4, 0.2, 0.55)), (0.8, (0.98, 0.55, 0.78)), (1.0, (1, 0.95, 0.9))):
        g.add_color_stop_rgb(stop, *mix(rgb, (1.0, 0.85, 0.5), tint * 0.35))
    return g


def font(ctx, family, size, bold=True, italic=False):
    ctx.select_font_face(family, cairo.FONT_SLANT_ITALIC if italic else cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)


# ---------------------------------------------------------------- static layers

@lru_cache(maxsize=None)
def snow(index):
    rand = random.Random(index)
    w, h = W // 4, H // 4
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_RGB24, w)
    data = bytearray(stride * h)
    grey = rand.randbytes(w * h)
    for y in range(h):
        band = 1.35 if (y + index * 7) % 45 < 6 else 1.0
        row = y * stride
        for x in range(w):
            v = min(255, int(grey[y * w + x] * band))
            data[row + 4 * x:row + 4 * x + 3] = bytes((v, v, v))
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, w, h, stride)


@lru_cache(maxsize=None)
def overlay():
    """CRT scanlines and a vignette, composited over every frame."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgba(0, 0, 0, 0.14)
    for y in range(0, H, 3):
        ctx.rectangle(0, y, W, 1)
    ctx.fill()
    vignette = cairo.RadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, W * 0.72)
    vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
    vignette.add_color_stop_rgba(1, 0, 0, 0, 0.55)
    ctx.set_source(vignette)
    ctx.paint()
    return surface


@lru_cache(maxsize=None)
def wordmark_layout():
    """Letter positions for the wordmark, sized to span about two thirds of the frame."""
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 8, 8))
    letters = [(ch, 0) for ch in T.WORDMARK[0]] + [(ch, 1) for ch in T.WORDMARK[1]]
    size = 120.0
    for _ in range(2):
        font(ctx, 'URW Gothic', size)
        tracking = size * 0.07  # Room for the fattened faces and their outlines.
        advances = [ctx.text_extents(ch).x_advance + tracking for ch, _ in letters]
        total = sum(advances) - tracking
        size *= 900 / total
    font(ctx, 'URW Gothic', size)
    x = (W - total) / 2
    layout = []
    for (ch, part), advance in zip(letters, advances):
        ext = ctx.text_extents(ch)
        layout.append({'ch': ch, 'part': part, 'x': x, 'w': ext.width, 'bearing': ext.x_bearing})
        x += advance
    return size, layout


BASELINE = 578

SHAPES = (  # x, y, kind, colour, size, turn, spin, beat it pops on
    (150, 150, 'squiggle', YELLOW, 95, -0.3, 0.35, 0),
    (1085, 205, 'triangle', TEAL, 70, 0.2, -0.5, 1),
    (250, 395, 'circle', PINK, 34, 0.0, 0.0, 2),
    (1135, 370, 'zigzag', WHITE, 72, 0.5, 0.25, 3),
    (120, 640, 'dots', CYAN, 64, 0.1, 0.15, 4),
    (1170, 640, 'half', ORANGE, 52, 0.8, -0.4, 5),
    (395, 105, 'plus', LIME, 30, 0.3, 0.9, 6),
    (890, 95, 'ring', PINK, 30, 0.0, 0.0, 7),
    (60, 330, 'triangle', YELLOW, 44, 1.2, 0.6, 7.5),
    (1225, 330, 'pill', CYAN, 50, 0.6, -0.3, 6.5),
)

GLINTS = ((8.2, 7), (10.7, 9), (14.1, 0), (18.9, 10), (22.6, 3))  # (time, letter)


# ---------------------------------------------------------------- scene pieces

def sky(ctx, t):
    k = colour_shift(t)
    top, middle, horizon = (mix(a, b, k) for a, b in zip(SKY_A, SKY_B))
    g = cairo.LinearGradient(0, 0, 0, HORIZON)
    g.add_color_stop_rgb(0, *top)
    g.add_color_stop_rgb(0.55, *middle)
    g.add_color_stop_rgb(1, *horizon)
    ctx.set_source(g)
    ctx.rectangle(0, 0, W, HORIZON)
    ctx.fill()


def sunburst_angle(t):
    # Turns slowly, then faster through the build; integrated so it never jumps.
    fast = max(0.0, min(t, T.KEY_CHANGE) - T.BUILD)
    return 0.12 * t + 0.35 * fast ** 2 / (T.KEY_CHANGE - T.BUILD) + 0.35 * max(0.0, t - T.KEY_CHANGE)


def sunburst(ctx, t):
    grow = ease_out(span(t, T.START, T.START + 0.9))
    if grow <= 0:
        return
    ctx.save()
    ctx.rectangle(0, 0, W, HORIZON)
    ctx.clip()
    cx, cy = EMBLEM
    rays, reach = 22, 1500 * grow
    angle = sunburst_angle(t)
    for i in range(rays):
        a = angle + i * TAU / rays
        ctx.move_to(cx, cy)
        ctx.line_to(cx + math.cos(a) * reach, cy + math.sin(a) * reach)
        ctx.line_to(cx + math.cos(a + TAU / rays / 2) * reach, cy + math.sin(a + TAU / rays / 2) * reach)
        ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.07 + 0.05 * colour_shift(t))
    ctx.fill()
    glow = cairo.RadialGradient(cx, cy, 0, cx, cy, 420)
    glow.add_color_stop_rgba(0, 1, 0.9, 1, 0.35 * grow)
    glow.add_color_stop_rgba(1, 1, 0.9, 1, 0)
    ctx.set_source(glow)
    ctx.paint()
    ctx.restore()


def floor(ctx, t):
    k = colour_shift(t)
    g = cairo.LinearGradient(0, HORIZON, 0, H)
    g.add_color_stop_rgb(0, *mix((0.42, 0.05, 0.36), (0.3, 0.2, 0.1), k))
    g.add_color_stop_rgb(1, *mix((0.06, 0.0, 0.1), (0.02, 0.03, 0.08), k))
    ctx.set_source(g)
    ctx.rectangle(0, HORIZON, W, H - HORIZON)
    ctx.fill()
    line = mix(CYAN, (1.0, 0.8, 0.3), k)
    ctx.set_line_cap(cairo.LINE_CAP_BUTT)
    for i in range(-14, 15):
        ctx.move_to(W / 2 + i * 22, HORIZON)
        ctx.line_to(W / 2 + i * 190, H + 40)
    ctx.set_source_rgba(*line, 0.45)
    ctx.set_line_width(2)
    ctx.stroke()
    speed = 1.6 + 2.5 * ease_in(span(t, T.BUILD, T.KEY_CHANGE), 2)
    scroll = (t * speed) % 1.0
    for j in range(16):
        z = j + 1 - scroll
        if z < 0.8:
            continue
        y = HORIZON + 250 / z
        if y > H + 4:
            continue
        ctx.move_to(0, y)
        ctx.line_to(W, y)
        ctx.set_source_rgba(*line, clamp(0.75 / z ** 0.6))
        ctx.set_line_width(max(1.0, 3.2 / z))
        ctx.stroke()
    haze = cairo.LinearGradient(0, HORIZON - 30, 0, HORIZON + 40)
    haze.add_color_stop_rgba(0, 1, 1, 1, 0)
    haze.add_color_stop_rgba(0.43, *mix((1, 0.6, 0.9), (1, 0.9, 0.6), k), 0.55)
    haze.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(haze)
    ctx.rectangle(0, HORIZON - 30, W, 70)
    ctx.fill()


def shape_path(ctx, kind, size):
    if kind == 'squiggle':
        ctx.move_to(-size, 0)
        for i in range(1, 41):
            x = -size + 2 * size * i / 40
            ctx.line_to(x, math.sin(i / 40 * TAU * 1.5) * size * 0.22)
    elif kind == 'zigzag':
        ctx.move_to(-size, size * 0.15)
        for i in range(1, 7):
            ctx.line_to(-size + 2 * size * i / 6, size * (0.15 if i % 2 == 0 else -0.15))
    elif kind == 'triangle':
        for i in range(3):
            a = -TAU / 4 + i * TAU / 3
            (ctx.move_to if i == 0 else ctx.line_to)(math.cos(a) * size * 0.6, math.sin(a) * size * 0.6)
        ctx.close_path()
    elif kind in ('circle', 'ring'):
        ctx.arc(0, 0, size, 0, TAU)
    elif kind == 'half':
        ctx.arc(0, 0, size, TAU / 2, TAU)
        ctx.close_path()
    elif kind == 'plus':
        for x, y, w, h in ((-size, -size * 0.3, 2 * size, size * 0.6), (-size * 0.3, -size, size * 0.6, 2 * size)):
            ctx.rectangle(x, y, w, h)
    elif kind == 'pill':
        rounded_rect(ctx, -size, -size * 0.32, 2 * size, size * 0.64, size * 0.32)


def confetti(ctx, t):
    build = max(0.0, min(t, T.KEY_CHANGE) - T.BUILD) ** 2 / 4 + max(0.0, t - T.KEY_CHANGE)
    for i, (x, y, kind, colour, size, turn, spin, beat) in enumerate(SHAPES):
        pop = span(t, T.beat(beat), T.beat(beat) + 0.45)
        if pop <= 0:
            continue
        scale = back_out(pop, 2.6)
        x += 14 * math.sin(0.7 * t + i * 1.7)
        y += 10 * math.cos(0.9 * t + i * 2.3)
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(turn + spin * t + 1.4 * spin * build + (1 - pop) * 2.5)
        ctx.scale(scale, scale)
        if kind == 'dots':
            for r in range(4):
                for c in range(4):
                    ctx.new_sub_path()
                    ctx.arc((c - 1.5) * size * 0.5, (r - 1.5) * size * 0.5, size * 0.09, 0, TAU)
            inked(ctx, colour, 3, (4, 4))
        elif kind in ('squiggle', 'zigzag'):
            shape_path(ctx, kind, size)
            inked_stroke(ctx, colour, 11)
        elif kind in ('triangle', 'ring'):
            shape_path(ctx, kind, size)
            inked_stroke(ctx, colour, 10)
        else:
            shape_path(ctx, kind, size)
            inked(ctx, colour)
        ctx.restore()


def emblem_pose(t):
    """(x, y, scale, spin angle, tilt) of the TV emblem."""
    x, y = EMBLEM
    if t < T.LOGO_FLIGHT:
        return None
    if t < T.HIT:
        p = span(t, T.LOGO_FLIGHT, T.HIT)
        return x, y + 60 * (1 - p), 0.04 + 1.08 * ease_in(p, 2.2), 3 * TAU * ease_out(p, 2), 0.0
    settle = elastic_out(span(t, T.HIT, T.HIT + 0.9))
    scale = 1.12 - 0.12 * settle
    bob = math.sin(TAU * (t - T.HIT) / 4) * 6
    tilt = math.sin(TAU * (t - T.HIT) / 5.5) * 0.025
    spin = TAU * ease_in_out(span(t, T.KEY_CHANGE, T.KEY_CHANGE + 1.0))
    squash = pulse(t, T.BUTTON, 0.35)
    scale *= 1 + 0.08 * squash + 0.02 * pulse(t, T.KEY_CHANGE, 0.3)
    return x, y + bob, scale, spin, tilt


def draw_tv(ctx, t, facing, side):
    cabinet = cairo.LinearGradient(0, -110, 0, 110)
    for stop, rgb in ((0, (0.35, 1.0, 0.92)), (0.35, TEAL), (1, (0.0, 0.36, 0.48))):
        cabinet.add_color_stop_rgb(stop, *rgb)
    # Extruded depth, towards the lower right and swinging with the spin.
    ex, ey = 10 * facing + 26 * side, 13
    for k in range(9, 0, -1):
        ctx.save()
        ctx.translate(ex * k / 9, ey * k / 9)
        rounded_rect(ctx, -150, -110, 300, 220, 36)
        ctx.set_source_rgb(*mix(INK, (0.0, 0.25, 0.3), 0.6 * k / 9))
        ctx.fill()
        ctx.restore()
    # Antennae, over the extrusion, under the cabinet.
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    wiggle = math.sin(t * 3.1) * 4
    for tip, ball in (((-98 + wiggle, -212), PINK), ((84 - wiggle, -222), YELLOW)):
        ctx.move_to(0, -118)
        ctx.line_to(*tip)
        inked_stroke(ctx, (0.85, 0.88, 0.95), 5, (4, 4))
        ctx.arc(*tip, 11, 0, TAU)
        inked(ctx, ball, 4, (4, 4))
    ctx.arc(0, -108, 26, TAU / 2, TAU)
    ctx.close_path()
    inked(ctx, PINK, 5, (4, 4))
    for x in (-112, 72):
        ctx.move_to(x, 108)
        ctx.line_to(x + 40, 108)
        ctx.line_to(x + 34, 132)
        ctx.line_to(x + 6, 132)
        ctx.close_path()
        inked(ctx, INK, 3, (0, 0))
    rounded_rect(ctx, -150, -110, 300, 220, 36)
    if facing < 0:  # The back of the set, seen mid-spin.
        inked(ctx, (0.0, 0.42, 0.5), 7, (0, 0))
        ctx.set_source_rgba(*INK, 0.6)
        for i in range(5):
            rounded_rect(ctx, -90, -60 + i * 26, 180, 10, 5)
        ctx.fill()
        return
    inked(ctx, cabinet, 7, (0, 0))
    gloss = cairo.LinearGradient(-150, -110, -40, 0)
    gloss.add_color_stop_rgba(0, 1, 1, 1, 0.45)
    gloss.add_color_stop_rgba(1, 1, 1, 1, 0)
    rounded_rect(ctx, -142, -102, 284, 90, 30)
    ctx.set_source(gloss)
    ctx.fill()
    # Screen with the V on it.
    rounded_rect(ctx, -128, -88, 198, 176, 28)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(10)
    ctx.stroke_preserve()
    glow = cairo.RadialGradient(-29, -12, 8, -29, 0, 140)
    glow.add_color_stop_rgb(0, 0.45, 0.98, 1.0)
    glow.add_color_stop_rgb(0.55, 0.1, 0.45, 0.85)
    glow.add_color_stop_rgb(1, 0.05, 0.08, 0.35)
    ctx.set_source(glow)
    ctx.fill()
    ctx.save()
    rounded_rect(ctx, -128, -88, 198, 176, 28)
    ctx.clip()
    font(ctx, 'URW Gothic', 178)
    ext = ctx.text_extents('V')
    ctx.move_to(-29 - ext.width / 2 - ext.x_bearing, 64)
    ctx.text_path('V')
    inked(ctx, chrome(-66, 64, colour_shift(t)), 6, (6, 6))
    ctx.set_source_rgba(0, 0, 0, 0.18)
    for y in range(-88, 88, 4):
        ctx.rectangle(-128, y, 198, 1.5)
    ctx.fill()
    ctx.move_to(-128, -30)
    ctx.line_to(-128, -88)
    ctx.line_to(-10, -88)
    ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.14)
    ctx.fill()
    ctx.restore()
    # Knobs and speaker grille.
    ctx.arc(108, -54, 16, 0, TAU)
    inked(ctx, YELLOW, 4, (3, 3))
    ctx.save()
    ctx.translate(108, -54)
    ctx.rotate(t * 0.8)
    ctx.move_to(0, 0)
    ctx.line_to(0, -12)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.restore()
    ctx.arc(108, -8, 11, 0, TAU)
    inked(ctx, PINK, 4, (3, 3))
    ctx.set_line_width(5)
    ctx.set_source_rgb(*INK)
    for y in (30, 44, 58, 72):
        ctx.move_to(93, y)
        ctx.line_to(124, y)
    ctx.stroke()


def emblem(ctx, t):
    pose = emblem_pose(t)
    if pose is None:
        return
    ghosts = ((0.05, 0.18), (0.025, 0.3)) if T.LOGO_FLIGHT < t < T.HIT else ()
    for lag, alpha in ghosts + ((0, 1.0),):
        x, y, scale, spin, tilt = emblem_pose(max(T.LOGO_FLIGHT, t - lag))
        facing, side = math.cos(spin), math.sin(spin)
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(tilt)
        ctx.scale(scale * max(abs(facing), 0.04), scale)
        if alpha < 1:
            ctx.push_group()
        draw_tv(ctx, t, 1 if facing >= 0 else -1, side)
        if alpha < 1:
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(alpha)
        ctx.restore()


def ring(ctx, t, front):
    """An orbit ribbon that draws itself around the emblem, then keeps turning."""
    draw = ease_in_out(span(t, T.RIBBON, T.RIBBON + 1.2))
    if draw <= 0:
        return
    x, y = emblem_pose(t)[:2]
    y += 30
    start = -TAU / 4 + 0.9 * (t - T.RIBBON)
    steps = max(2, int(160 * draw))
    tilt_c, tilt_s = math.cos(-0.16), math.sin(-0.16)
    colour = mix(PINK, (1.0, 0.95, 0.3), colour_shift(t))
    run, head = [], None
    # The lower half of the orbit passes in front of the set, the upper half behind it.
    for i in range(steps + 1):
        a = start + TAU * draw * i / steps
        px, py = math.cos(a) * 300, math.sin(a) * 78
        head = (x + px * tilt_c - py * tilt_s, y + px * tilt_s + py * tilt_c)
        if (math.sin(a) > 0) == front:
            run.append(head)
            continue
        stroke_run(ctx, run, colour)
        run = []
    stroke_run(ctx, run, colour)
    if front and draw < 1:
        glint(ctx, *head, 26, t * 6)


def stroke_run(ctx, points, colour):
    if len(points) > 1:
        ctx.move_to(*points[0])
        for point in points[1:]:
            ctx.line_to(*point)
        inked_stroke(ctx, colour, 12, (5, 5))


def glint(ctx, x, y, r, rotation=0.0, alpha=1.0):
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    halo = cairo.RadialGradient(x, y, 0, x, y, r * 1.2)
    halo.add_color_stop_rgba(0, 1, 1, 1, 0.8 * alpha)
    halo.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(halo)
    ctx.arc(x, y, r * 1.2, 0, TAU)
    ctx.fill()
    star(ctx, x, y, r, rotation)
    ctx.set_source_rgba(1, 1, 1, alpha)
    ctx.fill()
    ctx.restore()


def wordmark(ctx, t):
    size, layout = wordmark_layout()
    font(ctx, 'URW Gothic', size)
    top = BASELINE - size * 0.74
    colours = (PINK, YELLOW, TEAL, ORANGE, CYAN)
    for i, letter in enumerate(layout):
        land = T.LETTERS + i * T.LETTER_STEP
        p = span(t, land - 0.2, land)
        if p <= 0:
            continue
        # Each letter slams onto the glass from in front of it, then squashes on impact.
        zoom = 1 + 2.2 * (1 - ease_in(p, 2))
        impact = pulse(t, land, 0.18)
        wave = math.sin(clamp((t - T.KEY_CHANGE - i * 0.045) / 0.32) * math.pi) * 22 \
            + math.sin(clamp((t - T.BUTTON - i * 0.03) / 0.4) * math.pi) * 34
        cx = letter['x'] + letter['bearing'] + letter['w'] / 2
        cy = BASELINE - size * 0.37
        ctx.save()
        ctx.translate(cx, cy - wave)
        ctx.scale(zoom * (1 + 0.12 * impact), zoom * (1 - 0.18 * impact))
        ctx.rotate((1 - p) * (0.35 if i % 2 else -0.35))
        ctx.move_to(-letter['w'] / 2 - letter['bearing'], BASELINE - cy)
        ctx.text_path(letter['ch'])
        if p < 1:
            ctx.push_group()
        face_top, face_bottom = top - cy, BASELINE - cy
        if letter['part'] == 0:
            face = cairo.LinearGradient(0, face_top, 0, face_bottom)
            base = colours[i % len(colours)]
            face.add_color_stop_rgb(0, *mix(base, WHITE, 0.45))
            face.add_color_stop_rgb(0.5, *base)
            face.add_color_stop_rgb(1, *mix(base, INK, 0.25))
        else:
            face = chrome(face_top, face_bottom, colour_shift(t))
        inked(ctx, face, 5, (8, 8), fatten=7)
        if p < 1:
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(ease_out(clamp(p * 2.5)))
        ctx.restore()
        if impact > 0 and i % 2 == 0:
            dust(ctx, cx, BASELINE + 6, span(t, land, land + 0.3))
    sweep(ctx, t, size, layout)
    for when, index in GLINTS:
        life = span(t, when, when + 0.5)
        if 0 < life < 1:
            letter = layout[index]
            glint(ctx, letter['x'] + letter['w'] * 0.8, top + size * 0.12, 30 * math.sin(life * math.pi), life * 2)


def dust(ctx, x, y, p):
    if p >= 1:
        return
    ctx.set_source_rgba(1, 1, 1, 1 - p)
    ctx.set_line_width(3)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for a in (-2.6, -2.2, -0.9, -0.5):
        r0, r1 = 30 + 40 * p, 44 + 58 * p
        ctx.move_to(x + math.cos(a) * r0, y + math.sin(a) * r0 * 0.5)
        ctx.line_to(x + math.cos(a) * r1, y + math.sin(a) * r1 * 0.5)
    ctx.stroke()


def sweep(ctx, t, size, layout):
    """A diagonal highlight glides across the chrome."""
    p = span(t, T.SWEEP, T.SWEEP + 0.7)
    if not 0 < p < 1:
        return
    chrome_letters = [letter for letter in layout if letter['part'] == 1]
    x0 = chrome_letters[0]['x'] - 80
    x1 = chrome_letters[-1]['x'] + chrome_letters[-1]['w'] + 80
    x = x0 + (x1 - x0) * ease_in_out(p)
    ctx.save()
    for letter in chrome_letters:
        ctx.move_to(letter['x'], BASELINE)
        ctx.text_path(letter['ch'])
    ctx.clip()
    band = cairo.LinearGradient(x - 60, 0, x + 60, 0)
    band.add_color_stop_rgba(0, 1, 1, 1, 0)
    band.add_color_stop_rgba(0.5, 1, 1, 1, 0.85)
    band.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(band)
    ctx.paint()
    ctx.restore()


def tagline(ctx, t):
    p = span(t, T.TAGLINE, T.TAGLINE + 0.35)
    if p <= 0:
        return
    text = TAGLINE_TEXT
    font(ctx, 'Nimbus Sans', 34, italic=True)
    tracking = 7
    widths = [ctx.text_extents(ch).x_advance + tracking for ch in text]
    width = sum(widths) - tracking
    cx, cy, h = W / 2, 636, 50
    x0, x1 = cx - width / 2 - 34, cx + width / 2 + 34
    reveal = x0 + (x1 - x0 + 30) * ease_out(p)
    ctx.save()
    ctx.rectangle(0, 0, reveal, H)
    ctx.clip()
    ctx.move_to(x0 + 14, cy - h / 2)
    ctx.line_to(x1 + 14, cy - h / 2)
    ctx.line_to(x1 - 14, cy + h / 2)
    ctx.line_to(x0 - 14, cy + h / 2)
    ctx.close_path()
    inked(ctx, mix(PINK, (0.1, 0.35, 0.9), colour_shift(t)), 5, (6, 6))
    ctx.restore()
    x = cx - width / 2
    for i, (ch, advance) in enumerate(zip(text, widths)):
        q = span(t, T.TAGLINE + 0.15 + i * 0.035, T.TAGLINE + 0.3 + i * 0.035)
        if q > 0:
            ctx.save()
            ctx.translate(x, cy + 12)
            ctx.scale(1, back_out(q))
            ctx.move_to(0, 0)
            ctx.text_path(ch)
            ctx.set_source_rgb(*WHITE)
            ctx.fill()
            ctx.restore()
        x += advance


def flare(ctx, t):
    p = span(t, T.HIT, T.HIT + 1.3)
    if not 0 < p < 1:
        return
    strength = math.sin(p * math.pi)
    x = -200 + 1680 * ease_in_out(p)
    y = EMBLEM[1] - 40
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for height, alpha in ((5, 0.9), (26, 0.25)):
        streak = cairo.LinearGradient(x - 520, 0, x + 520, 0)
        streak.add_color_stop_rgba(0, 0.6, 0.8, 1, 0)
        streak.add_color_stop_rgba(0.5, 0.8, 0.9, 1, alpha * strength)
        streak.add_color_stop_rgba(1, 0.6, 0.8, 1, 0)
        ctx.set_source(streak)
        ctx.rectangle(x - 520, y - height / 2, 1040, height)
        ctx.fill()
    core = cairo.RadialGradient(x, y, 0, x, y, 130)
    core.add_color_stop_rgba(0, 1, 1, 1, 0.9 * strength)
    core.add_color_stop_rgba(1, 1, 0.8, 1, 0)
    ctx.set_source(core)
    ctx.arc(x, y, 130, 0, TAU)
    ctx.fill()
    for f, r, rgb in ((0.35, 26, TEAL), (0.7, 44, PINK), (1.25, 18, YELLOW), (1.6, 60, CYAN)):
        gx, gy = x + (W / 2 - x) * f * 2, y + (H / 2 - y) * f * 2
        ghost = cairo.RadialGradient(gx, gy, r * 0.6, gx, gy, r)
        ghost.add_color_stop_rgba(0, *rgb, 0.05 * strength)
        ghost.add_color_stop_rgba(0.85, *rgb, 0.3 * strength)
        ghost.add_color_stop_rgba(1, *rgb, 0)
        ctx.set_source(ghost)
        ctx.arc(gx, gy, r, 0, TAU)
        ctx.fill()
    ctx.restore()


def burst(ctx, t):
    p = span(t, T.BUTTON, T.BUTTON + 1.5)
    if not 0 < p < 1:
        return
    x, y = emblem_pose(t)[:2]
    for i in range(14):
        a = i * TAU / 14 + 0.3
        r = 90 + 430 * ease_out(p) * (0.75 + 0.25 * (i % 3))
        glint(ctx, x + math.cos(a) * r, y + math.sin(a) * r * 0.8, 24 * (1 - p) + 4, p * 4 + i, 1 - p)


def iris(ctx, t):
    if t < T.IRIS:
        return
    x, y = emblem_pose(t)[:2]
    close = span(t, T.IRIS, T.IRIS + 0.55)
    finish = span(t, T.IRIS + 0.75, T.BLACK)
    radius = 900 - 740 * ease_in(close, 2) if finish == 0 else 160 * (1 - ease_in(finish, 2))
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.rectangle(0, 0, W, H)
    if radius > 0.5:
        ctx.arc(x, y, radius, 0, TAU)
    ctx.set_source_rgb(0, 0, 0)
    ctx.fill()
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)


def static(ctx, t, frame):
    if t >= T.STATIC_END:
        return
    amount = 1.0 if t < T.STATIC_END - 0.15 else span(t, T.STATIC_END, T.STATIC_END - 0.15)
    ctx.save()
    ctx.scale(4, 4)
    ctx.set_source_surface(snow(frame % 6), 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_NEAREST)
    ctx.paint_with_alpha(amount)
    ctx.restore()
    band = (t * 1900) % (H + 120) - 60
    ctx.set_source_rgba(1, 1, 1, 0.25 * amount)
    ctx.rectangle(0, band, W, 34)
    ctx.fill()


def flash(ctx, t):
    amount = max(0.85 * pulse(t, T.HIT, 0.35), 0.55 * pulse(t, T.KEY_CHANGE, 0.3), 0.9 * pulse(t, T.BUTTON, 0.4))
    if amount > 0:
        ctx.set_source_rgba(1, 1, 1, amount)
        ctx.paint()


def camera(ctx, t):
    """Shake on the hits and a slow push through the build."""
    shake = max(pulse(t, T.HIT, 0.3), pulse(t, T.KEY_CHANGE, 0.25), pulse(t, T.BUTTON, 0.35))
    zoom = 1 + 0.045 * ease_in_out(span(t, T.BUILD, T.KEY_CHANGE)) \
        - 0.045 * ease_in_out(span(t, T.KEY_CHANGE, T.KEY_CHANGE + 0.8))
    ctx.translate(W / 2 + math.sin(t * 91) * 9 * shake, H / 2 + math.cos(t * 77) * 7 * shake)
    ctx.scale(zoom, zoom)
    ctx.translate(-W / 2, -H / 2)


# ---------------------------------------------------------------- frames

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= T.BLACK:
        return
    ctx.save()
    camera(ctx, t)
    ctx.rectangle(-40, -40, W + 80, H + 80)
    ctx.clip()
    sky(ctx, t)
    sunburst(ctx, t)
    floor(ctx, t)
    confetti(ctx, t)
    ring(ctx, t, front=False)
    emblem(ctx, t)
    ring(ctx, t, front=True)
    wordmark(ctx, t)
    tagline(ctx, t)
    flare(ctx, t)
    burst(ctx, t)
    ctx.restore()
    flash(ctx, t)
    ctx.set_source_surface(overlay(), 0, 0)
    ctx.paint()
    static(ctx, t, frame)
    iris(ctx, t)


def frames():
    return round(T.DURATION * T.FPS)


def render(frame):
    """One frame as raw BGRx bytes (ffmpeg pix_fmt bgr0)."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    draw(cairo.Context(surface), frame / T.FPS, frame)
    surface.flush()
    return bytes(surface.get_data())


def still(t, path):
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    draw(cairo.Context(surface), t, int(t * T.FPS))
    surface.write_to_png(str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Draw one frame of the station ID')
    parser.add_argument('--still', type=float, required=True, metavar='SECONDS')
    parser.add_argument('out', type=Path)
    args = parser.parse_args(argv)
    still(args.still, args.out)


if __name__ == '__main__':
    main()
