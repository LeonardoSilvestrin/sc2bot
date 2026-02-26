# bot/mind/self.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.data import Result

from bot.devlog import DevLogger
from bot.sensors.threat_sensor import Threat
from bot.intel.enemy_build_intel import EnemyBuildIntelConfig, derive_enemy_build_intel
from bot.mind.attention import derive_attention
from bot.mind.awareness import Awareness
from bot.mind.body import UnitLeases
from bot.mind.ego import Ego, EgoConfig
from bot.tasks.base_task import TaskTick

from bot.tasks.defend_task import Defend
from bot.tasks.scout_task import Scout
from bot.tasks.macro import MacroAresBioStandardTick, MacroAresRushDefenseTick, MacroOpeningTick

from bot.planners.defense_planner import DefensePlanner
from bot.planners.intel_planner import IntelPlanner
from bot.planners.macro_planner import MacroPlanner


@dataclass
class RuntimeApp:
    log: DevLogger
    awareness: Awareness
    threat: Threat
    body: UnitLeases
    ego: Ego
    enemy_build_cfg: EnemyBuildIntelConfig
    debug: bool = True

    @classmethod
    def build(cls, *, log: DevLogger, debug: bool = True) -> "RuntimeApp":
        awareness = Awareness(log=log)
        threat = Threat(defend_radius=22.0, min_enemy=1)
        body = UnitLeases(default_ttl=8.0)

        ego = Ego(
            body=body,
            log=log,
            cfg=EgoConfig(
                singleton_domains=frozenset({"MACRO"}),  # only one active MACRO mission at a time
                threat_block_start_at=70,
                threat_force_preempt_at=90,
                non_preemptible_grace_s=2.5,
                default_failure_cooldown_s=8.0,
            ),
        )

        defend_task = Defend(log=log, log_every_iters=11)

        scout_task = Scout(
            awareness=awareness,
            log=log,
            trigger_time=25.0,
            log_every=6.0,
            see_radius=14.0,
        )

        opening_macro_task = MacroOpeningTick(log=log, log_every_iters=22, scv_cap=60)

        bio_standard_task = MacroAresBioStandardTick(
            log=log,
            scv_cap=66,
            target_bases=2,
            log_every_iters=22,
        )

        rush_defense_task = MacroAresRushDefenseTick(
            log=log,
            scv_cap=40,
            target_bases=1,
            log_every_iters=22,
        )

        defense_planner = DefensePlanner(defend_task=defend_task, log=log)
        intel_planner = IntelPlanner(awareness=awareness, log=log, scout_task=scout_task)

        macro_planner = MacroPlanner(
            opening_task=opening_macro_task,
            bio_task=bio_standard_task,
            rush_defense_task=rush_defense_task,
            backoff_urgency=60,
            log=log,
        )

        ego.register_planners([defense_planner, intel_planner, macro_planner])

        return cls(
            log=log,
            awareness=awareness,
            threat=threat,
            body=body,
            ego=ego,
            enemy_build_cfg=EnemyBuildIntelConfig(),
            debug=bool(debug),
        )

    async def on_start(self, bot) -> None:
        try:
            self.body.reset()
        except Exception:
            pass
        if self.log:
            self.log.emit("runtime_start", {})

    async def on_step(self, bot, *, iteration: int) -> None:
        now = float(getattr(bot, "time", 0.0))

        attention = derive_attention(bot, awareness=self.awareness, threat=self.threat, log=self.log)

        derive_enemy_build_intel(
            bot,
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.enemy_build_cfg,
        )

        tick = TaskTick(iteration=int(iteration), time=now)
        await self.ego.tick(bot, tick=tick, attention=attention, awareness=self.awareness)

    async def on_end(self, bot, game_result: Result) -> None:
        if self.log:
            self.log.emit("game_end", {"result": str(game_result)})
