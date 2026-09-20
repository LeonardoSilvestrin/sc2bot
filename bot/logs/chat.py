"""What the bot says out loud, in the game's chat.

A fourth observer of the frame, beside the event log, the snapshots and the
overlay: it reads the layers and says, in one line, what the bot is thinking --
that it is being rushed, that the opening it scouted looks like an all-in, that
it saw something cloaked. Like every observer here, it may not change a
decision and may not drop a match.

It is deliberately quiet: one line at a time, `gap` seconds apart, a topic
never repeated before `topic_cooldown`, and at most `max_lines` in a game. The
choice of line is deterministic, so the same game says the same things.

Speaking is async and a frame is not, so `observe` only queues; `MyBot.on_step`
drains the queue and sends it.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.attention import AttentionState
from bot.awareness import AwarenessState
from bot.ego.strategy import StrategicIntent, StrategicPosture

# How loud and how sure an opening read must be before the bot says it out
# loud. Presentation only: no decision reads these.
OPENING_LOUD = 0.6
OPENING_SURE = 0.35


@dataclass(frozen=True, slots=True)
class ChatConfig:
    enabled: bool = True
    # Game seconds between two lines: the bot talks, it does not spam.
    gap: float = 12.0
    # The same topic is not brought up again before this.
    topic_cooldown: float = 120.0
    max_lines: int = 20

    def __post_init__(self) -> None:
        if self.gap < 0.0 or self.topic_cooldown < 0.0:
            raise ValueError("gap and topic_cooldown must not be negative")
        if self.max_lines < 0:
            raise ValueError("max_lines must not be negative")


# What the bot says per topic. Several lines are rotated through in order, so a
# repeated topic sounds different without anything random.
LINES: dict[str, tuple[str, ...]] = {
    "rushed": ("Tô sendo rushado!", "Chegou gente em casa de novo."),
    "emergency": ("Emergência em casa!",),
    "pressure": ("Vou dar uma pressionada.", "Passeando na sua metade."),
    "commit": ("Tô indo com tudo.", "Agora vai."),
    "recover": ("Levei um tapa, recuando pra respirar.", "Preciso de um tempo."),
    "develop": ("Voltando a construir.", "Calmaria: bora macrar."),
    "cloaked": ("Camuflado? Já vi. Scan a caminho.",),
    "proxy": ("Cadê a produção dessa main? Isso cheira a proxy.",),
    "aggression": ("Natural atrasada e produção de pé: vem all-in aí.",),
    "greed": ("Expandiu cedo assim? Anotado, vou visitar.",),
    "tech": ("Muito gás pra tão pouca unidade: tem tech vindo.",),
    "gg": ("gg",),
}
_BY_POSTURE: dict[StrategicPosture, str] = {
    StrategicPosture.DEFEND: "rushed",
    StrategicPosture.PRESSURE: "pressure",
    StrategicPosture.COMMIT: "commit",
    StrategicPosture.RECOVER: "recover",
    StrategicPosture.DEVELOP: "develop",
}


class Chat:
    def __init__(self, config: ChatConfig | None = None) -> None:
        self.config = config or ChatConfig()
        # (topic, line) queued this frame, waiting for an async send.
        self._pending: list[tuple[str, str]] = []
        # When each topic was last said, and how many times.
        self._said: dict[str, tuple[float, int]] = {}
        self._lines = 0
        self._last: float | None = None
        self._posture: StrategicPosture | None = None
        self._emergency = False
        self._cloak_seen = False

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    def observe(
        self,
        attention: AttentionState,
        awareness: AwarenessState,
        intent: StrategicIntent,
    ) -> tuple[tuple[str, str], ...]:
        """Queue what this frame is worth saying; returns what was queued."""

        if not self.config.enabled:
            return ()
        said: list[tuple[str, str]] = []
        now = attention.time
        # What the bot wants now, when it changes.
        if intent.posture is not self._posture:
            previous, self._posture = self._posture, intent.posture
            topic = _BY_POSTURE.get(intent.posture)
            # Nothing to announce about the posture the game opens in.
            if topic is not None and previous is not None:
                said.append(self.say(topic, now))
        # A one-shot line the pace swallowed is not lost: it waits its turn,
        # and an emergency that ends re-arms the next one.
        if not intent.emergency:
            self._emergency = False
        elif not self._emergency:
            said.append(self.say("emergency", now))
            self._emergency = said[-1] is not None
        # What it believes, when the belief is both loud and worth something.
        if awareness.cloak_seen_at is not None and not self._cloak_seen:
            said.append(self.say("cloaked", now))
            self._cloak_seen = said[-1] is not None
        opening = awareness.opening
        if opening.confidence >= OPENING_SURE:
            for topic, score in (
                ("proxy", opening.proxy),
                ("aggression", opening.aggression),
                ("greed", opening.greed),
                ("tech", opening.tech),
            ):
                if score >= OPENING_LOUD:
                    said.append(self.say(topic, now))
        return tuple(line for line in said if line is not None)

    def say(self, topic: str, now: float, *, force: bool = False) -> tuple[str, str] | None:
        """Queue one line about `topic`, and give back what was queued; None
        when the bot holds its tongue. `force` says it whatever the pace, for
        the one line that has to go out -- the `gg`."""

        config = self.config
        lines = LINES.get(topic, ())
        if not config.enabled or not lines:
            return None
        if not force:
            if self._lines >= config.max_lines:
                return None
            if self._last is not None and now - self._last < config.gap:
                return None
            said_at, times = self._said.get(topic, (None, 0))
            if said_at is not None and now - said_at < config.topic_cooldown:
                return None
        times = self._said.get(topic, (None, 0))[1]
        self._said[topic] = (now, times + 1)
        self._last = now
        self._lines += 1
        queued = (topic, lines[times % len(lines)])
        self._pending.append(queued)
        return queued

    def announce(self, line: str, now: float, *, topic: str = "army") -> tuple[str, str] | None:
        """Queue a line the caller wrote itself -- the army announcement at the
        start. Silence still silences it."""

        if not self.config.enabled or not line:
            return None
        self._said[topic] = (now, self._said.get(topic, (None, 0))[1] + 1)
        self._last = now
        self._lines += 1
        queued = (topic, line)
        self._pending.append(queued)
        return queued

    def drain(self) -> tuple[tuple[str, str], ...]:
        """Take everything queued; the caller is the one that can speak."""

        pending = tuple(self._pending)
        self._pending.clear()
        return pending
