# Module contracts

## Dependency rules

1. Actions may read only `AttentionSnapshot`, their assigned unit snapshots, and
   explicit command/logging ports.
2. Actions must not import `ares`, `BotAI`, `bot.awareness`, `bot.knowledge`, or
   `bot.infrastructure`.
3. Awareness consumes immutable world facts and publishes immutable beliefs.
4. Only `UnitRegistry` mutates unit ownership.
5. Only infrastructure adapters touch the filesystem or forward SC2 commands.
6. Every action step returns an `ActionResult` with a non-empty reason.
7. The scheduler owns lifecycle transitions and releases units on termination.

## Frame lifecycle

```text
observe Ares
build WorldFacts
update EnemyKnowledge
derive AwarenessSnapshot
build AttentionSnapshot
sync UnitRegistry
allocate units
step actions by priority
apply results
release completed/failed actions
```

## Logging

Modules emit structured events through `BotLogger`. Local runs opt in with
`--bot-log events`; the default and all ladder runs use `NullBotLogger`.

The local VS Code launcher exposes separate `com logs` and `sem logs`
configurations. Build-order transitions and an attention snapshot at most every
ten game-seconds are logged when events are enabled.
