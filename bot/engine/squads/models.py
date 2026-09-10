from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class SquadRole(Enum):
    """Persistent force archetypes introduced by the squad pilot."""

    MAIN_ARMY = auto()
    MAP_CONTROL = auto()
    BANSHEE_HARASS = auto()


@dataclass(slots=True)
class Squad:
    """Identity and membership that survive individual mission lifecycles."""

    squad_id: str
    role: SquadRole
    home_mission_key: str
    member_tags: set[int] = field(default_factory=set)
    home_mission_id: str | None = None
    current_mission_id: str | None = None
    current_mission_key: str | None = None
    preempted_from_mission_id: str | None = None


@dataclass(frozen=True, slots=True)
class SquadSnapshot:
    squad_id: str
    role: SquadRole
    home_mission_key: str
    member_tags: tuple[int, ...]
    home_mission_id: str | None
    current_mission_id: str | None
    current_mission_key: str | None
    preempted_from_mission_id: str | None

    @classmethod
    def from_squad(cls, squad: Squad) -> SquadSnapshot:
        return cls(
            squad_id=squad.squad_id,
            role=squad.role,
            home_mission_key=squad.home_mission_key,
            member_tags=tuple(sorted(squad.member_tags)),
            home_mission_id=squad.home_mission_id,
            current_mission_id=squad.current_mission_id,
            current_mission_key=squad.current_mission_key,
            preempted_from_mission_id=squad.preempted_from_mission_id,
        )
