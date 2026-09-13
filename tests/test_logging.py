from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bot.adapters.logging import JsonlBotLogger
from bot.adapters.logging.jsonl import SCHEMA_VERSION


def strict_records(path: Path) -> list[dict]:
    """Every line parsed as strict JSON: NaN or Infinity would raise."""

    def refuse(constant: str) -> float:
        raise ValueError(f"non-strict JSON constant {constant}")

    return [
        json.loads(line, parse_constant=refuse)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]


class CausalEnvelopeTests(unittest.TestCase):
    def test_every_record_carries_schema_run_sequence_and_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = JsonlBotLogger(Path(directory), session_name="pilot", run_id="r1")
            logger.event("game.started", component="app.runtime", game_time=0.0)
            logger.begin_frame(7)
            logger.event(
                "mission.evaluated",
                component="strategy.mission_policy",
                game_time=12.345678,
                data={"utility": 0.1 + 0.2},
            )
            logger.end_frame()
            logger.event("game.ended", component="app.runtime", game_time=99.0)
            logger.close()

            records = strict_records(logger.path)

        self.assertEqual([record["seq"] for record in records], [1, 2, 3])
        self.assertEqual({record["schema"] for record in records}, {SCHEMA_VERSION})
        self.assertEqual({record["run"] for record in records}, {"r1"})
        self.assertEqual([record["iteration"] for record in records], [None, 7, None])
        # Machine precision end to end: nothing is rounded on the way out.
        self.assertEqual(records[1]["game_time"], 12.345678)
        self.assertEqual(records[1]["data"]["utility"], 0.1 + 0.2)

    def test_each_logger_is_its_own_run(self):
        with tempfile.TemporaryDirectory() as directory:
            first = JsonlBotLogger(Path(directory), session_name="one")
            second = JsonlBotLogger(Path(directory), session_name="two")
            first.close()
            second.close()

        self.assertNotEqual(first.run_id, second.run_id)

    def test_unsupported_data_is_rejected_loudly_never_stringified(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = JsonlBotLogger(Path(directory), session_name="pilot")
            logger.event(
                "bad.object", component="c", game_time=1.0, data={"x": object()}
            )
            logger.event(
                "bad.number", component="c", game_time=2.0, data={"x": float("nan")}
            )
            logger.event("fine", component="c", game_time=3.0, data={"x": 1})
            logger.close()

            records = strict_records(logger.path)

        self.assertEqual(
            [record["event"] for record in records],
            ["logging.record_rejected", "logging.record_rejected", "fine"],
        )
        self.assertEqual(records[0]["data"]["rejected_event"], "bad.object")
        self.assertIn("not JSON serializable", records[0]["data"]["error"])
        self.assertEqual(records[1]["data"]["rejected_event"], "bad.number")
        self.assertNotIn("object at 0x", json.dumps(records))
        self.assertEqual([record["seq"] for record in records], [1, 2, 3])


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
