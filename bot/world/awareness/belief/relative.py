from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class RelativePosition(Enum):
    """Where we stand against the enemy on one axis (economy, army, ...)."""

    AHEAD = auto()
    EVEN = auto()
    BEHIND = auto()
    UNKNOWN = auto()


@dataclass(frozen=True, slots=True)
class RelativeBeliefConfig:
    """Tunables for turning a noisy own-vs-enemy estimate into a stable belief.

    ``ahead_ratio``/``strong_ratio`` are read against
    ``(own - estimated) / max(own, estimated, 1)``: e.g. 0.15 means roughly a
    15% material edge before even considering AHEAD/BEHIND, and
    ``strong_ratio`` a large enough edge to skip the persistence window in
    ``advance`` entirely (see ``classify``). Directly observed evidence that
    already proves BEHIND bypasses both ratios -- see ``classify``.
    """

    ahead_ratio: float = 0.15
    strong_ratio: float = 0.45
    min_confidence: float = 0.35
    observed_certainty_floor: float = 0.75
    persist_seconds: float = 12.0

    def __post_init__(self) -> None:
        if not 0.0 < self.ahead_ratio < self.strong_ratio:
            raise ValueError("ahead_ratio must be positive and below strong_ratio")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be within [0, 1]")
        if not 0.0 <= self.observed_certainty_floor <= 1.0:
            raise ValueError("observed_certainty_floor must be within [0, 1]")
        if self.persist_seconds < 0.0:
            raise ValueError("persist_seconds must not be negative")


@dataclass(frozen=True, slots=True)
class RelativeAssessment:
    """One stabilized belief: how we compare to the enemy on one axis.

    ``raw_state`` is this tick's instantaneous read of the evidence;
    ``stable_state`` is the hysteresis-debounced belief that should actually
    be trusted (and is what gets announced in chat). ``reason`` is only
    populated on the tick ``stable_state`` actually changes.
    """

    raw_state: RelativePosition
    stable_state: RelativePosition
    confidence: float
    reason: str = ""


@dataclass(frozen=True, slots=True)
class PendingTransition:
    state: RelativePosition
    since: float


@dataclass(frozen=True, slots=True)
class HysteresisState:
    """Bookkeeping ``advance_belief`` needs across ticks for one axis."""

    stable: RelativePosition = RelativePosition.UNKNOWN
    changed_at: float = float("-inf")
    pending: PendingTransition | None = None


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def freshness(now: float, last_seen_at: float | None, stale_after: float) -> float:
    """1.0 for evidence seen this instant, decaying linearly to 0 by ``stale_after``."""

    if last_seen_at is None or stale_after <= 0.0:
        return 0.0
    age = max(0.0, now - last_seen_at)
    return clamp01(1.0 - (age / stale_after))


def classify(
    *,
    own: float,
    estimated: float,
    observed: float,
    confidence: float,
    config: RelativeBeliefConfig,
) -> tuple[RelativePosition, float, bool]:
    """Fixed-threshold read of the current evidence.

    Returns ``(raw_state, effective_confidence, is_strong_evidence)``.
    Directly observed material already matching or exceeding our own is
    proof, not a guess: more unseen enemy material can only make BEHIND
    truer, never false, so it concludes BEHIND regardless of scouting
    coverage and is always treated as strong evidence.
    """

    if own > 0.0 and observed >= own:
        return (
            RelativePosition.BEHIND,
            max(confidence, config.observed_certainty_floor),
            True,
        )

    if confidence < config.min_confidence:
        return RelativePosition.UNKNOWN, confidence, False

    denom = max(own, estimated, 1.0)
    ratio = (own - estimated) / denom
    strong = abs(ratio) >= config.strong_ratio
    if ratio >= config.ahead_ratio:
        return RelativePosition.AHEAD, confidence, strong
    if ratio <= -config.ahead_ratio:
        return RelativePosition.BEHIND, confidence, strong
    return RelativePosition.EVEN, confidence, False


def advance(
    *,
    now: float,
    raw_state: RelativePosition,
    strong: bool,
    state: HysteresisState,
    config: RelativeBeliefConfig,
) -> HysteresisState:
    """Debounce a raw-state stream into a persistent, non-flappy belief.

    A candidate that differs from the current stable state must either be
    strong evidence (applied immediately) or persist for
    ``config.persist_seconds`` before it is accepted -- see the module
    docstring on ``RelativeBeliefConfig`` for what "strong" means.
    """

    if raw_state is state.stable:
        return HysteresisState(stable=state.stable, changed_at=state.changed_at)

    if strong:
        return HysteresisState(stable=raw_state, changed_at=now)

    pending = state.pending
    if pending is None or pending.state is not raw_state:
        pending = PendingTransition(state=raw_state, since=now)
        return HysteresisState(
            stable=state.stable, changed_at=state.changed_at, pending=pending
        )

    if now - pending.since >= config.persist_seconds:
        return HysteresisState(stable=raw_state, changed_at=now)

    return HysteresisState(
        stable=state.stable, changed_at=state.changed_at, pending=pending
    )


def advance_belief(
    *,
    now: float,
    own: float,
    estimated: float,
    observed: float,
    confidence: float,
    reason: str,
    state: HysteresisState,
    config: RelativeBeliefConfig,
) -> tuple[RelativeAssessment, HysteresisState]:
    """Run ``classify`` then ``advance`` and package the result for one axis."""

    raw_state, effective_confidence, strong = classify(
        own=own,
        estimated=estimated,
        observed=observed,
        confidence=confidence,
        config=config,
    )
    new_state = advance(
        now=now, raw_state=raw_state, strong=strong, state=state, config=config
    )
    changed = new_state.stable is not state.stable
    assessment = RelativeAssessment(
        raw_state=raw_state,
        stable_state=new_state.stable,
        confidence=effective_confidence,
        reason=reason if changed else "",
    )
    return assessment, new_state
