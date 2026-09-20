"""What the enemy's opening means, read from what Attention recorded of it.

`knowledge` holds the per-race expectations (when a natural is early, what
belongs in a main, how much gas is standard); `belief` scores one opening
against them. Calibrating the read means editing `knowledge`.
"""

from .belief import DEFAULT_CONFIG, OpeningBelief, OpeningBeliefConfig, read_opening
from .knowledge import BY_RACE, OpeningExpectations, expectations_for

__all__ = [
    "BY_RACE",
    "DEFAULT_CONFIG",
    "OpeningBelief",
    "OpeningBeliefConfig",
    "OpeningExpectations",
    "expectations_for",
    "read_opening",
]
