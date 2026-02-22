#economy.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple
from sc2.ids.unit_typeid import UnitTypeId as U


@dataclass(frozen=True)
class Cost:
    minerals: int
    vespene: int


@dataclass
class Budget:
    reserved_m: int = 0
    reserved_g: int = 0

    def reset(self) -> None:
        self.reserved_m = 0
        self.reserved_g = 0


class Economy:
    def __init__(self, bot: Any):
        self.bot = bot
        self.budget = Budget()

        # Minimal fallback table (only for when calculate_cost is unavailable).
        self._fallback: Dict[U, Cost] = {
            U.SUPPLYDEPOT: Cost(100, 0),
            U.BARRACKS: Cost(150, 0),
            U.REFINERY: Cost(75, 0),
            U.FACTORY: Cost(150, 100),
            U.STARPORT: Cost(150, 100),
            U.SCV: Cost(50, 0),
            U.MARINE: Cost(50, 0),
            U.MEDIVAC: Cost(100, 100),
        }

    def cost(self, unit_type: U) -> Cost:
        calc = getattr(self.bot, "calculate_cost", None)
        if callable(calc):
            c = calc(unit_type)
            return Cost(int(getattr(c, "minerals", 0)), int(getattr(c, "vespene", 0)))
        return self._fallback.get(unit_type, Cost(0, 0))

    def available(self) -> Tuple[int, int]:
        m = int(getattr(self.bot, "minerals", 0)) - self.budget.reserved_m
        g = int(getattr(self.bot, "vespene", 0)) - self.budget.reserved_g
        return m, g

    def can_afford_reserved(self, unit_type: U) -> bool:
        c = self.cost(unit_type)
        m, g = self.available()
        return m >= c.minerals and g >= c.vespene

    def reserve(self, unit_type: U) -> None:
        c = self.cost(unit_type)
        self.budget.reserved_m += c.minerals
        self.budget.reserved_g += c.vespene