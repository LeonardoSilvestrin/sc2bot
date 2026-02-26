# bot/mind/awareness.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


Key = Tuple[str, ...]


@dataclass(frozen=True)
class Fact:
    value: Any
    t: float
    confidence: float = 1.0
    ttl: Optional[float] = None


@dataclass
class MemoryStore:
    _facts: Dict[Key, Fact] = field(default_factory=dict)

    def set(
        self,
        key: Key,
        *,
        value: Any,
        now: float,
        ttl: Optional[float] = None,
        confidence: float = 1.0,
    ) -> None:
        self._facts[key] = Fact(value=value, t=float(now), confidence=float(confidence), ttl=ttl)

    def get(self, key: Key, *, now: float, default: Any = None, max_age: Optional[float] = None) -> Any:
        f = self._facts.get(key)
        if f is None:
            return default
        age = float(now) - float(f.t)
        if age < 0:
            age = 0.0
        if max_age is not None and age > float(max_age):
            return default
        if f.ttl is not None and age > float(f.ttl):
            return default
        return f.value

    def age(self, key: Key, *, now: float) -> Optional[float]:
        f = self._facts.get(key)
        if f is None:
            return None
        return max(0.0, float(now) - float(f.t))

    def is_stale(self, key: Key, *, now: float, max_age: float) -> bool:
        a = self.age(key, now=now)
        if a is None:
            return True
        return a > float(max_age)

    def has(self, key: Key, *, now: float, max_age: Optional[float] = None) -> bool:
        sentinel = object()
        return self.get(key, now=now, default=sentinel, max_age=max_age) is not sentinel

    def keys(self) -> Iterable[Key]:
        return self._facts.keys()

    def snapshot(self, *, now: float, prefix: Optional[Key] = None, max_age: Optional[float] = None) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, f in self._facts.items():
            if prefix is not None and k[: len(prefix)] != prefix:
                continue
            age = max(0.0, float(now) - float(f.t))
            if max_age is not None and age > float(max_age):
                continue
            if f.ttl is not None and age > float(f.ttl):
                continue
            sk = ":".join(k)
            out[sk] = {
                "value": f.value,
                "t": round(float(f.t), 2),
                "age": round(float(age), 2),
                "ttl": f.ttl,
                "confidence": round(float(f.confidence), 2),
            }
        return out


def K(*parts: str) -> Key:
    return tuple(parts)


@dataclass
class Awareness:
    mem: MemoryStore = field(default_factory=MemoryStore)

    _events: List[Dict[str, Any]] = field(default_factory=list)
    _events_cap: int = 200

    def emit(self, name: str, *, now: float, data: Optional[Dict[str, Any]] = None) -> None:
        evt = {"t": round(float(now), 2), "name": str(name)}
        if data:
            evt["data"] = data
        self._events.append(evt)
        if len(self._events) > self._events_cap:
            self._events = self._events[-self._events_cap :]

    def tail_events(self, n: int = 10) -> List[Dict[str, Any]]:
        if n <= 0:
            return []
        return self._events[-n:]

    def ops_proposal_running(self, *, proposal_id: str, now: float) -> bool:
        if not isinstance(proposal_id, str) or not proposal_id:
            raise ValueError("proposal_id must be a non-empty string")

        for k, f in self.mem._facts.items():
            if len(k) < 4:
                continue
            if k[0] != "ops" or k[1] != "mission":
                continue
            if k[-1] != "proposal_id":
                continue
            if f.value != proposal_id:
                continue

            mission_id = k[2]
            st = str(self.mem.get(K("ops", "mission", mission_id, "status"), now=now, default=""))
            if st == "RUNNING":
                return True

        return False

    # -----------------------
    # Convenience “intel” API
    # -----------------------
    _K_SCV_DISPATCHED = K("intel", "scv", "dispatched")
    _K_SCV_ARRIVED_MAIN = K("intel", "scv", "arrived_main")
    _K_SCAN_ENEMY_MAIN = K("intel", "scan", "enemy_main")
    _K_LAST_SCV_DISPATCH_AT = K("intel", "scv", "last_dispatch_at")
    _K_LAST_SCAN_AT = K("intel", "scan", "last_scan_at")

    # New: reaper scout bookkeeping
    _K_REAPER_SCOUT_DISPATCHED = K("intel", "reaper", "scout", "dispatched")
    _K_LAST_REAPER_SCOUT_AT = K("intel", "reaper", "scout", "last_dispatch_at")
    _K_REAPER_SCOUT_LAST_DONE_AT = K("intel", "reaper", "scout", "last_done_at")

    def intel_scv_dispatched(self, *, now: float) -> bool:
        return bool(self.mem.get(self._K_SCV_DISPATCHED, now=now, default=False))

    def intel_scv_arrived_main(self, *, now: float) -> bool:
        return bool(self.mem.get(self._K_SCV_ARRIVED_MAIN, now=now, default=False))

    def intel_scanned_enemy_main(self, *, now: float) -> bool:
        return bool(self.mem.get(self._K_SCAN_ENEMY_MAIN, now=now, default=False))

    def intel_last_scv_dispatch_at(self, *, now: float) -> float:
        return float(self.mem.get(self._K_LAST_SCV_DISPATCH_AT, now=now, default=0.0))

    def intel_last_scan_at(self, *, now: float) -> float:
        return float(self.mem.get(self._K_LAST_SCAN_AT, now=now, default=0.0))

    def mark_scv_dispatched(self, *, now: float) -> None:
        self.mem.set(self._K_SCV_DISPATCHED, value=True, now=now, ttl=None)
        self.mem.set(self._K_LAST_SCV_DISPATCH_AT, value=float(now), now=now, ttl=None)

    def mark_scv_arrived_main(self, *, now: float, ttl: Optional[float] = None) -> None:
        self.mem.set(self._K_SCV_ARRIVED_MAIN, value=True, now=now, ttl=ttl)

    def mark_scanned_enemy_main(self, *, now: float) -> None:
        self.mem.set(self._K_SCAN_ENEMY_MAIN, value=True, now=now, ttl=None)
        self.mem.set(self._K_LAST_SCAN_AT, value=float(now), now=now, ttl=None)

    # Reaper scout markers
    def intel_reaper_scout_dispatched(self, *, now: float) -> bool:
        return bool(self.mem.get(self._K_REAPER_SCOUT_DISPATCHED, now=now, default=False))

    def intel_last_reaper_scout_dispatch_at(self, *, now: float) -> float:
        return float(self.mem.get(self._K_LAST_REAPER_SCOUT_AT, now=now, default=0.0))

    def intel_last_reaper_scout_done_at(self, *, now: float) -> float:
        return float(self.mem.get(self._K_REAPER_SCOUT_LAST_DONE_AT, now=now, default=0.0))

    def mark_reaper_scout_dispatched(self, *, now: float) -> None:
        self.mem.set(self._K_REAPER_SCOUT_DISPATCHED, value=True, now=now, ttl=None)
        self.mem.set(self._K_LAST_REAPER_SCOUT_AT, value=float(now), now=now, ttl=None)

    def mark_reaper_scout_done(self, *, now: float) -> None:
        self.mem.set(self._K_REAPER_SCOUT_LAST_DONE_AT, value=float(now), now=now, ttl=None)