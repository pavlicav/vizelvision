from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .errors import ConfigError, ControlBusyError, RokuStreamError
from .scheduler import parse_time, utc_now


@dataclass
class QueueItem:
    id: str
    position: int
    channel: str
    release_type: str
    created_at: str
    run_at: str | None = None
    after_game_pk: int | None = None
    after_game_date: str | None = None
    after_game_title: str | None = None
    status: str = "queued"
    gate_status: str = "waiting"
    gate_detail: str | None = None
    gate_checked_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None


class PlayoutQueue:
    """Persistent ordered playout queue, independent from timed schedules."""

    def __init__(
        self,
        state_file: Path,
        executor: Callable[[str], dict[str, object]],
        game_status: Callable[[int, str | None], dict[str, object]],
        *,
        poll_seconds: float = 30.0,
        start_worker: bool = True,
    ) -> None:
        self.state_file = state_file
        self.executor = executor
        self.game_status = game_status
        self.poll_seconds = poll_seconds
        self._condition = threading.Condition()
        self._closed = False
        self._items = self._load()
        self._thread: threading.Thread | None = None
        if start_worker:
            self._thread = threading.Thread(
                target=self._run, name="roku-stream-playout-queue", daemon=True
            )
            self._thread.start()

    def _load(self) -> dict[str, QueueItem]:
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Cannot read queue state {self.state_file}: {exc}") from exc
        if not isinstance(raw, list):
            raise ConfigError("Playout queue state must be a JSON array")
        items: dict[str, QueueItem] = {}
        for value in raw:
            if not isinstance(value, dict):
                raise ConfigError("Invalid item in playout queue state")
            item = QueueItem(**value)
            if item.status == "running":
                item.status = "queued"
                item.gate_status = "waiting"
                item.started_at = None
            items[item.id] = item
        return items

    def _save_locked(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                [asdict(item) for item in self._ordered_locked()],
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_file)

    def _queued_locked(self) -> list[QueueItem]:
        return sorted(
            (item for item in self._items.values() if item.status == "queued"),
            key=lambda item: (item.position, item.created_at),
        )

    def _ordered_locked(self) -> list[QueueItem]:
        active = [item for item in self._items.values() if item.status == "running"]
        history = sorted(
            (
                item
                for item in self._items.values()
                if item.status not in ("queued", "running")
            ),
            key=lambda item: item.completed_at or item.created_at,
            reverse=True,
        )
        return active + self._queued_locked() + history

    def _next_position_locked(self) -> int:
        queued = self._queued_locked()
        return (queued[-1].position + 1) if queued else 0

    @staticmethod
    def _copy(item: QueueItem) -> QueueItem:
        return QueueItem(**asdict(item))

    def add_at_time(self, channel: str, run_at: datetime) -> QueueItem:
        run_at = run_at.astimezone(timezone.utc)
        if run_at <= utc_now():
            raise ConfigError("run_at must be in the future")
        with self._condition:
            item = QueueItem(
                id=uuid.uuid4().hex,
                position=self._next_position_locked(),
                channel=channel,
                release_type="at_time",
                run_at=run_at.isoformat(),
                created_at=utc_now().isoformat(),
                gate_detail=f"Waiting until {run_at.isoformat()}",
            )
            self._items[item.id] = item
            self._save_locked()
            self._condition.notify_all()
            return self._copy(item)

    def add_after_game(
        self,
        channel: str,
        *,
        game_pk: int,
        game_date: str,
        game_title: str,
    ) -> QueueItem:
        with self._condition:
            item = QueueItem(
                id=uuid.uuid4().hex,
                position=self._next_position_locked(),
                channel=channel,
                release_type="after_game",
                after_game_pk=game_pk,
                after_game_date=game_date,
                after_game_title=game_title,
                created_at=utc_now().isoformat(),
                gate_detail=f"Waiting for {game_title} to end",
            )
            self._items[item.id] = item
            self._save_locked()
            self._condition.notify_all()
            return self._copy(item)

    def list(self) -> list[QueueItem]:
        with self._condition:
            return [self._copy(item) for item in self._ordered_locked()]

    def get(self, item_id: str) -> QueueItem | None:
        with self._condition:
            item = self._items.get(item_id)
            return self._copy(item) if item else None

    def remove(self, item_id: str) -> QueueItem | None:
        with self._condition:
            item = self._items.get(item_id)
            if item is None:
                return None
            if item.status != "queued":
                raise ConfigError("Only waiting queue items can be removed")
            removed = self._copy(item)
            del self._items[item_id]
            for position, queued in enumerate(self._queued_locked()):
                queued.position = position
            self._save_locked()
            self._condition.notify_all()
            return removed

    def move(self, item_id: str, direction: str) -> QueueItem | None:
        if direction not in ("up", "down"):
            raise ConfigError("direction must be 'up' or 'down'")
        with self._condition:
            item = self._items.get(item_id)
            if item is None:
                return None
            if item.status != "queued":
                raise ConfigError("Only waiting queue items can be reordered")
            queued = self._queued_locked()
            index = next(i for i, value in enumerate(queued) if value.id == item_id)
            target = index - 1 if direction == "up" else index + 1
            if 0 <= target < len(queued):
                queued[index].position, queued[target].position = (
                    queued[target].position,
                    queued[index].position,
                )
                self._save_locked()
                self._condition.notify_all()
            return self._copy(item)

    def _mark_running_locked(self, item: QueueItem) -> tuple[str, str]:
        item.status = "running"
        item.gate_status = "released"
        item.started_at = utc_now().isoformat()
        item.gate_checked_at = item.started_at
        self._save_locked()
        return item.id, item.channel

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
                queued = self._queued_locked()
                if not queued:
                    self._condition.wait()
                    continue
                item = queued[0]
                if item.release_type == "at_time":
                    assert item.run_at is not None
                    delay = (parse_time(item.run_at) - utc_now()).total_seconds()
                    if delay > 0:
                        self._condition.wait(timeout=delay)
                        continue
                    item_id, channel = self._mark_running_locked(item)
                    game_gate = None
                else:
                    assert item.after_game_pk is not None
                    game_gate = (item.id, item.after_game_pk, item.after_game_date)

            if game_gate is not None:
                gate_item_id, game_pk, game_date = game_gate
                try:
                    status = self.game_status(game_pk, game_date)
                    error = None
                except RokuStreamError as exc:
                    status = None
                    error = f"{exc.code}: {exc}"
                except Exception as exc:
                    status = None
                    error = str(exc)
                with self._condition:
                    current = self._items.get(gate_item_id)
                    if current is None or current.status != "queued":
                        continue
                    current.gate_checked_at = utc_now().isoformat()
                    if error is not None:
                        current.gate_status = "unavailable"
                        current.gate_detail = error
                        self._save_locked()
                        self._condition.wait(timeout=self.poll_seconds)
                        continue
                    assert status is not None
                    current.gate_status = str(status.get("state") or "unknown").lower()
                    current.gate_detail = str(status.get("status") or "Checking game")
                    self._save_locked()
                    if status.get("finished") is not True:
                        self._condition.wait(timeout=self.poll_seconds)
                        continue
                    item_id, channel = self._mark_running_locked(current)

            try:
                result = self.executor(channel)
                execution_error = None
            except ControlBusyError:
                # A manual cue can own the Roku when a queue gate opens.
                # Keep this item at the head and retry when the controller frees.
                with self._condition:
                    current = self._items[item_id]
                    current.status = "queued"
                    current.started_at = None
                    current.gate_detail = "Waiting for the current Roku operation"
                    self._save_locked()
                    self._condition.wait(timeout=self.poll_seconds)
                continue
            except RokuStreamError as exc:
                result = None
                execution_error = {
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                }
            except Exception as exc:
                result = None
                execution_error = {
                    "code": "internal_error",
                    "message": str(exc),
                    "details": {},
                }
            with self._condition:
                current = self._items[item_id]
                current.status = "failed" if execution_error else "succeeded"
                current.completed_at = utc_now().isoformat()
                current.result = result
                current.error = execution_error
                self._save_locked()
                self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5)
