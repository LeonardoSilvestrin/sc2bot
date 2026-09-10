"""ASSESS: what is the Banshee-harass situation right now?

Attention supplies observed facts, Awareness supplies memory and inference,
and this module reads both through one lens: *is there a raid to be flown?*
It answers with numbers only. It never claims a unit, never creates a
mission, and keeps no second copy of enemy knowledge -- everything about
the enemy comes from `AwarenessSnapshot`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.position import Point2

from bot.behavior.strategy_intent import BuildStrategicIntent, StrategicIntent
from bot.world.attention import AttentionSnapshot, UnitSnapshot
from bot.world.awareness import AwarenessSnapshot

from .model import BansheeHarassAssessment, BansheeHarassConfig, BansheeTarget


@dataclass(slots=True)
class BansheeHarassAssessor:
    """Builds a `BansheeHarassAssessment` from the world model."""

    config: BansheeHarassConfig = field(default_factory=BansheeHarassConfig)
    strategic_intent: StrategicIntent = field(default_factory=BuildStrategicIntent)

    def assess(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> BansheeHarassAssessment:
        world = attention.world
        banshees = tuple(
            unit for unit in world.own_units if unit.unit_type in self.config.unit_types
        )
        ready = sum(unit.is_ready for unit in banshees)
        pending = sum(
            world.economy.unit_count(unit_type).pending
            for unit_type in self.config.unit_types
        )
        cloak_progress = world.economy.upgrade_progress(self.config.cloak_upgrade)
        cloak_ready = world.economy.upgrade_ready(self.config.cloak_upgrade)
        targets = self._candidate_targets(attention, awareness)
        risk = self._risk(awareness, targets)
        return BansheeHarassAssessment(
            now=world.time,
            banshees_alive=len(banshees),
            banshees_ready=ready,
            banshees_pending=pending,
            cloak_ready=cloak_ready,
            cloak_progress=cloak_progress,
            workers=sum(unit.is_worker for unit in world.own_units),
            build_supports_harass=self.strategic_intent.allows(
                self.config.strategic_intent, world
            ),
            candidate_targets=targets,
            known_anti_air_units=awareness.threat.known_anti_air_units,
            enemy_army_position=self._enemy_army_position(awareness),
            readiness=self._readiness(
                len(banshees), pending, cloak_progress, targets
            ),
            risk=risk,
        )

    def _candidate_targets(
        self, attention: AttentionSnapshot, awareness: AwarenessSnapshot
    ) -> tuple[BansheeTarget, ...]:
        """One entry per configured location, in preference order."""

        enemy_units = attention.world.enemy_units
        targets: list[BansheeTarget] = []
        for key in self.config.target_keys:
            location = awareness.enemy.location(key)
            if location is None:
                continue
            targets.append(
                BansheeTarget(
                    key=key,
                    position=location.position,
                    last_observed_at=location.last_observed_at,
                    age=location.age,
                    stale_after=location.stale_after,
                    anti_air_nearby=self._anti_air_near(
                        enemy_units, location.position
                    ),
                    workers_seen=self._workers_near(enemy_units, location.position),
                )
            )
        return tuple(targets)

    def _anti_air_near(
        self, enemy_units: tuple[UnitSnapshot, ...], position: Point2
    ) -> int:
        radius = self.config.anti_air_check_radius
        return sum(
            unit.visible_now
            and unit.can_attack_air
            and unit.position.distance_to(position) <= radius
            for unit in enemy_units
        )

    def _workers_near(
        self, enemy_units: tuple[UnitSnapshot, ...], position: Point2
    ) -> int:
        radius = self.config.disengage_radius
        return sum(
            unit.visible_now
            and unit.is_worker
            and unit.position.distance_to(position) <= radius
            for unit in enemy_units
        )

    @staticmethod
    def _enemy_army_position(awareness: AwarenessSnapshot) -> Point2 | None:
        """Centroid of the enemy combat units Awareness still remembers.

        Not a launch gate today -- it is here because "where is their army"
        is the first thing a human asks before flying two Banshees somewhere,
        and the raid should be able to start using it without a new plumbing
        pass.
        """

        combat = tuple(
            sighting
            for sighting in awareness.enemy.sightings
            if not sighting.is_structure
            and not sighting.is_worker
            and (sighting.can_attack_air or sighting.can_attack_ground)
        )
        if not combat:
            return None
        return Point2(
            (
                sum(item.last_position.x for item in combat) / len(combat),
                sum(item.last_position.y for item in combat) / len(combat),
            )
        )

    def _readiness(
        self,
        alive: int,
        pending: int,
        cloak_progress: float,
        targets: tuple[BansheeTarget, ...],
    ) -> float:
        """How close the raid is to being worth launching, 0.0-1.0.

        Descriptive only: the planner's gates are explicit booleans, not a
        threshold on this number. It exists so the log can show "one Banshee,
        cloak at 30%" as a low number and "two Banshees, cloak done" as a
        high one without re-deriving that at the reading end.
        """

        squad = self.config.preferred_squad_size
        force = min(1.0, (alive + 0.5 * pending) / squad)
        known = any(target.is_known for target in targets)
        return round(force * cloak_progress * (1.0 if known else 0.0), 3)

    @staticmethod
    def _risk(
        awareness: AwarenessSnapshot, targets: tuple[BansheeTarget, ...]
    ) -> float:
        """How dangerous flying in looks, 0.0-1.0.

        Anti-air actually near the target dominates; anti-air merely known to
        exist somewhere contributes a smaller, saturating amount.
        """

        near = max((target.anti_air_nearby for target in targets), default=0)
        known = awareness.threat.known_anti_air_units
        return round(min(1.0, 0.6 * min(1.0, near) + 0.4 * min(1.0, known / 5.0)), 3)
