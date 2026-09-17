"""What the fighting behaviors share: a Siege Tank decides its own siege, a
unit that fights attack-moves, and bio with an enemy near stims."""

from __future__ import annotations

from collections.abc import Sequence

from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AMove, SiegeTankDecision
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

TANKS = frozenset({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED})
# How far a Siege Tank looks for the enemies it sieges against.
TANK_SIGHT = 14.0
# An attacking unit this close to its point idles there and auto-acquires.
ATTACK_ARRIVAL = 2.0

# Unit type: (the stim it uses, the buff that says it is stimmed).
STIMS: dict[UnitTypeId, tuple[AbilityId, BuffId]] = {
    UnitTypeId.MARINE: (AbilityId.EFFECT_STIM_MARINE, BuffId.STIMPACK),
    UnitTypeId.MARAUDER: (AbilityId.EFFECT_STIM_MARAUDER, BuffId.STIMPACKMARAUDER),
}
# A bio unit stims with an enemy unit this close ...
STIM_RANGE = 10.0
# ... and at least this share of its health: stimming costs health.
STIM_MIN_HEALTH = 0.5


def maneuver(unit, target: Point2, enemies: Sequence, *, stay_sieged: bool) -> CombatManeuver:
    """A maneuver that starts with the siege decision when the unit is a Siege Tank."""

    maneuver = CombatManeuver()
    if unit.type_id in TANKS:
        maneuver.add(
            SiegeTankDecision(
                unit=unit,
                close_enemy=[enemy for enemy in enemies if enemy.distance_to(unit) <= TANK_SIGHT],
                target=target,
                stay_sieged_near_target=stay_sieged,
            )
        )
    return maneuver


def attack_move(unit, target: Point2) -> AMove:
    return AMove(unit=unit, target=target, success_at_distance=ATTACK_ARRIVAL)


def stim_for(unit, enemies: Sequence) -> AbilityId | None:
    """The stim the unit should use now, or None."""

    stim = STIMS.get(unit.type_id)
    if stim is None:
        return None
    ability, buff = stim
    if ability not in unit.abilities or unit.has_buff(buff):
        return None
    if unit.health_percentage < STIM_MIN_HEALTH:
        return None
    if not any(enemy.distance_to(unit) <= STIM_RANGE for enemy in enemies):
        return None
    return ability
