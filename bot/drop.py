#drop.py
from __future__ import annotations

from typing import Any, Optional

from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from .api import BotAPI
from .state import BotState
from .utils import game_loop, snap


class Drop:
    """
    Simple medivac drop state machine.
    - waits for 1 medivac + >= 8 marines
    - loads up to 8 marines
    - moves to staging then drop
    - unloads, stims, attacks enemy main
    """

    def __init__(self, bot: Any, state: BotState, debug: bool = True):
        self.bot = bot
        self.api = BotAPI(bot)
        self.state = state
        self.debug = debug

        # Tunables
        self.min_marines = 8
        self.load_count = 8
        self.move_eps = 3.0
        self.ground_radius = 12.0

    def _enemy_main(self) -> Optional[Point2]:
        locs = getattr(self.bot, "enemy_start_locations", None)
        if not locs:
            return None
        return locs[0]

    def _compute_positions(self) -> tuple[Optional[Point2], Optional[Point2]]:
        enemy_main = self._enemy_main()
        if enemy_main is None:
            return None, None

        center = self.bot.game_info.map_center
        staging = snap(enemy_main.towards(center, 12))
        drop_pos = snap(enemy_main.towards(center, 6))
        return staging, drop_pos

    def _sorted_by_distance(self, units, ref_unit):
        if hasattr(units, "sorted_by_distance_to"):
            try:
                return units.sorted_by_distance_to(ref_unit)
            except Exception:
                pass
        # fallback list sort
        try:
            return sorted(list(units), key=lambda u: u.distance_to(ref_unit))
        except Exception:
            return list(units)

    def _closer_than(self, units, dist: float, pos: Point2):
        return self.api.closer_than(units, dist, pos)

    async def step(self) -> None:
        now = game_loop(self.bot)

        medivacs = self.api.ready(U.MEDIVAC)
        marines = self.api.ready(U.MARINE)

        if (not self.api.exists(medivacs)) or (self.api.amount(marines) < self.min_marines):
            self.state.drop.in_progress = False
            return

        med = self.api.first(medivacs)
        if med is None:
            self.state.drop.in_progress = False
            return

        staging, drop_pos = self._compute_positions()
        if staging is None or drop_pos is None:
            return

        d = self.state.drop
        if not d.in_progress:
            d.in_progress = True
            d.loaded = False
            d.dropped = False
            d.staging_pos = staging
            d.target_pos = drop_pos

        # --- LOAD PHASE ---
        if not d.loaded:
            candidates = self._sorted_by_distance(marines, med)
            loaded_any = False

            for m in candidates[: self.load_count]:
                if med.distance_to(m) > 10:
                    continue
                try:
                    await self.bot.do(med(A.LOAD, m))
                    loaded_any = True
                except Exception:
                    continue

            if getattr(med, "cargo_used", 0) > 0 or loaded_any:
                d.loaded = True
            return

        # --- MOVE / UNLOAD PHASE ---
        if d.loaded and not d.dropped:
            assert d.staging_pos is not None and d.target_pos is not None

            if med.distance_to(d.staging_pos) > self.move_eps:
                await self.bot.do(med.move(d.staging_pos))
                return

            if med.distance_to(d.target_pos) > self.move_eps:
                await self.bot.do(med.move(d.target_pos))
                return

            try:
                await self.bot.do(med(A.UNLOADALLAT_MEDIVAC, d.target_pos))
            except Exception:
                return

            d.dropped = True
            self.state.mark_try("drop", now)
            return

        # --- POST-DROP MICRO ---
        if d.dropped:
            enemy_main = self._enemy_main()
            if enemy_main is None or d.target_pos is None:
                return

            ground = self._closer_than(marines, self.ground_radius, d.target_pos)

            for m in ground:
                try:
                    if m.has_ability(A.EFFECT_STIM):
                        await self.bot.do(m(A.EFFECT_STIM))
                except Exception:
                    pass
                await self.bot.do(m.attack(enemy_main))

            if getattr(med, "is_idle", False) and d.staging_pos is not None:
                await self.bot.do(med.move(d.staging_pos))