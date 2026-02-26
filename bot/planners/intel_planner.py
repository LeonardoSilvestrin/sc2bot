# bot/planners/intel_planner.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.scan_task import ScanAt
from bot.tasks.scout_task import Scout


@dataclass
class IntelPlanner:
    planner_id: str = "intel_planner"

    awareness: Awareness = None  # injected
    log: DevLogger | None = None
    scout_task: Scout = None  # template instance

    def _pid_scout(self) -> str:
        return f"{self.planner_id}:scout:scv_early"

    def _pid_scan(self, label: str) -> str:
        return f"{self.planner_id}:scan:{label}"

    def _enemy_main(self, bot) -> Point2:
        # strict: no fallbacks here; if engine doesn't provide, crash to expose wiring bug
        return bot.enemy_start_locations[0]

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        proposals: list[Proposal] = []

        if self.awareness is None:
            raise TypeError("IntelPlanner requires awareness injected")
        if self.scout_task is None:
            raise TypeError("IntelPlanner requires scout_task template instance")

        # 1) SCV scout early
        if not awareness.intel_scv_dispatched(now=now):
            def _scout_factory(mission_id: str) -> Scout:
                return self.scout_task.spawn()

            proposals.append(
                Proposal(
                    proposal_id=self._pid_scout(),
                    domain="INTEL",
                    score=35,
                    tasks=[
                        TaskSpec(
                            task_id="scout_scv",
                            task_factory=_scout_factory,
                            unit_requirements=[UnitRequirement(unit_type=U.SCV, count=1)],
                        )
                    ],
                    lease_ttl=40.0,
                    cooldown_s=8.0,
                    risk_level=1,
                    allow_preempt=True,
                )
            )

        # 2) Scan when threatened and orbital ready
        if bool(attention.combat.threatened) and bool(attention.intel.orbital_ready_to_scan):
            target = self._enemy_main(bot)
            label = "enemy_main"

            def _scan_factory(mission_id: str) -> ScanAt:
                return ScanAt(awareness=awareness, target=target, label=label, cooldown=20.0, log=self.log)

            proposals.append(
                Proposal(
                    proposal_id=self._pid_scan(label),
                    domain="INTEL",
                    score=55,
                    tasks=[TaskSpec(task_id="scan_at", task_factory=_scan_factory, unit_requirements=[])],
                    lease_ttl=5.0,
                    cooldown_s=20.0,
                    risk_level=1,
                    allow_preempt=True,
                )
            )

        return proposals