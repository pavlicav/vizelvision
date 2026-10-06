"""My ads on master (my_ads.py): the operator's own ads over a break ad mute has muted.

While the programme on air is muted (ad mute On, its gain under one half), master shows
one of the operator's ads in its place, with its sound, then the next; with none left
that may play, the break card under the usual break sound (silence or Cairo radio). The
muted programme stays on screen small (picture in picture, with a LIVE tab), so the
operator sees the show come back and can say "It's the show".

It all happens where the gain is applied, at release from the programme delay
(MasterMedia.release_programme), so a break starts and ends on the gain's own frames,
and "It's the show" ends it as fast as it brings the sound back. Ads are decoded ahead
in pipelines of their own (Reel) and pulled at master's pace: a slow ad holds its last
frame, a failed one gives way to the next or the card, and neither holds the programme
up. Cueing, the card and the play log are a helper thread's.

Station promos (promos.py) share the break: when one is due (none for `every` minutes),
the break opens with it, or the next item is it; with `fill`, they stand in when no ad is
left, each once a break. A promo's live text (the time, the temperature, the programme)
is blended into its frames as they decode (PromoReel). With My ads off, a due promo still
plays, and the break then carries on as ad mute has it ('pass': nothing replaced).
"""
from __future__ import annotations

from array import array
from collections import deque
import logging
from pathlib import Path
import re
import threading
import time

import gi

gi.require_version('GstVideo', '1.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import GstVideo, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

from .admute_link import apply_gain
from .my_ads import Rotation, allowed, append_play, card_file, counts, read_plays
from .programme_delay import retimable
from . import promo_overlay
from .promos import due as promo_due, last_promo, readiness, switched_on

SECOND = 1_000_000_000
RATE = 48000
FRAME_BYTES = 8                      # F32LE stereo
LOG = logging.getLogger(__name__)


def _even(value):
    return max(0, int(round(value / 2)) * 2)


def planes(buffer, width, height):
    """[(offset, stride)] of an I420 buffer's Y, U and V planes (its video meta's, if any)."""
    meta = GstVideo.buffer_get_video_meta(buffer)
    if meta is not None:
        return list(zip(list(meta.offset)[:3], list(meta.stride)[:3]))
    cw, ch = (width + 1) // 2, (height + 1) // 2
    ys, cs = (width + 3) & ~3, (cw + 3) & ~3
    return [(0, ys), (ys * height, cs), (ys * height + cs * ch, cs)]


def yuv(r, g, b):
    """BT.709, studio range, from 0-255 RGB (master's caps are bt709)."""
    return (round(16 + .1826 * r + .6142 * g + .0620 * b), round(128 - .1006 * r - .3386 * g + .4392 * b),
            round(128 + .4392 * r - .3989 * g - .0403 * b))


def to_i420(bgra, stride, width, height):
    """An opaque cairo ARGB32 picture as I420 rows: ([Y rows], [U rows], [V rows])."""
    def px(x, y):
        i = y * stride + x * 4
        return bgra[i + 2], bgra[i + 1], bgra[i]
    ys = [bytes(min(255, max(0, yuv(*px(x, y))[0])) for x in range(width)) for y in range(height)]
    us, vs = [], []
    for y in range(0, height, 2):
        u, v = bytearray(), bytearray()
        for x in range(0, width, 2):
            quad = [yuv(*px(x + dx, y + dy)) for dx in (0, 1) for dy in (0, 1)]
            u.append(min(255, max(0, round(sum(q[1] for q in quad) / 4))))
            v.append(min(255, max(0, round(sum(q[2] for q in quad) / 4))))
        us.append(bytes(u))
        vs.append(bytes(v))
    return ys, us, vs


class Pip:
    """The muted programme, small in a corner: nearest-neighbour rows (every f-th pixel of
    every f-th line), a white frame and a LIVE tab, written straight into an I420 frame.
    About 1.5 ms a frame at 720p, only while a break is replaced."""
    FACTORS = {'small': 5, 'medium': 4, 'large': 3}
    BORDER = 4
    EDGE = yuv(235, 235, 235)
    TAB = (204, 22, 22)

    def __init__(self, gst, width, height, corner, size):
        self.gst, self.W, self.H = gst, width, height
        self.f = f = self.FACTORS[size]
        self.w, self.h = (width // f) & ~1, (height // f) & ~1
        b = self.BORDER
        mx, my = _even(width * .045), _even(height * .05)
        x = mx + b if corner.endswith('left') else width - mx - b - self.w
        if corner.startswith('top'):    # below the AD badge (left) or the station clock (right)
            y = my + _even(height * (.19 if corner.endswith('left') else .09)) + b
        else:                           # above the crawl's bar
            y = height - _even(height * .035) - _even(height * .075) - _even(height * .03) - b - self.h
        self.x, self.y = _even(x), _even(y)
        self.tab = self._tab()

    def _tab(self):
        h = _even(max(10, self.h * .14))
        if h > self.h // 3:
            return None          # a corner too small for it
        font = Pango.FontDescription.from_string('Nimbus Sans Bold')
        font.set_absolute_size(round(h * .64) * Pango.SCALE)
        layout = PangoCairo.create_layout(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)))
        layout.set_font_description(font)
        layout.set_text('LIVE', -1)
        _, box = layout.get_pixel_extents()
        w = _even(box.width + 2 * round(h * .4))
        if w > self.w // 2:
            return None
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        ctx = cairo.Context(surface)
        ctx.set_source_rgb(*(c / 255 for c in self.TAB))
        ctx.paint()
        ctx.set_source_rgb(1, 1, 1)
        ctx.move_to((w - box.width) / 2 - box.x, (h - box.height) / 2 - box.y)
        PangoCairo.show_layout(ctx, layout)
        surface.flush()
        return w, h, to_i420(bytes(surface.get_data()), surface.get_stride(), w, h)

    def draw(self, out, live):
        """Frames the programme picture (live: an I420 frame of the output size) into out."""
        gst, W, H, f, b = self.gst, self.W, self.H, self.f, self.BORDER
        o = planes(out, W, H)
        if live is not None:
            s = planes(live, W, H)
            ok, info = live.map(gst.MapFlags.READ)
            if ok:
                try:
                    src = info.data
                    if len(src) >= s[2][0] + s[2][1] * ((H + 1) // 2):
                        for p, scale in enumerate((1, 2, 2)):
                            (o_off, o_str), (s_off, s_str) = o[p], s[p]
                            x, y, w, h, e = self.x // scale, self.y // scale, self.w // scale, self.h // scale, b // scale
                            side = bytes((self.EDGE[p],)) * e
                            full = bytes((self.EDGE[p],)) * (w + 2 * e)
                            for r in range(e):
                                out.fill(o_off + (y - e + r) * o_str + x - e, full)
                                out.fill(o_off + (y + h + r) * o_str + x - e, full)
                            row = W // scale
                            for r in range(h):
                                at = s_off + r * f * s_str
                                out.fill(o_off + (y + r) * o_str + x - e, side + src[at:at + row:f][:w] + side)
                finally:
                    live.unmap(info)
        if self.tab is None:
            return
        tw, th, rows = self.tab
        inset = _even(self.h * .05)
        for p, scale in enumerate((1, 2, 2)):
            o_off, o_str = o[p]
            x, y = (self.x + inset) // scale, (self.y + inset) // scale
            for r, line in enumerate(rows[p]):
                out.fill(o_off + (y + r) * o_str + x, line)


def load_picture(gst, path, caps):
    """A picture file as one I420 frame of master's size (letterboxed), for the break card."""
    pipeline = gst.parse_launch('filesrc name=src ! decodebin ! videoconvert ! videoscale add-borders=true '
                                f'! videoconvert ! {caps} ! appsink name=sink sync=false max-buffers=1 drop=false')
    pipeline.get_by_name('src').set_property('location', str(path))
    try:
        if pipeline.set_state(gst.State.PLAYING) == gst.StateChangeReturn.FAILURE:
            raise RuntimeError('cannot open it')
        sample = pipeline.get_by_name('sink').emit('try-pull-sample', 10 * SECOND)
        if sample is None:
            message = pipeline.get_bus().pop_filtered(gst.MessageType.ERROR)
            raise RuntimeError(message.parse_error()[0].message if message else 'no picture in it')
        return sample.get_buffer().copy_deep()
    finally:
        pipeline.set_state(gst.State.NULL)


class Reel:
    """One ad, decoded ahead in its own playbin (one picture, one sound, nothing else) into
    appsinks that block when full, and pulled by ad time on the programme-delay thread:
    frame() and sound() never wait. cue(), poll() and close() are the helper thread's."""
    VIDEO_BUFFERS = 12
    AUDIO_BUFFERS = 256

    def __init__(self, gst, ad, path, video_caps, audio_caps, live=False):
        self.gst, self.ad, self.path = gst, ad, Path(path)
        self.failed = None
        self.pending = self.shown = None
        self.video_done = False
        self.pcm, self.pcm0, self.next_frame = bytearray(), None, None
        caps = re.sub(r'framerate=[^,]*,?', '', video_caps)   # frames at the ad's own rate
        sink = 'sync=false emit-signals=false enable-last-sample=false drop=false'
        level = 10 ** (((ad.get('gain_db') or 0) + (ad.get('trim_db') or 0)) / 20)
        self.pipeline = gst.ElementFactory.make('playbin', None)
        self.pipeline.set_property('uri', Path(path).resolve().as_uri())
        self.pipeline.set_property('flags', 0x1 | 0x2)   # video and audio: no subtitles or visualisations
        # live: text blended into the frames as they decode (a promo's, PromoReel). The caps
        # after it keep it blending, not attaching the text as meta.
        overlay = f'overlaycomposition name=live ! {caps} ! ' if live else ''
        vbin = gst.parse_bin_from_description(
            'videoconvert ! deinterlace ! videoscale add-borders=true ! videoconvert '
            f'! {caps} ! {overlay}appsink name=video max-buffers={self.VIDEO_BUFFERS} {sink}', True)
        abin = gst.parse_bin_from_description(
            f'audioconvert ! audioresample ! volume volume={level:.6f} ! audioconvert ! {audio_caps} '
            f'! appsink name=audio max-buffers={self.AUDIO_BUFFERS} {sink}', True)
        self.pipeline.set_property('video-sink', vbin)
        self.pipeline.set_property('audio-sink', abin)
        self.video, self.audio = vbin.get_by_name('video'), abin.get_by_name('audio')
        self.live = vbin.get_by_name('live') if live else None
        self.bus = self.pipeline.get_bus()

    def cue(self, timeout=8.):
        """Starts decoding and waits for the first frame (helper thread). False: it won't play."""
        gst = self.gst
        if self.pipeline.set_state(gst.State.PLAYING) == gst.StateChangeReturn.FAILURE:
            self.failed = 'cannot start it'
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.poll()
            if self.failed:
                return False
            sample = self.video.emit('try-pull-sample', 100_000_000)
            if sample is not None:
                self.pending = self._timed(sample)
                return True
            if self.video.get_property('eos'):
                self.failed = 'no picture in it'
                return False
        self.failed = 'its first picture took too long'
        return False

    def poll(self):
        message = self.bus.pop_filtered(self.gst.MessageType.ERROR)
        if message is not None and not self.failed:
            self.failed = message.parse_error()[0].message

    def _timed(self, sample):
        gst, buffer = self.gst, sample.get_buffer()
        pts = sample.get_segment().to_running_time(gst.Format.TIME, buffer.pts)
        if pts == gst.CLOCK_TIME_NONE:
            pts = self.shown[0] + self.shown[2] if self.shown else 0
        duration = buffer.duration if buffer.duration not in (gst.CLOCK_TIME_NONE, 0) else SECOND // 30
        return pts, buffer, duration

    def frame(self, t):
        """The ad's picture at ad time t (ns): its latest frame due by then."""
        while True:
            if self.pending is None and not self.video_done:
                sample = self.video.emit('try-pull-sample', 0)
                if sample is None:
                    self.video_done = self.video.get_property('eos')
                    break
                self.pending = self._timed(sample)
            if self.pending is not None and (self.shown is None or self.pending[0] <= t + 2_000_000):
                self.shown, self.pending = self.pending, None
                continue
            break
        return self.shown[1] if self.shown else None

    def ended(self, t):
        return self.video_done and self.pending is None and (self.shown is None or t >= self.shown[0] + self.shown[2])

    def sound(self, t, size):
        """size bytes of the ad's sound from ad time t (ns); silence where there is none (yet)."""
        start = round(t * RATE / SECOND)
        if self.next_frame is not None and abs(start - self.next_frame) <= 2:
            start = self.next_frame          # programme buffers are contiguous: so is the ad's sound
        count = size // FRAME_BYTES
        end = start + count
        self.next_frame = end
        while self.pcm0 is None or self.pcm0 + len(self.pcm) // FRAME_BYTES < end:
            sample = self.audio.emit('try-pull-sample', 0)
            if sample is None:
                break
            pts, buffer, _ = self._timed(sample)
            at, data = round(pts * RATE / SECOND), buffer.extract_dup(0, buffer.get_size())
            if self.pcm0 is None or not self.pcm:
                self.pcm0, self.pcm = at, bytearray(data)
                continue
            have = self.pcm0 + len(self.pcm) // FRAME_BYTES
            if at > have + 96:                  # a gap in the ad's sound: silence
                self.pcm += bytes((at - have) * FRAME_BYTES)
            elif at < have - 96:                # an overlap: keep what came first
                data = data[(have - at) * FRAME_BYTES:]
            self.pcm += data
        out = bytearray(size)
        if self.pcm0 is not None:
            a, b = max(start, self.pcm0), min(end, self.pcm0 + len(self.pcm) // FRAME_BYTES)
            if b > a:
                out[(a - start) * FRAME_BYTES:(b - start) * FRAME_BYTES] = \
                    self.pcm[(a - self.pcm0) * FRAME_BYTES:(b - self.pcm0) * FRAME_BYTES]
            used = min(len(self.pcm) // FRAME_BYTES, max(0, end - self.pcm0))
            del self.pcm[:used * FRAME_BYTES]
            self.pcm0 += used
        return bytes(out)

    def close(self):
        self.pipeline.set_state(self.gst.State.NULL)


class PromoReel(Reel):
    """A station promo (promos.py), decoded as an ad is, with its live text (the time, the
    temperature, the programme on air) blended into its frames as they decode, by
    GStreamer's overlaycomposition on the reel's own thread. promo_overlay.py draws each
    text once; every frame only places it (an overlay rectangle) and fades or unfolds it."""

    def __init__(self, gst, promo, path, video_caps, audio_caps, values):
        self.overlays, self.values = promo['overlays'], values
        self.pixels = {}                     # (overlay, text) -> a BGRA buffer of its box
        self.draw_failed = None
        super().__init__(gst, promo, path, video_caps, audio_caps, live=bool(promo['overlays']))
        self.drawing = self.live.connect('draw', self._draw) if self.live is not None else None

    def _pixels(self, index, spec, text):
        key = (index, text)
        pixels = self.pixels.get(key)
        if pixels is None:
            surface = promo_overlay.render(spec['style'], text, spec['box'][2], spec['box'][3])
            pixels = self.gst.Buffer.new_wrapped(bytes(surface.get_data()))
            GstVideo.buffer_add_video_meta(pixels, GstVideo.VideoFrameFlags.NONE, GstVideo.VideoFormat.BGRA,
                                           surface.get_width(), surface.get_height())
            if len(self.pixels) > 16:        # the time moves on: old minutes go
                self.pixels.clear()
            self.pixels[key] = pixels
        return pixels

    def _draw(self, _element, sample):
        """The text on the frame at its promo time, or None (overlaycomposition's draw)."""
        try:
            buffer = sample.get_buffer()
            at = sample.get_segment().to_stream_time(self.gst.Format.TIME, buffer.pts)
            if at in (None, self.gst.CLOCK_TIME_NONE) or at < 0:
                return None
            t, rectangles = at / SECOND, []
            for index, spec in enumerate(self.overlays):
                where = promo_overlay.place(spec, t)
                text = where and promo_overlay.field_text(spec['field'], self.values)
                if not text:
                    continue
                x, y, w, h, alpha = where
                rectangle = GstVideo.VideoOverlayRectangle.new_raw(
                    self._pixels(index, spec, text), x, y, w, h, GstVideo.VideoOverlayFormatFlags.PREMULTIPLIED_ALPHA)
                if alpha < 1:
                    rectangle.set_global_alpha(alpha)
                rectangles.append(rectangle)
            if not rectangles:
                return None
            composition = GstVideo.VideoOverlayComposition.new(rectangles[0])
            for rectangle in rectangles[1:]:
                composition.add_rectangle(rectangle)
            return composition
        except Exception as exc:
            if self.draw_failed is None:
                self.draw_failed = str(exc)
                LOG.exception('Station promo %r: its live text failed', self.ad.get('name'))
            return None

    def close(self):
        if self.drawing is not None:
            self.live.disconnect(self.drawing)
            self.drawing = None
        super().close()


class AdBreak:
    """The break as master shows it (see the module doc). picture() and sound() run on the
    programme-delay thread; configure() and status() on the worker's; cueing, the card and
    the play log on a helper thread of its own."""
    TICK = .2
    LEAVE_OUT = 600                  # seconds an ad (or promo) that would not play is left out
    HISTORY = 7 * 86400              # plays remembered for limits (the longest is a week)

    def __init__(self, output, folder, plays_path):
        self.output, self.gst = output, output.gst
        self.W, self.H = output.width, output.height
        self.caps = re.sub(r'framerate=[^,]*,?', '', output.video_caps)
        self.folder, self.plays_path = Path(folder), Path(plays_path)
        self.lock = threading.Lock()
        self.settings, self.active, self.ads_on, self.admute = None, False, False, None
        self.pip, self.pip_key = None, None
        self.card, self.card_key, self.card_error = None, None, None
        c = ((self.W + 1) // 2) * ((self.H + 1) // 2)
        self.blank = self.gst.Buffer.new_wrapped(bytes((16,)) * (self.W * self.H) + bytes((128,)) * (2 * c))
        # Station promos (promos.py): settings, live values, the library by id, its folders
        self.promos, self.promos_on = None, False
        self.promo_values, self.library = {}, {}
        self.library_folder = self.variants_folder = None
        # The programme-delay thread's
        self.state = 'idle'                  # idle | ad | promo | card | pass (my ads off: nothing replaced)
        self.reel = self.reel_kind = self.reel_start = None
        self.break_start = self.break_end = None
        self.card_since = None               # (due, wall) while the card is up
        self.now_playing = None              # (ad id, wall) while an ad airs
        self.promo_playing = None            # (promo id, wall) while a promo airs
        self.break_promos = set()            # promos aired in this break: each once at most
        self.last_due = None
        self.failed_once = False
        # Shared
        self.cued = None                     # the next ad, decoded up to its first frames
        self.cued_promo = None               # the next promo, likewise
        self.rotation, self.promo_rotation = Rotation(), Rotation()
        self.left_out = {}                   # ad or promo id -> (until, why): it would not play
        self.done, self.log = deque(), deque()
        # The helper's
        self.plays = read_plays(self.plays_path, time.time() - self.HISTORY)
        self.last_promo = last_promo(self.plays)   # when the last promo that counted started
        self.wake, self.stopping = threading.Event(), threading.Event()
        self.thread = threading.Thread(target=self._run, name='my-ads', daemon=True)
        self.thread.start()

    # ------------------------------------------------------------ the worker's
    def configure(self, settings, admute):
        """my_ads settings (or None: unreadable) and ad mute's; once a second."""
        self.settings, self.admute = settings, admute
        self.ads_on = bool(settings and settings['enabled'])
        self._activate()
        pip = settings and settings['pip']
        key = pip and pip['enabled'] and (pip['corner'], pip['size'])
        if key != self.pip_key:
            try:
                self.pip = Pip(self.gst, self.W, self.H, *key) if key else None
            except Exception:
                LOG.exception('Cannot draw the picture-in-picture frame')
                self.pip = None
            self.pip_key = key

    def configure_promos(self, snapshot):
        """Station promos (promos.Promos.snapshot(), or None: unreadable); once a second."""
        snapshot = snapshot or {}
        settings = snapshot.get('settings')
        self.promos, self.promo_values = settings, snapshot.get('values') or {}
        self.library = {p['id']: p for p in snapshot.get('promos') or []}
        self.library_folder, self.variants_folder = snapshot.get('library'), snapshot.get('variants')
        self.promos_on = bool(settings and settings['enabled'])
        self._activate()
        for reel in (self.reel, self.cued_promo):
            if isinstance(reel, PromoReel):
                reel.values = self.promo_values

    def _activate(self):
        self.active = bool((self.admute or {}).get('mode') == 'on' and (self.ads_on or self.promos_on))

    def status(self):
        reel, kind, cued, cued_promo = self.reel, self.reel_kind, self.cued, self.cued_promo
        playing = self.now_playing if kind == 'ad' else self.promo_playing
        now = time.time()
        on_air = None
        if reel is not None:
            position = None
            if self.last_due is not None and self.reel_start is not None:
                position = round(max(0., (self.last_due - self.reel_start) / SECOND), 1)
            on_air = {'id': reel.ad['id'], 'name': reel.ad.get('name'), 'duration': reel.ad['duration'],
                      'position': position, 'since': playing and round(playing[1], 1)}
        with self.lock:
            left_out = {k: why for k, (until, why) in self.left_out.items() if until > now}
        settings = self.promos
        return {'active': self.active, 'state': self.state, 'ads_on': self.ads_on,
                'ad': on_air if kind == 'ad' else None, 'promo': on_air if kind == 'promo' else None,
                'card_since': self.card_since and round(self.card_since[1], 1),
                'cued': cued and cued.ad['id'], 'card': {'ready': self.card is not None, 'error': self.card_error},
                'left_out': left_out,
                'promos': {'active': self.active and self.promos_on, 'cued': cued_promo and cued_promo.ad['id'],
                           'last': self.last_promo and round(self.last_promo, 1),
                           'due': bool(settings) and promo_due(settings, self.last_promo, now),
                           'draw_failed': next((r.draw_failed for r in (reel, cued_promo)
                                                if isinstance(r, PromoReel) and r.draw_failed), None)}}

    def close(self):
        self.stopping.set()
        self.wake.set()
        self.thread.join(timeout=2)
        for reel in (self.reel, self.cued, self.cued_promo, *self.done):
            if reel is not None:
                reel.close()

    # ------------------------------------------------------------ the programme-delay thread's
    def _muted(self, pts, route):
        """Is the programme at this moment muted by ad mute? None: no way to tell (a filler)."""
        if not self.active:
            return False
        if not route or pts is None:
            return None
        tap, offset, _ = route
        if tap is None:
            return False
        at = pts + offset
        return (tap.link.peek(tap.key, at) if hasattr(tap, 'link') else tap.gain(at)) < .5

    def _follow(self, due, muted):
        if muted is None:
            return
        if muted and self.state == 'idle' and (self.break_end is None or due >= self.break_end):
            self.break_start = due
            self.break_promos = set()
            self._next(due)
        elif not muted and self.state != 'idle' and due >= self.break_start:
            if self.reel is not None:
                self._finish(due, cut=True)
            self._card_off(due)
            self.state, self.break_end = 'idle', due

    def _promo_wanted(self, now):
        """Should the cued promo go on next: one is due, or (fill) no ad is left to show."""
        promo, settings = self.cued_promo, self.promos
        if (not self.promos_on or not settings or promo is None or promo.failed
                or promo.ad['id'] in self.break_promos):
            return False
        if self.promo_playing is None and promo_due(settings, self.last_promo, now):
            return True
        return settings['fill'] and (not self.ads_on or self.cued is None)

    def _next(self, due):
        """What goes on air at due: the cued promo when one is due (or filling in), else the
        cued ad, else the card; with my ads off, the programme as ad mute has it ('pass')."""
        now = time.time()
        with self.lock:
            reel = kind = None
            if self._promo_wanted(now):
                reel, kind, self.cued_promo = self.cued_promo, 'promo', None
                self.promo_rotation.played(reel.ad['id'])
                self.break_promos.add(reel.ad['id'])
            elif self.ads_on and self.cued is not None:
                reel, kind, self.cued = self.cued, 'ad', None
                self.rotation.played(reel.ad['id'])
        if reel is not None and not reel.failed:
            self._card_off(due)
            self.reel, self.reel_kind, self.reel_start, self.state = reel, kind, due, kind
            if kind == 'promo':
                self.promo_playing = (reel.ad['id'], now)
            else:
                self.now_playing = (reel.ad['id'], now)
        else:
            if reel is not None:
                self.done.append(reel)
            self.reel = self.reel_kind = None
            if self.ads_on:
                self.state = 'card'
                if self.card_since is None:
                    self.card_since = (due, now)
            else:
                self.state = 'pass'
        self.wake.set()   # cue the one after

    def _finish(self, due, cut=False):
        reel, kind, self.reel, self.reel_kind = self.reel, self.reel_kind, None, None
        aired = max(0., (due - self.reel_start) / SECOND)
        length = reel.ad['duration']
        complete = not cut and not reel.failed
        playing = self.promo_playing if kind == 'promo' else self.now_playing
        row = {'kind': kind, 'id': reel.ad['id'], 'name': reel.ad.get('name'),
               'at': round(playing[1] if playing else time.time() - aired, 1),
               'seconds': round(aired, 1), 'length': length, 'complete': complete,
               'counted': complete or counts(aired, length)}
        if reel.failed:
            row['error'] = str(reel.failed)[:200]
        if kind == 'promo':
            self.promo_playing = None
            if row['counted']:
                self.last_promo = row['at']
        else:
            self.now_playing = None
        self.log.append(row)
        self.done.append(reel)

    def _card_off(self, due):
        if self.card_since is not None:
            since, wall = self.card_since
            self.log.append({'kind': 'card', 'at': round(wall, 1), 'seconds': round(max(0, due - since) / SECOND, 1)})
            self.card_since = None

    def picture(self, live, due, pts, route):
        """The frame master shows at due in place of the programme's (live), or None."""
        self._follow(due, self._muted(pts, route))
        if self.state == 'idle':
            return None
        self.last_due = due
        base = None
        if self.reel is not None:
            t = due - self.reel_start
            if not self.reel.failed:
                base = self.reel.frame(t)
            if self.reel.failed or self.reel.ended(t):
                self._finish(due)
                self._next(due)
                base = self.reel.frame(0) if self.reel is not None else None
        elif self._promo_wanted(time.time()) or (self.ads_on and self.cued is not None):
            self._next(due)                  # the card (or the muted programme) gives way: one is ready
            base = self.reel.frame(0) if self.reel is not None else None
        if self.state == 'pass':
            return None
        if base is None:
            base = self.card if self.card is not None else self.blank
        try:
            if self.pip is None:
                return retimable(self.gst, base)
            out = base.copy_deep()
            self.pip.draw(out, live)
            return out
        except Exception:
            if not self.failed_once:
                self.failed_once = True
                LOG.exception('My ads: the picture in picture failed')
            return retimable(self.gst, base)

    def sound(self, due, at, gain_at, scaled):
        """The break's sound for one programme audio buffer (scaled: already faded by ad
        mute's gain): the ad's or promo's, crossfaded with the programme's. None: the usual
        break bed."""
        if not self.active:
            return None
        end = at + len(scaled) * SECOND // (RATE * FRAME_BYTES)
        self._follow(due, gain_at((at + end) // 2) < .5)
        if self.reel is None:
            return None
        mine = self.reel.sound(due - self.reel_start, len(scaled))
        if max(gain_at(at), gain_at(end)) <= 1e-4:
            return mine
        mine = apply_gain(mine, at, RATE, 2, lambda p: 1. - gain_at(p)) or mine
        programme, ad = array('f'), array('f')
        programme.frombytes(scaled)
        ad.frombytes(mine)
        return array('f', (a + b for a, b in zip(programme, ad))).tobytes()

    # ------------------------------------------------------------ the helper's
    def _run(self):
        failures = 0
        while not self.stopping.is_set():
            self.wake.wait(self.TICK)
            self.wake.clear()
            try:
                self._help()
                failures = 0
            except Exception:
                failures += 1
                if failures in (1, 100):
                    LOG.exception('My ads helper failed')

    def _help(self):
        while self.done:
            self.done.popleft().close()
        while self.log:
            row = self.log.popleft()
            try:
                append_play(self.plays_path, row)
            except OSError as exc:
                LOG.warning('Cannot log a play of my ads: %s', exc)
            self.plays.append(row)
        cutoff = time.time() - self.HISTORY
        if self.plays and self.plays[0].get('at', 0) < cutoff:
            self.plays = [p for p in self.plays if p.get('at', 0) >= cutoff]
        for reel in (self.reel, self.cued, self.cued_promo):
            if reel is not None and not reel.failed:
                reel.poll()
                if reel.failed:
                    LOG.warning('%s %r failed %s: %s', 'Station promo' if isinstance(reel, PromoReel) else 'My ad',
                                reel.ad.get('name') or reel.ad['id'], 'on air' if reel is self.reel else 'while cued',
                                reel.failed)
        self._load_card()
        self._cue()
        self._cue_promo()

    def _load_card(self):
        settings = self.settings
        if not settings:
            return
        path = self.folder / card_file(settings)
        try:
            key = (str(path), path.stat().st_mtime_ns)
        except OSError:
            key = (str(path), None)
        if key == self.card_key:
            return
        self.card_key = key
        if key[1] is None:
            self.card_error = 'The break card is not drawn yet'
            return
        try:
            self.card, self.card_error = load_picture(self.gst, path, self.caps), None
        except Exception as exc:
            self.card_error = f'Cannot show the break card: {exc}'
            LOG.warning('%s', self.card_error)

    def _cue(self):
        settings, now, playing = self.settings, time.time(), self.now_playing
        with self.lock:
            cued = self.cued
        if not self.active or not self.ads_on or not settings:
            if cued is not None:
                self._drop(cued)
            return
        # The ad on air counts towards its limit while it plays.
        plays = self.plays + ([{'kind': 'ad', 'id': playing[0], 'at': playing[1], 'counted': True}] if playing else [])
        ads = {a['id']: a for a in settings['ads']}
        if cued is not None:
            ad = ads.get(cued.ad['id'])
            same = ad is not None and all(ad.get(k) == cued.ad.get(k) for k in ('file', 'gain_db', 'trim_db'))
            if same and not cued.failed and allowed(ad, plays, now):
                return
            LOG.info('My ads: %r is no longer next (%s)', cued.ad.get('name') or cued.ad['id'],
                     'failed' if cued.failed else 'changed' if ad is not None and not same else 'removed' if ad is None
                     else 'over its limit or switched off')
            self._drop(cued)
        with self.lock:
            self.left_out = {k: v for k, v in self.left_out.items() if v[0] > now}
            ad = self.rotation.pick(settings, plays, now, skip=set(self.left_out))
        if ad is None:
            return
        reel = None
        try:
            path = self.folder / ad['file']
            if not path.is_file():
                raise RuntimeError('its file is missing')
            reel = Reel(self.gst, ad, path, self.caps, self.output.audio_caps)
            if not reel.cue():
                raise RuntimeError(reel.failed)
        except Exception as exc:
            with self.lock:
                self.left_out[ad['id']] = (now + self.LEAVE_OUT, str(exc)[:200])
            LOG.warning('My ad %r is left out for %d minutes: %s', ad.get('name') or ad['id'], self.LEAVE_OUT // 60, exc)
            if reel is not None:
                reel.close()
            return
        with self.lock:
            if self.cued is None and self.active and self.ads_on:
                self.cued, reel = reel, None
        if reel is not None:
            reel.close()

    def _drop(self, reel):
        with self.lock:
            if self.cued is not reel:
                return
            self.cued = None
        reel.close()

    # ------------------------------------------------------------ station promos (the helper's)
    def _promo_path(self, promo, values):
        """The promo's file: its copy voiced for the programme on air if there is one, else its own."""
        variant = ((values.get('programme') or {}).get('variants') or {}).get(promo['id'])
        if variant and self.variants_folder is not None and (Path(self.variants_folder) / variant).is_file():
            return Path(self.variants_folder) / variant
        return Path(self.library_folder) / promo['file']

    def _cue_promo(self):
        settings, values, library, now = self.promos, self.promo_values, self.library, time.time()
        with self.lock:
            cued = self.cued_promo
        if not self.active or not self.promos_on or not settings or self.library_folder is None:
            if cued is not None:
                self._drop_promo(cued)
            return
        if cued is not None:
            promo = library.get(cued.ad['id'])
            why = ('removed' if promo is None else 'switched off' if not switched_on(settings, promo['id'])
                   else 'failed' if cued.failed else readiness(promo, values)
                   or ('changed' if self._promo_path(promo, values) != cued.path or promo != cued.ad else None))
            if why is None:
                return
            LOG.info('Station promo %r is no longer next (%s)', cued.ad.get('name') or cued.ad['id'], why)
            self._drop_promo(cued)
        with self.lock:
            self.left_out = {k: v for k, v in self.left_out.items() if v[0] > now}
            choices = [{'id': p['id'], 'enabled': True, 'limit': None} for p in library.values()
                       if switched_on(settings, p['id']) and readiness(p, values) is None and p['id'] not in self.left_out]
            pick = self.promo_rotation.pick({'ads': choices, 'order': 'shuffle'}, [], now) if choices else None
        if pick is None:
            return
        promo, reel = library[pick['id']], None
        try:
            path = self._promo_path(promo, values)
            if not path.is_file():
                raise RuntimeError('its file is missing')
            reel = PromoReel(self.gst, promo, path, self.caps, self.output.audio_caps, values)
            if not reel.cue():
                raise RuntimeError(reel.failed)
        except Exception as exc:
            with self.lock:
                self.left_out[promo['id']] = (now + self.LEAVE_OUT, str(exc)[:200])
            LOG.warning('Station promo %r is left out for %d minutes: %s', promo['name'], self.LEAVE_OUT // 60, exc)
            if reel is not None:
                reel.close()
            return
        with self.lock:
            if self.cued_promo is None and self.active and self.promos_on:
                self.cued_promo, reel = reel, None
        if reel is not None:
            reel.close()

    def _drop_promo(self, reel):
        with self.lock:
            if self.cued_promo is not reel:
                return
            self.cued_promo = None
        reel.close()
