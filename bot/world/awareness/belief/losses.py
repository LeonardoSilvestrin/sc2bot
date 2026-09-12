from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from bot.world.attention import WorldFacts
from bot.world.awareness.enemy import EnemySighting


@dataclass(frozen=True, slots=True)
class LossLedger:
    """Supply and workers each side lost lately, fading as both rebuild.

    Supply counts every unit, workers included. The trade is what moves the
    size we assume for an enemy we cannot see: an even game where we lost
    20 supply more than they did is no longer even.
    """

    own_supply: float = 0.0
    own_workers: float = 0.0
    enemy_supply: float = 0.0
    enemy_workers: float = 0.0

    @property
    def supply_trade(self) -> float:
        """Positive when we lost more supply than the enemy did."""

        return self.own_supply - self.enemy_supply

    @property
    def worker_trade(self) -> float:
        """Positive when we lost more workers than the enemy did."""

        return self.own_workers - self.enemy_workers


class LossTracker:
    """Books deaths the game reports into a decaying ``LossLedger``.

    Our own losses are the tags reported dead that were ours on the previous
    update; a unit loading into a bunker or transport disappears without
    dying and is not counted. ``recovery_time_constant`` is how long a trade
    keeps mattering: lost supply gets rebuilt.
    """

    def __init__(self, *, recovery_time_constant: float = 120.0) -> None:
        if recovery_time_constant <= 0.0:
            raise ValueError("recovery_time_constant must be positive")
        self.recovery_time_constant = float(recovery_time_constant)
        self._ledger = LossLedger()
        self._updated_at: float | None = None
        self._own_units: dict[int, tuple[float, bool]] = {}

    def update(
        self, world: WorldFacts, *, enemy_died: Iterable[EnemySighting]
    ) -> LossLedger:
        keep = (
            1.0
            if self._updated_at is None
            else math.exp(
                -max(0.0, world.time - self._updated_at)
                / self.recovery_time_constant
            )
        )
        own_dead = tuple(
            self._own_units[tag]
            for tag in world.dead_unit_tags
            if tag in self._own_units
        )
        enemy_dead = tuple(enemy_died)
        ledger = self._ledger
        self._ledger = LossLedger(
            own_supply=ledger.own_supply * keep
            + sum(supply for supply, _ in own_dead),
            own_workers=ledger.own_workers * keep
            + sum(1 for _, is_worker in own_dead if is_worker),
            enemy_supply=ledger.enemy_supply * keep
            + sum(sighting.supply_cost for sighting in enemy_dead),
            enemy_workers=ledger.enemy_workers * keep
            + sum(1 for sighting in enemy_dead if sighting.is_worker),
        )
        self._updated_at = world.time
        self._own_units = {
            unit.tag: (unit.supply_cost, unit.is_worker) for unit in world.own_units
        }
        return self._ledger
