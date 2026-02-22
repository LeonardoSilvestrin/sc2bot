# behaviors/supply.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId as U

from .base import Behavior, TickBudget


@dataclass
class SupplyCfg:
    enabled: bool = True
    trigger_supply_left: int = 2


class SupplyBehavior(Behavior):
    name = "supply"

    def __init__(self, bot: Any, builder: Any, cfg: SupplyCfg, ctx: Any, logger: Any | None = None, debug: bool = True):
        super().__init__(bot, ctx, logger=logger, debug=debug)
        self.builder = builder
        self.cfg = cfg

    async def step(self, budget: TickBudget) -> bool:
        if not self.cfg.enabled:
            return False

        if self.bot.supply_left > int(self.cfg.trigger_supply_left):
            return False

        # não gasta budget se não vai tentar
        if self.builder.pending(U.SUPPLYDEPOT) > 0:
            return False

        if not budget.spend(1):
            return False

        did = await self.builder.try_build(U.SUPPLYDEPOT)
        if self.log:
            self.log.emit(
                "behavior_supply",
                {"attempt": True, "did": bool(did), "supply_left": int(self.bot.supply_left)},
                meta={"iter": int(self.ctx.iteration)},
            )
        return bool(did)