#state.py

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from sc2.position import Point2


@dataclass
class DropPlan:
    in_progress: bool = False
    loaded: bool = False
    dropped: bool = False
    target_pos: Optional[Point2] = None
    staging_pos: Optional[Point2] = None


@dataclass
class BuildPlan:
    depot_started: bool = False
    rax_started: bool = False
    ref_started: bool = False
    factory_started: bool = False
    starport_started: bool = False


@dataclass
class PlacementPlan:
    ready: bool = False
    wall_depots: List[Point2] = field(default_factory=list)
    rax_slots: List[Point2] = field(default_factory=list)
    factory_slots: List[Point2] = field(default_factory=list)
    starport_slots: List[Point2] = field(default_factory=list)


@dataclass
class BotState:
    drop: DropPlan = field(default_factory=DropPlan)
    build: BuildPlan = field(default_factory=BuildPlan)
    place: PlacementPlan = field(default_factory=PlacementPlan)

    # last_try[tag] = game_loop when last attempt was made
    last_try: Dict[str, int] = field(
        default_factory=lambda: {
            "depot": -999999,
            "rax": -999999,
            "ref": -999999,
            "factory": -999999,
            "starport": -999999,
            "drop": -999999,
            "scv": -999999,
        }
    )

    def can_try(self, tag: str, now: int, cooldown: int) -> bool:
        last = self.last_try.get(tag, -999999)
        return (now - last) >= cooldown

    def mark_try(self, tag: str, now: int) -> None:
        self.last_try[tag] = now