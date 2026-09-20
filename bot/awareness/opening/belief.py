"""What the enemy's opening means: four continuous readings and a confidence.

`read_opening` turns the facts Attention recorded (`OpeningObservations`) into
an `OpeningBelief`: how much the opening looks like `aggression`, `greed`,
`tech` and `proxy`, each in [0, 1] and none of them the complement of another
-- an opening can be aggressive and teching at once, and an opening nobody
scouted is none of them.

Every term is continuous: a natural is not "late" or "on time" but somewhere
between `natural_early` and `natural_late` of its race, and every piece of
evidence adds before one saturation `S(x) = 1 - exp(-x)`. There is no
threshold anywhere, so one more Gateway never flips the read.

What is believed is read against *when it was observed*, never against now: an
expansion confirmed absent at 1:31 says the enemy had no natural at 1:31, and
that stays true however long ago it was. What ages is the confidence, which
falls as the record goes stale and rises with how much of the main was seen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from sc2.data import Race

from bot.attention import ExpansionObservation, ExpansionStatus, OpeningObservations

from .knowledge import OpeningExpectations, expectations_for


@dataclass(frozen=True, slots=True)
class OpeningBeliefConfig:
    # Weight of every piece of evidence, before saturation.
    late_natural: float = 1.0
    extra_production: float = 0.9
    rush_structures: float = 0.9
    combat_units: float = 0.6
    early_natural: float = 1.1
    early_third: float = 1.3
    tech_structures: float = 0.9
    extra_gas: float = 0.8
    # Gas bought instead of a third: tech, and the money went somewhere.
    delayed_third_gas: float = 0.6
    missing_expected: float = 1.6
    proxy_structure: float = 2.0
    proxy_rush: float = 0.5
    # How much of a signal saturates it: this many production structures above
    # the standard, this many early units, this much gas above the standard.
    production_span: float = 2.0
    combat_span: float = 4.0
    gas_span: float = 2.0
    tech_span: float = 2.0
    # How long past the expected time a structure must be missing from a
    # well-scouted main before the absence means it is somewhere else.
    missing_span: float = 60.0
    # Confidence: how much the main's coverage, the expansions checked and the
    # evidence gathered are each worth.
    coverage_weight: float = 0.45
    checks_weight: float = 0.35
    evidence_weight: float = 0.20
    evidence_span: float = 6.0
    # A record is current for `recency_grace` seconds, then fades with this tau.
    recency_grace: float = 30.0
    recency_tau: float = 120.0
    # What an opening read against the wrong expectations is worth.
    unknown_race_confidence: float = 0.6

    def __post_init__(self) -> None:
        for name in (
            "production_span",
            "combat_span",
            "gas_span",
            "tech_span",
            "missing_span",
            "evidence_span",
            "recency_tau",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if not 0.0 <= self.unknown_race_confidence <= 1.0:
            raise ValueError("unknown_race_confidence must be between 0 and 1")


DEFAULT_CONFIG = OpeningBeliefConfig()


@dataclass(frozen=True, slots=True)
class OpeningBelief:
    """What the opening looks like. Scores are independent; they do not sum
    to 1."""

    race: Race = Race.NoRace
    aggression: float = 0.0
    greed: float = 0.0
    tech: float = 0.0
    proxy: float = 0.0
    # How much the four readings are worth: coverage, checks and freshness.
    confidence: float = 0.0
    # Every term the readings were computed from, for the log.
    evidence: tuple[tuple[str, float], ...] = field(default=())

    @property
    def observed(self) -> bool:
        """Whether anything at all backs the reading."""

        return self.confidence > 0.0

    def term(self, name: str) -> float:
        for term, value in self.evidence:
            if term == name:
                return value
        return 0.0


EMPTY = OpeningBelief()


def read_opening(
    observations: OpeningObservations,
    now: float,
    config: OpeningBeliefConfig | None = None,
) -> OpeningBelief:
    """The opening the observations describe, read with its race's expectations."""

    config = config or DEFAULT_CONFIG
    if observations.last_updated is None:
        return EMPTY
    expectations = expectations_for(observations.enemy_race)
    terms = _terms(observations, expectations, config, now)
    read = terms.__getitem__
    return OpeningBelief(
        race=observations.enemy_race,
        aggression=_saturate(
            config.late_natural * read("natural_delay")
            + config.extra_production * read("extra_production")
            + config.rush_structures * read("rush")
            + config.combat_units * read("combat_units")
        ),
        greed=_saturate(
            config.early_natural * read("natural_earliness")
            + config.early_third * read("third_earliness")
        ),
        tech=_saturate(
            config.tech_structures * read("tech_structures")
            + config.extra_gas * read("extra_gas")
            + config.delayed_third_gas * read("third_delay") * read("extra_gas")
        ),
        proxy=_saturate(
            config.missing_expected * read("missing_expected")
            + config.proxy_structure * read("proxy_structures")
            + config.proxy_rush * read("rush")
        ),
        confidence=_confidence(observations, config, terms, now),
        evidence=tuple(sorted(terms.items())),
    )


def _terms(
    observations: OpeningObservations,
    expectations: OpeningExpectations,
    config: OpeningBeliefConfig,
    now: float,
) -> dict[str, float]:
    production_seen = observations.count(expectations.production)
    production_at = observations.first_seen(expectations.production)
    return {
        "natural_delay": _delay(
            observations.natural, expectations.natural_early, expectations.natural_late
        ),
        "natural_earliness": _earliness(
            observations.natural, expectations.natural_early, expectations.natural_late
        ),
        "third_delay": _delay(
            observations.third, expectations.third_early, expectations.third_late
        ),
        "third_earliness": _earliness(
            observations.third, expectations.third_early, expectations.third_late
        ),
        # Production above the standard, while seeing it still says something
        # about an opening rather than about a normal mid game.
        "extra_production": _clamp(
            (production_seen - expectations.standard_production) / config.production_span
        )
        * _fade(production_at, expectations.production_by, expectations.production_window),
        "rush": _clamp(
            sum(
                _fade(observations.structure(type_id).first_seen_at, 0.0, expectations.rush_by)
                for type_id in expectations.rush
            )
        ),
        "combat_units": _clamp(observations.early_combat_units_seen / config.combat_span),
        "tech_structures": _clamp(observations.types_seen(expectations.tech) / config.tech_span),
        "extra_gas": _clamp(
            (observations.gases_seen - expectations.standard_gases) / config.gas_span
        ),
        "missing_expected": _missing(observations, expectations, config),
        "proxy_structures": _clamp(observations.proxy_structures_seen),
        "coverage": observations.main_scout_coverage,
        "recency": _recency(observations.last_updated, now, config),
    }


def _delay(observation: ExpansionObservation, early: float, late: float) -> float:
    """How late the expansion was, in [0, 1]. An expansion nobody checked is
    not a late expansion: `UNKNOWN` reads 0."""

    if observation.status is ExpansionStatus.PRESENT:
        reference = observation.first_seen_at
    elif observation.status is ExpansionStatus.ABSENT_CONFIRMED:
        # It was still missing when we last looked, and that is all we know.
        reference = observation.last_checked_at
    else:
        return 0.0
    if reference is None:
        return 0.0
    return _clamp((reference - early) / max(1e-6, late - early))


def _earliness(observation: ExpansionObservation, early: float, late: float) -> float:
    """How early the expansion stood, in [0, 1]; 0 unless one was seen."""

    if observation.status is not ExpansionStatus.PRESENT or observation.first_seen_at is None:
        return 0.0
    return _clamp((late - observation.first_seen_at) / max(1e-6, late - early))


def _missing(
    observations: OpeningObservations,
    expectations: OpeningExpectations,
    config: OpeningBeliefConfig,
) -> float:
    """The share of what belongs in the main that a well-scouted main did not
    show, once it was late enough for it to be standing."""

    expected = expectations.expected_in_main
    if not expected:
        return 0.0
    missing = sum(1 for type_id in expected if observations.structure(type_id).count_seen == 0)
    if not missing:
        return 0.0
    since = (observations.last_updated or 0.0) - expectations.expected_in_main_by
    late = _clamp(since / config.missing_span)
    return (missing / len(expected)) * observations.main_scout_coverage * late


def _confidence(
    observations: OpeningObservations,
    config: OpeningBeliefConfig,
    terms: dict[str, float],
    now: float,
) -> float:
    checks = 0.5 * observations.natural_checked + 0.5 * observations.third_checked
    evidence = _clamp(
        (
            len(observations.structures)
            + observations.gases_seen
            + observations.early_combat_units_seen
        )
        / config.evidence_span
    )
    quality = (
        config.coverage_weight * observations.main_scout_coverage
        + config.checks_weight * checks
        + config.evidence_weight * evidence
    )
    race = 1.0 if observations.race_known else config.unknown_race_confidence
    return _clamp(quality * terms["recency"] * race)


def _recency(last_updated: float | None, now: float, config: OpeningBeliefConfig) -> float:
    if last_updated is None:
        return 0.0
    age = max(0.0, now - last_updated - config.recency_grace)
    return math.exp(-age / config.recency_tau)


def _fade(seen_at: float | None, until: float, window: float) -> float:
    """1 for something seen by `until`, falling to 0 over `window` after it;
    0 for something never seen."""

    if seen_at is None:
        return 0.0
    return _clamp((until + window - seen_at) / max(1e-6, window))


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _saturate(value: float) -> float:
    return 1.0 - math.exp(-max(0.0, value))
