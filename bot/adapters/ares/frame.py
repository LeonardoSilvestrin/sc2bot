from __future__ import annotations


def register_baseline_behaviors(bot) -> None:
    """Register stateless Ares behaviors that must run on every frame."""

    if not callable(getattr(bot, "register_behavior", None)):
        return
    from ares.behaviors.macro import Mining

    bot.register_behavior(Mining())
