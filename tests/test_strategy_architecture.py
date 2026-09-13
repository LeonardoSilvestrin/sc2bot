"""Strategy stays a pure layer, and only the runtime drives it.

The scoring/director core remains runtime-free. The one named adapter may
read Awareness; the app runtime updates the director and publishes its
intent. Gameplay reads that intent, never the objective itself.
"""

from __future__ import annotations

import ast
import re
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


# The pure core: scoring, direction, intent and mission ranking. Everything
# else in bot.strategy is boundary -- it carries positions or reads Awareness.
PURE_CORE = (
    "config",
    "director",
    "hysteresis",
    "intent",
    "mission_policy",
    "model",
    "posture",
    "scoring",
)


class PurityTests(unittest.TestCase):
    def test_strategy_core_imports_only_itself_domain_contracts_and_stdlib(self):
        core = {f"bot.strategy.{name}" for name in PURE_CORE}
        found = [
            f"{path.relative_to(BOT).as_posix()}: {name}"
            for name_ in PURE_CORE
            for path in (STRATEGY / f"{name_}.py",)
            for name in sorted(imported_modules(path))
            if not any(is_within(name, module) for module in core)
            and not any(is_within(name, allowed) for allowed in ALLOWED_IMPORTS)
        ]

        self.assertEqual(found, [])

    def test_only_the_named_boundary_modules_import_awareness(self):
        consumers = [
            path.relative_to(STRATEGY).as_posix()
            for path in sorted(STRATEGY.rglob("*.py"))
            if any(
                is_within(name, "bot.world.awareness")
                for name in imported_modules(path)
            )
        ]

        self.assertEqual(consumers, ["awareness_adapter.py", "spatial/policy.py"])

    def test_strategy_never_reaches_downstream(self):
        downstream = (
            "bot.behavior",
            "bot.engine",
            "bot.app",
            "bot.macro",
            "bot.adapters",
        )
        found = [
            f"{path.relative_to(BOT).as_posix()}: {name}"
            for path in sorted(STRATEGY.rglob("*.py"))
            for name in sorted(imported_modules(path))
            if any(is_within(name, prefix) for prefix in downstream)
        ]

        self.assertEqual(found, [])

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


class ConsumerTests(unittest.TestCase):
    def test_only_the_runtime_drives_the_director(self):
        strategic_names = {
            "StrategicDirector",
            "StrategicObjective",
            "StrategyInputs",
            "StrategySnapshot",
            "build_strategy_inputs",
            "derive_control_objectives",
            "derive_intent",
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

        self.assertEqual(consumers, ["app/strategy_runtime.py"])

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


class NamingTests(unittest.TestCase):
    def test_strategic_intent_has_exactly_one_meaning(self):
        """The opening's capability gate is `OpeningIntent`; `StrategicIntent`
        is only Strategy's."""

        definers = [
            path.relative_to(BOT).as_posix()
            for path in sorted(BOT.rglob("*.py"))
            if re.search(
                r"^class \w*StrategicIntent\b",
                path.read_text(encoding="utf-8-sig"),
                re.MULTILINE,
            )
        ]

        self.assertEqual(definers, ["strategy/intent.py"])
        self.assertFalse((BOT / "behavior" / "strategy_intent.py").exists())


if __name__ == "__main__":
    unittest.main()
