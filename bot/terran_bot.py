from __future__ import annotations

from sc2.bot_ai import BotAI

from bot.core.state import BotState
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
        self.state = BotState()
        self.strategy = load_strategy(strat_name)

        self.econ = Economy(self)
        self.place = Placement(self)
        self.builder = Builder(self, self.econ, self.place, self.state)

        self.plan = PlanExecutor(self, self.builder, self.strategy)
        self.drop = DropBehavior(self, self.strategy.drop, self.state, debug=debug)

    async def on_step(self, iteration: int):
        self.state.iteration = iteration
        await self.plan.step()
        if self.strategy.drop.enabled:
            await self.drop.step()
