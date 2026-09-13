"""Deprecated compatibility import for the former Awareness policy type.

New code imports ``MacroPosture`` from :mod:`bot.strategy`.  Awareness keeps
this alias temporarily because many snapshot fixtures still construct the
legacy transport field.  No posture policy is evaluated in this package.
"""

from __future__ import annotations

from bot.domain.posture import MacroPosture

__all__ = ["MacroPosture"]
