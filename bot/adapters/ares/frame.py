from __future__ import annotations

from bot.adapters.ares.depot_toggle import DepotToggle

_depot_toggle = DepotToggle()


def register_baseline_behaviors(bot) -> None:
    """Register stateless Ares behaviors that must run on every frame."""

    if not callable(getattr(bot, "register_behavior", None)):
        return
    from ares.behaviors.macro import Mining

    bot.register_behavior(Mining())
    bot.register_behavior(_depot_toggle)
