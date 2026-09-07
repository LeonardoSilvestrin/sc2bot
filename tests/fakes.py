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

    def path_to(
        self,
        *,
        mission_id,
        unit_tag,
        target,
        success_at_distance,
    ) -> None:
        self.commands.append(
            ("path_to", mission_id, unit_tag, target, success_at_distance)
        )

    def release(self, *, mission_id, unit_tag) -> None:
        self.commands.append(("release", mission_id, unit_tag))


class FakeEconomyCommands:
    def __init__(self) -> None:
        self.commands: list[tuple] = []

    def produce_worker(self, *, to_count) -> None:
        self.commands.append(("produce_worker", to_count))

    def produce_supply(self, *, base_location) -> None:
        self.commands.append(("produce_supply", base_location))

    def expand(self, *, to_count) -> None:
        self.commands.append(("expand", to_count))
