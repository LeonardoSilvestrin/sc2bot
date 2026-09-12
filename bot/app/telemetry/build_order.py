from __future__ import annotations

from bot.ports.logging import BotLogger

from .gate import ChangeGate


class BuildOrderTelemetry:
    """Logs each step the Ares build order runner moves on to."""

    def __init__(self, *, logger: BotLogger) -> None:
        self._logger = logger
        self._gate = ChangeGate()

    def report(self, bot, *, game_time: float) -> None:
        runner = getattr(bot, "build_order_runner", None)
        if runner is None:
            return
        step = int(getattr(runner, "build_step", 0))
        build_order = tuple(getattr(runner, "build_order", ()) or ())
        completed = bool(getattr(runner, "build_completed", False))
        opening = str(getattr(runner, "chosen_opening", ""))
        command = None
        if not completed and step < len(build_order):
            command = str(getattr(build_order[step], "command", build_order[step]))
        signature = (opening, step, completed, command)
        if not self._gate.admit(signature, now=game_time):
            return
        self._logger.event(
            "macro.build_order_progress",
            component="app.runtime",
            game_time=game_time,
            data={
                "opening": opening,
                "step": step,
                "total_steps": len(build_order),
                "command": command,
                "completed": completed,
            },
        )
