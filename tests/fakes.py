"""Test doubles: layer inputs built directly, plus one fake bot for the frame flow."""

from __future__ import annotations

import json
from collections import defaultdict
from types import SimpleNamespace
from typing import Any

import numpy as np
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, BaseView, MapView, UnitView
from bot.attention.topology import MapPassage, MapRegion, MapTopology
from bot.ego.planners import Command, Proposal

SIZE = 64
EXPANSIONS = (Point2((10.5, 10.5)), Point2((30.5, 12.5)), Point2((53.5, 53.5)))
LATTICE = tuple(
    Point2((x + 0.5, y + 0.5)) for y in range(2, SIZE, 4) for x in range(2, SIZE, 4)
)
TOPOLOGY = MapTopology(
    regions=(
        MapRegion("region:0", Point2((10.5, 10.5)), expansions=(EXPANSIONS[0],)),
        MapRegion("region:1", Point2((30.5, 12.5)), expansions=(EXPANSIONS[1],)),
        MapRegion("region:2", Point2((53.5, 53.5)), expansions=(EXPANSIONS[2],)),
    ),
    passages=(
        MapPassage(
            "choke:0", Point2((20.5, 11.5)), 4.0, ("region:0", "region:1"), "choke"
        ),
        MapPassage(
            "choke:1", Point2((42.5, 32.5)), 6.0, ("region:1", "region:2"), "choke"
        ),
    ),
    adjacency=(
        ("region:0", (("region:1", "choke:0"),)),
        ("region:1", (("region:0", "choke:0"), ("region:2", "choke:1"))),
        ("region:2", (("region:1", "choke:1"),)),
    ),
    expansion_to_region=tuple(
        zip(EXPANSIONS, ("region:0", "region:1", "region:2"), strict=True)
    ),
    own_start_region="region:0",
    enemy_start_region="region:2",
)

MAP = MapView(
    name="TestMap",
    bounds=(0.0, 0.0, float(SIZE), float(SIZE)),
    own_start=Point2((10.5, 10.5)),
    enemy_start=Point2((53.5, 53.5)),
    main_ramp=Point2((18.0, 18.0)),
    expansions=EXPANSIONS,
    lattice=LATTICE,
    lattice_spacing=4.0,
    topology=TOPOLOGY,
)
MAIN = BaseView(base_id="base:10:10", position=Point2((10.5, 10.5)), is_main=True)
NATURAL = BaseView(base_id="base:30:12", position=Point2((30.5, 12.5)), is_main=False)


def unit(
    tag: int,
    type_id: UnitTypeId = UnitTypeId.MARINE,
    x: float = 10.0,
    y: float = 10.0,
    *,
    power: float = 1.0,
    supply: float = 1.0,
    flying: bool = False,
    attack_air: bool = True,
    worker: bool = False,
    structure: bool = False,
    ready: bool = True,
    role: str | None = None,
    energy: float = 0.0,
    hidden: bool = False,
) -> UnitView:
    return UnitView(
        tag=tag,
        type_id=type_id,
        position=Point2((float(x), float(y))),
        health=1.0,
        power=power,
        supply=supply,
        is_flying=flying,
        can_attack_ground=power > 0.0,
        can_attack_air=attack_air and power > 0.0,
        is_worker=worker,
        is_structure=structure,
        is_ready=ready,
        role=role,
        energy=energy,
        is_cloaked=hidden,
        is_hidden=hidden,
    )


def attention(
    *,
    time: float = 0.0,
    iteration: int = 0,
    own_units=(),
    own_structures=(),
    enemy_units=(),
    enemy_structures=(),
    bases=(MAIN,),
    dead_tags=(),
    visibility: np.ndarray | None = None,
    workers: int = 12,
    opening_done: bool = True,
    map_view: MapView = MAP,
) -> AttentionState:
    def by_tag(items) -> tuple:
        return tuple(sorted(items, key=lambda item: item.tag))

    return AttentionState(
        iteration=iteration,
        time=float(time),
        minerals=50,
        vespene=0,
        supply_used=20.0,
        supply_cap=31.0,
        workers=workers,
        opening="Test",
        opening_done=opening_done,
        own_units=by_tag(own_units),
        own_structures=by_tag(own_structures),
        enemy_units=by_tag(enemy_units),
        enemy_structures=by_tag(enemy_structures),
        bases=tuple(bases),
        dead_tags=frozenset(dead_tags),
        map=map_view,
        visibility=visibility,
    )


PROPOSAL_TARGET = Point2((30.0, 30.0))


def proposal(
    proposal_id: str,
    priority: float,
    *,
    owner: str | None = None,
    count=None,
    unit_types=None,
    command=Command.ATTACK,
    target=PROPOSAL_TARGET,
) -> Proposal:
    return Proposal(
        proposal_id=proposal_id,
        owner=owner or proposal_id.split(":")[0],
        priority=priority,
        command=command,
        target=target,
        reason="test",
        count=count,
        unit_types=unit_types,
    )


def seen_everywhere() -> np.ndarray:
    return np.full((SIZE, SIZE), 2, dtype=np.uint8)


class FakeLogger:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.iteration: int | None = None
        self.closed = False

    def begin_frame(self, iteration: int) -> None:
        self.iteration = iteration

    def end_frame(self) -> None:
        self.iteration = None

    def event(self, name, *, component, game_time, data=None) -> None:
        # Every event a test produces must already be strict JSON.
        json.dumps({"data": data or {}, "game_time": game_time}, allow_nan=False)
        self.events.append(
            {
                "name": name,
                "component": component,
                "game_time": game_time,
                "iteration": self.iteration,
                "data": data or {},
            }
        )

    def named(self, name: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["name"] == name]

    def close(self) -> None:
        self.closed = True


class FakeUnit:
    """The python-sc2 `Unit` surface Attention and the behaviors read."""

    def __init__(
        self,
        tag: int,
        type_id: UnitTypeId,
        x: float,
        y: float,
        *,
        dps: float = 10.0,
        hit_points: float = 45.0,
        flying: bool = False,
        structure: bool = False,
        visible: bool = True,
        ready: bool = True,
        energy: float = 0.0,
        minerals: int = 0,
        abilities=(),
        buffs=(),
        health: float | None = None,
        cloaked: bool = False,
        burrowed: bool = False,
        revealed: bool = False,
        memory: bool = False,
    ) -> None:
        # An older frame's object: Ares lists the enemies it remembers out of
        # sight among the enemy units, as the snapshot it took.
        self.is_memory = memory
        # Cloak, burrow and detection as python-sc2 reports them.
        self.is_cloaked = cloaked
        self.is_burrowed = burrowed
        self.is_revealed = revealed
        # What the unit can use now, and the buffs it carries.
        self.abilities = set(abilities)
        self.buffs = set(buffs)
        self.is_ready = ready
        self.energy = energy
        self.mineral_contents = minerals
        # Abilities this unit was ordered to use, in order.
        self.commands: list = []
        self.tag = tag
        self.type_id = type_id
        self.position = Point2((float(x), float(y)))
        self.health = hit_points if health is None else health
        self.health_max = hit_points
        self.shield = 0.0
        self.shield_max = 0.0
        self.ground_dps = dps
        self.air_dps = 0.0 if structure else dps
        self.is_flying = flying
        self.can_attack_ground = dps > 0.0
        self.can_attack_air = dps > 0.0 and not structure
        self.is_structure = structure
        self.is_visible = visible

    @property
    def health_percentage(self) -> float:
        return self.health / self.health_max if self.health_max else 0.0

    def has_buff(self, buff) -> bool:
        return buff in self.buffs

    def distance_to(self, other) -> float:
        return self.position.distance_to(getattr(other, "position", other))

    def __call__(self, ability, target=None) -> None:
        self.commands.append(ability if target is None else (ability, target))


class FakeMediator:
    """The Ares mediator surface Attention and the behaviors use."""

    def __init__(self) -> None:
        self.get_ground_grid = np.ones((SIZE, SIZE))
        self.get_air_grid = np.ones((SIZE, SIZE))
        self.get_unit_role_dict: dict[str, set[int]] = {}
        self.removed_from_minerals: list[int] = []
        # Own structures by type, the way Ares' macro behaviors read them.
        self.get_own_structures_dict: dict[UnitTypeId, list] = defaultdict(list)
        # What Ares counts of each own unit type, aliases and production included.
        self.own_unit_counts: dict[UnitTypeId, int] = {}

    def get_own_unit_count(self, *, unit_type_id: UnitTypeId) -> int:
        return self.own_unit_counts.get(unit_type_id, 0)

    def assign_role(self, *, tag: int, role, remove_from_squad: bool = True) -> None:
        for tags in self.get_unit_role_dict.values():
            tags.discard(tag)
        self.get_unit_role_dict.setdefault(role.name, set()).add(tag)

    def remove_worker_from_mineral(self, *, worker_tag: int) -> None:
        self.removed_from_minerals.append(worker_tag)

    def role_of(self, tag: int) -> str | None:
        return next(
            (role for role, tags in self.get_unit_role_dict.items() if tag in tags), None
        )


class FakeDebugClient:
    def __init__(self) -> None:
        self.spheres: list[tuple] = []
        self.world_text: list[tuple] = []
        self.screen_text: list[tuple] = []

    def debug_sphere_out(self, *args) -> None:
        self.spheres.append(args)

    def debug_text_world(self, *args) -> None:
        self.world_text.append(args)

    def debug_text_screen(self, *args) -> None:
        self.screen_text.append(args)


# (minerals, vespene) of what a test asks the fake bot to afford.
_COST = {
    UnitTypeId.BARRACKSREACTOR: (50, 50),
    UnitTypeId.BARRACKS: (150, 0),
    UnitTypeId.MARINE: (50, 0),
}

_SUPPLY = {
    UnitTypeId.SCV: 1.0,
    UnitTypeId.MARINE: 1.0,
    UnitTypeId.MARAUDER: 2.0,
    UnitTypeId.SIEGETANK: 3.0,
    UnitTypeId.ZERGLING: 0.5,
    UnitTypeId.MUTALISK: 2.0,
}


class FakeBot:
    def __init__(self) -> None:
        self.time = 0.0
        self.minerals = 400
        self.vespene = 100
        self.supply_used = 30.0
        self.supply_cap = 46.0
        self.race = "Race.Terran"
        self.enemy_race = "Race.Zerg"
        self.units: list[FakeUnit] = []
        self.structures: list[FakeUnit] = []
        self.enemy_units: list[FakeUnit] = []
        self.enemy_structures: list[FakeUnit] = []
        self.townhalls: list[FakeUnit] = []
        self.mineral_field: list[FakeUnit] = []
        self.state = SimpleNamespace(
            dead_units=set(),
            visibility=SimpleNamespace(
                data_numpy=np.zeros((SIZE, SIZE), dtype=np.uint8)
            ),
        )
        self.build_order_runner = SimpleNamespace(
            chosen_opening="BioThreeOneOne", build_completed=True
        )
        self.mediator = FakeMediator()
        self.start_location = MAP.own_start
        self.enemy_start_locations = [MAP.enemy_start]
        self.main_base_ramp = SimpleNamespace(top_center=MAP.main_ramp)
        self.expansion_locations_list = list(MAP.expansions)
        pathing = np.zeros((SIZE, SIZE), dtype=np.uint8)
        pathing[4:60, 4:60] = 1
        self.game_info = SimpleNamespace(
            map_name="FakeMap",
            playable_area=SimpleNamespace(x=2, y=2, width=60, height=60),
            pathing_grid=SimpleNamespace(data_numpy=pathing),
        )
        self.client = FakeDebugClient()
        self.registered: list[Any] = []
        # SCVs inside a gas building: the game counts them, `units` does not list them.
        self.workers_in_gas = 0

    @property
    def unit_tag_dict(self) -> dict[int, FakeUnit]:
        return {unit.tag: unit for unit in self.units}

    @property
    def supply_workers(self) -> int:
        listed = sum(1 for unit in self.units if unit.type_id is UnitTypeId.SCV)
        return listed + self.workers_in_gas

    def calculate_supply_cost(self, type_id: UnitTypeId) -> float:
        return _SUPPLY.get(type_id, 0.0)

    def can_afford(self, type_id: UnitTypeId) -> bool:
        minerals, vespene = _COST[type_id]
        return self.minerals >= minerals and self.vespene >= vespene

    def register_behavior(self, behavior) -> None:
        self.registered.append(behavior)

    def get_terrain_z_height(self, position) -> float:
        return 10.0
