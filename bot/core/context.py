#bot/core/context.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from bot.devlog import DevLogger
from bot.services.roles import RoleService


@dataclass
class BotContext:
    """
    Container de serviços, config e logger.
    A ideia: actions/policies recebem (ctx, bb) e não ficam pescando bot.mediator.
    """
    bot: Any
    log: DevLogger
    roles: RoleService
    cfg: Optional[dict] = None

    @staticmethod
    def from_bot(bot: Any, log: DevLogger, *, cfg: Optional[dict] = None) -> "BotContext":
        return BotContext(
            bot=bot,
            log=log,
            roles=RoleService(bot),
            cfg=cfg,
        )