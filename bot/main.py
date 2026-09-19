"""The bot. The static map is read once, in ``on_start``; then every frame, in order:

ATTENTION -> AWARENESS -> EGO (strategy -> planners and their missions) -> BODY (engine ->
behaviors) -> LOGS

The Engine's result is kept for the next frame: it is the feedback the
missions read about what they were granted. Nothing is planned or allocated
twice in a frame.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random
from time import perf_counter

from ares import AresBot
from sc2.data import Result

from bot.attention import AttentionState, MapView, observe, read_map
from bot.awareness import AwarenessModel, AwarenessState
from bot.body import behaviors
from bot.body.behaviors.attack import MicroReport
from bot.body.behaviors.detection import DetectionReport
from bot.body.behaviors.economy import SpawnMode
from bot.body.engine import Engine, EngineResult
from bot.ego.missions import MissionView
from bot.ego.planners import (
    DetectionPlan,
    EconomyPlan,
    Proposal,
    StructurePlan,
    economy,
)
from bot.ego.planners.control.detection import Detection
from bot.ego.planners.control.structure_control import StructureControl
from bot.ego.planners.economy import styles
from bot.ego.planners.economy.styles import BIO, ArmyStyle
from bot.ego.planners.military.defense import DefensePlanner
from bot.ego.planners.military.intel import IntelPlanner
from bot.ego.planners.military.map_control import MapControlPlan, MapControlPlanner
from bot.ego.planners.military.offense import OffensePlan, OffensePlanner
from bot.ego.strategy import StrategyModel, StrategyState
from bot.logs import Logs

DEFAULT_LATTICE_SPACING = 4


@dataclass(slots=True)
class Layers:
    """What persists from one frame to the next, per layer."""

    map_view: MapView
    logs: Logs
    # Chosen once, in `on_start`.
    army: ArmyStyle = BIO
    awareness: AwarenessModel = field(default_factory=AwarenessModel)
    strategy: StrategyModel = field(default_factory=StrategyModel)
    defense: DefensePlanner = field(default_factory=DefensePlanner)
    map_control: MapControlPlanner = field(default_factory=MapControlPlanner)
    offense: OffensePlanner = field(default_factory=OffensePlanner)
    intel: IntelPlanner = field(default_factory=IntelPlanner)
    structure_control: StructureControl = field(default_factory=StructureControl)
    detection: Detection = field(default_factory=Detection)
    engine: Engine = field(default_factory=Engine)
    # The last allocation, read by the missions on the next frame.
    feedback: EngineResult | None = None

    def configs(self) -> dict[str, object]:
        return {
            "awareness": self.awareness.config,
            "strategy": self.strategy.config,
            "map_control": self.map_control.config,
            "offense": self.offense.config,
            "structure_control": self.structure_control.config,
            "detection": self.detection.config,
            "army": self.army,
        }


@dataclass(frozen=True, slots=True)
class Frame:
    attention: AttentionState
    awareness: AwarenessState
    strategy: StrategyState
    map_control: MapControlPlan
    offense: OffensePlan
    proposals: tuple[Proposal, ...]
    economy: EconomyPlan
    structures: StructurePlan
    result: EngineResult
    spawn: SpawnMode
    micro: MicroReport
    detection: DetectionPlan
    detected: DetectionReport
    # Every mission a planner governed this frame, as it left the frame.
    missions: tuple[MissionView, ...] = ()


def play_frame(bot, iteration: int, layers: Layers) -> Frame:
    laps = _Laps()
    attention = observe(bot, iteration, layers.map_view)
    laps.mark("attention")
    awareness = layers.awareness.infer(attention)
    laps.mark("awareness")
    strategy = layers.strategy.decide(attention, awareness)
    laps.mark("strategy")
    proposals = layers.defense.plan(attention, awareness, strategy, layers.feedback)
    map_control = layers.map_control.plan(attention, awareness, strategy)
    proposals += map_control.proposals
    # The offense assembles and falls back where MapControl holds the army.
    offense = layers.offense.plan(
        attention, awareness, strategy, map_control.anchor, layers.feedback
    )
    proposals += offense.proposals
    proposals += layers.intel.plan(attention, layers.feedback)
    missions = layers.defense.views() + layers.offense.views() + layers.intel.views()
    economy_plan = economy.plan(
        attention, strategy, layers.army, awareness.seen_enemy_types
    )
    structures = layers.structure_control.plan(attention)
    detection = layers.detection.plan(attention, awareness)
    laps.mark("planners")
    result = layers.engine.allocate(attention, proposals)
    layers.feedback = result
    laps.mark("engine")
    body = behaviors.execute(bot, attention, result, economy_plan, structures, detection)
    laps.mark("behaviors")
    layers.logs.record(
        bot,
        attention,
        awareness,
        strategy,
        map_control,
        offense,
        proposals,
        economy_plan,
        structures,
        result,
        body.spawn,
        body.micro,
        laps.times,
        detection=detection,
        detected=body.detection,
        missions=missions,
    )
    return Frame(
        attention,
        awareness,
        strategy,
        map_control,
        offense,
        proposals,
        economy_plan,
        structures,
        result,
        body.spawn,
        body.micro,
        detection,
        body.detection,
        missions,
    )


class MyBot(AresBot):
    def __init__(
        self,
        game_step_override: int | None = None,
        *,
        logs: Logs | None = None,
        lattice_spacing: int = DEFAULT_LATTICE_SPACING,
        army: str | None = None,
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
        army :
            The army style to play, by name; None draws one for the enemy's race.
        """
        super().__init__(game_step_override)
        self.bot_logs = logs or Logs()
        self.lattice_spacing = lattice_spacing
        self.army = army
        self.layers: Layers | None = None

    async def on_start(self) -> None:
        await super().on_start()
        map_view = read_map(self, lattice_spacing=self.lattice_spacing)
        army = styles.choose(self.enemy_race, Random(), forced=self.army)
        # Nothing of the opening has been played yet.
        self.build_order_runner.switch_opening(army.opening, remove_completed=False)
        self.layers = Layers(map_view=map_view, logs=self.bot_logs, army=army)
        self.bot_logs.game_started(self, map_view, self.layers.configs())
        await self.chat_send(styles.announcement(army))

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
