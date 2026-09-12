from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Generic, Protocol, TypeVar


@dataclass(slots=True)
class ProposalCadence:
    """Rate-limits a planner's proposals and hands out stable id sequence
    numbers.

    Nearly every mission planner needs both: propose at most once per
    ``cadence`` seconds, and give each emitted proposal a sequence number so
    its ``proposal_id`` stays stable across frames (required for
    deduplication and for ``EconomyController``/``MissionController`` traces
    to read sensibly). Centralizing it here keeps that bookkeeping out of
    every planner's ``propose()``.
    """

    _last_proposed_at: float = field(default=-9999.0, init=False, repr=False)
    _sequence: int = field(default=0, init=False, repr=False)

    def ready(self, now: float, cadence: float) -> bool:
        return now - self._last_proposed_at >= cadence

    def mark(self, now: float) -> None:
        self._last_proposed_at = now

    def next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence


class RankedTarget(Protocol):
    """What ``choose_target`` needs of a candidate: a stable key and a score."""

    @property
    def key(self) -> str: ...

    @property
    def score(self) -> float: ...


TargetT = TypeVar("TargetT", bound=RankedTarget)


class TargetChange(Enum):
    """How one decision moved a planner's target.

    NONE        nothing held, nothing to take
    SELECTED    nothing held: the best candidate is taken
    KEPT        the held target is still a candidate and not clearly beaten
    RETARGETED  another candidate beats the held one by more than the margin
    REPLACED    the held target is no longer a candidate: the best is taken
    LOST        the held target is no longer a candidate, and none is left
    """

    NONE = auto()
    SELECTED = auto()
    KEPT = auto()
    RETARGETED = auto()
    REPLACED = auto()
    LOST = auto()

    @property
    def changed(self) -> bool:
        return self not in {TargetChange.NONE, TargetChange.KEPT}


@dataclass(frozen=True, slots=True)
class TargetChoice(Generic[TargetT]):
    """One ``choose_target`` decision, and the key it was measured from."""

    target: TargetT | None
    change: TargetChange
    previous_key: str | None


def choose_target(
    candidates: Sequence[TargetT], *, current_key: str | None, margin: float
) -> TargetChoice[TargetT]:
    """The best candidate -- unless the held one is still a candidate and
    nothing beats it by more than ``margin``.

    Scores drift a little on every assessment as freshness decays and counts
    change; following whichever candidate ranks first would send a squad
    back and forth between two near-equal targets. A held target the planner
    no longer offers as a candidate is dropped without any margin. Ties go to
    the earlier candidate.
    """

    best = max(candidates, key=lambda candidate: candidate.score, default=None)
    held = next(
        (candidate for candidate in candidates if candidate.key == current_key), None
    )
    if held is not None and best is not None:
        if best.score - held.score > margin:
            return TargetChoice(best, TargetChange.RETARGETED, current_key)
        return TargetChoice(held, TargetChange.KEPT, current_key)
    if best is None:
        change = TargetChange.NONE if current_key is None else TargetChange.LOST
        return TargetChoice(None, change, current_key)
    change = TargetChange.SELECTED if current_key is None else TargetChange.REPLACED
    return TargetChoice(best, change, current_key)
