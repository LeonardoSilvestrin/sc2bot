from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from bot.mind.awareness import Awareness, K


@dataclass
class EnemyRushStateStore:
    awareness: Awareness

    def get_opening_first_seen_t(self, *, now: float) -> float | None:
        val = self.awareness.mem.get(K("enemy", "opening", "first_seen_t"), now=now, default=None)
        if val is None:
            return None
        return float(val)

    def set_opening_first_seen_t(self, *, now: float) -> None:
        self.awareness.mem.set(K("enemy", "opening", "first_seen_t"), value=float(now), now=now, ttl=None)

    def get_rush_state(self, *, now: float) -> str:
        return str(self.awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE")

    def get_rush_last_seen_pressure_t(self, *, now: float) -> float:
        return float(self.awareness.mem.get(K("enemy", "rush", "last_seen_pressure_t"), now=now, default=0.0) or 0.0)

    def get_workers_peak_seen(self, *, now: float) -> int:
        return int(self.awareness.mem.get(K("enemy", "rush", "workers_peak_seen"), now=now, default=0) or 0)

    def set_workers_peak_seen(self, *, now: float, value: int) -> None:
        self.awareness.mem.set(K("enemy", "rush", "workers_peak_seen"), value=int(value), now=now, ttl=None)

    def set_opening_snapshot(
        self,
        *,
        now: float,
        ttl_s: float,
        kind: str,
        confidence: float,
        signals: dict[str, Any],
    ) -> None:
        self.awareness.mem.set(K("enemy", "opening", "kind"), value=str(kind), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "opening", "confidence"), value=float(confidence), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "opening", "signals"), value=dict(signals), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "opening", "last_update_t"), value=float(now), now=now, ttl=None)

    def set_rush_snapshot(
        self,
        *,
        now: float,
        ttl_s: float,
        state: str,
        confidence: float,
        score: float,
        evidence: dict[str, Any],
        last_seen_pressure_t: float,
    ) -> None:
        self.awareness.mem.set(K("enemy", "rush", "state"), value=str(state), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "rush", "confidence"), value=float(confidence), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "rush", "score"), value=float(score), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "rush", "evidence"), value=dict(evidence), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(
            K("enemy", "rush", "last_seen_pressure_t"),
            value=float(last_seen_pressure_t),
            now=now,
            ttl=None,
        )
        self.awareness.mem.set(K("enemy", "rush", "last_update_t"), value=float(now), now=now, ttl=None)

    def set_rush_confirmed(self, *, now: float) -> None:
        self.awareness.mem.set(K("enemy", "rush", "last_confirmed_t"), value=float(now), now=now, ttl=None)

    def set_rush_ended(self, *, now: float, reason: str) -> None:
        self.awareness.mem.set(K("enemy", "rush", "ended_t"), value=float(now), now=now, ttl=None)
        self.awareness.mem.set(K("enemy", "rush", "ended_reason"), value=str(reason), now=now, ttl=None)


@dataclass
class EnemyWeakPointsStateStore:
    awareness: Awareness

    def set_weak_points_snapshot(
        self,
        *,
        now: float,
        ttl_s: float,
        payload: dict[str, Any],
        points: list[dict[str, Any]],
        primary: dict[str, Any] | None,
    ) -> None:
        self.awareness.mem.set(K("enemy", "weak_points", "snapshot"), value=dict(payload), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "weak_points", "points"), value=list(points), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "weak_points", "primary"), value=primary, now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "weak_points", "bases_visible"), value=int(len(points)), now=now, ttl=float(ttl_s))
        self.awareness.mem.set(K("enemy", "weak_points", "last_update_t"), value=float(now), now=now, ttl=None)
        # New canonical location-scoped publication for planners/tasks.
        self.awareness.mem.set(
            K("intel", "locations", "enemy_weak_points", "snapshot"),
            value=dict(payload),
            now=now,
            ttl=float(ttl_s),
        )
        self.awareness.mem.set(
            K("intel", "locations", "enemy_weak_points", "points"),
            value=list(points),
            now=now,
            ttl=float(ttl_s),
        )
        self.awareness.mem.set(
            K("intel", "locations", "enemy_weak_points", "primary"),
            value=primary,
            now=now,
            ttl=float(ttl_s),
        )
        self.awareness.mem.set(
            K("intel", "locations", "enemy_weak_points", "targets"),
            value=list(points),
            now=now,
            ttl=float(ttl_s),
        )
        self.awareness.mem.set(
            K("intel", "locations", "enemy_weak_points", "last_update_t"),
            value=float(now),
            now=now,
            ttl=None,
        )
