from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bot.adapters.logging import JsonlBotLogger


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
                (Path(directory) / "pilot" / "game.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            )
            record = json.loads(lines[0])

            self.assertEqual(len(lines), 1)
            self.assertEqual(record["event"], "action.route_changed")
            self.assertEqual(record["data"]["reason"], "anti_air_detected")

    def test_rejects_session_names_that_escape_the_log_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            with self.assertRaises(ValueError):
                JsonlBotLogger(root / "logs", session_name="../outside")

            self.assertFalse((root / "outside").exists())

    def test_does_not_append_to_an_existing_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = JsonlBotLogger(root, session_name="pilot")
            first.close()

            with self.assertRaises(FileExistsError):
                JsonlBotLogger(root, session_name="pilot")

    def test_exposes_one_directory_for_all_game_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = JsonlBotLogger(Path(directory), session_name="pilot")

            self.assertEqual(logger.session_directory, Path(directory) / "pilot")
            self.assertEqual(logger.path, logger.session_directory / "game.jsonl")
            logger.close()
