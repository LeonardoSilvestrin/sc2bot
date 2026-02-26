# bot/sensors/macro_sensor.py
from __future__ import annotations

from sc2.ids.unit_typeid import UnitTypeId
from bot.mind.attention import MacroSnapshot


def _opening_done(bot) -> bool:
    bor = getattr(bot, "build_order_runner", None)
    if bor is None:
        return False
    if not hasattr(bor, "build_completed"):
        raise AttributeError("Macro sensor requires build_order_runner.build_completed")

    return bool(bor.build_completed)


def _get_bases(bot):
    # Terran bases: CommandCenter, OrbitalCommand, PlanetaryFortress
    base_types = {
        UnitTypeId.COMMANDCENTER,
        UnitTypeId.ORBITALCOMMAND,
        UnitTypeId.PLANETARYFORTRESS,
    }
    return bot.townhalls.filter(lambda u: u.type_id in base_types)


def _get_production_structures(bot):
    # Terran production
    prod_types = {
        UnitTypeId.BARRACKS,
        UnitTypeId.FACTORY,
        UnitTypeId.STARPORT,
    }
    return bot.structures.filter(lambda u: u.type_id in prod_types and u.is_ready)


def derive_macro_snapshot(bot) -> MacroSnapshot:

    # --- Economy ---
    minerals = int(bot.minerals)
    vespene = int(bot.vespene)

    workers = bot.workers
    workers_total = workers.amount
    workers_idle = workers.idle.amount

    # --- Bases / Saturation ---
    bases = _get_bases(bot)
    bases_total = bases.amount

    bases_under = 0
    bases_over = 0

    for base in bases:
        assigned = base.assigned_harvesters
        ideal = base.ideal_harvesters

        if ideal == 0:
            continue

        if assigned < ideal:
            bases_under += 1
        elif assigned > ideal:
            bases_over += 1

    # --- Production structures ---
    prod_structs = _get_production_structures(bot)
    prod_structures_total = prod_structs.amount

    prod_structures_idle = prod_structs.idle.amount
    prod_structures_active = prod_structures_total - prod_structures_idle

    # --- Supply ---
    supply_used = bot.supply_used
    supply_cap = bot.supply_cap
    supply_left = supply_cap - supply_used
    supply_blocked = supply_left <= 0

    return MacroSnapshot(
        opening_done=bool(_opening_done(bot)),

        minerals=minerals,
        vespene=vespene,

        workers_total=workers_total,
        workers_idle=workers_idle,

        bases_total=bases_total,
        bases_under_saturated=bases_under,
        bases_over_saturated=bases_over,

        prod_structures_total=prod_structures_total,
        prod_structures_idle=prod_structures_idle,
        prod_structures_active=prod_structures_active,

        supply_used=supply_used,
        supply_cap=supply_cap,
        supply_left=supply_left,
        supply_blocked=supply_blocked,
    )