"""CONTROL: the planners that act through structures and abilities, not by
asking the Engine for army units.

- `detection`: scans, Missile Turrets and the energy kept for a scan.
- `structure_control`: which supply depots rise and which lower.

Neither governs missions; each keeps the little memory it needs. One that
grows past one question becomes a package, one module per question.
"""
