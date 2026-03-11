from __future__ import annotations

import math
from typing import Any

from ares.consts import BuildingSize
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.intel.utils.natural_geometry import (
    is_in_natural_descent_nogo,
    sanitize_natural_defense_point,
)


def point_payload(pos: Point2 | None) -> dict[str, float] | None:
    if pos is None:
        return None
    return {"x": float(pos.x), "y": float(pos.y)}


def point_from_payload(payload: Any) -> Point2 | None:
    if not isinstance(payload, dict):
        return None
    try:
        return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
    except Exception:
        return None


def points_payload(points: list[Point2]) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for point in list(points or []):
        payload = point_payload(point)
        if payload is not None:
            out.append(payload)
    return out


def _pathable(bot, pos: Point2 | None) -> bool:
    if pos is None:
        return False
    try:
        return bool(bot.in_pathing_grid(pos))
    except Exception:
        return True


def _can_place(bot, *, structure_type: U, pos: Point2 | None) -> bool:
    if pos is None:
        return False
    try:
        return bool(bot.mediator.can_place_structure(position=pos, structure_type=structure_type))
    except Exception:
        return False


def _snap_half(pos: Point2) -> Point2:
    return Point2((math.floor(float(pos.x)) + 0.5, math.floor(float(pos.y)) + 0.5))


def _offset(pos: Point2, *, dx: float = 0.0, dy: float = 0.0) -> Point2:
    return Point2((float(pos.x) + float(dx), float(pos.y) + float(dy)))


def _unit_vector(start: Point2, end: Point2) -> tuple[float, float]:
    dx = float(end.x) - float(start.x)
    dy = float(end.y) - float(start.y)
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return 0.0, 0.0
    return dx / length, dy / length


def _point_along(pos: Point2, *, axis_x: float, axis_y: float, axis_dist: float, lateral: float = 0.0) -> Point2:
    return Point2(
        (
            float(pos.x) + (float(axis_x) * float(axis_dist)) - (float(axis_y) * float(lateral)),
            float(pos.y) + (float(axis_y) * float(axis_dist)) + (float(axis_x) * float(lateral)),
        )
    )


def _terrain_height(bot, pos: Point2 | None) -> float:
    if pos is None:
        return -9999.0
    try:
        return float(bot.get_terrain_z_height(pos))
    except Exception:
        try:
            return float(bot.get_terrain_height(pos))
        except Exception:
            return -9999.0


def _valid_depot_pos(bot, *, nat: Point2, ramp_bottom: Point2 | None, pos: Point2) -> bool:
    if not _can_place(bot, structure_type=U.SUPPLYDEPOT, pos=pos):
        return False
    if not _pathable(bot, pos):
        return False
    try:
        if float(pos.distance_to(nat)) < 4.0 or float(pos.distance_to(nat)) > 11.5:
            return False
    except Exception:
        return False
    if is_in_natural_descent_nogo(bot, pos, nat=nat, clearance=2.75):
        return False
    if ramp_bottom is not None:
        try:
            if float(pos.distance_to(ramp_bottom)) > 7.5:
                return False
        except Exception:
            pass
    return True


def _valid_bunker_pos(bot, *, nat: Point2, ramp_bottom: Point2 | None, pos: Point2) -> bool:
    if not _can_place(bot, structure_type=U.BUNKER, pos=pos):
        return False
    try:
        if float(pos.distance_to(nat)) < 4.5 or float(pos.distance_to(nat)) > 12.5:
            return False
    except Exception:
        return False
    if is_in_natural_descent_nogo(bot, pos, nat=nat, clearance=2.5):
        return False
    if ramp_bottom is not None:
        try:
            pos_h = _terrain_height(bot, pos)
            bottom_h = _terrain_height(bot, ramp_bottom)
            if pos_h < (float(bottom_h) - 0.25):
                return False
        except Exception:
            pass
    return True


def _placement_entry(*, wall: bool, bunker: bool, supply_depot: bool) -> dict[str, Any]:
    return {
        "available": True,
        "has_addon": False,
        "is_wall": bool(wall),
        "building_tag": 0,
        "worker_on_route": False,
        "time_requested": 0.0,
        "production_pylon": False,
        "bunker": bool(bunker),
        "optimal_pylon": False,
        "first_pylon": False,
        "static_defence": False,
        "supply_depot": bool(supply_depot),
        "custom": True,
        "production": False,
        "upgrade_structure": False,
        "missile_turret": False,
        "sensor_tower": False,
        "reaper_wall": False,
    }


def _ensure_base_bucket(bot, *, base_location: Point2) -> dict:
    placements = bot.mediator.get_placements_dict
    if base_location not in placements:
        placements[base_location] = {}
    if BuildingSize.TWO_BY_TWO not in placements[base_location]:
        placements[base_location][BuildingSize.TWO_BY_TWO] = {}
    if BuildingSize.THREE_BY_THREE not in placements[base_location]:
        placements[base_location][BuildingSize.THREE_BY_THREE] = {}
    return placements[base_location]


def _existing_nat_wall(base_bucket: dict) -> tuple[list[Point2], Point2 | None]:
    depots: list[Point2] = []
    bunker_pos: Point2 | None = None
    two_by_two = base_bucket.get(BuildingSize.TWO_BY_TWO, {}) or {}
    three_by_three = base_bucket.get(BuildingSize.THREE_BY_THREE, {}) or {}
    for pos, info in two_by_two.items():
        if isinstance(info, dict) and bool(info.get("is_wall", False)) and bool(info.get("supply_depot", False)):
            depots.append(pos)
    for pos, info in three_by_three.items():
        if not isinstance(info, dict):
            continue
        if not bool(info.get("is_wall", False)):
            continue
        bunker_pos = pos
        if bool(info.get("bunker", False)):
            break
    depots.sort(key=lambda p: (float(p.x), float(p.y)))
    return depots, bunker_pos


def _natural_context(bot, *, nat: Point2) -> tuple[Point2, Point2 | None]:
    try:
        enemy_main = bot.enemy_start_locations[0]
    except Exception:
        enemy_main = nat
    try:
        ramp = getattr(bot, "main_base_ramp", None)
        ramp_bottom = getattr(ramp, "bottom_center", None) if ramp is not None else None
    except Exception:
        ramp_bottom = None
    if ramp_bottom is not None:
        try:
            if float(ramp_bottom.distance_to(nat)) > 22.0:
                ramp_bottom = None
        except Exception:
            ramp_bottom = None
    return enemy_main, ramp_bottom


def solve_nat_wall_layout(bot, *, nat: Point2) -> dict[str, Any]:
    enemy_main, ramp_bottom = _natural_context(bot, nat=nat)
    anchor_seed = nat.towards(enemy_main, 5.5)
    if ramp_bottom is not None:
        anchor_seed = ramp_bottom.towards(enemy_main, 1.25)
    choke_anchor = sanitize_natural_defense_point(
        bot,
        pos=anchor_seed,
        fallback=nat.towards(enemy_main, 5.0),
        prefer_towards=nat.towards(enemy_main, 6.25),
        nat=nat,
        clearance=3.0,
    )
    axis_x, axis_y = _unit_vector(nat, choke_anchor)
    if math.hypot(axis_x, axis_y) <= 1e-6:
        axis_x, axis_y = _unit_vector(nat, enemy_main)
    if math.hypot(axis_x, axis_y) <= 1e-6:
        axis_x, axis_y = 1.0, 0.0

    best: tuple[float, list[Point2], Point2] | None = None
    for center_back in (1.0, 1.5, 2.0, 2.5, 3.0):
        center = _point_along(choke_anchor, axis_x=axis_x, axis_y=axis_y, axis_dist=-center_back)
        for depot_spread in (1.5, 2.0, 1.0, 2.5):
            depot_targets = [
                _snap_half(_point_along(center, axis_x=axis_x, axis_y=axis_y, axis_dist=0.0, lateral=depot_spread)),
                _snap_half(_point_along(center, axis_x=axis_x, axis_y=axis_y, axis_dist=0.0, lateral=-depot_spread)),
            ]
            if any(not _valid_depot_pos(bot, nat=nat, ramp_bottom=ramp_bottom, pos=depot) for depot in depot_targets):
                continue
            try:
                if float(depot_targets[0].distance_to(depot_targets[1])) < 2.2:
                    continue
            except Exception:
                continue
            for bunker_back in (2.5, 3.0, 3.5, 4.0):
                for bunker_lat in (0.0, 1.0, -1.0, 1.5, -1.5):
                    bunker = _snap_half(
                        _point_along(center, axis_x=axis_x, axis_y=axis_y, axis_dist=-bunker_back, lateral=bunker_lat)
                    )
                    if not _valid_bunker_pos(bot, nat=nat, ramp_bottom=ramp_bottom, pos=bunker):
                        continue
                    try:
                        if any(float(bunker.distance_to(depot)) < 2.4 for depot in depot_targets):
                            continue
                    except Exception:
                        continue
                    score = 0.0
                    try:
                        score -= abs(float(center.distance_to(choke_anchor)) - 1.75) * 2.4
                        score -= abs(float(bunker.distance_to(center)) - 3.0) * 1.8
                        score -= sum(abs(float(depot.distance_to(choke_anchor)) - 2.2) for depot in depot_targets)
                        score -= abs(float(depot_targets[0].distance_to(depot_targets[1])) - 3.0) * 2.2
                        score -= float(bunker.distance_to(nat)) * 0.08
                        score -= abs(float(bunker_lat)) * 0.35
                        if ramp_bottom is not None:
                            score -= abs(float(center.distance_to(ramp_bottom)) - 2.0) * 0.55
                    except Exception:
                        score -= 999.0
                    if best is None or float(score) > float(best[0]):
                        best = (float(score), depot_targets, bunker)

    if best is None:
        return {
            "supported": False,
            "source": "nat_fallback_unresolved",
            "depots": [],
            "three_by_three": [],
            "anchor": choke_anchor,
        }
    return {
        "supported": True,
        "source": "nat_fallback",
        "depots": list(best[1]),
        "three_by_three": [best[2]],
        "anchor": choke_anchor,
    }


def ensure_nat_wall_placements(bot, *, nat: Point2) -> dict[str, Any]:
    base_bucket = _ensure_base_bucket(bot, base_location=nat)
    depots, bunker_pos = _existing_nat_wall(base_bucket)
    if depots and bunker_pos is not None:
        return {
            "supported": True,
            "source": "existing",
            "depots": depots,
            "three_by_three": [bunker_pos],
            "anchor": None,
        }

    layout = solve_nat_wall_layout(bot, nat=nat)
    if not bool(layout.get("supported", False)):
        return layout

    for depot in list(layout.get("depots", []) or []):
        base_bucket[BuildingSize.TWO_BY_TWO][depot] = _placement_entry(
            wall=True,
            bunker=False,
            supply_depot=True,
        )
    for pos in list(layout.get("three_by_three", []) or []):
        base_bucket[BuildingSize.THREE_BY_THREE][pos] = _placement_entry(
            wall=True,
            bunker=True,
            supply_depot=False,
        )
    return layout


def solve_perimeter_bunker_position(bot, *, base_pos: Point2, threat_pos: Point2 | None = None) -> Point2 | None:
    try:
        enemy_main = bot.enemy_start_locations[0]
    except Exception:
        enemy_main = None
    focus = threat_pos or enemy_main or base_pos
    axis_x, axis_y = _unit_vector(base_pos, focus)
    if math.hypot(axis_x, axis_y) <= 1e-6:
        axis_x, axis_y = 1.0, 0.0

    best: tuple[float, Point2] | None = None
    for forward in (4.5, 5.0, 5.5, 6.0, 6.5):
        center = _point_along(base_pos, axis_x=axis_x, axis_y=axis_y, axis_dist=forward)
        for lateral in (0.0, 1.5, -1.5, 2.5, -2.5, 3.5, -3.5):
            target = _snap_half(_point_along(center, axis_x=axis_x, axis_y=axis_y, axis_dist=0.0, lateral=lateral))
            if not _can_place(bot, structure_type=U.BUNKER, pos=target):
                continue
            try:
                if float(target.distance_to(base_pos)) < 4.5 or float(target.distance_to(base_pos)) > 11.5:
                    continue
            except Exception:
                continue
            score = 0.0
            try:
                score -= abs(float(target.distance_to(base_pos)) - 6.0) * 1.5
                score -= abs(float(lateral)) * 0.25
                if threat_pos is not None:
                    score -= float(target.distance_to(threat_pos)) * 0.08
                elif enemy_main is not None:
                    score -= float(target.distance_to(enemy_main)) * 0.03
            except Exception:
                score -= 999.0
            if best is None or float(score) > float(best[0]):
                best = (float(score), target)
    return best[1] if best is not None else None
