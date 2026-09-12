from __future__ import annotations

from dataclasses import replace

from bot.engine.missions.allocator import UnitAllocator
from bot.engine.missions.models import Mission, MissionKind, UnitRequirement
from bot.ports.logging import BotLogger
from bot.world.attention import UnitSnapshot

from .models import Squad, SquadRole, SquadSnapshot

_ROLE_BY_ID: dict[str, SquadRole] = {
    "main_army": SquadRole.MAIN_ARMY,
    "map_control": SquadRole.MAP_CONTROL,
    "banshee_harass": SquadRole.BANSHEE_HARASS,
}


class SquadController:
    """Persistent squad registry layered over mission-owned unit leases.

    It records who belongs together and supplies stable allocation preferences.
    It neither issues game commands nor owns units: MissionController and
    UnitAllocator remain the only lifecycle/allocation authorities.
    """

    def __init__(self, *, logger: BotLogger) -> None:
        self.logger = logger
        self._squads: dict[str, Squad] = {}
        self._mission_squads: dict[str, str] = {}

    def snapshots(self) -> tuple[SquadSnapshot, ...]:
        return tuple(
            SquadSnapshot.from_squad(squad)
            for squad in sorted(self._squads.values(), key=lambda item: item.squad_id)
        )

    def get(self, squad_id: str) -> Squad | None:
        return self._squads.get(squad_id)

    def sync(self, units: tuple[UnitSnapshot, ...], *, now: float) -> None:
        alive = {unit.tag for unit in units}
        for squad in self._squads.values():
            lost = squad.member_tags - alive
            if not lost:
                continue
            before = tuple(sorted(squad.member_tags))
            squad.member_tags.intersection_update(alive)
            self._log_membership(squad, before, now, reason="members_lost")

    def register_home_mission(self, mission: Mission, *, now: float) -> None:
        squad_id = mission.proposal.squad_id
        if squad_id is None:
            return
        squad = self._squads.get(squad_id)
        if squad is None:
            squad = Squad(
                squad_id=squad_id,
                role=_ROLE_BY_ID.get(squad_id, SquadRole.MAIN_ARMY),
                home_mission_key=mission.proposal.deduplication_key,
            )
            self._squads[squad_id] = squad
            self._emit(
                "squad_created",
                squad,
                now,
                reason="home_mission_registered",
            )
        elif squad.home_mission_key != mission.proposal.deduplication_key:
            raise ValueError(
                f"squad {squad_id!r} already has home mission "
                f"{squad.home_mission_key!r}"
            )

        squad.home_mission_id = mission.mission_id
        self._mission_squads[mission.mission_id] = squad_id
        if squad.current_mission_id is None:
            squad.current_mission_id = mission.mission_id
            squad.current_mission_key = mission.proposal.deduplication_key
            self._log_mission(squad, now, reason="home_mission_active")

    def bind_compatible_squad(
        self,
        mission: Mission,
        *,
        units: tuple[UnitSnapshot, ...],
        now: float,
    ) -> None:
        """Bind a capability request to a compatible squad, if one exists.

        Defense remains expressed solely as a UnitRequirement. This method
        evaluates the registered squads and does not require DefensePlanner to
        know squad or unit IDs.
        """

        if mission.mission_id in self._mission_squads:
            return
        if mission.proposal.kind is not MissionKind.DEFENSE:
            return

        by_tag = {unit.tag: unit for unit in units}
        requirement = mission.proposal.requirement
        candidates: list[tuple[int, float, str, Squad]] = []
        for squad in self._squads.values():
            if squad.home_mission_id is None:
                continue
            if squad.current_mission_id not in {None, squad.home_mission_id}:
                continue
            matching = [
                by_tag[tag]
                for tag in sorted(squad.member_tags)
                if tag in by_tag
                and requirement.matches(by_tag[tag], check_availability=False)
            ]
            if len(matching) < requirement.minimum:
                continue
            distance = sum(
                unit.position.distance_to(mission.proposal.target)
                for unit in matching[: requirement.desired]
            )
            candidates.append(
                (
                    -min(len(matching), requirement.desired),
                    distance,
                    squad.squad_id,
                    squad,
                )
            )
        if not candidates:
            return

        squad = min(candidates)[3]
        self._mission_squads[mission.mission_id] = squad.squad_id
        previous = squad.current_mission_id or squad.home_mission_id
        squad.preempted_from_mission_id = previous
        squad.current_mission_id = mission.mission_id
        squad.current_mission_key = mission.proposal.deduplication_key
        self._emit(
            "squad_preempted",
            squad,
            now,
            reason="higher_priority_compatible_mission",
            from_mission_id=previous,
            to_mission_id=mission.mission_id,
        )
        self._log_mission(squad, now, reason="temporary_mission_active")

    def preferred_tags(self, mission_id: str) -> frozenset[int]:
        squad_id = self._mission_squads.get(mission_id)
        squad = self._squads.get(squad_id) if squad_id is not None else None
        return frozenset() if squad is None else frozenset(squad.member_tags)

    def effective_requirement(
        self, mission: Mission, allocator: UnitAllocator
    ) -> UnitRequirement | None:
        """Avoid backfilling a home squad while members are preempted.

        The members away shrink the request by their count and, for a
        supply-sized request, by their supply too.
        """

        squad_id = mission.proposal.squad_id
        squad = self._squads.get(squad_id) if squad_id is not None else None
        if squad is None or squad.home_mission_id != mission.mission_id:
            return mission.proposal.requirement
        temporarily_away = [
            tag
            for tag in squad.member_tags
            if (owner := allocator.owner_of(tag)) is not None
            and owner != mission.mission_id
            and self._mission_squads.get(owner) == squad.squad_id
        ]
        requirement = mission.proposal.requirement
        desired = max(0, requirement.desired - len(temporarily_away))
        budget = requirement.supply_budget
        if budget is not None:
            budget -= sum(allocator.unit_supply(tag) for tag in temporarily_away)
        if desired == 0 or (budget is not None and budget <= 0.0):
            return None
        return replace(
            requirement,
            desired=desired,
            minimum=min(requirement.minimum, desired),
            supply_budget=budget,
        )

    def allocation_changed(
        self,
        mission: Mission,
        *,
        assigned_tags: tuple[int, ...],
        allocator: UnitAllocator,
        now: float,
    ) -> None:
        squad_id = self._mission_squads.get(mission.mission_id)
        squad = self._squads.get(squad_id) if squad_id is not None else None
        if squad is None:
            return
        before = tuple(sorted(squad.member_tags))
        if mission.mission_id == squad.home_mission_id:
            temporary_members = {
                tag
                for tag in squad.member_tags
                if (owner := allocator.owner_of(tag)) is not None
                and owner != squad.home_mission_id
                and self._mission_squads.get(owner) == squad.squad_id
            }
            squad.member_tags = set(assigned_tags) | temporary_members
            # A tag assigned to a new home squad has changed permanent team.
            for other in self._squads.values():
                if other is squad:
                    continue
                other.member_tags.difference_update(assigned_tags)
        # Temporary missions preserve, rather than redefine, membership.
        if tuple(sorted(squad.member_tags)) != before:
            self._log_membership(squad, before, now, reason="allocation_changed")

    def mission_finished(self, mission: Mission, *, now: float) -> None:
        squad_id = self._mission_squads.pop(mission.mission_id, None)
        squad = self._squads.get(squad_id) if squad_id is not None else None
        if squad is None:
            return
        if mission.mission_id == squad.home_mission_id:
            squad.home_mission_id = None
            if squad.current_mission_id == mission.mission_id:
                squad.current_mission_id = None
                squad.current_mission_key = None
            return
        squad.current_mission_id = squad.home_mission_id
        squad.current_mission_key = squad.home_mission_key
        squad.preempted_from_mission_id = None
        self._emit(
            "squad_returned_home",
            squad,
            now,
            reason="temporary_mission_finished",
            finished_mission_id=mission.mission_id,
            home_mission_id=squad.home_mission_id,
        )
        self._log_mission(squad, now, reason="home_mission_restored")

    def _log_membership(
        self, squad: Squad, before: tuple[int, ...], now: float, *, reason: str
    ) -> None:
        self._emit(
            "squad_membership_changed",
            squad,
            now,
            reason=reason,
            previous_member_tags=list(before),
            member_tags=sorted(squad.member_tags),
        )

    def _log_mission(self, squad: Squad, now: float, *, reason: str) -> None:
        self._emit(
            "squad_mission_changed",
            squad,
            now,
            reason=reason,
            current_mission_id=squad.current_mission_id,
            current_mission_key=squad.current_mission_key,
            home_mission_id=squad.home_mission_id,
            home_mission_key=squad.home_mission_key,
        )

    def _emit(
        self, event: str, squad: Squad, now: float, *, reason: str, **data
    ) -> None:
        self.logger.event(
            event,
            component="engine.squads.controller",
            game_time=now,
            data={
                "reason": reason,
                "squad_id": squad.squad_id,
                "squad_role": squad.role.name,
                **data,
            },
        )
