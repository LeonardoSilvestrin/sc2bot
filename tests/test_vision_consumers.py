from __future__ import annotations

import unittest
from unittest.mock import Mock

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.defense import DefensePlanner
from bot.behavior.scouting import ScoutingVisionRequester
from bot.engine.missions import MissionContext
from bot.engine.services import (
    BehaviorServices,
    VisionRequestResult,
    VisionRequestStatus,
    VisionUrgency,
)
from bot.world.attention import (
    AttentionSnapshot,
    MapFacts,
    MapObservation,
    UnitSnapshot,
    WorldFacts,
)
from bot.world.awareness import AwarenessService

MAIN = Point2((90, 90))
OWN_MAIN = Point2((10, 10))


def unit(
    tag: int,
    unit_type: UnitTypeId,
    position: Point2,
    *,
    visible: bool = True,
    structure: bool = False,
) -> UnitSnapshot:
    return UnitSnapshot(
        tag=tag,
        unit_type=unit_type,
        position=position,
        health_percentage=1.0,
        is_flying=False,
        is_worker=False,
        can_attack_air=False,
        can_attack_ground=unit_type == UnitTypeId.MARINE,
        visible_now=visible,
        is_structure=structure,
    )


def attention(
    now: float,
    *,
    main_visible: bool = False,
    enemies: tuple[UnitSnapshot, ...] = (),
    structures: tuple[UnitSnapshot, ...] = (),
) -> AttentionSnapshot:
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(now),
            time=now,
            minerals=0,
            vespene=0,
            supply_used=0,
            supply_cap=15,
            own_units=(),
            enemy_units=enemies,
            own_structures=structures,
            map=MapFacts(
                center=Point2((50, 50)),
                own_start=OWN_MAIN,
                enemy_starts=(MAIN,),
                observations=(
                    MapObservation("enemy_main", MAIN, main_visible),
                ),
            ),
        )
    )


def service_context() -> tuple[BehaviorServices, Mock]:
    vision = Mock()
    vision.request.return_value = VisionRequestResult(
        request_id="vision-0001",
        status=VisionRequestStatus.PENDING,
        reason="awaiting_resolution",
    )
    return BehaviorServices(vision=vision), vision


class VisionConsumerTests(unittest.TestCase):
    def test_scouting_requests_a_capability_without_naming_an_orbital(self):
        services, vision = service_context()
        current = attention(120.0)
        awareness = AwarenessService().update(current)

        result = ScoutingVisionRequester(services=services).tick(current, awareness)

        self.assertEqual(result.status, VisionRequestStatus.PENDING)
        vision.request.assert_called_once_with(
            position=MAIN,
            urgency=VisionUrgency.NORMAL,
            requester="scouting",
            reason="enemy_main_vision_stale",
            ttl=12.0,
        )
        self.assertNotIn("orbital", vision.request.call_args.kwargs)

    def test_scouting_does_not_request_while_main_information_is_fresh(self):
        services, vision = service_context()
        current = attention(120.0, main_visible=True)
        awareness = AwarenessService().update(current)

        result = ScoutingVisionRequester(services=services).tick(current, awareness)

        self.assertIsNone(result)
        vision.request.assert_not_called()

    def test_defense_uses_the_same_api_for_a_recently_lost_nearby_threat(self):
        services, vision = service_context()
        townhall = unit(
            100, UnitTypeId.COMMANDCENTER, OWN_MAIN, structure=True
        )
        visible = attention(
            10.0,
            enemies=(unit(7, UnitTypeId.MARINE, Point2((12, 10))),),
            structures=(townhall,),
        )
        hidden = attention(
            11.0,
            enemies=(
                unit(
                    7,
                    UnitTypeId.MARINE,
                    Point2((12, 10)),
                    visible=False,
                ),
            ),
            structures=(townhall,),
        )
        awareness_service = AwarenessService()
        awareness_service.update(visible)

        DefensePlanner(services=services).propose(
            hidden, awareness_service.update(hidden)
        )

        vision.request.assert_called_once_with(
            position=Point2((12, 10)),
            urgency=VisionUrgency.HIGH,
            requester="defense_planner",
            reason="recent_threat_lost_near_own_base",
            ttl=6.0,
        )
        self.assertNotIn("orbital", vision.request.call_args.kwargs)

    def test_mission_context_exposes_the_same_service_to_executors(self):
        services, vision = service_context()
        current = attention(10.0)
        context = MissionContext(
            attention=current,
            awareness=AwarenessService().update(current),
            assigned_units=(),
            commands=Mock(),
            services=services,
        )

        self.assertIs(context.services.vision, vision)


if __name__ == "__main__":
    unittest.main()
