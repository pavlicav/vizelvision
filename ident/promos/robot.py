"""The Football Robot: the big pre-game robot intro, VizelVision's own. A night stadium from
the near sideline at the 50, the station's TV painted at midfield. A streak of fire in the sky:
Unit 19 (chrome and gunmetal plates, the station's pink and teal, a helmet with a glowing visor
behind its face mask, shoulder pads built in, pistons at every joint, VIZELVISION 19 on its
chest) drops onto the 50 on its boot thrusters, a hero landing in sparks and turf with the
sideline flame cannons going off. It rises, and the open logo is four moves, a cannon a move:
the punch, the double-biceps flex, the robot, and a point at you. Its chest opens and hands it
a football; it drops it and punts it straight out of the stadium, the camera tilting up after
it into the night and out into orbit (PUNT: 254 MI, HANG TIME: STILL GOING). The ball comes
home as a meteor; back in the stadium the house lights go down, the spots find the robot with
its hand up, the wordmark drops in on the closed logo under FOOTBALL ON, and on the last note
the meteor lands in its palm.

Live text: the programme on air, on the ribbon board along the stands. Aired only during an
NFL game (LEAGUES). The sound is its own pre-game theme (robot_music.py: an original brass,
timpani and marching-snare theme on the logo notes), the moves landing on its stabs. The robot
speaks in Pluto's voice through its own circuits (the cue ring-modulates and crushes it):
"Incoming." / "Vizzle Vision... football..." / "...activated."
"""
import math
import random
from functools import lru_cache

import cairo

import arena
import neighborhood
from common import (INK, PINK, TAU, TEAL, W, H, WHITE, YELLOW, back_out, ease_in, ease_in_out, ease_out,  # noqa: F401
                    glint, grain, inked, inked_stroke, mix, pixel_text, rounded_rect, span, text_path, vignette)

ID = 'robot'
NAME = 'The Football Robot'
KIND = 'ident'
ORDER = 40
DESCRIPTION = ('Only during the NFL: the pre-game robot, with its own big brass theme. Unit 19 drops onto the 50 in '
               'sparks and flame, hits the open logo with four moves on the brass stabs (punch, flex, the robot, a '
               'point at you), punts a football into orbit and catches it as a meteor on the closed logo. The ribbon '
               'board carries the game on air. Pluto, robotized.')
DURATION = 10.0
STILL_AT = 2.55
LEAGUES = ('nfl',)

# Hit points (the music's too: robot_music.py).
STREAK = (0.0, 0.3)            # a streak of fire high in the sky
DROP = (0.25, 1.0)             # the fall, boot thrusters firing
LAND = 1.0                     # the hero landing on the 50: shockwave, sparks, every cannon
RISE = (1.08, 1.42)            # up from the crouch
MOVES = (1.5, 1.75, 2.0, 2.5)  # the open logo: punch, flex, the robot, the point
HATCH = (2.8, 3.05)            # the chest opens; a football rides out into its hand
TOSS = 3.3                     # the ball dropped for the punt
PUNT = 3.5                     # boot meets ball
TILT = (3.5, 4.6)              # the camera follows it up and out
SPACE = (4.6, 6.15)            # in orbit
RETURN = (6.15, 6.45)          # it comes home as a meteor
DIM = (6.45, 6.95)             # the house lights down, the spots on the robot
WORDMARK = 7.0                 # the closed logo
SUBTITLE = (7.0, 7.45)         # FOOTBALL ON
METEOR = (7.55, 8.0)           # the meteor's last dive
CATCH = 8.0                    # the last note: into its palm
FADE = (9.25, 9.6)
CANNONS = (1.0, 1.5, 1.75, 2.0, 2.5, 7.0, 7.25, 7.5, 8.0)   # the sideline flame cannons

# The camera: a pinhole on the near sideline at the 50, CAM_H metres up, FOCAL px; world x metres
# along the field, y up, z away across it. HOR0 is the horizon with the camera level.
FOCAL, CAM_H, HOR0 = 1000, 4.8, 250
ROBOT_Z = 13.0                 # where it lands: the 50, between the near sideline and the middle
PULL = 0.24                    # how far the camera zooms out for the finale
FAR_SIDELINE, MID_Z = 52.3, 27.9
CANNON_X = (-24.0, -12.0, 12.0, 24.0)
CANNON_Z = 55.5
TALL = 1400                    # the stadium layer's headroom above the screen, for the tilts
MX, MB = 260, 320              # and its margins at the sides and below, for the finale's pull back
FASCIA = (176, 208)            # the ribbon board's top and bottom (screen y, camera level)

CHROME = (0.86, 0.88, 0.93)
GUNMETAL = (0.25, 0.27, 0.33)
GUN_DARK = (0.14, 0.15, 0.2)
TURF = ((0.15, 0.43, 0.18), (0.12, 0.37, 0.15))
FLAME = (1.0, 0.62, 0.16)
AMBER = (1.0, 0.68, 0.18)

OVERLAYS = [
    {'field': 'programme', 'box': [36, 179, 470, 27], 'from': 1.15, 'to': 3.5,
     'style': {'font': 'Nimbus Sans Narrow', 'bold': True, 'size': 25, 'min_size': 13, 'color': [1.0, 0.68, 0.18],
               'upper': True, 'tracking': 0.1},
     'enter': {'kind': 'fade', 'seconds': 0.25}, 'exit': {'kind': 'fade', 'seconds': 0.15}},
]


def project(x, y, z, hor=HOR0, zoom=1.0):
    return W / 2 + zoom * FOCAL * x / z, hor - zoom * FOCAL * (y - CAM_H) / z


def zoom(t):
    """The finale's pull back (the lens zooms out about the horizon)."""
    return 1 - PULL * ease_in_out(span(t, DIM[0], WORDMARK + 0.3))


def scale(z):
    return FOCAL / z


# ---------------------------------------------------------------- where things are

def robot_height(t):
    """The robot's boots above the turf."""
    if t >= LAND:
        return 0.0
    return 40.0 * (1 - ease_in(span(t, DROP[0], LAND), 1.6))


def ball_height(t):
    return 2.6 + 270.0 * ease_in(span(t, PUNT, TILT[1]), 2.2)


def horizon(t):
    """The camera's tilt, as where the horizon sits: it rides the robot down, shakes on the
    landing, follows the ball up, and comes back for the finale."""
    if t < LAND:
        return HOR0 + 0.82 * FOCAL * robot_height(t) / ROBOT_Z
    shake = 0.0
    for at, size in ((LAND, 16.0), (PUNT, 5.0), (CATCH, 9.0)):
        if at <= t < at + 0.6:
            shake += size * math.sin((t - at) * 58) * math.exp(-(t - at) * 7)
    if PUNT <= t < SPACE[0]:
        return max(HOR0, 335 + FOCAL * (ball_height(t) - CAM_H) / ROBOT_Z) + shake
    return HOR0 + shake


# ---------------------------------------------------------------- the stadium (drawn once)

def _fp(x, y, z):
    """Into the stadium layer: camera level, TALL px of headroom above the screen, MX at the sides."""
    sx, sy = project(x, y, z)
    return sx + MX, sy + TALL


def _quad(ctx, pts):
    ctx.move_to(*_fp(*pts[0]))
    for p in pts[1:]:
        ctx.line_to(*_fp(*p))
    ctx.close_path()


def _ground_text(ctx, text, x, z, size, flip=True, colour=(1, 1, 1), alpha=0.92):
    """Text painted flat on the turf at (x, z), foreshortened; flip for the far side's numbers."""
    sx, sy = _fp(x, 0, z)
    k = scale(z)
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(k, k * CAM_H / z)
    if flip:
        ctx.rotate(math.pi)
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(size)
    ext = ctx.text_extents(text)
    ctx.move_to(-ext.width / 2 - ext.x_bearing, ext.height / 2)
    ctx.text_path(text)
    ctx.set_source_rgba(*colour, alpha)
    ctx.fill()
    ctx.restore()


def _midfield(ctx):
    """The station's TV painted at midfield: teal set, its V, a pink ring, flat on the grass."""
    sx, sy = _fp(0, 0, MID_Z)
    k = scale(MID_Z)
    ctx.save()
    ctx.translate(sx, sy)
    ctx.scale(k, k * CAM_H / MID_Z)
    ctx.set_line_width(0.35)
    ctx.arc(0, 0, 6.2, 0, TAU)
    ctx.set_source_rgba(*PINK, 0.85)
    ctx.stroke()
    rounded_rect(ctx, -4.0, -2.9, 8.0, 5.8, 1.1)
    ctx.set_source_rgba(*TEAL, 0.92)
    ctx.fill_preserve()
    ctx.set_source_rgba(*INK, 0.9)
    ctx.set_line_width(0.3)
    ctx.stroke()
    rounded_rect(ctx, -3.3, -2.3, 5.0, 4.6, 0.8)
    ctx.set_source_rgba(0.17, 0.35, 0.86, 0.95)
    ctx.fill()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(4.6)
    ctx.save()
    ctx.translate(-0.8, 0)
    ctx.rotate(math.pi)            # it reads right way up from the far side, like the numbers
    ext = ctx.text_extents('V')
    ctx.move_to(-ext.width / 2 - ext.x_bearing, ext.height / 2)
    ctx.text_path('V')
    ctx.set_source_rgba(1, 1, 1, 0.95)
    ctx.fill()
    ctx.restore()
    for dy, col in ((-1.0, YELLOW), (0.4, PINK)):
        ctx.arc(2.8, dy, 0.42, 0, TAU)
        ctx.set_source_rgba(*col, 0.95)
        ctx.fill()
    ctx.restore()


@lru_cache(maxsize=None)
def stadium():
    """Everything that does not move, the camera level: the field, the far sideline, the stands,
    the ribbon board's housing, the roof rim and the light towers high above."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W + 2 * MX, H + TALL + MB)
    ctx = cairo.Context(surface)
    rand = random.Random(19)
    # the stands, rising away beyond the far sideline (rows skipped for the ribbon board); the
    # helper fills one screen's width, so it is laid three times, side by side
    def proj(x, y, z):
        sx, sy = project(x, y, z)
        return sx, sy + TALL
    for shift in (-1, 0, 1):
        ctx.save()
        ctx.translate(MX + shift * W, 0)
        arena.stands(ctx, proj, scale, 60.0, 1.2, rows=46, skip=(16, 17, 18, 19, 20), seed=19 + shift)
        ctx.restore()
    # the upper rim and the light towers
    for side in (-1, 1):
        for k in range(2):
            x, z = side * (34 + 16 * k), 96.0 + 6 * k
            bx, by = _fp(x, 20.0, z)
            tx, ty = _fp(x, 58.0 + 6 * k, z)
            ctx.move_to(bx - 7, by)
            ctx.line_to(tx - 3, ty + 40)
            ctx.line_to(tx + 3, ty + 40)
            ctx.line_to(bx + 7, by)
            ctx.close_path()
            ctx.set_source_rgb(0.1, 0.09, 0.14)
            ctx.fill()
            rounded_rect(ctx, tx - 62, ty - 8, 124, 52, 6)
            ctx.set_source_rgb(0.12, 0.11, 0.16)
            ctx.fill()
            for r in range(3):
                for c in range(7):
                    ctx.arc(tx - 50 + c * 16.6, ty + 5 + r * 15, 5.2, 0, TAU)
                    ctx.set_source_rgb(1.0, 0.98, 0.9)
                    ctx.fill()
    rimy = _fp(0, 21.5, 100)[1]
    ctx.rectangle(0, rimy - 14, W + 2 * MX, 16)
    ctx.set_source_rgb(0.08, 0.07, 0.11)
    ctx.fill()
    # the sideline wall, the bench area, and the far sideline
    _quad(ctx, [(-90, 0, 52.3), (90, 0, 52.3), (90, 0, 60.0), (-90, 0, 60.0)])
    ctx.set_source_rgb(0.1, 0.27, 0.13)
    ctx.fill()
    wall_top, wall_bottom = _fp(0, 1.3, 59.0)[1], _fp(0, 0, 59.0)[1]
    ctx.rectangle(0, wall_top, W + 2 * MX, wall_bottom - wall_top)
    ctx.set_source_rgb(*mix(PINK, INK, 0.25))
    ctx.fill()
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size((wall_bottom - wall_top) * 0.8)
    x = -40.0
    while x < W + 2 * MX:
        ctx.move_to(x, wall_bottom - (wall_bottom - wall_top) * 0.18)
        ctx.text_path('VIZELVISION 19  ·  ')
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill()
        x += ctx.text_extents('VIZELVISION 19  ·  ').x_advance
    for k in range(14):                                  # people on the far sideline
        px = -30 + k * 4.6 + rand.uniform(-1, 1)
        sx, sy = _fp(px, 0, 55.0)
        s = scale(55.0)
        ctx.arc(sx, sy - 1.55 * s, 0.13 * s, 0, TAU)
        ctx.set_source_rgb(0.08, 0.06, 0.1)
        ctx.fill()
        rounded_rect(ctx, sx - 0.25 * s, sy - 1.42 * s, 0.5 * s, 1.42 * s, 0.12 * s)
        ctx.set_source_rgb(*rand.choice(((0.85, 0.85, 0.9), (0.08, 0.06, 0.1), (0.8, 0.2, 0.45))))
        ctx.fill()
    # the field: mown stripes, five yards each, out to the far sideline
    yard = 0.9144
    for k in range(-14, 14):
        x0, x1 = k * 5 * yard, (k + 1) * 5 * yard
        _quad(ctx, [(x0, 0, 2.0), (x1, 0, 2.0), (x1, 0, FAR_SIDELINE), (x0, 0, FAR_SIDELINE)])
        ctx.set_source_rgb(*TURF[k % 2])
        ctx.fill()
    _quad(ctx, [(-90, 0, FAR_SIDELINE - 0.1), (90, 0, FAR_SIDELINE - 0.1), (90, 0, FAR_SIDELINE + 1.8),
                (-90, 0, FAR_SIDELINE + 1.8)])
    ctx.set_source_rgb(0.95, 0.95, 0.92)
    ctx.fill()
    for k in range(-14, 15):                             # the yard lines
        x = k * 5 * yard
        _quad(ctx, [(x - 0.06, 0, 2.0), (x + 0.06, 0, 2.0), (x + 0.06, 0, FAR_SIDELINE), (x - 0.06, 0, FAR_SIDELINE)])
        ctx.set_source_rgba(1, 1, 1, 0.85 if k else 0.95)
        ctx.fill()
    for z in (3.5 + 21.6, FAR_SIDELINE - 21.6):          # the hash marks
        for k in range(-70, 71):
            x = k * yard
            _quad(ctx, [(x - 0.05, 0, z - 0.3), (x + 0.05, 0, z - 0.3), (x + 0.05, 0, z + 0.3), (x - 0.05, 0, z + 0.3)])
            ctx.set_source_rgba(1, 1, 1, 0.75)
            ctx.fill()
    for k, label in ((-4, '30'), (-2, '40'), (0, '50'), (2, '40'), (4, '30')):
        _ground_text(ctx, label, k * 5 * yard, FAR_SIDELINE - 11.0, 2.0)
    _midfield(ctx)
    return surface


@lru_cache(maxsize=None)
def stars():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    rand = random.Random(1919)
    for _ in range(420):
        x, y, r = rand.uniform(0, W), rand.uniform(0, H), rand.choice((0.6, 0.8, 1.0, 1.0, 1.4, 1.9))
        ctx.arc(x, y, r, 0, TAU)
        ctx.set_source_rgba(1, 1, mix((1, 1, 1), (0.7, 0.8, 1), rand.random())[2], rand.uniform(0.4, 1.0))
        ctx.fill()
    return surface


# ---------------------------------------------------------------- sky, ribbon board, crowd, cannons

def sky(ctx, hor):
    up = span(hor, HOR0, 4200)
    g = cairo.LinearGradient(0, 0, 0, H)
    g.add_color_stop_rgb(0, *mix((0.05, 0.05, 0.16), (0.0, 0.0, 0.02), up))
    g.add_color_stop_rgb(1, *mix((0.2, 0.14, 0.32), (0.02, 0.02, 0.08), up))
    ctx.set_source(g)
    ctx.paint()
    haze_y = hor - 120                                   # the lights' glow above the stands
    if haze_y > -300:
        halo = cairo.LinearGradient(0, haze_y - 360, 0, haze_y + 60)
        halo.add_color_stop_rgba(0, 1, 0.95, 0.85, 0)
        halo.add_color_stop_rgba(1, 1, 0.95, 0.85, 0.22)
        ctx.set_source(halo)
        ctx.rectangle(0, haze_y - 360, W, 420)
        ctx.fill()
    a = span(hor, 900, 3200)
    if a > 0:
        ctx.set_source_surface(stars(), 0, 0)
        ctx.paint_with_alpha(a)


def ribbon(ctx, t, dy):
    """The ribbon board along the stands: the programme on the left (master's live text), the
    station's name scrolling on the right."""
    y0, y1 = FASCIA[0] + dy, FASCIA[1] + dy
    if y1 < 0 or y0 > H:
        return
    ctx.rectangle(-MX, y0, W + 2 * MX, y1 - y0)
    ctx.set_source_rgb(0.03, 0.02, 0.05)
    ctx.fill()
    ctx.save()
    ctx.rectangle(530, y0, W - 530 + MX, y1 - y0)
    ctx.clip()
    ctx.select_font_face('Nimbus Sans Narrow', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(24)
    words = 'VIZELVISION 19  ·  FOOTBALL  ·  UNIT 19 IS IN THE BUILDING  ·  '
    adv = ctx.text_extents(words).x_advance
    x = 530 - (t * 140) % adv
    while x < W + MX:
        ctx.move_to(x, y1 - 7)
        ctx.text_path(words)
        x += adv
    ctx.set_source_rgb(*AMBER)
    ctx.fill()
    ctx.restore()
    ctx.rectangle(518, y0 + 3, 4, y1 - y0 - 6)
    ctx.set_source_rgb(*PINK)
    ctx.fill()


def crowd_flashes(ctx, t, frame, dy, busy):
    rand = random.Random(frame // 2 * 31 + 7)
    for _ in range(int(10 + 50 * busy)):
        x, y = rand.uniform(-MX, W + MX), rand.uniform(-60, 150) + dy
        if rand.random() < 0.6:
            continue
        halo = cairo.RadialGradient(x, y, 0, x, y, 9)
        halo.add_color_stop_rgba(0, 1, 1, 1, 0.95)
        halo.add_color_stop_rgba(1, 1, 1, 1, 0)
        ctx.set_source(halo)
        ctx.arc(x, y, 9, 0, TAU)
        ctx.fill()


def cannon(ctx, t, x, at, hor, tint=FLAME, zoom_=1.0):
    """A sideline flame cannon going off at ``at``: a column of fire, then smoke."""
    p = span(t, at, at + 0.75)
    if p <= 0 or p >= 1:
        return
    sx, sy = project(x, 0, CANNON_Z, hor, zoom_)
    k = scale(CANNON_Z) * zoom_
    rounded_rect(ctx, sx - 0.7 * k, sy - 1.0 * k, 1.4 * k, 1.0 * k, 0.2 * k)
    ctx.set_source_rgb(0.12, 0.12, 0.16)
    ctx.fill()
    height = 14 * k * ease_out(span(t, at, at + 0.18)) * (1 - 0.35 * span(t, at + 0.3, at + 0.75))
    fade = 1 - span(t, at + 0.35, at + 0.75)
    rand = random.Random(int(at * 100) + int(x))
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for i in range(9):
        u = i / 8
        r = (1.4 - 0.9 * u) * k * (1 + 0.15 * math.sin(t * 40 + i * 2.1))
        cy = sy - 1.0 * k - height * u
        cx = sx + math.sin(t * 23 + i * 1.7 + rand.random()) * 0.35 * k * u
        g = cairo.RadialGradient(cx, cy, 0, cx, cy, r * 2)
        g.add_color_stop_rgba(0, 1, 0.95, 0.75, 0.9 * fade)
        g.add_color_stop_rgba(0.4, *tint, 0.7 * fade)
        g.add_color_stop_rgba(1, *tint, 0)
        ctx.set_source(g)
        ctx.arc(cx, cy, r * 2, 0, TAU)
        ctx.fill()
    ctx.restore()
    smoke = span(t, at + 0.3, at + 0.75)
    if smoke > 0:
        for i in range(4):
            cy = sy - 1.0 * k - height * (0.6 + 0.4 * smoke) - i * 1.4 * k
            ctx.arc(sx + (i - 1.5) * 0.6 * k, cy, (1.0 + smoke) * k, 0, TAU)
            ctx.set_source_rgba(0.4, 0.38, 0.45, 0.25 * (1 - smoke))
            ctx.fill()


# ---------------------------------------------------------------- Unit 19

# A pose: crouch (m the pelvis drops), tilt (rad, the torso), head (rad), arms as (shoulder from
# down, outward +; elbow, bending up +) for its right (screen left) and left; legs as (hip, knee).
NEUTRAL = dict(crouch=0.0, tilt=0.0, head=0.0, rarm=(0.22, 0.2), larm=(0.22, 0.2), rleg=(0.1, 0.0), lleg=(0.1, 0.0),
               hand=('fist', 'fist'))
POSES = {
    'fall': dict(crouch=0.0, tilt=0.0, head=-0.1, rarm=(0.9, -0.3), larm=(0.9, -0.3), rleg=(0.05, 0.25), lleg=(0.05, 0.25), hand=('open', 'open')),
    'land': dict(crouch=1.05, tilt=0.12, head=0.35, rarm=(0.25, -0.1), larm=(1.55, 0.35), rleg=(0.55, 1.15), lleg=(0.5, 1.1), hand=('fist', 'open')),
    'stand': NEUTRAL,
    'punch': dict(crouch=0.25, tilt=-0.08, head=-0.12, rarm=(1.57, 0.0), larm=(0.55, 2.3), rleg=(0.32, 0.25), lleg=(0.28, 0.2), hand=('fist', 'fist')),
    'flex': dict(crouch=0.3, tilt=0.0, head=0.0, rarm=(1.6, 1.75), larm=(1.6, 1.75), rleg=(0.34, 0.3), lleg=(0.34, 0.3), hand=('fist', 'fist')),
    'robot': dict(crouch=0.15, tilt=0.12, head=0.32, rarm=(1.57, -1.57), larm=(1.57, 1.57), rleg=(0.2, 0.0), lleg=(0.45, 0.6), hand=('flat', 'flat')),
    'point': dict(crouch=0.1, tilt=-0.06, head=-0.2, rarm=(1.15, 0.12), larm=(0.75, -1.9), rleg=(0.22, 0.05), lleg=(0.25, 0.1), hand=('point', 'fist')),
    'hold': dict(crouch=0.0, tilt=0.0, head=0.25, rarm=(0.55, 1.35), larm=(0.4, 0.9), rleg=(0.12, 0.0), lleg=(0.12, 0.0), hand=('open', 'open')),
    'drop': dict(crouch=0.1, tilt=-0.05, head=0.3, rarm=(0.9, 0.4), larm=(0.8, 0.3), rleg=(0.12, 0.0), lleg=(0.25, 0.4), hand=('open', 'open')),
    'punt': dict(crouch=-0.05, tilt=-0.22, head=-0.15, rarm=(1.45, 0.2), larm=(0.5, 0.4), rleg=(0.08, 0.05), lleg=(1.95, 0.05), hand=('flat', 'flat')),
    'look': dict(crouch=0.0, tilt=0.0, head=-0.45, rarm=(0.6, 1.2), larm=(0.3, 0.3), rleg=(0.15, 0.0), lleg=(0.2, 0.0), hand=('flat', 'fist')),
    'wait': dict(crouch=0.12, tilt=0.03, head=-0.3, rarm=(2.05, 0.35), larm=(0.4, 0.4), rleg=(0.25, 0.15), lleg=(0.25, 0.15), hand=('open', 'fist')),
    'catch': dict(crouch=0.45, tilt=0.06, head=-0.1, rarm=(1.75, 0.95), larm=(0.9, 0.6), rleg=(0.32, 0.5), lleg=(0.32, 0.45), hand=('ball', 'fist')),
    'hero': dict(crouch=0.0, tilt=0.0, head=0.0, rarm=(1.2, 1.5), larm=(0.6, -1.6), rleg=(0.22, 0.0), lleg=(0.22, 0.0), hand=('ball', 'fist')),
}
# When each pose is struck (a servo's snap into it, then a hold).
KEYS = ((0.0, 'fall'), (LAND, 'land'), (RISE[0], 'stand'), (MOVES[0], 'punch'), (MOVES[1], 'flex'),
        (MOVES[2], 'robot'), (MOVES[3], 'point'), (2.78, 'hold'), (TOSS, 'drop'), (PUNT, 'punt'), (3.85, 'look'),
        (DIM[0], 'wait'), (CATCH, 'catch'), (8.55, 'hero'))
SNAP = 0.09


def _blend(a, b, u):
    out = {}
    for key in ('crouch', 'tilt', 'head'):
        out[key] = a[key] + (b[key] - a[key]) * u
    for key in ('rarm', 'larm', 'rleg', 'lleg'):
        out[key] = tuple(p + (q - p) * u for p, q in zip(a[key], b[key]))
    out['hand'] = b['hand'] if u > 0.5 else a['hand']
    return out


def pose(t):
    k = 0
    while k + 1 < len(KEYS) and t >= KEYS[k + 1][0]:
        k += 1
    at, name = KEYS[k]
    prev = KEYS[k - 1][1] if k else name
    move = {'land': 0.06, 'stand': RISE[1] - RISE[0], 'look': 0.3, 'wait': 0.35, 'hero': 0.3}.get(name, SNAP)
    u = ease_out(span(t, at, at + move), 4) if move else 1
    p = _blend(POSES[prev], POSES[name], u)
    # a servo's settle after the snap, and a breath in the holds
    settle = math.sin((t - at) * 60) * math.exp(-(t - at) * 18) * 0.04 if t > at + move * 0.6 else 0
    p['tilt'] += settle + 0.01 * math.sin(t * 3.1)
    return p


def _limb(ctx, x, y, angle, length, width, colour, armour=None):
    """A segment from (x, y) at angle (from straight down, + turning toward screen right) as a
    gunmetal cylinder with a chrome armour plate and a piston; returns its end."""
    ex, ey = x + math.sin(angle) * length, y + math.cos(angle) * length
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(-angle)
    rounded_rect(ctx, -width / 2, -width * 0.15, width, length + width * 0.3, width * 0.45)
    inked(ctx, colour, 0.07, (0.05, 0.05))
    if armour:
        rounded_rect(ctx, -width * 0.42, length * 0.18, width * 0.84, length * 0.6, width * 0.3)
        inked(ctx, armour, 0.05, (0.0, 0.0))
        ctx.rectangle(-width * 0.06, length * 0.24, width * 0.12, length * 0.48)
        ctx.set_source_rgb(*TEAL)
        ctx.fill()
    ctx.move_to(width * 0.55, length * 0.12)               # the piston along it
    ctx.line_to(width * 0.55, length * 0.85)
    ctx.set_source_rgb(*CHROME)
    ctx.set_line_width(0.06)
    ctx.stroke()
    ctx.restore()
    return ex, ey


def _joint(ctx, x, y, r):
    ctx.arc(x, y, r, 0, TAU)
    inked(ctx, CHROME, 0.06, (0.04, 0.04))
    ctx.arc(x, y, r * 0.38, 0, TAU)
    ctx.set_source_rgb(*PINK)
    ctx.fill()


def _hand(ctx, x, y, angle, kind, glow=0.0):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(-angle)
    if kind == 'open':
        rounded_rect(ctx, -0.2, -0.05, 0.4, 0.34, 0.08)
        inked(ctx, GUNMETAL, 0.06, (0.04, 0.04))
        for i in range(4):
            rounded_rect(ctx, -0.19 + i * 0.1, 0.27, 0.08, 0.24, 0.04)
            inked(ctx, CHROME, 0.04, (0, 0))
        rounded_rect(ctx, 0.2, 0.0, 0.16, 0.08, 0.04)
        inked(ctx, CHROME, 0.04, (0, 0))
        if glow > 0:
            halo = cairo.RadialGradient(0, 0.1, 0, 0, 0.1, 0.5)
            halo.add_color_stop_rgba(0, *TEAL, 0.8 * glow)
            halo.add_color_stop_rgba(1, *TEAL, 0)
            ctx.set_source(halo)
            ctx.arc(0, 0.1, 0.5, 0, TAU)
            ctx.fill()
    elif kind == 'flat':
        rounded_rect(ctx, -0.17, -0.05, 0.34, 0.56, 0.08)
        inked(ctx, CHROME, 0.06, (0.04, 0.04))
    elif kind == 'point':
        rounded_rect(ctx, -0.2, -0.05, 0.4, 0.36, 0.1)
        inked(ctx, GUNMETAL, 0.06, (0.04, 0.04))
        rounded_rect(ctx, -0.05, 0.25, 0.1, 0.42, 0.05)
        inked(ctx, CHROME, 0.05, (0.03, 0.03))
    else:   # fist (a ball in it, for 'ball')
        rounded_rect(ctx, -0.22, -0.05, 0.44, 0.42, 0.12)
        inked(ctx, GUNMETAL, 0.06, (0.04, 0.04))
        for i in range(3):
            ctx.arc(-0.12 + i * 0.12, 0.3, 0.06, 0, TAU)
            ctx.set_source_rgb(*CHROME)
            ctx.fill()
    ctx.restore()


def football(ctx, x, y, size, spin, heat=0.0, px=1.0):
    """A football, size units long (px pixels a unit), spun about its middle; heat turns it into
    a meteor's core."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(spin)
    ctx.scale(size / 2, size / 3.4)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, mix((0.55, 0.28, 0.12), (1.0, 0.85, 0.5), heat), max(1.5 / px, size * 0.06), (size * 0.05, size * 0.05))
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(spin)
    ctx.move_to(-size * 0.18, 0)
    ctx.line_to(size * 0.18, 0)
    for i in range(5):
        ctx.move_to(-size * 0.12 + i * size * 0.06, -size * 0.05)
        ctx.line_to(-size * 0.12 + i * size * 0.06, size * 0.05)
    ctx.set_source_rgba(1, 1, 1, 1 - heat)
    ctx.set_line_width(max(1 / px, size * 0.03))
    ctx.stroke()
    ctx.restore()


def unit19(ctx, t, x, y, k):
    """The robot, its boots at screen (x, y), k px a metre, in the pose of the moment."""
    p = pose(t)
    visor = 0.55 + 0.45 * max((1 - span(t, at, at + 0.25) for at in MOVES + (LAND, CATCH) if t >= at), default=0)
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(k, k)
    # the ground shadow
    ctx.save()
    ctx.scale(1, 0.18)
    ctx.arc(0, 0, 1.7, 0, TAU)
    ctx.restore()
    ctx.set_source_rgba(0, 0, 0, 0.35 * (1 - span(robot_height(t), 0, 20)))
    ctx.fill()
    lift = -robot_height(t) * 0           # the caller places the boots; nothing here
    hip_y = -2.3 + p['crouch'] + lift
    ctx.save()
    ctx.translate(0, hip_y)
    ctx.rotate(p['tilt'])
    # legs, from the hips; the boots and their thrusters
    feet = []
    for side, (ha, kb) in ((-1, p['rleg']), (1, p['lleg'])):
        hx = side * 0.42
        kx, ky = _limb(ctx, hx, 0.0, side * ha, 1.05, 0.42, GUNMETAL, CHROME)
        fx, fy = _limb(ctx, kx, ky, side * (ha - kb) if kb else side * ha * 0.6, 1.0, 0.38, GUNMETAL, CHROME)
        _joint(ctx, kx, ky, 0.2)
        feet.append((fx, fy, side))
    for fx, fy, side in feet:
        ctx.save()
        ctx.translate(fx, fy)
        ctx.rotate(-p['tilt'])
        ctx.move_to(-0.36, -0.12)
        ctx.line_to(0.36, -0.12)
        ctx.line_to(0.42, 0.22)
        ctx.line_to(-0.42, 0.22)
        ctx.close_path()
        inked(ctx, CHROME, 0.07, (0.05, 0.05))
        ctx.rectangle(-0.42, 0.13, 0.84, 0.09)
        ctx.set_source_rgb(*PINK)
        ctx.fill()
        if t < LAND:                                       # the thrusters
            flick = 0.85 + 0.15 * math.sin(t * 90 + side)
            g = cairo.LinearGradient(0, 0.22, 0, 1.8 * flick)
            g.add_color_stop_rgba(0, 0.8, 0.95, 1, 0.95)
            g.add_color_stop_rgba(0.3, *FLAME, 0.85)
            g.add_color_stop_rgba(1, *FLAME, 0)
            ctx.move_to(-0.3, 0.22)
            ctx.line_to(0.3, 0.22)
            ctx.line_to(0, 1.9 * flick)
            ctx.close_path()
            ctx.set_operator(cairo.OPERATOR_ADD)
            ctx.set_source(g)
            ctx.fill()
            ctx.set_operator(cairo.OPERATOR_OVER)
        ctx.restore()
    # the pelvis and the abdomen's pistons
    rounded_rect(ctx, -0.62, -0.25, 1.24, 0.5, 0.14)
    inked(ctx, CHROME, 0.07, (0.05, 0.05))
    ctx.rectangle(-0.6, -0.04, 1.2, 0.07)
    ctx.set_source_rgb(*PINK)
    ctx.fill()
    for sx in (-0.38, -0.13, 0.13, 0.38):
        rounded_rect(ctx, sx - 0.07, -0.85, 0.14, 0.62, 0.05)
        inked(ctx, GUNMETAL, 0.04, (0.02, 0.02))
        ctx.rectangle(sx - 0.025, -0.82, 0.05, 0.5)
        ctx.set_source_rgb(*CHROME)
        ctx.fill()
    # the chest: a chrome plate, VIZELVISION 19; its hatch opens for the ball
    ctx.move_to(-0.85, -1.75)
    ctx.line_to(0.85, -1.75)
    ctx.line_to(0.66, -0.68)
    ctx.line_to(-0.66, -0.68)
    ctx.close_path()
    inked(ctx, CHROME, 0.08, (0.06, 0.06))
    hatch = span(t, HATCH[0], HATCH[0] + 0.15) * (1 - span(t, HATCH[1] + 0.1, HATCH[1] + 0.3))
    rounded_rect(ctx, -0.42, -1.6, 0.84, 0.7, 0.1)
    inked(ctx, mix(GUN_DARK, (0.05, 0.03, 0.08), hatch), 0.05, (0, 0))
    if hatch < 0.95:
        ctx.save()
        ctx.rectangle(-0.42, -1.6 + 0.7 * hatch, 0.84, 0.7 * (1 - hatch))
        ctx.clip()
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(0.62)
        ext = ctx.text_extents('19')
        ctx.move_to(-ext.width / 2 - ext.x_bearing, -1.0 + 0.7 * hatch)
        ctx.text_path('19')
        inked(ctx, PINK, 0.06, (0.03, 0.03))
        ctx.restore()
    if hatch > 0:                                           # the glow inside
        g = cairo.RadialGradient(0, -1.25, 0, 0, -1.25, 0.5)
        g.add_color_stop_rgba(0, *TEAL, 0.9 * hatch)
        g.add_color_stop_rgba(1, *TEAL, 0)
        ctx.set_source(g)
        ctx.arc(0, -1.25, 0.5, 0, TAU)
        ctx.fill()
    rounded_rect(ctx, -0.6, -0.86, 1.2, 0.17, 0.05)
    inked(ctx, TEAL, 0.04, (0, 0))
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(0.13)
    ext = ctx.text_extents('VIZELVISION')
    ctx.move_to(-ext.width / 2 - ext.x_bearing, -0.73)
    ctx.text_path('VIZELVISION')
    ctx.set_source_rgb(*INK)
    ctx.fill()
    # the head: neck, helmet, its stripe, the face mask over the visor
    ctx.save()
    ctx.translate(0, -1.82)
    ctx.rotate(p['head'] * 0.35)
    rounded_rect(ctx, -0.22, -0.22, 0.44, 0.26, 0.06)
    inked(ctx, GUNMETAL, 0.05, (0.03, 0.03))
    ctx.arc(0, -0.72, 0.56, math.pi * 0.95, math.pi * 2.05)
    ctx.line_to(0.52, -0.25)
    ctx.line_to(-0.52, -0.25)
    ctx.close_path()
    inked(ctx, CHROME, 0.08, (0.06, 0.06))
    ctx.rectangle(-0.08, -1.28, 0.16, 0.6)
    ctx.set_source_rgb(*TEAL)
    ctx.fill()
    ctx.arc(-0.5, -0.62, 0.12, 0, TAU)
    ctx.arc(0.5, -0.62, 0.12, 0, TAU)
    ctx.set_source_rgb(*PINK)
    ctx.fill()
    rounded_rect(ctx, -0.42, -0.72, 0.84, 0.24, 0.1)          # the visor
    ctx.set_source_rgb(0.02, 0.02, 0.05)
    ctx.fill()
    g = cairo.LinearGradient(-0.4, 0, 0.4, 0)
    for stop, a in ((0, 0.25), (0.5, 1.0), (1, 0.25)):
        g.add_color_stop_rgba(stop, *mix(TEAL, (0.8, 1, 1), visor - 0.5), a * visor)
    rounded_rect(ctx, -0.38, -0.66, 0.76, 0.12, 0.05)
    ctx.set_source(g)
    ctx.fill()
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    halo = cairo.RadialGradient(0, -0.6, 0, 0, -0.6, 0.9)
    halo.add_color_stop_rgba(0, *TEAL, 0.45 * visor)
    halo.add_color_stop_rgba(1, *TEAL, 0)
    ctx.set_source(halo)
    ctx.arc(0, -0.6, 0.9, 0, TAU)
    ctx.fill()
    ctx.restore()
    for xx in (-0.28, 0.0, 0.28):                              # the face mask's bars
        ctx.move_to(xx, -0.48)
        ctx.line_to(xx * 0.8, -0.24)
    ctx.move_to(-0.45, -0.42)
    ctx.line_to(0.45, -0.42)
    ctx.set_source_rgb(*GUN_DARK)
    ctx.set_line_width(0.07)
    ctx.stroke()
    ctx.restore()
    # arms, from the shoulders, then the shoulder pads over them
    hands = []
    for side, (sa, el), hand in ((-1, p['rarm'], p['hand'][0]), (1, p['larm'], p['hand'][1])):
        sx, sy = side * 1.0, -1.55
        ex, ey = _limb(ctx, sx, sy, side * sa, 0.95, 0.34, GUNMETAL)
        wx, wy = _limb(ctx, ex, ey, side * (sa + el), 0.95, 0.32, GUNMETAL, CHROME)
        _joint(ctx, ex, ey, 0.17)
        hands.append((wx, wy, side * (sa + el), hand))
    for side in (-1, 1):
        ctx.save()
        ctx.translate(side * 0.95, -1.62)
        ctx.scale(1, 0.72)
        ctx.arc(0, 0, 0.58, math.pi, TAU)
        ctx.restore()
        ctx.close_path()
        inked(ctx, CHROME, 0.08, (0.05, 0.05))
        ctx.save()
        ctx.translate(side * 0.95, -1.62)
        ctx.scale(1, 0.72)
        ctx.arc(0, 0, 0.5, math.pi * 1.15, math.pi * 1.85)
        ctx.restore()
        ctx.set_source_rgb(*PINK)
        ctx.set_line_width(0.09)
        ctx.stroke()
    for wx, wy, angle, hand in hands:
        if hand == 'ball':
            _hand(ctx, wx, wy, angle, 'open')
            football(ctx, wx + math.sin(angle) * 0.42, wy + math.cos(angle) * 0.42, 0.95, 0.4 + angle,
                     heat=1 - span(t, CATCH, CATCH + 1.2), px=k)
        else:
            _hand(ctx, wx, wy, angle, hand, glow=span(t, DIM[0], DIM[1]) * (t < CATCH))
    ctx.restore()
    ctx.restore()
    # where its right hand is (screen), for the ball and the meteor
    wx, wy, angle, _ = hands[0]
    ca, sa_ = math.cos(p['tilt']), math.sin(p['tilt'])
    hx, hy = wx * ca - wy * sa_, wx * sa_ + wy * ca + hip_y
    return x + hx * k, y + hy * k, hands


def hand_point(t, hor=HOR0, zoom_=1.0):
    """Screen position of the robot's right hand at t."""
    p = pose(t)
    sa, el = p['rarm']
    side = -1
    sx, sy = side * 1.0, -1.55
    ex, ey = sx + math.sin(side * sa) * 0.95, sy + math.cos(side * sa) * 0.95
    a2 = side * (sa + el)
    wx, wy = ex + math.sin(a2) * 1.25, ey + math.cos(a2) * 1.25
    hip_y = -2.3 + p['crouch']
    ca, s = math.cos(p['tilt']), math.sin(p['tilt'])
    hx, hy = wx * ca - wy * s, wx * s + wy * ca + hip_y
    bx, by = project(0, 0, ROBOT_Z, hor, zoom_)
    k = scale(ROBOT_Z) * zoom_
    return bx + hx * k, by + hy * k


# ---------------------------------------------------------------- the landing, sparks and turf

def landing(ctx, t, x, y, k):
    p = span(t, LAND, LAND + 0.7)
    if p <= 0 or p >= 1:
        return
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(1, 0.22)
    r = (1.5 + 9 * ease_out(p)) * k
    ctx.arc(0, 0, r, 0, TAU)
    ctx.set_source_rgba(1, 0.95, 0.8, 0.6 * (1 - p))
    ctx.set_line_width(14 * (1 - p) + 2)
    ctx.stroke()
    ctx.restore()
    rand = random.Random(71)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for i in range(46):                                     # sparks
        a = rand.uniform(math.pi * 1.05, math.pi * 1.95)
        v = rand.uniform(4, 16) * k
        tt = (t - LAND) * rand.uniform(0.8, 1.2)
        sx = x + math.cos(a) * v * tt * 1.6
        sy = y + math.sin(a) * v * tt + 9.8 * k * tt * tt * 2
        ex, ey = sx - math.cos(a) * 0.5 * k, sy - math.sin(a) * 0.5 * k
        ctx.move_to(sx, sy)
        ctx.line_to(ex, ey)
        ctx.set_source_rgba(1, 0.85, 0.35, 1 - p)
        ctx.set_line_width(2.4)
        ctx.stroke()
    ctx.restore()
    for i in range(24):                                     # turf
        a = rand.uniform(math.pi * 1.1, math.pi * 1.9)
        v = rand.uniform(3, 9) * k
        tt = t - LAND
        sx = x + math.cos(a) * v * tt * 1.4
        sy = y + math.sin(a) * v * tt + 9.8 * k * tt * tt * 1.2
        ctx.rectangle(sx - 3, sy - 2, 6 + (i % 3) * 2, 4)
        ctx.set_source_rgba(*rand.choice((TURF[0], (0.35, 0.24, 0.12))), 1 - p)
        ctx.fill()
    dust = span(t, LAND, LAND + 1.4)
    for i in range(7):
        a = i / 6 * math.pi
        dx = math.cos(a) * (2 + 4 * ease_out(dust)) * k
        ctx.save()
        ctx.translate(x + dx, y - (0.25 + 0.35 * dust) * k)
        ctx.scale(1, 0.45)
        ctx.arc(0, 0, (0.6 + 1.0 * dust) * k, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(0.75, 0.72, 0.68, 0.2 * (1 - dust))
        ctx.fill()


def streak(ctx, t, hor):
    """The robot as a streak of fire on the way down."""
    if t >= LAND - 0.05:
        return
    bx, by = project(0, robot_height(t) + 2.5, ROBOT_Z, hor)
    tail = 260 * (1 - span(t, 0.75, LAND))
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    g = cairo.LinearGradient(bx, by - tail, bx, by)
    g.add_color_stop_rgba(0, *FLAME, 0)
    g.add_color_stop_rgba(1, 1, 0.9, 0.6, 0.5)
    ctx.move_to(bx - 22, by)
    ctx.line_to(bx + 22, by)
    ctx.line_to(bx + 4, by - tail)
    ctx.line_to(bx - 4, by - tail)
    ctx.close_path()
    ctx.set_source(g)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- orbit

@lru_cache(maxsize=None)
def earth():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    cx, cy, r = 640, 2620, 2060
    halo = cairo.RadialGradient(cx, cy, r - 10, cx, cy, r + 70)
    halo.add_color_stop_rgba(0, 0.45, 0.8, 1, 0.9)
    halo.add_color_stop_rgba(1, 0.3, 0.6, 1, 0)
    ctx.set_source(halo)
    ctx.arc(cx, cy, r + 70, 0, TAU)
    ctx.fill()
    ctx.arc(cx, cy, r, 0, TAU)
    g = cairo.LinearGradient(0, cy - r, 0, cy - r + 200)
    g.add_color_stop_rgb(0, 0.2, 0.45, 0.85)
    g.add_color_stop_rgb(1, 0.05, 0.16, 0.42)
    ctx.set_source(g)
    ctx.fill()
    rand = random.Random(3)
    ctx.save()
    ctx.arc(cx, cy, r, 0, TAU)
    ctx.clip()
    for _ in range(14):                                     # land and cloud
        x, y = rand.uniform(0, W), cy - r + rand.uniform(10, 160)
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(rand.uniform(80, 220), rand.uniform(10, 26))
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        ctx.set_source_rgba(*rand.choice(((0.25, 0.5, 0.25), (0.55, 0.48, 0.3), (1, 1, 1), (1, 1, 1))), 0.75)
        ctx.fill()
    shade = cairo.LinearGradient(0, 0, W, 0)
    shade.add_color_stop_rgba(0, 0, 0, 0.05, 0.75)
    shade.add_color_stop_rgba(0.45, 0, 0, 0.05, 0.0)
    ctx.set_source(shade)
    ctx.paint()
    for _ in range(90):                                     # the night side's lights
        x, y = rand.uniform(0, 420), cy - r + rand.uniform(15, 170)
        ctx.arc(x, y, rand.uniform(0.8, 1.8), 0, TAU)
        ctx.set_source_rgba(1, 0.85, 0.5, 0.85)
        ctx.fill()
    ctx.restore()
    return surface


def orbit_ball(t):
    """The ball's screen place and spin in orbit, and on the way home."""
    u = span(t, SPACE[0], SPACE[1])
    x = -60 + 860 * ease_in_out(u)
    y = 440 - 220 * math.sin(math.pi * min(1.0, u * 1.05)) * 0.9
    if t >= RETURN[0]:
        r = ease_in(span(t, *RETURN), 2)
        x, y = x + 380 * r, y + 420 * r
    return x, y, t * 9


def space(ctx, t, frame):
    ctx.set_source_rgb(0.0, 0.0, 0.02)
    ctx.paint()
    drift = (t - SPACE[0]) * 6
    ctx.set_source_surface(stars(), -drift, 0)
    ctx.paint()
    ctx.set_source_surface(stars(), W - drift, 0)
    ctx.paint()
    ctx.set_source_surface(earth(), 0, 0)
    ctx.paint()
    # a satellite, minding its business
    sx, sy = 980 - (t - SPACE[0]) * 22, 150 + (t - SPACE[0]) * 6
    ctx.save()
    ctx.translate(sx, sy)
    ctx.rotate(0.25 + 0.08 * math.sin(t))
    for side in (-1, 1):
        rounded_rect(ctx, side * 40 - 30, -12, 60, 24, 3)
        inked(ctx, (0.15, 0.25, 0.6), 3, (3, 3))
        for i in range(1, 4):
            ctx.move_to(side * 40 - 30 + i * 15, -12)
            ctx.line_to(side * 40 - 30 + i * 15, 12)
        ctx.set_source_rgba(0.7, 0.8, 1, 0.6)
        ctx.set_line_width(1)
        ctx.stroke()
    rounded_rect(ctx, -12, -16, 24, 32, 5)
    inked(ctx, CHROME, 3, (3, 3))
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(9)
    ctx.move_to(-10, 4)
    ctx.text_path('VZ19')
    ctx.set_source_rgb(*PINK)
    ctx.fill()
    ctx.restore()
    # the ball, tumbling, its contrail; on the way home it burns
    bx, by, spin = orbit_ball(t)
    heat = span(t, RETURN[0] - 0.05, RETURN[1])
    trail = 1 if heat > 0 else 0.6
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for i in range(14):
        tt = t - i * 0.03
        px, py, _ = orbit_ball(max(SPACE[0], tt))
        ctx.arc(px, py, (9 - i * 0.5) * (1 + 1.6 * heat), 0, TAU)
        colour = mix((0.7, 0.85, 1.0), FLAME, heat)
        ctx.set_source_rgba(*colour, (0.22 - i * 0.014) * trail)
        ctx.fill()
    ctx.restore()
    if heat > 0:
        g = cairo.RadialGradient(bx, by, 0, bx, by, 70 * heat + 10)
        g.add_color_stop_rgba(0, 1, 0.95, 0.7, 0.9)
        g.add_color_stop_rgba(0.5, *FLAME, 0.5)
        g.add_color_stop_rgba(1, *FLAME, 0)
        ctx.set_source(g)
        ctx.arc(bx, by, 70 * heat + 10, 0, TAU)
        ctx.fill()
    football(ctx, bx, by, 40, spin, heat)
    # the broadcast's stat, in the 5x7 face
    show = span(t, SPACE[0] + 0.35, SPACE[0] + 0.6) * (1 - span(t, RETURN[0], RETURN[0] + 0.1))
    if show > 0:
        ctx.save()
        ctx.translate(-260 * (1 - ease_out(show)), 0)
        rounded_rect(ctx, 48, 560, 330, 112, 10)
        inked(ctx, (0.04, 0.03, 0.1), 4, (5, 5))
        rounded_rect(ctx, 48, 560, 330, 30, 10)
        ctx.set_source_rgb(*PINK)
        ctx.fill()
        pixel_text(ctx, 'UNIT 19  PUNT', 64, 568, 2.4, WHITE)
        miles = int(254 * min(1.0, span(t, SPACE[0] + 0.35, SPACE[0] + 1.0)))
        pixel_text(ctx, f'DISTANCE  {miles} MI', 64, 604, 3, AMBER)
        if (t * 2.5) % 1 < 0.7:
            pixel_text(ctx, 'HANG TIME  STILL GOING', 64, 638, 3, TEAL)
        ctx.restore()
    flash = span(t, RETURN[1] - 0.06, RETURN[1])
    if flash > 0:
        ctx.set_source_rgba(1, 0.95, 0.85, flash)
        ctx.paint()


# ---------------------------------------------------------------- the finale

def spotlights(ctx, t, x, y, k):
    p = span(t, *DIM)
    if p <= 0:
        return
    ctx.set_source_rgba(0.02, 0.0, 0.05, 0.7 * ease_in_out(p))
    ctx.paint()
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for i, colour in enumerate((PINK, TEAL, WHITE, YELLOW)):
        settle = ease_in_out(span(t, DIM[0] + 0.08 * i, WORDMARK + 0.1))
        tx = x + (i - 1.5) * 260 * (1 - settle) + (i - 1.5) * 0.4 * k * settle
        rx = 2.6 * k
        g = cairo.RadialGradient(tx, y, 0, tx, y, rx)
        g.add_color_stop_rgba(0, *colour, 0.4 * p)
        g.add_color_stop_rgba(1, *colour, 0)
        ctx.save()
        ctx.translate(tx, y)
        ctx.scale(1, 0.25)
        ctx.arc(0, 0, rx, 0, TAU)
        ctx.restore()
        ctx.set_source(g)
        ctx.fill()
        beam = cairo.LinearGradient(tx, 0, tx, y)
        beam.add_color_stop_rgba(0, *colour, 0)
        beam.add_color_stop_rgba(1, *colour, 0.13 * p)
        top = W / 2 + (i - 1.5) * 300
        ctx.move_to(top - 18, 0)
        ctx.line_to(top + 18, 0)
        ctx.line_to(tx + rx * 0.45, y)
        ctx.line_to(tx - rx * 0.45, y)
        ctx.close_path()
        ctx.set_source(beam)
        ctx.fill()
    ctx.restore()


def meteor(ctx, t):
    """The ball's last dive, into the robot's palm on the last note."""
    if not METEOR[0] <= t < CATCH + 0.02:
        return
    hx, hy = hand_point(CATCH, horizon(CATCH), zoom(CATCH))
    u = ease_in(span(t, *METEOR), 1.6)
    sx, sy = W + 140, -120
    x, y = sx + (hx - sx) * u, sy + (hy - sy) * u
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    for i in range(12):
        v = max(0.0, u - i * 0.035)
        px, py = sx + (hx - sx) * v, sy + (hy - sy) * v
        ctx.arc(px, py, 26 - i * 1.8, 0, TAU)
        ctx.set_source_rgba(*FLAME, 0.3 - i * 0.022)
        ctx.fill()
    g = cairo.RadialGradient(x, y, 0, x, y, 60)
    g.add_color_stop_rgba(0, 1, 0.97, 0.8, 1)
    g.add_color_stop_rgba(1, *FLAME, 0)
    ctx.set_source(g)
    ctx.arc(x, y, 60, 0, TAU)
    ctx.fill()
    ctx.restore()
    football(ctx, x, y, 34, t * 14, 1.0)


def impact(ctx, t):
    p = span(t, CATCH, CATCH + 0.6)
    if p <= 0 or p >= 1:
        return
    hx, hy = hand_point(CATCH, horizon(CATCH), zoom(CATCH))
    rand = random.Random(8)
    ctx.save()
    ctx.set_operator(cairo.OPERATOR_ADD)
    flash = cairo.RadialGradient(hx, hy, 0, hx, hy, 260)
    flash.add_color_stop_rgba(0, 1, 0.95, 0.8, 0.9 * (1 - p))
    flash.add_color_stop_rgba(1, 1, 0.8, 0.5, 0)
    ctx.set_source(flash)
    ctx.paint()
    for i in range(40):
        a = rand.uniform(0, TAU)
        v = rand.uniform(120, 520)
        sx, sy = hx + math.cos(a) * v * p, hy + math.sin(a) * v * p + 300 * p * p
        ctx.move_to(sx, sy)
        ctx.line_to(sx - math.cos(a) * 18, sy - math.sin(a) * 18)
        ctx.set_source_rgba(1, 0.85, 0.35, 1 - p)
        ctx.set_line_width(2.6)
        ctx.stroke()
    ctx.restore()


def finale(ctx, t):
    if t < WORDMARK - 0.05:
        return
    neighborhood.lockup(ctx, t, WORDMARK, 212, scale=0.62)
    p = span(t, *SUBTITLE)
    if p > 0:
        ctx.save()
        ctx.rectangle(0, 0, W / 2 - 260 + 520 * ease_in_out(p), H)
        ctx.clip()
        ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(44)
        ctx.new_path()
        text_path(ctx, 'FOOTBALL ON', W / 2, 100, tracking=12, align='center')
        inked(ctx, YELLOW, 3, (5, 5), fatten=3)
        ctx.restore()
    for i, at in enumerate((WORDMARK + 0.3, CATCH + 0.2, WORDMARK + 2.0)):
        q = span(t, at, at + 0.5)
        if 0 < q < 1:
            glint(ctx, (380, 905, 640)[i], (140, 150, 112)[i], 22 * math.sin(math.pi * q), q * 3, 1)


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    if SPACE[0] <= t < RETURN[1]:
        space(ctx, t, frame)
    else:
        hor, z = horizon(t), zoom(t)
        sky(ctx, hor)
        ctx.save()                                           # the stadium, the lens zoomed about the horizon
        ctx.translate(W / 2, hor)
        ctx.scale(z, z)
        ctx.translate(-W / 2, -HOR0)
        ctx.set_source_surface(stadium(), -MX, -TALL)
        ctx.paint()
        ribbon(ctx, t, 0)
        busy = 1.0 if LAND <= t < DIM[1] or t > CATCH else 0.3
        crowd_flashes(ctx, t, frame, 0, busy)
        ctx.restore()
        for at, x in zip(MOVES, CANNON_X):
            cannon(ctx, t, x, at, hor)
        if LAND <= t < LAND + 0.8:
            for x in CANNON_X:
                cannon(ctx, t, x, LAND, hor)
        streak(ctx, t, hor)
        bx, by = project(0, robot_height(t), ROBOT_Z, hor, z)
        k = scale(ROBOT_Z) * z
        landing(ctx, t, bx, by, k)
        spotlights(ctx, t, bx, by, k)
        for at, x in zip((7.0, 7.25, 7.5, 8.0), CANNON_X):     # the closed logo's cannons, pink and teal
            cannon(ctx, t, x, at, hor, PINK if at in (7.0, 7.5) else TEAL, z)
        if t >= HATCH[0] + 0.05 and t < PUNT:                # the football
            if t < TOSS:
                hx, hy = hand_point(t)
                u = span(t, HATCH[0] + 0.05, HATCH[1])
                cx, cy = bx, by - 3.55 * k
                x, y = cx + (hx - cx) * ease_out(u), cy + (hy + 0.3 * k - cy) * ease_out(u)
            else:
                u = span(t, TOSS, PUNT)
                hx, hy = hand_point(TOSS)
                x = hx + (bx + 1.0 * k - hx) * u
                y = hy + (by - 0.9 * k - hy) * ease_in(u, 2)
            football(ctx, x, y, 0.95 * k, 0.6 + t * 2)
        unit19(ctx, t, bx, by, k)
        if PUNT <= t < SPACE[0]:                             # the punt, and the camera after it
            x, y = project(1.0 + 0.4 * span(t, PUNT, TILT[1]), ball_height(t), ROBOT_Z, hor)
            ctx.save()
            ctx.set_operator(cairo.OPERATOR_ADD)
            trail = cairo.LinearGradient(x, y, x, y + 340)
            trail.add_color_stop_rgba(0, 1, 0.95, 0.85, 0.75)
            trail.add_color_stop_rgba(1, 1, 0.95, 0.85, 0)
            ctx.move_to(x - 9, y)
            ctx.line_to(x + 9, y)
            ctx.line_to(x + 2, y + 340)
            ctx.line_to(x - 2, y + 340)
            ctx.close_path()
            ctx.set_source(trail)
            ctx.fill()
            boot = span(t, PUNT, PUNT + 0.18)
            if boot < 1:
                g = cairo.RadialGradient(x, y + 20, 0, x, y + 20, 120)
                g.add_color_stop_rgba(0, 1, 0.9, 0.6, 0.8 * (1 - boot))
                g.add_color_stop_rgba(1, *FLAME, 0)
                ctx.set_source(g)
                ctx.arc(x, y + 20, 120, 0, TAU)
                ctx.fill()
            ctx.restore()
            football(ctx, x, y, 0.95 * k, t * 18)
            out = span(t, TILT[1] - 0.18, TILT[1])         # through the top of the sky, into space
            if out > 0:
                ctx.set_source_rgba(0, 0, 0.02, out)
                ctx.paint()
        meteor(ctx, t)
        impact(ctx, t)
        finale(ctx, t)
        back = 1 - span(t, RETURN[1], RETURN[1] + 0.12)      # the flash out of the re-entry
        if RETURN[1] <= t and back > 0:
            ctx.set_source_rgba(1, 0.95, 0.85, back)
            ctx.paint()
    vignette(ctx, 0.4)
    grain(ctx, frame, 0.25)
    opening = 1 - ease_out(span(t, *STREAK))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
