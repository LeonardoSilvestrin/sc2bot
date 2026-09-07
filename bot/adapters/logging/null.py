from __future__ import annotations

from typing import Any


class NullBotLogger:
    """Logger used on the ladder. It never opens or writes a file."""

    def event(
        self,
        name: str,
        *,
        component: str,
        game_time: float,
        data: dict[str, Any] | None = None,
    ) -> None:
        return None

    def close(self) -> None:
        return None
