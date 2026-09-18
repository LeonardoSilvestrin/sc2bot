"""Economy: how much to invest in workers, bases and army after the opening.

The opening belongs to Ares' build runner. Afterwards this turns Strategy's
preferences into an `EconomyPlan`, which the Body's economy behavior runs as
Ares macro behaviors.

After the opening, Command Centers become Orbital Commands and every Orbital's
energy goes to MULEs. The upgrades of the composition are researched in
`UPGRADES` order -- except while stabilizing, when every resource goes to the
army.

The opening is a fixed script and cannot answer an attack. If the bot is
stabilizing against a threat of at least `OPENING_ABORT_DANGER` before the
opening is over, the plan interrupts it: from that frame on this plan runs,
spending on the army first.

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

A Barracks with a Reactor trains two Marines at a time, and 5 of the 12
Barracks of `bench/7b/001` never got an add-on while the bank grew past 9,900
minerals with supply free. Once the opening is over, and while nothing is being
stabilized, every Barracks with no add-on should take a Reactor -- except
`TECHLAB_RESERVE` of them, which stay free for the Tech Labs Ares adds when the
composition asks for Marauders.

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

from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.attention import AttentionState
from bot.ego.planners import EconomyPlan
from bot.ego.strategy import Objective, StrategyState

COMPOSITION: tuple[tuple[UnitTypeId, float, int], ...] = (
    (UnitTypeId.MARINE, 0.55, 2),
    (UnitTypeId.MARAUDER, 0.2, 1),
    (UnitTypeId.SIEGETANK, 0.15, 0),
    (UnitTypeId.MEDIVAC, 0.1, 1),
)

# Bio research first, then infantry weapons and armor level by level; the tanks'
# weapons come after the second infantry level.
UPGRADES: tuple[UpgradeId, ...] = (
    UpgradeId.STIMPACK,
    UpgradeId.SHIELDWALL,
    UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
    UpgradeId.PUNISHERGRENADES,
    UpgradeId.TERRANINFANTRYARMORSLEVEL1,
    UpgradeId.TERRANINFANTRYWEAPONSLEVEL2,
    UpgradeId.TERRANINFANTRYARMORSLEVEL2,
    UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,
    UpgradeId.TERRANINFANTRYWEAPONSLEVEL3,
    UpgradeId.TERRANINFANTRYARMORSLEVEL3,
    UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,
    UpgradeId.TERRANVEHICLEWEAPONSLEVEL3,
)

# The remembered threat, in [0, 1], that ends the opening while stabilizing:
# the strategy's emergency level.
OPENING_ABORT_DANGER = 0.6
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
# Ares' default ceiling of 12 production structures of a type, per three bases.
PRODUCTION_PER_BASE = 4
# Barracks left without an add-on for Ares' Tech Labs. One is enough: Ares adds
# a Tech Lab to the first idle Barracks with no add-on, one per frame.
TECHLAB_RESERVE = 1


def plan(attention: AttentionState, strategy: StrategyState) -> EconomyPlan:
    bases = max(1, len(attention.bases))
    # The workforce the plan will actually build; past `MAX_WORKERS` the
    # mineral lines stay open but no worker is ever added to fill them, and a
    # base beyond that is still worth taking: the patches held run down and
    # every base raises the production ceiling.
    saturated_at = min(MAX_WORKERS, MINERAL_WORKERS_PER_BASE * bases)
    saturated = attention.workers >= saturated_at
    lines_full = attention.workers >= MINERAL_WORKERS_PER_BASE * bases
    # A physical constraint before the score: the map has this many places to
    # put a townhall, the bases held included.
    sites = len(attention.map.expansions)
    room = bases < sites
    expand = strategy.economy >= 0.5 and saturated and room
    wanted_bases = bases + (1 if expand else 0)
    gas_workers = int(attention.workers * GAS_WORKER_SHARE)
    gas_buildings = min(
        GAS_BUILDINGS_PER_BASE * bases, gas_workers // WORKERS_PER_GAS_BUILDING
    )
    stabilizing = strategy.objective is Objective.STABILIZE
    interrupt = (
        not attention.opening_done and stabilizing and strategy.defense >= OPENING_ABORT_DANGER
    )
    active = attention.opening_done or interrupt
    if interrupt:
        reason = "opening_interrupted"
    elif not active:
        reason = "opening_runs"
    elif stabilizing:
        reason = "stabilize_spend_on_army"
    elif expand:
        reason = "mineral_lines_saturated" if lines_full else "worker_cap_reached"
    elif saturated and not room:
        reason = "no_expansion_left"
    else:
        reason = "build_economy"
    return EconomyPlan(
        active=active,
        workers=min(MAX_WORKERS, WORKERS_PER_BASE * wanted_bases),
        gas=gas_buildings,
        bases=wanted_bases,
        expand=expand,
        freeflow=stabilizing,
        composition=COMPOSITION,
        reason=reason,
        inputs=(
            ("workers", float(attention.workers)),
            ("bases", float(bases)),
            ("saturated_at", float(saturated_at)),
            ("expansion_sites", float(sites)),
            ("strategy_economy", strategy.economy),
            ("upgrades_done", float(sum(item in attention.upgrades for item in UPGRADES))),
            ("danger", strategy.defense),
            ("production_per_base", float(PRODUCTION_PER_BASE)),
            ("techlab_reserve", float(TECHLAB_RESERVE)),
            ("gas_worker_share", GAS_WORKER_SHARE),
        ),
        upgrades=UPGRADES if active and not stabilizing else (),
        orbitals=active,
        mules=active,
        interrupt_opening=interrupt,
        max_production=PRODUCTION_PER_BASE * bases,
        # A Reactor is an investment in throughput: while stabilizing, every
        # resource goes to the army instead, as with the upgrades.
        reactors=active and not stabilizing,
        techlab_reserve=TECHLAB_RESERVE,
    )
