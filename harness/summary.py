"""What a run of the matrix came to.

Every game the bot played counts in the win rate: a crash or a timeout is not a
win. A game the bot never played counts in neither the rate nor the mean
duration -- it measured nothing -- but is named in the counts and in `played`
versus `games`, so a matrix that lost cells to the environment cannot look like
a matrix that was won.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .outcome import OUTCOMES, UNMEASURED, VICTORY, outcome_of

# z for a 95% two-sided interval.
_Z95 = 1.959963984540054


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
    (map, race, difficulty, build).

    Every game the bot played counts in the win rate: a crash or a timeout is
    not a win. A game the bot never played counts in neither the rate nor the
    mean duration -- it measured nothing -- but is named in the counts and in
    `played` versus `games`, so a matrix that lost cells to the environment
    cannot look like a matrix that was won."""

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
    measured: list[Mapping[str, Any]] = []
    for record in records:
        name = outcome_of(record)
        counts[name] += 1
        if name not in UNMEASURED:
            measured.append(record)
    games, played = len(records), len(measured)
    low, high = wilson(counts[VICTORY], played)
    durations = [
        float(record["game_time"]) for record in measured if record.get("game_time") is not None
    ]
    return {
        "games": games,
        "played": played,
        "outcomes": counts,
        "win_rate": counts[VICTORY] / played if played else None,
        "win_rate_95": [low, high],
        "mean_game_time": sum(durations) / len(durations) if durations else None,
    }
