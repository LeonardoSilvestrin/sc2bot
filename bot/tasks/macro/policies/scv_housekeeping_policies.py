from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class GasFillResult:
    gas_deficit: int
    moved_to_gas: int
    remaining_budget: int


@dataclass
class MineralBalanceResult:
    moved_to_minerals: int
    recovered_idle: int
    remaining_budget: int


@dataclass
class GasFillPolicy:
    mineral_floor: int

    def apply(
        self,
        *,
        bot,
        gas_buildings: list,
        local_candidates: list,
        mineral_pool: list,
        orphans: list,
        per_base_workers: list[list],
        th_list: list,
        moved_tags: set[int],
        remaining_budget: int,
        is_building_or_repairing: Callable[[Any], bool],
    ) -> GasFillResult:
        gas_deficit = 0
        moved_to_gas = 0

        if gas_buildings:
            try:
                bot.mediator.set_workers_per_gas(amount=3)
            except Exception:
                pass

        for ref in gas_buildings:
            assigned = int(getattr(ref, "assigned_harvesters", 0) or 0)
            ideal = int(getattr(ref, "ideal_harvesters", 3) or 3)
            ideal = 3 if ideal <= 0 else ideal
            need = max(0, ideal - assigned)
            gas_deficit += need

            if need <= 0 or remaining_budget <= 0:
                continue

            donors = []
            donors.extend([w for w in mineral_pool if w.is_idle and int(w.tag) not in moved_tags])
            donors.extend([w for w in orphans if int(w.tag) not in moved_tags])

            for bidx, ws in enumerate(per_base_workers):
                if not ws:
                    continue
                if len(ws) > int(self.mineral_floor):
                    donors.extend(sorted(ws, key=lambda w: w.distance_to(th_list[bidx].position), reverse=True))
            if need > 0:
                donors.extend([w for w in mineral_pool if int(w.tag) not in moved_tags])
            if need > 0:
                donors.extend([w for w in local_candidates if int(w.tag) not in moved_tags])

            uniq = []
            seen = set()
            for w in donors:
                t = int(w.tag)
                if t in seen or t in moved_tags:
                    continue
                seen.add(t)
                uniq.append(w)

            for w in uniq:
                if need <= 0 or remaining_budget <= 0:
                    break
                if is_building_or_repairing(w):
                    continue
                wtag = int(w.tag)
                try:
                    bot.mediator.remove_worker_from_mineral(worker_tag=wtag)
                except Exception:
                    pass
                w.gather(ref)
                moved_tags.add(wtag)
                moved_to_gas += 1
                remaining_budget -= 1
                need -= 1

            if need > 0 and remaining_budget > 0:
                fallback = sorted(
                    [w for w in local_candidates if int(w.tag) not in moved_tags],
                    key=lambda w: float(w.distance_to(ref.position)),
                )
                for w in fallback:
                    if need <= 0 or remaining_budget <= 0:
                        break
                    if is_building_or_repairing(w):
                        continue
                    wtag = int(w.tag)
                    try:
                        bot.mediator.remove_worker_from_mineral(worker_tag=wtag)
                    except Exception:
                        pass
                    w.gather(ref)
                    moved_tags.add(wtag)
                    moved_to_gas += 1
                    remaining_budget -= 1
                    need -= 1

        return GasFillResult(
            gas_deficit=int(gas_deficit),
            moved_to_gas=int(moved_to_gas),
            remaining_budget=int(remaining_budget),
        )


@dataclass
class MineralBalancePolicy:
    mineral_floor: int
    mineral_cap: int

    @staticmethod
    def _waterfill_targets(counts: list[int], total_workers: int, floor: int, cap: int) -> list[int]:
        n = len(counts)
        if n <= 0:
            return []
        targets = [0] * n

        remaining = max(0, int(total_workers))
        floor_need = [max(0, floor - 0) for _ in range(n)]
        for i in range(n):
            take = min(remaining, floor_need[i])
            targets[i] += take
            remaining -= take

        for i in range(n):
            need = max(0, cap - targets[i])
            take = min(remaining, need)
            targets[i] += take
            remaining -= take
        return targets

    def apply(
        self,
        *,
        bot,
        townhalls,
        th_list: list,
        per_base_workers: list[list],
        orphans: list,
        mineral_pool: list,
        moved_tags: set[int],
        remaining_budget: int,
        is_local_worker: Callable[[Any, Any], bool],
        nearest_th: Callable[[Any, Any], Any],
        is_building_or_repairing: Callable[[Any], bool],
        assign_worker_to_mineral: Callable[[Any, Any], None],
    ) -> MineralBalanceResult:
        counts = [len(ws) for ws in per_base_workers]
        total_mineral_workers = sum(counts)
        targets = self._waterfill_targets(
            counts=counts,
            total_workers=total_mineral_workers,
            floor=int(self.mineral_floor),
            cap=int(self.mineral_cap),
        )

        deficits: list[tuple[int, int]] = []
        donors: list[tuple[int, object]] = []
        for bidx, ws in enumerate(per_base_workers):
            need = max(0, int(targets[bidx]) - int(len(ws)))
            extra = max(0, int(len(ws)) - int(targets[bidx]))
            if need > 0:
                deficits.append((bidx, need))
            if extra > 0:
                th = th_list[bidx]
                ws_sorted = sorted(ws, key=lambda w: w.distance_to(th.position), reverse=True)
                for w in ws_sorted[:extra]:
                    if int(w.tag) in moved_tags:
                        continue
                    donors.append((bidx, w))

        orphan_donors = [w for w in orphans if int(w.tag) not in moved_tags and is_local_worker(w, townhalls)]
        idle_donors = [w for w in mineral_pool if w.is_idle and int(w.tag) not in moved_tags]

        donor_pool = []
        seen = set()
        for w in orphan_donors + idle_donors + [w for _, w in donors]:
            t = int(w.tag)
            if t in seen or t in moved_tags:
                continue
            if is_building_or_repairing(w):
                continue
            seen.add(t)
            donor_pool.append(w)

        moved_to_minerals = 0
        recovered_idle = 0

        if not deficits:
            for w in idle_donors + orphan_donors:
                if remaining_budget <= 0:
                    break
                if is_building_or_repairing(w):
                    continue
                th = nearest_th(w, townhalls)
                if th is None:
                    continue
                mfs = bot.mineral_field.closer_than(10.0, th.position)
                if mfs.amount == 0:
                    continue
                assign_worker_to_mineral(w, mfs)
                moved_tags.add(int(w.tag))
                recovered_idle += 1
                remaining_budget -= 1
            return MineralBalanceResult(
                moved_to_minerals=int(moved_to_minerals),
                recovered_idle=int(recovered_idle),
                remaining_budget=int(remaining_budget),
            )

        for bidx, need in deficits:
            if remaining_budget <= 0:
                break
            th = th_list[bidx]
            mfs = bot.mineral_field.closer_than(10.0, th.position)
            if mfs.amount == 0:
                continue
            donors_sorted = sorted(
                [w for w in donor_pool if int(w.tag) not in moved_tags],
                key=lambda w: w.distance_to(th.position),
            )
            need_left = int(need)
            for w in donors_sorted:
                if need_left <= 0 or remaining_budget <= 0:
                    break
                if is_building_or_repairing(w):
                    continue
                was_idle_or_orphan = bool(w.is_idle) or (w in orphans)
                assign_worker_to_mineral(w, mfs)
                moved_tags.add(int(w.tag))
                moved_to_minerals += 1
                if was_idle_or_orphan:
                    recovered_idle += 1
                remaining_budget -= 1
                need_left -= 1

        if remaining_budget > 0:
            for w in mineral_pool:
                if remaining_budget <= 0:
                    break
                if not w.is_idle:
                    continue
                if int(w.tag) in moved_tags:
                    continue
                if is_building_or_repairing(w):
                    continue
                th = nearest_th(w, townhalls)
                if th is None:
                    continue
                mfs = bot.mineral_field.closer_than(10.0, th.position)
                if mfs.amount == 0:
                    continue
                assign_worker_to_mineral(w, mfs)
                moved_tags.add(int(w.tag))
                recovered_idle += 1
                remaining_budget -= 1

        return MineralBalanceResult(
            moved_to_minerals=int(moved_to_minerals),
            recovered_idle=int(recovered_idle),
            remaining_budget=int(remaining_budget),
        )

