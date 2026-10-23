"""What the arena idents (basketball.py, hockey.py) share: the stands, full, rising away from
the camera, and seven-segment digits for the clocks."""
import random

import cairo

from common import TAU, W, mix

SHIRTS = ((0.85, 0.18, 0.45), (0.95, 0.95, 0.95), (0.1, 0.55, 0.6), (0.2, 0.2, 0.3), (0.95, 0.75, 0.2),
          (0.55, 0.15, 0.6), (0.3, 0.45, 0.85), (0.8, 0.3, 0.2))
SKINS = ((0.95, 0.78, 0.62), (0.78, 0.56, 0.4), (0.55, 0.36, 0.24), (0.36, 0.23, 0.15))


def stands(ctx, project, scale, front_z, front_y, rows=24, skip=(), seed=19, shirts=SHIRTS):
    """Rows of fans from the back row forward: each row 0.85 m further and 0.42 m higher than
    the one before, from front_z and front_y; the rows in skip left bare (a fascia goes there).
    project(x, y, z) gives screen (x, y); scale(z) pixels per metre."""
    rand = random.Random(seed)
    for row in range(rows - 1, -1, -1):
        z, y = front_z + 0.85 * row, front_y + 0.42 * row
        k = scale(z)
        top = project(0, y + 0.9, z)[1]
        base = project(0, y, z)[1]
        light = 1 - 0.55 * row / (rows - 1)
        ctx.rectangle(0, top, W, base - top + 2)       # the riser
        ctx.set_source_rgb(*mix((0.18, 0.12, 0.2), (0, 0, 0), 1 - light))
        ctx.fill()
        if row in skip:
            continue
        x = -W / 2 / k - 1 + rand.uniform(0, 0.5)
        while x < W / 2 / k + 1:
            if rand.random() < 0.93:
                sx, sy = project(x, y + 0.75, z)
                ctx.move_to(sx - 0.22 * k, sy + 0.1 * k)
                ctx.curve_to(sx - 0.2 * k, sy - 0.12 * k, sx + 0.2 * k, sy - 0.12 * k, sx + 0.22 * k, sy + 0.1 * k)
                ctx.line_to(sx + 0.22 * k, sy + 0.5 * k)
                ctx.line_to(sx - 0.22 * k, sy + 0.5 * k)
                ctx.close_path()
                ctx.set_source_rgb(*mix(rand.choice(shirts), (0, 0, 0), 0.25 + 0.5 * (1 - light)))
                ctx.fill()
                ctx.arc(sx, sy - 0.24 * k, 0.11 * k, 0, TAU)
                ctx.set_source_rgb(*mix(rand.choice(SKINS), (0, 0, 0), 0.2 + 0.5 * (1 - light)))
                ctx.fill()
            x += 0.55 + rand.uniform(-0.05, 0.05)


def rafters(ctx, xs=(130, 400, 880, 1150)):
    """The light rig's glare along the top."""
    for x in xs:
        halo = cairo.RadialGradient(x, 18, 0, x, 18, 120)
        halo.add_color_stop_rgba(0, 1, 0.97, 0.9, 0.55)
        halo.add_color_stop_rgba(1, 1, 0.97, 0.9, 0)
        ctx.set_source(halo)
        ctx.paint()


def seven_segment(ctx, text, x, y, h, colour, dim=0.12):
    """Digits, points and colons in seven segments, top-left at (x, y), h tall; unlit
    segments faint."""
    w, th = h * 0.5, h * 0.12
    segs = {'a': (0, 0, 1, 0), 'b': (1, 0, 1, 0.5), 'c': (1, 0.5, 1, 1), 'd': (0, 1, 1, 1),
            'e': (0, 0.5, 0, 1), 'f': (0, 0, 0, 0.5), 'g': (0, 0.5, 1, 0.5)}
    digits = {'0': 'abcdef', '1': 'bc', '2': 'abged', '3': 'abgcd', '4': 'fgbc', '5': 'afgcd', '6': 'afgedc',
              '7': 'abc', '8': 'abcdefg', '9': 'abcfgd'}
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_width(th)
    for ch in text:
        if ch in '.:':
            for dot_y in ((y + h,) if ch == '.' else (y + h * 0.3, y + h * 0.75)):
                ctx.arc(x + th * 0.3, dot_y, th * 0.7, 0, TAU)
                ctx.set_source_rgb(*colour)
                ctx.fill()
            x += th * 2.2
            continue
        on = digits.get(ch, '')
        for name, (ax, ay, bx, by) in segs.items():
            ctx.move_to(x + ax * w, y + ay * h)
            ctx.line_to(x + bx * w, y + by * h)
            ctx.set_source_rgba(*colour, 1.0 if name in on else dim)
            ctx.stroke()
        x += w + th * 2.2
