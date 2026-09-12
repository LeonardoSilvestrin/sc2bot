"""End-of-frame diagnostics: what the bot perceives, believes and owns.

Every reporter reads state other components own and keeps only what it needs
to deduplicate its own events (see ``ChangeGate``); none of it feeds back into
a decision.
"""

from .frame import FrameTelemetry

__all__ = ["FrameTelemetry"]
