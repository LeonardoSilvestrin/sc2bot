# bot/core/state.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set


@dataclass
class BotState:
    iteration: int = 0

    # ---- unit management / reservations ----
    # unit_tag -> owner string (ex: "drop:drop_main")
    unit_owner: Dict[int, str] = field(default_factory=dict)

    # owner -> set of unit tags reserved
    owner_units: Dict[str, Set[int]] = field(default_factory=dict)

    # simple per-owner metadata (cooldowns, timestamps, etc.)
    owner_meta: Dict[str, dict] = field(default_factory=dict)

    def claim(self, owner: str, tag: int) -> None:
        tag = int(tag)
        self.unit_owner[tag] = owner
        self.owner_units.setdefault(owner, set()).add(tag)

    def release(self, tag: int) -> None:
        tag = int(tag)
        owner = self.unit_owner.pop(tag, None)
        if owner is None:
            return
        s = self.owner_units.get(owner)
        if s:
            s.discard(tag)

    def release_owner(self, owner: str) -> None:
        tags = list(self.owner_units.get(owner, set()))
        for t in tags:
            self.unit_owner.pop(int(t), None)
        self.owner_units[owner] = set()
        self.owner_meta.pop(owner, None)

    def owner_of(self, tag: int) -> Optional[str]:
        return self.unit_owner.get(int(tag))