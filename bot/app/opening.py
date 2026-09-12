"""Which opening this game plays.

`terran_builds.yml` sets `UseData: false` (ladder-safe: never persist
opponent history to disk), which makes Ares' own build-selection cycle
always resolve to `Cycle[0]` -- see `DataManager.initialise`. That pinned
every game to `BioThreeOneOne` and the `BansheeCloak` opener never ran.
`OpeningSelector` re-picks from that same cycle ourselves so every
configured opening actually gets played.
"""

from __future__ import annotations

import random

from ares.consts import BUILD_CHOICES, CYCLE, DEBUG, TEST_OPPONENT_ID

_OPENING_ANNOUNCEMENTS: dict[str, str] = {
    "BioThreeOneOne": "Reaper expand into Bio 3-1-1.",
    "BansheeCloak": "Reaper expand into cloaked Banshee harass.",
    "BattleMech": "",
}


class OpeningSelector:
    """Picks this game's opening from the configured cycle and declares it in
    game chat."""

    def __init__(self, *, rng: random.Random) -> None:
        self._rng = rng

    async def choose_and_announce(self, bot) -> None:
        """Ares' `chosen_opening` is already set by the time `on_start` runs,
        but with `UseData: false` it is always `Cycle[0]` (see the module
        docstring). We re-roll from the same configured cycle here, before the
        build runner has taken a single step, so switching is free.
        """

        runner = getattr(bot, "build_order_runner", None)
        if runner is None:
            return
        choices = self._opening_choices(bot, runner)
        if choices:
            switch_opening = getattr(runner, "switch_opening", None)
            if callable(switch_opening):
                switch_opening(self._rng.choice(choices))
        opening = str(getattr(runner, "chosen_opening", "") or "")
        if not opening:
            return
        chat_send = getattr(bot, "chat_send", None)
        if callable(chat_send):
            description = _OPENING_ANNOUNCEMENTS.get(opening)
            message = f"[Build] {opening}"
            if description:
                message += f" - {description}"
            await chat_send(message)

    @staticmethod
    def _opening_choices(bot, runner) -> tuple[str, ...]:
        config = getattr(runner, "config", None)
        if not isinstance(config, dict):
            return ()
        build_choices = config.get(BUILD_CHOICES)
        if not build_choices:
            return ()
        opponent_id = (
            TEST_OPPONENT_ID
            if config.get(DEBUG)
            else getattr(bot, "opponent_id", None)
        )
        key = opponent_id if opponent_id in build_choices else None
        if key is None:
            race_name = getattr(getattr(bot, "enemy_race", None), "name", None)
            key = race_name if race_name in build_choices else None
        if key is None:
            return ()
        return tuple(build_choices[key].get(CYCLE, ()) or ())
