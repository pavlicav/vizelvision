"""Halftime: the VizelVision marching band, seen from the blimp. The lit field at night,
the stands round it twinkling with camera flashes. The PA: "Ladies and gentlemen... the
Vizzle Vision marching band!" The band marches in from the end zone in a block, pink
jackets and white plumes, and hits the four notes of the open logo, brass flashing. Then
it peels off, rank by rank, left to right behind the drum major, and writes VizelVision
across the field. The three i's have no dots. On the closed logo three sousaphone players
high-step out from the sideline and dot them, one a note, and on the last all three bow.

The bug in the corner carries the game on air (master's live text). Aired only during an
NFL or college game (LEAGUES). The PA is Jupiter, with the stadium's echo.
"""
import math
import random
from functools import lru_cache

import cairo

from common import (INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    font, glint, grain, inked, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'halftime'
NAME = 'Halftime'
KIND = 'ident'
ORDER = 24
DESCRIPTION = ('Only during football: the VizelVision marching band from the blimp. It hits the logo, writes '
               'VizelVision across the field, and on the closed logo three sousaphones high-step out to dot its '
               "i's. The bug carries the game on air. Jupiter on the PA.")
DURATION = 10.0
STILL_AT = 8.7
LEAGUES = ('nfl', 'ncaaf')

# Hit points (the music's too: promos/music.py).
FADE_IN = (0.0, 0.5)
MARCH_IN = (0.2, 0.95)                           # the block, in from the end zone
HITS = (1.0, 1.25, 1.5, 2.0)                     # the open logo: the band hits each note
WRITE = (2.6, 6.2)                               # peeling off, left to right, into the word
STEP_TIME = 1.1                                  # each member's walk to its spot
DOTS = (7.0, 7.25, 7.5)                          # the closed logo: an i dotted a note
BOW = 8.0                                        # and on the last, all three bow
FADE = (9.3, 9.6)

PX = 11.0                                        # pixels a yard
SIDELINE = (67, 653)                             # the top and bottom sidelines
WORD = 'VizelVision'
WORD_SIZE, WORD_BASE = 210, 452
GRID = 10                                        # the band's spacing in the word, in pixels
BLOCK_TOP, BLOCK_RANKS = 496, 9                  # the block formation: its front rank, and how many
JACKET = PINK
PLUME = WHITE
BRASS = (1.0, 0.8, 0.3)
TURF = ((0.16, 0.42, 0.18), (0.13, 0.37, 0.15))

OVERLAYS = [
    {'field': 'programme', 'box': [212, 18, 420, 40], 'from': 0.6, 'to': FADE[0] + 0.1,
     'style': {'font': 'Nimbus Sans', 'bold': True, 'size': 26, 'min_size': 13, 'color': [1.0, 1.0, 1.0],
               'upper': True, 'tracking': 0.04},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': 0.3}},
]


def yard_x(yard):
    """Screen x of a yard line (0 the left end line, 60 midfield, 120 the right end line)."""
    return W / 2 + (yard - 60) * PX


# ---------------------------------------------------------------- the formation

@lru_cache(maxsize=None)
def layout():
    """The spots in the word (left to right), and the i's dots (their centres), which the
    band leaves empty."""
    surface = cairo.ImageSurface(cairo.FORMAT_A8, W, H)
    ctx = cairo.Context(surface)
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(WORD_SIZE)
    x = (W - ctx.text_extents(WORD).x_advance) / 2
    dots = []
    for ch in WORD:
        ctx.move_to(x, WORD_BASE)
        ctx.text_path(ch)
        if ch == 'i':
            sub = ctx.copy_path()
            ctx.new_path()
            pieces, current = [], []
            for kind, pts in sub:
                if kind == cairo.PATH_MOVE_TO and current:
                    pieces.append(current)
                    current = []
                if pts:
                    current.append(pts)
            pieces.append(current)
            top = min((p for p in pieces if p), key=lambda p: min(q[1] for q in p))
            dots.append((sum(q[0] for q in top) / len(top), sum(q[1] for q in top) / len(top)))
            for piece in pieces:                      # the stem only; the dot stays empty
                if piece and piece is not top:
                    ctx.move_to(*piece[0])
                    for q in piece[1:]:
                        ctx.line_to(*q)
                    ctx.close_path()
        ctx.fill()
        x += ctx.text_extents(ch).x_advance
    surface.flush()
    data, stride = surface.get_data(), surface.get_stride()
    spots = []
    for gx in range(0, W, GRID):
        for gy in range(SIDELINE[0] + 20, SIDELINE[1] - 20, GRID):
            if data[gy * stride + gx] > 140:
                spots.append((gx, gy))
    return tuple(spots), tuple(dots)


@lru_cache(maxsize=None)
def members():
    """Each member: (block spot, word spot, when they set off). The block is as wide as the
    word, so each file steps up into the letters above it; the word is written left to
    right."""
    spots, _ = layout()
    ranks = BLOCK_RANKS
    files = math.ceil(len(spots) / ranks)
    lo, hi = min(s[0] for s in spots), max(s[0] for s in spots)
    block = sorted((lo + (hi - lo) * f / (files - 1), BLOCK_TOP + r * 14) for f in range(files) for r in range(ranks))
    out = []
    for home, spot in zip(block, sorted(spots)):
        start = WRITE[0] + (WRITE[1] - WRITE[0] - STEP_TIME) * (spot[0] - lo) / (hi - lo)
        out.append((home, spot, start))
    return tuple(out)


def block_offset(t):
    """The block marching on from the near sideline: how far it still has to come (px)."""
    return 300 * (1 - ease_out(span(t, *MARCH_IN), 2))


def member_place(t, home, spot, start):
    """(x, y, moving) of a member at t."""
    off = block_offset(t)
    if t < start:
        return home[0], home[1] + off, t < MARCH_IN[1]
    p = span(t, start, start + STEP_TIME)
    q = ease_in_out(p)
    x = home[0] + (spot[0] - home[0]) * q
    y = home[1] + (spot[1] - home[1]) * q
    return x, y, p < 1


def figure(ctx, x, y, t, moving, hit, colour=JACKET, plume=PLUME, scale=1.0):
    """A bandsman from above: shoulders in the jacket, the shako, its plume, and a glint of
    brass in front; stepping (a bob) while moving."""
    step = math.sin(t * TAU * 2 + x * 0.05) * 1.2 if moving else 0.0
    ctx.save()
    ctx.translate(x, y + step)
    ctx.scale(scale, scale)
    ctx.save()
    ctx.translate(2.5, 3)
    ctx.scale(5.5, 3.6)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, 0.35)                     # its shadow from the lights
    ctx.fill()
    ctx.save()
    ctx.scale(5.4, 3.4)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*colour)
    ctx.fill()
    ctx.arc(0, -0.5, 2.6, 0, TAU)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.arc(-0.6, -1.4, 1.5, 0, TAU)
    ctx.set_source_rgb(*plume)
    ctx.fill()
    ctx.rectangle(-1.5, 3.2, 3, 2.4 + 2 * hit)              # the horn's bell, out in front
    ctx.set_source_rgb(*mix(BRASS, WHITE, hit))
    ctx.fill()
    ctx.restore()


def band(ctx, t):
    hit = max((pulse(t, h, 0.25) for h in HITS), default=0.0)
    for home, spot, start in members():
        x, y, moving = member_place(t, home, spot, start)
        figure(ctx, x, y, t, moving, hit if t < WRITE[0] else 0.0)
    if hit > 0.3 and t < WRITE[0]:                           # the brass flashing on the hits
        rand = random.Random(int(t * 30))
        for home, _, _ in rand.sample(members(), 14):
            glint(ctx, home[0], home[1] + block_offset(t) + 4, 9 * hit, rand.random() * 3, 0.8)


def drum_major(ctx, t):
    """Out in front of the block, then leading the line as the word is written."""
    spots, _ = layout()
    lo, hi = min(s[0] for s in spots), max(s[0] for s in spots)
    if t < WRITE[0]:
        x, y = W / 2, BLOCK_TOP - 26 + block_offset(t)
    else:
        p = span(t, WRITE[0], WRITE[1])
        lead = ease_in_out(span(t, WRITE[0] - 0.3, WRITE[0] + 0.3))
        x = W / 2 + (lo - 30 + (hi - lo + 60) * p - W / 2) * lead
        y = BLOCK_TOP - 26 - 18 * lead + 6 * math.sin(t * 6)
        if t > WRITE[1] + 0.2:
            q = ease_in_out(span(t, WRITE[1] + 0.2, WRITE[1] + 1.0))
            x, y = x + (W / 2 - x) * q, y + (SIDELINE[1] - 30 - y) * q
    twirl = t * 9
    ctx.save()
    ctx.translate(x, y)
    ctx.move_to(math.cos(twirl) * -12, math.sin(twirl) * -12)       # the mace, twirling
    ctx.line_to(math.cos(twirl) * 12, math.sin(twirl) * 12)
    ctx.set_source_rgb(*BRASS)
    ctx.set_line_width(2.5)
    ctx.stroke()
    ctx.restore()
    figure(ctx, x, y, t, True, 0.0, colour=WHITE, plume=YELLOW, scale=1.35)


def dotters(ctx, t):
    """The three sousaphones: up from the sideline in high steps, onto the dots, a note
    each; on the last note, all three bow."""
    _, dots = layout()
    for k, ((dx, dy), arrive) in enumerate(zip(dots, DOTS)):
        start = arrive - 0.9
        if t < start - 0.4:
            continue
        sy = SIDELINE[1] - 4
        p = ease_out(span(t, start, arrive), 1.6)
        x = dx + (1 - p) * (20 - 20 * k)
        y = sy + (dy - sy) * p
        high = abs(math.sin((t - start) * TAU * 2.2)) * 3 if p < 1 else 0.0
        bow = pulse(t, BOW, 0.5)
        ctx.save()
        ctx.translate(x, y - high)
        ctx.scale(1.3 - 0.25 * bow, 1.3 + 0.15 * bow)
        ctx.save()                                           # the shadow
        ctx.translate(3, 4)
        ctx.scale(15, 13)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(0, 0, 0, 0.35)
        ctx.fill()
        ctx.arc(0, 0, 11.5, 0, TAU)                         # the bell, gold, facing up at us
        g = cairo.RadialGradient(-3, -3, 1, 0, 0, 12)
        g.add_color_stop_rgb(0, 1, 0.97, 0.75)
        g.add_color_stop_rgb(0.6, *BRASS)
        g.add_color_stop_rgb(1, 0.6, 0.42, 0.1)
        ctx.set_source(g)
        ctx.fill()
        ctx.arc(0, 0, 7.5, 0, TAU)
        ctx.set_source_rgb(0.45, 0.3, 0.06)
        ctx.fill()
        ctx.arc(-6, 8, 3, 0, TAU)                           # the plume, peeking out
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
        ctx.restore()
        landed = span(t, arrive, arrive + 0.5)
        if 0 < landed < 1:                                  # a ring and a glint as it lands
            ctx.arc(dx, dy, 14 + 50 * ease_out(landed), 0, TAU)
            ctx.set_source_rgba(1, 1, 0.8, 0.8 * (1 - landed))
            ctx.set_line_width(3)
            ctx.stroke()
            glint(ctx, dx + 10, dy - 12, 16 * math.sin(math.pi * landed), landed * 2, 1)


# ---------------------------------------------------------------- the stadium

@lru_cache(maxsize=None)
def stadium():
    """The field (stripes, lines, numbers, end zones) and the stands, drawn once."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    rand = random.Random(9)
    ctx.set_source_rgb(0.06, 0.06, 0.1)
    ctx.paint()
    for y0, y1 in ((0, SIDELINE[0] - 18), (SIDELINE[1] + 18, H)):   # the stands: a crowd of dots
        for _ in range(int(W * (y1 - y0) / 30)):
            x, y = rand.uniform(0, W), rand.uniform(y0, y1)
            colour = rand.choice(((0.85, 0.2, 0.45), (0.9, 0.9, 0.95), (0.2, 0.6, 0.75), (0.95, 0.75, 0.3),
                                  (0.35, 0.3, 0.45), (0.5, 0.4, 0.35)))
            ctx.arc(x, y, rand.uniform(1.6, 3.2), 0, TAU)
            ctx.set_source_rgb(*mix(colour, (0.05, 0.05, 0.1), 0.35))
            ctx.fill()
    ctx.rectangle(0, SIDELINE[0] - 18, W, SIDELINE[1] - SIDELINE[0] + 36)   # the apron round the field
    ctx.set_source_rgb(*mix(TURF[1], INK, 0.25))
    ctx.fill()
    for k in range(24):                                       # mown stripes, five yards each
        x0 = yard_x(k * 5)
        ctx.rectangle(x0, SIDELINE[0], 5 * PX, SIDELINE[1] - SIDELINE[0])
        ctx.set_source_rgb(*TURF[k % 2])
        ctx.fill()
    for side, x0 in ((0, yard_x(0)), (1, yard_x(110))):       # the end zones
        ctx.rectangle(x0, SIDELINE[0], 10 * PX, SIDELINE[1] - SIDELINE[0])
        ctx.set_source_rgb(0.45, 0.06, 0.22)
        ctx.fill()
        ctx.save()
        ctx.translate(x0 + 5 * PX, (SIDELINE[0] + SIDELINE[1]) / 2)
        ctx.rotate(-TAU / 4 if side == 0 else TAU / 4)
        font(ctx, 'URW Gothic', 64)
        ctx.new_path()
        text_path(ctx, 'VIZELVISION', 0, 22, tracking=6, align='center')
        ctx.set_source_rgba(1, 1, 1, 0.85)
        ctx.fill()
        ctx.restore()
    ctx.set_source_rgba(1, 1, 1, 0.85)                        # the lines
    for k in range(0, 21):
        x = yard_x(10 + k * 5)
        ctx.rectangle(x - 1.5, SIDELINE[0], 3, SIDELINE[1] - SIDELINE[0])
    ctx.fill()
    for k in range(10, 111):                                  # hash marks
        x = yard_x(k)
        for y in (SIDELINE[0] + 4, (SIDELINE[0] + SIDELINE[1]) / 2 - 64, (SIDELINE[0] + SIDELINE[1]) / 2 + 58,
                  SIDELINE[1] - 10):
            ctx.rectangle(x - 1, y, 2, 6)
    ctx.fill()
    ctx.rectangle(yard_x(0), SIDELINE[0] - 4, 120 * PX, 4)
    ctx.rectangle(yard_x(0), SIDELINE[1], 120 * PX, 4)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 34)
    for k in range(1, 10):                                    # the numbers
        number = str(10 * min(k, 10 - k))
        x = yard_x(10 + k * 10)
        for y, flip in ((SIDELINE[0] + 70, True), (SIDELINE[1] - 46, False)):
            ctx.save()
            ctx.translate(x, y)
            if flip:
                ctx.rotate(math.pi)
            ctx.new_path()
            text_path(ctx, number, 0, 12, tracking=8, align='center')
            ctx.set_source_rgba(1, 1, 1, 0.8)
            ctx.fill()
            ctx.restore()
    return surface


def lights(ctx, t):
    """The stadium lights' wash, and camera flashes in the stands (more as the i's are dotted)."""
    g = cairo.RadialGradient(W / 2, H / 2, 200, W / 2, H / 2, 900)
    g.add_color_stop_rgba(0, 1, 1, 0.95, 0.06)
    g.add_color_stop_rgba(1, 0, 0, 0.05, 0.0)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(int(t * 20))
    count = 3 + int(14 * sum(pulse(t, d, 0.6) for d in DOTS + (BOW,)))
    for _ in range(count):
        x = rand.uniform(0, W)
        y = rand.choice((rand.uniform(0, SIDELINE[0] - 20), rand.uniform(SIDELINE[1] + 20, H)))
        glint(ctx, x, y, rand.uniform(4, 9), rand.random(), 0.9)


def bug(ctx, t):
    """The corner bug: HALFTIME, and the game (live text) beside it."""
    p = ease_out(span(t, 0.3, 0.7))
    if p <= 0:
        return
    out = 1 - ease_in_out(span(t, FADE[0] - 0.1, FADE[0] + 0.2))
    ctx.save()
    ctx.push_group()
    rounded_rect(ctx, 26, 14, 620, 48, 10)
    ctx.set_source_rgba(0.02, 0.03, 0.1, 0.82)
    ctx.fill()
    rounded_rect(ctx, 30, 18, 170, 40, 8)
    ctx.set_source_rgb(*YELLOW)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 26, italic=True)
    ctx.new_path()
    text_path(ctx, 'HALFTIME', 115, 47, tracking=1, align='center')
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(p * out)
    ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    zoom = 1.0 + 0.05 * ease_in_out(span(t, 0.0, DURATION))       # the blimp drifts lower
    ctx.save()
    ctx.translate(W / 2, H / 2)
    ctx.scale(zoom, zoom)
    ctx.translate(-W / 2, -H / 2)
    ctx.set_source_surface(stadium(), 0, 0)
    ctx.paint()
    band(ctx, t)
    drum_major(ctx, t)
    dotters(ctx, t)
    lights(ctx, t)
    ctx.restore()
    bug(ctx, t)
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.3)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
