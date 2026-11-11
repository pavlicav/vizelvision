"""The VizelVision station ID picture, clean (November 2026), drawn frame by frame with cairo.

The user found the 1990s ID's Memphis confetti, neon grid and chrome too busy ("the weird
shapes vizelvision thing is bad, can we make a cleaner one?"). This one keeps its timing and
its music, so every hit still lands on a hit (timeline.py), and its end card at 27.9 s, which
master holds while the next programme is prepared (roku_stream/ident.py IDENT_HOLD_AT):

- a deep navy field with one soft glow behind the emblem, nothing else moving;
- the TV emblem drawn flat, in line: it rises in and settles on the orchestra hit, with a
  single ring of light;
- VIZELVISION set evenly in one weight, VIZEL in white and VISION in the accent, a letter
  on each eighth note, one slow light sweep across it;
- a thin rule and STAY TUNED, letterspaced, for the end card;
- the accent warms from teal to gold through the build into the key change;
- a fade (with a slight settle) to black from the iris mark, black and silent to the end.

The promos, the Sports ID and My ads' break card still draw with animation.py's kit.

    python3 clean_animation.py --still 27.9 frame.png     one frame, for checking
Frames for the encoder come from render(frame) (BGRx bytes); see build.py.
"""
import argparse
import math
import sys
from functools import lru_cache
from pathlib import Path

import cairo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import timeline as T  # noqa: E402

W, H = T.WIDTH, T.HEIGHT
TAU = math.tau
# No VHS colour fringing: a whisper of grain only, against banding in the gradients (build.py).
VIDEO_FILTER = 'noise=alls=2:allf=t,format=yuv420p'

NAVY_TOP = (0.035, 0.05, 0.11)
NAVY_BOTTOM = (0.06, 0.085, 0.17)
WHITE = (0.97, 0.98, 1.0)
TEAL = (0.24, 0.86, 0.80)
GOLD = (1.0, 0.76, 0.32)
FAMILY = 'Open Sans'
TAGLINE_TEXT = 'STAY TUNED'

EMBLEM = (640, 268)          # centre of the TV
WORD_Y = 468                 # wordmark baseline
WORD_SIZE = 92
WORD_TRACK = 7               # extra space between letters
RULE_Y = 506
TAG_Y = 552


# ---------------------------------------------------------------- easing

def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def span(t, a, b):
    return clamp((t - a) / (b - a)) if b != a else float(t >= a)


def ease_out(x, power=3):
    return 1 - (1 - clamp(x)) ** power


def ease_in_out(x):
    x = clamp(x)
    return 0.5 - 0.5 * math.cos(math.pi * x)


def mix(a, b, k):
    return tuple(x + (y - x) * k for x, y in zip(a, b))


def pulse(t, at, length):
    """1 at `at`, easing back to 0 over `length`."""
    if t < at or t > at + length:
        return 0.0
    return 1 - ease_out((t - at) / length, 2)


def accent(t):
    return mix(TEAL, GOLD, ease_in_out(span(t, T.BUILD, T.KEY_CHANGE)))


# ---------------------------------------------------------------- layers

def field(ctx, t):
    """The navy field and one soft glow behind the emblem, swelling as it lands."""
    gradient = cairo.LinearGradient(0, 0, 0, H)
    gradient.add_color_stop_rgb(0, *NAVY_TOP)
    gradient.add_color_stop_rgb(1, *NAVY_BOTTOM)
    ctx.set_source(gradient)
    ctx.paint()
    glow = 0.10 + 0.10 * ease_out(span(t, T.LOGO_FLIGHT, T.HIT + 1.0)) + 0.08 * pulse(t, T.HIT, 1.6) \
        + 0.06 * pulse(t, T.KEY_CHANGE, 1.4) + 0.06 * pulse(t, T.BUTTON, 1.2)
    drift = math.sin(t * 0.35) * 18
    x, y = EMBLEM[0] + drift, EMBLEM[1] + 70
    radial = cairo.RadialGradient(x, y, 0, x, y, 560)
    r, g, b = accent(t)
    radial.add_color_stop_rgba(0, r, g, b, glow)
    radial.add_color_stop_rgba(0.45, r, g, b, glow * 0.35)
    radial.add_color_stop_rgba(1, r, g, b, 0)
    ctx.set_source(radial)
    ctx.paint()
    # A faint vignette keeps the eye in the middle.
    vignette = cairo.RadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, W * 0.75)
    vignette.add_color_stop_rgba(0, 0, 0, 0, 0)
    vignette.add_color_stop_rgba(1, 0, 0, 0, 0.45)
    ctx.set_source(vignette)
    ctx.paint()


def rounded_rect(ctx, x, y, w, h, r):
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -TAU / 4, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, TAU / 4)
    ctx.arc(x + r, y + h - r, r, TAU / 4, TAU / 2)
    ctx.arc(x + r, y + r, r, TAU / 2, 3 * TAU / 4)
    ctx.close_path()


def emblem_pose(t):
    """(y offset, scale, opacity): rising in from the flight mark, settled on the hit."""
    k = ease_out(span(t, T.LOGO_FLIGHT, T.HIT), 4)
    settle = pulse(t, T.HIT, 0.5)
    beat = 0.035 * pulse(t, T.KEY_CHANGE, 0.5) + 0.03 * pulse(t, T.BUTTON, 0.5)
    return 46 * (1 - k), 0.82 + 0.18 * k + 0.025 * settle + beat, k


def emblem(ctx, t):
    if t < T.LOGO_FLIGHT:
        return
    dy, scale, alpha = emblem_pose(t)
    colour = accent(t)
    ctx.save()
    ctx.translate(EMBLEM[0], EMBLEM[1] + dy)
    ctx.scale(scale, scale)
    ctx.push_group()
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    w, h = 200, 146
    # Antennas.
    ctx.set_source_rgb(*WHITE)
    ctx.set_line_width(6)
    for side in (-1, 1):
        ctx.move_to(side * 10, -h / 2 - 4)
        ctx.line_to(side * 46, -h / 2 - 50)
        ctx.stroke()
        ctx.arc(side * 46, -h / 2 - 50, 6.5, 0, TAU)
        ctx.fill()
    # Cabinet, with the screen tinted in the accent.
    rounded_rect(ctx, -w / 2, -h / 2, w, h, 26)
    ctx.set_source_rgba(*colour, 0.12)
    ctx.fill_preserve()
    ctx.set_source_rgb(*WHITE)
    ctx.set_line_width(7)
    ctx.stroke()
    # Feet.
    for side in (-1, 1):
        ctx.move_to(side * 52, h / 2 + 2)
        ctx.line_to(side * 62, h / 2 + 20)
        ctx.stroke()
    # The V.
    ctx.set_source_rgb(*colour)
    ctx.set_line_width(13)
    ctx.move_to(-34, -34)
    ctx.line_to(0, 36)
    ctx.line_to(34, -34)
    ctx.stroke()
    ctx.pop_group_to_source()
    ctx.paint_with_alpha(alpha)
    ctx.restore()
    ring(ctx, t)


def ring(ctx, t):
    """One ring of light out from the emblem on the hit (and a smaller one on the button)."""
    for at, size, strength in ((T.HIT, 1.0, 0.55), (T.KEY_CHANGE, 0.8, 0.35), (T.BUTTON, 0.7, 0.35)):
        k = span(t, at, at + 1.1)
        if 0 < k < 1:
            ctx.set_source_rgba(*accent(t), strength * (1 - k) ** 2)
            ctx.set_line_width(3)
            ctx.arc(EMBLEM[0], EMBLEM[1], (120 + 260 * ease_out(k)) * size, 0, TAU)
            ctx.stroke()


@lru_cache(maxsize=None)
def word_layout():
    """[(letter, x)] for VIZELVISION centred at W/2, evenly tracked."""
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 8, 8)
    ctx = cairo.Context(surface)
    ctx.select_font_face(FAMILY, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(WORD_SIZE)
    letters = ''.join(T.WORDMARK)
    advances = [ctx.text_extents(letter).x_advance for letter in letters]
    total = sum(advances) + WORD_TRACK * (len(letters) - 1)
    x, placed = (W - total) / 2, []
    for letter, advance in zip(letters, advances):
        placed.append((letter, x))
        x += advance + WORD_TRACK
    return tuple(placed), (W - total) / 2, total


def wordmark(ctx, t):
    if t < T.LETTERS:
        return
    placed, left, total = word_layout()
    first = len(T.WORDMARK[0])
    ctx.select_font_face(FAMILY, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    ctx.set_font_size(WORD_SIZE)
    colour = accent(t)
    for index, (letter, x) in enumerate(placed):
        k = ease_out(span(t, T.LETTERS + index * T.LETTER_STEP, T.LETTERS + index * T.LETTER_STEP + 0.4))
        if k <= 0:
            continue
        ctx.set_source_rgba(*(WHITE if index < first else colour), k)
        ctx.move_to(x, WORD_Y + 22 * (1 - k))
        ctx.show_text(letter)
    sweep(ctx, t, placed)


def sweep(ctx, t, placed):
    """One slow band of light across the wordmark, clipped to its letters."""
    k = span(t, T.SWEEP, T.SWEEP + 1.6)
    if not 0 < k < 1:
        return
    ctx.save()
    ctx.new_path()
    for letter, x in placed:
        ctx.move_to(x, WORD_Y)
        ctx.text_path(letter)
    ctx.clip()
    _, left, total = word_layout()
    centre = left - 120 + (total + 240) * ease_in_out(k)
    band = cairo.LinearGradient(centre - 90, 0, centre + 90, 0)
    band.add_color_stop_rgba(0, 1, 1, 1, 0)
    band.add_color_stop_rgba(0.5, 1, 1, 1, 0.55)
    band.add_color_stop_rgba(1, 1, 1, 1, 0)
    ctx.set_source(band)
    ctx.paint()
    ctx.restore()


def tagline(ctx, t):
    """A thin rule drawn out from the centre, then STAY TUNED under it."""
    if t < T.TAGLINE:
        return
    k = ease_out(span(t, T.TAGLINE, T.TAGLINE + 0.7))
    half = 170 * k
    ctx.set_source_rgba(*accent(t), 0.9)
    ctx.set_line_width(2.5)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.move_to(W / 2 - half, RULE_Y)
    ctx.line_to(W / 2 + half, RULE_Y)
    ctx.stroke()
    fade = ease_out(span(t, T.TAGLINE + 0.35, T.TAGLINE + 1.1))
    if fade <= 0:
        return
    ctx.select_font_face(FAMILY, cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(25)
    track = 9
    widths = [ctx.text_extents(c).x_advance for c in TAGLINE_TEXT]
    x = W / 2 - (sum(widths) + track * (len(TAGLINE_TEXT) - 1)) / 2
    ctx.set_source_rgba(*WHITE, 0.85 * fade)
    for c, advance in zip(TAGLINE_TEXT, widths):
        ctx.move_to(x, TAG_Y + 8 * (1 - fade))
        ctx.show_text(c)
        x += advance + track


def opening(ctx, t):
    """Out of black: a thin line of light opens into the picture, as a set warming up."""
    if t >= T.START:
        return
    k = ease_out(span(t, 0, T.START))
    ctx.set_source_rgba(0, 0, 0, 1 - k)
    ctx.paint()
    ctx.set_source_rgba(1, 1, 1, 0.6 * (1 - k))
    ctx.rectangle(W / 2 - W / 2 * k, H / 2 - 1.5, W * k, 3)
    ctx.fill()


def closing(ctx, t):
    """From the iris mark: a fade to black, black from BLACK on."""
    k = span(t, T.IRIS, T.BLACK)
    if k > 0:
        ctx.set_source_rgba(0, 0, 0, ease_in_out(k))
        ctx.paint()


def camera(ctx, t):
    """Almost still: a slow push through the whole ID and a slight settle into the close."""
    zoom = 1.0 + 0.025 * ease_in_out(span(t, T.START, T.IRIS)) - 0.02 * ease_in_out(span(t, T.IRIS, T.BLACK))
    ctx.translate(W / 2, H / 2)
    ctx.scale(zoom, zoom)
    ctx.translate(-W / 2, -H / 2)


# ---------------------------------------------------------------- frames

def draw(ctx, t, frame=0):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    if t >= T.BLACK:
        return
    ctx.save()
    camera(ctx, t)
    field(ctx, t)
    emblem(ctx, t)
    wordmark(ctx, t)
    tagline(ctx, t)
    ctx.restore()
    opening(ctx, t)
    closing(ctx, t)


def frames():
    return round(T.DURATION * T.FPS)


def render(frame):
    """One frame as raw BGRx bytes (ffmpeg pix_fmt bgr0)."""
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    draw(cairo.Context(surface), frame / T.FPS, frame)
    surface.flush()
    return bytes(surface.get_data())


def still(t, path):
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    draw(cairo.Context(surface), t, int(t * T.FPS))
    surface.write_to_png(str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Draw one frame of the clean station ID')
    parser.add_argument('--still', type=float, required=True, metavar='SECONDS')
    parser.add_argument('out', type=Path)
    args = parser.parse_args(argv)
    still(args.still, args.out)


if __name__ == '__main__':
    main()
