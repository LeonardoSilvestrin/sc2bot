"""MapControlPlanner: where the army no operation needs stands.

Always proposed, always last -- below Defense and the offense: it asks for
every free army unit and holds them at its anchor. It is no strategic
reserve: it gets whatever the planners above left. Against Zerg a separate
remove-creep mission coordinates a Raven and a small noncombat escort.

The anchor is where the uncommitted army reacts from and stages for the next
operation: the frame hands it to the `OffensePlanner` as the rally, where the
offense assembles and falls back to, and no planner calls another.

Where the anchor is, first match wins:

- `threatened_base`: DEFEND with a threatened base -- the most threatened
  base, as the army's place is at home.
- `staging` (`staging`): the lattice point that best answers every base of
  ours, a little in front of them, on a choke that guards them if one is at
  hand, away from the enemy's influence; kept until another outscores it by
  `staging_margin`. Evaluated every frame, and logged even while a threatened
  base is held.
- `legacy`: in front of the forward base, `rally_forward` toward the enemy
  start, or the main ramp while the main is the only base -- whenever staging
  places no anchor (`fallback` says why).

How far forward staging stands is this planner's reading of Strategy's
posture: `advance` 0 under DEFEND and RECOVER (the point only covers our
bases), `advance` under DEVELOP and `pressure_advance` under PRESSURE and
COMMIT, when the army waits further out on the enemy's way.

Its proposal keeps the id and owner `core_army`, its name before the renames:
the logs, the viewer and every bench so far know it by that name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sc2.data import Race
from sc2.position import Point2

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.economy.contracts import UnitRequest
from bot.ego.planners import CancelMode, Command, MissionFeedback, MissionView, Proposal
from bot.ego.strategy import StrategicIntent, StrategicPosture

from .missions.remove_creep import RemoveCreepConfig, RemoveCreepMission
from .policies.staging import StagingPlan, StagingPolicy

if TYPE_CHECKING:
    from bot.body.engine import EngineResult

OWNER = "core_army"
MAP_CONTROL_PRIORITY = -1.0

THREATENED_BASE = "threatened_base"
STAGING = "staging"
LEGACY = "legacy"


@dataclass(frozen=True, slots=True)
class MapControlConfig:
    # How far in front of the forward base the legacy anchor holds.
    rally_forward: float = 6.0
    # The staging score: -reaction + choke - exposure.
    # How much standing in front of a base, on the enemy's way to it, shortens
    # the response to it while developing; none while defending or recovering
    # ...
    advance: float = 0.7
    # ... and more while pressuring or committing: the army waits further out.
    pressure_advance: float = 0.8
    choke_weight: float = 0.15
    threat_weight: float = 0.3
    control_weight: float = 0.2
    # A challenger must outscore the held point by this much, in shares of the
    # distance between the starts, while our bases and the objective hold.
    staging_margin: float = 0.04
    # How many regions' best candidates are logged.
    top_candidates: int = 5
    # How narrow a choke is: exp(-width / width_scale).
    width_scale: float = 6.0
    # How far on our side of a passage the army stands to hold it.
    setback: float = 4.0
    remove_creep: RemoveCreepConfig = field(default_factory=RemoveCreepConfig)

    def __post_init__(self) -> None:
        if not 0.0 <= self.advance <= self.pressure_advance <= 1.0:
            raise ValueError("0 <= advance <= pressure_advance <= 1 must hold")
        for name in (
            "rally_forward",
            "choke_weight",
            "threat_weight",
            "control_weight",
            "setback",
            "staging_margin",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must not be negative")
        if self.width_scale <= 0.0:
            raise ValueError("width_scale must be positive")
        if self.top_candidates < 1:
            raise ValueError("top_candidates must be at least 1")


@dataclass(frozen=True, slots=True)
class MapControlPlan:
    # Where the free army holds, and where the offense assembles.
    anchor: Point2
    # threatened_base, staging or legacy.
    source: str
    # The posture read, and how far forward it let staging stand.
    posture: StrategicPosture
    advance: float
    reason: str
    # Why staging placed no anchor -- no_candidates or no_enemy_route; None
    # otherwise, and while a threatened base is held.
    fallback: str | None
    # The staging choice this frame, whether it places the anchor or not;
    # None without candidates.
    staging: StagingPlan | None
    proposals: tuple[Proposal, ...]
    unit_requests: tuple[UnitRequest, ...] = ()

    @property
    def held_passage(self) -> str | None:
        """The passage the anchor holds, if it holds one."""

        if self.source == STAGING and self.staging is not None:
            return self.staging.selected.passage_id
        return None

    @property
    def region(self) -> str | None:
        """The region the anchor stands in, when staging placed it."""

        if self.source == STAGING and self.staging is not None:
            return self.staging.selected.region_id
        return None


class MapControlPlanner:
    def __init__(self, config: MapControlConfig | None = None) -> None:
        self.config = config or MapControlConfig()
        self._staging = StagingPolicy(self.config)
        self._mission: RemoveCreepMission | None = None
        self._views: tuple[MissionView, ...] = ()
        self._opened = 0

    @property
    def mission(self) -> RemoveCreepMission | None:
        return self._mission

    def views(self) -> tuple[MissionView, ...]:
        return self._views

    def plan(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        feedback: EngineResult | None = None,
    ) -> MapControlPlan:
        posture = intent.posture
        advance = self.advance(posture)
        staging, fallback = self._staging.plan(attention, awareness.influence, advance)
        threatened = awareness.most_threatened
        if posture is StrategicPosture.DEFEND and threatened is not None:
            source, anchor, fallback = THREATENED_BASE, threatened.position, None
        elif staging is not None:
            source, anchor = STAGING, staging.selected.position
        else:
            source, anchor = LEGACY, self._legacy(attention)
        held = STAGING if source == STAGING else "rally"
        reason = f"hold_{held}_{posture.value.lower()}"
        inputs: tuple[tuple[str, float], ...] = (
            ("risk", intent.risk),
            ("danger", awareness.danger),
            ("advance", advance),
        )
        if source == STAGING and staging is not None:
            point = staging.selected
            inputs += (
                ("reaction", point.reaction),
                ("choke", point.choke),
                ("exposure", point.exposure),
                ("score", point.score),
            )
        self._views = ()
        if attention.enemy_race is Race.Zerg and self._mission is None:
            self._opened += 1
            self._mission = RemoveCreepMission(
                f"remove_creep:{self._opened}", attention.time, self.config.remove_creep
            )
        mission_proposals: tuple[Proposal, ...] = ()
        unit_requests: tuple[UnitRequest, ...] = ()
        if self._mission is not None:
            mission = self._mission
            if attention.enemy_race is not Race.Zerg:
                mission.lifecycle.request_cancel(CancelMode.IMMEDIATE, "not_zerg", attention.time)
            mission_proposals = mission.step(
                attention,
                awareness,
                intent,
                anchor,
                MissionFeedback.of(feedback, mission.mission_id),
            )
            unit_requests = mission.unit_requests
            self._views = (mission.view(),)
            if not mission.lifecycle.active:
                self._mission = None
        return MapControlPlan(
            anchor=anchor,
            source=source,
            posture=posture,
            advance=advance,
            reason=reason,
            fallback=fallback,
            staging=staging,
            unit_requests=unit_requests,
            proposals=(
                Proposal(
                    proposal_id=OWNER,
                    owner=OWNER,
                    priority=MAP_CONTROL_PRIORITY,
                    command=Command.HOLD,
                    target=anchor,
                    reason=reason,
                    inputs=inputs,
                ),
            )
            + mission_proposals,
        )

    def advance(self, posture: StrategicPosture) -> float:
        """How much standing in front of a base shortens the response to it."""

        if posture.offensive:
            return self.config.pressure_advance
        if posture is StrategicPosture.DEVELOP:
            return self.config.advance
        return 0.0

    def _legacy(self, attention: AttentionState) -> Point2:
        map_view = attention.map
        front = max(
            attention.bases,
            key=lambda base: (base.position.distance_to(map_view.own_start), base.base_id),
            default=None,
        )
        if front is None or front.is_main:
            return map_view.main_ramp
        if front.position.distance_to(map_view.enemy_start) <= self.config.rally_forward:
            return front.position
        return front.position.towards(map_view.enemy_start, self.config.rally_forward)
