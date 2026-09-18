"""EGO: what the bot wants done.

`strategy` chooses the objective, the preferences and the policy each domain
follows; the `planners` turn them into what should be done -- proposals (a
task, a target, a priority and the units it requires) and the economy,
structure and detection plans. A planner whose work lasts governs missions:
it opens them and asks them to end, and each mission carries one operation
and makes its proposals. The Ego names no unit and commands nothing.
"""
