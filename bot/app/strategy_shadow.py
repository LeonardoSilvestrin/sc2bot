"""Deprecated alias: Strategy no longer runs in shadow mode.

Use :mod:`bot.app.strategy_runtime`. Kept so existing imports keep working.
"""

from __future__ import annotations

from .strategy_runtime import COMPONENT, StrategyRuntime

StrategyShadow = StrategyRuntime

__all__ = ["COMPONENT", "StrategyShadow"]
