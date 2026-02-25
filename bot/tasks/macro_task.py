# bot/tasks/macro.py
from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.upgrade_id import UpgradeId as Up

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskTick


@dataclass
class MacroOpeningTick(BaseTask):
    """
    Opening macro minimalista:
      - SCV contínuo até scv_cap
      - Não mexe em tech/expand
    Rodado pelo Planner enquanto o opening do YAML não finalizou.
    """

    log: DevLogger | None = None
    log_every_iters: int = 22
    scv_cap: int = 60

    def __init__(
        self,
        *,
        log: DevLogger | None = None,
        log_every_iters: int = 22,
        scv_cap: int = 60,
    ):
        super().__init__(task_id="macro_opening_scv_only", domain="MACRO", commitment=10)
        self.log = log
        self.log_every_iters = int(log_every_iters)
        self.scv_cap = int(scv_cap)

    def _workers(self, bot) -> int:
        try:
            return int(bot.workers.amount)
        except Exception:
            return 0

    def _supply_left(self, bot) -> int:
        try:
            return int(getattr(bot, "supply_left", 0) or 0)
        except Exception:
            return 0

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        try:
            ths = bot.townhalls.ready
        except Exception:
            ths = None
        if not ths or ths.amount == 0:
            self._paused("no_townhalls")
            return False

        if self._supply_left(bot) <= 0:
            self._paused("no_supply")
            return False

        if not bot.can_afford(U.SCV):
            self._paused("cant_afford_scv")
            return False

        idle_ths = ths.idle
        if idle_ths.amount == 0:
            self._active("townhalls_busy")
            return False

        if self._workers(bot) >= self.scv_cap:
            self._active("scv_cap")
            return False

        idle_ths.first.train(U.SCV)
        self._active("training_scv_opening")
        return True


@dataclass
class MacroBio2BaseTick(BaseTask):
    """
    BIO_2BASE Macro v0.1 (pós-opening):
      - SCV contínuo (até cap simples).
      - Barracks por base: 1->1, 2->3, 3->5.
      - 1 TechLab total (prioriza), resto Reactor (best-effort; sem microgerenciar).
      - Stim, 1 Factory, 1 Starport.
      - Medivac até 2.
      - Expande até 3 bases quando tiver grana e safe.
      - Supply depot se estiver travando (se AutoSupply do Ares falhar).
    """

    log: DevLogger | None = None
    log_every_iters: int = 22

    scv_cap: int = 60
    target_bases: int = 3

    backoff_urgency: int = 60  # se threatened+urgência alta, não gasta em expand/tech

    def __init__(
        self,
        *,
        log: DevLogger | None = None,
        log_every_iters: int = 22,
        scv_cap: int = 60,
        target_bases: int = 3,
        backoff_urgency: int = 60,
    ):
        super().__init__(task_id="macro_bio_2base_v01", domain="MACRO", commitment=15)
        self.log = log
        self.log_every_iters = int(log_every_iters)
        self.scv_cap = int(scv_cap)
        self.target_bases = int(target_bases)
        self.backoff_urgency = int(backoff_urgency)

    # -----------------------
    # Helpers
    # -----------------------
    def _count(self, bot, unit_type: U) -> int:
        try:
            return int(bot.structures(unit_type).ready.amount)
        except Exception:
            return 0

    def _pending(self, bot, unit_type: U) -> int:
        try:
            return int(bot.already_pending(unit_type) or 0)
        except Exception:
            return 0

    def _townhalls_ready(self, bot) -> int:
        try:
            return int(bot.townhalls.ready.amount)
        except Exception:
            return 0

    def _workers(self, bot) -> int:
        try:
            return int(bot.workers.amount)
        except Exception:
            return 0

    def _supply_left(self, bot) -> int:
        try:
            return int(getattr(bot, "supply_left", 0) or 0)
        except Exception:
            return 0

    def _minerals(self, bot) -> int:
        try:
            return int(getattr(bot, "minerals", 0) or 0)
        except Exception:
            return 0

    def _target_barracks(self, bases: int) -> int:
        if bases <= 1:
            return 1
        if bases == 2:
            return 3
        return 5

    async def _try_build(self, bot, unit_type: U, *, near_pos) -> bool:
        try:
            if not bot.can_afford(unit_type):
                return False
            ok = await bot.build(unit_type, near=near_pos)
            return bool(ok)
        except Exception:
            return False

    def _log_snapshot(self, bot, tick: TaskTick, attention: Attention, *, phase: str) -> None:
        if not self.log:
            return
        if int(tick.iteration) % self.log_every_iters != 0:
            return

        bases = self._townhalls_ready(bot)
        barracks = self._count(bot, U.BARRACKS)
        factory = self._count(bot, U.FACTORY)
        starport = self._count(bot, U.STARPORT)
        workers = self._workers(bot)

        try:
            supply_used = int(getattr(bot, "supply_used", 0) or 0)
            supply_cap = int(getattr(bot, "supply_cap", 0) or 0)
        except Exception:
            supply_used, supply_cap = 0, 0

        self.log.emit(
            "macro_bio_snapshot",
            {
                "iteration": int(tick.iteration),
                "time": round(float(tick.time), 2),
                "opening_done": bool(attention.macro.opening_done),
                "phase": str(phase),
                "bases": int(bases),
                "workers": int(workers),
                "barracks": int(barracks),
                "factory": int(factory),
                "starport": int(starport),
                "supply": f"{supply_used}/{supply_cap}",
                "supply_left": int(self._supply_left(bot)),
                "minerals": int(self._minerals(bot)),
                "threatened": bool(attention.combat.threatened),
                "urgency": int(attention.combat.defense_urgency),
            },
        )

    # -----------------------
    # Main tick
    # -----------------------
    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> bool:
        try:
            ths = bot.townhalls.ready
        except Exception:
            ths = None
        if not ths or ths.amount == 0:
            self._paused("no_townhalls")
            return False

        # segurança: esta task é "pós-opening"; o Planner deveria impedir.
        if not attention.macro.opening_done:
            self._paused("waiting_opening_done")
            return False

        under_heavy_threat = bool(attention.combat.threatened and int(attention.combat.defense_urgency) >= self.backoff_urgency)

        bases = self._townhalls_ready(bot)
        phase = "MIDGAME" if bases < self.target_bases else "LATEGAME"

        did_any = False

        # (0) Supply (best-effort)
        supply_left = self._supply_left(bot)

        # Se travou em supply, a prioridade é destravar.
        # Mesmo em threat moderada, depot é barato e evita soft-lock.
        if supply_left <= 0:
            if self._pending(bot, U.SUPPLYDEPOT) == 0 and not under_heavy_threat:
                try:
                    near = ths.first.position
                except Exception:
                    near = bot.start_location
                if await self._try_build(bot, U.SUPPLYDEPOT, near_pos=near):
                    did_any = True
                    self._active("build_depot_supply_block")
                    self._log_snapshot(bot, tick, attention, phase=phase)
                    return True  # emitiu comando, encerra tick
            # Se não conseguiu construir, ainda registra bloqueio
            self._active("supply_blocked")
            self._log_snapshot(bot, tick, attention, phase=phase)
            return False

        # Preventivo: tenta depot antes de travar de vez
        if supply_left < 3 and not under_heavy_threat:
            if self._pending(bot, U.SUPPLYDEPOT) == 0:
                try:
                    near = ths.first.position
                except Exception:
                    near = bot.start_location
                if await self._try_build(bot, U.SUPPLYDEPOT, near_pos=near):
                    did_any = True
                    self._active("build_depot")

        # (1) SCVs (cap simples)
        did_any = (await self._maybe_train_scv(bot)) or did_any

        # (2) Barracks scaling
        target_barracks = self._target_barracks(bases)
        current_barracks = self._count(bot, U.BARRACKS)
        pending_barracks = self._pending(bot, U.BARRACKS)

        if not under_heavy_threat and (current_barracks + pending_barracks) < target_barracks:
            try:
                near = ths.first.position
            except Exception:
                near = bot.start_location
            if await self._try_build(bot, U.BARRACKS, near_pos=near):
                did_any = True
                self._active("build_barracks")

        # (3) Units: Marine contínuo
        did_any = (self._train_from_barracks(bot) or did_any)

        # (4) Tech path: TechLab -> Stim -> Factory -> Starport -> Medivac(<=2)
        if not under_heavy_threat:
            did_any = (self._ensure_barracks_techlab(bot) or did_any)
            did_any = (self._ensure_stim(bot) or did_any)

            if (self._count(bot, U.FACTORY) + self._pending(bot, U.FACTORY)) == 0:
                try:
                    near = ths.first.position
                except Exception:
                    near = bot.start_location
                if await self._try_build(bot, U.FACTORY, near_pos=near):
                    did_any = True
                    self._active("build_factory")

            if (self._count(bot, U.STARPORT) + self._pending(bot, U.STARPORT)) == 0:
                try:
                    near = ths.first.position
                except Exception:
                    near = bot.start_location
                if await self._try_build(bot, U.STARPORT, near_pos=near):
                    did_any = True
                    self._active("build_starport")

        did_any = (self._train_medivac_upto(bot, cap=2) or did_any)

        # (5) Expand até target bases
        if not under_heavy_threat and bases < self.target_bases:
            if self._minerals(bot) >= 450 and self._workers(bot) >= (20 * bases):
                try:
                    ok = await bot.expand_now()
                except Exception:
                    ok = False
                if ok:
                    did_any = True
                    self._active("expand_now")

        if did_any:
            self._active("macro_tick")
        else:
            self._active("macro_idle")

        self._log_snapshot(bot, tick, attention, phase=phase)
        return bool(did_any)

    async def _maybe_train_scv(self, bot) -> bool:
        if self._workers(bot) >= self.scv_cap:
            return False

        try:
            ths = bot.townhalls.ready
        except Exception:
            return False
        if ths.amount == 0:
            return False

        if self._supply_left(bot) <= 0:
            return False

        if not bot.can_afford(U.SCV):
            return False

        idle_ths = ths.idle
        if idle_ths.amount == 0:
            return False

        idle_ths.first.train(U.SCV)
        return True

    def _train_from_barracks(self, bot) -> bool:
        try:
            rax = bot.structures(U.BARRACKS).ready
        except Exception:
            return False
        if rax.amount == 0:
            return False
        if self._supply_left(bot) <= 0:
            return False
        if not bot.can_afford(U.MARINE):
            return False

        did = False
        for b in rax.idle:
            try:
                b.train(U.MARINE)
                did = True
            except Exception:
                continue
        return did

    def _ensure_barracks_techlab(self, bot) -> bool:
        try:
            techlabs = bot.structures(U.BARRACKSTECHLAB).ready
            if techlabs.amount > 0:
                return False
        except Exception:
            return False

        try:
            rax = bot.structures(U.BARRACKS).ready
        except Exception:
            return False
        if rax.amount == 0:
            return False

        for b in rax:
            try:
                if b.is_idle and bot.can_afford(U.BARRACKSTECHLAB):
                    b.build(U.BARRACKSTECHLAB)
                    return True
            except Exception:
                continue
        return False

    def _ensure_stim(self, bot) -> bool:
        try:
            if bot.already_pending_upgrade(Up.STIMPACK):
                return False
        except Exception:
            pass

        try:
            techlabs = bot.structures(U.BARRACKSTECHLAB).ready
        except Exception:
            return False
        if techlabs.amount == 0:
            return False

        for tl in techlabs:
            try:
                if tl.is_idle:
                    tl.research(Up.STIMPACK)
                    return True
            except Exception:
                continue
        return False

    def _train_medivac_upto(self, bot, *, cap: int = 2) -> bool:
        try:
            medivacs = bot.units(U.MEDIVAC)
            if int(medivacs.amount) >= int(cap):
                return False
        except Exception:
            pass

        try:
            ports = bot.structures(U.STARPORT).ready
        except Exception:
            return False
        if ports.amount == 0:
            return False

        if self._supply_left(bot) <= 0:
            return False
        if not bot.can_afford(U.MEDIVAC):
            return False

        did = False
        for sp in ports.idle:
            try:
                sp.train(U.MEDIVAC)
                did = True
            except Exception:
                continue
        return did