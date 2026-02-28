from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.intel.utils.opening_policy import OpeningIntelPolicy, sum_units
from bot.intel.utils.opening_types import OpeningIntelConfig
from bot.intel.utils.state_store import EnemyRushStateStore
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness

_WORKER_TYPES = (U.SCV, U.PROBE, U.DRONE)


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
    decision = policy.evaluate(
        now=now,
        attention=attention,
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

    store.set_opening_snapshot(
        now=now,
        ttl_s=float(cfg.ttl_s),
        kind=str(decision.kind),
        confidence=float(decision.confidence),
        signals=dict(decision.signals),
    )
    store.set_rush_snapshot(
        now=now,
        ttl_s=float(cfg.ttl_s),
        state=str(decision.rush_state),
        confidence=float(decision.rush_confidence),
        score=float(decision.rush_score),
        evidence=dict(decision.rush_math),
        last_seen_pressure_t=float(decision.last_seen_pressure_t),
    )
