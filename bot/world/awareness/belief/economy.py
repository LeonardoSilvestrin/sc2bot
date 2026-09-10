from __future__ import annotations

from dataclasses import dataclass

from bot.world.attention import WorldFacts
from bot.world.awareness.enemy import (
    EnemyBaseObservation,
    EnemyBaseStatus,
    EnemySighting,
)

from .relative import (
    HysteresisState,
    RelativeAssessment,
    RelativeBeliefConfig,
    advance_belief,
    clamp01,
    freshness,
)


@dataclass(frozen=True, slots=True)
class WorkerEstimate:
    observed: int
    estimated: int
    confidence: float


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
    # Conservative floor for "how many workers does N confirmed enemy bases
    # imply", used only as a lower bound alongside directly observed
    # workers -- never as a replacement for them.
    assumed_workers_per_base: float = 16.0
    worker_stale_after: float = 60.0
    relative: RelativeBeliefConfig = RelativeBeliefConfig(persist_seconds=15.0)


def assess_economy(
    *,
    world: WorldFacts,
    sightings: tuple[EnemySighting, ...],
    base_observations: tuple[EnemyBaseObservation, ...],
    coverage: float,
    now: float,
    state: HysteresisState,
    config: EconomyBeliefConfig,
) -> tuple[EconomyBelief, HysteresisState]:
    """Derive an economy belief. Conservative on purpose: absence of vision
    is never treated as absence of economy (see ``estimated_workers``), and
    an AHEAD conclusion is only trusted once scouting coverage backs it (see
    ``workers_confidence``) -- but a BEHIND conclusion already proven by
    directly observed workers is trusted immediately, in ``classify``.
    """

    own_workers = world.economy.workers.existing
    own_bases = len(world.bases)

    worker_sightings = tuple(sighting for sighting in sightings if sighting.is_worker)
    observed_workers = sum(1 for sighting in worker_sightings if sighting.visible_now)
    # A worker that just walked out of vision is still remembered (Ares
    # keeps reporting its tag) -- it must not silently stop counting until
    # the sighting itself expires. Absence of *current* vision is not
    # absence of economy.
    remembered_workers = len(worker_sightings)
    confirmed_bases = sum(
        1
        for observation in base_observations
        if observation.status is EnemyBaseStatus.CONFIRMED
    )
    projected_workers = confirmed_bases * config.assumed_workers_per_base
    estimated_workers = max(
        float(observed_workers), float(remembered_workers), projected_workers
    )

    last_worker_seen_at = max(
        (sighting.last_seen_at for sighting in worker_sightings), default=None
    )
    # A confirmed base is itself evidence for the workers it implies, even
    # with no worker directly seen recently -- freshness should reflect
    # whichever is more recent, not require a worker sighting specifically.
    last_confirmed_base_at = max(
        (
            observation.last_checked_at
            for observation in base_observations
            if observation.status is EnemyBaseStatus.CONFIRMED
            and observation.last_checked_at is not None
        ),
        default=None,
    )
    last_evidence_at = max(
        (
            timestamp
            for timestamp in (last_worker_seen_at, last_confirmed_base_at)
            if timestamp is not None
        ),
        default=None,
    )
    worker_freshness = freshness(now, last_evidence_at, config.worker_stale_after)
    # Coverage dominates: without it, "no bases confirmed" and "map not
    # scouted at all" look identical to "enemy really only has one base",
    # which is exactly the false-AHEAD trap this pilot must avoid.
    workers_confidence = clamp01(worker_freshness * (0.25 + 0.75 * coverage))
    bases_confidence = clamp01(coverage)

    enemy = EnemyEconomyKnowledge(
        workers=WorkerEstimate(
            observed=observed_workers,
            estimated=int(round(estimated_workers)),
            confidence=workers_confidence,
        ),
        bases=BaseEstimate(
            confirmed=confirmed_bases,
            estimated=confirmed_bases,
            confidence=bases_confidence,
        ),
    )

    reason = (
        "enemy workers observed"
        if own_workers > 0 and observed_workers >= own_workers
        else ""
    )
    assessment, new_state = advance_belief(
        now=now,
        own=float(own_workers),
        estimated=estimated_workers,
        observed=float(observed_workers),
        confidence=workers_confidence,
        reason=reason,
        state=state,
        config=config.relative,
    )

    return (
        EconomyBelief(
            own_workers=own_workers,
            own_bases=own_bases,
            enemy=enemy,
            relative=assessment,
        ),
        new_state,
    )
