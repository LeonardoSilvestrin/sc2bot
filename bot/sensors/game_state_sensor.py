# =============================================================================
# bot/sensors/game_state_sensor.py
# =============================================================================
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Tuple

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as U

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


def _opening_done(bot, *, awareness=None, now: float = 0.0) -> bool:
    if awareness is not None:
        try:
            forced = bool(awareness.mem.get(K("macro", "opening", "forced_done"), now=now, default=False))
            if forced:
                return True
        except Exception:
            pass
    bor = getattr(bot, "build_order_runner", None)
    if bor is None:
        return False
    if not hasattr(bor, "build_completed"):
        raise AttributeError("Game state sensor requires build_order_runner.build_completed")
    return bool(bor.build_completed)


def _production_counts(bot) -> tuple[int, int, int]:
    prod_types = {U.BARRACKS, U.FACTORY, U.STARPORT}
    try:
        prod_structs = bot.structures.filter(lambda unit: unit.type_id in prod_types and unit.is_ready)
        total = int(prod_structs.amount)
        idle = int(prod_structs.idle.amount)
        return total, idle, int(total - idle)
    except Exception:
        return 0, 0, 0


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


def derive_game_state_snapshot(bot, *, awareness=None) -> GameStateSnapshot:
    now = float(getattr(bot, "time", 0.0) or 0.0)
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

    macro = MacroSnapshot(
        opening_done=bool(_opening_done(bot, awareness=awareness, now=now)),
        minerals=minerals,
        vespene=gas,
        workers_total=workers_total,
        workers_idle=workers_idle,
        bases_total=int(len(bases_sat_out)),
        bases_under_saturated=int(bases_under_saturated),
        bases_over_saturated=int(bases_over_saturated),
        prod_structures_total=int(prod_structures_total),
        prod_structures_idle=int(prod_structures_idle),
        prod_structures_active=int(prod_structures_active),
        supply_used=int(supply_used),
        supply_cap=int(supply_cap),
        supply_left=int(supply_left),
        supply_blocked=bool(supply_blocked),
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
