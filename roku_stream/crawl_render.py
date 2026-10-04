"""Draws the crawl (crawl.py) onto master video.

An overlaycomposition element sits after the station clock. The crawl's text is
rendered once, off the streaming thread, into opaque tiles of the bar. Each frame
only places the tiles that are on screen, so a frame costs one blend of the bar
(about 2.6 ms at 720p) and, while the bar is off, nothing: the draw handler is blocked.

The bar slides up when a crawl starts and down when it ends. A crawl with passes runs
its text that many times and then slides away by itself (a bulletin); `finished` then
holds its key. With passes 0 it runs until replaced or cleared.
"""
from __future__ import annotations

from html import escape
import logging
import threading

import gi

gi.require_version('GstVideo', '1.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import GObject, GstVideo, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

TILE = 512
FONT = 'Nimbus Sans Bold'
WHITE, INK = (1, 1, 1), (.06, .06, .06)
# style: band, text, heading, label box (and tags), label text
PALETTE = {
    'warning': ((.62, .05, .07), WHITE, (1, .85, .3), WHITE, (.62, .05, .07)),
    'watch': ((.66, .26, 0), WHITE, (1, .88, .54), WHITE, (.66, .26, 0)),
    'advisory': ((.94, .75, 0), INK, (.45, .05, .05), INK, (.94, .75, 0)),
    'test': ((.18, .25, .32), WHITE, (.62, .83, 1), WHITE, (.18, .25, .32)),
    'station': ((.04, .09, .19), WHITE, (.39, .86, .89), (.39, .86, .89), (.04, .09, .19)),
}
PALETTE.update(national=PALETTE['warning'], urgent=PALETTE['warning'], unknown=PALETTE['advisory'])
SEPARATOR = '  ◆  '
SLIDE = .35  # seconds to slide the bar in or out


def _even(value):
    return max(2, int(round(value / 2)) * 2)


def _hex(rgb):
    return '#%02x%02x%02x' % tuple(round(c * 255) for c in rgb)


class Scene:
    """One crawl, rendered: tiles covering one period (the text and the gap after it)."""

    def __init__(self, gst, content, height, width):
        self.gst = gst
        self.key = content.get('key') or ''
        self.passes = content.get('passes') or 0
        band, text, heading, label_bg, label_fg = PALETTE.get(content['style'], PALETTE['station'])
        font = Pango.FontDescription.from_string(FONT)
        font.set_absolute_size(round(height * .52) * Pango.SCALE)
        parts = []
        for item in content['items']:
            tag = (f'<span background="{_hex(label_bg)}" foreground="{_hex(label_fg)}"> {escape(item["tag"])} </span> '
                   if item.get('tag') else '')
            head = (f'<span foreground="{_hex(heading)}">{escape(item["heading"])}</span> '
                    if item.get('heading') else '')
            parts.append(tag + head + escape(item['text']))
        # A crawl that runs until replaced repeats with the separator between passes; a
        # bulletin ends in plain band.
        body = escape(SEPARATOR).join(parts) + (escape(SEPARATOR) if not self.passes else '')
        layout = self._layout(font, f'<span foreground="{_hex(text)}">{body}</span>')
        _, logical = layout.get_pixel_extents()
        self.text_width = logical.width
        self.period = logical.width + (0 if not self.passes else round(width * .12))
        top = (height - logical.height) / 2
        self.tiles = []
        for x0 in range(0, self.period, TILE):
            span = min(TILE, self.period - x0)
            self.tiles.append((x0, span, self._paint(span, height, band,
                                                     lambda ctx, x0=x0: self._text(ctx, layout, -x0, top))))
        self.blank = self._paint(TILE, height, band, lambda ctx: None)
        self.label = None
        if content.get('label'):
            label_font = font.copy()
            label_font.set_absolute_size(round(height * .44) * Pango.SCALE)
            label = self._layout(label_font, f'<span foreground="{_hex(label_fg)}">{escape(content["label"])}</span>')
            _, box = label.get_pixel_extents()
            pad = round(height * .42)
            # A slanted right edge, as broadcast lower thirds have.
            slant = round(height * .32)
            span = box.width + 2 * pad + slant

            def draw(ctx):
                ctx.move_to(0, 0)
                ctx.line_to(span, 0)
                ctx.line_to(span - slant, height)
                ctx.line_to(0, height)
                ctx.close_path()
                ctx.set_source_rgb(*label_bg)
                ctx.fill()
                self._text(ctx, label, pad, (height - box.height) / 2)
            # Transparent beside the slant, so whichever crawl is passing shows through.
            self.label = (span, self._paint(span, height, None, draw))
        # Text is gone once it has passed behind the label box.
        self.edge = self.label[0] - round(height * .32) if self.label else 0

    @staticmethod
    def _layout(font, markup):
        layout = PangoCairo.create_layout(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)))
        layout.set_font_description(font)
        layout.set_markup(markup, -1)
        return layout

    @staticmethod
    def _text(ctx, layout, x, y):
        ctx.move_to(x, y)
        PangoCairo.show_layout(ctx, layout)

    def _paint(self, width, height, band, draw):
        # Tiles are opaque (the band underlies everything), so cairo's premultiplied ARGB
        # is also straight alpha and their blend needs no conversion.
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        ctx = cairo.Context(surface)
        if band:
            ctx.set_source_rgb(*band)
            ctx.paint()
        draw(ctx)
        surface.flush()
        buffer = self.gst.Buffer.new_wrapped(bytes(surface.get_data()))
        GstVideo.buffer_add_video_meta(buffer, GstVideo.VideoFrameFlags.NONE, GstVideo.VideoFormat.BGRA,
                                       width, height)
        return buffer


class CrawlRenderer:
    """Owns a crawl overlaycomposition element. show() may be called from any thread."""

    def __init__(self, gst, element, width, height):
        self.gst, self.element, self.width, self.height = gst, element, width, height
        # A bar 7.5% of the picture high, inside the action-safe area.
        self.bar = _even(height * .075)
        self.y = height - _even(height * .035) - self.bar
        # A multiple of 60 px/s (120 at 720p) moves whole pixels each frame at 30 and 60 fps.
        self.speed = max(60, round(height / 360) * 60)
        self.slide = int(SLIDE * gst.SECOND)
        self.lock = threading.Lock()
        self.generation = 0
        self.scene = self.pending = self.tail = None
        self.t0 = None
        self.entered = 0
        # Slide state: when the bar started up (and from how far), when it started down.
        self.shown_at = self.hiding_at = None
        self.rise_from = 0.
        self.visible = 0.
        self.hide_requested = False
        self.done_key = None
        # Key of the last crawl that ran all its passes and slid away.
        self.finished = None
        self.failed = False
        self.handler = element.connect('draw', self._draw)
        self.blocked = False
        self._block(True)

    def _block(self, block):
        if block != self.blocked:
            (GObject.signal_handler_block if block else GObject.signal_handler_unblock)(self.element, self.handler)
            self.blocked = block

    def show(self, content, *, restart=True):
        """None slides the bar away. restart=False lets the running pass finish first."""
        with self.lock:
            self.generation += 1
            generation = self.generation
            if content is None:
                self.pending = None
                if self.scene is not None:
                    self.hide_requested = True
                return
        threading.Thread(target=self._render, args=(content, restart, generation),
                         name='crawl-render', daemon=True).start()

    def _render(self, content, restart, generation):
        try:
            scene = Scene(self.gst, content, self.bar, self.width)
        except Exception:
            logging.getLogger(__name__).exception('Cannot render the crawl')
            return
        with self.lock:
            if generation != self.generation:
                return
            if restart or self.scene is None or self.hiding_at is not None or self.hide_requested:
                if self.scene is None:
                    self.shown_at, self.rise_from = None, 0.
                elif self.hiding_at is not None:
                    self.shown_at, self.rise_from = None, self.visible  # back up from where it was
                self.scene, self.pending, self.tail, self.t0, self.entered = scene, None, None, None, 0
                self.hiding_at, self.hide_requested, self.done_key = None, False, None
            else:
                self.pending = scene
            self._block(False)

    def _draw(self, _element, sample):
        try:
            pts = sample.get_buffer().pts
            with self.lock:
                return self._compose(pts) if pts != self.gst.CLOCK_TIME_NONE else None
        except Exception:
            if not self.failed:
                self.failed = True
                logging.getLogger(__name__).exception('Crawl frame failed')
            return None

    def _base(self, pts, t0):
        """Where copy 0 of a scene started at t0 is now."""
        return self.width - (pts - t0) * self.speed // self.gst.SECOND

    def _compose(self, pts):
        scene = self.scene
        if scene is None:
            return None
        if self.t0 is None or pts < self.t0:
            self.t0, self.entered = pts, 0
        if self.shown_at is None or pts < self.shown_at:
            self.shown_at = pts - int(self.rise_from * self.slide)
        base = self._base(pts, self.t0)
        # Copies whose left edge is on screen; a bulletin has no more than its passes.
        entered = max(0, -(-(self.width - base) // scene.period))
        if scene.passes:
            entered = min(entered, scene.passes)
        if self.pending is not None and entered > self.entered:
            # The next copy just came in at the right edge: it is the new crawl instead.
            x = base + (entered - 1) * scene.period
            self.tail = (scene, self.t0, entered - 2) if entered >= 2 else None
            scene, self.scene, self.pending = self.pending, self.pending, None
            self.t0 = pts - (self.width - x) * self.gst.SECOND // self.speed
            base, entered = self._base(pts, self.t0), 1
        self.entered = entered
        if self.hide_requested and self.hiding_at is None:
            self.hiding_at = pts
        if (scene.passes and self.hiding_at is None and entered == scene.passes
                and base + (scene.passes - 1) * scene.period + scene.text_width <= scene.edge):
            self.hiding_at, self.done_key = pts, scene.key  # every pass has run
        visible = min(1., (pts - self.shown_at) / self.slide)
        if self.hiding_at is not None:
            visible = min(visible, 1. - (pts - self.hiding_at) / self.slide)
            if visible <= 0:
                if self.done_key is not None:
                    self.finished = self.done_key
                self.scene = self.pending = self.tail = None
                self.shown_at = self.hiding_at = None
                self.hide_requested, self.done_key, self.visible = False, None, 0.
                self._block(True)
                return None
        self.visible = visible = max(0., visible)
        eased = visible * visible * (3 - 2 * visible)
        y = self.y + round((1 - eased) * (self.height - self.y))
        rectangles, left, blank = [], self.width, scene.blank
        if self.tail is not None:
            old, t0, last = self.tail
            old_base = self._base(pts, t0)
            if old_base + (last + 1) * old.period <= 0:
                self.tail = None
            else:
                left = self._copies(rectangles, old, old_base, range(max(0, (-old_base) // old.period), last + 1))
                blank = old.blank
        left = min(left, self._copies(rectangles, scene, base, range(max(0, (-base) // scene.period), entered)))
        while left > 0:  # Before the first copy has crossed: the bare band.
            left -= TILE
            rectangles.insert(0, (blank, left, TILE))
        right = base + entered * scene.period
        while right < self.width:  # After a bulletin's last pass: the bare band.
            rectangles.append((scene.blank, right, TILE))
            right += TILE
        opaque = GstVideo.VideoOverlayFormatFlags.NONE
        rectangles = [(buffer, x, width, opaque) for buffer, x, width in rectangles]
        if scene.label:
            rectangles.append((scene.label[1], 0, scene.label[0], GstVideo.VideoOverlayFormatFlags.PREMULTIPLIED_ALPHA))
        composition = None
        for buffer, x, width, flags in rectangles:
            rectangle = GstVideo.VideoOverlayRectangle.new_raw(buffer, x, y, width, self.bar, flags)
            if composition is None:
                composition = GstVideo.VideoOverlayComposition.new(rectangle)
            else:
                composition.add_rectangle(rectangle)
        return composition

    def _copies(self, rectangles, scene, base, copies):
        """Adds the on-screen tiles of these copies; returns the leftmost x drawn."""
        left = self.width
        for k in copies:
            origin = base + k * scene.period
            left = min(left, origin)
            for x0, width, buffer in scene.tiles:
                x = origin + x0
                if x < self.width and x + width > 0:
                    rectangles.append((buffer, x, width))
        return left
