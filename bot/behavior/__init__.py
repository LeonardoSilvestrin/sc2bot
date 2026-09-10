"""Gameplay behaviors, one vertical slice per behavior.

Each behavior owns a folder, and everything specific to it lives there:

    standing/          the default owner of every otherwise-idle combat unit
    harass/banshee/    cloaked Banshee raid
    harass/reaper/     single-Reaper worker-line raid
    defense/           per-base defense
    map_control/       the roaming patrol share
    scouting/          information missions
    macro/             the economic (non-mission) track

Every one of them follows the same shape -- see `contracts.py`:

    ASSESS -> PLAN -> (mission / ownership) -> EXECUTE

Assessment reads Attention and Awareness and describes the situation.
Planning turns that into proposals with a priority and unit requirements.
`bot.engine.missions` -- generic, and deliberately ignorant of what any
behavior means -- admits proposals, owns units, and arbitrates conflicts.
Execution commands only the units the mission actually owns.
"""
