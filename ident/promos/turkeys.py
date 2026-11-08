"""The wild turkey the Thanksgiving idents share (cat-leaf-pile, guest-of-honor), in the ID's
inked look: from the side (walking, gobbling, its tail folded or fanned) and from the front
(strutting, its tail spread behind it like a sunburst). A handsome bird, drawn with respect:
bronze and copper, a green sheen, a barred wing, a blue face and a red snood.

Both take the ground point between the feet; s scales the bird (about 230 px tall at 1).
"""
import math

import cairo

from common import INK, TAU, WHITE, clamp, inked, inked_stroke, mix

BRONZE = (0.45, 0.28, 0.15)
BRONZE_DARK = (0.22, 0.13, 0.08)
SHEEN = (0.24, 0.5, 0.36)
COPPER = (0.84, 0.5, 0.22)
CHESTNUT = (0.62, 0.34, 0.14)
BUFF = (0.97, 0.86, 0.62)
FACE = (0.62, 0.8, 0.98)
RED = (0.9, 0.14, 0.18)
BEAK = (0.95, 0.82, 0.52)
LEG = (0.9, 0.52, 0.5)
BAR = (0.96, 0.93, 0.86)


def feather(ctx, length, width, glow=0.0):
    """One tail feather from the origin, pointing up (-y): bronze, a dark band, a buff tip.
    glow (0..1) lights it gold."""
    ctx.move_to(-width * 0.3, 0)
    ctx.curve_to(-width * 0.55, -length * 0.4, -width * 0.6, -length * 0.85, 0, -length)
    ctx.curve_to(width * 0.6, -length * 0.85, width * 0.55, -length * 0.4, width * 0.3, 0)
    ctx.close_path()
    g = cairo.LinearGradient(0, 0, 0, -length)
    for stop, rgb in ((0, BRONZE_DARK), (0.5, BRONZE), (0.7, COPPER), (0.76, BRONZE_DARK), (0.84, BRONZE_DARK),
                      (0.87, CHESTNUT), (1, BUFF)):
        g.add_color_stop_rgb(stop, *mix(rgb, (1.0, 0.85, 0.35), 0.55 * glow))
    inked(ctx, g, 3.5, (4, 4))
    ctx.move_to(0, -length * 0.05)                    # the shaft
    ctx.line_to(0, -length * 0.92)
    ctx.set_source_rgba(*BUFF, 0.35)
    ctx.set_line_width(1.6)
    ctx.stroke()


def tail_fan(ctx, cx, cy, radius, spread, glows=None, count=15, squeeze=1.0, lean=0.0):
    """The fanned tail: count feathers radiating from (cx, cy) across spread radians of the
    upper half, centred on straight up (plus lean), squeezed horizontally for a side view."""
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(squeeze, 1)
    order = sorted(range(count), key=lambda i: -abs(i - (count - 1) / 2))   # outer ones first, middle on top
    for i in order:
        a = lean + (i / (count - 1) - 0.5) * spread
        ctx.save()
        ctx.rotate(a)
        feather(ctx, radius * (0.93 + 0.07 * math.cos(a - lean)), radius * 0.26,
                glows[i] if glows else 0.0)
        ctx.restore()
    ctx.restore()


def breast(cx, cy, r):
    """The body's sheen: copper going to green-bronze and dark at the edges."""
    g = cairo.RadialGradient(cx - r * 0.25, cy - r * 0.35, r * 0.1, cx, cy, r * 1.15)
    g.add_color_stop_rgb(0, *mix(COPPER, BUFF, 0.15))
    g.add_color_stop_rgb(0.45, *BRONZE)
    g.add_color_stop_rgb(0.75, *mix(BRONZE, SHEEN, 0.55))
    g.add_color_stop_rgb(1, *BRONZE_DARK)
    return g


def scales(ctx, cx, cy, rx, ry, rows=4, alpha=0.45):
    """Rows of little feather-scallops across the body, each edged in black."""
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(rx, ry)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.save()
    ctx.clip()
    ctx.set_line_width(2.2)
    for r in range(rows):
        y = cy - ry * 0.55 + r * ry * 0.38
        for k in range(-6, 7):
            x = cx + k * 20 + (10 if r % 2 else 0)
            ctx.new_sub_path()
            ctx.arc(x, y, 10, 0.15 * math.pi, 0.85 * math.pi)
        ctx.set_source_rgba(*INK, alpha)
        ctx.stroke()
    ctx.restore()


def leg(ctx, hip, foot, lift=0.0, facing=1):
    hx, hy = hip
    fx, fy = foot
    fy -= lift
    ctx.move_to(hx, hy)
    ctx.line_to(fx, fy)
    inked_stroke(ctx, LEG, 7, (3, 3))
    for a in (-0.9, 0.0, 0.9):                        # three toes forward, one back
        ctx.move_to(fx, fy)
        ctx.line_to(fx + facing * 20 * math.cos(a * 0.6), fy + 4 * math.sin(a) + 2)
    ctx.move_to(fx, fy)
    ctx.line_to(fx - facing * 10, fy + 2)
    inked_stroke(ctx, LEG, 4, (2, 2))


def eye(ctx, x, y, r, blink=0.0):
    if blink >= 0.95:
        ctx.move_to(x - r, y)
        ctx.line_to(x + r, y)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(2.4)
        ctx.stroke()
        return
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(1, max(0.08, 1 - blink))
    ctx.arc(0, 0, r, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(*INK)
    ctx.fill()
    ctx.arc(x - r * 0.3, y - r * 0.35 * (1 - blink), r * 0.38, 0, TAU)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()


def head(ctx, t, hx, hy, facing=1, gobble=0.0, blink=0.0, wobble=0.0, front=False, size=1.3):
    """The head at (hx, hy): blue face, beak, the red snood draped over it and the wattle
    under the chin. gobble (0..1) opens the beak, flushes the face red and shakes the snood."""
    ctx.save()
    ctx.translate(hx, hy)
    ctx.scale(size, size)
    _head(ctx, t, 0, 0, facing, gobble, blink, wobble, front)
    ctx.restore()


def _head(ctx, t, hx, hy, facing, gobble, blink, wobble, front):
    shake = math.sin(t * 38) * 5 * gobble + wobble
    face = mix(FACE, (0.95, 0.55, 0.65), 0.5 * gobble)
    if front:
        ctx.save()                                    # the wattle, under the chin
        ctx.translate(hx, hy + 14)
        ctx.move_to(-10, 0)
        ctx.curve_to(-14, 22 + 6 * gobble, 14, 22 + 6 * gobble, 10, 0)
        ctx.close_path()
        inked(ctx, RED, 3, (3, 3))
        ctx.restore()
        ctx.arc(hx, hy, 19, 0, TAU)
        inked(ctx, face, 3.5, (4, 4))
        for side in (-1, 1):                          # red caruncles at the cheeks
            ctx.arc(hx + side * 13, hy + 8, 5, 0, TAU)
            ctx.set_source_rgb(*RED)
            ctx.fill()
        open_ = 5 * gobble
        ctx.move_to(hx - 6, hy + 2)                   # the beak, end on
        ctx.line_to(hx + 6, hy + 2)
        ctx.line_to(hx, hy + 14 + open_)
        ctx.close_path()
        inked(ctx, BEAK, 2.5, (2, 2))
        for side in (-1, 1):
            eye(ctx, hx + side * 9, hy - 5, 3.6, blink)
        ctx.move_to(hx - 2, hy - 2)                   # the snood, from the brow, over the beak to one side
        ctx.curve_to(hx - 4, hy + 6, hx + 8 + shake, hy + 14, hx + 6 + shake, hy + 28 + 6 * gobble)
        inked_stroke(ctx, RED, 5, (2, 2))
        return
    f = facing
    ctx.move_to(hx + f * 4, hy + 10)                  # the wattle
    ctx.curve_to(hx + f * 2 + shake * 0.3, hy + 34 + 6 * gobble, hx - f * 14 + shake * 0.3, hy + 30, hx - f * 8, hy + 8)
    ctx.close_path()
    inked(ctx, RED, 3, (3, 3))
    ctx.save()
    ctx.translate(hx, hy)
    ctx.scale(1.15, 1)
    ctx.arc(0, 0, 17, 0, TAU)
    ctx.restore()
    inked(ctx, face, 3.5, (4, 4))
    open_ = 0.35 * gobble
    for sign in (-1, 1):                              # the beak, upper and lower
        ctx.save()
        ctx.translate(hx + f * 16, hy + 3)
        ctx.scale(f, 1)
        ctx.rotate(sign * open_)
        ctx.move_to(0, -4 * (sign < 0))
        ctx.line_to(16, 0)
        ctx.line_to(0, 5 * (sign > 0) - 1)
        ctx.close_path()
        ctx.restore()
        inked(ctx, BEAK, 2.5, (2, 2))
    eye(ctx, hx + f * 5, hy - 4, 3.8, blink)
    ctx.move_to(hx + f * 14, hy - 6)                  # the snood, draped over the beak
    ctx.curve_to(hx + f * 22, hy - 8, hx + f * (26 + shake * 0.4), hy + 4, hx + f * (22 + shake), hy + 22 + 8 * gobble)
    inked_stroke(ctx, RED, 5, (2, 2))


def side(ctx, t, x, y, s=1.0, facing=1, step=None, fan=0.0, gobble=0.0, blink=0.0, bob=0.0, peck=0.0, glows=None):
    """From the side, facing right (facing 1) or left (-1). step: the walk's phase in steps
    (None stands); fan (0..1) raises and spreads the tail; peck (0..1) dips the head."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s * facing, s)
    walking = step is not None
    phase = (step or 0.0) * math.pi
    lift_a = 14 * max(0.0, math.sin(phase)) if walking else 0.0
    lift_b = 14 * max(0.0, -math.sin(phase)) if walking else 0.0
    stride = 22 * math.cos(phase) if walking else 0.0
    sway = 3 * abs(math.sin(phase)) if walking else 0.0
    leg(ctx, (-6, -78), (-8 - stride, 0), lift_b)     # the far leg
    ctx.translate(0, -sway)
    # the tail: folded back and down, or raised and spread
    if fan < 0.02:
        tail_fan(ctx, -50, -112, 92, 0.5, count=7, squeeze=1.0, lean=-1.95)
    else:
        tail_fan(ctx, -40 + 8 * fan, -122, 92 + 70 * fan, 0.5 + 2.5 * fan, glows, count=15,
                 squeeze=1 - 0.55 * fan, lean=-1.95 * (1 - fan))
    ctx.save()                                        # the body
    ctx.translate(4, -118)
    ctx.rotate(-0.18)
    ctx.scale(74, 54)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, breast(16, -128, 74), 5, (6, 6))
    scales(ctx, 8, -116, 72, 52)
    ctx.move_to(56, -130)                             # the beard
    ctx.curve_to(64, -110, 60, -96, 62 + 3 * math.sin(t * 4), -84)
    ctx.set_source_rgb(*BRONZE_DARK)
    ctx.set_line_width(7)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    ctx.save()                                        # the wing, barred black and white
    ctx.translate(-12, -112)
    ctx.rotate(-0.12)
    ctx.move_to(-56, 4)
    ctx.curve_to(-40, -34, 34, -36, 46, -8)
    ctx.curve_to(30, 26, -30, 30, -56, 4)
    ctx.close_path()
    g = cairo.LinearGradient(0, -30, 0, 26)
    g.add_color_stop_rgb(0, *mix(BRONZE, COPPER, 0.5))
    g.add_color_stop_rgb(1, *BRONZE_DARK)
    inked(ctx, g, 4, (3, 3))
    ctx.move_to(-56, 4)
    ctx.curve_to(-40, -34, 34, -36, 46, -8)
    ctx.curve_to(30, 26, -30, 30, -56, 4)
    ctx.clip()
    for k in range(7):
        bx = -50 + k * 12
        ctx.move_to(bx, -30)
        ctx.line_to(bx - 6, 30)
    ctx.set_source_rgba(*BAR, 0.75)
    ctx.set_line_width(4)
    ctx.stroke()
    ctx.restore()
    leg(ctx, (14, -76), (12 + stride, 0 + sway), lift_a)   # the near leg
    # the neck and head
    dip = clamp(peck)
    hx = 80 + 22 * dip + 4 * math.sin(phase * 2) * walking
    hy = -214 + bob + 124 * dip - 6 * gobble
    ctx.move_to(46, -146)
    ctx.curve_to(66, -160, hx - 26, hy + 44, hx - 6, hy + 8)
    inked_stroke(ctx, mix(FACE, (0.85, 0.6, 0.7), 0.35), 13, (3, 3))
    for k in range(2, 4):                                # caruncles down the neck
        px = 48 + (hx - 52) * k / 4
        py = -152 + (hy + 28 + 152) * k / 4
        ctx.arc(px + 5, py, 4.5 - 0.6 * k, 0, TAU)
        ctx.set_source_rgb(*RED)
        ctx.fill()
    head(ctx, t, hx, hy, 1, gobble, blink)
    ctx.restore()


def front(ctx, t, x, y, s=1.0, fan=1.0, gobble=0.0, blink=0.0, bob=0.0, glows=None, wings=1.0, tilt=0.0):
    """From the front, strutting: the tail spread behind (fan 0..1), the wings drooped (wings
    0..1), the body puffed. glows lights each tail feather gold (15 values, left to right)."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    tail_fan(ctx, 0, -120, 120 + 85 * fan, 0.6 + 2.55 * fan, glows, count=15)
    for side_ in (-1, 1):                             # the legs
        leg(ctx, (side_ * 18, -60), (side_ * 22, 0), 0, side_)
    for side_ in (-1, 1):                             # the wings, drooped to the ground in the strut
        ctx.save()
        ctx.scale(side_, 1)
        ctx.translate(54, -110)
        ctx.rotate(0.15 + 0.3 * wings)
        ctx.move_to(-6, -40)
        ctx.curve_to(30, -40, 36, 30, 22, 70 * (0.75 + 0.25 * wings))
        ctx.curve_to(6, 60, -14, 30, -10, -20)
        ctx.close_path()
        g = cairo.LinearGradient(0, -40, 0, 70)
        g.add_color_stop_rgb(0, *mix(BRONZE, COPPER, 0.4))
        g.add_color_stop_rgb(1, *BRONZE_DARK)
        inked(ctx, g, 4, (4, 4))
        for k in range(4):
            ctx.move_to(-2 + k * 7, -10 + k * 4)
            ctx.line_to(4 + k * 7, 48 + k * 4)
        ctx.set_source_rgba(*BAR, 0.65)
        ctx.set_line_width(3.5)
        ctx.stroke()
        ctx.restore()
    ctx.save()                                        # the body, puffed
    ctx.translate(0, -112)
    ctx.scale(70, 72)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, breast(0, -122, 74), 5, (6, 6))
    scales(ctx, 0, -106, 68, 68, rows=5)
    ctx.move_to(0, -150)                              # the beard
    ctx.curve_to(4, -128, -4, -110, 2 * math.sin(t * 3), -92)
    ctx.set_source_rgb(*BRONZE_DARK)
    ctx.set_line_width(9)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.stroke()
    hx, hy = 6 * math.sin(tilt), -226 + bob - 8 * gobble
    ctx.move_to(0, -168)                              # the neck
    ctx.curve_to(0, -186, hx, hy + 26, hx, hy + 10)
    inked_stroke(ctx, mix(FACE, (0.85, 0.6, 0.7), 0.35), 16, (3, 3))
    for k, side_ in ((2, -1), (3, 1)):
        ctx.arc(hx * (k / 4) + side_ * 6, -176 + (hy + 30 + 176) * k / 4, 5, 0, TAU)
        ctx.set_source_rgb(*RED)
        ctx.fill()
    ctx.save()
    ctx.translate(hx, hy)
    ctx.rotate(tilt)
    head(ctx, t, 0, 0, 1, gobble, blink, front=True)
    ctx.restore()
    ctx.restore()
