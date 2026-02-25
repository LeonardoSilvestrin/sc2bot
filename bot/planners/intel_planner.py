# bot/planners/intel_planner.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal, UnitRequirement
from bot.tasks.scan_task import ScanAt
from bot.tasks.scout_task import Scout


@dataclass
class IntelPlanner:
    planner_id: str = "intel_planner"

    awareness: Awareness = None  # injected
    log: DevLogger = None  # injected
    scout_task: Scout = None  # injected

    def __post_init__(self) -> None:
        self._scan_label: Optional[str] = None
        self._scan_target: Optional[Point2] = None
        self._scan_map_source: Optional[str] = None

    def _choose_scan_target(self, bot) -> Tuple[Point2, str, str]:
        # minimal for now: scan enemy main position from game_info
        try:
            enemy_main = bot.enemy_start_locations[0]
            return enemy_main, "enemy_main", "enemy_start_locations"
        except Exception:
            return bot.game_info.map_center, "map_center", "fallback"

    # -----------------------
    # Proposal IDs
    # -----------------------
    def _pid_scout(self) -> str:
        return f"{self.planner_id}:scout:scv_early"

    def _pid_scan(self, label: str) -> str:
        return f"{self.planner_id}:scan:{label}"

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        """
        v2 contract:
          - Proposal(proposal_id, domain, score, task_factory, unit_requirements, ...)
        """
        now = float(getattr(attention, "time", 0.0))
        aw = awareness

        proposals: list[Proposal] = []

        # 1) SCV scout early (if not dispatched yet)
        if not aw.intel_scv_dispatched(now=now):
            def _scout_factory(mission_id: str) -> Scout:
                t = self.scout_task
                # compat: task ainda pode ignorar, mas fica disponível pra logs/ops
                try:
                    setattr(t, "mission_id", mission_id)
                except Exception:
                    pass
                return t

            proposals.append(
                Proposal(
                    proposal_id=self._pid_scout(),
                    domain="INTEL",
                    score=35,
                    task_factory=_scout_factory,
                    unit_requirements=[UnitRequirement(unit_type=U.SCV, count=1)],
                    lease_ttl=14.0,
                    cooldown_s=12.0,
                    risk_level=0,
                    allow_preempt=True,
                )
            )
            return proposals

        # 2) Scan when orbital is ready and we haven't scanned enemy main yet
        if (not aw.intel_scanned_enemy_main(now=now)) and bool(attention.intel.orbital_ready_to_scan):
            target, label, map_source = self._choose_scan_target(bot)

            # store for stable proposal_id/reasoning
            self._scan_label = label
            self._scan_target = target
            self._scan_map_source = map_source

            def _scan_factory(mission_id: str) -> ScanAt:
                # criar task fresca (scan tem estado próprio/cooldown interno)
                t = ScanAt(
                    awareness=aw,
                    target=target,
                    label=label,
                    cooldown=20.0,
                    log=self.log,
                )
                try:
                    setattr(t, "mission_id", mission_id)
                except Exception:
                    pass
                return t

            proposals.append(
                Proposal(
                    proposal_id=self._pid_scan(label),
                    domain="INTEL",
                    score=60,
                    task_factory=_scan_factory,
                    unit_requirements=[],     # scan usa orbital; gate é attention.orbital_ready_to_scan
                    lease_ttl=6.0,
                    cooldown_s=10.0,
                    risk_level=0,
                    allow_preempt=True,
                )
            )

        return proposals