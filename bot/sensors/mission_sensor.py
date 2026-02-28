from __future__ import annotations

from typing import Any

from bot.mind.attention import MissionSnapshot, MissionStatusSnapshot
from bot.mind.awareness import Awareness, K


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _to_int_tags(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for t in value:
        try:
            out.append(int(t))
        except Exception:
            continue
    return out


def _to_str_int_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            continue
        try:
            out[str(k)] = int(v)
        except Exception:
            continue
    return out


def derive_mission_snapshot(bot, *, awareness: Awareness, now: float) -> MissionSnapshot:
    ongoing: list[MissionStatusSnapshot] = []
    ongoing_units_alive = 0
    ongoing_units_missing = 0
    needing_support_count = 0

    for key in awareness.mem.keys():
        if len(key) != 4:
            continue
        if key[0] != "ops" or key[1] != "mission" or key[3] != "status":
            continue

        mission_id = str(key[2])
        status = str(awareness.mem.get(K("ops", "mission", mission_id, "status"), now=now, default=""))
        if status != "RUNNING":
            continue

        proposal_id = str(awareness.mem.get(K("ops", "mission", mission_id, "proposal_id"), now=now, default=""))
        domain = str(awareness.mem.get(K("ops", "mission", mission_id, "domain"), now=now, default=""))
        started_at = _to_float_or_none(awareness.mem.get(K("ops", "mission", mission_id, "started_at"), now=now, default=None))
        expires_at = _to_float_or_none(awareness.mem.get(K("ops", "mission", mission_id, "expires_at"), now=now, default=None))
        remaining_s = None if expires_at is None else max(0.0, float(expires_at) - float(now))

        assigned_tags = _to_int_tags(awareness.mem.get(K("ops", "mission", mission_id, "assigned_tags"), now=now, default=[]))
        original_tags = _to_int_tags(
            awareness.mem.get(K("ops", "mission", mission_id, "original_assigned_tags"), now=now, default=assigned_tags)
        )
        original_type_counts = _to_str_int_dict(
            awareness.mem.get(K("ops", "mission", mission_id, "original_type_counts"), now=now, default={})
        )

        alive_tags: list[int] = []
        missing_tags: list[int] = []
        for tag in assigned_tags:
            unit = bot.units.find_by_tag(int(tag))
            if unit is None:
                missing_tags.append(int(tag))
            else:
                alive_tags.append(int(tag))

        original_alive_tags: list[int] = []
        original_missing_tags: list[int] = []
        for tag in original_tags:
            unit = bot.units.find_by_tag(int(tag))
            if unit is None:
                original_missing_tags.append(int(tag))
            else:
                original_alive_tags.append(int(tag))

        assigned_count = len(assigned_tags)
        alive_count = len(alive_tags)
        missing_count = len(missing_tags)
        original_count = len(original_tags)
        original_alive_count = len(original_alive_tags)
        original_missing_count = len(original_missing_tags)
        original_alive_ratio = 1.0 if original_count <= 0 else (float(original_alive_count) / float(original_count))
        mission_degraded = bool(original_count >= 2 and original_alive_ratio <= 0.34)
        can_reinforce = original_missing_count > 0 and alive_count > 0

        ongoing_units_alive += alive_count
        ongoing_units_missing += missing_count
        if can_reinforce:
            needing_support_count += 1

        ongoing.append(
            MissionStatusSnapshot(
                mission_id=mission_id,
                proposal_id=proposal_id,
                domain=domain,
                status=status,
                started_at=started_at,
                expires_at=expires_at,
                remaining_s=remaining_s,
                assigned_count=assigned_count,
                alive_count=alive_count,
                missing_count=missing_count,
                original_count=original_count,
                original_alive_count=original_alive_count,
                original_missing_count=original_missing_count,
                original_alive_ratio=float(original_alive_ratio),
                mission_degraded=bool(mission_degraded),
                original_type_counts=tuple(sorted((str(k), int(v)) for k, v in original_type_counts.items())),
                alive_tags=tuple(alive_tags),
                missing_tags=tuple(missing_tags),
                can_reinforce=bool(can_reinforce),
            )
        )

    ongoing.sort(key=lambda m: (m.remaining_s is None, m.remaining_s if m.remaining_s is not None else 999999.0, m.mission_id))

    return MissionSnapshot(
        ongoing=tuple(ongoing),
        ongoing_count=len(ongoing),
        ongoing_units_alive=int(ongoing_units_alive),
        ongoing_units_missing=int(ongoing_units_missing),
        needing_support_count=int(needing_support_count),
    )
