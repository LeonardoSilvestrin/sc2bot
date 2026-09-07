from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class EconomicActionKind(Enum):
    """Kinds of economic intent a macro planner can argue for."""

    PRODUCE_WORKER = auto()
    PRODUCE_SUPPLY = auto()
    EXPAND = auto()


@dataclass(frozen=True, slots=True)
class ResourceCost:
    """A declared cost. Declaring one never reserves or spends resources."""

    minerals: int = 0
    vespene: int = 0
    supply: float = 0.0

    def __post_init__(self) -> None:
        if self.minerals < 0 or self.vespene < 0:
            raise ValueError("minerals and vespene must not be negative")
        if self.supply < 0.0:
            raise ValueError("supply must not be negative")

    def affordable_with(self, *, minerals: int, vespene: int) -> bool:
        return minerals >= self.minerals and vespene >= self.vespene


@dataclass(frozen=True, slots=True)
class EconomicProposal:
    """A planner's argument for one economic action; not yet a commitment.

    Distinct from ``MissionProposal``: it carries no unit requirement or map
    target because it does not move or command anything by itself.
    """

    proposal_id: str
    planner: str
    kind: EconomicActionKind
    priority: int
    reason: str
    cost: ResourceCost
    created_at: float

    def __post_init__(self) -> None:
        text_fields = (self.proposal_id, self.planner, self.reason)
        if any(not value.strip() for value in text_fields):
            raise ValueError("proposal identifiers and reason must not be empty")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
