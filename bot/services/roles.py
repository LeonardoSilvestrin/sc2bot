#bot/services/roles.py
from __future__ import annotations

from dataclasses import dataclass

from ares.consts import UnitRole
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2
from sc2.unit import Unit


@dataclass(frozen=True)
class RoleService:
    """
    Wrapper mínimo e direto do UnitRoleManager via mediator.

    Regra: sem fallback.
    Se mediator não tiver o método esperado, crasha.
    """

    bot: object  # AresBot / BotAI

    def assign(self, *, unit: Unit, role: UnitRole, remove_from_squad: bool = True) -> None:
        self.bot.mediator.assign_role(tag=unit.tag, role=role, remove_from_squad=remove_from_squad)

    def get_scout_workers(self):
        return self.bot.mediator.get_units_from_role(role=UnitRole.BUILD_RUNNER_SCOUT, unit_type=U.SCV)

    def request_worker_scout(self, *, target_position: Point2) -> Unit:
        """
        Seleciona 1 worker e marca como scout.

        - Usa select_worker do Ares (não é python-sc2 puro).
        - Atribui UnitRole.BUILD_RUNNER_SCOUT.
        """
        worker: Unit = self.bot.mediator.select_worker(target_position=target_position)
        self.assign(unit=worker, role=UnitRole.BUILD_RUNNER_SCOUT, remove_from_squad=True)
        return worker