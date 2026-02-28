from __future__ import annotations

from dataclasses import dataclass

from ares.behaviors.macro.auto_supply import AutoSupply
from ares.behaviors.macro.expansion_controller import ExpansionController
from ares.behaviors.macro.gas_building_controller import GasBuildingController
from ares.behaviors.macro.macro_plan import MacroPlan
from ares.behaviors.macro.production_controller import ProductionController
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.tasks.base_task import BaseTask, TaskTick, TaskResult
from bot.tasks.macro.utils.desired_comp import desired_comp_units, unit_comp_to_controller_dict
from bot.tasks.macro.utils.macro_policies import RushFortifyPolicy, WallPlacementPolicy
from bot.tasks.macro.utils.state_store import MacroStateStore
from bot.tasks.macro.utils.wall_mapper import try_build_next_wall_depot


@dataclass
class MacroSpendingTick(BaseTask):
    awareness: Awareness
    log: DevLogger | None = None
    target_bases_default: int = 2
    flood_m: int = 800
    flood_hi_m: int = 1400
    flood_hold_s: float = 12.0
    log_every_iters: int = 22
    orbital_target: int = 3
    main_wall_target: int = 2
    natural_wall_target: int = 2

    def __init__(
        self,
        *,
        awareness: Awareness,
        log: DevLogger | None = None,
        target_bases_default: int = 2,
        flood_m: int = 800,
        flood_hi_m: int = 1400,
        flood_hold_s: float = 12.0,
        log_every_iters: int = 22,
    ):
        super().__init__(task_id="macro_spending", domain="MACRO_SPENDING", commitment=10)
        self.awareness = awareness
        self.log = log
        self.target_bases_default = int(target_bases_default)
        self.flood_m = int(flood_m)
        self.flood_hi_m = int(flood_hi_m)
        self.flood_hold_s = float(flood_hold_s)
        self.log_every_iters = int(log_every_iters)
        self.orbital_target = 3
        self.main_wall_target = 2
        self.natural_wall_target = 2
        self.state_store = MacroStateStore(self.awareness)
        self.wall_policy = WallPlacementPolicy(
            state=self.state_store,
            main_wall_target=int(self.main_wall_target),
            natural_wall_target=int(self.natural_wall_target),
        )
        self.rush_fortify_policy = RushFortifyPolicy(state=self.state_store)

    def _morph_reserve(self, *, now: float) -> tuple[int, int, int, str]:
        pending = int(self.awareness.mem.get(K("macro", "morph", "pending_count"), now=now, default=0) or 0)
        reserve_m = int(self.awareness.mem.get(K("macro", "morph", "reserve_minerals"), now=now, default=0) or 0)
        reserve_g = int(self.awareness.mem.get(K("macro", "morph", "reserve_gas"), now=now, default=0) or 0)
        target_kind = str(self.awareness.mem.get(K("macro", "morph", "target_kind"), now=now, default="ORBITAL") or "ORBITAL").upper()
        return pending, reserve_m, reserve_g, target_kind

    def _priority_reserve(self, *, now: float) -> tuple[int, int, str]:
        reserve_m = int(self.awareness.mem.get(K("macro", "desired", "reserve_minerals"), now=now, default=0) or 0)
        reserve_g = int(self.awareness.mem.get(K("macro", "desired", "reserve_gas"), now=now, default=0) or 0)
        reserve_unit = str(self.awareness.mem.get(K("macro", "desired", "reserve_unit"), now=now, default="") or "")
        return reserve_m, reserve_g, reserve_unit

    def _army_comp_for_controllers(self, now: float) -> dict[U, dict[str, float | int]]:
        comp = desired_comp_units(awareness=self.awareness, now=now)
        return unit_comp_to_controller_dict(comp)

    def _target_bases(self, *, attention: Attention, now: float, expand_bias: int = 0) -> int:
        minerals = int(attention.economy.minerals)

        flood_until = float(self.awareness.mem.get(K("macro", "spending", "flood_until"), now=now, default=0.0) or 0.0)
        if minerals >= self.flood_hi_m:
            flood_until = now + float(self.flood_hold_s)
            self.awareness.mem.set(K("macro", "spending", "flood_until"), value=float(flood_until), now=now, ttl=None)

        flood_active = minerals >= self.flood_m or now < flood_until

        target = int(self.target_bases_default)
        if flood_active:
            target += 1
        target += int(expand_bias)

        return max(1, int(target))

    def _rush_state(self, *, now: float) -> str:
        return self.state_store.get_rush_state(now=now)

    def _parity_signal(self, *, now: float) -> tuple[str, str, str, int, int]:
        overall = str(self.awareness.mem.get(K("strategy", "parity", "overall"), now=now, default="EVEN") or "EVEN")
        econ = str(self.awareness.mem.get(K("strategy", "parity", "econ"), now=now, default="EVEN") or "EVEN")
        army = str(self.awareness.mem.get(K("strategy", "parity", "army"), now=now, default="EVEN") or "EVEN")
        expand_bias = int(self.awareness.mem.get(K("strategy", "parity", "expand_bias"), now=now, default=0) or 0)
        army_bias = int(self.awareness.mem.get(K("strategy", "parity", "army_bias"), now=now, default=0) or 0)
        return overall, econ, army, expand_bias, army_bias

    @staticmethod
    def _is_rush_active(state: str) -> bool:
        return str(state).upper() in {"SUSPECTED", "CONFIRMED", "HOLDING"}

    @staticmethod
    def _is_rush_confirmed(state: str) -> bool:
        return str(state).upper() == "CONFIRMED"

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err

        bor = getattr(bot, "build_order_runner", None)
        if bor is not None and not bool(getattr(bor, "build_completed", False)):
            return TaskResult.noop("build_order_active")

        now = float(tick.time)
        rush_state = self._rush_state(now=now)
        rush_active = self._is_rush_active(rush_state)
        rush_confirmed = self._is_rush_confirmed(rush_state)
        parity_overall, parity_econ, parity_army, expand_bias, army_bias = self._parity_signal(now=now)
        pending_morph, reserve_m, reserve_g, target_kind = self._morph_reserve(now=now)
        prio_m, prio_g, prio_unit = self._priority_reserve(now=now)

        # Absolute priority: morph CCs when housekeeping says there are pending townhalls.
        if pending_morph > 0:
            issued = 0
            for th in bot.townhalls.ready:
                if th.type_id != U.COMMANDCENTER:
                    continue
                if not bool(getattr(th, "is_idle", False)):
                    continue

                if target_kind == "PLANETARY":
                    try:
                        if bot.can_afford(U.PLANETARYFORTRESS):
                            th(AbilityId.UPGRADETOPLANETARYFORTRESS_PLANETARYFORTRESS)
                            issued += 1
                            break
                    except Exception:
                        pass
                else:
                    if bot.can_afford(U.ORBITALCOMMAND):
                        th(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)
                        issued += 1
                        break

            if issued > 0:
                if self.log is not None:
                    self.log.emit(
                        "macro_spending",
                        {
                            "iter": int(tick.iteration),
                            "t": round(float(now), 2),
                            "action": "morph_priority",
                            "issued": int(issued),
                            "target_kind": str(target_kind),
                            "pending_morph": int(pending_morph),
                            "reserve_minerals": int(reserve_m),
                            "reserve_gas": int(reserve_g),
                            "minerals": int(attention.economy.minerals),
                            "gas": int(attention.economy.gas),
                        },
                    )
                return TaskResult.running("morph_priority_issued")

            if int(attention.economy.minerals) < int(reserve_m) or int(attention.economy.gas) < int(reserve_g):
                return TaskResult.running("morph_priority_reserving")

        if int(attention.economy.minerals) < int(prio_m) or int(attention.economy.gas) < int(prio_g):
            if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
                self.log.emit(
                    "macro_spending",
                    {
                        "iter": int(tick.iteration),
                        "t": round(float(now), 2),
                        "action": "priority_unit_reserve_hold",
                        "reserve_unit": str(prio_unit),
                        "reserve_minerals": int(prio_m),
                        "reserve_gas": int(prio_g),
                        "minerals": int(attention.economy.minerals),
                        "gas": int(attention.economy.gas),
                    },
                )
            return TaskResult.running("priority_unit_reserving")

        if rush_confirmed:
            fort = await self.rush_fortify_policy.fortify_natural(bot, now=now)
            self.state_store.set_rush_active(now=now, active=True, ttl=30.0)
            if self.log is not None and (int(fort["depots"]) > 0 or int(fort["bunkers"]) > 0 or int(tick.iteration) % self.log_every_iters == 0):
                self.log.emit(
                    "macro_spending",
                    {
                        "iter": int(tick.iteration),
                        "t": round(float(now), 2),
                        "action": "rush_fortify_natural",
                        "rush_state": str(rush_state),
                        "issued_depots": int(fort["depots"]),
                        "issued_bunkers": int(fort["bunkers"]),
                    },
                )

        # Hard priority with progressive gate:
        # - Upgrade existing CCs first.
        # - Do not deadlock macro before 3rd CC exists.
        orbitals_ready = int(bot.structures(U.ORBITALCOMMAND).ready.amount)
        orbitals_pending = int(bot.already_pending(U.ORBITALCOMMAND))
        orbitals_total = int(orbitals_ready + orbitals_pending)
        townhalls_total = int(bot.townhalls.ready.amount)
        required_orbitals_now = min(int(self.orbital_target), int(townhalls_total))

        if required_orbitals_now > 0 and orbitals_total < required_orbitals_now:
            issued_orbital = 0
            for th in bot.townhalls.ready:
                if orbitals_total >= required_orbitals_now:
                    break
                if th.type_id != U.COMMANDCENTER:
                    continue
                if not bool(getattr(th, "is_idle", False)):
                    continue
                if not bot.can_afford(U.ORBITALCOMMAND):
                    break
                th(AbilityId.UPGRADETOORBITAL_ORBITALCOMMAND)
                issued_orbital += 1
                orbitals_total += 1

            if self.log is not None and (issued_orbital > 0 or int(tick.iteration) % self.log_every_iters == 0):
                self.log.emit(
                    "macro_spending",
                    {
                        "iter": int(tick.iteration),
                        "t": round(float(now), 2),
                        "action": "orbital_priority",
                        "issued_orbital": int(issued_orbital),
                        "orbitals_total": int(orbitals_total),
                        "required_orbitals_now": int(required_orbitals_now),
                        "townhalls_total": int(townhalls_total),
                        "orbital_target": int(self.orbital_target),
                        "minerals": int(attention.economy.minerals),
                    },
                )

            # If we already have 3+ townhalls, keep strict priority until the first 3 are upgraded.
            if int(townhalls_total) >= int(self.orbital_target):
                return TaskResult.running("orbital_priority")

        wall = self.wall_policy.evaluate(bot, now=now)
        main_plan = wall.main_plan
        nat_plan = wall.natural_plan
        main_target = int(wall.main_target)
        nat_target = int(wall.natural_target)
        main_occupied = int(main_plan.occupied)
        nat_occupied = int(nat_plan.occupied)
        nat_total = int(nat_plan.total)

        if wall.action == "build_main":
            if try_build_next_wall_depot(bot, plan=main_plan):
                if self.log is not None:
                    self.log.emit(
                        "macro_spending",
                        {
                            "iter": int(tick.iteration),
                            "t": round(float(now), 2),
                            "action": "wall_main_priority",
                            "main_wall_occupied": int(main_occupied),
                            "main_wall_target": int(main_target),
                        },
                    )
                return TaskResult.running("wall_main_priority_issued")
        elif wall.action == "build_natural":
            if try_build_next_wall_depot(bot, plan=nat_plan):
                if self.log is not None:
                    self.log.emit(
                        "macro_spending",
                        {
                            "iter": int(tick.iteration),
                            "t": round(float(now), 2),
                            "action": "wall_natural_priority",
                            "natural_wall_occupied": int(nat_occupied),
                            "natural_wall_target": int(nat_target),
                            "natural_inferred_slots": bool(nat_plan.inferred),
                        },
                    )
                return TaskResult.running("wall_natural_priority_issued")
            if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
                self.log.emit(
                    "macro_spending",
                    {
                        "iter": int(tick.iteration),
                        "t": round(float(now), 2),
                        "action": "wall_natural_waiting_slot",
                        "natural_wall_occupied": int(nat_occupied),
                        "natural_wall_target": int(nat_target),
                    },
                )
            return TaskResult.running("wall_natural_waiting_slot")
        elif wall.action == "natural_slots_missing":
            if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
                self.log.emit(
                    "macro_spending",
                    {
                        "iter": int(tick.iteration),
                        "t": round(float(now), 2),
                        "action": "wall_natural_slots_missing",
                        "natural_wall_slots": int(nat_total),
                    },
                )
            return TaskResult.running("wall_natural_slots_missing")

        if wall.action == "natural_waiting_slot":
            # Strict behavior: do not place generic depots while natural wall is pending.
            if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
                self.log.emit(
                    "macro_spending",
                    {
                        "iter": int(tick.iteration),
                        "t": round(float(now), 2),
                        "action": "wall_natural_waiting_slot",
                        "natural_wall_occupied": int(nat_occupied),
                        "natural_wall_target": int(nat_target),
                    },
                )
            return TaskResult.running("wall_natural_waiting_slot")

        target_bases = self._target_bases(attention=attention, now=now, expand_bias=int(expand_bias))
        if int(army_bias) > 0:
            target_bases = min(int(target_bases), max(1, int(attention.macro.bases_total)))
        if rush_active:
            # During rush response, do not greed expansions.
            target_bases = min(int(target_bases), 2)
        gas_target = max(0, int(attention.macro.bases_total) * 2)
        army_comp = self._army_comp_for_controllers(now)

        plan = MacroPlan()
        plan.add(AutoSupply(base_location=bot.start_location))
        plan.add(GasBuildingController(to_count=int(gas_target)))
        plan.add(ExpansionController(to_count=int(target_bases)))
        plan.add(
            ProductionController(
                army_composition_dict=army_comp,
                base_location=bot.start_location,
            )
        )

        bot.register_behavior(plan)

        if self.log is not None and (int(tick.iteration) % self.log_every_iters == 0):
            self.log.emit(
                "macro_spending",
                {
                    "iter": int(tick.iteration),
                    "t": round(float(now), 2),
                    "target_bases": int(target_bases),
                    "gas_target": int(gas_target),
                    "minerals": int(attention.economy.minerals),
                    "morph_pending": int(pending_morph),
                    "morph_target_kind": str(target_kind),
                    "reserve_minerals": int(reserve_m),
                    "reserve_gas": int(reserve_g),
                    "priority_reserve_unit": str(prio_unit),
                    "priority_reserve_minerals": int(prio_m),
                    "priority_reserve_gas": int(prio_g),
                    "rush_state": str(rush_state),
                    "rush_active": bool(rush_active),
                    "parity_overall": str(parity_overall),
                    "parity_econ": str(parity_econ),
                    "parity_army": str(parity_army),
                    "parity_expand_bias": int(expand_bias),
                    "parity_army_bias": int(army_bias),
                },
            )

        return TaskResult.running("spending_plan_registered")

