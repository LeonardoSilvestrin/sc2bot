from __future__ import annotations

from enum import Enum, auto


class MacroPosture(Enum):
    """Legacy coarse risk intent used by current macro and behavior code.

    The enum is a shared contract.  Strategy owns deriving the value; keeping
    the contract in ``bot.domain`` lets the deprecated Awareness re-export
    remain compatible without making Awareness depend on Strategy.
    """

    DEFENSE = auto()
    BALANCED = auto()
    GREED = auto()
    RECOVERY = auto()
