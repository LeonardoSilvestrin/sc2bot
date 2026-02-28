from __future__ import annotations

from typing import Any

from bot.devlog import DevLogger
from bot.planners.utils.proposals import Proposal, TaskSpec


class BasePlanner:
    """
    Shared planner helpers to keep planners lean and consistent.
    """

    planner_id: str
    log: DevLogger | None

    def proposal_id(self, suffix: str) -> str:
        return f"{self.planner_id}:{suffix}"

    @staticmethod
    def is_proposal_running(*, awareness, proposal_id: str, now: float) -> bool:
        return bool(awareness.ops_proposal_running(proposal_id=proposal_id, now=now))

    @staticmethod
    def due_by_last_done(*, awareness, key: tuple[str, ...], now: float, interval_s: float) -> bool:
        last = awareness.mem.get(key, now=now, default=None)
        if last is None:
            return True
        try:
            return (float(now) - float(last)) >= float(interval_s)
        except Exception:
            return True

    def make_single_task_proposal(
        self,
        *,
        proposal_id: str,
        domain: str,
        score: int,
        task_spec: TaskSpec,
        lease_ttl: float | None,
        cooldown_s: float = 0.0,
        risk_level: int = 0,
        allow_preempt: bool = True,
        reinforce_mission_id: str | None = None,
    ) -> list[Proposal]:
        return [
            Proposal(
                proposal_id=proposal_id,
                domain=domain,
                score=int(score),
                reinforce_mission_id=reinforce_mission_id,
                tasks=[task_spec],
                lease_ttl=lease_ttl,
                cooldown_s=float(cooldown_s),
                risk_level=int(risk_level),
                allow_preempt=bool(allow_preempt),
            )
        ]

    def emit_planner_proposed(self, payload: dict[str, Any]) -> None:
        if self.log is None:
            return
        out = {"planner": str(self.planner_id)}
        out.update(dict(payload))
        self.log.emit(
            "planner_proposed",
            out,
            meta={"module": "planner", "component": f"planner.{self.planner_id}"},
        )

