# bot/sensors/macro_sensor.py
from __future__ import annotations

from bot.mind.attention import MacroSnapshot


def _opening_done(bot) -> bool:
    """
    Opening state estimation.
    Rule: no side-effects.

    Strict mode:
      - Opening ends only when Ares BuildRunner reports build_completed.
    """
    bor = getattr(bot, "build_order_runner", None)
    if bor is None:
        # bootstrap guard: runner not ready yet this tick
        return False
    if not hasattr(bor, "build_completed"):
        raise AttributeError("Macro sensor requires build_order_runner.build_completed")

    return bool(bor.build_completed)


def derive_macro_snapshot(bot) -> MacroSnapshot:
    return MacroSnapshot(opening_done=bool(_opening_done(bot)))
