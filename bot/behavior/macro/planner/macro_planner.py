from __future__ import annotations

from dataclasses import dataclass, field

from bot.engine.economy.models import EconomicProposal
from bot.world.knowledge import AwarenessSnapshot
from bot.world.observation import AttentionSnapshot

from ..macro_config import MacroPlannerConfig
from . import (
    addon_proposals,
    army_proposals,
    expansion_proposals,
    gas_proposals,
    production_proposals,
    supply_proposals,
    worker_proposals,
)


@dataclass(slots=True)
class MacroPlanner:
    """Compare current + pending macro state with a strategic goal set.

    The planner never uses the bank to decide whether a goal is
    *affordable* -- it declares useful goals and their costs; the economy
    controller owns admission, saving and reservation. It does read the bank
    for one narrow purpose: as a pressure signal in ``production.py`` and
    ``army.py``, a pile sitting above ``MacroPlannerConfig.overflow``'s
    thresholds is itself evidence that current production/composition
    targets are too low, and raises them regardless of producer
    utilization. Every goal has a stable identity so repeating the same
    deficit across frames cannot create duplicate work.

    Each proposal category lives in its own sibling module (``supply``,
    ``worker``, ``expansion``, ``gas``, ``production``, ``addons``,
    ``army``) since they are independent of each other; this class only
    orders the calls and merges the results.
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

        supply_proposal = supply_proposals.propose_supply(
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

        worker_proposal = worker_proposals.propose_worker(
            self.config, self.planner_id, economy, posture, world.time
        )
        if worker_proposal is not None:
            proposals.append(worker_proposal)

        expansion_proposal = expansion_proposals.propose_expansion(
            self.config, self.planner_id, economy, posture, world.time
        )
        if expansion_proposal is not None:
            proposals.append(expansion_proposal)

        gas_proposal = gas_proposals.propose_gas(
            self.config, self.planner_id, economy, posture, world.time
        )
        if gas_proposal is not None:
            proposals.append(gas_proposal)

        proposals.extend(
            production_proposals.propose_production(
                self.config,
                self.planner_id,
                economy,
                posture,
                world.time,
                minerals=world.minerals,
                vespene=world.vespene,
            )
        )
        proposals.extend(
            addon_proposals.propose_addons(
                self.config, self.planner_id, economy, posture, world.time
            )
        )
        proposals.extend(
            army_proposals.propose_army(
                self.config,
                self.planner_id,
                economy,
                posture,
                world.time,
                minerals=world.minerals,
                vespene=world.vespene,
            )
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
        return tuple(proposals)
