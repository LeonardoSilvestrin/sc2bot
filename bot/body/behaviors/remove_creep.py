"""Execute a whole granted creep squad together, without acquiring enemies."""

from __future__ import annotations

from collections.abc import Sequence

from ares.behaviors.combat.individual import PathUnitToTarget
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.awareness.regions import TUMORS
from bot.ego.planners import Proposal


def execute(bot, units: Sequence, proposal: Proposal) -> None:
    config = dict(proposal.inputs)
    danger_distance = config.get("danger_distance", 15.0)
    cohesion = config.get("cohesion", 8.0)
    minimum = int(config.get("minimum_escort", 2.0))
    clearing = bool(config.get("clear", 1.0))
    fallback = proposal.fallback or proposal.target
    ravens = [u for u in units if u.type_id is UnitTypeId.RAVEN]
    escorts = [u for u in units if u.type_id in (UnitTypeId.MARINE, UnitTypeId.HELLION)]
    enemies = [
        e
        for e in (*bot.enemy_units, *bot.enemy_structures)
        if not getattr(e, "is_memory", False) and getattr(e, "is_visible", True)
    ]
    danger = [
        e
        for e in enemies
        if e.type_id not in TUMORS
        and (e.can_attack_ground or e.can_attack_air)
        and any(e.distance_to(u) <= danger_distance for u in units)
    ]
    target = proposal.target
    fleeing = bool(danger)
    if fleeing:
        center = Point2(
            (
                sum(u.position.x for u in units) / len(units),
                sum(u.position.y for u in units) / len(units),
            )
        )
        closest = min(danger, key=lambda e: e.distance_to(center))
        # When home is behind the enemy, first escape in the opposite direction.
        target = (
            center.towards(closest.position, -danger_distance)
            if (closest.distance_to(fallback) < center.distance_to(fallback))
            else fallback
        )
        area = bot.game_info.playable_area
        target = Point2(
            (
                max(area.x + 1, min(area.x + area.width - 1, target.x)),
                max(area.y + 1, min(area.y + area.height - 1, target.y)),
            )
        )
    ready = bool(ravens) and len(escorts) >= minimum
    if any(u.type_id is UnitTypeId.MARINE for u in escorts):
        ready = ready and any(u.type_id is UnitTypeId.MEDIVAC for u in units)
    if not ready and not fleeing:
        target = fallback
    elif ready and not fleeing and any(u.distance_to(ravens[0]) > cohesion for u in units):
        # Regroup at the ground escort; a fast Raven never runs ahead alone.
        target = min(escorts, key=lambda u: u.tag).position
        ready = False
    tumors = [
        e
        for e in enemies
        if e.type_id in TUMORS
        and (not getattr(e, "is_burrowed", False) or getattr(e, "is_revealed", False))
    ]
    nearby = [e for e in tumors if e.distance_to(proposal.target) <= 12.0]
    if clearing and ready and not fleeing and nearby:
        target = min(nearby, key=lambda e: (e.distance_to(ravens[0]), e.tag)).position
    for unit in units:
        if clearing and ready and not fleeing and unit in escorts:
            in_range = [
                e
                for e in tumors
                if e.distance_to(unit)
                <= (
                    getattr(unit, "ground_range", 5.0)
                    + getattr(unit, "radius", 0.5)
                    + getattr(e, "radius", 0.5)
                )
                and any(e.distance_to(raven) <= 10.0 for raven in ravens)
            ]
            if in_range:
                tumor = min(in_range, key=lambda e: (e.distance_to(unit), e.tag))
                unit(AbilityId.ATTACK, tumor)
                continue
        if clearing and ready and not fleeing and unit.type_id is UnitTypeId.MEDIVAC:
            injured = [
                u
                for u in escorts
                if u.type_id is UnitTypeId.MARINE
                and u.health_percentage < 1.0
                and unit.distance_to(u) <= 4.0
            ]
            if injured:
                unit(AbilityId.MEDIVACHEAL_HEAL, min(injured, key=lambda u: u.health_percentage))
                continue
        bot.register_behavior(
            PathUnitToTarget(
                unit=unit,
                grid=bot.mediator.get_air_grid if unit.is_flying else bot.mediator.get_ground_grid,
                target=target,
                success_at_distance=0.0 if fleeing else 1.0,
                sense_danger=True,
                danger_distance=danger_distance,
                danger_threshold=1.0,
            )
        )
