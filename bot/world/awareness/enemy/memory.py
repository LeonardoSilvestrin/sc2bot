from __future__ import annotations

from bot.world.attention import WorldFacts

from .knowledge import EnemySighting


class EnemyKnowledge:
    """Persists enemy sightings without exposing mutable storage.

    Attention already carries Ares' own visible/memory distinction per unit
    (``UnitSnapshot.visible_now``); this only adds the first/last-seen
    history Ares itself doesn't track. A tag is kept only as long as Ares
    keeps reporting it -- once a tag stops appearing at all (Ares confirmed
    it destroyed, or its own out-of-vision memory expired it), the sighting
    is dropped here too instead of being remembered forever.
    """

    def __init__(self) -> None:
        self._sightings: dict[int, EnemySighting] = {}

    def update(self, world: WorldFacts) -> tuple[EnemySighting, ...]:
        present_tags: set[int] = set()
        for unit in (*world.enemy_units, *world.enemy_structures):
            present_tags.add(unit.tag)
            previous = self._sightings.get(unit.tag)
            first_seen_at = (
                previous.first_seen_at if previous is not None else world.time
            )
            last_seen_at = (
                world.time
                if unit.visible_now
                else (previous.last_seen_at if previous is not None else world.time)
            )
            self._sightings[unit.tag] = EnemySighting(
                tag=unit.tag,
                unit_type=unit.unit_type,
                last_position=unit.position,
                first_seen_at=first_seen_at,
                last_seen_at=last_seen_at,
                visible_now=unit.visible_now,
                can_attack_air=unit.can_attack_air,
                can_attack_ground=unit.can_attack_ground,
                is_structure=unit.is_structure,
                is_worker=unit.is_worker,
                supply_cost=unit.supply_cost,
            )

        for tag in tuple(self._sightings):
            if tag not in present_tags:
                del self._sightings[tag]

        return tuple(self._sightings[tag] for tag in sorted(self._sightings))
