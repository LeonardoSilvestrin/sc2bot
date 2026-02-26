# bot/tasks/scv_housekeeping_task.py
from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro import Mining
from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult


@dataclass
class ScvHousekeeping(BaseTask):
    """
    Light-weight SCV housekeeping.
    - Planner decides WHEN to run (interval / sensors later).
    - Task decides HOW with assigned SCV(s).
    - Must be safe, fast, and idempotent.

    Policy:
      1) Gas first: keep 3 workers per refinery.
      2) Minerals main: keep up to 16 mineral workers in main.
      3) Overflow: send remaining mineral workers to natural.
    """

    awareness: Awareness

    def __init__(self, *, awareness: Awareness):
        super().__init__(task_id="scv_housekeeping", domain="MACRO", commitment=1)
        self.awareness = awareness

    def evaluate(self, bot, attention: Attention) -> int:
        return 10

    def _pick_main_and_nat(self, bot):
        ready_ths = bot.townhalls.ready
        if ready_ths.amount == 0:
            return None, None

        main = ready_ths.closest_to(bot.start_location)
        if ready_ths.amount < 2:
            return main, None

        nat_pos = bot.mediator.get_own_nat
        nat = ready_ths.closest_to(nat_pos)
        if nat.tag == main.tag:
            return main, None
        return main, nat

    @staticmethod
    def _assign_worker_to_mineral(worker, mineral_fields) -> None:
        if mineral_fields.amount == 0:
            return
        worker.gather(mineral_fields.closest_to(worker))

    def _rebalance_workers(self, bot) -> tuple[int, int]:
        workers = bot.mediator.get_units_from_role(role=UnitRole.GATHERING, unit_type=U.SCV)
        if workers.amount == 0:
            return 0, 0

        main, nat = self._pick_main_and_nat(bot)
        if main is None:
            return 0, 0

        # Let Ares handle gas saturation first.
        bot.register_behavior(Mining(workers_per_gas=3, long_distance_mine=False))

        worker_to_gas = bot.mediator.get_worker_to_vespene_dict
        worker_to_th = bot.mediator.get_worker_tag_to_townhall_tag

        mineral_workers = [w for w in workers if int(w.tag) not in worker_to_gas]

        main_tag = int(main.tag)
        main_mineral_workers = [w for w in mineral_workers if int(worker_to_th.get(int(w.tag), -1)) == main_tag]

        if nat is None:
            return len(main_mineral_workers), 0

        nat_tag = int(nat.tag)
        nat_mineral_workers = [w for w in mineral_workers if int(worker_to_th.get(int(w.tag), -1)) == nat_tag]
        other_mineral_workers = [
            w for w in mineral_workers
            if int(worker_to_th.get(int(w.tag), -1)) not in {main_tag, nat_tag}
        ]

        main_mfs = bot.mineral_field.closer_than(10.0, main.position)
        nat_mfs = bot.mineral_field.closer_than(10.0, nat.position)

        desired_main = 16
        current_main = len(main_mineral_workers)

        moved = 0

        if current_main < desired_main:
            need = desired_main - current_main
            donors = sorted(nat_mineral_workers + other_mineral_workers, key=lambda w: w.distance_to(main))
            for worker in donors[:need]:
                self._assign_worker_to_mineral(worker, main_mfs)
                moved += 1
        elif current_main > desired_main:
            excess = current_main - desired_main
            donors = sorted(main_mineral_workers, key=lambda w: w.distance_to(nat), reverse=True)
            for worker in donors[:excess]:
                self._assign_worker_to_mineral(worker, nat_mfs)
                moved += 1

        return current_main, moved

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        now = float(tick.time)

        if not isinstance(self.mission_id, str) or not self.mission_id:
            return TaskResult.failed("unbound_mission")
        if not isinstance(self.assigned_tags, list):
            return TaskResult.failed("assigned_tags_must_be_list")

        main_mineral_workers, moved = self._rebalance_workers(bot)

        # Mark last done time (planner uses it as interval gate).
        self.awareness.mem.set(K("macro", "scv", "housekeeping", "last_done_at"), value=float(now), now=now, ttl=None)

        self._done("housekeeping_done")
        return TaskResult.done(
            "housekeeping_done",
            telemetry={"main_mineral_workers": int(main_mineral_workers), "moved": int(moved)},
        )
