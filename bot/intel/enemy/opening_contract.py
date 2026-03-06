from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.awareness import Awareness, K


@dataclass(frozen=True)
class OpeningExitRule:
    min_time_s: float
    max_time_s: float
    min_units: Dict[U, int]
    min_structures_ready: Dict[U, int]
    require_any_addon: bool = False


DEFAULT_OPENING_EXIT_RULE = OpeningExitRule(
    min_time_s=95.0,
    max_time_s=260.0,
    min_units={},
    min_structures_ready={U.BARRACKS: 1, U.FACTORY: 1},
    require_any_addon=False,
)

OPENING_EXIT_RULES_BY_NAME: dict[str, OpeningExitRule] = {
    "MechaOpen": OpeningExitRule(
        min_time_s=65.0,
        max_time_s=210.0,
        min_units={U.REAPER: 1, U.HELLION: 2},
        min_structures_ready={U.FACTORY: 1},
        require_any_addon=True,
    ),
    "RushDefenseOpen": OpeningExitRule(
        min_time_s=70.0,
        max_time_s=210.0,
        min_units={U.MARINE: 6, U.SIEGETANK: 1},
        min_structures_ready={U.BARRACKS: 2, U.FACTORY: 1},
        require_any_addon=True,
    ),
}


def _unit_count_including_pending(bot, unit_id: U) -> int:
    try:
        ready = int(bot.units(unit_id).amount)
    except Exception:
        ready = 0
    try:
        pending = int(bot.already_pending(unit_id) or 0)
    except Exception:
        pending = 0
    return int(ready + pending)


def _structure_ready_count(bot, structure_id: U) -> int:
    try:
        return int(bot.structures(structure_id).ready.amount)
    except Exception:
        return 0


def _has_any_ready_addon(bot) -> bool:
    addons = (U.BARRACKSREACTOR, U.BARRACKSTECHLAB, U.FACTORYREACTOR, U.FACTORYTECHLAB, U.STARPORTREACTOR, U.STARPORTTECHLAB)
    try:
        return any(int(bot.structures(addon).ready.amount) > 0 for addon in addons)
    except Exception:
        return False


def _opening_rule_done(bot, *, rule: OpeningExitRule, now: float) -> bool:
    if float(now) < float(rule.min_time_s):
        return False
    if float(now) >= float(rule.max_time_s):
        return True
    for unit_id, required in dict(rule.min_units).items():
        if int(_unit_count_including_pending(bot, unit_id)) < int(required):
            return False
    for structure_id, required in dict(rule.min_structures_ready).items():
        if int(_structure_ready_count(bot, structure_id)) < int(required):
            return False
    if bool(rule.require_any_addon) and not bool(_has_any_ready_addon(bot)):
        return False
    return True


def derive_opening_contract_intel(bot, *, awareness: Awareness, now: float) -> None:
    bor = getattr(bot, "build_order_runner", None)
    done = bool(getattr(bor, "build_completed", False)) if bor is not None else False
    done_reason = "build_runner"
    if bor is not None and not bool(done):
        chosen_opening = str(getattr(bor, "chosen_opening", "") or "").strip()
        rule = OPENING_EXIT_RULES_BY_NAME.get(chosen_opening, DEFAULT_OPENING_EXIT_RULE)
        if _opening_rule_done(bot, rule=rule, now=float(now)):
            try:
                bor.set_build_completed()
                done = True
                done_reason = f"opening_signature:{chosen_opening or 'default'}"
            except Exception:
                pass
    awareness.mem.set(K("macro", "opening", "done"), value=bool(done), now=float(now), ttl=5.0)
    awareness.mem.set(K("macro", "opening", "done_reason"), value=str(done_reason), now=float(now), ttl=5.0)
    awareness.mem.set(K("macro", "opening", "done_owner"), value="intel.opening_contract", now=float(now), ttl=5.0)
