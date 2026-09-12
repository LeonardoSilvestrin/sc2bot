from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from .estimate import QuantityEstimate


class RelativePosition(Enum):
    """Where we stand against the enemy on one axis (economy, army, ...)."""

    AHEAD = auto()
    EVEN = auto()
    BEHIND = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class RelativeBeliefConfig:
    """How the probability of being ahead becomes a stated position.

    ``advantage`` is P(ours > theirs) from ``estimate.advantage``. The doubt
    about the enemy is already inside it, so no separate confidence gate
    exists: an unscouted enemy reads near 0.5, i.e. EVEN. Entering a
    position takes a clearer reading than staying in it (``*_enter`` vs
    ``*_exit``), and a new position must hold for ``persist_seconds`` before
    it is believed -- except BEHIND at or below ``decisive_behind``, acted on
    at once: wrongly cautious is cheap, wrongly greedy is not.
    """

    ahead_enter: float = 0.75
    ahead_exit: float = 0.60
    behind_enter: float = 0.25
    behind_exit: float = 0.40
    decisive_behind: float = 0.10
    persist_seconds: float = 12.0

    def __post_init__(self) -> None:
        if not (
            0.0
            <= self.decisive_behind
            <= self.behind_enter
            < self.behind_exit
            <= 0.5
            <= self.ahead_exit
            < self.ahead_enter
            <= 1.0
        ):
            raise ValueError(
                "thresholds must satisfy 0 <= decisive_behind <= behind_enter"
                " < behind_exit <= 0.5 <= ahead_exit < ahead_enter <= 1"
            )
        if self.persist_seconds < 0.0:
            raise ValueError("persist_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class RelativeAssessment:
    """One stabilized belief: how we compare to the enemy on one axis.

    ``raw_state`` is this tick's reading of ``advantage``; ``stable_state``
    is the position that reading has held long enough to be believed (and
    is what gets announced in chat). ``reason`` is only populated on the
    tick ``stable_state`` actually changes.
    """

    raw_state: RelativePosition
    stable_state: RelativePosition
    confidence: float
    reason: str = ""
    advantage: float = 0.5


@dataclass(frozen=True, slots=True)
class PendingTransition:
    state: RelativePosition
    since: float


@dataclass(frozen=True, slots=True)
class HysteresisState:
    """Bookkeeping ``advance`` needs across ticks for one axis."""

    stable: RelativePosition = RelativePosition.UNKNOWN
    changed_at: float = float("-inf")
    pending: PendingTransition | None = None


@dataclass(frozen=True, slots=True)
class BeliefState:
    """Everything one axis carries from one update to the next."""

    estimate: QuantityEstimate | None = None
    hysteresis: HysteresisState = HysteresisState()
    # Whether the axis has ever had evidence. Before that there is nothing
    # to compare, only an assumption, and the position stays UNKNOWN.
    informed: bool = False


def classify(
    *,
    advantage: float,
    informed: bool,
    state: HysteresisState,
    config: RelativeBeliefConfig,
) -> tuple[RelativePosition, bool]:
    """Read a position off the probability of being ahead.

    Returns ``(raw_state, decisive)``. A position already believed, or
    already waiting to be, is kept until the reading crosses its exit
    threshold; any other position needs its entry threshold.
    """

    if not informed:
        return RelativePosition.UNKNOWN, False
    held = {state.stable}
    if state.pending is not None:
        held.add(state.pending.state)
    if RelativePosition.AHEAD in held and advantage >= config.ahead_exit:
        position = RelativePosition.AHEAD
    elif RelativePosition.BEHIND in held and advantage <= config.behind_exit:
        position = RelativePosition.BEHIND
    elif advantage >= config.ahead_enter:
        position = RelativePosition.AHEAD
    elif advantage <= config.behind_enter:
        position = RelativePosition.BEHIND
    else:
        position = RelativePosition.EVEN
    decisive = (
        position is RelativePosition.BEHIND and advantage <= config.decisive_behind
    )
    return position, decisive


def advance(
    *,
    now: float,
    raw_state: RelativePosition,
    decisive: bool,
    state: HysteresisState,
    config: RelativeBeliefConfig,
) -> HysteresisState:
    """Accept a new position once it has held for ``persist_seconds``.

    UNKNOWN is not a claim about relative strength and never replaces a
    believed position.
    """

    if raw_state is state.stable or raw_state is RelativePosition.UNKNOWN:
        return HysteresisState(stable=state.stable, changed_at=state.changed_at)

    if decisive:
        return HysteresisState(stable=raw_state, changed_at=now)

    pending = state.pending
    if pending is None or pending.state is not raw_state:
        pending = PendingTransition(state=raw_state, since=now)
    if now - pending.since >= config.persist_seconds:
        return HysteresisState(stable=raw_state, changed_at=now)
    return HysteresisState(
        stable=state.stable, changed_at=state.changed_at, pending=pending
    )


def advance_belief(
    *,
    now: float,
    advantage: float,
    informed: bool,
    confidence: float,
    reason: str,
    state: HysteresisState,
    config: RelativeBeliefConfig,
) -> tuple[RelativeAssessment, HysteresisState]:
    """Run ``classify`` then ``advance`` and package the result for one axis."""

    raw_state, decisive = classify(
        advantage=advantage, informed=informed, state=state, config=config
    )
    new_state = advance(
        now=now, raw_state=raw_state, decisive=decisive, state=state, config=config
    )
    changed = new_state.stable is not state.stable
    assessment = RelativeAssessment(
        raw_state=raw_state,
        stable_state=new_state.stable,
        confidence=confidence,
        reason=reason if changed else "",
        advantage=advantage,
    )
    return assessment, new_state
