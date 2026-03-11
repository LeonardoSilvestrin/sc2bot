from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Optional

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.intel.geometry.sector_types import SectorId, SectorMode
from bot.intel.strategy.i3_army_posture_intel import ArmyPosture
from bot.mind.attention import Attention, BaseThreatSnapshot
from bot.mind.awareness import Awareness, K
from bot.planners.utils.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.defense.defense_bunker_task import DefenseBunkerTask
from bot.tasks.defense.defend_base_task import DefendBaseTask
from bot.tasks.defense.hold_ramp_task import HoldRampTask
from bot.tasks.defense.scv_defensive_pull_task import ScvDefensivePullTask
from bot.tasks.defense.scv_repair_task import ScvRepairTask
from bot.tasks.defense.defend_task import Defend
from bot.tasks.defense.lift_natural_task import LiftNaturalTask
from bot.tasks.defense.reaper_nat_patrol_task import ReaperPatrolTask


@dataclass(frozen=True)
class _DefendPickPolicy:
    objective: Point2
    unit_type: U
    bulk_anchor_pos: Optional[Point2] = None
    defense_overflow: bool = False
    bulk_exclusion_radius: float = 14.0
    name: str = "defense.base.nearest_objective.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != self.unit_type:
            return False
        if not bool(getattr(unit, "is_ready", False)):
            return False
        if float(getattr(unit, "health_percentage", 1.0) or 1.0) < 0.30:
            return False
        # Invariante 6: unidades no setor MASS_HOLD não são elegíveis para defense
        # a menos que defense_overflow=True (emergência real)
        if not self.defense_overflow and self.bulk_anchor_pos is not None:
            try:
                if float(unit.distance_to(self.bulk_anchor_pos)) <= float(self.bulk_exclusion_radius):
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
            if bool(getattr(unit, "is_carrying_resource", False)):
                return False
        except Exception:
            pass
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
    defend_task: Defend | None = None
    log: DevLogger | None = None
    cadence_s: float = 2.0
    min_base_urgency: int = 1
    max_bases_per_tick: int = 3
    existence_trigger_enabled: bool = True
    rush_heavy_bonus_general: int = 3
    rush_extreme_bonus_general: int = 6
    scv_pull_max: int = 8
    scv_repair_max: int = 4
    scv_hold_ramp_max: int = 3
    early_defense_window_s: float = 240.0
    low_army_pull_supply_cap: int = 2
    main_breach_radius: float = 11.0
    main_breach_pull_base: int = 5
    early_wall_repair_base: int = 2

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

    def _pid_reaper_nat_patrol(self) -> str:
        return f"{self.planner_id}:reaper_nat_patrol"

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

    def _make_bunker_factory(self, *, awareness: Awareness, base_tag: int, base_pos: Point2, threat_pos: Point2, anchor_mode: str):
        def _factory(mission_id: str) -> DefenseBunkerTask:
            return DefenseBunkerTask(
                awareness=awareness,
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

    def _make_repair_factory(
        self,
        *,
        base_tag: int,
        base_pos: Point2,
        threat_pos: Point2,
        repair_focus_pos: Point2 | None = None,
    ):
        def _factory(mission_id: str) -> ScvRepairTask:
            return ScvRepairTask(
                base_tag=int(base_tag),
                base_pos=base_pos,
                threat_pos=threat_pos,
                repair_focus_pos=repair_focus_pos,
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

    def _make_reaper_patrol_factory(
        self,
        *,
        roam_center: Point2,
        safe_point: Point2,
        roam_radius: float = 7.0,
        engage_radius: float = 12.0,
        patrol_points: tuple[Point2, ...] | list[Point2] | None = None,
        task_domain: str = "DEFENSE",
        task_id: str = "reaper_patrol",
    ):
        def _factory(mission_id: str) -> ReaperPatrolTask:
            return ReaperPatrolTask(
                roam_center=roam_center,
                safe_point=safe_point,
                roam_radius=float(roam_radius),
                engage_radius=float(engage_radius),
                patrol_points=patrol_points,
                task_domain=str(task_domain),
                task_id=str(task_id),
                log=self.log,
            )
        return _factory

    def _make_lift_natural_factory(self, *, nat_pos: Point2, anchor_pos: Point2):
        def _factory(mission_id: str) -> LiftNaturalTask:
            return LiftNaturalTask(
                nat_pos=nat_pos,
                anchor_pos=anchor_pos,
                log=self.log,
            )
        return _factory

    @staticmethod
    def _should_lift_natural(bot, *, awareness: Awareness, rush_ctx: dict, now: float) -> bool:
        _DANGER_PERSIST_S = 5.0   # segundos de perigo contínuo antes de levantar
        _ENEMY_MIN = 4            # inimigos visíveis mínimos para acionar
        _DEFENSE_MAX = 2.0        # threshold de defesa efetiva para considerar indefesa

        try:
            own_nat = getattr(getattr(bot, "mediator", None), "get_own_nat", None)
            if own_nat is None:
                return False
        except Exception:
            return False
        nat_cc = None
        for th in list(getattr(bot, "townhalls", []) or []):
            try:
                if float(th.distance_to(own_nat)) <= 8.0:
                    nat_cc = th
                    break
            except Exception:
                continue
        if nat_cc is None:
            return False
        if nat_cc.type_id not in {U.COMMANDCENTER, U.ORBITALCOMMAND}:
            return False

        # A base precisa ter tomado dano — não levanta CC saudável.
        try:
            hp = float(getattr(nat_cc, "health", 0) or 0)
            hp_max = float(getattr(nat_cc, "health_max", 1500) or 1500)
            if hp >= hp_max:
                return False
        except Exception:
            return False

        try:
            enemy_near = int(bot.enemy_units.closer_than(10.0, own_nat).amount)
        except Exception:
            return False
        if enemy_near < _ENEMY_MIN:
            # Perigo desapareceu — limpa o timestamp
            awareness.mem.set(("ops", "defense", "nat_lift", "danger_since"), value=None, now=now, ttl=None)
            return False

        # Bunker contribui 4.0 ao score mas sem garrison não segura a nat.
        # Desconta bunkers do score para avaliar se a nat realmente tem defesa suficiente.
        bunker_score = 0.0
        try:
            for b in bot.structures(U.BUNKER):
                if float(b.distance_to(own_nat)) <= 16.0:
                    bunker_score += 4.0
        except Exception:
            pass
        defense_score = DefensePlanner._own_defense_score_near_base(bot, base_pos=own_nat)
        effective_defense = defense_score - bunker_score
        if effective_defense >= _DEFENSE_MAX:
            awareness.mem.set(("ops", "defense", "nat_lift", "danger_since"), value=None, now=now, ttl=None)
            return False

        # Não levanta se tem exército disponível na main suficiente para descer e brigar.
        # O exército vai ser acionado pelo defense_overflow — levantar aqui seria desperdício.
        _MAIN_ARMY_RESCUE_SUPPLY = 6  # supply mínimo de combate na main para cancelar o lift
        _COMBAT_TYPES = {U.MARINE, U.MARAUDER, U.CYCLONE, U.HELLION, U.THOR, U.THORAP, U.SIEGETANK, U.SIEGETANKSIEGED}
        _SUPPLY_COST_LIFT = {U.MARINE: 1, U.MARAUDER: 2, U.CYCLONE: 3, U.HELLION: 2, U.THOR: 6, U.THORAP: 6, U.SIEGETANK: 3, U.SIEGETANKSIEGED: 3}
        try:
            main_army_supply = 0
            for u in bot.units:
                if getattr(u, "type_id", None) not in _COMBAT_TYPES:
                    continue
                if not bool(getattr(u, "is_ready", False)):
                    continue
                try:
                    if float(u.distance_to(bot.start_location)) <= 30.0:
                        main_army_supply += int(_SUPPLY_COST_LIFT.get(u.type_id, 1))
                except Exception:
                    pass
            if main_army_supply >= _MAIN_ARMY_RESCUE_SUPPLY:
                awareness.mem.set(("ops", "defense", "nat_lift", "danger_since"), value=None, now=now, ttl=None)
                return False
        except Exception:
            pass

        # Perigo confirmado — exige persistência temporal antes de levantar.
        danger_since = awareness.mem.get(("ops", "defense", "nat_lift", "danger_since"), now=now, default=None)
        if danger_since is None:
            awareness.mem.set(("ops", "defense", "nat_lift", "danger_since"), value=float(now), now=now, ttl=30.0)
            return False
        try:
            elapsed = float(now) - float(danger_since)
        except Exception:
            return False
        return elapsed >= _DANGER_PERSIST_S

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
        # Read active opening so bunker logic can gate on build type.
        opening_selected = str(awareness.mem.get(K("macro", "opening", "selected"), now=now, default="") or "")
        if not opening_selected.strip():
            opening_selected = str(awareness.mem.get(K("macro", "opening", "build_selected"), now=now, default="") or "")
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
            "opening_selected": str(opening_selected),
            "is_mech_build": bool(str(opening_selected).startswith("Mecha")),
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

    @classmethod
    def _is_outer_base(cls, bot, *, base_pos: Point2) -> bool:
        try:
            is_main = float(base_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False
        return bool((not is_main) and (not cls._is_natural_base(bot, base_pos=base_pos)))

    @staticmethod
    def _main_ramp_anchor(bot) -> Point2:
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            if ramp is not None:
                top = getattr(ramp, "top_center", None)
                if top is not None:
                    return top
                barracks_pos = getattr(ramp, "barracks_correct_placement", None)
                if barracks_pos is not None:
                    return barracks_pos
        except Exception:
            pass
        try:
            enemy_main = bot.enemy_start_locations[0]
            return bot.start_location.towards(enemy_main, 8.0)
        except Exception:
            return bot.start_location

    @staticmethod
    def _nat_choke_anchor(bot, *, base_pos: Point2) -> Point2:
        try:
            enemy_main = bot.enemy_start_locations[0]
            return base_pos.towards(enemy_main, 4.5)
        except Exception:
            return base_pos

    @staticmethod
    def _reaper_nat_patrol_points(bot, *, own_nat: Point2, nat_anchor: Point2, nat_has_cc: bool) -> tuple[Point2, ...]:
        points: list[Point2] = []
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            bottom = getattr(ramp, "bottom_center", None) if ramp is not None else None
            if isinstance(bottom, Point2):
                points.append(bottom)
        except Exception:
            pass
        points.extend([own_nat, nat_anchor])
        try:
            expansions = list(getattr(getattr(bot, "mediator", None), "get_own_expansions", []) or [])
        except Exception:
            expansions = []
        try:
            if not expansions:
                expansions = [(p, float(own_nat.distance_to(p))) for p in list(getattr(bot, "expansion_locations_list", []) or [])]
        except Exception:
            expansions = expansions or []

        extras: list[Point2] = []
        for item in expansions:
            try:
                pos = item[0] if isinstance(item, tuple) else item
            except Exception:
                pos = item
            if not isinstance(pos, Point2):
                continue
            try:
                if float(pos.distance_to(own_nat)) <= 4.5:
                    continue
                if float(pos.distance_to(bot.start_location)) <= 8.0:
                    continue
                if float(pos.distance_to(own_nat)) > (16.0 if nat_has_cc else 18.0):
                    continue
            except Exception:
                continue
            extras.append(pos)

        try:
            extras.sort(key=lambda p: (float(own_nat.distance_to(p)), float(nat_anchor.distance_to(p))))
        except Exception:
            pass
        for pos in extras[:2]:
            points.append(pos)

        deduped: list[Point2] = []
        for pos in points:
            try:
                if any(float(pos.distance_to(existing)) <= 2.0 for existing in deduped):
                    continue
            except Exception:
                pass
            deduped.append(pos)
        return tuple(deduped)

    @classmethod
    def _default_defense_objective(cls, bot, *, base_pos: Point2) -> Point2:
        try:
            is_main = float(base_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False
        if is_main:
            return cls._main_ramp_anchor(bot)
        if cls._is_natural_base(bot, base_pos=base_pos):
            return cls._nat_choke_anchor(bot, base_pos=base_pos)
        try:
            enemy_main = bot.enemy_start_locations[0]
            return base_pos.towards(enemy_main, 5.0)
        except Exception:
            return base_pos

    @classmethod
    def _proactive_home_threats(
        cls,
        bot,
        *,
        rush_ctx: dict[str, float | str | bool],
        include_natural: bool = False,
    ) -> list[BaseThreatSnapshot]:
        if not bool(rush_ctx.get("active", False)):
            return []

        out: list[BaseThreatSnapshot] = []
        severity = float(rush_ctx.get("severity", 0.0) or 0.0)
        tier = str(rush_ctx.get("tier", "NONE") or "NONE")
        one_base_rush = bool(rush_ctx.get("enemy_one_base_rush", False))

        townhalls = list(getattr(bot, "townhalls", []) or [])
        if not townhalls:
            return []

        main_th = None
        nat_th = None
        try:
            ordered = sorted(townhalls, key=lambda th: float(th.distance_to(bot.start_location)))
            if ordered:
                main_th = ordered[0]
            if len(ordered) >= 2:
                nat_th = ordered[1]
        except Exception:
            main_th = townhalls[0]
            nat_th = townhalls[1] if len(townhalls) >= 2 else None

        synth_enemy = 2
        if bool(rush_ctx.get("heavy", False)):
            synth_enemy = 3
        if bool(rush_ctx.get("extreme", False)) or severity >= 0.82:
            synth_enemy = 4

        main_urgency = 9
        nat_urgency = 8
        if one_base_rush:
            main_urgency += 4
            nat_urgency += 6
        if tier in {"HEAVY", "EXTREME"}:
            main_urgency += 3
            nat_urgency += 3
        if severity >= 0.70:
            main_urgency += 2
            nat_urgency += 2

        if main_th is not None:
            out.append(
                BaseThreatSnapshot(
                    th_tag=int(getattr(main_th, "tag", -1) or -1),
                    th_pos=main_th.position,
                    enemy_count=int(synth_enemy),
                    enemy_power=float(synth_enemy),
                    urgency=int(max(1, min(20, main_urgency))),
                    threat_pos=cls._main_ramp_anchor(bot),
                )
            )

        if include_natural and nat_th is not None:
            out.append(
                BaseThreatSnapshot(
                    th_tag=int(getattr(nat_th, "tag", -1) or -1),
                    th_pos=nat_th.position,
                    enemy_count=int(synth_enemy),
                    enemy_power=float(synth_enemy),
                    urgency=int(max(1, min(20, nat_urgency))),
                    threat_pos=cls._nat_choke_anchor(bot, base_pos=nat_th.position),
                )
            )

        return out

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

        if self._is_outer_base(bot, base_pos=th.th_pos):
            raw += 4.0
            if int(th.enemy_count) > 0:
                raw += 2.5
            if float(defense_here) < max(3.0, float(th.enemy_count)):
                raw += 2.0
            if bool(rush_ctx.get("active", False)):
                raw -= 6.0
            if bool(rush_ctx.get("enemy_one_base_rush", False)):
                raw -= 4.0

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
                threat_pos=self._default_defense_objective(bot, base_pos=base_pos),
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
            start = bot.start_location
            if float(base_pos.distance_to(start)) <= 8.0:
                return "MAIN_RAMP"
        except Exception:
            pass
        try:
            ths = list(getattr(bot, "townhalls", []) or [])
            if not ths:
                return "BASE"
            ordered = sorted(ths, key=lambda th: float(th.distance_to(bot.start_location)))
            if ordered:
                if float(base_pos.distance_to(ordered[0].position)) <= 5.0:
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

    # Supply cost estimate per unit type (SC2 supply values)
    _SUPPLY_COST: ClassVar[dict] = {
        U.MARINE: 1, U.MARAUDER: 2, U.REAPER: 1,
        U.HELLION: 2, U.CYCLONE: 3,
        U.SIEGETANK: 3, U.SIEGETANKSIEGED: 3,
        U.THOR: 6, U.THORAP: 6,
        U.MEDIVAC: 2,
        U.WIDOWMINE: 2, U.WIDOWMINEBURROWED: 2,
        U.SCV: 1,
    }

    def _requirements(self, *, bot, th: BaseThreatSnapshot, objective: Point2, rush_ctx: dict[str, float | str | bool], max_detach_supply: int = 999, bulk_anchor_pos: Optional[Point2] = None, defense_overflow: bool = False) -> list[UnitRequirement]:
        urgency = int(th.urgency)
        enemy_count = int(th.enemy_count)
        outer_base = self._is_outer_base(bot, base_pos=th.th_pos)

        desired_tanks = 1 if urgency < 35 else (2 if urgency < 70 else 3)
        desired_general = 3 if urgency < 35 else (6 if urgency < 70 else 10)

        if outer_base:
            desired_general += 2 if enemy_count <= 4 else 4
            if enemy_count >= 3:
                desired_tanks = max(int(desired_tanks), 2)

        if bool(rush_ctx.get("heavy", False)):
            desired_tanks = max(int(desired_tanks), 2 if urgency < 70 else 3)
            desired_general += int(self.rush_heavy_bonus_general)

        if bool(rush_ctx.get("extreme", False)):
            desired_tanks = max(int(desired_tanks), 3)
            desired_general += int(self.rush_extreme_bonus_general)

        # Guardrail: não arrancar tank da defesa principal para third/fourth durante rush.
        if outer_base and bool(rush_ctx.get("active", False)):
            desired_tanks = 0
            desired_general = min(int(desired_general), 4)

        reqs: list[UnitRequirement] = []
        budget = int(max_detach_supply)  # Supply restante para destacamento

        tank_avail = self._available(bot, U.SIEGETANK)
        sieged_tank_avail = self._available(bot, U.SIEGETANKSIEGED)

        if int(desired_tanks) > 0:
            desired_tank_total = min(int(desired_tanks), int(tank_avail + sieged_tank_avail))
            take_unsieged = min(int(desired_tank_total), int(tank_avail))
            take_sieged = min(max(0, int(desired_tank_total) - int(take_unsieged)), int(sieged_tank_avail))

            # Cap pelo budget
            tank_cost = int(self._SUPPLY_COST.get(U.SIEGETANK, 3))
            take_unsieged = min(int(take_unsieged), max(0, int(budget) // int(tank_cost)))
            budget = max(0, int(budget) - int(take_unsieged) * int(tank_cost))

            if take_unsieged > 0:
                reqs.append(
                    UnitRequirement(
                        unit_type=U.SIEGETANK,
                        count=int(take_unsieged),
                        pick_policy=_DefendPickPolicy(objective=objective, unit_type=U.SIEGETANK, bulk_anchor_pos=bulk_anchor_pos, defense_overflow=defense_overflow),
                        required=True,
                    )
                )
            sieged_cost = int(self._SUPPLY_COST.get(U.SIEGETANKSIEGED, 3))
            take_sieged = min(int(take_sieged), max(0, int(budget) // int(sieged_cost)))
            budget = max(0, int(budget) - int(take_sieged) * int(sieged_cost))

            if take_sieged > 0 and not outer_base:
                reqs.append(
                    UnitRequirement(
                        unit_type=U.SIEGETANKSIEGED,
                        count=int(take_sieged),
                        pick_policy=_DefendPickPolicy(objective=objective, unit_type=U.SIEGETANKSIEGED, bulk_anchor_pos=bulk_anchor_pos, defense_overflow=defense_overflow),
                        required=len(reqs) == 0,
                    )
                )

        general_types = [U.CYCLONE, U.MARAUDER, U.MARINE, U.HELLION, U.THOR, U.THORAP]
        if outer_base:
            general_types = [U.MARINE, U.MARAUDER, U.CYCLONE, U.HELLION, U.THOR, U.THORAP]
        if bool(rush_ctx.get("heavy", False)):
            general_types = [U.MARINE, U.MARAUDER, U.CYCLONE, U.HELLION, U.THOR, U.THORAP]

        remaining = int(desired_general)
        for t in general_types:
            if remaining <= 0 or int(budget) <= 0:
                break
            avail = self._available(bot, t)
            if avail <= 0:
                continue
            unit_cost = int(self._SUPPLY_COST.get(t, 1))
            can_afford = max(0, int(budget) // int(unit_cost))
            take = min(int(avail), int(remaining), int(can_afford))
            if take <= 0:
                continue
            reqs.append(
                UnitRequirement(
                    unit_type=t,
                    count=int(take),
                    pick_policy=_DefendPickPolicy(objective=objective, unit_type=t, bulk_anchor_pos=bulk_anchor_pos, defense_overflow=defense_overflow),
                    required=len(reqs) == 0,
                )
            )
            remaining -= int(take)
            budget = max(0, int(budget) - int(take) * int(unit_cost))

        return reqs

    @staticmethod
    def _bunker_already_present(bot, *, anchor: Point2, radius: float = 14.0) -> bool:
        """Retorna True se já existe bunker (pronto ou em construção) perto do anchor."""
        try:
            for b in bot.structures(U.BUNKER):
                if float(b.distance_to(anchor)) <= radius:
                    return True
        except Exception:
            pass
        try:
            tracker = dict(bot.mediator.get_building_tracker_dict or {})
        except Exception:
            return False
        for entry in tracker.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("structure_type", None) != U.BUNKER:
                continue
            pos = entry.get("target", None) or entry.get("pos", None)
            if pos is None:
                continue
            try:
                if float(pos.distance_to(anchor)) <= radius:
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _should_request_bunker(
        *,
        bot,
        awareness: Awareness | None,
        now: float,
        th: BaseThreatSnapshot | None,
        rush_ctx: dict[str, float | str | bool],
    ) -> bool:
        """
        Lógica simples:
        - Main: bunker perto da rampa se rush confirmado/suspeito
        - Nat: bunker na nat se rush confirmado E nat está segura (sem contato imediato)
        Não pede se já tem bunker ou construção no local.
        """
        if th is None:
            return False
        # Mech builds don't use bunkers — tanks + PF are the defensive backbone.
        if bool(rush_ctx.get("is_mech_build", False)):
            return False
        state = str(rush_ctx.get("state", "NONE"))
        tier = str(rush_ctx.get("tier", "NONE"))
        if state not in {"SUSPECTED", "CONFIRMED", "HOLDING"}:
            return False

        try:
            is_main = float(th.th_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False

        if is_main:
            wall_status = {}
            if awareness is not None:
                try:
                    wall_status = awareness.mem.get(K("ops", "wall", "main", "status"), now=now, default={}) or {}
                except Exception:
                    wall_status = {}
            if not isinstance(wall_status, dict):
                wall_status = {}
            wall_complete = bool(wall_status.get("complete", False))
            depots_done = int(wall_status.get("depots_done", 0) or 0)
            depots_expected = int(wall_status.get("depots_expected", 0) or 0)
            three_by_three_done = int(wall_status.get("three_by_three_done", 0) or 0)
            emergency_wall = bool(wall_status.get("emergency_wall", False))
            enemy_near_wall = bool(wall_status.get("enemy_near", False))
            target_near_wall = bool(wall_status.get("target_near", False))
            wall_geometry_ready = bool(
                wall_complete
                or (
                    depots_expected > 0
                    and depots_done >= depots_expected
                    and three_by_three_done >= 1
                )
            )
            # Nao tenta bunker da rampa antes da wall da main existir minimamente.
            # Isso evita o primeiro bunker sair com geometria incompleta e ir parar longe da rampa.
            # Em rush HEAVY/EXTREME ou one-base-rush, relaxar para 1 depot (geometria já usável).
            main_wall_contact = bool(
                emergency_wall
                or enemy_near_wall
                or target_near_wall
                or DefensePlanner._enemy_contacting_main_wall(bot)
            )
            breach = DefensePlanner._main_breach_snapshot(
                bot,
                base_pos=th.th_pos,
                now=float(now),
                early_window_s=float(DefensePlanner.early_defense_window_s),
                breach_radius=float(DefensePlanner.main_breach_radius),
            )
            # Relaxa o requisito de wall em rush HEAVY/EXTREME com 1+ depot, ou quando
            # wall_status expirou (dict vazio) mas o rush ja esta confirmado.
            wall_geometry_relaxed = bool(
                (tier in {"HEAVY", "EXTREME"} and (depots_done >= 1 or three_by_three_done >= 1))
                or (not wall_status and state in {"CONFIRMED", "HOLDING"})
            )
            if not wall_geometry_ready and not wall_geometry_relaxed:
                return False
            # Bunker perto da rampa
            try:
                ramp = getattr(bot, "main_base_ramp", None)
                ramp_anchor = (
                    getattr(ramp, "top_center", None)
                    or getattr(ramp, "barracks_correct_placement", None)
                    or bot.start_location
                ) if ramp is not None else bot.start_location
            except Exception:
                ramp_anchor = th.th_pos
            return not DefensePlanner._bunker_already_present(bot, anchor=ramp_anchor, radius=14.0)
        else:
            # Bunker na nat: SUSPECTED com tier médio+ já justifica construção proativa.
            # Não espera CONFIRMED — o rush chega antes do bunker ficar pronto.
            if state not in {"SUSPECTED", "CONFIRMED", "HOLDING"}:
                return False
            if state == "SUSPECTED" and tier not in {"MEDIUM", "HEAVY", "EXTREME"}:
                return False
            if state in {"CONFIRMED", "HOLDING"} and tier not in {"MEDIUM", "HEAVY", "EXTREME"}:
                return False
            # Nat precisa estar tomada (tem nosso CC lá)
            nat_taken = False
            for townhall in list(getattr(bot, "townhalls", []) or []):
                try:
                    if float(townhall.distance_to(th.th_pos)) <= 8.0:
                        nat_taken = True
                        break
                except Exception:
                    continue
            if not nat_taken:
                return False
            # Não desce bunker na nat se tem inimigo em cima
            try:
                local_contact = int(bot.enemy_units.closer_than(12.0, th.th_pos).amount) >= 2
            except Exception:
                local_contact = False
            if local_contact:
                return False
            return not DefensePlanner._bunker_already_present(bot, anchor=th.th_pos, radius=14.0)

    @staticmethod
    def _enemy_contacting_main_wall(bot) -> bool:
        try:
            ramp = getattr(bot, "main_base_ramp", None)
            if ramp is None:
                return False
            probes = []
            top = getattr(ramp, "top_center", None)
            if top is not None:
                probes.append((top, 8.5))
            bottom = getattr(ramp, "bottom_center", None)
            if bottom is not None:
                probes.append((bottom, 6.5))
            for pos in list(getattr(ramp, "corner_depots", []) or []):
                probes.append((pos, 5.5))
            barracks_pos = getattr(ramp, "barracks_correct_placement", None)
            if barracks_pos is not None:
                probes.append((barracks_pos, 6.0))
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
            if tid in {
                U.OVERLORD, U.OVERSEER, U.OBSERVER, U.CHANGELING, U.CHANGELINGMARINESHIELD,
                U.CHANGELINGMARINE, U.CHANGELINGZEALOT, U.CHANGELINGZERGLING, U.CHANGELINGZERGLINGWINGS
            }:
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
            U.COMMANDCENTERFLYING,
            U.ORBITALCOMMAND,
            U.ORBITALCOMMANDFLYING,
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
        wall_tags = DefensePlanner._main_wall_target_tags(bot) if main_bias else set()
        total = 0
        for unit in list(getattr(bot, "structures", []) or []) + list(getattr(bot, "units", []) or []):
            try:
                if unit.type_id not in allowed:
                    continue
                tag = int(getattr(unit, "tag", -1) or -1)
                is_wall_target = tag in wall_tags
                if (not is_wall_target) and float(unit.distance_to(base_pos)) > 14.0:
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
        # Addons (reactor/techlab) ficam adjacentes à barracks — raio maior para cobrir
        addon_types = {U.BARRACKSREACTOR, U.BARRACKSTECHLAB}
        tags: set[int] = set()
        for unit in list(getattr(bot, "structures", []) or []):
            try:
                tid = getattr(unit, "type_id", None)
                if tid not in wall_types:
                    continue
                on_wall = any(float(unit.distance_to(pos)) <= 1.8 for pos in depot_positions)
                if not on_wall and barracks_pos is not None:
                    # Addons ficam colados na barracks lateralmente (~3.5 tiles do centro)
                    radius = 4.0 if tid in addon_types else 2.4
                    on_wall = float(unit.distance_to(barracks_pos)) <= radius
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
            U.COMMANDCENTERFLYING,
            U.ORBITALCOMMAND,
            U.ORBITALCOMMANDFLYING,
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
                is_wall_target = tag in wall_tags
                if (not is_wall_target) and float(unit.distance_to(base_pos)) > 16.0:
                    continue
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                build_progress = float(getattr(unit, "build_progress", 1.0) or 1.0)
                if hp_max <= 0.0 or build_progress < 1.0 or hp >= hp_max:
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
        if bool(main_wall_contact) and not bool(early_main_breach):
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
            U.COMMANDCENTERFLYING,
            U.ORBITALCOMMAND,
            U.ORBITALCOMMANDFLYING,
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
        try:
            main_bias = float(base_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            main_bias = False
        wall_tags = DefensePlanner._main_wall_target_tags(bot) if main_bias else set()
        for unit in list(getattr(bot, "structures", []) or []) + list(getattr(bot, "units", []) or []):
            try:
                if unit.type_id not in allowed:
                    continue
                tag = int(getattr(unit, "tag", -1) or -1)
                is_wall_target = tag in wall_tags
                if (not is_wall_target) and float(unit.distance_to(base_pos)) > 16.0:
                    continue
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                build_progress = float(getattr(unit, "build_progress", 1.0) or 1.0)
                if hp_max > 0.0 and (hp < hp_max or build_progress < 1.0):
                    total += 1
            except Exception:
                continue
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
                    if hp_max > 0.0 and build_progress >= 1.0 and hp < hp_max:
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
        # Para nat: mede inimigos também no choke (raio 20) — eles podem não estar em cima do CC
        choke_enemy_now = 0
        if not is_main:
            try:
                choke_enemy_now = int(bot.enemy_units.closer_than(20.0, th.th_pos).amount)
            except Exception:
                choke_enemy_now = int(close_enemy_now)
        # Durante one-base rush: não bloquear repair na nat se há bunker danificado perto.
        # Sem este check, o retorno antecipado impediria reparar o bunker da nat enquanto ele
        # estava sendo atacado — que é exatamente quando o repair é mais necessário.
        if bool(rush_ctx.get("enemy_one_base_rush", False)) and not bool(is_main):
            nat_bunker_damaged = False
            try:
                for b in bot.structures(U.BUNKER):
                    if float(b.distance_to(th.th_pos)) <= 18.0:
                        hp = float(getattr(b, "health", 0) or 0)
                        hp_max = float(getattr(b, "health_max", 1) or 1)
                        if hp < hp_max:
                            nat_bunker_damaged = True
                            break
            except Exception:
                pass
            if not nat_bunker_damaged:
                return 0
        main_wall_contact = bool(is_main and self._enemy_contacting_main_wall(bot))
        damaged_ready = int(self._damaged_owned_targets_near_base(bot, base_pos=th.th_pos))
        if bool(rush_ctx.get("enemy_one_base_rush", False)) and bool(is_main) and not bool(main_wall_contact) and int(damaged_ready) <= 0:
            if int(breach.get("inside_count", 0) or 0) <= 0:
                return 0
        local_pressure = bool(
            int(close_enemy_now) > 0
            or int(choke_enemy_now) > 0
            or bool(main_wall_contact)
            or int(th.enemy_count) > 0
            or int(breach.get("inside_count", 0) or 0) > 0
        )
        high_priority_damage = bool(repair_pressure >= 3.0 or int(damaged_ready) > 0)
        # Bunker danificado na nat sempre justifica repair, mesmo sem inimigo visível perto
        nat_bunker_damaged = False
        if not is_main:
            try:
                for b in bot.structures(U.BUNKER):
                    if float(b.distance_to(th.th_pos)) <= 18.0:
                        hp = float(getattr(b, "health", 0) or 0)
                        hp_max = float(getattr(b, "health_max", 1) or 1)
                        if hp < hp_max:
                            nat_bunker_damaged = True
                            break
            except Exception:
                pass
        if (not bool(local_pressure)) and not bool(high_priority_damage) and not bool(nat_bunker_damaged):
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

    def _repair_focus_pos(self, *, bot, th: BaseThreatSnapshot, rush_ctx: dict[str, float | str | bool]) -> Point2 | None:
        try:
            is_main = float(th.th_pos.distance_to(bot.start_location)) <= 10.0
        except Exception:
            is_main = False
        if not is_main:
            return None
        breach = self._main_breach_snapshot(
            bot,
            base_pos=th.th_pos,
            now=float(getattr(bot, "time", 0.0) or 0.0),
            early_window_s=float(self.early_defense_window_s),
            breach_radius=float(self.main_breach_radius),
        )
        main_wall_contact = bool(self._enemy_contacting_main_wall(bot))
        if bool(breach.get("early_window", False)) and (
            bool(rush_ctx.get("enemy_one_base_rush", False))
            or bool(rush_ctx.get("active", False))
            or bool(main_wall_contact)
        ):
            return self._main_ramp_anchor(bot)
        return None

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
                # Cap ao capacity do bunker da rampa se já existe bunker pronto —
                # marines excedentes ficam disponíveis para defender a nat.
                ramp_bunker_cap = None
                try:
                    ramp = getattr(bot, "main_base_ramp", None)
                    ramp_top = getattr(ramp, "top_center", None) if ramp is not None else None
                    if ramp_top is not None:
                        ramp_bunkers = [
                            b for b in bot.structures(U.BUNKER)
                            if float(b.distance_to(ramp_top)) <= 14.0 and bool(getattr(b, "is_ready", False))
                        ]
                        if ramp_bunkers:
                            ramp_bunker_cap = sum(
                                max(0, int(getattr(b, "cargo_max", 4) or 4) - int(getattr(b, "cargo_used", 0) or 0))
                                for b in ramp_bunkers
                            )
                            ramp_bunker_cap = max(2, int(ramp_bunker_cap))
                except Exception:
                    ramp_bunker_cap = None
                if ramp_bunker_cap is not None:
                    target_count = min(int(avail), ramp_bunker_cap)
                else:
                    target_count = min(int(avail), max(2, 6 + max(0, int(enemy_at_ramp) - 4)))
                pick_policy = _HoldRampMarinePickPolicy(objective=objective)
            elif unit_type == U.MEDIVAC:
                target_count = min(1, int(avail))
                pick_policy = _HoldRampCombatPickPolicy(objective=objective, unit_type=unit_type)
            elif unit_type in (U.REAPER, U.HELLION):
                # Reapers e hellions são valiosos para harass/scout — só pega 1 no máximo.
                # Deixa o resto disponível para outras missões.
                target_count = min(1, int(avail))
                pick_policy = _HoldRampCombatPickPolicy(objective=objective, unit_type=unit_type)
            else:
                target_count = min(int(avail), 3)
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
            scv_target = min(int(scv_count), int(self.scv_hold_ramp_max))
            reqs.append(
                UnitRequirement(
                    unit_type=U.SCV,
                    count=int(scv_target),
                    pick_policy=_ScvDefensePickPolicy(objective=objective),
                    required=len(reqs) == 0,
                )
            )
        return reqs

    def _merge_threats(
        self,
        *,
        bot,
        raw_threats: list[BaseThreatSnapshot],
        rush_ctx: dict[str, float | str | bool],
        include_proactive_natural: bool = False,
    ) -> list[BaseThreatSnapshot]:
        merged: dict[int, BaseThreatSnapshot] = {}

        for th in list(raw_threats or []):
            try:
                merged[int(th.th_tag)] = th
            except Exception:
                continue

        for th in self._proactive_home_threats(
            bot,
            rush_ctx=rush_ctx,
            include_natural=bool(include_proactive_natural),
        ):
            tag = int(getattr(th, "th_tag", -1) or -1)
            current = merged.get(tag)
            if current is None:
                merged[tag] = th
                continue
            try:
                current_prio = self._threat_priority(bot=bot, th=current, rush_ctx=rush_ctx)
            except Exception:
                current_prio = -9999.0
            try:
                new_prio = self._threat_priority(bot=bot, th=th, rush_ctx=rush_ctx)
            except Exception:
                new_prio = -9999.0
            if new_prio > current_prio:
                merged[tag] = th

        out = list(merged.values())
        out.sort(key=lambda th: self._threat_priority(bot=bot, th=th, rush_ctx=rush_ctx), reverse=True)
        return out

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        out: list[Proposal] = []
        rush_ctx = self._rush_ctx(awareness=awareness, now=now)

        # --- Lê geometria operacional (fonte primária) ---
        geo_snap = awareness.mem.get(K("intel", "geometry", "operational", "snapshot"), now=now, default=None)
        use_geometry = isinstance(geo_snap, dict) and bool(geo_snap)

        # Extrai bulk_anchor_pos para o guard de exclusão espacial do MASS_HOLD
        bulk_anchor_pos: Optional[Point2] = None
        if use_geometry:
            _bap = geo_snap.get("bulk_anchor_pos")
            if isinstance(_bap, dict):
                try:
                    bulk_anchor_pos = Point2((float(_bap["x"]), float(_bap["y"])))
                except Exception:
                    pass

        # --- Lê postura operacional para orçamento de destacamento ---
        posture_snap = awareness.mem.get(K("strategy", "army", "snapshot"), now=now, default={}) or {}
        if not isinstance(posture_snap, dict):
            posture_snap = {}
        posture_str = str(posture_snap.get("posture", ArmyPosture.HOLD_MAIN_RAMP.value) or ArmyPosture.HOLD_MAIN_RAMP.value)
        try:
            posture = ArmyPosture(posture_str)
        except ValueError:
            posture = ArmyPosture.HOLD_MAIN_RAMP

        # Orçamento de supply: fonte primária é a geometria, fallback é a postura
        if use_geometry:
            max_detach_supply = int(geo_snap.get("max_detach_supply", 8) or 8)
        else:
            max_detach_supply = int(posture_snap.get("max_detach_supply", 8) or 8)

        # Guard: quando a geometria tem NAT_CHOKE em MASS_HOLD, o bulk já está lá
        # DefensePlanner NÃO deve propor unidades que estejam no setor MASS_HOLD
        # (a menos que defense_overflow — situação de emergência)
        geometry_owns_nat = False
        if use_geometry:
            nat_choke_sector = (geo_snap.get("sector_states") or {}).get(SectorId.NAT_CHOKE.value, {})
            nat_choke_mode = str(nat_choke_sector.get("mode", SectorMode.NONE.value) or SectorMode.NONE.value)
            geometry_owns_nat = nat_choke_mode == SectorMode.MASS_HOLD.value
        if not geometry_owns_nat:
            geometry_owns_nat = posture in {
                ArmyPosture.HOLD_NAT_CHOKE,
                ArmyPosture.SECURE_NAT,
                ArmyPosture.CONTROLLED_RETAKE,
            }

        # --- Lê anchors do frontline_intel para objetivos mais honestos ---
        nat_snap = awareness.mem.get(K("intel", "frontline", "nat", "snapshot"), now=now, default={}) or {}
        if not isinstance(nat_snap, dict):
            nat_snap = {}
        territory_snap = awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
        if not isinstance(territory_snap, dict):
            territory_snap = {}
        territory_zones = territory_snap.get("zones", {}) if isinstance(territory_snap.get("zones", {}), dict) else {}
        _nat_forward_raw = nat_snap.get("forward_anchor")
        _nat_fallback_raw = nat_snap.get("fallback_anchor")
        nat_forward_anchor: Point2 | None = None
        nat_fallback_anchor: Point2 | None = None
        if isinstance(_nat_forward_raw, dict):
            try:
                nat_forward_anchor = Point2((float(_nat_forward_raw["x"]), float(_nat_forward_raw["y"])))
            except Exception:
                pass
        if isinstance(_nat_fallback_raw, dict):
            try:
                nat_fallback_anchor = Point2((float(_nat_fallback_raw["x"]), float(_nat_fallback_raw["y"])))
            except Exception:
                pass
        main_zone = territory_zones.get("main_ramp", {}) if isinstance(territory_zones.get("main_ramp", {}), dict) else {}
        nat_zone = territory_zones.get("natural_front", {}) if isinstance(territory_zones.get("natural_front", {}), dict) else {}
        territory_main_anchor = Point2((float(main_zone["front_anchor"]["x"]), float(main_zone["front_anchor"]["y"]))) if isinstance(main_zone.get("front_anchor"), dict) else None
        territory_main_fallback = Point2((float(main_zone["fallback_anchor"]["x"]), float(main_zone["fallback_anchor"]["y"]))) if isinstance(main_zone.get("fallback_anchor"), dict) else None
        territory_nat_anchor = Point2((float(nat_zone["front_anchor"]["x"]), float(nat_zone["front_anchor"]["y"]))) if isinstance(nat_zone.get("front_anchor"), dict) else None
        if territory_nat_anchor is not None:
            nat_forward_anchor = territory_nat_anchor
        if territory_main_fallback is not None:
            nat_fallback_anchor = territory_main_fallback

        # Bunker proativo na nat: independente do loop de threats.
        # Quando o rush é detectado (SUSPECTED+) e a nat tem CC mas ainda não tem bunker,
        # pede imediatamente — não espera o inimigo aparecer na porta.
        # Mech builds não usam bunker na nat — tanks e PF são a defesa primária.
        nat_bunker_proactive_pid = f"{self.planner_id}:nat_bunker_proactive"
        if (
            bool(rush_ctx.get("active", False))
            and not bool(rush_ctx.get("is_mech_build", False))
            and not awareness.ops_proposal_running(proposal_id=nat_bunker_proactive_pid, now=now)
            and self._due(awareness=awareness, now=now, pid=nat_bunker_proactive_pid)
        ):
            try:
                own_nat = bot.mediator.get_own_nat
                nat_has_cc = any(
                    float(th.distance_to(own_nat)) <= 8.0
                    for th in list(getattr(bot, "townhalls", []) or [])
                )
                # Só pede se a nat está tomada e não tem bunker lá ainda
                if nat_has_cc and not self._bunker_already_present(bot, anchor=own_nat, radius=14.0):
                    state_now = str(rush_ctx.get("state", "NONE"))
                    tier_now = str(rush_ctx.get("tier", "NONE"))
                    # SUSPECTED só com tier MEDIUM+; CONFIRMED/HOLDING sempre
                    tier_ok = tier_now in {"MEDIUM", "HEAVY", "EXTREME"}
                    state_ok = state_now in {"CONFIRMED", "HOLDING"} or (state_now == "SUSPECTED" and tier_ok)
                    # Não desce SCV se tem inimigo em cima da nat
                    nat_contact = int(bot.enemy_units.closer_than(12.0, own_nat).amount) >= 2
                    if state_ok and not nat_contact:
                        nat_anchor = self._nat_choke_anchor(bot, base_pos=own_nat)
                        nat_th_tag = -2  # tag sintético para a nat
                        for th in list(getattr(bot, "townhalls", []) or []):
                            try:
                                if float(th.distance_to(own_nat)) <= 8.0:
                                    nat_th_tag = int(getattr(th, "tag", -2) or -2)
                                    break
                            except Exception:
                                pass
                        bunker_factory = self._make_bunker_factory(
                            awareness=awareness,
                            base_tag=int(nat_th_tag),
                            base_pos=own_nat,
                            threat_pos=nat_anchor,
                            anchor_mode="NAT_CHOKE",
                        )
                        urgency_score = min(100, self._score_from_urgency(14 + (8 if bool(rush_ctx.get("heavy", False)) else 3)))
                        out.append(
                            Proposal(
                                proposal_id=nat_bunker_proactive_pid,
                                domain="DEFENSE",
                                score=urgency_score,
                                tasks=[
                                    TaskSpec(
                                        task_id="defense_bunker",
                                        task_factory=bunker_factory,
                                        unit_requirements=[
                                            UnitRequirement(
                                                unit_type=U.SCV,
                                                count=1,
                                                pick_policy=_ScvDefensePickPolicy(objective=own_nat),
                                                required=True,
                                            )
                                        ],
                                        lease_ttl=60.0,
                                    )
                                ],
                                lease_ttl=60.0,
                                cooldown_s=0.0,
                                risk_level=0,
                                allow_preempt=True,
                            )
                        )
                        self._mark_proposed(awareness=awareness, now=now, pid=nat_bunker_proactive_pid)
            except Exception:
                pass

        lift_pid = f"{self.planner_id}:lift_natural"
        if (
            self._should_lift_natural(bot, awareness=awareness, rush_ctx=rush_ctx, now=now)
            and not awareness.ops_proposal_running(proposal_id=lift_pid, now=now)
            and self._due(awareness=awareness, now=now, pid=lift_pid)
        ):
            try:
                own_nat = bot.mediator.get_own_nat
                anchor = bot.start_location
                lift_factory = self._make_lift_natural_factory(nat_pos=own_nat, anchor_pos=anchor)
                out.append(
                    Proposal(
                        proposal_id=lift_pid,
                        domain="DEFENSE",
                        score=95,
                        tasks=[
                            TaskSpec(
                                task_id="lift_natural",
                                task_factory=lift_factory,
                                unit_requirements=[],
                                lease_ttl=30.0,
                            )
                        ],
                        lease_ttl=30.0,
                        cooldown_s=15.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                )
                self._mark_proposed(awareness=awareness, now=now, pid=lift_pid)
            except Exception:
                pass

        # Reaper: patrulha a nat durante rush OU quando há presença inimiga na nat.
        # - Se a nat está segura (temos CC lá): roam no choke da nat, safe_point = topo da rampa
        # - Se a nat NÃO está segura (one-base-rush / nat perdida): roam na região da nat
        #   com safe_point = topo da rampa (atrás da parede)
        _nat_ctrl_snap = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
        if not isinstance(_nat_ctrl_snap, dict):
            _nat_ctrl_snap = {}
        _nat_enemy_power = float(_nat_ctrl_snap.get("enemy_nat_power", 0.0) or 0.0)
        _nat_presence_power = float(_nat_ctrl_snap.get("enemy_presence_nat_side_power", 0.0) or 0.0)
        _reaper_should_patrol = False
        try:
            own_nat = bot.mediator.get_own_nat
            nat_enemy_close = int(bot.enemy_units.closer_than(18.0, own_nat).amount)
            nat_regular_defenders = sum(
                1
                for u in bot.units
                if getattr(u, "type_id", None) in {
                    U.MARINE,
                    U.MARAUDER,
                    U.HELLION,
                    U.CYCLONE,
                    U.WIDOWMINE,
                    U.WIDOWMINEBURROWED,
                    U.SIEGETANK,
                    U.SIEGETANKSIEGED,
                    U.THOR,
                    U.THORAP,
                }
                and bool(getattr(u, "is_ready", False))
                and float(u.distance_to(own_nat)) <= 20.0
            )
            nat_under_threat = bool(
                nat_enemy_close >= 2
                or _nat_enemy_power >= 2.0
                or _nat_presence_power >= 2.0
            )
            _reaper_should_patrol = bool(nat_under_threat and nat_regular_defenders <= 2)
        except Exception:
            _reaper_should_patrol = False
        reaper_nat_pid = self._pid_reaper_nat_patrol()
        if (
            bool(_reaper_should_patrol)
            and int(self._available(bot, U.REAPER)) > 0
            and not awareness.ops_proposal_running(proposal_id=reaper_nat_pid, now=now)
            and self._due(awareness=awareness, now=now, pid=reaper_nat_pid)
        ):
            try:
                own_nat = bot.mediator.get_own_nat
                ramp_safe = self._main_ramp_anchor(bot)

                # Choke da nat: ponto entre nat e inimigo
                nat_anchor = self._nat_choke_anchor(bot, base_pos=own_nat)

                # Nat segura = temos CC na nat
                nat_has_cc = any(
                    float(th.distance_to(own_nat)) <= 8.0
                    for th in list(getattr(bot, "townhalls", []) or [])
                )

                if nat_has_cc:
                    # Roam no choke da nat, safe = topo da rampa
                    roam_center = nat_anchor
                    safe_point = ramp_safe
                    roam_radius = 7.0
                    engage_radius = 12.0
                else:
                    # Nat perdida / one-base-rush: roam na região da nat com safe atrás da wall
                    roam_center = Point2((float(own_nat.x), float(own_nat.y)))
                    safe_point = ramp_safe
                    roam_radius = 9.0
                    engage_radius = 14.0

                patrol_points = self._reaper_nat_patrol_points(
                    bot,
                    own_nat=own_nat,
                    nat_anchor=nat_anchor,
                    nat_has_cc=bool(nat_has_cc),
                )
                reaper_count = min(1, int(self._available(bot, U.REAPER)))
                reaper_patrol_factory = self._make_reaper_patrol_factory(
                    roam_center=roam_center,
                    safe_point=safe_point,
                    roam_radius=roam_radius,
                    engage_radius=engage_radius,
                    patrol_points=patrol_points,
                    task_id="reaper_nat_patrol",
                )
                out.append(
                    Proposal(
                        proposal_id=reaper_nat_pid,
                        domain="DEFENSE",
                        score=min(100, self._score_from_urgency(15 + (10 if bool(rush_ctx.get("heavy", False)) else 4))),
                        tasks=[
                            TaskSpec(
                                task_id="reaper_nat_patrol",
                                task_factory=reaper_patrol_factory,
                                unit_requirements=[
                                    UnitRequirement(
                                        unit_type=U.REAPER,
                                        count=reaper_count,
                                        pick_policy=_HoldRampCombatPickPolicy(objective=roam_center, unit_type=U.REAPER),
                                        required=True,
                                    )
                                ],
                                lease_ttl=20.0,
                            )
                        ],
                        lease_ttl=20.0,
                        cooldown_s=5.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                )
                self._mark_proposed(awareness=awareness, now=now, pid=reaper_nat_pid)
            except Exception:
                pass

        # Guardrail: se a geometria / MapControlPlanner já está segurando a nat,
        # DefensePlanner não aciona o fallback de existência para a nat.
        map_control_owns_nat = geometry_owns_nat

        threats_raw = [b for b in self._threats(attention) if int(b.urgency) >= int(self.min_base_urgency)]
        threats_raw = self._merge_threats(
            bot=bot,
            raw_threats=threats_raw,
            rush_ctx=rush_ctx,
            include_proactive_natural=False,
        )

        if threats_raw:
            threats = threats_raw[: max(1, int(self.max_bases_per_tick))]
        elif bool(self.existence_trigger_enabled) and (not bool(map_control_owns_nat)) and (
            int(self._defense_units_available(bot)) > 0
            or bool(rush_ctx.get("active", False))
            or any(float(self._repair_pressure_near_base(bot, base_pos=th.position)) > 0.0 for th in list(getattr(bot, "townhalls", []) or []))
        ):
            fallback = self._fallback_base_candidates(bot, rush_ctx=rush_ctx)
            fallback = self._merge_threats(
                bot=bot,
                raw_threats=fallback,
                rush_ctx=rush_ctx,
                include_proactive_natural=False,
            )
            threats = fallback[: max(1, int(self.max_bases_per_tick))]
        else:
            threats = []

        for th in threats:
            pid = self._pid_base(int(th.th_tag))
            if awareness.ops_proposal_running(proposal_id=pid, now=now):
                continue
            if not self._due(awareness=awareness, now=now, pid=pid):
                continue

            # Substituir objetivo heurístico pelo anchor do frontline_intel quando disponível
            is_main_base = False
            is_nat_base = self._is_natural_base(bot, base_pos=th.th_pos)
            try:
                is_main_base = float(th.th_pos.distance_to(bot.start_location)) <= 10.0
            except Exception:
                is_main_base = False

            if is_nat_base and nat_forward_anchor is not None:
                # Usar o choke anchor da nat derivado pelo frontline_intel
                improved_th = BaseThreatSnapshot(
                    th_tag=th.th_tag,
                    th_pos=th.th_pos,
                    enemy_count=th.enemy_count,
                    enemy_power=th.enemy_power,
                    urgency=th.urgency,
                    threat_pos=nat_forward_anchor,
                )
                th = improved_th
            elif is_main_base and nat_fallback_anchor is not None:
                # Main ameaçada → fallback anchor entre nat e main (topo da rampa)
                improved_th = BaseThreatSnapshot(
                    th_tag=th.th_tag,
                    th_pos=th.th_pos,
                    enemy_count=th.enemy_count,
                    enemy_power=th.enemy_power,
                    urgency=th.urgency,
                    threat_pos=nat_fallback_anchor,
                )
                th = improved_th
            elif is_main_base and territory_main_anchor is not None:
                improved_th = BaseThreatSnapshot(
                    th_tag=th.th_tag,
                    th_pos=th.th_pos,
                    enemy_count=th.enemy_count,
                    enemy_power=th.enemy_power,
                    urgency=th.urgency,
                    threat_pos=territory_main_anchor,
                )
                th = improved_th

            objective = self._objective(th)

            effective_urgency = int(th.urgency)
            if bool(rush_ctx.get("heavy", False)):
                effective_urgency += 10
            elif bool(rush_ctx.get("active", False)):
                effective_urgency += 4

            bunker_pid = self._pid_bunker(int(th.th_tag))
            if (
                self._should_request_bunker(bot=bot, awareness=awareness, now=now, th=th, rush_ctx=rush_ctx)
                and not awareness.ops_proposal_running(proposal_id=bunker_pid, now=now)
                and self._due(awareness=awareness, now=now, pid=bunker_pid)
            ):
                # is_main_base já calculado acima; forçar MAIN_RAMP para a main
                # evita que _base_anchor_mode caia no fallback errado quando o CC
                # fica longe do start_location (threshold 8.0 pode ser pequeno).
                bunker_anchor_mode = "MAIN_RAMP" if is_main_base else self._base_anchor_mode(bot, base_pos=th.th_pos)
                bunker_factory = self._make_bunker_factory(
                    awareness=awareness,
                    base_tag=int(th.th_tag),
                    base_pos=th.th_pos,
                    threat_pos=objective,
                    anchor_mode=bunker_anchor_mode,
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
                                lease_ttl=45.0,
                            )
                        ],
                        lease_ttl=45.0,
                        cooldown_s=0.0,
                        risk_level=0,
                        allow_preempt=True,
                    )
                )
                self._mark_proposed(awareness=awareness, now=now, pid=bunker_pid)

            # Budget: sempre respeita max_detach_supply da geometria.
            # Exceção: defense_overflow=True permite usar supply além do budget normal.
            # Isso garante que o DefensePlanner NUNCA sequestra o bulk do MASS_HOLD
            # exceto em situação de emergência explicitamente sinalizada.
            defense_overflow = bool(
                awareness.mem.get(K("strategy", "army", "defense_overflow"), now=now, default=False)
            )

            # Antecipa defense_overflow quando a nat está sendo pressionada com defesa fraca
            # e existe exército na main disponível para descer. Não espera urgency >= 75.
            if not defense_overflow and is_nat_base:
                try:
                    nat_enemy_near = int(bot.enemy_units.closer_than(20.0, th.th_pos).amount)
                    nat_defense_score = self._own_defense_score_near_base(bot, base_pos=th.th_pos)
                    _NAT_OVERFLOW_ENEMY_MIN = 2
                    _NAT_OVERFLOW_DEFENSE_MAX = 5.0
                    _NAT_OVERFLOW_MAIN_SUPPLY_MIN = 4
                    if nat_enemy_near >= _NAT_OVERFLOW_ENEMY_MIN and nat_defense_score < _NAT_OVERFLOW_DEFENSE_MAX:
                        _combat_types_ovf = {U.MARINE, U.MARAUDER, U.CYCLONE, U.HELLION, U.THOR, U.THORAP, U.SIEGETANK, U.SIEGETANKSIEGED}
                        _supply_cost_ovf = {U.MARINE: 1, U.MARAUDER: 2, U.CYCLONE: 3, U.HELLION: 2, U.THOR: 6, U.THORAP: 6, U.SIEGETANK: 3, U.SIEGETANKSIEGED: 3}
                        main_supply = sum(
                            int(_supply_cost_ovf.get(u.type_id, 1))
                            for u in bot.units
                            if getattr(u, "type_id", None) in _combat_types_ovf
                            and bool(getattr(u, "is_ready", False))
                            and float(u.distance_to(bot.start_location)) <= 30.0
                        )
                        if main_supply >= _NAT_OVERFLOW_MAIN_SUPPLY_MIN:
                            defense_overflow = True
                            awareness.mem.set(K("strategy", "army", "defense_overflow"), value=True, now=now, ttl=10.0)
                except Exception:
                    pass

            effective_budget = int(max_detach_supply) if not defense_overflow else int(max_detach_supply) * 2
            # Cap absoluto: nunca mais que army_supply disponível (evita solicitar inexistente)
            army_supply = int(getattr(bot, "supply_army", 0) or 0)
            effective_budget = min(int(effective_budget), int(army_supply))
            reqs = self._requirements(bot=bot, th=th, objective=objective, rush_ctx=rush_ctx, max_detach_supply=int(effective_budget), bulk_anchor_pos=bulk_anchor_pos, defense_overflow=bool(defense_overflow))
            base_pos = th.th_pos

            # Sinaliza defense_overflow se a ameaça é grave e o budget normal não basta
            # Isso permite que o army_posture_intel propague a emergência no próximo tick
            if not defense_overflow and int(th.urgency) >= 75 and int(max_detach_supply) < 6:
                awareness.mem.set(K("strategy", "army", "defense_overflow"), value=True, now=now, ttl=8.0)

            if reqs:
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
                        score=self._score_from_urgency(
                            int(effective_urgency) + (6 if self._is_outer_base(bot, base_pos=base_pos) else 0)
                        ),
                        tasks=[
                            TaskSpec(
                                task_id="defend_base",
                                task_factory=factory,
                                unit_requirements=reqs,
                                lease_ttl=None,
                            )
                        ],
                        lease_ttl=None,
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
                repair_count = min(self.scv_hold_ramp_max, self._repair_count(bot=bot, th=th, rush_ctx=rush_ctx))
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
                                    lease_ttl=18.0,
                                )
                            ],
                            lease_ttl=18.0,
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
                and (
                    not bool(main_wall_contact)
                    or (
                        bool(is_main_base)
                        and bool(
                            self._main_breach_snapshot(
                                bot,
                                base_pos=th.th_pos,
                                now=now,
                                early_window_s=float(self.early_defense_window_s),
                                breach_radius=float(self.main_breach_radius),
                            ).get("inside_count", 0) or 0
                        ) > 0
                    )
                )
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
                                lease_ttl=18.0,
                            )
                        ],
                        lease_ttl=18.0,
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
                repair_focus_pos = self._repair_focus_pos(bot=bot, th=th, rush_ctx=rush_ctx)
                repair_factory = self._make_repair_factory(
                    base_tag=int(th.th_tag),
                    base_pos=th.th_pos,
                    threat_pos=objective,
                    repair_focus_pos=repair_focus_pos,
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

        if self.log is not None and out:
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

        # Salvage empty bunkers when the rush is over.
        # One Proposal per bunker tag so each can be tracked/preempted independently.
        rush_ended = not bool(rush_ctx.get("active", False)) and str(rush_ctx.get("state", "NONE")) in {"NONE", "ENDED"}
        if rush_ended:
            try:
                from bot.tasks.defense.salvage_bunker_task import SalvageBunkerTask
                for bunker in list(bot.structures(U.BUNKER).ready or []):
                    try:
                        garrison = int(getattr(bunker, "cargo_used", 0) or 0)
                        if garrison > 0:
                            continue
                        enemies_near = int(bot.enemy_units.closer_than(16.0, bunker.position).amount)
                        if enemies_near > 0:
                            continue
                        salvage_pid = f"{self.planner_id}:salvage_bunker:{int(bunker.tag)}"
                        if awareness.ops_proposal_running(proposal_id=salvage_pid, now=now):
                            continue
                        bunker_tag = int(bunker.tag)
                        bunker_pos = bunker.position

                        def _make_salvage(tag=bunker_tag, pos=bunker_pos):
                            def _factory(mission_id: str) -> SalvageBunkerTask:
                                return SalvageBunkerTask(bunker_tag=tag, bunker_pos=pos)
                            return _factory

                        out.append(
                            Proposal(
                                proposal_id=salvage_pid,
                                domain="DEFENSE",
                                score=12,
                                tasks=[
                                    TaskSpec(
                                        task_id="salvage_bunker",
                                        task_factory=_make_salvage(),
                                        unit_requirements=[],
                                        lease_ttl=15.0,
                                    )
                                ],
                                lease_ttl=15.0,
                                cooldown_s=0.0,
                                risk_level=0,
                                allow_preempt=True,
                            )
                        )
                    except Exception:
                        continue
            except Exception:
                pass

        return out
