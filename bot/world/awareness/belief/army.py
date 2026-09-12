from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId

from bot.world.attention import WorldFacts
from bot.world.awareness.enemy import EnemySighting

from .estimate import (
    EstimateConfig,
    advance_estimate,
    advantage,
    confidence,
    roster_evidence,
)
from .losses import LossLedger
from .relative import (
    BeliefState,
    RelativeAssessment,
    RelativeBeliefConfig,
    advance_belief,
)


@dataclass(frozen=True, slots=True)
class EnemyUnitTypeCount:
    unit_type: UnitTypeId
    count: int


@dataclass(frozen=True, slots=True)
class ArmySupplyEstimate:
    """Enemy army supply: in view now, and believed in total."""

    observed: float
    estimated: float
    confidence: float
    # Seen and not seen dying (fading slowly): ``estimated`` never drops below.
    known: float = 0.0
    # Spread of the part not seen, in supply.
    uncertainty: float = 0.0


@dataclass(frozen=True, slots=True)
class EnemyArmyKnowledge:
    supply: ArmySupplyEstimate
    # Composition of the known enemy army by unit type, from the roster.
    composition: tuple[EnemyUnitTypeCount, ...]


@dataclass(frozen=True, slots=True)
class ArmyBelief:
    """What we believe about the military race, own vs enemy, by supply."""

    own_supply: float
    enemy: EnemyArmyKnowledge
    relative: RelativeAssessment


@dataclass(frozen=True, slots=True)
class ArmyBeliefConfig:
    estimate: EstimateConfig = EstimateConfig()
    relative: RelativeBeliefConfig = RelativeBeliefConfig(persist_seconds=8.0)


def assess_army(
    *,
    world: WorldFacts,
    sightings: tuple[EnemySighting, ...],
    roster: tuple[EnemySighting, ...],
    losses: LossLedger,
    enemy_workers: float,
    visibility: float,
    scouted: bool,
    state: BeliefState,
    config: ArmyBeliefConfig,
) -> tuple[ArmyBelief, BeliefState]:
    """Compare our combat supply with a running estimate of the enemy's.

    The enemy side is every combat unit seen and not seen dying, plus an
    unseen remainder (see ``estimate.py``). With nothing scouted the
    remainder assumes an enemy our size -- our supply, corrected by the
    supply each side lost lately, minus the workers we believe it has -- and
    drifts back to that as information goes stale, so an army out of vision
    neither vanishes nor stays frozen at its last glimpse. How much a
    reading counts is ``visibility`` (``enemy_territory_coverage``) times
    how current the known army is.
    """

    now = world.time
    own_supply = sum(
        unit.supply_cost
        for unit in world.own_units
        if not unit.is_worker and (unit.can_attack_air or unit.can_attack_ground)
    )
    own_total = max(
        world.supply_used, sum(unit.supply_cost for unit in world.own_units)
    )
    combat_roster = tuple(
        entry for entry in roster if entry.is_combat_unit and entry.last_seen_known
    )
    evidence = roster_evidence(
        ((entry.supply_cost, entry.last_seen_at) for entry in combat_roster),
        now=now,
        config=config.estimate,
    )
    prior = own_total + losses.supply_trade - enemy_workers
    estimate = advance_estimate(
        state.estimate,
        now=now,
        known=evidence.known,
        reading=evidence.known,
        prior=prior,
        information=visibility * evidence.freshness,
        config=config.estimate,
        prior_scale=own_total,
    )
    informed = state.informed or scouted or bool(combat_roster)
    belief_confidence = confidence(estimate, config.estimate)
    relative, hysteresis = advance_belief(
        now=now,
        advantage=advantage(own_supply, estimate, config.estimate),
        informed=informed,
        confidence=belief_confidence,
        reason=(
            f"own {own_supply:.0f} vs enemy ~{estimate.mean:.0f}"
            f"±{estimate.spread:.0f} supply"
        ),
        state=state.hysteresis,
        config=config.relative,
    )

    composition = tuple(
        sorted(
            (
                EnemyUnitTypeCount(unit_type=unit_type, count=count)
                for unit_type, count in Counter(
                    entry.unit_type for entry in combat_roster
                ).items()
            ),
            key=lambda item: item.unit_type.value,
        )
    )
    enemy = EnemyArmyKnowledge(
        supply=ArmySupplyEstimate(
            observed=sum(
                sighting.supply_cost
                for sighting in sightings
                if sighting.is_combat_unit and sighting.visible_now
            ),
            estimated=estimate.mean,
            confidence=belief_confidence,
            known=estimate.known,
            uncertainty=estimate.spread,
        ),
        composition=composition,
    )
    return (
        ArmyBelief(own_supply=own_supply, enemy=enemy, relative=relative),
        BeliefState(estimate=estimate, hysteresis=hysteresis, informed=informed),
    )
