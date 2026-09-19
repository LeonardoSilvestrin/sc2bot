"""OffensePlanner: whether to attack -- when an attack opens, the cooldown
between attacks and when it asks a running one to end. How the attack goes is
`missions.main_attack.MainAttackMission`.

The planner holds at most one mission. With none open the offense is IDLE,
which is derived, not kept: since the last mission ended (or the first
frame), for the reason it ended. The planner keeps only what outlives an
attack: when the last one ended (the cooldown), and when each searchable place
was last in vision (an attack that searches reads it).

Whether to attack is read from Strategy's intent; how the offense serves
each posture is this planner's:

- PRESSURE or COMMIT: an attack opens, from IDLE, with at least
  `minimum_power` of army and no mission ended in the last `cooldown`
  seconds -- except under COMMIT, where the window is now: the cooldown is
  waived, so a defense won against a spent enemy turns into a counterattack.
  The attack opens for the intent's reason (`army_advantage`, `power_spike`,
  `decisive_advantage`).
- DEVELOP: no attack opens; a running one carries on until it ends itself --
  at its next regroup, since the posture is no longer offensive.
- RECOVER: no attack opens, and a running one is asked to cancel GRACEFULLY:
  it walks the army back to the rally before it ends.
- DEFEND: no attack opens, and a running one is asked to cancel IMMEDIATELY:
  its units are free for Defense and MapControl in the same allocation.

The mission also ends by itself (`main_attack`); every end starts the cooldown.

Priority: Defense (positive exactly while an attacker is in reach) outranks the
offense (0), which outranks MapControl (-1). Defense takes the power
an incident needs and the offense the rest of the army.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from sc2.position import Point2

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.missions import (
    CancelMode,
    MissionFeedback,
    MissionStatus,
    MissionView,
)
from bot.ego.planners import Proposal
from bot.ego.strategy import StrategicIntent, StrategicPosture

from .missions.main_attack import (
    KIND,
    OWNER,
    LocalFight,
    MainAttackMission,
    OffenseConfig,
    OffenseContext,
    Stage,
    offense_inputs,
    recent,
    targets,
)

if TYPE_CHECKING:
    from bot.body.engine import EngineResult


# Absorbs float noise so a value exactly at its threshold counts.
_TOLERANCE = 1e-9
# Why no attack opens, and why a running one is asked to end, by posture.
_HELD_BACK = {
    StrategicPosture.DEFEND: "home_threatened",
    StrategicPosture.RECOVER: "recovering",
    StrategicPosture.DEVELOP: "no_opportunity",
}


@dataclass(frozen=True, slots=True)
class OffensePlan:
    # The mission's phase, or IDLE with none open.
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
    # The mission stepped or opened this frame -- also on the frame it ended.
    mission_id: str | None = None
    mission_status: MissionStatus | None = None


@dataclass(frozen=True, slots=True)
class _Ended:
    time: float
    reason: str
    # The mission's last phase.
    phase: Stage


class OffensePlanner:
    def __init__(self, config: OffenseConfig | None = None) -> None:
        self.config = config or OffenseConfig()
        self._started: float | None = None
        # When each searchable place was last in vision.
        self._seen_at: dict[Point2, float] = {}
        self._mission: MainAttackMission | None = None
        self._ended: _Ended | None = None
        self._opened = 0
        self._views: tuple[MissionView, ...] = ()

    @property
    def mission(self) -> MainAttackMission | None:
        """The open mission, if any."""

        return self._mission

    def views(self) -> tuple[MissionView, ...]:
        """The missions this frame's `plan` governed, as they left it."""

        return self._views

    def plan(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        rally: Point2,
        feedback: EngineResult | None = None,
    ) -> OffensePlan:
        """`rally`: where the army assembles and falls back to, MapControl's
        anchor this frame. `feedback`: the last `EngineResult`, or None before
        the first."""

        config = self.config
        now = attention.time
        if self._started is None:
            self._started = now
        self._views = ()
        own = awareness.own_power
        near = sum(
            unit.power
            for unit in attention.own_units
            if not unit.is_worker
            and unit.power > 0.0
            and unit.position.distance_to(rally) <= config.assemble_radius
        )
        known = targets(awareness)
        places = self._look(attention)
        ctx = OffenseContext(
            attention=attention,
            awareness=awareness,
            intent=intent,
            rally=rally,
            places=places,
            seen_at=MappingProxyType(self._seen_at),
            own_power=own,
            assembled=near / own if own > 0.0 else 0.0,
            known=known,
            start_cleared=not known
            and recent(self._seen_at.get(attention.map.enemy_start), now, config.search_memory),
            offensive=intent.posture.offensive,
            cooldown_left=(
                0.0
                if self._ended is None
                else max(0.0, config.cooldown - (now - self._ended.time))
            ),
        )
        mission = self._mission
        if mission is not None:
            return self._govern(mission, ctx, feedback)
        return self._idle(ctx)

    def _govern(
        self, mission: MainAttackMission, ctx: OffenseContext, feedback: EngineResult | None
    ) -> OffensePlan:
        now = ctx.now
        posture = ctx.intent.posture
        if posture is StrategicPosture.DEFEND:
            # Defense needs the units now, and MapControl holds the rest at the
            # threatened base: no walk back first.
            mission.request_cancel(CancelMode.IMMEDIATE, _HELD_BACK[posture], now)
        elif posture is StrategicPosture.RECOVER:
            # Nothing presses at home: bring the army back whole.
            mission.request_cancel(CancelMode.GRACEFUL, _HELD_BACK[posture], now)
        granted = MissionFeedback.of(feedback, mission.mission_id)
        step = mission.step(ctx, granted)
        self._views = (mission.view(granted, step.proposals),)
        stage = step.phase
        if not mission.active:
            self._ended = _Ended(now, step.reason, step.phase)
            self._mission = None
            stage = Stage.IDLE
        return OffensePlan(
            stage=stage,
            previous=Stage.IDLE if step.previous is None else step.previous,
            since=step.since,
            reason=step.reason,
            blocked_by=step.blocked_by,
            committed_power=step.committed_power,
            target=step.target,
            target_tag=step.target_tag,
            target_kind=step.target_kind,
            proposals=step.proposals,
            inputs=step.inputs,
            fight=step.fight,
            mission_id=mission.mission_id,
            mission_status=mission.status,
        )

    def _idle(self, ctx: OffenseContext) -> OffensePlan:
        config = self.config
        now = ctx.now
        ended = self._ended
        assert self._started is not None
        since = self._started if ended is None else ended.time
        intent = ctx.intent
        own = ctx.own_power
        opened: str | None = None
        blocked_by: str | None = None
        if not ctx.offensive:
            blocked_by = _HELD_BACK[intent.posture]
        elif ctx.cooldown_left > _TOLERANCE and intent.posture is not StrategicPosture.COMMIT:
            blocked_by = "cooling_down"
        elif own < config.minimum_power - _TOLERANCE:
            blocked_by = "army_below_minimum"
        else:
            opened = intent.reason
        if opened is None:
            return OffensePlan(
                stage=Stage.IDLE,
                previous=None if ended is None else ended.phase,
                since=since,
                reason="not_committed" if ended is None else ended.reason,
                blocked_by=blocked_by,
                committed_power=0.0,
                target=None,
                target_tag=None,
                target_kind=None,
                proposals=(),
                inputs=offense_inputs(
                    ctx, committed=0.0, stage_for=now - since, clear_for=now - since
                ),
            )
        self._opened += 1
        mission = MainAttackMission(
            f"{OWNER}:{KIND}:{self._opened}", config, now=now, reason=opened, committed=own
        )
        self._mission = mission
        self._views = (mission.view(MissionFeedback(), ()),)
        return OffensePlan(
            stage=mission.phase,
            previous=Stage.IDLE,
            since=now,
            reason=opened,
            blocked_by=None,
            committed_power=own,
            target=None,
            target_tag=None,
            target_kind=None,
            proposals=(),
            inputs=offense_inputs(ctx, committed=own, stage_for=0.0, clear_for=now - since),
            mission_id=mission.mission_id,
            mission_status=mission.status,
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
