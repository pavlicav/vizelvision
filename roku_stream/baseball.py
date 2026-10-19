from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from typing import Callable

from .config import AppConfig, normalize_channel_name
from .errors import BaseballScheduleError, ChannelNotFoundError, ConfigError


# MLB lists shared carriage as "NBC/Peacock", "Peacock/NBCSN" or "FOX / FS1"; each
# part is matched exactly, so a streaming-only partner such as Peacock is skipped.
_YTTV_NETWORKS: tuple[tuple[str, str], ...] = (
    ("ESPN2", "ESPN2"),
    ("ESPN", "ESPN"),
    ("TBS", "TBS"),
    ("TRUTV", "truTV"),
    ("FOX", "FOX"),
    ("FS1", "FS1"),
    ("ABC", "ABC"),
    ("NBC", "NBC"),
    ("NBCSN", "NBC Sports Network"),
    ("MLBN", "MLB Network"),
    ("MLBNETWORK", "MLB Network"),
)

# Streaming services whose exclusives a YouTube TV channel carries, used only when no channel
# of the game's own is configured (NBC/Peacock is on NBC). Northwestern at Michigan State,
# listed by ESPN only as Peacock on 2026-10-17, was on NBC Sports Network.
EXCLUSIVES = {"PEACOCK": "NBC Sports Network"}

_TEAM_CARD_NAMES = {
    108: "Angels", 109: "D-backs", 110: "Orioles", 111: "Red Sox",
    112: "Cubs", 113: "Reds", 114: "Guardians", 115: "Rockies",
    116: "Tigers", 117: "Astros", 118: "Royals", 119: "Dodgers",
    120: "Nationals", 121: "Mets", 133: "Athletics", 134: "Pirates",
    135: "Padres", 136: "Mariners", 137: "Giants", 138: "Cardinals",
    139: "Rays", 140: "Rangers", 141: "Blue Jays", 142: "Twins",
    143: "Phillies", 144: "Braves", 145: "White Sox", 146: "Marlins",
    147: "Yankees", 158: "Brewers",
}


def team_ocr_names(team: dict[str, object]) -> tuple[str, ...]:
    """Return the full and short names MLB renders on Roku game cards."""
    full = str(team.get("name") or "").strip()
    short = _TEAM_CARD_NAMES.get(team.get("id"))
    return tuple(dict.fromkeys(value for value in (full, short) if value))


def scoreline(game: dict[str, object]) -> str:
    """'Phillies 4, Braves 2 · Top 8th' once a game is live or final, else its status."""
    away = game.get("away") if isinstance(game.get("away"), dict) else {}
    home = game.get("home") if isinstance(game.get("home"), dict) else {}
    status = str(game.get("status") or game.get("state") or "")
    started = str(game.get("state") or "").casefold() in ("live", "final", "in", "post")
    if not started or away.get("score") is None or home.get("score") is None:
        return status
    name = lambda team: team.get("nickname") or team.get("name") or "?"
    return f"{name(away)} {away['score']}, {name(home)} {home['score']} · {game.get('detail') or status}"


def _iso_date(value: str | None) -> str:
    if value is None or not value.strip():
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ConfigError("date must use YYYY-MM-DD format") from exc


def _team(raw: object) -> dict[str, object]:
    value = raw if isinstance(raw, dict) else {}
    team = value.get("team") if isinstance(value.get("team"), dict) else {}
    return {
        "id": team.get("id"),
        "name": team.get("name") or "Unknown team",
        "nickname": _TEAM_CARD_NAMES.get(team.get("id")) or team.get("name") or "Unknown team",
        "score": value.get("score"),
        "is_winner": value.get("isWinner") is True,
    }


class MlbScheduleClient:
    """Small cached client for MLB's public schedule feed."""

    def __init__(
        self,
        url: str,
        *,
        timeout: float = 10.0,
        cache_seconds: float = 60.0,
        opener: Callable[..., object] = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.cache_seconds = cache_seconds
        self._opener = opener
        self._clock = clock
        self._cache: dict[str, tuple[float, list[dict[str, object]]]] = {}
        self._lock = threading.Lock()

    def games(self, requested_date: str | None = None) -> tuple[str, list[dict[str, object]]]:
        day = _iso_date(requested_date)
        return day, self._fetch(day, {"sportId": "1", "date": day, "hydrate": "broadcasts,linescore"}, {"date": day})

    def range(self, start: str, end: str) -> list[dict[str, object]]:
        """Every game from start through end (inclusive), for the schedule browser."""
        return self._fetch(f"{start}/{end}", {"sportId": "1", "startDate": start, "endDate": end,
                                               "hydrate": "broadcasts"}, {"start": start, "end": end})

    def by_pk(self, game_pk: int) -> list[dict[str, object]]:
        """Every listing of one game, wherever it is now. A postponed game is listed again
        on its new date; an if-necessary game that was not needed is no longer listed."""
        return self._fetch(f"pk/{game_pk}", {"sportId": "1", "gamePk": str(game_pk), "hydrate": "broadcasts"},
                           {"game_pk": str(game_pk)})

    def _fetch(self, key: str, params: dict[str, str], details: dict[str, str]) -> list[dict[str, object]]:
        now = self._clock()
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] <= self.cache_seconds:
                return cached[1]

        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{self.url}?{query}",
            headers={"Accept": "application/json", "User-Agent": "VizelVision/0.2"},
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise BaseballScheduleError(
                f"Could not load the MLB schedule: {exc}",
                details={**details, "url": self.url},
            ) from exc

        dates = payload.get("dates", []) if isinstance(payload, dict) else []
        raw_games: list[object] = []
        for item in dates if isinstance(dates, list) else []:
            if isinstance(item, dict) and isinstance(item.get("games"), list):
                raw_games.extend(item["games"])
        games = [self._normalize(game) for game in raw_games if isinstance(game, dict)]
        games.sort(key=lambda game: str(game["start_time"]))
        with self._lock:
            self._cache[key] = (now, games)
        return games

    @staticmethod
    def _normalize(raw: dict[str, object]) -> dict[str, object]:
        teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
        status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
        broadcasts: list[dict[str, object]] = []
        for item in raw.get("broadcasts", []) if isinstance(raw.get("broadcasts"), list) else []:
            if not isinstance(item, dict) or str(item.get("type", "")).upper() != "TV":
                continue
            availability = item.get("availability") if isinstance(item.get("availability"), dict) else {}
            media_state = item.get("mediaState") if isinstance(item.get("mediaState"), dict) else {}
            broadcasts.append(
                {
                    "name": item.get("name") or item.get("callSign") or "TV feed",
                    "call_sign": item.get("callSign"),
                    "home_away": item.get("homeAway"),
                    "is_national": item.get("isNational") is True,
                    "available_for_streaming": item.get("availableForStreaming") is True,
                    "availability": availability.get("availabilityText"),
                    "media_state": media_state.get("mediaStateText"),
                    "media_id": item.get("mediaId"),
                }
            )
        away = _team(teams.get("away"))
        home = _team(teams.get("home"))
        linescore = raw.get("linescore") if isinstance(raw.get("linescore"), dict) else {}
        inning = " ".join(str(v) for v in (linescore.get("inningState"), linescore.get("currentInningOrdinal")) if v)
        return {
            "game_pk": raw.get("gamePk"),
            "official_date": raw.get("officialDate"),
            "start_time": raw.get("gameDate"),
            "game_type": raw.get("gameType"),
            "start_time_tbd": status.get("startTimeTBD") is True,
            "series": raw.get("seriesDescription"),
            "series_game": raw.get("seriesGameNumber"),
            "if_necessary": raw.get("ifNecessary") == "Y",
            "status": status.get("detailedState") or status.get("abstractGameState") or "Unknown",
            "state": status.get("abstractGameState") or "Unknown",
            # "Top 8th" while live; the status ("Final") otherwise.
            "detail": inning if status.get("abstractGameState") == "Live" and inning else None,
            "period": linescore.get("currentInning"),
            "half": linescore.get("inningState"),
            "away": away,
            "home": home,
            "title": f"{away['name']} at {home['name']}",
            "broadcasts": broadcasts,
        }


class BaseballCatalog:
    """Resolve one baseball schedule into provider-neutral playable games."""

    def __init__(self, config: AppConfig, client: MlbScheduleClient | None = None) -> None:
        self.config = config
        self.client = client or MlbScheduleClient(
            config.mlb.schedule_url,
            timeout=config.mlb.request_timeout_seconds,
            cache_seconds=config.mlb.cache_seconds,
        )

    def games(self, requested_date: str | None = None) -> dict[str, object]:
        day, games = self.client.games(requested_date)
        resolved = [self._with_sources(game) for game in games]
        return {
            "date": day,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "games": resolved,
        }

    def range(self, start: str, end: str) -> list[dict[str, object]]:
        return [self._with_sources(game) for game in self.client.range(start, end)]

    def game(self, game_pk: int, requested_date: str | None = None) -> dict[str, object]:
        catalog = self.games(requested_date)
        match = next(
            (game for game in catalog["games"] if game.get("game_pk") == game_pk),
            None,
        )
        if match is None:
            raise ConfigError(f"MLB game {game_pk} is not on the requested date")
        return match

    def locate(self, game_pk: int) -> dict[str, object] | None:
        """One game by id on whatever date it is now, or None once MLB no longer lists it."""
        games = [self._with_sources(game) for game in self.client.by_pk(game_pk)]
        return next((game for game in games if str(game.get("status")).casefold() != "postponed"),
                    games[0] if games else None)

    def game_status(
        self, game_pk: int, requested_date: str | None = None
    ) -> dict[str, object]:
        """Return the small, provider-neutral gate used by the playout queue."""
        game = self.game(game_pk, requested_date)
        state = str(game.get("state") or "Unknown")
        status = str(game.get("status") or state)
        terminal_statuses = {
            "final",
            "game over",
            "completed early",
            "cancelled",
            "canceled",
            "postponed",
        }
        return {
            "game_pk": game_pk,
            "title": game.get("title"),
            "state": state,
            "status": status,
            "summary": scoreline(game),
            "period": game.get("period"),
            "finished": (
                state.casefold() == "final"
                or status.casefold() in terminal_statuses
            ),
        }

    def _configured_channel(self, name: str) -> str | None:
        try:
            _, channel = self.config.resolve_channel(name)
        except ChannelNotFoundError:
            return None
        return channel.name

    def _yttv_channel(self, broadcast: dict[str, object]) -> str | None:
        if broadcast.get("is_national") is not True:
            return None
        return next(iter(self._yttv_channels(broadcast)), None)

    def _yttv_channels(self, broadcast: dict[str, object]) -> list[str]:
        """Configured channels for a national broadcast, in listed order."""
        if broadcast.get("is_national") is not True:
            return []
        # ESPN+ is streaming: without its "+" it would be ESPN.
        parts = [normalize_channel_name(part) for field in ("name", "call_sign")
                 for part in str(broadcast.get(field) or "").split("/")
                 if part.strip() and not part.strip().endswith("+")]
        tokens = {normalize_channel_name(token): name for token, name in _YTTV_NETWORKS}
        found: list[str] = []
        # Exact parts only: NBC must not match NBCSN, nor FOX match "FOX Dep." (Fox Deportes).
        for part in parts:
            channel = self._configured_channel(tokens[part]) if part in tokens else None
            if channel and channel not in found:
                found.append(channel)
        # A Peacock exclusive is on NBC Sports Network; NBC/Peacock is on NBC.
        exclusive = [EXCLUSIVES[part.upper()] for part in parts if part.upper() in EXCLUSIVES]
        if not found and exclusive and self._configured_channel(exclusive[0]):
            found.append(self._configured_channel(exclusive[0]))
        return found

    def _with_sources(self, game: dict[str, object]) -> dict[str, object]:
        sources: list[dict[str, object]] = []
        seen_channels: set[str] = set()
        broadcasts = game.get("broadcasts", [])
        for broadcast in broadcasts if isinstance(broadcasts, list) else []:
            if not isinstance(broadcast, dict):
                continue
            for channel in self._yttv_channels(broadcast):
                if channel in seen_channels:
                    continue
                seen_channels.add(channel)
                sources.append(
                    {
                        "provider": "youtube_tv",
                        "label": channel,
                        "channel": channel,
                        "broadcast": broadcast.get("name"),
                        "availability": "scheduled",
                    }
                )

        mlb_feeds = [
            {
                "name": item.get("name"),
                "home_away": item.get("home_away"),
                "media_id": item.get("media_id"),
            }
            for item in broadcasts if isinstance(item, dict)
            and item.get("available_for_streaming") is True
        ] if isinstance(broadcasts, list) else []
        if mlb_feeds:
            sources.append(
                {
                    "provider": "mlb",
                    "label": "MLB.TV",
                    "feeds": mlb_feeds,
                    "availability": "verify_in_app",
                }
            )

        state = str(game.get("state") or "Unknown")
        if state.casefold() == "final":
            sources.sort(key=lambda source: source["provider"] != "mlb")
        result = dict(game)
        result["sources"] = sources
        result["preferred_source"] = sources[0] if sources else None
        result["playable"] = bool(sources)
        return result
