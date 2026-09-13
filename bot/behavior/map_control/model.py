"""Types local to the roaming map-control patrol."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind
from bot.strategy import ControlMatch, MissionSignals
from bot.world.awareness.spatial import SpatialFieldSample

# The units the patrol was written for: ground units that fight on the move,
# with no siege or transform to manage -- its loop walks pathable samples, its
# pathing is the ground grid and its retreat reads ground threats. Tanks hold
# lines, Reapers and Banshees belong to their raids, and air or support units
# are never asked for. A new unit type patrols only once it is added here.
PATROL_UNIT_TYPES: frozenset[UnitTypeId] = frozenset(
    {UnitTypeId.CYCLONE, UnitTypeId.HELLION, UnitTypeId.MARINE, UnitTypeId.MARAUDER}
)
# The patrol's own preference among them: the mobile units that also answer
# air first, then Hellions, then infantry.
PATROL_TYPE_DESIRABILITY: tuple[tuple[UnitTypeId, float], ...] = (
    (UnitTypeId.CYCLONE, 1.0),
    (UnitTypeId.HELLION, 0.9),
    (UnitTypeId.MARINE, 0.6),
    (UnitTypeId.MARAUDER, 0.6),
)


@dataclass(frozen=True, slots=True)
class MapControlConfig:
    """Conservative thresholds for a persistent map-presence squad."""

    start_after: float = 0.0
    proposal_cadence: float = 15.0
    mission_timeout: float = 3600.0
    failure_cooldown: float = 15.0
    # Which units patrol, and which the patrol would rather have.
    unit_types: frozenset[UnitTypeId] = PATROL_UNIT_TYPES
    type_desirability: tuple[tuple[UnitTypeId, float], ...] = PATROL_TYPE_DESIRABILITY
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

    # --- what Strategy wants (anchor selection only) -----------------------
    # Unknown space is worth `information_weight * intent.information` against
    # `unknown_weight`'s caution. A sample that meaningfully serves an
    # approach Strategy wants controlled or watched (a `ControlMatch`) is
    # worth `objective_weight * importance * alignment`; alignment fades over
    # `objective_sigma_steps` grid steps and stops being a match below
    # `MINIMUM_CONTROL_ALIGNMENT` (about 1.2 sigma, near the patrol loop's
    # edge). Strategy says whether space and information matter; this still
    # decides which point obtains them. None of it enters the opportunity the
    # Mission Policy is told.
    information_weight: float = 0.3
    objective_weight: float = 0.6
    objective_sigma_steps: float = 1.5

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
            "information_weight",
            "objective_weight",
            "objective_sigma_steps",
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

    @property
    def force_available(self) -> bool:
        return self.started and self.combat_units > 0

    def log_fields(self) -> dict[str, Any]:
        return {
            "combat_units": self.combat_units,
            "combat_supply": round(self.combat_supply, 1),
            "started": self.started,
        }


@dataclass(frozen=True, slots=True)
class MapControlPlan:
    """How much of the army roams, and where it centres its patrol."""

    anchor: Point2
    # A count cap. With a supply budget it is every combat unit, so the
    # budget is what binds.
    desired_units: int
    supply_budget: float | None
    # The local reading the Mission Policy ranks this patrol from.
    signals: MissionSignals

    def log_fields(self) -> dict[str, Any]:
        return {
            "anchor": [round(float(self.anchor.x), 1), round(float(self.anchor.y), 1)],
            "desired_units": self.desired_units,
            "supply_budget": self.supply_budget,
            **self.signals.log_fields(),
        }


@dataclass(frozen=True, slots=True)
class MapControlCandidate:
    """One sampled point, evaluated as the patrol's anchor.

    Three groups of terms, each with one owner, and nothing counted twice:

    - **local evidence** -- ``support_score``, ``frontier_score``,
      ``advancement_score``, the sample's choke and route values, and
      ``travel_cost`` -- weighted into ``local_value``. What the field and the
      patrol's own position say about holding this point. ``opportunity`` is
      ``local_value`` over the best a sample could reach: the only thing the
      Mission Policy is told as opportunity.
    - **caution** -- enemy threat, enemy control and unknown space, weighted.
      It steers selection away from danger; the Mission Policy prices the
      same danger again only through ``MissionSignals.risk``, for the
      separate cross-mission decision.
    - **strategy** -- ``strategic_value``: unknown space priced by
      ``information_desire`` (``intent.information``), plus the importance of
      the control objective the point meaningfully serves (``control``). The
      one path by which Strategy moves the anchor.

    ``score`` is exactly ``local_value - caution + strategic_value``.
    """

    sample: SpatialFieldSample
    support_score: float
    frontier_score: float
    advancement_score: float
    travel_cost: float
    unknown_risk: float
    local_value: float
    caution: float
    opportunity: float
    information_desire: float = 0.0
    control: ControlMatch | None = None
    control_importance: float = 0.0
    strategic_value: float = 0.0
    selected: bool = False
    reason: str = "lower_score"

    def __post_init__(self) -> None:
        if self.control is None and self.control_importance != 0.0:
            raise ValueError("control_importance needs a control match")

    @property
    def score(self) -> float:
        return self.local_value - self.caution + self.strategic_value

    def log_fields(self) -> dict[str, Any]:
        """Every term exactly as evaluated: machine precision, no rounding."""

        sample = self.sample
        return {
            "position": [float(sample.position.x), float(sample.position.y)],
            "score": self.score,
            "local_value": self.local_value,
            "caution": self.caution,
            "strategic_value": self.strategic_value,
            "opportunity": self.opportunity,
            "frontier": self.frontier_score,
            "advancement": self.advancement_score,
            "friendly_support": (
                sample.friendly_value
                if sample.friendly_control is None
                else sample.friendly_control
            ),
            "friendly_proximity": sample.friendly_value,
            "support_band": self.support_score,
            "enemy_control": sample.enemy_control,
            "enemy_threat": sample.enemy_threat,
            "knowledge": sample.knowledge_confidence,
            "unknown_risk": self.unknown_risk,
            "choke": sample.choke_value,
            "route": sample.route_value,
            "travel_cost": self.travel_cost,
            "information_desire": self.information_desire,
            "control_objective": (
                None if self.control is None else self.control.objective_id
            ),
            "control_alignment": (
                None if self.control is None else self.control.alignment
            ),
            "control_importance": self.control_importance,
            "selected": self.selected,
            "reason": self.reason,
        }


class PatrolPhase(Enum):
    """What the patrol squad is doing right now.

    The patrol is deliberately timid: a base under attack, any hurt member,
    or any nearby enemy that can shoot it sends the squad home rather than
    into a fight it was never sized to win.
    """

    WAITING = auto()
    PATROL = auto()
    RETREAT = auto()
    HOLDING_HOME = auto()
