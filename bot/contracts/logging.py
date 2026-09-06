from __future__ import annotations

from typing import Any, Protocol


class BotLogger(Protocol):
    """Structured event logger used by the application and domain modules."""

    def event(
        self,
        name: str,
        *,
        component: str,
        game_time: float,
        data: dict[str, Any] | None = None,
    ) -> None: ...

    def close(self) -> None: ...
