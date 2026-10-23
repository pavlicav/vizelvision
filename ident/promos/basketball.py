"""Basketball on VizelVision: a buzzer-beater, from the broadcast camera high behind the
shooter. No. 19 (VIZELVISION across the back of a pink jersey) waits beyond the arc with the
game clock at 3.9; two dribbles on the beat, then the open logo is the crossover, a bounce a
note, right, left, right and the gather. The shot goes up at 0.9, the buzzer sounds with
the ball in the air and the backboard's edge lights go red; nothing but net. Three fingers up
on each hand, the photographers' flashes, BANG! along the fascia. The house lights go down,
the spotlights find the court, and the wordmark drops in on the closed logo with BASKETBALL
underneath. The baseline LED board carries the game on air (master's live text).

Aired only during an NBA or WNBA game (LEAGUES). Arcas, the play-by-play:
"Vizzle Vision, for three!" / "Nothing but net!"
"""
import math
import random
from functools import lru_cache

import cairo

import arena
import neighborhood
from common import (INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in_out, ease_out,  # noqa: F401
                    glint, grain, inked, mix, pixel_text, rounded_rect, span, text_path, vignette)

ID = 'basketball'
NAME = 'Basketball on VizelVision'
KIND = 'ident'
ORDER = 22
DESCRIPTION = ('Only during basketball: a buzzer-beater from behind No. 19. The crossover on the open logo, the '
               'shot at 0.9, the buzzer with the ball in the air, nothing but net, and the wordmark on the closed '
               'logo under the spotlights. The baseline board carries the game on air. Arcas.')
DURATION = 10.0
STILL_AT = 8.6
LEAGUES = ('nba', 'wnba')

# Hit points (the music's too: promos/music.py).
DRIBBLES = (0.5, 1.0, 1.5, 1.75, 2.0, 2.5)    # the ball on the floor; the last four are the open logo
LOGO_DRIBBLES = (1.5, 1.75, 2.0, 2.5)
GATHER = 2.75                                  # both hands on the ball
JUMP = (2.8, 3.45)                             # off the floor and back
RELEASE = 3.0                                  # the shot (the clock at 0.9)
BUZZER = 3.9                                   # the clock at 0.0
SWISH = 4.2                                    # through the net
BOUNCES = (4.62, 4.98, 5.24, 5.42)             # the ball on the floor under the basket
THREES = 4.4                                   # three fingers up on each hand
FLASHES = (4.3, 6.3)                           # the photographers
BANG = 4.35                                    # BANG! on the fascia
DIM = (6.45, 6.95)                             # the house lights down
WORDMARK = 7.0                                 # the closed logo
BASKETBALL = (7.55, 8.2)
FADE = (9.25, 9.6)

# The camera: a pinhole at HEIGHT metres, FOCAL px, the horizon at HORIZON px. World x is
# metres to the right, y up from the floor, z away from the camera.
FOCAL, HEIGHT, HORIZON = 1800, 1.6, 380
PLAYER = (1.0, 9.0)                            # where No. 19 stands (x, z): just beyond the arc
BASKET = 16.5                                  # the rim's centre (z), at x 0
RIM_Y, RIM_R = 3.05, 0.2286
BOARD_Z = BASKET + 0.38
BASELINE = BASKET + 1.6
LED_Z = BASELINE + 1.4
FASCIA = 16                                    # the row of the stands where the ribbon board runs
BALL_R = 0.12
ARC = 0.6                                      # the shot's rise over a straight line to the rim (m)

WOOD = (0.86, 0.62, 0.36)
LANE = (0.05, 0.42, 0.45)
SKIN = (0.55, 0.36, 0.24)
HAIR = (0.1, 0.07, 0.06)
JERSEY = PINK
LEATHER = (0.9, 0.42, 0.12)
LED_RED = (1.0, 0.12, 0.1)
AMBER = (1.0, 0.68, 0.18)

OVERLAYS = [
    {'field': 'programme', 'box': [40, 470, 500, 46], 'from': 0.4, 'to': DIM[0],
     'style': {'font': 'Nimbus Sans Narrow', 'bold': True, 'size': 34, 'min_size': 16, 'color': [1.0, 0.68, 0.18],
               'upper': True, 'tracking': 0.1},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': 0.3}},
]


def project(x, y, z):
    return W / 2 + FOCAL * x / z, HORIZON - FOCAL * (y - HEIGHT) / z


def scale(z):
    """Pixels per metre at depth z."""
    return FOCAL / z


def floor_path(ctx, points):
    """A polygon on the floor: (x, z) points."""
    ctx.move_to(*project(points[0][0], 0, points[0][1]))
    for x, z in points[1:]:
        ctx.line_to(*project(x, 0, z))
    ctx.close_path()


def floor_arc(cx, cz, r, a0, a1, n=48):
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), cz + r * math.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


# ---------------------------------------------------------------- the arena (drawn once)

@lru_cache(maxsize=None)
def arena_surface():
    """The stands rising behind the baseline, full, under the house lights; the light rig."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, 470)
    g.add_color_stop_rgb(0, 0.03, 0.02, 0.06)
    g.add_color_stop_rgb(1, 0.13, 0.09, 0.16)
    ctx.set_source(g)
    ctx.paint()
    arena.stands(ctx, project, scale, LED_Z + 0.6, 0.9, skip=(FASCIA,))
    arena.rafters(ctx)
    return surface


@lru_cache(maxsize=None)
def court_surface():
    """The hardwood, the lines and the painted lane, the boards beyond the baseline, drawn once
    (ARGB: transparent above the floor)."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    floor_path(ctx, ((-30, 6), (30, 6), (30, LED_Z), (-30, LED_Z)))
    g = cairo.LinearGradient(0, project(0, 0, LED_Z)[1], 0, H)
    g.add_color_stop_rgb(0, *mix(WOOD, (0.3, 0.15, 0.05), 0.35))
    g.add_color_stop_rgb(1, *WOOD)
    ctx.set_source(g)
    ctx.fill()
    rand = random.Random(7)
    ctx.set_line_width(1)
    for k in range(-60, 61):                           # the boards, running baseline to baseline
        x = k * 0.25
        ctx.move_to(*project(x, 0, 6))
        ctx.line_to(*project(x, 0, BASELINE))
        ctx.set_source_rgba(0.35, 0.2, 0.08, 0.18 + 0.12 * rand.random())
        ctx.stroke()
    lane = ((-2.44, BASELINE), (2.44, BASELINE), (2.44, BASELINE - 5.8), (-2.44, BASELINE - 5.8))
    floor_path(ctx, lane)
    ctx.set_source_rgb(*LANE)
    ctx.fill()
    ctx.set_source_rgb(0.97, 0.97, 0.95)
    ctx.set_line_width(4)
    for points in (lane, ((-9, BASELINE), (9, BASELINE))):
        ctx.move_to(*project(points[0][0], 0, points[0][1]))
        for x, z in points[1:]:
            ctx.line_to(*project(x, 0, z))
        if len(points) > 2:
            ctx.close_path()
        ctx.stroke()
    ft = BASELINE - 5.8
    for points, dashed in ((floor_arc(0, ft, 1.8, math.pi, TAU), False), (floor_arc(0, ft, 1.8, 0, math.pi), True),
                           (floor_arc(0, BASKET, 1.22, math.pi, TAU), False)):
        ctx.set_dash([10, 10] if dashed else [])
        ctx.move_to(*project(*[points[0][0], 0, points[0][1]]))
        for x, z in points[1:]:
            ctx.line_to(*project(x, 0, z))
        ctx.stroke()
    ctx.set_dash([])
    corner = math.acos(6.7 / 7.24)                     # the three-point line: the arc and its corners
    arc = [(-6.7, BASELINE)] + floor_arc(0, BASKET, 7.24, math.pi + corner, TAU - corner, 80) + [(6.7, BASELINE)]
    ctx.move_to(*project(arc[0][0], 0, arc[0][1]))
    for x, z in arc[1:]:
        ctx.line_to(*project(x, 0, z))
    ctx.set_line_width(5)
    ctx.stroke()
    shine = cairo.LinearGradient(0, project(0, 0, BASELINE)[1], 0, H)   # the floor's gloss
    shine.add_color_stop_rgba(0, 1, 1, 1, 0.16)
    shine.add_color_stop_rgba(0.5, 1, 1, 1, 0.0)
    for x in (-5.5, -1.5, 3.5):
        ctx.move_to(*project(x - 0.6, 0, BASELINE))
        ctx.line_to(*project(x + 0.6, 0, BASELINE))
        ctx.line_to(*project(x + 1.6, 0, 6))
        ctx.line_to(*project(x - 1.6, 0, 6))
        ctx.close_path()
        ctx.set_source(shine)
        ctx.fill()
    # Beyond the baseline: the apron, the stanchion's padded base, the LED boards.
    floor_path(ctx, ((-30, BASELINE + 0.03), (30, BASELINE + 0.03), (30, LED_Z), (-30, LED_Z)))
    ctx.set_source_rgba(0.25, 0.12, 0.2, 0.9)
    ctx.fill()
    return surface


def led_board(ctx, t, frame, lit):
    """The LED boards along the baseline, either side of the stanchion: black glass, and on
    the right VIZELVISION 19 in amber pixels (the left carries master's text); all pink on
    the closed logo."""
    top, base = project(0, 0.95, LED_Z)[1], project(0, 0, LED_Z)[1]
    ctx.rectangle(0, top, W, base - top)
    ctx.set_source_rgb(0.03, 0.02, 0.04)
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.08)
    ctx.rectangle(0, top, W, 2)
    ctx.fill()
    cell = 5
    ctx.save()
    ctx.rectangle(*project(0.8, 0.95, LED_Z), W, base - top)
    ctx.clip()
    finale = span(t, WORDMARK, WORDMARK + 0.25)
    colour = mix(AMBER, PINK, finale)
    text = 'VIZELVISION 19   BASKETBALL   ' * 3
    offset = (t * 90) % ((len(text) // 3) * 6 * cell)
    pixel_text(ctx, text, 760 - offset, top + (base - top - 7 * cell) / 2, cell, mix((0.05, 0.04, 0.05), colour, lit))
    ctx.restore()


def stanchion(ctx):
    """The padded base behind the baseline and the post up to the board's arm."""
    x0, y0 = project(-0.75, 1.0, LED_Z - 0.05)
    x1, y1 = project(0.75, 0.0, LED_Z - 0.05)
    rounded_rect(ctx, x0, y0, x1 - x0, y1 - y0, 6)
    ctx.set_source_rgb(0.08, 0.06, 0.12)
    ctx.fill()
    ctx.set_source_rgb(*PINK)
    ctx.rectangle(x0, y0 + 10, x1 - x0, 6)
    ctx.fill()
    font_y = y0 + 52
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(20)
    ctx.new_path()
    text_path(ctx, '19', (x0 + x1) / 2, font_y, tracking=2, align='center')
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    px0, py0 = project(-0.11, 3.6, LED_Z - 0.3)
    px1, py1 = project(0.11, 1.0, LED_Z - 0.3)
    ctx.rectangle(px0, py0, px1 - px0, py1 - py0)
    ctx.set_source_rgb(0.16, 0.16, 0.2)
    ctx.fill()


def clock_text(t):
    return '%.1f' % (max(0, math.floor((BUZZER - t) * 10 + 1e-6)) / 10)


def board(ctx, t):
    """The backboard: glass over the stands, its frame, the target square, the edge lights
    that go red at the buzzer, the padding; the game clock on top."""
    x0, y0 = project(-0.915, 3.97, BOARD_Z)
    x1, y1 = project(0.915, 2.9, BOARD_Z)
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.set_source_rgba(0.85, 0.9, 1.0, 0.13)
    ctx.fill()
    ctx.move_to(x0 + 30, y0)                           # a reflection across the glass
    ctx.line_to(x0 + 70, y0)
    ctx.line_to(x0 + 20, y1)
    ctx.line_to(x0 - 20 + 30, y1)
    ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.07)
    ctx.fill()
    red = 1.0 if t >= BUZZER else 0.0
    if red:
        blink = 0.75 + 0.25 * math.cos((t - BUZZER) * 14)
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        for width, alpha in ((22, 0.18), (12, 0.35)):
            ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
            ctx.set_source_rgba(*LED_RED, alpha * blink)
            ctx.set_line_width(width)
            ctx.stroke()
        ctx.restore()
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.set_source_rgb(*(mix(WHITE, LED_RED, 0.85) if red else (0.92, 0.92, 0.95)))
    ctx.set_line_width(5)
    ctx.stroke()
    sx0, sy0 = project(-0.295, 3.5, BOARD_Z)
    sx1, sy1 = project(0.295, 3.05, BOARD_Z)
    ctx.rectangle(sx0, sy0, sx1 - sx0, sy1 - sy0)
    ctx.set_source_rgb(0.95, 0.95, 0.97)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.rectangle(x0 - 3, y1, x1 - x0 + 6, 10)        # the pad along the bottom edge
    ctx.set_source_rgb(0.1, 0.08, 0.14)
    ctx.fill()
    cx0, cy0 = project(-0.38, 4.38, BOARD_Z)          # the clock unit
    cx1, cy1 = project(0.38, 3.99, BOARD_Z)
    rounded_rect(ctx, cx0, cy0, cx1 - cx0, cy1 - cy0, 4)
    ctx.set_source_rgb(0.05, 0.05, 0.06)
    ctx.fill()
    text = clock_text(t)
    lit = 1.0 if t < BUZZER or math.cos((t - BUZZER) * 9) > -0.3 else 0.35
    h = (cy1 - cy0) * 0.62
    arena.seven_segment(ctx, text, (cx0 + cx1) / 2 - h * 0.85, cy0 + (cy1 - cy0 - h) / 2, h, mix((0.2, 0, 0), LED_RED, lit))


# ---------------------------------------------------------------- the hoop

def net_sway(t):
    """(sideways, lift) of the net's bottom, in metres: it snaps up at the swish and swings."""
    if t < SWISH - 0.08:
        return 0.0, 0.0
    u = t - (SWISH - 0.08)
    return 0.05 * math.sin(u * 15) * math.exp(-u * 2.2), 0.17 * math.exp(-u * 5) * (1 - math.exp(-u * 40))


def rim_points(front):
    angles = [math.pi + math.pi * k / 24 for k in range(25)] if front else [math.pi * k / 24 for k in range(25)]
    return [project(RIM_R * math.cos(a), RIM_Y, BASKET + RIM_R * math.sin(a)) for a in angles]


def rim(ctx, front):
    pts = rim_points(front)
    ctx.move_to(*pts[0])
    for p in pts[1:]:
        ctx.line_to(*p)
    ctx.set_source_rgb(0.95, 0.38, 0.08)
    ctx.set_line_width(4.5)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()


def net(ctx, t, front):
    """Twelve cords from the rim to the narrower ring below, laced in diamonds."""
    side, lift = net_sway(t)
    n = 12
    rows = 5
    bottom = 0.45 - lift
    points = []
    for r in range(rows + 1):
        v = r / rows
        radius = RIM_R * (1 - 0.42 * v)
        drop = bottom * v
        row = []
        for k in range(n):
            a = TAU * (k + 0.5 * (r % 2)) / n
            row.append((radius * math.cos(a) + side * v * v, RIM_Y - drop, BASKET + radius * math.sin(a), a))
        points.append(row)
    ctx.set_line_width(1.6)
    ctx.set_source_rgba(1, 1, 1, 0.85 if front else 0.45)
    for r in range(rows):
        for k in range(n):
            a = points[r][k]
            for b in (points[r + 1][k], points[r + 1][(k - 1 + (r % 2) * 2) % n if r % 2 == 0 else (k + 1) % n]):
                is_front = math.sin(a[3]) < 0
                if is_front != front:
                    continue
                ctx.move_to(*project(*a[:3]))
                ctx.line_to(*project(*b[:3]))
    ctx.stroke()


# ---------------------------------------------------------------- No. 19

POSES = {
    # metres: x right, y up, from the floor between the feet (seen from behind).
    'dribble': {'pelvis': (0, 0.92), 'neck': (0, 1.48), 'head': (0.0, 1.66), 'ls': (-0.22, 1.45), 'rs': (0.22, 1.45),
                'le': (-0.4, 1.2), 'lh': (-0.5, 1.05), 're': (0.36, 1.13), 'rh': (0.42, 0.86),
                'lk': (-0.25, 0.5), 'rk': (0.25, 0.5), 'lf': (-0.32, 0.04), 'rf': (0.32, 0.04)},
    'cross': {'pelvis': (0, 0.9), 'neck': (0, 1.46), 'head': (0.0, 1.64), 'ls': (-0.22, 1.43), 'rs': (0.22, 1.43),
              're': (0.4, 1.2), 'rh': (0.5, 1.05), 'le': (-0.36, 1.12), 'lh': (-0.42, 0.85),
              'lk': (-0.25, 0.5), 'rk': (0.25, 0.5), 'lf': (-0.32, 0.04), 'rf': (0.32, 0.04)},
    'gather': {'pelvis': (0, 0.82), 'neck': (0, 1.38), 'head': (0.0, 1.56), 'ls': (-0.22, 1.35), 'rs': (0.22, 1.35),
               'le': (-0.3, 1.08), 'lh': (-0.15, 1.12), 're': (0.3, 1.08), 'rh': (0.15, 1.12),
               'lk': (-0.24, 0.44), 'rk': (0.24, 0.44), 'lf': (-0.28, 0.04), 'rf': (0.28, 0.04)},
    'shoot': {'pelvis': (0, 1.0), 'neck': (0, 1.55), 'head': (0.0, 1.73), 'ls': (-0.21, 1.53), 'rs': (0.21, 1.53),
              'le': (-0.18, 1.86), 'lh': (-0.02, 2.12), 're': (0.3, 1.88), 'rh': (0.16, 2.2),
              'lk': (-0.12, 0.53), 'rk': (0.13, 0.53), 'lf': (-0.13, 0.06), 'rf': (0.14, 0.06)},
    'follow': {'pelvis': (0, 1.0), 'neck': (0, 1.55), 'head': (0.0, 1.73), 'ls': (-0.21, 1.53), 'rs': (0.21, 1.53),
               'le': (-0.25, 1.85), 'lh': (-0.16, 2.08), 're': (0.22, 1.95), 'rh': (0.12, 2.32),
               'lk': (-0.12, 0.53), 'rk': (0.13, 0.53), 'lf': (-0.13, 0.06), 'rf': (0.14, 0.06)},
    'threes': {'pelvis': (0, 0.98), 'neck': (0, 1.54), 'head': (0.0, 1.72), 'ls': (-0.22, 1.51), 'rs': (0.22, 1.51),
               'le': (-0.48, 1.7), 'lh': (-0.56, 2.02), 're': (0.48, 1.7), 'rh': (0.56, 2.02),
               'lk': (-0.18, 0.52), 'rk': (0.18, 0.52), 'lf': (-0.24, 0.04), 'rf': (0.24, 0.04)},
}
# (time, pose): the pose eases from one to the next.
KEYS = ((0.0, 'dribble'), (1.5, 'dribble'), (1.66, 'cross'), (1.86, 'dribble'), (2.6, 'dribble'), (2.75, 'gather'),
        (2.85, 'gather'), (2.98, 'shoot'), (3.08, 'follow'), (4.3, 'follow'), (4.5, 'threes'))


def pose(t):
    for (t0, a), (t1, b) in zip(KEYS, KEYS[1:]):
        if t < t1:
            k = ease_in_out(span(t, t0, t1))
            return {j: (POSES[a][j][0] + (POSES[b][j][0] - POSES[a][j][0]) * k,
                        POSES[a][j][1] + (POSES[b][j][1] - POSES[a][j][1]) * k) for j in POSES[a]}
    return dict(POSES[KEYS[-1][1]])


def lift(t):
    """How high off the floor (m): the jump, and a hop for the threes."""
    jump = math.sin(math.pi * span(t, *JUMP)) * 0.55
    hop = math.sin(math.pi * span(t, THREES, THREES + 0.3)) * 0.12
    return jump + hop


def to_screen(px, py):
    x, z = PLAYER
    return project(x + px, py, z)


def player(ctx, t):
    p = pose(t)
    up = lift(t)
    # A dribbling hand rides the ball's top; the threes hands bob.
    hand = dribble_hand(t)
    if hand:
        side, height = hand
        key = 'rh' if side > 0 else 'lh'
        p[key] = (p[key][0], height)
    s = scale(PLAYER[1])
    j = {k: to_screen(x, y + up) for k, (x, y) in p.items()}
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    fx, fy = to_screen(0, 0)                           # the shadow on the floor
    ctx.save()
    ctx.translate(fx, fy)
    ctx.scale(1, 0.18)
    ctx.arc(0, 0, 0.6 * s * (1 - 0.35 * up), 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, 0.35 - 0.2 * up)
    ctx.fill()

    def limb(points, colour, width):
        ctx.move_to(*points[0])
        for pt in points[1:]:
            ctx.line_to(*pt)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(width + 6)
        ctx.stroke_preserve()
        ctx.set_source_rgb(*colour)
        ctx.set_line_width(width)
        ctx.stroke()

    for side in ('l', 'r'):                            # legs, sneakers
        hip = to_screen((-0.12 if side == 'l' else 0.12), p['pelvis'][1] + up - 0.02)
        limb((hip, j[side + 'k'], j[side + 'f']), SKIN, 0.13 * s)
        foot = j[side + 'f']
        ctx.save()
        ctx.translate(foot[0], foot[1] - 0.03 * s)
        rounded_rect(ctx, -0.09 * s, -0.06 * s, 0.18 * s, 0.11 * s, 0.04 * s)
        ctx.restore()
        inked(ctx, WHITE, 3, (0, 0))
        ctx.save()
        ctx.translate(foot[0], foot[1] - 0.03 * s)
        ctx.rectangle(-0.09 * s, -0.01 * s, 0.18 * s, 0.03 * s)
        ctx.set_source_rgb(*TEAL)
        ctx.fill()
        ctx.restore()
        knee = j[side + 'k']                           # the sock
        ctx.move_to(foot[0], foot[1] - 0.06 * s)
        ctx.line_to(foot[0] + (knee[0] - foot[0]) * 0.22, foot[1] - 0.06 * s + (knee[1] - foot[1]) * 0.22)
        ctx.set_source_rgb(*WHITE)
        ctx.set_line_width(0.12 * s)
        ctx.stroke()
    pl = to_screen(-0.2, p['pelvis'][1] + up + 0.05)  # the shorts
    pr = to_screen(0.2, p['pelvis'][1] + up + 0.05)
    lk, rk = j['lk'], j['rk']
    ctx.move_to(*pl)
    ctx.line_to(*pr)
    ctx.line_to(pr[0] + (rk[0] - pr[0]) * 0.62 + 0.07 * s, pr[1] + (rk[1] - pr[1]) * 0.62)
    ctx.line_to(pr[0] + (rk[0] - pr[0]) * 0.62 - 0.12 * s, pr[1] + (rk[1] - pr[1]) * 0.62)
    ctx.line_to((pl[0] + pr[0]) / 2, (pl[1] + pr[1]) / 2 + 0.2 * s)
    ctx.line_to(pl[0] + (lk[0] - pl[0]) * 0.62 + 0.12 * s, pl[1] + (lk[1] - pl[1]) * 0.62)
    ctx.line_to(pl[0] + (lk[0] - pl[0]) * 0.62 - 0.07 * s, pl[1] + (lk[1] - pl[1]) * 0.62)
    ctx.close_path()
    inked(ctx, JERSEY, 3, (0, 0))
    for side in ('l', 'r'):                            # arms (behind the jersey's shoulders)
        limb((j[side + 's'], j[side + 'e'], j[side + 'h']), SKIN, 0.1 * s)
    ls, rs = j['ls'], j['rs']                          # the jersey: a tank top, from behind
    ctx.move_to(ls[0] + 0.05 * s, ls[1] - 0.02 * s)
    ctx.line_to(ls[0] + 0.1 * s, ls[1] - 0.04 * s)
    ctx.curve_to(j['neck'][0] - 0.05 * s, j['neck'][1] + 0.02 * s, j['neck'][0] + 0.05 * s, j['neck'][1] + 0.02 * s,
                 rs[0] - 0.1 * s, rs[1] - 0.04 * s)
    ctx.line_to(rs[0] - 0.05 * s, rs[1] - 0.02 * s)
    ctx.curve_to(rs[0] - 0.02 * s, rs[1] + 0.15 * s, rs[0] - 0.02 * s, rs[1] + 0.25 * s, pr[0] + 0.02 * s, pr[1] - 0.05 * s)
    ctx.line_to(pl[0] - 0.02 * s, pl[1] - 0.05 * s)
    ctx.curve_to(ls[0] + 0.02 * s, ls[1] + 0.25 * s, ls[0] + 0.02 * s, ls[1] + 0.15 * s, ls[0] + 0.05 * s, ls[1] - 0.02 * s)
    ctx.close_path()
    inked(ctx, JERSEY, 3, (0, 0))
    cx = (ls[0] + rs[0]) / 2                           # VIZELVISION and 19 across the back
    ctx.save()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(0.07 * s)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', cx, ls[1] + 0.13 * s, tracking=0.004 * s, align='center')
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.set_font_size(0.24 * s)
    ctx.new_path()
    text_path(ctx, '19', cx, ls[1] + 0.38 * s, tracking=0.01 * s, align='center')
    path = ctx.copy_path()
    ctx.set_source_rgb(*TEAL)
    ctx.set_line_width(0.02 * s)
    ctx.stroke()
    ctx.append_path(path)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.restore()
    nx, ny = j['neck']
    limb((j['neck'], (nx, ny - 0.06 * s)), SKIN, 0.09 * s)
    hx, hy = j['head']                                 # the head, from behind: ears and short hair
    for side in (-1, 1):
        ctx.arc(hx + side * 0.1 * s, hy + 0.01 * s, 0.032 * s, 0, TAU)
        inked(ctx, SKIN, 2.5, (0, 0))
    ctx.arc(hx, hy, 0.105 * s, 0, TAU)
    inked(ctx, SKIN, 3, (0, 0))
    ctx.arc(hx, hy - 0.004 * s, 0.1 * s, math.pi * 0.93, math.pi * 2.07)
    ctx.curve_to(hx + 0.08 * s, hy + 0.08 * s, hx - 0.08 * s, hy + 0.08 * s, hx - 0.1 * s, hy + 0.03 * s)
    ctx.close_path()
    ctx.set_source_rgb(*HAIR)
    ctx.fill()
    for side in ('l', 'r'):                            # hands; three fingers up for the threes
        hx, hy = j[side + 'h']
        threes = span(t, THREES - 0.1, THREES + 0.05)
        if threes > 0:
            for f in (-1, 0, 1):
                ctx.move_to(hx + f * 0.025 * s, hy)
                ctx.line_to(hx + f * 0.032 * s, hy - 0.09 * s * threes)
            ctx.set_source_rgb(*INK)
            ctx.set_line_width(0.035 * s)
            ctx.stroke_preserve()
            ctx.set_source_rgb(*SKIN)
            ctx.set_line_width(0.02 * s)
            ctx.stroke()
        ctx.arc(hx, hy, 0.05 * s, 0, TAU)
        inked(ctx, SKIN, 2.5, (0, 0))
    ctx.restore()


# ---------------------------------------------------------------- the ball

# Where the ball is between dribbles: (the time it leaves a hand, the hand: +1 right, -1 left).
HANDS = ((0.25, 1), (0.75, 1), (1.25, 1), (1.62, -1), (1.88, 1), (2.25, 1))
HAND_HEIGHT = 0.86


def dribble_hand(t):
    """(side, height) of the hand on the ball while dribbling, or None."""
    if t >= DRIBBLES[-1] + 0.2:
        return None
    for k, bounce in enumerate(DRIBBLES):
        start = HANDS[k][0]
        if start <= t < bounce:
            return HANDS[k][1], HAND_HEIGHT - 0.25 * ease_out(span(t, start, start + 0.08))
        if k + 1 < len(DRIBBLES):
            catch = HANDS[k + 1][0]
            if bounce <= t < catch:
                return HANDS[k + 1][1], HAND_HEIGHT - 0.25 * (1 - ease_out(span(t, catch - 0.08, catch)))
    return None


def ball_local(t):
    """The ball (x, y in metres from the player's feet) before the gather: down from a hand
    to the floor, up to the next hand (across the body on a crossover)."""
    top = HAND_HEIGHT - BALL_R
    if t < HANDS[0][0]:
        return 0.44 * HANDS[0][1], top
    for k, bounce in enumerate(DRIBBLES):
        leave, side = HANDS[k]
        catch, nxt = HANDS[k + 1] if k + 1 < len(HANDS) else (GATHER, 0)
        floor_x = 0.22 * (side + nxt) if nxt else 0.3 * side
        if t < bounce:
            u = span(t, leave, bounce) ** 1.4
            return 0.44 * side + (floor_x - 0.44 * side) * u, top + (BALL_R - top) * u
        if t < catch:
            u = 1 - (1 - span(t, bounce, catch)) ** 1.4
            end_x, end_y = (0.44 * nxt, top) if nxt else (0.0, 1.0)
            return floor_x + (end_x - floor_x) * u, BALL_R + (end_y - BALL_R) * u
    return 0.0, 1.0


def release_point():
    p = POSES['shoot']
    up = lift(RELEASE)
    return PLAYER[0] + p['rh'][0] - 0.04, p['rh'][1] + up + 0.16, PLAYER[1] + 0.05


def flight(t):
    """The ball's world position from the release to the floor under the basket."""
    x0, y0, z0 = release_point()
    if t < SWISH:
        u = span(t, RELEASE, SWISH)
        x = x0 + (0 - x0) * u
        z = z0 + (BASKET - z0) * u
        base = y0 + (RIM_Y + 0.05 - y0) * u
        return x, base + 4 * ARC * u * (1 - u), z
    # Through the net and down; then the bounces, drifting toward the baseline.
    if t < BOUNCES[0]:
        u = span(t, SWISH, BOUNCES[0])
        return 0.0, RIM_Y - (RIM_Y - BALL_R) * u ** 1.7, BASKET + 0.25 * u
    for (a, b), height in zip(zip(BOUNCES, BOUNCES[1:]), (0.6, 0.3, 0.12)):
        if t < b:
            u = span(t, a, b)
            return 0.0, BALL_R + height * 4 * u * (1 - u), BASKET + 0.25 + 0.6 * span(t, BOUNCES[0], BOUNCES[-1])
    roll = t - BOUNCES[-1]
    return 0.0, BALL_R, BASKET + 0.85 + min(0.9, roll * 0.5)


def ball(ctx, x, y, r, spin, shade=1.0):
    ctx.save()
    ctx.translate(x, y)
    ctx.arc(0, 0, r, 0, TAU)
    g = cairo.RadialGradient(-r * 0.35, -r * 0.4, r * 0.1, 0, 0, r)
    g.add_color_stop_rgb(0, *mix(LEATHER, WHITE, 0.25 * shade))
    g.add_color_stop_rgb(1, *mix(LEATHER, (0.2, 0.05, 0), 0.45))
    ctx.set_source(g)
    ctx.fill_preserve()
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(max(1.0, r * 0.1))
    ctx.stroke()
    ctx.arc(0, 0, r, 0, TAU)
    ctx.clip()
    ctx.rotate(spin)
    ctx.set_line_width(max(0.8, r * 0.07))
    ctx.move_to(-r, 0)
    ctx.line_to(r, 0)
    ctx.move_to(0, -r)
    ctx.line_to(0, r)
    for side in (-1, 1):
        ctx.move_to(side * r * 0.55, -r)
        ctx.curve_to(side * r * 0.2, -r * 0.4, side * r * 0.2, r * 0.4, side * r * 0.55, r)
    ctx.stroke()
    ctx.restore()


def ball_shadow(ctx, wx, wy, wz):
    sx, sy = project(wx, 0, wz)
    k = scale(wz)
    a = max(0.0, 0.4 - 0.12 * wy)
    if a <= 0:
        return
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(1, 0.25)
    ctx.arc(0, 0, BALL_R * k * (1 + 0.3 * wy), 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, a)
    ctx.fill()


def held_ball(ctx, t):
    """The ball while dribbling and in the hands, before the shot."""
    if t >= RELEASE:
        return
    s = scale(PLAYER[1])
    if t < GATHER:
        bx, by = ball_local(t)
    else:
        p = pose(t)
        rh, lh = p['rh'], p['lh']
        bx = (rh[0] + lh[0]) / 2
        by = (rh[1] + lh[1]) / 2 + lift(t) + BALL_R * 0.9 * span(t, 2.85, 2.98)
    wx, wz = PLAYER[0] + bx, PLAYER[1] - 0.1 * span(t, GATHER - 0.1, GATHER)
    ball_shadow(ctx, wx, by, wz)
    sx, sy = project(wx, by, wz)
    ball(ctx, sx, sy, BALL_R * s, t * 9)


def flying_ball(ctx, t, inside):
    """The ball after the release. inside: the part of it drawn between the rim's back and
    the net's front (from just above the rim to the floor)."""
    if t < RELEASE:
        return
    x, y, z = flight(t)
    near = t >= SWISH - 0.12
    if near != inside:
        return
    if t >= SWISH:
        ball_shadow(ctx, x, y, z)
    sx, sy = project(x, y, z)
    ball(ctx, sx, sy, BALL_R * scale(z), -t * 14)


# ---------------------------------------------------------------- the house

def fascia(ctx, t, frame):
    """The ribbon board along the fascia between the bowls: the score bug's colours scrolling,
    BANG! flashing after the shot, VIZELVISION on the closed logo."""
    z, y = LED_Z + 0.6 + 0.85 * FASCIA, 0.9 + 0.42 * FASCIA
    top, base = project(0, y + 0.9, z)[1], project(0, y, z)[1]
    ctx.rectangle(0, top, W, base - top)
    ctx.set_source_rgb(0.02, 0.02, 0.03)
    ctx.fill()
    cell = max(3, int((base - top) / 9))
    y0 = top + (base - top - 7 * cell) / 2
    if t >= WORDMARK:
        text = '  VIZELVISION 19  ' * 4
        offset = (t * 70) % (18 * 6 * cell)
        pixel_text(ctx, text, -offset, y0, cell, PINK)
    elif t >= BANG:
        on = int((t - BANG) * 6) % 2 == 0
        for x in range(0, W, 260):
            pixel_text(ctx, 'BANG!', x + 30, y0, cell, YELLOW if on else (1.0, 0.35, 0.1))
    else:
        text = 'DEFENSE  DEFENSE  ' * 4
        offset = (t * 70) % (18 * 6 * cell)
        pixel_text(ctx, text, -offset, y0, cell, mix(AMBER, (0.04, 0.03, 0.03), 0.15))


def flashes(ctx, t, frame):
    if not FLASHES[0] <= t < FLASHES[1]:
        return
    rand = random.Random(frame // 3)
    density = 1 - span(t, FLASHES[0] + 0.8, FLASHES[1])
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for _ in range(int(9 * density) + 1):
        x, y = rand.uniform(20, W - 20), rand.uniform(60, 440)
        r = rand.uniform(6, 16)
        halo = cairo.RadialGradient(x, y, 0, x, y, r * 3)
        halo.add_color_stop_rgba(0, 1, 1, 1, 0.9)
        halo.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(halo)
        ctx.arc(x, y, r * 3, 0, TAU)
        ctx.fill()
    ctx.restore()


def spotlights(ctx, t):
    """The house lights down, and four spots sweeping in to the circle under the wordmark."""
    p = span(t, *DIM)
    if p <= 0:
        return
    ctx.set_source_rgba(0.02, 0.0, 0.05, 0.72 * ease_in_out(p))
    ctx.paint()
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for k, (start, colour) in enumerate(((-6, PINK), (6, TEAL), (-3, WHITE), (3, YELLOW))):
        settle = ease_in_out(span(t, DIM[0] + 0.1 * k, WORDMARK + 0.2))
        x = start * (1 - settle) + (k - 1.5) * 0.9 * settle
        z = 12.0 + 2.5 * math.sin(t * 1.3 + k)
        sx, sy = project(x, 0, z)
        rx = 2.2 * scale(z)
        g = cairo.RadialGradient(sx, sy, 0, sx, sy, rx)
        g.add_color_stop_rgba(0, *colour, 0.35 * p)
        g.add_color_stop_rgba(1, *colour, 0)
        ctx.save()
        ctx.translate(sx, sy)
        ctx.scale(1, 0.3)
        ctx.translate(-sx, -sy)
        ctx.arc(sx, sy, rx, 0, TAU)
        ctx.set_source(g)
        ctx.fill()
        ctx.restore()
        beam = cairo.LinearGradient(sx, 0, sx, sy)     # the beam, from the rafters
        beam.add_color_stop_rgba(0, *colour, 0.0)
        beam.add_color_stop_rgba(1, *colour, 0.12 * p)
        ctx.move_to(W / 2 + (k - 1.5) * 260 - 20, 0)
        ctx.line_to(W / 2 + (k - 1.5) * 260 + 20, 0)
        ctx.line_to(sx + rx * 0.5, sy)
        ctx.line_to(sx - rx * 0.5, sy)
        ctx.close_path()
        ctx.set_source(beam)
        ctx.fill()
    ctx.restore()


def finale(ctx, t):
    if t < WORDMARK - 0.05:
        return
    neighborhood.lockup(ctx, t, WORDMARK, 330, scale=0.66)
    p = span(t, *BASKETBALL)
    if p > 0:
        ctx.save()
        ctx.rectangle(0, 0, W / 2 - 300 + 600 * ease_in_out(p), H)
        ctx.clip()
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(46)
        ctx.new_path()
        text_path(ctx, 'BASKETBALL', W / 2, 405, tracking=16, align='center')
        inked(ctx, LEATHER, 5, (6, 6))
        ctx.restore()
    for i, at in enumerate((WORDMARK + 0.25, WORDMARK + 1.0, WORDMARK + 2.0)):
        q = span(t, at, at + 0.5)
        if 0 < q < 1:
            glint(ctx, (370, 910, 640)[i], (250, 262, 222)[i], 22 * math.sin(math.pi * q), q * 3, 1)


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.set_source_surface(arena_surface(), 0, 0)
    ctx.paint()
    fascia(ctx, t, frame)
    flashes(ctx, t, frame)
    led_board(ctx, t, frame, 1.0)
    ctx.set_source_surface(court_surface(), 0, 0)
    ctx.paint()
    stanchion(ctx)
    board(ctx, t)
    rim(ctx, front=False)
    net(ctx, t, front=False)
    flying_ball(ctx, t, inside=True)
    net(ctx, t, front=True)
    rim(ctx, front=True)
    held_ball(ctx, t)
    player(ctx, t)
    flying_ball(ctx, t, inside=False)
    spotlights(ctx, t)
    finale(ctx, t)
    vignette(ctx, 0.4)
    grain(ctx, frame, 0.25)
    opening = 1 - ease_out(span(t, 0.0, 0.25))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
