"""Offense: take the army to the enemy once waiting gains nothing more.

A planner with a lifecycle, in stages, with at most one transition per frame:

- IDLE: no proposal, so CoreArmy holds the army at the rally.
- ASSEMBLE: committed, still no proposal, while CoreArmy gathers the army at
  the rally -- until `assemble_share` of the army's power stands within
  `assemble_radius` of it, or `assemble_timeout` after committing.
- ADVANCE: one ATTACK proposal for every free army unit, at the target.

The bot commits, from IDLE, with no threat at home (Strategy is not
stabilizing), no call-off in the last `cooldown` seconds and at least
`minimum_power` of army, once either

- the army is at least the enemy army Strategy plans against -- its estimate
  plus a margin on the part no contact places (`army_share` >= 1/2); or
- supply reached `maxed_supply`: the army cannot grow any more, so waiting
  only lets the enemy catch up.

A commitment is called off, back to IDLE, when home is threatened or the army
fell below `depleted_share` of the power it committed with.

The target is a remembered enemy structure: a townhall before any other kind,
the nearest to the rally first, the lowest tag on a tie. It is kept while it
is remembered and no better kind is known, so a nearer one of the same kind
does not pull the army around; once destroyed or forgotten, the next one takes
its place. With none known, the army goes to the enemy start.

Priority: Defense (positive exactly while an attacker is in reach) outranks the
offense (0), which outranks the CoreArmy fallback (-1). Defense takes the power
an incident needs and the offense the rest of the army.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ares.consts import TOWNHALL_TYPES
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState, MapView
from bot.awareness import AwarenessState, Contact
from bot.ego.planners import Command, Proposal
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
ENEMY_START = "enemy_start"


class Stage(str, Enum):
    IDLE = "IDLE"
    ASSEMBLE = "ASSEMBLE"
    ADVANCE = "ADVANCE"


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

    def __post_init__(self) -> None:
        if min(self.minimum_power, self.assemble_radius) <= 0.0:
            raise ValueError("minimum_power and assemble_radius must be positive")
        if not 0.0 < self.maxed_supply <= 200.0:
            raise ValueError("maxed_supply must be in (0, 200]")
        if not 0.0 < self.assemble_share <= 1.0:
            raise ValueError("assemble_share must be in (0, 1]")
        if not 0.0 <= self.depleted_share < 1.0:
            raise ValueError("depleted_share must be in [0, 1)")
        if min(self.assemble_timeout, self.cooldown) < 0.0:
            raise ValueError("assemble_timeout and cooldown must not be negative")


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
    # Where the army goes, while advancing.
    target: Point2 | None
    # The remembered enemy structure it goes to; None for the enemy start.
    target_tag: int | None
    # known_base, known_structure or enemy_start, while advancing.
    target_kind: str | None
    proposals: tuple[Proposal, ...]
    # The values the stage was decided from.
    inputs: tuple[tuple[str, float], ...]


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

    def plan(
        self, attention: AttentionState, awareness: AwarenessState, strategy: StrategyState
    ) -> OffensePlan:
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
            elif now - self._since >= config.assemble_timeout - _TOLERANCE:
                self._enter(Stage.ADVANCE, "assemble_timed_out", now)
            else:
                blocked_by = "army_not_assembled"

        known = _targets(awareness)
        inputs = (
            ("own_power", own),
            ("army_share", strategy.army_share),
            ("supply_used", attention.supply_used),
            ("assembled_share", assembled),
            ("committed_power", self._committed),
            ("stage_for", now - self._since),
            ("cooldown_left", cooldown_left),
            ("known_structures", float(len(known))),
        )
        target: Point2 | None = None
        kind: str | None = None
        proposals: tuple[Proposal, ...] = ()
        if self._stage is Stage.ADVANCE:
            target, kind = self._target(known, attention.map, strategy.rally)
            proposals = (
                Proposal(
                    proposal_id=OWNER,
                    owner=OWNER,
                    priority=PRIORITY,
                    command=Command.ATTACK,
                    target=target,
                    reason=f"advance_on_{kind}",
                    inputs=inputs,
                ),
            )
        else:
            self._target_tag = None
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
        )

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
        return chosen.position, KNOWN_BASE if _kind(chosen) == 0 else KNOWN_STRUCTURE


def _targets(awareness: AwarenessState) -> tuple[Contact, ...]:
    return tuple(
        contact
        for contact in awareness.contacts
        if contact.is_structure and contact.type_id not in _NOT_TARGETS
    )


def _kind(contact: Contact) -> int:
    """0 for a townhall, 1 for any other structure."""

    return 0 if contact.type_id in TOWNHALL_TYPES else 1


def _rank(contact: Contact, rally: Point2) -> tuple[int, float, int]:
    return (_kind(contact), contact.position.distance_to(rally), contact.tag)
