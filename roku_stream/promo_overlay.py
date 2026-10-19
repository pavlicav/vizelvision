"""Live text on a station promo (promos.py): the time, the temperature, the programme on
air, drawn over the promo's own pictures as it airs, so a bumper built once always says
what is true at that moment.

Pure pycairo, no GStreamer. Master turns these pictures into overlay rectangles that
GStreamer blends into the promo's frames as they decode (ad_break.PromoReel). The web app
draws them over a promo's still and serves them for the page's preview player. The
build uses them to check its layouts.

An overlay, from the promo's manifest (ident/promos/<id>.json):

    {"field": "time", "box": [x, y, w, h], "from": 1.3, "to": 9.4,
     "style": {"font": "URW Bookman", "size": 150, "color": [0.3, 0.15, 0.05], ...},
     "enter": {"kind": "flip", "seconds": 0.35}, "exit": {"kind": "fade", "seconds": 0.3}}

The text is fitted to its box. It shrinks to fit, takes two lines if the style allows,
and is cut short with an ellipsis as a last resort. Its picture is rendered once per text.
place() animates the box over time: flip (it unfolds from a line), pop, or fade in, and
fade out.
"""
from __future__ import annotations

import math
import time

import cairo

FIELDS = ('time', 'ampm', 'temperature', 'programme', 'place', 'decimal_time', 'celsius')
DECIMAL_SECOND = 0.864         # a day of ten hours, a hundred minutes each, a hundred seconds each
ENTERS = ('none', 'fade', 'flip', 'pop')
EXITS = ('none', 'fade')
STYLE = {
    'font': 'Nimbus Sans', 'bold': True, 'italic': False,
    'size': 96.0, 'min_size': 24.0,          # px: the largest the text is drawn, and the smallest it shrinks to
    'color': (1.0, 1.0, 1.0),
    'outline': None, 'outline_width': 0.0,   # an ink line around each letter
    'shadow': None,                          # [dx, dy, r, g, b, a]: a hard drop shadow
    'align': 'center',                       # left | center | right
    'tracking': 0.0,                         # extra space between letters, a fraction of the size
    'lines': 1,                              # 2: a long text may wrap onto a second line
    'upper': False,
}
MAX_BOX = (1920, 1080)


def _number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
        raise ValueError(f'expected a number from {lo} to {hi}, not {value!r}')
    return float(value)


def _colour(value, size=3):
    if value is None:
        return None
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise ValueError(f'a colour is {size} numbers from 0 to 1')
    return tuple(_number(c, 0, 1) for c in value)


def validate(spec):
    """One overlay from a manifest, checked and completed; ValueError if it cannot be drawn."""
    if not isinstance(spec, dict) or spec.get('field') not in FIELDS:
        raise ValueError('an overlay needs a field: ' + ', '.join(FIELDS))
    box = spec.get('box')
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError('an overlay needs a box: x, y, width, height')
    x, y = (int(_number(v, -MAX_BOX[0], MAX_BOX[0])) for v in box[:2])
    w, h = int(_number(box[2], 4, MAX_BOX[0])), int(_number(box[3], 4, MAX_BOX[1]))
    start, end = _number(spec.get('from', 0), 0, 3600), _number(spec.get('to', 3600), 0, 3600)
    if end <= start:
        raise ValueError('an overlay ends after it starts')
    raw = spec.get('style') or {}
    if not isinstance(raw, dict) or set(raw) - set(STYLE):
        raise ValueError('style takes ' + ', '.join(STYLE))
    style = {**STYLE, **raw}
    if not isinstance(style['font'], str) or not style['font'] or len(style['font']) > 60:
        raise ValueError('style font is a family name')
    style['size'] = _number(style['size'], 4, 600)
    style['min_size'] = min(style['size'], _number(style['min_size'], 4, 600))
    style['color'] = _colour(style['color'])
    style['outline'] = _colour(style['outline'])
    style['outline_width'] = _number(style['outline_width'], 0, 40)
    if style['shadow'] is not None:
        shadow = style['shadow']
        if not isinstance(shadow, (list, tuple)) or len(shadow) != 6:
            raise ValueError('style shadow is dx, dy, r, g, b, a')
        style['shadow'] = (_number(shadow[0], -40, 40), _number(shadow[1], -40, 40), *_colour(shadow[2:], 4))
    if style['align'] not in ('left', 'center', 'right'):
        raise ValueError('style align is left, center or right')
    style['tracking'] = _number(style['tracking'], -0.2, 1)
    if style['lines'] not in (1, 2):
        raise ValueError('style lines is 1 or 2')
    for key in ('bold', 'italic', 'upper'):
        if not isinstance(style[key], bool):
            raise ValueError(f'style {key} is true or false')
    moves = []
    for key, kinds in (('enter', ENTERS), ('exit', EXITS)):
        move = spec.get(key) or {'kind': 'none'}
        if not isinstance(move, dict) or move.get('kind', 'none') not in kinds:
            raise ValueError(f'{key} is one of ' + ', '.join(kinds))
        moves.append({'kind': move.get('kind', 'none'), 'seconds': _number(move.get('seconds', .3), 0, 5)})
    return {'field': spec['field'], 'box': (x, y, w, h), 'from': start, 'to': end, 'style': style,
            'enter': moves[0], 'exit': moves[1]}


def validate_all(specs):
    """The overlays that can be drawn, and why the others cannot (lenient: master and page)."""
    good, bad = [], []
    for spec in specs if isinstance(specs, list) else []:
        try:
            good.append(validate(spec))
        except (ValueError, TypeError) as exc:
            bad.append(str(exc))
    return good, bad


# ---------------------------------------------------------------- the words

def field_text(field, values, now=None):
    """What a field says now; None when it is not known (the promo sits out)."""
    now = time.time() if now is None else now
    values = values or {}
    if field in ('time', 'ampm'):
        local = time.localtime(now)
        if field == 'ampm':
            return 'AM' if local.tm_hour < 12 else 'PM'
        return f'{local.tm_hour % 12 or 12}:{local.tm_min:02d}'
    if field == 'decimal_time':       # French Revolutionary time, to the decimal second: 5:95:30
        local = time.localtime(now)
        seconds = local.tm_hour * 3600 + local.tm_min * 60 + local.tm_sec + now % 1
        hours, rest = divmod(min(99999, int(seconds / DECIMAL_SECOND)), 10000)
        return f'{hours}:{rest // 100:02d}:{rest % 100:02d}'
    if field in ('temperature', 'place', 'celsius'):
        reading = values.get('temperature') or {}
        if field == 'place':
            return reading.get('place') or None
        if field == 'celsius':
            c = reading.get('c')
            if not isinstance(c, (int, float)) and isinstance(reading.get('f'), (int, float)):
                c = (reading['f'] - 32) * 5 / 9
            return f'{round(c)}°C' if isinstance(c, (int, float)) else None
        return f"{reading['f']}°" if isinstance(reading.get('f'), (int, float)) else None
    if field == 'programme':
        return (values.get('programme') or {}).get('title') or None
    return None


# ---------------------------------------------------------------- the pictures

def _face(ctx, style, size):
    ctx.select_font_face(style['font'], cairo.FONT_SLANT_ITALIC if style['italic'] else cairo.FONT_SLANT_NORMAL,
                         cairo.FONT_WEIGHT_BOLD if style['bold'] else cairo.FONT_WEIGHT_NORMAL)
    ctx.set_font_size(size)


def _width(ctx, text, size, tracking):
    if not text:
        return 0.0
    advances = sum(ctx.text_extents(ch).x_advance for ch in text)
    return advances + tracking * size * (len(text) - 1)


def _two_lines(ctx, text, size, tracking):
    """The best place to break text in two (the shorter longest line), or None."""
    words = text.split(' ')
    if len(words) < 2:
        return None
    options = [(' '.join(words[:i]), ' '.join(words[i:])) for i in range(1, len(words))]
    return min(options, key=lambda pair: max(_width(ctx, line, size, tracking) for line in pair))


def fit(ctx, style, text, width, height):
    """(lines, size) for text in a width x height space: the largest size that fits,
    on one line or (if allowed and larger) two, else cut short at the smallest size."""
    tracking, size = style['tracking'], style['size']
    best = None
    while True:
        _face(ctx, style, size)
        cap = ctx.text_extents('H').height or size * .7
        if _width(ctx, text, size, tracking) <= width and cap <= height:
            best = ([text], size)
            break
        if size <= style['min_size']:
            break
        size = max(style['min_size'], size * .96)
    if style['lines'] == 2 and (best is None or best[1] < style['size'] * .7):
        size = style['size']
        while True:
            _face(ctx, style, size)
            pair = _two_lines(ctx, text, size, tracking)
            cap = ctx.text_extents('H').height or size * .7
            if pair is None:
                break
            if max(_width(ctx, line, size, tracking) for line in pair) <= width and cap + size * 1.08 <= height:
                if best is None or size > best[1]:
                    best = (list(pair), size)
                break
            if size <= style['min_size']:
                break
            size = max(style['min_size'], size * .96)
    if best is not None:
        return best
    size = style['min_size']
    _face(ctx, style, size)
    cut = text
    while cut and _width(ctx, cut.rstrip() + '…', size, tracking) > width:
        cut = cut[:-1]
    return [(cut.rstrip() + '…') if cut else '…'], size


def render(style, text, width, height):
    """text in its style, fitted to width x height: a transparent ARGB32 cairo surface
    (premultiplied, as GStreamer's overlay rectangles take it)."""
    style = {**STYLE, **style}
    if style['upper']:
        text = text.upper()
    text = ' '.join(str(text).split())
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(width), int(height))
    ctx = cairo.Context(surface)
    shadow = style['shadow']
    edge = style['outline_width'] / 2 if style['outline'] else 0
    pad_x = edge + 2 + (abs(shadow[0]) if shadow else 0)
    pad_y = edge + 2 + (abs(shadow[1]) if shadow else 0)
    lines, size = fit(ctx, style, text, width - 2 * pad_x, height - 2 * pad_y)
    _face(ctx, style, size)
    cap = ctx.text_extents('H').height or size * .7
    gap = size * 1.08
    block = cap + gap * (len(lines) - 1)
    top = (height - block) / 2 + cap
    tracking = style['tracking'] * size
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    for index, line in enumerate(lines):
        line_width = _width(ctx, line, size, style['tracking'])
        x = {'left': pad_x, 'right': width - pad_x - line_width}.get(style['align'], (width - line_width) / 2)
        y = top + index * gap
        ctx.new_path()
        for ch in line:
            ctx.move_to(x, y)
            ctx.text_path(ch)
            x += ctx.text_extents(ch).x_advance + tracking
        path = ctx.copy_path()
        if shadow:
            ctx.save()
            ctx.translate(shadow[0], shadow[1])
            ctx.new_path()
            ctx.append_path(path)
            ctx.set_source_rgba(*shadow[2:])
            if style['outline']:
                ctx.set_line_width(style['outline_width'])
                ctx.stroke_preserve()
            ctx.fill()
            ctx.restore()
        if style['outline']:
            ctx.new_path()
            ctx.append_path(path)
            ctx.set_source_rgb(*style['outline'])
            ctx.set_line_width(style['outline_width'])
            ctx.stroke()
        ctx.new_path()
        ctx.append_path(path)
        ctx.set_source_rgb(*style['color'])
        ctx.fill()
    surface.flush()
    return surface


# ---------------------------------------------------------------- over time

def _back_out(x, s=1.7):
    x -= 1
    return 1 + x * x * ((s + 1) * x + s)


def place(spec, t):
    """Where the overlay's picture goes at promo time t (seconds): (x, y, width, height,
    alpha), or None while it is not shown."""
    if not spec['from'] <= t < spec['to']:
        return None
    x, y, w, h = spec['box']
    sx = sy = alpha = 1.0
    enter, leave = spec['enter'], spec['exit']
    p = (t - spec['from']) / enter['seconds'] if enter['seconds'] > 0 else 1.0
    if p < 1 and enter['kind'] != 'none':
        if enter['kind'] == 'fade':
            alpha = p * p * (3 - 2 * p)
        elif enter['kind'] == 'flip':      # unfolds from a line across its middle, with a little bounce
            sy = max(.02, _back_out(p))
        elif enter['kind'] == 'pop':
            sx = sy = .55 + .45 * _back_out(p, 2.4)
            alpha = min(1.0, p * 3)
    q = (spec['to'] - t) / leave['seconds'] if leave['seconds'] > 0 else 1.0
    if q < 1 and leave['kind'] == 'fade':
        alpha *= max(0.0, q)
    if alpha <= .004:
        return None
    rw, rh = max(2, int(round(w * sx))), max(2, int(round(h * sy)))
    return x + (w - rw) // 2, y + (h - rh) // 2, rw, rh, min(1.0, alpha)


def draw(ctx, overlays, values, t, now=None, cache=None):
    """The overlays at promo time t onto a cairo context of the promo's frame size (the
    page's stills, the build's checks). cache: {(index, text): surface} kept between calls."""
    cache = {} if cache is None else cache
    for index, spec in enumerate(overlays):
        where = place(spec, t)
        text = field_text(spec['field'], values, now)
        if where is None or not text:
            continue
        key = (index, text)
        if key not in cache:
            cache[key] = render(spec['style'], text, spec['box'][2], spec['box'][3])
        surface = cache[key]
        x, y, w, h, alpha = where
        ctx.save()
        ctx.translate(x, y)
        ctx.scale(w / surface.get_width(), h / surface.get_height())
        ctx.set_source_surface(surface, 0, 0)
        ctx.paint_with_alpha(alpha)
        ctx.restore()


def frames_with_text(overlays, duration, step=.1):
    """Promo times (every step seconds) at which some overlay is on screen: for checks."""
    return [round(i * step, 3) for i in range(int(math.ceil(duration / step)))
            if any(place(spec, i * step) for spec in overlays)]
