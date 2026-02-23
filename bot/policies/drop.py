#bot/policies/drop.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.unit import Unit


class DropPhase(str, Enum):
    IDLE = "IDLE"
    STAGING = "STAGING"
    LOADING = "LOADING"
    FLYING = "FLYING"
    DROPPING = "DROPPING"
    FIGHTING = "FIGHTING"
    EVAC = "EVAC"
    RESET = "RESET"


@dataclass
class DropState:
    phase: DropPhase = DropPhase.IDLE
    medivac_tag: Optional[int] = None
    started_at: float = 0.0
    last_transition_at: float = 0.0
    target_pos: Optional[Point2] = None
    staging_pos: Optional[Point2] = None


class DropPolicy:
    """
    Drop básico e robusto (estado + timeout).
    Meta: bot fazer algo perigoso *sem travar*.

    Premissas:
      - Terran
      - Medivac + Marines
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        min_marines: int = 8,
        load_count: int = 8,
        stage_radius: float = 10.0,
        phase_timeout: float = 35.0,
        fight_time: float = 10.0,
    ):
        self.enabled = enabled
        self.min_marines = min_marines
        self.load_count = load_count
        self.stage_radius = stage_radius
        self.phase_timeout = phase_timeout
        self.fight_time = fight_time
        self.state = DropState()

    def _enemy_main_like(self, bot) -> Optional[Point2]:
        # Melhor esforço:
        # - se o bot já viu enemy_start_locations, usa o primeiro
        try:
            if bot.enemy_start_locations:
                return bot.enemy_start_locations[0]
        except Exception:
            pass
        return None

    def _default_staging(self, bot) -> Optional[Point2]:
        # staging perto da natural/main, evitando ficar no meio do mapa
        try:
            if bot.townhalls:
                th = bot.townhalls.closest_to(bot.start_location)
                return th.position.towards(bot.game_info.map_center, 6)
        except Exception:
            pass
        return bot.start_location.towards(bot.game_info.map_center, 6)

    def _get_medivac(self, bot) -> Optional[Unit]:
        if self.state.medivac_tag:
            m = bot.units.find_by_tag(self.state.medivac_tag)
            if m and m.is_alive:
                return m

        medivacs = bot.units(U.MEDIVAC)
        if medivacs.amount == 0:
            return None

        # escolhe um medivac relativamente "livre"
        m = medivacs.sorted(lambda x: x.cargo_used)[0]
        self.state.medivac_tag = m.tag
        return m

    def _phase_timed_out(self, bot) -> bool:
        if self.state.phase in (DropPhase.IDLE, DropPhase.RESET):
            return False
        return (bot.time - self.state.last_transition_at) > self.phase_timeout

    def _transition(self, bot, phase: DropPhase) -> None:
        self.state.phase = phase
        if self.state.started_at == 0.0:
            self.state.started_at = bot.time
        self.state.last_transition_at = bot.time

    def evaluate(self, bot) -> bool:
        if not self.enabled:
            return False

        # Só tenta se tiver recursos mínimos
        if bot.units(U.MEDIVAC).amount < 1:
            return False

        marines = bot.units(U.MARINE)
        if marines.amount < self.min_marines:
            return False

        # precisa ter target
        target = self._enemy_main_like(bot)
        if not target:
            return False

        return True

    async def act(self, bot) -> bool:
        """
        Retorna True se emitiu comando.
        """
        if not self.evaluate(bot):
            # Se não dá pra dropar, reseta state pra não ficar "preso"
            self.state = DropState()
            return False

        if self._phase_timed_out(bot):
            self._transition(bot, DropPhase.RESET)

        target = self._enemy_main_like(bot)
        staging = self._default_staging(bot)
        if not target or not staging:
            return False

        self.state.target_pos = target
        self.state.staging_pos = staging

        m = self._get_medivac(bot)
        if not m:
            return False

        marines = bot.units(U.MARINE)
        if marines.amount == 0:
            return False

        issued = False

        # -----------------------
        # State machine
        # -----------------------
        if self.state.phase == DropPhase.IDLE:
            self._transition(bot, DropPhase.STAGING)

        if self.state.phase == DropPhase.STAGING:
            # junta marines e medivac no staging
            pack = marines.closest_n_units(staging, self.load_count)
            for u in pack:
                if u.distance_to(staging) > self.stage_radius:
                    u.move(staging)
                    issued = True

            if m.distance_to(staging) > self.stage_radius:
                m.move(staging)
                issued = True

            # pronto pra carregar se o pack estiver perto
            if pack.amount >= self.load_count and pack.center.distance_to(staging) <= self.stage_radius:
                self._transition(bot, DropPhase.LOADING)

        if self.state.phase == DropPhase.LOADING:
            pack = marines.closest_n_units(m.position, self.load_count)

            # se medivac já cheio o suficiente, parte
            if m.cargo_used >= self.load_count:
                self._transition(bot, DropPhase.FLYING)
            else:
                # manda os marines entrarem no medivac (load)
                # cuidado: python-sc2 faz o order no próprio marine com AbilityId.LOAD_MEDIVAC
                for u in pack:
                    if u.is_alive and u.distance_to(m) <= 5:
                        u( A.LOAD_MEDIVAC, m )
                        issued = True
                    elif u.is_alive:
                        u.move(m.position)
                        issued = True

        if self.state.phase == DropPhase.FLYING:
            # vai para um ponto próximo do alvo pra evitar cair em cima de torre/canhões
            approach = target.towards(bot.game_info.map_center, -6)
            if m.distance_to(approach) > 4:
                m.move(approach)
                issued = True
            else:
                self._transition(bot, DropPhase.DROPPING)

        if self.state.phase == DropPhase.DROPPING:
            # unload all
            if m.cargo_used > 0:
                m( A.UNLOADALLAT_MEDIVAC, m.position.towards(target, 3) )
                issued = True
            self._transition(bot, DropPhase.FIGHTING)

        if self.state.phase == DropPhase.FIGHTING:
            # manda marines atacar algo por um tempo curto e depois evacuar
            fight_elapsed = bot.time - self.state.last_transition_at
            local_marines = bot.units(U.MARINE).closer_than(18, m.position)

            # Se não viu nada, ataca o target "as cegas"
            if bot.enemy_units.closer_than(18, m.position).amount > 0:
                enemy = bot.enemy_units.closer_than(18, m.position).closest_to(m.position)
                for u in local_marines:
                    if u.is_idle:
                        u.attack(enemy)
                        issued = True
            else:
                for u in local_marines:
                    if u.is_idle:
                        u.attack(target)
                        issued = True

            if fight_elapsed >= self.fight_time:
                self._transition(bot, DropPhase.EVAC)

        if self.state.phase == DropPhase.EVAC:
            # tenta recolher os marines próximos
            local_marines = bot.units(U.MARINE).closer_than(10, m.position)
            if m.cargo_used < m.cargo_max and local_marines.amount > 0:
                for u in local_marines:
                    if u.is_alive and u.distance_to(m) <= 5:
                        u( A.LOAD_MEDIVAC, m )
                        issued = True
                    elif u.is_alive:
                        u.move(m.position)
                        issued = True

            # volta pra staging e reseta quando chegar
            if m.distance_to(staging) > 6:
                m.move(staging)
                issued = True
            else:
                self._transition(bot, DropPhase.RESET)

        if self.state.phase == DropPhase.RESET:
            # reset total para permitir um próximo drop depois
            self.state = DropState()
            issued = True

        return issued