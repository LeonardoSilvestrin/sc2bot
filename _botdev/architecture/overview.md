# Pilot architecture

The pilot implements one directional flow:

```text
Ares -> AttentionBuilder (current facts) -> Knowledge (persistent facts)
     -> Awareness (beliefs) -> AttentionSnapshot
     -> ActionScheduler -> command adapter -> Ares
```

## Ownership

- `attention` publishes immutable facts, beliefs, and mission summaries.
- `knowledge` owns persistent observations such as first/last seen times.
- `awareness` derives beliefs from facts and never issues commands.
- `actions` retain operational state and return explicit results.
- `units` is the sole authority for action-to-unit ownership.
- `application` orchestrates the frame without containing strategy.
- `infrastructure` is the only layer that touches files or adapts Ares commands.

The initial runtime submits no actions. This deliberately makes the pilot neutral
while its contracts are validated. Bio strategy and the build runner are the next
vertical slice.
