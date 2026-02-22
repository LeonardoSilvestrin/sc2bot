#run.py
from __future__ import annotations

from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.maps import get
from sc2.player import Bot, Computer

import argparse
from bot.debuglog import DebugLogger
from bot.orchestrator import Orchestrator
from bot.strategy import load_strategy


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--strat", default=None, help="Name of strategy JSON in strats/<name>.json")
    return p.parse_args()


ARGS = _parse_args()
STRAT = load_strategy(ARGS.strat)


class TerranBotV1(BotAI):
    def __init__(self, debug: bool = True):
        super().__init__()
        self.debug = debug
        self.dbg = DebugLogger(base_dir="debug_runs", enabled=debug)
        self.orch: Orchestrator | None = None
        self._strat = STRAT

    # IMPORTANT: this fork calls on_start() without await -> must be sync
    # IMPORTANT: this fork calls on_start() without await -> must be sync
    def on_start(self):
        map_name = getattr(self.game_info, "map_name", "unknown_map")
        self.dbg.start_run(map_name=map_name, opponent="Computer")

    async def on_step(self, iteration: int):
        self.iteration = iteration  # Essential: cooldown logic depends on this
        if self.orch is None:
            self.orch = Orchestrator(self, debug=self.debug, strat=self._strat)
        await self.orch.step()

    # IMPORTANT: this fork calls on_end() without await -> must be sync
    def on_end(self, game_result):
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