"""MainAttackMission: one attack, from gathering the army to calling it off.

The offense planner opens it and may ask it to end; the mission carries the
attack through its phases, with at most one transition per frame:

- ASSEMBLE: no proposal, while MapControl gathers the army at the rally -- until
  `assemble_share` of the army's power stands within `assemble_radius` of it,
  or `assemble_timeout` after the attack opened.
- ADVANCE: one ATTACK proposal for every free army unit, at the target.
- SEARCH: the same ATTACK proposal, at an expansion the enemy may hold.
- ENGAGE: the same ATTACK proposal, at the enemies near the squad.
- RETREAT: one RETREAT proposal: the squad walks back to the rally without
  fighting.
- REGROUP: no proposal again, while MapControl holds the army at the rally.
- WITHDRAW: only after a graceful cancel request: the RETREAT proposal until
  the army is assembled at the rally or `retreat_timeout` passed, then the
  mission is CANCELLED.

The mission ends by itself as FAILED when the army fell below
`depleted_share` of the power it committed with (`army_depleted`), or when a
regroup finds the commitment no longer holds (`advantage_lost`). An immediate
cancel request, or a graceful one while the mission holds no unit (ASSEMBLE,
REGROUP), ends it as CANCELLED at once. The proposal keeps the id `offense`
through every phase and every mission, so the Engine keeps the same units.

The fight is judged locally. The squad is what the Engine granted the mission
last frame; its core is the squad unit with the most squad power within
`engage_radius` of it, and the core group is what that power is made of -- the
squad units within `engage_radius` of the core. Its local share is that power
against the remembered enemy fighters (`power * confidence`, workers aside)
within `engage_radius` of any unit of the core group, plus each contact's
uncertainty: an enemy shooting the front of the group is in the fight even
when the core stands at the back of it. A fight the squad holds at least `won_share` of is
no contest: the attack-move on the way settles it, so it counts as no enemy
near. While advancing, the squad engages at a local share of at least
`engage_share` and retreats below it; once engaged, it retreats
only below `retreat_share` and after `engage_dwell` seconds of fighting, so a
share moving inside the band does not flip the decision. A fight with no
enemy near for `clear_after` seconds is won: the squad advances again. A
retreat ends at the rally, with the army assembled or `retreat_timeout` after
it began, and the army regroups for at least `regroup_dwell` seconds: then it
advances again if the commitment still holds (advantage or maxed supply), or
the mission fails.

The target is a remembered enemy structure: a townhall on the ground before
any other structure on the ground, and those before a structure in the air;
the nearest to the rally first, the lowest tag on a tie. It is kept while it
is remembered and no better kind is known, so a nearer one of the same kind
does not pull the army around; once destroyed or forgotten, the next one takes
its place. A structure in the air is attacked only by units that shoot up.
With none known, the army goes to the enemy start -- unless the start was in
vision within `search_memory` seconds, found empty: then the army searches.

Searching goes from expansion to expansion (the enemy start among them, our
own bases aside): first those out of vision for more than `search_memory`
seconds, the nearest to the squad first, then the one out of vision the
longest; ties by position. The target is kept until it comes into vision. A
fight while searching is judged as while advancing, and a structure found
sends the army back to advancing on it.
A fight won while searching goes back to advancing, which searches again on
the next frame if the enemy start is still known empty.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np
from ares.consts import TOWNHALL_TYPES
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, MapView, UnitView
from bot.awareness import AwarenessState, Contact
from bot.ego.missions import (
    CancelMode,
    Lifecycle,
    MissionFeedback,
    MissionStatus,
    MissionView,
)
from bot.ego.planners import Command, Domain, Proposal
from bot.ego.strategy import StrategyState

OWNER = "offense"
KIND = "main_attack"
# One id through every phase and every mission, so the Engine keeps the same units.
PROPOSAL_ID = OWNER
PRIORITY = 0.0
# Absorbs float noise so a value exactly at its threshold counts.
_TOLERANCE = 1e-9
# Cloaked and spread everywhere: never where the army goes.
_NOT_TARGETS = frozenset(
    {UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMORQUEEN}
)
KNOWN_BASE = "known_base"
KNOWN_STRUCTURE = "known_structure"
FLYING_STRUCTURE = "flying_structure"
ENEMY_START = "enemy_start"
SEARCH_TARGET = "search"
_KINDS = (KNOWN_BASE, KNOWN_STRUCTURE, FLYING_STRUCTURE)
# An expansion this close to one of our bases is ours, not searched.
_OWN_BASE_DISTANCE = 6.0


class Stage(str, Enum):
    """IDLE is the planner's: no mission open. The rest are the mission's phases."""

    IDLE = "IDLE"
    ASSEMBLE = "ASSEMBLE"
    ADVANCE = "ADVANCE"
    SEARCH = "SEARCH"
    ENGAGE = "ENGAGE"
    RETREAT = "RETREAT"
    REGROUP = "REGROUP"
    WITHDRAW = "WITHDRAW"


# The phases the mission holds units in.
_HOLDING = frozenset({Stage.ADVANCE, Stage.SEARCH, Stage.ENGAGE, Stage.RETREAT, Stage.WITHDRAW})
# The phases that go somewhere and judge a fight on the way.
_MOVING = frozenset({Stage.ADVANCE, Stage.SEARCH})


@dataclass(frozen=True, slots=True)
class OffenseConfig:
    # Army, in Marines, the bot never commits with less of.
    minimum_power: float = 20.0
    # Supply at which the army cannot grow any more.
    maxed_supply: float = 190.0
    # The army is assembled once this share of its power stands this close to
    # the rally, in cells ...
    assemble_share: float = 0.8
    assemble_radius: float = 12.0
    # ... and advances anyway this long after committing.
    assemble_timeout: float = 45.0
    # A commitment is called off below this share of the power it started with ...
    depleted_share: float = 0.5
    # ... and the next one waits this long after any call-off.
    cooldown: float = 30.0
    # How far from the squad's centre a fight counts, in cells.
    engage_radius: float = 16.0
    # The squad's local share of power it engages at, and retreats below once
    # engaged -- after fighting at least `engage_dwell` seconds.
    engage_share: float = 0.5
    retreat_share: float = 0.35
    engage_dwell: float = 4.0
    # A fight the squad holds this share of is no contest.
    won_share: float = 0.9
    # A fight with no enemy near for this long is won.
    clear_after: float = 3.0
    # A retreat, or a withdrawal, ends this long after it began, even away
    # from the rally ...
    retreat_timeout: float = 30.0
    # ... and the army then regroups at least this long.
    regroup_dwell: float = 10.0
    # A place in vision this recently needs no searching.
    search_memory: float = 60.0

    def __post_init__(self) -> None:
        if min(self.minimum_power, self.assemble_radius, self.engage_radius) <= 0.0:
            raise ValueError("minimum_power, assemble_radius and engage_radius must be positive")
        if not 0.0 < self.maxed_supply <= 200.0:
            raise ValueError("maxed_supply must be in (0, 200]")
        if not 0.0 < self.assemble_share <= 1.0:
            raise ValueError("assemble_share must be in (0, 1]")
        if not 0.0 <= self.depleted_share < 1.0:
            raise ValueError("depleted_share must be in [0, 1)")
        if not 0.0 <= self.retreat_share <= self.engage_share <= self.won_share <= 1.0:
            raise ValueError("retreat_share <= engage_share <= won_share must be in [0, 1]")
        for name in (
            "assemble_timeout",
            "cooldown",
            "engage_dwell",
            "clear_after",
            "retreat_timeout",
            "regroup_dwell",
            "search_memory",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True, slots=True)
class LocalFight:
    """The squad against the enemy fighters near it."""

    center: Point2
    own_power: float
    enemy_power: float
    # (power * confidence)-weighted position of the enemies near; None without.
    enemy_center: Point2 | None

    @property
    def share(self) -> float | None:
        """The squad's share of the power near it; None with no enemy near."""

        if self.enemy_power <= 0.0:
            return None
        return self.own_power / (self.own_power + self.enemy_power)


@dataclass(frozen=True, slots=True)
class OffenseContext:
    """What the planner hands its mission each frame: the layers, and the
    signals it measured for its own decisions too."""

    attention: AttentionState
    awareness: AwarenessState
    strategy: StrategyState
    # Where the army assembles and falls back to: MapControl's anchor.
    rally: Point2
    # The searchable places, and when each was last in vision (the planner's
    # memory, read only).
    places: tuple[Point2, ...]
    seen_at: Mapping[Point2, float]
    own_power: float
    # Share of the army's power within `assemble_radius` of the rally.
    assembled: float
    known: tuple[Contact, ...]
    start_cleared: bool
    # The army is at least the enemy planned against, or supply is maxed.
    advantage: bool
    cooldown_left: float

    @property
    def now(self) -> float:
        return self.attention.time


@dataclass(frozen=True, slots=True)
class MainAttackStep:
    """What the mission did this frame."""

    status: MissionStatus
    phase: Stage
    previous: Stage | None
    since: float
    reason: str
    blocked_by: str | None
    committed_power: float
    target: Point2 | None
    target_tag: int | None
    target_kind: str | None
    proposals: tuple[Proposal, ...]
    inputs: tuple[tuple[str, float], ...]
    fight: LocalFight | None


class MainAttackMission:
    def __init__(
        self,
        mission_id: str,
        config: OffenseConfig,
        *,
        now: float,
        reason: str,
        committed: float,
    ) -> None:
        self.lifecycle = Lifecycle(mission_id)
        self.config = config
        self._phase = Stage.ASSEMBLE
        self._previous: Stage | None = None
        self._since = now
        self._reason = reason
        self._committed = committed
        self._target_tag: int | None = None
        # When an enemy was last near the squad.
        self._enemy_near_at: float | None = None
        self._search_target: Point2 | None = None
        self._search_since = 0.0

    @property
    def mission_id(self) -> str:
        return self.lifecycle.mission_id

    @property
    def status(self) -> MissionStatus:
        return self.lifecycle.status

    @property
    def active(self) -> bool:
        return self.lifecycle.active

    @property
    def phase(self) -> Stage:
        """The current phase; the last one once the mission ended."""

        return self._phase

    @property
    def previous(self) -> Stage | None:
        return self._previous

    @property
    def since(self) -> float:
        return self._since

    @property
    def reason(self) -> str:
        return self._reason

    @property
    def committed_power(self) -> float:
        return self._committed

    def request_cancel(self, mode: CancelMode, reason: str, now: float) -> None:
        self.lifecycle.request_cancel(mode, reason, now)

    def step(self, ctx: OffenseContext, feedback: MissionFeedback) -> MainAttackStep:
        """`feedback`: what the Engine granted this mission last frame."""

        config = self.config
        now = ctx.now
        held = feedback.tags if self.active else frozenset()
        squad = [unit for unit in ctx.attention.own_units if unit.tag in held and unit.power > 0.0]
        squad_power = sum(unit.power for unit in squad)
        fight = _local_fight(squad, ctx.awareness.contacts, config.engage_radius)
        share = None if fight is None else fight.share
        # Trace bench/all 000, 871-966 s: engaged with 0.95 of the power near,
        # the army chased 2 Marines of enemy across the map instead of the base.
        if share is not None and share >= config.won_share - _TOLERANCE:
            share = None
        if share is not None:
            self._enemy_near_at = now
        clear_for = (
            now - self._since
            if self._enemy_near_at is None
            else now - max(self._enemy_near_at, self._since)
        )
        blocked_by = self._advance(ctx, share, clear_for) if self.active else None
        inputs = offense_inputs(
            ctx,
            committed=self._committed,
            stage_for=now - self._since,
            squad=squad,
            squad_power=squad_power,
            fight=fight,
            contested=share is not None,
            clear_for=clear_for,
        )
        phase = self._phase if self.active else None
        rally = ctx.rally
        target: Point2 | None = None
        kind: str | None = None
        proposals: tuple[Proposal, ...] = ()
        must_attack: Domain | None = None
        if phase is Stage.SEARCH:
            self._target_tag = None
            origin = rally if fight is None else fight.center
            target = self._search(ctx, origin)
            kind, reason = SEARCH_TARGET, "search_expansion"
        elif phase in (Stage.ADVANCE, Stage.ENGAGE):
            target, kind = self._target(ctx.known, ctx.attention.map, rally)
            reason = f"advance_on_{kind}"
            if kind == FLYING_STRUCTURE:
                must_attack = Domain.AIR
        if phase is Stage.ENGAGE and share is not None and fight.enemy_center:
            target, reason = fight.enemy_center, "engage_near_enemies"
        if target is not None:
            proposals = (self._proposal(Command.ATTACK, target, reason, inputs, must_attack),)
        elif phase is Stage.RETREAT:
            target = rally
            proposals = (self._proposal(Command.RETREAT, target, "retreat_to_rally", inputs),)
        elif phase is Stage.WITHDRAW:
            target = rally
            proposals = (self._proposal(Command.RETREAT, target, "withdraw_to_rally", inputs),)
        if phase is not Stage.SEARCH:
            self._search_target = None
        if phase not in (Stage.ADVANCE, Stage.ENGAGE):
            self._target_tag = None
        if phase not in _HOLDING:
            self._enemy_near_at = None
        return MainAttackStep(
            status=self.status,
            phase=self._phase,
            previous=self._previous,
            since=self._since,
            reason=self._reason,
            blocked_by=blocked_by,
            committed_power=self._committed,
            target=target,
            target_tag=self._target_tag,
            target_kind=kind,
            proposals=proposals,
            inputs=inputs,
            fight=fight,
        )

    def view(self, feedback: MissionFeedback, proposals: Sequence[Proposal]) -> MissionView:
        return MissionView(
            mission_id=self.mission_id,
            owner=OWNER,
            kind=KIND,
            status=self.status,
            phase=self._phase.value,
            since=self._since,
            reason=self._reason,
            cancel=self.lifecycle.cancel,
            proposals=tuple(proposal.proposal_id for proposal in proposals),
            granted_units=len(feedback.tags),
            granted_power=feedback.power,
        )

    def _advance(
        self, ctx: OffenseContext, share: float | None, clear_for: float
    ) -> str | None:
        """At most one transition; returns the rule that kept the phase, if any."""

        config = self.config
        now = ctx.now
        stage_for = now - self._since
        assembled = ctx.assembled
        cancel = self.lifecycle.cancel
        if cancel is not None and (
            cancel.mode is CancelMode.IMMEDIATE or self._phase not in _HOLDING
        ):
            # Nothing held to walk back, or the planner needs the units now.
            self._end(MissionStatus.CANCELLED, cancel.reason, now)
        elif cancel is not None and self._phase is not Stage.WITHDRAW:
            self._enter(Stage.WITHDRAW, cancel.reason, now)
        elif self._phase is Stage.WITHDRAW:
            if assembled >= config.assemble_share - _TOLERANCE:
                self._end(MissionStatus.CANCELLED, "withdrawn", now)
            elif stage_for >= config.retreat_timeout - _TOLERANCE:
                self._end(MissionStatus.CANCELLED, "withdraw_timed_out", now)
            else:
                return "withdrawing"
        elif ctx.own_power < config.depleted_share * self._committed - _TOLERANCE:
            self._end(MissionStatus.FAILED, "army_depleted", now)
        elif self._phase is Stage.ASSEMBLE:
            if assembled >= config.assemble_share - _TOLERANCE:
                self._enter(Stage.ADVANCE, "army_assembled", now)
            elif stage_for >= config.assemble_timeout - _TOLERANCE:
                self._enter(Stage.ADVANCE, "assemble_timed_out", now)
            else:
                return "army_not_assembled"
        elif self._phase in _MOVING and share is not None:
            if share >= config.engage_share - _TOLERANCE:
                self._enter(Stage.ENGAGE, "favorable_fight", now)
            else:
                self._enter(Stage.RETREAT, "unfavorable_fight", now)
        elif self._phase is Stage.ADVANCE:
            if ctx.start_cleared:
                self._enter(Stage.SEARCH, "enemy_start_empty", now)
        elif self._phase is Stage.SEARCH:
            if ctx.known:
                self._enter(Stage.ADVANCE, "structure_found", now)
        elif self._phase is Stage.ENGAGE:
            if share is None:
                if clear_for >= config.clear_after - _TOLERANCE:
                    self._enter(Stage.ADVANCE, "fight_won", now)
                else:
                    return "clearing"
            elif share >= config.retreat_share - _TOLERANCE:
                return "fight_holds"
            elif stage_for >= config.engage_dwell - _TOLERANCE:
                self._enter(Stage.RETREAT, "fight_lost", now)
            else:
                return "engage_dwell"
        elif self._phase is Stage.RETREAT:
            if assembled >= config.assemble_share - _TOLERANCE:
                self._enter(Stage.REGROUP, "army_regrouped", now)
            elif stage_for >= config.retreat_timeout - _TOLERANCE:
                self._enter(Stage.REGROUP, "retreat_timed_out", now)
            else:
                return "retreating"
        elif self._phase is Stage.REGROUP:
            if stage_for < config.regroup_dwell - _TOLERANCE:
                return "regroup_dwell"
            if (
                assembled < config.assemble_share - _TOLERANCE
                and stage_for < config.regroup_dwell + config.assemble_timeout - _TOLERANCE
            ):
                return "army_not_assembled"
            if ctx.advantage:
                # A new commitment, measured against the army it now has.
                self._enter(Stage.ADVANCE, "regrouped", now)
                self._committed = ctx.own_power
            else:
                self._end(MissionStatus.FAILED, "advantage_lost", now)
        return None

    def _proposal(
        self,
        command: Command,
        target: Point2,
        reason: str,
        inputs: tuple[tuple[str, float], ...],
        must_attack: Domain | None = None,
    ) -> Proposal:
        return Proposal(
            proposal_id=PROPOSAL_ID,
            owner=OWNER,
            priority=PRIORITY,
            command=command,
            target=target,
            reason=reason,
            inputs=inputs,
            must_attack=must_attack,
            mission_id=self.mission_id,
        )

    def _search(self, ctx: OffenseContext, origin: Point2) -> Point2:
        now = ctx.now
        seen_at = ctx.seen_at
        held = self._search_target
        if held is not None and seen_at.get(held, -1.0) < self._search_since:
            return held
        ours = [base.position for base in ctx.attention.bases]
        candidates = [
            place
            for place in ctx.places
            if all(place.distance_to(base) > _OWN_BASE_DISTANCE for base in ours)
        ] or list(ctx.places)
        memory = self.config.search_memory

        def rank(place: Point2) -> tuple:
            seen = seen_at.get(place)
            if not recent(seen, now, memory):
                return (0, place.distance_to(origin), place.x, place.y)
            return (1, seen, place.x, place.y)

        self._search_target = min(candidates, key=rank)
        self._search_since = now
        return self._search_target

    def _enter(self, stage: Stage, reason: str, now: float) -> None:
        self._previous, self._phase, self._since, self._reason = self._phase, stage, now, reason

    def _end(self, status: MissionStatus, reason: str, now: float) -> None:
        # `previous` keeps the last phase, `phase` stays on it.
        self._previous, self._since, self._reason = self._phase, now, reason
        self._committed = 0.0
        self.lifecycle.end(status)

    def _target(
        self, known: tuple[Contact, ...], map_view: MapView, rally: Point2
    ) -> tuple[Point2, str]:
        if not known:
            self._target_tag = None
            return map_view.enemy_start, ENEMY_START
        best = min(known, key=lambda contact: _rank(contact, rally))
        held = next((contact for contact in known if contact.tag == self._target_tag), None)
        chosen = best if held is None or _kind(held) > _kind(best) else held
        self._target_tag = chosen.tag
        return chosen.position, _KINDS[_kind(chosen)]


def offense_inputs(
    ctx: OffenseContext,
    *,
    committed: float,
    stage_for: float,
    squad: Sequence[UnitView] = (),
    squad_power: float = 0.0,
    fight: LocalFight | None = None,
    contested: bool = False,
    clear_for: float,
) -> tuple[tuple[str, float], ...]:
    """The values the offense decided from, with or without a mission."""

    return (
        ("own_power", ctx.own_power),
        ("army_share", ctx.strategy.army_share),
        ("supply_used", ctx.attention.supply_used),
        ("assembled_share", ctx.assembled),
        ("committed_power", committed),
        ("stage_for", stage_for),
        ("cooldown_left", ctx.cooldown_left),
        ("known_structures", float(len(ctx.known))),
        ("squad_units", float(len(squad))),
        ("squad_power", squad_power),
        ("core_power", 0.0 if fight is None else fight.own_power),
        ("local_enemy_power", 0.0 if fight is None else fight.enemy_power),
        ("local_share", -1.0 if fight is None or fight.share is None else fight.share),
        ("contested", float(contested)),
        ("clear_for", clear_for),
        ("start_cleared", float(ctx.start_cleared)),
    )


def _local_fight(
    squad: Sequence[UnitView], contacts: Sequence[Contact], radius: float
) -> LocalFight | None:
    """The fight around the squad's core: the unit with the most squad power
    within `radius` of it (the lowest tag on a tie). A squad strung out between
    home and the front is judged where most of it stands, not at an empty
    point between its parts.

    The enemy side is every remembered fighter within `radius` of any unit of
    that core group. Measured from the core alone, a bio ball 25 cells long
    read 6.8 of enemy power against six sieged Siege Tanks and two Thors
    standing 18-29 cells away (`bench/base3/007`, 515-521 s): `share` 0.88,
    then `fight_won` with `enemy_power` 0, while the squad fell from 62 of
    power to 27."""

    fighters = [unit for unit in squad if unit.power > 0.0]
    if not fighters:
        return None
    xy = np.array([(unit.position.x, unit.position.y) for unit in fighters])
    power = np.array([unit.power for unit in fighters])
    near = ((xy[:, None, :] - xy[None, :, :]) ** 2).sum(axis=2) <= radius * radius + _TOLERANCE
    held = near @ power
    best = max(range(len(fighters)), key=lambda index: (held[index], -fighters[index].tag))
    center = fighters[best].position
    own = float(held[best])
    # What the core's power is made of: the enemy is measured against those
    # units, not against the core alone.
    group = xy[near[best]]
    fighting = [
        contact for contact in contacts if contact.power > 0.0 and not contact.is_worker
    ]
    enemy = weighted_x = weighted_y = 0.0
    if fighting:
        there = np.array([(item.position.x, item.position.y) for item in fighting])
        gaps = np.sqrt(((group[:, None, :] - there[None, :, :]) ** 2).sum(axis=2)).min(axis=0)
        for contact, gap in zip(fighting, gaps, strict=True):
            if gap > radius + contact.uncertainty:
                continue
            weight = contact.power * contact.confidence
            enemy += weight
            weighted_x += weight * contact.position.x
            weighted_y += weight * contact.position.y
    return LocalFight(
        center=center,
        own_power=own,
        enemy_power=enemy,
        enemy_center=Point2((weighted_x / enemy, weighted_y / enemy)) if enemy > 0.0 else None,
    )


def targets(awareness: AwarenessState) -> tuple[Contact, ...]:
    """The remembered enemy structures an attack may go to."""

    return tuple(
        contact
        for contact in awareness.contacts
        if contact.is_structure and contact.type_id not in _NOT_TARGETS
    )


def _kind(contact: Contact) -> int:
    """0 for a townhall on the ground, 1 for any other structure on the
    ground, 2 for a structure in the air."""

    if contact.is_flying:
        return 2
    return 0 if contact.type_id in TOWNHALL_TYPES else 1


def recent(seen: float | None, now: float, memory: float) -> bool:
    return seen is not None and now - seen <= memory + _TOLERANCE


def _rank(contact: Contact, rally: Point2) -> tuple[int, float, int]:
    return (_kind(contact), contact.position.distance_to(rally), contact.tag)
