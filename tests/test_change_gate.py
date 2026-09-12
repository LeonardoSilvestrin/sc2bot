from __future__ import annotations

import unittest

from bot.app.telemetry.gate import ChangeGate


class ChangeGateTests(unittest.TestCase):
    def test_without_a_heartbeat_only_a_new_signature_passes(self):
        gate = ChangeGate()

        self.assertTrue(gate.admit(("a",), now=0.0))
        self.assertFalse(gate.admit(("a",), now=500.0))
        self.assertTrue(gate.admit(("b",), now=501.0))
        self.assertTrue(gate.admit(("a",), now=502.0))

    def test_a_heartbeat_resurfaces_a_steady_signature(self):
        gate = ChangeGate(heartbeat=10.0)

        self.assertTrue(gate.admit("steady", now=5.0))
        self.assertFalse(gate.admit("steady", now=14.9))
        self.assertTrue(gate.admit("steady", now=15.0))
        self.assertFalse(gate.admit("steady", now=20.0))

    def test_a_change_passes_at_once_and_restarts_the_heartbeat(self):
        gate = ChangeGate(heartbeat=10.0)
        gate.admit("before", now=0.0)

        self.assertTrue(gate.admit("after", now=3.0))
        self.assertFalse(gate.admit("after", now=12.0))
        self.assertTrue(gate.admit("after", now=13.0))


if __name__ == "__main__":
    unittest.main()
