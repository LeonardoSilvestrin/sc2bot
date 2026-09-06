from __future__ import annotations

from collections.abc import Iterable

from bot.attention.models import (
    AttentionSnapshot,
    MapFacts,
    MissionSummary,
    UnitSnapshot,
    WorldFacts,
)
from bot.awareness.models import AwarenessSnapshot
from bot.knowledge.models import EnemyKnowledgeView


class AttentionBuilder:
    """The sole adapter that turns mutable Ares state into immutable facts."""

    @staticmethod
    def _unit_snapshot(bot, unit, *, visible_now: bool) -> UnitSnapshot:
        return UnitSnapshot(
            tag=int(unit.tag),
            unit_type=unit.type_id,
            position=unit.position,
            health_percentage=float(unit.health_percentage),
            is_flying=bool(unit.is_flying),
            is_worker=bool(unit.type_id == bot.worker_type),
            can_attack_air=bool(unit.can_attack_air),
            can_attack_ground=bool(unit.can_attack_ground),
            visible_now=visible_now,
        )

    def world_facts(self, bot, *, iteration: int) -> WorldFacts:
        own_units = tuple(
            self._unit_snapshot(bot, unit, visible_now=True) for unit in bot.units
        )
        enemy_units = tuple(
            self._unit_snapshot(
                bot, unit, visible_now=not bool(getattr(unit, "is_memory", False))
            )
            for unit in bot.all_enemy_units
        )
        return WorldFacts(
            iteration=int(iteration),
            time=float(bot.time),
            minerals=int(bot.minerals),
            vespene=int(bot.vespene),
            supply_used=float(bot.supply_used),
            supply_cap=float(bot.supply_cap),
            own_units=own_units,
            enemy_units=enemy_units,
            map=MapFacts(
                center=bot.game_info.map_center,
                own_start=bot.start_location,
                enemy_starts=tuple(bot.enemy_start_locations),
            ),
        )

    @staticmethod
    def build(
        *,
        world: WorldFacts,
        enemy_knowledge: EnemyKnowledgeView,
        awareness: AwarenessSnapshot,
        missions: Iterable[MissionSummary],
    ) -> AttentionSnapshot:
        return AttentionSnapshot(
            world=world,
            enemy_knowledge=enemy_knowledge,
            awareness=awareness,
            missions=tuple(missions),
        )
