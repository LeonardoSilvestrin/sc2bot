"""Domain intent and global posture, without game effects.

- `strategy`: how the game stands and what the bot wants now, read by all.
- `planners`: what the units and structures we have do, one planner per
  domain. Planners may use episodic missions or express continuous desired
  state directly.
- `economy`: what we buy.

The normative roles are defined in docs/architecture.md.
"""
