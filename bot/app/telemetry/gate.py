from __future__ import annotations

from collections.abc import Hashable


class ChangeGate:
    """Decides whether one deduplicated diagnostic event goes out this frame.

    It does when its signature differs from the last one let through or,
    given a ``heartbeat``, once that many game seconds have passed since then
    -- so a steady state still resurfaces in the log instead of vanishing.
    """

    def __init__(self, *, heartbeat: float | None = None) -> None:
        self._heartbeat = heartbeat
        self._signature: Hashable | None = None
        self._passed_at = -999.0

    def admit(self, signature: Hashable, *, now: float) -> bool:
        changed = signature != self._signature
        periodic = (
            self._heartbeat is not None and now - self._passed_at >= self._heartbeat
        )
        if not changed and not periodic:
            return False
        self._signature = signature
        self._passed_at = now
        return True
