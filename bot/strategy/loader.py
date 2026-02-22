# loader.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from .schema import (
    StrategyConfig,
    EconomyCfg,
    ProductionCfg,
    DropCfg,
    BehaviorsCfg,
    MacroBehaviorCfg,
    CombatBehaviorCfg,
)


def _as_int(x: Any, default: int) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _as_float(x: Any, default: float) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _as_bool(x: Any, default: bool) -> bool:
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        s = x.strip().lower()
        if s in {"1", "true", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "no", "n", "off"}:
            return False
    if isinstance(x, (int, float)):
        return bool(x)
    return default


def load_strategy(name: str) -> StrategyConfig:
    """
    Carrega bot/strats/<name>.json (utf-8-sig para suportar BOM)
    Fallback: bot/strats/default.json
    """
    base = Path(__file__).resolve().parents[1] / "strats"  # bot/strats
    path = base / f"{name}.json"

    if not path.exists():
        fallback = base / "default.json"
        if fallback.exists():
            path = fallback
        else:
            return StrategyConfig(name=name)

    data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8-sig"))

    econ = data.get("economy") or {}
    prod = data.get("production") or {}
    drop = data.get("drop") or {}

    beh = data.get("behaviors") or {}
    macro = beh.get("macro") or {}
    combat = beh.get("combat") or {}

    return StrategyConfig(
        name=str(data.get("name", name)),
        economy=EconomyCfg(
            scv_target=_as_int(econ.get("scv_target", 20), 20),
            depot_trigger_supply_left=_as_int(econ.get("depot_trigger_supply_left", 2), 2),
        ),
        production=ProductionCfg(
            marine_cap=_as_int(prod.get("marine_cap", 24), 24),
        ),
        drop=DropCfg(
            enabled=_as_bool(drop.get("enabled", False), False),
            min_marines=_as_int(drop.get("min_marines", 8), 8),
            load_count=_as_int(drop.get("load_count", 8), 8),
            move_eps=_as_float(drop.get("move_eps", 3.0), 3.0),
            ground_radius=_as_float(drop.get("ground_radius", 12.0), 12.0),
        ),
        behaviors=BehaviorsCfg(
            macro=MacroBehaviorCfg(
                enabled=_as_bool(macro.get("enabled", True), True),
                auto_workers=_as_bool(macro.get("auto_workers", True), True),
                auto_scv=_as_bool(macro.get("auto_scv", True), True),
                auto_supply=_as_bool(macro.get("auto_supply", True), True),
            ),
            combat=CombatBehaviorCfg(
                enabled=_as_bool(combat.get("enabled", False), False),
            ),
        ),
        build=data.get("build") or [],
        production_rules=data.get("production_rules") or [],
    )