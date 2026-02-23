#bot/main.py
from __future__ import annotations

import os
from typing import Optional

from ares import AresBot
from sc2.data import Result

from bot.actions.base import TickContext
from bot.actions.scout import ScoutAction
from bot.core.orchestrator import Orchestrator
from bot.devlog import DevLogger
from bot.policies.drop import DropPolicy
from bot.policies.threat import ThreatPolicy


class MyBot(AresBot):
    def __init__(self, game_step_override: Optional[int] = None, *, debug: bool = True):
        super().__init__(game_step_override)
        self.debug = debug

        self.log = DevLogger(enabled=True)

        # policies (legado por enquanto)
        self.threat_policy = ThreatPolicy(defend_radius=22.0, min_enemy=1)
        self.drop_policy = DropPolicy(enabled=True, min_marines=8, load_count=8)

        # orchestrator + actions
        self.orch = Orchestrator(command_budget=2, defense_floor=80)
        self.orch.add(ScoutAction(trigger_time=25.0, log_every=6.0, see_radius=14.0))

    async def on_start(self) -> None:
        await super().on_start()

        map_name = self.game_info.map_name
        enemy = self.enemy_race.name

        fname = f"MyBot__{map_name}__vs__{enemy}__start.jsonl".replace(" ", "_")
        self.log.set_file(fname)

        if self.debug:
            print("[on_start] Ares build runner enabled")
            print(f"[on_start] devlog={os.path.join(self.log.log_dir, fname)}")

        self.log.emit("bot_init", {"strategy": "terran_builds.yml/Default"}, meta={"map": map_name})

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)

        opening_done = bool(self.build_order_runner.build_completed)

        # Threat sempre avalia (mesmo na opening)
        threat_report = self.threat_policy.evaluate(self)

        ctx = TickContext(
            iteration=iteration,
            time=float(self.time),
            opening_done=opening_done,
            threatened=bool(threat_report.threatened),
        )

        # 1) Orchestrator roda SEMPRE (inclusive durante opening)
        await self.orch.tick(self, ctx)

        # 2) Defesa reativa (pode ficar fora do orch por enquanto)
        if threat_report.threatened:
            acted = await self.threat_policy.act(self, threat_report)
            if acted:
                self.log.emit(
                    "threat_defend",
                    {
                        "iteration": iteration,
                        "time": round(self.time, 2),
                        "enemy_count": threat_report.enemy_count,
                        "radius": threat_report.radius,
                        "pos": [round(threat_report.threat_pos.x, 1), round(threat_report.threat_pos.y, 1)]
                        if threat_report.threat_pos
                        else None,
                        "opening_done": opening_done,
                    },
                )

        # 3) Drop só pós-opening e sem ameaça (por enquanto)
        if opening_done and (not threat_report.threatened):
            drop_acted = await self.drop_policy.act(self)
            if drop_acted and iteration % 11 == 0:
                self.log.emit(
                    "drop_tick",
                    {"iteration": iteration, "time": round(self.time, 2), "phase": str(self.drop_policy.state.phase)},
                )

        if self.debug and iteration % 44 == 0:
            print(
                f"[tick] iter={iteration} t={self.time:.1f} "
                f"m={int(self.minerals)} g={int(self.vespene)} "
                f"s={int(self.supply_used)}/{int(self.supply_cap)} "
                f"opening_done={opening_done} threat={threat_report.threatened} "
                f"drop={self.drop_policy.state.phase}"
            )

    async def on_end(self, game_result: Result) -> None:
        await super().on_end(game_result)
        if self.debug:
            print(f"[game_end] result={game_result}")
        self.log.emit("game_end", {"result": str(game_result)})