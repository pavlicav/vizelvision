"""The MNBA: men's basketball, presented the way women's sports used to be, as a plucky
little league that deserves a chance. A 1990s community-access promo shot from the
sideline of a small gym: cinderblock, a bedsheet banner (THE MNBA, MEN'S BASKETBALL),
folding bleachers with almost nobody on them (a dad with a camcorder, a man holding GO MEN!,
a mom with a thermos, a kid asleep) and a mascot with very little left to give.

No. 19, in a pink VIZELVISION jersey, a headband and tube socks, dribbles the open logo, a
bounce a note; picks the ball up and walks (the whistle: travelling, and the character
generator says THAT'S OK!); runs at the hoop and dunks, and stays up there, hanging from
the rim, sheepish, while the camera operator zooms in. One man claps once. On the closed
logo the station's end card slides in: THE MNBA ON VIZELVISION, the wordmark dropping in a
letter a sixteenth, and WE SUPPORT MEN'S SPORTS. He is still hanging from the rim.

Aired only during an NBA game (LEAGUES). Luna, very supportive: "The MNBA. It's like the
WNBA... but for men." / "Give them a chance." / "Vizzle Vision supports men's sports."
"""
import math
import random
from functools import lru_cache

import cairo

import arena
import neighborhood
from common import (INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    grain, inked, mix, pixel_text, rounded_rect, scanlines, span, text_path, vignette)

ID = 'mnba'
NAME = 'The MNBA'
KIND = 'ident'
ORDER = 35
DESCRIPTION = ('Only during the NBA: men\'s basketball as a plucky little league that deserves a chance. A '
               'community-access promo in a nearly empty gym: No. 19 dribbles the open logo, travels (THAT\'S OK!), '
               'dunks and stays hanging from the rim; one man claps once. The closed logo brings THE MNBA ON '
               'VIZELVISION and WE SUPPORT MEN\'S SPORTS. Luna.')
DURATION = 10.0
STILL_AT = 8.6
LEAGUES = ('nba',)

# Hit points (the music's too: mnba_music.py).
DRIBBLES = (0.5, 1.0, 1.5, 1.75, 2.0, 2.5)    # the ball on the floor; the last four are the open logo
LOGO_DRIBBLES = (1.5, 1.75, 2.0, 2.5)
CATCH = 2.62                                   # he picks it up
STEPS = (2.75, 2.95, 3.15, 3.35)               # and walks: four steps, no dribble
WHISTLE = 3.22                                 # travelling
RUN = (3.55, 4.05)                             # at the hoop
JUMP = (4.05, 4.42)
DUNK = 4.42                                    # through the rim; he stays up there
BOUNCES = (4.9, 5.3, 5.58, 5.76)               # the ball on the floor under the hoop
HOME_SCORES = 4.75                             # the scoreboard goes from 2 to 4
ZOOM = (4.7, 5.6)                              # the camera operator zooms in on him
LONE_CLAP = 5.95                               # one man claps, once
CLOSED = 6.15                                  # the closed logo: the end card
TAGLINE = 7.95                                 # WE SUPPORT MEN'S SPORTS
BEND = (6.6, 9.0)                              # the rim gives a little
FADE = (9.3, 9.62)
CAPTIONS = ((1.85, 3.2, 'FACT: MEN CAN ALSO PLAY BASKETBALL'), (3.32, 4.55, "TRAVELING. (THAT'S OK!)"),
            (4.75, 6.0, "THEY'RE TRYING THEIR BEST"))

# The gym, in pixels: the floor where No. 19 plays is BASE_Y, PPM pixels a metre there.
BASE_Y, PPM = 585, 140
START_X = 430                                  # where he dribbles
RIM_X, RIM_R = 1035, 32                        # the rim's centre and half-width (px)
RIM_Y = BASE_Y - 3.05 * PPM
PIVOT_X = 1068                                 # where the rim meets the backboard
BOARD = (1072, 1100, BASE_Y - 3.95 * PPM, BASE_Y - 2.88 * PPM)
WALL_Y = 432
BALL_R = 0.14
HANG_LIFT = 0.85                               # metres off the floor while he hangs
TIERS = 5
FOCUS = (RIM_X - 60, 262)                      # the zoom's centre
ZOOM_TO = 1.55

SKIN = (0.62, 0.42, 0.29)
HAIR = (0.12, 0.08, 0.06)
JERSEY = PINK
LEATHER = (0.92, 0.45, 0.14)
BLOCK = (0.93, 0.88, 0.7)
MAROON = (0.5, 0.1, 0.16)
WOOD = (0.86, 0.66, 0.42)
PLANK = (0.78, 0.6, 0.36)
CG_BLUE = (0.07, 0.14, 0.52)
MARKER = (0.12, 0.2, 0.62)

OVERLAYS = [
    {'field': 'programme', 'box': [44, 192, 208, 46], 'from': 0.3, 'to': DUNK + 0.25,
     'style': {'font': 'Quicksand', 'bold': True, 'size': 34, 'min_size': 14, 'color': [0.12, 0.2, 0.62],
               'align': 'center', 'lines': 2},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': 0.3}},
]


def font(ctx, family, size, bold=True, italic=False):
    ctx.select_font_face(family, cairo.FONT_SLANT_ITALIC if italic else cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)


def tier_y(k):
    """The top of bleacher plank k (0 the bottom)."""
    return 456 - k * 34


# ---------------------------------------------------------------- the gym (drawn once)

@lru_cache(maxsize=None)
def gym_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    rand = random.Random(35)
    # Cinderblock, painted the yellow of every school gym, with a maroon stripe.
    ctx.set_source_rgb(*BLOCK)
    ctx.paint()
    ctx.set_source_rgb(*mix(BLOCK, INK, 0.16))
    ctx.set_line_width(2)
    for row, y in enumerate(range(0, WALL_Y, 30)):
        ctx.move_to(0, y + 0.5)
        ctx.line_to(W, y + 0.5)
        for x in range(-60 if row % 2 else -30, W, 60):
            ctx.move_to(x + 0.5, y)
            ctx.line_to(x + 0.5, y + 30)
    ctx.stroke()
    for _ in range(140):                                  # scuffs
        ctx.arc(rand.uniform(0, W), rand.uniform(0, WALL_Y), rand.uniform(1, 4), 0, TAU)
        ctx.set_source_rgba(*INK, rand.uniform(0.03, 0.08))
        ctx.fill()
    ctx.rectangle(0, WALL_Y - 46, W, 24)
    ctx.set_source_rgb(*MAROON)
    ctx.fill()
    ctx.rectangle(0, WALL_Y - 22, W, 22)                  # the baseboard
    ctx.set_source_rgb(*mix(BLOCK, INK, 0.35))
    ctx.fill()
    # The floor: honey maple, planks running across, court lines.
    g = cairo.LinearGradient(0, WALL_Y, 0, H)
    g.add_color_stop_rgb(0, *mix(WOOD, INK, 0.12))
    g.add_color_stop_rgb(1, *mix(WOOD, WHITE, 0.12))
    ctx.rectangle(0, WALL_Y, W, H - WALL_Y)
    ctx.set_source(g)
    ctx.fill()
    ctx.set_line_width(1.2)
    y, gap = WALL_Y + 4, 5.0
    while y < H:
        ctx.move_to(0, y)
        ctx.line_to(W, y)
        ctx.set_source_rgba(0.4, 0.25, 0.1, 0.25)
        ctx.stroke()
        for _ in range(4):                                # board ends
            x = rand.uniform(0, W)
            ctx.move_to(x, y)
            ctx.line_to(x, y + gap)
        ctx.stroke()
        y += gap
        gap *= 1.09
    glare = cairo.RadialGradient(640, 560, 20, 640, 560, 520)  # the fluorescent lights on the varnish
    glare.add_color_stop_rgba(0, 1, 1, 0.95, 0.28)
    glare.add_color_stop_rgba(1, 1, 1, 0.95, 0)
    ctx.save()
    ctx.translate(0, 560)
    ctx.scale(1, 0.25)
    ctx.translate(0, -560)
    ctx.rectangle(0, 0, W, 2 * H)
    ctx.set_source(glare)
    ctx.fill()
    ctx.restore()
    # The paint under the hoop, and the lines.
    ctx.move_to(860, WALL_Y + 40)
    ctx.line_to(W, WALL_Y + 40)
    ctx.line_to(W, 690)
    ctx.line_to(820, 690)
    ctx.close_path()
    ctx.set_source_rgba(*MAROON, 0.85)
    ctx.fill_preserve()
    ctx.set_source_rgb(*WHITE)
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.save()
    ctx.translate(840, (WALL_Y + 40 + 690) / 2)
    ctx.scale(0.42, 1)
    ctx.arc(0, 0, (690 - WALL_Y - 40) / 2, math.pi / 2, 3 * math.pi / 2)
    ctx.restore()
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.set_line_width(4)
    ctx.move_to(0, WALL_Y + 14)                           # the far sideline
    ctx.line_to(W, WALL_Y + 14)
    ctx.stroke()
    ctx.set_line_width(8)
    ctx.move_to(0, 712)
    ctx.line_to(W, 712)
    ctx.stroke()
    ctx.set_line_width(5)
    ctx.move_to(205, WALL_Y + 14)                         # half court, and the circle
    ctx.line_to(140, 712)
    ctx.stroke()
    ctx.save()
    ctx.translate(176, 580)
    ctx.scale(1, 0.28)
    ctx.arc(0, 0, 175, 0, TAU)
    ctx.restore()
    ctx.stroke()
    # The bleachers, pulled out five rows and not needed.
    for k in range(TIERS - 1, -1, -1):
        y, x1 = tier_y(k), 640 - k * 12
        ctx.rectangle(14, y, x1 - 14, WALL_Y - 22 - y + 22 if k == 0 else 34)
        ctx.set_source_rgb(*mix(PLANK, INK, 0.55))
        ctx.fill()
        ctx.rectangle(14, y, x1 - 14, 12)
        ctx.set_source_rgb(*PLANK)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(2.5)
        ctx.stroke()
        for x in range(60, x1, 140):                      # the knee boards' bolts
            ctx.arc(x, y + 6, 2, 0, TAU)
            ctx.set_source_rgb(*mix(PLANK, INK, 0.5))
            ctx.fill()
    ctx.rectangle(10, tier_y(TIERS - 1) - 40, 6, WALL_Y - tier_y(TIERS - 1) + 40)  # the rail
    ctx.set_source_rgb(0.6, 0.62, 0.66)
    ctx.fill()
    ctx.move_to(13, tier_y(TIERS - 1) - 40)
    ctx.line_to(13, tier_y(0))
    ctx.set_line_width(2)
    ctx.set_source_rgb(*INK)
    ctx.stroke()
    # The wall: an EXIT sign, the banner, the whiteboard, a sign, the clock, the scoreboard's frame.
    rounded_rect(ctx, 26, 30, 92, 40, 4)
    ctx.set_source_rgb(0.15, 0.03, 0.03)
    ctx.fill()
    font(ctx, 'Nimbus Sans', 26)
    ctx.move_to(38, 60)
    ctx.text_path('EXIT')
    ctx.set_source_rgb(1, 0.18, 0.12)
    ctx.fill()
    banner(ctx)
    rounded_rect(ctx, 30, 140, 236, 112, 6)               # the whiteboard
    ctx.set_source_rgb(0.97, 0.97, 0.95)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.55, 0.57, 0.6)
    ctx.set_line_width(5)
    ctx.stroke()
    font(ctx, 'Quicksand', 26)
    ctx.move_to(46, 176)
    ctx.text_path('TONIGHT:')
    ctx.set_source_rgb(0.75, 0.1, 0.12)
    ctx.fill()
    ctx.move_to(44, 182)
    ctx.line_to(170, 180)
    ctx.set_line_width(2.5)
    ctx.stroke()
    ctx.save()                                            # PLEASE CHEER, on printer paper
    ctx.translate(300, 198)
    ctx.rotate(-0.06)
    ctx.rectangle(0, 0, 112, 84)
    ctx.set_source_rgb(0.99, 0.99, 0.97)
    ctx.fill_preserve()
    ctx.set_source_rgba(*INK, 0.4)
    ctx.set_line_width(1.5)
    ctx.stroke()
    for tx in (4, 92):
        ctx.rectangle(tx, -6, 18, 12)
        ctx.set_source_rgba(0.85, 0.85, 0.75, 0.85)
        ctx.fill()
    font(ctx, 'Quicksand', 19)
    ctx.set_source_rgb(*MARKER)
    for i, line in enumerate(('PLEASE', 'CHEER :)')):
        ctx.move_to(56 - ctx.text_extents(line).x_advance / 2, 36 + 26 * i)
        ctx.show_text(line)
    ctx.restore()
    ctx.new_path()
    ctx.arc(1010, 320, 26, 0, TAU)                        # the clock, always 7:40
    ctx.set_source_rgb(0.98, 0.98, 0.96)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.set_line_width(3)
    for a, r in ((TAU * (40 / 60) - math.pi / 2, 19), (TAU * (7.66 / 12) - math.pi / 2, 12)):
        ctx.move_to(1010, 320)
        ctx.line_to(1010 + r * math.cos(a), 320 + r * math.sin(a))
        ctx.stroke()
    rounded_rect(ctx, 792, 26, 200, 104, 8)               # the scoreboard
    ctx.set_source_rgb(0.08, 0.08, 0.1)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(4)
    ctx.stroke()
    pixel_text(ctx, 'HOME', 836, 40, 3, (0.95, 0.95, 0.9), align='center')
    pixel_text(ctx, 'GUEST', 948, 40, 3, (0.95, 0.95, 0.9), align='center')
    # The hoop: a steel arm from the end wall, the backboard, its padding.
    x0, x1, top, bottom = BOARD
    ctx.move_to(x1 - 4, top + 30)
    ctx.line_to(W + 10, top + 10)
    ctx.move_to(x1 - 4, bottom - 20)
    ctx.line_to(W + 10, top + 70)
    ctx.move_to(x1 + 40, top + 25)
    ctx.line_to(x1 + 80, top + 62)
    ctx.move_to(x1 + 120, top + 18)
    ctx.line_to(x1 + 150, top + 52)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(14)
    ctx.stroke_preserve()
    ctx.set_source_rgb(0.55, 0.58, 0.62)
    ctx.set_line_width(8)
    ctx.stroke()
    ctx.move_to(x0, top)
    ctx.line_to(x1, top + 6)
    ctx.line_to(x1, bottom + 6)
    ctx.line_to(x0, bottom)
    ctx.close_path()
    inked(ctx, (0.96, 0.96, 0.94), 4, (0, 0))
    ctx.rectangle(x0 + 4, bottom - 40, 14, 30)
    ctx.set_source_rgb(0.85, 0.3, 0.15)
    ctx.set_line_width(3)
    ctx.stroke()
    ctx.rectangle(x0 - 3, bottom - 2, x1 - x0 + 6, 14)    # the pad on its bottom edge
    ctx.set_source_rgb(*MAROON)
    ctx.fill()
    return surface


def banner(ctx):
    """A bedsheet, taped up, hand-painted: THE MNBA, MEN'S BASKETBALL."""
    x, y, w, h = 296, 38, 470, 140
    ctx.save()
    ctx.move_to(x, y)
    ctx.curve_to(x + w * 0.3, y + 10, x + w * 0.7, y + 10, x + w, y)
    ctx.curve_to(x + w + 6, y + h * 0.4, x + w - 4, y + h * 0.7, x + w + 2, y + h)
    ctx.curve_to(x + w * 0.65, y + h + 14, x + w * 0.35, y + h + 14, x - 2, y + h)
    ctx.curve_to(x + 4, y + h * 0.7, x - 5, y + h * 0.35, x, y)
    ctx.close_path()
    ctx.set_source_rgb(0.98, 0.97, 0.93)
    ctx.fill_preserve()
    ctx.set_source_rgba(*INK, 0.5)
    ctx.set_line_width(2)
    ctx.stroke()
    for fx in (0.3, 0.62):                                # its folds
        ctx.move_to(x + w * fx, y + 8)
        ctx.curve_to(x + w * fx + 6, y + 50, x + w * fx - 6, y + 90, x + w * fx + 2, y + h + 6)
        ctx.set_source_rgba(*INK, 0.08)
        ctx.set_line_width(5)
        ctx.stroke()
    for tx, ty in ((x - 8, y - 6), (x + w - 22, y - 6)):  # duct tape
        ctx.rectangle(tx, ty, 30, 14)
        ctx.set_source_rgb(0.62, 0.63, 0.66)
        ctx.fill()
    ctx.translate(x + w / 2, y + 74)
    ctx.rotate(-0.025)
    font(ctx, 'URW Gothic', 78)
    ctx.new_path()
    width = text_path(ctx, 'THE MNBA', 0, 0, tracking=4, align='center')
    ctx.set_source_rgb(*MARKER)
    ctx.fill()
    for dx in (-0.36, -0.1, 0.22, 0.4):                   # the paint ran a little
        ctx.rectangle(width * dx, -4, 4, 14 + 10 * abs(math.sin(dx * 40)))
    ctx.fill()
    font(ctx, 'URW Bookman', 27)
    ctx.new_path()
    text_path(ctx, "MEN'S BASKETBALL!", 0, 44, tracking=2, align='center')
    ctx.set_source_rgb(0.8, 0.12, 0.14)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the crowd (all four of them) and the mascot

def seated(ctx, x, k, shirt, skin=(0.9, 0.72, 0.58), hair=HAIR, scale=100):
    """A person sitting on bleacher plank k, centre x: returns their shoulders and head."""
    s = scale
    y = tier_y(k)
    ctx.move_to(x - 0.2 * s, y + 4)                        # legs over the plank
    ctx.line_to(x + 0.2 * s, y + 4)
    ctx.line_to(x + 0.22 * s, y + 0.28 * s)
    ctx.line_to(x - 0.22 * s, y + 0.28 * s)
    ctx.close_path()
    inked(ctx, (0.25, 0.3, 0.45), 2.5, (0, 0))
    rounded_rect(ctx, x - 0.2 * s, y - 0.52 * s, 0.4 * s, 0.56 * s, 0.1 * s)
    inked(ctx, shirt, 2.5, (0, 0))
    hx, hy = x, y - 0.66 * s
    ctx.arc(hx, hy, 0.12 * s, 0, TAU)
    inked(ctx, skin, 2.5, (0, 0))
    ctx.arc(hx, hy - 0.02 * s, 0.122 * s, math.pi * 1.02, math.pi * 1.98)
    ctx.close_path()
    ctx.set_source_rgb(*hair)
    ctx.fill()
    return (x - 0.17 * s, y - 0.45 * s), (x + 0.17 * s, y - 0.45 * s), (hx, hy)


def arm(ctx, a, b, c, colour, width=8):
    ctx.move_to(*a)
    ctx.line_to(*b)
    ctx.line_to(*c)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(width + 4)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*colour)
    ctx.set_line_width(width)
    ctx.stroke()


def crowd(ctx, t):
    skin = (0.9, 0.72, 0.58)
    # The kid, asleep on the top plank, z's rising.
    y, kx = tier_y(4), 520
    for lx in (kx, kx + 8):                                # legs, sneakers
        rounded_rect(ctx, lx - 22, y - 9 - (lx - kx), 30, 8, 4)
        inked(ctx, (0.25, 0.3, 0.45), 2, (0, 0))
    rounded_rect(ctx, kx + 8, y - 22, 52, 22, 9)
    inked(ctx, (0.98, 0.55, 0.2), 2.5, (0, 0))
    ctx.arc(kx + 72, y - 14, 12, 0, TAU)
    inked(ctx, skin, 2.5, (0, 0))
    ctx.arc(kx + 72, y - 16, 12.5, math.pi * 1.1, math.pi * 1.9)
    ctx.close_path()
    ctx.set_source_rgb(0.4, 0.22, 0.1)
    ctx.fill()
    for k in range(3):
        u = ((t * 0.45 + k / 3) % 1)
        font(ctx, 'Nimbus Sans', 12 + 10 * u)
        ctx.move_to(kx + 88 + 26 * u + 5 * math.sin(u * 7), y - 22 - 46 * u)
        ctx.set_source_rgba(*INK, 0.8 * math.sin(math.pi * u))
        ctx.show_text('z')
    # Mom, with a thermos, sipping now and then.
    ls, rs, (hx, hy) = seated(ctx, 486, 2, (0.55, 0.3, 0.6), skin=(0.95, 0.8, 0.68), hair=(0.55, 0.32, 0.15))
    sip = max(math.sin(math.pi * span(t, 2.8, 3.5)), math.sin(math.pi * span(t, 7.3, 8.0)))
    cup = (rs[0] + 2, rs[1] + 16 - 30 * sip)
    arm(ctx, rs, (rs[0] + 14, rs[1] + 22 - 6 * sip), cup, (0.55, 0.3, 0.6))
    ctx.rectangle(cup[0] - 7 - 8 * sip, cup[1] - 16, 13, 16)
    inked(ctx, (0.75, 0.2, 0.2), 2, (0, 0))
    ctx.arc(hx - 4, hy + 2, 2, 0, TAU)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    # Dad, recording all of it.
    ls, rs, (hx, hy) = seated(ctx, 150, 1, (0.2, 0.42, 0.7), hair=(0.35, 0.3, 0.28))
    arm(ctx, ls, (ls[0] + 4, ls[1] + 18), (hx + 4, hy + 6), (0.2, 0.42, 0.7))
    arm(ctx, rs, (rs[0] + 10, rs[1] + 16), (hx + 16, hy + 6), (0.2, 0.42, 0.7))
    rounded_rect(ctx, hx - 4, hy - 13, 42, 24, 4)           # the camcorder
    inked(ctx, (0.15, 0.15, 0.17), 2.5, (0, 0))
    ctx.arc(hx + 40, hy - 1, 8, 0, TAU)
    inked(ctx, (0.25, 0.25, 0.3), 2, (0, 0))
    if (t % 1.0) < 0.6:
        ctx.arc(hx + 8, hy - 8, 2.5, 0, TAU)
        ctx.set_source_rgb(1, 0.15, 0.1)
        ctx.fill()
    # The man with the sign. He lowers it to clap, once.
    ls, rs, (hx, hy) = seated(ctx, 340, 0, (0.95, 0.75, 0.2), skin=(0.78, 0.56, 0.4))
    down = ease_in_out(span(t, LONE_CLAP - 0.3, LONE_CLAP - 0.08)) * (1 - ease_in_out(span(t, LONE_CLAP + 0.35, LONE_CLAP + 0.75)))
    shake = 4 * math.sin(t * 9) * (1 - down)
    sy = hy - 64 + 70 * down
    clap = math.cos(math.pi * min(1.0, abs(t - LONE_CLAP) / 0.12)) * 0.5 + 0.5 if abs(t - LONE_CLAP) < 0.12 else 0
    if down < 0.5:
        arm(ctx, ls, (ls[0] - 14, ls[1] - 26 + 40 * down), (hx - 30 + shake, sy + 20), (0.95, 0.75, 0.2))
        arm(ctx, rs, (rs[0] + 14, rs[1] - 26 + 40 * down), (hx + 30 + shake, sy + 20), (0.95, 0.75, 0.2))
    else:
        apart = 16 * (1 - clap)
        arm(ctx, ls, (ls[0] - 4, ls[1] + 14), (hx - apart, hy + 34), (0.95, 0.75, 0.2))
        arm(ctx, rs, (rs[0] + 4, rs[1] + 14), (hx + apart, hy + 34), (0.95, 0.75, 0.2))
    ctx.save()                                             # GO MEN!, on a box flap, in marker
    ctx.translate(hx + shake, sy + 10 * down)
    ctx.rotate(-0.05 + 0.04 * math.sin(t * 4.5))
    if down > 0.5:
        ctx.translate(0, 34)
        ctx.rotate(0.3)
    rounded_rect(ctx, -62, -30, 124, 54, 3)
    inked(ctx, (0.8, 0.64, 0.42), 2.5, (0, 0))
    font(ctx, 'Quicksand', 30)
    ctx.new_path()
    text_path(ctx, 'GO MEN!', 0, 8, align='center')
    ctx.set_source_rgb(*MARKER)
    ctx.fill()
    ctx.restore()


def mascot(ctx, t):
    """The mascot, a foam basketball with a man inside, giving what he has left: a foam
    finger that rises an inch on each note of the logo, and a little more for the dunk."""
    s = 105
    x = 712 + 3 * math.sin(t * 1.3)
    feet = 522
    lift = sum(14 * math.exp(-max(0.0, t - n) / 0.12) * (t >= n) for n in LOGO_DRIBBLES)
    lift += 34 * math.sin(math.pi * span(t, DUNK + 0.1, DUNK + 0.9))
    for side in (-1, 1):                                   # legs in sweatpants, big shoes
        ctx.move_to(x + side * 0.12 * s, feet - 0.8 * s)
        ctx.line_to(x + side * 0.14 * s, feet - 0.05 * s)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(0.17 * s + 4)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*MAROON)
        ctx.set_line_width(0.17 * s)
        ctx.stroke()
        rounded_rect(ctx, x + side * 0.14 * s - 0.13 * s, feet - 0.09 * s, 0.26 * s, 0.12 * s, 0.05 * s)
        inked(ctx, WHITE, 2.5, (0, 0))
    rounded_rect(ctx, x - 0.3 * s, feet - 1.5 * s, 0.6 * s, 0.78 * s, 0.14 * s)
    inked(ctx, MAROON, 3, (0, 0))
    font(ctx, 'URW Gothic', 0.22 * s)
    ctx.new_path()
    text_path(ctx, 'MNBA', x, feet - 1.05 * s, align='center')
    ctx.set_source_rgb(*YELLOW)
    ctx.fill()
    ctx.move_to(x - 0.28 * s, feet - 1.36 * s)             # the slack arm
    ctx.line_to(x - 0.34 * s, feet - 0.86 * s)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(0.13 * s + 4)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*MAROON)
    ctx.set_line_width(0.13 * s)
    ctx.stroke()
    fx, fy = x + 0.42 * s, feet - 1.05 * s - lift          # the foam finger
    ctx.move_to(x + 0.26 * s, feet - 1.36 * s)
    ctx.line_to(fx, fy + 0.12 * s)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(0.13 * s + 4)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*MAROON)
    ctx.set_line_width(0.13 * s)
    ctx.stroke()
    ctx.save()
    ctx.translate(fx, fy)
    ctx.rotate(0.35 - 0.012 * lift)
    rounded_rect(ctx, -0.13 * s, -0.12 * s, 0.26 * s, 0.3 * s, 0.07 * s)
    inked(ctx, YELLOW, 2.5, (0, 0))
    rounded_rect(ctx, -0.05 * s, -0.42 * s, 0.1 * s, 0.33 * s, 0.05 * s)
    inked(ctx, YELLOW, 2.5, (0, 0))
    font(ctx, 'Nimbus Sans', 0.12 * s)
    ctx.move_to(-0.1 * s, 0.1 * s)
    ctx.set_source_rgb(*MAROON)
    ctx.show_text('#1')
    ctx.restore()
    hx, hy = x, feet - 1.92 * s                            # the head: a foam ball, eyelids half down
    ctx.new_path()
    ctx.arc(hx, hy, 0.45 * s, 0, TAU)
    inked(ctx, LEATHER, 3.5, (0, 0))
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(2.5)
    ctx.move_to(hx - 0.45 * s, hy)
    ctx.line_to(hx + 0.45 * s, hy)
    ctx.stroke()
    ctx.arc(hx, hy, 0.45 * s, -0.5, 0.5)
    ctx.stroke()
    for side in (-1, 1):
        ex, ey = hx + side * 0.15 * s, hy - 0.1 * s
        ctx.arc(ex, ey, 0.09 * s, 0, TAU)
        inked(ctx, WHITE, 2.5, (0, 0))
        ctx.arc(ex, ey + 0.03 * s, 0.04 * s, 0, TAU)
        ctx.set_source_rgb(*INK)
        ctx.fill()
        ctx.arc(ex, ey, 0.092 * s, math.pi, TAU)           # the lids, heavy
        ctx.close_path()
        ctx.set_source_rgb(*mix(LEATHER, INK, 0.2))
        ctx.fill()
    ctx.move_to(hx - 0.08 * s, hy + 0.17 * s)
    ctx.line_to(hx + 0.08 * s, hy + 0.17 * s)
    ctx.set_line_width(3)
    ctx.set_source_rgb(*INK)
    ctx.stroke()


def scoreboard(ctx, t):
    home = '4' if t >= HOME_SCORES else '2'
    arena.seven_segment(ctx, home, 824, 62, 50, (1.0, 0.22, 0.12))
    arena.seven_segment(ctx, '0', 936, 62, 50, (1.0, 0.22, 0.12))


# ---------------------------------------------------------------- No. 19

POSES = {
    # metres: x right, y up from the floor between his feet; facing the camera.
    'dribble': {'pelvis': (0, 0.92), 'neck': (0, 1.5), 'head': (0, 1.72), 'ls': (-0.24, 1.45), 'rs': (0.24, 1.45),
                'le': (-0.36, 1.18), 'lh': (-0.3, 0.98), 're': (0.42, 1.16), 'rh': (0.48, 0.92),
                'lk': (-0.18, 0.5), 'rk': (0.2, 0.5), 'lf': (-0.24, 0.04), 'rf': (0.26, 0.04)},
    'hold': {'pelvis': (0, 0.95), 'neck': (0, 1.52), 'head': (0, 1.74), 'ls': (-0.24, 1.47), 'rs': (0.24, 1.47),
             'le': (-0.34, 1.2), 'lh': (-0.14, 1.22), 're': (0.34, 1.2), 'rh': (0.14, 1.22),
             'lk': (-0.15, 0.5), 'rk': (0.16, 0.5), 'lf': (-0.18, 0.04), 'rf': (0.2, 0.04)},
    'jump': {'pelvis': (0, 1.0), 'neck': (0, 1.56), 'head': (0, 1.78), 'ls': (-0.24, 1.52), 'rs': (0.24, 1.52),
             'le': (-0.28, 1.9), 'lh': (-0.12, 2.25), 're': (0.28, 1.9), 'rh': (0.12, 2.25),
             'lk': (-0.22, 0.68), 'rk': (0.18, 0.6), 'lf': (-0.16, 0.32), 'rf': (0.2, 0.22)},
    'hang': {'pelvis': (0, 0.95), 'neck': (0, 1.5), 'head': (0, 1.72), 'ls': (-0.22, 1.48), 'rs': (0.22, 1.48),
             'le': (-0.21, 1.85), 'lh': (-0.1, 2.2), 're': (0.21, 1.85), 'rh': (0.1, 2.2),
             'lk': (-0.12, 0.52), 'rk': (0.14, 0.5), 'lf': (-0.12, 0.06), 'rf': (0.16, 0.05)},
}
KEYS = ((0.0, 'dribble'), (2.52, 'dribble'), (2.62, 'hold'), (JUMP[0], 'hold'), (JUMP[0] + 0.18, 'jump'),
        (DUNK, 'jump'), (DUNK + 0.14, 'hang'))


def pose(t):
    for (t0, a), (t1, b) in zip(KEYS, KEYS[1:]):
        if t < t1:
            k = ease_in_out(span(t, t0, t1))
            return {j: (POSES[a][j][0] + (POSES[b][j][0] - POSES[a][j][0]) * k,
                        POSES[a][j][1] + (POSES[b][j][1] - POSES[a][j][1]) * k) for j in POSES[a]}
    return dict(POSES[KEYS[-1][1]])


def step_legs(p, side, amount):
    """Lift one leg (side 'l' or 'r') by amount (0..1): knee up and in, foot off the floor."""
    kx, ky = p[side + 'k']
    fx, fy = p[side + 'f']
    p[side + 'k'] = (kx * (1 - 0.3 * amount), ky + 0.16 * amount)
    p[side + 'f'] = (fx * (1 - 0.25 * amount), fy + 0.24 * amount)


def ball_bounce(t, contacts, top):
    """Height (m) of a ball bouncing between contacts, rising to top at each midpoint."""
    for a, b in zip(contacts, contacts[1:]):
        if a <= t <= b:
            return BALL_R + (top - BALL_R) * math.sin(math.pi * (t - a) / (b - a))
    return None


def rim_bend(t):
    return 0.15 * ease_in_out(span(t, *BEND))


def rim_front(t):
    """The middle of the rim's near edge, where he hangs on, as it gives."""
    a = rim_bend(t)
    dx, dy = RIM_X - PIVOT_X, RIM_R * 0.2
    return PIVOT_X + dx * math.cos(a) + dy * math.sin(a), RIM_Y - dx * math.sin(a) + dy * math.cos(a)


def root(t):
    """Where his feet are (screen x of his centre, metres off the floor), and a swing (rad)."""
    if t < CATCH:
        return START_X + 5 * math.sin(t * 2.2), 0.0, 0.0
    step = 0.32 * PPM
    if t < STEPS[-1] + 0.2:
        x = START_X
        for when in STEPS:
            x += step * ease_in_out(span(t, when, when + 0.2))
        return x, 0.0, 0.0
    walked = START_X + 4 * step
    takeoff = RIM_X - 1.0 * PPM
    hx, _ = rim_front(t)
    if t < JUMP[0]:
        return walked + (takeoff - walked) * span(t, STEPS[-1] + 0.2, JUMP[0]), 0.0, 0.0
    if t < DUNK:
        u = span(t, *JUMP)
        return takeoff + (hx - takeoff) * ease_out(u, 2), HANG_LIFT * ease_out(u, 2) + 0.55 * math.sin(math.pi * u) * 0.6, 0.0
    since = t - DUNK
    swing = 0.24 * math.sin(TAU * since / 1.25) * math.exp(-since / 1.6) + 0.03 * math.sin(t * 2.3)
    _, hy = rim_front(t)
    return hx, HANG_LIFT - (hy - RIM_Y - RIM_R * 0.2) / PPM, swing


def ball(t):
    """The ball: (screen x, metres up) or None while it's held (drawn with his hands)."""
    if t < CATCH:
        h = ball_bounce(t, (0.0,) + DRIBBLES, 0.95)
        if h is None:                                     # from the last bounce up into his hands
            h = BALL_R + (1.22 - BALL_R) * math.sin(math.pi / 2 * span(t, DRIBBLES[-1], CATCH))
        return START_X + 5 * math.sin(t * 2.2) + 0.48 * PPM * (1 - span(t, DRIBBLES[-1], CATCH)), h
    if t < DUNK - 0.04:
        return None
    if t < DUNK + 0.1:                                    # down through the rim
        u = span(t, DUNK - 0.04, DUNK + 0.1)
        return RIM_X - 4, 3.3 - 0.75 * u
    if t < BOUNCES[0]:
        u = span(t, DUNK + 0.1, BOUNCES[0])
        return RIM_X - 4 - 10 * u, 2.55 - (2.55 - BALL_R) * u * u
    x0 = RIM_X - 14
    roll = 60 * span(t, BOUNCES[0], BOUNCES[-1]) + 90 * ease_out(span(t, BOUNCES[-1], BOUNCES[-1] + 1.4))
    h = ball_bounce(t, BOUNCES, 0.0)
    if h is not None:
        k = BOUNCES.index(max(b for b in BOUNCES if b <= t))
        h = BALL_R + (h - BALL_R) * (0.85, 0.42, 0.2)[k]
    return x0 - roll, h if h is not None else BALL_R


def draw_ball(ctx, x, y, r, spin=0.0):
    ctx.arc(x, y, r, 0, TAU)
    inked(ctx, LEATHER, 3, (0, 0))
    ctx.save()
    ctx.arc(x, y, r, 0, TAU)
    ctx.clip()
    ctx.translate(x, y)
    ctx.rotate(spin)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(max(1.5, r * 0.09))
    ctx.move_to(-r, 0)
    ctx.line_to(r, 0)
    ctx.move_to(0, -r)
    ctx.line_to(0, r)
    ctx.stroke()
    for side in (-1, 1):
        ctx.arc(side * r * 1.25, 0, r * 0.85, 0, TAU)
        ctx.stroke()
    ctx.restore()


def limb(ctx, points, colour, width):
    ctx.move_to(*points[0])
    for pt in points[1:]:
        ctx.line_to(*pt)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(width + 6)
    ctx.stroke_preserve()
    ctx.set_source_rgb(*colour)
    ctx.set_line_width(width)
    ctx.stroke()


def player(ctx, t):
    p = pose(t)
    x0, lift, swing = root(t)
    # The legs: stepping (travelling), then running.
    if CATCH <= t < STEPS[-1] + 0.2:
        for k, when in enumerate(STEPS):
            step_legs(p, 'lr'[k % 2], math.sin(math.pi * span(t, when, when + 0.2)))
    elif STEPS[-1] + 0.2 <= t < JUMP[0]:
        phase = (t - STEPS[-1] - 0.2) / 0.11
        step_legs(p, 'lr'[int(phase) % 2], abs(math.sin(math.pi * phase)) * 1.2)
    if t >= DUNK:                                          # a little kicking while he hangs
        p['lf'] = (p['lf'][0] + 0.05 * math.sin(t * 5.1), p['lf'][1] + 0.03 * math.sin(t * 3.7))
        p['rf'] = (p['rf'][0] + 0.05 * math.sin(t * 4.3 + 1), p['rf'][1] + 0.03 * math.sin(t * 4.9))
    held = ball(t) is None
    # While dribbling, his right hand rides the top of the ball.
    if t < CATCH:
        bx, bh = ball(t)
        p['rh'] = (0.48, max(0.78, bh + BALL_R + 0.02))
    s = PPM

    def at(j):
        x, y = p[j]
        return x0 + x * s, BASE_Y - (y + lift) * s

    j = {k: at(k) for k in p}
    ctx.save()
    if swing:
        hx, hy = (j['lh'][0] + j['rh'][0]) / 2, (j['lh'][1] + j['rh'][1]) / 2
        ctx.translate(hx, hy)
        ctx.rotate(swing)
        ctx.translate(-hx, -hy)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    for side in ('l', 'r'):                                # legs, tube socks, high-tops
        hip = (x0 + (-0.12 if side == 'l' else 0.12) * s, BASE_Y - (p['pelvis'][1] + lift) * s)
        knee, foot = j[side + 'k'], j[side + 'f']
        limb(ctx, (hip, knee, foot), SKIN, 0.13 * s)
        sock_top = (foot[0] + (knee[0] - foot[0]) * 0.7, foot[1] + (knee[1] - foot[1]) * 0.7)
        ctx.move_to(foot[0], foot[1] - 0.05 * s)
        ctx.line_to(*sock_top)
        ctx.set_source_rgb(*WHITE)
        ctx.set_line_width(0.135 * s)
        ctx.stroke()
        for k, colour in ((0.78, PINK), (0.9, TEAL)):
            a = (foot[0] + (knee[0] - foot[0]) * (k * 0.7), foot[1] + (knee[1] - foot[1]) * (k * 0.7))
            b = (foot[0] + (knee[0] - foot[0]) * (k * 0.7 + 0.06), foot[1] + (knee[1] - foot[1]) * (k * 0.7 + 0.06))
            ctx.move_to(*a)
            ctx.line_to(*b)
            ctx.set_source_rgb(*colour)
            ctx.set_line_width(0.135 * s)
            ctx.stroke()
        ctx.save()
        ctx.translate(foot[0], foot[1])
        rounded_rect(ctx, -0.1 * s, -0.12 * s, 0.22 * s, 0.15 * s, 0.05 * s)
        ctx.restore()
        inked(ctx, WHITE, 3, (0, 0))
    pl, pr = (x0 - 0.23 * s, j['pelvis'][1] - 0.06 * s), (x0 + 0.23 * s, j['pelvis'][1] - 0.06 * s)
    lk, rk = j['lk'], j['rk']                              # the shorts, baggy, to the knee
    ctx.move_to(*pl)
    ctx.line_to(*pr)
    ctx.line_to(rk[0] + 0.11 * s, rk[1] - 0.04 * s)
    ctx.line_to(rk[0] - 0.12 * s, rk[1] - 0.02 * s)
    ctx.line_to(x0, j['pelvis'][1] + 0.12 * s)
    ctx.line_to(lk[0] + 0.12 * s, lk[1] - 0.02 * s)
    ctx.line_to(lk[0] - 0.11 * s, lk[1] - 0.04 * s)
    ctx.close_path()
    inked(ctx, JERSEY, 3, (0, 0))
    ctx.move_to(rk[0] + 0.1 * s, rk[1] - 0.09 * s)
    ctx.line_to(pr[0] + 0.01 * s, pr[1] + 0.06 * s)
    ctx.set_source_rgb(*WHITE)
    ctx.set_line_width(0.03 * s)
    ctx.stroke()
    ls, rs = j['ls'], j['rs']
    for side in ('l', 'r'):                                # arms, wristbands
        limb(ctx, (j[side + 's'], j[side + 'e'], j[side + 'h']), SKIN, 0.1 * s)
        e, h_ = j[side + 'e'], j[side + 'h']
        ctx.move_to(e[0] + (h_[0] - e[0]) * 0.62, e[1] + (h_[1] - e[1]) * 0.62)
        ctx.line_to(e[0] + (h_[0] - e[0]) * 0.82, e[1] + (h_[1] - e[1]) * 0.82)
        ctx.set_source_rgb(*WHITE)
        ctx.set_line_width(0.11 * s)
        ctx.stroke()
    ctx.move_to(ls[0] + 0.06 * s, ls[1] - 0.03 * s)        # the jersey
    ctx.curve_to(j['neck'][0] - 0.06 * s, j['neck'][1] + 0.1 * s, j['neck'][0] + 0.06 * s, j['neck'][1] + 0.1 * s,
                 rs[0] - 0.06 * s, rs[1] - 0.03 * s)
    ctx.curve_to(rs[0] - 0.02 * s, rs[1] + 0.15 * s, rs[0] - 0.01 * s, rs[1] + 0.3 * s, pr[0] + 0.01 * s, pr[1] + 0.04 * s)
    ctx.line_to(pl[0] - 0.01 * s, pl[1] + 0.04 * s)
    ctx.curve_to(ls[0] + 0.01 * s, ls[1] + 0.3 * s, ls[0] + 0.02 * s, ls[1] + 0.15 * s, ls[0] + 0.06 * s, ls[1] - 0.03 * s)
    ctx.close_path()
    inked(ctx, JERSEY, 3, (0, 0))
    cx = (ls[0] + rs[0]) / 2
    ctx.save()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(0.065 * s)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', cx, ls[1] + 0.15 * s, tracking=0.003 * s, align='center')
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.set_font_size(0.26 * s)
    ctx.new_path()
    text_path(ctx, '19', cx, ls[1] + 0.42 * s, tracking=0.01 * s, align='center')
    path = ctx.copy_path()
    ctx.set_source_rgb(*TEAL)
    ctx.set_line_width(0.024 * s)
    ctx.stroke()
    ctx.append_path(path)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.restore()
    head(ctx, t, j, s)
    if held and t < DUNK:                                  # the ball, in both hands
        bx = (j['lh'][0] + j['rh'][0]) / 2
        by = min(j['lh'][1], j['rh'][1]) - (0.06 * s if t > JUMP[0] + 0.1 else -0.02 * s)
        draw_ball(ctx, bx, by, BALL_R * s, spin=0.4)
    for side in ('l', 'r'):                                # hands
        hx, hy = j[side + 'h']
        ctx.arc(hx, hy, 0.055 * s, 0, TAU)
        inked(ctx, SKIN, 2.5, (0, 0))
    ctx.restore()


def head(ctx, t, j, s):
    nx, ny = j['neck']
    limb(ctx, ((nx, ny), (nx, ny - 0.08 * s)), SKIN, 0.1 * s)
    hx, hy = j['head']
    r = 0.15 * s
    for side in (-1, 1):                                   # ears
        ctx.arc(hx + side * r * 0.98, hy + 0.01 * s, 0.035 * s, 0, TAU)
        inked(ctx, SKIN, 2.5, (0, 0))
    ctx.arc(hx, hy, r, 0, TAU)
    inked(ctx, SKIN, 3, (0, 0))
    ctx.arc(hx, hy - 0.01 * s, r * 1.02, math.pi * 1.05, math.pi * 1.95)   # short hair
    ctx.close_path()
    ctx.set_source_rgb(*HAIR)
    ctx.fill()
    ctx.save()                                             # the headband
    ctx.arc(hx, hy, r, 0, TAU)
    ctx.clip()
    ctx.rectangle(hx - r, hy - r * 0.62, 2 * r, r * 0.3)
    ctx.set_source_rgb(*PINK)
    ctx.fill()
    ctx.rectangle(hx - r, hy - r * 0.5, 2 * r, r * 0.06)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.restore()
    sheepish = span(t, DUNK + 0.4, DUNK + 0.8)
    look = 0.02 * s * math.sin(t * 0.9) if t < DUNK else 0.0
    for side in (-1, 1):                                   # eyes
        ex, ey = hx + side * 0.055 * s + look, hy + 0.01 * s
        ctx.arc(ex, ey, 0.018 * s, 0, TAU)
        ctx.set_source_rgb(*INK)
        ctx.fill()
        tilt = (0.25 * side) if sheepish < 0.5 else (-0.35 if side < 0 else 0.15)
        bump = -0.015 * s * sheepish if side < 0 else 0
        ctx.move_to(ex - 0.03 * s, ey - 0.05 * s + bump - tilt * 0.02 * s)
        ctx.line_to(ex + 0.03 * s, ey - 0.05 * s + bump + tilt * 0.02 * s)
        ctx.set_line_width(0.014 * s)
        ctx.stroke()
    ctx.set_line_width(0.014 * s)
    if sheepish > 0.5:                                     # a wobbly little smile
        ctx.move_to(hx - 0.045 * s, hy + 0.075 * s)
        ctx.curve_to(hx - 0.02 * s, hy + 0.09 * s, hx + 0.01 * s, hy + 0.065 * s, hx + 0.05 * s, hy + 0.08 * s)
        ctx.stroke()
        for side in (-1, 1):
            ctx.arc(hx + side * 0.085 * s, hy + 0.05 * s, 0.022 * s, 0, TAU)
            ctx.set_source_rgba(1, 0.4, 0.4, 0.5)
            ctx.fill()
        drop = span(t, DUNK + 1.0, DUNK + 2.2)             # and a bead of sweat
        if 0 < drop < 1:
            dx, dy = hx + 0.13 * s, hy - 0.06 * s + 0.08 * s * drop
            ctx.move_to(dx, dy - 0.03 * s)
            ctx.curve_to(dx + 0.02 * s, dy, dx + 0.02 * s, dy + 0.02 * s, dx, dy + 0.02 * s)
            ctx.curve_to(dx - 0.02 * s, dy + 0.02 * s, dx - 0.02 * s, dy, dx, dy - 0.03 * s)
            ctx.set_source_rgb(0.6, 0.85, 1.0)
            ctx.fill()
    else:                                                  # concentrating
        ctx.set_source_rgb(*INK)
        ctx.move_to(hx - 0.04 * s, hy + 0.08 * s)
        ctx.line_to(hx + 0.04 * s, hy + 0.08 * s)
        ctx.stroke()


# ---------------------------------------------------------------- the rim and the net

def rim(ctx, t, front):
    a = rim_bend(t)
    ctx.save()
    ctx.translate(PIVOT_X, RIM_Y)
    ctx.rotate(-a)
    ctx.translate(-PIVOT_X, -RIM_Y)
    ctx.save()
    ctx.translate(RIM_X, RIM_Y)
    ctx.scale(1, 0.2)
    if front:
        ctx.arc(0, 0, RIM_R, 0, math.pi)
    else:
        ctx.arc(0, 0, RIM_R, math.pi, TAU)
        ctx.move_to(RIM_R, 0)
        ctx.line_to(PIVOT_X - RIM_X, 0)
    ctx.restore()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(9)
    ctx.stroke_preserve()
    ctx.set_source_rgb(0.95, 0.35, 0.1)
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.restore()


def net(ctx, t):
    a = rim_bend(t)
    whip = math.sin(math.pi * span(t, DUNK - 0.02, DUNK + 0.35)) * 12
    ctx.save()
    ctx.translate(PIVOT_X, RIM_Y)
    ctx.rotate(-a)
    ctx.translate(-PIVOT_X, -RIM_Y)
    top, bottom, length = RIM_R, RIM_R * 0.55, 0.45 * PPM + whip
    sway = 2 * math.sin(t * 3)
    cols = 7
    ctx.set_source_rgba(0.98, 0.98, 0.98, 0.9)
    ctx.set_line_width(2)
    for i in range(cols + 1):
        u = i / cols
        x0 = RIM_X - top + 2 * top * u
        x1 = RIM_X - bottom + 2 * bottom * ((u + 0.5 / cols) % 1.0 if i < cols else 1.0) + sway
        ctx.move_to(x0, RIM_Y + 2)
        ctx.line_to(x1, RIM_Y + length)
        x2 = RIM_X - bottom + 2 * bottom * max(0.0, u - 0.5 / cols) + sway
        ctx.move_to(x0, RIM_Y + 2)
        ctx.line_to(x2, RIM_Y + length)
    ctx.stroke()
    for k in range(1, 4):
        y = RIM_Y + length * k / 4
        w = top + (bottom - top) * k / 4
        ctx.move_to(RIM_X - w + sway * k / 4, y)
        ctx.line_to(RIM_X + w + sway * k / 4, y)
    ctx.stroke()
    ctx.restore()


# ---------------------------------------------------------------- the character generator

def caption(ctx, t, start, end, text):
    p = span(t, start, start + 0.18)
    out = span(t, end - 0.15, end)
    if p <= 0 or out >= 1:
        return
    font(ctx, 'Nimbus Sans Narrow', 40)
    width = ctx.text_extents(text).x_advance + 56
    x, y, h = 52, 626, 60
    ctx.push_group()
    ctx.save()
    ctx.rectangle(x, y - 10, width * ease_out(p), h + 20)
    ctx.clip()
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, *mix(CG_BLUE, WHITE, 0.25))
    g.add_color_stop_rgb(0.5, *CG_BLUE)
    g.add_color_stop_rgb(1, *mix(CG_BLUE, INK, 0.4))
    ctx.rectangle(x, y, width, h)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(x, y, width, 3)
    ctx.set_source_rgb(*YELLOW)
    ctx.fill()
    ctx.move_to(x + 31, y + 45)
    ctx.text_path(text)
    ctx.set_source_rgba(0, 0, 0, 0.85)
    ctx.fill()
    ctx.move_to(x + 28, y + 42)
    ctx.text_path(text)
    ctx.set_source_rgb(1.0, 0.92, 0.3)
    ctx.fill()
    ctx.restore()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(1 - out)


def bug(ctx, t):
    pixel_text(ctx, 'CH 19  COMMUNITY SPORTS', 1236, 690, 2, (0.95, 0.95, 0.95), align='right',
               shadow=(1, 1, (0.1, 0.1, 0.1)))


@lru_cache(maxsize=None)
def panel_surface():
    """The end card's panel: a nineties character-generator gradient with a grid."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 840, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 840, H)
    g.add_color_stop_rgb(0, 0.32, 0.08, 0.5)
    g.add_color_stop_rgb(0.6, 0.1, 0.16, 0.6)
    g.add_color_stop_rgb(1, 0.06, 0.32, 0.62)
    ctx.rectangle(0, 0, 810, H)
    ctx.set_source(g)
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.07)
    ctx.set_line_width(2)
    for x in range(0, 810, 45):
        ctx.move_to(x, 0)
        ctx.line_to(x, H)
    for y in range(0, H, 45):
        ctx.move_to(0, y)
        ctx.line_to(810, y)
    ctx.stroke()
    ctx.rectangle(810, 0, 14, H)
    ctx.set_source_rgb(*PINK)
    ctx.fill()
    ctx.rectangle(824, 0, 8, H)
    ctx.set_source_rgb(*YELLOW)
    ctx.fill()
    ctx.rectangle(832, 0, 8, H)
    ctx.set_source_rgb(*TEAL)
    ctx.fill()
    return surface


def end_card(ctx, t):
    slide = ease_out(span(t, CLOSED - 0.35, CLOSED - 0.02))
    if slide <= 0:
        return
    cx = 405
    ctx.save()
    ctx.translate(-840 * (1 - slide), 0)
    ctx.set_source_surface(panel_surface(), 0, 0)
    ctx.paint()
    pop = back_out(span(t, CLOSED - 0.15, CLOSED + 0.2))
    if pop > 0:                                            # THE MNBA
        ctx.save()
        ctx.translate(cx, 200)
        ctx.scale(pop, pop)
        font(ctx, 'URW Gothic', 112)
        ctx.new_path()
        text_path(ctx, 'THE MNBA', 0, 0, tracking=6, align='center')
        inked(ctx, YELLOW, 6, (7, 7))
        ctx.restore()
    on = span(t, CLOSED + 0.15, CLOSED + 0.4)
    if on > 0:
        ctx.save()
        font(ctx, 'Nimbus Sans', 30)
        ctx.new_path()
        text_path(ctx, 'ON', cx, 268, tracking=8, align='center')
        ctx.set_source_rgba(1, 1, 1, on)
        ctx.fill()
        ctx.restore()
    ctx.save()                                             # the wordmark, a letter a sixteenth
    ctx.translate(cx - W / 2, 0)
    neighborhood.lockup(ctx, t, CLOSED + 0.1, 392, scale=0.54)
    ctx.restore()
    rib = back_out(span(t, TAGLINE, TAGLINE + 0.3))
    if rib > 0:                                            # WE SUPPORT MEN'S SPORTS
        ctx.save()
        ctx.translate(cx, 506)
        ctx.scale(rib, rib)
        ctx.rotate(-0.03)
        font(ctx, 'Nimbus Sans Narrow', 42)
        width = ctx.text_extents("WE SUPPORT MEN'S SPORTS").x_advance + 70
        ctx.move_to(-width / 2 - 26, -28)
        ctx.line_to(width / 2 + 26, -28)
        ctx.line_to(width / 2 + 8, 0)
        ctx.line_to(width / 2 + 26, 28)
        ctx.line_to(-width / 2 - 26, 28)
        ctx.line_to(-width / 2 - 8, 0)
        ctx.close_path()
        inked(ctx, PINK, 5, (6, 6))
        ctx.new_path()
        text_path(ctx, "WE SUPPORT MEN'S SPORTS", 0, 15, tracking=1.5, align='center')
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
        ctx.restore()
    ctx.restore()


# ---------------------------------------------------------------- the frame

def zoom(t):
    return 1 + (ZOOM_TO - 1) * ease_in_out(span(t, *ZOOM)) * (1 - ease_in_out(span(t, CLOSED - 0.4, CLOSED + 0.05)))


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.save()
    k = zoom(t)                                            # the camera operator, and his hands
    shake_x = 1.6 * math.sin(t * 1.7) + 0.8 * math.sin(t * 4.3 + 1)
    shake_y = 1.2 * math.sin(t * 2.1 + 2) + 0.6 * math.sin(t * 5.7)
    ctx.translate(FOCUS[0] + shake_x, FOCUS[1] + shake_y)
    ctx.scale(k, k)
    ctx.translate(-FOCUS[0], -FOCUS[1])
    ctx.set_source_surface(gym_surface(), 0, 0)
    ctx.paint()
    scoreboard(ctx, t)
    crowd(ctx, t)
    mascot(ctx, t)
    rim(ctx, t, front=False)
    b = ball(t)
    spin = -t * 6
    if b and b[1] > 2.5:                                   # through the hoop: behind the net
        draw_ball(ctx, b[0], BASE_Y - b[1] * PPM, BALL_R * PPM, spin)
    net(ctx, t)
    if b and b[1] <= 2.5:
        bx, bh = b
        if t >= DUNK:                                      # its shadow on the floor
            ctx.save()
            ctx.translate(bx, BASE_Y)
            ctx.scale(1, 0.25)
            ctx.arc(0, 0, BALL_R * PPM * (1.1 - 0.15 * min(bh, 2.0)), 0, TAU)
            ctx.restore()
            ctx.set_source_rgba(0, 0, 0, 0.25)
            ctx.fill()
        draw_ball(ctx, bx, BASE_Y - bh * PPM, BALL_R * PPM, spin)
    x0, lift, _ = root(t)
    ctx.save()                                             # his shadow
    ctx.translate(x0, BASE_Y)
    ctx.scale(1, 0.18)
    ctx.arc(0, 0, 0.42 * PPM * (1 - 0.3 * min(1.0, lift)), 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, 0.3 - 0.15 * min(1.0, lift))
    ctx.fill()
    player(ctx, t)
    rim(ctx, t, front=True)
    ctx.restore()
    for start, end, text in CAPTIONS:
        caption(ctx, t, start, end, text)
    end_card(ctx, t)
    bug(ctx, t)
    scanlines(ctx, 0.07, 3)
    vignette(ctx, 0.35)
    grain(ctx, frame, 0.3)
    opening = 1 - ease_out(span(t, 0.0, 0.3))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
