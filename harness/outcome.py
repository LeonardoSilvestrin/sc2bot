"""What happened to one game, under one rule.

A game that did not finish still has an outcome: `timeout` when it reached the
game time limit, `crash` when the process failed or ran out of wall time, and
`no_result` when it ended without one.

A game can also report a result the bot never earned. Ares' ``on_start`` raised
``IndexError`` on two specs of ``bench/7jk`` -- the client did not hand it the
map's expansions -- python-sc2 resigned on the first step, and the game reported
``Result.Defeat`` at ``game_time`` 0 with exit code 0, which the win rate
counted as a loss. A result reported without the bot ever advancing the game
clock is `not_played`: nothing about the bot was measured, so it counts in no
rate.

`outcome_of` applies the rule to what a record stored, so a run recorded before
the rule existed is judged by the same one.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

VICTORY = "victory"
DEFEAT = "defeat"
TIE = "tie"
TIMEOUT = "timeout"
CRASH = "crash"
NO_RESULT = "no_result"
NOT_PLAYED = "not_played"
OUTCOMES = (VICTORY, DEFEAT, TIE, TIMEOUT, CRASH, NO_RESULT, NOT_PLAYED)
# Outcomes of a game that measured nothing about the bot: they are counted and
# named, and left out of every rate and mean.
UNMEASURED = (NOT_PLAYED,)
_RESULTS = {"Victory": VICTORY, "Defeat": DEFEAT, "Tie": TIE}
# The last step the bot played before python-sc2 stops a game at its time
# limit is up to a few game loops short of it.
LIMIT_TOLERANCE = 1.0


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

    A game that reported a result while the bot's clock never left zero was not
    played by the bot: python-sc2 resigns on the first step when the bot's
    `on_start` raises, and reports that resignation as a defeat.
    """

    if result is not None and game_time is not None and game_time <= 0.0:
        return NOT_PLAYED
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


def outcome_of(record: Mapping[str, Any]) -> str:
    """The outcome of a stored record under the current rule.

    A record keeps what the game reported, not only the verdict, so the verdict
    is recomputed: runs recorded before a rule existed are summarized under the
    same rule as new ones. A record without those fields keeps its own verdict.
    """

    spec = record.get("spec") or {}
    if "game_time_limit" not in spec or "result" not in record:
        return str(record["outcome"])
    return outcome(
        result=record["result"],
        game_time=record.get("game_time"),
        game_time_limit=float(spec["game_time_limit"]),
        exit_code=record.get("exit_code"),
        wall_timed_out=bool(record.get("wall_timed_out")),
    )


def needs_replay(record: Mapping[str, Any]) -> bool:
    """Whether a recorded game should be played again.

    A game the bot never played measured nothing, so its record is not a reason
    to skip the spec.
    """

    return outcome_of(record) in UNMEASURED
