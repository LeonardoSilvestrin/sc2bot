from run import parse_local_args


def test_spatial_view_is_opt_in() -> None:
    assert not parse_local_args([]).spatial_view
    assert parse_local_args(["--spatial-view"]).spatial_view


def test_local_options_tolerate_ladder_arguments() -> None:
    args = parse_local_args(
        ["--LadderServer", "127.0.0.1", "--spatial-view", "--bot-log", "events"]
    )

    assert args.spatial_view
    assert args.bot_log == "events"
