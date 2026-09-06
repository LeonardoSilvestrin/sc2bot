from __future__ import annotations

import unittest

from bot.awareness import AwarenessService
from bot.planners import IntelPlanner
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
