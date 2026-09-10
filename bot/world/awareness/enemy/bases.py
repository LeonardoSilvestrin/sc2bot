from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from sc2.position import Point2

from bot.world.attention import TOWNHALL_TYPES, WorldFacts

# How close an enemy townhall must be to a candidate expansion slot to count
# as occupying it, and how close a slot must be to one of our own bases to
# be excluded as a candidate in the first place.
_CONFIRM_RADIUS = 6.0
_OWN_BASE_EXCLUSION_RADIUS = 6.0


class EnemyBaseStatus(Enum):
    """What we currently believe about one candidate expansion slot."""

    CONFIRMED = auto()
    EMPTY = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class EnemyBaseObservation:
    """Typed freshness information about one candidate enemy base slot."""

    key: str
    position: Point2
    status: EnemyBaseStatus
    last_confirmed_at: float | None
    last_checked_at: float | None
    confidence: float
    stale_after: float
    is_stale: bool


class EnemyBaseMemory:
    """Tracks which map expansions likely hold an enemy base.

    Complements ``EnemyKnowledge`` (which only remembers a base for as long
    as Ares keeps reporting its townhall's tag) with a location-based memory:
    once a candidate expansion slot has actually been seen, we remember
    whether it held an enemy townhall or was empty, until it is looked at
    again. Absence of vision does not erase that memory -- it only ages it.
    """

    def __init__(self, *, stale_after: float = 120.0) -> None:
        if stale_after <= 0.0:
            raise ValueError("stale_after must be positive")
        self.stale_after = float(stale_after)
        self._status: dict[str, EnemyBaseStatus] = {}
        self._last_confirmed_at: dict[str, float] = {}
        self._last_checked_at: dict[str, float] = {}

    def update(self, world: WorldFacts) -> tuple[EnemyBaseObservation, ...]:
        own_positions = tuple(base.position for base in world.bases)
        enemy_townhalls = tuple(
            structure
            for structure in world.enemy_structures
            if structure.visible_now and structure.unit_type in TOWNHALL_TYPES
        )

        observations: list[EnemyBaseObservation] = []
        for slot in world.map.expansions:
            if any(
                slot.position.distance_to(position) <= _OWN_BASE_EXCLUSION_RADIUS
                for position in own_positions
            ):
                continue

            if slot.visible_now:
                self._last_checked_at[slot.key] = world.time
                confirmed = any(
                    townhall.position.distance_to(slot.position) <= _CONFIRM_RADIUS
                    for townhall in enemy_townhalls
                )
                if confirmed:
                    self._status[slot.key] = EnemyBaseStatus.CONFIRMED
                    self._last_confirmed_at[slot.key] = world.time
                else:
                    self._status[slot.key] = EnemyBaseStatus.EMPTY

            last_checked = self._last_checked_at.get(slot.key)
            age = None if last_checked is None else max(0.0, world.time - last_checked)
            confidence = (
                0.0 if age is None else max(0.0, 1.0 - (age / self.stale_after))
            )
            observations.append(
                EnemyBaseObservation(
                    key=slot.key,
                    position=slot.position,
                    status=self._status.get(slot.key, EnemyBaseStatus.UNKNOWN),
                    last_confirmed_at=self._last_confirmed_at.get(slot.key),
                    last_checked_at=last_checked,
                    confidence=confidence,
                    stale_after=self.stale_after,
                    is_stale=age is None or age >= self.stale_after,
                )
            )
        return tuple(observations)


def scouting_coverage(observations: tuple[EnemyBaseObservation, ...]) -> float:
    """Fraction of candidate expansion slots recently looked at.

    A coarse, conservative proxy for how much of the map/opponent we have
    actually scouted lately -- used to gate belief confidence built on top
    of "we haven't seen it", since absence of vision is not absence of
    economy or army. Defaults to full coverage when there is nothing to
    check (no map expansion data available), so confidence then falls back
    to evidence freshness alone instead of being needlessly capped.
    """

    if not observations:
        return 1.0
    checked = sum(
        1
        for observation in observations
        if observation.last_checked_at is not None and not observation.is_stale
    )
    return checked / len(observations)
