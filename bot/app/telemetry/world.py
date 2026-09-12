from __future__ import annotations

from bot.engine.missions import MissionSnapshot
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot
from bot.world.awareness import AwarenessSnapshot

from .gate import ChangeGate


class WorldSnapshotTelemetry:
    """Logs the headline belief (``knowledge.updated``) and the raw
    observation behind it (``observation.updated``) together, whenever the
    headline changes and on a ten-second heartbeat."""

    def __init__(self, *, logger: BotLogger) -> None:
        self._logger = logger
        self._gate = ChangeGate(heartbeat=10.0)

    def report(
        self,
        attention: AttentionSnapshot,
        awareness: AwarenessSnapshot,
        *,
        missions: tuple[MissionSnapshot, ...],
    ) -> None:
        world = attention.world
        economy = world.economy
        strength = awareness.relative_strength
        threat = awareness.threat
        live_missions = tuple(
            mission for mission in missions if not mission.status.terminal
        )
        signature = (
            awareness.macro_posture,
            round(strength.score, 3),
            strength.own_combat_units,
            strength.known_enemy_combat_units,
            threat.visible_enemy_units,
            threat.known_anti_air_units,
            threat.visible_anti_air_units,
            threat.visible_enemy_combat_units,
            threat.near_own_base_enemy_units,
            threat.near_own_base_enemy_combat_units,
            len(awareness.enemy.sightings),
            tuple(
                (mission.mission_id, mission.status.name) for mission in live_missions
            ),
        )
        if not self._gate.admit(signature, now=world.time):
            return
        self._logger.event(
            "knowledge.updated",
            component="world.awareness",
            game_time=world.time,
            data={
                "posture": awareness.macro_posture.name,
                "relative_strength": {
                    "score": round(strength.score, 3),
                    "confidence": round(strength.confidence, 3),
                    "own_combat_units": strength.own_combat_units,
                    "known_enemy_combat_units": strength.known_enemy_combat_units,
                },
                "threat": {
                    "visible_enemy_units": threat.visible_enemy_units,
                    "known_anti_air_units": threat.known_anti_air_units,
                    "visible_anti_air_units": threat.visible_anti_air_units,
                    "visible_enemy_combat_units": (
                        threat.visible_enemy_combat_units
                    ),
                    "near_own_base_enemy_units": (
                        threat.near_own_base_enemy_units
                    ),
                    "near_own_base_enemy_combat_units": (
                        threat.near_own_base_enemy_combat_units
                    ),
                },
                "enemy_sightings": len(awareness.enemy.sightings),
                "active_missions": len(live_missions),
            },
        )
        self._logger.event(
            "observation.updated",
            component="world.attention",
            game_time=world.time,
            data={
                "minerals": world.minerals,
                "vespene": world.vespene,
                "supply_used": world.supply_used,
                "supply_cap": world.supply_cap,
                "economy": {
                    "opening_name": economy.opening_name,
                    "opening_completed": economy.opening_completed,
                    "mineral_collection_rate": economy.mineral_collection_rate,
                    "vespene_collection_rate": economy.vespene_collection_rate,
                    "workers": {
                        "existing": economy.workers.existing,
                        "ready": economy.workers.ready,
                        "pending": economy.workers.pending,
                    },
                    "townhalls": {
                        "existing": economy.townhalls.existing,
                        "ready": economy.townhalls.ready,
                        "pending": economy.townhalls.pending,
                    },
                    "ideal_harvesters": economy.ideal_harvesters,
                    "assigned_harvesters": economy.assigned_harvesters,
                    "supply_pending": economy.supply_pending,
                },
                "own_unit_count": len(world.own_units),
                "own_structure_count": len(world.own_structures),
                "visible_enemy_unit_count": sum(
                    unit.visible_now for unit in world.enemy_units
                ),
            },
        )
