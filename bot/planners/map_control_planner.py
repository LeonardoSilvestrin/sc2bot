"""
Map Control Planner — dono da posição do bulk do exército.

Responsabilidade:
    - Ler a geometria operacional (OperationalGeometryController)
    - Propor tasks coerentes com os setores ativos:
        * HoldAnchorTask → setor MASS_HOLD (bulk principal)
        * SecureBaseTask → setores ANCHOR/HEAVY_ANCHOR/SCREEN secundários
        * DefenseBunkerTask → quando postura pede defesa no choke
    - NÃO disputar posse do bulk com DefensePlanner
    - NÃO reagir à base atacada diretamente — isso é responsabilidade da geometria

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
from bot.tasks.map_control.secure_base_task import SecureBaseTask


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

    def _bulk_requirements(self, *, bot, anchor: Point2) -> list[UnitRequirement]:
        """Constrói requerimentos para o bulk do exército (sem cap de detach budget — é o bulk total)."""
        reqs: list[UnitRequirement] = []
        for unit_type in _BULK_UNIT_TYPES:
            try:
                avail = int(bot.units.of_type(unit_type).ready.amount)
            except Exception:
                avail = 0
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

        # --- HoldAnchorTask: bulk do exército posiciona no setor MASS_HOLD ---
        # Sempre proposto quando há anchor válido, independente de postura.
        # A geometria decide ONDE — o planner só propõe a missão.
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
                bulk_reqs = self._bulk_requirements(bot=bot, anchor=anchor_point)

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

        if posture_wants_garrison:
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

        return out
