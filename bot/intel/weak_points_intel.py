from __future__ import annotations

from bot.intel.utils.state_store import EnemyWeakPointsStateStore
from bot.intel.utils.weak_points_policy import WeakPointsPolicy
from bot.intel.utils.weak_points_types import WeakPointsIntelConfig
from bot.mind.awareness import Awareness


def derive_enemy_weak_points_intel(
    bot,
    *,
    awareness: Awareness,
    now: float,
    cfg: WeakPointsIntelConfig = WeakPointsIntelConfig(),
) -> None:
    store = EnemyWeakPointsStateStore(awareness=awareness)
    policy = WeakPointsPolicy()
    decision = policy.evaluate(bot)
    payload = decision.payload(now=now)
    store.set_weak_points_snapshot(
        now=now,
        ttl_s=float(cfg.ttl_s),
        payload=payload,
        points=list(decision.points),
        primary=decision.primary,
    )
