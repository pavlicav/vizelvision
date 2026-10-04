from __future__ import annotations

from enum import StrEnum


class AppState(StrEnum):
    """Surfaces the Roku controller can safely act from."""

    ROKU_HOME = "roku_home"
    YOUTUBE_TV_USER_SELECT = "youtube_tv_user_select"
    YOUTUBE_TV_HOME = "youtube_tv_home"
    YOUTUBE_TV_LOCATION_VERIFICATION = "youtube_tv_location_verification"
    LIVE_GUIDE = "live_guide"
    FULL_PROGRAM = "full_program"
    CHANNEL_DESCRIPTION = "channel_description"
    JOIN_LIVE_OR_START_FROM_BEGINNING = "join_live_or_start_from_beginning"
    MLB_HOME = "mlb_home"
    MLB_GAMES_LOADING = "mlb_games_loading"
    MLB_GAMES_GRID = "mlb_games_grid"
    MLB_FEED_PICKER = "mlb_feed_picker"
    MLB_ENTITLEMENT_REQUIRED = "mlb_entitlement_required"
    MLB_ERROR = "mlb_error"
    MLB_BROADCAST_ENDED = "mlb_broadcast_ended"
    UNKNOWN = "unknown"
