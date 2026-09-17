"""HARNESS: a fixed matrix of local games, each tied to what produced it.

Pure and testable without StarCraft: the matrix, the outcome of a game, the
record written next to its replay and log, and the summary over records.
``bench.py`` runs the games.

Every record links the outcome to the bot commit, the Ares commit, the
decision configuration fingerprint (read from the game's own ``game.started``
event), the map, the opponent, the seed, the replay and the JSONL log. A game
that did not finish still gets a record: ``timeout`` when it reached the game
time limit, ``crash`` when the process failed or ran out of wall time, and
``no_result`` when it ended without one.
"""

from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from bot.logs.identity import REPOSITORY_ROOT, describe_build

RECORD_SCHEMA = 1
VICTORY = "victory"
DEFEAT = "defeat"
TIE = "tie"
TIMEOUT = "timeout"
CRASH = "crash"
NO_RESULT = "no_result"
OUTCOMES = (VICTORY, DEFEAT, TIE, TIMEOUT, CRASH, NO_RESULT)
_RESULTS = {"Victory": VICTORY, "Defeat": DEFEAT, "Tie": TIE}
# The last step the bot played before python-sc2 stops a game at its time
# limit is up to a few game loops short of it.
LIMIT_TOLERANCE = 1.0
# z for a 95% two-sided interval.
_Z95 = 1.959963984540054


@dataclass(frozen=True, slots=True)
class GameSpec:
    """One game of the matrix; `game_id` names its directory."""

    index: int
    map_name: str
    enemy_race: str
    difficulty: str
    ai_build: str
    seed: int
    game_time_limit: float

    @property
    def game_id(self) -> str:
        return (
            f"{self.index:03d}-{self.map_name}-{self.enemy_race}-"
            f"{self.difficulty}-{self.ai_build}-{self.seed}"
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> GameSpec:
        return cls(**{name: data[name] for name in cls.__dataclass_fields__})


def matrix(
    *,
    maps: Sequence[str],
    races: Sequence[str],
    difficulties: Sequence[str],
    ai_builds: Sequence[str],
    games: int,
    seed: int,
    game_time_limit: float,
) -> tuple[GameSpec, ...]:
    """Every combination, `games` times, in a fixed order; game k plays seed + k.

    The same arguments always give the same games, so a baseline and a
    challenger run on the same matrix play the same maps, opponents and seeds.
    """

    if games <= 0:
        raise ValueError("games must be positive")
    if game_time_limit <= 0.0:
        raise ValueError("game_time_limit must be positive")
    for name, values in (
        ("maps", maps),
        ("races", races),
        ("difficulties", difficulties),
        ("ai_builds", ai_builds),
    ):
        if not values:
            raise ValueError(f"{name} must not be empty")
    specs: list[GameSpec] = []
    for repeat in range(games):
        for map_name in maps:
            for race in races:
                for difficulty in difficulties:
                    for ai_build in ai_builds:
                        index = len(specs)
                        specs.append(
                            GameSpec(
                                index=index,
                                map_name=map_name,
                                enemy_race=race,
                                difficulty=difficulty,
                                ai_build=ai_build,
                                seed=seed + repeat,
                                game_time_limit=float(game_time_limit),
                            )
                        )
    return tuple(specs)


def outcome(
    *,
    result: str | None,
    game_time: float | None,
    game_time_limit: float,
    exit_code: int | None,
    wall_timed_out: bool,
) -> str:
    """What happened to one game.

    python-sc2 ends a game at its time limit as a Tie, so a Tie within
    `LIMIT_TOLERANCE` of the limit is a timeout, not a draw.
    """

    if wall_timed_out or exit_code not in (0, None):
        return CRASH
    if result is None:
        return NO_RESULT if exit_code == 0 else CRASH
    name = result.removeprefix("Result.")
    if (
        name == "Tie"
        and game_time is not None
        and game_time >= game_time_limit - LIMIT_TOLERANCE
    ):
        return TIMEOUT
    return _RESULTS.get(name, NO_RESULT)


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


def wilson(successes: int, trials: int) -> tuple[float, float]:
    """95% Wilson score interval of a proportion; (0, 1) without trials."""

    if trials <= 0:
        return 0.0, 1.0
    share = successes / trials
    z2 = _Z95 * _Z95
    centre = (share + z2 / (2 * trials)) / (1 + z2 / trials)
    spread = (
        _Z95 * math.sqrt(share * (1 - share) / trials + z2 / (4 * trials * trials))
    ) / (1 + z2 / trials)
    return max(0.0, centre - spread), min(1.0, centre + spread)


def summarize(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Outcome counts, win rate with its interval and duration, overall and per
    (map, race, difficulty, build). Every game counts in the win rate: a crash
    or a timeout is not a win."""

    records = list(records)
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        spec = record["spec"]
        key = "/".join(
            (spec["map_name"], spec["enemy_race"], spec["difficulty"], spec["ai_build"])
        )
        groups.setdefault(key, []).append(record)
    return {
        "overall": _group(records),
        "builds": sorted(
            {
                json.dumps(record["build"], sort_keys=True)
                for record in records
            }
        ),
        "config_fingerprints": sorted(
            {str(record.get("config_fingerprint")) for record in records}
        ),
        "groups": {key: _group(groups[key]) for key in sorted(groups)},
    }


def _group(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {name: 0 for name in OUTCOMES}
    for record in records:
        counts[record["outcome"]] += 1
    games = len(records)
    low, high = wilson(counts[VICTORY], games)
    durations = [
        float(record["game_time"]) for record in records if record.get("game_time") is not None
    ]
    return {
        "games": games,
        "outcomes": counts,
        "win_rate": counts[VICTORY] / games if games else None,
        "win_rate_95": [low, high],
        "mean_game_time": sum(durations) / len(durations) if durations else None,
    }


def _existing(path: Path | None) -> str | None:
    return str(path) if path is not None and path.is_file() else None
