"""EXECUTE: fly the raid this frame.

This is the tactical loop. It runs every frame off what the squad can see
right now, independently of the planner's much slower strategic cadence, and
it commands only the Banshees the mission actually owns.

    ASSEMBLE -> APPROACH -> INFILTRATE -> STRIKE -> EVADE -> REPOSITION

Movement, pathing and ability casting all go through the `MissionCommands`
port, which the Ares adapter implements -- no Ares or SC2 API access here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sc2.ids.ability_id import AbilityId
from sc2.position import Point2

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)
from bot.engine.missions.models import Mission
from bot.ports.logging import BotLogger
from bot.world.attention import UnitSnapshot
from bot.world.awareness.bases import BaseSecurityLevel

from .model import BansheeHarassConfig, BansheeHarassState, BansheePhase

COMPONENT = "behavior.harass.banshee"


@dataclass(slots=True)
class BansheeHarassExecutor(MissionExecutor):
    """Persistent approach/strike/evade/recover loop for the Banshee squad."""

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    config: BansheeHarassConfig = field(default_factory=BansheeHarassConfig)
    logger: BotLogger | None = None
    state: BansheeHarassState = field(default_factory=BansheeHarassState)
    _log: BehaviorLog = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    # Kept as attributes so existing tuning by keyword still reads naturally.
    @property
    def disengage_radius(self) -> float:
        return self.config.disengage_radius

    @property
    def arrival_radius(self) -> float:
        return self.config.arrival_radius

    @property
    def retreat_health(self) -> float:
        return self.config.retreat_health

    @property
    def phase(self) -> BansheePhase:
        return self.state.phase

    def refresh(self, mission: Mission) -> None:
        self.target_key = mission.proposal.target_key
        self.target = mission.proposal.target

    def preemption_cost(self) -> float:
        """Banshees already inside the worker line are expensive to recall.

        Flying out or regrouping, they cost nothing extra -- take them. The
        striking cost is deliberately small enough that a threatened base
        (DEFENSE, priority 85) still wins them; it only stops a same-tier
        mission from pulling the raid apart at its most valuable moment.
        """

        if self.state.phase in {BansheePhase.INFILTRATE, BansheePhase.STRIKE}:
            return self.config.strike_preemption_cost
        return 0.0

    async def step(self, context: MissionContext) -> MissionResult:
        harassers = context.assigned_units
        if not harassers:
            self._enter(BansheePhase.ASSEMBLE, "no_banshees_assigned_yet", context)
            return MissionResult(MissionOutcome.ACTIVE, "waiting_for_banshee_squad")

        defenders = self._anti_air_near_target(context)
        weakest_health = min(unit.health_percentage for unit in harassers)
        if defenders or weakest_health <= self.retreat_health:
            self.state.retreating = True

        if self.state.retreating:
            return self._evade(context, harassers, defenders=defenders)

        return self._strike(context, harassers)

    # --- approach / strike ------------------------------------------------

    def _strike(
        self, context: MissionContext, harassers: tuple[UnitSnapshot, ...]
    ) -> MissionResult:
        """Cloak and press the target.

        APPROACH, INFILTRATE and STRIKE issue the same pair of commands on
        purpose: closing the last tiles onto a worker line changes what is at
        stake (see `preemption_cost`), not what the squad should be told to
        do.
        """

        distance = self._centroid(harassers).distance_to(self.target)
        if distance > self.config.infiltration_radius:
            phase = BansheePhase.APPROACH
        elif distance > self.arrival_radius:
            phase = BansheePhase.INFILTRATE
        else:
            phase = BansheePhase.STRIKE
        self._enter(phase, "closing_on_target", context)

        for harasser in harassers:
            context.commands.use_ability(
                mission_id=self.mission_id,
                unit_tag=harasser.tag,
                ability=AbilityId.BEHAVIOR_CLOAKON_BANSHEE,
            )
            context.commands.attack_move(
                mission_id=self.mission_id,
                unit_tag=harasser.tag,
                target=self.target,
                success_at_distance=self.arrival_radius,
            )
        return MissionResult(
            MissionOutcome.ACTIVE, "harassing_enemy_worker_line_cloaked"
        )

    # --- evade / reposition ----------------------------------------------

    def _evade(
        self,
        context: MissionContext,
        harassers: tuple[UnitSnapshot, ...],
        *,
        defenders: tuple[UnitSnapshot, ...],
    ) -> MissionResult:
        """Break off to the nearest safe base, then come back.

        Banshees are mechanical and have no passive regen, and this bot has
        no repair behavior -- gating recovery on health rising back above
        `retreat_health` would leave the squad stuck at home forever after a
        single point of damage. Recovery only needs the threat gone and the
        squad clear of it.
        """

        home = self._home_anchor(context, self._centroid(harassers))
        self.state.home = home
        recovered = not defenders and all(
            unit.position.distance_to(home) <= self.arrival_radius
            for unit in harassers
        )
        if not recovered:
            self._enter(
                BansheePhase.EVADE if defenders else BansheePhase.REPOSITION,
                "anti_air_near_target" if defenders else "regrouping_at_safe_base",
                context,
            )
            for harasser in harassers:
                context.commands.safe_path_to(
                    mission_id=self.mission_id,
                    unit_tag=harasser.tag,
                    target=home,
                    success_at_distance=self.arrival_radius,
                )
            return MissionResult(
                MissionOutcome.ACTIVE, "banshee_squad_retreating_or_recovering"
            )

        self.state.retreating = False
        return self._strike(context, harassers)

    # --- helpers ----------------------------------------------------------

    def _anti_air_near_target(
        self, context: MissionContext
    ) -> tuple[UnitSnapshot, ...]:
        return tuple(
            unit
            for unit in context.attention.world.enemy_units
            if unit.is_visible_combat_threat(against_ground=False)
            and unit.position.distance_to(self.target) <= self.disengage_radius
        )

    def _enter(
        self, phase: BansheePhase, reason: str, context: MissionContext
    ) -> None:
        if self.state.enter(phase):
            self._log.state_changed(
                now=context.attention.world.time,
                state=phase.name,
                reason=reason,
                mission_id=self.mission_id,
                target=self.target_key,
            )

    @staticmethod
    def _centroid(units: tuple[UnitSnapshot, ...]) -> Point2:
        x = sum(unit.position.x for unit in units) / len(units)
        y = sum(unit.position.y for unit in units) / len(units)
        return Point2((x, y))

    @staticmethod
    def _home_anchor(context: MissionContext, position: Point2) -> Point2:
        safe = tuple(
            base
            for base in context.awareness.bases
            if base.security is BaseSecurityLevel.SAFE
        )
        if not safe:
            return context.attention.world.map.own_start
        return min(safe, key=lambda base: base.position.distance_to(position)).position
