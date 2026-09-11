from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    # Type-only: the economy controller imports this port, so a runtime
    # import of its models here would be circular.
    from bot.engine.economy.models import EconomicAction, EconomicFeedback


class EconomyCommands(Protocol):
    """Executes one funded economic action for `EconomyController`.

    The economy counterpart of `MissionCommands`, and deliberately narrower:
    there is no unit tag to authorize, because an economic action commands
    no unit a mission owns. Which SCV lays a structure, or which Barracks
    trains the Marine, is the adapter's operational choice. ``None`` means
    no progress was possible this frame, not failure.
    """

    def dispatch(self, action: EconomicAction) -> EconomicFeedback | None:
        ...
