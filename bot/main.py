#bot/main.py
from __future__ import annotations

import os
from typing import Optional

from ares import AresBot
from sc2.data import Result

from bot.devlog import DevLogger
from bot.policies.drop import DropPolicy
from bot.policies.threat import ThreatPolicy
from bot.policies.scout import ScoutPolicy

from bot.services.roles import RoleService
from bot.services.map import MapService


class MyBot(AresBot):
    def __init__(self, game_step_override: Optional[int] = None, *, debug: bool = True):
        super().__init__(game_step_override)
        self.debug = debug

        # services (comunicação com managers/mediator)
        self.roles: RoleService | None = None
        self.maps: MapService | None = None

        # policies
        self.threat_policy = ThreatPolicy(defend_radius=22.0, min_enemy=1)
        self.drop_policy = DropPolicy(enabled=True, min_marines=8, load_count=8)
        self.scout_policy = ScoutPolicy()

        # devlog
        self.log = DevLogger(enabled=True)

    async def on_start(self) -> None:
        await super().on_start()

        # services prontos (sem fallback)
        self.roles = RoleService(self)
        self.maps = MapService(self)

        map_name = self.game_info.map_name  # sem getattr
        enemy = self.enemy_race.name        # sem try/except

        fname = f"MyBot__{map_name}__vs__{enemy}__start.jsonl".replace(" ", "_")
        self.log.set_file(fname)

        if self.debug:
            print("[on_start] Ares build runner enabled")
            print(f"[on_start] devlog={os.path.join(self.log.log_dir, fname)}")

        self.log.emit("bot_init", {"strategy": "terran_builds.yml/Default"}, meta={"map": map_name})

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)

        # opening do Ares
        if not self.build_order_runner.build_completed:
            if self.debug and iteration % 22 == 0:
                print(
                    f"[opening] iter={iteration} "
                    f"t={self.time:.1f} "
                    f"m={int(self.minerals)} g={int(self.vespene)} "
                    f"s={int(self.supply_used)}/{int(self.supply_cap)}"
                )
            if iteration % 44 == 0:
                self.log.emit(
                    "opening_tick",
                    {
                        "iteration": iteration,
                        "time": round(self.time, 2),
                        "minerals": int(self.minerals),
                        "gas": int(self.vespene),
                        "supply_used": int(self.supply_used),
                        "supply_cap": int(self.supply_cap),
                    },
                )
            return

        # services obrigatórios (se estiver None -> crash, como você quer)
        roles = self.roles
        maps = self.maps
        assert roles is not None
        assert maps is not None

        # 1) threat primeiro
        threat_report = self.threat_policy.evaluate(self)
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
                    },
                )

        # 2) scout (exemplo: só se não estiver ameaçado)
        if not threat_report.threatened:
            scout_acted = await self.scout_policy.act(self, roles=roles, maps=maps)
            if scout_acted:
                self.log.emit(
                    "scout_dispatch",
                    {
                        "iteration": iteration,
                        "time": round(self.time, 2),
                        "scout_tag": self.scout_policy.state.scout_tag,
                        "target": [round(maps.enemy_main().x, 1), round(maps.enemy_main().y, 1)],
                    },
                )

        # 3) drop (depois)
        if not threat_report.threatened:
            drop_acted = await self.drop_policy.act(self)
            if drop_acted and iteration % 11 == 0:
                self.log.emit(
                    "drop_tick",
                    {
                        "iteration": iteration,
                        "time": round(self.time, 2),
                        "phase": str(self.drop_policy.state.phase),
                    },
                )

        if self.debug and iteration % 44 == 0:
            print(
                f"[post_opening] iter={iteration} "
                f"t={self.time:.1f} "
                f"m={int(self.minerals)} g={int(self.vespene)} "
                f"s={int(self.supply_used)}/{int(self.supply_cap)} "
                f"threat={threat_report.threatened} "
                f"scout_dispatched={self.scout_policy.state.dispatched} "
                f"drop={self.drop_policy.state.phase}"
            )

    async def on_end(self, game_result: Result) -> None:
        await super().on_end(game_result)
        if self.debug:
            print(f"[game_end] result={game_result}")
        self.log.emit("game_end", {"result": str(game_result)})