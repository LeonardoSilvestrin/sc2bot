from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class EconomyCfg:
    scv_target: int = 20
    depot_trigger_supply_left: int = 4


@dataclass(frozen=True)
class TechCfg:
    need_factory: bool = True
    need_starport: bool = True


@dataclass(frozen=True)
class ProductionCfg:
    marine_cap: int = 32
    marines_for_drop: int = 8


@dataclass(frozen=True)
class DropCfg:
    enabled: bool = True
    min_marines: int = 8
    load_count: int = 8
    move_eps: float = 3.0
    ground_radius: float = 12.0


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "default"
    economy: EconomyCfg = EconomyCfg()
    tech: TechCfg = TechCfg()
    production: ProductionCfg = ProductionCfg()
    drop: DropCfg = DropCfg()
    # raw plan lists (optional)
    build_plan: list[Dict[str, Any]] | None = None
    production_plan: list[Dict[str, Any]] | None = None


def _get(d: Dict[str, Any], key: str, default: Any) -> Any:
    v = d.get(key, default)
    return default if v is None else v


def _as_int(x: Any, *, default: int) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _as_float(x: Any, *, default: float) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _as_bool(x: Any, *, default: bool) -> bool:
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


def load_strategy(strategy_name: Optional[str], *, base_dir: str | Path | None = None) -> StrategyConfig:
    """
    Load strats/<name>.json. Fallback to default.json. If none found, return defaults.
    """
    if base_dir is None:
        base = Path(__file__).parent / "strats"
    else:
        base = Path(base_dir)
    name = (strategy_name or os.getenv("SC2_STRAT") or "default").strip()
    candidates = [base / f"{name}.json", base / "default.json"]

    path = next((p for p in candidates if p.exists()), None)
    if path is None:
        return StrategyConfig(name=name)

    data = json.loads(path.read_text(encoding="utf-8"))
    econ = data.get("economy", {}) or {}
    tech = data.get("tech", {}) or {}
    prod = data.get("production", {}) or {}
    drop = data.get("drop", {}) or {}

    cfg = StrategyConfig(
        name=str(_get(data, "name", name)),
        economy=EconomyCfg(
            scv_target=_as_int(_get(econ, "scv_target", 20), default=20),
            depot_trigger_supply_left=_as_int(_get(econ, "depot_trigger_supply_left", 4), default=4),
        ),
        tech=TechCfg(
            need_factory=_as_bool(_get(tech, "need_factory", True), default=True),
            need_starport=_as_bool(_get(tech, "need_starport", True), default=True),
        ),
        production=ProductionCfg(
            marine_cap=_as_int(_get(prod, "marine_cap", 32), default=32),
            marines_for_drop=_as_int(_get(prod, "marines_for_drop", 8), default=8),
        ),
        drop=DropCfg(
            enabled=_as_bool(_get(drop, "enabled", True), default=True),
            min_marines=_as_int(_get(drop, "min_marines", 8), default=8),
            load_count=_as_int(_get(drop, "load_count", 8), default=8),
            move_eps=_as_float(_get(drop, "move_eps", 3.0), default=3.0),
            ground_radius=_as_float(_get(drop, "ground_radius", 12.0), default=12.0),
        ),
        build_plan=data.get("build", None),
        production_plan=data.get("production", None),
    )

    # basic sanity: don't allow extremely low scv target
    if cfg.economy.scv_target < 12:
        cfg = StrategyConfig(
            name=cfg.name,
            economy=EconomyCfg(scv_target=12, depot_trigger_supply_left=cfg.economy.depot_trigger_supply_left),
            tech=cfg.tech,
            production=cfg.production,
            drop=cfg.drop,
        )
    return cfg
