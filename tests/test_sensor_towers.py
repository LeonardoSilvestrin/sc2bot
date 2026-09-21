"""Coverage plans must be built at the same coordinates they were scored at."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from ares.consts import BuildingSize
from ares.managers.utils.placement_strategy import PlacementRequest, UnpoweredPlacementStrategy
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import observe
from bot.body.behaviors.sensor_towers import BuildSensorTower
from bot.ego.planners.intel.policies.sensor_towers import sensor_tower_sites

from .fakes import FakeBot
from .test_intel import SENSOR_MAP, open_bases, sensor_state, tower

BASE = Point2((64.5, 70.5))
TARGET = Point2((66.0, 62.0))
PRESET = Point2((75.0, 78.0))


class PlacementMediator:
    """Use Ares' real selection logic, with only its placement inventory faked."""

    def __init__(self, *, occupied=False):
        self.sites = {
            TARGET: {"available": not occupied},
            PRESET: {"available": True, "sensor_tower": True},
        }
        self.get_placements_dict = {BASE: {BuildingSize.TWO_BY_TWO: self.sites}}
        self.get_ground_grid = None
        self.reserved = []
        self.built = []

    def is_position_safe(self, **kwargs):
        return True

    def request_building_placement(self, base_location, structure_type, **kwargs):
        request = PlacementRequest(**kwargs)
        manager = SimpleNamespace(
            placements_dict=self.get_placements_dict,
            manager_mediator=self,
        )
        available = [point for point, info in self.sites.items() if info["available"]]
        if not available:
            return None
        selected = UnpoweredPlacementStrategy(
            manager, request, structure_type, BuildingSize.TWO_BY_TWO
        ).select(available, base_location)
        if request.reserve_placement:
            self.reserved.append(selected)
            self.sites[selected]["available"] = False
        return selected

    def select_worker(self, **kwargs):
        return SimpleNamespace(tag=1)

    def build_with_specific_worker(self, worker, structure_type, pos):
        self.built.append(pos)
        return True


def behavior():
    return BuildSensorTower(
        BASE, UnitTypeId.SENSORTOWER, closest_to=TARGET,
        production=False, find_alternative=False,
    )


def builder(*, pending=0, tech=1.0):
    from sc2.data import Race

    return SimpleNamespace(
        race=Race.Terran,
        not_started_but_in_building_tracker=lambda _: pending,
        tech_requirement_progress=lambda _: tech,
    )


def test_sensor_tower_uses_planned_coordinate_despite_an_ares_preset():
    mediator = PlacementMediator()
    # The old request ignores TARGET in favor of this flagged site.
    assert mediator.request_building_placement(
        BASE, UnitTypeId.SENSORTOWER, closest_to=TARGET,
        sensor_tower=True, production=False, reserve_placement=False,
    ) == PRESET

    assert behavior().execute(builder(), {}, mediator)
    assert mediator.built == [TARGET]
    assert mediator.reserved == [TARGET]


def test_occupied_target_never_builds_a_series_of_fallback_towers():
    mediator = PlacementMediator(occupied=True)
    for _ in range(20):
        assert not behavior().execute(builder(), {}, mediator)
    assert mediator.built == mediator.reserved == []
    assert mediator.sites[PRESET]["available"]


@pytest.mark.parametrize("ai", [builder(pending=1), builder(tech=0.0)])
def test_pending_builder_or_missing_tech_does_not_reserve_another_tower(ai):
    mediator = PlacementMediator()
    assert not behavior().execute(ai, {}, mediator)
    assert mediator.built == mediator.reserved == []


def test_attention_filters_occupied_reserved_and_custom_sites_without_changing_map():
    bot = FakeBot()
    points = tuple(Point2((x, 10)) for x in (10, 14, 18, 22))
    view = replace(SENSOR_MAP, tower_sites=((BASE, points),))
    bot.mediator.get_placements_dict = {
        BASE: {BuildingSize.TWO_BY_TWO: dict(zip(points, (
            {"available": True},
            {"available": False},
            {"available": True, "worker_on_route": True},
            {"available": True, "custom": True},
        ), strict=True))}
    }
    state = observe(bot, 0, view)
    assert state.available_tower_sites == ((BASE, (points[0],)),)
    assert state.map is view and view.tower_sites == ((BASE, points),)
    bot.mediator.get_placements_dict[BASE][BuildingSize.TWO_BY_TWO][points[1]]["available"] = True
    assert observe(bot, 1, view).available_tower_sites == ((BASE, points[:2]),)


def test_planner_replaces_an_occupied_target_and_finishes_after_actual_construction():
    state = sensor_state(time=300.0)
    first = sensor_tower_sites(state)[0]
    free = tuple(
        (base, tuple(point for point in points if point != first.target))
        for base, points in state.map.tower_sites
    )
    state = replace(state, available_tower_sites=free)
    built = []
    for _ in range(10):
        plan = sensor_tower_sites(state)
        if not plan:
            break
        target = plan[0].target
        assert target != first.target and target not in built
        built.append(target)
        free = tuple(
            (base, tuple(point for point in points if point != target))
            for base, points in free
        )
        state = replace(
            state, available_tower_sites=free,
            own_structures=tuple(tower(i, point, ready=False) for i, point in enumerate(built)),
        )
    assert not sensor_tower_sites(state)
    assert len(built) <= len(state.bases)
    assert open_bases(state.bases, built) == []


def test_empty_live_placement_inventory_does_not_fall_back_to_static_sites():
    state = replace(sensor_state(time=300.0), available_tower_sites=())
    assert sensor_tower_sites(state) == ()
