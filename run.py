#run.py
from __future__ import annotations

from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.maps import get
from sc2.player import Bot, Computer

from bot.debuglog import DebugLogger
from bot.orchestrator import Orchestrator


class TerranBotV1(BotAI):
    def __init__(self, debug: bool = True):
        super().__init__()
        self.debug = debug
        self.dbg = DebugLogger(base_dir="debug_runs", enabled=debug)
        self.orch: Orchestrator | None = None

    async def on_start(self):
        map_name = getattr(self.game_info, "map_name", "unknown_map")
        self.dbg.start_run(map_name=map_name, opponent="Computer")

    async def on_step(self, iteration: int):
        if self.orch is None:
            # Import já está no topo; evitar import relativo que quebra quando roda como script
            self.orch = Orchestrator(self, debug=self.debug)

        await self.orch.step()

    async def on_end(self, game_result):
        # python-sc2 chama on_end em vários forks; se não chamar, tudo bem
        try:
            if getattr(self, "dbg", None) is not None:
                self.dbg.log_state({"event": "run_end", "result": str(game_result)})
                self.dbg.close()
        except Exception:
            pass


if __name__ == "__main__":
    run_game(
        get("PersephoneAIE_v4"),
        [
            Bot(Race.Terran, TerranBotV1(debug=True)),
            Computer(Race.Zerg, Difficulty.Easy),
        ],
        realtime=False,
    )