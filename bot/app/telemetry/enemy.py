from __future__ import annotations

from bot.ports.logging import BotLogger
from bot.world.awareness import AwarenessSnapshot

from .gate import ChangeGate


class EnemyTelemetry:
    """Logs what Awareness knows of the enemy: scouted structures and
    locations (``knowledge.enemy_intel``), then where its bases and forces are
    believed to be (``knowledge.enemy_model``)."""

    def __init__(self, *, logger: BotLogger) -> None:
        self._logger = logger
        self._intel_gate = ChangeGate()
        # Freshness moves every number every frame, so only a change in which
        # bases are confirmed or which cluster is the main force logs at once;
        # the numbers otherwise ride a ten-second heartbeat.
        self._model_gate = ChangeGate(heartbeat=10.0)

    def report(self, awareness: AwarenessSnapshot, *, game_time: float) -> None:
        self._report_intel(awareness, game_time=game_time)
        self._report_model(awareness, game_time=game_time)

    def _report_intel(self, awareness: AwarenessSnapshot, *, game_time: float) -> None:
        """Expose scout discoveries without bloating periodic world snapshots."""

        structures = tuple(
            sighting for sighting in awareness.enemy.sightings if sighting.is_structure
        )
        confirmed_locations = tuple(
            location.key
            for location in awareness.enemy.locations
            if location.last_observed_at is not None
        )
        signature = (
            tuple(
                (
                    structure.tag,
                    structure.unit_type,
                    round(structure.last_position.x, 1),
                    round(structure.last_position.y, 1),
                    structure.visible_now,
                )
                for structure in structures
            ),
            confirmed_locations,
        )
        if not self._intel_gate.admit(signature, now=game_time):
            return
        self._logger.event(
            "knowledge.enemy_intel",
            component="world.awareness.enemy",
            game_time=game_time,
            data={
                "known_enemy_bases": awareness.enemy.known_base_count,
                "known_enemy_structures": awareness.enemy.known_structure_count,
                "confirmed_locations": list(confirmed_locations),
                "structures": [
                    {
                        "tag": structure.tag,
                        "type": structure.unit_type.name,
                        "position": [
                            round(float(structure.last_position.x), 1),
                            round(float(structure.last_position.y), 1),
                        ],
                        "visible_now": structure.visible_now,
                        "last_seen_at": structure.last_seen_at,
                    }
                    for structure in structures
                ],
            },
        )

    def _report_model(self, awareness: AwarenessSnapshot, *, game_time: float) -> None:
        enemy = awareness.enemy
        confirmed = enemy.bases.confirmed
        main_force = enemy.main_force
        main_force_id = None if main_force is None else main_force.cluster_id
        signature = (tuple(base.key for base in confirmed), main_force_id)
        if not self._model_gate.admit(signature, now=game_time):
            return
        self._logger.event(
            "knowledge.enemy_model",
            component="world.awareness.enemy",
            game_time=game_time,
            data={
                "bases": [
                    {
                        "key": base.key,
                        "economic_value": round(base.economic_value, 2),
                        "workers": base.worker_count_estimate,
                        "air_defense": round(base.air_defense, 2),
                        "air_defense_confidence": round(
                            base.air_defense_confidence, 2
                        ),
                        "ground_defense": round(base.ground_defense, 2),
                        "ground_defense_confidence": round(
                            base.ground_defense_confidence, 2
                        ),
                        "confidence": round(base.confidence, 2),
                    }
                    for base in confirmed
                ],
                "forces": [
                    {
                        "cluster_id": cluster.cluster_id,
                        "center": [
                            round(float(cluster.center.x), 1),
                            round(float(cluster.center.y), 1),
                        ],
                        "radius": round(cluster.radius, 1),
                        "position_uncertainty": round(
                            cluster.position_uncertainty, 1
                        ),
                        "strength": round(cluster.combat_strength, 1),
                        "anti_air": round(cluster.anti_air_strength, 1),
                        "anti_ground": round(cluster.anti_ground_strength, 1),
                        "units": cluster.unit_count,
                        "visible_units": cluster.visible_unit_count,
                        "confidence": round(cluster.confidence, 2),
                    }
                    for cluster in enemy.forces
                ],
                "main_force": main_force_id,
            },
        )
