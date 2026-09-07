from __future__ import annotations

from dataclasses import replace

from bot.world.knowledge.enemy.models import EnemySighting
from bot.world.observation.models import WorldFacts


class EnemyKnowledge:
    """Persists enemy sightings without exposing mutable storage."""

    def __init__(self) -> None:
        self._sightings: dict[int, EnemySighting] = {}

    def update(self, world: WorldFacts) -> tuple[EnemySighting, ...]:
        visible_tags: set[int] = set()
        for unit in (*world.enemy_units, *world.enemy_structures):
            previous = self._sightings.get(unit.tag)
            if unit.visible_now:
                visible_tags.add(unit.tag)
                self._sightings[unit.tag] = EnemySighting(
                    tag=unit.tag,
                    unit_type=unit.unit_type,
                    last_position=unit.position,
                    first_seen_at=(
                        previous.first_seen_at if previous is not None else world.time
                    ),
                    last_seen_at=world.time,
                    visible_now=True,
                    can_attack_air=unit.can_attack_air,
                    can_attack_ground=unit.can_attack_ground,
                    is_structure=unit.is_structure,
                )
            elif previous is None:
                # Ares can expose a memory unit when this runtime starts.
                self._sightings[unit.tag] = EnemySighting(
                    tag=unit.tag,
                    unit_type=unit.unit_type,
                    last_position=unit.position,
                    first_seen_at=world.time,
                    last_seen_at=world.time,
                    visible_now=False,
                    can_attack_air=unit.can_attack_air,
                    can_attack_ground=unit.can_attack_ground,
                    is_structure=unit.is_structure,
                )

        for tag, sighting in tuple(self._sightings.items()):
            if tag not in visible_tags and sighting.visible_now:
                self._sightings[tag] = replace(sighting, visible_now=False)

        return tuple(self._sightings[tag] for tag in sorted(self._sightings))
