# bot/planners/intel_planner.py
from __future__ import annotations

from dataclasses import dataclass
from pickle import FALSE
from typing import Optional, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.proposals import Proposal, TaskSpec, UnitRequirement
from bot.tasks.scan_task import ScanAt
from bot.tasks.scout_task import Scout
from bot.tasks.reaper_scout_task import ReaperScout, ReaperScoutObjective


@dataclass
class IntelPlanner:
    planner_id: str = "intel_planner"

    awareness: Awareness = None  # injected
    log: DevLogger | None = None

    # SCV re-scout (optional; early SCV scout is YAML now)
    scout_task: Scout | None = None
    scout_min_dispatch_interval_s: float = 75.0
    scout_lease_ttl_s: float = 120.0

    # Reaper scout
    reaper_scout_interval_early_s: float = 35.0
    reaper_scout_interval_mid_s: float = 70.0
    reaper_scout_lease_ttl_s: float = 90.0

    confidence_min: float = 0.70
    confidence_rescout_below: float = 0.65

    def _pid_scv_rescout(self) -> str:
        return f"{self.planner_id}:scout:scv_rescout"

    def _pid_reaper_scout(self) -> str:
        return f"{self.planner_id}:scout:reaper"

    def _pid_scan(self, label: str) -> str:
        return f"{self.planner_id}:scan:{label}"

    def _enemy_main(self, bot) -> Point2:
        return bot.enemy_start_locations[0]

    def _opening_state(self, *, awareness: Awareness, now: float) -> Tuple[Optional[str], float, float, Optional[float], dict]:
        first_seen_t = awareness.mem.get(K("enemy", "opening", "first_seen_t"), now=now, default=None)
        last_update_t = awareness.mem.get(K("enemy", "opening", "last_update_t"), now=now, default=None)

        kind = awareness.mem.get(K("enemy", "opening", "kind"), now=now, default=None)
        conf = awareness.mem.get(K("enemy", "opening", "confidence"), now=now, default=0.0)
        signals = awareness.mem.get(K("enemy", "opening", "signals"), now=now, default={}) or {}

        try:
            conf_f = float(conf)
        except Exception:
            conf_f = 0.0

        age_s = 9999.0
        if last_update_t is not None:
            try:
                age_s = max(0.0, float(now) - float(last_update_t))
            except Exception:
                age_s = 9999.0

        kind_s = str(kind) if kind is not None else None
        fst = float(first_seen_t) if first_seen_t is not None else None
        return kind_s, conf_f, float(age_s), fst, dict(signals)

    def _reaper_objective(self, *, kind: Optional[str], conf: float, signals: dict, now: float) -> ReaperScoutObjective:
        """
        Pick ONE discriminative objective.
        Keep it simple; we can add proxy sweeps later.
        """
        nat_on_ground = bool(signals.get("natural_on_ground", False))
        if float(now) <= 210.0 and not nat_on_ground:
            return ReaperScoutObjective.CONFIRM_NATURAL
        if kind == "AGGRESSIVE" and conf >= 0.70:
            # in aggressive case, just peek main/ramp quickly
            return ReaperScoutObjective.CONFIRM_MAIN_RAMP
        return ReaperScoutObjective.CONFIRM_NATURAL

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        proposals: list[Proposal] = []

        if self.awareness is None:
            raise TypeError("IntelPlanner requires awareness injected")

        # -------------------------
        # 0) SCV re-scout (optional)
        # -------------------------
        if False and (self.scout_task is not None):
            pid = self._pid_scv_rescout()
            # never donate SCV under pressure
            if not bool(attention.combat.threatened):
                kind, conf, age_s, first_seen_t, signals = self._opening_state(awareness=awareness, now=now)

                need_scv = False
                if first_seen_t is None and now >= 75.0:
                    need_scv = True
                elif kind is None and now >= 75.0:
                    need_scv = True
                elif conf < float(self.confidence_rescout_below) and now >= 75.0:
                    need_scv = True

                if need_scv:
                    last_dispatch = awareness.intel_last_scv_dispatch_at(now=now)
                    if last_dispatch <= 0.0 or (now - float(last_dispatch)) >= float(self.scout_min_dispatch_interval_s):
                        if not awareness.ops_proposal_running(proposal_id=pid, now=now):

                            def _scv_factory(mission_id: str) -> Scout:
                                return self.scout_task.spawn()

                            proposals.append(
                                Proposal(
                                    proposal_id=pid,
                                    domain="INTEL",
                                    score=33,
                                    tasks=[
                                        TaskSpec(
                                            task_id="scout_scv",
                                            task_factory=_scv_factory,
                                            unit_requirements=[UnitRequirement(unit_type=U.SCV, count=1)],
                                        )
                                    ],
                                    lease_ttl=float(self.scout_lease_ttl_s),
                                    cooldown_s=8.0,
                                    risk_level=1,
                                    allow_preempt=True,
                                )
                            )

        # -------------------------
        # 1) Reaper scout controller
        # -------------------------
        # Only if we have a reaper ready
        reapers_ready = int(attention.economy.units_ready.get(U.REAPER, 0) or 0)
        if reapers_ready >= 1:
            pid = self._pid_reaper_scout()

            # don't send reaper scout if home is on fire
            if not bool(attention.combat.threatened):
                kind, conf, age_s, first_seen_t, signals = self._opening_state(awareness=awareness, now=now)

                # staleness window: tighter early, looser mid
                refresh = float(self.reaper_scout_interval_early_s) if now <= 240.0 else float(self.reaper_scout_interval_mid_s)

                need_reaper = False
                if first_seen_t is None and now >= 75.0:
                    need_reaper = True
                elif kind is None and now >= 75.0:
                    need_reaper = True
                elif conf < float(self.confidence_min):
                    need_reaper = True
                elif age_s >= refresh:
                    need_reaper = True

                # anti-spam using awareness timestamp
                last_rep = awareness.intel_last_reaper_scout_dispatch_at(now=now)
                if need_reaper and (last_rep <= 0.0 or (now - float(last_rep)) >= refresh):
                    if not awareness.ops_proposal_running(proposal_id=pid, now=now):
                        obj = self._reaper_objective(kind=kind, conf=conf, signals=signals, now=now)

                        def _reaper_factory(mission_id: str) -> ReaperScout:
                            return ReaperScout(awareness=awareness, log=self.log, objective=obj)

                        proposals.append(
                            Proposal(
                                proposal_id=pid,
                                domain="INTEL",
                                score=52 if conf < 0.65 else 42,
                                tasks=[
                                    TaskSpec(
                                        task_id="reaper_scout",
                                        task_factory=_reaper_factory,
                                        unit_requirements=[UnitRequirement(unit_type=U.REAPER, count=1)],
                                    )
                                ],
                                lease_ttl=float(self.reaper_scout_lease_ttl_s),
                                cooldown_s=6.0,
                                risk_level=1,
                                allow_preempt=True,
                            )
                        )

                        if self.log:
                            self.log.emit(
                                "intel_reaper_scout_proposed",
                                {
                                    "t": round(float(now), 2),
                                    "proposal_id": pid,
                                    "objective": str(obj.value),
                                    "kind": str(kind),
                                    "confidence": float(conf),
                                    "age_s": float(age_s),
                                },
                                meta={"module": "planner", "component": f"planner.{self.planner_id}"},
                            )

        # -------------------------
        # 2) Scan when threatened and orbital ready
        # -------------------------
        if bool(attention.combat.threatened) and bool(attention.intel.orbital_ready_to_scan):
            target = self._enemy_main(bot)
            label = "enemy_main"

            def _scan_factory(mission_id: str) -> ScanAt:
                return ScanAt(awareness=awareness, target=target, label=label, cooldown=20.0, log=self.log)

            proposals.append(
                Proposal(
                    proposal_id=self._pid_scan(label),
                    domain="INTEL",
                    score=55,
                    tasks=[TaskSpec(task_id="scan_at", task_factory=_scan_factory, unit_requirements=[])],
                    lease_ttl=5.0,
                    cooldown_s=20.0,
                    risk_level=1,
                    allow_preempt=True,
                )
            )

        return proposals
