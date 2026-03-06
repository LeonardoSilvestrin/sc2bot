from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.intel.utils.enemy_econ_estimates import sum_units
from bot.intel.utils.opening_policy import OpeningIntelPolicy
from bot.intel.utils.opening_types import OpeningIntelConfig
from bot.intel.utils.state_store import EnemyRushStateStore
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K

_WORKER_TYPES = (U.SCV, U.PROBE, U.DRONE)


@dataclass(frozen=True)
class OpeningExitRule:
    min_time_s: float
    max_time_s: float
    min_units: Dict[U, int]
    min_structures_ready: Dict[U, int]
    require_any_addon: bool = False


DEFAULT_OPENING_EXIT_RULE = OpeningExitRule(
    min_time_s=95.0,
    max_time_s=260.0,
    min_units={},
    min_structures_ready={U.BARRACKS: 1, U.FACTORY: 1},
    require_any_addon=False,
)

OPENING_EXIT_RULES_BY_NAME: dict[str, OpeningExitRule] = {
    "MechaOpen": OpeningExitRule(
        min_time_s=65.0,
        max_time_s=210.0,
        min_units={U.REAPER: 1, U.HELLION: 2},
        min_structures_ready={U.FACTORY: 1},
        require_any_addon=True,
    ),
}


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(v)))


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


def _unit_count_including_pending(bot, unit_id: U) -> int:
    ready = 0
    pending = 0
    try:
        ready = int(bot.units(unit_id).amount)
    except Exception:
        ready = 0
    try:
        pending = int(bot.already_pending(unit_id) or 0)
    except Exception:
        pending = 0
    return int(ready + pending)


def _structure_ready_count(bot, structure_id: U) -> int:
    try:
        return int(bot.structures(structure_id).ready.amount)
    except Exception:
        return 0


def _has_any_ready_addon(bot) -> bool:
    addons = (U.BARRACKSREACTOR, U.BARRACKSTECHLAB, U.FACTORYREACTOR, U.FACTORYTECHLAB, U.STARPORTREACTOR, U.STARPORTTECHLAB)
    try:
        return any(int(bot.structures(addon).ready.amount) > 0 for addon in addons)
    except Exception:
        return False


def _opening_rule_done(bot, *, rule: OpeningExitRule, now: float) -> bool:
    if float(now) < float(rule.min_time_s):
        return False
    if float(now) >= float(rule.max_time_s):
        return True

    for unit_id, required in dict(rule.min_units).items():
        if int(_unit_count_including_pending(bot, unit_id)) < int(required):
            return False
    for structure_id, required in dict(rule.min_structures_ready).items():
        if int(_structure_ready_count(bot, structure_id)) < int(required):
            return False
    if bool(rule.require_any_addon) and not bool(_has_any_ready_addon(bot)):
        return False
    return True


def derive_opening_contract_intel(bot, *, awareness: Awareness, now: float) -> None:
    bor = getattr(bot, "build_order_runner", None)
    done = bool(getattr(bor, "build_completed", False)) if bor is not None else False
    done_reason = "build_runner"
    if bor is not None and not bool(done):
        chosen_opening = str(getattr(bor, "chosen_opening", "") or "").strip()
        rule = OPENING_EXIT_RULES_BY_NAME.get(chosen_opening, DEFAULT_OPENING_EXIT_RULE)
        if _opening_rule_done(bot, rule=rule, now=float(now)):
            try:
                bor.set_build_completed()
                done = True
                done_reason = f"opening_signature:{chosen_opening or 'default'}"
            except Exception:
                pass
    awareness.mem.set(K("macro", "opening", "done"), value=bool(done), now=float(now), ttl=5.0)
    awareness.mem.set(K("macro", "opening", "done_reason"), value=str(done_reason), now=float(now), ttl=5.0)
    awareness.mem.set(K("macro", "opening", "done_owner"), value="intel.opening_contract", now=float(now), ttl=5.0)


def derive_enemy_opening_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: OpeningIntelConfig = OpeningIntelConfig(),
) -> None:
    store = EnemyRushStateStore(awareness=awareness)
    policy = OpeningIntelPolicy(cfg=cfg)

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
    decision = policy.evaluate(
        now=now,
        attention=attention,
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

    if decision.rush_state == "CONFIRMED":
        store.set_rush_confirmed(now=now)
    if decision.rush_state == "ENDED":
        store.set_rush_ended(now=now, reason="pressure_clear_and_economy_recovered")

    rush_math = dict(decision.rush_math or {})
    signals = dict(decision.signals or {})
    structural_evidence = bool(rush_math.get("hard_rush", False)) or bool(rush_math.get("matched_timing_rules", []))
    no_natural = not bool(signals.get("natural_on_ground", False))
    worker_deficit = int(rush_math.get("worker_deficit", 0) or 0)
    since_confirmed = max(0.0, float(now) - float(last_confirmed_t)) if float(last_confirmed_t) > 0.0 else 9999.0

    rush_state_out = str(decision.rush_state or "NONE").upper()
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
        value={"rush_state": str(rush_state_out), "rush_is_early": bool(rush_is_early)},
        now=now,
        ttl=float(cfg.ttl_s),
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
                    "rush_ttl_s": round(float(rush_ttl_s), 2),
                    "aggression_state": str(aggression_state),
                    "workers_peak_seen": int(workers_peak_seen),
                    "signals": dict(decision.signals),
                },
                meta={"module": "intel", "component": "intel.opening"},
            )
