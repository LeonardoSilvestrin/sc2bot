# bot/mind/ego.py
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bot.control.priority_policy import PriorityPolicy
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.mind.body import UnitLeases
from bot.planners.utils.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.base_task import Task, TaskTick, TaskResult


@dataclass
class Commitment:
    mission_id: str
    proposal_id: str
    domain: str
    task: Task
    started_at: float
    expires_at: Optional[float]
    non_preemptible_until: float
    assigned_tags: List[int] = field(default_factory=list)

    def is_expired(self, now: float) -> bool:
        return self.expires_at is not None and float(now) >= float(self.expires_at)


@dataclass(frozen=True)
class EgoConfig:
    threat_block_start_at: int = 70
    threat_force_preempt_at: int = 90
    non_preemptible_grace_s: float = 2.5
    default_failure_cooldown_s: float = 8.0
    singleton_domains: frozenset[str] = frozenset({"MACRO"})
    # Global anti-spam / pacing controls.
    default_task_min_step_interval_s: float = 0.0
    macro_task_min_step_interval_s: float = 0.35
    perf_log_interval_s: float = 2.0


class Ego:
    def __init__(self, *, body: UnitLeases, log: Any = None, cfg: EgoConfig = EgoConfig()):
        self.body = body
        self.log = log
        self.cfg = cfg
        self.priority_policy = PriorityPolicy()

        self._planners: List[Any] = []
        self._active: Dict[str, Commitment] = {}
        self._active_by_domain: Dict[str, List[str]] = {}
        self._last_mem_gc_at: float = -1.0
        self._last_perf_emit_at: float = -9999.0

    def register_planners(self, planners: Sequence[Any]) -> None:
        self._planners = list(planners)

    async def tick(self, bot, *, tick: TaskTick, attention: Attention, awareness: Awareness) -> None:
        now = float(tick.time)

        # Periodic memory compaction keeps O(n) scans from degrading over time.
        if self._last_mem_gc_at < 0.0 or (now - self._last_mem_gc_at) >= 8.0:
            removed = int(awareness.mem.prune(now=now, mission_retention_s=120.0, cooldown_retention_s=60.0))
            self._last_mem_gc_at = float(now)
            if self.log is not None and removed > 0:
                self.log.emit(
                    "awareness_gc",
                    {"time": round(now, 2), "removed": int(removed)},
                    meta={"module": "awareness", "component": "awareness"},
                )

        self.body.reap(now=now)
        self._reap_commitments(now=now, awareness=awareness)

        proposals: List[Proposal] = []
        planner_perf: list[dict[str, Any]] = []
        for planner in self._planners:
            every = int(getattr(planner, "propose_every_iters", 1) or 1)
            if every > 1 and (int(tick.iteration) % every) != 0:
                continue
            t0 = time.perf_counter()
            p = planner.propose(bot, awareness=awareness, attention=attention) or []
            dt_ms = (time.perf_counter() - t0) * 1000.0
            proposals.extend(p)
            if dt_ms >= 2.0:
                planner_perf.append(
                    {
                        "planner_id": str(getattr(planner, "planner_id", type(planner).__name__)),
                        "ms": round(float(dt_ms), 3),
                        "proposals": int(len(p)),
                        "every_iters": int(every),
                    }
                )

        for prop in proposals:
            prop.validate()

        self.priority_policy.begin_tick(attention=attention, awareness=awareness, now=now)
        proposals = self._prioritize_proposals(proposals=proposals, attention=attention, awareness=awareness, now=now)

        await self._admit(bot, now=now, attention=attention, awareness=awareness, proposals=proposals)
        task_perf = await self._execute(bot, tick=tick, attention=attention, awareness=awareness)

        if (
            self.log is not None
            and (planner_perf or task_perf)
            and (float(now) - float(self._last_perf_emit_at)) >= float(self.cfg.perf_log_interval_s)
        ):
            self.log.emit(
                "ego_perf",
                {
                    "iter": int(tick.iteration),
                    "t": round(float(now), 2),
                    "planner_slow": planner_perf,
                    "task_slow": task_perf,
                    "proposals_total": int(len(proposals)),
                    "active_missions": int(len(self._active)),
                },
                meta={"module": "runtime", "component": "runtime.perf"},
            )
            self._last_perf_emit_at = float(now)

    def _prioritize_proposals(
        self,
        *,
        proposals: List[Proposal],
        attention: Attention,
        awareness: Awareness,
        now: float,
    ) -> List[Proposal]:
        scored: List[Tuple[float, int, str, Proposal]] = []
        for prop in proposals:
            try:
                decision = self.priority_policy.evaluate(proposal=prop, attention=attention, awareness=awareness, now=now)
                eff = float(decision.effective_score)
            except Exception as e:
                awareness.mem.set(
                    K("control", "priority", "error", str(prop.proposal_id)),
                    value=str(type(e).__name__),
                    now=now,
                    ttl=10.0,
                )
                if self.log is not None:
                    self.log.emit(
                        "priority_policy_error",
                        {
                            "time": round(float(now), 2),
                            "proposal_id": str(prop.proposal_id),
                            "domain": str(prop.domain),
                            "error_type": str(type(e).__name__),
                            "error": str(e),
                        },
                    )
                raise RuntimeError(f"priority_policy_failed:{prop.proposal_id}:{type(e).__name__}") from e
            scored.append((eff, int(prop.score), str(prop.proposal_id), prop))

        # Deterministic ordering:
        # 1) effective_score (policy-adjusted)
        # 2) base planner score
        # 3) proposal_id lexical
        scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        return [prop for _eff, _base, _pid, prop in scored]

    async def _admit(
        self,
        bot,
        *,
        now: float,
        attention: Attention,
        awareness: Awareness,
        proposals: List[Proposal],
    ) -> None:
        urgency = int(attention.combat.primary_urgency)
        threatened = urgency > 0

        for prop in proposals:
            if self._is_in_cooldown(awareness, now=now, proposal_id=prop.proposal_id):
                continue

            domain = str(prop.domain)
            reinforce_mission_id = str(prop.reinforce_mission_id or "").strip()
            reinforce_commitment = self._active.get(reinforce_mission_id) if reinforce_mission_id else None

            # Never admit the same proposal while one is already running.
            if (not reinforce_mission_id) and self._is_proposal_running(prop.proposal_id):
                continue

            if reinforce_mission_id and reinforce_commitment is None:
                self._set_cooldown(
                    awareness,
                    now=now,
                    proposal_id=prop.proposal_id,
                    seconds=float(prop.cooldown_s),
                    reason="reinforce_target_missing",
                )
                continue

            effective_domain = domain if reinforce_commitment is None else str(reinforce_commitment.domain)
            if threatened and urgency >= self.cfg.threat_block_start_at and effective_domain != "DEFENSE":
                continue

            if reinforce_commitment is None and domain in self.cfg.singleton_domains:
                self._preempt_domain(now=now, awareness=awareness, domain=domain, reason=f"preempted_by:{prop.proposal_id}")

            mission_id = reinforce_mission_id if reinforce_commitment is not None else f"{prop.proposal_id}:{int(now * 1000)}"
            spec: TaskSpec = prop.task()

            ok, tags, fail_reason = self._select_and_claim_units(
                bot,
                now=now,
                attention=attention,
                spec=spec,
                proposal=prop,
                mission_id=mission_id,
                claim_domain=effective_domain,
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

            if reinforce_commitment is not None:
                if tags:
                    merged_tags = self._merge_tags(reinforce_commitment.assigned_tags, tags)
                    reinforce_commitment.assigned_tags = merged_tags
                    reinforce_commitment.task.add_assigned_tags(tags)
                    awareness.mem.set(
                        K("ops", "mission", reinforce_commitment.mission_id, "assigned_tags"),
                        value=list(merged_tags),
                        now=now,
                        ttl=None,
                    )
                    awareness.emit(
                        "mission_reinforced",
                        now=now,
                        data={
                            "mission_id": reinforce_commitment.mission_id,
                            "proposal_id": prop.proposal_id,
                            "domain": reinforce_commitment.domain,
                            "added_tags": len(tags),
                            "total_tags": len(merged_tags),
                        },
                    )
                    if self.log is not None:
                        self.log.emit(
                            "mission_reinforced",
                            {
                                "time": round(now, 2),
                                "mission_id": reinforce_commitment.mission_id,
                                "proposal_id": prop.proposal_id,
                                "domain": reinforce_commitment.domain,
                                "added_tags": len(tags),
                                "total_tags": len(merged_tags),
                            },
                        )
                continue

            task_obj = spec.task_factory(mission_id)
            self._validate_task(task_obj, spec=spec)
            task_obj.bind_mission(mission_id=mission_id, assigned_tags=list(tags))

            ttl = spec.lease_ttl if spec.lease_ttl is not None else prop.lease_ttl
            expires_at = None if ttl is None else (float(now) + float(ttl))

            c = Commitment(
                mission_id=mission_id,
                proposal_id=prop.proposal_id,
                domain=domain,
                task=task_obj,
                started_at=float(now),
                expires_at=expires_at,
                non_preemptible_until=float(now) + float(self.cfg.non_preemptible_grace_s),
                assigned_tags=list(tags),
            )
            self._active[mission_id] = c
            self._active_by_domain.setdefault(domain, []).append(mission_id)

            self._awareness_start_mission(bot, awareness, now=now, c=c)
            awareness.emit(
                "mission_started",
                now=now,
                data={
                    "mission_id": mission_id,
                    "proposal_id": prop.proposal_id,
                    "domain": domain,
                    "tags": len(tags),
                    "ttl": ttl,
                },
            )
            if self.log is not None:
                self.log.emit(
                    "mission_started",
                    {
                        "time": round(now, 2),
                        "mission_id": mission_id,
                        "proposal_id": prop.proposal_id,
                        "domain": domain,
                        "tags": len(tags),
                        "ttl": ttl,
                    },
                )

    async def _execute(self, bot, *, tick: TaskTick, attention: Attention, awareness: Awareness) -> list[dict[str, Any]]:
        now = float(tick.time)
        mission_health = {str(m.mission_id): bool(m.mission_degraded) for m in attention.missions.ongoing}
        task_perf: list[dict[str, Any]] = []

        for mission_id, c in list(self._active.items()):
            if c.is_expired(now):
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason="expired")
                continue

            degraded = bool(mission_health.get(str(c.mission_id), False))
            if degraded:
                self._finish_mission(awareness, now=now, c=c, status="FAILED", reason="mission_degraded")
                continue

            # Global pacing by domain/task to prevent per-frame command spam.
            min_step_interval_s = float(self.cfg.default_task_min_step_interval_s)
            if str(c.domain).startswith("MACRO"):
                min_step_interval_s = max(min_step_interval_s, float(self.cfg.macro_task_min_step_interval_s))
            try:
                task_override = float(getattr(c.task, "min_step_interval_s", 0.0) or 0.0)
            except Exception:
                task_override = 0.0
            min_step_interval_s = max(min_step_interval_s, float(task_override))
            if min_step_interval_s > 0.0:
                last_step_at = awareness.mem.get(
                    K("ops", "mission", c.mission_id, "last_step_at"),
                    now=now,
                    default=None,
                )
                if last_step_at is not None and (float(now) - float(last_step_at)) < min_step_interval_s:
                    continue

            self._touch_leases_for_commitment(now=now, c=c)

            t0 = time.perf_counter()
            res = await c.task.step(bot, tick, attention)
            dt_ms = (time.perf_counter() - t0) * 1000.0
            awareness.mem.set(
                K("ops", "mission", c.mission_id, "last_step_at"),
                value=float(now),
                now=now,
                ttl=120.0,
            )
            if dt_ms >= 2.0:
                task_perf.append(
                    {
                        "mission_id": str(c.mission_id),
                        "domain": str(c.domain),
                        "task_id": str(getattr(c.task, "task_id", type(c.task).__name__)),
                        "ms": round(float(dt_ms), 3),
                        "status": str(getattr(res, "status", "UNKNOWN")),
                    }
                )
            if not isinstance(res, TaskResult):
                raise TypeError(f"Task {type(c.task).__name__} returned non-TaskResult: {type(res)!r}")

            if res.status == "FAILED":
                cooldown = float(res.retry_after_s) if float(res.retry_after_s) > 0 else float(self.cfg.default_failure_cooldown_s)
                self._set_cooldown(awareness, now=now, proposal_id=c.proposal_id, seconds=cooldown, reason=res.reason)
                self._finish_mission(awareness, now=now, c=c, status="FAILED", reason=res.reason)
                continue

            if res.status == "DONE":
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason=res.reason)
                continue

            if self._should_emit_mission_step(awareness, now=now, c=c, status=res.status):
                awareness.emit(
                    "mission_step",
                    now=now,
                    data={"mission_id": c.mission_id, "domain": c.domain, "status": res.status, "reason": res.reason},
                )
        return task_perf

    def _reap_commitments(self, *, now: float, awareness: Awareness) -> None:
        for mission_id, c in list(self._active.items()):
            if c.is_expired(now):
                self._finish_mission(awareness, now=now, c=c, status="DONE", reason="expired")

    def _finish_mission(self, awareness: Awareness, *, now: float, c: Commitment, status: str, reason: str) -> None:
        self.body.release_mission(mission_id=c.mission_id)

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
        if self.log is not None:
            self.log.emit(
                "mission_ended",
                {
                    "time": round(now, 2),
                    "mission_id": c.mission_id,
                    "proposal_id": c.proposal_id,
                    "domain": c.domain,
                    "status": status,
                    "reason": reason,
                },
            )

    def _is_proposal_running(self, proposal_id: str) -> bool:
        return any(c.proposal_id == proposal_id for c in self._active.values())

    def _preempt_domain(self, *, now: float, awareness: Awareness, domain: str, reason: str) -> None:
        mids = list(self._active_by_domain.get(domain, []))
        for mid in mids:
            c = self._active.get(mid)
            if c is None:
                continue
            self._finish_mission(awareness, now=now, c=c, status="DONE", reason=reason)

    def _validate_task(self, task_obj: Any, *, spec: TaskSpec) -> None:
        if not isinstance(task_obj, Task):
            raise TypeError(f"Task factory for {spec.task_id} returned non-Task: {type(task_obj).__name__}")

    def _select_and_claim_units(
        self,
        bot,
        *,
        now: float,
        attention: Attention,
        spec: TaskSpec,
        proposal: Proposal,
        mission_id: str,
        claim_domain: Optional[str] = None,
    ) -> Tuple[bool, List[int], str]:
        reqs: List[UnitRequirement] = list(spec.unit_requirements)
        if not reqs:
            return True, [], ""

        units_ready = attention.economy.units_ready
        selected: List[int] = []

        for req in reqs:
            utype = req.unit_type
            need = int(req.count)
            required = bool(req.required)

            if int(units_ready.get(utype, 0)) <= 0:
                if required:
                    return False, [], f"no_{utype.name.lower()}"
                continue

            # Build candidate unit objects (not tags), so we can score/filter.
            candidates_units: List[Any] = []
            for u in bot.units.of_type(utype).ready:
                tag = int(u.tag)
                if tag in selected:
                    continue
                if self.body.can_claim(tag, now=now):
                    candidates_units.append(u)

            if len(candidates_units) < need and required:
                return False, [], f"insufficient_free_{utype.name.lower()}"
            take_n = min(need, len(candidates_units))
            if take_n <= 0:
                continue

            policy = req.pick_policy
            # Hard filter (allow)
            filtered: List[Any] = []
            for u in candidates_units:
                try:
                    if bool(policy.allow(u, bot=bot, attention=attention, now=now)):
                        filtered.append(u)
                except Exception:
                    # Policy errors are programmer errors; fail fast and loud via cooldown.
                    return False, [], f"pick_policy_allow_error:{policy.name}"
            candidates_units = filtered

            if len(candidates_units) < need and required:
                return False, [], f"insufficient_free_{utype.name.lower()}"
            take_n = min(need, len(candidates_units))
            if take_n <= 0:
                continue

            # Score + deterministic tie-break by tag
            scored: List[Tuple[float, int, Any]] = []
            for u in candidates_units:
                tag = int(u.tag)
                try:
                    s = float(policy.score(u, bot=bot, attention=attention, now=now))
                except Exception:
                    return False, [], f"pick_policy_score_error:{policy.name}"
                scored.append((s, tag, u))

            # Higher score first; on tie, smaller tag first (deterministic)
            scored.sort(key=lambda t: (-t[0], t[1]))
            candidates_units = [u for _s, _tag, u in scored]

            selected.extend([int(u.tag) for u in candidates_units[:take_n]])

        ttl_for_claim = spec.lease_ttl if spec.lease_ttl is not None else proposal.lease_ttl
        if ttl_for_claim is None:
            ttl_for_claim = self.body.default_ttl

        role = self.body._role_for_domain(str(claim_domain or proposal.domain))
        claimed_now: List[int] = []

        for tag in selected:
            ok = self.body.claim(task_id=mission_id, unit_tag=tag, role=role, now=now, ttl=float(ttl_for_claim), force=False)
            if not ok:
                for ct in claimed_now:
                    self.body.release(unit_tag=int(ct))
                return False, [], "claim_failed"
            claimed_now.append(int(tag))

        return True, selected, ""

    def _merge_tags(self, current: List[int], new_tags: List[int]) -> List[int]:
        seen = {int(x) for x in current}
        merged = [int(x) for x in current]
        for tag in new_tags:
            itag = int(tag)
            if itag in seen:
                continue
            seen.add(itag)
            merged.append(itag)
        return merged

    def _touch_leases_for_commitment(self, *, now: float, c: Commitment) -> None:
        if not c.assigned_tags:
            return

        if c.expires_at is None:
            ttl = self.body.default_ttl
        else:
            remaining = float(c.expires_at) - float(now)
            if remaining <= 0.0:
                return
            ttl = max(0.25, min(8.0, remaining))

        for tag in c.assigned_tags:
            self.body.touch(task_id=c.mission_id, unit_tag=int(tag), now=now, ttl=ttl)

    def _is_in_cooldown(self, awareness: Awareness, *, now: float, proposal_id: str) -> bool:
        until = awareness.mem.get(K("ops", "cooldown", proposal_id, "until"), now=now, default=None)
        if until is None:
            return False
        return float(now) < float(until)

    def _set_cooldown(self, awareness: Awareness, *, now: float, proposal_id: str, seconds: float, reason: str) -> None:
        # Always persist reason so downstream intel can react to proposal denials,
        # even when proposal cooldown is configured as zero.
        until = float(now) + max(0.0, float(seconds))
        awareness.mem.set(K("ops", "cooldown", proposal_id, "until"), value=float(until), now=now, ttl=None)
        awareness.mem.set(K("ops", "cooldown", proposal_id, "reason"), value=str(reason), now=now, ttl=None)

    def _awareness_start_mission(self, bot, awareness: Awareness, *, now: float, c: Commitment) -> None:
        original_type_counts: Dict[str, int] = {}
        for tag in c.assigned_tags:
            unit = bot.units.find_by_tag(int(tag))
            if unit is None:
                continue
            name = str(getattr(getattr(unit, "type_id", None), "name", ""))
            if not name:
                continue
            original_type_counts[name] = int(original_type_counts.get(name, 0)) + 1

        awareness.mem.set(K("ops", "mission", c.mission_id, "status"), value="RUNNING", now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "domain"), value=c.domain, now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "proposal_id"), value=c.proposal_id, now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "started_at"), value=float(c.started_at), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "expires_at"), value=c.expires_at, now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "assigned_tags"), value=list(c.assigned_tags), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "original_assigned_tags"), value=list(c.assigned_tags), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", c.mission_id, "original_type_counts"), value=dict(original_type_counts), now=now, ttl=None)

    def _awareness_end_mission(self, awareness: Awareness, *, now: float, mission_id: str, status: str, reason: str) -> None:
        awareness.mem.set(K("ops", "mission", mission_id, "status"), value=str(status), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", mission_id, "reason"), value=str(reason), now=now, ttl=None)
        awareness.mem.set(K("ops", "mission", mission_id, "ended_at"), value=float(now), now=now, ttl=None)

    def _should_emit_mission_step(self, awareness: Awareness, *, now: float, c: Commitment, status: str) -> bool:
        if str(status) != "NOOP":
            return True
        key = K("ops", "mission", c.mission_id, "last_noop_emit_at")
        last = awareness.mem.get(key, now=now, default=None)
        if last is None or (float(now) - float(last)) >= 5.0:
            awareness.mem.set(key, value=float(now), now=now, ttl=None)
            return True
        return False

