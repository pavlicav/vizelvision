"""Bounded, persistent channel-cue history and timestamped diagnostics."""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path


class OperationStore:
    def __init__(self, directory: Path, retain: int = 100):
        self.directory = directory
        self.retain = retain
        self.lock = threading.Lock()
        directory.mkdir(parents=True, exist_ok=True)

    def recover_interrupted(self, current_id: str | None = None) -> None:
        # A restart cannot resume remote navigation from an old observation.
        for path in self.directory.glob("*.json"):
            if path.stem == current_id:
                continue
            record = self.get(path.stem)
            if record and record.get("active"):
                record.update(active=False, phase="error", completed_at=datetime.now(timezone.utc).isoformat(),
                              message="Service restarted before cue completion",
                              error={"code": "operation_interrupted", "message": "Service restarted before cue completion"})
                self.save(record)

    def get(self, operation_id: str) -> dict | None:
        if not re.fullmatch(r"[0-9a-f]{32}", operation_id):
            return None
        with self.lock:
            try:
                return json.loads((self.directory / f"{operation_id}.json").read_text())
            except (OSError, ValueError):
                return None

    def save(self, record: dict) -> None:
        operation_id = record["id"]
        with self.lock:
            path = self.directory / f"{operation_id}.json"
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(record, indent=2, default=str) + "\n")
            temporary.replace(path)

    def prune(self) -> None:
        with self.lock:
            paths = sorted(self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for path in paths[self.retain:]:
                for suffix in (".json", ".jsonl", ".ppm"):
                    path.with_suffix(suffix).unlink(missing_ok=True)


class EventLog(list):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def append(self, event: dict) -> None:
        entry = {**event, "at": datetime.now(timezone.utc).isoformat()}
        super().append(entry)
        with self.path.open("a") as stream:
            stream.write(json.dumps(entry, default=str) + "\n")
