from __future__ import annotations

from dataclasses import dataclass

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K


@dataclass(frozen=True)
class MissionUnitThreatIntelConfig:
    ttl_s: float = 8.0
    observed_weight: float = 0.7
    inferred_weight: float = 0.3
    tick_on_danger_delta: int = 1
    max_summary: int = 6
    min_update_interval_s: float = 0.6


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _risk_level(score: float) -> str:
    s = float(score)
    if s >= 0.78:
        return "CRITICAL"
    if s >= 0.58:
        return "HIGH"
    if s >= 0.32:
        return "MID"
    return "LOW"


def derive_mission_unit_threat_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: MissionUnitThreatIntelConfig = MissionUnitThreatIntelConfig(),
) -> None:
    _ = bot
    m_by_id = {str(m.mission_id): m for m in attention.missions.ongoing}
    mt_by_id = {str(m.mission_id): m for m in attention.unit_threats.missions}

    flow_conf = float(awareness.mem.get(K("enemy", "pathing", "flow", "confidence"), now=now, default=0.0) or 0.0)
    flow_conf = _clamp01(flow_conf)
    pressure_on_us = int(awareness.mem.get(K("enemy", "pathing", "route", "pressure_on_us"), now=now, default=0) or 0)
    route_tags = awareness.mem.get(K("enemy", "pathing", "route", "tags"), now=now, default=[]) or []
    if not isinstance(route_tags, list):
        route_tags = []
    route_tag_set = {str(x) for x in route_tags}
    threat_urgency = int(attention.combat.primary_urgency)
    urgency_factor = _clamp01(float(threat_urgency) / 100.0)

    changed_any = False
    summary: list[dict] = []

    for mission_id, ms in m_by_id.items():
        mt = mt_by_id.get(mission_id)
        domain = str(ms.domain or "")

        unit_count = int(getattr(mt, "unit_count", int(ms.alive_count)) or int(ms.alive_count))
        units_in_danger = int(getattr(mt, "units_in_danger", 0) or 0)
        enemy_count_local = int(getattr(mt, "enemy_count_local", 0) or 0)
        worker_targets = int(getattr(mt, "worker_targets", 0) or 0)
        can_win_value = int(getattr(mt, "can_win_value", 5) or 5)

        observed_ratio = float(units_in_danger) / float(max(1, unit_count))
        lose_pressure = _clamp01(float(max(0, 5 - int(can_win_value))) / 5.0)
        local_density = _clamp01(float(enemy_count_local) / 7.0)
        danger_observed = _clamp01((0.52 * observed_ratio) + (0.33 * lose_pressure) + (0.15 * local_density))

        infer = 0.0
        if pressure_on_us > 0 and domain in {"DEFENSE", "INTEL"}:
            infer += 0.55 * float(flow_conf)
        elif pressure_on_us > 0 and domain == "HARASS":
            infer += 0.25 * float(flow_conf)
        if "DEFENSE_PRIORITIZE" in route_tag_set and domain == "DEFENSE":
            infer += 0.2 * float(flow_conf)
        if "HARASS_WINDOW" in route_tag_set and domain == "HARASS":
            infer -= 0.18 * float(flow_conf)
        infer += 0.15 * float(urgency_factor) if domain in {"DEFENSE", "INTEL"} else 0.05 * float(urgency_factor)
        danger_inferred = _clamp01(infer)

        danger_final = _clamp01(
            (float(cfg.observed_weight) * float(danger_observed))
            + (float(cfg.inferred_weight) * float(danger_inferred))
        )
        risk_level = _risk_level(danger_final)
        retreat_recommended = bool(
            risk_level in {"HIGH", "CRITICAL"}
            and (can_win_value <= 3 or observed_ratio >= 0.5 or units_in_danger >= max(1, unit_count // 2))
        )
        reinforce_needed = bool(
            risk_level in {"HIGH", "CRITICAL"}
            and enemy_count_local >= max(2, unit_count)
            and can_win_value <= 4
        )
        engage_window_s = 0.0
        if not retreat_recommended and can_win_value >= 6 and worker_targets >= 2 and risk_level in {"LOW", "MID"}:
            engage_window_s = 3.5

        prev_state = awareness.mem.get(K("intel", "mission", mission_id, "threat", "state"), now=now, default={}) or {}
        if not isinstance(prev_state, dict):
            prev_state = {}
        prev_updated = float(prev_state.get("updated_at", 0.0) or 0.0)
        min_interval_ok = (float(now) - float(prev_updated)) >= float(cfg.min_update_interval_s)

        changed = bool(
            str(prev_state.get("risk_level", "")) != str(risk_level)
            or bool(prev_state.get("retreat_recommended", False)) != bool(retreat_recommended)
            or int(prev_state.get("units_in_danger", -1) or -1) != int(units_in_danger)
        )
        prev_tick = int(awareness.mem.get(K("intel", "mission", mission_id, "threat", "danger_tick"), now=now, default=0) or 0)
        danger_tick = int(prev_tick + int(cfg.tick_on_danger_delta)) if changed else int(prev_tick)

        state = {
            "mission_id": str(mission_id),
            "domain": str(domain),
            "risk_level": str(risk_level),
            "danger_score": float(round(danger_final, 3)),
            "danger_observed": float(round(danger_observed, 3)),
            "danger_inferred": float(round(danger_inferred, 3)),
            "units_in_danger": int(units_in_danger),
            "unit_count": int(unit_count),
            "enemy_count_local": int(enemy_count_local),
            "can_win_value": int(can_win_value),
            "worker_targets": int(worker_targets),
            "retreat_recommended": bool(retreat_recommended),
            "reinforce_needed": bool(reinforce_needed),
            "engage_window_s": float(round(engage_window_s, 2)),
            "updated_at": float(now),
        }
        if changed and min_interval_ok:
            changed_any = True
        if changed or min_interval_ok:
            awareness.mem.set(K("intel", "mission", mission_id, "threat", "state"), value=state, now=now, ttl=float(cfg.ttl_s))
            awareness.mem.set(
                K("intel", "mission", mission_id, "threat", "danger_tick"),
                value=int(danger_tick),
                now=now,
                ttl=float(cfg.ttl_s),
            )
            awareness.mem.set(
                K("intel", "mission", mission_id, "threat", "risk_level"),
                value=str(risk_level),
                now=now,
                ttl=float(cfg.ttl_s),
            )
            awareness.mem.set(
                K("intel", "mission", mission_id, "threat", "units_in_danger"),
                value=int(units_in_danger),
                now=now,
                ttl=float(cfg.ttl_s),
            )
            awareness.mem.set(
                K("intel", "mission", mission_id, "threat", "retreat_recommended"),
                value=bool(retreat_recommended),
                now=now,
                ttl=float(cfg.ttl_s),
            )
            awareness.mem.set(
                K("intel", "mission", mission_id, "threat", "reinforce_needed"),
                value=bool(reinforce_needed),
                now=now,
                ttl=float(cfg.ttl_s),
            )
            awareness.mem.set(
                K("intel", "mission", mission_id, "threat", "engage_window_s"),
                value=float(engage_window_s),
                now=now,
                ttl=float(cfg.ttl_s),
            )

        summary.append(
            {
                "mission_id": str(mission_id),
                "domain": str(domain),
                "risk_level": str(risk_level),
                "danger_score": float(round(danger_final, 3)),
                "units_in_danger": int(units_in_danger),
                "unit_count": int(unit_count),
                "retreat_recommended": bool(retreat_recommended),
                "danger_tick": int(danger_tick),
            }
        )

    summary.sort(
        key=lambda x: (
            {"LOW": 0, "MID": 1, "HIGH": 2, "CRITICAL": 3}.get(str(x.get("risk_level", "LOW")), 0),
            float(x.get("danger_score", 0.0)),
            int(x.get("units_in_danger", 0)),
        ),
        reverse=True,
    )
    summary = summary[: max(1, int(cfg.max_summary))]

    worst_id = str(summary[0]["mission_id"]) if summary else ""
    critical_top3 = [s for s in summary if str(s.get("risk_level", "")) in {"HIGH", "CRITICAL"}][:3]
    awareness.mem.set(K("intel", "mission", "summary"), value=list(summary), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "mission", "worst_mission_id"), value=str(worst_id), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "mission", "critical_top3"), value=list(critical_top3), now=now, ttl=float(cfg.ttl_s))

    prev_ver = int(awareness.mem.get(K("intel", "mission", "version"), now=now, default=0) or 0)
    ver = int(prev_ver + 1) if changed_any else int(prev_ver)
    awareness.mem.set(K("intel", "mission", "version"), value=int(ver), now=now, ttl=None)
