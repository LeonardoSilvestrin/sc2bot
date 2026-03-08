from __future__ import annotations

from typing import Any

from bot.builds import PROFILES_BY_OPENING
from bot.mind.awareness import Awareness, K


OPENING_TRANSITIONS_BY_NAME: dict[str, str] = {
    "BioOpen": "STIM",
    "MechaOpen": "BANSHEE",
    "RushDefenseOpen": "STIM",
}
VALID_TRANSITION_TARGETS = frozenset(OPENING_TRANSITIONS_BY_NAME.values())


def _require_non_empty_str(*, contract: str, value: Any) -> str:
    out = str(value or "").strip()
    if not out:
        raise RuntimeError(f"missing_contract:{contract}")
    return out


def validate_opening_name(*, opening: Any, contract: str) -> str:
    opening_name = _require_non_empty_str(contract=contract, value=opening)
    if opening_name not in PROFILES_BY_OPENING:
        raise RuntimeError(f"invalid_contract:{contract}:{opening_name}")
    return opening_name


def validate_transition_target(*, transition_target: Any, contract: str) -> str:
    target = _require_non_empty_str(contract=contract, value=transition_target).upper()
    if target not in VALID_TRANSITION_TARGETS:
        raise RuntimeError(f"invalid_contract:{contract}:{target}")
    return target


def transition_target_for_opening(*, opening: Any) -> str:
    opening_name = validate_opening_name(opening=opening, contract="macro.opening.selected")
    target = OPENING_TRANSITIONS_BY_NAME.get(opening_name)
    if target is None:
        raise RuntimeError(f"invalid_contract:macro.opening.transition_target:{opening_name}")
    return str(target)


def set_active_opening_state(
    *,
    awareness: Awareness,
    now: float,
    opening: Any,
    transition_target: Any,
    ttl_s: float = 30.0,
) -> None:
    opening_name = validate_opening_name(opening=opening, contract="macro.opening.selected")
    target = validate_transition_target(
        transition_target=transition_target,
        contract="macro.opening.transition_target",
    )
    awareness.mem.set(K("macro", "opening", "selected"), value=str(opening_name), now=float(now), ttl=float(ttl_s))
    awareness.mem.set(K("macro", "opening", "transition_target"), value=str(target), now=float(now), ttl=float(ttl_s))


def set_requested_opening_state(
    *,
    awareness: Awareness,
    now: float,
    opening: Any,
    transition_target: Any,
    reason: Any,
    ttl_s: float,
) -> None:
    opening_name = validate_opening_name(opening=opening, contract="macro.opening.requested")
    target = validate_transition_target(
        transition_target=transition_target,
        contract="macro.opening.requested_transition_target",
    )
    request_reason = _require_non_empty_str(contract="macro.opening.request_reason", value=reason)
    awareness.mem.set(K("macro", "opening", "requested"), value=str(opening_name), now=float(now), ttl=float(ttl_s))
    awareness.mem.set(
        K("macro", "opening", "requested_transition_target"),
        value=str(target),
        now=float(now),
        ttl=float(ttl_s),
    )
    awareness.mem.set(
        K("macro", "opening", "request_reason"),
        value=str(request_reason),
        now=float(now),
        ttl=float(ttl_s),
    )


def require_active_opening_state(*, awareness: Awareness, now: float) -> tuple[str, str]:
    raw_opening = awareness.mem.get(K("macro", "opening", "selected"), now=now, default=None)
    raw_transition = awareness.mem.get(K("macro", "opening", "transition_target"), now=now, default=None)
    if raw_opening is None or str(raw_opening).strip() == "":
        raw_opening = awareness.mem.get(K("macro", "opening", "build_selected"), now=now, default=None)
    if raw_transition is None or str(raw_transition).strip() == "":
        raw_transition = awareness.mem.get(K("macro", "opening", "build_transition_target"), now=now, default=None)
    opening_name = validate_opening_name(
        opening=raw_opening,
        contract="macro.opening.selected",
    )
    transition_target = validate_transition_target(
        transition_target=raw_transition,
        contract="macro.opening.transition_target",
    )
    return str(opening_name), str(transition_target)


def get_requested_opening_state(*, awareness: Awareness, now: float) -> tuple[str, str, str] | None:
    raw_opening = awareness.mem.get(K("macro", "opening", "requested"), now=now, default=None)
    if raw_opening is None or str(raw_opening).strip() == "":
        return None
    opening_name = validate_opening_name(opening=raw_opening, contract="macro.opening.requested")
    transition_target = validate_transition_target(
        transition_target=awareness.mem.get(K("macro", "opening", "requested_transition_target"), now=now, default=None),
        contract="macro.opening.requested_transition_target",
    )
    reason = _require_non_empty_str(
        contract="macro.opening.request_reason",
        value=awareness.mem.get(K("macro", "opening", "request_reason"), now=now, default=None),
    )
    return str(opening_name), str(transition_target), str(reason)


def sync_opening_selection_from_runner(*, bot, awareness: Awareness, now: float, ttl_s: float = 30.0) -> None:
    bor = getattr(bot, "build_order_runner", None)
    if bor is None:
        return
    opening_name = validate_opening_name(
        opening=getattr(bor, "chosen_opening", ""),
        contract="build_order_runner.chosen_opening",
    )
    transition_target = transition_target_for_opening(opening=opening_name)
    awareness.mem.set(K("macro", "opening", "build_selected"), value=str(opening_name), now=float(now), ttl=float(ttl_s))
    awareness.mem.set(
        K("macro", "opening", "build_transition_target"),
        value=str(transition_target),
        now=float(now),
        ttl=float(ttl_s),
    )
    requested = get_requested_opening_state(awareness=awareness, now=now)
    if requested is not None:
        requested_opening, requested_transition, _request_reason = requested
        if str(requested_opening) != str(opening_name):
            return
        set_active_opening_state(
            awareness=awareness,
            now=float(now),
            opening=str(requested_opening),
            transition_target=str(requested_transition),
            ttl_s=float(ttl_s),
        )
        return
    set_active_opening_state(
        awareness=awareness,
        now=float(now),
        opening=str(opening_name),
        transition_target=str(transition_target),
        ttl_s=float(ttl_s),
    )


def apply_opening_request(*, bot, awareness: Awareness, now: float, log=None, ttl_s: float = 30.0) -> None:
    request = get_requested_opening_state(awareness=awareness, now=now)
    if request is None:
        return
    requested_opening, requested_transition, request_reason = request
    bor = getattr(bot, "build_order_runner", None)
    if bor is None:
        set_active_opening_state(
            awareness=awareness,
            now=float(now),
            opening=str(requested_opening),
            transition_target=str(requested_transition),
            ttl_s=float(ttl_s),
        )
        return

    current_opening = validate_opening_name(
        opening=getattr(bor, "chosen_opening", ""),
        contract="build_order_runner.chosen_opening",
    )
    build_completed = bool(getattr(bor, "build_completed", False))
    selected_now, _ = require_active_opening_state(awareness=awareness, now=now)

    if build_completed:
        if selected_now != requested_opening:
            set_active_opening_state(
                awareness=awareness,
                now=float(now),
                opening=str(requested_opening),
                transition_target=str(requested_transition),
                ttl_s=float(ttl_s),
            )
        return

    if current_opening == requested_opening:
        return

    config = getattr(bor, "config", None)
    builds = {}
    if isinstance(config, dict):
        builds = dict(config.get("Builds", {}) or {})
    if requested_opening not in builds:
        raise RuntimeError(f"invalid_contract:build_order_runner.switch_opening:{requested_opening}")

    try:
        bor.switch_opening(str(requested_opening), remove_completed=True)
    except Exception as exc:
        raise RuntimeError(f"invalid_contract:build_order_runner.switch_opening:{type(exc).__name__}") from exc

    if str(requested_opening) == "RushDefenseOpen":
        try:
            bor.set_build_completed()
        except Exception:
            pass

    set_active_opening_state(
        awareness=awareness,
        now=float(now),
        opening=str(requested_opening),
        transition_target=str(requested_transition),
        ttl_s=float(ttl_s),
    )
    awareness.mem.set(K("macro", "opening", "switch_t"), value=float(now), now=float(now), ttl=None)
    awareness.mem.set(
        K("macro", "opening", "switch_reason"),
        value={
            "from": str(current_opening),
            "to": str(requested_opening),
            "reason": str(request_reason),
        },
        now=float(now),
        ttl=60.0,
    )
    if log is not None:
        log.emit(
            "opening_switch",
            {
                "t": round(float(now), 2),
                "from": str(current_opening),
                "to": str(requested_opening),
                "reason": str(request_reason),
            },
            meta={"module": "macro", "component": "build_order.runner"},
        )
