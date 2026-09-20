"""The record written next to a replay and a log.

Every record links the outcome to the bot commit, the Ares commit, the decision
configuration fingerprint (read from the game's own ``game.started`` event),
the map, the opponent, the seed, the replay and the JSONL log: a result nobody
can tie back to what produced it is not evidence. A game that did not finish
still gets a record.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bot.logs.identity import REPOSITORY_ROOT, describe_build

from .matrix import GameSpec
from .outcome import outcome

RECORD_SCHEMA = 1


def identity(root: Path = REPOSITORY_ROOT) -> dict[str, str | bool | None]:
    """The bot and Ares commits, and whether the checkout differs from the commit."""

    bot = describe_build(root)
    ares = describe_build(root / "ares-sc2")
    return {
        "commit": bot["commit"],
        "branch": bot["branch"],
        "ares_commit": ares["commit"],
        "dirty": _dirty(root),
    }


def _dirty(root: Path) -> bool | None:
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(status.stdout.strip())


def started_event(log: Path) -> dict[str, Any] | None:
    """The data of the first ``game.started`` event in a JSONL log."""

    if not log.is_file():
        return None
    with log.open(encoding="utf-8") as lines:
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("event") == "game.started":
                return record.get("data") or {}
    return None


def build_record(
    spec: GameSpec,
    *,
    label: str,
    identity: Mapping[str, str | None],
    result: str | None,
    game_time: float | None,
    exit_code: int | None,
    wall_timed_out: bool,
    wall_seconds: float,
    replay: Path | None,
    log: Path | None,
    error: str | None = None,
) -> dict[str, Any]:
    started = started_event(log) if log is not None else None
    return {
        "schema": RECORD_SCHEMA,
        "label": label,
        "game_id": spec.game_id,
        "spec": spec.to_json(),
        "outcome": outcome(
            result=result,
            game_time=game_time,
            game_time_limit=spec.game_time_limit,
            exit_code=exit_code,
            wall_timed_out=wall_timed_out,
        ),
        "result": result,
        "game_time": game_time,
        "exit_code": exit_code,
        "wall_timed_out": wall_timed_out,
        "wall_seconds": wall_seconds,
        "build": dict(identity),
        "config_fingerprint": None if started is None else started.get("config_fingerprint"),
        "configs": None if started is None else started.get("configs"),
        "replay": _existing(replay),
        "log": _existing(log),
        "error": error,
    }


def load_records(directory: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*/result.json"))
    ]
    return sorted(records, key=lambda record: record["spec"]["index"])


def _existing(path: Path | None) -> str | None:
    return str(path) if path is not None and path.is_file() else None
