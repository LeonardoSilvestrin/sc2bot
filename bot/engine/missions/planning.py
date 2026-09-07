from __future__ import annotations

from dataclasses import dataclass, field


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
