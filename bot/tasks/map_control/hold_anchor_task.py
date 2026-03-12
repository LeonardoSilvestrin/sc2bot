"""
HoldAnchorTask: posture task for the army bulk.

Responsibility: move the army bulk to the current posture anchor and hold it there.
This task executes posture; it does not derive posture.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.intel.geometry.sector_types import FrontTemplate, SectorMode
from bot.intel.strategy.i3_army_posture_intel import ArmyPosture
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick

_BULK_TYPES = {
    U.MARINE,
    U.MARAUDER,
    # REAPER excluído do bulk: é unidade de harass/scout, não faz sentido
    # segurar no anchor. Sem missão, deve ficar livre no mapa.
    U.HELLION,
    U.CYCLONE,
    U.SIEGETANK,
    U.SIEGETANKSIEGED,
    U.THOR,
    U.THORAP,
    U.MEDIVAC,
}

# Units that need extra care instead of blindly rushing the anchor.
_SLOW_POSITIONAL = {U.SIEGETANK, U.SIEGETANKSIEGED, U.WIDOWMINE, U.WIDOWMINEBURROWED}
_MINE_SLOT_ROLES = {"mine_choke", "mine_flank_left", "mine_flank_right"}

# Raio dentro do qual consideramos a unidade "no anchor"
_AT_ANCHOR_RADIUS = 4.5
_SLOW_AT_ANCHOR_RADIUS = 7.0
# Raio a partir do qual tanks sieged recebem unsiege para se mover ao novo anchor.
# Valor alto por design: o anchor pode oscilar alguns tiles entre ticks (geometria),
# então só unsiegeia se realmente precisar se reposicionar muito.
_TANK_UNSIEGE_TO_MOVE_RADIUS = 16.0
_TANK_LOCAL_HOLD_RADIUS = 15.0
_MAIN_RAMP_BUNKER_RADIUS = 14.0
# Distância recuada do anchor da rampa para posicionar o tank em siege (fora do range inimigo).
# O anchor de MAIN_RAMP já está 4.5 tiles atrás do ramp_top — recuo extra pequeno.
_TANK_RAMP_SIEGE_RETREAT = 2.0
_MAIN_RAMP_TANK_RESERVE_RETREAT = 8.0
_MAIN_RAMP_TANK_AT_ANCHOR_RADIUS = 3.25
_MAIN_RAMP_TANK_UNSIEGE_TO_MOVE_RADIUS = 5.5


def _point_from_payload(payload) -> Point2 | None:
    if not isinstance(payload, dict):
        return None
    try:
        return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
    except Exception:
        return None


def _nat_landing_reservation(awareness: Awareness, *, now: float) -> tuple[Point2 | None, Point2 | None]:
    snap = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
    if not isinstance(snap, dict):
        return None, None
    if not bool(snap.get("nat_offsite", False) or snap.get("safe_to_land", False)):
        return None, None
    return _point_from_payload(snap.get("target")), _point_from_payload(snap.get("staging"))


def _building_tracker(bot) -> dict:
    try:
        return dict(bot.mediator.get_building_tracker_dict or {})
    except Exception:
        return {}


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


def _nat_reserved_sites(awareness: Awareness, bot, *, now: float) -> tuple[list[Point2], Point2 | None]:
    snap = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
    if not isinstance(snap, dict):
        return [], None

    target = _point_from_payload(snap.get("target"))
    staging = _point_from_payload(snap.get("staging"))
    hold = _point_from_payload(snap.get("hold"))
    centers = [p for p in (target, staging, hold) if p is not None]
    out: list[Point2] = []

    for entry in _building_tracker(bot).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("structure_type", None) not in {U.BUNKER, U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS}:
            continue
        pos = entry.get("target", None) or entry.get("pos", None)
        if pos is None:
            continue
        try:
            point = Point2((float(pos.x), float(pos.y))) if hasattr(pos, "x") else pos
        except Exception:
            point = pos
        try:
            if centers and min(float(point.distance_to(center)) for center in centers) > 12.0:
                continue
        except Exception:
            continue
        if not any(float(point.distance_to(existing)) <= 0.9 for existing in out):
            out.append(point)

    if target is not None and bool(snap.get("nat_offsite", False) or snap.get("safe_to_land", False)):
        for point in _cc_footprint_sites(target):
            if not any(float(point.distance_to(existing)) <= 0.9 for existing in out):
                out.append(point)

    return out, staging


def _main_ramp_top(bot) -> Point2 | None:
    try:
        return bot.main_base_ramp.top_center
    except Exception:
        return None


def _main_ramp_guard_points(bot) -> list[tuple[Point2, float]]:
    try:
        ramp = getattr(bot, "main_base_ramp", None)
    except Exception:
        ramp = None
    if ramp is None:
        return []
    out: list[tuple[Point2, float]] = []
    for point, radius in (
        (getattr(ramp, "top_center", None), 8.5),
        (getattr(ramp, "bottom_center", None), 7.5),
        (getattr(ramp, "barracks_correct_placement", None), 4.75),
    ):
        if point is not None:
            out.append((point, float(radius)))
    for depot in list(getattr(ramp, "corner_depots", []) or []):
        if depot is not None:
            out.append((depot, 5.75))
    return out


def _respects_main_ramp_guards(pos: Point2 | None, *, bot, slack: float = 0.15) -> bool:
    if pos is None:
        return False
    for guarded_point, min_dist in _main_ramp_guard_points(bot):
        try:
            if float(pos.distance_to(guarded_point)) + float(slack) < float(min_dist):
                return False
        except Exception:
            continue
    return True


def _clamp_main_ramp_tank_anchor(bot, *, anchor: Point2, fallback: Point2) -> Point2:
    if _respects_main_ramp_guards(anchor, bot=bot):
        return anchor
    candidates = [fallback]
    try:
        start = bot.start_location
    except Exception:
        start = fallback
    for backoff in (1.5, 3.0, 4.5, 6.0, 7.5, 9.0):
        try:
            candidates.append(anchor.towards(start, float(backoff)))
        except Exception:
            continue
    for candidate in candidates:
        try:
            if not bool(bot.in_pathing_grid(candidate)):
                continue
        except Exception:
            pass
        if _respects_main_ramp_guards(candidate, bot=bot):
            return candidate
    return fallback


def _main_ramp_bunkers(bot) -> list:
    top = _main_ramp_top(bot)
    if top is None:
        return []
    out = []
    for bunker in list(getattr(bot, "structures", []) or []):
        try:
            if getattr(bunker, "type_id", None) != U.BUNKER:
                continue
            if not bool(getattr(bunker, "is_ready", False)):
                continue
            cargo_used = int(getattr(bunker, "cargo_used", 0) or 0)
            cargo_max = int(getattr(bunker, "cargo_max", 4) or 4)
            if cargo_used >= cargo_max:
                continue
            if min(float(bunker.distance_to(top)), float(bunker.distance_to(bot.start_location))) > float(_MAIN_RAMP_BUNKER_RADIUS):
                continue
            out.append(bunker)
        except Exception:
            continue
    return out


def _anchor_bunkers(bot, *, anchor: Point2, radius: float = 14.0) -> list:
    """Retorna bunkers prontos com espaço dentro do raio do anchor (excluindo bunkers da rampa principal)."""
    top = _main_ramp_top(bot)
    out = []
    for bunker in list(getattr(bot, "structures", []) or []):
        try:
            if getattr(bunker, "type_id", None) != U.BUNKER:
                continue
            if not bool(getattr(bunker, "is_ready", False)):
                continue
            cargo_used = int(getattr(bunker, "cargo_used", 0) or 0)
            cargo_max = int(getattr(bunker, "cargo_max", 4) or 4)
            if cargo_used >= cargo_max:
                continue
            if float(bunker.distance_to(anchor)) > float(radius):
                continue
            # Exclui bunkers que pertencem à rampa principal
            if top is not None and float(bunker.distance_to(top)) <= float(_MAIN_RAMP_BUNKER_RADIUS):
                continue
            out.append(bunker)
        except Exception:
            continue
    return out


def _bulk_sector_mode(awareness: Awareness, *, now: float) -> str:
    """Retorna o SectorMode do setor onde o bulk está (bulk_sector da geometria)."""
    geo_snap = awareness.mem.get(K("intel", "geometry", "operational", "snapshot"), now=now, default=None)
    if not isinstance(geo_snap, dict):
        return SectorMode.NONE.value
    bulk_sector = geo_snap.get("bulk_sector")
    if not bulk_sector:
        return SectorMode.NONE.value
    sector_states = geo_snap.get("sector_states") or {}
    if not isinstance(sector_states, dict):
        return SectorMode.NONE.value
    sector = sector_states.get(str(bulk_sector), {})
    if not isinstance(sector, dict):
        return SectorMode.NONE.value
    return str(sector.get("mode", SectorMode.NONE.value) or SectorMode.NONE.value)


def _template_allows_siege(template_str: str) -> bool:
    """Templates em que o bulk deve sentar tanks e burrar mines quando no anchor."""
    return template_str in {
        FrontTemplate.HOLD_MAIN.value,
        FrontTemplate.TURTLE_NAT.value,
        FrontTemplate.STABILIZE_AND_EXPAND.value,
        FrontTemplate.CONTAIN.value,
    }


def _geo_template(awareness: Awareness, *, now: float) -> str:
    geo_snap = awareness.mem.get(K("intel", "geometry", "operational", "snapshot"), now=now, default=None)
    if not isinstance(geo_snap, dict):
        return ""
    return str(geo_snap.get("template", "") or "")


def _territory_tank_slots(awareness: Awareness, *, now: float, zone_key: str) -> list[Point2]:
    snap = awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
    if not isinstance(snap, dict):
        return []
    zones = snap.get("zones", {})
    if not isinstance(zones, dict):
        return []
    zone = zones.get(str(zone_key), {})
    if not isinstance(zone, dict):
        return []
    out: list[Point2] = []
    for slot in list(zone.get("active_slots", []) or []):
        if not isinstance(slot, dict):
            continue
        if str(slot.get("role", "") or "") not in {"siege_anchor", "fallback_anchor"}:
            continue
        pos = _point_from_payload(slot.get("position"))
        if pos is None:
            continue
        out.append(pos)
    return out


def _territory_role_slots(awareness: Awareness, *, now: float, zone_key: str, roles: set[str]) -> list[Point2]:
    snap = awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
    if not isinstance(snap, dict):
        return []
    zones = snap.get("zones", {})
    if not isinstance(zones, dict):
        return []
    zone = zones.get(str(zone_key), {})
    if not isinstance(zone, dict):
        return []
    out: list[Point2] = []
    for slot in list(zone.get("active_slots", []) or []):
        if not isinstance(slot, dict):
            continue
        if str(slot.get("role", "") or "") not in roles:
            continue
        pos = _point_from_payload(slot.get("position"))
        if pos is None:
            continue
        out.append(pos)
    return out


def _territory_zone_point(awareness: Awareness, *, now: float, zone_key: str, field: str) -> Point2 | None:
    snap = awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
    if not isinstance(snap, dict):
        return None
    zones = snap.get("zones", {})
    if not isinstance(zones, dict):
        return None
    zone = zones.get(str(zone_key), {})
    if not isinstance(zone, dict):
        return None
    return _point_from_payload(zone.get(str(field)))


def _best_zone_for_anchor(awareness: Awareness, *, now: float, anchor: Point2) -> str | None:
    snap = awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}
    if not isinstance(snap, dict):
        return None
    zones = snap.get("zones", {})
    if not isinstance(zones, dict):
        return None
    best_key = None
    best_dist = 9999.0
    for zone_key in ("main_ramp", "natural_front", "third_front"):
        zone = zones.get(zone_key, {})
        if not isinstance(zone, dict):
            continue
        refs = [
            _point_from_payload(zone.get("center")),
            _point_from_payload(zone.get("front_anchor")),
            _point_from_payload(zone.get("fallback_anchor")),
        ]
        refs = [pos for pos in refs if pos is not None]
        if not refs:
            continue
        try:
            dist = min(float(anchor.distance_to(pos)) for pos in refs)
        except Exception:
            continue
        if dist < best_dist:
            best_dist = dist
            best_key = str(zone_key)
    return best_key


def _assign_tank_slots(tanks, slots: list[Point2], *, limit: int) -> dict[int, Point2]:
    if not slots or limit <= 0:
        return {}
    remaining_slots = list(slots[: max(0, int(limit))])
    assignments: dict[int, Point2] = {}
    sortable = []
    for tank in list(tanks or []):
        try:
            nearest = min(float(tank.distance_to(slot)) for slot in remaining_slots)
        except Exception:
            nearest = 9999.0
        sortable.append((nearest, int(getattr(tank, "tag", 0) or 0), tank))
    sortable.sort(key=lambda item: (item[0], item[1]))
    for _nearest, tag, tank in sortable:
        if not remaining_slots:
            break
        try:
            best_slot = min(remaining_slots, key=lambda slot: float(tank.distance_to(slot)))
        except Exception:
            best_slot = remaining_slots[0]
        assignments[int(tag)] = best_slot
        remaining_slots.remove(best_slot)
    return assignments


def _main_ramp_enemy_pressure(bot) -> bool:
    top = _main_ramp_top(bot)
    if top is None:
        return False
    for enemy in list(getattr(bot, "enemy_units", []) or []):
        try:
            if bool(getattr(enemy, "is_flying", False)):
                continue
            if float(enemy.distance_to(top)) <= 12.0 or float(enemy.distance_to(bot.start_location)) <= 14.0:
                return True
        except Exception:
            continue
    return False


@dataclass
class HoldAnchorTask(BaseTask):
    """
    Hold the current operational posture anchor.
    The anchor is read from awareness each tick and is not fixed at creation time.
    """

    awareness: Awareness
    log: DevLogger | None = None
    log_every_iters: int = 15
    _iters: int = field(default=0, init=False, repr=False)
    _tank_anchor_cache: dict[int, Point2] = field(default_factory=dict, init=False, repr=False)

    def __init__(self, *, awareness: Awareness, log: DevLogger | None = None, log_every_iters: int = 15):
        super().__init__(task_id="hold_anchor", domain="MAP_CONTROL", commitment=86)
        self.awareness = awareness
        self.log = log
        self.log_every_iters = int(log_every_iters)
        self._iters = 0
        self._tank_anchor_cache = {}

    def _prune_tank_anchor_cache(self, *, live_tags: set[int]) -> None:
        self._tank_anchor_cache = {
            int(tag): pos
            for tag, pos in dict(self._tank_anchor_cache).items()
            if int(tag) in live_tags
        }

    def _stable_tank_anchor(self, *, unit, computed_anchor: Point2, replace_distance: float) -> Point2:
        tag = int(getattr(unit, "tag", 0) or 0)
        cached = self._tank_anchor_cache.get(tag)
        if cached is None:
            self._tank_anchor_cache[tag] = computed_anchor
            return computed_anchor
        try:
            if float(cached.distance_to(computed_anchor)) > float(replace_distance):
                self._tank_anchor_cache[tag] = computed_anchor
                return computed_anchor
        except Exception:
            self._tank_anchor_cache[tag] = computed_anchor
            return computed_anchor
        return cached

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        self._iters += 1
        now = float(tick.time)

        guard = self.require_mission_bound(min_tags=1)
        if guard is not None:
            return guard

        posture_snap = self.awareness.mem.get(K("strategy", "army", "snapshot"), now=now, default={}) or {}
        if not isinstance(posture_snap, dict):
            posture_snap = {}
        army_control_snap = self.awareness.mem.get(K("ops", "army_control", "snapshot"), now=now, default={}) or {}
        if not isinstance(army_control_snap, dict):
            army_control_snap = {}

        anchor = _point_from_payload(army_control_snap.get("primary_anchor")) or _point_from_payload(posture_snap.get("anchor"))
        posture_str = str(posture_snap.get("posture", "HOLD_MAIN_RAMP") or "HOLD_MAIN_RAMP")
        nat_landing_target, nat_landing_fallback = _nat_landing_reservation(self.awareness, now=now)
        nat_reserved_sites, nat_reserved_fallback = _nat_reserved_sites(self.awareness, bot, now=now)
        main_ramp_bunkers = _main_ramp_bunkers(bot)
        main_ramp_pressure = _main_ramp_enemy_pressure(bot)
        anchor_bunkers = _anchor_bunkers(bot, anchor=anchor) if anchor is not None else []
        # Keep at most one tank on the main-ramp highground while holding the nat.
        # More than that can clog the main and soft-lock pathing for the army.
        ramp_top = _main_ramp_top(bot)
        nat_defense_postures = {
            ArmyPosture.HOLD_NAT_CHOKE.value,
            ArmyPosture.SECURE_NAT.value,
            ArmyPosture.CONTROLLED_RETAKE.value,
        }
        _NAT_TANK_HIGHGROUND_MAX = 1
        _MAIN_HOLD_TANK_MAX = 1
        # Lê modo do setor bulk e template para decidir siege/burrow
        bulk_sector_mode_str = _bulk_sector_mode(self.awareness, now=now)
        geo_template_str = _geo_template(self.awareness, now=now)
        # Bulk deve sentar/burrar quando no modo de hold (não em push)
        bulk_hold_modes = {SectorMode.MASS_HOLD.value, SectorMode.HEAVY_ANCHOR.value, SectorMode.ANCHOR.value}
        bulk_in_hold = bulk_sector_mode_str in bulk_hold_modes
        # Template permite siege? (não quando prep_push — nesse caso o bulk está mobile)
        template_siege_ok = _template_allows_siege(geo_template_str) if geo_template_str else True
        # Siege ativo: bulk parado num setor de hold com template defensivo
        bulk_siege_active = bulk_in_hold and template_siege_ok

        if anchor is None:
            return TaskResult.noop("no_anchor_defined")

        assigned_set = set(int(t) for t in self.assigned_tags)
        bulk = bot.units.filter(lambda u: int(u.tag) in assigned_set)
        self._prune_tank_anchor_cache(
            live_tags={
                int(getattr(u, "tag", 0) or 0)
                for u in list(bulk.of_type({U.SIEGETANK, U.SIEGETANKSIEGED}) or [])
            }
        )

        if bulk.amount == 0:
            return TaskResult.failed("assigned_units_gone")

        medivacs = bulk.of_type({U.MEDIVAC})
        mobile = bulk - medivacs
        slow = mobile.of_type(_SLOW_POSITIONAL)
        fast = mobile - slow

        # Assign highground tags: up to _NAT_TANK_HIGHGROUND_MAX siege tanks go to ramp_top
        # when defending the nat. Sorted by distance to ramp_top (closest first).
        highground_tank_tags: set[int] = set()
        if (
            posture_str in nat_defense_postures
            and ramp_top is not None
        ):
            tanks = slow.of_type({U.SIEGETANK, U.SIEGETANKSIEGED})
            sorted_tanks = sorted(tanks, key=lambda u: float(u.distance_to(ramp_top)))
            for t in sorted_tanks[:_NAT_TANK_HIGHGROUND_MAX]:
                highground_tank_tags.add(int(t.tag))

        main_hold_tank_anchors: dict[int, Point2] = {}
        main_zone_center = anchor
        main_zone_fallback = anchor
        main_hold_reserve_anchor = anchor
        if posture_str == ArmyPosture.HOLD_MAIN_RAMP.value:
            main_zone_center = _territory_zone_point(
                self.awareness,
                now=now,
                zone_key="main_ramp",
                field="center",
            ) or anchor
            main_zone_fallback = _territory_zone_point(
                self.awareness,
                now=now,
                zone_key="main_ramp",
                field="fallback_anchor",
            ) or main_zone_center
            try:
                main_hold_reserve_anchor = main_zone_fallback.towards(
                    bot.start_location,
                    float(_MAIN_RAMP_TANK_RESERVE_RETREAT),
                )
            except Exception:
                main_hold_reserve_anchor = main_zone_fallback
            main_hold_reserve_anchor = _clamp_main_ramp_tank_anchor(
                bot,
                anchor=main_hold_reserve_anchor,
                fallback=main_zone_center,
            )
            main_tank_slots = _territory_role_slots(
                self.awareness,
                now=now,
                zone_key="main_ramp",
                roles={"siege_anchor", "fallback_anchor"},
            )
            if main_tank_slots:
                tanks = slow.of_type({U.SIEGETANK, U.SIEGETANKSIEGED})
                main_hold_tank_anchors = _assign_tank_slots(
                    tanks,
                    main_tank_slots,
                    limit=min(_MAIN_HOLD_TANK_MAX, len(main_tank_slots)),
                )

        mine_zone_key = None
        if posture_str == ArmyPosture.HOLD_MAIN_RAMP.value:
            mine_zone_key = "main_ramp"
        elif posture_str in nat_defense_postures:
            mine_zone_key = "natural_front"
        else:
            mine_zone_key = _best_zone_for_anchor(self.awareness, now=now, anchor=anchor)
        bulk_mine_slots = (
            _territory_role_slots(self.awareness, now=now, zone_key=mine_zone_key, roles=_MINE_SLOT_ROLES)
            if mine_zone_key is not None
            else []
        )
        mine_units = slow.of_type({U.WIDOWMINE, U.WIDOWMINEBURROWED})
        mine_slot_by_tag = _assign_tank_slots(
            mine_units,
            bulk_mine_slots,
            limit=min(len(bulk_mine_slots), int(mine_units.amount)),
        )

        issued = 0

        for unit in fast:
            try:
                if unit.type_id == U.MARINE and main_ramp_pressure and main_ramp_bunkers:
                    bunker = min(main_ramp_bunkers, key=lambda b: float(unit.distance_to(b)))
                    already_loading = False
                    try:
                        for order in list(getattr(unit, "orders", []) or []):
                            ab = getattr(getattr(order, "ability", None), "id", None)
                            if ab is not None and "LOAD" in str(ab).upper():
                                already_loading = True
                                break
                    except Exception:
                        pass
                    if not already_loading:
                        if float(unit.distance_to(bunker)) <= 8.0:
                            unit(AbilityId.SMART, bunker)
                        else:
                            unit.move(bunker.position)
                        issued += 1
                    continue
                if unit.type_id == U.MARINE and anchor_bunkers:
                    bunker = min(anchor_bunkers, key=lambda b: float(unit.distance_to(b)))
                    already_loading = False
                    try:
                        for order in list(getattr(unit, "orders", []) or []):
                            ab = getattr(getattr(order, "ability", None), "id", None)
                            if ab is not None and "LOAD" in str(ab).upper():
                                already_loading = True
                                break
                    except Exception:
                        pass
                    if not already_loading:
                        if float(unit.distance_to(bunker)) <= 8.0:
                            unit(AbilityId.SMART, bunker)
                        else:
                            unit.move(bunker.position)
                        issued += 1
                    continue
                reserved_site = None
                for site in nat_reserved_sites:
                    if float(unit.distance_to(site)) <= 2.6:
                        reserved_site = site
                        break
                if reserved_site is not None:
                    retreat = nat_reserved_fallback or nat_landing_fallback or anchor
                    if float(unit.distance_to(retreat)) > 1.5:
                        unit.move(retreat)
                    else:
                        unit.attack(retreat)
                    issued += 1
                    continue
                if nat_landing_target is not None and float(unit.distance_to(nat_landing_target)) <= 4.75:
                    retreat = nat_landing_fallback or anchor
                    if float(unit.distance_to(retreat)) > 1.5:
                        unit.move(retreat)
                    else:
                        unit.attack(retreat)
                    issued += 1
                    continue

                dist = float(unit.distance_to(anchor))
                if dist > float(_AT_ANCHOR_RADIUS):
                    unit.move(anchor)
                    issued += 1
                elif not bool(getattr(unit, "is_attacking", False)):
                    unit.attack(anchor)
                    issued += 1
            except Exception:
                continue

        for unit in slow:
            try:
                reserved_site = None
                for site in nat_reserved_sites:
                    if float(unit.distance_to(site)) <= 2.6:
                        reserved_site = site
                        break
                if reserved_site is not None:
                    retreat = nat_reserved_fallback or nat_landing_fallback or anchor
                    if unit.type_id == U.SIEGETANKSIEGED:
                        unit(AbilityId.UNSIEGE_UNSIEGE)
                        issued += 1
                        continue
                    if unit.type_id == U.WIDOWMINEBURROWED:
                        unit(AbilityId.BURROWUP_WIDOWMINE)
                        issued += 1
                        continue
                    if float(unit.distance_to(retreat)) > 1.5:
                        unit.move(retreat)
                        issued += 1
                    continue
                if nat_landing_target is not None and float(unit.distance_to(nat_landing_target)) <= 4.9:
                    if unit.type_id == U.SIEGETANKSIEGED:
                        unit(AbilityId.UNSIEGE_UNSIEGE)
                        issued += 1
                        continue
                    if unit.type_id == U.WIDOWMINEBURROWED:
                        unit(AbilityId.BURROWUP_WIDOWMINE)
                        issued += 1
                        continue
                    retreat = nat_landing_fallback or anchor
                    if float(unit.distance_to(retreat)) > 1.5:
                        unit.move(retreat)
                        issued += 1
                    continue

                # Widowmines burrowed: desenterrar se bulk em modo de push ou longe do anchor
                if unit.type_id == U.WIDOWMINEBURROWED:
                    mine_anchor = mine_slot_by_tag.get(int(unit.tag), anchor)
                    dist_burrowed = float(unit.distance_to(mine_anchor))
                    if not bulk_siege_active or dist_burrowed > float(_TANK_UNSIEGE_TO_MOVE_RADIUS):
                        enemy_near_burrowed = bot.enemy_units.closer_than(_TANK_LOCAL_HOLD_RADIUS, unit)
                        if int(enemy_near_burrowed.amount) <= 0:
                            unit(AbilityId.BURROWUP_WIDOWMINE)
                            issued += 1
                    continue

                # Highground tanks: primeiros N tanks ficam no topo da rampa cobrindo a nat.
                if (
                    int(unit.tag) in highground_tank_tags
                    and ramp_top is not None
                ):
                    hg_dist = float(unit.distance_to(ramp_top))
                    is_sieged_hg = unit.type_id == U.SIEGETANKSIEGED
                    if is_sieged_hg:
                        enemy_near = bot.enemy_units.closer_than(_TANK_LOCAL_HOLD_RADIUS, unit)
                        if hg_dist > float(_TANK_UNSIEGE_TO_MOVE_RADIUS) and int(enemy_near.amount) <= 0:
                            unit(AbilityId.UNSIEGE_UNSIEGE)
                            issued += 1
                        continue
                    if hg_dist > float(_SLOW_AT_ANCHOR_RADIUS):
                        unit.move(ramp_top)
                        issued += 1
                        continue
                    # No topo da rampa: siegia para cobrir o choke da nat.
                    if unit.type_id == U.SIEGETANK:
                        enemy_too_close = bot.enemy_units.closer_than(4.0, unit)
                        if int(enemy_too_close.amount) <= 0:
                            unit(AbilityId.SIEGEMODE_SIEGEMODE)
                            issued += 1
                    continue

                # Tanks na postura HOLD_MAIN_RAMP sob pressão devem sentar recuados do
                # topo da rampa — no range de ataque mas fora do alcance inimigo (adeptos, etc.).
                tank_ramp_defense = bool(
                    unit.type_id in {U.SIEGETANK, U.SIEGETANKSIEGED}
                    and posture_str == ArmyPosture.HOLD_MAIN_RAMP.value
                    and main_ramp_pressure
                )
                assigned_main_anchor = main_hold_tank_anchors.get(int(unit.tag))
                main_ramp_tank = bool(
                    unit.type_id in {U.SIEGETANK, U.SIEGETANKSIEGED}
                    and posture_str == ArmyPosture.HOLD_MAIN_RAMP.value
                )
                main_ramp_slot_tank = bool(assigned_main_anchor is not None or not main_hold_tank_anchors)
                reserve_anchor = main_hold_reserve_anchor if main_ramp_tank else anchor
                effective_anchor = assigned_main_anchor or (main_zone_fallback if main_ramp_tank else anchor)
                if main_ramp_tank and not main_ramp_slot_tank:
                    effective_anchor = reserve_anchor
                elif tank_ramp_defense and assigned_main_anchor is None:
                    effective_anchor = reserve_anchor
                if main_ramp_tank:
                    effective_anchor = _clamp_main_ramp_tank_anchor(
                        bot,
                        anchor=effective_anchor,
                        fallback=reserve_anchor,
                    )
                effective_anchor = self._stable_tank_anchor(
                    unit=unit,
                    computed_anchor=effective_anchor,
                    replace_distance=(3.0 if main_ramp_tank else 5.0),
                )
                if main_ramp_tank:
                    effective_anchor = _clamp_main_ramp_tank_anchor(
                        bot,
                        anchor=effective_anchor,
                        fallback=reserve_anchor,
                    )
                    self._tank_anchor_cache[int(getattr(unit, "tag", 0) or 0)] = effective_anchor

                dist = float(unit.distance_to(effective_anchor))
                is_sieged = unit.type_id == U.SIEGETANKSIEGED
                precise_main_ramp_tank = bool(
                    main_ramp_tank and main_ramp_slot_tank
                )
                tank_move_radius = (
                    float(_MAIN_RAMP_TANK_AT_ANCHOR_RADIUS)
                    if precise_main_ramp_tank
                    else float(_SLOW_AT_ANCHOR_RADIUS)
                )
                tank_unsiege_radius = (
                    float(_MAIN_RAMP_TANK_UNSIEGE_TO_MOVE_RADIUS)
                    if main_ramp_tank
                    else float(_TANK_UNSIEGE_TO_MOVE_RADIUS)
                )

                if is_sieged:
                    enemy_near = bot.enemy_units.closer_than(_TANK_LOCAL_HOLD_RADIUS, unit)
                    blocking_main_ramp = bool(
                        main_ramp_tank and not _respects_main_ramp_guards(unit.position, bot=bot)
                    )
                    if (dist > tank_unsiege_radius or blocking_main_ramp) and int(enemy_near.amount) <= 0:
                        unit(AbilityId.UNSIEGE_UNSIEGE)
                        issued += 1
                    continue

                # Widowmines: burrar quando no anchor em modo de hold
                if unit.type_id == U.WIDOWMINE:
                    mine_anchor = mine_slot_by_tag.get(int(unit.tag), anchor)
                    dist = float(unit.distance_to(mine_anchor))
                    if bulk_siege_active and dist <= float(_SLOW_AT_ANCHOR_RADIUS):
                        enemy_too_close = bot.enemy_units.closer_than(4.0, unit)
                        if int(enemy_too_close.amount) <= 0:
                            unit(AbilityId.BURROWDOWN_WIDOWMINE)
                            issued += 1
                    elif dist > float(_SLOW_AT_ANCHOR_RADIUS):
                        unit.move(mine_anchor)
                        issued += 1
                    continue

                if dist > tank_move_radius:
                    unit.move(effective_anchor)
                    issued += 1
                    continue
                if main_ramp_tank and not _respects_main_ramp_guards(unit.position, bot=bot):
                    unit.move(effective_anchor)
                    issued += 1
                    continue

                should_siege = unit.type_id == U.SIEGETANK and (
                    (
                        posture_str == ArmyPosture.HOLD_MAIN_RAMP.value
                        and main_ramp_pressure
                        and main_ramp_slot_tank
                    )
                    or (
                        bulk_siege_active
                        and posture_str == ArmyPosture.HOLD_MAIN_RAMP.value
                        and main_ramp_slot_tank
                    )
                )
                if should_siege:
                    enemy_too_close = bot.enemy_units.closer_than(4.0, unit)
                    if int(enemy_too_close.amount) <= 0:
                        unit(AbilityId.SIEGEMODE_SIEGEMODE)
                        issued += 1
            except Exception:
                continue

        if medivacs.amount > 0 and fast.amount > 0:
            try:
                follow_target = fast.center
                for med in medivacs:
                    med.move(follow_target)
                    issued += 1
            except Exception:
                pass

        if self._iters % self.log_every_iters == 0 and self.log is not None:
            self.log.emit(
                "hold_anchor_tick",
                {
                    "posture": posture_str,
                    "army_control_mode": str(army_control_snap.get("mode", "") or ""),
                    "anchor": {"x": float(anchor.x), "y": float(anchor.y)},
                    "bulk_count": int(bulk.amount),
                    "issued_commands": int(issued),
                },
                meta={"module": "task", "component": "hold_anchor_task"},
            )

        return TaskResult.running("holding_anchor")
