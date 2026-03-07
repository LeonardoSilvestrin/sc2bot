from __future__ import annotations

from dataclasses import dataclass

from ares.consts import BuildingSize

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.tasks.defense.maintain_wall_task import MaintainWallTask


@dataclass
class WallPlanner:
    planner_id: str = "wall_planner"
    log: DevLogger | None = None
    main_score: int = 84
    nat_score: int = 82
    cadence_s: float = 4.0

    def _pid(self, zone: str) -> str:
        return f"{self.planner_id}:{str(zone)}"

    def _due(self, *, awareness: Awareness, now: float, zone: str) -> bool:
        last = awareness.mem.get(K("ops", "wall", str(zone), "proposal_last_t"), now=now, default=0.0) or 0.0
        return (float(now) - float(last)) >= float(self.cadence_s)

    def _mark(self, *, awareness: Awareness, now: float, zone: str) -> None:
        awareness.mem.set(K("ops", "wall", str(zone), "proposal_last_t"), value=float(now), now=now, ttl=None)

    @staticmethod
    def _rush_active(*, awareness: Awareness, now: float) -> bool:
        state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        return state in {"SUSPECTED", "CONFIRMED", "HOLDING"}

    @staticmethod
    def _opening_build_active(bot) -> bool:
        bor = getattr(bot, "build_order_runner", None)
        if bor is None:
            return False
        return not bool(getattr(bor, "build_completed", False))

    @staticmethod
    def _nat_wall_supported(bot) -> bool:
        try:
            nat = bot.mediator.get_own_nat
            placements = dict(bot.mediator.get_placements_dict or {})
        except Exception:
            return False
        if nat not in placements:
            return False
        nat_two_by_two = placements[nat].get(BuildingSize.TWO_BY_TWO, {}) or {}
        nat_three_by_three = placements[nat].get(BuildingSize.THREE_BY_THREE, {}) or {}
        has_wall_depots = any(
            isinstance(info, dict) and bool(info.get("is_wall", False)) and bool(info.get("supply_depot", False))
            for info in nat_two_by_two.values()
        )
        has_wall_three_by_three = any(
            isinstance(info, dict) and bool(info.get("is_wall", False))
            for info in nat_three_by_three.values()
        )
        return bool(has_wall_depots or has_wall_three_by_three)

    def _main_factory(self, *, awareness: Awareness):
        def _factory(mission_id: str) -> MaintainWallTask:
            return MaintainWallTask(awareness=awareness, zone="main", log=self.log)

        return _factory

    def _nat_factory(self, *, awareness: Awareness):
        def _factory(mission_id: str) -> MaintainWallTask:
            return MaintainWallTask(awareness=awareness, zone="nat", log=self.log)

        return _factory

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        out: list[Proposal] = []
        opening_build_active = bool(self._opening_build_active(bot))
        rush_active = bool(self._rush_active(awareness=awareness, now=now))

        if opening_build_active and not rush_active:
            if self.log is not None:
                self.log.emit(
                    "planner_skipped",
                    {
                        "planner": self.planner_id,
                        "reason": "opening_build_active",
                        "rush_active": bool(rush_active),
                        "bases_total": int(attention.macro.bases_total),
                    },
                    meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                )
            return out

        main_pid = self._pid("main")
        if not awareness.ops_proposal_running(proposal_id=main_pid, now=now) and self._due(awareness=awareness, now=now, zone="main"):
            out.append(
                Proposal(
                    proposal_id=main_pid,
                    domain="DEFENSE",
                    score=int(self.main_score),
                    tasks=[
                        TaskSpec(
                            task_id="maintain_main_wall",
                            task_factory=self._main_factory(awareness=awareness),
                            unit_requirements=[],
                            lease_ttl=20.0,
                        )
                    ],
                    lease_ttl=20.0,
                    cooldown_s=0.0,
                    risk_level=0,
                    allow_preempt=True,
                )
            )
            self._mark(awareness=awareness, now=now, zone="main")

        nat_supported = bool(self._nat_wall_supported(bot))
        nat_required = bool(nat_supported and (rush_active or int(attention.macro.bases_total) >= 2))
        nat_pid = self._pid("nat")
        if nat_required and not awareness.ops_proposal_running(proposal_id=nat_pid, now=now) and self._due(awareness=awareness, now=now, zone="nat"):
            out.append(
                Proposal(
                    proposal_id=nat_pid,
                    domain="DEFENSE",
                    score=int(self.nat_score),
                    tasks=[
                        TaskSpec(
                            task_id="maintain_nat_wall",
                            task_factory=self._nat_factory(awareness=awareness),
                            unit_requirements=[],
                            lease_ttl=20.0,
                        )
                    ],
                    lease_ttl=20.0,
                    cooldown_s=0.0,
                    risk_level=0,
                    allow_preempt=True,
                )
            )
            self._mark(awareness=awareness, now=now, zone="nat")

        if self.log is not None and out:
            self.log.emit(
                "planner_proposed",
                {
                    "planner": self.planner_id,
                    "count": len(out),
                    "zones": [str(p.proposal_id).split(":")[-1] for p in out],
                    "rush_active": bool(rush_active),
                    "bases_total": int(attention.macro.bases_total),
                    "nat_supported": bool(nat_supported),
                },
                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
            )
        return out
