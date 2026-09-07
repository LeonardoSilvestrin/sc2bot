from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from math import isfinite


class EconomicActionKind(Enum):
    """Kinds of economic intent a macro planner can argue for."""

    PRODUCE_WORKER = auto()
    PRODUCE_SUPPLY = auto()
    EXPAND = auto()
    BUILD_GAS = auto()
    BUILD_PRODUCTION = auto()
    PRODUCE_UNIT = auto()
    BUILD_ADDON = auto()
    RESEARCH_UPGRADE = auto()


@dataclass(frozen=True, slots=True)
class ResourceCost:
    """A declared cost. Declaring one never reserves or spends resources."""

    minerals: int = 0
    vespene: int = 0
    supply: float = 0.0

    def __post_init__(self) -> None:
        if self.minerals < 0 or self.vespene < 0:
            raise ValueError("minerals and vespene must not be negative")
        if not isfinite(self.supply) or self.supply < 0.0:
            raise ValueError("supply must not be negative")

    def affordable_with(
        self,
        *,
        minerals: int,
        vespene: int,
        supply_available: float | None = None,
    ) -> bool:
        """Return whether a bank covers this cost.

        ``supply_available`` is optional for compatibility with planners which
        check supply separately. The economy controller always supplies it.
        """

        return (
            minerals >= self.minerals
            and vespene >= self.vespene
            and (
                supply_available is None or supply_available >= self.supply
            )
        )

    def __add__(self, other: ResourceCost) -> ResourceCost:
        if not isinstance(other, ResourceCost):
            return NotImplemented
        return ResourceCost(
            minerals=self.minerals + other.minerals,
            vespene=self.vespene + other.vespene,
            supply=self.supply + other.supply,
        )


@dataclass(frozen=True, slots=True)
class ResourceBank:
    """Resources observed at the beginning of an economy-controller tick."""

    minerals: int
    vespene: int
    supply_available: float

    def __post_init__(self) -> None:
        if self.minerals < 0 or self.vespene < 0:
            raise ValueError("minerals and vespene must not be negative")
        if not isfinite(self.supply_available) or self.supply_available < 0.0:
            raise ValueError("supply_available must be finite and non-negative")

    def can_afford(self, cost: ResourceCost) -> bool:
        return cost.affordable_with(
            minerals=self.minerals,
            vespene=self.vespene,
            supply_available=self.supply_available,
        )

    def reserve(self, cost: ResourceCost) -> ResourceBank:
        """Return the virtual bank left after a fully funded reservation."""

        if not self.can_afford(cost):
            raise ValueError("resource bank cannot cover reservation")
        return ResourceBank(
            minerals=self.minerals - cost.minerals,
            vespene=self.vespene - cost.vespene,
            supply_available=self.supply_available - cost.supply,
        )

    def hold_towards(self, cost: ResourceCost) -> ResourceBank:
        """Protect currently available resources while saving for ``cost``.

        A high-priority proposal can therefore make progress toward a future
        purchase without producing a negative virtual bank.
        """

        return ResourceBank(
            minerals=self.minerals - min(self.minerals, cost.minerals),
            vespene=self.vespene - min(self.vespene, cost.vespene),
            supply_available=(
                self.supply_available
                - min(self.supply_available, cost.supply)
            ),
        )

    def consumed_from(self, original: ResourceBank) -> ResourceCost:
        """Describe how much of ``original`` is absent from this virtual bank."""

        if (
            self.minerals > original.minerals
            or self.vespene > original.vespene
            or self.supply_available > original.supply_available
        ):
            raise ValueError("bank is not derived from the supplied original")
        return ResourceCost(
            minerals=original.minerals - self.minerals,
            vespene=original.vespene - self.vespene,
            supply=original.supply_available - self.supply_available,
        )


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
    deduplication_key: str = ""
    target: str | None = None
    target_count: int | None = None
    dispatch_timeout_seconds: float = 5.0
    confirmation_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        text_fields = (self.proposal_id, self.planner, self.reason)
        if any(not value.strip() for value in text_fields):
            raise ValueError("proposal identifiers and reason must not be empty")
        if not 0 <= self.priority <= 100:
            raise ValueError("priority must be between 0 and 100")
        if not isfinite(self.created_at) or self.created_at < 0.0:
            raise ValueError("created_at must be finite and non-negative")
        if self.target is not None and not self.target.strip():
            raise ValueError("target must not be blank")
        if self.target_count is not None and self.target_count <= 0:
            raise ValueError("target_count must be positive")
        if (
            not isfinite(self.dispatch_timeout_seconds)
            or self.dispatch_timeout_seconds <= 0.0
            or not isfinite(self.confirmation_timeout_seconds)
            or self.confirmation_timeout_seconds <= 0.0
        ):
            raise ValueError("economy timeouts must be finite and positive")

        if self.deduplication_key == "":
            target_suffix = f":{self.target}" if self.target is not None else ""
            object.__setattr__(
                self,
                "deduplication_key",
                f"{self.planner}:{self.kind.name.lower()}{target_suffix}",
            )
        elif not self.deduplication_key.strip():
            raise ValueError("deduplication_key must not be blank")


class EconomicActionStatus(Enum):
    """Lifecycle of an admitted economic commitment."""

    PENDING = auto()
    IN_FLIGHT = auto()
    COMPLETED = auto()
    FAILED = auto()
    TIMED_OUT = auto()

    @property
    def terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.TIMED_OUT}


@dataclass(frozen=True, slots=True)
class EconomicAction:
    """A funded proposal ready for an infrastructure adapter to execute."""

    action_id: str
    proposal: EconomicProposal
    admitted_at: float


class EconomicFeedbackKind(Enum):
    """Facts reported by the execution adapter or pending-state observer."""

    DISPATCHED = auto()
    CONFIRMED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class EconomicFeedback:
    action_id: str
    kind: EconomicFeedbackKind
    reason: str

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.reason.strip():
            raise ValueError("feedback action_id and reason must not be empty")


@dataclass(frozen=True, slots=True)
class EconomicActionSnapshot:
    action: EconomicAction
    status: EconomicActionStatus
    reason: str
    dispatched_at: float | None
    finished_at: float | None

    @property
    def action_id(self) -> str:
        return self.action.action_id

    @property
    def proposal(self) -> EconomicProposal:
        return self.action.proposal


@dataclass(frozen=True, slots=True)
class EconomyTickResult:
    """New work and the virtual bank remaining after one arbitration pass."""

    admitted_actions: tuple[EconomicAction, ...]
    available_bank: ResourceBank
    reserved_cost: ResourceCost
