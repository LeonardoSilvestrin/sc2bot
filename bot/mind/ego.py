# bot/mind/ego.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.mind.body import UnitLeases
from bot.planners.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.base_task import Task, TaskTick, TaskResult


@dataclass
class Commitment:
    """
    An admitted Proposal becomes a Commitment (mission).
    Holds unit ownership via Body (leases) under mission_id.
    """
    mission_id: str
    proposal_id: str
    domain: str
    task: Task
    started_at: float
    expires_at: float
    non_preemptible_until: float
    assigned_tags: List[int] = field(default_factory=list)

    def is_expired(self, now: float) -> bool:
        return float(now) >= float(self.expires_at)

    def is_non_preemptible(self, now: float) -> bool:
        return float(now) < float(self.non_preemptible_until)


@dataclass(frozen=True)
class EgoConfig:
    """
    Strict behavior:
      - no fallback/compat layers
      - allow multiple concurrent missions in the same domain by default
    """
    one_commitment_per_domain: bool = False
    threat_block_start_at: int = 70
    threat_force_preempt_at: int = 90
    non_preemptible_grace_s: float = 2.5
    default_failure_cooldown_s: float = 8.0


class Ego:
    def __init__(self, *, body: UnitLeases, log: Any = None, cfg: EgoConfig = EgoConfig()):
        self.body = body
        self.log = log
        self.cfg = cfg

        self._planners: List[Any] = []
        self._active: Dict[str, Commitment] = {}           # mission_id -> Commitment
        self._active_by_domain: Dict[str, List[str]] = {}  # domain -> [mission_id]

    def register_planners(self, planners: Sequence[Any]) -> None:
        self._planners = list(planners)

    async def tick(self, bot, *, tick: TaskTick, attention: Attention, awareness: Awareness) -> None:
        now = float(tick.time)

        self.body.reap(now=now)
        self._reap_commitments(now=now, awareness=awareness)

        proposals: List[Proposal] = []
        for p in self._planners:
            ps = p.propose(bot, awareness=awareness, attention=attention) or []
            proposals.extend(ps)

        # Validate proposals NOW (crash-fast, no fallback)
        for prop in proposals:
            prop.validate()

        proposals.sort(key=lambda x: int(x.score), reverse=True)

        await self._admit(bot, now=now, attention=attention, awareness=awareness, proposals=proposals)
        await self._execute(bot, tick=tick, attention=attention, awareness=awareness)

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
            if self._is_in_cooldown(awareness, now=now, proposal_id=prop.proposal_id):
                continue

            domain = str(prop.domain)

            if self.cfg.one_commitment_per_domain and self._active_by_domain.get(domain):
                continue

            if threatened and urgency >= self.cfg.threat_block_start_at and domain != "DEFENSE":
                continue

            mission_id = f"{prop.proposal_id}:{int(now * 1000)}"
            spec: TaskSpec = prop.task()

            ok, tags, fail_reason = self._select_and_claim_units(
                bot,
                now=now,
                attention=attention,
                spec=spec,
                proposal=prop,
                mission_id=mission_id,
            )
            if not ok:
                self._set_cooldown(
                    awareness,
                    now=now,
                    proposal_id=prop.proposal_id,
                    seconds=float(prop.cooldown_s),
                    reason=fail_reason,
                )
                continue

            task_obj = spec.task_factory(mission_id)
            self._validate_task(task_obj, spec=spec)

            task_obj.bind_mission(mission_id=mission_id, assigned_tags=list(tags))

            ttl = float(spec.lease_ttl) if spec.lease_ttl is not None else float(prop.lease_ttl)
            non_preempt = now + float(self.cfg.non_preemptible_grace_s)

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
            self._active[mission_id] = c
            self._active_by_domain.setdefault(domain, []).append(mission_id)

            self._awareness_start_mission(awareness, now=now, c=c)
            awareness.emit(
                "mission_started",
                now=now,
                data={"mission_id": mission_id, "proposal_id": prop.proposal_id, "domain": domain, "tags": len(tags), "ttl": ttl},
            )

            if self.log is not None:
                self.log.emit(
                    "mission_started",
                    {"time": round(now, 2), "mission_id": mission_id, "proposal_id": prop.proposal_id, "domain": domain, "tags": len(tags)},
                )

    def _validate_task(self, task_obj: Any, *, spec: TaskSpec) -> None:
        if not isinstance(task_obj, Task):
            raise TypeError(f"Task factory for {spec.task_id} returned non-Task: {type(task_obj)!r}")

    def _select_and_claim_units(
        self,
        bot,
        *,
        now: float,
        attention: Attention,
        spec: TaskSpec,
        proposal: Proposal,
        mission_id: str,
    ) -> Tuple[bool, List[int], str]:
        reqs: List[UnitRequirement] = list(spec.unit_requirements)
        if not reqs:
            return True, [], ""

        units_ready = attention.economy.units_ready
        selected: List[int] = []

        for req in reqs:
            utype = req.unit_type
            need = int(req.count)

            if int(units_ready.get(utype, 0)) <= 0:
                return False, [], f"no_{utype.name.lower()}"

            candidates: List[int] = []
            for u in bot.units.of_type(utype).ready:
                tag = int(u.tag)
                if self.body.can_claim(tag, now=now):
                    candidates.append(tag)

            if len(candidates) < need:
                return False, [], f"insufficient_free_{utype.name.lower()}"

            selected.extend(candidates[:need])

        ttl = float(spec.lease_ttl) if spec.lease_ttl is not None else float(proposal.lease_ttl)
        role = self.body._role_for_domain(str(proposal.domain))

        for tag in selected:
            ok = self.body.claim(task_id=mission_id, unit_tag=tag, role=role, now=now, ttl=ttl, force=False)
            if not ok:
                self.body.release_owner(task_id=mission_id)
                return False, [], "claim_failed"

        return True, selected, ""

    def _touch_leases_for_commitment(self, *, now: float, c: Commitment) -> None:
        """
        Keep unit leases alive while the mission is active.

        Contract:
          - Leases are owned by mission_id (not task_id).
          - Tasks should NOT claim/touch leases directly for correctness and testability.
        """
        if not c.assigned_tags:
            return
        remaining = float(c.expires_at) - float(now)
        if remaining <= 0.0:
            return
        # renew leases just long enough to survive until mission expiry
        ttl = max(0.25, min(8.0, remaining))
        for tag in c.assigned_tags:
            self.body.touch(task_id=c.mission_id, unit_tag=int(tag), now=now, ttl=ttl)

    async def _execute(self, bot, *, tick: TaskTick, attention: Attention, awareness: Awareness) -> None:
        now = float(tick.time)

        for mission_id, c in list(self._active.items()):
            if c.is_expired(now):
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason="expired")
                continue

            # keep leases alive
            self._touch_leases_for_commitment(now=now, c=c)

            res = await c.task.step(bot, tick, attention)

            if res.status == "FAILED":
                cooldown = float(res.retry_after_s) if float(res.retry_after_s) > 0 else float(self.cfg.default_failure_cooldown_s)
                self._set_cooldown(awareness, now=now, proposal_id=c.proposal_id, seconds=cooldown, reason=res.reason)
                self._finish_mission(awareness, now=now, c=c, status="FAILED", reason=res.reason)
                continue

            if res.status == "DONE":
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason=res.reason)
                continue

            awareness.emit("mission_step", now=now, data={"mission_id": c.mission_id, "domain": c.domain, "status": res.status, "reason": res.reason})

    def _reap_commitments(self, *, now: float, awareness: Awareness) -> None:
        for mission_id, c in list(self._active.items()):
            if c.is_expired(now):
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason="expired")

    def _finish_mission(self, awareness: Awareness, *, now: float, c: Commitment, status: str, reason: str) -> None:
        self.body.release_owner(task_id=c.mission_id)

        self._active.pop(c.mission_id, None)
        ids = self._active_by_domain.get(c.domain)
        if ids is not None:
            try:
                ids.remove(c.mission_id)
            except ValueError:
                pass
            if not ids:
                self._active_by_domain.pop(c.domain, None)

        self._awareness_end_mission(awareness, now=now, mission_id=c.mission_id, status=status, reason=reason)
        awareness.emit(
            "mission_ended",
            now=now,
            data={"mission_id": c.mission_id, "proposal_id": c.proposal_id, "domain": c.domain, "status": status, "reason": reason},
        )

    def _is_in_cooldown(self, awareness: Awareness, *, now: float, proposal_id: str) -> bool:
        until = awareness.mem.get(K("ops", "cooldown", proposal_id, "until"), now=now, default=None)
        if until is None:
            return False
        return float(now) < float(until)

    def _set_cooldown(self, awareness: Awareness, *, now: float, proposal_id: str, seconds: float, reason: str) -> None:
        if seconds <= 0:
            return
        awareness.mem.set(K("ops", "cooldown", proposal_id, "until"), value=float(now) + float(seconds), now=now, ttl=None)
        awareness.mem.set(K("ops", "cooldown", proposal_id, "reason"), value=str(reason), now=now, ttl=None)

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
        awareness.mem.set(K("ops", "mission", mission_id, "reason"), value=str(reason), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", mission_id, "ended_at"), value=float(now), now=now, ttl=None)