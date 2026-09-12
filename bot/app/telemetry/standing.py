from __future__ import annotations

from bot.behavior.standing import StandingPlanner
from bot.domain import is_combat_unit
from bot.engine.missions import MissionController
from bot.ports.logging import BotLogger
from bot.world.attention import AttentionSnapshot

from .gate import ChangeGate


class StandingTelemetry:
    """Surfaces standing-army ownership so "why is this unit here?" and "how
    many units have no mission?" are answerable from the logs.

    Grouped by ``deduplication_key``/``kind`` straight off the live
    ``Mission`` objects (not ``MissionSnapshot``, which drops
    ``requirement.desired``) -- this is diagnostics, not a second source of
    truth: ownership itself still lives only in ``UnitAllocator``.
    """

    # How long an eligible combat unit may sit without any mission owning it
    # before it is worth a distinct log line -- the standing behavior is the
    # default owner, so this should not normally happen at all.
    _UNASSIGNED_WARNING_AFTER = 15.0

    def __init__(
        self,
        *,
        logger: BotLogger,
        missions: MissionController,
        standing_planner: StandingPlanner,
    ) -> None:
        self._logger = logger
        self._missions = missions
        self._standing_planner = standing_planner
        self._gate = ChangeGate(heartbeat=10.0)
        self._unassigned_eligible_since: float | None = None

    def report(self, attention: AttentionSnapshot) -> None:
        world = attention.world
        standing: dict[str, tuple[int, int]] = {}
        allocation_by_kind: dict[str, int] = {}
        for mission in self._missions.board.live():
            kind_name = mission.proposal.kind.name
            allocation_by_kind[kind_name] = allocation_by_kind.get(
                kind_name, 0
            ) + len(mission.assigned_unit_tags)
            if mission.proposal.squad_id is not None:
                slot = mission.proposal.squad_id
                standing[slot] = (
                    mission.proposal.requirement.desired,
                    len(mission.assigned_unit_tags),
                )

        unassigned_tags = tuple(
            unit.tag
            for unit in world.own_units
            if is_combat_unit(unit.unit_type)
            and unit.available_for_mission
            and self._missions.allocator.owner_of(unit.tag) is None
        )

        if unassigned_tags:
            if self._unassigned_eligible_since is None:
                self._unassigned_eligible_since = world.time
        else:
            self._unassigned_eligible_since = None
        unassigned_duration = (
            0.0
            if self._unassigned_eligible_since is None
            else world.time - self._unassigned_eligible_since
        )

        signature = (
            self._standing_planner.last_posture.name,
            tuple(sorted(standing.items())),
            tuple(sorted(allocation_by_kind.items())),
            len(unassigned_tags),
        )
        if not self._gate.admit(signature, now=world.time):
            return

        self._logger.event(
            "standing.updated",
            component="behavior.standing",
            game_time=world.time,
            data={
                "combat_posture": self._standing_planner.last_posture.name,
                "standing": {
                    slot: {"desired": desired, "assigned": assigned}
                    for slot, (desired, assigned) in sorted(standing.items())
                },
                "mission_allocation": allocation_by_kind,
                "squads": [
                    {
                        "squad_id": squad.squad_id,
                        "role": squad.role.name,
                        "members": list(squad.member_tags),
                        "current_mission_id": squad.current_mission_id,
                        "home_mission_id": squad.home_mission_id,
                    }
                    for squad in self._missions.squads.snapshots()
                ],
                "unassigned_eligible_units": len(unassigned_tags),
            },
        )

        if unassigned_tags and unassigned_duration >= self._UNASSIGNED_WARNING_AFTER:
            self._logger.event(
                "standing.unassigned_units_persisting",
                component="behavior.standing",
                game_time=world.time,
                data={
                    "unassigned_eligible_units": len(unassigned_tags),
                    "unassigned_unit_tags": list(unassigned_tags),
                    "duration_seconds": round(unassigned_duration, 1),
                },
            )
