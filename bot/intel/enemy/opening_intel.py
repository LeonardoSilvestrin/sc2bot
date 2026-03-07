from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.intel.config.opening_timing_rules import OpeningTimingRule
from bot.intel.utils.enemy_econ_estimates import count_enemy_bases, expected_workers, sum_units
from bot.intel.utils.opening_types import OpeningIntelConfig
from bot.intel.utils.state_store import EnemyRushStateStore
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K

_WORKER_TYPES = (U.SCV, U.PROBE, U.DRONE)
_PRODUCTION_STRUCTURES_BY_RACE: dict[str, tuple[U, ...]] = {
    "PROTOSS": (U.GATEWAY, U.WARPGATE, U.ROBOTICSFACILITY, U.STARGATE),
    "TERRAN": (U.BARRACKS, U.FACTORY, U.STARPORT),
    "ZERG": (U.SPAWNINGPOOL, U.ROACHWARREN, U.BANELINGNEST, U.HYDRALISKDEN),
}


@dataclass(frozen=True)
class OpeningDecision:
    kind: str
    confidence: float
    rush_state: str
    rush_confidence: float
    rush_score: float
    rush_severity: float
    rush_tier: str
    rush_math: dict
    signals: dict
    last_seen_pressure_t: float


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(v)))


def _sync_build_runner_scout_intel(*, bot, awareness: Awareness, now: float) -> None:
    lost_early_key = K("intel", "scv", "lost_early")
    lost_early_t_key = K("intel", "scv", "lost_early_t")
    try:
        scouts = bot.mediator.get_units_from_role(role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=U.SCV)
    except Exception:
        scouts = []
    scouts = [u for u in list(scouts or []) if u is not None]
    if not scouts:
        dispatched = bool(awareness.intel_scv_dispatched(now=now))
        arrived_main = bool(awareness.intel_scv_arrived_main(now=now))
        last_dispatch_at = float(awareness.intel_last_scv_dispatch_at(now=now) or 0.0)
        lost_early = bool(awareness.mem.get(lost_early_key, now=now, default=False))
        lost_early_window = bool(
            dispatched
            and not arrived_main
            and not lost_early
            and float(now) <= 220.0
            and float(last_dispatch_at) > 0.0
            and (float(now) - float(last_dispatch_at)) <= 120.0
        )
        if lost_early_window:
            awareness.mem.set(lost_early_key, value=True, now=now, ttl=180.0)
            awareness.mem.set(lost_early_t_key, value=float(now), now=now, ttl=180.0)
        return

    if not awareness.intel_scv_dispatched(now=now):
        awareness.mark_scv_dispatched(now=now)

    try:
        enemy_main = bot.enemy_start_locations[0]
    except Exception:
        enemy_main = None
    if enemy_main is None or awareness.intel_scv_arrived_main(now=now):
        return

    for scout in scouts:
        try:
            if float(scout.distance_to(enemy_main)) <= 12.0:
                awareness.mark_scv_arrived_main(now=now, ttl=180.0)
                return
        except Exception:
            continue


def _match_timing_rule(
    *,
    now: float,
    rule: OpeningTimingRule,
    enemy_race: str,
    enemy_structs: Dict[U, int],
    main_structs: Dict[U, int],
    progress: Dict[U, dict],
) -> bool:
    rr = str(rule.race).upper()
    er = str(enemy_race or "UNKNOWN").upper()
    if rr != "ANY" and rr != er:
        return False
    if float(now) < float(rule.earliest_t) or float(now) > float(rule.latest_t):
        return False

    total_count = int(enemy_structs.get(rule.structure, 0))
    main_count = int(main_structs.get(rule.structure, 0))
    max_prog = float((progress.get(rule.structure, {}) or {}).get("max", 0.0) or 0.0)

    if int(total_count) < int(rule.min_total_count):
        return False
    if rule.max_total_count is not None and int(total_count) > int(rule.max_total_count):
        return False
    if int(main_count) < int(rule.min_main_count):
        return False
    if rule.max_main_count is not None and int(main_count) > int(rule.max_main_count):
        return False
    if float(max_prog) < float(rule.min_progress):
        return False
    return True


def _rush_math_signals(*, now: float, eb, cfg: OpeningIntelConfig, workers_peak_seen: int = 0, enemy_race: str = "UNKNOWN") -> dict:
    rules = tuple(cfg.timing_rules or ())
    if not rules:
        raise RuntimeError("missing_contract:opening_intel.timing_rules")
    enemy_units: Dict[U, int] = dict(getattr(eb, "enemy_units", {}) or {})
    enemy_structs: Dict[U, int] = dict(getattr(eb, "enemy_structures", {}) or {})
    main_units: Dict[U, int] = dict(getattr(eb, "enemy_units_main", {}) or {})
    main_structs: Dict[U, int] = dict(getattr(eb, "enemy_structures_main", {}) or {})
    progress: Dict[U, dict] = dict(getattr(eb, "enemy_structures_progress", {}) or {})

    workers_seen_all = sum_units(enemy_units, _WORKER_TYPES)
    workers_seen_main = sum_units(main_units, _WORKER_TYPES)
    workers_seen_now = int(max(workers_seen_all, workers_seen_main))
    workers_seen = int(max(workers_seen_now, int(workers_peak_seen)))
    expected = expected_workers(float(now), period_s=float(cfg.expected_worker_period_s), cap=80)
    worker_deficit = max(0, int(expected) - int(workers_seen))

    enemy_bases = count_enemy_bases(enemy_structs)
    nat_on_ground = bool(getattr(eb, "enemy_natural_on_ground", False))
    nat_prog = float(getattr(eb, "enemy_natural_townhall_progress", 0.0) or 0.0)
    race_u = str(enemy_race or "UNKNOWN").upper()
    production_structures_visible = int(
        sum(
            max(0, int(enemy_structs.get(uid, 0) or 0))
            for uid in _PRODUCTION_STRUCTURES_BY_RACE.get(race_u, ())
        )
    )
    visible_non_worker_total = int(
        sum(
            max(0, int(cnt or 0))
            for uid, cnt in enemy_units.items()
            if uid not in _WORKER_TYPES
        )
    )

    score = 0.0
    matched_rules: list[str] = []
    hard_rush = False

    for rule in rules:
        if not _match_timing_rule(
            now=float(now),
            rule=rule,
            enemy_race=str(enemy_race),
            enemy_structs=enemy_structs,
            main_structs=main_structs,
            progress=progress,
        ):
            continue
        score += float(rule.score)
        matched_rules.append(str(rule.name))
        if bool(rule.confirm):
            hard_rush = True

    worker_deficit_score = 0.0
    if (
        worker_deficit >= int(cfg.worker_under_count_tolerance)
        and float(now) <= float(cfg.worker_deficit_check_until_s)
        and int(enemy_bases) <= 1
        and not bool(nat_on_ground)
    ):
        worker_deficit_score = min(float(cfg.worker_deficit_score_cap), float(worker_deficit) * 1.0)
        score += float(worker_deficit_score)
    if int(enemy_bases) <= 1 and not nat_on_ground and float(now) >= float(cfg.one_base_alert_at_s):
        score += float(cfg.one_base_alert_score)
    if float(now) <= float(cfg.no_natural_alert_until_s) and not nat_on_ground and nat_prog <= 0.0:
        score += float(cfg.no_natural_alert_score)
    if not nat_on_ground and int(production_structures_visible) >= 3 and float(now) <= 300.0:
        score += float(10.0 + (6.0 * max(0, int(production_structures_visible) - 3)))
        matched_rules.append(f"production_stack_no_nat:{production_structures_visible}")
        if int(production_structures_visible) >= 4:
            hard_rush = True

    if not nat_on_ground and float(now) <= 260.0:
        if race_u == "PROTOSS":
            stargates = int(enemy_structs.get(U.STARGATE, 0) or 0)
            robos = int(enemy_structs.get(U.ROBOTICSFACILITY, 0) or 0)
            gateways = int(enemy_structs.get(U.GATEWAY, 0) or 0) + int(enemy_structs.get(U.WARPGATE, 0) or 0)
            if stargates >= 2:
                score += float(18.0 + (10.0 * max(0, stargates - 2)))
                matched_rules.append(f"protoss_multi_stargate_no_nat:{stargates}")
                if stargates >= 3:
                    hard_rush = True
            if robos >= 2:
                score += 18.0
                matched_rules.append("protoss_double_robo_no_nat")
            if gateways >= 3 and float(now) >= 105.0:
                score += 10.0
                matched_rules.append(f"protoss_gateway_stack_no_nat:{gateways}")
        elif race_u == "TERRAN":
            barracks = int(enemy_structs.get(U.BARRACKS, 0) or 0)
            factories = int(enemy_structs.get(U.FACTORY, 0) or 0)
            if barracks >= 2:
                score += float(12.0 + (6.0 * max(0, barracks - 2)))
                matched_rules.append(f"terran_barracks_stack_no_nat:{barracks}")
            if factories >= 2:
                score += 16.0
                matched_rules.append(f"terran_factory_stack_no_nat:{factories}")
        elif race_u == "ZERG":
            roaches = int(enemy_units.get(U.ROACH, 0) or 0)
            if roaches >= 4:
                score += 16.0
                matched_rules.append(f"zerg_roach_count_no_nat:{roaches}")

    if not nat_on_ground and float(now) <= 260.0 and int(visible_non_worker_total) >= 8:
        score += float(min(20.0, 4.0 + (2.0 * max(0, int(visible_non_worker_total) - 8))))
        matched_rules.append(f"visible_army_no_nat:{visible_non_worker_total}")
        if int(visible_non_worker_total) >= 12:
            hard_rush = True

    likely_end = bool((nat_on_ground and float(nat_prog) >= 0.90) and worker_deficit <= 2 and enemy_bases >= 2)

    return {
        "workers_seen": int(workers_seen),
        "workers_seen_now": int(workers_seen_now),
        "workers_peak_seen": int(max(0, int(workers_peak_seen))),
        "workers_expected": int(expected),
        "worker_deficit": int(worker_deficit),
        "worker_deficit_score": float(round(worker_deficit_score, 2)),
        "enemy_bases_visible": int(enemy_bases),
        "natural_on_ground": bool(nat_on_ground),
        "natural_progress": float(nat_prog),
        "production_structures_visible": int(production_structures_visible),
        "visible_non_worker_total": int(visible_non_worker_total),
        "matched_timing_rules": list(matched_rules),
        "rush_score": float(round(score, 2)),
        "hard_rush": bool(hard_rush),
        "likely_end": bool(likely_end),
    }


def _evaluate_opening(
    *,
    now: float,
    attention: Attention,
    cfg: OpeningIntelConfig,
    enemy_race: str,
    prev_rush_state: str,
    last_pressure_t: float,
    workers_peak_seen: int,
) -> OpeningDecision:
    eb = attention.enemy_build
    enemy_units: Dict[U, int] = eb.enemy_units
    enemy_structs: Dict[U, int] = eb.enemy_structures
    main_units: Dict[U, int] = dict(getattr(eb, "enemy_units_main", {}) or {})

    enemy_bases = count_enemy_bases(enemy_structs)
    near_bases = int(attention.combat.primary_enemy_count)
    threatened = bool(
        int(attention.combat.primary_urgency) >= int(cfg.threatened_urgency_min)
        and int(near_bases) >= int(cfg.threatened_near_bases_min)
    )

    lings = sum_units(enemy_units, (U.ZERGLING,))
    marines = sum_units(enemy_units, (U.MARINE,))
    reapers = sum_units(enemy_units, (U.REAPER,))
    zealots = sum_units(enemy_units, (U.ZEALOT,))
    adepts = sum_units(enemy_units, (U.ADEPT,))
    stalkers = sum_units(enemy_units, (U.STALKER,))
    main_army_core = sum_units(
        main_units,
        (U.ZERGLING, U.MARINE, U.REAPER, U.ZEALOT, U.ADEPT, U.STALKER, U.ROACH, U.RAVAGER, U.HYDRALISK),
    )

    early = float(now) <= float(cfg.early_s)
    greedy_window = float(now) <= float(cfg.greedy_s)
    nat_on_ground = bool(getattr(eb, "enemy_natural_on_ground", False))

    kind = "NORMAL"
    conf = 0.40

    rush_math = _rush_math_signals(
        now=now,
        eb=eb,
        cfg=cfg,
        workers_peak_seen=int(workers_peak_seen),
        enemy_race=str(enemy_race),
    )
    rush_score = float(rush_math["rush_score"])
    hard_rush = bool(rush_math["hard_rush"])

    if early and (near_bases >= int(cfg.rush_units_near_bases) or (threatened and near_bases >= 3)):
        kind = "AGGRESSIVE"
        conf = min(0.95, 0.55 + 0.05 * float(near_bases))
        if (lings + marines + reapers + zealots + adepts + stalkers) >= 6:
            conf = min(0.98, conf + 0.10)
    elif hard_rush or rush_score >= float(cfg.rush_score_confirmed):
        kind = "AGGRESSIVE"
        conf = min(0.98, 0.62 + (rush_score / 200.0))
    elif greedy_window and (nat_on_ground or enemy_bases >= 2) and near_bases <= 1 and not threatened:
        kind = "GREEDY"
        conf = 0.75

    main_army_refresh_evidence = bool(
        (not nat_on_ground)
        and float(now) <= float(cfg.rush_main_army_refresh_no_nat_until_s)
        and int(main_army_core) >= int(cfg.rush_main_army_refresh_units_min)
    )
    if int(near_bases) > 0 or bool(threatened) or bool(main_army_refresh_evidence):
        last_pressure_t = float(now)
    clear_for = max(0.0, float(now) - float(last_pressure_t))
    recent_pressure = clear_for <= float(cfg.rush_end_clear_s)

    is_suspected = bool(
        rush_score >= float(cfg.rush_score_suspected)
        and (early or recent_pressure or int(near_bases) >= 2 or bool(threatened))
    )
    confirmed_with_pressure = bool(
        rush_score >= float(cfg.rush_score_confirmed) and (bool(threatened) or int(near_bases) >= 2)
    )
    ling_flood_contact = bool(
        float(now) <= float(cfg.rush_phase_max_s)
        and int(lings) >= 4
        and int(near_bases) >= 2
    )
    is_confirmed = bool(hard_rush or confirmed_with_pressure or (threatened and near_bases >= 3) or ling_flood_contact)
    rush_likely_end = bool(rush_math["likely_end"]) and clear_for >= float(cfg.rush_end_clear_s)
    rush_forced_end = bool(clear_for >= float(cfg.rush_hold_max_s) and int(near_bases) <= 1 and not bool(threatened))
    rush_suspected_decay = bool(clear_for >= float(cfg.rush_suspect_decay_s) and int(near_bases) <= 1 and not bool(threatened))

    rush_state = str(prev_rush_state or "NONE")
    if is_confirmed:
        rush_state = "CONFIRMED"
    elif is_suspected:
        rush_state = "SUSPECTED" if rush_state in {"NONE", "ENDED"} else "HOLDING"
    elif rush_state in {"CONFIRMED", "SUSPECTED", "HOLDING"}:
        if rush_likely_end or rush_forced_end or (rush_state == "SUSPECTED" and rush_suspected_decay):
            rush_state = "ENDED"
        else:
            rush_state = "HOLDING"
    else:
        rush_state = "NONE"

    rush_conf = min(0.99, max(0.05, 0.30 + rush_score / 100.0 + (0.20 if is_confirmed else 0.0)))
    if rush_state == "NONE":
        rush_conf = min(rush_conf, 0.35)
    if rush_state == "ENDED":
        rush_conf = min(rush_conf, 0.55)

    matched_rules = list(rush_math.get("matched_timing_rules", []) or [])
    worker_deficit = int(rush_math.get("worker_deficit", 0) or 0)
    no_natural = not bool(nat_on_ground)
    score_norm = 0.0
    if float(cfg.rush_score_extreme) > float(cfg.rush_score_suspected):
        score_norm = max(
            0.0,
            min(
                1.0,
                (float(rush_score) - float(cfg.rush_score_suspected))
                / max(1e-6, float(cfg.rush_score_extreme) - float(cfg.rush_score_suspected)),
            ),
        )
    direct_pressure = max(0.0, min(1.0, (float(near_bases) - 1.0) / 5.0))
    structural_pressure = 1.0 if bool(hard_rush) else max(0.0, min(1.0, float(len(matched_rules)) / 2.0))
    worker_pressure = max(0.0, min(1.0, float(worker_deficit) / 10.0))
    severity = (
        (0.45 * float(score_norm))
        + (0.22 * float(direct_pressure))
        + (0.12 * (1.0 if bool(threatened) else 0.0))
        + (0.11 * float(structural_pressure))
        + (0.06 * float(worker_pressure))
        + (0.04 * (1.0 if bool(no_natural) else 0.0))
    )
    severity = max(0.0, min(1.0, float(severity)))
    if rush_state == "NONE":
        severity = 0.0
    elif rush_state == "ENDED":
        severity *= 0.35
    elif rush_state == "CONFIRMED":
        severity = max(float(severity), 0.58)
    elif rush_state == "HOLDING":
        severity = max(float(severity), 0.46)
    if bool(hard_rush) and bool(threatened) and int(near_bases) >= int(cfg.rush_heavy_near_bases):
        severity = max(float(severity), 0.78)
    if bool(hard_rush) and bool(threatened) and int(near_bases) >= int(cfg.rush_extreme_near_bases):
        severity = max(float(severity), 0.92)

    rush_tier = "NONE"
    if rush_state != "NONE":
        rush_tier = "LIGHT"
        if float(severity) >= 0.42 or float(rush_score) >= float(cfg.rush_score_medium) or rush_state in {"CONFIRMED", "HOLDING"}:
            rush_tier = "MEDIUM"
        if float(severity) >= 0.70 or (
            float(rush_score) >= float(cfg.rush_score_heavy)
            and (bool(threatened) or int(near_bases) >= int(cfg.rush_heavy_near_bases) or bool(hard_rush))
        ):
            rush_tier = "HEAVY"
        if (
            float(severity) >= 0.90
            or (bool(hard_rush) and bool(threatened) and int(near_bases) >= int(cfg.rush_extreme_near_bases))
            or (float(rush_score) >= float(cfg.rush_score_extreme) and int(near_bases) >= int(cfg.rush_heavy_near_bases))
        ):
            rush_tier = "EXTREME"
    if rush_state == "ENDED":
        rush_tier = "NONE"

    signals = {
        "t": round(float(now), 2),
        "early": bool(early),
        "greedy_window": bool(greedy_window),
        "enemy_bases_visible": int(enemy_bases),
        "enemy_near_our_bases": int(near_bases),
        "threatened": bool(threatened),
        "natural_on_ground": bool(nat_on_ground),
        "natural_townhall_progress": float(getattr(eb, "enemy_natural_townhall_progress", 0.0) or 0.0),
        "natural_townhall_type": str(getattr(eb, "enemy_natural_townhall_type", None)),
        "seen_units": {
            "lings": int(lings),
            "marines": int(marines),
            "reapers": int(reapers),
            "zealots": int(zealots),
            "adepts": int(adepts),
            "stalkers": int(stalkers),
        },
        "main_units": dict(getattr(eb, "enemy_units_main", {}) or {}),
        "main_army_core": int(main_army_core),
        "main_army_refresh_evidence": bool(main_army_refresh_evidence),
        "main_structures": dict(getattr(eb, "enemy_structures_main", {}) or {}),
        "structures_progress": dict(getattr(eb, "enemy_structures_progress", {}) or {}),
        "rush_math": dict(rush_math),
        "rush_state": str(rush_state),
        "rush_confidence": float(round(rush_conf, 3)),
        "rush_severity": float(round(severity, 3)),
        "rush_tier": str(rush_tier),
        "last_seen_pressure_t": float(round(last_pressure_t, 2)),
        "pressure_clear_s": float(round(clear_for, 2)),
        "recent_pressure": bool(recent_pressure),
        "rush_forced_end": bool(rush_forced_end),
        "rush_suspected_decay": bool(rush_suspected_decay),
    }

    return OpeningDecision(
        kind=str(kind),
        confidence=float(conf),
        rush_state=str(rush_state),
        rush_confidence=float(rush_conf),
        rush_score=float(rush_score),
        rush_severity=float(severity),
        rush_tier=str(rush_tier),
        rush_math=dict(rush_math),
        signals=signals,
        last_seen_pressure_t=float(last_pressure_t),
    )


def _rush_snapshot_ttl_s(*, cfg: OpeningIntelConfig, decision) -> float:
    ttl = float(cfg.ttl_s)
    state = str(getattr(decision, "rush_state", "NONE") or "NONE").upper()
    rush_math = dict(getattr(decision, "rush_math", {}) or {})
    signals = dict(getattr(decision, "signals", {}) or {})

    if state == "CONFIRMED":
        ttl += float(cfg.rush_ttl_confirmed_bonus_s)
    elif state in {"SUSPECTED", "HOLDING"}:
        ttl += float(cfg.rush_ttl_suspected_bonus_s)

    if not bool(signals.get("natural_on_ground", False)):
        ttl += float(cfg.rush_ttl_no_natural_bonus_s)
    if bool(rush_math.get("hard_rush", False)):
        ttl += float(cfg.rush_ttl_hard_rule_bonus_s)
    if bool(signals.get("main_army_refresh_evidence", False)):
        ttl += float(cfg.rush_ttl_main_army_no_nat_bonus_s)
    if int(rush_math.get("worker_deficit", 0) or 0) >= int(cfg.worker_under_count_tolerance) + 2:
        ttl += float(cfg.rush_ttl_worker_deficit_bonus_s)

    return float(_clamp(ttl, float(cfg.rush_ttl_min_s), float(cfg.rush_ttl_max_s)))


def derive_enemy_opening_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: OpeningIntelConfig = OpeningIntelConfig(),
) -> None:
    _sync_build_runner_scout_intel(bot=bot, awareness=awareness, now=now)
    store = EnemyRushStateStore(awareness=awareness)

    eb = attention.enemy_build
    workers_seen_now = int(
        max(
            sum_units(dict(getattr(eb, "enemy_units", {}) or {}), _WORKER_TYPES),
            sum_units(dict(getattr(eb, "enemy_units_main", {}) or {}), _WORKER_TYPES),
        )
    )
    workers_peak_seen = max(int(store.get_workers_peak_seen(now=now)), int(workers_seen_now))
    store.set_workers_peak_seen(now=now, value=int(workers_peak_seen))

    prev_state = store.get_rush_state(now=now)
    last_pressure_t = store.get_rush_last_seen_pressure_t(now=now)
    last_confirmed_t = float(awareness.mem.get(K("enemy", "rush", "last_confirmed_t"), now=now, default=0.0) or 0.0)
    decision = _evaluate_opening(
        now=now,
        attention=attention,
        cfg=cfg,
        enemy_race=str(getattr(getattr(bot, "enemy_race", None), "name", "UNKNOWN") or "UNKNOWN"),
        prev_rush_state=str(prev_state),
        last_pressure_t=float(last_pressure_t),
        workers_peak_seen=int(workers_peak_seen),
    )

    enemy_units = eb.enemy_units
    enemy_structs = eb.enemy_structures
    first_seen = store.get_opening_first_seen_t(now=now)
    saw_anything = (len(enemy_units) > 0) or (len(enemy_structs) > 0)
    if first_seen is None and saw_anything:
        store.set_opening_first_seen_t(now=now)

    if decision.rush_state == "ENDED":
        store.set_rush_ended(now=now, reason="pressure_clear_and_economy_recovered")

    rush_math = dict(decision.rush_math or {})
    signals = dict(decision.signals or {})
    last_seen_main_t = float(awareness.mem.get(K("enemy", "build", "last_seen_main_t"), now=now, default=0.0) or 0.0)
    scv_dispatched = bool(awareness.intel_scv_dispatched(now=now))
    scv_lost_early = bool(awareness.mem.get(K("intel", "scv", "lost_early"), now=now, default=False))
    reaper_done = bool(awareness.intel_last_reaper_scout_done_at(now=now) > 0.0)
    main_seen_recent = bool(float(last_seen_main_t) > 0.0 and (float(now) - float(last_seen_main_t)) <= 75.0)
    visible_non_worker_total = int(rush_math.get("visible_non_worker_total", 0) or 0)
    production_structures_visible = int(rush_math.get("production_structures_visible", 0) or 0)
    enemy_bases_visible = int(signals.get("enemy_bases_visible", 0) or 0)
    lings_seen = int((signals.get("seen_units", {}) or {}).get("lings", 0) or 0)
    structural_evidence = bool(rush_math.get("hard_rush", False)) or bool(rush_math.get("matched_timing_rules", []))
    no_natural_structural_confirmed = bool(
        float(now) <= float(cfg.rush_phase_max_s)
        and not bool(signals.get("natural_on_ground", False))
        and (
            bool(rush_math.get("hard_rush", False))
            or int(production_structures_visible) >= 3
            or int(visible_non_worker_total) >= 10
            or (
                int(production_structures_visible) >= 2
                and int(visible_non_worker_total) >= 6
            )
        )
    )
    scout_no_natural_suspected = bool(
        float(now) <= float(cfg.rush_phase_max_s)
        and scv_dispatched
        and not bool(signals.get("natural_on_ground", False))
        and (reaper_done or main_seen_recent or structural_evidence or int(visible_non_worker_total) >= 4)
    )
    scout_no_natural_confirmed = bool(
        scout_no_natural_suspected
        and (
            structural_evidence
            or int(production_structures_visible) >= 2
            or int(visible_non_worker_total) >= 6
        )
    )
    no_natural = not bool(signals.get("natural_on_ground", False))
    worker_deficit = int(rush_math.get("worker_deficit", 0) or 0)
    since_confirmed = max(0.0, float(now) - float(last_confirmed_t)) if float(last_confirmed_t) > 0.0 else 9999.0

    rush_state_out = str(decision.rush_state or "NONE").upper()
    rush_tier_out = str(getattr(decision, "rush_tier", "NONE") or "NONE").upper()
    rush_severity_out = float(getattr(decision, "rush_severity", 0.0) or 0.0)
    if scout_no_natural_confirmed or no_natural_structural_confirmed:
        rush_state_out = "CONFIRMED"
        rush_tier_out = "HEAVY" if rush_tier_out not in {"HEAVY", "EXTREME"} else rush_tier_out
        rush_severity_out = max(float(rush_severity_out), 0.84)
    elif scout_no_natural_suspected and rush_state_out in {"NONE", "ENDED"}:
        rush_state_out = "SUSPECTED"
        rush_tier_out = "MEDIUM" if rush_tier_out == "NONE" else rush_tier_out
        rush_severity_out = max(float(rush_severity_out), 0.56)
    if no_natural_structural_confirmed and (
        int(production_structures_visible) >= 4 or int(visible_non_worker_total) >= 12 or bool(rush_math.get("hard_rush", False))
    ):
        rush_tier_out = "EXTREME"
        rush_severity_out = max(float(rush_severity_out), 0.93)
    if structural_evidence and rush_state_out in {"NONE", "ENDED"}:
        rush_state_out = "HOLDING" if str(prev_state).upper() in {"CONFIRMED", "HOLDING"} else "SUSPECTED"
    if since_confirmed <= float(cfg.rush_confirmed_min_hold_s) and rush_state_out in {"NONE", "ENDED", "SUSPECTED"}:
        rush_state_out = "HOLDING"
    if (
        no_natural
        and structural_evidence
        and float(now) <= float(cfg.rush_structural_hold_s)
        and rush_state_out in {"NONE", "ENDED"}
    ):
        rush_state_out = "SUSPECTED"
    if (
        worker_deficit >= int(cfg.worker_under_count_tolerance)
        and float(now) <= float(cfg.rush_worker_deficit_hold_s)
        and (bool(signals.get("threatened", False)) or int(signals.get("enemy_near_our_bases", 0) or 0) > 0)
    ):
        if rush_state_out in {"NONE", "ENDED"}:
            rush_state_out = "SUSPECTED"
    early_visible_ling_flood = bool(
        float(now) <= float(cfg.rush_phase_max_s)
        and int(lings_seen) >= 6
        and int(enemy_bases_visible) <= 1
    )
    scout_loss_army_confirmed = bool(
        scv_lost_early
        and float(now) <= float(cfg.rush_phase_max_s)
        and (
            bool(structural_evidence)
            or (int(lings_seen) >= 6 and int(enemy_bases_visible) <= 1)
            or int(visible_non_worker_total) >= 8
            or (int(production_structures_visible) >= 2 and int(visible_non_worker_total) >= 5)
        )
    )
    scout_loss_army_suspected = bool(
        scv_lost_early
        and float(now) <= float(cfg.rush_phase_max_s)
        and (
            bool(structural_evidence)
            or int(lings_seen) >= 4
            or int(visible_non_worker_total) >= 5
            or int(enemy_bases_visible) <= 1
        )
    )
    if early_visible_ling_flood or scout_loss_army_confirmed:
        rush_state_out = "CONFIRMED"
        rush_tier_out = "HEAVY" if rush_tier_out not in {"HEAVY", "EXTREME"} else rush_tier_out
        rush_severity_out = max(float(rush_severity_out), 0.86)
    elif scout_loss_army_suspected and rush_state_out in {"NONE", "ENDED"}:
        rush_state_out = "SUSPECTED"
        rush_tier_out = "MEDIUM" if rush_tier_out == "NONE" else rush_tier_out
        rush_severity_out = max(float(rush_severity_out), 0.58)

    rush_is_early = bool(float(now) <= float(cfg.rush_phase_max_s))
    if (not rush_is_early) and rush_state_out in {"SUSPECTED", "CONFIRMED", "HOLDING"}:
        rush_state_out = "ENDED"

    last_seen_pressure_out = float(decision.last_seen_pressure_t)
    near_bases = int(signals.get("enemy_near_our_bases", 0) or 0)
    threatened = bool(signals.get("threatened", False))
    main_army_refresh = bool(signals.get("main_army_refresh_evidence", False))
    # Keep long TTL for no-natural + aggression evidence, but avoid refreshing forever from
    # "no natural + worker deficit" alone when we have zero direct pressure.
    if (structural_evidence and (threatened or near_bases > 0 or main_army_refresh)) or (
        main_army_refresh and no_natural
    ):
        last_seen_pressure_out = float(now)
    if bool(scout_no_natural_confirmed) or bool(no_natural_structural_confirmed):
        last_seen_pressure_out = float(now)
    if bool(early_visible_ling_flood) or bool(scout_loss_army_confirmed):
        last_seen_pressure_out = float(now)
    if rush_state_out == "CONFIRMED":
        store.set_rush_confirmed(now=now)

    store.set_opening_snapshot(
        now=now,
        ttl_s=float(cfg.ttl_s),
        kind=str(decision.kind),
        confidence=float(decision.confidence),
        signals=dict(decision.signals),
    )
    rush_ttl_s = _rush_snapshot_ttl_s(cfg=cfg, decision=decision)
    store.set_rush_snapshot(
        now=now,
        ttl_s=float(rush_ttl_s),
        state=str(rush_state_out),
        confidence=float(decision.rush_confidence),
        score=float(decision.rush_score),
        severity=float(rush_severity_out),
        tier=str(rush_tier_out),
        evidence=dict(decision.rush_math),
        last_seen_pressure_t=float(last_seen_pressure_out),
    )
    aggression_state = "NONE"
    if bool(signals.get("threatened", False)) or int(signals.get("enemy_near_our_bases", 0) or 0) > 0:
        aggression_state = "RUSH" if (rush_is_early and rush_state_out in {"SUSPECTED", "CONFIRMED", "HOLDING"}) else "AGGRESSION"
    aggression_confidence = float(
        _clamp(
            max(float(decision.rush_confidence), 0.20 + (0.10 * float(int(signals.get("enemy_near_our_bases", 0) or 0)))),
            0.05,
            0.99,
        )
    )
    awareness.mem.set(K("enemy", "aggression", "state"), value=str(aggression_state), now=now, ttl=float(cfg.ttl_s))
    awareness.mem.set(
        K("enemy", "aggression", "confidence"),
        value=float(aggression_confidence if aggression_state != "NONE" else 0.0),
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(
        K("enemy", "aggression", "source"),
        value={
            "rush_state": str(rush_state_out),
            "rush_is_early": bool(rush_is_early),
            "rush_tier": str(rush_tier_out),
            "rush_severity": float(rush_severity_out),
            "scout_no_natural_confirmed": bool(scout_no_natural_confirmed),
            "no_natural_structural_confirmed": bool(no_natural_structural_confirmed),
            "scv_lost_early": bool(scv_lost_early),
            "early_visible_ling_flood": bool(early_visible_ling_flood),
            "scout_loss_army_confirmed": bool(scout_loss_army_confirmed),
            "production_structures_visible": int(production_structures_visible),
            "visible_non_worker_total": int(visible_non_worker_total),
        },
        now=now,
        ttl=float(cfg.ttl_s),
    )
    awareness.mem.set(
        K("enemy", "rush", "scout_no_natural_confirmed"),
        value=bool(scout_no_natural_confirmed),
        now=now,
        ttl=float(rush_ttl_s),
    )
    awareness.mem.set(
        K("enemy", "rush", "no_natural_structural_confirmed"),
        value=bool(no_natural_structural_confirmed),
        now=now,
        ttl=float(rush_ttl_s),
    )
    awareness.mem.set(
        K("enemy", "rush", "scv_lost_early"),
        value=bool(scv_lost_early),
        now=now,
        ttl=float(rush_ttl_s),
    )
    # Periodic explicit intel log for rush/greedy classification observability.
    last_emit = float(
        awareness.mem.get(K("intel", "opening", "last_emit_t"), now=now, default=0.0) or 0.0
    )
    if (float(now) - float(last_emit)) >= float(cfg.log_interval_s):
        awareness.mem.set(K("intel", "opening", "last_emit_t"), value=float(now), now=now, ttl=None)
        if awareness.log is not None:
            awareness.log.emit(
                "opening_intel",
                {
                    "t": round(float(now), 2),
                    "kind": str(decision.kind),
                    "confidence": round(float(decision.confidence), 3),
                    "rush_state": str(rush_state_out),
                    "rush_confidence": round(float(decision.rush_confidence), 3),
                    "rush_score": round(float(decision.rush_score), 3),
                    "rush_severity": round(float(rush_severity_out), 3),
                    "rush_tier": str(rush_tier_out),
                    "scout_no_natural_confirmed": bool(scout_no_natural_confirmed),
                    "no_natural_structural_confirmed": bool(no_natural_structural_confirmed),
                    "production_structures_visible": int(production_structures_visible),
                    "visible_non_worker_total": int(visible_non_worker_total),
                    "rush_ttl_s": round(float(rush_ttl_s), 2),
                    "aggression_state": str(aggression_state),
                    "workers_peak_seen": int(workers_peak_seen),
                    "signals": dict(decision.signals),
                },
                meta={"module": "intel", "component": "intel.opening"},
            )
