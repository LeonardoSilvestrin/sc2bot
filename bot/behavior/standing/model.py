"""Types local to the standing army behavior."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions.models import MissionKind
from bot.world.awareness.bases import BaseAssessment


class CombatPosture(Enum):
    """Whether anything observed is pressing on the standing army.

    Descriptive only: it is logged and moves nothing. It is deliberately not
    a strategic reading -- what the bot wants is Strategy's intent, and how
    risky spending is stays macro's concern -- only what Awareness observes
    about threatened bases and the army belief.
    """

    TURTLE = auto()
    BALANCED = auto()
    PRESSURE = auto()


@dataclass(frozen=True, slots=True)
class StandingConfig:
    """Thresholds for the standing army behavior.

    The core army is the fallback owner: the Mission Policy ranks it at its
    fixed fallback floor, below every viable opportunity by at least the
    allocator's preemption margin, so a standing slot is always freely
    preemptible. Where the army waits follows Strategy's home control
    objectives; the anchor fraction is only the last resort without them.

    Which units belong to the core army is ``STANDING_ROSTER``, not a
    setting: every unit of those types no more specific mission is using.
    Specialized behaviors (the Banshee raid) take theirs back through
    ordinary preemption.
    """

    proposal_cadence: float = 5.0
    minimum_unit_health: float = 0.0
    mission_timeout: float = 3600.0
    cooldown_seconds: float = 5.0
    commitment_seconds: float = 2.0
    arrival_radius: float = 4.0
    # Where the core army waits on a home passage Strategy wants held: this
    # far inside it, toward the base it protects.
    home_anchor_standoff: float = 4.0
    # A base or passage must matter this much more than the one the army
    # already supports before the army moves to it.
    anchor_retarget_margin: float = 0.1
    # Last resort only, with no spatial objective to support: most of the way
    # from the previous base toward the newest one.
    anchor_fraction_to_newest_base: float = 0.72

    def __post_init__(self) -> None:
        if self.proposal_cadence <= 0.0:
            raise ValueError("proposal_cadence must be positive")
        if not 0.0 <= self.minimum_unit_health <= 1.0:
            raise ValueError("minimum_unit_health must be between 0 and 1")
        if self.mission_timeout <= 0.0:
            raise ValueError("mission_timeout must be positive")
        if self.cooldown_seconds < 0.0:
            raise ValueError("cooldown_seconds must not be negative")
        if self.commitment_seconds < 0.0:
            raise ValueError("commitment_seconds must not be negative")
        if self.arrival_radius <= 0.0:
            raise ValueError("arrival_radius must be positive")
        if not 0.0 <= self.anchor_fraction_to_newest_base <= 1.0:
            raise ValueError("anchor_fraction_to_newest_base must be between 0 and 1")
        if self.home_anchor_standoff < 0.0:
            raise ValueError("home_anchor_standoff must not be negative")
        if not 0.0 <= self.anchor_retarget_margin <= 1.0:
            raise ValueError("anchor_retarget_margin must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class StandingAssessment:
    """Where our army is, what it is protecting, and what is pressing it."""

    now: float
    posture: CombatPosture
    # Held bases ordered by distance from the main -- our stand-in for
    # expansion order until construction timestamps exist.
    bases: tuple[BaseAssessment, ...]
    threatened_base_ids: tuple[str, ...]
    pressure: int
    # Ready units of the standing roster, at or above the health floor.
    combat_units: int
    own_start: Point2

    @property
    def newest_base(self) -> Point2 | None:
        return self.bases[-1].position if self.bases else None

    @property
    def previous_base(self) -> Point2 | None:
        return self.bases[-2].position if len(self.bases) >= 2 else None

    def log_fields(self) -> dict[str, Any]:
        return {
            "posture": self.posture.name,
            "bases": len(self.bases),
            "threatened_bases": list(self.threatened_base_ids),
            "pressure": self.pressure,
            "combat_units": self.combat_units,
        }


@dataclass(frozen=True, slots=True)
class StandingPlan:
    """Where the heart of the army should sit, and how much of it."""

    anchor: Point2
    anchor_reason: str
    # Every roster unit, not a share: this is the fallback owner, so whatever
    # no higher-priority mission holds belongs here. A cardinality, not a
    # force size -- "all of them" is exact whatever each unit weighs.
    core_count: int
    # The Strategy objective the anchor holds (a home passage), and the base
    # objective it protects; both ``None`` on the fallback anchor.
    objective_id: str | None = None
    supports: str | None = None

    def log_fields(self) -> dict[str, Any]:
        return {
            "anchor": [round(float(self.anchor.x), 1), round(float(self.anchor.y), 1)],
            "anchor_reason": self.anchor_reason,
            "core_count": self.core_count,
            "objective": self.objective_id,
            "supports": self.supports,
        }


MISSION_KIND = MissionKind.HOLD_RALLY
SQUAD_ID = "main_army"
DEDUPLICATION_KEY = "hold_rally:main_army"

# The fallback owner's roster: every military unit type this bot fields that
# the standing executor can park on an anchor. Every build's army belongs
# here, and so do the types a unit can turn into (a sieged Tank, a landed
# Viking) so a mode change never orphans it. Unarmed support (Medivacs) and
# workers never do. A newly produced unit type joins only by an explicit
# decision here -- until then Standing does not claim it.
STANDING_ROSTER: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.MARINE,
        UnitTypeId.MARAUDER,
        UnitTypeId.REAPER,
        UnitTypeId.HELLION,
        UnitTypeId.HELLIONTANK,
        UnitTypeId.CYCLONE,
        UnitTypeId.SIEGETANK,
        UnitTypeId.SIEGETANKSIEGED,
        UnitTypeId.THOR,
        UnitTypeId.THORAP,
        UnitTypeId.VIKINGFIGHTER,
        UnitTypeId.VIKINGASSAULT,
        UnitTypeId.BANSHEE,
    }
)
