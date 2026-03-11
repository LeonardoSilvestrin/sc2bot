"""
Frontline Intel — modelagem explícita de frentes terrestres.

Responsabilidade: OBSERVAR o estado espacial de cada frente, não decidir postura.

Produz por frente (NAT_FRONT, MAIN_FRONT):
    - ground_state: estado do terreno (CLEAR / CONTESTED / COMPROMISED / LOST)
    - control_state: quem controla a frente (OURS / NEUTRAL / ENEMY / UNKNOWN)
    - fallback_anchor: posição defensável para recuo
    - forward_anchor: posição avançada da frente
    - retake_viable: bool — retomada parece viável
    - main_shielded_by_nat: a main está coberta porque a nat segura o acesso terrestre

Não decide se o exército deve ir para lá — isso é responsabilidade de army_posture_intel.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.intel.utils.natural_geometry import sanitize_natural_defense_point
from bot.mind.awareness import Awareness, K


# ---------------------------------------------------------------------------
# Enums de estado
# ---------------------------------------------------------------------------

class GroundState(str, Enum):
    """Estado do terreno/ground na frente."""
    CLEAR = "CLEAR"               # Sem inimigos próximos
    CONTESTED = "CONTESTED"       # Presença inimiga, mas não dominante
    COMPROMISED = "COMPROMISED"   # Inimigo claramente presente e forte
    LOST = "LOST"                 # Frente perdida / base destruída


class ControlState(str, Enum):
    """Quem controla a frente."""
    OURS = "OURS"
    NEUTRAL = "NEUTRAL"
    ENEMY = "ENEMY"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Tipos de dados
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FrontlineIntelConfig:
    ttl_s: float = 6.0
    contested_power_threshold: float = 1.0    # inimigo acima disso = CONTESTED
    compromised_power_threshold: float = 2.5  # inimigo acima disso = COMPROMISED
    lost_power_threshold: float = 5.0         # inimigo acima disso = LOST
    retake_viable_max_enemy_power: float = 3.0
    retake_viable_min_own_power: float = 4.0
    nat_radius: float = 18.0
    main_radius: float = 18.0
    # Distância máxima do choke da nat para considerar que a main está shielded
    nat_choke_shield_max_dist: float = 35.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_WORKER_TYPES = {U.SCV, U.PROBE, U.DRONE, U.MULE, U.LARVA, U.EGG}

_ENEMY_WEIGHTS = {
    U.ZERGLING: 0.55,
    U.BANELING: 0.9,
    U.ROACH: 1.7,
    U.RAVAGER: 2.2,
    U.HYDRALISK: 1.5,
    U.MARINE: 1.0,
    U.MARAUDER: 1.45,
    U.REAPER: 1.25,
    U.HELLION: 1.0,
    U.CYCLONE: 1.8,
    U.SIEGETANK: 3.0,
    U.SIEGETANKSIEGED: 4.5,
    U.ZEALOT: 1.3,
    U.ADEPT: 1.35,
    U.STALKER: 1.8,
    U.IMMORTAL: 3.0,
    U.PHOTONCANNON: 3.6,
    U.SPINECRAWLER: 3.6,
    U.BUNKER: 4.0,
}

_OWN_WEIGHTS = {
    U.SIEGETANK: 3.0,
    U.SIEGETANKSIEGED: 4.5,
    U.WIDOWMINE: 2.0,
    U.WIDOWMINEBURROWED: 3.2,
    U.CYCLONE: 1.5,
    U.MARAUDER: 1.35,
    U.MARINE: 1.0,
    U.HELLION: 0.85,
    U.THOR: 3.2,
    U.THORAP: 3.2,
    U.MEDIVAC: 0.6,
    U.BUNKER: 4.0,
    U.PLANETARYFORTRESS: 6.0,
}


def _enemy_power_near(bot, *, center: Point2, radius: float) -> float:
    total = 0.0
    for unit in list(getattr(bot, "enemy_units", []) or []):
        try:
            if unit.type_id in _WORKER_TYPES:
                continue
            if float(unit.distance_to(center)) <= float(radius):
                total += float(_ENEMY_WEIGHTS.get(unit.type_id, 1.0))
        except Exception:
            continue
    for struct in list(getattr(bot, "enemy_structures", []) or []):
        try:
            if struct.type_id in _WORKER_TYPES:
                continue
            if struct.type_id in {U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS,
                                   U.HATCHERY, U.LAIR, U.HIVE, U.NEXUS}:
                continue
            if float(struct.distance_to(center)) <= float(radius):
                total += float(_ENEMY_WEIGHTS.get(struct.type_id, 0.5))
        except Exception:
            continue
    return float(total)


def _own_power_near(bot, *, center: Point2, radius: float) -> float:
    total = 0.0
    for unit in list(getattr(bot, "units", []) or []):
        try:
            w = float(_OWN_WEIGHTS.get(unit.type_id, 0.0))
            if w <= 0.0:
                continue
            if not bool(getattr(unit, "is_ready", True)):
                continue
            if float(unit.distance_to(center)) <= float(radius):
                total += w
        except Exception:
            continue
    for struct in list(getattr(bot, "structures", []) or []):
        try:
            w = float(_OWN_WEIGHTS.get(struct.type_id, 0.0))
            if w <= 0.0:
                continue
            if float(struct.distance_to(center)) <= float(radius):
                total += w
        except Exception:
            continue
    return float(total)


def _pathable(bot, pos: Point2) -> bool:
    try:
        return bool(bot.in_pathing_grid(pos))
    except Exception:
        return True


def _point_payload(pos: Point2 | None) -> dict | None:
    if pos is None:
        return None
    return {"x": float(pos.x), "y": float(pos.y)}


def _our_natural(bot) -> Point2 | None:
    try:
        return bot.mediator.get_own_nat
    except Exception:
        pass
    exps = list(getattr(bot, "expansion_locations_list", []) or [])
    if not exps:
        return None
    try:
        ordered = sorted(
            [p for p in exps if float(p.distance_to(bot.start_location)) > 2.0],
            key=lambda p: float(bot.start_location.distance_to(p)),
        )
    except Exception:
        ordered = exps
    return ordered[0] if ordered else None


def _nat_choke_pos(bot, *, nat: Point2, enemy_main: Point2) -> Point2:
    """
    Posição defensável no choke da natural.
    Usa ramp bottom se disponível, senão heurística geométrica menos ruim que 'towards X 4.5'.
    """
    try:
        ramp = getattr(bot, "main_base_ramp", None)
        if ramp is not None:
            bottom = getattr(ramp, "bottom_center", None)
            if bottom is not None and float(bottom.distance_to(nat)) <= 20.0:
                # Escalar para frente do choke, mas garantir pathable
                candidate = bottom.towards(enemy_main, 1.5)
                if _pathable(bot, candidate):
                    return sanitize_natural_defense_point(
                        bot,
                        pos=candidate,
                        fallback=nat.towards(enemy_main, 5.5),
                        prefer_towards=nat.towards(enemy_main, 6.5),
                        nat=nat,
                    )
    except Exception:
        pass
    # Fallback geométrico: frente da nat em direção ao inimigo
    candidate = nat.towards(enemy_main, 5.5)
    if _pathable(bot, candidate):
        return sanitize_natural_defense_point(
            bot,
            pos=candidate,
            fallback=nat,
            prefer_towards=nat.towards(enemy_main, 6.5),
            nat=nat,
        )
    return nat


def _nat_fallback_anchor(bot, *, nat: Point2) -> Point2:
    """
    Posição de fallback segura — entre a nat e a main, em highground se possível.
    """
    try:
        ramp = getattr(bot, "main_base_ramp", None)
        if ramp is not None:
            top = getattr(ramp, "top_center", None)
            if top is not None:
                candidate = top.towards(nat, 2.0)
                if _pathable(bot, candidate):
                    return sanitize_natural_defense_point(
                        bot,
                        pos=candidate,
                        fallback=top,
                        prefer_towards=bot.start_location,
                        nat=nat,
                    )
    except Exception:
        pass
    return sanitize_natural_defense_point(
        bot,
        pos=nat.towards(bot.start_location, 5.0),
        fallback=bot.start_location,
        prefer_towards=bot.start_location,
        nat=nat,
    )


def _main_fallback_anchor(bot) -> Point2:
    """Anchor da main — atrás da wall, alguns tiles dentro da main.
    Não pode ser o top_center diretamente pois coloca unidades em cima dos depots.
    """
    try:
        ramp = getattr(bot, "main_base_ramp", None)
        if ramp is not None:
            top = getattr(ramp, "top_center", None)
            if top is not None:
                # Recua 4.5 tiles para dentro da main — atrás da wall,
                # mas próximo o suficiente para cobrir a rampa
                return top.towards(bot.start_location, 4.5)
    except Exception:
        pass
    return bot.start_location


def _nat_exists(bot, *, nat: Point2) -> bool:
    """Verifica se ainda há townhall na nat."""
    for th in list(getattr(bot, "townhalls", []) or []):
        try:
            if float(th.distance_to(nat)) <= 8.0:
                return True
        except Exception:
            continue
    return False


def _ground_state_from_power(enemy_power: float, *, cfg: FrontlineIntelConfig) -> GroundState:
    if enemy_power >= float(cfg.lost_power_threshold):
        return GroundState.LOST
    if enemy_power >= float(cfg.compromised_power_threshold):
        return GroundState.COMPROMISED
    if enemy_power >= float(cfg.contested_power_threshold):
        return GroundState.CONTESTED
    return GroundState.CLEAR


def _control_state(
    enemy_power: float,
    own_power: float,
    *,
    cfg: FrontlineIntelConfig,
) -> ControlState:
    if enemy_power <= 0.2 and own_power >= float(cfg.retake_viable_min_own_power):
        return ControlState.OURS
    if enemy_power >= float(cfg.compromised_power_threshold) and enemy_power > own_power * 1.3:
        return ControlState.ENEMY
    if enemy_power <= 0.2 and own_power <= 0.5:
        return ControlState.UNKNOWN
    return ControlState.NEUTRAL


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def derive_frontline_intel(
    bot,
    *,
    awareness: Awareness,
    now: float,
    cfg: FrontlineIntelConfig = FrontlineIntelConfig(),
) -> None:
    """
    Deriva o estado de cada frente terrestre e persiste em awareness.

    Chaves escritas:
        K("intel", "frontline", "nat", "snapshot")
        K("intel", "frontline", "main", "snapshot")
        K("intel", "frontline", "main_shielded_by_nat")
    """
    nat = _our_natural(bot)
    if nat is None:
        return

    try:
        enemy_main = bot.enemy_start_locations[0]
    except Exception:
        enemy_main = nat

    main_pos = bot.start_location

    # --- NAT FRONT ---
    nat_enemy_power = _enemy_power_near(bot, center=nat, radius=float(cfg.nat_radius))
    nat_own_power = _own_power_near(bot, center=nat, radius=float(cfg.nat_radius))
    nat_ground_state = _ground_state_from_power(nat_enemy_power, cfg=cfg)
    nat_control_state = _control_state(nat_enemy_power, nat_own_power, cfg=cfg)
    nat_has_th = _nat_exists(bot, nat=nat)

    nat_forward_anchor = _nat_choke_pos(bot, nat=nat, enemy_main=enemy_main)
    nat_fallback_anchor = _nat_fallback_anchor(bot, nat=nat)

    nat_retake_viable = bool(
        nat_ground_state != GroundState.LOST
        and float(nat_enemy_power) <= float(cfg.retake_viable_max_enemy_power)
        and float(nat_own_power) >= float(cfg.retake_viable_min_own_power)
    )

    nat_snapshot = {
        "updated_at": float(now),
        "label": "NAT_FRONT",
        "ground_state": nat_ground_state.value,
        "control_state": nat_control_state.value,
        "enemy_power": float(round(nat_enemy_power, 3)),
        "own_power": float(round(nat_own_power, 3)),
        "has_townhall": bool(nat_has_th),
        "retake_viable": bool(nat_retake_viable),
        "forward_anchor": _point_payload(nat_forward_anchor),
        "fallback_anchor": _point_payload(nat_fallback_anchor),
        "center": _point_payload(nat),
    }

    # --- MAIN FRONT ---
    main_enemy_power = _enemy_power_near(bot, center=main_pos, radius=float(cfg.main_radius))
    main_own_power = _own_power_near(bot, center=main_pos, radius=float(cfg.main_radius))
    main_ground_state = _ground_state_from_power(main_enemy_power, cfg=cfg)
    main_control_state = _control_state(main_enemy_power, main_own_power, cfg=cfg)

    main_fallback_anchor = _main_fallback_anchor(bot)

    main_snapshot = {
        "updated_at": float(now),
        "label": "MAIN_FRONT",
        "ground_state": main_ground_state.value,
        "control_state": main_control_state.value,
        "enemy_power": float(round(main_enemy_power, 3)),
        "own_power": float(round(main_own_power, 3)),
        "retake_viable": False,  # main não tem retake — se perdeu, é GG
        "forward_anchor": _point_payload(nat_forward_anchor),  # main avança até o choke da nat
        "fallback_anchor": _point_payload(main_fallback_anchor),
        "center": _point_payload(main_pos),
    }

    # --- main_shielded_by_nat ---
    # A main está coberta se a nat está CLEAR ou CONTESTED e tem unidades lá
    # E a nat fica entre a main e o inimigo (geometria)
    nat_dist_to_main = float(nat.distance_to(main_pos))
    nat_dist_to_enemy = float(nat.distance_to(enemy_main))
    main_dist_to_enemy = float(main_pos.distance_to(enemy_main))
    nat_is_between = bool(nat_dist_to_enemy < main_dist_to_enemy and nat_dist_to_main <= float(cfg.nat_choke_shield_max_dist))
    main_shielded_by_nat = bool(
        nat_is_between
        and nat_ground_state in {GroundState.CLEAR, GroundState.CONTESTED}
        and nat_control_state in {ControlState.OURS, ControlState.NEUTRAL}
        and float(nat_own_power) >= 2.0
    )

    # Persiste
    awareness.mem.set(K("intel", "frontline", "nat", "snapshot"), value=nat_snapshot, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "frontline", "nat", "ground_state"), value=nat_ground_state.value, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "frontline", "nat", "control_state"), value=nat_control_state.value, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "frontline", "main", "snapshot"), value=main_snapshot, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "frontline", "main", "ground_state"), value=main_ground_state.value, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "frontline", "main_shielded_by_nat"), value=bool(main_shielded_by_nat), now=now, ttl=float(cfg.ttl_s))
