# behaviors/macro.py
from __future__ import annotations

from typing import Any

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.strategy.schema import EconomyCfg, MacroBehaviorCfg


class MacroBehavior:
    """
    Macro contínuo (homeostase):
    - distribute workers
    - train scv até target
    - auto_supply: depots quando supply baixo
    """

    def __init__(
        self,
        bot: Any,
        economy: Any,
        builder: Any,
        econ_cfg: EconomyCfg,
        cfg: MacroBehaviorCfg,
        ctx: Any,
        logger: Any | None = None,
        debug: bool = True,
    ):
        self.bot = bot
        self.econ = economy
        self.builder = builder
        self.econ_cfg = econ_cfg
        self.cfg = cfg
        self.ctx = ctx
        self.log = logger
        self.debug = debug

    async def step(self) -> None:
        if not self.cfg.enabled:
            return

        if self.cfg.auto_workers:
            await self.econ.step()

        if self.cfg.auto_scv:
            await self.econ.train_scv(int(self.econ_cfg.scv_target))

        if self.cfg.auto_supply:
            await self._auto_supply()

    async def _auto_supply(self) -> bool:
        trigger = int(self.econ_cfg.depot_trigger_supply_left)

        if self.bot.supply_left > trigger:
            return False

        if self.builder.pending(U.SUPPLYDEPOT) > 0:
            return False

        did = await self.builder.try_build(U.SUPPLYDEPOT)

        if self.log:
            self.log.emit(
                "macro_supply",
                {"did": bool(did), "supply_left": int(self.bot.supply_left), "trigger": int(trigger)},
                meta={"iter": int(self.ctx.iteration)},
            )

        return bool(did)