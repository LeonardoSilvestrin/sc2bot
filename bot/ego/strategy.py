"""STRATEGY: what the bot is trying to achieve now, and how hard.

`StrategyModel.decide` turns Awareness into one `StrategyState`: an objective
held with hysteresis, continuous preferences that the planners read directly,
and the policy each domain with operations of its own must follow -- whether
it may pursue them, or must withdraw so defending comes first. Strategy
publishes that policy and nothing more: it knows no mission, and the planner
of the domain decides which of its operations end and how. Strategy commands
no unit and names no place on the map: where the army stands is MapControl's.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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


class Posture(str, Enum):
    # Open new operations and carry on with those running.
    PURSUE = "PURSUE"
    # Open none, and wind down those running.
    WITHDRAW = "WITHDRAW"


class EconomyPosture(str, Enum):
    """How aggressively the economy may invest beyond immediate army."""

    INVEST = "INVEST"
    ARMY_FIRST = "ARMY_FIRST"
    SURVIVE = "SURVIVE"


@dataclass(frozen=True, slots=True)
class DomainPolicy:
    """What Strategy allows one domain's operations."""

    posture: Posture
    reason: str


@dataclass(frozen=True, slots=True)
class EconomyPolicy:
    posture: EconomyPosture
    reason: str


# While stabilizing, the army defends: no attack starts, and a running one
# gives its units back.
_OFFENSE = {
    Objective.STABILIZE: DomainPolicy(Posture.WITHDRAW, "home_threatened"),
    Objective.BUILD_ADVANTAGE: DomainPolicy(Posture.PURSUE, "home_secure"),
}


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    # A challenger must lead the objective in force by this much ...
    switch_margin: float = 0.1
    # ... after it was held this long; STABILIZE skips the dwell at this danger.
    minimum_dwell: float = 8.0
    emergency_danger: float = 0.6
    # The enemy army planned against is its estimate plus this share of the
    # part no contact places.
    commit_margin: float = 0.5

    def __post_init__(self) -> None:
        if not 0.0 <= self.switch_margin < 1.0:
            raise ValueError("switch_margin must be in [0, 1)")
        if min(self.minimum_dwell, self.commit_margin) < 0.0:
            raise ValueError("minimum_dwell and commit_margin must not be negative")


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
    # Our army's share of it and the enemy army planned against: 1/2 when even.
    army_share: float
    inputs: tuple[tuple[str, float], ...]
    scores: tuple[tuple[str, float], ...]
    # The policy of the offense's operations.
    offense: DomainPolicy
    # Investment, army first, or the emergency fallback. SURVIVE is latched
    # until the objective leaves STABILIZE.
    economy_policy: EconomyPolicy


class StrategyModel:
    def __init__(self, config: StrategyConfig | None = None) -> None:
        self.config = config or StrategyConfig()
        self._objective: Objective | None = None
        self._previous: Objective | None = None
        self._since = 0.0
        self._reason = ""
        self._survival = False

    def decide(self, attention: AttentionState, awareness: AwarenessState) -> StrategyState:
        now = attention.time
        danger = awareness.danger
        # The fog is no advantage: the army no contact places still counts, with a margin.
        planned_enemy = (
            awareness.estimated_enemy_power
            + self.config.commit_margin * awareness.enemy_uncertainty
        )
        total_power = awareness.own_power + planned_enemy
        army_share = awareness.own_power / total_power if total_power > 0.0 else 0.5
        scores = {Objective.STABILIZE: danger, Objective.BUILD_ADVANTAGE: 1.0 - danger}
        self._select(scores, danger, now)
        objective = self._objective
        assert objective is not None
        if objective is not Objective.STABILIZE:
            self._survival = False
        elif danger >= self.config.emergency_danger:
            self._survival = True
        if self._survival:
            economy_policy = EconomyPolicy(EconomyPosture.SURVIVE, "emergency_threat")
        elif objective is Objective.STABILIZE:
            economy_policy = EconomyPolicy(EconomyPosture.ARMY_FIRST, "home_threatened")
        else:
            economy_policy = EconomyPolicy(EconomyPosture.INVEST, "home_secure")
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
            army_share=army_share,
            inputs=(
                ("danger", danger),
                ("danger_now", awareness.danger_now),
                ("army_share", army_share),
                ("own_power", awareness.own_power),
                ("enemy_power", awareness.enemy_power),
                ("estimated_enemy_power", awareness.estimated_enemy_power),
                ("enemy_uncertainty", awareness.enemy_uncertainty),
                ("planned_enemy_power", planned_enemy),
            ),
            scores=tuple((item.value, scores[item]) for item in Objective),
            offense=_OFFENSE[objective],
            economy_policy=economy_policy,
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


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))
