"""Types local to Reaper worker-line harass."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind


@dataclass(frozen=True, slots=True)
class ReaperTargetHeuristics:
    """How a lone Reaper reads one enemy base as a raid target.

    Not the Banshee reading with ground swapped for air. A Reaper raid is a
    short, finite visit by one cheap, fast unit that climbs cliffs, kills a
    worker at a time, runs home on its own at low health, and has always
    tolerated a defender or two -- a Reaper that waits for an empty mineral
    line never raids at all. So it reads::

        score =   opportunity_weight    * economic_opportunity
                - ground_defense_weight * ground_defense_risk
                - army_weight           * army_risk
                - uncertainty_weight    * (1 - information_confidence)

    economic_opportunity
        Leans on the worker line (``value_share`` is small): a Reaper hurts
        workers, not the base.
    ground_defense_risk
        Only the believed ``ground_defense`` above
        ``tolerated_ground_defense`` counts, rescaled so 1.0 still means
        fully defended. Where ``ground_defense_confidence`` does not cover
        the reading, it is assumed to be at least ``assumed_ground_defense``.
        Defense that only shoots air cannot touch a Reaper and is not read.
    army_risk
        Anti-ground strength of force clusters that may be within
        ``army_reach`` -- a short reach, since a Reaper outruns what is not
        already at hand -- counted at its confidence with no floor, above
        ``tolerated_army_strength``, over ``dangerous_ground_strength``.
    information_confidence
        How recently the base was looked at. It weighs little: going to
        look is part of what a Reaper is for.

    The score only ranks; a raid launches at a target only while both risks
    stay within ``max_ground_defense_risk`` and ``max_army_risk``. These are
    first guesses, to be calibrated against real games.
    """

    opportunity_weight: float = 1.0
    value_share: float = 0.3
    full_worker_line: float = 16.0

    ground_defense_weight: float = 1.0
    assumed_ground_defense: float = 0.35
    # About one Queen or Spine Crawler: 2 of the 8 that read as fully defended.
    tolerated_ground_defense: float = 0.25

    army_weight: float = 1.0
    army_contact_radius: float = 6.0
    army_reach: float = 25.0
    # In supply, like the cluster strengths.
    tolerated_army_strength: float = 2.0
    dangerous_ground_strength: float = 6.0

    uncertainty_weight: float = 0.05

    max_ground_defense_risk: float = 0.6
    max_army_risk: float = 0.6

    # The next raid only leaves the last raid's base for one scoring this
    # much more.
    retarget_margin: float = 0.15
    # A fallback location has no base reading; it scores as a base this rich.
    fallback_opportunity: float = 0.5

    def __post_init__(self) -> None:
        for name in (
            "opportunity_weight",
            "ground_defense_weight",
            "army_weight",
            "uncertainty_weight",
            "army_contact_radius",
            "tolerated_army_strength",
            "retarget_margin",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")
        for name in (
            "value_share",
            "assumed_ground_defense",
            "max_ground_defense_risk",
            "max_army_risk",
            "fallback_opportunity",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if not 0.0 <= self.tolerated_ground_defense < 1.0:
            raise ValueError("tolerated_ground_defense must be within [0, 1)")
        for name in ("full_worker_line", "dangerous_ground_strength"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.army_reach <= self.army_contact_radius:
            raise ValueError("army_reach must exceed army_contact_radius")


@dataclass(frozen=True, slots=True)
class ReaperHarassConfig:
    """Tuning for the single-Reaper raid on a worker line.

    Unlike the Banshee squad, this raid only ever has one or two precious
    Reapers, so it withholds unless one is genuinely idle and healthy right
    now -- never stealing the Reaper mid-scout to propose a raid that would
    just get preempted.
    """

    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.REAPER})
    )
    minimum_workers: int = 16
    proposal_cadence: float = 45.0
    priority: int = 60
    mission_timeout: float = 60.0
    failure_cooldown: float = 30.0
    minimum_unit_health: float = 0.5
    commitment_seconds: float = 5.0

    # --- targeting ----------------------------------------------------------
    targeting: ReaperTargetHeuristics = field(default_factory=ReaperTargetHeuristics)
    # Every enemy base Awareness has confirmed is a candidate. Only while
    # there is none do these locations, once observed, stand in -- the
    # natural being the fixed target the raid used before bases were
    # assessed.
    fallback_target_keys: tuple[str, ...] = ("enemy_natural",)

    # --- tactics ----------------------------------------------------------
    worker_search_radius: float = 16.0
    arrival_radius: float = 3.0
    retreat_health: float = 0.40
    retreat_arrival_radius: float = 10.0

    mission_kind: MissionKind = MissionKind.HARASS

    def __post_init__(self) -> None:
        if any(not key.strip() for key in self.fallback_target_keys):
            raise ValueError("fallback_target_keys must not be blank")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum_workers < 1:
            raise ValueError("minimum_workers must be at least 1")
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
        for name in (
            "worker_search_radius",
            "arrival_radius",
            "retreat_arrival_radius",
        ):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if not 0.0 <= self.retreat_health <= 1.0:
            raise ValueError("retreat_health must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ReaperTargetAssessment:
    """One enemy base read as a Reaper raid target. A reading, not a choice."""

    key: str
    position: Point2
    score: float
    economic_opportunity: float
    ground_defense_risk: float
    army_risk: float
    information_confidence: float
    workers: int
    viable: bool
    # When the place was last looked at, for the proposal's evidence fields.
    last_observed_at: float | None
    age: float | None
    stale_after: float | None
    # Not an assessed base: an observed location standing in for one.
    is_fallback: bool = False

    def summary(self) -> str:
        text = (
            f"{self.key} score={self.score:.2f}"
            f" value={self.economic_opportunity:.2f}"
            f" ground={self.ground_defense_risk:.2f}"
            f" army_risk={self.army_risk:.2f}"
            f" confidence={self.information_confidence:.2f}"
        )
        if self.is_fallback:
            text += " fallback"
        if not self.viable:
            text += " not_viable"
        return text


@dataclass(frozen=True, slots=True)
class ReaperHarassAssessment:
    """Whether a Reaper raid is currently available, and where it could go."""

    now: float
    reapers_available: int
    workers: int
    # Every candidate target, best score first, viable or not.
    targets: tuple[ReaperTargetAssessment, ...]
    readiness: float

    @property
    def viable_targets(self) -> tuple[ReaperTargetAssessment, ...]:
        return tuple(target for target in self.targets if target.viable)

    @property
    def preferred_target(self) -> ReaperTargetAssessment | None:
        """The best-scoring viable target. The planner may hold another."""

        return next(iter(self.viable_targets), None)

    def log_fields(self) -> dict[str, Any]:
        target = self.preferred_target
        return {
            "readiness": round(self.readiness, 2),
            "reapers_available": self.reapers_available,
            "workers": self.workers,
            "target": None if target is None else target.key,
            "target_score": None if target is None else round(target.score, 2),
            "candidates": len(self.targets),
            "viable_candidates": len(self.viable_targets),
        }


@dataclass(frozen=True, slots=True)
class ReaperHarassPlan:
    target: ReaperTargetAssessment
    priority: int
    reason: str
    readiness: float

    def log_fields(self) -> dict[str, Any]:
        return {
            "target": self.target.key,
            "target_score": round(self.target.score, 2),
            "priority": self.priority,
            "reason": self.reason,
            "readiness": round(self.readiness, 2),
        }
