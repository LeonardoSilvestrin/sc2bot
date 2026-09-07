from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from math import isfinite
from typing import Any

from bot.engine.economy.models import (
    EconomicAction,
    EconomicActionSnapshot,
    EconomicActionStatus,
    EconomicFeedback,
    EconomicFeedbackKind,
    EconomicProposal,
    EconomyTickResult,
    ResourceBank,
    ResourceCost,
)
from bot.ports.logging import BotLogger


@dataclass(slots=True)
class _Commitment:
    action: EconomicAction
    status: EconomicActionStatus = EconomicActionStatus.PENDING
    reason: str = "waiting_for_dispatch"
    dispatched_at: float | None = None
    finished_at: float | None = None

    def snapshot(self) -> EconomicActionSnapshot:
        return EconomicActionSnapshot(
            action=self.action,
            status=self.status,
            reason=self.reason,
            dispatched_at=self.dispatched_at,
            finished_at=self.finished_at,
        )


class EconomyController:
    """Arbitrate planner proposals and own economic action commitments.

    The controller has no knowledge of Ares or python-sc2. It returns funded
    ``EconomicAction`` values; an infrastructure adapter reports dispatch,
    completion, or failure as ``EconomicFeedback`` on a later tick.
    """

    def __init__(self, *, logger: BotLogger) -> None:
        self.logger = logger
        self._commitments: dict[str, _Commitment] = {}
        self._known_proposal_ids: set[str] = set()
        self._last_proposal_outcomes: dict[str, tuple[str, ...]] = {}
        self._action_sequence = 0
        self._last_tick_at = -1.0

    def snapshots(self) -> tuple[EconomicActionSnapshot, ...]:
        return tuple(
            commitment.snapshot()
            for commitment in sorted(
                self._commitments.values(),
                key=lambda item: (
                    item.action.admitted_at,
                    item.action.action_id,
                ),
            )
        )

    def tick(
        self,
        *,
        now: float,
        bank: ResourceBank,
        proposals: Iterable[EconomicProposal] = (),
        feedback: Iterable[EconomicFeedback] = (),
    ) -> EconomyTickResult:
        """Advance lifecycle and admit the highest-priority affordable work."""

        self._validate_time(now)
        feedback_items = tuple(feedback)
        proposal_items = tuple(proposals)
        self._apply_feedback(feedback_items, now)
        expired_keys = self._expire(now)

        available = bank
        for commitment in self._live_commitments(
            status=EconomicActionStatus.PENDING
        ):
            # A pending action owns its reservation. Saturating the hold keeps
            # the bank valid if unrelated game activity changed the observation.
            available = available.hold_towards(commitment.action.proposal.cost)

        admitted: list[EconomicAction] = []
        considered_proposal_ids: set[str] = set()
        considered_keys: set[str] = set()
        for proposal in sorted(proposal_items, key=self._proposal_order):
            self._log_proposal_once(proposal, now)

            if proposal.proposal_id in considered_proposal_ids:
                self._emit_proposal_outcome(
                    "economic_proposal_rejected",
                    now,
                    "duplicate_proposal_id_in_tick",
                    proposal=proposal,
                )
                continue
            considered_proposal_ids.add(proposal.proposal_id)

            if proposal.deduplication_key in considered_keys:
                self._emit_proposal_outcome(
                    "economic_proposal_rejected",
                    now,
                    "lower_ranked_duplicate_in_tick",
                    proposal=proposal,
                )
                continue
            considered_keys.add(proposal.deduplication_key)

            live = self._live_for_key(proposal.deduplication_key)
            if live is not None:
                self._emit_proposal_outcome(
                    "economic_proposal_rejected",
                    now,
                    "matching_economic_action_already_live",
                    proposal=proposal,
                    action=live.action,
                    outcome_detail=live.action.action_id,
                    status=live.status.name,
                )
                continue
            if proposal.deduplication_key in expired_keys:
                self._emit_proposal_outcome(
                    "economic_proposal_rejected",
                    now,
                    "matching_economic_action_timed_out_this_tick",
                    proposal=proposal,
                )
                continue

            bank_before = available
            if not available.can_afford(proposal.cost):
                available = available.hold_towards(proposal.cost)
                held = available.consumed_from(bank_before)
                self._emit_proposal_outcome(
                    "economic_proposal_deferred",
                    now,
                    "insufficient_virtual_bank",
                    proposal=proposal,
                    available_bank=self._bank_data(bank_before),
                    held_cost=self._cost_data(held),
                )
                continue

            available = available.reserve(proposal.cost)
            action = self._admit(proposal, now)
            admitted.append(action)

        self._last_tick_at = now
        return EconomyTickResult(
            admitted_actions=tuple(admitted),
            available_bank=available,
            reserved_cost=available.consumed_from(bank),
        )

    def _validate_time(self, now: float) -> None:
        if not isfinite(now) or now < 0.0:
            raise ValueError("now must be finite and non-negative")
        if now < self._last_tick_at:
            raise ValueError("economy controller time must not move backwards")

    @staticmethod
    def _proposal_order(proposal: EconomicProposal) -> tuple[Any, ...]:
        return (
            -proposal.priority,
            proposal.created_at,
            proposal.deduplication_key,
            proposal.proposal_id,
        )

    def _admit(self, proposal: EconomicProposal, now: float) -> EconomicAction:
        self._action_sequence += 1
        action = EconomicAction(
            action_id=f"economic-action-{self._action_sequence:04d}",
            proposal=proposal,
            admitted_at=now,
        )
        self._commitments[action.action_id] = _Commitment(action=action)
        # A later deferral/rejection for this stable proposal id is a new
        # lifecycle state and must be visible even if the same outcome occurred
        # before this action was admitted.
        self._last_proposal_outcomes[proposal.proposal_id] = (
            "economic_action_admitted",
            action.action_id,
        )
        self._emit(
            "economic_action_admitted",
            now,
            "resources_reserved",
            action=action,
        )
        self._emit(
            "economic_action_pending",
            now,
            "waiting_for_dispatch",
            action=action,
            status=EconomicActionStatus.PENDING.name,
        )
        return action

    def _apply_feedback(
        self, feedback_items: tuple[EconomicFeedback, ...], now: float
    ) -> None:
        seen_feedback: set[tuple[str, EconomicFeedbackKind]] = set()
        for item in feedback_items:
            feedback_key = (item.action_id, item.kind)
            if feedback_key in seen_feedback:
                self._emit(
                    "economic_feedback_rejected",
                    now,
                    "duplicate_feedback_in_tick",
                    feedback=item,
                )
                continue
            seen_feedback.add(feedback_key)

            commitment = self._commitments.get(item.action_id)
            if commitment is None:
                self._emit(
                    "economic_feedback_rejected",
                    now,
                    "unknown_economic_action",
                    feedback=item,
                )
                continue
            if commitment.status.terminal:
                self._emit(
                    "economic_feedback_rejected",
                    now,
                    "economic_action_already_terminal",
                    feedback=item,
                    action=commitment.action,
                    status=commitment.status.name,
                )
                continue

            if item.kind is EconomicFeedbackKind.DISPATCHED:
                if commitment.status is EconomicActionStatus.IN_FLIGHT:
                    continue
                commitment.status = EconomicActionStatus.IN_FLIGHT
                commitment.reason = item.reason
                commitment.dispatched_at = now
                self._emit(
                    "economic_action_dispatched",
                    now,
                    item.reason,
                    action=commitment.action,
                    status=commitment.status.name,
                )
            elif item.kind is EconomicFeedbackKind.CONFIRMED:
                self._finish(
                    commitment,
                    EconomicActionStatus.COMPLETED,
                    item.reason,
                    now,
                )
            else:
                self._finish(
                    commitment,
                    EconomicActionStatus.FAILED,
                    item.reason,
                    now,
                )

    def _expire(self, now: float) -> set[str]:
        expired_keys: set[str] = set()
        for commitment in self._live_commitments():
            proposal = commitment.action.proposal
            if commitment.status is EconomicActionStatus.PENDING:
                expired = (
                    now - commitment.action.admitted_at
                    >= proposal.dispatch_timeout_seconds
                )
                reason = "dispatch_timeout"
            else:
                assert commitment.dispatched_at is not None
                expired = (
                    now - commitment.dispatched_at
                    >= proposal.confirmation_timeout_seconds
                )
                reason = "confirmation_timeout"
            if not expired:
                continue
            expired_keys.add(proposal.deduplication_key)
            self._finish(
                commitment,
                EconomicActionStatus.TIMED_OUT,
                reason,
                now,
            )
        return expired_keys

    def _finish(
        self,
        commitment: _Commitment,
        status: EconomicActionStatus,
        reason: str,
        now: float,
    ) -> None:
        commitment.status = status
        commitment.reason = reason
        commitment.finished_at = now
        event = {
            EconomicActionStatus.COMPLETED: "economic_action_confirmed",
            EconomicActionStatus.FAILED: "economic_action_failed",
            EconomicActionStatus.TIMED_OUT: "economic_action_timed_out",
        }[status]
        self._emit(
            event,
            now,
            reason,
            action=commitment.action,
            status=status.name,
        )

    def _live_commitments(
        self, *, status: EconomicActionStatus | None = None
    ) -> tuple[_Commitment, ...]:
        return tuple(
            commitment
            for commitment in self._commitments.values()
            if not commitment.status.terminal
            and (status is None or commitment.status is status)
        )

    def _live_for_key(self, deduplication_key: str) -> _Commitment | None:
        return next(
            (
                commitment
                for commitment in self._live_commitments()
                if (
                    commitment.action.proposal.deduplication_key
                    == deduplication_key
                )
            ),
            None,
        )

    def _log_proposal_once(
        self, proposal: EconomicProposal, now: float
    ) -> None:
        if proposal.proposal_id in self._known_proposal_ids:
            return
        self._known_proposal_ids.add(proposal.proposal_id)
        self._emit(
            "economic_proposal_created",
            now,
            proposal.reason,
            proposal=proposal,
        )

    def _emit_proposal_outcome(
        self,
        event: str,
        now: float,
        reason: str,
        *,
        proposal: EconomicProposal,
        action: EconomicAction | None = None,
        outcome_detail: str = "",
        **extra: Any,
    ) -> None:
        """Log a proposal state transition without repeating it every frame."""

        signature = (
            event,
            reason,
            outcome_detail,
            str(extra.get("status", "")),
        )
        if self._last_proposal_outcomes.get(proposal.proposal_id) == signature:
            return
        self._last_proposal_outcomes[proposal.proposal_id] = signature
        self._emit(
            event,
            now,
            reason,
            proposal=proposal,
            action=action,
            **extra,
        )

    @staticmethod
    def _cost_data(cost: ResourceCost) -> dict[str, int | float]:
        return {
            "minerals": cost.minerals,
            "vespene": cost.vespene,
            "supply": cost.supply,
        }

    @staticmethod
    def _bank_data(bank: ResourceBank) -> dict[str, int | float]:
        return {
            "minerals": bank.minerals,
            "vespene": bank.vespene,
            "supply_available": bank.supply_available,
        }

    def _emit(
        self,
        event: str,
        now: float,
        reason: str,
        *,
        proposal: EconomicProposal | None = None,
        action: EconomicAction | None = None,
        feedback: EconomicFeedback | None = None,
        **extra: Any,
    ) -> None:
        if action is not None and proposal is None:
            proposal = action.proposal
        data: dict[str, Any] = {"reason": reason}
        if proposal is not None:
            data.update(
                proposal_id=proposal.proposal_id,
                deduplication_key=proposal.deduplication_key,
                planner_id=proposal.planner,
                action_kind=proposal.kind.name,
                priority=proposal.priority,
                target=proposal.target,
                target_count=proposal.target_count,
                proposal_reason=proposal.reason,
                cost=self._cost_data(proposal.cost),
            )
        if action is not None:
            data.update(
                action_id=action.action_id,
                admitted_at=action.admitted_at,
            )
        if feedback is not None:
            data.update(
                action_id=feedback.action_id,
                feedback_kind=feedback.kind.name,
                feedback_reason=feedback.reason,
            )
        data.update(extra)
        self.logger.event(
            event,
            component="engine.economy.controller",
            game_time=now,
            data=data,
        )
