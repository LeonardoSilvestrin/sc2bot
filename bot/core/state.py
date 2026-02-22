from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BotState:
    iteration: int = 0
