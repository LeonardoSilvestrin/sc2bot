# schema.py
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
class DropCfg:
    enabled: bool = False
    min_marines: Optional[int] = None
    load_count: Optional[int] = None
    move_eps: Optional[float] = None
    ground_radius: Optional[float] = None

    # novos campos (do seu JSON)
    staging: Optional[str] = None   # ex: "ENEMY_NATURAL"
    target: Optional[str] = None    # ex: "ENEMY_MAIN"
    staging_dist: Optional[float] = None  # opcional (fallback)
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
    # OBS: "estratégia selecionada" NÃO é responsabilidade do schema.
    # O schema só descreve o conteúdo do JSON carregado.
    name: str = "default"

    economy: EconomyCfg = EconomyCfg()
    production: ProductionCfg = ProductionCfg()
    behaviors: BehaviorsCfg = BehaviorsCfg()
    drop: DropCfg = DropCfg()

    build: List[Dict[str, Any]] = field(default_factory=list)
    production_rules: List[Dict[str, Any]] = field(default_factory=list)