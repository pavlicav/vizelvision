from __future__ import annotations

import json
import math
import re
import subprocess
import time
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .config import ChannelConfig, FeedbackConfig, normalize_channel_name
from .errors import NavigationError
from .ocr import LocalOcr
from .states import AppState


@dataclass(frozen=True)
class GrayTemplate:
    width: int
    height: int
    pixels: tuple[int, ...]

    def difference(self, other: "GrayTemplate") -> float:
        if self.width != other.width or self.height != other.height:
            return 255.0
        if not self.pixels:
            return 255.0
        return sum(abs(a - b) for a, b in zip(self.pixels, other.pixels)) / len(
            self.pixels
        )

    def correlation(self, other: "GrayTemplate") -> float:
        """Compare shape while ignoring global brightness and contrast."""
        if self.width != other.width or self.height != other.height:
            return -1.0
        if not self.pixels:
            return -1.0
        self_mean = sum(self.pixels) / len(self.pixels)
        other_mean = sum(other.pixels) / len(other.pixels)
        numerator = sum(
            (left - self_mean) * (right - other_mean)
            for left, right in zip(self.pixels, other.pixels)
        )
        self_energy = sum((value - self_mean) ** 2 for value in self.pixels)
        other_energy = sum((value - other_mean) ** 2 for value in other.pixels)
        denominator = (self_energy * other_energy) ** 0.5
        return numerator / denominator if denominator else -1.0

    def contrast_normalized(self) -> "GrayTemplate":
        """Normalize analog brightness while retaining the logo's shape."""
        if not self.pixels:
            return self
        ordered = sorted(self.pixels)
        low = ordered[int((len(ordered) - 1) * 0.05)]
        high = ordered[int((len(ordered) - 1) * 0.95)]
        if high <= low:
            return self
        pixels = tuple(
            max(0, min(255, (value - low) * 255 // (high - low)))
            for value in self.pixels
        )
        return GrayTemplate(self.width, self.height, pixels)

    def to_dict(self, *, channel: str, kind: str = "guide_logo") -> dict[str, object]:
        return {
            "channel": channel,
            "kind": kind,
            "width": self.width,
            "height": self.height,
            "pixels": list(self.pixels),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "GrayTemplate":
        try:
            width = int(data["width"])
            height = int(data["height"])
            pixels_raw = data["pixels"]
            if not isinstance(pixels_raw, list):
                raise ValueError("pixels is not an array")
            pixels = tuple(int(value) for value in pixels_raw)
        except (KeyError, TypeError, ValueError) as exc:
            raise NavigationError(f"Invalid channel template: {exc}") from exc
        if width < 1 or height < 1 or len(pixels) != width * height:
            raise NavigationError("Invalid channel template dimensions")
        return cls(width, height, pixels)


@dataclass(frozen=True)
class PpmFrame:
    width: int
    height: int
    rgb: bytes

    @classmethod
    def parse(cls, payload: bytes) -> "PpmFrame":
        # ffmpeg's ppm encoder emits a simple binary P6 image. Comments are
        # accepted so this parser remains valid for other PPM producers.
        tokens: list[bytes] = []
        position = 0
        while len(tokens) < 4:
            while position < len(payload) and payload[position] in b" \t\r\n":
                position += 1
            if position < len(payload) and payload[position] == ord("#"):
                newline = payload.find(b"\n", position)
                if newline < 0:
                    break
                position = newline + 1
                continue
            end = position
            while end < len(payload) and payload[end] not in b" \t\r\n":
                end += 1
            tokens.append(payload[position:end])
            position = end
        if len(tokens) != 4 or tokens[0] != b"P6" or tokens[3] != b"255":
            raise NavigationError("TV Thing frame is not an 8-bit binary PPM image")
        if payload[position : position + 2] == b"\r\n":
            position += 2
        elif position < len(payload) and payload[position] in b" \t\r\n":
            position += 1
        width, height = int(tokens[1]), int(tokens[2])
        rgb = payload[position:]
        expected = width * height * 3
        if len(rgb) < expected:
            raise NavigationError(
                f"TV Thing frame is truncated ({len(rgb)} bytes, expected {expected})"
            )
        return cls(width, height, rgb[:expected])

    def luma(self, x: int, y: int) -> int:
        offset = (y * self.width + x) * 3
        red, green, blue = self.rgb[offset : offset + 3]
        return (77 * red + 150 * green + 29 * blue) >> 8

    def mean_luma(self, x0: int, y0: int, x1: int, y1: int) -> float:
        total = 0
        count = 0
        for y in range(max(0, y0), min(self.height, y1)):
            for x in range(max(0, x0), min(self.width, x1)):
                total += self.luma(x, y)
                count += 1
        return total / count if count else 0.0

    def mean_rgb(
        self, x0: int, y0: int, x1: int, y1: int
    ) -> tuple[float, float, float]:
        red_total = green_total = blue_total = count = 0
        for y in range(max(0, y0), min(self.height, y1)):
            for x in range(max(0, x0), min(self.width, x1)):
                offset = (y * self.width + x) * 3
                red, green, blue = self.rgb[offset : offset + 3]
                red_total += red
                green_total += green
                blue_total += blue
                count += 1
        if not count:
            return 0.0, 0.0, 0.0
        return red_total / count, green_total / count, blue_total / count


class VisualFeedback:
    """Screen recognition shared by direct and HTTP capture backends."""

    def __init__(self, config: FeedbackConfig) -> None:
        self.config = config
        self.last_frame: PpmFrame | None = None
        self.last_capture: dict[str, object] | None = None
        self.on_capture = None
        self.wait = time.sleep
        self.ocr = (
            LocalOcr(
                executable=config.tesseract_path,
                scale=config.ocr_scale,
                min_confidence=config.ocr_min_confidence,
                timeout=config.ocr_timeout_seconds,
            )
            if config.ocr_enabled
            else None
        )

    @staticmethod
    def _has_guide_station_tile(frame: PpmFrame, top: int, bottom: int) -> bool:
        """Require the separate, inset station tile beside a program highlight."""
        ys = (top + 9, bottom - 9)
        corners = [frame.mean_luma(int(frame.width*x), y, int(frame.width*x)+3, y+3)
                   for x in (.066, .121) for y in ys]
        surrounds = [frame.mean_luma(int(frame.width*x), y, int(frame.width*x)+3, y+3)
                     for x in (.056, .132) for y in ys]
        return min(corners) >= 35 and max(corners)-min(corners) <= 35 and min(corners)-max(surrounds) >= 12

    @staticmethod
    def _guide_row_geometry(frame: PpmFrame) -> tuple[int, int]:
        """Find the filled row when a wrapped program header shifts the grid."""
        if frame.width >= 1280 and frame.width / frame.height >= 1.7:
            runs = []
            start = None
            bottom = int(frame.height * .83)
            for y in range(int(frame.height * .48), bottom + 1):
                bright = y < bottom and any(
                    frame.mean_luma(x, y, x + int(frame.width * .025), y + 1) >= 170
                    for x in range(int(frame.width*.14), int(frame.width*.91), max(8, frame.width//30)))
                if bright and start is None:
                    start = y
                elif not bright and start is not None:
                    if (frame.height*.07 <= y-start <= frame.height*.105
                            and VisualFeedback._has_guide_station_tile(frame, start-3, y+4)):
                        runs.append((start-3, y+4))
                    start = None
            if len(runs) == 1:
                return runs[0]
        return int(frame.height*.525), int(frame.height*.625)

    @staticmethod
    def _program_focus_runs(frame: PpmFrame) -> list[tuple[int, int]]:
        """Find filled program highlights, including nearly-ended tiny cells."""
        row_start, row_end = VisualFeedback._guide_row_geometry(frame)
        y0, y1 = row_start + int(frame.height*.02), row_end - int(frame.height*.01)
        runs = []
        start = None
        left, right = int(frame.width * .125), int(frame.width * .94)
        for x in range(left, right + 1):
            bright = x < right and frame.mean_luma(x, y0, x + 1, y1) >= 160
            if bright and start is None:
                start = x
            elif not bright and start is not None:
                if x - start >= max(6, frame.width // 120):
                    runs.append((start, x))
                start = None
        return runs

    def _selected_row_bounds(self, frame: PpmFrame) -> tuple[int, int]:
        # Wrapped program headers move the focus row. Follow its highlight
        # and require the separate station tile to exclude promotional banners.
        row_start, row_end = self._guide_row_geometry(frame)
        if frame.width >= 1280 and not self._has_guide_station_tile(frame, row_start, row_end):
            raise NavigationError('No separate guide station tile beside the program highlight')
        sample_start = int(frame.width * 0.145)
        sample_end = int(frame.width * 0.94)
        window = max(20, frame.width // 12)
        step = max(8, window // 3)
        peak = max(
            frame.mean_luma(x, row_start, min(sample_end, x + window), row_end)
            for x in range(sample_start, sample_end - window + 1, step)
        )
        comparison_start = row_start + int(frame.height*.115)
        comparison_end = min(frame.height, row_end + int(frame.height*.115))
        comparison_peak = max(
            frame.mean_luma(
                x, comparison_start, min(sample_end, x + window), comparison_end
            )
            for x in range(sample_start, sample_end - window + 1, step)
        )
        # Direct composite capture is substantially darker than the modulated
        # RF return. Accept its focus fill by contrast with the next guide row,
        # while retaining the absolute threshold for legacy channel 69.
        contrast_focus = peak >= 55 and peak - comparison_peak >= 15
        if peak < self.config.focus_luma_threshold and not contrast_focus and not self._program_focus_runs(frame):
            raise NavigationError(
                "The Roku return feed does not show a selected YouTube TV guide row",
                details={
                    "focused_row_peak_luma": round(peak, 2),
                    "adjacent_row_peak_luma": round(comparison_peak, 2),
                },
            )
        return row_start, row_end

    def _guide_logo_crop(
        self, frame: PpmFrame, row_start: int, row_end: int
    ) -> GrayTemplate:
        crop_x0 = int(frame.width * 0.05)
        # The program highlight begins around x=.125 on direct capture.
        # Including its white edge overwhelms the tiny station wordmarks and
        # makes unrelated networks correlate almost perfectly.
        crop_x1 = int(frame.width * 0.115)
        if frame.width >= 1280 and frame.width / frame.height >= 1.7:
            # Component 720p places the station tile at x=.061..127. Keep
            # the crop inside its edges so background/borders cannot dominate
            # the station wordmark when comparing unrelated channels.
            crop_x0 = int(frame.width * .069)
            crop_x1 = int(frame.width * .120)
        # Avoid the focus border while retaining the complete small logo.
        crop_y0 = row_start + max(2, (row_end - row_start) // 12)
        crop_y1 = row_end - max(2, (row_end - row_start) // 12)
        return self._downsample(
            frame,
            crop_x0,
            crop_y0,
            crop_x1,
            crop_y1,
            width=36,
            height=24,
            normalize=True,
        )

    def selected_logo(self, frame: PpmFrame | None = None) -> GrayTemplate:
        frame = frame or self.capture()
        row_start, row_end = self._selected_row_bounds(frame)
        return self._guide_logo_crop(frame, row_start, row_end)

    def assert_exit_dialog(self, frame: PpmFrame | None = None) -> dict[str, object]:
        """Verify the static YouTube TV exit confirmation before pressing OK."""
        frame = frame or self.capture()
        selected_button = frame.mean_luma(
            int(frame.width * 0.415),
            int(frame.height * 0.565),
            int(frame.width * 0.49),
            int(frame.height * 0.65),
        )
        surrounding_background = frame.mean_luma(
            0,
            0,
            int(frame.width * 0.25),
            int(frame.height * 0.25),
        )
        title_band = frame.mean_luma(
            int(frame.width * 0.36),
            int(frame.height * 0.35),
            int(frame.width * 0.67),
            int(frame.height * 0.44),
        )
        matched = (
            selected_button >= 125
            and surrounding_background <= 35
            and title_band >= 12
        )
        result = {
            "matched": matched,
            "selected_button_luma": round(selected_button, 2),
            "background_luma": round(surrounding_background, 2),
            "title_band_luma": round(title_band, 2),
        }
        if not matched:
            raise NavigationError(
                "The Roku return feed does not show the expected YouTube TV exit confirmation; "
                "refusing to press Select",
                details={"exit_dialog_verification": result},
            )
        return result

    def assert_home_tab(self, frame: PpmFrame | None = None) -> dict[str, object]:
        """Verify that YouTube TV's top Home tab is the current focus anchor."""
        frame = frame or self.capture()
        for offset in (0., .115):
            def region(left, right, top=.035, bottom=.125):
                return frame.mean_luma(int(frame.width*left), int(frame.height*(top+offset)),
                                       int(frame.width*right), int(frame.height*(bottom+offset)))
            pill = region(.46, .55)
            left, right = region(.405, .445), region(.56, .60)
            background = region(.10, .26, .025, .13)
            # The resume banner above the navigation is much wider than Home.
            # Require dark sides so it cannot masquerade as a focused Home tab.
            if pill >= 105 and background <= 65 and max(left, right) < 90 and pill-max(left, right) > 50:
                return {'matched': True, 'home_pill_luma': round(pill, 2),
                        'top_left_background_luma': round(background, 2), 'navigation_offset': offset}
        raise NavigationError('The Roku return feed does not show the YouTube TV Home tab focus anchor')

    def assert_resume_banner(self, frame: PpmFrame) -> dict[str, object]:
        """Recognize the wide focused return-to-playback button above the tabs."""
        regions = ((.36, .40), (.46, .54), (.59, .63))
        brightness = [frame.mean_luma(int(frame.width*l), int(frame.height*.045),
                                      int(frame.width*r), int(frame.height*.105)) for l, r in regions]
        red_fraction = 0.
        for y in range(int(frame.height*.12), int(frame.height*.145), max(1, frame.height//360)):
            pixels = [frame.rgb[(y*frame.width+x)*3:(y*frame.width+x)*3+3]
                      for x in range(int(frame.width*.1), int(frame.width*.9), max(1, frame.width//64))]
            red_fraction = max(red_fraction, sum(r > 100 and r > g*1.4 and r > b*1.1
                                                 for r, g, b in pixels) / max(1, len(pixels)))
        if min(brightness) < 140 or red_fraction < .7:
            raise NavigationError('The return-to-playback banner is not focused')
        return {'matched': True, 'red_progress_fraction': round(red_fraction, 3)}

    def assert_live_tab(self, frame: PpmFrame | None = None) -> dict[str, object]:
        """Recognize the focused Live navigation pill above the guide shelves."""
        frame = frame or self.capture()
        for offset in (0., .115):
            pill = frame.mean_luma(int(frame.width * .552), int(frame.height * (.067+offset)),
                                   int(frame.width * .607), int(frame.height * (.116+offset)))
            background = frame.mean_luma(int(frame.width * .53), int(frame.height * (.14+offset)),
                                         int(frame.width * .63), int(frame.height * (.19+offset)))
            home = frame.mean_luma(int(frame.width * .46), int(frame.height * (.067+offset)),
                                   int(frame.width * .52), int(frame.height * (.116+offset)))
            if pill >= 160 and background < 65 and home < 90:
                return {'matched': True, 'live_pill_luma': round(pill, 2),
                        'background_luma': round(background, 2), 'navigation_offset': offset}
        raise NavigationError('The Live navigation tab is not visibly focused')

    def location_verification_selection(
        self, frame: PpmFrame | None = None
    ) -> dict[str, object]:
        """Identify the focused button on YouTube TV's location modal."""
        frame = frame or self.capture()
        verification_luma = frame.mean_luma(
            int(frame.width * 0.36),
            int(frame.height * 0.70),
            int(frame.width * 0.54),
            int(frame.height * 0.82),
        )
        dismiss_luma = frame.mean_luma(
            int(frame.width * 0.53),
            int(frame.height * 0.70),
            int(frame.width * 0.67),
            int(frame.height * 0.82),
        )
        contrast = verification_luma - dismiss_luma
        selected = (
            "verification"
            if verification_luma >= 90 and contrast >= 45
            else "dismiss"
            if dismiss_luma >= 90 and contrast <= -45
            else None
        )
        return {
            "matched": selected is not None,
            "selected": selected,
            "verification_luma": round(verification_luma, 2),
            "dismiss_luma": round(dismiss_luma, 2),
            "contrast": round(contrast, 2),
        }

    def assert_network_tile_focus(
        self, frame: PpmFrame | None = None
    ) -> dict[str, object]:
        """Require YouTube TV's bright focus border on the guide network tile."""
        frame = frame or self.capture()
        x0 = int(frame.width * 0.055)
        x1 = int(frame.width * 0.125)
        y0 = int(frame.height * 0.529)
        y1 = int(frame.height * 0.621)
        thickness = max(2, frame.width // 180)
        borders = (
            frame.mean_luma(x0, y0, x0 + thickness, y1),
            frame.mean_luma(x1 - thickness, y0, x1, y1),
            frame.mean_luma(x0, y0, x1, y0 + thickness),
            frame.mean_luma(x0, y1 - thickness, x1, y1),
        )
        score = sum(borders) / len(borders)
        # The narrow vertical edges are heavily blurred by the analog path.
        # Requiring both of them to remain present plus a strong four-edge
        # average still separates this rectangle from an unfocused tile.
        interior = frame.mean_luma(x0 + thickness + 2, y0 + thickness + 2,
                                   x1 - thickness - 2, y1 - thickness - 2)
        matched = score >= 125 and min(borders) >= 75 and score - interior >= 45
        # Composite capture moves the image a few pixels relative to RF.
        # Locate a complete bright rectangle in the station column instead of
        # assuming that its four edges fall on the old absolute coordinates.
        if not matched:
            left, right = int(frame.width * .035), int(frame.width * .14)
            segments = []
            for y in range(int(frame.height * .50), int(frame.height * .80)):
                start = None
                for x in range(left, right + 1):
                    bright = x < right and frame.luma(x, y) >= 145
                    if bright and start is None:
                        start = x
                    elif not bright and start is not None:
                        if frame.width * .045 <= x - start <= frame.width * .095:
                            segments.append((start, x, y))
                        start = None
            for lx, rx, top in segments:
                for bx, br, bottom in segments:
                    if abs(lx - bx) > 3 or abs(rx - br) > 3 or not frame.height * .075 <= bottom - top <= frame.height * .11:
                        continue
                    edges = (
                        frame.mean_luma(lx, top, lx + 2, bottom),
                        frame.mean_luma(rx - 2, top, rx, bottom),
                        frame.mean_luma(lx, top, rx, top + 2),
                        frame.mean_luma(lx, bottom - 1, rx, bottom + 1),
                    )
                    inside = frame.mean_luma(lx + 5, top + 5, rx - 5, bottom - 5)
                    # Some focused stations (ABC, for example) fill the tile
                    # with a bright brand color. Their white border contrasts
                    # with the surrounding grid, not the tile's interior.
                    outside = (
                        frame.mean_luma(lx - 5, top, lx - 2, bottom),
                        frame.mean_luma(rx + 2, top, rx + 5, bottom),
                        frame.mean_luma(lx, top - 5, rx, top - 2),
                        frame.mean_luma(lx, bottom + 2, rx, bottom + 5),
                    )
                    border_score = sum(edges) / 4
                    outlined = border_score - inside >= 65
                    isolated = min(edge - surround for edge, surround in zip(edges, outside)) >= 65
                    if min(edges) >= 100 and (outlined or isolated):
                        return {"matched": True, "border_luma": [round(v, 2) for v in edges], "border_score": round(sum(edges) / 4, 2), "bounds": [lx, top, rx, bottom], "evidence": "observed_station_border"}
        result = {
            "matched": matched,
            "border_luma": [round(value, 2) for value in borders],
            "border_score": round(score, 2),
        }
        if not matched:
            raise NavigationError(
                "The guide network tile is not visibly focused; refusing to press Select",
                details={"network_tile_focus": result},
            )
        return result

    def assert_current_program_focus(
        self, frame: PpmFrame | None = None
    ) -> dict[str, object]:
        """Require focus on the first/current program cell, not a future cell."""
        frame = frame or self.capture()
        row_start, row_end = self._guide_row_geometry(frame)
        luma = frame.mean_luma(
            int(frame.width * 0.145),
            row_start + int(frame.height * .01),
            int(frame.width * 0.215),
            row_end - int(frame.height * .01),
        )
        runs = self._program_focus_runs(frame)
        matched = luma >= self.config.focus_luma_threshold or any(start <= frame.width * .16 for start, _ in runs)
        result = {"matched": matched, "current_program_luma": round(luma, 2)}
        if not matched:
            raise NavigationError(
                "The guide's current program cell is not visibly focused",
                details={"current_program_focus": result},
            )
        return result

    def assert_join_live_prompt(
        self, frame: PpmFrame | None = None
    ) -> dict[str, object]:
        """Verify the playback-choice panel with Join live selected."""
        frame = frame or self.capture()
        join_live_luma = frame.mean_luma(
            int(frame.width * 0.62),
            int(frame.height * 0.165),
            int(frame.width * 0.98),
            int(frame.height * 0.255),
        )
        start_beginning_luma = frame.mean_luma(
            int(frame.width * 0.62),
            int(frame.height * 0.275),
            int(frame.width * 0.98),
            int(frame.height * 0.335),
        )
        contrast = join_live_luma - start_beginning_luma
        matched = (
            join_live_luma >= 140
            and start_beginning_luma <= 80
            and contrast >= 80
        )
        result = {
            "matched": matched,
            "selected": "join_live",
            "join_live_luma": round(join_live_luma, 2),
            "start_from_beginning_luma": round(start_beginning_luma, 2),
            "contrast": round(contrast, 2),
        }
        if not matched:
            raise NavigationError(
                "Channel 69 does not show Join live as the selected playback choice",
                details={"join_live_prompt": result},
            )
        return result

    @staticmethod
    def _downsample(
        frame: PpmFrame,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        *,
        width: int,
        height: int,
        normalize: bool = False,
    ) -> GrayTemplate:
        low = 0
        high = 255
        if normalize:
            source_values = sorted(
                frame.luma(x, y)
                for y in range(max(0, y0), min(frame.height, y1))
                for x in range(max(0, x0), min(frame.width, x1))
            )
            if source_values:
                low = source_values[int((len(source_values) - 1) * 0.01)]
                high = source_values[int((len(source_values) - 1) * 0.99)]

        def adjusted(value: int) -> int:
            if not normalize or high <= low:
                return value
            return max(0, min(255, (value - low) * 255 // (high - low)))

        pixels: list[int] = []
        for out_y in range(height):
            source_y0 = y0 + (y1 - y0) * out_y // height
            source_y1 = y0 + (y1 - y0) * (out_y + 1) // height
            source_y1 = max(source_y0 + 1, source_y1)
            for out_x in range(width):
                source_x0 = x0 + (x1 - x0) * out_x // width
                source_x1 = x0 + (x1 - x0) * (out_x + 1) // width
                source_x1 = max(source_x0 + 1, source_x1)
                total = 0
                count = 0
                for source_y in range(source_y0, source_y1):
                    for source_x in range(source_x0, source_x1):
                        total += adjusted(frame.luma(source_x, source_y))
                        count += 1
                pixels.append(total // count)
        return GrayTemplate(width, height, tuple(pixels))

    def template_path(self, channel: str, configured: str | None = None) -> Path:
        assert self.config.template_dir is not None
        if configured:
            path = Path(configured)
            if not path.is_absolute():
                path = self.config.template_dir / path
            return path
        return self.config.template_dir / f"{normalize_channel_name(channel)}.json"

    def network_template_path(self, channel: str) -> Path:
        assert self.config.template_dir is not None
        return self.config.template_dir / (
            f"network-{normalize_channel_name(channel)}.json"
        )

    def network_detail_template_path(self, channel: str) -> Path:
        assert self.config.template_dir is not None
        return self.config.template_dir / (
            f"network-detail-{normalize_channel_name(channel)}.json"
        )

    def profile_template_path(self) -> Path:
        assert self.config.template_dir is not None
        path = Path(self.config.profile_template)
        if not path.is_absolute():
            path = self.config.template_dir / path
        return path

    @staticmethod
    def _profile_box(frame: PpmFrame) -> tuple[int, int, int, int]:
        return (int(frame.width * 0.13), int(frame.height * 0.37),
                int(frame.width * 0.28), int(frame.height * 0.70))

    def selected_first_profile(self, frame: PpmFrame | None = None) -> GrayTemplate:
        frame = frame or self.capture()
        # Includes Vivian's avatar, selected ring, and label, at the position
        # used for calibration. Comparing all of it detects focus moving away.
        return self._downsample(frame, *self._profile_box(frame), width=40, height=40)

    def _search_profile(
        self, frame: PpmFrame, templates: tuple[GrayTemplate, ...]
    ) -> tuple[float, int]:
        """Best match for the calibrated tile anywhere in the chooser's left part.

        YouTube TV centers the profile row, so adding or removing a family
        member moves the tiles sideways. The tile, including its focus ring,
        is matched at every horizontal offset; an unfocused Vivian tile still
        fails. Prefix sums give exactly the averages `_downsample` computes.
        """
        box_x0, y0, box_x1, y1 = self._profile_box(frame)
        crop, size = box_x1 - box_x0, 40
        limit = min(int(frame.width * 0.45), frame.width - crop)
        span = limit + crop
        rows = []
        for out_y in range(size):
            source_y0 = y0 + (y1 - y0) * out_y // size
            source_y1 = max(source_y0 + 1, y0 + (y1 - y0) * (out_y + 1) // size)
            sums = [0] * span
            for y in range(source_y0, source_y1):
                row = frame.rgb[y * frame.width * 3:(y * frame.width + span) * 3]
                for x, (red, green, blue) in enumerate(zip(row[0::3], row[1::3], row[2::3])):
                    sums[x] += (77 * red + 150 * green + 29 * blue) >> 8
            prefix = [0]
            for value in sums:
                prefix.append(prefix[-1] + value)
            rows.append((prefix, source_y1 - source_y0))
        columns = []
        for out_x in range(size):
            start = crop * out_x // size
            columns.append((start, max(start + 1, crop * (out_x + 1) // size)))

        def score(x0: int) -> float:
            pixels = tuple((prefix[x0 + end] - prefix[x0 + start]) // (height * (end - start))
                           for prefix, height in rows for start, end in columns)
            actual = GrayTemplate(size, size, pixels)
            return min(expected.difference(actual) for expected in templates)

        coarse = min((score(x0), x0) for x0 in range(0, limit + 1, 8))
        return min((score(x0), x0) for x0 in range(max(0, coarse[1] - 8), min(limit, coarse[1] + 8) + 1))

    def save_profile_template(self, profile: str = "Vivian") -> Path:
        template = self.selected_first_profile()
        path = self.profile_template_path()
        return self._save_observation_template(template, path, channel=profile, kind="profile")

    def verify_vivian_profile(
        self, frame: PpmFrame | None = None, *, search: bool = True
    ) -> dict[str, object]:
        path = self.profile_template_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise NavigationError(
                "Vivian profile template has not been calibrated",
                details={"template_path": str(path)},
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise NavigationError(f"Cannot read profile template {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise NavigationError(f"Profile template {path} is not a JSON object")
        frame = frame or self.capture()
        templates = self._template_variants(raw)
        actual = self.selected_first_profile(frame)
        difference = min(expected.difference(actual) for expected in templates)
        position = self._profile_box(frame)[0]
        if difference > self.config.template_difference_threshold and search:
            difference, position = min((difference, position), self._search_profile(frame, templates))
        matched = difference <= self.config.template_difference_threshold
        result = {
            "matched": matched,
            "profile": "Vivian",
            "difference": round(difference, 3),
            "position": round(position / frame.width, 3),
            "threshold": self.config.template_difference_threshold,
            "template_path": str(path),
        }
        if not matched:
            raise NavigationError(
                "The selected YouTube TV profile is not the calibrated Vivian profile; "
                "refusing to continue",
                details={"profile_verification": result},
            )
        return result

    def read_guide_header(self, frame: PpmFrame | None = None) -> dict[str, object]:
        """OCR the Live guide's header for the focused row.

        For a Sunday Ticket game the header shows the matchup in large type
        ("Chicago Bears at Carolina Panthers") and a detail line such as
        "Sun, Sep 13, 1:00 PM • NFL ST • FOX". Rows are temporary and carry no
        calibrated logo, so this text is their only identity.
        """
        if self.ocr is None:
            raise NavigationError("Local OCR is disabled")
        frame = frame or self.capture()
        crop = (int(frame.width * 0.03), int(frame.height * 0.05),
                int(frame.width * 0.68), int(frame.height * 0.36))
        observation = self.ocr.read(frame, crop=crop, psm=6)
        text = observation.text
        compact = normalize_channel_name(text)
        return {
            "text": text,
            # Tesseract reads the small "NFL ST" as "NEL ST" at 720p.
            "sunday_ticket": bool(re.search(r"\bN[FE][LI1]\s*ST\b", text)) or "sundayticket" in compact,
            # "In 6 days", "In 2 hours", "Starts in 5 min": not playable yet.
            "upcoming": bool(re.search(r"\b(?:starts\s+)?in\s+\d+\s*(?:day|hour|hr|min)", text, re.IGNORECASE)),
        }

    def read_guide_row(self, frame: PpmFrame | None = None) -> dict[str, object]:
        """OCR the focused program cell, e.g. "Upcoming: Chicago Bears at Carolina Panthers"."""
        if self.ocr is None:
            raise NavigationError("Local OCR is disabled")
        frame = frame or self.capture()
        top, bottom = self._selected_row_bounds(frame)
        text = self.ocr.read(frame, crop=(int(frame.width * 0.125), top, frame.width, bottom), psm=7).text
        return {"text": text, "upcoming": "upcoming" in text.casefold()}

    def sunday_ticket_template_path(self) -> Path:
        assert self.config.template_dir is not None
        return self.config.template_dir / "sunday-ticket.json"

    def save_sunday_ticket_template(self) -> Path:
        """Calibrate the logo shared by every Sunday Ticket guide row (focus one first)."""
        return self._save_observation_template(self.selected_logo(), self.sunday_ticket_template_path(),
                                               channel="Sunday Ticket", kind="guide_logo")

    def sunday_ticket_logo(self, frame: PpmFrame) -> dict[str, object] | None:
        """Compare the focused row's logo with the Sunday Ticket template, if calibrated."""
        path = self.sunday_ticket_template_path()
        if not path.is_file():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        actual = self.selected_logo(frame)
        difference = min(expected.difference(actual) for expected in self._template_variants(raw))
        return {"matched": difference <= self.config.template_difference_threshold,
                "difference": round(difference, 3)}

    @staticmethod
    def match_nfl_game(texts: list[str], game: dict[str, object]) -> dict[str, object]:
        """Both teams of `game` must appear in the OCR text, by full name or nickname."""
        compact = normalize_channel_name(" ".join(texts))
        teams = {}
        for side in ("away", "home"):
            team = game.get(side) or {}
            names = [str(team.get(key)) for key in ("name", "nickname") if team.get(key)]
            teams[side] = next((name for name in names if normalize_channel_name(name) in compact), None)
        return {"matched": all(teams.values()), "teams": teams}

    def read_screen_text(self, frame: PpmFrame | None = None) -> dict[str, object]:
        if self.ocr is None:
            raise NavigationError("Local OCR is disabled")
        frame = frame or self.capture()
        observation = self.ocr.read(frame, psm=11)
        state = "unknown"
        if observation.contains_phrase("Location verification required") or (
            observation.contains_phrase("location")
            and observation.contains_phrase("verification")
            and observation.contains_phrase("required")
        ):
            state = "location_verification"
        elif observation.contains_phrase("Who's watching"):
            state = "profile_chooser"
        elif observation.contains_phrase("Exit YouTube TV"):
            state = "exit_dialog"
        elif observation.contains_phrase('Top picks for you'):
            # Home recommendations contain broadcast times too. They are not
            # a guide grid, even when OCR misses one of the navigation labels.
            state = 'youtube_tv_home_content'
        elif all(
            observation.contains_phrase(value)
            for value in ("Library", "Home", "Live")
        ):
            state = "youtube_tv_navigation"
        elif len(
            re.findall(
                r"\b\d{1,2}\s*:\s*\d{2}\s*(?:AM|PM)\b",
                observation.text,
                flags=re.IGNORECASE,
            )
        ) >= 2:
            state = "live_guide"
        return {
            "state": state,
            "text": observation.text,
            "word_count": len(observation.words),
        }

    def mlb_grid_cursor(self, frame: PpmFrame | None = None) -> dict[str, object]:
        """Locate MLB's white selected game card using normalized grid regions."""
        frame = frame or self.capture()
        columns = ((0.045, 0.345), (0.358, 0.655), (0.670, 0.965))
        rows = ((0.245, 0.680), (0.700, 0.995))
        candidates: list[dict[str, object]] = []
        for row, (top, bottom) in enumerate(rows):
            for column, (left, right) in enumerate(columns):
                bounds = (
                    int(frame.width * left),
                    int(frame.height * top),
                    int(frame.width * right),
                    int(frame.height * bottom),
                )
                inset_x = max(2, int(frame.width * 0.012))
                inset_y = max(2, int(frame.height * 0.018))
                score = frame.mean_luma(
                    bounds[0] + inset_x,
                    bounds[1] + inset_y,
                    bounds[2] - inset_x,
                    bounds[3] - inset_y,
                )
                candidates.append(
                    {
                        "row": row,
                        "column": column,
                        "bounds": list(bounds),
                        "mean_luma": round(score, 2),
                    }
                )
        ranked = sorted(candidates, key=lambda item: float(item["mean_luma"]), reverse=True)
        best = ranked[0]
        runner_up = ranked[1]
        margin = float(best["mean_luma"]) - float(runner_up["mean_luma"])
        matched = float(best["mean_luma"]) >= 55 and margin >= 18
        result = {
            **best,
            "matched": matched,
            "margin": round(margin, 2),
            "candidates": candidates,
        }
        if not matched:
            raise NavigationError(
                "The MLB game-grid cursor is not confidently visible",
                details={"mlb_grid_cursor": result},
            )
        return result

    def assert_mlb_games_tab_focus(
        self, frame: PpmFrame | None = None
    ) -> dict[str, object]:
        """Require MLB's bright Games header pill before Select is allowed."""
        frame = frame or self.capture()
        regions = {
            "home": (0.045, 0.058, 0.108, 0.113),
            "games": (0.115, 0.058, 0.195, 0.113),
            "shows": (0.200, 0.058, 0.265, 0.113),
        }
        scores: dict[str, float] = {}
        for name, (left, top, right, bottom) in regions.items():
            scores[name] = frame.mean_luma(
                int(frame.width * left),
                int(frame.height * top),
                int(frame.width * right),
                int(frame.height * bottom),
            )
        competitor = max(scores["home"], scores["shows"])
        margin = scores["games"] - competitor
        matched = scores["games"] >= 20 and margin >= 12
        result = {
            "matched": matched,
            "scores": {name: round(value, 2) for name, value in scores.items()},
            "margin": round(margin, 2),
        }
        if not matched:
            raise NavigationError(
                "MLB's Games tab is not visibly focused",
                details={"mlb_games_tab_focus": result},
            )
        return result

    def verify_mlb_selected_game(
        self,
        away_names: tuple[str, ...],
        home_names: tuple[str, ...],
        frame: PpmFrame | None = None,
    ) -> dict[str, object]:
        """OCR only the white MLB cursor card and require both teams."""
        if self.ocr is None:
            raise NavigationError("Local OCR is required for MLB game selection")
        frame = frame or self.capture()
        cursor = self.mlb_grid_cursor(frame)
        bounds = tuple(int(value) for value in cursor["bounds"])
        observation = self.ocr.read(frame, crop=bounds, psm=11)
        away_matches = observation.find_names(away_names)
        home_matches = observation.find_names(home_names)
        matched = bool(away_matches and home_matches)
        # Grid cards put a small red LIVE badge above the team logos. OCR
        # often loses that label and reads an inning such as BOT 7 as BOT?.
        x0, x1 = bounds[0] + int(frame.width * .025), bounds[0] + int(frame.width * .055)
        y0, y1 = bounds[1] + int(frame.height * .045), bounds[1] + int(frame.height * .075)
        colors = [frame.rgb[(y * frame.width + x) * 3:(y * frame.width + x) * 3 + 3]
                  for y in range(y0, min(y1, frame.height)) for x in range(x0, min(x1, frame.width))]
        red_fraction = sum(r >= 85 and r - g >= 30 and r - b >= 30 for r, g, b in colors) / max(1, len(colors))
        return {
            "matched": matched,
            "cursor": cursor,
            "away_matches": away_matches,
            "home_matches": home_matches,
            "ocr_text": observation.text,
            "live": observation.contains_phrase("Live") or bool(re.search(r"\b(?:top|bot|bottom|mid|end)\s*\d", observation.text, re.I)) or red_fraction >= .3,
            "live_badge_red_fraction": round(red_fraction, 3),
        }

    def mlb_home_lineup_cursor(
        self, frame: PpmFrame | None = None
    ) -> dict[str, object]:
        """Locate the white card in MLB Home's three-slot lineup carousel."""
        frame = frame or self.capture()
        columns = ((0.045, 0.345), (0.358, 0.655), (0.670, 0.965))
        top, bottom = 0.105, 0.515
        candidates: list[dict[str, object]] = []
        for column, (left, right) in enumerate(columns):
            bounds = (
                int(frame.width * left),
                int(frame.height * top),
                int(frame.width * right),
                int(frame.height * bottom),
            )
            score = frame.mean_luma(
                bounds[0] + int(frame.width * 0.012),
                bounds[1] + int(frame.height * 0.018),
                bounds[2] - int(frame.width * 0.012),
                bounds[3] - int(frame.height * 0.018),
            )
            candidates.append(
                {
                    "column": column,
                    "bounds": list(bounds),
                    "mean_luma": round(score, 2),
                }
            )
        ranked = sorted(
            candidates, key=lambda item: float(item["mean_luma"]), reverse=True
        )
        best, runner_up = ranked[:2]
        margin = float(best["mean_luma"]) - float(runner_up["mean_luma"])
        matched = float(best["mean_luma"]) >= 105 and margin >= 18
        # A focused card has dark gutters on both sides. Broadcast graphics
        # can be bright in the same region but extend through those gutters.
        x0, y0, x1, y1 = best["bounds"]
        y0 += int(frame.height * .11)
        y1 -= int(frame.height * .02)
        sides = (
            (x0 + int(frame.width * .007), x0 + int(frame.width * .012),
             x0 - int(frame.width * .017), x0 - int(frame.width * .01)),
            (x1 - int(frame.width * .016), x1 - int(frame.width * .012),
             x1 + int(frame.width * .005), x1 + int(frame.width * .01)),
        )
        side_contrasts = [frame.mean_luma(a, y0, max(a + 1, b), y1)
                          - frame.mean_luma(c, y0, max(c + 1, d), y1)
                          for a, b, c, d in sides]
        matched = matched and min(side_contrasts) >= 30
        result = {
            **best,
            "matched": matched,
            "side_contrasts": [round(value, 2) for value in side_contrasts],
            "margin": round(margin, 2),
            "candidates": candidates,
        }
        if not matched:
            raise NavigationError(
                "MLB's selected Today’s Lineup card is not visible",
                details={"mlb_home_lineup_cursor": result},
            )
        return result

    def verify_mlb_home_lineup_game(
        self,
        away_names: tuple[str, ...],
        home_names: tuple[str, ...],
        frame: PpmFrame | None = None,
    ) -> dict[str, object]:
        if self.ocr is None:
            raise NavigationError("Local OCR is required for MLB game selection")
        frame = frame or self.capture()
        cursor = self.mlb_home_lineup_cursor(frame)
        bounds = tuple(int(value) for value in cursor["bounds"])
        observation = self.ocr.read(frame, crop=bounds, psm=11)
        away_matches = observation.find_names(away_names)
        home_matches = observation.find_names(home_names)
        # The tiny LIVE label is often unreadable at 480i. Its red badge is
        # separate from the team logos and future start-time badges are white.
        x0 = bounds[0] + int(frame.width * .01)
        x1 = bounds[0] + int(frame.width * .04)
        y0 = bounds[1] + int(frame.height * .07)
        y1 = bounds[1] + int(frame.height * .10)
        colors = [frame.rgb[(y * frame.width + x) * 3:(y * frame.width + x) * 3 + 3]
                  for y in range(y0, min(y1, frame.height)) for x in range(x0, min(x1, frame.width))]
        red_fraction = sum(r >= 85 and r - g >= 30 and r - b >= 30 for r, g, b in colors) / max(1, len(colors))
        return {
            "matched": bool(away_matches and home_matches),
            "cursor": cursor,
            "away_matches": away_matches,
            "home_matches": home_matches,
            "ocr_text": observation.text,
            "live": observation.contains_phrase("Live") or red_fraction >= .3,
            "live_badge_red_fraction": round(red_fraction, 3),
        }

    def mlb_feed_picker_selection(self, frame: PpmFrame) -> dict[str, object]:
        """Locate outlined video/audio pills in MLB's observed feed layouts."""
        drift = max(1, int(frame.height * .007))
        inset = max(2, int(frame.width * .022))

        def button(kind, column, left, right, top, bottom):
            x0, x1 = int(left * frame.width), int(right * frame.width)
            y0, y1 = int(top * frame.height), int(bottom * frame.height)
            edges = [max(frame.mean_luma(x0 + inset, y, x1 - inset, y + 1)
                         for y in range(v - drift, v + drift + 1)) for v in (y0, y1)]
            padding = max(2, int(frame.height * .0125))
            score = frame.mean_luma(x0 + inset, y0 + padding, x1 - inset, y1 - padding)
            return {"kind": kind, "column": column, "score": round(score, 2), "edges": edges}

        # Composite and HD captures have different picture margins; scaling
        # the composite coordinates alone misses the HD button outlines.
        layouts = (
            ("composite", ((.331, .488), (.502, .659)),
             (.486, .542), (.625, .681), (.706, .763), None),
            ("hd", ((.335, .487), (.499, .651)),
             (.470, .523), (.605, .658), (.680, .733), None),
            # Completed games can retain a live postgame broadcast while
            # adding a focused Condensed Game button above the video row.
            ("hd-condensed", ((.335, .487), (.499, .651)),
             (.508, .561), (.642, .695), (.718, .770), (.382, .436)),
        )
        attempts = []
        for name, columns, video_row, audio_row, extra_audio_row, condensed_row in layouts:
            # A continuous outline across the column gap identifies one wide
            # video button. Two-feed dialogs have background in that gap.
            center = int(frame.width * (columns[0][1] + columns[1][0]) / 2)
            seam_edges = [max(frame.mean_luma(center - 2, y, center + 3, y + 1)
                              for y in range(int(v * frame.height) - drift, int(v * frame.height) + drift + 1))
                          for v in video_row]
            video_columns = ((columns[0][0], columns[-1][1]),) if min(seam_edges) >= 140 else columns
            buttons = [button("video", column, left, right, *video_row)
                       for column, (left, right) in enumerate(video_columns)]
            # Both first-row audio pills are present in the supported layouts.
            buttons += [button("audio", column, left, right, *audio_row)
                        for column, (left, right) in enumerate(columns)]
            if condensed_row:
                buttons.append(button("condensed", 0, *columns[0], *condensed_row))
            attempts.append({"layout": name, "buttons": buttons})
            if min(edge for item in buttons for edge in item["edges"]) < 140:
                continue
            for column, (left, right) in enumerate(columns):
                candidate = button("audio", column, left, right, *extra_audio_row)
                if min(candidate["edges"]) >= 140:
                    buttons.append(candidate)
            ranked = sorted(buttons, key=lambda item: item["score"], reverse=True)
            best, runner_up = ranked[:2]
            if best["score"] >= 130 and best["score"] - runner_up["score"] >= 50:
                return {"matched": True, "selected": best["kind"], "column": best["column"],
                        "layout": name, "buttons": buttons}
        raise NavigationError("MLB's feed button outlines and focus were not clearly located",
                              details={"layouts": attempts})

    def mlb_live_prompt_selection(
        self, frame: PpmFrame | None = None, *, require_outline: bool = False
    ) -> dict[str, object]:
        """Identify live choices, including the extra Resume row on re-entry."""
        frame = frame or self.capture()
        layouts = (
            # 720p re-entry dialog: four rows are more tightly spaced than
            # the older Resume layout. Require every outline before selecting.
            (("catch_up", 185, 215), ("resume", 233, 262), ("watch_live", 280, 309), ("start_from_beginning", 327, 356)),
            (("catch_up", 213, 242), ("watch_live", 261, 291), ("start_from_beginning", 311, 341)),
            (("catch_up", 188, 218), ("resume", 237, 267), ("watch_live", 286, 316), ("start_from_beginning", 335, 365)),
            # Postgame streams omit Catch Up and Resume in the HD dialog.
            (("watch_live", 233, 263), ("start_from_beginning", 279, 310)),
            # HD re-entry without Catch Up: Resume opens focused (filled).
            (("resume", 209, 238), ("watch_live", 256, 285), ("start_from_beginning", 303, 332)),
        )
        x0, x1 = int(frame.width * .355), int(frame.width * .64)
        drift = max(1, int(frame.height * .007))
        for layout in layouts:
            buttons = []
            for name, top, bottom in layout:
                y0, y1 = int(top * frame.height / 480), int(bottom * frame.height / 480)
                edges = [max(frame.mean_luma(x0, y, x1, y + 1)
                             for y in range(v - drift, v + drift + 1)) for v in (y0, y1)]
                inset = max(2, int(frame.height * .015))
                buttons.append({"name": name, "edges": edges,
                                "score": frame.mean_luma(x0, y0 + inset, x1, y1 - inset)})
            if min(edge for button in buttons for edge in button["edges"]) < 140:
                continue
            ranked = sorted(buttons, key=lambda item: item["score"], reverse=True)
            margin = ranked[0]["score"] - ranked[1]["score"]
            if ranked[0]["score"] >= 130 and margin >= 60:
                return {"matched": True, "selected": ranked[0]["name"], "button_count": len(buttons),
                        "scores": {button["name"]: round(button["score"], 2) for button in buttons},
                        "margin": round(margin, 2)}
        if require_outline:
            raise NavigationError("MLB's live-choice button outlines were not located")

        # OCR can independently establish the older three-choice dialog;
        # retain its focus-only check for that path.
        regions = {
            "catch_up": (0.34, 0.425, 0.67, 0.495),
            "watch_live": (0.34, 0.525, 0.67, 0.600),
            "start_from_beginning": (0.34, 0.630, 0.67, 0.705),
        }
        scores = {
            name: frame.mean_luma(
                int(frame.width * left),
                int(frame.height * top),
                int(frame.width * right),
                int(frame.height * bottom),
            )
            for name, (left, top, right, bottom) in regions.items()
        }
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        selected, best_score = ranked[0]
        margin = best_score - ranked[1][1]
        matched = best_score >= 120 and margin >= 60
        result = {
            "matched": matched,
            "selected": selected if matched else None,
            "scores": {name: round(value, 2) for name, value in scores.items()},
            "margin": round(margin, 2),
        }
        if not matched:
            raise NavigationError(
                "MLB's selected live-playback choice is not confidently visible",
                details={"mlb_live_prompt": result},
            )
        return result

    def detect_mlb_state(
        self,
        frame: PpmFrame,
        media_player: dict[str, object],
        app_id: str | None = None,
    ) -> dict[str, object]:
        """Classify the MLB surfaces needed by the baseball cue workflow."""
        player_state = str(media_player.get("state", "")).casefold()
        plugin = media_player.get("plugin")
        plugin_id = plugin.get("id") if isinstance(plugin, dict) else None
        plugin_name = plugin.get("name") if isinstance(plugin, dict) else None
        is_mlb_player = (
            (app_id is not None and plugin_id == app_id)
            or str(plugin_name or "").casefold() == "mlb"
        )
        text = None
        if self.ocr is not None:
            try:
                observation = self.ocr.read(frame, psm=11)
                text = observation.text
                if observation.contains_phrase("Thank You for Watching"):
                    return {"state": AppState.MLB_BROADCAST_ENDED, "evidence": "ocr", "ocr_text": text}
                if observation.contains_phrase("problem communicating with MLB"):
                    return {"state": AppState.MLB_ERROR, "evidence": "ocr", "ocr_text": text}
                if observation.contains_phrase("Entitlement Required") or observation.contains_phrase("Upgrade Plan"):
                    return {"state": AppState.MLB_ENTITLEMENT_REQUIRED, "evidence": "ocr", "ocr_text": text}
                has_start_choice = (observation.contains_phrase("Start")
                                    and observation.contains_phrase("Beginning"))
                if observation.contains_phrase("Watch Live") or has_start_choice:
                    try:
                        selection = self.mlb_live_prompt_selection(frame, require_outline=True)
                    except NavigationError:
                        selection = None
                    # Home's hero also says Watch Live. That text alone is
                    # not a modal and must not trigger Back/chooser navigation.
                    if selection or has_start_choice:
                        return {
                            "state": AppState.JOIN_LIVE_OR_START_FROM_BEGINNING,
                            "evidence": "ocr",
                            "ocr_text": text,
                            "selection": selection,
                        }
                if observation.contains_phrase("Video") and observation.contains_phrase("Audio"):
                    try:
                        selection = self.mlb_feed_picker_selection(frame)
                    except NavigationError:
                        selection = None
                    return {"state": AppState.MLB_FEED_PICKER, "evidence": "ocr", "ocr_text": text, "selection": selection}
            except NavigationError:
                pass
        try:
            selection = self.mlb_live_prompt_selection(frame, require_outline=True)
        except NavigationError:
            pass
        else:
            return {"state": AppState.JOIN_LIVE_OR_START_FROM_BEGINNING,
                    "evidence": "live_choice_outlines", "selection": selection, "ocr_text": text}
        try:
            selection = self.mlb_feed_picker_selection(frame)
        except NavigationError:
            pass
        else:
            return {"state": AppState.MLB_FEED_PICKER, "evidence": "feed_button_layout", "selection": selection, "ocr_text": text}
        # A blue loading ring appears both during launch and while Home loads.
        # In particular, the Home background must not become a feed picker.
        for center_x, center_y in ((0.49, 0.495), (0.49, 0.833)):
            cx, cy = int(frame.width * center_x), int(frame.height * center_y)
            radius = max(2, int(frame.height * 0.0375))
            samples = []
            for index in range(16):
                angle = index * math.tau / 16
                x, y = int(cx + radius * math.cos(angle)), int(cy + radius * math.sin(angle))
                samples.append(frame.mean_rgb(x - 1, y - 1, x + 2, y + 2))
            blue = sum(b >= 40 and b - r >= 20 and b >= g * .8 for r, g, b in samples)
            center = frame.mean_rgb(cx - 4, cy - 4, cx + 4, cy + 4)
            if blue >= 8 and sum(s[2] for s in samples) / 16 - center[2] >= 15:
                return {"state": AppState.MLB_GAMES_LOADING, "evidence": "blue_loading_ring", "ocr_text": text}

        # Modal-like brightness is only supporting evidence. It cannot
        # authorize Select when the video/feed labels were not recognized.
        center_luma = frame.mean_luma(
            int(frame.width * 0.31),
            int(frame.height * 0.19),
            int(frame.width * 0.70),
            int(frame.height * 0.81),
        )
        right_luma = frame.mean_luma(
            int(frame.width * 0.73),
            int(frame.height * 0.19),
            int(frame.width * 0.98),
            int(frame.height * 0.81),
        )
        possible_modal = 22 <= center_luma <= 100 and center_luma - right_luma >= 15
        # The Home hero has a rounded bright outline; its lineup is below it.
        # This only authorizes moving Down to the cards, never opening a game.
        x0, y0, x1, y1 = int(frame.width * .38), int(frame.height * .15), int(frame.width * .96), int(frame.height * .73)
        inset = max(2, int(frame.width * .025))
        drift = max(1, int(frame.width * .006))
        edges = [max(frame.mean_luma(x0 + inset, y, x1 - inset, y + 1) for y in range(v - drift, v + drift + 1)) for v in (y0, y1)]
        edges += [max(frame.mean_luma(x, y0 + inset, x + 1, y1 - inset) for x in range(v - drift, v + drift + 1)) for v in (x0, x1)]
        surrounding = frame.mean_luma(x0 - 12, y0 + inset, x0 - 6, y1 - inset)
        if min(edges) >= 145 and sum(edges) / 4 - surrounding >= 60:
            return {"state": AppState.MLB_HOME, "evidence": "home_hero_focus_outline", "ocr_text": text}
        if text and "todayslineup" in normalize_channel_name(text):
            return {"state": AppState.MLB_HOME, "evidence": "ocr_today_lineup", "ocr_text": text}
        try:
            cursor = self.mlb_grid_cursor(frame)
        except NavigationError:
            cursor = None
        # A bright part of a broadcast is not a game card. Require the
        # navigation header as well as candidate card geometry.
        normalized = normalize_channel_name(text or "")
        grid_header = "todaysgames" in normalized or all(
            value in normalized for value in ("home", "games", "shows")
        )
        if cursor is not None and not grid_header:
            try:
                self.assert_mlb_games_tab_focus(frame)
                grid_header = True
            except NavigationError:
                pass
        if cursor is not None and grid_header:
            return {
                "state": AppState.MLB_GAMES_GRID,
                "evidence": "grid_cursor_and_navigation_header",
                "cursor": cursor,
                "ocr_text": text,
            }
        if text:
            normalized = normalize_channel_name(text)
            if all(value in normalized for value in ("home", "games", "shows")):
                return {"state": AppState.MLB_HOME, "evidence": "ocr_navigation", "ocr_text": text}
            if "todaysgames" in normalized:
                return {"state": AppState.MLB_GAMES_LOADING, "evidence": "ocr_without_cursor", "ocr_text": text}
        if possible_modal:
            return {"state": AppState.UNKNOWN, "evidence": "unverified_modal_geometry", "ocr_text": text}
        # Like YouTube TV, MLB may leave a stream running behind an app menu.
        # Only use ECP playback after every visible UI surface has failed.
        if is_mlb_player and player_state not in ("", "none", "close", "stop", "stopped"):
            return {
                "state": AppState.FULL_PROGRAM,
                "evidence": "roku_media_player_after_ui_checks",
                "player_state": player_state,
            }
        return {
            "state": AppState.UNKNOWN,
            "evidence": "no_mlb_state_evidence",
            "ocr_text": text,
        }

    def _identify_guide_logo(
        self,
        actual: GrayTemplate,
        channels: tuple[ChannelConfig, ...],
        *,
        focus: str,
    ) -> dict[str, object]:
        errors: list[dict[str, object]] = []
        for channel in channels:
            try:
                verification = self._verify_template(
                    actual,
                    self.template_path(channel.name, channel.template),
                    expected_kind="guide_logo",
                    channel=channel.name,
                    surface="guide row",
                )
            except NavigationError as exc:
                errors.append({"channel": channel.name, "message": str(exc)})
                continue
            return {
                "matched": True,
                "channel": channel.name,
                "guide_index": channel.guide_index,
                "focus": focus,
                "verification": verification,
            }
        raise NavigationError(
            "The live guide is visible, but its selected row is not calibrated",
            details={"guide_identification_errors": errors},
        )

    def identify_selected(
        self,
        channels: tuple[ChannelConfig, ...],
        frame: PpmFrame | None = None,
    ) -> dict[str, object]:
        """Identify the currently focused configured guide row."""
        frame = frame or self.capture()
        try:
            actual = self.selected_logo(frame)
            focus = "program"
        except NavigationError as program_error:
            try:
                tile = self.assert_network_tile_focus(frame)
            except NavigationError as network_error:
                raise NavigationError(
                    "The Roku return feed does not show a recognizable live-guide focus",
                    details={
                        "program_focus": str(program_error),
                        "network_focus": str(network_error),
                    },
                ) from network_error
            bounds = tile.get('bounds')
            row_start, row_end = (bounds[1]-3, bounds[3]+4) if bounds else self._guide_row_geometry(frame)
            actual = self._guide_logo_crop(frame, row_start, row_end)
            focus = "network_tile"
        identified = self._identify_guide_logo(actual, channels, focus=focus)
        self._verify_guide_identity(identified['channel'], frame,
                                    identified['verification'].get('template_path'))
        return identified

    def identify_network_page(
        self,
        channels: tuple[ChannelConfig, ...],
        frame: PpmFrame | None = None,
    ) -> dict[str, object]:
        """Identify any calibrated YouTube TV channel-description page."""
        frame = frame or self.capture()
        content_luma = frame.mean_luma(
            int(frame.width * 0.15),
            int(frame.height * 0.12),
            int(frame.width * 0.95),
            int(frame.height * 0.90),
        )
        if content_luma < 8:
            raise NavigationError(
                "The frame is too dark to be a channel-description page",
                details={"content_luma": round(content_luma, 2)},
            )
        broad_actual = self.network_page_logo(frame)
        detail_actual = self.network_page_detail_logo(frame)
        pages = tuple(dict.fromkeys(channel.network_page or channel.name for channel in channels))
        for page in pages:
            detail_path = self.network_detail_template_path(page)
            if detail_path.is_file():
                try:
                    detail = self._verify_template(
                        detail_actual,
                        detail_path,
                        expected_kind="network_detail_logo",
                        channel=page,
                        surface="network page detail logo",
                        required_margin=self.config.network_template_margin,
                    )
                except NavigationError:
                    continue
                return {
                    "matched": True,
                    "channel": page,
                    "content_luma": round(content_luma, 2),
                    "detail": detail,
                }
            try:
                broad = self._verify_template(
                    broad_actual,
                    self.network_template_path(page),
                    expected_kind="network_logo",
                    channel=page,
                    surface="network page logo",
                    required_margin=self.config.network_template_margin,
                )
            except NavigationError:
                continue
            # Broad network crops are mostly empty background. A dark video
            # frame can have a tiny pixel difference while sharing no logo
            # shape at all (observed false NFL matches at correlation .04).
            if float(broad.get("correlation", -1)) < self.config.guide_correlation_threshold:
                continue
            return {
                "matched": True,
                "channel": page,
                "content_luma": round(content_luma, 2),
                "broad": broad,
            }
        raise NavigationError("No calibrated channel-description page is visible")

    def detect_youtube_tv_state(
        self,
        frame: PpmFrame,
        channels: tuple[ChannelConfig, ...],
        media_player: dict[str, object],
    ) -> dict[str, object]:
        """Classify a YouTube TV surface using deterministic visual evidence."""
        try:
            join_live = self.assert_join_live_prompt(frame)
        except NavigationError:
            pass
        else:
            return {
                "state": AppState.JOIN_LIVE_OR_START_FROM_BEGINNING,
                "evidence": "join_live_focus_geometry",
                "verification": join_live,
            }

        try:
            # Fixed position only: this runs for every observed frame. The OCR
            # chooser branch below searches when the row has shifted.
            profile = self.verify_vivian_profile(frame, search=False)
        except NavigationError:
            pass
        else:
            return {
                "state": AppState.YOUTUBE_TV_USER_SELECT,
                "evidence": "vivian_profile_template",
                "profile_verified": True,
                "verification": profile,
            }

        try:
            resume = self.assert_resume_banner(frame)
        except NavigationError:
            pass
        else:
            return {'state': AppState.YOUTUBE_TV_HOME, 'evidence': 'resume_banner_focus_geometry',
                    'navigation_tab': 'resume', 'verification': resume}

        try:
            live = self.assert_live_tab(frame)
        except NavigationError:
            pass
        else:
            return {"state": AppState.YOUTUBE_TV_HOME, "evidence": "live_tab_focus_geometry",
                    "navigation_tab": "live", "verification": live}

        try:
            home = self.assert_home_tab(frame)
        except NavigationError:
            pass
        else:
            return {
                "state": AppState.YOUTUBE_TV_HOME,
                "evidence": "home_focus_geometry",
                "verification": home,
            }

        # A station tile can be focused with every program cell dimmed. This
        # is still the guide; normalizing it requires Right, not another Down.
        try:
            tile = self.assert_network_tile_focus(frame)
        except NavigationError:
            pass
        else:
            return {"state": AppState.LIVE_GUIDE, "evidence": "station_tile_border", "focus": "network_tile", "verification": tile}

        guide_focus: str | None = None
        guide_actual: GrayTemplate | None = None
        try:
            guide_actual = self.selected_logo(frame)
            guide_focus = "program"
        except NavigationError:
            try:
                network_focus = self.assert_network_tile_focus(frame)
            except NavigationError:
                pass
            else:
                bounds = network_focus.get('bounds')
                row_start, row_end = (bounds[1]-3, bounds[3]+4) if bounds else self._guide_row_geometry(frame)
                guide_actual = self._guide_logo_crop(frame, row_start, row_end)
                guide_focus = "network_tile"

        if guide_actual is not None and guide_focus is not None:
            identified: dict[str, object] | None = None
            try:
                identified = self._identify_guide_logo(
                    guide_actual, channels, focus=guide_focus
                )
            except NavigationError:
                pass
            if identified is not None:
                try:
                    self._verify_guide_identity(identified['channel'], frame,
                                                identified['verification'].get('template_path'))
                except NavigationError:
                    identified = None
            if identified is not None:
                return {
                    "state": AppState.LIVE_GUIDE,
                    "evidence": "calibrated_guide_row",
                    "focus": guide_focus,
                    "channel": identified["channel"],
                    "guide_index": identified["guide_index"],
                    "guide_verification": identified["verification"],
                }

        # Explicit navigation text must win before broad network-page image
        # templates. Direct composite capture can change logo texture enough
        # for an unrelated dark surface to otherwise become the closest match.
        if self.ocr is not None:
            try:
                screen_text = self.read_screen_text(frame)
            except NavigationError:
                pass
            else:
                if screen_text["state"] == "location_verification":
                    return {
                        "state": AppState.YOUTUBE_TV_LOCATION_VERIFICATION,
                        "evidence": "ocr_location_verification",
                        "ocr": screen_text,
                        "selection": self.location_verification_selection(frame),
                    }
                if screen_text["state"] == "profile_chooser":
                    try:
                        profile = self.verify_vivian_profile(frame)
                    except NavigationError as exc:
                        profile = exc.details.get("profile_verification")
                        verified = False
                    else:
                        verified = True
                    return {
                        "state": AppState.YOUTUBE_TV_USER_SELECT,
                        "evidence": "vivian_profile_search" if verified else "ocr_profile_chooser",
                        "profile_verified": verified,
                        "verification": profile,
                        "ocr": screen_text,
                    }
                if screen_text['state'] == 'youtube_tv_home_content':
                    return {'state': AppState.YOUTUBE_TV_HOME,
                            'evidence': 'ocr_home_recommendations', 'verification': screen_text}
                if screen_text["state"] == "youtube_tv_navigation":
                    return {
                        "state": AppState.YOUTUBE_TV_HOME,
                        "evidence": "ocr_top_navigation",
                        "verification": screen_text,
                    }
                if screen_text["state"] == "live_guide":
                    return {
                        "state": AppState.LIVE_GUIDE,
                        "evidence": "ocr_guide_time_grid",
                        "focus": guide_focus,
                        "ocr": screen_text,
                    }

        try:
            page = self.identify_network_page(channels, frame)
        except NavigationError:
            pass
        else:
            return {
                "state": AppState.CHANNEL_DESCRIPTION,
                "evidence": "network_page_template",
                "channel": page["channel"],
                "verification": page,
            }

        player_state = str(media_player.get("state", "")).casefold()
        if player_state not in ("", "none", "close", "stop", "stopped"):
            return {
                "state": AppState.FULL_PROGRAM,
                "evidence": "roku_media_player",
                "player_state": player_state,
            }

        return {
            "state": AppState.UNKNOWN,
            "evidence": "no_state_evidence",
            "player_state": player_state or None,
        }

    def verify_network_text(
        self,
        channel: str,
        aliases: tuple[str, ...] = (),
    ) -> dict[str, object]:
        if self.ocr is None:
            if self.config.ocr_required:
                raise NavigationError("Local OCR is required but disabled")
            return {"matched": False, "required": False, "reason": "ocr_disabled"}
        frame = self.capture()
        # The network page header occupies the upper half. Excluding lower
        # content shelves prevents ESPN recommendations on an ESPN2 page (or
        # vice versa) from becoming false matches.
        crop = (0, 0, frame.width, int(frame.height * 0.58))
        observation = self.ocr.read(frame, crop=crop, psm=11)
        matches = observation.find_names((channel, *aliases))
        # Prefer a reasonably large header token. Coordinates are in the
        # OCR-upscaled image, so divide by the configured scale for source px.
        strong = [
            match
            for match in matches
            if float(match["confidence"]) >= self.config.ocr_min_confidence
            and int(match["height"]) / self.config.ocr_scale >= 12
        ]
        result = {
            "matched": bool(strong),
            "expected": channel,
            "matches": strong,
            "ocr_text": observation.text,
            "crop": list(crop),
        }
        if not strong and self.config.ocr_required:
            raise NavigationError(
                f"Local OCR could not verify network page {channel!r}",
                details={"ocr_verification": result},
            )
        return result

    def network_page_logo(self, frame: PpmFrame | None = None) -> GrayTemplate:
        """Extract the fixed network mark in a YouTube TV network-page header."""
        frame = frame or self.capture()
        # Network pages put a small white station logo against black in the
        # upper-left. This deliberately excludes the changing hero artwork.
        return self._downsample(
            frame,
            int(frame.width * 0.010),
            int(frame.height * 0.010),
            int(frame.width * 0.125),
            int(frame.height * 0.115),
            width=48,
            height=24,
        )

    def network_page_detail_logo(
        self, frame: PpmFrame | None = None
    ) -> GrayTemplate:
        """Extract only the identifying wordmark from the page's upper-left."""
        frame = frame or self.capture()
        return self._downsample(
            frame,
            int(frame.width * 0.020),
            int(frame.height * 0.035),
            int(frame.width * 0.090),
            int(frame.height * 0.095),
            width=48,
            height=20,
            normalize=True,
        )

    @staticmethod
    def _template_kind(raw: dict[str, object], path: Path) -> str:
        kind = raw.get("kind")
        if isinstance(kind, str) and kind:
            return kind
        # Backward compatibility for templates captured before kinds were
        # added. Legacy channel files are guide logos.
        if path.name.startswith("network-"):
            return "network_logo"
        if path.name.startswith("profile-"):
            return "profile"
        return "guide_logo"

    @staticmethod
    def _save_template(
        template: GrayTemplate,
        path: Path,
        *,
        channel: str,
        kind: str,
    ) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(template.to_dict(channel=channel, kind=kind), indent=2)
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
        return path

    @staticmethod
    def _template_variants(raw: dict[str, object]) -> tuple[GrayTemplate, ...]:
        templates = [GrayTemplate.from_dict(raw)]
        variants = raw.get("variants", [])
        if variants is None:
            variants = []
        if not isinstance(variants, list):
            raise NavigationError("Channel template variants must be an array")
        for variant in variants:
            if not isinstance(variant, dict):
                raise NavigationError("Each channel template variant must be an object")
            templates.append(GrayTemplate.from_dict(variant))
        return tuple(templates)

    @classmethod
    def _save_observation_template(
        cls,
        template: GrayTemplate,
        path: Path,
        *,
        channel: str,
        kind: str,
    ) -> Path:
        """Append a distinct analog observation without losing prior ones."""
        if not path.is_file():
            return cls._save_template(template, path, channel=channel, kind=kind)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NavigationError(f"Cannot read channel template {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise NavigationError(f"Channel template {path} is not a JSON object")
        if cls._template_kind(raw, path) != kind:
            raise NavigationError(
                f"Channel template {path} does not contain {kind} observations"
            )
        existing = cls._template_variants(raw)
        if any(candidate.difference(template) < 0.5 for candidate in existing):
            return path
        variants = raw.get("variants")
        if not isinstance(variants, list):
            variants = []
        variants.append(template.to_dict(channel=channel, kind=kind))
        raw["variants"] = variants
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
        return path

    def _verify_template(
        self,
        actual: GrayTemplate,
        path: Path,
        *,
        expected_kind: str,
        channel: str,
        surface: str,
        required_margin: float | None = None,
    ) -> dict[str, object]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise NavigationError(
                f"No {surface} template has been calibrated for {channel!r}",
                details={"template_path": str(path)},
            ) from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise NavigationError(f"Cannot read channel template {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise NavigationError(f"Channel template {path} is not a JSON object")
        if self._template_kind(raw, path) != expected_kind:
            raise NavigationError(
                f"Channel template {path} is not a {surface} template"
            )

        expected_variants = self._template_variants(raw)
        difference = min(expected.difference(actual) for expected in expected_variants)
        correlation = max(
            expected.correlation(actual) for expected in expected_variants
        )
        closest_competitor: dict[str, object] | None = None
        closest_correlation_competitor: dict[str, object] | None = None
        assert self.config.template_dir is not None
        for candidate_path in self.config.template_dir.glob("*.json"):
            if candidate_path.resolve() == path.resolve():
                continue
            try:
                candidate_raw = json.loads(candidate_path.read_text(encoding="utf-8"))
                if not isinstance(candidate_raw, dict):
                    continue
                if self._template_kind(candidate_raw, candidate_path) != expected_kind:
                    continue
                candidate_variants = self._template_variants(candidate_raw)
                candidate_channel = str(
                    candidate_raw.get("channel", candidate_path.stem)
                )
            except (OSError, json.JSONDecodeError, NavigationError):
                continue
            candidate_difference = min(
                candidate.difference(actual) for candidate in candidate_variants
            )
            candidate_correlation = max(
                candidate.correlation(actual) for candidate in candidate_variants
            )
            if candidate_difference >= 255:
                continue
            if (
                closest_competitor is None
                or candidate_difference < closest_competitor["difference"]
            ):
                closest_competitor = {
                    "channel": candidate_channel,
                    "difference": round(candidate_difference, 3),
                    "template_path": str(candidate_path),
                }
            if (
                closest_correlation_competitor is None
                or candidate_correlation
                > closest_correlation_competitor["correlation"]
            ):
                closest_correlation_competitor = {
                    "channel": candidate_channel,
                    "correlation": round(candidate_correlation, 6),
                    "template_path": str(candidate_path),
                }

        competitor_difference = (
            float(closest_competitor["difference"])
            if closest_competitor is not None
            else None
        )
        margin = (
            competitor_difference - difference
            if competitor_difference is not None
            else None
        )
        effective_margin = (
            self.config.template_margin
            if required_margin is None
            else required_margin
        )
        difference_matched = difference <= self.config.template_difference_threshold and (
            margin is None or margin >= effective_margin
        )
        correlation_competitor = (
            float(closest_correlation_competitor["correlation"])
            if closest_correlation_competitor is not None
            else None
        )
        correlation_margin = (
            correlation - correlation_competitor
            if correlation_competitor is not None
            else None
        )
        # Guide logos are small and pass through an analog modulator. Their
        # overall brightness can move enough to confuse absolute pixel
        # distance, while the wordmark shape remains stable. Network-page
        # logos stay on the stricter absolute-distance path and are verified
        # independently before the final playback Select.
        correlation_matched = expected_kind == "guide_logo" and (
            correlation >= self.config.guide_correlation_threshold
            and (
                correlation_margin is None
                or correlation_margin >= self.config.guide_correlation_margin
            )
        )
        matched = difference_matched or correlation_matched
        if expected_kind == 'guide_logo' and raw.get('capture_format') == '720p':
            # Crisp component wordmarks need shape agreement as well as a
            # separated winner. Mostly dark crops must not pass by distance.
            matched = matched and correlation >= .96 and (correlation_margin is None or correlation_margin >= .02)
        result = {
            "matched": matched,
            "surface": surface,
            "difference": round(difference, 3),
            "threshold": self.config.template_difference_threshold,
            "required_margin": effective_margin,
            "competitor_margin": round(margin, 3) if margin is not None else None,
            "closest_competitor": closest_competitor,
            "correlation": round(correlation, 6),
            "correlation_threshold": self.config.guide_correlation_threshold,
            "correlation_margin": (
                round(correlation_margin, 6)
                if correlation_margin is not None
                else None
            ),
            "required_correlation_margin": self.config.guide_correlation_margin,
            "closest_correlation_competitor": closest_correlation_competitor,
            "matched_by": (
                "difference"
                if difference_matched
                else "correlation"
                if correlation_matched
                else None
            ),
            "template_variants": len(expected_variants),
            "template_path": str(path),
        }
        if not matched:
            raise NavigationError(
                f"Visible {surface} does not match {channel!r}; refusing to play it",
                details={"visual_verification": result},
            )
        return result

    def save_network_template(self, channel: str) -> Path:
        frame = self.capture()
        broad_path = self._save_observation_template(
            self.network_page_logo(frame),
            self.network_template_path(channel),
            channel=channel,
            kind="network_logo",
        )
        self._save_observation_template(
            self.network_page_detail_logo(frame),
            self.network_detail_template_path(channel),
            channel=channel,
            kind="network_detail_logo",
        )
        return broad_path

    def verify_network_page(
        self,
        channel: str,
        aliases: tuple[str, ...] = (),
    ) -> dict[str, object]:
        frame = self.capture()
        broad: dict[str, object] | None = None
        broad_error: NavigationError | None = None
        try:
            broad = self._verify_template(
                self.network_page_logo(frame),
                self.network_template_path(channel),
                expected_kind="network_logo",
                channel=channel,
                surface="network page logo",
                required_margin=self.config.network_template_margin,
            )
        except NavigationError as exc:
            broad_error = exc

        detail_path = self.network_detail_template_path(channel)
        detail: dict[str, object] | None = None
        if detail_path.is_file():
            # Once calibrated, the tight wordmark is mandatory. It is also
            # sufficient when analog noise makes the broad mostly-black crop
            # ambiguous, as happens among ESPN-family pages.
            detail = self._verify_template(
                self.network_page_detail_logo(frame),
                detail_path,
                expected_kind="network_detail_logo",
                channel=channel,
                surface="network page detail logo",
                required_margin=self.config.network_template_margin,
            )
        elif broad_error is not None:
            raise broad_error

        visual: dict[str, object] = {
            "matched": True,
            "detail": detail,
            "broad": broad,
            "broad_error": (
                {
                    "message": str(broad_error),
                    "details": broad_error.details,
                }
                if broad_error is not None
                else None
            ),
        }
        ocr_result: dict[str, object] | None = None
        if self.ocr is not None:
            crop = (0, 0, frame.width, int(frame.height * 0.58))
            observation = self.ocr.read(frame, crop=crop, psm=11)
            matches = observation.find_names((channel, *aliases))
            ocr_result = {
                "matched": bool(matches),
                "expected": channel,
                "matches": matches,
                "ocr_text": observation.text,
                "crop": list(crop),
            }
        elif self.config.ocr_required:
            raise NavigationError("Local OCR is required but disabled")
        return {"matched": True, "visual": visual, "ocr": ocr_result}

    def save_selected_template(
        self,
        channel: str,
        *,
        configured_path: str | None = None,
        frame: PpmFrame | None = None,
    ) -> Path:
        frame = frame or self.capture()
        template = self.selected_logo(frame)
        path = self.template_path(channel, configured_path)
        self._save_observation_template(
            template, path, channel=channel, kind="guide_logo"
        )
        if (frame.width, frame.height) == (1280, 720):
            raw = json.loads(path.read_text())
            raw['capture_format'] = '720p'
            temporary = path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(raw, indent=2) + '\n')
            temporary.replace(path)
        return path

    def verify_selected(
        self,
        channel: str,
        *,
        configured_path: str | None = None,
        frame: PpmFrame | None = None,
    ) -> dict[str, object]:
        frame = frame or self.capture()
        path = self.template_path(channel, configured_path)
        result = self._verify_template(
            self.selected_logo(frame),
            path,
            expected_kind="guide_logo",
            channel=channel,
            surface="guide row",
        )
        identity = self._verify_guide_identity(channel, frame, configured_path)
        if identity is not None:
            result['station_identity'] = identity
        return result

    def _verify_guide_identity(self, channel: str, frame: PpmFrame,
                               configured_path: str | None = None) -> dict | None:
        raw = json.loads(self.template_path(channel, configured_path).read_text())
        names = raw.get('guide_identity_names')
        if not names:
            return None
        if self.ocr is None:
            raise NavigationError(f'{channel} requires its station call sign to be read')
        row_start, _ = self._guide_row_geometry(frame)
        observation = self.ocr.read(frame, crop=(int(frame.width*.055), int(frame.height*.10),
                                                int(frame.width*.65), row_start-int(frame.height*.08)), psm=11)
        matches = observation.find_names(tuple(names))
        excluded = observation.find_names(tuple(raw.get('guide_identity_exclude', []))) if raw.get('guide_identity_exclude') else []
        if not matches or excluded:
            raise NavigationError(f'The selected guide row is not the required {channel} station',
                                  details={'expected_station': names, 'ocr_text': observation.text})
        return {'matched': True, 'names': names, 'ocr_text': observation.text}


class TvThingFeedback(VisualFeedback):
    """Visual feedback from a selected TV Thing Roku capture source."""

    def __init__(self, config: FeedbackConfig, *, selection_path: Path | None = None) -> None:
        if not config.base_url:
            raise ValueError("TV Thing feedback has no base URL")
        super().__init__(config)
        self._required_source = config.required_source
        self._required_cable_channel = config.required_cable_channel
        self._required_capture_id = config.required_capture_id
        self._selection_path = selection_path
        if selection_path is not None and selection_path.is_file():
            try:
                saved = json.loads(selection_path.read_text(encoding="utf-8"))
                source, channel, capture_id = saved["source"], saved["channel"], saved["source_id"]
                if source not in ("cable", "capture") or type(channel) is not int or not 1 <= channel <= 135:
                    raise ValueError("invalid source or channel")
                if source == "capture" and (not isinstance(capture_id, str) or not capture_id):
                    raise ValueError("missing capture ID")
                self._required_source = source
                self._required_cable_channel = channel
                self._required_capture_id = capture_id
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise NavigationError(f"Cannot load saved Roku source: {exc}") from exc

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}/{path.lstrip('/')}"

    def _request_json(
        self, path: str, *, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        request: str | urllib.request.Request = self._url(path)
        if payload is not None:
            request = urllib.request.Request(
                request,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.config.capture_timeout_seconds,
            ) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                error_data = json.loads(exc.read().decode("utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                error_data = None
            message = None
            if isinstance(error_data, dict):
                error = error_data.get("error")
                if isinstance(error, dict):
                    message = error.get("message")
                elif isinstance(error, str):
                    message = error
            raise NavigationError(
                f"TV Thing request failed: {message or exc.reason}",
                details={"path": path, "status": exc.code},
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise NavigationError(f"Cannot read TV Thing response: {exc}") from exc
        if not isinstance(data, dict):
            raise NavigationError("TV Thing response is not a JSON object")
        return data

    def status(self) -> dict[str, object]:
        return self._request_json(self.config.status_path)

    @staticmethod
    def _capture_id(status: dict[str, object]) -> str | None:
        capture = status.get("capture")
        if not isinstance(capture, dict):
            return None
        value = capture.get("id")
        return value if isinstance(value, str) else None

    @classmethod
    def _status_matches(
        cls,
        status: dict[str, object],
        source: str,
        cable_channel: int,
        capture_id: str | None,
    ) -> bool:
        ready = status.get("stream_ready", status.get("streaming")) is True
        if source == "cable":
            actual_channel = status.get("cable_channel", status.get("channel"))
            return status.get("mode") == "cable" and actual_channel == cable_channel and ready
        return (
            status.get("mode") == "capture"
            and cls._capture_id(status) == capture_id
            and ready
        )

    def source_catalog(self) -> dict[str, object]:
        """Return switchable Roku observation inputs and the current selection."""
        sources_data = self._request_json("/api/v1/sources")
        raw_sources = sources_data.get("sources")
        raw_sources = raw_sources if isinstance(raw_sources, list) else []
        cable_available = any(
            isinstance(item, dict)
            and item.get("id") == "cable"
            and item.get("available") is True
            for item in raw_sources
        )
        options: list[dict[str, object]] = [
            {
                "key": f"cable:{self.config.required_cable_channel}",
                "source": "cable",
                "channel": self.config.required_cable_channel,
                "name": f"Cable channel {self.config.required_cable_channel}",
                "detail": "Analog RF return",
                "available": cable_available,
            }
        ]
        capture_data = self._request_json("/api/v1/sources/capture")
        raw_captures = capture_data.get("items")
        raw_captures = raw_captures if isinstance(raw_captures, list) else []
        for item in raw_captures:
            if not isinstance(item, dict):
                continue
            capture_id = item.get("id")
            name = item.get("name")
            if not isinstance(capture_id, str) or not isinstance(name, str):
                continue
            options.append(
                {
                    "key": capture_id,
                    "source": "capture",
                    "source_id": capture_id,
                    "name": name.rstrip("/"),
                    "detail": str(item.get("device") or "Direct capture"),
                    "available": item.get("available") is True,
                }
            )

        status = self.status()
        selected = None
        if status.get("mode") == "cable" and isinstance(status.get("cable_channel"), int):
            selected = f"cable:{status['cable_channel']}"
        elif status.get("mode") == "capture":
            selected = self._capture_id(status)
        required = (
            f"cable:{self._required_cable_channel}"
            if self._required_source == "cable"
            else self._required_capture_id
        )
        return {
            "sources": options,
            "selected": selected,
            "required": required,
            "ready": self._status_matches(
                status,
                self._required_source,
                self._required_cable_channel,
                self._required_capture_id,
            ),
        }

    def select_source(self, key: str) -> dict[str, object]:
        """Tune TV Thing and require that source for subsequent observations."""
        catalog = self.source_catalog()
        option = next(
            (
                item
                for item in catalog["sources"]
                if isinstance(item, dict) and item.get("key") == key
            ),
            None,
        )
        if option is None:
            raise NavigationError(
                f"Unknown Roku capture source {key!r}",
                details={"available": [item["key"] for item in catalog["sources"]]},
            )
        if option.get("available") is not True:
            raise NavigationError(f"Roku capture source {option['name']} is unavailable")

        source = str(option["source"])
        cable_channel = int(option.get("channel", self.config.required_cable_channel))
        capture_id = option.get("source_id")
        capture_id = capture_id if isinstance(capture_id, str) else None
        quality = self.status().get("quality", "low")
        payload: dict[str, object] = {"source": source, "quality": quality}
        if source == "cable":
            payload["channel"] = cable_channel
        else:
            payload["source_id"] = capture_id
        result = self._request_json("/api/v1/tune", payload=payload)
        if result.get("ok") is not True:
            raise NavigationError(
                "TV Thing did not accept the Roku source",
                details={"source": option, "response": result},
            )

        deadline = time.monotonic() + max(5.0, self.config.capture_timeout_seconds)
        status = self.status()
        while not self._status_matches(
            status, source, cable_channel, capture_id
        ) and time.monotonic() < deadline:
            time.sleep(0.25)
            status = self.status()
        if not self._status_matches(status, source, cable_channel, capture_id):
            raise NavigationError(
                f"TV Thing did not make {option['name']} ready in time",
                details={"source": option, "tv_thing_status": status},
            )

        if self._selection_path is not None:
            self._selection_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._selection_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"source": source, "channel": cable_channel, "source_id": capture_id}) + "\n", encoding="utf-8")
            temporary.replace(self._selection_path)
        self._required_source = source
        self._required_cable_channel = cable_channel
        self._required_capture_id = capture_id
        return {"ok": True, "source": option, "status": status}

    def assert_ready(self) -> dict[str, object]:
        status = self.status()
        if not self._status_matches(
            status,
            self._required_source,
            self._required_cable_channel,
            self._required_capture_id,
        ):
            expected = (
                f"cable channel {self._required_cable_channel}"
                if self._required_source == "cable"
                else f"capture source {self._required_capture_id}"
            )
            raise NavigationError(
                f"TV Thing is not ready to observe the Roku on {expected}",
                details={"tv_thing_status": status},
            )
        return status

    def capture(self) -> PpmFrame:
        status = self.assert_ready()
        if self.config.fresh_segments:
            return self._capture_fresh_segment(status)
        frame = self._decode_frame(self._url(self.config.playlist_path))
        self.last_frame = frame
        self.last_capture = {"fresh": False, "observed_at": datetime.now(timezone.utc).isoformat()}
        return frame

    def _latest_segment(self) -> tuple[int, str]:
        url = self._url(self.config.playlist_path)
        try:
            request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=self.config.capture_timeout_seconds) as response:
                playlist = response.read(128 * 1024).decode("utf-8")
            sequence = int(re.search(r"^#EXT-X-MEDIA-SEQUENCE:(\d+)", playlist, re.M)[1])
            segments = [line.strip() for line in playlist.splitlines() if line.strip() and not line.startswith("#")]
            if "#EXT-X-INDEPENDENT-SEGMENTS" not in playlist or not segments:
                raise ValueError("independent media segments are required")
            segment_url = urllib.parse.urljoin(url, segments[-1])
            if urllib.parse.urlsplit(segment_url).netloc != urllib.parse.urlsplit(url).netloc:
                raise ValueError("segment is outside the configured capture service")
            return sequence + len(segments) - 1, segment_url
        except (OSError, ValueError, TypeError, UnicodeError) as exc:
            raise NavigationError(f"Cannot read TV Thing media sequence: {exc}") from exc

    def _capture_fresh_segment(self, status: dict[str, object]) -> PpmFrame:
        started_at = datetime.now(timezone.utc).isoformat()
        stream_id = status.get("stream_id")
        if not stream_id:
            raise NavigationError("Fresh capture requires TV Thing stream_id")
        baseline, _ = self._latest_segment()
        deadline = time.monotonic() + self.config.capture_timeout_seconds
        # Skip the segment being encoded when this observation began. A
        # second completed segment is publication evidence after the barrier;
        # it is not a claim about the capture device's internal latency.
        while True:
            sequence, url = self._latest_segment()
            if sequence >= baseline + 2:
                break
            if sequence < baseline:
                raise NavigationError("TV Thing media sequence reset during capture")
            if time.monotonic() >= deadline:
                raise NavigationError("TV Thing stream stopped advancing", details={"baseline_sequence": baseline, "last_sequence": sequence})
            self.wait(0.2)
        frame = self._decode_frame(url)
        current = self.assert_ready()
        if current.get("stream_id") != stream_id:
            raise NavigationError("TV Thing stream changed during capture")
        self.last_frame = frame
        self.last_capture = {
            "fresh": True, "stream_id": stream_id,
            "baseline_sequence": baseline, "sequence": sequence,
            "barrier_at": started_at,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.on_capture is not None:
            self.on_capture(dict(self.last_capture))
        return frame

    def _decode_frame(self, url: str) -> PpmFrame:
        command = [
            self.config.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-rw_timeout",
            str(int(self.config.capture_timeout_seconds * 1_000_000)),
            "-i",
            url,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "ppm",
            "pipe:1",
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.config.capture_timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NavigationError(f"Cannot capture TV Thing frame: {exc}") from exc
        if completed.returncode != 0 or not completed.stdout:
            stderr = completed.stderr.decode("utf-8", errors="replace")[-1000:]
            raise NavigationError(
                f"FFmpeg could not capture TV Thing frame: {stderr.strip()}"
            )
        return PpmFrame.parse(completed.stdout)

    @staticmethod
    def _jpeg_frames(stream: BinaryIO) -> Iterator[bytes]:
        """Split ffmpeg's concatenated MJPEG output into complete images."""
        buffer = bytearray()
        while chunk := stream.read1(64 * 1024):
            buffer.extend(chunk)
            while True:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    # Keep a possible split start marker, but discard unrelated
                    # output before it can grow without bound.
                    if len(buffer) > 1:
                        del buffer[:-1]
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    break
                end += 2
                frame = bytes(buffer[start:end])
                del buffer[:end]
                yield frame

    def preview_frames(self) -> Iterator[bytes]:
        """Yield a low-bandwidth browser preview of the selected Roku feed."""
        self.assert_ready()
        command = [
            self.config.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-rw_timeout",
            str(int(self.config.capture_timeout_seconds * 1_000_000)),
            "-i",
            self._url(self.config.playlist_path),
            "-an",
            "-vf",
            "fps=2,scale=960:-2:flags=bicubic",
            "-q:v",
            "5",
            "-f",
            "mjpeg",
            "pipe:1",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise NavigationError(f"Cannot start TV Thing preview: {exc}") from exc
        try:
            assert process.stdout is not None
            yield from self._jpeg_frames(process.stdout)
        finally:
            if process.stdout is not None:
                process.stdout.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
