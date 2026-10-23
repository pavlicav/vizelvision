"""VizelVision Church (Non-Denominational): a Sunday at the big church in the converted
warehouse, from the back of the room, with love. Everything All Are Welcome isn't: no stone,
no organ, no robes; haze, moving heads, a drum shield and an LED wall.

1. The room in the dark before the service: black ductwork, the band on the risers in blue
   (the worship leader in a beanie, an acoustic with the capo up at the seventh fret), fake
   fiddle-leaf figs in white planters, the drum kit behind its plexiglass shield. The wall
   counts down the way it does every week: "service begins in" 00:03, 00:02, 00:01, under
   the lowercase "vizelvision." with the station's TV for its full stop.
2. 00:00 is the open logo: four kick hits, the CO2 jets firing on each, the moving heads
   snapping white, and a lyric slide a hit on the stock backgrounds (a mountain sunrise, a
   wave, a man on a summit with his arms up, a nebula): "you never" / "go to" /
   "commercial" / "oh oh oh". The crowd's phones go up.
3. Pastor Brayden jogs out: fitted heather v-neck, ripped skinny jeans, chunky white
   sneakers, a headset mic, Oakleys pushed up on his head and a forty-ounce tumbler. The
   wall cuts to him close up (IMAG, LEAD PASTOR on the lower third), the side pillars cycle
   the announcements (STEAK & SCRIPTURE, men's night; the PARKING LOT CAMPUS and its lifted
   truck with the station's decal; CAMPUSES: CHANTILLY · ASHBURN · ONLINE; TEXT 19 TO GIVE):
   "It's not a religion." / "It's a relationship." / "With channel nineteen."
4. On "nineteen" the closed logo, up a key as worship songs go: the wall resolves to the
   wordmark over CHURCH and ONE CHANNEL. MANY CAMPUSES., all four jets, confetti, every hand
   in the room up. "Come on, church!"

Airs any time (no league). Apollo, Pastor Brayden.
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (A, CYAN, INK, ORANGE, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out,  # noqa: F401
                    ease_out, font, glint, grain, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'non-denom'
NAME = 'VizelVision Church'
KIND = 'ident'
ORDER = 36
DESCRIPTION = ('VizelVision as a non-denominational megachurch in a converted warehouse: the countdown on the LED '
               'wall, CO2 jets and lyric slides on the open logo ("you never go to commercial, oh oh oh"), Pastor '
               'Brayden in a v-neck and Oakleys on the IMAG, "It\'s not a religion, it\'s a relationship. With '
               'channel nineteen.", the wordmark on the wall and every hand up on the closed logo. Apollo.')
DURATION = 10.0
STILL_AT = 8.6
OVERLAYS = []

# Hit points (the music's too: non_denom_music.py).
FADE_IN = (0.0, 0.35)
COUNT = (0.0, 0.5, 1.0)                           # the countdown: 00:03, 00:02, 00:01
HITS = (1.5, 1.75, 2.0, 2.5)                      # the open logo: kick, CO2, a lyric slide each
WALK = (2.62, 3.2)                                # the pastor jogs out to centre stage
IMAG = 2.85                                       # the wall cuts to him close up
LINES = (3.1, 4.55, 5.95, 8.0)                    # the voice lines start (script-non-denom.json)
SPEECH = ((3.1, 4.19), (4.55, 5.59), (5.95, 6.98), (8.0, 9.03))   # when his mouth moves
SLIDES = (3.0, 4.45, 5.75)                        # the side pillars change slides
POINT = (4.6, 5.7)                                # "relationship": a hand to the sky
BUILD = (6.15, 7.15)                              # the snare build
WHITEOUT = (6.9, 7.15)                            # the wall goes white...
CLOSED = 7.15                                     # ...and the closed logo: the wordmark
HANDS = (6.75, 7.4)                               # the room's hands go up
JETS_CLOSED = (7.15, 8.15)                        # the CO2 again, on the first and last notes
CHURCH = 7.75                                     # CHURCH sets under the wordmark
TAGLINE = 8.2                                     # ONE CHANNEL. MANY CAMPUSES.
FADE = (9.4, 9.65)

# The room.
WALL = (250, 66, 780, 330)                        # the LED wall: x, y, w, h
PILLARS = ((62, 100, 150, 262), (1068, 100, 150, 262))
FIXTURES = (140, 300, 460, 640, 820, 980, 1140)   # moving heads on the truss
TRUSS_Y = 50
STAGE_BACK, STAGE_FRONT, STAGE_LIP = 412, 522, 560
JETS = (262, 520, 760, 1018)
PASTOR_X = (1230, 664)                            # from offstage right to centre
LEADER_X, BASS_X, KEYS_X = 452, 872, 318

NIGHT = (0.016, 0.016, 0.05)
BLUE = (0.16, 0.28, 1.0)
VIOLET = (0.52, 0.18, 1.0)
AMBER = (1.0, 0.68, 0.32)
HEATHER = (0.56, 0.57, 0.61)
DENIM = (0.27, 0.4, 0.62)
SKIN = (0.88, 0.67, 0.53)
BEARD = (0.38, 0.23, 0.12)
MUSTARD = (0.86, 0.62, 0.16)
LYRICS = ('you never', 'go to', 'commercial', 'oh oh oh')


def stage_x(x, y):
    """The stage's perspective: x at the front edge, slid towards the centre at depth y."""
    k = (y - STAGE_BACK) / (STAGE_FRONT - STAGE_BACK)
    return 640 + (x - 640) * (0.86 + 0.14 * k)


# ---------------------------------------------------------------- light: what colour the room is
def wash(t):
    """The stage colour: blue before, white on the hits, warm for the pastor, the station's at the end."""
    if t < HITS[0]:
        return mix(BLUE, VIOLET, 0.5 + 0.5 * math.sin(t * 2.0))
    if t < WALK[0]:
        k = sum(pulse(t, h, 0.3) for h in HITS)
        base = (PINK, TEAL, YELLOW, WHITE)[sum(1 for h in HITS if t >= h) - 1]
        return mix(base, WHITE, min(1.0, k))
    if t < WHITEOUT[0]:
        return mix(VIOLET, AMBER, ease_out(span(t, WALK[0], WALK[1])) * 0.55)
    if t < CLOSED:
        return mix(VIOLET, WHITE, span(t, *WHITEOUT))
    return (PINK, TEAL, YELLOW, CYAN)[int((t - CLOSED) / 0.5) % 4]


def hit_flash(t):
    return max([pulse(t, h, 0.28) for h in HITS] + [pulse(t, CLOSED, 0.4) * 1.2, pulse(t, JETS_CLOSED[1], 0.3) * 0.7])


# ---------------------------------------------------------------- the room (drawn once)
@lru_cache(maxsize=None)
def room_surface():
    """The warehouse in the dark: ductwork, the truss, the stage and its risers, the planters."""
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(s)
    ctx.set_source_rgb(*NIGHT)
    ctx.paint()
    # A spiral duct and bar joists across the ceiling, barely there.
    for y, r in ((14, 15), (88, 9)):
        g = cairo.LinearGradient(0, y - r, 0, y + r)
        g.add_color_stop_rgb(0, 0.09, 0.09, 0.13)
        g.add_color_stop_rgb(0.5, 0.05, 0.05, 0.08)
        g.add_color_stop_rgb(1, 0.02, 0.02, 0.04)
        ctx.rectangle(0, y - r, W, 2 * r)
        ctx.set_source(g)
        ctx.fill()
        ctx.set_source_rgba(0.13, 0.13, 0.18, 0.5)
        ctx.set_line_width(1)
        for x in range(-20, W + 20, 26):
            ctx.move_to(x, y - r)
            ctx.line_to(x + 8, y + r)
        ctx.stroke()
    # The truss: two chords and the zigzag.
    ctx.set_source_rgb(0.16, 0.16, 0.2)
    ctx.set_line_width(3)
    for y in (TRUSS_Y - 9, TRUSS_Y + 1):
        ctx.move_to(40, y)
        ctx.line_to(W - 40, y)
    ctx.stroke()
    ctx.set_line_width(1.5)
    for x in range(40, W - 40, 16):
        ctx.move_to(x, TRUSS_Y - 9)
        ctx.line_to(x + 8, TRUSS_Y + 1)
        ctx.line_to(x + 16, TRUSS_Y - 9)
    ctx.stroke()
    # Speaker arrays hanging either side of the wall.
    for x in (226, 1040):
        for k in range(6):
            rounded_rect(ctx, x, 70 + k * 30 + k * k * 0.6, 24, 27, 3)
            ctx.set_source_rgb(0.05, 0.05, 0.07)
            ctx.fill()
    # The stage deck, its front face, an LED strip along the lip.
    ctx.move_to(stage_x(80, STAGE_BACK), STAGE_BACK)
    ctx.line_to(stage_x(1200, STAGE_BACK), STAGE_BACK)
    ctx.line_to(1200, STAGE_FRONT)
    ctx.line_to(80, STAGE_FRONT)
    ctx.close_path()
    g = cairo.LinearGradient(0, STAGE_BACK, 0, STAGE_FRONT)
    g.add_color_stop_rgb(0, 0.05, 0.05, 0.09)
    g.add_color_stop_rgb(1, 0.1, 0.1, 0.15)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(80, STAGE_FRONT, 1120, STAGE_LIP - STAGE_FRONT)
    ctx.set_source_rgb(0.025, 0.025, 0.04)
    ctx.fill()
    # Risers: the drums in the middle, keys stage left.
    for x0, x1, y0, h in ((548, 732, 398, 22), (250, 400, 418, 14), (800, 940, 418, 14)):
        ctx.rectangle(x0, y0, x1 - x0, h)
        ctx.set_source_rgb(0.03, 0.03, 0.05)
        ctx.fill()
        ctx.rectangle(x0, y0, x1 - x0, 2)
        ctx.set_source_rgb(0.14, 0.14, 0.2)
        ctx.fill()
    # Wedges along the lip.
    for x in (398, 640, 884):
        ctx.move_to(x - 34, STAGE_FRONT - 2)
        ctx.line_to(x + 34, STAGE_FRONT - 2)
        ctx.line_to(x + 26, STAGE_FRONT - 22)
        ctx.line_to(x - 26, STAGE_FRONT - 14)
        ctx.close_path()
        ctx.set_source_rgb(0.04, 0.04, 0.06)
        ctx.fill()
    # The CO2 cannons: little black boxes on the lip.
    for x in JETS:
        ctx.rectangle(x - 14, STAGE_FRONT - 16, 28, 16)
        ctx.set_source_rgb(0.06, 0.06, 0.08)
        ctx.fill()
        ctx.arc(x, STAGE_FRONT - 16, 5, math.pi, 0)
        ctx.set_source_rgb(0.15, 0.15, 0.2)
        ctx.fill()
    return s


def plant(ctx, x, foot, height, lit, seed):
    """A fake fiddle-leaf fig in a white cylinder planter (everyone has them)."""
    rand = random.Random(seed)
    pot_h, pot_w = height * 0.24, height * 0.2
    g = cairo.LinearGradient(x - pot_w / 2, 0, x + pot_w / 2, 0)
    g.add_color_stop_rgb(0, *mix((0.75, 0.75, 0.78), lit, 0.15))
    g.add_color_stop_rgb(0.6, *mix((0.92, 0.92, 0.94), lit, 0.2))
    g.add_color_stop_rgb(1, 0.5, 0.5, 0.55)
    ctx.rectangle(x - pot_w / 2, foot - pot_h, pot_w, pot_h)
    ctx.set_source(g)
    ctx.fill()
    ctx.set_source_rgb(0.25, 0.17, 0.1)
    ctx.set_line_width(4)
    ctx.move_to(x, foot - pot_h)
    ctx.curve_to(x - 6, foot - height * 0.5, x + 8, foot - height * 0.7, x + 2, foot - height * 0.9)
    ctx.stroke()
    for k in range(17):
        a = rand.uniform(-1.4, 1.4)
        ly = foot - pot_h - rand.uniform(0.25, 0.75) * (height - pot_h)
        lx = x + math.sin(a) * rand.uniform(4, 22)
        ctx.save()
        ctx.translate(lx, ly)
        ctx.rotate(a * 0.9 + rand.uniform(-0.3, 0.3))
        ctx.scale(1, 1.5)
        ctx.arc(0, -10, 11, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*mix((0.08, 0.26, 0.1), lit, 0.18 + 0.1 * rand.random()))
        ctx.fill()


@lru_cache(maxsize=None)
def pixel_grid():
    """The LED wall's pixels: a fine dark lattice over whatever it shows."""
    w, h = WALL[2], WALL[3]
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    ctx = cairo.Context(s)
    ctx.set_source_rgba(0, 0, 0, 0.32)
    for x in range(0, w, 5):
        ctx.rectangle(x, 0, 1, h)
    for y in range(0, h, 5):
        ctx.rectangle(0, y, w, 1)
    ctx.fill()
    # The panel seams.
    ctx.set_source_rgba(0, 0, 0, 0.55)
    for x in range(0, w, 130):
        ctx.rectangle(x, 0, 2, h)
    for y in range(0, h, 110):
        ctx.rectangle(0, y, w, 2)
    ctx.fill()
    return s


# ---------------------------------------------------------------- the wall's content
def lower(ctx, text, x, y, size, alpha=1.0, colour=WHITE, weight=True, tracking=0.0, align='center'):
    font(ctx, 'Quicksand', size, bold=weight)
    ctx.set_source_rgba(*colour, alpha)
    text_path(ctx, text, x, y, tracking=tracking, align=align)
    ctx.fill()


def tv_dot(ctx, t, x, y, s):
    """The station's TV, small: the full stop of the lowercase logo."""
    if s <= 0.001:
        return
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    A.draw_tv(ctx, t, 1, 0)
    ctx.restore()


def brand(ctx, t, x, y, size, alpha=1.0):
    """"vizelvision." in the church's lowercase, the TV for its full stop."""
    font(ctx, 'Quicksand', size, bold=True)
    width = ctx.text_extents('vizelvision').x_advance
    ctx.push_group()
    lower(ctx, 'vizelvision', x - width / 2 - size * 0.3, y, size)
    tv_dot(ctx, t, x + width / 2 + size * 0.22, y - size * 0.22, size / 330)
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(alpha)


def countdown(ctx, t, w, h):
    g = cairo.LinearGradient(0, 0, w, h)
    g.add_color_stop_rgb(0, 0.08, 0.04, 0.22)
    g.add_color_stop_rgb(1, 0.02, 0.1, 0.3)
    ctx.set_source(g)
    ctx.paint()
    for k in range(3):                                       # slow soft blobs, the loop's motion background
        bx = w * (0.25 + 0.25 * k) + 60 * math.sin(t * 0.7 + k * 2)
        by = h * 0.5 + 40 * math.cos(t * 0.5 + k)
        r = cairo.RadialGradient(bx, by, 0, bx, by, 220)
        r.add_color_stop_rgba(0, *(PINK, TEAL, VIOLET)[k], 0.35)
        r.add_color_stop_rgba(1, 0, 0, 0, 0)
        ctx.set_source(r)
        ctx.paint()
    brand(ctx, t, w / 2, 70, 34)
    lower(ctx, 'service begins in', w / 2, 150, 26, 0.85, weight=False, tracking=6)
    left = max(0, 3 - int(t / 0.5))
    lower(ctx, f'00:0{left}', w / 2, 262, 110)


def mountains(ctx, w, h, layers):
    for k, (colour, base, amp, seed) in enumerate(layers):
        rand = random.Random(seed)
        ctx.move_to(0, h)
        x = 0
        y = base
        while x <= w:
            ctx.line_to(x, y)
            x += rand.uniform(30, 70)
            y = base - rand.uniform(0, amp)
        ctx.line_to(w, h)
        ctx.close_path()
        ctx.set_source_rgb(*colour)
        ctx.fill()


def lyric_slide(ctx, t, w, h, k):
    """The stock backgrounds every church has, and a line of the song."""
    if k == 0:                                               # a mountain sunrise
        g = cairo.LinearGradient(0, 0, 0, h)
        for stop, c in ((0, (0.2, 0.1, 0.4)), (0.5, (0.95, 0.4, 0.45)), (0.8, (1.0, 0.75, 0.4))):
            g.add_color_stop_rgb(stop, *c)
        ctx.set_source(g)
        ctx.paint()
        sun = cairo.RadialGradient(w * 0.5, h * 0.72, 10, w * 0.5, h * 0.72, 180)
        sun.add_color_stop_rgba(0, 1, 0.95, 0.75, 1)
        sun.add_color_stop_rgba(1, 1, 0.8, 0.5, 0)
        ctx.set_source(sun)
        ctx.paint()
        mountains(ctx, w, h, (((0.45, 0.25, 0.45), h * 0.78, 70, 3), ((0.22, 0.12, 0.3), h * 0.9, 50, 4)))
    elif k == 1:                                             # a wave
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgb(0, 0.0, 0.3, 0.42)
        g.add_color_stop_rgb(1, 0.0, 0.55, 0.6)
        ctx.set_source(g)
        ctx.paint()
        ctx.move_to(0, h * 0.95)
        ctx.curve_to(w * 0.3, h * 0.9, w * 0.45, h * 0.25, w * 0.7, h * 0.3)
        ctx.curve_to(w * 0.85, h * 0.33, w * 0.9, h * 0.5, w * 0.78, h * 0.55)
        ctx.curve_to(w * 0.7, h * 0.58, w * 0.66, h * 0.48, w * 0.72, h * 0.45)
        ctx.curve_to(w * 0.6, h * 0.5, w * 0.62, h * 0.75, w, h * 0.8)
        ctx.line_to(w, h)
        ctx.line_to(0, h)
        ctx.close_path()
        g = cairo.LinearGradient(0, h * 0.3, 0, h)
        g.add_color_stop_rgb(0, 0.85, 0.97, 1.0)
        g.add_color_stop_rgb(0.3, 0.1, 0.6, 0.7)
        g.add_color_stop_rgb(1, 0.0, 0.25, 0.4)
        ctx.set_source(g)
        ctx.fill()
    elif k == 2:                                             # a man on a summit, arms up
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgb(0, 0.98, 0.62, 0.2)
        g.add_color_stop_rgb(1, 0.98, 0.9, 0.55)
        ctx.set_source(g)
        ctx.paint()
        ctx.move_to(0, h)
        ctx.line_to(w * 0.3, h * 0.82)
        ctx.line_to(w * 0.62, h * 0.62)
        ctx.line_to(w * 0.75, h * 0.7)
        ctx.line_to(w, h * 0.86)
        ctx.line_to(w, h)
        ctx.close_path()
        ctx.set_source_rgb(0.18, 0.1, 0.06)
        ctx.fill()
        mx, my = w * 0.62, h * 0.62                          # him
        ctx.set_source_rgb(0.18, 0.1, 0.06)
        ctx.set_line_width(4)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(mx, my - 2)
        ctx.line_to(mx, my - 24)
        ctx.move_to(mx, my - 22)
        ctx.line_to(mx - 12, my - 38)
        ctx.move_to(mx, my - 22)
        ctx.line_to(mx + 12, my - 38)
        ctx.stroke()
        ctx.arc(mx, my - 30, 5, 0, TAU)
        ctx.fill()
    else:                                                    # a nebula
        ctx.set_source_rgb(0.05, 0.01, 0.12)
        ctx.paint()
        for cx, cy, r, c in ((w * 0.35, h * 0.4, 260, PINK), (w * 0.65, h * 0.6, 240, TEAL), (w * 0.5, h * 0.3, 150, VIOLET)):
            g = cairo.RadialGradient(cx, cy, 0, cx, cy, r)
            g.add_color_stop_rgba(0, *c, 0.65)
            g.add_color_stop_rgba(1, 0, 0, 0, 0)
            ctx.set_source(g)
            ctx.paint()
        rand = random.Random(11)
        for _ in range(140):
            ctx.arc(rand.uniform(0, w), rand.uniform(0, h), rand.uniform(0.6, 1.8), 0, TAU)
            ctx.set_source_rgba(1, 1, 1, rand.uniform(0.4, 1))
            ctx.fill()
    text = LYRICS[k]
    size = 96 if k == 3 else 80
    pop = back_out(span(t, HITS[k], HITS[k] + 0.18))
    ctx.save()
    ctx.translate(w / 2, h / 2 + size * 0.32)
    ctx.scale(0.85 + 0.15 * pop, 0.85 + 0.15 * pop)
    font(ctx, 'Quicksand', size, bold=True)
    ctx.set_source_rgba(0, 0, 0, 0.35)
    text_path(ctx, text, 3, 4, tracking=2, align='center')
    ctx.fill()
    lower(ctx, text, 0, 0, size, tracking=2)
    ctx.restore()


def mouth_open(t):
    for a, b in SPEECH:
        if a <= t <= b:
            syl = 0.5 + 0.5 * math.sin((t - a) * TAU * 4.1) * math.sin((t - a) * TAU * 1.3 + 0.7)
            return 0.15 + 0.85 * abs(syl)
    return 0.0


def imag(ctx, t, w, h):
    """IMAG: the pastor on the wall, close up, a lens's worth of soft focus behind him."""
    g = cairo.LinearGradient(0, 0, 0, h)
    g.add_color_stop_rgb(0, 0.12, 0.06, 0.2)
    g.add_color_stop_rgb(1, 0.25, 0.1, 0.18)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(5)
    for _ in range(18):                                      # the bokeh of the moving heads behind him
        bx, by, r = rand.uniform(0, w), rand.uniform(0, h * 0.7), rand.uniform(14, 40)
        c = rand.choice((AMBER, VIOLET, PINK, BLUE))
        ctx.arc(bx + 6 * math.sin(t + bx), by, r, 0, TAU)
        ctx.set_source_rgba(*c, 0.22)
        ctx.fill()
    talk = mouth_open(t)
    nod = 4 * math.sin(t * 5.3) * (1 if talk else 0.3)
    point = ease_in_out(span(t, POINT[0], POINT[0] + 0.3)) * (1 - ease_in_out(span(t, POINT[1] - 0.3, POINT[1])))
    cx, cy = w * 0.5 + 4 * math.sin(t * 0.8), 150 + nod * 0.4
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(0.035 * math.sin(t * 1.7))
    # Shoulders and the v-neck, the chain and its cross.
    ctx.move_to(-230, 200)
    ctx.curve_to(-210, 100, -120, 96, -58, 82)
    ctx.line_to(58, 82)
    ctx.curve_to(120, 96, 210, 100, 230, 200)
    ctx.close_path()
    g = cairo.LinearGradient(-200, 80, 200, 200)
    g.add_color_stop_rgb(0, *mix(HEATHER, AMBER, 0.15))
    g.add_color_stop_rgb(1, *mix(HEATHER, (0.2, 0.2, 0.25), 0.4))
    ctx.set_source(g)
    ctx.fill()
    ctx.move_to(-44, 80)
    ctx.line_to(0, 168)
    ctx.line_to(44, 80)
    ctx.close_path()
    ctx.set_source_rgb(*mix(SKIN, (0.5, 0.3, 0.25), 0.1))
    ctx.fill()
    ctx.set_source_rgb(0.85, 0.82, 0.75)
    ctx.set_line_width(1.6)
    ctx.move_to(-30, 82)
    ctx.curve_to(-22, 128, 22, 128, 30, 82)
    ctx.stroke()
    ctx.set_line_width(3)
    ctx.move_to(0, 120)
    ctx.line_to(0, 140)
    ctx.move_to(-7, 127)
    ctx.line_to(7, 127)
    ctx.stroke()
    # A sleeve tattoo coming down the arm: a few lines of it.
    ctx.set_source_rgba(0.15, 0.2, 0.35, 0.6)
    ctx.set_line_width(2)
    for k in range(4):
        ctx.arc(-200 + k * 6, 170 + k * 6, 12 + k * 3, 0.2, 2.2)
        ctx.stroke()
    # The neck, the head.
    ctx.rectangle(-30, 30, 60, 60)
    ctx.set_source_rgb(*mix(SKIN, (0.4, 0.25, 0.2), 0.15))
    ctx.fill()
    ctx.save()
    ctx.scale(1, 1.18)
    ctx.arc(0, -10, 62, 0, TAU)
    ctx.restore()
    g = cairo.RadialGradient(-20, -40, 10, 0, -10, 90)
    g.add_color_stop_rgb(0, *mix(SKIN, WHITE, 0.12))
    g.add_color_stop_rgb(1, *mix(SKIN, (0.5, 0.25, 0.2), 0.25))
    ctx.set_source(g)
    ctx.fill()
    for sx in (-1, 1):                                       # ears
        ctx.save()
        ctx.scale(1, 1.4)
        ctx.arc(sx * 60, -6, 11, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*mix(SKIN, (0.6, 0.3, 0.25), 0.2))
        ctx.fill()
    # The beard: trimmed, along the jaw.
    ctx.move_to(-60, -6)
    ctx.curve_to(-58, 50, -30, 74, 0, 76)
    ctx.curve_to(30, 74, 58, 50, 60, -6)
    ctx.curve_to(50, 20, 34, 30, 22, 26)
    ctx.curve_to(10, 22, -10, 22, -22, 26)
    ctx.curve_to(-34, 30, -50, 20, -60, -6)
    ctx.close_path()
    ctx.set_source_rgb(*BEARD)
    ctx.fill()
    # The mouth: open as he talks.
    ctx.save()
    ctx.translate(0, 40)
    ctx.scale(1, 0.25 + 0.9 * talk)
    ctx.arc(0, 0, 14, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.25, 0.08, 0.08)
    ctx.fill()
    ctx.move_to(-16, 34)
    ctx.curve_to(-6, 30, 6, 30, 16, 34)
    ctx.set_source_rgb(*mix(BEARD, (0.1, 0.06, 0.03), 0.4))
    ctx.set_line_width(5)
    ctx.stroke()
    # Nose, brows, eyes (sincere).
    ctx.move_to(-2, -20)
    ctx.curve_to(-8, 4, -10, 12, 0, 14)
    ctx.set_source_rgba(0.5, 0.28, 0.22, 0.6)
    ctx.set_line_width(3)
    ctx.stroke()
    lift = 4 * point + 3 * talk
    for sx in (-1, 1):
        ctx.move_to(sx * 14, -34 - lift)
        ctx.curve_to(sx * 26, -40 - lift, sx * 36, -38 - lift, sx * 44, -32 - lift)
        ctx.set_source_rgb(*BEARD)
        ctx.set_line_width(6)
        ctx.stroke()
        ctx.save()
        ctx.translate(sx * 27, -18)
        ctx.scale(1, 0.75)
        ctx.arc(0, 0, 9, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(0.98, 0.97, 0.94)
        ctx.fill()
        ctx.arc(sx * 27 - 2, -18, 5.5, 0, TAU)
        ctx.set_source_rgb(0.22, 0.32, 0.45)
        ctx.fill()
        ctx.arc(sx * 27 - 3, -20, 1.8, 0, TAU)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
    # Hair: a fade at the sides, a textured quiff on top.
    ctx.move_to(-62, -30)
    ctx.curve_to(-66, -90, -20, -112, 20, -106)
    ctx.curve_to(52, -104, 72, -80, 62, -30)
    ctx.curve_to(56, -56, 40, -66, 20, -70)
    ctx.curve_to(0, -74, -40, -70, -62, -30)
    ctx.close_path()
    ctx.set_source_rgb(0.3, 0.18, 0.09)
    ctx.fill()
    ctx.set_source_rgba(0.5, 0.33, 0.18, 0.6)
    ctx.set_line_width(2)
    for k in range(9):
        ctx.move_to(-40 + k * 9, -72)
        ctx.curve_to(-38 + k * 9, -90, -30 + k * 10, -100, -26 + k * 10, -104)
        ctx.stroke()
    # The Oakleys, pushed up: a black wraparound frame, the prizm lens.
    ctx.save()
    ctx.translate(0, -86)
    ctx.move_to(-66, 8)
    ctx.curve_to(-50, -14, 50, -14, 66, 8)
    ctx.curve_to(50, 2, 20, 4, 0, 6)
    ctx.curve_to(-20, 4, -50, 2, -66, 8)
    ctx.close_path()
    g = cairo.LinearGradient(-66, 0, 66, 0)
    for stop, c in ((0, (0.55, 0.1, 0.55)), (0.35, (1.0, 0.45, 0.15)), (0.65, (0.2, 0.7, 0.8)), (1, (0.45, 0.1, 0.6))):
        g.add_color_stop_rgb(stop, *c)
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.set_source_rgb(0.05, 0.05, 0.06)
    ctx.set_line_width(5)
    ctx.stroke()
    ctx.restore()
    # The headset mic: over the ear, along the cheek, to the corner of the mouth.
    ctx.set_source_rgb(0.86, 0.72, 0.58)
    ctx.set_line_width(2.5)
    ctx.move_to(62, -14)
    ctx.curve_to(66, 8, 52, 30, 22, 40)
    ctx.stroke()
    ctx.arc(20, 40, 4, 0, TAU)
    ctx.fill()
    ctx.restore()
    # His hand up on "relationship": an open palm, the worship hand.
    if point > 0:
        hx, hy = w * 0.5 + 180, h + 60 - 230 * point
        skin = mix(SKIN, (0.4, 0.25, 0.2), 0.1)
        ctx.set_source_rgb(*mix(HEATHER, AMBER, 0.1))
        ctx.move_to(hx - 26, hy + 62)
        ctx.line_to(hx + 26, hy + 62)
        ctx.line_to(hx + 34, hy + 260)
        ctx.line_to(hx - 34, hy + 260)
        ctx.close_path()
        ctx.fill()
        ctx.set_source_rgb(*skin)
        ctx.save()
        ctx.translate(hx, hy)
        ctx.rotate(0.12)
        rounded_rect(ctx, -24, 0, 48, 66, 18)                # the palm
        ctx.fill()
        for k, (fx, length, lean) in enumerate(((-17, 44, -0.12), (-6, 52, -0.04), (6, 54, 0.03), (17, 46, 0.1))):
            ctx.save()
            ctx.translate(fx, 6)
            ctx.rotate(lean)
            rounded_rect(ctx, -5.5, -length, 11, length + 6, 5.5)
            ctx.restore()
            ctx.fill()
        ctx.save()                                           # the thumb, out to the side
        ctx.translate(-22, 38)
        ctx.rotate(-0.9)
        rounded_rect(ctx, -6, -34, 12, 40, 6)
        ctx.restore()
        ctx.fill()
        ctx.set_source_rgba(0.55, 0.32, 0.25, 0.5)           # palm creases
        ctx.set_line_width(1.5)
        ctx.move_to(-14, 30)
        ctx.curve_to(-4, 38, 8, 36, 18, 26)
        ctx.stroke()
        ctx.restore()
    # The lower third.
    lt = ease_out(span(t, 3.15, 3.45)) * (1 - ease_in_out(span(t, 4.45, 4.7)))
    if lt > 0:
        ctx.save()
        ctx.translate(-260 * (1 - lt), 0)
        ctx.rectangle(24, h - 160, 300, 52)
        ctx.set_source_rgba(0, 0, 0, 0.55 * lt)
        ctx.fill()
        ctx.rectangle(24, h - 160, 5, 52)
        ctx.set_source_rgba(*PINK, lt)
        ctx.fill()
        lower(ctx, 'pastor brayden', 40, h - 133, 24, lt, align='left')
        lower(ctx, 'LEAD PASTOR', 40, h - 114, 13, 0.75 * lt, weight=False, tracking=3, align='left')
        ctx.restore()
    handle = ease_out(span(t, 4.75, 5.05)) * (1 - ease_in_out(span(t, 6.6, 6.85)))
    if handle > 0:
        ctx.rectangle(24, h - 150, 270, 34)
        ctx.set_source_rgba(0, 0, 0, 0.5 * handle)
        ctx.fill()
        lower(ctx, '@vizelvisionchurch', 38, h - 127, 19, handle, align='left')


def finale_wall(ctx, t, w, h):
    """The closed logo: the station's colours, the wordmark, CHURCH."""
    shift = (t - CLOSED) * 0.4
    g = cairo.LinearGradient(0, 0, w, h)
    g.add_color_stop_rgb(0, *mix((0.2, 0.05, 0.35), PINK, 0.25 + 0.15 * math.sin(shift * 3)))
    g.add_color_stop_rgb(0.5, 0.06, 0.02, 0.18)
    g.add_color_stop_rgb(1, *mix((0.0, 0.25, 0.35), TEAL, 0.3))
    ctx.set_source(g)
    ctx.paint()
    for k in range(16):                                      # rays from behind the wordmark
        a = k * TAU / 16 + shift
        ctx.move_to(w / 2, h * 0.5)
        ctx.line_to(w / 2 + 900 * math.cos(a - 0.08), h * 0.5 + 900 * math.sin(a - 0.08))
        ctx.line_to(w / 2 + 900 * math.cos(a + 0.08), h * 0.5 + 900 * math.sin(a + 0.08))
        ctx.close_path()
        ctx.set_source_rgba(1, 1, 1, 0.05)
        ctx.fill()


def wall(ctx, t):
    x, y, w, h = WALL
    ctx.save()
    ctx.rectangle(x, y, w, h)
    ctx.clip()
    ctx.translate(x, y)
    if t < HITS[0]:
        countdown(ctx, t, w, h)
    elif t < IMAG:
        k = sum(1 for hit in HITS if t >= hit) - 1
        lyric_slide(ctx, t, w, h, k)
    elif t < CLOSED:
        imag(ctx, t, w, h)
    else:
        finale_wall(ctx, t, w, h)
    ctx.restore()
    if t >= CLOSED - 0.02:                                   # the wordmark, on the wall
        ctx.save()
        ctx.rectangle(x, y, w, h)
        ctx.clip()
        neighborhood.lockup(ctx, t, CLOSED, y + 150, scale=0.66, step=0.05)
        c = ease_out(span(t, CHURCH, CHURCH + 0.35))
        if c > 0:
            lower(ctx, 'C H U R C H', 640, y + 208, 30, c, tracking=10)
        g2 = ease_out(span(t, TAGLINE, TAGLINE + 0.35))
        if g2 > 0:
            lower(ctx, 'ONE CHANNEL. MANY CAMPUSES.', 640, y + 246, 17, 0.9 * g2, weight=False, tracking=5)
        ctx.restore()
    # Flashes: the hits, the whiteout.
    flash_amt = max(hit_flash(t) * 0.22, ease_in(span(t, *WHITEOUT)) * (1 if t < CLOSED else 0))
    if t < IMAG and t >= HITS[0]:
        last = max(h for h in HITS if h <= t)
        flash_amt = max(flash_amt, 0.85 * (1 - span(t, last, last + 0.07)))
    if flash_amt > 0:
        ctx.rectangle(x, y, w, h)
        ctx.set_source_rgba(1, 1, 1, min(1, flash_amt))
        ctx.fill()
    ctx.set_source_surface(pixel_grid(), x, y)
    ctx.paint()
    # The wall lights the room.
    glow = cairo.RadialGradient(640, y + h / 2, 100, 640, y + h / 2, 700)
    colour = (0.6, 0.4, 1.0) if t < CLOSED else (1.0, 0.5, 0.8)
    glow.add_color_stop_rgba(0, *colour, 0.10 + 0.15 * flash_amt)
    glow.add_color_stop_rgba(1, 0, 0, 0, 0)
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_source(glow)
    ctx.paint()
    ctx.set_operator(cairo.OPERATOR_OVER)


# ---------------------------------------------------------------- the side pillars
def truck(ctx, x, y, s):
    """A lifted truck with the station's decal."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    for wx in (-34, 30):                                     # mud tyres
        ctx.arc(wx, 22, 15, 0, TAU)
        ctx.set_source_rgb(0.08, 0.08, 0.08)
        ctx.fill()
        ctx.arc(wx, 22, 6, 0, TAU)
        ctx.set_source_rgb(0.6, 0.6, 0.62)
        ctx.fill()
    ctx.rectangle(-36, 4, 72, 4)                             # the lift
    ctx.set_source_rgb(0.85, 0.2, 0.2)
    ctx.fill()
    ctx.move_to(-50, 4)
    ctx.line_to(-50, -14)
    ctx.line_to(-16, -14)
    ctx.line_to(-8, -32)
    ctx.line_to(22, -32)
    ctx.line_to(30, -14)
    ctx.line_to(52, -12)
    ctx.line_to(52, 4)
    ctx.close_path()
    ctx.set_source_rgb(0.12, 0.13, 0.16)
    ctx.fill()
    ctx.rectangle(-4, -28, 22, 12)
    ctx.set_source_rgb(0.5, 0.65, 0.8)
    ctx.fill()
    ctx.restore()
    tv_dot(ctx, 0, x - 26 * s, y - 4 * s, 0.05 * s)          # the decal on the bed


def pillar_slide(ctx, t, x, y, w, h, slide):
    ctx.save()
    ctx.rectangle(x, y, w, h)
    ctx.clip()
    ctx.translate(x, y)
    if slide == 'steak':
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgb(0, 0.15, 0.08, 0.05)
        g.add_color_stop_rgb(1, 0.32, 0.12, 0.06)
        ctx.set_source(g)
        ctx.paint()
        ctx.save()                                           # a steak, sizzling
        ctx.translate(w / 2, 150)
        ctx.scale(1, 0.6)
        ctx.arc(0, 0, 44, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(0.5, 0.18, 0.1)
        ctx.fill()
        ctx.set_source_rgb(0.25, 0.08, 0.05)
        ctx.set_line_width(3)
        for k in range(4):
            ctx.move_to(w / 2 - 30 + k * 16, 132)
            ctx.line_to(w / 2 - 40 + k * 16, 168)
        ctx.stroke()
        lower(ctx, 'STEAK &', w / 2, 52, 22, tracking=2)
        lower(ctx, 'SCRIPTURE', w / 2, 80, 22, tracking=2)
        lower(ctx, "MEN'S NIGHT", w / 2, 214, 15, 0.9, weight=False, tracking=2)
        lower(ctx, 'THU 7PM', w / 2, 240, 15, 0.9, weight=False, tracking=2)
    elif slide == 'truck':
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgb(0, 0.35, 0.55, 0.85)
        g.add_color_stop_rgb(1, 0.85, 0.9, 0.95)
        ctx.set_source(g)
        ctx.paint()
        ctx.rectangle(0, 170, w, h - 170)
        ctx.set_source_rgb(0.3, 0.3, 0.33)
        ctx.fill()
        ctx.set_source_rgb(1, 1, 1)
        for k in range(5):
            ctx.rectangle(k * 34 - 4, 200, 4, 30)
        ctx.fill()
        truck(ctx, w / 2, 168, 1.1)
        lower(ctx, 'PARKING LOT', w / 2, 52, 20, colour=(0.05, 0.08, 0.2), tracking=1)
        lower(ctx, 'CAMPUS', w / 2, 80, 26, colour=(0.05, 0.08, 0.2), tracking=3)
        lower(ctx, 'tune in: 19', w / 2, 250, 14, colour=WHITE, weight=False)
    elif slide == 'campuses':
        ctx.set_source_rgb(0.06, 0.06, 0.1)
        ctx.paint()
        lower(ctx, 'CAMPUSES', w / 2, 52, 20, colour=PINK, tracking=3)
        for k, name in enumerate(('chantilly', 'ashburn', 'online')):
            lower(ctx, name, w / 2, 108 + k * 50, 24)
            ctx.arc(w / 2, 122 + k * 50, 2.5, 0, TAU)
            ctx.set_source_rgba(1, 1, 1, 0.5)
            ctx.fill()
    else:                                                    # text to give
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgb(0, 0.0, 0.5, 0.45)
        g.add_color_stop_rgb(1, 0.0, 0.2, 0.3)
        ctx.set_source(g)
        ctx.paint()
        lower(ctx, 'GIVE', w / 2, 70, 34, tracking=6)
        lower(ctx, 'text', w / 2, 128, 18, weight=False)
        lower(ctx, '19', w / 2, 192, 64)
        lower(ctx, 'to 70', w / 2, 236, 18, weight=False)
    ctx.restore()


def pillars(ctx, t):
    plan = (('steak', 'truck'), ('campuses', 'give'), ('truck', 'steak'))
    for side, (x, y, w, h) in enumerate(PILLARS):
        if t < SLIDES[0] or t >= CLOSED:
            # The countdown loop and the finale: the brand and the station colours, quiet.
            ctx.save()
            ctx.rectangle(x, y, w, h)
            ctx.clip()
            g = cairo.LinearGradient(x, y, x, y + h)
            c = wash(t)
            g.add_color_stop_rgb(0, *mix(c, NIGHT, 0.55))
            g.add_color_stop_rgb(1, *mix(c, NIGHT, 0.85))
            ctx.set_source(g)
            ctx.paint()
            if t >= CLOSED:
                tv_dot(ctx, t, x + w / 2, y + h / 2, 0.36 * ease_out(span(t, CLOSED, CLOSED + 0.4)))
            ctx.restore()
        else:
            k = sum(1 for s in SLIDES if t >= s) - 1
            pillar_slide(ctx, t, x, y, w, h, plan[k][side])
            wipe = 1 - span(t, SLIDES[k], SLIDES[k] + 0.15)
            if wipe > 0:
                ctx.rectangle(x, y, w, h)
                ctx.set_source_rgba(1, 1, 1, wipe * 0.7)
                ctx.fill()
        ctx.set_source_surface(pixel_grid(), x, y)
        ctx.save()
        ctx.rectangle(x, y, w, h)
        ctx.clip()
        ctx.paint()
        ctx.restore()


# ---------------------------------------------------------------- the beams, the jets, the haze
def beams(ctx, t):
    colour = wash(t)
    flash = hit_flash(t)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for i, fx in enumerate(FIXTURES):
        if HITS[0] <= t < WALK[0]:                           # on the hits: snapped to centre, then fanned
            k = sum(1 for h in HITS if t >= h) - 1
            fan = ease_out(span(t, HITS[k], HITS[k] + 0.2))
            angle = (i - 3) * (0.04 + 0.12 * fan) * (1 if k % 2 else -1)
        elif t >= CLOSED:                                    # the finale: big sweeps
            angle = 0.5 * math.sin(t * 2.4 + i * 0.9)
        else:
            angle = 0.32 * math.sin(t * 0.9 + i * 0.8) + (i - 3) * 0.05
        level = 0.1 + 0.16 * flash + (0.06 if t >= CLOSED else 0)
        length, spread = 760, 0.07 + 0.02 * (i % 2)
        x0, y0 = fx, TRUSS_Y + 10
        x1, y1 = x0 + length * math.sin(angle - spread), y0 + length * math.cos(angle - spread)
        x2, y2 = x0 + length * math.sin(angle + spread), y0 + length * math.cos(angle + spread)
        g = cairo.LinearGradient(x0, y0, (x1 + x2) / 2, (y1 + y2) / 2)
        c = mix(colour, WHITE, 0.25 if i % 2 else 0)
        g.add_color_stop_rgba(0, *c, level * 1.4)
        g.add_color_stop_rgba(0.45, *c, level * 0.45)
        g.add_color_stop_rgba(1, *c, 0)
        ctx.move_to(x0, y0)
        ctx.line_to(x1, y1)
        ctx.line_to(x2, y2)
        ctx.close_path()
        ctx.set_source(g)
        ctx.fill()
        ctx.arc(x0, y0, 7, 0, TAU)                           # the lens
        ctx.set_source_rgba(*c, 0.6 + 0.4 * flash)
        ctx.fill()
    ctx.restore()
    for fx in FIXTURES:                                      # the fixtures themselves
        rounded_rect(ctx, fx - 10, TRUSS_Y - 2, 20, 12, 3)
        ctx.set_source_rgb(0.08, 0.08, 0.1)
        ctx.fill()


@lru_cache(maxsize=None)
def puff():
    """One soft white CO2 puff, to stamp along a jet."""
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 128, 128)
    ctx = cairo.Context(s)
    g = cairo.RadialGradient(64, 64, 0, 64, 64, 64)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.55)
    g.add_color_stop_rgba(0.6, 1, 1, 1, 0.2)
    g.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(g)
    ctx.paint()
    return s


def jets(ctx, t):
    fires = []
    for k, h in enumerate(HITS):
        which = ((0, 3), (1, 2), (0, 1, 2, 3), (0, 1, 2, 3))[k]
        fires += [(h, j, 0.8 if k < 3 else 1.0) for j in which]
    fires += [(when, j, 1.1) for when in JETS_CLOSED for j in range(4)]
    for when, j, size in fires:
        age = t - when
        if not 0 <= age < 1.1:
            continue
        height = 340 * size * ease_out(min(1, age / 0.35))
        fade = 1 - span(age, 0.25, 1.1)
        x0, y0 = JETS[j], STAGE_FRONT - 18
        rand = random.Random(j * 31 + int(when * 100))
        for n in range(16):
            u = n / 15
            if u * 340 * size > height + 1:
                break
            r = (14 + 46 * u) * (0.8 + 0.4 * rand.random()) * (1 + 0.6 * age)
            px = x0 + rand.uniform(-6, 6) * (1 + u * 3) + age * 20 * (u - 0.3)
            py = y0 - u * height
            ctx.save()
            ctx.translate(px - r, py - r)
            ctx.scale(r / 64, r / 64)
            ctx.set_source_surface(puff(), 0, 0)
            ctx.paint_with_alpha(fade * (1 - 0.5 * u))
            ctx.restore()


@lru_cache(maxsize=None)
def haze_surface(seed):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, W // 4, H // 4)
    ctx = cairo.Context(s)
    rand = random.Random(seed)
    for _ in range(40):
        x, y, r = rand.uniform(0, W / 4), rand.uniform(0, H / 4), rand.uniform(20, 70)
        g = cairo.RadialGradient(x, y, 0, x, y, r)
        g.add_color_stop_rgba(0, 0.6, 0.6, 0.75, 0.06)
        g.add_color_stop_rgba(1, 0, 0, 0, 0)
        ctx.set_source(g)
        ctx.paint()
    return s


def haze(ctx, t):
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for seed, speed in ((1, 6), (2, -4)):
        ctx.save()
        ctx.translate((t * speed) % 40 - 20, 0)
        ctx.scale(4, 4)
        ctx.set_source_surface(haze_surface(seed), 0, 0)
        ctx.paint()
        ctx.restore()
    ctx.restore()


# ---------------------------------------------------------------- people on stage
def limb(ctx, points, width, colour):
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    ctx.move_to(*points[0])
    for p in points[1:]:
        ctx.line_to(*p)
    ctx.set_source_rgb(*colour)
    ctx.set_line_width(width)
    ctx.stroke()


def lit(colour, t, amount=0.35):
    """A colour under the stage wash."""
    return mix(mix(colour, NIGHT, 0.35), wash(t), amount * 0.5)


def worship_leader(ctx, t):
    """Beanie, denim jacket, black skinny jeans, an acoustic with the capo high up."""
    x, foot = LEADER_X, 505
    sway = 3 * math.sin(t * math.pi * 2 * 0.5)
    strum = math.sin(t * math.pi * 4) * (1.0 if t > HITS[0] else 0.5)
    ctx.save()
    ctx.translate(x + sway, foot)
    jeans, jacket = lit((0.06, 0.06, 0.08), t), lit(DENIM, t)
    limb(ctx, [(-8, -62), (-12, -30), (-10, 0)], 12, jeans)
    limb(ctx, [(8, -62), (12, -30), (14, 0)], 12, jeans)
    for sx in (-10, 14):                                     # boots
        rounded_rect(ctx, sx - 9, -6, 20, 8, 3)
        ctx.set_source_rgb(*lit((0.3, 0.18, 0.1), t))
        ctx.fill()
    rounded_rect(ctx, -20, -128, 40, 70, 10)                 # the jacket
    ctx.set_source_rgb(*jacket)
    ctx.fill()
    ctx.arc(0, -142, 15, 0, TAU)                             # head
    ctx.set_source_rgb(*lit(SKIN, t))
    ctx.fill()
    ctx.arc(0, -148, 16, math.pi, 0)                         # the beanie, cuffed
    ctx.set_source_rgb(*lit(MUSTARD, t, 0.2))
    ctx.fill()
    ctx.rectangle(-16, -150, 32, 6)
    ctx.fill()
    # The guitar: body, soundhole, neck up to his left, the capo at the seventh fret.
    ctx.save()
    ctx.translate(2, -84)
    ctx.rotate(-0.42)
    ctx.save()
    ctx.scale(1, 0.8)
    ctx.arc(-6, 6, 25, 0, TAU)
    ctx.arc(18, 4, 19, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*lit((0.8, 0.55, 0.28), t, 0.25))
    ctx.fill()
    ctx.arc(4, 3, 6, 0, TAU)
    ctx.set_source_rgb(0.08, 0.05, 0.03)
    ctx.fill()
    ctx.rectangle(-78, 0, 66, 6)
    ctx.set_source_rgb(*lit((0.35, 0.2, 0.1), t))
    ctx.fill()
    ctx.rectangle(-92, -1, 16, 8)                            # the headstock
    ctx.fill()
    ctx.rectangle(-52, -3, 4, 12)                            # the capo, way up at seven
    ctx.set_source_rgb(0.9, 0.9, 0.95)
    ctx.fill()
    ctx.restore()
    # The fretting hand and the strumming arm.
    limb(ctx, [(-14, -118), (-40, -102), (-58, -118)], 8, jacket)
    limb(ctx, [(16, -118), (24, -92), (12 + 6 * strum, -78 + 8 * strum)], 8, jacket)
    ctx.restore()


def bassist(ctx, t):
    x, foot = BASS_X, 474
    bob = 2 * abs(math.sin(t * math.pi))
    ctx.save()
    ctx.translate(x, foot - bob)
    jeans = lit((0.12, 0.12, 0.16), t)
    limb(ctx, [(-7, -56), (-10, 0)], 11, jeans)
    limb(ctx, [(7, -56), (12, 0)], 11, jeans)
    rounded_rect(ctx, -17, -116, 34, 62, 9)
    ctx.set_source_rgb(*lit((0.18, 0.18, 0.2), t))
    ctx.fill()
    ctx.arc(0, -128, 13, 0, TAU)
    ctx.set_source_rgb(*lit((0.55, 0.38, 0.28), t))
    ctx.fill()
    ctx.arc(0, -133, 14, math.pi * 1.05, -0.05)              # a man bun
    ctx.set_source_rgb(*lit((0.15, 0.1, 0.06), t))
    ctx.fill()
    ctx.arc(2, -148, 6, 0, TAU)
    ctx.fill()
    ctx.save()
    ctx.translate(0, -80)
    ctx.rotate(-0.35)
    rounded_rect(ctx, -22, -12, 40, 24, 10)
    ctx.set_source_rgb(*lit((0.6, 0.1, 0.12), t, 0.3))
    ctx.fill()
    ctx.rectangle(-80, -3, 62, 5)
    ctx.set_source_rgb(*lit((0.2, 0.12, 0.06), t))
    ctx.fill()
    ctx.restore()
    ctx.restore()


def keys(ctx, t):
    x, foot = KEYS_X, 420
    ctx.save()
    ctx.translate(x, foot)
    ctx.rectangle(-40, -50, 80, 8)                           # the keyboard on its X stand
    ctx.set_source_rgb(*lit((0.1, 0.1, 0.12), t))
    ctx.fill()
    ctx.set_source_rgb(*lit((0.6, 0.6, 0.65), t))
    ctx.set_line_width(3)
    ctx.move_to(-30, 0)
    ctx.line_to(30, -42)
    ctx.move_to(30, 0)
    ctx.line_to(-30, -42)
    ctx.stroke()
    rounded_rect(ctx, -14, -104, 28, 56, 8)
    ctx.set_source_rgb(*lit((0.92, 0.9, 0.85), t, 0.3))
    ctx.fill()
    ctx.arc(0, -119, 14, math.pi * 0.85, math.pi * 2.15)     # long hair, behind
    ctx.rectangle(-14, -119, 28, 26)
    ctx.set_source_rgb(*lit((0.55, 0.38, 0.2), t))
    ctx.fill()
    ctx.arc(0, -116, 11, 0, TAU)                             # her face, turned to the keys
    ctx.set_source_rgb(*lit((0.82, 0.62, 0.5), t))
    ctx.fill()
    ctx.arc(0, -121, 12, math.pi * 1.05, math.pi * 1.95)     # her fringe
    ctx.set_source_rgb(*lit((0.55, 0.38, 0.2), t))
    ctx.fill()
    limb(ctx, [(-10, -96), (-24, -76), (-30, -60)], 6, lit((0.92, 0.9, 0.85), t, 0.3))
    limb(ctx, [(10, -96), (22, -76), (26, -60)], 6, lit((0.92, 0.9, 0.85), t, 0.3))
    ctx.rectangle(-46, -64, 92, 9)                           # the keyboard, in front of her
    ctx.set_source_rgb(*lit((0.1, 0.1, 0.12), t))
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.5)
    for k in range(14):
        ctx.rectangle(-44 + k * 6.4, -63, 4.4, 3)
    ctx.fill()
    ctx.restore()


def drums(ctx, t):
    """The kit behind its plexiglass shield; the drummer's arms come down on the kicks' snares."""
    hit = max([pulse(t, h, 0.15) for h in HITS] + [pulse(t, CLOSED, 0.2)])
    ctx.save()
    ctx.translate(640, 398)
    for cx, cy, r in ((-46, -28, 18), (46, -28, 18), (-22, -46, 12), (22, -46, 12)):
        ctx.save()
        ctx.scale(1, 0.4)
        ctx.arc(cx, cy / 0.4, r, 0, TAU)
        ctx.restore()
        ctx.set_source_rgb(*lit((0.75, 0.68, 0.3), t, 0.2))
        ctx.fill()
    ctx.arc(0, -14, 22, 0, TAU)                              # the kick drum, the logo on its head
    ctx.set_source_rgb(*lit((0.9, 0.9, 0.92), t, 0.3))
    ctx.fill()
    font(ctx, 'Quicksand', 9, bold=True)
    ctx.set_source_rgb(0.1, 0.1, 0.15)
    text_path(ctx, 'vizelvision.', 0, -11, align='center')
    ctx.fill()
    ctx.arc(0, -70, 11, 0, TAU)
    ctx.set_source_rgb(*lit((0.6, 0.42, 0.3), t))
    ctx.fill()
    arm = -1 + 2 * (1 - hit)
    limb(ctx, [(-10, -58), (-30, -48 + arm * 8)], 6, lit((0.15, 0.15, 0.18), t))
    limb(ctx, [(10, -58), (30, -48 - arm * 8)], 6, lit((0.15, 0.15, 0.18), t))
    # The shield: five clear panels with their highlights.
    for k in range(5):
        x0 = -90 + k * 36
        ctx.rectangle(x0, -96, 34, 96)
        ctx.set_source_rgba(0.7, 0.8, 1.0, 0.07)
        ctx.fill()
        ctx.move_to(x0 + 6, -92)
        ctx.line_to(x0 + 16, -60)
        ctx.set_source_rgba(1, 1, 1, 0.25 + 0.4 * hit)
        ctx.set_line_width(1.5)
        ctx.stroke()
        ctx.rectangle(x0, -96, 34, 96)
        ctx.set_source_rgba(0.8, 0.85, 1, 0.3)
        ctx.set_line_width(1)
        ctx.stroke()
    ctx.restore()


def pastor(ctx, t):
    """Pastor Brayden: jogs out, talks with his hands, both arms up for the finale."""
    if t < WALK[0]:
        return
    p = ease_out(span(t, *WALK), 2)
    x = PASTOR_X[0] + (PASTOR_X[1] - PASTOR_X[0]) * p
    jog = span(t, *WALK) < 1
    foot = 512
    stride = math.sin(t * math.pi * 6) if jog else 0
    bounce = abs(stride) * 4 if jog else 0
    up = ease_out(span(t, HANDS[0] + 0.2, HANDS[0] + 0.6))
    point = ease_in_out(span(t, POINT[0], POINT[0] + 0.3)) * (1 - ease_in_out(span(t, POINT[1] - 0.3, POINT[1])))
    talk = mouth_open(t)
    ctx.save()
    ctx.translate(x, foot - bounce)
    ctx.scale(1.05, 1.05)
    jeans = lit((0.32, 0.45, 0.66), t, 0.25)
    limb(ctx, [(-8, -66), (-10 - 8 * stride, -32), (-9 - 14 * stride, 0)], 12, jeans)
    limb(ctx, [(8, -66), (10 + 8 * stride, -32), (11 + 14 * stride, 0)], 12, jeans)
    ctx.set_source_rgba(1, 1, 1, 0.8)                        # the rips at the knees
    for kx in (-10 - 8 * stride, 10 + 8 * stride):
        ctx.rectangle(kx - 4, -36, 8, 2)
        ctx.rectangle(kx - 3, -31, 6, 2)
    ctx.fill()
    for sx in (-9 - 14 * stride, 11 + 14 * stride):          # chunky white sneakers
        rounded_rect(ctx, sx - 11, -9, 24, 11, 5)
        ctx.set_source_rgb(0.97, 0.97, 0.98)
        ctx.fill()
        ctx.rectangle(sx - 11, -2, 24, 3)
        ctx.set_source_rgb(0.75, 0.75, 0.78)
        ctx.fill()
    # The fitted v-neck.
    ctx.move_to(-22, -134)
    ctx.line_to(22, -134)
    ctx.line_to(18, -64)
    ctx.line_to(-18, -64)
    ctx.close_path()
    ctx.set_source_rgb(*lit(HEATHER, t, 0.3))
    ctx.fill()
    ctx.move_to(-8, -134)
    ctx.line_to(0, -114)
    ctx.line_to(8, -134)
    ctx.close_path()
    ctx.set_source_rgb(*lit(SKIN, t, 0.25))
    ctx.fill()
    # Arms: the tumbler in his left hand; his right points up on "relationship"; both up at the end.
    tumbler_hand = (-30 - 30 * up, -84 - 76 * up)
    right_hand = (32 + 10 * point - 0 * up, -84 - 80 * max(point, up))
    sleeve = lit(SKIN, t, 0.25)
    limb(ctx, [(-20, -128), (-28 - 18 * up, -104 - 46 * up), tumbler_hand], 8, sleeve)
    limb(ctx, [(20, -128), (28 + 14 * up, -104 - 48 * max(point, up)), right_hand], 8, sleeve)
    ctx.set_source_rgba(0.15, 0.2, 0.35, 0.7)                # the sleeve tattoo
    ctx.set_line_width(3)
    ctx.move_to(-21, -124)
    ctx.line_to(-27 - 18 * up, -104 - 46 * up)
    ctx.stroke()
    rounded_rect(ctx, tumbler_hand[0] - 6, tumbler_hand[1] - 22, 12, 26, 3)  # the forty-ounce tumbler
    ctx.set_source_rgb(0.75, 0.88, 0.85)
    ctx.fill()
    ctx.arc(tumbler_hand[0] + 7, tumbler_hand[1] - 10, 4, -1.5, 1.5)
    ctx.set_source_rgb(0.6, 0.75, 0.72)
    ctx.set_line_width(2)
    ctx.stroke()
    ctx.rectangle(tumbler_hand[0] - 1, tumbler_hand[1] - 30, 2, 8)       # the straw
    ctx.set_source_rgb(0.95, 0.95, 0.95)
    ctx.fill()
    # Head: beard, hair, the Oakleys up top, the headset.
    ctx.arc(0, -150, 15, 0, TAU)
    ctx.set_source_rgb(*lit(SKIN, t, 0.25))
    ctx.fill()
    ctx.arc(0, -147, 15, 0.15, math.pi - 0.15)
    ctx.set_source_rgb(*lit(BEARD, t, 0.2))
    ctx.fill()
    if talk:
        ctx.arc(0, -141, 2 + 3 * talk, 0, TAU)
        ctx.set_source_rgb(0.2, 0.05, 0.05)
        ctx.fill()
    ctx.arc(0, -157, 15, math.pi, 0)
    ctx.set_source_rgb(*lit((0.3, 0.18, 0.09), t, 0.2))
    ctx.fill()
    ctx.move_to(-15, -164)
    ctx.curve_to(-6, -170, 6, -170, 15, -164)
    ctx.set_source_rgb(0.05, 0.05, 0.06)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.move_to(-13, -165)
    ctx.curve_to(-4, -169, 4, -169, 13, -165)
    ctx.set_source_rgb(0.9, 0.45, 0.2)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.move_to(14, -152)
    ctx.curve_to(15, -146, 10, -142, 5, -141)
    ctx.set_source_rgb(0.86, 0.72, 0.58)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.restore()
    # A warm follow spot on him.
    spot = cairo.RadialGradient(x, foot - 80, 10, x, foot - 80, 150)
    spot.add_color_stop_rgba(0, *AMBER, 0.14 * (1 if t < CLOSED else 0.5))
    spot.add_color_stop_rgba(1, 0, 0, 0, 0)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    ctx.set_source(spot)
    ctx.paint()
    ctx.restore()


# ---------------------------------------------------------------- the room's people
def _crowd():
    rand = random.Random(36)
    people = []
    for y, r, n, spread in ((598, 12, 34, 40), (636, 18, 22, 60), (700, 30, 12, 110)):
        for k in range(n):
            x = -20 + (k + rand.uniform(-0.3, 0.3)) * (W + 40) / (n - 1)
            people.append({'x': x, 'y': y + rand.uniform(-5, 5), 'r': r * rand.uniform(0.9, 1.1),
                           'style': rand.choice(('short', 'short', 'bun', 'cap', 'long', 'beanie')),
                           'delay': rand.uniform(0, 0.45), 'phone': rand.random() < 0.18,
                           'early': rand.random() < 0.22, 'sway': rand.uniform(0, TAU)})
    return people


CROWD = _crowd()


def crowd(ctx, t):
    rim = wash(t)
    flash = hit_flash(t)
    for p in CROWD:
        x, y, r = p['x'] + 2 * math.sin(t * 1.5 + p['sway']), p['y'], p['r']
        dark = mix(NIGHT, (0.08, 0.06, 0.12), 0.5)
        raise_ = ease_out(span(t, HANDS[0] + p['delay'], HANDS[0] + p['delay'] + 0.45))
        if p['early']:                                       # some are already up by the hits
            raise_ = max(raise_, ease_out(span(t, HITS[0] + p['delay'], HITS[0] + p['delay'] + 0.4)) * 0.85)
        phone = p['phone'] and HITS[0] + 0.1 <= t < HANDS[0] + p['delay']
        sway = 0.25 * math.sin(t * math.pi + p['sway']) * raise_
        # Arms, behind the head.
        if raise_ > 0 or phone:
            for sx in (-1, 1):
                if phone and sx < 0 and raise_ <= 0:
                    continue
                k = raise_ if not phone else max(raise_, 0.8)
                hx = x + sx * r * (1.0 + 0.5 * k) + sway * r * 2
                hy = y + r * 0.6 - r * 3.4 * k
                limb(ctx, [(x + sx * r * 0.9, y + r * 0.8), (hx, hy)], r * 0.5, dark)
                ctx.arc(hx, hy - r * 0.15, r * 0.32, 0, TAU)
                ctx.set_source_rgb(*dark)
                ctx.fill()
                if phone and sx > 0:
                    rounded_rect(ctx, hx - r * 0.3, hy - r * 0.9, r * 0.6, r * 0.95, r * 0.1)
                    ctx.set_source_rgb(0.7, 0.8, 1.0)
                    ctx.fill()
        # Shoulders and head.
        ctx.save()
        ctx.translate(x, y + r * 1.4)
        ctx.scale(1.75, 1)
        ctx.arc(0, 0, r, math.pi, 0)
        ctx.restore()
        ctx.rectangle(x - r * 1.75, y + r * 1.4, r * 3.5, 80)
        ctx.set_source_rgb(*dark)
        ctx.fill()
        ctx.arc(x, y, r, 0, TAU)
        ctx.fill()
        style = p['style']
        if style == 'bun':
            ctx.arc(x, y - r * 0.95, r * 0.4, 0, TAU)
            ctx.fill()
        elif style == 'cap':
            ctx.rectangle(x - r * 1.1, y - r * 0.35, r * 0.6, r * 0.25)
            ctx.fill()
        elif style == 'beanie':
            ctx.arc(x, y - r * 1.05, r * 0.25, 0, TAU)
            ctx.fill()
        elif style == 'long':
            ctx.rectangle(x - r, y, r * 2, r * 1.3)
            ctx.fill()
        # The stage's light on the tops of heads.
        ctx.arc(x, y, r, math.pi * 1.15, math.pi * 1.85)
        ctx.set_source_rgba(*rim, 0.55 + 0.45 * flash)
        ctx.set_line_width(max(1.0, r * 0.07))
        ctx.stroke()


def confetti(ctx, t):
    if t < CLOSED:
        return
    age = t - CLOSED
    rand = random.Random(19)
    colours = (PINK, TEAL, YELLOW, CYAN, ORANGE, WHITE)
    for k in range(240):
        x0 = rand.uniform(-50, W + 50)
        speed = rand.uniform(90, 200)
        start = rand.uniform(-0.6, 0.0) * 400
        y = -20 + start * 0.1 + age * speed + rand.uniform(-300, 0)
        if y < -20 or y > H + 20:
            continue
        x = x0 + 20 * math.sin(age * rand.uniform(2, 5) + k)
        spin = age * rand.uniform(4, 10) + k
        ctx.save()
        ctx.translate(x, y)
        ctx.rotate(spin)
        ctx.scale(1, abs(math.sin(spin * 1.3)) + 0.15)
        ctx.rectangle(-5, -3, 10, 6)
        ctx.restore()
        ctx.set_source_rgb(*rand.choice(colours))
        ctx.fill()


# ---------------------------------------------------------------- the frame
def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.save()
    # The camera: a slow push from the back of the room, a jolt on the kicks.
    zoom = 1.0 + 0.045 * ease_in_out(span(t, 0, FADE[1]))
    jolt = max([pulse(t, h, 0.12) for h in HITS] + [pulse(t, CLOSED, 0.15)])
    ctx.translate(640, 330 + 3 * jolt)
    ctx.scale(zoom, zoom)
    ctx.translate(-640, -330)
    ctx.set_source_surface(room_surface(), 0, 0)
    ctx.paint()
    wall(ctx, t)
    pillars(ctx, t)
    beams(ctx, t)
    haze(ctx, t)
    drums(ctx, t)
    keys(ctx, t)
    bassist(ctx, t)
    plant(ctx, 150, 522, 150, wash(t), 4)
    plant(ctx, 1130, 522, 150, wash(t), 7)
    plant(ctx, 248, 420, 80, wash(t), 9)
    plant(ctx, 1016, 420, 80, wash(t), 12)
    worship_leader(ctx, t)
    pastor(ctx, t)
    jets(ctx, t)
    # The lip's LED strip in the wash colour, brighter on hits.
    ctx.rectangle(80, STAGE_FRONT, 1120, 3)
    ctx.set_source_rgba(*wash(t), 0.5 + 0.5 * hit_flash(t))
    ctx.fill()
    confetti(ctx, t)
    crowd(ctx, t)
    ctx.restore()
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.18)
    opening = 1 - ease_out(span(t, *FADE_IN))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
