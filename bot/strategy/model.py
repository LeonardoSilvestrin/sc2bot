from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto


class StrategicObjective(Enum):
    """The dominant strategic direction: what we are trying to achieve now.

    An objective names a direction, never an execution: no target, base,
    army, build or production choice. Declaration order runs from the most
    defensive to the most aggressive, and is the tie-break order: on equal
    scores the earlier (more conservative) objective wins.
    """

    STABILIZE = auto()
    RECOVER = auto()
    BUILD_ADVANTAGE = auto()
    TAKE_MAP_CONTROL = auto()
    PRESSURE = auto()


EDGE_RANGE = (-1.0, 1.0)
UNIT_RANGE = (0.0, 1.0)

# Every input signal and the closed range it must lie in.
SIGNAL_RANGES: dict[str, tuple[float, float]] = {
    "military_edge": EDGE_RANGE,
    "economic_edge": EDGE_RANGE,
    "territory_edge": EDGE_RANGE,
    "immediate_threat": UNIT_RANGE,
    "base_exposure": UNIT_RANGE,
    "knowledge_confidence": UNIT_RANGE,
}


@dataclass(frozen=True, slots=True)
class StrategyInputs:
    """The normalized signals Strategy decides from, and nothing else.

    A pure strategic contract: it knows no snapshot, unit or position.

    - ``military_edge``, ``economic_edge``, ``territory_edge``: -1 (clearly
      behind) .. 0 (even, or unknown) .. +1 (clearly ahead). An edge we
      cannot read is 0, never positive: not knowing the enemy is not the
      enemy being weak.
    - ``immediate_threat``: 0 .. 1, how much enemy force is acting on our
      position right now.
    - ``base_exposure``: 0 .. 1, how reachable our held bases are to enemy
      forces, whether or not any is coming.
    - ``knowledge_confidence``: 0 (we know nothing about the enemy) .. 1
      (current, complete knowledge).

    Out-of-range and NaN values are rejected; ``clamped`` is the lenient
    constructor for callers whose arithmetic may drift past a bound.
    """

    military_edge: float
    economic_edge: float
    territory_edge: float
    immediate_threat: float
    base_exposure: float
    knowledge_confidence: float

    def __post_init__(self) -> None:
        for name, (low, high) in SIGNAL_RANGES.items():
            value = getattr(self, name)
            # NaN fails this comparison too.
            if not low <= value <= high:
                raise ValueError(f"{name} must be within [{low}, {high}], got {value}")

    @classmethod
    def clamped(
        cls,
        *,
        military_edge: float,
        economic_edge: float,
        territory_edge: float,
        immediate_threat: float,
        base_exposure: float,
        knowledge_confidence: float,
    ) -> StrategyInputs:
        """Build inputs with every signal clamped into its range.

        NaN is still rejected: it is a broken signal, not a slightly
        out-of-range one.
        """

        values = {
            "military_edge": military_edge,
            "economic_edge": economic_edge,
            "territory_edge": territory_edge,
            "immediate_threat": immediate_threat,
            "base_exposure": base_exposure,
            "knowledge_confidence": knowledge_confidence,
        }
        clamped: dict[str, float] = {}
        for name, value in values.items():
            if math.isnan(value):
                raise ValueError(f"{name} must not be NaN")
            low, high = SIGNAL_RANGES[name]
            clamped[name] = min(max(float(value), low), high)
        return cls(**clamped)


@dataclass(frozen=True, slots=True)
class ScoreContribution:
    """How much one signal moved one objective's score, signed."""

    signal: str
    contribution: float


@dataclass(frozen=True, slots=True)
class ObjectiveAssessment:
    """One objective's score and the contributions that make it up.

    ``raw_score`` is the exact sum of ``contributions``; ``score`` is that
    sum clamped into [0, 1]. Each signal appears at most once.
    """

    objective: StrategicObjective
    score: float
    contributions: tuple[ScoreContribution, ...]

    @property
    def raw_score(self) -> float:
        return sum(item.contribution for item in self.contributions)

    def contribution(self, signal: str) -> float:
        """The signed contribution of ``signal``; 0 if it does not take part."""

        return next(
            (item.contribution for item in self.contributions if item.signal == signal),
            0.0,
        )


@dataclass(frozen=True, slots=True)
class StrategySnapshot:
    """The strategic direction held after one director update.

    - ``objective``: the objective in force, after hysteresis. It can differ
      from ``leader``, the best-scoring objective this update.
    - ``confidence``: how clearly ``objective`` leads the best other
      objective, 0 (tied, or held by hysteresis against a better score) ..
      1 (ahead by at least ``StrategyConfig.clear_lead``).
    - ``assessments``: every objective's score, in ``StrategicObjective``
      order.
    - ``previous_objective``: what ``objective`` replaced; ``None`` before
      the first switch.
    - ``game_time``: when this snapshot was computed.
    - ``time_in_objective``: how long ``objective`` has been held at
      ``game_time``.
    - ``inputs``: the signals it was computed from.
    """

    objective: StrategicObjective
    confidence: float
    assessments: tuple[ObjectiveAssessment, ...]
    previous_objective: StrategicObjective | None
    game_time: float
    time_in_objective: float
    inputs: StrategyInputs

    def assessment(self, objective: StrategicObjective) -> ObjectiveAssessment:
        return next(item for item in self.assessments if item.objective is objective)

    def score(self, objective: StrategicObjective) -> float:
        return self.assessment(objective).score

    @property
    def leader(self) -> StrategicObjective:
        return leading(self.assessments).objective


def leading(assessments: tuple[ObjectiveAssessment, ...]) -> ObjectiveAssessment:
    """The best-scoring assessment; ties go to the earliest one."""

    best = assessments[0]
    for item in assessments[1:]:
        if item.score > best.score:
            best = item
    return best
