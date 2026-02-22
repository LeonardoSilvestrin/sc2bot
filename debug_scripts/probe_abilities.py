from __future__ import annotations

import json
from datetime import datetime

from sc2.bot_ai import BotAI
from sc2.main import run_game
from sc2.data import Race, Difficulty
from sc2.player import Bot, Computer
from sc2.maps import get

from sc2.ids.ability_id import AbilityId as A
from sc2.ids.unit_typeid import UnitTypeId as U


class AbilityDumpBot(BotAI):
    def on_start(self):
        self._dumped = False

    async def on_step(self, iteration: int):
        if self._dumped:
            return

        worker = None
        if self.workers.idle.exists:
            worker = self.workers.idle.first
        elif self.workers.exists:
            worker = self.workers.first

        if worker is None:
            return

        # =========================
        # ENUM LOCAL (lib python)
        # =========================
        enum_abilities = []
        for ab in A:
            enum_abilities.append({
                "name": ab.name,
                "id": ab.value
            })

        # =========================
        # RUNTIME (jogo real)
        # =========================
        runtime_abs = await self.get_available_abilities(worker)

        runtime_abilities = []
        for ab in runtime_abs:
            runtime_abilities.append({
                "name": ab.name,
                "id": ab.value
            })

        # =========================
        # FILTRO BUILD
        # =========================
        def is_build_related(name: str) -> bool:
            return any(k in name for k in [
                "BUILD",
                "TERRANBUILD",
                "PROTOSSBUILD",
                "ZERGBUILD",
                "BARRACK",
                "FACTORY",
                "STARPORT",
                "SUPPLY",
                "REFINERY"
            ])

        enum_build = [a for a in enum_abilities if is_build_related(a["name"])]
        runtime_build = [a for a in runtime_abilities if is_build_related(a["name"])]

        # =========================
        # CROSS CHECK
        # =========================
        enum_names = set(a["name"] for a in enum_abilities)
        runtime_names = set(a["name"] for a in runtime_abilities)

        only_enum = sorted(list(enum_names - runtime_names))
        only_runtime = sorted(list(runtime_names - enum_names))

        # =========================
        # OUTPUT JSON
        # =========================
        data = {
            "timestamp": datetime.utcnow().isoformat(),
            "unit": "SCV",
            "summary": {
                "enum_total": len(enum_abilities),
                "runtime_total": len(runtime_abilities),
                "enum_build_count": len(enum_build),
                "runtime_build_count": len(runtime_build)
            },
            "enum_build_abilities": enum_build,
            "runtime_build_abilities": runtime_build,
            "diff": {
                "only_in_enum": only_enum,
                "only_in_runtime": only_runtime
            }
        }

        with open("sc2_abilities_dump.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        print("\n=== ABILITY DUMP GERADO: sc2_abilities_dump.json ===\n")
        print(json.dumps(data["summary"], indent=2))

        self._dumped = True


if __name__ == "__main__":
    run_game(
        get("PersephoneAIE_v4"),
        [
            Bot(Race.Terran, AbilityDumpBot()),
            Computer(Race.Zerg, Difficulty.Easy),
        ],
        realtime=False,
    )