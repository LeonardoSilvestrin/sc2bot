from __future__ import annotations

from dataclasses import dataclass

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K


@dataclass(frozen=True)
class MissionValueIntelConfig:
    ttl_s: float = 10.0
    conservative_army_fraction_at: float = 0.45
    very_conservative_army_fraction_at: float = 0.70


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _mission_domain_gain(domain: str) -> float:
    d = str(domain).upper()
    if d == "DEFENSE":
        return 0.85
    if d == "HARASS":
        return 0.62
    if d == "INTEL":
        return 0.48
    if d.startswith("MACRO"):
        return 0.55
    return 0.50


def derive_mission_value_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: MissionValueIntelConfig = MissionValueIntelConfig(),
) -> None:
    if not hasattr(bot, "mediator"):
        raise RuntimeError("missing_contract:mediator")
    own_army_dict = getattr(bot.mediator, "get_own_army_dict", None)
    if own_army_dict is None:
        raise RuntimeError("missing_contract:mediator.get_own_army_dict")
    if not isinstance(own_army_dict, dict):
        raise RuntimeError("invalid_contract:mediator.get_own_army_dict")

    total_army_units = 0
    for units in own_army_dict.values():
        try:
            total_army_units += int(getattr(units, "amount", len(units)))
        except Exception:
            continue
    total_army_units = max(1, int(total_army_units))

    pressure_on_us = int(awareness.mem.get(K("enemy", "pathing", "route", "pressure_on_us"), now=now, default=0) or 0)
    route_tags = awareness.mem.get(K("enemy", "pathing", "route", "tags"), now=now, default=[]) or []
    if not isinstance(route_tags, list):
        route_tags = []
    route_tags = {str(x) for x in route_tags}
    threat_urgency = int(attention.combat.primary_urgency)

    for ms in attention.missions.ongoing:
        mission_id = str(ms.mission_id)
        domain = str(ms.domain or "")
        alive = int(ms.alive_count)
        army_fraction = _clamp01(float(alive) / float(max(1, total_army_units)))

        thr = awareness.mem.get(K("intel", "mission", mission_id, "threat", "state"), now=now, default={}) or {}
        if not isinstance(thr, dict):
            thr = {}
        danger_score = _clamp01(float(thr.get("danger_score", 0.0) or 0.0))
        risk_level = str(thr.get("risk_level", "LOW") or "LOW").upper()
        worker_targets = int(thr.get("worker_targets", 0) or 0)
        can_win_value = int(thr.get("can_win_value", 5) or 5)

        risk_score = float(danger_score)
        if risk_level == "CRITICAL":
            risk_score = max(risk_score, 0.90)
        elif risk_level == "HIGH":
            risk_score = max(risk_score, 0.68)

        gain_score = _mission_domain_gain(domain)
        if domain == "HARASS":
            gain_score += min(0.22, float(worker_targets) * 0.035)
            if can_win_value >= 6:
                gain_score += 0.08
        if domain == "DEFENSE":
            gain_score += min(0.25, float(threat_urgency) / 220.0)
            if pressure_on_us > 0 or "DEFENSE_PRIORITIZE" in route_tags:
                gain_score += 0.10
        gain_score = _clamp01(gain_score)

        preserve_score = _clamp01((0.58 * army_fraction) + (0.42 * risk_score))
        conservative = bool(
            army_fraction >= float(cfg.conservative_army_fraction_at)
            or preserve_score >= 0.62
            or (domain == "DEFENSE" and pressure_on_us > 0)
        )
        very_conservative = bool(
            army_fraction >= float(cfg.very_conservative_army_fraction_at)
            or preserve_score >= 0.82
        )

        behavior = {
            "conservative_mode": bool(conservative),
            "very_conservative_mode": bool(very_conservative),
            "retreat_hp_bias": float(round(0.05 + (0.18 * preserve_score), 3)),
            "kite_bias": float(round(0.10 + (0.30 * risk_score), 3)),
            "commit_bias": float(round(max(0.0, 0.6 - (0.5 * preserve_score)), 3)),
        }
        snapshot = {
            "mission_id": str(mission_id),
            "domain": str(domain),
            "t": float(now),
            "alive_units": int(alive),
            "total_army_units": int(total_army_units),
            "army_fraction": float(round(army_fraction, 3)),
            "risk_score": float(round(risk_score, 3)),
            "gain_score": float(round(gain_score, 3)),
            "preserve_score": float(round(preserve_score, 3)),
            "behavior": dict(behavior),
        }
        awareness.mem.set(K("intel", "mission", mission_id, "value", "snapshot"), value=snapshot, now=now, ttl=float(cfg.ttl_s))
        awareness.mem.set(K("intel", "mission", mission_id, "value", "risk_score"), value=float(risk_score), now=now, ttl=float(cfg.ttl_s))
        awareness.mem.set(K("intel", "mission", mission_id, "value", "gain_score"), value=float(gain_score), now=now, ttl=float(cfg.ttl_s))
        awareness.mem.set(
            K("intel", "mission", mission_id, "value", "preserve_score"),
            value=float(preserve_score),
            now=now,
            ttl=float(cfg.ttl_s),
        )
        awareness.mem.set(K("intel", "mission", mission_id, "behavior"), value=dict(behavior), now=now, ttl=float(cfg.ttl_s))
