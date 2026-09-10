from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId

from bot.behavior.scouting import IntelAssessor, IntelPlanner
from bot.world.awareness import AwarenessService
from tests.test_scout_slice import attention


class IntelPlannerTests(unittest.TestCase):
    def test_waits_for_economic_gate(self):
        observed = attention(10.0, visible=False, workers=15)
        awareness = AwarenessService().update(observed)

        self.assertEqual(IntelPlanner().propose(observed, awareness), ())

    def test_does_not_propose_when_information_is_fresh(self):
        observed = attention(10.0, visible=True)
        awareness = AwarenessService().update(observed)

        self.assertEqual(IntelPlanner().propose(observed, awareness), ())

    def test_repeat_scout_waits_until_periodic_phase(self):
        service = AwarenessService(location_stale_after=90.0)
        planner = IntelPlanner()
        service.update(attention(10.0, visible=True))
        stale_early = attention(100.0, visible=False)
        stale_early_awareness = service.update(stale_early)
        periodic = attention(240.0, visible=False)
        periodic_awareness = service.update(periodic)

        self.assertEqual(planner.propose(stale_early, stale_early_awareness), ())
        proposals = planner.propose(periodic, periodic_awareness)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0].reason, "enemy_natural_information_stale")

    def test_falls_back_to_worker_when_no_reaper_is_alive(self):
        observed = attention(10.0, visible=False, reapers=0)
        awareness = AwarenessService().update(observed)

        proposals = IntelPlanner().propose(observed, awareness)

        self.assertEqual(len(proposals), 1)
        self.assertEqual(
            proposals[0].requirement.unit_types, frozenset({UnitTypeId.SCV})
        )

    def test_prefers_reaper_when_one_is_alive(self):
        observed = attention(10.0, visible=False, reapers=1)
        awareness = AwarenessService().update(observed)

        proposals = IntelPlanner().propose(observed, awareness)

        self.assertEqual(len(proposals), 1)
        self.assertEqual(
            proposals[0].requirement.unit_types, frozenset({UnitTypeId.REAPER})
        )


class IntelAssessmentTests(unittest.TestCase):
    def test_falls_back_to_the_natural_when_the_main_has_no_route(self):
        """Synthetic maps expose no main perimeter; the natural still works.

        Resolving that belongs to assessment, so planner and executor both
        see one already-decided target.
        """

        observed = attention(10.0, visible=False)
        awareness = AwarenessService().update(observed)

        assessment = IntelAssessor().assess(observed, awareness)

        self.assertEqual(assessment.target.key, "enemy_natural")
        self.assertFalse(assessment.target.has_route)
        self.assertTrue(assessment.target.is_stale)

    def test_reports_which_unit_would_be_spent(self):
        with_reaper = attention(10.0, visible=False, reapers=1)
        without = attention(10.0, visible=False, reapers=0)
        service = AwarenessService()

        alive = IntelAssessor().assess(with_reaper, service.update(with_reaper))
        gone = IntelAssessor().assess(without, service.update(without))

        self.assertTrue(alive.preferred_scout_alive)
        self.assertEqual(alive.scout_unit_types, frozenset({UnitTypeId.REAPER}))
        self.assertFalse(gone.preferred_scout_alive)
        self.assertEqual(gone.scout_unit_types, frozenset({UnitTypeId.SCV}))

    def test_the_plan_carries_the_reason_the_proposal_reports(self):
        observed = attention(10.0, visible=False)
        awareness = AwarenessService().update(observed)
        planner = IntelPlanner()

        proposals = planner.propose(observed, awareness)

        self.assertEqual(len(proposals), 1)
        self.assertEqual(planner.last_plan.reason, proposals[0].reason)
        self.assertEqual(planner.last_plan.target.key, proposals[0].target_key)


if __name__ == "__main__":
    unittest.main()
