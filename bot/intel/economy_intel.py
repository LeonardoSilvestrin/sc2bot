# bot/inteligence/economy.py
from __future__ import annotations

from dataclasses import dataclass

from bot.mind.awareness import Awareness, K
from bot.mind.attention import Attention


@dataclass(frozen=True)
class EconomyIntelConfig:
    macro_profile: str = "BIO_2BASE"
    target_bases: int = 3


def derive_economy_intel(
    bot,
    *,
    awareness: Awareness,
    attention: Attention,
    now: float,
    cfg: EconomyIntelConfig = EconomyIntelConfig(),
) -> None:
    """
    Atualiza a Awareness (memória) com o plano macro ativo e fase do jogo.
    - Não executa nada.
    - Não decide estratégia dinâmica.
    - Só escreve sinais estáveis de economia/plano.
    """

    try:
        bases = int(bot.townhalls.ready.amount)
    except Exception:
        bases = 0

    opening_done = bool(attention.macro.opening_done)

    if not opening_done:
        phase = "OPENING"
    elif bases < int(cfg.target_bases):
        phase = "MIDGAME"
    else:
        phase = "LATEGAME"

    awareness.mem.set(K("plan", "macro"), value=str(cfg.macro_profile), now=now, ttl=None)
    awareness.mem.set(K("plan", "phase"), value=str(phase), now=now, ttl=None)
    awareness.mem.set(K("plan", "opening_done"), value=opening_done, now=now, ttl=None)
    awareness.mem.set(K("plan", "target_bases"), value=int(cfg.target_bases), now=now, ttl=None)
    awareness.mem.set(K("plan", "bases_ready"), value=int(bases), now=now, ttl=8.0)