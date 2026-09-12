"""One independent score per objective.

Each function reads ``StrategyInputs`` through a few shaped features, all in
[0, 1], and returns the signed contribution of every signal it uses. There
is no decision tree: which objective wins is only a comparison of scores,
made by the hysteresis step.

Shaped features:

- ``ahead(edge) = max(edge, 0)``, ``behind(edge) = max(-edge, 0)``
- ``home_security = (1 - immediate_threat) * (1 - base_exposure)``
"""

from __future__ import annotations

from collections.abc import Iterable

from .config import (
    BuildAdvantageWeights,
    PressureWeights,
    RecoverWeights,
    StabilizeWeights,
    StrategyConfig,
    TakeMapControlWeights,
)
from .model import (
    ObjectiveAssessment,
    ScoreContribution,
    StrategicObjective,
    StrategyInputs,
)


def ahead(edge: float) -> float:
    return max(edge, 0.0)


def behind(edge: float) -> float:
    return max(-edge, 0.0)


def home_security(inputs: StrategyInputs) -> float:
    """1 when nothing threatens or can reach our bases, 0 when either is total."""

    return (1.0 - inputs.immediate_threat) * (1.0 - inputs.base_exposure)


def _assessment(
    objective: StrategicObjective, terms: Iterable[tuple[str, float]]
) -> ObjectiveAssessment:
    # ``+ 0.0`` turns a -0.0 (a penalty on a zero signal) into 0.0.
    contributions = tuple(
        ScoreContribution(signal, value + 0.0) for signal, value in terms
    )
    raw = sum(item.contribution for item in contributions)
    return ObjectiveAssessment(
        objective=objective,
        score=min(max(raw, 0.0), 1.0),
        contributions=contributions,
    )


def score_stabilize(
    inputs: StrategyInputs, weights: StabilizeWeights
) -> ObjectiveAssessment:
    return _assessment(
        StrategicObjective.STABILIZE,
        (
            ("immediate_threat", weights.immediate_threat * inputs.immediate_threat),
            ("base_exposure", weights.base_exposure * inputs.base_exposure),
            ("military_edge", weights.military_deficit * behind(inputs.military_edge)),
        ),
    )


def score_recover(
    inputs: StrategyInputs, weights: RecoverWeights
) -> ObjectiveAssessment:
    return _assessment(
        StrategicObjective.RECOVER,
        (
            ("economic_edge", weights.economic_deficit * behind(inputs.economic_edge)),
            ("military_edge", weights.military_deficit * behind(inputs.military_edge)),
            (
                "territory_edge",
                weights.territory_deficit * behind(inputs.territory_edge),
            ),
            ("home_security", weights.instability * (1.0 - home_security(inputs))),
            ("immediate_threat", -weights.immediate_threat * inputs.immediate_threat),
        ),
    )


def score_build_advantage(
    inputs: StrategyInputs, weights: BuildAdvantageWeights
) -> ObjectiveAssessment:
    military = inputs.military_edge
    return _assessment(
        StrategicObjective.BUILD_ADVANTAGE,
        (
            ("baseline", weights.baseline),
            ("home_security", weights.home_security * home_security(inputs)),
            ("immediate_threat", -weights.immediate_threat * inputs.immediate_threat),
            (
                "military_edge",
                -weights.military_deficit * behind(military)
                - weights.military_surplus * ahead(military),
            ),
            ("economic_edge", -weights.economic_deficit * behind(inputs.economic_edge)),
            (
                "knowledge_confidence",
                weights.uncertainty * (1.0 - inputs.knowledge_confidence),
            ),
        ),
    )


def score_take_map_control(
    inputs: StrategyInputs, weights: TakeMapControlWeights
) -> ObjectiveAssessment:
    """Wants a sufficient army and territory left to take.

    ``support = min(ahead(military_edge) / military_sufficient, 1)``. The
    ``military_edge`` contribution also takes back the confident edge beyond
    ``military_sufficient``: that much advantage is PRESSURE's to use.
    """

    military = inputs.military_edge
    support = min(ahead(military) / weights.military_sufficient, 1.0)
    surplus = max(ahead(military) - weights.military_sufficient, 0.0)
    return _assessment(
        StrategicObjective.TAKE_MAP_CONTROL,
        (
            (
                "military_edge",
                weights.military_edge * support
                - weights.military_surplus * surplus * inputs.knowledge_confidence
                - weights.military_deficit * behind(military),
            ),
            ("home_security", weights.home_security * home_security(inputs)),
            (
                "territory_edge",
                weights.territory_room * (1.0 - ahead(inputs.territory_edge)) * support,
            ),
            (
                "knowledge_confidence",
                weights.knowledge_confidence * inputs.knowledge_confidence,
            ),
            ("immediate_threat", -weights.immediate_threat * inputs.immediate_threat),
        ),
    )


def score_pressure(
    inputs: StrategyInputs, weights: PressureWeights
) -> ObjectiveAssessment:
    """Credits only the military edge we are confident in.

    ``military_edge`` reports the full edge; ``knowledge_confidence``
    reports what low confidence takes back from it, plus a flat uncertainty
    penalty. Their sum credits ``edge * knowledge_confidence``.
    """

    military = weights.military_edge * ahead(inputs.military_edge)
    uncertainty = 1.0 - inputs.knowledge_confidence
    return _assessment(
        StrategicObjective.PRESSURE,
        (
            ("military_edge", military),
            (
                "knowledge_confidence",
                -(military + weights.uncertainty) * uncertainty,
            ),
            ("home_security", weights.home_security * home_security(inputs)),
            ("economic_edge", weights.economic_edge * ahead(inputs.economic_edge)),
            ("territory_edge", weights.territory_edge * ahead(inputs.territory_edge)),
            ("immediate_threat", -weights.immediate_threat * inputs.immediate_threat),
        ),
    )


def assess_objectives(
    inputs: StrategyInputs, config: StrategyConfig
) -> tuple[ObjectiveAssessment, ...]:
    """Every objective's assessment, in ``StrategicObjective`` order."""

    return (
        score_stabilize(inputs, config.stabilize),
        score_recover(inputs, config.recover),
        score_build_advantage(inputs, config.build_advantage),
        score_take_map_control(inputs, config.take_map_control),
        score_pressure(inputs, config.pressure),
    )
