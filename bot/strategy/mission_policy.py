"""Mission Policy: every behavior's opportunities on one comparable scale.

A behavior planner describes a concrete opportunity in local terms only --
how good it is, how urgent, how risky, what it would teach us
(``MissionSignals``). This policy, and nothing else, weighs those terms
against the current ``StrategicIntent``, decides whether the opportunity is
worth executing at all, and turns a viable one into the mission engine's
0..100 priority. The engine only ever sees that final number, and only for
viable work.

It values; it does not choose units. Several viable opportunities can rank
high at once, and which of them actually gets units stays the allocator's
decision.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any

from .intent import StrategicActivity, StrategicIntent

_SIGNALS = ("opportunity", "urgency", "risk", "information_gain")

# The weakest alignment that still counts as serving a control objective: the
# work is at least half as direct as standing on the objective itself. A
# proximity kernel's positive tail is not an association -- below this a
# planner reports no match at all, so no objective id travels with a
# negligible alignment and no control value is priced for it.
MINIMUM_CONTROL_ALIGNMENT = 0.5


@dataclass(frozen=True, slots=True)
class ControlMatch:
    """A meaningful association between one candidate and one control objective.

    ``objective_id`` names the ``ControlObjective``; ``alignment`` in
    ``[MINIMUM_CONTROL_ALIGNMENT, 1]`` is how directly the work serves it.
    Weaker associations are not matches: ``from_alignment`` returns ``None``
    for them, and constructing one directly raises.
    """

    objective_id: str
    alignment: float

    def __post_init__(self) -> None:
        if not self.objective_id.strip():
            raise ValueError("objective_id must not be blank")
        # NaN fails this comparison too.
        if not MINIMUM_CONTROL_ALIGNMENT <= self.alignment <= 1.0:
            raise ValueError(
                f"alignment must be within [{MINIMUM_CONTROL_ALIGNMENT}, 1], "
                f"got {self.alignment}"
            )

    @classmethod
    def from_alignment(cls, objective_id: str, alignment: float) -> ControlMatch | None:
        """The match, or ``None`` when ``alignment`` is not a meaningful one."""

        if math.isnan(alignment):
            raise ValueError("alignment must not be NaN")
        if alignment < MINIMUM_CONTROL_ALIGNMENT:
            return None
        return cls(objective_id=objective_id, alignment=min(alignment, 1.0))


@dataclass(frozen=True, slots=True)
class MissionSignals:
    """One opportunity as the planner that found it sees it. No strategy here.

    - ``activity``: which strategic preference the work serves; ``None`` for
      the fallback owner, which serves none and ranks at a fixed floor.
    - ``opportunity``: 0 (pointless) .. 1 (as good as this kind of work gets)
      if we pursue it, judged locally: value at the target, fit of the force.
      It must not already contain a term priced below -- risk, information,
      urgency, strategic desirability or a control objective's importance.
    - ``urgency``: 0 (can wait indefinitely) .. 1 (a loss is happening now and
      every second of delay costs).
    - ``risk``: 0 (safe) .. 1 (the units sent are likely lost).
    - ``information_gain``: 0 (we would learn nothing) .. 1 (it resolves what
      we know least).
    - ``control``: the Strategy control objective the work meaningfully
      serves, if any (``ControlMatch``). Work serving none is still valid.
    - ``reason``: the planner's short explanation.
    """

    activity: StrategicActivity | None
    opportunity: float = 0.0
    urgency: float = 0.0
    risk: float = 0.0
    information_gain: float = 0.0
    control: ControlMatch | None = None
    reason: str = ""

    def __post_init__(self) -> None:
        for name in _SIGNALS:
            value = getattr(self, name)
            # NaN fails this comparison too.
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be within [0, 1], got {value}")

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
            "control_objective": (
                None if self.control is None else self.control.objective_id
            ),
            "control_alignment": (
                None if self.control is None else round(self.control.alignment, 3)
            ),
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
    """Every number behind cross-behavior valuation, in one place.

    First guesses, like the rest of Strategy's weights; see
    ``docs/strategy.md`` for the formula they enter.
    """

    # --- the priority scale ------------------------------------------------
    # The fallback owner's fixed rank ...
    fallback_priority: int = 20
    # ... and the lowest rank of any viable opportunity. The gap is at least
    # the allocator's preemption margin, so every viable mission can still
    # take units from the fallback owner.
    minimum_priority: int = 30
    maximum_priority: int = 100

    # --- viability ---------------------------------------------------------
    # A candidate is executable only when its final utility -- after the
    # emergency floor -- is above this. At 0 a candidate must be worth
    # something at all: one whose value never outweighs its risk is not
    # proposed, however it would rank against nothing.
    minimum_viable_utility: float = 0.0

    # --- value of the opportunity ------------------------------------------
    opportunity_weight: float = 0.55
    # Scaled by how much Strategy wants information.
    information_weight: float = 0.20
    # Scaled by the served objective's importance, gap and the alignment.
    control_weight: float = 0.25
    # Share of the value an activity Strategy does not want at all keeps.
    desirability_floor: float = 0.15
    # How much of the utility the (desirability-scaled) value can reach.
    value_share: float = 0.85

    # --- urgency -----------------------------------------------------------
    urgency_weight: float = 0.45
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
        if not 0.0 <= self.minimum_viable_utility < 1.0:
            raise ValueError("minimum_viable_utility must be within [0, 1)")


# Why an evaluation came out as it did. Machine-readable and stable: logs and
# the viewer key on them.
FALLBACK_OWNER = "fallback_owner"
VIABLE_POSITIVE_UTILITY = "viable_positive_utility"
VIABLE_BY_URGENCY_FLOOR = "viable_by_urgency_floor"
REJECTED_NEGATIVE_RAW_UTILITY = "rejected_negative_raw_utility"
REJECTED_UTILITY_NOT_ABOVE_MINIMUM = "rejected_utility_not_above_minimum"


@dataclass(frozen=True, slots=True)
class MissionEvaluation:
    """One candidate's complete Mission Policy evaluation, as it was decided.

    - The four contributions and ``risk_penalty`` are the exact signed parts
      of ``raw_utility``.
    - ``urgency_floor`` is the emergency floor; ``utility`` is
      ``clamp(max(raw_utility, urgency_floor), 0, 1)``.
    - ``viable`` is ``is_viable(utility)``; the fallback owner is always
      viable.
    - ``priority`` is the engine priority when viable and ``None`` otherwise:
      a rejected candidate has no rank.
    - The inputs read from Strategy are kept too: ``strategic_desirability``,
      ``information_desire`` and ``risk_tolerance`` from the intent, and
      ``control_need`` for the matched objective. ``None`` where the
      calculation did not read them (the fallback owner; no match).
    """

    activity: StrategicActivity | None
    reason: str
    viable: bool
    priority: int | None
    utility: float
    raw_utility: float
    urgency_floor: float
    opportunity_contribution: float
    information_contribution: float
    control_contribution: float
    urgency_contribution: float
    risk_penalty: float
    strategic_desirability: float | None = None
    information_desire: float | None = None
    risk_tolerance: float | None = None
    control_need: ControlNeed | None = None

    def __post_init__(self) -> None:
        if self.viable != (self.priority is not None):
            raise ValueError("a priority exists exactly when the evaluation is viable")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")

    @property
    def is_fallback(self) -> bool:
        return self.activity is None

    @property
    def floor_applied(self) -> bool:
        return self.urgency_floor > self.raw_utility

    def log_fields(self) -> dict[str, Any]:
        need = self.control_need
        return {
            "activity": "FALLBACK" if self.activity is None else self.activity.name,
            "reason": self.reason,
            "viable": self.viable,
            "priority": self.priority,
            "utility": round(self.utility, 3),
            "raw_utility": round(self.raw_utility, 3),
            "urgency_floor": round(self.urgency_floor, 3),
            "floor_applied": self.floor_applied,
            "opportunity_contribution": round(self.opportunity_contribution, 3),
            "information_contribution": round(self.information_contribution, 3),
            "control_contribution": round(self.control_contribution, 3),
            "urgency_contribution": round(self.urgency_contribution, 3),
            "risk_penalty": round(self.risk_penalty, 3),
            "strategic_desirability": _rounded(self.strategic_desirability),
            "information_desire": _rounded(self.information_desire),
            "risk_tolerance": _rounded(self.risk_tolerance),
            "control_importance": None if need is None else round(need.importance, 3),
            "control_gap": None if need is None else round(need.gap, 3),
        }


def is_viable(utility: float, config: MissionPolicyConfig | None = None) -> bool:
    """Whether a candidate of this final utility is worth executing at all.

    The one viability predicate: ``utility > minimum_viable_utility``.
    """

    config = config or MissionPolicyConfig()
    if math.isnan(utility):
        raise ValueError("utility must not be NaN")
    return utility > config.minimum_viable_utility


def evaluate_mission(
    signals: MissionSignals,
    intent: StrategicIntent,
    *,
    need: ControlNeed | None = None,
    config: MissionPolicyConfig | None = None,
) -> MissionEvaluation:
    """Evaluate one opportunity under the current intent.

    ::

        desirability = floor + (1 - floor) * intent[activity]
        value        = value_share * desirability * (
                           opportunity_weight * opportunity
                         + information_weight * information_gain * intent.information
                         + control_weight * alignment * importance * gap)
                       (alignment * importance * gap is 0 without a ControlMatch
                        to an objective the context still holds)
        urgency      = urgency_weight * urgency
        risk         = risk_weight * risk
                       * (unavoidable + (1 - unavoidable) * (1 - risk_tolerance))
        raw_utility  = value + urgency - risk
        floor        = emergency_utility
                       * clamp((urgency - emergency_urgency) / (1 - emergency_urgency))
        utility      = clamp(max(raw_utility, floor), 0, 1)
        viable       = utility > minimum_viable_utility
        priority     = minimum + round((maximum - minimum) * utility)   if viable

    The floor is applied before viability, so a genuine emergency stays
    viable even when its ordinary raw utility is negative. The fallback
    owner (``activity is None``) is not weighed at all: it is always viable,
    at ``fallback_priority``.
    """

    config = config or MissionPolicyConfig()
    if signals.activity is None:
        return MissionEvaluation(
            activity=None,
            reason=FALLBACK_OWNER,
            viable=True,
            priority=config.fallback_priority,
            utility=0.0,
            raw_utility=0.0,
            urgency_floor=0.0,
            opportunity_contribution=0.0,
            information_contribution=0.0,
            control_contribution=0.0,
            urgency_contribution=0.0,
            risk_penalty=0.0,
        )

    desirability = intent.desirability(signals.activity)
    scale = config.value_share * (
        config.desirability_floor + (1.0 - config.desirability_floor) * desirability
    )
    # Control is priced only for a meaningful match to an objective Strategy
    # still holds; work serving no objective keeps every other term.
    matched_need = None if signals.control is None else need
    control_value = (
        0.0
        if signals.control is None or matched_need is None
        else signals.control.alignment * matched_need.value
    )
    unavoidable = config.unavoidable_risk_share
    opportunity = scale * config.opportunity_weight * signals.opportunity
    information = (
        scale
        * config.information_weight
        * signals.information_gain
        * intent.information
    )
    control = scale * config.control_weight * control_value
    urgency = config.urgency_weight * signals.urgency
    risk = (
        config.risk_weight
        * signals.risk
        * (unavoidable + (1.0 - unavoidable) * (1.0 - intent.risk_tolerance))
    )
    raw = opportunity + information + control + urgency - risk
    floor = config.emergency_utility * _clamp01(
        (signals.urgency - config.emergency_urgency)
        / (1.0 - config.emergency_urgency)
    )
    utility = _clamp01(max(raw, floor))
    viable = is_viable(utility, config)
    if viable:
        reason = VIABLE_BY_URGENCY_FLOOR if floor > raw else VIABLE_POSITIVE_UTILITY
    elif raw < 0.0:
        reason = REJECTED_NEGATIVE_RAW_UTILITY
    else:
        reason = REJECTED_UTILITY_NOT_ABOVE_MINIMUM
    return MissionEvaluation(
        activity=signals.activity,
        reason=reason,
        viable=viable,
        priority=to_priority(utility, config) if viable else None,
        utility=utility,
        raw_utility=raw,
        urgency_floor=floor,
        opportunity_contribution=opportunity,
        information_contribution=information,
        control_contribution=control,
        urgency_contribution=urgency,
        risk_penalty=risk,
        strategic_desirability=desirability,
        information_desire=intent.information,
        risk_tolerance=intent.risk_tolerance,
        control_need=matched_need,
    )


def to_priority(utility: float, config: MissionPolicyConfig | None = None) -> int:
    """A viable utility on the engine's scale: the only such conversion.

    Every viable opportunity lands in ``[minimum_priority, maximum_priority]``,
    strictly above the fallback owner. A non-viable utility has no priority.
    """

    config = config or MissionPolicyConfig()
    if not is_viable(utility, config):
        raise ValueError(f"utility {utility} is not viable and has no priority")
    span = config.maximum_priority - config.minimum_priority
    return config.minimum_priority + round(span * _clamp01(utility))


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


__all__ = [
    "FALLBACK_OWNER",
    "MINIMUM_CONTROL_ALIGNMENT",
    "REJECTED_NEGATIVE_RAW_UTILITY",
    "REJECTED_UTILITY_NOT_ABOVE_MINIMUM",
    "VIABLE_BY_URGENCY_FLOOR",
    "VIABLE_POSITIVE_UTILITY",
    "ControlMatch",
    "ControlNeed",
    "MissionEvaluation",
    "MissionPolicyConfig",
    "MissionSignals",
    "evaluate_mission",
    "is_viable",
    "to_priority",
]
