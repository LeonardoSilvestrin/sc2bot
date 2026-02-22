# bot/strategy/loader.py
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
def _as_str(x: Any, *, path: str) -> str:
    if not isinstance(x, str):
        raise TypeError(f"{path}: expected str, got {type(x).__name__}")
    return x

def _as_int(x: Any, *, path: str) -> int:
    if not isinstance(x, (int, float)):
        raise TypeError(f"{path}: expected int, got {type(x).__name__}")
    return int(x)


def _as_float(x: Any, *, path: str) -> float:
    if not isinstance(x, (int, float)):
        raise TypeError(f"{path}: expected float, got {type(x).__name__}")
    return float(x)


def _as_bool(x: Any, *, path: str) -> bool:
    if not isinstance(x, bool):
        raise TypeError(f"{path}: expected bool, got {type(x).__name__}")
    return x


def _require_obj(d: Dict[str, Any], key: str, *, path: str) -> Dict[str, Any]:
    if key not in d:
        raise KeyError(f"{path}: missing required key '{key}'")
    v = d[key]
    if not isinstance(v, dict):
        raise TypeError(f"{path}.{key}: must be object")
    return v


def _require_list(d: Dict[str, Any], key: str, *, path: str) -> list:
    if key not in d:
        raise KeyError(f"{path}: missing required key '{key}'")
    v = d[key]
    if not isinstance(v, list):
        raise TypeError(f"{path}.{key}: must be array")
    return v


def load_strategy(name: str) -> StrategyConfig:
    """
    Carrega bot/strats/<name>.json.
    NÃO faz fallback.
    NÃO usa defaults silenciosos em behaviors habilitados.
    Explode se algo estiver errado.
    """
    base = Path(__file__).resolve().parents[1] / "strats"
    path = base / f"{name}.json"

    if not path.exists():
        raise FileNotFoundError(f"Strategy file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as e:
        raise RuntimeError(f"Failed to parse JSON strategy: {path}") from e

    if not isinstance(data, dict):
        raise ValueError(f"Strategy root must be JSON object: {path}")

    # Required top-level
    econ = _require_obj(data, "economy", path=str(path))
    beh = _require_obj(data, "behaviors", path=str(path))
    build = _require_list(data, "build", path=str(path))
    prod_rules = _require_list(data, "production_rules", path=str(path))

    # economy required keys
    scv_target = _as_int(econ.get("scv_target"), path="economy.scv_target")
    depot_trigger = _as_int(econ.get("depot_trigger_supply_left"), path="economy.depot_trigger_supply_left")

    # production (opcional por enquanto)
    prod_cfg = data.get("production", {})
    if not isinstance(prod_cfg, dict):
        raise TypeError("production must be object")
    marine_cap = prod_cfg.get("marine_cap", 24)
    marine_cap = _as_int(marine_cap, path="production.marine_cap")

    # behaviors.macro required keys
    macro = beh.get("macro")
    if not isinstance(macro, dict):
        raise TypeError("behaviors.macro must be object")
    for k in ("enabled", "auto_workers", "auto_scv", "auto_supply"):
        if k not in macro:
            raise KeyError(f"behaviors.macro: missing required key '{k}'")

    # behaviors.combat required keys
    combat = beh.get("combat")
    if not isinstance(combat, dict):
        raise TypeError("behaviors.combat must be object")
    if "enabled" not in combat:
        raise KeyError("behaviors.combat: missing required key 'enabled'")

    # drop (opcional)
    raw_drop = data.get("drop", {})
    if raw_drop is None:
        raw_drop = {}
    if not isinstance(raw_drop, dict):
        raise TypeError("drop must be object")

    drop_enabled = _as_bool(raw_drop.get("enabled", False), path="drop.enabled")

    if drop_enabled:
        # exigidos se enabled=true
        for k in ("min_marines", "load_count", "move_eps", "ground_radius", "staging", "target"):
            if k not in raw_drop:
                raise KeyError(f"drop.enabled=true exige '{k}'")

        staging = _as_str(raw_drop["staging"], path="drop.staging")
        target = _as_str(raw_drop["target"], path="drop.target")

        # valida enums "baratos" (evita typo silencioso)
        allowed_points = {"ENEMY_MAIN", "ENEMY_NATURAL", "MY_MAIN", "MY_NATURAL"}
        if staging not in allowed_points:
            raise ValueError(f"drop.staging inválido: {staging} (allowed={sorted(allowed_points)})")
        if target not in allowed_points:
            raise ValueError(f"drop.target inválido: {target} (allowed={sorted(allowed_points)})")

        staging_dist = raw_drop.get("staging_dist", None)
        if staging_dist is not None:
            staging_dist = _as_float(staging_dist, path="drop.staging_dist")

        drop_cfg = DropCfg(
            enabled=True,
            min_marines=_as_int(raw_drop["min_marines"], path="drop.min_marines"),
            load_count=_as_int(raw_drop["load_count"], path="drop.load_count"),
            move_eps=_as_float(raw_drop["move_eps"], path="drop.move_eps"),
            ground_radius=_as_float(raw_drop["ground_radius"], path="drop.ground_radius"),
            staging=staging,
            target=target,
            staging_dist=staging_dist,
        )
    else:
        drop_cfg = DropCfg(enabled=False)

    return StrategyConfig(
        name=str(data.get("name", name)),
        economy=EconomyCfg(
            scv_target=scv_target,
            depot_trigger_supply_left=depot_trigger,
        ),
        production=ProductionCfg(
            marine_cap=marine_cap,
        ),
        behaviors=BehaviorsCfg(
            macro=MacroBehaviorCfg(
                enabled=_as_bool(macro["enabled"], path="behaviors.macro.enabled"),
                auto_workers=_as_bool(macro["auto_workers"], path="behaviors.macro.auto_workers"),
                auto_scv=_as_bool(macro["auto_scv"], path="behaviors.macro.auto_scv"),
                auto_supply=_as_bool(macro["auto_supply"], path="behaviors.macro.auto_supply"),
            ),
            combat=CombatBehaviorCfg(
                enabled=_as_bool(combat["enabled"], path="behaviors.combat.enabled"),
            ),
        ),
        drop=drop_cfg,
        build=build,
        production_rules=prod_rules,
    )