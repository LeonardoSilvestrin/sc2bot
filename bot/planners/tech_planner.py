from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId as Up

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.mind.awareness import Awareness, K
from bot.planners.utils.base_planner import BasePlanner
from bot.planners.utils.proposals import Proposal, TaskSpec
from bot.tasks.macro.tech_tick import MacroTechTick


@dataclass
class TechPlanner(BasePlanner):
    """
    Planner decides tech/upgrades and publishes an explicit tech plan.
    Task only executes the chosen plan.
    """

    planner_id: str = "tech_planner"
    score: int = 42
    start_delay_after_opening_s: float = 60.0
    fallback_start_after_game_s: float = 150.0
    bypass_delay_for_banshee_pressure: bool = True
    plan_ttl_s: float = 8.0
    log_every_iters: int = 22
    log: DevLogger | None = None

    def _pid(self) -> str:
        return self.proposal_id("macro_tech")

    @staticmethod
    def _urgent_banshee_tech(*, awareness: Awareness, now: float) -> bool:
        reserve_unit = str(awareness.mem.get(K("macro", "desired", "reserve_unit"), now=now, default="") or "")
        if reserve_unit == "BANSHEE":
            return True
        priority_units = list(awareness.mem.get(K("macro", "desired", "priority_units"), now=now, default=[]) or [])
        if any(str(u) == "BANSHEE" for u in priority_units):
            return True
        comp = dict(awareness.mem.get(K("macro", "desired", "comp"), now=now, default={}) or {})
        try:
            return float(comp.get("BANSHEE", 0.0) or 0.0) >= 0.08
        except Exception:
            return False

    @staticmethod
    def _unit_count_with_pending(bot, unit_type) -> int:
        try:
            ready = int(bot.units.of_type(unit_type).ready.amount)
        except Exception:
            ready = 0
        try:
            pending = int(bot.already_pending(unit_type) or 0)
        except Exception:
            pending = 0
        return int(ready + pending)

    def _upgrade_is_unlocked_by_army(self, bot, *, name: str, awareness: Awareness, now: float) -> bool:
        n = str(name)
        marines = self._unit_count_with_pending(bot, U.MARINE)
        marauders = self._unit_count_with_pending(bot, U.MARAUDER)
        tanks = self._unit_count_with_pending(bot, U.SIEGETANK)
        hellions = self._unit_count_with_pending(bot, U.HELLION)
        air_core = (
            self._unit_count_with_pending(bot, U.BANSHEE)
            + self._unit_count_with_pending(bot, U.MEDIVAC)
            + self._unit_count_with_pending(bot, U.VIKINGFIGHTER)
            + self._unit_count_with_pending(bot, U.LIBERATOR)
        )

        # Let cloak start as soon as banshee path is truly active.
        if n == "BANSHEECLOAK":
            if self._unit_count_with_pending(bot, U.BANSHEE) >= 1:
                return True
            reserve_unit = str(awareness.mem.get(K("macro", "desired", "reserve_unit"), now=now, default="") or "")
            if reserve_unit == "BANSHEE":
                return True
            priority_units = list(awareness.mem.get(K("macro", "desired", "priority_units"), now=now, default=[]) or [])
            return any(str(u) == "BANSHEE" for u in priority_units)

        if n == "STIMPACK":
            return (marines + marauders) >= 8
        if n == "SHIELDWALL":
            return marines >= 10
        if n == "PUNISHERGRENADES":
            return marauders >= 2
        if n in {"TERRANINFANTRYWEAPONSLEVEL1", "TERRANINFANTRYARMORSLEVEL1"}:
            return (marines + marauders) >= 8
        if n in {"TERRANINFANTRYWEAPONSLEVEL2", "TERRANINFANTRYARMORSLEVEL2"}:
            return (marines + marauders) >= 14
        if n in {"TERRANINFANTRYWEAPONSLEVEL3", "TERRANINFANTRYARMORSLEVEL3"}:
            return (marines + marauders) >= 20

        if n in {"TERRANVEHICLEWEAPONSLEVEL1", "TERRANVEHICLEANDSHIPARMORSLEVEL1"}:
            return (tanks + hellions) >= 4
        if n in {"TERRANVEHICLEWEAPONSLEVEL2", "TERRANVEHICLEANDSHIPARMORSLEVEL2"}:
            return (tanks + hellions) >= 8
        if n in {"TERRANVEHICLEWEAPONSLEVEL3", "TERRANVEHICLEANDSHIPARMORSLEVEL3"}:
            return (tanks + hellions) >= 12

        if n in {"TERRANSHIPWEAPONSLEVEL1"}:
            return air_core >= 3
        if n in {"TERRANSHIPWEAPONSLEVEL2"}:
            return air_core >= 6
        if n in {"TERRANSHIPWEAPONSLEVEL3"}:
            return air_core >= 9

        return True

    @staticmethod
    def _upgrade_names_from_comp(*, comp: dict[str, float], reserve_unit: str) -> list[str]:
        infantry = float(comp.get("MARINE", 0.0)) + float(comp.get("MARAUDER", 0.0)) + float(comp.get("GHOST", 0.0))
        mech = float(comp.get("HELLION", 0.0)) + float(comp.get("SIEGETANK", 0.0)) + float(comp.get("CYCLONE", 0.0)) + float(comp.get("THOR", 0.0))
        air = float(comp.get("MEDIVAC", 0.0)) + float(comp.get("VIKINGFIGHTER", 0.0)) + float(comp.get("LIBERATOR", 0.0)) + float(comp.get("BANSHEE", 0.0)) + float(comp.get("RAVEN", 0.0))
        banshee_pressure = float(comp.get("BANSHEE", 0.0) or 0.0) >= 0.08 or str(reserve_unit) == "BANSHEE"

        names: list[str] = []
        if banshee_pressure:
            names.extend(["BANSHEECLOAK"])
        if infantry >= 0.35:
            names.extend(
                [
                    "STIMPACK",
                    "SHIELDWALL",
                    "PUNISHERGRENADES",
                    "TERRANINFANTRYWEAPONSLEVEL1",
                    "TERRANINFANTRYARMORSLEVEL1",
                    "TERRANINFANTRYWEAPONSLEVEL2",
                    "TERRANINFANTRYARMORSLEVEL2",
                    "TERRANINFANTRYWEAPONSLEVEL3",
                    "TERRANINFANTRYARMORSLEVEL3",
                ]
            )
        if mech >= 0.30:
            names.extend(
                [
                    "TERRANVEHICLEWEAPONSLEVEL1",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL1",
                    "TERRANVEHICLEWEAPONSLEVEL2",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL2",
                    "TERRANVEHICLEWEAPONSLEVEL3",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL3",
                ]
            )
        if air >= 0.25:
            names.extend(
                [
                    "TERRANSHIPWEAPONSLEVEL1",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL1",
                    "TERRANSHIPWEAPONSLEVEL2",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL2",
                    "TERRANSHIPWEAPONSLEVEL3",
                    "TERRANVEHICLEANDSHIPARMORSLEVEL3",
                ]
            )
        if not names:
            names.extend(
                [
                    "STIMPACK",
                    "SHIELDWALL",
                    "TERRANINFANTRYWEAPONSLEVEL1",
                    "TERRANINFANTRYARMORSLEVEL1",
                ]
            )

        seen: set[str] = set()
        out: list[str] = []
        for name in names:
            s = str(name)
            if s in seen:
                continue
            if getattr(Up, s, None) is None:
                continue
            seen.add(s)
            out.append(s)
        return out

    def _publish_tech_plan(self, bot, *, awareness: Awareness, now: float) -> list[str]:
        comp = dict(awareness.mem.get(K("macro", "desired", "comp"), now=now, default={}) or {})
        reserve_unit = str(awareness.mem.get(K("macro", "desired", "reserve_unit"), now=now, default="") or "")
        raw_upgrades = self._upgrade_names_from_comp(comp=comp, reserve_unit=reserve_unit)
        upgrades = [u for u in raw_upgrades if self._upgrade_is_unlocked_by_army(bot, name=str(u), awareness=awareness, now=now)]

        reserve_m = 0
        reserve_g = 0
        reserve_name = ""
        for name in upgrades:
            up = getattr(Up, str(name), None)
            if up is None:
                continue
            try:
                pending = float(bot.already_pending_upgrade(up) or 0.0)
                if pending >= 1.0:
                    continue
            except Exception:
                pass
            try:
                cost = bot.calculate_cost(up)
                reserve_m = int(getattr(cost, "minerals", 0) or 0)
                reserve_g = int(getattr(cost, "vespene", 0) or 0)
                reserve_name = str(name)
                break
            except Exception:
                continue

        ttl = float(self.plan_ttl_s)
        awareness.mem.set(K("macro", "tech", "plan", "upgrades"), value=list(upgrades), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "tech", "plan", "upgrades_raw"), value=list(raw_upgrades), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "tech", "plan", "reserve_minerals"), value=int(reserve_m), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "tech", "plan", "reserve_gas"), value=int(reserve_g), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "tech", "plan", "reserve_name"), value=str(reserve_name), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "tech", "plan", "updated_at"), value=float(now), now=now, ttl=None)

        # Shared explicit reserve contract used by production.
        awareness.mem.set(K("macro", "reserve", "tech", "minerals"), value=int(reserve_m), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "reserve", "tech", "gas"), value=int(reserve_g), now=now, ttl=ttl)
        awareness.mem.set(K("macro", "reserve", "tech", "name"), value=str(reserve_name), now=now, ttl=ttl)
        return upgrades

    def propose(self, bot, *, awareness: Awareness, attention: Attention) -> list[Proposal]:
        now = float(attention.time)
        pid = self._pid()
        upgrades = self._publish_tech_plan(bot, awareness=awareness, now=now)
        # Record opening start reference once so delayed start can work
        # even when BuildRunner stalls and opening_done never flips.
        opening_started_at = awareness.mem.get(K("macro", "opening", "started_at"), now=now, default=None)
        if opening_started_at is None:
            awareness.mem.set(K("macro", "opening", "started_at"), value=float(now), now=now, ttl=None)
            opening_started_at = float(now)

        opening_done_at = awareness.mem.get(K("macro", "opening", "done_at"), now=now, default=None)
        if bool(attention.macro.opening_done) and opening_done_at is None:
            awareness.mem.set(K("macro", "opening", "done_at"), value=float(now), now=now, ttl=None)
            opening_done_at = float(now)

        urgent_banshee_tech = self._urgent_banshee_tech(awareness=awareness, now=now)
        bypass_for_banshee = bool(self.bypass_delay_for_banshee_pressure) and bool(urgent_banshee_tech)
        if not bypass_for_banshee:
            if opening_done_at is not None:
                if (float(now) - float(opening_done_at)) < float(self.start_delay_after_opening_s):
                    return []
            else:
                # Fallback gate when opening never completes: start tech after
                # a conservative elapsed game-time threshold.
                if (float(now) - float(opening_started_at)) < float(self.fallback_start_after_game_s):
                    return []

        if self.is_proposal_running(awareness=awareness, proposal_id=pid, now=now):
            return []

        def _factory(mission_id: str) -> MacroTechTick:
            return MacroTechTick(awareness=awareness, log=self.log, log_every_iters=int(self.log_every_iters))

        out = self.make_single_task_proposal(
            proposal_id=pid,
            domain="MACRO_TECH",
            score=int(self.score),
            task_spec=TaskSpec(task_id="macro_tech", task_factory=_factory, unit_requirements=[]),
            lease_ttl=None,
            cooldown_s=0.0,
            risk_level=0,
            allow_preempt=True,
        )

        opening_done_log = None if opening_done_at is None else round(float(opening_done_at), 2)
        opening_started_log = None if opening_started_at is None else round(float(opening_started_at), 2)
        self.emit_planner_proposed(
            {
                "count": len(out),
                "opening_done_at": opening_done_log,
                "opening_started_at": opening_started_log,
                "delay_s": float(self.start_delay_after_opening_s),
                "fallback_start_after_game_s": float(self.fallback_start_after_game_s),
                "urgent_banshee_tech": bool(urgent_banshee_tech),
                "upgrade_count": int(len(upgrades)),
            }
        )
        return out
