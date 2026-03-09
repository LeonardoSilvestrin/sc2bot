"""
WorldCompression Intel — comprime o estado do jogo em vetor compacto de sinais.

Responsabilidade:
    Transformar todas as percepções (frontline, presence, parity, rush, pathing)
    em um vetor normalizado de sinais contínuos [0..1] ou [-1..1].

    Isso elimina dezenas de flags booleanas espalhadas e cria uma única
    representação numérica do "estado do mundo" que a GeometryIntel consome.

Chaves produzidas:
    K("intel", "geometry", "world", "compression") → dict com sinais

Não decide nada. Só comprime e normaliza.
"""
from __future__ import annotations

from dataclasses import dataclass

from bot.mind.awareness import Awareness, K


@dataclass(frozen=True)
class WorldCompressionConfig:
    ttl_s: float = 4.0

    # Thresholds para pressure
    pressure_nat_light:  float = 0.8   # enemy_power acima disso → pressure leve
    pressure_nat_heavy:  float = 2.5   # acima disso → pressure pesada
    pressure_main_light: float = 0.5
    pressure_main_heavy: float = 2.0

    # Parity
    parity_floor: float = -1.0
    parity_ceil:  float = 1.0


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def _norm_pressure(enemy_power: float, *, light: float, heavy: float) -> float:
    """Normaliza power inimiga em 0..1 de forma suave."""
    if float(enemy_power) <= 0.0:
        return 0.0
    if float(enemy_power) >= float(heavy):
        return 1.0
    if float(enemy_power) >= float(light):
        frac = (float(enemy_power) - float(light)) / max(0.01, float(heavy) - float(light))
        return _clamp(0.3 + frac * 0.7)
    return _clamp(float(enemy_power) / max(0.01, float(light)) * 0.3)


def derive_world_compression(
    bot,
    *,
    awareness: Awareness,
    now: float,
    cfg: WorldCompressionConfig = WorldCompressionConfig(),
) -> None:
    """
    Deriva o vetor de compressão mundial e persiste em awareness.

    Deve ser chamado APÓS:
        - i5_frontline_intel
        - i4_enemy_presence_intel
        - i1_game_parity_intel
        - i3_map_control_intel
    """
    # --- Lê frontline ---
    nat_snap = awareness.mem.get(K("intel", "frontline", "nat", "snapshot"), now=now, default={}) or {}
    main_snap = awareness.mem.get(K("intel", "frontline", "main", "snapshot"), now=now, default={}) or {}
    if not isinstance(nat_snap, dict):
        nat_snap = {}
    if not isinstance(main_snap, dict):
        main_snap = {}

    nat_enemy_power = float(nat_snap.get("enemy_power", 0.0) or 0.0)
    nat_own_power = float(nat_snap.get("own_power", 0.0) or 0.0)
    nat_ground_state = str(nat_snap.get("ground_state", "CLEAR") or "CLEAR").upper()
    main_enemy_power = float(main_snap.get("enemy_power", 0.0) or 0.0)
    main_ground_state = str(main_snap.get("ground_state", "CLEAR") or "CLEAR").upper()

    # --- Lê parity ---
    parity_raw = float(
        awareness.mem.get(K("strategy", "parity", "army_score_norm"), now=now, default=0.0) or 0.0
    )
    army_strength_rel = _clamp(float(parity_raw), -1.0, 1.0)

    # --- Lê rush state ---
    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    rush_active = rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}
    rush_weight = {
        "NONE": 0.0,
        "SUSPECTED": 0.4,
        "CONFIRMED": 0.75,
        "HOLDING": 0.6,
    }.get(rush_state, 0.0)

    # --- Lê map control ---
    mc_snap = awareness.mem.get(K("intel", "map_control", "our_nat", "snapshot"), now=now, default={}) or {}
    if not isinstance(mc_snap, dict):
        mc_snap = {}
    nat_taken = bool(mc_snap.get("nat_taken", False))
    bases_now = int(mc_snap.get("bases_now", 0) or 0)

    # --- Lê army supply ---
    army_supply = float(getattr(bot, "supply_army", 0) or 0)

    # --- Deriva sinais ---

    # pressure_nat: combinação de enemy_power na nat + rush + ground_state
    pressure_nat_from_power = _norm_pressure(
        nat_enemy_power,
        light=float(cfg.pressure_nat_light),
        heavy=float(cfg.pressure_nat_heavy),
    )
    # Ground state amplifica a pressão
    ground_mult_nat = {
        "CLEAR": 0.5,
        "CONTESTED": 0.85,
        "COMPROMISED": 1.0,
        "LOST": 1.0,
    }.get(nat_ground_state, 0.7)
    pressure_nat = _clamp(
        max(float(pressure_nat_from_power) * float(ground_mult_nat), float(rush_weight) * 0.7)
    )

    # pressure_main
    pressure_main_from_power = _norm_pressure(
        main_enemy_power,
        light=float(cfg.pressure_main_light),
        heavy=float(cfg.pressure_main_heavy),
    )
    ground_mult_main = {
        "CLEAR": 0.5,
        "CONTESTED": 0.9,
        "COMPROMISED": 1.0,
        "LOST": 1.0,
    }.get(main_ground_state, 0.7)
    pressure_main = _clamp(float(pressure_main_from_power) * float(ground_mult_main))

    # pressure_outer: ameaça genérica no mapa (pathing)
    route_pressure = float(
        awareness.mem.get(K("enemy", "pathing", "route", "pressure_on_us"), now=now, default=0) or 0
    )
    pressure_outer = _clamp(float(route_pressure) / 10.0)

    # expansion_commit: quão comprometidos em expandir
    # Alta quando nat tomada, baixa quando sob pressão
    if not nat_taken and int(bases_now) < 2:
        expansion_commit = _clamp(0.3 - float(pressure_nat) * 0.4)
    elif nat_taken and int(bases_now) >= 2:
        expansion_commit = _clamp(0.7 - float(pressure_nat) * 0.5)
    else:
        expansion_commit = _clamp(0.5 - float(pressure_nat) * 0.4)

    # push_commit: quão prontos para atacar
    # Alta quando parity forte e nat segura
    if float(army_strength_rel) > 0.3 and float(pressure_nat) < 0.3 and nat_taken:
        push_commit = _clamp((float(army_strength_rel) - 0.3) / 0.7 * float(army_supply) / 20.0)
    else:
        push_commit = 0.0

    # mobility_need: necessidade de mobilidade (vs. ficar anchored)
    # Alta quando há múltiplas ameaças simultâneas ou drop risk
    mobility_need = _clamp(
        float(pressure_outer) * 0.5 + (0.2 if float(pressure_nat) > 0.3 and float(pressure_main) > 0.2 else 0.0)
    )

    # map_presence_need: quanto queremos presença no mapa exterior
    # Alta quando estamos ahead e nat está segura
    if float(army_strength_rel) > 0.2 and float(pressure_nat) < 0.25 and nat_taken:
        map_presence_need = _clamp(float(army_strength_rel) * 0.6 + (0.2 if float(bases_now) >= 2 else 0.0))
    else:
        map_presence_need = _clamp(float(army_strength_rel) * 0.1)

    # drop_risk / air_risk: por agora placeholders baseados em enemy presence
    # Serão refinados quando houver detecção de drops
    drop_risk = 0.0
    air_risk = 0.0

    compression = {
        "updated_at":       float(now),
        "pressure_main":    round(float(pressure_main), 3),
        "pressure_nat":     round(float(pressure_nat), 3),
        "pressure_outer":   round(float(pressure_outer), 3),
        "expansion_commit": round(float(expansion_commit), 3),
        "push_commit":      round(float(push_commit), 3),
        "mobility_need":    round(float(mobility_need), 3),
        "map_presence_need": round(float(map_presence_need), 3),
        "army_strength_rel": round(float(army_strength_rel), 3),
        "drop_risk":        round(float(drop_risk), 3),
        "air_risk":         round(float(air_risk), 3),
        # Signals derivados para facilitar leitura
        "rush_active":      bool(rush_active),
        "nat_taken":        bool(nat_taken),
        "bases_now":        int(bases_now),
        "army_supply":      int(army_supply),
        "nat_ground_state": str(nat_ground_state),
        "main_ground_state": str(main_ground_state),
    }

    awareness.mem.set(
        K("intel", "geometry", "world", "compression"),
        value=compression,
        now=now,
        ttl=float(cfg.ttl_s),
    )
