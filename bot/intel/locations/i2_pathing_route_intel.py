from __future__ import annotations

from dataclasses import dataclass
import math

from sc2.position import Point2

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K


@dataclass(frozen=True)
class PathingRouteIntelConfig:
    ttl_s: float = 20.0
    min_flow_confidence: float = 0.25
    landmark_near_radius: float = 18.0
    flank_angle_deg: float = 28.0


def _enemy_main(bot) -> Point2:
    return bot.enemy_start_locations[0]


def _enemy_natural(bot) -> Point2:
    main = _enemy_main(bot)
    exps = list(getattr(bot, "expansion_locations_list", []) or [])
    if not exps:
        return main
    exps_no_main = [p for p in exps if float(p.distance_to(main)) > 5.0]
    if not exps_no_main:
        exps_no_main = exps
    exps_no_main.sort(key=lambda p: float(p.distance_to(main)))
    return exps_no_main[0]


def _enemy_third(bot) -> Point2:
    main = _enemy_main(bot)
    exps = list(getattr(bot, "expansion_locations_list", []) or [])
    if not exps:
        return main
    exps_no_main = [p for p in exps if float(p.distance_to(main)) > 5.0]
    if len(exps_no_main) < 2:
        return exps_no_main[0] if exps_no_main else main
    exps_no_main.sort(key=lambda p: float(p.distance_to(main)))
    return exps_no_main[1]


def _our_natural(bot) -> Point2:
    try:
        return bot.mediator.get_own_nat
    except Exception:
        return bot.start_location


def _closest_landmark_name(pos: Point2, landmarks: list[tuple[str, Point2]]) -> tuple[str, float]:
    best = ("UNKNOWN", 1e9)
    for name, p in landmarks:
        d = float(pos.distance_to(p))
        if d < best[1]:
            best = (str(name), d)
    return best


def _angle_between(vx: float, vy: float, wx: float, wy: float) -> float:
    vn = math.hypot(vx, vy)
    wn = math.hypot(wx, wy)
    if vn <= 1e-6 or wn <= 1e-6:
        return 0.0
    dot = (vx * wx) + (vy * wy)
    c = max(-1.0, min(1.0, dot / (vn * wn)))
    return float(math.degrees(math.acos(c)))


def derive_pathing_route_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: PathingRouteIntelConfig = PathingRouteIntelConfig(),
) -> None:
    _ = attention
    flow = awareness.mem.get(K("enemy", "pathing", "flow", "snapshot"), now=now, default={}) or {}
    if not isinstance(flow, dict):
        return
    conf = float(flow.get("confidence", 0.0) or 0.0)
    if conf < float(cfg.min_flow_confidence):
        return

    from_d = flow.get("from", {}) if isinstance(flow.get("from", {}), dict) else {}
    to_d = flow.get("to", {}) if isinstance(flow.get("to", {}), dict) else {}
    pred_d = flow.get("predicted", {}) if isinstance(flow.get("predicted", {}), dict) else {}
    vec_d = flow.get("vector", {}) if isinstance(flow.get("vector", {}), dict) else {}

    p_from = Point2((float(from_d.get("x", 0.0) or 0.0), float(from_d.get("y", 0.0) or 0.0)))
    p_to = Point2((float(to_d.get("x", 0.0) or 0.0), float(to_d.get("y", 0.0) or 0.0)))
    p_pred = Point2((float(pred_d.get("x", 0.0) or 0.0), float(pred_d.get("y", 0.0) or 0.0)))
    vx = float(vec_d.get("x", 0.0) or 0.0)
    vy = float(vec_d.get("y", 0.0) or 0.0)

    em = _enemy_main(bot)
    en = _enemy_natural(bot)
    et = _enemy_third(bot)
    on = _our_natural(bot)
    oc = bot.start_location
    mc = bot.game_info.map_center

    landmarks = [
        ("ENEMY_MAIN", em),
        ("ENEMY_NAT", en),
        ("ENEMY_THIRD", et),
        ("OUR_NAT", on),
        ("OUR_MAIN", oc),
        ("MAP_CENTER", mc),
    ]
    from_name, from_dist = _closest_landmark_name(p_from, landmarks)
    to_name, to_dist = _closest_landmark_name(p_to, landmarks)

    near_r = float(cfg.landmark_near_radius)
    near_from = from_name if from_dist <= near_r else "FIELD"
    near_to = to_name if to_dist <= near_r else "FIELD"

    route = "FIELD_FLOW"
    if near_from.startswith("ENEMY_") and near_to.startswith("ENEMY_"):
        route = f"{near_from}_TO_{near_to}"
    elif near_from.startswith("ENEMY_") and near_to.startswith("OUR_"):
        route = "ENEMY_TO_OUR_PUSH"
    elif near_from == "MAP_CENTER" and near_to.startswith("OUR_"):
        route = "CENTER_TO_OUR_SIDE"
    elif near_to == "MAP_CENTER" and near_from.startswith("ENEMY_"):
        route = "ENEMY_TO_CENTER"

    base_axis_x = float(on.x) - float(em.x)
    base_axis_y = float(on.y) - float(em.y)
    angle_to_our_side = _angle_between(vx, vy, base_axis_x, base_axis_y)
    flank = "NONE"
    if angle_to_our_side <= float(cfg.flank_angle_deg):
        flank = "DIRECT"
    elif angle_to_our_side >= (180.0 - float(cfg.flank_angle_deg)):
        flank = "RETREATING"
    else:
        cross = (base_axis_x * vy) - (base_axis_y * vx)
        flank = "LEFT_FLANK" if cross > 0.0 else "RIGHT_FLANK"

    pressure_on_us = 1 if p_to.distance_to(on) < p_to.distance_to(em) else 0
    tags: list[str] = []
    tags.append(str(route))
    tags.append(str(flank))
    if pressure_on_us:
        tags.append("PRESSURE_TO_OUR_SIDE")
    if "ENEMY_TO_OUR_PUSH" == route:
        tags.append("DEFENSE_PRIORITIZE")
    if route in {"ENEMY_MAIN_TO_ENEMY_NAT", "ENEMY_NAT_TO_ENEMY_THIRD"}:
        tags.append("HARASS_WINDOW")

    payload = {
        "t": float(now),
        "route": str(route),
        "flank": str(flank),
        "from_landmark": str(near_from),
        "to_landmark": str(near_to),
        "from_dist": float(round(from_dist, 2)),
        "to_dist": float(round(to_dist, 2)),
        "pressure_on_us": int(pressure_on_us),
        "confidence": float(round(conf, 3)),
        "tags": list(tags),
        "predicted": {"x": float(round(p_pred.x, 2)), "y": float(round(p_pred.y, 2))},
    }
    awareness.mem.set(K("enemy", "pathing", "route", "snapshot"), value=payload, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "pathing", "route", "label"), value=str(route), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "pathing", "route", "flank"), value=str(flank), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "pathing", "route", "pressure_on_us"), value=int(pressure_on_us), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "pathing", "route", "tags"), value=list(tags), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "pathing", "route", "last_t"), value=float(now), now=now, ttl=None)

    hints = {
        "defense_priority": bool("DEFENSE_PRIORITIZE" in tags or pressure_on_us == 1),
        "harass_window": bool("HARASS_WINDOW" in tags and pressure_on_us == 0),
        "enemy_vector_confidence": float(round(conf, 3)),
    }
    awareness.mem.set(K("intel", "locations", "hints"), value=hints, now=now, ttl=float(cfg.ttl_s))
