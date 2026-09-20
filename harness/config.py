"""The games to play, written down in a file instead of in the flags.

`matrix.yml` is the list: one line per game -- race, how the built-in AI opens,
the map, which army the bot plays -- and `games: 10` on a line to ask for ten
of that one. What a line leaves out comes from `defaults`, so it can be as
short as `{race: Protoss, strategy: Rush, games: 10}`.

`bench.py run` and `run.py --matrix file` read the same file, so the games
being measured and the games being watched are written in one place; the
tables of `matrix.py` are still there behind `--matrix base|wide`.

It is YAML because YAML takes comments: the cheat sheet of every name that
fits -- the maps, the races, the AI's openings, the bot's army styles -- lives
at the top of the file, next to the games themselves. The names are checked
against the game and the bot before any game is launched, so a typo costs a
message and not an afternoon.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from .matrix import MAPS, RANDOM, GameSpec

# `bench.py run --matrix file`, `run.py --matrix file`: play what the file says.
MATRIX_FILE = "file"
# The file read when no other one is named; it sits next to the tables it
# stands in for.
DEFAULT_PATH = Path(__file__).resolve().parent / "matrix.yml"

# The three keys the file itself has.
TOP_LEVEL = ("seed", "defaults", "matrix")
# What an entry is made of, and what a field is worth when neither the entry
# nor `defaults` says.
DEFAULTS: Mapping[str, Any] = {
    "map": RANDOM,
    "race": "Random",
    "strategy": "RandomBuild",
    "difficulty": "VeryHard",
    "army": None,
    "games": 1,
    "time_limit": 1800.0,
}
FIELDS = tuple(DEFAULTS)
DEFAULT_SEED = 1


class MatrixFileError(ValueError):
    """Something a hand wrote in the file does not fit; the message says what.

    The entry points turn it into the one line a person reads, not a traceback.
    """


def specs(
    path: Path | str = DEFAULT_PATH,
    *,
    seed: int | None = None,
    time_limit: float | None = None,
) -> tuple[GameSpec, ...]:
    """Every game the file asks for, in the order it lists them.

    An entry asking for ten games becomes ten, one after the other, each with
    its own seed. `seed` and `time_limit` are what a flag gave by hand; without
    them the file decides.
    """

    path = Path(path)
    document = _document(path)
    where = path.name
    _check_keys(document, TOP_LEVEL, where, "the file")
    defaults = _mapping(document.get("defaults", {}), where, '"defaults"')
    _check_keys(defaults, FIELDS, where, '"defaults"')
    entries = document.get("matrix")
    if not isinstance(entries, list) or not entries:
        raise MatrixFileError(f'{where}: "matrix" must be a list with at least one game in it')
    base_seed = _seed(document, where) if seed is None else int(seed)
    known = _known()
    # A file that asks for a random map draws one, once: every game of the run
    # is played on the same drawn map, and the next run draws again.
    drawn = random.choice(MAPS)
    games: list[GameSpec] = []
    for number, entry in enumerate(entries, start=1):
        at = f"game {number}"
        given = _mapping(entry, where, at)
        _check_keys(given, FIELDS, where, at)
        values = {**DEFAULTS, **defaults, **given}
        for field, names in known.items():
            _check_name(values[field], names, where, at, field)
        map_name = _text(values["map"], where, at, "map")
        count = _count(values["games"], where, at)
        limit = _limit(values["time_limit"], where, at) if time_limit is None else float(time_limit)
        for repeat in range(count):
            games.append(
                GameSpec(
                    index=len(games),
                    map_name=drawn if map_name == RANDOM else map_name,
                    enemy_race=values["race"],
                    difficulty=values["difficulty"],
                    ai_build=values["strategy"],
                    seed=base_seed + repeat,
                    game_time_limit=limit,
                    army=values["army"],
                )
            )
    return tuple(games)


def _known() -> Mapping[str, tuple[Any, ...]]:
    """What the game and the bot accept, asked of them rather than copied."""

    from sc2.data import AIBuild, Difficulty, Race

    from bot.ego.planners.economy.knowledge.styles import STYLES

    return {
        "race": tuple(name for name in Race.__members__ if name != "NoRace"),
        "strategy": tuple(AIBuild.__members__),
        "difficulty": tuple(Difficulty.__members__),
        # None is a name too: it lets the bot draw its own style.
        "army": (*sorted(STYLES), None),
    }


def _document(path: Path) -> Mapping[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise MatrixFileError(f"{path}: no such file") from error
    except OSError as error:
        raise MatrixFileError(f"{path}: {error.strerror or error}") from error
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise MatrixFileError(f"{path.name}{_at_line(error)}: {_said(error)}") from error
    return _mapping(document, path.name, "the file")


def _at_line(error: yaml.YAMLError) -> str:
    """Where YAML gave up, when it says; a file a hand writes is read by eye."""

    mark = getattr(error, "problem_mark", None)
    return "" if mark is None else f", line {mark.line + 1}"


def _said(error: yaml.YAMLError) -> str:
    return getattr(error, "problem", None) or str(error).splitlines()[0]


def _mapping(value: Any, where: str, at: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise MatrixFileError(f"{where}, {at}: expected a line like {{race: Zerg}}")
    return value


def _check_keys(values: Mapping[str, Any], known: Sequence[str], where: str, at: str) -> None:
    unknown = [key for key in values if key not in known]
    if unknown:
        raise MatrixFileError(
            f"{where}, {at}: unknown {', '.join(sorted(unknown))} (known: {', '.join(known)})"
        )


def _check_name(value: Any, known: Sequence[Any], where: str, at: str, field: str) -> None:
    if value not in known:
        raise MatrixFileError(
            f"{where}, {at}: unknown {field} {value!r} (known: {', '.join(_spelled(known))})"
        )


def _spelled(names: Sequence[Any]) -> tuple[str, ...]:
    return tuple("null" if name is None else str(name) for name in names)


def _text(value: Any, where: str, at: str, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise MatrixFileError(f"{where}, {at}: {field} must be a name, not {value!r}")
    return value


def _count(value: Any, where: str, at: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MatrixFileError(
            f"{where}, {at}: games must be a whole number above zero, not {value!r}"
        )
    return value


def _limit(value: Any, where: str, at: str) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise MatrixFileError(
            f"{where}, {at}: time_limit must be seconds above zero, not {value!r}"
        )
    return float(value)


def _seed(document: Mapping[str, Any], where: str) -> int:
    value = document.get("seed", DEFAULT_SEED)
    if not isinstance(value, int) or isinstance(value, bool):
        raise MatrixFileError(f"{where}: seed must be a whole number, not {value!r}")
    return value
