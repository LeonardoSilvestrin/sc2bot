from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention, BaseThreatSnapshot
from bot.mind.awareness import Awareness
from bot.planners.utils.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.defense.defend_base_task import DefendBaseTask
from bot.tasks.defense.defend_task import Defend


@dataclass(frozen=True)
class _DefendPickPolicy:
    objective: Point2
    unit_type: U
    name: str = "defense.base.nearest_objective.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != self.unit_type:
            return False
        if not bool(getattr(unit, "is_ready", False)):
            return False
        return float(getattr(unit, "health_percentage", 1.0) or 1.0) >= 0.30

    def score(self, unit, *, bot, attention, now: float) -> float:
        try:
            dist = float(unit.distance_to(self.objective))
        except Exception:
            dist = 9999.0
        hp = float(getattr(unit, "health_percentage", 1.0) or 1.0)
        return (hp * 14.0) - dist


@dataclass
class DefensePlanner:
    """
    Defesa por base: uma proposal por base ameaçada.
    """
    planner_id: str = "defense_planner"
    defend_task: Defend | None = None  # legado (mantido por compatibilidade com RuntimeApp.build)
    log: DevLogger | None = None
    cadence_s: float = 2.0
    min_base_urgency: int = 1
    max_bases_per_tick: int = 3
    existence_trigger_enabled: bool = True

    def _pid_base(self, base_tag: int) -> str:
        return f"{self.planner_id}:defend:base:{int(base_tag)}"

    def _due(self, *, awareness: Awareness, now: float, pid: str) -> bool:
        last = awareness.mem.get(("ops", "defense", "proposal", pid, "last_t"), now=now, default=None)
        if last is None:
            return True
        try:
            return (float(now) - float(last)) >= float(self.cadence_s)
        except Exception:
            return True

    @staticmethod
    def _mark_proposed(*, awareness: Awareness, now: float, pid: str) -> None:
        awareness.mem.set(("ops", "defense", "proposal", pid, "last_t"), value=float(now), now=now, ttl=None)

    @staticmethod
    def _score_from_urgency(urgency: int) -> int:
        return max(80, min(100, 62 + int(urgency)))

    @staticmethod
    def _threats(attention: Attention) -> list[BaseThreatSnapshot]:
        out = [
            b
            for b in list(attention.combat.base_threats or ())
            if int(b.enemy_count) > 0 and int(b.urgency) >= 1
        ]
        out.sort(key=lambda b: (-int(b.urgency), -int(b.enemy_count), int(b.th_tag)))
        return out

    @staticmethod
    def _defense_units_available(bot) -> int:
        pool = [U.SIEGETANK, U.WIDOWMINE, U.CYCLONE, U.MARAUDER, U.MARINE, U.HELLION, U.THOR, U.THORAP, U.MEDIVAC]
        total = 0
        for t in pool:
            total += int(bot.units.of_type(t).ready.amount)
        return int(total)

    @staticmethod
    def _most_exposed_townhall(bot):
        ths = list(getattr(bot, "townhalls", []) or [])
        if not ths:
            return None
        try:
            enemy_main = bot.enemy_start_locations[0]
            ths.sort(key=lambda th: float(th.distance_to(enemy_main)))
        except Exception:
            pass
        return ths[0]

    @staticmethod
    def _own_defense_score_near_base(bot, *, base_pos: Point2) -> float:
        score = 0.0
        own = list(getattr(bot, "units", []) or [])
        for u in own:
            try:
                if float(u.distance_to(base_pos)) > 20.0:
                    continue
            except Exception:
                continue
            tid = getattr(u, "type_id", None)
            if tid in {U.SIEGETANKSIEGED}:
                score += 4.5
            elif tid in {U.SIEGETANK}:
                score += 3.0
            elif tid in {U.WIDOWMINEBURROWED}:
                score += 3.2
            elif tid in {U.WIDOWMINE}:
                score += 2.0
            elif tid in {U.BUNKER, U.PLANETARYFORTRESS}:
                score += 4.0
            elif tid in {U.CYCLONE, U.MARAUDER, U.MARINE, U.HELLION, U.THOR, U.THORAP}:
                score += 1.0
            elif tid in {U.MEDIVAC}:
                score += 0.4
        return float(score)

    def _threat_priority(self, *, bot, th: BaseThreatSnapshot) -> float:
        defense_here = self._own_defense_score_near_base(bot, base_pos=th.th_pos)
        raw = (float(th.urgency) + (2.2 * float(th.enemy_count))) - (2.1 * float(defense_here))
        return float(raw)

    def _fallback_base_candidates(self, bot) -> list[BaseThreatSnapshot]:
        ths = list(getattr(bot, "townhalls", []) or [])
        if not ths:
            return []
        try:
            enemy_main = bot.enemy_start_locations[0]
        except Exception:
            enemy_main = None

        scored: list[tuple[float, BaseThreatSnapshot]] = []
        for th in ths:
            base_pos = th.position
            defense_here = self._own_defense_score_near_base(bot, base_pos=base_pos)
            if enemy_main is not None:
                try:
                    dist = float(base_pos.distance_to(enemy_main))
                except Exception:
                    dist = 80.0
            else:
                dist = 80.0
            exposure = max(0.0, min(1.0, (90.0 - dist) / 90.0))
            vulnerability = (3.5 * exposure) + max(0.0, 3.0 - float(defense_here))
            urgency = max(1, min(20, int(round(1.0 + (vulnerability * 4.0)))))
            snap = BaseThreatSnapshot(
                th_tag=int(getattr(th, "tag", -1) or -1),
                th_pos=base_pos,
                enemy_count=0,
                enemy_power=0.0,
                urgency=int(urgency),
                threat_pos=(enemy_main if enemy_main is not None else base_pos),
            )
            scored.append((float(vulnerability), snap))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _v, s in scored]

    @staticmethod
    def _objective(th: BaseThreatSnapshot) -> Point2:
        return th.threat_pos or th.th_pos

    @staticmethod
    def _available(bot, unit_type: U) -> int:
        return int(bot.units.of_type(unit_type).ready.amount)

    def _requirements(self, *, bot, th: BaseThreatSnapshot, objective: Point2) -> list[UnitRequirement]:
        urgency = int(th.urgency)
        desired_tanks = 1 if urgency < 35 else (2 if urgency < 70 else 3)
        desired_mines = 1 if urgency < 40 else 2
        desired_general = 3 if urgency < 35 else (6 if urgency < 70 else 10)

        reqs: list[UnitRequirement] = []

        # Preferential: siege tank first.
        tank_avail = self._available(bot, U.SIEGETANK)
        if tank_avail > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.SIEGETANK,
                    count=min(int(desired_tanks), int(tank_avail)),
                    pick_policy=_DefendPickPolicy(objective=objective, unit_type=U.SIEGETANK),
                    required=True,
                )
            )

        mine_avail = self._available(bot, U.WIDOWMINE)
        if mine_avail > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.WIDOWMINE,
                    count=min(int(desired_mines), int(mine_avail)),
                    pick_policy=_DefendPickPolicy(objective=objective, unit_type=U.WIDOWMINE),
                    required=len(reqs) == 0,
                )
            )

        general_types = [U.CYCLONE, U.MARAUDER, U.MARINE, U.HELLION, U.THOR, U.THORAP]
        remaining = int(desired_general)
        for t in general_types:
            if remaining <= 0:
                break
            avail = self._available(bot, t)
            if avail <= 0:
                continue
            take = min(int(avail), int(remaining))
            reqs.append(
                UnitRequirement(
                    unit_type=t,
                    count=int(take),
                    pick_policy=_DefendPickPolicy(objective=objective, unit_type=t),
                    required=len(reqs) == 0,
                )
            )
            remaining -= int(take)

        return reqs

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        out: list[Proposal] = []
        threats_raw = [b for b in self._threats(attention) if int(b.urgency) >= int(self.min_base_urgency)]
        if threats_raw:
            threats_raw.sort(key=lambda th: self._threat_priority(bot=bot, th=th), reverse=True)
            threats = threats_raw[: max(1, int(self.max_bases_per_tick))]
        elif bool(self.existence_trigger_enabled) and int(self._defense_units_available(bot)) > 0:
            threats = self._fallback_base_candidates(bot)[: max(1, int(self.max_bases_per_tick))]
        else:
            threats = []

        for th in threats:
            pid = self._pid_base(int(th.th_tag))
            if awareness.ops_proposal_running(proposal_id=pid, now=now):
                continue
            if not self._due(awareness=awareness, now=now, pid=pid):
                continue

            objective = self._objective(th)
            reqs = self._requirements(bot=bot, th=th, objective=objective)
            if not reqs:
                continue

            base_pos = th.th_pos

            def _factory(mission_id: str) -> DefendBaseTask:
                return DefendBaseTask(
                    base_tag=int(th.th_tag),
                    base_pos=base_pos,
                    threat_pos=objective,
                    log=self.log,
                )

            out.append(
                Proposal(
                    proposal_id=pid,
                    domain="DEFENSE",
                    score=self._score_from_urgency(int(th.urgency)),
                    tasks=[
                        TaskSpec(
                            task_id="defend_base",
                            task_factory=_factory,
                            unit_requirements=reqs,
                            lease_ttl=None,
                        )
                    ],
                    lease_ttl=None,  # sua regra: missão de defesa de base sem ttl
                    cooldown_s=0.0,
                    risk_level=0,
                    allow_preempt=True,
                )
            )
            self._mark_proposed(awareness=awareness, now=now, pid=pid)

        if self.log is not None:
            self.log.emit(
                "planner_proposed",
                {
                    "planner": self.planner_id,
                    "count": len(out),
                    "bases_considered": int(len(threats)),
                    "base_tags": [int(b.th_tag) for b in threats],
                    "base_urgencies": [int(b.urgency) for b in threats],
                },
                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
            )
        return out
