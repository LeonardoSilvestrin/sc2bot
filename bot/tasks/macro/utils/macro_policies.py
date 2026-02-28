from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.tasks.macro.utils.state_store import MacroStateStore
from bot.tasks.macro.utils.wall_mapper import WallDepotPlan, get_wall_depot_plan, try_build_next_wall_depot


@dataclass(frozen=True)
class WallDecision:
    action: str
    main_plan: WallDepotPlan
    natural_plan: WallDepotPlan
    main_target: int
    natural_target: int


@dataclass
class WallPlacementPolicy:
    state: MacroStateStore
    main_wall_target: int = 2
    natural_wall_target: int = 2

    @staticmethod
    def own_natural(bot) -> Point2:
        try:
            return bot.mediator.get_own_nat
        except Exception:
            try:
                return bot.start_location.towards(bot.game_info.map_center, 12.0)
            except Exception:
                return bot.start_location

    def evaluate(self, bot, *, now: float) -> WallDecision:
        main_plan = get_wall_depot_plan(
            bot,
            base_location=bot.start_location,
            desired_slots=int(self.main_wall_target),
            infer_when_missing=False,
        )
        nat_pos = self.own_natural(bot)
        natural_plan = get_wall_depot_plan(
            bot,
            base_location=nat_pos,
            desired_slots=int(self.natural_wall_target),
            infer_when_missing=True,
        )

        main_target = min(int(self.main_wall_target), int(main_plan.total))
        natural_target = min(int(self.natural_wall_target), int(natural_plan.total))
        natural_slots_missing = int(natural_plan.total) <= 0

        self.state.set_wall_status(
            now=now,
            main_total=int(main_plan.total),
            main_occupied=int(main_plan.occupied),
            main_target=int(main_target),
            natural_total=int(natural_plan.total),
            natural_occupied=int(natural_plan.occupied),
            natural_target=int(natural_target),
            natural_inferred=bool(natural_plan.inferred),
        )

        if main_target > 0 and int(main_plan.occupied) < main_target:
            return WallDecision("build_main", main_plan, natural_plan, int(main_target), int(natural_target))
        if natural_target > 0 and int(natural_plan.occupied) < natural_target:
            return WallDecision("build_natural", main_plan, natural_plan, int(main_target), int(natural_target))
        if natural_slots_missing:
            return WallDecision("natural_slots_missing", main_plan, natural_plan, int(main_target), int(natural_target))
        if natural_target > 0 and int(natural_plan.occupied) < natural_target:
            return WallDecision("natural_waiting_slot", main_plan, natural_plan, int(main_target), int(natural_target))
        return WallDecision("none", main_plan, natural_plan, int(main_target), int(natural_target))


@dataclass
class RushFortifyPolicy:
    state: MacroStateStore

    @staticmethod
    def own_natural(bot) -> Point2:
        return WallPlacementPolicy.own_natural(bot)

    async def fortify_natural(self, bot, *, now: float) -> dict:
        nat = self.own_natural(bot)
        issued = {"depots": 0, "bunkers": 0}

        try:
            depots_near_nat = int(
                bot.structures.of_type({U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED}).closer_than(11.0, nat).amount
            )
        except Exception:
            depots_near_nat = 0
        try:
            bunkers_near_nat = int(bot.structures.of_type({U.BUNKER}).closer_than(12.0, nat).amount)
        except Exception:
            bunkers_near_nat = 0

        pending_depot = int(bot.already_pending(U.SUPPLYDEPOT))
        pending_bunker = int(bot.already_pending(U.BUNKER))

        if depots_near_nat + pending_depot < 2 and bot.can_afford(U.SUPPLYDEPOT):
            rush_nat_plan = get_wall_depot_plan(
                bot,
                base_location=nat,
                desired_slots=2,
                infer_when_missing=True,
            )
            if try_build_next_wall_depot(bot, plan=rush_nat_plan):
                issued["depots"] += 1

        if bunkers_near_nat + pending_bunker < 1 and bot.can_afford(U.BUNKER):
            try:
                bunker_anchor = nat.towards(bot.game_info.map_center, 4.0)
                if await bot.build(U.BUNKER, near=bunker_anchor, max_distance=9, random_alternative=True):
                    issued["bunkers"] += 1
            except Exception:
                pass

        self.state.set_rush_fortify_last(now=now, depots=int(issued["depots"]), bunkers=int(issued["bunkers"]))
        return issued
