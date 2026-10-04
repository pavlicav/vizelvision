"""Provider-neutral, read-only source and program catalog."""
from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable

from .config import AppConfig
from .errors import ChannelNotFoundError
from .tv_thing import SourceUnavailableError, TvThingClient


SOURCE_INFO = {
    "tv-thing-digital": ("TV-Thing Digital", "tv_thing:digital", "broadcast"),
    "tv-thing-analog": ("TV-Thing Analog", "tv_thing:analog", "unavailable"),
    "youtube-tv": ("YouTube TV", "roku:primary", "unavailable"),
    "mlb": ("Baseball", "roku:primary", "games"),
    "sunday-ticket": ("NFL Sunday Ticket", "roku:primary", "games"),
    "thursday-night-football": ("Thursday Night Football", "roku:primary", "games"),
    "library": ("Media Library", "library:files", "library"),
}


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def normalize_events(channel_id: str, events: object, now: float) -> list[dict]:
    result = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        start, duration = event.get("start"), event.get("duration")
        if not _number(start) or not _number(duration) or duration <= 0:
            continue
        end = start + duration
        if not math.isfinite(end) or end <= now:
            continue
        event_id = event.get("event_id")
        result.append({"id": f"tv-thing-digital:{channel_id}:{event_id}:{start}",
                       "event_id": event_id, "title": str(event.get("title") or "Untitled program"),
                       "start": start, "end": end, "end_kind": "scheduled",
                       "state": "current" if start <= now < end else "upcoming"})
    return sorted(result, key=lambda item: (item["start"], item["id"]))


class SourceCatalog:
    def __init__(self, config: AppConfig, baseball=None, *, tv: TvThingClient | None = None,
                 clock: Callable = time.time, sports=None, library=None):
        self.config = config
        self.library = library
        self.baseball = baseball
        self.sports = sports
        self.tv = tv or TvThingClient(config.tv_thing)
        self.clock = clock

    def list(self) -> dict:
        sources = []
        for source_id, (name, resource, guide) in SOURCE_INFO.items():
            configured = (self.config.tv_thing.enabled if source_id.startswith("tv-thing") else
                          bool(self.library and self.library.config.enabled) if source_id == "library" else True)
            sources.append({"id": source_id, "name": name, "resource_id": resource,
                            "configured": configured, "availability": "unknown" if configured else "disabled",
                            "guide_kind": guide, "selection": None,
                            "capabilities": {"browse": configured, "master_take": False,
                                             "master_queue": False}})
        warnings = []
        library = next(s for s in sources if s["id"] == "library")
        if library["configured"]:
            listing = self.library.listing()
            available = [r for r in listing["roots"] if r["available"]]
            library["count"] = len(listing["items"])
            library["availability"] = (f"{library['count']} files" if available else "unavailable")
            warnings.extend(f"{r['name']}: {r['error']}" for r in listing["roots"] if r["error"])
        if self.config.tv_thing.enabled:
            # Neither read opens a capture device or modifies a tuner.
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {key: pool.submit(self.tv.get, key) for key in ("sources", "status")}
                responses = {}
                for key, future in futures.items():
                    try:
                        responses[key] = future.result()
                    except SourceUnavailableError as exc:
                        warnings.append(str(exc))
            discovery, status = responses.get("sources"), responses.get("status")
            for item in sources[:2]:
                lane = "digital" if item["id"] == "tv-thing-digital" else "analog"
                upstream_id = "digital" if lane == "digital" else "cable"
                match = next((s for s in (discovery or {}).get("data", {}).get("sources", [])
                              if isinstance(s, dict) and s.get("id") == upstream_id), {})
                item["availability"] = ("unknown" if not discovery or discovery["stale"] else
                                        "available" if match.get("available") is True else "unavailable")
                item["stale"] = any(r["stale"] for r in responses.values())
                if status and not status["stale"]:
                    state = status["data"]["lanes"].get(lane, {})
                    if isinstance(state, dict):
                        item["selection"] = state.get("selection")
                        stream = state.get("stream")
                        item["stream_state"] = stream.get("state") if isinstance(stream, dict) else None
                item["count"] = match.get("count")
            warnings.extend(r["error"] for r in responses.values() if r["error"])
        return {"sources": sources, "warnings": warnings,
                "master": {"state": "not_configured", "can_take": False,
                           "message": "Master switching is not connected. Browse sources; use the existing Cue Sheet for Roku control."}}

    def programs(self, source_id: str, requested_date: str | None = None) -> dict:
        if source_id not in SOURCE_INFO:
            raise ChannelNotFoundError("Unknown source", details={"sources": list(SOURCE_INFO)})
        if source_id == "youtube-tv":
            return {"source_id": source_id, "guide": {"available": False, "reason": "No program guide configured"},
                    "channels": [{"id": c.name, "number": None, "name": c.name, "now": None,
                                  "upcoming": []} for c in self.config.channels], "stale": False}
        if source_id == "mlb":
            return self._baseball(requested_date)
        if source_id == "sunday-ticket":
            return self._sunday_ticket(requested_date)
        if source_id == "thursday-night-football":
            return self._sunday_ticket(requested_date, source_id=source_id)
        if source_id == "library":
            if not self.library or not self.library.config.enabled:
                raise SourceUnavailableError("The media library is not configured")
            return self.library.listing()
        return self._television(source_id)

    def _television(self, source_id: str) -> dict:
        digital = source_id == "tv-thing-digital"
        catalog = self.tv.get("digital" if digital else "analog")
        warnings = [catalog["error"]] if catalog["error"] else []
        guide = None
        if digital:
            try:
                guide = self.tv.get("guide")
                if guide["error"]:
                    warnings.append(guide["error"])
            except SourceUnavailableError as exc:
                warnings.append(str(exc))
        now = self.clock()
        data = guide["data"] if guide else {}
        guide_channels = data.get("channels", {})
        by_id = {c["id"]: c for c in guide_channels.values()
                 if isinstance(c, dict) and isinstance(c.get("id"), str)}
        channels = []
        for item in catalog["data"]["items"]:
            if not isinstance(item, dict):
                continue
            channel_id = item.get("id") if digital else item.get("number")
            if (digital and (not isinstance(channel_id, str) or not channel_id)) or (
                not digital and (isinstance(channel_id, bool) or not isinstance(channel_id, int))
            ):
                continue
            number = str(item.get("number") or "")
            matched = by_id.get(channel_id)
            if matched is None:
                candidate = guide_channels.get(number, {})
                # Never map a guide row whose explicit ID contradicts the catalog.
                if isinstance(candidate, dict) and candidate.get("id") in (None, channel_id):
                    matched = candidate
            events = normalize_events(str(channel_id), (matched or {}).get("events"), now)
            current = next((e for e in events if e["state"] == "current"), None)
            channels.append({"id": channel_id, "number": number,
                             "name": str(item.get("name") or f"Channel {number}"),
                             "now": current, "upcoming": [e for e in events if e["state"] == "upcoming"]})
        generated = data.get("generated_at")
        horizon = data.get("horizon")
        return {"source_id": source_id, "channels": channels, "warnings": warnings,
                "stale": catalog["stale"] or bool(guide and guide["stale"]),
                "fetched_at": catalog["fetched_at"], "guide": {
                    "available": data.get("available") is True,
                    "generated_at": generated,
                    "age_seconds": max(0, now - generated) if _number(generated) else None,
                    "coverage_hours": max(0, horizon - now) / 3600 if _number(horizon) else None,
                    "stale": bool(guide and guide["stale"]),
                    "reason": None if data.get("available") is True else "Program listings unavailable"}}

    def _sunday_ticket(self, requested_date: str | None, *, source_id="sunday-ticket") -> dict:
        """NFL games of the day; each is found in YouTube TV's guide by its title."""
        if self.sports is None:
            raise SourceUnavailableError("Sports schedules are not configured")
        catalog = self.sports.games("nfl", requested_date)
        channels = []
        for game in catalog["games"]:
            if source_id == 'thursday-night-football' and not game.get('prime_video_target'):
                continue
            if source_id == 'sunday-ticket' and game.get('on_sunday_ticket') is False:
                continue  # a national exclusive: Sunday Ticket does not carry it
            try:
                start = datetime.fromisoformat(str(game["start_time"]).replace("Z", "+00:00")).timestamp()
            except (KeyError, ValueError):
                continue
            state = {"pre": "preview", "in": "live", "post": "final"}.get(game["state"], game["state"])
            program = {"id": f"nfl:{game['game_id']}", "title": game["title"], "start": start, "end": None,
                       "end_kind": "game_status", "state": state, "status": game["status"],
                       "networks": game["channels"], "note": game["note"]}
            channels.append({"id": str(game["game_id"]), "name": game["title"], "number": None,
                             "now": program if state == "live" else None,
                             "upcoming": [program] if state == "preview" else [], "game": program})
        return {"source_id": source_id, "date": catalog["date"], "channels": channels,
                "guide": {"available": True, "kind": "games"}, "stale": False}

    def _baseball(self, requested_date: str | None) -> dict:
        if self.baseball is None:
            raise SourceUnavailableError("Baseball schedule is not configured")
        catalog = self.baseball.games(requested_date)
        channels = []
        for game in catalog["games"]:
            try:
                start = datetime.fromisoformat(str(game.get("start_time")).replace("Z", "+00:00"))
                if start.tzinfo is None:
                    continue
                start = start.astimezone(timezone.utc).timestamp()
            except (ValueError, OverflowError):
                continue
            state = str(game.get("state") or "").lower()
            program = {"id": f"mlb:{game['game_pk']}", "title": game["title"], "start": start,
                       "end": None, "end_kind": "game_status", "state": state,
                       "status": game.get("status"), "game_pk": game["game_pk"],
                       "sources": game.get("sources", []), "preferred_source": game.get("preferred_source")}
            channels.append({"id": str(game["game_pk"]), "name": game["title"], "number": None,
                             "now": program if state == "live" else None,
                             "upcoming": [program] if state == "preview" else [],
                             "game": program})
        return {"source_id": "mlb", "date": catalog["date"], "channels": channels,
                "guide": {"available": True, "kind": "games"}, "stale": False}
