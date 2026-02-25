from __future__ import annotations

from dataclasses import dataclass

from bot.devlog import DevLogger
from bot.planners.proposals import Proposal
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.tasks.scan import ScanAt
from bot.tasks.scout import Scout


@dataclass
class IntelPlanner:
    planner_id: str = "intel_planner"

    def __init__(self, *, awareness: Awareness, log: DevLogger, scout_task: Scout):
        self.awareness = awareness
        self.log = log
        self.scout_task = scout_task

        self._scan_task: ScanAt | None = None
        self._scan_label: str | None = None

    def _choose_scan_target(self, bot, attention: Attention):
        # por enquanto: enemy main
        target, source = bot.ares.map.enemy_main()
        return target, "enemy_main", source

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        out: list[Proposal] = []

        threat_penalty = 50 if (attention.threatened and attention.defense_urgency >= 80) else 0

        # 1) SCV scout early
        if not awareness.intel.scv_dispatched:
            out.append(
                Proposal(
                    domain="INTEL",
                    score=max(1, 70 - threat_penalty),
                    task=self.scout_task,
                    reason="need_first_scout_main",
                )
            )

        # 2) scan quando orbital estiver pronto (derivado em attention)
        if (not awareness.intel.scanned_enemy_main) and attention.orbital_ready_to_scan:
            target, label, map_source = self._choose_scan_target(bot, attention)

            if self._scan_task is None or self._scan_label != label:
                self._scan_task = ScanAt(awareness=awareness, target=target, label=label, cooldown=20.0)
                self._scan_label = label

            out.append(
                Proposal(
                    domain="INTEL",
                    score=max(1, 85 - threat_penalty),
                    task=self._scan_task,
                    reason=f"orbital_ready_scan_{label}_src={map_source}",
                )
            )

        return out