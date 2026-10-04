import json
import tempfile
import unittest
from pathlib import Path

from roku_stream.config import load_config
from roku_stream.controller import RokuStreamController
from roku_stream.ecp import RokuApp
from roku_stream.errors import ControlBusyError, CueCancelledError, NavigationError
from roku_stream.states import AppState


class FakeEcp:
    base_url = "http://roku.test:8060"

    def __init__(self) -> None:
        self.keys: list[str] = []
        self.launches: list[str] = []

    def device_info(self):
        return {
            "ecp-setting-mode": "enabled",
            "model-name": "Roku Express+",
            "software-version": "15.3.4",
        }

    def apps(self):
        return [RokuApp("195316", "YouTube TV", "2")]

    def active_app(self):
        return RokuApp("195316", "YouTube TV", "2")

    def media_player(self):
        return {"state": "play", "plugin": {"id": "195316"}}

    def launch(self, app_id):
        self.launches.append(app_id)

    def keypress(self, key):
        self.keys.append(key)

    def wait_for_active_app(self, app_id, **kwargs):
        return RokuApp(app_id, "YouTube TV", "2")

    def wait_for_player(self, app_id, **kwargs):
        return {"state": "play", "plugin": {"id": app_id}}


class FakeFeedback:
    def __init__(self):
        self.focus_failures = 0
        self.states = [
            AppState.YOUTUBE_TV_HOME,
            AppState.LIVE_GUIDE,
            AppState.FULL_PROGRAM,
        ]

    def assert_ready(self):
        return {"mode": "cable", "cable_channel": 69, "stream_ready": True}

    def capture(self):
        return object()

    def detect_youtube_tv_state(self, frame, channels, media_player):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        result = {"state": state, "evidence": "test"}
        if state == AppState.YOUTUBE_TV_USER_SELECT:
            result["profile_verified"] = True
        if state == AppState.YOUTUBE_TV_LOCATION_VERIFICATION:
            result["selection"] = {"selected": "verification"}
        if state == AppState.LIVE_GUIDE:
            result.update({"channel": "ESPN", "guide_index": 2})
        return result

    def identify_selected(self, channels, frame=None):
        return {
            "matched": True,
            "channel": "ESPN",
            "guide_index": 2,
            "verification": {"matched": True},
        }

    def assert_home_tab(self, frame=None):
        return {"matched": True}

    def verify_vivian_profile(self, frame=None):
        raise NavigationError("not profile")

    def verify_selected(self, channel, *, configured_path=None):
        return {"matched": True, "difference": 3.0}

    def selected_logo(self, frame=None):
        return object()

    def network_template_path(self, channel):
        class ExistingTemplate:
            def is_file(self):
                return True

            def __str__(self):
                return f"/tmp/network-{channel}.json"

        return ExistingTemplate()

    def verify_network_page(self, channel, aliases=()):
        return {"matched": True, "visual": {"matched": True}, "ocr": None}

    def assert_network_tile_focus(self, frame=None):
        if self.focus_failures:
            self.focus_failures -= 1
            raise NavigationError("focus not ready")
        return {"matched": True}

    def assert_current_program_focus(self, frame=None):
        return {"matched": True}

    def template_path(self, channel, configured=None):
        return Path("/tmp") / f"{channel}.json"

    def status(self):
        return self.assert_ready()


class ControllerTests(unittest.TestCase):
    def test_bad_network_page_does_not_scan_away_from_verified_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            feedback = FakeFeedback()
            config = self.config(Path(directory))
            controller = RokuStreamController(config, ecp=ecp, feedback=feedback, sleeper=lambda _: None)
            def reject_page(*args):
                raise NavigationError("stale page template")
            feedback.verify_network_page = reject_page
            with self.assertRaisesRegex(NavigationError, "page calibration"):
                controller._open_channel_row(config.resolve_channel("ESPN")[1], [],
                    guide_observation={"channel": "ESPN", "guide_index": 2})
            self.assertEqual(ecp.keys, ["Left", "Select", "Back"])

    def test_guide_scan_reverses_after_observed_overshoot(self):
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            feedback = FakeFeedback()
            config = self.config(Path(directory), channels=[
                {"name": "NBC", "guide_index": 0},
                {"name": "ESPN", "guide_index": 2},
                {"name": "FOX", "guide_index": 4},
            ])
            controller = RokuStreamController(config, ecp=ecp, feedback=feedback, sleeper=lambda _: None)
            feedback.identify_selected = lambda channels: {"channel": "NBC", "guide_index": 0}
            def verify(channel, *, configured_path=None):
                if "Down" not in ecp.keys:
                    raise NavigationError("overshot onto NBC")
                return {"matched": True}
            feedback.verify_selected = verify
            result = controller._open_channel_row(config.resolve_channel("ESPN")[1], [],
                guide_observation={"channel": "FOX", "guide_index": 4})
            self.assertTrue(result["matched"])
            self.assertEqual(ecp.keys[:3], ["Up", "Up", "Down"])

    def test_second_cue_is_rejected_without_sending_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            controller = RokuStreamController(self.config(Path(directory)), ecp=ecp, feedback=FakeFeedback(), sleeper=lambda _: None)
            with controller._lock:
                with self.assertRaises(ControlBusyError):
                    controller.play("ESPN")
            self.assertEqual(ecp.keys, [])

    def test_operator_can_stop_cue_during_navigation(self):
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            controller = RokuStreamController(self.config(Path(directory)), ecp=ecp, feedback=FakeFeedback(), sleeper=lambda _: None)
            def stop_after_key(key):
                ecp.keys.append(key)
                controller.cancel_operation()
            ecp.keypress = stop_after_key
            with self.assertRaises(CueCancelledError):
                controller.play("ESPN")
            self.assertFalse(controller.operation_status()["active"])
            self.assertEqual(controller.operation_status()["phase"], "cancelled")
            self.assertNotIn("Select", ecp.keys)
            self.assertTrue(controller._lock.acquire(blocking=False))
            controller._lock.release()

    def config(self, root: Path, channels=None):
        path = root / "config.json"
        path.write_text(
            json.dumps(
                {
                    "roku": {"url": "http://roku.test:8060", "app_id": "195316"},
                    "feedback": {
                        "base_url": "http://tv.test:8080",
                        "ocr_enabled": False
                    },
                    "navigation": {
                        "key_delay_seconds": 0,
                        "guide_settle_seconds": 0,
                        "play_settle_seconds": 0,
                    },
                    "channels": channels or [{"name": "ESPN", "guide_index": 2}],
                }
            ),
            encoding="utf-8",
        )
        return load_config(path)

    def test_play_verifies_before_final_select(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=FakeFeedback(),
                sleeper=lambda _: None,
            )
            result = controller.play("espn")
            self.assertTrue(result["ok"])
            operation = controller.operation_status()
            self.assertFalse(operation["active"])
            self.assertEqual(operation["phase"], "complete")
            self.assertEqual(operation["app_state"], AppState.FULL_PROGRAM)
            self.assertEqual(
                ecp.keys,
                [
                    "Right",
                    "Select",
                    "Down",
                    "Down",
                    "Left",
                    "Select",
                    "Back",
                    "Select",
                ],
            )
            self.assertTrue(result["verification"]["visible_channel_template"]["matched"])

    def test_location_verification_is_confirmed_before_guide_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            feedback = FakeFeedback()
            feedback.states = [
                AppState.YOUTUBE_TV_LOCATION_VERIFICATION,
                AppState.LIVE_GUIDE,
                AppState.FULL_PROGRAM,
            ]
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=feedback,
                sleeper=lambda _: None,
            )

            result = controller.play("ESPN")

            self.assertTrue(result["ok"])
            self.assertEqual(ecp.keys[0], "Select")
            first_state = next(
                event
                for event in result["events"]
                if event["event"] == "state_detected"
            )
            self.assertEqual(
                first_state["state"],
                AppState.YOUTUBE_TV_LOCATION_VERIFICATION,
            )

    def test_non_unique_guide_logo_is_not_used_as_relative_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            feedback = FakeFeedback()
            observations = {"count": 0}

            def detect(frame, channels, media_player):
                observations["count"] += 1
                if observations["count"] > 1:
                    return {"state": AppState.FULL_PROGRAM, "evidence": "test"}
                return {
                    "state": AppState.LIVE_GUIDE,
                    "evidence": "test",
                    "channel": "PBS",
                    "guide_index": 4,
                }

            feedback.detect_youtube_tv_state = detect
            anchor_checks = {"count": 0}

            def verify_selected(channel, *, configured_path=None):
                if channel == "NBC":
                    anchor_checks["count"] += 1
                    if anchor_checks["count"] <= 4:
                        raise NavigationError("not at the top anchor yet")
                return {"matched": True, "difference": 0.0}

            feedback.verify_selected = verify_selected
            config = self.config(
                Path(directory),
                channels=[
                    {"name": "NBC", "guide_index": 0},
                    {
                        "name": "PBS",
                        "guide_index": 4,
                        "anchor_safe": False,
                    },
                    {"name": "ESPN", "guide_index": 8},
                ],
            )
            controller = RokuStreamController(
                config,
                ecp=ecp,
                feedback=feedback,
                sleeper=lambda _: None,
            )

            result = controller.play("ESPN")

            self.assertTrue(result["ok"])
            self.assertEqual(ecp.keys[:4], ["Up"] * 4)
            self.assertEqual(ecp.keys[4:12], ["Down"] * 8)

    def test_dropped_left_is_detected_before_network_select(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            feedback = FakeFeedback()
            feedback.focus_failures = 1
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=feedback,
                sleeper=lambda _: None,
            )
            result = controller.play("espn")
            self.assertTrue(result["ok"])
            self.assertEqual(
                ecp.keys,
                [
                    "Right",
                    "Select",
                    "Down",
                    "Down",
                    "Left",
                    "Left",
                    "Select",
                    "Back",
                    "Select",
                ],
            )

    def test_play_from_existing_live_guide_does_not_relaunch_or_reopen_live(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            feedback = FakeFeedback()
            feedback.states = [AppState.LIVE_GUIDE, AppState.FULL_PROGRAM]
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=feedback,
                sleeper=lambda _: None,
            )

            result = controller.play("ESPN")

            self.assertTrue(result["ok"])
            self.assertEqual(ecp.launches, [])
            self.assertEqual(ecp.keys, ["Left", "Select", "Back", "Select"])

    def test_existing_guide_moves_up_from_the_identified_current_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            feedback = FakeFeedback()
            feedback.states = [AppState.LIVE_GUIDE, AppState.FULL_PROGRAM]
            observations = {"count": 0}

            def detect(frame, channels, media_player):
                observations["count"] += 1
                if observations["count"] > 1:
                    return {
                        "state": AppState.FULL_PROGRAM,
                        "evidence": "test",
                    }
                return {
                    "state": AppState.LIVE_GUIDE,
                    "evidence": "test",
                    "channel": "TBS",
                    "guide_index": 13,
                }

            feedback.detect_youtube_tv_state = detect
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=feedback,
                sleeper=lambda _: None,
            )

            result = controller.play("ESPN")

            self.assertTrue(result["ok"])
            self.assertEqual(ecp.keys[:11], ["Up"] * 11)
            self.assertEqual(ecp.keys[11:], ["Left", "Select", "Back", "Select"])

    def test_play_accepts_join_live_prompt_before_waiting_for_player(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            class JoinLiveEcp(FakeEcp):
                def __init__(self):
                    super().__init__()
                    self.selects = 0

                def keypress(self, key):
                    super().keypress(key)
                    if key == "Select":
                        self.selects += 1

                def media_player(self):
                    state = "play" if self.selects >= 4 else "none"
                    return {"state": state, "plugin": {"id": "195316"}}

            class JoinLiveFeedback(FakeFeedback):
                def __init__(self, ecp):
                    super().__init__()
                    self.ecp = ecp

                def detect_youtube_tv_state(self, frame, channels, media_player):
                    if self.ecp.selects == 3:
                        return {
                            "state": AppState.JOIN_LIVE_OR_START_FROM_BEGINNING,
                            "evidence": "test",
                        }
                    return super().detect_youtube_tv_state(
                        frame, channels, media_player
                    )

            ecp = JoinLiveEcp()
            feedback = JoinLiveFeedback(ecp)
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=feedback,
                sleeper=lambda _: None,
            )

            result = controller.play("ESPN")

            self.assertTrue(result["ok"])
            self.assertEqual(ecp.keys[-2:], ["Select", "Select"])
            self.assertTrue(
                any(event.get("action") == "join_live" for event in result["events"])
            )

    def test_play_confirms_location_verification_during_playback_wait(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ecp = FakeEcp()
            feedback = FakeFeedback()
            feedback.states = [
                AppState.LIVE_GUIDE,
                AppState.YOUTUBE_TV_LOCATION_VERIFICATION,
                AppState.FULL_PROGRAM,
            ]
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=feedback,
                sleeper=lambda _: None,
            )

            result = controller.play("ESPN")

            self.assertTrue(result["ok"])
            actions = [
                event.get("action")
                for event in result["events"]
                if event["event"] == "state_action"
            ]
            self.assertIn("confirm_location_verification", actions)

    def test_mlb_wait_moves_from_catch_up_to_watch_live_before_select(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            class MlbEcp(FakeEcp):
                def active_app(self):
                    return RokuApp("14", "MLB", "9")

                def media_player(self):
                    # A stream may still report play behind MLB's prompt.
                    return {"state": "play", "plugin": {"id": "14"}}

            class MlbFeedback(FakeFeedback):
                def __init__(self):
                    super().__init__()
                    self.observations = [
                        {
                            "state": AppState.JOIN_LIVE_OR_START_FROM_BEGINNING,
                            "selection": {"matched": True, "selected": "catch_up"},
                        },
                        {
                            "state": AppState.JOIN_LIVE_OR_START_FROM_BEGINNING,
                            "selection": {"matched": True, "selected": "watch_live"},
                        },
                        {"state": AppState.FULL_PROGRAM},
                    ]

                def detect_mlb_state(self, frame, media_player, app_id):
                    return self.observations.pop(0) if len(self.observations) > 1 else self.observations[0]

            ecp = MlbEcp()
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=MlbFeedback(),
                sleeper=lambda _: None,
            )
            events = []

            result = controller._wait_for_mlb_playback("14", events)

            self.assertEqual(result["state"], "play")
            self.assertEqual(ecp.keys, ["Down", "Select"])
            self.assertEqual(
                [event["action"] for event in events if event["event"] == "keypress"],
                ["focus_mlb_watch_live", "mlb_join_live"],
            )

    def test_each_known_state_has_a_bounded_route_to_live_guide(self) -> None:
        transitions = (
            (AppState.YOUTUBE_TV_USER_SELECT, ["Select"]),
            (AppState.YOUTUBE_TV_HOME, ["Right", "Select", "Down", "Down"]),
            (AppState.FULL_PROGRAM, ["Back"]),
            (AppState.CHANNEL_DESCRIPTION, ["Back"]),
        )
        with tempfile.TemporaryDirectory() as directory:
            for starting_state, expected_keys in transitions:
                with self.subTest(starting_state=starting_state):
                    ecp = FakeEcp()
                    feedback = FakeFeedback()
                    feedback.states = (
                        [starting_state, starting_state, AppState.LIVE_GUIDE]
                        if starting_state == AppState.CHANNEL_DESCRIPTION
                        else [starting_state, AppState.LIVE_GUIDE]
                    )
                    controller = RokuStreamController(
                        self.config(Path(directory)),
                        ecp=ecp,
                        feedback=feedback,
                        sleeper=lambda _: None,
                    )
                    events = []

                    observed = controller._drive_to_live_guide("195316", events)

                    self.assertEqual(observed["state"], AppState.LIVE_GUIDE)
                    self.assertEqual(ecp.keys, expected_keys)

    def test_roku_home_launches_youtube_tv_before_observing_its_screen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            class HomeEcp(FakeEcp):
                launched = False

                def active_app(self):
                    if not self.launched:
                        return RokuApp(None, "Roku", None)
                    return super().active_app()

                def launch(self, app_id):
                    super().launch(app_id)
                    self.launched = True

            ecp = HomeEcp()
            feedback = FakeFeedback()
            feedback.states = [AppState.LIVE_GUIDE]
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=feedback,
                sleeper=lambda _: None,
            )
            events = []

            observed = controller._drive_to_live_guide("195316", events)

            self.assertEqual(observed["state"], AppState.LIVE_GUIDE)
            self.assertEqual(ecp.launches, ["195316"])

    def test_existing_exit_dialog_is_confirmed_without_canceling_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            screen = {"value": "dialog"}

            class DialogEcp(FakeEcp):
                def active_app(self):
                    if screen["value"] == "roku_home":
                        return RokuApp(None, "Roku", None)
                    return RokuApp("195316", "YouTube TV", "2")

                def keypress(self, key):
                    self.keys.append(key)
                    if screen["value"] == "dialog" and key == "Select":
                        screen["value"] = "roku_home"

                def launch(self, app_id):
                    self.launches.append(app_id)
                    screen["value"] = "youtube_home"

            class DialogFeedback(FakeFeedback):
                def assert_home_tab(self, frame=None):
                    if screen["value"] == "youtube_home":
                        return {"matched": True}
                    raise NavigationError("not home")

                def assert_exit_dialog(self, frame=None):
                    if screen["value"] == "dialog":
                        return {"matched": True}
                    raise NavigationError("not dialog")

            ecp = DialogEcp()
            controller = RokuStreamController(
                self.config(Path(directory)),
                ecp=ecp,
                feedback=DialogFeedback(),
                sleeper=lambda _: None,
            )
            events = []
            controller._clean_launch("195316", events)
            self.assertEqual(ecp.keys, ["Select"])
            self.assertEqual(ecp.launches, ["195316"])
            self.assertTrue(
                any(event.get("initial") is True for event in events)
            )


if __name__ == "__main__":
    unittest.main()
