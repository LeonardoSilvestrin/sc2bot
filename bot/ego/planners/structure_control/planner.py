"""StructureControlPlanner: what our own structures do by themselves.

Supply depots go up and down, and a Barracks, Factory or Starport that walls a
Siege Tank in flies out of its way (`policies.relocation`). A finished depot
goes up the frame a ground enemy comes within `raise_reach` of it, and down
again once no ground enemy has been that close for `lower_after` seconds, so an
enemy pacing at the edge of reach cannot toggle it faster than that. Flying
enemies do not count: a depot does not stop them.

Raising a depot pushes our own units on top of it to its nearest edge, and an
enemy on top keeps it from rising until it steps off (the Body simply orders
it again). The plan counts our units on the depots it raises, so that cost is
in the log.

The relocation never touches a depot, and the depots' plan does not depend on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, MapView
from bot.ego.planners import StructurePlan

from .policies.relocation import RelocationConfig, Relocator

DEPOT_TYPES = frozenset({UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED})
# A 2x2 depot's half side plus a small unit's radius: a unit this close to the
# center stands on it.
ON_DEPOT = 1.5


@dataclass(frozen=True, slots=True)
class StructureConfig:
    # A ground enemy this close to a depot, in cells, raises it.
    raise_reach: float = 8.0
    # Seconds a depot stays up after the last ground enemy left its reach.
    lower_after: float = 3.0
    relocation: RelocationConfig = field(default_factory=RelocationConfig)

    def __post_init__(self) -> None:
        if self.raise_reach <= 0.0:
            raise ValueError("raise_reach must be positive")
        if self.lower_after < 0.0:
            raise ValueError("lower_after must not be negative")


class StructureControlPlanner:
    def __init__(self, config: StructureConfig | None = None) -> None:
        self.config = config or StructureConfig()
        # When a ground enemy was last within reach, by depot tag.
        self._threatened_at: dict[int, float] = {}
        self._relocator = Relocator(self.config.relocation)

    def corridor(self, map_view: MapView) -> tuple[Point2, ...]:
        """Production sites of the main to leave empty: the way to the ramp."""

        return self._relocator.corridor(map_view)

    def plan(self, attention: AttentionState) -> StructurePlan:
        relocation = self._relocator.plan(attention)
        return replace(
            self._depots(attention),
            lift=relocation.lift,
            land=relocation.land,
            relocation=relocation.events,
        )

    def _depots(self, attention: AttentionState) -> StructurePlan:
        config = self.config
        now = attention.time
        depots = tuple(
            structure
            for structure in attention.own_structures
            if structure.type_id in DEPOT_TYPES and structure.is_ready
        )
        ground = tuple(enemy.position for enemy in attention.enemy_units if not enemy.is_flying)
        tags = {depot.tag for depot in depots}
        threatened_at = {tag: at for tag, at in self._threatened_at.items() if tag in tags}
        lower: list[int] = []
        raise_: list[int] = []
        near = recently_near = lowered = 0
        nearest = math.inf
        for depot in depots:
            distance = min(
                (depot.position.distance_to(enemy) for enemy in ground), default=math.inf
            )
            nearest = min(nearest, distance)
            if distance <= config.raise_reach:
                threatened_at[depot.tag] = now
                near += 1
                up = True
            elif now - threatened_at.get(depot.tag, -math.inf) < config.lower_after:
                recently_near += 1
                up = True
            else:
                up = False
            is_lowered = depot.type_id is UnitTypeId.SUPPLYDEPOTLOWERED
            lowered += is_lowered
            if up and is_lowered:
                raise_.append(depot.tag)
            elif not up and not is_lowered:
                lower.append(depot.tag)
        self._threatened_at = threatened_at

        rising = [depot.position for depot in depots if depot.tag in raise_]
        on_raising = sum(
            1
            for unit in attention.own_units
            if not unit.is_flying
            and any(unit.position.distance_to(center) <= ON_DEPOT for center in rising)
        )
        if not depots:
            reason = "no_depots"
        elif near:
            reason = "enemy_near"
        elif recently_near:
            reason = "enemy_recently_near"
        else:
            reason = "no_enemy_near"
        inputs = [
            ("depots", float(len(depots))),
            ("lowered", float(lowered)),
            ("enemy_near", float(near)),
            ("recently_near", float(recently_near)),
            ("ground_enemies", float(len(ground))),
            ("friendly_on_raising", float(on_raising)),
        ]
        if math.isfinite(nearest):
            inputs.append(("nearest_ground_enemy", nearest))
        return StructurePlan(
            lower=tuple(lower),
            raise_=tuple(raise_),
            reason=reason,
            inputs=tuple(inputs),
        )
