"""You're Watching VizelVision: the station ID's jingle, remixed for hype. A build of
"you're, you're, you're" in the brand colours, the drop on "You're watching", the TV
emblem on a slowly turning sunburst over a checkerboard floor, the wordmark dropping
in on sixteenths for "VizelVision!", a crowd and the stadium horn, the lift to the
closed logo, and the iris.

The sound is all hype; the picture is steady (2026-10-06: "less graphically jumpy").
No camera shake, no strobing colour, nothing bouncing on the beat: things arrive with
the music, then hold still.
"""
import math

import cairo

from common import (A, CYAN, INK, LIME, ORANGE, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, chrome, clamp,  # noqa: F401
                    ease_in, ease_in_out, ease_out, elastic_out, flash, font, glint, grain, inked, inked_stroke, iris,
                    mix, pulse, rounded_rect, scanlines, span, text_path, vignette)

ID = 'watching'
NAME = "You're Watching VizelVision"
KIND = 'ident'
ORDER = 2
DESCRIPTION = ("The station ID's jingle remixed for hype: a stuttered build, the drop on \"You're watching\", "
               'the wordmark stomping in for "VizelVision!", the crowd, the stadium horn and the lift. DJ Low Tide.')
DURATION = 10.0
STILL_AT = 6.6
OVERLAYS = []

BEAT = 0.5
# Hit points (the music's too).
CHOPS = (0.0, 0.5, 1.0, 1.25, 1.5, 1.625, 1.75, 1.875)   # "you're" stutters in the build
DROP = 2.0
LETTERS, LETTER_STEP = 5.0, 0.125                    # "VizelVision!": a letter a sixteenth
LIFT = 7.0                                           # the key change: the closed logo
BUTTON = 9.0
IRIS = (9.15, 9.55)
COLOURS = (PINK, TEAL, YELLOW, CYAN, ORANGE, LIME)
NAVY, GOLDEN = (0.06, 0.03, 0.18), (0.12, 0.06, 0.02)


def shift(t):
    return ease_in_out(span(t, LIFT - 0.1, LIFT + 0.3))


def last_chop(t):
    hits = [c for c in CHOPS if c <= t]
    return (len(hits) - 1, hits[-1]) if hits else (None, None)


# ---------------------------------------------------------------- the build

def build(ctx, t):
    """Night, a glow that grows with the riser, and YOU'RE: each chop gives the word the
    next brand colour and a small pop; it grows steadily towards the drop."""
    ctx.set_source_rgb(*NAVY)
    ctx.paint()
    rise = ease_in(span(t, 0.0, DROP), 2)
    glow = cairo.RadialGradient(W / 2, H / 2 + 20, 0, W / 2, H / 2 + 20, 380 + 420 * rise)
    glow.add_color_stop_rgba(0, *mix(PINK, WHITE, 0.2), 0.1 + 0.3 * rise)
    glow.add_color_stop_rgba(1, *PINK, 0)
    ctx.set_source(glow)
    ctx.paint()
    index, at = last_chop(t)
    if index is None:
        return
    life = span(t, at, at + 0.2)
    colour = COLOURS[index % len(COLOURS)]
    ctx.save()
    ctx.translate(W / 2, H / 2 + 20)
    zoom = (0.92 + 0.16 * rise) * (1 + 0.04 * (1 - ease_out(life)))
    ctx.scale(zoom, zoom)
    font(ctx, 'URW Gothic', 230, italic=True)
    ext = ctx.text_extents("YOU'RE")
    ctx.move_to(-ext.width / 2 - ext.x_bearing, ext.height / 2)
    ctx.text_path("YOU'RE")
    inked(ctx, mix(colour, WHITE, 0.25), 7, (12, 12), fatten=6)
    ctx.restore()


# ---------------------------------------------------------------- after the drop

def sunburst(ctx, t):
    k = shift(t)
    ctx.set_source_rgb(*mix(NAVY, GOLDEN, k))
    ctx.paint()
    cx, cy = W / 2, 330
    a0 = 0.22 * (t - DROP)
    for i in range(20):
        a = a0 + i * TAU / 20
        ctx.move_to(cx, cy)
        ctx.line_to(cx + math.cos(a) * 1500, cy + math.sin(a) * 1500)
        ctx.line_to(cx + math.cos(a + TAU / 40) * 1500, cy + math.sin(a + TAU / 40) * 1500)
        ctx.close_path()
        ctx.set_source_rgb(*(mix(PINK, (0.95, 0.55, 0.1), k) if i % 2 else mix((0.35, 0.1, 0.6), (0.9, 0.3, 0.1), k)))
        ctx.fill()
    glow = cairo.RadialGradient(cx, cy, 0, cx, cy, 520)
    glow.add_color_stop_rgba(0, 1, 0.95, 0.8, 0.55)
    glow.add_color_stop_rgba(1, 1, 0.95, 0.8, 0)
    ctx.set_source(glow)
    ctx.paint()


def checker(ctx, t):
    """A checkerboard floor scrolling towards the viewer."""
    top = 545
    k = shift(t)
    ctx.save()
    ctx.rectangle(0, top, W, H - top)
    ctx.clip()
    ctx.set_source_rgb(*mix((0.08, 0.02, 0.14), (0.1, 0.05, 0.02), k))
    ctx.paint()
    scroll = (t * 0.5) % 1
    light = mix(CYAN, YELLOW, k)
    for row in range(10):
        z0, z1 = row + scroll, row + 1 + scroll
        y0, y1 = top + 160 / (8 - z0 * 0.7) if z0 < 11 else H, top + 160 / (8 - z1 * 0.7) if z1 < 11 else H
        y0, y1 = top + (z0 / 10) ** 1.8 * (H - top + 20), top + (z1 / 10) ** 1.8 * (H - top + 20)
        for col in range(-12, 13):
            if (col + row) % 2:
                continue
            spread = lambda y: (y - top + 40) / (H - top + 40)  # noqa: E731
            xa0, xa1 = W / 2 + col * 110 * spread(y0), W / 2 + (col + 1) * 110 * spread(y0)
            xb0, xb1 = W / 2 + col * 110 * spread(y1), W / 2 + (col + 1) * 110 * spread(y1)
            ctx.move_to(xa0, y0)
            ctx.line_to(xa1, y0)
            ctx.line_to(xb1, y1)
            ctx.line_to(xb0, y1)
            ctx.close_path()
    ctx.set_source_rgba(*light, 0.55)
    ctx.fill()
    ctx.restore()
    ctx.set_source_rgba(1, 1, 1, 0.7)
    ctx.rectangle(0, top - 2, W, 4)
    ctx.fill()


def headline(ctx, t):
    """YOU'RE WATCHING, settling in on the drop and holding; it eases away for the wordmark."""
    p = ease_out(span(t, DROP, DROP + 0.35))
    leave = ease_in_out(span(t, LETTERS - 0.4, LETTERS))
    if p <= 0 or leave >= 1:
        return
    zoom = 1.12 - 0.12 * p
    ctx.save()
    ctx.translate(W / 2, 118 - 60 * leave)
    ctx.scale(zoom, zoom)
    ctx.rotate(-0.05)
    ctx.push_group()
    font(ctx, 'URW Gothic', 112, italic=True)
    for text, y, colour in (("YOU'RE", -10, YELLOW), ('WATCHING', 100, WHITE)):
        ext = ctx.text_extents(text)
        ctx.move_to(-ext.width / 2 - ext.x_bearing, y)
        ctx.text_path(text)
        inked(ctx, colour, 6, (10, 10), fatten=5)
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(p * (1 - leave))
    ctx.restore()


def emblem(ctx, t):
    if t < DROP:
        return
    p = back_out(span(t, DROP, DROP + 0.6), 1.2)
    if p <= 0.01:
        return
    spin = TAU * ease_in_out(span(t, LIFT, LIFT + 1.2))
    y = 390 - 130 * ease_in_out(span(t, LETTERS - 0.3, LETTERS + 0.5)) + 6 * math.sin(TAU * (t - DROP) / 4)
    facing, side = math.cos(spin), math.sin(spin)
    ctx.save()
    ctx.translate(W / 2, y)
    ctx.rotate(math.sin(TAU * (t - DROP) / 5) * 0.025)
    scale = (0.9 + 0.15 * ease_in_out(span(t, LETTERS - 0.3, LETTERS + 0.5))) * p
    ctx.scale(scale * max(abs(facing), 0.05), scale)
    A.draw_tv(ctx, t, 1 if facing >= 0 else -1, side)
    ctx.restore()


def wordmark(ctx, t):
    """VIZELVISION dropping in a letter a sixteenth, the ID's faces, a small wave on the lift."""
    size, layout = A.wordmark_layout()
    font(ctx, 'URW Gothic', size)
    base = 640
    top = base - size * 0.74
    for i, letter in enumerate(layout):
        land = LETTERS + i * LETTER_STEP
        p = span(t, land - 0.2, land + 0.05)
        if p <= 0:
            continue
        zoom = 1 + 0.35 * (1 - ease_out(p))
        drop = -40 * (1 - ease_out(p))
        wave = math.sin(clamp((t - LIFT - i * 0.04) / 0.45) * math.pi) * 12 \
            + math.sin(clamp((t - BUTTON - i * 0.03) / 0.5) * math.pi) * 12 + drop
        cx = letter['x'] + letter['bearing'] + letter['w'] / 2
        cy = base - size * 0.37
        ctx.save()
        ctx.translate(cx, cy - wave)
        ctx.scale(zoom, zoom)
        ctx.move_to(-letter['w'] / 2 - letter['bearing'], base - cy)
        ctx.text_path(letter['ch'])
        if letter['part'] == 0:
            colour = COLOURS[i % 5]
            face = cairo.LinearGradient(0, top - cy, 0, base - cy)
            face.add_color_stop_rgb(0, *mix(colour, WHITE, 0.45))
            face.add_color_stop_rgb(0.5, *colour)
            face.add_color_stop_rgb(1, *mix(colour, INK, 0.25))
        else:
            face = chrome(top - cy, base - cy, shift(t))
        if p < 1:
            ctx.push_group()
        inked(ctx, face, 5, (8, 8), fatten=7)
        if p < 1:
            ctx.pop_group_to_source()
            ctx.paint_with_alpha(ease_out(clamp(p * 1.6)))
        ctx.restore()


def confetti(ctx, t):
    if t < DROP:
        return
    for i, (x, y, kind, colour, size, turn, spin, _) in enumerate(A.SHAPES):
        pop = span(t, DROP + 0.05 * i, DROP + 0.05 * i + 0.4)
        if pop <= 0:
            continue
        px = x + 10 * math.sin(0.6 * t + i)
        py = y + 8 * math.cos(0.7 * t + i)
        ctx.save()
        ctx.translate(px, py)
        ctx.rotate(turn + spin * 0.6 * t)
        s = back_out(pop, 1.4) * 0.9
        ctx.scale(s, s)
        A.shape_path(ctx, kind if kind != 'dots' else 'circle', size * (0.5 if kind == 'dots' else 1))
        if kind in ('squiggle', 'zigzag', 'triangle', 'ring'):
            inked_stroke(ctx, colour, 10)
        else:
            inked(ctx, colour)
        ctx.restore()


def glints(ctx, t):
    for k, at in enumerate((LIFT, BUTTON)):
        p = span(t, at, at + 1.2)
        if not 0 < p < 1:
            continue
        for i in range(14):
            a = i * TAU / 14 + 0.3 + k
            r = 120 + 460 * ease_out(p) * (0.75 + 0.25 * (i % 3))
            glint(ctx, W / 2 + math.cos(a) * r, 300 + math.sin(a) * r * 0.75, 26 * (1 - p) + 4, p * 4 + i, 1 - p)


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS[1]:
        return
    if t < DROP:
        build(ctx, t)
    else:
        sunburst(ctx, t)
        checker(ctx, t)
        confetti(ctx, t)
        emblem(ctx, t)
        headline(ctx, t)
        wordmark(ctx, t)
        glints(ctx, t)
    flash(ctx, max(0.35 * pulse(t, DROP, 0.6), 0.15 * pulse(t, LIFT, 0.6), 0.15 * pulse(t, BUTTON, 0.6)))
    scanlines(ctx, 0.1)
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.5)
    close = span(t, *IRIS)
    if close > 0:
        iris(ctx, W / 2, 260, 900 * (1 - ease_in(close, 2)))
