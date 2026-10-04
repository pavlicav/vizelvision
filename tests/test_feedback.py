import json
import io
import tempfile
import unittest
from unittest.mock import Mock
from pathlib import Path

from roku_stream.config import ChannelConfig, FeedbackConfig
from roku_stream.errors import NavigationError
from roku_stream.feedback import GrayTemplate, PpmFrame, TvThingFeedback
from roku_stream.states import AppState
from roku_stream.ocr import OcrObservation, OcrWord


class FeedbackTests(unittest.TestCase):
    def test_resume_banner_is_not_home_and_shifted_navigation_is_supported(self):
        width, height = 1280, 720
        feedback = TvThingFeedback(FeedbackConfig(base_url='http://tv.invalid', ocr_enabled=False))
        def picture(rectangle, red=False):
            rgb = bytearray([20] * width*height*3)
            x0, y0, x1, y1 = rectangle
            for y in range(y0, y1):
                rgb[(y*width+x0)*3:(y*width+x1)*3] = bytes([230]) * (x1-x0)*3
            if red:
                for y in range(94, 98):
                    rgb[(y*width+20)*3:(y*width+1250)*3] = bytes([255, 0, 70]) * 1230
            return PpmFrame(width, height, bytes(rgb))
        resume = picture((445, 29, 823, 83), red=True)
        self.assertTrue(feedback.assert_resume_banner(resume)['matched'])
        with self.assertRaises(NavigationError):
            feedback.assert_home_tab(resume)
        home = picture((586, 127, 684, 177), red=True)
        self.assertEqual(feedback.assert_home_tab(home)['navigation_offset'], .115)
        with self.assertRaises(NavigationError):
            feedback.assert_resume_banner(home)
        live = picture((704, 127, 787, 177), red=True)
        self.assertEqual(feedback.assert_live_tab(live)['navigation_offset'], .115)

    def test_home_recommendation_times_are_not_a_live_guide(self):
        feedback = TvThingFeedback(FeedbackConfig(base_url='http://tv.invalid', ocr_enabled=False))
        feedback.ocr = Mock()
        words = 'Library Live Top picks for you WILX 3:29 PM FOX 3:50 PM'.split()
        feedback.ocr.read.return_value = OcrObservation(tuple(
            OcrWord(value, 90, i*40, 0, 35, 20, 1, 1, 1) for i, value in enumerate(words)))
        screen = feedback.read_screen_text(PpmFrame(1, 1, b'abc'))
        self.assertEqual(screen['state'], 'youtube_tv_home_content')

    def test_720p_wrapped_header_moves_focus_row_and_logo_together(self):
        width, height = 1280, 720
        rgb = bytearray([25] * width * height * 3)
        for y in range(427, 491):
            rgb[(y*width+78)*3:(y*width+163)*3] = bytes([80]) * (163-78)*3
            start = (y*width+175)*3
            rgb[start:(y*width+435)*3] = bytes([230]) * (435-175)*3
        frame = PpmFrame(width, height, bytes(rgb))
        f = TvThingFeedback(FeedbackConfig(base_url='http://tv.invalid', ocr_enabled=False))
        top, bottom = f._selected_row_bounds(frame)
        self.assertTrue(423 <= top <= 427)
        self.assertTrue(491 <= bottom <= 495)
        self.assertTrue(f.assert_current_program_focus(frame)['matched'])

        # A similarly sized white promotional banner has no separate tile.
        for y in range(427, 491):
            rgb[(y*width+78)*3:(y*width+163)*3] = bytes([25]) * (163-78)*3
        with self.assertRaises(NavigationError):
            f._selected_row_bounds(PpmFrame(width, height, bytes(rgb)))

    def test_720p_dark_crops_require_wordmark_shape_agreement(self):
        with tempfile.TemporaryDirectory() as directory:
            f = TvThingFeedback(FeedbackConfig(base_url='http://tv.invalid',
                template_dir=Path(directory), ocr_enabled=False))
            raw = GrayTemplate(3, 2, (0, 0, 4, 0, 0, 4)).to_dict(channel='NBC', kind='guide_logo')
            raw['capture_format'] = '720p'
            path = Path(directory) / 'nbc.json'
            path.write_text(json.dumps(raw))
            with self.assertRaises(NavigationError):
                f._verify_template(GrayTemplate(3, 2, (4, 0, 0, 4, 0, 0)), path,
                                   expected_kind='guide_logo', channel='NBC', surface='guide row')

    def test_shared_pbs_logo_requires_whut_call_sign(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            f = TvThingFeedback(FeedbackConfig(base_url='http://tv.invalid',
                template_dir=Path(directory), ocr_enabled=False))
            (Path(directory) / 'pbs.json').write_text(json.dumps({'guide_identity_names': ['WHUT']}))
            f.ocr = Mock()
            observation = f.ocr.read.return_value
            observation.text = 'MPT • Finding Your Roots'
            observation.find_names.return_value = []
            frame = PpmFrame(1280, 720, bytes(1280*720*3))
            with self.assertRaises(NavigationError):
                f._verify_guide_identity('PBS', frame)
            observation.text = 'WHUT • Nature'
            observation.find_names.return_value = [{'name': 'WHUT'}]
            self.assertTrue(f._verify_guide_identity('PBS', frame)['matched'])

    def test_shared_pbs_logo_accepts_any_configured_market_call_sign(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            f = TvThingFeedback(FeedbackConfig(base_url='http://tv.invalid',
                template_dir=Path(directory), ocr_enabled=False))
            (Path(directory) / 'pbs.json').write_text(json.dumps({'guide_identity_names': ['WHUT', 'WKAR']}))
            f.ocr = Mock()
            observation = f.ocr.read.return_value
            observation.text = 'WKAR - Big Cats 24/7'
            observation.find_names.return_value = [{'name': 'WKAR'}]
            frame = PpmFrame(1280, 720, bytes(1280*720*3))
            self.assertTrue(f._verify_guide_identity('PBS', frame)['matched'])
            observation.find_names.assert_called_with(('WHUT', 'WKAR'))

    def test_bright_branded_station_tile_has_an_isolated_focus_border(self):
        width, height = 720, 480
        rgb = bytearray([25] * width * height * 3)
        for y in range(260, 304):
            for x in range(34, 83):
                border = x < 37 or x >= 80 or y < 263 or y >= 301
                color = (220, 220, 220) if border else (220, 170, 40)
                offset = (y * width + x) * 3
                rgb[offset:offset + 3] = bytes(color)
        feedback = TvThingFeedback(FeedbackConfig(base_url="http://tv.invalid", ocr_enabled=False))
        self.assertTrue(feedback.assert_network_tile_focus(PpmFrame(width, height, bytes(rgb)))["matched"])

    def test_bright_video_is_not_a_focused_station_border(self):
        feedback = TvThingFeedback(FeedbackConfig(base_url="http://tv.invalid", ocr_enabled=False))
        frame = PpmFrame(720, 480, bytes([190]) * 720 * 480 * 3)
        with self.assertRaises(NavigationError):
            feedback.assert_network_tile_focus(frame)

    def test_guide_logo_excludes_neighboring_program_highlight(self):
        width, height = 720, 480
        rgb = bytearray([70] * width * height * 3)
        feedback = TvThingFeedback(FeedbackConfig(base_url="http://tv.invalid", ocr_enabled=False))
        original = feedback._guide_logo_crop(PpmFrame(width, height, bytes(rgb)), 252, 300)
        for y in range(252, 304):
            for x in range(90, width):
                offset = (y * width + x) * 3
                rgb[offset:offset + 3] = bytes([220] * 3)
        changed = feedback._guide_logo_crop(PpmFrame(width, height, bytes(rgb)), 252, 300)
        self.assertEqual(original, changed)

    def test_nearly_ended_program_cell_can_still_be_focused(self):
        width, height = 720, 480
        rgb = bytearray([70] * width * height * 3)
        for y in range(260, 304):
            for x in range(91, 114):
                offset = (y * width + x) * 3
                rgb[offset:offset + 3] = bytes([220] * 3)
        feedback = TvThingFeedback(FeedbackConfig(base_url="http://tv.invalid", ocr_enabled=False))
        frame = PpmFrame(width, height, bytes(rgb))
        self.assertTrue(feedback.assert_current_program_focus(frame)["matched"])
        self.assertEqual(feedback._selected_row_bounds(frame), (252, 300))

    def test_dark_video_cannot_match_a_mostly_empty_network_logo(self):
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(FeedbackConfig(base_url="http://tv.invalid", template_dir=Path(directory), ocr_enabled=False))
            feedback._verify_template = lambda *args, **kwargs: {"matched": True, "difference": 4, "correlation": .04}
            frame = PpmFrame(720, 480, bytes([12]) * 720 * 480 * 3)
            with self.assertRaises(NavigationError):
                feedback.identify_network_page((ChannelConfig("NFL Network"),), frame)

    def test_source_switch_is_saved_and_reloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            config = FeedbackConfig(base_url="http://tv.invalid", ocr_enabled=False)
            feedback = TvThingFeedback(config, selection_path=path)
            feedback.source_catalog = lambda: {"sources": [{"key": "capture:dazzle", "name": "Dazzle", "source": "capture", "source_id": "capture:dazzle", "available": True}]}
            feedback._request_json = lambda *args, **kwargs: {"ok": True}
            feedback.status = lambda: {"mode": "capture", "capture": {"id": "capture:dazzle"}, "stream_ready": True, "quality": "high"}
            feedback.select_source("capture:dazzle")
            reloaded = TvThingFeedback(config, selection_path=path)
            reloaded.status = feedback.status
            self.assertEqual(reloaded.assert_ready()["capture"]["id"], "capture:dazzle")

    def test_station_focus_border_survives_direct_capture_offset(self):
        width, height = 720, 480
        rgb = bytearray([25] * width * height * 3)
        for y in range(260, 304):
            for x in range(34, 83):
                value = 220 if x < 37 or x >= 80 or y < 263 or y >= 301 else 25
                offset = (y * width + x) * 3
                rgb[offset:offset + 3] = bytes([value] * 3)
        feedback = TvThingFeedback(FeedbackConfig(base_url="http://tv.invalid", ocr_enabled=False))
        result = feedback.assert_network_tile_focus(PpmFrame(width, height, bytes(rgb)))
        self.assertTrue(result["matched"])
        self.assertEqual(result["evidence"], "observed_station_border")

    def test_capture_source_can_satisfy_readiness_gate(self) -> None:
        feedback = TvThingFeedback(
            FeedbackConfig(
                base_url="http://tv.invalid",
                required_source="capture",
                required_capture_id="capture:dazzle",
                ocr_enabled=False,
            )
        )
        feedback.status = lambda: {
            "mode": "capture",
            "capture": {"id": "capture:dazzle"},
            "stream_ready": True,
        }

        status = feedback.assert_ready()

        self.assertEqual(status["capture"]["id"], "capture:dazzle")

    def test_capture_source_rejects_a_different_device(self) -> None:
        feedback = TvThingFeedback(
            FeedbackConfig(
                base_url="http://tv.invalid",
                required_source="capture",
                required_capture_id="capture:dazzle",
                ocr_enabled=False,
            )
        )
        feedback.status = lambda: {
            "mode": "capture",
            "capture": {"id": "capture:hauppauge"},
            "stream_ready": True,
        }

        with self.assertRaises(NavigationError):
            feedback.assert_ready()

    def test_location_verification_precedes_network_page_templates(self) -> None:
        class LocationOcr:
            class Observation:
                text = "Location verification required"
                words = ()

                @staticmethod
                def contains_phrase(phrase):
                    return phrase.casefold() in "location verification required".casefold()

            def read(self, frame, *, crop=None, psm=11):
                return self.Observation()

        width, height = 720, 480
        pixels = bytearray([8, 8, 8] * width * height)
        for y in range(int(height * 0.70), int(height * 0.82)):
            for x in range(int(width * 0.36), int(width * 0.54)):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes((210, 210, 210))
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(
                FeedbackConfig(
                    base_url="http://tv.invalid",
                    template_dir=Path(directory),
                    ocr_enabled=False,
                )
            )
            feedback.ocr = LocationOcr()

            result = feedback.detect_youtube_tv_state(
                PpmFrame(width, height, bytes(pixels)), (), {"state": "close"}
            )

        self.assertEqual(result["state"], AppState.YOUTUBE_TV_LOCATION_VERIFICATION)
        self.assertEqual(result["selection"]["selected"], "verification")

    def test_mlb_grid_cursor_finds_white_selected_region(self) -> None:
        width, height = 300, 200
        pixels = bytearray([10, 10, 10] * width * height)
        x0, x1 = int(width * 0.358), int(width * 0.655)
        y0, y1 = int(height * 0.245), int(height * 0.680)
        for y in range(y0, y1):
            for x in range(x0, x1):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes((220, 220, 220))
        feedback = object.__new__(TvThingFeedback)

        result = feedback.mlb_grid_cursor(PpmFrame(width, height, bytes(pixels)))

        self.assertTrue(result["matched"])
        self.assertEqual(result["row"], 0)
        self.assertEqual(result["column"], 1)

    def test_mlb_home_cursor_follows_white_carousel_card(self) -> None:
        width, height = 300, 200
        pixels = bytearray([20, 20, 20] * width * height)
        x0, x1 = int(width * 0.670), int(width * 0.965)
        y0, y1 = int(height * 0.105), int(height * 0.515)
        for y in range(y0, y1):
            for x in range(x0, x1):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes((220, 220, 220))
        feedback = object.__new__(TvThingFeedback)

        result = feedback.mlb_home_lineup_cursor(
            PpmFrame(width, height, bytes(pixels))
        )

        self.assertTrue(result["matched"])
        self.assertEqual(result["column"], 2)

    def test_mlb_live_prompt_identifies_watch_live_focus(self) -> None:
        width, height = 300, 200
        pixels = bytearray([20, 20, 20] * width * height)
        x0, x1 = int(width * 0.34), int(width * 0.67)
        y0, y1 = int(height * 0.525), int(height * 0.600)
        for y in range(y0, y1):
            for x in range(x0, x1):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes((225, 225, 225))
        feedback = object.__new__(TvThingFeedback)

        result = feedback.mlb_live_prompt_selection(
            PpmFrame(width, height, bytes(pixels))
        )

        self.assertTrue(result["matched"])
        self.assertEqual(result["selected"], "watch_live")

    def test_mlb_games_tab_requires_bright_games_pill(self) -> None:
        width, height = 300, 200
        pixels = bytearray([10, 10, 10] * width * height)
        x0, x1 = int(width * 0.115), int(width * 0.195)
        y0, y1 = int(height * 0.045), int(height * 0.115)
        for y in range(y0, y1):
            for x in range(x0, x1):
                offset = (y * width + x) * 3
                pixels[offset : offset + 3] = bytes((210, 210, 210))
        feedback = object.__new__(TvThingFeedback)

        result = feedback.assert_mlb_games_tab_focus(
            PpmFrame(width, height, bytes(pixels))
        )

        self.assertTrue(result["matched"])

    def test_mlb_state_ignores_stale_other_app_player(self) -> None:
        feedback = object.__new__(TvThingFeedback)
        feedback.ocr = None
        frame = PpmFrame(30, 20, bytes([5, 5, 5] * 30 * 20))

        result = feedback.detect_mlb_state(
            frame,
            {"state": "play", "plugin": {"id": "195316", "name": "YouTube TV"}},
            "14",
        )

        self.assertEqual(result["state"], AppState.UNKNOWN)

    def test_join_live_prompt_requires_bright_default_choice(self) -> None:
        width, height = 720, 480
        rgb = bytearray(width * height * 3)

        def paint(x0, y0, x1, y1, value):
            for y in range(y0, y1):
                for x in range(x0, x1):
                    offset = (y * width + x) * 3
                    rgb[offset : offset + 3] = bytes((value, value, value))

        paint(
            int(width * 0.62),
            int(height * 0.165),
            int(width * 0.98),
            int(height * 0.255),
            210,
        )
        paint(
            int(width * 0.62),
            int(height * 0.275),
            int(width * 0.98),
            int(height * 0.335),
            35,
        )
        feedback = TvThingFeedback(
            FeedbackConfig(base_url="http://tv.invalid", template_dir=None)
        )

        result = feedback.assert_join_live_prompt(
            PpmFrame(width, height, bytes(rgb))
        )

        self.assertTrue(result["matched"])
        self.assertEqual(result["selected"], "join_live")

    def test_media_player_identifies_fullscreen_after_ui_surfaces_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(
                FeedbackConfig(
                    base_url="http://tv.invalid",
                    template_dir=Path(directory),
                    ocr_enabled=False,
                )
            )
            frame = PpmFrame(720, 480, bytes(720 * 480 * 3))

            result = feedback.detect_youtube_tv_state(
                frame, (), {"state": "play"}
            )

            self.assertEqual(result["state"], AppState.FULL_PROGRAM)
            self.assertEqual(result["evidence"], "roku_media_player")

    def test_live_guide_visual_takes_priority_over_background_playback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            feedback = TvThingFeedback(
                FeedbackConfig(
                    base_url="http://tv.invalid",
                    template_dir=Path(directory),
                    ocr_enabled=False,
                )
            )
            frame = PpmFrame(2, 2, bytes(12))

            def not_this_surface(frame=None, **_options):
                raise NavigationError("not this surface")

            feedback.verify_vivian_profile = not_this_surface
            feedback.assert_home_tab = not_this_surface
            feedback.selected_logo = lambda frame=None: GrayTemplate(1, 1, (0,))
            feedback._identify_guide_logo = lambda actual, channels, focus: {
                "channel": "NBC",
                "guide_index": 0,
                "verification": {"matched": True},
            }
            (Path(directory) / 'nbc.json').write_text(json.dumps(
                GrayTemplate(1, 1, (0,)).to_dict(channel='NBC')))

            result = feedback.detect_youtube_tv_state(
                frame, (), {"state": "play"}
            )

            self.assertEqual(result["state"], AppState.LIVE_GUIDE)
            self.assertEqual(result["channel"], "NBC")

    def test_mjpeg_output_is_split_across_arbitrary_chunks(self) -> None:
        class ChunkedStream(io.BytesIO):
            def read1(self, size=-1):
                return self.read(3)

        first = b"\xff\xd8one\xff\xd9"
        second = b"\xff\xd8two\xff\xd9"
        frames = list(
            TvThingFeedback._jpeg_frames(
                ChunkedStream(b"noise" + first + second)
            )
        )
        self.assertEqual(frames, [first, second])

    def test_ppm_parser_preserves_whitespace_valued_first_pixel(self) -> None:
        raster = bytes([32, 10, 9, 1, 2, 3])
        frame = PpmFrame.parse(b"P6\n2 1\n255\n" + raster)
        self.assertEqual(frame.width, 2)
        self.assertEqual(frame.height, 1)
        self.assertEqual(frame.rgb, raster)

    def test_selected_guide_row_is_found_and_downsampled(self) -> None:
        width, height = 720, 480
        rgb = bytearray([10] * width * height * 3)

        def paint(x0: int, y0: int, x1: int, y1: int, value: int) -> None:
            for y in range(y0, y1):
                for x in range(x0, x1):
                    offset = (y * width + x) * 3
                    rgb[offset : offset + 3] = bytes([value, value, value])

        paint(95, 250, 600, 295, 230)
        paint(40, 250, 95, 295, 210)
        paint(55, 260, 80, 285, 25)
        feedback = TvThingFeedback(
            FeedbackConfig(base_url="http://tv.invalid", template_dir=None)
        )
        template = feedback.selected_logo(PpmFrame(width, height, bytes(rgb)))
        self.assertEqual((template.width, template.height), (36, 24))
        self.assertLess(min(template.pixels), 80)
        self.assertGreater(max(template.pixels), 180)

    def test_direct_capture_guide_focus_uses_adjacent_row_contrast(self) -> None:
        width, height = 720, 480
        rgb = bytearray([20] * width * height * 3)

        for y in range(int(height * 0.525), int(height * 0.625)):
            for x in range(int(width * 0.145), int(width * 0.94)):
                offset = (y * width + x) * 3
                rgb[offset : offset + 3] = bytes((80, 80, 80))

        feedback = TvThingFeedback(
            FeedbackConfig(
                base_url="http://tv.invalid",
                template_dir=None,
                focus_luma_threshold=145,
            )
        )

        bounds = feedback._selected_row_bounds(
            PpmFrame(width, height, bytes(rgb))
        )

        self.assertEqual(bounds, (int(height * 0.525), int(height * 0.625)))

    def test_network_tile_requires_bright_focus_border(self) -> None:
        width, height = 720, 480
        rgb = bytearray([70] * width * height * 3)
        x0, x1 = int(width * 0.055), int(width * 0.125)
        y0, y1 = int(height * 0.529), int(height * 0.621)
        for y in range(y0, y1):
            for x in range(x0, x1):
                offset = (y * width + x) * 3
                border = x < x0 + 4 or x >= x1 - 4 or y < y0 + 4 or y >= y1 - 4
                value = 210 if border else 40
                rgb[offset : offset + 3] = bytes([value, value, value])
        feedback = TvThingFeedback(
            FeedbackConfig(base_url="http://tv.invalid", template_dir=None)
        )
        result = feedback.assert_network_tile_focus(
            PpmFrame(width, height, bytes(rgb))
        )
        self.assertTrue(result["matched"])

        neutral = PpmFrame(width, height, bytes([80] * width * height * 3))
        with self.assertRaises(NavigationError):
            feedback.assert_network_tile_focus(neutral)

    def test_closer_competitor_rejects_ambiguous_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates = Path(directory)
            target = GrayTemplate(2, 1, (0, 0))
            competitor = GrayTemplate(2, 1, (10, 10))
            (templates / "espn.json").write_text(
                json.dumps(target.to_dict(channel="ESPN")), encoding="utf-8"
            )
            (templates / "espn2.json").write_text(
                json.dumps(competitor.to_dict(channel="ESPN2")), encoding="utf-8"
            )
            feedback = TvThingFeedback(
                FeedbackConfig(
                    base_url="http://tv.invalid",
                    template_dir=templates,
                    template_difference_threshold=12,
                    template_margin=1.5,
                )
            )
            feedback.selected_logo = lambda frame=None: GrayTemplate(2, 1, (9, 9))
            with self.assertRaises(NavigationError) as caught:
                feedback.verify_selected("ESPN", frame=PpmFrame(1, 1, bytes(3)))
            result = caught.exception.details["visual_verification"]
            self.assertEqual(result["closest_competitor"]["channel"], "ESPN2")
            self.assertFalse(result["matched"])

    def test_guide_shape_correlation_survives_analog_brightness_shift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates = Path(directory)
            target = GrayTemplate(3, 2, (0, 0, 0, 255, 255, 255))
            competitor = GrayTemplate(3, 2, (50, 50, 90, 190, 190, 150))
            (templates / "wilx.json").write_text(
                json.dumps(target.to_dict(channel="WILX")), encoding="utf-8"
            )
            (templates / "espn2.json").write_text(
                json.dumps(competitor.to_dict(channel="ESPN2")), encoding="utf-8"
            )
            feedback = TvThingFeedback(
                FeedbackConfig(
                    base_url="http://tv.invalid",
                    template_dir=templates,
                    template_difference_threshold=12,
                    guide_correlation_threshold=0.9,
                    guide_correlation_margin=0.005,
                )
            )
            feedback.selected_logo = lambda frame=None: GrayTemplate(
                3, 2, (40, 40, 40, 200, 200, 200)
            )
            result = feedback.verify_selected("WILX", frame=PpmFrame(1, 1, bytes(3)))
            self.assertTrue(result["matched"])
            self.assertEqual(result["matched_by"], "correlation")

    def test_guide_calibration_preserves_distinct_analog_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates = Path(directory)
            feedback = TvThingFeedback(
                FeedbackConfig(
                    base_url="http://tv.invalid",
                    template_dir=templates,
                    template_difference_threshold=1,
                )
            )
            observations = iter(
                (
                    GrayTemplate(2, 2, (0, 20, 220, 255)),
                    GrayTemplate(2, 2, (30, 60, 170, 210)),
                )
            )
            feedback.selected_logo = lambda frame=None: next(observations)
            feedback.save_selected_template("WILX", frame=PpmFrame(1, 1, bytes(3)))
            feedback.save_selected_template("WILX", frame=PpmFrame(1, 1, bytes(3)))
            raw = json.loads((templates / "wilx.json").read_text(encoding="utf-8"))
            self.assertEqual(len(raw["variants"]), 1)
            actual = GrayTemplate(2, 2, (30, 60, 170, 210))
            result = feedback._verify_template(
                actual,
                templates / "wilx.json",
                expected_kind="guide_logo",
                channel="WILX",
                surface="guide row",
            )
            self.assertTrue(result["matched"])
            self.assertEqual(result["template_variants"], 2)

    def test_network_calibration_preserves_distinct_analog_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            templates = Path(directory)
            feedback = TvThingFeedback(
                FeedbackConfig(
                    base_url="http://tv.invalid",
                    template_dir=templates,
                )
            )
            observations = iter(
                (
                    GrayTemplate(2, 2, (0, 20, 220, 255)),
                    GrayTemplate(2, 2, (30, 60, 170, 210)),
                )
            )
            detail_observations = iter(
                (
                    GrayTemplate(2, 2, (0, 30, 210, 255)),
                    GrayTemplate(2, 2, (20, 70, 160, 220)),
                )
            )
            feedback.capture = lambda: object()
            feedback.network_page_logo = lambda frame=None: next(observations)
            feedback.network_page_detail_logo = (
                lambda frame=None: next(detail_observations)
            )
            feedback.save_network_template("ESPN")
            feedback.save_network_template("ESPN")
            raw = json.loads(
                (templates / "network-espn.json").read_text(encoding="utf-8")
            )
            self.assertEqual(raw["kind"], "network_logo")
            self.assertEqual(len(raw["variants"]), 1)


if __name__ == "__main__":
    unittest.main()
