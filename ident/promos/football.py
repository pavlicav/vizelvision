"""Football on VizelVision: a coach's chalkboard. PLAY 19 is chalked at the top and the game
on air in the corner (master's live text). The O's and X's tap onto the board with the
drumline; the four routes are drawn on the four notes of the open logo, each squeaking;
the pass, in dots, from the quarterback to the end zone, the ball spiralling along it;
TD! circled twice. An eraser clears the middle of the board and, on the closed logo, the
wordmark drops in over it with FOOTBALL chalked underneath.

Aired only during an NFL or college game (LEAGUES). Zeus: "Football... on Vizzle Vision."
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
from common import (INK, TAU, W, H, WHITE, YELLOW, back_out, clamp, ease_in, ease_in_out, ease_out, font,  # noqa: F401
                    glint, grain, inked, mix, pulse, rounded_rect, span, text_path, vignette)

ID = 'football'
NAME = 'Football on VizelVision'
KIND = 'ident'
ORDER = 21
DESCRIPTION = ("Only during football: a coach's chalkboard. PLAY 19's O's and X's tap in with the drumline, the "
               'routes are drawn on the logo, a pass for a touchdown, and the wordmark on the closed logo. The game '
               'on air is chalked in the corner. Zeus.')
DURATION = 10.0
STILL_AT = 8.6
LEAGUES = ('nfl', 'ncaaf')

# Hit points (the music's too: promos/music.py).
TITLE = (0.25, 0.75)                           # PLAY 19, written
OFFENSE = (0.6, 1.15)                          # the O's, a tap each
DEFENSE = (1.15, 1.75)                         # the X's
ROUTES = (2.0, 2.25, 2.5, 3.0)                 # the open logo: a route each
ROUTE_DRAW = 0.22
PASS = (3.3, 3.95)                             # the ball along the dotted line
TD = 4.0                                       # TD! and the whistle
CIRCLE = (4.05, 4.45)
ERASE = (6.45, 6.95)
WORDMARK = 7.0                                 # the closed logo
FOOTBALL = (7.6, 8.3)
FADE = (9.25, 9.6)

LINE = 470                                     # the line of scrimmage
SLATE = (0.13, 0.22, 0.17)
CHALK = (0.93, 0.94, 0.9)
GOLD = (1.0, 0.82, 0.35)

OVERLAYS = [
    {'field': 'programme', 'box': [700, 34, 520, 64], 'from': TITLE[0] + 0.3, 'to': FADE[0] + 0.1,
     'style': {'font': 'Z003', 'bold': False, 'size': 50, 'min_size': 22, 'color': [0.93, 0.94, 0.9],
               'align': 'right'},
     'enter': {'kind': 'fade', 'seconds': 0.4}, 'exit': {'kind': 'fade', 'seconds': 0.3}},
]

# The formation: (x, y) on the board.
O_SPOTS = ((520, 504), (580, 504), (640, 504), (700, 504), (760, 504), (830, 512),     # the line, the tight end
           (640, 560), (640, 616), (640, 668),                                        # QB, fullback, back
           (230, 512), (1060, 512))                                                   # the receivers
X_SPOTS = ((550, 436), (610, 436), (670, 436), (730, 436),                           # the front four
           (520, 372), (640, 360), (780, 372),                                        # linebackers
           (230, 424), (1060, 424), (460, 236), (840, 236))                          # corners, safeties
# The routes, in order: (start, through, end); the last is the one the ball goes to.
ROUTE_POINTS = (((1060, 512), (1060, 330), (1180, 250)),       # the right receiver: up and out
                ((830, 512), (830, 330), (700, 240)),           # the tight end: the seam, bending in
                ((640, 668), (840, 640), (980, 470)),           # the back: the wheel
                ((230, 512), (230, 250), (430, 150)))           # the left receiver: the post, to the end zone
END_ZONE = 150


# ---------------------------------------------------------------- chalk

@lru_cache(maxsize=None)
def chalk_texture():
    """White with speckled alpha: chalk's grain on the slate (premultiplied BGRA)."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    noise = random.Random(19).randbytes(W * H)
    alpha = bytes(120 + v % 136 if v > 40 else v for v in range(256))
    pixels = bytearray(4 * W * H)
    for channel, k in ((0, 0.93), (1, 0.94), (2, 0.9)):
        pixels[channel::4] = noise.translate(bytes(int(k * a) for a in alpha))
    pixels[3::4] = noise.translate(alpha)
    surface.get_data()[:] = pixels
    surface.mark_dirty()
    return surface


def chalk(ctx, draw, alpha=1.0):
    """Whatever draw() paints (in any colour, as a mask) comes out as chalk."""
    ctx.push_group()
    draw()
    mask = ctx.pop_group()
    ctx.save()
    ctx.push_group()
    ctx.set_source_surface(chalk_texture(), 0, 0)
    ctx.mask(mask)
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(alpha)
    ctx.restore()


def partial(points, p):
    """A polyline cut to fraction p of its length."""
    if p <= 0:
        return []
    lengths = [0.0]
    for a, b in zip(points, points[1:]):
        lengths.append(lengths[-1] + math.dist(a, b))
    reach = lengths[-1] * min(p, 1.0)
    out = [points[0]]
    for (a, b), l0, l1 in zip(zip(points, points[1:]), lengths, lengths[1:]):
        if l1 <= reach:
            out.append(b)
        else:
            k = (reach - l0) / max(l1 - l0, 1e-9)
            out.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
            break
    return out


def curve(start, through, end, n=40):
    """A route: a quadratic bend from start, via through, to end."""
    return [((1 - u) ** 2 * start[0] + 2 * (1 - u) * u * through[0] + u * u * end[0],
             (1 - u) ** 2 * start[1] + 2 * (1 - u) * u * through[1] + u * u * end[1]) for u in (k / n for k in range(n + 1))]


def wobble(points, seed, amount=1.6):
    rand = random.Random(seed)
    return [(x + rand.uniform(-amount, amount), y + rand.uniform(-amount, amount)) for x, y in points]


# ---------------------------------------------------------------- the board

@lru_cache(maxsize=None)
def slate_surface():
    """The slate, the ghosts of old plays, and the wooden frame and chalk tray, drawn once."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.RadialGradient(W / 2, H / 2, 100, W / 2, H / 2, 800)
    g.add_color_stop_rgb(0, *mix(SLATE, WHITE, 0.06))
    g.add_color_stop_rgb(1, *mix(SLATE, (0, 0, 0), 0.35))
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(7)
    for _ in range(26):                                 # smudges: old plays half rubbed out
        x, y, r = rand.uniform(0, W), rand.uniform(0, H), rand.uniform(60, 220)
        smudge = cairo.RadialGradient(x, y, 0, x, y, r)
        smudge.add_color_stop_rgba(0, 1, 1, 1, rand.uniform(0.02, 0.06))
        smudge.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(smudge)
        ctx.paint()
    ctx.set_line_width(3)
    for _ in range(16):
        x, y = rand.uniform(80, W - 80), rand.uniform(80, H - 120)
        ctx.set_source_rgba(1, 1, 1, rand.uniform(0.03, 0.07))
        if rand.random() < 0.5:
            ctx.arc(x, y, 14, 0, TAU)
        else:
            ctx.move_to(x - 12, y - 12)
            ctx.line_to(x + 12, y + 12)
            ctx.move_to(x + 12, y - 12)
            ctx.line_to(x - 12, y + 12)
        ctx.stroke()
    wood = cairo.LinearGradient(0, 0, 0, 24)
    wood.add_color_stop_rgb(0, 0.55, 0.36, 0.18)
    wood.add_color_stop_rgb(1, 0.38, 0.23, 0.1)
    ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
    ctx.rectangle(0, 0, W, H)
    ctx.rectangle(18, 18, W - 36, H - 50)
    ctx.set_source_rgb(0.47, 0.3, 0.14)
    ctx.fill()
    ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
    ctx.rectangle(0, H - 34, W, 34)                     # the chalk tray, with its stubs
    ctx.set_source_rgb(0.38, 0.23, 0.1)
    ctx.fill()
    for x, length in ((200, 46), (236, 30), (1010, 54)):
        rounded_rect(ctx, x, H - 30, length, 10, 5)
        ctx.set_source_rgb(0.95, 0.95, 0.9)
        ctx.fill()
    return surface


def title(ctx, t):
    p = span(t, *TITLE)
    if p <= 0:
        return

    def draw():
        ctx.save()
        ctx.rectangle(0, 0, 60 + 330 * ease_in_out(p), H)
        ctx.clip()
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(58)
        ctx.new_path()
        text_path(ctx, 'PLAY 19', 62, 92, tracking=3)
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        ctx.move_to(58, 108)
        ctx.curve_to(150, 102, 260, 112, 336, 104)
        ctx.set_line_width(5)
        ctx.stroke()
        ctx.restore()
    chalk(ctx, draw)


def marks(ctx, t):
    """The line of scrimmage, the goal line, the O's and the X's as they tap on."""
    def draw():
        ctx.set_source_rgb(1, 1, 1)
        reach = ease_out(span(t, 0.3, 0.7))
        if reach > 0:
            ctx.set_dash([16, 12])
            ctx.set_line_width(3)
            ctx.move_to(70, LINE)
            ctx.line_to(70 + (W - 140) * reach, LINE)
            ctx.stroke()
            ctx.set_dash([])
            ctx.move_to(70, END_ZONE + 40)
            ctx.line_to(70 + (W - 140) * reach, END_ZONE + 40)
            ctx.set_line_width(4)
            ctx.stroke()
            ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(22)
            ctx.new_path()
            text_path(ctx, 'END ZONE', 930, END_ZONE + 28, tracking=10, align='center')
            ctx.fill()
        for i, (x, y) in enumerate(O_SPOTS):
            q = span(t, OFFENSE[0] + i * (OFFENSE[1] - OFFENSE[0]) / len(O_SPOTS), OFFENSE[1])
            if q > 0:
                ctx.new_sub_path()
                ctx.arc(x, y, 17 * back_out(min(1.0, q * 4), 2.5), 0, TAU)
                ctx.set_line_width(5)
                ctx.stroke()
        for i, (x, y) in enumerate(X_SPOTS):
            q = span(t, DEFENSE[0] + i * (DEFENSE[1] - DEFENSE[0]) / len(X_SPOTS), DEFENSE[1])
            if q > 0:
                k = 15 * back_out(min(1.0, q * 4), 2.5)
                ctx.move_to(x - k, y - k)
                ctx.line_to(x + k, y + k)
                ctx.move_to(x + k, y - k)
                ctx.line_to(x - k, y + k)
                ctx.set_line_width(5)
                ctx.stroke()
    chalk(ctx, draw)


def arrowhead(ctx, a, b, size=18):
    angle = math.atan2(b[1] - a[1], b[0] - a[0])
    for side in (-1, 1):
        ctx.move_to(*b)
        ctx.line_to(b[0] - size * math.cos(angle + side * 0.5), b[1] - size * math.sin(angle + side * 0.5))


def routes(ctx, t):
    def draw():
        ctx.set_source_rgb(1, 1, 1)
        ctx.set_line_width(5)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        for k, (when, (start, through, end)) in enumerate(zip(ROUTES, ROUTE_POINTS)):
            p = ease_out(span(t, when, when + ROUTE_DRAW))
            pts = partial(wobble(curve(start, through, end), k), p)
            if len(pts) < 2:
                continue
            ctx.move_to(*pts[0])
            for pt in pts[1:]:
                ctx.line_to(*pt)
            if p >= 1:
                arrowhead(ctx, pts[-3], pts[-1])
            ctx.stroke()
        q = span(t, PASS[0] - 0.25, PASS[0])             # the pass, dotted, from the quarterback
        if q > 0:
            qb, target = O_SPOTS[6], ROUTE_POINTS[3][2]
            for i in range(int(18 * q)):
                u = (i + 0.5) / 18
                x = qb[0] + (target[0] - qb[0]) * u
                y = qb[1] + (target[1] - qb[1]) * u - 120 * math.sin(math.pi * u)
                ctx.new_sub_path()
                ctx.arc(x, y, 3.2, 0, TAU)
            ctx.fill()
    chalk(ctx, draw)


def football(ctx, x, y, angle, size, spin=0.0):
    """A chalk-drawn football: the leather, its laces."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(angle)
    ctx.move_to(-size, 0)
    ctx.curve_to(-size * 0.5, -size * 0.62, size * 0.5, -size * 0.62, size, 0)
    ctx.curve_to(size * 0.5, size * 0.62, -size * 0.5, size * 0.62, -size, 0)
    ctx.close_path()
    ctx.set_source_rgb(0.6, 0.3, 0.12)
    ctx.fill_preserve()
    ctx.set_source_rgb(*CHALK)
    ctx.set_line_width(3)
    ctx.stroke()
    offset = size * 0.12 * math.sin(spin)
    ctx.move_to(-size * 0.35, -size * 0.05 + offset)
    ctx.line_to(size * 0.35, -size * 0.05 + offset)
    for k in range(5):
        lx = -size * 0.24 + k * size * 0.12
        ctx.move_to(lx, -size * 0.14 + offset)
        ctx.line_to(lx, size * 0.04 + offset)
    ctx.set_line_width(2.5)
    ctx.stroke()
    ctx.restore()


def the_pass(ctx, t):
    if not PASS[0] <= t < PASS[1] + 0.3:
        return
    p = ease_in_out(span(t, *PASS))
    qb, target = O_SPOTS[6], ROUTE_POINTS[3][2]
    x = qb[0] + (target[0] - qb[0]) * p
    y = qb[1] + (target[1] - qb[1]) * p - 120 * math.sin(math.pi * p)
    football(ctx, x, y, math.atan2(target[1] - qb[1], target[0] - qb[0]) - 0.6 * math.cos(math.pi * p),
             26 - 6 * math.sin(math.pi * p), spin=t * 40)


def touchdown(ctx, t):
    p = span(t, TD, TD + 0.25)
    if p <= 0:
        return
    cx, cy = 540, 100

    def draw():
        ctx.save()
        ctx.translate(cx, cy)
        ctx.rotate(-0.08)
        k = back_out(p, 2.4)
        ctx.scale(k, k)
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(64)
        ctx.new_path()
        text_path(ctx, 'TD!', 0, 22, tracking=2, align='center')
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        ctx.restore()
        q = ease_in_out(span(t, *CIRCLE))                 # circled twice, a little loosely
        if q > 0:
            pts = [(cx + (100 + 6 * a / TAU) * math.cos(a - 2.6), cy + (52 + 4 * a / TAU) * math.sin(a - 2.6))
                   for a in (k / 90 * 2 * TAU * q for k in range(91))]
            ctx.move_to(*pts[0])
            for pt in pts[1:]:
                ctx.line_to(*pt)
            ctx.set_line_width(5)
            ctx.stroke()
    chalk(ctx, draw)


def eraser(ctx, t):
    """The middle of the board rubbed clean, left to right: a slate-coloured smear over the
    chalk, and the felt eraser itself."""
    p = span(t, *ERASE)
    if p <= 0:
        return
    reach = 60 + (W - 120) * ease_in_out(p)
    ctx.save()
    g = cairo.LinearGradient(0, 250, 0, 580)
    g.add_color_stop_rgba(0, *SLATE, 0)
    g.add_color_stop_rgba(0.12, *mix(SLATE, WHITE, 0.08), 0.94)
    g.add_color_stop_rgba(0.88, *mix(SLATE, WHITE, 0.08), 0.94)
    g.add_color_stop_rgba(1, *SLATE, 0)
    ctx.rectangle(40, 250, reach - 40, 330)
    ctx.set_source(g)
    ctx.fill()
    ctx.restore()
    if p < 1:
        ctx.save()
        ctx.translate(reach, 415 + 40 * math.sin(p * 18))
        ctx.rotate(0.1 * math.sin(p * 18))
        rounded_rect(ctx, -60, -130, 120, 260, 16)
        inked(ctx, (0.55, 0.36, 0.2), 5, (6, 6))
        rounded_rect(ctx, -60, -130, 120, 60, 16)
        ctx.set_source_rgb(0.3, 0.3, 0.32)
        ctx.fill()
        ctx.restore()


def finale(ctx, t):
    if t < WORDMARK - 0.05:
        return
    neighborhood.lockup(ctx, t, WORDMARK, 420, scale=0.7)
    p = span(t, *FOOTBALL)
    if p <= 0:
        return

    def draw():
        ctx.save()
        ctx.rectangle(0, 0, 400 + 480 * ease_in_out(p), H)
        ctx.clip()
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(52)
        ctx.new_path()
        text_path(ctx, 'FOOTBALL', W / 2, 510, tracking=14, align='center')
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        ctx.move_to(W / 2 - 200, 530)
        ctx.curve_to(W / 2 - 60, 522, W / 2 + 60, 536, W / 2 + 200, 526)
        ctx.set_line_width(5)
        ctx.stroke()
        ctx.restore()
    chalk(ctx, draw)
    for i, at in enumerate((WORDMARK + 0.25, WORDMARK + 1.0, WORDMARK + 2.0)):
        q = span(t, at, at + 0.5)
        if 0 < q < 1:
            glint(ctx, (380, 900, 640)[i], (330, 340, 300)[i], 22 * math.sin(math.pi * q), q * 3, 1)


def dust(ctx, t, frame):
    """Chalk dust falling where a piece just tapped or squeaked."""
    rand = random.Random(frame // 2)
    events = [(OFFENSE[0] + i * (OFFENSE[1] - OFFENSE[0]) / len(O_SPOTS), O_SPOTS[i]) for i in range(len(O_SPOTS))]
    events += [(DEFENSE[0] + i * (DEFENSE[1] - DEFENSE[0]) / len(X_SPOTS), X_SPOTS[i]) for i in range(len(X_SPOTS))]
    for when, (x, y) in events:
        p = span(t, when, when + 0.5)
        if 0 < p < 1:
            for _ in range(5):
                ctx.arc(x + rand.uniform(-14, 14), y + 18 + 60 * p + rand.uniform(-6, 6), 1.3, 0, TAU)
                ctx.set_source_rgba(1, 1, 1, 0.5 * (1 - p))
                ctx.fill()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.set_source_surface(slate_surface(), 0, 0)
    ctx.paint()
    title(ctx, t)
    marks(ctx, t)
    routes(ctx, t)
    the_pass(ctx, t)
    touchdown(ctx, t)
    dust(ctx, t, frame)
    eraser(ctx, t)
    finale(ctx, t)
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.3)
    opening = 1 - ease_out(span(t, 0.0, 0.25))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
