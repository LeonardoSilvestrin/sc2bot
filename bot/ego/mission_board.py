from __future__ import annotations

from bot.ego.models import Mission, MissionSnapshot


class MissionBoard:
    """Single catalog for live and finished mission commitments."""

    def __init__(self) -> None:
        self._missions: dict[str, Mission] = {}

    def add(self, mission: Mission) -> None:
        if mission.mission_id in self._missions:
            raise ValueError(f"duplicate mission_id: {mission.mission_id}")
        self._missions[mission.mission_id] = mission

    def get(self, mission_id: str) -> Mission | None:
        return self._missions.get(mission_id)

    def live(self) -> tuple[Mission, ...]:
        return tuple(
            mission
            for mission in self._missions.values()
            if not mission.status.terminal
        )

    def live_for_key(self, deduplication_key: str) -> Mission | None:
        return next(
            (
                mission
                for mission in self.live()
                if mission.proposal.deduplication_key == deduplication_key
            ),
            None,
        )

    def snapshots(self) -> tuple[MissionSnapshot, ...]:
        return tuple(
            MissionSnapshot.from_mission(mission)
            for mission in sorted(
                self._missions.values(),
                key=lambda item: (item.admitted_at, item.mission_id),
            )
        )
