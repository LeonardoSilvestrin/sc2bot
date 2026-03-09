"""
Army Posture Intel — camada de síntese operacional.

Responsabilidade: consumir a geometria operacional (OperationalGeometryIntel)
e produzir a POSTURA EXPLÍCITA do exército para compatibilidade com o sistema legado.

A partir da refatoração para OperationalGeometryController, este módulo é uma camada
de tradução: converte FrontTemplate → ArmyPosture e lê anchor/detach do setor MASS_HOLD.

Não comanda unidades. Não propõe tasks. Só sintetiza e persiste em awareness.

Chaves produzidas:
    K("strategy", "army", "posture")            → ArmyPosture value (str)
    K("strategy", "army", "anchor")             → Point2 payload
    K("strategy", "army", "secondary_anchor")   → Point2 payload | None
    K("strategy", "army", "max_detach_supply")  → int
    K("strategy", "army", "min_bulk_supply")    → int
    K("strategy", "army", "snapshot")           → dict completo

Regras semânticas:
    - A postura deriva do FrontTemplate da geometria operacional
    - O anchor deriva do setor MASS_HOLD da geometria
    - max_detach_supply deriva da soma de target_power dos setores secundários
    - Planners devem ler da geometria diretamente quando possível
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sc2.position import Point2

from bot.intel.geometry.sector_types import FrontTemplate, SectorId, SectorMode
from bot.mind.awareness import Awareness, K


# ---------------------------------------------------------------------------
# Enum de Postura
# ---------------------------------------------------------------------------

class ArmyPosture(str, Enum):
    """
    Postura operacional do bulk do exército.

    HOLD_MAIN_RAMP      — tank/army segura o topo da rampa da main
    HOLD_NAT_CHOKE      — bulk na frente da nat (forward anchor da nat)
    SECURE_NAT          — bulk avançando para tomar/segurar a nat
    CONTROLLED_RETREAT  — recuar para fallback anchor (nat comprometida → main ramp)
    CONTROLLED_RETAKE   — retomar posição perdida com força adequada
    PRESS_FORWARD       — avançar além da nat (vantagem clara)
    ABANDON_EXPOSED_BASE — abandonar base exposta, consolidar em posição defensável
    """
    HOLD_MAIN_RAMP = "HOLD_MAIN_RAMP"
    HOLD_NAT_CHOKE = "HOLD_NAT_CHOKE"
    SECURE_NAT = "SECURE_NAT"
    CONTROLLED_RETREAT = "CONTROLLED_RETREAT"
    CONTROLLED_RETAKE = "CONTROLLED_RETAKE"
    PRESS_FORWARD = "PRESS_FORWARD"
    ABANDON_EXPOSED_BASE = "ABANDON_EXPOSED_BASE"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArmyPostureIntelConfig:
    ttl_s: float = 6.0

    # Supply do exército (army supply = supply_army do bot)
    hold_main_min_supply: int = 0       # Sempre pode segurar a main
    hold_nat_min_supply: int = 4        # Mínimo para ir para a nat choke
    secure_nat_min_supply: int = 6      # Mínimo para avançar e tomar a nat
    press_forward_min_supply: int = 14  # Mínimo para avançar além

    # Destacamento máximo em % do army supply
    detach_fraction_normal: float = 0.35   # 35% do exército pode ser destacado
    detach_fraction_pressed: float = 0.20  # Se pressionado, destacamento menor
    detach_min_supply: int = 2
    detach_max_supply: int = 12

    # Thresholds de parity
    retreat_parity_threshold: float = -0.4  # parity_score abaixo disso → considera retreat
    retake_parity_threshold: float = 0.1    # acima disso → retake viável
    press_parity_threshold: float = 0.35    # acima disso → press forward


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _point_from_payload(payload) -> Point2 | None:
    if not isinstance(payload, dict):
        return None
    try:
        return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
    except Exception:
        return None


def _point_payload(pos: Point2 | None) -> dict | None:
    if pos is None:
        return None
    return {"x": float(pos.x), "y": float(pos.y)}


def _army_supply(bot) -> int:
    try:
        return int(getattr(bot, "supply_army", 0) or 0)
    except Exception:
        return 0


def _parity_score(awareness: Awareness, now: float) -> float:
    """Lê parity score normalizado de game_parity_intel (-1..+1 aprox)."""
    raw = awareness.mem.get(K("strategy", "parity", "army_score_norm"), now=now, default=0.0)
    try:
        return float(raw or 0.0)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Lógica de derivação de postura
# ---------------------------------------------------------------------------

_TEMPLATE_TO_POSTURE: dict[str, ArmyPosture] = {
    FrontTemplate.HOLD_MAIN.value:           ArmyPosture.HOLD_MAIN_RAMP,
    FrontTemplate.TURTLE_NAT.value:          ArmyPosture.HOLD_NAT_CHOKE,
    FrontTemplate.STABILIZE_AND_EXPAND.value: ArmyPosture.HOLD_NAT_CHOKE,
    FrontTemplate.CONTAIN.value:             ArmyPosture.PRESS_FORWARD,
    FrontTemplate.PREP_PUSH.value:           ArmyPosture.PRESS_FORWARD,
}


def _posture_from_geometry(awareness: Awareness, now: float) -> ArmyPosture:
    """
    Deriva ArmyPosture a partir do FrontTemplate ativo na geometria operacional.
    Fallback para lógica legada se a geometria não estiver disponível.
    """
    template_str = awareness.mem.get(K("intel", "geometry", "operational", "template"), now=now, default=None)
    if template_str is not None:
        posture = _TEMPLATE_TO_POSTURE.get(str(template_str))
        if posture is not None:
            return posture

    # Fallback: lê nat_ground_state diretamente
    nat_ground_state = str(
        awareness.mem.get(K("intel", "frontline", "nat", "ground_state"), now=now, default="CLEAR") or "CLEAR"
    ).upper()
    main_ground_state = str(
        awareness.mem.get(K("intel", "frontline", "main", "ground_state"), now=now, default="CLEAR") or "CLEAR"
    ).upper()
    if main_ground_state in {"COMPROMISED", "LOST"}:
        return ArmyPosture.HOLD_MAIN_RAMP
    if nat_ground_state in {"COMPROMISED", "LOST"}:
        return ArmyPosture.HOLD_NAT_CHOKE
    return ArmyPosture.HOLD_MAIN_RAMP


def _derive_posture(
    *,
    army_supply: int,
    parity_score: float,
    rush_state: str,
    nat_ground_state: str,
    nat_control_state: str,
    main_ground_state: str,
    main_shielded_by_nat: bool,
    nat_has_th: bool,
    nat_retake_viable: bool,
    nat_taken: bool,
    bases_now: int,
    cfg: ArmyPostureIntelConfig,
) -> ArmyPosture:
    """
    Derivação de postura legada — mantida para fallback.
    Use _posture_from_geometry quando a geometria operacional estiver disponível.
    """
    # --- 1. Main sob ataque real ---
    if main_ground_state in {"COMPROMISED", "LOST"}:
        return ArmyPosture.HOLD_MAIN_RAMP

    # --- 2. Rush ativo ---
    rush_active = rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
    if rush_active:
        if int(army_supply) < int(cfg.hold_nat_min_supply):
            return ArmyPosture.HOLD_MAIN_RAMP
        if nat_ground_state not in {"LOST"}:
            return ArmyPosture.HOLD_NAT_CHOKE
        return ArmyPosture.HOLD_MAIN_RAMP

    # --- 3. Nat perdida ---
    if nat_ground_state == "LOST" or nat_control_state == "ENEMY":
        if bool(nat_retake_viable) and int(army_supply) >= int(cfg.secure_nat_min_supply):
            return ArmyPosture.CONTROLLED_RETAKE
        return ArmyPosture.CONTROLLED_RETREAT

    # --- 4. Nat comprometida ---
    if nat_ground_state == "COMPROMISED":
        if float(parity_score) < float(cfg.retreat_parity_threshold):
            return ArmyPosture.CONTROLLED_RETREAT
        if int(army_supply) >= int(cfg.hold_nat_min_supply):
            return ArmyPosture.HOLD_NAT_CHOKE
        return ArmyPosture.HOLD_MAIN_RAMP

    # --- 5. Nat clear/contested ---
    if nat_ground_state in {"CLEAR", "CONTESTED"}:
        if not bool(nat_taken) and bases_now < 2:
            if int(army_supply) >= int(cfg.secure_nat_min_supply):
                return ArmyPosture.SECURE_NAT
            return ArmyPosture.HOLD_MAIN_RAMP
        if bool(nat_taken):
            if float(parity_score) >= float(cfg.press_parity_threshold) and int(army_supply) >= int(cfg.press_forward_min_supply):
                return ArmyPosture.PRESS_FORWARD
            if int(army_supply) >= int(cfg.hold_nat_min_supply):
                return ArmyPosture.HOLD_NAT_CHOKE
            return ArmyPosture.HOLD_MAIN_RAMP
        if int(army_supply) >= int(cfg.hold_nat_min_supply):
            return ArmyPosture.HOLD_NAT_CHOKE
        return ArmyPosture.HOLD_MAIN_RAMP

    return ArmyPosture.HOLD_MAIN_RAMP


def _derive_anchor(
    *,
    posture: ArmyPosture,
    nat_forward_anchor: Point2 | None,
    nat_fallback_anchor: Point2 | None,
    main_fallback_anchor: Point2 | None,
    nat_center: Point2 | None,
    main_pos: Point2,
) -> Point2:
    """Retorna o anchor do bulk baseado na postura."""
    if posture == ArmyPosture.HOLD_MAIN_RAMP:
        return main_fallback_anchor or main_pos
    if posture == ArmyPosture.HOLD_NAT_CHOKE:
        return nat_forward_anchor or nat_center or main_pos
    if posture == ArmyPosture.SECURE_NAT:
        return nat_center or nat_forward_anchor or main_pos
    if posture == ArmyPosture.CONTROLLED_RETREAT:
        return nat_fallback_anchor or main_fallback_anchor or main_pos
    if posture == ArmyPosture.CONTROLLED_RETAKE:
        return nat_forward_anchor or nat_center or main_pos
    if posture == ArmyPosture.PRESS_FORWARD:
        return nat_center or nat_forward_anchor or main_pos
    if posture == ArmyPosture.ABANDON_EXPOSED_BASE:
        return main_fallback_anchor or main_pos
    return main_pos


def _derive_detach_budget(
    *,
    posture: ArmyPosture,
    army_supply: int,
    cfg: ArmyPostureIntelConfig,
) -> int:
    """
    Orçamento de supply disponível para destacamentos locais (DefensePlanner).
    O bulk não pode ser sequestrado por defesa local.
    """
    pressed = posture in {ArmyPosture.HOLD_MAIN_RAMP, ArmyPosture.CONTROLLED_RETREAT}
    fraction = float(cfg.detach_fraction_pressed) if pressed else float(cfg.detach_fraction_normal)
    budget = int(float(army_supply) * fraction)
    budget = max(int(cfg.detach_min_supply), min(int(cfg.detach_max_supply), budget))
    # Se exército muito pequeno, não destacar nada
    if int(army_supply) <= int(cfg.hold_nat_min_supply):
        budget = 0
    return int(budget)


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def derive_army_posture_intel(
    bot,
    *,
    awareness: Awareness,
    now: float,
    cfg: ArmyPostureIntelConfig = ArmyPostureIntelConfig(),
) -> None:
    """
    Sintetiza percepções e deriva a postura operacional do exército.

    Fonte primária: OperationalGeometryIntel (FrontTemplate → ArmyPosture).
    Fallback: lógica legada baseada em frontline + rush + parity.

    Deve ser chamado APÓS operational_geometry_intel no pipeline.
    """
    army_supply = _army_supply(bot)
    parity_score = _parity_score(awareness, now)
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()

    # --- Lê frontline para anchor e fallback ---
    nat_snap = awareness.mem.get(K("intel", "frontline", "nat", "snapshot"), now=now, default={}) or {}
    main_snap = awareness.mem.get(K("intel", "frontline", "main", "snapshot"), now=now, default={}) or {}
    if not isinstance(nat_snap, dict):
        nat_snap = {}
    if not isinstance(main_snap, dict):
        main_snap = {}

    nat_ground_state = str(nat_snap.get("ground_state", "CLEAR") or "CLEAR").upper()
    nat_control_state = str(nat_snap.get("control_state", "UNKNOWN") or "UNKNOWN").upper()
    nat_has_th = bool(nat_snap.get("has_townhall", False))
    nat_retake_viable = bool(nat_snap.get("retake_viable", False))
    nat_forward_anchor = _point_from_payload(nat_snap.get("forward_anchor"))
    nat_fallback_anchor = _point_from_payload(nat_snap.get("fallback_anchor"))
    nat_center = _point_from_payload(nat_snap.get("center"))
    main_ground_state = str(main_snap.get("ground_state", "CLEAR") or "CLEAR").upper()
    main_fallback_anchor = _point_from_payload(main_snap.get("fallback_anchor"))
    main_shielded_by_nat = bool(
        awareness.mem.get(K("intel", "frontline", "main_shielded_by_nat"), now=now, default=False)
    )

    mc_snap = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
    if not isinstance(mc_snap, dict):
        mc_snap = {}
    nat_taken = bool(mc_snap.get("nat_taken", False))
    nat_offsite = bool(mc_snap.get("nat_offsite", False))
    bases_now = int(mc_snap.get("bases_now", 0) or 0)

    # --- Postura: fonte primária é a geometria operacional ---
    geo_snap = awareness.mem.get(K("intel", "geometry", "operational", "snapshot"), now=now, default=None)
    use_geometry = isinstance(geo_snap, dict) and geo_snap

    if use_geometry:
        posture = _posture_from_geometry(awareness, now)
        # Anchor: lê o bulk_anchor_pos da geometria operacional
        bulk_anchor_payload = geo_snap.get("bulk_anchor_pos")
        anchor_from_geo = _point_from_payload(bulk_anchor_payload) if isinstance(bulk_anchor_payload, dict) else None
        max_detach_supply = int(geo_snap.get("max_detach_supply", 8) or 8)
    else:
        # Fallback legado
        posture = _derive_posture(
            army_supply=army_supply,
            parity_score=parity_score,
            rush_state=rush_state,
            nat_ground_state=nat_ground_state,
            nat_control_state=nat_control_state,
            main_ground_state=main_ground_state,
            main_shielded_by_nat=main_shielded_by_nat,
            nat_has_th=nat_has_th,
            nat_retake_viable=nat_retake_viable,
            nat_taken=nat_taken,
            bases_now=bases_now,
            cfg=cfg,
        )
        anchor_from_geo = None
        max_detach_supply = _derive_detach_budget(posture=posture, army_supply=army_supply, cfg=cfg)

    main_pos = bot.start_location

    # Anchor: prefere geometria, fallback para lógica legada
    if anchor_from_geo is not None:
        anchor = anchor_from_geo
    else:
        anchor = _derive_anchor(
            posture=posture,
            nat_forward_anchor=nat_forward_anchor,
            nat_fallback_anchor=nat_fallback_anchor,
            main_fallback_anchor=main_fallback_anchor,
            nat_center=nat_center,
            main_pos=main_pos,
        )

    # secondary_anchor
    secondary_anchor: Point2 | None = None
    if posture in {ArmyPosture.HOLD_NAT_CHOKE, ArmyPosture.SECURE_NAT, ArmyPosture.CONTROLLED_RETAKE}:
        secondary_anchor = nat_fallback_anchor or main_fallback_anchor
    elif posture == ArmyPosture.PRESS_FORWARD:
        secondary_anchor = nat_center or nat_forward_anchor

    min_bulk_supply = max(0, int(army_supply) - int(max_detach_supply))

    defense_overflow = bool(
        awareness.mem.get(K("strategy", "army", "defense_overflow"), now=now, default=False)
    )

    snapshot = {
        "updated_at": float(now),
        "posture": posture.value,
        "anchor": _point_payload(anchor),
        "secondary_anchor": _point_payload(secondary_anchor),
        "army_supply": int(army_supply),
        "min_bulk_supply": int(min_bulk_supply),
        "max_detach_supply": int(max_detach_supply),
        "parity_score": float(round(parity_score, 3)),
        "rush_state": str(rush_state),
        "nat_ground_state": str(nat_ground_state),
        "nat_control_state": str(nat_control_state),
        "main_ground_state": str(main_ground_state),
        "main_shielded_by_nat": bool(main_shielded_by_nat),
        "nat_taken": bool(nat_taken),
        "nat_offsite": bool(nat_offsite),
        "defense_overflow": bool(defense_overflow),
        "source": "geometry" if use_geometry else "legacy",
    }

    awareness.mem.set(K("strategy", "army", "posture"), value=posture.value, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "army", "anchor"), value=_point_payload(anchor), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "army", "secondary_anchor"), value=_point_payload(secondary_anchor), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "army", "max_detach_supply"), value=int(max_detach_supply), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "army", "min_bulk_supply"), value=int(min_bulk_supply), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "army", "snapshot"), value=snapshot, now=now, ttl=float(cfg.ttl_s))
