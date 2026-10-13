from __future__ import annotations


import hmac
import json
import re
import shutil
import threading
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
import urllib.request

from .baseball import BaseballCatalog
from .config import AppConfig
from .tv_control import TvControl
from .tv_roku import RokuHold, TvRoku
from .errors import (
    BaseballScheduleError,
    ChannelNotFoundError,
    ConfigError,
    ControlBusyError,
    CueCancelledError,
    EcpError,
    NavigationError,
    RokuNotReadyError,
    RokuStreamError,
)
from .scheduler import Scheduler, parse_time
from .playout_queue import PlayoutQueue
from .sources import SourceCatalog
from .networks import Networks
from .tv_thing import SourceUnavailableError
from .master import MasterStreamError
from .master_worker import MasterClient
from .source_coordinator import SourceCoordinator
from .source_queue import SourceQueue, QueueSchedules, QueuePrograms
from .master_preview import MasterPreview
from .input_preview import InputPreview
from .production import ProductionSettings
from .caption_settings import CaptionSettings, MODELS as CAPTION_MODELS, LANGUAGES as CAPTION_LANGUAGES
from .admute_settings import AdMuteSettings
from . import my_ads as my_ads_module
from .my_ads import MyAds
from .promos import PromoDesk, Promos
from . import promos as promos_module
from .crawl import AREA_NAMES, CONTEXTS, MODES, SEGMENTS, CrawlSettings, FeedSettings
from .crawl_desk import CrawlDesk
from .crawl_ledger import CrawlLedger
from . import crawl_feeds
from .production_monitor import ProductionMonitor
from . import playback
from .continuity import Continuity, Voice
from .ident import ident_file
from .programming import Programming
from .sports import SportsCatalog
from .library import MediaLibrary


_STATIC_PATH = Path(__file__).with_name("static")
# The web UI: one HTML file per page and its scripts and styles, all in static/ui/. New files
# there are served without a restart (the pattern below), so the UI can grow while it runs.
_UI_PATH = _STATIC_PATH / "ui"
PAGES = ("/air", "/sources", "/schedule", "/crawl", "/presentation", "/ads", "/engineering", "/sonic")
# Addresses from before the control-room UI, and where they went. A fragment survives the
# redirect, so production#crawl reaches presentation, which forwards it to crawl. Ad mute and
# My ads became tabs of Ads (with the ad database) on 2026-10-04.
MOVED = {"/": "air", "/cue-sheet": "air", "/production": "presentation", "/continuity": "presentation#continuity",
         "/admute": "ads#admute", "/my-ads": "ads#my-ads",
         # The Roku's capture and calibration moved to TV Thing on 2026-10-06.
         "/calibration": "engineering#roku"}
# Routes of the Roku controller VizelVision ran until 2026-10-06. TV Thing's Roku lane
# does all of this now (its roku.html page and /api/v1/roku API); these answer 410.
ROKU_MOVED_GET = ("/v1/preview", "/v1/roku/signal", "/v1/roku/calibration", "/v1/roku/capture",
                  "/v1/roku/sources", "/v1/state")
ROKU_MOVED_POST = ("/v1/play", "/v1/thursday-night-football/play", "/v1/sunday-ticket/find",
                   "/v1/sunday-ticket/calibrate", "/v1/sunday-ticket/play", "/v1/baseball/play",
                   "/v1/calibrate", "/v1/calibrate-profile", "/v1/calibrate-network",
                   "/v1/calibrate-current-network", "/v1/verify", "/v1/roku/source")


def roku_operation(roku):
    """The Roku's navigation, as the old /v1/operation summary: TV Thing's operation."""
    if roku is None:
        return {"active": False, "phase": "idle", "message": "The Roku is TV Thing's; it is not configured here"}
    try:
        lane, lock = roku.lane()
    except MasterStreamError as exc:
        return {"active": False, "phase": "unavailable", "message": str(exc)}
    operation = (lane.get("roku") or {}).get("operation") or {}
    selection = lane.get("selection") or {}
    target = operation.get("target") or {}
    return {"active": bool(operation.get("active")), "phase": operation.get("phase") or operation.get("state") or "idle",
            "message": operation.get("message") or ("Roku idle" if not operation else operation.get("state")),
            "channel": target.get("channel_id") or selection.get("channel_id"), "provider": target.get("source_id"),
            "error": operation.get("error"), "state": operation.get("state"),
            "selection": selection or None, "lock": lock}


def roku_last_game(roku):
    """The baseball game the Roku last verified, for an after_game release with no game named."""
    known = roku.snapshot() if roku is not None else None
    target = (known or {}).get("target") or {}
    if target.get("source_id") != "mlb" or not str(target.get("channel_id", "")).isdecimal():
        return None
    return {"game_pk": int(target["channel_id"]), "game_date": target.get("date")}
_UI_FILE = re.compile(r"/static/ui/[a-z0-9-]+\.(js|css)")
# The sonic identity's reference renders (ident/sonic.py).
_SONIC_PATH = Path(__file__).resolve().parent.parent / "ident" / "build" / "sonic"


def _error_status(error: RokuStreamError) -> HTTPStatus:
    if isinstance(error, (ControlBusyError, CueCancelledError)):
        return HTTPStatus.CONFLICT
    if isinstance(error, ChannelNotFoundError):
        return HTTPStatus.NOT_FOUND
    if isinstance(error, ConfigError):
        return HTTPStatus.BAD_REQUEST
    if isinstance(error, RokuNotReadyError):
        return HTTPStatus.SERVICE_UNAVAILABLE
    if isinstance(error, BaseballScheduleError):
        return HTTPStatus.BAD_GATEWAY
    if isinstance(error, (SourceUnavailableError, MasterStreamError)):
        return HTTPStatus.SERVICE_UNAVAILABLE
    if isinstance(error, (EcpError, NavigationError)):
        return HTTPStatus.BAD_GATEWAY
    return HTTPStatus.INTERNAL_SERVER_ERROR


def handler_factory(
    config: AppConfig,
    roku: TvRoku | None,
    scheduler: Scheduler,
    baseball: BaseballCatalog | None = None,
    playout: PlayoutQueue | None = None,
    sources: SourceCatalog | None = None,
    coordinator: SourceCoordinator | None = None,
    programming: Programming | None = None,
    sports: SportsCatalog | None = None,
    production_monitor: ProductionMonitor | None = None,
    projector: playback.Projector | None = None,
    continuity: Continuity | None = None,
    crawl_desk: CrawlDesk | None = None,
    promo_desk: PromoDesk | None = None,
) -> type[BaseHTTPRequestHandler]:
    master = coordinator or MasterClient(config.master)
    master_preview = MasterPreview(config.master)
    input_preview = InputPreview(coordinator.master if coordinator else master)
    queue_programs = QueuePrograms(sources) if sources else None
    production = ProductionSettings(config.master)
    caption_settings = CaptionSettings(config.master.socket_path)
    crawl_settings = CrawlSettings(config.master)
    feed_settings = FeedSettings(config.master)
    admute_settings = AdMuteSettings(config.master.socket_path)
    admute_dir = Path(config.master.socket_path).parent
    worker_client = MasterClient(config.master)
    my_ads = MyAds(config.master.socket_path)
    # Station promos (promos.py): the desk keeps their live values; without one (tests), a quiet one.
    promo_desk = promo_desk or PromoDesk(Promos(config.master.socket_path), master=master, start_worker=False)

    def captions_view():
        error, status = None, None
        try:
            result = master.request()
            status = result.get('captions')
            if result.get('state') in ('unavailable', 'not_configured'):
                error = result.get('error') or 'The master worker is not configured'
            elif result.get('state') in ('starting', 'reconnecting'):
                error = 'Waiting for the master publisher to reconnect'
                status = None
            elif status is None:
                error = 'Restart the master worker to load live-caption support'
        except Exception as exc:
            error = f'Master is unavailable: {exc}'
        return {'settings': caption_settings.read(), 'status': status, 'master_error': error,
                'models': list(CAPTION_MODELS), 'languages': CAPTION_LANGUAGES}

    def admute_view():
        """Settings, what the master worker applies, and what the detector sidecar sees."""
        delay = None
        try:
            status = master.request()
            worker, on_air = status.get('admute'), status.get('on_air')
            # The shared programme delay: what the detector saw that long ago is on master now.
            delay = ((status.get('captions') or {}).get('programme_delay') or {}).get('seconds')
        except Exception as exc:
            worker, on_air = {'error': f'Master is unavailable: {exc}'}, None
        try:
            detector = json.loads((admute_dir / 'admute-state.json').read_text())
            stale = time.time() - float(detector.get('updated') or 0) > 10
        except (OSError, ValueError):
            detector, stale = None, True
        labels = []
        try:
            with open(admute_dir / 'admute-labels.jsonl', 'rb') as f:
                f.seek(0, 2)
                start = max(0, f.tell() - 65536)
                f.seek(start)
                lines = f.read().splitlines()[1 if start else 0:]  # mid-file, the first line is partial
                labels = [json.loads(line) for line in lines if line.strip()][-100:]
        except (OSError, ValueError):
            pass
        settings = admute_settings.read()
        if not isinstance(delay, (int, float)) or isinstance(delay, bool):
            delay = settings['lookahead'] + 1  # a worker without the shared delay holds each input this long
        return {'settings': settings, 'worker': worker, 'on_air': on_air, 'delay': delay,
                'detector': detector, 'detector_stale': stale, 'labels': labels}

    def admute_known():
        """The known-ads database's clips (the sidecar writes admute-prints.json)."""
        try:
            data = json.loads((admute_dir / 'admute-prints.json').read_text())
        except (OSError, ValueError):
            return {'updated': None, 'clips': []}
        clips = sorted(data.get('clips') or [], key=lambda c: -(c.get('last') or 0))
        return {'updated': data.get('updated'), 'clips': clips}

    def admute_forget(data):
        """Forget known clips: queued for the sidecar, which acts within a second."""
        ids = data.get('clips') if isinstance(data, dict) else None
        if (not isinstance(ids, list) or not 0 < len(ids) <= 100
                or any(isinstance(c, bool) or not isinstance(c, int) or c <= 0 for c in ids) or set(data) != {'clips'}):
            raise ConfigError('forget takes clips: a list of up to 100 clip ids')
        with open(admute_dir / 'admute-commands.jsonl', 'a') as f:
            f.write(json.dumps({'forget': ids, 'at': round(time.time(), 1)}) + '\n')

    def admute_name(data):
        """Name a known clip (say, the advertiser): queued for the sidecar, like forget."""
        if not isinstance(data, dict) or set(data) != {'clip', 'name'}:
            raise ConfigError('name takes clip and name')
        clip, name = data['clip'], data['name']
        if isinstance(clip, bool) or not isinstance(clip, int) or clip <= 0:
            raise ConfigError('clip must be a clip id')
        if not isinstance(name, str) or len(name) > 80:
            raise ConfigError('name must be text of up to 80 characters')
        with open(admute_dir / 'admute-commands.jsonl', 'a') as f:
            f.write(json.dumps({'name': {'clip': clip, 'name': name}, 'at': round(time.time(), 1)}) + '\n')

    def admute_ad_picture(name):
        """A known ad's picture: <clip id>-<n>.jpg (the sidecar and admute.scripts keep them)."""
        if not re.fullmatch(r'\d{1,7}-\d\.jpg', name):
            raise ConfigError('Unknown ad picture')
        try:
            return (admute_dir / 'admute-ads' / name).read_bytes()
        except OSError:
            return None

    def admute_recordings():
        """Training recordings (admute/recordings.py keeps admute-recordings.json)."""
        try:
            data = json.loads((admute_dir / 'admute-recordings.json').read_text())
        except (OSError, ValueError):
            data = {}
        recs = [{'game': key, **{k: v.get(k) for k in ('title', 'channel', 'start', 'end', 'status', 'adopted', 'file',
                                                      'steps', 'error', 'note', 'processed_at')},
                 'game_title': (v.get('game') or {}).get('title')} for key, v in (data.get('recordings') or {}).items()]
        skipped = [{'game': key, **v} for key, v in (data.get('skipped') or {}).items()]
        return {'updated': data.get('updated'), 'error': data.get('plan_error'),
                'recordings': sorted(recs, key=lambda r: -(r.get('start') or 0)),
                'skipped': sorted(skipped, key=lambda r: r.get('start') or 0)}

    def admute_cancel_recording(data):
        """Stop a game being recorded for training. VizelVision's own timer is cancelled in
        TV-Thing; a timer of the operator's own is only no longer learnt from."""
        key = data.get('game') if isinstance(data, dict) else None
        if not isinstance(key, str) or set(data) != {'game'}:
            raise ConfigError('cancel takes game: a game key from the list')
        listing = {r['game']: r for r in admute_recordings()['recordings']}
        rec = listing.get(key)
        if rec is None or rec.get('status') not in ('scheduled', 'recording'):
            raise ConfigError('That game is not being recorded')
        skip_path = admute_dir / 'admute-recordings-skip.json'
        try:
            skip = json.loads(skip_path.read_text())
        except (OSError, ValueError):
            skip = {'games': []}
        skip['games'] = sorted(set(skip.get('games', [])) | {key})
        skip_path.write_text(json.dumps(skip))
        if not rec.get('adopted'):
            raw = json.loads((admute_dir / 'admute-recordings.json').read_text())['recordings'][key]
            body = json.dumps({'id': raw['timer']}).encode()
            req = urllib.request.Request(config.tv_thing.base_url.rstrip('/') + '/api/v1/recordings/cancel', data=body,
                                         method='POST', headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    r.read()
            except Exception as exc:
                raise MasterStreamError(f'TV-Thing did not cancel the timer: {exc}') from exc

    def admute_frame(name):
        """The detector's picture nearest a wall-clock second: <input key>/<second>.jpg."""
        match = re.fullmatch(r'([a-f0-9]{32})/(\d{9,11})\.jpg', name)
        if not match:
            raise ConfigError('Unknown ad-mute picture')
        folder, second = admute_dir / 'admute-frames' / match[1], int(match[2])
        for near in (0, -1, 1, -2, 2, -3, 3):
            try:
                return (folder / f'{second + near}.jpg').read_bytes()
            except OSError:
                continue
        return None

    def admute_label(data):
        """A review mark on a past break: {span_id, label: show|ad, start?, end?, title?}."""
        if not isinstance(data, dict) or not set(data) <= {'span_id', 'label', 'start', 'end', 'title', 'note'}:
            raise ConfigError('A label takes span_id, label, start, end, title and note')
        if data.get('label') not in ('show', 'ad'):
            raise ConfigError('label must be show or ad')
        for key in ('start', 'end'):
            if data.get(key) is not None and (isinstance(data[key], bool) or not isinstance(data[key], (int, float))):
                raise ConfigError(f'{key} must be a time')
        for key in ('span_id', 'title', 'note'):
            if data.get(key) is not None and (not isinstance(data[key], str) or len(data[key]) > 200):
                raise ConfigError(f'{key} must be text of up to 200 characters')
        row = {**data, 'source': 'review', 'at': round(time.time(), 1)}
        with open(admute_dir / 'admute-labels.jsonl', 'a') as f:
            f.write(json.dumps(row) + '\n')

    def my_ads_view():
        """My ads: settings, each ad with its plays and whether it may air now, what master shows."""
        settings, now = my_ads.read(), time.time()
        plays = my_ads.plays(now - 7 * 86400)
        try:
            status = master.request()
            worker, on_air = status.get('my_ads'), status.get('on_air')
            if status.get('state') in ('unavailable', 'not_configured'):
                worker = {'error': status.get('error') or 'The master worker is not running'}
        except Exception as exc:
            worker, on_air = {'error': f'Master is unavailable: {exc}'}, None
        ads = []
        for ad in settings['ads']:
            mine = [p for p in plays if p.get('kind') == 'ad' and p.get('id') == ad['id']]
            counted = [p['at'] for p in mine if p.get('counted')]
            ads.append({**ad, 'present': (my_ads.folder / ad['file']).is_file(),
                        'allowed': my_ads_module.allowed(ad, plays, now),
                        'again': my_ads_module.allowed_again(ad, plays, now),
                        'played': {'hour': sum(1 for t in counted if t >= now - 3600),
                                   'day': sum(1 for t in counted if t >= now - 86400), 'week': len(counted),
                                   'last': max((p['at'] for p in mine), default=None)}})
        cards = [p for p in plays if p.get('kind') == 'card']
        return {'settings': {k: v for k, v in settings.items() if k != 'ads'}, 'ads': ads, 'status': worker,
                'admute_mode': admute_settings.read()['mode'], 'on_air': on_air, 'recent': plays[-80:][::-1],
                'card': {'file': my_ads_module.card_file(settings),
                         'seconds_today': round(sum(p.get('seconds', 0) for p in cards if p['at'] >= now - 86400))},
                'limits': {'bytes': my_ads_module.MAX_BYTES, 'image_bytes': my_ads_module.MAX_IMAGE_BYTES,
                           'seconds': my_ads_module.MAX_SECONDS, 'video': list(my_ads_module.VIDEO_EXT),
                           'image': list(my_ads_module.IMAGE_EXT), 'card_text': my_ads_module.CARD_TEXT}}

    def my_ads_settings(data):
        """Settings; new card words are drawn before master is told to show them."""
        if isinstance(data, dict) and isinstance(data.get('card'), dict) and 'text' in data['card']:
            text = my_ads_module.validate_card_text(data['card']['text'])
            probe = my_ads.read()
            probe['card'] = {**probe['card'], 'text': text}
            my_ads.card(probe)
        my_ads.update(data)

    def promos_view():
        """Station promos for Presentation's Promos tab, with ad mute's mode (they play only when it is On)."""
        return {**promo_desk.status(), 'admute_mode': admute_settings.read()['mode']}

    def my_ads_file(name):
        """A file of my-ads/ for the page: an ad's picture, the card, or the ad itself."""
        if re.fullmatch(r'[0-9a-f]{12}-\d\.jpg', name) or re.fullmatch(r'card-[0-9a-f]{10}\.png', name) \
                or re.fullmatch(r'card-own-[0-9a-f]{8}\.(png|jpe?g|webp)', name):
            path = my_ads.folder / name
        elif re.fullmatch(r'[0-9a-f]{12}', name):
            ad = next((a for a in my_ads.read()['ads'] if a['id'] == name), None)
            path = my_ads.folder / ad['file'] if ad else None
        else:
            raise ConfigError('Unknown file of my ads')
        return path if path is not None and path.is_file() else None

    def crawl_view():
        # What the worker is running comes from its status; a stopped worker leaves settings editable.
        try:
            result = master.request()
            status, error = result.get('crawl'), None
            if result.get('state') in ('unavailable', 'not_configured'):
                error = result.get('error') or 'The master worker is not configured'
        except Exception as exc:
            status, error = None, f'Master is unavailable: {exc}'
        settings = crawl_settings.read()
        return {'settings': settings, 'status': status, 'master_error': error, 'feeds': feed_settings.read(),
                'rotation': crawl_desk.status(settings, status) if crawl_desk else None,
                'segments': {key: {'name': name, 'label': label} for key, (name, label, _) in SEGMENTS.items()},
                'contexts': CONTEXTS, 'modes': MODES, 'eas_url': config.master.eas_url,
                'nws_zones': list(config.master.nws_zones),
                'areas': [{'code': code, 'name': AREA_NAMES.get(code)} for code in config.master.eas_areas]}

    def crawl_feeds_save(data):
        """Feed options: {transit?: {rail, bus, routes}, weather?: {zip}}. A new ZIP is looked up
        now, so a mistyped one is refused here rather than silently airing no weather."""
        if not isinstance(data, dict) or not set(data) <= {'transit', 'weather', 'segments'}:
            raise ConfigError('Feed options are transit, weather and segments')
        current = feed_settings.read()
        value = {**current, **{k: {**current[k], **v} if isinstance(v, dict) else v for k, v in data.items()}}
        if isinstance(data.get('segments'), dict):  # One segment's change keeps its other options.
            value['segments'] = {**current['segments'], **{
                key: {**current['segments'].get(key, {}), **options} if isinstance(options, dict) else options
                for key, options in data['segments'].items()}}
        weather = data.get('weather')
        if isinstance(weather, dict) and set(weather) - {'zip'}:
            raise ConfigError('Set the weather location by zip')
        code = value['weather'].get('zip') if isinstance(value['weather'], dict) else None
        if isinstance(weather, dict) and code != current['weather']['zip']:
            if code and isinstance(code, str) and re.fullmatch(r'\d{5}', code):
                try:
                    value['weather'] = {'zip': code, **crawl_feeds.lookup_zip(code)}
                except (OSError, ValueError, KeyError) as exc:
                    raise ConfigError(f'Could not look up ZIP {code}: {exc}') from exc
            elif code == '':
                value['weather'] = dict(FeedSettings.validate({})['weather'])
        saved = feed_settings.save(value)
        if crawl_desk:
            for name in data:
                feed = crawl_desk.feeds.get(name)
                if feed:
                    feed.poke()
        return saved

    def crawl_layer(name, data):
        """The important or override layer from {text, label, style?, minutes}: minutes null runs until cleared."""
        allowed = {'text', 'label', 'minutes'} | ({'style'} if name == 'override' else set())
        if not isinstance(data, dict) or not set(data) <= allowed:
            raise ConfigError(f'{name} takes ' + ', '.join(sorted(allowed)))
        minutes = data.get('minutes')
        if minutes is not None and (isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 24 * 60):
            raise ConfigError('minutes must be 1 to 1440, or null to run until cleared')
        current = crawl_settings.read()[name]
        layer = {**current, **{key: data[key] for key in data if key != 'minutes'},
                 'until': (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat() if minutes else None}
        crawl_settings.update({name: layer})

    if projector is None and programming is not None and isinstance(playout, SourceQueue):
        projector = playback.Projector(queue=playout, programming=programming, master=master, sports=sports,
                                       library=coordinator.library if coordinator else None)

    class ApiHandler(BaseHTTPRequestHandler):
        server_version = "VizelVisionRokuStream/0.1"

        def _roku_moved(self) -> None:
            self._json(HTTPStatus.GONE, {"error": {
                "code": "moved_to_tv_thing",
                "message": "The source Roku is TV Thing's Roku lane now: drive, calibrate and watch it "
                           "at /tv/roku.html and the Roku tab of /tv/, or through TV Thing's /api/v1/roku API"}})

        def _json(self, status: HTTPStatus | int, payload: object) -> None:
            body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _page(self, page_path: Path) -> None:
            try:
                body = page_path.read_bytes()
            except OSError as exc:
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {
                        "error": {
                            "code": "page_unavailable",
                            "message": str(exc),
                        }
                    },
                )
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'self' 'unsafe-inline'; font-src 'self'; frame-src 'self'; frame-ancestors 'self'; "
                "script-src 'self' 'unsafe-inline'; connect-src 'self'; media-src 'self' blob:; "
                "img-src 'self' data: blob:; base-uri 'none'; form-action 'none'",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            expected = config.server.api_key
            if expected is None:
                return True
            supplied = self.headers.get("X-API-Key", "")
            authorization = self.headers.get("Authorization", "")
            if authorization.startswith("Bearer "):
                supplied = authorization[7:]
            return hmac.compare_digest(supplied, expected)

        def _authorize(self) -> bool:
            if self._authorized():
                return True
            self._json(
                HTTPStatus.UNAUTHORIZED,
                {"error": {"code": "unauthorized", "message": "Invalid API key"}},
            )
            return False

        def _body(self) -> dict[str, Any]:
            length_text = self.headers.get("Content-Length", "0")
            try:
                length = int(length_text)
            except ValueError as exc:
                raise ConfigError("Invalid Content-Length") from exc
            if length < 0 or length > 65_536:
                raise ConfigError("Request body must be at most 64 KiB")
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Invalid JSON body: {exc.msg}") from exc
            if not isinstance(data, dict):
                raise ConfigError("JSON body must be an object")
            return data

        def _handle_error(self, error: Exception) -> None:
            if isinstance(error, (BrokenPipeError, ConnectionResetError)):
                return
            if isinstance(error, RokuStreamError):
                self._json(
                    _error_status(error),
                    {
                        "error": {
                            "code": error.code,
                            "message": str(error),
                            "details": error.details,
                        }
                    },
                )
            else:
                self.log_error("Unhandled API error: %r", error)
                self._json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"error": {"code": "internal_error", "message": str(error)}},
                )

        @staticmethod
        def _channel_from(data: dict[str, Any]) -> str:
            channel = data.get("channel")
            if not isinstance(channel, str) or not channel.strip():
                raise ConfigError("channel must be a non-empty string")
            return channel.strip()

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            parsed = urlsplit(self.path)
            path = parsed.path.rstrip("/") or "/"
            # Public presentation shells contain no operational data. All API
            # reads, media and writes still require the configured credentials.
            public = PAGES + tuple(MOVED) + ('/static/test-pattern.webp',)
            # The sonic identity's fonts and reference renders are brand material, not operational data.
            brand = re.fullmatch(r'/static/(fonts/[a-z0-9-]+\.woff2|sonic/[a-z-]+\.mp3)', path)
            if path not in public and not brand and not _UI_FILE.fullmatch(path) and not self._authorize():
                return
            try:
                if path in MOVED:
                    self.send_response(HTTPStatus.TEMPORARY_REDIRECT)
                    self.send_header("Location", ("../" if path != "/" and parsed.path.endswith("/") else "") + MOVED[path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif path in PAGES:
                    if parsed.path.endswith("/"):
                        self.send_response(HTTPStatus.TEMPORARY_REDIRECT)
                        self.send_header("Location", ".." + path)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    else:
                        self._page(_UI_PATH / (path[1:] + ".html"))
                elif path == '/v1/production/monitor':
                    if production_monitor is None:
                        raise ConfigError('Production monitor is unavailable')
                    self._json(HTTPStatus.OK, production_monitor.status())
                elif path == '/v1/production':
                    self._json(HTTPStatus.OK, production.describe())
                elif path == '/v1/captions':
                    self._json(HTTPStatus.OK, captions_view())
                elif path == '/v1/crawl':
                    self._json(HTTPStatus.OK, crawl_view())
                elif path == '/v1/admute':
                    self._json(HTTPStatus.OK, admute_view())
                elif path == '/v1/admute/recordings':
                    self._json(HTTPStatus.OK, admute_recordings())
                elif path == '/v1/admute/known':
                    self._json(HTTPStatus.OK, admute_known())
                elif path.startswith('/v1/admute/ad/'):
                    body = admute_ad_picture(path[len('/v1/admute/ad/'):])
                    if body is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "No such picture"}})
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'private, max-age=86400')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    self.wfile.write(body)
                elif path.startswith('/v1/admute/frame/'):
                    body = admute_frame(path[len('/v1/admute/frame/'):])
                    if body is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "No picture for that time"}})
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'private, max-age=3600')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    self.wfile.write(body)
                elif path == '/v1/promos':
                    self._json(HTTPStatus.OK, promos_view())
                elif path.startswith('/v1/promos/still/') or path.startswith('/v1/promos/overlay/'):
                    # A promo's still, or one of its live texts, as it would read now.
                    found = re.fullmatch(r'/v1/promos/(?:still/([a-z0-9-]{1,40})|overlay/([a-z0-9-]{1,40})/(\d{1,2}))\.png', path)
                    if not found:
                        raise ConfigError('Unknown promo picture')
                    body = (promo_desk.still_png(found[1]) if found[1]
                            else promo_desk.overlay_png(found[2], int(found[3])))
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', 'image/png')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    self.wfile.write(body)
                elif path.startswith('/v1/promos/file/'):
                    name = path[len('/v1/promos/file/'):]
                    found = promo_desk.library.path(name)
                    if found is None and promos_module._VARIANT.match(name) and (promo_desk.store.folder / name).is_file():
                        found = promo_desk.store.folder / name
                    if found is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "No such file"}})
                        return
                    kind = {'.png': 'image/png', '.mp4': 'video/mp4', '.wav': 'audio/wav'}[found.suffix]
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', kind)
                    self.send_header('Content-Length', str(found.stat().st_size))
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    with open(found, 'rb') as stream:
                        shutil.copyfileobj(stream, self.wfile, 1 << 20)
                elif path.startswith('/v1/idents/'):
                    # The station ID and the Sports ID, and their end cards (Ads › Idents).
                    found = ident_file(path[len('/v1/idents/'):])
                    if found is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "No such file"}})
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', 'video/mp4' if found.suffix == '.mp4' else 'image/png')
                    self.send_header('Content-Length', str(found.stat().st_size))
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    with open(found, 'rb') as stream:
                        shutil.copyfileobj(stream, self.wfile, 1 << 20)
                elif path == '/v1/my-ads':
                    self._json(HTTPStatus.OK, my_ads_view())
                elif path.startswith('/v1/my-ads/file/'):
                    found = my_ads_file(path[len('/v1/my-ads/file/'):])
                    if found is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "No such file"}})
                        return
                    kind = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.webp': 'image/webp',
                            '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/quicktime', '.webm': 'video/webm',
                            '.mkv': 'video/x-matroska'}.get(found.suffix.lower(), 'application/octet-stream')
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', kind)
                    self.send_header('Content-Length', str(found.stat().st_size))
                    self.send_header('Cache-Control', 'private, max-age=3600' if kind.startswith('image') else 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    with open(found, 'rb') as stream:
                        shutil.copyfileobj(stream, self.wfile, 1 << 20)
                elif path == '/v1/crawl/alerts':
                    if crawl_desk is None:
                        raise ConfigError('The crawl rotation requires the master queue')
                    self._json(HTTPStatus.OK, crawl_desk.register())
                elif path == '/v1/crawl/bus-routes':
                    if crawl_desk is None or 'transit' not in crawl_desk.feeds:
                        raise ConfigError('The Metro and bus feed requires the master queue')
                    try:
                        routes = crawl_desk.feeds['transit'].routes()
                    except (OSError, ValueError) as exc:
                        raise ConfigError(f'Could not load WMATA bus routes: {exc}') from exc
                    self._json(HTTPStatus.OK, {'routes': routes})
                elif path == '/v1/programming':
                    if programming is None:
                        raise ConfigError('Programming requires the master queue')
                    self._json(HTTPStatus.OK, programming.describe())
                elif path == '/v1/playback':
                    # What will actually air: Up next and the schedule under the queue's rules.
                    if projector is None:
                        raise ConfigError('The playback projection requires the master queue')
                    until = parse_qs(parsed.query).get('until', [None])[0]
                    now = datetime.now(timezone.utc)
                    horizon = parse_time(until) if until else now + timedelta(hours=24)
                    horizon = min(max(horizon, now + timedelta(hours=1)), now + timedelta(days=8))
                    self._json(HTTPStatus.OK, projector.describe(now, horizon))
                elif path == '/v1/continuity':
                    if continuity is None:
                        raise ConfigError('Continuity announcements require the master queue')
                    self._json(HTTPStatus.OK, continuity.status())
                elif path.startswith('/v1/continuity/audio/'):
                    if continuity is None:
                        raise ConfigError('Continuity announcements require the master queue')
                    audio = continuity.audio(path.rsplit('/', 1)[1])
                    body = audio.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', 'audio/wav' if audio.suffix == '.wav' else 'video/mp4')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)
                elif path == '/static/test-pattern.webp' or brand or _UI_FILE.fullmatch(path):
                    name = path.split('/static/', 1)[1]
                    folder = _SONIC_PATH if name.startswith('sonic/') else _STATIC_PATH
                    try:
                        body = (folder / (name.split('/', 1)[1] if name.startswith('sonic/') else name)).read_bytes()
                    except OSError:
                        self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "Unknown file"}})
                        return
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', {'webp': 'image/webp', 'js': 'text/javascript', 'css': 'text/css',
                                                      'woff2': 'font/woff2', 'mp3': 'audio/mpeg'}[path.rsplit('.', 1)[1]])
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/v1/master":
                    self._json(HTTPStatus.OK, {**master.request(), "preview_enabled": config.master.enabled})
                elif path == "/v1/master/end-options":
                    # What a take's "on air until" prompt offers: the game on that source, if any.
                    query = parse_qs(parsed.query)
                    target = {k: query[k][0] for k in ("source_id", "channel_id", "date") if query.get(k)}
                    channel, program = {}, None
                    if str(target.get("source_id")).startswith("tv-thing-") and sources is not None:
                        try:
                            listing = sources.programs(target["source_id"])
                            channel = next((c for c in listing.get("channels", [])
                                            if str(c["id"]) == str(target.get("channel_id"))), {})
                        except RokuStreamError:
                            pass  # Guide unavailable: offer the clock and custom times.
                        now_on = channel.get("now") or {}
                        if now_on.get("id") and now_on.get("end"):
                            program = {k: now_on[k] for k in ("id", "title", "start", "end")}
                    games, warnings = sports.games_on(target, channel_name=channel.get("name")) if sports else ([], [])
                    self._json(HTTPStatus.OK, {
                        "games": games, "program": program, "warnings": warnings,
                        "returns_to": "schedule" if programming is not None and programming.enabled else "off_air"})
                elif path.startswith('/v1/inputs/'):
                    parts = path.split('/')
                    if len(parts) != 6 or parts[4] != 'media':
                        raise ConfigError('Unknown source preview route')
                    body, content_type = input_preview.read(parts[3], parts[5])
                    self.send_response(HTTPStatus.OK)
                    self.send_header('Content-Type', content_type)
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('X-Content-Type-Options', 'nosniff')
                    self.end_headers()
                    self.wfile.write(body)
                elif path.startswith("/v1/master/media/"):
                    body, content_type = master_preview.read(path[len("/v1/master/media/"):], parsed.query)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/static/vendor/hls-1.7.2.min.js":
                    body = (_STATIC_PATH / "vendor/hls-1.7.2.min.js").read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/javascript; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "private, max-age=86400")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(body)
                elif path == "/v1/sources":
                    if sources is None:
                        raise SourceUnavailableError("Source catalog is not configured")
                    catalog = sources.list()
                    catalog["master"] = master.request()
                    catalog["master"]["preview_enabled"] = config.master.enabled
                    for source in catalog["sources"]:
                        independent = source["id"].startswith('tv-thing-') or source["id"] == 'library'
                        source["capabilities"]["master_queue"] = bool(
                            isinstance(playout, SourceQueue) and source["configured"] and
                            (independent or coordinator.roku_enabled))
                        source["capabilities"]["master_take"] = bool(source["configured"] and (independent
                                                                    or catalog["master"].get('roku_enabled'))
                                                                    and catalog["master"].get("can_prepare"))
                    self._json(HTTPStatus.OK, catalog)
                elif path == "/v1/networks":
                    # Networks on both YouTube TV and the antenna, for the pages' source choices.
                    if coordinator.networks is None:
                        raise SourceUnavailableError("Source catalog is not configured")
                    self._json(HTTPStatus.OK, {"networks": coordinator.networks.listing()})
                elif path.startswith("/v1/sources/") and path.endswith("/programs"):
                    if sources is None:
                        raise SourceUnavailableError("Source catalog is not configured")
                    parts = path.split("/")
                    if len(parts) != 5:
                        raise ChannelNotFoundError("Unknown source route")
                    query = parse_qs(parsed.query)
                    self._json(HTTPStatus.OK, sources.programs(parts[3], query.get("date", [None])[0]))
                elif path == "/health":
                    # The web app's health. The Roku's is TV Thing's (/v1/roku/status).
                    self._json(HTTPStatus.OK, {"service": "roku-stream", "ready": True,
                                               "roku": roku_operation(roku)})
                elif path == "/v1/channels":
                    self._json(
                        HTTPStatus.OK,
                        {
                            "channels": [
                                {
                                    "name": channel.name,
                                    "aliases": list(channel.aliases),
                                    "guide_index": channel.guide_index,
                                    "anchor_safe": channel.anchor_safe,
                                    "network_page": channel.network_page
                                    or channel.name,
                                }
                                # TV Thing's Roku lane lists them (and calibrates them).
                                for channel in config.youtube_tv_channels()
                            ]
                        },
                    )
                elif path in ROKU_MOVED_GET or path.startswith("/v1/operations/"):
                    self._roku_moved()
                elif path == "/v1/operation":
                    self._json(HTTPStatus.OK, roku_operation(roku))
                elif path == '/v1/sports/games':
                    if sports is None:
                        raise ConfigError('Sports schedules are not configured')
                    query = parse_qs(parsed.query)
                    self._json(HTTPStatus.OK, sports.games(query.get('league', ['mlb'])[0], query.get('date', [None])[0]))
                elif path == '/v1/sports/week':
                    if sports is None:
                        raise ConfigError('Sports schedules are not configured')
                    query = parse_qs(parsed.query)
                    def number(name):
                        value = query.get(name, [None])[0]
                        if value is None:
                            return None
                        if not value.isdigit():
                            raise ConfigError(f'{name} must be a number')
                        return int(value)
                    self._json(HTTPStatus.OK, sports.week(query.get('league', ['nfl'])[0], number('seasontype'), number('week')))
                elif path == '/v1/sports/upcoming':
                    if sports is None:
                        raise ConfigError('Sports schedules are not configured')
                    query = parse_qs(parsed.query)
                    days = query.get('days', ['10'])[0]
                    if not days.isdigit():
                        raise ConfigError('days must be a number')
                    self._json(HTTPStatus.OK, sports.upcoming(query.get('league', ['mlb'])[0], int(days)))
                elif path == '/v1/sports/teams':
                    if sports is None:
                        raise ConfigError('Sports schedules are not configured')
                    league = parse_qs(parsed.query).get('league', ['mlb'])[0]
                    self._json(HTTPStatus.OK, {'league': league, 'teams': sports.teams(league)})
                elif path == "/v1/baseball/games":
                    if baseball is None:
                        raise ConfigError("Baseball schedule is not configured")
                    query = parse_qs(parsed.query)
                    requested_date = query.get("date", [None])[0]
                    self._json(HTTPStatus.OK, baseball.games(requested_date))
                elif path == "/v1/queue":
                    if playout is None:
                        raise ConfigError("Playout queue is not configured")
                    items = playout.list()
                    queued_keys = {getattr(i, "schedule_key", None) for i in items
                                   if i.status in ("queued", "blocked", "running")}
                    # A programming key is "run_at|kind|ref|target"; ref is the show id for shows and games.
                    queued_refs = {key.split("|")[2] for key in queued_keys if key and key.count("|") >= 3}
                    self._json(
                        HTTPStatus.OK,
                        {
                            "items": [asdict(item) for item in items],
                            "next_scheduled": programming.next_program(exclude=queued_keys) if programming else None,
                            "scheduled_shows": programming.upcoming_shows(exclude=queued_refs) if programming else [],
                            "schedule_enabled": bool(programming and programming.enabled),
                            "on_air": roku.snapshot() if roku is not None else None,
                            **({'master_on_air': master.request().get('on_air')} if isinstance(playout, SourceQueue) else {}),
                            **(playout.status() if isinstance(playout, SourceQueue) else {}),
                        },
                    )
                elif path == "/v1/roku/status":
                    # The source Roku, as TV Thing's Roku lane reports it.
                    if roku is None:
                        raise ConfigError("The Roku is TV Thing's Roku lane; enable tv_thing")
                    lane, lock = roku.lane()
                    self._json(HTTPStatus.OK, {"lane": lane, "lock": lock,
                                               "last_prepared": roku.snapshot()})
                elif path == "/v1/jobs":
                    self._json(
                        HTTPStatus.OK,
                        {"jobs": [asdict(job) for job in scheduler.list()]},
                    )
                elif path.startswith("/v1/jobs/"):
                    job_id = path.rsplit("/", 1)[1]
                    job = scheduler.get(job_id)
                    if job is None:
                        self._json(
                            HTTPStatus.NOT_FOUND,
                            {"error": {"code": "not_found", "message": "Unknown job"}},
                        )
                    else:
                        self._json(HTTPStatus.OK, asdict(job))
                else:
                    self._json(
                        HTTPStatus.NOT_FOUND,
                        {"error": {"code": "not_found", "message": "Unknown endpoint"}},
                    )
            except Exception as exc:
                self._handle_error(exc)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if not self._authorize():
                return
            path = urlsplit(self.path).path.rstrip("/") or "/"
            if path in ('/v1/my-ads/upload', '/v1/my-ads/card-image'):
                # The file itself is the body, streamed to disk: not JSON, and far over 64 KiB.
                try:
                    name = (parse_qs(urlsplit(self.path).query).get('name') or [''])[0][-200:]
                    try:
                        length = int(self.headers.get('Content-Length') or 0)
                    except ValueError as exc:
                        raise ConfigError('Invalid Content-Length') from exc
                    card = path.endswith('card-image')
                    ext = Path(name).suffix.lower()
                    if ext not in (my_ads_module.IMAGE_EXT if card else my_ads_module.VIDEO_EXT):
                        raise ConfigError('Upload ' + ('a picture: ' if card else 'a video: ')
                                          + ' '.join(my_ads_module.IMAGE_EXT if card else my_ads_module.VIDEO_EXT))
                    upload = my_ads_module.copy_upload(self.rfile, length, my_ads.folder, ext,
                                                       my_ads_module.MAX_IMAGE_BYTES if card else my_ads_module.MAX_BYTES)
                    if card:
                        my_ads.set_card_image(upload, name)
                        self._json(HTTPStatus.OK, my_ads_view())
                    else:
                        _, ad = my_ads.add(upload, name)
                        self._json(HTTPStatus.OK, {**my_ads_view(), 'added': ad['id']})
                except Exception as exc:
                    self._handle_error(exc)
                return
            try:
                data = self._body()
                if path in ('/v1/production/monitor', '/v1/production/monitor/check', '/v1/production/monitor/launch'):
                    if production_monitor is None:
                        raise ConfigError('Production monitor is unavailable')
                    if path.endswith('/launch'):
                        if data:
                            raise ConfigError('Launch takes an empty object')
                        self._json(HTTPStatus.OK, production_monitor.launch_app())
                    elif path.endswith('/check'):
                        if data:
                            raise ConfigError('Check takes an empty object; TV locks cannot be overridden')
                        self._json(HTTPStatus.ACCEPTED, production_monitor.request_check())
                    else:
                        self._json(HTTPStatus.OK, production_monitor.save(data))
                elif path == '/v1/production':
                    self._json(HTTPStatus.OK, production.save(data))
                elif path == '/v1/captions':
                    caption_settings.update(data)
                    self._json(HTTPStatus.OK, captions_view())
                elif path == '/v1/crawl':
                    crawl_settings.update(data)
                    self._json(HTTPStatus.OK, crawl_view())
                elif path == '/v1/admute':
                    admute_settings.update(data)
                    self._json(HTTPStatus.OK, admute_view())
                elif path == '/v1/admute/override':
                    if set(data) != {'action'} or data['action'] not in ('mute', 'unmute'):
                        raise ConfigError('Override takes action: mute or unmute')
                    result = worker_client.request('admute', data)
                    self._json(HTTPStatus.OK if result.get('accepted') else HTTPStatus.CONFLICT,
                               {**admute_view(), 'override': result})
                elif path == '/v1/admute/pause':
                    # "Pause for this program": the input on air is left alone until it changes
                    # (or for hours at most); resume clears it.
                    if set(data) - {'hours', 'resume'}:
                        raise ConfigError('Pause takes hours or resume')
                    if data.get('resume'):
                        admute_settings.update({'paused_until': None, 'paused_input': None})
                    else:
                        hours = data.get('hours', 6)
                        if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not 0 < hours <= 24:
                            raise ConfigError('hours must be from 0 to 24')
                        key = ((master.request().get('on_air') or {}).get('id'))
                        admute_settings.update({'paused_until': time.time() + hours * 3600, 'paused_input': key})
                    self._json(HTTPStatus.OK, admute_view())
                elif path == '/v1/admute/label':
                    admute_label(data)
                    self._json(HTTPStatus.OK, admute_view())
                elif path == '/v1/admute/forget':
                    admute_forget(data)
                    self._json(HTTPStatus.OK, admute_view())
                elif path == '/v1/admute/name':
                    admute_name(data)
                    self._json(HTTPStatus.OK, {'ok': True})
                elif path == '/v1/admute/recordings/cancel':
                    admute_cancel_recording(data)
                    self._json(HTTPStatus.OK, admute_recordings())
                elif path == '/v1/promos':
                    promo_desk.store.update(data)
                    promo_desk.poke()
                    self._json(HTTPStatus.OK, promos_view())
                elif path.startswith('/v1/promos/promo/'):
                    promo_desk.store.set_promo(path.rsplit('/', 1)[1], data)
                    promo_desk.poke()
                    self._json(HTTPStatus.OK, promos_view())
                elif path == '/v1/my-ads':
                    my_ads_settings(data)
                    self._json(HTTPStatus.OK, my_ads_view())
                elif path.startswith('/v1/my-ads/ads/'):
                    my_ads.edit(path.rsplit('/', 1)[1], data)
                    self._json(HTTPStatus.OK, my_ads_view())
                elif path == '/v1/my-ads/order':
                    if set(data) != {'ids'}:
                        raise ConfigError('order takes ids: every ad, in their new order')
                    my_ads.reorder(data['ids'])
                    self._json(HTTPStatus.OK, my_ads_view())
                elif path == '/v1/my-ads/shuffle':
                    if data:
                        raise ConfigError('Shuffle takes an empty object')
                    my_ads.shuffle()
                    self._json(HTTPStatus.OK, my_ads_view())
                elif path == '/v1/crawl/dismiss':
                    if set(data) - {'source', 'id', 'dismissed'}:
                        raise ConfigError('Dismiss takes source, id and dismissed')
                    crawl_settings.dismiss(data.get('source', 'eas'), data.get('id'), data.get('dismissed', True))
                    self._json(HTTPStatus.OK, crawl_view())
                elif path == '/v1/crawl/feeds':
                    crawl_feeds_save(data)
                    self._json(HTTPStatus.OK, crawl_view())
                elif path in ('/v1/crawl/important', '/v1/crawl/override'):
                    crawl_layer(path.rsplit('/', 1)[1], data)
                    self._json(HTTPStatus.OK, crawl_view())
                elif path == '/v1/crawl/run':
                    if crawl_desk is None:
                        raise ConfigError('The crawl rotation requires the master queue')
                    if set(data) != {'segment'}:
                        raise ConfigError('Run takes a segment')
                    crawl_desk.run_now(data['segment'])
                    self._json(HTTPStatus.ACCEPTED, crawl_view())
                elif path.startswith('/v1/crawl/alerts/'):
                    # One item of the register: {action: air | mute | unmute}.
                    if crawl_desk is None:
                        raise ConfigError('The crawl rotation requires the master queue')
                    ident = unquote(path[len('/v1/crawl/alerts/'):])
                    if set(data) != {'action'} or data['action'] not in ('air', 'mute', 'unmute'):
                        raise ConfigError('An item takes action air, mute or unmute')
                    if data['action'] == 'air':
                        crawl_desk.air([ident])
                    else:
                        crawl_desk.mute(ident, data['action'] == 'mute')
                    self._json(HTTPStatus.ACCEPTED if data['action'] == 'air' else HTTPStatus.OK,
                               {'accepted': True, 'id': ident, 'action': data['action']})
                elif path in ('/v1/continuity', '/v1/continuity/preview'):
                    if continuity is None:
                        raise ConfigError('Continuity announcements require the master queue')
                    if path == '/v1/continuity':
                        self._json(HTTPStatus.OK, continuity.save(data))
                    else:
                        self._json(HTTPStatus.OK, continuity.preview(data.get('announcer'), data.get('just_played'),
                                                                     data.get('up_next')))
                elif path.startswith('/v1/programming'):
                    if programming is None:
                        raise ConfigError('Programming requires the master queue')
                    if path == '/v1/programming':
                        self._json(HTTPStatus.OK, programming.save_grid(data))
                    elif path == '/v1/programming/shows':
                        self._json(HTTPStatus.CREATED, programming.add_show(data))
                    elif path.startswith('/v1/programming/shows/'):
                        # {priority}: a show that outranks what holds master cuts in at its start.
                        result = programming.set_priority(path.rsplit('/', 1)[1], data.get('priority'))
                        self._json(HTTPStatus.OK if result else HTTPStatus.NOT_FOUND,
                                   result or {"error": {"code": "not_found", "message": "Unknown show"}})
                    elif path == '/v1/programming/take-current':
                        self._json(HTTPStatus.ACCEPTED, {'items': [asdict(i) for i in programming.take_current()]})
                    elif path == '/v1/programming/follow-games':
                        changes = programming.follow_games()
                        self._json(HTTPStatus.OK, {**programming.describe(), 'changes': changes})
                    else:
                        self._json(HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "Unknown endpoint"}})
                elif path in ("/v1/master/prepare", "/v1/master/prepare-take", "/v1/master/take",
                              "/v1/master/take-known", "/v1/master/fallback", "/v1/master/cancel"):
                    self._json(HTTPStatus.ACCEPTED, master.request(path.rsplit("/", 1)[1], data))
                elif path == "/v1/master/hold":
                    if coordinator is None or not isinstance(playout, SourceQueue):
                        raise ConfigError("The master queue is not configured")
                    self._json(HTTPStatus.OK, coordinator.set_hold(data.get("until")))
                elif path in ROKU_MOVED_POST or (path.startswith("/v1/operations/") and path.endswith("/cancel")):
                    self._roku_moved()
                elif path in ('/v1/queue/pause', '/v1/queue/resume'):
                    if not isinstance(playout, SourceQueue):
                        raise ConfigError('Master queue is not configured')
                    self._json(HTTPStatus.OK, playout.pause() if path.endswith('/pause') else playout.resume())
                elif path == '/v1/queue/clear':
                    if not isinstance(playout, SourceQueue):
                        raise ConfigError('Master queue is not configured')
                    if data:
                        raise ConfigError('Clear takes an empty object')
                    removed = playout.clear_added()
                    self._json(HTTPStatus.OK, {**playout.status(), 'removed': removed})
                elif path.startswith('/v1/queue/') and path.rsplit('/', 1)[-1] in ('skip', 'retry', 'tune-anyway'):
                    if not isinstance(playout, SourceQueue):
                        raise ConfigError('Master queue is not configured')
                    item = playout.action(path.split('/')[-2], path.split('/')[-1])
                    self._json(HTTPStatus.OK if item else HTTPStatus.NOT_FOUND,
                               asdict(item) if item else {'error': {'message': 'Unknown queue item'}})
                elif path == "/v1/queue":
                    if playout is None:
                        raise ConfigError("Playout queue is not configured")
                    if isinstance(playout, SourceQueue):
                        target_data = data.get('target') or {'source_id': 'youtube-tv', 'channel_id': self._channel_from(data)}
                        if not isinstance(target_data, dict):
                            raise ConfigError('target must be an object')
                        target, _ = coordinator.normalize_target(target_data)
                        program = None
                        if data.get('program_id'):
                            program = queue_programs.snapshot(target, data['program_id'])
                        gate = None
                        if data.get('release_type') == 'after_game':
                            gate_data = data.get('after_game')
                            if gate_data is None and 'target' not in data:
                                gate_data = roku_last_game(roku)
                            if not isinstance(gate_data, dict):
                                raise ConfigError('An exact after_game is required')
                            pk, date = gate_data.get('game_pk'), gate_data.get('game_date') or gate_data.get('official_date')
                            if isinstance(pk, bool) or not isinstance(pk, int) or not isinstance(date, str):
                                raise ConfigError('after_game requires integer game_pk and game_date')
                            game = baseball.game(pk, date)
                            gate = {'game_pk': pk, 'game_date': date, 'title': game.get('title') or str(pk)}
                        run_at = data.get('run_at')
                        after_program = None
                        if data.get('release_type') == 'scheduled_end':
                            end_data = data.get('after_program')
                            if not isinstance(end_data, dict) or not isinstance(end_data.get('target'), dict):
                                raise ConfigError('Scheduled end requires an exact after_program target and program_id')
                            end_target, _ = coordinator.normalize_target(end_data['target'])
                            end_program = queue_programs.snapshot(end_target, end_data.get('program_id'))
                            if not end_program.get('end'):
                                raise ConfigError('This program has no scheduled end')
                            run_at = datetime.fromtimestamp(end_program['end'], timezone.utc).isoformat()
                            after_program = {'target': end_target, 'program': end_program}
                        # "Plays until": how long it holds master once taken. None is open-ended.
                        end = coordinator.queue_end(data['until'], target) if data.get('until') is not None else None
                        item = playout.add_target(target, data.get('release_type'), run_at=run_at,
                                                  program=program, after_game=gate, after_program=after_program,
                                                  hold_end=end)
                        # Play now ends what is held on air (a game, a take until its time) so this
                        # follows at once; resume also lifts an operator's pause.
                        if data.get('release_type') == 'now' and (playout.hold or data.get('resume') is True):
                            playout.resume()
                        self._json(HTTPStatus.CREATED, asdict(item))
                        return
                    channel = self._channel_from(data)
                    _, resolved = config.resolve_channel(channel)
                    release_type = data.get("release_type")
                    if release_type == "at_time":
                        run_at = data.get("run_at")
                        if not isinstance(run_at, str):
                            raise ConfigError("run_at must be an ISO-8601 string")
                        item = playout.add_at_time(
                            resolved.name, parse_time(run_at)
                        )
                    elif release_type == "after_game":
                        if baseball is None:
                            raise ConfigError("Baseball schedule is not configured")
                        gate = data.get("after_game")
                        if gate is None:
                            gate = roku_last_game(roku)
                        if not isinstance(gate, dict):
                            raise ConfigError(
                                "after_game requires a currently confirmed baseball game"
                            )
                        game_pk = gate.get("game_pk")
                        game_date = gate.get("game_date") or gate.get("official_date")
                        if isinstance(game_pk, bool) or not isinstance(game_pk, int):
                            raise ConfigError("after_game.game_pk must be an integer")
                        if not isinstance(game_date, str):
                            raise ConfigError("after_game.game_date must use YYYY-MM-DD")
                        game = baseball.game(game_pk, game_date)
                        item = playout.add_after_game(
                            resolved.name,
                            game_pk=game_pk,
                            game_date=game_date,
                            game_title=str(game.get("title") or f"MLB game {game_pk}"),
                        )
                    else:
                        raise ConfigError(
                            "release_type must be 'after_game' or 'at_time'"
                        )
                    self._json(HTTPStatus.CREATED, asdict(item))
                elif path.startswith("/v1/queue/") and path.endswith("/move"):
                    if playout is None:
                        raise ConfigError("Playout queue is not configured")
                    item_id = path.split("/")[-2]
                    direction = data.get("direction")
                    if not isinstance(direction, str):
                        raise ConfigError("direction must be 'up' or 'down'")
                    item = playout.move(item_id, direction)
                    if item is None:
                        self._json(
                            HTTPStatus.NOT_FOUND,
                            {"error": {"code": "not_found", "message": "Unknown queue item"}},
                        )
                    else:
                        self._json(HTTPStatus.OK, asdict(item))
                elif path == "/v1/schedules":
                    channel = self._channel_from(data)
                    run_at = data.get("run_at")
                    if not isinstance(run_at, str):
                        raise ConfigError("run_at must be an ISO-8601 string")
                    _, resolved = config.resolve_channel(channel)
                    job = scheduler.add(resolved.name, parse_time(run_at))
                    self._json(HTTPStatus.CREATED, asdict(job))
                elif path == "/v1/operation/cancel":
                    # Stop the Roku's navigation: master control's own operation when it runs it.
                    if coordinator is not None and coordinator.enabled:
                        self._json(HTTPStatus.OK, coordinator.request("cancel", {}))
                    else:
                        self._json(HTTPStatus.OK, roku_operation(roku))
                else:
                    self._json(
                        HTTPStatus.NOT_FOUND,
                        {"error": {"code": "not_found", "message": "Unknown endpoint"}},
                    )
            except Exception as exc:
                self._handle_error(exc)

        def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if not self._authorize():
                return
            path = urlsplit(self.path).path.rstrip("/") or "/"
            try:
                if path.startswith("/v1/jobs/"):
                    job_id = path.rsplit("/", 1)[1]
                    job = scheduler.cancel(job_id)
                    if job is None:
                        self._json(
                            HTTPStatus.NOT_FOUND,
                            {"error": {"code": "not_found", "message": "Unknown job"}},
                        )
                    else:
                        self._json(HTTPStatus.OK, asdict(job))
                elif path.startswith('/v1/my-ads/ads/'):
                    my_ads.remove(path.rsplit('/', 1)[1])
                    self._json(HTTPStatus.OK, my_ads_view())
                elif path == '/v1/my-ads/card-image':
                    my_ads.clear_card_image()
                    my_ads.card()
                    self._json(HTTPStatus.OK, my_ads_view())
                elif path.startswith('/v1/programming/shows/'):
                    if programming is None:
                        raise ConfigError('Programming requires the master queue')
                    result = programming.remove_show(path.rsplit('/', 1)[1])
                    self._json(HTTPStatus.OK if result else HTTPStatus.NOT_FOUND,
                               result or {"error": {"code": "not_found", "message": "Unknown show"}})
                elif path.startswith("/v1/queue/"):
                    if playout is None:
                        raise ConfigError("Playout queue is not configured")
                    item_id = path.rsplit("/", 1)[1]
                    # The master queue's Remove also disarms a cued file and keeps schedule entries' record.
                    item = playout.remove_entry(item_id) if isinstance(playout, SourceQueue) else playout.remove(item_id)
                    if item is None:
                        self._json(
                            HTTPStatus.NOT_FOUND,
                            {"error": {"code": "not_found", "message": "Unknown queue item"}},
                        )
                    else:
                        self._json(HTTPStatus.OK, asdict(item))
                else:
                    self._json(
                        HTTPStatus.NOT_FOUND,
                        {"error": {"code": "not_found", "message": "Unknown endpoint"}},
                    )
            except Exception as exc:
                self._handle_error(exc)

    return ApiHandler


def build_roku(config: AppConfig, in_use=lambda: False) -> TvRoku | None:
    """The source Roku: TV Thing's Roku lane, when TV Thing is configured."""
    if not config.tv_thing.enabled:
        return None
    control = TvControl(config.tv_thing)
    token_path = config.master.socket_path.with_name("roku-lock.json")
    return TvRoku(control, RokuHold(control, token_path, in_use=in_use))


def serve(config: AppConfig) -> None:
    baseball = BaseballCatalog(config)
    roku = build_roku(config)
    coordinator = SourceCoordinator(config, roku, baseball)
    if roku is not None:
        roku.hold.in_use = coordinator.roku_in_use
    sports = SportsCatalog(config, baseball)
    coordinator.sports = sports
    library = MediaLibrary(config.library, config.state_file.with_name('library-cache.json'))
    coordinator.library = library
    sources = SourceCatalog(config, baseball, sports=sports, library=library)
    # A network YouTube TV is not ready with in time comes from the antenna (networks.py).
    coordinator.networks = Networks(config, sources.tv)
    if config.master.enabled:
        playout = SourceQueue(config.state_file.with_name('queue.json'), coordinator.execute_queue,
                              sports.game_status, validate_program=QueuePrograms(sources).validate,
                              schedules_file=config.state_file, start_worker=False,
                              preroll=coordinator.preroll_queue if coordinator.roku_enabled or config.library.enabled else None,
                              media_gate=coordinator.media_gate, on_pause=coordinator.disarm,
                              ident=coordinator.station_id, on_air=coordinator.on_air, game_on=coordinator.game_on,
                              input_failure=coordinator.input_failure, ready=coordinator.roku_ready,
                              stop_preroll=coordinator.stop_preroll, alternates=coordinator.alternates,
                              upgrade=coordinator.upgrade_queue if coordinator.roku_enabled else None,
                              roku_playing=coordinator.roku_playing if coordinator.roku_enabled else None,
                              roku_player=coordinator.roku_player if coordinator.roku_enabled else None)
        coordinator.queue = playout
        scheduler = QueueSchedules(playout)
        programming = Programming(config.state_file.with_name('programming.json'), playout,
                                  normalize=lambda target: coordinator.normalize_target(target, resolve_game=False)[0],
                                  game=sports.game, locate=sports.locate, start_worker=False)
        # When a manual take's end arrives, the schedule (or OFF AIR) takes master back.
        playout.on_hold_end = programming.take_back
        # A show's priority decides whether it cuts in on what holds master.
        playout.rank = programming.rank
        # ...and is prepared on the Roku while the take finishes (a warm-up).
        playout.schedule_now = programming.on_now
        coordinator.programs = QueuePrograms(sources)
    else:
        programming = None
        # Without master control, a legacy job or queue entry only puts the channel on the Roku.
        def play(channel):
            if roku is None:
                raise ConfigError("The Roku is TV Thing's Roku lane; enable tv_thing")
            try:
                return roku.prepare({"source_id": "youtube-tv", "channel_id": config.resolve_channel(channel)[1].name})
            finally:
                roku.hold.release()
        scheduler = Scheduler(config.state_file, play)
        playout = PlayoutQueue(config.state_file.with_name('queue.json'), play, baseball.game_status)
    production_monitor = ProductionMonitor(config)
    projector = continuity = crawl_desk = promo_desk = None
    if programming is not None:
        projector = playback.Projector(queue=playout, programming=programming, master=coordinator, sports=sports,
                                       library=library)
        # Continuity announcements: what just played and what is next, over the station ID.
        folder = config.state_file.parent / 'continuity'
        continuity = Continuity(config.state_file.with_name('continuity.json'), folder,
                                voice=Voice(folder / 'voice', config.continuity.keys_file),
                                project=lambda: projector.describe(datetime.now(timezone.utc),
                                                                   datetime.now(timezone.utc) + timedelta(hours=6))['segments'],
                                spoken=projector.spoken, master=coordinator.master, start_worker=False)
    if config.master.enabled:
        # The crawl's rotation: bulletins from public feeds, sent to the worker (crawl_desk.py).
        crawl_settings, feed_settings = CrawlSettings(config.master), FeedSettings(config.master)
        feeds = {'transit': crawl_feeds.TransitFeed(config.crawl.keys_file, lambda: feed_settings.read()['transit']),
                 'dc_alerts': crawl_feeds.AlertDcFeed(),
                 'weather': crawl_feeds.WeatherFeed(config.crawl.weather_station, config.crawl.forecast_point,
                                                    config.crawl.weather_place, lambda: feed_settings.read()['weather']),
                 'scores': crawl_feeds.ScoresFeed(sports.scoreboard, lambda: crawl_settings.read()['teams']),
                 'cairo': crawl_feeds.CairoFeed(config.master.off_air_radio_info_url)}
        if projector is not None:
            feeds['coming_up'] = crawl_feeds.ComingUpFeed(projector)
        ledger = CrawlLedger(Path(config.master.socket_path).with_name('crawl-ledger.json'))
        crawl_desk = CrawlDesk(crawl_settings, MasterClient(config.master), feeds=feeds,
                               production=ProductionSettings(config.master), projector=projector,
                               feed_options=feed_settings.read, ledger=ledger)

        # Station promos' live values (promos.py): the temperature (a weather feed of its own,
        # fetched only while a promo shows it) and the programme on air, voiced for 'only-on'.
        def on_air_programme():
            if projector is None:
                return None
            now = datetime.now(timezone.utc)
            segments = projector.describe(now, now + timedelta(hours=1))['segments']
            return next((s for s in segments if s.get('kind') != 'ident'), None)

        def programme_name(segment):
            shown = promos_module.display_name(segment, projector.game_info if projector else None)
            return shown, (projector.spoken(segment, 'en') if projector and shown else shown)

        voice_folder = config.state_file.parent / 'continuity' / 'voice'
        from .continuity import mix as continuity_mix
        promo_desk = PromoDesk(Promos(config.master.socket_path), programme=on_air_programme, name=programme_name,
                               weather=crawl_feeds.WeatherFeed(config.crawl.weather_station, config.crawl.forecast_point,
                                                               config.crawl.weather_place,
                                                               lambda: feed_settings.read()['weather']),
                               voice=continuity.voice if continuity else Voice(voice_folder, config.continuity.keys_file),
                               master=coordinator.master if coordinator else MasterClient(config.master),
                               mix=continuity_mix, start_worker=False)
    server = ThreadingHTTPServer(
        (config.server.host, config.server.port),
        handler_factory(config, roku, scheduler, baseball, playout, sources, coordinator, programming, sports,
                        production_monitor, projector, continuity, crawl_desk, promo_desk),
    )
    if roku is not None:
        roku.hold.start()
    production_monitor.start()
    if config.master.enabled:
        # My ads' break card, drawn before master first needs it (it keeps the last one it had).
        def draw_card():
            try:
                MyAds(config.master.socket_path).card()
            except Exception as exc:
                print(f'My ads: cannot draw the break card: {exc}', flush=True)
        threading.Thread(target=draw_card, name='my-ads-card', daemon=True).start()
    if isinstance(playout, SourceQueue):
        playout.start()
        programming.start()
        continuity.start()
    if crawl_desk:
        crawl_desk.start()
    if promo_desk:
        promo_desk.start()
    print(
        f"Roku Stream listening on http://{config.server.host}:{config.server.port}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        production_monitor.close()
        if isinstance(playout, SourceQueue):
            playout.pause('Service stopping')
        if programming:
            programming.close()
        if continuity:
            continuity.close()
        if crawl_desk:
            crawl_desk.stop()
        if promo_desk:
            promo_desk.close()
        coordinator.close()
        library.close()
        server.shutdown()
        server.server_close()
        playout.close()
        scheduler.close()
        if roku is not None:
            roku.hold.stop()  # Keeps the lock: the worker may still be playing the Roku.
