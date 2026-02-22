#bot/strategy/schema.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class EconomyCfg:
    scv_target: int = 20
    depot_trigger_supply_left: int = 2


@dataclass(frozen=True)
class ProductionCfg:
    marine_cap: int = 24


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
class DropCfg:
    enabled: bool = False
    name: str = "drop"

    start_loop: Optional[int] = None
    start_time: Optional[float] = None

    min_marines: int = 8
    load_count: int = 8
    move_eps: float = 3.0
    ground_radius: float = 12.0

    pickup: str = "MY_MAIN"
    staging: str = "ENEMY_NATURAL"
    target: str = "ENEMY_MAIN"
    staging_dist: float = 18.0

    pickup_eps: float = 6.0
    load_range: float = 7.0

    require_stim: bool = False


@dataclass(frozen=True)
class OpenerCfg:
    """
    Opener obrigatório (se enabled):
      - depots na MAIN wall
      - barracks na MAIN wall
    'force_wall' tenta usar os spots do WallPlanner; se falhar repetidamente, o PlanExecutor faz fallback.
    """
    enabled: bool = True
    force_wall: bool = True
    depots: int = 2
    barracks: int = 1


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "default"

    economy: EconomyCfg = EconomyCfg()
    production: ProductionCfg = ProductionCfg()
    behaviors: BehaviorsCfg = BehaviorsCfg()

    # NATURAL wall como parâmetro da build (mantido)
    wall_natural: bool = False

    # NOVO: opener obrigatório (main wall)
    opener: OpenerCfg = OpenerCfg()

    drops: List[DropCfg] = field(default_factory=list)

    build: List[Dict[str, Any]] = field(default_factory=list)
    production_rules: List[Dict[str, Any]] = field(default_factory=list)