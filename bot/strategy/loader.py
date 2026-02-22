#bot/strategy/loader.py
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .schema import (
    StrategyConfig,
    EconomyCfg,
    ProductionCfg,
    DropCfg,
    BehaviorsCfg,
    MacroBehaviorCfg,
    CombatBehaviorCfg,
    OpenerCfg,
)

_ALLOWED_POINTS = {"ENEMY_MAIN", "ENEMY_NATURAL", "MY_MAIN", "MY_NATURAL"}


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


def _parse_drop_obj(raw: Dict[str, Any], *, path: str, default_name: str) -> DropCfg:
    enabled = _as_bool(raw.get("enabled", False), path=f"{path}.enabled")
    if not enabled:
        return DropCfg(enabled=False, name=default_name)

    for k in ("min_marines", "load_count", "move_eps", "ground_radius", "staging", "target"):
        if k not in raw:
            raise KeyError(f"{path}.enabled=true exige '{k}'")

    name = raw.get("name", default_name)
    if not isinstance(name, str):
        raise TypeError(f"{path}.name: expected str")

    staging = _as_str(raw["staging"], path=f"{path}.staging")
    target = _as_str(raw["target"], path=f"{path}.target")

    if staging not in _ALLOWED_POINTS:
        raise ValueError(f"{path}.staging inválido: {staging} (allowed={sorted(_ALLOWED_POINTS)})")
    if target not in _ALLOWED_POINTS:
        raise ValueError(f"{path}.target inválido: {target} (allowed={sorted(_ALLOWED_POINTS)})")

    staging_dist = _as_float(raw.get("staging_dist", 18.0), path=f"{path}.staging_dist")

    start_time = raw.get("start_time", None)
    if start_time is not None:
        start_time = _as_float(start_time, path=f"{path}.start_time")

    start_loop = raw.get("start_loop", None)
    if start_loop is not None:
        start_loop = _as_int(start_loop, path=f"{path}.start_loop")

    pickup = _as_str(raw.get("pickup", "MY_MAIN"), path=f"{path}.pickup")
    if pickup not in _ALLOWED_POINTS:
        raise ValueError(f"{path}.pickup inválido: {pickup} (allowed={sorted(_ALLOWED_POINTS)})")

    pickup_eps = _as_float(raw.get("pickup_eps", 6.0), path=f"{path}.pickup_eps")
    load_range = _as_float(raw.get("load_range", 7.0), path=f"{path}.load_range")

    return DropCfg(
        enabled=True,
        name=name,
        start_time=start_time,
        start_loop=start_loop,
        min_marines=_as_int(raw["min_marines"], path=f"{path}.min_marines"),
        load_count=_as_int(raw["load_count"], path=f"{path}.load_count"),
        move_eps=_as_float(raw["move_eps"], path=f"{path}.move_eps"),
        ground_radius=_as_float(raw["ground_radius"], path=f"{path}.ground_radius"),
        pickup=pickup,
        staging=staging,
        target=target,
        staging_dist=staging_dist,
        pickup_eps=pickup_eps,
        load_range=load_range,
        require_stim=_as_bool(raw.get("require_stim", False), path=f"{path}.require_stim"),
    )


def _parse_opener(data: Dict[str, Any], *, path: str) -> OpenerCfg:
    # default: opener ligado e forçando wall
    if "opener" not in data or data["opener"] is None:
        return OpenerCfg()

    raw = data["opener"]
    if not isinstance(raw, dict):
        raise TypeError(f"{path}.opener must be object")

    enabled = _as_bool(raw.get("enabled", True), path=f"{path}.opener.enabled")
    force_wall = _as_bool(raw.get("force_wall", True), path=f"{path}.opener.force_wall")
    depots = _as_int(raw.get("depots", 2), path=f"{path}.opener.depots")
    barracks = _as_int(raw.get("barracks", 1), path=f"{path}.opener.barracks")

    # sane defaults
    depots = max(0, depots)
    barracks = max(0, barracks)

    return OpenerCfg(enabled=enabled, force_wall=force_wall, depots=depots, barracks=barracks)


def load_strategy(name: str) -> StrategyConfig:
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

    econ = _require_obj(data, "economy", path=str(path))
    beh = _require_obj(data, "behaviors", path=str(path))
    build = _require_list(data, "build", path=str(path))
    prod_rules = _require_list(data, "production_rules", path=str(path))

    scv_target = _as_int(econ.get("scv_target"), path="economy.scv_target")
    depot_trigger = _as_int(econ.get("depot_trigger_supply_left"), path="economy.depot_trigger_supply_left")

    prod_cfg = data.get("production", {})
    if not isinstance(prod_cfg, dict):
        raise TypeError("production must be object")
    marine_cap = _as_int(prod_cfg.get("marine_cap", 24), path="production.marine_cap")

    macro = beh.get("macro")
    if not isinstance(macro, dict):
        raise TypeError("behaviors.macro must be object")
    for k in ("enabled", "auto_workers", "auto_scv", "auto_supply"):
        if k not in macro:
            raise KeyError(f"behaviors.macro: missing required key '{k}'")

    combat = beh.get("combat")
    if not isinstance(combat, dict):
        raise TypeError("behaviors.combat must be object")
    if "enabled" not in combat:
        raise KeyError("behaviors.combat: missing required key 'enabled'")

    # wall_natural pode vir como root bool, ou wall: { natural: bool }
    wall_natural = False
    if "wall_natural" in data:
        wall_natural = _as_bool(data.get("wall_natural", False), path="wall_natural")
    elif "wall" in data and isinstance(data["wall"], dict):
        wall_natural = _as_bool(data["wall"].get("natural", False), path="wall.natural")

    opener = _parse_opener(data, path=str(path))

    drops: List[DropCfg] = []
    if "drops" in data and data["drops"] is not None:
        raw_drops = data["drops"]
        if not isinstance(raw_drops, list):
            raise TypeError("drops must be array")
        for i, rd in enumerate(raw_drops):
            if not isinstance(rd, dict):
                raise TypeError(f"drops[{i}] must be object")
            dc = _parse_drop_obj(rd, path=f"drops[{i}]", default_name=f"drop_{i}")
            if dc.enabled:
                drops.append(dc)
    else:
        raw_drop = data.get("drop", None)
        if raw_drop is not None:
            if not isinstance(raw_drop, dict):
                raise TypeError("drop must be object")
            dc = _parse_drop_obj(raw_drop, path="drop", default_name="drop_0")
            if dc.enabled:
                drops.append(dc)

    return StrategyConfig(
        name=str(data.get("name", name)),
        economy=EconomyCfg(scv_target=scv_target, depot_trigger_supply_left=depot_trigger),
        production=ProductionCfg(marine_cap=marine_cap),
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
        wall_natural=bool(wall_natural),
        opener=opener,
        drops=drops,
        build=build,
        production_rules=prod_rules,
    )