"""What the fighting behaviors share: a Siege Tank decides its own siege, and a
unit that fights attack-moves."""

from __future__ import annotations

from collections.abc import Sequence

from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AMove, SiegeTankDecision
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

TANKS = frozenset({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED})
# How far a Siege Tank looks for the enemies it sieges against.
TANK_SIGHT = 14.0
# An attacking unit this close to its point idles there and auto-acquires.
ATTACK_ARRIVAL = 2.0


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
