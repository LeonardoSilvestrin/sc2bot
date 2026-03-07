from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class LiftNaturalTask(BaseTask):
    nat_pos: Point2
    anchor_pos: Point2
    log: DevLogger | None = None

    def __init__(
        self,
        *,
        nat_pos: Point2,
        anchor_pos: Point2,
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="lift_natural", domain="DEFENSE", commitment=72)
        self.nat_pos = nat_pos
        self.anchor_pos = anchor_pos
        self.log = log

    @staticmethod
    def _nat_cc(bot, *, nat_pos: Point2):
        """Retorna o CC/OC no chão perto da natural."""
        for th in list(getattr(bot, "townhalls", []) or []):
            try:
                if float(th.distance_to(nat_pos)) <= 8.0:
                    return th
            except Exception:
                continue
        return None

    @staticmethod
    def _flying_cc_anywhere(bot):
        """Retorna qualquer CC/OC voando."""
        for s in list(getattr(bot, "structures", []) or []):
            try:
                if s.type_id in {U.COMMANDCENTERFLYING, U.ORBITALCOMMANDFLYING}:
                    return s
            except Exception:
                continue
        return None

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound()
        if bound_err is not None:
            return bound_err

        now = float(tick.time)
        nat_cc = self._nat_cc(bot, nat_pos=self.nat_pos)

        if nat_cc is None:
            # CC saiu da natural - verifica se está voando
            flying = self._flying_cc_anywhere(bot)
            if flying is None:
                self._done("nat_cc_gone_or_destroyed")
                return TaskResult.done("nat_cc_gone_or_destroyed")
            try:
                dist = float(flying.distance_to(self.anchor_pos))
                if dist > 4.0:
                    flying.move(self.anchor_pos)
                    self._active("flying_to_anchor")
                    return TaskResult.running("flying_to_anchor")
                else:
                    self._done("nat_cc_at_anchor")
                    return TaskResult.done("nat_cc_at_anchor")
            except Exception:
                self._done("nat_cc_navigation_done")
                return TaskResult.done("nat_cc_navigation_done")

        is_flying = bool(getattr(nat_cc, "is_flying", False))
        if is_flying:
            try:
                dist = float(nat_cc.distance_to(self.anchor_pos))
                if dist > 4.0:
                    nat_cc.move(self.anchor_pos)
                self._active("flying_to_anchor")
                return TaskResult.running("flying_to_anchor")
            except Exception:
                self._done("nat_cc_flying")
                return TaskResult.done("nat_cc_flying")

        # CC no chão - emite lift
        try:
            cc_type = nat_cc.type_id
            if cc_type == U.COMMANDCENTER:
                nat_cc(AbilityId.LIFT_COMMANDCENTER)
            elif cc_type == U.ORBITALCOMMAND:
                nat_cc(AbilityId.LIFT_ORBITALCOMMAND)
            else:
                self._done("nat_cc_not_liftable")
                return TaskResult.done("nat_cc_not_liftable")
            if self.log:
                self.log.emit(
                    "lift_natural_issued",
                    {
                        "t": round(float(now), 2),
                        "cc_type": str(cc_type),
                        "nat_pos": [round(self.nat_pos.x, 1), round(self.nat_pos.y, 1)],
                        "anchor": [round(self.anchor_pos.x, 1), round(self.anchor_pos.y, 1)],
                    },
                    meta={"module": "defense", "component": "defense.lift_natural"},
                )
            self._active("lifting_nat")
            return TaskResult.running("lifting_nat")
        except Exception:
            self._done("lift_failed")
            return TaskResult.done("lift_failed")
