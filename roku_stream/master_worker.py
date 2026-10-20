"""Single-owner master worker and private local command socket.

The output always starts on fallback. A restart never replays tuner actions.
Commands are serialized; status reads and cancellation remain responsive while
preparation waits for TV-Thing or its decoder.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import copy
import fcntl
import json
import logging
import os
import queue
import socket
import socketserver
import threading
import time
import uuid
from urllib.error import URLError
from urllib.request import urlopen

from .errors import ConfigError, ControlBusyError
from .master import MasterStreamError, _gst
from .master_media import DecodedInput, FileInput, MasterMedia
from .ident import (FILL_HOLD_LIMIT, IDENT_HOLD_AT, IDENT_HOLD_LIMIT, IDENT_PATH, IDENT_SECONDS, IDENT_SLOT,
                    JOIN_FREEZE_SLACK, IdentLease)
from .library import FileLease, LIBRARY_SOURCE_ID, cache_path, cached_breaks, library_target
from .tv_control import RokuLease, SharedLease, TvControl, target_from
from .roku_input import ROKU_SOURCE_IDS, roku_target
from .production import ProductionSettings
from .caption_settings import CaptionSettings
from .radio_info import RadioInfo
from .admute_link import AdMuteLink
from .admute_settings import AdMuteSettings, DEFAULTS as ADMUTE_DEFAULTS, lane_enabled
from .my_ads import MyAds
from .promos import Promos
from . import crawl

# How long the rotation's choice of where the bar runs lasts unless renewed (crawl_desk.py
# renews it every POSITION_RENEW s): a stopped web app leaves the bar at the bottom.
CRAWL_POSITION_LEASE = 60


class MasterWorker:
    # Start the armed next file this long before the on-air one ends, so its first
    # frames are flowing at the cut. It skips at most this much of the next file.
    NEXT_FILE_LEAD = .4
    IDENT_PREPARE_SECONDS = 20
    IDENT_RETRY_SECONDS = 60
    # The take lands at the join bumper's end; this long after, the ID stops waiting for it.
    JOIN_TAKE_GRACE_NS = 5_000_000_000
    # A prepared (off-air) input that was ready may drop out this long before it fails.
    PREPARED_SETTLE_SECONDS = 8
    # A live input on air that stops delivering holds its last picture this long (see
    # DecodedInput.ride_out) before master cuts to the test card and waits for it there.
    STALL_HOLD_SECONDS = 8

    def __init__(self, config, *, media_factory=MasterMedia, decoder_factory=DecodedInput,
                 file_decoder_factory=FileInput, tv=None, status_reader=None, ident_path=None):
        self.config = config.master
        self.app_config = config
        self.production = ProductionSettings(config.master)
        self.production_checked = 0
        self.production_card = None
        self.production_clock = None
        self.caption_settings = CaptionSettings(config.master.socket_path)
        self.caption_error = None
        self.radio_info = RadioInfo(self.config.off_air_radio_info_url) if self.config.off_air_radio_info_url else None
        self.crawl_settings = crawl.CrawlSettings(config.master, lenient=True)
        # Ad mute: the detector sidecar's link, and the settings it is read with.
        self.admute_settings = AdMuteSettings(config.master.socket_path, lenient=True)
        self.admute_conf = copy.deepcopy(ADMUTE_DEFAULTS)
        self.admute = AdMuteLink(Path(config.master.socket_path).with_name('admute.sock'))
        self.admute_error = None
        self.retired_taps = []
        # My ads over muted breaks (my_ads.py, ad_break.py): settings the web app writes.
        self.my_ads = MyAds(config.master.socket_path, lenient=True)
        self.my_ads_error = None
        # Station promos in the same breaks (promos.py): settings and live values from the web app.
        self.promos = Promos(config.master.socket_path, lenient=True)
        self.promos_error = None
        self.eas = crawl.EasAlerts(self.config.eas_url, self.config.eas_areas) if self.config.eas_url else None
        self.nws = crawl.NwsAlerts(self.config.nws_zones) if self.config.nws_zones else None
        # What the output's crawl was last told to run.
        self.crawl_content = None
        # The rotation's bulletin (crawl_desk.py): content and when its lease runs out.
        self.bulletin = None
        self.bulletin_log = []
        self.crawl_wake = False
        # Where the rotation wants the bar (top during some games) and until when: past its
        # lease, the bottom.
        self.crawl_position = ('bottom', 0.)
        # The source Roku is TV Thing's Roku lane, played like its tuners.
        self.roku_enabled = bool(config.tv_thing.enabled)
        self.tv = tv or TvControl(config.tv_thing)
        self.tv_enabled = config.tv_thing.enabled
        self.library_config = getattr(config, 'library', None)
        self.library_enabled = bool(self.library_config and self.library_config.enabled)
        self.file_decoder_factory = file_decoder_factory
        # (prepared input, on-air input): take the prepared file when that one ends.
        self.arm = None
        # The station ID (ident.py): kept cued in its own slot while a path is given.
        self.ident_path = ident_path
        self.ident_key = None
        self.ident_request = None
        # The request may start the ID from the test card (the Sports ID before a game).
        self.ident_from_test_card = False
        # Hold the ID's end card until this moment (the next source is being prepared).
        self.ident_hold_until = None
        # The join bumper to play once the next source is ready ({'path', 'seconds'}), and the
        # wait fill under way on the held end card ({'finishing'}; ad_break.py), this airing's.
        self.ident_join = None
        self.ident_fill = None
        # A continuity announcement version of the ID, for its next airing only.
        self.ident_override = None
        self.ident_retry_at = 0.
        self.ident_error = None
        self.media_factory, self.decoder_factory = media_factory, decoder_factory
        self.status_reader = status_reader or self._read_publication
        self.output = None
        self.inputs = {}
        self.prepared = None
        self.active = None
        self.recovering = None
        self.commands = queue.Queue(maxsize=1)
        self.cancel = threading.Event()
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.preview_inputs = {}
        self.snapshot = {"state": "starting", "on_air": None, "prepared": None, "operation": None,
                         "can_prepare": False, "can_take": False, "error": None, "cleanup_warning": None,
                         "tv_thing_enabled": self.tv_enabled, "roku_enabled": self.roku_enabled,
                         "library_enabled": self.library_enabled, "last_completed": None,
                         "publisher_ready": False, "last_input_failure": None, "recovery": None, "stall": None,
                         "ident": None, "last_station_id": None}
        self.busy = False
        self.publisher_ready = False
        self.publisher_id = None
        self.next_status = 0
        self.output_started = 0

    def _read_publication(self):
        with urlopen(self.config.status_url, timeout=2) as response:
            raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise MasterStreamError("MediaMTX status response too large")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise MasterStreamError("Invalid MediaMTX status")
        return result

    def status(self):
        with self.lock:
            return copy.deepcopy(self.snapshot)

    def preview(self, key):
        with self.lock:
            entry = self.preview_inputs.get(key)
            if not entry or entry['expires'] < time.monotonic():
                raise MasterStreamError('Source preview expired; prepare the source again')
            return {k: v for k, v in entry.items() if k != 'expires'}

    def submit(self, action, body):
        if action == "disarm":
            # Immediate, not queued: a paused queue must not advance at the end of a file.
            with self.lock:
                self.arm = None
            return {"accepted": True}
        if action == "crawl":
            # A bulletin from the rotation, or None to clear it; and (with or without one) where
            # the bar runs, for CRAWL_POSITION_LEASE seconds. Important and override crawls
            # are not interrupted: the bulletin is refused while one runs.
            position = crawl.validate_position(body['position']) if 'position' in body else None
            if position is None and 'bulletin' not in body:
                raise ConfigError('The crawl command takes a bulletin, a position or both')
            bulletin = crawl.validate_bulletin(body['bulletin']) if body.get('bulletin') is not None else None
            with self.lock:
                if position is not None:
                    self.crawl_position = (position, time.monotonic() + CRAWL_POSITION_LEASE)
                    self.crawl_wake = True
                if 'bulletin' not in body:
                    return {"accepted": True}
                kind = (self.crawl_content or {}).get('kind')
                if bulletin and kind in ('important', 'override'):
                    return {"accepted": False, "reason": kind}
                self.bulletin = ({**bulletin, 'deadline': time.monotonic() + bulletin['lease'], 'started': time.time()}
                                 if bulletin else None)
                self.crawl_wake = True
            return {"accepted": True}
        if action == "ident":
            # Immediate: a timed queue entry is 30 s away. The worker thread cuts to the ID.
            # from_test_card also plays it with nothing on air (the Sports ID before a game).
            with self.lock:
                self.ident_request = time.monotonic()
                self.ident_from_test_card = body.get('from_test_card') is True
            return {"accepted": True}
        if action == "ident_file":
            # The next ID plays this announcement version of it (continuity), once; None
            # returns to the plain ID.
            path = body.get('path')
            if path is not None and not (isinstance(path, str) and self._continuity_file(Path(path))):
                raise ConfigError('ident_file must be a continuity announcement in the state directory')
            with self.lock:
                self.ident_override = Path(path).resolve() if path else None
            return {"accepted": True}
        if action == "ident_hold":
            # Immediate: the next source is still being prepared, so the ID on air holds its
            # end card, with ads over it when there are some (a wait fill); false plays the
            # iris-out once the ad on air ends, so the take lands on its black tail. With join
            # (a game joined in progress), the "We now join..." bumper plays instead of the
            # iris (and of the Sports ID after it), and the take lands at its end.
            if not isinstance(body.get('hold'), bool):
                raise ConfigError('hold must be true or false')
            join = body.get('join')
            if join is not None:
                path = join.get('path') if isinstance(join, dict) else None
                seconds = join.get('seconds') if isinstance(join, dict) else None
                if (body['hold'] or not isinstance(path, str) or not Path(path).name.startswith('join-')
                        or not self._continuity_file(Path(path)) or isinstance(seconds, bool)
                        or not isinstance(seconds, (int, float)) or not 1 <= seconds <= 30):
                    raise ConfigError('join must be a join bumper in the announcements folder, with its seconds')
                join = {'path': str(Path(path).resolve()), 'seconds': float(seconds)}
            limit = FILL_HOLD_LIMIT if self._fills() else IDENT_HOLD_LIMIT
            with self.lock:
                self.ident_hold_until = time.monotonic() + limit if body['hold'] else None
                self.ident_join = join
            return {"accepted": True}
        if action == "my_ads":
            # Immediate: the operator's Next up in breaks (ad_break.AdBreak.command): queue an ad
            # or a promo by hand, skip one, or cut short the one on air.
            breaks = self._ad_break()
            if breaks is None:
                raise ConfigError('My ads is not running on master')
            return {**breaks.command(body), 'my_ads': breaks.status()}
        if action == "admute":
            # Immediate: the operator's correction for the input on air ("it's the show" /
            # "it's an ad"). Applied here at once, and the detector learns of it.
            if body.get('action') not in ('mute', 'unmute'):
                raise ConfigError('admute action must be mute or unmute')
            key = self.active
            if not key or not (self.inputs.get(key) or {}).get('tap'):
                return {"accepted": False, "reason": "Nothing analysed is on air"}
            return {"accepted": self.admute.override(key, body['action'])}
        if action not in ("prepare", "take", "fallback", "cancel"):
            raise ConfigError("Unknown master command")
        if action == "prepare":
            if body.get('source_id') == LIBRARY_SOURCE_ID:
                if not self.library_enabled:
                    raise ConfigError('The media library is not configured')
                after = body.get('after_input_id')
                if after is not None and (not isinstance(after, str) or len(after) > 64):
                    raise ConfigError('after_input_id must be an input ID')
                body = {**library_target(body), 'after_input_id': after}
            elif body.get('source_id') in ROKU_SOURCE_IDS:
                if not self.roku_enabled:
                    raise ConfigError('The Roku is played from TV-Thing, which is disabled')
                # The web app's lease on the Roku lane, by token (tv_roku.py).
                body = {**roku_target(body), 'roku': body.get('roku')}
            else:
                body = target_from(body)
        if action == "take" and (not isinstance(body.get("prepared_id"), str) or not body["prepared_id"]):
            raise ConfigError("Take requires the current prepared_id")
        with self.lock:
            if action in ("cancel", "fallback") and self.busy:
                self.cancel.set()
                # Fallback is performed after the in-flight bounded request
                # returns. No second graph-mutating thread is introduced.
                if action == "fallback":
                    self.pending_fallback = True
                return {"accepted": True, "state": "cancelling"}
            if self.busy:
                raise MasterStreamError("A master operation is already running")
            if action in ("prepare", "take") and not self.snapshot["can_prepare"]:
                raise MasterStreamError("Master publisher is not ready")
            self.busy = True
            self.pending_fallback = action == "fallback"
            self.cancel.clear()
            operation = {"id": uuid.uuid4().hex, "action": action, "state": "pending", "error": None}
            self.snapshot["operation"] = operation
            self.snapshot["can_prepare"] = self.snapshot["can_take"] = False
            self.commands.put_nowait((action, body, operation["id"]))
            return copy.deepcopy(operation)

    def _publish(self, **updates):
        with self.lock:
            self.snapshot.update(updates)

    def _refresh(self):
        healthy = bool(self.output and self.output.healthy() and self.publisher_ready)
        prepared = self.inputs.get(self.prepared)
        ready = bool(prepared and prepared["decoder"] and prepared["decoder"].ready())
        previews = {}
        if healthy:
            for key in (self.active, self.prepared):
                entry = self.inputs.get(key)
                # Library files have no HLS preview; the master monitor shows them.
                if (entry and entry['decoder'] and entry['decoder'].ready() and entry.get('url')
                        and not isinstance(entry['lease'], FileLease)):
                    previews[key] = {'input_id': key, 'url': entry['url'], 'expires': time.monotonic() + 3}
        with self.lock:
            self.preview_inputs = previews
        self._publish(state=("live" if self.active else "fallback") if healthy else "reconnecting",
                      publisher_ready=self.publisher_ready,
                      on_air=self._public(self.active), prepared=self._public(self.prepared),
                      can_prepare=healthy and (self.tv_enabled or self.roku_enabled or self.library_enabled) and not self.busy,
                      can_take=healthy and ready and not self.busy,
                      tracks=self.output.status() if self.output else {},
                      ident=self._ident_status())
        self._publish(recovery=({"target": self._public(self.recovering),
                                "message": "Waiting for fresh audio/video from the same source"}
                               if self.recovering else None),
                      input_tracks={name: self.inputs[key]['decoder'].status()
                                    for name, key in (('on_air', self.active), ('prepared', self.prepared),
                                                      ('recovering', self.recovering))
                                    if key in self.inputs and self.inputs[key]['decoder']})

    def _public(self, key):
        entry = self.inputs.get(key)
        if not entry:
            return None
        lease = entry['lease']
        result = {"id": key, **lease.target, "generation": lease.generation}
        if isinstance(lease, RokuLease):
            result['resolved_source'] = getattr(lease, 'resolved_source', None)
        if isinstance(lease, SharedLease):
            result['shared_with'] = lease.shared_with
        if isinstance(lease, FileLease) and entry['decoder'] and hasattr(entry['decoder'], 'progress'):
            result['media'] = entry['decoder'].progress()
            if entry.get('breaks'):
                result['break_plan'] = self._break_status(entry['breaks'])
            with self.lock:
                if self.arm and self.arm[0] == key:
                    result['after_input_id'] = self.arm[1]
        return result

    def _drop(self, key):
        with self.lock:
            self.preview_inputs.pop(key, None)
        entry = self.inputs.pop(key, None)
        if entry:
            if entry.get("tap"):
                if getattr(self.output, 'shared_playout', False) is True:
                    # Keep the detector's decisions until this input's buffered tail airs.
                    self.retired_taps.append((time.monotonic() + self.output.programme.delay_ns / 1e9 + 1, key))
                else:
                    self.admute.close_input(key)
            if entry["decoder"]:
                entry["decoder"].close()
            if not entry["lease"].release():
                self._publish(cleanup_warning="Tuner release could not be confirmed; its lease expires within 90 seconds. Playback was left running.")
        if self.prepared == key:
            self.prepared = None
        with self.lock:
            if self.arm and key in self.arm:
                self.arm = None
        plan = entry.get("breaks") if entry else None
        if plan and plan['state'] != 'play' and self._ad_break() is not None:
            # The show left air in (or just before) one of its ad breaks: the break ends with it.
            try:
                if plan['state'] == 'held':
                    self._ad_break().fill_stop(self.output.running_time())
                else:
                    self._ad_break().fill_unprime()
            except Exception:
                logging.getLogger(__name__).warning('The ad break could not be closed', exc_info=True)
        if self.ident_key == key:
            self.ident_key = None
            self._end_fill()  # The ID left air: whatever fills its end card stops there.
            if self.active == key:
                with self.lock:
                    self.ident_hold_until = None  # A hold belongs to the airing that ended.
                    self.ident_join = None
        if self.active == key:
            self.active = None
        if self.recovering == key:
            self.recovering = None

    def _ride_out(self, key, entry, now):
        """The input on air stopped delivering: hold its picture on air rather than cut to the
        test card, when its decoder can. False when it cannot (recovery starts at once)."""
        decoder = entry['decoder']
        if getattr(decoder, 'RIDES_OUT_ON_AIR', False) is not True or not decoder.ride_out(True):
            return False
        entry['stalled_since'] = now
        stall = {"target": self._public(key), "since": time.time(), "tracks": decoder.status()}
        logging.getLogger(__name__).warning('Master input stalled on air; holding its picture: %s', json.dumps(stall))
        self._publish(stall=stall)
        return True

    def _riding_out(self, key, entry, ready, now):
        """Riding out a stall: back to normal once the input is ready again, or the test card
        and recovery after STALL_HOLD_SECONDS."""
        decoder = entry['decoder']
        seconds = round(now - entry['stalled_since'], 3)
        if ready:
            entry['stalled_since'] = None
            decoder.ride_out(False)
            logging.getLogger(__name__).warning('Master input rode out a stall on air: %s', json.dumps(
                {"target": self._public(key), "seconds": seconds, "reanchors": getattr(decoder, 'reanchors', None),
                 "tracks": decoder.status()}))
            self._publish(stall=None)
        elif now - entry['stalled_since'] >= self.STALL_HOLD_SECONDS:
            entry['stalled_since'] = None
            decoder.ride_out(False)
            self._publish(stall=None)
            logging.getLogger(__name__).warning('Master input still stalled after holding its picture %.1f s', seconds)
            self._begin_recovery(key, entry)

    def _begin_recovery(self, key, entry):
        now = time.monotonic()
        attempts = [t for t in entry.get('recoveries', []) if now - t < 60]
        if len(attempts) >= 3:
            raise MasterStreamError('Input repeatedly stalled; prepare the source again')
        entry['recoveries'] = attempts + [now]
        entry['recovery_deadline'] = now + 8
        entry['recovery_ready_since'] = None
        failure = {"target": self._public(key), "error": "Input audio/video stopped arriving",
                   "at": time.time(), "was_on_air": True, "tracks": entry['decoder'].status()}
        logging.getLogger(__name__).warning('Master input recovering: %s', json.dumps(failure))
        self.output.take(0)
        self.active = None
        self.recovering = key
        self._publish(state='fallback', on_air=None,
                      recovery={'target': self._public(key), 'message': 'Waiting for fresh audio/video from the same source'},
                      error='Input paused; master is on fallback while checking recovery', last_input_failure=failure)

    def _recover(self, key, entry, ready):
        now = time.monotonic()
        if now >= entry['recovery_deadline']:
            raise MasterStreamError('Input did not recover within 8 seconds; prepare the source again')
        if not ready:
            entry['recovery_ready_since'] = None
            return
        if entry['recovery_ready_since'] is None:
            entry['recovery_ready_since'] = now
            return
        if now - entry['recovery_ready_since'] < .5:
            return
        entry['lease'].renew(force=True)
        if entry['lease'].check() != entry['url'] or not entry['decoder'].ready():
            raise MasterStreamError('Source identity or readiness changed during recovery')
        if self.busy or self.stopping.is_set():
            return
        self.output.take(entry['slot'])
        self.active, self.recovering = key, None
        recovered = {'target': self._public(key), 'at': time.time(),
                     'seconds_on_fallback': round(now - (entry['recovery_deadline'] - 8), 3)}
        self._publish(error=None, last_recovery=recovered)
        logging.getLogger(__name__).warning('Master input recovered: %s', json.dumps(recovered))

    def _fallback(self):
        if self.output:
            self.output.take(0)
        self.active = None
        for key in list(self.inputs):
            self._drop(key)

    def _tick(self):
        self.output.poll()
        if time.monotonic() >= self.production_checked:
            self.production_checked = time.monotonic() + 1
            try:
                settings = self.production.read()
                card = self.production.card('master', settings, radio=self.radio_info.lines() if self.radio_info else ())
                if card != self.production_card and hasattr(self.output, 'set_test_card'):
                    self.output.set_test_card(card)
                    self.production_card = card
                if settings['clock'] != self.production_clock and hasattr(self.output, 'set_clock'):
                    self.output.set_clock(settings['clock'])
                    self.production_clock = settings['clock']
                self._publish(production_error=None)
            except (OSError, ValueError, ConfigError) as exc:
                self._publish(production_error=f'Cannot load test card settings: {exc}')
            self._crawl()
            try:
                if hasattr(self.output, 'configure_captions'):
                    self.output.configure_captions(self.caption_settings.read())
                self.caption_error = None
            except Exception as exc:
                self.caption_error = f'Cannot load live captions: {exc}'
            try:
                self.admute_conf = self.admute_settings.read()
                self.admute_error = None
            except (OSError, ValueError, ConfigError) as exc:
                self.admute_error = f'Cannot load ad-mute settings: {exc}'
            self.admute.set_mode(self.admute_conf['mode'])
            if getattr(self.output, 'shared_playout', False) is True:
                self.output.configure_admute(self.admute_conf)
            if hasattr(self.output, 'want_bed'):
                self.output.want_bed(self.admute_conf['mode'] == 'on' and self.admute_conf['sound'] == 'radio'
                                     and any(e.get('tap') for e in self.inputs.values()))
            if getattr(self.output, 'shared_playout', False) is True:
                try:
                    my_ads, self.my_ads_error = self.my_ads.read(), None
                except (OSError, ValueError, ConfigError) as exc:
                    my_ads, self.my_ads_error = None, f'Cannot load my ads: {exc}'  # breaks stay as they are
                self.output.configure_my_ads(my_ads, self.my_ads)
                try:
                    promos, self.promos_error = self.promos.snapshot(), None
                except (OSError, ValueError, ConfigError) as exc:
                    promos, self.promos_error = None, f'Cannot load station promos: {exc}'
                self.output.configure_promos(promos, self.my_ads)
        elif self.crawl_wake:
            self._crawl()  # A bulletin just arrived: start it now, not at the next second.
        tracks = self.output.status().values()
        if any(track.get("backwards", 0) for track in tracks):
            raise MasterStreamError("Master output timestamps went backwards")
        now = time.monotonic()
        # Output timestamps are running time. An output behind the clock plays out faster
        # than real time until it catches up, and players cannot hold the live edge.
        if now - self.output_started > 12 and any((track.get("lag_seconds") or 0) > 5 for track in tracks):
            raise MasterStreamError("Master output fell behind real time")
        if now - self.output_started > 12 and not self.output.healthy():
            raise MasterStreamError("Master output stopped producing audio/video")
        if now >= self.next_status:
            self.next_status = now + 2
            try:
                status = self.status_reader()
                self.publisher_ready = status.get("ready") is True
                current_id = (status.get("source") or {}).get("id")
                if self.publisher_ready and current_id:
                    if self.publisher_id and current_id != self.publisher_id:
                        raise MasterStreamError("Master publisher identity changed")
                    self.publisher_id = current_id
            except (OSError, URLError, ValueError):
                self.publisher_ready = False
            if now - self.output_started > 12 and not self.publisher_ready:
                raise MasterStreamError("MediaMTX master path is not ready")
        for key, entry in list(self.inputs.items()):
            try:
                decoder = entry["decoder"]
                if decoder:
                    decoder.poll()
                    if getattr(decoder, 'finished', False) is True:
                        if key != self.active:
                            raise MasterStreamError('File ended before it was taken')
                        self._complete(key)
                        continue
                    if key == self.active:
                        self._start_armed(key, entry)
                    ready = decoder.ready()
                    if ready:
                        entry.pop("unready_since", None)
                    if entry.get("stalled_since") is not None and key != self.active:
                        # Cut away from (the station ID, a take): no picture to hold any more.
                        entry["stalled_since"] = None
                        decoder.ride_out(False)
                        self._publish(stall=None)
                    if key == self.recovering:
                        self._recover(key, entry, ready)
                    elif key == self.active and entry.get("stalled_since") is not None:
                        self._riding_out(key, entry, ready, now)
                    elif entry["was_ready"] and not ready:
                        if key == self.active:
                            if not self._ride_out(key, entry, now):
                                self._begin_recovery(key, entry)
                        # Off air, a fresh capture can pause or re-anchor its timestamps
                        # (DecodedInput resets its counts) while it settles. Like an on-air
                        # stall, it has a few seconds to become ready again.
                        elif now - entry.setdefault("unready_since", now) >= self.PREPARED_SETTLE_SECONDS:
                            raise MasterStreamError("Prepared input audio/video stopped arriving")
                    entry["was_ready"] = entry["was_ready"] or ready
                if now >= entry["check_at"]:
                    entry["url"] = entry["lease"].check()
                    entry["check_at"] = time.monotonic() + 2
                    if entry["was_ready"] and not entry["url"]:
                        raise MasterStreamError("Source stream is no longer ready")
            except MasterStreamError as exc:
                if key == self.ident_key and key != self.active:
                    self._ident_failed(str(exc))  # A cued ID failing is not a master error.
                    continue
                # An input that fails while master waits for it on the test card (its stall
                # recovery) was on air: the queue puts its program back on.
                failure = {"target": self._public(key), "error": str(exc), "at": time.time(),
                           "was_on_air": key in (self.active, self.recovering),
                           "during_recovery": key == self.recovering,
                           "tracks": decoder.status() if decoder and hasattr(decoder, 'status') else {}}
                logging.getLogger(__name__).warning("Master input failed: %s", json.dumps(failure))
                if key == self.active:
                    self.output.take(0)
                if entry.get("stalled_since") is not None:
                    self._publish(stall=None)
                self._drop(key)
                self._publish(error=str(exc), last_input_failure=failure)
        with self.lock:
            requested, self.ident_request = self.ident_request, None
            from_test_card, self.ident_from_test_card = self.ident_from_test_card, False
        if requested and now - requested < 2 and self._ends_first(self.active):
            logging.getLogger(__name__).info('Station ID waits for the end of %s', json.dumps(self._public(self.active)))
        elif requested and now - requested < 2 and self.active and self.active != self.ident_key:
            self._ident_after(self.active, 'schedule')
        elif requested and now - requested < 2 and self.active is None and from_test_card:
            if self._air_ident(None):  # Ends on its own: the next take, or back to the test card.
                logging.getLogger(__name__).info("Station ID started from the test card")
        self._hold_ident()
        self._programme_breaks()
        self._keep_ident()
        self._admute_tick()
        if hasattr(self.output, 'caption_status'):
            status = self.output.caption_status()
            if isinstance(status, dict):
                self._publish(captions={**status, 'error': self.caption_error or status.get('error')})
        self._refresh()

    # ------------------------------------------------------------ ad mute

    def _admute_tick(self):
        """Badge and break bed for the input on air. Never fails the output."""
        keep = []
        for deadline, key in self.retired_taps:
            if time.monotonic() >= deadline:
                self.admute.close_input(key)
            else:
                keep.append((deadline, key))
        self.retired_taps = keep
        try:
            self._admute_output()
        except Exception as exc:
            logging.getLogger(__name__).warning('Ad mute presentation failed: %s', exc)
        entry = self.inputs.get(self.active)
        status = self.admute.status(self.active) if entry and entry.get('tap') else None
        self._publish(admute={**self.admute.summary(), 'error': self.admute_error or self.admute.error,
                              'on_air': status and {k: status[k] for k in ('state', 'p_ad', 'override', 'fresh')},
                              'tapped': sorted(k for k, e in self.inputs.items() if e.get('tap'))})
        if getattr(self.output, 'shared_playout', False) is True:
            self._publish(my_ads={**(self.output.my_ads_status() or {'active': False, 'state': 'idle'}),
                                  'error': self.my_ads_error, 'promos_error': self.promos_error})

    def _admute_output(self):
        if getattr(self.output, 'shared_playout', False) is True:
            # Gain, the replacement bed and badge follow the delayed frame's source.
            # A selector change here would delay the replacement a second time.
            return
        if not hasattr(self.output, 'set_badge'):
            return
        conf = self.admute_conf
        entry = self.inputs.get(self.active)
        decoder = entry and entry.get('decoder')
        status = self.admute.status(self.active) if entry and entry.get('tap') else None
        intervals = []
        show = conf['badge'] == 'always' or (conf['badge'] == 'shadow' and conf['mode'] == 'shadow')
        if status and status['badge'] and show and decoder and conf['mode'] != 'off':
            start, end, label, p = status['badge']
            caption = (f'SHADOW · {round(100 * p)}%' if conf['mode'] == 'shadow' and p is not None
                       else 'MUTED' if conf['mode'] == 'on' else '')
            m_start = decoder.to_master(start)
            if m_start is not None:
                intervals.append((m_start, decoder.to_master(end) if end is not None else None, label, caption))
        if intervals != getattr(self, '_badge_shown', []):
            self.output.set_badge(intervals)
            self._badge_shown = intervals
        # The bed: while the programme on air is muted, the sound comes from slot 4.
        bed = False
        if status and conf['mode'] == 'on' and conf['sound'] == 'radio' and decoder:
            pts = decoder.from_master(self.output.running_time())
            bed = pts is not None and self.admute.peek(self.active, pts) < .5
        current = getattr(self.output, 'audio_slot', None)
        if bed and current != 4:
            self.output.set_bed(10 ** (conf['radio_db'] / 20))
            self.output.take_audio(4)
        elif not bed and current == 4:
            if entry:  # (a take or fallback already put the sound back with the picture)
                self.output.take_audio(entry['slot'])
            self.output.set_bed(0.)

    # ------------------------------------------------------------ crawl

    def _crawl(self):
        # Never fails the output: a bad alert or settings file leaves the crawl as it was.
        self.crawl_wake = False
        try:
            self._update_crawl()
        except Exception as exc:
            if not isinstance(exc, (OSError, ValueError, ConfigError)):
                logging.getLogger(__name__).exception('Crawl update failed')
            self._publish(crawl={**(self.snapshot.get('crawl') or {}), 'error': f'Crawl not updated: {exc}'})

    def _end_bulletin(self, how):
        with self.lock:
            bulletin, self.bulletin = self.bulletin, None
        if bulletin:
            self.bulletin_log = (self.bulletin_log + [{'key': bulletin['key'], 'how': how, 'at': time.time()}])[-10:]

    def _update_crawl(self):
        settings = self.crawl_settings.read()
        now = datetime.now(timezone.utc)
        eas = self.eas.alerts(tests=settings['eas_tests']) if self.eas else []
        nws = self.nws.alerts() if self.nws else []
        important, label, rotation, summaries = crawl.alert_layers(settings, eas, nws, now, self.config.eas_areas)
        content = crawl.compose(settings, important, label, now)
        with self.lock:
            bulletin = self.bulletin
            position, until = self.crawl_position
        position = position if time.monotonic() < until else 'bottom'
        if bulletin:
            finished = getattr(self.output, 'crawl_finished', lambda: None)()
            if finished == bulletin['key']:
                self._end_bulletin('done')
            elif time.monotonic() > bulletin['deadline']:
                self._end_bulletin('expired')
            elif content is not None:
                self._end_bulletin('preempted by ' + content['kind'])
            else:
                content = {key: bulletin[key] for key in ('kind', 'key', 'label', 'flag', 'style', 'passes', 'items')}
        if content is not None:
            content = {**content, 'position': position}
        if content != self.crawl_content and hasattr(self.output, 'set_crawl'):
            old = self.crawl_content
            # The same crawl with new words (a transcript arrived, the rotation's loop
            # changed) follows the running pass, and moved to the top or bottom slides there;
            # anything else cuts in at once.
            same = bool(old and content and old['key'] == content['key'])
            if content is not None or (old or {}).get('kind') != 'bulletin' or not old.get('passes'):
                self.output.set_crawl(content, restart=not same)
            self.crawl_content = content
            if (content or old or {}).get('kind') != 'bulletin':
                logging.getLogger(__name__).warning('Crawl %s: %s', 'updated' if content else 'cleared',
                                                    crawl.plain(content)[:300] or '-')
        with self.lock:
            bulletin = self.bulletin
        self._publish(crawl={
            'on_air': self.crawl_content is not None,
            'kind': (self.crawl_content or {}).get('kind'),
            'key': (self.crawl_content or {}).get('key'),
            'label': (self.crawl_content or {}).get('label'),
            'flag': (self.crawl_content or {}).get('flag') or '',
            'style': (self.crawl_content or {}).get('style'),
            # Where the bar runs (or would run): the rotation's choice while its lease lasts.
            'position': position,
            # The status reply is capped at 64 KB: the items once, without a plain-text copy.
            'items': (self.crawl_content or {}).get('items', [])[:40],
            'alerts': summaries,
            # Lesser alerts for the rotation's weather alerts segment (summaries, no transcripts).
            'rotation_alerts': rotation[:10],
            'bulletin': {'key': bulletin['key'], 'started': bulletin['started']} if bulletin else None,
            'bulletins_ended': self.bulletin_log,
            'eas': self.eas.status() if self.eas else None,
            'nws': self.nws.status() if self.nws else None,
            'error': None})

    # ------------------------------------------------------------ a show's ad breaks
    # A file queued with ad breaks (library.py, library_breaks.py) stops at each act break
    # found by its scan: My ads (and station promos) play over its held frame for about the
    # length asked, the ad on air plays out, and the show goes on from the break.
    #   play ─(BREAK_PRIME s before)─▶ primed: the break's first ad is cued
    #        ─(BREAK_ARM s before)───▶ armed: the file stops passing media on at the break,
    #                                  or, with nothing to show, the break is skipped
    #        ─(the break's frame)────▶ held: frozen, the fill window open (ad_break.AdBreak)
    #        ─(the break's time)─────▶ play, from the break's resume point; ads go on over it
    #                                  until the show's first frame airs (a programme delay on)
    BREAK_PRIME = 15
    BREAK_ARM = 2
    BREAK_OVERRUN = 15   # the show waits for an ad that ends at most this long past the break's length

    def _break_plan(self, lease):
        points = cached_breaks(cache_path(self.app_config), lease.target['channel_id'], lease.generation) or []
        if not points:
            logging.getLogger(__name__).warning('No ad breaks are known for %s: it plays straight through',
                                                lease.target['channel_id'])
        return {'points': sorted(points, key=lambda p: p['at']), 'seconds': lease.target['ad_breaks'],
                'index': 0, 'state': 'play', 'aired': 0, 'skipped': 0, 'since': None}

    def _break_status(self, plan):
        left = len(plan['points']) - plan['index']
        held = plan['state'] == 'held' and plan['since'] is not None
        current = max(0., plan['seconds'] - (time.monotonic() - plan['since'])) if held else 0.
        return {'seconds': plan['seconds'], 'count': len(plan['points']), 'aired': plan['aired'],
                'skipped': plan['skipped'], 'state': plan['state'],
                'next_at': plan['points'][plan['index']]['at'] if left > 0 else None,
                # Time still to come in breaks, for Up next's sums: this one's rest and the others.
                'left_seconds': round(current + plan['seconds'] * (left - (1 if held else 0)), 1)}

    def _programme_breaks(self):
        key = self.active
        entry = self.inputs.get(key) if key and key != self.ident_key else None
        plan = entry.get('breaks') if entry else None
        decoder = entry['decoder'] if entry else None
        if not plan or not decoder or not hasattr(decoder, 'stop_at') or not getattr(decoder, 'started', False):
            return
        log, breaks = logging.getLogger(__name__), self._ad_break()
        if plan['state'] == 'held':
            # The show comes back on the input side at the break's time, or where the ad on air
            # then ends (if soon after); what airs is a programme delay behind, and the ads
            # carry on over it until the show's first frame (ad_break.fill_resume).
            if breaks is not None and breaks.fill_status() is not None:
                report = breaks.fill_end()
                due = plan['frozen_at'] + int(plan['seconds'] * 1e9)
                if report and report.get('empty'):
                    due = report['end']
                elif report:
                    due = max(due, min(report['end'], due + int(self.BREAK_OVERRUN * 1e9)))
                if self.output.running_time() < due:
                    return
            point = plan['points'][plan['index']]
            decoder.thaw(point['resume'])
            if breaks is not None and isinstance(getattr(decoder, 'floor', None), int):
                breaks.fill_resume(decoder.floor)
            plan.update(state='play', index=plan['index'] + 1, aired=plan['aired'] + 1, since=None)
            log.info('Ad break %d of %d over: the show goes on from %.1f s', plan['index'], len(plan['points']),
                     point['resume'])
            return
        if plan['index'] >= len(plan['points']):
            return
        point = plan['points'][plan['index']]

        def skip(why):
            decoder.stop_at(None)
            if breaks is not None:
                breaks.fill_unprime()
            plan.update(state='play', index=plan['index'] + 1, skipped=plan['skipped'] + 1)
            log.warning('Ad break at %.1f s skipped: %s', point['at'], why)

        if plan['state'] == 'armed':
            if not getattr(decoder, 'stopped', False):
                return
            if breaks is not None and decoder.freeze():
                breaks.fill_start(decoder.frozen_at, length=plan['seconds'])
                plan.update(state='held', since=time.monotonic(), frozen_at=decoder.frozen_at)
                log.info('Ad break %d of %d at %.1f s: about %d s of ads', plan['index'] + 1, len(plan['points']),
                         point['at'], plan['seconds'])
            else:
                skip('the file could not hold its picture')
            return
        position = decoder.progress().get('position_seconds')
        if position is None:
            return
        if position > point['at'] + 1:
            plan['index'] += 1   # already past it (a file started partway through)
            return
        if plan['state'] == 'play' and position >= point['at'] - self.BREAK_PRIME:
            if breaks is None:
                return skip('master has no ad breaks')
            breaks.fill_prime()
            plan['state'] = 'primed'
        if plan['state'] == 'primed' and position >= point['at'] - self.BREAK_ARM:
            if not (self._fills() and breaks.fill_ready()):
                return skip('none of My ads or station promos may play now')
            decoder.stop_at(point['at'])
            plan['state'] = 'armed'

    # ------------------------------------------------------------ station ID

    def _ad_break(self):
        """Master's ad breaks (ad_break.AdBreak), which fill a wait; None without one."""
        return getattr(self.output, 'ad_break', None) if self.output is not None else None

    def _fills(self):
        """Whether a wait would be filled: My ads or station promos are switched on."""
        breaks = self._ad_break()
        return bool(breaks and (getattr(breaks, 'ads_on', False) or getattr(breaks, 'promos_on', False)))

    def _end_fill(self):
        """Close the wait fill now (the ID left air, or gave up holding)."""
        fill, self.ident_fill = self.ident_fill, None
        breaks = self._ad_break()
        if fill is not None and breaks is not None:
            try:
                breaks.fill_stop(self.output.running_time())
            except Exception:  # No clock: the next airing's window replaces this one.
                logging.getLogger(__name__).warning('The wait fill could not be closed', exc_info=True)

    def _hold_ident(self):
        """Hold the ID's end card while the next source is prepared, with ads over it (the
        wait fill); once it is ready (the hold is released), iris out when the ad on air
        ends, or play the join bumper there and leave the take to land at its end. After
        the limit, iris out regardless."""
        entry = self.inputs.get(self.ident_key) if self.active and self.active == self.ident_key else None
        decoder = entry and entry["decoder"]
        if not decoder or not hasattr(decoder, "freeze"):
            return
        log = logging.getLogger(__name__)
        now = time.monotonic()
        with self.lock:
            until, join = self.ident_hold_until, self.ident_join
        wanted = until is not None and now < until
        breaks = self._ad_break()
        if getattr(decoder, "frozen", False):
            if wanted:
                return
            fill = self.ident_fill
            if fill is None or breaks is None:
                decoder.thaw()
                log.info("Station ID released its end card")
                return
            if until is not None:  # Out of time: the ID irises out, whatever fills it.
                self._end_fill()
                decoder.thaw()
                log.warning("Station ID gave up holding its end card for the next source")
                return
            running = self.output.running_time()
            if not fill['finishing']:
                fill['finishing'] = True
                if not breaks.fill_finish(running, join):
                    self._end_fill()
                    decoder.thaw()
                    return
                log.info("The next source is ready: %s", 'the join bumper follows the wait fill' if join
                         else 'the station ID irises out after the wait fill')
            report = breaks.fill_end()
            if report and not report['take'] and running >= report['end']:
                decoder.thaw()  # The fill has ended: the iris (or the Sports ID after it), then the take.
                self.ident_fill = None  # Its window closes there on its own.
                log.info("Station ID released its end card after the wait fill")
            elif report and report['take'] and running >= report['end'] + self.JOIN_TAKE_GRACE_NS:
                self._end_fill()  # The take never came (cancelled, or it failed): iris out.
                decoder.thaw()
                log.warning("No take followed the join bumper: the station ID irises out")
            return
        position = decoder.progress().get("position_seconds") or 0
        # A join bumper only takes the end card's place: once the iris has begun, it is too late.
        joining = join is not None and position <= IDENT_HOLD_AT + JOIN_FREEZE_SLACK and breaks is not None
        if (wanted or joining) and position >= IDENT_HOLD_AT:
            if decoder.freeze():
                log.info("Station ID holding its end card for the next source%s",
                         ' (the join bumper next)' if not wanted else ' (ads over it)' if self._fills() else '')
                frozen_at = getattr(decoder, 'frozen_at', None)
                if breaks is not None and isinstance(frozen_at, int) and (self._fills() or not wanted):
                    breaks.fill_start(frozen_at)
                    self.ident_fill = {'finishing': False}

    def _fill_status(self):
        """The wait fill for the status: filling, or finishing with where it ends (ends_in
        seconds from now on master's clock; take: the take lands there, after the bumper)."""
        breaks, fill = self._ad_break(), self.ident_fill
        if fill is None or breaks is None:
            return None
        report = breaks.fill_end()
        try:
            ends_in = round((report['end'] - self.output.running_time()) / 1e9, 3) if report else None
        except Exception:
            ends_in = None
        return {'state': 'finishing' if fill['finishing'] else 'filling', 'take': bool(report and report['take']),
                'fixed': bool(report and report['fixed']), 'ends_in': ends_in}

    def _ident_status(self):
        entry = self.inputs.get(self.ident_key)
        return {"enabled": bool(self.ident_path), "ready": self._ident_ready(),
                "on_air": self.active is not None and self.active == self.ident_key,
                "held": bool(entry and entry["decoder"] and getattr(entry["decoder"], "frozen", False)),
                "file": Path(entry["lease"].path).name if entry else None,
                "duration_seconds": entry.get("duration") if entry else None, "error": self.ident_error,
                "fill": self._fill_status()}

    def _ident_ready(self):
        entry = self.inputs.get(self.ident_key)
        return bool(entry and self.active != self.ident_key and entry["decoder"]
                    and getattr(entry["decoder"], "cued", False))

    def _ident_failed(self, error):
        logging.getLogger(__name__).warning("Station ID unavailable: %s", error)
        if self.ident_key and self.ident_key != self.active:
            self._drop(self.ident_key)
        self.ident_error = error
        self.ident_retry_at = time.monotonic() + self.IDENT_RETRY_SECONDS

    def _continuity_file(self, path):
        """An announcement written by the continuity service: an .mp4 in its directory."""
        state = getattr(getattr(self, 'app_config', None), 'state_file', None)
        if state is None:
            return False
        folder = (Path(state).parent / 'continuity').resolve()
        path = path.resolve()
        return path.suffix == '.mp4' and path.parent == folder and path.is_file()

    def _keep_ident(self):
        """Keep the station ID decoded and parked at its start in slot 3, ready to cut to:
        the announcement version when continuity asked for one, else the plain ID."""
        if not self.ident_path:
            return
        entry = self.inputs.get(self.ident_key)
        now = time.monotonic()
        with self.lock:
            override = self.ident_override
        wanted = override if override and override.is_file() else self.ident_path
        try:
            if entry and self.active != self.ident_key and Path(entry["lease"].path) != Path(wanted):
                self._drop(self.ident_key)  # Swap the cued copy for the one wanted next.
                entry, self.ident_retry_at = None, 0.
            if entry and self.active != self.ident_key and now >= entry["ident_check_at"]:
                entry["ident_check_at"] = now + 2
                if not entry["lease"].current():  # Rebuilt or removed: replace the cued copy.
                    self._drop(self.ident_key)
                    entry, self.ident_retry_at = None, 0.
            if entry is None:
                if (self.busy or now < self.ident_retry_at or not self.publisher_ready
                        or not self.output.healthy()):
                    return
                try:
                    lease = IdentLease(wanted)
                except OSError:
                    self.ident_retry_at = now + 5  # No file: the ID is switched off.
                    return
                key = uuid.uuid4().hex
                self.inputs[key] = entry = {"lease": lease, "decoder": None, "slot": IDENT_SLOT, "was_ready": False,
                                            "check_at": 0, "url": lease.uri, "ident_check_at": now + 2,
                                            "deadline": now + self.IDENT_PREPARE_SECONDS}
                self.ident_key = key
                entry["decoder"] = self.file_decoder_factory(self.output, IDENT_SLOT, lease.uri)
                return
            decoder = entry["decoder"]
            if decoder.started or decoder.cued:
                return
            if decoder.ready():
                decoder.cue()
                entry["duration"] = decoder.progress().get("duration_seconds") or IDENT_SECONDS
                self.ident_error = None
            elif now >= entry["deadline"]:
                raise MasterStreamError("Station ID did not decode in time")
        except MasterStreamError as exc:
            self._ident_failed(str(exc))

    def _air_ident(self, previous):
        """Cut to the cued station ID. An input armed to follow `previous` follows the ID instead."""
        if not self._ident_ready():
            logging.getLogger(__name__).warning('Station ID not played: it is not cued (%s)', self.ident_error or 'still decoding')
            return False
        key = self.ident_key
        entry = self.inputs[key]
        try:
            self._start_file(entry)  # Blocks briefly until its first frames arrive.
        except MasterStreamError as exc:
            self._ident_failed(f"Station ID could not start: {exc}")
            return False
        self.output.take(entry["slot"])
        self.active = key
        aired = Path(entry["lease"].path)
        with self.lock:
            if self.arm and self.arm[1] == previous:
                self.arm = (self.arm[0], key)
            if self.ident_override and Path(self.ident_override) == aired:
                self.ident_override = None  # An announcement plays once.
        self._publish(last_station_id={"at": time.time(), "after": self._public(previous), "file": aired.name})
        return True

    def _ident_after(self, key, reason):
        """Replace on-air input `key` with the station ID now; False leaves it on air."""
        completed = {"target": self._public(key), "input_id": key, "at": time.time()}
        if not self._air_ident(key):
            return False
        is_file = isinstance(self.inputs[key]["lease"], FileLease)
        self._drop(key)
        logging.getLogger(__name__).info("Station ID replaced the end of %s (%s)", completed["target"], reason)
        if is_file:
            self._publish(last_completed={**completed, "next_input_id": self.ident_key, "cut_for_station_id": True})
        return True

    def _ends_first(self, key):
        """A recording on air that ends within the ID's length keeps its ending: asked for
        the ID before a timed entry, it plays out and the ID follows it (_complete)."""
        entry = self.inputs.get(key) if key and key != self.ident_key else None
        if not entry or not isinstance(entry["lease"], FileLease) or not self._ident_ready():
            return False
        media = entry["decoder"].progress()
        position, duration = media.get("position_seconds"), media.get("duration_seconds")
        length = self.inputs[self.ident_key].get("duration") or IDENT_SECONDS
        return position is not None and bool(duration) and duration - position <= length

    def _armed_next(self, key):
        """The prepared file waiting for on-air input `key` to end, if any."""
        with self.lock:
            arm = self.arm
        if arm and arm[1] == key and arm[0] == self.prepared and arm[0] in self.inputs and not self.busy:
            return self.inputs[arm[0]]
        return None

    def _start_armed(self, key, entry):
        following = self._armed_next(key)
        if not following or not getattr(following['decoder'], 'cued', False):
            return
        if key != self.ident_key and self._ident_ready():
            return  # The ID follows this file; the next one starts as the ID ends.
        media = entry['decoder'].progress() if hasattr(entry['decoder'], 'progress') else {}
        position, duration = media.get('position_seconds'), media.get('duration_seconds')
        if position is not None and duration and duration - position <= self.NEXT_FILE_LEAD:
            try:
                self._start_file(following)  # Blocks briefly until its first frames arrive.
            except MasterStreamError as exc:
                logging.getLogger(__name__).warning('Next file could not start: %s', exc)
                self._drop(self.prepared)

    def _complete(self, key):
        """The on-air file ended: the station ID follows a program (keeping whatever is armed
        for after it); otherwise cut to the armed next file, or to fallback."""
        completed = {'target': self._public(key), 'input_id': key, 'at': time.time()}
        if key != self.ident_key and self._air_ident(key):
            completed['next_input_id'] = self.ident_key
            self._drop(key)
            logging.getLogger(__name__).info('Master file completed: %s', json.dumps(completed))
            self._publish(last_completed=completed)
            return
        following = self._armed_next(key)
        taken = None
        if following:
            try:
                self._start_file(following)
                self.output.take(following['slot'])
                taken = self.prepared
            except MasterStreamError as exc:
                logging.getLogger(__name__).warning('Next file could not start: %s', exc)
                self._drop(self.prepared)
        if taken:
            self.active, self.prepared = taken, None
            with self.lock:
                self.arm = None
            completed['next_input_id'] = taken
        else:
            self.output.take(0)
            self.active = None
        self._drop(key)
        logging.getLogger(__name__).info('Master file completed: %s', json.dumps(completed))
        self._publish(last_completed=completed)

    def _start_file(self, entry):
        decoder = entry['decoder']
        if not decoder.started:
            if not decoder.cued:
                decoder.cue()
            decoder.start()
        deadline = time.monotonic() + decoder.START_TIMEOUT
        while not decoder.ready():
            decoder.poll()
            if time.monotonic() >= deadline:
                raise MasterStreamError('File did not start playing')
            if self.stopping.wait(.01):
                raise MasterStreamError('Worker stopping')

    def _prepare(self, target):
        is_roku = target['source_id'] in ROKU_SOURCE_IDS
        is_file = target['source_id'] == LIBRARY_SOURCE_ID
        after = target.pop('after_input_id', None) if is_file else None
        if not is_roku and not is_file and not self.tv_enabled:
            raise MasterStreamError("TV-Thing is disabled")
        if self.prepared:
            self._drop(self.prepared)
        lane = ('roku' if is_roku else 'library' if is_file
                else "digital" if target["source_id"] == "tv-thing-digital" else "analog")
        active = self.inputs.get(self.active)
        # Preparing another channel on the SAME tuner cannot preserve the old
        # feed. This behavior is stated next to the UI's Prepare action.
        # Files are independent: any number can be open at once.
        if active and active["lease"].lane == lane and not is_file:
            self._fallback()
        try:
            if is_file:
                try:
                    lease = FileLease(self.library_config, target)
                except (ConfigError, OSError) as exc:
                    raise MasterStreamError(str(exc)) from exc
            else:
                if is_roku:
                    handoff = target.pop('roku', None)
                    lease = RokuLease.adopt(self.tv, target, handoff)
                else:
                    lease = self.tv.acquire(target)
        except MasterStreamError as exc:
            if exc.details.get('http_status') == 423:
                # An explicit lease refusal happened before any tune command.
                raise ControlBusyError(str(exc)) from exc
            raise
        key = uuid.uuid4().hex
        used = {entry["slot"] for entry in self.inputs.values()}
        slot = next(s for s in (1, 2) if s not in used)
        entry = {"lease": lease, "decoder": None, "slot": slot, "was_ready": False, "check_at": 0, "url": None}
        self.inputs[key] = entry
        try:
            if self.cancel.is_set() or self.stopping.is_set():
                raise MasterStreamError("Preparation cancelled")
            lease.tune()
            deadline = time.monotonic() + (20 if is_file else 40)
            ready_since = None
            while time.monotonic() < deadline:
                if self.cancel.is_set() or self.stopping.is_set():
                    raise MasterStreamError("Preparation cancelled")
                self._tick()
                if key not in self.inputs:
                    raise MasterStreamError(self.status().get("error") or "Input preparation failed")
                if entry["url"] and entry["decoder"] is None:
                    factory = self.file_decoder_factory if is_file else self.decoder_factory
                    if is_file and getattr(lease, 'audio_tracks', 1) > 1:
                        entry["decoder"] = factory(self.output, slot, entry["url"], select_audio=True)
                    elif not is_file and lane_enabled(self.admute_conf, lane):
                        # Ad mute analyses this input; the programme plays the lookahead behind.
                        entry["tap"] = self.admute.open_input(key, {
                            **{k: v for k, v in lease.target.items() if isinstance(v, (str, int, float))},
                            'lane': lane, 'lookahead': float(self.admute_conf['lookahead']),
                            'range': 'limited', 'fps': self.config.fps})
                        entry["decoder"] = factory(self.output, slot, entry["url"], tap=entry["tap"])
                    else:
                        entry["decoder"] = factory(self.output, slot, entry["url"])
                if entry["decoder"] and entry["decoder"].ready():
                    if ready_since is None:
                        ready_since = time.monotonic()
                    if is_roku and time.monotonic() - ready_since < 2:
                        self.stopping.wait(.05)
                        continue
                    lease.renew(force=True)
                    if not lease.check():
                        raise MasterStreamError("Source readiness changed during preparation")
                    if is_file:
                        entry["decoder"].cue()  # Decodes; now wait at the start for the take.
                        if lease.target.get('ad_breaks'):
                            entry["breaks"] = self._break_plan(lease)
                    self.prepared = key
                    if is_file and after:
                        with self.lock:
                            self.arm = (key, after)
                    return
                ready_since = None  # A Roku feed must stay ready for 2 unbroken seconds.
                self.stopping.wait(.05)
            raise MasterStreamError("Timed out waiting for source audio and video")
        except BaseException:
            self._drop(key)
            raise

    def _take(self, body):
        key = self.prepared
        if key is None or body.get("prepared_id") != key:
            raise MasterStreamError("Prepared input changed; refresh before taking")
        entry = self.inputs[key]
        entry["lease"].renew(force=True)
        if not entry["lease"].check() or not entry["decoder"].ready():
            raise MasterStreamError("Prepared input is no longer ready")
        if self.cancel.is_set():
            raise MasterStreamError("Take cancelled")
        if isinstance(entry["lease"], FileLease):
            self._start_file(entry)
        old = self.active
        self.output.take(entry["slot"])
        self.active, self.prepared = key, None
        if old:
            if self.inputs.get(old, {}).get("stalled_since") is not None:
                self._publish(stall=None)
            self._drop(old)

    def run(self):
        backoff = 1
        self.admute.start()
        if self.radio_info:
            self.radio_info.start()
        if self.eas:
            self.eas.start()
        if self.nws:
            self.nws.start()
        try:
            while not self.stopping.is_set():
                try:
                    if self.output is None:
                        self.production_card = None
                        self.production_clock = None
                        self.production_checked = 0
                        self.crawl_content = None
                        self.output = self.media_factory(self.config.rtsp_url, width=self.config.width,
                                                        height=self.config.height, fps=self.config.fps, bitrate=self.config.bitrate,
                                                        radio_url=self.config.off_air_radio_url,
                                                        radio_gain_db=self.config.off_air_radio_gain_db,
                                                        encoder=self.config.encoder)
                        self.output_started = time.monotonic()
                        self.publisher_id = None
                        self.next_status = 0
                    self._tick()
                    if self.publisher_ready and self.output.healthy():
                        backoff = 1
                    try:
                        action, body, operation_id = self.commands.get(timeout=.05)
                    except queue.Empty:
                        continue
                    error = None
                    error_code = None
                    try:
                        # An explicit command supersedes recovery of the old selection.
                        if self.recovering:
                            self._drop(self.recovering)
                        if action == "prepare":
                            self._prepare(body)
                        elif action == "take":
                            self._take(body)
                        elif action == "cancel" and self.prepared:
                            self._drop(self.prepared)
                    except Exception as exc:
                        error = str(exc)
                        error_code = getattr(exc, 'code', None)
                    finally:
                        if self.cancel.is_set() and self.prepared:
                            self._drop(self.prepared)
                            error = error or "Preparation cancelled"
                        # Drain fallback requests while still marked busy. A
                        # request arriving during lease cleanup cannot be lost.
                        while True:
                            with self.lock:
                                fallback = self.pending_fallback
                                self.pending_fallback = False
                                if not fallback:
                                    self.busy = False
                                    self.snapshot["operation"] = {"id": operation_id, "action": action,
                                                                  "state": "failed" if error else "succeeded", "error": error,
                                                                  "error_code": error_code}
                                    self.snapshot["error"] = error
                                    break
                            self._fallback()
                        self._refresh()
                except Exception as exc:
                    self._publish(state="reconnecting", error=str(exc), can_take=False, can_prepare=False,
                                  publisher_ready=False, on_air=None, prepared=None)
                    for key in list(self.inputs):
                        self._drop(key)
                    if self.output:
                        self.output.close()
                        self.output = None
                    self.publisher_ready = False
                    # A command accepted immediately before a failure must not
                    # tune after reconnect or remain permanently pending.
                    with self.lock:
                        if (self.snapshot.get("operation") or {}).get("state") == "pending":
                            self.snapshot["operation"].update(state="failed", error=str(exc))
                        while not self.commands.empty():
                            action, _, op_id = self.commands.get_nowait()
                            self.snapshot["operation"] = {"id": op_id, "action": action, "state": "failed", "error": str(exc)}
                        self.busy = False
                    self.stopping.wait(backoff)
                    backoff = min(15, backoff * 2)
        finally:
            self.admute.stop()
            if self.radio_info:
                self.radio_info.stop()
            if self.eas:
                self.eas.stop()
            if self.nws:
                self.nws.stop()
            for key in list(self.inputs):
                self._drop(key)
            if self.output:
                self.output.close()
            self._publish(state="stopped", on_air=None, prepared=None, can_take=False, can_prepare=False, publisher_ready=False)


class MasterClient:
    def __init__(self, config):
        self.config = config

    def request(self, action="status", body=None):
        if not self.config.enabled:
            if action == "status":
                return {"state": "not_configured", "can_prepare": False, "can_take": False}
            raise MasterStreamError("Master worker is disabled")
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(2)
                connection.connect(str(self.config.socket_path))
                connection.sendall(json.dumps({"action": action, "body": body or {}}).encode() + b"\n")
                with connection.makefile("rb") as stream:
                    raw = stream.readline(65537)
            if len(raw) > 65536:
                raise ValueError("Worker response too large")
            result = json.loads(raw)
        except (OSError, ValueError) as exc:
            if action == "status":
                return {"state": "unavailable", "can_prepare": False, "can_take": False,
                        "error": "Master worker is unavailable"}
            raise MasterStreamError("Master worker is unavailable; refresh status before retrying") from exc
        if "error" in result and result.get("ok") is False:
            error_type = ConfigError if result.get("code") == ConfigError.code else MasterStreamError
            raise error_type(result["error"])
        return result


@contextmanager
def control_socket(worker):
    path = worker.config.socket_path
    path.parent.mkdir(parents=True, exist_ok=True)
    # flock survives stale socket files and prevents a second worker from
    # unlinking the first worker's socket or publishing to the same endpoint.
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MasterStreamError("A master worker already owns this control socket") from exc
        path.unlink(missing_ok=True)
        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                self.connection.settimeout(2)
                try:
                    raw = self.rfile.readline(8193)
                    if len(raw) > 8192:
                        raise ConfigError("Master command too large")
                    request = json.loads(raw)
                    action, body = request.get("action"), request.get("body", {})
                    if not isinstance(body, dict):
                        raise ConfigError("Master body must be an object")
                    result = (worker.status() if action == "status" else
                              worker.preview(body.get('input_id')) if action == 'preview' else worker.submit(action, body))
                except Exception as exc:
                    result = {"ok": False, "error": str(exc), "code": getattr(exc, "code", "master_stream_error")}
                try:
                    self.wfile.write(json.dumps(result).encode() + b"\n")
                except OSError:
                    pass
        class Server(socketserver.UnixStreamServer):
            # Local handlers only submit work or return a snapshot, never wait
            # on hardware. A bounded serial server avoids unbounded threads.
            pass
        server = Server(str(path), Handler)
        os.chmod(path, 0o600)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .1}, daemon=True)
        thread.start()
        try:
            yield
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            path.unlink(missing_ok=True)
    finally:
        os.close(fd)


def serve_worker(config):
    if not config.master.enabled:
        raise ConfigError("Set master.enabled to true in the candidate configuration")
    gst = _gst()
    from .master import BENCH_ELEMENTS, LIVE_ELEMENTS
    missing = [name for name in BENCH_ELEMENTS + LIVE_ELEMENTS if gst.ElementFactory.find(name) is None]
    if missing or gst.version()[:2] < (1, 22):
        raise MasterStreamError("Master worker requires GStreamer 1.22+ and all master-check plugins", details={"missing": missing})
    worker = MasterWorker(config, ident_path=IDENT_PATH)
    import signal
    previous = {}
    def stop(_signum, _frame):
        worker.cancel.set()
        worker.stopping.set()
    for signum in (signal.SIGINT, signal.SIGTERM):
        previous[signum] = signal.signal(signum, stop)
    try:
        with control_socket(worker):
            worker.run()
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
