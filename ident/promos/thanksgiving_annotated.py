"""The First Thanksgiving (Annotated): a 1950s classroom filmstrip, projected on the pull-down
screen in a dark classroom, faded to pink, dust and all. THE FIRST THANKSGIVING, 1621: a long
table under an autumn tree, the Mayflower at anchor, and the caption every school read aloud:
"The Pilgrims and the Indians shared a feast of turkey and pumpkin pie."

On the open logo a red marker comes into the picture and annotates it, a footnote a note:
"the Indians" struck, the Wampanoag written over it; "turkey" circled: unconfirmed; "pumpkin
pie" struck: no ovens yet!; and, on the held note, under "shared a feast", a 3-day diplomatic
summit. Beep: the next frame is THE END. The marker strikes that too and writes STILL HERE.
under it: the Wampanoag Nation, Mashpee & Aquinnah. On the closed logo VIZELVISION drops in
under the screen: WE READ THE FOOTNOTES; and, small, in marker: (please still enjoy your
dinner).

Every footnote is the history: about ninety Wampanoag men came with Massasoit and stayed three
days, at the alliance's first harvest; Winslow's letter has deer and wildfowl, turkey perhaps;
Plymouth had no ovens that autumn. Nobody is drawn: the filmstrip's picture is the table and
the ship.

Zeus, the filmstrip: "The Pilgrims and the Indians shared a feast..." / "The end." Theia:
"Thanksgiving. Now with footnotes."
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (INK, TAU, W, H, WHITE, back_out, clamp, ease_in, ease_in_out, ease_out, font,  # noqa: F401
                    grain, inked, iris, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'thanksgiving-annotated'
NAME = 'The First Thanksgiving (Annotated)'
KIND = 'ident'
ORDER = 54
DESCRIPTION = ('A 1950s classroom filmstrip of the first Thanksgiving, corrected live by a red marker, a footnote '
               'on each note of the open logo: the Wampanoag, turkey unconfirmed, no ovens yet, a 3-day '
               'diplomatic summit. THE END is struck out: STILL HERE, the Wampanoag Nation. VIZELVISION: '
               'WE READ THE FOOTNOTES.')
DURATION = 10.0
STILL_AT = 9.0
OVERLAYS = []

# Hit points (the music's too: thanksgiving_annotated_music.py).
IRIS_OPEN = (0.0, 0.5)
MARKER_IN = (2.55, 2.95)                     # the marker comes into the picture
EDITS = (3.0, 3.25, 3.5, 4.0)                # the open logo: a footnote a note
WRITE = (0.2, 0.2, 0.2, 0.42)                # how long each takes to write
ADVANCE = 4.45                               # beep: the next frame
STRIKE_END = 5.3                             # THE END, struck out
STILL_HERE = (5.5, 6.05)
NATION = 6.2
LOGO = (7.2, 7.45, 7.7, 8.2)                 # the closed logo
DINNER = (8.35, 8.75)                        # (please still enjoy your dinner)
IRIS_CLOSE = (9.25, 9.6)

SCREEN = (190, 34, 900, 560)                 # the pull-down screen
FRAME = (250, 70, 780, 470)                  # the projected filmstrip frame
CAPTION_TOP = 318
LINE_1, LINE_2 = 392, 474
RED = (0.88, 0.08, 0.1)
FADED_INK = (0.28, 0.16, 0.2)


def faded(rgb, amount=0.45):
    """An old filmstrip's colour: the cyan gone, everything drifting to pink and cream."""
    r, g, b = rgb
    return mix((min(1.0, r * 1.05 + 0.08), g * 0.82 + 0.06, b * 0.78 + 0.1), (0.95, 0.78, 0.74), amount * 0.4)


# ---------------------------------------------------------------- the classroom

@lru_cache(maxsize=1)
def room_surface():
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(s)
    ctx.set_source_rgb(0.12, 0.13, 0.14)                       # the dark classroom wall
    ctx.paint()
    ctx.rectangle(60, 70, W - 120, 470)                        # the chalkboard, behind the screen
    inked(ctx, (0.14, 0.24, 0.2), 4, (0, 0))
    ctx.rectangle(60, 532, W - 120, 14)                        # its ledge, chalk and a brush
    ctx.set_source_rgb(0.3, 0.22, 0.15)
    ctx.fill()
    for x, w in ((120, 30), (150, 22), (1110, 60)):
        rounded_rect(ctx, x, 526, w, 8, 3)
        ctx.set_source_rgb(0.85, 0.85, 0.8) if w < 50 else ctx.set_source_rgb(0.4, 0.3, 0.2)
        ctx.fill()
    ctx.select_font_face('Z003', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)   # chalk peeking out
    ctx.set_font_size(44)
    ctx.move_to(86, 130)
    ctx.text_path('Nov.')
    ctx.set_source_rgba(0.85, 0.88, 0.85, 0.35)
    ctx.fill()
    x, y, w, h = SCREEN
    ctx.rectangle(x - 26, y - 22, w + 52, 26)                  # the roller case
    g = cairo.LinearGradient(0, y - 22, 0, y + 4)
    g.add_color_stop_rgb(0, 0.55, 0.56, 0.58)
    g.add_color_stop_rgb(1, 0.3, 0.31, 0.33)
    inked(ctx, g, 3, (0, 4))
    ctx.rectangle(x, y, w, h)                                  # the screen, beaded white
    g = cairo.RadialGradient(x + w / 2, y + h / 2, 50, x + w / 2, y + h / 2, w * 0.7)
    g.add_color_stop_rgb(0, 0.42, 0.42, 0.44)
    g.add_color_stop_rgb(1, 0.26, 0.26, 0.28)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(x - 6, y + h - 6, w + 12, 14)                # the bottom bar and its pull ring
    ctx.set_source_rgb(0.2, 0.2, 0.22)
    ctx.fill()
    ctx.arc(x + w / 2, y + h + 26, 12, 0, TAU)
    ctx.set_source_rgb(0.2, 0.2, 0.22)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.move_to(x + w / 2, y + h + 8)
    ctx.line_to(x + w / 2, y + h + 14)
    ctx.stroke()
    ctx.rectangle(0, 600, W, H - 600)                          # the front row's desks, in silhouette
    ctx.set_source_rgb(0.05, 0.05, 0.06)
    ctx.fill()
    for k in range(5):
        rounded_rect(ctx, 40 + k * 250, 586, 200, 40, 8)
        ctx.set_source_rgb(0.07, 0.07, 0.08)
        ctx.fill()
    return s


# ---------------------------------------------------------------- the filmstrip's frames

@lru_cache(maxsize=1)
def card_feast():
    x, y, w, h = FRAME
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(s)
    ctx.rectangle(x, y, w, CAPTION_TOP - y)                    # the picture: an autumn shore
    g = cairo.LinearGradient(0, y, 0, CAPTION_TOP)
    g.add_color_stop_rgb(0, *faded((0.45, 0.65, 0.9)))
    g.add_color_stop_rgb(0.6, *faded((0.95, 0.85, 0.6)))
    g.add_color_stop_rgb(1, *faded((0.95, 0.75, 0.45)))
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(x + 360, 196, w - 360, 40)                   # the bay, and the ship at anchor
    ctx.set_source_rgb(*faded((0.25, 0.45, 0.7)))
    ctx.fill()
    sx, sy = 880, 200
    ctx.move_to(sx - 70, sy)
    ctx.line_to(sx + 70, sy)
    ctx.line_to(sx + 56, sy + 22)
    ctx.line_to(sx - 60, sy + 22)
    ctx.close_path()
    ctx.set_source_rgb(*faded((0.35, 0.22, 0.14)))
    ctx.fill()
    for mx, top in ((sx - 34, 110), (sx + 8, 96), (sx + 46, 124)):
        ctx.move_to(mx, sy)
        ctx.line_to(mx, top)
        ctx.set_line_width(3)
        ctx.stroke()
        ctx.rectangle(mx - 20, top + 8, 40, (sy - top) * 0.55)
        ctx.set_source_rgb(*faded((0.95, 0.92, 0.82)))
        ctx.fill()
        ctx.set_source_rgb(*faded((0.35, 0.22, 0.14)))
    ctx.rectangle(x, 236, w, CAPTION_TOP - 236)                # the meadow
    ctx.set_source_rgb(*faded((0.55, 0.62, 0.3)))
    ctx.fill()
    ctx.move_to(330, 300)                                      # an oak in its fall colours
    ctx.line_to(340, 150)
    ctx.line_to(356, 150)
    ctx.line_to(366, 300)
    ctx.close_path()
    ctx.set_source_rgb(*faded((0.35, 0.22, 0.14)))
    ctx.fill()
    rand = random.Random(16)
    for _ in range(26):
        ctx.arc(348 + rand.uniform(-90, 90), 130 + rand.uniform(-45, 35), rand.uniform(22, 36), 0, TAU)
        ctx.set_source_rgb(*faded(rand.choice(((0.9, 0.45, 0.1), (0.8, 0.25, 0.1), (0.95, 0.7, 0.2)))))
        ctx.fill()
    ctx.move_to(450, 262)                                      # the long table, laid
    ctx.line_to(800, 262)
    ctx.line_to(820, 290)
    ctx.line_to(430, 290)
    ctx.close_path()
    ctx.set_source_rgb(*faded((0.97, 0.93, 0.82)))
    ctx.fill()
    for k in range(9):
        cx = 470 + k * 40
        ctx.arc(cx, 262, 9 + 3 * (k % 3), math.pi, 0)
        ctx.set_source_rgb(*faded(((0.95, 0.55, 0.12), (0.85, 0.75, 0.3), (0.6, 0.3, 0.12))[k % 3]))
        ctx.fill()
    for lx in (460, 790):
        ctx.rectangle(lx, 290, 8, 24)
        ctx.set_source_rgb(*faded((0.35, 0.22, 0.14)))
        ctx.fill()
    plate(ctx, x + 20, y + 18, '1621')
    caption_panel(ctx)
    font(ctx, 'URW Bookman', 34, bold=False)
    ctx.set_source_rgb(*FADED_INK)
    for text, base in ((LINE_1_TEXT, LINE_1), (LINE_2_TEXT, LINE_2)):
        ctx.new_path()
        text_path(ctx, text, W / 2, base, align='center')
        ctx.fill()
    return s


@lru_cache(maxsize=1)
def card_end():
    x, y, w, h = FRAME
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(s)
    ctx.rectangle(x, y, w, h)
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, *faded((0.3, 0.25, 0.55)))
    g.add_color_stop_rgb(0.55, *faded((0.95, 0.5, 0.35)))
    g.add_color_stop_rgb(1, *faded((1.0, 0.8, 0.45)))
    ctx.set_source(g)
    ctx.fill()
    ctx.arc(W / 2, y + h * 0.62, 90, 0, TAU)                   # the setting sun
    ctx.set_source_rgb(*faded((1.0, 0.88, 0.55)))
    ctx.fill()
    ctx.rectangle(x, y + h * 0.66, w, h * 0.34)
    ctx.set_source_rgb(*faded((0.3, 0.3, 0.45)))
    ctx.fill()
    font(ctx, 'URW Bookman', 96)
    ctx.new_path()
    text_path(ctx, 'THE END', W / 2, END_BASE, tracking=8, align='center')
    ctx.set_source_rgb(*faded((0.99, 0.96, 0.86)))
    ctx.fill_preserve()
    ctx.set_source_rgb(*FADED_INK)
    ctx.set_line_width(2.5)
    ctx.stroke()
    return s


LINE_1_TEXT = 'The Pilgrims and the Indians shared'
LINE_2_TEXT = 'a feast of turkey and pumpkin pie.'
END_BASE = 236


def plate(ctx, x, y, text):
    rounded_rect(ctx, x, y, 92, 40, 6)
    ctx.set_source_rgb(*faded((0.99, 0.95, 0.85)))
    ctx.fill()
    font(ctx, 'URW Bookman', 24)
    ctx.new_path()
    text_path(ctx, text, x + 46, y + 29, align='center')
    ctx.set_source_rgb(*FADED_INK)
    ctx.fill()


def caption_panel(ctx):
    x, y, w, h = FRAME
    ctx.rectangle(x, CAPTION_TOP, w, y + h - CAPTION_TOP)
    ctx.set_source_rgb(*faded((0.99, 0.95, 0.84)))
    ctx.fill()
    ctx.rectangle(x + 14, CAPTION_TOP + 10, w - 28, y + h - CAPTION_TOP - 20)
    ctx.set_source_rgb(*faded((0.75, 0.55, 0.35)))
    ctx.set_line_width(2)
    ctx.stroke()


@lru_cache(maxsize=None)
def word_box(line, word):
    """Where a word of a caption line sits: (x0, x1, baseline)."""
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 8, 8))
    font(ctx, 'URW Bookman', 34, bold=False)
    text = LINE_1_TEXT if line == 1 else LINE_2_TEXT
    left = W / 2 - ctx.text_extents(text).x_advance / 2
    i = text.index(word)
    x0 = left + ctx.text_extents(text[:i]).x_advance if i else left
    x0 = left + sum(ctx.text_extents(ch).x_advance for ch in text[:i])
    x1 = x0 + sum(ctx.text_extents(ch).x_advance for ch in word)
    return x0, x1, LINE_1 if line == 1 else LINE_2


# ---------------------------------------------------------------- the marker

def marker_hand(t, x, y):
    """The red marker, its tip at (x, y), leaning in from the lower right."""
    return x, y


def draw_marker(ctx, x, y, t, lift=0.0):
    ctx.save()
    ctx.translate(x + 14 * lift, y - 30 * lift)
    ctx.rotate(-0.7 + 0.04 * math.sin(t * 19))
    ctx.move_to(0, 0)                                          # the felt tip
    ctx.line_to(14, -7)
    ctx.line_to(14, 7)
    ctx.close_path()
    inked(ctx, RED, 2, (3, 3))
    rounded_rect(ctx, 12, -11, 22, 22, 3)                      # the collar
    inked(ctx, (0.92, 0.92, 0.9), 2.5, (3, 3))
    rounded_rect(ctx, 32, -15, 170, 30, 9)                     # the barrel
    g = cairo.LinearGradient(0, -15, 0, 15)
    g.add_color_stop_rgb(0, 0.97, 0.97, 0.95)
    g.add_color_stop_rgb(1, 0.78, 0.78, 0.76)
    inked(ctx, g, 3, (5, 5))
    rounded_rect(ctx, 180, -16, 26, 32, 8)                     # the end cap, red
    inked(ctx, RED, 3, (0, 0))
    font(ctx, 'Nimbus Sans', 14)
    ctx.new_path()
    text_path(ctx, 'PERMANENT', 60, 5, tracking=2)
    ctx.set_source_rgb(*RED)
    ctx.fill()
    ctx.restore()


def scrawl(ctx, text, x, y, size, progress, angle=-0.04, align='left'):
    """Marker handwriting, revealed left to right; returns where the tip is."""
    ctx.save()
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    width = ctx.text_extents(text).x_advance
    if align == 'center':
        x -= width / 2
    ctx.translate(x, y)
    ctx.rotate(angle)
    tip = (x + width * progress * math.cos(angle), y + width * progress * math.sin(angle) - size * 0.3)
    if progress > 0:
        ctx.rectangle(-10, -size * 1.2, width * progress + 10, size * 1.6)
        ctx.clip()
        ctx.move_to(0, 0)
        ctx.text_path(text)
        ctx.set_source_rgb(*RED)
        ctx.fill()
    ctx.restore()
    return tip


def strike(ctx, x0, x1, y, progress, wobble=0):
    """A marker line struck through, drawn from x0 to x1."""
    if progress <= 0:
        return (x0, y)
    xe = x0 + (x1 - x0) * progress
    ctx.move_to(x0 - 6, y + 2)
    ctx.curve_to(x0 + (xe - x0) * 0.3, y - 3 + wobble, x0 + (xe - x0) * 0.7, y + 3 - wobble, xe, y - 1)
    ctx.set_source_rgba(*RED, 0.92)
    ctx.set_line_width(7)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    return (xe, y - 1)


def ring(ctx, cx, cy, rx, ry, progress):
    """A loop drawn round a word, a little more than once round."""
    if progress <= 0:
        return (cx + rx, cy)
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(rx, ry)
    a0 = -2.6
    a1 = a0 + TAU * 1.08 * progress
    ctx.arc(0, 0, 1, a0, a1)
    ctx.restore()
    ctx.set_source_rgba(*RED, 0.92)
    ctx.set_line_width(6)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    return (cx + rx * math.cos(a1), cy + ry * math.sin(a1))


def edit_progress(t, k):
    return clamp((t - EDITS[k]) / WRITE[k])


def annotations(ctx, t):
    """The footnotes on the feast card; returns where the marker's tip is, or None."""
    tip = None
    # 1: the Indians -> the Wampanoag
    p = edit_progress(t, 0)
    if p > 0:
        x0, x1, base = word_box(1, 'the Indians')
        tip = strike(ctx, x0, x1, base - 11, clamp(p / 0.4))
        if p > 0.4:
            tip = scrawl(ctx, 'the Wampanoag', (x0 + x1) / 2, base - 40, 30, (p - 0.4) / 0.6, align='center')
    # 2: turkey, circled: unconfirmed
    p = edit_progress(t, 1)
    if p > 0:
        x0, x1, base = word_box(2, 'turkey')
        tip = ring(ctx, (x0 + x1) / 2, base - 11, (x1 - x0) / 2 + 12, 24, clamp(p / 0.45))
        if p > 0.45:
            tip = scrawl(ctx, 'unconfirmed', (x0 + x1) / 2 - 20, base - 44, 26, (p - 0.45) / 0.55, angle=-0.08,
                         align='center')
    # 3: pumpkin pie -> no ovens yet!
    p = edit_progress(t, 2)
    if p > 0:
        x0, x1, base = word_box(2, 'pumpkin pie')
        tip = strike(ctx, x0, x1, base - 11, clamp(p / 0.35), 2)
        if p > 0.35:
            tip = scrawl(ctx, 'no ovens yet!', (x0 + x1) / 2 + 30, base - 44, 26, (p - 0.35) / 0.65, angle=0.05,
                         align='center')
    # 4: shared a feast -> a 3-day diplomatic summit (in the sky)
    p = edit_progress(t, 3)
    if p > 0:
        x0, _, base = word_box(1, 'shared')
        _, x1, _ = word_box(2, 'feast')
        sx0, _, _ = word_box(1, 'shared')
        _, sx1, _ = word_box(1, 'shared')
        u = clamp(p / 0.3)
        tip = strike(ctx, sx0, sx1, base + 10, u, -3)          # underlined, both lines
        fx0, fx1, base2 = word_box(2, 'a feast')
        strike(ctx, fx0, fx1, base2 + 10, clamp((p - 0.15) / 0.2), 3)
        if p > 0.32:
            tip = scrawl(ctx, '*a 3-day diplomatic summit', 690, 150, 32, (p - 0.32) / 0.68, angle=-0.06,
                         align='center')
        if p > 0.3:
            q = clamp((p - 0.3) / 0.1)                         # an arrow up to it
            ctx.move_to(sx1 - 10, base - 34)
            ctx.line_to(sx1 - 10 + (650 - sx1) * q * 0.35, base - 34 - (base - 200) * q)
            ctx.set_source_rgba(*RED, 0.9)
            ctx.set_line_width(5)
            ctx.stroke()
    return tip


def end_annotations(ctx, t):
    tip = None
    p = span(t, STRIKE_END, STRIKE_END + 0.18)
    if p > 0:
        tip = strike(ctx, 420, 860, END_BASE - 34, p, 6)
        strike(ctx, 420, 860, END_BASE - 22, clamp((p - 0.5) / 0.5), -5)
    p = span(t, *STILL_HERE)
    if p > 0:
        tip = scrawl(ctx, 'STILL HERE.', W / 2, 372, 104, p, angle=-0.05, align='center')
    q = ease_out(span(t, NATION, NATION + 0.35))
    if q > 0:                                                  # in clean modern type, over the old film
        x, y, w, h = FRAME
        ctx.save()
        ctx.rectangle(x + 70, 412, w - 140, 62)
        ctx.set_source_rgba(0.05, 0.05, 0.08, 0.82 * q)
        ctx.fill()
        font(ctx, 'Nimbus Sans', 26)
        ctx.new_path()
        text_path(ctx, 'THE WAMPANOAG NATION', W / 2, 442, tracking=5, align='center')
        ctx.set_source_rgba(1, 1, 1, q)
        ctx.fill()
        font(ctx, 'Nimbus Sans', 16, bold=False)
        ctx.new_path()
        text_path(ctx, 'MASHPEE  ·  AQUINNAH  ·  PEOPLE OF THE FIRST LIGHT', W / 2, 463, tracking=3, align='center')
        ctx.set_source_rgba(1, 0.85, 0.5, q)
        ctx.fill()
        ctx.restore()
    p = span(t, *DINNER)
    if p > 0:
        tip = scrawl(ctx, '(please still enjoy your dinner)', 800, 512, 27, p, angle=-0.03, align='center')
    return tip


# ---------------------------------------------------------------- the projection

def projection(ctx, t, frame):
    x, y, w, h = FRAME
    flick = 0.93 + 0.05 * math.sin(t * 47) + 0.03 * math.sin(t * 71 + 1)
    slide = ease_in_out(span(t, ADVANCE, ADVANCE + 0.2))
    ctx.save()
    ctx.rectangle(x, y, w, h)
    ctx.clip()
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if slide < 1:
        ctx.save()
        ctx.translate(0, -(h + 16) * slide)
        ctx.set_source_surface(card_feast(), 0, 0)
        ctx.paint()
        tip = annotations(ctx, t)
        ctx.restore()
    if slide > 0:
        ctx.save()
        ctx.translate(0, (h + 16) * (1 - slide))
        ctx.set_source_surface(card_end(), 0, 0)
        ctx.paint()
        ctx.restore()
    if slide >= 1:
        tip = end_annotations(ctx, t)
    rand = random.Random(frame // 3)                           # dust, a hair, the gate's flicker
    for _ in range(7):
        ctx.arc(rand.uniform(x, x + w), rand.uniform(y, y + h), rand.uniform(1, 3.5), 0, TAU)
        ctx.set_source_rgba(0.1, 0.05, 0.05, 0.5)
        ctx.fill()
    if rand.random() < 0.25:
        hx = rand.uniform(x, x + w)
        ctx.move_to(hx, y)
        ctx.curve_to(hx + 10, y + h * 0.3, hx - 10, y + h * 0.6, hx + 4, y + h)
        ctx.set_source_rgba(0.95, 0.9, 0.85, 0.25)
        ctx.set_line_width(1.5)
        ctx.stroke()
    g = cairo.RadialGradient(x + w / 2, y + h / 2, h * 0.3, x + w / 2, y + h / 2, w * 0.62)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0, 0, 0, 0.55)
    ctx.set_source(g)
    ctx.paint()
    ctx.set_source_rgba(0, 0, 0, 1 - flick)
    ctx.paint()
    ctx.restore()
    return tip


def marker(ctx, t, tip):
    """In from the lower right before the first footnote; it rests between them, and leaves
    after the dinner note."""
    come = ease_out(span(t, *MARKER_IN))
    go = ease_in(span(t, DINNER[1] + 0.05, DINNER[1] + 0.45))
    if come <= 0 or go >= 1:
        return
    rest = (W - 120, H - 60)
    if tip is None:
        x, y, lift = rest[0] - 300 * come, rest[1] - 140 * come, 1.0
        if t > EDITS[0]:
            x, y = 930, 560
    else:
        x, y, lift = tip[0], tip[1], 0.0
    x += (W + 200 - x) * go
    y += (H + 200 - y) * go
    if come < 1:
        x = x + (W + 260 - x) * (1 - come)
        y = y + (H + 200 - y) * (1 - come)
    draw_marker(ctx, x, y, t, lift)


# ---------------------------------------------------------------- the closed logo

def lockup(ctx, t):
    if t < LOGO[0] - 0.1:
        return
    neighborhood.lockup(ctx, t, LOGO[0], 660, scale=0.56, step=(LOGO[3] - LOGO[0]) / 10)
    q = ease_out(span(t, LOGO[3], LOGO[3] + 0.4))
    if q > 0:
        font(ctx, 'Nimbus Sans', 22)
        ctx.new_path()
        text_path(ctx, 'WE READ THE FOOTNOTES', W / 2, 702, tracking=9, align='center')
        ctx.set_source_rgba(1.0, 0.82, 0.4, q)
        ctx.fill()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    ctx.set_source_surface(room_surface(), 0, 0)
    ctx.paint()
    x, y, w, h = FRAME                                         # the projector's light on the screen around it
    g = cairo.RadialGradient(x + w / 2, y + h / 2, h * 0.4, x + w / 2, y + h / 2, w * 0.66)
    g.add_color_stop_rgba(0, 0.95, 0.9, 0.8, 0.25)
    g.add_color_stop_rgba(1, 0.95, 0.9, 0.8, 0)
    ctx.save()
    ctx.rectangle(*SCREEN)
    ctx.clip()
    ctx.set_source(g)
    ctx.paint()
    ctx.restore()
    tip = projection(ctx, t, frame)
    marker(ctx, t, tip)
    lockup(ctx, t)
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.6)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        iris(ctx, W / 2, 300, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        iris(ctx, W / 2, 340, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 110 * (1 - closing) / .3)
