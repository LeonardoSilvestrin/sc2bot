from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.defense.defense_bunker_task import DefenseBunkerTask
from bot.tasks.defense.land_base_task import LandBaseTask
from bot.tasks.defense.secure_base_task import SecureBaseTask


@dataclass(frozen=True)
class _SecureBasePickPolicy:
    objective: Point2
    unit_type: U
    name: str = "map_control.secure_base.nearest.v1"

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
        return (hp * 12.0) - dist


@dataclass(frozen=True)
class _SecureScvPickPolicy:
    objective: Point2
    name: str = "map_control.secure_base.support_scv.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != U.SCV:
            return False
        if not bool(getattr(unit, "is_ready", False)):
            return False
        if float(getattr(unit, "health_percentage", 1.0) or 1.0) < 0.65:
            return False
        try:
            if bool(getattr(unit, "is_constructing", False)):
                return False
        except Exception:
            pass
        try:
            for order in list(getattr(unit, "orders", []) or []):
                name = str(getattr(getattr(order, "ability", None), "name", "") or "").upper()
                if "BUILD" in name or "REPAIR" in name:
                    return False
        except Exception:
            pass
        return True

    def score(self, unit, *, bot, attention, now: float) -> float:
        try:
            dist = float(unit.distance_to(self.objective))
        except Exception:
            dist = 9999.0
        hp = float(getattr(unit, "health_percentage", 1.0) or 1.0)
        carrying_penalty = 0.0
        try:
            carrying_penalty = 5.0 if bool(getattr(unit, "is_carrying_resource", False)) else 0.0
        except Exception:
            carrying_penalty = 0.0
        return (hp * 11.0) - dist - carrying_penalty


@dataclass
class MapControlPlanner:
    planner_id: str = "map_control_planner"
    log: DevLogger | None = None
    cadence_s: float = 2.0
    lease_ttl_s: Optional[float] = None

    def _pid(self, label: str) -> str:
        return f"{self.planner_id}:{str(label)}"

    def _make_bunker_factory(self, *, base_pos: Point2, hold_pos: Point2):
        def _factory(mission_id: str) -> DefenseBunkerTask:
            return DefenseBunkerTask(
                base_tag=-1,
                base_pos=base_pos,
                threat_pos=hold_pos,
                anchor_mode="NAT_CHOKE",
                log=self.log,
            )

        return _factory

    @staticmethod
    def _point(payload, *, fallback: Point2 | None = None) -> Point2 | None:
        if not isinstance(payload, dict):
            return fallback
        try:
            return Point2((float(payload.get("x", 0.0)), float(payload.get("y", 0.0))))
        except Exception:
            return fallback

    def _due(self, *, awareness: Awareness, now: float, pid: str) -> bool:
        last = awareness.mem.get(K("ops", "map_control", "proposal", pid, "last_t"), now=now, default=None)
        if last is None:
            return True
        try:
            return (float(now) - float(last)) >= float(self.cadence_s)
        except Exception:
            return True

    @staticmethod
    def _mark(*, awareness: Awareness, now: float, pid: str) -> None:
        awareness.mem.set(K("ops", "map_control", "proposal", pid, "last_t"), value=float(now), now=now, ttl=None)

    @staticmethod
    def _available(bot, unit_type: U) -> int:
        return int(bot.units.of_type(unit_type).ready.amount)

    @staticmethod
    def _nat_bunker_started_or_pending(bot, *, base_pos: Point2, hold_pos: Point2) -> bool:
        refs = [base_pos, hold_pos]
        try:
            for bunker in bot.structures(U.BUNKER):
                if any(float(bunker.distance_to(ref)) <= 10.0 for ref in refs):
                    return True
        except Exception:
            pass
        try:
            tracker = dict(bot.mediator.get_building_tracker_dict or {})
        except Exception:
            tracker = {}
        for entry in tracker.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("structure_type", None) != U.BUNKER:
                continue
            pos = entry.get("target", None) or entry.get("pos", None)
            if pos is None:
                continue
            try:
                if any(float(pos.distance_to(ref)) <= 10.0 for ref in refs):
                    return True
            except Exception:
                continue
        return False

    def _should_request_nat_bunker(self, *, bot, attention: Attention, snapshot: dict, base_pos: Point2, hold_pos: Point2) -> bool:
        if self._nat_bunker_started_or_pending(bot, base_pos=base_pos, hold_pos=hold_pos):
            return False
        rush_state = str(snapshot.get("rush_state", "NONE") or "NONE").upper()
        rush_active = rush_state in {"CONFIRMED", "HOLDING"}
        nat_offsite = bool(snapshot.get("nat_offsite", False))
        delayed_natural_alarm = bool(snapshot.get("delayed_natural_alarm", False))
        enemy_nat_power = float(snapshot.get("enemy_nat_power", 0.0) or 0.0)
        own_total_power = float(snapshot.get("own_total_power", 0.0) or 0.0)
        if not (rush_active or nat_offsite or delayed_natural_alarm):
            return False
        if own_total_power < (3.0 if delayed_natural_alarm else 4.0):
            return False
        if enemy_nat_power > (3.2 if delayed_natural_alarm else 2.6):
            return False
        try:
            marines = int(bot.units(U.MARINE).ready.amount)
            marauders = int(bot.units(U.MARAUDER).ready.amount)
        except Exception:
            marines = 0
            marauders = 0
        combat_supply = float(getattr(bot, "supply_army", 0.0) or 0.0)
        if delayed_natural_alarm:
            return bool((marines + marauders) >= 1 or combat_supply >= 6.0 or int(self._available(bot, U.SIEGETANK)) > 0)
        return bool((marines + marauders) >= 2 or combat_supply >= 8.0 or int(getattr(attention.macro, "bases_total", 0) or 0) >= 2)

    def _requirements(self, *, bot, attention: Attention, hold_pos: Point2, snapshot: dict) -> list[UnitRequirement]:
        enemy_nat_power = float(snapshot.get("enemy_nat_power", 0.0) or 0.0)
        own_total_power = float(snapshot.get("own_total_power", 0.0) or 0.0)
        rush_state = str(snapshot.get("rush_state", "NONE") or "NONE").upper()
        delayed_natural_alarm = bool(snapshot.get("delayed_natural_alarm", False))
        own_nat_bunker_count = int(snapshot.get("own_nat_bunker_count", 0) or 0)
        bases_now = int(getattr(attention.macro, "bases_total", 0) or 0)
        desired_general = 4
        if own_total_power >= 8.0:
            desired_general = 5
        if enemy_nat_power >= 1.0 or rush_state in {"CONFIRMED", "HOLDING"}:
            desired_general += 2
        if delayed_natural_alarm and bases_now < 2:
            desired_general += 2
        if own_nat_bunker_count > 0:
            desired_general = max(int(desired_general), 6)

        reqs: list[UnitRequirement] = []

        tank_avail = self._available(bot, U.SIEGETANK)
        sieged_tank_avail = self._available(bot, U.SIEGETANKSIEGED)
        desired_tanks = (1 if enemy_nat_power < 1.5 else 2) + (1 if delayed_natural_alarm and (tank_avail + sieged_tank_avail) >= 2 else 0)
        total_tanks = min(int(desired_tanks), int(tank_avail + sieged_tank_avail))
        take_unsieged = min(int(total_tanks), int(tank_avail))
        take_sieged = min(max(0, int(total_tanks) - int(take_unsieged)), int(sieged_tank_avail))
        if take_unsieged > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.SIEGETANK,
                    count=int(take_unsieged),
                    pick_policy=_SecureBasePickPolicy(objective=hold_pos, unit_type=U.SIEGETANK),
                    required=True,
                )
            )
        if take_sieged > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.SIEGETANKSIEGED,
                    count=int(take_sieged),
                    pick_policy=_SecureBasePickPolicy(objective=hold_pos, unit_type=U.SIEGETANKSIEGED),
                    required=len(reqs) == 0,
                )
            )

        mine_avail = self._available(bot, U.WIDOWMINE)
        if mine_avail > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.WIDOWMINE,
                    count=min(1, int(mine_avail)),
                    pick_policy=_SecureBasePickPolicy(objective=hold_pos, unit_type=U.WIDOWMINE),
                    required=len(reqs) == 0,
                )
            )

        remaining = int(desired_general)
        general_types = [U.MARINE, U.MARAUDER, U.CYCLONE, U.HELLION, U.THOR, U.THORAP]
        for unit_type in general_types:
            if remaining <= 0:
                break
            avail = self._available(bot, unit_type)
            if avail <= 0:
                continue
            take = min(int(avail), int(remaining))
            if unit_type == U.MARINE and own_nat_bunker_count > 0:
                take = min(int(avail), max(int(take), min(4, int(avail))))
            reqs.append(
                UnitRequirement(
                    unit_type=unit_type,
                    count=int(take),
                    pick_policy=_SecureBasePickPolicy(objective=hold_pos, unit_type=unit_type),
                    required=len(reqs) == 0,
                )
            )
            remaining -= int(take)

        medivac_avail = self._available(bot, U.MEDIVAC)
        if medivac_avail > 0 and own_total_power >= 7.0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.MEDIVAC,
                    count=1,
                    pick_policy=_SecureBasePickPolicy(objective=hold_pos, unit_type=U.MEDIVAC),
                    required=False,
                )
            )
        scv_avail = self._available(bot, U.SCV)
        support_scvs = 0
        if bases_now < 2 and rush_state in {"CONFIRMED", "HOLDING"} and own_total_power >= 7.0:
            support_scvs = 2 if enemy_nat_power <= 1.2 else 3
        elif delayed_natural_alarm and bases_now < 2 and own_total_power >= 5.0:
            support_scvs = 2 if enemy_nat_power <= 1.6 else 3
        elif enemy_nat_power > 0.0 and own_total_power >= 8.0:
            support_scvs = 1
        if scv_avail > 0 and support_scvs > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.SCV,
                    count=min(int(support_scvs), int(scv_avail)),
                    pick_policy=_SecureScvPickPolicy(objective=hold_pos),
                    required=False,
                )
            )
        return reqs

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        snapshot = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
        if not isinstance(snapshot, dict):
            return []
        out: list[Proposal] = []
        safe_to_land = bool(snapshot.get("safe_to_land", False))
        nat_offsite = bool(snapshot.get("nat_offsite", False))
        delayed_natural_alarm = bool(snapshot.get("delayed_natural_alarm", False))
        base_pos = self._point(snapshot.get("target"))
        if bool(safe_to_land) and bool(nat_offsite) and base_pos is not None:
            land_pid = self._pid("land_our_nat")
            if not awareness.ops_proposal_running(proposal_id=land_pid, now=now) and self._due(awareness=awareness, now=now, pid=land_pid):
                def _land_factory(mission_id: str) -> LandBaseTask:
                    return LandBaseTask(
                        awareness=awareness,
                        base_label="NATURAL",
                        target_pos=base_pos,
                        log=self.log,
                    )

                out.append(
                    Proposal(
                        proposal_id=land_pid,
                        domain="DEFENSE",
                        score=96,
                        tasks=[
                            TaskSpec(
                                task_id="land_base_natural",
                                task_factory=_land_factory,
                                unit_requirements=[],
                                lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                            )
                        ],
                        lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                        cooldown_s=0.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                )
                self._mark(awareness=awareness, now=now, pid=land_pid)
        if base_pos is not None:
            hold_pos_early = self._point(snapshot.get("hold"), fallback=base_pos)
            if hold_pos_early is not None:
                bunker_pid = self._pid("secure_our_nat_bunker")
                if (
                    self._should_request_nat_bunker(
                        bot=bot,
                        attention=attention,
                        snapshot=snapshot,
                        base_pos=base_pos,
                        hold_pos=hold_pos_early,
                    )
                    and not awareness.ops_proposal_running(proposal_id=bunker_pid, now=now)
                    and self._due(awareness=awareness, now=now, pid=bunker_pid)
                ):
                    bunker_factory = self._make_bunker_factory(base_pos=base_pos, hold_pos=hold_pos_early)
                    out.append(
                        Proposal(
                            proposal_id=bunker_pid,
                            domain="MAP_CONTROL",
                            score=(94 if delayed_natural_alarm else 92),
                            tasks=[
                                TaskSpec(
                                    task_id="secure_nat_bunker",
                                    task_factory=bunker_factory,
                                    unit_requirements=[
                                        UnitRequirement(
                                            unit_type=U.SCV,
                                            count=1,
                                            pick_policy=_SecureScvPickPolicy(objective=hold_pos_early),
                                            required=True,
                                        )
                                    ],
                                    lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                                )
                            ],
                            lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                            cooldown_s=0.0,
                            risk_level=0,
                            allow_preempt=True,
                        )
                    )
                    self._mark(awareness=awareness, now=now, pid=bunker_pid)
        if not bool(snapshot.get("should_secure", False)):
            return out

        pid = self._pid("secure_our_nat")
        if awareness.ops_proposal_running(proposal_id=pid, now=now):
            return out
        if not self._due(awareness=awareness, now=now, pid=pid):
            return out

        base_pos = self._point(snapshot.get("target"))
        staging_pos = self._point(snapshot.get("staging"), fallback=base_pos)
        hold_pos = self._point(snapshot.get("hold"), fallback=base_pos)
        if base_pos is None or staging_pos is None or hold_pos is None:
            return out

        reqs = self._requirements(bot=bot, attention=attention, hold_pos=hold_pos, snapshot=snapshot)
        if not reqs:
            return out

        def _factory(mission_id: str) -> SecureBaseTask:
            return SecureBaseTask(
                awareness=awareness,
                base_pos=base_pos,
                staging_pos=staging_pos,
                hold_pos=hold_pos,
                label="our_nat",
                log=self.log,
            )

        score = 94 if str(snapshot.get("rush_state", "NONE")).upper() in {"CONFIRMED", "HOLDING"} else 88
        out.append(
            Proposal(
                proposal_id=pid,
                domain="MAP_CONTROL",
                score=int(score),
                tasks=[
                    TaskSpec(
                        task_id="secure_base",
                        task_factory=_factory,
                        unit_requirements=reqs,
                        lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                    )
                ],
                lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                cooldown_s=0.0,
                risk_level=0,
                allow_preempt=True,
            )
        )
        self._mark(awareness=awareness, now=now, pid=pid)
        if self.log is not None:
            self.log.emit(
                "planner_proposed",
                {
                    "planner": self.planner_id,
                    "count": int(len(out)),
                    "label": "secure_our_nat",
                    "rush_state": str(snapshot.get("rush_state", "NONE")),
                    "clear_for": float(round(float(snapshot.get("clear_for", 0.0) or 0.0), 2)),
                    "enemy_nat_power": float(round(float(snapshot.get("enemy_nat_power", 0.0) or 0.0), 2)),
                    "safe_to_land": bool(safe_to_land),
                    "nat_offsite": bool(nat_offsite),
                },
                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
            )
        return out
