"""STRATEGY: what the bot is trying to achieve now, and how hard.

`StrategyModel.decide` turns Awareness into one `StrategyState`: an objective
held with hysteresis, plus continuous preferences that the planners read
directly. Strategy commands no unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sc2.position import Point2

from bot.attention import AttentionState
from bot.awareness import AwarenessState

# Absorbs float noise so a challenger exactly `switch_margin` ahead counts.
_TOLERANCE = 1e-9


class Objective(str, Enum):
    STABILIZE = "STABILIZE"
    BUILD_ADVANTAGE = "BUILD_ADVANTAGE"


_REASONS = {
    Objective.STABILIZE: "base_under_threat",
    Objective.BUILD_ADVANTAGE: "no_immediate_threat",
}


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    # A challenger must lead the objective in force by this much ...
    switch_margin: float = 0.1
    # ... after it was held this long; STABILIZE skips the dwell at this danger.
    minimum_dwell: float = 8.0
    emergency_danger: float = 0.6
    # How far in front of the forward base the army holds.
    rally_forward: float = 6.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.switch_margin < 1.0:
            raise ValueError("switch_margin must be in [0, 1)")
        if self.minimum_dwell < 0.0 or self.rally_forward < 0.0:
            raise ValueError("minimum_dwell and rally_forward must not be negative")


@dataclass(frozen=True, slots=True)
class StrategyState:
    time: float
    objective: Objective
    previous: Objective | None
    since: float
    reason: str
    # How much defending outranks everything else, in [0, 1].
    defense: float
    # Share of spending wanted in army; economy is the rest.
    army: float
    economy: float
    risk: float
    rally: Point2
    inputs: tuple[tuple[str, float], ...]
    scores: tuple[tuple[str, float], ...]


class StrategyModel:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()
        self._objective: Objective | None = None
        self._previous: Objective | None = None
        self._since = 0.0
        self._reason = ""

    def decide(self, attention: AttentionState, awareness: AwarenessState) -> StrategyState:
        now = attention.time
        danger = awareness.danger
        total_power = awareness.own_power + awareness.enemy_power
        army_share = awareness.own_power / total_power if total_power > 0.0 else 0.5
        scores = {Objective.STABILIZE: danger, Objective.BUILD_ADVANTAGE: 1.0 - danger}
        self._select(scores, danger, now)
        objective = self._objective
        assert objective is not None
        army = _unit(0.3 + 0.5 * danger + 0.4 * (0.5 - army_share))
        return StrategyState(
            time=now,
            objective=objective,
            previous=self._previous,
            since=self._since,
            reason=self._reason,
            defense=danger,
            army=army,
            economy=1.0 - army,
            risk=army_share * (1.0 - danger),
            rally=self._rally(attention, awareness, objective),
            inputs=(
                ("danger", danger),
                ("army_share", army_share),
                ("own_power", awareness.own_power),
                ("enemy_power", awareness.enemy_power),
            ),
            scores=tuple((item.value, scores[item]) for item in Objective),
        )

    def _select(self, scores: dict[Objective, float], danger: float, now: float) -> None:
        if self._objective is None:
            # A tie keeps the conservative objective.
            self._objective = max(
                Objective, key=lambda item: (scores[item], item is Objective.STABILIZE)
            )
            self._since = now
            self._reason = _REASONS[self._objective]
            return
        current = self._objective
        challenger = next(item for item in Objective if item is not current)
        if scores[challenger] - scores[current] < self.config.switch_margin - _TOLERANCE:
            return
        dwelled = now - self._since >= self.config.minimum_dwell
        emergency = challenger is Objective.STABILIZE and danger >= self.config.emergency_danger
        if not (dwelled or emergency):
            return
        self._previous, self._objective, self._since = current, challenger, now
        self._reason = "emergency_threat" if not dwelled else _REASONS[challenger]

    def _rally(
        self, attention: AttentionState, awareness: AwarenessState, objective: Objective
    ) -> Point2:
        threatened = awareness.most_threatened
        if objective is Objective.STABILIZE and threatened is not None:
            return threatened.position
        map_view = attention.map
        front = max(
            attention.bases,
            key=lambda base: (base.position.distance_to(map_view.own_start), base.base_id),
            default=None,
        )
        if front is None or front.is_main:
            return map_view.main_ramp
        if front.position.distance_to(map_view.enemy_start) <= self.config.rally_forward:
            return front.position
        return front.position.towards(map_view.enemy_start, self.config.rally_forward)


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))
