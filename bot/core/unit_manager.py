# bot/core/unit_manager.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import inspect

from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.core.state import BotState


@dataclass
class UnitGroup:
    owner: str
    pickup: Point2
    requirements: Dict[U, int]
    assigned: Dict[U, List[int]]  # unit tags
    ready: bool = False


class UnitManager:
    """
    Responsável por:
    - reservar unidades (claims) para um "owner" (ex: drop:drop_main)
    - montar grupos (UnitGroup) com seleção consistente
    - stage/gather: mover unidades para pickup antes do task executar
    """

    def __init__(self, bot: Any, ctx: BotState, logger: Any | None = None, debug: bool = True):
        self.bot = bot
        self.ctx = ctx
        self.log = logger
        self.debug = debug
        self._iter: int = -1

    async def _do(self, cmd) -> bool:
        fn = getattr(self.bot, "do", None)
        if fn is None:
            return False
        res = fn(cmd)
        if inspect.isawaitable(res):
            await res
            return True
        if isinstance(res, bool):
            return res
        return True

    def _emit(self, event: str, payload: dict):
        if self.log:
            self.log.emit(event, payload, meta={"iter": int(getattr(self.ctx, "iteration", 0))})

    def begin_tick(self, iteration: int) -> None:
        self._iter = int(iteration)

    def _alive_unit_by_tag(self, unit_type: U, tag: int):
        units = self.bot.units(unit_type) if hasattr(self.bot, "units") else None
        if not units:
            return None
        return units.find_by_tag(int(tag))

    def _free_units(self, unit_type: U) -> List[Any]:
        units = self.bot.units(unit_type) if hasattr(self.bot, "units") else None
        if not units:
            return []
        ready = units.ready if hasattr(units, "ready") else units
        out = []
        for u in ready:
            if self.ctx.owner_of(int(u.tag)) is None:
                out.append(u)
        return out

    def _reserved_units(self, owner: str, unit_type: U) -> List[Any]:
        tags = self.ctx.owner_units.get(owner, set())
        if not tags:
            return []
        units = self.bot.units(unit_type) if hasattr(self.bot, "units") else None
        if not units:
            return []
        out = []
        for t in tags:
            u = units.find_by_tag(int(t))
            if u:
                out.append(u)
        return out

    def _ensure_owner_set(self, owner: str) -> None:
        self.ctx.owner_units.setdefault(owner, set())
        self.ctx.owner_meta.setdefault(owner, {})

    async def request_group(
        self,
        *,
        owner: str,
        pickup: Point2,
        requirements: Dict[U, int],
        soft_gather: bool = True,
        hard_gather: bool = False,
        gather_radius: float = 10.0,
        max_distance_by_type: Dict[U, float] | None = None,
    ) -> UnitGroup:
        """
        - Reserva unidades livres para cumprir requirements.
        - Mantém reservas estáveis entre ticks.
        - Emite movimentos para pickup (gather).
        - max_distance_by_type: impede "roubo" de unidades muito longe do pickup.
        """
        self._ensure_owner_set(owner)
        max_distance_by_type = max_distance_by_type or {}

        assigned: Dict[U, List[int]] = {}
        all_ok = True

        for ut, need in requirements.items():
            need = int(need)

            # 1) mantém reservas atuais vivas
            reserved = self._reserved_units(owner, ut)
            reserved_tags = [int(u.tag) for u in reserved]
            kept = reserved_tags[:need]

            # libera excedente antigo
            for t in reserved_tags[need:]:
                if self.ctx.owner_of(t) == owner:
                    self.ctx.release(t)

            # 2) completa com unidades livres
            have = len(kept)
            if have < need:
                free = self._free_units(ut)

                # filtro de distância (anti-roubo de marines do outro lado do mapa)
                maxd = float(max_distance_by_type.get(ut, 0.0) or 0.0)
                if maxd > 0.0:
                    free = [u for u in free if float(u.distance_to(pickup)) <= maxd]

                free.sort(key=lambda x: x.distance_to(pickup))

                for u in free:
                    if have >= need:
                        break
                    tag = int(u.tag)
                    self.ctx.claim(owner, tag)
                    kept.append(tag)
                    have += 1

            if len(kept) < need:
                all_ok = False

            assigned[ut] = kept

        group = UnitGroup(owner=owner, pickup=pickup, requirements=requirements, assigned=assigned, ready=all_ok)

        await self._gather_group(group, soft=soft_gather, hard=hard_gather, radius=gather_radius)

        self._emit(
            "unitmgr_group",
            {
                "owner": owner,
                "ready": bool(group.ready),
                "requirements": {k.name: int(v) for k, v in requirements.items()},
                "assigned": {k.name: [int(x) for x in v] for k, v in assigned.items()},
                "pickup": [float(pickup.x), float(pickup.y)],
                "soft_gather": bool(soft_gather),
                "hard_gather": bool(hard_gather),
            },
        )
        return group

    async def _gather_group(self, group: UnitGroup, *, soft: bool, hard: bool, radius: float) -> None:
        pickup = group.pickup

        for ut, tags in group.assigned.items():
            for t in tags:
                u = self._alive_unit_by_tag(ut, t)
                if not u:
                    if self.ctx.owner_of(int(t)) == group.owner:
                        self.ctx.release(int(t))
                    continue

                d = float(u.distance_to(pickup))
                if d <= float(radius):
                    continue

                # heurística de combate (best effort)
                in_combat = False
                if hasattr(u, "weapon_cooldown"):
                    try:
                        if float(getattr(u, "weapon_cooldown", 0.0)) > 0.0:
                            in_combat = True
                    except Exception:
                        pass
                if hasattr(u, "is_attacking"):
                    try:
                        if bool(getattr(u, "is_attacking", False)):
                            in_combat = True
                    except Exception:
                        pass

                if in_combat:
                    continue

                orders = getattr(u, "orders", None)
                has_orders = bool(orders) if orders is not None else False
                is_idle = bool(getattr(u, "is_idle", False))

                if soft and (is_idle or not has_orders):
                    await self._do(u.move(pickup))
                    continue

                if hard:
                    await self._do(u.move(pickup))
                    continue

    def release_owner(self, owner: str) -> None:
        self.ctx.release_owner(owner)
        self._emit("unitmgr_release_owner", {"owner": owner})

    def release_tags(self, owner: str, tags: Iterable[int]) -> None:
        for t in tags:
            if self.ctx.owner_of(int(t)) == owner:
                self.ctx.release(int(t))
        self._emit("unitmgr_release_tags", {"owner": owner, "tags": [int(x) for x in tags]})