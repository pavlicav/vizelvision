"""Guest of Honor: Thanksgiving dinner at dusk. A long table laid with every side dish there
is (sweet potatoes under marshmallows, the cranberry sauce still the shape of its can, green
bean casserole, rolls, mashed potatoes, a pumpkin pie), a cornucopia and four tapers down
the middle, and at the head of the table an empty chair and a place card: GUEST OF HONOR.

The four candles light on the open logo. The door opens and a wild turkey walks in, hops up
onto the chair at the head of the table and finds its plate: cranberries, corn and a little
pie. It gobbles its thanks. Four glasses rise into the frame and clink, a toast to the guest.
On the closed logo the turkey spreads its tail, the feathers lighting gold a quarter a note
from the middle out, a sunburst behind it, and VIZELVISION drops in over the table: HAPPY
THANKSGIVING. The turkey gives you a slow blink and the iris closes on it.

Helena: "Everybody's here..." / "...and here's our guest of honor!" / "Happy Thanksgiving."
"""
import math
import random
from functools import lru_cache

import cairo

import neighborhood
import turkeys
from common import (A, INK, ORANGE, PINK, TAU, TEAL, W, WHITE, YELLOW, H, back_out, clamp, ease_in, ease_in_out,  # noqa: F401
                    ease_out, font, grain, inked, inked_stroke, iris, mix, pulse, rounded_rect, span, text_path,
                    vignette)

ID = 'guest-of-honor'
NAME = 'Guest of Honor'
KIND = 'ident'
ORDER = 52
DESCRIPTION = ('Thanksgiving dinner at dusk: four candles light on the open logo, the door opens and a wild '
               'turkey walks in and takes the seat of honor at the head of the table, with its own plate of '
               'cranberries, corn and pie. It gobbles its thanks, four glasses rise in a toast, and on the '
               'closed logo it spreads its tail into a golden sunburst behind the wordmark: HAPPY THANKSGIVING.')
DURATION = 10.0
STILL_AT = 8.6
OVERLAYS = []

# Hit points (the music's too: guest_of_honor_music.py).
IRIS_OPEN = (0.0, 0.6)
CANDLES = (2.0, 2.25, 2.5, 3.0)              # the open logo: a candle a note
DOOR = (3.3, 3.75)                           # the door swings open
WALK = (3.6, 5.0)                            # in from the door, along the wall, behind the table
STEPS = 7                                    # footfalls on the walk
HOP = (5.0, 5.35)                            # up onto the chair, turning to face you
PLATE = 5.45                                 # it looks down at its plate
GOBBLE = (5.75, 6.25)
TOAST = (6.15, 6.6)                          # four glasses rise into the frame
CLINK = 6.8
LOGO = (7.2, 7.45, 7.7, 8.2)                 # the closed logo: the tail lights a quarter a note
FAN = (7.0, 7.35)                            # the tail spreads
LOCKUP = 7.2
BLINK = (8.85, 9.1)
IRIS_CLOSE = (9.25, 9.6)

FLOOR = 446
FAR, NEAR = 400, 760                         # the table's far and near edges (y)
DOOR_BOX = (96, 150, 150, FLOOR - 150)       # x, y, w, h
CHAIR = 640
SEAT = (CHAIR, 424)                          # where the turkey stands on the chair (behind the table)
TURKEY_SIDE = 0.62
TURKEY_FRONT = 0.82
WALL = (0.86, 0.66, 0.42)
STRIPE = (0.8, 0.57, 0.34)
CLOTH = (0.97, 0.93, 0.84)
RUNNER = (0.86, 0.42, 0.14)
FLAME = (1.0, 0.75, 0.3)


def table_at(u, v):
    """The table in perspective: u across (-1 left edge .. 1 right edge), v from the far end
    (0) to the near edge (1). Returns (x, y, scale)."""
    y = FAR + (NEAR - FAR) * v
    half = 170 + 720 * v
    return CHAIR + u * half, y, 0.5 + 0.8 * v


def candles_lit(t):
    return sum(1 for c in CANDLES if t >= c)


def warmth(t):
    """How much the candles light the room (0 at dusk, 1 with all four)."""
    return sum(ease_out(span(t, c - 0.02, c + 0.3)) for c in CANDLES) / 4


def flicker(t, k):
    return 0.88 + 0.06 * math.sin(t * 13.3 + k * 2.1) + 0.04 * math.sin(t * 31.7 + k) + 0.02 * math.sin(t * 51 + k * 3)


# ---------------------------------------------------------------- the room

@lru_cache(maxsize=1)
def room_surface():
    s = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(s)
    ctx.set_source_rgb(*WALL)
    ctx.paint()
    for x in range(0, W, 48):                                  # the wallpaper's stripes and a little sprig
        ctx.rectangle(x, 0, 16, FLOOR)
    ctx.set_source_rgb(*STRIPE)
    ctx.fill()
    rand = random.Random(11)
    for x in range(24, W, 48):
        for y in range(40, FLOOR - 60, 70):
            yy = y + (35 if (x // 48) % 2 else 0)
            ctx.arc(x, yy, 3.2, 0, TAU)
            ctx.set_source_rgba(0.62, 0.24, 0.12, 0.55)
            ctx.fill()
            for a in (-0.6, 0.6):
                ctx.save()
                ctx.translate(x, yy + 2)
                ctx.rotate(a + rand.uniform(-0.1, 0.1))
                ctx.scale(2.4, 6)
                ctx.arc(0, 1, 1, 0, TAU)
                ctx.restore()
                ctx.set_source_rgba(0.45, 0.5, 0.2, 0.45)
                ctx.fill()
    ctx.rectangle(0, FLOOR - 110, W, 8)                        # the chair rail and wainscot
    ctx.set_source_rgb(0.5, 0.3, 0.16)
    ctx.fill()
    ctx.rectangle(0, FLOOR - 102, W, 102)
    ctx.set_source_rgb(0.56, 0.34, 0.18)
    ctx.fill()
    for x in range(20, W, 120):
        rounded_rect(ctx, x, FLOOR - 92, 96, 76, 4)
        ctx.set_source_rgba(0, 0, 0, 0.12)
        ctx.set_line_width(3)
        ctx.stroke()
    ctx.rectangle(0, FLOOR - 14, W, 14)                        # the skirting
    ctx.set_source_rgb(0.36, 0.2, 0.1)
    ctx.fill()
    ctx.rectangle(0, FLOOR, W, H - FLOOR)                      # the floorboards
    ctx.set_source_rgb(0.42, 0.25, 0.13)
    ctx.fill()
    ctx.set_source_rgba(0.2, 0.1, 0.05, 0.6)
    ctx.set_line_width(2)
    for k in range(-20, 21):
        ctx.move_to(CHAIR + k * 22, FLOOR)
        ctx.line_to(CHAIR + k * 110, H)
    ctx.stroke()
    window(ctx)
    portrait(ctx)
    door_frame(ctx)
    return s


def window(ctx):
    """Dusk in November: an orange band under violet, bare-ish maples with a few leaves left."""
    x, y, w, h = 900, 96, 270, 230
    rounded_rect(ctx, x - 14, y - 14, w + 28, h + 28, 6)
    inked(ctx, (0.94, 0.9, 0.82), 4, (5, 5))
    ctx.save()
    ctx.rectangle(x, y, w, h)
    ctx.clip()
    g = cairo.LinearGradient(0, y, 0, y + h)
    for stop, rgb in ((0, (0.24, 0.18, 0.42)), (0.55, (0.72, 0.34, 0.42)), (0.8, (1.0, 0.6, 0.25)),
                      (1, (1.0, 0.78, 0.4))):
        g.add_color_stop_rgb(stop, *rgb)
    ctx.set_source(g)
    ctx.paint()
    rand = random.Random(4)
    for tx, th in ((x + 50, 150), (x + 190, 190), (x + 250, 120)):
        ctx.set_source_rgb(0.18, 0.1, 0.12)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.move_to(tx, y + h)
        ctx.line_to(tx + 4, y + h - th)
        ctx.set_line_width(9)
        ctx.stroke()
        for b in range(6):
            bx, by = tx + 2, y + h - th * (0.45 + 0.09 * b)
            a = rand.uniform(-2.6, -0.5)
            ctx.move_to(bx, by)
            ctx.line_to(bx + math.cos(a) * 60, by + math.sin(a) * 50)
            ctx.set_line_width(3)
            ctx.stroke()
            for _ in range(3):
                lx, ly = bx + math.cos(a) * rand.uniform(20, 60), by + math.sin(a) * rand.uniform(15, 50)
                ctx.arc(lx, ly, rand.uniform(3, 6), 0, TAU)
                ctx.set_source_rgb(*rand.choice(((0.95, 0.45, 0.1), (0.85, 0.22, 0.1), (0.98, 0.7, 0.15))))
                ctx.fill()
                ctx.set_source_rgb(0.18, 0.1, 0.12)
    ctx.restore()
    ctx.rectangle(x + w / 2 - 4, y, 8, h)
    ctx.rectangle(x, y + h / 2 - 4, w, 8)
    ctx.set_source_rgb(0.94, 0.9, 0.82)
    ctx.fill()
    ctx.rectangle(x - 26, y + h + 12, w + 52, 14)              # the sill, with a little gourd
    inked(ctx, (0.94, 0.9, 0.82), 3, (3, 3))
    ctx.save()
    ctx.translate(x + 40, y + h + 4)
    ctx.scale(1.3, 1)
    ctx.arc(0, 0, 10, 0, TAU)
    ctx.restore()
    inked(ctx, (0.95, 0.75, 0.2), 2.5, (2, 2))


def portrait(ctx):
    """A framed portrait of the station's TV, as a family's ancestor."""
    x, y, w, h = 330, 120, 150, 180
    ctx.save()
    ctx.translate(x + w / 2, y + h / 2)
    ctx.scale(1, h / w)
    ctx.arc(0, 0, w / 2 + 14, 0, TAU)
    ctx.restore()
    g = cairo.LinearGradient(0, y, 0, y + h)
    g.add_color_stop_rgb(0, 0.95, 0.78, 0.35)
    g.add_color_stop_rgb(1, 0.65, 0.45, 0.15)
    inked(ctx, g, 4, (6, 6))
    ctx.save()
    ctx.translate(x + w / 2, y + h / 2)
    ctx.scale(1, h / w)
    ctx.arc(0, 0, w / 2, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.2, 0.28, 0.24)
    ctx.fill()
    ctx.save()
    ctx.translate(x + w / 2, y + h / 2 + 6)
    ctx.scale(0.36, 0.36)
    A.draw_tv(ctx, 0.0, 1, 0.0)
    ctx.restore()


def door_frame(ctx):
    x, y, w, h = DOOR_BOX
    ctx.rectangle(x - 16, y - 16, w + 32, h + 16)
    inked(ctx, (0.94, 0.9, 0.82), 4, (5, 5))
    ctx.rectangle(x, y, w, h)
    g = cairo.LinearGradient(x, 0, x + w, 0)                   # the lit hall beyond
    g.add_color_stop_rgb(0, 1.0, 0.86, 0.6)
    g.add_color_stop_rgb(1, 0.95, 0.72, 0.42)
    ctx.set_source(g)
    ctx.fill()
    ctx.rectangle(x, y + h - 60, w, 60)                        # the hall's runner
    ctx.set_source_rgb(0.7, 0.25, 0.18)
    ctx.fill()


def door(ctx, t):
    """The door, hinged on the right, swinging in towards the hall."""
    x, y, w, h = DOOR_BOX
    p = ease_out(span(t, *DOOR), 2)
    width = w * math.cos(p * 1.25)
    if width < 2:
        return
    x0 = x + w - width
    ctx.move_to(x + w, y)
    ctx.line_to(x0, y - 10 * p)
    ctx.line_to(x0, y + h + 6 * p)
    ctx.line_to(x + w, y + h)
    ctx.close_path()
    g = cairo.LinearGradient(x0, 0, x + w, 0)
    g.add_color_stop_rgb(0, 0.55, 0.32, 0.16)
    g.add_color_stop_rgb(1, 0.46, 0.26, 0.13)
    inked(ctx, g, 4, (3, 3))
    for k in range(2):                                         # its panels
        py = y + 24 + k * 130
        ctx.move_to(x + w - 16 * (width / w), py)
        ctx.line_to(x0 + 16 * (width / w), py - 4 * p)
        ctx.line_to(x0 + 16 * (width / w), py + 100 - 2 * p)
        ctx.line_to(x + w - 16 * (width / w), py + 100)
        ctx.close_path()
        ctx.set_source_rgba(0, 0, 0, 0.16)
        ctx.set_line_width(3)
        ctx.stroke()
    ctx.arc(x0 + 18 * (width / w), y + h * 0.55, 6, 0, TAU)  # the knob
    inked(ctx, (0.95, 0.78, 0.3), 2, (2, 2))


def hall_light(ctx, t):
    """The hall's light spilling across the floor once the door is open."""
    p = ease_out(span(t, *DOOR))
    if p <= 0:
        return
    x, y, w, h = DOOR_BOX
    ctx.move_to(x, FLOOR)
    ctx.line_to(x + w, FLOOR)
    ctx.line_to(x + w + 260, H)
    ctx.line_to(x - 120, H)
    ctx.close_path()
    g = cairo.LinearGradient(0, FLOOR, 0, H)
    g.add_color_stop_rgba(0, 1.0, 0.85, 0.55, 0.32 * p)
    g.add_color_stop_rgba(1, 1.0, 0.85, 0.55, 0)
    ctx.set_source(g)
    ctx.fill()


def chair(ctx):
    """The head chair's tall back, behind the far end of the table."""
    x = CHAIR
    ctx.move_to(x - 86, FAR + 10)
    ctx.line_to(x - 80, 196)
    ctx.curve_to(x - 70, 150, x - 30, 136, x, 140)
    ctx.curve_to(x + 30, 136, x + 70, 150, x + 80, 196)
    ctx.line_to(x + 86, FAR + 10)
    ctx.close_path()
    g = cairo.LinearGradient(x - 86, 0, x + 86, 0)
    g.add_color_stop_rgb(0, 0.42, 0.22, 0.1)
    g.add_color_stop_rgb(0.5, 0.6, 0.34, 0.16)
    g.add_color_stop_rgb(1, 0.4, 0.2, 0.09)
    inked(ctx, g, 5, (6, 6))
    ctx.move_to(x - 56, FAR)                                   # its upholstered panel
    ctx.line_to(x - 54, 200)
    ctx.curve_to(x - 44, 172, x - 20, 166, x, 168)
    ctx.curve_to(x + 20, 166, x + 44, 172, x + 54, 200)
    ctx.line_to(x + 56, FAR)
    ctx.close_path()
    inked(ctx, (0.62, 0.16, 0.14), 3, (0, 0))
    for k in range(3):
        for j in range(-1, 2):
            ctx.arc(x + j * 30, 214 + k * 56, 3, 0, TAU)
            ctx.set_source_rgb(0.95, 0.78, 0.3)
            ctx.fill()


# ---------------------------------------------------------------- the table

def dish(ctx, x, y, s, rx=70, ry=24, colour=WHITE):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s * rx, s * ry)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, colour, 3, (4, 4))


def sweet_potatoes(ctx, x, y, s):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    rounded_rect(ctx, -70, -20, 140, 50, 12)                   # the dish
    inked(ctx, (0.9, 0.9, 0.95), 3, (4, 4))
    ctx.save()
    ctx.translate(0, -16)
    ctx.scale(66, 18)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, (0.95, 0.5, 0.15), 3, (0, 0))
    rand = random.Random(5)
    for _ in range(14):                                        # the marshmallows, toasted
        mx, my = rand.uniform(-54, 54), rand.uniform(-28, -6)
        rounded_rect(ctx, mx - 8, my - 6, 16, 12, 5)
        g = cairo.LinearGradient(0, my - 6, 0, my + 6)
        g.add_color_stop_rgb(0, 0.8, 0.5, 0.25)
        g.add_color_stop_rgb(1, 1.0, 0.97, 0.9)
        inked(ctx, g, 1.8, (0, 0))
    ctx.restore()


def cranberry(ctx, x, y, s):
    """The cranberry sauce, still exactly the shape of its can, ridges and all."""
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    dish(ctx, 0, 14, 1, 70, 22, (0.95, 0.95, 0.98))
    rounded_rect(ctx, -46, -36, 92, 50, 18)
    g = cairo.LinearGradient(-46, 0, 46, 0)
    g.add_color_stop_rgb(0, 0.55, 0.04, 0.12)
    g.add_color_stop_rgb(0.35, 0.86, 0.14, 0.24)
    g.add_color_stop_rgb(1, 0.5, 0.03, 0.1)
    inked(ctx, g, 3, (3, 3))
    for k in range(1, 5):                                      # the ridges
        ctx.move_to(-46 + k * 18.4, -34)
        ctx.line_to(-46 + k * 18.4, 12)
    ctx.set_source_rgba(0.35, 0.0, 0.06, 0.6)
    ctx.set_line_width(2)
    ctx.stroke()
    ctx.save()
    ctx.translate(-46, -11)
    ctx.scale(9, 25)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.95, 0.3, 0.38)
    ctx.fill()
    ctx.restore()


def green_beans(ctx, x, y, s):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.save()
    ctx.scale(80, 32)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, (0.92, 0.9, 0.86), 3, (4, 4))
    ctx.save()
    ctx.translate(0, -4)
    ctx.scale(70, 24)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    ctx.set_source_rgb(0.42, 0.55, 0.22)
    ctx.fill()
    rand = random.Random(8)
    for _ in range(16):                                        # the crispy onions
        ox, oy = rand.uniform(-56, 56), rand.uniform(-20, 8)
        ctx.move_to(ox - 8, oy)
        ctx.curve_to(ox - 4, oy - 6, ox + 4, oy - 6, ox + 8, oy)
        ctx.set_source_rgb(0.85, 0.6, 0.25)
        ctx.set_line_width(4)
        ctx.stroke()
    ctx.restore()


def rolls(ctx, x, y, s):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.move_to(-66, -10)
    ctx.line_to(66, -10)
    ctx.line_to(52, 26)
    ctx.line_to(-52, 26)
    ctx.close_path()
    inked(ctx, (0.78, 0.55, 0.28), 3, (4, 4))
    ctx.set_source_rgba(0.45, 0.28, 0.12, 0.6)
    for k in range(-60, 61, 12):
        ctx.move_to(k, -10)
        ctx.line_to(k * 0.8, 26)
    ctx.set_line_width(2)
    ctx.stroke()
    for rx, ry in ((-36, -20), (0, -26), (36, -20), (-18, -36), (18, -36)):
        ctx.save()
        ctx.translate(rx, ry)
        ctx.scale(24, 17)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        g = cairo.RadialGradient(rx - 6, ry - 8, 2, rx, ry, 26)
        g.add_color_stop_rgb(0, 0.98, 0.8, 0.5)
        g.add_color_stop_rgb(1, 0.75, 0.45, 0.18)
        inked(ctx, g, 2.5, (2, 2))
    ctx.restore()


def mashed(ctx, x, y, s):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    dish(ctx, 0, 6, 1, 64, 24, (0.35, 0.5, 0.7))
    ctx.move_to(-50, 0)
    ctx.curve_to(-46, -40, -10, -52, 0, -48)
    ctx.curve_to(14, -56, 48, -40, 50, 0)
    ctx.close_path()
    inked(ctx, (0.99, 0.96, 0.88), 3, (0, 0))
    ctx.move_to(-14, -42)                                      # the pat of butter, melting
    ctx.line_to(12, -46)
    ctx.line_to(16, -34)
    ctx.line_to(-10, -30)
    ctx.close_path()
    inked(ctx, (1.0, 0.88, 0.35), 2, (0, 0))
    ctx.restore()


def pie(ctx, x, y, s, slice_only=False):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    if slice_only:
        ctx.move_to(-28, 6)
        ctx.line_to(28, 6)
        ctx.line_to(4, -26)
        ctx.close_path()
        inked(ctx, (0.85, 0.48, 0.16), 2.5, (2, 2))
        ctx.move_to(-28, 6)
        ctx.line_to(28, 6)
        ctx.line_to(28, 12)
        ctx.line_to(-28, 12)
        ctx.close_path()
        inked(ctx, (0.92, 0.72, 0.42), 2.5, (2, 2))
        ctx.arc(2, -6, 7, 0, TAU)
        inked(ctx, WHITE, 1.8, (0, 0))
        ctx.restore()
        return
    ctx.save()
    ctx.scale(80, 30)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    inked(ctx, (0.92, 0.72, 0.42), 3, (4, 4))
    ctx.save()
    ctx.translate(0, -3)
    ctx.scale(68, 24)
    ctx.arc(0, 0, 1, 0, TAU)
    ctx.restore()
    g = cairo.RadialGradient(-10, -10, 4, 0, -3, 70)
    g.add_color_stop_rgb(0, 0.95, 0.6, 0.22)
    g.add_color_stop_rgb(1, 0.78, 0.38, 0.1)
    inked(ctx, g, 2, (0, 0))
    for k in range(10):                                        # the crimped edge
        a = k * TAU / 10
        ctx.arc(76 * math.cos(a), 28 * math.sin(a) - 1, 5, 0, TAU)
        ctx.set_source_rgb(0.85, 0.62, 0.32)
        ctx.fill()
    for wx, wy in ((-20, -8), (20, -4), (0, 8)):                # whipped cream
        ctx.arc(wx, wy, 9, 0, TAU)
        inked(ctx, WHITE, 1.8, (0, 0))
    ctx.restore()


def cornucopia(ctx, x, y, s):
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    ctx.move_to(70, -40)                                       # the horn
    ctx.curve_to(40, -64, -60, -40, -110, -10)
    ctx.curve_to(-130, 4, -120, 14, -100, 4)
    ctx.curve_to(-60, -10, 20, 0, 66, 18)
    ctx.close_path()
    g = cairo.LinearGradient(-120, 0, 70, 0)
    g.add_color_stop_rgb(0, 0.55, 0.36, 0.16)
    g.add_color_stop_rgb(1, 0.85, 0.62, 0.32)
    inked(ctx, g, 3.5, (4, 4))
    ctx.set_source_rgba(0.4, 0.25, 0.1, 0.6)
    ctx.set_line_width(2)
    for k in range(6):
        px = -90 + k * 30
        ctx.move_to(px, -30 + 4 * k)
        ctx.line_to(px + 12, 10 + k)
    ctx.stroke()
    for gx, gy, rx, ry, colour in ((86, -14, 30, 26, (1.0, 0.55, 0.12)), (128, 4, 22, 18, (0.95, 0.85, 0.3)),
                                   (66, 14, 18, 14, (0.45, 0.6, 0.25)), (108, 20, 20, 13, (0.62, 0.18, 0.2)),
                                   (150, 18, 16, 14, (0.98, 0.7, 0.2))):
        ctx.save()
        ctx.translate(gx, gy)
        ctx.scale(rx, ry)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        inked(ctx, colour, 3, (3, 3))
    for k in range(3):                                         # grapes
        for j in range(3 - k):
            ctx.arc(40 + j * 12 + k * 6, 26 + k * 10, 7, 0, TAU)
            inked(ctx, (0.45, 0.2, 0.5), 2, (0, 0))
    ctx.restore()


CANDLE_U = (-0.36, -0.12, 0.12, 0.36)
CANDLE_V = 0.46


def candle_points():
    return [table_at(u, CANDLE_V) for u in CANDLE_U]


@lru_cache(maxsize=1)
def table_surface():
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    # the cloth, hanging a little at the far end
    l0, _, _ = table_at(-1, 0)
    r0, _, _ = table_at(1, 0)
    l1, _, _ = table_at(-1, 1)
    r1, _, _ = table_at(1, 1)
    ctx.move_to(l0 - 6, FAR + 26)
    ctx.line_to(l0, FAR)
    ctx.line_to(r0, FAR)
    ctx.line_to(r0 + 6, FAR + 26)
    ctx.line_to(r1 + 60, NEAR)
    ctx.line_to(l1 - 60, NEAR)
    ctx.close_path()
    inked(ctx, (0.88, 0.82, 0.72), 4, (0, 0))
    ctx.move_to(l0, FAR)
    ctx.line_to(r0, FAR)
    ctx.line_to(r1, NEAR)
    ctx.line_to(l1, NEAR)
    ctx.close_path()
    g = cairo.LinearGradient(0, FAR, 0, NEAR)
    g.add_color_stop_rgb(0, *mix(CLOTH, (0.8, 0.7, 0.55), 0.3))
    g.add_color_stop_rgb(1, *CLOTH)
    inked(ctx, g, 4, (0, 0))
    a0, _, _ = table_at(-0.26, 0)                              # the runner down the middle
    b0, _, _ = table_at(0.26, 0)
    a1, _, _ = table_at(-0.26, 1)
    b1, _, _ = table_at(0.26, 1)
    ctx.move_to(a0, FAR)
    ctx.line_to(b0, FAR)
    ctx.line_to(b1, NEAR)
    ctx.line_to(a1, NEAR)
    ctx.close_path()
    ctx.set_source_rgb(*RUNNER)
    ctx.fill()
    ctx.set_source_rgba(1.0, 0.85, 0.4, 0.8)
    ctx.set_line_width(3)
    for u in (-0.22, 0.22):
        x0, _, _ = table_at(u, 0)
        x1, _, _ = table_at(u, 1)
        ctx.move_to(x0, FAR)
        ctx.line_to(x1, NEAR)
    ctx.stroke()
    # the guest's place: plate, cranberries, corn and a slice of pie; the place card
    x, y, s = table_at(0, 0.07)
    ctx.save()
    ctx.translate(x, y)
    ctx.scale(s, s)
    dish(ctx, 0, 0, 1, 88, 28, (0.97, 0.97, 1.0))
    dish(ctx, 0, 0, 1, 66, 20, (0.92, 0.85, 0.65))
    rand = random.Random(2)
    for _ in range(18):                                        # cranberries
        cx, cy = rand.uniform(-50, -12), rand.uniform(-14, 6)
        ctx.arc(cx, cy, 6, 0, TAU)
        inked(ctx, (0.8, 0.08, 0.18), 1.5, (0, 0))
    for _ in range(26):                                        # corn kernels
        cx, cy = rand.uniform(8, 34), rand.uniform(-12, 8)
        ctx.arc(cx, cy, 4, 0, TAU)
        inked(ctx, (1.0, 0.85, 0.25), 1.2, (0, 0))
    ctx.restore()
    pie(ctx, x + 46 * s, y - 2, s * 0.9, slice_only=True)
    cx, cy, cs = table_at(0, 0.2)                              # the place card
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(cs, cs)
    ctx.move_to(-92, 10)
    ctx.line_to(-86, -30)
    ctx.line_to(86, -30)
    ctx.line_to(92, 10)
    ctx.close_path()
    inked(ctx, (1.0, 0.98, 0.92), 3, (4, 4))
    ctx.select_font_face('C059', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(22)
    ctx.new_path()
    text_path(ctx, 'Guest of Honor', 0, -3, align='center')
    ctx.set_source_rgb(0.6, 0.2, 0.1)
    ctx.fill()
    ctx.move_to(-60, 3)
    ctx.line_to(60, 3)
    ctx.set_source_rgba(0.85, 0.6, 0.2, 0.9)
    ctx.set_line_width(2)
    ctx.stroke()
    ctx.restore()
    # the sides
    for u, v, make in ((-0.58, 0.3, sweet_potatoes), (0.6, 0.27, cranberry), (-0.62, 0.58, rolls),
                       (0.62, 0.56, mashed), (-0.55, 0.8, green_beans), (0.52, 0.8, pie)):
        x, y, s = table_at(u, v)
        make(ctx, x, y, s)
    # the centrepiece, and the four candlesticks
    x, y, s = table_at(0, 0.7)
    cornucopia(ctx, x - 20, y, s * 0.85)
    for x, y, s in candle_points():
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(s, s)
        ctx.save()
        ctx.scale(22, 8)
        ctx.arc(0, 0, 1, 0, TAU)
        ctx.restore()
        inked(ctx, (0.95, 0.75, 0.3), 2.5, (3, 3))
        ctx.move_to(-6, 0)
        ctx.line_to(-8, -22)
        ctx.line_to(8, -22)
        ctx.line_to(6, 0)
        ctx.close_path()
        inked(ctx, (0.95, 0.75, 0.3), 2.5, (0, 0))
        rounded_rect(ctx, -7, -110, 14, 90, 4)                 # the taper
        g = cairo.LinearGradient(-7, 0, 7, 0)
        g.add_color_stop_rgb(0, 0.85, 0.82, 0.74)
        g.add_color_stop_rgb(0.4, 1.0, 0.98, 0.92)
        g.add_color_stop_rgb(1, 0.82, 0.78, 0.7)
        inked(ctx, g, 2.5, (3, 3))
        ctx.move_to(0, -110)
        ctx.line_to(0, -118)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(2)
        ctx.stroke()
        ctx.restore()
    return surface


def flames(ctx, t):
    for k, ((x, y, s), lit) in enumerate(zip(candle_points(), CANDLES)):
        p = span(t, lit - 0.02, lit + 0.12)
        if p <= 0:
            continue
        f = flicker(t, k)
        burst = 1 + 0.6 * pulse(t, lit, 0.35)
        fx, fy = x, y - 118 * s
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        g = cairo.RadialGradient(fx, fy - 10, 2, fx, fy - 10, 110 * f * burst * s)
        g.add_color_stop_rgba(0, 1.0, 0.75, 0.35, 0.45 * p)
        g.add_color_stop_rgba(1, 1.0, 0.55, 0.2, 0)
        ctx.set_source(g)
        ctx.paint()
        ctx.restore()
        ctx.save()
        ctx.translate(fx, fy)
        ctx.scale(s * p * burst, s * p * burst * f)
        ctx.rotate(0.06 * math.sin(t * 7 + k))
        ctx.move_to(0, 0)
        ctx.curve_to(-9, -6, -7, -22, 0, -34)
        ctx.curve_to(7, -22, 9, -6, 0, 0)
        ctx.close_path()
        g = cairo.LinearGradient(0, 0, 0, -34)
        g.add_color_stop_rgb(0, 1.0, 0.98, 0.85)
        g.add_color_stop_rgb(0.5, *FLAME)
        g.add_color_stop_rgb(1, 1.0, 0.45, 0.1)
        ctx.set_source(g)
        ctx.fill()
        ctx.restore()


def dusk(ctx, t):
    """The room before the candles: dim and blue. It warms a candle at a time."""
    k = warmth(t)
    ctx.set_source_rgba(0.1, 0.08, 0.22, 0.42 * (1 - k))
    ctx.paint()
    if k > 0:
        x, y, _ = table_at(0, CANDLE_V)
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_ADD)
        g = cairo.RadialGradient(x, y - 60, 20, x, y - 60, 620)
        g.add_color_stop_rgba(0, 1.0, 0.65, 0.25, 0.22 * k)
        g.add_color_stop_rgba(1, 1.0, 0.5, 0.2, 0)
        ctx.set_source(g)
        ctx.paint()
        ctx.restore()


# ---------------------------------------------------------------- the guest

def turkey(ctx, t):
    if t < WALK[0]:
        return
    x0 = DOOR_BOX[0] + DOOR_BOX[2] / 2
    x1 = CHAIR - 130
    if t < HOP[0]:
        p = span(t, *WALK)
        x = x0 + (x1 - x0) * ease_in_out(p) if p < 1 else x1
        step = STEPS * p
        bob = 4 * math.sin(step * TAU)
        turkeys.side(ctx, t, x, FLOOR + 4, TURKEY_SIDE, 1, step=step, bob=bob)
        return
    p = span(t, *HOP)
    if p < 1:                                                  # the hop: an arc up onto the seat, turning
        x = x1 + (CHAIR - x1) * ease_in_out(p)
        y = FLOOR + 4 + (SEAT[1] - FLOOR - 4) * p - 120 * math.sin(math.pi * p)
        if p < 0.5:
            turkeys.side(ctx, t, x, y, TURKEY_SIDE, 1, fan=0.0)
        else:
            turkeys.front(ctx, t, x, y, TURKEY_SIDE + (TURKEY_FRONT - TURKEY_SIDE) * p, fan=0.0, wings=0.0)
        return
    land = pulse(t, HOP[1], 0.25)
    look_down = ease_in_out(span(t, PLATE, PLATE + 0.25)) * (1 - ease_in_out(span(t, GOBBLE[0] - 0.1, GOBBLE[0] + 0.1)))
    gob = math.sin(math.pi * span(t, *GOBBLE)) if GOBBLE[0] <= t <= GOBBLE[1] else 0.0
    fan = ease_out(span(t, *FAN), 2)
    glows = fan_glows(t)
    blink = math.sin(math.pi * span(t, *BLINK))
    turkeys.front(ctx, t, CHAIR, SEAT[1] + 10 * land, TURKEY_FRONT, fan=fan, gobble=gob, blink=blink,
                  bob=26 * look_down + 6 * land - 6 * math.sin(t * 2.2) * (t > GOBBLE[1]), glows=glows,
                  wings=fan, tilt=0.15 * math.sin(math.pi * span(t, GOBBLE[1], GOBBLE[1] + 0.6)))


def fan_glows(t):
    """The tail lights gold a quarter a note, from the middle feathers out."""
    order = sorted(range(15), key=lambda i: abs(i - 7))
    groups = (order[:3], order[3:7], order[7:11], order[11:])
    glows = [0.0] * 15
    for when, group in zip(LOGO, groups):
        g = ease_out(span(t, when - 0.02, when + 0.2))
        for i in group:
            glows[i] = g * (0.85 + 0.15 * math.sin(t * 5 + i))
    return glows


def sunburst(ctx, t):
    """Gold rays behind the spread tail, turning slowly, on the closed logo."""
    p = ease_out(span(t, LOGO[0] - 0.1, LOGO[3]))
    if p <= 0:
        return
    cx, cy = CHAIR, SEAT[1] - 120 * TURKEY_FRONT
    ctx.save()
    ctx.translate(cx, cy)
    ctx.rotate(0.12 * t)
    ctx.set_operator(cairo.OPERATOR_ADD)
    for k in range(24):
        a = k * TAU / 24
        ctx.move_to(0, 0)
        ctx.arc(0, 0, 900, a - 0.05, a + 0.05)
        ctx.close_path()
    g = cairo.RadialGradient(0, 0, 40, 0, 0, 700)
    g.add_color_stop_rgba(0, 1.0, 0.8, 0.35, 0.35 * p)
    g.add_color_stop_rgba(1, 1.0, 0.6, 0.2, 0)
    ctx.set_source(g)
    ctx.fill()
    g = cairo.RadialGradient(0, 0, 10, 0, 0, 360)
    g.add_color_stop_rgba(0, 1.0, 0.85, 0.45, 0.45 * p)
    g.add_color_stop_rgba(1, 1.0, 0.6, 0.2, 0)
    ctx.set_source(g)
    ctx.paint()
    ctx.restore()


# ---------------------------------------------------------------- the toast

SLEEVES = ((0.85, 0.62, 0.18), (0.25, 0.32, 0.55), (0.62, 0.16, 0.2), (0.3, 0.45, 0.32))
SKIN = ((0.96, 0.78, 0.62), (0.55, 0.36, 0.24), (0.82, 0.6, 0.44), (0.4, 0.26, 0.18))
HANDS = (((-60, 760), (200, 540)), ((-80, 820), (330, 610)), ((1340, 760), (1080, 540)), ((1360, 820), (950, 610)))


def toast(ctx, t):
    p = ease_out(span(t, *TOAST))
    if p <= 0:
        return
    clink = pulse(t, CLINK, 0.3)
    for k, ((sx, sy), (hx, hy)) in enumerate(HANDS):
        side = -1 if sx < W / 2 else 1
        q = ease_out(span(t, TOAST[0] + 0.06 * k, TOAST[1] + 0.06 * k))
        x = sx + (hx - sx) * q - side * 26 * clink
        y = sy + (hy - sy) * q - 30 * clink
        ctx.move_to(sx, sy + 40)                               # the arm, in its sleeve
        ctx.line_to(x, y + 20)
        inked_stroke(ctx, SLEEVES[k], 54, (5, 5))
        ctx.save()                                             # the hand
        ctx.translate(x, y)
        ctx.rotate(side * 0.18)
        rounded_rect(ctx, -22, -14, 44, 40, 14)
        inked(ctx, SKIN[k], 3.5, (3, 3))
        ctx.move_to(-4, -20)                                   # the glass: cider in a stemmed glass
        ctx.line_to(-2, 28)
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(5)
        ctx.stroke()
        ctx.move_to(-2, -18)
        ctx.curve_to(-30, -24, -34, -70, -30, -96)
        ctx.line_to(26, -96)
        ctx.curve_to(30, -70, 26, -24, -2, -18)
        ctx.close_path()
        g = cairo.LinearGradient(-30, 0, 26, 0)
        g.add_color_stop_rgba(0, 0.9, 0.95, 1.0, 0.35)
        g.add_color_stop_rgba(1, 0.8, 0.9, 1.0, 0.2)
        ctx.set_source(g)
        ctx.fill_preserve()
        ctx.set_source_rgb(*INK)
        ctx.set_line_width(3)
        ctx.stroke()
        ctx.move_to(-31, -64)
        ctx.curve_to(-30, -30, 26, -30, 27, -64)
        ctx.close_path()
        ctx.set_source_rgba(0.95, 0.6, 0.15, 0.9)
        ctx.fill()
        ctx.move_to(-22, -88)
        ctx.line_to(-22, -50)
        ctx.set_source_rgba(1, 1, 1, 0.6)
        ctx.set_line_width(4)
        ctx.stroke()
        for f in range(4):                                     # fingers round the stem
            rounded_rect(ctx, -24, -12 + f * 9, 30, 10, 5)
            inked(ctx, SKIN[k], 2, (0, 0))
        ctx.save()                                             # the thumb
        ctx.translate(14 * -side, -10)
        ctx.rotate(-side * 0.6)
        rounded_rect(ctx, -6, -16, 12, 26, 6)
        ctx.restore()
        inked(ctx, SKIN[k], 2, (0, 0))
        ctx.restore()
    if 0 < clink:                                              # the clink's sparkle
        for k in range(2):
            gx, gy = (300, 470) if k == 0 else (980, 470)
            A.glint(ctx, gx, gy - 30 * clink, 26 * clink, k)


# ---------------------------------------------------------------- the frame

def lockup(ctx, t):
    p = ease_out(span(t, LOCKUP - 0.1, LOCKUP + 0.3))
    if p <= 0:
        return
    g = cairo.LinearGradient(0, 520, 0, H)
    g.add_color_stop_rgba(0, 0.12, 0.04, 0.02, 0)
    g.add_color_stop_rgba(0.45, 0.12, 0.04, 0.02, 0.7 * p)
    g.add_color_stop_rgba(1, 0.12, 0.04, 0.02, 0.85 * p)
    ctx.rectangle(0, 520, W, H - 520)
    ctx.set_source(g)
    ctx.fill()
    neighborhood.lockup(ctx, t, LOCKUP, 646, scale=0.6, tint=0.8)
    q = ease_out(span(t, LOGO[3], LOGO[3] + 0.4))
    if q > 0:
        font(ctx, 'Nimbus Sans', 24)
        ctx.new_path()
        text_path(ctx, 'HAPPY THANKSGIVING', W / 2, 692, tracking=10, align='center')
        ctx.set_source_rgba(1.0, 0.82, 0.4, q)
        ctx.fill()


def camera(t):
    return 1 + 0.12 * ease_in_out(span(t, HOP[1], IRIS_CLOSE[0]))


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= IRIS_CLOSE[1]:
        return
    ctx.save()
    z = camera(t)
    ctx.translate(CHAIR, 300)
    ctx.scale(z, z)
    ctx.translate(-CHAIR, -300)
    ctx.set_source_surface(room_surface(), 0, 0)
    ctx.paint()
    hall_light(ctx, t)
    door(ctx, t)
    sunburst(ctx, t)
    chair(ctx)
    turkey(ctx, t)
    ctx.set_source_surface(table_surface(), 0, 0)
    ctx.paint()
    dusk(ctx, t)
    flames(ctx, t)
    ctx.restore()
    toast(ctx, t)
    lockup(ctx, t)
    vignette(ctx, 0.5)
    grain(ctx, frame, 0.5)
    opening = span(t, *IRIS_OPEN)
    if opening < 1:
        x, y, _ = table_at(0, CANDLE_V)
        iris(ctx, x, y - 80, 900 * ease_in(opening, 2))
    closing = span(t, *IRIS_CLOSE)
    if closing > 0:
        z = camera(t)
        hy = 300 + (SEAT[1] - 226 * TURKEY_FRONT - 300) * z
        iris(ctx, CHAIR, hy, 900 * (1 - ease_in(closing, 2)) if closing < .7 else 110 * (1 - closing) / .3)
