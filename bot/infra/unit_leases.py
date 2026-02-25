#bot/runtime/unit_leases.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ares.consts import UnitRole


@dataclass
class Lease:
    owner: str          # task_id
    role: UnitRole
    expires_at: float


class UnitLeases:
    """
    Ownership mínimo com TTL pra evitar unidade "presa".
    - Task chama claim/touch.
    - Scheduler chama reap() por tick.
    """

    def __init__(self, *, default_ttl: float = 8.0):
        self.default_ttl = float(default_ttl)
        self._leases: Dict[int, Lease] = {}  # unit_tag -> Lease

    def reap(self, *, now: float) -> None:
        expired = [tag for tag, lease in self._leases.items() if lease.expires_at <= now]
        for tag in expired:
            del self._leases[tag]

    def owner_of(self, unit_tag: int, *, now: float) -> Optional[str]:
        self.reap(now=now)
        lease = self._leases.get(unit_tag)
        return lease.owner if lease else None

    def can_claim(self, unit_tag: int, *, now: float) -> bool:
        self.reap(now=now)
        return unit_tag not in self._leases

    def claim(
        self,
        *,
        task_id: str,
        unit_tag: int,
        role: UnitRole,
        now: float,
        ttl: Optional[float] = None,
        force: bool = False,
    ) -> bool:
        self.reap(now=now)
        if (not force) and unit_tag in self._leases:
            return False

        t = float(ttl) if ttl is not None else self.default_ttl
        self._leases[unit_tag] = Lease(owner=task_id, role=role, expires_at=now + t)
        return True

    def touch(self, *, task_id: str, unit_tag: int, now: float, ttl: Optional[float] = None) -> None:
        self.reap(now=now)
        lease = self._leases.get(unit_tag)
        if not lease or lease.owner != task_id:
            return
        t = float(ttl) if ttl is not None else self.default_ttl
        lease.expires_at = now + t

    def release_owner(self, *, task_id: str) -> None:
        to_del = [tag for tag, lease in self._leases.items() if lease.owner == task_id]
        for tag in to_del:
            del self._leases[tag]