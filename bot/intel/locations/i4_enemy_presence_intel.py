from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K

_NON_COMBAT = {U.SCV, U.PROBE, U.DRONE, U.MULE, U.LARVA, U.EGG, U.OVERLORD}
_POWER = {
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
    U.SIEGETANKSIEGED: 4.0,
    U.ZEALOT: 1.3,
    U.ADEPT: 1.35,
    U.STALKER: 1.8,
    U.IMMORTAL: 3.0,
    U.ARCHON: 3.3,
    U.PHOTONCANNON: 3.5,
    U.SPINECRAWLER: 3.5,
    U.BUNKER: 4.0,
}


@dataclass(frozen=True)
class EnemyPresenceIntelConfig:
    ttl_s: float = 10.0
    cluster_join_radius: float = 9.0
    stale_s: float = 20.0
    split_power_min: float = 2.5
    own_side_radius: float = 18.0


def _our_natural(bot) -> Point2:
    try:
        return bot.mediator.get_own_nat
    except Exception:
        return bot.start_location


def _enemy_main(bot) -> Point2:
    return bot.enemy_start_locations[0]


def _enemy_natural(bot) -> Point2:
    main = _enemy_main(bot)
    exps = list(getattr(bot, "expansion_locations_list", []) or [])
    if not exps:
        return main
    exps = [p for p in exps if float(p.distance_to(main)) > 5.0] or exps
    exps.sort(key=lambda p: float(p.distance_to(main)))
    return exps[0]


def _enemy_third(bot) -> Point2:
    main = _enemy_main(bot)
    exps = list(getattr(bot, "expansion_locations_list", []) or [])
    if not exps:
        return main
    exps = [p for p in exps if float(p.distance_to(main)) > 5.0] or exps
    exps.sort(key=lambda p: float(p.distance_to(main)))
    return exps[1] if len(exps) >= 2 else exps[0]


def _point_payload(pos: Point2 | None) -> dict[str, float] | None:
    if pos is None:
        return None
    return {"x": float(pos.x), "y": float(pos.y)}


def _visible_enemy_combat(bot) -> list:
    out = []
    for unit in list(getattr(bot, "enemy_units", []) or []):
        try:
            if unit.type_id in _NON_COMBAT:
                continue
            out.append(unit)
        except Exception:
            continue
    for struct in list(getattr(bot, "enemy_structures", []) or []):
        try:
            if getattr(struct, "type_id", None) in _NON_COMBAT:
                continue
            if getattr(struct, "type_id", None) in {U.HATCHERY, U.LAIR, U.HIVE, U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS, U.NEXUS}:
                continue
            if bool(getattr(struct, "can_attack_ground", False)):
                out.append(struct)
        except Exception:
            continue
    return out


def _unit_power(unit) -> float:
    try:
        return float(_POWER.get(getattr(unit, "type_id", None), 1.0))
    except Exception:
        return 1.0


def _cluster_units(units: list, *, join_radius: float) -> list[list]:
    clusters: list[list] = []
    for unit in units:
        placed = False
        for cluster in clusters:
            try:
                if any(float(unit.distance_to(other)) <= float(join_radius) for other in cluster):
                    cluster.append(unit)
                    placed = True
                    break
            except Exception:
                continue
        if not placed:
            clusters.append([unit])
    return clusters


def _cluster_center(cluster: list) -> Point2:
    total_power = sum(_unit_power(u) for u in cluster) or 1.0
    x = sum(float(u.position.x) * _unit_power(u) for u in cluster) / float(total_power)
    y = sum(float(u.position.y) * _unit_power(u) for u in cluster) / float(total_power)
    return Point2((x, y))


def _closest_label(pos: Point2, landmarks: list[tuple[str, Point2]]) -> tuple[str, float]:
    best = ("UNKNOWN", 9999.0)
    for label, point in landmarks:
        dist = float(pos.distance_to(point))
        if dist < best[1]:
            best = (str(label), dist)
    return best


def derive_enemy_presence_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: EnemyPresenceIntelConfig = EnemyPresenceIntelConfig(),
) -> None:
    _ = attention
    units = _visible_enemy_combat(bot)
    own_nat = _our_natural(bot)
    own_main = bot.start_location
    enemy_main = _enemy_main(bot)
    enemy_nat = _enemy_natural(bot)
    enemy_third = _enemy_third(bot)
    landmarks = [
        ("OUR_MAIN", own_main),
        ("OUR_NAT", own_nat),
        ("ENEMY_MAIN", enemy_main),
        ("ENEMY_NAT", enemy_nat),
        ("ENEMY_THIRD", enemy_third),
        ("MAP_CENTER", bot.game_info.map_center),
    ]

    clusters_payload: list[dict] = []
    own_side_power = 0.0
    nat_side_power = 0.0
    primary = None
    state = "UNKNOWN"
    confidence = 0.0

    if units:
        clustered = _cluster_units(units, join_radius=float(cfg.cluster_join_radius))
        scored: list[tuple[float, dict]] = []
        for idx, cluster in enumerate(clustered):
            center = _cluster_center(cluster)
            power = float(sum(_unit_power(u) for u in cluster))
            count = int(len(cluster))
            near_label, near_dist = _closest_label(center, landmarks)
            side = "MID_MAP"
            if float(center.distance_to(own_nat)) <= float(cfg.own_side_radius):
                side = "OUR_NAT_SIDE"
                nat_side_power += float(power)
            elif float(center.distance_to(own_main)) <= float(cfg.own_side_radius):
                side = "OUR_MAIN_SIDE"
                own_side_power += float(power)
            elif float(center.distance_to(own_nat)) < float(center.distance_to(enemy_nat)):
                side = "OUR_SIDE"
                own_side_power += float(power)
            elif near_label in {"ENEMY_MAIN", "ENEMY_NAT", "ENEMY_THIRD"}:
                side = "ENEMY_SIDE"
            radius = 0.0
            for unit in cluster:
                try:
                    radius = max(radius, float(unit.distance_to(center)))
                except Exception:
                    continue
            payload = {
                "id": int(idx),
                "center": _point_payload(center),
                "power": float(round(power, 3)),
                "count": int(count),
                "radius": float(round(radius, 2)),
                "side": str(side),
                "near_label": str(near_label),
                "near_dist": float(round(near_dist, 2)),
                "freshness_s": 0.0,
            }
            clusters_payload.append(payload)
            scored.append((float(power), payload))
        scored.sort(key=lambda x: x[0], reverse=True)
        primary = dict(scored[0][1]) if scored else None
        strong_clusters = [p for p in clusters_payload if float(p.get("power", 0.0) or 0.0) >= float(cfg.split_power_min)]
        if len(strong_clusters) >= 2:
            state = "SPLIT_PRESSURE"
        elif primary is not None:
            side = str(primary.get("side", "MID_MAP"))
            if side in {"OUR_NAT_SIDE", "OUR_MAIN_SIDE", "OUR_SIDE"}:
                state = "ON_OUR_SIDE"
            elif side == "ENEMY_SIDE":
                state = "AT_HOME"
            else:
                state = "MOVING_OUT"
        confidence = min(0.98, 0.35 + (0.08 * float(len(clusters_payload))) + min(0.40, float(sum(_unit_power(u) for u in units)) / 18.0))
    else:
        prev = awareness.mem.get(K("enemy", "army", "positions", "snapshot"), now=now, default={}) or {}
        if isinstance(prev, dict):
            last_t = float(prev.get("updated_at", 0.0) or 0.0)
            age = max(0.0, float(now) - float(last_t)) if last_t > 0.0 else 9999.0
            if age <= float(cfg.stale_s):
                primary = prev.get("primary")
                if isinstance(primary, dict):
                    primary = dict(primary)
                    primary["freshness_s"] = float(round(age, 2))
                clusters_prev = prev.get("clusters", [])
                if isinstance(clusters_prev, list):
                    clusters_payload = []
                    for item in clusters_prev:
                        if not isinstance(item, dict):
                            continue
                        copy = dict(item)
                        copy["freshness_s"] = float(round(age, 2))
                        clusters_payload.append(copy)
                own_side_power = float(prev.get("own_side_power", 0.0) or 0.0)
                nat_side_power = float(prev.get("nat_side_power", 0.0) or 0.0)
                state = "LAST_KNOWN"
                confidence = max(0.12, 0.42 * max(0.0, 1.0 - (age / max(1.0, float(cfg.stale_s)))))

    payload = {
        "updated_at": float(now),
        "state": str(state),
        "confidence": float(round(confidence, 3)),
        "clusters": list(clusters_payload),
        "primary": primary,
        "cluster_count": int(len(clusters_payload)),
        "own_side_power": float(round(own_side_power, 3)),
        "nat_side_power": float(round(nat_side_power, 3)),
        "visible_power": float(round(sum(float(c.get("power", 0.0) or 0.0) for c in clusters_payload), 3)),
    }
    awareness.mem.set(K("enemy", "army", "positions", "snapshot"), value=dict(payload), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "army", "positions", "state"), value=str(state), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "army", "positions", "confidence"), value=float(confidence), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "army", "positions", "primary"), value=primary, now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("enemy", "army", "positions", "last_t"), value=float(now), now=now, ttl=None)
    awareness.mem.set(K("intel", "locations", "enemy_army", "snapshot"), value=dict(payload), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "locations", "enemy_army", "state"), value=str(state), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(K("intel", "locations", "enemy_army", "primary"), value=primary, now=now, ttl=float(cfg.ttl_s))
