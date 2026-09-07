from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from sc2.ids.unit_typeid import UnitTypeId

from bot.behavior.macro.config import MacroPlannerConfig
from bot.behavior.macro.goals import ProductionGoal
from bot.behavior.posture import MacroPosture
from bot.engine.economy.models import (
    EconomicActionKind,
    EconomicProposal,
    ResourceCost,
)
from bot.world.knowledge.models import AwarenessSnapshot
from bot.world.observation.models import AttentionSnapshot, EconomyFacts, ProducerFacts


@dataclass(slots=True)
class MacroPlanner:
    """Compare current + pending macro state with a strategic goal set.

    The planner deliberately ignores the current mineral and gas bank. It
    declares useful goals and their costs; the economy controller owns
    admission, saving and reservation. Every goal has a stable identity so
    repeating the same deficit across frames cannot create duplicate work.
    """

    config: MacroPlannerConfig = field(default_factory=MacroPlannerConfig)
    planner_id: str = "macro_planner"

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[EconomicProposal, ...]:
        world = attention.world
        economy = world.economy
        if self.config.require_opening_completed and not economy.opening_completed:
            return ()

        posture = awareness.macro_posture
        proposals: list[EconomicProposal] = []

        supply = self._propose_supply(
            economy,
            world.supply_used,
            world.supply_cap,
            posture,
            world.time,
        )
        if supply is not None:
            proposals.append(supply)

        worker = self._propose_worker(economy, posture, world.time)
        if worker is not None:
            proposals.append(worker)

        expansion = self._propose_expansion(economy, posture, world.time)
        if expansion is not None:
            proposals.append(expansion)

        gas = self._propose_gas(economy, posture, world.time)
        if gas is not None:
            proposals.append(gas)

        proposals.extend(self._propose_production(economy, posture, world.time))
        proposals.extend(self._propose_addons(economy, posture, world.time))
        proposals.extend(self._propose_army(economy, posture, world.time))

        # Admission order belongs to EconomyController, but returning the same
        # priority order makes traces and unit tests much easier to read.
        proposals.sort(
            key=lambda proposal: (
                -proposal.priority,
                proposal.kind.value,
                proposal.target or "",
            )
        )
        return tuple(proposals)

    def _propose_supply(
        self,
        economy: EconomyFacts,
        supply_used: float,
        supply_cap: float,
        posture: MacroPosture,
        now: float,
    ) -> EconomicProposal | None:
        if supply_cap >= self.config.max_supply_cap:
            return None
        effective_remaining = supply_cap + economy.supply_pending - supply_used
        if effective_remaining > self.config.supply_buffer:
            return None
        return self._proposal(
            kind=EconomicActionKind.PRODUCE_SUPPLY,
            category="supply",
            target=UnitTypeId.SUPPLYDEPOT.name,
            target_count=None,
            priority=self.config.priority_for("supply", posture),
            reason="effective_supply_capacity_near_limit",
            cost=self.config.supply_cost,
            now=now,
        )

    def _propose_worker(
        self,
        economy: EconomyFacts,
        posture: MacroPosture,
        now: float,
    ) -> EconomicProposal | None:
        desired = self._desired_workers(economy)
        if economy.workers.total >= desired:
            return None
        return self._proposal(
            kind=EconomicActionKind.PRODUCE_WORKER,
            category="worker",
            target=UnitTypeId.SCV.name,
            target_count=desired,
            priority=self.config.priority_for("worker", posture),
            reason="worker_count_below_current_saturation_target",
            cost=self.config.worker_cost,
            now=now,
        )

    def _propose_expansion(
        self,
        economy: EconomyFacts,
        posture: MacroPosture,
        now: float,
    ) -> EconomicProposal | None:
        goals = self.config.goals
        if economy.townhalls.total >= goals.max_townhalls:
            return None
        # One command center already in progress represents this exact goal.
        if economy.townhalls.pending > 0:
            return None
        if posture is MacroPosture.DEFENSE:
            return None

        saturation_target = self._saturation_target(economy)
        threshold = {
            MacroPosture.BALANCED: 0.90,
            MacroPosture.GREED: 0.72,
            MacroPosture.RECOVERY: 1.00,
            MacroPosture.DEFENSE: 1.00,
        }[posture]
        if saturation_target > 0 and economy.workers.total < ceil(
            saturation_target * threshold
        ):
            return None
        return self._proposal(
            kind=EconomicActionKind.EXPAND,
            category="expansion",
            target=UnitTypeId.COMMANDCENTER.name,
            target_count=economy.townhalls.total + 1,
            priority=self.config.priority_for("expansion", posture),
            reason=f"current_bases_saturated_for_{posture.name.lower()}_posture",
            cost=self.config.expansion_cost,
            now=now,
        )

    def _propose_gas(
        self,
        economy: EconomyFacts,
        posture: MacroPosture,
        now: float,
    ) -> EconomicProposal | None:
        goals = self.config.goals
        refinery_count = economy.structure_count(UnitTypeId.REFINERY)
        desired = min(
            goals.max_refineries,
            economy.townhalls.ready * goals.refineries_per_townhall,
        )
        if desired <= 0 or refinery_count.total >= desired:
            return None
        # Do not take workers off minerals for all gases at the start of a base.
        minimum_workers = max(12, (desired - 1) * 3)
        if economy.workers.total < minimum_workers:
            return None
        return self._proposal(
            kind=EconomicActionKind.BUILD_GAS,
            category="gas",
            target=UnitTypeId.REFINERY.name,
            target_count=desired,
            priority=self.config.priority_for("gas", posture),
            reason="refinery_count_below_strategy_target",
            cost=self.config.gas_cost,
            now=now,
        )

    def _propose_production(
        self,
        economy: EconomyFacts,
        posture: MacroPosture,
        now: float,
    ) -> tuple[EconomicProposal, ...]:
        proposals: list[EconomicProposal] = []
        for goal in self.config.goals.production:
            count = economy.structure_count(goal.structure_type)
            desired = goal.target_for_income(
                minerals=economy.mineral_collection_rate,
                vespene=economy.vespene_collection_rate,
            )
            if desired > goal.minimum and not self._production_is_saturated(
                goal,
                economy.producer(goal.structure_type),
            ):
                desired = goal.minimum
            if count.total >= desired:
                continue
            proposals.append(
                self._proposal(
                    kind=EconomicActionKind.BUILD_PRODUCTION,
                    category="production",
                    target=goal.structure_type.name,
                    target_count=desired,
                    priority=self.config.priority_for("production", posture),
                    reason=(
                        "production_below_opening_floor"
                        if count.total < goal.minimum
                        else "sustained_income_exceeds_busy_production_capacity"
                    ),
                    cost=goal.cost,
                    now=now,
                )
            )
        return tuple(proposals)

    def _propose_addons(
        self,
        economy: EconomyFacts,
        posture: MacroPosture,
        now: float,
    ) -> tuple[EconomicProposal, ...]:
        proposals: list[EconomicProposal] = []
        for addon, desired, cost in self.config.goals.addons:
            if desired <= 0 or economy.structure_count(addon).total >= desired:
                continue
            proposals.append(
                self._proposal(
                    kind=EconomicActionKind.BUILD_ADDON,
                    category="addon",
                    target=addon.name,
                    target_count=desired,
                    priority=self.config.priority_for("addon", posture),
                    reason="addon_count_below_strategy_target",
                    cost=cost,
                    now=now,
                )
            )
        return tuple(proposals)

    def _propose_army(
        self,
        economy: EconomyFacts,
        posture: MacroPosture,
        now: float,
    ) -> tuple[EconomicProposal, ...]:
        goals = self.config.goals
        counts = {
            goal.unit_type: economy.unit_count(goal.unit_type).total
            for goal in goals.army
        }
        army_supply = sum(
            counts[goal.unit_type] * goal.cost.supply for goal in goals.army
        )
        if army_supply >= goals.army_supply_target:
            return ()

        total_weight = sum(goal.weight for goal in goals.army)
        # Anchor the ratio to whichever member is furthest behind its own
        # weight share, not to the grand total: an over-built member (eg.
        # spare Marines) must never inflate every other member's target
        # just because the army as a whole is already large. The lookahead
        # only widens the shared target while some member is still below
        # its configured floor; once every member has cleared its own
        # minimum, a member already sitting at its bottleneck-implied share
        # must not be re-proposed to chase the remaining army-supply gap.
        bottleneck_scale = min(
            counts[goal.unit_type] / goal.weight for goal in goals.army
        )
        below_own_minimum = any(
            counts[goal.unit_type] < goal.minimum for goal in goals.army
        )
        desired_total = bottleneck_scale * total_weight
        if below_own_minimum:
            desired_total += goals.composition_lookahead
        proposals: list[EconomicProposal] = []
        for goal in goals.army:
            ratio_target = ceil(desired_total * goal.weight / total_weight)
            desired = max(goal.minimum, ratio_target)
            if counts[goal.unit_type] >= desired:
                continue
            proposals.append(
                self._proposal(
                    kind=EconomicActionKind.PRODUCE_UNIT,
                    category="army",
                    target=goal.unit_type.name,
                    target_count=desired,
                    priority=self.config.priority_for(
                        "army", posture, offset=goal.priority_offset
                    ),
                    reason="unit_count_below_strategy_composition",
                    cost=goal.cost,
                    now=now,
                )
            )
        return tuple(proposals)

    def _desired_workers(self, economy: EconomyFacts) -> int:
        goals = self.config.goals
        saturation = self._saturation_target(economy)
        return min(goals.max_workers, saturation)

    def _saturation_target(self, economy: EconomyFacts) -> int:
        if economy.ideal_harvesters > 0:
            return economy.ideal_harvesters
        return economy.townhalls.ready * self.config.goals.workers_per_townhall

    @staticmethod
    def _production_is_saturated(
        goal: ProductionGoal,
        producer: ProducerFacts,
    ) -> bool:
        if producer.ready <= 0:
            # Missing producer telemetry must not make a valid high-income
            # signal disappear. Runtime snapshots normally have this detail.
            return True
        return producer.busy / producer.ready >= goal.minimum_utilization

    def _proposal(
        self,
        *,
        kind: EconomicActionKind,
        category: str,
        target: str,
        target_count: int | None,
        priority: int,
        reason: str,
        cost: ResourceCost,
        now: float,
    ) -> EconomicProposal:
        deduplication_key = f"{self.planner_id}:{category}:{target.lower()}"
        return EconomicProposal(
            proposal_id=deduplication_key,
            planner=self.planner_id,
            kind=kind,
            priority=priority,
            reason=reason,
            cost=cost,
            created_at=now,
            deduplication_key=deduplication_key,
            target=target,
            target_count=target_count,
        )
