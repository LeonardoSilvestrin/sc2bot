from __future__ import annotations

from sc2.bot_ai import BotAI
from sc2.main import run_game
from sc2.data import Race, Difficulty
from sc2.player import Bot, Computer
from sc2.maps import get
from sc2.ids.unit_typeid import UnitTypeId as U

class DiagBot(BotAI):
    def __init__(self):
        super().__init__()
        self._started = False

    # Alguns forks chamam sync, outros async; vamos suportar os dois.
    def on_start(self):
        self._started = True
        print("[DIAG] on_start (sync) called")

    async def on_start_async(self):
        self._started = True
        print("[DIAG] on_start_async called")

    async def on_step(self, iteration: int):
        # prova de vida
        if iteration % 10 == 0:
            print(f"[DIAG] on_step iter={iteration} minerals={self.minerals} supply={self.supply_used}/{self.supply_cap}")

        # prova de ação simples: treina SCV se possível
        if self.townhalls.ready.exists:
            cc = self.townhalls.ready.first
            if cc.is_idle and self.can_afford(U.SCV):
                await self.do(cc.train(U.SCV))

        await self.distribute_workers()

if __name__ == "__main__":
    run_game(
        get("PersephoneAIE_v4"),
        [
            Bot(Race.Terran, DiagBot()),
            Computer(Race.Zerg, Difficulty.Easy),
        ],
        realtime=False,
    )