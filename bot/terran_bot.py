from __future__ import annotations

from sc2.bot_ai import BotAI

from bot.core.state import BotState
from bot.core.logger import JsonlLogger
from bot.engine.economy import Economy
from bot.engine.placement import Placement
from bot.engine.builder import Builder
from bot.strategy.loader import load_strategy
from bot.strategy.plan_executor import PlanExecutor
from bot.behaviors.drop import DropBehavior


class TerranBot(BotAI):
    def __init__(self, strat_name: str = "default", debug: bool = True):
        super().__init__()
        self.debug = debug

        # NÃO use self.state: isso é GameState do python-sc2
        self.ctx = BotState()

        self.strategy = load_strategy(strat_name)

        self.log = JsonlLogger(enabled=True)
        self.log.emit("bot_init", {"strategy": self.strategy.name})

        self.econ = Economy(self)
        self.place = Placement(self)

        # passe o ctx (estado do seu bot) para os módulos
        self.builder = Builder(self, self.econ, self.place, self.ctx)

        self.plan = PlanExecutor(self, self.builder, self.strategy, logger=self.log)
        self.drop = DropBehavior(self, self.strategy.drop, self.ctx, debug=debug)

        self._last_snapshot_iter = -999999

    async def on_step(self, iteration: int):
        self.ctx.iteration = iteration

        # snapshot a cada ~1 segundo (22.4 iterações por segundo em normal speed)
        if iteration - self._last_snapshot_iter >= 22:
            self._last_snapshot_iter = iteration
            self.log.emit(
                "snapshot",
                {
                    "iteration": iteration,
                    "time": float(self.time),
                    "minerals": int(self.minerals),
                    "gas": int(self.vespene),
                    "supply_used": int(self.supply_used),
                    "supply_cap": int(self.supply_cap),
                    "supply_left": int(self.supply_left),
                    "workers": int(self.workers.amount),
                },
                meta={"strategy": self.strategy.name},
            )

        await self.plan.step()

        if self.strategy.drop.enabled:
            await self.drop.step()

    async def on_end(self, game_result):
        # python-sc2 chama quando o jogo termina
        self.log.emit("game_end", {"result": str(game_result), "time": float(self.time)})
        self.log.close()