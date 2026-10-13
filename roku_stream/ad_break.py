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

**Next up.** The rotation's ads are drawn AHEAD at a time into a queue (self.queue), so the
page shows what is coming and the operator can change it: an entry skipped never airs (a
drawn ad is out of this round), and an ad or a promo queued by hand airs before the
rotation's ads and before a due promo, whatever its switch or limit. The rotation's next
promo (self.next_promo) keeps its place until it airs or is skipped. The operator can skip
what is on air too (command). Entries queued by hand survive a restart (my-ads-queue.json).

**The wait fill.** While the station ID holds its end card for a source still being
prepared (a Roku changing channel), master shows ads in its place too: the worker opens a
window on master's running clock where the end card froze (fill_start), and the ads (and a
due promo) play there, whole and no longer than FILL_LONGEST, with nothing in a corner.
With nothing to show, the end card shows. Once the source is ready (fill_finish), the ad
on air plays out, then, for a game joined in progress, the "We now join..." bumper
(sports_join.py). fill_end() says where the window ends, so the worker irises the ID out
there, or the take lands at the bumper's end. The window is on the programme's own
timeline, which runs the programme delay ahead of what master releases, so the worker and
the take never wait on what viewers have yet to see.
"""
from __future__ import annotations

from array import array
from collections import deque
import json
import logging
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

import gi

gi.require_version('GstVideo', '1.0')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import GstVideo, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

from .admute_link import apply_gain
from .errors import ConfigError
from .my_ads import Rotation, allowed, append_play, card_file, counts, played, read_plays
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


def _entry(kind, item_id, by):
    """An entry of Next up: an ad or a promo, queued by the rotation or by the operator ('you')."""
    return {'key': secrets.token_hex(4), 'kind': kind, 'id': item_id, 'by': by}


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
    entry = None                     # its entry of Next up (the join bumper has none)

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
    FILL_LONGEST = 31.0              # seconds: the longest ad a wait fill starts (the source may be ready)
    AHEAD = 5                        # the rotation's ads kept drawn in Next up
    QUEUED_MOST = 20                 # entries queued by hand, at most
    JOIN_GRACE = 3 * SECOND          # a take late for the bumper's end finds its last (black) frame

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
        self.break_items = 0                 # what has gone on air this break: with every 0, a promo opens it or none does
        self.last_due = None
        self.picture_due = None              # the latest frame's due: while frames come, they decide
        self.failed_once = False
        self.reel_start_pts = None           # where the reel on air started, on the programme's clock
        self.fill = None                     # the wait fill's window, while open (see fill_start)
        # Shared
        self.cued = None                     # the next ad, decoded up to its first frames
        self.cued_promo = None               # the next promo, likewise
        self.rotation, self.promo_rotation = Rotation(), Rotation()
        self.left_out = {}                   # ad or promo id -> (until, why): it would not play
        # Next up: entries {key, kind (ad|promo), id, by (you|rotation)} in the order they air,
        # those queued by hand first; the rotation's next promo, placed by its timing
        self.queue_path = self.plays_path.with_name('my-ads-queue.json')
        self.queue = self._load_queue()
        self.queue_saved = [{'kind': e['kind'], 'id': e['id']} for e in self.queue]
        self.queue_order = None              # (order, the list's ids in list order): a change redraws
        self.next_promo = None
        self.last_aired = None               # the rotation's last ad on air: list order resumes after it
        self.skip_on_air = None              # the key of the entry on air the operator skipped
        self.done, self.log = deque(), deque()
        # The wait fill: the worker's request (start, finish, join, stop on the running clock),
        # whether ads are wanted for it, its join bumper decoded ahead, and its planned end.
        self.fill_request = None
        self.filling = False
        self.cued_join = None
        self.fill_report = None
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
        for reel in (self.reel, self.cued, self.cued_promo):
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
            entry = getattr(reel, 'entry', None) or {}
            on_air = {'id': reel.ad['id'], 'name': reel.ad.get('name'), 'duration': reel.ad['duration'],
                      'position': position, 'since': playing and round(playing[1], 1),
                      'key': entry.get('key'), 'by': entry.get('by')}
        with self.lock:
            left_out = {k: why for k, (until, why) in self.left_out.items() if until > now}
        settings = self.promos
        return {'active': self.active, 'state': self.state, 'ads_on': self.ads_on,
                'ad': on_air if kind == 'ad' else None, 'promo': on_air if kind == 'promo' else None,
                'card_since': self.card_since and round(self.card_since[1], 1),
                'cued': cued and cued.ad['id'], 'card': {'ready': self.card is not None, 'error': self.card_error},
                'fill': self.fill_status(),
                'left_out': left_out,
                'next': self._upcoming(now),
                'promos': {'active': self.active and self.promos_on, 'cued': cued_promo and cued_promo.ad['id'],
                           'last': self.last_promo and round(self.last_promo, 1),
                           'due': bool(settings) and promo_due(settings, self.last_promo, now),
                           'draw_failed': next((r.draw_failed for r in (reel, cued_promo)
                                                if isinstance(r, PromoReel) and r.draw_failed), None)}}

    # ------------------------------------------------------------ Next up (the worker's)
    def command(self, body):
        """The operator's changes to Next up. {op: add, kind: ad|promo, id, next}: queued by hand,
        first (next) or after the others queued by hand. {op: skip, key}: an entry out of Next
        up, the next promo for another, or what is on air cut short for what follows it."""
        op = body.get('op')
        if op == 'add':
            kind, item_id, first = body.get('kind'), body.get('id'), body.get('next', False)
            if not isinstance(first, bool):
                raise ConfigError('next must be true or false')
            if kind == 'ad':
                ad = next((a for a in (self.settings or {}).get('ads', []) if a['id'] == item_id), None)
                if ad is None:
                    raise ConfigError('No such ad')
                if not (self.folder / ad['file']).is_file():
                    raise ConfigError('That ad\'s file is missing')
            elif kind == 'promo':
                promo = self.library.get(item_id) if isinstance(item_id, str) else None
                if promo is None:
                    raise ConfigError('No such promo')
                why = readiness(promo, self.promo_values)
                if why:
                    raise ConfigError(f'{promo["name"]} cannot air now: {why}')
            else:
                raise ConfigError('kind must be ad or promo')
            with self.lock:
                mine = sum(1 for e in self.queue if e['by'] == 'you')
                if mine >= self.QUEUED_MOST:
                    raise ConfigError(f'At most {self.QUEUED_MOST} can be queued by hand')
                entry = _entry(kind, item_id, 'you')
                # Moved up: the rotation's own draw of it goes (never twice running)
                self.queue = [e for e in self.queue if not (e['by'] == 'rotation' and e['kind'] == kind and e['id'] == item_id)]
                self.queue.insert(0 if first else mine, entry)
            self.wake.set()
            return {'accepted': True, 'key': entry['key']}
        if op == 'skip':
            key = body.get('key')
            if not isinstance(key, str) or not key:
                raise ConfigError('skip takes the key of an entry')
            reel = self.reel
            if reel is not None and (getattr(reel, 'entry', None) or {}).get('key') == key:
                with self.lock:
                    request = self.fill_request
                if self.fill is not None and request is not None and request['finish'] is not None:
                    raise ConfigError('The next program is ready: what is on air plays out first')
                self.skip_on_air = key       # the programme-delay thread cuts it at its next frame
                return {'accepted': True, 'on_air': True}
            with self.lock:
                entry = next((e for e in self.queue if e['key'] == key), None)
                if entry is not None:
                    self.queue.remove(entry)
                elif self.next_promo is not None and self.next_promo['key'] == key:
                    entry, self.next_promo = self.next_promo, None
                    self.promo_rotation.played(entry['id'])
            if entry is None:
                raise ConfigError('That is no longer in Next up')
            self.wake.set()
            return {'accepted': True, 'on_air': False}
        raise ConfigError('op must be add or skip')

    def _upcoming(self, now):
        """Next up as the page shows it: the entries in the order they would air, with the next
        promo where its timing puts it, each with its name, length, whether it is cued and, in a
        break, in how many seconds it would start if the break lasts."""
        settings, promos, library = self.settings, self.promos, self.library
        ads = {a['id']: a for a in (settings or {}).get('ads', [])}
        with self.lock:
            queue, promo_entry, left_out = list(self.queue), self.next_promo, dict(self.left_out)
        cued = {(getattr(r, 'entry', None) or {}).get('key') for r in (self.cued, self.cued_promo) if r is not None}
        in_break = self.state not in ('idle', 'fill') and self.fill is None
        at = None
        if in_break:
            at, reel = 0., self.reel
            if reel is not None and self.last_due is not None and self.reel_start is not None:
                at = max(0., reel.ad['duration'] - (self.last_due - self.reel_start) / SECOND)
        rows = []

        def add(entry, item, **extra):
            nonlocal at
            why = left_out.get(entry['id'])
            plays = not why and (self.ads_on if entry['kind'] == 'ad' else self.promos_on)
            rows.append({'key': entry['key'], 'kind': entry['kind'], 'id': entry['id'], 'by': entry['by'],
                         'name': item.get('name') or '', 'duration': item.get('duration'),
                         'cued': entry['key'] in cued, 'in': None if at is None or not plays else round(at, 1),
                         'left_out': why and why[1], **extra})
            if at is not None and plays:
                at += item.get('duration') or 0

        promo = promo_entry and self.promos_on and promos and library.get(promo_entry['id'])
        due_at = None
        if promo:
            last = self.promo_playing[1] if self.promo_playing else self.last_promo
            due_at = now if last is None else last + promos['every'] * 60
        for entry in queue:
            item = ads.get(entry['id']) if entry['kind'] == 'ad' else library.get(entry['id'])
            if item is None:
                continue
            # The promo goes on before the rotation's ads (never before those queued by hand):
            # between breaks, it opens the next one (once due); in a break, as it falls due.
            # Every break (every 0): it opens the next break.
            if promo and entry['by'] != 'you' and (not in_break or (promos['every'] and now + at >= due_at)):
                add(promo_entry, promo, due_at=round(due_at, 1), opens=not in_break)
                promo = None
            add(entry, item)
        if promo:
            add(promo_entry, promo, due_at=round(due_at, 1), opens=True)
        return rows

    def _load_queue(self):
        """What the operator queued by hand before a restart (my-ads-queue.json, master's own)."""
        try:
            rows = json.loads(self.queue_path.read_text())
        except (OSError, ValueError):
            return []
        return [_entry(row['kind'], row['id'], 'you') for row in (rows if isinstance(rows, list) else [])
                if isinstance(row, dict) and row.get('kind') in ('ad', 'promo')
                and isinstance(row.get('id'), str) and 0 < len(row['id']) <= 40][:self.QUEUED_MOST]

    def _save_queue(self):
        with self.lock:
            mine = [{'kind': e['kind'], 'id': e['id']} for e in self.queue if e['by'] == 'you']
        if mine == self.queue_saved:
            return
        try:
            fd, name = tempfile.mkstemp(prefix='.my-ads-queue-', dir=self.queue_path.parent)
            try:
                with os.fdopen(fd, 'w') as stream:
                    json.dump(mine, stream)
                os.replace(name, self.queue_path)
            finally:
                Path(name).unlink(missing_ok=True)
            self.queue_saved = mine
        except OSError as exc:
            LOG.warning('Cannot keep Next up: %s', exc)

    def close(self):
        self.stopping.set()
        self.wake.set()
        self.thread.join(timeout=2)
        for reel in (self.reel, self.cued, self.cued_promo, self.cued_join, *self.done):
            if reel is not None:
                reel.close()

    # ------------------------------------------------------------ the wait fill (the worker's)
    def fill_start(self, pts):
        """The station ID holds its end card from running time pts (its first held frame)
        while the next source is prepared: from there, ads in its place."""
        with self.lock:
            self.fill_request = {'start': pts, 'finish': None, 'join': None, 'stop': None}
            self.filling, self.fill_report = True, None
        self.wake.set()

    def fill_finish(self, pts, join=None):
        """The next source is ready, at running time pts. The ad on air plays out, then join
        ({'path', 'seconds'}: the bumper for a game joined in progress) if given; fill_end()
        then says where the window ends. False with no fill open."""
        with self.lock:
            request = self.fill_request
            if request is None or request['stop'] is not None:
                return False
            request.update(finish=pts, join=dict(join) if join else None)
            self.filling = False
            window = self.fill
            if window is None or window['request'] is not request:
                # What master releases has not reached the fill yet, so no ad has started in
                # it: the ID irises out at once, or the bumper takes the end card's place.
                self.fill_report = ({'end': request['start'] + int(join['seconds'] * SECOND), 'take': True, 'fixed': False}
                                    if join else {'end': pts, 'take': False, 'fixed': True})
        self.wake.set()
        return True

    def fill_stop(self, pts):
        """The ID left air or gave up holding: the window closes at running time pts, cutting
        whatever plays there."""
        with self.lock:
            if self.fill_request is not None and self.fill_request['stop'] is None:
                self.fill_request['stop'] = pts
            self.filling = False
        self.wake.set()

    def fill_end(self):
        """{'end': running time the window closes at, 'take': the take lands there (a join
        bumper) rather than the ID irising out, 'fixed': it will not move}; None until the
        end is planned (or with no fill)."""
        with self.lock:
            return dict(self.fill_report) if self.fill_report else None

    def fill_status(self):
        with self.lock:
            request, report = self.fill_request, self.fill_report
        if request is None:
            return None
        return {'state': 'finishing' if request['finish'] is not None else 'filling',
                'join': bool(request['join']), 'joined': self.reel_kind == 'join',
                'cued_join': self.cued_join is not None, 'planned': bool(report)}

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
            self.break_promos, self.break_items = set(), 0
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
        # Every break (every 0): a promo is always due, so only as the break's first item.
        if (self.promo_playing is None and promo_due(settings, self.last_promo, now)
                and (settings['every'] or not self.break_items)):
            return True
        return settings['fill'] and (not self.ads_on or self.cued is None)

    def _choice(self, now, fill=False):
        """What would go on now: 'cued' (Next up's first: queued by hand, or the rotation's ad),
        'promo' (the next promo, due) or None. First what the operator queued, then a due
        promo, then the rotation. A wait fill starts only short ads."""
        cued = self.cued
        if cued is not None and fill and cued.ad['duration'] > self.FILL_LONGEST:
            cued = None
        entry = (getattr(cued, 'entry', None) or {}) if cued is not None else {}
        kind = entry.get('kind', 'ad')
        if cued is not None and entry.get('by') == 'you' and (self.ads_on if kind == 'ad' else self.promos_on):
            return 'cued'
        if self._promo_wanted(now):
            return 'promo'
        return 'cued' if cued is not None and kind == 'ad' and self.ads_on else None

    def _take(self, now, fill=False):
        """Takes what goes on now off Next up: (reel, kind), or (None, None)."""
        with self.lock:
            choice = self._choice(now, fill)
            if choice is None:
                return None, None
            if choice == 'promo':
                reel, self.cued_promo = self.cued_promo, None
            else:
                reel, self.cued = self.cued, None
            entry = getattr(reel, 'entry', None) or {}
            kind = 'promo' if choice == 'promo' or entry.get('kind') == 'promo' else 'ad'
            if entry:
                self.queue = [e for e in self.queue if e['key'] != entry['key']]
            if kind == 'promo':
                self.promo_rotation.played(reel.ad['id'])
                self.break_promos.add(reel.ad['id'])
                if self.next_promo is not None and self.next_promo['id'] == reel.ad['id']:
                    self.next_promo = None       # never the same promo twice running
            elif entry.get('by') != 'you':
                self.last_aired = reel.ad['id']
        return reel, kind

    def _skipped(self):
        """Did the operator skip what is on air? (once)"""
        key, self.skip_on_air = self.skip_on_air, None
        return key is not None and self.reel is not None and (getattr(self.reel, 'entry', None) or {}).get('key') == key

    def _next(self, due):
        """What goes on air at due: what the operator queued, a due promo, the rotation's ad
        (see _choice), else the card; with my ads off, the programme as ad mute has it ('pass')."""
        now = time.time()
        reel, kind = self._take(now)
        if reel is not None and not reel.failed:
            self._card_off(due)
            self.break_items += 1
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

    def _finish(self, due, cut=False, skipped=False):
        reel, kind, self.reel, self.reel_kind = self.reel, self.reel_kind, None, None
        aired = max(0., (due - self.reel_start) / SECOND)
        length = reel.ad['duration']
        complete = not cut and not skipped and not reel.failed
        playing = self.promo_playing if kind == 'promo' else self.now_playing
        row = {'kind': kind, 'id': reel.ad['id'], 'name': reel.ad.get('name'),
               'at': round(playing[1] if playing else time.time() - aired, 1),
               'seconds': round(aired, 1), 'length': length, 'complete': complete,
               'counted': complete or counts(aired, length)}
        if reel.failed:
            row['error'] = str(reel.failed)[:200]
        if skipped:
            row['skipped'] = True
            if kind == 'promo':
                row['counted'] = True        # it was the break's promo: none takes its place at once
        if (getattr(reel, 'entry', None) or {}).get('by') == 'you':
            row['queued'] = True             # queued by hand
        if self.fill is not None:
            row['wait'] = True               # aired while the next source got ready
        if kind == 'promo':
            self.promo_playing = None
            if row['counted']:
                self.last_promo = row['at']
        elif kind == 'ad':
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
        self.picture_due = due
        try:
            filled = self._fill_step(due, pts, route)
        except Exception:            # never a reason to lose a frame: the fill is a nicety
            if not self.failed_once:
                self.failed_once = True
                LOG.exception('The wait fill failed')
            filled = False
        if filled is not False:  # a wait fill's frame, or None: the ID's own (its end card)
            return filled
        self._follow(due, self._muted(pts, route))
        if self.state == 'idle':
            return None
        self.last_due = due
        base = None
        if self.reel is not None:
            t = due - self.reel_start
            skipped = self._skipped()
            if not self.reel.failed and not skipped:
                base = self.reel.frame(t)
            if skipped or self.reel.failed or self.reel.ended(t):
                self._finish(due, skipped=skipped)
                self._next(due)
                base = self.reel.frame(0) if self.reel is not None else None
        elif self._choice(time.time()) is not None:
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

    # ------------------------------------------------------------ the wait fill (programme-delay thread)
    def _fill_step(self, due, pts, route):
        """Inside a wait fill: what master shows at due (None: the ID's end card); outside,
        False. Opens, plans and closes the window as the programme's clock (pts) crosses it."""
        with self.lock:
            request = self.fill_request
        window = self.fill
        if window is not None and window['request'] is not request:
            self._fill_close(due, window)    # a new airing of the ID: the old window is over
            window = None
        if window is None:
            if request is None or pts is None or pts < request['start']:
                return False
            if request['stop'] is not None and pts >= request['stop']:
                self._fill_close(due, {'request': request})
                return False
            window = self.fill = {'request': request, 'route': route[2] if route else None,
                                  'end': None, 'take': False, 'join_at': None, 'joined': False}
            if self.state != 'idle':         # a muted break was on: the fill takes over from it
                if self.reel is not None:
                    self._finish(due, cut=True)
                self._card_off(due)
            self.state, self.break_start, self.break_end, self.break_promos = 'fill', due, None, set()
            self.break_items = 0             # it opens like a break: with every 0, a promo first
        if pts is not None:
            if request['stop'] is not None and pts >= request['stop']:
                self._fill_close(due, window)
                return False
            end = window['end']
            if end is not None and pts >= end:
                late = window['take'] and route is not None and route[2] == window['route'] and pts < end + self.JOIN_GRACE
                if not late:
                    self._fill_close(due, window)
                    return False
                shown = getattr(self.reel, 'shown', None) if self.reel is not None else None
                last = shown[1] if shown else None
                return retimable(self.gst, last) if last is not None else self.blank
            if request['finish'] is not None and end is None:
                self._fill_plan(window, request, pts)
        self.last_due = due
        base = None
        if self.reel is not None:
            t = due - self.reel_start
            skipped = self.reel_kind != 'join' and window['end'] is None and self._skipped()
            if not self.reel.failed and not skipped:
                base = self.reel.frame(t)
            if skipped or self.reel.failed or self.reel.ended(t):
                joined = self.reel_kind == 'join'
                self._finish(due, skipped=skipped)
                base = None
                if joined:                   # its last frame holds until the take (or the end)
                    return self.blank
        if self.reel is None and window['joined']:
            return self.blank                # the bumper has ended: black until the take
        if self.reel is None and pts is not None:
            if window['end'] is None:
                self._fill_next(due, pts)
            elif window['join_at'] is not None and not window['joined'] and pts >= window['join_at']:
                self._fill_join(due, pts, window)
            if self.reel is not None:
                base = self.reel.frame(0)
        if base is None:
            return None
        return retimable(self.gst, base)

    def _fill_plan(self, window, request, pts):
        """The source is ready: the window ends where the ad on air ends, or after the join
        bumper that follows it."""
        start = pts
        if self.reel is not None and self.reel_start_pts is not None and self.reel_kind != 'join':
            start = max(pts, self.reel_start_pts + int(self.reel.ad['duration'] * SECOND))
        start = max(start, request['start'])
        join = request['join']
        if join:
            window.update(join_at=start, take=True, end=start + int(join['seconds'] * SECOND))
        else:
            window.update(end=start, take=False)
        with self.lock:
            if self.fill_request is request:
                self.fill_report = {'end': window['end'], 'take': window['take'], 'fixed': not join}

    def _fill_next(self, due, pts):
        """The next of the fill: what the operator queued, a due promo, else a short ad; else the end card."""
        now = time.time()
        reel, kind = self._take(now, fill=True)
        if reel is None:
            return
        self.wake.set()                      # cue the one after
        if reel.failed:
            self.done.append(reel)
            return
        self.break_items += 1
        self.reel, self.reel_kind, self.reel_start, self.reel_start_pts = reel, kind, due, pts
        if kind == 'promo':
            self.promo_playing = (reel.ad['id'], now)
        else:
            self.now_playing = (reel.ad['id'], now)

    def _fill_join(self, due, pts, window):
        """The join bumper goes on (once decoded): the window then ends at its end, for good."""
        with self.lock:
            reel, self.cued_join = self.cued_join, None
            request = window['request']
            joined = reel is not None and not reel.failed
            if not joined:                   # not decoded yet: the end moves with it
                window['join_at'] = pts
                window['end'] = pts + int(request['join']['seconds'] * SECOND)
                if reel is not None:         # it failed: the window ends now, the take follows
                    window.update(end=pts, take=True)
            if self.fill_request is request:
                self.fill_report = {'end': window['end'], 'take': True, 'fixed': joined or reel is not None}
        if reel is None:
            return
        if not joined:
            self.done.append(reel)
            LOG.warning('The sports join bumper failed: %s', reel.failed)
            return
        window['joined'] = True
        window['end'] = pts + int(reel.ad['duration'] * SECOND)
        with self.lock:
            if self.fill_request is request:
                self.fill_report = {'end': window['end'], 'take': True, 'fixed': True}
        self.reel, self.reel_kind, self.reel_start, self.reel_start_pts = reel, 'join', due, pts
        self.now_playing = None

    def _fill_close(self, due, window):
        if self.reel is not None and self.fill is window:
            self._finish(due, cut=self.reel_kind != 'join')
        if self.fill is window:
            self.fill = None
            self.state, self.break_end = 'idle', due
        with self.lock:
            if self.fill_request is window['request']:
                self.fill_request, self.fill_report, self.filling = None, None, False
        self.wake.set()                      # the helper lets the bumper go

    def fill_sound(self, due, pts, size):
        """The wait fill's sound for one buffer at running time pts; None outside one (or with
        nothing on in it: the ID's own silence)."""
        window = self.fill
        if window is None or pts is None or pts < window['request']['start'] or self.reel is None:
            return None
        try:
            return self.reel.sound(due - self.reel_start, size)
        except Exception:            # the ID's own silence rather than no sound at all
            LOG.debug('The wait fill\'s sound failed', exc_info=True)
            return None

    def sound(self, due, at, gain_at, scaled):
        """The break's sound for one programme audio buffer (scaled: already faded by ad
        mute's gain): the ad's or promo's, crossfaded with the programme's. None: the usual
        break bed."""
        if not self.active:
            return None
        end = at + len(scaled) * SECOND // (RATE * FRAME_BYTES)
        # The picture decides when a break starts and ends; the sound only while no frame has
        # come for a second. When the two disagreed (2026-10-08 11:56-11:58, a second input
        # tapped: the frames said muted, the sound not), each cut and restarted the ad:
        # 48 of my ads in two minutes, each on air for about a second.
        if self.picture_due is None or due - self.picture_due > SECOND:
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
        self._cue_join()
        self._cue()
        self._cue_promo()
        self._save_queue()

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
        """Keeps Next up, and its first entry that may go on now cued."""
        settings, now, playing = self.settings, time.time(), self.now_playing
        with self.lock:
            cued = self.cued
        if not settings:
            if cued is not None:
                self._drop(cued)
            return
        # The ad on air counts towards its limit while it plays.
        plays = self.plays + ([{'kind': 'ad', 'id': playing[0], 'at': playing[1], 'counted': True}] if playing else [])
        self._keep_queue(settings, plays, now)
        entry = self._first() if self.active or self.filling else None
        if cued is not None:
            why = self._stale(cued, entry)
            if why is None:
                return
            LOG.info('My ads: %r is no longer next (%s)', cued.ad.get('name') or cued.ad['id'], why)
            self._drop(cued)
        if entry is None:
            return
        try:
            reel = self._reel(entry)
        except Exception as exc:
            with self.lock:
                self.left_out[entry['id']] = (now + self.LEAVE_OUT, str(exc)[:200])
                self.queue = [e for e in self.queue if e['key'] != entry['key']]
            LOG.warning('%s %r is left out for %d minutes: %s', 'My ad' if entry['kind'] == 'ad' else 'Station promo',
                        entry['id'], self.LEAVE_OUT // 60, exc)
            return
        with self.lock:
            if self.cued is None and (self.active or self.filling) and any(e is entry for e in self.queue):
                self.cued, reel = reel, None
        if reel is not None:
            reel.close()

    def _keep_queue(self, settings, plays, now):
        """Next up: drops what can no longer air (gone; the rotation's over its limit or
        switched off; a promo that cannot air now) and draws the rotation's next ads, AHEAD of
        them. A new order (or list order) puts the rotation's back and draws them again. The
        limits are weighed outside the lock: the programme-delay thread takes from Next up."""
        ads = {a['id']: a for a in settings['ads']}
        order = (settings['order'], tuple(ads) if settings['order'] == 'list' else None)
        # Only plays that a limit can still see count (the longest limit, not the week).
        horizon = max((a['limit']['minutes'] for a in settings['ads'] if a.get('limit')), default=0) * 60
        plays = [p for p in plays if p.get('kind', 'ad') == 'ad' and played(p) and p.get('at', 0) >= now - horizon]
        with self.lock:
            if order != self.queue_order:
                if self.queue_order is not None:
                    self.rotation.undraw([e['id'] for e in self.queue if e['by'] == 'rotation'], self.last_aired)
                self.queue = [e for e in self.queue if e['by'] != 'rotation']
                self.queue_order = order
            self.left_out = {k: v for k, v in self.left_out.items() if v[0] > now}
            queue, left_out = list(self.queue), set(self.left_out)
            library, values, known = self.library, self.promo_values, self.library_folder is not None
        ahead, gone, drawn = [], set(), 0    # ahead: plays to come, for the limits of what follows them
        for e in queue:
            if e['kind'] == 'ad':
                ad = ads.get(e['id'])
                if ad is None or (e['by'] == 'rotation' and not allowed(ad, plays + ahead, now)):
                    gone.add(e['key'])
                    continue
                ahead.append({'kind': 'ad', 'id': e['id'], 'at': now, 'counted': True})
                drawn += e['by'] == 'rotation'
            elif known and (e['id'] not in library or readiness(library[e['id']], values)):
                gone.add(e['key'])
        new = []
        while drawn < self.AHEAD:            # the rotation is the helper's alone
            ad = self.rotation.pick(settings, plays + ahead, now, skip=left_out)
            if ad is None:
                break
            self.rotation.played(ad['id'])
            new.append(_entry('ad', ad['id'], 'rotation'))
            ahead.append({'kind': 'ad', 'id': ad['id'], 'at': now, 'counted': True})
            drawn += 1
        if gone or new:
            with self.lock:
                self.queue = [e for e in self.queue if e['key'] not in gone] + new

    def _first(self):
        """The first entry of Next up that may go on now: an ad with My ads on (in a wait fill,
        a short one), a promo with promos on; none left out."""
        ads = {a['id']: a for a in (self.settings or {}).get('ads', [])}
        with self.lock:
            for e in self.queue:
                if e['id'] in self.left_out:
                    continue
                if e['kind'] == 'ad':
                    if self.ads_on and not (self.filling and (ads.get(e['id'], {}).get('duration') or 0) > self.FILL_LONGEST):
                        return e
                elif self.promos_on and self.library_folder is not None:
                    return e
        return None

    def _stale(self, cued, entry):
        """Why the cued reel should not stay cued for entry (Next up's first), or None."""
        mine = getattr(cued, 'entry', None)
        if cued.failed:
            return 'failed'
        if entry is None or mine is None or mine['key'] != entry['key']:
            with self.lock:
                there = mine is not None and any(e['key'] == mine['key'] for e in self.queue)
            return 'not first any more' if there else 'out of Next up'
        if entry['kind'] == 'ad':
            ad = next((a for a in self.settings['ads'] if a['id'] == entry['id']), None)
            if ad is None or any(ad.get(k) != cued.ad.get(k) for k in ('file', 'gain_db', 'trim_db')):
                return 'changed'
        else:
            promo = self.library.get(entry['id'])
            if promo is None or promo != cued.ad or self._promo_path(promo, self.promo_values) != cued.path:
                return 'changed'
        return None

    def _reel(self, entry):
        """A reel for an entry, decoded up to its first frames. RuntimeError: it won't play."""
        if entry['kind'] == 'ad':
            ad = next((a for a in self.settings['ads'] if a['id'] == entry['id']), None)
            if ad is None:
                raise RuntimeError('it is gone')
            path = self.folder / ad['file']
            if not path.is_file():
                raise RuntimeError('its file is missing')
            reel = Reel(self.gst, ad, path, self.caps, self.output.audio_caps)
        else:
            promo = self.library.get(entry['id'])
            if promo is None:
                raise RuntimeError('it is gone')
            path = self._promo_path(promo, self.promo_values)
            if not path.is_file():
                raise RuntimeError('its file is missing')
            reel = PromoReel(self.gst, promo, path, self.caps, self.output.audio_caps, self.promo_values)
        reel.entry = entry
        try:
            if not reel.cue():
                raise RuntimeError(reel.failed)
        except BaseException:
            reel.close()
            raise
        return reel

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
        """Keeps the rotation's next promo (kept until it airs, is skipped or cannot air now),
        cued while breaks may come."""
        settings, values, library, now = self.promos, self.promo_values, self.library, time.time()
        with self.lock:
            cued = self.cued_promo
        if not self.promos_on or not settings or self.library_folder is None:
            with self.lock:
                self.next_promo = None
            if cued is not None:
                self._drop_promo(cued)
            return
        with self.lock:
            self.left_out = {k: v for k, v in self.left_out.items() if v[0] > now}
            entry = self.next_promo
            promo = entry and library.get(entry['id'])
            if entry is not None and (promo is None or not switched_on(settings, promo['id'])
                                      or readiness(promo, values) or promo['id'] in self.left_out):
                entry = self.next_promo = None
            if entry is None:
                choices = [{'id': p['id'], 'enabled': True, 'limit': None} for p in library.values()
                           if switched_on(settings, p['id']) and readiness(p, values) is None and p['id'] not in self.left_out]
                pick = self.promo_rotation.pick({'ads': choices, 'order': 'shuffle'}, [], now) if choices else None
                if pick is not None:
                    entry = self.next_promo = _entry('promo', pick['id'], 'promos')
        if not (self.active or self.filling) or entry is None:
            if cued is not None:
                self._drop_promo(cued)
            return
        if cued is not None:
            why = self._stale(cued, entry)
            if why is None:
                return
            LOG.info('Station promo %r is no longer next (%s)', cued.ad.get('name') or cued.ad['id'], why)
            self._drop_promo(cued)
        try:
            reel = self._reel(entry)
        except Exception as exc:
            with self.lock:
                self.left_out[entry['id']] = (now + self.LEAVE_OUT, str(exc)[:200])
                if self.next_promo is entry:
                    self.next_promo = None
            LOG.warning('Station promo %r is left out for %d minutes: %s', entry['id'], self.LEAVE_OUT // 60, exc)
            return
        with self.lock:
            if self.cued_promo is None and (self.active or self.filling) and self.promos_on and self.next_promo is entry:
                self.cued_promo, reel = reel, None
        if reel is not None:
            reel.close()

    # ------------------------------------------------------------ the join bumper (the helper's)
    def _cue_join(self):
        """Decode the join bumper the fill asks for, ahead of its turn; let it go after."""
        try:
            self._cue_join_now()
        except Exception:            # never in the way of cueing the ads
            LOG.exception('The sports join bumper could not be cued')

    def _cue_join_now(self):
        with self.lock:
            request, cued = self.fill_request, self.cued_join
            join = request and request['stop'] is None and request['join']
        if cued is not None and (not join or str(cued.path) != join['path']):
            with self.lock:
                if self.cued_join is cued:
                    self.cued_join = None
            cued.close()
            cued = None
        if not join or cued is not None:
            return
        reel = Reel(self.gst, {'id': 'sports-join', 'name': 'We now join', 'duration': float(join['seconds'])},
                    join['path'], self.caps, self.output.audio_caps)
        if not reel.cue():
            LOG.warning('The sports join bumper could not be decoded: %s', reel.failed)
        with self.lock:
            if self.fill_request is request and self.cued_join is None:
                self.cued_join, reel = reel, None
        if reel is not None:
            reel.close()

    def _drop_promo(self, reel):
        with self.lock:
            if self.cued_promo is not reel:
                return
            self.cued_promo = None
        reel.close()
