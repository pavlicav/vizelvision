"""VizelVision Shaadi: the station's TV marries the remote, at a big Indian wedding.

1. The baraat, at night outside the banquet hall: the groom, the station's TV, rides in on a
   white mare in a red safa with a kalgi, a sehra of marigolds and pearls hung over its screen
   and a garland on. The dhol player leads; two uncles dance (one screwing in a light bulb, one
   patting the dog). The welcome board: TV & REMOTE, GUESTS: 1,900, KNOWN TO THE COUPLE: 19.
   DJ Low Tide: "Make some noise for the groom!" The open logo is four dhol strokes, a firework
   each; on the fourth the sehra parts and the screen lights.
2. The mandap: under the marigold canopy, before the sacred fire, the TV and its bride, the
   remote, in a red lehenga and a gold-bordered dupatta, a maang tikka over its power button.
   The wedding video's title in script: TV weds Remote. "The TV, and the remote." The
   gathbandhan: his scarf knotted to her dupatta, and the lower third: THE REMOTE WILL NEVER BE
   LOST AGAIN.
3. The reception: an auntie in a pink sari leans into the camera with a plate of laddoos: "So
   when's the spin-off?" (a wink). Behind her two cousins run off with the groom's shoes,
   SHOE RANSOM ₹19,000.
4. The send-off: the palace lit in fairy lights under a marigold toran, diyas on the lawn, and
   four fireworks on the closed logo; the wordmark drops in, "Vizzle Vision! Shaadi Mubarak!",
   शादी मुबारक and CHANNEL 19.

DJ Low Tide (Orpheus), Harmonia (the wedding video), Vesta (an auntie).
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (A, CYAN, INK, ORANGE, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out,  # noqa: F401
                    ease_out, font, grain, inked, inked_stroke, mix, pulse, rounded_rect, span, star, text_path,
                    vignette)
from lds import circle, ellipse, label, limb, talking

ID = 'shaadi'
NAME = 'VizelVision Shaadi'
KIND = 'ident'
ORDER = 42
DESCRIPTION = ('The station\'s TV marries the remote at a big Indian wedding: the baraat with the TV on a white mare '
               'in a sehra, the dhol and fireworks on the open logo, the gathbandhan at the mandap ("The remote '
               'will never be lost again"), an auntie asking "So when\'s the spin-off?", the shoes held for ransom, '
               'and the wordmark over the lit palace as fireworks go up on the closed logo: शादी मुबारक. DJ Low '
               'Tide, Harmonia and Vesta.')
DURATION = 10.0
STILL_AT = 8.6
OVERLAYS = []

# Hit points (the music's too: shaadi_music.py).
FADE_IN = (0.0, 0.3)
BARAAT = (0.0, 3.2)                              # the procession, outside the hall
GROOM_LINE = 0.2                                 # "Make some noise for the groom!"
GROOVE = (0.0, 1.8)                              # the dhol's bhangra before the logo
LOGO = 1.8                                       # the open logo: four dhol strokes, a firework each
DHOL = (1.8, 2.05, 2.3, 2.8)
SEHRA = (2.8, 3.05)                              # the sehra parts, the screen lights
MANDAP_IN = (2.95, 3.2)
TITLE = (3.25, 3.6)                              # TV weds Remote, in script
COUPLE_LINE = 3.35                               # "The TV, and the remote."
KNOT = (4.15, 4.5)                               # the gathbandhan
CAPTION = (4.3, 4.6)                             # THE REMOTE WILL NEVER BE LOST AGAIN
AUNTIE_IN = (5.05, 5.3)
AUNTIE_LINE = 5.3                                # "So when's the spin-off?"
WINK = 6.35
RANSOM = (5.15, 6.7)                             # the cousins run off with the shoes
FINALE_IN = (6.45, 6.7)
CLOSER = 6.9                                     # "Vizzle Vision! Shaadi Mubarak!"
CLOSED = 7.0                                     # the closed logo: four fireworks, the wordmark
FIREWORKS = (7.0, 7.25, 7.5, 8.0)
AFTER = (8.45, 8.85)                             # two more, smaller, as the wordmark settles
DEVANAGARI = (8.0, 8.4)                          # शादी मुबारक, CHANNEL 19
FADE = (9.25, 9.6)

MARIGOLD = (1.0, 0.58, 0.06)
MARIGOLD_Y = (1.0, 0.8, 0.16)
JASMINE = (0.99, 0.98, 0.93)
SINDOOR = (0.86, 0.1, 0.12)
MAROON = (0.42, 0.05, 0.12)
GOLD = (0.96, 0.77, 0.3)
GOLD_DARK = (0.72, 0.52, 0.16)
ROSE = (0.92, 0.22, 0.48)
LEAF = (0.18, 0.52, 0.24)
IVORY = (0.99, 0.95, 0.87)
COPPER = (0.78, 0.42, 0.2)
MARE = (0.97, 0.96, 0.94)
MARE_SHADE = (0.82, 0.82, 0.86)
HAIR = (0.1, 0.08, 0.08)
SILVER = (0.78, 0.78, 0.8)
SKINS = ((0.72, 0.5, 0.36), (0.6, 0.4, 0.28), (0.8, 0.59, 0.44), (0.52, 0.34, 0.24))
BURST = (PINK, TEAL, YELLOW, CYAN, ORANGE)


def devanagari(ctx, size):
    ctx.select_font_face('FreeSans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)


def centred(ctx, text, x, y):
    ext = ctx.text_extents(text)
    ctx.move_to(x - ext.width / 2 - ext.x_bearing, y)
    ctx.text_path(text)


def path_points(p0, p1, p2, p3, n):
    """n+1 points along a cubic."""
    out = []
    for k in range(n + 1):
        u = k / n
        a, b, c, d = (1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


# ---------------------------------------------------------------- flowers and lights

def bead(ctx, x, y, r, colour, outline=1.5):
    circle(ctx, x, y, r)
    ctx.set_source_rgb(*colour)
    ctx.fill_preserve()
    ctx.set_source_rgb(*mix(colour, INK, 0.55))
    ctx.set_line_width(outline)
    ctx.stroke()


def marigold(ctx, x, y, r, colour=MARIGOLD):
    """A marigold head: a ruffled disc, darker at the heart."""
    ctx.save()
    ctx.translate(x, y)
    ctx.new_path()
    for k in range(12):
        a = k * TAU / 12
        ctx.arc(math.cos(a) * r * 0.55, math.sin(a) * r * 0.55, r * 0.5, 0, TAU)
        ctx.new_sub_path()
    ctx.set_source_rgb(*mix(colour, INK, 0.5))
    ctx.fill()
    circle(ctx, 0, 0, r * 0.92)
    ctx.set_source_rgb(*colour)
    ctx.fill()
    circle(ctx, 0, 0, r * 0.45)
    ctx.set_source_rgb(*mix(colour, (0.8, 0.3, 0.0), 0.6))
    ctx.fill()
    ctx.restore()


def strand(ctx, x, y0, y1, r, sway=0.0, pearls=False):
    """A hanging string of marigolds, orange and yellow, a jasmine bud between each pair."""
    n = max(2, int((y1 - y0) / (r * 1.7)))
    for k in range(n + 1):
        u = k / n
        xx = x + sway * u * u
        yy = y0 + (y1 - y0) * u
        if pearls and k % 2:
            bead(ctx, xx, yy, r * 0.55, JASMINE, 1)
        else:
            marigold(ctx, xx, yy, r, MARIGOLD if k % 3 else MARIGOLD_Y)


def garland(ctx, x0, y0, x1, y1, sag, r, roses=True):
    """A garland swag between two points: marigolds with a rose every few."""
    pts = path_points((x0, y0), (x0 + (x1 - x0) * 0.25, y0 + sag), (x0 + (x1 - x0) * 0.75, y1 + sag), (x1, y1),
                      max(4, int(math.hypot(x1 - x0, y1 - y0) / (r * 1.5))))
    for k, (x, y) in enumerate(pts):
        if roses and k % 5 == 2:
            marigold(ctx, x, y, r * 1.05, ROSE)
        else:
            marigold(ctx, x, y, r, MARIGOLD if k % 2 else MARIGOLD_Y)


@lru_cache(maxsize=None)
def glow_sprite(radius, colour):
    size = int(radius * 2) + 2
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    g = cairo.RadialGradient(size / 2, size / 2, 0, size / 2, size / 2, radius)
    g.add_color_stop_rgba(0, *colour, 1.0)
    g.add_color_stop_rgba(0.18, *colour, 0.7)
    g.add_color_stop_rgba(1, *colour, 0)
    ctx.set_source(g)
    ctx.paint()
    return surface


def glow(ctx, x, y, radius, colour, alpha):
    if alpha <= 0.01:
        return
    sprite = glow_sprite(int(radius), colour)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_source_surface(sprite, x - sprite.get_width() / 2, y - sprite.get_height() / 2)
    ctx.paint_with_alpha(min(1.0, alpha))
    ctx.restore()


FAIRY = (1.0, 0.82, 0.45)


def fairy_swag(x0, y0, x1, y1, sag, step=22):
    """Points along a string of fairy lights hung in a swag."""
    n = max(2, int(abs(x1 - x0) / step))
    return [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n + sag * math.sin(math.pi * k / n)) for k in range(n + 1)]


def fairy_lights(ctx, points, t, seed, size=2.6, halo=12, wire=True):
    if wire and len(points) > 1:
        ctx.move_to(*points[0])
        for p in points[1:]:
            ctx.line_to(*p)
        ctx.set_source_rgba(0.05, 0.04, 0.05, 0.8)
        ctx.set_line_width(1.2)
        ctx.stroke()
    rand = random.Random(seed)
    for x, y in points:
        twinkle = 0.75 + 0.25 * math.sin(t * rand.uniform(3, 7) + rand.uniform(0, TAU))
        glow(ctx, x, y, halo, FAIRY, 0.5 * twinkle)
        circle(ctx, x, y, size)
        ctx.set_source_rgb(1.0, 0.96, 0.8)
        ctx.fill()


def petals(ctx, t, seed, count, start=0.0, y_top=-40):
    """Marigold and rose petals drifting down."""
    rand = random.Random(seed)
    for k in range(count):
        x0 = rand.uniform(-40, W + 40)
        speed = rand.uniform(70, 140)
        phase = rand.uniform(0, 10)
        y = y_top + ((t - start) * speed + phase * 80) % (H + 80)
        x = x0 + 30 * math.sin(t * rand.uniform(1.2, 2.2) + phase)
        spin = t * rand.uniform(-4, 4) + phase
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(spin)
        ctx.scale(1, 0.45 + 0.4 * abs(math.sin(spin * 0.7)))
        circle(ctx, 0, 0, rand.uniform(4, 7))
        ctx.set_source_rgb(*rand.choice((MARIGOLD, MARIGOLD_Y, ROSE, MARIGOLD)))
        ctx.fill()
        ctx.restore()


def firework(ctx, t, at, x, y, size, colours, count=34, seed=0):
    """A burst: a flash, sparks flying out and falling, trails fading."""
    age = t - at
    if age < 0 or age > 1.6:
        return
    rand = random.Random(seed)
    glow(ctx, x, y, size * 0.9, (1.0, 0.95, 0.85), 0.9 * (1 - span(age, 0, 0.25)))
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    fade = 1 - span(age, 0.6, 1.6)
    for k in range(count):
        a = k * TAU / count + rand.uniform(-0.08, 0.08)
        reach = size * rand.uniform(0.85, 1.1)
        colour = colours[k % len(colours)]
        d1 = reach * ease_out(span(age, 0, 0.9))
        d0 = reach * ease_out(span(age, 0.12, 1.1))
        drop = 60 * age * age
        x1, y1 = x + math.cos(a) * d1, y + math.sin(a) * d1 + drop
        x0, y0 = x + math.cos(a) * d0, y + math.sin(a) * d0 + drop * 0.7
        ctx.move_to(x0, y0)
        ctx.line_to(x1, y1)
        ctx.set_source_rgba(*colour, 0.85 * fade)
        ctx.set_line_width(3.5)
        ctx.stroke()
        sparkle = fade * (0.6 + 0.4 * math.sin(age * 40 + k))
        circle(ctx, x1, y1, 3.2)
        ctx.set_source_rgba(*mix(colour, WHITE, 0.6), sparkle)
        ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- people

def head(ctx, x, y, r, skin, hair='short', hair_colour=HAIR, mouth=0.0, smile=1.0, moustache=None, beard=None,
         glasses=False, bindi=False, brow=0.0, wink=0.0, turban=None, look=0.0, sindoor=False):
    """A round, friendly face, front on, in the Have You Heard? family's style, with the
    wedding's extras: a turban, a moustache, a beard, a bun with a gajra, a bindi."""
    if hair == 'bun':                                                # the bun and its jasmine, behind
        circle(ctx, x + r * 0.62, y - r * 0.78, r * 0.42)
        inked(ctx, hair_colour, 3, (2, 2))
        for k in range(9):
            a = -0.4 + k * 0.42
            bead(ctx, x + r * 0.62 + math.cos(a) * r * 0.44, y - r * 0.78 + math.sin(a) * r * 0.44, r * 0.08, JASMINE, 1)
    if hair == 'braid':
        for k in range(5):
            circle(ctx, x - r * 0.95, y + r * (0.2 + 0.32 * k), r * 0.2)
        inked(ctx, hair_colour, 2.5, (2, 2))
    circle(ctx, x - r * 0.98, y + r * 0.08, r * 0.2)
    circle(ctx, x + r * 0.98, y + r * 0.08, r * 0.2)
    inked(ctx, skin, 3, (3, 3))
    circle(ctx, x, y, r)
    inked(ctx, skin, 4, (4, 4))
    if hair in ('short', 'kid'):
        ctx.move_to(x - r * 0.98, y - r * 0.05)
        ctx.curve_to(x - r * 1.05, y - r * 1.15, x + r * 1.05, y - r * 1.15, x + r * 0.98, y - r * 0.05)
        ctx.curve_to(x + r * 0.7, y - r * 0.6, x - r * 0.1, y - r * 0.65, x - r * 0.98, y - r * 0.05)
        ctx.close_path()
        inked(ctx, hair_colour, 3, (2, 2))
    elif hair in ('bun', 'braid'):                                   # a middle parting
        ctx.move_to(x - r * 1.0, y + r * 0.1)
        ctx.curve_to(x - r * 1.1, y - r * 1.2, x + r * 1.1, y - r * 1.2, x + r * 1.0, y + r * 0.1)
        ctx.curve_to(x + r * 0.85, y - r * 0.4, x + r * 0.3, y - r * 0.62, x, y - r * 0.7)
        ctx.curve_to(x - r * 0.3, y - r * 0.62, x - r * 0.85, y - r * 0.4, x - r * 1.0, y + r * 0.1)
        ctx.close_path()
        inked(ctx, hair_colour, 3, (2, 2))
        if sindoor:
            ctx.move_to(x, y - r * 0.98)
            ctx.line_to(x, y - r * 0.72)
            ctx.set_source_rgb(*SINDOOR)
            ctx.set_line_width(r * 0.07)
            ctx.stroke()
    elif hair == 'bald':                                             # grey tufts over the ears
        for sx in (-1, 1):
            ellipse(ctx, x + sx * r * 0.86, y - r * 0.28, r * 0.2, r * 0.3)
            inked(ctx, hair_colour, 2.5, (1, 1))
        ctx.arc(x - r * 0.25, y - r * 0.6, r * 0.18, math.pi * 1.1, math.pi * 1.6)
        ctx.set_source_rgba(1, 1, 1, 0.5)
        ctx.set_line_width(r * 0.06)
        ctx.stroke()
    if turban:                                                       # a peaked dastaar, its folds
        ctx.move_to(x - r * 1.04, y - r * 0.12)
        ctx.curve_to(x - r * 1.2, y - r * 1.0, x - r * 0.5, y - r * 1.6, x, y - r * 1.62)
        ctx.curve_to(x + r * 0.5, y - r * 1.6, x + r * 1.2, y - r * 1.0, x + r * 1.04, y - r * 0.12)
        ctx.curve_to(x + r * 0.6, y - r * 0.5, x + r * 0.2, y - r * 0.5, x, y - r * 0.32)
        ctx.curve_to(x - r * 0.2, y - r * 0.5, x - r * 0.6, y - r * 0.5, x - r * 1.04, y - r * 0.12)
        ctx.close_path()
        inked(ctx, turban, 3.5, (3, 3))
        ctx.set_source_rgba(*mix(turban, INK, 0.45), 0.8)
        ctx.set_line_width(max(1.5, r * 0.05))
        for k in range(3):
            ctx.move_to(x - r * (0.85 - 0.12 * k), y - r * (0.35 + 0.32 * k))
            ctx.curve_to(x - r * 0.3, y - r * (0.75 + 0.25 * k), x + r * 0.3, y - r * (0.95 + 0.2 * k),
                         x + r * (0.7 - 0.15 * k), y - r * (1.2 + 0.1 * k))
        ctx.stroke()
    if beard:
        ctx.move_to(x - r * 0.95, y + r * 0.05)
        ctx.curve_to(x - r * 0.9, y + r * 1.05, x - r * 0.35, y + r * 1.35, x, y + r * 1.38)
        ctx.curve_to(x + r * 0.35, y + r * 1.35, x + r * 0.9, y + r * 1.05, x + r * 0.95, y + r * 0.05)
        ctx.curve_to(x + r * 0.7, y + r * 0.45, x + r * 0.4, y + r * 0.6, x, y + r * 0.6)
        ctx.curve_to(x - r * 0.4, y + r * 0.6, x - r * 0.7, y + r * 0.45, x - r * 0.95, y + r * 0.05)
        ctx.close_path()
        inked(ctx, beard, 3, (2, 2))
    for k, sx in enumerate((-1, 1)):                                 # eyes, and the brows over them
        ex, ey = x + sx * r * 0.36 + look * r * 0.08, y + r * 0.0
        if (wink > 0.5 and sx == 1):
            ctx.move_to(ex - r * 0.13, ey + r * 0.02)
            ctx.curve_to(ex - r * 0.05, ey - r * 0.06, ex + r * 0.05, ey - r * 0.06, ex + r * 0.13, ey + r * 0.02)
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(max(2, r * 0.07))
            ctx.stroke()
        else:
            ellipse(ctx, ex, ey, r * 0.09, r * 0.12)
            ctx.set_source_rgb(*INK)
            ctx.fill()
            circle(ctx, ex + r * 0.03, ey - r * 0.04, r * 0.035)
            ctx.set_source_rgb(1, 1, 1)
            ctx.fill()
        lift = brow * (1.0 if sx == -1 else 0.4)
        ctx.move_to(ex - r * 0.15, ey - r * (0.25 + 0.12 * lift))
        ctx.curve_to(ex - r * 0.05, ey - r * (0.33 + 0.16 * lift), ex + r * 0.05, ey - r * (0.33 + 0.16 * lift),
                     ex + r * 0.15, ey - r * (0.26 + 0.1 * lift))
        ctx.set_source_rgb(*mix(hair_colour if hair != 'bald' else HAIR, INK, 0.3))
        ctx.set_line_width(max(2, r * 0.07))
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    if glasses:
        for sx in (-1, 1):
            circle(ctx, x + sx * r * 0.36, y, r * 0.22)
        ctx.move_to(x - r * 0.14, y - r * 0.02)
        ctx.line_to(x + r * 0.14, y - r * 0.02)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(max(2, r * 0.05))
        ctx.stroke()
    ctx.move_to(x - r * 0.04, y + r * 0.1)                           # the nose
    ctx.curve_to(x - r * 0.12, y + r * 0.26, x + r * 0.02, y + r * 0.3, x + r * 0.1, y + r * 0.24)
    ctx.set_source_rgba(*mix(skin, INK, 0.5), 0.9)
    ctx.set_line_width(max(1.5, r * 0.04))
    ctx.stroke()
    for sx in (-1, 1):
        ellipse(ctx, x + sx * r * 0.62, y + r * 0.32, r * 0.16, r * 0.09)
        ctx.set_source_rgba(1.0, 0.45, 0.45, 0.4)
        ctx.fill()
    if bindi:
        circle(ctx, x, y - r * 0.34, r * 0.075)
        ctx.set_source_rgb(*SINDOOR)
        ctx.fill()
    if mouth > 0.08:
        ctx.move_to(x - r * 0.38, y + r * 0.42)
        ctx.curve_to(x - r * 0.28, y + r * (0.62 + 0.32 * mouth), x + r * 0.28, y + r * (0.62 + 0.32 * mouth),
                     x + r * 0.38, y + r * 0.42)
        ctx.close_path()
        ctx.set_source_rgb(0.42, 0.1, 0.12)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(max(2, r * 0.06))
        ctx.stroke()
        ctx.rectangle(x - r * 0.26, y + r * 0.43, r * 0.52, r * 0.07)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
    else:
        ctx.move_to(x - r * 0.36, y + r * 0.42)
        ctx.curve_to(x - r * 0.22, y + r * (0.42 + 0.28 * smile), x + r * 0.22, y + r * (0.42 + 0.28 * smile),
                     x + r * 0.36, y + r * 0.42)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(max(2, r * 0.07))
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    if moustache:
        for sx in (-1, 1):
            ctx.move_to(x, y + r * 0.33)
            ctx.curve_to(x + sx * r * 0.2, y + r * 0.24, x + sx * r * 0.42, y + r * 0.3, x + sx * r * 0.52, y + r * 0.2)
            ctx.curve_to(x + sx * r * 0.45, y + r * 0.44, x + sx * r * 0.2, y + r * 0.42, x, y + r * 0.4)
            ctx.close_path()
        inked(ctx, moustache, 2, (1, 1))


def jutti(ctx, x, y, s, colour=GOLD, facing=1):
    """A embroidered jutti, its toe curling up."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s * facing, s)
    ctx.move_to(-20, 0)
    ctx.curve_to(-22, -12, -6, -14, 6, -10)
    ctx.curve_to(16, -8, 24, -10, 28, -20)
    ctx.curve_to(31, -12, 26, 0, 14, 2)
    ctx.close_path()
    inked(ctx, colour, 2.5, (2, 2))
    for k in range(3):
        circle(ctx, -8 + k * 8, -6, 1.8)
    ctx.set_source_rgb(*SINDOOR)
    ctx.fill()
    ctx.restore()


def dancer(ctx, x, ground, s, t, who, arms, step=0.0, lean=0.0):
    """A wedding guest, full length: kurta and churidar, juttis. arms gives each hand's
    position from its shoulder, (dx, dy), left then right."""
    ctx.save()
    ctx.translate(x, ground)
    ctx.scale(s, s)
    ctx.rotate(lean)
    bounce = 7 * abs(math.sin(step * math.pi))
    hip = -128 - bounce
    for side in (-1, 1):                                             # the legs, a hop on each beat
        lift = max(0.0, math.sin(step * math.pi + (side + 1) * math.pi / 2)) * 22
        foot = (side * 22, -lift)
        hp = (side * 16, hip)
        kn = (side * 26 + 6, (hip + foot[1]) / 2 - lift * 0.3)
        limb(ctx, hp, kn, foot, who['pants'], 22)
        jutti(ctx, foot[0] + 4, foot[1] + 4, 1.0, who.get('shoes', GOLD))
    top = -262 - bounce
    ctx.move_to(-44, top + 14)                                       # the kurta
    ctx.curve_to(-50, top, 50, top, 44, top + 14)
    ctx.line_to(56, hip + 26)
    ctx.line_to(-56, hip + 26)
    ctx.close_path()
    inked(ctx, who['kurta'], 4, (4, 4))
    if who.get('jacket'):
        for sx in (-1, 1):
            ctx.move_to(sx * 8, top + 6)
            ctx.line_to(sx * 42, top + 12)
            ctx.line_to(sx * 48, hip - 6)
            ctx.line_to(sx * 8, hip - 6)
            ctx.close_path()
            inked(ctx, who['jacket'], 3, (0, 0))
    ctx.move_to(0, top + 4)                                          # the placket and its buttons
    ctx.line_to(0, top + 64)
    ctx.set_source_rgba(*INK, 0.6)
    ctx.set_line_width(2.5)
    ctx.stroke()
    for k in range(3):
        circle(ctx, 0, top + 18 + k * 16, 3)
    ctx.set_source_rgb(*GOLD)
    ctx.fill()
    if who.get('scarf'):
        ctx.move_to(-38, top + 8)
        ctx.curve_to(-20, top + 50, 20, top + 50, 38, top + 8)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(16)
        ctx.stroke()
        ctx.move_to(-38, top + 8)
        ctx.curve_to(-20, top + 50, 20, top + 50, 38, top + 8)
        ctx.set_source_rgb(*who['scarf'])
        ctx.set_line_width(10)
        ctx.stroke()
    for side, (dx, dy) in zip((-1, 1), arms):                        # the arms
        sh = (side * 40, top + 16)
        hand = (sh[0] + dx, sh[1] + dy)
        mid = ((sh[0] + hand[0]) / 2 + side * 22, (sh[1] + hand[1]) / 2 + 8)
        limb(ctx, sh, mid, hand, who['kurta'], 20)
        circle(ctx, *hand, 11)
        inked(ctx, who['skin'], 2.5, (2, 2))
    head(ctx, 0, top - 46, 44, who['skin'], **who.get('head', {}))
    ctx.restore()


def bulb_arms(t, rate=2.0, phase=0.0):
    """Bhangra's light bulb: both hands up, turning."""
    a = t * TAU * rate + phase
    return ((-22 + 9 * math.cos(a), -110 + 9 * math.sin(a)), (22 + 9 * math.cos(a + 1), -112 + 9 * math.sin(a + 1)))


def dog_arms(t, rate=2.0):
    """Bhangra's patting the dog: one hand up, the other patting down by the hip."""
    pat = math.sin(t * TAU * rate * 2)
    return ((-30, -112 + 6 * pat), (52, 64 + 12 * pat))


# ---------------------------------------------------------------- the groom

def safa(ctx, open_=0.0, t=0.0, plume=True, sehra=True):
    """The groom's red safa on the TV's cabinet (in the TV's units), with the kalgi, and the
    sehra over the screen; open_ parts its strands to the sides."""
    ctx.move_to(-132, -102)
    ctx.curve_to(-150, -170, -90, -214, 0, -216)
    ctx.curve_to(90, -214, 150, -170, 132, -102)
    ctx.curve_to(70, -118, -70, -118, -132, -102)
    ctx.close_path()
    shade = cairo.LinearGradient(-140, 0, 140, 0)
    shade.add_color_stop_rgb(0, *mix(SINDOOR, WHITE, 0.12))
    shade.add_color_stop_rgb(0.6, *SINDOOR)
    shade.add_color_stop_rgb(1, *mix(SINDOOR, INK, 0.3))
    inked(ctx, shade, 5, (4, 4))
    ctx.save()
    ctx.move_to(-132, -102)
    ctx.curve_to(-150, -170, -90, -214, 0, -216)
    ctx.curve_to(90, -214, 150, -170, 132, -102)
    ctx.curve_to(70, -118, -70, -118, -132, -102)
    ctx.clip()
    ctx.set_source_rgba(*GOLD, 0.9)                                  # bands of gold zari
    ctx.set_line_width(7)
    for k in range(-4, 5):
        ctx.move_to(-160 + k * 40, -100)
        ctx.line_to(-60 + k * 40, -220)
    ctx.stroke()
    ctx.restore()
    ctx.move_to(118, -150)                                           # the turra, a fan at the side
    ctx.curve_to(170, -190, 196, -150, 186, -120)
    ctx.curve_to(170, -130, 150, -128, 128, -122)
    ctx.close_path()
    inked(ctx, GOLD, 4, (3, 3))
    if plume:                                                        # the kalgi: a jewel and a plume
        sway = 4 * math.sin(t * 3.0)
        ctx.move_to(0, -170)
        ctx.curve_to(10, -230, 40 + sway, -260, 64 + sway, -290)
        ctx.curve_to(50 + sway, -250, 30, -220, 12, -170)
        ctx.close_path()
        inked(ctx, JASMINE, 3, (2, 2))
        circle(ctx, 0, -168, 15)
        inked(ctx, GOLD, 3, (2, 2))
        circle(ctx, 0, -168, 7)
        ctx.set_source_rgb(0.1, 0.65, 0.35)
        ctx.fill()
    if not sehra:
        return
    # The sehra: strands from the safa's brim down over the screen.
    for k in range(13):
        u = k / 12
        x = -124 + 190 * u
        centre = -29
        side = -1 if x < centre else 1
        spread = open_ * (abs(x - centre) * 0.15 + 70) * side
        gathered = x + spread + (open_ * (-150 - x) if side < 0 else open_ * (150 - x)) * 0.5
        sway = 5 * math.sin(t * 2.5 + k * 0.7) * (1 - open_)
        strand(ctx, gathered, -110, 92 - 20 * open_, 8.5, sway, pearls=True)


def varmala(ctx, x0, x1, y, drop, r=11):
    """The wedding garland round the neck: a deep U of marigolds and roses."""
    garland(ctx, x0, y, x1, y, drop * 1.33, r)


def groom(ctx, x, y, s, t, lit=1.0, open_=1.0, garland_=True, sehra=True):
    """The station's TV dressed as the groom, centred on (x, y), s of its size."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    A.draw_tv(ctx, t, 1, 0.0)
    if lit < 1:
        rounded_rect(ctx, -128, -88, 198, 176, 28)
        ctx.set_source_rgba(0.02, 0.03, 0.08, 0.82 * (1 - lit))
        ctx.fill()
    safa(ctx, open_, t, sehra=sehra)
    if garland_:
        varmala(ctx, -118, 118, 100, 80, 12)
    ctx.restore()


# ---------------------------------------------------------------- the bride

def remote(ctx, x, y, s, t, led=0.0, dressed=True, garland_=True):
    """The remote as the bride: lehenga, dupatta, maang tikka; its IR light blinks, shy."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    if dressed:                                                      # the dupatta's back, behind
        ctx.move_to(-72, 140)
        ctx.curve_to(-84, -60, -72, -200, 0, -206)
        ctx.curve_to(72, -200, 84, -60, 72, 140)
        ctx.close_path()
        ctx.set_source_rgba(*mix(SINDOOR, MAROON, 0.4), 1)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(4)
        ctx.stroke()
    rounded_rect(ctx, -56, -165, 112, 330, 42)
    body = cairo.LinearGradient(-56, 0, 56, 0)
    body.add_color_stop_rgb(0, 0.32, 0.32, 0.38)
    body.add_color_stop_rgb(0.5, 0.2, 0.2, 0.25)
    body.add_color_stop_rgb(1, 0.12, 0.12, 0.16)
    inked(ctx, body, 5, (5, 5))
    circle(ctx, 0, -150, 6)                                          # the IR window
    ctx.set_source_rgb(*mix((0.3, 0.05, 0.05), (1.0, 0.2, 0.2), led))
    ctx.fill()
    glow(ctx, 0, -150, 26, (1.0, 0.25, 0.25), led)
    circle(ctx, 0, -112, 15)                                         # power
    inked(ctx, SINDOOR, 2.5, (2, 2))
    ctx.arc(0, -112, 7, -1.1, 4.25)
    ctx.set_source_rgb(1, 1, 1)
    ctx.set_line_width(2.5)
    ctx.stroke()
    font(ctx, 'Nimbus Sans', 13)
    for row in range(3):                                             # the number pad
        for col in range(3):
            bx, by = -30 + col * 30, -70 + row * 30
            rounded_rect(ctx, bx - 11, by - 9, 22, 18, 6)
            ctx.set_source_rgb(0.55, 0.56, 0.62)
            ctx.fill()
            ctx.set_source_rgb(*INK)
            centred(ctx, str(row * 3 + col + 1), bx, by + 5)
            ctx.fill()
    circle(ctx, 0, 30, 26)                                           # the d-pad, and OK
    ctx.set_source_rgb(0.42, 0.43, 0.5)
    ctx.fill()
    circle(ctx, 0, 30, 11)
    ctx.set_source_rgb(*TEAL)
    ctx.fill()
    if dressed:
        ctx.move_to(-50, 64)                                         # the lehenga
        ctx.curve_to(-60, 110, -98, 150, -104, 172)
        ctx.curve_to(-40, 186, 40, 186, 104, 172)
        ctx.curve_to(98, 150, 60, 110, 50, 64)
        ctx.close_path()
        skirt = cairo.LinearGradient(0, 64, 0, 180)
        skirt.add_color_stop_rgb(0, SINDOOR[0] * 0.95, SINDOOR[1], SINDOOR[2])
        skirt.add_color_stop_rgb(1, *mix(SINDOOR, MAROON, 0.5))
        inked(ctx, skirt, 4, (4, 4))
        ctx.move_to(-102, 166)                                       # its gold border, and butis
        ctx.curve_to(-40, 180, 40, 180, 102, 166)
        ctx.set_source_rgb(*GOLD)
        ctx.set_line_width(9)
        ctx.stroke()
        for k in range(7):
            circle(ctx, -54 + k * 18, 120 + 10 * abs(k - 3) ** 0.5, 3.2)
        ctx.set_source_rgb(*GOLD)
        ctx.fill()
        ctx.move_to(-50, 66)                                         # the waistband
        ctx.line_to(50, 66)
        ctx.set_source_rgb(*GOLD)
        ctx.set_line_width(7)
        ctx.stroke()
        # The dupatta over the top: sheer red with a gold border.
        ctx.move_to(-76, 120)
        ctx.curve_to(-88, -70, -72, -198, 0, -204)
        ctx.curve_to(72, -198, 88, -70, 76, 120)
        ctx.line_to(62, 120)
        ctx.curve_to(72, -40, 58, -178, 0, -184)
        ctx.curve_to(-58, -178, -72, -40, -62, 120)
        ctx.close_path()
        ctx.set_source_rgba(*SINDOOR, 0.92)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(3)
        ctx.stroke()
        ctx.move_to(-69, 120)
        ctx.curve_to(-80, -60, -66, -190, 0, -194)
        ctx.curve_to(66, -190, 80, -60, 69, 120)
        ctx.set_source_rgb(*GOLD)
        ctx.set_line_width(5)
        ctx.stroke()
        ctx.move_to(0, -190)                                         # the maang tikka
        ctx.line_to(0, -160)
        ctx.set_source_rgb(*GOLD_DARK)
        ctx.set_line_width(2)
        ctx.stroke()
        ctx.move_to(0, -160)
        ctx.line_to(-8, -150)
        ctx.line_to(0, -136)
        ctx.line_to(8, -150)
        ctx.close_path()
        inked(ctx, GOLD, 2, (1, 1))
        circle(ctx, 0, -150, 3)
        ctx.set_source_rgb(0.1, 0.65, 0.35)
        ctx.fill()
        if garland_:
            varmala(ctx, -58, 58, -40, 92, 10)
    ctx.restore()


# ---------------------------------------------------------------- 1. the baraat

GROUND = 690
UNCLES = (
    {'skin': SKINS[0], 'kurta': (0.98, 0.72, 0.2), 'pants': IVORY, 'scarf': SINDOOR,
     'head': {'turban': (0.95, 0.45, 0.1), 'beard': SILVER, 'moustache': SILVER, 'hair': 'none'}},
    {'skin': SKINS[1], 'kurta': (0.38, 0.72, 0.85), 'pants': IVORY, 'jacket': (0.2, 0.25, 0.5),
     'head': {'hair': 'bald', 'hair_colour': SILVER, 'moustache': HAIR, 'glasses': True}},
)
DHOLI = {'skin': SKINS[3], 'kurta': (0.85, 0.2, 0.55), 'pants': (0.95, 0.92, 0.82), 'scarf': YELLOW,
         'head': {'turban': (0.98, 0.82, 0.15), 'moustache': HAIR, 'hair': 'none'}}


@lru_cache(maxsize=None)
def baraat_back():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    sky = cairo.LinearGradient(0, 0, 0, 520)
    sky.add_color_stop_rgb(0, 0.05, 0.05, 0.18)
    sky.add_color_stop_rgb(0.7, 0.22, 0.09, 0.3)
    sky.add_color_stop_rgb(1, 0.45, 0.16, 0.28)
    ctx.set_source(sky)
    ctx.paint()
    rand = random.Random(19)
    for _ in range(60):
        circle(ctx, rand.uniform(0, W), rand.uniform(0, 300), rand.uniform(0.6, 1.4))
        ctx.set_source_rgba(1, 0.96, 0.9, rand.uniform(0.3, 0.8))
        ctx.fill()
    # Rowhouses across the street, in silhouette, a window or two lit.
    x = -20
    while x < 760:
        w = rand.uniform(90, 140)
        top = rand.uniform(300, 360)
        ctx.rectangle(x, top, w, 520 - top)
        ctx.set_source_rgb(*mix((0.08, 0.06, 0.14), (0.2, 0.1, 0.22), rand.random() * 0.6))
        ctx.fill()
        for wy in (top + 30, top + 90):
            for wx in (x + 18, x + w - 42):
                if rand.random() < 0.45:
                    ctx.rectangle(wx, wy, 22, 34)
                    ctx.set_source_rgb(1.0, 0.8, 0.45)
                    ctx.fill()
        x += w + 4
    # The banquet hall's gate on the right: a cusped arch, marigolds hung all over it.
    gx = 930
    ctx.rectangle(gx, 140, 360, 400)
    hall = cairo.LinearGradient(0, 140, 0, 540)
    hall.add_color_stop_rgb(0, 0.96, 0.88, 0.8)
    hall.add_color_stop_rgb(1, 0.93, 0.62, 0.5)
    inked(ctx, hall, 4, (0, 0))
    ctx.move_to(gx + 60, 540)
    ctx.line_to(gx + 60, 330)
    ctx.curve_to(gx + 60, 250, gx + 130, 220, gx + 160, 200)
    ctx.curve_to(gx + 190, 220, gx + 260, 250, gx + 260, 330)
    ctx.line_to(gx + 260, 540)
    ctx.close_path()
    inside = cairo.LinearGradient(0, 200, 0, 540)
    inside.add_color_stop_rgb(0, 1.0, 0.85, 0.5)
    inside.add_color_stop_rgb(1, 0.95, 0.5, 0.25)
    inked(ctx, inside, 4, (0, 0))
    for k in range(12):
        strand(ctx, gx + 66 + k * 17.5, 214 + 40 * abs(k - 5.5) ** 0.8 * 0.5, 300 + 10 * (k % 3), 7)
    garland(ctx, gx + 20, 160, gx + 340, 160, 50, 10)
    ctx.rectangle(0, 520, W, H - 520)                                # the street
    street = cairo.LinearGradient(0, 520, 0, H)
    street.add_color_stop_rgb(0, 0.24, 0.16, 0.22)
    street.add_color_stop_rgb(1, 0.14, 0.1, 0.14)
    ctx.set_source(street)
    ctx.fill()
    ctx.rectangle(0, 520, W, 8)
    ctx.set_source_rgb(0.35, 0.25, 0.3)
    ctx.fill()
    # The welcome board, on an easel by the gate.
    bx, by, bw, bh = 1040, 330, 216, 176
    for lx in (bx + 40, bx + bw - 40):
        ctx.move_to(lx, by + bh)
        ctx.line_to(lx + (lx - bx - bw / 2) * 0.2, 540)
        ctx.set_source_rgb(*mix(COPPER, INK, 0.4))
        ctx.set_line_width(7)
        ctx.stroke()
    rounded_rect(ctx, bx, by, bw, bh, 12)
    inked(ctx, IVORY, 4, (5, 5))
    rounded_rect(ctx, bx + 8, by + 8, bw - 16, bh - 16, 8)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(3)
    ctx.stroke()
    label(ctx, 'WELCOME TO THE WEDDING OF', bx + bw / 2, by + 34, 10, MAROON, tracking=0.6)
    font(ctx, 'Z003', 40, bold=False)
    ctx.set_source_rgb(*SINDOOR)
    centred(ctx, 'TV & Remote', bx + bw / 2, by + 82)
    ctx.fill()
    ctx.move_to(bx + 40, by + 100)
    ctx.line_to(bx + bw - 40, by + 100)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(2)
    ctx.stroke()
    label(ctx, 'GUESTS: 1,900', bx + bw / 2, by + 126, 15, INK, tracking=1.5)
    label(ctx, 'KNOWN TO THE COUPLE: 19', bx + bw / 2, by + 150, 12, mix(INK, WHITE, 0.3), tracking=1.0)
    return surface


def mare(ctx, x, ground, s, t, rear=0.0):
    """The white mare, side on, walking right, dressed for the baraat."""
    gait = t * TAU * 1.4
    ctx.save()
    ctx.translate(x, ground)
    ctx.scale(s, s)
    ctx.rotate(-0.06 * rear)
    lift = 6 * abs(math.sin(gait))

    def leg(hip_x, phase, colour):
        swing = math.sin(gait + phase)
        foot = (hip_x + 26 * swing, -max(0.0, 26 * math.cos(gait + phase)))
        knee = ((hip_x + foot[0]) / 2 + 12 * swing, -88 - lift * 0.5)
        limb(ctx, (hip_x, -170 - lift), knee, foot, colour, 22)
        rounded_rect(ctx, foot[0] - 13, foot[1] - 10, 26, 14, 4)
        ctx.set_source_rgb(*INK)
        ctx.fill()

    leg(-88, math.pi, MARE_SHADE)                                    # the far legs
    leg(92, 0.0, MARE_SHADE)
    ctx.move_to(-126, -212 - lift)                                   # the tail
    ctx.curve_to(-170, -200, -176, -130, -160, -78)
    ctx.curve_to(-150, -120, -140, -170, -122, -190 - lift)
    ctx.close_path()
    inked(ctx, (0.9, 0.86, 0.78), 4, (3, 3))
    ctx.move_to(56, -236 - lift)                                     # the neck
    ctx.curve_to(94, -296, 112, -326, 126, -352 - lift)
    ctx.line_to(178, -324 - lift)
    ctx.curve_to(170, -272, 160, -214, 138, -170 - lift)
    ctx.close_path()
    inked(ctx, MARE, 5, (5, 5))
    ellipse(ctx, 0, -196 - lift, 134, 56)                            # the body
    inked(ctx, MARE, 5, (5, 5))
    ctx.move_to(124, -352 - lift)                                    # the head
    ctx.curve_to(150, -376, 176, -368, 196, -330)
    ctx.line_to(226, -290)
    ctx.curve_to(232, -276, 214, -266, 200, -276)
    ctx.line_to(164, -308)
    ctx.curve_to(148, -312, 132, -330, 124, -352 - lift)
    ctx.close_path()
    inked(ctx, MARE, 5, (5, 5))
    for ex in (136, 150):                                            # the ears
        ctx.move_to(ex, -358 - lift)
        ctx.line_to(ex + 4, -390 - lift)
        ctx.line_to(ex + 14, -360 - lift)
        ctx.close_path()
        inked(ctx, MARE, 3, (2, 2))
    circle(ctx, 172, -336 - lift, 5)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    circle(ctx, 216, -286, 3)
    ctx.fill()
    for k in range(7):                                               # the mane
        mx = 118 - k * 9 + 0
        my = -350 + k * 24 - lift
        ellipse(ctx, mx, my, 12, 16)
    inked(ctx, (0.88, 0.84, 0.76), 3, (2, 2))
    ctx.move_to(140, -360 - lift)                                    # the head plume and browband
    ctx.curve_to(150, -400, 130, -430, 150, -450)
    ctx.curve_to(160, -425, 168, -400, 156, -358 - lift)
    ctx.close_path()
    inked(ctx, SINDOOR, 3, (2, 2))
    ctx.move_to(130, -340 - lift)
    ctx.line_to(190, -318 - lift)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(6)
    ctx.stroke()
    for k in range(5):
        circle(ctx, 136 + k * 13, -337 + k * 4.7 - lift, 3)
    ctx.set_source_rgb(*ROSE)
    ctx.fill()
    garland(ctx, 96, -280 - lift, 150, -230 - lift, 50, 9, roses=True)    # round the neck
    # The saddle cloth: red with a gold border and a fringe.
    ctx.move_to(-78, -244 - lift)
    ctx.curve_to(-30, -258, 30, -258, 74, -244 - lift)
    ctx.line_to(84, -150 - lift)
    ctx.line_to(-88, -150 - lift)
    ctx.close_path()
    inked(ctx, SINDOOR, 4, (3, 3))
    ctx.rectangle(-80, -168 - lift, 158, 10)
    ctx.set_source_rgb(*GOLD)
    ctx.fill()
    for k in range(9):
        circle(ctx, -60 + k * 15, -205 - lift + 6 * (k % 2), 4)
    ctx.set_source_rgb(*GOLD)
    ctx.fill()
    for k in range(18):
        ctx.move_to(-86 + k * 9.8, -150 - lift)
        ctx.line_to(-86 + k * 9.8 + 2 * math.sin(gait + k), -134 - lift)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(3)
    ctx.stroke()
    leg(-108, 0.0, MARE)                                             # the near legs
    leg(72, math.pi, MARE)
    ctx.restore()
    return lift * s


def dholi(ctx, x, ground, s, t):
    """The dhol player: the drum slung across him, the dagga in his right hand, the tilli in
    his left, striking the heads on the groove and the logo."""
    strike = 0.0
    for at in DHOL:
        strike = max(strike, pulse(t, at, 0.16))
    groove = 0.0
    if GROOVE[0] <= t < GROOVE[1]:
        groove = pulse(t, GROOVE[0] + math.floor((t - GROOVE[0]) / 0.25) * 0.25, 0.12)
    right = (54 - 30 * strike, 80 - 24 * strike)                     # the hand that holds the dagga
    left = (-30 + 10 * groove, 86 - 18 * groove)
    dancer(ctx, x, ground, s, t, DHOLI, (left, right), step=(t * 2.0) % 2)
    ctx.save()
    ctx.translate(x, ground)
    ctx.scale(s, s)
    bounce = 7 * abs(math.sin(((t * 2.0) % 2) * math.pi))
    cy = -170 - bounce
    ctx.move_to(-40, -250 - bounce)                                  # the strap
    ctx.line_to(30, cy - 40)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(7)
    ctx.stroke()
    ctx.rectangle(-78, cy - 44, 156, 88)                             # the drum
    shell = cairo.LinearGradient(0, cy - 44, 0, cy + 44)
    shell.add_color_stop_rgb(0, 0.75, 0.46, 0.22)
    shell.add_color_stop_rgb(0.5, 0.58, 0.3, 0.12)
    shell.add_color_stop_rgb(1, 0.4, 0.2, 0.08)
    inked(ctx, shell, 4, (4, 4))
    ctx.move_to(-70, cy - 40)
    for k in range(9):                                               # its rope, zigzagged
        ctx.line_to(-70 + (k + 0.5) * 15.5, cy + (40 if k % 2 == 0 else -40))
    ctx.set_source_rgb(*IVORY)
    ctx.set_line_width(3)
    ctx.stroke()
    for side, ring in ((-1, MARIGOLD_Y), (1, SINDOOR)):
        ellipse(ctx, side * 78, cy, 16, 46)
        inked(ctx, (0.95, 0.9, 0.78), 4, (2, 2))
        ellipse(ctx, side * 78, cy, 16, 46)
        ctx.set_source_rgb(*ring)
        ctx.set_line_width(4)
        ctx.stroke()
    hx, hy = 40 + right[0], -246 - bounce + right[1]                 # the dagga, curved
    ctx.move_to(hx, hy)
    ctx.curve_to(hx + 20, hy + 8, hx + 34, hy + 30, hx + 40, hy + 44 - 10 * strike)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(7)
    ctx.stroke()
    hx, hy = -40 + left[0], -246 - bounce + left[1]                  # the tilli, a thin cane
    ctx.move_to(hx, hy)
    ctx.line_to(hx - 46, hy + 28)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.restore()


def baraat(ctx, t):
    ctx.set_source_surface(baraat_back(), 0, 0)
    ctx.paint()
    ctx.save()                                                       # fairy lights strung over the street
    for k, (x0, x1, y, sag) in enumerate(((-20, 420, 40, 70), (400, 940, 30, 80), (920, 1300, 50, 60))):
        fairy_lights(ctx, fairy_swag(x0, y, x1, y + 10, sag), t, k)
    ctx.restore()
    for k, at in enumerate(DHOL):                                    # a firework on each stroke
        big = k == 3
        firework(ctx, t, at, (230, 560, 380, 720)[k], (150, 110, 190, 120)[k], 170 if big else 120,
                 BURST if big else (BURST[k], mix(BURST[k], WHITE, 0.5)), 44 if big else 30, seed=k)
    drift = 15 * t                                                   # the procession moves along
    open_ = ease_in_out(span(t, *SEHRA))
    lit = ease_out(span(t, DHOL[3], DHOL[3] + 0.2))
    pose = [pulse(t, at, 0.3) for at in DHOL]
    step = (t * 2.0) % 2
    lift = mare(ctx, 720 + drift, GROUND, 0.95, t, rear=pulse(t, DHOL[3], 0.5))
    groom(ctx, 712 + drift, GROUND - 0.95 * 244 - lift - 50, 0.43, t, lit=0.25 + 0.75 * lit, open_=open_)
    dholi(ctx, 445 + drift, GROUND, 0.92, t)
    arms = bulb_arms(t, 2.0)
    if any(p > 0.2 for p in pose[::2]):
        arms = ((-60, -90), (60, -90))                               # a big "hoi!" on the strokes
    dancer(ctx, 95 + drift, GROUND, 0.95, t, UNCLES[0], arms, step=step, lean=-0.06 * math.sin(t * 4))
    arms = dog_arms(t, 2.0)
    if any(p > 0.2 for p in pose[1::2]):
        arms = ((-50, -100), (50, -100))
    dancer(ctx, 268 + drift, GROUND - 14, 0.86, t, UNCLES[1], arms, step=(step + 1) % 2,
           lean=0.05 * math.sin(t * 4 + 1))


# ---------------------------------------------------------------- 2. the mandap

TV_AT, REMOTE_AT = (480, 508), (820, 425)


@lru_cache(maxsize=None)
def mandap_back():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    back = cairo.LinearGradient(0, 0, 0, H)
    back.add_color_stop_rgb(0, 0.32, 0.04, 0.14)
    back.add_color_stop_rgb(1, 0.55, 0.12, 0.2)
    ctx.set_source(back)
    ctx.paint()
    for k in range(18):                                              # draped fabric, in folds
        x = k * 76 - 20
        fold = cairo.LinearGradient(x, 0, x + 76, 0)
        fold.add_color_stop_rgba(0, 1, 0.6, 0.7, 0.0)
        fold.add_color_stop_rgba(0.5, 1, 0.6, 0.7, 0.13)
        fold.add_color_stop_rgba(1, 1, 0.6, 0.7, 0.0)
        ctx.rectangle(x, 0, 76, H)
        ctx.set_source(fold)
        ctx.fill()
    rand = random.Random(7)
    for k in range(30):                                              # a curtain of fairy lights
        x = 30 + k * 42
        for j in range(int(rand.uniform(9, 14))):
            y = 150 + j * 34 + (k % 2) * 17
            g = cairo.RadialGradient(x, y, 0, x, y, 9)
            g.add_color_stop_rgba(0, *FAIRY, 0.8)
            g.add_color_stop_rgba(1, *FAIRY, 0)
            ctx.set_source(g)
            ctx.arc(x, y, 9, 0, TAU)
            ctx.fill()
            circle(ctx, x, y, 1.8)
            ctx.set_source_rgb(1, 0.95, 0.8)
            ctx.fill()
    ctx.rectangle(0, 590, W, H - 590)                                # the stage, in white and gold
    stage = cairo.LinearGradient(0, 590, 0, H)
    stage.add_color_stop_rgb(0, 0.98, 0.92, 0.82)
    stage.add_color_stop_rgb(1, 0.85, 0.7, 0.55)
    ctx.set_source(stage)
    ctx.fill()
    ctx.rectangle(0, 586, W, 8)
    ctx.set_source_rgb(*GOLD)
    ctx.fill()
    rand = random.Random(3)
    for k in range(40):                                              # rangoli petals strewn on it
        marigold(ctx, rand.uniform(0, W), rand.uniform(620, 715), rand.uniform(5, 8),
                 rand.choice((MARIGOLD, MARIGOLD_Y, ROSE)))
    for px in (150, 1130):                                           # the pillars, wound with marigolds
        ctx.rectangle(px - 28, 120, 56, 480)
        col = cairo.LinearGradient(px - 28, 0, px + 28, 0)
        col.add_color_stop_rgb(0, *mix(GOLD, WHITE, 0.3))
        col.add_color_stop_rgb(0.5, *GOLD)
        col.add_color_stop_rgb(1, *GOLD_DARK)
        inked(ctx, col, 4, (5, 5))
        for k in range(26):
            y = 130 + k * 18
            marigold(ctx, px - 22 + 44 * (0.5 + 0.5 * math.sin(k * 0.9)), y, 8, MARIGOLD if k % 2 else MARIGOLD_Y)
        rounded_rect(ctx, px - 40, 586, 80, 22, 4)
        inked(ctx, GOLD_DARK, 3, (2, 2))
    # The canopy: a red swag with a gold fringe, and marigold strands hanging from it.
    ctx.move_to(0, 0)
    ctx.line_to(W, 0)
    ctx.line_to(W, 100)
    for k in range(8, -1, -1):
        x = k * W / 8
        ctx.curve_to(x + W / 16, 150, x + W / 16, 150, x, 100)
    ctx.close_path()
    inked(ctx, SINDOOR, 4, (0, 6))
    for k in range(8):
        x = k * W / 8
        pts = path_points((x, 100), (x + W / 16, 150), (x + W / 16, 150), (x + W / 8, 100), 12)
        for (fx, fy) in pts:
            ctx.move_to(fx, fy)
            ctx.line_to(fx, fy + 12)
        ctx.set_source_rgb(*GOLD)
        ctx.set_line_width(2.5)
        ctx.stroke()
    ctx.rectangle(0, 0, W, 26)
    ctx.set_source_rgb(*GOLD)
    ctx.fill()
    for k in range(17):
        x = 40 + k * 75
        strand(ctx, x, 30, 88 + 18 * (k % 2), 7)
    return surface


def flames(ctx, x, y, t, scale=1.0, seed=0):
    """The sacred fire: tongues of flame licking up, flickering."""
    rand = random.Random(seed)
    glow(ctx, x, y - 40 * scale, 160 * scale, (1.0, 0.55, 0.2), 0.55 + 0.1 * math.sin(t * 17))
    for layer, colour in enumerate(((0.95, 0.3, 0.06), (1.0, 0.6, 0.1), (1.0, 0.88, 0.4))):
        k_scale = 1 - layer * 0.28
        for k in range(5):
            off = (k - 2) * 22 * scale * k_scale
            h = (70 + 30 * math.sin(t * rand.uniform(9, 14) + k * 1.7 + layer)) * scale * k_scale
            sway = 8 * math.sin(t * rand.uniform(5, 8) + k) * scale
            w = 20 * scale * k_scale
            ctx.move_to(x + off - w, y)
            ctx.curve_to(x + off - w, y - h * 0.5, x + off + sway, y - h * 0.7, x + off + sway, y - h)
            ctx.curve_to(x + off + sway, y - h * 0.7, x + off + w, y - h * 0.5, x + off + w, y)
            ctx.close_path()
        ctx.set_source_rgb(*colour)
        ctx.fill()


def havan_kund(ctx, x, y, t, s=1.0):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    x = y = 0
    flames(ctx, x, y - 30, t, 0.9)
    ctx.move_to(x - 92, y - 34)                                      # the copper kund
    ctx.line_to(x + 92, y - 34)
    ctx.line_to(x + 66, y + 22)
    ctx.line_to(x - 66, y + 22)
    ctx.close_path()
    body = cairo.LinearGradient(0, y - 34, 0, y + 22)
    body.add_color_stop_rgb(0, *mix(COPPER, WHITE, 0.25))
    body.add_color_stop_rgb(1, *mix(COPPER, INK, 0.35))
    inked(ctx, body, 4, (4, 4))
    for k in range(3):
        ctx.move_to(x - 84 + k * 8, y - 26 + k * 16)
        ctx.line_to(x + 84 - k * 8, y - 26 + k * 16)
    ctx.set_source_rgba(*INK, 0.35)
    ctx.set_line_width(2)
    ctx.stroke()
    ctx.restore()


def knot_path(progress):
    """The gathbandhan: from the groom's scarf to the bride's dupatta, drawn on from both ends."""
    a = (TV_AT[0] + 100, TV_AT[1] + 10)
    b = (REMOTE_AT[0] - 70, REMOTE_AT[1] + 60)
    return path_points(a, (a[0] + 40, a[1] + 45), (b[0] - 40, b[1] + 45), b, 40), progress


def gathbandhan(ctx, t):
    p = ease_in_out(span(t, *KNOT))
    if p <= 0:
        return
    pts, _ = knot_path(p)
    n = len(pts) - 1
    half = int(round(n / 2 * p))
    for seg in (pts[:half + 1], pts[n - half:]):
        if len(seg) < 2:
            continue
        for width, colour in ((20, INK), (14, (1.0, 0.85, 0.3)), (6, ROSE)):
            ctx.move_to(*seg[0])
            for q in seg[1:]:
                ctx.line_to(*q)
            ctx.set_source_rgb(*colour)
            ctx.set_line_width(width)
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.stroke()
    if p >= 1:                                                       # the knot itself, and a sparkle
        mx, my = pts[n // 2]
        tied = max(0.01, back_out(span(t, KNOT[1], KNOT[1] + 0.25)))
        ctx.save()
        ctx.translate(mx, my)
        ctx.scale(tied, tied)
        for sx in (-1, 1):
            ellipse(ctx, sx * 16, -4, 18, 10)
            inked(ctx, (1.0, 0.85, 0.3), 3, (2, 2))
        circle(ctx, 0, 0, 9)
        inked(ctx, SINDOOR, 3, (2, 2))
        ctx.restore()
        sparkle = pulse(t, KNOT[1], 0.6)
        if sparkle > 0:
            A.glint(ctx, mx, my, 60 * (1.2 - sparkle), 0.4, sparkle)


def mandap(ctx, t):
    ctx.set_source_surface(mandap_back(), 0, 0)
    ctx.paint()
    since = t - MANDAP_IN[0]
    push = 1 + 0.03 * span(t, MANDAP_IN[0], AUNTIE_IN[1])            # a slow push in
    ctx.save()
    ctx.translate(W / 2, 470)
    ctx.scale(push, push)
    ctx.translate(-W / 2, -470)
    shy = 0.5 + 0.5 * math.sin(since * 7) if 0.4 < since < 1.4 else pulse(t, KNOT[1], 0.5)
    remote(ctx, *REMOTE_AT, 0.88, t, led=shy)
    groom(ctx, *TV_AT, 0.62, t, sehra=False)
    ctx.move_to(TV_AT[0] + 92, TV_AT[1] - 30)                        # his scarf, hanging at his side
    ctx.curve_to(TV_AT[0] + 104, TV_AT[1] - 10, TV_AT[0] + 104, TV_AT[1] + 30, TV_AT[0] + 100, TV_AT[1] + 70)
    inked_stroke(ctx, (1.0, 0.85, 0.3), 10, (2, 2))
    gathbandhan(ctx, t)
    havan_kund(ctx, 650, 586, t, 0.62)
    ctx.restore()
    petals(ctx, t, 11, 26, MANDAP_IN[0])
    k = ease_out(span(t, *TITLE))                                    # the wedding video's title
    if k > 0:
        ctx.save()
        font(ctx, 'Z003', 66, bold=False)
        for dx, dy, colour in ((3, 3, (*INK, 0.8 * k)), (0, 0, (*GOLD, k))):
            centred(ctx, 'TV weds Remote', W / 2 + dx, 196 + 10 * (1 - k) + dy)
            ctx.set_source_rgba(*colour)
            ctx.fill()
        label(ctx, 'A VIZELVISION WEDDING FILM', W / 2, 228, 14, mix(IVORY, MAROON, 1 - k), tracking=5)
        ctx.restore()
    c = ease_out(span(t, *CAPTION))                                  # the lower third
    if c > 0:
        x = 70 - 900 * (1 - c)
        ctx.save()
        rounded_rect(ctx, x, 618, 760, 74, 10)
        inked(ctx, MAROON, 4, (5, 5))
        ctx.rectangle(x + 6, 624, 10, 62)
        ctx.set_source_rgb(*GOLD)
        ctx.fill()
        label(ctx, 'GATHBANDHAN', x + 34, 646, 15, GOLD, tracking=5, align='left')
        label(ctx, 'THE REMOTE WILL NEVER BE LOST AGAIN', x + 34, 677, 26, WHITE, tracking=1, align='left')
        ctx.restore()


# ---------------------------------------------------------------- 3. the auntie

AUNTIE = {'skin': SKINS[2], 'sari': (0.93, 0.2, 0.55), 'blouse': (0.98, 0.74, 0.18)}
COUSINS = (
    {'skin': SKINS[1], 'kurta': (0.98, 0.78, 0.2), 'pants': IVORY, 'head': {'hair': 'kid'}},
    {'skin': SKINS[0], 'kurta': (0.2, 0.7, 0.62), 'pants': (0.2, 0.7, 0.62), 'head': {'hair': 'braid', 'bindi': True}},
)


@lru_cache(maxsize=None)
def reception_back():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    back = cairo.LinearGradient(0, 0, 0, H)
    back.add_color_stop_rgb(0, 0.35, 0.1, 0.3)
    back.add_color_stop_rgb(0.6, 0.6, 0.25, 0.32)
    back.add_color_stop_rgb(1, 0.4, 0.2, 0.22)
    ctx.set_source(back)
    ctx.paint()
    rand = random.Random(5)
    for k in range(55):                                              # the hall's lights, out of focus
        x, y, r = rand.uniform(0, W), rand.uniform(0, 420), rand.uniform(18, 46)
        g = cairo.RadialGradient(x, y, 0, x, y, r)
        colour = rand.choice((FAIRY, (1.0, 0.6, 0.75), (1.0, 0.9, 0.7)))
        g.add_color_stop_rgba(0, *colour, 0.35)
        g.add_color_stop_rgba(0.8, *colour, 0.25)
        g.add_color_stop_rgba(1, *colour, 0)
        ctx.set_source(g)
        ctx.arc(x, y, r, 0, TAU)
        ctx.fill()
    for k in range(5):                                               # round tables, soft
        x = 80 + k * 290
        ellipse(ctx, x, 520, 130, 34)
        ctx.set_source_rgba(1, 0.97, 0.94, 0.55)
        ctx.fill()
        ctx.rectangle(x - 130, 520, 260, 90)
        ctx.set_source_rgba(1, 0.97, 0.94, 0.4)
        ctx.fill()
    ctx.rectangle(0, 600, W, H - 600)
    ctx.set_source_rgb(0.3, 0.14, 0.16)
    ctx.fill()
    return surface


def placard(ctx, x, y, s):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.rotate(-0.06)
    ctx.move_to(0, 0)
    ctx.line_to(0, 120)
    ctx.set_source_rgb(*mix(COPPER, INK, 0.3))
    ctx.set_line_width(7)
    ctx.stroke()
    rounded_rect(ctx, -110, -84, 220, 92, 8)
    inked(ctx, IVORY, 4, (4, 4))
    label(ctx, 'SHOE RANSOM', 0, -50, 22, SINDOOR, tracking=1.5)
    font(ctx, 'FreeSans', 34)
    ctx.set_source_rgb(*INK)
    centred(ctx, '₹19,000', 0, -10)
    ctx.fill()
    ctx.restore()


def cousins(ctx, t):
    run = span(t, *RANSOM)
    if run <= 0 or run >= 1:
        return
    x = 700 + 760 * run
    for k, who in enumerate(COUSINS):
        cx = x - k * 150
        stride = (t * 6 + k) % 2
        arms = ((-10, -112), (30, -60)) if k == 0 else ((-20, -118), (24, -118))
        dancer(ctx, cx, 590, 0.6, t, who, arms, step=stride, lean=0.18)
        if k == 0:
            placard(ctx, cx - 0.6 * 20, 590 - 0.6 * 380, 0.6)
        else:                                                        # the shoes, held high
            jutti(ctx, cx - 18, 590 - 0.6 * 345, 1.4, GOLD, facing=-1)
            jutti(ctx, cx + 62, 590 - 0.6 * 350, 1.4, GOLD)


def bangles(ctx, x, y, r, count=6):
    for k in range(count):
        ellipse(ctx, x, y + k * 6 - count * 3, r, r * 0.28)
        ctx.set_source_rgb(*(GOLD, SINDOOR, (0.2, 0.6, 0.3), GOLD)[k % 4])
        ctx.set_line_width(4.5)
        ctx.stroke()


def laddoos(ctx, x, y):
    ellipse(ctx, x, y + 6, 116, 30)                                  # the thali
    inked(ctx, (0.85, 0.85, 0.88), 4, (4, 4))
    ellipse(ctx, x, y + 2, 92, 20)
    ctx.set_source_rgb(0.75, 0.75, 0.8)
    ctx.fill()
    for k, (dx, dy) in enumerate(((-54, -10), (-18, -14), (18, -14), (54, -10), (-36, -36), (0, -40), (36, -36),
                                  (-18, -62), (18, -62))):
        circle(ctx, x + dx, y + dy, 21)
        shade = cairo.RadialGradient(x + dx - 6, y + dy - 7, 2, x + dx, y + dy, 22)
        shade.add_color_stop_rgb(0, 1.0, 0.78, 0.3)
        shade.add_color_stop_rgb(1, 0.9, 0.52, 0.1)
        inked(ctx, shade, 2.5, (1, 1))
        for j in range(4):
            circle(ctx, x + dx + 8 * math.cos(j * 1.7 + k), y + dy + 7 * math.sin(j * 2.3 + k), 1.6)
        ctx.set_source_rgba(1, 0.95, 0.75, 0.9)
        ctx.fill()


def auntie(ctx, t):
    """Waist up, leaning into the lens: a pink sari with a gold border, the pallu over her
    shoulder, bangles, jhumkas, a bindi, a bun with a gajra; a plate of laddoos."""
    since = t - AUNTIE_IN[0]
    lean = ease_in_out(span(t, AUNTIE_IN[0], AUNTIE_LINE + 0.5))
    s = 1.0 + 0.08 * span(t, AUNTIE_IN[0], FINALE_IN[1])
    x, y = 440 - 30 * lean, 520 - 10 * lean
    who = AUNTIE
    mouth = talking(t, AUNTIE_LINE, 1.1)
    wink = 1.0 if WINK <= t < WINK + 0.35 else 0.0
    brow = ease_out(span(t, AUNTIE_LINE + 0.5, AUNTIE_LINE + 0.8))
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.rotate(-0.05 * lean + 0.012 * math.sin(since * 3))
    ctx.move_to(-190, 260)                                           # the sari's drape, below
    ctx.curve_to(-200, 40, -150, -40, 0, -48)
    ctx.curve_to(150, -40, 200, 40, 190, 260)
    ctx.close_path()
    inked(ctx, who['sari'], 5, (6, 6))
    ctx.move_to(-176, 10)                                            # the blouse: shoulders and neckline
    ctx.curve_to(-150, -36, -60, -48, 0, -48)
    ctx.curve_to(60, -48, 150, -36, 176, 10)
    ctx.curve_to(120, 30, 60, 40, 0, 40)
    ctx.curve_to(-60, 40, -120, 30, -176, 10)
    ctx.close_path()
    inked(ctx, who['blouse'], 4, (0, 0))
    for k in range(3):                                               # the pleats, falling
        ctx.move_to(-110 + k * 26, 140)
        ctx.curve_to(-112 + k * 26, 190, -116 + k * 26, 230, -120 + k * 26, 262)
    ctx.set_source_rgba(*mix(who['sari'], INK, 0.4), 0.7)
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.move_to(120, -36)                                            # the pallu, over the left shoulder
    ctx.curve_to(60, 40, -40, 120, -120, 260)
    ctx.line_to(-30, 260)
    ctx.curve_to(30, 150, 110, 60, 172, -6)
    ctx.close_path()
    inked(ctx, mix(who['sari'], MAROON, 0.15), 5, (5, 5))
    for off in (0, 1):                                               # its gold borders
        ctx.move_to(120 + off * 50, -36 + off * 30)
        ctx.curve_to(60 + off * 70, 40 + off * 20, -40 + off * 90, 120 + off * 20, -120 + off * 90, 260)
        ctx.set_source_rgb(*GOLD)
        ctx.set_line_width(11)
        ctx.stroke()
    rand = random.Random(4)
    for k in range(14):                                              # and its butis
        u = rand.random()
        circle(ctx, 140 - 230 * u + rand.uniform(-20, 20), -10 + 260 * u + rand.uniform(-10, 10), 4)
    ctx.set_source_rgb(*GOLD)
    ctx.fill()
    # Her left hand, palm up in a knowing little gesture; her right carries the laddoos.
    gesture = 6 * math.sin(since * 5) * (1 if mouth > 0 else 0.3)
    limb(ctx, (-170, 30), (-232, 150), (-168, 92 + gesture), who['skin'], 34)
    limb(ctx, (-168, 22), (-188, 56), (-196, 70), who['blouse'], 40)
    bangles(ctx, -205, 130, 22)
    ellipse(ctx, -160, 86 + gesture, 30, 22)
    inked(ctx, who['skin'], 3, (2, 2))
    limb(ctx, (170, 30), (232, 140), (128, 160), who['skin'], 34)
    limb(ctx, (168, 22), (188, 56), (196, 70), who['blouse'], 40)
    bangles(ctx, 204, 132, 22)
    laddoos(ctx, 60, 150)
    circle(ctx, 124, 160, 22)
    inked(ctx, who['skin'], 3, (2, 2))
    ctx.move_to(-30, -60)                                            # the neck, and a necklace
    ctx.line_to(30, -60)
    ctx.line_to(26, -20)
    ctx.curve_to(10, -10, -10, -10, -26, -20)
    ctx.close_path()
    inked(ctx, who['skin'], 3, (0, 0))
    ctx.arc(0, -44, 40, 0.3, math.pi - 0.3)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(6)
    ctx.stroke()
    head(ctx, 0, -150, 100, who['skin'], hair='bun', hair_colour=(0.16, 0.1, 0.1), mouth=mouth, bindi=True,
         brow=brow, wink=wink, look=0.3, sindoor=True)
    for sx in (-1, 1):                                               # the jhumkas
        hx, hy = sx * 98, -126
        ctx.move_to(hx, hy)
        ctx.line_to(hx, hy + 16)
        ctx.set_source_rgb(*GOLD_DARK)
        ctx.set_line_width(2)
        ctx.stroke()
        ctx.move_to(hx - 13, hy + 34)
        ctx.curve_to(hx - 12, hy + 14, hx + 12, hy + 14, hx + 13, hy + 34)
        ctx.close_path()
        inked(ctx, GOLD, 2.5, (2, 2))
        for k in range(4):
            circle(ctx, hx - 9 + k * 6, hy + 38, 2.6)
        ctx.set_source_rgb(*GOLD)
        ctx.fill()
    ctx.restore()


def reception(ctx, t):
    ctx.set_source_surface(reception_back(), 0, 0)
    ctx.paint()
    cousins(ctx, t)
    ctx.rectangle(0, 0, W, H)                                        # the cousins, out of focus behind her
    ctx.set_source_rgba(0.55, 0.25, 0.35, 0.22)
    ctx.fill()
    auntie(ctx, t)


# ---------------------------------------------------------------- 4. the send-off

@lru_cache(maxsize=None)
def palace_back():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    sky = cairo.LinearGradient(0, 0, 0, 480)
    sky.add_color_stop_rgb(0, 0.04, 0.04, 0.16)
    sky.add_color_stop_rgb(0.65, 0.2, 0.08, 0.3)
    sky.add_color_stop_rgb(1, 0.5, 0.18, 0.32)
    ctx.set_source(sky)
    ctx.paint()
    rand = random.Random(23)
    for _ in range(70):
        circle(ctx, rand.uniform(0, W), rand.uniform(0, 330), rand.uniform(0.5, 1.4))
        ctx.set_source_rgba(1, 0.96, 0.9, rand.uniform(0.3, 0.85))
        ctx.fill()
    ctx.rectangle(0, 470, W, H - 470)                                # the lawn
    lawn = cairo.LinearGradient(0, 470, 0, H)
    lawn.add_color_stop_rgb(0, 0.1, 0.16, 0.14)
    lawn.add_color_stop_rgb(1, 0.04, 0.07, 0.08)
    ctx.set_source(lawn)
    ctx.fill()
    return surface


def palace_outline():
    """The palace's shapes, a lake palace in the Rajasthani way (path builders), for its
    face and its fairy-light edges: bastions, two storeys, and chhatris on the roof."""
    def box(x, y, w, h):
        def build(ctx):
            ctx.rectangle(x, y, w, h)
        return build

    def dome(cx, base, w, h):
        def build(ctx):
            ctx.move_to(cx - w, base)
            ctx.curve_to(cx - w, base - h * 0.7, cx - w * 0.35, base - h * 0.9, cx, base - h)
            ctx.curve_to(cx + w * 0.35, base - h * 0.9, cx + w, base - h * 0.7, cx + w, base)
            ctx.close_path()
        return build

    def eave(cx, y, w):
        def build(ctx):
            ctx.move_to(cx - w - 10, y + 8)
            ctx.line_to(cx - w + 4, y - 4)
            ctx.line_to(cx + w - 4, y - 4)
            ctx.line_to(cx + w + 10, y + 8)
            ctx.close_path()
        return build

    shapes = [box(266, 250, 66, 222), box(948, 250, 66, 222), box(300, 330, 680, 142), box(372, 252, 536, 80)]
    for cx, base, w, h in ((299, 222, 30, 40), (981, 222, 30, 40), (400, 222, 26, 36), (880, 222, 26, 36),
                           (640, 196, 60, 64)):
        shapes += [box(cx - w + 4, base, 2 * w - 8, (250 if cx in (299, 981) else 252) - base),
                   eave(cx, base, w), dome(cx, base - 4, w, h)]
    shapes.append(box(552, 196, 176, 56))
    return tuple((build, IVORY) for build in shapes)


FINIALS = ((299, 178), (981, 178), (400, 182), (880, 182), (640, 128))


@lru_cache(maxsize=None)
def palace_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    for build, fill in palace_outline():
        build(ctx)
        face = cairo.LinearGradient(0, 110, 0, 472)
        face.add_color_stop_rgb(0, 0.98, 0.93, 0.86)
        face.add_color_stop_rgb(1, 0.98, 0.62, 0.5)
        inked(ctx, face, 3.5, (0, 0))

    def arch(ax, top, w, bottom):
        ctx.move_to(ax, bottom)
        ctx.line_to(ax, top + w * 0.6)
        ctx.curve_to(ax, top + w * 0.12, ax + w * 0.36, top, ax + w / 2, top - w * 0.2)
        ctx.curve_to(ax + w * 0.64, top, ax + w, top + w * 0.12, ax + w, top + w * 0.6)
        ctx.line_to(ax + w, bottom)
        ctx.close_path()
        inside = cairo.LinearGradient(0, top, 0, bottom)
        inside.add_color_stop_rgb(0, 1.0, 0.86, 0.5)
        inside.add_color_stop_rgb(1, 1.0, 0.55, 0.22)
        inked(ctx, inside, 3, (0, 0))

    for k in range(9):                                               # the arcade, lit gold within
        arch(615 + (k - 4) * 72, 366 if k != 4 else 352, 50, 472)
    for k in range(7):                                               # the jharokhas upstairs
        x = 640 + (k - 3) * 72
        arch(x - 15, 278, 30, 318)
        ctx.move_to(x - 26, 274)
        ctx.line_to(x, 262)
        ctx.line_to(x + 26, 274)
        ctx.close_path()
        inked(ctx, IVORY, 2.5, (0, 0))
        ctx.rectangle(x - 22, 318, 44, 8)
        inked(ctx, IVORY, 2.5, (0, 0))
    for x in (299, 981):                                             # the bastions' windows
        for y in (300, 380):
            arch(x - 12, y, 24, y + 40)
    ctx.set_source_rgb(*GOLD)
    for cx, top in FINIALS:
        ctx.move_to(cx, top + 14)
        ctx.line_to(cx, top - 8)
        ctx.set_line_width(4)
        ctx.stroke()
        circle(ctx, cx, top - 10, 5)
        ctx.fill()
    return surface


@lru_cache(maxsize=None)
def palace_lights():
    """Points along the palace's edges, for its fairy lights."""
    points = []
    scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4))
    for build, _ in palace_outline():
        scratch.new_path()
        build(scratch)
        flat = scratch.copy_path_flat()
        last = start = None
        carry = 0.0
        for kind, pts in flat:
            if kind == cairo.PATH_MOVE_TO:
                last = start = pts
                continue
            if kind == cairo.PATH_CLOSE_PATH:
                pts = start
            seg = math.hypot(pts[0] - last[0], pts[1] - last[1])
            d = carry
            while d < seg:
                u = d / seg
                points.append((last[0] + (pts[0] - last[0]) * u, last[1] + (pts[1] - last[1]) * u))
                d += 18
            carry = d - seg
            last = pts
    return tuple(points)


def diya(ctx, x, y, t, k):
    ctx.move_to(x - 16, y)
    ctx.curve_to(x - 12, y + 12, x + 12, y + 12, x + 16, y)
    ctx.close_path()
    inked(ctx, COPPER, 2, (1, 1))
    flick = 1 + 0.15 * math.sin(t * 19 + k * 2.1)
    ctx.move_to(x - 4, y - 1)
    ctx.curve_to(x - 4, y - 8 * flick, x, y - 14 * flick, x + 1, y - 18 * flick)
    ctx.curve_to(x + 2, y - 12 * flick, x + 5, y - 8, x + 4, y - 1)
    ctx.close_path()
    ctx.set_source_rgb(1.0, 0.82, 0.35)
    ctx.fill()
    glow(ctx, x, y - 8, 28, (1.0, 0.6, 0.25), 0.5)


def toran(ctx, t):
    """Marigolds swagged across the top of the frame, strands and mango leaves hanging."""
    for k in range(6):
        x0 = -30 + k * 230
        garland(ctx, x0, 6, x0 + 230, 6, 70, 10, roses=False)
    for k in range(14):
        x = 20 + k * 95
        sway = 4 * math.sin(t * 1.8 + k)
        ctx.save()
        ctx.translate(x + sway * 0.5, 36)
        ctx.rotate(0.05 * math.sin(t * 1.8 + k))
        ctx.move_to(0, 0)
        ctx.curve_to(-12, 18, -10, 40, 0, 54)
        ctx.curve_to(10, 40, 12, 18, 0, 0)
        ctx.close_path()
        inked(ctx, LEAF, 2, (1, 1))
        ctx.restore()
        if k % 2:
            strand(ctx, x + 47, 30, 92, 6.5, sway)


def send_off(ctx, t):
    ctx.set_source_surface(palace_back(), 0, 0)
    ctx.paint()
    for k, at in enumerate(FIREWORKS):                               # four fireworks on the closed logo
        big = k == 3
        firework(ctx, t, at, (360, 930, 520, 760)[k], (150, 130, 90, 120)[k], 190 if big else 140,
                 BURST if big else (BURST[k], mix(BURST[k], WHITE, 0.5)), 48 if big else 32, seed=10 + k)
    for k, at in enumerate(AFTER):
        firework(ctx, t, at, (1080, 200)[k], (200, 230)[k], 100, (BURST[k + 3], WHITE), 26, seed=20 + k)
    ctx.set_source_surface(palace_surface(), 0, 0)
    ctx.paint()
    rand = random.Random(29)
    for x, y in palace_lights():                                     # its fairy lights, twinkling
        tw = 0.7 + 0.3 * math.sin(t * rand.uniform(3, 7) + rand.uniform(0, TAU))
        glow(ctx, x, y, 10, FAIRY, 0.45 * tw)
        circle(ctx, x, y, 2.2)
        ctx.set_source_rgb(1, 0.95, 0.8)
        ctx.fill()
    groom(ctx, 626, 446, 0.13, t, garland_=False, sehra=False)    # the couple, under the arch
    remote(ctx, 656, 448, 0.13, t, garland_=False)
    for k in range(13):                                              # diyas along the lawn
        diya(ctx, 40 + k * 100, 700, t, k)
    petals(ctx, t, 31, 20, FINALE_IN[0])
    toran(ctx, t)
    neighborhood.lockup(ctx, t, CLOSED, 555, scale=0.62)
    k = ease_out(span(t, *DEVANAGARI))
    if k > 0:
        rise = 12 * (1 - k)
        ctx.save()
        for dx, dy, colour in ((3, 3, (*INK, 0.9 * k)), (0, 0, (1.0, 1.0, 1.0, k))):
            devanagari(ctx, 46)
            centred(ctx, 'शादी मुबारक', W / 2 + dx, 622 + rise + dy)
            ctx.set_source_rgba(*colour)
            ctx.fill()
            font(ctx, 'Nimbus Sans', 22)
            text_path(ctx, 'CHANNEL 19', W / 2 + dx, 664 + rise + dy, tracking=8, align='center')
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
    if t < MANDAP_IN[1]:
        baraat(ctx, t)
    if t < AUNTIE_IN[1]:
        scene(ctx, t, mandap, ease_in_out(span(t, *MANDAP_IN)))
    if t < FINALE_IN[1]:
        scene(ctx, t, reception, ease_in_out(span(t, *AUNTIE_IN)))
    scene(ctx, t, send_off, ease_in_out(span(t, *FINALE_IN)))
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
