from __future__ import annotations

import unittest

from sc2.ids.unit_typeid import UnitTypeId

from bot.behavior.scouting import IntelPlanner
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
