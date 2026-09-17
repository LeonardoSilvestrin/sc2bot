"""Economy: how much to invest in workers, bases and army after the opening.

The opening belongs to Ares' build runner. Afterwards this turns Strategy's
preferences into an `EconomyPlan`, which the Body's economy behavior runs as
Ares macro behaviors.

After the opening, Command Centers become Orbital Commands and every Orbital's
energy goes to MULEs. The upgrades of the composition are researched in
`UPGRADES` order -- except while stabilizing, when every resource goes to the
army.
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

MAX_WORKERS = 80
# 16 on minerals and 6 on gas.
WORKERS_PER_BASE = 22
MINERAL_WORKERS_PER_BASE = 16
WORKERS_PER_GAS_BUILDING = 12


def plan(attention: AttentionState, strategy: StrategyState) -> EconomyPlan:
    bases = max(1, len(attention.bases))
    saturated_at = MINERAL_WORKERS_PER_BASE * bases
    saturated = attention.workers >= saturated_at
    expand = strategy.economy >= 0.5 and saturated
    wanted_bases = bases + (1 if expand else 0)
    stabilizing = strategy.objective is Objective.STABILIZE
    if not attention.opening_done:
        reason = "opening_runs"
    elif stabilizing:
        reason = "stabilize_spend_on_army"
    elif expand:
        reason = "mineral_lines_saturated"
    else:
        reason = "build_economy"
    return EconomyPlan(
        active=attention.opening_done,
        workers=min(MAX_WORKERS, WORKERS_PER_BASE * wanted_bases),
        gas=min(2 * bases, 1 + attention.workers // WORKERS_PER_GAS_BUILDING),
        bases=wanted_bases,
        expand=expand,
        freeflow=stabilizing,
        composition=COMPOSITION,
        reason=reason,
        inputs=(
            ("workers", float(attention.workers)),
            ("bases", float(bases)),
            ("saturated_at", float(saturated_at)),
            ("strategy_economy", strategy.economy),
            ("upgrades_done", float(sum(item in attention.upgrades for item in UPGRADES))),
        ),
        upgrades=UPGRADES if attention.opening_done and not stabilizing else (),
        orbitals=attention.opening_done,
        mules=attention.opening_done,
    )
