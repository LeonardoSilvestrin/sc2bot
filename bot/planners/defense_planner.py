from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention, BaseThreatSnapshot
from bot.mind.awareness import Awareness, K
from bot.planners.utils.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.defense.defense_bunker_task import DefenseBunkerTask
from bot.tasks.defense.defend_base_task import DefendBaseTask
from bot.tasks.defense.hold_ramp_task import HoldRampTask
from bot.tasks.defense.scv_defensive_pull_task import ScvDefensivePullTask
from bot.tasks.defense.scv_repair_task import ScvRepairTask
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


@dataclass(frozen=True)
class _ScvDefensePickPolicy:
    objective: Point2
    max_distance: float = 18.0
    name: str = "defense.scv.nearest_objective.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != U.SCV:
            return False
        if not bool(getattr(unit, "is_ready", False)):
            return False
        if float(getattr(unit, "health_percentage", 1.0) or 1.0) < 0.45:
            return False
        try:
            if float(unit.distance_to(self.objective)) > float(self.max_distance):
                return False
        except Exception:
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
            carrying_penalty = 4.0 if bool(getattr(unit, "is_carrying_minerals", False) or getattr(unit, "is_carrying_vespene", False)) else 0.0
        except Exception:
            carrying_penalty = 0.0
        return (hp * 10.0) - dist - carrying_penalty


@dataclass(frozen=True)
class _HoldRampMarinePickPolicy:
    objective: Point2
    name: str = "defense.ramp.marine.nearest.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != U.MARINE:
            return False
        return bool(getattr(unit, "is_ready", False))

    def score(self, unit, *, bot, attention, now: float) -> float:
        try:
            dist = float(unit.distance_to(self.objective))
        except Exception:
            dist = 9999.0
        return -dist


@dataclass(frozen=True)
class _HoldRampCombatPickPolicy:
    objective: Point2
    unit_type: U
    name: str = "defense.ramp.combat.nearest.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != self.unit_type:
            return False
        if not bool(getattr(unit, "is_ready", False)):
            return False
        try:
            if float(getattr(unit, "health_percentage", 1.0) or 1.0) < 0.25:
                return False
        except Exception:
            return False
        return True

    def score(self, unit, *, bot, attention, now: float) -> float:
        try:
            dist = float(unit.distance_to(self.objective))
        except Exception:
            dist = 9999.0
        hp = float(getattr(unit, "health_percentage", 1.0) or 1.0)
        return (hp * 10.0) - dist


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
    rush_heavy_bonus_general: int = 3
    rush_extreme_bonus_general: int = 6
    scv_pull_max: int = 8
    scv_repair_max: int = 4
    early_defense_window_s: float = 240.0
    low_army_pull_supply_cap: int = 2
    main_breach_radius: float = 11.0
    main_breach_pull_base: int = 5
    early_wall_repair_base: int = 3

    @staticmethod
    def _ready_bunker_garrison_near(bot, *, center: Point2, radius: float = 16.0) -> int:
        total = 0
        for unit_type in (U.MARINE, U.MARAUDER, U.REAPER):
            try:
                total += int(bot.units(unit_type).ready.closer_than(float(radius), center).amount)
            except Exception:
                continue
        return int(total)

    def _pid_base(self, base_tag: int) -> str:
        return f"{self.planner_id}:defend:base:{int(base_tag)}"

    def _pid_bunker(self, base_tag: int) -> str:
        return f"{self.planner_id}:bunker:base:{int(base_tag)}"

    def _pid_scv_pull(self, base_tag: int) -> str:
        return f"{self.planner_id}:scv_pull:base:{int(base_tag)}"

    def _pid_repair(self, base_tag: int) -> str:
        return f"{self.planner_id}:repair:base:{int(base_tag)}"

    def _pid_hold_ramp(self, base_tag: int) -> str:
        return f"{self.planner_id}:hold_ramp:base:{int(base_tag)}"

    def _make_defend_factory(self, *, awareness: Awareness, base_tag: int, base_pos: Point2, objective: Point2):
        def _factory(mission_id: str) -> DefendBaseTask:
            return DefendBaseTask(
                awareness=awareness,
                base_tag=int(base_tag),
                base_pos=base_pos,
                threat_pos=objective,
                log=self.log,
            )

        return _factory

    def _make_bunker_factory(self, *, base_tag: int, base_pos: Point2, threat_pos: Point2, anchor_mode: str):
        def _factory(mission_id: str) -> DefenseBunkerTask:
            return DefenseBunkerTask(
                base_tag=int(base_tag),
                base_pos=base_pos,
                threat_pos=threat_pos,
                anchor_mode=str(anchor_mode),
                log=self.log,
            )

        return _factory

    def _make_scv_pull_factory(self, *, base_tag: int, base_pos: Point2, threat_pos: Point2):
        def _factory(mission_id: str) -> ScvDefensivePullTask:
            return ScvDefensivePullTask(
                base_tag=int(base_tag),
                base_pos=base_pos,
                threat_pos=threat_pos,
                log=self.log,
            )

        return _factory

    def _make_repair_factory(self, *, base_tag: int, base_pos: Point2, threat_pos: Point2):
        def _factory(mission_id: str) -> ScvRepairTask:
            return ScvRepairTask(
                base_tag=int(base_tag),
                base_pos=base_pos,
                threat_pos=threat_pos,
                log=self.log,
            )

        return _factory

    def _make_hold_ramp_factory(self, *, base_tag: int, base_pos: Point2, threat_pos: Point2):
        def _factory(mission_id: str) -> HoldRampTask:
            return HoldRampTask(
                base_tag=int(base_tag),
                base_pos=base_pos,
                threat_pos=threat_pos,
                log=self.log,
            )

        return _factory

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
    def _rush_ctx(*, awareness: Awareness, now: float) -> dict[str, float | str | bool]:
        state = str(awareness.mem.get(("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        tier = str(awareness.mem.get(("enemy", "rush", "tier"), now=now, default="NONE") or "NONE").upper()
        severity = float(awareness.mem.get(("enemy", "rush", "severity"), now=now, default=0.0) or 0.0)
        scout_no_natural_confirmed = bool(
            awareness.mem.get(("enemy", "rush", "scout_no_natural_confirmed"), now=now, default=False)
        )
        build_snapshot = awareness.mem.get(("enemy", "build", "snapshot"), now=now, default={}) or {}
        if not isinstance(build_snapshot, dict):
            build_snapshot = {}
        enemy_bases_visible = int(build_snapshot.get("bases_visible", 0) or 0)
        enemy_natural_on_ground = bool(build_snapshot.get("natural_on_ground", False))
        active = bool(state in {"SUSPECTED", "CONFIRMED", "HOLDING"})
        return {
            "state": str(state),
            "tier": str(tier),
            "severity": float(severity),
            "active": bool(active),
            "heavy": bool(active and tier in {"HEAVY", "EXTREME"}),
            "extreme": bool(active and tier == "EXTREME"),
            "scout_no_natural_confirmed": bool(scout_no_natural_confirmed),
            "enemy_bases_visible": int(enemy_bases_visible),
            "enemy_natural_on_ground": bool(enemy_natural_on_ground),
            "enemy_one_base_rush": bool(
                active and (bool(scout_no_natural_confirmed) or int(enemy_bases_visible) <= 1 or not bool(enemy_natural_on_ground))
            ),
        }

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
        pool = [U.SIEGETANK, U.WIDOWMINE, U.REAPER, U.CYCLONE, U.MARAUDER, U.MARINE, U.HELLION, U.THOR, U.THORAP, U.MEDIVAC]
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

    @staticmethod
    def _is_natural_base(bot, *, base_pos: Point2) -> bool:
        try:
            own_nat = getattr(getattr(bot, "mediator", None), "get_own_nat", None)
            return own_nat is not None and float(base_pos.distance_to(own_nat)) <= 4.5
        except Exception:
            return False

    def _threat_priority(self, *, bot, th: BaseThreatSnapshot, rush_ctx: dict[str, float | str | bool] | None = None) -> float:
        defense_here = self._own_defense_score_near_base(bot, base_pos=th.th_pos)
        raw = (float(th.urgency) + (2.2 * float(th.enemy_count))) - (2.1 * float(defense_here))
        rush_ctx = rush_ctx or {}
        is_nat = self._is_natural_base(bot, base_pos=th.th_pos)
        is_main = False
        try:
            is_main = float(th.th_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False
        if bool(rush_ctx.get("active", False)) and is_nat:
            raw += 3.5
            if float(defense_here) < 6.0:
                raw += 2.0
        if bool(rush_ctx.get("enemy_one_base_rush", False)) and is_nat:
            raw += 2.5
        if bool(rush_ctx.get("active", False)) and is_main and float(defense_here) >= 8.0:
            raw -= 2.5
        return float(raw)

    def _fallback_base_candidates(self, bot, *, rush_ctx: dict[str, float | str | bool]) -> list[BaseThreatSnapshot]:
        ths = list(getattr(bot, "townhalls", []) or [])
        if not ths:
            return []
        try:
            enemy_main = bot.enemy_start_locations[0]
        except Exception:
            enemy_main = None

        scored: list[tuple[float, BaseThreatSnapshot]] = []
        one_base_rush = bool(rush_ctx.get("enemy_one_base_rush", False))
        for th in ths:
            base_pos = th.position
            defense_here = self._own_defense_score_near_base(bot, base_pos=base_pos)
            repair_pressure = float(self._repair_pressure_near_base(bot, base_pos=base_pos))
            if enemy_main is not None:
                try:
                    dist = float(base_pos.distance_to(enemy_main))
                except Exception:
                    dist = 80.0
            else:
                dist = 80.0
            exposure = max(0.0, min(1.0, (90.0 - dist) / 90.0))
            vulnerability = (3.5 * exposure) + max(0.0, 3.0 - float(defense_here))
            vulnerability += min(8.0, 1.8 * float(repair_pressure))
            if one_base_rush:
                try:
                    main_bias = max(0.0, 1.0 - (float(base_pos.distance_to(bot.start_location)) / 20.0))
                except Exception:
                    main_bias = 0.0
                vulnerability += (4.5 * float(main_bias))
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
    def _base_anchor_mode(bot, *, base_pos: Point2) -> str:
        try:
            own_nat = getattr(getattr(bot, "mediator", None), "get_own_nat", None)
            if own_nat is not None and float(base_pos.distance_to(own_nat)) <= 4.5:
                return "NAT_CHOKE"
        except Exception:
            pass
        try:
            ths = list(getattr(bot, "townhalls", []) or [])
            if not ths:
                return "BASE"
            ordered = sorted(ths, key=lambda th: float(th.distance_to(bot.start_location)))
            if ordered:
                if float(base_pos.distance_to(ordered[0].position)) <= 2.5:
                    return "MAIN_RAMP"
                if len(ordered) >= 2 and float(base_pos.distance_to(ordered[1].position)) <= 3.5:
                    return "NAT_CHOKE"
        except Exception:
            pass
        return "PERIMETER"

    @staticmethod
    def _objective(th: BaseThreatSnapshot) -> Point2:
        return th.threat_pos or th.th_pos

    @staticmethod
    def _available(bot, unit_type: U) -> int:
        return int(bot.units.of_type(unit_type).ready.amount)

    def _requirements(self, *, bot, th: BaseThreatSnapshot, objective: Point2, rush_ctx: dict[str, float | str | bool]) -> list[UnitRequirement]:
        urgency = int(th.urgency)
        desired_tanks = 1 if urgency < 35 else (2 if urgency < 70 else 3)
        desired_mines = 1 if urgency < 40 else 2
        desired_general = 3 if urgency < 35 else (6 if urgency < 70 else 10)
        if bool(rush_ctx.get("heavy", False)):
            desired_tanks = max(int(desired_tanks), 2 if urgency < 70 else 3)
            desired_mines = max(int(desired_mines), 2)
            desired_general += int(self.rush_heavy_bonus_general)
        if bool(rush_ctx.get("extreme", False)):
            desired_tanks = max(int(desired_tanks), 3)
            desired_mines = max(int(desired_mines), 2)
            desired_general += int(self.rush_extreme_bonus_general)

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
        if bool(rush_ctx.get("heavy", False)):
            general_types = [U.MARINE, U.MARAUDER, U.CYCLONE, U.HELLION, U.THOR, U.THORAP]
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

    @staticmethod
    def _should_request_bunker(*, bot, th: BaseThreatSnapshot | None, rush_ctx: dict[str, float | str | bool]) -> bool:
        if th is None:
            return False
        tier = str(rush_ctx.get("tier", "NONE"))
        state = str(rush_ctx.get("state", "NONE"))
        severity = float(rush_ctx.get("severity", 0.0) or 0.0)
        one_base_rush = bool(rush_ctx.get("enemy_one_base_rush", False))
        scout_no_natural_confirmed = bool(rush_ctx.get("scout_no_natural_confirmed", False))
        local_contact = False
        try:
            local_contact = int(bot.enemy_units.closer_than(10.0, th.th_pos).amount) >= 2
        except Exception:
            local_contact = int(getattr(th, "enemy_count", 0) or 0) >= 2
        is_main = False
        nat_taken = False
        nat_ready = False
        try:
            is_main = float(th.th_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False
        if not bool(is_main):
            for townhall in list(getattr(bot, "townhalls", []) or []):
                try:
                    if float(townhall.distance_to(th.th_pos)) <= 8.0:
                        nat_taken = True
                        if float(getattr(townhall, "build_progress", 1.0) or 1.0) >= 1.0:
                            nat_ready = True
                        break
                except Exception:
                    continue
        main_wall_contact = bool(is_main) and bool(DefensePlanner._enemy_contacting_main_wall(bot))
        proactive_wall_bunker = bool(
            is_main
            and (
                main_wall_contact
                or (local_contact and one_base_rush and state in {"CONFIRMED", "HOLDING"})
                or (one_base_rush and scout_no_natural_confirmed and tier in {"HEAVY", "EXTREME"} and severity >= 0.72)
                or (state == "CONFIRMED" and tier == "EXTREME")
            )
        )
        proactive_nat_bunker = bool(
            (not is_main)
            and bool(nat_ready)
            and (
                (local_contact and one_base_rush and state in {"CONFIRMED", "HOLDING"})
                or (local_contact and state in {"CONFIRMED", "HOLDING"} and tier in {"MEDIUM", "HEAVY", "EXTREME"})
                or (state == "CONFIRMED" and tier == "EXTREME" and severity >= 0.86)
            )
        )
        if (not bool(is_main)) and bool(nat_taken) and (not bool(nat_ready)) and (not bool(local_contact)):
            return False
        if bool(one_base_rush) and not bool(is_main) and not bool(local_contact) and not bool(proactive_nat_bunker):
            return False
        if (
            tier not in {"MEDIUM", "HEAVY", "EXTREME"}
            and not bool(local_contact)
            and not bool(proactive_wall_bunker)
            and not bool(proactive_nat_bunker)
        ):
            return False
        bunker_anchor = th.th_pos
        try:
            if is_main:
                ramp = getattr(bot, "main_base_ramp", None)
                wall_center = getattr(ramp, "top_center", None) if ramp is not None else None
                barracks_pos = getattr(ramp, "barracks_correct_placement", None) if ramp is not None else None
                refs = [p for p in (wall_center, barracks_pos, th.th_pos, getattr(bot, "start_location", None)) if p is not None]
                bunker_anchor = wall_center or barracks_pos or th.th_pos
                existing = [
                    b
                    for b in bot.structures(U.BUNKER)
                    if any(float(b.distance_to(ref)) <= 16.0 for ref in refs)
                ]
            else:
                existing = [b for b in bot.structures(U.BUNKER) if float(b.distance_to(th.th_pos)) <= 16.0]
        except Exception:
            existing = []
            bunker_anchor = th.th_pos
        ready_garrison = DefensePlanner._ready_bunker_garrison_near(bot, center=bunker_anchor)
        if int(ready_garrison) <= 0:
            return False
        try:
            tracker = dict(bot.mediator.get_building_tracker_dict or {})
        except Exception:
            tracker = {}
        pending = 0
        for entry in tracker.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("structure_type", None) != U.BUNKER:
                continue
            pos = entry.get("target", None) or entry.get("pos", None)
            if pos is None:
                continue
            try:
                if is_main and any(float(pos.distance_to(ref)) <= 16.0 for ref in refs):
                    pending += 1
                elif (not is_main) and float(pos.distance_to(th.th_pos)) <= 16.0:
                    pending += 1
            except Exception:
                continue
        max_bunkers = 1 if is_main else 1
        return (len(existing) + int(pending)) < int(max_bunkers)

    @staticmethod
    def _enemy_contacting_main_wall(bot) -> bool:
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            if ramp is None:
                return False
            probes = []
            top = getattr(ramp, "top_center", None)
            if top is not None:
                probes.append((top, 5.5))
            for pos in list(getattr(ramp, "corner_depots", []) or []):
                probes.append((pos, 4.5))
            barracks_pos = getattr(ramp, "barracks_correct_placement", None)
            if barracks_pos is not None:
                probes.append((barracks_pos, 5.0))
            for pos, radius in probes:
                if int(bot.enemy_units.closer_than(float(radius), pos).amount) > 0:
                    return True
        except Exception:
            return False
        return False

    @staticmethod
    def _main_breach_snapshot(bot, *, base_pos: Point2, now: float, early_window_s: float, breach_radius: float) -> dict[str, int | bool]:
        try:
            is_main = float(base_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False
        if not is_main or float(now) > float(early_window_s):
            return {
                "is_main": bool(is_main),
                "early_window": bool(float(now) <= float(early_window_s)),
                "inside_count": 0,
                "ling_count": 0,
                "worker_count": 0,
            }

        inside_count = 0
        ling_count = 0
        worker_count = 0
        for enemy in list(getattr(bot, "enemy_units", []) or []):
            try:
                if float(enemy.distance_to(base_pos)) > float(breach_radius):
                    continue
            except Exception:
                continue
            tid = getattr(enemy, "type_id", None)
            if tid in {U.OVERLORD, U.OVERSEER, U.OBSERVER, U.CHANGELING, U.CHANGELINGMARINESHIELD, U.CHANGELINGMARINE, U.CHANGELINGZEALOT, U.CHANGELINGZERGLING, U.CHANGELINGZERGLINGWINGS}:
                continue
            inside_count += 1
            if tid == U.ZERGLING:
                ling_count += 1
            if tid in {U.SCV, U.DRONE, U.PROBE}:
                worker_count += 1
        return {
            "is_main": bool(is_main),
            "early_window": True,
            "inside_count": int(inside_count),
            "ling_count": int(ling_count),
            "worker_count": int(worker_count),
        }

    @staticmethod
    def _damaged_owned_targets_near_base(bot, *, base_pos: Point2) -> int:
        allowed = {
            U.BUNKER,
            U.SIEGETANK,
            U.SIEGETANKSIEGED,
            U.COMMANDCENTER,
            U.ORBITALCOMMAND,
            U.PLANETARYFORTRESS,
            U.BARRACKS,
            U.BARRACKSREACTOR,
            U.BARRACKSTECHLAB,
            U.SUPPLYDEPOT,
            U.SUPPLYDEPOTLOWERED,
            U.FACTORY,
            U.FACTORYTECHLAB,
        }
        total = 0
        for unit in list(getattr(bot, "structures", []) or []) + list(getattr(bot, "units", []) or []):
            try:
                if unit.type_id not in allowed:
                    continue
                if float(unit.distance_to(base_pos)) > 14.0:
                    continue
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                build_progress = float(getattr(unit, "build_progress", 1.0) or 1.0)
                if hp_max > 0.0 and build_progress >= 1.0 and hp < hp_max:
                    total += 1
            except Exception:
                continue
        return int(total)

    @staticmethod
    def _main_wall_target_tags(bot) -> set[int]:
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            depot_positions = list(getattr(ramp, "corner_depots", []) or []) if ramp is not None else []
            barracks_pos = getattr(ramp, "barracks_correct_placement", None) if ramp is not None else None
        except Exception:
            depot_positions = []
            barracks_pos = None
        if not depot_positions and barracks_pos is None:
            return set()
        wall_types = {U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED, U.BARRACKS, U.BARRACKSREACTOR, U.BARRACKSTECHLAB}
        tags: set[int] = set()
        for unit in list(getattr(bot, "structures", []) or []):
            try:
                if getattr(unit, "type_id", None) not in wall_types:
                    continue
                on_wall = any(float(unit.distance_to(pos)) <= 1.8 for pos in depot_positions)
                if not on_wall and barracks_pos is not None:
                    on_wall = float(unit.distance_to(barracks_pos)) <= 2.4
                if on_wall:
                    tags.add(int(getattr(unit, "tag", -1) or -1))
            except Exception:
                continue
        return tags

    @classmethod
    def _repair_pressure_near_base(cls, bot, *, base_pos: Point2) -> float:
        allowed = {
            U.BUNKER,
            U.SIEGETANK,
            U.SIEGETANKSIEGED,
            U.COMMANDCENTER,
            U.ORBITALCOMMAND,
            U.PLANETARYFORTRESS,
            U.BARRACKS,
            U.BARRACKSREACTOR,
            U.BARRACKSTECHLAB,
            U.SUPPLYDEPOT,
            U.SUPPLYDEPOTLOWERED,
            U.FACTORY,
            U.FACTORYTECHLAB,
        }
        try:
            main_bias = float(base_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            main_bias = False
        wall_tags = cls._main_wall_target_tags(bot) if main_bias else set()
        pressure = 0.0
        seen_tags: set[int] = set()
        for unit in list(getattr(bot, "structures", []) or []) + list(getattr(bot, "units", []) or []):
            try:
                if getattr(unit, "type_id", None) not in allowed:
                    continue
                tag = int(getattr(unit, "tag", -1) or -1)
                if tag in seen_tags:
                    continue
                if float(unit.distance_to(base_pos)) > 16.0:
                    continue
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                build_progress = float(getattr(unit, "build_progress", 1.0) or 1.0)
                if hp_max <= 0.0 or (hp >= hp_max and build_progress >= 1.0):
                    continue
                seen_tags.add(tag)
                weight = 1.0
                tid = getattr(unit, "type_id", None)
                if tid == U.BUNKER:
                    weight = 4.0
                elif tag in wall_tags:
                    weight = 3.0
                elif tid in {U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED, U.BARRACKS, U.BARRACKSREACTOR, U.BARRACKSTECHLAB}:
                    weight = 1.5
                if build_progress < 1.0:
                    weight = max(weight, 1.5)
                pressure += float(weight)
            except Exception:
                continue
        return float(pressure)

    def _scv_pull_count(self, *, bot, th: BaseThreatSnapshot, rush_ctx: dict[str, float | str | bool]) -> int:
        breach = self._main_breach_snapshot(
            bot,
            base_pos=th.th_pos,
            now=float(getattr(bot, "time", 0.0) or 0.0),
            early_window_s=float(self.early_defense_window_s),
            breach_radius=float(self.main_breach_radius),
        )
        is_main = False
        close_enemy_now = 0
        contact_enemy_now = 0
        try:
            is_main = float(th.th_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False
        try:
            close_enemy_now = int(bot.enemy_units.closer_than(16.0, th.th_pos).amount)
        except Exception:
            close_enemy_now = int(th.enemy_count)
        try:
            contact_enemy_now = int(bot.enemy_units.closer_than(10.0, th.th_pos).amount)
        except Exception:
            contact_enemy_now = max(0, int(close_enemy_now))
        defense_units = int(self._defense_units_available(bot))
        early_main_breach = bool(
            breach.get("is_main", False)
            and breach.get("early_window", False)
            and int(breach.get("inside_count", 0) or 0) > 0
            and int(defense_units) <= int(self.low_army_pull_supply_cap)
        )
        if not bool(rush_ctx.get("active", False)) and not bool(early_main_breach):
            return 0
        if bool(rush_ctx.get("enemy_one_base_rush", False)) and not bool(is_main):
            return 0
        main_wall_contact = bool(is_main and self._enemy_contacting_main_wall(bot))
        damaged_owned = int(self._damaged_owned_targets_near_base(bot, base_pos=th.th_pos))
        if bool(main_wall_contact) and not bool(early_main_breach) and int(damaged_owned) <= 0:
            return 0
        if bool(rush_ctx.get("enemy_one_base_rush", False)) and bool(is_main) and not bool(main_wall_contact) and int(damaged_owned) <= 0:
            if not bool(early_main_breach):
                return 0
        committed_contact = bool(
            int(damaged_owned) > 0
            or bool(main_wall_contact)
            or int(contact_enemy_now) >= (2 if bool(rush_ctx.get("enemy_one_base_rush", False)) else 3)
            or bool(early_main_breach)
        )
        if not (
            bool(rush_ctx.get("heavy", False))
            or bool(rush_ctx.get("enemy_one_base_rush", False))
            or (is_main and str(rush_ctx.get("state", "NONE")) in {"CONFIRMED", "HOLDING"})
            or (is_main and bool(committed_contact))
            or bool(early_main_breach)
        ):
            return 0
        if not bool(committed_contact):
            return 0
        threat_workers = int(max(0, int(th.enemy_count) - int(defense_units)))
        base = 2 if int(th.urgency) < 40 else 4
        if is_main and (bool(main_wall_contact) or int(contact_enemy_now) >= 2):
            base = max(int(base), 3 if int(contact_enemy_now) < 6 else 5)
        if int(damaged_owned) > 0:
            base = max(int(base), 4)
        if bool(early_main_breach):
            inside_count = int(breach.get("inside_count", 0) or 0)
            ling_count = int(breach.get("ling_count", 0) or 0)
            base = max(int(base), int(self.main_breach_pull_base))
            if ling_count >= 4:
                base = max(int(base), 6)
            desired = max(int(base), int(inside_count + 1), int(ling_count), int(threat_workers))
        else:
            desired = max(int(base), int(threat_workers))
        if bool(rush_ctx.get("extreme", False)):
            desired += 2
        return max(0, min(int(self.scv_pull_max), int(desired)))

    @staticmethod
    def _repair_targets_near_base(bot, *, base_pos: Point2) -> int:
        allowed = {
            U.BUNKER,
            U.SIEGETANK,
            U.SIEGETANKSIEGED,
            U.COMMANDCENTER,
            U.ORBITALCOMMAND,
            U.PLANETARYFORTRESS,
            U.BARRACKS,
            U.BARRACKSREACTOR,
            U.BARRACKSTECHLAB,
            U.SUPPLYDEPOT,
            U.SUPPLYDEPOTLOWERED,
            U.FACTORY,
            U.FACTORYTECHLAB,
        }
        total = 0
        for unit in list(getattr(bot, "structures", []) or []) + list(getattr(bot, "units", []) or []):
            try:
                if unit.type_id not in allowed:
                    continue
                if float(unit.distance_to(base_pos)) > 16.0:
                    continue
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                build_progress = float(getattr(unit, "build_progress", 1.0) or 1.0)
                if hp_max > 0.0 and (hp < hp_max or build_progress < 1.0):
                    total += 1
            except Exception:
                continue
        try:
            main_bias = float(base_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            main_bias = False
        if main_bias:
            try:
                ramp = getattr(bot, "main_base_ramp", None)
                depot_positions = list(getattr(ramp, "corner_depots", []) or []) if ramp is not None else []
                barracks_pos = getattr(ramp, "barracks_correct_placement", None) if ramp is not None else None
            except Exception:
                depot_positions = []
                barracks_pos = None
            wall_types = {U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED, U.BARRACKS, U.BARRACKSREACTOR, U.BARRACKSTECHLAB}
            for unit in list(getattr(bot, "structures", []) or []):
                try:
                    if unit.type_id not in wall_types:
                        continue
                    on_wall = any(float(unit.distance_to(pos)) <= 1.8 for pos in depot_positions)
                    if not on_wall and barracks_pos is not None:
                        on_wall = float(unit.distance_to(barracks_pos)) <= 2.4
                    if not on_wall:
                        continue
                    hp = float(getattr(unit, "health", 0.0) or 0.0)
                    hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                    build_progress = float(getattr(unit, "build_progress", 1.0) or 1.0)
                    if hp_max > 0.0 and (hp < hp_max or build_progress < 1.0):
                        total += 1
                except Exception:
                    continue
        return int(total)

    def _repair_count(self, *, bot, th: BaseThreatSnapshot, rush_ctx: dict[str, float | str | bool]) -> int:
        repairables = int(self._repair_targets_near_base(bot, base_pos=th.th_pos))
        repair_pressure = float(self._repair_pressure_near_base(bot, base_pos=th.th_pos))
        if repairables <= 0 or repair_pressure <= 0.0:
            return 0
        breach = self._main_breach_snapshot(
            bot,
            base_pos=th.th_pos,
            now=float(getattr(bot, "time", 0.0) or 0.0),
            early_window_s=float(self.early_defense_window_s),
            breach_radius=float(self.main_breach_radius),
        )
        is_main = False
        close_enemy_now = 0
        try:
            is_main = float(th.th_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False
        try:
            close_enemy_now = int(bot.enemy_units.closer_than(14.0, th.th_pos).amount)
        except Exception:
            close_enemy_now = int(th.enemy_count)
        if bool(rush_ctx.get("enemy_one_base_rush", False)) and not bool(is_main):
            return 0
        main_wall_contact = bool(is_main and self._enemy_contacting_main_wall(bot))
        damaged_ready = int(self._damaged_owned_targets_near_base(bot, base_pos=th.th_pos))
        if bool(rush_ctx.get("enemy_one_base_rush", False)) and bool(is_main) and not bool(main_wall_contact) and int(damaged_ready) <= 0:
            if int(breach.get("inside_count", 0) or 0) <= 0:
                return 0
        local_pressure = bool(
            int(close_enemy_now) > 0
            or bool(main_wall_contact)
            or int(th.enemy_count) > 0
            or int(breach.get("inside_count", 0) or 0) > 0
        )
        high_priority_damage = bool(repair_pressure >= 3.0 or int(damaged_ready) > 0)
        if (not bool(local_pressure)) and not bool(high_priority_damage):
            return 0
        if bool(rush_ctx.get("active", False)):
            desired = 2 if repairables == 1 else 3
        else:
            desired = 1
            if repair_pressure >= 3.0:
                desired = 2
            if repair_pressure >= 6.0 or repairables >= 3:
                desired = 3
        if bool(main_wall_contact) and bool(is_main) and bool(breach.get("early_window", False)):
            desired = max(int(desired), int(self.early_wall_repair_base))
        if int(breach.get("inside_count", 0) or 0) > 0 and bool(is_main):
            desired = max(int(desired), 3)
        if bool(rush_ctx.get("extreme", False)) and bool(rush_ctx.get("active", False)):
            desired += 1
        return max(1, min(int(self.scv_repair_max), int(desired)))

    def _hold_ramp_reqs(self, *, bot, objective: Point2, scv_count: int) -> list[UnitRequirement]:
        reqs: list[UnitRequirement] = []
        enemy_at_ramp = 0
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            top = getattr(ramp, "top_center", None) if ramp is not None else None
            if top is not None:
                enemy_at_ramp = int(bot.enemy_units.closer_than(9.0, top).amount)
        except Exception:
            enemy_at_ramp = 0

        combat_types = (
            U.REAPER,
            U.MARINE,
            U.MARAUDER,
            U.CYCLONE,
            U.HELLION,
            U.THOR,
            U.THORAP,
            U.MEDIVAC,
        )
        primary_required = True
        for unit_type in combat_types:
            avail = int(self._available(bot, unit_type))
            if avail <= 0:
                continue
            if unit_type == U.MARINE:
                target_count = min(int(avail), max(2, 6 + max(0, int(enemy_at_ramp) - 4)))
                pick_policy = _HoldRampMarinePickPolicy(objective=objective)
            elif unit_type == U.MEDIVAC:
                target_count = min(1, int(avail))
                pick_policy = _HoldRampCombatPickPolicy(objective=objective, unit_type=unit_type)
            else:
                target_count = int(avail)
                pick_policy = _HoldRampCombatPickPolicy(objective=objective, unit_type=unit_type)
            if target_count <= 0:
                continue
            reqs.append(
                UnitRequirement(
                    unit_type=unit_type,
                    count=int(target_count),
                    pick_policy=pick_policy,
                    required=bool(primary_required),
                )
            )
            primary_required = False
        if scv_count > 0:
            reqs.append(
                UnitRequirement(
                    unit_type=U.SCV,
                    count=int(scv_count),
                    pick_policy=_ScvDefensePickPolicy(objective=objective),
                    required=len(reqs) == 0,
                )
            )
        return reqs

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        out: list[Proposal] = []
        rush_ctx = self._rush_ctx(awareness=awareness, now=now)
        secure_natural_commit = bool(
            awareness.mem.get(K("intel", "map_control", "our_nat", "should_secure"), now=now, default=False)
        )
        threats_raw = [b for b in self._threats(attention) if int(b.urgency) >= int(self.min_base_urgency)]
        if threats_raw:
            threats_raw.sort(key=lambda th: self._threat_priority(bot=bot, th=th, rush_ctx=rush_ctx), reverse=True)
            threats = threats_raw[: max(1, int(self.max_bases_per_tick))]
        elif bool(self.existence_trigger_enabled) and (not bool(secure_natural_commit)) and (
            int(self._defense_units_available(bot)) > 0
            or bool(rush_ctx.get("active", False))
            or any(float(self._repair_pressure_near_base(bot, base_pos=th.position)) > 0.0 for th in list(getattr(bot, "townhalls", []) or []))
        ):
            threats = self._fallback_base_candidates(bot, rush_ctx=rush_ctx)[: max(1, int(self.max_bases_per_tick))]
        else:
            threats = []

        for th in threats:
            pid = self._pid_base(int(th.th_tag))
            if awareness.ops_proposal_running(proposal_id=pid, now=now):
                continue
            if not self._due(awareness=awareness, now=now, pid=pid):
                continue

            objective = self._objective(th)
            is_main_base = False
            try:
                is_main_base = float(th.th_pos.distance_to(bot.start_location)) <= 10.0
            except Exception:
                is_main_base = False
            effective_urgency = int(th.urgency)
            if bool(rush_ctx.get("heavy", False)):
                effective_urgency += 10
            elif bool(rush_ctx.get("active", False)):
                effective_urgency += 4
            bunker_pid = self._pid_bunker(int(th.th_tag))
            if (
                self._should_request_bunker(bot=bot, th=th, rush_ctx=rush_ctx)
                and not awareness.ops_proposal_running(proposal_id=bunker_pid, now=now)
                and self._due(awareness=awareness, now=now, pid=bunker_pid)
            ):
                bunker_factory = self._make_bunker_factory(
                    base_tag=int(th.th_tag),
                    base_pos=th.th_pos,
                    threat_pos=objective,
                    anchor_mode=self._base_anchor_mode(bot, base_pos=th.th_pos),
                )
                out.append(
                    Proposal(
                        proposal_id=bunker_pid,
                        domain="DEFENSE",
                        score=min(100, self._score_from_urgency(int(effective_urgency) + 6)),
                        tasks=[
                            TaskSpec(
                                task_id="defense_bunker",
                                task_factory=bunker_factory,
                                unit_requirements=[
                                    UnitRequirement(
                                        unit_type=U.SCV,
                                        count=1,
                                        pick_policy=_ScvDefensePickPolicy(objective=th.th_pos),
                                        required=True,
                                    )
                                ],
                                lease_ttl=18.0,
                            )
                        ],
                        lease_ttl=18.0,
                        cooldown_s=0.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                )
                self._mark_proposed(awareness=awareness, now=now, pid=bunker_pid)
            reqs = self._requirements(bot=bot, th=th, objective=objective, rush_ctx=rush_ctx)
            if not reqs:
                continue

            base_pos = th.th_pos

            factory = self._make_defend_factory(
                awareness=awareness,
                base_tag=int(th.th_tag),
                base_pos=base_pos,
                objective=objective,
            )

            out.append(
                Proposal(
                    proposal_id=pid,
                    domain="DEFENSE",
                    score=self._score_from_urgency(int(effective_urgency)),
                    tasks=[
                        TaskSpec(
                            task_id="defend_base",
                            task_factory=factory,
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

            hold_ramp_pid = self._pid_hold_ramp(int(th.th_tag))
            main_wall_contact = bool(
                is_main_base and self._enemy_contacting_main_wall(bot)
            ) if getattr(bot, "start_location", None) is not None else False
            if (
                bool(main_wall_contact)
                and not awareness.ops_proposal_running(proposal_id=hold_ramp_pid, now=now)
                and self._due(awareness=awareness, now=now, pid=hold_ramp_pid)
            ):
                repair_count = max(2, self._repair_count(bot=bot, th=th, rush_ctx=rush_ctx))
                hold_factory = self._make_hold_ramp_factory(
                    base_tag=int(th.th_tag),
                    base_pos=th.th_pos,
                    threat_pos=objective,
                )
                hold_reqs = self._hold_ramp_reqs(bot=bot, objective=th.th_pos, scv_count=repair_count)
                if hold_reqs:
                    out.append(
                        Proposal(
                            proposal_id=hold_ramp_pid,
                            domain="DEFENSE",
                            score=min(100, self._score_from_urgency(int(effective_urgency) + 8)),
                            tasks=[
                                TaskSpec(
                                    task_id="hold_ramp",
                                    task_factory=hold_factory,
                                    unit_requirements=hold_reqs,
                                    lease_ttl=12.0,
                                )
                            ],
                            lease_ttl=12.0,
                            cooldown_s=0.0,
                            risk_level=0,
                            allow_preempt=True,
                        )
                    )
                    self._mark_proposed(awareness=awareness, now=now, pid=hold_ramp_pid)
            scv_pull_count = self._scv_pull_count(bot=bot, th=th, rush_ctx=rush_ctx)
            scv_pull_pid = self._pid_scv_pull(int(th.th_tag))
            if (
                scv_pull_count > 0
                and (not bool(main_wall_contact) or bool(is_main_base))
                and not awareness.ops_proposal_running(proposal_id=scv_pull_pid, now=now)
                and self._due(awareness=awareness, now=now, pid=scv_pull_pid)
            ):
                scv_pull_factory = self._make_scv_pull_factory(
                    base_tag=int(th.th_tag),
                    base_pos=th.th_pos,
                    threat_pos=objective,
                )
                out.append(
                    Proposal(
                        proposal_id=scv_pull_pid,
                        domain="DEFENSE",
                        score=min(100, self._score_from_urgency(int(effective_urgency) + 3)),
                        tasks=[
                            TaskSpec(
                                task_id="scv_defensive_pull",
                                task_factory=scv_pull_factory,
                                unit_requirements=[
                                    UnitRequirement(
                                        unit_type=U.SCV,
                                        count=int(scv_pull_count),
                                        pick_policy=_ScvDefensePickPolicy(objective=th.th_pos),
                                        required=True,
                                    )
                                ],
                                lease_ttl=12.0,
                            )
                        ],
                        lease_ttl=12.0,
                        cooldown_s=0.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                )
                self._mark_proposed(awareness=awareness, now=now, pid=scv_pull_pid)

            repair_count = self._repair_count(bot=bot, th=th, rush_ctx=rush_ctx)
            repair_pid = self._pid_repair(int(th.th_tag))
            if (
                repair_count > 0
                and (not bool(main_wall_contact) or bool(is_main_base))
                and not awareness.ops_proposal_running(proposal_id=repair_pid, now=now)
                and self._due(awareness=awareness, now=now, pid=repair_pid)
            ):
                repair_factory = self._make_repair_factory(
                    base_tag=int(th.th_tag),
                    base_pos=th.th_pos,
                    threat_pos=objective,
                )
                out.append(
                    Proposal(
                        proposal_id=repair_pid,
                        domain="DEFENSE",
                        score=min(100, self._score_from_urgency(int(effective_urgency) + 4)),
                        tasks=[
                            TaskSpec(
                                task_id="scv_repair",
                                task_factory=repair_factory,
                                unit_requirements=[
                                    UnitRequirement(
                                        unit_type=U.SCV,
                                        count=int(repair_count),
                                        pick_policy=_ScvDefensePickPolicy(objective=th.th_pos),
                                        required=True,
                                    )
                                ],
                                lease_ttl=12.0,
                            )
                        ],
                        lease_ttl=12.0,
                        cooldown_s=0.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                )
                self._mark_proposed(awareness=awareness, now=now, pid=repair_pid)

        if self.log is not None:
            self.log.emit(
                "planner_proposed",
                {
                    "planner": self.planner_id,
                    "count": len(out),
                    "bases_considered": int(len(threats)),
                    "base_tags": [int(b.th_tag) for b in threats],
                    "base_urgencies": [int(b.urgency) for b in threats],
                    "rush_tier": str(rush_ctx.get("tier", "NONE")),
                    "rush_severity": float(round(float(rush_ctx.get("severity", 0.0) or 0.0), 3)),
                },
                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
            )
        return out
