"""Offense: take the army to the enemy once waiting gains nothing more, fight
where it is favored, and step back where it is not.

A planner with a lifecycle, in stages, with at most one transition per frame:

- IDLE: no proposal, so CoreArmy holds the army at the rally.
- ASSEMBLE: committed, still no proposal, while CoreArmy gathers the army at
  the rally -- until `assemble_share` of the army's power stands within
  `assemble_radius` of it, or `assemble_timeout` after committing.
- ADVANCE: one ATTACK proposal for every free army unit, at the target.
- SEARCH: the same ATTACK proposal, at an expansion the enemy may hold.
- ENGAGE: the same ATTACK proposal, at the enemies near the squad.
- RETREAT: one RETREAT proposal: the squad walks back to the rally without
  fighting.
- REGROUP: no proposal again, while CoreArmy holds the army at the rally.

The bot commits, from IDLE, with no threat at home (Strategy is not
stabilizing), no call-off in the last `cooldown` seconds and at least
`minimum_power` of army, once either

- the army is at least the enemy army Strategy plans against -- its estimate
  plus a margin on the part no contact places (`army_share` >= 1/2); or
- supply reached `maxed_supply`: the army cannot grow any more, so waiting
  only lets the enemy catch up.

A commitment is called off, back to IDLE, when home is threatened or the army
fell below `depleted_share` of the power it committed with.

The fight is judged locally. The squad is what the Engine granted the offense
last frame; its core is the squad unit with the most squad power within
`engage_radius` of it. Its local share is that power against the remembered
enemy fighters (`power * confidence`, workers aside) within that radius plus
each contact's uncertainty. A fight the squad holds at least `won_share` of is
no contest: the attack-move on the way settles it, so it counts as no enemy
near. While advancing, the squad engages at a local share of at least
`engage_share` and retreats below it; once engaged, it retreats
only below `retreat_share` and after `engage_dwell` seconds of fighting, so a
share moving inside the band does not flip the decision. A fight with no
enemy near for `clear_after` seconds is won: the squad advances again. A
retreat ends at the rally, with the army assembled or `retreat_timeout` after
it began, and the army regroups for at least `regroup_dwell` seconds: then it
advances again if the commitment still holds (advantage or maxed supply), or
goes back to IDLE, which counts as a call-off.

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

Priority: Defense (positive exactly while an attacker is in reach) outranks the
offense (0), which outranks the CoreArmy fallback (-1). Defense takes the power
an incident needs and the offense the rest of the army.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np
from ares.consts import TOWNHALL_TYPES
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, MapView, UnitView
from bot.awareness import AwarenessState, Contact
from bot.ego.planners import Command, Domain, Proposal
from bot.ego.strategy import Objective, StrategyState

OWNER = "offense"
PRIORITY = 0.0
# The army is at least the enemy army planned against.
EVEN_SHARE = 0.5
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
    IDLE = "IDLE"
    ASSEMBLE = "ASSEMBLE"
    ADVANCE = "ADVANCE"
    SEARCH = "SEARCH"
    ENGAGE = "ENGAGE"
    RETREAT = "RETREAT"
    REGROUP = "REGROUP"


# The stages the offense holds units in.
_HOLDING = frozenset({Stage.ADVANCE, Stage.SEARCH, Stage.ENGAGE, Stage.RETREAT})
# The stages that go somewhere and judge a fight on the way.
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
    # A retreat ends this long after it began, even away from the rally ...
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
class OffensePlan:
    stage: Stage
    previous: Stage | None
    since: float
    # Why the stage was entered.
    reason: str
    # The rule that keeps the stage from moving on this frame; None on the
    # frame it changed and while advancing.
    blocked_by: str | None
    # Army power when the bot committed; 0 while idle.
    committed_power: float
    # Where the army goes, while holding units.
    target: Point2 | None
    # The remembered enemy structure it goes to; None for the enemy start.
    target_tag: int | None
    # known_base, known_structure, flying_structure, enemy_start or search,
    # while advancing, searching or engaged.
    target_kind: str | None
    proposals: tuple[Proposal, ...]
    # The values the stage was decided from.
    inputs: tuple[tuple[str, float], ...]
    # The squad's fight this frame; None without a squad.
    fight: LocalFight | None = None


class Offense:
    def __init__(self, config: OffenseConfig | None = None) -> None:
        self.config = config or OffenseConfig()
        self._stage = Stage.IDLE
        self._previous: Stage | None = None
        self._since: float | None = None
        self._reason = "not_committed"
        self._committed = 0.0
        self._called_off_at: float | None = None
        self._target_tag: int | None = None
        # When an enemy was last near the squad.
        self._enemy_near_at: float | None = None
        # When each searchable place was last in vision.
        self._seen_at: dict[Point2, float] = {}
        self._search_target: Point2 | None = None
        self._search_since = 0.0

    def plan(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        strategy: StrategyState,
        held: Collection[int] = (),
    ) -> OffensePlan:
        """`held`: the units the Engine granted the offense last frame."""

        config = self.config
        now = attention.time
        if self._since is None:
            self._since = now
        own = awareness.own_power
        near = sum(
            unit.power
            for unit in attention.own_units
            if not unit.is_worker
            and unit.power > 0.0
            and unit.position.distance_to(strategy.rally) <= config.assemble_radius
        )
        assembled = near / own if own > 0.0 else 0.0
        threatened = strategy.objective is Objective.STABILIZE
        cooldown_left = (
            0.0
            if self._called_off_at is None
            else max(0.0, config.cooldown - (now - self._called_off_at))
        )
        squad = [unit for unit in attention.own_units if unit.tag in held and unit.power > 0.0]
        squad_power = sum(unit.power for unit in squad)
        fight = _local_fight(squad, awareness.contacts, config.engage_radius)
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
        stage_for = now - self._since
        advantage = (
            strategy.army_share >= EVEN_SHARE - _TOLERANCE
            or attention.supply_used >= config.maxed_supply - _TOLERANCE
        )
        places = self._look(attention)
        known = _targets(awareness)
        start_cleared = not known and _recent(
            self._seen_at.get(attention.map.enemy_start), now, config.search_memory
        )
        blocked_by: str | None = None
        if self._stage is Stage.IDLE:
            if threatened:
                blocked_by = "home_threatened"
            elif cooldown_left > _TOLERANCE:
                blocked_by = "cooling_down"
            elif own < config.minimum_power - _TOLERANCE:
                blocked_by = "army_below_minimum"
            elif strategy.army_share >= EVEN_SHARE - _TOLERANCE:
                self._commit("army_advantage", now, own)
            elif attention.supply_used >= config.maxed_supply - _TOLERANCE:
                self._commit("supply_maxed", now, own)
            else:
                blocked_by = "no_advantage"
        elif threatened:
            self._call_off("home_threatened", now)
        elif own < config.depleted_share * self._committed - _TOLERANCE:
            self._call_off("army_depleted", now)
        elif self._stage is Stage.ASSEMBLE:
            if assembled >= config.assemble_share - _TOLERANCE:
                self._enter(Stage.ADVANCE, "army_assembled", now)
            elif stage_for >= config.assemble_timeout - _TOLERANCE:
                self._enter(Stage.ADVANCE, "assemble_timed_out", now)
            else:
                blocked_by = "army_not_assembled"
        elif self._stage in _MOVING and share is not None:
            if share >= config.engage_share - _TOLERANCE:
                self._enter(Stage.ENGAGE, "favorable_fight", now)
            else:
                self._enter(Stage.RETREAT, "unfavorable_fight", now)
        elif self._stage is Stage.ADVANCE:
            if start_cleared:
                self._enter(Stage.SEARCH, "enemy_start_empty", now)
        elif self._stage is Stage.SEARCH:
            if known:
                self._enter(Stage.ADVANCE, "structure_found", now)
        elif self._stage is Stage.ENGAGE:
            if share is None:
                if clear_for >= config.clear_after - _TOLERANCE:
                    self._enter(Stage.ADVANCE, "fight_won", now)
                else:
                    blocked_by = "clearing"
            elif share >= config.retreat_share - _TOLERANCE:
                blocked_by = "fight_holds"
            elif stage_for >= config.engage_dwell - _TOLERANCE:
                self._enter(Stage.RETREAT, "fight_lost", now)
            else:
                blocked_by = "engage_dwell"
        elif self._stage is Stage.RETREAT:
            if assembled >= config.assemble_share - _TOLERANCE:
                self._enter(Stage.REGROUP, "army_regrouped", now)
            elif stage_for >= config.retreat_timeout - _TOLERANCE:
                self._enter(Stage.REGROUP, "retreat_timed_out", now)
            else:
                blocked_by = "retreating"
        elif self._stage is Stage.REGROUP:
            if stage_for < config.regroup_dwell - _TOLERANCE:
                blocked_by = "regroup_dwell"
            elif (
                assembled < config.assemble_share - _TOLERANCE
                and stage_for < config.regroup_dwell + config.assemble_timeout - _TOLERANCE
            ):
                blocked_by = "army_not_assembled"
            elif advantage:
                # A new commitment, measured against the army it now has.
                self._enter(Stage.ADVANCE, "regrouped", now)
                self._committed = own
            else:
                self._call_off("advantage_lost", now)

        inputs = (
            ("own_power", own),
            ("army_share", strategy.army_share),
            ("supply_used", attention.supply_used),
            ("assembled_share", assembled),
            ("committed_power", self._committed),
            ("stage_for", now - self._since),
            ("cooldown_left", cooldown_left),
            ("known_structures", float(len(known))),
            ("squad_units", float(len(squad))),
            ("squad_power", squad_power),
            ("core_power", 0.0 if fight is None else fight.own_power),
            ("local_enemy_power", 0.0 if fight is None else fight.enemy_power),
            ("local_share", -1.0 if fight is None or fight.share is None else fight.share),
            ("contested", float(share is not None)),
            ("clear_for", clear_for),
            ("start_cleared", float(start_cleared)),
        )
        target: Point2 | None = None
        kind: str | None = None
        proposals: tuple[Proposal, ...] = ()
        must_attack: Domain | None = None
        if self._stage is Stage.SEARCH:
            self._target_tag = None
            origin = strategy.rally if fight is None else fight.center
            target = self._search(places, attention, origin)
            kind, reason = SEARCH_TARGET, "search_expansion"
        elif self._stage in (Stage.ADVANCE, Stage.ENGAGE):
            target, kind = self._target(known, attention.map, strategy.rally)
            reason = f"advance_on_{kind}"
            if kind == FLYING_STRUCTURE:
                must_attack = Domain.AIR
        if self._stage is Stage.ENGAGE and share is not None and fight.enemy_center:
            target, reason = fight.enemy_center, "engage_near_enemies"
        if target is not None:
            proposals = (self._proposal(Command.ATTACK, target, reason, inputs, must_attack),)
        elif self._stage is Stage.RETREAT:
            target = strategy.rally
            proposals = (self._proposal(Command.RETREAT, target, "retreat_to_rally", inputs),)
        if self._stage is not Stage.SEARCH:
            self._search_target = None
        if self._stage not in (Stage.ADVANCE, Stage.ENGAGE):
            self._target_tag = None
        if self._stage not in _HOLDING:
            self._enemy_near_at = None
        return OffensePlan(
            stage=self._stage,
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

    def _proposal(
        self,
        command: Command,
        target: Point2,
        reason: str,
        inputs: tuple[tuple[str, float], ...],
        must_attack: Domain | None = None,
    ) -> Proposal:
        # One id through every stage, so the Engine keeps the same units.
        return Proposal(
            proposal_id=OWNER,
            owner=OWNER,
            priority=PRIORITY,
            command=command,
            target=target,
            reason=reason,
            inputs=inputs,
            must_attack=must_attack,
        )

    def _look(self, attention: AttentionState) -> tuple[Point2, ...]:
        """The searchable places, with when each was last in vision."""

        map_view = attention.map
        places = tuple(
            sorted(
                {*map_view.expansions, map_view.enemy_start},
                key=lambda point: (point.x, point.y),
            )
        )
        for place in places:
            if attention.is_visible(place):
                self._seen_at[place] = attention.time
        return places

    def _search(
        self, places: tuple[Point2, ...], attention: AttentionState, origin: Point2
    ) -> Point2:
        now = attention.time
        held = self._search_target
        if held is not None and self._seen_at.get(held, -1.0) < self._search_since:
            return held
        ours = [base.position for base in attention.bases]
        candidates = [
            place
            for place in places
            if all(place.distance_to(base) > _OWN_BASE_DISTANCE for base in ours)
        ] or list(places)
        memory = self.config.search_memory

        def rank(place: Point2) -> tuple:
            seen = self._seen_at.get(place)
            if not _recent(seen, now, memory):
                return (0, place.distance_to(origin), place.x, place.y)
            return (1, seen, place.x, place.y)

        self._search_target = min(candidates, key=rank)
        self._search_since = now
        return self._search_target

    def _enter(self, stage: Stage, reason: str, now: float) -> None:
        self._previous, self._stage, self._since, self._reason = self._stage, stage, now, reason

    def _commit(self, reason: str, now: float, power: float) -> None:
        self._enter(Stage.ASSEMBLE, reason, now)
        self._committed = power

    def _call_off(self, reason: str, now: float) -> None:
        self._enter(Stage.IDLE, reason, now)
        self._called_off_at = now
        self._committed = 0.0

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


def _local_fight(
    squad: Sequence[UnitView], contacts: Sequence[Contact], radius: float
) -> LocalFight | None:
    """The fight around the squad's core: the unit with the most squad power
    within `radius` of it (the lowest tag on a tie). A squad strung out between
    home and the front is judged where most of it stands, not at an empty
    point between its parts."""

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
    enemy = weighted_x = weighted_y = 0.0
    for contact in contacts:
        if contact.power <= 0.0 or contact.is_worker:
            continue
        if contact.position.distance_to(center) > radius + contact.uncertainty:
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


def _targets(awareness: AwarenessState) -> tuple[Contact, ...]:
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


def _recent(seen: float | None, now: float, memory: float) -> bool:
    return seen is not None and now - seen <= memory + _TOLERANCE


def _rank(contact: Contact, rally: Point2) -> tuple[int, float, int]:
    return (_kind(contact), contact.position.distance_to(rally), contact.tag)
