"""Happy Little Channel: a public-television painting show. A canvas on an easel in the
dark studio: a soft sky, snowy mountains, a still lake, grassy banks. The painter (never
seen; the brush and a soft voice) taps in four happy little evergreens, one on each note
of the open logo, tip to trunk. "And everybody needs a friend": on the bank between them
the brush paints a happy little TV, the station's emblem, which, once it is finished,
gives a little hop. On the closed logo the brush is beaten against the easel's leg, a
thwack on each note, paint flying, and the painting is signed in red: VizelVision.

The painter is Orion: "Let's put some happy little trees in here." / "And everybody needs
a friend."
"""
import math
import random
from functools import lru_cache

import cairo

from common import (A, INK, TAU, H, W, WHITE, back_out, clamp, ease_in, ease_in_out, ease_out, glint, grain,  # noqa: F401
                    inked, mix, pulse, rounded_rect, span, vignette)

ID = 'happy-little'
NAME = 'Happy Little Channel'
KIND = 'ident'
ORDER = 25
DESCRIPTION = ('A painting show: four happy little trees tapped in on the notes of the logo, a happy little TV '
               'for a friend, the brush beaten against the easel on the closed logo, and a red signature. '
               'Orion, softly.')
DURATION = 10.0
STILL_AT = 8.95
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
FADE_IN = (0.0, 0.4)
BRUSH_IN = (0.3, 0.9)
TREES = (1.0, 1.25, 1.5, 2.0)                    # the open logo: a tree each, tip to trunk
GROW = (0.2, 0.2, 0.2, 0.42)
FRIEND = (3.3, 5.3)                              # the happy little TV, painted
HOP = 5.75                                       # ...and its little hop
BRUSH_OUT = (5.9, 6.4)
WHACKS = (7.0, 7.25, 7.5, 8.0)                   # the closed logo: beat the devil out of it
SIGN = (8.25, 8.95)                              # the signature
FADE = (9.3, 9.6)

CANVAS = (190, 46, 900, 584)                     # x, y, w, h: the painting, as it is drawn
PLACE = (235, 22, 0.9)                           # ...and where it is on the screen: x, y, scale
HORIZON = 388                                    # the lake's far shore
BANK = 500                                       # the near bank's top, at the middle
# The trees: (x, base y, height); the fourth is the big one.
TREE_SPOTS = ((318, 492, 150), (392, 512, 196), (930, 486, 130), (1012, 520, 250))
FRIEND_AT = (680, 574)                           # the little TV's feet, on the near shore
FRIEND_SCALE = 0.3
LEG = 640                                        # the easel's leg, under the canvas

SKY = ((0.23, 0.42, 0.72), (0.98, 0.86, 0.55))
MOUNTAIN = ((0.33, 0.33, 0.48), (0.24, 0.24, 0.36))
SNOW = (0.97, 0.97, 1.0)
GREEN = (0.13, 0.32, 0.17)
GREEN_DARK = (0.05, 0.16, 0.08)
GRASS = (0.38, 0.55, 0.2)
SIGNATURE = (0.82, 0.08, 0.1)


# ---------------------------------------------------------------- the painting

@lru_cache(maxsize=None)
def landscape():
    """The painting as it stands when we join: drawn once."""
    x0, y0, w, h = CANVAS
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    ctx.rectangle(*CANVAS)
    ctx.clip()
    sky = cairo.LinearGradient(0, y0, 0, HORIZON)
    sky.add_color_stop_rgb(0, *SKY[0])
    sky.add_color_stop_rgb(1, *SKY[1])
    ctx.set_source(sky)
    ctx.paint()
    rand = random.Random(4)
    for cx, cy, s in ((360, 120, 1.0), (760, 92, 1.3), (1000, 150, 0.8)):      # soft clouds: little circles
        for _ in range(16):
            r = rand.uniform(18, 40) * s
            g = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
            dx, dy = rand.uniform(-70, 70) * s, rand.uniform(-16, 12) * s
            g = cairo.RadialGradient(cx + dx, cy + dy, 0, cx + dx, cy + dy, r)
            g.add_color_stop_rgba(0, 1, 1, 1, 0.5)
            g.add_color_stop_rgba(1, 1, 1, 1, 0)
            ctx.set_source(g)
            ctx.paint()
    for k, (peaks, colour) in enumerate(((((190, 330), (330, 190), (470, 300), (600, 150), (760, 290), (880, 210),
                                          (1090, 320)), MOUNTAIN[0]),
                                         (((190, 360), (300, 270), (420, 340), (520, 250), (700, 350), (820, 260),
                                           (960, 330), (1090, 280)), MOUNTAIN[1]))):
        ctx.move_to(x0, HORIZON)
        for px, py in peaks:
            ctx.line_to(px, py)
        ctx.line_to(x0 + w, HORIZON)
        ctx.close_path()
        ctx.set_source_rgb(*colour)
        ctx.fill()
        for (ax, ay), (px, py), (bx, by) in zip(peaks, peaks[1:], peaks[2:]):   # the snow on each peak
            if py > (ay + by) / 2 - 20:
                continue
            depth = 40 + 10 * k
            ctx.move_to(px, py)
            ctx.line_to(px + (ax - px) * depth / (ay - py), py + depth)
            for j in range(4):
                ctx.line_to(px + (ax - px) * (depth - 14) / (ay - py) + j * (bx - ax) * depth / (ay - py) / 6,
                            py + depth - 10 + (12 if j % 2 else 0))
            ctx.line_to(px + (bx - px) * depth / (by - py), py + depth)
            ctx.close_path()
            ctx.set_source_rgba(*SNOW, 0.95)
            ctx.fill()
    mist = cairo.LinearGradient(0, HORIZON - 70, 0, HORIZON)
    mist.add_color_stop_rgba(0, 1, 0.95, 0.85, 0)
    mist.add_color_stop_rgba(1, 1, 0.95, 0.85, 0.55)
    ctx.set_source(mist)
    ctx.rectangle(x0, HORIZON - 70, w, 70)
    ctx.fill()
    lake = cairo.LinearGradient(0, HORIZON, 0, y0 + h)
    lake.add_color_stop_rgb(0, *mix(SKY[1], SKY[0], 0.3))
    lake.add_color_stop_rgb(1, *mix(SKY[0], INK, 0.2))
    ctx.set_source(lake)
    ctx.rectangle(x0, HORIZON, w, y0 + h - HORIZON)
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.55)                  # the water's shine, in streaks
    for _ in range(26):
        sx, sy = rand.uniform(x0 + 40, x0 + w - 120), rand.uniform(HORIZON + 6, HORIZON + 80)
        ctx.rectangle(sx, sy, rand.uniform(30, 120), 2)
    ctx.fill()
    for left, right, top, colour in ((x0 - 10, 560, BANK - 20, GRASS), (800, x0 + w + 10, BANK - 30, GRASS),
                                     (x0 - 10, x0 + w + 10, BANK + 34, mix(GRASS, GREEN_DARK, 0.4))):
        ctx.move_to(left, y0 + h)
        ctx.line_to(left, top + 30)
        ctx.curve_to(left + (right - left) * 0.3, top - 10, left + (right - left) * 0.7, top + 10, right, top + 26)
        ctx.line_to(right, y0 + h)
        ctx.close_path()
        g = cairo.LinearGradient(0, top, 0, y0 + h)
        g.add_color_stop_rgb(0, *mix(colour, (1, 0.95, 0.6), 0.25))
        g.add_color_stop_rgb(1, *mix(colour, GREEN_DARK, 0.5))
        ctx.set_source(g)
        ctx.fill()
    ctx.set_source_rgba(1, 1, 0.8, 0.35)               # grass flicks along the banks
    ctx.set_line_width(2)
    for _ in range(160):
        gx = rand.uniform(x0, x0 + w)
        gy = rand.uniform(BANK + 10, y0 + h)
        ctx.move_to(gx, gy)
        ctx.line_to(gx + rand.uniform(-4, 4), gy - rand.uniform(6, 14))
    ctx.stroke()
    return surface


@lru_cache(maxsize=None)
def tree_shape(index):
    """A painted evergreen at unit height (base at 0, tip at -1, width ±0.3): tiers of dabs."""
    rand = random.Random(index * 13 + 1)
    tiers = []
    for k in range(14):
        v = k / 13
        half = 0.03 + 0.27 * v ** 0.9
        tiers.append((-1 + v * 0.92, half * rand.uniform(0.8, 1.1), rand.uniform(-0.03, 0.03)))
    return tuple(tiers)


def tree(ctx, index, x, base, height, grown):
    """Tier by tier from the tip down to how far it has grown (0..1), dark first, then a
    lighter side where the light catches it."""
    if grown <= 0:
        return
    tiers = tree_shape(index)
    ctx.save()
    ctx.translate(x, base)
    ctx.scale(height, height)
    ctx.move_to(0, 0)
    ctx.line_to(0, -0.12)
    ctx.set_line_width(0.035)
    ctx.set_source_rgb(0.3, 0.18, 0.08)
    if grown > 0.95:
        ctx.stroke()
    ctx.new_path()
    shown = max(1, int(len(tiers) * grown + 0.999))
    for y, half, lean in tiers[:shown]:
        ctx.move_to(lean, y - 0.05)
        ctx.line_to(lean - half, y + 0.06)
        for j in range(5):
            ctx.line_to(lean - half + (j + 0.5) * half * 2 / 5, y + 0.06 + (0.025 if j % 2 else -0.005))
        ctx.line_to(lean + half, y + 0.06)
        ctx.close_path()
    ctx.set_source_rgb(*GREEN_DARK)
    ctx.fill()
    if grown >= 1:
        for y, half, lean in tiers:
            ctx.move_to(lean - 0.01, y - 0.04)
            ctx.line_to(lean - half * 0.85, y + 0.05)
            ctx.line_to(lean - half * 0.2, y + 0.04)
            ctx.close_path()
        ctx.set_source_rgba(*mix(GREEN, (0.75, 0.85, 0.3), 0.35), 0.9)
        ctx.fill()
    ctx.restore()


def trees(ctx, t):
    for i, ((x, base, height), when, grow) in enumerate(zip(TREE_SPOTS, TREES, GROW)):
        tree(ctx, i, x, base, height, span(t, when, when + grow))


def friend(ctx, t):
    """The happy little TV: revealed under the brush, left to right, then a hop."""
    p = span(t, *FRIEND)
    if p <= 0:
        return
    x, y = FRIEND_AT
    hop = math.sin(math.pi * span(t, HOP, HOP + 0.4))
    squash = pulse(t, HOP + 0.4, 0.25) - 0.6 * pulse(t, HOP - 0.05, 0.15)
    ctx.save()
    ctx.translate(x, y - 132 * FRIEND_SCALE)
    ctx.rectangle(-60, -80, 120 * ease_in_out(p), 140)    # as much as is painted
    ctx.clip()
    ctx.translate(0, -40 * hop)
    ctx.scale(FRIEND_SCALE * (1 + 0.1 * squash), FRIEND_SCALE * (1 - 0.1 * squash))
    ctx.push_group()
    A.draw_tv(ctx, t, 1, 0.0)
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(0.92)
    ctx.restore()
    if t > FRIEND[1]:                                     # its shadow on the grass
        ctx.save()
        ctx.translate(x, y + 2)
        ctx.scale(42 * (1 - 0.3 * hop), 6)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(0, 0.1, 0, 0.3)
        ctx.fill()
    q = span(t, HOP + 0.35, HOP + 0.85)
    if 0 < q < 1:
        glint(ctx, x + 40, y - 100, 16 * math.sin(math.pi * q), q * 2, 1)


@lru_cache(maxsize=None)
def signature_path():
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8))
    ctx.select_font_face('Z003', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(64)
    ctx.move_to(0, 0)
    ctx.text_path('VizelVision')
    ext = ctx.text_extents('VizelVision')
    return ctx.copy_path(), ext.x_advance


def signature(ctx, t):
    """Signed in red in the lower left, written left to right; returns the pen's place."""
    p = span(t, *SIGN)
    if p <= 0:
        return None
    path, width = signature_path()
    x, y = CANVAS[0] + 40, CANVAS[1] + CANVAS[3] - 34
    reach = width * ease_in_out(p) + 6
    ctx.save()
    ctx.rectangle(x - 10, y - 70, reach + 10, 100)
    ctx.clip()
    ctx.translate(x, y)
    ctx.rotate(-0.04)
    ctx.append_path(path)
    ctx.set_source_rgb(*SIGNATURE)
    ctx.fill()
    ctx.restore()
    return x + reach, y - 12 - 10 * math.sin(p * 40)


# ---------------------------------------------------------------- the studio, the easel, the brush

def studio(ctx):
    g = cairo.RadialGradient(W / 2, H / 2, 100, W / 2, H / 2, 800)
    g.add_color_stop_rgb(0, 0.09, 0.08, 0.08)
    g.add_color_stop_rgb(1, 0.01, 0.01, 0.01)
    ctx.set_source(g)
    ctx.paint()


def on_screen(x, y):
    """A point of the painting, where it is on the screen."""
    return PLACE[0] + PLACE[2] * (x - CANVAS[0]), PLACE[1] + PLACE[2] * (y - CANVAS[1])


def into_painting(ctx, jolt):
    ctx.translate(PLACE[0], PLACE[1] + jolt)
    ctx.scale(PLACE[2], PLACE[2])
    ctx.translate(-CANVAS[0], -CANVAS[1])


def easel(ctx, jolt):
    x0, y0 = on_screen(CANVAS[0], CANVAS[1])
    x1, y1 = on_screen(CANVAS[0] + CANVAS[2], CANVAS[1] + CANVAS[3])
    ctx.rectangle(LEG - 15, y1, 30, H - y1 + 10)                          # the leg
    g = cairo.LinearGradient(LEG - 15, 0, LEG + 15, 0)
    g.add_color_stop_rgb(0, 0.55, 0.37, 0.19)
    g.add_color_stop_rgb(1, 0.36, 0.23, 0.11)
    inked(ctx, g, 3, (0, 0))
    ctx.rectangle(x0 - 40, y1 + 4, x1 - x0 + 80, 22)                     # the ledge
    inked(ctx, (0.52, 0.35, 0.18), 3, (0, 6))
    ctx.rectangle(W / 2 - 60, y0 - 22, 120, 26)                          # the top clamp
    inked(ctx, (0.52, 0.35, 0.18), 3, (0, 6))
    ctx.save()
    ctx.translate(0, jolt)
    ctx.rectangle(x0 - 7, y0 - 7, x1 - x0 + 14, y1 - y0 + 14)           # the canvas's edge
    ctx.set_source_rgb(0.92, 0.9, 0.84)
    ctx.fill()
    ctx.restore()
    ctx.save()
    into_painting(ctx, jolt)
    ctx.set_source_surface(landscape(), 0, 0)
    ctx.paint()
    ctx.restore()


def brush_place(t, pen):
    """(x, y, angle) of the brush's bristles, or None when it is out of frame."""
    rest = (1240, 800, 0.5)
    if t < BRUSH_IN[0] or BRUSH_OUT[1] <= t < WHACKS[0] - 0.4 and pen is None:
        return None
    if t < TREES[0]:
        tip = TREE_SPOTS[0]
        p = ease_out(span(t, *BRUSH_IN))
        return (rest[0] + (tip[0] - rest[0]) * p, rest[1] + (tip[2] * -1 + tip[1] - rest[1]) * p, 0.5 - 0.2 * p)
    if t < FRIEND[0]:
        spot, start, grow = TREE_SPOTS[-1], TREES[-1], GROW[-1]
        for i in range(len(TREES)):
            if t < TREES[i] + GROW[i] or i == len(TREES) - 1:
                spot, start, grow = TREE_SPOTS[i], TREES[i], GROW[i]
                break
        x, base, height = spot
        g = span(t, start, start + grow)
        if t < start:                                       # on the way to the next tip
            prev = TREE_SPOTS[i - 1]
            q = ease_in_out(span(t, TREES[i - 1] + GROW[i - 1], start))
            return (prev[0] + (x - prev[0]) * q, prev[1] + (base - height - prev[1]) * q - 40 * math.sin(math.pi * q), 0.3)
        tap = 6 * math.sin(g * TAU * 6)
        if t > start + grow:                                # done: off towards the friend
            q = ease_in_out(span(t, start + grow, FRIEND[0]))
            fx, fy = FRIEND_AT
            return (x + (fx - 50 - x) * q, base + (fy - 70 - base) * q, 0.3)
        return (x + tap, base - height + height * 0.92 * g, 0.3)
    if t < FRIEND[1]:                                       # painting the friend: little strokes, left to right
        p = span(t, *FRIEND)
        fx, fy = FRIEND_AT
        return (fx - 50 + 100 * ease_in_out(p), fy - 70 + 36 * math.sin(p * TAU * 7), 0.3)
    if t < BRUSH_OUT[1]:
        fx, fy = FRIEND_AT
        p = ease_in(span(t, FRIEND[1] + 0.1, BRUSH_OUT[1]))
        return (fx + 50 + (rest[0] - fx - 50) * p, fy - 70 + (rest[1] - fy + 70) * p, 0.3 + 0.2 * p)
    if pen is not None:
        return (pen[0], pen[1], 0.3)
    return None


def whack(t):
    """The swing against the easel's leg: 0 at rest beside it, 1 at the hit."""
    best = 0.0
    for when in WHACKS:
        best = max(best, ease_in(span(t, when - 0.11, when)) * (1 - ease_out(span(t, when, when + 0.12))))
    return best


def brush(ctx, x, y, angle, loaded=GREEN_DARK):
    """A two-inch brush: bristles at (x, y), the handle running off down to the right."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(angle)
    rounded_rect(ctx, -8, 70, 16, 420, 8)              # the handle
    g = cairo.LinearGradient(-8, 0, 8, 0)
    g.add_color_stop_rgb(0, 0.7, 0.45, 0.2)
    g.add_color_stop_rgb(1, 0.45, 0.26, 0.1)
    inked(ctx, g, 3, (0, 0))
    rounded_rect(ctx, -26, 36, 52, 40, 5)              # the ferrule
    g = cairo.LinearGradient(-26, 0, 26, 0)
    g.add_color_stop_rgb(0, 0.85, 0.85, 0.88)
    g.add_color_stop_rgb(0.5, 1, 1, 1)
    g.add_color_stop_rgb(1, 0.55, 0.55, 0.6)
    inked(ctx, g, 3, (0, 0))
    ctx.move_to(-24, 38)                               # the bristles, loaded
    ctx.line_to(-22, 4)
    ctx.curve_to(-14, -4, 14, -4, 22, 4)
    ctx.line_to(24, 38)
    ctx.close_path()
    g = cairo.LinearGradient(0, 0, 0, 38)
    g.add_color_stop_rgb(0, *loaded)
    g.add_color_stop_rgb(1, 0.85, 0.8, 0.7)
    inked(ctx, g, 3, (0, 0))
    ctx.restore()


def beating(ctx, t, frame):
    """The closed logo: the brush swung against the easel's leg on each note, swishes
    behind it, paint flying off it."""
    if t < WHACKS[0] - 0.45 or t > SIGN[0]:
        return
    come = ease_out(span(t, WHACKS[0] - 0.45, WHACKS[0] - 0.15)) * (1 - ease_in(span(t, WHACKS[-1] + 0.2, SIGN[0])))
    hit = (LEG + 26, 652)                              # the bristles, against the leg
    back = (LEG + 150, 588)                            # drawn back

    def place(k):
        return (hit[0] + (back[0] - hit[0]) * (1 - k) + 420 * (1 - come),
                hit[1] + (back[1] - hit[1]) * (1 - k) + 160 * (1 - come), -1.45 + 0.65 * k)
    for lag, alpha in ((0.05, 0.2), (0.025, 0.35)):    # a blur of it, swinging
        k = whack(t - lag)
        if abs(k - whack(t)) > 0.15:
            ctx.push_group()
            brush(ctx, *place(k), loaded=(0.3, 0.45, 0.6))
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(alpha)
    brush(ctx, *place(whack(t)), loaded=(0.3, 0.45, 0.6))
    rand = random.Random(19)
    for when in WHACKS:                                # the spray from each hit
        p = span(t, when, when + 0.6)
        if not 0 < p < 1:
            rand.random()
            continue
        for j in range(38):
            a = rand.uniform(-TAU * 0.5, TAU * 0.02)
            v = rand.uniform(300, 760)
            colour = rand.choice(((0.3, 0.5, 0.75), GREEN, (0.95, 0.95, 0.9), (0.9, 0.78, 0.3), (0.13, 0.32, 0.6)))
            r = rand.uniform(4, 11)
            px = hit[0] + math.cos(a) * v * p
            py = hit[1] + math.sin(a) * v * p + 900 * p * p
            ctx.arc(px, py, r * (1 - 0.4 * p), 0, TAU)
            ctx.set_source_rgba(*colour, 1 - p ** 2)
            ctx.fill()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    studio(ctx)
    jolt = sum(5 * pulse(t, when, 0.12) for when in WHACKS)
    easel(ctx, jolt)
    ctx.save()
    into_painting(ctx, jolt)
    ctx.rectangle(*CANVAS)
    ctx.clip()
    trees(ctx, t)
    friend(ctx, t)
    pen = signature(ctx, t)
    ctx.restore()
    place = brush_place(t, pen)
    if place:
        brush(ctx, *on_screen(place[0], place[1]), place[2], loaded=SIGNATURE if pen else GREEN_DARK)
    beating(ctx, t, frame)
    vignette(ctx, 0.55)
    grain(ctx, frame, 0.35)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
