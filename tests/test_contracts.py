from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.executors import MissionOutcome, MissionResult
from bot.infrastructure.logging import NullBotLogger


class ContractTests(unittest.TestCase):
    def test_mission_result_requires_a_reason(self):
        with self.assertRaises(ValueError):
            MissionResult(MissionOutcome.ACTIVE, "")

    def test_null_logger_never_opens_a_file(self):
        with patch("builtins.open", side_effect=AssertionError("file opened")):
            logger = NullBotLogger()
            logger.event("test", component="test", game_time=0.0)
            logger.close()

    def test_domain_boundaries_keep_ares_in_infrastructure(self):
        root = Path(__file__).parents[1] / "bot"
        scopes = {
            root / "attention": ("bot.awareness", "bot.ego", "bot.executors"),
            root / "awareness": ("bot.ego",),
            root / "planners": ("ares", "bot.infrastructure"),
            root / "executors": ("ares", "bot.infrastructure"),
        }
        violations: list[str] = []
        for scope, forbidden in scopes.items():
            for path in scope.rglob("*.py"):
                tree = ast.parse(
                    path.read_text(encoding="utf-8-sig"), filename=str(path)
                )
                for node in ast.walk(tree):
                    names: list[str] = []
                    if isinstance(node, ast.Import):
                        names = [alias.name for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module]
                    for name in names:
                        if any(
                            name == blocked or name.startswith(f"{blocked}.")
                            for blocked in forbidden
                        ):
                            violations.append(f"{path.name}: {name}")
        self.assertEqual(violations, [])
