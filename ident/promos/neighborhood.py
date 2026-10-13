"""What the neighbourhood idents share: the place tag (a map pin and the neighbourhood's
name, top left) and the lockup (the ID's wordmark, smaller, dropping in a letter a
sixteenth on the closed logo).
"""
import cairo

from common import (A, CYAN, INK, ORANGE, PINK, TEAL, WHITE, YELLOW, chrome, ease_in_out, ease_out, font, inked, mix,
                    rounded_rect, span, text_path)

COLOURS = (PINK, TEAL, YELLOW, CYAN, ORANGE)


def tag(ctx, t, name, area, start, end):
    """The place, on a white card that slides in from the left at start and out at end."""
    p = ease_out(span(t, start, start + 0.45)) * (1 - ease_in_out(span(t, end, end + 0.4)))
    if p <= 0:
        return
    font(ctx, 'Nimbus Sans', 36)
    width = ctx.text_extents(name).x_advance
    font(ctx, 'Nimbus Sans', 15)
    width = max(width, ctx.text_extents(area).x_advance + 2.5 * len(area)) + 112
    x, y, h = 44 - (width + 80) * (1 - p), 44, 82
    ctx.save()
    rounded_rect(ctx, x, y, width, h, 16)
    inked(ctx, WHITE, 5, (7, 7))
    # The pin.
    px, py = x + 44, y + 36
    ctx.move_to(px, py + 30)
    ctx.curve_to(px - 6, py + 14, px - 20, py + 8, px - 20, py - 4)
    ctx.arc(px, py - 4, 20, 3.1416, 0)
    ctx.curve_to(px + 20, py + 8, px + 6, py + 14, px, py + 30)
    ctx.close_path()
    inked(ctx, PINK, 4, (3, 3))
    ctx.arc(px, py - 4, 7, 0, 6.2832)
    ctx.set_source_rgb(*WHITE)
    ctx.fill()
    ctx.set_source_rgb(*INK)
    font(ctx, 'Nimbus Sans', 36)
    text_path(ctx, name, x + 80, y + 44)
    ctx.fill()
    ctx.set_source_rgb(*mix(INK, WHITE, 0.45))
    font(ctx, 'Nimbus Sans', 15)
    text_path(ctx, area, x + 81, y + 68, tracking=2.5)
    ctx.fill()
    ctx.restore()


def lockup(ctx, t, start, y, scale=0.62, step=0.0625, tint=1.0):
    """VIZELVISION in the ID's faces, centred, baseline at y: a letter every step from start,
    each easing down into place."""
    size, layout = A.wordmark_layout()
    base = A.BASELINE
    top = base - size * 0.74
    ctx.save()
    ctx.translate(A.W / 2, y)
    ctx.scale(scale, scale)
    ctx.translate(-A.W / 2, -base)
    font(ctx, 'URW Gothic', size)
    for i, letter in enumerate(layout):
        p = span(t, start + i * step, start + i * step + 0.3)
        if p <= 0:
            continue
        ctx.save()
        ctx.translate(0, -50 * (1 - ease_out(p)))
        ctx.move_to(letter['x'], base)
        ctx.text_path(letter['ch'])
        if letter['part'] == 0:
            colour = COLOURS[i % 5]
            face = cairo.LinearGradient(0, top, 0, base)
            face.add_color_stop_rgb(0, *mix(colour, WHITE, 0.45))
            face.add_color_stop_rgb(0.5, *colour)
            face.add_color_stop_rgb(1, *mix(colour, INK, 0.25))
        else:
            face = chrome(top, base, tint)
        ctx.push_group()
        inked(ctx, face, 5, (8, 8), fatten=7)
        ctx.pop_group_to_source()
        ctx.paint_with_alpha(ease_out(min(1.0, p * 1.6)))
        ctx.restore()
    ctx.restore()
