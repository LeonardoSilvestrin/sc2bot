# bot/mind/self.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sc2.data import Result

from bot.devlog import DevLogger
from bot.infra.unit_leases import UnitLeases
from bot.inteligence.threat import Threat
from bot.mind.attention import derive_attention
from bot.mind.awareness import Awareness
from bot.mind.ego import Ego, EgoConfig
from bot.planners.defense_planner import DefensePlanner
from bot.planners.intel_planner import IntelPlanner
from bot.tasks.base import TaskTick
from bot.tasks.defend import Defend
from bot.tasks.scout import Scout


@dataclass
class RuntimeApp:
    """
    Orquestrador único do bot.
    O main.py só delega pra cá.
    """

    log: DevLogger
    awareness: Awareness
    threat: Threat
    leases: UnitLeases
    ego: Ego
    debug: bool = True

    @classmethod
    def build(cls, *, log: DevLogger, debug: bool = True) -> "RuntimeApp":
        awareness = Awareness()
        threat = Threat(defend_radius=22.0, min_enemy=1)

        leases = UnitLeases(default_ttl=8.0)
        ego = Ego(
            leases=leases,
            log=log,
            cfg=EgoConfig(command_budget=2, soft_preempt_at=60, hard_preempt_at=80),
        )

        # tasks
        defend_task = Defend(log=log, log_every_iters=11)
        scout_task = Scout(
            leases=leases,
            awareness=awareness,
            log=log,
            trigger_time=25.0,
            log_every=6.0,
            see_radius=14.0,
        )

        # planners
        defense_planner = DefensePlanner(awareness=awareness, defend_task=defend_task)
        intel_planner = IntelPlanner(awareness=awareness, log=log, scout_task=scout_task)

        ego.register_planner(defense_planner)
        ego.register_planner(intel_planner)

        return cls(
            log=log,
            awareness=awareness,
            threat=threat,
            leases=leases,
            ego=ego,
            debug=debug,
        )

    async def on_start(self, bot) -> None:
        map_name = bot.game_info.map_name
        enemy = bot.enemy_race.name
        fname = f"MyBot__{map_name}__vs__{enemy}__start.jsonl".replace(" ", "_")
        self.log.set_file(fname)

        self.log.emit("bot_init", {"strategy": "terran_builds.yml/Default"}, meta={"map": map_name})

        if self.debug:
            print(f"[on_start] devlog={self.log.log_dir}/{fname}")

    async def on_step(self, bot, *, iteration: int) -> None:
        now = float(getattr(bot, "time", 0.0))
        attention = derive_attention(bot, awareness=self.awareness, threat=self.threat)

        await self.ego.tick(
            bot,
            tick=TaskTick(iteration=iteration, time=now),
            attention=attention,
            awareness=self.awareness,
        )

        if iteration % 44 == 0:
            intel = self.awareness.intel_snapshot(now=now)
            mem_intel = self.awareness.mem.snapshot(now=now, prefix=("intel",), max_age=600.0)

            self.log.emit(
                "awareness_snapshot",
                {
                    "time": round(now, 2),
                    "attention": {
                        "opening_done": attention.opening_done,
                        "threatened": attention.threatened,
                        "urgency": attention.defense_urgency,
                        "enemy_count_near_bases": attention.enemy_count_near_bases,
                        "orbital_ready_to_scan": attention.orbital_ready_to_scan,
                        "orbital_energy": round(attention.orbital_energy, 1),
                    },
                    "intel": intel,
                    "mem_intel": mem_intel,
                    "events_tail": self.awareness.tail_events(6),
                },
            )

        if self.debug and iteration % 44 == 0:
            intel = self.awareness.intel_snapshot(now=now)
            print(
                f"[tick] iter={iteration} t={now:.1f} "
                f"s={int(bot.supply_used)}/{int(bot.supply_cap)} "
                f"threat={attention.threatened} urg={attention.defense_urgency} "
                f"intel(scv={intel['scv_dispatched']}/{intel['scv_arrived_main']}, scan={intel['scanned_enemy_main']})"
            )

    async def on_end(self, bot, *, game_result: Result) -> None:
        self.log.emit("game_end", {"result": str(game_result)})