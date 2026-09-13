from __future__ import annotations

import json
from typing import Any

from bot.engine.economy.models import (
    EconomicAction,
    EconomicFeedback,
    EconomicFeedbackKind,
)


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.iteration: int | None = None

    def begin_frame(self, iteration: int) -> None:
        self.iteration = iteration

    def end_frame(self) -> None:
        self.iteration = None

    def event(self, name, *, component, game_time, data=None) -> None:
        # Every event any test produces must already be strict JSON: no NaN,
        # nothing the real log writer would have to stringify.
        json.dumps({"data": data or {}, "game_time": game_time}, allow_nan=False)
        self.events.append(
            {
                "name": name,
                "component": component,
                "game_time": game_time,
                "iteration": self.iteration,
                "data": data or {},
            }
        )

    def close(self) -> None:
        return None


class FakeCommands:
    def __init__(self) -> None:
        self.commands: list[tuple] = []
        self.kept_available: set[int] = set()

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

    def attack_move(
        self,
        *,
        mission_id,
        unit_tag,
        target,
        success_at_distance,
    ) -> None:
        self.commands.append(
            ("attack_move", mission_id, unit_tag, target, success_at_distance)
        )

    def attack_unit(
        self,
        *,
        mission_id,
        unit_tag,
        target_unit_tag,
    ) -> None:
        self.commands.append(("attack_unit", mission_id, unit_tag, target_unit_tag))

    def safe_path_to(
        self,
        *,
        mission_id,
        unit_tag,
        target,
        success_at_distance,
        search_radius=14.0,
        keep_available=False,
    ) -> None:
        command = (
            "safe_path_to",
            mission_id,
            unit_tag,
            target,
            success_at_distance,
        )
        if search_radius != 14.0:
            command += (search_radius,)
        self.commands.append(command)
        if keep_available:
            self.kept_available.add(unit_tag)
        else:
            self.kept_available.discard(unit_tag)

    def release(self, *, mission_id, unit_tag) -> None:
        self.commands.append(("release", mission_id, unit_tag))

    def use_ability(self, *, mission_id, unit_tag, ability) -> None:
        self.commands.append(("use_ability", mission_id, unit_tag, ability))


class FakeEconomyCommands:
    def __init__(self) -> None:
        self.commands: list[tuple] = []

    def dispatch(self, action: EconomicAction) -> EconomicFeedback:
        proposal = action.proposal
        self.commands.append((proposal.kind.name.lower(), proposal.target_count))
        return EconomicFeedback(
            action_id=action.action_id,
            kind=EconomicFeedbackKind.DISPATCHED,
            reason="fake_command_accepted",
        )
