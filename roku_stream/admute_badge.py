"""The on-screen AD badge (ad mute, admute_link.py): a big "AD" plate, top left,
opposite the station clock, while the detector says an ad is airing.

Shadow mode is for judging the detector by eye, so the badge says SHADOW and how
sure it is; "AD?" is a provisional call, "AD" a confirmed one. Like the crawl, the
plate is rendered once off the streaming thread, and the draw handler is blocked
while there is nothing to show.
"""
from __future__ import annotations

import logging
import threading

import gi

gi.require_version('GstVideo', '1.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import GObject, GstVideo, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

FONT = 'Nimbus Sans Bold'
AMBER, INK, WHITE = (.98, .74, .02), (.06, .06, .06), (1, 1, 1)
FADE = .3  # seconds


def _even(value):
    return max(2, int(round(value / 2)) * 2)


class Plate:
    def __init__(self, gst, label, caption, height):
        self.gst = gst
        big = Pango.FontDescription.from_string(FONT)
        big.set_absolute_size(round(height * .62) * Pango.SCALE)
        small = Pango.FontDescription.from_string(FONT)
        small.set_absolute_size(round(height * .17) * Pango.SCALE)
        main = self._layout(big, label)
        sub = self._layout(small, caption) if caption else None
        _, box = main.get_pixel_extents()
        sub_box = sub.get_pixel_extents()[1] if sub else None
        pad = round(height * .14)
        self.width = _even(max(box.width, sub_box.width if sub_box else 0) + 2 * pad)
        # A diagnostic caption runs to two lines: the plate grows to hold it.
        self.height = _even(max(height, box.height + (sub_box.height if sub_box else 0) + pad))
        provisional = label.endswith('?')
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width, self.height)
        ctx = cairo.Context(surface)
        r = round(height * .12)
        w, h = self.width, self.height
        ctx.new_sub_path()
        ctx.arc(w - r, r, r, -1.5708, 0)
        ctx.arc(w - r, h - r, r, 0, 1.5708)
        ctx.arc(r, h - r, r, 1.5708, 3.1416)
        ctx.arc(r, r, r, 3.1416, 4.7124)
        ctx.close_path()
        if provisional:  # an outline: not sure yet
            ctx.set_source_rgba(0, 0, 0, .55)
            ctx.fill_preserve()
            ctx.set_source_rgb(*AMBER)
            ctx.set_line_width(max(2, round(height * .05)))
            ctx.stroke()
        else:
            ctx.set_source_rgb(*AMBER)
            ctx.fill()
        ink = AMBER if provisional else INK
        top = (h - box.height - (sub_box.height if sub_box else 0)) / 2
        if sub:
            sub.set_alignment(Pango.Alignment.CENTER)
        ctx.set_source_rgb(*ink)
        ctx.move_to((w - box.width) / 2 - box.x, top - box.y)
        PangoCairo.show_layout(ctx, main)
        if sub:
            ctx.set_source_rgb(*(WHITE if provisional else INK))
            ctx.move_to((w - sub_box.width) / 2 - sub_box.x, top + box.height - sub_box.y)
            PangoCairo.show_layout(ctx, sub)
        surface.flush()
        # Premultiplied ARGB (cairo) is what GStreamer's BGRA overlay with the flag expects.
        self.buffer = gst.Buffer.new_wrapped(bytes(surface.get_data()))
        GstVideo.buffer_add_video_meta(self.buffer, GstVideo.VideoFrameFlags.NONE, GstVideo.VideoFormat.BGRA,
                                       self.width, self.height)

    @staticmethod
    def _layout(font, text):
        layout = PangoCairo.create_layout(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)))
        layout.set_font_description(font)
        layout.set_text(text, -1)
        return layout


class AdBadge:
    """Owns the adbadge overlaycomposition element; show() may be called from any thread."""

    def __init__(self, gst, element, width, height):
        self.gst, self.element = gst, element
        self.size = _even(height * .17)
        self.x, self.y = round(width * .045), round(height * .05)
        self.cover = 0               # the crawl's bar along the top reaches this far down: the badge goes below
        self.lock = threading.Lock()
        self.intervals = []          # [(from_ns, to_ns | None, Plate)] on the master clock
        self.plates = {}
        self.failed = False
        self.handler = element.connect('draw', self._draw)
        self.blocked = False
        self._block(True)

    def _block(self, block):
        if block != self.blocked:
            (GObject.signal_handler_block if block else GObject.signal_handler_unblock)(self.element, self.handler)
            self.blocked = block

    def show(self, intervals):
        """[(from_ns, to_ns | None, label, caption)], master running time. [] clears."""
        resolved = []
        for start, end, label, caption in intervals:
            key = (label, caption)
            if key not in self.plates:
                try:
                    self.plates[key] = Plate(self.gst, label, caption, self.size)
                except Exception:
                    logging.getLogger(__name__).exception('Cannot render the AD badge')
                    continue
                if len(self.plates) > 64:
                    self.plates = {key: self.plates[key]}
            resolved.append((start, end, self.plates[key]))
        with self.lock:
            prev = self.intervals
            if (len(resolved) == 1 and resolved[0][1] is None and len(prev) == 1 and prev[0][1] is None):
                # The same badge with new words (AD? -> AD, a diagnostic reason): no new fade-in.
                resolved = [(prev[0][0], None, resolved[0][2])]
            self.intervals = resolved
            if resolved:
                self._block(False)

    def _draw(self, _element, sample):
        try:
            pts = sample.get_buffer().pts
            if pts == self.gst.CLOCK_TIME_NONE:
                return None
            fade = int(FADE * self.gst.SECOND)
            with self.lock:
                if not self.intervals:
                    self._block(True)
                    return None
                for start, end, plate in self.intervals:
                    if start <= pts and (end is None or pts < end):
                        alpha = min(1., (pts - start) / fade)
                        if end is not None:
                            alpha = min(alpha, (end - pts) / fade)
                        rect = GstVideo.VideoOverlayRectangle.new_raw(
                            plate.buffer, self.x, max(self.y, self.cover), plate.width, plate.height,
                            GstVideo.VideoOverlayFormatFlags.PREMULTIPLIED_ALPHA)
                        if alpha < 1:
                            rect.set_global_alpha(max(0., alpha))
                        return GstVideo.VideoOverlayComposition.new(rect)
            return None
        except Exception:
            if not self.failed:
                self.failed = True
                logging.getLogger(__name__).exception('AD badge frame failed')
            return None
