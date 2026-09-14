"""ENGINE: arbitration and execution.

Behaviors propose; the Engine ranks proposals by ``(-priority, owner,
proposal_id)``, grants every army unit to at most one of them and turns only
those grants into Ares commands. It is also where the economy plan becomes
Ares macro behaviors. It decides nothing about *what* the bot should do.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
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
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, UnitView

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


def is_army(unit: UnitView) -> bool:
    return not unit.is_worker and not unit.is_structure and unit.type_id not in _NOT_ARMY


class Command(str, Enum):
    # Attack-move to the target.
    ATTACK = "ATTACK"
    # Walk to the target and fight whatever comes there.
    HOLD = "HOLD"


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
    # Which unit types; None accepts any army unit.
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
    ) -> EngineResult:
        result = self.allocate(attention, proposals)
        command_army(bot, result)
        run_economy(bot, economy)
        return result

    def allocate(self, attention: AttentionState, proposals: Sequence[Proposal]) -> EngineResult:
        army = {unit.tag: unit for unit in attention.own_units if is_army(unit)}
        free = set(army)
        grants: list[Grant] = []
        seen: set[str] = set()
        for proposal in rank(proposals):
            if proposal.proposal_id in seen:
                raise ValueError(f"duplicate proposal id {proposal.proposal_id!r}")
            seen.add(proposal.proposal_id)
            candidates = sorted(
                (
                    army[tag]
                    for tag in free
                    if proposal.unit_types is None or army[tag].type_id in proposal.unit_types
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
            unassigned=tuple(sorted(free)),
        )


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
