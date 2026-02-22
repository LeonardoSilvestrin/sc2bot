# terran_bot.py
from __future__ import annotations

from sc2.bot_ai import BotAI

from bot.core.state import BotState
from bot.core.logger import JsonlLogger
from bot.engine.economy import Economy
from bot.engine.placement import Placement
from bot.engine.builder import Builder
from bot.strategy.loader import load_strategy
from bot.strategy.plan_executor import PlanExecutor
from bot.behaviors.macro import MacroBehavior
from bot.behaviors.drop import DropBehavior
from bot.behaviors.combat import CombatBehavior


class TerranBot(BotAI):
    def __init__(self, strat_name: str, debug: bool = True):
        super().__init__()
        if not strat_name:
            raise ValueError("strat_name é obrigatório (ex: 'default').")

        self.debug = debug
        self.ctx = BotState()
        self.strategy = load_strategy(strat_name)

        self.log = JsonlLogger(enabled=True)
        self.log.emit("bot_init", {"strategy": self.strategy.name, "strat_name": strat_name})

        self.econ = Economy(self, ctx=self.ctx, logger=self.log)
        self.place = Placement(self, ctx=self.ctx, logger=self.log)

        self.builder = Builder(self, self.econ, self.place, self.ctx, logger=self.log)
        self.plan = PlanExecutor(self, self.builder, self.strategy, ctx=self.ctx, logger=self.log)

        self.macro = MacroBehavior(
            self,
            self.econ,
            self.builder,
            econ_cfg=self.strategy.economy,
            cfg=self.strategy.behaviors.macro,
            ctx=self.ctx,
            logger=self.log,
            debug=debug,
        )

        self.combat = CombatBehavior(self, self.ctx, logger=self.log, debug=debug)
        self.drop = DropBehavior(self, self.strategy.drop, self.ctx, logger=self.log, debug=debug)

        self._last_snapshot_iter = -999999

    async def on_step(self, iteration: int):
        self.ctx.iteration = int(iteration)

        if iteration - self._last_snapshot_iter >= 22:
            self._last_snapshot_iter = iteration
            self.log.emit(
                "snapshot",
                {
                    "iteration": int(iteration),
                    "time": float(self.time),
                    "minerals": int(self.minerals),
                    "gas": int(self.vespene),
                    "supply_used": int(self.supply_used),
                    "supply_cap": int(self.supply_cap),
                    "supply_left": int(self.supply_left),
                    "workers": int(self.workers.amount),
                },
                meta={"strategy": self.strategy.name, "iter": int(self.ctx.iteration)},
            )

        await self.macro.step()
        await self.plan.step()

        if self.strategy.behaviors.combat.enabled:
            await self.combat.step()
        if self.strategy.drop.enabled:
            await self.drop.step()

    async def on_end(self, game_result):
        self.log.emit("game_end", {"result": str(game_result), "time": float(self.time)})
        self.log.close()