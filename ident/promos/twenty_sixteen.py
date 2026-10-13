"""VizelVision '16: the station in 2016, flat and streaming. A purple-to-orange gradient,
drifting. A flat white phone rises with a long shadow. On the open logo: a notification
drops onto its lock screen (VIZELVISION · now · LIVE), a thumb taps it, the app opens
out of it in a circle, and the stream is live. Hearts float up its right side and
comments rise in bubbles; beside it the wordmark stacks in in flat rounded letters with
long shadows, and a NOW STREAMING pill. On the closed logo #VizelVision pops in a letter
a sixteenth and the hearts burst out across the frame.

Thalia: "Vizzle Vision." / "Stream it live. Anywhere."
"""
import math
import random
from functools import lru_cache

import cairo

from common import (A, TAU, W, H, back_out, clamp, ease_in, ease_in_out, ease_out, grain, mix, pulse,  # noqa: F401
                    rounded_rect, span, text_path)

ID = 'twenty-sixteen'
NAME = "VizelVision '16"
KIND = 'ident'
ORDER = 15
DESCRIPTION = ("2016: a flat white phone on a purple-to-orange gradient; a LIVE notification, a tap and the stream "
               'on the logo; floating hearts and comments, flat long-shadow type, #VizelVision. Tropical house '
               'marimba and vocal chops. Thalia.')
DURATION = 10.0
STILL_AT = 8.4
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
PHONE_UP = (0.1, 0.7)
NOTIFY = 1.0                                   # the open logo: the notification drops,
TAP = 1.25                                     # a thumb taps it,
OPEN_APP = 1.5                                 # the app opens out of it,
LIVE = 2.0                                     # and the stream is live: the drop
WORD = (2.5, 2.875)                            # the wordmark stacks in ("Vizzle Vision." at 2.6)
PILL = 4.4                                     # NOW STREAMING ("Stream it live. Anywhere." at 4.5)
HASHTAG = 7.0                                  # the closed logo: #VizelVision, a letter a sixteenth
BURST = 7.0
FADE = (9.25, 9.6)

PHONE = (800, 60, 300, 600)                    # x, y, w, h (resting)
SCREEN_INSET = (16, 64, 16, 76)                # left, top, right, bottom
WHITE = (1, 1, 1)
LIVE_RED = (0.95, 0.15, 0.25)
TEAL_ = (0.0, 0.78, 0.72)
PINKISH = (1.0, 0.3, 0.55)


# ---------------------------------------------------------------- the background

def background(ctx, t):
    a = 0.6 + 0.15 * math.sin(t * 0.5)
    g = cairo.LinearGradient(0, 0, W * math.cos(a), H + W * math.sin(a) * 0.3)
    g.add_color_stop_rgb(0, 0.33, 0.2, 0.75)
    g.add_color_stop_rgb(0.4, 0.8, 0.2, 0.6)
    g.add_color_stop_rgb(0.75, 1.0, 0.45, 0.35)
    g.add_color_stop_rgb(1, 1.0, 0.78, 0.3)
    ctx.set_source(g)
    ctx.paint()
    for k, (x, y, r) in enumerate(((180, 120, 140), (1150, 620, 200), (640, 690, 90))):   # soft flat circles
        ctx.arc(x + 20 * math.sin(t * 0.4 + k), y + 14 * math.cos(t * 0.5 + k), r, 0, TAU)
        ctx.set_source_rgba(1, 1, 1, 0.07)
        ctx.fill()


def long_shadow(ctx, path, length=60, alpha=0.18):
    """Flat design's long shadow, at 45 degrees down to the right."""
    ctx.push_group()
    for k in range(0, length, 2):
        ctx.save()
        ctx.translate(k, k)
        ctx.new_path()
        ctx.append_path(path)
        ctx.set_source_rgb(0.15, 0.0, 0.25)
        ctx.fill()
        ctx.restore()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(alpha)


# ---------------------------------------------------------------- the phone

def phone_rect(t):
    x, y, w, h = PHONE
    rise = back_out(span(t, *PHONE_UP), 1.4)
    return x, y + (H + 40 - y) * (1 - rise), w, h


def screen_rect(t):
    x, y, w, h = phone_rect(t)
    left, top, right, bottom = SCREEN_INSET
    return x + left, y + top, w - left - right, h - top - bottom


def app_icon(ctx, x, y, size):
    rounded_rect(ctx, x, y, size, size, size * 0.22)
    g = cairo.LinearGradient(x, y, x + size, y + size)
    g.add_color_stop_rgb(0, *TEAL_)
    g.add_color_stop_rgb(1, *PINKISH)
    ctx.set_source(g)
    ctx.fill()
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size * 0.72)
    ctx.new_path()
    text_path(ctx, 'V', x + size / 2, y + size * 0.76, align='center')
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()


def lock_screen(ctx, t, x, y, w, h):
    g = cairo.LinearGradient(x, y, x + w, y + h)
    g.add_color_stop_rgb(0, 0.25, 0.3, 0.6)
    g.add_color_stop_rgb(1, 0.6, 0.35, 0.65)
    ctx.set_source(g)
    ctx.rectangle(x, y, w, h)
    ctx.fill()
    ctx.select_font_face('Quicksand Light', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(66)
    ctx.new_path()
    text_path(ctx, '7:19', x + w / 2, y + 100, align='center')
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    ctx.select_font_face('Quicksand Medium', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(15)
    ctx.new_path()
    text_path(ctx, 'Friday, October 7', x + w / 2, y + 128, align='center')
    ctx.fill()
    p = span(t, NOTIFY, NOTIFY + 0.3)
    if p <= 0:
        return
    ny = y + 150 - 140 * (1 - back_out(p, 1.6))
    pressed = 1 - 0.04 * pulse(t, TAP, 0.2)
    ctx.save()
    ctx.translate(x + w / 2, ny + 40)
    ctx.scale(pressed, pressed)
    ctx.translate(-(x + w / 2), -(ny + 40))
    rounded_rect(ctx, x + 10, ny, w - 20, 82, 14)
    ctx.set_source_rgba(1, 1, 1, 0.92)
    ctx.fill()
    app_icon(ctx, x + 20, ny + 10, 26)
    ctx.select_font_face('Quicksand Medium', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(12)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', x + 54, ny + 28, tracking=1.5)
    ctx.set_source_rgb(0.4, 0.4, 0.45)
    ctx.fill()
    ctx.new_path()
    text_path(ctx, 'now', x + w - 22, ny + 28, align='right')
    ctx.fill()
    ctx.arc(x + 27, ny + 59, 5, 0, TAU)
    ctx.set_source_rgb(*LIVE_RED)
    ctx.fill()
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(15)
    ctx.new_path()
    text_path(ctx, "LIVE: you're missing it", x + 40, ny + 64)
    ctx.set_source_rgb(0.1, 0.1, 0.15)
    ctx.fill()
    ctx.restore()
    q = span(t, TAP, TAP + 0.35)                         # the tap: a ripple where the thumb lands
    if 0 < q < 1:
        ctx.arc(x + w * 0.6, ny + 46, 10 + 50 * ease_out(q), 0, TAU)
        ctx.set_source_rgba(1, 1, 1, 0.6 * (1 - q))
        ctx.fill()


@lru_cache(maxsize=None)
def heart_plan():
    rand = random.Random(16)
    return [(rand.uniform(LIVE, 9.2), rand.uniform(-1, 1), rand.uniform(0.7, 1.2),
             rand.choice(((1, 0.3, 0.45), (1, 0.6, 0.2), (0.4, 0.7, 1), (0.6, 0.9, 0.4), (0.9, 0.4, 1))))
            for _ in range(46)]


def heart(ctx, x, y, s, colour, alpha):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.move_to(0, 9)
    ctx.curve_to(-14, -2, -6, -13, 0, -5)
    ctx.curve_to(6, -13, 14, -2, 0, 9)
    ctx.set_source_rgba(*colour, alpha)
    ctx.fill()
    ctx.restore()


COMMENTS = (('@q_street', 'this is everything'), ('@dupontdan', 'who else is watching rn'), ('@meridian', 'iconic'),
            ('@mvp19', 'VizelVision >>>'), ('@cairo_fan', 'same'), ('@nightowl', 'obsessed'))


def live_stream(ctx, t, x, y, w, h):
    """The stream: the station's world (sunburst and the TV emblem), LIVE, viewers, comments."""
    ctx.set_source_rgb(0.45, 0.1, 0.5)
    ctx.rectangle(x, y, w, h)
    ctx.fill()
    cx, cy = x + w / 2, y + h * 0.42
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(t * 0.3)
    for i in range(16):
        a = i * TAU / 16
        ctx.move_to(0, 0)
        ctx.arc(0, 0, h, a, a + TAU / 32)
        ctx.close_path()
    ctx.set_source_rgba(1, 0.8, 0.2, 0.3)
    ctx.fill()
    ctx.restore()
    ctx.save()
    ctx.translate(cx, cy + 20)
    ctx.scale(0.62, 0.62)
    A.draw_tv(ctx, t, 1, 0.0)
    ctx.restore()
    rounded_rect(ctx, x + 12, y + 14, 58, 24, 6)
    ctx.set_source_rgb(*LIVE_RED)
    ctx.fill()
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(14)
    ctx.new_path()
    text_path(ctx, 'LIVE', x + 41, y + 31, tracking=1, align='center')
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    rounded_rect(ctx, x + 76, y + 14, 74, 24, 6)
    ctx.set_source_rgba(0, 0, 0, 0.35)
    ctx.fill()
    viewers = 19.1 + 0.1 * int((t - LIVE) * 3)
    ctx.new_path()
    text_path(ctx, f'{viewers:.1f}K', x + 113, y + 31, align='center')
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    for k, (name, text) in enumerate(COMMENTS):          # comments rising up the left
        start = LIVE + 0.4 + k * 0.9
        p = span(t, start, start + 3.2)
        if not 0 < p < 1:
            continue
        by = y + h - 70 - 220 * p
        alpha = min(1.0, p * 6) * (1 - span(p, 0.75, 1.0))
        ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(12)
        width = max(ctx.text_extents(name).x_advance, ctx.text_extents(text).x_advance * 1.1) + 22
        rounded_rect(ctx, x + 10, by, width, 40, 12)
        ctx.set_source_rgba(0, 0, 0, 0.35 * alpha)
        ctx.fill()
        ctx.new_path()
        text_path(ctx, name, x + 21, by + 16)
        ctx.set_source_rgba(1, 0.85, 0.4, alpha)
        ctx.fill()
        ctx.select_font_face('Quicksand Medium', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(13)
        ctx.new_path()
        text_path(ctx, text, x + 21, by + 32)
        ctx.set_source_rgba(1, 1, 1, alpha)
        ctx.fill()
    for when, drift, size, colour in heart_plan():     # hearts floating up the right
        p = span(t, when, when + 2.2)
        if not 0 < p < 1:
            continue
        hx = x + w - 34 + 16 * math.sin(p * 6 + drift * 3) * p
        hy = y + h - 40 - (h - 120) * ease_out(p, 1.6)
        heart(ctx, hx, hy, size * (0.6 + 0.4 * min(1.0, p * 5)), colour, 1 - p ** 2)
    rounded_rect(ctx, x + 10, y + h - 42, w - 64, 30, 15)
    ctx.set_source_rgba(1, 1, 1, 0.25)
    ctx.fill()
    ctx.select_font_face('Quicksand Medium', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(13)
    ctx.new_path()
    text_path(ctx, 'Say something...', x + 24, y + h - 22)
    ctx.set_source_rgba(1, 1, 1, 0.8)
    ctx.fill()
    heart(ctx, x + w - 30, y + h - 27, 1.1, (1, 0.3, 0.45), 1)


def phone(ctx, t):
    x, y, w, h = phone_rect(t)
    if y >= H:
        return
    rounded_rect(ctx, x, y, w, h, 44)
    long_shadow(ctx, ctx.copy_path(), 80, 0.16)
    rounded_rect(ctx, x, y, w, h, 44)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    rounded_rect(ctx, x + w / 2 - 34, y + 30, 68, 8, 4)  # the speaker; the home button
    ctx.set_source_rgb(0.85, 0.85, 0.88)
    ctx.fill()
    ctx.arc(x + w / 2, y + h - 38, 22, 0, TAU)
    ctx.set_source_rgb(0.85, 0.85, 0.88)
    ctx.set_line_width(3)
    ctx.stroke()
    sx, sy, sw, sh = screen_rect(t)
    ctx.save()
    ctx.rectangle(sx, sy, sw, sh)
    ctx.clip()
    lock_screen(ctx, t, sx, sy, sw, sh)
    p = span(t, OPEN_APP, LIVE)
    if p > 0:                                            # the app opens out of the notification in a circle
        ctx.save()
        ctx.arc(sx + sw * 0.6, sy + 196, 10 + 560 * ease_in_out(p), 0, TAU)
        ctx.clip()
        live_stream(ctx, t, sx, sy, sw, sh)
        ctx.restore()
    ctx.restore()


# ---------------------------------------------------------------- the type

def flat_word(ctx, t, text, x, y, size, start, colour=WHITE):
    p = span(t, start, start + 0.35)
    if p <= 0:
        return
    ctx.save()
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    ctx.translate(0, 40 * (1 - back_out(p, 1.8)))
    ctx.new_path()
    text_path(ctx, text, x, y)
    path = ctx.copy_path()
    ctx.push_group()
    long_shadow(ctx, path, 70, 0.22)
    ctx.new_path()
    ctx.append_path(path)
    ctx.set_source_rgb(*colour)
    ctx.fill()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(min(1.0, p * 3))
    ctx.restore()


def words(ctx, t):
    flat_word(ctx, t, 'Vizel', 110, 260, 150, WORD[0])
    flat_word(ctx, t, 'Vision', 110, 410, 150, WORD[1])
    p = span(t, PILL, PILL + 0.3)
    if p > 0:
        ctx.save()
        ctx.translate(118, 456)
        k = back_out(p, 2.0)
        ctx.scale(k, k)
        rounded_rect(ctx, 0, 0, 300, 52, 26)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        ctx.arc(30, 26, 8, 0, TAU)
        ctx.set_source_rgb(*LIVE_RED)
        ctx.fill()
        ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(22)
        ctx.new_path()
        text_path(ctx, 'NOW STREAMING', 50, 34, tracking=2)
        ctx.set_source_rgb(0.45, 0.15, 0.55)
        ctx.fill()
        ctx.restore()
    tag = '#VizelVision'
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(64)
    x = 118
    for i, ch in enumerate(tag):
        q = span(t, HASHTAG + i * 0.0625 * 0.75, HASHTAG + i * 0.0625 * 0.75 + 0.25)
        advance = ctx.text_extents(ch).x_advance
        if q > 0:
            ctx.save()
            ctx.translate(x + advance / 2, 600)
            k = back_out(q, 2.4)
            ctx.scale(k, k)
            ctx.new_path()
            ctx.move_to(-advance / 2, 0)
            ctx.text_path(ch)
            ctx.set_source_rgb(*((1, 0.9, 0.35) if ch == '#' else WHITE))
            ctx.fill()
            ctx.restore()
        x += advance


def burst(ctx, t):
    """On the closed logo the hearts spill out of the phone across the frame."""
    p = span(t, BURST, BURST + 2.2)
    if not 0 < p < 1:
        return
    rand = random.Random(2016)
    x0, y0, w, h = phone_rect(t)
    for k in range(34):
        angle = rand.uniform(-math.pi, 0.2)
        speed = rand.uniform(250, 700)
        delay = rand.uniform(0, 0.3)
        q = clamp((p * 2.2 - delay) / 2.0)
        if q <= 0:
            continue
        x = x0 + w * 0.8 + math.cos(angle) * speed * q
        y = y0 + h * 0.75 + math.sin(angle) * speed * q + 300 * q * q
        colour = ((1, 0.3, 0.45), (1, 0.6, 0.2), (0.4, 0.7, 1), (0.6, 0.9, 0.4), (0.9, 0.4, 1))[k % 5]
        heart(ctx, x, y, rand.uniform(1.0, 2.2), colour, 1 - q ** 2)


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    background(ctx, t)
    words(ctx, t)
    phone(ctx, t)
    burst(ctx, t)
    grain(ctx, frame, 0.15)
    opening = 1 - ease_out(span(t, 0.0, 0.3))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
