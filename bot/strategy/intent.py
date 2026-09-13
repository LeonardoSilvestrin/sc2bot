"""Strategic intent: how much each kind of activity is wanted right now.

``StrategicObjective`` names a direction. ``StrategicIntent`` spells that
direction out in the one vocabulary behaviors and mission ranking share:
continuous preferences for defense, map control, harass and information,
plus how much risk those activities may take.

One mapping owns ``StrategicObjective -> StrategicIntent`` (``IntentConfig``
and ``derive_intent``). No behavior reads the objective itself, so the
direction is interpreted once, the same way, for everyone.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum, auto

from .model import StrategicObjective, StrategySnapshot


class StrategicActivity(Enum):
    """The kinds of work Strategy expresses a preference for.

    DEFENSE       keeping what we hold
    MAP_CONTROL   holding and contesting the space around and between bases
    HARASS        damaging the enemy economy or position
    INFORMATION   learning what we do not know
    """

    DEFENSE = auto()
    MAP_CONTROL = auto()
    HARASS = auto()
    INFORMATION = auto()


@dataclass(frozen=True, slots=True)
class StrategicIntent:
    """What Strategy currently wants, as normalized preferences.

    - ``defense``, ``map_control``, ``harass``, ``information``: 0 (not wanted
      at all) .. 1 (wanted fully). They are independent preferences, not
      shares of a whole: a direction can want defense and information at once.
    - ``risk_tolerance``: 0 (avoid losses even at the cost of the payoff) ..
      1 (accept losses for the payoff).

    Out-of-range and NaN values are rejected.
    """

    defense: float
    map_control: float
    harass: float
    information: float
    risk_tolerance: float

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            # NaN fails this comparison too.
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{item.name} must be within [0, 1], got {value}")

    def desirability(self, activity: StrategicActivity) -> float:
        """How much Strategy wants ``activity``, 0..1."""

        return float(getattr(self, _ACTIVITY_FIELDS[activity]))

    def as_dict(self) -> dict[str, float]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


_ACTIVITY_FIELDS: dict[StrategicActivity, str] = {
    StrategicActivity.DEFENSE: "defense",
    StrategicActivity.MAP_CONTROL: "map_control",
    StrategicActivity.HARASS: "harass",
    StrategicActivity.INFORMATION: "information",
}


# First guesses, as deliberately untuned as ``StrategyConfig``'s weights: only
# the relations between them are intended (STABILIZE defends and avoids risk,
# TAKE_MAP_CONTROL wants space and information, PRESSURE harasses and accepts
# risk). Match logs decide the numbers.


@dataclass(frozen=True, slots=True)
class IntentConfig:
    """The one mapping from each objective to the intent it stands for."""

    stabilize: StrategicIntent = field(
        default_factory=lambda: StrategicIntent(
            defense=0.95,
            map_control=0.15,
            harass=0.10,
            information=0.45,
            risk_tolerance=0.15,
        )
    )
    recover: StrategicIntent = field(
        default_factory=lambda: StrategicIntent(
            defense=0.75,
            map_control=0.25,
            harass=0.25,
            information=0.55,
            risk_tolerance=0.25,
        )
    )
    build_advantage: StrategicIntent = field(
        default_factory=lambda: StrategicIntent(
            defense=0.60,
            map_control=0.35,
            harass=0.55,
            information=0.55,
            risk_tolerance=0.40,
        )
    )
    take_map_control: StrategicIntent = field(
        default_factory=lambda: StrategicIntent(
            defense=0.50,
            map_control=0.85,
            harass=0.50,
            information=0.80,
            risk_tolerance=0.50,
        )
    )
    pressure: StrategicIntent = field(
        default_factory=lambda: StrategicIntent(
            defense=0.35,
            map_control=0.65,
            harass=0.90,
            information=0.60,
            risk_tolerance=0.70,
        )
    )
    # How much of the intent the objective in force owns. The remainder
    # follows every objective's score, so a close challenger already shades
    # the intent before hysteresis lets it take over -- a smooth vocabulary
    # instead of a step at every switch.
    held_share: float = 0.7
    # The intent before Strategy has produced any snapshot.
    fallback_objective: StrategicObjective = StrategicObjective.BUILD_ADVANTAGE

    def __post_init__(self) -> None:
        if not 0.0 <= self.held_share <= 1.0:
            raise ValueError("held_share must be within [0, 1]")

    def profile(self, objective: StrategicObjective) -> StrategicIntent:
        return getattr(self, objective.name.lower())


def derive_intent(
    snapshot: StrategySnapshot | None, config: IntentConfig | None = None
) -> StrategicIntent:
    """The intent a strategy snapshot stands for.

    ``held_share`` of it is the profile of the objective in force; the rest is
    the score-weighted mix of every objective's profile. Without a snapshot,
    or when no objective scores above zero, it is the held profile alone.
    """

    config = config or IntentConfig()
    if snapshot is None:
        return config.profile(config.fallback_objective)
    held = config.profile(snapshot.objective)
    total = sum(item.score for item in snapshot.assessments)
    if total <= 0.0 or config.held_share >= 1.0:
        return held
    weighted = tuple(
        (config.profile(item.objective), item.score / total)
        for item in snapshot.assessments
    )
    values = {}
    for item in fields(StrategicIntent):
        mixed = sum(
            getattr(profile, item.name) * weight for profile, weight in weighted
        )
        blended = (
            config.held_share * getattr(held, item.name)
            + (1.0 - config.held_share) * mixed
        )
        values[item.name] = min(max(blended, 0.0), 1.0)
    return StrategicIntent(**values)


__all__ = [
    "IntentConfig",
    "StrategicActivity",
    "StrategicIntent",
    "derive_intent",
]
