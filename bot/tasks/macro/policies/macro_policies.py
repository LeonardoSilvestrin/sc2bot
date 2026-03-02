from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.tasks.macro.support.state_store import MacroStateStore
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
    infer_when_missing: bool = False
    min_eval_interval_s: float = 1.0
    _next_eval_at: float = 0.0
    _cached_decision: WallDecision | None = None

    @staticmethod
    def own_natural(bot) -> Point2:
        try:
            return bot.mediator.get_own_nat
        except Exception:
            return None

    def evaluate(self, bot, *, now: float) -> WallDecision:
        if self._cached_decision is not None and float(now) < float(self._next_eval_at):
            return self._cached_decision

        main_plan = get_wall_depot_plan(
            bot,
            base_location=bot.start_location,
            desired_slots=int(self.main_wall_target),
            infer_when_missing=bool(self.infer_when_missing),
        )
        main_target = min(int(self.main_wall_target), int(main_plan.total))
        nat_pos = self.own_natural(bot)
        if nat_pos is None:
            empty = WallDepotPlan(base_key=None, slots=(), total=0, occupied=0, contiguous_occupied=False, inferred=False)
            decision = WallDecision("natural_unavailable", main_plan, empty, int(main_target), 0)
            self._cached_decision = decision
            self._next_eval_at = float(now) + float(self.min_eval_interval_s)
            return decision
        natural_plan = get_wall_depot_plan(
            bot,
            base_location=nat_pos,
            desired_slots=int(self.natural_wall_target),
            infer_when_missing=bool(self.infer_when_missing),
        )

        natural_target = int(self.natural_wall_target)
        natural_slots_missing = int(natural_plan.total) < int(self.natural_wall_target)

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
            decision = WallDecision("build_main", main_plan, natural_plan, int(main_target), int(natural_target))
        elif natural_slots_missing:
            decision = WallDecision("natural_slots_missing", main_plan, natural_plan, int(main_target), int(natural_target))
        elif natural_target > 0 and int(natural_plan.occupied) < natural_target:
            decision = WallDecision("natural_waiting_slot", main_plan, natural_plan, int(main_target), int(natural_target))
        elif natural_target > 1 and not bool(natural_plan.contiguous_occupied):
            decision = WallDecision("natural_waiting_slot", main_plan, natural_plan, int(main_target), int(natural_target))
        else:
            decision = WallDecision("none", main_plan, natural_plan, int(main_target), int(natural_target))

        self._cached_decision = decision
        self._next_eval_at = float(now) + float(self.min_eval_interval_s)
        return decision


@dataclass
class RushFortifyPolicy:
    state: MacroStateStore

    @staticmethod
    def own_natural(bot) -> Point2:
        return WallPlacementPolicy.own_natural(bot)

    async def fortify_natural(self, bot, *, now: float) -> dict:
        nat = self.own_natural(bot)
        if nat is None:
            return {"depots": 0, "bunkers": 0}
        issued = {"depots": 0, "bunkers": 0}

        try:
            depots_near_nat = int(bot.structures.of_type({U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED}).closer_than(11.0, nat).amount)
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

