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
    ttl: Optional[float] = None  # seconds; None = never expires


@dataclass
class MemoryStore:
    """
    Keyed memory with timestamped facts + optional TTL.
    Designed for fast per-tick usage (dict lookups), not analytics.
    """
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
            # clock skew / weirdness: treat as fresh
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
        """
        Returns a JSON-friendly dict of { "a:b:c": {value,t,age,ttl,confidence} }
        filtered by optional prefix and optional max_age.
        """
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
    """
    Persistent world memory.
    - Use mem for generic facts (keyed, timestamped, TTL-aware)
    - Keep only a few structured helpers where it buys clarity/perf.
    """
    mem: MemoryStore = field(default_factory=MemoryStore)

    # ring buffer style event log (debug/audit)
    _events: List[Dict[str, Any]] = field(default_factory=list)
    _events_cap: int = 200

    # -----------------------
    # Logging / events
    # -----------------------
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

    # -----------------------
    # Convenience “intel” API
    # (minimal wrappers so the rest of the bot stays clean)
    # -----------------------
    _K_SCV_DISPATCHED = K("intel", "scv", "dispatched")
    _K_SCV_ARRIVED_MAIN = K("intel", "scv", "arrived_main")
    _K_SCAN_ENEMY_MAIN = K("intel", "scan", "enemy_main")
    _K_LAST_SCV_DISPATCH_AT = K("intel", "scv", "last_dispatch_at")
    _K_LAST_SCAN_AT = K("intel", "scan", "last_scan_at")

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
        self.emit("intel_scv_dispatched", now=now)

    def mark_scv_arrived_main(self, *, now: float) -> None:
        self.mem.set(self._K_SCV_ARRIVED_MAIN, value=True, now=now, ttl=None)
        self.emit("intel_scv_arrived_main", now=now)

    def mark_scan_enemy_main(self, *, now: float) -> None:
        self.mem.set(self._K_SCAN_ENEMY_MAIN, value=True, now=now, ttl=None)
        self.mem.set(self._K_LAST_SCAN_AT, value=float(now), now=now, ttl=None)
        self.emit("intel_scan_enemy_main", now=now)

    def intel_snapshot(self, *, now: float) -> Dict[str, Any]:
        return {
            "scv_dispatched": self.intel_scv_dispatched(now=now),
            "scv_arrived_main": self.intel_scv_arrived_main(now=now),
            "scanned_enemy_main": self.intel_scanned_enemy_main(now=now),
            "last_scv_dispatch_at": round(self.intel_last_scv_dispatch_at(now=now), 2),
            "last_scan_at": round(self.intel_last_scan_at(now=now), 2),
        }