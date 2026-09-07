from __future__ import annotations

from typing import Any

from bot.attention.models import AttentionSnapshot, WorldFacts
from bot.contracts.commands import EconomyCommands
from bot.contracts.economy import EconomicActionKind, EconomicProposal
from bot.contracts.logging import BotLogger
from bot.planners.macro import MacroPlannerConfig, ready_townhall_count


class EconomyController:
    """Admits economic proposals with in-tick resource reservation and
    dispatches them to self-gating Ares macro behaviors.

    Unlike ``MissionController``, economic actions are single-frame and
    self-gating (Ares re-checks affordability/idle state at execution time),
    so there is no multi-frame commitment lifecycle or unit lease to manage
    here — only admission and dispatch.
    """

    def __init__(self, *, logger: BotLogger, config: MacroPlannerConfig) -> None:
        self.logger = logger
        self.config = config
        self._active: dict[EconomicActionKind, str] = {}

    def tick(
        self,
        *,
        attention: AttentionSnapshot,
        proposals: tuple[EconomicProposal, ...],
        commands: EconomyCommands,
    ) -> None:
        world = attention.world
        now = world.time
        remaining_minerals = world.minerals
        remaining_vespene = world.vespene
        seen: set[EconomicActionKind] = set()

        for proposal in sorted(proposals, key=lambda item: -item.priority):
            seen.add(proposal.kind)
            if proposal.cost.affordable_with(
                minerals=remaining_minerals, vespene=remaining_vespene
            ):
                remaining_minerals -= proposal.cost.minerals
                remaining_vespene -= proposal.cost.vespene
                self._transition(proposal.kind, "admitted", now, proposal)
                self._dispatch(proposal.kind, world, commands)
            else:
                self._transition(
                    proposal.kind,
                    "rejected",
                    now,
                    proposal,
                    reason="insufficient_reserved_resources",
                )

        for kind in [kind for kind in self._active if kind not in seen]:
            del self._active[kind]
            self.logger.event(
                "economy.action_resolved",
                component="ego.economy_controller",
                game_time=now,
                data={"kind": kind.name},
            )

    def _dispatch(
        self,
        kind: EconomicActionKind,
        world: WorldFacts,
        commands: EconomyCommands,
    ) -> None:
        if kind is EconomicActionKind.PRODUCE_WORKER:
            commands.produce_worker(to_count=self.config.max_workers)
        elif kind is EconomicActionKind.PRODUCE_SUPPLY:
            commands.produce_supply(base_location=world.map.own_start)
        elif kind is EconomicActionKind.EXPAND:
            commands.expand(to_count=ready_townhall_count(world) + 1)

    def _transition(
        self,
        kind: EconomicActionKind,
        status: str,
        now: float,
        proposal: EconomicProposal,
        *,
        reason: str | None = None,
    ) -> None:
        if self._active.get(kind) == status:
            return
        self._active[kind] = status
        data: dict[str, Any] = {
            "proposal_id": proposal.proposal_id,
            "planner": proposal.planner,
            "kind": kind.name,
            "priority": proposal.priority,
            "reason": reason or proposal.reason,
            "cost_minerals": proposal.cost.minerals,
            "cost_vespene": proposal.cost.vespene,
            "cost_supply": proposal.cost.supply,
        }
        self.logger.event(
            f"economy.proposal_{status}",
            component="ego.economy_controller",
            game_time=now,
            data=data,
        )
