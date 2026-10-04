"""Investment: how much goes to workers, bases, gas and production.

Nothing here depends on which army is built; that is the army style's
(`styles`). The opening belongs to Ares' build runner, and this decides when
the macro plan takes over from it.

How greedy the plan is follows Strategy's posture, read here:

- DEFEND: every resource goes to the army -- no expansion, and the planner
  drops upgrades and add-ons.
- RECOVER and COMMIT: no expansion; the army is rebuilt, or the window is
  spent on it. Upgrades and add-ons go on.
- DEVELOP: expand once the mineral lines are saturated.
- PRESSURE: the same, and like COMMIT it accepts a larger military
  commitment: the production ceiling grows to `offensive_production_per_base`
  per base.

The opening is a fixed script and cannot answer an attack. If Strategy
latches an emergency (a DEFEND that met an emergency threat) before the
opening is over, the plan interrupts it: from that frame on this plan runs,
spending on the army first.

A script can also stall. Ares' build runner stopped at the third gas of the
mech opening in `bench/ci-mech/003` and `004` and never moved on: the bank grew
to 9,415 and 2,125 minerals with two units of army. Seventeen openings that
ran through (`bench/6f`, `ci-bio`, `ci-mech`) never held more than 680 -- what
they save for the natural -- so a bank of `OPENING_STALL_BANK` means the
script stopped, and the plan takes over.

Ares adds production as income allows, up to a ceiling per structure type. A
fixed ceiling of 12 Barracks capped the army's growth once the bot had more
than three bases (`bench/7b`), so the ceiling grows with the bases.

The gas target was one Refinery per twelve workers, so it stopped at seven
while the bot held six bases with twelve geysers (`bench/base3`, all nine
games). In the 300-700 s window those games spent 5-30 samples with less than
100 gas and more than 800 minerals banked, and not one sample the other way
around: gas was the binding resource exactly while the army and the upgrades
were being paid for. A Refinery is mined by three workers, so the target is
every geyser of the bases held, as long as at most `GAS_WORKER_SHARE` of the
workers is mining gas.

The bot expanded while its mineral lines were saturated, and saturation was
`MINERAL_WORKERS_PER_BASE` workers per base held. That count passes
`MAX_WORKERS` at five bases, so from the sixth on the test compared the
workforce against a number the same plan never builds: all nine games of
`bench/base3` asked for their last base at 494-570 s and then held six for the
205-693 s that were left, banking 7,585-18,850 minerals. Saturation is measured
against the workforce the plan itself asks for, and the bases the map offers
bound the target.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.attention import AttentionState
from bot.ego.strategy import StrategicIntent, StrategicPosture

# Minerals no opening that runs ever holds.
OPENING_STALL_BANK = 1000
MAX_WORKERS = 80
# 16 on minerals and 6 on gas.
WORKERS_PER_BASE = 22
MINERAL_WORKERS_PER_BASE = 16
# The geysers of a base on the ladder maps.
GAS_BUILDINGS_PER_BASE = 2
# A Refinery is mined by three workers (Ares' `Mining.workers_per_gas`).
WORKERS_PER_GAS_BUILDING = 3
# The most of the workforce that may be mining gas: with 83 workers, 33 of
# them in eleven Refineries and 50 left on the mineral lines.
GAS_WORKER_SHARE = 0.4
# Ares' default ceiling of 12 production structures of a type, per three bases ...
PRODUCTION_PER_BASE = 4
# ... and one more per base while pressuring or committing.
OFFENSIVE_PRODUCTION_PER_BASE = 5
# The postures that take a base once the mineral lines are saturated.
_EXPANDING = frozenset({StrategicPosture.DEVELOP, StrategicPosture.PRESSURE})


@dataclass(frozen=True, slots=True)
class InvestmentConfig:
    opening_stall_bank: int = OPENING_STALL_BANK
    max_workers: int = MAX_WORKERS
    workers_per_base: int = WORKERS_PER_BASE
    mineral_workers_per_base: int = MINERAL_WORKERS_PER_BASE
    gas_buildings_per_base: int = GAS_BUILDINGS_PER_BASE
    workers_per_gas_building: int = WORKERS_PER_GAS_BUILDING
    gas_worker_share: float = GAS_WORKER_SHARE
    production_per_base: int = PRODUCTION_PER_BASE
    offensive_production_per_base: int = OFFENSIVE_PRODUCTION_PER_BASE

    def __post_init__(self) -> None:
        counts = (
            self.opening_stall_bank,
            self.max_workers,
            self.workers_per_base,
            self.mineral_workers_per_base,
            self.gas_buildings_per_base,
            self.workers_per_gas_building,
            self.production_per_base,
        )
        if min(counts) <= 0:
            raise ValueError("investment counts must be positive")
        if self.offensive_production_per_base < self.production_per_base:
            raise ValueError("offensive_production_per_base must not be below production_per_base")
        if not 0.0 < self.gas_worker_share <= 1.0:
            raise ValueError("gas_worker_share must be in (0, 1]")


@dataclass(frozen=True, slots=True)
class Investment:
    # False while Ares' build runner still plays the opening.
    active: bool
    workers: int
    gas: int
    bases: int
    expand: bool
    # Every resource goes to the army: no upgrade, no add-on for throughput.
    defending: bool
    # Stop Ares' build runner: the opening is over from this frame on.
    interrupt_opening: bool
    max_production: int
    reason: str
    inputs: tuple[tuple[str, float], ...] = ()


def plan(
    attention: AttentionState,
    intent: StrategicIntent,
    config: InvestmentConfig | None = None,
) -> Investment:
    config = config or InvestmentConfig()
    posture = intent.posture
    bases = max(1, len(attention.bases))
    # The workforce the plan will actually build; past `MAX_WORKERS` the
    # mineral lines stay open but no worker is ever added to fill them, and a
    # base beyond that is still worth taking: the patches held run down and
    # every base raises the production ceiling.
    saturated_at = min(config.max_workers, config.mineral_workers_per_base * bases)
    saturated = attention.workers >= saturated_at
    lines_full = attention.workers >= config.mineral_workers_per_base * bases
    # A physical constraint before the score: the map has this many places to
    # put a townhall, the bases held included.
    sites = len(attention.map.expansions)
    room = bases < sites
    greedy = posture in _EXPANDING
    expand = intent.economy >= 0.5 and saturated and room and greedy
    wanted_bases = bases + (1 if expand else 0)
    gas_workers = int(attention.workers * config.gas_worker_share)
    gas_buildings = min(
        config.gas_buildings_per_base * bases,
        gas_workers // config.workers_per_gas_building,
    )
    defending = posture is StrategicPosture.DEFEND
    emergency = intent.emergency
    per_base = (
        config.offensive_production_per_base if posture.offensive else config.production_per_base
    )
    stalled = attention.minerals >= config.opening_stall_bank
    interrupt = not attention.opening_done and (emergency or stalled)
    active = attention.opening_done or interrupt
    if interrupt:
        reason = "opening_interrupted" if emergency else "opening_stalled"
    elif not active:
        reason = "opening_runs"
    elif defending:
        reason = "defend_spend_on_army"
    elif not greedy:
        reason = f"{posture.value.lower()}_army_first"
    elif expand:
        reason = "mineral_lines_saturated" if lines_full else "worker_cap_reached"
    elif saturated and not room:
        reason = "no_expansion_left"
    else:
        reason = "build_economy"
    return Investment(
        active=active,
        workers=min(config.max_workers, config.workers_per_base * wanted_bases),
        gas=gas_buildings,
        bases=wanted_bases,
        expand=expand,
        defending=defending,
        interrupt_opening=interrupt,
        max_production=per_base * bases,
        reason=reason,
        inputs=(
            ("workers", float(attention.workers)),
            ("bases", float(bases)),
            ("saturated_at", float(saturated_at)),
            ("expansion_sites", float(sites)),
            ("strategy_economy", intent.economy),
            ("danger", intent.defense),
            ("production_per_base", float(per_base)),
            ("gas_worker_share", config.gas_worker_share),
        ),
    )
