# bot/planners/intel_planner.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.planners.proposals import Proposal
from bot.tasks.scan import ScanAt
from bot.tasks.scout import Scout


@dataclass
class IntelPlanner:
    planner_id: str = "intel_planner"

    awareness: Awareness = None  # injected
    log: DevLogger = None  # injected
    scout_task: Scout = None  # injected

    def __post_init__(self) -> None:
        self._scan_task: Optional[ScanAt] = None
        self._scan_label: Optional[str] = None

    def _choose_scan_target(self, bot):
        # minimal for now: scan enemy main position from game_info
        try:
            enemy_main = bot.enemy_start_locations[0]
            return enemy_main, "enemy_main", "enemy_start_locations"
        except Exception:
            return bot.game_info.map_center, "map_center", "fallback"

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        """
        Contract expected by Ego:
          - returns List[Proposal]
          - Proposal has: domain: str, score: int, task: Task, reason: str
        """
        now = float(getattr(bot, "time", 0.0))
        aw = awareness  # use the injected instance from ego.tick()

        proposals: list[Proposal] = []

        # 1) SCV scout early (if not dispatched yet)
        if not aw.intel_scv_dispatched(now=now):
            proposals.append(
                Proposal(
                    domain="INTEL",
                    task=self.scout_task,
                    score=30,
                    reason="no_scv_scout_dispatched",
                )
            )
            return proposals

        # 2) Scan when orbital is ready and we haven't scanned enemy main yet
        if (not aw.intel_scanned_enemy_main(now=now)) and attention.orbital_ready_to_scan:
            target, label, map_source = self._choose_scan_target(bot)

            if self._scan_task is None or self._scan_label != label:
                self._scan_task = ScanAt(
                    awareness=aw,
                    target=target,
                    label=label,
                    cooldown=20.0,
                    log=self.log,
                )
                self._scan_label = label

            proposals.append(
                Proposal(
                    domain="INTEL",
                    task=self._scan_task,
                    score=55,
                    reason=f"orbital_ready_scan_{label}_src={map_source}",
                )
            )

        return proposals