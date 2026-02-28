from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.units import Units

from bot.mind.attention import MissionSnapshot, MissionUnitThreatSnapshot, UnitThreatSnapshot, UnitThreatsSnapshot


def _is_ground_threat(enemy) -> bool:
    try:
        return bool(getattr(enemy, "can_attack_ground", False))
    except Exception:
        return False


def _danger_weight(enemy) -> float:
    try:
        if bool(getattr(enemy, "is_worker", False)):
            return 0.35
    except Exception:
        pass
    try:
        if bool(getattr(enemy, "is_structure", False)):
            return 1.25 if bool(getattr(enemy, "can_attack_ground", False)) else 0.0
    except Exception:
        pass
    try:
        rng = float(getattr(enemy, "ground_range", 0.0) or 0.0)
    except Exception:
        rng = 0.0
    if rng >= 7.0:
        return 2.25
    if rng >= 5.0:
        return 1.75
    if rng > 0.0:
        return 1.20
    return 0.0


def _can_win_value(bot, own_units: list, enemy_units: Units) -> int | None:
    if not own_units:
        return None
    if enemy_units.amount <= 0:
        return None
    try:
        own = Units(own_units, bot)
        res = bot.mediator.can_win_fight(
            own_units=own,
            enemy_units=enemy_units,
            timing_adjust=True,
            good_positioning=True,
            workers_do_no_damage=True,
        )
        return int(getattr(res, "value", int(res)))
    except Exception:
        return None


def derive_unit_threat_snapshot(
    bot,
    *,
    missions: MissionSnapshot,
    unit_radius: float = 9.0,
    mission_radius: float = 12.0,
) -> UnitThreatsSnapshot:
    units_out: list[UnitThreatSnapshot] = []
    missions_out: list[MissionUnitThreatSnapshot] = []

    enemy_units = bot.enemy_units
    if enemy_units is None or enemy_units.amount == 0:
        return UnitThreatsSnapshot()

    worker_types = {U.SCV, U.PROBE, U.DRONE, U.MULE}

    for mission in missions.ongoing:
        live_units = [bot.units.find_by_tag(int(tag)) for tag in mission.alive_tags]
        live_units = [u for u in live_units if u is not None]
        if not live_units:
            continue

        cx = sum(float(u.position.x) for u in live_units) / float(len(live_units))
        cy = sum(float(u.position.y) for u in live_units) / float(len(live_units))
        center = Point2((cx, cy))

        enemy_near_mission = enemy_units.closer_than(float(mission_radius), center)
        ground_threats_mission = enemy_near_mission.filter(lambda e: _is_ground_threat(e))
        can_win_val = _can_win_value(bot, live_units, ground_threats_mission)
        can_win = None if can_win_val is None else bool(can_win_val >= 5)
        worker_targets = int(enemy_near_mission.of_type(worker_types).amount)

        units_in_danger = 0
        for unit in live_units:
            near = ground_threats_mission.closer_than(float(unit_radius), unit.position)
            enemy_count_local = int(near.amount)
            hp_frac = float(getattr(unit, "health_percentage", 1.0) or 1.0)
            danger = float(sum(_danger_weight(e) for e in near)) / max(0.25, hp_frac)
            in_danger = bool(danger >= 7.5 or (hp_frac <= 0.35 and enemy_count_local > 0))
            if in_danger:
                units_in_danger += 1
            units_out.append(
                UnitThreatSnapshot(
                    mission_id=str(mission.mission_id),
                    unit_tag=int(unit.tag),
                    unit_type=str(getattr(getattr(unit, "type_id", None), "name", "")),
                    hp_frac=float(hp_frac),
                    enemy_count_local=int(enemy_count_local),
                    danger_score=round(float(danger), 3),
                    in_danger=bool(in_danger),
                )
            )

        missions_out.append(
            MissionUnitThreatSnapshot(
                mission_id=str(mission.mission_id),
                unit_count=int(len(live_units)),
                units_in_danger=int(units_in_danger),
                enemy_count_local=int(ground_threats_mission.amount),
                worker_targets=int(worker_targets),
                can_win_value=None if can_win_val is None else int(can_win_val),
                can_win_fight=can_win,
            )
        )

    missions_out.sort(key=lambda m: (-(m.units_in_danger), -m.enemy_count_local, m.mission_id))
    return UnitThreatsSnapshot(units=tuple(units_out), missions=tuple(missions_out))
