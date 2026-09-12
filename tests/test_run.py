import json
from pathlib import Path

from run import parse_local_args


def test_spatial_view_is_opt_in() -> None:
    defaults = parse_local_args([])
    assert not defaults.spatial_view
    assert defaults.spatial_view_spacing == 5

    configured = parse_local_args(
        ["--spatial-view", "--spatial-view-spacing", "4"]
    )
    assert configured.spatial_view
    assert configured.spatial_view_spacing == 4


def test_spatial_snapshot_is_opt_in_and_interval_is_configurable() -> None:
    assert not parse_local_args([]).spatial_snapshot
    args = parse_local_args(["--spatial-snapshot", "--spatial-snapshot-interval", "15"])

    assert args.spatial_snapshot
    assert args.spatial_snapshot_interval == 15.0


def test_local_options_tolerate_ladder_arguments() -> None:
    args = parse_local_args(
        ["--LadderServer", "127.0.0.1", "--spatial-view", "--bot-log", "events"]
    )

    assert args.spatial_view
    assert args.bot_log == "events"


def test_vscode_exposes_the_supported_launcher_modes() -> None:
    launch_file = Path(__file__).parents[1] / ".vscode" / "launch.json"
    launch_config = json.loads(launch_file.read_text(encoding="utf-8"))
    configurations = launch_config["configurations"]

    assert [configuration["name"] for configuration in configurations] == [
        "sem logs nem view",
        "só logs",
        "logs e view",
        "logs e snapshot SVG",
        "logs, view e snapshot SVG",
        "log visualizer",
    ]
    assert configurations[0]["args"] == ["--bot-log", "off"]
    assert configurations[1]["args"] == ["--bot-log", "events"]
    assert configurations[2]["args"] == [
        "--bot-log",
        "events",
        "--spatial-view",
        "--spatial-view-spacing",
        "5",
    ]
    assert configurations[3]["args"] == [
        "--bot-log",
        "events",
        "--spatial-snapshot",
    ]
    assert configurations[4]["args"] == [
        "--bot-log",
        "events",
        "--spatial-view",
        "--spatial-view-spacing",
        "5",
        "--spatial-snapshot",
    ]
