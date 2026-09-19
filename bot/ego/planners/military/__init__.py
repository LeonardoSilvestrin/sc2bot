"""MILITARY: the planners that ask the Engine for army units (and a scout).

- `offense`: the main attack.
- `defense`: one area defense per threat incident.
- `intel`: the early scout.
- `army_fallback`: every army unit no one else needs, held at the rally.

Each is a package with `planner.py` and, when it governs operations, one
module per kind of mission in `missions/`.
"""
