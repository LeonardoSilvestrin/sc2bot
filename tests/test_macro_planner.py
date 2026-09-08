from __future__ import annotations

from dataclasses import replace

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.macro import (
    MacroPlanner,
    MacroPlannerConfig,
    ProductionGoal,
    bio_three_one_one,
)
from bot.behavior.posture import MacroPosture
from bot.engine.economy.models import EconomicActionKind, ResourceCost
from bot.world.attention import (
    AttentionSnapshot,
    CountFacts,
    EconomyFacts,
    MapFacts,
    ProducerFacts,
    UnitTypeCount,
    WorldFacts,
)
from bot.world.awareness import AwarenessService

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


class TestMacroPlanner:
    def test_waits_for_opening_handoff(self):
        attention = economy_attention(opening_completed=False)

        assert proposals_for(attention) == ()

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
        assert proposal.target_count == 22
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

    def test_high_income_adds_only_busy_production_capacity(self):
        busy = economy_attention(
            mineral_rate=1_200.0,
            producers=(
                ProducerFacts(
                    UnitTypeId.BARRACKS,
                    ready=3,
                    busy=3,
                    idle=0,
                ),
            ),
        )
        idle = economy_attention(
            mineral_rate=1_200.0,
            producers=(
                ProducerFacts(
                    UnitTypeId.BARRACKS,
                    ready=3,
                    busy=1,
                    idle=2,
                ),
            ),
        )

        proposal = next(
            (
                item
                for item in proposals_for(busy)
                if item.kind is EconomicActionKind.BUILD_PRODUCTION
                and item.target == UnitTypeId.BARRACKS.name
            ),
            None,
        )
        assert proposal is not None
        assert proposal.target_count == 4
        assert not any(
            item.kind is EconomicActionKind.BUILD_PRODUCTION
            and item.target == UnitTypeId.BARRACKS.name
            for item in proposals_for(idle)
        )

    def test_army_composition_includes_current_and_pending_units(self):
        units = dict(CONVERGED_UNITS)
        units[UnitTypeId.MEDIVAC] = (1, 1)
        attention = economy_attention(units=units)

        assert not any(
            item.kind is EconomicActionKind.PRODUCE_UNIT
            and item.target == UnitTypeId.MEDIVAC.name
            for item in proposals_for(attention)
        )

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

    def test_bank_overflow_raises_production_targets_past_the_usual_ceiling(self):
        # minerals=1700 is 3 steps over the default 800/400 overflow config,
        # which must push the barracks target from its converged minimum (3)
        # to 6, bypassing the usual "producers must be busy" gate entirely.
        attention = economy_attention(minerals=1700)

        barracks_proposal = next(
            (
                item
                for item in proposals_for(attention)
                if item.kind is EconomicActionKind.BUILD_PRODUCTION
                and item.target == UnitTypeId.BARRACKS.name
            ),
            None,
        )

        assert barracks_proposal is not None
        assert barracks_proposal.target_count == 6
        assert barracks_proposal.reason == "resource_bank_overflowing"

    def test_a_bank_under_the_overflow_threshold_does_not_inflate_targets(self):
        attention = economy_attention(minerals=500)

        assert not any(
            item.kind is EconomicActionKind.BUILD_PRODUCTION
            for item in proposals_for(attention)
        )

    def test_gas_overflow_also_raises_production_targets(self):
        # vespene=500 is 1 step over the default 400/200 vespene overflow
        # config: (500 - 400) // 200 + 1 == 1 extra production structure.
        attention = economy_attention(vespene=500)

        barracks_proposal = next(
            (
                item
                for item in proposals_for(attention)
                if item.kind is EconomicActionKind.BUILD_PRODUCTION
                and item.target == UnitTypeId.BARRACKS.name
            ),
            None,
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
