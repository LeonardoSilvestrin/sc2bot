from __future__ import annotations

from dataclasses import dataclass

from .vision.model import VisionRequester


@dataclass(frozen=True, slots=True)
class BehaviorServices:
    """Capabilities shared by otherwise independent behaviors."""

    vision: VisionRequester
