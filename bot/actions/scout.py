#bot/actions/scout.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ares.consts import UnitRole
from sc2.position import Point2
from sc2.unit import Unit


@dataclass
class ScoutState:
    dispatched: bool = False
    arrived: bool = False
    scout_tag: Optional[int] = None
    last_seen_log_at: float = 0.0


class ScoutAction:
    name = "scout_main_scv"
    priority = 30
    allow_during_opening = True

    def __init__(self, *, trigger_time: float = 25.0, log_every: float = 6.0, see_radius: float = 14.0):
        self.trigger_time = trigger_time
        self.log_every = log_every
        self.see_radius = see_radius
        self.state = ScoutState()

    def is_done(self) -> bool:
        # Scout “não termina” por enquanto; ele continua reportando até morrer.
        return False

    def _enemy_main(self, bot) -> Point2:
        return bot.enemy_start_locations[0]

    def _get_scout(self, bot) -> Optional[Unit]:
        if self.state.scout_tag is None:
            return None
        return bot.units.find_by_tag(self.state.scout_tag)


    async def step(self, bot, ctx) -> bool:
        target = self._enemy_main(bot)

        # 1) Só dispara após trigger_time
        if not self.state.dispatched:
            if bot.time < self.trigger_time:
                return False

            # pega worker via Ares
            worker: Unit = bot.mediator.select_worker(target_position=target)

            # marca role scout
            bot.mediator.assign_role(tag=worker.tag, role=UnitRole.BUILD_RUNNER_SCOUT, remove_from_squad=True)

            # envia
            worker.move(target)

            self.state.dispatched = True
            self.state.scout_tag = worker.tag

            bot.log.emit(
                "scout_dispatch",
                {
                    "iteration": ctx.iteration,
                    "time": round(bot.time, 2),
                    "scout_tag": worker.tag,
                    "target": [round(target.x, 1), round(target.y, 1)],
                    "trigger_time": self.trigger_time,
                    "opening_done": ctx.opening_done,
                },
            )
            return True  # consumiu budget (emitimos comando)

        # 2) Pós-dispatch: log do que vê
        scout = self._get_scout(bot)
        if scout is None:
            return False

        # arrived 1x
        if not self.state.arrived and scout.distance_to(target) <= 8:
            self.state.arrived = True
            bot.log.emit(
                "scout_arrived",
                {
                    "iteration": ctx.iteration,
                    "time": round(bot.time, 2),
                    "scout_tag": scout.tag,
                    "pos": [round(scout.position.x, 1), round(scout.position.y, 1)],
                },
            )

        # log structures seen periodically
        if (bot.time - self.state.last_seen_log_at) >= self.log_every:
            self.state.last_seen_log_at = bot.time

            seen = bot.enemy_structures.closer_than(self.see_radius, scout.position)
            payload = {
                "iteration": ctx.iteration,
                "time": round(bot.time, 2),
                "scout_tag": scout.tag,
                "scout_pos": [round(scout.position.x, 1), round(scout.position.y, 1)],
                "count": int(seen.amount),
                "types": [s.type_id.name for s in seen],
                "structures": [
                    {"type": s.type_id.name, "pos": [round(s.position.x, 1), round(s.position.y, 1)], "hp": int(s.health)}
                    for s in seen
                ],
            }
            bot.log.emit("scout_seen_structures", payload)

        return False