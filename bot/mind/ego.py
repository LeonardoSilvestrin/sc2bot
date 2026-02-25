# bot/mind/ego.py
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
class EgoConfig:
    command_budget: int = 2
    soft_preempt_at: int = 60
    hard_preempt_at: int = 80

    # audit/debug
    log_ego_steps: bool = True
    log_every_iters: int = 22  # throttle: loga a cada N iters mesmo sem mudança


@dataclass
class Active:
    task: Task
    score: int


class Ego:
    def __init__(self, *, leases: UnitLeases, log: DevLogger, cfg: Optional[EgoConfig] = None):
        self.leases = leases
        self.log = log
        self.cfg = cfg or EgoConfig()
        self._planners: List[Planner] = []
        self._active_by_domain: Dict[str, Active] = {}

        # audit state
        self._last_logged_tid: Dict[str, str] = {}
        self._last_logged_iter: Dict[str, int] = {}

    def register_planner(self, planner: Planner) -> None:
        self._planners.append(planner)

    def register_planners(self, planners: List[Planner]) -> None:
        for p in planners:
            self.register_planner(p)

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

    def _maybe_log_ego_step(self, *, tick: TaskTick, domain: str, slot: Active) -> None:
        if not self.cfg.log_ego_steps:
            return

        tid = str(slot.task.task_id)
        it = int(tick.iteration)

        last_tid = self._last_logged_tid.get(domain)
        last_it = self._last_logged_iter.get(domain, -10_000)

        changed = (last_tid != tid)
        due = (it - last_it) >= int(self.cfg.log_every_iters)

        if changed or due:
            self._last_logged_tid[domain] = tid
            self._last_logged_iter[domain] = it

            self.log.emit(
                "ego_step",
                {
                    "iteration": it,
                    "time": round(float(tick.time), 2),
                    "domain": domain,
                    "tid": tid,
                    "score": int(slot.score),
                },
            )

    def _cleanup_done_tasks(self, *, now: float) -> None:
        """
        Remove tasks that reached DONE/ABORTED and free their leases.
        """
        to_remove: List[str] = []

        for domain, slot in self._active_by_domain.items():
            if slot.task.is_done():
                # libera unidades associadas
                try:
                    self.leases.release_owner(task_id=slot.task.task_id)
                except Exception:
                    pass

                self.log.emit(
                    "task_finished",
                    {
                        "domain": domain,
                        "tid": slot.task.task_id,
                        "status": slot.task.status().value,
                    },
                )

                to_remove.append(domain)

        for domain in to_remove:
            del self._active_by_domain[domain]

    async def tick(self, bot, *, tick: TaskTick, attention: Attention, awareness: Awareness) -> None:
        now = float(tick.time)

        # 1) limpeza de leases expirados
        self.leases.reap(now=now)

        # 2) limpeza de tasks concluídas (fix principal)
        self._cleanup_done_tasks(now=now)

        # 3) coletar propostas
        proposals: List[Proposal] = []
        for pl in self._planners:
            try:
                proposals.extend(pl.propose(bot, awareness=awareness, attention=attention))
            except Exception as e:
                self.log.emit(
                    "planner_error",
                    {"planner": getattr(pl, "planner_id", "unknown"), "err": str(e)},
                )

        desired = self._pick_from_proposals(proposals)

        # 4) preempção por urgência
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

        # 5) swap active tasks
        for domain, slot in desired.items():
            cur = self._active_by_domain.get(domain)

            if cur is None or cur.task.task_id != slot.task.task_id:
                if cur is not None:
                    await cur.task.abort(bot, reason="replaced")
                    self.leases.release_owner(task_id=cur.task.task_id)
                    self.log.emit(
                        "task_replaced",
                        {"domain": domain, "from": cur.task.task_id, "to": slot.task.task_id},
                    )

                self._active_by_domain[domain] = slot
                self.log.emit(
                    "task_selected",
                    {"domain": domain, "tid": slot.task.task_id, "score": slot.score},
                )

        # 6) execução com budget (DEFENSE first)
        budget = int(self.cfg.command_budget)

        ordered: List[Tuple[str, Active]] = sorted(
            self._active_by_domain.items(),
            key=lambda kv: (0 if kv[0] == "DEFENSE" else 1, -kv[1].score),
        )

        for domain, slot in ordered:
            if budget <= 0:
                break

            # audit
            self._maybe_log_ego_step(tick=tick, domain=domain, slot=slot)

            used = await slot.task.step(bot, tick, attention)

            # pós-step: se terminou durante step, limpar imediatamente
            if slot.task.is_done():
                self.leases.release_owner(task_id=slot.task.task_id)
                self.log.emit(
                    "task_finished",
                    {
                        "domain": domain,
                        "tid": slot.task.task_id,
                        "status": slot.task.status().value,
                    },
                )
                del self._active_by_domain[domain]
                continue

            if used:
                budget -= 1