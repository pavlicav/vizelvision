"""Press Start: VizelVision as an 8-bit game. The TV emblem as a sprite walks in over
the bricks, jumps and bumps a ? block, a V coin pops out (+19, the channel), the
wordmark drops in letter by letter, the closed logo plays on square waves, and PRESS
START blinks. Drawn at 256x144 and blown up five times with hard pixels, under scanlines.
Five seconds.
"""
import math
from functools import lru_cache

import cairo

from common import W, H, flash, pixel_text, scanlines, span, vignette  # noqa: F401

ID = 'press-start'
NAME = 'Press Start'
KIND = 'ident'
ORDER = 5
DESCRIPTION = ('VizelVision as an 8-bit game: the TV sprite bumps a ? block, a V coin pops out (+19), the '
               'wordmark drops in and the four-note logo plays on square waves. PRESS START.')
DURATION = 5.0
STILL_AT = 3.3
OVERLAYS = []

LW, LH, PX = 256, 144, 5
# Hit points (the music's too).
FADE_IN = (0.0, 0.18)
WALK = (0.15, 1.0)
JUMP = (1.0, 1.5)
BUMP = 1.2
LETTERS, LETTER_STEP = 1.75, 0.1
LOGO = 3.0
START_BLINK = 3.0
HOP = (3.0, 3.5)
FADE_OUT = (4.3, 4.6)
GROUND = 118
BLOCK = (104, 64)

PALETTE = {
    'sky': (0.05, 0.05, 0.22), 'star': (1.0, 1.0, 0.85), 'brick': (0.78, 0.36, 0.12), 'mortar': (0.32, 0.12, 0.05),
    'hill': (0.12, 0.58, 0.22), 'hill2': (0.36, 0.8, 0.3), 'block': (0.98, 0.76, 0.12), 'used': (0.55, 0.32, 0.12),
    'ink': (0.05, 0.02, 0.08), 'white': (1.0, 1.0, 1.0), 'pink': (1.0, 0.25, 0.55), 'yellow': (1.0, 0.86, 0.15),
    'teal': (0.0, 0.8, 0.72), 'teal2': (0.0, 0.5, 0.55), 'screen': (0.1, 0.35, 0.85), 'cyan': (0.45, 0.95, 1.0),
    'grey': (0.75, 0.78, 0.85), 'cloud': (0.85, 0.88, 1.0),
}
TV = (  # the emblem as a 16x15 sprite: . clear, p pink, y yellow, g grey, k ink, t teal, d dark teal, s screen, v V
    '..y..........p..',
    '...g........g...',
    '....g......g....',
    '.....g....g.....',
    '......g..g......',
    '...kkkkkkkkkk...',
    '..kttttttttttk..',
    '.ktsssssssstttk.',
    '.ktsvsssssvtytk.',
    '.ktssvsssvstttk.',
    '.ktsssvsvsstptk.',
    '.ktssssvssstttk.',
    '.ktsssssssstddk.',
    '..kdddddddddddk.',
    '...kkkkkkkkkkk..',
)
LEGS = ('..kk......kk....', '...kk....kk.....')
MOON = ('..####..', '.##.....', '##......', '##......', '##......', '##......', '.##.....', '..####..')
COLOURS = {'p': 'pink', 'y': 'yellow', 'g': 'grey', 'k': 'ink', 't': 'teal', 'd': 'teal2', 's': 'screen', 'v': 'white'}


def px(ctx, x, y, w, h, colour, dim=1.0):
    ctx.rectangle(int(round(x)), int(round(y)), w, h)
    ctx.set_source_rgb(*(c * dim for c in PALETTE[colour]))
    ctx.fill()


def sprite(ctx, rows, x, y, dim, legs=None):
    for r, row in enumerate(rows + ((legs,) if legs else ())):
        for c, key in enumerate(row):
            if key != '.':
                px(ctx, x + c, y + r, 1, 1, COLOURS[key], dim)


def stars(ctx, t, dim):
    for i in range(30):
        x, y = (i * 97 + 13) % LW, (i * 53 + 7) % 96
        if (int(t * 8) + i) % 7 == 0:
            continue
        px(ctx, x, y, 1, 1, 'star', dim)


def world(ctx, t, dim):
    px(ctx, 0, 0, LW, LH, 'sky', dim)
    stars(ctx, t, dim)
    for r, row in enumerate(MOON):             # a pixel crescent
        for c, key in enumerate(row):
            if key == '#':
                px(ctx, 226 + c, 56 + r, 1, 1, 'cloud', dim)
    for cx, cy in ((34, 34), (150, 48)):       # clouds
        for dx, dy, w in ((0, 4, 24), (4, 0, 14), (8, 8, 18)):
            drift = cx + dx - (t * 6) % 300
            px(ctx, drift if drift > -30 else drift + 300, cy + dy, w, 5, 'cloud', dim * 0.8)
    for hx, hw, hh in ((6, 50, 22), (160, 64, 28), (216, 40, 14)):   # hills
        for k in range(hh):
            w = int(hw * (1 - (k / hh) ** 2))
            px(ctx, hx + (hw - w) // 2, GROUND - k, w, 1, 'hill' if k < hh - 4 else 'hill2', dim)
    px(ctx, 0, GROUND, LW, LH - GROUND, 'brick', dim)
    for row in range(0, LH - GROUND, 8):
        px(ctx, 0, GROUND + row, LW, 1, 'mortar', dim)
        for col in range(0, LW, 16):
            px(ctx, col + (8 if (row // 8) % 2 else 0), GROUND + row, 1, 8, 'mortar', dim)


def block(ctx, t, dim):
    bx, by = BLOCK
    bump = -4 * math.sin(math.pi * span(t, BUMP, BUMP + 0.15))
    used = t >= BUMP
    px(ctx, bx, by + bump, 16, 16, 'ink', dim)
    px(ctx, bx + 1, by + 1 + bump, 14, 14, 'used' if used else 'block', dim)
    if not used:
        pixel_text(ctx, '?', bx + 5.5, by + 4.5 + bump, 1, tuple(c * dim for c in PALETTE['ink']))
    for cx, cy in ((2, 2), (12, 2), (2, 12), (12, 12)):
        px(ctx, bx + cx, by + cy + bump, 1, 1, 'ink', dim)


def coin(ctx, t, dim):
    p = span(t, BUMP, BUMP + 0.5)
    if not 0 < p < 1:
        return
    bx, by = BLOCK
    y = by - 6 - 46 * math.sin(math.pi * min(1.0, p * 1.2))
    w = max(1, int(round(8 * abs(math.cos(t * 26)))))
    px(ctx, bx + 8 - w / 2 - 1, y - 1, w + 2, 14, 'ink', dim)
    px(ctx, bx + 8 - w / 2, y, w, 12, 'yellow', dim)
    if w >= 6:
        pixel_text(ctx, 'V', bx + 5.5, y + 2.5, 1, tuple(c * dim for c in PALETTE['pink']))
    q = span(t, BUMP + 0.1, BUMP + 0.9)
    if 0 < q < 1:
        pixel_text(ctx, '+19', bx + 20, by - 10 - 20 * q, 1, tuple(c * dim for c in PALETTE['white']))


def hero(ctx, t, dim):
    """The TV sprite: walks in, jumps at the block, lands, then hops for joy."""
    x = -18 + (BLOCK[0] - (-18)) * span(t, *WALK)
    y = GROUND - 16
    legs = LEGS[int(t * 10) % 2] if WALK[0] <= t < WALK[1] else LEGS[0]
    if JUMP[0] <= t < JUMP[1]:
        p = span(t, *JUMP)
        y -= (GROUND - 16 - (BLOCK[1] + 16)) * math.sin(math.pi * p) * 1.05 if p < .4 else 0
        if p < .4:
            y = GROUND - 16 - (GROUND - 16 - (BLOCK[1] + 16)) * math.sin(math.pi * p / .8)
        else:
            y = BLOCK[1] + 16 + (GROUND - 16 - BLOCK[1] - 16) * ((p - .4) / .6) ** 2
        legs = LEGS[1]
    hop = span(t, *HOP)
    if 0 < hop < 1:
        y -= 14 * abs(math.sin(math.pi * 2 * hop))
    sprite(ctx, TV, x, y - 15 + 16, dim, legs)


def wordmark(ctx, t, dim):
    text = 'VIZELVISION'
    width = len(text) * 12 - 2
    x0 = (LW - width) // 2
    colours = ('pink', 'yellow', 'teal', 'yellow', 'pink', 'cyan', 'white', 'cyan', 'white', 'cyan', 'white')
    for i, ch in enumerate(text):
        land = LETTERS + i * LETTER_STEP
        p = span(t, land - 0.12, land)
        if p <= 0:
            continue
        y = 22 - 40 * (1 - p) ** 2 - 3 * math.sin(math.pi * span(t, land, land + 0.12))
        y -= 3 * abs(math.sin(math.pi * 2 * span(t, LOGO + i * 0.03, LOGO + 0.5 + i * 0.03)))
        pixel_text(ctx, ch, x0 + i * 12, int(y), 2, tuple(c * dim for c in PALETTE[colours[i]]),
                   shadow=(1, 1, tuple(c * dim for c in PALETTE['ink'])))


def hud(ctx, t, dim):
    white = tuple(c * dim for c in PALETTE['white'])
    pixel_text(ctx, 'SCORE', 8, 6, 1, white)
    pixel_text(ctx, '000019' if t >= BUMP + 0.05 else '000000', 8, 15, 1, tuple(c * dim for c in PALETTE['yellow']))
    pixel_text(ctx, 'CH 19', LW - 8, 6, 1, white, 'right')
    if int(t * 4) % 2 == 0:
        pixel_text(ctx, '1UP', LW - 8, 15, 1, tuple(c * dim for c in PALETTE['pink']), 'right')
    if t >= START_BLINK and int((t - START_BLINK) * 4) % 2 == 0:
        pixel_text(ctx, 'PRESS START', LW // 2, 48, 1, white, 'center', shadow=(1, 1, tuple(c * dim for c in PALETTE['ink'])))
    if t >= LOGO:
        pixel_text(ctx, '© VIZELVISION 19', LW // 2, 131, 1, tuple(c * dim * .85 for c in PALETTE['white']), 'center')


@lru_cache(maxsize=1)
def canvas():
    return cairo.ImageSurface(cairo.FORMAT_RGB24, LW, LH)


def dim_at(t):
    """NES-style fades: the palette steps, not a smooth ramp."""
    if t < FADE_IN[1]:
        return (int(span(t, *FADE_IN) * 4) + 1) / 4
    if t >= FADE_OUT[0]:
        return 1 - min(4, int(span(t, *FADE_OUT) * 4) + 1) / 4
    return 1.0


def draw(ctx, t, frame):
    ctx.set_source_rgb(0, 0, 0)
    ctx.paint()
    dim = dim_at(t)
    if dim <= 0:
        return
    low = canvas()
    small = cairo.Context(low)
    small.set_antialias(cairo.ANTIALIAS_NONE)
    world(small, t, dim)
    block(small, t, dim)
    coin(small, t, dim)
    hero(small, t, dim)
    wordmark(small, t, dim)
    hud(small, t, dim)
    low.flush()
    ctx.save()
    ctx.scale(PX, PX)
    ctx.set_source_surface(low, 0, 0)
    ctx.get_source().set_filter(cairo.FILTER_NEAREST)
    ctx.paint()
    ctx.restore()
    scanlines(ctx, 0.16, 4)
    vignette(ctx, 0.4)
