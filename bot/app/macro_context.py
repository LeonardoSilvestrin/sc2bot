"""Runtime for macro's own policy: derive the context, log it, hand it over."""

from __future__ import annotations

from dataclasses import dataclass, field

from bot.macro import MacroContext, MacroPosture, MacroPostureDirector
from bot.ports.logging import BotLogger
from bot.world.awareness import AwarenessSnapshot, RelativePosition

COMPONENT = "macro.posture"


@dataclass(slots=True)
class MacroContextRuntime:
    """Derive the frame's ``MacroContext`` from Awareness and log changes.

    Macro policy reaches ``MacroPlanner`` only through the context this
    returns -- never through Awareness. ``macro.posture`` is written whenever
    the posture changes, with the director's reason and the Awareness readings
    it decided from.
    """

    logger: BotLogger
    director: MacroPostureDirector = field(default_factory=MacroPostureDirector)
    _logged: MacroPosture | None = field(default=None, init=False, repr=False)

    def update(self, awareness: AwarenessSnapshot) -> MacroContext:
        workers = awareness.economy.own_workers
        townhalls = awareness.economy.own_bases
        own_combat = awareness.relative_strength.own_combat_units
        stably_ahead = awareness.army.relative.stable_state is RelativePosition.AHEAD
        nearby = awareness.threat.near_own_base_enemy_combat_units
        posture = self.director.update(
            now=awareness.updated_at,
            workers=workers,
            townhalls=townhalls,
            own_combat=own_combat,
            strength_is_stably_ahead=stably_ahead,
            nearby_enemy_combat=nearby,
        )
        if posture is not self._logged:
            self.logger.event(
                "macro.posture",
                component=COMPONENT,
                game_time=awareness.updated_at,
                data={
                    "posture": posture.name,
                    "previous_posture": (
                        None if self._logged is None else self._logged.name
                    ),
                    "reason": self.director.state.reason,
                    "inputs": {
                        "workers": workers,
                        "townhalls": townhalls,
                        "own_combat_units": own_combat,
                        "army_stably_ahead": stably_ahead,
                        "near_own_base_enemy_combat_units": nearby,
                    },
                },
            )
            self._logged = posture
        return MacroContext(posture=posture)


__all__ = ["COMPONENT", "MacroContextRuntime"]
