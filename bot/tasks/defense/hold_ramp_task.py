from __future__ import annotations

from dataclasses import dataclass

from ares.consts import UnitRole
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U
from sc2.position import Point2

from bot.devlog import DevLogger
from bot.mind.attention import Attention
from bot.tasks.base_task import BaseTask, TaskResult, TaskTick


@dataclass
class HoldRampTask(BaseTask):
    base_tag: int
    base_pos: Point2
    threat_pos: Point2 | None = None
    log: DevLogger | None = None

    _sticky: dict = None  # type: ignore[assignment]

    def __init__(
        self,
        *,
        base_tag: int,
        base_pos: Point2,
        threat_pos: Point2 | None = None,
        log: DevLogger | None = None,
    ) -> None:
        super().__init__(task_id="hold_ramp", domain="DEFENSE", commitment=88)
        self.base_tag = int(base_tag)
        self.base_pos = base_pos
        self.threat_pos = threat_pos
        self.log = log
        self._sticky = {}

    def _resolve_base_pos(self, bot) -> Point2:
        th = bot.townhalls.find_by_tag(int(self.base_tag))
        if th is not None:
            return th.position
        return self.base_pos

    @staticmethod
    def _assign_role(bot, units: list, role: UnitRole) -> None:
        for unit in list(units or []):
            try:
                if getattr(unit, "type_id", None) != U.SCV:
                    continue
                bot.mediator.assign_role(tag=int(unit.tag), role=role, remove_from_squad=True)
            except Exception:
                continue

    @staticmethod
    def _wall_context(bot) -> tuple[Point2, list[Point2], Point2 | None]:
        ramp = getattr(bot, "main_base_ramp", None)
        top = getattr(ramp, "top_center", None) if ramp is not None else None
        depots = list(getattr(ramp, "corner_depots", []) or []) if ramp is not None else []
        barracks_pos = getattr(ramp, "barracks_correct_placement", None) if ramp is not None else None
        if top is None:
            top = bot.start_location
        return top, depots, barracks_pos

    @staticmethod
    def _wall_targets(bot, *, depots: list[Point2], barracks_pos: Point2 | None) -> list:
        out = []
        wall_types = {U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED, U.BARRACKS, U.BARRACKSREACTOR, U.BARRACKSTECHLAB, U.BUNKER}

        # Localiza o barracks real na wall para detectar reactor/techlab anexados a ele
        real_barracks_pos: Point2 | None = None
        for unit in list(getattr(bot, "structures", []) or []):
            try:
                tid = getattr(unit, "type_id", None)
                if tid not in {U.BARRACKS, U.BARRACKSREACTOR, U.BARRACKSTECHLAB}:
                    continue
                on_depot = any(float(unit.distance_to(pos)) <= 1.8 for pos in depots)
                on_ramp = barracks_pos is not None and float(unit.distance_to(barracks_pos)) <= 2.5
                if on_depot or on_ramp:
                    real_barracks_pos = unit.position
                    break
            except Exception:
                continue

        for unit in list(getattr(bot, "structures", []) or []):
            try:
                if getattr(unit, "type_id", None) not in wall_types:
                    continue
                on_wall = any(float(unit.distance_to(pos)) <= 1.8 for pos in depots)
                if not on_wall and barracks_pos is not None:
                    on_wall = float(unit.distance_to(barracks_pos)) <= 2.5
                # Reactor/techlab ficam a ~2.5 tiles do centro do barracks — usa posição real
                if not on_wall and real_barracks_pos is not None:
                    on_wall = float(unit.distance_to(real_barracks_pos)) <= 3.0
                if not on_wall and getattr(unit, "type_id", None) != U.BUNKER:
                    continue
                out.append(unit)
            except Exception:
                continue
        return out

    @staticmethod
    def _repair_targets(bot, *, depots: list[Point2], barracks_pos: Point2 | None) -> list:
        targets = []
        for unit in HoldRampTask._wall_targets(bot, depots=depots, barracks_pos=barracks_pos):
            try:
                hp = float(getattr(unit, "health", 0.0) or 0.0)
                hp_max = float(getattr(unit, "health_max", 0.0) or 0.0)
                build_progress = float(getattr(unit, "build_progress", 1.0) or 1.0)
                if hp_max > 0.0 and (hp < hp_max or build_progress < 1.0):
                    targets.append(unit)
            except Exception:
                continue
        targets.sort(
            key=lambda u: (
                0 if getattr(u, "type_id", None) in {U.SUPPLYDEPOT, U.SUPPLYDEPOTLOWERED} else 1,
                float(getattr(u, "health_percentage", 1.0) or 1.0),
            )
        )
        return targets

    @staticmethod
    def _scv_hold_slots(*, depots: list[Point2], barracks_pos: Point2 | None, top_center: Point2, base_pos: Point2) -> list[Point2]:
        slots: list[Point2] = []
        for pos in list(depots or []):
            try:
                slots.append(pos.towards(base_pos, 0.9))
            except Exception:
                slots.append(pos)
        if barracks_pos is not None:
            try:
                slots.append(barracks_pos.towards(base_pos, 1.1))
            except Exception:
                slots.append(barracks_pos)
        if not slots:
            try:
                slots.append(top_center.towards(base_pos, 1.8))
            except Exception:
                slots.append(top_center)
        return slots

    @staticmethod
    def _reaper_hold_slot(*, depots: list[Point2], barracks_pos: Point2 | None, top_center: Point2, base_pos: Point2) -> Point2:
        candidates: list[Point2] = []
        if barracks_pos is not None:
            try:
                candidates.append(barracks_pos.towards(base_pos, 2.2))
            except Exception:
                candidates.append(barracks_pos)
        for pos in list(depots or []):
            try:
                candidates.append(pos.towards(base_pos, 2.0))
            except Exception:
                candidates.append(pos)
        try:
            candidates.append(top_center.towards(base_pos, 2.4))
        except Exception:
            candidates.append(top_center)
        if not candidates:
            return top_center
        try:
            return min(candidates, key=lambda p: float(p.distance_to(top_center)))
        except Exception:
            return candidates[0]

    @staticmethod
    def _issue_repair(scv, target) -> bool:
        try:
            repair_fn = getattr(scv, "repair", None)
            if callable(repair_fn):
                repair_fn(target)
                return True
        except Exception:
            pass
        for ability_name in ("EFFECT_REPAIR_SCV", "EFFECT_REPAIR"):
            try:
                ability = getattr(AbilityId, ability_name, None)
                if ability is None:
                    continue
                scv(ability, target)
                return True
            except Exception:
                continue
        return False

    @staticmethod
    def _building_tracker(bot) -> dict:
        try:
            return dict(bot.mediator.get_building_tracker_dict or {})
        except Exception:
            return {}

    @classmethod
    def _planned_structure_sites(cls, bot, *, centers: list[Point2], structure_types: set[U], radius: float) -> list[Point2]:
        out: list[Point2] = []
        for entry in cls._building_tracker(bot).values():
            if not isinstance(entry, dict):
                continue
            if entry.get("structure_type", None) not in structure_types:
                continue
            pos = entry.get("target", None) or entry.get("pos", None)
            if pos is None:
                continue
            try:
                point = Point2((float(pos.x), float(pos.y))) if hasattr(pos, "x") else pos
            except Exception:
                point = pos
            try:
                if centers and min(float(point.distance_to(center)) for center in centers if center is not None) > float(radius):
                    continue
            except Exception:
                continue
            duplicate = False
            for existing in out:
                try:
                    if float(existing.distance_to(point)) <= 0.9:
                        duplicate = True
                        break
                except Exception:
                    continue
            if not duplicate:
                out.append(point)
        return out

    @staticmethod
    def _nearest_reserved_site(unit, reserved_sites: list[Point2], *, radius: float) -> Point2 | None:
        best = None
        best_dist = float(radius)
        for site in list(reserved_sites or []):
            try:
                dist = float(unit.distance_to(site))
            except Exception:
                continue
            if dist <= best_dist:
                best = site
                best_dist = dist
        return best

    @staticmethod
    def _sanitize_slots(slots: list[Point2], *, reserved_sites: list[Point2], retreat: Point2, fallback: Point2) -> list[Point2]:
        out: list[Point2] = []
        for slot in list(slots or []):
            conflict = False
            for site in list(reserved_sites or []):
                try:
                    if float(slot.distance_to(site)) <= 2.5:
                        conflict = True
                        break
                except Exception:
                    continue
            if not conflict:
                out.append(slot)
                continue
            try:
                shifted = slot.towards(retreat, 2.75)
            except Exception:
                shifted = fallback
            retry_conflict = False
            for site in list(reserved_sites or []):
                try:
                    if float(shifted.distance_to(site)) <= 2.25:
                        retry_conflict = True
                        break
                except Exception:
                    continue
            if not retry_conflict:
                out.append(shifted)
        return out or [fallback]

    @staticmethod
    def _bunkers_near_wall(bot, *, top_center: Point2) -> list:
        out = []
        seen: set[int] = set()
        # Busca perto do top_center (raio 16) e também perto da start_location (raio 20)
        # para cobrir mapas onde o bunker fica perto dos depots no bottom da rampa
        search_centers = [top_center]
        try:
            search_centers.append(bot.start_location)
        except Exception:
            pass
        for center in search_centers:
            for unit in list(getattr(bot, "structures", []) or []):
                try:
                    tag = int(getattr(unit, "tag", -1) or -1)
                    if tag in seen:
                        continue
                    if getattr(unit, "type_id", None) == U.BUNKER and float(unit.distance_to(center)) <= 20.0:
                        seen.add(tag)
                        out.append(unit)
                except Exception:
                    continue
        return out

    @staticmethod
    def _bunker_has_space(bunker) -> bool:
        try:
            return int(getattr(bunker, "cargo_used", 0) or 0) < int(getattr(bunker, "cargo_max", 4) or 4)
        except Exception:
            return True

    @staticmethod
    def _enemy_wall_units(bot, *, top_center: Point2) -> list:
        out = []
        seen: set[int] = set()
        ramp = getattr(bot, "main_base_ramp", None)
        search_centers = [(top_center, 9.0)]
        try:
            bottom = getattr(ramp, "bottom_center", None) if ramp is not None else None
            if bottom is not None:
                search_centers.append((bottom, 7.0))
        except Exception:
            pass
        for center, radius in search_centers:
            for unit in list(getattr(bot, "enemy_units", []) or []):
                try:
                    tag = int(getattr(unit, "tag", -1) or -1)
                    if tag in seen:
                        continue
                    if float(unit.distance_to(center)) > float(radius):
                        continue
                    seen.add(tag)
                    out.append(unit)
                except Exception:
                    continue
        return out

    async def on_step(self, bot, tick: TaskTick, attention: Attention) -> TaskResult:
        bound_err = self.require_mission_bound(min_tags=1)
        if bound_err is not None:
            return bound_err

        units = [bot.units.find_by_tag(int(tag)) for tag in self.assigned_tags]
        units = [u for u in units if u is not None]
        if not units:
            return TaskResult.failed("no_hold_ramp_units_alive")

        top_center, depots, barracks_pos = self._wall_context(bot)
        base_pos = self._resolve_base_pos(bot)
        enemy_wall = self._enemy_wall_units(bot, top_center=top_center)
        repair_targets = self._repair_targets(bot, depots=depots, barracks_pos=barracks_pos)
        if not enemy_wall and not repair_targets:
            self._assign_role(bot, units, UnitRole.GATHERING)
            self._done("ramp_contact_cleared")
            return TaskResult.done("ramp_contact_cleared")

        self._assign_role(bot, units, UnitRole.REPAIRING)
        reserved_sites = self._planned_structure_sites(
            bot,
            centers=[top_center, base_pos],
            structure_types={U.BUNKER, U.COMMANDCENTER, U.ORBITALCOMMAND, U.PLANETARYFORTRESS},
            radius=14.0,
        )
        scv_hold_slots = self._scv_hold_slots(
            depots=depots,
            barracks_pos=barracks_pos,
            top_center=top_center,
            base_pos=base_pos,
        )
        scv_hold_slots = self._sanitize_slots(scv_hold_slots, reserved_sites=reserved_sites, retreat=base_pos, fallback=top_center)
        reaper_hold_slot = self._reaper_hold_slot(
            depots=depots,
            barracks_pos=barracks_pos,
            top_center=top_center,
            base_pos=base_pos,
        )
        bunkers = [b for b in self._bunkers_near_wall(bot, top_center=top_center) if self._bunker_has_space(b)]
        issued = False
        marine_slots = depots[:] if depots else [top_center]
        marine_slots = self._sanitize_slots(marine_slots, reserved_sites=reserved_sites, retreat=base_pos, fallback=top_center)
        marine_idx = 0
        scv_idx = 0
        enemy_count = int(len(enemy_wall))

        # Distribui SCVs entre alvos de reparo com sticky — evita troca de alvo a cada tick
        repair_tag_map = {int(getattr(t, "tag", -1)): t for t in repair_targets}
        scvs = [u for u in units if u.type_id == U.SCV]
        scv_repair_assign: dict[int, object] = {}
        repair_load: dict[int, int] = {}
        for scv in scvs:
            stag = int(scv.tag)
            prev = int(self._sticky.get(stag, -1))
            if prev in repair_tag_map:
                scv_repair_assign[stag] = repair_tag_map[prev]
                repair_load[prev] = repair_load.get(prev, 0) + 1
            else:
                # Escolhe alvo com menor carga
                chosen = None
                for rt in repair_targets:
                    rtag = int(getattr(rt, "tag", -1))
                    if repair_load.get(rtag, 0) < 2:
                        chosen = rt
                        break
                if chosen is None and repair_targets:
                    chosen = repair_targets[0]
                scv_repair_assign[stag] = chosen
                if chosen is not None:
                    ctag = int(getattr(chosen, "tag", -1))
                    self._sticky[stag] = ctag
                    repair_load[ctag] = repair_load.get(ctag, 0) + 1
        # Limpa sticky de SCVs que saíram
        live_tags = {int(u.tag) for u in scvs}
        self._sticky = {k: v for k, v in self._sticky.items() if k in live_tags}

        for unit in units:
            if unit.type_id == U.SCV:
                close_enemy = None
                try:
                    close_enemy = min(enemy_wall, key=lambda e: float(unit.distance_to(e))) if enemy_wall else None
                except Exception:
                    close_enemy = None
                if close_enemy is not None:
                    try:
                        if (
                            float(unit.distance_to(close_enemy)) <= 2.6
                            and float(getattr(unit, "health_percentage", 1.0) or 1.0) >= 0.5
                        ):
                            unit.attack(close_enemy)
                            issued = True
                            continue
                    except Exception:
                        pass
                target = scv_repair_assign.get(int(unit.tag))
                if target is not None:
                    # Só emite repair se idle ou não está já reparando
                    repairing = False
                    try:
                        for order in list(getattr(unit, "orders", []) or []):
                            name = str(getattr(getattr(order, "ability", None), "name", "") or "").upper()
                            if "REPAIR" in name:
                                repairing = True
                                break
                    except Exception:
                        pass
                    if not repairing:
                        issued = self._issue_repair(unit, target) or issued
                    continue
                reserved_site = self._nearest_reserved_site(unit, reserved_sites, radius=2.2)
                if reserved_site is not None:
                    unit.move(reserved_site.towards(base_pos, 3.1))
                    issued = True
                    continue
                hold = scv_hold_slots[scv_idx % len(scv_hold_slots)] if scv_hold_slots else top_center
                scv_idx += 1
                if float(unit.distance_to(hold)) > 1.5 and not bool(getattr(unit, "is_moving", False)):
                    unit.move(hold)
                    issued = True
                elif close_enemy is not None:
                    unit.attack(close_enemy)
                    issued = True
                continue

            if unit.type_id == U.REAPER:
                reserved_site = self._nearest_reserved_site(unit, reserved_sites, radius=2.5)
                if reserved_site is not None:
                    unit.move(reserved_site.towards(base_pos, 3.0))
                    issued = True
                    continue
                target = min(enemy_wall, key=lambda e: float(unit.distance_to(e))) if enemy_wall else None
                if target is None:
                    continue
                try:
                    if float(unit.distance_to(reaper_hold_slot)) > 1.25:
                        unit.move(reaper_hold_slot)
                        issued = True
                        continue
                    if float(unit.distance_to(target)) <= 5.25:
                        unit.attack(target)
                    else:
                        unit.move(reaper_hold_slot)
                    issued = True
                except Exception:
                    unit.move(reaper_hold_slot)
                    issued = True
                continue

            if unit.type_id == U.MARINE:
                if not enemy_wall:
                    continue
                target = min(enemy_wall, key=lambda e: float(unit.distance_to(e)))
                slot = marine_slots[marine_idx % len(marine_slots)] if marine_slots else top_center
                marine_idx += 1
                reserved_site = self._nearest_reserved_site(unit, reserved_sites, radius=2.4)
                if reserved_site is not None and not bunkers:
                    unit.move(reserved_site.towards(base_pos, 3.2))
                    issued = True
                    continue
                # Se há bunker disponível, entra direto — prioridade máxima
                if bunkers:
                    bunker = min(bunkers, key=lambda b: float(unit.distance_to(b)))
                    dist_to_bunker = float(unit.distance_to(bunker))
                    # Emite SMART (load) sempre que não está já dentro ou carregando
                    already_loading = False
                    try:
                        for order in list(getattr(unit, "orders", []) or []):
                            ab = getattr(getattr(order, "ability", None), "id", None)
                            if ab is not None and "LOAD" in str(ab).upper():
                                already_loading = True
                                break
                    except Exception:
                        pass
                    if not already_loading:
                        if dist_to_bunker <= 6.0:
                            unit(AbilityId.SMART, bunker)
                        else:
                            unit.move(bunker.position)
                        issued = True
                    continue
                try:
                    if float(unit.distance_to(slot)) > 1.5:
                        if not bool(getattr(unit, "is_moving", False)):
                            unit.move(slot)
                            issued = True
                    else:
                        unit.attack(target)
                        issued = True
                except Exception:
                    unit.attack(target)
                    issued = True
                continue

            if not enemy_wall:
                continue
            target = min(enemy_wall, key=lambda e: float(unit.distance_to(e)))
            unit.attack(target)
            issued = True

        if issued:
            self._active("holding_ramp")
            return TaskResult.running("holding_ramp")
        if repair_targets:
            self._active("repairing_ramp_wall")
            return TaskResult.running("repairing_ramp_wall")
        return TaskResult.noop("hold_ramp_idle")
