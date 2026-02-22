from __future__ import annotations

from typing import Any, Dict, List

from sc2.ids.unit_typeid import UnitTypeId as U

from .schema import StrategyConfig


class PlanExecutor:
    def __init__(self, bot, builder, strategy: StrategyConfig):
        self.bot = bot
        self.builder = builder
        self.strategy = strategy
        self._build_i = 0

    async def step(self):
        # TODO: implementar DSL (when/do). Por enquanto não faz nada.
        return


def parse_unit(name: str) -> U:
    # Ex: "BARRACKS" -> UnitTypeId.BARRACKS
    try:
        return getattr(U, name)
    except AttributeError as e:
        raise ValueError(f"UnitTypeId inválido no JSON: {name}") from e
