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
    contiguous_occupied: bool
    inferred: bool


def _rank_slots_for_choke(bot, *, base_location: Point2, slots: list[Point2]) -> list[Point2]:
    if not slots:
        return []
    choke_anchor = _choke_anchor_near_natural(bot, base_location=base_location)
    if choke_anchor is None:
        choke_anchor = base_location.towards(bot.game_info.map_center, 8.0)
    mineral_center = _mineral_center_near_base(bot, base_location)
    enemy_dir = bot.game_info.map_center - base_location

    scored: list[tuple[float, Point2]] = []
    for pos in slots:
        d_choke = float(pos.distance_to(choke_anchor))
        d_base = float(pos.distance_to(base_location))
        outward_penalty = 0.0
        try:
            rel = pos - base_location
            dot = float((rel.x * enemy_dir.x) + (rel.y * enemy_dir.y))
            if dot <= 0.0:
                outward_penalty = 8.0
        except Exception:
            pass
        mineral_penalty = 0.0
        if mineral_center is not None:
            d_m = float(pos.distance_to(mineral_center))
            mineral_penalty = max(0.0, 9.0 - d_m) * 2.5
        score = d_choke + (0.15 * d_base) + outward_penalty + mineral_penalty
        scored.append((score, pos))
    scored.sort(key=lambda x: x[0])
    return [p for _, p in scored]


def _pick_contiguous_slots(*, ranked_slots: list[Point2], desired_slots: int) -> list[Point2]:
    if int(desired_slots) <= 1 or len(ranked_slots) <= 1:
        return ranked_slots[: max(0, int(desired_slots))]

    best_pair: tuple[float, Point2, Point2] | None = None
    for i in range(len(ranked_slots)):
        a = ranked_slots[i]
        for j in range(i + 1, len(ranked_slots)):
            b = ranked_slots[j]
            d = float(a.distance_to(b))
            # Depot centers should be roughly adjacent to form a closed segment.
            if d < 1.4 or d > 2.6:
                continue
            pair_score = float(i + j) + abs(d - 2.0) * 3.0
            if best_pair is None or pair_score < float(best_pair[0]):
                best_pair = (pair_score, a, b)

    if best_pair is None:
        return ranked_slots[: max(0, int(desired_slots))]

    out = [best_pair[1], best_pair[2]]
    if int(desired_slots) <= 2:
        return out

    for p in ranked_slots:
        if p in out:
            continue
        out.append(p)
        if len(out) >= int(desired_slots):
            break
    return out


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

    choke_anchor = _choke_anchor_near_natural(bot, base_location=base_location)
    if choke_anchor is None:
        choke_anchor = base_location.towards(bot.game_info.map_center, 7.0)
    mineral_center = _mineral_center_near_base(bot, base_location)
    enemy_dir = bot.game_info.map_center - base_location

    scored: list[tuple[float, Point2]] = []
    for pos, info in two_by_two.items():
        if bool(info.get("static_defence", False)):
            continue
        d_choke = float(pos.distance_to(choke_anchor))
        d_base = float(pos.distance_to(base_location))
        # Favor slots on the outer side of the natural (towards the map center/choke).
        outward_penalty = 0.0
        try:
            rel = pos - base_location
            dot = float((rel.x * enemy_dir.x) + (rel.y * enemy_dir.y))
            if dot <= 0.0:
                outward_penalty = 12.0
        except Exception:
            pass
        mineral_penalty = 0.0
        if mineral_center is not None:
            d_m = float(pos.distance_to(mineral_center))
            mineral_penalty = max(0.0, 10.0 - d_m) * 4.0
        base_penalty = max(0.0, 5.0 - d_base) * 2.0
        choke_band_penalty = max(0.0, d_choke - 6.0) * 2.5
        score = d_choke + mineral_penalty + base_penalty + choke_band_penalty + outward_penalty + (0.1 * d_base)
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


def _choke_anchor_near_natural(bot, *, base_location: Point2) -> Point2 | None:
    try:
        chokes = list(bot.mediator.get_map_choke_points or [])
    except Exception:
        chokes = []
    if not chokes:
        return None
    probe = base_location.towards(bot.game_info.map_center, 8.0)
    try:
        anchor = min(chokes, key=lambda p: float(p.distance_to(probe)))
    except Exception:
        return None
    # If the nearest choke point is too far, avoid forcing an invalid anchor.
    if float(anchor.distance_to(base_location)) > 18.0:
        return None
    return anchor


def _query_wall_slots_from_mediator(bot, *, base_location: Point2, desired_slots: int) -> list[Point2]:
    out: list[Point2] = []
    if int(desired_slots) <= 0:
        return out
    choke_anchor = _choke_anchor_near_natural(bot, base_location=base_location)
    closest_probe = choke_anchor if choke_anchor is not None else base_location.towards(bot.game_info.map_center, 8.0)
    for _ in range(max(1, int(desired_slots) * 2)):
        try:
            pos = bot.mediator.request_building_placement(
                base_location=base_location,
                structure_type=U.SUPPLYDEPOT,
                wall=True,
                find_alternative=False,
                reserve_placement=False,
                closest_to=closest_probe,
            )
        except Exception:
            pos = None
        if pos is None:
            continue
        if any(float(pos.distance_to(p)) < 0.5 for p in out):
            continue
        out.append(pos)
        if len(out) >= int(desired_slots):
            break
    return out


def _is_slot_occupied(*, two_by_two: dict, pos: Point2) -> bool:
    info = two_by_two.get(pos, {})
    return (not bool(info.get("available", True))) or bool(info.get("worker_on_route", False))


def _contiguous_occupied(*, two_by_two: dict, slots: list[Point2]) -> bool:
    occ = [p for p in slots if _is_slot_occupied(two_by_two=two_by_two, pos=p)]
    if len(occ) <= 1:
        return False
    best = min(float(a.distance_to(b)) for i, a in enumerate(occ) for b in occ[i + 1 :])
    return 1.4 <= float(best) <= 2.6


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
        return WallDepotPlan(base_key=None, slots=(), total=0, occupied=0, contiguous_occupied=False, inferred=False)

    try:
        two_by_two = dict(placements[base_key][BuildingSize.TWO_BY_TWO] or {})
    except Exception:
        two_by_two = {}
    if not two_by_two:
        return WallDepotPlan(base_key=base_key, slots=(), total=0, occupied=0, contiguous_occupied=False, inferred=False)

    explicit_slots = [pos for pos, info in two_by_two.items() if bool(info.get("is_wall", False))]
    inferred = False
    slots: list[Point2]
    if explicit_slots:
        slots = _rank_slots_for_choke(bot, base_location=base_location, slots=list(explicit_slots))
    elif bool(infer_when_missing):
        slots = _query_wall_slots_from_mediator(
            bot,
            base_location=base_location,
            desired_slots=max(1, int(desired_slots)),
        )
        if not slots:
            slots = _infer_natural_slots(
                bot,
                two_by_two=two_by_two,
                base_location=base_location,
                desired_slots=max(1, int(desired_slots)),
            )
        slots = _rank_slots_for_choke(bot, base_location=base_location, slots=list(slots))
        inferred = bool(slots)
    else:
        slots = []

    # For natural-style walling (desired >= 2), enforce contiguous slot selection.
    slots = _pick_contiguous_slots(ranked_slots=list(slots), desired_slots=max(1, int(desired_slots)))
    occupied = sum(1 for pos in slots if _is_slot_occupied(two_by_two=two_by_two, pos=pos))
    contiguous_occupied = _contiguous_occupied(two_by_two=two_by_two, slots=list(slots))
    return WallDepotPlan(
        base_key=base_key,
        slots=tuple(slots),
        total=int(len(slots)),
        occupied=int(occupied),
        contiguous_occupied=bool(contiguous_occupied),
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

    target_pos = next_available_wall_slot(bot, plan=plan)
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


def next_available_wall_slot(bot, *, plan: WallDepotPlan) -> Point2 | None:
    if plan.base_key is None or not plan.slots:
        return None
    try:
        placements = dict(bot.mediator.get_placements_dict or {})
        two_by_two = dict(placements[plan.base_key][BuildingSize.TWO_BY_TWO] or {})
    except Exception:
        return None
    for pos in plan.slots:
        info = two_by_two.get(pos, {})
        if bool(info.get("available", True)) and not bool(info.get("worker_on_route", False)):
            return pos
    return None
