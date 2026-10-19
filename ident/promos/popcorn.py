"""Popcorn: a microwave in a dark kitchen at night, close up through its glowing window.
A bag of popcorn turns on the plate while the display counts down to zero. The first
four kernels pop on the notes of the open logo, the bag puffing a little at each; then
the popping runs away, the bag swells and swells and the microwave shudders on the
counter. At 0:00, on the closed logo, the microwave beeps it: BEEP BEEP BEEP BEEEP. The
door bangs open, the bag bursts, and the popcorn flies out across the screen and lands
spelling VIZELVISION. Janus, from the next room: "Popcorn's ready!"
"""
import math
import random
from functools import lru_cache

import cairo

import beats
from common import (CYAN, INK, ORANGE, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, clamp, ease_in,  # noqa: F401
                    ease_in_out, ease_out, font, glint, grain, inked, mix, pixel_text, pulse, rounded_rect, span,
                    vignette)

ID = 'popcorn'
NAME = 'Popcorn'
KIND = 'ident'
ORDER = 27
DESCRIPTION = ('A microwave at night: the first kernels pop on the notes of the logo, the bag swells, and at 0:00 '
               'it beeps the closed logo; the door flies open and the popcorn lands spelling VIZELVISION. '
               '"Popcorn\'s ready!" Janus.')
DURATION = 10.0
STILL_AT = 8.9
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
FADE_IN = (0.0, 0.35)
POPS = beats.POPCORN_FIRST                      # the open logo: the first four kernels
FRENZY = beats.POPCORN_FRENZY                   # then it runs away
SWELL = (2.6, 6.8)                              # and the bag swells
DONE = 7.0                                      # 0:00: the closed logo, beeped
BEEPS = (7.0, 7.25, 7.5, 8.0)
DOOR = 8.05                                     # on the last beep, the door bangs open
BURST = 8.1                                     # the bag bursts
LAND = (8.1, 8.75)                              # the popcorn flies out and lands as the wordmark
FADE = (9.35, 9.65)
SECONDS = 7                                     # on the display at the start (0:07, to 0:00 at DONE)
WORD_SIZE, WORD_BASE = 178, 470                 # the wordmark the popcorn lands as

OVEN = (150, 110, 980, 520)                     # x, y, w, h
WINDOW = (200, 160, 640, 420)
PANEL = (880, 160, 210, 420)
PLATE = (520, 520)                              # the turntable's centre (seen a little from above)
COUNTER = 630
STEEL = (0.82, 0.83, 0.85)
GLOW = (1.0, 0.82, 0.45)
BAG = (0.97, 0.94, 0.86)
KERNEL = (1.0, 0.97, 0.86)


# ---------------------------------------------------------------- the kernels

POP_TIMES = beats.popcorn_pops()                 # every pop (the music's too)


def swell(t):
    """How full the bag is (0 flat, 1 bursting)."""
    pops = sum(1 for p in POPS if p <= t) * 0.03
    return min(1.0, pops + 0.88 * ease_in_out(span(t, *SWELL)))


@lru_cache(maxsize=None)
def word_spots():
    """Where each piece of popcorn lands: points filling the wordmark's letters."""
    surface = cairo.ImageSurface(cairo.FORMAT_A8, W, H)
    ctx = cairo.Context(surface)
    word_path(ctx)
    ctx.fill()
    surface.flush()
    data, stride = surface.get_data(), surface.get_stride()
    rand = random.Random(19)
    spots = []
    for y in range(WORD_BASE - 170, WORD_BASE + 10, 11):
        for x in range(30, W - 30, 11):
            jx, jy = x + rand.uniform(-3, 3), y + rand.uniform(-3, 3)
            if data[int(jy) * stride + int(jx)] > 128:
                spots.append((jx, jy))
    rand.shuffle(spots)
    return tuple(spots)


def word_path(ctx):
    font(ctx, 'URW Gothic', WORD_SIZE)
    ext = ctx.text_extents('VIZELVISION')
    ctx.move_to((W - ext.x_advance) / 2, WORD_BASE)
    ctx.text_path('VIZELVISION')


def butter(ctx, t):
    """Behind the popcorn as it lands: the kitchen dims, and the letters glow butter-gold."""
    p = ease_in_out(span(t, BURST + 0.1, LAND[1]))
    if p <= 0:
        return
    ctx.set_source_rgba(0.02, 0.01, 0.04, 0.55 * p)
    ctx.paint()
    ctx.save()
    word_path(ctx)
    path = ctx.copy_path()
    ctx.new_path()
    for width, alpha in ((26, 0.18), (14, 0.3)):
        ctx.append_path(path)
        ctx.set_source_rgba(1.0, 0.78, 0.25, alpha * p)
        ctx.set_line_width(width)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.stroke()
    ctx.append_path(path)
    ctx.set_source_rgba(1.0, 0.82, 0.3, 0.75 * p)
    ctx.fill()
    ctx.restore()


def kernel(ctx, x, y, r, spin, colour=KERNEL):
    """A popped kernel: a lumpy white cloud with a golden heart."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(spin)
    for k in range(5):
        a = k * TAU / 5
        ctx.new_sub_path()
        ctx.arc(math.cos(a) * r * 0.45, math.sin(a) * r * 0.45, r * 0.62, 0, TAU)
    ctx.set_source_rgb(*mix(colour, INK, 0.6))
    ctx.set_line_width(r * 0.28)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*colour)
    ctx.fill()
    ctx.arc(r * 0.15, r * 0.1, r * 0.25, 0, TAU)
    ctx.set_source_rgb(0.95, 0.72, 0.25)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the kitchen and the oven

@lru_cache(maxsize=None)
def kitchen():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, COUNTER)
    g.add_color_stop_rgb(0, 0.05, 0.06, 0.14)
    g.add_color_stop_rgb(1, 0.1, 0.1, 0.2)
    ctx.set_source(g)
    ctx.paint()
    ctx.set_source_rgba(1, 1, 1, 0.05)                   # the tiled splashback
    for y in range(0, COUNTER, 60):
        ctx.rectangle(0, y, W, 2)
    for x in range(0, W, 60):
        ctx.rectangle(x, 0, 2, COUNTER)
    ctx.fill()
    ctx.rectangle(0, COUNTER, W, H - COUNTER)            # the counter
    g = cairo.LinearGradient(0, COUNTER, 0, H)
    g.add_color_stop_rgb(0, 0.32, 0.22, 0.2)
    g.add_color_stop_rgb(1, 0.12, 0.08, 0.08)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(0, COUNTER, W, 8)
    ctx.set_source_rgb(0.5, 0.36, 0.3)
    ctx.fill()
    return surface


def oven_body(ctx, t, door_open):
    x, y, w, h = OVEN
    rounded_rect(ctx, x, y, w, h, 26)
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, *mix(STEEL, WHITE, 0.3))
    g.add_color_stop_rgb(0.5, *STEEL)
    g.add_color_stop_rgb(1, *mix(STEEL, INK, 0.25))
    inked(ctx, g, 6, (10, 10))
    for fx in (x + 40, x + w - 80):                       # feet
        rounded_rect(ctx, fx, y + h - 2, 40, 14, 4)
        ctx.set_source_rgb(*INK)
        ctx.fill()
    panel(ctx, t)
    wx, wy, ww, wh = WINDOW
    rounded_rect(ctx, wx - 6, wy - 6, ww + 12, wh + 12, 18)   # the cavity, lit while it runs
    lit = 0.0 if door_open else 1.0
    g = cairo.RadialGradient(PLATE[0], PLATE[1] - 120, 40, PLATE[0], PLATE[1] - 80, 520)
    g.add_color_stop_rgb(0, *mix((0.15, 0.1, 0.08), GLOW, 0.95 * lit + 0.4 * (1 - lit)))
    g.add_color_stop_rgb(1, *mix((0.08, 0.05, 0.04), (0.55, 0.36, 0.14), lit))
    ctx.set_source(g)
    ctx.fill()


def panel(ctx, t):
    """The control panel: the display counting down, the keypad, the door button."""
    x, y, w, h = PANEL
    rounded_rect(ctx, x, y, w, h, 14)
    ctx.set_source_rgb(0.14, 0.15, 0.17)
    ctx.fill()
    rounded_rect(ctx, x + 18, y + 20, w - 36, 74, 8)
    ctx.set_source_rgb(0.02, 0.05, 0.03)
    ctx.fill()
    if t < DONE:
        left = max(0, math.ceil(SECONDS - t * SECONDS / DONE - 1e-9))
        text = f'0:{left:02d}'
    elif t < DOOR or math.sin((t - DOOR) * 9) > 0:
        text = 'END'
    else:
        text = 'ENJOY'
    on = t < DONE or any(b <= t < b + (0.18 if b != BEEPS[-1] else 0.5) for b in BEEPS) or t >= BEEPS[-1] + 0.5
    if on:
        cell = 7 if len(text) <= 4 else 5
        pixel_text(ctx, text, x + w / 2, y + 57 - 3.5 * cell, cell, (0.35, 1.0, 0.45), align='center',
                   shadow=(0, 0, (0.1, 0.4, 0.15)))
    for r in range(4):                                     # the keypad
        for c in range(3):
            rounded_rect(ctx, x + 30 + c * 52, y + 120 + r * 48, 42, 36, 6)
            ctx.set_source_rgb(0.32, 0.33, 0.36)
            ctx.fill()
            label = '123456789-0+'[r * 3 + c]
            pixel_text(ctx, label, x + 51 + c * 52, y + 131 + r * 48, 2, (0.85, 0.86, 0.9), align='center')
    pressed = 4 * pulse(t, DOOR - 0.05, 0.2)
    rounded_rect(ctx, x + 30, y + 330 + pressed, w - 60, 56, 10)    # the door button
    inked(ctx, PINK, 4, (0, 6 - pressed))
    font(ctx, 'Nimbus Sans', 20)
    ctx.move_to(x + w / 2 - ctx.text_extents('OPEN').x_advance / 2, y + 366 + pressed)
    ctx.text_path('OPEN')
    ctx.set_source_rgb(*WHITE)
    ctx.fill()


def turntable(ctx, t):
    x, y = PLATE
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(1, 0.24)
    ctx.arc(0, 0, 230, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(1, 1, 1, 0.3)
    ctx.fill()


def bag(ctx, t):
    """The bag on the turning plate: flat, then puffing, then a balloon; it turns (its
    printed side swinging round) and shivers more as it fills."""
    if t >= BURST:
        return
    full = swell(t)
    turn = math.sin(t * 1.4)                                 # the turntable: its face swings
    rand = random.Random(int(t * 60))
    shake = full * 3 * (rand.random() - 0.5) if FRENZY[0] < t < DONE else 0
    jolt = max((pulse(t, p, 0.1) for p in POPS), default=0)
    cx, base = PLATE[0] + 40 * turn + shake, PLATE[1] - 6
    w = 300 * (0.7 + 0.3 * abs(math.cos(t * 1.4))) * (1 + 0.25 * full)
    h = 70 + 250 * full + 10 * jolt
    ctx.save()
    ctx.translate(cx, base)
    ctx.move_to(-w / 2, 0)
    ctx.curve_to(-w / 2 - 10 * full, -h * 0.6, -w * 0.3, -h, 0, -h)
    ctx.curve_to(w * 0.3, -h, w / 2 + 10 * full, -h * 0.6, w / 2, 0)
    ctx.close_path()
    g = cairo.LinearGradient(-w / 2, 0, w / 2, 0)
    g.add_color_stop_rgb(0, *mix(BAG, INK, 0.15))
    g.add_color_stop_rgb(0.4, *BAG)
    g.add_color_stop_rgb(1, *mix(BAG, (0.8, 0.5, 0.2), 0.3))
    inked(ctx, g, 5, (0, 0))
    face = math.cos(t * 1.4)                                # the print, while it faces us
    if face > 0.2:
        ctx.save()
        ctx.scale(face, 1)
        rounded_rect(ctx, -w * 0.32, -h * 0.72, w * 0.64, h * 0.42, 10)
        ctx.set_source_rgb(0.86, 0.12, 0.14)
        ctx.fill()
        ctx.save()
        ctx.translate(0, -h * 0.51)
        k = min(1.4, 0.5 + h / 260)
        ctx.scale(k, k)
        font(ctx, 'URW Gothic', 26)
        for i, (word, dy) in enumerate((('POP', -6), ('CORN', 20))):
            ctx.move_to(-ctx.text_extents(word).x_advance / 2, dy)
            ctx.text_path(word)
        ctx.set_source_rgb(*YELLOW)
        ctx.fill()
        ctx.restore()
        ctx.restore()
    ctx.restore()


def inside_pops(ctx, t):
    """The pops seen through the window: a flash of white kernel at each, jumping inside the bag."""
    rand = random.Random(3)
    for at in POP_TIMES:
        x, y = PLATE[0] + rand.uniform(-110, 110), PLATE[1] - rand.uniform(40, 180) * (0.4 + swell(at))
        p = span(t, at, at + 0.12)
        if 0 < p < 1:
            ctx.arc(x, y - 30 * p, 10 + 30 * (1 - p), 0, TAU)
            ctx.set_source_rgba(1, 1, 0.9, 0.5 * (1 - p))
            ctx.fill()


def window_glass(ctx, t):
    wx, wy, ww, wh = WINDOW
    ctx.save()
    rounded_rect(ctx, wx, wy, ww, wh, 14)
    ctx.clip()
    ctx.set_source_rgba(0, 0, 0, 0.32)                       # the mesh
    for x in range(wx, wx + ww, 8):
        for y in range(wy + (x // 8 % 2) * 4, wy + wh, 8):
            ctx.rectangle(x, y, 3, 3)
    ctx.fill()
    ctx.move_to(wx, wy + 120)
    ctx.line_to(wx, wy)
    ctx.line_to(wx + 260, wy)
    ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.12)
    ctx.fill()
    ctx.restore()
    rounded_rect(ctx, wx, wy, ww, wh, 14)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(8)
    ctx.stroke()


def door(ctx, t):
    """The door: shut over the window, or swung open on its left hinge (seen edge-on, narrowing)."""
    x, y, w, h = OVEN
    swing = ease_out(span(t, DOOR, DOOR + 0.25), 2)
    bounce = 0.06 * math.sin((t - DOOR - 0.25) * 18) * math.exp(-(t - DOOR - 0.25) * 6) if t > DOOR + 0.25 else 0
    width = PANEL[0] - 14 - (x + 22)
    if swing <= 0:
        rounded_rect(ctx, x + 22, y + 22, width, h - 44, 18)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(5)
        ctx.stroke()
        rounded_rect(ctx, x + width - 34, y + 190, 22, 140, 8)       # the handle
        inked(ctx, mix(STEEL, WHITE, 0.4), 4, (4, 4))
        return
    k = math.cos(math.pi / 2 * min(1.0, swing + bounce))      # how much of its face we still see
    width *= max(k, 0.0)
    hinge = x + 22
    ctx.move_to(hinge, y + 22)
    ctx.line_to(hinge - width * 0.35, y - 10)
    ctx.line_to(hinge - width * 0.35, y + h + 10)
    ctx.line_to(hinge, y + h - 22)
    ctx.close_path()
    inked(ctx, mix(STEEL, INK, 0.2), 5, (6, 6))
    ctx.rectangle(hinge - 18, y + 20, 18, h - 40)             # its edge
    inked(ctx, mix(STEEL, WHITE, 0.2), 4, (0, 0))


# ---------------------------------------------------------------- the burst and the word

def flying(ctx, t):
    """The popcorn: out of the burst bag, through the open door, across the screen, each
    piece to its place in the wordmark."""
    if t < BURST:
        return
    spots = word_spots()
    rand = random.Random(11)
    origin = (PLATE[0], PLATE[1] - 160)
    for i, (sx, sy) in enumerate(spots):
        delay = rand.uniform(0, 0.25)
        flight = rand.uniform(0.35, 0.5)
        p = span(t, BURST + delay, BURST + delay + flight)
        if p <= 0:
            continue
        lift = rand.uniform(120, 320)
        x = origin[0] + rand.uniform(-60, 60) + (sx - origin[0]) * ease_out(p, 2)
        y = origin[1] + rand.uniform(-40, 40) + (sy - origin[1]) * p - lift * math.sin(math.pi * p)
        settle = back_out(span(t, BURST + delay + flight, BURST + delay + flight + 0.25), 3)
        r = (6.5 + rand.uniform(0, 2.5)) * (0.85 + 0.15 * settle if p >= 1 else 1.2)
        kernel(ctx, x, y, r, rand.uniform(0, TAU) + t * (4 if p < 1 else 0))


def burst_puff(ctx, t):
    p = span(t, BURST, BURST + 0.4)
    if not 0 < p < 1:
        return
    x, y = PLATE[0], PLATE[1] - 160
    rand = random.Random(8)
    k = ease_out(p)
    for i in range(14):
        a = rand.uniform(0, TAU)
        d = rand.uniform(30, 150) * k
        ctx.new_sub_path()
        ctx.arc(x + math.cos(a) * d, y + math.sin(a) * d * 0.7, rand.uniform(50, 90) * k, 0, TAU)
    ctx.set_source_rgba(1, 0.98, 0.9, 0.75 * (1 - p))
    ctx.fill()


def steam(ctx, t):
    """Wisps from the open door."""
    if t < DOOR:
        return
    for k in range(4):
        p = span(t, DOOR + 0.2 + k * 0.25, DOOR + 1.3 + k * 0.25)
        if not 0 < p < 1:
            continue
        x = OVEN[0] + 160 + k * 150
        ctx.move_to(x, OVEN[1] + 80 - 160 * p)
        ctx.curve_to(x - 30, OVEN[1] + 40 - 160 * p, x + 30, OVEN[1] - 160 * p, x, OVEN[1] - 40 - 160 * p)
        ctx.set_source_rgba(1, 1, 1, 0.25 * math.sin(math.pi * p))
        ctx.set_line_width(10)
        ctx.stroke()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.set_source_surface(kitchen(), 0, 0)
    ctx.paint()
    rand = random.Random(frame)
    shudder = 0.0
    if FRENZY[0] < t < DONE:
        shudder = 2.5 * math.sin(math.pi * span(t, *FRENZY)) * (rand.random() - 0.5)
    ctx.save()
    ctx.translate(shudder, 0)
    door_open = t >= DOOR
    oven_body(ctx, t, door_open)
    wx, wy, ww, wh = WINDOW
    ctx.save()
    rounded_rect(ctx, wx, wy, ww, wh, 14)
    ctx.clip()
    turntable(ctx, t)
    bag(ctx, t)
    inside_pops(ctx, t)
    ctx.restore()
    if not door_open:
        window_glass(ctx, t)
    door(ctx, t)
    ctx.restore()
    steam(ctx, t)
    butter(ctx, t)
    burst_puff(ctx, t)
    flying(ctx, t)
    vignette(ctx, 0.5)
    grain(ctx, frame, 0.35)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
