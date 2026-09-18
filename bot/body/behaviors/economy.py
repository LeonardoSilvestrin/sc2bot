"""Economy: the workers mine, and the economy plan runs as Ares macro behaviors.

Mining always runs; a worker the Engine released goes back to the GATHERING
role, so Mining takes it again. The macro plan runs only once the opening is
over.

Ares' SpawnController skips a unit type once its share of the army is met,
counting what is in production. When every type of the composition is met at
once -- counts an exact multiple of the proportions, like 11 Marines, 4
Marauders, 3 Siege Tanks and 2 Medivacs for 0.55/0.2/0.15/0.1 -- it trains
nothing at all, and the army stops growing until a unit dies. That frame it
spends freely instead: whatever it trains takes the counts off the multiple.

A plan that interrupts the opening stops Ares' build runner before anything
else, so the macro plan takes over that same frame.

`ExactResearch` runs right before Ares' UpgradeController. The
UpgradeController orders `unit.research(upgrade)`, which python-sc2 resolves
through the game's data, while it checks the structure for the ability of
python-sc2's own research table. For the vehicle and ship plating the two
differ: the game dropped the order, the UpgradeController "researched" it again
every frame from 7:14 on (950 times in `bench/smoke-mech`), and since Ares'
MacroPlan stops at the first behavior that acts, nothing after it -- the army
above all -- was bought for the rest of the game. `ExactResearch` orders the
ability of the table for those upgrades only, so the structure is busy and the
UpgradeController passes.

Add-ons run before the MacroPlan, outside it, one per frame: an idle
production structure of the plan's type with no add-on takes a Reactor while
fewer than `reactor_share` of them carry one, and a Tech Lab otherwise. Inside
the MacroPlan they came after the SpawnController, which acts whenever
production is idle and the bank is up, so they almost never ran: at 502 s of
`bench/ci-mech/000` 9 of 13 Factories had no add-on, one had a Tech Lab, and
not one Cyclone was built all game. An add-on ordered on a structure the
SpawnController then orders to train is lost -- the last order wins
(`bench/7/002`) -- so the SpawnController is told to leave that structure
alone this frame (`ignored_build_from_tags`). An add-on the game refuses (no
room beside the structure) is ordered again later and starves nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro import (
    AutoSupply,
    BuildWorkers,
    ExpansionController,
    GasBuildingController,
    MacroPlan,
    Mining,
    ProductionController,
    SpawnController,
    UpgradeCCs,
    UpgradeController,
)
from ares.behaviors.macro.macro_behavior import MacroBehavior
from ares.consts import UnitRole
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bot.attention import AttentionState
from bot.body.engine import EngineResult
from bot.ego.planners import EconomyPlan

# SpawnController's guard against an empty army in its share test.
_EMPTY_ARMY = 1e-16
# Energy a MULE costs.
MULE_ENERGY = 50.0
# A mineral field this close to a townhall is mined from it.
MINING_DISTANCE = 10.0


# The (Reactor, Tech Lab) each production structure builds.
ADD_ONS = {
    UnitTypeId.BARRACKS: (UnitTypeId.BARRACKSREACTOR, UnitTypeId.BARRACKSTECHLAB),
    UnitTypeId.FACTORY: (UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB),
    UnitTypeId.STARPORT: (UnitTypeId.STARPORTREACTOR, UnitTypeId.STARPORTTECHLAB),
}


def add_add_on(bot, structure: UnitTypeId, reactor_share: float) -> int | None:
    """An add-on on the ready, idle `structure` with no add-on of lowest tag:
    a Reactor while one more keeps the Reactors within `reactor_share` of every
    `structure`, a Tech Lab otherwise. Returns the tag ordered, if any."""

    reactor, techlab = ADD_ONS[structure]
    structures = bot.mediator.get_own_structures_dict
    free = [
        building
        for building in structures[structure]
        if building.is_ready and building.is_idle and not building.has_add_on
    ]
    if not free:
        return None
    wanted = reactor if len(structures[reactor]) + 1 <= reactor_share * len(
        structures[structure]
    ) else techlab
    if not bot.can_afford(wanted):
        return None
    building = min(free, key=lambda item: item.tag)
    building.build(wanted)
    return building.tag


@dataclass
class ExactResearch(MacroBehavior):
    """Walks `upgrades` in order, as Ares' UpgradeController does. An upgrade
    whose research ability in the game's data is the one its structure offers
    is Ares': if a structure could start it now, this yields to Ares. Any
    other is ordered here by the ability its structure offers. The order of
    the list holds: in `bench/smoke-mech2` walking past Ares' upgrades let the
    plating take the only Armory ahead of the weapons, and the weapons were
    never researched."""

    upgrades: tuple[UpgradeId, ...] = ()

    def execute(self, ai, config, mediator) -> bool:
        for upgrade in self.upgrades:
            if upgrade in ai.state.upgrades:
                continue
            source = UPGRADE_RESEARCHED_FROM[upgrade]
            ability = RESEARCH_INFO[source][upgrade]["ability"]
            structures = mediator.get_own_structures_dict[source]
            if any(order.ability.exact_id == ability for s in structures for order in s.orders):
                continue
            idle = [s for s in structures if s.is_ready and s.is_idle and ability in s.abilities]
            if ai.game_data.upgrades[upgrade.value].research_ability.exact_id == ability:
                if idle:
                    return False
                continue
            if idle and ai.can_afford(upgrade):
                min(idle, key=lambda structure: structure.tag)(ability)
                return True
        return False


@dataclass(frozen=True, slots=True)
class SpawnMode:
    """How the plan's composition went to Ares' SpawnController this frame."""

    freeflow: bool
    # plan_inactive, plan_freeflow, composition_met or composition_short.
    reason: str
    # (unit type, count) as SpawnController counts them: aliases and units in
    # production included. Empty while the plan is inactive.
    counts: tuple[tuple[UnitTypeId, int], ...] = ()


def release_workers(bot, attention: AttentionState, result: EngineResult) -> None:
    """A worker no proposal holds any more goes back to mining."""

    workers = {unit.tag for unit in attention.own_units if unit.is_worker}
    for tag in result.released:
        if tag in workers:
            bot.mediator.assign_role(tag=tag, role=UnitRole.GATHERING)


def execute(
    bot,
    plan: EconomyPlan,
    *,
    energy_reserve: float = 0.0,
    busy: frozenset[int] = frozenset(),
) -> SpawnMode:
    """`energy_reserve` is what each Orbital keeps; `busy` Orbitals already
    used their energy this frame."""

    if plan.interrupt_opening:
        runner = getattr(bot, "build_order_runner", None)
        if runner is not None and not runner.build_completed:
            runner.set_build_completed()
    bot.register_behavior(Mining())
    if not plan.active:
        return SpawnMode(freeflow=False, reason="plan_inactive")
    spawn = spawn_mode(bot, plan)
    composition = {
        unit_type: {"proportion": proportion, "priority": priority}
        for unit_type, proportion, priority in plan.composition
    }
    add_on = add_add_on(bot, plan.addons_on, plan.reactor_share) if plan.addons else None
    # Ares' MacroPlan stops at the first behavior that acts, and the
    # SpawnController acts whenever production is idle: whatever should not
    # wait for the army to stop growing goes before it.
    macro = MacroPlan()
    macro.add(AutoSupply(base_location=bot.start_location))
    if plan.orbitals:
        # Before BuildWorkers, which keeps the Command Centers busy.
        macro.add(UpgradeCCs(to=UnitTypeId.ORBITALCOMMAND))
    macro.add(BuildWorkers(to_count=plan.workers))
    macro.add(GasBuildingController(to_count=plan.gas))
    if plan.expand:
        macro.add(ExpansionController(to_count=plan.bases))
    if plan.upgrades:
        macro.add(ExactResearch(plan.upgrades))
        macro.add(UpgradeController(list(plan.upgrades), base_location=bot.start_location))
    macro.add(
        SpawnController(
            composition,
            freeflow_mode=spawn.freeflow,
            ignored_build_from_tags=set() if add_on is None else {add_on},
        )
    )
    # Only in a frame the SpawnController did not act: on its own it would add
    # a Tech Lab to a Barracks the SpawnController just ordered to train, and
    # the last order wins (`bench/7/002`).
    macro.add(
        ProductionController(
            composition,
            base_location=bot.start_location,
            max_production_structures=plan.max_production,
        )
    )
    bot.register_behavior(macro)
    if plan.mules:
        call_mules(bot, reserve=energy_reserve, busy=busy)
    return spawn


def call_mules(bot, *, reserve: float = 0.0, busy: frozenset[int] = frozenset()) -> None:
    """Every ready Orbital with a MULE's energy beyond `reserve`, and not
    `busy`, drops one on the fullest mineral field of a ready townhall; ties go
    to the lowest tag."""

    townhalls = [townhall for townhall in bot.townhalls if townhall.is_ready]
    fields = [
        field
        for field in bot.mineral_field
        if any(field.distance_to(townhall) <= MINING_DISTANCE for townhall in townhalls)
    ]
    if not fields:
        return
    target = max(fields, key=lambda field: (field.mineral_contents, -field.tag))
    for orbital in bot.structures:
        if (
            orbital.type_id is UnitTypeId.ORBITALCOMMAND
            and orbital.is_ready
            and orbital.energy >= MULE_ENERGY + reserve
            and orbital.tag not in busy
        ):
            orbital(AbilityId.CALLDOWNMULE_CALLDOWNMULE, target)


def spawn_mode(bot, plan: EconomyPlan) -> SpawnMode:
    counts = tuple(
        (unit_type, int(bot.mediator.get_own_unit_count(unit_type_id=unit_type)))
        for unit_type, _, _ in plan.composition
    )
    if plan.freeflow:
        return SpawnMode(freeflow=True, reason="plan_freeflow", counts=counts)
    total = sum(count for _, count in counts)
    # SpawnController's own test, type by type: a type whose share is met is skipped.
    met = bool(counts) and all(
        count / (total + _EMPTY_ARMY) >= proportion
        for (_, count), (_, proportion, _) in zip(counts, plan.composition, strict=True)
    )
    if met:
        return SpawnMode(freeflow=True, reason="composition_met", counts=counts)
    return SpawnMode(freeflow=False, reason="composition_short", counts=counts)
