from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .errors import ConfigError


_VALID_KEYS = {
    "Home",
    "Rev",
    "Fwd",
    "Play",
    "Select",
    "Left",
    "Right",
    "Down",
    "Up",
    "Back",
    "InstantReplay",
    "Info",
    "Backspace",
    "Search",
    "Enter",
}


def normalize_channel_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 6969
    api_key: str | None = None


@dataclass(frozen=True)
class RokuConfig:
    url: str | None = None
    discovery_address: str = "0.0.0.0"
    app_name: str = "YouTube TV"
    app_id: str | None = None
    request_timeout_seconds: float = 5.0
    launch_timeout_seconds: float = 40.0
    playback_timeout_seconds: float = 35.0
    poll_interval_seconds: float = 1.0


@dataclass(frozen=True)
class PrimeVideoConfig:
    # Only this visibly focused adult profile may be selected automatically.
    # Empty disables profile selection and leaves it to the operator.
    profile_name: str = "Vivian"


@dataclass(frozen=True)
class MlbConfig:
    app_name: str = "MLB"
    app_id: str | None = "14"
    schedule_url: str = "https://statsapi.mlb.com/api/v1/schedule"
    request_timeout_seconds: float = 10.0
    cache_seconds: float = 60.0
    launch_settle_seconds: float = 12.0
    games_settle_seconds: float = 7.0
    scan_settle_seconds: float = 1.2
    max_cards: int = 24


@dataclass(frozen=True)
class NavigationConfig:
    reset_back_presses: int = 8
    reset_key_delay_seconds: float = 1.0
    post_exit_settle_seconds: float = 4.0
    launch_settle_seconds: float = 10.0
    key_delay_seconds: float = 0.9
    guide_settle_seconds: float = 5.0
    play_settle_seconds: float = 1.5
    guide_scan_lookbehind: int = 2
    guide_scan_max_rows: int = 14
    # A clean YouTube TV launch focuses Home on the supported UI. Right selects
    # Live; Select opens it; two Downs move through ON NOW to the first guide row.
    open_live_guide_keys: tuple[str, ...] = ("Right", "Select", "Down", "Down")


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    aliases: tuple[str, ...] = ()
    guide_index: int = 0
    template: str | None = None
    network_page: str | None = None
    anchor_safe: bool = True


@dataclass(frozen=True)
class FeedbackConfig:
    backend: str = "tv_thing"
    device: str | None = None
    input_format: str = "yuyv422"
    contribution_url: str | None = None
    source_name: str = "Roku USB capture"
    video_standard: str | None = None
    input_index: int | None = None
    base_url: str | None = None
    status_path: str = "/api/status"
    playlist_path: str = "/stream/live.m3u8"
    required_source: str = "cable"
    required_cable_channel: int = 69
    required_capture_id: str | None = None
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    capture_timeout_seconds: float = 15.0
    focus_luma_threshold: int = 145
    template_difference_threshold: float = 12.0
    template_margin: float = 1.5
    guide_correlation_threshold: float = 0.86
    guide_correlation_margin: float = 0.005
    network_template_margin: float = 1.0
    verify_attempts: int = 3
    verify_retry_seconds: float = 2.0
    template_dir: Path | None = None
    profile_template: str = "profile-vivian.json"
    ocr_enabled: bool = True
    ocr_required: bool = True
    tesseract_path: str = "auto"
    ocr_scale: int = 3
    ocr_min_confidence: float = 20.0
    ocr_timeout_seconds: float = 15.0
    network_page_settle_seconds: float = 7.0
    fresh_segments: bool = False
    network_page_fallback: bool = False

    @property
    def fresh_frames(self) -> bool:
        return self.backend == "direct" or self.fresh_segments


@dataclass(frozen=True)
class TvThingConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080/"
    request_timeout_seconds: float = 4.0
    catalog_cache_seconds: float = 300.0
    guide_cache_seconds: float = 60.0
    retry_seconds: float = 15.0


@dataclass(frozen=True)
class MasterConfig:
    enabled: bool = False
    socket_path: Path = Path("state/master.sock")
    rtsp_url: str = "rtsp://127.0.0.1:18554/master"
    status_url: str = "http://127.0.0.1:19997/v3/paths/get/master"
    hls_url: str = "http://127.0.0.1:18888/master/"
    width: int = 1280
    height: int = 720
    fps: int = 30
    bitrate: int = 2500
    roku_prepare_max_age_seconds: int = 900
    off_air_radio_url: str = "http://127.0.0.1:1615/cairo.mp3"
    off_air_radio_info_url: str | None = "http://127.0.0.1:1894"
    # Cairo is mastered near -15 LUFS; -9 dB brings it to the -24 LKFS broadcast sources use.
    off_air_radio_gain_db: float = -9.0
    # "auto" uses NVENC when it can encode, else x264.
    encoder: str = "auto"
    # The local EAS decoder (its /eas prefix): alerts for these SAME areas run in the crawl.
    # 011001 is the District of Columbia.
    eas_url: str | None = "http://127.0.0.1:8090/eas"
    eas_areas: tuple[str, ...] = ("011001",)
    # api.weather.gov alert zones: DC's public forecast zone and its county (for warnings).
    nws_zones: tuple[str, ...] = ("DCZ001", "DCC001")


@dataclass(frozen=True)
class LibraryRoot:
    id: str
    name: str
    path: Path
    # Its files may be queued with ad breaks spliced in (library_breaks.py): a show's own
    # folder (Jellyfin), never TV-Thing's recordings, whose breaks are already cut out live.
    ad_breaks: bool = False


@dataclass(frozen=True)
class LibraryConfig:
    enabled: bool = False
    roots: tuple[LibraryRoot, ...] = ()


@dataclass(frozen=True)
class ContinuityConfig:
    # A KEY=value file holding DEEPGRAM_API_KEY, read when an announcement is voiced;
    # DEEPGRAM_API_KEY in the environment is used first.
    keys_file: Path | None = None


@dataclass(frozen=True)
class CrawlConfig:
    # A KEY=value file holding WMATA_API_KEY (for Metro and bus); the environment comes first.
    keys_file: Path | None = None
    # The latest observation for the weather segment, and the point whose forecast it reads.
    weather_station: str = "KDCA"
    weather_place: str = "Reagan National"
    forecast_point: tuple[float, float] = (38.8951, -77.0364)


@dataclass(frozen=True)
class AppConfig:
    server: ServerConfig
    roku: RokuConfig
    mlb: MlbConfig
    navigation: NavigationConfig
    feedback: FeedbackConfig
    channels: tuple[ChannelConfig, ...]
    state_file: Path
    config_path: Path
    _channel_lookup: dict[str, int] = field(repr=False, compare=False)
    tv_thing: TvThingConfig = field(default_factory=TvThingConfig)
    master: MasterConfig = field(default_factory=MasterConfig)
    library: LibraryConfig = field(default_factory=LibraryConfig)
    continuity: ContinuityConfig = field(default_factory=ContinuityConfig)
    crawl: CrawlConfig = field(default_factory=CrawlConfig)
    prime_video: PrimeVideoConfig = field(default_factory=PrimeVideoConfig)
    # Since 2026-10-06 the source Roku is TV Thing's Roku lane: with no
    # configured channels, YouTube TV's channels come from its catalog.
    channel_catalog: object | None = field(default=None, repr=False, compare=False)

    def youtube_tv_channels(self) -> tuple[ChannelConfig, ...]:
        """YouTube TV's channels in Live-guide order: configured, or TV Thing's."""
        if self.channels or self.channel_catalog is None:
            return self.channels
        return self.channel_catalog.channels()

    def resolve_channel(self, requested: str) -> tuple[int, ChannelConfig]:
        if not self.channels and self.channel_catalog is not None:
            return self.channel_catalog.resolve(requested)
        key = normalize_channel_name(requested)
        index = self._channel_lookup.get(key)
        if index is None:
            from .errors import ChannelNotFoundError

            raise ChannelNotFoundError(
                f"Unknown YouTube TV channel: {requested!r}",
                details={"available": [channel.name for channel in self.channels]},
            )
        return index, self.channels[index]


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a JSON object")
    return value


def _number(data: dict[str, Any], key: str, default: float) -> float:
    value = data.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ConfigError(f"{key} must be a non-negative number")
    return float(value)


def _library(raw: dict[str, Any]) -> LibraryConfig:
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("library.enabled must be true or false")
    values = raw.get("roots", [])
    if not isinstance(values, list):
        raise ConfigError("library.roots must be a list")
    roots = []
    for value in values:
        value = _mapping(value, "library root")
        root_id, name, path = value.get("id"), value.get("name"), value.get("path")
        # Root IDs are the first component of every item ID and queue entry.
        if not isinstance(root_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", root_id):
            raise ConfigError("library root id must be 1-40 lowercase letters, digits or hyphens")
        if any(root.id == root_id for root in roots):
            raise ConfigError(f"Duplicate library root id: {root_id}")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError("library root name must be a non-empty string")
        if not isinstance(path, str) or not Path(path).is_absolute():
            raise ConfigError("library root path must be an absolute directory")
        ad_breaks = value.get("ad_breaks", False)
        if not isinstance(ad_breaks, bool):
            raise ConfigError("library root ad_breaks must be true or false")
        roots.append(LibraryRoot(id=root_id, name=name.strip(), path=Path(path), ad_breaks=ad_breaks))
    if enabled and not roots:
        raise ConfigError("library.enabled requires at least one root")
    return LibraryConfig(enabled=enabled, roots=tuple(roots))


def _continuity(raw: dict[str, Any]) -> ContinuityConfig:
    keys = raw.get("keys_file")
    if keys is not None and (not isinstance(keys, str) or not Path(keys).is_absolute()):
        raise ConfigError("continuity.keys_file must be an absolute path")
    return ContinuityConfig(keys_file=Path(keys) if keys else None)


def _crawl(raw: dict[str, Any]) -> CrawlConfig:
    keys = raw.get("keys_file")
    if keys is not None and (not isinstance(keys, str) or not Path(keys).is_absolute()):
        raise ConfigError("crawl.keys_file must be an absolute path")
    station = raw.get("weather_station", "KDCA")
    if not isinstance(station, str) or not re.fullmatch(r"[A-Z0-9]{3,5}", station):
        raise ConfigError("crawl.weather_station must be an NWS station ID such as KDCA")
    place = raw.get("weather_place", "Reagan National")
    if not isinstance(place, str) or not 1 <= len(place) <= 40:
        raise ConfigError("crawl.weather_place must be a short name")
    point = raw.get("forecast_point", [38.8951, -77.0364])
    if (not isinstance(point, list) or len(point) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in point)
            or not -90 <= point[0] <= 90 or not -180 <= point[1] <= 180):
        raise ConfigError("crawl.forecast_point must be [latitude, longitude]")
    return CrawlConfig(keys_file=Path(keys) if keys else None, weather_station=station, weather_place=place,
                       forecast_point=(float(point[0]), float(point[1])))


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file does not exist: {config_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Cannot read configuration {config_path}: {exc}") from exc

    root = _mapping(raw, "configuration")
    server_raw = _mapping(root.get("server"), "server")
    roku_raw = _mapping(root.get("roku"), "roku")
    mlb_raw = _mapping(root.get("mlb"), "mlb")
    prime_raw = _mapping(root.get("prime_video"), "prime_video")
    prime_profile = prime_raw.get("profile_name", "Vivian")
    if not isinstance(prime_profile, str) or len(prime_profile) > 100:
        raise ConfigError("prime_video.profile_name must be a string of at most 100 characters")
    nav_raw = _mapping(root.get("navigation"), "navigation")
    tv_raw = _mapping(root.get("tv_thing"), "tv_thing")
    tv_enabled = tv_raw.get("enabled", False)
    if not isinstance(tv_enabled, bool):
        raise ConfigError("tv_thing.enabled must be a boolean")
    tv_base = tv_raw.get("base_url", "http://127.0.0.1:8080/")
    try:
        parsed = urlsplit(tv_base) if isinstance(tv_base, str) else None
        valid = (parsed and parsed.scheme in ("http", "https") and parsed.hostname
                 and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment
                 and not any(c.isspace() for c in tv_base))
        if parsed:
            parsed.port  # Validate the port before the first HTTP request.
    except ValueError:
        valid = False
    if not valid:
        raise ConfigError("tv_thing.base_url must be an HTTP(S) application URL without credentials, query or fragment")
    tv_numbers = {}
    for key, default in (("request_timeout_seconds", 4.0), ("catalog_cache_seconds", 300.0),
                         ("guide_cache_seconds", 60.0), ("retry_seconds", 15.0)):
        value = _number(tv_raw, key, default)
        if not math.isfinite(value) or value <= 0 or value > 3600:
            raise ConfigError(f"tv_thing.{key} must be finite and between 0 and 3600 seconds (exclusive of 0)")
        tv_numbers[key] = value
    tv_thing = TvThingConfig(enabled=tv_enabled, base_url=tv_base.rstrip("/") + "/", **tv_numbers)
    master_raw = _mapping(root.get("master"), "master")
    master_enabled = master_raw.get("enabled", False)
    if not isinstance(master_enabled, bool):
        raise ConfigError("master.enabled must be true or false")
    master_socket = master_raw.get("socket_path", "state/master.sock")
    if not isinstance(master_socket, str) or not master_socket:
        raise ConfigError("master.socket_path must be a non-empty path")
    master_socket = Path(master_socket)
    if not master_socket.is_absolute():
        master_socket = config_path.parent / master_socket
    master_urls = {}
    for key, default, scheme in (("rtsp_url", "rtsp://127.0.0.1:18554/master", "rtsp"),
                                 ("status_url", "http://127.0.0.1:19997/v3/paths/get/master", "http"),
                                 ("hls_url", "http://127.0.0.1:18888/master/", "http")):
        value = master_raw.get(key, default)
        parsed = urlsplit(value) if isinstance(value, str) else None
        if not parsed or parsed.scheme != scheme or parsed.hostname != "127.0.0.1" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigError(f"master.{key} must be a {scheme}://127.0.0.1 URL without credentials, query or fragment")
        try:
            if parsed.port is None or not parsed.path or parsed.path == "/":
                raise ValueError()
        except ValueError as exc:
            raise ConfigError(f"master.{key} requires a valid port and path") from exc
        master_urls[key] = value
    if not master_urls["hls_url"].endswith("/"):
        raise ConfigError("master.hls_url must end with a slash")
    master_numbers = {}
    for key, default, low, high in (("width", 1280, 160, 1920), ("height", 720, 90, 1080),
                                   ("fps", 30, 10, 60), ("bitrate", 2500, 128, 10000),
                                   ("roku_prepare_max_age_seconds", 900, 1, 3600)):
        value = master_raw.get(key, default)
        if type(value) is not int or not low <= value <= high or (key in ("width", "height") and value % 2):
            raise ConfigError(f"Invalid master.{key}")
        master_numbers[key] = value
    radio_url = master_raw.get("off_air_radio_url", "http://127.0.0.1:1615/cairo.mp3")
    parsed = urlsplit(radio_url) if isinstance(radio_url, str) else None
    if not parsed or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ConfigError("master.off_air_radio_url must be an http:// or https:// URL")
    info_url = master_raw.get("off_air_radio_info_url", "http://127.0.0.1:1894")
    parsed = urlsplit(info_url) if isinstance(info_url, str) else None
    if info_url is not None and (not parsed or parsed.scheme not in ("http", "https") or not parsed.hostname):
        raise ConfigError("master.off_air_radio_info_url must be null or an http:// or https:// URL")
    radio_gain = master_raw.get("off_air_radio_gain_db", -9.0)
    if isinstance(radio_gain, bool) or not isinstance(radio_gain, (int, float)) or not -40 <= radio_gain <= 6:
        raise ConfigError("master.off_air_radio_gain_db must be a number from -40 through 6")
    encoder = master_raw.get("encoder", "auto")
    if encoder not in ("auto", "nvenc", "x264"):
        raise ConfigError("master.encoder must be auto, nvenc or x264")
    eas_url = master_raw.get("eas_url", "http://127.0.0.1:8090/eas")
    parsed = urlsplit(eas_url) if isinstance(eas_url, str) else None
    if eas_url is not None and (not parsed or parsed.scheme not in ("http", "https") or not parsed.hostname
                                or parsed.username or parsed.password):
        raise ConfigError("master.eas_url must be null or an http:// or https:// URL without credentials")
    eas_areas = master_raw.get("eas_areas", ["011001"])
    if (not isinstance(eas_areas, list) or not 1 <= len(eas_areas) <= 32
            or any(not isinstance(code, str) or len(code) != 6 or not code.isdigit() for code in eas_areas)):
        raise ConfigError("master.eas_areas must list 1 to 32 six-digit SAME location codes (PSSCCC)")
    nws_zones = master_raw.get("nws_zones", ["DCZ001", "DCC001"])
    if (not isinstance(nws_zones, list) or len(nws_zones) > 16
            or any(not isinstance(zone, str) or not re.fullmatch(r"[A-Z]{2}[CZ]\d{3}", zone) for zone in nws_zones)):
        raise ConfigError("master.nws_zones must list up to 16 NWS zone IDs such as DCZ001 (empty turns NWS alerts off)")
    master = MasterConfig(enabled=master_enabled, socket_path=master_socket.resolve(), **master_urls, **master_numbers,
                          off_air_radio_url=radio_url, off_air_radio_info_url=info_url,
                          off_air_radio_gain_db=float(radio_gain), encoder=encoder,
                          eas_url=eas_url, eas_areas=tuple(eas_areas), nws_zones=tuple(nws_zones))
    library = _library(_mapping(root.get("library"), "library"))

    port = server_raw.get("port", 6969)
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ConfigError("server.port must be an integer from 1 through 65535")
    api_key = server_raw.get("api_key")
    if api_key is not None and (not isinstance(api_key, str) or not api_key):
        raise ConfigError("server.api_key must be null or a non-empty string")
    server = ServerConfig(
        host=str(server_raw.get("host", "127.0.0.1")),
        port=port,
        api_key=api_key,
    )

    roku_url = roku_raw.get("url")
    if roku_url is not None:
        if not isinstance(roku_url, str) or not roku_url.startswith("http://"):
            raise ConfigError("roku.url must be an http:// URL or null")
        roku_url = roku_url.rstrip("/")
    app_id = roku_raw.get("app_id")
    if app_id is not None:
        app_id = str(app_id)
    roku = RokuConfig(
        url=roku_url,
        discovery_address=str(roku_raw.get("discovery_address", "0.0.0.0")),
        app_name=str(roku_raw.get("app_name", "YouTube TV")),
        app_id=app_id,
        request_timeout_seconds=_number(roku_raw, "request_timeout_seconds", 5.0),
        launch_timeout_seconds=_number(roku_raw, "launch_timeout_seconds", 40.0),
        playback_timeout_seconds=_number(roku_raw, "playback_timeout_seconds", 35.0),
        poll_interval_seconds=_number(roku_raw, "poll_interval_seconds", 1.0),
    )

    mlb_app_id = mlb_raw.get("app_id", "14")
    if mlb_app_id is not None:
        mlb_app_id = str(mlb_app_id)
    schedule_url = str(
        mlb_raw.get(
            "schedule_url", "https://statsapi.mlb.com/api/v1/schedule"
        )
    )
    if not schedule_url.startswith(("https://", "http://")):
        raise ConfigError("mlb.schedule_url must be an http:// or https:// URL")
    max_cards = mlb_raw.get("max_cards", 24)
    if (
        isinstance(max_cards, bool)
        or not isinstance(max_cards, int)
        or not 1 <= max_cards <= 60
    ):
        raise ConfigError("mlb.max_cards must be from 1 through 60")
    mlb = MlbConfig(
        app_name=str(mlb_raw.get("app_name", "MLB")),
        app_id=mlb_app_id,
        schedule_url=schedule_url,
        request_timeout_seconds=_number(
            mlb_raw, "request_timeout_seconds", 10.0
        ),
        cache_seconds=_number(mlb_raw, "cache_seconds", 60.0),
        launch_settle_seconds=_number(
            mlb_raw, "launch_settle_seconds", 12.0
        ),
        games_settle_seconds=_number(
            mlb_raw, "games_settle_seconds", 7.0
        ),
        scan_settle_seconds=_number(
            mlb_raw, "scan_settle_seconds", 1.2
        ),
        max_cards=max_cards,
    )

    keys_raw = nav_raw.get(
        "open_live_guide_keys", ["Right", "Select", "Down", "Down"]
    )
    if not isinstance(keys_raw, list) or not keys_raw:
        raise ConfigError("navigation.open_live_guide_keys must be a non-empty array")
    keys: list[str] = []
    for key in keys_raw:
        if not isinstance(key, str) or key not in _VALID_KEYS:
            raise ConfigError(f"Unsupported Roku key in open_live_guide_keys: {key!r}")
        keys.append(key)
    reset_back_presses = nav_raw.get("reset_back_presses", 8)
    if (
        isinstance(reset_back_presses, bool)
        or not isinstance(reset_back_presses, int)
        or not 1 <= reset_back_presses <= 30
    ):
        raise ConfigError("navigation.reset_back_presses must be from 1 through 30")
    guide_scan_lookbehind = nav_raw.get("guide_scan_lookbehind", 2)
    if (
        isinstance(guide_scan_lookbehind, bool)
        or not isinstance(guide_scan_lookbehind, int)
        or not 0 <= guide_scan_lookbehind <= 20
    ):
        raise ConfigError("navigation.guide_scan_lookbehind must be from 0 through 20")
    guide_scan_max_rows = nav_raw.get("guide_scan_max_rows", 14)
    if (
        isinstance(guide_scan_max_rows, bool)
        or not isinstance(guide_scan_max_rows, int)
        or not 1 <= guide_scan_max_rows <= 100
    ):
        raise ConfigError("navigation.guide_scan_max_rows must be from 1 through 100")
    navigation = NavigationConfig(
        reset_back_presses=reset_back_presses,
        reset_key_delay_seconds=_number(nav_raw, "reset_key_delay_seconds", 1.0),
        post_exit_settle_seconds=_number(nav_raw, "post_exit_settle_seconds", 4.0),
        launch_settle_seconds=_number(nav_raw, "launch_settle_seconds", 10.0),
        key_delay_seconds=_number(nav_raw, "key_delay_seconds", 0.9),
        guide_settle_seconds=_number(nav_raw, "guide_settle_seconds", 5.0),
        play_settle_seconds=_number(nav_raw, "play_settle_seconds", 1.5),
        guide_scan_lookbehind=guide_scan_lookbehind,
        guide_scan_max_rows=guide_scan_max_rows,
        open_live_guide_keys=tuple(keys),
    )

    feedback_raw = _mapping(root.get("feedback"), "feedback")
    feedback_url = feedback_raw.get("base_url")
    if feedback_url is not None:
        if not isinstance(feedback_url, str) or not feedback_url.startswith("http://"):
            raise ConfigError("feedback.base_url must be an http:// URL or null")
        feedback_url = feedback_url.rstrip("/")
    required_source = feedback_raw.get("required_source", "cable")
    if required_source not in ("cable", "capture"):
        raise ConfigError("feedback.required_source must be 'cable' or 'capture'")
    required_channel = feedback_raw.get("required_cable_channel", 69)
    if (
        isinstance(required_channel, bool)
        or not isinstance(required_channel, int)
        or not 1 <= required_channel <= 135
    ):
        raise ConfigError("feedback.required_cable_channel must be from 1 through 135")
    required_capture_id = feedback_raw.get("required_capture_id")
    if required_capture_id is not None and (
        not isinstance(required_capture_id, str) or not required_capture_id.strip()
    ):
        raise ConfigError(
            "feedback.required_capture_id must be null or a non-empty string"
        )
    if required_source == "capture" and required_capture_id is None:
        raise ConfigError(
            "feedback.required_capture_id is required when required_source is 'capture'"
        )
    luma_threshold = feedback_raw.get("focus_luma_threshold", 145)
    if isinstance(luma_threshold, bool) or not isinstance(luma_threshold, int) or not 0 <= luma_threshold <= 255:
        raise ConfigError("feedback.focus_luma_threshold must be from 0 through 255")
    diff_threshold = _number(
        feedback_raw, "template_difference_threshold", 12.0
    )
    template_margin = _number(feedback_raw, "template_margin", 1.5)
    guide_correlation_threshold = _number(
        feedback_raw, "guide_correlation_threshold", 0.86
    )
    guide_correlation_margin = _number(
        feedback_raw, "guide_correlation_margin", 0.005
    )
    if guide_correlation_threshold > 1:
        raise ConfigError("guide_correlation_threshold must be from 0 through 1")
    if guide_correlation_margin > 1:
        raise ConfigError("guide_correlation_margin must be from 0 through 1")
    network_template_margin = _number(
        feedback_raw, "network_template_margin", 1.0
    )
    verify_attempts = feedback_raw.get("verify_attempts", 3)
    if (
        isinstance(verify_attempts, bool)
        or not isinstance(verify_attempts, int)
        or not 1 <= verify_attempts <= 10
    ):
        raise ConfigError("feedback.verify_attempts must be from 1 through 10")
    ocr_scale = feedback_raw.get("ocr_scale", 3)
    if (
        isinstance(ocr_scale, bool)
        or not isinstance(ocr_scale, int)
        or not 1 <= ocr_scale <= 6
    ):
        raise ConfigError("feedback.ocr_scale must be from 1 through 6")
    for boolean_key in ("ocr_enabled", "ocr_required", "fresh_segments", "network_page_fallback"):
        if boolean_key in feedback_raw and not isinstance(
            feedback_raw[boolean_key], bool
        ):
            raise ConfigError(f"feedback.{boolean_key} must be true or false")

    channels_raw = root.get("channels", [])
    # The channels belong to the Roku, which TV Thing now drives: a
    # configuration without them reads TV Thing's catalog instead.
    if not isinstance(channels_raw, list) or (not channels_raw and not tv_thing.enabled):
        raise ConfigError("channels must be a non-empty array in exact Live-guide order "
                          "(or enable tv_thing, whose Roku lane lists them)")
    channels: list[ChannelConfig] = []
    lookup: dict[str, int] = {}
    for index, item in enumerate(channels_raw):
        item = _mapping(item, f"channels[{index}]")
        name = item.get("name")
        aliases = item.get("aliases", [])
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"channels[{index}].name must be a non-empty string")
        if not isinstance(aliases, list) or not all(isinstance(v, str) for v in aliases):
            raise ConfigError(f"channels[{index}].aliases must be an array of strings")
        guide_index = item.get("guide_index", index)
        if isinstance(guide_index, bool) or not isinstance(guide_index, int) or guide_index < 0:
            raise ConfigError(f"channels[{index}].guide_index must be a non-negative integer")
        template = item.get("template")
        if template is not None and (not isinstance(template, str) or not template):
            raise ConfigError(f"channels[{index}].template must be null or a non-empty string")
        network_page = item.get("network_page")
        if network_page is not None and (
            not isinstance(network_page, str) or not network_page.strip()
        ):
            raise ConfigError(
                f"channels[{index}].network_page must be null or a non-empty string"
            )
        anchor_safe = item.get("anchor_safe", True)
        if not isinstance(anchor_safe, bool):
            raise ConfigError(f"channels[{index}].anchor_safe must be true or false")
        channel = ChannelConfig(
            name=name.strip(),
            aliases=tuple(aliases),
            guide_index=guide_index,
            template=template,
            network_page=network_page.strip() if network_page else None,
            anchor_safe=anchor_safe,
        )
        channels.append(channel)
        for value in (channel.name, *channel.aliases):
            key = normalize_channel_name(value)
            if not key:
                raise ConfigError(f"Channel name or alias cannot normalize to empty: {value!r}")
            if key in lookup and lookup[key] != index:
                raise ConfigError(f"Duplicate channel name or alias: {value!r}")
            lookup[key] = index

    state_value = root.get("state_file", "state/jobs.json")
    if not isinstance(state_value, str) or not state_value:
        raise ConfigError("state_file must be a non-empty path")
    state_file = Path(state_value)
    if not state_file.is_absolute():
        state_file = config_path.parent / state_file

    template_dir_value = feedback_raw.get("template_dir", "state/templates")
    if not isinstance(template_dir_value, str) or not template_dir_value:
        raise ConfigError("feedback.template_dir must be a non-empty path")
    template_dir = Path(template_dir_value)
    if not template_dir.is_absolute():
        template_dir = config_path.parent / template_dir
    backend = feedback_raw.get("backend", "tv_thing")
    if backend not in ("direct", "tv_thing"):
        raise ConfigError("feedback.backend must be direct or tv_thing")
    device = feedback_raw.get("device")
    if backend == "direct" and (
        not isinstance(device, str) or not device.startswith("/dev/")
        or ".." in Path(device).parts
    ):
        raise ConfigError("Direct feedback requires an absolute /dev/ capture device path")
    input_format = feedback_raw.get("input_format", "yuyv422")
    if input_format not in ("yuyv422", "uyvy422", "mjpeg", "mpegts"):
        raise ConfigError("feedback.input_format must be yuyv422, uyvy422, mjpeg, or mpegts")
    contribution_url = feedback_raw.get("contribution_url")
    if contribution_url is not None:
        # This is a private contribution, never a browser-supplied destination.
        if not isinstance(contribution_url, str) or not re.fullmatch(
                r"rtsp://127\.0\.0\.1:[0-9]{1,5}/[a-zA-Z0-9_-]+", contribution_url):
            raise ConfigError("feedback.contribution_url must be a loopback RTSP URL with a port and path")
        if not 1 <= int(contribution_url.split(":")[2].split("/")[0]) <= 65535:
            raise ConfigError("feedback.contribution_url has an invalid port")
        if contribution_url == master.rtsp_url:
            raise ConfigError("Roku contribution must use a different path from the master output")
        if backend != "direct" or input_format != "mpegts":
            raise ConfigError("Roku contribution requires direct MPEG-TS capture")
    source_name = feedback_raw.get("source_name", "Roku USB capture")
    if not isinstance(source_name, str) or not source_name.strip():
        raise ConfigError("feedback.source_name must be a non-empty string")
    video_standard = feedback_raw.get("video_standard")
    if video_standard not in (None, "NTSC-M", "PAL"):
        raise ConfigError("feedback.video_standard must be NTSC-M or PAL")
    input_index = feedback_raw.get("input_index")
    if input_index is not None and (type(input_index) is not int or not 0 <= input_index <= 31):
        raise ConfigError("feedback.input_index must be an integer from 0 through 31")
    feedback = FeedbackConfig(
        backend=backend,
        device=device,
        input_format=input_format,
        contribution_url=contribution_url,
        source_name=source_name.strip(),
        video_standard=video_standard,
        input_index=input_index,
        base_url=feedback_url,
        status_path=str(feedback_raw.get("status_path", "/api/status")),
        playlist_path=str(feedback_raw.get("playlist_path", "/stream/live.m3u8")),
        required_source=required_source,
        required_cable_channel=required_channel,
        required_capture_id=(
            required_capture_id.strip() if required_capture_id is not None else None
        ),
        ffmpeg_path=str(feedback_raw.get("ffmpeg_path", "/usr/bin/ffmpeg")),
        capture_timeout_seconds=_number(
            feedback_raw, "capture_timeout_seconds", 15.0
        ),
        focus_luma_threshold=luma_threshold,
        template_difference_threshold=diff_threshold,
        template_margin=template_margin,
        guide_correlation_threshold=guide_correlation_threshold,
        guide_correlation_margin=guide_correlation_margin,
        network_template_margin=network_template_margin,
        verify_attempts=verify_attempts,
        verify_retry_seconds=_number(feedback_raw, "verify_retry_seconds", 2.0),
        template_dir=template_dir.resolve(),
        profile_template=str(
            feedback_raw.get("profile_template", "profile-vivian.json")
        ),
        ocr_enabled=feedback_raw.get("ocr_enabled", True),
        ocr_required=feedback_raw.get("ocr_required", True),
        tesseract_path=str(feedback_raw.get("tesseract_path", "auto")),
        ocr_scale=ocr_scale,
        ocr_min_confidence=_number(feedback_raw, "ocr_min_confidence", 20.0),
        ocr_timeout_seconds=_number(feedback_raw, "ocr_timeout_seconds", 15.0),
        network_page_settle_seconds=_number(
            feedback_raw, "network_page_settle_seconds", 7.0
        ),
        fresh_segments=feedback_raw.get("fresh_segments", False),
        network_page_fallback=feedback_raw.get("network_page_fallback", False),
    )

    channel_catalog = None
    if not channels and tv_thing.enabled:
        from .tv_thing import TvThingChannels
        channel_catalog = TvThingChannels(tv_thing, state_file.with_name("youtube-tv-channels.json"))

    return AppConfig(
        channel_catalog=channel_catalog,
        server=server,
        roku=roku,
        mlb=mlb,
        prime_video=PrimeVideoConfig(profile_name=prime_profile.strip()),
        navigation=navigation,
        feedback=feedback,
        channels=tuple(channels),
        state_file=state_file.resolve(),
        config_path=config_path,
        _channel_lookup=lookup,
        tv_thing=tv_thing,
        master=master,
        library=library,
        continuity=_continuity(_mapping(root.get("continuity"), "continuity")),
        crawl=_crawl(_mapping(root.get("crawl"), "crawl")),
    )
