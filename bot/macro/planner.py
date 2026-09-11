from __future__ import annotations

from dataclasses import dataclass, field

from bot.engine.economy.models import EconomicProposal
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .construction.addons import propose_addons
from .construction.capacity import (
    CapacityAssessment,
    assess_capacity,
    propose_production,
)
from .construction.gas import propose_gas
from .construction.supply import propose_supply
from .expansion.bases import propose_expansion
from .production.army import propose_army
from .production.army_demand import ArmyDemand, army_demand
from .production.workers import propose_worker
from .strategy.config import MacroPlannerConfig
from .strategy.openings import macro_config_for_opening


@dataclass(frozen=True, slots=True)
class MacroStatus:
    """What the macro layer wanted this tick, kept for diagnostics.

    Holding on to the demand and the capacity verdicts is what makes "why is
    that Factory idle?" answerable from the logs without recomputing any of
    it in the logging path.
    """

    updated_at: float
    demand: ArmyDemand
    capacity: tuple[CapacityAssessment, ...]
    proposals: tuple[EconomicProposal, ...]


@dataclass(slots=True)
class MacroPlanner:
    """Turn a strategy's goals into one tick's worth of spend proposals.

    The layering, top to bottom: the goal set says what we should have,
    ``army_demand`` measures the gap, ``propose_army`` picks the next unit
    to train, ``assess_capacity`` decides separately whether infrastructure
    is the bottleneck, and the economy controller pays for at most one item
    per proposal. The planner never checks whether anything is affordable --
    it reads the bank only as pressure evidence, since a pile above
    ``MacroPlannerConfig.overflow``'s thresholds means the army we want is
    too small for the income we have.

    It runs during an opening as well as after it. An unfinished opening is a
    set of commitments, not a freeze: what keeps its timings intact is that
    ``EconomyController.tick(protected=...)`` withholds the cost of its next
    steps, so macro only ever spends a genuine surplus. Early on there is no
    surplus and macro does almost nothing; by the time the bank runs ahead of
    a long opening, spending it on workers, supply, units and even another
    Barracks is the right move rather than something to wait out. The single
    exception is add-ons, which contend for a slot rather than for money.

    This is the one module that knows how the spend domains depend on each
    other -- capacity reads army demand -- and in which order they are asked.
    """

    config: MacroPlannerConfig = field(default_factory=MacroPlannerConfig)
    planner_id: str = "macro_planner"
    # Ares' build runner resolves `chosen_opening` only after the bot is
    # composed, so a following planner treats `config` as a default until
    # Attention reports the opening, then adopts that opening's profile for
    # the rest of the game. A pinned config (tests, tuning) never follows.
    follow_opening: bool = False
    last_status: MacroStatus | None = None

    def propose(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
    ) -> tuple[EconomicProposal, ...]:
        world = attention.world
        economy = world.economy
        self._follow_opening(economy.opening_name)
        posture = awareness.macro_posture
        proposals: list[EconomicProposal] = []

        demand = army_demand(
            self.config.goals,
            economy,
            supply_bonus=self.config.overflow.army_supply_bonus(
                minerals=world.minerals, vespene=world.vespene
            ),
        )
        capacity = assess_capacity(
            self.config,
            economy,
            demand,
            world.time,
            minerals=world.minerals,
            vespene=world.vespene,
        )

        supply_proposal = propose_supply(
            self.config,
            self.planner_id,
            economy,
            world.supply_used,
            world.supply_cap,
            posture,
            world.time,
        )
        if supply_proposal is not None:
            proposals.append(supply_proposal)

        worker_proposal = propose_worker(
            self.config, self.planner_id, economy, posture, world.time
        )
        if worker_proposal is not None:
            proposals.append(worker_proposal)

        gas_proposal = propose_gas(
            self.config, self.planner_id, economy, posture, world.time
        )
        if gas_proposal is not None:
            proposals.append(gas_proposal)

        expansion_proposal = propose_expansion(
            self.config, self.planner_id, economy, posture, world.time
        )
        if expansion_proposal is not None:
            proposals.append(expansion_proposal)

        proposals.extend(
            propose_production(
                self.config, self.planner_id, capacity, posture, world.time
            )
        )

        # Add-ons are the one thing that cannot simply be paid for out of the
        # surplus: a Starport holds one, so building a Reactor on the only
        # Starport would leave the opening's own Tech Lab step with nowhere to
        # go, and the build order would never finish. Money can be shared;
        # that slot cannot.
        if economy.opening_completed:
            proposals.extend(
                propose_addons(
                    self.config, self.planner_id, economy, posture, world.time
                )
            )
        proposals.extend(
            propose_army(self.config, self.planner_id, demand, posture, world.time)
        )

        # Admission order belongs to EconomyController, but returning the same
        # priority order makes traces and unit tests much easier to read.
        proposals.sort(
            key=lambda proposal: (
                -proposal.priority,
                proposal.kind.value,
                proposal.target or "",
            )
        )
        self.last_status = MacroStatus(
            updated_at=world.time,
            demand=demand,
            capacity=capacity,
            proposals=tuple(proposals),
        )
        return tuple(proposals)

    def _follow_opening(self, opening_name: str) -> None:
        if not self.follow_opening or not opening_name:
            return
        self.config = macro_config_for_opening(opening_name)
        self.follow_opening = False
