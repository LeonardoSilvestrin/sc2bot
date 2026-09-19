"""STRATEGY: from the assessment to the one intent every planner reads.

Strategy owns no operation, names no place and issues no game command; each
planner decides what a posture means in its own domain. See the normative
roles in docs/architecture.md.

The posture is the answer to four questions, asked in this order; the first
answered yes wins, and DEVELOP is what is left:

- DEFEND: is home threatened? `threat_level`.
- RECOVER: was the army set back, or is it badly outmatched?
  1 - (1 - setback)(1 - confidence * max(0, -army_position)): the losses we
  saw, or a deficit as far as the enemy army is backed by sightings.
- COMMIT: is there a decisive advantage?
  safety * sqrt(max(0, army_position) * enemy_vulnerability): clearly
  stronger, and the enemy just lost its army.
- PRESSURE: is there a window to act?
  safety * max(army_share, min(1, 2 * army_share) * power_spike): stronger,
  or at a power spike -- which counts in full from an even army down to
  nothing as the army share falls to zero.

`safety` is 1 - threat_level. Each question is a gate held with hysteresis,
the rule the old binary objective used: its score s is compared with its
complement 1 - s, and the gate flips only once the other side leads by
`switch_margin` (s >= 0.55 to open, s <= 0.45 to close by default). DEFEND
also waits `minimum_dwell` seconds before it flips, except that it opens at
once at `emergency_danger`. On the first frame a tie opens the conservative
gates (DEFEND, RECOVER) and not the others.

The posture itself persists: it never goes back to the posture it replaced
before it was held `stance_dwell` seconds, so a score moving across a band
cannot make it ping-pong. Moving on to a third posture is not held back --
PRESSURE may escalate to COMMIT while the window is open -- and DEFEND is
exempt both ways: home is answered at once, and DEFEND ends by its own gate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bot.attention import AttentionState
from bot.awareness import AwarenessState

from .assessment import AssessmentConfig, AssessmentModel
from .model import GameAssessment, PostureGate, StrategicIntent, StrategicPosture

# Absorbs float noise so a challenger exactly `switch_margin` ahead counts.
_TOLERANCE = 1e-9

DEFEND = StrategicPosture.DEFEND
RECOVER = StrategicPosture.RECOVER
DEVELOP = StrategicPosture.DEVELOP
PRESSURE = StrategicPosture.PRESSURE
COMMIT = StrategicPosture.COMMIT
# The gates, in precedence order.
_ORDER = (DEFEND, RECOVER, COMMIT, PRESSURE)
_CONSERVATIVE = frozenset({DEFEND, RECOVER})
# What explains a posture, in the order it is written.
_SALIENT = {
    DEFEND: ("threat_level", "army_position"),
    RECOVER: ("setback", "army_position", "confidence"),
    DEVELOP: ("threat_level", "army_position", "power_spike"),
    PRESSURE: ("threat_level", "power_spike", "army_position"),
    COMMIT: ("threat_level", "army_position", "enemy_vulnerability"),
}
_WRITTEN = (
    "threat_level",
    "setback",
    "power_spike",
    "army_position",
    "enemy_vulnerability",
    "confidence",
)
# DEVELOP is entered when every question is answered no: why depends on what it left.
_DEVELOP_REASONS = {
    None: "no_opportunity",
    DEFEND: "threat_cleared",
    RECOVER: "recovered",
    PRESSURE: "window_closed",
    COMMIT: "window_closed",
}


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    # A gate flips once the other side leads it by this much in score ...
    switch_margin: float = 0.1
    # ... and DEFEND once it was held this long, but opens without the dwell
    # at this threat.
    minimum_dwell: float = 8.0
    emergency_danger: float = 0.6
    # A posture is held this long before the one it replaced may come back.
    stance_dwell: float = 15.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.switch_margin < 1.0:
            raise ValueError("switch_margin must be in [0, 1)")
        if min(self.minimum_dwell, self.stance_dwell) < 0.0:
            raise ValueError("minimum_dwell and stance_dwell must not be negative")


@dataclass(slots=True)
class _Gate:
    posture: StrategicPosture
    dwell: float
    open: bool | None = None
    since: float = 0.0

    def update(self, score: float, now: float, margin: float, *, urgent: bool = False) -> bool:
        """Flips the gate if the other side leads by `margin` after the dwell,
        or at once when opening is `urgent`; True when it flipped without the
        dwell."""

        if self.open is None:
            conservative = self.posture in _CONSERVATIVE
            self.open = score > 0.5 or (conservative and score >= 0.5)
            self.since = now
            return False
        # The challenger's score minus the incumbent's.
        lead = 1.0 - 2.0 * score if self.open else 2.0 * score - 1.0
        if lead < margin - _TOLERANCE:
            return False
        dwelled = now - self.since >= self.dwell
        if not (dwelled or (urgent and not self.open)):
            return False
        self.open, self.since = not self.open, now
        return not dwelled


class StrategyModel:
    def __init__(
        self,
        config: StrategyConfig | None = None,
        assessment: AssessmentConfig | None = None,
    ) -> None:
        self.config = config or StrategyConfig()
        self.assessment = AssessmentModel(assessment)
        # Only DEFEND's gate dwells; the posture holds the rest.
        self._gates = {
            posture: _Gate(posture, self.config.minimum_dwell if posture is DEFEND else 0.0)
            for posture in _ORDER
        }
        self._posture: StrategicPosture | None = None
        self._previous: StrategicPosture | None = None
        self._since = 0.0
        self._reason = ""
        self._because: tuple[tuple[str, float], ...] = ()
        self._emergency = False

    def decide(self, attention: AttentionState, awareness: AwarenessState) -> StrategicIntent:
        config = self.config
        now = attention.time
        assessment = self.assessment.assess(attention, awareness)
        danger = assessment.threat_level
        scores = gate_scores(assessment)
        emergency = danger >= config.emergency_danger
        # DEFEND opened this frame without its dwell.
        rushed = False
        for posture, gate in self._gates.items():
            skipped = gate.update(
                scores[posture], now, config.switch_margin, urgent=posture is DEFEND and emergency
            )
            rushed |= skipped
        wanted = next((item for item in _ORDER if self._gates[item].open), DEVELOP)
        posture = wanted if self._may_switch(wanted, now) else self._posture
        assert posture is not None
        if posture is not self._posture:
            left = self._posture
            self._previous, self._posture, self._since = left, posture, now
            self._reason = _reason(posture, left, assessment, rushed=rushed)
            self._because = _because(posture, left, assessment)
        if posture is not DEFEND:
            self._emergency = False
        elif emergency:
            self._emergency = True
        share = assessment.army_share
        army = _unit(0.3 + 0.5 * danger + 0.4 * (0.5 - share))
        return StrategicIntent(
            time=now,
            posture=posture,
            previous=self._previous,
            since=self._since,
            reason=self._reason,
            because=self._because,
            assessment=assessment,
            emergency=self._emergency,
            defense=danger,
            army=army,
            economy=1.0 - army,
            risk=share * (1.0 - danger),
            gates=tuple(
                PostureGate(item, scores[item], bool(gate.open), gate.since)
                for item, gate in self._gates.items()
            ),
        )

    def _may_switch(self, wanted: StrategicPosture, now: float) -> bool:
        """False only while `wanted` would take back the last change too soon."""

        current = self._posture
        if current is None or wanted is current or DEFEND in (current, wanted):
            return True
        return wanted is not self._previous or now - self._since >= self.config.stance_dwell


def gate_scores(assessment: GameAssessment) -> dict[StrategicPosture, float]:
    """How strongly the assessment answers each question yes, in [0, 1]."""

    safety = 1.0 - assessment.threat_level
    share = assessment.army_share
    ahead = max(0.0, assessment.army_position)
    behind = max(0.0, -assessment.army_position)
    return {
        DEFEND: assessment.threat_level,
        RECOVER: 1.0 - (1.0 - assessment.setback) * (1.0 - assessment.confidence * behind),
        COMMIT: safety * math.sqrt(ahead * assessment.enemy_vulnerability),
        PRESSURE: safety * max(share, min(1.0, 2.0 * share) * assessment.power_spike),
    }


def _reason(
    posture: StrategicPosture,
    left: StrategicPosture | None,
    assessment: GameAssessment,
    *,
    rushed: bool,
) -> str:
    if posture is DEFEND:
        return "emergency_threat" if rushed else "home_threatened"
    if posture is RECOVER:
        outmatched = assessment.confidence * max(0.0, -assessment.army_position)
        return "army_setback" if assessment.setback >= outmatched else "outmatched"
    if posture is COMMIT:
        return "decisive_advantage"
    if posture is PRESSURE:
        share = assessment.army_share
        spiking = min(1.0, 2.0 * share) * assessment.power_spike
        return "army_advantage" if share >= spiking else "power_spike"
    return _DEVELOP_REASONS[left]


def _because(
    posture: StrategicPosture, left: StrategicPosture | None, assessment: GameAssessment
) -> tuple[tuple[str, float], ...]:
    names = set(_SALIENT[posture]) | set(_SALIENT[left] if left is not None else ())
    return tuple((name, float(getattr(assessment, name))) for name in _WRITTEN if name in names)


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))
