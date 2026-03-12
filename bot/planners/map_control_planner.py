"""
Map Control Planner — dono da posição do bulk do exército.

Responsabilidade:
    - Ler a geometria operacional (OperationalGeometryController)
    - Propor tasks coerentes com os setores ativos:
        * HoldAnchorTask → setor MASS_HOLD (bulk principal)
        * SecureBaseTask → setores ANCHOR/HEAVY_ANCHOR/SCREEN secundários
        * DefenseBunkerTask → quando postura pede defesa no choke
        * MoveOutTask → quando template=PREP_PUSH e condições late-game (supply+banco)
    - NÃO disputar posse do bulk com DefensePlanner
    - NÃO reagir à base atacada diretamente — isso é responsabilidade da geometria

    Late-game push (multi-frente):
        MoveOutTask (bulk central, leapfrog de tanks) no domínio MAP_CONTROL score=97.
        BansheeHarass ou MedivacDropHarassTask em bases laterais, propostos em paralelo
        no domínio HARASS — não competem com o bulk.

Fonte primária: K("intel", "geometry", "operational", "snapshot")
Fallback: postura legada (K("strategy", "army", "snapshot"))
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.intel.geometry.sector_types import FrontTemplate, SectorId, SectorMode
from bot.intel.strategy.i3_army_posture_intel import ArmyPosture
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.defense.defense_bunker_task import DefenseBunkerTask
from bot.tasks.map_control.hold_anchor_task import HoldAnchorTask
from bot.tasks.map_control.land_base_task import LandBaseTask
from bot.tasks.map_control.move_out_task import MoveOutTask
from bot.tasks.map_control.secure_base_task import SecureBaseTask
from bot.tasks.harass.banshee_harass_task import BansheeHarass
from bot.tasks.harass.medivac_drop_harass_task import MedivacDropHarassTask


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
            if bool(getattr(unit, "is_carrying_resource", False)):
                return False
        except Exception:
            pass
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


_BULK_UNIT_TYPES = [
    U.MARINE, U.MARAUDER,
    # REAPER excluído: reapers são unidades de harass/scout independentes.
    # Quando não estão em missão de harass, ficam livres para se mover pelo mapa.
    # Inclui-los no bulk faz o reaper ficar parado no anchor esperando.
    U.WIDOWMINE, U.WIDOWMINEBURROWED,
    U.HELLION, U.CYCLONE,
    U.SIEGETANK, U.SIEGETANKSIEGED,
    U.THOR, U.THORAP,
    U.MEDIVAC,
]

@dataclass(frozen=True)
class _BulkPickPolicy:
    anchor: Point2
    unit_type: U
    name: str = "map_control.bulk.anchor.v1"

    def allow(self, unit, *, bot, attention, now: float) -> bool:
        if unit is None or unit.type_id != self.unit_type:
            return False
        return bool(getattr(unit, "is_ready", False))

    def score(self, unit, *, bot, attention, now: float) -> float:
        try:
            dist = float(unit.distance_to(self.anchor))
        except Exception:
            dist = 9999.0
        return -dist  # Prefer closest to anchor


@dataclass
class MapControlPlanner:
    planner_id: str = "map_control_planner"
    log: DevLogger | None = None
    cadence_s: float = 2.0
    lease_ttl_s: Optional[float] = None

    @staticmethod
    def _point_payload(pos: Point2 | None) -> dict | None:
        if pos is None:
            return None
        return {"x": float(pos.x), "y": float(pos.y)}

    def _pid(self, label: str) -> str:
        return f"{self.planner_id}:{str(label)}"

    def _make_bunker_factory(self, *, awareness: Awareness, base_pos: Point2, hold_pos: Point2):
        def _factory(mission_id: str) -> DefenseBunkerTask:
            return DefenseBunkerTask(
                awareness=awareness,
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
    def _base_is_established(entry: dict) -> bool:
        state = str(entry.get("state", "") or "").upper()
        return state in {"ESTABLISHED", "LANDED_UNSAFE", "SECURING"}

    @staticmethod
    def _base_point(entry: dict) -> Point2 | None:
        payload = entry.get("current_pos") or entry.get("intended_pos")
        if not isinstance(payload, dict):
            return None
        try:
            return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
        except Exception:
            return None

    def _standard_bulk_anchor(
        self,
        *,
        bot,
        awareness: Awareness,
        attention: Attention,
        now: float,
        fallback_anchor: Point2 | None,
    ) -> tuple[Point2 | None, dict]:
        registry = awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
        if not isinstance(registry, dict):
            registry = {}

        nat_entry = dict(registry.get("NATURAL", {})) if isinstance(registry.get("NATURAL", {}), dict) else {}
        nat_pos = self._base_point(nat_entry)
        rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        primary_urgency = int(getattr(attention.combat, "primary_urgency", 0) or 0)
        primary_enemy_count = int(getattr(attention.combat, "primary_enemy_count", 0) or 0)

        result = {
            "mode": "geometry_bulk",
            "reason": "fallback",
            "reinforce_base_label": "",
            "reinforce_base_pos": None,
            "controlled_unit_types": [str(t.name) for t in _BULK_UNIT_TYPES],
            "split_ready": False,
        }
        if nat_pos is None:
            return fallback_anchor, result
        if rush_state in {"CONFIRMED", "HOLDING"} or primary_urgency >= 16 or primary_enemy_count >= 2:
            result["reason"] = "home_pressure_or_rush"
            return fallback_anchor or nat_pos, result

        enemy_main = bot.enemy_start_locations[0] if getattr(bot, "enemy_start_locations", None) else bot.start_location
        owned_outer: list[tuple[int, float, str, Point2]] = []
        for label, raw_entry in registry.items():
            if str(label) in {"MAIN", "NATURAL"}:
                continue
            if not isinstance(raw_entry, dict):
                continue
            entry = dict(raw_entry)
            if not bool(entry.get("owned", False)):
                continue
            if not self._base_is_established(entry):
                continue
            base_pos = self._base_point(entry)
            if base_pos is None:
                continue
            order = int(entry.get("order", 99) or 99)
            try:
                enemy_dist = float(base_pos.distance_to(enemy_main))
            except Exception:
                enemy_dist = 9999.0
            owned_outer.append((order, enemy_dist, str(label), base_pos))

        if not owned_outer:
            result["reason"] = "no_established_outer_base"
            return fallback_anchor or nat_pos, result

        owned_outer.sort(key=lambda item: (-int(item[0]), float(item[1])))
        _order, _enemy_dist, reinforce_label, reinforce_pos = owned_outer[0]
        try:
            anchor = nat_pos.towards(reinforce_pos, nat_pos.distance_to(reinforce_pos) * 0.58)
        except Exception:
            anchor = fallback_anchor or nat_pos
        result["mode"] = "standard_bulk"
        result["reason"] = "stabilized_outer_base_reinforce"
        result["reinforce_base_label"] = str(reinforce_label)
        result["reinforce_base_pos"] = self._point_payload(reinforce_pos)
        return anchor, result

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

    def _should_request_nat_bunker(
        self,
        *,
        bot,
        attention: Attention,
        posture: ArmyPosture,
        snapshot: dict,
        base_pos: Point2,
        hold_pos: Point2,
    ) -> bool:
        """
        Decide se deve construir bunker no choke da nat.
        Baseado na postura, não em should_secure.
        """
        if self._nat_bunker_started_or_pending(bot, base_pos=base_pos, hold_pos=hold_pos):
            return False

        # Bunker faz sentido quando vamos segurar o choke da nat
        posture_wants_bunker = posture in {
            ArmyPosture.HOLD_NAT_CHOKE,
            ArmyPosture.SECURE_NAT,
            ArmyPosture.CONTROLLED_RETAKE,
        }
        # rush_active só justifica bunker na nat se a postura já NÃO for HOLD_MAIN_RAMP.
        # Durante HOLD_MAIN_RAMP o exército precisa estar na rampa, não puxado para a nat.
        rush_state = str(snapshot.get("rush_state", "NONE") or "NONE").upper()
        rush_active = rush_state in {"CONFIRMED", "HOLDING"} and posture != ArmyPosture.HOLD_MAIN_RAMP
        delayed_natural_alarm = bool(snapshot.get("delayed_natural_alarm", False))

        if not (posture_wants_bunker or rush_active or delayed_natural_alarm):
            return False

        own_total_power = float(snapshot.get("own_total_power", 0.0) or 0.0)
        enemy_nat_power = float(snapshot.get("enemy_nat_power", 0.0) or 0.0)

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

    def _requirements(
        self,
        *,
        bot,
        attention: Attention,
        hold_pos: Point2,
        snapshot: dict,
        posture_snap: dict,
    ) -> list[UnitRequirement]:
        """
        Calcula requerimentos de unidades para SecureBaseTask.
        Respeita max_detach_supply da postura — o bulk não pode ser sequestrado.
        """
        enemy_nat_power = float(snapshot.get("enemy_nat_power", 0.0) or 0.0)
        own_total_power = float(snapshot.get("own_total_power", 0.0) or 0.0)
        rush_state = str(snapshot.get("rush_state", "NONE") or "NONE").upper()
        delayed_natural_alarm = bool(snapshot.get("delayed_natural_alarm", False))
        own_nat_bunker_count = int(snapshot.get("own_nat_bunker_count", 0) or 0)
        bases_now = int(getattr(attention.macro, "bases_total", 0) or 0)

        # Orçamento de destacamento da postura operacional
        max_detach = int(posture_snap.get("max_detach_supply", 8) or 8)
        # Garantir que o bulk não seja esvaziado — budget total é o max_detach
        budget_remaining = int(max_detach)

        desired_general = 4
        if own_total_power >= 8.0:
            desired_general = 5
        if enemy_nat_power >= 1.0 or rush_state in {"CONFIRMED", "HOLDING"}:
            desired_general += 2
        if delayed_natural_alarm and bases_now < 2:
            desired_general += 2
        if own_nat_bunker_count > 0:
            desired_general = max(int(desired_general), 6)

        # Cap pelo orçamento de destacamento
        desired_general = min(int(desired_general), int(budget_remaining))

        reqs: list[UnitRequirement] = []

        tank_avail = self._available(bot, U.SIEGETANK)
        sieged_tank_avail = self._available(bot, U.SIEGETANKSIEGED)
        desired_tanks = (1 if enemy_nat_power < 1.5 else 2) + (1 if delayed_natural_alarm and (tank_avail + sieged_tank_avail) >= 2 else 0)
        total_tanks = min(int(desired_tanks), int(tank_avail + sieged_tank_avail))
        take_unsieged = min(int(total_tanks), int(tank_avail))
        take_sieged = min(max(0, int(total_tanks) - int(take_unsieged)), int(sieged_tank_avail))

        # Tanks contam contra o budget (supply real por unidade seria melhor, aqui 2 por tank)
        tank_supply_cost = (int(take_unsieged) + int(take_sieged)) * 2
        if int(tank_supply_cost) > int(budget_remaining):
            take_unsieged = min(int(take_unsieged), int(budget_remaining) // 2)
            take_sieged = 0
            tank_supply_cost = int(take_unsieged) * 2
        budget_remaining -= int(tank_supply_cost)

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

        desired_mines = 0
        if own_nat_bunker_count > 0 or enemy_nat_power >= 0.45:
            desired_mines = 1
        if delayed_natural_alarm or rush_state in {"CONFIRMED", "HOLDING"} or enemy_nat_power >= 1.1:
            desired_mines = 2
        remaining_mines = int(desired_mines)
        for mine_type in (U.WIDOWMINE, U.WIDOWMINEBURROWED):
            if remaining_mines <= 0 or budget_remaining < int(self._SUPPLY_COST.get(mine_type, 2)):
                break
            avail = self._available(bot, mine_type)
            if avail <= 0:
                continue
            unit_cost = int(self._SUPPLY_COST.get(mine_type, 2))
            can_afford = max(0, int(budget_remaining) // int(unit_cost))
            take = min(int(avail), int(remaining_mines), int(can_afford))
            if take <= 0:
                continue
            reqs.append(
                UnitRequirement(
                    unit_type=mine_type,
                    count=int(take),
                    pick_policy=_SecureBasePickPolicy(objective=hold_pos, unit_type=mine_type),
                    required=len(reqs) == 0,
                )
            )
            remaining_mines -= int(take)
            budget_remaining = max(0, int(budget_remaining) - int(take) * int(unit_cost))

        remaining = min(int(desired_general), int(budget_remaining))
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
        if medivac_avail > 0 and own_total_power >= 7.0 and budget_remaining >= 1:
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
            support_scvs = 1 if enemy_nat_power <= 1.2 else 2
        elif delayed_natural_alarm and bases_now < 2 and own_total_power >= 5.0:
            support_scvs = 1 if enemy_nat_power <= 1.6 else 2
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

    @staticmethod
    def _requirement_counts(reqs: list[UnitRequirement]) -> dict[U, int]:
        counts: dict[U, int] = {}
        for req in list(reqs or []):
            try:
                unit_type = req.unit_type
                counts[unit_type] = int(counts.get(unit_type, 0)) + int(req.count)
            except Exception:
                continue
        return counts

    def _bulk_requirements(self, *, bot, anchor: Point2, reserve_counts: Optional[dict[U, int]] = None, tank_cap: Optional[int] = None) -> list[UnitRequirement]:
        """Constrói requerimentos para o bulk preservando reservas locais de defesa."""
        reqs: list[UnitRequirement] = []
        reserve_counts = dict(reserve_counts or {})
        tank_types = {U.SIEGETANK, U.SIEGETANKSIEGED}
        remaining_tank_cap = None if tank_cap is None else max(0, int(tank_cap))
        for unit_type in _BULK_UNIT_TYPES:
            try:
                avail = int(bot.units.of_type(unit_type).ready.amount)
            except Exception:
                avail = 0
            avail = max(0, int(avail) - int(reserve_counts.get(unit_type, 0) or 0))
            if unit_type in tank_types and remaining_tank_cap is not None:
                avail = min(int(avail), int(remaining_tank_cap))
            if avail <= 0:
                continue
            reqs.append(
                UnitRequirement(
                    unit_type=unit_type,
                    count=avail,
                    pick_policy=_BulkPickPolicy(anchor=anchor, unit_type=unit_type, name=f"map_control.bulk.anchor.{unit_type.name}.v1"),
                    required=False,
                )
            )
            if unit_type in tank_types and remaining_tank_cap is not None:
                remaining_tank_cap = max(0, int(remaining_tank_cap) - int(avail))
        return reqs

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)

        # --- Lê geometria operacional (fonte primária) ---
        geo_snap = awareness.mem.get(K("intel", "geometry", "operational", "snapshot"), now=now, default=None)
        use_geometry = isinstance(geo_snap, dict) and bool(geo_snap)

        # --- Lê postura legada (fallback e compatibilidade) ---
        posture_snap = awareness.mem.get(K("strategy", "army", "snapshot"), now=now, default={}) or {}
        if not isinstance(posture_snap, dict):
            posture_snap = {}
        posture_str = str(posture_snap.get("posture", ArmyPosture.HOLD_MAIN_RAMP.value) or ArmyPosture.HOLD_MAIN_RAMP.value)
        try:
            posture = ArmyPosture(posture_str)
        except ValueError:
            posture = ArmyPosture.HOLD_MAIN_RAMP

        # --- Lê snapshot da nat (fatos estruturais) ---
        snapshot = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
        if not isinstance(snapshot, dict):
            return []
        territory_snap = awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
        territory_zones = territory_snap.get("zones", {}) if isinstance(territory_snap, dict) else {}
        nat_zone = territory_zones.get("natural_front", {}) if isinstance(territory_zones, dict) else {}

        out: list[Proposal] = []
        secure_plan: dict[str, object] | None = None

        posture_wants_garrison = False
        if use_geometry:
            nat_choke_sector = (geo_snap.get("sector_states") or {}).get(SectorId.NAT_CHOKE.value, {})
            nat_choke_mode = str(nat_choke_sector.get("mode", SectorMode.NONE.value) or SectorMode.NONE.value)
            nat_choke_target = float(nat_choke_sector.get("target_power", 0.0) or 0.0)
            posture_wants_garrison = nat_choke_mode in {
                SectorMode.ANCHOR.value,
                SectorMode.HEAVY_ANCHOR.value,
            } and nat_choke_target > 0.0
        else:
            posture_wants_garrison = posture in {
                ArmyPosture.HOLD_NAT_CHOKE,
                ArmyPosture.SECURE_NAT,
                ArmyPosture.CONTROLLED_RETAKE,
            }

        if posture_wants_garrison:
            secure_pid = self._pid("secure_our_nat")
            if not awareness.ops_proposal_running(proposal_id=secure_pid, now=now) and self._due(awareness=awareness, now=now, pid=secure_pid):
                base_pos2 = self._point(snapshot.get("target"))
                staging_pos = self._point(snapshot.get("staging"), fallback=base_pos2)
                hold_pos = self._point(snapshot.get("hold"), fallback=base_pos2)
                rush_state = str(snapshot.get("rush_state", "NONE")).upper()
                delayed_natural_alarm = bool(snapshot.get("delayed_natural_alarm", False))
                enemy_nat_power = float(snapshot.get("enemy_nat_power", 0.0) or 0.0)
                own_nat_bunker_count = int(snapshot.get("own_nat_bunker_count", 0) or 0)
                nat_take_in_progress = bool(snapshot.get("nat_offsite", False) or snapshot.get("safe_to_land", False))
                secure_needed = bool(
                    delayed_natural_alarm
                    or rush_state in {"CONFIRMED", "HOLDING"}
                    or enemy_nat_power >= 0.6
                    or own_nat_bunker_count > 0
                    or nat_take_in_progress
                    or posture in {ArmyPosture.SECURE_NAT, ArmyPosture.CONTROLLED_RETAKE}
                )
                if secure_needed:
                    if isinstance(nat_zone.get("fallback_anchor"), dict):
                        staging_pos = self._point(nat_zone.get("fallback_anchor"), fallback=staging_pos)
                    if isinstance(nat_zone.get("front_anchor"), dict):
                        hold_pos = self._point(nat_zone.get("front_anchor"), fallback=hold_pos)
                    if base_pos2 is not None and staging_pos is not None and hold_pos is not None:
                        reqs = self._requirements(
                            bot=bot,
                            attention=attention,
                            hold_pos=hold_pos,
                            snapshot=snapshot,
                            posture_snap=posture_snap,
                        )
                        if reqs:
                            if use_geometry:
                                template_str = str(geo_snap.get("template", "") or "")
                                if delayed_natural_alarm or rush_state in {"CONFIRMED", "HOLDING"}:
                                    score = 88
                                elif template_str == FrontTemplate.TURTLE_NAT.value:
                                    score = 88
                                elif template_str in {FrontTemplate.STABILIZE_AND_EXPAND.value, FrontTemplate.CONTAIN.value} and enemy_nat_power >= 0.6:
                                    score = 85
                                else:
                                    score = 74
                            elif posture == ArmyPosture.HOLD_NAT_CHOKE and rush_state in {"CONFIRMED", "HOLDING"}:
                                score = 88
                            elif posture in {ArmyPosture.HOLD_NAT_CHOKE, ArmyPosture.SECURE_NAT} and (enemy_nat_power >= 0.6 or nat_take_in_progress):
                                score = 85
                            else:
                                score = 74

                            if (
                                delayed_natural_alarm
                                or rush_state in {"CONFIRMED", "HOLDING"}
                                or enemy_nat_power >= 0.6
                                or own_nat_bunker_count > 0
                                or nat_take_in_progress
                            ):
                                score = max(int(score), 95)

                            secure_plan = {
                                "proposal_id": secure_pid,
                                "base_pos": base_pos2,
                                "staging_pos": staging_pos,
                                "hold_pos": hold_pos,
                                "reqs": reqs,
                                "score": int(score),
                                "rush_state": str(rush_state),
                            }

        # --- Determina anchor do bulk ---
        # Fonte primária: setor MASS_HOLD da geometria
        # Fallback: anchor da postura legada
        anchor_point: Optional[Point2] = None

        if use_geometry:
            bulk_anchor_payload = geo_snap.get("bulk_anchor_pos")
            if isinstance(bulk_anchor_payload, dict):
                anchor_point = self._point(bulk_anchor_payload)

        if anchor_point is None:
            anchor_payload = posture_snap.get("anchor")
            anchor_point = self._point(anchor_payload) if anchor_payload else None

        anchor_point, army_control_meta = self._standard_bulk_anchor(
            bot=bot,
            awareness=awareness,
            attention=attention,
            now=now,
            fallback_anchor=anchor_point,
        )
        awareness.mem.set(
            K("ops", "army_control", "snapshot"),
            value={
                "updated_at": float(now),
                "owner": self.planner_id,
                "primary_anchor": self._point_payload(anchor_point),
                "secondary_anchor": army_control_meta.get("reinforce_base_pos"),
                "mode": str(army_control_meta.get("mode", "geometry_bulk") or "geometry_bulk"),
                "reason": str(army_control_meta.get("reason", "fallback") or "fallback"),
                "reinforce_base_label": str(army_control_meta.get("reinforce_base_label", "") or ""),
                "controlled_unit_types": list(army_control_meta.get("controlled_unit_types", [])),
                "split_ready": bool(army_control_meta.get("split_ready", False)),
            },
            now=now,
            ttl=5.0,
        )

        # --- HoldAnchorTask: bulk do exército posiciona no setor MASS_HOLD ---
        # Sempre proposto quando há anchor válido, independente de postura.
        # A geometria decide ONDE — o planner só propõe a missão.
        bulk_reserve_counts = self._requirement_counts(list(secure_plan.get("reqs", []))) if secure_plan is not None else {}
        bulk_tank_cap = 1 if posture == ArmyPosture.HOLD_MAIN_RAMP else None
        should_hold = anchor_point is not None
        if use_geometry:
            # Com geometria: propõe sempre que há bulk_sector definido
            should_hold = anchor_point is not None and geo_snap.get("bulk_sector") is not None
        else:
            # Fallback legado: posturas que requerem hold
            _POSTURES_NEEDING_HOLD = {
                ArmyPosture.HOLD_MAIN_RAMP,
                ArmyPosture.HOLD_NAT_CHOKE,
                ArmyPosture.SECURE_NAT,
                ArmyPosture.CONTROLLED_RETREAT,
                ArmyPosture.CONTROLLED_RETAKE,
            }
            should_hold = posture in _POSTURES_NEEDING_HOLD and anchor_point is not None

        if should_hold and anchor_point is not None:
            hold_pid = self._pid("hold_anchor_bulk")
            if not awareness.ops_proposal_running(proposal_id=hold_pid, now=now) and self._due(awareness=awareness, now=now, pid=hold_pid):
                bulk_reqs = self._bulk_requirements(
                    bot=bot,
                    anchor=anchor_point,
                    reserve_counts=bulk_reserve_counts,
                    tank_cap=bulk_tank_cap,
                )

                if bulk_reqs:
                    def _hold_factory(mission_id: str) -> HoldAnchorTask:
                        return HoldAnchorTask(awareness=awareness, log=self.log)

                    out.append(
                        Proposal(
                            proposal_id=hold_pid,
                            domain="MAP_CONTROL",
                            score=93,
                            tasks=[
                                TaskSpec(
                                    task_id="hold_anchor",
                                    task_factory=_hold_factory,
                                    unit_requirements=bulk_reqs,
                                    lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                                )
                            ],
                            lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                            cooldown_s=0.0,
                            risk_level=0,
                            allow_preempt=True,
                        )
                    )
                    self._mark(awareness=awareness, now=now, pid=hold_pid)

        # --- LandBaseTask: fato safe_to_land (compatibilidade) ---
        safe_to_land = bool(snapshot.get("safe_to_land", False))
        nat_offsite = bool(snapshot.get("nat_offsite", False))
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

        # --- DefenseBunkerTask: construir bunker no choke se a postura pede ---
        if base_pos is not None:
            hold_pos_early = self._point(snapshot.get("hold"), fallback=base_pos)
            if hold_pos_early is not None:
                bunker_pid = self._pid("secure_our_nat_bunker")
                if (
                    self._should_request_nat_bunker(
                        bot=bot,
                        attention=attention,
                        posture=posture,
                        snapshot=snapshot,
                        base_pos=base_pos,
                        hold_pos=hold_pos_early,
                    )
                    and not awareness.ops_proposal_running(proposal_id=bunker_pid, now=now)
                    and self._due(awareness=awareness, now=now, pid=bunker_pid)
                ):
                    bunker_factory = self._make_bunker_factory(
                        awareness=awareness,
                        base_pos=base_pos,
                        hold_pos=hold_pos_early,
                    )
                    delayed_natural_alarm = bool(snapshot.get("delayed_natural_alarm", False))
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

        # --- SecureBaseTask: destacamento local no choke da nat ---
        # Proposto quando a geometria pede guarnição local (setor NAT_CHOKE / NAT_RING)
        # OU quando a postura legada pede garrison.
        # NÃO é o dono do bulk — apenas um destacamento local dentro do max_detach_supply.

        # Fonte primária: geometria tem setor NAT_CHOKE em ANCHOR/HEAVY_ANCHOR
        posture_wants_garrison = False
        if use_geometry:
            nat_choke_sector = (geo_snap.get("sector_states") or {}).get(SectorId.NAT_CHOKE.value, {})
            nat_choke_mode = str(nat_choke_sector.get("mode", SectorMode.NONE.value) or SectorMode.NONE.value)
            nat_choke_target = float(nat_choke_sector.get("target_power", 0.0) or 0.0)
            posture_wants_garrison = nat_choke_mode in {
                SectorMode.ANCHOR.value,
                SectorMode.HEAVY_ANCHOR.value,
            } and nat_choke_target > 0.0
        else:
            posture_wants_garrison = posture in {
                ArmyPosture.HOLD_NAT_CHOKE,
                ArmyPosture.SECURE_NAT,
                ArmyPosture.CONTROLLED_RETAKE,
            }

        if False:  # Legacy path disabled; secure_plan above owns nat garrison admission.
            pid = self._pid("secure_our_nat")
            if not awareness.ops_proposal_running(proposal_id=pid, now=now) and self._due(awareness=awareness, now=now, pid=pid):
                base_pos2 = self._point(snapshot.get("target"))
                staging_pos = self._point(snapshot.get("staging"), fallback=base_pos2)
                hold_pos = self._point(snapshot.get("hold"), fallback=base_pos2)
                rush_state = str(snapshot.get("rush_state", "NONE")).upper()
                delayed_natural_alarm = bool(snapshot.get("delayed_natural_alarm", False))
                enemy_nat_power = float(snapshot.get("enemy_nat_power", 0.0) or 0.0)
                own_nat_bunker_count = int(snapshot.get("own_nat_bunker_count", 0) or 0)
                nat_take_in_progress = bool(snapshot.get("nat_offsite", False) or snapshot.get("safe_to_land", False))
                secure_needed = bool(
                    delayed_natural_alarm
                    or rush_state in {"CONFIRMED", "HOLDING"}
                    or enemy_nat_power >= 0.6
                    or own_nat_bunker_count > 0
                    or nat_take_in_progress
                    or posture in {ArmyPosture.SECURE_NAT, ArmyPosture.CONTROLLED_RETAKE}
                )
                if not secure_needed:
                    return out
                if isinstance(nat_zone.get("fallback_anchor"), dict):
                    staging_pos = self._point(nat_zone.get("fallback_anchor"), fallback=staging_pos)
                if isinstance(nat_zone.get("front_anchor"), dict):
                    hold_pos = self._point(nat_zone.get("front_anchor"), fallback=hold_pos)
                if base_pos2 is not None and staging_pos is not None and hold_pos is not None:
                    reqs = self._requirements(
                        bot=bot,
                        attention=attention,
                        hold_pos=hold_pos,
                        snapshot=snapshot,
                        posture_snap=posture_snap,
                    )
                    if reqs:
                        def _factory(mission_id: str) -> SecureBaseTask:
                            return SecureBaseTask(
                                awareness=awareness,
                                base_pos=base_pos2,
                                staging_pos=staging_pos,
                                hold_pos=hold_pos,
                                label="our_nat",
                                log=self.log,
                            )

                        # Score baseado no template da geometria (quando disponível)
                        if use_geometry:
                            template_str = str(geo_snap.get("template", "") or "")
                            if delayed_natural_alarm or rush_state in {"CONFIRMED", "HOLDING"}:
                                score = 88
                            elif template_str == FrontTemplate.TURTLE_NAT.value:
                                score = 88  # Alta urgência — turtle com rush
                            elif template_str in {FrontTemplate.STABILIZE_AND_EXPAND.value, FrontTemplate.CONTAIN.value} and enemy_nat_power >= 0.6:
                                score = 85
                            else:
                                score = 74
                        elif posture == ArmyPosture.HOLD_NAT_CHOKE and rush_state in {"CONFIRMED", "HOLDING"}:
                            score = 88
                        elif posture in {ArmyPosture.HOLD_NAT_CHOKE, ArmyPosture.SECURE_NAT} and (enemy_nat_power >= 0.6 or nat_take_in_progress):
                            score = 85
                        else:
                            score = 74

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
                                    "posture": str(posture.value),
                                    "rush_state": str(snapshot.get("rush_state", "NONE")),
                                    "max_detach_supply": int(posture_snap.get("max_detach_supply", 0) or 0),
                                },
                                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                            )

        if secure_plan is not None:
            base_pos2 = secure_plan["base_pos"]
            staging_pos = secure_plan["staging_pos"]
            hold_pos = secure_plan["hold_pos"]
            reqs = list(secure_plan["reqs"])
            score = int(secure_plan["score"])
            pid = str(secure_plan["proposal_id"])

            def _factory(mission_id: str) -> SecureBaseTask:
                return SecureBaseTask(
                    awareness=awareness,
                    base_pos=base_pos2,
                    staging_pos=staging_pos,
                    hold_pos=hold_pos,
                    label="our_nat",
                    log=self.log,
                )

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
                        "posture": str(posture.value),
                        "rush_state": str(secure_plan.get("rush_state", "NONE")),
                        "max_detach_supply": int(posture_snap.get("max_detach_supply", 0) or 0),
                    },
                    meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                )

        # -----------------------------------------------------------------------
        # LATE-GAME PUSH: MoveOutTask + harass lateral
        #
        # Condições de ativação:
        #   - template == PREP_PUSH (geometria decidiu que é hora de atacar)
        #   - supply_used >= 160 (exército grande o suficiente)
        #   - bank_minerals >= 400 (banco construindo — não gastos ainda)
        #   - sem MoveOutTask já rodando
        #
        # Propõe em paralelo:
        #   1. MoveOutTask — bulk central com leapfrog de tanks (MAP_CONTROL, score=97)
        #   2. BansheeHarass — base lateral do inimigo (HARASS, score=82) se tiver banshee
        #   3. MedivacDropHarassTask — segunda frente (HARASS, score=80) se tiver medivac+bio
        #
        # O harass lateral não compete com o bulk: domínios diferentes.
        # -----------------------------------------------------------------------

        if use_geometry:
            geo_template_str = str(geo_snap.get("template", "") or "")
            is_prep_push = geo_template_str == FrontTemplate.PREP_PUSH.value

            supply_used = float(getattr(bot, "supply_used", 0) or 0)
            minerals = float(getattr(bot, "minerals", 0) or 0)
            vespene = float(getattr(bot, "vespene", 0) or 0)

            push_conditions_met = bool(
                is_prep_push
                and supply_used >= 160
                and (minerals >= 400 or vespene >= 200)
            )

            move_out_pid = self._pid("late_game_move_out")
            move_out_running = awareness.ops_proposal_running(proposal_id=move_out_pid, now=now)

            if push_conditions_met and not move_out_running and self._due(awareness=awareness, now=now, pid=move_out_pid):

                # --- Determina alvo: base mais externa do inimigo com estruturas ---
                push_target: Optional[Point2] = None

                # 1. Estrutura inimiga mais distante da main inimiga (= base mais externa conhecida)
                try:
                    enemy_main = bot.enemy_start_locations[0] if getattr(bot, "enemy_start_locations", None) else None
                    if enemy_main is not None and bot.enemy_structures.amount > 0:
                        structs_sorted = sorted(
                            bot.enemy_structures,
                            key=lambda s: float(s.distance_to(enemy_main)),
                            reverse=True,
                        )
                        push_target = structs_sorted[0].position
                except Exception:
                    pass

                # 2. Fallback: expansion mais próxima do inimigo não nossa
                if push_target is None:
                    try:
                        enemy_main = bot.enemy_start_locations[0] if getattr(bot, "enemy_start_locations", None) else None
                        if enemy_main is not None:
                            candidates = [
                                loc for loc in bot.expansion_locations_list
                                if float(loc.distance_to(enemy_main)) < float(loc.distance_to(bot.start_location))
                            ]
                            if candidates:
                                push_target = min(candidates, key=lambda p: float(p.distance_to(enemy_main)))
                    except Exception:
                        pass

                # 3. Fallback final: enemy_start_location
                if push_target is None:
                    try:
                        push_target = bot.enemy_start_locations[0]
                    except Exception:
                        pass

                # --- Determina ponto de staging (PUSH_STAGING anchor da geometria) ---
                push_staging: Optional[Point2] = None
                push_staging_sector = (geo_snap.get("sector_states") or {}).get("PUSH_STAGING", {})
                push_staging_payload = push_staging_sector.get("anchor_pos") if isinstance(push_staging_sector, dict) else None
                if isinstance(push_staging_payload, dict):
                    push_staging = self._point(push_staging_payload)
                if push_staging is None:
                    push_staging = anchor_point

                if push_target is not None and push_staging is not None and anchor_point is not None:

                    # ---- 1. MoveOutTask: bulk central ----
                    banshee_count = int(bot.units.of_type(U.BANSHEE).ready.amount)
                    medivac_idle_count = int(bot.units.of_type(U.MEDIVAC).ready.idle.amount)

                    move_out_reqs = self._bulk_requirements(
                        bot=bot,
                        anchor=push_staging,
                        reserve_counts={},
                        tank_cap=None,
                    )

                    if move_out_reqs:
                        _pt = push_target
                        _ps = push_staging

                        def _move_out_factory(mission_id: str) -> MoveOutTask:
                            return MoveOutTask(
                                awareness=awareness,
                                target_pos=_pt,
                                start_pos=_ps,
                                n_leapfrog_steps=3,
                                log=self.log,
                            )

                        out.append(
                            Proposal(
                                proposal_id=move_out_pid,
                                domain="MAP_CONTROL",
                                score=97,
                                tasks=[
                                    TaskSpec(
                                        task_id="move_out",
                                        task_factory=_move_out_factory,
                                        unit_requirements=move_out_reqs,
                                        lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                                    )
                                ],
                                lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                                cooldown_s=0.0,
                                risk_level=3,
                                allow_preempt=True,
                            )
                        )
                        self._mark(awareness=awareness, now=now, pid=move_out_pid)

                    # ---- 2. BansheeHarass: base lateral ----
                    banshee_pid = self._pid("late_game_banshee_harass")
                    banshee_running = awareness.ops_proposal_running(proposal_id=banshee_pid, now=now)

                    if banshee_count >= 1 and not banshee_running:
                        banshee_target: Optional[Point2] = None
                        try:
                            enemy_main_b = bot.enemy_start_locations[0] if getattr(bot, "enemy_start_locations", None) else None
                            if enemy_main_b is not None:
                                expansions_sorted = sorted(
                                    bot.expansion_locations_list,
                                    key=lambda p: float(p.distance_to(enemy_main_b)),
                                )
                                for exp in expansions_sorted:
                                    if float(exp.distance_to(enemy_main_b)) > 5.0:
                                        if push_target is None or float(exp.distance_to(push_target)) > 10.0:
                                            banshee_target = exp
                                            break
                                if banshee_target is None:
                                    banshee_target = enemy_main_b
                        except Exception:
                            pass

                        if banshee_target is not None:
                            @dataclass(frozen=True)
                            class _BansheeAttackPickPolicy:
                                objective: Point2
                                name: str = "map_control.push.banshee.v1"

                                def allow(self, unit, *, bot, attention, now: float) -> bool:
                                    if unit is None or unit.type_id != U.BANSHEE:
                                        return False
                                    return bool(getattr(unit, "is_ready", False)) and float(getattr(unit, "health_percentage", 1.0) or 1.0) >= 0.50

                                def score(self, unit, *, bot, attention, now: float) -> float:
                                    try:
                                        dist = float(unit.distance_to(self.objective))
                                    except Exception:
                                        dist = 9999.0
                                    return (float(getattr(unit, "health_percentage", 1.0) or 1.0) * 20.0) - dist

                            _bt = banshee_target

                            def _banshee_factory(mission_id: str) -> BansheeHarass:
                                return BansheeHarass(awareness=awareness, log=self.log, preferred_target=_bt)

                            out.append(
                                Proposal(
                                    proposal_id=banshee_pid,
                                    domain="HARASS",
                                    score=82,
                                    tasks=[
                                        TaskSpec(
                                            task_id="banshee_harass",
                                            task_factory=_banshee_factory,
                                            unit_requirements=[
                                                UnitRequirement(
                                                    unit_type=U.BANSHEE,
                                                    count=min(int(banshee_count), 2),
                                                    pick_policy=_BansheeAttackPickPolicy(objective=_bt),
                                                    required=True,
                                                )
                                            ],
                                            lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                                        )
                                    ],
                                    lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                                    cooldown_s=0.0,
                                    risk_level=2,
                                    allow_preempt=True,
                                )
                            )
                            self._mark(awareness=awareness, now=now, pid=banshee_pid)

                    # ---- 3. MedivacDrop: segunda frente se não tiver banshee ----
                    drop_pid = self._pid("late_game_medivac_drop")
                    drop_running = awareness.ops_proposal_running(proposal_id=drop_pid, now=now)

                    marine_idle = int(bot.units.of_type(U.MARINE).ready.idle.amount)
                    marauder_idle = int(bot.units.of_type(U.MARAUDER).ready.idle.amount)
                    drop_troopers = marine_idle + marauder_idle * 2

                    can_drop = bool(
                        medivac_idle_count >= 1
                        and drop_troopers >= 4
                        and banshee_count == 0
                        and not drop_running
                    )

                    if can_drop:
                        drop_target: Optional[Point2] = None
                        try:
                            enemy_main_d = bot.enemy_start_locations[0] if getattr(bot, "enemy_start_locations", None) else None
                            if enemy_main_d is not None:
                                expansions_by_dist = sorted(
                                    bot.expansion_locations_list,
                                    key=lambda p: float(p.distance_to(enemy_main_d)),
                                )
                                for exp in expansions_by_dist:
                                    if float(exp.distance_to(enemy_main_d)) > 5.0:
                                        drop_target = exp
                                        break
                                if drop_target is None:
                                    drop_target = enemy_main_d
                        except Exception:
                            pass

                        if drop_target is not None:
                            @dataclass(frozen=True)
                            class _MedivacPickPolicy:
                                objective: Point2
                                name: str = "map_control.push.medivac.v1"

                                def allow(self, unit, *, bot, attention, now: float) -> bool:
                                    if unit is None or unit.type_id != U.MEDIVAC:
                                        return False
                                    return bool(getattr(unit, "is_ready", False)) and bool(getattr(unit, "is_idle", True))

                                def score(self, unit, *, bot, attention, now: float) -> float:
                                    try:
                                        return -float(unit.distance_to(self.objective))
                                    except Exception:
                                        return 0.0

                            @dataclass(frozen=True)
                            class _TrooperPickPolicy:
                                objective: Point2
                                unit_type: U
                                name: str = "map_control.push.trooper.v1"

                                def allow(self, unit, *, bot, attention, now: float) -> bool:
                                    if unit is None or unit.type_id != self.unit_type:
                                        return False
                                    return bool(getattr(unit, "is_ready", False)) and bool(getattr(unit, "is_idle", True))

                                def score(self, unit, *, bot, attention, now: float) -> float:
                                    try:
                                        return -float(unit.distance_to(self.objective))
                                    except Exception:
                                        return 0.0

                            _dt = drop_target
                            n_medivac_drop = min(int(medivac_idle_count), 2)
                            slots_available = n_medivac_drop * 8

                            def _drop_factory(mission_id: str) -> MedivacDropHarassTask:
                                return MedivacDropHarassTask(
                                    awareness=awareness,
                                    log=self.log,
                                    target_locations=[_dt],
                                )

                            marines_for_drop = min(int(marine_idle), slots_available)
                            remaining_slots = slots_available - marines_for_drop
                            marauders_for_drop = min(int(marauder_idle), remaining_slots // 2)

                            drop_reqs = [
                                UnitRequirement(
                                    unit_type=U.MEDIVAC,
                                    count=n_medivac_drop,
                                    pick_policy=_MedivacPickPolicy(objective=_dt),
                                    required=True,
                                ),
                            ]
                            if marines_for_drop > 0:
                                drop_reqs.append(
                                    UnitRequirement(
                                        unit_type=U.MARINE,
                                        count=marines_for_drop,
                                        pick_policy=_TrooperPickPolicy(objective=_dt, unit_type=U.MARINE),
                                        required=False,
                                    )
                                )
                            if marauders_for_drop > 0:
                                drop_reqs.append(
                                    UnitRequirement(
                                        unit_type=U.MARAUDER,
                                        count=marauders_for_drop,
                                        pick_policy=_TrooperPickPolicy(objective=_dt, unit_type=U.MARAUDER),
                                        required=False,
                                    )
                                )

                            out.append(
                                Proposal(
                                    proposal_id=drop_pid,
                                    domain="HARASS",
                                    score=80,
                                    tasks=[
                                        TaskSpec(
                                            task_id="medivac_drop_harass",
                                            task_factory=_drop_factory,
                                            unit_requirements=drop_reqs,
                                            lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                                        )
                                    ],
                                    lease_ttl=(None if self.lease_ttl_s is None else float(self.lease_ttl_s)),
                                    cooldown_s=0.0,
                                    risk_level=2,
                                    allow_preempt=True,
                                )
                            )
                            self._mark(awareness=awareness, now=now, pid=drop_pid)

                    if self.log is not None:
                        self.log.emit(
                            "late_game_push_proposed",
                            {
                                "planner": self.planner_id,
                                "supply_used": round(float(supply_used), 1),
                                "minerals": round(float(minerals), 0),
                                "template": geo_template_str,
                                "push_target": {"x": float(push_target.x), "y": float(push_target.y)} if push_target else None,
                                "banshee_count": int(banshee_count),
                                "medivac_idle": int(medivac_idle_count),
                                "proposals_total": int(len(out)),
                            },
                            meta={"module": "planner", "component": "map_control_planner.late_game_push"},
                        )

        return out
