from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .knowledge import EnemySighting


@dataclass(frozen=True, slots=True)
class RosterUpdate:
    alive: tuple[EnemySighting, ...]
    # Units the game reported dead this update, as they were last seen.
    died: tuple[EnemySighting, ...]


class EnemyRoster:
    """Every mobile enemy unit seen, kept until the game reports it dead.

    ``EnemyKnowledge`` forgets a unit once Ares stops reporting its tag,
    about 30 s after it leaves vision. That is the right lifetime for "where
    is it", but not for "how much does the enemy have": an army that walked
    into the fog still exists. The roster keeps each unit's last sighting
    until its tag appears in ``WorldFacts.dead_unit_tags``. Losses nobody
    saw (a merge, a morph that replaced the tag) are left to the beliefs
    reading the roster, which let old entries fade.
    """

    def __init__(self) -> None:
        self._entries: dict[int, EnemySighting] = {}
        self._dead: set[int] = set()

    def update(
        self, sightings: Iterable[EnemySighting], *, dead_tags: frozenset[int]
    ) -> RosterUpdate:
        for sighting in sightings:
            if not sighting.is_structure and sighting.tag not in self._dead:
                self._entries[sighting.tag] = sighting
        # A tag is reported dead on two consecutive observations, and Ares
        # may still echo it once; it must only ever count as one loss.
        died = tuple(
            self._entries.pop(tag)
            for tag in sorted(dead_tags & self._entries.keys())
        )
        self._dead.update(dead_tags)
        return RosterUpdate(
            alive=tuple(self._entries[tag] for tag in sorted(self._entries)),
            died=died,
        )
