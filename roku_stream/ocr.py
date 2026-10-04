from __future__ import annotations

import csv
import io
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .config import normalize_channel_name
from .errors import NavigationError


@dataclass(frozen=True)
class OcrWord:
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    block: int
    paragraph: int
    line: int


@dataclass(frozen=True)
class OcrObservation:
    words: tuple[OcrWord, ...]

    @property
    def text(self) -> str:
        lines: dict[tuple[int, int, int], list[OcrWord]] = {}
        for word in self.words:
            lines.setdefault((word.block, word.paragraph, word.line), []).append(word)
        rendered: list[str] = []
        for key in sorted(lines):
            rendered.append(" ".join(word.text for word in sorted(lines[key], key=lambda item: item.left)))
        return "\n".join(rendered)

    def find_names(self, names: Iterable[str]) -> list[dict[str, object]]:
        targets = {
            normalize_channel_name(name): name
            for name in names
            if normalize_channel_name(name)
        }
        tokens = [
            (normalize_channel_name(word.text), word)
            for word in self.words
            if normalize_channel_name(word.text)
        ]
        matches: list[dict[str, object]] = []
        for start in range(len(tokens)):
            combined = ""
            confidence = 100.0
            raw: list[str] = []
            first = tokens[start][1]
            for end in range(start, min(len(tokens), start + 5)):
                token, word = tokens[end]
                # Do not combine words across unrelated OCR lines.
                if (word.block, word.paragraph, word.line) != (
                    first.block,
                    first.paragraph,
                    first.line,
                ):
                    break
                combined += token
                confidence = min(confidence, word.confidence)
                raw.append(word.text)
                if combined in targets:
                    matches.append(
                        {
                            "configured_name": targets[combined],
                            "ocr_text": " ".join(raw),
                            "normalized": combined,
                            "confidence": round(confidence, 2),
                            "left": first.left,
                            "top": first.top,
                            "height": max(
                                tokens[index][1].height
                                for index in range(start, end + 1)
                            ),
                        }
                    )
        return matches

    def contains_phrase(self, phrase: str) -> bool:
        expected = normalize_channel_name(phrase)
        return expected in normalize_channel_name(self.text)


class LocalOcr:
    def __init__(
        self,
        *,
        executable: str = "auto",
        scale: int = 3,
        min_confidence: float = 20.0,
        timeout: float = 15.0,
    ) -> None:
        self.executable, self.environment = self._resolve(executable)
        self.scale = scale
        self.min_confidence = min_confidence
        self.timeout = timeout

    @staticmethod
    def _resolve(configured: str) -> tuple[str, dict[str, str]]:
        environment = dict(os.environ)
        if configured != "auto":
            path = Path(configured).expanduser().resolve()
            if not path.is_file():
                raise NavigationError(f"Configured Tesseract binary does not exist: {path}")
            return str(path), environment
        system = shutil.which("tesseract")
        if system:
            return system, environment
        project = Path(__file__).resolve().parent.parent
        binary = project / "vendor/tesseract/usr/bin/tesseract"
        library = project / "vendor/tesseract/usr/lib/x86_64-linux-gnu"
        tessdata = project / "vendor/tesseract/usr/share/tesseract-ocr/5/tessdata"
        if not binary.is_file():
            raise NavigationError(
                "Local OCR is enabled but Tesseract is unavailable; install tesseract-ocr"
            )
        existing = environment.get("LD_LIBRARY_PATH")
        environment["LD_LIBRARY_PATH"] = (
            f"{library}:{existing}" if existing else str(library)
        )
        environment["TESSDATA_PREFIX"] = str(tessdata)
        return str(binary), environment

    @staticmethod
    def _percentile_bounds(values: bytes) -> tuple[int, int]:
        histogram = [0] * 256
        for value in values:
            histogram[value] += 1
        cutoff = max(1, len(values) // 100)
        running = 0
        low = 0
        for low, count in enumerate(histogram):
            running += count
            if running >= cutoff:
                break
        running = 0
        high = 255
        for high in range(255, -1, -1):
            running += histogram[high]
            if running >= cutoff:
                break
        if high <= low:
            return 0, 255
        return low, high

    def _pgm(self, frame, crop: tuple[int, int, int, int] | None) -> bytes:
        if crop is None:
            x0, y0, x1, y1 = 0, 0, frame.width, frame.height
        else:
            x0, y0, x1, y1 = crop
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(frame.width, x1), min(frame.height, y1)
        if x1 <= x0 or y1 <= y0:
            raise NavigationError("OCR crop is empty")
        grayscale = bytes(
            frame.luma(x, y)
            for y in range(y0, y1)
            for x in range(x0, x1)
        )
        low, high = self._percentile_bounds(grayscale)
        table = bytes(
            max(0, min(255, (value - low) * 255 // max(1, high - low)))
            for value in range(256)
        )
        source_width = x1 - x0
        rows: list[bytes] = []
        for row_start in range(0, len(grayscale), source_width):
            source = grayscale[row_start : row_start + source_width].translate(table)
            scaled = b"".join(bytes([value]) * self.scale for value in source)
            rows.extend([scaled] * self.scale)
        width = source_width * self.scale
        height = (y1 - y0) * self.scale
        return f"P5\n{width} {height}\n255\n".encode("ascii") + b"".join(rows)

    def read(self, frame, *, crop: tuple[int, int, int, int] | None = None, psm: int = 11) -> OcrObservation:
        command = [
            self.executable,
            "stdin",
            "stdout",
            "--psm",
            str(psm),
            "--dpi",
            "300",
            "-l",
            "eng",
            "tsv",
        ]
        try:
            completed = subprocess.run(
                command,
                input=self._pgm(frame, crop),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.environment,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise NavigationError(f"Local OCR failed: {exc}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")[-1000:]
            raise NavigationError(f"Tesseract failed: {stderr.strip()}")
        text = completed.stdout.decode("utf-8", errors="replace")
        words: list[OcrWord] = []
        for row in csv.DictReader(io.StringIO(text), delimiter="\t"):
            value = (row.get("text") or "").strip()
            try:
                confidence = float(row.get("conf") or -1)
            except ValueError:
                continue
            if not value or confidence < self.min_confidence:
                continue
            try:
                words.append(
                    OcrWord(
                        text=value,
                        confidence=confidence,
                        left=int(row["left"]),
                        top=int(row["top"]),
                        width=int(row["width"]),
                        height=int(row["height"]),
                        block=int(row["block_num"]),
                        paragraph=int(row["par_num"]),
                        line=int(row["line_num"]),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return OcrObservation(tuple(words))
