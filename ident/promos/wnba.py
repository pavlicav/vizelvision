"""The Tunnel Walk: the WNBA's pregame runway. The concrete tunnel under the arena before
tip-off, photographers three deep behind velvet ropes, and No. 19 walking toward the camera
in a head-to-toe VizelVision fit: an oversized pink blazer and wide pink trousers, teal
headphones round her neck, yellow sunglasses, and a little purse shaped like the station's
TV, antennae and all. The open logo is four steps, a burst of flashes on each. She stops,
pops a hip, lowers the sunglasses with one finger and looks over them at you (the flashes go
wild), flips the TV purse onto her shoulder and walks on, into the lens. A whip pan: the
court from the tunnel's mouth, the house sold out, SOLD OUT along the fascia, her back to
us (19, VIZELVISION) with a wave to the stands. The house lights go down, the spotlights
find the court, and the wordmark drops in on the closed logo over WOMEN'S BASKETBALL.

Live text: the programme on air, on the LED sign hanging in the tunnel, then on the baseline
board. Aired only during a WNBA game (LEAGUES). Thalia, the courtside correspondent:
"Tonight's tunnel walk... number nineteen." / "Head to toe... Vizzle Vision."
"""
import math
import random
from functools import lru_cache

import cairo

import arena
import basketball as court     # the arena: its stands, floor, hoop and spotlights (same camera)
import neighborhood
from common import (A, INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    glint, grain, inked, mix, pixel_text, rounded_rect, span, text_path, vignette)

ID = 'wnba'
NAME = 'The Tunnel Walk'
KIND = 'ident'
ORDER = 34
DESCRIPTION = ('Only during the WNBA: the tunnel walk. No. 19 struts toward the cameras in a head-to-toe VizelVision '
               'fit with a purse shaped like the station TV, a burst of flashes on each note of the open logo, a look '
               'over the sunglasses; then the sold-out court and the wordmark on the closed logo. Thalia.')
DURATION = 10.0
STILL_AT = 3.5
LEAGUES = ('wnba',)

# Hit points (the music's too: wnba_music.py).
FOOTFALLS = (0.0, 0.5, 1.0, 1.5, 1.75, 2.0, 2.5)  # her heels on the concrete; the last four are the open logo
LOGO_STEPS = (1.5, 1.75, 2.0, 2.5)
STRIDES = (0.95, 0.95, 0.95, 0.55, 0.55, 0.95)    # metres walked between footfalls
STOP = 2.75                                       # she settles: a hip popped, a hand on it
GLASSES = (3.05, 3.4)                             # one finger pulls the sunglasses down her nose
FRENZY = (3.4, 4.3)                               # the look over them, the flashes going wild
FLIP = (4.3, 4.72)                                # the TV purse swung up onto her shoulder
ONWARD = (4.9, 5.15)                              # two more strides, into the lens
WHIP = (5.12, 5.42)                               # the whip pan to the court
COURT = 5.27
WAVE = (5.85, 6.45)                               # a wave to the stands
DIM = (6.45, 6.95)                                # the house lights down (court.spotlights uses the same)
WORDMARK = 7.0                                    # the closed logo
SUBTITLE = (7.55, 8.2)
FADE = (9.25, 9.6)

# The tunnel's camera: a pinhole at CAM_H metres, FOCAL px, the horizon at HORIZON px; world x
# metres right, y up from the floor, z away from the camera.
FOCAL, CAM_H, HORIZON = 820, 1.5, 345
HALF, ROOF, MOUTH = 2.6, 3.3, 27.0               # the tunnel's half width and height; the far end
ROPE_X = 1.55
Z_STOP = 3.4                                     # where she stops

CONCRETE = (0.4, 0.42, 0.47)
SKIN = (0.42, 0.26, 0.17)
HAIR = (0.07, 0.05, 0.04)
BLAZER = PINK
TROUSERS = mix(PINK, (0.6, 0.05, 0.3), 0.18)
VELVET = (0.55, 0.06, 0.2)
CHROME = (0.82, 0.84, 0.88)
AMBER = (1.0, 0.68, 0.18)

OVERLAYS = [
    {'field': 'programme', 'box': [456, 167, 292, 42], 'from': 0.45, 'to': 2.85,
     'style': {'font': 'Nimbus Sans Narrow', 'bold': True, 'size': 30, 'min_size': 14, 'color': [1.0, 0.68, 0.18],
               'upper': True, 'tracking': 0.1},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': 0.2}},
    {'field': 'programme', 'box': [40, 470, 500, 46], 'from': 5.5, 'to': DIM[0],
     'style': {'font': 'Nimbus Sans Narrow', 'bold': True, 'size': 34, 'min_size': 16, 'color': [1.0, 0.68, 0.18],
               'upper': True, 'tracking': 0.1},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': 0.3}},
]


def project(x, y, z):
    return W / 2 + FOCAL * x / z, HORIZON - FOCAL * (y - CAM_H) / z


def scale(z):
    return FOCAL / z


def quad(ctx, pts):
    ctx.move_to(*project(*pts[0]))
    for p in pts[1:]:
        ctx.line_to(*project(*p))
    ctx.close_path()


# ---------------------------------------------------------------- the tunnel (drawn once)

LIGHTS = tuple(2.5 + 3.0 * k for k in range(9))   # fluorescent strips down the ceiling


@lru_cache(maxsize=None)
def tunnel_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.05, 0.05, 0.07)
    ctx.paint()
    near = 0.6
    # The far end: the arena, bright through the tunnel's mouth.
    x0, y0 = project(-HALF, ROOF, MOUTH)
    x1, y1 = project(HALF, 0, MOUTH)
    g = cairo.LinearGradient(0, y0, 0, y1)
    g.add_color_stop_rgb(0, 1.0, 0.95, 0.85)
    g.add_color_stop_rgb(0.55, 0.98, 0.86, 0.7)
    g.add_color_stop_rgb(1, 0.95, 0.7, 0.45)
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.set_source(g)
    ctx.fill()
    rand = random.Random(4)
    for row in range(6):                               # the stands beyond, in the glare
        yy = y0 + 6 + row * 7
        for k in range(26):
            ctx.arc(x0 + 4 + k * (x1 - x0 - 8) / 25 + rand.uniform(-1, 1), yy, 2.2, 0, TAU)
            ctx.set_source_rgba(*mix(rand.choice(arena.SHIRTS), (1, 0.95, 0.85), 0.55), 1)
            ctx.fill()
    ctx.rectangle(x0, y1 - (y1 - y0) * 0.22, x1 - x0, (y1 - y0) * 0.22)   # the hardwood
    ctx.set_source_rgb(0.95, 0.72, 0.45)
    ctx.fill()
    # Floor: dark rubber, the pink runner down the middle with teal edges, pools of light.
    quad(ctx, ((-HALF, 0, near), (HALF, 0, near), (HALF, 0, MOUTH), (-HALF, 0, MOUTH)))
    g = cairo.LinearGradient(0, project(0, 0, MOUTH)[1], 0, H)
    g.add_color_stop_rgb(0, 0.32, 0.28, 0.3)
    g.add_color_stop_rgb(1, 0.13, 0.12, 0.14)
    ctx.set_source(g)
    ctx.fill()
    quad(ctx, ((-0.95, 0, near), (0.95, 0, near), (0.95, 0, MOUTH), (-0.95, 0, MOUTH)))
    g = cairo.LinearGradient(0, project(0, 0, MOUTH)[1], 0, H)
    g.add_color_stop_rgb(0, *mix(PINK, (1, 0.9, 0.8), 0.45))
    g.add_color_stop_rgb(1, *mix(PINK, INK, 0.35))
    ctx.set_source(g)
    ctx.fill()
    for side in (-1, 1):
        quad(ctx, ((side * 0.95, 0, near), (side * 1.02, 0, near), (side * 1.02, 0, MOUTH), (side * 0.95, 0, MOUTH)))
        ctx.set_source_rgb(*TEAL)
        ctx.fill()
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for z in LIGHTS:                                   # light pools under the strips
        cx, cy = project(0, 0, z)
        r = 1.6 * scale(z)
        pool = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
        pool.add_color_stop_rgba(0, 1, 1, 1, 0.13)
        pool.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(1, 0.22)
        ctx.translate(-cx, -cy)
        ctx.arc(cx, cy, r, 0, TAU)
        ctx.set_source(pool)
        ctx.fill()
        ctx.restore()
    ctx.restore()
    # Walls: painted block, a pink stripe at waist height, panel seams, padding at the far end.
    for side in (-1, 1):
        quad(ctx, ((side * HALF, 0, near), (side * HALF, ROOF, near), (side * HALF, ROOF, MOUTH), (side * HALF, 0, MOUTH)))
        g = cairo.LinearGradient(project(side * HALF, 0, near)[0], 0, project(side * HALF, 0, MOUTH)[0], 0)
        g.add_color_stop_rgb(0, *mix(CONCRETE, INK, 0.5))
        g.add_color_stop_rgb(0.75, *CONCRETE)
        g.add_color_stop_rgb(1, *mix(CONCRETE, (1, 0.9, 0.75), 0.3))
        ctx.set_source(g)
        ctx.fill()
        for y0_, y1_, colour in ((0.9, 1.15, PINK), (1.15, 1.22, YELLOW), (0.0, 0.18, (0.2, 0.2, 0.24))):
            quad(ctx, ((side * HALF, y0_, near), (side * HALF, y1_, near), (side * HALF, y1_, MOUTH), (side * HALF, y0_, MOUTH)))
            ctx.set_source_rgb(*colour)
            ctx.fill()
        ctx.set_line_width(1.2)
        for z in [near + 1.2 * k for k in range(1, 22)]:    # the block's seams
            ctx.move_to(*project(side * HALF, 0.18, z))
            ctx.line_to(*project(side * HALF, ROOF, z))
            ctx.set_source_rgba(0, 0, 0, 0.18)
            ctx.stroke()
        for y in (0.6, 1.6, 2.1, 2.6):
            ctx.move_to(*project(side * HALF, y, near))
            ctx.line_to(*project(side * HALF, y, MOUTH))
            ctx.set_source_rgba(0, 0, 0, 0.1)
            ctx.stroke()
    # 19s stencilled big on the walls, every few metres (letters face the camera, scaled by depth).
    for side in (-1, 1):
        for z in (9.0, 15.0, 21.0):
            x, y = project(side * (HALF - 0.02), 2.25, z)
            ctx.save()
            ctx.translate(x, y)
            ctx.transform(cairo.Matrix(0.45, side * -0.32, 0, 1, 0, 0))
            ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(0.75 * scale(z))
            ctx.new_path()
            text_path(ctx, '19', 0, 0, align='center')
            ctx.set_source_rgba(1, 1, 1, 0.22)
            ctx.fill()
            ctx.restore()
    # The ceiling: dark, with ducts and the strips of light.
    quad(ctx, ((-HALF, ROOF, near), (HALF, ROOF, near), (HALF, ROOF, MOUTH), (-HALF, ROOF, MOUTH)))
    ctx.set_source_rgb(0.12, 0.12, 0.15)
    ctx.fill()
    for x in (-1.9, 1.7):
        quad(ctx, ((x - 0.18, ROOF - 0.05, near), (x + 0.18, ROOF - 0.05, near), (x + 0.18, ROOF - 0.05, MOUTH), (x - 0.18, ROOF - 0.05, MOUTH)))
        ctx.set_source_rgb(0.3, 0.31, 0.34)
        ctx.fill()
    for z in LIGHTS:
        quad(ctx, ((-0.7, ROOF - 0.02, z), (0.7, ROOF - 0.02, z), (0.7, ROOF - 0.02, z + 0.35), (-0.7, ROOF - 0.02, z + 0.35)))
        ctx.set_source_rgb(0.97, 0.98, 1.0)
        ctx.fill()
    # A green EXIT sign, a fire extinguisher cabinet: the building's small print.
    ex, ey = project(-HALF + 0.02, 2.75, 6.0)
    k = scale(6.0)
    ctx.rectangle(ex, ey, 0.35 * k * 0.5, 0.16 * k)
    ctx.set_source_rgb(0.1, 0.75, 0.35)
    ctx.fill()
    cx, cy = project(HALF - 0.02, 1.6, 11.0)
    k = scale(11.0)
    ctx.rectangle(cx - 0.18 * k, cy, 0.18 * k, 0.5 * k)
    ctx.set_source_rgb(0.75, 0.1, 0.1)
    ctx.fill()
    # The bloom of the court's light around the mouth.
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    mx, my = project(0, 1.4, MOUTH)
    bloom = cairo.RadialGradient(mx, my, 10, mx, my, 230)
    bloom.add_color_stop_rgba(0, 1, 0.9, 0.75, 0.35)
    bloom.add_color_stop_rgba(1, 1, 0.9, 0.75, 0)
    ctx.set_source(bloom)
    ctx.paint()
    ctx.restore()
    return surface


def sign(ctx, t):
    """The LED sign hanging over the tunnel: black glass; the programme (master's text) on the
    left two thirds, a pink pixel 19 on the right."""
    x0, y0 = project(-1.5, 2.98, 6.5)
    x1, y1 = project(1.5, 2.5, 6.5)
    for side in (-1.2, 1.2):                            # its hangers
        hx, hy = project(side, ROOF, 6.5)
        ctx.move_to(hx, hy)
        ctx.line_to(hx, y0)
        ctx.set_source_rgb(0.3, 0.3, 0.33)
        ctx.set_line_width(2)
        ctx.stroke()
    rounded_rect(ctx, x0 - 4, y0 - 4, x1 - x0 + 8, y1 - y0 + 8, 5)
    ctx.set_source_rgb(0.1, 0.1, 0.12)
    ctx.fill()
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.set_source_rgb(0.02, 0.02, 0.03)
    ctx.fill()
    cell = 4
    blink = 1.0 if int(t * 2.5) % 2 == 0 else 0.6
    pixel_text(ctx, '19', x1 - 62, y0 + (y1 - y0 - 7 * cell) / 2, cell, mix((0.1, 0.02, 0.05), PINK, blink))


# ---------------------------------------------------------------- the photographers

def _photographers():
    rand = random.Random(19)
    out = []
    for side in (-1, 1):
        for z in (2.8, 4.1, 5.5, 7.0, 8.7, 10.6, 12.8, 15.3, 18.0, 21.0):
            for row in (0, 1):                          # two deep
                if row and rand.random() < 0.35:
                    continue
                x = side * (1.95 + 0.42 * row + rand.uniform(-0.05, 0.08))
                out.append({'x': x, 'z': z + rand.uniform(-0.3, 0.3) + 0.45 * row, 'side': side, 'row': row,
                            'h': rand.uniform(1.62, 1.85), 'up': rand.random() < 0.3,
                            'jacket': rand.choice(((0.12, 0.12, 0.15), (0.2, 0.18, 0.22), (0.1, 0.14, 0.2),
                                                   (0.25, 0.2, 0.16), (0.16, 0.16, 0.16))),
                            'skin': rand.choice(arena.SKINS), 'cap': rand.random() < 0.35})
    return sorted(out, key=lambda p: -p['z'])


PHOTOGRAPHERS = _photographers()


def _flash_schedule():
    """(time, photographer) for every flash: a scatter while she walks, a burst on each step of
    the open logo, a storm for the look, a scatter again."""
    rand = random.Random(2026)
    n = len(PHOTOGRAPHERS)
    out = []
    t = 0.3
    while t < 4.9:
        if not FRENZY[0] - 0.1 < t < FRENZY[1]:
            out.append((t, rand.randrange(n)))
        t += rand.uniform(0.09, 0.22)
    for step in LOGO_STEPS:
        for _ in range(6):
            out.append((step + rand.uniform(0.0, 0.05), rand.randrange(n)))
    t = FRENZY[0]
    while t < FRENZY[1]:
        for _ in range(rand.randint(1, 3)):
            out.append((t + rand.uniform(0, 0.03), rand.randrange(n)))
        t += 1 / 30
    return sorted(out)


FLASHES = _flash_schedule()
FLASH_LEN = 0.06


def lit_flashes(t):
    return [(at, j) for at, j in FLASHES if at <= t < at + FLASH_LEN]


def camera_point(p):
    """Where a photographer's flash head is (world)."""
    lean = -p['side'] * 0.18
    y = p['h'] + (0.42 if p['up'] else 0.06)
    return p['x'] + lean, y, p['z'] - 0.05


def photographer(ctx, p, t, firing):
    k = scale(p['z'])
    fx, fy = project(p['x'], 0, p['z'])
    dark = 0.55 if p['row'] else 0.3
    jacket = mix(p['jacket'], (0.6, 0.55, 0.5), 0.15)
    sway = 0.02 * math.sin(t * 1.7 + p['z'])
    # body
    hx, hy = project(p['x'] + sway, p['h'] - 0.1, p['z'])
    ctx.move_to(fx - 0.24 * k, fy)
    ctx.line_to(fx - 0.26 * k, hy + 0.22 * k)
    ctx.curve_to(fx - 0.24 * k, hy + 0.06 * k, fx + 0.24 * k, hy + 0.06 * k, fx + 0.26 * k, hy + 0.22 * k)
    ctx.line_to(fx + 0.24 * k, fy)
    ctx.close_path()
    ctx.set_source_rgb(*mix(jacket, (0, 0, 0), dark))
    ctx.fill()
    # head
    ctx.arc(hx, hy - 0.02 * k, 0.1 * k, 0, TAU)
    ctx.set_source_rgb(*mix(p['skin'], (0, 0, 0), dark + 0.1))
    ctx.fill()
    if p['cap']:
        ctx.arc(hx, hy - 0.04 * k, 0.1 * k, math.pi, TAU)
        ctx.set_source_rgb(*mix((0.1, 0.1, 0.12), (0, 0, 0), dark))
        ctx.fill()
    # the camera: up at the face, or held high over the heads, its lens toward the middle
    cx, cy, cz = camera_point(p)
    sx, sy = project(cx, cy - 0.1, cz)
    if p['up']:
        for side in (-1, 1):                             # arms up to it
            ctx.move_to(hx + side * 0.18 * k, hy + 0.15 * k)
            ctx.line_to(sx + side * 0.06 * k, sy + 0.05 * k)
        ctx.set_source_rgb(*mix(jacket, (0, 0, 0), dark))
        ctx.set_line_width(0.09 * k)
        ctx.stroke()
    rounded_rect(ctx, sx - 0.08 * k, sy - 0.05 * k, 0.16 * k, 0.1 * k, 0.02 * k)
    ctx.set_source_rgb(0.04, 0.04, 0.05)
    ctx.fill()
    lx = sx - p['side'] * 0.1 * k
    ctx.rectangle(min(lx, sx), sy - 0.035 * k, abs(lx - sx), 0.07 * k)
    ctx.fill()
    ctx.arc(lx, sy, 0.035 * k, 0, TAU)
    ctx.set_source_rgb(0.15, 0.2, 0.3)
    ctx.fill()
    fhx, fhy = project(cx, cy, cz)                       # the flash head on top
    ctx.rectangle(fhx - 0.04 * k, fhy - 0.03 * k, 0.08 * k, 0.05 * k)
    ctx.set_source_rgb(*((1, 1, 1) if firing else (0.25, 0.25, 0.28)))
    ctx.fill()


def ropes(ctx):
    posts = [1.3 + 2.1 * k for k in range(11)]
    for side in (-1, 1):
        for a, b in zip(posts[::-1][1:], posts[::-1][:-1]):    # far to near
            pts = []
            for i in range(13):
                u = i / 12
                z = a + (b - a) * u
                y = 0.88 - 0.16 * math.sin(math.pi * u)
                pts.append(project(side * ROPE_X, y, z))
            ctx.move_to(*pts[0])
            for p in pts[1:]:
                ctx.line_to(*p)
            ctx.set_source_rgb(*mix(VELVET, (0, 0, 0), 0.3))
            ctx.set_line_width(0.05 * scale((a + b) / 2) + 1)
            ctx.stroke_preserve()
            ctx.set_source_rgb(*VELVET)
            ctx.set_line_width(0.03 * scale((a + b) / 2))
            ctx.stroke()
        for z in posts[::-1]:
            k = scale(z)
            bx, by = project(side * ROPE_X, 0, z)
            tx, ty = project(side * ROPE_X, 0.95, z)
            ctx.rectangle(bx - 0.025 * k, ty, 0.05 * k, by - ty)
            ctx.set_source_rgb(*CHROME)
            ctx.fill()
            ctx.arc(tx, ty, 0.045 * k, 0, TAU)
            ctx.fill()
            ctx.save()
            ctx.translate(bx, by)
            ctx.scale(1, 0.3)
            ctx.arc(0, 0, 0.14 * k, 0, TAU)
            ctx.restore()
            ctx.set_source_rgb(*mix(CHROME, INK, 0.3))
            ctx.fill()


# ---------------------------------------------------------------- No. 19, toward the camera

def body_z(t):
    """Her depth: a stride a footfall to Z_STOP, then on into the lens."""
    zs = [Z_STOP + sum(STRIDES)]
    for s in STRIDES:
        zs.append(zs[-1] - s)
    if t <= FOOTFALLS[-1]:
        for k in range(len(FOOTFALLS) - 1):
            if t < FOOTFALLS[k + 1]:
                u = span(t, FOOTFALLS[k], FOOTFALLS[k + 1])
                return zs[k] + (zs[k + 1] - zs[k]) * u
        return zs[-1]
    if t < ONWARD[0]:
        return Z_STOP + 0.0 * span(t, FOOTFALLS[-1], STOP)
    return Z_STOP - (Z_STOP - 0.75) * ease_in(span(t, ONWARD[0], WHIP[0] + 0.12), 2)


def swing(t):
    """(which leg swings: -1 screen left, +1 screen right, or 0; how far through the stride)."""
    steps = FOOTFALLS + (ONWARD[0] - 0.25, ONWARD[0], ONWARD[1], ONWARD[1] + 0.25)
    for k in range(len(steps) - 1):
        a, b = steps[k], steps[k + 1]
        if a <= t < b and b - a <= 0.6:
            return (-1 if k % 2 == 0 else 1), (t - a) / (b - a)
    return 0, 0.0


BASE = {'pelvis': (0.0, 0.97), 'neck': (0.0, 1.52), 'head': (0.0, 1.69),
        'ls': (-0.25, 1.47), 'rs': (0.25, 1.47), 'le': (-0.32, 1.2), 're': (0.33, 1.2),
        'lh': (-0.33, 0.95), 'rh': (0.35, 0.96), 'lk': (-0.12, 0.52), 'rk': (0.12, 0.52),
        'lf': (-0.13, 0.04), 'rf': (0.13, 0.04)}
STAND = {**BASE, 'pelvis': (0.05, 0.96), 'le': (-0.46, 1.18), 'lh': (-0.2, 1.0), 'lf': (-0.2, 0.04),
         'rf': (0.11, 0.04), 'lk': (-0.17, 0.5), 'rk': (0.13, 0.53)}
SPECS = {**STAND, 'le': (-0.36, 1.3), 'lh': (-0.08, 1.56)}
FLIPPED = {**STAND, 're': (0.4, 1.28), 'rh': (0.23, 1.5)}


def lerp_pose(a, b, k):
    return {j: (a[j][0] + (b[j][0] - a[j][0]) * k, a[j][1] + (b[j][1] - a[j][1]) * k) for j in a}


def pose(t):
    leg, u = swing(t)
    if t < FOOTFALLS[-1] + 0.12 or t >= ONWARD[0] - 0.25:
        p = dict(BASE if t < STOP else FLIPPED)
        if leg:
            side = 'l' if leg < 0 else 'r'
            lift = math.sin(math.pi * u)
            fx, fy = p[side + 'f']
            kx, ky = p[side + 'k']
            p[side + 'f'] = (fx - leg * 0.03 * lift, fy + 0.13 * lift)
            p[side + 'k'] = (kx - leg * 0.02 * lift, ky + 0.09 * lift)
            p['pelvis'] = (p['pelvis'][0] + leg * 0.035 * lift, p['pelvis'][1] - 0.012 + 0.024 * lift)
            if t < STOP:                                # the free arm swings with the opposite leg
                p['lh'] = (p['lh'][0] + 0.03 * leg * lift, p['lh'][1] + 0.05 * (leg > 0) * lift)
        if t < STOP and t > FOOTFALLS[-1]:
            p = lerp_pose(p, STAND, ease_in_out(span(t, FOOTFALLS[-1] + 0.05, STOP)))
        return p
    p = lerp_pose(BASE, STAND, ease_in_out(span(t, FOOTFALLS[-1] + 0.05, STOP)))
    p = lerp_pose(p, SPECS, specs_hand(t))
    p = lerp_pose(p, FLIPPED, ease_in_out(span(t, FLIP[0], FLIP[1])))
    if FLIP[0] <= t < FLIP[1]:                          # the hand goes high on the way
        k = math.sin(math.pi * span(t, FLIP[0], FLIP[1]))
        p['rh'] = (p['rh'][0] + 0.05 * k, p['rh'][1] + 0.3 * k)
        p['re'] = (p['re'][0] + 0.06 * k, p['re'][1] + 0.18 * k)
    return p


def specs_hand(t):
    """How far the hand is up at the sunglasses (0..1)."""
    return ease_in_out(span(t, GLASSES[0], GLASSES[0] + 0.2)) * (1 - ease_in_out(span(t, FRENZY[0] + 0.35, FRENZY[0] + 0.6)))


def specs_down(t):
    """How far the sunglasses have slid down her nose (0..1)."""
    return ease_out(span(t, GLASSES[0] + 0.12, GLASSES[1])) * (1 - ease_in_out(span(t, ONWARD[0] - 0.3, ONWARD[0])))


def purse_state(t):
    """(where the TV purse hangs relative to her hand or shoulder, angle, behind?)."""
    if t < FLIP[0]:
        return 'hand', 0.12 * math.sin(t * 5.5) + (0.08 * math.sin((t - 2.5) * 9) * math.exp(-(t - 2.5) * 3) if t > 2.5 else 0)
    if t < FLIP[1]:
        return 'flight', span(t, *FLIP)
    return 'shoulder', 0.05 * math.sin((t - FLIP[1]) * 8) * math.exp(-(t - FLIP[1]) * 3)


def tv_purse(ctx, x, y, size, angle, t):
    """The station's TV as a purse: the emblem's set (animation.draw_tv), a pink ring round it,
    a gold chain from its top. (x, y) is where the chain meets her hand."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(angle)
    k = size / 300
    ctx.move_to(0, 0)                                    # the chain
    ctx.line_to(0, 0.35 * size)
    ctx.set_source_rgb(*YELLOW)
    ctx.set_line_width(max(1.5, 0.012 * size))
    ctx.set_dash([max(2, 0.03 * size), max(1.5, 0.015 * size)])
    ctx.stroke()
    ctx.set_dash([])
    ctx.translate(0, 0.35 * size + 230 * k)
    ctx.scale(k, k)
    ctx.save()
    ctx.scale(1, 0.32)
    ctx.arc(0, 30 / 0.32, 205, math.pi, TAU)              # the ring, its back half
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(26)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*PINK)
    ctx.set_line_width(14)
    ctx.stroke()
    ctx.restore()
    A.draw_tv(ctx, t, 1, 0)
    ctx.save()
    ctx.scale(1, 0.32)
    ctx.arc(0, 30 / 0.32, 205, 0, math.pi)                # and its front
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(26)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*PINK)
    ctx.set_line_width(14)
    ctx.stroke()
    ctx.restore()
    ctx.restore()


def limb(ctx, points, colour, width, outline=5):
    ctx.move_to(*points[0])
    for pt in points[1:]:
        ctx.line_to(*pt)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(width + outline)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*colour)
    ctx.set_line_width(width)
    ctx.stroke()


def sneaker(ctx, x, y, s, back=False):
    rounded_rect(ctx, x - 0.08 * s, y - 0.1 * s, 0.16 * s, 0.11 * s, 0.045 * s)
    inked(ctx, WHITE, 3, (0, 0))
    ctx.rectangle(x - 0.08 * s, y - 0.025 * s, 0.16 * s, 0.03 * s)
    ctx.set_source_rgb(*TEAL)
    ctx.fill()
    if not back:
        ctx.move_to(x - 0.04 * s, y - 0.075 * s)
        ctx.line_to(x + 0.04 * s, y - 0.075 * s)
        ctx.set_source_rgb(*PINK)
        ctx.set_line_width(max(1.5, 0.012 * s))
        ctx.stroke()


def figure_front(ctx, t, z, x0=0.0, light=1.0):
    """No. 19 facing the camera at depth z."""
    p = pose(t)
    s = scale(z)
    up = 0.0

    def P(x, y):
        return project(x0 + x, y + up, z)

    j = {k: P(*v) for k, v in p.items()}
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    fx, fy = P(p['pelvis'][0] * 0.3, 0)                 # her shadow
    ctx.save()
    ctx.translate(fx, fy)
    ctx.scale(1, 0.16)
    ctx.arc(0, 0, 0.5 * s, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, 0.35)
    ctx.fill()
    where, angle = purse_state(t)
    purse_size = 0.26 * s
    if where == 'shoulder':                              # behind her, peeking over the shoulder
        sx, sy = P(p['rs'][0] + 0.02, p['rs'][1] + 0.02)
        tv_purse(ctx, sx, sy - 0.32 * s, purse_size, angle + 0.25, t)
    # Wide trousers, each leg from the hip, flaring to the cuff over the sneaker.
    pel = p['pelvis']
    for side in ('l', 'r'):
        sign = -1 if side == 'l' else 1
        hip_out, hip_in = P(pel[0] + sign * 0.2, pel[1]), P(pel[0] + sign * 0.01, pel[1] - 0.06)
        kx, ky = p[side + 'k']
        fx_, fy_ = p[side + 'f']
        ctx.move_to(*hip_out)
        ctx.line_to(*P(kx + sign * 0.12, ky))
        ctx.line_to(*P(fx_ + sign * 0.15, fy_ + 0.05))
        ctx.line_to(*P(fx_ - sign * 0.11, fy_ + 0.05))
        ctx.line_to(*P(kx - sign * 0.09, ky))
        ctx.line_to(*hip_in)
        ctx.close_path()
        inked(ctx, mix(TROUSERS, INK, 0.08 if side == 'l' else 0.0), 4, (0, 0))
        ctx.move_to(*P(kx + sign * 0.02, ky + 0.25))      # a crease
        ctx.line_to(*P(fx_ + sign * 0.02, fy_ + 0.1))
        ctx.set_source_rgba(*INK, 0.35)
        ctx.set_line_width(max(1, 0.01 * s))
        ctx.stroke()
    for side in ('l', 'r'):
        sneaker(ctx, *P(*p[side + 'f']), s)
    # The blazer: oversized, shoulders padded, long.
    ls, rs = P(p['ls'][0] - 0.05, p['ls'][1] + 0.03), P(p['rs'][0] + 0.05, p['rs'][1] + 0.03)
    neck = j['neck']
    hem_l, hem_r = P(pel[0] - 0.32, 0.8), P(pel[0] + 0.32, 0.8)
    # sleeves first (behind the body's edge)
    for side in ('l', 'r'):
        sh = j[side + 's']
        limb(ctx, (sh, j[side + 'e'], j[side + 'h']), BLAZER, 0.14 * s)
        hx, hy = j[side + 'h']
        ex, ey = j[side + 'e']
        cuff = (hx + (ex - hx) * 0.18, hy + (ey - hy) * 0.18)
        ctx.move_to(*cuff)
        ctx.line_to(hx + (ex - hx) * 0.1, hy + (ey - hy) * 0.1)
        ctx.set_source_rgb(*WHITE)
        ctx.set_line_width(0.12 * s)
        ctx.stroke()
    ctx.move_to(*ls)
    ctx.curve_to(ls[0] + 0.06 * s, ls[1] - 0.04 * s, neck[0] - 0.12 * s, neck[1] + 0.02 * s, neck[0] - 0.06 * s, neck[1] + 0.03 * s)
    ctx.line_to(neck[0] + 0.06 * s, neck[1] + 0.03 * s)
    ctx.curve_to(neck[0] + 0.12 * s, neck[1] + 0.02 * s, rs[0] - 0.06 * s, rs[1] - 0.04 * s, *rs)
    ctx.line_to(rs[0] + 0.02 * s, rs[1] + 0.2 * s)
    ctx.line_to(*hem_r)
    ctx.line_to(*hem_l)
    ctx.line_to(ls[0] - 0.02 * s, ls[1] + 0.2 * s)
    ctx.close_path()
    inked(ctx, BLAZER, 5, (0, 0))
    # the white tee in the V, the lapels, two buttons, the breast pocket with a teal square
    vx, vy = P(pel[0] * 0.5, 1.12)
    ctx.move_to(neck[0] - 0.07 * s, neck[1] + 0.04 * s)
    ctx.line_to(neck[0] + 0.07 * s, neck[1] + 0.04 * s)
    ctx.line_to(vx, vy)
    ctx.close_path()
    inked(ctx, WHITE, 3, (0, 0))
    for sign in (-1, 1):
        ctx.move_to(neck[0] + sign * 0.07 * s, neck[1] + 0.04 * s)
        ctx.line_to(neck[0] + sign * 0.15 * s, neck[1] + 0.12 * s)
        ctx.line_to(neck[0] + sign * 0.1 * s, neck[1] + 0.15 * s)
        ctx.line_to(vx, vy)
        ctx.close_path()
        inked(ctx, mix(BLAZER, INK, 0.18), 3, (0, 0))
    for k in range(2):
        ctx.arc(vx, vy + (0.05 + 0.12 * k) * s, 0.018 * s, 0, TAU)
        inked(ctx, YELLOW, 2, (0, 0))
    px, py = P(pel[0] - 0.17, 1.32)
    ctx.rectangle(px - 0.06 * s, py, 0.12 * s, 0.012 * s)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.move_to(px - 0.045 * s, py)
    ctx.line_to(px - 0.03 * s, py - 0.05 * s)
    ctx.line_to(px, py - 0.03 * s)
    ctx.line_to(px + 0.025 * s, py - 0.055 * s)
    ctx.line_to(px + 0.045 * s, py)
    ctx.close_path()
    inked(ctx, TEAL, 2, (0, 0))
    # VIZELVISION down the right lapel, small; a 19 pin on the left
    ctx.save()
    tx, ty = P(pel[0] + 0.16, 1.22)
    ctx.translate(tx, ty)
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(0.045 * s)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', 0, 0, tracking=0.003 * s, align='center')
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.restore()
    # neck, headphones round it, the head
    hx, hy = j['head']
    tilt = 0.08 * ease_in_out(span(t, GLASSES[1] - 0.1, GLASSES[1] + 0.15)) * (1 - ease_in_out(span(t, FLIP[0], FLIP[1])))
    limb(ctx, (neck, (neck[0], neck[1] - 0.07 * s)), SKIN, 0.085 * s, 4)
    for sign in (-1, 1):                                # headphone cups at the collarbones
        cx, cy = neck[0] + sign * 0.09 * s, neck[1] - 0.005 * s
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(0.75, 1)
        ctx.arc(0, 0, 0.04 * s, 0, TAU)
        ctx.restore()
        inked(ctx, TEAL, 3, (0, 0))
        ctx.arc(cx, cy, 0.015 * s, 0, TAU)
        ctx.set_source_rgb(*YELLOW)
        ctx.fill()
    ctx.move_to(neck[0] - 0.09 * s, neck[1] - 0.04 * s)    # the band, round the back of the neck
    ctx.curve_to(neck[0] - 0.09 * s, neck[1] - 0.11 * s, neck[0] + 0.09 * s, neck[1] - 0.11 * s, neck[0] + 0.09 * s, neck[1] - 0.04 * s)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(0.035 * s)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*WHITE)
    ctx.set_line_width(0.018 * s)
    ctx.stroke()
    head(ctx, t, hx, hy, s, tilt)
    # hands: one on the hip (or at the sunglasses), one holding the purse's chain
    finger = specs_hand(t)
    if finger > 0:                                      # an index finger to the bridge of the sunglasses
        x, y = j['lh']
        bx, by = hx + 0.0, hy + (-0.002 + 0.052 * specs_down(t) - 0.01) * s
        tip = (x + (bx - x) * finger, y + (by - y) * finger)
        limb(ctx, ((x, y), tip), SKIN, 0.022 * s, 3)
    for side in ('l', 'r'):
        x, y = j[side + 'h']
        ctx.arc(x, y, (0.048 - 0.012 * finger * (side == 'l')) * s, 0, TAU)
        inked(ctx, SKIN, 3, (0, 0))
    if where == 'hand':
        x, y = j['rh']
        tv_purse(ctx, x, y + 0.02 * s, purse_size, angle, t)
    elif where == 'flight':
        u = angle
        x, y = j['rh']
        tv_purse(ctx, x, y + 0.02 * s, purse_size, -math.pi * 0.95 * ease_in_out(u), t)
    ctx.restore()


def head(ctx, t, hx, hy, s, tilt):
    ctx.save()
    ctx.translate(hx, hy)
    ctx.rotate(tilt)
    # hair: a high puff, and the hairline swept back
    ctx.arc(0, -0.16 * s, 0.1 * s, 0, TAU)
    inked(ctx, HAIR, 3, (0, 0))
    ctx.arc(0.03 * s, -0.19 * s, 0.03 * s, 0, TAU)
    ctx.set_source_rgba(1, 1, 1, 0.1)
    ctx.fill()
    for sign in (-1, 1):                                # gold hoops
        ctx.arc(sign * 0.1 * s, 0.03 * s, 0.028 * s, 0, TAU)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(0.014 * s)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*YELLOW)
        ctx.set_line_width(0.008 * s)
        ctx.stroke()
    ctx.save()
    ctx.scale(0.9, 1.08)
    ctx.arc(0, 0, 0.11 * s, 0, TAU)
    ctx.restore()
    inked(ctx, SKIN, 3, (0, 0))
    ctx.save()
    ctx.scale(0.9, 1.08)
    ctx.arc(0, -0.004 * s, 0.112 * s, math.pi * 1.08, math.pi * 1.92)
    ctx.restore()
    ctx.close_path()
    ctx.set_source_rgb(*HAIR)
    ctx.fill()
    down = specs_down(t)
    # the eyes, under the sunglasses until they come down: a look straight at you, a brow up
    if down > 0.15:
        for sign in (-1, 1):
            ex, ey = sign * 0.038 * s, -0.012 * s
            ctx.save()
            ctx.translate(ex, ey)
            ctx.scale(1, 0.55)
            ctx.arc(0, 0, 0.025 * s, 0, TAU)
            ctx.restore()
            ctx.set_source_rgb(*WHITE)
            ctx.fill()
            ctx.arc(ex, ey, 0.012 * s, 0, TAU)
            ctx.set_source_rgb(0.12, 0.07, 0.04)
            ctx.fill()
            ctx.arc(ex + 0.004 * s, ey - 0.004 * s, 0.0035 * s, 0, TAU)
            ctx.set_source_rgb(1, 1, 1)
            ctx.fill()
            ctx.move_to(ex - 0.026 * s, ey - 0.003 * s)          # lashes, a flick at the corner
            ctx.curve_to(ex - 0.01 * s, ey - 0.018 * s, ex + 0.012 * s, ey - 0.018 * s, ex + 0.028 * s, ey - 0.006 * s)
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(max(1, 0.006 * s))
            ctx.stroke()
            raise_ = 0.016 * s * down if sign > 0 else 0.0
            ctx.move_to(ex - 0.024 * s, ey - 0.03 * s - raise_ * 0.5)
            ctx.curve_to(ex - 0.01 * s, ey - 0.042 * s - raise_, ex + 0.01 * s, ey - 0.042 * s - raise_, ex + 0.026 * s, ey - 0.032 * s - raise_ * 0.6)
            ctx.set_line_width(max(1.2, 0.008 * s))
            ctx.stroke()
    ctx.move_to(-0.004 * s, 0.01 * s)                    # nose
    ctx.curve_to(-0.012 * s, 0.035 * s, -0.008 * s, 0.045 * s, 0.006 * s, 0.045 * s)
    ctx.set_source_rgba(*INK, 0.6)
    ctx.set_line_width(max(1, 0.006 * s))
    ctx.stroke()
    ctx.save()                                           # lips: berry, a small knowing smile
    ctx.translate(0.004 * s, 0.07 * s)
    ctx.scale(1, 0.5)
    ctx.arc(0, 0, 0.028 * s, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.55, 0.06, 0.25)
    ctx.fill()
    ctx.move_to(-0.026 * s, 0.069 * s)
    ctx.curve_to(-0.01 * s, 0.077 * s, 0.015 * s, 0.075 * s, 0.032 * s, 0.064 * s)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(max(1, 0.005 * s))
    ctx.stroke()
    # the sunglasses: yellow cat-eye frames, teal lenses with a glint
    gy = -0.002 * s + 0.052 * s * down
    for sign in (-1, 1):
        ctx.save()
        ctx.translate(sign * 0.04 * s, gy)
        ctx.move_to(-0.034 * s, -0.016 * s)
        ctx.line_to(0.034 * s, -0.022 * s * (1 if sign > 0 else 0.7))
        ctx.curve_to(0.04 * s, 0.01 * s, 0.02 * s, 0.024 * s, 0.0, 0.024 * s)
        ctx.curve_to(-0.026 * s, 0.024 * s, -0.04 * s, 0.01 * s, -0.034 * s, -0.016 * s)
        ctx.close_path()
        if sign < 0:
            ctx.scale(-1, 1)
        lens = cairo.LinearGradient(0, -0.02 * s, 0, 0.024 * s)
        lens.add_color_stop_rgb(0, 0.0, 0.55, 0.55)
        lens.add_color_stop_rgb(1, 0.02, 0.18, 0.25)
        inked(ctx, lens, max(2, 0.012 * s), (0, 0))
        ctx.move_to(-0.02 * s, -0.008 * s)
        ctx.line_to(-0.005 * s, -0.014 * s)
        ctx.set_source_rgba(1, 1, 1, 0.7)
        ctx.set_line_width(max(1, 0.006 * s))
        ctx.stroke()
        ctx.restore()
    ctx.move_to(-0.008 * s, gy - 0.008 * s)
    ctx.line_to(0.008 * s, gy - 0.008 * s)
    ctx.set_source_rgb(*YELLOW)
    ctx.set_line_width(max(1.5, 0.008 * s))
    ctx.stroke()
    ctx.restore()


def flash_light(ctx, t, lit):
    """The flashes: a white star at each head that fires, and the tunnel lit up a little."""
    if not lit:
        return
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_source_rgba(1, 1, 1, min(0.22, 0.045 * len(lit)))
    ctx.paint()
    for at, j in lit:
        p = PHOTOGRAPHERS[j]
        x, y = project(*camera_point(p))
        k = scale(p['z'])
        fade = 1 - span(t, at, at + FLASH_LEN)
        r = 0.5 * k
        halo = cairo.RadialGradient(x, y, 0, x, y, r)
        halo.add_color_stop_rgba(0, 1, 1, 1, 0.95 * fade)
        halo.add_color_stop_rgba(0.25, 0.85, 0.92, 1, 0.45 * fade)
        halo.add_color_stop_rgba(1, 0.8, 0.9, 1, 0)
        ctx.set_source(halo)
        ctx.arc(x, y, r, 0, TAU)
        ctx.fill()
        glint(ctx, x, y, 0.5 * k * fade, 0.0, 0.9 * fade)
    ctx.restore()


PUNCH = (2.85, 3.25, 4.55, 4.85)                  # the camera punches in for the look, and back out
PUNCH_AT = (640, 330)


def tunnel(ctx, t, frame):
    k = 1 + 0.5 * ease_in_out(span(t, PUNCH[0], PUNCH[1])) * (1 - ease_in_out(span(t, PUNCH[2], PUNCH[3])))
    ctx.save()
    ctx.translate(*PUNCH_AT)
    ctx.scale(k, k)
    ctx.translate(-PUNCH_AT[0], -PUNCH_AT[1])
    ctx.set_source_surface(tunnel_surface(), 0, 0)
    ctx.paint()
    sign(ctx, t)
    lit = lit_flashes(t)
    firing = {j for _, j in lit}
    z = body_z(t)
    for k, p in enumerate(PHOTOGRAPHERS):
        photographer(ctx, p, t, k in firing)
    ropes(ctx)
    figure_front(ctx, t, z)
    flash_light(ctx, t, lit)
    ctx.restore()


# ---------------------------------------------------------------- the court, from the tunnel's mouth

CP = court.project
CS = court.scale


def court_z(t):
    """Her depth walking out from under the camera, away onto the floor."""
    return 4.2 + 4.6 * ease_out(span(t, COURT - 0.05, WORDMARK + 0.4), 1.6)


def figure_back(ctx, t):
    """No. 19 from behind, walking away: the puff, the headphones' band, the blazer's back
    with VIZELVISION across the shoulders and a big 19, the purse on her left shoulder."""
    z = court_z(t)
    s = CS(z)
    walk = (t - COURT) * 4.0
    bob = 0.02 * abs(math.sin(math.pi * walk))

    def P(x, y):
        return CP(0.3 + x, y + bob, z)

    wave = span(t, *WAVE)
    w = math.sin(math.pi * wave)
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    fx, fy = P(0, 0)
    ctx.save()
    ctx.translate(fx, fy)
    ctx.scale(1, 0.16)
    ctx.arc(0, 0, 0.5 * s, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, 0.35)
    ctx.fill()
    step = math.sin(math.pi * walk)
    for sign in (-1, 1):                                 # trousers and heels
        lift = max(0.0, step * sign) * 0.1
        hip_out, hip_in = P(sign * 0.2, 0.96), P(sign * 0.01, 0.9)
        ctx.move_to(*hip_out)
        ctx.line_to(*P(sign * 0.26, 0.05 + lift))
        ctx.line_to(*P(sign * 0.02, 0.05 + lift))
        ctx.line_to(*hip_in)
        ctx.close_path()
        inked(ctx, TROUSERS, 4, (0, 0))
        sneaker(ctx, *P(sign * 0.13, 0.03 + lift), s, back=True)
    # the left arm (screen left, seen from behind) hangs; the right waves
    limb(ctx, (P(-0.26, 1.46), P(-0.33, 1.2), P(-0.34, 0.96)), BLAZER, 0.14 * s)
    hand = P(-0.34, 0.96)
    ctx.arc(*hand, 0.048 * s, 0, TAU)
    inked(ctx, SKIN, 3, (0, 0))
    if w > 0:
        wv = 0.08 * math.sin((t - WAVE[0]) * 22) * w
        elbow, hand = P(0.42, 1.38 + 0.1 * w), P(0.4 + wv, 1.5 + 0.3 * w)
    else:
        elbow, hand = P(0.33, 1.2), P(0.34, 0.96)
    limb(ctx, (P(0.26, 1.46), elbow, hand), BLAZER, 0.14 * s)
    ctx.arc(*hand, 0.05 * s, 0, TAU)
    inked(ctx, SKIN, 3, (0, 0))
    ls, rs = P(-0.31, 1.5), P(0.31, 1.5)                  # the blazer's back
    ctx.move_to(*ls)
    ctx.curve_to(ls[0] + 0.1 * s, ls[1] - 0.05 * s, rs[0] - 0.1 * s, rs[1] - 0.05 * s, *rs)
    ctx.line_to(*P(0.33, 0.8))
    ctx.line_to(*P(-0.33, 0.8))
    ctx.close_path()
    inked(ctx, BLAZER, 5, (0, 0))
    ctx.move_to(*P(0.0, 1.1))
    ctx.line_to(*P(0.0, 0.8))
    ctx.set_source_rgba(*INK, 0.4)
    ctx.set_line_width(max(1, 0.01 * s))
    ctx.stroke()
    cx = P(0, 0)[0]
    ctx.save()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(0.075 * s)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', cx, P(0, 1.36)[1], tracking=0.004 * s, align='center')
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.set_font_size(0.26 * s)
    ctx.new_path()
    text_path(ctx, '19', cx, P(0, 1.08)[1], tracking=0.01 * s, align='center')
    path = ctx.copy_path()
    ctx.set_source_rgb(*TEAL)
    ctx.set_line_width(0.025 * s)
    ctx.stroke()
    ctx.append_path(path)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.restore()
    # the purse on her left shoulder (screen left from behind), hanging down her back
    sx, sy = P(-0.22, 1.5)
    tv_purse(ctx, sx, sy - 0.02 * s, 0.24 * s, 0.1 + 0.05 * math.sin(walk * math.pi), t)
    # neck, the headphones' band, the head from behind with the puff
    nx, ny = P(0, 1.52)
    limb(ctx, ((nx, ny), (nx, ny - 0.07 * s)), SKIN, 0.085 * s, 4)
    ctx.move_to(nx - 0.11 * s, ny - 0.0 * s)
    ctx.curve_to(nx - 0.1 * s, ny + 0.06 * s, nx + 0.1 * s, ny + 0.06 * s, nx + 0.11 * s, ny)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(0.04 * s)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*TEAL)
    ctx.set_line_width(0.024 * s)
    ctx.stroke()
    hx, hy = P(0, 1.69)
    ctx.save()
    ctx.translate(hx, hy)
    ctx.scale(0.9, 1.08)
    ctx.arc(0, 0, 0.11 * s, 0, TAU)
    ctx.restore()
    inked(ctx, HAIR, 3, (0, 0))
    ctx.arc(hx, hy - 0.16 * s, 0.1 * s, 0, TAU)
    inked(ctx, HAIR, 3, (0, 0))
    for sign in (-1, 1):
        ctx.arc(hx + sign * 0.1 * s, hy + 0.03 * s, 0.028 * s, 0, TAU)
        ctx.set_source_rgb(*YELLOW)
        ctx.set_line_width(0.008 * s)
        ctx.stroke()
    ctx.restore()


def fascia(ctx, t):
    """The ribbon board between the bowls: SOLD OUT, flashing; VIZELVISION 19 on the closed logo."""
    z, y = court.LED_Z + 0.6 + 0.85 * court.FASCIA, 0.9 + 0.42 * court.FASCIA
    top, base = CP(0, y + 0.9, z)[1], CP(0, y, z)[1]
    ctx.rectangle(0, top, W, base - top)
    ctx.set_source_rgb(0.02, 0.02, 0.03)
    ctx.fill()
    cell = max(3, int((base - top) / 9))
    y0 = top + (base - top - 7 * cell) / 2
    if t >= WORDMARK:
        offset = (t * 70) % (18 * 6 * cell)
        pixel_text(ctx, '  VIZELVISION 19  ' * 4, -offset, y0, cell, PINK)
    else:
        on = int((t - COURT) * 5) % 2 == 0
        for k, x in enumerate(range(-40, W, 230)):
            pixel_text(ctx, 'SOLD OUT', x + 20, y0, cell, (YELLOW if on else PINK) if k % 2 == 0 else (PINK if on else YELLOW))


def led_board(ctx, t):
    """The baseline boards: the left carries master's text, the right WNBA ON VIZELVISION in pixels."""
    top, base = CP(0, 0.95, court.LED_Z)[1], CP(0, 0, court.LED_Z)[1]
    ctx.rectangle(0, top, W, base - top)
    ctx.set_source_rgb(0.03, 0.02, 0.04)
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.08)
    ctx.rectangle(0, top, W, 2)
    ctx.fill()
    cell = 5
    ctx.save()
    ctx.rectangle(*CP(0.8, 0.95, court.LED_Z), W, base - top)
    ctx.clip()
    colour = mix(AMBER, PINK, span(t, WORDMARK, WORDMARK + 0.25))
    text = "WNBA ON VIZELVISION 19   TONIGHT'S TUNNEL WALK   " * 3
    offset = (t * 90) % ((len(text) // 3) * 6 * cell)
    pixel_text(ctx, text, 760 - offset, top + (base - top - 7 * cell) / 2, cell, colour)
    ctx.restore()


def court_flashes(ctx, t, frame):
    if not COURT <= t < DIM[1]:
        return
    rand = random.Random(frame // 3)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for _ in range(rand.randint(2, 7)):
        x, y = rand.uniform(20, W - 20), rand.uniform(60, 440)
        r = rand.uniform(6, 15)
        halo = cairo.RadialGradient(x, y, 0, x, y, r * 3)
        halo.add_color_stop_rgba(0, 1, 1, 1, 0.9)
        halo.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(halo)
        ctx.arc(x, y, r * 3, 0, TAU)
        ctx.fill()
    ctx.restore()


def pregame_clock(ctx):
    """The backboard's clock before tip-off: 24, steady."""
    cx0, cy0 = CP(-0.38, 4.38, court.BOARD_Z)
    cx1, cy1 = CP(0.38, 3.99, court.BOARD_Z)
    rounded_rect(ctx, cx0, cy0, cx1 - cx0, cy1 - cy0, 4)
    ctx.set_source_rgb(0.05, 0.05, 0.06)
    ctx.fill()
    h = (cy1 - cy0) * 0.62
    arena.seven_segment(ctx, '24', (cx0 + cx1) / 2 - h * 0.6, cy0 + (cy1 - cy0 - h) / 2, h, court.LED_RED)


def finale(ctx, t):
    if t < WORDMARK - 0.05:
        return
    neighborhood.lockup(ctx, t, WORDMARK, 330, scale=0.66)
    p = span(t, *SUBTITLE)
    if p > 0:
        ctx.save()
        ctx.rectangle(0, 0, W / 2 - 330 + 660 * ease_in_out(p), H)
        ctx.clip()
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(44)
        ctx.new_path()
        text_path(ctx, "WOMEN'S BASKETBALL", W / 2, 408, tracking=12, align='center')
        inked(ctx, YELLOW, 3, (5, 5), fatten=4)
        ctx.restore()
    for i, at in enumerate((WORDMARK + 0.25, WORDMARK + 1.0, WORDMARK + 2.0)):
        q = span(t, at, at + 0.5)
        if 0 < q < 1:
            glint(ctx, (370, 910, 640)[i], (250, 262, 222)[i], 22 * math.sin(math.pi * q), q * 3, 1)


def court_scene(ctx, t, frame):
    ctx.set_source_surface(court.arena_surface(), 0, 0)
    ctx.paint()
    fascia(ctx, t)
    court_flashes(ctx, t, frame)
    led_board(ctx, t)
    ctx.set_source_surface(court.court_surface(), 0, 0)
    ctx.paint()
    court.stanchion(ctx)
    court.board(ctx, 0.0)
    pregame_clock(ctx)
    court.rim(ctx, front=False)
    court.net(ctx, 0.0, front=False)
    court.net(ctx, 0.0, front=True)
    court.rim(ctx, front=True)
    figure_back(ctx, t)
    court.spotlights(ctx, t)
    finale(ctx, t)


# ---------------------------------------------------------------- the frame

def whip(ctx, t, frame):
    """The whip pan: the tunnel (her pink blazer filling the lens) streaks off left, the court
    streaks in from the right, the two smeared together across the middle."""
    u = span(t, *WHIP)
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    blur = 420 * math.sin(math.pi * u)
    swap = span(u, 0.38, 0.62)
    for scene, dx, alpha in ((tunnel, -W * 0.55 * ease_in(u, 2), 1 - swap),
                             (court_scene, W * 0.55 * (1 - ease_out(u, 2)), swap)):
        if alpha <= 0:
            continue
        ctx.push_group()
        scene(ctx, t, frame)
        pattern = ctx.pop_group()
        copies = 9
        for i in range(copies):
            ctx.save()
            ctx.translate(dx + blur * (i / (copies - 1) - 0.5), 0)
            ctx.set_source(pattern)
            ctx.paint_with_alpha(alpha * (1.0 if i == 0 else 1.7 / copies))
            ctx.restore()
    ctx.save()                                            # the streaks
    ctx.set_operator(cairo.OPERATOR_ADD)
    rand = random.Random(frame)
    for _ in range(40):
        y = rand.uniform(0, H)
        ctx.rectangle(0, y, W, rand.uniform(1, 4))
        ctx.set_source_rgba(1, 0.85, 0.95, 0.07 * math.sin(math.pi * u))
        ctx.fill()
    ctx.restore()


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    if t < WHIP[0]:
        tunnel(ctx, t, frame)
    elif t < WHIP[1]:
        whip(ctx, t, frame)
    else:
        court_scene(ctx, t, frame)
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.25)
    opening = 1 - ease_out(span(t, 0.0, 0.25))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
