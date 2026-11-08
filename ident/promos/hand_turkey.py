"""The Hand Turkey: the kindergarten classic, from above. A sheet of construction paper on
the craft table (a box of VizelVision crayons, glue, safety scissors, macaroni). A small hand
lands on the paper, fingers spread, and a brown crayon traces it: slowly round the thumb, then
one finger on each note of the open logo, faster and faster. The hand lifts away. The crayons
colour it in (four feathers: red, orange, yellow, green), a googly eye, a beak and a wattle,
two legs; and the hand turkey blinks, wiggles and hops across the paper. GOBBLE! On the closed
logo VIZELVISION is scribbled across the top a crayon a letter, HAPPY THANKSGIVIИG under it
with its N on backwards, and a gold star sticker slaps down. The turkey blinks.

Iris, the teacher: "Okay, everybody... trace your hand!" / "Oh! Well, hello there!" /
"Happy Thanksgiving!"
"""
import math
import random
from functools import lru_cache

import cairo

from common import (INK, TAU, W, H, WHITE, back_out, clamp, ease_in, ease_in_out, ease_out, font,  # noqa: F401
                    grain, inked, inked_stroke, iris, mix, pulse, rounded_rect, span, star, text_path, vignette)
from common import A

ID = 'hand-turkey'
NAME = 'The Hand Turkey'
KIND = 'ident'
ORDER = 53
DESCRIPTION = ("The kindergarten classic, from above: a small hand on construction paper is traced in brown "
               "crayon, a finger on each note of the open logo; it lifts away, the crayons colour in four "
               "feathers, a googly eye and a beak, and the hand turkey comes alive, hops and gobbles. "
               "VIZELVISION is scribbled across the top in crayon, HAPPY THANKSGIVING (one N backwards) and "
               "a gold star sticker. Voiced by Iris, the teacher.")
DURATION = 10.0
STILL_AT = 8.7
OVERLAYS = []

# Hit points (the music's too: hand_turkey_music.py).
IRIS_OPEN = (0.0, 0.5)
HAND_IN = (0.55, 1.05)
TRACE = 1.3                                  # the crayon sets down at the wrist
THUMB = 2.8                                  # ...and has gone round the thumb
FINGERS = (3.0, 3.25, 3.5, 4.0)              # the open logo: a finger traced on each note
TRACE_END = 4.2                              # back down to the wrist
HAND_OUT = (4.2, 4.55)
COLOUR = (4.5, 4.62, 4.74, 4.86)             # a feather coloured in on each
BODY = 4.98                                  # the palm and thumb, brown
FACE = 5.12                                  # googly eye, beak, wattle, legs
ALIVE = 5.4                                  # it blinks
HOPS = (5.75, 6.2)                           # two hops to the right
GOBBLE = (6.72, 7.12)
LOGO = (7.2, 7.45, 7.7, 8.2)                 # the closed logo: the wordmark, scribbled
STICKER = 8.2
BLINK = (8.75, 9.0)
IRIS_CLOSE = (9.25, 9.6)

PAPER = (150, 60, 980, 620)                  # x, y, w, h (turned a little)
PAPER_TURN = -0.025
HAND_AT = (600, 470)                         # the palm's centre
HAND_SCALE = 0.82
HOP_DX = 70
SKIN = (0.98, 0.8, 0.66)
CRAYON_BROWN = (0.5, 0.3, 0.16)
FEATHER_COLOURS = ((0.92, 0.16, 0.16), (1.0, 0.5, 0.08), (1.0, 0.82, 0.1), (0.3, 0.68, 0.2))
LETTER_COLOURS = ((0.92, 0.16, 0.16), (1.0, 0.5, 0.08), (0.95, 0.75, 0.05), (0.3, 0.68, 0.2), (0.15, 0.55, 0.85),
                  (0.55, 0.3, 0.75), (1.0, 0.35, 0.6), (0.92, 0.16, 0.16), (1.0, 0.5, 0.08), (0.3, 0.68, 0.2),
                  (0.15, 0.55, 0.85))

# The hand, palm down, thumb out to the left: (base x, base y, angle, length, width) about the
# palm's centre, before HAND_SCALE. Angles are screen angles (up is -pi/2).
THUMB_GEOM = (-92, 10, math.pi + 0.55, 130, 50)
FINGER_GEOM = ((-62, -62, -math.pi / 2 - 0.42, 168, 44), (-20, -76, -math.pi / 2 - 0.13, 186, 44),
               (24, -72, -math.pi / 2 + 0.16, 176, 42), (64, -54, -math.pi / 2 + 0.46, 140, 38))
PALM = (-96, -70, 96, 110)                   # left, top, right, wrist


# ---------------------------------------------------------------- the hand's outline

def finger_points(base, angle, length, width, pad, steps=14):
    """Up one side of a finger, round its tip and down the other (clockwise on screen)."""
    bx, by, = base
    dx, dy = math.cos(angle), math.sin(angle)
    r = width / 2 + pad
    cx, cy = bx + dx * (length - width / 2), by + dy * (length - width / 2)
    lx, ly = dy, -dx
    pts = [(bx + lx * r, by + ly * r)]
    for k in range(steps + 1):
        a = angle - math.pi / 2 + math.pi * k / steps
        pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    pts.append((bx - lx * r, by - ly * r))
    return pts


@lru_cache(maxsize=None)
def outline(pad):
    """The hand's outline as points about the palm's centre (scaled), and the index in it
    where each part ends: (thumb, four fingers, the end)."""
    s = HAND_SCALE
    left, top, right, wrist = PALM
    pts = [(left * s, wrist * s), ((left - pad) * s, (wrist - 20) * s)]
    marks = []
    tx, ty, ta, tl, tw = THUMB_GEOM
    pts += [(x * s, y * s) for x, y in finger_points((tx, ty), ta, tl, tw, pad)]
    marks.append(len(pts) - 1)
    pts.append(((left - pad * 0.3) * s, (top + 10) * s))
    for fx, fy, fa, fl, fw in FINGER_GEOM:
        pts += [(x * s, y * s) for x, y in finger_points((fx, fy), fa, fl, fw, pad)]
        marks.append(len(pts) - 1)
    pts += [((right + pad) * s, (top + 40) * s), ((right + pad) * s, (wrist - 20) * s), (right * s, wrist * s)]
    marks.append(len(pts) - 1)
    return pts, marks


def lengths(pts):
    out = [0.0]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        out.append(out[-1] + math.hypot(x1 - x0, y1 - y0))
    return out


def path(ctx, pts, close=False):
    ctx.move_to(*pts[0])
    for x, y in pts[1:]:
        ctx.line_to(x, y)
    if close:
        ctx.close_path()


def trace_progress(t):
    """How far along the traced outline the crayon is (in points of its run), by the hits."""
    pts, marks = outline(14)
    cum = lengths(pts)
    at = [cum[m] for m in marks]
    keys = ((TRACE, 0.0), (THUMB, at[0])) + tuple(zip(FINGERS, at[1:5])) + ((TRACE_END, at[5]),)
    if t <= keys[0][0]:
        return 0.0
    for (t0, d0), (t1, d1) in zip(keys, keys[1:]):
        if t <= t1:
            return d0 + (d1 - d0) * ease_in_out(span(t, t0, t1))
    return cum[-1]


def partial(pts, distance):
    """The outline up to distance along it, and where its end is."""
    cum = lengths(pts)
    out = [pts[0]]
    for k in range(1, len(pts)):
        if cum[k] <= distance:
            out.append(pts[k])
            continue
        seg = cum[k] - cum[k - 1]
        f = (distance - cum[k - 1]) / seg if seg else 0
        (x0, y0), (x1, y1) = pts[k - 1], pts[k]
        out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
        break
    return out


def crayon_line(ctx, pts, colour, width=7.0, seed=0):
    """A waxy crayon line: the stroke, a lighter broken pass over it, and a little grain."""
    if len(pts) < 2:
        return
    ctx.save()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    path(ctx, pts)
    ctx.set_source_rgba(*colour, 0.92)
    ctx.set_line_width(width)
    ctx.stroke()
    path(ctx, pts)
    ctx.set_source_rgba(*mix(colour, WHITE, 0.35), 0.5)
    ctx.set_line_width(width * 0.35)
    ctx.set_dash([3, 5, 1, 7], seed % 7)
    ctx.stroke()
    ctx.set_dash([])
    ctx.restore()


# ---------------------------------------------------------------- the table and paper

@lru_cache(maxsize=1)
def table_surface():
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(s)
    ctx.set_source_rgb(0.86, 0.72, 0.5)                        # a birch craft table
    ctx.paint()
    rand = random.Random(6)
    for k in range(60):
        y = rand.uniform(-20, H + 20)
        ctx.move_to(-10, y)
        ctx.curve_to(400, y + rand.uniform(-14, 14), 900, y + rand.uniform(-14, 14), W + 10, y + rand.uniform(-8, 8))
        ctx.set_source_rgba(0.6, 0.42, 0.24, rand.uniform(0.08, 0.22))
        ctx.set_line_width(rand.uniform(1, 4))
        ctx.stroke()
    crayon_box(ctx, 1180, 120)
    loose = ((1150, 400, 0.4, (0.15, 0.55, 0.85)), (1190, 470, -0.2, (0.55, 0.3, 0.75)),
             (70, 600, 1.2, (1.0, 0.35, 0.6)), (95, 160, -0.9, (0.3, 0.68, 0.2)))
    for x, y, a, colour in loose:
        crayon(ctx, x, y, a, colour, 0.9)
    glue(ctx, 70, 380)
    for k in range(9):                                         # macaroni
        mx, my = 1120 + rand.uniform(-50, 70), 620 + rand.uniform(-40, 50)
        ctx.save()
        ctx.translate(mx, my)
        ctx.rotate(rand.uniform(0, TAU))
        ctx.arc(0, 0, 12, math.pi * 0.1, math.pi * 1.1)
        ctx.set_line_width(9)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_source_rgb(*INK)
        ctx.stroke_preserve()
        ctx.set_source_rgb(0.98, 0.82, 0.42)
        ctx.set_line_width(6)
        ctx.stroke()
        ctx.restore()
    paper(ctx)
    return s


def crayon_box(ctx, x, y):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(0.12)
    for k, colour in enumerate(LETTER_COLOURS[:7]):            # tips poking out the top
        ctx.move_to(-62 + k * 18, -60)
        ctx.line_to(-55 + k * 18, -86 - 4 * (k % 2))
        ctx.line_to(-48 + k * 18, -60)
        ctx.close_path()
        inked(ctx, colour, 2.5, (0, 0))
    rounded_rect(ctx, -76, -62, 152, 170, 6)
    inked(ctx, (1.0, 0.82, 0.12), 4, (6, 6))
    ctx.move_to(-76, -10)                                      # the green chevron band
    ctx.line_to(0, 22)
    ctx.line_to(76, -10)
    ctx.line_to(76, 20)
    ctx.line_to(0, 52)
    ctx.line_to(-76, 20)
    ctx.close_path()
    ctx.set_source_rgb(0.2, 0.6, 0.3)
    ctx.fill()
    ctx.save()
    ctx.translate(0, 76)
    ctx.scale(0.16, 0.16)
    A.draw_tv(ctx, 0.0, 1, 0.0)
    ctx.restore()
    font(ctx, 'Quicksand', 15)
    ctx.new_path()
    text_path(ctx, 'VIZELVISION', 0, 4, align='center')
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.restore()


def crayon(ctx, x, y, angle, colour, s=1.0, worn=0.0):
    """A crayon lying (or held) with its tip at (x, y), pointing along angle."""
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(angle)
    ctx.scale(s, s)
    ctx.move_to(0, 0)                                          # the tip
    ctx.line_to(22, -9 + 2 * worn)
    ctx.line_to(22, 9 - 2 * worn)
    ctx.close_path()
    inked(ctx, colour, 2.5, (3, 3))
    rounded_rect(ctx, 22, -10, 110, 20, 3)
    inked(ctx, colour, 2.5, (3, 3))
    rounded_rect(ctx, 38, -10.5, 76, 21, 2)                    # the paper wrapper
    ctx.set_source_rgb(*mix(colour, WHITE, 0.25))
    ctx.fill()
    for bx in (42, 108):
        ctx.rectangle(bx, -10.5, 3, 21)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.restore()


def glue(ctx, x, y):
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(-0.3)
    rounded_rect(ctx, -26, -60, 52, 110, 12)
    inked(ctx, WHITE, 3.5, (5, 5))
    ctx.rectangle(-26, -18, 52, 34)
    ctx.set_source_rgb(1.0, 0.55, 0.1)
    ctx.fill()
    ctx.move_to(-12, -60)
    ctx.line_to(12, -60)
    ctx.line_to(4, -86)
    ctx.line_to(-4, -86)
    ctx.close_path()
    inked(ctx, (1.0, 0.55, 0.1), 3, (3, 3))
    ctx.restore()


def paper(ctx):
    x, y, w, h = PAPER
    ctx.save()
    ctx.translate(x + w / 2, y + h / 2)
    ctx.rotate(PAPER_TURN)
    ctx.rectangle(-w / 2 + 10, -h / 2 + 12, w, h)              # its shadow
    ctx.set_source_rgba(0, 0, 0, 0.22)
    ctx.fill()
    ctx.rectangle(-w / 2, -h / 2, w, h)
    ctx.set_source_rgb(0.97, 0.88, 0.7)
    ctx.fill()
    rand = random.Random(12)
    for _ in range(900):                                       # the paper's fibres
        fx, fy = rand.uniform(-w / 2, w / 2), rand.uniform(-h / 2, h / 2)
        a = rand.uniform(0, TAU)
        ctx.move_to(fx, fy)
        ctx.line_to(fx + 4 * math.cos(a), fy + 4 * math.sin(a))
    ctx.set_source_rgba(0.7, 0.55, 0.35, 0.25)
    ctx.set_line_width(1)
    ctx.stroke()
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)   # the name, in pencil
    ctx.set_font_size(26)
    ctx.move_to(w / 2 - 150, h / 2 - 26)
    ctx.text_path('by Sam, age 5')
    ctx.set_source_rgba(0.35, 0.35, 0.4, 0.7)
    ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the hand

def draw_hand(ctx, ox, oy):
    pts, _ = outline(0)
    ctx.save()
    ctx.translate(ox, oy)
    ctx.translate(16, 22)                                      # its shadow on the paper
    path(ctx, pts, close=True)
    ctx.set_source_rgba(0, 0, 0, 0.2)
    ctx.fill()
    ctx.translate(-16, -22)
    path(ctx, pts + [(pts[-1][0], 400), (pts[0][0], 400)], close=True)   # the arm goes on off the frame
    g = cairo.LinearGradient(-100, 0, 100, 0)
    g.add_color_stop_rgb(0, *mix(SKIN, INK, 0.08))
    g.add_color_stop_rgb(0.5, *SKIN)
    g.add_color_stop_rgb(1, *mix(SKIN, INK, 0.12))
    inked(ctx, g, 3.5, (0, 0))
    s = HAND_SCALE
    for fx, fy, fa, fl, fw in FINGER_GEOM + (THUMB_GEOM,):     # nails and knuckle creases
        dx, dy = math.cos(fa), math.sin(fa)
        nx, ny = (fx + dx * (fl - fw * 0.6)) * s, (fy + dy * (fl - fw * 0.6)) * s
        ctx.save()
        ctx.translate(nx, ny)
        ctx.rotate(fa + math.pi / 2)
        rounded_rect(ctx, -fw * 0.28 * s, -fw * 0.36 * s, fw * 0.56 * s, fw * 0.6 * s, 6)
        ctx.restore()
        ctx.set_source_rgba(1.0, 0.92, 0.88, 0.9)
        ctx.fill_preserve()
        ctx.set_source_rgba(*INK, 0.35)
        ctx.set_line_width(1.5)
        ctx.stroke()
        kx, ky = (fx + dx * fl * 0.45) * s, (fy + dy * fl * 0.45) * s
        ctx.move_to(kx - dy * 9, ky + dx * 9)
        ctx.line_to(kx + dy * 9, ky - dx * 9)
        ctx.set_source_rgba(*INK, 0.25)
        ctx.set_line_width(2)
        ctx.stroke()
    ctx.restore()


def hand(ctx, t):
    if t < HAND_IN[0] or t > HAND_OUT[1]:
        return
    p_in = ease_out(span(t, *HAND_IN))
    p_out = ease_in(span(t, *HAND_OUT))
    hx, hy = HAND_AT
    draw_hand(ctx, hx, hy + 420 * (1 - p_in) + 460 * p_out - 18 * p_out)


def held_crayon(ctx, t):
    """The brown crayon, at the end of the line while it traces; it lifts away after."""
    if t < TRACE - 0.3 or t > TRACE_END + 0.4:
        return
    pts, _ = outline(14)
    hx, hy = HAND_AT
    d = trace_progress(t)
    run = partial(pts, max(d, 0.5))
    x, y = run[-1]
    lift = ease_in(span(t, TRACE_END, TRACE_END + 0.4))
    arrive = 1 - ease_out(span(t, TRACE - 0.3, TRACE))
    wob = 0.06 * math.sin(t * 23)
    crayon(ctx, hx + x + 260 * arrive + 200 * lift, hy + y - 60 * arrive - 220 * lift, -0.95 + wob, CRAYON_BROWN, 1.1, 0.6)


# ---------------------------------------------------------------- the turkey

def life(t):
    """(dx, dy, squash) of the hand turkey once it's alive: two hops to the right."""
    dx, dy, sq = 0.0, 0.0, 0.0
    for k, when in enumerate(HOPS):
        p = span(t, when, when + 0.3)
        dx += HOP_DX * ease_in_out(p)
        dy -= 70 * math.sin(math.pi * p)
        sq += 0.18 * pulse(t, when, 0.12) - 0.14 * pulse(t, when + 0.3, 0.15)
    sq += 0.08 * pulse(t, GOBBLE[0], 0.2)
    wiggle = 0.04 * math.sin(TAU * 3 * span(t, ALIVE + 0.2, ALIVE + 0.6))
    return dx, dy, sq, wiggle


def scribble_fill(ctx, clip_pts, colour, p, seed, step=11, angle=0.6):
    """Zig-zag crayon strokes filling the shape, p (0..1) of the way through it."""
    if p <= 0:
        return
    ctx.save()
    path(ctx, clip_pts, close=True)
    ctx.clip()
    xs = [x for x, _ in clip_pts]
    ys = [y for _, y in clip_pts]
    x0, x1, y0, y1 = min(xs) - 40, max(xs) + 40, min(ys) - 40, max(ys) + 40
    rand = random.Random(seed)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    rows = int((y1 - y0) / step) + 1
    done = p * rows
    ctx.move_to(x0, y1)
    for r in range(rows):
        if r > done:
            break
        y = y1 - r * step
        a, b = (x0, x1) if r % 2 == 0 else (x1, x0)
        frac = clamp(done - r)
        ctx.line_to(a + (b - a) * frac, y - step * 0.5 + rand.uniform(-3, 3) - (b - a) * frac * 0.12 * angle)
    ctx.set_source_rgba(*colour, 0.85)
    ctx.set_line_width(step * 1.35)
    ctx.stroke()
    ctx.restore()


def finger_shape(k, pad=8):
    geom = FINGER_GEOM[k] if k < 4 else THUMB_GEOM
    fx, fy, fa, fl, fw = geom
    s = HAND_SCALE
    pts = finger_points((fx, fy), fa, fl, fw, pad)
    back = (-math.cos(fa) * 30, -math.sin(fa) * 30)
    pts = pts + [(pts[-1][0] + back[0], pts[-1][1] + back[1]), (pts[0][0] + back[0], pts[0][1] + back[1])]
    return [(x * s, y * s) for x, y in pts]


def head_at():
    tx, ty, ta, tl, tw = THUMB_GEOM
    s = HAND_SCALE
    return ((tx + math.cos(ta) * (tl - tw * 0.55)) * s, (ty + math.sin(ta) * (tl - tw * 0.55)) * s)


def turkey(ctx, t):
    """The traced outline, coloured in, with its face; alive from ALIVE on."""
    if t < TRACE:
        return
    hx, hy = HAND_AT
    dx, dy, sq, wiggle = life(t)
    ctx.save()
    ctx.translate(hx + dx, hy + dy)
    ctx.translate(0, 120)
    ctx.scale(1 + sq * 0.6, 1 - sq)
    ctx.rotate(wiggle)
    ctx.translate(0, -120)
    if dy < 0:                                                 # off the paper: its shadow below
        ctx.save()
        ctx.translate(14, 18 - dy)
        ctx.scale(1 + dy / 600, 1 + dy / 600)
        path(ctx, outline(14)[0], close=True)
        ctx.set_source_rgba(0, 0, 0, 0.18)
        ctx.fill()
        ctx.restore()
    if t >= HAND_OUT[1] - 0.2:                                 # the paper turkey, cut loose once alive
        if t >= ALIVE:
            path(ctx, outline(22)[0], close=True)
            ctx.set_source_rgb(0.97, 0.88, 0.7)
            ctx.fill()
        for k, when in enumerate(COLOUR):
            scribble_fill(ctx, finger_shape(k, 10), FEATHER_COLOURS[k], ease_in_out(span(t, when - 0.1, when + 0.08)), k,
                          angle=0.4 + 0.2 * k)
        body = ease_in_out(span(t, BODY - 0.12, BODY + 0.08))
        palm = [(x * HAND_SCALE, y * HAND_SCALE) for x, y in ((PALM[0] - 6, PALM[3]), (PALM[0] - 8, PALM[1] + 6),
                                                              (PALM[2] + 8, PALM[1] + 6), (PALM[2] + 8, PALM[3]))]
        scribble_fill(ctx, palm, (0.62, 0.38, 0.2), body, 7, step=12)
        scribble_fill(ctx, finger_shape(4, 10), (0.62, 0.38, 0.2), body, 8, step=10)
    pts, _ = outline(14)                                       # the traced line itself
    crayon_line(ctx, partial(pts, trace_progress(t)), CRAYON_BROWN, 8, 1)
    face(ctx, t)
    ctx.restore()


def face(ctx, t):
    p = back_out(span(t, FACE, FACE + 0.22), 2.8)
    if p <= 0:
        return
    x, y = head_at()
    tx, ty, ta, tl, tw = THUMB_GEOM
    gob = math.sin(math.pi * span(t, *GOBBLE)) if GOBBLE[0] <= t <= GOBBLE[1] else 0.0
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(p, p)
    bx, by = math.cos(ta) * 30, math.sin(ta) * 30              # the beak, past the tip
    ctx.save()
    ctx.translate(bx, by)
    ctx.rotate(ta)
    for sign in (-1, 1):
        ctx.save()
        ctx.rotate(sign * 0.35 * gob)
        ctx.move_to(-4, 0)
        ctx.line_to(26, sign * 3)
        ctx.line_to(-4, sign * 15)
        ctx.close_path()
        ctx.restore()
        inked(ctx, (1.0, 0.62, 0.1), 3, (2, 2))
    ctx.restore()
    ctx.move_to(bx - 4, by + 10)                               # the wattle, a red crayon squiggle
    ctx.curve_to(bx - 4, by + 40 + 6 * gob, bx - 26, by + 44, bx - 22, by + 14)
    ctx.set_source_rgb(0.92, 0.16, 0.16)
    ctx.set_line_width(9)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    blink = math.sin(math.pi * span(t, ALIVE, ALIVE + 0.2)) + math.sin(math.pi * span(t, *BLINK))
    ex, ey = -4, -14                                           # the googly eye
    ctx.arc(ex, ey, 17, 0, TAU)
    inked(ctx, WHITE, 3, (3, 3))
    alive = span(t, ALIVE, ALIVE + 0.01)
    roll = t * 4 if alive else 0.0
    jig = 4 * math.sin(t * 31) * (pulse(t, HOPS[0] + 0.3, 0.3) + pulse(t, HOPS[1] + 0.3, 0.3) + pulse(t, FACE + 0.1, 0.4))
    px, py = ex + 6 * math.cos(roll + 1.2) * alive + jig, ey + 5 + 3 * math.sin(roll) * alive
    ctx.arc(px, py, 8.5, 0, TAU)
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.arc(px - 3, py - 3, 2.5, 0, TAU)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    if blink > 0:
        ctx.save()
        ctx.arc(ex, ey, 17, 0, TAU)
        ctx.clip()
        ctx.rectangle(ex - 20, ey - 20, 40, 40 * min(1.0, blink))
        ctx.set_source_rgb(0.62, 0.38, 0.2)
        ctx.fill()
        ctx.restore()
        ctx.arc(ex, ey, 17, 0, TAU)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(3)
        ctx.stroke()
    ctx.restore()
    q = ease_out(span(t, FACE + 0.08, FACE + 0.25))            # the legs, in crayon
    if q > 0:
        s = HAND_SCALE
        for lx in (-30, 30):
            x0, y0 = lx * s, PALM[3] * s + 2
            crayon_line(ctx, [(x0, y0), (x0 + 4, y0 + 46 * q)], (1.0, 0.62, 0.1), 7, 3)
            for toe in (-0.6, 0.0, 0.6):
                crayon_line(ctx, [(x0 + 4, y0 + 46 * q), (x0 + 4 + 18 * math.sin(toe) * q, y0 + (46 + 16 * math.cos(toe)) * q)],
                            (1.0, 0.62, 0.1), 6, 4)


def bubble(ctx, t):
    """GOBBLE! in a scribbled speech bubble by its beak."""
    p = back_out(span(t, GOBBLE[0], GOBBLE[0] + 0.2), 2.6) * (1 - ease_in(span(t, LOGO[0] - 0.05, LOGO[0] + 0.15)))
    if p <= 0:
        return
    hx, hy = HAND_AT
    dx, dy, _, _ = life(t)
    x, y = head_at()
    bx, by = hx + dx + x - 150, hy + dy + y - 120
    ctx.save()
    ctx.translate(bx, by)
    ctx.scale(p, p)
    ctx.rotate(-0.08)
    ctx.save()
    ctx.scale(1.0, 0.62)
    ctx.arc(0, 0, 120, 0, TAU)
    ctx.restore()
    ctx.move_to(40, 60)
    ctx.line_to(110, 120)
    ctx.line_to(70, 50)
    ctx.set_source_rgb(1, 1, 1)
    ctx.fill()
    pts = [(math.cos(a) * 120 + 3 * math.sin(a * 13), math.sin(a) * 74 + 3 * math.cos(a * 11))
           for a in [k * TAU / 60 for k in range(61)]]
    crayon_line(ctx, pts, (0.15, 0.15, 0.2), 5, 2)
    crayon_line(ctx, [(44, 58), (110, 120), (72, 52)], (0.15, 0.15, 0.2), 5, 3)
    shake = 3 * math.sin(t * 40) * (t < GOBBLE[1])
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(52)
    x = -ctx.text_extents('GOBBLE!').x_advance / 2
    for i, ch in enumerate('GOBBLE!'):
        ctx.save()
        ctx.translate(x + shake, 18 + 4 * math.sin(i * 2.1) + shake * (-1) ** i)
        ctx.rotate(0.08 * math.sin(i * 1.7))
        ctx.move_to(0, 0)
        ctx.text_path(ch)
        ctx.set_source_rgb(*FEATHER_COLOURS[i % 4] if ch != '!' else (0.15, 0.15, 0.2))
        ctx.fill()
        ctx.restore()
        x += ctx.text_extents(ch).x_advance + 1
    ctx.restore()


# ---------------------------------------------------------------- the closed logo

@lru_cache(maxsize=1)
def letter_runs():
    """VIZELVISION's letters as flattened outlines, centred across the top of the paper."""
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_RGB24, 8, 8))
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(96)
    word = 'VIZELVISION'
    total = sum(ctx.text_extents(ch).x_advance + 8 for ch in word) - 8
    x = W / 2 - total / 2
    letters = []
    rand = random.Random(4)
    for i, ch in enumerate(word):
        ctx.new_path()
        ctx.save()
        tilt = rand.uniform(-0.1, 0.1)
        adv = ctx.text_extents(ch).x_advance
        ctx.translate(x + adv / 2, 150 + rand.uniform(-8, 8))
        ctx.rotate(tilt)
        ctx.move_to(-adv / 2, 0)
        ctx.text_path(ch)
        ctx.restore()
        runs, run = [], []
        for kind, pts in ctx.copy_path_flat():
            if kind == cairo.PATH_MOVE_TO:
                if run:
                    runs.append(run)
                run = [pts]
            elif kind == cairo.PATH_LINE_TO:
                run.append(pts)
            elif kind == cairo.PATH_CLOSE_PATH and run:
                run.append(run[0])
                runs.append(run)
                run = []
        if run:
            runs.append(run)
        letters.append(runs)
        x += adv + 8
    return letters


def wordmark(ctx, t):
    if t < LOGO[0] - 0.05:
        return
    step = (LOGO[3] - LOGO[0]) / 10
    for i, runs in enumerate(letter_runs()):
        p = span(t, LOGO[0] + i * step - 0.03, LOGO[0] + i * step + 0.12)
        if p <= 0:
            continue
        colour = LETTER_COLOURS[i]
        ctx.save()
        ctx.new_path()
        for run in runs:
            path(ctx, run, close=True)
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.clip()
        xs = [x for run in runs for x, _ in run]
        ys = [y for run in runs for _, y in run]
        rand = random.Random(i)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        rows = int((max(ys) - min(ys)) / 7) + 2
        for r in range(int(rows * p)):
            y = max(ys) - r * 7
            ctx.move_to(min(xs) - 6, y + rand.uniform(-2, 2))
            ctx.line_to(max(xs) + 6, y - 10 + rand.uniform(-2, 2))
        ctx.set_source_rgba(*colour, 0.85)
        ctx.set_line_width(8)
        ctx.stroke()
        ctx.restore()
        for k, run in enumerate(runs):                         # the outline, pressed hard
            n = max(2, int(len(run) * p))
            crayon_line(ctx, run[:n], mix(colour, INK, 0.3), 4, i + k)


def happy(ctx, t):
    """HAPPY THANKSGIVIИG, in a five-year-old's hand: the last N on backwards."""
    q = span(t, LOGO[3] - 0.05, LOGO[3] + 0.45)
    if q <= 0:
        return
    text = 'HAPPY THANKSGIVING'
    ctx.select_font_face('Quicksand', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(36)
    widths = [ctx.text_extents(ch).x_advance + 6 for ch in text]
    x = W / 2 - sum(widths) / 2
    shown = int(len(text) * q + 0.999)
    rand = random.Random(21)
    for i, (ch, wd) in enumerate(zip(text, widths)):
        jy, ja, js = rand.uniform(-5, 5), rand.uniform(-0.12, 0.12), rand.uniform(0.9, 1.15)
        if i >= shown or ch == ' ':
            x += wd
            continue
        ctx.save()
        ctx.translate(x + wd / 2, 216 + jy)
        ctx.rotate(ja)
        ctx.scale(-js if i == len(text) - 2 else js, js)     # the backwards N
        ctx.move_to(-wd / 2 + 3, 0)
        ctx.text_path(ch)
        ctx.set_source_rgb(0.18, 0.3, 0.7)
        ctx.fill()
        ctx.restore()
        x += wd


def sticker(ctx, t):
    """A gold star sticker, slapped down on the last note."""
    p = span(t, STICKER - 0.12, STICKER)
    if p <= 0:
        return
    s = 1 + 1.8 * (1 - ease_in(p, 2))
    x, y = 1035, 470
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(0.2)
    ctx.scale(s, s)
    ctx.save()
    ctx.translate(6 / s, 8 / s)
    star_shape(ctx, 84)
    ctx.set_source_rgba(0, 0, 0, 0.25 * p)
    ctx.fill()
    ctx.restore()
    star_shape(ctx, 84)
    g = cairo.LinearGradient(-60, -60, 60, 60)
    g.add_color_stop_rgb(0, 1.0, 0.95, 0.55)
    g.add_color_stop_rgb(0.5, 1.0, 0.78, 0.15)
    g.add_color_stop_rgb(1, 0.85, 0.55, 0.05)
    inked(ctx, g, 3, (0, 0))
    font(ctx, 'Nimbus Sans', 19)
    ctx.new_path()
    text_path(ctx, 'GREAT', 0, -2, align='center')
    text_path(ctx, 'JOB!', 0, 20, align='center')
    ctx.set_source_rgb(0.55, 0.3, 0.02)
    ctx.fill()
    ctx.restore()
    shine = span(t, STICKER + 0.05, STICKER + 0.5)
    if 0 < shine < 1:
        A.glint(ctx, x + 40, y - 40, 26 * math.sin(shine * math.pi), 2)


def star_shape(ctx, r):
    ctx.new_path()
    for k in range(10):
        a = -math.pi / 2 + k * math.pi / 5
        rr = r if k % 2 == 0 else r * 0.48
        ctx.line_to(math.cos(a) * rr, math.sin(a) * rr)
    ctx.close_path()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    ctx.set_source_surface(table_surface(), 0, 0)
    ctx.paint()
    turkey(ctx, t)
    hand(ctx, t)
    held_crayon(ctx, t)
    bubble(ctx, t)
    wordmark(ctx, t)
    happy(ctx, t)
    sticker(ctx, t)
    vignette(ctx, 0.4)
    grain(ctx, frame, 0.5)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        iris(ctx, HAND_AT[0], HAND_AT[1] - 60, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        dx, dy, _, _ = life(t)
        x, y = head_at()
        cx, cy = HAND_AT[0] + dx + x - 4, HAND_AT[1] + dy + y - 14
        iris(ctx, cx, cy, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 110 * (1 - closing) / .3)
