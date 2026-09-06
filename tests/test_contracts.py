from __future__ import annotations

import ast
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.actions.models import ActionOutcome, ActionResult
from bot.infrastructure.logging import NullBotLogger


class ContractTests(unittest.TestCase):
    def test_action_result_requires_a_reason(self):
        with self.assertRaises(ValueError):
            ActionResult(ActionOutcome.RUNNING, "")

    def test_null_logger_never_opens_a_file(self):
        with patch("builtins.open", side_effect=AssertionError("file opened")):
            logger = NullBotLogger()
            logger.event("test", component="test", game_time=0.0)
            logger.close()

    def test_actions_do_not_import_forbidden_layers(self):
        actions_root = Path(__file__).parents[1] / "bot" / "actions"
        forbidden = ("ares", "bot.infrastructure", "bot.awareness", "bot.knowledge")
        violations: list[str] = []
        for path in actions_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name == forbidden[0] or name.startswith(forbidden[1:]):
                        violations.append(f"{path.name}: {name}")
        self.assertEqual(violations, [])
