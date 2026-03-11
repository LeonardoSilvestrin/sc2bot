from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import TaskSpec, UnitRequirement
from bot.tasks.map_control.widowmine_lurk import WidowmineLurkTask


@dataclass(frozen=True)
class _WidowminePickPolicy:
    objective: Point2
    unit_type: U
    name: str = "widowmine.control.nearest.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != self.unit_type:
            return False
        return bool(getattr(unit, "is_ready", False))

    def score(self, unit, *, bot, attention, now: float) -> float:
        try:
            dist = float(unit.distance_to(self.objective))
        except Exception:
            dist = 9999.0
        return -dist


@dataclass
class WidowminePlanner(BasePlanner):
    planner_id: str = "widowmine_planner"
    log: DevLogger | None = None
    score: int = 68
    cadence_s: float = 3.0
    lease_ttl_s: float = 10.0
    min_mines_for_control: int = 1
    min_mines_for_drop: int = 4

    def _pid(self) -> str:
        return self.proposal_id("lurk_control")

    def _due(self, *, awareness: Awareness, now: float, pid: str) -> bool:
        last = awareness.mem.get(K("ops", "widowmine", "proposal", pid, "last_t"), now=now, default=None)
        if last is None:
            return True
        try:
            return (float(now) - float(last)) >= float(self.cadence_s)
        except Exception:
            return True

    @staticmethod
    def _mark(*, awareness: Awareness, now: float, pid: str) -> None:
        awareness.mem.set(K("ops", "widowmine", "proposal", pid, "last_t"), value=float(now), now=now, ttl=None)

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list:
        now = float(attention.time)
        pid = self._pid()
        if self.is_proposal_running(awareness=awareness, proposal_id=pid, now=now):
            return []
        if not self._due(awareness=awareness, now=now, pid=pid):
            return []

        target = None
        try:
            target = bot.mediator.get_own_nat
        except Exception:
            target = bot.start_location
        mine_count = int(bot.units.of_type(U.WIDOWMINE).ready.amount) + int(bot.units.of_type(U.WIDOWMINEBURROWED).ready.amount)
        if mine_count < int(self.min_mines_for_control):
            return []

        reqs: list[UnitRequirement] = []
        free_unburrowed = int(bot.units.of_type(U.WIDOWMINE).ready.amount)
        free_burrowed = int(bot.units.of_type(U.WIDOWMINEBURROWED).ready.amount)
        if free_unburrowed > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.WIDOWMINE,
                    count=int(free_unburrowed),
                    pick_policy=_WidowminePickPolicy(objective=target, unit_type=U.WIDOWMINE),
                    required=True,
                )
            )
        if free_burrowed > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.WIDOWMINEBURROWED,
                    count=int(free_burrowed),
                    pick_policy=_WidowminePickPolicy(objective=target, unit_type=U.WIDOWMINEBURROWED),
                    required=not reqs,
                )
            )
        if mine_count >= int(self.min_mines_for_drop) and int(bot.units.of_type(U.MEDIVAC).ready.amount) > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.MEDIVAC,
                    count=1,
                    pick_policy=_WidowminePickPolicy(objective=target, unit_type=U.MEDIVAC),
                    required=False,
                )
            )

        if not reqs:
            return []

        def _factory(mission_id: str) -> WidowmineLurkTask:
            return WidowmineLurkTask(awareness=awareness, log=self.log)

        self._mark(awareness=awareness, now=now, pid=pid)
        return self.make_single_task_proposal(
            proposal_id=pid,
            domain="DEFENSE",
            score=int(self.score),
            task_spec=TaskSpec(
                task_id="widowmine_lurk",
                task_factory=_factory,
                unit_requirements=reqs,
                lease_ttl=float(self.lease_ttl_s),
            ),
            lease_ttl=float(self.lease_ttl_s),
            cooldown_s=0.0,
            risk_level=0,
            allow_preempt=True,
        )
