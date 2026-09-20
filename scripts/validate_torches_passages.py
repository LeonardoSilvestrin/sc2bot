"""Live Torches geometry and frame integration, with simulated mineral removal.

Run from the repository: .venv/Scripts/python.exe scripts/validate_torches_passages.py
Requires SC2 and TorchesAIE_v4. Removal is injected into the observed neutral
list; this checks topology, consumers and telemetry, not actual worker mining.
An incomplete run or a swallowed SC2 callback exception fails the command.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "ares-sc2/src"), str(ROOT / "ares-sc2")]

from sc2 import maps  # noqa: E402
from sc2.data import Difficulty, Race  # noqa: E402
from sc2.main import run_game  # noqa: E402
from sc2.player import Bot, Computer  # noqa: E402

from bot.ego.planners.map_control.policies.staging import Ground  # noqa: E402
from bot.logs import Logs  # noqa: E402
from bot.main import BotBandido  # noqa: E402


def identity(view):
    topology = view.topology
    return (
        view.enemy_natural, view.enemy_third, view.expansions,
        topology.regions, topology.expansion_to_region, topology.adjacency,
        tuple((p.passage_id, p.regions, p.position, p.blocker_tags) for p in topology.passages),
    )


class Recorder(Logs):
    def __init__(self):
        super().__init__()
        self.changes = []

    def passages_changed(self, iteration, time, changes):
        self.changes.extend(changes)
        super().passages_changed(iteration, time, changes)


class Probe(BotBandido):
    def __init__(self):
        self.recorder = Recorder()
        super().__init__(logs=self.recorder, army="bio")
        self.stage = 0
        self.hidden = set()
        self.report = None

    async def on_step(self, iteration):
        if self.hidden:
            self.mineral_field = self.mineral_field.filter(
                lambda unit: unit.tag not in self.hidden
            )
        await super().on_step(iteration)
        view = self.layers.map_view
        topology = view.topology
        if self.stage == 0:
            walls = [p for p in topology.blocked_passages() if p.blocker_type == "mineral_wall"]
            assert len(walls) == 2, f"Expected two Torches walls, found {walls}"
            assert all(p.is_closed and len(p.blocker_tags) > 1 for p in walls)
            self.target, self.other = walls
            self.original = view
            self.original_identity = identity(view)
            self.before = topology.route(*self.target.regions)
            assert len(self.before) > 2, self.before
            self.ground_before = Ground(view)
            self.hidden = set(self.target.blocker_tags[:len(self.target.blocker_tags) // 2])
        elif self.stage == 1:
            assert view is self.original, "Partial removal must keep the same map snapshot"
            assert topology.passage(self.target.passage_id).is_closed
            assert not self.recorder.changes
            self.hidden = set(self.target.blocker_tags)
        elif self.stage == 2:
            assert topology.passage(self.target.passage_id).is_open
            assert topology.passage(self.other.passage_id).is_closed
            assert identity(view) == self.original_identity
            assert topology.regions is self.original.topology.regions
            assert topology.route(*self.target.regions) == self.target.regions
            change, = self.recorder.changes
            assert change.passage_id == self.target.passage_id
            assert change.transition == "CLOSED -> OPEN" and change.blockers_left == 0
            first, second = (topology.region(key) for key in self.target.regions)
            before = self.ground_before.table(first.center, first.region_id)
            after_ground = Ground(view)
            after = after_ground.table(first.center, first.region_id)
            xy = after_ground.lattice[list(second.sample_indices)]
            old_distances = self.ground_before.to(
                xy, second.region_id, first.center, first.region_id, before
            )
            new_distances = after_ground.to(
                xy, second.region_id, first.center, first.region_id, after
            )
            assert (new_distances < old_distances).any(), "Staging must use the new shortcut"
            self.report = {
                "map": view.name,
                "own_start": list(view.own_start),
                "regions": len(topology.regions),
                "passages": len(topology.passages),
                "wall_blockers": [len(self.target.blocker_tags), len(self.other.blocker_tags)],
                "partial_removal": "CLOSED",
                "full_removal": "OPEN",
                "identity_preserved": True,
                "route_before": self.before,
                "route_after": topology.route(*self.target.regions),
                "staging_shortcut": True,
                "telemetry": change.transition,
                "removal": "simulated in neutral observations",
            }
        else:
            assert len(self.recorder.changes) == 1, "Repeated frames must not repeat events"
            await self.client.leave()
        self.stage += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    probe = Probe()
    run_game(
        maps.get("TorchesAIE_v4"),
        [Bot(Race.Terran, probe), Computer(Race.Zerg, Difficulty.VeryEasy)],
        realtime=False, random_seed=args.seed, game_time_limit=30,
    )
    assert probe.stage == 4 and probe.report is not None, "Torches validation did not finish"
    report = json.dumps({"seed": args.seed, **probe.report}, indent=2)
    print(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
