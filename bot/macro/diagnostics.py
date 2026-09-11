"""Why macro is, or is not, spending -- answered from the log.

Runs after `EconomyController.step`, because the question needs both halves:
what `MacroPlanner` wanted this tick (`MacroStatus`) and what the controller
did with the bank (`EconomyTickResult`). It decides nothing.
"""

from __future__ import annotations

from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId

from bot.engine.economy import (
    EconomyTickResult,
    ResourceBank,
    ResourceCost,
    observe_bank,
    observe_protected_cost,
)
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot

from .planner import MacroStatus

COMPONENT = "macro.planner"


class MacroDiagnostics:
    """Emits ``macro.status`` and ``macro.idle_producer_unexplained``."""

    # Macro state is logged on change, plus this heartbeat so a stable but
    # wrong state (banking with nothing in demand) still shows up.
    _STATUS_LOG_INTERVAL = 10.0
    # A producer can legitimately be idle for a moment; this long with a unit
    # owed and the money free is a bug in some layer above.
    _IDLE_PRODUCER_WARNING_AFTER = 15.0

    def __init__(self, *, logger: BotLogger) -> None:
        self.logger = logger
        self._last_status_signature: tuple | None = None
        self._last_status_log_at: float = -999.0
        self._idle_producer_since: dict[UnitTypeId, float] = {}

    def report(
        self,
        attention: AttentionSnapshot,
        status: MacroStatus | None,
        result: EconomyTickResult,
    ) -> None:
        if status is None:
            return
        world = attention.world
        bank = observe_bank(world)
        self._log_status(attention, status, bank, result)
        self._log_idle_producers(
            attention, status, bank, observe_protected_cost(world.economy)
        )

    def _log_status(
        self,
        attention: AttentionSnapshot,
        status: MacroStatus,
        bank: ResourceBank,
        result: EconomyTickResult,
    ) -> None:
        """Make "why is it not spending?" answerable from the log.

        One line carrying the four resource quantities, the army debt, the
        per-producer utilization and each capacity verdict -- the reasons the
        economy controller emits per proposal explain the rest.
        """

        world = attention.world
        demand = status.demand
        unit_demand = {
            unit.unit_type.name: unit.missing
            for unit in demand.units
            if unit.buildable_shortfall > 0
        }
        # Owed, but the game will not allow it yet: the reason a producer for
        # it is standing still, and a reason not to reserve minerals for it.
        tech_blocked = {
            unit.unit_type.name: unit.missing
            for unit in demand.units
            if unit.missing > 0 and not unit.tech_ready
        }
        capacity = {
            assessment.structure_type.name: {
                "demanded": assessment.demanded,
                "current": assessment.current,
                "desired": assessment.desired,
                "reason": assessment.reason,
            }
            for assessment in status.capacity
        }
        signature = (
            round(demand.desired_supply, 1),
            round(demand.current_supply, 1),
            tuple(sorted(unit_demand.items())),
            tuple(sorted(tech_blocked.items())),
            tuple(sorted((name, str(value)) for name, value in capacity.items())),
            tuple(sorted(proposal.deduplication_key for proposal in status.proposals)),
        )
        periodic = world.time - self._last_status_log_at >= self._STATUS_LOG_INTERVAL
        if signature == self._last_status_signature and not periodic:
            return
        self._last_status_signature = signature
        self._last_status_log_at = world.time

        self.logger.event(
            "macro.status",
            component=COMPONENT,
            game_time=world.time,
            data={
                "opening": {
                    "name": world.economy.opening_name,
                    "completed": world.economy.opening_completed,
                },
                "resources": {
                    "bank": [bank.minerals, bank.vespene],
                    "protected": [
                        result.protected_cost.minerals,
                        result.protected_cost.vespene,
                    ],
                    "reserved": [
                        result.reserved_cost.minerals,
                        result.reserved_cost.vespene,
                    ],
                    "free": [
                        result.available_bank.minerals,
                        result.available_bank.vespene,
                    ],
                },
                "army": {
                    "desired_supply": round(demand.desired_supply, 1),
                    "ready_supply": round(demand.ready_supply, 1),
                    "pending_supply": round(demand.pending_supply, 1),
                    "supply_debt": round(demand.supply_debt, 1),
                },
                "unit_demand": unit_demand,
                "tech_blocked": tech_blocked,
                "production": [
                    {
                        "type": producer.unit_type.name,
                        "ready": producer.ready,
                        "idle": producer.idle,
                        "pending": producer.pending,
                        "utilization_20s": round(producer.utilization_20s, 2),
                    }
                    for producer in world.economy.producers
                ],
                "capacity": capacity,
                "proposals": [
                    {
                        "key": proposal.deduplication_key,
                        "priority": proposal.priority,
                        "reason": proposal.reason,
                    }
                    for proposal in status.proposals
                ],
            },
        )

    def _log_idle_producers(
        self,
        attention: AttentionSnapshot,
        status: MacroStatus,
        bank: ResourceBank,
        protected: ResourceCost,
    ) -> None:
        """Flag production that is idle with no reason to be.

        Idle is often correct: saving for a protected timing, nothing this
        structure makes being wanted, or the owed unit needing an add-on this
        particular building may not have -- ``macro.status`` carries all
        three. This warning is deliberately narrow so that it stays worth
        reading: something a bare structure of this type could build is owed,
        the money for it is free, and it still has not been built.
        """

        world = attention.world
        spendable = bank.hold_towards(protected)
        buildable_here = status.demand.producer_types_in_demand
        for producer in world.economy.producers:
            owed = tuple(
                unit
                for unit in status.demand.units
                if unit.buildable_shortfall > 0
                and producer.unit_type
                in UNIT_TRAINED_FROM.get(unit.unit_type, ())
            )
            unexplained = (
                producer.idle > 0
                and producer.unit_type in buildable_here
                and any(spendable.can_afford(unit.cost) for unit in owed)
            )
            if not unexplained:
                self._idle_producer_since.pop(producer.unit_type, None)
                continue
            since = self._idle_producer_since.setdefault(
                producer.unit_type, world.time
            )
            if world.time - since < self._IDLE_PRODUCER_WARNING_AFTER:
                continue
            self._idle_producer_since[producer.unit_type] = world.time
            self.logger.event(
                "macro.idle_producer_unexplained",
                component=COMPONENT,
                game_time=world.time,
                data={
                    "producer": producer.unit_type.name,
                    "idle": producer.idle,
                    "ready": producer.ready,
                    "utilization_20s": round(producer.utilization_20s, 2),
                    "owed_units": {unit.unit_type.name: unit.missing for unit in owed},
                    "spendable": [spendable.minerals, spendable.vespene],
                    "protected": [protected.minerals, protected.vespene],
                    "duration_seconds": round(
                        world.time - since, 1
                    ),
                },
            )
