"""Attack: carries out ATTACK -- fight at the target, for Defense or the offense.

Every granted unit attack-moves to the target; a Siege Tank also decides on
its own when to siege, without holding the spot. Two local reactions keep the
bio alive in the fight, and the report says who took them:

- a Marine or Marauder with an enemy unit within `STIM_RANGE`, at least
  `STIM_MIN_HEALTH` of its health, not stimmed and able to stim (researched,
  off cooldown), stims first;
- a Medivac attack-moves -- which heals on the way -- to the centre of the
  other granted units instead of the target, so it does not fly ahead of
  them; with no other unit granted it goes to the target.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ares.behaviors.combat.individual import UseAbility
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import WORKER_TYPES
from bot.ego.planners import Proposal

from .combat import attack_move, maneuver

# Unit type: (the stim it uses, the buff that says it is stimmed).
STIMS: dict[UnitTypeId, tuple[AbilityId, BuffId]] = {
    UnitTypeId.MARINE: (AbilityId.EFFECT_STIM_MARINE, BuffId.STIMPACK),
    UnitTypeId.MARAUDER: (AbilityId.EFFECT_STIM_MARAUDER, BuffId.STIMPACKMARAUDER),
}
# A bio unit stims with an enemy unit this close ...
STIM_RANGE = 10.0
# ... and at least this share of its health: stimming costs health.
STIM_MIN_HEALTH = 0.5
ESCORTS = frozenset({UnitTypeId.MEDIVAC})


@dataclass(frozen=True, slots=True)
class MicroReport:
    """The local reactions the fighting behaviors took this frame."""

    # Units that stimmed, by tag.
    stimmed: tuple[int, ...] = ()
    # Medivacs that followed their group instead of heading for the target.
    escorts: tuple[int, ...] = ()

    def merge(self, other: MicroReport) -> MicroReport:
        return MicroReport(
            stimmed=tuple(sorted((*self.stimmed, *other.stimmed))),
            escorts=tuple(sorted((*self.escorts, *other.escorts))),
        )


def execute(bot, units: Sequence, proposal: Proposal) -> MicroReport:
    enemies = list(bot.enemy_units)
    fighters = [enemy for enemy in enemies if enemy.type_id not in WORKER_TYPES]
    group = group_center(units)
    stimmed: list[int] = []
    escorts: list[int] = []
    for unit in units:
        fight = maneuver(unit, proposal.target, enemies, stay_sieged=False)
        stim = stim_for(unit, fighters)
        if stim is not None:
            fight.add(UseAbility(stim, unit))
            stimmed.append(unit.tag)
        target = proposal.target
        if unit.type_id in ESCORTS and group is not None:
            target = group
            escorts.append(unit.tag)
        fight.add(attack_move(unit, target))
        bot.register_behavior(fight)
    return MicroReport(stimmed=tuple(sorted(stimmed)), escorts=tuple(sorted(escorts)))


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


def group_center(units: Sequence) -> Point2 | None:
    """Mean position of the granted units that are not escorts."""

    group = [unit for unit in units if unit.type_id not in ESCORTS]
    if not group:
        return None
    return Point2(
        (
            sum(float(unit.position.x) for unit in group) / len(group),
            sum(float(unit.position.y) for unit in group) / len(group),
        )
    )
