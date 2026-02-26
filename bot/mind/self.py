# bot/mind/self.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.data import Result

from bot.devlog import DevLogger
from bot.sensors.threat_sensor import Threat
from bot.intel.enemy_build_intel import EnemyBuildIntelConfig, derive_enemy_build_intel
from bot.intel.my_army_composition_intel import MyArmyCompositionConfig, derive_my_army_composition_intel
from bot.mind.attention import derive_attention
from bot.mind.awareness import Awareness
from bot.mind.body import UnitLeases
from bot.mind.ego import Ego, EgoConfig
from bot.tasks.base_task import TaskTick

from bot.tasks.defend_task import Defend
from bot.tasks.scout_task import Scout
from bot.tasks.macro.opening import MacroOpeningTick

from bot.planners.defense_planner import DefensePlanner
from bot.planners.intel_planner import IntelPlanner

from bot.planners.production_planner import ProductionPlanner
from bot.planners.spending_planner import SpendingPlanner
from bot.planners.housekeeping_planner import HousekeepingPlanner


@dataclass
class RuntimeApp:
    log: DevLogger
    awareness: Awareness
    threat: Threat
    body: UnitLeases
    ego: Ego
    enemy_build_cfg: EnemyBuildIntelConfig
    my_comp_cfg: MyArmyCompositionConfig
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
                # New singleton macro domains: allow spending+production+housekeeping concurrently,
                # without changing Ego internals.
                singleton_domains=frozenset({"MACRO_SPENDING", "MACRO_PRODUCTION", "MACRO_HOUSEKEEPING"}),
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

        # Opening remains a tiny SCV-only macro while BuildRunner/YML does the rest.
        opening_macro_task = MacroOpeningTick(log=log, log_every_iters=22, scv_cap=60)

        defense_planner = DefensePlanner(defend_task=defend_task, log=log)
        intel_planner = IntelPlanner(awareness=awareness, log=log, scout_task=scout_task)

        spending_planner = SpendingPlanner(
            target_bases_default=2,
            flood_m=800,
            flood_hi_m=1400,
            flood_hold_s=12.0,
            log=log,
        )

        production_planner = ProductionPlanner(
            scv_cap=66,
            log=log,
        )

        housekeeping_planner = HousekeepingPlanner(
            interval_s=35.0,
            cooldown_s=6.0,
            lease_ttl_s=12.0,
            score=18,
            log=log,
        )

        # Keep opening as a "pre-macro" handled by its own planner? (MVP: reuse ProductionPlanner gate.)
        # For now: register opening via a tiny planner-inline shim inside runtime:
        # We keep it as a planner to respect the architecture.
        from bot.planners.proposals import Proposal, TaskSpec

        @dataclass
        class OpeningPlanner:
            planner_id: str = "opening_planner"
            score: int = 60
            log: DevLogger | None = None
            opening_task: MacroOpeningTick = None

            def _pid(self) -> str:
                return f"{self.planner_id}:macro_opening"

            def propose(self, bot, *, awareness: Awareness, attention) -> list[Proposal]:
                now = float(attention.time)
                if bool(attention.macro.opening_done):
                    return []
                pid = self._pid()
                if awareness.ops_proposal_running(proposal_id=pid, now=now):
                    return []

                def _factory(mission_id: str) -> MacroOpeningTick:
                    return self.opening_task.spawn()

                out = [
                    Proposal(
                        proposal_id=pid,
                        domain="MACRO_PRODUCTION",  # opening shares the production lane
                        score=int(self.score),
                        tasks=[TaskSpec(task_id="macro_opening", task_factory=_factory, unit_requirements=[], lease_ttl=None)],
                        lease_ttl=None,
                        cooldown_s=0.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                ]
                if self.log:
                    self.log.emit(
                        "planner_proposed",
                        {"planner": self.planner_id, "count": len(out), "mode": "opening"},
                        meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                    )
                return out

        opening_planner = OpeningPlanner(opening_task=opening_macro_task, log=log)

        ego.register_planners(
            [
                defense_planner,
                intel_planner,
                opening_planner,
                spending_planner,
                production_planner,
                housekeeping_planner,
            ]
        )

        return cls(
            log=log,
            awareness=awareness,
            threat=threat,
            body=body,
            ego=ego,
            enemy_build_cfg=EnemyBuildIntelConfig(),
            my_comp_cfg=MyArmyCompositionConfig(),
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

        # New: strategy reference (mode + proportions)
        derive_my_army_composition_intel(
            awareness=self.awareness,
            attention=attention,
            now=now,
            cfg=self.my_comp_cfg,
        )

        tick = TaskTick(iteration=int(iteration), time=now)
        await self.ego.tick(bot, tick=tick, attention=attention, awareness=self.awareness)

    async def on_end(self, bot, game_result: Result) -> None:
        if self.log:
            self.log.emit("game_end", {"result": str(game_result)})