"""The bot. Every frame, in order:

ATTENTION -> AWARENESS -> STRATEGY -> BEHAVIORS -> ENGINE -> LOGS
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

from ares import AresBot
from sc2.data import Result

from bot.attention import AttentionState, MapView, observe, read_map
from bot.awareness import AwarenessModel, AwarenessState
from bot.behaviors import core_army, defense, economy
from bot.engine import EconomyPlan, Engine, EngineResult, Proposal
from bot.logs import Logs
from bot.strategy import StrategyModel, StrategyState

DEFAULT_LATTICE_SPACING = 4


@dataclass(slots=True)
class Layers:
    """What persists from one frame to the next, per layer."""

    map_view: MapView
    logs: Logs
    awareness: AwarenessModel = field(default_factory=AwarenessModel)
    strategy: StrategyModel = field(default_factory=StrategyModel)
    engine: Engine = field(default_factory=Engine)

    def configs(self) -> dict[str, object]:
        return {"awareness": self.awareness.config, "strategy": self.strategy.config}


@dataclass(frozen=True, slots=True)
class Frame:
    attention: AttentionState
    awareness: AwarenessState
    strategy: StrategyState
    proposals: tuple[Proposal, ...]
    economy: EconomyPlan
    result: EngineResult


def play_frame(bot, iteration: int, layers: Layers) -> Frame:
    laps = _Laps()
    attention = observe(bot, iteration, layers.map_view)
    laps.mark("attention")
    awareness = layers.awareness.infer(attention)
    laps.mark("awareness")
    strategy = layers.strategy.decide(attention, awareness)
    laps.mark("strategy")
    proposals = defense.plan(attention, awareness, strategy)
    proposals += core_army.plan(attention, awareness, strategy)
    economy_plan = economy.plan(attention, strategy)
    laps.mark("behaviors")
    result = layers.engine.execute(bot, attention, proposals, economy_plan)
    laps.mark("engine")
    layers.logs.record(
        bot, attention, awareness, strategy, proposals, economy_plan, result, laps.times
    )
    return Frame(attention, awareness, strategy, proposals, economy_plan, result)


class MyBot(AresBot):
    def __init__(
        self,
        game_step_override: int | None = None,
        *,
        logs: Logs | None = None,
        lattice_spacing: int = DEFAULT_LATTICE_SPACING,
    ):
        """
        Parameters
        ----------
        game_step_override :
            If provided, set the game_step to this value regardless of how it was
            specified elsewhere
        logs :
            Where the bot explains itself; silent by default (ladder).
        lattice_spacing :
            Map cells between the points Awareness reasons over.
        """
        super().__init__(game_step_override)
        self.bot_logs = logs or Logs()
        self.lattice_spacing = lattice_spacing
        self.layers: Layers | None = None

    async def on_start(self) -> None:
        await super().on_start()
        map_view = read_map(self, lattice_spacing=self.lattice_spacing)
        self.layers = Layers(map_view=map_view, logs=self.bot_logs)
        self.bot_logs.game_started(self, map_view, self.layers.configs())

    async def on_step(self, iteration: int) -> None:
        await super().on_step(iteration)
        if self.layers is not None:
            play_frame(self, iteration, self.layers)

    async def on_end(self, game_result: Result) -> None:
        await super().on_end(game_result)
        self.bot_logs.game_ended(float(self.time), game_result)


class _Laps:
    def __init__(self) -> None:
        self._last = perf_counter()
        self.times: dict[str, float] = {}

    def mark(self, name: str) -> None:
        now = perf_counter()
        self.times[name] = (now - self._last) * 1000.0
        self._last = now
