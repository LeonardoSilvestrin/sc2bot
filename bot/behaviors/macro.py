# behaviors/macro.py
from __future__ import annotations

from typing import Any

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.strategy.schema import EconomyCfg, MacroBehaviorCfg
from .base import TickBudget


class MacroBehavior:
    name = "macro"

    def __init__(
        self,
        bot: Any,
        econ: Any,
        builder: Any,
        ctx: Any,
        logger: Any | None = None,
        debug: bool = True,
    ):
        self.bot = bot
        self.econ = econ
        self.builder = builder
        self.ctx = ctx
        self.log = logger
        self.debug = debug
        self._supply_cooldown_until_iter = 0

    async def step(self, budget: TickBudget, cfg: dict) -> bool:
        """
        cfg esperado:
          { "econ": EconomyCfg, "macro": MacroBehaviorCfg }
        """
        econ_cfg: EconomyCfg = cfg["econ"]
        macro_cfg: MacroBehaviorCfg = cfg["macro"]

        if not macro_cfg.enabled:
            return False

        did_any = False

        if macro_cfg.auto_workers:
            await self.econ.step()

        if macro_cfg.auto_scv:
            await self.econ.train_scv(int(econ_cfg.scv_target))

        if macro_cfg.auto_supply and budget.remaining > 0:
            if await self._auto_supply(int(econ_cfg.depot_trigger_supply_left)):
                # supply é “ação” -> consome budget
                budget.spend(1)
                did_any = True

        return did_any

    async def _auto_supply(self, trigger: int) -> bool:
        bot = self.bot
        it = int(getattr(self.ctx, "iteration", 0))
        if it < self._supply_cooldown_until_iter:
            return False

        if bot.supply_left > trigger:
            return False

        if self.builder.pending(U.SUPPLYDEPOT) > 0:
            return False

        did = await self.builder.try_build(U.SUPPLYDEPOT)

        if self.log:
            self.log.emit(
                "macro_supply",
                {"did": bool(did), "supply_left": int(bot.supply_left), "trigger": int(trigger)},
                meta={"iter": it},
            )

        self._supply_cooldown_until_iter = it + 22
        return bool(did)