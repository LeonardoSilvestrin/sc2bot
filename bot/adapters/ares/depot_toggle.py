from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

_RAISED = UnitTypeId.SUPPLYDEPOT
_LOWERED = UnitTypeId.SUPPLYDEPOTLOWERED


@dataclass
class DepotToggle:
    """Lower supply depots when no ground enemy is near, raise them when one is.

    Ares has no built-in depot-toggle behavior; this fills that gap the same
    way ``Mining()`` fills worker assignment in
    ``bot.adapters.ares.frame.register_baseline_behaviors`` -- register once
    and let Ares' behavior executioner call ``execute`` every frame. Only
    ground units matter: a flying unit is never blocked by, and never cares
    about, a depot's height.

    Attributes:
        threat_radius: distance (in tiles) at which a ground enemy keeps a
            depot raised, or forces one back up.
    """

    threat_radius: float = 6.5

    def execute(self, ai, config, mediator) -> bool:
        depots = [*ai.structures(_RAISED), *ai.structures(_LOWERED)]
        if not depots:
            return False

        nearby_ground_enemies = [unit for unit in ai.enemy_units if not unit.is_flying]

        did_action = False
        for depot in depots:
            threatened = any(
                depot.distance_to(enemy) <= self.threat_radius
                for enemy in nearby_ground_enemies
            )
            if threatened and depot.type_id == _LOWERED:
                depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                did_action = True
            elif not threatened and depot.type_id == _RAISED:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
                did_action = True
        return did_action
