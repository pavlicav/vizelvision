"""Hockey on VizelVision: the pipes play the logo. From the ice, low behind No. 19 in the high
slot: the other side has pulled its goalie, the clock says 0:04, EMPTY NET. Four taps of the
stick handling the puck, the wind-up, the slapshot; and the puck rings off the left post, the
crossbar and the right post, a ping a note of the open logo, pops up and comes down bar-down
on the last. The goal light spins, the horn, the organ, the stick up. The house lights go
down, pink and teal sweep the ice, and the wordmark drops in on the closed logo with HOCKEY
underneath. The LED dasher board carries the game on air (master's live text).

Aired only during an NHL game (LEAGUES). Odysseus, the play-by-play:
"Vizzle Vision shoots..." / "...and scores!"
"""
import math
import random
from functools import lru_cache

import cairo

import arena
import neighborhood
from common import (INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, ease_in_out, ease_out,  # noqa: F401
                    glint, grain, inked, mix, pixel_text, rounded_rect, span, text_path, vignette)

ID = 'hockey'
NAME = 'Hockey on VizelVision'
KIND = 'ident'
ORDER = 23
DESCRIPTION = ('Only during hockey: an empty net at 0:04. The slapshot rings off the left post, the crossbar and '
               'the right post on the open logo and goes in bar-down; the goal light, the horn, the organ, and '
               'the wordmark on the closed logo over the ice. The dasher board carries the game on air. Odysseus.')
DURATION = 10.0
STILL_AT = 8.6
LEAGUES = ('nhl',)

# Hit points (the music's too: promos/music.py).
TAPS = (0.5, 0.75, 1.0, 1.25)                  # the stick handling the puck, side to side
WINDUP = (1.3, 1.65)
SHOT = 1.75                                    # the slapshot
PIPES = (2.0, 2.25, 2.5, 3.0)                  # left post, crossbar, right post, bar-down: the open logo
GOAL = 3.15                                    # the puck in the back of the net
HORN = 3.2                                     # the goal horn and the light
CELEBRATE = (3.3, 3.7)                         # the stick up
DIM = (6.45, 6.95)                             # the house lights down
WORDMARK = 7.0                                 # the closed logo
HOCKEY = (7.55, 8.2)
FADE = (9.25, 9.6)

# The camera: a pinhole at HEIGHT metres, FOCAL px, the horizon at HORIZON px; world x is
# metres right, y up from the ice, z away from the camera.
FOCAL, HEIGHT, HORIZON = 2200, 1.4, 350
PLAYER = (-1.5, 9.0)                           # No. 19's skates (x, z)
GOAL_Z = 17.0                                  # the goal line
POST_X, BAR_Y = 0.915, 1.22
NET_DEPTH = 1.1
BOARDS_Z = GOAL_Z + 3.4
BOARD_TOP, GLASS_TOP = 1.07, 2.6
PUCK_R = 0.038

ICE = (0.9, 0.95, 0.99)
CREASE = (0.35, 0.65, 0.95)
GOAL_RED = (0.85, 0.08, 0.1)
JERSEY = PINK
PANTS = (0.08, 0.06, 0.1)
AMBER = (1.0, 0.68, 0.18)

OVERLAYS = [
    {'field': 'programme', 'box': [830, 412, 430, 46], 'from': 0.4, 'to': DIM[0],
     'style': {'font': 'Nimbus Sans Narrow', 'bold': True, 'size': 34, 'min_size': 16, 'color': [1.0, 0.68, 0.18],
               'upper': True, 'tracking': 0.1},
     'enter': {'kind': 'fade', 'seconds': 0.3}, 'exit': {'kind': 'fade', 'seconds': 0.3}},
]


def project(x, y, z):
    return W / 2 + FOCAL * x / z, HORIZON - FOCAL * (y - HEIGHT) / z


def scale(z):
    return FOCAL / z


def poly(ctx, points):
    """A path through world points (x, y, z)."""
    ctx.move_to(*project(*points[0]))
    for p in points[1:]:
        ctx.line_to(*project(*p))


def ice_arc(cx, cz, r, a0, a1, n=48):
    return [(cx + r * math.cos(a0 + (a1 - a0) * k / n), 0, cz + r * math.sin(a0 + (a1 - a0) * k / n))
            for k in range(n + 1)]


# ---------------------------------------------------------------- the rink (drawn once)

@lru_cache(maxsize=None)
def rink_surface():
    """The stands over the glass, the boards, the ice with its lines and the crease."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    g = cairo.LinearGradient(0, 0, 0, 400)
    g.add_color_stop_rgb(0, 0.03, 0.02, 0.06)
    g.add_color_stop_rgb(1, 0.13, 0.09, 0.16)
    ctx.set_source(g)
    ctx.paint()
    arena.stands(ctx, project, scale, BOARDS_Z + 1.2, 1.4, rows=22, seed=23)
    arena.rafters(ctx)
    gx0, gy0 = project(-30, GLASS_TOP, BOARDS_Z)       # the glass, and its seams
    gx1, gy1 = project(30, BOARD_TOP, BOARDS_Z)
    ctx.rectangle(0, gy0, W, gy1 - gy0)
    ctx.set_source_rgba(0.75, 0.85, 0.95, 0.12)
    ctx.fill()
    ctx.set_source_rgba(1, 1, 1, 0.35)
    ctx.set_line_width(2)
    for k in range(-12, 13):
        x = k * 1.5
        ctx.move_to(*project(x, GLASS_TOP, BOARDS_Z))
        ctx.line_to(*project(x, BOARD_TOP, BOARDS_Z))
    ctx.stroke()
    ctx.rectangle(0, gy0 - 3, W, 4)
    ctx.fill()
    bx0, by0 = project(-30, BOARD_TOP, BOARDS_Z)       # the boards: white, the cap, the kick plate
    bx1, by1 = project(30, 0, BOARDS_Z)
    ctx.rectangle(0, by0, W, by1 - by0)
    ctx.set_source_rgb(0.95, 0.96, 0.97)
    ctx.fill()
    ctx.rectangle(0, by0, W, 6)
    ctx.set_source_rgb(0.2, 0.25, 0.4)
    ctx.fill()
    kick = project(0, 0.22, BOARDS_Z)[1]
    ctx.rectangle(0, kick, W, by1 - kick)
    ctx.set_source_rgb(0.95, 0.8, 0.15)
    ctx.fill()
    for x0, x1 in ((-6.0, -1.6),):                      # a printed panel on the left
        px0, py0 = project(x0, 0.95, BOARDS_Z)
        px1, py1 = project(x1, 0.3, BOARDS_Z)
        ctx.rectangle(px0, py0, px1 - px0, py1 - py0)
        ctx.set_source_rgb(*PINK)
        ctx.fill()
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size((py1 - py0) * 0.55)
        ctx.new_path()
        text_path(ctx, 'VIZELVISION 19', (px0 + px1) / 2, py1 - (py1 - py0) * 0.28, tracking=3, align='center')
        ctx.set_source_rgb(*WHITE)
        ctx.fill()
    # The ice.
    top = project(0, 0, BOARDS_Z)[1]
    g = cairo.LinearGradient(0, top, 0, H)
    g.add_color_stop_rgb(0, *mix(ICE, (0.6, 0.7, 0.85), 0.35))
    g.add_color_stop_rgb(1, *ICE)
    ctx.rectangle(0, top, W, H - top)
    ctx.set_source(g)
    ctx.fill()
    reflect = cairo.LinearGradient(0, top, 0, top + 60)  # the boards' reflection in it
    reflect.add_color_stop_rgba(0, 1, 1, 1, 0.5)
    reflect.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.rectangle(0, top, W, 60)
    ctx.set_source(reflect)
    ctx.fill()
    rand = random.Random(4)                             # skate marks
    ctx.set_line_width(1)
    for _ in range(140):
        x, z = rand.uniform(-6, 6), rand.uniform(8, BOARDS_Z)
        a = rand.uniform(-0.6, 0.6)
        length = rand.uniform(0.5, 2.5)
        poly(ctx, ((x, 0, z), (x + length * math.sin(a), 0, z + length * math.cos(a))))
        ctx.set_source_rgba(0.55, 0.65, 0.78, rand.uniform(0.15, 0.4))
        ctx.stroke()
    crease = ice_arc(0, GOAL_Z, 1.83, math.pi, TAU, 40)
    poly(ctx, [(-1.83, 0, GOAL_Z)] + crease[1:] + [(1.83, 0, GOAL_Z)])
    ctx.close_path()
    ctx.set_source_rgb(*CREASE)
    ctx.fill_preserve()
    ctx.set_source_rgb(*GOAL_RED)
    ctx.set_line_width(3)
    ctx.stroke()
    poly(ctx, ((-30, 0, GOAL_Z), (30, 0, GOAL_Z)))      # the goal line
    ctx.set_line_width(4)
    ctx.stroke()
    for side in (-1, 1):                                # the hash marks of the circles, off to the sides
        poly(ctx, ((side * 5.0, 0, GOAL_Z - 6), (side * 4.3, 0, GOAL_Z - 6)))
        ctx.stroke()
    return surface


def dasher(ctx, t):
    """The LED dasher panel on the right: black, scrolling amber; the live text sits in it."""
    x0, y0 = project(1.6, 0.98, BOARDS_Z)
    x1, y1 = project(8.0, 0.24, BOARDS_Z)
    ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
    ctx.set_source_rgb(0.03, 0.02, 0.04)
    ctx.fill()
    if t >= WORDMARK:
        cell = 5
        ctx.save()
        ctx.rectangle(x0, y0, x1 - x0, y1 - y0)
        ctx.clip()
        pixel_text(ctx, 'VIZELVISION 19   ' * 3, x0 + 20 - (t - WORDMARK) * 80, y0 + (y1 - y0 - 7 * cell) / 2, cell,
                   PINK)
        ctx.restore()


def scoreboard(ctx, t):
    """Hung over the glass: the clock at 0:04 and running, EMPTY NET flashing; GOAL after."""
    x0, y0 = project(-1.3, 4.6, BOARDS_Z + 2)
    x1, y1 = project(1.3, 3.5, BOARDS_Z + 2)
    rounded_rect(ctx, x0, y0, x1 - x0, y1 - y0, 6)
    ctx.set_source_rgb(0.04, 0.04, 0.05)
    ctx.fill()
    seconds = max(0, math.ceil(4.0 - t * 4.0 / GOAL - 1e-6)) if t < GOAL else 0
    h = (y1 - y0) * 0.42
    arena.seven_segment(ctx, '0:%02d' % seconds, x0 + 12, y0 + 8, h, (1.0, 0.12, 0.1))
    cell = max(2, int((y1 - y0) * 0.06))
    if t < GOAL:
        if int(t * 3) % 2 == 0:
            pixel_text(ctx, 'EMPTY NET', (x0 + x1) / 2, y1 - 8 * cell, cell, AMBER, align='center')
    else:
        pixel_text(ctx, 'GOAL!', (x0 + x1) / 2, y1 - 8 * cell, cell,
                   YELLOW if int((t - GOAL) * 6) % 2 == 0 else (1.0, 0.3, 0.1), align='center')


def goal_light(ctx, t):
    """The red light over the glass behind the net, spinning from the goal."""
    x, y = project(0, GLASS_TOP + 0.15, BOARDS_Z)
    r = 0.16 * scale(BOARDS_Z)
    on = t >= GOAL
    ctx.rectangle(x - r * 0.8, y, r * 1.6, r * 0.5)
    ctx.set_source_rgb(0.15, 0.15, 0.18)
    ctx.fill()
    ctx.arc(x, y, r, math.pi, TAU)
    ctx.set_source_rgb(*(GOAL_RED if on else (0.35, 0.05, 0.06)))
    ctx.fill()
    if not on:
        return
    spin = (t - GOAL) * 7
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    halo = cairo.RadialGradient(x, y, 0, x, y, r * 6)
    halo.add_color_stop_rgba(0, 1, 0.15, 0.1, 0.55 + 0.25 * math.cos(spin * 2))
    halo.add_color_stop_rgba(1, 1, 0.15, 0.1, 0)
    ctx.set_source(halo)
    ctx.arc(x, y, r * 6, 0, TAU)
    ctx.fill()
    for side in (0, math.pi):                           # its beam, sweeping round
        a = spin + side
        reach = 500 * abs(math.cos(a))
        dx = reach * math.copysign(1, math.cos(a))
        beam = cairo.LinearGradient(x, y, x + dx, y)
        beam.add_color_stop_rgba(0, 1, 0.2, 0.1, 0.45)
        beam.add_color_stop_rgba(1, 1, 0.2, 0.1, 0)
        ctx.move_to(x, y - r * 0.3)
        ctx.line_to(x + dx, y - 40)
        ctx.line_to(x + dx, y + 40)
        ctx.close_path()
        ctx.set_source(beam)
        ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the net

def ring(t, at):
    """A pipe's ring after the puck hits it: 0..1, fading."""
    if t < at:
        return 0.0
    return math.exp(-(t - at) * 9)


def bulge(t):
    """How far the back of the net bellies out (m) when the puck hits it."""
    if t < GOAL:
        return 0.0
    u = t - GOAL
    return 0.25 * math.exp(-u * 5) * math.cos(u * 18) + 0.06 * math.exp(-u * 1.5)


def net(ctx, t):
    """The mesh (the back, the sides and the top, bellying out at the goal), then the pipes,
    each shaking as it rings."""
    back = GOAL_Z + NET_DEPTH + bulge(t)
    ctx.set_line_width(1.6)
    ctx.set_source_rgba(0.35, 0.4, 0.5, 0.75)
    for k in range(13):                                 # the back: verticals and horizontals
        x = -POST_X + 2 * POST_X * k / 12
        poly(ctx, ((x * 0.95, BAR_Y * 0.85, back - 0.5), (x, 0, back)))
    for k in range(8):
        y = BAR_Y * 0.85 * k / 7
        poly(ctx, ((-POST_X, y, back - 0.5 * y / (BAR_Y * 0.85)), (POST_X, y, back - 0.5 * y / (BAR_Y * 0.85))))
    for side in (-1, 1):                                # the sides
        for k in range(7):
            u = k / 6
            poly(ctx, ((side * POST_X, BAR_Y * (1 - u), GOAL_Z), (side * POST_X, BAR_Y * 0.85 * (1 - u), back - 0.5 * (1 - u))))
    for k in range(13):                                 # the top
        x = -POST_X + 2 * POST_X * k / 12
        poly(ctx, ((x, BAR_Y, GOAL_Z), (x * 0.95, BAR_Y * 0.85, back - 0.5)))
    ctx.stroke()
    poly(ctx, ((-POST_X, 0, GOAL_Z), (-POST_X * 0.9, 0, back), (POST_X * 0.9, 0, back), (POST_X, 0, GOAL_Z)))
    ctx.set_source_rgb(0.95, 0.95, 0.97)
    ctx.set_line_width(4)
    ctx.stroke()
    shake = [ring(t, at) for at in PIPES]
    wob = lambda k: 0.02 * shake[k] * math.sin((t - PIPES[k]) * 90)     # noqa: E731
    left = ((-POST_X + wob(0), 0, GOAL_Z), (-POST_X + wob(0), BAR_Y, GOAL_Z))
    right = ((POST_X + wob(2), 0, GOAL_Z), (POST_X + wob(2), BAR_Y, GOAL_Z))
    bar = ((-POST_X, BAR_Y + wob(1) + wob(3), GOAL_Z), (POST_X, BAR_Y + wob(1) + wob(3), GOAL_Z))
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    poly(ctx, (left[0], left[1], bar[1], right[1], right[0]))
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(13)
    ctx.stroke()
    poly(ctx, (left[0], left[1], bar[1], right[1], right[0]))
    ctx.set_source_rgb(*GOAL_RED)
    ctx.set_line_width(8)
    ctx.stroke()
    for k, (point, at) in enumerate(zip(HITS, PIPES)):  # the clang: a glint where it rang
        q = span(t, at, at + 0.35)
        if 0 < q < 1:
            x, y = project(*point)
            glint(ctx, x, y, 26 * math.sin(math.pi * q), q * 3, 1)


# ---------------------------------------------------------------- the puck

HITS = ((-POST_X + 0.03, 0.45, GOAL_Z), (-0.25, BAR_Y - 0.03, GOAL_Z), (POST_X - 0.03, 0.75, GOAL_Z),
        (0.15, BAR_Y - 0.03, GOAL_Z + 0.05))
APEX = (0.35, 2.1, GOAL_Z - 0.5)                       # off the right post, up and over


def blade_x(t):
    """The blade's (and the puck's) x offset from the skates while stickhandling (m)."""
    if t < TAPS[0] - 0.25:
        return 0.55
    for k, at in enumerate(TAPS):
        if t < at:
            prev = 0.55 if k % 2 == 0 else 0.15
            nxt = 0.15 if k % 2 == 0 else 0.55
            return prev + (nxt - prev) * ease_in_out(span(t, at - 0.25, at))
    return 0.15 + 0.4 * ease_in_out(span(t, TAPS[-1], WINDUP[0]))


def puck_at(t):
    """The puck (x, y, z) in the world, or None before the shot (on the blade)."""
    if t < SHOT:
        return PLAYER[0] + blade_x(min(t, WINDUP[0])) + 0.12, 0.0, PLAYER[1] + 0.35
    start = (PLAYER[0] + 0.67, 0.02, PLAYER[1] + 0.35)
    legs = ((SHOT, start), (PIPES[0], HITS[0]), (PIPES[1], HITS[1]), (PIPES[2], HITS[2]),
            ((PIPES[2] + PIPES[3]) / 2, APEX), (PIPES[3], HITS[3]), (GOAL, (0.05, 0.25, GOAL_Z + NET_DEPTH)))
    for (t0, a), (t1, b) in zip(legs, legs[1:]):
        if t < t1:
            u = span(t, t0, t1)
            if t0 == PIPES[2]:                              # up off the post, decelerating
                u = ease_out(u, 2)
            elif t0 == (PIPES[2] + PIPES[3]) / 2:           # and falling
                u = u * u
            return tuple(a[i] + (b[i] - a[i]) * u for i in range(3))
    settle = span(t, GOAL, GOAL + 0.3)
    return 0.05, 0.25 * (1 - settle) + PUCK_R, GOAL_Z + NET_DEPTH - 0.05


def puck(ctx, t):
    x, y, z = puck_at(t)
    k = scale(z)
    sx, sy = project(x, y, z)
    if SHOT <= t < GOAL:                                 # a streak behind it
        px, py = project(*puck_at(max(SHOT, t - 1 / 20)))
        ctx.move_to(px, py)
        ctx.line_to(sx, sy)
        ctx.set_source_rgba(0.1, 0.1, 0.12, 0.45)
        ctx.set_line_width(max(6.0, PUCK_R * k * 2))
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.stroke()
    if y < 0.3:                                          # its shadow
        gx, gy = project(x, 0, z)
        ctx.save()
        ctx.translate(gx, gy)
        ctx.scale(1, 0.3)
        ctx.arc(0, 0, PUCK_R * k * 1.4, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(0, 0, 0, 0.25)
        ctx.fill()
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(1, 0.45 if y < 0.05 else 0.8)
    ctx.arc(0, 0, max(5.0, PUCK_R * k * 1.3), 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.05, 0.05, 0.06)
    ctx.fill()


# ---------------------------------------------------------------- No. 19

POSES = {
    # metres: x right, y up, from the ice between the skates (seen from behind). top/bot:
    # the hands on the stick; blade: where its blade is.
    'ready': {'pelvis': (0, 0.85), 'neck': (0, 1.38), 'head': (0.02, 1.55), 'ls': (-0.26, 1.34), 'rs': (0.26, 1.34),
              'le': (-0.3, 1.05), 'top': (-0.05, 0.92), 're': (0.36, 1.0), 'bot': (0.3, 0.68),
              'blade': (0.55, 0.0), 'lk': (-0.25, 0.45), 'rk': (0.25, 0.45), 'lf': (-0.3, 0.03), 'rf': (0.3, 0.03)},
    'windup': {'pelvis': (0, 0.88), 'neck': (0.05, 1.4), 'head': (0.08, 1.57), 'ls': (-0.22, 1.37), 'rs': (0.3, 1.36),
               'le': (0.0, 1.45), 'top': (0.25, 1.5), 're': (0.45, 1.5), 'bot': (0.55, 1.65),
               'blade': (1.2, 2.3), 'lk': (-0.25, 0.47), 'rk': (0.25, 0.47), 'lf': (-0.32, 0.03), 'rf': (0.32, 0.03)},
    'shot': {'pelvis': (0, 0.82), 'neck': (-0.04, 1.34), 'head': (-0.05, 1.51), 'ls': (-0.3, 1.3), 'rs': (0.22, 1.3),
             'le': (-0.32, 1.02), 'top': (-0.12, 0.95), 're': (0.25, 0.95), 'bot': (0.32, 0.62),
             'blade': (0.67, 0.0), 'lk': (-0.25, 0.43), 'rk': (0.25, 0.43), 'lf': (-0.32, 0.03), 'rf': (0.32, 0.03)},
    'follow': {'pelvis': (0, 0.86), 'neck': (-0.06, 1.38), 'head': (-0.08, 1.55), 'ls': (-0.3, 1.34), 'rs': (0.2, 1.35),
               'le': (-0.42, 1.2), 'top': (-0.35, 1.1), 're': (-0.05, 1.12), 'bot': (-0.3, 1.25),
               'blade': (-1.1, 1.6), 'lk': (-0.25, 0.46), 'rk': (0.25, 0.46), 'lf': (-0.32, 0.03), 'rf': (0.32, 0.03)},
    'celebrate': {'pelvis': (0, 0.95), 'neck': (0, 1.48), 'head': (0.0, 1.65), 'ls': (-0.26, 1.45), 'rs': (0.26, 1.45),
                  'le': (-0.45, 1.75), 'top': (-0.5, 2.1), 're': (0.45, 1.75), 'bot': (0.5, 2.1),
                  'blade': (1.2, 2.25), 'lk': (-0.2, 0.5), 'rk': (0.2, 0.5), 'lf': (-0.25, 0.03), 'rf': (0.25, 0.03)},
}
KEYS = ((0.0, 'ready'), (WINDUP[0], 'ready'), (WINDUP[1], 'windup'), (SHOT, 'shot'), (SHOT + 0.18, 'follow'),
        (CELEBRATE[0], 'follow'), (CELEBRATE[1], 'celebrate'))


def pose(t):
    for (t0, a), (t1, b) in zip(KEYS, KEYS[1:]):
        if t < t1:
            k = ease_in_out(span(t, t0, t1))
            return {j: (POSES[a][j][0] + (POSES[b][j][0] - POSES[a][j][0]) * k,
                        POSES[a][j][1] + (POSES[b][j][1] - POSES[a][j][1]) * k) for j in POSES[a]}
    return dict(POSES[KEYS[-1][1]])


def glide(t):
    """How far No. 19 has glided toward the net celebrating (m)."""
    return 1.6 * ease_out(span(t, CELEBRATE[0], CELEBRATE[0] + 3.0), 2)


def player(ctx, t):
    p = pose(t)
    if t < WINDUP[0]:                                    # the blade handling the puck
        dx = blade_x(t) - 0.55
        p['blade'] = (p['blade'][0] + dx, 0.0)
        p['bot'] = (p['bot'][0] + dx * 0.5, p['bot'][1])
        p['top'] = (p['top'][0] + dx * 0.25, p['top'][1])
    z = PLAYER[1] + glide(t)
    s = scale(z)

    def at(px, py):
        return project(PLAYER[0] + px, py, z)

    j = {k: at(*v) for k, v in p.items()}
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)

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

    fx, fy = at(0, 0)                                    # the shadow on the ice
    ctx.save()
    ctx.translate(fx, fy)
    ctx.scale(1, 0.16)
    ctx.arc(0, 0, 0.6 * s, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(0.2, 0.3, 0.45, 0.3)
    ctx.fill()
    # The stick: from the top hand through the bottom hand to the blade.
    tx, ty = j['top']
    bx, by = j['blade']
    limb(((tx, ty), (bx, by)), (0.15, 0.15, 0.17), 0.035 * s)
    angle = math.copysign(1, bx - tx) if abs(bx - tx) > 1 else 1
    limb(((bx, by), (bx + angle * 0.2 * s, by + 0.01 * s)), (0.15, 0.15, 0.17), 0.05 * s)
    ctx.move_to(bx + angle * 0.04 * s, by)
    ctx.line_to(bx + angle * 0.18 * s, by)
    ctx.set_source_rgb(*WHITE)                           # the tape
    ctx.set_line_width(0.04 * s)
    ctx.stroke()
    for side in ('l', 'r'):                              # legs: socks in stripes, skates
        hip = at(-0.13 if side == 'l' else 0.13, p['pelvis'][1] - 0.05)
        limb((hip, j[side + 'k'], j[side + 'f']), JERSEY, 0.15 * s)
        kx, ky = j[side + 'k']
        ffx, ffy = j[side + 'f']
        for u in (0.35, 0.55):
            ctx.move_to(kx + (ffx - kx) * u - 0.075 * s, ky + (ffy - ky) * u)
            ctx.line_to(kx + (ffx - kx) * u + 0.075 * s, ky + (ffy - ky) * u)
        ctx.set_source_rgb(*WHITE)
        ctx.set_line_width(0.04 * s)
        ctx.stroke()
        rounded_rect(ctx, ffx - 0.08 * s, ffy - 0.14 * s, 0.16 * s, 0.12 * s, 0.03 * s)
        inked(ctx, (0.1, 0.1, 0.12), 3, (0, 0))
        ctx.rectangle(ffx - 0.09 * s, ffy - 0.02 * s, 0.18 * s, 0.025 * s)
        ctx.set_source_rgb(0.8, 0.85, 0.9)
        ctx.fill()
    pl, pr = at(-0.24, p['pelvis'][1] + 0.08), at(0.24, p['pelvis'][1] + 0.08)   # the pants
    lk, rk = j['lk'], j['rk']
    ctx.move_to(*pl)
    ctx.line_to(*pr)
    ctx.line_to(pr[0] + (rk[0] - pr[0]) * 0.55 + 0.08 * s, pr[1] + (rk[1] - pr[1]) * 0.55)
    ctx.line_to(pr[0] + (rk[0] - pr[0]) * 0.55 - 0.14 * s, pr[1] + (rk[1] - pr[1]) * 0.55)
    ctx.line_to((pl[0] + pr[0]) / 2, (pl[1] + pr[1]) / 2 + 0.16 * s)
    ctx.line_to(pl[0] + (lk[0] - pl[0]) * 0.55 + 0.14 * s, pl[1] + (lk[1] - pl[1]) * 0.55)
    ctx.line_to(pl[0] + (lk[0] - pl[0]) * 0.55 - 0.08 * s, pl[1] + (lk[1] - pl[1]) * 0.55)
    ctx.close_path()
    inked(ctx, PANTS, 3, (0, 0))
    for side, hand in (('l', 'top'), ('r', 'bot')):     # arms in sleeves, gloves
        limb((j[side + 's'], j[side + 'e'], j[hand]), JERSEY, 0.15 * s)
        hx, hy = j[side + 'e']
        gx, gy = j[hand]
        ctx.move_to(hx + (gx - hx) * 0.55, hy + (gy - hy) * 0.55)
        ctx.line_to(hx + (gx - hx) * 0.7, hy + (gy - hy) * 0.7)
        ctx.set_source_rgb(*WHITE)
        ctx.set_line_width(0.15 * s)
        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.stroke()
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ls, rs = j['ls'], j['rs']                            # the sweater, from behind
    ctx.move_to(ls[0] - 0.02 * s, ls[1] - 0.04 * s)
    ctx.curve_to(j['neck'][0] - 0.1 * s, j['neck'][1] - 0.02 * s, j['neck'][0] + 0.1 * s, j['neck'][1] - 0.02 * s,
                 rs[0] + 0.02 * s, rs[1] - 0.04 * s)
    ctx.curve_to(rs[0] + 0.08 * s, rs[1] + 0.2 * s, pr[0] + 0.06 * s, pr[1] - 0.25 * s, pr[0] + 0.04 * s, pr[1] + 0.02 * s)
    ctx.line_to(pl[0] - 0.04 * s, pl[1] + 0.02 * s)
    ctx.curve_to(pl[0] - 0.06 * s, pl[1] - 0.25 * s, ls[0] - 0.08 * s, ls[1] + 0.2 * s, ls[0] - 0.02 * s, ls[1] - 0.04 * s)
    ctx.close_path()
    inked(ctx, JERSEY, 3, (0, 0))
    hem = (pl[1] + pr[1]) / 2 - 0.1 * s                  # the hem's stripes
    ctx.save()
    ctx.move_to(ls[0] - 0.02 * s, ls[1] - 0.04 * s)
    ctx.line_to(rs[0] + 0.02 * s, rs[1] - 0.04 * s)
    ctx.line_to(pr[0] + 0.1 * s, pr[1] + 0.02 * s)
    ctx.line_to(pl[0] - 0.1 * s, pl[1] + 0.02 * s)
    ctx.close_path()
    ctx.clip()
    for dy, colour in ((0, WHITE), (0.035, TEAL), (0.07, WHITE)):
        ctx.rectangle(0, hem + dy * s, W, 0.025 * s)
        ctx.set_source_rgb(*colour)
        ctx.fill()
    ctx.restore()
    cx = (ls[0] + rs[0]) / 2                             # VIZELVISION and 19
    ctx.save()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(0.065 * s)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', cx, ls[1] + 0.11 * s, tracking=0.004 * s, align='center')
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.set_font_size(0.24 * s)
    ctx.new_path()
    text_path(ctx, '19', cx, ls[1] + 0.36 * s, tracking=0.01 * s, align='center')
    path = ctx.copy_path()
    ctx.set_source_rgb(*TEAL)
    ctx.set_line_width(0.025 * s)
    ctx.stroke()
    ctx.append_path(path)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.restore()
    for hand in ('top', 'bot'):                          # gloves over the stick
        gx, gy = j[hand]
        rounded_rect(ctx, gx - 0.07 * s, gy - 0.07 * s, 0.14 * s, 0.14 * s, 0.04 * s)
        inked(ctx, (0.12, 0.12, 0.14), 3, (0, 0))
    hx, hy = j['head']                                   # the helmet, from behind
    ctx.arc(hx, hy, 0.13 * s, math.pi * 0.95, math.pi * 2.05)
    ctx.curve_to(hx + 0.13 * s, hy + 0.1 * s, hx - 0.13 * s, hy + 0.1 * s, hx - 0.13 * s, hy + 0.02 * s)
    ctx.close_path()
    inked(ctx, PINK, 3, (0, 0))
    ctx.move_to(hx - 0.12 * s, hy + 0.0 * s)
    ctx.line_to(hx + 0.12 * s, hy + 0.0 * s)
    ctx.set_source_rgb(*WHITE)
    ctx.set_line_width(0.02 * s)
    ctx.stroke()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(0.07 * s)
    ctx.new_path()
    text_path(ctx, '19', hx, hy + 0.075 * s, align='center')
    ctx.fill()
    ctx.restore()


def spray(ctx, t, frame):
    """Ice spraying off the skates as No. 19 stops to celebrate."""
    p = span(t, CELEBRATE[0] + 0.8, CELEBRATE[0] + 1.6)
    if not 0 < p < 1:
        return
    rand = random.Random(frame // 2)
    z = PLAYER[1] + glide(t)
    for _ in range(40):
        u = rand.random()
        x, y = project(PLAYER[0] + 0.3 + u * 0.8, 0.05 + 0.5 * u * math.sin(math.pi * p), z)
        ctx.arc(x + rand.uniform(-6, 6), y + rand.uniform(-6, 6), rand.uniform(1, 3), 0, TAU)
        ctx.set_source_rgba(1, 1, 1, 0.8 * (1 - p))
        ctx.fill()


# ---------------------------------------------------------------- the closer

def ice_show(ctx, t):
    """The house lights down, and pink and teal light sweeping across the ice, the way the
    rinks project onto it before a game."""
    p = span(t, *DIM)
    if p <= 0:
        return
    ctx.set_source_rgba(0.02, 0.0, 0.06, 0.74 * ease_in_out(p))
    ctx.paint()
    top = project(0, 0, BOARDS_Z)[1]
    ctx.save()
    ctx.rectangle(0, top, W, H - top)
    ctx.clip()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for k, colour in enumerate((PINK, TEAL, PINK, TEAL)):
        x = -8 + 16 * ((t - DIM[0]) * 0.35 + k * 0.25) % 16
        a, b = project(x - 0.8, 0, BOARDS_Z), project(x + 0.8, 0, BOARDS_Z)
        c, d = project(x + 1.6, 0, 6), project(x - 1.6, 0, 6)
        ctx.move_to(*a)
        ctx.line_to(*b)
        ctx.line_to(*c)
        ctx.line_to(*d)
        ctx.close_path()
        ctx.set_source_rgba(*colour, 0.28 * p)
        ctx.fill()
    ctx.restore()


def finale(ctx, t):
    if t < WORDMARK - 0.05:
        return
    neighborhood.lockup(ctx, t, WORDMARK, 300, scale=0.66)
    p = span(t, *HOCKEY)
    if p > 0:
        ctx.save()
        ctx.rectangle(0, 0, W / 2 - 240 + 480 * ease_in_out(p), H)
        ctx.clip()
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(46)
        ctx.new_path()
        text_path(ctx, 'HOCKEY', W / 2, 375, tracking=22, align='center')
        inked(ctx, (0.75, 0.88, 1.0), 5, (6, 6))
        ctx.restore()
    for i, at in enumerate((WORDMARK + 0.25, WORDMARK + 1.0, WORDMARK + 2.0)):
        q = span(t, at, at + 0.5)
        if 0 < q < 1:
            glint(ctx, (370, 910, 640)[i], (220, 232, 192)[i], 22 * math.sin(math.pi * q), q * 3, 1)


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.set_source_surface(rink_surface(), 0, 0)
    ctx.paint()
    scoreboard(ctx, t)
    dasher(ctx, t)
    goal_light(ctx, t)
    net(ctx, t)
    if t < SHOT or t >= PIPES[3]:                        # on the blade, or in the net
        puck(ctx, t)
    player(ctx, t)
    spray(ctx, t, frame)
    if SHOT <= t < PIPES[3]:                             # in flight, in front of everything
        puck(ctx, t)
    ice_show(ctx, t)
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
