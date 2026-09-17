"""ENGINE: who gets what.

Planners propose; the Engine ranks proposals by ``(-priority, owner,
proposal_id)`` and grants every army unit to at most one of them. A unit is a
candidate only if it meets the proposal's hard constraints -- its unit types,
what it must be able to shoot at -- and candidates go the units a proposal
already held first, then the nearest. A proposal asks for power, a head count
or every candidate still free, and each grant says whether it got that (FULL),
less (PARTIAL) or nothing (REJECTED), and why. Workers are eligible only for
proposals that name a worker type, only out of mining, and stay with the
proposal that took them. A unit no proposal holds any more is released. The
Engine commands nothing: what to do is the planners' decision, how to do it
the behaviors'.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from ares.consts import UnitRole

from bot.attention import AttentionState, UnitView, is_army
from bot.ego.planners import Domain, Proposal

# Absorbs float noise so a grant exactly at its minimum power counts.
_TOLERANCE = 1e-9


class GrantStatus(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class Grant:
    proposal: Proposal
    tags: tuple[int, ...]
    # Sum of the granted units' power, in Marines.
    power: float
    status: GrantStatus
    reason: str


@dataclass(frozen=True, slots=True)
class EngineResult:
    time: float
    # Every proposal, in arbitration order, with the units it was granted.
    grants: tuple[Grant, ...]
    # (tag, proposal_id), by tag.
    owners: tuple[tuple[int, str], ...]
    # Army units no proposal was granted.
    unassigned: tuple[int, ...]
    # Units some proposal held last frame and none holds now, by tag.
    released: tuple[int, ...]

    def owner_of(self, tag: int) -> str | None:
        return next((owner for owned, owner in self.owners if owned == tag), None)


def rank(proposals: Iterable[Proposal]) -> tuple[Proposal, ...]:
    return tuple(sorted(proposals, key=lambda item: (-item.priority, item.owner, item.proposal_id)))


class Engine:
    def __init__(self) -> None:
        self._owners: dict[int, str] = {}

    def held_by(self, proposal_id: str) -> frozenset[int]:
        """The units the last allocation granted a proposal: feedback for the
        planner that made it, which still names no unit."""

        return frozenset(tag for tag, owner in self._owners.items() if owner == proposal_id)

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
            eligible = [unit for unit in pool.values() if _meets(proposal, unit, army)]
            candidates = sorted(
                (unit for unit in eligible if unit.tag in free),
                # Units this proposal already held stay with it first, so a
                # grant does not churn as its units move.
                key=lambda unit: (
                    self._owners.get(unit.tag) != proposal.proposal_id,
                    unit.position.distance_to(proposal.target),
                    unit.tag,
                ),
            )
            chosen = _choose(proposal, candidates)
            power = sum(unit.power for unit in chosen)
            status, reason = _judge(proposal, chosen, power, bool(eligible))
            tags = tuple(sorted(unit.tag for unit in chosen))
            free.difference_update(tags)
            grants.append(Grant(proposal, tags, power, status, reason))
        owners = {tag: grant.proposal.proposal_id for grant in grants for tag in grant.tags}
        released = tuple(sorted(set(self._owners) - set(owners)))
        self._owners = owners
        return EngineResult(
            time=attention.time,
            grants=tuple(grants),
            owners=tuple(sorted(owners.items())),
            unassigned=tuple(sorted(tag for tag in free if tag in army)),
            released=released,
        )


def _meets(proposal: Proposal, unit: UnitView, army: Mapping[int, UnitView]) -> bool:
    """The proposal's hard constraints; no score can buy a unit past them."""

    if proposal.unit_types is None:
        if unit.tag not in army:
            return False
    elif unit.type_id not in proposal.unit_types:
        return False
    # A unit that adds no power cannot help reach a minimum power.
    if proposal.minimum_power is not None and unit.power <= 0.0:
        return False
    if proposal.must_attack is Domain.GROUND:
        return unit.can_attack_ground
    if proposal.must_attack is Domain.AIR:
        return unit.can_attack_air
    return True


def _choose(proposal: Proposal, candidates: list[UnitView]) -> list[UnitView]:
    limit = len(candidates) if proposal.count is None else max(0, proposal.count)
    if proposal.minimum_power is None:
        return candidates[:limit]
    chosen: list[UnitView] = []
    power = 0.0
    for unit in candidates[:limit]:
        if power >= proposal.minimum_power - _TOLERANCE:
            break
        chosen.append(unit)
        power += unit.power
    return chosen


def _judge(
    proposal: Proposal, chosen: list[UnitView], power: float, any_eligible: bool
) -> tuple[GrantStatus, str]:
    if proposal.minimum_power is not None:
        if power >= proposal.minimum_power - _TOLERANCE:
            return GrantStatus.FULL, "minimum_power_met"
        if chosen:
            return GrantStatus.PARTIAL, "insufficient_power"
    elif proposal.count is not None:
        if len(chosen) >= proposal.count:
            return GrantStatus.FULL, "count_met"
        if chosen:
            return GrantStatus.PARTIAL, "insufficient_units"
    elif chosen:
        # Every free unit is all it asked for, however few.
        return GrantStatus.FULL, "every_free_unit"
    # Nothing at all could serve it, or everything that could was ranked above.
    return GrantStatus.REJECTED, "eligible_units_taken" if any_eligible else "no_eligible_units"
