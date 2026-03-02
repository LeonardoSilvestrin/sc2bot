from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.intel.utils.enemy_econ_estimates import sum_units
from bot.intel.utils.opening_policy import OpeningIntelPolicy
from bot.intel.utils.opening_types import OpeningIntelConfig
from bot.intel.utils.state_store import EnemyRushStateStore
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K

_WORKER_TYPES = (U.SCV, U.PROBE, U.DRONE)


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
    if no_natural and float(now) <= float(cfg.rush_structural_hold_s) and rush_state_out in {"NONE", "ENDED"}:
        rush_state_out = "SUSPECTED"
    if worker_deficit >= int(cfg.worker_under_count_tolerance) and float(now) <= float(cfg.rush_worker_deficit_hold_s):
        if rush_state_out in {"NONE", "ENDED"}:
            rush_state_out = "SUSPECTED"

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
                    "workers_peak_seen": int(workers_peak_seen),
                    "signals": dict(decision.signals),
                },
                meta={"module": "intel", "component": "intel.opening"},
            )
