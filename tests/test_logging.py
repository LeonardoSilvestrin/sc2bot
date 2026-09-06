from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bot.infrastructure.logging import JsonlBotLogger


class JsonlBotLoggerTests(unittest.TestCase):
    def test_writes_one_structured_record_per_event(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = JsonlBotLogger(Path(directory), session_name="pilot")
            logger.event(
                "action.route_changed",
                component="action.drop",
                game_time=42.125,
                data={"reason": "anti_air_detected"},
            )
            logger.close()

            lines = (
                (Path(directory) / "pilot.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            record = json.loads(lines[0])

            self.assertEqual(len(lines), 1)
            self.assertEqual(record["event"], "action.route_changed")
            self.assertEqual(record["data"]["reason"], "anti_air_detected")
