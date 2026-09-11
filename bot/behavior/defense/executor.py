"""EXECUTE: defend the base, each defender in its own role.

A unit does not only belong to a defense mission -- its type decides what it
does inside it (see `DefenseRole`):

    SIEGE_ANCHOR  Tanks move to a siege anchor behind the fight, siege there
                  and hold. They are never attack-moved at the enemy.
    SCREEN        every other defender intercepts the nearest threat.

Roles are resolved here, from the units the mission was handed. Neither the
proposal, the allocator nor the controller carries one: this is a pilot of
the idea inside one behavior, not an engine contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.behavior.contracts import BehaviorLog
from bot.engine.missions.execution import (
    MissionContext,
    MissionExecutor,
    MissionOutcome,
    MissionResult,
)
from bot.ports.logging import BotLogger
from bot.world.attention import UnitSnapshot

from .model import DefenseAnchors, DefenseConfig, DefenseRole, SiegePhase

COMPONENT = "behavior.defense"


@dataclass(slots=True)
class DefendBaseExecutor(MissionExecutor):
    """Defends until no threat remains near where the mission was admitted.

    Once it is clear, Tanks are unsieged before the mission completes:
    `MissionController` releases every unit the moment this reports
    COMPLETED, and a Tank left sieged would stay sieged under its next owner.
    """

    mission_id: str
    target_key: str
    target: Point2
    started_at: float
    config: DefenseConfig = field(default_factory=DefenseConfig)
    logger: BotLogger | None = None
    _log: BehaviorLog = field(init=False, repr=False)
    _roles: dict[int, DefenseRole] = field(
        default_factory=dict, init=False, repr=False
    )
    _siege_phases: dict[int, SiegePhase] = field(
        default_factory=dict, init=False, repr=False
    )
    _releasing_since: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._log = BehaviorLog(component=COMPONENT, logger=self.logger)

    @property
    def engagement_radius(self) -> float:
        return self.config.engagement_radius

    @property
    def arrival_radius(self) -> float:
        return self.config.arrival_radius

    async def step(self, context: MissionContext) -> MissionResult:
        now = context.attention.world.time
        self._resolve_roles(context.assigned_units, now)
        threats = tuple(
            unit
            for unit in context.attention.world.enemy_units
            if unit.is_visible_combat_threat()
            and unit.position.distance_to(self.target) <= self.engagement_radius
        )
        if not threats:
            return self._release(context, now)

        if not context.assigned_units:
            return MissionResult(MissionOutcome.FAILED, "assigned_unit_missing")

        # A threat is back: whatever unsieging had started is called off.
        self._releasing_since = None
        anchors = self._anchors(context, threats)
        nearest = min(threats, key=lambda unit: unit.position.distance_to(self.target))
        for unit in context.assigned_units:
            if self._roles[unit.tag] is DefenseRole.SIEGE_ANCHOR:
                self._hold_siege_anchor(context, unit, anchors, now)
            else:
                self._screen(context, unit, nearest.position)
        return MissionResult(MissionOutcome.ACTIVE, "engaging_enemy_near_own_base")

    # --- roles --------------------------------------------------------------

    def _resolve_roles(self, units: tuple[UnitSnapshot, ...], now: float) -> None:
        """Interpret each newly assigned unit's role; forget departed units."""

        present = {unit.tag for unit in units}
        for tag in [tag for tag in self._roles if tag not in present]:
            del self._roles[tag]
            self._siege_phases.pop(tag, None)

        resolved: dict[DefenseRole, list[UnitSnapshot]] = {}
        for unit in units:
            if unit.tag not in self._roles:
                role = DefenseRole.for_unit_type(unit.unit_type)
                self._roles[unit.tag] = role
                resolved.setdefault(role, []).append(unit)
        for role, members in resolved.items():
            self._log.state_changed(
                now=now,
                state=role.name,
                reason="role_resolved_from_unit_type",
                mission_id=self.mission_id,
                target=self.target_key,
                unit_tags=[unit.tag for unit in members],
                unit_types=[unit.unit_type.name for unit in members],
            )

    # --- SCREEN -------------------------------------------------------------

    def _screen(
        self, context: MissionContext, unit: UnitSnapshot, threat: Point2
    ) -> None:
        """Intercept the nearest threat -- what every defender used to do."""

        context.commands.attack_move(
            mission_id=self.mission_id,
            unit_tag=unit.tag,
            target=threat,
            success_at_distance=self.arrival_radius,
        )

    # --- SIEGE_ANCHOR -------------------------------------------------------

    def _hold_siege_anchor(
        self,
        context: MissionContext,
        tank: UnitSnapshot,
        anchors: DefenseAnchors,
        now: float,
    ) -> None:
        """Move to the siege anchor, siege on it, and stay there.

        A sieged Tank fires at whatever enters its range by itself, so it is
        never told to attack. Once it has committed to sieging, only a
        significant anchor move (`siege_reposition_distance`) pulls it off.
        """

        distance = tank.position.distance_to(anchors.siege)
        sieged = tank.unit_type == UnitTypeId.SIEGETANKSIEGED
        committed = sieged or self._siege_phases.get(tank.tag) is SiegePhase.SIEGING
        leash = (
            self.config.siege_reposition_distance
            if committed
            else self.config.siege_arrival_radius
        )
        detail = {**anchors.log_fields(), "distance_to_anchor": round(distance, 1)}

        if distance <= leash:
            if sieged:
                self._enter_siege_phase(
                    tank, SiegePhase.SIEGED, "siege_mode_confirmed", now, **detail
                )
                return
            self._enter_siege_phase(
                tank, SiegePhase.SIEGING, "tank_reached_siege_anchor", now, **detail
            )
            self._use_ability(context, tank, AbilityId.SIEGEMODE_SIEGEMODE)
            return

        if sieged:
            self._enter_siege_phase(
                tank, SiegePhase.REPOSITIONING, "siege_anchor_moved", now, **detail
            )
            self._use_ability(context, tank, AbilityId.UNSIEGE_UNSIEGE)
            return

        self._enter_siege_phase(
            tank,
            SiegePhase.MOVING_TO_ANCHOR,
            "tank_away_from_siege_anchor",
            now,
            **detail,
        )
        context.commands.attack_move(
            mission_id=self.mission_id,
            unit_tag=tank.tag,
            target=anchors.siege,
            success_at_distance=self.config.siege_arrival_radius,
        )

    def _anchors(
        self, context: MissionContext, threats: tuple[UnitSnapshot, ...]
    ) -> DefenseAnchors:
        """Anchors facing the ground attack on the defended base.

        Faces the ground threats' centroid when there are any -- a Tank has
        nothing to answer the air with -- and every threat otherwise. Falls
        back to the main if the defended base is no longer held.
        """

        base = context.awareness.bases.get(self.target_key)
        origin = (
            base.position
            if base is not None
            else context.attention.world.map.own_start
        )
        ground = tuple(unit for unit in threats if not unit.is_flying)
        return DefenseAnchors.toward(origin, _centroid(ground or threats), self.config)

    # --- release ------------------------------------------------------------

    def _release(self, context: MissionContext, now: float) -> MissionResult:
        """The threat is gone: pack the Tanks up before giving units back.

        Bounded by `unsiege_timeout`, so a Tank that cannot unsiege never
        holds the mission open.
        """

        pending = tuple(
            unit
            for unit in context.assigned_units
            if unit.unit_type == UnitTypeId.SIEGETANKSIEGED
            # Ordered to siege but not reported sieged yet: wait for it to
            # land instead of releasing a Tank that is about to set up.
            or self._siege_phases.get(unit.tag) is SiegePhase.SIEGING
        )
        if not pending:
            return MissionResult(
                MissionOutcome.COMPLETED, "threat_cleared_near_own_base"
            )

        if self._releasing_since is None:
            self._releasing_since = now
        if now - self._releasing_since >= self.config.unsiege_timeout:
            return MissionResult(
                MissionOutcome.COMPLETED, "threat_cleared_unsiege_timed_out"
            )

        for tank in pending:
            if tank.unit_type == UnitTypeId.SIEGETANKSIEGED:
                self._enter_siege_phase(
                    tank,
                    SiegePhase.UNSIEGING,
                    "threat_cleared_unsieging_before_release",
                    now,
                )
                self._use_ability(context, tank, AbilityId.UNSIEGE_UNSIEGE)
        return MissionResult(MissionOutcome.ACTIVE, "unsieging_tanks_before_release")

    # --- helpers ------------------------------------------------------------

    def _enter_siege_phase(
        self,
        tank: UnitSnapshot,
        phase: SiegePhase,
        reason: str,
        now: float,
        **detail: Any,
    ) -> None:
        previous = self._siege_phases.get(tank.tag)
        if previous is phase:
            return
        self._siege_phases[tank.tag] = phase
        self._log.state_changed(
            now=now,
            state=phase.name,
            reason=reason,
            mission_id=self.mission_id,
            target=self.target_key,
            role=DefenseRole.SIEGE_ANCHOR.name,
            unit_tag=tank.tag,
            unit_type=tank.unit_type.name,
            previous_state=None if previous is None else previous.name,
            position=_xy(tank.position),
            **detail,
        )

    def _use_ability(
        self, context: MissionContext, tank: UnitSnapshot, ability: AbilityId
    ) -> None:
        # Safe to repeat every frame: the adapter's Ares `UseAbility` no-ops
        # while the ability is unavailable (mid-morph, or already done).
        context.commands.use_ability(
            mission_id=self.mission_id, unit_tag=tank.tag, ability=ability
        )


def _centroid(units: tuple[UnitSnapshot, ...]) -> Point2:
    x = sum(unit.position.x for unit in units) / len(units)
    y = sum(unit.position.y for unit in units) / len(units)
    return Point2((x, y))


def _xy(point: Point2) -> list[float]:
    return [round(float(point.x), 1), round(float(point.y), 1)]
