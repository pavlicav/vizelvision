"""What the Orange Cat Behavior idents share (the cat itself is only_on.py's): the nature
documentary's caption, the station banner that wipes in on the closed logo, the teal TV
set with its screen left to each promo, and an ottoman.
"""
import math

import cairo

import only_on as O
from common import (INK, PINK, TAU, TEAL, W, WHITE, YELLOW, back_out, ease_in_out, ease_out, font, glint, inked,
                    inked_stroke, rounded_rect, span, text_path)

SERIES = 'ORANGE CAT BEHAVIOR'


def caption(ctx, t, number, title, start, end):
    """The documentary's caption, bottom left: the series in spaced caps over a hairline,
    the episode in italics. It fades and drifts in at start, and out at end."""
    p = ease_out(span(t, start, start + 0.5)) * (1 - ease_in_out(span(t, end, end + 0.4)))
    if p <= 0:
        return
    x, y = 64 - 16 * (1 - p), 610
    ctx.save()
    ctx.push_group()
    scrim = cairo.RadialGradient(180, 650, 20, 180, 650, 420)       # a soft shade behind the words
    scrim.add_color_stop_rgba(0, 0, 0, 0, 0.5)
    scrim.add_color_stop_rgba(1, 0, 0, 0, 0)
    ctx.save()
    ctx.translate(0, 650)
    ctx.scale(1, 0.4)
    ctx.translate(0, -650)
    ctx.set_source(scrim)
    ctx.paint()
    ctx.restore()
    for dx, dy, colour in ((2, 2, (0, 0, 0)), (0, 0, WHITE)):
        ctx.set_source_rgba(*colour, 0.55 if colour == (0, 0, 0) else 1.0)
        font(ctx, 'Nimbus Sans', 26)
        ctx.new_path()
        text_path(ctx, SERIES, x + dx, y + dy, tracking=5)
        ctx.fill()
        ctx.rectangle(x + dx, y + 14 + dy, 220 * ease_out(span(t, start + 0.15, start + 0.7)), 2)
        ctx.fill()
        ctx.select_font_face('C059', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(27)
        ctx.new_path()
        text_path(ctx, f'No. {number}: {title}', x + dx, y + 50 + dy)
        ctx.fill()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(p)
    ctx.restore()


def banner(ctx, t, text, start, cx=470, cy=690):
    """A pink slab that wipes in from the left, its letters springing up one by one
    (only_on's ONLY ON VIZELVISION), with glints."""
    p = span(t, start, start + 0.35)
    if p <= 0:
        return
    font(ctx, 'Nimbus Sans', 34, italic=True)
    widths = [ctx.text_extents(ch).x_advance + 6 for ch in text]
    width = sum(widths) - 6
    h = 48
    x0, x1 = cx - width / 2 - 30, cx + width / 2 + 30
    ctx.save()
    ctx.rectangle(0, 0, x0 + (x1 - x0 + 30) * ease_out(p), 720)
    ctx.clip()
    ctx.move_to(x0 + 14, cy - h / 2)
    ctx.line_to(x1 + 14, cy - h / 2)
    ctx.line_to(x1 - 14, cy + h / 2)
    ctx.line_to(x0 - 14, cy + h / 2)
    ctx.close_path()
    inked(ctx, PINK, 5, (6, 6))
    ctx.restore()
    x = cx - width / 2
    for i, (ch, wd) in enumerate(zip(text, widths)):
        q = span(t, start + 0.12 + i * 0.025, start + 0.26 + i * 0.025)
        if q > 0:
            ctx.save()
            ctx.translate(x, cy + 12)
            ctx.scale(1, back_out(q))
            ctx.move_to(0, 0)
            ctx.text_path(ch)
            ctx.set_source_rgb(*WHITE)
            ctx.fill()
            ctx.restore()
        x += wd
    for i in range(6):
        life = span(t, start + 0.2 + i * 0.12, start + 0.6 + i * 0.12)
        if 0 < life < 1:
            glint(ctx, x0 + 40 + i * (x1 - x0 - 80) / 5, cy - 34 + 14 * (i % 2), 18 * math.sin(life * math.pi), i)


def tv_set(ctx, t, screen, wobble=0.0, cabinet=O.CABINET):
    """only_on's teal set on its stand; screen(ctx, t, x, y, w, h) fills the picture tube,
    clipped to it, and the glass's frame and reflection go over it."""
    x, y, w, h = cabinet
    ctx.rectangle(x - 35, y + h, w + 70, 16)
    inked(ctx, O.WOOD, 5, (6, 6))
    for lx in (x - 20, x + w + 2):
        ctx.rectangle(lx, y + h + 16, 18, O.FLOOR - y - h - 16)
        inked(ctx, O.WOOD_DARK, 4, (4, 4))
    ctx.save()
    ctx.translate(x + w / 2, y + h)
    ctx.rotate(wobble)
    ctx.translate(-(x + w / 2), -(y + h))
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    for tip, ball in (((x + w - 120, y - 92), PINK), ((x + w - 30, y - 104), YELLOW)):
        ctx.move_to(x + w - 75, y - 4)
        ctx.line_to(*tip)
        inked_stroke(ctx, (0.85, 0.88, 0.95), 5, (4, 4))
        ctx.arc(*tip, 10, 0, TAU)
        inked(ctx, ball, 4, (4, 4))
    rounded_rect(ctx, x, y, w, h, 34)
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, 0.35, 1.0, 0.92)
    g.add_color_stop_rgb(0.35, *TEAL)
    g.add_color_stop_rgb(1, 0.0, 0.36, 0.48)
    inked(ctx, g, 7, (10, 10))
    for ky, colour in ((y + 60, YELLOW), (y + 120, PINK)):
        ctx.arc(x + w - 48, ky, 16, 0, TAU)
        inked(ctx, colour, 4, (3, 3))
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(5)
    for gy in range(y + 170, y + 250, 14):
        ctx.move_to(x + w - 66, gy)
        ctx.line_to(x + w - 30, gy)
    ctx.stroke()
    sx, sy, sw, sh = x + 25, y + 22, 270, 226
    ctx.save()
    rounded_rect(ctx, sx, sy, sw, sh, 26)
    ctx.clip()
    screen(ctx, t, sx, sy, sw, sh)
    ctx.set_source_rgba(0, 0, 0, 0.2)
    for ly in range(int(sy), int(sy + sh), 4):
        ctx.rectangle(sx, ly, sw, 1.6)
    ctx.fill()
    ctx.move_to(sx, sy + 40)
    ctx.line_to(sx, sy)
    ctx.line_to(sx + 110, sy)
    ctx.close_path()
    ctx.set_source_rgba(1, 1, 1, 0.1)
    ctx.fill()
    ctx.restore()
    rounded_rect(ctx, sx, sy, sw, sh, 26)
    ctx.set_source_rgb(*INK)
    ctx.set_line_width(10)
    ctx.stroke()
    ctx.restore()


def ottoman(ctx, cx, top, width, floor=O.FLOOR):
    """A round tufted pouf in mustard velvet, seen a little from above."""
    left, right = cx - width / 2, cx + width / 2
    ctx.move_to(left, top + 14)
    ctx.curve_to(left - 8, top + 60, left - 4, floor - 30, left + 18, floor - 4)
    ctx.line_to(right - 18, floor - 4)
    ctx.curve_to(right + 4, floor - 30, right + 8, top + 60, right, top + 14)
    ctx.close_path()
    g = cairo.LinearGradient(left, 0, right, 0)
    g.add_color_stop_rgb(0, 0.78, 0.55, 0.12)
    g.add_color_stop_rgb(0.45, 0.95, 0.72, 0.22)
    g.add_color_stop_rgb(1, 0.7, 0.48, 0.1)
    inked(ctx, g, 5, (8, 8))
    ctx.set_source_rgba(0.45, 0.28, 0.02, 0.5)       # the piping and the tufts
    ctx.set_line_width(3)
    for k in range(1, 6):
        x = left + width * k / 6
        ctx.move_to(x, top + 22)
        ctx.curve_to(x + (x - cx) * 0.05, top + 60, x + (x - cx) * 0.08, floor - 40, x + (x - cx) * 0.06, floor - 8)
    ctx.stroke()
    ctx.save()
    ctx.translate(cx, top + 12)
    ctx.scale(width / 2, 16)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    top_g = cairo.LinearGradient(0, top - 4, 0, top + 28)
    top_g.add_color_stop_rgb(0, 1.0, 0.84, 0.36)
    top_g.add_color_stop_rgb(1, 0.88, 0.64, 0.18)
    inked(ctx, top_g, 5, (0, 0))
    ctx.arc(cx, top + 12, 4, 0, TAU)
    ctx.set_source_rgba(0.45, 0.28, 0.02, 0.8)
    ctx.fill()
