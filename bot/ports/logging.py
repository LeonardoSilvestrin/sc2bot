from __future__ import annotations

from typing import Any, Protocol


class BotLogger(Protocol):
    """Structured event logger used by the application and domain modules.

    ``begin_frame`` / ``end_frame`` bracket one game frame, so a writer can
    stamp every event emitted in between with that frame's iteration. Events
    outside a frame -- game start and end -- carry none.
    """

    def event(
        self,
        name: str,
        *,
        component: str,
        game_time: float,
        data: dict[str, Any] | None = None,
    ) -> None:
        ...

    def begin_frame(self, iteration: int) -> None:
        ...

    def end_frame(self) -> None:
        ...

    def close(self) -> None:
        ...
