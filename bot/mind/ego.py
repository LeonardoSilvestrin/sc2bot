from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from bot.devlog import DevLogger
from bot.planners.proposals import Planner, Proposal
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness
from bot.infra.unit_leases import UnitLeases
from bot.tasks.base import Task, TaskTick


@dataclass
class egoConfig:
    command_budget: int = 2
    soft_preempt_at: int = 60
    hard_preempt_at: int = 80


@dataclass
class Active:
    task: Task
    score: int


class Ego:
    def __init__(self, *, leases: UnitLeases, log: DevLogger, cfg: Optional[egoConfig] = None):
        self.leases = leases
        self.log = log
        self.cfg = cfg or egoConfig()
        self._planners: List[Planner] = []
        self._active_by_domain: Dict[str, Active] = {}

    def register_planner(self, planner: Planner) -> None:
        self._planners.append(planner)

    def _pick_from_proposals(self, proposals: List[Proposal]) -> Dict[str, Active]:
        best: Dict[str, Active] = {}
        for p in proposals:
            score = int(p.score)
            if score <= 0:
                continue
            cur = best.get(p.domain)
            if cur is None or score > cur.score:
                best[p.domain] = Active(task=p.task, score=score)
        return best

    async def tick(self, bot, *, tick: TaskTick, attention: Attention, awareness: Awareness) -> None:
        now = float(tick.time)
        self.leases.reap(now=now)

        proposals: List[Proposal] = []
        for pl in self._planners:
            try:
                proposals.extend(pl.propose(bot, awareness=awareness, attention=attention))
            except Exception as e:
                self.log.emit("planner_error", {"planner": getattr(pl, "planner_id", "unknown"), "err": str(e)})

        desired = self._pick_from_proposals(proposals)

        # preempção
        if attention.defense_urgency >= self.cfg.hard_preempt_at:
            for domain in ("HARASS", "MAP"):
                slot = self._active_by_domain.get(domain)
                if slot:
                    await slot.task.abort(bot, reason=f"hard_preempt urgency={attention.defense_urgency}")
                    self.leases.release_owner(task_id=slot.task.task_id)
                    del self._active_by_domain[domain]
                    self.log.emit("task_hard_preempt", {"domain": domain, "tid": slot.task.task_id})
        elif attention.defense_urgency >= self.cfg.soft_preempt_at:
            for domain in ("HARASS", "MAP"):
                slot = self._active_by_domain.get(domain)
                if slot:
                    await slot.task.pause(bot, reason=f"soft_preempt urgency={attention.defense_urgency}")
                    self.log.emit("task_soft_preempt", {"domain": domain, "tid": slot.task.task_id})

        # swap active
        for domain, slot in desired.items():
            cur = self._active_by_domain.get(domain)
            if cur is None or cur.task.task_id != slot.task.task_id:
                if cur is not None:
                    await cur.task.abort(bot, reason="replaced")
                    self.leases.release_owner(task_id=cur.task.task_id)
                    self.log.emit("task_replaced", {"domain": domain, "from": cur.task.task_id, "to": slot.task.task_id})

                self._active_by_domain[domain] = slot
                self.log.emit("task_selected", {"domain": domain, "tid": slot.task.task_id, "score": slot.score})

        # execute with budget (DEFENSE first)
        budget = int(self.cfg.command_budget)
        ordered: List[Tuple[str, Active]] = sorted(
            self._active_by_domain.items(),
            key=lambda kv: (0 if kv[0] == "DEFENSE" else 1, -kv[1].score),
        )

        for domain, slot in ordered:
            if budget <= 0:
                break
            used = await slot.task.step(bot, tick, attention)
            if used:
                budget -= 1