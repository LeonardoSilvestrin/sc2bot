"""What gets played: the table of games, and one game of it.

The matrix is fixed on purpose. A slice is measured by playing the same games
before and after it, so what they are has to be written down where anyone can
read it -- one line per game, ``map, race, how the AI opens``:

- `BASE` is the nine games a slice is measured on: every race against every way
  the built-in AI opens, on one map. A change that only shows against one
  opening is not a change worth keeping.
- `WIDE` is those nine on every map, for when the question is whether the map
  was carrying the result.

`games_of` hands back one of them, or the product of whatever axis was asked
for instead; `matrix` turns games into `GameSpec`s, which is what a run plays
and what a record stores.

The list a hand writes is next door: `matrix.yml`, read by `config.py`, is
where a run of ten games against a Protoss rush on one map is asked for, and
it is what a plain `bench.py run` plays. The tables here are the fixed ones,
the matrices a slice is measured on, kept in code so that they cannot be
edited by accident.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, NamedTuple


class Game(NamedTuple):
    """One game, as it reads: where, against whom, and how they open."""

    map_name: str
    race: str
    ai_build: str


# The rotation: every map the matrix knows, and what a `random` map draws
# from. It is the ladder pool, so it is what changes when the season does.
MAPS = (
    "IncorporealAIE_v4",
    "LeyLinesAIE_v3",
    "MagannathaAIE_v2",
    "PersephoneAIE_v4",
    "PylonAIE_v4",
    "TorchesAIE_v4",
    "UltraloveAIE_v2",
)
# The maps the wide table walks, which is not the whole rotation: nine games on
# each of seven maps is sixty-three, and whether the map was carrying a result
# is already answered by three.
WIDE_MAPS = ("PersephoneAIE_v4", "TorchesAIE_v4", "IncorporealAIE_v4")
# A map drawn when the games are built, not written into the table.
RANDOM = "random"
# The map the nine base games are played on. `RANDOM` draws one of `MAPS` per
# run -- the same one for all nine, a different one next time -- which is what
# a run you are watching wants. Two runs that have to be compared need the
# same map: name one here, or pass --maps.
BASE_MAP = RANDOM
RACES = ("Zerg", "Terran", "Protoss")
# How the built-in AI opens: a rush, a macro game, and one it draws itself.
AI_BUILDS = ("Rush", "Macro", "RandomBuild")

# The nine games a slice is measured on.
BASE = (
    #    map       race       how the AI opens
    Game(BASE_MAP, "Zerg",    "Rush"),
    Game(BASE_MAP, "Zerg",    "Macro"),
    Game(BASE_MAP, "Zerg",    "RandomBuild"),
    Game(BASE_MAP, "Terran",  "Rush"),
    Game(BASE_MAP, "Terran",  "Macro"),
    Game(BASE_MAP, "Terran",  "RandomBuild"),
    Game(BASE_MAP, "Protoss", "Rush"),
    Game(BASE_MAP, "Protoss", "Macro"),
    Game(BASE_MAP, "Protoss", "RandomBuild"),
)
# The same nine on every map: twenty-seven games.
WIDE = tuple(game._replace(map_name=map_name) for map_name in WIDE_MAPS for game in BASE)
MATRICES: Mapping[str, tuple[Game, ...]] = {"base": BASE, "wide": WIDE}

# --- what a run plays when nothing is asked for ----------------------------
# Edit these two lines instead of a launch configuration; every flag wins over
# them.
# `bench.py run --matrix`: file (the games matrix.yml lists), base (the nine
# above) or wide (27).
DEFAULT_MATRIX = "file"
# `run.py --matrix`: single (one game), builds (the three openings), wide, or
# file (the games matrix.yml lists).
DEFAULT_LAUNCHER = "single"


def games_of(
    name: str = "base",
    *,
    maps: Sequence[str] | None = None,
    races: Sequence[str] | None = None,
    ai_builds: Sequence[str] | None = None,
) -> tuple[Game, ...]:
    """The named matrix; an axis given by hand replaces that column, and the
    games become the product of the three."""

    table = _drawn(MATRICES[name])
    if maps is None and races is None and ai_builds is None:
        return table
    return tuple(
        Game(map_name, race, ai_build)
        for map_name in (tuple(maps) if maps else _column(table, "map_name"))
        for race in (tuple(races) if races else _column(table, "race"))
        for ai_build in (tuple(ai_builds) if ai_builds else _column(table, "ai_build"))
    )


def _drawn(games: Sequence[Game]) -> tuple[Game, ...]:
    """A table that asks for a random map gets one, once: every game of the
    run is played on the same drawn map, and the next run draws again."""

    if not any(game.map_name == RANDOM for game in games):
        return tuple(games)
    map_name = random.choice(MAPS)
    return tuple(
        game._replace(map_name=map_name) if game.map_name == RANDOM else game for game in games
    )


def _column(games: Sequence[Game], field: str) -> tuple[str, ...]:
    """The values of one column, each once, in the order the table has them."""

    return tuple(dict.fromkeys(getattr(game, field) for game in games))


@dataclass(frozen=True, slots=True)
class GameSpec:
    """One game of the matrix; `game_id` names its directory."""

    index: int
    map_name: str
    enemy_race: str
    difficulty: str
    ai_build: str
    # The seed the game is played with; None lets it draw its own, which is
    # what the launcher does when no file wrote one down.
    seed: int | None
    # Game seconds before the game is called off; None lets it run as long as
    # it takes, which is what a single watched game does.
    game_time_limit: float | None
    # The bot's army style, by name; None lets the bot draw one.
    army: str | None = None

    @property
    def game_id(self) -> str:
        suffix = "" if self.army is None else f"-{self.army}"
        return (
            f"{self.index:03d}-{self.map_name}-{self.enemy_race}-"
            f"{self.difficulty}-{self.ai_build}-{self.seed}{suffix}"
        )

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> GameSpec:
        # A record written before a field existed holds its default.
        return cls(**{name: data[name] for name in cls.__dataclass_fields__ if name in data})


def matrix(
    games: Sequence[Game],
    *,
    difficulties: Sequence[str] = ("VeryHard",),
    armies: Sequence[str | None] = (None,),
    repeats: int = 1,
    seed: int = 1,
    game_time_limit: float,
) -> tuple[GameSpec, ...]:
    """Every game, at every difficulty, with every army style, `repeats` times,
    in a fixed order; repeat k plays seed + k.

    The same arguments always give the same games, so a baseline and a
    challenger run on the same matrix play the same maps, opponents and seeds.
    """

    if repeats <= 0:
        raise ValueError("repeats must be positive")
    if game_time_limit <= 0.0:
        raise ValueError("game_time_limit must be positive")
    for name, values in (("games", games), ("difficulties", difficulties), ("armies", armies)):
        if not values:
            raise ValueError(f"{name} must not be empty")
    specs: list[GameSpec] = []
    for repeat in range(repeats):
        for game in games:
            for difficulty in difficulties:
                for army in armies:
                    specs.append(
                        GameSpec(
                            index=len(specs),
                            map_name=game.map_name,
                            enemy_race=game.race,
                            difficulty=difficulty,
                            ai_build=game.ai_build,
                            seed=seed + repeat,
                            game_time_limit=float(game_time_limit),
                            army=army,
                        )
                    )
    return tuple(specs)
