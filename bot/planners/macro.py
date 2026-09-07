from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention.models import AttentionSnapshot, WorldFacts
from bot.awareness.models import AwarenessSnapshot
from bot.contracts.economy import EconomicActionKind, EconomicProposal, ResourceCost

_TOWNHALL_TYPES: frozenset[UnitTypeId] = frozenset(
    {
        UnitTypeId.COMMANDCENTER,
        UnitTypeId.ORBITALCOMMAND,
        UnitTypeId.PLANETARYFORTRESS,
    }
)


@dataclass(frozen=True, slots=True)
class MacroPlannerConfig:
    """Thresholds for the first macroeconomic planning slice."""

    worker_cost: ResourceCost = field(
        default_factory=lambda: ResourceCost(minerals=50, supply=1.0)
    )
    supply_cost: ResourceCost = field(
        default_factory=lambda: ResourceCost(minerals=100)
    )
    expansion_cost: ResourceCost = field(
        default_factory=lambda: ResourceCost(minerals=400)
    )
    workers_per_townhall: int = 16
    max_workers: int = 80
    supply_buffer: float = 4.0
    max_supply_cap: float = 200.0
    worker_priority: int = 50
    supply_priority: int = 90
    expansion_priority: int = 60

    def __post_init__(self) -> None:
        if self.workers_per_townhall <= 0 or self.max_workers <= 0:
            raise ValueError("worker capacity settings must be positive")
        if self.max_workers < self.workers_per_townhall:
            raise ValueError("max_workers must be at least workers_per_townhall")
        if self.supply_buffer < 0.0 or self.max_supply_cap <= 0.0:
            raise ValueError("invalid supply block settings")
        for priority in (
            self.worker_priority,
            self.supply_priority,
            self.expansion_priority,
        ):
            if not 0 <= priority <= 100:
                raise ValueError("priorities must be between 0 and 100")


@dataclass(slots=True)
class MacroPlanner:
    """Proposes worker production, supply, and expansion after the opening.

    Every proposal declares its own ``ResourceCost``; this planner never
    deducts, reserves, or spends resources itself.
    """

    config: MacroPlannerConfig = field(default_factory=MacroPlannerConfig)
    planner_id: str = "macro_planner"

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[EconomicProposal, ...]:
        world = attention.world
        townhalls = self._ready_townhall_count(world)
        ideal_workers = min(
            townhalls * self.config.workers_per_townhall,
            self.config.max_workers,
        )
        workers = sum(unit.is_worker for unit in world.own_units)

        proposals: list[EconomicProposal] = []

        supply_proposal = self._propose_supply(world)
        if supply_proposal is not None:
            proposals.append(supply_proposal)

        worker_proposal = self._propose_worker(world, workers, ideal_workers)
        if worker_proposal is not None:
            proposals.append(worker_proposal)

        expansion_proposal = self._propose_expansion(
            world, awareness, workers, ideal_workers
        )
        if expansion_proposal is not None:
            proposals.append(expansion_proposal)

        return tuple(proposals)

    def _propose_supply(self, world: WorldFacts) -> EconomicProposal | None:
        if world.supply_cap >= self.config.max_supply_cap:
            return None
        remaining_supply = world.supply_cap - world.supply_used
        if remaining_supply > self.config.supply_buffer:
            return None
        if not self.config.supply_cost.affordable_with(
            minerals=world.minerals, vespene=world.vespene
        ):
            return None
        return EconomicProposal(
            proposal_id=f"{self.planner_id}:supply:{world.time}",
            planner=self.planner_id,
            kind=EconomicActionKind.PRODUCE_SUPPLY,
            priority=self.config.supply_priority,
            reason="supply_capacity_near_limit",
            cost=self.config.supply_cost,
            created_at=world.time,
        )

    def _propose_worker(
        self, world: WorldFacts, workers: int, ideal_workers: int
    ) -> EconomicProposal | None:
        if workers >= ideal_workers:
            return None
        remaining_supply = world.supply_cap - world.supply_used
        if remaining_supply < self.config.worker_cost.supply:
            return None
        if not self.config.worker_cost.affordable_with(
            minerals=world.minerals, vespene=world.vespene
        ):
            return None
        return EconomicProposal(
            proposal_id=f"{self.planner_id}:worker:{world.time}",
            planner=self.planner_id,
            kind=EconomicActionKind.PRODUCE_WORKER,
            priority=self.config.worker_priority,
            reason="worker_count_below_ideal_for_current_bases",
            cost=self.config.worker_cost,
            created_at=world.time,
        )

    def _propose_expansion(
        self,
        world: WorldFacts,
        awareness: AwarenessSnapshot,
        workers: int,
        ideal_workers: int,
    ) -> EconomicProposal | None:
        if workers < ideal_workers:
            return None
        if awareness.threat.visible_enemy_units > 0:
            return None
        if not self.config.expansion_cost.affordable_with(
            minerals=world.minerals, vespene=world.vespene
        ):
            return None
        return EconomicProposal(
            proposal_id=f"{self.planner_id}:expand:{world.time}",
            planner=self.planner_id,
            kind=EconomicActionKind.EXPAND,
            priority=self.config.expansion_priority,
            reason="worker_count_saturated_for_current_bases",
            cost=self.config.expansion_cost,
            created_at=world.time,
        )

    @staticmethod
    def _ready_townhall_count(world: WorldFacts) -> int:
        return max(
            1,
            sum(
                1
                for structure in world.own_structures
                if structure.unit_type in _TOWNHALL_TYPES and structure.is_ready
            ),
        )
