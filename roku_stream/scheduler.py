from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .errors import ConfigError, RokuStreamError


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ConfigError("run_at must be an ISO-8601 timestamp with a timezone") from exc
    if parsed.tzinfo is None:
        raise ConfigError("run_at must include a timezone offset")
    return parsed.astimezone(timezone.utc)


@dataclass
class ScheduledJob:
    id: str
    channel: str
    run_at: str
    created_at: str
    status: str = "queued"
    started_at: str | None = None
    completed_at: str | None = None
    result: dict[str, object] | None = None
    error: dict[str, object] | None = None


class Scheduler:
    def __init__(
        self,
        state_file: Path,
        executor: Callable[[str], dict[str, object]],
    ) -> None:
        self.state_file = state_file
        self.executor = executor
        self._condition = threading.Condition()
        self._closed = False
        self._jobs = self._load()
        self._thread = threading.Thread(
            target=self._run, name="roku-stream-scheduler", daemon=True
        )
        self._thread.start()

    def _load(self) -> dict[str, ScheduledJob]:
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"Cannot read scheduler state {self.state_file}: {exc}") from exc
        if not isinstance(raw, list):
            raise ConfigError("Scheduler state must be a JSON array")
        jobs: dict[str, ScheduledJob] = {}
        for item in raw:
            if not isinstance(item, dict):
                raise ConfigError("Invalid job in scheduler state")
            job = ScheduledJob(**item)
            if job.status == "running":
                job.status = "queued"
                job.started_at = None
            jobs[job.id] = job
        return jobs

    def _save_locked(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                [asdict(job) for job in self._jobs.values()], indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.state_file)

    def add(self, channel: str, run_at: datetime) -> ScheduledJob:
        run_at = run_at.astimezone(timezone.utc)
        if run_at <= utc_now():
            raise ConfigError("run_at must be in the future")
        now = utc_now().isoformat()
        job = ScheduledJob(
            id=uuid.uuid4().hex,
            channel=channel,
            run_at=run_at.isoformat(),
            created_at=now,
        )
        with self._condition:
            self._jobs[job.id] = job
            self._save_locked()
            self._condition.notify_all()
        return ScheduledJob(**asdict(job))

    def get(self, job_id: str) -> ScheduledJob | None:
        with self._condition:
            job = self._jobs.get(job_id)
            return ScheduledJob(**asdict(job)) if job else None

    def list(self) -> list[ScheduledJob]:
        with self._condition:
            return [
                ScheduledJob(**asdict(job))
                for job in sorted(self._jobs.values(), key=lambda item: item.run_at)
            ]

    def cancel(self, job_id: str) -> ScheduledJob | None:
        with self._condition:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job.status != "queued":
                raise ConfigError("Only queued jobs can be cancelled")
            job.status = "cancelled"
            job.completed_at = utc_now().isoformat()
            self._save_locked()
            self._condition.notify_all()
            return ScheduledJob(**asdict(job))

    def _next_locked(self) -> tuple[ScheduledJob | None, float | None]:
        queued = [job for job in self._jobs.values() if job.status == "queued"]
        if not queued:
            return None, None
        job = min(queued, key=lambda item: item.run_at)
        delay = max(0.0, (parse_time(job.run_at) - utc_now()).total_seconds())
        return job, delay

    def _run(self) -> None:
        while True:
            with self._condition:
                if self._closed:
                    return
                job, delay = self._next_locked()
                if job is None:
                    self._condition.wait()
                    continue
                if delay and delay > 0:
                    self._condition.wait(timeout=delay)
                    continue
                job.status = "running"
                job.started_at = utc_now().isoformat()
                self._save_locked()
                job_id, channel = job.id, job.channel
            try:
                result = self.executor(channel)
                error = None
            except RokuStreamError as exc:
                result = None
                error = {
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                }
            except Exception as exc:  # Keep the scheduler alive on unexpected failures.
                result = None
                error = {"code": "internal_error", "message": str(exc), "details": {}}
            with self._condition:
                current = self._jobs[job_id]
                current.status = "failed" if error else "succeeded"
                current.completed_at = utc_now().isoformat()
                current.result = result
                current.error = error
                self._save_locked()

    def close(self) -> None:
        with self._condition:
            self._closed = True
            self._condition.notify_all()
        self._thread.join(timeout=5)
