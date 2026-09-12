"""Everything Banshee harass needs to describe itself.

These types are local on purpose: `BansheeHarassAssessment` and
`BansheeHarassPlan` mean nothing outside this folder, and nothing outside
this folder should have to know them. Only the genuinely shared vocabulary
(`Mission`, `MissionProposal`, `UnitRequirement`, `MissionResult`) lives in
`bot.engine.missions`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind


@dataclass(frozen=True, slots=True)
class BansheeTargetHeuristics:
    """How a cloaked Banshee reads one enemy base as a raid target.

    Every weight of that reading lives here::

        score =   opportunity_weight    * economic_opportunity
                - air_defense_weight    * air_defense_risk
                - ground_defense_weight * ground_defense
                - army_weight           * army_risk
                - uncertainty_weight    * (1 - information_confidence)

    economic_opportunity
        ``value_share`` of the base's ``economic_value``, the rest from how
        full a worker line was last counted there.
    air_defense_risk
        The base's ``air_defense`` as far as ``air_defense_confidence``
        covers it; the uncovered share is assumed to hold at least
        ``assumed_air_defense``. Anti-air nobody has looked for recently is
        unknown, not absent -- while anti-air already seen never shrinks.
    ground_defense
        Barely counts: nothing that only shoots ground can touch a Banshee,
        so a base full of it is only a hint that it is being held.
    army_risk
        Anti-air strength of every enemy force cluster that may be within
        ``army_reach``: in full inside ``army_contact_radius``, fading to
        nothing at ``army_reach``, and counted from ``army_confidence_floor``
        at confidence 0 up to in full at confidence 1 -- over
        ``dangerous_anti_air_strength``. A cluster's distance already allows
        for its spread and for how far it may have moved since it was seen.
    information_confidence
        How recently the base itself was looked at.

    The score only ranks. What lets a raid launch at a target is viability:
    both risks within ``max_air_defense_risk`` and ``max_army_risk``. These
    are first guesses, to be calibrated against real games.
    """

    opportunity_weight: float = 1.0
    value_share: float = 0.6
    full_worker_line: float = 16.0

    air_defense_weight: float = 1.0
    # One anti-air structure's worth: 2 of the 8 that read as fully defended.
    assumed_air_defense: float = 0.25
    ground_defense_weight: float = 0.1

    army_weight: float = 0.8
    army_contact_radius: float = 10.0
    army_reach: float = 45.0
    army_confidence_floor: float = 0.35
    # In supply: six Marines, or three Hydralisks, Stalkers or Queens.
    dangerous_anti_air_strength: float = 6.0

    uncertainty_weight: float = 0.15

    max_air_defense_risk: float = 0.4
    max_army_risk: float = 0.5

    # The raid only leaves the target it holds for one scoring this much more.
    retarget_margin: float = 0.15
    # A fallback location has no base reading; it scores as a base this rich.
    fallback_opportunity: float = 0.5

    def __post_init__(self) -> None:
        for name in (
            "opportunity_weight",
            "air_defense_weight",
            "ground_defense_weight",
            "army_weight",
            "uncertainty_weight",
            "army_contact_radius",
            "retarget_margin",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")
        for name in (
            "value_share",
            "assumed_air_defense",
            "army_confidence_floor",
            "max_air_defense_risk",
            "max_army_risk",
            "fallback_opportunity",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        for name in ("full_worker_line", "dangerous_anti_air_strength"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if self.army_reach <= self.army_contact_radius:
            raise ValueError("army_reach must exceed army_contact_radius")


@dataclass(frozen=True, slots=True)
class BansheeHarassConfig:
    """Tuning for the whole raid: when it starts, where, and how it is flown.

    The launch and tactical values are the ones the raid has been played
    with. Where it flies is read from Awareness through ``targeting``.
    """

    # --- strategy: when does this raid make sense at all -------------------
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: frozenset({UnitTypeId.BANSHEE})
    )
    minimum_workers: int = 12
    # Reproposing frequently keeps the standing squad's desired count
    # current, so a freshly produced Banshee joins the raid within a few
    # seconds instead of waiting out a long cadence.
    proposal_cadence: float = 8.0
    priority: int = 62
    mission_timeout: float = 70.0
    failure_cooldown: float = 30.0
    minimum_unit_health: float = 0.5
    commitment_seconds: float = 5.0
    strategic_intent: str = "banshee_harass"
    cloak_upgrade: UpgradeId = UpgradeId.BANSHEECLOAK
    # Squad size the readiness score is measured against. Not a launch gate:
    # the raid still starts with one Banshee, this only says when it reads
    # as fully assembled.
    preferred_squad_size: int = 2

    # --- targeting: where the raid flies ----------------------------------
    targeting: BansheeTargetHeuristics = field(
        default_factory=BansheeTargetHeuristics
    )
    # Every enemy base Awareness has confirmed is a candidate. Only while
    # there is none do these locations, once observed, stand in -- the
    # natural being the fixed target the raid flew to before bases were
    # assessed.
    fallback_target_keys: tuple[str, ...] = ("enemy_natural",)

    # --- tactics: how the raid is flown once it is live -------------------
    disengage_radius: float = 12.0
    arrival_radius: float = 3.0
    infiltration_radius: float = 12.0
    retreat_health: float = 0.45
    # What it costs to pull these Banshees off the raid right now, added to
    # the allocator's preemption margin. Deliberately smaller than the gap
    # between AIR_HARASS (62) and DEFENSE (85): a base under attack still
    # wins the Banshees mid-strike, a same-tier mission no longer does.
    strike_preemption_cost: float = 5.0

    mission_kind: MissionKind = MissionKind.AIR_HARASS
    squad_id: str = "banshee_harass"

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
        if not self.strategic_intent.strip():
            raise ValueError("strategic_intent must not be blank")
        if self.preferred_squad_size < 1:
            raise ValueError("preferred_squad_size must be at least 1")
        for name in ("disengage_radius", "arrival_radius", "infiltration_radius"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if not 0.0 <= self.retreat_health <= 1.0:
            raise ValueError("retreat_health must be between 0 and 1")
        if self.strike_preemption_cost < 0.0:
            raise ValueError("strike_preemption_cost must not be negative")
        if not self.squad_id.strip():
            raise ValueError("squad_id must not be blank")


@dataclass(frozen=True, slots=True)
class BansheeTargetAssessment:
    """One enemy base read as a Banshee raid target. A reading, not a choice.

    The components sit next to the score they add up to, so a log line can
    say why a base ranks where it does.
    """

    key: str
    position: Point2
    score: float
    economic_opportunity: float
    air_defense_risk: float
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
            f" aa={self.air_defense_risk:.2f}"
            f" army_risk={self.army_risk:.2f}"
            f" confidence={self.information_confidence:.2f}"
        )
        if self.is_fallback:
            text += " fallback"
        if not self.viable:
            text += " not_viable"
        return text


@dataclass(frozen=True, slots=True)
class BansheeHarassAssessment:
    """The situation, read through the Banshee-harass lens. No decisions here.

    Everything below is derived from Attention and Awareness only. It does
    not know whether a mission exists, and it never asks.
    """

    now: float
    # Every Banshee we own, whether or not it has finished morphing --
    # this is the count the raid is sized against.
    banshees_alive: int
    banshees_ready: int
    banshees_pending: int
    cloak_ready: bool
    cloak_progress: float
    workers: int
    build_supports_harass: bool
    # Every candidate target, best score first, viable or not.
    targets: tuple[BansheeTargetAssessment, ...]
    known_anti_air_units: int
    enemy_army_position: Point2 | None
    readiness: float
    risk: float

    @property
    def viable_targets(self) -> tuple[BansheeTargetAssessment, ...]:
        return tuple(target for target in self.targets if target.viable)

    @property
    def preferred_target(self) -> BansheeTargetAssessment | None:
        """The best-scoring target it would be safe to launch at, if any.

        Which target the raid actually flies to is the planner's call: it
        holds on to its current one until another is clearly better, and a
        live raid may keep a target that is no longer viable.
        """

        return next(iter(self.viable_targets), None)

    @property
    def has_banshees(self) -> bool:
        return self.banshees_alive > 0

    def log_fields(self) -> dict[str, Any]:
        target = self.preferred_target
        return {
            "readiness": round(self.readiness, 2),
            "risk": round(self.risk, 2),
            "banshees": self.banshees_alive,
            "banshees_ready": self.banshees_ready,
            "banshees_pending": self.banshees_pending,
            "cloak": (
                "ready" if self.cloak_ready else f"{self.cloak_progress:.0%}"
            ),
            "target": None if target is None else target.key,
            "target_score": None if target is None else round(target.score, 2),
            "candidates": len(self.targets),
            "viable_candidates": len(self.viable_targets),
            "build_supports_harass": self.build_supports_harass,
        }


@dataclass(frozen=True, slots=True)
class BansheeHarassPlan:
    """What the raid intends: where, with how many, and how badly it wants it.

    Carried as the mission's payload. `MissionController` never reads inside
    it -- only this folder's executor does.
    """

    target: BansheeTargetAssessment
    desired_banshees: int
    priority: int
    reason: str
    readiness: float
    risk: float

    def log_fields(self) -> dict[str, Any]:
        return {
            "target": self.target.key,
            "target_score": round(self.target.score, 2),
            "target_viable": self.target.viable,
            "desired_banshees": self.desired_banshees,
            "priority": self.priority,
            "reason": self.reason,
            "readiness": round(self.readiness, 2),
            "risk": round(self.risk, 2),
        }


class BansheePhase(Enum):
    """Where the raid currently is in its own tactical loop.

    ASSEMBLE -> APPROACH -> INFILTRATE -> STRIKE -> EVADE -> REPOSITION,
    then back to APPROACH. The phase names what the squad is doing; the
    commands issued in APPROACH/INFILTRATE/STRIKE are deliberately the same
    cloak-and-attack-move pair, because closing the last few tiles onto a
    worker line is a change of situation, not of order.
    """

    ASSEMBLE = auto()
    APPROACH = auto()
    INFILTRATE = auto()
    STRIKE = auto()
    EVADE = auto()
    REPOSITION = auto()


@dataclass(slots=True)
class BansheeHarassState:
    """Tactical state the executor carries between frames.

    This is the local loop the strategic planner does not touch: it changes
    every frame from what the squad can see, while the plan above it is
    only re-derived on the planner's much slower cadence.
    """

    phase: BansheePhase = BansheePhase.ASSEMBLE
    retreating: bool = False
    home: Point2 | None = None

    def enter(self, phase: BansheePhase) -> bool:
        """Move to `phase`, reporting whether that was actually a change."""

        if self.phase is phase:
            return False
        self.phase = phase
        return True
