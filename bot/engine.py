"""ENGINE: arbitration and execution.

Behaviors propose; the Engine ranks proposals by ``(-priority, owner,
proposal_id)``, grants every army unit to at most one of them and turns only
those grants into Ares commands. Workers are granted only to proposals that
name a worker type, only out of mining, and go back to mining when no
proposal holds them any more. It is also where the economy and structure
plans become Ares behaviors and commands. It decides nothing about *what* the
bot should do.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from ares.behaviors.combat import CombatManeuver
from ares.behaviors.combat.individual import AMove, PathUnitToTarget, SiegeTankDecision
from ares.behaviors.macro import (
    AutoSupply,
    BuildWorkers,
    ExpansionController,
    GasBuildingController,
    MacroPlan,
    Mining,
    ProductionController,
    SpawnController,
)
from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import WORKER_TYPES, AttentionState, UnitView

# Neither workers nor structures, and still not an army.
_NOT_ARMY = frozenset(
    {
        UnitTypeId.MULE,
        UnitTypeId.AUTOTURRET,
        UnitTypeId.LARVA,
        UnitTypeId.EGG,
        UnitTypeId.BROODLING,
        UnitTypeId.OVERLORD,
        UnitTypeId.OVERSEER,
        UnitTypeId.CHANGELING,
        UnitTypeId.OBSERVER,
        UnitTypeId.ADEPTPHASESHIFT,
    }
)
_TANKS = frozenset({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED})
# A holding unit stops walking this close to its point and fights what comes.
HOLD_RADIUS = 4.0
# An attacking unit this close to its point idles there and auto-acquires.
ATTACK_ARRIVAL = 2.0
# A holding unit with an enemy this close fights its way instead of walking.
ENGAGE_RADIUS = 10.0
# How far a Siege Tank looks for the enemies it sieges against.
TANK_SIGHT = 14.0
# A scout this close to its point has reached it.
SCOUT_ARRIVAL = 3.0


def is_army(unit: UnitView) -> bool:
    return not unit.is_worker and not unit.is_structure and unit.type_id not in _NOT_ARMY


class Command(str, Enum):
    # Attack-move to the target.
    ATTACK = "ATTACK"
    # Walk to the target and fight whatever comes there.
    HOLD = "HOLD"
    # Walk to the target and do nothing else; a worker stops mining for it.
    SCOUT = "SCOUT"


@dataclass(frozen=True, slots=True)
class Proposal:
    proposal_id: str
    owner: str
    priority: float
    command: Command
    target: Point2
    reason: str
    # How many units; None asks for every eligible unit still free.
    count: int | None = None
    # Which unit types; None accepts any army unit. Only a proposal that names
    # a worker type can be granted workers.
    unit_types: frozenset[UnitTypeId] | None = None
    # The values the priority and count were computed from.
    inputs: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class EconomyPlan:
    # False while Ares' build runner still plays the opening.
    active: bool
    workers: int
    gas: int
    bases: int
    expand: bool
    # Spend on army regardless of the composition's proportions.
    freeflow: bool
    # (unit type, proportion, priority): lower priority numbers build first.
    composition: tuple[tuple[UnitTypeId, float, int], ...]
    reason: str


@dataclass(frozen=True, slots=True)
class StructurePlan:
    # Supply depots to lower, by tag.
    lower: tuple[int, ...]
    reason: str
    inputs: tuple[tuple[str, float], ...] = ()


@dataclass(frozen=True, slots=True)
class Grant:
    proposal: Proposal
    tags: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class EngineResult:
    time: float
    # Every proposal, in arbitration order, with the units it was granted.
    grants: tuple[Grant, ...]
    # (tag, proposal_id), by tag.
    owners: tuple[tuple[int, str], ...]
    # Army units no proposal was granted.
    unassigned: tuple[int, ...]

    def owner_of(self, tag: int) -> str | None:
        return next((owner for owned, owner in self.owners if owned == tag), None)


def rank(proposals: Iterable[Proposal]) -> tuple[Proposal, ...]:
    return tuple(sorted(proposals, key=lambda item: (-item.priority, item.owner, item.proposal_id)))


class Engine:
    def __init__(self) -> None:
        self._owners: dict[int, str] = {}

    def execute(
        self,
        bot,
        attention: AttentionState,
        proposals: Sequence[Proposal],
        economy: EconomyPlan,
        structures: StructurePlan,
    ) -> EngineResult:
        previous = self._owners
        result = self.allocate(attention, proposals)
        release_workers(bot, attention, previous, result)
        command_army(bot, result)
        run_economy(bot, economy)
        run_structures(bot, structures)
        return result

    def allocate(self, attention: AttentionState, proposals: Sequence[Proposal]) -> EngineResult:
        army = {unit.tag: unit for unit in attention.own_units if is_army(unit)}
        # A worker is only taken out of mining, and stays with whoever took it.
        workers = {
            unit.tag: unit
            for unit in attention.own_units
            if unit.is_worker
            and (unit.role == UnitRole.GATHERING.name or unit.tag in self._owners)
        }
        pool = {**army, **workers}
        free = set(pool)
        grants: list[Grant] = []
        seen: set[str] = set()
        for proposal in rank(proposals):
            if proposal.proposal_id in seen:
                raise ValueError(f"duplicate proposal id {proposal.proposal_id!r}")
            seen.add(proposal.proposal_id)
            candidates = sorted(
                (
                    pool[tag]
                    for tag in free
                    if (
                        tag in army
                        if proposal.unit_types is None
                        else pool[tag].type_id in proposal.unit_types
                    )
                ),
                # Units this proposal already held stay with it first, so a
                # grant does not churn as its units move.
                key=lambda unit: (
                    self._owners.get(unit.tag) != proposal.proposal_id,
                    unit.position.distance_to(proposal.target),
                    unit.tag,
                ),
            )
            chosen = candidates if proposal.count is None else candidates[: max(0, proposal.count)]
            tags = tuple(sorted(unit.tag for unit in chosen))
            free.difference_update(tags)
            grants.append(Grant(proposal=proposal, tags=tags))
        owners = {tag: grant.proposal.proposal_id for grant in grants for tag in grant.tags}
        self._owners = owners
        return EngineResult(
            time=attention.time,
            grants=tuple(grants),
            owners=tuple(sorted(owners.items())),
            unassigned=tuple(sorted(tag for tag in free if tag in army)),
        )


def release_workers(
    bot, attention: AttentionState, previous: Mapping[int, str], result: EngineResult
) -> None:
    """A worker no proposal holds any more goes back to mining."""

    owned = dict(result.owners)
    workers = {unit.tag for unit in attention.own_units if unit.is_worker}
    for tag in sorted(set(previous) - set(owned)):
        if tag in workers:
            bot.mediator.assign_role(tag=tag, role=UnitRole.GATHERING)


def command_army(bot, result: EngineResult) -> None:
    """Issue commands only for the units each proposal was granted."""

    units = bot.unit_tag_dict
    ground = bot.mediator.get_ground_grid
    air = bot.mediator.get_air_grid
    enemies = list(bot.enemy_units)
    for grant in result.grants:
        proposal = grant.proposal
        for tag in grant.tags:
            unit = units.get(tag)
            if unit is None:
                continue
            if proposal.command is Command.SCOUT:
                bot.register_behavior(
                    scout(bot, unit, proposal.target, air if unit.is_flying else ground)
                )
                continue
            close = [enemy for enemy in enemies if enemy.distance_to(unit) <= TANK_SIGHT]
            maneuver = CombatManeuver()
            if unit.type_id in _TANKS:
                maneuver.add(
                    SiegeTankDecision(
                        unit=unit,
                        close_enemy=close,
                        target=proposal.target,
                        stay_sieged_near_target=proposal.command is Command.HOLD,
                    )
                )
            engaged = any(enemy.distance_to(unit) <= ENGAGE_RADIUS for enemy in close)
            if proposal.command is Command.HOLD and not engaged:
                maneuver.add(
                    PathUnitToTarget(
                        unit=unit,
                        grid=air if unit.is_flying else ground,
                        target=proposal.target,
                        success_at_distance=HOLD_RADIUS,
                        sense_danger=False,
                    )
                )
            else:
                maneuver.add(
                    AMove(unit=unit, target=proposal.target, success_at_distance=ATTACK_ARRIVAL)
                )
            bot.register_behavior(maneuver)


def scout(bot, unit, target: Point2, grid) -> PathUnitToTarget:
    """The SCOUTING role keeps Ares' mining and building from taking the unit.

    No danger avoidance: to Ares' grid the enemy's own workers are danger, and
    a scout that keeps away from them never sees the mineral line.
    """

    if unit.type_id in WORKER_TYPES:
        bot.mediator.remove_worker_from_mineral(worker_tag=unit.tag)
    bot.mediator.assign_role(tag=unit.tag, role=UnitRole.SCOUTING)
    return PathUnitToTarget(
        unit=unit,
        grid=grid,
        target=target,
        success_at_distance=SCOUT_ARRIVAL,
        sense_danger=False,
    )


def run_economy(bot, plan: EconomyPlan) -> None:
    bot.register_behavior(Mining())
    if not plan.active:
        return
    composition = {
        unit_type: {"proportion": proportion, "priority": priority}
        for unit_type, proportion, priority in plan.composition
    }
    macro = MacroPlan()
    macro.add(AutoSupply(base_location=bot.start_location))
    macro.add(BuildWorkers(to_count=plan.workers))
    macro.add(GasBuildingController(to_count=plan.gas))
    if plan.expand:
        macro.add(ExpansionController(to_count=plan.bases))
    macro.add(SpawnController(composition, freeflow_mode=plan.freeflow))
    macro.add(ProductionController(composition, base_location=bot.start_location))
    bot.register_behavior(macro)


def run_structures(bot, plan: StructurePlan) -> None:
    lower = set(plan.lower)
    for structure in bot.structures:
        if structure.tag in lower:
            structure(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
