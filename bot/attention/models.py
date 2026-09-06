from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

if TYPE_CHECKING:
    from bot.awareness.models import AwarenessSnapshot
    from bot.knowledge.models import EnemyKnowledgeView


@dataclass(frozen=True, slots=True)
class UnitSnapshot:
    tag: int
    unit_type: UnitTypeId
    position: Point2
    health_percentage: float
    is_flying: bool
    is_worker: bool
    can_attack_air: bool
    can_attack_ground: bool
    visible_now: bool = True


@dataclass(frozen=True, slots=True)
class MapFacts:
    center: Point2
    own_start: Point2
    enemy_starts: tuple[Point2, ...]


@dataclass(frozen=True, slots=True)
class WorldFacts:
    iteration: int
    time: float
    minerals: int
    vespene: int
    supply_used: float
    supply_cap: float
    own_units: tuple[UnitSnapshot, ...]
    enemy_units: tuple[UnitSnapshot, ...]
    map: MapFacts


@dataclass(frozen=True, slots=True)
class MissionSummary:
    action_id: str
    action_type: str
    status: str
    priority: int
    started_at: float | None
    assigned_unit_tags: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class AttentionSnapshot:
    """Immutable, authorized view consumed by actions."""

    world: WorldFacts
    enemy_knowledge: EnemyKnowledgeView
    awareness: AwarenessSnapshot
    missions: tuple[MissionSummary, ...]
