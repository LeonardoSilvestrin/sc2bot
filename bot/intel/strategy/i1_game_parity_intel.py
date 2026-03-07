from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.intel.utils.enemy_econ_estimates import count_enemy_bases, expected_workers, sum_units
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K


@dataclass(frozen=True)
class GameParityIntelConfig:
    ttl_s: float = 15.0
    ema_alpha: float = 0.22
    max_enemy_workers_assumed: int = 85
    expected_worker_period_s: float = 12.0
    enemy_awareness_power_blend: float = 0.40
    army_behind_norm: float = 22.0
    army_ahead_norm: float = 22.0
    econ_behind_norm: float = 18.0
    econ_ahead_norm: float = 18.0
    parity_state_trigger: float = 0.32
    delayed_natural_alarm_at_s: float = 300.0
    delayed_natural_pressure_urgency_high: int = 18


_WORKER_TYPES: Tuple[U, ...] = (U.SCV, U.PROBE, U.DRONE)
_ARMY_WEIGHTS: Dict[U, float] = {
    U.MARINE: 1.0,
    U.MARAUDER: 1.8,
    U.REAPER: 1.6,
    U.HELLION: 1.4,
    U.CYCLONE: 3.6,
    U.SIEGETANK: 5.4,
    U.MEDIVAC: 2.6,
    U.VIKINGFIGHTER: 2.8,
    U.BANSHEE: 3.5,
    U.RAVEN: 2.8,
    U.LIBERATOR: 3.8,
    U.BATTLECRUISER: 8.0,
    U.ZERGLING: 0.45,
    U.ROACH: 1.6,
    U.RAVAGER: 2.1,
    U.HYDRALISK: 1.7,
    U.BANELING: 1.0,
    U.MUTALISK: 2.0,
    U.CORRUPTOR: 2.6,
    U.ULTRALISK: 6.5,
    U.BROODLORD: 5.8,
    U.QUEEN: 1.8,
    U.ZEALOT: 1.2,
    U.STALKER: 2.2,
    U.ADEPT: 1.7,
    U.SENTRY: 1.8,
    U.IMMORTAL: 4.1,
    U.COLOSSUS: 6.0,
    U.DISRUPTOR: 5.3,
    U.HIGHTEMPLAR: 2.4,
    U.ARCHON: 4.4,
    U.DARKTEMPLAR: 3.0,
    U.PHOENIX: 2.2,
    U.VOIDRAY: 3.6,
    U.CARRIER: 7.8,
    U.TEMPEST: 6.2,
    U.ORACLE: 2.8,
}
def _army_power(units: Dict[U, int]) -> float:
    p = 0.0
    for uid, count in units.items():
        n = int(count)
        if n <= 0:
            continue
        p += float(_ARMY_WEIGHTS.get(uid, 1.0)) * float(n)
    return float(p)


def _army_power_from_mediator_dict(*, army_dict: dict) -> float:
    if not isinstance(army_dict, dict):
        raise RuntimeError("invalid_contract:mediator.army_dict")
    p = 0.0
    for uid, units in army_dict.items():
        try:
            n = int(getattr(units, "amount", len(units)))
        except Exception:
            n = 0
        if n <= 0:
            continue
        try:
            u = U(uid) if isinstance(uid, int) else uid
        except Exception:
            u = uid
        p += float(_ARMY_WEIGHTS.get(u, 1.0)) * float(n)
    return float(p)


def _army_power_named(units: list[dict]) -> float:
    p = 0.0
    for item in units:
        if not isinstance(item, dict):
            continue
        name = str(item.get("unit", "") or "").strip().upper()
        if not name:
            continue
        try:
            uid = getattr(U, name)
        except Exception:
            uid = None
        try:
            n = int(item.get("count", 0) or 0)
        except Exception:
            n = 0
        if uid is None or n <= 0:
            continue
        p += float(_ARMY_WEIGHTS.get(uid, 1.0)) * float(n)
    return float(p)


def _ema(*, prev: float, cur: float, alpha: float) -> float:
    a = max(0.01, min(1.0, float(alpha)))
    return (float(prev) * (1.0 - a)) + (float(cur) * a)


def _state(v: float, *, low: float, high: float) -> str:
    if float(v) <= float(low):
        return "BEHIND"
    if float(v) >= float(high):
        return "AHEAD"
    return "EVEN"


def _parity_state(*, army_delta: float, econ_delta: float, cfg: GameParityIntelConfig) -> str:
    army_behind = max(0.0, min(1.0, (0.0 - float(army_delta)) / max(1e-6, float(cfg.army_behind_norm))))
    army_ahead = max(0.0, min(1.0, float(army_delta) / max(1e-6, float(cfg.army_ahead_norm))))
    econ_behind = max(0.0, min(1.0, (0.0 - float(econ_delta)) / max(1e-6, float(cfg.econ_behind_norm))))
    econ_ahead = max(0.0, min(1.0, float(econ_delta) / max(1e-6, float(cfg.econ_ahead_norm))))
    thr = max(0.05, min(0.9, float(cfg.parity_state_trigger)))
    if army_ahead >= thr and econ_behind >= thr:
        return "AHEAD_ARMY_BEHIND_ECON"
    if army_behind >= thr and econ_ahead >= thr:
        return "BEHIND_ARMY_AHEAD_ECON"
    if army_ahead >= thr and econ_ahead >= thr:
        return "AHEAD_BOTH"
    if army_behind >= thr and econ_behind >= thr:
        return "BEHIND_BOTH"
    return "TRADEOFF_MIXED"


def derive_game_parity_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: GameParityIntelConfig = GameParityIntelConfig(),
) -> None:
    if not hasattr(bot, "mediator"):
        raise RuntimeError("missing_contract:mediator")
    own_army_dict = getattr(bot.mediator, "get_own_army_dict", None)
    enemy_army_dict = getattr(bot.mediator, "get_enemy_army_dict", None)
    if own_army_dict is None:
        raise RuntimeError("missing_contract:mediator.get_own_army_dict")
    if enemy_army_dict is None:
        raise RuntimeError("missing_contract:mediator.get_enemy_army_dict")
    if not isinstance(own_army_dict, dict):
        raise RuntimeError("invalid_contract:mediator.get_own_army_dict")
    if not isinstance(enemy_army_dict, dict):
        raise RuntimeError("invalid_contract:mediator.get_enemy_army_dict")

    enemy_units = dict(attention.enemy_build.enemy_units or {})
    enemy_structs = dict(attention.enemy_build.enemy_structures or {})

    own_workers = int(attention.economy.workers_total)
    own_bases = int(attention.macro.bases_total)
    own_army_power = float(_army_power_from_mediator_dict(army_dict=own_army_dict))
    our_bases_registry = awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
    if not isinstance(our_bases_registry, dict):
        our_bases_registry = {}
    nat_entry = dict(our_bases_registry.get("NATURAL", {})) if isinstance(our_bases_registry.get("NATURAL", {}), dict) else {}
    nat_state = str(nat_entry.get("state", "PLANNED") or "PLANNED").upper()
    nat_flying = bool(nat_entry.get("is_flying", False))
    nat_taken = bool(nat_state in {"ESTABLISHED", "LANDED_UNSAFE", "SECURING"} and not nat_flying)
    pressure_level = int(awareness.mem.get(K("control", "pressure", "level"), now=now, default=1) or 1)
    pressure_high = bool(
        int(pressure_level) >= 3
        or int(getattr(attention.combat, "primary_urgency", 0) or 0) >= int(cfg.delayed_natural_pressure_urgency_high)
    )
    delayed_natural_alarm = bool(
        float(now) >= float(cfg.delayed_natural_alarm_at_s)
        and int(own_bases) < 2
        and not bool(nat_taken)
        and not bool(pressure_high)
    )

    enemy_workers_seen = int(sum_units(enemy_units, _WORKER_TYPES))
    enemy_bases_seen = int(count_enemy_bases(enemy_structs))
    enemy_army_seen_power = float(_army_power_from_mediator_dict(army_dict=enemy_army_dict))
    army_summary = awareness.mem.get(K("enemy", "army", "comp_summary"), now=now, default={}) or {}
    if not isinstance(army_summary, dict):
        army_summary = {}
    enemy_aw_top = list(army_summary.get("top_units", [])) if isinstance(army_summary.get("top_units", []), list) else []
    enemy_aw_main_top = (
        list(army_summary.get("top_units_main", []))
        if isinstance(army_summary.get("top_units_main", []), list)
        else []
    )
    enemy_army_aw_power = max(
        float(_army_power_named(enemy_aw_top)),
        float(_army_power_named(enemy_aw_main_top)),
    )
    blend = max(0.0, min(1.0, float(cfg.enemy_awareness_power_blend)))
    enemy_army_obs_power = max(
        float(enemy_army_seen_power),
        ((1.0 - blend) * float(enemy_army_seen_power)) + (blend * float(enemy_army_aw_power)),
    )

    expected_workers_now = expected_workers(
        float(now),
        period_s=float(cfg.expected_worker_period_s),
        cap=int(cfg.max_enemy_workers_assumed),
    )
    enemy_workers_now = max(int(enemy_workers_seen), int(expected_workers_now))
    enemy_bases_now = max(int(enemy_bases_seen), 1)

    prev_workers_est = float(
        awareness.mem.get(
            K("enemy", "parity", "workers_est"),
            now=now,
            default=float(enemy_workers_now),
        )
        or float(enemy_workers_now)
    )
    prev_bases_est = float(
        awareness.mem.get(
            K("enemy", "parity", "bases_est"),
            now=now,
            default=float(enemy_bases_now),
        )
        or float(enemy_bases_now)
    )
    prev_army_est = float(
        awareness.mem.get(
            K("enemy", "parity", "army_power_est"),
            now=now,
            default=float(enemy_army_obs_power),
        )
        or float(enemy_army_obs_power)
    )

    enemy_workers_est = max(float(enemy_workers_now), _ema(prev=prev_workers_est, cur=float(enemy_workers_now), alpha=float(cfg.ema_alpha)))
    enemy_bases_est = max(float(enemy_bases_now), _ema(prev=prev_bases_est, cur=float(enemy_bases_now), alpha=float(cfg.ema_alpha)))
    enemy_army_est = max(
        float(enemy_army_obs_power),
        _ema(prev=prev_army_est, cur=float(enemy_army_obs_power), alpha=float(cfg.ema_alpha)),
    )

    econ_delta = (float(own_workers) - float(enemy_workers_est)) + (float(own_bases) - float(enemy_bases_est)) * 7.0
    army_delta = float(own_army_power) - float(enemy_army_est)
    overall_delta = (0.45 * float(econ_delta)) + (0.55 * float(army_delta))

    econ_state = _state(econ_delta, low=-6.0, high=6.0)
    army_state = _state(army_delta, low=-8.0, high=8.0)
    overall_state = _state(overall_delta, low=-6.0, high=6.0)

    expand_bias = 0
    army_bias = 0
    if overall_state == "AHEAD":
        expand_bias = 1
    elif overall_state == "BEHIND":
        army_bias = 1

    if econ_state == "BEHIND":
        expand_bias = 0
        army_bias = max(army_bias, 1)
    if army_state == "AHEAD" and econ_state != "BEHIND":
        expand_bias = max(expand_bias, 1)
    if army_state == "BEHIND":
        army_bias = max(army_bias, 1)
        expand_bias = 0

    rush_state = str(awareness.mem.get(K("enemy", "rush", "state"), now=now, default="NONE") or "NONE").upper()
    aggression_state = str(awareness.mem.get(K("enemy", "aggression", "state"), now=now, default="NONE") or "NONE").upper()
    aggression_source = awareness.mem.get(K("enemy", "aggression", "source"), now=now, default={}) or {}
    if not isinstance(aggression_source, dict):
        aggression_source = {}
    rush_is_early = bool(aggression_source.get("rush_is_early", False))
    if (rush_is_early and rush_state in {"SUSPECTED", "CONFIRMED", "HOLDING"}) or aggression_state == "AGGRESSION":
        army_bias = max(army_bias, 1)
        expand_bias = 0
    if delayed_natural_alarm:
        expand_bias = max(expand_bias, 2)

    army_behind_severity = max(0.0, min(1.0, (0.0 - float(army_delta)) / max(1e-6, float(cfg.army_behind_norm))))
    army_ahead_severity = max(0.0, min(1.0, float(army_delta) / max(1e-6, float(cfg.army_ahead_norm))))
    econ_behind_severity = max(0.0, min(1.0, (0.0 - float(econ_delta)) / max(1e-6, float(cfg.econ_behind_norm))))
    econ_ahead_severity = max(0.0, min(1.0, float(econ_delta) / max(1e-6, float(cfg.econ_ahead_norm))))
    parity_state = _parity_state(army_delta=float(army_delta), econ_delta=float(econ_delta), cfg=cfg)

    payload = {
        "overall": str(overall_state),
        "econ": str(econ_state),
        "army": str(army_state),
        "overall_delta": float(round(overall_delta, 2)),
        "econ_delta": float(round(econ_delta, 2)),
        "army_delta": float(round(army_delta, 2)),
        "own_workers": int(own_workers),
        "enemy_workers_est": int(round(enemy_workers_est)),
        "own_bases": int(own_bases),
        "enemy_bases_est": int(round(enemy_bases_est)),
        "own_army_power": float(round(own_army_power, 2)),
        "enemy_army_power_est": float(round(enemy_army_est, 2)),
        "enemy_workers_seen": int(enemy_workers_seen),
        "enemy_bases_seen": int(enemy_bases_seen),
        "enemy_army_power_seen": float(round(enemy_army_seen_power, 2)),
        "enemy_army_power_awareness": float(round(enemy_army_aw_power, 2)),
        "enemy_army_power_observed": float(round(enemy_army_obs_power, 2)),
        "army_behind_severity": float(round(army_behind_severity, 3)),
        "army_ahead_severity": float(round(army_ahead_severity, 3)),
        "econ_behind_severity": float(round(econ_behind_severity, 3)),
        "econ_ahead_severity": float(round(econ_ahead_severity, 3)),
        "parity_state": str(parity_state),
        "expand_bias": int(expand_bias),
        "army_bias": int(army_bias),
        "rush_state": str(rush_state),
        "aggression_state": str(aggression_state),
        "nat_taken": bool(nat_taken),
        "pressure_high": bool(pressure_high),
        "delayed_natural_alarm": bool(delayed_natural_alarm),
    }

    awareness.mem.set(K("enemy", "parity", "workers_est"), value=float(enemy_workers_est), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "parity", "bases_est"), value=float(enemy_bases_est), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "parity", "army_power_est"), value=float(enemy_army_est), now=now, ttl=float(cfg.ttl_s))

    awareness.mem.set(K("strategy", "parity", "overall"), value=str(overall_state), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "parity", "econ"), value=str(econ_state), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "parity", "army"), value=str(army_state), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "parity", "expand_bias"), value=int(expand_bias), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "parity", "army_bias"), value=int(army_bias), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(
        K("strategy", "parity", "severity", "army_behind"),
        value=float(army_behind_severity),
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(
        K("strategy", "parity", "severity", "army_ahead"),
        value=float(army_ahead_severity),
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(
        K("strategy", "parity", "severity", "econ_behind"),
        value=float(econ_behind_severity),
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(
        K("strategy", "parity", "severity", "econ_ahead"),
        value=float(econ_ahead_severity),
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(K("strategy", "parity", "state"), value=str(parity_state), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(
        K("strategy", "parity", "alarms", "delayed_natural"),
        value=bool(delayed_natural_alarm),
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(K("strategy", "parity", "signals"), value=dict(payload), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("strategy", "parity", "last_update_t"), value=float(now), now=now, ttl=None)
