"""Types local to base defense."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind
from bot.strategy import MissionSignals
from bot.world.awareness import AwarenessSnapshot, PassageTerritory
from bot.world.awareness.bases import BaseAssessment, BaseSecurityLevel

_DEFAULT_DEFENDER_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.REAPER,
        UnitTypeId.SIEGETANK,
        UnitTypeId.SIEGETANKSIEGED,
        UnitTypeId.BANSHEE,
    }
)

# Who is worth pulling, by what is attacking, as
# `UnitRequirement.type_desirability` pairs. Two flat tables instead of a
# matchup system on purpose: each rule reads in one line and changes in one
# line. A type left out keeps the neutral 1.0; 0.0 means "never request it".
_GROUND_THREAT_DESIRABILITY: tuple[tuple[UnitTypeId, float], ...] = (
    (UnitTypeId.SIEGETANK, 1.0),
    (UnitTypeId.SIEGETANKSIEGED, 1.0),
    (UnitTypeId.MARAUDER, 0.7),
    (UnitTypeId.MARINE, 0.6),
    (UnitTypeId.REAPER, 0.4),
    (UnitTypeId.BANSHEE, 0.4),
)
_AIR_ONLY_THREAT_DESIRABILITY: tuple[tuple[UnitTypeId, float], ...] = (
    (UnitTypeId.MARINE, 1.0),
    # Ground-only weapons as well, but not excluded: only ranked behind
    # every Marine.
    (UnitTypeId.MARAUDER, 0.2),
    (UnitTypeId.REAPER, 0.2),
    (UnitTypeId.SIEGETANK, 0.0),
    (UnitTypeId.SIEGETANKSIEGED, 0.0),
    (UnitTypeId.BANSHEE, 0.0),
)

_SIEGE_ANCHOR_TYPES: frozenset[UnitTypeId] = frozenset(
    {UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}
)


@dataclass(frozen=True, slots=True)
class DefenseConfig:
    """Thresholds for defense proposals, one per threatened base."""

    proposal_cadence: float = 5.0
    mission_timeout: float = 120.0
    failure_cooldown: float = 10.0
    unit_types: frozenset[UnitTypeId] = field(
        default_factory=lambda: _DEFAULT_DEFENDER_TYPES
    )
    minimum_units: int = 1
    max_desired_units: int = 6
    minimum_unit_health: float = 0.3
    commitment_seconds: float = 3.0
    remembered_threat_max_age: float = 12.0
    vision_request_ttl: float = 6.0

    # --- opportunity signals ----------------------------------------------
    # Local readings only; what the base is worth, and how a defense ranks
    # against everything else, is Strategy's (see `DefensePlanner._signals`).
    # Urgency of a base some defender already covers, rising toward 1.0 as the
    # attack outweighs that cover; an undefended base is 1.0 outright.
    threatened_urgency: float = 0.55
    # Risk to the defenders, scaled by how outweighed the base is.
    engagement_risk: float = 0.4

    # --- defender preference ------------------------------------------------
    # Used when anything attacking the base is on the ground.
    ground_threat_desirability: tuple[tuple[UnitTypeId, float], ...] = (
        _GROUND_THREAT_DESIRABILITY
    )
    # Used when every attacker is in the air.
    air_only_threat_desirability: tuple[tuple[UnitTypeId, float], ...] = (
        _AIR_ONLY_THREAT_DESIRABILITY
    )

    # --- tactics ----------------------------------------------------------
    engagement_radius: float = 25.0
    arrival_radius: float = 2.0
    # Roles (see `DefenseRole`). Both anchors sit on the line from the base
    # toward the ground threat, the siege anchor behind the screen, so a
    # Tank is never what the enemy reaches first.
    siege_anchor_offset: float = 6.0
    screen_anchor_offset: float = 12.0
    # A mobile Tank this close to its anchor sieges instead of moving.
    siege_arrival_radius: float = 2.5
    # A Tank already sieged (or sieging) only packs up once its anchor has
    # moved this far -- wider than `siege_arrival_radius` on purpose, so a
    # drifting threat does not unsiege a Tank that just set up.
    siege_reposition_distance: float = 7.0
    # Once the threat clears, how long the mission may hold its Tanks to
    # unsiege them before completing regardless.
    unsiege_timeout: float = 6.0
    # When the attack still has to come through a passage into the defended
    # base's region -- no farther out than this -- the defense holds that
    # way in, the siege anchor this far back from it toward the base.
    approach_max_distance: float = 30.0
    approach_siege_standoff: float = 6.0

    mission_kind: MissionKind = MissionKind.DEFENSE

    def __post_init__(self) -> None:
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        for name in ("threatened_urgency", "engagement_risk"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not self.unit_types:
            raise ValueError("unit_types must not be empty")
        if self.minimum_units < 1:
            raise ValueError("minimum_units must be at least 1")
        if self.max_desired_units < self.minimum_units:
            raise ValueError("max_desired_units must be >= minimum_units")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
        if self.remembered_threat_max_age <= 0.0 or self.vision_request_ttl <= 0.0:
            raise ValueError("defense vision timings must be positive")
        for name in ("ground_threat_desirability", "air_only_threat_desirability"):
            if any(not 0.0 <= value <= 1.0 for _, value in getattr(self, name)):
                raise ValueError(f"{name} values must be between 0 and 1")
        if self.engagement_radius <= 0.0 or self.arrival_radius <= 0.0:
            raise ValueError("engagement and arrival radii must be positive")
        if not 0.0 <= self.siege_anchor_offset < self.screen_anchor_offset:
            raise ValueError(
                "expected 0 <= siege_anchor_offset < screen_anchor_offset"
            )
        if not 0.0 < self.siege_arrival_radius < self.siege_reposition_distance:
            raise ValueError(
                "expected 0 < siege_arrival_radius < siege_reposition_distance"
            )
        if self.unsiege_timeout < 0.0:
            raise ValueError("unsiege_timeout must not be negative")
        if self.approach_max_distance <= 0.0 or self.approach_siege_standoff < 0.0:
            raise ValueError("invalid approach geometry")


@dataclass(frozen=True, slots=True)
class ThreatenedBase:
    """One base under attack, plus what kind of attack it is.

    `air_threats`/`ground_threats` describe the composition rather than only
    its size. The planner reads them to decide which defenders are actually
    worth pulling (see `DefenseConfig.ground_threat_desirability`).
    """

    base: BaseAssessment
    air_threats: int
    ground_threats: int

    @property
    def base_id(self) -> str:
        return self.base.base_id

    @property
    def is_critical(self) -> bool:
        return self.base.security is BaseSecurityLevel.CRITICAL

    @property
    def target(self) -> Point2:
        return self.base.nearest_threat_position or self.base.position

    @property
    def gap(self) -> float:
        """How far the threat outweighs what is already defending the base."""

        return self.base.threat_score - self.base.protection_score

    @property
    def balance(self) -> float:
        """The attack's share of everything at the base, 0 (no threat) .. 1
        (nothing defends it)."""

        threat = max(0.0, self.base.threat_score)
        total = threat + max(0.0, self.base.protection_score)
        return 0.0 if total <= 0.0 else threat / total


@dataclass(frozen=True, slots=True)
class DefenseAssessment:
    """Which of our bases are in trouble, and how badly."""

    now: float
    threatened: tuple[ThreatenedBase, ...]
    held_bases: int
    pressure: int

    @property
    def under_attack(self) -> bool:
        return bool(self.threatened)

    def log_fields(self) -> dict[str, Any]:
        return {
            "held_bases": self.held_bases,
            "threatened_bases": [item.base_id for item in self.threatened],
            "critical_bases": [
                item.base_id for item in self.threatened if item.is_critical
            ],
            "pressure": self.pressure,
            "air_threats": sum(item.air_threats for item in self.threatened),
            "ground_threats": sum(item.ground_threats for item in self.threatened),
        }


@dataclass(frozen=True, slots=True)
class DefensePlan:
    """The answer for one threatened base: go there, with this many, now."""

    base: ThreatenedBase
    desired_units: int
    reason: str
    # The local reading the Mission Policy ranks this defense from.
    signals: MissionSignals
    # Which defender types this attack makes worth pulling.
    type_desirability: tuple[tuple[UnitTypeId, float], ...] = ()
    # The passage the attack is expected through, if it has one to pass.
    approach: str | None = None

    @property
    def target(self) -> Point2:
        return self.base.target

    def log_fields(self) -> dict[str, Any]:
        return {
            "base_id": self.base.base_id,
            "desired_units": self.desired_units,
            **self.signals.log_fields(),
            "approach": self.approach,
            "reason": self.reason,
            "critical": self.base.is_critical,
            "ground_threats": self.base.ground_threats,
            "air_threats": self.base.air_threats,
            "type_desirability": {
                unit_type.name: value for unit_type, value in self.type_desirability
            },
        }


class DefenseRole(Enum):
    """What one defender does inside a defense mission.

    Owning the unit is the mission's business; *how* that unit defends is
    decided by its type. `DefendBaseExecutor` resolves it from the units it
    was handed -- neither the proposal, the allocator nor the controller
    carries a role.

        SIEGE_ANCHOR  sieges at a deliberate spot behind the fight and holds
        SCREEN        meets the threat in front of it
    """

    SIEGE_ANCHOR = auto()
    SCREEN = auto()

    @classmethod
    def for_unit_type(cls, unit_type: UnitTypeId) -> DefenseRole:
        if unit_type in _SIEGE_ANCHOR_TYPES:
            return cls.SIEGE_ANCHOR
        return cls.SCREEN


class SiegePhase(Enum):
    """Where one SIEGE_ANCHOR Tank is in its own loop.

        MOVING_TO_ANCHOR -> SIEGING -> SIEGED
        SIEGED -> REPOSITIONING -> MOVING_TO_ANCHOR    the anchor moved
        SIEGED -> UNSIEGING                            the threat cleared
    """

    MOVING_TO_ANCHOR = auto()
    SIEGING = auto()
    SIEGED = auto()
    REPOSITIONING = auto()
    UNSIEGING = auto()


@dataclass(frozen=True, slots=True)
class DefenseAnchors:
    """Where each role stands this frame, facing the attack on the base.

    Two shapes, the siege anchor always closer to the base than the screen:

    - ``at_approach``: the attack still has to come through a passage into
      the base's region, so the defense holds that way in.
    - ``toward``: plain geometry on the segment from the base toward the
      threat, when there is no way in to hold (the attack is already inside,
      or no region graph exists).
    """

    base: Point2
    threat: Point2
    siege: Point2
    screen: Point2
    approach: str | None = None

    @classmethod
    def at_approach(
        cls,
        base: Point2,
        passage: PassageTerritory,
        threat: Point2,
        config: DefenseConfig,
    ) -> DefenseAnchors:
        standoff = min(
            config.approach_siege_standoff, passage.position.distance_to(base)
        )
        return cls(
            base=base,
            threat=threat,
            siege=passage.position.towards(base, standoff),
            screen=passage.position,
            approach=passage.key,
        )

    @classmethod
    def toward(
        cls, base: Point2, threat: Point2, config: DefenseConfig
    ) -> DefenseAnchors:
        # An enemy already inside the screen line squeezes both anchors back
        # toward the base proportionally: neither lands beyond the enemy, and
        # the siege anchor stays behind the screen.
        scale = min(1.0, base.distance_to(threat) / config.screen_anchor_offset)
        return cls(
            base=base,
            threat=threat,
            siege=base.towards(threat, config.siege_anchor_offset * scale),
            screen=base.towards(threat, config.screen_anchor_offset * scale),
        )

    def log_fields(self) -> dict[str, Any]:
        return {
            "base": _xy(self.base),
            "threat": _xy(self.threat),
            "siege_anchor": _xy(self.siege),
            "screen_anchor": _xy(self.screen),
            "approach": self.approach,
        }


def base_region_key(awareness: AwarenessSnapshot, base_id: str) -> str | None:
    """The region Awareness places one of our bases in, if it has a graph."""

    territory = next(
        (item for item in awareness.territory.bases if item.base_id == base_id), None
    )
    if territory is None or territory.region is None:
        return None
    return territory.region.key


def choose_approach(
    base: Point2,
    region_key: str | None,
    threat: Point2,
    passages: Iterable[PassageTerritory],
    config: DefenseConfig,
) -> PassageTerritory | None:
    """The way into the base's region the attack still has to come through.

    Tactical geometry over Awareness' topology, nothing strategic: a passage
    of the base's region, within ``approach_max_distance`` of the base,
    nearer the base than the attack and nearer the attack than the base --
    so it lies between them -- best aligned with where the attack comes
    from. ``None`` once the attack is inside, or without a region graph.
    """

    if region_key is None:
        return None
    threat_distance = base.distance_to(threat)
    if threat_distance <= 0.0:
        return None
    best: PassageTerritory | None = None
    best_alignment = 0.0
    for passage in sorted(passages, key=lambda item: item.key):
        if region_key not in passage.regions:
            continue
        reach = base.distance_to(passage.position)
        if not 0.0 < reach <= config.approach_max_distance:
            continue
        if (
            reach >= threat_distance
            or passage.position.distance_to(threat) >= threat_distance
        ):
            continue
        alignment = (
            (passage.position.x - base.x) * (threat.x - base.x)
            + (passage.position.y - base.y) * (threat.y - base.y)
        ) / (reach * threat_distance)
        if alignment > best_alignment:
            best, best_alignment = passage, alignment
    return best


def _xy(point: Point2) -> list[float]:
    return [round(float(point.x), 1), round(float(point.y), 1)]
