"""Gameplay behaviors: what units already on the map do.

A behavior works with missions, squads and unit leases -- who goes where and
does what, with which units. What the bot *buys* is not a behavior: units,
structures, tech and bases are `bot.macro`'s decision, arbitrated against the
bank by `bot.engine.economy`. A behavior may read what exists (Banshees
alive, cloak progress); it never proposes spend.

Each behavior owns a folder, and everything specific to it lives there --
the same four filenames every time, so any behavior answers the same four
questions in the same place:

    standing/          the default owner of every otherwise-idle combat unit
    harass/banshee/    cloaked Banshee raid
    harass/reaper/     single-Reaper worker-line raid
    defense/           per-base defense
    map_control/       the roaming patrol share
    scouting/          information missions

    model.py           the types the three below share
    assessment.py      ASSESS   what is the situation, through this lens?
    planner.py         PLAN     what do we want, at what priority, which units?
    executor.py        EXECUTE  how do we make it happen this frame?

See `contracts.py` for the protocols that fix that vocabulary.
`bot.engine.missions` -- generic, and deliberately ignorant of what any
behavior means -- sits between PLAN and EXECUTE: it admits proposals, owns
units, and arbitrates conflicts.
"""
