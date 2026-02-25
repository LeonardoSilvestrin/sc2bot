# bot/infra/unit_leases.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set, List

from ares.consts import UnitRole


@dataclass
class Lease:
    owner: str          # task_id
    role: UnitRole
    expires_at: float


class UnitLeases:
    """
    Unit ownership with TTL and reverse index.
    """

    def __init__(self, *, default_ttl: float = 8.0):
        self.default_ttl = float(default_ttl)
        self._leases: Dict[int, Lease] = {}          # unit_tag -> Lease
        self._by_owner: Dict[str, Set[int]] = {}     # task_id -> {unit_tag}

    def reap(self, *, now: float) -> None:
        expired: List[int] = [tag for tag, lease in self._leases.items() if lease.expires_at <= now]
        for tag in expired:
            self._remove_tag(tag)

    def _remove_tag(self, unit_tag: int) -> None:
        lease = self._leases.pop(unit_tag, None)
        if lease is None:
            return
        s = self._by_owner.get(lease.owner)
        if s:
            s.discard(unit_tag)
            if not s:
                del self._by_owner[lease.owner]

    # ---------------- Queries ----------------

    def owner_of(self, unit_tag: int, *, now: float) -> Optional[str]:
        self.reap(now=now)
        lease = self._leases.get(unit_tag)
        return lease.owner if lease else None

    def units_of(self, task_id: str, *, now: float) -> Set[int]:
        self.reap(now=now)
        return set(self._by_owner.get(task_id, set()))

    def can_claim(self, unit_tag: int, *, now: float) -> bool:
        self.reap(now=now)
        return unit_tag not in self._leases

    # ---------------- Claim API ----------------

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

        if unit_tag in self._leases:
            self._remove_tag(unit_tag)

        t = float(ttl) if ttl is not None else self.default_ttl
        self._leases[unit_tag] = Lease(owner=task_id, role=role, expires_at=now + t)
        self._by_owner.setdefault(task_id, set()).add(unit_tag)
        return True

    def try_acquire(
        self,
        task_id: str,
        *,
        unit_tag: int,
        role: UnitRole,
        now: float,
        ttl: Optional[float] = None,
        force: bool = False,
    ) -> bool:
        """
        Convenience method (alias of claim) kept for compatibility with tasks.
        """
        return self.claim(
            task_id=task_id,
            unit_tag=unit_tag,
            role=role,
            now=now,
            ttl=ttl,
            force=force,
        )

    def touch(self, *, task_id: str, unit_tag: int, now: float, ttl: Optional[float] = None) -> None:
        self.reap(now=now)
        lease = self._leases.get(unit_tag)
        if not lease or lease.owner != task_id:
            return
        t = float(ttl) if ttl is not None else self.default_ttl
        lease.expires_at = now + t

    def release(self, *, unit_tag: int) -> None:
        self._remove_tag(unit_tag)

    def release_owner(self, *, task_id: str) -> None:
        tags = list(self._by_owner.get(task_id, []))
        for tag in tags:
            self._remove_tag(tag)

    def snapshot(self, *, now: float) -> dict:
        self.reap(now=now)
        return {
            "total_leases": len(self._leases),
            "by_owner": {owner: len(tags) for owner, tags in self._by_owner.items()},
        }