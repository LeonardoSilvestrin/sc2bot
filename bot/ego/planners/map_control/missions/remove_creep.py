"""A Raven and a small escort peel safe creep fronts, yielding to combat."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bot.attention import AttentionState
from bot.awareness import AwarenessState, RegionControl
from bot.awareness.regions import TUMORS
from bot.ego.economy.contracts import UnitRequest
from bot.ego.planners import (
    CancelMode,
    Command,
    Lifecycle,
    MissionFeedback,
    MissionStatus,
    MissionView,
    Proposal,
)
from bot.ego.strategy import StrategicIntent, StrategicPosture

OWNER = "map_control"
KIND = "remove_creep"


class CreepPhase(str, Enum):
    ASSEMBLE = "ASSEMBLE"
    CLEAR = "CLEAR"
    RETREAT = "RETREAT"
    WAIT = "WAIT"


@dataclass(frozen=True, slots=True)
class RemoveCreepConfig:
    marines: int = 4
    hellions: int = 2
    minimum_escort: int = 2
    cohesion: float = 8.0
    danger_distance: float = 15.0
    maximum_threat: float = 0.25
    retreat_for: float = 8.0
    revisit_after: float = 30.0
    # Combat operations can take the escort; the detector stays with its mission.
    escort_priority: float = -0.5
    raven_priority: float = 0.05

    def __post_init__(self) -> None:
        if self.minimum_escort < 1 or min(self.marines, self.hellions) < self.minimum_escort:
            raise ValueError("escort sizes must meet the positive minimum")
        if min(self.cohesion, self.danger_distance, self.retreat_for, self.revisit_after) <= 0.0:
            raise ValueError("distances and retreat time must be positive")
        if not 0.0 <= self.maximum_threat <= 1.0:
            raise ValueError("maximum_threat must be between zero and one")


class RemoveCreepMission:
    def __init__(self, mission_id: str, now: float, config: RemoveCreepConfig) -> None:
        self.lifecycle = Lifecycle(mission_id)
        self.config = config
        self.phase = CreepPhase.ASSEMBLE
        self.since = now
        self.reason = "need_detector"
        self.region: str | None = None
        self.target: Point2 | None = None
        self._retreat_until = 0.0
        self._escort = UnitTypeId.MARINE
        self._proposals: tuple[Proposal, ...] = ()
        self._feedback = MissionFeedback()
        self._searched: dict[Point2, float] = {}

    @property
    def mission_id(self) -> str:
        return self.lifecycle.mission_id

    @property
    def unit_requests(self) -> tuple[UnitRequest, ...]:
        if not self.lifecycle.active:
            return ()
        return (UnitRequest(UnitTypeId.RAVEN, 1, self.mission_id, "creep_detection"),)

    def step(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
        anchor: Point2,
        feedback: MissionFeedback,
    ) -> tuple[Proposal, ...]:
        self._feedback = feedback
        self._proposals = ()
        if not self.lifecycle.active:
            return ()
        now, config = attention.time, self.config
        squad = [u for u in attention.own_units if u.tag in feedback.tags]
        if self.lifecycle.cancel is not None:
            request = self.lifecycle.cancel
            if (
                request.mode is CancelMode.IMMEDIATE
                or now - request.time >= config.retreat_for
                or (all(u.position.distance_to(anchor) <= config.cohesion for u in squad))
            ):
                self.lifecycle.end(MissionStatus.CANCELLED)
                self._set(CreepPhase.RETREAT, request.reason, now)
                return ()
            self._set(CreepPhase.RETREAT, request.reason, now)
            self.target = anchor
        else:
            # Choose one escort family, keeping it while the last grant exists.
            if not any(u.type_id == self._escort for u in squad):
                self._escort = (
                    UnitTypeId.HELLION
                    if sum(u.type_id is UnitTypeId.HELLION for u in attention.own_units)
                    >= config.minimum_escort
                    else UnitTypeId.MARINE
                )
            dangerous = any(
                contact.power > 0.0
                and contact.confidence >= 0.2
                and any(
                    u.position.distance_to(contact.position)
                    <= config.danger_distance + contact.uncertainty
                    for u in squad
                )
                for contact in awareness.contacts
            )
            if dangerous or intent.posture in (StrategicPosture.DEFEND, StrategicPosture.RECOVER):
                self._retreat_until = now + config.retreat_for
                self._set(
                    CreepPhase.RETREAT, "avoid_combat" if dangerous else "home_needs_army", now
                )
                self.target = anchor
            elif now < self._retreat_until:
                self._set(CreepPhase.RETREAT, "danger_cooldown", now)
                self.target = anchor
            else:
                if (
                    self.phase is CreepPhase.CLEAR
                    and self.target is not None
                    and self._ready(squad)
                ):
                    reached = any(
                        u.type_id is UnitTypeId.RAVEN
                        and u.position.distance_to(self.target) <= config.cohesion
                        for u in squad
                    )
                    tumors = any(
                        u.type_id in TUMORS and u.position.distance_to(self.target) <= 10.0
                        for u in attention.enemy_structures
                    )
                    if reached and not tumors:
                        for region in awareness.regions:
                            for point in region.creep_points:
                                if point.distance_to(self.target) <= config.cohesion:
                                    self._searched[point] = now
                choices = self._targets(attention, awareness, anchor, now)
                if not choices:
                    self.region, self.target = None, anchor
                    self._set(CreepPhase.WAIT, "no_safe_creep", now)
                elif not self._ready(squad):
                    self._set(CreepPhase.ASSEMBLE, "need_detector_and_escort", now)
                    self.target = anchor
                else:
                    # Keep a safe region while searching its remaining creep.
                    region, point = next(
                        ((r, p) for r, p in choices if r.region_id == self.region), choices[0]
                    )
                    self.region, self.target = region.region_id, point
                    self._set(CreepPhase.CLEAR, "safe_creep_front", now)
        command = Command.REMOVE_CREEP
        target = self.target or anchor
        has_raven = any(u.type_id is UnitTypeId.RAVEN for u in attention.own_units)
        parts = [("raven", UnitTypeId.RAVEN, 1, config.raven_priority)] if has_raven else []
        if has_raven and self.phase is not CreepPhase.WAIT:
            parts.append(
                (
                    "escort",
                    self._escort,
                    config.hellions if self._escort is UnitTypeId.HELLION else config.marines,
                    config.escort_priority,
                )
            )
            if self._escort is UnitTypeId.MARINE:
                parts.append(("medivac", UnitTypeId.MEDIVAC, 1, config.escort_priority))
        self._proposals = tuple(
            Proposal(
                f"{self.mission_id}:{part}",
                OWNER,
                priority,
                command,
                target,
                self.reason,
                count=count,
                unit_types=frozenset({kind}),
                mission_id=self.mission_id,
                fallback=anchor,
                inputs=(
                    ("danger_distance", config.danger_distance),
                    ("cohesion", config.cohesion),
                    ("minimum_escort", float(config.minimum_escort)),
                    ("clear", float(self.phase is CreepPhase.CLEAR)),
                ),
            )
            for part, kind, count, priority in parts
        )
        return self._proposals

    def _targets(
        self, attention: AttentionState, awareness: AwarenessState, anchor: Point2, now: float
    ) -> list[tuple[RegionControl, Point2]]:
        config = self.config
        ranked = {r.region_id: r for r in awareness.regions}
        choices = []
        for region in awareness.regions:
            if region.creep <= 0.0 or region.threat > config.maximum_threat:
                continue
            if region.region_id == attention.map.topology.enemy_start_region:
                continue
            route = attention.map.route_to(region.target, origin=anchor)
            if not route or any(
                name in ranked and ranked[name].threat > config.maximum_threat for name in route
            ):
                continue
            for point in region.creep_points or (region.target,):
                if now - self._searched.get(point, -config.revisit_after) < config.revisit_after:
                    continue
                index = awareness.influence.nearest(point)
                if index >= 0 and awareness.influence.threat[index] > config.maximum_threat:
                    continue
                choices.append((region, point))
                break
        return choices

    def _ready(self, squad) -> bool:
        config = self.config
        ravens = [u for u in squad if u.type_id is UnitTypeId.RAVEN]
        escorts = [u for u in squad if u.type_id == self._escort]
        if not ravens or len(escorts) < config.minimum_escort:
            return False
        if self._escort is UnitTypeId.MARINE and not any(
            u.type_id is UnitTypeId.MEDIVAC for u in squad
        ):
            return False
        return all(u.position.distance_to(ravens[0].position) <= config.cohesion for u in squad)

    def _set(self, phase: CreepPhase, reason: str, now: float) -> None:
        if (self.phase, self.reason) != (phase, reason):
            self.phase, self.reason, self.since = phase, reason, now

    def view(self) -> MissionView:
        return MissionView(
            self.mission_id,
            OWNER,
            KIND,
            self.lifecycle.status,
            self.phase.value,
            self.since,
            self.reason,
            self.lifecycle.cancel,
            tuple(p.proposal_id for p in self._proposals),
            len(self._feedback.tags),
            self._feedback.power,
        )
