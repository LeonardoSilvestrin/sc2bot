from __future__ import annotations

from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.engine.economy.models import EconomicActionKind, ResourceCost
from bot.macro import (
    MacroPlanner,
    MacroPlannerConfig,
    ProductionGoal,
    bio_three_one_one,
    macro_config_for_opening,
)
from bot.macro.production.army_demand import army_demand
from bot.world.attention import (
    AttentionSnapshot,
    CountFacts,
    EconomyFacts,
    MapFacts,
    ProducerFacts,
    UnitTypeCount,
    WorldFacts,
)
from bot.world.awareness import AwarenessService, MacroPosture

MAP = MapFacts(
    center=Point2((50, 50)),
    own_start=Point2((10, 10)),
    enemy_starts=(Point2((90, 90)),),
)

CONVERGED_UNITS = {
    UnitTypeId.MARINE: (70, 0),
    UnitTypeId.MARAUDER: (15, 0),
    UnitTypeId.MEDIVAC: (4, 0),
    UnitTypeId.SIEGETANK: (3, 0),
}
CONVERGED_STRUCTURES = {
    UnitTypeId.REFINERY: (8, 0),
    UnitTypeId.BARRACKS: (3, 0),
    UnitTypeId.FACTORY: (1, 0),
    UnitTypeId.STARPORT: (1, 0),
    UnitTypeId.BARRACKSTECHLAB: (2, 0),
    UnitTypeId.FACTORYTECHLAB: (1, 0),
    UnitTypeId.STARPORTREACTOR: (1, 0),
}


def typed_counts(
    values: dict[UnitTypeId, tuple[int, int]],
) -> tuple[UnitTypeCount, ...]:
    return tuple(
        UnitTypeCount(
            unit_type=unit_type,
            existing=ready + pending,
            ready=ready,
            pending=pending,
        )
        for unit_type, (ready, pending) in values.items()
    )


def economy_attention(
    *,
    time: float = 100.0,
    workers: tuple[int, int] = (70, 0),
    townhalls: tuple[int, int] = (4, 0),
    ideal_harvesters: int = 88,
    units: dict[UnitTypeId, tuple[int, int]] | None = None,
    structures: dict[UnitTypeId, tuple[int, int]] | None = None,
    producers: tuple[ProducerFacts, ...] = (),
    mineral_rate: float = 0.0,
    vespene_rate: float = 0.0,
    supply_used: float = 150.0,
    supply_cap: float = 200.0,
    supply_pending: int = 0,
    opening_completed: bool = True,
    minerals: int = 0,
    vespene: int = 0,
    tech_ready: frozenset[UnitTypeId] | None = None,
) -> AttentionSnapshot:
    ready_workers, pending_workers = workers
    ready_townhalls, pending_townhalls = townhalls
    economy = EconomyFacts(
        opening_name="BioThreeOneOne",
        opening_completed=opening_completed,
        mineral_collection_rate=mineral_rate,
        vespene_collection_rate=vespene_rate,
        workers=CountFacts(
            existing=ready_workers + pending_workers,
            ready=ready_workers,
            pending=pending_workers,
        ),
        ideal_harvesters=ideal_harvesters,
        assigned_harvesters=ready_workers,
        townhalls=CountFacts(
            existing=ready_townhalls + pending_townhalls,
            ready=ready_townhalls,
            pending=pending_townhalls,
        ),
        supply_pending=supply_pending,
        unit_counts=typed_counts(
            units if units is not None else CONVERGED_UNITS
        ),
        structure_counts=typed_counts(
            structures if structures is not None else CONVERGED_STRUCTURES
        ),
        producers=producers,
        tech_ready=tech_ready,
    )
    return AttentionSnapshot(
        WorldFacts(
            iteration=int(time),
            time=time,
            minerals=minerals,
            vespene=vespene,
            supply_used=supply_used,
            supply_cap=supply_cap,
            own_units=(),
            enemy_units=(),
            map=MAP,
            economy=economy,
        )
    )


def proposals_for(
    attention: AttentionSnapshot,
    *,
    posture: MacroPosture = MacroPosture.BALANCED,
):
    awareness = replace(
        AwarenessService().update(attention),
        macro_posture=posture,
    )
    return MacroPlanner().propose(attention, awareness)


def proposal_of_kind(proposals, kind: EconomicActionKind):
    return next((proposal for proposal in proposals if proposal.kind is kind), None)


def proposal_for(proposals, kind: EconomicActionKind, target: UnitTypeId):
    return next(
        (
            proposal
            for proposal in proposals
            if proposal.kind is kind and proposal.target == target.name
        ),
        None,
    )


def units_short_of_marines() -> dict[UnitTypeId, tuple[int, int]]:
    """A converged army except for Marines, which need no Tech Lab.

    Marines are what makes another *bare* Barracks useful; a Marauder deficit
    would be a reason to build a Tech Lab instead.
    """

    return {**CONVERGED_UNITS, UnitTypeId.MARINE: (30, 0)}


def saturated(unit_type: UnitTypeId, ready: int = 3) -> ProducerFacts:
    """Producers that have been continuously busy, not just busy this frame."""

    return ProducerFacts(
        unit_type, ready=ready, busy=ready, idle=0, utilization_20s=1.0
    )


MECH_OPENING_STRUCTURES = {
    UnitTypeId.REFINERY: (4, 0),
    UnitTypeId.BARRACKS: (1, 0),
    UnitTypeId.FACTORY: (1, 0),
    UnitTypeId.FACTORYREACTOR: (1, 0),
    UnitTypeId.STARPORT: (1, 0),
    UnitTypeId.STARPORTTECHLAB: (1, 0),
}


def mech_proposals(attention: AttentionSnapshot):
    planner = MacroPlanner(config=macro_config_for_opening("BattleMech"))
    return planner.propose(attention, AwarenessService().update(attention))


class TestBattleMechMacro:
    def test_the_third_base_brings_two_factories_and_a_second_starport(self):
        on_two = mech_proposals(
            economy_attention(townhalls=(2, 0), structures=MECH_OPENING_STRUCTURES)
        )
        assert proposal_for(
            on_two, EconomicActionKind.BUILD_PRODUCTION, UnitTypeId.FACTORY
        ) is None
        assert proposal_for(
            on_two, EconomicActionKind.BUILD_PRODUCTION, UnitTypeId.STARPORT
        ) is None

        # The Command Center only has to be started.
        third_started = mech_proposals(
            economy_attention(townhalls=(2, 1), structures=MECH_OPENING_STRUCTURES)
        )
        for structure_type in (UnitTypeId.FACTORY, UnitTypeId.STARPORT):
            proposal = proposal_for(
                third_started, EconomicActionKind.BUILD_PRODUCTION, structure_type
            )
            assert proposal is not None
            assert proposal.reason == "production_below_townhall_floor"

    def test_overflow_cannot_buy_production_before_the_third(self):
        """The expansion's bank is not permission to improvise a 2-base flood."""

        attention = economy_attention(
            townhalls=(2, 0),
            units={},
            structures=MECH_OPENING_STRUCTURES,
            producers=(
                saturated(UnitTypeId.FACTORY, ready=1),
                saturated(UnitTypeId.STARPORT, ready=1),
            ),
            minerals=1_700,
            vespene=1_200,
        )
        planner = MacroPlanner(config=macro_config_for_opening("BattleMech"))

        proposals = planner.propose(attention, AwarenessService().update(attention))

        for structure_type in (UnitTypeId.FACTORY, UnitTypeId.STARPORT):
            assert proposal_for(
                proposals, EconomicActionKind.BUILD_PRODUCTION, structure_type
            ) is None
            assessment = next(
                item
                for item in planner.last_status.capacity
                if item.structure_type is structure_type
            )
            assert assessment.desired == 1
            assert assessment.reason == "dynamic_growth_waits_for_ready_townhall"

    def test_factory_flood_unlocks_only_after_the_third_is_ready(self):
        structures = {
            **MECH_OPENING_STRUCTURES,
            UnitTypeId.FACTORY: (3, 0),
            UnitTypeId.FACTORYTECHLAB: (2, 0),
            UnitTypeId.STARPORT: (2, 0),
            UnitTypeId.STARPORTTECHLAB: (2, 0),
        }
        attention = economy_attention(
            townhalls=(3, 0),
            units={},
            structures=structures,
            producers=(saturated(UnitTypeId.FACTORY, ready=3),),
            vespene=1_200,
        )
        planner = MacroPlanner(config=macro_config_for_opening("BattleMech"))

        proposals = planner.propose(attention, AwarenessService().update(attention))
        factory = proposal_for(
            proposals, EconomicActionKind.BUILD_PRODUCTION, UnitTypeId.FACTORY
        )

        assert factory is not None
        assert factory.target_count == 4
        assert factory.reason == "saturated_capacity_and_bank_overflowing"
        assessment = next(
            item
            for item in planner.last_status.capacity
            if item.structure_type is UnitTypeId.FACTORY
        )
        assert assessment.desired == 5

    def test_an_add_on_waits_for_a_structure_that_can_hold_it(self):
        # The only Factory holds the Reactor it took from the Barracks, so a
        # Tech Lab has nowhere to go until the third base adds another.
        assert proposal_for(
            mech_proposals(economy_attention(structures=MECH_OPENING_STRUCTURES)),
            EconomicActionKind.BUILD_ADDON,
            UnitTypeId.FACTORYTECHLAB,
        ) is None

        with_new_factory = {**MECH_OPENING_STRUCTURES, UnitTypeId.FACTORY: (2, 0)}
        assert proposal_for(
            mech_proposals(economy_attention(structures=with_new_factory)),
            EconomicActionKind.BUILD_ADDON,
            UnitTypeId.FACTORYTECHLAB,
        ) is not None


class TestArmyDemand:
    def test_debt_is_the_gap_to_the_supply_target(self):
        goals = replace(bio_three_one_one(), army_supply_target=55.0)
        economy = EconomyFacts(
            unit_counts=typed_counts(
                {
                    UnitTypeId.MARINE: (14, 2),
                    UnitTypeId.MARAUDER: (5, 0),
                    UnitTypeId.SIEGETANK: (2, 0),
                }
            )
        )

        demand = army_demand(goals, economy)

        # 14 Marines + 5 Marauders + 2 Tanks ready is 30 supply, plus 2
        # Marines in production; 55 wanted leaves 23 owed.
        assert demand.ready_supply == 30.0
        assert demand.pending_supply == 2.0
        assert demand.supply_debt == 23.0

    def test_the_composition_scales_to_the_target_rather_than_to_itself(self):
        goals = replace(bio_three_one_one(), army_supply_target=55.0)

        demand = army_demand(goals, EconomyFacts())

        # One full cycle of the 8/3/2/2 weights is 24 supply, so reaching 55
        # takes a bit over two of them -- every member is wanted well above
        # its minimum.
        desired = {unit.unit_type: unit.desired for unit in demand.units}
        assert desired[UnitTypeId.MARINE] == 19
        assert desired[UnitTypeId.MARAUDER] == 7
        assert sum(
            unit.desired * unit.cost.supply for unit in demand.units
        ) >= 55.0


class TestMacroPlanner:
    def test_macro_still_plans_while_the_opening_is_running(self):
        # An unfinished opening is a set of protected commitments, not a
        # freeze: the economy controller withholds what the build runner's
        # next steps cost (see `EconomyController.tick(protected=...)`), and
        # macro argues for what the surplus should buy.
        attention = economy_attention(
            opening_completed=False, workers=(10, 0), ideal_harvesters=22
        )

        assert proposal_of_kind(
            proposals_for(attention), EconomicActionKind.PRODUCE_WORKER
        ) is not None

    def test_an_opening_does_not_stop_macro_from_using_a_surplus(self):
        # A long opening used to mean a bank piling up behind one Barracks.
        # Money is shared safely -- the controller withholds the opening's
        # next steps -- so everything paid for in minerals stays available.
        attention = economy_attention(
            opening_completed=False,
            workers=(20, 0),
            townhalls=(1, 0),
            ideal_harvesters=22,
            units={},
            structures={},
            minerals=1500,
        )

        kinds = {item.kind for item in proposals_for(attention)}

        assert EconomicActionKind.PRODUCE_UNIT in kinds
        assert EconomicActionKind.PRODUCE_WORKER in kinds
        assert EconomicActionKind.BUILD_PRODUCTION in kinds

    def test_add_ons_wait_for_the_opening_to_finish(self):
        # A Starport holds one add-on. Putting our Reactor on the only one
        # would leave the opening's own Tech Lab step with nowhere to build,
        # and the build order would never complete -- a slot cannot be shared
        # the way a mineral surplus can.
        structures = dict(CONVERGED_STRUCTURES)
        del structures[UnitTypeId.STARPORTREACTOR]
        attention = economy_attention(
            opening_completed=False, structures=structures, minerals=1500
        )

        assert not any(
            item.kind is EconomicActionKind.BUILD_ADDON
            for item in proposals_for(attention)
        )
        assert any(
            item.kind is EconomicActionKind.BUILD_ADDON
            for item in proposals_for(
                economy_attention(
                    opening_completed=True, structures=structures, minerals=1500
                )
            )
        )

    def test_converged_profile_has_no_proposals(self):
        attention = economy_attention()

        assert proposals_for(attention) == ()

    def test_worker_goal_is_emitted_without_waiting_for_affordability(self):
        attention = economy_attention(
            workers=(10, 0),
            townhalls=(1, 0),
            ideal_harvesters=22,
            minerals=0,
        )

        proposal = proposal_of_kind(
            proposals_for(attention),
            EconomicActionKind.PRODUCE_WORKER,
        )

        assert proposal is not None
        assert proposal.target == UnitTypeId.SCV.name
        # The goal is 22 workers; this action buys one of them, and costs one.
        assert proposal.target_count == 11
        assert proposal.cost.minerals == 50

    def test_pending_worker_is_part_of_the_saturation_count(self):
        attention = economy_attention(
            workers=(21, 1),
            townhalls=(1, 0),
            ideal_harvesters=22,
        )

        assert proposal_of_kind(
            proposals_for(attention),
            EconomicActionKind.PRODUCE_WORKER,
        ) is None

    def test_pending_supply_prevents_redundant_depot(self):
        attention = economy_attention(
            supply_used=196.0,
            supply_cap=200.0,
            supply_pending=8,
        )

        assert proposal_of_kind(
            proposals_for(attention),
            EconomicActionKind.PRODUCE_SUPPLY,
        ) is None

    def test_opening_owns_supply_depots(self):
        # The build order places its own depots (`supply @ ramp` closes the
        # wall); a macro depot would go down off the wall and take its turn.
        near_limit = dict(supply_used=17.0, supply_cap=23.0, minerals=150)

        assert proposal_of_kind(
            proposals_for(economy_attention(opening_completed=False, **near_limit)),
            EconomicActionKind.PRODUCE_SUPPLY,
        ) is None
        assert proposal_of_kind(
            proposals_for(economy_attention(opening_completed=True, **near_limit)),
            EconomicActionKind.PRODUCE_SUPPLY,
        ) is not None

    def test_supply_goal_does_not_require_100_minerals_in_bank(self):
        attention = economy_attention(
            supply_used=194.0,
            supply_cap=199.0,
            minerals=0,
        )

        proposal = proposal_of_kind(
            proposals_for(attention),
            EconomicActionKind.PRODUCE_SUPPLY,
        )

        assert proposal is not None
        assert proposal.reason == "effective_supply_capacity_near_limit"

    def test_expansion_is_bounded_and_pending_aware(self):
        saturated = economy_attention(
            workers=(40, 0),
            townhalls=(2, 0),
            ideal_harvesters=44,
            minerals=0,
        )
        pending = economy_attention(
            workers=(40, 0),
            townhalls=(2, 1),
            ideal_harvesters=44,
        )
        at_limit = economy_attention(
            workers=(70, 0),
            townhalls=(4, 0),
            ideal_harvesters=88,
        )

        proposal = proposal_of_kind(
            proposals_for(saturated),
            EconomicActionKind.EXPAND,
        )
        assert proposal is not None
        assert proposal.target_count == 3
        assert proposal.cost.minerals == 400
        assert proposal_of_kind(
            proposals_for(pending), EconomicActionKind.EXPAND
        ) is None
        assert proposal_of_kind(
            proposals_for(at_limit), EconomicActionKind.EXPAND
        ) is None

    def test_defense_withholds_expansion_but_a_remote_sighting_does_not(self):
        attention = economy_attention(
            workers=(40, 0),
            townhalls=(2, 0),
            ideal_harvesters=44,
        )

        assert proposal_of_kind(
            proposals_for(attention, posture=MacroPosture.BALANCED),
            EconomicActionKind.EXPAND,
        ) is not None
        assert proposal_of_kind(
            proposals_for(attention, posture=MacroPosture.DEFENSE),
            EconomicActionKind.EXPAND,
        ) is None

    def test_gas_target_uses_current_and_pending_refineries(self):
        structures = dict(CONVERGED_STRUCTURES)
        structures[UnitTypeId.REFINERY] = (3, 1)
        attention = economy_attention(
            townhalls=(2, 0),
            ideal_harvesters=44,
            workers=(30, 0),
            structures=structures,
        )

        assert proposal_of_kind(
            proposals_for(attention), EconomicActionKind.BUILD_GAS
        ) is None

    def test_high_income_adds_only_sustainedly_busy_production_capacity(self):
        units = units_short_of_marines()
        busy = economy_attention(
            units=units,
            mineral_rate=1_200.0,
            producers=(saturated(UnitTypeId.BARRACKS),),
        )
        idle = economy_attention(
            units=units,
            mineral_rate=1_200.0,
            producers=(
                ProducerFacts(
                    UnitTypeId.BARRACKS,
                    ready=3,
                    busy=1,
                    idle=2,
                    utilization_20s=0.4,
                ),
            ),
        )

        proposal = proposal_for(
            proposals_for(busy),
            EconomicActionKind.BUILD_PRODUCTION,
            UnitTypeId.BARRACKS,
        )
        assert proposal is not None
        assert proposal.target_count == 4
        assert (
            proposal_for(
                proposals_for(idle),
                EconomicActionKind.BUILD_PRODUCTION,
                UnitTypeId.BARRACKS,
            )
            is None
        )

    def test_a_recently_idle_producer_does_not_justify_more_capacity(self):
        # Busy in this exact frame, but idle for most of the last twenty
        # seconds: capacity decisions must use the sustained figure, or every
        # gap between two units would read as saturation.
        units = units_short_of_marines()
        attention = economy_attention(
            units=units,
            mineral_rate=1_200.0,
            producers=(
                ProducerFacts(
                    UnitTypeId.BARRACKS,
                    ready=3,
                    busy=3,
                    idle=0,
                    utilization_20s=0.2,
                ),
            ),
        )

        assert (
            proposal_for(
                proposals_for(attention),
                EconomicActionKind.BUILD_PRODUCTION,
                UnitTypeId.BARRACKS,
            )
            is None
        )

    def test_a_unit_needing_a_tech_lab_does_not_justify_a_bare_structure(self):
        # Observed in a real game: Siege Tanks owed, the one Factory with a
        # Tech Lab constantly busy, so a second Factory got built -- and then
        # sat idle forever, because a bare Factory cannot build Tanks either.
        # The bottleneck is the add-on, not the building.
        units = dict(CONVERGED_UNITS)
        units[UnitTypeId.SIEGETANK] = (1, 0)
        attention = economy_attention(
            units=units,
            mineral_rate=1_200.0,
            vespene_rate=900.0,
            producers=(saturated(UnitTypeId.FACTORY, ready=1),),
        )

        assert (
            proposal_for(
                proposals_for(attention),
                EconomicActionKind.BUILD_PRODUCTION,
                UnitTypeId.FACTORY,
            )
            is None
        )

    def test_capacity_is_not_added_for_units_nobody_wants(self):
        # Saturated Barracks and plenty of income, but the army is already at
        # its target: infrastructure exists to serve demand, so there is none.
        attention = economy_attention(
            mineral_rate=1_200.0,
            producers=(saturated(UnitTypeId.BARRACKS),),
        )

        assert not any(
            item.kind is EconomicActionKind.BUILD_PRODUCTION
            for item in proposals_for(attention)
        )

    def test_army_demand_counts_pending_units(self):
        units = dict(CONVERGED_UNITS)
        units[UnitTypeId.MEDIVAC] = (1, 1)
        attention = economy_attention(units=units)

        proposal = proposal_for(
            proposals_for(attention),
            EconomicActionKind.PRODUCE_UNIT,
            UnitTypeId.MEDIVAC,
        )

        # One Medivac flying and one in production count as two, so the next
        # action asks for a third rather than re-ordering the pending one.
        assert proposal is not None
        assert proposal.target_count == 3

    def test_profile_proposes_all_four_composition_members_from_empty_army(self):
        attention = economy_attention(units={})

        targets = {
            item.target
            for item in proposals_for(attention)
            if item.kind is EconomicActionKind.PRODUCE_UNIT
        }

        assert targets == {
            UnitTypeId.MARINE.name,
            UnitTypeId.MARAUDER.name,
            UnitTypeId.MEDIVAC.name,
            UnitTypeId.SIEGETANK.name,
        }

    def test_meeting_every_minimum_does_not_stop_army_production(self):
        # Every composition member is at its configured minimum, which is 30
        # army supply against a 115 target. A member's minimum is a floor for
        # early usefulness, never permission to stop: 85 supply of debt has to
        # keep producing, or the bot banks minerals with an army a third of
        # the size it wants.
        attention = economy_attention(
            units={
                UnitTypeId.MARINE: (12, 0),
                UnitTypeId.MARAUDER: (4, 0),
                UnitTypeId.MEDIVAC: (2, 0),
                UnitTypeId.SIEGETANK: (2, 0),
            }
        )

        targets = {
            item.target
            for item in proposals_for(attention)
            if item.kind is EconomicActionKind.PRODUCE_UNIT
        }

        assert targets == {
            UnitTypeId.MARINE.name,
            UnitTypeId.MARAUDER.name,
            UnitTypeId.MEDIVAC.name,
            UnitTypeId.SIEGETANK.name,
        }

    def test_units_without_tech_are_owed_but_not_argued_for(self):
        # Reserving minerals for a Siege Tank with no Tech Lab would hold the
        # bank against a purchase the game refuses, and (being the most
        # expensive thing owed) starve the Marines we can actually build.
        attention = economy_attention(
            units={},
            tech_ready=frozenset(
                {UnitTypeId.MARINE, UnitTypeId.SCV, UnitTypeId.SUPPLYDEPOT}
            ),
        )

        targets = {
            item.target
            for item in proposals_for(attention)
            if item.kind is EconomicActionKind.PRODUCE_UNIT
        }

        assert targets == {UnitTypeId.MARINE.name}

    def test_idle_capacity_is_used_before_more_is_built(self):
        # The situation this refactor exists for: a huge bank, an army below
        # target, and production standing around. The answer is to train, not
        # to build a fourth Barracks next to two idle ones.
        attention = economy_attention(
            minerals=1200,
            vespene=400,
            units={UnitTypeId.MARINE: (12, 0)},
            producers=(
                ProducerFacts(
                    UnitTypeId.BARRACKS,
                    ready=3,
                    busy=1,
                    idle=2,
                    utilization_20s=0.35,
                ),
                ProducerFacts(
                    UnitTypeId.FACTORY,
                    ready=1,
                    busy=0,
                    idle=1,
                    utilization_20s=0.1,
                ),
            ),
        )

        proposals = proposals_for(attention)

        assert any(
            item.kind is EconomicActionKind.PRODUCE_UNIT for item in proposals
        )
        assert not any(
            item.kind is EconomicActionKind.BUILD_PRODUCTION for item in proposals
        )

    def test_posture_changes_worker_versus_army_priority(self):
        attention = economy_attention(
            workers=(10, 0),
            townhalls=(1, 0),
            ideal_harvesters=22,
            units={},
        )

        defense = proposals_for(attention, posture=MacroPosture.DEFENSE)
        greed = proposals_for(attention, posture=MacroPosture.GREED)
        defense_worker = proposal_of_kind(defense, EconomicActionKind.PRODUCE_WORKER)
        defense_army = proposal_of_kind(defense, EconomicActionKind.PRODUCE_UNIT)
        greed_worker = proposal_of_kind(greed, EconomicActionKind.PRODUCE_WORKER)
        greed_army = proposal_of_kind(greed, EconomicActionKind.PRODUCE_UNIT)

        assert defense_worker.priority < defense_army.priority
        assert greed_worker.priority > greed_army.priority

    def test_bank_overflow_raises_saturated_production_past_the_usual_ceiling(self):
        # minerals=1700 is 3 steps over the default 800/400 overflow config.
        # With the Barracks genuinely saturated the pile justifies more of
        # them -- one at a time, since the action is what gets paid for.
        attention = economy_attention(
            minerals=1700,
            units=units_short_of_marines(),
            producers=(saturated(UnitTypeId.BARRACKS),),
        )

        barracks_proposal = proposal_for(
            proposals_for(attention),
            EconomicActionKind.BUILD_PRODUCTION,
            UnitTypeId.BARRACKS,
        )

        assert barracks_proposal is not None
        assert barracks_proposal.target_count == 4
        assert barracks_proposal.reason == "saturated_capacity_and_bank_overflowing"

    def test_bank_overflow_does_not_add_producers_that_are_already_idle(self):
        # minerals=1700 is 3 steps over threshold, same as
        # test_bank_overflow_raises_saturated_production_past_the_usual_ceiling,
        # but here the existing Barracks are mostly idle: the pile is better
        # spent as more units at those Barracks (see propose_army, which
        # still reacts to this overflow) than as new, equally idle Barracks.
        attention = economy_attention(
            minerals=1700,
            producers=(
                ProducerFacts(
                    UnitTypeId.BARRACKS,
                    ready=3,
                    busy=1,
                    idle=2,
                    utilization_20s=0.3,
                ),
            ),
        )

        assert not any(
            item.kind is EconomicActionKind.BUILD_PRODUCTION
            and item.target == UnitTypeId.BARRACKS.name
            for item in proposals_for(attention)
        )

    def test_a_bank_spike_cannot_commit_to_several_structures_at_once(self):
        # The overflow ceiling may rise by three, but a single tick can only
        # ever argue for one more building per type: the resources reserved
        # have to match what the action really does.
        attention = economy_attention(
            minerals=1700,
            vespene=900,
            producers=(
                saturated(UnitTypeId.BARRACKS),
                saturated(UnitTypeId.STARPORT, ready=1),
            ),
        )

        production = [
            item
            for item in proposals_for(attention)
            if item.kind is EconomicActionKind.BUILD_PRODUCTION
        ]

        assert production
        for proposal in production:
            structures = CONVERGED_STRUCTURES[UnitTypeId[proposal.target]][0]
            assert proposal.target_count == structures + 1

    def test_a_bank_under_the_overflow_threshold_does_not_inflate_targets(self):
        attention = economy_attention(minerals=500)

        assert not any(
            item.kind is EconomicActionKind.BUILD_PRODUCTION
            for item in proposals_for(attention)
        )

    def test_gas_overflow_also_raises_production_targets(self):
        # vespene=500 is 1 step over the default 400/200 vespene overflow
        # config: (500 - 400) // 200 + 1 == 1 extra production structure.
        attention = economy_attention(
            vespene=500,
            units=units_short_of_marines(),
            producers=(saturated(UnitTypeId.BARRACKS),),
        )

        barracks_proposal = proposal_for(
            proposals_for(attention),
            EconomicActionKind.BUILD_PRODUCTION,
            UnitTypeId.BARRACKS,
        )

        assert barracks_proposal is not None
        assert barracks_proposal.target_count == 4

    def test_bank_overflow_raises_the_army_supply_ceiling(self):
        # CONVERGED_UNITS sits at 117 army supply, just above the default
        # 115 target, so nothing is normally proposed (see
        # test_converged_profile_has_no_proposals). An overflowing bank must
        # still push production past that converged composition.
        attention = economy_attention(minerals=1700)

        siegetank_proposal = next(
            (
                item
                for item in proposals_for(attention)
                if item.kind is EconomicActionKind.PRODUCE_UNIT
                and item.target == UnitTypeId.SIEGETANK.name
            ),
            None,
        )

        assert siegetank_proposal is not None

    def test_reference_build_floors_a_production_goal_below_its_own_minimum(self):
        # With the goal's own minimum dropped to zero, the only thing that
        # can still justify a barracks below the standard build's benchmark
        # is the reference build itself (income and overflow are both off).
        goals = replace(
            bio_three_one_one(),
            production=(
                ProductionGoal(
                    UnitTypeId.BARRACKS,
                    minimum=0,
                    maximum=8,
                    cost=ResourceCost(minerals=150),
                ),
            ),
        )
        config = MacroPlannerConfig(goals=goals)
        attention = economy_attention(
            time=100.0, structures={UnitTypeId.BARRACKS: (0, 0)}
        )
        awareness = replace(
            AwarenessService().update(attention), macro_posture=MacroPosture.BALANCED
        )

        proposals = MacroPlanner(config=config).propose(attention, awareness)
        barracks_proposal = next(
            (
                item
                for item in proposals
                if item.kind is EconomicActionKind.BUILD_PRODUCTION
                and item.target == UnitTypeId.BARRACKS.name
            ),
            None,
        )

        assert barracks_proposal is not None
        # The bio_three_one_one reference build reaches 1 barracks at 0:41
        # and 2 at 1:51 -- at t=100 only the first checkpoint applies.
        assert barracks_proposal.target_count == 1
        assert barracks_proposal.reason == "production_below_reference_build_benchmark"

    def test_goal_identity_is_stable_across_frames(self):
        first = proposals_for(
            economy_attention(time=100.0, workers=(10, 0), ideal_harvesters=22)
        )
        second = proposals_for(
            economy_attention(time=101.0, workers=(10, 0), ideal_harvesters=22)
        )

        assert [item.proposal_id for item in first] == [
            item.proposal_id for item in second
        ]
        assert [item.deduplication_key for item in first] == [
            item.deduplication_key for item in second
        ]
