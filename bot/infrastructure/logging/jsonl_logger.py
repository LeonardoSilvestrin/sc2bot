from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, TextIO


class JsonlBotLogger:
    """Append-only structured logger intended only for local development."""

    def __init__(self, directory: Path, *, session_name: str | None = None) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        name = session_name or f"game-{timestamp}"
        self.path = directory / f"{name}.jsonl"
        self._file: TextIO = self.path.open("a", encoding="utf-8")
        self._lock = Lock()

    def event(
        self,
        name: str,
        *,
        component: str,
        game_time: float,
        data: dict[str, Any] | None = None,
    ) -> None:
        record = {
            "event": name,
            "component": component,
            "game_time": round(float(game_time), 3),
            "data": data or {},
        }
        line = json.dumps(
            record, ensure_ascii=False, default=str, separators=(",", ":")
        )
        with self._lock:
            self._file.write(line + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()
