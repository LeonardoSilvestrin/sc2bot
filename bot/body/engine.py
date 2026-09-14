"""ENGINE: who gets what.

Planners propose; the Engine ranks proposals by ``(-priority, owner,
proposal_id)`` and grants every army unit to at most one of them -- the units a
proposal already held first, then the nearest. Workers are eligible only for
proposals that name a worker type, only out of mining, and stay with the
proposal that took them. A unit no proposal holds any more is released. The
Engine commands nothing: what to do is the planners' decision, how to do it
the behaviors'.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ares.consts import UnitRole

from bot.attention import AttentionState, is_army
from bot.ego.planners import Proposal


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
    # Units some proposal held last frame and none holds now, by tag.
    released: tuple[int, ...]

    def owner_of(self, tag: int) -> str | None:
        return next((owner for owned, owner in self.owners if owned == tag), None)


def rank(proposals: Iterable[Proposal]) -> tuple[Proposal, ...]:
    return tuple(sorted(proposals, key=lambda item: (-item.priority, item.owner, item.proposal_id)))


class Engine:
    def __init__(self) -> None:
        self._owners: dict[int, str] = {}

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
        released = tuple(sorted(set(self._owners) - set(owners)))
        self._owners = owners
        return EngineResult(
            time=attention.time,
            grants=tuple(grants),
            owners=tuple(sorted(owners.items())),
            unassigned=tuple(sorted(tag for tag in free if tag in army)),
            released=released,
        )
