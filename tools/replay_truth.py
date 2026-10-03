"""What the enemy really had, against what the bot believed.

A replay holds the whole game: every ~7 s each player's workers, income and
army value (PlayerStatsEvent), and every unit born, morphed and killed. This
rebuilds the enemy army alive over time, prices it in Marines the way the bot
does (sqrt(dps * splash * hit points) / a Marine's), and compares it with the
`awareness.updated` events of the game's JSONL log.

    python tools/replay_truth.py bench/<label> [more labels or game folders]

Needs `sc2reader` (``pip install sc2reader``), which is not a dependency of
the bot. Locally hosted replays carry no Battle.net cache handles, which
sc2reader expects; `_load` makes up for that.

The power table is static and prices every unit at full health, so it reads a
little more than the bot, which prices what it sees as it is. Each game is
calibrated by the bot's own army: the median of the logged `own_power` over
the table's price of our own units is applied to the enemy's.

Per game it reports:

- `bias` and `mae`: mean error and mean absolute error of the estimate, in Marines;
- `nees`: mean of (truth - estimate)^2 / sigma^2 -- about 1 for a consistent
  filter, above it for an overconfident one (logs with `enemy_sigma` only);
- `in_2sigma`: share of the time the truth was within two sigma;
- `ahead`: share of the time the bot really was ahead -- army_position as the
  Assessment computes it, with the true enemy army -- and the share it
  believed it was (planned against estimate + 0.5 sigma; a log from before
  the observer has no sigma, and is read against the estimate alone).
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

LOOPS_PER_SECOND = 22.4
MARINE = math.sqrt(9.8 * 45.0)
# The Assessment's prior_power and sigma_margin.
PRIOR_POWER = 20.0
SIGMA_MARGIN = 0.5
# A position this far from even is "ahead".
AHEAD = 0.05

# (dps at Faster, hit points + shields, splash targets); dps 0 for no weapon.
STATS: dict[str, tuple[float, float, float]] = {
    # Zerg
    "Zergling": (10.1, 35, 1),
    "Baneling": (19.2, 30, 3),
    "Roach": (11.2, 145, 1),
    "Ravager": (14.0, 120, 1),
    "Hydralisk": (20.3, 90, 1),
    "Queen": (12.7, 175, 1),
    "Mutalisk": (8.3, 120, 1.5),
    "Corruptor": (10.3, 200, 1),
    "LurkerMPBurrowed": (14.0, 190, 2.5),
    "Ultralisk": (57.4, 500, 1),
    "BroodLord": (11.2, 225, 1),
    "LocustMP": (23.0, 50, 1),
    "LocustMPFlying": (23.0, 50, 1),
    # Terran
    "Marine": (9.8, 45, 1),
    "Marauder": (9.35, 125, 1),
    "Reaper": (10.1, 60, 1),
    "Ghost": (9.35, 100, 1),
    "Hellion": (4.5, 90, 2),
    "HellionTank": (12.6, 135, 2.5),
    "WidowMineBurrowed": (4.3, 90, 2.5),
    "SiegeTank": (20.3, 175, 1),
    "SiegeTankSieged": (18.7, 175, 2.5),
    "Cyclone": (15.5, 120, 1),
    "Thor": (65.9, 400, 1),
    "ThorAP": (65.9, 400, 1),
    "VikingFighter": (14.0, 135, 1),
    "VikingAssault": (16.9, 135, 1),
    "Banshee": (27.0, 140, 1),
    "Liberator": (7.75, 180, 1),
    "LiberatorAG": (65.8, 180, 2),
    "Battlecruiser": (50.0, 550, 1),
    # Protoss
    "Zealot": (18.6, 150, 1),
    "Stalker": (9.7, 160, 1),
    "Adept": (6.2, 150, 1),
    "Sentry": (8.4, 80, 1),
    "Immortal": (19.2, 300, 1),
    "Colossus": (18.7, 350, 2.5),
    "Archon": (20.0, 360, 2),
    "DarkTemplar": (37.2, 120, 1),
    "VoidRay": (16.8, 250, 1),
    "Carrier": (37.4, 550, 1),
    "Phoenix": (12.7, 180, 1),
    "Tempest": (12.7, 350, 1),
}


def power(name: str) -> float:
    dps, hit_points, splash = STATS.get(name, (0.0, 0.0, 1.0))
    return math.sqrt(dps * splash * hit_points) / MARINE if dps > 0.0 else 0.0


def _load(path: Path):
    """sc2reader's replay, tolerating a replay no Battle.net server cached."""

    import sc2reader
    from sc2reader import resources

    original = resources.Replay.load_details
    void = hashlib.sha256(b"Standard Data: Void.SC2Mod").hexdigest()

    def load_details(self):
        details = self.raw_data.get("replay.details") or self.raw_data.get("replay.details.backup")
        if details is not None and not details["cache_handles"]:
            details["cache_handles"] = [SimpleNamespace(server="local", hash=void)]
        return original(self)

    resources.Replay.load_details = load_details
    try:
        return sc2reader.load_replay(str(path), load_level=3, load_map=False)
    finally:
        resources.Replay.load_details = original


def truth(path: Path) -> dict[str, list[tuple[float, float]]] | None:
    """(time, army power at full health) for our bot and its enemy; None for a
    replay of a game that was not played."""

    replay = _load(path)
    alive: dict[int, tuple[int, str]] = {}
    early: dict[int, set[str]] = {}
    series: dict[int, list[tuple[float, float]]] = {}
    for event in replay.tracker_events:
        kind = type(event).__name__
        if kind in ("UnitBornEvent", "UnitInitEvent"):
            alive[event.unit_id] = (event.control_pid, event.unit_type_name)
            if event.frame < 30 * LOOPS_PER_SECOND:
                early.setdefault(event.control_pid, set()).add(event.unit_type_name)
        elif kind == "UnitTypeChangeEvent" and event.unit_id in alive:
            alive[event.unit_id] = (alive[event.unit_id][0], event.unit_type_name)
        elif kind == "UnitDiedEvent":
            alive.pop(event.unit_id, None)
        elif kind == "PlayerStatsEvent" and event.pid in (1, 2):
            total = sum(power(name) for owner, name in alive.values() if owner == event.pid)
            series.setdefault(event.pid, []).append((event.frame / LOOPS_PER_SECOND, total))
    ours = next((pid for pid, names in early.items() if "SCV" in names), None)
    if ours is None or ours not in series or 3 - ours not in series:
        return None
    return {"bot": series[ours], "enemy": series[3 - ours]}


def beliefs(path: Path) -> list[tuple[float, float, float | None, float]]:
    """(time, estimate, sigma or None, own power) from `awareness.updated`."""

    rows = []
    for line in path.open(encoding="utf-8"):
        event = json.loads(line)
        if event["event"] != "awareness.updated":
            continue
        data = event["data"]
        rows.append(
            (
                event["game_time"],
                data["estimated_enemy_power"],
                data.get("enemy_sigma"),
                data["own_power"],
            )
        )
    return rows


def _at(series: list, time: float):
    index = bisect.bisect_right([row[0] for row in series], time) - 1
    return series[index] if index >= 0 else None


def _position(own: float, enemy: float) -> float:
    return (own - enemy) / (own + enemy + PRIOR_POWER)


def compare(game: Path, step: float = 10.0) -> dict[str, float] | None:
    replay, log = game / "replay.SC2Replay", game / "log" / "game.jsonl"
    if not replay.exists() or not log.exists():
        return None
    real = truth(replay)
    believed = beliefs(log)
    if real is None or not believed:
        return None
    end = min(real["enemy"][-1][0], believed[-1][0])
    ratios = []
    for time, _, _, own in believed:
        priced = _at(real["bot"], time)
        if priced is not None and priced[1] > 5.0:
            ratios.append(own / priced[1])
    scale = statistics.median(ratios) if ratios else 1.0
    errors, normalized, inside, ahead, believed_ahead = [], [], [], [], []
    time = 120.0
    while time <= end:
        enemy = _at(real["enemy"], time)
        row = _at(believed, time)
        time += step
        if enemy is None or row is None:
            continue
        _, estimate, sigma, own = row
        actual = scale * enemy[1]
        errors.append(estimate - actual)
        if sigma:
            normalized.append(((actual - estimate) / sigma) ** 2)
            inside.append(abs(actual - estimate) <= 2.0 * sigma)
        planned = estimate + SIGMA_MARGIN * (sigma or 0.0)
        ahead.append(_position(own, actual) > AHEAD)
        believed_ahead.append(_position(own, planned) > AHEAD)
    if not errors:
        return None
    return {
        "scale": scale,
        "bias": statistics.mean(errors),
        "mae": statistics.mean(abs(error) for error in errors),
        "nees": statistics.mean(normalized) if normalized else float("nan"),
        "in_2sigma": statistics.mean(inside) if inside else float("nan"),
        "ahead": statistics.mean(ahead),
        "believed_ahead": statistics.mean(believed_ahead),
    }


def games(paths: list[str]) -> list[Path]:
    found = []
    for name in paths:
        path = Path(name)
        found.extend([path] if (path / "replay.SC2Replay").exists() else sorted(path.iterdir()))
    return [path for path in found if path.is_dir()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", help="bench labels or game folders")
    args = parser.parse_args(argv)
    print(
        f"{'game':48s} {'scale':>5s} {'bias':>6s} {'mae':>5s} {'nees':>5s} "
        f"{'in2s':>5s} {'ahead':>5s} {'bot':>5s}"
    )
    for game in games(args.paths):
        result = compare(game)
        if result is None:
            continue
        print(
            f"{game.name[:48]:48s} {result['scale']:5.2f} {result['bias']:+6.1f} "
            f"{result['mae']:5.1f} {result['nees']:5.2f} {result['in_2sigma']:5.0%} "
            f"{result['ahead']:5.0%} {result['believed_ahead']:5.0%}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
