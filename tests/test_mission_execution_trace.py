"""What a running mission reports, and what fails while it runs, is on record."""

from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.missions import (
    MissionController,
    MissionKind,
    MissionProposal,
    UnitRequirement,
)
from bot.engine.missions.execution import MissionOutcome, MissionResult
from bot.world.attention import AttentionSnapshot, MapFacts, UnitSnapshot, WorldFacts
from bot.world.awareness import AwarenessSnapshot, RelativeStrength, ThreatAssessment
from bot.world.awareness.enemy import EnemyAwareness
from tests.fakes import FakeCommands, FakeLogger

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)
MARINE = UnitSnapshot(
    tag=1,
    unit_type=UnitTypeId.MARINE,
    position=Point2((10, 10)),
    health_percentage=1.0,
    is_flying=False,
    is_worker=False,
    can_attack_air=True,
    can_attack_ground=True,
)


def proposal(
    key: str, *, priority: int, now: float, kind: MissionKind = MissionKind.HARASS
) -> MissionProposal:
    return MissionProposal(
        proposal_id=f"{key}:{now}",
        deduplication_key=key,
        planner=f"{key}_planner",
        kind=kind,
        priority=priority,
        target_key=key,
        target=Point2((40, 40)),
        reason="test_mission",
        requirement=UnitRequirement.combat(
            unit_types=frozenset({UnitTypeId.MARINE}), desired=1, minimum=1
        ),
        created_at=now,
        timeout_seconds=600.0,
        can_preempt=True,
        commitment_seconds=0.0,
    )


class Scripted:
    """Reports ``results`` in order, repeating the last; optionally a cost."""

    def __init__(self, *results: MissionResult, cost=None) -> None:
        self.results = list(results)
        self.cost = cost

    async def step(self, context) -> MissionResult:
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]

    def preemption_cost(self) -> float:
        return 0.0 if self.cost is None else self.cost()


class Harness(unittest.IsolatedAsyncioTestCase):
    async def tick(self, controller, now: float, *proposals: MissionProposal) -> None:
        await controller.tick(
            attention=AttentionSnapshot(
                WorldFacts(
                    iteration=int(now),
                    time=now,
                    minerals=0,
                    vespene=0,
                    supply_used=1.0,
                    supply_cap=200.0,
                    own_units=(MARINE,),
                    enemy_units=(),
                    map=MAP,
                )
            ),
            awareness=AwarenessSnapshot(
                enemy=EnemyAwareness(sightings=(), locations=()),
                relative_strength=RelativeStrength(0.0, 0.0, 0, 0),
                threat=ThreatAssessment(0, 0, 0),
                updated_at=now,
            ),
            proposals=proposals,
            commands=FakeCommands(),
        )

    @staticmethod
    def named(logger: FakeLogger, name: str) -> list[dict]:
        return [event["data"] for event in logger.events if event["name"] == name]


class MissionProgressTests(Harness):
    async def test_progress_is_logged_when_the_report_changes_and_only_then(self):
        logger = FakeLogger()
        executor = Scripted(
            MissionResult(MissionOutcome.ACTIVE, "approaching"),
            MissionResult(MissionOutcome.ACTIVE, "approaching"),
            MissionResult(MissionOutcome.ACTIVE, "striking"),
            MissionResult(MissionOutcome.COMPLETED, "target_destroyed"),
        )
        controller = MissionController(
            logger=logger,
            executor_factories={MissionKind.HARASS: lambda mission, now: executor},
        )

        await self.tick(controller, 10.0, proposal("raid", priority=50, now=10.0))
        for now in (11.0, 12.0, 13.0):
            await self.tick(controller, now)

        progressed = self.named(logger, "mission.progressed")
        self.assertEqual(
            [(item["outcome"], item["reason"]) for item in progressed],
            [
                ("ACTIVE", "approaching"),
                ("ACTIVE", "striking"),
                ("COMPLETED", "target_destroyed"),
            ],
        )
        self.assertIsNone(progressed[0]["previous_reason"])
        self.assertEqual(progressed[1]["previous_reason"], "approaching")
        self.assertEqual({item["mission_id"] for item in progressed}, {"mission-0001"})
        self.assertEqual({item["proposal_id"] for item in progressed}, {"raid:10.0"})


class PreemptionCostFaultTests(Harness):
    async def test_a_failing_cost_is_logged_rate_limited_and_reads_as_zero(self):
        logger = FakeLogger()

        def broken() -> float:
            raise RuntimeError("cost model exploded")

        controller = MissionController(
            logger=logger,
            executor_factories={
                MissionKind.HARASS: lambda mission, now: Scripted(
                    MissionResult(MissionOutcome.ACTIVE, "raiding"), cost=broken
                ),
                MissionKind.DEFENSE: lambda mission, now: Scripted(
                    MissionResult(MissionOutcome.ACTIVE, "defending")
                ),
            },
        )

        # The executor exists only after the first allocation: no cost yet.
        await self.tick(controller, 10.0, proposal("raid", priority=50, now=10.0))
        await self.tick(controller, 11.0)  # first failure: logged
        await self.tick(controller, 12.0)  # within the interval: counted
        await self.tick(controller, 45.0)  # interval over: logged with the count

        faults = self.named(logger, "mission.preemption_cost_failed")
        self.assertEqual(len(faults), 2)
        self.assertEqual(faults[0]["error"], "RuntimeError: cost model exploded")
        self.assertEqual(faults[0]["fallback_cost"], 0.0)
        self.assertEqual(
            [item["suppressed_since_last"] for item in faults], [0, 1]
        )

        # Read as zero: a defense exactly the margin above takes the unit.
        await self.tick(
            controller,
            46.0,
            proposal("defense", priority=60, now=46.0, kind=MissionKind.DEFENSE),
        )
        defense = controller.board.live_for_key("defense")
        self.assertEqual(controller.allocator.owner_of(1), defense.mission_id)


if __name__ == "__main__":
    unittest.main()
