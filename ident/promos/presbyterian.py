"""Decently and in Order: VizelVision as a Presbyterian session meeting, played dry.

1. The church parlour on a weeknight: oak panelling, John Knox frowning from his frame,
   DECENTLY & IN ORDER in cross-stitch, the clock at 7:19, and through the window a
   piper on the lawn in his feather bonnet. Behind a folding table in a white cloth sit
   four elders in cardigans and the moderator in his black Geneva gown and white preaching
   bands; name tents, a coffee carafe, shortbread, the Book of Order, Robert's Rules. On
   the easel, the agenda: ITEM 19, MOTION TO WATCH VIZELVISION, circled in red marker.
   "All in favour?" The open logo is the vote: a green AYE card up on each note, left to
   right, each elder saying it ("Aye."), and the piper playing it outside. The gavel.
   "The motion carries." A tick on the agenda.
2. The minutes of the session, open on the table: the motion moved, seconded and
   CARRIED, in a clerk's hand, and dated the 19th day of October, 1536. "As it was
   always going to." A red PREDESTINED stamp comes down.
3. A tartan wipe (the station's own sett: navy, teal, pink, a yellow line), and on the
   closed logo the burning bush: the seal of the station's TV in the flames, flaring on
   each note and NEC TAMEN CONSUMEBATUR round the ring, the wordmark under it, and
   DECENTLY AND IN ORDER. "Decently, and in order."

The voices: Draco, the moderator; Hera, Mars, Cora and Zeus, the elders' ayes.
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (A, INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    font, grain, inked, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'presbyterian'
NAME = 'Decently and in Order'
KIND = 'ident'
ORDER = 38
DESCRIPTION = ('VizelVision as a Presbyterian session meeting: elders in cardigans vote AYE on the open logo while a '
               'piper plays it on the lawn, the gavel, "The motion carries", then the minutes, already written in '
               '1536, stamped PREDESTINED. The burning bush with the station\'s TV in it on the closed logo. '
               'Decently and in order. Draco and the elders.')
DURATION = 10.0
STILL_AT = 8.9
OVERLAYS = []

# Hit points (the music's too).
FADE_IN = (0.0, 0.4)
CIRCLE = (0.55, 1.25)                            # the red marker goes round item 19
CARDS = (1.5, 1.75, 2.0, 2.5)                    # the open logo: an AYE card up on each note
GAVEL_UP = (2.55, 2.85)
GAVEL = 2.95                                     # the gavel comes down
TICK = (3.05, 3.3)                               # a tick against item 19
CARDS_DOWN = (3.35, 3.85)
CUT = 4.35                                       # to the minutes
STAMP = 5.3                                      # PREDESTINED
WIPE = (6.3, 6.85)                               # the tartan comes across
SEAL_IN = (6.6, 7.0)
CLOSED = 7.0                                     # the closed logo: the bush flares on each note
FLARES = (7.0, 7.25, 7.5, 8.0)
TAGLINE = 8.05
FADE = (9.25, 9.6)

# The parlour.
TABLE_BACK, TABLE_FRONT, CLOTH_HEM = 436, 474, 610
SHOULDER_Y = 368
ELDERS = ((250, 'bun', (0.55, 0.22, 0.28), 'MRS. McGREGOR', (0.86, 0.86, 0.84)),
          (445, 'fringe', (0.36, 0.42, 0.3), 'MR. PATTERSON', (0.78, 0.78, 0.76)),
          (835, 'short', (0.2, 0.3, 0.5), 'DR. NG', (0.12, 0.1, 0.1)),
          (1030, 'perm', (0.62, 0.48, 0.3), 'MS. CAMPBELL', (0.92, 0.9, 0.88)))
MODERATOR = 640
WINDOW = (72, 72, 236, 236)                      # x, y, w, h of the glass
EASEL = (1040, 150, 186, 250)                    # the pad: x, y, w, h

SKIN = ((0.93, 0.76, 0.64), (0.86, 0.68, 0.55), (0.88, 0.72, 0.58), (0.92, 0.75, 0.62), (0.9, 0.73, 0.6))
OAK = (0.45, 0.28, 0.15)
OAK_DARK = (0.3, 0.18, 0.09)
PLASTER = (0.93, 0.89, 0.8)
CLOTH = (0.97, 0.96, 0.92)
BRASS = (0.86, 0.68, 0.32)
GOLD = (0.95, 0.76, 0.3)
NAVY = (0.07, 0.11, 0.27)
INKWELL = (0.24, 0.13, 0.06)
STAMP_RED = (0.8, 0.08, 0.1)
MARKER_RED = (0.86, 0.1, 0.12)
MARKER_BLUE = (0.1, 0.16, 0.42)
AYE_GREEN = (0.12, 0.55, 0.28)
# The station's sett: navy ground, teal, pink, a yellow line (widths in px).
SETT = ((NAVY, 36), (TEAL, 14), (NAVY, 6), (PINK, 22), (NAVY, 6), (TEAL, 14), (NAVY, 30), ((1.0, 0.86, 0.12), 3))


# ---------------------------------------------------------------- 1. the parlour (drawn once)

def panel(ctx, x, y, w, h):
    """A raised oak panel: a bevel round a flat field."""
    ctx.rectangle(x, y, w, h)
    ctx.set_source_rgb(*mix(OAK, OAK_DARK, 0.4))
    ctx.fill()
    g = cairo.LinearGradient(x, y, x + w, y + h)
    g.add_color_stop_rgb(0, *mix(OAK, (1, 0.9, 0.7), 0.15))
    g.add_color_stop_rgb(1, *OAK_DARK)
    rounded_rect(ctx, x + 8, y + 8, w - 16, h - 16, 3)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(x + 16, y + 16, w - 32, h - 32)
    ctx.set_source_rgb(*mix(OAK, OAK_DARK, 0.2))
    ctx.fill()
    rand = random.Random(int(x * 7 + y))
    for _ in range(9):                                               # the grain
        gx = x + 18 + rand.random() * (w - 36)
        ctx.move_to(gx, y + 17)
        ctx.curve_to(gx + rand.uniform(-6, 6), y + h * 0.3, gx + rand.uniform(-6, 6), y + h * 0.7, gx + rand.uniform(-4, 4),
                     y + h - 17)
        ctx.set_source_rgba(*OAK_DARK, 0.35)
        ctx.set_line_width(1.2)
        ctx.stroke()


def frame_box(ctx, x, y, w, h, gilt=True):
    """A picture frame: moulded, gilt or dark."""
    for k, (inset, colour) in enumerate(((0, (0.42, 0.3, 0.1) if gilt else OAK_DARK), (5, GOLD if gilt else OAK),
                                         (10, (0.6, 0.44, 0.16) if gilt else OAK_DARK))):
        ctx.rectangle(x + inset, y + inset, w - 2 * inset, h - 2 * inset)
        ctx.set_source_rgb(*colour)
        ctx.fill()


def knox(ctx):
    """John Knox, in oils: black cap, long beard, displeased."""
    x, y, w, h = 572, 46, 136, 176
    frame_box(ctx, x, y, w, h)
    ix, iy, iw, ih = x + 14, y + 14, w - 28, h - 28
    g = cairo.RadialGradient(ix + iw / 2, iy + ih * 0.4, 10, ix + iw / 2, iy + ih / 2, ih)
    g.add_color_stop_rgb(0, 0.32, 0.26, 0.17)
    g.add_color_stop_rgb(1, 0.1, 0.08, 0.05)
    ctx.rectangle(ix, iy, iw, ih)
    ctx.set_source(g)
    ctx.fill()
    cx = ix + iw / 2
    ctx.save()
    ctx.rectangle(ix, iy, iw, ih)
    ctx.clip()
    ctx.move_to(cx - 52, iy + ih)                                    # the black gown
    ctx.curve_to(cx - 48, iy + 110, cx + 48, iy + 110, cx + 52, iy + ih)
    ctx.set_source_rgb(0.06, 0.05, 0.05)
    ctx.fill()
    ctx.save()                                                       # the face
    ctx.translate(cx, iy + 60)
    ctx.scale(1, 1.25)
    ctx.arc(0, 0, 19, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.78, 0.6, 0.46)
    ctx.fill()
    ctx.move_to(cx - 19, iy + 64)                                    # the beard, long and forked
    ctx.curve_to(cx - 26, iy + 110, cx - 10, iy + 128, cx - 2, iy + 136)
    ctx.line_to(cx + 2, iy + 136)
    ctx.curve_to(cx + 10, iy + 128, cx + 26, iy + 110, cx + 19, iy + 64)
    ctx.curve_to(cx + 10, iy + 76, cx - 10, iy + 76, cx - 19, iy + 64)
    ctx.set_source_rgb(0.42, 0.36, 0.3)
    ctx.fill()
    ctx.arc(cx, iy + 47, 21, math.pi, 0)                             # the cap
    ctx.set_source_rgb(0.05, 0.04, 0.04)
    ctx.fill()
    ctx.set_source_rgb(0.15, 0.1, 0.08)                              # the frown
    ctx.set_line_width(2)
    for sx in (-1, 1):
        ctx.move_to(cx + sx * 4, iy + 54)
        ctx.line_to(cx + sx * 13, iy + 57)
    ctx.stroke()
    for sx in (-1, 1):
        ctx.arc(cx + sx * 8, iy + 60, 1.8, 0, TAU)
        ctx.fill()
    ctx.restore()
    rounded_rect(ctx, cx - 50, y + h + 6, 100, 20, 3)                # the plaque
    ctx.set_source_rgb(*BRASS)
    ctx.fill()
    ctx.set_source_rgb(0.2, 0.13, 0.05)
    font(ctx, 'C059', 10.5)
    text_path(ctx, 'JOHN KNOX  1514-1572', cx, y + h + 20, tracking=0.6, align='center')
    ctx.fill()


def sampler(ctx):
    """DECENTLY & IN ORDER in cross-stitch, in a dark frame."""
    x, y, w, h = 384, 92, 156, 104
    frame_box(ctx, x, y, w, h, gilt=False)
    ctx.rectangle(x + 10, y + 10, w - 20, h - 20)
    ctx.set_source_rgb(0.95, 0.92, 0.84)
    ctx.fill()
    for lx, ly, text, colour in ((x + w / 2, y + 42, 'DECENTLY &', (0.12, 0.3, 0.55)),
                                 (x + w / 2, y + 62, 'IN ORDER', (0.12, 0.3, 0.55)),
                                 (x + w / 2, y + 83, '1 COR 14:40', (0.62, 0.14, 0.18))):
        ctx.set_source_rgb(*colour)
        font(ctx, 'Nimbus Mono PS', 15 if ly < y + 70 else 11)
        text_path(ctx, text, lx, ly, tracking=1.2, align='center')
        ctx.fill()
    for k in range(16):                                              # a stitched border of little crosses
        for (bx, by) in ((x + 16 + k * 8.2, y + 18), (x + 16 + k * 8.2, y + h - 18)):
            ctx.move_to(bx - 2, by - 2)
            ctx.line_to(bx + 2, by + 2)
            ctx.move_to(bx + 2, by - 2)
            ctx.line_to(bx - 2, by + 2)
    ctx.set_source_rgb(0.3, 0.5, 0.3)
    ctx.set_line_width(1.2)
    ctx.stroke()


def clock(ctx):
    """The parlour clock, at 7:19."""
    cx, cy, r = 820, 112, 36
    ctx.arc(cx, cy, r + 5, 0, TAU)
    ctx.set_source_rgb(*OAK_DARK)
    ctx.fill()
    ctx.arc(cx, cy, r, 0, TAU)
    ctx.set_source_rgb(0.97, 0.95, 0.9)
    ctx.fill()
    ctx.set_source_rgb(0.15, 0.12, 0.1)
    for k in range(12):
        a = k * TAU / 12
        ctx.move_to(cx + math.sin(a) * (r - 4), cy - math.cos(a) * (r - 4))
        ctx.line_to(cx + math.sin(a) * (r - 9), cy - math.cos(a) * (r - 9))
    ctx.set_line_width(2)
    ctx.stroke()
    for angle, length, width in ((TAU * (7 + 19 / 60) / 12, r * 0.5, 3.4), (TAU * 19 / 60, r * 0.78, 2.2)):
        ctx.move_to(cx, cy)
        ctx.line_to(cx + math.sin(angle) * length, cy - math.cos(angle) * length)
        ctx.set_line_width(width)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()


def window_frame(ctx):
    """The sash window's casing and its green velvet curtains (the glass is drawn per frame)."""
    x, y, w, h = WINDOW
    ctx.rectangle(x - 16, y - 16, w + 32, h + 34)
    ctx.set_source_rgb(0.95, 0.94, 0.9)
    ctx.fill()
    ctx.rectangle(x - 24, y + h + 12, w + 48, 12)                    # the sill
    ctx.set_source_rgb(0.88, 0.86, 0.8)
    ctx.fill()
    for side in (-1, 1):                                             # the curtains, gathered
        cx = x - 10 if side < 0 else x + w + 10
        ctx.move_to(cx, y - 30)
        ctx.line_to(cx + side * 46, y - 30)
        ctx.curve_to(cx + side * 40, y + 110, cx + side * 30, y + 170, cx + side * 52, y + h + 60)
        ctx.line_to(cx - side * 22, y + h + 60)
        ctx.curve_to(cx - side * 4, y + 200, cx - side * 18, y + 60, cx, y - 30)
        g = cairo.LinearGradient(cx - 30, 0, cx + 50, 0)
        g.add_color_stop_rgb(0, 0.08, 0.26, 0.16)
        g.add_color_stop_rgb(0.5, 0.16, 0.42, 0.26)
        g.add_color_stop_rgb(1, 0.06, 0.2, 0.12)
        ctx.set_source(g)
        ctx.fill()
    ctx.rectangle(x - 40, y - 36, w + 80, 9)                         # the rod
    ctx.set_source_rgb(*BRASS)
    ctx.fill()


@lru_cache(maxsize=None)
def parlour():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, 330)                           # plaster, warm under the lamps
    g.add_color_stop_rgb(0, *mix(PLASTER, (0.7, 0.62, 0.5), 0.25))
    g.add_color_stop_rgb(1, PLASTER[0], PLASTER[1] * 0.98, PLASTER[2] * 0.94)
    ctx.rectangle(0, 0, W, 330)
    ctx.set_source(g)
    ctx.fill()
    for y, h, colour in ((0, 16, OAK_DARK), (16, 6, OAK), (322, 10, OAK_DARK), (316, 6, OAK)):   # cornice and rail
        ctx.rectangle(0, y, W, h)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    for k in range(9):                                               # the wainscot
        panel(ctx, k * 146 - 20, 332, 146, 188)
    ctx.rectangle(0, 520, W, H - 520)                                # the carpet, institutional maroon
    ctx.set_source_rgb(0.42, 0.12, 0.14)
    ctx.fill()
    rand = random.Random(4)
    for _ in range(260):
        ctx.arc(rand.uniform(0, W), rand.uniform(522, H), rand.uniform(1, 2.4), 0, TAU)
        ctx.set_source_rgba(0.8, 0.62, 0.3, 0.25)
        ctx.fill()
    window_frame(ctx)
    knox(ctx)
    sampler(ctx)
    clock(ctx)
    # The easel's legs (the pad is drawn per frame).
    x, y, w, h = EASEL
    ctx.set_source_rgb(*OAK)
    ctx.set_line_width(9)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for x0, x1 in ((x + 22, x - 12), (x + w - 22, x + w + 12), (x + w / 2, x + w / 2 + 6)):
        ctx.move_to(x0, y - 12)
        ctx.line_to(x1, 640)
        ctx.stroke()
    ctx.rectangle(x - 6, y + h + 4, w + 12, 12)                      # the ledge
    ctx.set_source_rgb(*OAK_DARK)
    ctx.fill()
    return surface


@lru_cache(maxsize=None)
def table_cloth():
    """The folding table in its white cloth, hanging in folds."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    ctx.move_to(150, TABLE_BACK)                                     # the top, seen a little from above
    ctx.line_to(1130, TABLE_BACK)
    ctx.line_to(1162, TABLE_FRONT)
    ctx.line_to(118, TABLE_FRONT)
    ctx.close_path()
    ctx.set_source_rgb(*mix(CLOTH, (0.8, 0.78, 0.72), 0.12))
    ctx.fill()
    ctx.rectangle(118, TABLE_FRONT, 1044, CLOTH_HEM - TABLE_FRONT)    # the drop, in folds
    g = cairo.LinearGradient(118, 0, 1162, 0)
    for k in range(29):
        g.add_color_stop_rgb(k / 28, *mix(CLOTH, (0.72, 0.7, 0.66), 0.15 + 0.15 * math.sin(k * 1.9) ** 2))
    ctx.set_source(g)
    ctx.fill()
    ctx.move_to(118, CLOTH_HEM)                                      # a scalloped hem
    for k in range(29):
        ctx.curve_to(118 + k * 36 + 12, CLOTH_HEM + 7, 118 + k * 36 + 24, CLOTH_HEM + 7, 118 + (k + 1) * 36, CLOTH_HEM)
    ctx.line_to(1162, CLOTH_HEM - 2)
    ctx.line_to(118, CLOTH_HEM - 2)
    ctx.close_path()
    ctx.set_source_rgb(*mix(CLOTH, (0.72, 0.7, 0.66), 0.25))
    ctx.fill()
    ctx.move_to(118, TABLE_FRONT)
    ctx.line_to(1162, TABLE_FRONT)
    ctx.set_source_rgba(0, 0, 0, 0.12)
    ctx.set_line_width(2)
    ctx.stroke()
    # The runner down the front: ordinary-time green, gold braid, a Celtic cross, a fringe.
    x0, x1, bottom = 586, 694, 592
    ctx.rectangle(x0, TABLE_FRONT - 2, x1 - x0, bottom - TABLE_FRONT)
    ctx.set_source_rgb(0.1, 0.36, 0.2)
    ctx.fill()
    for inset in (6, 10):
        ctx.rectangle(x0 + inset, TABLE_FRONT + 2, x1 - x0 - 2 * inset, bottom - TABLE_FRONT - 8)
    ctx.set_source_rgb(*GOLD)
    ctx.set_line_width(1.4)
    ctx.stroke()
    cx, cy = (x0 + x1) / 2, TABLE_FRONT + 52
    ctx.set_source_rgb(*GOLD)
    ctx.rectangle(cx - 5, cy - 34, 10, 76)                           # the cross
    ctx.rectangle(cx - 26, cy - 5, 52, 10)
    ctx.fill()
    ctx.arc(cx, cy, 16, 0, TAU)                                      # and its ring
    ctx.set_line_width(4)
    ctx.stroke()
    for k in range(18):                                              # the fringe
        ctx.move_to(x0 + 3 + k * 6, bottom)
        ctx.line_to(x0 + 3 + k * 6, bottom + 9)
    ctx.set_line_width(2)
    ctx.stroke()
    return surface


def table_things(ctx):
    """On the table: name tents, the carafe, cups, shortbread, the Book of Order, Robert's Rules,
    the sound block."""
    rounded_rect(ctx, 588, 444, 38, 11, 3)                           # the gavel's sound block
    ctx.set_source_rgb(*OAK_DARK)
    ctx.fill()
    for x, _, _, name, _ in ELDERS:
        tent(ctx, x, name)
    tent(ctx, MODERATOR, 'MODERATOR')
    # The carafe.
    cx, base = 545, 466
    rounded_rect(ctx, cx - 17, base - 74, 34, 74, 7)
    g = cairo.LinearGradient(cx - 17, 0, cx + 17, 0)
    g.add_color_stop_rgb(0, 0.12, 0.12, 0.14)
    g.add_color_stop_rgb(0.35, 0.45, 0.45, 0.5)
    g.add_color_stop_rgb(1, 0.08, 0.08, 0.1)
    ctx.set_source(g)
    ctx.fill()
    rounded_rect(ctx, cx - 11, base - 90, 22, 18, 4)
    ctx.set_source_rgb(0.1, 0.1, 0.12)
    ctx.fill()
    ctx.rectangle(cx + 15, base - 64, 10, 34)
    ctx.set_source_rgb(0.1, 0.1, 0.12)
    ctx.set_line_width(5)
    ctx.stroke()
    for x in (318, 520, 900, 1125, 600):                             # styrofoam cups
        cup(ctx, x, 468)
    # Shortbread on a plate.
    ctx.save()
    ctx.translate(745, 458)
    ctx.scale(1, 0.32)
    ctx.arc(0, 0, 40, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.96, 0.96, 0.98)
    ctx.fill()
    for k in range(5):
        rounded_rect(ctx, 718 + k * 11, 446 + (k % 2) * 3, 16, 9, 2)
        ctx.set_source_rgb(0.92, 0.78, 0.5)
        ctx.fill()
    book(ctx, 352, 458, 70, 18, (0.12, 0.28, 0.62), 'BOOK OF ORDER')
    book(ctx, 952, 458, 74, 18, (0.66, 0.1, 0.12), "ROBERT'S RULES")


def tent(ctx, x, name):
    font(ctx, 'Nimbus Sans Narrow', 11.5)
    w = ctx.text_extents(name).x_advance + 18
    ctx.move_to(x - w / 2, TABLE_FRONT - 2)
    ctx.line_to(x - w / 2 + 3, TABLE_FRONT - 22)
    ctx.line_to(x + w / 2 - 3, TABLE_FRONT - 22)
    ctx.line_to(x + w / 2, TABLE_FRONT - 2)
    ctx.close_path()
    ctx.set_source_rgb(0.99, 0.99, 0.97)
    ctx.fill_preserve()
    ctx.set_source_rgba(0, 0, 0, 0.25)
    ctx.set_line_width(1)
    ctx.stroke()
    ctx.set_source_rgb(0.1, 0.1, 0.12)
    text_path(ctx, name, x, TABLE_FRONT - 8, align='center')
    ctx.fill()


def cup(ctx, x, base):
    ctx.move_to(x - 9, base - 24)
    ctx.line_to(x + 9, base - 24)
    ctx.line_to(x + 6.5, base)
    ctx.line_to(x - 6.5, base)
    ctx.close_path()
    ctx.set_source_rgb(0.97, 0.97, 0.95)
    ctx.fill_preserve()
    ctx.set_source_rgba(0, 0, 0, 0.2)
    ctx.set_line_width(1)
    ctx.stroke()


def book(ctx, x, y, w, h, colour, title):
    ctx.move_to(x - w / 2 + 6, y - h)
    ctx.line_to(x + w / 2 + 6, y - h)
    ctx.line_to(x + w / 2, y)
    ctx.line_to(x - w / 2, y)
    ctx.close_path()
    ctx.set_source_rgb(*colour)
    ctx.fill()
    ctx.rectangle(x - w / 2, y, w, 5)
    ctx.set_source_rgb(0.95, 0.93, 0.86)
    ctx.fill()
    ctx.set_source_rgb(0.97, 0.9, 0.6)
    font(ctx, 'Nimbus Sans Narrow', 8)
    text_path(ctx, title, x + 3, y - h / 2 + 3, align='center')
    ctx.fill()


# ---------------------------------------------------------------- the people

def raised(t, at):
    """0 down, 1 up: the card goes up on its note, and comes down after the gavel."""
    up = back_out(span(t, at - 0.12, at + 0.06))
    down = ease_in_out(span(t, *CARDS_DOWN))
    return up * (1 - down)


def head(ctx, x, y, skin, hair, style, blink, glasses):
    """A face, front on: hair behind and on top, ears, eyes (blinking), a mouth."""
    if style == 'perm':
        for k in range(11):
            a = math.pi + k * math.pi / 10
            ctx.arc(x + math.cos(a) * 33, y - 4 + math.sin(a) * 34, 12, 0, TAU)
        ctx.set_source_rgb(*hair)
        ctx.fill()
    for sx in (-1, 1):                                               # ears
        ctx.arc(x + sx * 31, y + 4, 7, 0, TAU)
        ctx.set_source_rgb(*mix(skin, (0.6, 0.3, 0.25), 0.15))
        ctx.fill()
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(1, 1.15)
    ctx.arc(0, 0, 31, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*skin)
    ctx.fill()
    ctx.set_source_rgb(*hair)
    if style == 'bun':
        ctx.arc(x, y - 6, 32, math.pi * 1.02, -0.02)
        ctx.fill()
        ctx.arc(x, y - 44, 15, 0, TAU)
        ctx.fill()
    elif style == 'fringe':                                          # bald on top, a white fringe
        for sx in (-1, 1):
            ctx.save()
            ctx.translate(x + sx * 28, y - 2)
            ctx.scale(0.55, 1)
            ctx.arc(0, 0, 13, 0, TAU)
            ctx.restore()
            ctx.fill()
        ctx.arc(x - 8, y - 22, 8, 0, TAU)
        ctx.set_source_rgba(1, 1, 1, 0.25)
        ctx.fill()
    elif style == 'short':
        ctx.arc(x, y - 8, 32, math.pi * 1.05, -0.05)
        ctx.close_path()
        ctx.fill()
        ctx.rectangle(x - 31, y - 16, 62, 8)
        ctx.fill()
    elif style == 'perm':
        ctx.arc(x, y - 14, 30, math.pi * 1.05, -0.05)
        ctx.fill()
    ink = (0.14, 0.1, 0.08)
    for sx in (-1, 1):                                               # eyes
        ctx.save()
        ctx.translate(x + sx * 11, y + 2)
        ctx.scale(1, max(0.12, 1 - blink))
        ctx.arc(0, 0, 3.4, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*ink)
        ctx.fill()
        ctx.move_to(x + sx * 6, y - 9)                               # brows
        ctx.line_to(x + sx * 17, y - 10)
        ctx.set_source_rgb(*mix(hair, ink, 0.4))
        ctx.set_line_width(2.4)
        ctx.stroke()
    if glasses:
        for sx in (-1, 1):
            ctx.arc(x + sx * 11, y + 2, 9, 0, TAU)
            ctx.new_sub_path()
        ctx.move_to(x - 2, y + 1)
        ctx.line_to(x + 2, y + 1)
        ctx.set_source_rgb(0.25, 0.2, 0.15)
        ctx.set_line_width(1.8)
        ctx.stroke()
    ctx.move_to(x - 7, y + 19)                                       # a mouth, mild
    ctx.curve_to(x - 3, y + 21, x + 3, y + 21, x + 7, y + 19)
    ctx.set_source_rgb(0.5, 0.25, 0.22)
    ctx.set_line_width(2)
    ctx.stroke()
    ctx.move_to(x, y + 3)                                            # the nose
    ctx.line_to(x - 3, y + 12)
    ctx.line_to(x + 2, y + 12)
    ctx.set_source_rgba(0.5, 0.3, 0.25, 0.5)
    ctx.set_line_width(1.4)
    ctx.stroke()


def torso(ctx, x, colour, collar, gown=False):
    top = SHOULDER_Y
    ctx.move_to(x - 66, TABLE_BACK + 6)
    ctx.curve_to(x - 70, top + 20, x - 56, top, x - 30, top - 4)
    ctx.line_to(x + 30, top - 4)
    ctx.curve_to(x + 56, top, x + 70, top + 20, x + 66, TABLE_BACK + 6)
    ctx.close_path()
    ctx.set_source_rgb(*colour)
    ctx.fill()
    ctx.rectangle(x - 10, top - 26, 20, 26)                          # the neck
    ctx.set_source_rgb(*collar[0])
    ctx.fill()
    if gown:                                                          # white preaching bands on a black gown
        ctx.move_to(x - 16, top - 6)
        ctx.line_to(x + 16, top - 6)
        ctx.line_to(x + 10, top + 2)
        ctx.line_to(x - 10, top + 2)
        ctx.close_path()
        ctx.set_source_rgb(0.98, 0.98, 0.98)
        ctx.fill()
        for sx in (-1, 1):
            ctx.move_to(x + sx * 1.5, top)
            ctx.line_to(x + sx * 11, top)
            ctx.line_to(x + sx * 13, top + 44)
            ctx.line_to(x + sx * 2, top + 44)
            ctx.close_path()
            ctx.set_source_rgb(0.98, 0.98, 0.98)
            ctx.fill_preserve()
            ctx.set_source_rgba(0, 0, 0, 0.2)
            ctx.set_line_width(1)
            ctx.stroke()
        for sx in (-1, 1):                                            # the gown's velvet facings
            ctx.move_to(x + sx * 22, top - 2)
            ctx.line_to(x + sx * 30, TABLE_BACK + 6)
            ctx.set_source_rgb(0.18, 0.18, 0.2)
            ctx.set_line_width(9)
            ctx.stroke()
        return
    ctx.move_to(x - 15, top - 4)                                      # shirt in the V of the cardigan
    ctx.line_to(x + 15, top - 4)
    ctx.line_to(x, top + 34)
    ctx.close_path()
    ctx.set_source_rgb(*collar[1])
    ctx.fill()
    for k in range(3):                                                # buttons
        ctx.arc(x, top + 44 + k * 16, 3, 0, TAU)
        ctx.set_source_rgb(*mix(colour, (0.95, 0.9, 0.8), 0.5))
        ctx.fill()
    ctx.move_to(x, top + 36)
    ctx.line_to(x, TABLE_BACK + 6)
    ctx.set_source_rgba(0, 0, 0, 0.18)
    ctx.set_line_width(1.5)
    ctx.stroke()


def limb(ctx, points, colour, width=22):
    ctx.move_to(*points[0])
    for p in points[1:]:
        ctx.line_to(*p)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_source_rgb(*mix(colour, INK, 0.35))
    ctx.set_line_width(width + 3)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*colour)
    ctx.set_line_width(width)
    ctx.stroke()


def elder(ctx, t, k, x, style, colour, hair):
    skin = SKIN[k]
    side = -1 if k == 3 else 1                                       # Ms. Campbell votes with her other hand
    blink = pulse(t, 0.9 + k * 1.37 % 3.1, 0.14) + pulse(t, 5.0 + k * 0.7, 0.14)
    up = raised(t, CARDS[k])
    nod = 3 * math.sin(math.pi * span(t, GAVEL + 0.05, GAVEL + 0.6)) + 4 * math.sin(math.pi * span(t, *CARDS_DOWN))
    torso(ctx, x, colour, (skin, (0.96, 0.95, 0.9) if k % 2 else (0.85, 0.88, 0.95)))
    head(ctx, x, SHOULDER_Y - 58 + nod - 4 * up, skin, hair, style, min(1, blink), glasses=k in (0, 1, 3))
    # One arm rests; the other hand holds the card, then raises it.
    limb(ctx, [(x - side * 56, SHOULDER_Y + 18), (x - side * 52, TABLE_BACK + 4), (x - side * 18, TABLE_BACK + 14)],
         colour)
    ctx.arc(x - side * 14, TABLE_BACK + 14, 9, 0, TAU)
    ctx.set_source_rgb(*skin)
    ctx.fill()
    reach = 86 if side > 0 else 48
    hand = (mix((x + side * 26, TABLE_BACK + 12), (x + side * reach, SHOULDER_Y - 96), up))
    elbow = mix((x + side * 62, TABLE_BACK - 2), (x + side * (reach + 6), SHOULDER_Y - 10), up)
    limb(ctx, [(x + side * 56, SHOULDER_Y + 18), elbow, hand], colour)
    card(ctx, hand[0], hand[1], up)
    ctx.arc(hand[0], hand[1], 9, 0, TAU)
    ctx.set_source_rgb(*skin)
    ctx.fill()


def card(ctx, x, y, up):
    """The green voting card, AYE on it, flat on the table until it goes up."""
    ctx.save()
    ctx.translate(x + 2, y - 2)
    ctx.rotate(-0.08 * up)
    ctx.scale(1, 0.3 + 0.7 * up)
    rounded_rect(ctx, -24, -44, 48, 36, 3)
    ctx.set_source_rgb(*AYE_GREEN)
    ctx.fill_preserve()
    ctx.set_source_rgba(0, 0, 0, 0.3)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.set_source_rgb(1, 1, 1)
    font(ctx, 'Nimbus Sans', 17)
    text_path(ctx, 'AYE', 0, -20, align='center')
    ctx.fill()
    ctx.restore()


def moderator(ctx, t):
    x = MODERATOR
    skin = SKIN[4]
    torso(ctx, x, (0.07, 0.07, 0.09), (skin, WHITE), gown=True)
    blink = pulse(t, 2.2, 0.14) + pulse(t, 4.0, 0.14)
    head(ctx, x, SHOULDER_Y - 58, skin, (0.9, 0.9, 0.88), 'fringe', min(1, blink), glasses=True)
    # The gavel in his right hand (on our left): up, and down on the block.
    lift = ease_out(span(t, *GAVEL_UP)) * (1 - ease_in(span(t, GAVEL_UP[1], GAVEL)))
    rebound = 0.25 * math.sin(math.pi * span(t, GAVEL, GAVEL + 0.25))
    k = max(lift, rebound)
    hand = mix((x - 34, TABLE_BACK + 12), (x - 82, SHOULDER_Y - 40), k)
    elbow = mix((x - 70, TABLE_BACK - 6), (x - 96, SHOULDER_Y + 30), k)
    limb(ctx, [(x - 56, SHOULDER_Y + 18), elbow, hand], (0.07, 0.07, 0.09), width=26)
    ctx.save()                                                       # the gavel
    ctx.translate(*hand)
    ctx.rotate(-0.5 - 0.9 * k)
    rounded_rect(ctx, -3, -4, 40, 7, 3)
    ctx.set_source_rgb(*OAK)
    ctx.fill()
    rounded_rect(ctx, 30, -14, 18, 28, 5)
    ctx.set_source_rgb(*OAK_DARK)
    ctx.fill()
    ctx.restore()
    ctx.arc(*hand, 10, 0, TAU)
    ctx.set_source_rgb(*skin)
    ctx.fill()
    limb(ctx, [(x + 56, SHOULDER_Y + 18), (x + 50, TABLE_BACK + 4), (x + 16, TABLE_BACK + 14)], (0.07, 0.07, 0.09),
         width=26)
    ctx.arc(x + 14, TABLE_BACK + 14, 10, 0, TAU)
    ctx.set_source_rgb(*skin)
    ctx.fill()
    whack = 1 - span(t, GAVEL, GAVEL + 0.22)                         # the knock: lines off the block
    if GAVEL <= t and whack > 0:
        ctx.set_source_rgba(0.15, 0.1, 0.06, whack)
        ctx.set_line_width(3)
        for a in (-2.6, -2.1, -1.0, -0.5):
            ctx.move_to(606 + math.cos(a) * 26, 446 + math.sin(a) * 26)
            ctx.line_to(606 + math.cos(a) * 44, 446 + math.sin(a) * 44)
        ctx.stroke()


# ---------------------------------------------------------------- the piper, the agenda

def piper(ctx, t):
    """Through the window: a piper on the lawn in a feather bonnet, swaying as he plays."""
    x, y, w, h = WINDOW
    ctx.save()
    ctx.rectangle(x, y, w, h)
    ctx.clip()
    g = cairo.LinearGradient(0, y, 0, y + 150)
    g.add_color_stop_rgb(0, 0.42, 0.62, 0.86)
    g.add_color_stop_rgb(1, 0.94, 0.82, 0.62)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(9)
    for _ in range(14):                                              # distant trees
        ctx.arc(x + rand.uniform(-10, w + 10), y + 150 + rand.uniform(-6, 6), rand.uniform(16, 30), 0, TAU)
        ctx.set_source_rgb(*mix((0.2, 0.36, 0.22), (0.35, 0.42, 0.4), rand.random() * 0.5))
        ctx.fill()
    ctx.rectangle(x, y + 162, w, h)                                  # the lawn
    ctx.set_source_rgb(0.33, 0.55, 0.26)
    ctx.fill()
    ctx.rectangle(x, y + 152, w, 14)                                 # a low stone wall
    ctx.set_source_rgb(0.62, 0.6, 0.55)
    ctx.fill()
    for k in range(12):
        ctx.rectangle(x + k * 21, y + 152, 1.5, 14)
    ctx.set_source_rgba(0.3, 0.3, 0.28, 0.6)
    ctx.fill()
    # The piper: feet on the lawn, a little sway, the bag squeezed in time.
    px, py = x + 130, y + 226
    sway = 0.04 * math.sin(t * 2.6)
    squeeze = 1 + 0.06 * math.sin(t * TAU * 1.0)
    ctx.translate(px, py)
    ctx.rotate(sway)
    ctx.scale(0.62, 0.62)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for sx in (-1, 1):                                               # hose, flashes and brogues
        ctx.rectangle(sx * 7 - 4, -30, 8, 28)
        ctx.set_source_rgb(0.95, 0.94, 0.9)
        ctx.fill()
        ctx.rectangle(sx * 7 - 4, -30, 8, 3)
        ctx.set_source_rgb(0.8, 0.1, 0.1)
        ctx.fill()
        ctx.save()
        ctx.translate(sx * 8, 0)
        ctx.scale(1.4, 0.6)
        ctx.arc(0, -1, 6, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(0.05, 0.05, 0.05)
        ctx.fill()
    ctx.move_to(-17, -66)                                            # the kilt, pleated tartan
    ctx.line_to(17, -66)
    ctx.line_to(22, -30)
    ctx.line_to(-22, -30)
    ctx.close_path()
    ctx.set_source_rgb(0.72, 0.08, 0.1)
    ctx.fill()
    for k in range(5):
        ctx.rectangle(-22 + k * 10, -66, 3, 36)
    ctx.set_source_rgba(0.05, 0.25, 0.15, 0.8)
    ctx.fill()
    ctx.rectangle(-22, -52, 44, 3)
    ctx.set_source_rgba(0.05, 0.1, 0.3, 0.7)
    ctx.fill()
    ctx.save()                                                       # the sporran
    ctx.translate(0, -58)
    ctx.scale(1, 1.3)
    ctx.arc(0, 0, 7, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.92, 0.92, 0.9)
    ctx.fill()
    rounded_rect(ctx, -15, -104, 30, 40, 6)                          # the doublet
    ctx.set_source_rgb(0.06, 0.06, 0.08)
    ctx.fill()
    ctx.move_to(-15, -104)                                           # the plaid over his shoulder
    ctx.line_to(-4, -104)
    ctx.line_to(15, -70)
    ctx.line_to(6, -66)
    ctx.close_path()
    ctx.set_source_rgb(0.72, 0.08, 0.1)
    ctx.fill()
    ctx.arc(0, -112, 8, 0, TAU)                                      # head
    ctx.set_source_rgb(0.9, 0.72, 0.6)
    ctx.fill()
    rounded_rect(ctx, -12, -150, 24, 36, 10)                         # the feather bonnet
    ctx.set_source_rgb(0.04, 0.04, 0.05)
    ctx.fill()
    ctx.save()                                                       # the bag, under his left arm
    ctx.translate(16, -88)
    ctx.scale(squeeze, 1 / squeeze)
    ctx.save()
    ctx.scale(1.4, 1)
    ctx.arc(0, 0, 11, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.72, 0.08, 0.1)
    ctx.fill()
    ctx.restore()
    ctx.set_source_rgb(0.08, 0.06, 0.05)                             # three drones over the shoulder
    ctx.set_line_width(3)
    for dx, dy in ((-30, -70), (-24, -56), (-18, -48)):
        ctx.move_to(14, -92)
        ctx.line_to(14 + dx, -92 + dy)
        ctx.stroke()
        ctx.arc(14 + dx * 0.55, -92 + dy * 0.55, 2.6, 0, TAU)
        ctx.set_source_rgb(0.95, 0.92, 0.85)
        ctx.fill()
        ctx.set_source_rgb(0.08, 0.06, 0.05)
    ctx.move_to(1, -104)                                             # the chanter, held low
    ctx.line_to(4, -64)
    ctx.set_line_width(3.5)
    ctx.stroke()
    ctx.move_to(0, -110)                                             # the blowpipe
    ctx.line_to(12, -95)
    ctx.set_line_width(2.5)
    ctx.stroke()
    ctx.restore()
    x, y, w, h = WINDOW                                              # sash bars and the glass's sheen
    ctx.set_source_rgb(0.95, 0.94, 0.9)
    ctx.rectangle(x, y + h / 2 - 4, w, 8)
    ctx.rectangle(x + w / 2 - 3, y, 6, h)
    ctx.rectangle(x, y + h / 4 - 2, w, 4)
    ctx.rectangle(x, y + 3 * h / 4 - 2, w, 4)
    ctx.fill()
    g = cairo.LinearGradient(x, y, x + w, y + h)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.16)
    g.add_color_stop_rgba(0.45, 1, 1, 1, 0.0)
    g.add_color_stop_rgba(0.55, 1, 1, 1, 0.1)
    g.add_color_stop_rgba(1, 1, 1, 1, 0.0)
    ctx.rectangle(x, y, w, h)
    ctx.set_source(g)
    ctx.fill()


def agenda(ctx, t):
    """The pad on the easel, in marker: the agenda, item 19 circled in red, then ticked."""
    x, y, w, h = EASEL
    ctx.rectangle(x, y, w, h)
    ctx.set_source_rgb(0.99, 0.99, 0.97)
    ctx.fill()
    ctx.rectangle(x - 4, y - 14, w + 8, 16)                          # the clamp
    ctx.set_source_rgb(0.2, 0.2, 0.22)
    ctx.fill()
    rows = (('SESSION  OCT 19', 28, 17, True), ('AGENDA', 58, 15, True), ('17. ROOF FUND', 98, 14, False),
            ('18. CARPET (TABLED)', 128, 14, False), ('19. MOTION TO WATCH', 168, 14, False),
            ('VIZELVISION', 190, 18, False))
    for text, dy, size, header in rows:
        font(ctx, 'Nimbus Sans Narrow', size)
        ctx.set_source_rgb(*(MARKER_RED if header and dy > 40 else MARKER_BLUE))
        text_path(ctx, text, x + (w / 2 if header else 16 if not text.startswith('VIZ') else 40), y + dy,
                  tracking=0.8, align='center' if header else 'left')
        ctx.fill()
    for dy in (98, 128):                                             # the earlier items, done or tabled
        ctx.move_to(x + 150, y + dy - 12)
        ctx.line_to(x + 156, y + dy - 4)
        ctx.line_to(x + 170, y + dy - 18)
        ctx.set_source_rgb(0.2, 0.5, 0.25)
        ctx.set_line_width(2.4)
        ctx.stroke()
    p = ease_in_out(span(t, *CIRCLE))                                 # the red circle, drawn round 19
    if p > 0:
        cx, cy = x + w / 2 + 2, y + 174
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(1, 0.32)
        ctx.arc(0, 0, 92, -2.6, -2.6 + p * TAU * 1.06)
        ctx.restore()
        ctx.set_source_rgb(*MARKER_RED)
        ctx.set_line_width(3.2)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    q = span(t, *TICK)                                                # and ticked once carried
    if q > 0:
        bx, by = x + 166, y + 230
        pts = ((bx - 12, by - 10), (bx - 3, by), (bx + 18, by - 30))
        ctx.move_to(*pts[0])
        ctx.line_to(*mix(pts[0], pts[1], min(1, q * 2)))
        if q > 0.5:
            ctx.line_to(*mix(pts[1], pts[2], (q - 0.5) * 2))
        ctx.set_source_rgb(0.15, 0.55, 0.25)
        ctx.set_line_width(5)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()


def scene_parlour(ctx, t):
    zoom = 1.1 + 0.05 * ease_in_out(span(t, 0, CUT))
    ctx.save()
    ctx.translate(640, 320)
    ctx.scale(zoom, zoom)
    ctx.translate(-640, -320)
    ctx.set_source_surface(parlour(), 0, 0)
    ctx.paint()
    piper(ctx, t)
    agenda(ctx, t)
    jolt = 2.5 * math.sin(math.pi * span(t, GAVEL, GAVEL + 0.12))     # the gavel shakes the table a little
    for k, (x, style, colour, _, hair) in enumerate(ELDERS):
        elder(ctx, t, k, x, style, colour, hair)
    moderator(ctx, t)
    ctx.save()
    ctx.translate(0, -jolt)
    ctx.set_source_surface(table_cloth(), 0, 0)
    ctx.paint()
    table_things(ctx)
    ctx.restore()
    ctx.restore()


# ---------------------------------------------------------------- 2. the minutes

@lru_cache(maxsize=None)
def ledger():
    """The minutes book open on the oak table, written up long ago."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(*mix(OAK, OAK_DARK, 0.5))                     # the tabletop
    ctx.paint()
    rand = random.Random(12)
    for _ in range(80):
        y = rand.uniform(0, H)
        ctx.move_to(0, y)
        ctx.curve_to(W * 0.3, y + rand.uniform(-8, 8), W * 0.7, y + rand.uniform(-8, 8), W, y + rand.uniform(-6, 6))
        ctx.set_source_rgba(*OAK_DARK, rand.uniform(0.1, 0.35))
        ctx.set_line_width(rand.uniform(0.8, 2.2))
        ctx.stroke()
    rounded_rect(ctx, 130, 52, 1020, 622, 10)                        # the leather binding
    ctx.set_source_rgb(0.36, 0.13, 0.08)
    ctx.fill()
    for x0 in (148, 640):                                            # the two pages
        g = cairo.LinearGradient(x0, 0, x0 + 492, 0)
        if x0 < 640:
            g.add_color_stop_rgb(0, 0.86, 0.78, 0.6)
            g.add_color_stop_rgb(0.08, 0.95, 0.9, 0.76)
            g.add_color_stop_rgb(0.88, 0.94, 0.88, 0.74)
            g.add_color_stop_rgb(1, 0.72, 0.62, 0.46)
        else:
            g.add_color_stop_rgb(0, 0.72, 0.62, 0.46)
            g.add_color_stop_rgb(0.12, 0.94, 0.88, 0.74)
            g.add_color_stop_rgb(0.92, 0.95, 0.9, 0.76)
            g.add_color_stop_rgb(1, 0.86, 0.78, 0.6)
        ctx.rectangle(x0, 66, 492, 594)
        ctx.set_source(g)
        ctx.fill()
    for _ in range(90):                                              # foxing
        ctx.arc(rand.uniform(160, 1120), rand.uniform(80, 650), rand.uniform(1, 6), 0, TAU)
        ctx.set_source_rgba(0.6, 0.38, 0.18, rand.uniform(0.05, 0.22))
        ctx.fill()
    ctx.arc(330, 520, 46, 0, TAU)                                    # a coffee ring, more recent
    ctx.set_source_rgba(0.45, 0.25, 0.1, 0.28)
    ctx.set_line_width(5)
    ctx.stroke()
    for k in range(18):                                              # ruled lines
        for x0 in (190, 682):
            ctx.move_to(x0, 150 + k * 28)
            ctx.line_to(x0 + 410, 150 + k * 28)
    ctx.set_source_rgba(0.4, 0.5, 0.65, 0.18)
    ctx.set_line_width(1)
    ctx.stroke()
    hand = (0.22, 0.12, 0.06)

    def write(text, x, y, size, align='left'):
        font(ctx, 'Z003', size, bold=False)
        ctx.set_source_rgb(*hand)
        text_path(ctx, text, x, y, align=align)
        ctx.fill()

    write('Minutes', 394, 168, 70, 'center')
    write('of the Session', 394, 230, 40, 'center')
    ctx.move_to(300, 262)
    ctx.curve_to(360, 250, 430, 274, 490, 262)
    ctx.set_source_rgb(*hand)
    ctx.set_line_width(2)
    ctx.stroke()
    write('Item 18. The carpet.', 200, 342, 30)
    write('Tabled, until such time', 200, 376, 30)
    write('as the Lord should will it.', 200, 410, 30)
    write('The 19th day of October,', 690, 148, 32)
    write('in the year of our Lord 1536.', 690, 184, 32)
    write('Item 19. Moved, and seconded,', 690, 256, 32)
    write('that the Session do watch', 690, 292, 32)
    write('VizelVision.', 690, 344, 46)
    write('The motion carried.', 690, 400, 32)
    write('Unanimously.', 690, 436, 32)
    write('Attest:', 690, 590, 28)
    ctx.move_to(790, 590)                                            # the clerk's signature, a flourish
    ctx.curve_to(820, 548, 850, 610, 870, 572)
    ctx.curve_to(890, 540, 900, 600, 930, 584)
    ctx.curve_to(960, 570, 1000, 598, 1060, 576)
    ctx.set_source_rgb(*hand)
    ctx.set_line_width(2.4)
    ctx.stroke()
    write('Clerk of Session', 900, 626, 20)
    ctx.move_to(918, 192)                                            # 1536, underlined twice
    ctx.line_to(992, 190)
    ctx.move_to(920, 198)
    ctx.line_to(988, 197)
    ctx.set_line_width(1.6)
    ctx.stroke()
    # The quill and its inkwell.
    ctx.arc(1180, 120, 34, 0, TAU)
    ctx.set_source_rgb(0.08, 0.08, 0.12)
    ctx.fill()
    ctx.arc(1180, 120, 16, 0, TAU)
    ctx.set_source_rgb(0.02, 0.02, 0.04)
    ctx.fill()
    ctx.save()
    ctx.translate(1180, 120)
    ctx.rotate(2.3)
    ctx.move_to(0, 0)
    ctx.curve_to(60, -26, 170, -22, 230, 0)
    ctx.curve_to(170, 18, 60, 16, 0, 0)
    ctx.set_source_rgb(0.95, 0.94, 0.9)
    ctx.fill()
    ctx.move_to(0, 0)
    ctx.line_to(230, 0)
    ctx.set_source_rgba(0.5, 0.45, 0.4, 0.8)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.restore()
    return surface


@lru_cache(maxsize=None)
def stamp_surface():
    """PREDESTINED, in red rubber-stamp ink, a little patchy."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 180)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(*STAMP_RED)
    for inset, width in ((8, 7), (19, 2.5)):
        rounded_rect(ctx, inset, inset, 640 - 2 * inset, 180 - 2 * inset, 14)
        ctx.set_line_width(width)
        ctx.stroke()
    font(ctx, 'Nimbus Sans', 70)
    text_path(ctx, 'PREDESTINED', 320, 114, tracking=3, align='center')
    ctx.fill()
    ctx.set_operator(cairo.OPERATOR_DEST_OUT)
    rand = random.Random(8)
    for _ in range(800):
        ctx.arc(rand.uniform(0, 640), rand.uniform(0, 180), rand.uniform(0.5, 2.6), 0, TAU)
        ctx.set_source_rgba(0, 0, 0, rand.uniform(0.3, 1.0))
        ctx.fill()
    return surface


def scene_minutes(ctx, t):
    zoom = 1.0 + 0.1 * ease_in_out(span(t, CUT, WIPE[1]))
    shake = 6 * math.sin(math.pi * span(t, STAMP, STAMP + 0.1))        # the stamp jolts the table
    ctx.save()
    ctx.translate(880, 330 + shake)
    ctx.scale(zoom, zoom)
    ctx.translate(-880, -330)
    ctx.set_source_surface(ledger(), 0, 0)
    ctx.paint()
    if t >= STAMP - 0.08:
        p = span(t, STAMP - 0.08, STAMP)
        size = 1.5 - 0.5 * ease_in(p)
        ctx.save()
        ctx.translate(872, 500)
        ctx.rotate(-0.11)
        ctx.scale(size * 0.7, size * 0.7)
        ctx.set_source_surface(stamp_surface(), -320, -90)
        ctx.paint_with_alpha(0.35 + 0.6 * p)
        ctx.restore()
    ctx.restore()


# ---------------------------------------------------------------- 3. the burning bush

@lru_cache(maxsize=None)
def tartan():
    """The station's sett, woven: the stripes across, the same down, half over, and the twill."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    period = sum(width for _, width in SETT) * 2
    stripes = list(SETT) + list(reversed(SETT))                      # a sett mirrors itself
    ctx.set_source_rgb(*NAVY)
    ctx.paint()
    for vertical in (False, True):
        pos = 0
        while pos < (W if vertical else H) + period:
            for colour, width in stripes:
                if vertical:
                    ctx.rectangle(pos, 0, width, H)
                else:
                    ctx.rectangle(0, pos, W, width)
                ctx.set_source_rgba(*colour, 0.55 if vertical else 1.0)
                ctx.fill()
                pos += width
    ctx.set_source_rgba(0, 0, 0, 0.12)                               # the twill's diagonal
    for k in range(-H, W, 4):
        ctx.move_to(k, 0)
        ctx.line_to(k + H, H)
    ctx.set_line_width(1.2)
    ctx.stroke()
    return surface


def flame(ctx, x, y, h, w, lean, colour):
    ctx.move_to(x - w / 2, y)
    ctx.curve_to(x - w * 0.7, y - h * 0.45, x + lean * h * 0.3 - w * 0.2, y - h * 0.7, x + lean * h * 0.45, y - h)
    ctx.curve_to(x + lean * h * 0.2 + w * 0.3, y - h * 0.62, x + w * 0.75, y - h * 0.4, x + w / 2, y)
    ctx.close_path()
    inked(ctx, colour, 4, (4, 4))


def bush(ctx, t, cx, cy):
    """Flames in a ring round the TV's foot, rising behind it, flaring on each note."""
    flare = sum(0.4 * pulse(t, at, 0.4) for at in FLARES)
    lit = ease_out(span(t, CLOSED - 0.15, CLOSED + 0.2))
    if lit <= 0:
        return
    tongues = ((-92, 0.9, -0.5), (-66, 1.2, -0.3), (-36, 1.5, -0.12), (0, 1.75, 0.0), (36, 1.5, 0.12), (66, 1.2, 0.3),
               (92, 0.9, 0.5))
    for layer, (colour, scale_h, scale_w) in enumerate((((0.88, 0.16, 0.08), 1.0, 1.0), ((1.0, 0.5, 0.1), 0.78, 0.7),
                                                         ((1.0, 0.85, 0.2), 0.52, 0.45))):
        for k, (dx, size, lean) in enumerate(tongues):
            flick = 1 + 0.12 * math.sin(t * 11 + k * 1.7 + layer) + 0.08 * math.sin(t * 17.3 + k * 2.9)
            h = 70 * size * scale_h * flick * (1 + flare) * lit
            flame(ctx, cx + dx, cy + 62, h, 36 * scale_w * (0.8 + 0.2 * size), lean + 0.08 * math.sin(t * 6 + k),
                  colour)
    rand = random.Random(19)                                         # the bush itself, leafy, the fire in it
    for k in range(30):
        bx, by = cx + rand.uniform(-106, 106), cy + 60 + rand.uniform(-4, 24)
        ctx.arc(bx, by, rand.uniform(9, 15), 0, TAU)
        ctx.set_source_rgb(*mix((0.1, 0.32, 0.14), (0.32, 0.52, 0.2), rand.random()))
        ctx.fill_preserve()
        ctx.set_source_rgba(*INK, 0.5)
        ctx.set_line_width(1.5)
        ctx.stroke()


def ring_text(ctx, text, cx, cy, r, bottom=False):
    """Capitals round a circle, centred on its top (reading clockwise) or its bottom
    (reading left to right, upright), baseline at radius r."""
    font(ctx, 'C059', 19)
    advances = [ctx.text_extents(ch).x_advance + 1.8 for ch in text]
    sweep = sum(advances) / r
    a = math.pi + sweep / 2 if bottom else -sweep / 2
    for ch, adv in zip(text, advances):
        ctx.save()
        ctx.translate(cx, cy)
        if bottom:
            ctx.rotate(a - adv / 2 / r - math.pi)
            ctx.move_to(-adv / 2 + 1.1, r)
            a -= adv / r
        else:
            ctx.rotate(a + adv / 2 / r)
            ctx.move_to(-adv / 2 + 1.1, -r)
            a += adv / r
        ctx.text_path(ch)
        ctx.restore()
    ctx.fill()


def seal(ctx, t, cx, cy, scale):
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(scale, scale)
    ctx.translate(-cx, -cy)
    ctx.arc(cx, cy, 168, 0, TAU)                                     # the gold rim
    inked(ctx, GOLD, 6, (8, 8))
    ctx.arc(cx, cy, 154, 0, TAU)                                     # the navy band with its motto
    ctx.set_source_rgb(*NAVY)
    ctx.fill()
    ctx.set_source_rgb(*GOLD)
    ring_text(ctx, 'NEC TAMEN CONSUMEBATUR', cx, cy, 129)
    ring_text(ctx, 'AND IT WAS NOT CONSUMED', cx, cy, 145, bottom=True)
    for a in (-math.pi / 2, math.pi / 2):                            # a cross either side, between the mottoes
        ctx.save()
        ctx.translate(cx + math.sin(a) * 137, cy - math.cos(a) * 137)
        ctx.rectangle(-1.6, -8, 3.2, 16)
        ctx.rectangle(-6, -3.5, 12, 3.2)
        ctx.restore()
    ctx.fill()
    g = cairo.RadialGradient(cx, cy - 20, 10, cx, cy, 124)           # the field, lit by the fire
    g.add_color_stop_rgb(0, 1.0, 0.96, 0.84)
    g.add_color_stop_rgb(1, 0.95, 0.84, 0.62)
    ctx.arc(cx, cy, 120, 0, TAU)
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.save()
    ctx.arc(cx, cy, 118, 0, TAU)
    ctx.clip()
    bush(ctx, t, cx, cy)
    ctx.save()                                                       # the TV, in the fire, unharmed
    ctx.translate(cx, cy + 6)
    s = 0.34 * (1 + 0.03 * sum(pulse(t, at, 0.3) for at in FLARES))
    ctx.scale(s, s)
    A.draw_tv(ctx, t, 1, 0)
    ctx.restore()
    ctx.restore()
    ctx.restore()


def scene_seal(ctx, t):
    ctx.set_source_rgb(*mix(NAVY, (0, 0, 0), 0.35))
    ctx.paint()
    g = cairo.RadialGradient(640, 270, 40, 640, 270, 520)            # the fire's glow on the dark
    glow = ease_out(span(t, CLOSED - 0.1, CLOSED + 0.4)) * (0.8 + 0.2 * math.sin(t * 9))
    g.add_color_stop_rgba(0, 1.0, 0.55, 0.15, 0.32 * glow)
    g.add_color_stop_rgba(1, 1.0, 0.55, 0.15, 0.0)
    ctx.set_source(g)
    ctx.paint()
    for y0 in (0, H - 36):                                           # tartan bands, top and bottom
        ctx.save()
        ctx.rectangle(0, y0, W, 36)
        ctx.clip()
        ctx.set_source_surface(tartan(), 0, 0)
        ctx.paint()
        ctx.restore()
        ctx.rectangle(0, y0 + (36 if y0 == 0 else -3), W, 3)
        ctx.set_source_rgb(*GOLD)
        ctx.fill()
    s = back_out(span(t, *SEAL_IN))
    if s > 0:
        seal(ctx, t, 640, 262, (0.2 + 0.8 * s) * 1.12)
    neighborhood.lockup(ctx, t, CLOSED, 532, scale=0.5)
    p = ease_out(span(t, TAGLINE, TAGLINE + 0.35))
    if p > 0:
        ctx.save()
        ctx.push_group()
        font(ctx, 'C059', 34)
        ctx.set_source_rgb(0.97, 0.93, 0.82)
        text_path(ctx, 'DECENTLY AND IN ORDER', 640, 604, tracking=7, align='center')
        ctx.fill()
        font(ctx, 'C059', 17, bold=False)
        ctx.set_source_rgb(*GOLD)
        text_path(ctx, '1 CORINTHIANS 14:40   ·   CHANNEL 19', 640, 638, tracking=3, align='center')
        ctx.fill()
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(p)
        ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    if t < CUT:
        scene_parlour(ctx, t)
    elif t < WIPE[1]:
        scene_minutes(ctx, t)
    if t >= WIPE[0]:
        # The tartan comes across from the right: a band, with the seal's scene behind it.
        p = ease_in_out(span(t, *WIPE))
        edge = W - (W + 260) * p                                     # the band's leading edge
        ctx.save()
        ctx.rectangle(edge + 260, 0, W, H)
        ctx.clip()
        scene_seal(ctx, t)
        ctx.restore()
        if p < 1:
            ctx.save()
            ctx.rectangle(edge, 0, 260, H)
            ctx.clip()
            ctx.set_source_surface(tartan(), 0, 0)
            ctx.paint()
            ctx.restore()
            for x in (edge, edge + 257):
                ctx.rectangle(x, 0, 3, H)
            ctx.set_source_rgb(*GOLD)
            ctx.fill()
    vignette(ctx, 0.42)
    grain(ctx, frame, 0.3)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
