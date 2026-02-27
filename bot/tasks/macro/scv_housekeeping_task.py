# bot/tasks/macro/scv_housekeeping_task.py

# =============================================================================
# bot/tasks/macro/scv_housekeeping_task.py  (MODIFIED: domain)
# =============================================================================
from __future__ import annotations

from dataclasses import dataclass

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class ScvHousekeeping(BaseTask):
    """
    Light-weight SCV housekeeping.

    Policy:
      1) Gas first: keep ideal workers per refinery.
      2) Minerals: keep ~16 mineral workers per base (margin).
      3) Recover idles/orphans: any local idle SCV should be re-assigned quickly.
    """

    awareness: Awareness
    max_reassign_per_run: int = 12
    mineral_balance_margin: int = 0

    # distance gates (avoid retasking scouts / far workers)
    local_worker_max_dist: float = 26.0
    # if worker has no worker_to_th mapping, we allow nearest-base fallback within this distance
    th_fallback_max_dist: float = 30.0

    def __init__(self, *, awareness: Awareness):
        # Global housekeeping task: no unit leases are required.
        super().__init__(task_id="scv_housekeeping", domain="MACRO_HOUSEKEEPING", commitment=0)
        self.awareness = awareness

    def evaluate(self, bot, attention: Attention) -> int:
        return 10

    @staticmethod
    def _assign_worker_to_mineral(worker, mineral_fields) -> None:
        if mineral_fields.amount == 0:
            return
        worker.gather(mineral_fields.closest_to(worker))

    def _reserved_running_tags(self, now: float) -> set[int]:
        """
        Tags currently assigned to RUNNING missions in Ego/Awareness.
        Housekeeping must not retask these workers.
        """
        out: set[int] = set()
        try:
            facts = self.awareness.mem._facts.items()
        except Exception:
            return out

        for k, _f in facts:
            if len(k) < 4:
                continue
            if k[0] != "ops" or k[1] != "mission" or k[-1] != "status":
                continue
            mission_id = k[2]
            st = str(self.awareness.mem.get(K("ops", "mission", mission_id, "status"), now=now, default=""))
            if st != "RUNNING":
                continue
            tags = self.awareness.mem.get(K("ops", "mission", mission_id, "assigned_tags"), now=now, default=[])
            if not isinstance(tags, list):
                continue
            for t in tags:
                try:
                    out.add(int(t))
                except Exception:
                    pass
        return out

    def _collect_candidate_scvs(self, bot, *, reserved_tags: set[int]):
        """
        Candidate SCVs for housekeeping:
        - SCVs in GATHERING role (mediator)
        - PLUS local idle SCVs (bot.units) to recover true idles/orphans
        """
        gathering = bot.mediator.get_units_from_role(role=UnitRole.GATHERING, unit_type=U.SCV)
        all_scvs = bot.units(U.SCV)

        # idle SCVs might not be in GATHERING role; recover them explicitly
        idle = all_scvs.idle

        # unify by tag
        by_tag = {}
        for u in list(gathering) + list(idle):
            try:
                tag = int(u.tag)
            except Exception:
                continue
            if tag in reserved_tags:
                continue
            by_tag[tag] = u
        return list(by_tag.values())

    def _nearest_th(self, worker, townhalls):
        if townhalls.amount == 0:
            return None
        try:
            th = townhalls.closest_to(worker.position)
            if float(worker.distance_to(th.position)) <= float(self.th_fallback_max_dist):
                return th
        except Exception:
            return None
        return None

    def _rebalance_workers(self, bot, *, now: float) -> tuple[int, int, int, int, int]:
        townhalls = bot.townhalls.ready
        if townhalls.amount == 0:
            return 0, 0, 0, 0, 0

        reserved_tags = self._reserved_running_tags(now)
        try:
            bo_scouts = bot.mediator.get_units_from_role(role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=U.SCV)
            reserved_tags.update(int(u.tag) for u in bo_scouts)
        except Exception:
            pass

        worker_to_gas = bot.mediator.get_worker_to_vespene_dict
        worker_to_th = bot.mediator.get_worker_tag_to_townhall_tag

        own_bases = list(townhalls)

        def _is_local_worker(worker) -> bool:
            if not own_bases:
                return True
            try:
                nearest = min(float(worker.distance_to(th.position)) for th in own_bases)
                return nearest <= float(self.local_worker_max_dist)
            except Exception:
                return True

        # candidates = gathering + idle (local), minus reserved
        candidates = self._collect_candidate_scvs(bot, reserved_tags=reserved_tags)

        # filter down to local, non-reserved, non-scout etc.
        local_candidates = [w for w in candidates if _is_local_worker(w)]
        if not local_candidates:
            return 0, 0, 0, 0, len(reserved_tags)

        # classify gas workers using mediator mapping, but keep idle ones too
        def _is_gas_worker(w) -> bool:
            try:
                return int(w.tag) in worker_to_gas
            except Exception:
                return False

        mineral_pool = [w for w in local_candidates if not _is_gas_worker(w)]
        if not mineral_pool:
            return 0, 0, 0, 0, len(reserved_tags)

        # build base_tag mapping with fallback for orphans
        base_tag_by_worker: dict[int, int] = {}
        orphans: list = []
        for w in mineral_pool:
            wtag = int(w.tag)
            th_tag = worker_to_th.get(wtag, None)
            if th_tag is not None and int(th_tag) != -1:
                base_tag_by_worker[wtag] = int(th_tag)
                continue
            th = self._nearest_th(w, townhalls)
            if th is None:
                orphans.append(w)
            else:
                base_tag_by_worker[wtag] = int(th.tag)

        moved_tags: set[int] = set()
        remaining_budget = int(self.max_reassign_per_run)

        # 1) Gas saturation first (pull from mineral pool, prioritizing idle/orphans implicitly by distance)
        gas_deficit = 0
        moved_to_gas = 0
        gas_buildings = [g for g in bot.gas_buildings if g.is_ready]

        for gas in gas_buildings:
            assigned = int(getattr(gas, "assigned_harvesters", 0) or 0)
            ideal = int(getattr(gas, "ideal_harvesters", 0) or 0)
            if ideal <= 0:
                continue
            need = max(0, ideal - assigned)
            gas_deficit += int(need)
            if need <= 0 or remaining_budget <= 0:
                continue

            donors = sorted(
                [w for w in mineral_pool if int(w.tag) not in moved_tags],
                key=lambda w: (0 if w.is_idle else 1, w.distance_to(gas)),
            )
            for w in donors:
                if need <= 0 or remaining_budget <= 0:
                    break
                wtag = int(w.tag)
                w.gather(gas)
                moved_tags.add(wtag)
                moved_to_gas += 1
                remaining_budget -= 1
                need -= 1

        if remaining_budget <= 0:
            return gas_deficit, moved_to_gas, 0, 0, len(reserved_tags)

        # 2) Minerals per base
        margin = int(self.mineral_balance_margin)

        # count current mineral workers per base (excluding already moved)
        per_base_workers: dict[int, list] = {}
        for w in mineral_pool:
            wtag = int(w.tag)
            if wtag in moved_tags:
                continue
            btag = base_tag_by_worker.get(wtag, None)
            if btag is None:
                continue
            per_base_workers.setdefault(int(btag), []).append(w)

        deficits: list[tuple[object, int]] = []
        surplus: list = []
        total_deficit = 0

        for th in townhalls:
            th_tag = int(th.tag)
            ws = per_base_workers.get(th_tag, [])
            count = len(ws)
            desired_for_th = int(getattr(th, "ideal_harvesters", 0) or 16)
            desired_for_th = max(8, desired_for_th)
            if count < (desired_for_th - margin):
                need = desired_for_th - count
                deficits.append((th, need))
                total_deficit += need
            elif count > (desired_for_th + margin):
                # donors: farthest first
                excess = count - desired_for_th
                surplus.extend(sorted(ws, key=lambda w: w.distance_to(th.position), reverse=True)[:excess])

        # IMPORTANT: orphans + true idle should be donated first (they are the ones causing “SCV idle forever”)
        orphan_donors = [w for w in orphans if int(w.tag) not in moved_tags and _is_local_worker(w)]
        idle_donors = [w for w in mineral_pool if w.is_idle and int(w.tag) not in moved_tags]
        donor_pool = []
        # de-dupe by tag
        seen = set()
        for w in orphan_donors + idle_donors + surplus:
            t = int(w.tag)
            if t in seen:
                continue
            seen.add(t)
            donor_pool.append(w)

        if not deficits or not donor_pool:
            # if there are idle/orphans but no deficit, still assign them to nearest base minerals
            reassigned_idle = 0
            for w in orphan_donors + idle_donors:
                if remaining_budget <= 0:
                    break
                th = self._nearest_th(w, townhalls)
                if th is None:
                    continue
                mfs = bot.mineral_field.closer_than(10.0, th.position)
                if mfs.amount == 0:
                    continue
                self._assign_worker_to_mineral(w, mfs)
                remaining_budget -= 1
                reassigned_idle += 1
            return gas_deficit, moved_to_gas, total_deficit, reassigned_idle, len(reserved_tags)

        moved_to_minerals = 0
        moved_idle_or_orphan = 0

        for th, need in deficits:
            if remaining_budget <= 0:
                break
            mfs = bot.mineral_field.closer_than(10.0, th.position)
            if mfs.amount == 0:
                continue

            need_left = int(need)
            donors_sorted = sorted(
                [w for w in donor_pool if int(w.tag) not in moved_tags],
                key=lambda w: w.distance_to(th),
            )
            for w in donors_sorted:
                if need_left <= 0 or remaining_budget <= 0:
                    break
                wtag = int(w.tag)
                was_idle_or_orphan = w.is_idle or (w in orphans)
                self._assign_worker_to_mineral(w, mfs)
                moved_tags.add(wtag)
                moved_to_minerals += 1
                if was_idle_or_orphan:
                    moved_idle_or_orphan += 1
                remaining_budget -= 1
                need_left -= 1

        # Final anti-idle sweep: any remaining local idle mineral worker gets a mineral order.
        recovered_tail = 0
        if remaining_budget > 0:
            for w in local_candidates:
                if remaining_budget <= 0:
                    break
                wtag = int(w.tag)
                if wtag in moved_tags:
                    continue
                if not w.is_idle:
                    continue
                if _is_gas_worker(w):
                    continue
                th = self._nearest_th(w, townhalls)
                if th is None:
                    continue
                mfs = bot.mineral_field.closer_than(10.0, th.position)
                if mfs.amount == 0:
                    continue
                self._assign_worker_to_mineral(w, mfs)
                moved_tags.add(wtag)
                recovered_tail += 1
                remaining_budget -= 1

        return gas_deficit, moved_to_gas, total_deficit, (moved_idle_or_orphan + recovered_tail), len(reserved_tags)

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)

        gas_deficit, moved_to_gas, mineral_deficit, recovered_idle, reserved = self._rebalance_workers(bot, now=now)

        # Mark last done time (planner uses it as interval gate).
        self.awareness.mem.set(K("macro", "scv", "housekeeping", "last_done_at"), value=float(now), now=now, ttl=None)

        self._done("housekeeping_done")
        return TaskResult.done(
            "housekeeping_done",
            telemetry={
                "gas_deficit": int(gas_deficit),
                "moved_to_gas": int(moved_to_gas),
                "mineral_deficit": int(mineral_deficit),
                "recovered_idle": int(recovered_idle),
                "reserved_tags": int(reserved),
            },
        )
