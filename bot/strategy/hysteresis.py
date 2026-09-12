from __future__ import annotations

from dataclasses import dataclass

from .config import StrategyConfig
from .model import ObjectiveAssessment, StrategicObjective, leading

# Absorbs float noise so a challenger exactly ``switch_margin`` ahead counts.
_TOLERANCE = 1e-9


@dataclass(frozen=True, slots=True)
class ObjectiveState:
    """The objective in force, and what ``select_objective`` needs across
    updates to keep it stable."""

    objective: StrategicObjective
    entered_at: float
    previous: StrategicObjective | None = None


def select_objective(
    *,
    state: ObjectiveState,
    assessments: tuple[ObjectiveAssessment, ...],
    immediate_threat: float,
    now: float,
    config: StrategyConfig,
) -> ObjectiveState:
    """Keep the objective in force unless a challenger clearly beats it.

    The best other objective replaces it only when both hold:

    - its score is at least the current score plus ``switch_margin``;
    - the current objective has been held ``minimum_dwell_seconds``.

    The one exception: with ``immediate_threat`` at or above
    ``emergency_threat``, STABILIZE skips the dwell (never the margin).
    """

    current = next(item for item in assessments if item.objective is state.objective)
    challenger = leading(
        tuple(item for item in assessments if item.objective is not state.objective)
    )
    if challenger.score - current.score < config.switch_margin - _TOLERANCE:
        return state

    dwelled = now - state.entered_at >= config.minimum_dwell_seconds
    emergency = (
        challenger.objective is StrategicObjective.STABILIZE
        and config.emergency_threat is not None
        and immediate_threat >= config.emergency_threat
    )
    if not (dwelled or emergency):
        return state
    return ObjectiveState(
        objective=challenger.objective, entered_at=now, previous=state.objective
    )


def decision_confidence(
    objective: StrategicObjective,
    assessments: tuple[ObjectiveAssessment, ...],
    config: StrategyConfig,
) -> float:
    """How clearly ``objective`` leads the best other objective, in [0, 1]."""

    current = next(item for item in assessments if item.objective is objective)
    runner_up = leading(
        tuple(item for item in assessments if item.objective is not objective)
    )
    lead = current.score - runner_up.score
    return min(max(lead / config.clear_lead, 0.0), 1.0)
