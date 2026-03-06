from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention, MissionStatusSnapshot
from bot.mind.awareness import Awareness
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.mission_objective import mission_objective_from_alive_tags
from bot.planners.utils.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.support.support_mission_task import SupportMission


@dataclass(frozen=True)
class ReinforcePickPolicy:
    unit_type: object
    objective: Point2
    name: str = "reinforce.same_type.nearest_objective.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != self.unit_type:
            return False
        if not bool(getattr(unit, "is_ready", False)):
            return False
        return float(getattr(unit, "health_percentage", 1.0) or 1.0) >= 0.35

    def score(self, unit, *, bot, attention, now: float) -> float:
        try:
            dist = float(unit.distance_to(self.objective))
        except Exception:
            dist = 9999.0
        hp = float(getattr(unit, "health_percentage", 1.0) or 1.0)
        return (hp * 8.0) - dist


@dataclass
class ReinforceMissionPlanner(BasePlanner):
    planner_id: str = "reinforce_mission_planner"
    log: DevLogger | None = None
    allowed_domains: tuple[str, ...] = ("HARASS",)
    max_add_per_type: int = 1
    cooldown_s: float = 1.2
    lease_ttl_s: float = 8.0
    score: int = 72
    min_remaining_s: float = 3.0
    banshee_harass_target_size: int = 2

    def _proposal_id(self, mission_id: str, unit_type_name: str) -> str:
        return f"{self.planner_id}:{mission_id}:{unit_type_name}"

    @staticmethod
    def _mission_objective(bot, mission: MissionStatusSnapshot) -> Point2:
        return mission_objective_from_alive_tags(bot, mission)

    @staticmethod
    def _alive_type_counts(bot, mission: MissionStatusSnapshot) -> dict[str, int]:
        counts: dict[str, int] = {}
        for tag in mission.alive_tags:
            unit = bot.units.find_by_tag(int(tag))
            if unit is None:
                continue
            ut_name = str(getattr(getattr(unit, "type_id", None), "name", ""))
            if not ut_name:
                continue
            counts[ut_name] = int(counts.get(ut_name, 0)) + 1
        return counts

    @staticmethod
    def _is_banshee_harass_mission(mission: MissionStatusSnapshot) -> bool:
        return str(mission.domain) == "HARASS" and str(mission.proposal_id).startswith("harass_planner:banshee")

    def _requirements_for_mission(self, bot, mission: MissionStatusSnapshot) -> list[UnitRequirement]:
        objective = self._mission_objective(bot, mission)
        desired_counts = {str(k): int(v) for k, v in mission.original_type_counts}
        if not desired_counts:
            return []
        if self._is_banshee_harass_mission(mission):
            desired_counts["BANSHEE"] = max(
                int(desired_counts.get("BANSHEE", 0)),
                int(self.banshee_harass_target_size),
            )
        alive_counts = self._alive_type_counts(bot, mission)

        reqs: list[UnitRequirement] = []
        for unit_name, desired_count in desired_counts.items():
            if desired_count <= 0:
                continue
            try:
                unit_type = getattr(U, unit_name)
            except Exception:
                continue
            alive_count = int(alive_counts.get(unit_name, 0))
            missing = max(0, int(desired_count) - int(alive_count))
            if missing <= 0:
                continue
            ready_total = int(bot.units.of_type(unit_type).ready.amount)
            add_n = min(int(self.max_add_per_type), int(missing), int(ready_total))
            if add_n <= 0:
                continue
            reqs.append(
                UnitRequirement(
                    unit_type=unit_type,
                    count=int(add_n),
                    pick_policy=ReinforcePickPolicy(unit_type=unit_type, objective=objective),
                )
            )
        return reqs

    @staticmethod
    def _domain_allowed(domain: str, allowed: set[str]) -> bool:
        if not allowed:
            return True
        return str(domain) in allowed

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        out: list[Proposal] = []
        allowed = {str(d) for d in self.allowed_domains}

        for mission in attention.missions.ongoing:
            banshee_growth_candidate = bool(
                self._is_banshee_harass_mission(mission)
                and int(mission.alive_count) > 0
            )
            if not bool(mission.can_reinforce) and not banshee_growth_candidate:
                continue
            if not self._domain_allowed(str(mission.domain), allowed):
                continue
            if mission.remaining_s is not None and float(mission.remaining_s) < float(self.min_remaining_s):
                continue

            reqs = self._requirements_for_mission(bot, mission)
            if not reqs:
                continue

            for req in reqs:
                type_name = str(getattr(req.unit_type, "name", str(req.unit_type)))
                pid = self._proposal_id(mission.mission_id, type_name)
                if self.is_proposal_running(awareness=awareness, proposal_id=pid, now=now):
                    continue
                target_mission_id = str(mission.mission_id)

                def _factory(mission_id: str) -> SupportMission:
                    return SupportMission(awareness=awareness, target_mission_id=target_mission_id)

                out.extend(
                    self.make_single_task_proposal(
                        proposal_id=pid,
                        domain=str(mission.domain),
                        score=int(self.score),
                        reinforce_mission_id=str(mission.mission_id),
                        task_spec=TaskSpec(
                            task_id="support_mission",
                            task_factory=_factory,
                            unit_requirements=[req],
                        ),
                        lease_ttl=float(self.lease_ttl_s),
                        cooldown_s=float(self.cooldown_s),
                        risk_level=1,
                        allow_preempt=True,
                    )
                )

        if out:
            self.emit_planner_proposed({"count": len(out), "ongoing": int(attention.missions.ongoing_count)})
        return out

