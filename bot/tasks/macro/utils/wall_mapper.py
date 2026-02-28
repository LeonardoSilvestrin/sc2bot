from __future__ import annotations

from dataclasses import dataclass

from ares.consts import BuildingSize
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2


@dataclass(frozen=True)
class WallDepotPlan:
    base_key: Point2 | None
    slots: tuple[Point2, ...]
    total: int
    occupied: int
    inferred: bool


def resolve_base_key(*, placements: dict, target: Point2, max_snap_distance: float = 7.5) -> Point2 | None:
    if not placements:
        return None
    if target in placements:
        return target
    try:
        key = min(placements.keys(), key=lambda p: float(p.distance_to(target)))
        if float(key.distance_to(target)) > float(max_snap_distance):
            return None
        return key
    except Exception:
        return None


def _mineral_center_near_base(bot, base_location: Point2) -> Point2 | None:
    try:
        minerals = bot.mineral_field.closer_than(11.0, base_location)
        if minerals.amount <= 0:
            return None
        xs = [float(m.position.x) for m in minerals]
        ys = [float(m.position.y) for m in minerals]
        return Point2((sum(xs) / len(xs), sum(ys) / len(ys)))
    except Exception:
        return None


def _infer_natural_slots(bot, *, two_by_two: dict, base_location: Point2, desired_slots: int) -> list[Point2]:
    if not two_by_two:
        return []

    choke_anchor = base_location.towards(bot.game_info.map_center, 7.0)
    mineral_center = _mineral_center_near_base(bot, base_location)

    scored: list[tuple[float, Point2]] = []
    for pos, info in two_by_two.items():
        if bool(info.get("static_defence", False)):
            continue
        d_choke = float(pos.distance_to(choke_anchor))
        d_base = float(pos.distance_to(base_location))
        mineral_penalty = 0.0
        if mineral_center is not None:
            d_m = float(pos.distance_to(mineral_center))
            mineral_penalty = max(0.0, 9.0 - d_m) * 2.0
        base_penalty = max(0.0, 4.5 - d_base) * 1.2
        score = d_choke + mineral_penalty + base_penalty + (0.1 * d_base)
        scored.append((score, pos))

    scored.sort(key=lambda x: x[0])
    if not scored:
        return []

    picked: list[Point2] = []
    min_gap = 1.5
    for _, pos in scored:
        if any(float(pos.distance_to(prev)) < min_gap for prev in picked):
            continue
        picked.append(pos)
        if len(picked) >= int(desired_slots):
            break

    if len(picked) < int(desired_slots):
        for _, pos in scored:
            if pos in picked:
                continue
            picked.append(pos)
            if len(picked) >= int(desired_slots):
                break
    return picked[: max(0, int(desired_slots))]


def _is_slot_occupied(*, two_by_two: dict, pos: Point2) -> bool:
    info = two_by_two.get(pos, {})
    return (not bool(info.get("available", True))) or bool(info.get("worker_on_route", False))


def get_wall_depot_plan(
    bot,
    *,
    base_location: Point2,
    desired_slots: int = 2,
    infer_when_missing: bool = False,
) -> WallDepotPlan:
    try:
        placements = dict(bot.mediator.get_placements_dict or {})
    except Exception:
        placements = {}
    base_key = resolve_base_key(placements=placements, target=base_location)
    if base_key is None:
        return WallDepotPlan(base_key=None, slots=(), total=0, occupied=0, inferred=False)

    try:
        two_by_two = dict(placements[base_key][BuildingSize.TWO_BY_TWO] or {})
    except Exception:
        two_by_two = {}
    if not two_by_two:
        return WallDepotPlan(base_key=base_key, slots=(), total=0, occupied=0, inferred=False)

    explicit_slots = [pos for pos, info in two_by_two.items() if bool(info.get("is_wall", False))]
    inferred = False
    slots: list[Point2]
    if explicit_slots:
        slots = explicit_slots
    elif bool(infer_when_missing):
        slots = _infer_natural_slots(
            bot,
            two_by_two=two_by_two,
            base_location=base_location,
            desired_slots=max(1, int(desired_slots)),
        )
        inferred = True
    else:
        slots = []

    occupied = sum(1 for pos in slots if _is_slot_occupied(two_by_two=two_by_two, pos=pos))
    return WallDepotPlan(
        base_key=base_key,
        slots=tuple(slots),
        total=int(len(slots)),
        occupied=int(occupied),
        inferred=bool(inferred),
    )


def try_build_next_wall_depot(bot, *, plan: WallDepotPlan) -> bool:
    if int(bot.already_pending(U.SUPPLYDEPOT)) > 0:
        return False
    if not bool(bot.can_afford(U.SUPPLYDEPOT)):
        return False
    if plan.base_key is None or not plan.slots:
        return False

    try:
        placements = dict(bot.mediator.get_placements_dict or {})
        two_by_two = dict(placements[plan.base_key][BuildingSize.TWO_BY_TWO] or {})
    except Exception:
        return False

    target_pos = None
    for pos in plan.slots:
        info = two_by_two.get(pos, {})
        if bool(info.get("available", True)) and not bool(info.get("worker_on_route", False)):
            target_pos = pos
            break
    if target_pos is None:
        return False

    try:
        worker = bot.mediator.select_worker(target_position=target_pos, force_close=True)
    except Exception:
        worker = None
    if worker is None:
        return False

    try:
        return bool(
            bot.mediator.build_with_specific_worker(
                worker=worker,
                structure_type=U.SUPPLYDEPOT,
                pos=target_pos,
            )
        )
    except Exception:
        return False
