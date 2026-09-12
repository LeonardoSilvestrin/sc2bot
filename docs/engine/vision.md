# Active vision

Seeing a position right now is a capability several behaviors need and none of
them should implement. `bot/engine/services/vision/` owns it: behaviors ask for
vision, the service decides which needs are worth answering this frame, and a
provider answers them. Today the only provider is Terran Scanner Sweep.

Source: `bot/engine/services/` (`context.py`, `vision/model.py`,
`vision/service.py`, `vision/scan_provider.py`), `bot/ports/vision_commands.py`,
`bot/adapters/ares/vision_commands.py`. Consumers:
[behavior/scouting.md](../behavior/scouting.md),
[behavior/defense.md](../behavior/defense.md).

```text
behavior (planner or executor)
    -> VisionRequester.request(position, urgency, reason, requester, ttl)
    -> VisionService          persist, deduplicate, arbitrate
    -> ScanProvider           pick an Orbital that can afford it
    -> VisionCommands port    (AresVisionCommands)
    -> Ares UseAbility(SCANNERSWEEP_SCAN)
```

## Contract

A behavior sees only `VisionRequester` (`request` and `result`), reached
through `BehaviorServices.vision`: planners receive `BehaviorServices` at
construction, executors as `context.services`. A request carries a position, a
`VisionUrgency` (`LOW` 25, `NORMAL` 50, `HIGH` 75, `CRITICAL` 100), a non-empty
reason and requester, and a TTL. It returns a `VisionRequestResult` -- a
`request_id`, a status and a reason -- never an Orbital or an energy value:

| Status | Meaning |
| --- | --- |
| `SATISFIED` | the position is visible |
| `PENDING` | waiting for resolution, or a scan was dispatched |
| `UNAVAILABLE` | the provider could not answer this frame; the reason says why |

Re-asking every frame is the expected usage: the service folds repeats into one
live request.

## Frame protocol

`FrameProcessor` drives the service in three steps around mission planning:

1. `begin_frame(attention, commands)` -- drops requests past their TTL and
   dispatches older than `scan_cooldown`, marks requests `SATISFIED` when their
   position is visible (and back to `PENDING` if vision was lost), and lets the
   provider read Orbital energy. `request` and `resolve` raise if it has not
   run.
2. `request(...)` -- during `ScoutingVisionRequester.tick` and every planner's
   `propose`. A request within `spatial_deduplication_radius` (10) of a live
   one merges into it: the TTL extends, the urgency rises to the higher of the
   two, and the existing `request_id` comes back.
3. `resolve()` -- after all planners ran. Unsatisfied requests not already
   covered by a scan within `scan_cooldown_radius` (13) during the last
   `scan_cooldown` (15 s) are ordered by urgency, then age, and at most
   `max_provider_attempts_per_frame` (1) of them goes to the provider.
   Accepted -> `PENDING`, and the dispatch is remembered for the cooldown;
   refused -> `UNAVAILABLE` with the provider's reason.

## ScanProvider

`ScanProvider` considers every ready `ORBITALCOMMAND`/`ORBITALCOMMANDFLYING`
holding at least `scan_energy_cost + reserve_energy` (50 + 50) energy and picks
the fullest one (lowest tag on ties), so a scan always leaves 50 behind. When a
cast is accepted it subtracts the cost from its own per-frame energy cache.
Refusal reasons: `insufficient_orbital_energy`, `scanner_sweep_command_rejected`,
`provider_frame_not_started`.

`AresVisionCommands` is the only code that casts: `has_vision` reads
`bot.is_visible`, and `scan` executes Ares' `UseAbility` immediately instead of
registering it, so the result is known in the same frame.

## Consumers

| Requester | When | Urgency | TTL |
| --- | --- | --- | --- |
| `ScoutingVisionRequester` (`behavior/scouting/planner.py`) | the enemy main is not visible and has gone `max_without_vision` (120 s) without an observation -- counted from game start if never seen; at most every 5 s | `NORMAL` | 12 s |
| `DefensePlanner` (`behavior/defense/planner.py`) | every frame: a remembered, no-longer-visible, attack-capable non-worker enemy last seen at most 12 s ago within 25 of one of our bases; targets the most recently seen one | `HIGH` | 6 s |

`ScoutingVisionRequester` follows a behavior's assess -> plan shape and logs
`behavior.assessed`/`behavior.proposed` under `behavior.scouting.vision`, but it
produces no mission; `FrameProcessor` ticks it before the mission planners. No
executor consumes `context.services.vision` yet.

## Events

Component `engine.services.vision`: `vision.request_created`,
`vision.request_deduplicated`, `vision.request_selected`,
`vision.request_satisfied`, `vision.request_deferred`. Deduplication, deferral,
and re-selection of a request that was unavailable are throttled to one line
per `deduplication_log_cooldown` (15 s). Component
`engine.services.vision.scan_provider`: `vision.provider_selected`,
`vision.scan_executed`.

## Deliberately not built

- Any provider other than Scanner Sweep (moving a unit, an Observer or
  Overseer, a Raven). `VisionService` holds a concrete `ScanProvider`, not yet
  a provider protocol.
- Coordination of Orbital energy with any other use.
- Cancelling a request, or a consumer reacting to `UNAVAILABLE`.
- Any use of `CRITICAL` urgency.

Known gap: a lifted Orbital (`ORBITALCOMMANDFLYING`) is still a candidate but
cannot cast. If it is the fullest one, `UseAbility` refuses, the request becomes
`UNAVAILABLE` with `scanner_sweep_command_rejected`, and with one attempt per
frame no scan happens until it lands.
