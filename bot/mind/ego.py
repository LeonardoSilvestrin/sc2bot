# bot/mind/ego.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.mind.body import UnitLeases
from bot.planners.proposals import Proposal, UnitRequirement
from bot.tasks.base import TaskTick, TaskResult, TaskStatus  # ajuste import se seu arquivo chama base.py
# Se o seu path real for bot/tasks/base_task.py, troque pra:
# from bot.tasks.base_task import TaskTick, TaskResult, TaskStatus


# -----------------------
# CompositeTask (execução de N subtasks dentro da mesma missão)
# -----------------------
@dataclass
class CompositeTask:
    """
    Um 'task' composto que executa várias subtasks no mesmo tick.
    Ele implementa a interface que o Ego espera (step/status/is_done).

    IMPORTANTE:
    - O mission_id é único (da missão).
    - assigned_tags é o pool da missão (por enquanto).
      No próximo passo, vamos particionar tags por subtask (LeaseGroup).
    """
    domain: str
    children: List[Any] = field(default_factory=list)

    # mission binding (injetado pelo Ego)
    mission_id: Optional[str] = None
    assigned_tags: List[int] = field(default_factory=list)

    _status: str = "IDLE"
    _last_reason: str = ""

    def bind_mission(self, *, mission_id: str, assigned_tags: List[int]) -> None:
        self.mission_id = str(mission_id)
        self.assigned_tags = [int(x) for x in (assigned_tags or [])]

        # repassa bind pra children (se suportarem)
        for t in self.children:
            if hasattr(t, "bind_mission"):
                t.bind_mission(mission_id=self.mission_id, assigned_tags=list(self.assigned_tags))
            else:
                # fallback: não ideal, mas mantém compat
                try:
                    setattr(t, "mission_id", self.mission_id)
                    setattr(t, "assigned_tags", list(self.assigned_tags))
                except Exception:
                    pass

    def status(self) -> str:
        return self._status

    def is_done(self) -> bool:
        return self._status in ("DONE", "ABORTED")

    async def step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        if self.is_done():
            return TaskResult.noop("already_done")

        if not self.mission_id:
            self._status = "PAUSED"
            self._last_reason = "unbound_mission"
            return TaskResult.failed("unbound_mission", retry_after_s=0.0)

        self._status = "ACTIVE"

        any_running = False
        any_noop = False

        for t in self.children:
            # roda cada child; se child não tiver step, tenta on_step
            try:
                if hasattr(t, "step"):
                    r = await t.step(bot, tick, attention)
                else:
                    r = await t.on_step(bot, tick, attention)
            except Exception:
                # falha hard do plano
                self._status = "ACTIVE"
                self._last_reason = "child_exception"
                return TaskResult.failed("child_exception", retry_after_s=8.0)

            # normaliza bool legado
            if isinstance(r, bool):
                r = TaskResult.running("did_any" if r else "idle")

            if not isinstance(r, TaskResult):
                r = TaskResult.running("unknown_child_return")

            if r.status == "FAILED":
                self._last_reason = f"child_failed:{r.reason}"
                return TaskResult.failed(self._last_reason, retry_after_s=max(0.0, float(r.retry_after_s or 0.0)))

            if r.status == "DONE":
                # continua rodando outros; o plano só termina quando TODOS terminarem
                pass
            elif r.status == "NOOP":
                any_noop = True
            else:
                any_running = True

        # Se nenhum child está RUNNING, consideramos plano DONE
        if not any_running:
            self._status = "DONE"
            self._last_reason = "all_children_done"
            return TaskResult.done("all_children_done")

        # Caso contrário, está ativo
        self._status = "ACTIVE"
        return TaskResult.running("composite_running" if not any_noop else "composite_running_with_noop")


# -----------------------
# Commitment / Mission
# -----------------------
@dataclass
class Commitment:
    """
    An admitted proposal becomes a commitment (mission).
    Holds unit ownership via Body (leases) under mission_id.
    """
    mission_id: str
    proposal_id: str
    domain: str
    task: Any  # Task-like (BaseTask or CompositeTask)
    started_at: float
    expires_at: float
    non_preemptible_until: float
    assigned_tags: List[int] = field(default_factory=list)

    def is_expired(self, now: float) -> bool:
        return float(now) >= float(self.expires_at)

    def is_non_preemptible(self, now: float) -> bool:
        return float(now) < float(self.non_preemptible_until)


# -----------------------
# Ego config
# -----------------------
@dataclass(frozen=True)
class EgoConfig:
    one_commitment_per_domain: bool = True

    threat_block_start_at: int = 70
    threat_force_preempt_at: int = 90

    non_preemptible_grace_s: float = 2.5
    default_failure_cooldown_s: float = 8.0


# -----------------------
# Ego
# -----------------------
class Ego:
    def __init__(
        self,
        *,
        body: UnitLeases,
        log: Any = None,
        cfg: EgoConfig = EgoConfig(),
    ):
        self.body = body
        self.log = log
        self.cfg = cfg

        self._planners: List[Any] = []
        self._active_by_domain: Dict[str, Commitment] = {}

    def register_planners(self, planners: Sequence[Any]) -> None:
        self._planners = list(planners)

    async def tick(self, bot, *, tick: TaskTick, attention: Attention, awareness: Awareness) -> None:
        now = float(tick.time)

        # Reap expired leases
        try:
            self.body.reap(now=now)
        except Exception:
            pass

        # End expired commitments (and release their leases)
        self._reap_commitments(now=now, awareness=awareness)

        # Collect proposals
        proposals: List[Proposal] = []
        for p in self._planners:
            try:
                ps = p.propose(bot, awareness=awareness, attention=attention) or []
                proposals.extend(ps)
            except Exception as e:
                awareness.emit("planner_error", now=now, data={"planner": getattr(p, "planner_id", "?"), "err": str(e)})
                continue

        proposals.sort(key=lambda x: int(getattr(x, "score", 0)), reverse=True)

        await self._admit(bot, now=now, attention=attention, awareness=awareness, proposals=proposals)
        await self._execute(bot, tick=tick, attention=attention, awareness=awareness)

    # -----------------------
    # Admission
    # -----------------------
    async def _admit(
        self,
        bot,
        *,
        now: float,
        attention: Attention,
        awareness: Awareness,
        proposals: List[Proposal],
    ) -> None:
        threatened = bool(attention.combat.threatened)
        urgency = int(attention.combat.defense_urgency)

        for prop in proposals:
            domain = str(prop.domain)

            if self._is_in_cooldown(awareness, now=now, proposal_id=prop.proposal_id):
                continue

            if self.cfg.one_commitment_per_domain and domain in self._active_by_domain:
                continue

            if threatened and urgency >= self.cfg.threat_block_start_at and domain != "DEFENSE":
                continue

            # 1) mission_id único
            mission_id = f"{prop.proposal_id}:{int(now * 1000)}"

            # 2) claim atômico do plano (por enquanto: requirements agregados no Proposal)
            ok, tags, fail_reason = self._select_and_claim_units(
                bot,
                now=now,
                attention=attention,
                proposal=prop,
                mission_id=mission_id,
            )
            if not ok:
                self._set_cooldown(
                    awareness,
                    now=now,
                    proposal_id=prop.proposal_id,
                    seconds=max(2.0, float(getattr(prop, "cooldown_s", 2.0))),
                    reason=fail_reason,
                )
                continue

            # 3) construir tasks do plano (compat: 1 factory vira plano de 1 task)
            try:
                task_obj = self._build_task_plan(prop, mission_id=mission_id)
            except Exception as e:
                try:
                    self.body.release_owner(task_id=mission_id)
                except Exception:
                    pass
                self._set_cooldown(awareness, now=now, proposal_id=prop.proposal_id, seconds=8.0, reason="task_factory_error")
                awareness.emit("mission_rejected", now=now, data={"proposal_id": prop.proposal_id, "err": str(e)})
                continue

            # 4) bind missão (contrato único)
            self._bind_task(task_obj, mission_id=mission_id, assigned_tags=list(tags))

            ttl = float(getattr(prop, "lease_ttl", 30.0))
            non_preempt = now + float(getattr(prop, "non_preemptible_s", 0.0) or self.cfg.non_preemptible_grace_s)

            c = Commitment(
                mission_id=mission_id,
                proposal_id=prop.proposal_id,
                domain=domain,
                task=task_obj,
                started_at=now,
                expires_at=now + ttl,
                non_preemptible_until=non_preempt,
                assigned_tags=list(tags),
            )
            self._active_by_domain[domain] = c

            self._awareness_start_mission(awareness, now=now, c=c)

            awareness.emit(
                "mission_started",
                now=now,
                data={"mission_id": mission_id, "proposal_id": prop.proposal_id, "domain": domain, "tags": len(tags), "ttl": ttl},
            )
            if self.log:
                try:
                    self.log.emit(
                        "mission_started",
                        {"time": round(now, 2), "mission_id": mission_id, "proposal_id": prop.proposal_id, "domain": domain, "tags": len(tags)},
                    )
                except Exception:
                    pass

    def _build_task_plan(self, prop: Proposal, *, mission_id: str) -> Any:
        """
        Compat mode:
        - Se prop tiver `task_factories: List[Callable[[str], object]]`, vira CompositeTask.
        - Caso contrário, usa `task_factory` único como antes.
        """
        task_factories = getattr(prop, "task_factories", None)
        if task_factories:
            children = [f(mission_id) for f in list(task_factories)]
            return CompositeTask(domain=str(prop.domain), children=children)

        # fallback: 1 task
        return prop.task_factory(mission_id)

    def _bind_task(self, task_obj: Any, *, mission_id: str, assigned_tags: List[int]) -> None:
        if hasattr(task_obj, "bind_mission"):
            task_obj.bind_mission(mission_id=mission_id, assigned_tags=list(assigned_tags))
            return

        # fallback (não ideal)
        try:
            setattr(task_obj, "mission_id", str(mission_id))
            setattr(task_obj, "assigned_tags", list(assigned_tags))
        except Exception:
            pass

    def _select_and_claim_units(
        self,
        bot,
        *,
        now: float,
        attention: Attention,
        proposal: Proposal,
        mission_id: str,
    ) -> Tuple[bool, List[int], str]:
        reqs: List[UnitRequirement] = list(getattr(proposal, "unit_requirements", []) or [])
        if not reqs:
            return True, [], ""

        units_ready = getattr(attention.economy, "units_ready", {}) or {}
        selected: List[int] = []

        for req in reqs:
            utype = req.unit_type
            need = int(req.count)

            if int(units_ready.get(utype, 0)) <= 0:
                return False, [], f"no_{utype.name.lower()}"

            candidates: List[int] = []
            try:
                for u in bot.units.of_type(utype).ready:
                    tag = int(u.tag)
                    if self.body.can_claim(tag, now=now):
                        candidates.append(tag)
            except Exception:
                return False, [], "unit_iter_error"

            if len(candidates) < need:
                return False, [], f"insufficient_free_{utype.name.lower()}"

            selected.extend(candidates[:need])

        ttl = float(getattr(proposal, "lease_ttl", 30.0))
        role = self.body._role_for_domain(str(getattr(proposal, "domain", "MACRO")))

        # claim atômico: se falhar 1, rollback tudo
        for tag in selected:
            ok = self.body.claim(task_id=mission_id, unit_tag=tag, role=role, now=now, ttl=ttl, force=False)
            if not ok:
                try:
                    self.body.release_owner(task_id=mission_id)
                except Exception:
                    pass
                return False, [], "claim_failed"

        return True, selected, ""

    # -----------------------
    # Execution
    # -----------------------
    async def _execute(self, bot, *, tick: TaskTick, attention: Attention, awareness: Awareness) -> None:
        now = float(tick.time)

        for domain, c in list(self._active_by_domain.items()):
            if c.is_expired(now):
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason="expired")
                continue

            res = await self._run_task_safely(c, bot=bot, tick=tick, attention=attention, awareness=awareness)

            if res.status == "FAILED":
                cooldown = res.retry_after_s if res.retry_after_s > 0 else self.cfg.default_failure_cooldown_s
                self._set_cooldown(awareness, now=now, proposal_id=c.proposal_id, seconds=cooldown, reason=res.reason)
                self._finish_mission(awareness, now=now, c=c, status="FAILED", reason=res.reason)
                continue

            if res.status == "DONE":
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason=res.reason)
                continue

            awareness.emit("mission_step", now=now, data={"mission_id": c.mission_id, "domain": c.domain, "status": res.status, "reason": res.reason})

    async def _run_task_safely(self, c: Commitment, *, bot, tick: TaskTick, attention: Attention, awareness: Awareness) -> TaskResult:
        now = float(tick.time)

        try:
            if hasattr(c.task, "step"):
                out = await c.task.step(bot, tick, attention)
            else:
                out = await c.task.on_step(bot, tick, attention)
        except Exception as e:
            awareness.emit("task_exception", now=now, data={"mission_id": c.mission_id, "task_id": getattr(c.task, "task_id", "?"), "err": str(e)})
            if self.log:
                try:
                    self.log.emit("task_exception", {"t": round(now, 2), "mission_id": c.mission_id, "err": str(e)})
                except Exception:
                    pass
            return TaskResult.failed(reason="exception", retry_after_s=self.cfg.default_failure_cooldown_s)

        if isinstance(out, bool):
            return TaskResult.running(reason="did_any" if out else "idle")
        if isinstance(out, TaskResult):
            return out

        awareness.emit("task_return_unknown", now=now, data={"mission_id": c.mission_id, "task_id": getattr(c.task, "task_id", "?"), "type": str(type(out))})
        return TaskResult.running(reason="unknown_return")

    # -----------------------
    # Preemption
    # -----------------------
    def maybe_force_preempt(self, *, now: float, attention: Attention, awareness: Awareness) -> None:
        threatened = bool(attention.combat.threatened)
        urgency = int(attention.combat.defense_urgency)
        if not threatened or urgency < self.cfg.threat_force_preempt_at:
            return

        for domain, c in list(self._active_by_domain.items()):
            if domain == "DEFENSE":
                continue
            if c.is_non_preemptible(now):
                continue
            self._finish_mission(awareness, now=now, c=c, status="FAILED", reason="preempted_by_threat")

    # -----------------------
    # Mission lifecycle
    # -----------------------
    def _reap_commitments(self, *, now: float, awareness: Awareness) -> None:
        for domain, c in list(self._active_by_domain.items()):
            if c.is_expired(now):
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason="expired")

    def _finish_mission(self, awareness: Awareness, *, now: float, c: Commitment, status: str, reason: str) -> None:
        try:
            self.body.release_owner(task_id=c.mission_id)
        except Exception:
            pass

        self._awareness_end_mission(awareness, now=now, mission_id=c.mission_id, status=status, reason=reason)
        self._active_by_domain.pop(c.domain, None)

        awareness.emit("mission_ended", now=now, data={"mission_id": c.mission_id, "proposal_id": c.proposal_id, "domain": c.domain, "status": status, "reason": reason})
        if self.log:
            try:
                self.log.emit("mission_ended", {"time": round(now, 2), "mission_id": c.mission_id, "domain": c.domain, "status": status, "reason": reason})
            except Exception:
                pass

    def _awareness_start_mission(self, awareness: Awareness, *, now: float, c: Commitment) -> None:
        awareness.mem.set(K("ops", "mission", c.mission_id, "status"), value="RUNNING", now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "domain"), value=c.domain, now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "proposal_id"), value=c.proposal_id, now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "started_at"), value=float(c.started_at), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "expires_at"), value=float(c.expires_at), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "non_preemptible_until"), value=float(c.non_preemptible_until), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "assigned_tags"), value=list(c.assigned_tags), now=now, ttl=None)

    def _awareness_end_mission(self, awareness: Awareness, *, now: float, mission_id: str, status: str, reason: str) -> None:
        awareness.mem.set(K("ops", "mission", mission_id, "status"), value=str(status), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", mission_id, "end_reason"), value=str(reason), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", mission_id, "ended_at"), value=float(now), now=now, ttl=None)

    # -----------------------
    # Cooldown
    # -----------------------
    def _cooldown_key(self, proposal_id: str) -> Tuple[str, ...]:
        return K("ops", "cooldown", proposal_id)

    def _is_in_cooldown(self, awareness: Awareness, *, now: float, proposal_id: str) -> bool:
        until = awareness.mem.get(self._cooldown_key(proposal_id), now=now, default=0.0)
        try:
            return float(until) > float(now)
        except Exception:
            return False

    def _set_cooldown(self, awareness: Awareness, *, now: float, proposal_id: str, seconds: float, reason: str = "") -> None:
        until = float(now) + float(seconds)
        awareness.mem.set(self._cooldown_key(proposal_id), value=until, now=now, ttl=None)
        if reason:
            awareness.mem.set(K("ops", "cooldown_reason", proposal_id), value=str(reason), now=now, ttl=None)
        awareness.emit("proposal_cooldown_set", now=now, data={"proposal_id": proposal_id, "until": round(until, 2), "reason": reason})