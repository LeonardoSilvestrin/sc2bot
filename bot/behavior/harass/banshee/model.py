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
class BansheeHarassConfig:
    """Tuning for the whole raid: when it starts, and how it is flown.

    The values are the ones the raid has been played with; this refactor
    moved them, it did not retune them.
    """

    # --- strategy: when does this raid make sense at all -------------------
    # Ordered by preference. Only the natural is configured by default --
    # the same single target the raid has always used; the tuple exists so a
    # second location can be added without reshaping assessment or planner.
    target_keys: tuple[str, ...] = ("enemy_natural",)
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
    # A flying, cloaked harasser cannot be threatened by a ground-only
    # defender, so the launch gate only withholds on anti-air actually near
    # the target -- see `disengage_radius` for the matching in-flight check.
    anti_air_check_radius: float = 15.0
    cloak_upgrade: UpgradeId = UpgradeId.BANSHEECLOAK
    # Squad size the readiness score is measured against. Not a launch gate:
    # the raid still starts with one Banshee, this only says when it reads
    # as fully assembled.
    preferred_squad_size: int = 2

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
        if not self.target_keys or any(
            not key.strip() for key in self.target_keys
        ):
            raise ValueError("target_keys must not be empty or blank")
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
        if self.anti_air_check_radius <= 0.0:
            raise ValueError("anti_air_check_radius must be positive")
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
class BansheeTarget:
    """One place the raid could go, with what is known about it."""

    key: str
    position: Point2
    last_observed_at: float | None
    age: float | None
    stale_after: float
    anti_air_nearby: int
    workers_seen: int

    @property
    def is_known(self) -> bool:
        return self.last_observed_at is not None

    @property
    def is_defended(self) -> bool:
        return self.anti_air_nearby > 0


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
    candidate_targets: tuple[BansheeTarget, ...]
    known_anti_air_units: int
    enemy_army_position: Point2 | None
    readiness: float
    risk: float

    @property
    def preferred_target(self) -> BansheeTarget | None:
        """First known target in configured order, defended or not.

        Whether a defended target is worth flying to is the planner's call
        (and it is allowed to change its mind mid-raid, which is why the
        assessment reports both `is_known` and `is_defended` rather than
        pre-filtering).
        """

        return next(
            (target for target in self.candidate_targets if target.is_known), None
        )

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
            "target_defended": None if target is None else target.is_defended,
            "build_supports_harass": self.build_supports_harass,
        }


@dataclass(frozen=True, slots=True)
class BansheeHarassPlan:
    """What the raid intends: where, with how many, and how badly it wants it.

    Carried as the mission's payload. `MissionController` never reads inside
    it -- only this folder's executor does.
    """

    target: BansheeTarget
    desired_banshees: int
    priority: int
    reason: str
    readiness: float
    risk: float

    def log_fields(self) -> dict[str, Any]:
        return {
            "target": self.target.key,
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
