"""ASSESS: what do we not know, and what could we send to find out?"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from bot.world.attention import AttentionSnapshot, WorldFacts
from bot.world.awareness import AwarenessSnapshot

from .model import (
    IntelAssessment,
    IntelConfig,
    ScanAssessment,
    ScanConfig,
    ScoutTarget,
)

_ORBITAL_TYPES = frozenset(
    {UnitTypeId.ORBITALCOMMAND, UnitTypeId.ORBITALCOMMANDFLYING}
)


@dataclass(slots=True)
class IntelAssessor:
    config: IntelConfig = field(default_factory=IntelConfig)

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> IntelAssessment:
        world = attention.world
        preferred_alive = any(
            unit.unit_type in self.config.unit_types for unit in world.own_units
        )
        return IntelAssessment(
            now=world.time,
            target=self._target(world, awareness),
            workers=sum(unit.is_worker for unit in world.own_units),
            scout_unit_types=self._scout_unit_types(preferred_alive),
            preferred_scout_alive=preferred_alive,
        )

    def _target(
        self, world: WorldFacts, awareness: AwarenessSnapshot
    ) -> ScoutTarget | None:
        """Resolve which location this scout should actually visit.

        Synthetic/unit-test maps and unusual custom maps may not expose a
        usable main perimeter. Keep the old natural scout as a fallback.
        """

        key = self.config.target_key
        location = awareness.enemy.location(key)
        if key == "enemy_main" and (
            location is None or world.map.route(key) is None
        ):
            key = "enemy_natural"
            location = awareness.enemy.location(key)
        if location is None:
            return None
        return ScoutTarget(
            key=key,
            position=location.position,
            last_observed_at=location.last_observed_at,
            age=location.age,
            stale_after=location.stale_after,
            is_stale=location.is_stale,
            has_route=world.map.route(key) is not None,
        )

    def _scout_unit_types(self, preferred_alive: bool) -> frozenset[UnitTypeId]:
        """Prefer the configured scout unit; fall back only once none is alive."""

        if preferred_alive:
            return self.config.unit_types
        return self.config.fallback_unit_types


@dataclass(slots=True)
class ScanAssessor:
    """Measure enemy-main vision age and available Orbital energy."""

    config: ScanConfig = field(default_factory=ScanConfig)

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> ScanAssessment:
        world = attention.world
        observation = world.map.observation(self.config.target_key)
        knowledge = awareness.enemy.location(self.config.target_key)
        last_observed_at = None if knowledge is None else knowledge.last_observed_at
        seconds_without_vision = (
            world.time
            if last_observed_at is None
            else max(0.0, world.time - last_observed_at)
        )
        eligible = tuple(
            sorted(
                (
                    (structure.tag, structure.energy)
                    for structure in world.own_structures
                    if structure.unit_type in _ORBITAL_TYPES
                    and structure.is_ready
                    and structure.energy >= self.config.required_energy
                ),
                key=lambda item: (-item[1], item[0]),
            )
        )
        return ScanAssessment(
            now=world.time,
            target=None if observation is None else observation.position,
            visible_now=False if observation is None else observation.visible_now,
            last_observed_at=last_observed_at,
            seconds_without_vision=seconds_without_vision,
            eligible_orbitals=eligible,
        )
