"""Mission Policy: every behavior's opportunities on one comparable scale.

A behavior planner describes a concrete opportunity in local terms only --
how good it is, how urgent, how risky, what it would teach us
(``MissionSignals``). This policy, and nothing else, weighs those terms
against the current ``StrategicIntent`` and turns the result into the mission
engine's 0..100 priority. The engine only ever sees that final number.

It ranks; it does not choose. Several opportunities can rank high at once,
and which of them actually gets units stays the allocator's decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any

from .intent import StrategicActivity, StrategicIntent

_SIGNALS = ("opportunity", "urgency", "risk", "information_gain", "control_alignment")


@dataclass(frozen=True, slots=True)
class MissionSignals:
    """One opportunity as the planner that found it sees it. No strategy here.

    - ``activity``: which strategic preference the work serves; ``None`` for
      the fallback owner, which serves none and ranks at a fixed floor.
    - ``opportunity``: 0 (pointless) .. 1 (as good as this kind of work gets)
      if we pursue it, judged locally: value at the target, fit of the force.
    - ``urgency``: 0 (can wait indefinitely) .. 1 (a loss is happening now and
      every second of delay costs).
    - ``risk``: 0 (safe) .. 1 (the units sent are likely lost).
    - ``information_gain``: 0 (we would learn nothing) .. 1 (it resolves what
      we know least).
    - ``control_objective``: the id of the Strategy control objective the work
      serves, if any; ``control_alignment`` 0..1 how directly it serves it.
    - ``reason``: the planner's short explanation.
    """

    activity: StrategicActivity | None
    opportunity: float = 0.0
    urgency: float = 0.0
    risk: float = 0.0
    information_gain: float = 0.0
    control_objective: str | None = None
    control_alignment: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        for name in _SIGNALS:
            value = getattr(self, name)
            # NaN fails this comparison too.
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1], got {value}")
        if self.control_objective is not None and not self.control_objective.strip():
            raise ValueError("control_objective must not be blank")
        if self.control_alignment > 0.0 and self.control_objective is None:
            raise ValueError("control_alignment needs a control_objective")

    @classmethod
    def fallback(cls, reason: str) -> MissionSignals:
        """The fallback owner's signals: no activity, nothing to weigh."""

        return cls(activity=None, reason=reason)

    @property
    def is_fallback(self) -> bool:
        return self.activity is None

    def log_fields(self) -> dict[str, Any]:
        return {
            "activity": "FALLBACK" if self.activity is None else self.activity.name,
            "opportunity": round(self.opportunity, 3),
            "urgency": round(self.urgency, 3),
            "risk": round(self.risk, 3),
            "information_gain": round(self.information_gain, 3),
            "control_objective": self.control_objective,
            "control_alignment": round(self.control_alignment, 3),
            "signal_reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class ControlNeed:
    """What a control objective still asks for, as Strategy reads it.

    ``importance`` 0..1 is how much the objective matters; ``gap`` 0..1 how
    far current control or visibility falls short of the desired level.
    """

    importance: float
    gap: float

    def __post_init__(self) -> None:
        for name in ("importance", "gap"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1], got {value}")

    @property
    def value(self) -> float:
        return self.importance * self.gap


@dataclass(frozen=True, slots=True)
class MissionPolicyConfig:
    """Every number behind cross-behavior ranking, in one place.

    First guesses, like the rest of Strategy's weights; see
    ``docs/strategy.md`` for the formula they enter.
    """

    # --- the priority scale ------------------------------------------------
    # The fallback owner's fixed rank ...
    fallback_priority: int = 20
    # ... and the lowest rank of any real opportunity. The gap is at least the
    # allocator's preemption margin, so every real mission can still take
    # units from the fallback owner.
    minimum_priority: int = 30
    maximum_priority: int = 100

    # --- value of the opportunity ------------------------------------------
    opportunity_weight: float = 0.55
    # Scaled by how much Strategy wants information.
    information_weight: float = 0.20
    # Scaled by the served objective's importance, gap and the alignment.
    control_weight: float = 0.25
    # Share of the value an activity Strategy does not want at all keeps.
    desirability_floor: float = 0.25
    # How much of the utility the (desirability-scaled) value can reach.
    value_share: float = 0.70

    # --- urgency -----------------------------------------------------------
    urgency_weight: float = 0.30
    # Above this urgency a floor rises, independent of strategic preference:
    # a stale preference never buries an obvious emergency ...
    emergency_urgency: float = 0.5
    # ... reaching this utility at urgency 1.
    emergency_utility: float = 0.95

    # --- risk ----------------------------------------------------------------
    risk_weight: float = 0.40
    # Share of the risk penalty that remains even at full risk tolerance.
    unavoidable_risk_share: float = 0.15

    def __post_init__(self) -> None:
        if not (
            0
            <= self.fallback_priority
            < self.minimum_priority
            <= self.maximum_priority
            <= 100
        ):
            raise ValueError(
                "expected 0 <= fallback < minimum <= maximum <= 100 priorities"
            )
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, float) and not (math.isfinite(value) and value >= 0):
                raise ValueError(f"{item.name} must be finite and not negative")
        for name in (
            "desirability_floor",
            "value_share",
            "emergency_utility",
            "unavoidable_risk_share",
        ):
            if getattr(self, name) > 1.0:
                raise ValueError(f"{name} must be within [0, 1]")
        if not 0.0 <= self.emergency_urgency < 1.0:
            raise ValueError("emergency_urgency must be within [0, 1)")


@dataclass(frozen=True, slots=True)
class MissionRanking:
    """One opportunity's final rank and every term that produced it.

    ``raw_utility`` is the exact signed sum of the contributions; ``utility``
    is that sum, raised to ``urgency_floor`` when the floor is higher, and
    clamped into [0, 1]. ``priority`` is ``utility`` on the engine's scale.
    """

    utility: float
    priority: int
    strategic_desirability: float
    opportunity_contribution: float
    information_contribution: float
    control_contribution: float
    urgency_contribution: float
    risk_penalty: float
    urgency_floor: float

    @property
    def raw_utility(self) -> float:
        return (
            self.opportunity_contribution
            + self.information_contribution
            + self.control_contribution
            + self.urgency_contribution
            - self.risk_penalty
        )

    @property
    def floor_applied(self) -> bool:
        return self.urgency_floor > self.raw_utility

    def log_fields(self) -> dict[str, Any]:
        return {
            "utility": round(self.utility, 3),
            "priority": self.priority,
            "strategic_desirability": round(self.strategic_desirability, 3),
            "opportunity_contribution": round(self.opportunity_contribution, 3),
            "information_contribution": round(self.information_contribution, 3),
            "control_contribution": round(self.control_contribution, 3),
            "urgency_contribution": round(self.urgency_contribution, 3),
            "risk_penalty": round(self.risk_penalty, 3),
            "urgency_floor": round(self.urgency_floor, 3),
            "floor_applied": self.floor_applied,
        }


def score_mission(
    signals: MissionSignals,
    intent: StrategicIntent,
    *,
    need: ControlNeed | None = None,
    config: MissionPolicyConfig | None = None,
) -> MissionRanking:
    """Rank one opportunity under the current intent.

    ::

        desirability = floor + (1 - floor) * intent[activity]
        value        = value_share * desirability * (
                           opportunity_weight * opportunity
                         + information_weight * information_gain * intent.information
                         + control_weight * alignment * importance * gap)
        urgency      = urgency_weight * urgency
        risk         = risk_weight * risk
                       * (unavoidable + (1 - unavoidable) * (1 - risk_tolerance))
        floor        = emergency_utility
                       * clamp((urgency - emergency_urgency) / (1 - emergency_urgency))
        utility      = clamp(max(value + urgency - risk, floor), 0, 1)

    The fallback owner (``activity is None``) is not weighed at all: it ranks
    at ``fallback_priority``.
    """

    config = config or MissionPolicyConfig()
    if signals.activity is None:
        return MissionRanking(
            utility=0.0,
            priority=config.fallback_priority,
            strategic_desirability=0.0,
            opportunity_contribution=0.0,
            information_contribution=0.0,
            control_contribution=0.0,
            urgency_contribution=0.0,
            risk_penalty=0.0,
            urgency_floor=0.0,
        )

    desirability = intent.desirability(signals.activity)
    scale = config.value_share * (
        config.desirability_floor + (1.0 - config.desirability_floor) * desirability
    )
    control_value = 0.0 if need is None else need.value
    unavoidable = config.unavoidable_risk_share
    ranking_terms = {
        "opportunity_contribution": scale
        * config.opportunity_weight
        * signals.opportunity,
        "information_contribution": scale
        * config.information_weight
        * signals.information_gain
        * intent.information,
        "control_contribution": scale
        * config.control_weight
        * signals.control_alignment
        * control_value,
        "urgency_contribution": config.urgency_weight * signals.urgency,
        "risk_penalty": config.risk_weight
        * signals.risk
        * (unavoidable + (1.0 - unavoidable) * (1.0 - intent.risk_tolerance)),
    }
    raw = (
        ranking_terms["opportunity_contribution"]
        + ranking_terms["information_contribution"]
        + ranking_terms["control_contribution"]
        + ranking_terms["urgency_contribution"]
        - ranking_terms["risk_penalty"]
    )
    floor = config.emergency_utility * _clamp01(
        (signals.urgency - config.emergency_urgency)
        / (1.0 - config.emergency_urgency)
    )
    utility = _clamp01(max(raw, floor))
    return MissionRanking(
        utility=utility,
        priority=to_priority(utility, config),
        strategic_desirability=desirability,
        urgency_floor=floor,
        **ranking_terms,
    )


def to_priority(utility: float, config: MissionPolicyConfig | None = None) -> int:
    """Utility 0..1 on the engine's scale: the only such conversion.

    Every real opportunity lands in ``[minimum_priority, maximum_priority]``,
    strictly above the fallback owner.
    """

    config = config or MissionPolicyConfig()
    if math.isnan(utility):
        raise ValueError("utility must not be NaN")
    span = config.maximum_priority - config.minimum_priority
    return config.minimum_priority + round(span * _clamp01(utility))


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


__all__ = [
    "ControlNeed",
    "MissionPolicyConfig",
    "MissionRanking",
    "MissionSignals",
    "score_mission",
    "to_priority",
]
