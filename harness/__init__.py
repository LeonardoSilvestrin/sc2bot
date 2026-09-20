"""HARNESS: a fixed matrix of local games, each tied to what produced it.

Pure and testable without StarCraft; ``bench.py`` runs the games and ``run.py``
can walk the same matrix with the game window open.

```text
config.py    the list a hand writes: matrix.yml, read into GameSpecs
matrix.py    what gets played: the table of games (map, race, opening), GameSpec
outcome.py   what happened to one game, including the ones nobody played
record.py    the record written next to a replay and a log
summary.py   what a run of the matrix came to
```
"""

from .config import (
    DEFAULT_PATH as MATRIX_PATH,
)
from .config import (
    MATRIX_FILE,
    MatrixFileError,
)
from .config import (
    specs as file_specs,
)
from .matrix import (
    AI_BUILDS,
    BASE,
    BASE_MAP,
    DEFAULT_LAUNCHER,
    DEFAULT_MATRIX,
    MAPS,
    MATRICES,
    RACES,
    RANDOM,
    WIDE,
    WIDE_MAPS,
    Game,
    GameSpec,
    games_of,
    matrix,
)
from .outcome import (
    CRASH,
    DEFEAT,
    LIMIT_TOLERANCE,
    NO_RESULT,
    NOT_PLAYED,
    OUTCOMES,
    TIE,
    TIMEOUT,
    UNMEASURED,
    VICTORY,
    needs_replay,
    outcome,
    outcome_of,
)
from .record import RECORD_SCHEMA, build_record, identity, load_records, started_event
from .summary import summarize, wilson

__all__ = [
    "AI_BUILDS",
    "BASE",
    "BASE_MAP",
    "CRASH",
    "DEFAULT_LAUNCHER",
    "DEFAULT_MATRIX",
    "DEFEAT",
    "LIMIT_TOLERANCE",
    "MAPS",
    "MATRICES",
    "MATRIX_FILE",
    "MATRIX_PATH",
    "NOT_PLAYED",
    "NO_RESULT",
    "OUTCOMES",
    "RACES",
    "RANDOM",
    "RECORD_SCHEMA",
    "TIE",
    "TIMEOUT",
    "UNMEASURED",
    "VICTORY",
    "WIDE",
    "WIDE_MAPS",
    "Game",
    "GameSpec",
    "MatrixFileError",
    "build_record",
    "file_specs",
    "games_of",
    "identity",
    "load_records",
    "matrix",
    "needs_replay",
    "outcome",
    "outcome_of",
    "started_event",
    "summarize",
    "wilson",
]
