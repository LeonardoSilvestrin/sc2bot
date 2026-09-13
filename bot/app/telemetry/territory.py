from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from sc2.position import Point2

from bot.ports.logging import BotLogger
from bot.world.awareness import AwarenessSnapshot, TerritoryControl

from .gate import ChangeGate

# Enough frontline points to see its shape without logging every crossing.
_FRONTLINE_POINTS = 6
# A region's security logs at once when it crosses one of these steps.
_SECURITY_STEP = 0.2


class TerritoryTelemetry:
    """Logs the perceived territory (``knowledge.territory``): how much of the
    map each side holds, the frontline, and the ground security of every base
    we hold and every region with an expansion slot.

    Aggregated, never sample by sample. It goes out when one of those regions
    changes control or security step, a base changes region, or the frontline
    appears or disappears, and otherwise on a ten-second heartbeat.
    """

    def __init__(self, *, logger: BotLogger) -> None:
        self._logger = logger
        self._gate = ChangeGate(heartbeat=10.0)

    def report(self, awareness: AwarenessSnapshot, *, game_time: float) -> None:
        territory = awareness.territory
        expansion_regions = tuple(
            region for region in territory.regions if region.expansions
        )
        signature = (
            tuple(
                (
                    region.key,
                    region.control,
                    round(region.ground_security / _SECURITY_STEP),
                )
                for region in expansion_regions
            ),
            tuple(
                (base.base_id, None if base.region is None else base.region.key)
                for base in territory.bases
            ),
            bool(territory.frontline),
        )
        if not self._gate.admit(signature, now=game_time):
            return
        self._logger.event(
            "knowledge.territory",
            component="world.awareness.territory",
            game_time=game_time,
            data={
                "samples": _control_counts(
                    sample.control for sample in territory.samples
                ),
                "regions": _control_counts(
                    region.control for region in territory.regions
                ),
                "confidence": round(territory.confidence, 2),
                "enemy_controlled_samples": territory.count(
                    TerritoryControl.ENEMY
                ),
                "enemy_threat_samples": sum(
                    sample.enemy_threat > 0.05 for sample in awareness.spatial.samples
                ),
                "remembered_enemy_clusters": territory.remembered_enemy_clusters,
                "oldest_enemy_memory": (
                    None
                    if territory.oldest_enemy_memory is None
                    else round(territory.oldest_enemy_memory, 1)
                ),
                "largest_position_uncertainty": round(
                    territory.largest_position_uncertainty, 1
                ),
                "largest_control_radius": round(
                    territory.largest_control_radius, 1
                ),
                "largest_possible_presence_radius": round(
                    territory.largest_possible_presence_radius, 1
                ),
                "frontline": {
                    "size": len(territory.frontline),
                    "points": [
                        _xy(point) for point in _representative(territory.frontline)
                    ],
                },
                "bases": [
                    {
                        "base_id": base.base_id,
                        "region": None if base.region is None else base.region.key,
                        "control": (
                            None if base.region is None else base.region.control.name
                        ),
                        "ground_access": (
                            None
                            if base.region is None
                            else round(base.region.ground_access, 2)
                        ),
                        "ground_security": (
                            None
                            if base.region is None
                            else round(base.region.ground_security, 2)
                        ),
                        "layered_ground_security": (
                            None
                            if base.region is None
                            else round(1.0 - base.region.layered_ground_access, 2)
                        ),
                        "confidence": (
                            None
                            if base.region is None
                            else round(base.region.reading.confidence, 2)
                        ),
                    }
                    for base in territory.bases
                ],
                "expansion_regions": [
                    {
                        "key": region.key,
                        "center": _xy(region.center),
                        "control": region.control.name,
                        "dominance": round(region.reading.dominance, 2),
                        "confidence": round(region.reading.confidence, 2),
                        "ground_security": round(region.ground_security, 2),
                        "layered_ground_security": round(
                            1.0 - region.layered_ground_access, 2
                        ),
                    }
                    for region in expansion_regions
                ],
            },
        )


def _control_counts(controls: Iterable[TerritoryControl]) -> dict[str, int]:
    counts = {control.name.lower(): 0 for control in TerritoryControl}
    for control in controls:
        counts[control.name.lower()] += 1
    return counts


def _representative(points: Sequence[Point2]) -> Sequence[Point2]:
    if len(points) <= _FRONTLINE_POINTS:
        return points
    step = len(points) / _FRONTLINE_POINTS
    return [points[int(index * step)] for index in range(_FRONTLINE_POINTS)]


def _xy(point: Point2) -> list[Any]:
    return [round(float(point.x), 1), round(float(point.y), 1)]
