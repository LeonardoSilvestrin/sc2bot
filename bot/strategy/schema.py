# schema.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class EconomyCfg:
    scv_target: int = 20
    depot_trigger_supply_left: int = 2


@dataclass(frozen=True)
class ProductionCfg:
    marine_cap: int = 24


@dataclass(frozen=True)
class DropCfg:
    enabled: bool = False
    min_marines: int = 8
    load_count: int = 8
    move_eps: float = 3.0
    ground_radius: float = 12.0


# ----------------------------
# Behaviors configs
# ----------------------------
@dataclass(frozen=True)
class MacroBehaviorCfg:
    enabled: bool = True
    auto_workers: bool = True
    auto_scv: bool = True
    auto_supply: bool = True


@dataclass(frozen=True)
class CombatBehaviorCfg:
    enabled: bool = False


@dataclass(frozen=True)
class BehaviorsCfg:
    macro: MacroBehaviorCfg = MacroBehaviorCfg()
    combat: CombatBehaviorCfg = CombatBehaviorCfg()


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "default"
    economy: EconomyCfg = EconomyCfg()
    production: ProductionCfg = ProductionCfg()
    drop: DropCfg = DropCfg()
    behaviors: BehaviorsCfg = BehaviorsCfg()

    # Plan DSL
    build: List[Dict[str, Any]] = field(default_factory=list)
    production_rules: List[Dict[str, Any]] = field(default_factory=list)