# =============================================================================
# bot/sensors/game_state_sensor.py
# =============================================================================
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Tuple

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.mind.attention import BaseSat, EconomySnapshot, IntelSnapshot, MacroSnapshot
from bot.mind.awareness import K


@dataclass(frozen=True)
class GameStateSnapshot:
    economy: EconomySnapshot
    macro: MacroSnapshot
    intel: IntelSnapshot


def _xy(u) -> tuple[float, float]:
    try:
        p = u.position
        return float(p.x), float(p.y)
    except Exception:
        return 0.0, 0.0


def _opening_done(*, awareness, now: float) -> bool:
    if awareness is None:
        raise RuntimeError("missing_contract:awareness")
    sentinel = "__MISSING__"
    value = awareness.mem.get(K("macro", "opening", "done"), now=now, default=sentinel)
    if value == sentinel:
        raise RuntimeError("missing_contract:macro.opening.done")
    if not isinstance(value, bool):
        raise RuntimeError(f"invalid_contract:macro.opening.done:{type(value).__name__}")
    return bool(value)


def _production_counts(bot) -> tuple[int, int, int]:
    prod_types = {U.BARRACKS, U.FACTORY, U.STARPORT}
    try:
        prod_structs = bot.structures.filter(lambda unit: unit.type_id in prod_types and unit.is_ready)
        total = int(prod_structs.amount)
        idle = int(prod_structs.idle.amount)
        return total, idle, int(total - idle)
    except Exception:
        return 0, 0, 0


def _addon_counts(bot) -> dict[str, int | float]:
    counts = {
        "barracks_reactor": 0,
        "barracks_techlab": 0,
        "factory_reactor": 0,
        "factory_techlab": 0,
        "starport_reactor": 0,
        "starport_techlab": 0,
    }
    try:
        counts["barracks_reactor"] = int(bot.structures.of_type({U.BARRACKSREACTOR}).ready.amount)
        counts["barracks_techlab"] = int(bot.structures.of_type({U.BARRACKSTECHLAB}).ready.amount)
        counts["factory_reactor"] = int(bot.structures.of_type({U.FACTORYREACTOR}).ready.amount)
        counts["factory_techlab"] = int(bot.structures.of_type({U.FACTORYTECHLAB}).ready.amount)
        counts["starport_reactor"] = int(bot.structures.of_type({U.STARPORTREACTOR}).ready.amount)
        counts["starport_techlab"] = int(bot.structures.of_type({U.STARPORTTECHLAB}).ready.amount)
    except Exception:
        pass

    reactor_total = int(counts["barracks_reactor"] + counts["factory_reactor"] + counts["starport_reactor"])
    techlab_total = int(counts["barracks_techlab"] + counts["factory_techlab"] + counts["starport_techlab"])
    addon_total = int(reactor_total + techlab_total)
    reactor_ratio = (float(reactor_total) / float(addon_total)) if addon_total > 0 else 0.0
    techlab_ratio = (float(techlab_total) / float(addon_total)) if addon_total > 0 else 0.0
    out: dict[str, int | float] = dict(counts)
    out["addon_reactor_total"] = int(reactor_total)
    out["addon_techlab_total"] = int(techlab_total)
    out["addon_total"] = int(addon_total)
    out["addon_reactor_ratio"] = float(reactor_ratio)
    out["addon_techlab_ratio"] = float(techlab_ratio)
    return out


def _orbital_scan_status(bot) -> Tuple[bool, float]:
    try:
        orbitals = bot.structures(U.ORBITALCOMMAND).ready
        if orbitals.amount == 0:
            return False, 0.0
        oc = orbitals.first
        energy = float(getattr(oc, "energy", 0.0) or 0.0)
        return (energy >= 50.0), energy
    except Exception:
        return False, 0.0


def _units_ready_histogram(bot) -> dict:
    out: dict = {}
    try:
        for unit in bot.units.ready:
            utype = unit.type_id
            out[utype] = int(out.get(utype, 0) + 1)
    except Exception:
        pass
    return out


def _as_dict_maybe(x):
    try:
        if callable(x):
            x = x()
    except Exception:
        pass
    return x if isinstance(x, dict) else {}


def _point_payload(pos) -> dict[str, float] | None:
    try:
        return {"x": float(pos.x), "y": float(pos.y)}
    except Exception:
        return None


def _point_from_payload(payload: Any) -> Point2 | None:
    if not isinstance(payload, dict):
        return None
    try:
        return Point2((float(payload.get("x", 0.0) or 0.0), float(payload.get("y", 0.0) or 0.0)))
    except Exception:
        return None


def _site_labels(bot) -> list[tuple[str, Point2]]:
    out: list[tuple[str, Point2]] = []
    try:
        start = bot.start_location
        out.append(("MAIN", start))
    except Exception:
        start = None
    exps = list(getattr(bot, "expansion_locations_list", []) or [])
    if not exps:
        return out
    try:
        if start is not None:
            exps = [p for p in exps if float(p.distance_to(start)) > 2.0]
            exps.sort(key=lambda p: float(start.distance_to(p)))
    except Exception:
        pass
    labels = ["NATURAL", "THIRD", "FOURTH", "FIFTH", "SIXTH"]
    for idx, pos in enumerate(exps):
        label = labels[idx] if idx < len(labels) else f"BASE_{idx + 2}"
        out.append((str(label), pos))
    return out


def _townhall_units(bot) -> list:
    try:
        return list(getattr(bot, "townhalls", []) or [])
    except Exception:
        return []


def _is_readyish_townhall(unit) -> bool:
    try:
        return bool(getattr(unit, "build_progress", 0.0) or 0.0) >= 0.98
    except Exception:
        return False


def _is_flying_townhall(unit) -> bool:
    try:
        return bool(getattr(unit, "is_flying", False))
    except Exception:
        return False


def _is_mining_townhall(unit) -> bool:
    return bool(_is_readyish_townhall(unit) and not _is_flying_townhall(unit))


def _state_for_base(*, entry: dict[str, Any], unit, intended_pos: Point2 | None) -> str:
    if unit is None:
        if bool(entry.get("needs_rebuild", False)):
            return "DESTROYED"
        return str(entry.get("state", "PLANNED") or "PLANNED")
    flying = bool(_is_flying_townhall(unit))
    current_pos = getattr(unit, "position", None)
    dist_to_site = 9999.0
    try:
        if intended_pos is not None and current_pos is not None:
            dist_to_site = float(current_pos.distance_to(intended_pos))
    except Exception:
        dist_to_site = 9999.0
    if flying:
        if dist_to_site <= 5.0:
            return "FLYING_TO_SITE"
        return "BUILDING_OFFSITE"
    if not bool(_is_readyish_townhall(unit)):
        return "BUILDING_OFFSITE" if dist_to_site > 8.0 else "SECURING"
    if dist_to_site <= 8.0:
        return "ESTABLISHED"
    if dist_to_site > 15.0:
        # CC is ready but far from intended site (e.g. built at main, not yet flown to natural).
        # Treat as offsite so the fly-down logic is still triggered.
        return "BUILDING_OFFSITE"
    return "LANDED_UNSAFE"


def _update_our_bases_registry(bot, *, awareness, now: float) -> dict[str, dict[str, Any]]:
    previous = awareness.mem.get(K("intel", "our_bases", "registry"), now=now, default={}) or {}
    if not isinstance(previous, dict):
        previous = {}
    labels = _site_labels(bot)
    townhalls = _townhall_units(bot)
    by_tag: dict[int, Any] = {}
    for th in townhalls:
        try:
            by_tag[int(th.tag)] = th
        except Exception:
            continue
    assigned_tags: set[int] = set()
    out: dict[str, dict[str, Any]] = {}

    # First pass: keep stable ownership for known tags.
    for order, (label, pos) in enumerate(labels):
        prev = dict(previous.get(label, {})) if isinstance(previous.get(label, {}), dict) else {}
        entry: dict[str, Any] = {
            "label": str(label),
            "order": int(order),
            "intended_pos": _point_payload(pos),
            "current_pos": prev.get("current_pos"),
            "townhall_tag": None,
            "townhall_type": str(prev.get("townhall_type", "") or ""),
            "state": str(prev.get("state", "PLANNED") or "PLANNED"),
            "owned": bool(prev.get("owned", label == "MAIN")),
            "is_flying": bool(prev.get("is_flying", False)),
            "is_ready": bool(prev.get("is_ready", False)),
            "is_mining": bool(prev.get("is_mining", False)),
            "safe_to_land": bool(prev.get("safe_to_land", False)),
            "safe_to_mine": bool(prev.get("safe_to_mine", False)),
            "fortified": bool(prev.get("fortified", False)),
            "needs_rebuild": bool(prev.get("needs_rebuild", False)),
            "destroyed": bool(prev.get("destroyed", False)),
            "updated_at": float(now),
        }
        prev_tag = int(prev.get("townhall_tag", 0) or 0)
        unit = by_tag.get(prev_tag)
        if unit is not None:
            entry["townhall_tag"] = int(prev_tag)
            entry["townhall_type"] = str(getattr(unit.type_id, "name", "") or "")
            entry["current_pos"] = _point_payload(getattr(unit, "position", None))
            entry["is_flying"] = bool(_is_flying_townhall(unit))
            entry["is_ready"] = bool(_is_readyish_townhall(unit))
            entry["is_mining"] = bool(_is_mining_townhall(unit))
            entry["owned"] = True
            entry["destroyed"] = False
            entry["needs_rebuild"] = False
            entry["state"] = _state_for_base(entry=entry, unit=unit, intended_pos=pos)
            assigned_tags.add(int(prev_tag))
        elif prev_tag:
            entry["owned"] = bool(prev.get("owned", False))
            entry["destroyed"] = bool(prev.get("owned", False))
            entry["needs_rebuild"] = bool(prev.get("owned", False))
            entry["state"] = "DESTROYED" if bool(entry["destroyed"]) else str(entry["state"])
        out[str(label)] = entry

    # Second pass: assign remaining townhalls by proximity to intended site.
    for th in townhalls:
        try:
            tag = int(th.tag)
        except Exception:
            continue
        if tag in assigned_tags:
            continue
        best_label = None
        best_dist = 9999.0
        for label, pos in labels:
            entry = out.get(str(label), {})
            if int(entry.get("townhall_tag", 0) or 0) != 0:
                continue
            try:
                dist = float(th.distance_to(pos))
            except Exception:
                dist = 9999.0
            if dist < best_dist:
                best_label = str(label)
                best_dist = float(dist)
        if best_label is None:
            continue
        pos = _point_from_payload(out[best_label].get("intended_pos"))
        out[best_label]["townhall_tag"] = int(tag)
        out[best_label]["townhall_type"] = str(getattr(th.type_id, "name", "") or "")
        out[best_label]["current_pos"] = _point_payload(getattr(th, "position", None))
        out[best_label]["is_flying"] = bool(_is_flying_townhall(th))
        out[best_label]["is_ready"] = bool(_is_readyish_townhall(th))
        out[best_label]["is_mining"] = bool(_is_mining_townhall(th))
        out[best_label]["owned"] = True
        out[best_label]["destroyed"] = False
        out[best_label]["needs_rebuild"] = False
        out[best_label]["state"] = _state_for_base(entry=out[best_label], unit=th, intended_pos=pos)
        assigned_tags.add(int(tag))

    owned_townhalls_total = 0
    established_bases_total = 0
    mining_bases_total = 0
    for entry in out.values():
        if bool(entry.get("townhall_tag")):
            owned_townhalls_total += 1
        if str(entry.get("state", "")).upper() in {"ESTABLISHED", "LANDED_UNSAFE", "SECURING"}:
            established_bases_total += 1
        if bool(entry.get("is_mining", False)):
            mining_bases_total += 1
    awareness.mem.set(K("intel", "our_bases", "registry"), value=dict(out), now=now, ttl=8.0)
    awareness.mem.set(
        K("intel", "our_bases", "summary"),
        value={
            "owned_townhalls_total": int(owned_townhalls_total),
            "established_bases_total": int(established_bases_total),
            "mining_bases_total": int(mining_bases_total),
        },
        now=now,
        ttl=8.0,
    )
    return out


def derive_game_state_snapshot(bot, *, awareness=None) -> GameStateSnapshot:
    now = float(getattr(bot, "time", 0.0) or 0.0)
    if awareness is not None:
        _update_our_bases_registry(bot, awareness=awareness, now=now)
    # resources + supply
    try:
        minerals = int(getattr(bot, "minerals", 0) or 0)
        gas = int(getattr(bot, "vespene", 0) or 0)
        supply_used = int(getattr(bot, "supply_used", 0) or 0)
        supply_cap = int(getattr(bot, "supply_cap", 0) or 0)
        supply_left = int(supply_cap - supply_used)
        supply_blocked = bool(supply_left <= 0)
    except Exception:
        minerals, gas = 0, 0
        supply_used, supply_cap, supply_left = 0, 0, 0
        supply_blocked = False

    # workers
    try:
        workers = bot.workers
        workers_total = int(workers.amount)
        idle_units = bot.units(U.SCV).idle
        workers_idle = int(idle_units.amount)
        idle_worker_tags = tuple(int(u.tag) for u in idle_units)
        idle_worker_pos = tuple(_xy(u) for u in idle_units)
    except Exception:
        workers_total = 0
        workers_idle = 0
        idle_worker_tags = ()
        idle_worker_pos = ()

    units_ready = _units_ready_histogram(bot)

    # townhalls
    try:
        townhalls = bot.townhalls.ready
    except Exception:
        townhalls = bot.townhalls

    th_list = list(townhalls)
    try:
        sl = bot.start_location
        th_list.sort(key=lambda th: float(th.distance_to(sl)))
    except Exception:
        pass

    # mediator mappings (may be callables)
    worker_to_gas = _as_dict_maybe(getattr(bot.mediator, "get_worker_to_vespene_dict", {}))
    worker_to_th = _as_dict_maybe(getattr(bot.mediator, "get_worker_tag_to_townhall_tag", {}))

    # refineries
    try:
        refineries = [g for g in bot.gas_buildings if g.is_ready]
    except Exception:
        refineries = []

    # refinery -> closest townhall tag
    refinery_to_th: dict[int, int] = {}
    for refinery in refineries:
        try:
            rtag = int(refinery.tag)
        except Exception:
            continue
        if townhalls.amount == 0:
            continue
        try:
            th = townhalls.closest_to(refinery.position)
            refinery_to_th[rtag] = int(th.tag)
        except Exception:
            pass

    # refinery snapshot per TH
    th_refineries: dict[int, list[tuple[int, tuple[float, float], int]]] = defaultdict(list)
    for refinery in refineries:
        try:
            rtag = int(refinery.tag)
            ideal = int(getattr(refinery, "ideal_harvesters", 3) or 3)
            ideal = 3 if ideal <= 0 else ideal
            th_tag = int(refinery_to_th.get(rtag, -1))

            eco = (rtag, _xy(refinery), ideal)
            if th_tag != -1:
                th_refineries[th_tag].append(eco)
        except Exception:
            continue

    # mapping-based mineral workers per TH (for BaseSat mineral_actual)
    mineral_workers_by_th: dict[int, list[int]] = defaultdict(list)
    try:
        gathering_scvs = bot.mediator.get_units_from_role(role=UnitRole.GATHERING, unit_type=U.SCV)
        all_scvs = list(gathering_scvs) + list(bot.units(U.SCV).idle)
        uniq = {}
        for unit in all_scvs:
            try:
                uniq[int(unit.tag)] = unit
            except Exception:
                pass

        for wtag, _unit in uniq.items():
            # ignore gas-tagged workers
            if int(wtag) in worker_to_gas:
                continue

            th_tag = worker_to_th.get(int(wtag), None)
            if th_tag is None:
                continue
            try:
                th_tag = int(th_tag)
            except Exception:
                continue
            if th_tag == -1:
                continue

            mineral_workers_by_th[th_tag].append(int(wtag))
    except Exception:
        pass

    # invert worker_to_gas if it maps worker_tag -> refinery_tag
    gas_workers_per_refinery: dict[int, int] = defaultdict(int)
    for _wtag, rtag in worker_to_gas.items():
        try:
            gas_workers_per_refinery[int(rtag)] += 1
        except Exception:
            pass

    # build base saturation view
    bases_sat_out: list[BaseSat] = []

    surplus_tags: list[int] = []
    deficit_tags: list[int] = []
    bases_under_saturated = 0
    bases_over_saturated = 0

    for base_id, th in enumerate(th_list):
        try:
            th_tag = int(th.tag)

            # IMPORTANT FIX:
            # In python-sc2, townhall.assigned_harvesters / ideal_harvesters are mineral-line only.
            mineral_ideal = int(getattr(th, "ideal_harvesters", 16) or 16)
            mineral_ideal = 16 if mineral_ideal <= 0 else mineral_ideal

            # refineries (stable order by proximity to TH)
            refs = th_refineries.get(th_tag, [])
            try:
                tx, ty = _xy(th)
                refs = sorted(refs, key=lambda r: float((r.pos[0] - tx) ** 2 + (r.pos[1] - ty) ** 2))
            except Exception:
                pass

            refinery_tags = [int(r[0]) for r in refs]
            gas_saturation = tuple(int(gas_workers_per_refinery.get(rtag, 0)) for rtag in refinery_tags)
            gas_ideal = tuple(int(r[2]) for r in refs)
            gas_assigned = int(sum(gas_saturation))
            gas_target = int(sum(gas_ideal))

            geysers_taken = int(len(refs))

            mineral_tags = mineral_workers_by_th.get(th_tag, [])
            mineral_actual = int(len(mineral_tags))

            workers_actual = int(mineral_actual + gas_assigned)
            workers_ideal = int(mineral_ideal + gas_target)

            mineral_surplus = max(0, mineral_actual - mineral_ideal)
            mineral_deficit = max(0, mineral_ideal - mineral_actual)

            if mineral_deficit > 0:
                bases_under_saturated += 1
            if mineral_surplus > 0:
                bases_over_saturated += 1

            if mineral_surplus > 0 and mineral_tags:
                surplus_tags.extend(mineral_tags[: min(6, len(mineral_tags))])
            if mineral_deficit > 0 and mineral_tags:
                deficit_tags.extend(mineral_tags[: min(2, len(mineral_tags))])

            bases_sat_out.append(
                BaseSat(
                    base_id=int(base_id),
                    loc=_xy(th),
                    th_tag=int(th_tag),
                    geysers_taken=int(geysers_taken),
                    workers_actual=int(workers_actual),
                    workers_ideal=int(workers_ideal),
                    mineral_actual=int(mineral_actual),
                    mineral_ideal=int(mineral_ideal),
                    gas_saturation=tuple(int(x) for x in gas_saturation),
                    gas_ideal=tuple(int(x) for x in gas_ideal),
                    refinery_tags=tuple(int(x) for x in refinery_tags),
                )
            )

        except Exception:
            continue

    surplus_mineral_worker_tags = tuple(int(t) for t in surplus_tags[:24])
    deficit_mineral_worker_tags = tuple(int(t) for t in deficit_tags[:24])

    economy = EconomySnapshot(
        units_ready=units_ready,
        supply_left=supply_left,
        minerals=minerals,
        gas=gas,
        supply_used=supply_used,
        supply_cap=supply_cap,
        supply_blocked=bool(supply_blocked),
        workers_total=workers_total,
        workers_idle=workers_idle,
        idle_worker_tags=idle_worker_tags,
        idle_worker_pos=idle_worker_pos,
        bases_sat=tuple(bases_sat_out),
        surplus_mineral_worker_tags=surplus_mineral_worker_tags,
        deficit_mineral_worker_tags=deficit_mineral_worker_tags,
    )

    prod_structures_total, prod_structures_idle, prod_structures_active = _production_counts(bot)
    add_ons = _addon_counts(bot)

    macro = MacroSnapshot(
        opening_done=bool(_opening_done(awareness=awareness, now=now)),
        bases_total=int(len(bases_sat_out)),
        prod_structures_total=int(prod_structures_total),
        prod_structures_idle=int(prod_structures_idle),
        prod_structures_active=int(prod_structures_active),
        addon_total=int(add_ons["addon_total"]),
        addon_reactor_total=int(add_ons["addon_reactor_total"]),
        addon_techlab_total=int(add_ons["addon_techlab_total"]),
        addon_reactor_ratio=float(add_ons["addon_reactor_ratio"]),
        addon_techlab_ratio=float(add_ons["addon_techlab_ratio"]),
        barracks_reactor=int(add_ons["barracks_reactor"]),
        barracks_techlab=int(add_ons["barracks_techlab"]),
        factory_reactor=int(add_ons["factory_reactor"]),
        factory_techlab=int(add_ons["factory_techlab"]),
        starport_reactor=int(add_ons["starport_reactor"]),
        starport_techlab=int(add_ons["starport_techlab"]),
    )

    orbital_ready_to_scan, orbital_energy = _orbital_scan_status(bot)
    intel = IntelSnapshot(
        orbital_ready_to_scan=bool(orbital_ready_to_scan),
        orbital_energy=float(orbital_energy),
    )

    return GameStateSnapshot(
        economy=economy,
        macro=macro,
        intel=intel,
    )
