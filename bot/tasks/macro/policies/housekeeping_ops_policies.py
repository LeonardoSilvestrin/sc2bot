from __future__ import annotations

from dataclasses import dataclass

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId as U

from bot.mind.awareness import Awareness, K


@dataclass
class MorphReservePolicy:
    awareness: Awareness

    @staticmethod
    def _pending_command_centers(bot) -> list:
        try:
            return [
                th
                for th in bot.townhalls.ready
                if th.type_id == U.COMMANDCENTER and not bool(getattr(th, "is_flying", False))
            ]
        except Exception:
            return []

    def _morph_target_kind(self, *, now: float) -> str:
        raw = self.awareness.mem.get(K("macro", "morph", "target_kind"), now=now, default="ORBITAL")
        out = str(raw or "ORBITAL").strip().upper()
        if out not in {"ORBITAL", "PLANETARY"}:
            out = "ORBITAL"
        return out

    def apply(self, bot, *, now: float) -> dict:
        pending_cc = self._pending_command_centers(bot)
        pending_tags = [int(cc.tag) for cc in pending_cc]
        pending_count = int(len(pending_tags))
        target_kind = self._morph_target_kind(now=now)

        reserve_m = 150 if pending_count > 0 else 0
        reserve_g = 150 if (pending_count > 0 and target_kind == "PLANETARY") else 0

        self.awareness.mem.set(K("macro", "morph", "pending_cc_tags"), value=list(pending_tags), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "morph", "pending_count"), value=int(pending_count), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "morph", "target_kind"), value=str(target_kind), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "morph", "reserve_minerals"), value=int(reserve_m), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "morph", "reserve_gas"), value=int(reserve_g), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "morph", "last_update_t"), value=float(now), now=now, ttl=None)

        return {
            "pending_count": int(pending_count),
            "pending_cc_tags": list(pending_tags),
            "target_kind": str(target_kind),
            "reserve_minerals": int(reserve_m),
            "reserve_gas": int(reserve_g),
        }


@dataclass
class MulePolicy:
    awareness: Awareness
    mule_spam_until_s: float = 360.0
    mule_keep_two_from_s: float = 720.0
    mule_max_reserved_scans: int = 2

    def _scan_reserve_count(self, *, now: float) -> int:
        if float(now) < float(self.mule_spam_until_s):
            return 0
        if float(now) < float(self.mule_keep_two_from_s):
            return 1
        return int(max(0, min(int(self.mule_max_reserved_scans), 2)))

    @staticmethod
    def _mule_target_for_orbital(bot, orbital):
        try:
            mfs = bot.mineral_field.closer_than(12.0, orbital.position)
            if mfs.amount > 0:
                return mfs.closest_to(orbital)
        except Exception:
            pass
        try:
            if bot.mineral_field.amount > 0:
                return bot.mineral_field.closest_to(orbital)
        except Exception:
            pass
        return None

    def apply(self, bot, *, now: float) -> dict:
        reserve_scans = int(self._scan_reserve_count(now=now))
        casts = 0
        orbitals_count = 0
        total_energy = 0.0

        try:
            orbitals = bot.structures(U.ORBITALCOMMAND).ready
        except Exception:
            orbitals = []

        for oc in orbitals:
            orbitals_count += 1
            energy = float(getattr(oc, "energy", 0.0) or 0.0)
            total_energy += energy

            scans_available = int(energy // 50.0)
            mules_to_cast = max(0, scans_available - int(reserve_scans))
            if mules_to_cast <= 0:
                continue

            for _ in range(mules_to_cast):
                target = self._mule_target_for_orbital(bot, oc)
                if target is None:
                    break
                try:
                    oc(AbilityId.CALLDOWNMULE_CALLDOWNMULE, target)
                    casts += 1
                except Exception:
                    break

        self.awareness.mem.set(K("macro", "mules", "scan_reserve"), value=int(reserve_scans), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "mules", "casts_last"), value=int(casts), now=now, ttl=None)
        self.awareness.mem.set(K("macro", "mules", "last_done_at"), value=float(now), now=now, ttl=None)

        return {
            "scan_reserve": int(reserve_scans),
            "casts": int(casts),
            "orbitals": int(orbitals_count),
            "orbital_energy_total": round(float(total_energy), 2),
        }

