"""
Territorial Control Intel.

Modela a defesa como linhas -> zonas -> slots funcionais.
Publica score de controle por zona e uma linha ativa progressiva:
main_ramp -> natural_front -> third_front.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.intel.geometry.sector_types import SectorId
from bot.mind.awareness import Awareness, K

_WORKERS = {U.SCV, U.PROBE, U.DRONE, U.MULE, U.LARVA, U.EGG}
_POWER = {
    U.MARINE: 1.0,
    U.MARAUDER: 1.45,
    U.REAPER: 1.0,
    U.HELLION: 0.85,
    U.CYCLONE: 1.8,
    U.SIEGETANK: 3.0,
    U.SIEGETANKSIEGED: 4.5,
    U.MEDIVAC: 0.6,
    U.WIDOWMINE: 2.0,
    U.WIDOWMINEBURROWED: 3.2,
    U.THOR: 3.2,
    U.THORAP: 3.2,
    U.BUNKER: 4.0,
    U.PLANETARYFORTRESS: 6.0,
}
_ROLE_UNITS = {
    "siege_anchor": {U.SIEGETANK, U.SIEGETANKSIEGED},
    "fallback_anchor": {U.SIEGETANK, U.SIEGETANKSIEGED, U.BUNKER},
    "screen_front": {U.MARINE, U.MARAUDER, U.HELLION, U.CYCLONE, U.THOR, U.THORAP},
    "screen_left": {U.MARINE, U.MARAUDER, U.HELLION, U.CYCLONE},
    "screen_right": {U.MARINE, U.MARAUDER, U.HELLION, U.CYCLONE},
    "mine_choke": {U.WIDOWMINE, U.WIDOWMINEBURROWED},
    "mine_flank_left": {U.WIDOWMINE, U.WIDOWMINEBURROWED},
    "mine_flank_right": {U.WIDOWMINE, U.WIDOWMINEBURROWED},
    "rear_support": {U.MEDIVAC, U.MARINE, U.MARAUDER, U.SCV},
    "vision_spot": {U.MARINE, U.REAPER, U.HELLION},
}


@dataclass(frozen=True)
class TerritorialControlConfig:
    ttl_s: float = 4.0
    zone_radius: float = 14.0
    hold_main_if_below: float = 0.55
    natural_activate_at: float = 0.62
    natural_hold_at: float = 0.50
    third_activate_at: float = 0.74
    third_hold_at: float = 0.60


def _point_payload(pos: Point2 | None) -> dict | None:
    if pos is None:
        return None
    return {"x": float(pos.x), "y": float(pos.y)}


def _point_from_payload(payload, fallback: Point2 | None = None) -> Point2 | None:
    if not isinstance(payload, dict):
        return fallback
    try:
        return Point2((float(payload.get("x", 0.0)), float(payload.get("y", 0.0))))
    except Exception:
        return fallback


def _pathable(bot, pos: Point2 | None) -> bool:
    if pos is None:
        return False
    try:
        return bool(bot.in_pathing_grid(pos))
    except Exception:
        return True


def _safe_point(bot, preferred: Point2 | None, fallback: Point2) -> Point2:
    if preferred is not None and _pathable(bot, preferred):
        return preferred
    return fallback


def _height(bot, pos: Point2 | None) -> float:
    if pos is None or not _pathable(bot, pos):
        return -9999.0
    try:
        return float(bot.get_terrain_z_height(pos))
    except Exception:
        return 0.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _pull_back_towards(target: Point2, home: Point2, *, backoff: float) -> Point2:
    try:
        dist = float(target.distance_to(home))
    except Exception:
        return home
    step = max(0.5, min(float(backoff), max(0.5, dist - 0.5)))
    try:
        return target.towards(home, step)
    except Exception:
        return home


def _main_wall_guard_points(bot) -> list[tuple[Point2, float]]:
    ramp = getattr(bot, "main_base_ramp", None)
    if ramp is None:
        return []
    out: list[tuple[Point2, float]] = []
    top = getattr(ramp, "top_center", None)
    bottom = getattr(ramp, "bottom_center", None)
    if top is not None:
        out.append((top, 8.5))
    if bottom is not None:
        out.append((bottom, 7.5))
    for depot in list(getattr(ramp, "corner_depots", []) or []):
        if depot is not None:
            out.append((depot, 5.75))
    barracks_pos = getattr(ramp, "barracks_correct_placement", None)
    if barracks_pos is not None:
        out.append((barracks_pos, 4.75))
    return out


def _respects_guard_points(
    pos: Point2 | None,
    guards: list[tuple[Point2, float]],
    *,
    slack: float = 0.15,
) -> bool:
    if pos is None:
        return False
    for guarded_point, min_dist in list(guards or []):
        try:
            if float(pos.distance_to(guarded_point)) + float(slack) < float(min_dist):
                return False
        except Exception:
            continue
    return True


def _mineral_line_center(bot, *, base_pos: Point2, radius: float = 10.5) -> Point2:
    try:
        mfs = bot.mineral_field.closer_than(float(radius), base_pos)
    except Exception:
        mfs = None
    if mfs is None or int(getattr(mfs, "amount", 0) or 0) <= 0:
        return base_pos
    try:
        x = sum(float(m.position.x) for m in mfs) / float(mfs.amount)
        y = sum(float(m.position.y) for m in mfs) / float(mfs.amount)
        return Point2((x, y))
    except Exception:
        return base_pos


def _extra_expansion(bot, *, known: list[Point2], reference: Point2) -> Point2 | None:
    try:
        exps = list(getattr(bot, "expansion_locations_list", []) or [])
    except Exception:
        exps = []
    candidates: list[Point2] = []
    for pos in exps:
        if not isinstance(pos, Point2):
            continue
        try:
            if any(float(pos.distance_to(existing)) <= 5.0 for existing in known):
                continue
        except Exception:
            continue
        candidates.append(pos)
    try:
        candidates.sort(key=lambda p: (float(p.distance_to(reference)), float(p.distance_to(bot.start_location))))
    except Exception:
        pass
    return candidates[0] if candidates else None


def _best_main_highground_anchor(
    bot,
    *,
    plateau_ref: Point2,
    preferred: Point2,
    fallback: Point2,
    targets: list[tuple[Point2, float]],
    used: list[Point2] | None = None,
    min_distance_from: list[tuple[Point2, float]] | None = None,
) -> Point2:
    used = list(used or [])
    min_distance_from = list(min_distance_from or [])
    plateau_h = _height(bot, plateau_ref)
    fallback_h = _height(bot, fallback)
    min_height = max(plateau_h, fallback_h) - 0.45
    candidates: list[Point2] = [preferred, fallback, plateau_ref]
    for target, _weight in targets:
        candidates.append(_pull_back_towards(target, plateau_ref, backoff=11.5))
    for radius in (0.0, 1.5, 3.0, 4.5, 6.0):
        steps = 1 if radius <= 0.01 else 16
        for idx in range(steps):
            ang = 0.0 if steps == 1 else (2.0 * math.pi * float(idx)) / float(steps)
            candidates.append(
                Point2(
                    (
                        float(preferred.x) + (float(radius) * math.cos(ang)),
                        float(preferred.y) + (float(radius) * math.sin(ang)),
                    )
                )
            )

    best = fallback
    best_score = -999999.0
    best_guarded: Point2 | None = None
    best_guarded_score = -999999.0
    for candidate in candidates:
        if not _pathable(bot, candidate):
            continue
        cand_h = _height(bot, candidate)
        if cand_h < min_height:
            continue
        score = (cand_h * 0.35) - (0.22 * float(candidate.distance_to(preferred)))
        respects_guards = _respects_guard_points(candidate, min_distance_from) if min_distance_from else True
        for guarded_point, min_dist in min_distance_from:
            dist_guard = float(candidate.distance_to(guarded_point))
            if dist_guard < float(min_dist):
                score -= 28.0 + ((float(min_dist) - dist_guard) * 9.0)
        for target, weight in targets:
            dist = float(candidate.distance_to(target))
            if dist <= 13.25:
                score += 6.0 * float(weight)
            elif dist <= 16.5:
                score += max(0.0, (16.5 - dist)) * 0.9 * float(weight)
            else:
                score -= (dist - 16.5) * 0.08 * float(weight)
        for other in used:
            other_dist = float(candidate.distance_to(other))
            if other_dist < 2.75:
                score -= 6.0
            elif other_dist < 4.5:
                score -= (4.5 - other_dist) * 1.25
        if score > best_score:
            best = candidate
            best_score = score
        if respects_guards and score > best_guarded_score:
            best_guarded = candidate
            best_guarded_score = score
    return best_guarded or best


def _main_wall_preferred_anchors(
    bot,
    *,
    main_center: Point2,
    fallback: Point2,
    nat_center: Point2 | None,
) -> tuple[list[Point2], Point2 | None]:
    ramp = getattr(bot, "main_base_ramp", None)
    top = getattr(ramp, "top_center", None) if ramp is not None else None
    bottom = getattr(ramp, "bottom_center", None) if ramp is not None else None
    guards = _main_wall_guard_points(bot)
    if top is None:
        base = _safe_point(bot, fallback, main_center)
        return [
            base,
            _safe_point(bot, _offset_perp(base, main_center, side=2.35), base),
            _safe_point(bot, _offset_perp(base, main_center, side=-2.35), base),
        ], None

    # O core precisa ficar atras da wall, alguns tiles longe dos depots/barracks.
    # no highground atrás da wall, longe do corredor de saída para a nat.
    try:
        core = _safe_point(bot, top.towards(main_center, 11.5), fallback)
    except Exception:
        core = _safe_point(bot, fallback, main_center)
    for backoff in (9.75, 10.5, 11.25, 12.0):
        try:
            candidate = top.towards(main_center, backoff)
        except Exception:
            candidate = fallback
        candidate = _safe_point(bot, candidate, fallback)
        if _respects_guard_points(candidate, guards):
            core = candidate
            break

    if bottom is None:
        return [
            core,
            _safe_point(bot, _offset_perp(core, main_center, side=2.35), core),
            _safe_point(bot, _offset_perp(core, main_center, side=-2.35), core),
        ], top

    nat_side = 1.0
    if nat_center is not None:
        try:
            left = _offset_perp(core, bottom, side=2.0)
            right = _offset_perp(core, bottom, side=-2.0)
            nat_side = 1.0 if float(left.distance_to(nat_center)) <= float(right.distance_to(nat_center)) else -1.0
        except Exception:
            nat_side = 1.0

    nat_cover = _safe_point(
        bot,
        _offset_perp(core, bottom, forward=0.15, side=2.5 * nat_side),
        core,
    )
    third_cover = _safe_point(
        bot,
        _offset_perp(core, bottom, forward=-0.25, side=-2.5 * nat_side),
        core,
    )
    return [core, nat_cover, third_cover], top


def _power_near(units: list, *, center: Point2, radius: float) -> float:
    total = 0.0
    for unit in list(units or []):
        try:
            if unit.type_id in _WORKERS:
                continue
            if not bool(getattr(unit, "is_ready", True)):
                continue
            if float(unit.distance_to(center)) <= float(radius):
                total += float(_POWER.get(unit.type_id, 0.8))
        except Exception:
            continue
    return float(total)


def _offset_perp(origin: Point2, target: Point2, *, forward: float = 0.0, side: float = 0.0) -> Point2:
    dx = float(target.x) - float(origin.x)
    dy = float(target.y) - float(origin.y)
    norm = math.hypot(dx, dy)
    if norm <= 0.001:
        return origin
    ux, uy = dx / norm, dy / norm
    px, py = -uy, ux
    return Point2((float(origin.x) + ux * float(forward) + px * float(side), float(origin.y) + uy * float(forward) + py * float(side)))


def _slot(name: str, role: str, pos: Point2, priority: float, *, radius: float = 2.5, critical: bool = False) -> dict:
    return {
        "name": str(name),
        "role": str(role),
        "position": _point_payload(pos),
        "priority": float(priority),
        "radius": float(radius),
        "critical": bool(critical),
    }


def _build_main_slots(*, fallback: Point2, front: Point2, tank_anchors: list[Point2] | None = None) -> list[dict]:
    anchors = list(tank_anchors or [])
    primary = anchors[0] if len(anchors) >= 1 else fallback
    cover_nat = anchors[1] if len(anchors) >= 2 else _offset_perp(primary, front, side=2.0)
    cover_third = anchors[2] if len(anchors) >= 3 else _offset_perp(primary, front, side=-2.4)
    return [
        _slot("main_tank_core", "siege_anchor", primary, 0.98, radius=2.8, critical=True),
        _slot("main_tank_nat_cover", "fallback_anchor", cover_nat, 0.90, radius=2.8, critical=True),
        _slot("main_tank_third_cover", "fallback_anchor", cover_third, 0.82, radius=2.8),
        _slot("main_screen_front", "screen_front", _offset_perp(primary, front, forward=2.2), 0.82, critical=True),
        _slot("main_screen_left", "screen_left", _offset_perp(primary, front, forward=1.6, side=-2.0), 0.72),
        _slot("main_screen_right", "screen_right", _offset_perp(primary, front, forward=1.6, side=2.0), 0.72),
        _slot("main_mine_ramp", "mine_choke", _offset_perp(primary, front, forward=1.1), 0.62, radius=2.2, critical=True),
        _slot("main_mine_nat_lane", "mine_flank_left", _offset_perp(cover_nat, front, forward=0.6, side=1.2), 0.54, radius=2.1),
        _slot("main_mine_third_lane", "mine_flank_right", _offset_perp(cover_third, front, forward=0.6, side=-1.2), 0.50, radius=2.1),
        _slot("main_support", "rear_support", _offset_perp(primary, front, forward=-1.6), 0.52, radius=3.0),
    ]


def _build_natural_slots(*, fallback: Point2, front: Point2) -> list[dict]:
    mine_choke = _offset_perp(front, fallback, forward=0.45)
    return [
        _slot("nat_tank_front", "siege_anchor", fallback, 0.97, radius=2.8, critical=True),
        _slot("nat_tank_rear", "fallback_anchor", _offset_perp(fallback, front, forward=-1.2), 0.86, radius=2.8, critical=True),
        _slot("nat_screen_front", "screen_front", front, 0.90, critical=True),
        _slot("nat_screen_left", "screen_left", _offset_perp(front, fallback, side=-3.0), 0.78),
        _slot("nat_screen_right", "screen_right", _offset_perp(front, fallback, side=3.0), 0.78),
        _slot("nat_mine_choke", "mine_choke", mine_choke, 0.66, radius=2.1, critical=True),
        _slot("nat_mine_left", "mine_flank_left", _offset_perp(mine_choke, fallback, side=-2.4), 0.58, radius=2.0),
        _slot("nat_mine_right", "mine_flank_right", _offset_perp(mine_choke, fallback, side=2.4), 0.54, radius=2.0),
        _slot("nat_support", "rear_support", _offset_perp(fallback, front, forward=-2.0), 0.55, radius=3.0),
        _slot("nat_vision", "vision_spot", _offset_perp(front, fallback, forward=2.0), 0.48, radius=2.2),
    ]


def _build_third_slots(*, fallback: Point2, front: Point2) -> list[dict]:
    mine_choke = _offset_perp(front, fallback, forward=0.55)
    return [
        _slot("third_tank_front", "siege_anchor", fallback, 0.94, radius=2.8, critical=True),
        _slot("third_tank_rear", "fallback_anchor", _offset_perp(fallback, front, forward=-1.4), 0.80, radius=2.8),
        _slot("third_screen_front", "screen_front", front, 0.84, critical=True),
        _slot("third_screen_left", "screen_left", _offset_perp(front, fallback, side=-2.8), 0.70),
        _slot("third_screen_right", "screen_right", _offset_perp(front, fallback, side=2.8), 0.70),
        _slot("third_mine_choke", "mine_choke", mine_choke, 0.58, radius=2.1, critical=True),
        _slot("third_mine_left", "mine_flank_left", _offset_perp(mine_choke, fallback, side=-2.2), 0.50, radius=2.0),
        _slot("third_mine_right", "mine_flank_right", _offset_perp(mine_choke, fallback, side=2.2), 0.46, radius=2.0),
        _slot("third_support", "rear_support", _offset_perp(fallback, front, forward=-2.2), 0.48, radius=3.0),
    ]


def _occupied_score(bot, *, slot: dict) -> float:
    pos = _point_from_payload(slot.get("position"))
    if pos is None:
        return 0.0
    role = str(slot.get("role", "") or "")
    allowed = _ROLE_UNITS.get(role, set())
    radius = float(slot.get("radius", 2.5) or 2.5)
    for unit in list(getattr(bot, "units", []) or []) + list(getattr(bot, "structures", []) or []):
        try:
            if allowed and getattr(unit, "type_id", None) not in allowed:
                continue
            if not bool(getattr(unit, "is_ready", True)):
                continue
            if float(unit.distance_to(pos)) <= radius:
                return 1.0
        except Exception:
            continue
    return 0.0


def _zone_status(
    bot,
    *,
    zone_id: str,
    center: Point2,
    front: Point2,
    fallback: Point2,
    slots: list[dict],
    cfg: TerritorialControlConfig,
) -> dict:
    friendly_power = _power_near(list(getattr(bot, "units", []) or []) + list(getattr(bot, "structures", []) or []), center=center, radius=float(cfg.zone_radius))
    enemy_power = _power_near(list(getattr(bot, "enemy_units", []) or []) + list(getattr(bot, "enemy_structures", []) or []), center=center, radius=float(cfg.zone_radius))
    slot_weights = sum(float(s.get("priority", 0.5) or 0.5) for s in slots) or 1.0
    occupied_weight = 0.0
    critical_weight = 0.0
    critical_occupied = 0.0
    missing_roles: dict[str, float] = {}
    for slot in slots:
        weight = float(slot.get("priority", 0.5) or 0.5)
        occ = _occupied_score(bot, slot=slot)
        occupied_weight += weight * occ
        if bool(slot.get("critical", False)):
            critical_weight += weight
            critical_occupied += weight * occ
        if occ < 0.5:
            role = str(slot.get("role", "") or "unknown")
            missing_roles[role] = round(float(missing_roles.get(role, 0.0)) + weight, 3)
    occupied_ratio = _clamp01(occupied_weight / slot_weights)
    critical_ratio = _clamp01(critical_occupied / max(critical_weight, 0.001))
    siege_total = sum(float(s.get("priority", 0.0) or 0.0) for s in slots if str(s.get("role", "")).endswith("anchor")) or 1.0
    siege_occ = sum(
        float(s.get("priority", 0.0) or 0.0) * _occupied_score(bot, slot=s)
        for s in slots if str(s.get("role", "")).endswith("anchor")
    )
    choke_denial = _clamp01(siege_occ / siege_total)
    flank_need = [
        s for s in slots if str(s.get("role", "") or "") in {"screen_left", "screen_right", "vision_spot"}
    ]
    flank_occ = sum(_occupied_score(bot, slot=s) for s in flank_need)
    flank_exposure = 1.0 - _clamp01(flank_occ / max(1, len(flank_need)))
    reinforce_advantage = _clamp01(1.0 - (float(center.distance_to(bot.start_location)) / 35.0))
    vision_control = _clamp01(1.0 - (0.5 * flank_exposure))
    friendly_norm = _clamp01(friendly_power / 12.0)
    enemy_norm = _clamp01(enemy_power / 10.0)
    control_score = _clamp01(
        (0.35 * friendly_norm)
        + (0.25 * occupied_ratio)
        + (0.20 * reinforce_advantage)
        + (0.10 * vision_control)
        + (0.10 * choke_denial)
        - (0.40 * enemy_norm)
        - (0.15 * flank_exposure)
    )
    return {
        "zone_id": str(zone_id),
        "center": _point_payload(center),
        "front_anchor": _point_payload(front),
        "fallback_anchor": _point_payload(fallback),
        "control_score": float(round(control_score, 3)),
        "threat_score": float(round(enemy_norm, 3)),
        "friendly_power": float(round(friendly_power, 3)),
        "enemy_power": float(round(enemy_power, 3)),
        "occupied_critical_slots_ratio": float(round(critical_ratio, 3)),
        "occupied_slots_ratio": float(round(occupied_ratio, 3)),
        "reinforce_advantage": float(round(reinforce_advantage, 3)),
        "vision_control": float(round(vision_control, 3)),
        "choke_denial": float(round(choke_denial, 3)),
        "flank_exposure": float(round(flank_exposure, 3)),
        "missing_roles": dict(sorted(missing_roles.items(), key=lambda item: item[1], reverse=True)),
        "active_slots": list(slots),
        "is_stable": bool(control_score >= 0.7 and critical_ratio >= 0.66 and enemy_norm <= 0.45),
    }


def derive_territorial_control_intel(
    bot,
    *,
    awareness: Awareness,
    now: float,
    cfg: TerritorialControlConfig = TerritorialControlConfig(),
) -> None:
    nat_snap = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
    main_snap = awareness.mem.get(K("intel", "frontline", "main", "snapshot"), now=now, default={}) or {}
    nat_frontline = awareness.mem.get(K("intel", "frontline", "nat", "snapshot"), now=now, default={}) or {}
    geo_snap = awareness.mem.get(K("intel", "geometry", "operational", "snapshot"), now=now, default={}) or {}
    prev = awareness.mem.get(K("intel", "territory", "defense", "snapshot"), now=now, default={}) or {}

    main_center = getattr(bot, "start_location", None) or Point2((0.0, 0.0))
    main_fallback = _safe_point(bot, _point_from_payload(main_snap.get("fallback_anchor")), main_center)
    main_front = _safe_point(bot, _point_from_payload(main_snap.get("forward_anchor"), fallback=main_fallback), main_fallback)

    nat_center = _point_from_payload(nat_snap.get("target"))
    if nat_center is None:
        try:
            nat_center = bot.mediator.get_own_nat
        except Exception:
            nat_center = main_center
    nat_fallback = _safe_point(bot, _point_from_payload(nat_snap.get("staging"), fallback=nat_center), nat_center)
    nat_front = _safe_point(
        bot,
        _point_from_payload(nat_snap.get("hold"), fallback=_point_from_payload(nat_frontline.get("forward_anchor"), fallback=nat_center)),
        nat_center,
    )

    third_anchor = None
    sector_states = (geo_snap.get("sector_states") or {}) if isinstance(geo_snap, dict) else {}
    third_sector = sector_states.get(SectorId.THIRD_ENTRY.value, {}) if isinstance(sector_states, dict) else {}
    if isinstance(third_sector, dict):
        third_anchor = _point_from_payload(third_sector.get("anchor_pos"))
    registry = awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
    if third_anchor is None and isinstance(registry, dict):
        third_entry = registry.get("THIRD", {})
        if isinstance(third_entry, dict):
            third_anchor = _point_from_payload(third_entry.get("current_pos")) or _point_from_payload(third_entry.get("intended_pos"))
    if third_anchor is None:
        third_anchor = _offset_perp(nat_center, main_center, forward=-7.0)
    third_center = third_anchor
    third_fallback = _safe_point(bot, _offset_perp(third_center, nat_center, forward=2.0), nat_center)
    third_front = _safe_point(bot, third_center, third_fallback)
    nat_mineral = _mineral_line_center(bot, base_pos=nat_center)
    third_mineral = _mineral_line_center(bot, base_pos=third_center)
    fourth_center = _extra_expansion(bot, known=[main_center, nat_center, third_center], reference=third_center)
    fourth_mineral = _mineral_line_center(bot, base_pos=fourth_center) if fourth_center is not None else None

    wall_tank_pref, ramp_top = _main_wall_preferred_anchors(
        bot,
        main_center=main_center,
        fallback=main_fallback,
        nat_center=nat_center,
    )
    main_tank_anchors: list[Point2] = []
    # Mantém tanks afastados do topo da rampa (7.0) e do fundo da rampa (6.5).
    # Isso evita que tanks bloqueiem o corredor de saída principal → nat.
    main_ramp_guard = _main_wall_guard_points(bot)
    main_tank_specs = [
        (
            wall_tank_pref[0],
            [(main_front, 1.0), (nat_mineral, 1.0), (nat_center, 0.4)],
        ),
        (
            wall_tank_pref[1],
            [(main_front, 0.9), (nat_mineral, 1.0), (third_mineral, 0.55), (nat_center, 0.7)],
        ),
        (
            wall_tank_pref[2],
            [(main_front, 0.8), (third_mineral, 1.0), (third_center, 0.8)] + ([(fourth_mineral, 0.55)] if fourth_mineral is not None else []),
        ),
    ]
    for preferred, targets in main_tank_specs:
        anchor = _best_main_highground_anchor(
            bot,
            plateau_ref=main_center,
            preferred=preferred,
            fallback=main_fallback,
            targets=targets,
            used=main_tank_anchors,
            min_distance_from=main_ramp_guard,
        )
        main_tank_anchors.append(anchor)

    zones = {
        "main_ramp": _zone_status(
            bot,
            zone_id="main_ramp",
            center=main_fallback,
            front=main_front,
            fallback=main_fallback,
            slots=_build_main_slots(fallback=main_fallback, front=main_front, tank_anchors=main_tank_anchors),
            cfg=cfg,
        ),
        "natural_front": _zone_status(
            bot,
            zone_id="natural_front",
            center=nat_center,
            front=nat_front,
            fallback=nat_fallback,
            slots=_build_natural_slots(fallback=nat_fallback, front=nat_front),
            cfg=cfg,
        ),
        "third_front": _zone_status(
            bot,
            zone_id="third_front",
            center=third_center,
            front=third_front,
            fallback=third_fallback,
            slots=_build_third_slots(fallback=third_fallback, front=third_front),
            cfg=cfg,
        ),
    }

    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    rush_active = rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
    main_score = float(zones["main_ramp"]["control_score"])
    nat_score = float(zones["natural_front"]["control_score"])
    third_score = float(zones["third_front"]["control_score"])
    nat_stable = bool(zones["natural_front"]["is_stable"])
    third_threat = float(zones["third_front"]["threat_score"])
    army_supply = int(getattr(bot, "supply_army", 0) or 0)
    desired_line = "main_ramp_line"
    if not rush_active and nat_stable and nat_score >= float(cfg.third_activate_at) and third_threat <= 0.35 and army_supply >= 18:
        desired_line = "third_line"
    elif nat_score >= float(cfg.natural_activate_at) or bool(nat_snap.get("should_secure", False)) or bool(nat_snap.get("nat_taken", False)):
        desired_line = "natural_line"
    if main_score < float(cfg.hold_main_if_below):
        desired_line = "main_ramp_line"

    prev_line = str(prev.get("active_line", "main_ramp_line") or "main_ramp_line")
    if prev_line == "third_line" and not rush_active and nat_score >= float(cfg.third_hold_at) and third_score >= float(cfg.third_hold_at):
        active_line = "third_line"
    elif prev_line == "natural_line" and nat_score >= float(cfg.natural_hold_at) and main_score >= float(cfg.hold_main_if_below):
        active_line = "natural_line"
    else:
        active_line = desired_line

    lines = {
        "main_ramp_line": {
            "zones": ["main_ramp"],
            "activation_score": float(round(1.0 - main_score, 3)),
            "hold_score": float(round(main_score, 3)),
            "collapse_risk": float(round(max(zones["main_ramp"]["threat_score"], 1.0 - main_score), 3)),
            "progress_score": float(round(main_score, 3)),
        },
        "natural_line": {
            "zones": ["main_ramp", "natural_front"],
            "activation_score": float(round(nat_score, 3)),
            "hold_score": float(round(min(main_score, nat_score), 3)),
            "collapse_risk": float(round(max(zones["natural_front"]["threat_score"], 1.0 - nat_score), 3)),
            "progress_score": float(round(nat_score, 3)),
        },
        "third_line": {
            "zones": ["natural_front", "third_front"],
            "activation_score": float(round(third_score, 3)),
            "hold_score": float(round(min(nat_score, third_score), 3)),
            "collapse_risk": float(round(max(zones["third_front"]["threat_score"], 1.0 - third_score), 3)),
            "progress_score": float(round(min(nat_score, third_score), 3)),
        },
    }

    snapshot = {
        "updated_at": float(now),
        "active_line": str(active_line),
        "desired_line": str(desired_line),
        "rush_state": str(rush_state),
        "lines": lines,
        "zones": zones,
    }
    awareness.mem.set(K("intel", "territory", "defense", "snapshot"), value=snapshot, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "territory", "defense", "active_line"), value=str(active_line), now=now, ttl=float(cfg.ttl_s))
