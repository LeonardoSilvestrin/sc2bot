from __future__ import annotations

import math
from dataclasses import dataclass

from bot.world.attention import WorldFacts
from bot.world.awareness.enemy import (
    EnemyBaseObservation,
    EnemyBaseStatus,
    EnemySighting,
)

from .estimate import (
    EstimateConfig,
    advance_estimate,
    advantage,
    clamp01,
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
class WorkerEstimate:
    observed: int
    estimated: int
    confidence: float
    # Workers seen and not seen dying (fading slowly).
    known: float = 0.0
    # Spread of the part not seen, in workers.
    uncertainty: float = 0.0


@dataclass(frozen=True, slots=True)
class BaseEstimate:
    confirmed: int
    estimated: int
    confidence: float


@dataclass(frozen=True, slots=True)
class EnemyEconomyKnowledge:
    workers: WorkerEstimate
    bases: BaseEstimate


@dataclass(frozen=True, slots=True)
class EconomyBelief:
    """What we believe about the economic race, own vs enemy."""

    own_workers: int
    own_bases: int
    enemy: EnemyEconomyKnowledge
    relative: RelativeAssessment


@dataclass(frozen=True, slots=True)
class EconomyBeliefConfig:
    # How many workers a confirmed enemy base reads as. A reading of the
    # whole, not a floor: a fresh expansion has none yet.
    assumed_workers_per_base: float = 16.0
    # A worker count is the economy itself, not a stand-in for it: little
    # spread on either side, so seeing more workers than we have is decisive.
    estimate: EstimateConfig = EstimateConfig(
        own_relative_sd=0.05, evidence_relative_sd=0.05, noise_floor=2.0
    )
    relative: RelativeBeliefConfig = RelativeBeliefConfig(persist_seconds=15.0)


def assess_economy(
    *,
    world: WorldFacts,
    sightings: tuple[EnemySighting, ...],
    roster: tuple[EnemySighting, ...],
    base_observations: tuple[EnemyBaseObservation, ...],
    losses: LossLedger,
    coverage: float,
    visibility: float,
    scouted: bool,
    state: BeliefState,
    config: EconomyBeliefConfig,
) -> tuple[EconomyBelief, BeliefState]:
    """Compare our workers with a running estimate of the enemy's.

    The floor is every enemy worker seen and not seen dying; the reading is
    the larger of that and what the confirmed bases imply. With nothing
    scouted the enemy is assumed to have as many workers as we do, corrected
    by the workers each side lost lately. See ``estimate.py``.
    """

    now = world.time
    own_workers = world.economy.workers.existing
    workers = roster_evidence(
        ((1.0, entry.last_seen_at) for entry in roster if entry.is_worker),
        now=now,
        config=config.estimate,
    )
    confirmed = tuple(
        observation
        for observation in base_observations
        if observation.status is EnemyBaseStatus.CONFIRMED
    )
    projected = len(confirmed) * config.assumed_workers_per_base
    if projected > workers.known:
        last_checked = max(
            (
                observation.last_checked_at
                for observation in confirmed
                if observation.last_checked_at is not None
            ),
            default=None,
        )
        freshness = (
            0.0
            if last_checked is None
            else math.exp(
                -max(0.0, now - last_checked)
                / config.estimate.evidence_time_constant
            )
        )
    else:
        freshness = workers.freshness

    prior = own_workers + losses.worker_trade
    estimate = advance_estimate(
        state.estimate,
        now=now,
        known=workers.known,
        reading=max(workers.known, projected),
        prior=prior,
        information=visibility * freshness,
        config=config.estimate,
    )
    informed = state.informed or scouted or workers.known > 0.0 or bool(confirmed)
    belief_confidence = confidence(estimate, config.estimate)
    relative, hysteresis = advance_belief(
        now=now,
        advantage=advantage(float(own_workers), estimate, config.estimate),
        informed=informed,
        confidence=belief_confidence,
        reason=(
            f"own {own_workers} vs enemy ~{estimate.mean:.0f}"
            f"±{estimate.spread:.0f} workers"
        ),
        state=state.hysteresis,
        config=config.relative,
    )

    enemy = EnemyEconomyKnowledge(
        workers=WorkerEstimate(
            observed=sum(
                1
                for sighting in sightings
                if sighting.is_worker and sighting.visible_now
            ),
            estimated=int(round(estimate.mean)),
            confidence=belief_confidence,
            known=estimate.known,
            uncertainty=estimate.spread,
        ),
        bases=BaseEstimate(
            confirmed=len(confirmed),
            estimated=len(confirmed),
            confidence=clamp01(coverage),
        ),
    )
    return (
        EconomyBelief(
            own_workers=own_workers,
            own_bases=len(world.bases),
            enemy=enemy,
            relative=relative,
        ),
        BeliefState(estimate=estimate, hysteresis=hysteresis, informed=informed),
    )
