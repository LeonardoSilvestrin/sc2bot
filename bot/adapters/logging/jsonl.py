from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, TextIO

# Bumped whenever the record envelope changes shape.
SCHEMA_VERSION = 2
FAULT_COMPONENT = "adapters.logging"


class JsonlBotLogger:
    """Append-only structured logger intended only for local development.

    Every line is one strict-JSON record in a layer-neutral envelope::

        schema      SCHEMA_VERSION
        run         this game's run id, one per logger
        seq         1, 2, 3, ... in write order: the causal order of the log
        iteration   the frame the event was emitted in; null outside a frame
        event, component
        game_time   exactly as given, never rounded
        data

    Nothing is stringified. A record whose data is not strict JSON -- an
    unsupported object, NaN or infinity -- is replaced by a
    ``logging.record_rejected`` record that names the event and the error,
    so the fault is visible instead of silently coerced.
    """

    def __init__(
        self,
        directory: Path,
        *,
        session_name: str | None = None,
        run_id: str | None = None,
    ) -> None:
        directory = directory.resolve()
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        name = session_name or f"game-{timestamp}"
        if not name.strip() or name in {".", ".."} or Path(name).name != name:
            raise ValueError("session_name must be a non-empty file name")
        self.session_directory = (directory / name).resolve()
        if self.session_directory.parent != directory:
            raise ValueError("session_name must stay inside the log directory")
        self.run_id = uuid.uuid4().hex if run_id is None else run_id
        if not self.run_id.strip():
            raise ValueError("run_id must not be blank")
        self.session_directory.mkdir(exist_ok=False)
        self.path = self.session_directory / "game.jsonl"
        self._file: TextIO = self.path.open("x", encoding="utf-8")
        self._lock = Lock()
        self._sequence = 0
        self._iteration: int | None = None

    def begin_frame(self, iteration: int) -> None:
        with self._lock:
            self._iteration = int(iteration)

    def end_frame(self) -> None:
        with self._lock:
            self._iteration = None

    def event(
        self,
        name: str,
        *,
        component: str,
        game_time: float,
        data: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self._sequence += 1
            envelope = {
                "schema": SCHEMA_VERSION,
                "run": self.run_id,
                "seq": self._sequence,
                "iteration": self._iteration,
            }
            try:
                line = _encode(
                    {
                        **envelope,
                        "event": name,
                        "component": component,
                        "game_time": float(game_time),
                        "data": data or {},
                    }
                )
            except (TypeError, ValueError) as error:
                line = _encode(
                    {
                        **envelope,
                        "event": "logging.record_rejected",
                        "component": FAULT_COMPONENT,
                        "game_time": _finite_or_none(game_time),
                        "data": {
                            "rejected_event": str(name),
                            "rejected_component": str(component),
                            "error": f"{type(error).__name__}: {error}",
                        },
                    }
                )
            self._file.write(line + "\n")
            self._file.flush()

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()


def _encode(record: dict[str, Any]) -> str:
    return json.dumps(
        record, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def _finite_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
