from __future__ import annotations

from typing import Any


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def event(self, name, *, component, game_time, data=None) -> None:
        self.events.append(
            {
                "name": name,
                "component": component,
                "game_time": game_time,
                "data": data or {},
            }
        )

    def close(self) -> None:
        return None


class FakeCommands:
    def __init__(self) -> None:
        self.commands: list[tuple] = []

    def move(self, *, action_id, unit_tag, target, queue=False) -> None:
        self.commands.append(("move", action_id, unit_tag, target, queue))

    def attack(self, *, action_id, unit_tag, target, queue=False) -> None:
        self.commands.append(("attack", action_id, unit_tag, target, queue))
