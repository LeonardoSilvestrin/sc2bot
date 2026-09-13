"""Types local to the roaming map-control patrol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from sc2.position import Point2

from bot.engine.missions.models import MissionKind
from bot.engine.missions.roles import CombatRole
from bot.world.awareness.spatial import SpatialFieldSample


@dataclass(frozen=True, slots=True)
class MapControlConfig:
    """Conservative thresholds for a persistent map-presence squad."""

    start_after: float = 0.0
    proposal_cadence: float = 15.0
    priority: int = 40
    mission_timeout: float = 3600.0
    failure_cooldown: float = 15.0
    # What the patrol is for, not what it is made of: every combat unit is
    # scored against the role, and the best-suited ones patrol.
    role: CombatRole = CombatRole.MOBILE_CONTROL
    # The patrol's share of the army, measured in combat supply.
    force_ratio: float = 0.2
    # Below this much combat supply a share would leave no real army at home.
    minimum_force_supply: float = 6.0
    # Optional fixed unit count retained for experiments/config compatibility;
    # it replaces the supply share.
    desired_units: int | None = None
    minimum_unit_health: float = 0.7
    commitment_seconds: float = 1.0

    # --- spatial utility --------------------------------------------------
    friendly_weight: float = 0.45
    frontier_weight: float = 0.65
    advancement_weight: float = 0.25
    choke_weight: float = 0.35
    route_weight: float = 0.55
    threat_weight: float = 0.80
    enemy_control_weight: float = 1.0
    unknown_weight: float = 0.25
    travel_weight: float = 0.15
    # Friendly influence is useful as a support band, not as a monotonic
    # reward. The frontier pool excludes both unsupported space and the deep
    # friendly interior whenever a viable frontier exists.
    frontier_support: float = 0.45
    frontier_support_width: float = 0.35
    frontier_min_support: float = 0.10
    frontier_max_support: float = 0.80
    max_enemy_control: float = 0.55
    max_enemy_threat: float = 0.75
    base_exclusion_radius: float = 6.0
    retarget_score_improvement: float = 0.12
    # Measured in grid steps (multiples of the field's sample spacing), so it
    # keeps its meaning when the spacing changes. 1.5 steps spans a sample's
    # eight neighbours, which the patrol region already covers.
    retarget_min_sample_steps: float = 1.5
    logged_candidate_count: int = 5

    # --- tactics ----------------------------------------------------------
    # The patrol walks every sampled pathable point within this many grid
    # steps of the anchor; 0 holds the anchor itself.
    patrol_radius_sample_steps: float = 1.5
    danger_radius: float = 20.0
    arrival_radius: float = 5.0
    retreat_arrival_radius: float = 7.0
    retreat_health: float = 0.6

    mission_kind: MissionKind = MissionKind.MAP_CONTROL
    squad_id: str = "map_control"

    def __post_init__(self) -> None:
        if self.start_after < 0.0:
            raise ValueError("start_after must not be negative")
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.failure_cooldown < 0.0:
            raise ValueError("failure_cooldown must not be negative")
        if not 0.0 < self.force_ratio < 1.0:
            raise ValueError("force_ratio must be between 0 and 1")
        if self.minimum_force_supply <= 0.0:
            raise ValueError("minimum_force_supply must be positive")
        if self.desired_units is not None and self.desired_units < 1:
            raise ValueError("desired_units must be positive when provided")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
        for name in (
            "friendly_weight",
            "frontier_weight",
            "advancement_weight",
            "choke_weight",
            "route_weight",
            "threat_weight",
            "enemy_control_weight",
            "unknown_weight",
            "travel_weight",
            "frontier_support_width",
            "base_exclusion_radius",
            "retarget_score_improvement",
            "retarget_min_sample_steps",
            "patrol_radius_sample_steps",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")
        for name in (
            "frontier_support",
            "frontier_min_support",
            "frontier_max_support",
            "max_enemy_control",
            "max_enemy_threat",
        ):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")
        if self.frontier_min_support >= self.frontier_max_support:
            raise ValueError("frontier_min_support must be below frontier_max_support")
        if self.frontier_support_width <= 0.0:
            raise ValueError("frontier_support_width must be positive")
        if self.logged_candidate_count < 1:
            raise ValueError("logged_candidate_count must be positive")
        for name in ("danger_radius", "arrival_radius", "retreat_arrival_radius"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if not 0.0 <= self.retreat_health <= 1.0:
            raise ValueError("retreat_health must be between 0 and 1")
        if not self.squad_id.strip():
            raise ValueError("squad_id must not be blank")


@dataclass(frozen=True, slots=True)
class MapControlAssessment:
    """Whether we can currently spare a squad to hold the map."""

    now: float
    # Ready combat units healthy enough to roam, of any type, and the supply
    # they add up to: the army the patrol takes a share of.
    combat_units: int
    combat_supply: float
    started: bool
    strategically_safe: bool

    @property
    def force_available(self) -> bool:
        return self.started and self.combat_units > 0

    def log_fields(self) -> dict[str, Any]:
        return {
            "combat_units": self.combat_units,
            "combat_supply": round(self.combat_supply, 1),
            "started": self.started,
            "strategically_safe": self.strategically_safe,
        }


@dataclass(frozen=True, slots=True)
class MapControlPlan:
    """How much of the army roams, and where it centres its patrol."""

    anchor: Point2
    # A count cap. With a supply budget it is every combat unit, so the
    # budget is what binds.
    desired_units: int
    supply_budget: float | None
    priority: int

    def log_fields(self) -> dict[str, Any]:
        return {
            "anchor": [round(float(self.anchor.x), 1), round(float(self.anchor.y), 1)],
            "desired_units": self.desired_units,
            "supply_budget": self.supply_budget,
            "priority": self.priority,
        }


@dataclass(frozen=True, slots=True)
class MapControlCandidate:
    """One sampled point scored with map-control-specific preferences."""

    sample: SpatialFieldSample
    score: float
    frontier_score: float = 0.0
    advancement_score: float = 0.0
    support_score: float = 0.0
    unknown_risk: float = 0.0
    travel_cost: float = 0.0
    selected: bool = False
    reason: str = "lower_score"

    def log_fields(self) -> dict[str, Any]:
        sample = self.sample
        return {
            "position": [
                round(float(sample.position.x), 1),
                round(float(sample.position.y), 1),
            ],
            "score": round(self.score, 3),
            "frontier": round(self.frontier_score, 3),
            "advancement": round(self.advancement_score, 3),
            "friendly_support": round(
                sample.friendly_value
                if sample.friendly_control is None
                else sample.friendly_control,
                3,
            ),
            "friendly_proximity": round(sample.friendly_value, 3),
            "support_band": round(self.support_score, 3),
            "enemy_control": round(sample.enemy_control, 3),
            "enemy_threat": round(sample.enemy_threat, 3),
            "knowledge": round(sample.knowledge_confidence, 3),
            "unknown_risk": round(self.unknown_risk, 3),
            "choke": round(sample.choke_value, 3),
            "route": round(sample.route_value, 3),
            "travel_cost": round(self.travel_cost, 3),
            "selected": self.selected,
            "reason": self.reason,
        }


class PatrolPhase(Enum):
    """What the patrol squad is doing right now.

    The patrol is deliberately timid: anything strategically wrong, any hurt
    member, or any nearby enemy that can shoot it sends the squad home rather
    than into a fight it was never sized to win.
    """

    WAITING = auto()
    PATROL = auto()
    RETREAT = auto()
    HOLDING_HOME = auto()
