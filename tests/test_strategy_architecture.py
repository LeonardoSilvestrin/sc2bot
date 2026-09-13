"""Strategy stays a pure layer, and stays in shadow mode.

The scoring/director core remains runtime-free. The one named adapter may
read Awareness, and the app may update/log snapshots in shadow mode, but no
gameplay module may consume the new objective yet.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

BOT = Path(__file__).resolve().parents[1] / "bot"
STRATEGY = BOT / "strategy"

# Everything bot.strategy may import besides itself.
ALLOWED_IMPORTS = {
    "__future__",
    "bot.domain",
    "collections.abc",
    "dataclasses",
    "enum",
    "math",
    "statistics",
    "typing",
}
IO_CALLS = {"open", "print", "input", "exec", "eval"}


def imported_modules(path: Path) -> set[str]:
    """Absolute module names ``path`` imports, relative imports resolved."""

    # The package a relative import starts from: a module's parent, or the
    # package an ``__init__.py`` defines.
    package = list(path.relative_to(BOT.parent).parent.parts)
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - node.level + 1] if node.level else []
            module = ".".join([*base, node.module] if node.module else base)
            names.add(module)
            # ``from package import module`` imports the module too.
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def is_within(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(f"{prefix}.")


class PurityTests(unittest.TestCase):
    def test_strategy_core_imports_only_itself_domain_contracts_and_stdlib(self):
        found = [
            f"{path.relative_to(BOT).as_posix()}: {name}"
            for path in sorted(STRATEGY.rglob("*.py"))
            if path.name != "awareness_adapter.py"
            for name in sorted(imported_modules(path))
            if not is_within(name, "bot.strategy")
            and not any(
                is_within(name, allowed) or name.startswith(f"{allowed}.")
                for allowed in ALLOWED_IMPORTS
            )
        ]

        self.assertEqual(found, [])

    def test_only_the_named_adapter_imports_awareness(self):
        consumers = [
            path.relative_to(STRATEGY).as_posix()
            for path in sorted(STRATEGY.rglob("*.py"))
            if any(
                is_within(name, "bot.world.awareness")
                for name in imported_modules(path)
            )
        ]

        self.assertEqual(consumers, ["awareness_adapter.py"])

    def test_strategy_performs_no_io(self):
        found = [
            f"{path.relative_to(BOT).as_posix()}: {node.func.id}"
            for path in sorted(STRATEGY.rglob("*.py"))
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig")))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in IO_CALLS
        ]

        self.assertEqual(found, [])


class ShadowModeTests(unittest.TestCase):
    def test_only_the_shadow_coordinator_consumes_the_new_strategy_api(self):
        strategic_names = {
            "StrategicDirector",
            "StrategicObjective",
            "StrategyInputs",
            "StrategySnapshot",
            "build_strategy_inputs",
        }
        consumers: list[str] = []
        for path in sorted(BOT.rglob("*.py")):
            if STRATEGY in path.parents:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.module != "bot.strategy":
                    continue
                if strategic_names.intersection(alias.name for alias in node.names):
                    consumers.append(path.relative_to(BOT).as_posix())

        self.assertEqual(consumers, ["app/strategy_shadow.py"])

    def test_awareness_never_imports_strategy(self):
        consumers = [
            path.relative_to(BOT).as_posix()
            for path in sorted((BOT / "world" / "awareness").rglob("*.py"))
            if any(
                is_within(name, "bot.strategy")
                for name in imported_modules(path)
            )
        ]

        self.assertEqual(consumers, [])

    def test_relative_imports_resolve_to_their_own_package(self):
        """``from .strategy import ...`` in ``bot/macro/__init__.py`` is macro's
        own package, not a consumer of ``bot.strategy``."""

        names = imported_modules(BOT / "macro" / "__init__.py")

        self.assertTrue(any(is_within(name, "bot.macro.strategy") for name in names))
        self.assertFalse(any(is_within(name, "bot.strategy") for name in names))


if __name__ == "__main__":
    unittest.main()
