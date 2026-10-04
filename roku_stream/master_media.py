"""Persistent output and isolated, bounded raw A/V input bridges.

All graph mutations belong to the worker thread. Decoder callbacks only copy
timestamped buffers into appsrc; an input's EOS/errors never end the output.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from array import array
from html import escape

from .admute_link import apply_gain, badge_words
from .master import MasterStreamError, _gst
from .config import MasterConfig
from .production import PATTERN, DEFAULTS, ProductionSettings
from .captions import LiveCaptions, LOOKAHEAD_SECONDS
from .programme_delay import ProgrammeDelay, retimable


_NVENC_WORKS = None


def _nvenc_works(gst):
    """Encodes a few frames once per process: the factory can exist while the GPU or driver cannot."""
    global _NVENC_WORKS
    if _NVENC_WORKS is None:
        _NVENC_WORKS = False
        if gst.ElementFactory.find("nvh264enc"):
            pipeline = gst.parse_launch("videotestsrc num-buffers=5 ! video/x-raw,format=I420,width=320,height=180 "
                                        "! nvh264enc ! fakesink")
            try:
                if pipeline.set_state(gst.State.PLAYING) != gst.StateChangeReturn.FAILURE:
                    message = pipeline.get_bus().timed_pop_filtered(
                        10 * gst.SECOND, gst.MessageType.ERROR | gst.MessageType.EOS)
                    _NVENC_WORKS = message is not None and message.type == gst.MessageType.EOS
            finally:
                pipeline.set_state(gst.State.NULL)
        logging.getLogger(__name__).warning("Master video encoder: %s", "nvh264enc" if _NVENC_WORKS else "x264enc")
    return _NVENC_WORKS


def video_encoder(gst, encoder, fps, bitrate):
    # x264 at 720p60 shares the CPU with capture and TV-Thing transcodes. When it falls
    # below real time, videorate pads the gap with duplicates and the output drifts
    # hours behind the clock. NVENC keeps the encode off the CPU.
    if encoder == "nvenc" or (encoder == "auto" and _nvenc_works(gst)):
        return (f"nvh264enc preset=low-latency-hq rc-mode=cbr bitrate={bitrate} gop-size={fps} "
                "zerolatency=true bframes=0")
    return f"x264enc speed-preset=ultrafast tune=zerolatency threads=2 bitrate={bitrate} key-int-max={fps}"


class MasterMedia:
    shared_playout = True
    ad_break = None   # my ads over a muted break (ad_break.py), once configured

    def __init__(self, rtsp_url, *, width=1280, height=720, fps=30, bitrate=2500, radio_url=None, radio_gain_db=0.0,
                 encoder="auto"):
        self.gst = gst = _gst()
        self.fps = fps
        self.width, self.height = width, height
        self.video_caps =(f"video/x-raw,format=I420,width={width},height={height},framerate={fps}/1,"
                           "pixel-aspect-ratio=1/1,interlace-mode=progressive,colorimetry=bt709,chroma-site=mpeg2")
        card_caps = self.video_caps.replace(f"framerate={fps}/1", f"framerate={min(fps, 10)}/1")
        self.audio_caps = "audio/x-raw,format=F32LE,rate=48000,channels=2,layout=interleaved"
        queue = "queue max-size-buffers=8 max-size-bytes=0 max-size-time=500000000"
        graph = [
            f"input-selector name=video sync-streams=true sync-mode=clock cache-buffers=true drop-backwards=true ! {queue} "
            f"! identity single-segment=true ! videorate ! {self.video_caps} "
            "! appsink name=programme_video emit-signals=true sync=false async=false max-buffers=2 drop=true",
            'appsrc name=delayed_video is-live=true format=time block=false max-buffers=8 max-bytes=0 '
            f'max-time=500000000 leaky-type=downstream caps="{self.video_caps}" ! identity name=frame_context '
            # Station clock over everything on air, top right, in the style of Japanese
            # broadcast TV: bold white numerals, dark outline, no box. Silent until enabled.
            "! clockoverlay name=clock silent=true halignment=right valignment=top auto-resize=false "
            f"xpad={round(width * .045)} ypad={round(height * .05)} draw-outline=true draw-shadow=true "
            "shaded-background=false color=0xffffffff outline-color=0xff101010 "
            # The crawl (crawl_render.py) along the bottom: passes frames through while off.
            "! overlaycomposition name=crawl "
            # The ad-mute AD badge (admute_badge.py), top left: passes frames through while off.
            "! overlaycomposition name=adbadge "
            # Live captions sit above the crawl, in the shared video seen by every viewer.
            "! textoverlay name=live_captions silent=true halignment=center valignment=bottom "
            f"ypad={round(height * .16)} xpad={round(width * .08)} auto-resize=false "
            "shaded-background=true shading-value=180 draw-outline=true draw-shadow=false "
            f"! {self.video_caps} ! {video_encoder(gst, encoder, fps, bitrate)} "
            "! h264parse ! identity name=video_out ! publisher.sink_0",
            f"input-selector name=audio sync-streams=true sync-mode=clock cache-buffers=true drop-backwards=true ! {queue} "
            "! identity single-segment=true ! audiorate skip-to-first=true ! tee name=caption_audio "
            "! appsink name=programme_audio emit-signals=true sync=false async=false max-buffers=8 drop=true",
            'appsrc name=delayed_audio is-live=true format=time block=false max-buffers=16 max-bytes=0 '
            f'max-time=500000000 leaky-type=downstream caps="{self.audio_caps}" '
            f"! {queue} ! audioconvert "
            "! avenc_aac ! aacparse ! identity name=audio_out ! publisher.sink_1",
            # Leaky audio branch: a stopped/slow recognizer cannot block publication.
            "caption_audio. ! queue leaky=downstream max-size-buffers=8 max-size-bytes=0 max-size-time=250000000 "
            "! audioconvert ! audioresample ! audio/x-raw,format=F32LE,rate=16000,channels=1,layout=interleaved "
            "! appsink name=caption_pcm emit-signals=true sync=false async=false max-buffers=2 drop=true",
            # Blending the full-frame card in software cannot keep up with 60 fps. The card is
            # static between caption changes, so draw it at 10 fps and let videorate repeat it.
            f"videotestsrc is-live=true pattern=black ! {card_caps} ! videoconvert "
            f"! gdkpixbufoverlay name=test_card overlay-width={width} overlay-height={height} "
            '! textoverlay name=card_caption halignment=center valignment=center shaded-background=true shading-value=220 draw-shadow=false draw-outline=false '
            f'! videoconvert ! {card_caps} ! videorate ! {self.video_caps} ! {queue} ! video.sink_0',
            # Off-air audio mixes the tone with the optional radio. The tone source keeps the
            # mixer clocked, so a silent or failed radio never stalls the audio track.
            f"audiotestsrc name=off_air_audio is-live=true wave=sine freq=1000 volume=0.1 samplesperbuffer=480 ! {self.audio_caps} ! {queue} ! off_air_mix.sink_0",
            f'appsrc name=off_air_radio is-live=true format=time block=false max-buffers=16 max-bytes=0 '
            f'max-time=500000000 leaky-type=downstream caps="{self.audio_caps}" ! {queue} ! off_air_mix.sink_1',
            f"audiomixer name=off_air_mix latency=100000000 ! {self.audio_caps} ! {queue} ! audio.sink_0",
            "rtspclientsink name=publisher protocols=tcp latency=100 tcp-timeout=5000000",
        ]
        # Slots 1 and 2 carry sources; slot 3 is reserved for the station ID (see ident.py).
        for slot in (1, 2, 3):
            for kind, caps in (("video", self.video_caps), ("audio", self.audio_caps)):
                graph.append(f'appsrc name={kind}_{slot} is-live=true format=time block=false '
                             f'max-buffers=8 max-bytes=0 max-time=500000000 leaky-type=downstream caps="{caps}" '
                             f'! {queue} ! {kind}.sink_{slot}')
        # Audio slot 4 (requested after 0-3: input-selector numbers its pads in order): the
        # bed under a muted ad break, Cairo radio from the same decoder as the off-air
        # radio. Only the audio selector ever switches to it; the picture stays on the
        # source. A silent clock keeps the mixer running with no radio.
        graph += [
            f"audiotestsrc name=bed_clock is-live=true wave=silence samplesperbuffer=480 ! {self.audio_caps} ! {queue} ! bed_mix.sink_0",
            f'appsrc name=bed_radio is-live=true format=time block=false max-buffers=16 max-bytes=0 '
            f'max-time=500000000 leaky-type=downstream caps="{self.audio_caps}" ! {queue} ! volume name=bed_gain volume=0 ! bed_mix.sink_1',
            f"audiomixer name=bed_mix latency=100000000 ! {self.audio_caps} ! {queue} ! audio.sink_4",
        ]
        self.pipeline = gst.parse_launch(" ".join(graph))
        self.pipeline.get_by_name('test_card').set_property('location', str(PATTERN))
        self.pipeline.get_by_name('card_caption').set_property('font-desc', 'DejaVu Sans Mono 11')
        self.pipeline.get_by_name('clock').set_property('font-desc', f'DejaVu Sans Bold {round(height / 22)}')
        self.pipeline.get_by_name('live_captions').set_property('font-desc', f'DejaVu Sans {round(height / 28)}')
        self.captions = LiveCaptions()
        self.caption_text = ''
        self.programme = ProgrammeDelay(self)
        self.input_decoders = {}
        self.route_lock = threading.Lock()
        self.route_history = {kind: collections.deque(maxlen=2048) for kind in ('audio', 'video')}
        self.frame_history = collections.deque(maxlen=128)
        self.radio_history = collections.deque(maxlen=2048)
        self.admute_conf = None
        self.rendered_badge = None
        for kind in ('audio', 'video'):
            self.pipeline.get_by_name('programme_' + kind).connect('new-sample', self._programme_sample, kind)
            self.pipeline.get_by_name(kind).get_static_pad('src').add_probe(
                gst.PadProbeType.BUFFER, self._route_probe, kind)
        self.pipeline.get_by_name('frame_context').get_static_pad('src').add_probe(
            gst.PadProbeType.BUFFER, self._present_frame)
        self.pipeline.get_by_name('caption_pcm').connect('new-sample', self._caption_audio)
        from .crawl_render import CrawlRenderer  # Needs gi; imported only with a real pipeline.
        from .admute_badge import AdBadge
        self.crawl = CrawlRenderer(gst, self.pipeline.get_by_name('crawl'), width, height)
        self.badge = AdBadge(gst, self.pipeline.get_by_name('adbadge'), width, height)
        self.bed = BedGain(gst, self.pipeline.get_by_name('bed_gain'))
        self.audio_slot = 0
        self.radio = OffAirRadio(self, radio_url, radio_gain_db)
        self.set_test_card(ProductionSettings(MasterConfig(width=width, height=height, fps=fps, bitrate=bitrate)).card('master', DEFAULTS))
        self.bus = self.pipeline.get_bus()
        publisher = self.pipeline.get_by_name("publisher")
        publisher.set_property("location", rtsp_url)
        publisher.get_static_pad("sink_1").set_property("payloader", gst.ElementFactory.make("rtpmp4gpay"))
        self.selectors = [self.pipeline.get_by_name(kind) for kind in ("video", "audio")]
        self.lock = threading.Lock()
        self.tracks = {kind: {"buffers": 0, "last_at": 0., "last_pts": None, "backwards": 0}
                       for kind in ("video", "audio")}
        for kind in self.tracks:
            self.pipeline.get_by_name(kind + "_out").get_static_pad("sink").add_probe(
                gst.PadProbeType.BUFFER, self._observe, kind)
        for selector in self.selectors:
            selector.set_property("active-pad", selector.get_static_pad("sink_0"))
        self.active = 0
        if self.pipeline.set_state(gst.State.PLAYING) == gst.StateChangeReturn.FAILURE:
            self.close()
            raise MasterStreamError("Cannot start master publisher")
        self.programme.start()

    def set_test_card(self, card):
        # textoverlay accepts Pango markup: user captions must remain literal text.
        title = '<span weight="bold" size="x-large">' + escape(card['caption']) + '</span>'
        text = title + ('\n\n' + '\n'.join(escape(line) for line in card['lines']) if card['lines'] else '')
        self.pipeline.get_by_name('card_caption').set_property('text', text)
        self.pipeline.get_by_name('off_air_audio').set_property('volume', 0.1 if card['audio'] == 'tone' else 0.0)
        self.radio.set_enabled(card['audio'] == 'radio')

    def set_clock(self, clock):
        # Hour without a leading zero (7:05), as on Japanese TV. Local time of this process.
        overlay = self.pipeline.get_by_name('clock')
        overlay.set_property('time-format', '%-H:%M:%S' if clock['seconds'] else '%-H:%M')
        overlay.set_property('silent', not clock['enabled'])

    def set_crawl(self, content, restart=True):
        """A crawl (crawl.compose() or a bulletin), or None to slide the bar away."""
        self.crawl.show(content, restart=restart)

    def configure_captions(self, settings):
        self.captions.configure(settings)
        if settings['enabled']:
            self.programme.require(LOOKAHEAD_SECONDS)
        else:
            self._caption_overlay('')

    def configure_admute(self, settings):
        self.admute_conf = dict(settings)
        if settings['mode'] != 'off':
            self.programme.require(settings['lookahead'] + 1)

    def configure_my_ads(self, settings, store):
        """My ads settings (my_ads.py; None if unreadable), with the store's folder and play log."""
        if self.ad_break is None:
            if not settings:
                return
            from .ad_break import AdBreak  # Needs gi; imported only with a real pipeline.
            self.ad_break = AdBreak(self, store.folder, store.plays_path)
        self.ad_break.configure(settings, self.admute_conf)

    def my_ads_status(self):
        return self.ad_break.status() if self.ad_break else None

    def caption_status(self):
        return {**self.captions.status(), 'programme_delay': self.programme.status()}

    def register_input(self, slot, decoder):
        self.input_decoders[slot] = decoder
        if decoder.tap:
            self.programme.require(decoder.tap.delay_ns / self.gst.SECOND)

    def _route_probe(self, pad, info, kind):
        buffer = info.get_buffer()
        if buffer is not None:
            selector = self.pipeline.get_by_name(kind)
            active = selector.get_property('active-pad')
            slot = int(active.get_name().rsplit('_', 1)[-1]) if active else 0
            decoder = self.input_decoders.get(slot)
            anchor = decoder.anchor if decoder else None
            route = (decoder.tap if decoder else None, anchor[0] - anchor[1] if anchor else 0,
                     id(decoder) if decoder else slot)
            with self.route_lock:
                self.route_history[kind].append((buffer.pts, route))
        return self.gst.PadProbeReturn.OK

    def _route_at(self, kind, pts):
        with self.route_lock:
            return next((route for at, route in reversed(self.route_history[kind]) if at <= pts), None)

    def _programme_sample(self, sink, kind):
        sample = sink.emit('pull-sample')
        if sample:
            buffer = sample.get_buffer()
            pts = sample.get_segment().to_running_time(self.gst.Format.TIME, buffer.pts)
            if pts != self.gst.CLOCK_TIME_NONE:
                self.programme.put(kind, buffer, pts, self._route_at(kind, pts))
        return self.gst.FlowReturn.OK

    def remember_radio(self, buffer):
        with self.route_lock:
            self.radio_history.append((buffer.pts, buffer.extract_dup(0, buffer.get_size())))

    def _radio_at(self, pts, size):
        result = bytearray(size)
        with self.route_lock:
            history = list(self.radio_history)
        end = pts + size * self.gst.SECOND // (48000 * 8)
        for at, data in reversed(history):
            stop = at + len(data) * self.gst.SECOND // (48000 * 8)
            if stop <= pts:
                break
            if at >= end:
                continue
            start_frame = max(0, round((at - pts) * 48000 / self.gst.SECOND))
            source_frame = max(0, round((pts - at) * 48000 / self.gst.SECOND))
            count = min(size // 8 - start_frame, len(data) // 8 - source_frame)
            if count > 0:
                result[start_frame * 8:(start_frame + count) * 8] = data[source_frame * 8:(source_frame + count) * 8]
        return bytes(result)

    def release_programme(self, kind, buffer, due, duration, pts, route):
        gst = self.gst
        replaced = False
        if kind == 'audio' and route and route[0] and pts is not None:
            tap, offset, _ = route
            raw = buffer.extract_dup(0, buffer.get_size())
            scaled = apply_gain(raw, pts + offset, 48000, 2, tap.gain)
            if scaled is not None:
                conf = self.admute_conf or {}
                mine = self.ad_break.sound(due, pts + offset, tap.gain, scaled) if self.ad_break else None
                if mine is not None:   # one of my ads plays over the break, in place of the bed
                    scaled = mine
                elif conf.get('mode') == 'on' and conf.get('sound') == 'radio':
                    level = 10 ** (conf['radio_db'] / 20)
                    bed = self._radio_at(pts, len(raw))
                    bed = apply_gain(bed, pts + offset, 48000, 2, lambda p: 1 - tap.gain(p)) or bed
                    programme, replacement = array('f'), array('f')
                    programme.frombytes(scaled)
                    replacement.frombytes(bed)
                    scaled = array('f', (a + b * level for a, b in zip(programme, replacement))).tobytes()
                buffer = gst.Buffer.new_wrapped(scaled)
        if kind == 'video':
            if self.ad_break:
                shown = self.ad_break.picture(buffer, due, pts, route)
                if shown is not None:  # my ad (or the break card), the programme in a corner
                    buffer, replaced = shown, True
            with self.route_lock:
                self.frame_history.append((due, pts, route, replaced))
        buffer.pts, buffer.dts, buffer.duration = due, gst.CLOCK_TIME_NONE, duration
        self.pipeline.get_by_name('delayed_' + kind).emit('push-buffer', buffer)

    def _present_frame(self, _pad, info):
        buffer = info.get_buffer()
        with self.route_lock:
            context = next(((pts, route, replaced) for at, pts, route, replaced in reversed(self.frame_history)
                            if at <= buffer.pts), (None, None, False))
        pts, route, replaced = context
        audible, badge = True, None
        if route and route[0] and pts is not None:
            tap, offset, _ = route
            gain = tap.link.peek(tap.key, pts + offset) if hasattr(tap, 'link') else tap.gain(pts + offset)
            audible = gain >= .5
            status = tap.link.status(tap.key) if hasattr(tap, 'link') else None
            badge = badge_words(status, self.admute_conf or {}, pts + offset, gain)
            if replaced and not (self.admute_conf or {}).get('diagnostic'):
                badge = None  # my ad is on screen: an AD MUTED plate over it says nothing
        if self.admute_conf is not None and badge != self.rendered_badge:
            self.badge.show([(buffer.pts, None, *badge)] if badge else [])
            self.rendered_badge = badge
        self._caption_overlay(self.captions.text_at(pts / self.gst.SECOND if pts is not None else None,
                                                  audible=audible))
        return self.gst.PadProbeReturn.OK

    def _caption_audio(self, sink):
        sample = sink.emit('pull-sample')
        try:
            if sample is not None:
                buf = sample.get_buffer()
                pts = sample.get_segment().to_running_time(self.gst.Format.TIME, buf.pts)
                if pts != self.gst.CLOCK_TIME_NONE:
                    route = self._route_at('audio', pts)
                    self.captions.feed(buf.extract_dup(0, buf.get_size()), pts / self.gst.SECOND,
                                       route=route[2] if route else None)
        except Exception:
            logging.getLogger(__name__).exception('Caption audio tap failed')
        return self.gst.FlowReturn.OK

    def _caption_overlay(self, text):
        if text != self.caption_text:
            overlay = self.pipeline.get_by_name('live_captions')
            overlay.set_property('text', escape(text))
            overlay.set_property('silent', not bool(text))
            self.caption_text = text

    def set_badge(self, intervals):
        """[(from_ns, to_ns | None, label, caption)] on the master clock; [] for none."""
        self.badge.show(intervals)

    def set_bed(self, level, at=None):
        """Fade the ad-break bed to level (linear) starting at master running time at."""
        self.bed.fade(level, self.running_time() if at is None else at)

    def want_bed(self, wanted):
        self.radio.want_bed(wanted)

    def crawl_finished(self):
        """The key of the last crawl that ran all its passes."""
        return self.crawl.finished

    def _observe(self, pad, info, kind):
        buf = info.get_buffer()
        if buf is not None:
            # Encoders offset timestamps by 1000 hours; running time is comparable to the clock.
            event = pad.get_sticky_event(self.gst.EventType.SEGMENT, 0)
            running = (event.parse_segment().to_running_time(self.gst.Format.TIME, buf.pts)
                       if event is not None and buf.pts != self.gst.CLOCK_TIME_NONE else None)
            with self.lock:
                track = self.tracks[kind]
                track["buffers"] += 1
                track["last_at"] = time.monotonic()
                if buf.pts != self.gst.CLOCK_TIME_NONE:
                    track["backwards"] += int(track["last_pts"] is not None and buf.pts < track["last_pts"])
                    track["last_pts"] = buf.pts
                if running is not None and running != self.gst.CLOCK_TIME_NONE:
                    track["last_running"] = running
        return self.gst.PadProbeReturn.OK

    def running_time(self):
        clock = self.pipeline.get_clock()
        if clock is None:
            raise MasterStreamError("Master clock is not ready")
        return max(0, clock.get_time() - self.pipeline.get_base_time())

    def poll(self):
        self.radio.poll()
        if self.programme.error:
            raise MasterStreamError('Programme delay failed: ' + self.programme.error)
        message = self.bus.pop_filtered(self.gst.MessageType.ERROR | self.gst.MessageType.EOS)
        if message:
            reason = message.parse_error()[0].message if message.type == self.gst.MessageType.ERROR else "unexpected EOS"
            raise MasterStreamError("Master publisher failed: " + reason)

    def healthy(self):
        with self.lock:
            # rtspclientsink can hold the first encoded buffers during SETUP.
            # Those alone do not establish a working publisher.
            return all(t["buffers"] >= 10 and time.monotonic() - t["last_at"] < 2 for t in self.tracks.values())

    def status(self):
        try:
            now = self.running_time()
        except MasterStreamError:
            now = None
        with self.lock:
            return {kind: {"buffers": t["buffers"], "backwards": t["backwards"],
                           "age_seconds": round(time.monotonic() - t["last_at"], 3) if t["last_at"] else None,
                           "lag_seconds": round((now - t["last_running"]) / self.gst.SECOND, 3)
                           if now is not None and t.get("last_running") is not None else None}
                    for kind, t in self.tracks.items()}

    def take(self, slot):
        if slot not in (0, 1, 2, 3):
            raise MasterStreamError("Invalid input slot")
        probes = []
        try:
            for selector in self.selectors:
                idle = threading.Event()
                pad = selector.get_static_pad("src")
                def blocked(_pad, _info, event=idle):
                    event.set()
                    return self.gst.PadProbeReturn.OK
                probe = pad.add_probe(self.gst.PadProbeType.IDLE, blocked)
                probes.append((pad, probe, idle))
            deadline = time.monotonic() + 1
            for _, _, idle in probes:
                if not idle.wait(max(0, deadline - time.monotonic())):
                    raise MasterStreamError("Timed out synchronizing master A/V cut")
            # Mark the slot on air first: its input must stop off-air resyncs before the cut.
            self.active = slot
            self.audio_slot = slot
            for selector in self.selectors:
                selector.set_property("active-pad", selector.get_static_pad(f"sink_{slot}"))
        finally:
            for pad, probe, _ in probes:
                pad.remove_probe(probe)

    def take_audio(self, slot):
        """Switch only the sound: to the ad-break bed (4) and back to the slot on air."""
        if slot not in (self.active, 4) or slot == self.audio_slot:
            return
        selector = self.selectors[1]
        pad = selector.get_static_pad("src")
        idle = threading.Event()

        def blocked(_pad, _info):
            idle.set()
            return self.gst.PadProbeReturn.OK
        probe = pad.add_probe(self.gst.PadProbeType.IDLE, blocked)
        try:
            if not idle.wait(1):
                raise MasterStreamError("Timed out switching the ad-break bed")
            self.audio_slot = slot
            selector.set_property("active-pad", selector.get_static_pad(f"sink_{slot}"))
        finally:
            pad.remove_probe(probe)

    def close(self):
        self.captions.close()
        self.programme.close()
        if self.ad_break:
            self.ad_break.close()
        self.radio.bed_wanted = False
        self.radio.set_enabled(False)
        self.pipeline.set_state(self.gst.State.NULL)
        self.pipeline.get_state(2 * self.gst.SECOND)


class BedGain:
    """The ad-break bed's volume, faded on the master clock (GstController when the
    typelib is there; otherwise set at once, which only happens at a muted seam)."""
    FADE = 250_000_000

    def __init__(self, gst, element):
        self.gst, self.element = gst, element
        self.level = 0.
        self.source = None
        try:
            gi = __import__('gi')
            gi.require_version('GstController', '1.0')
            from gi.repository import GstController
            self.source = GstController.InterpolationControlSource()
            self.source.set_property('mode', GstController.InterpolationMode.LINEAR)
            element.add_control_binding(GstController.DirectControlBinding.new_absolute(element, 'volume', self.source))
        except Exception:
            logging.getLogger(__name__).warning('GstController unavailable: the ad-break bed switches without a fade')
            self.source = None

    def fade(self, level, at):
        if self.source is None:
            self.element.set_property('volume', level)
        else:
            self.source.unset_all()
            self.source.set(max(0, at), self.level)
            self.source.set(max(0, at) + self.FADE, level)
        self.level = level


class OffAirRadio:
    """Decodes the off-air radio stream in its own pipeline.

    Radio errors or EOS only silence it: it reconnects after RETRY_SECONDS and never
    fails the master publisher. Buffers are restamped contiguously just ahead of the
    master clock and resynchronized when they drift outside the mixer's latency window.
    """
    RETRY_SECONDS = 5
    LEAD = 50_000_000
    TOLERANCE = 40_000_000

    def __init__(self, output: MasterMedia, url, gain_db=0.0):
        self.output, self.url = output, url
        self.gain = 10 ** (gain_db / 20)
        self.gst = output.gst
        self.target = output.pipeline.get_by_name('off_air_radio')
        self.lock = threading.Lock()
        self.bed = output.pipeline.get_by_name('bed_radio')
        self.pipeline = self.bus = None
        self.card = False                # the off-air card plays the radio
        self.bed_wanted = False          # ad mute may put it under a break
        self.wanted = False
        self.retry_at = 0.
        self.next_pts = None

    def set_enabled(self, enabled):
        self.card = bool(enabled)
        self._want()

    def want_bed(self, wanted):
        self.bed_wanted = bool(wanted)
        self._want()

    def _want(self):
        self.wanted = bool((self.card or self.bed_wanted) and self.url)
        if not self.wanted:
            self._stop()
        elif self.pipeline is None:
            self.retry_at = 0.
            self.poll()

    def poll(self):
        gst = self.gst
        if self.pipeline is not None:
            message = self.bus.pop_filtered(gst.MessageType.ERROR | gst.MessageType.EOS)
            if message:
                reason = message.parse_error()[0].message if message.type == gst.MessageType.ERROR else "stream ended"
                logging.getLogger(__name__).warning("Off-air radio stopped (%s); retrying in %ss", reason, self.RETRY_SECONDS)
                self._stop()
                self.retry_at = time.monotonic() + self.RETRY_SECONDS
        if self.wanted and self.pipeline is None and time.monotonic() >= self.retry_at:
            try:
                self._start()
            except Exception as exc:
                logging.getLogger(__name__).warning("Cannot start off-air radio: %s", exc)
                self._stop()
                self.retry_at = time.monotonic() + self.RETRY_SECONDS

    def _start(self):
        gst = self.gst
        pipeline = gst.parse_launch(
            "uridecodebin name=decoder caps=audio/x-raw ! queue max-size-buffers=0 max-size-bytes=0 "
            f"max-size-time=2000000000 ! audioconvert ! volume volume={self.gain:.6f} ! audioresample ! {self.output.audio_caps} "
            "! appsink name=audio emit-signals=true sync=true max-buffers=8 drop=true")
        pipeline.get_by_name('decoder').set_property('uri', self.url)
        pipeline.get_by_name('audio').connect('new-sample', self._sample)
        with self.lock:
            self.pipeline, self.bus, self.next_pts = pipeline, pipeline.get_bus(), None
        if pipeline.set_state(gst.State.PLAYING) == gst.StateChangeReturn.FAILURE:
            raise MasterStreamError("Cannot start off-air radio decoder")

    def _sample(self, sink):
        gst = self.gst
        sample = sink.emit('pull-sample')
        with self.lock:
            if sample is None or self.pipeline is None:
                return gst.FlowReturn.OK
            try:
                target = self.output.running_time() + self.LEAD
            except MasterStreamError:
                return gst.FlowReturn.OK
            buffer = retimable(gst, sample.get_buffer())
            duration = buffer.get_size() // 8 * gst.SECOND // 48000  # F32LE stereo frames
            if self.next_pts is None or abs(self.next_pts - target) > self.TOLERANCE:
                self.next_pts = target
            buffer.pts, buffer.dts, buffer.duration = self.next_pts, gst.CLOCK_TIME_NONE, duration
            self.next_pts += duration
            self.output.remember_radio(buffer)
            self.target.emit('push-buffer', buffer)
            if self.bed_wanted and self.bed is not None:
                self.bed.emit('push-buffer', buffer)
        return gst.FlowReturn.OK

    def _stop(self):
        # Never hold the lock while stopping: the streaming thread may be waiting for it.
        with self.lock:
            pipeline, self.pipeline, self.bus = self.pipeline, None, None
        if pipeline is not None:
            pipeline.set_state(self.gst.State.NULL)
            pipeline.get_state(2 * self.gst.SECOND)


CLOCK_WINDOW = "Input audio/video is outside the master clock window"
DRIFTED = "Input {} is over a second behind its {}; prepare the source again"


class DecodedInput:
    # A fresh HLS input can rewind its audio once, ~0.5 s into decoding. Off air,
    # a timeline fault restarts the anchor (at most MAX_RESYNCS times in RESYNC_WINDOW);
    # ready() then waits for SETTLE of continuous media. A playing file which rides out
    # stalls drops frames that arrive too late.
    #
    # A live input on air rides out what used to fail it (2026-10-04: a FOX 5 game that
    # looked fine was failed off the air five times in eight minutes). Frames over a second
    # late are dropped and its timeline kept; a small step back (a repeated audio packet) is
    # dropped as overlap; while a track delivers nothing, ride_out() repeats the last picture
    # or silence on the master timeline (the worker allows that STALL_HOLD_SECONDS); frames
    # still late LATE_REANCHOR seconds into a hold re-anchor it on air, after what was held.
    # A jump ahead or a rewind of over a second still fails it closed.
    #
    # Each track keeps its own lateness. When only one is late, not catching up, while the
    # other arrives on time, the two have drifted over a second apart and no single anchor
    # fits both (2026-10-04 12:10: YouTube TV's video ran behind its audio, the picture was
    # held 8 s and recovery failed in 0.1 s): it fails at once and the queue puts it back.
    SETTLE = 1_500_000_000
    MAX_RESYNCS = 5
    RESYNC_WINDOW = 60
    RIDES_OUT_STALLS = False
    RIDES_OUT_ON_AIR = True
    OVERLAP = 1_000_000_000
    LATE_REANCHOR = 1.5
    FILL_AFTER = .25          # a track silent this long is filled while riding out a stall
    CATCH_UP = 200_000_000    # media this close behind a held picture is about to take over
    GAINING = 1.25            # late media coming this much faster than real time is catching up
    FILL_CHUNK = 20_000_000   # 20 ms of silence per filled audio buffer
    tap = None   # no ad-mute tap: media goes straight to master
    delay = 0

    def __init__(self, output: MasterMedia, slot: int, url: str, *, test_pattern=None, tap=None):
        self.output, self.slot = output, slot
        self.gst = gst = output.gst
        # The detector sees decoded media immediately. MasterMedia delays the selected
        # programme once and applies gain on release; legacy outputs retain a local delay.
        self.tap = tap
        self.delay = int(tap.delay_ns) if tap is not None and not getattr(output, 'shared_playout', False) else 0
        self.held = collections.deque()       # (kind, buffer, input pts, mapped) waiting to air
        self.held_cv = threading.Condition()
        self.pushed = {"video": 0, "audio": 0}
        self.lock = threading.Lock()
        self.closed = False
        self.error = None
        self.anchor = None
        self.floor = 0  # A new anchor starts no earlier than this (after a held picture).
        self.resyncs = 0
        self.resync_times = collections.deque()  # monotonic times of recent re-anchors
        self.last = {kind: {"pts": None, "at": 0., "count": 0, "end": None} for kind in ("video", "audio")}
        self.last_frame = None
        self.packets = {kind: {'at': None, 'count': 0, 'max_gap': 0.} for kind in self.last}
        self.late = {kind: 0 for kind in self.last}  # frames dropped for arriving too late
        # Riding out a stall on air: the filler thread, when each track last delivered media
        # in time, and how much picture or silence was filled in. Each track's first late
        # frame: (monotonic time, mapped pts), None while it is on time.
        self.riding, self.filler = False, None
        self.late_since = {kind: None for kind in self.last}
        self.arrived = {kind: 0. for kind in self.last}
        self.filled = {kind: 0 for kind in self.last}
        self.overlap = {kind: 0 for kind in self.last}  # frames dropped as a repeat of what aired
        self.reanchors = 0  # re-anchored on air, late frames after a held picture
        self.sources = {kind: output.pipeline.get_by_name(f"{kind}_{slot}") for kind in self.last}
        if getattr(output, 'shared_playout', False):
            output.register_input(slot, self)
        # A reused appsrc gets a fresh segment. It is inactive before this reset.
        for source in self.sources.values():
            source.set_state(gst.State.NULL)
            source.sync_state_with_parent()
        if test_pattern is None:
            graph = "uridecodebin name=decoder "
            video, audio = "decoder.", "decoder."
        else:
            graph = ""
            video = f"videotestsrc is-live=true pattern={int(test_pattern)}"
            audio = "audiotestsrc is-live=true wave=sine freq=440 samplesperbuffer=480"
        video_in = (f"{video} ! queue max-size-buffers=8 max-size-bytes=0 max-size-time=500000000 "
                    f"! videoconvert ! deinterlace ! videoscale ! videorate ! {output.video_caps} ")
        audio_in = (f"{audio} ! queue max-size-buffers=8 max-size-bytes=0 max-size-time=500000000 "
                    f"! audioconvert ! audioresample ! {output.audio_caps} ")
        sink = "emit-signals=true sync=true max-buffers=2 drop=true"
        if tap is None:
            graph += (f"{video_in}! appsink name=video {sink} "
                      f"{audio_in}! appsink name=audio {sink}")
        else:
            # The programme branches are as without a tap. The analysis branches are leaky
            # and never hold the programme up. (Holding the delay in queues here instead
            # starved live HLS demuxing: TV-Thing's audio rewound mid-stream, 2026-10-02.)
            leaky = "queue leaky=downstream max-size-bytes=0 max-size-time=0"
            graph += (f"{video_in}! tee name=vtee "
                      f"vtee. ! queue max-size-buffers=4 max-size-bytes=0 max-size-time=0 ! appsink name=video {sink} "
                      f"vtee. ! {leaky} max-size-buffers=4 ! videoscale add-borders=false "
                      "! video/x-raw,width=320,height=180 ! videoconvert ! video/x-raw,format=GRAY8 "
                      "! appsink name=tap_gray emit-signals=true sync=false max-buffers=8 drop=true "
                      f"vtee. ! {leaky} max-size-buffers=2 ! videorate drop-only=true max-rate=1 "
                      "! videoscale add-borders=false ! video/x-raw,width=224,height=224 ! videoconvert "
                      "! video/x-raw,format=RGB ! appsink name=tap_rgb emit-signals=true sync=false max-buffers=2 drop=true "
                      f"{audio_in}! tee name=atee "
                      f"atee. ! queue max-size-buffers=8 max-size-bytes=0 max-size-time=0 ! appsink name=audio {sink} "
                      "atee. ! queue leaky=downstream max-size-buffers=0 max-size-bytes=0 max-size-time=2000000000 "
                      "! audioconvert ! audioresample ! audio/x-raw,format=F32LE,rate=16000,channels=1,layout=interleaved "
                      "! appsink name=tap_audio emit-signals=true sync=false max-buffers=64 drop=true")
        self.pipeline = gst.parse_launch(graph)
        self.bus = self.pipeline.get_bus()
        if test_pattern is None:
            source = self.pipeline.get_by_name("decoder")
            source.connect('source-setup', self._source_setup)
            source.set_property("uri", url)
        for kind in self.last:
            self.pipeline.get_by_name(kind).connect("new-sample", self._sample, kind)
        if tap is not None:
            for name, size, send in (("tap_gray", 320 * 180, tap.gray), ("tap_rgb", 224 * 224 * 3, tap.rgb),
                                     ("tap_audio", None, tap.audio)):
                self.pipeline.get_by_name(name).connect("new-sample", self._tapped, size, send)
            if self.delay:
                threading.Thread(target=self._release, name=f"admute-delay-{slot}", daemon=True).start()
        if self.pipeline.set_state(gst.State.PLAYING) == gst.StateChangeReturn.FAILURE:
            self.close()
            raise MasterStreamError("Cannot start input decoder")

    def _tapped(self, sink, size, send):
        """Hands the detector a copy of what the programme will play D seconds later."""
        gst = self.gst
        sample = sink.emit("pull-sample")
        if sample is None or self.closed:
            return gst.FlowReturn.OK
        try:
            buffer = sample.get_buffer()
            pts = sample.get_segment().to_running_time(gst.Format.TIME, buffer.pts)
            if pts != gst.CLOCK_TIME_NONE and (size is None or buffer.get_size() == size):
                send(pts, buffer.extract_dup(0, buffer.get_size()))
        except Exception:  # The detector's copy is never a reason to fail the input.
            logging.getLogger(__name__).debug("Ad-mute tap dropped a buffer", exc_info=True)
        return gst.FlowReturn.OK

    def to_master(self, pts):
        """When input running time pts airs, on the master clock (None before anchoring)."""
        with self.lock:
            anchor = self.anchor
        return None if anchor is None or pts is None else pts - anchor[0] + anchor[1] + self.delay

    def from_master(self, running):
        """The input running time airing at master running time ``running``."""
        with self.lock:
            anchor = self.anchor
        return None if anchor is None else running - self.delay - anchor[1] + anchor[0]

    RELEASE_LEAD = 100_000_000   # hand a held buffer to master this long before it airs

    def _release(self):
        """The ad-mute delay line: each programme buffer goes to master once its delayed
        time is near, its audio scaled by the detector's gain as late as possible."""
        gst = self.gst
        while True:
            with self.held_cv:
                while not self.closed and not self.held:
                    self.held_cv.wait(.1)
                if self.closed:
                    self.held.clear()
                    return
                kind, buffer, pts, mapped = self.held[0]
            due = mapped + self.delay
            try:
                now = self.output.running_time()
            except MasterStreamError:
                time.sleep(.01)
                continue
            if due - self.RELEASE_LEAD > now:
                time.sleep(min(.02, (due - self.RELEASE_LEAD - now) / gst.SECOND))
                continue
            with self.held_cv:
                if not self.held or self.held[0][1] is not buffer:
                    continue
                self.held.popleft()
            if due < now - gst.SECOND:   # a stall left it behind the clock: never air it late
                with self.lock:
                    self.late[kind] += 1
                continue
            if kind == "audio":
                scaled = apply_gain(buffer.extract_dup(0, buffer.get_size()), pts, 48000, 2, self.tap.gain)
                if scaled is not None:
                    fresh = gst.Buffer.new_wrapped(scaled)
                    fresh.duration = buffer.duration
                    buffer = fresh
            buffer.pts, buffer.dts = due, gst.CLOCK_TIME_NONE
            if self.sources[kind].emit("push-buffer", buffer) != gst.FlowReturn.OK:
                with self.lock:
                    self.error = self.error or "Master input bridge stopped accepting media"
            else:
                with self.lock:
                    self.pushed[kind] += 1

    def _source_setup(self, _decoder, source):
        if source.get_factory().get_name() == 'rtspsrc':
            source.connect('pad-added', self._rtp_pad)

    def _rtp_pad(self, _source, pad):
        caps = pad.get_current_caps()
        kind = caps.get_structure(0).get_string('media') if caps and caps.get_size() else None
        if kind in self.packets:
            pad.add_probe(self.gst.PadProbeType.BUFFER, self._packet, kind)

    def _packet(self, _pad, _info, kind):
        with self.lock:
            now, track = time.monotonic(), self.packets[kind]
            if track['at']:
                track['max_gap'] = max(track['max_gap'], now - track['at'])
            track.update(at=now, count=track['count'] + 1)
        return self.gst.PadProbeReturn.OK

    def _sample(self, sink, kind):
        gst = self.gst
        sample = sink.emit("pull-sample")
        if sample is None:
            return gst.FlowReturn.OK
        with self.lock:
            if self.closed or self.error:
                return gst.FlowReturn.OK
            try:
                original = sample.get_buffer()
                pts = sample.get_segment().to_running_time(gst.Format.TIME, original.pts)
                if pts == gst.CLOCK_TIME_NONE:
                    raise MasterStreamError("Input has no usable timestamp")
                fault = self._timeline_fault(kind, pts)
                if fault == CLOCK_WINDOW and self.RIDES_OUT_STALLS and getattr(self, 'started', False) \
                        and self.anchor is not None and pts - self.anchor[0] + self.anchor[1] < self.output.running_time():
                    # The machine stalled and these frames of a playing file are already in the
                    # past. Drop them and keep the timeline: the decoder catches up with the clock
                    # by itself, in a burst. (Re-anchoring on late frames instead chases that
                    # burst, late then ahead, until the file fails.) If the stall lasts over a
                    # second, ready() goes false and the worker's stall recovery holds the test
                    # card, then takes the same file back once it is on time again.
                    self.late[kind] += 1
                    # Its place in the timeline moves on (so the jump check sees no gap when frames
                    # are on time again); its arrival time does not (so a long stall still shows).
                    self.last[kind]['pts'] = pts - self.anchor[0] + self.anchor[1]
                    return gst.FlowReturn.OK
                if self._live_on_air():
                    if self._ride(kind, pts, fault):
                        return gst.FlowReturn.OK
                    if self.anchor is None:  # re-anchored past a held picture
                        fault = self._timeline_fault(kind, pts)
                if fault and self.output.active != self.slot and self._may_resync():
                    self.anchor = None
                    if self.delay:
                        with self.held_cv:  # held media belongs to the old timeline
                            self.held.clear()
                    for track in self.last.values():
                        track.update(pts=None, count=0)
                    fault = self._timeline_fault(kind, pts)
                if fault:
                    raise MasterStreamError(fault)
                mapped = pts - self.anchor[0] + self.anchor[1]
                if self.delay:
                    # Into the delay line; a copy of our own, so decoder buffer pools are not held.
                    with self.held_cv:
                        self.held.append((kind, original.copy_deep(), pts, mapped))
                        self.held_cv.notify()
                    buffer = None
                else:
                    # (Not original.copy(): that is the same buffer, which the ad-mute tap
                    # shares through the tee; retiming it gave the tap master's clock.)
                    buffer = retimable(gst, original)
                    buffer.pts, buffer.dts = mapped, gst.CLOCK_TIME_NONE
                    result = self.sources[kind].emit("push-buffer", buffer)
                    if result != gst.FlowReturn.OK:
                        raise MasterStreamError("Master input bridge stopped accepting media")
                length = original.duration if original.duration != gst.CLOCK_TIME_NONE else 0
                self.arrived[kind] = time.monotonic()
                self.last[kind].update(pts=mapped, at=self.arrived[kind], count=self.last[kind]["count"] + 1,
                                       end=mapped + length)
                if kind == "video" and buffer is not None:
                    self.last_frame = buffer
            except Exception as exc:
                self.error = str(exc)
        return gst.FlowReturn.OK

    def _timeline_fault(self, kind, pts):
        """Anchors the input if needed; returns why pts cannot continue the timeline."""
        gst = self.gst
        if self.anchor is None:
            self.anchor = (pts, max(self.output.running_time() + 100 * gst.MSECOND, self.floor))
        mapped = pts - self.anchor[0] + self.anchor[1]
        if abs(mapped - self.output.running_time()) > gst.SECOND:
            return CLOCK_WINDOW
        previous = self.last[kind]["pts"]
        if mapped < 0 or (previous is not None and (mapped < previous or mapped - previous > 3 * gst.SECOND)):
            delta = (mapped - previous) / gst.MSECOND if previous is not None else None
            return f"Input {kind} timestamps changed (delta_ms={delta}); prepare the source again"
        return None

    def _may_resync(self):
        """Whether the timeline may be re-anchored now: at most MAX_RESYNCS times in
        RESYNC_WINDOW seconds (a long-lived feed is not failed for re-anchors hours apart)."""
        now, times = time.monotonic(), self.resync_times
        while times and now - times[0] > self.RESYNC_WINDOW:
            times.popleft()
        if len(times) >= self.MAX_RESYNCS:
            return False
        times.append(now)
        self.resyncs += 1
        return True

    def _live_on_air(self):
        return (self.RIDES_OUT_ON_AIR and not self.delay and self.anchor is not None
                and self.output.active == self.slot)

    def _ride(self, kind, pts, fault):
        """A live input on air drops a late frame, or one repeating what already aired,
        instead of failing; True when this frame is dropped. Late frames that go on while
        its picture is held re-anchor the input past it (the source fell behind for good);
        when only this track fell behind, and is not catching up, the input fails. A jump
        ahead of the clock or of its own timeline still fails it."""
        now = time.monotonic()
        mapped = pts - self.anchor[0] + self.anchor[1]
        previous = self.last[kind]["pts"]
        behind = previous - mapped if previous is not None else None  # >= 0: before what aired
        if fault is None and not behind == 0:
            self.late_since[kind] = None
            return False
        late = fault == CLOCK_WINDOW and mapped < self.output.running_time()
        if not late and behind is not None and 0 <= behind < self.OVERLAP:
            self.overlap[kind] += 1
            if not self.riding or behind < self.CATCH_UP:
                self.arrived[kind] = now  # media is arriving again: the filler gives way to it
                return True
            # Far behind a held picture: as good as late.
        elif late or (behind is not None and behind > 0):
            self.late[kind] += 1  # behind the clock, or further back than what already aired
        else:
            return False
        since = self.late_since[kind] = self.late_since[kind] or (now, mapped)
        if self.riding and now - since[0] >= self.LATE_REANCHOR:
            other = 'audio' if kind == 'video' else 'video'
            if self.late_since[other] is None and now - self.arrived[other] < self.FILL_AFTER:
                # Only this track fell behind; re-anchoring it would put the other ahead.
                # A backlog after a stall comes faster than real time and catches up by
                # itself; one that does not never will.
                if (mapped - since[1]) / self.gst.SECOND <= self.GAINING * (now - since[0]):
                    raise MasterStreamError(DRIFTED.format(kind, other))
            elif self._may_resync():
                self.floor = max(t["end"] or 0 for t in self.last.values()) + 60 * self.gst.MSECOND
                self.anchor = None
                self.late_since = {k: None for k in self.last}
                self.reanchors += 1
                return False
        return True

    def ride_out(self, on):
        """Hold the picture on air while this live input delivers nothing: each silent track
        is filled on the master timeline (the last frame repeated, or silence) until media
        arrives in time again. Returns whether it is riding out a stall."""
        with self.lock:
            if bool(on) == self.riding:
                return self.riding
            if on and (self.last_frame is None or self.closed or self.delay):
                return False
            self.riding = bool(on)
            self.late_since = {kind: None for kind in self.last}
            filler = self.filler
        if on:
            self.filler = threading.Thread(target=self._fill, name=f'input-hold-{self.slot}', daemon=True)
            self.filler.start()
        elif filler:
            filler.join(timeout=1)
        return bool(on)

    def _fill(self):
        gst = self.gst
        frame = gst.SECOND // self.output.fps
        silence = bytes(int(48000 * self.FILL_CHUNK / gst.SECOND) * 2 * 4)  # F32LE stereo
        while True:
            with self.lock:
                if not self.riding or self.closed or self.error:
                    return
                try:
                    now, running = time.monotonic(), self.output.running_time()
                    # Just ahead of the clock, as a playing input would be; a gap further back
                    # than the bridge holds is left to videorate and audiorate downstream.
                    ahead, behind = running + 100 * gst.MSECOND, running - 400 * gst.MSECOND
                    for kind, track in self.last.items():
                        if now - self.arrived[kind] < self.FILL_AFTER:
                            continue
                        step = frame if kind == 'video' else self.FILL_CHUNK
                        at = max(track['end'] or behind, behind)
                        while at < ahead:
                            if kind == 'video':
                                buffer = retimable(gst, self.last_frame)
                            else:
                                buffer = gst.Buffer.new_wrapped(silence)
                            buffer.pts, buffer.dts, buffer.duration = at, gst.CLOCK_TIME_NONE, step
                            if self.sources[kind].emit('push-buffer', buffer) != gst.FlowReturn.OK:
                                raise MasterStreamError('Master input bridge stopped accepting media')
                            track.update(pts=at, end=at + step)
                            self.filled[kind] += 1
                            at += step
                except Exception as exc:
                    self.error = str(exc)
                    return
            time.sleep(frame / gst.SECOND / 2)

    def poll(self):
        message = self.bus.pop_filtered(self.gst.MessageType.ERROR | self.gst.MessageType.EOS)
        if message:
            self.error = message.parse_error()[0].message if message.type == self.gst.MessageType.ERROR else "Input ended"
        if self.error:
            raise MasterStreamError(self.error)

    def ready(self):
        with self.lock:
            settled = self.anchor is not None and all(
                t["pts"] is not None and t["pts"] - self.anchor[1] >= self.SETTLE for t in self.last.values())
            # With an ad-mute delay, the programme must also be coming out of the delay line.
            flowing = not self.delay or all(n >= 5 for n in self.pushed.values())
            return settled and flowing and not self.closed and not self.error and all(
                t["count"] >= 5 and time.monotonic() - t["at"] < 1 for t in self.last.values())

    def status(self):
        with self.lock:
            now = time.monotonic()
            return {kind: {"buffers": track["count"],
                           "age_seconds": round(now - track["at"], 3) if track["at"] else None,
                           "rtp_packets": self.packets[kind]['count'],
                           "packet_age_seconds": round(now - self.packets[kind]['at'], 3) if self.packets[kind]['at'] else None,
                           "max_packet_gap_seconds": round(self.packets[kind]['max_gap'], 3),
                           "late_dropped": self.late[kind], "overlap_dropped": self.overlap[kind],
                           "filled": self.filled[kind]}
                    for kind, track in self.last.items()}

    def close(self):
        with self.lock:
            self.closed, self.riding = True, False
        with self.held_cv:
            self.held_cv.notify_all()
        self.pipeline.set_state(self.gst.State.NULL)
        self.pipeline.get_state(2 * self.gst.SECOND)


class FileInput(DecodedInput):
    """A library file. Preparation checks that it decodes, then parks it paused at its
    start; take plays it from there. EOS is completion, not failure: a track that has
    ended no longer counts as stalled while the other finishes.

    Broadcast recordings often begin with audio only (TV-Thing's start ~1.6 s before
    the first video frame). The cue skips that lead-in so a take or a back-to-back cut
    has both tracks immediately instead of freezing the previous picture."""
    START_TIMEOUT = 5
    AUDIO_CHUNK = 20_000_000  # 20 ms of silence per buffer while held.
    RIDES_OUT_STALLS = True
    RIDES_OUT_ON_AIR = False  # A file holds its picture with freeze() instead.

    def __init__(self, output: MasterMedia, slot: int, url: str, *, start_seconds=0):
        self.cued = self.started = self.finished = self.frozen = False
        self.holder = None
        self.ended = set()
        self.start_ns = int(start_seconds * 1_000_000_000)
        self.first_video_ns = None
        super().__init__(output, slot, url)
        for kind in self.last:
            self.pipeline.get_by_name(kind).get_static_pad('sink').add_probe(
                self.gst.PadProbeType.EVENT_DOWNSTREAM, self._event, kind)
        self.pipeline.get_by_name('video').get_static_pad('sink').add_probe(
            self.gst.PadProbeType.BUFFER, self._first_video)

    def _first_video(self, pad, info):
        gst, buffer = self.gst, info.get_buffer()
        event = pad.get_sticky_event(gst.EventType.SEGMENT, 0)
        if event is None or buffer.pts == gst.CLOCK_TIME_NONE:
            return gst.PadProbeReturn.OK
        # Stream time, not PTS: an MP4 edit list can shift PTS without moving the start.
        position = event.parse_segment().to_stream_time(gst.Format.TIME, buffer.pts)
        with self.lock:
            if self.first_video_ns is None and not self.started and position != gst.CLOCK_TIME_NONE:
                self.first_video_ns = position
        return gst.PadProbeReturn.REMOVE

    def _event(self, _pad, info, kind):
        if info.get_event().type == self.gst.EventType.EOS:
            with self.lock:
                self.ended.add(kind)
        return self.gst.PadProbeReturn.OK

    def cue(self):
        gst = self.gst
        with self.lock:
            self.cued = self.started = False
        self.pipeline.set_state(gst.State.PAUSED)
        self.pipeline.get_state(2 * gst.SECOND)
        with self.lock:
            # Skip an audio-only lead-in, but never more than a few seconds of the file.
            lead = self.first_video_ns if self.first_video_ns and self.first_video_ns < 5 * gst.SECOND else 0
        position = max(self.start_ns, lead)
        if not self.pipeline.seek_simple(gst.Format.TIME, gst.SeekFlags.FLUSH | gst.SeekFlags.ACCURATE, position):
            raise MasterStreamError('Cannot return the file to its start')
        result, _, _ = self.pipeline.get_state(5 * gst.SECOND)
        if result == gst.StateChangeReturn.FAILURE:
            raise MasterStreamError('File did not reopen at its start')
        with self.lock:
            self.ended.clear()
            self.cued = True

    def start(self):
        """Play from the cued position. The caller waits for ready() before cutting."""
        with self.lock:
            if not self.cued:
                raise MasterStreamError('File is not cued')
            self.cued, self.started = False, True
            self.anchor, self.resyncs = None, 0
            self.resync_times.clear()
            for track in self.last.values():
                track.update(pts=None, at=0., count=0)
        if self.pipeline.set_state(self.gst.State.PLAYING) == self.gst.StateChangeReturn.FAILURE:
            raise MasterStreamError('Cannot play file')

    def poll(self):
        message = self.bus.pop_filtered(self.gst.MessageType.ERROR | self.gst.MessageType.EOS)
        with self.lock:
            if message and message.type == self.gst.MessageType.ERROR:
                self.error = message.parse_error()[0].message
            elif (message or len(self.ended) == len(self.last)) and not self.cued:
                if self.started:
                    self.finished = True
                elif not self.error:
                    self.error = 'File ended while it was being checked'
            if self.error:
                raise MasterStreamError(self.error)

    def ready(self):
        with self.lock:
            if self.closed or self.error:
                return False
            if self.cued:
                return True
            if not self.started:
                pass  # Preparation: fall through to the settled check below.
            else:
                now = time.monotonic()
                return all(kind in self.ended or (t['count'] >= 2 and now - t['at'] < 1)
                           for kind, t in self.last.items())
        return super().ready()

    def freeze(self):
        """Hold the picture on air: the file pauses where it is, and its last frame repeats
        with silence on the master timeline until thaw(). The station ID holds its end card
        this way while the next source is still being prepared."""
        with self.lock:
            if self.frozen or not self.started or self.closed or self.last_frame is None:
                return False
            self.frozen = True
        self.pipeline.set_state(self.gst.State.PAUSED)
        self.holder = threading.Thread(target=self._hold, name='file-hold', daemon=True)
        self.holder.start()
        return True

    def _hold(self):
        gst = self.gst
        frame = gst.SECOND // self.output.fps
        silence = bytes(int(48000 * self.AUDIO_CHUNK / gst.SECOND) * 2 * 4)  # F32LE stereo
        while True:
            with self.lock:
                if not self.frozen or self.closed or self.error:
                    return
                try:
                    # Keep both tracks just ahead of the clock, as a playing input would.
                    ahead = self.output.running_time() + 100 * gst.MSECOND
                    video, audio = self.last['video'], self.last['audio']
                    video['end'] = max(video['end'] or ahead, 0)
                    audio['end'] = max(audio['end'] or ahead, 0)
                    while video['end'] < ahead:
                        buffer = retimable(gst, self.last_frame)
                        buffer.pts, buffer.dts, buffer.duration = video['end'], gst.CLOCK_TIME_NONE, frame
                        if self.sources['video'].emit('push-buffer', buffer) != gst.FlowReturn.OK:
                            raise MasterStreamError('Master input bridge stopped accepting media')
                        video.update(pts=buffer.pts, end=buffer.pts + frame, at=time.monotonic(), count=video['count'] + 1)
                    while audio['end'] < ahead:
                        buffer = gst.Buffer.new_wrapped(silence)
                        buffer.pts, buffer.duration = audio['end'], self.AUDIO_CHUNK
                        if self.sources['audio'].emit('push-buffer', buffer) != gst.FlowReturn.OK:
                            raise MasterStreamError('Master input bridge stopped accepting media')
                        audio.update(pts=buffer.pts, end=buffer.pts + self.AUDIO_CHUNK, at=time.monotonic(),
                                     count=audio['count'] + 1)
                except Exception as exc:
                    self.error = str(exc)
                    return
            time.sleep(frame / gst.SECOND / 2)

    def thaw(self):
        """Play on from the held position; the file's timeline continues after the held frames."""
        with self.lock:
            if not self.frozen:
                return False
            self.frozen = False
            self.anchor = None
            # Past both held tracks by more than a frame or chunk: audio and video restart a
            # few tens of ms apart, and neither may appear to go backwards.
            self.floor = max(t['end'] or 0 for t in self.last.values()) + 60 * self.gst.MSECOND
        if self.holder:
            self.holder.join(timeout=1)
        if self.pipeline.set_state(self.gst.State.PLAYING) == self.gst.StateChangeReturn.FAILURE:
            with self.lock:
                self.error = 'Cannot resume the held file'
        return True

    def close(self):
        with self.lock:
            self.frozen = False
        super().close()

    def progress(self):
        gst = self.gst
        ok, position = self.pipeline.query_position(gst.Format.TIME)
        known, duration = self.pipeline.query_duration(gst.Format.TIME)
        return {'position_seconds': round(position / gst.SECOND, 1) if ok and position >= 0 else None,
                'duration_seconds': round(duration / gst.SECOND, 1) if known and duration > 0 else None}
