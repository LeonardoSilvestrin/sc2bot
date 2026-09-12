from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId

from bot.world.attention import WorldFacts
from bot.world.awareness.enemy import EnemySighting

from .relative import (
    HysteresisState,
    RelativeAssessment,
    RelativeBeliefConfig,
    advance_belief,
    clamp01,
    freshness,
)


@dataclass(frozen=True, slots=True)
class EnemyUnitTypeCount:
    unit_type: UnitTypeId
    count: int


@dataclass(frozen=True, slots=True)
class ArmySupplyEstimate:
    observed: float
    estimated: float
    confidence: float


@dataclass(frozen=True, slots=True)
class EnemyArmyKnowledge:
    supply: ArmySupplyEstimate
    # Known composition of the *estimated* (observed + remembered) enemy
    # army, by unit type -- carried over from ``EnemyKnowledge`` sightings,
    # not a new tracking mechanism.
    composition: tuple[EnemyUnitTypeCount, ...]


@dataclass(frozen=True, slots=True)
class ArmyBelief:
    """What we believe about the military race, own vs enemy, by supply."""

    own_supply: float
    enemy: EnemyArmyKnowledge
    relative: RelativeAssessment


@dataclass(frozen=True, slots=True)
class ArmyBeliefConfig:
    stale_after: float = 45.0
    relative: RelativeBeliefConfig = RelativeBeliefConfig(persist_seconds=8.0)


def assess_army(
    *,
    world: WorldFacts,
    sightings: tuple[EnemySighting, ...],
    coverage: float,
    now: float,
    state: HysteresisState,
    config: ArmyBeliefConfig,
) -> tuple[ArmyBelief, HysteresisState]:
    """Derive an army belief from supply, not unit counts.

    Confidence leans mainly on ``coverage`` (the same scouting-coverage
    signal economy uses, from ``EnemyBaseMemory``) rather than how much of
    the *estimated* army is currently visible: a couple of freshly-seen
    units being the entirety of what we know is exactly the "few visible
    units" case that must not read as AHEAD.
    """

    own_supply = sum(
        unit.supply_cost
        for unit in world.own_units
        if not unit.is_worker and (unit.can_attack_air or unit.can_attack_ground)
    )

    combat_sightings = tuple(
        sighting for sighting in sightings if sighting.is_combat_unit
    )
    observed_supply = sum(
        sighting.supply_cost for sighting in combat_sightings if sighting.visible_now
    )
    estimated_supply = sum(sighting.supply_cost for sighting in combat_sightings)

    last_seen_at = max(
        (sighting.last_seen_at for sighting in combat_sightings), default=None
    )
    army_freshness = freshness(now, last_seen_at, config.stale_after)
    directly_confirmed_ratio = (
        observed_supply / estimated_supply if estimated_supply > 0 else 0.0
    )
    confidence = clamp01(
        army_freshness * (0.15 + 0.70 * coverage + 0.15 * directly_confirmed_ratio)
    )

    composition = tuple(
        sorted(
            (
                EnemyUnitTypeCount(unit_type=unit_type, count=count)
                for unit_type, count in Counter(
                    sighting.unit_type for sighting in combat_sightings
                ).items()
            ),
            key=lambda item: item.unit_type.value,
        )
    )
    enemy = EnemyArmyKnowledge(
        supply=ArmySupplyEstimate(
            observed=observed_supply,
            estimated=estimated_supply,
            confidence=confidence,
        ),
        composition=composition,
    )

    reason = (
        "enemy army sighted" if own_supply > 0 and observed_supply >= own_supply else ""
    )
    assessment, new_state = advance_belief(
        now=now,
        own=own_supply,
        estimated=estimated_supply,
        observed=observed_supply,
        confidence=confidence,
        reason=reason,
        state=state,
        config=config.relative,
    )

    return (
        ArmyBelief(own_supply=own_supply, enemy=enemy, relative=assessment),
        new_state,
    )
