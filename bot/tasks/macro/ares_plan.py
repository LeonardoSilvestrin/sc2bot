# bot/tasks/macro/ares_plan.py
from __future__ import annotations

from bot.devlog import DevLogger
from bot.tasks.base_task import TaskTick


def register_macro_plan(bot, plan, *, log: DevLogger | None, tick: TaskTick, label: str, log_every_iters: int = 22) -> None:
    """
    Strict: requires AresBot.register_behavior to exist.
    This helper stays inside tasks layer; planners/ego remain unaware of Ares internals.
    """
    bot.register_behavior(plan)

    if log and (int(tick.iteration) % int(log_every_iters) == 0):
        log.emit(
            "macro_ares_plan",
            {"iter": int(tick.iteration), "t": round(float(tick.time), 2), "label": str(label)},
        )