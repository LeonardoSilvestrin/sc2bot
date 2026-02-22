import json
from sc2.bot_ai import BotAI
from sc2.main import run_game
from sc2.data import Race, Difficulty
from sc2.player import Bot, Computer
from sc2.maps import get


def _safe_unit_dict(u):
    # u._proto é o objeto raw da Blizzard (protobuf)
    p = getattr(u, "_proto", None)

    # unit_type bruto (int) — NÃO converte pra UnitTypeId
    unit_type_raw = None
    if p is not None and hasattr(p, "unit_type"):
        unit_type_raw = int(p.unit_type)

    # alliance/owner
    owner = None
    if p is not None and hasattr(p, "owner"):
        owner = int(p.owner)

    # name "melhor esforço" (pode dar erro dependendo do build)
    name = None
    try:
        name = str(getattr(u, "name", None))
    except Exception:
        name = None

    return {
        "name": name,
        "unit_type_raw": unit_type_raw,
        "owner": owner,
        "is_structure": bool(getattr(u, "is_structure", False)),
        "is_visible": bool(getattr(u, "is_visible", True)),
        "x": float(u.position.x),
        "y": float(u.position.y),
        # tag bruto costuma ser seguro
        "tag": int(getattr(u, "tag", 0)),
    }


class DebugJSONBotSafe(BotAI):
    async def on_step(self, iteration: int):
        # roda uma vez e sai
        if iteration != 0:
            return

        data = {
            "map": "PersephoneAIE_v4",
            "all_units": [],
            "neutral_structures": [],
            "near_base": [],
        }

        # All units (dump completo)
        for u in self.state.units:
            d = _safe_unit_dict(u)
            data["all_units"].append(d)

            # neutral structures (owner 0 = neutro na maioria dos casos)
            if d["owner"] in (0, None) and d["is_structure"]:
                data["neutral_structures"].append(d)

        # Units perto da base (pra achar geysers perto do CC)
        if self.townhalls.exists:
            cc = self.townhalls.first
            for u in self.state.units:
                if u.position.distance_to(cc.position) < 16:
                    data["near_base"].append(_safe_unit_dict(u))

        with open("debug_units.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        print("✅ JSON gerado: debug_units.json (safe, sem UnitTypeId)")
        # opcional: parar o jogo rápido
        await self.client.leave()


if __name__ == "__main__":
    run_game(
        get("PersephoneAIE_v4"),
        [
            Bot(Race.Terran, DebugJSONBotSafe()),
            Computer(Race.Zerg, Difficulty.Easy),
        ],
        realtime=True,
    )