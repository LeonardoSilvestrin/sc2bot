"""
Tipos de dados fundamentais para o sistema de geometria operacional.

SectorId    — identificadores dos setores do mapa
SectorMode  — o que cada setor deve fazer
SectorState — estado completo de um setor num dado tick
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from sc2.position import Point2


class SectorId(str, Enum):
    """
    Setores operacionais do mapa.

    Esses setores são derivados da geometria do mapa (rampas, chokes, nat, main)
    e representam zonas funcionais do campo de batalha, não bases nomeadas.
    """
    HOME_CORE     = "HOME_CORE"       # Interior da main — produção, SCVs, reserva
    MAIN_RAMP     = "MAIN_RAMP"       # Topo da rampa — last line of defense
    RETREAT_BUFFER = "RETREAT_BUFFER" # Entre nat e main — zona de fallback
    NAT_FOOTPRINT = "NAT_FOOTPRINT"   # Área central da nat — reservada para CC
    NAT_RING      = "NAT_RING"        # Entorno da nat — guarnição leve
    NAT_CHOKE     = "NAT_CHOKE"       # Choke de entrada da nat — frente principal
    MID_APPROACH  = "MID_APPROACH"    # Corredor nat→mid — screen/pressure
    WATCH_AREA    = "WATCH_AREA"      # Posição de visão avançada no mapa
    THIRD_ENTRY   = "THIRD_ENTRY"     # Entrada da terceira base
    PUSH_STAGING  = "PUSH_STAGING"    # Área de concentração antes de push


class SectorMode(str, Enum):
    """
    Modo operacional de um setor.

    Define o papel estratégico das unidades nesse setor.
    """
    NONE         = "NONE"         # Sem presença — setor ignorado
    SCREEN       = "SCREEN"       # Presença leve: visão, early warning
    ANCHOR       = "ANCHOR"       # Ancoragem: hold position, aceita combate
    HEAVY_ANCHOR = "HEAVY_ANCHOR" # Ancoragem pesada: tanks sieged, bunker
    MASS_HOLD    = "MASS_HOLD"    # Concentração do bulk — posição principal
    PRESSURE     = "PRESSURE"     # Pressão ativa: avança e engaja
    RESERVED     = "RESERVED"     # Proibido — zona para expansão / trânsito


class OccupancyCap(str, Enum):
    """Quanto de força pode ocupar um setor simultaneamente."""
    ZERO      = "zero"      # Nenhuma unidade militar
    LOW       = "low"       # Até ~4 supply
    MEDIUM    = "medium"    # Até ~8 supply
    HIGH      = "high"      # Até ~16 supply
    UNLIMITED = "unlimited" # Sem limite


class SectorPriority(str, Enum):
    """Urgência de atender o setor."""
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    ABSOLUTE = "absolute"  # Não pode ser ignorado — defesa imediata


@dataclass
class SectorState:
    """Estado completo de um setor num dado tick."""
    sector_id:    SectorId
    mode:         SectorMode
    target_power: float          # Força desejada neste setor
    actual_power: float          # Força real presente (calculada pela geometria intel)
    cap:          OccupancyCap
    priority:     SectorPriority
    anchor_pos:   Optional[Point2] = None  # Posição concreta derivada do mapa
    dwell_min_s:  float = 4.0    # Tempo mínimo antes de realocar unidades
    hysteresis:   float = 1.5    # Margem de erro antes de trigger de reallocation

    @property
    def power_deficit(self) -> float:
        """Quanto de força falta para atingir o target."""
        return max(0.0, float(self.target_power) - float(self.actual_power))

    @property
    def power_surplus(self) -> float:
        """Quanto de força está acima do target."""
        return max(0.0, float(self.actual_power) - float(self.target_power))

    @property
    def needs_reinforcement(self) -> bool:
        return float(self.power_deficit) > float(self.hysteresis)

    @property
    def is_overstuffed(self) -> bool:
        return float(self.power_surplus) > float(self.hysteresis)

    def to_dict(self) -> dict:
        return {
            "sector_id":     self.sector_id.value,
            "mode":          self.mode.value,
            "target_power":  round(float(self.target_power), 2),
            "actual_power":  round(float(self.actual_power), 2),
            "occupancy_cap": self.cap.value,
            "priority":      self.priority.value,
            "anchor_pos":    {"x": float(self.anchor_pos.x), "y": float(self.anchor_pos.y)} if self.anchor_pos else None,
            "dwell_min_s":   float(self.dwell_min_s),
            "hysteresis":    float(self.hysteresis),
            "power_deficit": round(float(self.power_deficit), 2),
            "needs_reinforcement": bool(self.needs_reinforcement),
        }


class FrontTemplate(str, Enum):
    """
    Template doutrinário de configuração espacial.

    Determina qual geometria operacional queremos manter agora.
    Não é uma posição — é uma forma do mapa.
    """
    TURTLE_NAT          = "TURTLE_NAT"          # Defesa total no choke da nat
    STABILIZE_AND_EXPAND = "STABILIZE_AND_EXPAND" # Segurar nat, expandir
    CONTAIN             = "CONTAIN"             # Presença no mid, conter inimigo
    PREP_PUSH           = "PREP_PUSH"           # Concentrar para ataque
    HOLD_MAIN           = "HOLD_MAIN"           # Último recurso: segurar a main


# ---------------------------------------------------------------------------
# Mapeamento template → setores
# ---------------------------------------------------------------------------

def template_sector_config(template: FrontTemplate) -> dict[SectorId, tuple[SectorMode, OccupancyCap, SectorPriority, float]]:
    """
    Retorna configuração padrão dos setores para um template.
    Formato: { SectorId: (mode, cap, priority, target_power) }
    """
    if template == FrontTemplate.HOLD_MAIN:
        return {
            SectorId.MAIN_RAMP:     (SectorMode.MASS_HOLD,    OccupancyCap.UNLIMITED, SectorPriority.ABSOLUTE, 10.0),
            SectorId.HOME_CORE:     (SectorMode.ANCHOR,       OccupancyCap.HIGH,      SectorPriority.HIGH,      4.0),
            SectorId.NAT_FOOTPRINT: (SectorMode.RESERVED,     OccupancyCap.ZERO,      SectorPriority.ABSOLUTE,  0.0),
            SectorId.NAT_RING:      (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
            SectorId.NAT_CHOKE:     (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
            SectorId.RETREAT_BUFFER:(SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.MEDIUM,    2.0),
            SectorId.MID_APPROACH:  (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
            SectorId.WATCH_AREA:    (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
            SectorId.PUSH_STAGING:  (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
        }

    if template == FrontTemplate.TURTLE_NAT:
        return {
            SectorId.MAIN_RAMP:     (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.HIGH,      2.0),
            SectorId.HOME_CORE:     (SectorMode.ANCHOR,       OccupancyCap.MEDIUM,    SectorPriority.MEDIUM,    3.0),
            SectorId.NAT_FOOTPRINT: (SectorMode.RESERVED,     OccupancyCap.ZERO,      SectorPriority.ABSOLUTE,  0.0),
            SectorId.NAT_RING:      (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.MEDIUM,    2.0),
            SectorId.NAT_CHOKE:     (SectorMode.MASS_HOLD,    OccupancyCap.HIGH,      SectorPriority.ABSOLUTE, 10.0),
            SectorId.RETREAT_BUFFER:(SectorMode.ANCHOR,       OccupancyCap.LOW,       SectorPriority.MEDIUM,    3.0),
            SectorId.MID_APPROACH:  (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
            SectorId.WATCH_AREA:    (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
            SectorId.PUSH_STAGING:  (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
        }

    if template == FrontTemplate.STABILIZE_AND_EXPAND:
        return {
            SectorId.MAIN_RAMP:     (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.MEDIUM,    2.0),
            SectorId.HOME_CORE:     (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.NAT_FOOTPRINT: (SectorMode.RESERVED,     OccupancyCap.ZERO,      SectorPriority.ABSOLUTE,  0.0),
            SectorId.NAT_RING:      (SectorMode.ANCHOR,       OccupancyCap.MEDIUM,    SectorPriority.HIGH,      4.0),
            SectorId.NAT_CHOKE:     (SectorMode.MASS_HOLD,    OccupancyCap.HIGH,      SectorPriority.HIGH,      8.0),
            SectorId.RETREAT_BUFFER:(SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.MID_APPROACH:  (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.MEDIUM,    2.0),
            SectorId.WATCH_AREA:    (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
            SectorId.PUSH_STAGING:  (SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
        }

    if template == FrontTemplate.CONTAIN:
        return {
            SectorId.MAIN_RAMP:     (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.HOME_CORE:     (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.NAT_FOOTPRINT: (SectorMode.RESERVED,     OccupancyCap.ZERO,      SectorPriority.ABSOLUTE,  0.0),
            SectorId.NAT_RING:      (SectorMode.ANCHOR,       OccupancyCap.MEDIUM,    SectorPriority.MEDIUM,    3.0),
            SectorId.NAT_CHOKE:     (SectorMode.ANCHOR,       OccupancyCap.MEDIUM,    SectorPriority.HIGH,      5.0),
            SectorId.RETREAT_BUFFER:(SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.MID_APPROACH:  (SectorMode.MASS_HOLD,    OccupancyCap.HIGH,      SectorPriority.HIGH,      8.0),
            SectorId.WATCH_AREA:    (SectorMode.ANCHOR,       OccupancyCap.LOW,       SectorPriority.MEDIUM,    2.0),
            SectorId.PUSH_STAGING:  (SectorMode.ANCHOR,       OccupancyCap.MEDIUM,    SectorPriority.MEDIUM,    3.0),
        }

    if template == FrontTemplate.PREP_PUSH:
        return {
            SectorId.MAIN_RAMP:     (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.HOME_CORE:     (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.NAT_FOOTPRINT: (SectorMode.RESERVED,     OccupancyCap.ZERO,      SectorPriority.ABSOLUTE,  0.0),
            SectorId.NAT_RING:      (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.NAT_CHOKE:     (SectorMode.ANCHOR,       OccupancyCap.MEDIUM,    SectorPriority.MEDIUM,    4.0),
            SectorId.RETREAT_BUFFER:(SectorMode.NONE,         OccupancyCap.ZERO,      SectorPriority.LOW,       0.0),
            SectorId.MID_APPROACH:  (SectorMode.MASS_HOLD,    OccupancyCap.HIGH,      SectorPriority.HIGH,     10.0),
            SectorId.WATCH_AREA:    (SectorMode.SCREEN,       OccupancyCap.LOW,       SectorPriority.LOW,       1.0),
            SectorId.PUSH_STAGING:  (SectorMode.HEAVY_ANCHOR, OccupancyCap.UNLIMITED, SectorPriority.HIGH,     12.0),
        }

    # Default: STABILIZE
    return template_sector_config(FrontTemplate.STABILIZE_AND_EXPAND)
