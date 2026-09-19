"""What Strategy publishes: how the game stands and what the bot wants now.

`GameAssessment` answers *how is the game going?* from what Awareness
believes; `StrategicIntent` answers *what does the bot want to do now?* and is
the one context every planner reads. Neither names a unit, a place or an
operation; how a posture is served is each planner's decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StrategicPosture(str, Enum):
    """The bot's global intent. A posture is not a phase of the game: any of
    them can follow any other, as the assessment moves."""

    # Rebuild after a setback: no new attack, no greed, stay close to home.
    RECOVER = "RECOVER"
    # Home is threatened: answer it before anything else.
    DEFEND = "DEFEND"
    # Nothing special to act on: grow the economy and the army.
    DEVELOP = "DEVELOP"
    # A window to act: stronger or at a power spike, and home is safe.
    PRESSURE = "PRESSURE"
    # A clear advantage against a vulnerable enemy: go for the decision.
    COMMIT = "COMMIT"

    @property
    def offensive(self) -> bool:
        """The postures the offense may open and carry an attack in."""

        return self in (StrategicPosture.PRESSURE, StrategicPosture.COMMIT)


class ThreatBand(str, Enum):
    """A readable name for the threat level; decisions read the level itself."""

    CLEAR = "CLEAR"
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


@dataclass(frozen=True, slots=True)
class GameAssessment:
    """How the game stands, in continuous values.

    Everything about the enemy is an estimate: `confidence` says how much of
    the enemy army estimate rests on sightings rather than on the prior that
    grows with game time.
    """

    time: float
    # The most any base of ours is remembered threatened, in [0, 1].
    threat_level: float
    # Our army against the enemy army planned against (its estimate plus a
    # margin on the part no contact places), in [-1, 1]: 0 is even, +1/3 is
    # twice as strong, -1/3 half as strong.
    army_position: float
    # Our bases against the enemy bases believed (known, never fewer than the
    # prior expects by now), in [-1, 1].
    economy_position: float
    # The share of the enemy army lost recently, in [0, 1).
    enemy_vulnerability: float
    # How much our army is at a peak -- fresh upgrades, supply near the cap --
    # in [0, 1].
    power_spike: float
    # The share of the enemy army estimate backed by sightings, in [0, 1].
    confidence: float
    # The share of our army lost recently, counted in full when it traded
    # evenly or worse and less as it traded better, in [0, 1).
    setback: float
    # The two parts of the power spike.
    upgrade_spike: float
    supply_spike: float
    # The values the assessment was computed from.
    inputs: tuple[tuple[str, float], ...] = ()

    @property
    def army_share(self) -> float:
        """Our share of the power: 1/2 when even."""

        return 0.5 * (1.0 + self.army_position)

    @property
    def threat(self) -> ThreatBand:
        return threat_band(self.threat_level)


# Below this the remembered threat is forgotten (`AwarenessConfig.forget_below`).
_CLEAR_BELOW = 0.05
_LOW_BELOW = 0.3
# The threat Strategy treats as an emergency (`StrategyConfig.emergency_danger`).
_HIGH_FROM = 0.6


def threat_band(level: float) -> ThreatBand:
    if level < _CLEAR_BELOW:
        return ThreatBand.CLEAR
    if level < _LOW_BELOW:
        return ThreatBand.LOW
    if level < _HIGH_FROM:
        return ThreatBand.ELEVATED
    return ThreatBand.HIGH


@dataclass(frozen=True, slots=True)
class PostureGate:
    """One question behind the posture, held with hysteresis: is home
    threatened, is the army set back, is there a decisive advantage, is there
    a window to pressure?"""

    posture: StrategicPosture
    # How strongly the assessment supports the posture, in [0, 1].
    score: float
    # Whether the question is answered yes; held until the complement leads.
    open: bool
    # When it last changed.
    since: float


@dataclass(frozen=True, slots=True)
class StrategicIntent:
    """The common context of every planner: the posture and why, and the
    continuous preferences. Planners translate it into their own domain."""

    time: float
    posture: StrategicPosture
    previous: StrategicPosture | None
    since: float
    # Why the posture was entered: the gate that opened, or the one that closed.
    reason: str
    # The salient values of the change, (name, value), in a stable order.
    because: tuple[tuple[str, float], ...]
    assessment: GameAssessment
    # Latched once DEFEND meets an emergency threat, until DEFEND ends.
    emergency: bool
    # How much defending outranks everything else, in [0, 1].
    defense: float
    # Share of spending wanted in army; economy is the rest.
    army: float
    economy: float
    risk: float
    # Every gate, in precedence order.
    gates: tuple[PostureGate, ...]

    @property
    def army_share(self) -> float:
        return self.assessment.army_share

    @property
    def scores(self) -> tuple[tuple[str, float], ...]:
        return tuple((gate.posture.value, gate.score) for gate in self.gates)

    def summary(self) -> str:
        """One line for a human: ``DEVELOP -> DEFEND: threat=HIGH army_position=-0.18``."""

        before = "START" if self.previous is None else self.previous.value
        values = " ".join(_describe(name, value) for name, value in self.because)
        return f"{before} -> {self.posture.value} ({self.reason}): {values}".rstrip(": ")


_SIGNED = frozenset({"army_position", "economy_position"})


def _describe(name: str, value: float) -> str:
    if name == "threat_level":
        return f"threat={threat_band(value).value} threat_level={value:.2f}"
    if name in _SIGNED:
        return f"{name}={value:+.2f}"
    return f"{name}={value:.2f}"
