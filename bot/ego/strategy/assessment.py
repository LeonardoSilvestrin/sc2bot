"""ASSESSMENT: how the game stands, from what Awareness believes.

Every value is continuous and every enemy value is an estimate:

- `threat_level` is Awareness' remembered danger at our most threatened base.
- `army_position` compares our army with the enemy army planned against: its
  estimate (never less than the prior that grows with game time) plus
  `commit_margin` of the part no contact places, so the fog is no advantage.
  Both armies carry `prior_power` Marines of doubt, so a skirmish between a
  few units is no verdict: (own - planned) / (own + planned + prior_power).
- `economy_position` compares our bases with the enemy bases believed: the
  townhalls remembered, never fewer than one base plus one per
  `enemy_base_interval` seconds, up to half the map's expansions.
- `enemy_vulnerability` is the share of the enemy army that died in our sight
  recently: lost / (lost + estimate), the losses fading with `loss_memory`.
- `setback` is the same share of our own army, counted in full when it
  traded evenly or worse and less as it traded better.
- `power_spike` joins a fresh upgrade -- each completed upgrade adds
  exp(-age / upgrade_window) to a sum saturated as 1 - exp(-sum) -- and supply
  close to the cap, where the army cannot grow any more (a ramp from
  `supply_spike_from` to `maxed_supply`): 1 - (1 - upgrades)(1 - supply).
- `confidence` is the share of the enemy army estimate backed by sightings,
  alive and not seen die; 1 while nothing is expected.

The model remembers only what the frame forgets: last frame's armies by tag
(to price a death), the losses on both sides and when each upgrade completed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ares.consts import TOWNHALL_TYPES
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.attention import AttentionState, UnitView, is_army
from bot.awareness import AwarenessState

from .model import GameAssessment

# A townhall in the air holds no base.
_BASES = TOWNHALL_TYPES - {UnitTypeId.COMMANDCENTERFLYING, UnitTypeId.ORBITALCOMMANDFLYING}


@dataclass(frozen=True, slots=True)
class AssessmentConfig:
    # The enemy army planned against is its estimate plus this share of the
    # part no contact places.
    commit_margin: float = 0.5
    # Power, in Marines, of doubt both armies carry.
    prior_power: float = 20.0
    # tau of a remembered loss, ours or the enemy's.
    loss_memory: float = 30.0
    # tau of a completed upgrade's spike.
    upgrade_window: float = 60.0
    # Supply where the spike of a capped army starts, and where it is full.
    supply_spike_from: float = 170.0
    maxed_supply: float = 190.0
    # The enemy is believed to take one more base every this many seconds.
    enemy_base_interval: float = 150.0

    def __post_init__(self) -> None:
        if min(self.commit_margin, self.prior_power) < 0.0:
            raise ValueError("commit_margin and prior_power must not be negative")
        for name in ("loss_memory", "upgrade_window", "enemy_base_interval"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")
        if not 0.0 <= self.supply_spike_from < self.maxed_supply <= 200.0:
            raise ValueError("supply_spike_from < maxed_supply must be in [0, 200]")


class AssessmentModel:
    def __init__(self, config: AssessmentConfig | None = None) -> None:
        self.config = config or AssessmentConfig()
        # Last frame's armies: power by tag.
        self._own: dict[int, float] = {}
        self._enemy: dict[int, float] = {}
        # Remembered losses, as of `_then`.
        self._own_lost = 0.0
        self._enemy_lost = 0.0
        self._then: float | None = None
        # When each upgrade completed; those done before the first frame never spike.
        self._upgraded_at: dict[UpgradeId, float] | None = None

    def assess(self, attention: AttentionState, awareness: AwarenessState) -> GameAssessment:
        config = self.config
        now = attention.time
        own_lost, enemy_lost = self._losses(attention)
        own = awareness.own_power
        estimated = awareness.estimated_enemy_power
        planned = estimated + config.commit_margin * awareness.enemy_uncertainty
        own_bases = float(len(attention.bases))
        known_bases = float(
            sum(
                1
                for contact in awareness.contacts
                if contact.is_structure and contact.type_id in _BASES
            )
        )
        expected_bases = min(
            max(1.0, 0.5 * len(attention.map.expansions)),
            1.0 + max(0.0, now) / config.enemy_base_interval,
        )
        enemy_bases = max(known_bases, expected_bases)
        fresh = self._fresh_upgrades(attention)
        upgrade_spike = 1.0 - math.exp(-fresh)
        supply_spike = _unit(
            (attention.supply_used - config.supply_spike_from)
            / (config.maxed_supply - config.supply_spike_from)
        )
        seen = max(awareness.enemy_power, awareness.seen_enemy_power)
        return GameAssessment(
            time=now,
            threat_level=awareness.danger,
            army_position=_position(own, planned, config.prior_power),
            economy_position=_position(own_bases, enemy_bases, 0.0),
            enemy_vulnerability=enemy_lost / (enemy_lost + estimated) if enemy_lost > 0.0 else 0.0,
            power_spike=1.0 - (1.0 - upgrade_spike) * (1.0 - supply_spike),
            confidence=min(1.0, seen / estimated) if estimated > 0.0 else 1.0,
            setback=(
                own_lost / (own_lost + own) * min(1.0, 2.0 * own_lost / (own_lost + enemy_lost))
                if own_lost > 0.0
                else 0.0
            ),
            upgrade_spike=upgrade_spike,
            supply_spike=supply_spike,
            inputs=(
                ("danger", awareness.danger),
                ("danger_now", awareness.danger_now),
                ("own_power", own),
                ("enemy_power", awareness.enemy_power),
                ("seen_enemy_power", awareness.seen_enemy_power),
                ("expected_enemy_power", awareness.expected_enemy_power),
                ("estimated_enemy_power", estimated),
                ("enemy_uncertainty", awareness.enemy_uncertainty),
                ("planned_enemy_power", planned),
                ("own_lost", own_lost),
                ("enemy_lost", enemy_lost),
                ("own_bases", own_bases),
                ("known_enemy_bases", known_bases),
                ("expected_enemy_bases", expected_bases),
                ("fresh_upgrades", fresh),
                ("supply_used", attention.supply_used),
            ),
        )

    def _losses(self, attention: AttentionState) -> tuple[float, float]:
        """The army power remembered lost, ours and the enemy's: what died
        this frame, priced as it stood last frame, on top of the faded past."""

        now = attention.time
        fade = (
            0.0
            if self._then is None
            else math.exp(-max(0.0, now - self._then) / self.config.loss_memory)
        )
        dead = attention.dead_tags
        self._own_lost = self._own_lost * fade + sum(
            power for tag, power in self._own.items() if tag in dead
        )
        self._enemy_lost = self._enemy_lost * fade + sum(
            power for tag, power in self._enemy.items() if tag in dead
        )
        self._then = now
        self._own = _army(attention.own_units)
        self._enemy = _army(attention.enemy_units)
        return self._own_lost, self._enemy_lost

    def _fresh_upgrades(self, attention: AttentionState) -> float:
        """sum(exp(-age / upgrade_window)) of the upgrades completed so far."""

        now = attention.time
        if self._upgraded_at is None:
            self._upgraded_at = dict.fromkeys(attention.upgrades, -math.inf)
        for upgrade in attention.upgrades:
            self._upgraded_at.setdefault(upgrade, now)
        window = self.config.upgrade_window
        return sum(
            math.exp(-max(0.0, now - done) / window)
            for done in self._upgraded_at.values()
            if done > -math.inf
        )


def _army(units: tuple[UnitView, ...]) -> dict[int, float]:
    return {unit.tag: unit.power for unit in units if is_army(unit) and unit.power > 0.0}


def _position(own: float, other: float, prior: float) -> float:
    total = own + other + prior
    return (own - other) / total if total > 0.0 else 0.0


def _unit(value: float) -> float:
    return min(1.0, max(0.0, value))
