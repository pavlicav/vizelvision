"""VizelVision '96: the station on the World Wide Web. A beige monitor on a desk against
nineties confetti wallpaper. On its teal desktop a dial-up box dials, verifies, and
connects at 28,800 bps; the browser opens on www.vizelvision.com, and on the four notes
of the open logo the home page loads a piece at a time, top to bottom: the starfield and
its yellow headline, a spinning chrome V, the hit counter, UNDER CONSTRUCTION. A marquee
crawls, links sit underlined in blue, and the cursor wanders to ENTER and clicks: on the
closed logo the wordmark arches across the screen in rainbow letters, one a sixteenth,
with CHANNEL 19 and NEW! bursts blinking.

Apollo: "Vizzle Vision..." / "now on the World Wide Web!"
"""
import math
import random
from functools import lru_cache

import cairo

from common import (TAU, W, H, back_out, clamp, ease_in, ease_in_out, ease_out, grain, mix, pixel_text, pulse,  # noqa: F401
                    rounded_rect, span, text_path, vignette)

ID = 'ninety-six'
NAME = "VizelVision '96"
KIND = 'ident'
ORDER = 14
DESCRIPTION = ('1996: a beige monitor dials up at 28,800 bps and www.vizelvision.com loads on the logo: a '
               'starfield, a spinning V, a hit counter, UNDER CONSTRUCTION, a marquee; ENTER, and the wordmark '
               'arches in rainbow letters. A modem handshake into a breakbeat. Apollo.')
DURATION = 10.0
STILL_AT = 8.3
OVERLAYS = []

# Hit points (the music's too: promos/music.py).
DIALING = 0.15                                 # the modem dials...
VERIFYING = 0.85                               # ...shrieks through the handshake...
CONNECTED = 1.6                                # ...and connects
BROWSER = 1.8                                  # the browser opens
LOADS = (2.0, 2.25, 2.5, 3.0)                  # the open logo: the page loads, a piece each
CURSOR = (5.9, 6.75)                           # the pointer wanders over to ENTER
CLICK = 6.85
WORDART = 7.0                                  # the closed logo: the wordmark, a letter a sixteenth
NEW_BURSTS = (7.25, 7.5, 8.0)
FADE = (9.25, 9.6)

SCREEN = (238, 62, 804, 510)                   # the picture tube: x, y, w, h
PAGE_TOP = 174                                 # the page under the browser's bars
PAGE_BOTTOM = 548                              # and above its status bar
GREY = (0.75, 0.75, 0.75)
TEAL = (0.0, 0.5, 0.5)
LINK = (0.1, 0.25, 1.0)
VISITED = (0.55, 0.2, 0.7)


# ---------------------------------------------------------------- the room and the monitor

@lru_cache(maxsize=None)
def wallpaper():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.1, 0.07, 0.22)
    ctx.paint()
    rand = random.Random(96)
    colours = ((0.0, 0.75, 0.7), (0.65, 0.25, 0.85), (1.0, 0.5, 0.2), (0.2, 0.5, 1.0))
    for _ in range(90):                                  # the confetti: squiggles, triangles, dots
        x, y = rand.uniform(0, W), rand.uniform(0, H)
        ctx.set_source_rgba(*rand.choice(colours), 0.55)
        kind = rand.random()
        if kind < 0.4:
            ctx.move_to(x, y)
            for k in range(1, 6):
                ctx.line_to(x + 8 * k, y + (7 if k % 2 else -7))
            ctx.set_line_width(4)
            ctx.stroke()
        elif kind < 0.7:
            a = rand.uniform(0, TAU)
            ctx.move_to(x + 14 * math.cos(a), y + 14 * math.sin(a))
            ctx.line_to(x + 14 * math.cos(a + 2.1), y + 14 * math.sin(a + 2.1))
            ctx.line_to(x + 14 * math.cos(a + 4.2), y + 14 * math.sin(a + 4.2))
            ctx.close_path()
            ctx.fill()
        else:
            ctx.arc(x, y, rand.uniform(3, 7), 0, TAU)
            ctx.fill()
    g = cairo.LinearGradient(0, 610, 0, H)              # the desk
    g.add_color_stop_rgb(0, 0.62, 0.48, 0.32)
    g.add_color_stop_rgb(1, 0.42, 0.3, 0.18)
    ctx.set_source(g)
    ctx.rectangle(0, 610, W, H - 610)
    ctx.fill()
    return surface


def monitor(ctx):
    """The beige box: a thick bezel, a badge, the power light, its foot; the keyboard."""
    beige = (0.86, 0.83, 0.73)
    ctx.rectangle(560, 600, 160, 34)                    # the foot
    ctx.set_source_rgb(*mix(beige, (0, 0, 0), 0.25))
    ctx.fill()
    rounded_rect(ctx, 190, 22, 900, 600, 26)
    g = cairo.LinearGradient(0, 22, 0, 622)
    g.add_color_stop_rgb(0, *mix(beige, (1, 1, 1), 0.25))
    g.add_color_stop_rgb(1, *mix(beige, (0, 0, 0), 0.18))
    ctx.set_source(g)
    ctx.fill()
    x, y, w, h = SCREEN
    rounded_rect(ctx, x - 14, y - 12, w + 28, h + 24, 22)  # the recess round the tube
    ctx.set_source_rgb(*mix(beige, (0, 0, 0), 0.35))
    ctx.fill()
    ctx.select_font_face('Nimbus Sans', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(18)
    ctx.new_path()
    text_path(ctx, 'VV  VIZELVISION', 640, 600, tracking=3, align='center')
    ctx.set_source_rgb(*mix(beige, (0, 0, 0), 0.5))
    ctx.fill()
    ctx.arc(1040, 596, 5, 0, TAU)                       # the power light
    ctx.set_source_rgb(0.2, 0.95, 0.3)
    ctx.fill()
    rounded_rect(ctx, 240, 640, 800, 120, 14)           # the keyboard, in front
    ctx.set_source_rgb(*mix(beige, (1, 1, 1), 0.1))
    ctx.fill()
    for row in range(3):
        for col in range(19):
            rounded_rect(ctx, 262 + col * 40, 652 + row * 24, 34, 20, 4)
    ctx.set_source_rgb(*mix(beige, (0, 0, 0), 0.12))
    ctx.fill()


def glass(ctx):
    """The tube's curve: darker corners, a soft highlight, scanlines."""
    x, y, w, h = SCREEN
    g = cairo.RadialGradient(x + w / 2, y + h / 2, h * 0.4, x + w / 2, y + h / 2, w * 0.66)
    g.add_color_stop_rgba(0, 0, 0, 0, 0)
    g.add_color_stop_rgba(1, 0, 0, 0, 0.45)
    ctx.set_source(g)
    ctx.paint()
    ctx.set_source_rgba(0, 0, 0, 0.16)
    for ly in range(int(y), int(y + h), 3):
        ctx.rectangle(x, ly, w, 1)
    ctx.fill()
    g = cairo.LinearGradient(x, y, x + w * 0.5, y + h * 0.5)
    g.add_color_stop_rgba(0, 1, 1, 1, 0.14)
    g.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(g)
    ctx.paint()


# ---------------------------------------------------------------- the desktop and the dialer

def bevel(ctx, x, y, w, h, pressed=False, face=GREY):
    ctx.rectangle(x, y, w, h)
    ctx.set_source_rgb(*face)
    ctx.fill()
    light, dark = ((1, 1, 1), (0.35, 0.35, 0.35)) if not pressed else ((0.35, 0.35, 0.35), (1, 1, 1))
    ctx.set_line_width(2)
    ctx.move_to(x + 1, y + h - 1)
    ctx.line_to(x + 1, y + 1)
    ctx.line_to(x + w - 1, y + 1)
    ctx.set_source_rgb(*light)
    ctx.stroke()
    ctx.move_to(x + w - 1, y + 1)
    ctx.line_to(x + w - 1, y + h - 1)
    ctx.line_to(x + 1, y + h - 1)
    ctx.set_source_rgb(*dark)
    ctx.stroke()


def ui_text(ctx, text, x, y, size=13, colour=(0, 0, 0), bold=False, align='left'):
    ctx.select_font_face('DejaVu Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD if bold else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)
    ctx.new_path()
    text_path(ctx, text, x, y, align=align)
    ctx.set_source_rgb(*colour)
    ctx.fill()


def title_bar(ctx, x, y, w, text):
    g = cairo.LinearGradient(x, 0, x + w, 0)
    g.add_color_stop_rgb(0, 0.0, 0.0, 0.5)
    g.add_color_stop_rgb(1, 0.1, 0.5, 0.85)
    ctx.rectangle(x, y, w, 22)
    ctx.set_source(g)
    ctx.fill()
    ui_text(ctx, text, x + 8, y + 16, 13, (1, 1, 1), bold=True)
    for k, mark in enumerate(('_', '□', '×')):
        bevel(ctx, x + w - 66 + k * 21, y + 3, 18, 16)
        ui_text(ctx, mark, x + w - 57 + k * 21, y + 15, 11, align='center', bold=True)


def desktop(ctx, t):
    x, y, w, h = SCREEN
    ctx.rectangle(x, y, w, h)
    ctx.set_source_rgb(*TEAL)
    ctx.fill()
    for k, label in enumerate(('My Computer', 'Online', 'Recycle')):
        ix, iy = x + 30, y + 30 + k * 90
        rounded_rect(ctx, ix + 10, iy, 40, 34, 4)
        ctx.set_source_rgb(0.85, 0.85, 0.8)
        ctx.fill()
        ui_text(ctx, label, ix + 30, iy + 54, 11, (1, 1, 1), align='center')
    dx, dy, dw, dh = x + 210, y + 150, 384, 200
    ctx.rectangle(dx + 6, dy + 6, dw, dh)
    ctx.set_source_rgba(0, 0, 0, 0.4)
    ctx.fill()
    bevel(ctx, dx, dy, dw, dh)
    title_bar(ctx, dx + 3, dy + 3, dw - 6, 'Connecting to VizelVision Online')
    for k, cx in enumerate((dx + 70, dx + dw - 70)):    # two computers, a line of dots between them
        ctx.rectangle(cx - 26, dy + 52, 52, 40)
        ctx.set_source_rgb(0.3, 0.3, 0.35)
        ctx.fill()
        ctx.rectangle(cx - 20, dy + 58, 40, 28)
        ctx.set_source_rgb(0.2, 0.6, 0.65)
        ctx.fill()
    if t < CONNECTED:
        for k in range(8):
            on = (int(t * 10) - k) % 8 == 0
            ctx.rectangle(dx + 118 + k * 20, dy + 70, 10, 6)
            ctx.set_source_rgb(*((0.1, 0.9, 0.2) if on else (0.45, 0.45, 0.45)))
            ctx.fill()
    else:
        ctx.rectangle(dx + 118, dy + 71, 150, 4)
        ctx.set_source_rgb(0.1, 0.9, 0.2)
        ctx.fill()
    status = ('Dialing 555-0119...' if t < VERIFYING else 'Verifying user name and password...'
              if t < CONNECTED else 'Connected at 28,800 bps')
    ui_text(ctx, status, dx + dw / 2, dy + 128, 14, align='center')
    bevel(ctx, dx + dw / 2 - 50, dy + 150, 100, 30)
    ui_text(ctx, 'Cancel', dx + dw / 2, dy + 170, 13, align='center')


# ---------------------------------------------------------------- the browser and the page

def browser_chrome(ctx, t, loading):
    x, y, w, h = SCREEN
    ctx.rectangle(x, y, w, h)
    ctx.set_source_rgb(*GREY)
    ctx.fill()
    title_bar(ctx, x + 2, y + 2, w - 4, 'VizelVision Online - Web Browser')
    mx = x + 12
    for item in ('File', 'Edit', 'View', 'Go', 'Bookmarks', 'Help'):
        ui_text(ctx, item, mx, y + 42, 13)
        mx += 22 + 8.5 * len(item)
    for k, label in enumerate(('Back', 'Forward', 'Reload', 'Home', 'Search', 'Stop')):
        bevel(ctx, x + 8 + k * 66, y + 50, 62, 44)
        ctx.arc(x + 39 + k * 66, y + 66, 9, 0, TAU)
        ctx.set_source_rgb(*((0.2, 0.4, 0.8), (0.2, 0.4, 0.8), (0.2, 0.6, 0.3), (0.8, 0.6, 0.2), (0.5, 0.5, 0.5),
                             (0.85, 0.2, 0.2))[k])
        ctx.fill()
        ui_text(ctx, label, x + 39 + k * 66, y + 89, 11, align='center')
    tx, ty = x + w - 62, y + 48                          # the throbber: a comet round a V while it loads
    bevel(ctx, tx, ty, 54, 48, pressed=True, face=(0.05, 0.05, 0.2))
    ui_text(ctx, 'V', tx + 27, ty + 35, 28, (0.9, 0.9, 1), bold=True, align='center')
    if loading:
        a = t * 9
        ctx.arc(tx + 27 + 17 * math.cos(a), ty + 24 + 15 * math.sin(a), 3.5, 0, TAU)
        ctx.set_source_rgb(1, 0.9, 0.3)
        ctx.fill()
    ui_text(ctx, 'Location:', x + 10, y + 114, 13, bold=True)
    bevel(ctx, x + 84, y + 100, w - 160, 20, pressed=True, face=(1, 1, 1))
    url = 'http://www.vizelvision.com/'
    typed = url[:max(0, int(len(url) * span(t, BROWSER, BROWSER + 0.3)))]
    ui_text(ctx, typed, x + 90, y + 115, 13)
    bevel(ctx, x, PAGE_BOTTOM, w, h - (PAGE_BOTTOM - y))
    status = ('Connect: Contacting host: www.vizelvision.com...' if loading else
              'Document: Done') if t < WORDART else 'Document: Done'
    ui_text(ctx, status, x + 10, PAGE_BOTTOM + 17, 12)


@lru_cache(maxsize=None)
def stars_tile():
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 64, 64)
    ctx = cairo.Context(surface)
    ctx.set_source_rgb(0.02, 0.02, 0.12)
    ctx.paint()
    rand = random.Random(3)
    for _ in range(9):
        ctx.rectangle(rand.randrange(64), rand.randrange(64), 1.5, 1.5)
        ctx.set_source_rgb(1, 1, rand.uniform(0.7, 1))
        ctx.fill()
    return surface


def revealed(ctx, t, at, x, y, w, h, draw):
    """An image loading the nineties way: a placeholder box, then drawn from the top down."""
    if t < at - 0.12:
        return
    if t < at:
        ctx.rectangle(x, y, w, h)
        ctx.set_source_rgb(0.75, 0.75, 0.75)
        ctx.set_line_width(1)
        ctx.stroke()
        return
    p = span(t, at, at + 0.22)
    ctx.save()
    ctx.rectangle(x, y, w, h * p + 1)
    ctx.clip()
    draw()
    ctx.restore()


def spinning_v(ctx, t, cx, cy):
    turn = math.cos(t * 4)
    ctx.save()
    ctx.translate(cx, cy)
    ctx.scale(max(abs(turn), 0.08), 1)
    ctx.select_font_face('URW Gothic', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(96)
    ctx.new_path()
    text_path(ctx, 'V', 0, 34, align='center')
    g = cairo.LinearGradient(0, -36, 0, 34)
    g.add_color_stop_rgb(0, 0.95, 0.95, 1)
    g.add_color_stop_rgb(0.5, 0.5, 0.55, 0.7)
    g.add_color_stop_rgb(0.52, 0.3, 0.25, 0.3)
    g.add_color_stop_rgb(1, 0.9, 0.8, 0.95)
    ctx.set_source(g if turn > 0 else cairo.SolidPattern(0.4, 0.4, 0.55))
    ctx.fill_preserve()
    ctx.set_source_rgb(1, 1, 1)
    ctx.set_line_width(1.5)
    ctx.stroke()
    ctx.restore()


def counter(ctx, x, y, number):
    digits = f'{number:07d}'
    for k, d in enumerate(digits):
        ctx.rectangle(x + k * 22, y, 20, 28)
        ctx.set_source_rgb(0, 0, 0)
        ctx.fill()
        ctx.select_font_face('DejaVu Sans Mono', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(20)
        ctx.new_path()
        text_path(ctx, d, x + k * 22 + 10, y + 21, align='center')
        ctx.set_source_rgb(0.3, 1, 0.3)
        ctx.fill()


def page(ctx, t):
    x, y, w, _ = SCREEN
    top, bottom = PAGE_TOP, PAGE_BOTTOM
    ctx.save()
    ctx.rectangle(x + 2, top, w - 4, bottom - top)
    ctx.clip()
    ctx.set_source_rgb(1, 1, 1)
    ctx.paint()
    if t >= LOADS[0]:                                   # the starfield tiles and the headline
        def head():
            pattern = cairo.SurfacePattern(stars_tile())
            pattern.set_extend(cairo.EXTEND_REPEAT)
            ctx.set_source(pattern)
            ctx.paint()
            ctx.select_font_face('Nimbus Roman', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
            ctx.set_font_size(38)
            ctx.new_path()
            text_path(ctx, 'Welcome to VizelVision ONLINE!', x + w / 2, top + 48, align='center')
            ctx.set_source_rgb(1, 0.95, 0.2)
            ctx.fill()
            for k, colour in enumerate(((1, 0, 0), (1, 0.5, 0), (1, 1, 0), (0, 0.8, 0), (0, 0.4, 1), (0.6, 0, 0.8))):
                ctx.rectangle(x + 60, top + 62 + k * 2, w - 120, 2)
                ctx.set_source_rgb(*colour)
                ctx.fill()
        revealed(ctx, t, LOADS[0], x + 2, top, w - 4, bottom - top, head)
    if t >= LOADS[1] - 0.12:
        revealed(ctx, t, LOADS[1], x + 40, top + 90, 130, 120, lambda: spinning_v(ctx, t, x + 105, top + 150))
    if t >= LOADS[2] - 0.12:
        def hits_():
            ctx.select_font_face('Nimbus Roman', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(19)
            ctx.new_path()
            text_path(ctx, 'You are visitor number', x + 200, top + 128)
            ctx.set_source_rgb(1, 1, 1)
            ctx.fill()
            counter(ctx, x + 400, top + 108, 1019 if t < WORDART else 1019 + min(1000, int((t - WORDART) * 1300)))
        revealed(ctx, t, LOADS[2], x + 196, top + 100, 560, 40, hits_)
    if t >= LOADS[3] - 0.12:
        def construction():
            ctx.save()
            ctx.rectangle(x + 200, top + 156, 540, 34)
            ctx.clip()
            for k in range(-2, 30):
                ctx.move_to(x + 200 + k * 26, top + 190)
                ctx.line_to(x + 200 + k * 26 + 13, top + 156)
                ctx.line_to(x + 200 + k * 26 + 26, top + 156)
                ctx.line_to(x + 200 + k * 26 + 13, top + 190)
                ctx.close_path()
            ctx.set_source_rgb(0, 0, 0)
            ctx.paint()
            ctx.set_source_rgb(1, 0.85, 0)
            ctx.fill()
            ctx.restore()
            ctx.rectangle(x + 330, top + 160, 280, 26)
            ctx.set_source_rgb(1, 0.85, 0)
            ctx.fill()
            ui_text(ctx, 'UNDER CONSTRUCTION', x + 470, top + 179, 17, bold=True, align='center')
        revealed(ctx, t, LOADS[3], x + 200, top + 156, 540, 34, construction)
        marquee = '*** Welcome to the Information Superhighway! *** Sign our guestbook! *** Tell a friend! '
        ctx.select_font_face('Nimbus Roman', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(22)
        width = ctx.text_extents(marquee).x_advance
        mx = x + w - (t - LOADS[3]) * 160 % (width + w)
        ctx.new_path()
        text_path(ctx, marquee, mx, top + 226)
        ctx.set_source_rgb(1, 0.35, 0.35)
        ctx.fill()
        for k, (text, colour) in enumerate((('Click here for TV listings!', LINK), ('Sign my guestbook', LINK),
                                            ('Cool links', VISITED))):
            ctx.select_font_face('Nimbus Roman', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
            ctx.set_font_size(19)
            ctx.new_path()
            lx = x + 60 + k * 250
            width_ = text_path(ctx, text, lx, top + 270)
            ctx.set_source_rgb(*(mix(colour, (1, 1, 1), 0.45)))
            ctx.fill()
            ctx.rectangle(lx, top + 274, width_, 1.5)
            ctx.fill()
        pressed = CLICK <= t < CLICK + 0.12
        bevel(ctx, x + w / 2 - 70, top + 296, 140, 44, pressed=pressed)
        ui_text(ctx, 'ENTER', x + w / 2 + (1 if pressed else 0), top + 325 + (1 if pressed else 0), 20, bold=True,
                align='center')
        ctx.select_font_face('Nimbus Roman', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_NORMAL)
        ctx.set_font_size(14)
        ctx.new_path()
        text_path(ctx, 'Best viewed at 800 x 600', x + w / 2, top + 362, align='center')
        ctx.set_source_rgb(0.7, 0.7, 0.8)
        ctx.fill()
    ctx.restore()


# ---------------------------------------------------------------- the closed logo: WordArt

def wordart(ctx, t):
    x, y, w, _ = SCREEN
    ctx.save()
    ctx.rectangle(x + 2, PAGE_TOP, w - 4, PAGE_BOTTOM - PAGE_TOP)
    ctx.clip()
    pattern = cairo.SurfacePattern(stars_tile())
    pattern.set_extend(cairo.EXTEND_REPEAT)
    ctx.set_source(pattern)
    ctx.paint()
    word = 'VizelVision'
    ctx.select_font_face('Nimbus Sans', cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(84)
    advances = [ctx.text_extents(ch).x_advance for ch in word]
    total = sum(advances)
    cx, cy, radius = x + w / 2, PAGE_TOP + 700, 560        # letters along a wide arch
    start = -total / 2
    rainbow = ((1, 0.1, 0.1), (1, 0.5, 0), (1, 0.9, 0), (0.1, 0.8, 0.2), (0.1, 0.5, 1), (0.6, 0.2, 0.9))
    for i, ch in enumerate(word):
        p = span(t, WORDART + i * 0.0625, WORDART + i * 0.0625 + 0.25)
        if p <= 0:
            start += advances[i]
            continue
        mid = start + advances[i] / 2
        angle = mid / radius
        ctx.save()
        ctx.translate(cx + radius * math.sin(angle), cy - radius * math.cos(angle))
        ctx.rotate(angle)
        k = back_out(p, 2.4)
        ctx.scale(k, k)
        ctx.new_path()
        ctx.move_to(-advances[i] / 2, 0)
        ctx.text_path(ch)
        path = ctx.copy_path()
        for d in range(8, 0, -1):                           # its 3D shadow, down and right
            ctx.save()
            ctx.translate(d * 0.8, d * 0.8)
            ctx.new_path()
            ctx.append_path(path)
            ctx.set_source_rgb(0.25, 0.1, 0.35)
            ctx.fill()
            ctx.restore()
        ctx.new_path()
        ctx.append_path(path)
        g = cairo.LinearGradient(0, -62, 0, 0)
        for s, colour in enumerate(rainbow):
            g.add_color_stop_rgb(s / 5, *colour)
        ctx.set_source(g)
        ctx.fill_preserve()
        ctx.set_source_rgb(1, 1, 1)
        ctx.set_line_width(1.5)
        ctx.stroke()
        ctx.restore()
        start += advances[i]
    p = span(t, WORDART + 0.75, WORDART + 1.0)
    if p > 0:
        ctx.select_font_face('Nimbus Sans', cairo.FONT_SLANT_ITALIC, cairo.FONT_WEIGHT_BOLD)
        ctx.set_font_size(42)
        ctx.new_path()
        text_path(ctx, 'CHANNEL 19', cx, PAGE_TOP + 250, tracking=6, align='center')
        path = ctx.copy_path()
        for d in range(6, 0, -1):
            ctx.save()
            ctx.translate(d, d)
            ctx.new_path()
            ctx.append_path(path)
            ctx.set_source_rgba(0.2, 0.2, 0.3, ease_out(p))
            ctx.fill()
            ctx.restore()
        ctx.new_path()
        ctx.append_path(path)
        g = cairo.LinearGradient(0, PAGE_TOP + 214, 0, PAGE_TOP + 250)
        g.add_color_stop_rgb(0, 1, 1, 1)
        g.add_color_stop_rgb(0.5, 0.6, 0.65, 0.75)
        g.add_color_stop_rgb(1, 0.95, 0.95, 1)
        ctx.set_source(g)
        ctx.fill()
    for i, when in enumerate(NEW_BURSTS):                   # NEW! bursts, blinking
        q = span(t, when, when + 0.2)
        if q <= 0 or math.sin((t - when) * 18) < -0.6:
            continue
        bx, by = ((x + 120, PAGE_TOP + 290), (x + w - 120, PAGE_TOP + 300), (x + w / 2, PAGE_TOP + 320))[i]
        ctx.save()
        ctx.translate(bx, by)
        ctx.rotate(-0.2 + 0.2 * i)
        k = back_out(q, 2.4)
        ctx.scale(k, k)
        ctx.new_path()
        for j in range(24):
            r = 44 if j % 2 == 0 else 32
            ctx.line_to(math.cos(j * TAU / 24) * r, math.sin(j * TAU / 24) * r * 0.7)
        ctx.close_path()
        ctx.set_source_rgb(1, 0.1, 0.2)
        ctx.fill()
        ui_text(ctx, 'NEW!', 0, 7, 20, (1, 1, 0.3), bold=True, align='center')
        ctx.restore()
    counter(ctx, cx - 77, PAGE_BOTTOM - 44, 1019 + min(9000, int((t - WORDART) * 1300)))
    ctx.restore()


def pointer(ctx, t):
    """The arrow, wandering from the corner to ENTER, then clicking."""
    if t < CURSOR[0] - 0.4 or t >= WORDART + 0.3:
        return
    x, y, w, _ = SCREEN
    p = ease_in_out(span(t, *CURSOR))
    sx, sy = x + w - 90, PAGE_TOP + 40
    ex, ey = x + w / 2 + 18, PAGE_TOP + 322
    px = sx + (ex - sx) * p + 30 * math.sin(math.pi * p)
    py = sy + (ey - sy) * p
    ctx.save()
    ctx.translate(px, py)
    for pts, colour, width in ((((0, 0), (0, 24), (6, 18), (11, 28), (15, 26), (10, 17), (18, 17)), (0, 0, 0), 0),):
        ctx.move_to(*pts[0])
        for pt in pts[1:]:
            ctx.line_to(*pt)
        ctx.close_path()
        ctx.set_source_rgb(1, 1, 1)
        ctx.fill_preserve()
        ctx.set_source_rgb(*colour)
        ctx.set_line_width(1.5)
        ctx.stroke()
    ctx.restore()


# ---------------------------------------------------------------- the frame

def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= FADE[1]:
        return
    ctx.set_source_surface(wallpaper(), 0, 0)
    ctx.paint()
    monitor(ctx)
    x, y, w, h = SCREEN
    ctx.save()
    rounded_rect(ctx, x, y, w, h, 14)
    ctx.clip()
    if t < BROWSER:
        desktop(ctx, t)
    else:
        loading = t < LOADS[3] + 0.25
        browser_chrome(ctx, t, loading)
        if t < WORDART:
            page(ctx, t)
        else:
            wordart(ctx, t)
        pointer(ctx, t)
    glass(ctx)
    ctx.restore()
    vignette(ctx, 0.45)
    grain(ctx, frame, 0.35)
    opening = 1 - ease_out(span(t, 0.0, 0.3))
    if opening > 0:
        ctx.set_source_rgba(0, 0, 0, opening)
        ctx.paint()
    out = span(t, *FADE)
    if out > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(out))
        ctx.paint()
