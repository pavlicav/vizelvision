class RokuStreamError(Exception):
    """Base error with a stable API-facing error code."""

    code = "roku_stream_error"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class ConfigError(RokuStreamError):
    code = "invalid_config"


class EcpError(RokuStreamError):
    code = "roku_ecp_error"


class RokuNotReadyError(RokuStreamError):
    code = "roku_not_ready"


class ChannelNotFoundError(RokuStreamError):
    code = "channel_not_found"


class NavigationError(RokuStreamError):
    code = "navigation_failed"


class ControlBusyError(RokuStreamError):
    code = "control_busy"


class CueCancelledError(RokuStreamError):
    code = "cue_cancelled"


class BaseballScheduleError(RokuStreamError):
    code = "baseball_schedule_error"
