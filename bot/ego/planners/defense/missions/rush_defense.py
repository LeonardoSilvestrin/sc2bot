"""RushDefenseMission: hold one base behind a Bunker until the rush is over.

The planner opens it when the rush reading (`policies/rush.py`) says a rush is
coming or on, and hands it the base to hold. The mission is the Bunker's
operation, not the fight's: every incident keeps its own `DefendAreaMission`,
and what this one adds is a fortified spot to fight from.

- `FORTIFY`: no Bunker of ours is ready at the site. While none stands there,
  one is wanted (a direct plan: the Body has Ares build it); one being built
  is waited for.
- `HOLD`: the Bunker is ready. Marines are asked for its free slots, nearest
  first (`GARRISON`); they go in ahead of any incident, so the first ones on
  the spot fight from cover instead of in the open. SCVs are asked to repair
  it (`REPAIR`): one while it is damaged, and more with the attack on it --
  `REPAIRERS_PER_POWER` per Marine of incident power in reach of it, up to
  `MAX_REPAIRERS`. With nothing to repair and no attack, they go back to
  mining.

A Bunker that dies sends the mission back to `FORTIFY`. The mission completes
once the rush reading falls below `close_at` and no attacker presses the base
(`rush_over`), and in any case once Awareness says the early game is over
(`early_game_over`): past it there is no rush left to hold, whatever attacks
the base; it fails if the base is lost (`base_lost`). Either way the
garrison walks out: Marines inside a Bunker are listed nowhere, so the army
would never see them again. The Bunker itself stays, and a later rush defense
at the same base fights from it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId

from bot.attention import AttentionState, UnitView
from bot.awareness import AwarenessState
from bot.ego.planners import (
    BunkerSite,
    CancelMode,
    Command,
    Lifecycle,
    MissionFeedback,
    MissionStatus,
    MissionView,
    Proposal,
)

from ..policies.rush import RushConfig, RushReading

OWNER = "defense"
KIND = "rush_defense"
FORTIFY = "FORTIFY"
HOLD = "HOLD"
# A Bunker this close to the site's point is the site's.
BUNKER_REACH = 12.0
# What fills a Bunker: one slot each.
GARRISON_TYPES = frozenset({UnitTypeId.MARINE})
REPAIR_TYPES = frozenset({UnitTypeId.SCV})
# Filling the Bunker comes before any incident (whose priority stays below 1),
# so the Marines nearest it go in rather than out.
GARRISON_PRIORITY = 1.0
REPAIR_PRIORITY = 1.0
# An incident whose centre is this close to the Bunker is attacking it.
ATTACK_REACH = 15.0
# SCVs repairing per Marine of power attacking the Bunker ...
REPAIRERS_PER_POWER = 0.5
# ... and never more than this many.
MAX_REPAIRERS = 5


@dataclass(frozen=True, slots=True)
class RushStep:
    """What the mission asks for this frame."""

    proposals: tuple[Proposal, ...] = ()
    # The Bunker wanted, while none stands at the site.
    bunker: BunkerSite | None = None
    # Bunkers whose garrison walks out, by tag.
    unload: tuple[int, ...] = ()


class RushDefenseMission:
    def __init__(self, mission_id: str, site: BunkerSite, now: float, reason: str) -> None:
        self.lifecycle = Lifecycle(mission_id)
        self.site = site
        self.phase = FORTIFY
        self.since = now
        self.reason = reason
        # The Bunker that holds the site, once one is seen there.
        self.bunker: int | None = None

    @property
    def mission_id(self) -> str:
        return self.lifecycle.mission_id

    @property
    def status(self) -> MissionStatus:
        return self.lifecycle.status

    @property
    def active(self) -> bool:
        return self.lifecycle.active

    def request_cancel(self, mode: CancelMode, reason: str, now: float) -> None:
        self.lifecycle.request_cancel(mode, reason, now)

    def step(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        reading: RushReading,
        config: RushConfig,
    ) -> RushStep:
        if not self.active:
            return RushStep()
        now = attention.time
        bunker = self._find_bunker(attention)
        cancel = self.lifecycle.cancel
        if cancel is not None:
            return self._end(MissionStatus.CANCELLED, cancel.reason, now, bunker)
        if all(base.base_id != self.site.site_id for base in attention.bases):
            return self._end(MissionStatus.FAILED, "base_lost", now, bunker)
        if awareness.early_game <= 0.0:
            return self._end(MissionStatus.COMPLETED, "early_game_over", now, bunker)
        pressed = any(
            base.base_id == self.site.site_id and base.pressure > 0.0 for base in awareness.bases
        )
        if reading.level < config.close_at and not pressed:
            return self._end(MissionStatus.COMPLETED, "rush_over", now, bunker)
        if bunker is None:
            # Until one stands, the reason stays why the mission opened.
            if self.phase == HOLD:
                self._enter(FORTIFY, "bunker_lost", now)
            return RushStep(bunker=self.site)
        if not bunker.is_ready:
            self._enter(FORTIFY, "bunker_building", now)
            return RushStep()
        self._enter(HOLD, "bunker_ready", now)
        return RushStep(proposals=self._hold(bunker, awareness, reading))

    def view(self, feedback: MissionFeedback, proposals: Sequence[Proposal]) -> MissionView:
        return MissionView(
            mission_id=self.mission_id,
            owner=OWNER,
            kind=KIND,
            status=self.status,
            phase=self.phase,
            since=self.since,
            reason=self.reason,
            cancel=self.lifecycle.cancel,
            proposals=tuple(proposal.proposal_id for proposal in proposals),
            granted_units=len(feedback.tags),
            granted_power=feedback.power,
        )

    def _hold(
        self, bunker: UnitView, awareness: AwarenessState, reading: RushReading
    ) -> tuple[Proposal, ...]:
        proposals: list[Proposal] = []
        free = bunker.cargo_max - bunker.cargo_used
        common = (
            ("bunker_health", bunker.health),
            ("cargo_used", float(bunker.cargo_used)),
            ("cargo_max", float(bunker.cargo_max)),
            *reading.inputs,
        )
        if free > 0:
            proposals.append(
                Proposal(
                    proposal_id=f"{self.mission_id}:garrison",
                    owner=OWNER,
                    priority=GARRISON_PRIORITY,
                    command=Command.GARRISON,
                    target=bunker.position,
                    reason="bunker_slots_free",
                    count=free,
                    unit_types=GARRISON_TYPES,
                    inputs=common,
                    mission_id=self.mission_id,
                )
            )
        attacking = sum(
            incident.power
            for incident in awareness.incidents
            if incident.center.distance_to(bunker.position) <= ATTACK_REACH
        )
        repairers = math.ceil(REPAIRERS_PER_POWER * attacking - 1e-9)
        if bunker.health < 1.0:
            repairers = max(repairers, 1)
        repairers = min(repairers, MAX_REPAIRERS)
        if repairers > 0:
            proposals.append(
                Proposal(
                    proposal_id=f"{self.mission_id}:repair",
                    owner=OWNER,
                    priority=REPAIR_PRIORITY,
                    command=Command.REPAIR,
                    target=bunker.position,
                    reason="bunker_attacked" if attacking > 0.0 else "bunker_damaged",
                    count=repairers,
                    unit_types=REPAIR_TYPES,
                    inputs=(("attacking_power", attacking), *common),
                    mission_id=self.mission_id,
                )
            )
        return tuple(proposals)

    def _find_bunker(self, attention: AttentionState) -> UnitView | None:
        bunkers = [
            structure
            for structure in attention.own_structures
            if structure.type_id is UnitTypeId.BUNKER
            and structure.position.distance_to(self.site.near) <= BUNKER_REACH
        ]
        held = next((bunker for bunker in bunkers if bunker.tag == self.bunker), None)
        if held is None:
            # The one ready first, then the nearest: a second Bunker is a spare.
            held = min(
                bunkers,
                key=lambda bunker: (
                    not bunker.is_ready,
                    bunker.position.distance_to(self.site.near),
                    bunker.tag,
                ),
                default=None,
            )
        self.bunker = None if held is None else held.tag
        return held

    def _enter(self, phase: str, reason: str, now: float) -> None:
        if phase == self.phase and reason == self.reason:
            return
        if phase != self.phase:
            self.since = now
        self.phase, self.reason = phase, reason

    def _end(
        self, status: MissionStatus, reason: str, now: float, bunker: UnitView | None
    ) -> RushStep:
        self.since, self.reason = now, reason
        self.lifecycle.end(status)
        if bunker is None or bunker.cargo_used <= 0:
            return RushStep()
        return RushStep(unload=(bunker.tag,))
