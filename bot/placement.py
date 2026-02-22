# placement.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Iterable
from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.ids.ability_id import AbilityId as A

from .utils import snap


@dataclass(frozen=True)
class PlacementResult:
    pos: Point2
    strict: bool  # True se veio de query do motor / can_place, False se foi fallback fraco


class Placement:
    def __init__(self, bot, debug: bool = True):
        self.bot = bot
        self.debug = debug

    def _dbg(self, msg: str):
        if self.debug:
            print(msg)

    def _ability_for(self, unit_type: U) -> Optional[A]:
        # Terran basic build abilities (SCV)
        mapping = {
            U.COMMANDCENTER: getattr(A, "TERRANBUILD_COMMANDCENTER", None),
            U.SUPPLYDEPOT: getattr(A, "TERRANBUILD_SUPPLYDEPOT", None),
            U.REFINERY: getattr(A, "TERRANBUILD_REFINERY", None),
            U.BARRACKS: getattr(A, "TERRANBUILD_BARRACKS", None),
            U.ENGINEERINGBAY: getattr(A, "TERRANBUILD_ENGINEERINGBAY", None),
            U.BUNKER: getattr(A, "TERRANBUILD_BUNKER", None),
            U.MISSILETURRET: getattr(A, "TERRANBUILD_MISSILETURRET", None),
            U.FACTORY: getattr(A, "TERRANBUILD_FACTORY", None),
            U.STARPORT: getattr(A, "TERRANBUILD_STARPORT", None),
            U.ARMORY: getattr(A, "TERRANBUILD_ARMORY", None),
            U.FUSIONCORE: getattr(A, "TERRANBUILD_FUSIONCORE", None),
            U.SENSORTOWER: getattr(A, "TERRANBUILD_SENSORTOWER", None),
            U.GHOSTACADEMY: getattr(A, "TERRANBUILD_GHOSTACADEMY", None),
        }
        return mapping.get(unit_type)

    async def can_place_strict(self, unit_type: U, pos: Point2) -> tuple[bool, bool]:
        """
        Returns (can_place, strict_used)
        strict_used=True means we asked the engine or can_place API.
        strict_used=False means fallback to placement_grid.
        """
        pos = snap(pos)
        client = getattr(self.bot, "_client", None)
        ab = self._ability_for(unit_type)

        # 1) Best: query_building_placement (engine)
        if client is not None and hasattr(client, "query_building_placement") and ab is not None:
            try:
                res = await client.query_building_placement(ab, [pos])
                result = bool(res[0])
                if self.debug:
                    print(f"[PLACEMENT] query_building_placement result: {result}")
                return result, True
            except Exception as e:
                # silent fallback
                if self.debug:
                    print(f"[PLACEMENT] query_building_placement failed: {e}")
                pass

        # 2) Common: bot.can_place(unit_type, pos)
        if hasattr(self.bot, "can_place"):
            try:
                ok = await self.bot.can_place(unit_type, pos)
                result = bool(ok)
                if self.debug:
                    print(f"[PLACEMENT] bot.can_place({unit_type}) result: {result}")
                return result, True
            except Exception as e:
                if self.debug:
                    print(f"[PLACEMENT] bot.can_place failed: {e}")
                pass

        # 3) Weak fallback: placement_grid or assume ok
        # If we reach here, the strict methods (query_building_placement, can_place) aren't available
        # Always return True to let the actual build command determine if placement is valid
        if self.debug:
            print(f"[PLACEMENT] Using fallback (returning True)")
        return True, False

    async def find_near(self, unit_type: U, near: Point2, max_dist: int = 25) -> Optional[PlacementResult]:
        near = snap(near)

        # Optional helper in some forks: bot.find_placement
        if hasattr(self.bot, "find_placement"):
            try:
                p = await self.bot.find_placement(unit_type, near)
                if p is not None:
                    p = snap(p)
                    ok, strict = await self.can_place_strict(unit_type, p)
                    if ok:
                        return PlacementResult(p, strict)
            except Exception:
                pass

        # Ring search (Manhattan-ish ring)
        x0, y0 = int(near.x), int(near.y)
        checked_count = 0
        for r in range(0, max_dist + 1):
            # top/bottom edges
            for dx in range(-r, r + 1):
                for dy in (-r, r):
                    p = Point2((x0 + dx, y0 + dy))
                    ok, strict = await self.can_place_strict(unit_type, p)
                    checked_count += 1
                    if ok:
                        return PlacementResult(snap(p), strict)
            # left/right edges (excluding corners already tested)
            for dy in range(-r + 1, r):
                for dx in (-r, r):
                    p = Point2((x0 + dx, y0 + dy))
                    ok, strict = await self.can_place_strict(unit_type, p)
                    checked_count += 1
                    if ok:
                        return PlacementResult(snap(p), strict)

        return None

    def find_refinery_spot(self, near: Point2, max_dist: float = 15.0) -> Optional[Point2]:
        near = snap(near)

        # 1) Try built-in bot.vespene_geyser property
        geysers = getattr(self.bot, "vespene_geyser", None) or getattr(self.bot, "vespene_geysers", None)
        if geysers is not None and getattr(geysers, "exists", False):
            try:
                g = geysers.closest_to(near)
                if g.distance_to(near) <= max_dist:
                    self._dbg(f"[REFINERY] Found via bot.vespene_geyser: {snap(g.position)}")
                    return snap(g.position)
            except Exception:
                pass

        # 2) Fallback: search by unit type ID (VespeneGeyser, ProtossVespeneGeyser, ShakurasVespeneGeyser)
        candidates = []
        for tid in (U.VESPENEGEYSER, U.PROTOSSVESPENEGEYSER, U.SHAKURASVESPENEGEYSER):
            try:
                us = self.bot.units(tid)
                if getattr(us, "exists", False):
                    candidates.extend(list(us))
            except Exception:
                pass

        # 3) Fallback: search all units by name (case-insensitive, matches any geyser variant)
        if not candidates:
            au = getattr(self.bot, "all_units", None)
            if au is not None:
                for u in au:
                    name = str(getattr(u, "name", "")).lower()
                    # Match any variant: "vespenegeyser", "protossvespenegeyser", "shakurasvespenegeyser"
                    if "vespenegeyser" in name:
                        candidates.append(u)
                        self._dbg(f"[REFINERY] Found geyser by name: {getattr(u, 'name', 'Unknown')}")

        if not candidates:
            self._dbg(f"[REFINERY] No geysers found near {near}")
            return None

        # escolher o mais perto dentro do range
        best = None
        best_d = 1e18
        for g in candidates:
            gp = getattr(g, "position", None)
            if gp is None:
                x, y = getattr(g, "x", None), getattr(g, "y", None)
                if x is None or y is None:
                    continue
                gp = Point2((float(x), float(y)))
            d = gp.distance_to(near)
            if d <= max_dist and d < best_d:
                best_d = d
                best = gp

        if best is not None:
            self._dbg(f"[REFINERY] Selected geyser at {snap(best)} (distance: {best_d:.1f})")
        return snap(best) if best is not None else None

    async def find_position(self, unit_type: U, desired: Point2, max_dist: int = 25) -> Optional[PlacementResult]:
        """
        Try to find a valid building position.
        1. First try the exact desired position
        2. If that fails, use ring search around the desired position
        """
        desired = snap(desired)
        
        # Try the desired position first
        ok, strict = await self.can_place_strict(unit_type, desired)
        if ok:
            self._dbg(f"[PLACEMENT] desired position {desired} is valid")
            return PlacementResult(desired, strict)
        
        self._dbg(f"[PLACEMENT] desired position {desired} is blocked, searching nearby")
        
        # Ring search around the desired position
        result = await self.find_near(unit_type, desired, max_dist=max_dist)
        if result is not None:
            self._dbg(f"[PLACEMENT] found valid position {result.pos} via ring search")
            return result
        
        self._dbg(f"[PLACEMENT] no valid position found within {max_dist} tiles of {desired}")
        return None
