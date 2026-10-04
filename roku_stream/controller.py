from __future__ import annotations

import threading
import time
import uuid
from copy import deepcopy
from contextlib import contextmanager, nullcontext
from datetime import date, datetime, timezone
from typing import Callable

from .baseball import team_ocr_names
from .config import AppConfig, ChannelConfig, normalize_channel_name
from .ecp import EcpClient, RokuApp, discover_roku
from .errors import ControlBusyError, CueCancelledError, EcpError, NavigationError, RokuNotReadyError
from .feedback import PpmFrame, TvThingFeedback, VisualFeedback
from .direct_capture import DirectCaptureFeedback
from .states import AppState
from .operations import EventLog, OperationStore


class RokuStreamController:
    def __init__(
        self,
        config: AppConfig,
        *,
        ecp: EcpClient | None = None,
        feedback: VisualFeedback | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._sleeper = sleeper
        self._cancel = threading.Event()
        self.navigation_guard = nullcontext
        self._lock = threading.Lock()
        self._operation_lock = threading.Lock()
        self._on_air_lock = threading.Lock()
        self._on_air: dict[str, object] | None = None
        self._operations = OperationStore(config.state_file.parent / "operations")
        self._operation: dict[str, object] = {
            "active": False,
            "phase": "idle",
            "app_state": None,
            "channel": None,
            "provider": None,
            "game_pk": None,
            "game": None,
            "message": "No channel cue is running",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if ecp is None:
            roku_url = config.roku.url
            if roku_url is None:
                found = discover_roku(
                    bind_address=config.roku.discovery_address,
                    timeout=config.roku.request_timeout_seconds,
                )
                if len(found) != 1:
                    raise RokuNotReadyError(
                        "Roku discovery must find exactly one device; set roku.url explicitly",
                        details={"discovered": found},
                    )
                roku_url = found[0]
            ecp = EcpClient(
                roku_url,
                timeout=config.roku.request_timeout_seconds,
                sleeper=sleeper,
                launch_timeout=config.roku.launch_timeout_seconds,
                poll_interval=config.roku.poll_interval_seconds,
            )
        self.ecp = ecp
        if feedback is not None:
            self.feedback = feedback
        elif config.feedback.backend == "direct":
            self.feedback = DirectCaptureFeedback(config.feedback)
            self.feedback.preview_allowed = lambda: not self.operation_status().get("active")
        elif config.feedback.base_url:
            self.feedback = TvThingFeedback(config.feedback, selection_path=config.state_file.with_name("roku-source.json"))
        else:
            self.feedback = None
        if isinstance(self.ecp, EcpClient):
            self.ecp._sleep = self._sleep
        if isinstance(self.feedback, VisualFeedback):
            self.feedback.wait = self._sleep

    def _publish_operation(self, **updates: object) -> None:
        with self._operation_lock:
            self._operation.update(updates)
            self._operation["updated_at"] = datetime.now(timezone.utc).isoformat()
            if self._operation.get("id"):
                self._operations.save(self._operation)

    def operation_status(self) -> dict[str, object]:
        """Return cue progress without waiting for the Roku control lock."""
        with self._operation_lock:
            return deepcopy({key: value for key, value in self._operation.items() if key != "result"})

    def get_operation(self, operation_id: str) -> dict[str, object] | None:
        return self._operations.get(operation_id)

    def recover_operations(self) -> None:
        with self._operation_lock:
            self._operations.recover_interrupted(self._operation.get("id"))

    def _begin_channel_operation(self, channel: str, *, provider: str = "youtube_tv", game: dict | None = None) -> str:
        operation_id = uuid.uuid4().hex
        with self._operation_lock:
            self._operation = {"id": operation_id, "active": True, "channel": channel,
                               "provider": provider, "game": game.get("title") if game else None,
                               "game_pk": game.get("game_pk") if game else None,
                               "phase": "accepted", "app_state": None,
                               "message": f"Accepted cue for {channel}", "error": None,
                               "started_at": datetime.now(timezone.utc).isoformat(), "completed_at": None}
        self._publish_operation()
        self._operations.prune()
        return operation_id

    def submit_play(self, requested_channel: str) -> dict[str, object]:
        _, channel = self.config.resolve_channel(requested_channel)
        return self._submit_cue(channel.name, "youtube_tv", None,
                                lambda operation_id: self.play(channel.name, _reserved=True, _operation_id=operation_id))

    def submit_baseball_game(self, game: dict[str, object]) -> dict[str, object]:
        source = game.get("preferred_source")
        if not isinstance(source, dict) or source.get("provider") not in ("youtube_tv", "mlb"):
            raise NavigationError("No controllable stream is listed for this game")
        if source["provider"] == "youtube_tv":
            self.config.resolve_channel(str(source.get("channel") or ""))
        return self._submit_cue(str(game.get("title")), str(source["provider"]), game,
                                lambda operation_id: self.play_baseball_game(game, source, _reserved=True, _operation_id=operation_id))

    def _submit_cue(self, title: str, provider: str, game: dict | None,
                    action: Callable[[str], object]) -> dict[str, object]:
        # Reserve before acknowledging. A concurrent cue cannot slip in
        # before the worker starts, and cancellation survives that handoff.
        if not self._lock.acquire(blocking=False):
            raise ControlBusyError("The Roku is busy; wait for the current operation or stop it first")
        self._cancel.clear()
        try:
            operation_id = self._begin_channel_operation(title, provider=provider, game=game)
            accepted = self.operation_status()
            def run() -> None:
                try:
                    action(operation_id)
                except Exception:
                    # play persists the exception and releases the reservation.
                    pass
            threading.Thread(target=run, name=f"cue-{operation_id}", daemon=True).start()
            return accepted
        except Exception as exc:
            try:
                self._publish_operation(active=False, phase="error", message=f"Could not start cue: {exc}",
                                        completed_at=datetime.now(timezone.utc).isoformat(),
                                        error={"type": type(exc).__name__, "message": str(exc)})
            finally:
                self._lock.release()
            raise

    def _sleep(self, seconds: float) -> None:
        # Bound cancellation latency without interrupting an in-flight ECP key.
        remaining = seconds
        while remaining > 0:
            if self._cancel.is_set():
                raise CueCancelledError("Cue stopped by the operator")
            step = min(remaining, 0.25)
            self._sleeper(step)
            remaining -= step
        if self._cancel.is_set():
            raise CueCancelledError("Cue stopped by the operator")

    @contextmanager
    def _cue_control(self, *, reserved: bool = False):
        if not reserved and not self._lock.acquire(blocking=False):
            raise ControlBusyError("The Roku is busy; wait for the current operation or stop it first")
        if not reserved:
            self._cancel.clear()
        try:
            with self.navigation_guard():
                yield
        except Exception as exc:
            # An asynchronous cue reserves its operation before entering the
            # guard. Record admission failures as terminal too.
            if reserved and self.operation_status().get('active'):
                self._publish_operation(active=False, phase='error', message=str(exc),
                                        error={'message': str(exc), 'code': getattr(exc, 'code', 'navigation_failed')},
                                        completed_at=datetime.now(timezone.utc).isoformat())
            raise
        finally:
            self._cancel.clear()
            self._lock.release()

    def cancel_operation(self, expected_id: str | None = None) -> dict[str, object]:
        with self._operation_lock:
            if expected_id is not None and self._operation.get("id") != expected_id:
                raise ControlBusyError("That cue is no longer the current operation")
            if self._operation.get("active"):
                self._cancel.set()
                self._operation.update(phase="stopping", message="Stopping after the current device request")
                self._operation["updated_at"] = datetime.now(timezone.utc).isoformat()
                if self._operation.get("id"):
                    self._operations.save(self._operation)
            return deepcopy({key: value for key, value in self._operation.items() if key != "result"})

    def on_air_source(self) -> dict[str, object] | None:
        """Return the last source whose playback completed all verification."""
        with self._on_air_lock:
            return dict(self._on_air) if self._on_air is not None else None

    def _set_on_air(self, source: dict[str, object]) -> None:
        with self._on_air_lock:
            self._on_air = {
                **source,
                "confirmed_at": datetime.now(timezone.utc).isoformat(),
            }

    @staticmethod
    def _state_progress_message(state: AppState) -> str:
        return {
            AppState.ROKU_HOME: "Roku Home detected; launching YouTube TV",
            AppState.YOUTUBE_TV_USER_SELECT: "YouTube TV profile chooser detected",
            AppState.YOUTUBE_TV_HOME: "YouTube TV Home detected; opening Live",
            AppState.YOUTUBE_TV_LOCATION_VERIFICATION: "YouTube TV location verification detected",
            AppState.LIVE_GUIDE: "Live guide detected",
            AppState.FULL_PROGRAM: "Fullscreen program detected; returning to the guide",
            AppState.CHANNEL_DESCRIPTION: "Channel description detected; returning to the guide",
            AppState.JOIN_LIVE_OR_START_FROM_BEGINNING: "Join live chooser detected",
            AppState.MLB_HOME: "MLB Home detected",
            AppState.MLB_GAMES_LOADING: "MLB game grid is loading",
            AppState.MLB_GAMES_GRID: "MLB game grid detected",
            AppState.MLB_FEED_PICKER: "MLB broadcast picker detected",
            AppState.MLB_ENTITLEMENT_REQUIRED: "MLB entitlement is required",
            AppState.MLB_ERROR: "MLB reported an error",
            AppState.MLB_BROADCAST_ENDED: "MLB broadcast has ended",
            AppState.UNKNOWN: "Screen is not recognized yet; observing again",
        }[state]

    def _app_id(self) -> str:
        installed = self.ecp.apps()
        configured_id = self.config.roku.app_id
        if configured_id:
            match = next((app for app in installed if app.id == configured_id), None)
            if match is None:
                raise RokuNotReadyError(
                    f"Configured YouTube TV app ID {configured_id} is not installed"
                )
            return configured_id
        expected = self.config.roku.app_name.casefold()
        matches = [app for app in installed if app.name.casefold() == expected]
        if len(matches) != 1 or not matches[0].id:
            raise RokuNotReadyError(
                f"Could not uniquely find installed Roku app {self.config.roku.app_name!r}",
                details={"matches": [app.__dict__ for app in matches]},
            )
        return matches[0].id

    def _mlb_app_id(self) -> str:
        installed = self.ecp.apps()
        configured_id = self.config.mlb.app_id
        if configured_id:
            match = next((app for app in installed if app.id == configured_id), None)
            if match is None:
                raise RokuNotReadyError(
                    f"Configured MLB app ID {configured_id} is not installed"
                )
            return configured_id
        expected = self.config.mlb.app_name.casefold()
        matches = [app for app in installed if app.name.casefold() == expected]
        if len(matches) != 1 or not matches[0].id:
            raise RokuNotReadyError(
                f"Could not uniquely find installed Roku app {self.config.mlb.app_name!r}",
                details={"matches": [app.__dict__ for app in matches]},
            )
        return matches[0].id

    def _assert_ready(self) -> tuple[str, dict[str, str]]:
        info = self.ecp.device_info()
        if info.get("ecp-setting-mode", "").casefold() != "enabled":
            raise RokuNotReadyError(
                "Roku Control by mobile apps must be set to Enabled",
                details={"ecp_setting_mode": info.get("ecp-setting-mode")},
            )
        app_id = self._app_id()
        if self.feedback:
            self.feedback.assert_ready()
        return app_id, info

    def plan(self, requested_channel: str) -> dict[str, object]:
        _, channel = self.config.resolve_channel(requested_channel)
        approximate_downs = max(
            0,
            channel.guide_index
            - self.config.navigation.guide_scan_lookbehind,
        )
        keys = [
            *self.config.navigation.open_live_guide_keys,
            *(["Down"] * approximate_downs),
        ]
        template_path = None
        network_template_path = None
        if self.feedback:
            template_path = str(
                self.feedback.template_path(channel.name, channel.template)
            )
            network_template_path = str(
                self.feedback.network_template_path(
                    channel.network_page or channel.name
                )
            )
        return {
            "channel": channel.name,
            "network_page": channel.network_page or channel.name,
            "guide_index": channel.guide_index,
            "approximate_downs": approximate_downs,
            "normalization": "detect current Roku/YouTube TV state and transition to live guide",
            "keys_from_youtube_tv_home": keys,
            "positioning": "relative to identified row, or absolute top anchor",
            "then": "verified row scan, two fresh row/focus checks or network-page fallback, Select",
            "visual_verification": bool(self.feedback),
            "template_path": template_path,
            "network_template_path": network_template_path,
        }

    def _observe_state(self, app_id: str) -> dict[str, object]:
        """Observe one actionable Roku/YouTube TV state without sending keys."""
        active = self.ecp.active_app()
        if active.id != app_id:
            return {
                "state": AppState.ROKU_HOME,
                "evidence": "active_app_is_not_youtube_tv",
                "active_app": active.__dict__,
            }

        player = self.ecp.media_player()
        if self.feedback is None:
            player_state = str(player.get("state", "")).casefold()
            state = (
                AppState.FULL_PROGRAM
                if player_state not in ("", "none", "close", "stop", "stopped")
                else AppState.UNKNOWN
            )
            return {
                "state": state,
                "evidence": "roku_media_player_only",
                "active_app": active.__dict__,
                "media_player": player,
            }

        frame = self.feedback.capture()
        observation = self.feedback.detect_youtube_tv_state(
            frame, self.config.channels, player
        )
        return {
            **observation,
            "active_app": active.__dict__,
            "media_player": player,
        }

    def current_state(self) -> dict[str, object]:
        """Return the state the next play request would act from."""
        operation = self.operation_status()
        if operation.get("active"):
            return {"ok": True, "state": operation.get("app_state") or AppState.UNKNOWN, "evidence": "active_operation", "operation": operation}
        with self._lock:
            app_id, _ = self._assert_ready()
            active = self.ecp.active_app()
            try:
                mlb_app_id = self._mlb_app_id()
            except RokuNotReadyError:
                mlb_app_id = None
            if active.id == mlb_app_id and self.feedback is not None:
                frame = self.feedback.capture()
                return {
                    "ok": True,
                    **self.feedback.detect_mlb_state(
                        frame, self.ecp.media_player(), mlb_app_id
                    ),
                    "active_app": active.__dict__,
                }
            return {"ok": True, **self._observe_state(app_id)}

    def feedback_sources(self) -> dict[str, object]:
        """List capture inputs that can carry the Roku return feed."""
        if self.feedback is None:
            raise NavigationError("Visual feedback is not configured")
        return self.feedback.source_catalog()

    def select_feedback_source(self, key: str) -> dict[str, object]:
        """Switch the Roku return feed without racing an active cue."""
        if self.feedback is None:
            raise NavigationError("Visual feedback is not configured")
        if not self._lock.acquire(blocking=False):
            raise ControlBusyError(
                "Cannot change the Roku source while a cue or state check is running"
            )
        try:
            return self.feedback.select_source(key)
        finally:
            self._lock.release()

    def _drive_to_live_guide(
        self, app_id: str, events: list[dict[str, object]]
    ) -> dict[str, object]:
        """Advance from the current observed state to a verified live guide."""
        nav = self.config.navigation
        roku = self.config.roku
        unknown_attempts = 0
        unverified_profiles = 0
        prior_state: AppState | None = None
        repeated_state = 0
        live_entry_started = False

        for transition in range(1, 21):
            observation = self._observe_state(app_id)
            state = AppState(str(observation["state"]))
            self._publish_operation(
                phase="observing_state",
                app_state=state,
                message=self._state_progress_message(state),
            )
            repeated_state = repeated_state + 1 if state == prior_state else 1
            prior_state = state
            events.append(
                {
                    "event": "state_detected",
                    "transition": transition,
                    "state": state,
                    "observation": observation,
                }
            )

            if state == AppState.LIVE_GUIDE:
                if observation.get('evidence') == 'ocr_guide_time_grid' and observation.get('focus') is None:
                    # The sort toolbar and promotional shelf expose guide
                    # times, but neither is a selected station/program row.
                    self.ecp.keypress('Down')
                    events.append({'event': 'keypress', 'key': 'Down', 'action': 'enter_guide_rows'})
                    self._sleep(nav.guide_settle_seconds)
                    continue
                return observation

            if state == AppState.ROKU_HOME:
                self.ecp.launch(app_id)
                self._publish_operation(
                    phase="launching_youtube_tv",
                    message="Launching YouTube TV from Roku Home",
                )
                events.append(
                    {
                        "event": "state_action",
                        "from": state,
                        "action": "launch_youtube_tv",
                    }
                )
                self.ecp.wait_for_active_app(
                    app_id,
                    timeout=roku.launch_timeout_seconds,
                    interval=roku.poll_interval_seconds,
                )
                self._sleep(nav.launch_settle_seconds)
                unknown_attempts = 0
                continue

            if state == AppState.YOUTUBE_TV_USER_SELECT:
                unverified_profiles = (unverified_profiles + 1
                                       if observation.get("profile_verified") is not True else 0)
                if unverified_profiles > 3:
                    raise NavigationError(
                        "YouTube TV's profile chooser does not show a recognizable focused Vivian "
                        "profile. If the profile photo changed, recalibrate with calibrate-profile.",
                        details={"profile_verification": observation.get("verification")},
                    )
                if observation.get("profile_verified") is not True:
                    # Anchor the chooser on its far-left profile, then require
                    # the calibrated Vivian template on the next observation.
                    self.ecp.keypress("Left")
                    action = "focus_leftmost_profile"
                else:
                    self.ecp.keypress("Select")
                    action = "select_vivian"
                self._publish_operation(
                    phase="selecting_profile",
                    message=(
                        "Focusing the far-left Vivian profile"
                        if action == "focus_leftmost_profile"
                        else "Selecting the verified Vivian profile"
                    ),
                )
                events.append(
                    {
                        "event": "state_action",
                        "from": state,
                        "action": action,
                    }
                )
                self._sleep(nav.launch_settle_seconds)
                unknown_attempts = 0
                continue

            if state == AppState.YOUTUBE_TV_HOME:
                self._publish_operation(
                    phase="opening_live_guide",
                    message="Opening the YouTube TV Live guide",
                )
                evidence = observation.get('evidence')
                if observation.get('navigation_tab') == 'resume':
                    keys = ('Down',)
                    live_entry_started = False
                elif evidence == 'ocr_home_recommendations':
                    # Recommendation cards are below the navigation. Moving
                    # Right/Select here opens a card, not the Live tab.
                    keys = ('Up',)
                    live_entry_started = False
                elif evidence == 'ocr_top_navigation' and not live_entry_started:
                    keys = ('Up',)  # Confirm a focused tab before selecting Live.
                elif live_entry_started and evidence == 'ocr_top_navigation':
                    # The Live landing page may insert a promotional shelf
                    # before the grid. Observe it and advance one shelf only.
                    keys = ('Down',)
                else:
                    keys = ('Down', 'Down') if observation.get('navigation_tab') == 'live' else nav.open_live_guide_keys
                    live_entry_started = True
                for key in keys:
                    self.ecp.keypress(key)
                    events.append(
                        {
                            "event": "keypress",
                            "key": key,
                            "action": "open_live_guide",
                        }
                    )
                    self._sleep(
                        nav.guide_settle_seconds
                        if key == "Select"
                        else nav.key_delay_seconds
                    )
                self._sleep(nav.guide_settle_seconds)
                unknown_attempts = 0
                continue

            if state == AppState.YOUTUBE_TV_LOCATION_VERIFICATION:
                selection = observation.get("selection")
                verification_selected = (
                    isinstance(selection, dict)
                    and selection.get("selected") == "verification"
                )
                key = "Select" if verification_selected else "Left"
                action = (
                    "confirm_location_verification"
                    if verification_selected
                    else "focus_location_verification"
                )
                self.ecp.keypress(key)
                self._publish_operation(
                    phase="verifying_location",
                    message=(
                        "Confirming YouTube TV location verification"
                        if verification_selected
                        else "Focusing YouTube TV's Verification button"
                    ),
                )
                events.append(
                    {
                        "event": "state_action",
                        "from": state,
                        "action": action,
                        "key": key,
                    }
                )
                self._sleep(nav.launch_settle_seconds)
                unknown_attempts = 0
                continue

            if state in (AppState.FULL_PROGRAM, AppState.CHANNEL_DESCRIPTION):
                if (
                    state == AppState.CHANNEL_DESCRIPTION
                    and repeated_state < 2
                ):
                    events.append(
                        {
                            "event": "state_confirmation_wait",
                            "state": state,
                            "reason": "channel_description_requires_two_observations",
                        }
                    )
                    self._sleep(roku.poll_interval_seconds)
                    continue
                self.ecp.keypress("Back")
                self._publish_operation(
                    phase="returning_to_guide",
                    message="Returning from the current screen to the Live guide",
                )
                events.append(
                    {
                        "event": "state_action",
                        "from": state,
                        "action": "back_to_live_guide",
                    }
                )
                self._sleep(nav.guide_settle_seconds)
                unknown_attempts = 0
                continue

            if state == AppState.JOIN_LIVE_OR_START_FROM_BEGINNING:
                self.ecp.keypress("Select")
                self._publish_operation(
                    phase="joining_live",
                    message="Join live is selected; confirming it",
                )
                events.append(
                    {
                        "event": "state_action",
                        "from": state,
                        "action": "join_live",
                    }
                )
                self._sleep(nav.play_settle_seconds)
                unknown_attempts = 0
                continue

            unknown_attempts += 1
            if unknown_attempts < self.config.feedback.verify_attempts:
                self._sleep(roku.poll_interval_seconds)
                continue

            # Unknown may be a transient launch frame. Only after repeated
            # observations do we use Roku Home as a deterministic safe anchor.
            self.ecp.keypress("Home")
            self._publish_operation(
                phase="recovering",
                message="Screen stayed unknown; recovering through Roku Home",
            )
            events.append(
                {
                    "event": "state_action",
                    "from": state,
                    "action": "recover_to_roku_home",
                    "attempts": unknown_attempts,
                }
            )
            self._sleep(nav.post_exit_settle_seconds)
            unknown_attempts = 0

        raise NavigationError(
            "Could not reach the YouTube TV live guide from the current state",
            details={"state_transitions": list(events)},
        )

    def _wait_for_playback(
        self, app_id: str, events: list[dict[str, object]]
    ) -> dict[str, object]:
        """Wait for playback, accepting a verified Join live prompt if shown."""
        roku = self.config.roku
        deadline = time.monotonic() + roku.playback_timeout_seconds
        last_player: dict[str, object] = {}
        last_observation: dict[str, object] | None = None
        location_confirmations = 0

        while time.monotonic() < deadline:
            active = self.ecp.active_app()
            if active.id != app_id:
                raise EcpError("YouTube TV stopped being the active Roku app")
            last_player = self.ecp.media_player()
            plugin = last_player.get("plugin")
            plugin_id = plugin.get("id") if isinstance(plugin, dict) else None
            if last_player.get("error") == "true":
                raise EcpError(
                    "Roku media player reported an error", details=last_player
                )

            if self.feedback is not None:
                frame = self.feedback.capture()
                last_observation = self.feedback.detect_youtube_tv_state(
                    frame, self.config.channels, last_player
                )
                state = AppState(str(last_observation["state"]))
                self._publish_operation(
                    phase="waiting_for_playback",
                    app_state=state,
                    message=f"Waiting for Roku playback (player: {last_player.get('state', 'unknown')})",
                )
                events.append(
                    {
                        "event": "playback_state_detected",
                        "state": state,
                        "observation": last_observation,
                    }
                )
                if state == AppState.JOIN_LIVE_OR_START_FROM_BEGINNING:
                    self.ecp.keypress("Select")
                    self._publish_operation(
                        phase="joining_live",
                        message="Join live is selected; confirming it",
                    )
                    events.append(
                        {
                            "event": "state_action",
                            "from": state,
                            "action": "join_live",
                        }
                    )
                    self._sleep(self.config.navigation.play_settle_seconds)
                    continue
                if state == AppState.YOUTUBE_TV_LOCATION_VERIFICATION:
                    selection = last_observation.get("selection")
                    verification_selected = (
                        isinstance(selection, dict)
                        and selection.get("selected") == "verification"
                    )
                    key = "Select" if verification_selected else "Left"
                    action = (
                        "confirm_location_verification"
                        if verification_selected
                        else "focus_location_verification"
                    )
                    self.ecp.keypress(key)
                    self._publish_operation(
                        phase="verifying_location",
                        app_state=state,
                        message=(
                            "Confirming YouTube TV location verification"
                            if verification_selected
                            else "Focusing YouTube TV's Verification button"
                        ),
                    )
                    events.append(
                        {
                            "event": "state_action",
                            "from": state,
                            "action": action,
                            "key": key,
                        }
                    )
                    if verification_selected and location_confirmations < 2:
                        location_confirmations += 1
                        deadline = time.monotonic() + roku.playback_timeout_seconds
                    self._sleep(self.config.navigation.launch_settle_seconds)
                    continue
                if (
                    state == AppState.FULL_PROGRAM
                    and last_player.get("state") == "play"
                    and plugin_id == app_id
                ):
                    self._publish_operation(
                        phase="playback_confirmed",
                        app_state=AppState.FULL_PROGRAM,
                        message="Roku reports playback after the verified selection",
                    )
                    return last_player
            elif last_player.get("state") == "play" and plugin_id == app_id:
                return last_player
            self._sleep(roku.poll_interval_seconds)

        raise EcpError(
            "Timed out waiting for YouTube TV playback",
            details={
                "media_player": last_player,
                "last_observation": last_observation,
            },
        )

    def _clean_launch(self, app_id: str, events: list[dict[str, object]]) -> None:
        nav = self.config.navigation
        roku = self.config.roku
        initially_active = self.ecp.active_app().id == app_id

        def wait_for_start_screen(*, home_only: bool = False) -> tuple[str, dict[str, object]]:
            if not self.feedback:
                self._sleep(nav.launch_settle_seconds)
                active = self.ecp.active_app()
                if active.id != app_id:
                    raise NavigationError(
                        "YouTube TV did not remain active during launch",
                        details={"active_app": active.__dict__},
                    )
                return "unverified", {}
            deadline = time.monotonic() + roku.launch_timeout_seconds
            last_details: dict[str, object] = {}
            while time.monotonic() < deadline:
                active = self.ecp.active_app()
                if active.id != app_id:
                    raise NavigationError(
                        "YouTube TV stopped before its UI became ready",
                        details={"active_app": active.__dict__},
                    )
                frame = self.feedback.capture()
                try:
                    home = self.feedback.assert_home_tab(frame)
                except NavigationError as exc:
                    last_details.update(exc.details)
                else:
                    return "home", home
                if not home_only:
                    try:
                        profile = self.feedback.verify_vivian_profile(frame)
                    except NavigationError as exc:
                        last_details.update(exc.details)
                    else:
                        return "profile", profile
                self._sleep(roku.poll_interval_seconds)
            expected = "Home" if home_only else "Home or the Vivian profile chooser"
            raise NavigationError(
                f"Timed out waiting for YouTube TV {expected} to become visible",
                details=last_details,
            )

        def launch_and_wait() -> tuple[str, dict[str, object]]:
            self.ecp.launch(app_id)
            self.ecp.wait_for_active_app(
                app_id,
                timeout=roku.launch_timeout_seconds,
                interval=roku.poll_interval_seconds,
            )
            return wait_for_start_screen()

        if not initially_active:
            state, verification = launch_and_wait()
            events.append(
                {"event": "launch_screen_verification", "state": state, "result": verification}
            )
        else:
            state = "unknown"
            verification: dict[str, object] = {}
            initial_exit_dialog: dict[str, object] | None = None
            if self.feedback:
                frame = self.feedback.capture()
                try:
                    verification = self.feedback.assert_home_tab(frame)
                    state = "home"
                except NavigationError:
                    try:
                        verification = self.feedback.verify_vivian_profile(frame)
                        state = "profile"
                    except NavigationError:
                        try:
                            initial_exit_dialog = self.feedback.assert_exit_dialog(frame)
                        except NavigationError:
                            pass

            if state == "unknown":
                exited = False
                if initial_exit_dialog is not None:
                    events.append(
                        {
                            "event": "exit_dialog_verification",
                            "result": initial_exit_dialog,
                            "initial": True,
                        }
                    )
                    self.ecp.keypress("Select")
                    events.append(
                        {"event": "keypress", "key": "Select", "action": "confirm_exit"}
                    )
                    deadline = time.monotonic() + roku.launch_timeout_seconds
                    while time.monotonic() < deadline:
                        active = self.ecp.active_app()
                        if active.id != app_id:
                            exited = True
                            break
                        self._sleep(roku.poll_interval_seconds)
                else:
                    for attempt in range(1, nav.reset_back_presses + 1):
                        self.ecp.keypress("Back")
                        self._sleep(nav.reset_key_delay_seconds)
                        active = self.ecp.active_app()
                        events.append(
                            {
                                "event": "reset_back",
                                "attempt": attempt,
                                "active_app": active.__dict__,
                            }
                        )
                        if active.id != app_id:
                            exited = True
                            break
                        if not self.feedback:
                            continue
                        frame = self.feedback.capture()
                        try:
                            verification = self.feedback.assert_home_tab(frame)
                        except NavigationError:
                            pass
                        else:
                            state = "home"
                            events.append(
                                {
                                    "event": "reset_reached_home",
                                    "attempt": attempt,
                                    "result": verification,
                                }
                            )
                            break
                        try:
                            dialog = self.feedback.assert_exit_dialog(frame)
                        except NavigationError:
                            continue
                        events.append(
                            {"event": "exit_dialog_verification", "result": dialog}
                        )
                        self.ecp.keypress("Select")
                        deadline = time.monotonic() + roku.launch_timeout_seconds
                        while time.monotonic() < deadline:
                            active = self.ecp.active_app()
                            if active.id != app_id:
                                exited = True
                                break
                            self._sleep(roku.poll_interval_seconds)
                        break
                if state == "home":
                    pass
                elif not exited:
                    raise NavigationError(
                        "Could not exit YouTube TV to establish a known starting state"
                    )
                else:
                    self._sleep(nav.post_exit_settle_seconds)
                    state, verification = launch_and_wait()
            events.append(
                {"event": "launch_screen_verification", "state": state, "result": verification}
            )

        if state == "profile":
            self.ecp.keypress("Select")
            events.append(
                {"event": "keypress", "key": "Select", "action": "select_vivian"}
            )
            state, verification = wait_for_start_screen(home_only=True)
        if state not in ("home", "unverified"):
            raise NavigationError(
                f"Unexpected YouTube TV launch state: {state}",
                details={"verification": verification},
            )
        active = self.ecp.active_app()
        if active.id != app_id:
            raise NavigationError(
                "YouTube TV stopped after reaching the Home screen",
                details={"active_app": active.__dict__},
            )
        events.append(
            {
                "event": "clean_launch",
                "active_app": active.__dict__,
                "home_verification": verification,
            }
        )

    def _focus_network_tile(
        self, events: list[dict[str, object]] | None = None
    ) -> dict[str, object]:
        if not self.feedback:
            raise NavigationError("Visual feedback is not configured")
        last_error: NavigationError | None = None
        # Focus may be several future program cells to the right. Walk left
        # while a program cell is still visibly selected; stop at the first
        # verified station-tile border.
        for attempt in range(1, 9):
            self.ecp.keypress("Left")
            if events is not None:
                events.append(
                    {
                        "event": "keypress",
                        "key": "Left",
                        "action": "seek_network_tile",
                        "attempt": attempt,
                    }
                )
            self._sleep(self.config.navigation.guide_settle_seconds)
            try:
                return self.feedback.assert_network_tile_focus()
            except NavigationError as exc:
                last_error = exc
            # If neither a network-tile border nor a selected program is
            # visible, do not send another blind key.
            try:
                self.feedback.selected_logo()
            except NavigationError:
                assert last_error is not None
                raise last_error
        assert last_error is not None
        raise last_error

    def _focus_current_program(
        self, events: list[dict[str, object]] | None = None
    ) -> dict[str, object]:
        if not self.feedback:
            raise NavigationError("Visual feedback is not configured")
        last_error: NavigationError | None = None
        for attempt in range(1, 10):
            frame = self.feedback.capture()
            try:
                return self.feedback.assert_current_program_focus(frame)
            except NavigationError as exc:
                last_error = exc

            try:
                self.feedback.assert_network_tile_focus(frame)
            except NavigationError:
                try:
                    self.feedback.selected_logo(frame)
                except NavigationError:
                    key = "Down"
                    action = "leave_on_now_for_guide"
                else:
                    key = "Left"
                    action = "seek_current_program"
            else:
                key = "Right"
                action = "leave_network_tile"

            self.ecp.keypress(key)
            if events is not None:
                events.append(
                    {
                        "event": "keypress",
                        "key": key,
                        "action": action,
                        "attempt": attempt,
                    }
                )
            self._sleep(self.config.navigation.guide_settle_seconds)
        assert last_error is not None
        raise last_error

    def _open_channel_row(
        self,
        channel: ChannelConfig,
        events: list[dict[str, object]],
        *,
        guide_observation: dict[str, object] | None = None,
    ) -> dict[str, object] | None:
        nav = self.config.navigation
        if self.feedback and guide_observation and guide_observation.get("focus") == "network_tile":
            self._focus_current_program(events)
            guide_observation = None
            try:
                guide_observation = self.feedback.identify_selected(self.config.channels)
            except NavigationError:
                guide_observation = {"state": AppState.LIVE_GUIDE}
        self._publish_operation(
            phase="positioning_guide",
            app_state=AppState.LIVE_GUIDE,
            message=f"Positioning the Live guide for {channel.name}",
        )
        if guide_observation is None:
            for key in nav.open_live_guide_keys:
                self.ecp.keypress(key)
                events.append({"event": "keypress", "key": key})
                self._sleep(
                    nav.guide_settle_seconds
                    if key == "Select"
                    else nav.key_delay_seconds
                )
            self._sleep(nav.guide_settle_seconds)

        if not self.feedback:
            for position in range(channel.guide_index):
                self.ecp.keypress("Down")
                events.append(
                    {
                        "event": "guide_down",
                        "position": position + 1,
                        "target": channel.guide_index,
                    }
                )
                self._sleep(nav.key_delay_seconds)
            return None

        network_page = channel.network_page or channel.name
        network_template = self.feedback.network_template_path(network_page)
        if not self.config.feedback.network_page_fallback and not network_template.is_file():
            raise NavigationError(
                f"No network page logo template has been calibrated for {channel.name!r}",
                details={"template_path": str(network_template)},
            )

        # The old Roku occasionally acknowledges an ECP key while its UI is
        # still busy and silently drops the action. Confirm that the guide row
        # exists; additional Down presses finish entering the guide if one of
        # the two configured Down keys was lost.
        guide_visible = guide_observation is not None
        guide_error: NavigationError | None = None
        if guide_visible:
            events.append(
                {
                    "event": "guide_visible",
                    "source": "state_detector",
                    "observation": guide_observation,
                }
            )
        for attempt in range(1, self.config.feedback.verify_attempts + 3):
            if guide_visible:
                break
            try:
                self.feedback.selected_logo()
                guide_visible = True
                events.append({"event": "guide_visible", "attempt": attempt})
                break
            except NavigationError as exc:
                guide_error = exc
                events.append(
                    {
                        "event": "guide_visibility_retry",
                        "attempt": attempt,
                        "error": {"message": str(exc), "details": exc.details},
                    }
                )
                self.ecp.keypress("Down")
                events.append(
                    {"event": "keypress", "key": "Down", "action": "enter_guide"}
                )
                self._sleep(nav.guide_settle_seconds)
        if not guide_visible:
            assert guide_error is not None
            raise guide_error

        current_index: int | None = None
        rejected_guide_anchor = False
        if guide_observation is not None:
            observed_index = guide_observation.get("guide_index")
            observed_name = guide_observation.get("channel")
            observed_channel = next(
                (
                    item
                    for item in self.config.channels
                    if item.name == observed_name
                ),
                None,
            )
            if (
                isinstance(observed_index, int)
                and not isinstance(observed_index, bool)
                and (observed_channel is None or observed_channel.anchor_safe)
                and self._reliable_guide_anchor(guide_observation)
            ):
                current_index = observed_index
            elif observed_channel is not None and not observed_channel.anchor_safe:
                rejected_guide_anchor = True
                events.append(
                    {
                        "event": "guide_anchor_rejected",
                        "channel": observed_channel.name,
                        "reason": "guide_logo_is_not_unique",
                    }
                )

        if current_index is None and not rejected_guide_anchor:
            try:
                identified = self.feedback.identify_selected(self.config.channels)
            except NavigationError as exc:
                events.append(
                    {
                        "event": "guide_row_unidentified",
                        "error": {"message": str(exc), "details": exc.details},
                    }
                )
            else:
                identified_channel = next(
                    (
                        item
                        for item in self.config.channels
                        if item.name == identified.get("channel")
                    ),
                    None,
                )
                if (identified_channel is None or identified_channel.anchor_safe) and self._reliable_guide_anchor(identified):
                    current_index = int(identified["guide_index"])
                    events.append(
                        {"event": "guide_row_identified", "result": identified}
                    )
                else:
                    events.append(
                        {
                            "event": "guide_anchor_rejected",
                            "channel": identified.get("channel"),
                            "reason": "guide_logo_is_not_unique_or_confident",
                        }
                    )

        if current_index is None:
            # The selected row may be one of the deliberately unconfigured
            # gaps or one of several affiliates with the same tiny logo. Walk
            # upward until the first uniquely calibrated row is *observed*;
            # a blind burst of Up keys can leave this old Roku too busy to
            # accept the following Down keys.
            anchor_channel = min(
                (item for item in self.config.channels if item.anchor_safe),
                key=lambda item: item.guide_index,
            )
            anchor_attempts = (
                max(item.guide_index for item in self.config.channels)
                + nav.guide_scan_max_rows
                + 2
            )
            self._publish_operation(
                phase="anchoring_guide",
                message=(
                    "Current guide row is ambiguous; finding the first "
                    f"unique row ({anchor_channel.name})"
                ),
            )
            anchor_verification = None
            last_anchor_error: NavigationError | None = None
            recovered_live_tab = False
            for position in range(anchor_attempts + 1):
                try:
                    anchor_verification = self.feedback.verify_selected(
                        anchor_channel.name,
                        configured_path=anchor_channel.template,
                    )
                    if not self._reliable_guide_anchor({"channel": anchor_channel.name, "verification": anchor_verification}):
                        raise NavigationError("Top guide anchor did not meet the required logo confidence")
                except NavigationError as exc:
                    last_anchor_error = exc
                    if isinstance(self.feedback, VisualFeedback) and self.feedback.last_frame is not None:
                        try:
                            self.feedback.assert_live_tab(self.feedback.last_frame)
                        except NavigationError:
                            pass
                        else:
                            if recovered_live_tab:
                                break
                            recovered_live_tab = True
                            self._drive_to_live_guide(self._app_id(), events)
                            events.append({'event': 'guide_anchor_reenter_from_live_tab'})
                            continue
                else:
                    events.append(
                        {
                            "event": "guide_anchor_verified",
                            "channel": anchor_channel.name,
                            "guide_index": anchor_channel.guide_index,
                            "attempt": position + 1,
                            "verification": anchor_verification,
                        }
                    )
                    current_index = anchor_channel.guide_index
                    break
                if position >= anchor_attempts:
                    break
                self.ecp.keypress("Up")
                events.append(
                    {
                        "event": "guide_anchor_up",
                        "position": position + 1,
                        "target": anchor_attempts,
                    }
                )
                self._sleep(nav.key_delay_seconds)
            if current_index is None:
                raise NavigationError(
                    f"Could not establish the {anchor_channel.name!r} top guide anchor",
                    details={
                        "anchor_channel": anchor_channel.name,
                        "attempts": anchor_attempts + 1,
                        "last_error": (
                            {
                                "message": str(last_anchor_error),
                                "details": last_anchor_error.details,
                            }
                            if last_anchor_error is not None
                            else None
                        ),
                    },
                )
            self._sleep(nav.guide_settle_seconds)
            delta = channel.guide_index - current_index
            scan_key = "Down" if delta >= 0 else "Up"
            initial_moves = abs(delta)
            positioning = "top_anchor"
        else:
            delta = channel.guide_index - current_index
            scan_key = "Down" if delta >= 0 else "Up"
            initial_moves = abs(delta)
            positioning = "relative_to_identified_row"

        # Guide positions are estimates: lineup changes can move the target
        # closer as well as farther away. Observe each move so an old offset
        # cannot scroll past the requested channel before verification starts.
        for position in range(initial_moves):
            self.ecp.keypress(scan_key)
            self._publish_operation(
                phase="positioning_guide",
                message=(
                    f"Moving {scan_key.lower()} through the guide for {channel.name} "
                    f"({position + 1}/{initial_moves})"
                ),
            )
            events.append(
                {
                    "event": "guide_position",
                    "key": scan_key,
                    "position": position + 1,
                    "target": initial_moves,
                    "phase": "approximate",
                    "positioning": positioning,
                }
            )
            self._sleep(nav.key_delay_seconds)
            if isinstance(self.feedback, VisualFeedback) and self.config.feedback.fresh_frames:
                try:
                    verification = self.feedback.verify_selected(
                        channel.name, configured_path=channel.template
                    )
                except NavigationError:
                    pass
                else:
                    events.append({
                        "event": "guide_target_observed_during_positioning",
                        "position": position + 1,
                        "expected_moves": initial_moves,
                        "result": verification,
                    })
                    break
        if initial_moves:
            self._sleep(nav.guide_settle_seconds)

        last_error: NavigationError | None = None
        for scan_offset in range(nav.guide_scan_max_rows + 1):
            self._publish_operation(
                phase="verifying_guide_row",
                app_state=AppState.LIVE_GUIDE,
                message=f"Checking the highlighted guide row for {channel.name}",
            )
            guide_verification = None
            for attempt in range(1, self.config.feedback.verify_attempts + 1):
                try:
                    guide_verification = self.feedback.verify_selected(
                        channel.name, configured_path=channel.template
                    )
                    break
                except NavigationError as exc:
                    last_error = exc
                    events.append(
                        {
                            "event": "guide_candidate_retry",
                            "scan_offset": scan_offset,
                            "attempt": attempt,
                            "error": {"message": str(exc), "details": exc.details},
                        }
                    )
                    if self.config.feedback.fresh_frames and "visual_verification" in exc.details:
                        # This is a fresh, visible row with the wrong logo.
                        # Re-reading it three times cannot make it the target.
                        break
                    if attempt < self.config.feedback.verify_attempts:
                        self._sleep(self.config.feedback.verify_retry_seconds)

            if guide_verification is not None:
                direct = self._verify_direct_selection(channel, events)
                if direct is not None:
                    return direct
                if not network_template.is_file():
                    raise NavigationError(
                        f"{channel.name} needs network-page verification, but its page template is missing"
                    )
                self._publish_operation(
                    phase="verifying_channel_description",
                    app_state=AppState.LIVE_GUIDE,
                    message=f"Found {channel.name}; focusing its station tile",
                )
                events.append(
                    {
                        "event": "guide_candidate",
                        "scan_offset": scan_offset,
                        "result": guide_verification,
                    }
                )
                network_focus = self._focus_network_tile(events)
                events.append(
                    {"event": "network_focus_verification", "result": network_focus}
                )
                self.ecp.keypress("Select")
                events.append(
                    {"event": "keypress", "key": "Select", "action": "open_network"}
                )
                self._publish_operation(
                    phase="verifying_channel_description",
                    app_state=None,
                    message=f"Opening and verifying {channel.name}'s channel page",
                )
                self._sleep(self.config.feedback.network_page_settle_seconds)
                network_verification = None
                try:
                    for attempt in range(1, self.config.feedback.verify_attempts + 1):
                        try:
                            network_verification = self.feedback.verify_network_page(
                                network_page, (channel.name, *channel.aliases)
                            )
                            break
                        except NavigationError as exc:
                            last_error = exc
                            events.append(
                                {
                                    "event": "network_page_candidate_retry",
                                    "scan_offset": scan_offset,
                                    "attempt": attempt,
                                    "error": {
                                        "message": str(exc),
                                        "details": exc.details,
                                    },
                                }
                            )
                            if attempt < self.config.feedback.verify_attempts:
                                self._sleep(self.config.feedback.verify_retry_seconds)
                finally:
                    self.ecp.keypress("Back")
                    self._publish_operation(
                        phase="returning_to_guide",
                        app_state=AppState.LIVE_GUIDE,
                        message=(f"Channel page verified; returning to {channel.name}" if network_verification is not None else f"Channel page did not verify; returning to the guide"),
                    )
                    events.append(
                        {"event": "keypress", "key": "Back", "action": "close_network"}
                    )
                    self._sleep(nav.guide_settle_seconds)
                    current_focus = self._focus_current_program(events)
                    events.append(
                        {
                            "event": "current_program_focus_verification",
                            "result": current_focus,
                        }
                    )

                if network_verification is None:
                    # The row was already positively identified. A failed
                    # page check is not evidence that the next row is right;
                    # scanning onward just hides a missing/stale calibration.
                    raise NavigationError(
                        f"{channel.name}'s channel page could not be verified on the selected input; its page calibration may need updating",
                        details={
                            "channel": channel.name,
                            "network_page": network_page,
                            "last_verification": last_error.details if last_error else {},
                        },
                    )

                if network_verification is not None:
                    events.append(
                        {
                            "event": "network_page_verification",
                            "scan_offset": scan_offset,
                            "result": network_verification,
                        }
                    )
                    # Returning is another UI transition. Re-check the row
                    # before the only key that can begin playback.
                    final_guide = None
                    for attempt in range(
                        1, self.config.feedback.verify_attempts + 1
                    ):
                        try:
                            final_guide = self.feedback.verify_selected(
                                channel.name, configured_path=channel.template
                            )
                            break
                        except NavigationError as exc:
                            last_error = exc
                            if attempt < self.config.feedback.verify_attempts:
                                self._sleep(self.config.feedback.verify_retry_seconds)
                    if final_guide is not None:
                        self._publish_operation(
                            phase="guide_verified",
                            app_state=AppState.LIVE_GUIDE,
                            message=f"{channel.name} is verified and ready to play",
                        )
                        result = dict(final_guide)
                        result["network_page"] = network_verification
                        events.append(
                            {"event": "final_channel_verification", "result": result}
                        )
                        return result

            if scan_offset < nav.guide_scan_max_rows:
                # Row offsets are only estimates: dropped keys and new local
                # stations can put us on either side of the requested channel.
                # Recompute direction from a recognized neighbor each time.
                try:
                    if isinstance(self.feedback, VisualFeedback) and self.config.feedback.fresh_frames:
                        current = self.feedback.identify_selected(self.config.channels, self.feedback.last_frame)
                    else:
                        current = self.feedback.identify_selected(self.config.channels)
                except NavigationError:
                    pass
                else:
                    observed_index = current.get("guide_index")
                    if (type(observed_index) is int and observed_index != channel.guide_index
                            and self._reliable_guide_anchor(current)):
                        scan_key = "Up" if observed_index > channel.guide_index else "Down"
                    events.append({"event": "guide_scan_anchor", "observation": current,
                                   "trusted": self._reliable_guide_anchor(current), "direction": scan_key})
                self.ecp.keypress(scan_key)
                events.append(
                    {
                        "event": "guide_scan",
                        "key": scan_key,
                        "scan_offset": scan_offset + 1,
                        "phase": "closed_loop_scan",
                    }
                )
                self._sleep(nav.key_delay_seconds if self.config.feedback.fresh_frames else nav.guide_settle_seconds)

        details = last_error.details if last_error is not None else {}
        raise NavigationError(
            f"Could not find and independently verify {channel.name!r} "
            f"within {nav.guide_scan_max_rows} guide rows",
            details={"last_error": str(last_error), "last_details": details},
        )

    def _reliable_guide_anchor(self, observation: dict[str, object]) -> bool:
        channel = next((item for item in self.config.channels if item.name == observation.get("channel")), None)
        if channel is not None and not channel.anchor_safe:
            return False
        if not isinstance(self.feedback, VisualFeedback) or not self.config.feedback.fresh_frames:
            return True
        verification = observation.get("guide_verification") or observation.get("verification") or {}
        return (float(verification.get("correlation", -1)) >= max(0.95, self.config.feedback.guide_correlation_threshold)
                and float(verification.get("correlation_margin") or 0) >= max(0.01, self.config.feedback.guide_correlation_margin))

    def _verify_direct_selection(
        self, channel: ChannelConfig, events: list[dict[str, object]]
    ) -> dict[str, object] | None:
        feedback = self.feedback
        if not (self.config.feedback.network_page_fallback
                and self.config.feedback.fresh_frames
                and isinstance(feedback, VisualFeedback)
                and channel.anchor_safe):
            return None
        observations = []
        for _ in range(2):
            frame = feedback.capture()
            try:
                focus = feedback.assert_current_program_focus(frame)
                verification = feedback.verify_selected(channel.name, configured_path=channel.template, frame=frame)
            except NavigationError as exc:
                events.append({"event": "direct_selection_fallback", "reason": str(exc)})
                return None
            # The short route needs stronger shape separation than the normal
            # candidate check. A low pixel distance alone is insufficient.
            if (float(verification.get("correlation", -1)) < max(0.95, self.config.feedback.guide_correlation_threshold)
                    or float(verification.get("correlation_margin") or 0) < max(0.02, self.config.feedback.guide_correlation_margin)):
                events.append({"event": "direct_selection_fallback", "reason": "insufficient_logo_separation", "verification": verification})
                return None
            observations.append({"capture": dict(feedback.last_capture or {}), "verification": verification, "focus": focus})
        first, second = (item["capture"] for item in observations)
        if not (first.get("fresh") and second.get("fresh")
                and first.get("stream_id") == second.get("stream_id")
                and second.get("sequence", 0) > first.get("sequence", 0)):
            raise NavigationError("Direct selection requires two distinct fresh frames from the same stream")
        result = {**observations[-1]["verification"], "method": "two_fresh_guide_observations",
                  "observations": observations, "network_page": None}
        events.append({"event": "final_channel_verification", "result": result})
        self._publish_operation(phase="guide_verified", app_state=AppState.LIVE_GUIDE,
                                message=f"{channel.name} and current-program focus verified in two fresh frames")
        return result

    def play(
        self,
        requested_channel: str,
        *,
        baseball_game: dict[str, object] | None = None,
        sunday_ticket: dict[str, object] | None = None,
        select: bool = True,
        _reserved: bool = False,
        _operation_id: str | None = None,
    ) -> dict[str, object]:
        """Play a guide row. With `sunday_ticket` (an NFL game), `requested_channel`
        is the anchor row the scan starts from; `select=False` stops on the verified
        row without pressing Select."""
        _, channel = self.config.resolve_channel(requested_channel)
        label = str(sunday_ticket.get("title")) if sunday_ticket else channel.name
        with self._cue_control(reserved=_reserved):
            operation_id = _operation_id or self._begin_channel_operation(label)
            started = datetime.now(timezone.utc)
            self._publish_operation(
                active=True,
                phase="checking_control_path",
                app_state=None,
                channel=label,
                provider="sunday_ticket" if sunday_ticket else "youtube_tv",
                game_pk=(baseball_game or {}).get("game_pk") or (sunday_ticket or {}).get("game_id"),
                game=(baseball_game or sunday_ticket or {}).get("title"),
                message="Checking the Roku and selected return feed",
                started_at=started.isoformat(),
                completed_at=None,
                error=None,
            )
            try:
                events = EventLog(self._operations.directory / f"{operation_id}.jsonl")
                if isinstance(self.feedback, VisualFeedback):
                    self.feedback.last_frame = None
                    self.feedback.last_capture = None
                    self.feedback.on_capture = lambda observation: events.append({"event": "frame_captured", **observation})
                if self._cancel.is_set():
                    raise CueCancelledError("Cue stopped by the operator")
                app_id, info = self._assert_ready()
                events.append(
                    {
                        "event": "ready",
                        "roku_model": info.get("model-name"),
                        "roku_version": info.get("software-version"),
                        "app_id": app_id,
                    }
                )
                if self.feedback is None:
                    self._clean_launch(app_id, events)
                    verification = self._open_channel_row(channel, events)
                elif sunday_ticket:
                    guide_observation = self._drive_to_live_guide(app_id, events)
                    verification = self._open_sunday_ticket_row(
                        sunday_ticket, channel, events, guide_observation=guide_observation
                    )
                else:
                    guide_observation = self._drive_to_live_guide(app_id, events)
                    verification = self._open_channel_row(
                        channel, events, guide_observation=guide_observation
                    )
                if not select:
                    completed = datetime.now(timezone.utc)
                    result = {"ok": True, "selected": False, "operation_id": operation_id,
                              "channel": label, "started_at": started.isoformat(),
                              "completed_at": completed.isoformat(),
                              "duration_seconds": round((completed - started).total_seconds(), 3),
                              "verification": {"guide_row": verification}, "events": events}
                    self._publish_operation(active=False, phase="complete", app_state=AppState.LIVE_GUIDE,
                                            message=f"Found {label} in the guide; not selected",
                                            completed_at=completed.isoformat(), result=result)
                    return result
                self._publish_operation(
                    phase="starting_playback",
                    app_state=AppState.LIVE_GUIDE,
                    message=f"Starting {label} from the verified guide row",
                )
                self.ecp.keypress("Select")
                events.append(
                    {"event": "keypress", "key": "Select", "action": "play"}
                )
                self._sleep(self.config.navigation.play_settle_seconds)
                player = self._wait_for_playback(app_id, events)
                completed = datetime.now(timezone.utc)
                result = {
                    "ok": True,
                    "operation_id": operation_id,
                    "channel": label,
                    "guide_index": None if sunday_ticket else channel.guide_index,
                    "started_at": started.isoformat(),
                    "completed_at": completed.isoformat(),
                    "duration_seconds": round((completed - started).total_seconds(), 3),
                    "verification": {
                        "roku_app": "YouTube TV",
                        "player_state": player.get("state"),
                        "visible_channel_template": verification,
                        "playback_evidence": "roku_player_play_after_verified_selection",
                        "playing_channel_independently_verified": False,
                    },
                    "events": events,
                }
                if sunday_ticket is not None:
                    result.update({"game_id": sunday_ticket.get("game_id"), "game": sunday_ticket.get("title"),
                                   "provider": "sunday_ticket", "source": "NFL Sunday Ticket"})
                if baseball_game is not None:
                    result.update(
                        {
                            "game_pk": baseball_game.get("game_pk"),
                            "game": baseball_game.get("title"),
                            "provider": "youtube_tv",
                            "source": channel.name,
                        }
                    )
            except Exception as exc:
                if hasattr(exc, "details"):
                    exc.details["operation_id"] = operation_id
                diagnostic = None
                if isinstance(self.feedback, VisualFeedback) and self.feedback.last_frame is not None:
                    frame = self.feedback.last_frame
                    path = self._operations.directory / f"{operation_id}.ppm"
                    try:
                        path.write_bytes(f"P6\n{frame.width} {frame.height}\n255\n".encode() + frame.rgb)
                        diagnostic = {"frame_path": str(path), "capture": self.feedback.last_capture}
                    except OSError:
                        pass
                error = {"type": type(exc).__name__, "message": str(exc),
                         "code": getattr(exc, "code", "internal_error"), "details": getattr(exc, "details", {})}
                events.append({"event": "cue_failed", "error": error, "diagnostic": diagnostic})
                self._publish_operation(
                    active=False,
                    phase="cancelled" if isinstance(exc, CueCancelledError) else "error",
                    message=str(exc) if isinstance(exc, CueCancelledError) else f"Cue failed: {exc}",
                    error=error,
                    diagnostic=diagnostic,
                    completed_at=datetime.now(timezone.utc).isoformat(),
                )
                raise
            finally:
                if isinstance(self.feedback, VisualFeedback):
                    self.feedback.on_capture = None

            self._publish_operation(
                active=False,
                phase="complete",
                app_state=AppState.FULL_PROGRAM,
                message=f"{label} was selected; Roku reported playback",
                completed_at=completed.isoformat(),
                result=result,
            )
            if sunday_ticket is not None:
                self._set_on_air({"type": "sunday_ticket", "channel": label, "provider": "sunday_ticket",
                                  "game_id": sunday_ticket.get("game_id"), "title": sunday_ticket.get("title")})
            elif baseball_game is None:
                self._set_on_air(
                    {
                        "type": "channel",
                        "channel": channel.name,
                        "provider": "youtube_tv",
                    }
                )
            else:
                self._set_on_air(
                    {
                        "type": "baseball",
                        "channel": channel.name,
                        "provider": "youtube_tv",
                        "game_pk": baseball_game.get("game_pk"),
                        "game_date": baseball_game.get("official_date"),
                        "title": baseball_game.get("title"),
                    }
                )
            return result

    def _observe_mlb(self, app_id: str) -> dict[str, object]:
        active = self.ecp.active_app()
        if active.id != app_id:
            return {
                "state": AppState.ROKU_HOME,
                "evidence": "active_app_is_not_mlb",
                "active_app": active.__dict__,
            }
        if self.feedback is None:
            raise NavigationError("Visual feedback is required for MLB navigation")
        player = self.ecp.media_player()
        frame = self.feedback.capture()
        return {
            **self.feedback.detect_mlb_state(frame, player, app_id),
            "active_app": active.__dict__,
            "media_player": player,
            "frame": frame,
        }

    def _open_mlb_games(
        self, app_id: str, events: list[dict[str, object]]
    ) -> dict[str, object]:
        mlb = self.config.mlb
        nav = self.config.navigation
        self._publish_operation(
            phase="launching_mlb",
            app_state=AppState.ROKU_HOME,
            message="Launching MLB",
        )
        # A fresh Roku-Home launch clears abandoned feed pickers and invalid
        # deep-link error screens while preserving the signed-in account.
        self.ecp.keypress("Home")
        self._sleep(nav.post_exit_settle_seconds)
        self.ecp.launch(app_id)
        self.ecp.wait_for_active_app(
            app_id,
            timeout=self.config.roku.launch_timeout_seconds,
            interval=self.config.roku.poll_interval_seconds,
        )
        self._sleep(mlb.launch_settle_seconds)
        events.append({"event": "launch", "app": "MLB", "app_id": app_id})

        for attempt in range(1, 8):
            observation = self._observe_mlb(app_id)
            frame = observation.pop("frame", None)
            state = AppState(str(observation["state"]))
            self._publish_operation(
                phase="opening_mlb_games",
                app_state=state,
                message=self._state_progress_message(state),
            )
            events.append(
                {
                    "event": "mlb_state_detected",
                    "attempt": attempt,
                    "state": state,
                    "observation": observation,
                }
            )
            if state == AppState.MLB_GAMES_GRID:
                observation["frame"] = frame
                return observation
            if state == AppState.ROKU_HOME:
                self.ecp.launch(app_id)
                self.ecp.wait_for_active_app(
                    app_id,
                    timeout=self.config.roku.launch_timeout_seconds,
                    interval=self.config.roku.poll_interval_seconds,
                )
                events.append(
                    {"event": "relaunch", "app": "MLB", "app_id": app_id}
                )
                self._sleep(mlb.launch_settle_seconds)
                continue
            if state == AppState.MLB_ERROR:
                self.ecp.keypress("Select")
                events.append({"event": "keypress", "key": "Select", "action": "mlb_try_again"})
                self._sleep(mlb.launch_settle_seconds)
                continue
            if state in (
                AppState.FULL_PROGRAM,
                AppState.MLB_FEED_PICKER,
                AppState.MLB_ENTITLEMENT_REQUIRED,
                AppState.MLB_BROADCAST_ENDED,
            ):
                self.ecp.keypress("Back")
                events.append({"event": "keypress", "key": "Back", "action": "return_to_mlb"})
                self._sleep(mlb.games_settle_seconds)
                continue
            if state == AppState.MLB_GAMES_LOADING:
                self._sleep(mlb.games_settle_seconds)
                continue

            if state == AppState.UNKNOWN:
                self._sleep(self.config.roku.poll_interval_seconds)
                continue

            # MLB's header order is Home, Games, Shows. Repeated Up reaches the
            # header from any home shelf, repeated Left anchors Home, and Right
            # focuses Games. Crucially, geometry must prove the white Games
            # pill before the Select that changes screens.
            for _ in range(6):
                self.ecp.keypress("Up")
                self._sleep(mlb.scan_settle_seconds)
            for _ in range(6):
                self.ecp.keypress("Left")
                self._sleep(mlb.scan_settle_seconds)
            self.ecp.keypress("Right")
            self._sleep(mlb.scan_settle_seconds)
            if self.feedback is None:
                raise NavigationError("Visual feedback is required for MLB navigation")
            focus_frame = self.feedback.capture()
            games_focus = self.feedback.assert_mlb_games_tab_focus(focus_frame)
            events.append(
                {
                    "event": "mlb_games_tab_verified",
                    "verification": games_focus,
                }
            )
            self.ecp.keypress("Select")
            events.append({"event": "navigation", "action": "open_mlb_games_tab"})
            self._sleep(mlb.games_settle_seconds)

        raise NavigationError(
            "Could not reach MLB's Games grid",
            details={"events": events[-8:]},
        )

    def _find_mlb_game_card(
        self,
        app_id: str,
        game: dict[str, object],
        events: list[dict[str, object]],
    ) -> dict[str, object]:
        if self.feedback is None:
            raise NavigationError("Visual feedback is required for MLB navigation")
        away = game.get("away") if isinstance(game.get("away"), dict) else {}
        home = game.get("home") if isinstance(game.get("home"), dict) else {}
        away_names = team_ocr_names(away)
        home_names = team_ocr_names(home)
        direction = "right"
        last_verification: dict[str, object] = {}

        self._publish_operation(
            phase="scanning_mlb_games",
            app_state=AppState.MLB_GAMES_GRID,
            message=f"Scanning MLB game cards for {game.get('title')}",
        )
        for scan_index in range(self.config.mlb.max_cards):
            if self.ecp.active_app().id != app_id:
                raise EcpError("MLB stopped being the active Roku app")
            # A fresh capture can still show MLB's loading screen.
            # Wait for the white cursor instead of treating
            # one transient spinner frame as a navigation failure.
            cursor_error: NavigationError | None = None
            for cursor_attempt in range(1, 7):
                frame = self.feedback.capture()
                try:
                    last_verification = self.feedback.verify_mlb_selected_game(
                        away_names, home_names, frame
                    )
                except NavigationError as exc:
                    cursor_error = exc
                    self._publish_operation(
                        phase="waiting_for_mlb_grid",
                        app_state=AppState.MLB_GAMES_LOADING,
                        message="Waiting for MLB's selected game card to appear",
                    )
                    if cursor_attempt < 6:
                        self._sleep(self.config.feedback.verify_retry_seconds)
                        continue
                    raise NavigationError(
                        "MLB's game grid did not become visually ready",
                        details={"last_cursor_error": cursor_error.details},
                    ) from exc
                else:
                    break
            events.append(
                {
                    "event": "mlb_card_observed",
                    "scan_index": scan_index,
                    "verification": last_verification,
                }
            )
            if last_verification["matched"] is True:
                confirmation = self._confirm_mlb_game(
                    game, last_verification,
                    lambda frame: self.feedback.verify_mlb_selected_game(away_names, home_names, frame), events)
                if confirmation is not None:
                    self._publish_operation(app_state=AppState.MLB_GAMES_GRID)
                    return confirmation
                continue

            cursor = last_verification["cursor"]
            column = int(cursor["column"])
            if direction == "right" and column < 2:
                key = "Right"
            elif direction == "right":
                key = "Down"
                direction = "left"
            elif column > 0:
                key = "Left"
            else:
                key = "Down"
                direction = "right"
            self.ecp.keypress(key)
            events.append(
                {
                    "event": "keypress",
                    "key": key,
                    "action": "scan_mlb_game_grid",
                    "scan_index": scan_index,
                }
            )
            self._sleep(self.config.mlb.scan_settle_seconds)

        raise NavigationError(
            f"Could not visually find {game.get('title')} in MLB's game grid",
            details={"last_verification": last_verification},
        )

    def _wait_for_mlb_playback(
        self, app_id: str, events: list[dict[str, object]]
    ) -> dict[str, object]:
        deadline = time.monotonic() + self.config.roku.playback_timeout_seconds
        last_observation: dict[str, object] = {}
        playing_observations = 0
        feed_confirmed = False
        live_confirmed = False
        feed_focus_actions = 0
        prompt_actions = 0
        last_player: dict[str, object] = {}
        while time.monotonic() < deadline:
            active = self.ecp.active_app()
            if active.id != app_id:
                raise EcpError("MLB stopped being the active Roku app")
            player = self.ecp.media_player()
            last_player = player
            if player.get("error") == "true":
                raise EcpError("Roku reported an MLB playback error", details={"media_player": player})
            plugin = player.get("plugin")
            plugin_id = plugin.get("id") if isinstance(plugin, dict) else None
            if self.feedback is not None:
                frame = self.feedback.capture()
                last_observation = self.feedback.detect_mlb_state(
                    frame, player, app_id
                )
                state = AppState(str(last_observation["state"]))
                events.append({"event": "mlb_playback_state", "observation": last_observation, "media_player": player})
                self._publish_operation(
                    phase="waiting_for_mlb_playback",
                    app_state=state,
                    message=f"Waiting for MLB playback (screen: {state}, player: {player.get('state', 'unknown')})",
                )
                if state != AppState.FULL_PROGRAM:
                    playing_observations = 0
                if state == AppState.MLB_BROADCAST_ENDED:
                    raise NavigationError(
                        'This MLB broadcast has ended (Thank You for Watching); no live program is available',
                        details={'observation': last_observation},
                    )
                if state == AppState.MLB_FEED_PICKER:
                    if not feed_confirmed:
                        selection = last_observation.get("selection") or {}
                        selected = selection.get("selected")
                        if selected in ("video", "audio", "condensed"):
                            feed_focus_actions += 1
                            if feed_focus_actions > 3:
                                raise NavigationError("MLB video-feed focus did not advance")
                            key = {"video": "Select", "audio": "Up", "condensed": "Down"}[selected]
                            self.ecp.keypress(key)
                            feed_confirmed = selected == "video"
                            events.append({"event": "keypress", "key": key, "action": "select_mlb_video_feed" if feed_confirmed else "focus_mlb_video_feed", "selection": selection})
                            self._publish_operation(phase="selecting_mlb_feed", message="Opening the verified video feed" if feed_confirmed else "Moving to the video broadcast")
                            deadline = time.monotonic() + self.config.roku.playback_timeout_seconds
                    self._sleep(self.config.navigation.play_settle_seconds)
                    continue
                if state == AppState.JOIN_LIVE_OR_START_FROM_BEGINNING:
                    if live_confirmed:
                        self._sleep(self.config.navigation.play_settle_seconds)
                        continue
                    prompt_actions += 1
                    if prompt_actions > 4:
                        raise NavigationError("MLB's live prompt did not advance after verified actions", details={"observation": last_observation})
                    selection = last_observation.get("selection")
                    selected = (
                        selection.get("selected")
                        if isinstance(selection, dict)
                        else None
                    )
                    if selected in ("catch_up", "resume"):
                        self.ecp.keypress("Down")
                        action = "focus_mlb_watch_live"
                        key = "Down"
                    elif selected == "start_from_beginning":
                        self.ecp.keypress("Up")
                        action = "focus_mlb_watch_live"
                        key = "Up"
                    elif selected == "watch_live":
                        self.ecp.keypress("Select")
                        live_confirmed = True
                        action = "mlb_join_live"
                        key = "Select"
                    else:
                        raise NavigationError(
                            "MLB's Watch Live option was not visibly located",
                            details={"observation": last_observation},
                        )
                    events.append(
                        {"event": "keypress", "key": key, "action": action}
                    )
                    if selected == "watch_live":
                        deadline = time.monotonic() + self.config.roku.playback_timeout_seconds
                    self._sleep(self.config.navigation.play_settle_seconds)
                    continue
                if state == AppState.MLB_ENTITLEMENT_REQUIRED:
                    raise NavigationError(
                        "This MLB broadcast requires an additional entitlement",
                        details={"observation": last_observation},
                    )
                if state == AppState.MLB_ERROR:
                    raise NavigationError(
                        "MLB reported an error while starting the game",
                        details={"observation": last_observation},
                    )
                if (
                    state == AppState.FULL_PROGRAM
                    and player.get("state") == "play"
                    and plugin_id == app_id
                ):
                    media_format = player.get("format") or {}
                    if "video" in media_format and str(media_format["video"]).casefold() in ("", "none"):
                        raise NavigationError("MLB opened audio without video", details={"media_player": player})
                    playing_observations += 1
                    if playing_observations >= 2 and (feed_confirmed or live_confirmed):
                        return player
                else:
                    playing_observations = 0
            elif player.get("state") == "play" and plugin_id == app_id:
                return player
            self._sleep(self.config.roku.poll_interval_seconds)
        raise EcpError(
            "Timed out waiting for MLB playback",
            details={"last_observation": last_observation, "media_player": last_player,
                     "video_feed_confirmed": feed_confirmed, "watch_live_confirmed": live_confirmed},
        )

    def _confirm_mlb_game(self, game, verification, verifier, events):
        """Require the same focused matchup again, without another remote key."""
        first_capture = dict(getattr(self.feedback, "last_capture", None) or {})
        self._sleep(self.config.mlb.scan_settle_seconds)
        frame = self.feedback.capture()
        confirmation = verifier(frame)
        second_capture = dict(getattr(self.feedback, "last_capture", None) or {})
        events.append({"event": "mlb_game_confirmation", "first": verification,
                       "confirmation": confirmation, "captures": [first_capture, second_capture]})
        if not confirmation.get("matched"):
            return None
        if isinstance(self.feedback, VisualFeedback) and self.config.feedback.fresh_frames:
            if not (first_capture.get("fresh") and second_capture.get("fresh")
                    and first_capture.get("stream_id") == second_capture.get("stream_id")
                    and second_capture.get("sequence", 0) > first_capture.get("sequence", 0)):
                raise NavigationError("MLB game confirmation needs two fresh frames from the same stream")
        if str(game.get("state", "")).casefold() == "live" and not (verification.get("live") and confirmation.get("live")):
            raise NavigationError("Both teams were found, but this card was not confirmed live in both observations",
                                  details={"verification": verification, "confirmation": confirmation})
        self._publish_operation(phase="mlb_game_verified", app_state=AppState.MLB_HOME,
                                message=f"Verified {game.get('title')} in two observations")
        return {**confirmation, "confirmation_count": 2, "captures": [first_capture, second_capture]}

    def _find_mlb_home_lineup_card(self, app_id, game, events):
        """Observe the current lineup, then scan both ways without key bursts."""
        if self.feedback is None:
            raise NavigationError("Visual feedback is required for MLB navigation")
        away_names = team_ocr_names(game.get("away") or {})
        home_names = team_ocr_names(game.get("home") or {})
        verifier = lambda frame: self.feedback.verify_mlb_home_lineup_game(away_names, home_names, frame)
        self._publish_operation(phase="opening_mlb_home_lineup", app_state=None,
                                message="Finding the game in MLB's Today’s Lineup")
        if self.ecp.active_app().id != app_id:
            self.ecp.launch(app_id)
            self.ecp.wait_for_active_app(app_id, timeout=self.config.roku.launch_timeout_seconds,
                                         interval=self.config.roku.poll_interval_seconds)
            events.append({"event": "launch", "app": "MLB", "app_id": app_id})
            self._sleep(self.config.mlb.launch_settle_seconds)
        # App launch and menu loading have separate bounded budgets. A slow
        # launch must not consume the time reserved for observing its spinner.
        deadline = time.monotonic() + max(60, self.config.roku.launch_timeout_seconds)
        while time.monotonic() < deadline:
            if self.ecp.active_app().id != app_id:
                raise EcpError("MLB stopped being the active Roku app while its lineup loaded")
            frame = self.feedback.capture()
            try:
                self.feedback.mlb_home_lineup_cursor(frame)
                break
            except NavigationError:
                observation = self.feedback.detect_mlb_state(frame, self.ecp.media_player(), app_id)
            state = AppState(str(observation["state"]))
            events.append({"event": "mlb_state_detected", "observation": observation})
            self._publish_operation(app_state=state, message="Waiting for MLB's lineup" if state in (AppState.UNKNOWN, AppState.MLB_GAMES_LOADING) else self._state_progress_message(state))
            if state == AppState.MLB_ERROR:
                raise NavigationError("MLB could not load its menu", details={"observation": observation})
            if state in (AppState.FULL_PROGRAM, AppState.MLB_FEED_PICKER, AppState.JOIN_LIVE_OR_START_FROM_BEGINNING, AppState.MLB_ENTITLEMENT_REQUIRED, AppState.MLB_BROADCAST_ENDED):
                key = "Back"
            elif state in (AppState.MLB_HOME, AppState.MLB_GAMES_GRID):
                key = "Down"
            else:
                self._sleep(max(1, self.config.roku.poll_interval_seconds))
                continue
            self.ecp.keypress(key)
            events.append({"event": "keypress", "key": key, "action": "reach_mlb_lineup"})
            self._sleep(self.config.mlb.games_settle_seconds)
        else:
            raise NavigationError("MLB's lineup did not become ready; stopped without selecting an unknown screen")

        direction = "Right"
        reversed_direction = False
        previous = None
        stationary = 0
        for scan_index in range(self.config.mlb.max_cards * 2 + 4):
            if self.ecp.active_app().id != app_id:
                raise EcpError("MLB stopped being the active Roku app")
            self._publish_operation(phase="scanning_mlb_games", app_state=AppState.MLB_HOME,
                                    message=f"Checking lineup card {scan_index + 1} for {game.get('title')}")
            for attempt in range(self.config.feedback.verify_attempts):
                frame = self.feedback.capture()
                try:
                    verification = verifier(frame)
                    break
                except NavigationError:
                    if attempt + 1 == self.config.feedback.verify_attempts:
                        raise
                    self._sleep(self.config.feedback.verify_retry_seconds)
            events.append({"event": "mlb_home_card_observed", "scan_index": scan_index, "verification": verification})
            if verification.get("matched"):
                confirmation = self._confirm_mlb_game(game, verification, verifier, events)
                if confirmation is not None:
                    return confirmation
                # A moving or changed card invalidates the candidate. Observe
                # again before choosing another movement.
                continue
            signature = (verification.get("cursor", {}).get("column"),
                         normalize_channel_name(str(verification.get("ocr_text") or "")))
            stationary = stationary + 1 if signature == previous and signature[1] else 0
            if stationary >= 2:
                if reversed_direction:
                    break
                direction = "Left"
                reversed_direction = True
                stationary = 0
                events.append({"event": "mlb_lineup_boundary", "direction": direction})
            previous = signature
            self.ecp.keypress(direction)
            events.append({"event": "keypress", "key": direction, "action": "scan_mlb_today_lineup", "scan_index": scan_index})
            self._sleep(self.config.mlb.scan_settle_seconds)
        raise NavigationError(f"Could not verify {game.get('title')} in MLB Today’s Lineup",
                              details={"last_verification": verification})

    @staticmethod
    def _prefer_mlb_lineup(game: dict[str, object]) -> bool:
        # A West Coast game retains yesterday's official date after midnight
        # on this controller. Its live status is the relevant routing signal.
        return str(game.get("state", "")).casefold() == "live" or game.get("official_date") == date.today().isoformat()

    def _record_cue_failure(self, operation_id: str, events: EventLog, exc: Exception) -> None:
        if hasattr(exc, "details"):
            exc.details["operation_id"] = operation_id
        diagnostic = None
        if isinstance(self.feedback, VisualFeedback) and self.feedback.last_frame is not None:
            frame = self.feedback.last_frame
            path = self._operations.directory / f"{operation_id}.ppm"
            try:
                path.write_bytes(f"P6\n{frame.width} {frame.height}\n255\n".encode() + frame.rgb)
                diagnostic = {"frame_path": str(path), "capture": self.feedback.last_capture}
            except OSError:
                pass
        error = {"type": type(exc).__name__, "message": str(exc),
                 "code": getattr(exc, "code", "internal_error"), "details": getattr(exc, "details", {})}
        events.append({"event": "cue_failed", "error": error, "diagnostic": diagnostic})
        self._publish_operation(active=False, phase="cancelled" if isinstance(exc, CueCancelledError) else "error",
                                message=f"Cue failed: {exc}", error=error, diagnostic=diagnostic,
                                completed_at=datetime.now(timezone.utc).isoformat())

    def play_mlb_game(self, game: dict[str, object], *, _reserved: bool = False,
                      _operation_id: str | None = None) -> dict[str, object]:
        """Visually select a schedule game in MLB and start its default video feed."""
        game_pk = game.get("game_pk")
        title = str(game.get("title") or f"MLB game {game_pk}")
        with self._cue_control(reserved=_reserved):
            operation_id = _operation_id or self._begin_channel_operation(title, provider="mlb", game=game)
            started = datetime.now(timezone.utc)
            self._publish_operation(
                active=True,
                phase="checking_control_path",
                app_state=None,
                channel=title,
                provider="mlb",
                id=operation_id,
                result=None,
                game_pk=game_pk,
                game=title,
                message="Checking the Roku and selected return feed",
                started_at=started.isoformat(),
                completed_at=None,
                error=None,
            )
            events = EventLog(self._operations.directory / f"{operation_id}.jsonl")
            try:
                if isinstance(self.feedback, VisualFeedback):
                    self.feedback.last_frame = None
                    self.feedback.last_capture = None
                    self.feedback.on_capture = lambda observation: events.append({"event": "frame_captured", **observation})
                if self._cancel.is_set():
                    raise CueCancelledError("Cue stopped by the operator")
                if game.get("official_date") and not self._prefer_mlb_lineup(game):
                    raise NavigationError(
                        "MLB archive date selection is not verified; select a current-day or still-live game",
                        details={"game_pk": game_pk, "official_date": game.get("official_date")},
                    )
                info = self.ecp.device_info()
                if info.get("ecp-setting-mode", "").casefold() != "enabled":
                    raise RokuNotReadyError("Roku Control by mobile apps must be set to Enabled")
                if self.feedback is None:
                    raise NavigationError("Visual feedback is required for MLB navigation")
                self.feedback.assert_ready()
                app_id = self._mlb_app_id()
                events.append({"event": "ready", "app_id": app_id, "game_pk": game_pk,
                               "official_date": game.get("official_date"), "game_state": game.get("state")})
                verification = None
                last_grid_error: NavigationError | None = None
                today_lineup_attempted = False
                if self._prefer_mlb_lineup(game):
                    today_lineup_attempted = True
                    try:
                        verification = self._find_mlb_home_lineup_card(
                            app_id, game, events
                        )
                    except NavigationError as exc:
                        events.append(
                            {
                                "event": "mlb_home_lineup_failed",
                                "error": str(exc),
                                "action": "try_mlb_games_grid",
                            }
                        )

                if verification is None:
                    for grid_attempt in range(1, 4):
                        try:
                            self._open_mlb_games(app_id, events)
                            verification = self._find_mlb_game_card(
                                app_id, game, events
                            )
                        except NavigationError as exc:
                            last_grid_error = exc
                            events.append(
                                {
                                    "event": "mlb_grid_retry",
                                    "attempt": grid_attempt,
                                    "error": str(exc),
                                }
                            )
                            if grid_attempt < 3:
                                self._publish_operation(
                                    phase="reopening_mlb_games",
                                    app_state=AppState.MLB_GAMES_LOADING,
                                    message="MLB returned from its loader; reopening Games",
                                )
                                continue
                            break
                        else:
                            break

                if verification is None and not today_lineup_attempted:
                    events.append(
                        {
                            "event": "mlb_games_fallback",
                            "error": str(last_grid_error),
                            "action": "scan_home_today_lineup",
                        }
                    )
                    verification = self._find_mlb_home_lineup_card(
                        app_id, game, events
                    )
                if verification is None:
                    raise NavigationError(
                        f"Could not visually verify {title} in MLB",
                        details={"last_grid_error": str(last_grid_error)},
                    )
                self.ecp.keypress("Select")
                events.append({"event": "keypress", "key": "Select", "action": "open_mlb_game"})
                self._sleep(self.config.mlb.games_settle_seconds)

                player = self._wait_for_mlb_playback(app_id, events)
                completed = datetime.now(timezone.utc)
                result = {
                    "ok": True,
                    "operation_id": operation_id,
                    "game_pk": game_pk,
                    "game": title,
                    "provider": "mlb",
                    "source": "MLB.TV",
                    "started_at": started.isoformat(),
                    "completed_at": completed.isoformat(),
                    "duration_seconds": round((completed - started).total_seconds(), 3),
                    "verification": {
                        "roku_app": "MLB",
                        "player_state": player.get("state"),
                        "selected_game_card": verification,
                        "playback_evidence": "two_player_observations_after_verified_mlb_playback_action",
                        "playback_observation_count": 2,
                    },
                    "events": events,
                }
            except Exception as exc:
                self._record_cue_failure(operation_id, events, exc)
                raise
            finally:
                if isinstance(self.feedback, VisualFeedback):
                    self.feedback.on_capture = None
            self._publish_operation(
                active=False,
                phase="complete",
                app_state=AppState.FULL_PROGRAM,
                message=f"{title} playback is confirmed via MLB",
                completed_at=completed.isoformat(),
                result=result,
            )
            self._set_on_air(
                {
                    "type": "baseball",
                    "provider": "mlb",
                    "game_pk": game_pk,
                    "game_date": game.get("official_date"),
                    "title": title,
                }
            )
            return result

    def play_sunday_ticket(self, game: dict[str, object], *, select: bool = True,
                           _reserved: bool = False, _operation_id: str | None = None) -> dict[str, object]:
        """Find an NFL game's temporary Sunday Ticket row by reading the guide, then play it."""
        if not isinstance(game.get("away"), dict) or not isinstance(game.get("home"), dict):
            raise NavigationError("The NFL game has no team names to look for")
        anchor = min(self.config.channels, key=lambda channel: channel.guide_index)
        return self.play(anchor.name, sunday_ticket=game, select=select,
                        _reserved=_reserved, _operation_id=_operation_id)

    def play_prime_game(self, game: dict[str, object], *, catalog=None) -> dict[str, object]:
        """Resolve and visually verify a live NFL event in the installed Prime app."""
        from .prime_video import PrimeVideoCatalog, start_game
        with self._cue_control():
            title = str(game.get('title') or 'Thursday Night Football')
            operation_id = self._begin_channel_operation(title, provider='prime_video', game=game)
            events = EventLog(self._operations.directory / f'{operation_id}.jsonl')
            self._publish_operation(active=True, phase='resolving_prime_video',
                                    message='Finding the live game in Prime Video', game_pk=game.get('game_id'))
            try:
                event = (catalog or PrimeVideoCatalog()).resolve(game)
                events.append({'event': 'prime_event_resolved', **event})
                self._sleep(0)  # Check cancellation after the catalog request.
                if isinstance(self.feedback, VisualFeedback):
                    self.feedback.last_frame = None
                    self.feedback.last_capture = None
                    self.feedback.on_capture = lambda observation: events.append({'event': 'frame_captured', **observation})
                verification = start_game(self, game, event, events)
                result = {'ok': True, 'operation_id': operation_id, 'game_id': game.get('game_id'),
                          'game': title, 'provider': 'prime_video', 'source': 'Thursday Night Football · Prime Video',
                          'verification': verification, 'events': events}
            except Exception as exc:
                self._record_cue_failure(operation_id, events, exc)
                raise
            finally:
                if isinstance(self.feedback, VisualFeedback):
                    self.feedback.on_capture = None
            self._publish_operation(active=False, phase='complete', app_state=AppState.FULL_PROGRAM,
                                    message=f'{title} is playing live on Prime Video', result=result,
                                    completed_at=datetime.now(timezone.utc).isoformat())
            self._set_on_air({'type': 'football', 'provider': 'prime_video', 'game_id': game.get('game_id'),
                              'game_date': event['date'], 'title': title})
            return result

    def calibrate_sunday_ticket(self, game: dict[str, object]) -> dict[str, object]:
        """Save the Sunday Ticket logo from the focused row, once it verifies as `game`."""
        with self._cue_control():
            observation = self._observe_sunday_ticket_row(game)
            if observation["calibrated_channel"] or not observation["matched"]:
                raise NavigationError("The focused guide row is not this game's Sunday Ticket row; find it first",
                                      details={"observation": observation})
            path = self.feedback.save_sunday_ticket_template()
            return {"ok": True, "template_path": str(path), "observation": observation,
                    "verification": self.feedback.sunday_ticket_logo(self.feedback.capture())}

    def _observe_sunday_ticket_row(self, game: dict[str, object]) -> dict[str, object]:
        frame = self.feedback.capture()
        header = self.feedback.read_guide_header(frame)
        try:
            row = self.feedback.read_guide_row(frame)
        except NavigationError:
            row = {"text": "", "upcoming": False}
        try:
            calibrated = self.feedback.identify_selected(self.config.channels, frame).get("channel")
        except NavigationError:
            calibrated = None
        logo = self.feedback.sunday_ticket_logo(frame)
        teams = self.feedback.match_nfl_game([header["text"], row["text"]], game)
        # A Sunday Ticket row is never a calibrated channel, so FOX showing the
        # same matchup is not mistaken for it. Strong evidence is the "NFL ST"
        # header line or the calibrated Sunday Ticket logo. Without a logo
        # template, any uncalibrated row whose title names both teams qualifies.
        strong = calibrated is None and (header["sunday_ticket"] or bool(logo and logo["matched"]))
        ticket = strong or (calibrated is None and logo is None)
        return {"header": header["text"], "row": row["text"], "calibrated_channel": calibrated,
                "sunday_ticket_logo": logo, "sunday_ticket": ticket, "strong_sunday_ticket": strong,
                "teams": teams["teams"], "matched": ticket and teams["matched"],
                "upcoming": header["upcoming"] or row["upcoming"]}

    def _open_sunday_ticket_row(
        self,
        game: dict[str, object],
        anchor: ChannelConfig,
        events: list[dict[str, object]],
        *,
        guide_observation: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Verify the top guide row, then read each row below it until the game's
        Sunday Ticket row is found in two fresh observations."""
        if self.feedback is None or getattr(self.feedback, "ocr", None) is None:
            raise NavigationError("Sunday Ticket selection needs the direct capture and local OCR")
        anchor_verification = self._open_channel_row(anchor, events, guide_observation=guide_observation)
        nav = self.config.navigation
        title = str(game.get("title"))
        seen_ticket = False
        limit = len(self.config.channels) + 40  # Every configured row plus a full Sunday slate.
        for step in range(1, limit + 1):
            self._publish_operation(phase="finding_sunday_ticket", app_state=AppState.LIVE_GUIDE,
                                    message=f"Reading guide row {step} for {title}")
            self.ecp.keypress("Down")
            events.append({"event": "sunday_ticket_scan", "key": "Down", "step": step})
            self._sleep(nav.key_delay_seconds + 0.6)
            observation = self._observe_sunday_ticket_row(game)
            events.append({"event": "sunday_ticket_row", "step": step,
                           **{k: v for k, v in observation.items() if k != "row" or v}})
            seen_ticket = seen_ticket or observation["strong_sunday_ticket"]
            if seen_ticket and observation["calibrated_channel"]:
                break  # Past the block of temporary Sunday Ticket rows.
            if not observation["matched"]:
                continue
            self._sleep(nav.key_delay_seconds)
            confirmation = self._observe_sunday_ticket_row(game)
            events.append({"event": "sunday_ticket_confirm", "step": step,
                           **{k: v for k, v in confirmation.items() if k != "row" or v}})
            if not confirmation["matched"]:
                continue
            if observation["upcoming"] or confirmation["upcoming"]:
                raise NavigationError(
                    f"{title} is listed on Sunday Ticket but has not started; it can be selected once it is live",
                    details={"sunday_ticket_row": confirmation, "row_offset": step})
            return {"matched": True, "surface": "sunday_ticket_guide_row", "anchor": anchor_verification,
                    "row_offset": step, "observations": [observation, confirmation]}
        raise NavigationError(
            f"{title} was not found among YouTube TV's Sunday Ticket guide rows",
            details={"rows_read": step, "sunday_ticket_rows_seen": seen_ticket})

    def play_baseball_game(
        self,
        game: dict[str, object],
        source: dict[str, object] | None = None,
        *,
        _reserved: bool = False,
        _operation_id: str | None = None,
    ) -> dict[str, object]:
        selected = source or (
            game.get("preferred_source")
            if isinstance(game.get("preferred_source"), dict)
            else None
        )
        if selected is None:
            raise NavigationError(
                f"No stream source is listed for {game.get('title')}",
                details={"game_pk": game.get("game_pk")},
            )
        provider = selected.get("provider")
        if provider == "youtube_tv":
            channel = selected.get("channel")
            if not isinstance(channel, str) or not channel:
                raise NavigationError("The YouTube TV baseball source has no channel")
            return self.play(channel, baseball_game=game, _reserved=_reserved, _operation_id=_operation_id)
        if provider == "mlb":
            return self.play_mlb_game(game, _reserved=_reserved, _operation_id=_operation_id)
        raise NavigationError(f"Unsupported baseball provider: {provider!r}")

    def calibrate(self, requested_channel: str) -> dict[str, object]:
        if not self.feedback:
            raise NavigationError("Visual feedback is not configured")
        _, channel = self.config.resolve_channel(requested_channel)
        with self._lock:
            active: RokuApp = self.ecp.active_app()
            app_id = self._app_id()
            if active.id != app_id:
                raise NavigationError(
                    "YouTube TV must be active with the requested guide row visibly selected"
                )
            path = self.feedback.save_selected_template(
                channel.name, configured_path=channel.template
            )
            verification = self.feedback.verify_selected(
                channel.name, configured_path=channel.template
            )
            return {
                "ok": True,
                "channel": channel.name,
                "template_path": str(path),
                "verification": verification,
            }

    def verify_current_row(self, requested_channel: str) -> dict[str, object]:
        if not self.feedback:
            raise NavigationError("Visual feedback is not configured")
        _, channel = self.config.resolve_channel(requested_channel)
        with self._lock:
            active = self.ecp.active_app()
            app_id = self._app_id()
            if active.id != app_id:
                raise NavigationError(
                    "YouTube TV must be active with a guide row visibly selected"
                )
            verification = self.feedback.verify_selected(
                channel.name, configured_path=channel.template
            )
            return {
                "ok": True,
                "expected_channel": channel.name,
                "verification": verification,
            }

    def calibrate_guide_frame(
        self, requested_channel: str, ppm_path: str
    ) -> dict[str, object]:
        """Calibrate from a previously observed raw channel-69 PPM frame."""
        if not self.feedback:
            raise NavigationError("Visual feedback is not configured")
        _, channel = self.config.resolve_channel(requested_channel)
        from pathlib import Path

        path = Path(ppm_path).expanduser().resolve()
        try:
            frame = PpmFrame.parse(path.read_bytes())
        except OSError as exc:
            raise NavigationError(f"Cannot read calibration frame {path}: {exc}") from exc
        with self._lock:
            template_path = self.feedback.save_selected_template(
                channel.name,
                configured_path=channel.template,
                frame=frame,
            )
            verification = self.feedback.verify_selected(
                channel.name,
                configured_path=channel.template,
                frame=frame,
            )
            return {
                "ok": True,
                "channel": channel.name,
                "source_frame": str(path),
                "template_path": str(template_path),
                "verification": verification,
            }

    def calibrate_profile(self) -> dict[str, object]:
        if not self.feedback:
            raise NavigationError("Visual feedback is not configured")
        with self._lock:
            active = self.ecp.active_app()
            app_id = self._app_id()
            if active.id != app_id:
                raise NavigationError(
                    "YouTube TV must be active with Vivian visibly selected"
                )
            path = self.feedback.save_profile_template("Vivian")
            verification = self.feedback.verify_vivian_profile()
            return {
                "ok": True,
                "profile": "Vivian",
                "template_path": str(path),
                "verification": verification,
            }

    def calibrate_network(self, requested_channel: str) -> dict[str, object]:
        if not self.feedback:
            raise NavigationError("Visual feedback is not configured")
        _, channel = self.config.resolve_channel(requested_channel)
        with self._lock:
            active = self.ecp.active_app()
            app_id = self._app_id()
            if active.id != app_id:
                raise NavigationError(
                    "YouTube TV must be active on the requested network page"
                )
            network_page = channel.network_page or channel.name
            path = self.feedback.save_network_template(network_page)
            verification = self.feedback.verify_network_page(
                network_page, (channel.name, *channel.aliases)
            )
            return {
                "ok": True,
                "channel": channel.name,
                "network_page": network_page,
                "template_path": str(path),
                "verification": verification,
            }

    def calibrate_current_network(self, requested_channel: str) -> dict[str, object]:
        """Safely open and calibrate the page for the selected verified row."""
        if not self.feedback:
            raise NavigationError("Visual feedback is not configured")
        _, channel = self.config.resolve_channel(requested_channel)
        nav = self.config.navigation
        network_page = channel.network_page or channel.name
        with self._cue_control():
            active = self.ecp.active_app()
            app_id = self._app_id()
            if active.id != app_id:
                raise NavigationError(
                    "YouTube TV must be active with the requested guide row selected"
                )
            guide = self.feedback.verify_selected(
                channel.name, configured_path=channel.template
            )

            focus = self._focus_network_tile()

            self.ecp.keypress("Select")
            self._sleep(self.config.feedback.network_page_settle_seconds)
            try:
                path = self.feedback.save_network_template(network_page)
                page = self.feedback.verify_network_page(
                    network_page, (channel.name, *channel.aliases)
                )
            finally:
                self.ecp.keypress("Back")
                self._sleep(nav.guide_settle_seconds)
                self._focus_current_program()

            final_guide = self.feedback.verify_selected(
                channel.name, configured_path=channel.template
            )
            return {
                "ok": True,
                "channel": channel.name,
                "network_page": network_page,
                "template_path": str(path),
                "guide_verification": guide,
                "network_focus": focus,
                "network_verification": page,
                "final_guide_verification": final_guide,
            }

    def status(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ready": False,
            "roku_url": self.ecp.base_url,
            "feedback_enabled": self.feedback is not None,
        }
        try:
            app_id, info = self._assert_ready()
            result.update(
                {
                    "ready": True,
                    "device": {
                        "name": info.get("user-device-name")
                        or info.get("friendly-device-name"),
                        "model": info.get("model-name"),
                        "model_number": info.get("model-number"),
                        "software_version": info.get("software-version"),
                        "ecp_setting_mode": info.get("ecp-setting-mode"),
                    },
                    "youtube_tv_app_id": app_id,
                    "active_app": self.ecp.active_app().__dict__,
                    "media_player": self.ecp.media_player(),
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "last_successful_cue": self.on_air_source(),
                    "current_channel": None,
                    "feedback": self.feedback.status() if self.feedback else None,
                    "tv_thing": self.feedback.status() if isinstance(self.feedback, TvThingFeedback) else None,
                }
            )
        except (EcpError, RokuNotReadyError, NavigationError) as exc:
            result["error"] = {
                "code": exc.code,
                "message": str(exc),
                "details": exc.details,
            }
        return result
