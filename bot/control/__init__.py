"""
Control package.

Keep package init lightweight to avoid import cycles at startup.
Import concrete modules directly, e.g.:
  - bot.control.priority_policy
  - bot.control.macro_resource_controller
  - bot.control.advantage_supervisor
"""

__all__: list[str] = []
