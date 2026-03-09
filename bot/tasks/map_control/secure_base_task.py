from __future__ import annotations

from dataclasses import dataclass
import math

from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.intel.utils.natural_geometry import sanitize_natural_defense_point
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick

_NON_COMBAT = {U.SCV, U.PROBE, U.DRONE, U.MULE, U.LARVA, U.EGG}


@dataclass
class SecureBaseTask(BaseTask):
    awareness: Awareness
    base_pos: Point2
    staging_pos: Point2
    hold_pos: Point2
    label: str = "our_nat"
    log: DevLogger | None = None
    _probe_tag: int | None = None
    _probe_cleared_at: float = 0.0
    _probe_hold_started_at: float = 0.0

    def __init__(
        self,
        *,
        awareness: Awareness,
        base_pos: Point2,
        staging_pos: Point2,
        hold_pos: Point2,
        label: str = "our_nat",
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="secure_base", domain="MAP_CONTROL", commitment=72)
        self.awareness = awareness
        self.base_pos = base_pos
        self.staging_pos = staging_pos
        self.hold_pos = hold_pos
        self.label = str(label)
        self.log = log
        self._probe_tag = None
        self._probe_cleared_at = 0.0
        self._probe_hold_started_at = 0.0

    @staticmethod
    def _enemy_combat_near(bot, *, center: Point2, radius: float) -> list:
        out = []
        for unit in list(getattr(bot, "enemy_units", []) or []):
            try:
                if unit.type_id in _NON_COMBAT:
                    continue
                if float(unit.distance_to(center)) <= float(radius):
                    out.append(unit)
            except Exception:
                continue
        for struct in list(getattr(bot, "enemy_structures", []) or []):
            try:
                if float(struct.distance_to(center)) > float(radius):
                    continue
                if struct.type_id in {
                    U.COMMANDCENTER,
                    U.ORBITALCOMMAND,
                    U.PLANETARYFORTRESS,
                    U.HATCHERY,
                    U.LAIR,
                    U.HIVE,
                    U.NEXUS,
                }:
                    continue
                out.append(struct)
            except Exception:
                continue
        return out

    @staticmethod
    def _slots(center: Point2, *, radius: float, count: int) -> list[Point2]:
        out: list[Point2] = []
        for idx in range(max(1, int(count))):
            ang = (2.0 * math.pi * float(idx)) / float(max(1, int(count)))
            out.append(
                Point2(
                    (
                        float(center.x) + (float(radius) * math.cos(ang)),
                        float(center.y) + (float(radius) * math.sin(ang)),
                    )
                )
            )
        return out

    @staticmethod
    def _point_from_payload(payload, *, fallback: Point2) -> Point2:
        if not isinstance(payload, dict):
            return fallback
        try:
            return Point2((float(payload.get("x", fallback.x)), float(payload.get("y", fallback.y))))
        except Exception:
            return fallback

    @staticmethod
    def _pathable(bot, pos: Point2) -> bool:
        try:
            return bool(bot.in_pathing_grid(pos))
        except Exception:
            return True

    @staticmethod
    def _building_tracker(bot) -> dict:
        try:
            return dict(bot.mediator.get_building_tracker_dict or {})
        except Exception:
            return {}

    @classmethod
    def _planned_structure_sites(cls, bot, *, centers: list[Point2], structure_types: set[U], radius: float) -> list[Point2]:
        out: list[Point2] = []
        for entry in cls._building_tracker(bot).values():
            if not isinstance(entry, dict):
                continue
            if entry.get("structure_type", None) not in structure_types:
                continue
            pos = entry.get("target", None) or entry.get("pos", None)
            if pos is None:
                continue
            try:
                point = Point2((float(pos.x), float(pos.y))) if hasattr(pos, "x") else pos
            except Exception:
                point = pos
            try:
                if centers and min(float(point.distance_to(center)) for center in centers if center is not None) > float(radius):
                    continue
            except Exception:
                continue
            duplicate = False
            for existing in out:
                try:
                    if float(existing.distance_to(point)) <= 0.9:
                        duplicate = True
                        break
                except Exception:
                    continue
            if not duplicate:
                out.append(point)
        return out

    @staticmethod
    def _nearest_reserved_site(unit, reserved_sites: list[Point2], *, radius: float) -> Point2 | None:
        best = None
        best_dist = float(radius)
        for site in list(reserved_sites or []):
            try:
                dist = float(unit.distance_to(site))
            except Exception:
                continue
            if dist <= best_dist:
                best = site
                best_dist = dist
        return best

    def _sanitize_slots(self, bot, slots: list[Point2], *, reserved_sites: list[Point2], retreat: Point2, fallback: Point2) -> list[Point2]:
        out: list[Point2] = []
        for slot in list(slots or []):
            conflict = False
            for site in list(reserved_sites or []):
                try:
                    if float(slot.distance_to(site)) <= 2.6:
                        conflict = True
                        break
                except Exception:
                    continue
            if not conflict:
                safe_slot = sanitize_natural_defense_point(
                    bot,
                    pos=slot,
                    fallback=fallback,
                    prefer_towards=retreat,
                    nat=self.base_pos,
                )
                if not any(float(existing.distance_to(safe_slot)) <= 0.6 for existing in out):
                    out.append(safe_slot)
                continue
            try:
                shifted = slot.towards(retreat, 3.0)
            except Exception:
                shifted = fallback
            shifted = sanitize_natural_defense_point(
                bot,
                pos=shifted,
                fallback=fallback,
                prefer_towards=retreat,
                nat=self.base_pos,
            )
            retry_conflict = False
            for site in list(reserved_sites or []):
                try:
                    if float(shifted.distance_to(site)) <= 2.4:
                        retry_conflict = True
                        break
                except Exception:
                    continue
            if not retry_conflict:
                if not any(float(existing.distance_to(shifted)) <= 0.6 for existing in out):
                    out.append(shifted)
        if out:
            return out
        return [
            sanitize_natural_defense_point(
                bot,
                pos=fallback,
                fallback=fallback,
                prefer_towards=retreat,
                nat=self.base_pos,
            )
        ]

    def _safe_anchor(self, bot, *, preferred: Point2, fallback: Point2) -> Point2:
        if self._pathable(bot, preferred):
            return preferred
        if self._pathable(bot, fallback):
            return fallback
        return self.base_pos

    @staticmethod
    def _cc_footprint_sites(center: Point2) -> list[Point2]:
        offsets = (
            (0.0, 0.0),
            (2.0, 0.0),
            (-2.0, 0.0),
            (0.0, 2.0),
            (0.0, -2.0),
            (2.0, 2.0),
            (2.0, -2.0),
            (-2.0, 2.0),
            (-2.0, -2.0),
        )
        return [Point2((float(center.x) + dx, float(center.y) + dy)) for dx, dy in offsets]

    @staticmethod
    def _bunkers_near_base(bot, *, base_pos: Point2, hold_pos: Point2) -> list:
        out = []
        for unit in list(getattr(bot, "structures", []) or []):
            try:
                if getattr(unit, "type_id", None) != U.BUNKER:
                    continue
                if not bool(getattr(unit, "is_ready", False)):
                    continue
                if min(float(unit.distance_to(base_pos)), float(unit.distance_to(hold_pos))) > 10.0:
                    continue
                out.append(unit)
            except Exception:
                continue
        return out

    @staticmethod
    def _bunker_has_space(bunker) -> bool:
        try:
            cargo_max = int(getattr(bunker, "cargo_max", 4) or 4)
            cargo_used = int(getattr(bunker, "cargo_used", 0) or 0)
            return int(cargo_used) < int(cargo_max)
        except Exception:
            return True

    @staticmethod
    def _height(bot, pos: Point2) -> float:
        try:
            if not bool(bot.in_pathing_grid(pos)):
                return -9999.0
        except Exception:
            pass
        try:
            return float(bot.get_terrain_z_height(pos))
        except Exception:
            return -9999.0

    def _best_ramp_tank_anchor(self, bot) -> Point2:
        # Tank deve sentar no highground da nat (staging_pos), de onde cobre o
        # lowground (hold_pos) com alcance de siege. NÃO deve descer para o choke.
        siege_range = 13.0
        highground_h = self._height(bot, self.staging_pos)
        lowground_h = self._height(bot, self.hold_pos)
        preferred_center = self.staging_pos
        fallback = self._safe_anchor(bot, preferred=preferred_center, fallback=self.base_pos)
        best = fallback
        best_score = -9999.0

        candidates = [self.staging_pos, self.base_pos.towards(self.staging_pos, 1.5)]
        for radius in (1.0, 2.0, 3.0, 4.0):
            for idx in range(16):
                ang = (2.0 * math.pi * float(idx)) / 16.0
                candidates.append(
                    Point2(
                        (
                            float(preferred_center.x) + (float(radius) * math.cos(ang)),
                            float(preferred_center.y) + (float(radius) * math.sin(ang)),
                        )
                    )
                )

        for pos in candidates:
            if not self._pathable(bot, pos):
                continue
            h = self._height(bot, pos)
            # Apenas highground — mesma altura ou mais alto que staging_pos
            if h < (float(highground_h) - 0.5):
                continue
            # Deve cobrir o choke com alcance de siege
            if float(pos.distance_to(self.hold_pos)) > siege_range:
                continue
            score = 0.0
            # Prefere posições altas (não no lowground do choke)
            score += max(0.0, float(h) - float(lowground_h)) * 4.0
            # Próximo ao staging_pos
            score += max(0.0, 5.0 - float(pos.distance_to(self.staging_pos))) * 2.0
            if score > best_score:
                best = pos
                best_score = score
        return best

    def _snapshot(self, *, now: float) -> dict:
        snap = self.awareness.mem.get(
            K("intel", "map_control", "our_nat", "snapshot"),
            now=now,
            default={},
        ) or {}
        return snap if isinstance(snap, dict) else {}

    def _territorial_zone(self, *, now: float) -> dict:
        snap = self.awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
        if not isinstance(snap, dict):
            return {}
        zones = snap.get("zones", {})
        if not isinstance(zones, dict):
            return {}
        zone = zones.get("natural_front", {})
        return dict(zone) if isinstance(zone, dict) else {}

    @staticmethod
    def _slot_point(slot: dict | None) -> Point2 | None:
        if not isinstance(slot, dict):
            return None
        payload = slot.get("position")
        if not isinstance(payload, dict):
            return None
        try:
            return Point2((float(payload["x"]), float(payload["y"])))
        except Exception:
            return None

    def _slot_positions(self, zone: dict, *, roles: set[str]) -> list[Point2]:
        out: list[Point2] = []
        for slot in list(zone.get("active_slots", []) or []):
            try:
                if str(slot.get("role", "") or "") not in roles:
                    continue
                pos = self._slot_point(slot)
                if pos is not None:
                    out.append(pos)
            except Exception:
                continue
        return out

    @staticmethod
    def _assign_scv_role(bot, units: list, role: UnitRole) -> None:
        for unit in list(units or []):
            try:
                if getattr(unit, "type_id", None) != U.SCV:
                    continue
                bot.mediator.assign_role(tag=int(unit.tag), role=role, remove_from_squad=True)
            except Exception:
                continue

    def _should_release(self, *, bot, now: float, enemy_near: list, enemy_main: list) -> bool:
        snap = self._snapshot(now=now)
        if enemy_main:
            return True
        if enemy_near:
            return False
        should_secure = bool(snap.get("should_secure", False))
        fortified = bool(snap.get("fortified", False))
        rush_state = str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
        nat_taken = False
        for th in list(getattr(bot, "townhalls", []) or []):
            try:
                if float(th.distance_to(self.base_pos)) <= 8.0:
                    nat_taken = True
                    break
            except Exception:
                continue
        # Rush terminou e sem inimigos visíveis → libera independente de should_secure
        rush_over = rush_state in {"ENDED", "NONE"}
        if rush_over:
            return True
        # HOLDING sem inimigos visíveis e defesa fortified → libera SCVs para minerar
        # Evita SCVs presos por até 36s enquanto rush_state aguarda transição para ENDED
        if rush_state == "HOLDING" and bool(fortified):
            return True
        return bool(
            (not should_secure)
            or (
                nat_taken
                and fortified
                and rush_state not in {"SUSPECTED", "CONFIRMED", "HOLDING"}
            )
        )

    def _pick_probe_unit(self, units: list):
        if self._probe_tag is not None:
            for unit in units:
                try:
                    if int(getattr(unit, "tag", -1) or -1) == int(self._probe_tag):
                        return unit
                except Exception:
                    continue
        priorities = [U.MARINE, U.SCV, U.MARAUDER, U.HELLION, U.CYCLONE]
        for unit_type in priorities:
            candidates = [u for u in units if getattr(u, "type_id", None) == unit_type]
            if candidates:
                probe = min(candidates, key=lambda u: float(u.distance_to(self.hold_pos)))
                self._probe_tag = int(getattr(probe, "tag", -1) or -1)
                return probe
        if units:
            probe = min(units, key=lambda u: float(u.distance_to(self.hold_pos)))
            self._probe_tag = int(getattr(probe, "tag", -1) or -1)
            return probe
        return None

    def _nat_probe_cleared(self, *, bot, now: float, probe_unit, enemy_near: list, enemy_main: list) -> bool:
        if enemy_near:
            self._probe_cleared_at = 0.0
            self._probe_hold_started_at = 0.0
            return False
        if probe_unit is None:
            self._probe_hold_started_at = 0.0
            return False
        try:
            if float(probe_unit.distance_to(self.hold_pos)) > 4.5:
                self._probe_hold_started_at = 0.0
                return False
        except Exception:
            self._probe_hold_started_at = 0.0
            return False
        if float(self._probe_hold_started_at) <= 0.0:
            self._probe_hold_started_at = float(now)
        if float(self._probe_cleared_at) <= 0.0:
            self._probe_cleared_at = float(now)
            return False
        hold_time = float(now) - float(self._probe_cleared_at)
        # If there is still harassment in main, avoid stalling natural forever:
        # require a longer, stable hold at the nat choke before releasing lowground.
        if enemy_main:
            return hold_time >= 2.1
        return hold_time >= 0.8

    def _handle_tank(self, *, unit, anchor: Point2, enemy_near: list, hold_pressure: bool) -> bool:
        if unit.type_id == U.SIEGETANKSIEGED:
            if enemy_near:
                unit.attack(min(enemy_near, key=lambda e: float(unit.distance_to(e))))
                return True
            if bool(hold_pressure):
                return True
            if float(unit.distance_to(anchor)) > 7.5:
                unit(AbilityId.UNSIEGE_UNSIEGE)
                return True
            return True
        if float(unit.distance_to(anchor)) > 2.5:
            unit.move(anchor)
            return True
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        return True

    @staticmethod
    def _support_targets(bot, *, base_pos: Point2, hold_pos: Point2) -> list:
        allowed = {
            U.SIEGETANK,
            U.SIEGETANKSIEGED,
            U.BUNKER,
            U.COMMANDCENTER,
            U.ORBITALCOMMAND,
            U.PLANETARYFORTRESS,
            U.SUPPLYDEPOT,
            U.SUPPLYDEPOTLOWERED,
            U.BARRACKS,
            U.BARRACKSREACTOR,
            U.BARRACKSTECHLAB,
        }
        targets = []
        for unit in list(getattr(bot, "units", []) or []) + list(getattr(bot, "structures", []) or []):
            try:
                if getattr(unit, "type_id", None) not in allowed:
                    continue
                if min(float(unit.distance_to(base_pos)), float(unit.distance_to(hold_pos))) > 10.0:
                    continue
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                if hp_max <= 0.0 or hp >= hp_max:
                    continue
                targets.append(unit)
            except Exception:
                continue
        targets.sort(
            key=lambda u: (
                0 if getattr(u, "type_id", None) in {U.SIEGETANK, U.SIEGETANKSIEGED, U.BUNKER} else 1,
                float(getattr(u, "health_percentage", 1.0) or 1.0),
            )
        )
        return targets

    @staticmethod
    def _issue_repair(scv, target) -> bool:
        try:
            repair_fn = getattr(scv, "repair", None)
            if callable(repair_fn):
                repair_fn(target)
                return True
        except Exception:
            pass
        for ability_name in ("EFFECT_REPAIR_SCV", "EFFECT_REPAIR"):
            try:
                ability = getattr(AbilityId, ability_name, None)
                if ability is None:
                    continue
                scv(ability, target)
                return True
            except Exception:
                continue
        try:
            scv.move(target.position)
            return True
        except Exception:
            return False

    def _handle_mine(self, *, unit, slot: Point2, enemy_near: list) -> bool:
        if unit.type_id == U.WIDOWMINEBURROWED:
            if enemy_near:
                return False
            if float(unit.distance_to(slot)) > 3.0:
                unit(AbilityId.BURROWUP_WIDOWMINE)
                return True
            return False
        if float(unit.distance_to(slot)) > 1.7:
            unit.move(slot)
            return True
        unit(AbilityId.BURROWDOWN_WIDOWMINE)
        return True

    def _handle_general(self, *, unit, slot: Point2, enemy_near: list, bunkers: list, reserved_sites: list[Point2]) -> bool:
        if unit.type_id == U.MEDIVAC:
            unit.move(self.staging_pos)
            return True
        reserved_site = self._nearest_reserved_site(unit, reserved_sites, radius=2.6)
        if reserved_site is not None and unit.type_id != U.MEDIVAC:
            unit.move(slot)
            return True
        if unit.type_id == U.MARINE and bunkers:
            ready_bunkers = [b for b in bunkers if self._bunker_has_space(b)]
            if ready_bunkers:
                bunker = min(ready_bunkers, key=lambda b: float(unit.distance_to(b)))
                if float(unit.distance_to(bunker)) <= 2.0:
                    unit(AbilityId.SMART, bunker)
                else:
                    unit.move(bunker.position)
                return True
        if enemy_near:
            unit.attack(min(enemy_near, key=lambda e: float(unit.distance_to(e))))
            return True
        if float(unit.distance_to(slot)) > 2.0:
            unit.move(slot)
            return True
        unit.attack(self.hold_pos)
        return True

    def _handle_scv(self, *, unit, slot: Point2, enemy_near: list, repair_targets: list, reserved_sites: list[Point2]) -> bool:
        reserved_site = self._nearest_reserved_site(unit, reserved_sites, radius=2.4)
        if reserved_site is not None and not repair_targets:
            unit.move(slot)
            return True
        if enemy_near and float(getattr(unit, "health_percentage", 1.0) or 1.0) >= 0.55:
            close_enemy = [e for e in list(enemy_near) if float(unit.distance_to(e)) <= 3.0]
            if close_enemy:
                unit.attack(min(close_enemy, key=lambda e: float(unit.distance_to(e))))
                return True
        if repair_targets:
            return bool(self._issue_repair(unit, repair_targets[0]))
        if float(unit.distance_to(slot)) > 1.8:
            unit.move(slot)
            return True
        unit.move(self.hold_pos.towards(self.base_pos, 1.5))
        return True

    def _handle_probe_unit(self, *, unit, enemy_near: list, reserved_sites: list[Point2]) -> bool:
        reserved_site = self._nearest_reserved_site(unit, reserved_sites, radius=2.5)
        if reserved_site is not None:
            unit.move(self.staging_pos)
            return True
        if enemy_near:
            if unit.type_id == U.SCV:
                close_enemy = [e for e in list(enemy_near) if float(unit.distance_to(e)) <= 2.8]
                if close_enemy:
                    unit.attack(min(close_enemy, key=lambda e: float(unit.distance_to(e))))
                    return True
            unit.move(self.staging_pos)
            return True
        try:
            if float(unit.distance_to(self.hold_pos)) > 2.0:
                unit.move(self.hold_pos)
                return True
        except Exception:
            unit.move(self.hold_pos)
            return True
        if unit.type_id != U.SCV:
            unit.attack(self.hold_pos)
        else:
            unit.move(self.hold_pos)
        return True

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        now = float(tick.time)
        snap = self._snapshot(now=now)
        zone = self._territorial_zone(now=now)
        self.base_pos = self._point_from_payload(snap.get("target"), fallback=self.base_pos)
        self.staging_pos = self._point_from_payload(snap.get("staging"), fallback=self.staging_pos)
        self.hold_pos = self._point_from_payload(snap.get("hold"), fallback=self.hold_pos)
        zone_front = self._slot_point({"position": zone.get("front_anchor")}) if zone else None
        zone_fallback = self._slot_point({"position": zone.get("fallback_anchor")}) if zone else None
        if zone_fallback is not None:
            self.staging_pos = zone_fallback
        if zone_front is not None:
            self.hold_pos = zone_front
        self.staging_pos = sanitize_natural_defense_point(
            bot,
            pos=self.staging_pos,
            fallback=self.base_pos,
            prefer_towards=self.base_pos,
            nat=self.base_pos,
        )
        self.hold_pos = sanitize_natural_defense_point(
            bot,
            pos=self.hold_pos,
            fallback=self.base_pos,
            prefer_towards=self.hold_pos.towards(self.base_pos, 1.0),
            nat=self.base_pos,
        )

        units = [bot.units.find_by_tag(int(tag)) for tag in self.assigned_tags]
        units = [u for u in units if u is not None]
        if not units:
            return TaskResult.failed("no_units_alive")

        enemy_near = self._enemy_combat_near(bot, center=self.hold_pos, radius=18.0)
        enemy_main = self._enemy_combat_near(bot, center=bot.start_location, radius=18.0)
        if self._should_release(bot=bot, now=now, enemy_near=enemy_near, enemy_main=enemy_main):
            self._assign_scv_role(bot, units, UnitRole.GATHERING)
            self._done("secure_base_released")
            return TaskResult.done("secure_base_released")

        self._assign_scv_role(bot, units, UnitRole.REPAIRING)
        probe_unit = self._pick_probe_unit(units)
        lowground_cleared = self._nat_probe_cleared(bot=bot, now=now, probe_unit=probe_unit, enemy_near=enemy_near, enemy_main=enemy_main)
        reserved_sites = self._planned_structure_sites(
            bot,
            centers=[self.base_pos, self.hold_pos, self.staging_pos],
            structure_types={U.BUNKER, U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS},
            radius=12.0,
        )
        # Se a expansão da nat ainda não foi encomendada, reservar o site pretendido
        # para evitar deadlock: marines parados no tile bloqueiam o SCV de construir.
        # CC tem footprint 5x5 (raio ~2.83 até o canto) — reservar centro + 4 offsets
        # para garantir que _sanitize_slots e _handle_general empurrem unidades de toda a área.
        plan_active = self.awareness.mem.get(K("macro", "plan", "active"), now=now, default={}) or {}
        reserve_nat_cc_site = bool(
            (isinstance(plan_active, dict) and bool(plan_active.get("enable_expansion")) and str(plan_active.get("expand_target_label", "") or "") == "NATURAL")
            or bool(snap.get("nat_offsite", False))
            or bool(snap.get("safe_to_land", False))
        )
        if reserve_nat_cc_site:
            registry = self.awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
            if isinstance(registry, dict):
                nat_entry = registry.get("NATURAL", {})
                if isinstance(nat_entry, dict):
                    intended_raw = nat_entry.get("intended_pos")
                    if isinstance(intended_raw, dict):
                        try:
                            intended_pt = Point2((float(intended_raw["x"]), float(intended_raw["y"])))
                            if not any(float(intended_pt.distance_to(s)) <= 0.9 for s in reserved_sites):
                                reserved_sites = list(reserved_sites) + self._cc_footprint_sites(intended_pt)
                        except Exception:
                            pass
        if reserve_nat_cc_site and not any(float(self.base_pos.distance_to(s)) <= 0.9 for s in reserved_sites):
            reserved_sites = list(reserved_sites) + self._cc_footprint_sites(self.base_pos)
        perimeter = self._slots(self.hold_pos, radius=4.5, count=max(4, len(units)))
        staging_perimeter = self._slots(self.staging_pos, radius=3.0, count=max(4, len(units)))
        mine_center = self.staging_pos
        mine_slots = self._slots(mine_center, radius=2.5, count=4)
        support_slots = self._slots(self.hold_pos.towards(self.base_pos, 1.7), radius=1.8, count=3)
        territorial_tank_slots = self._slot_positions(zone, roles={"siege_anchor", "fallback_anchor"})
        territorial_screen_slots = self._slot_positions(zone, roles={"screen_front", "screen_left", "screen_right"})
        territorial_support_slots = self._slot_positions(zone, roles={"rear_support", "vision_spot"})
        perimeter = self._sanitize_slots(bot, perimeter, reserved_sites=reserved_sites, retreat=self.staging_pos, fallback=self.staging_pos)
        staging_perimeter = self._sanitize_slots(bot, staging_perimeter, reserved_sites=reserved_sites, retreat=self.staging_pos, fallback=self.staging_pos)
        support_slots = self._sanitize_slots(bot, support_slots, reserved_sites=reserved_sites, retreat=self.staging_pos, fallback=self.staging_pos)
        if territorial_screen_slots:
            perimeter = territorial_screen_slots
        if territorial_support_slots:
            support_slots = territorial_support_slots
        tank_units = [u for u in units if u.type_id in {U.SIEGETANK, U.SIEGETANKSIEGED}]
        forward_staging_anchor = self._best_ramp_tank_anchor(bot)
        rear_tank_anchor = self._safe_anchor(
            bot,
            preferred=self.staging_pos.towards(self.base_pos, 0.8),
            fallback=self.staging_pos,
        )
        front_tank_anchor = forward_staging_anchor
        tank_anchors = [front_tank_anchor]
        if territorial_tank_slots:
            tank_anchors = list(territorial_tank_slots)
            front_tank_anchor = territorial_tank_slots[0]
            rear_tank_anchor = territorial_tank_slots[min(1, len(territorial_tank_slots) - 1)]
        if enemy_main:
            tank_anchors = [rear_tank_anchor] * len(tank_units)
        elif len(tank_units) >= 2:
            tank_anchors.append(rear_tank_anchor)
        repair_targets = self._support_targets(bot, base_pos=self.base_pos, hold_pos=self.hold_pos)
        bunkers = self._bunkers_near_base(bot, base_pos=self.base_pos, hold_pos=self.hold_pos)
        issued = False
        mine_idx = 0
        general_idx = 0
        tank_idx = 0
        scv_idx = 0

        for unit in units:
            is_probe = probe_unit is not None and int(getattr(unit, "tag", -1) or -1) == int(getattr(probe_unit, "tag", -2) or -2)
            if is_probe and not lowground_cleared:
                issued = self._handle_probe_unit(unit=unit, enemy_near=enemy_near, reserved_sites=reserved_sites) or issued
                continue
            if unit.type_id in {U.SIEGETANK, U.SIEGETANKSIEGED}:
                if not lowground_cleared:
                    if enemy_main:
                        anchor = rear_tank_anchor
                    else:
                        anchor = forward_staging_anchor if int(tank_idx) == 0 else rear_tank_anchor
                    tank_idx += 1
                    issued = self._handle_tank(
                        unit=unit,
                        anchor=anchor,
                        enemy_near=enemy_near,
                        hold_pressure=bool(enemy_near or enemy_main),
                    ) or issued
                    continue
                anchor = tank_anchors[min(int(tank_idx), len(tank_anchors) - 1)]
                tank_idx += 1
                issued = self._handle_tank(
                    unit=unit,
                    anchor=anchor,
                    enemy_near=enemy_near,
                    hold_pressure=bool(enemy_near or enemy_main),
                ) or issued
                continue
            if unit.type_id in {U.WIDOWMINE, U.WIDOWMINEBURROWED}:
                slot = mine_slots[mine_idx % len(mine_slots)] if mine_slots else self.base_pos
                mine_idx += 1
                issued = self._handle_mine(unit=unit, slot=slot, enemy_near=enemy_near) or issued
                continue
            if unit.type_id == U.SCV:
                if not lowground_cleared:
                    slot = staging_perimeter[scv_idx % len(staging_perimeter)] if staging_perimeter else self.staging_pos
                    scv_idx += 1
                    if not is_probe:
                        if float(unit.distance_to(slot)) > 1.8:
                            unit.move(slot)
                        else:
                            unit.move(self.staging_pos)
                        issued = True
                        continue
                slot = support_slots[scv_idx % len(support_slots)] if support_slots else self.staging_pos
                scv_idx += 1
                issued = self._handle_scv(
                    unit=unit,
                    slot=slot,
                    enemy_near=enemy_near,
                    repair_targets=repair_targets,
                    reserved_sites=reserved_sites,
                ) or issued
                continue
            if not lowground_cleared:
                slot = staging_perimeter[general_idx % len(staging_perimeter)] if staging_perimeter else self.staging_pos
                general_idx += 1
                if float(unit.distance_to(slot)) > 2.0:
                    unit.move(slot)
                elif unit.type_id != U.MEDIVAC:
                    unit.attack(self.staging_pos)
                else:
                    unit.move(self.staging_pos)
                issued = True
                continue
            slot = perimeter[general_idx % len(perimeter)] if perimeter else self.staging_pos
            general_idx += 1
            issued = self._handle_general(
                unit=unit,
                slot=slot,
                enemy_near=enemy_near,
                bunkers=bunkers,
                reserved_sites=reserved_sites,
            ) or issued

        if issued:
            self._active("securing_base")
            return TaskResult.running("securing_base")
        return TaskResult.noop("secure_base_idle")
