# Logging

The bot explains itself in a structured event log: every proposal, admission,
lease, phase change and purchase is a line with a reason. This document is
the catalog of those lines and how to read them.

Source: `bot/ports/logging.py`, `bot/adapters/logging/`, `bot/app/telemetry/`,
plus every `logger.event(...)` call listed below. Viewer: `logs/viewer.html`,
`logs/viewer/*.js`.

## Format and location

One strict-JSON object per line, in a layer-neutral envelope:

```json
{"schema": 2, "run": "9f1c0b...", "seq": 4182, "iteration": 2911, "event": "mission_started", "component": "engine.missions.controller", "game_time": 131.42857142857142, "data": {"reason": "unit_requirements_satisfied", "mission_id": "mission-0007", "...": "..."}}
```

| Field | Meaning |
| --- | --- |
| `schema` | envelope version, `SCHEMA_VERSION` (2) |
| `run` | the run id, one per logger (a UUID unless given) |
| `seq` | 1, 2, 3, ... in write order: the causal order of the log |
| `iteration` | the frame the event was emitted in -- `FrameProcessor` brackets every frame with `begin_frame` / `end_frame`; `null` for `game.started`, `game.ended` and anything else outside a frame |
| `game_time` | exact, never rounded |

- Nothing is stringified and there is no NaN or Infinity. A record that
  cannot be written exactly is replaced by `logging.record_rejected`
  (component `adapters.logging`: `rejected_event`, `rejected_component`,
  `error`). `tests/fakes.py` holds every event any test emits to the same
  strictness.
- Decision records -- `strategy.context`, `mission.evaluated`,
  `map_control.spatial_candidates` -- carry values at machine precision;
  round only when reading. Periodic state summaries may still round.
- `data` always carries a `reason` for transitions, plus the correlation keys
  that apply: `proposal_id`, `mission_id`, `deduplication_key`, `squad_id`,
  `action_id`, `request_id`.
- Local runs write `logs/game-<UTC timestamp>/game.jsonl` when started with
  `--bot-log events` or `--spatial-snapshot` ([app.md](app.md)). SVG
  snapshots go to that folder's `spatial/`.
- Ladder runs use `NullBotLogger` and write nothing.

### Change gates

Periodic diagnostics would bury decisions, so most state reporters use a
`ChangeGate`: a line goes out when its signature (a tuple of the values that
matter) differs from the last one let through, or when its heartbeat has
elapsed since then. Without a heartbeat, only changes go out.

Decisions and transitions are never gated: every policy evaluation, every
context revision a decision cites, and every proposal, admission, rejection,
lease change, preemption, phase change, progress change and failure is
written when it happens.

## Catalog

### `app.runtime`

| Event | When | Data |
| --- | --- | --- |
| `game.started` | `on_start`, after the opening re-roll | `map`; `opening` (the one played, or `null`); `build` {`commit`, `branch`, `source`: `git` or `unknown`}; `config_fingerprint` over every decision-critical configuration, and `configs` {name: fingerprint}; `rng_seed`, `rng_seed_source` (`generated`, `configured` or `external`) |
| `game.ended` | `on_end` | `result` |
| `macro.build_order_progress` | the build runner moves to another step, or completes | `opening`, `step`, `total_steps`, `command`, `completed` |

### `app.debug.spatial_snapshot`

| Event | When | Data |
| --- | --- | --- |
| `debug.spatial_snapshot_written` | an SVG was written | `path`, `elements`, `bytes`, `render_write_ms` |
| `debug.spatial_snapshot_failed` | rendering or writing raised | `error` |

### `world.attention` / `world.awareness`

Emitted together by `WorldSnapshotTelemetry`, on a change of the headline
signature (posture, relative strength, threat counts, sighting count, live
mission ids and statuses) and every 10 s.

| Event | Data |
| --- | --- |
| `knowledge.updated` (`world.awareness`) | `posture`; `relative_strength` {`score`, `confidence`, `own_combat_units`, `known_enemy_combat_units`}; `threat` {`visible_enemy_units`, `known_anti_air_units`, `visible_anti_air_units`, `visible_enemy_combat_units`, `near_own_base_enemy_units`, `near_own_base_enemy_combat_units`}; `enemy_sightings`; `active_missions` |
| `observation.updated` (`world.attention`) | `minerals`, `vespene`, `supply_used`, `supply_cap`; `economy` {`opening_name`, `opening_completed`, collection rates, `workers`, `townhalls` (existing/ready/pending), `ideal_harvesters`, `assigned_harvesters`, `supply_pending`}; `own_unit_count`, `own_structure_count`, `visible_enemy_unit_count` |

### `world.awareness.enemy`

| Event | When | Data |
| --- | --- | --- |
| `knowledge.enemy_intel` | known structures (tag, type, position, visibility) or confirmed locations change | `known_enemy_bases`, `known_enemy_structures`, `confirmed_locations`, `structures[]` {`tag`, `type`, `position`, `visible_now`, `last_seen_at`} |
| `knowledge.enemy_model` | confirmed base keys or main force id change; every 10 s | `bases[]` {`key`, `economic_value`, `workers`, `air_defense`, `air_defense_confidence`, `ground_defense`, `ground_defense_confidence`, `confidence`}; `forces[]` {`cluster_id`, `center`, `radius`, `position_uncertainty`, `strength`, `anti_air`, `anti_ground`, `units`, `visible_units`, `confidence`}; `main_force` |

### `world.awareness.belief`

| Event | When | Data |
| --- | --- | --- |
| `awareness.world_belief` | raw or stable state of either axis changes; every 10 s | `economy` {`own_workers`, `own_bases`, `enemy_observed_workers`, `enemy_known_workers`, `enemy_estimated_workers`, `enemy_workers_uncertainty`, `enemy_confirmed_bases`, `enemy_estimated_bases`, `raw`, `stable`, `advantage`, `confidence`}; `army` {`own_supply`, `enemy_observed_supply`, `enemy_known_supply`, `enemy_estimated_supply`, `enemy_supply_uncertainty`, `raw`, `stable`, `advantage`, `confidence`} |
| `awareness.belief_changed` | a stable state changes | `message`, e.g. `[Awareness] ARMY: EVEN -> AHEAD (p_ahead=0.78, confidence=0.52) \| own 40 vs enemy ~28±6 supply` |

### `world.awareness.spatial` and `world.awareness.territory`

| Event | When | Data |
| --- | --- | --- |
| `spatial.perf` | every 10 s | `samples`, `clusters`, `routes`, `route_points`; `cache_check_ms`, `recompute_ms`, `total_ms`; per component (`static`, `friendly`, `route`, `threat`) `*_cache_ms`, `*_recompute_ms`, `*_rebuilt`, `*_rebuilds`; `compose_ms` |
| `knowledge.territory` | a region with an expansion changes control or crosses a 0.2 security step, a base changes region, the frontline appears or disappears; every 10 s | `samples` and `regions` counted per control; `confidence`; enemy control/threat sample counts; remembered cluster count, oldest memory, largest uncertainty/control/possible-presence radii; `frontline`; `bases[]`; `expansion_regions[]` |
| `territory.perf` | every 10 s | `update_ms`, `updates`, `topology_rebuilds`, `samples`, `regions`, `passages`, `friendly_forces`, `enemy_forces` |

### `engine.missions.controller`

Every event carries `reason` and, where a proposal or mission is involved:
`proposal_id`, `deduplication_key`, `planner_id`, `mission_kind`, `priority`,
`target_key`, `target`, `proposal_reason`, `last_observed_at`,
`observation_age`, `stale_after`, `squad_id`, and for missions `mission_id`,
`status`, `unit_tags`.

| Event | Reasons | Extra data |
| --- | --- | --- |
| `proposal_created` | the proposal's own reason | -- |
| `proposal_admitted` | `no_conflicting_live_mission` | -- |
| `proposal_rejected` | `matching_mission_already_live`, `mission_cooldown_active`, `unsupported_mission_kind` | `conflicting_mission_id` |
| `mission_queued` | `waiting_for_unit_allocation` | -- |
| `mission_started` | `unit_requirements_satisfied` | -- |
| `mission_blocked` | `unit_requirements_not_satisfied` (once per block) | -- |
| `mission_completed` | the executor's reason | -- |
| `mission_failed` | `all_assigned_units_lost`, `all_assigned_units_preempted`, `executor_error:<Type>:<message>`, or the executor's reason | -- |
| `mission_cancelled` | `mission_timeout`, `objective_satisfied_before_mission_started`, `standing_proposal_omitted` | -- |
| `mission.progressed` | the executor's reason, whenever an active mission's `(outcome, reason)` changes -- its first report included | `outcome`, `previous_outcome`, `previous_reason` |
| `mission.preemption_cost_failed` | `executor_preemption_cost_failed`: `preemption_cost()` raised or returned NaN; logged on the first failure, then at most every 30 s per mission | `error`, `fallback_cost` (0), `suppressed_since_last` |
| `standing_mission_updated` | `standing_requirement_changed` | `previous_priority`, `previous_desired`, `previous_supply_budget` |
| `units_assigned` | `allocator_assignment_changed` | `previous_unit_tags`, `unit_tags`, `unit_types` |
| `units_reassigned` | `higher_priority_after_commitment_window` | `unit_tags`, `unit_types`, `from_mission_id`, `from_proposal_id`, `from_priority` |
| `units_released` | `requirement_desired_reduced`, `replaced_by_more_suitable_unit`, or the finishing reason | `unit_tags`, `unit_types` |
| `units_upgraded` | `clearly_more_suitable_unit_available` | `upgrades[]` {released/acquired tag, type, utility} |
| `capability_composition_changed` | `capability_allocation` | `role`, `previous_composition`, `composition`, `new_unit_types`, `supply`, `supply_budget`, `candidates[]` |
| `capability_no_suitable_candidates` | `capability_allocation` (once until a unit fits) | `role`, `candidates[]` |

### `engine.squads.controller`

Every event carries `reason`, `squad_id`, `squad_role`.

| Event | Reasons | Extra data |
| --- | --- | --- |
| `squad_created` | `home_mission_registered` | -- |
| `squad_membership_changed` | `members_lost`, `allocation_changed` | `previous_member_tags`, `member_tags` |
| `squad_mission_changed` | `home_mission_active`, `temporary_mission_active`, `home_mission_restored` | `current_mission_id/key`, `home_mission_id/key` |
| `squad_preempted` | `higher_priority_compatible_mission` | `from_mission_id`, `to_mission_id` |
| `squad_returned_home` | `temporary_mission_finished` | `finished_mission_id`, `home_mission_id` |

### `engine.services.vision` and `engine.services.vision.scan_provider`

Request events carry `request_id`, `requester`, `reason`, `position`,
`urgency`, `status`, `status_reason`.

| Event | When | Extra data |
| --- | --- | --- |
| `vision.request_created` | a new request | `ttl` |
| `vision.request_deduplicated` | a request merged into a live one (at most every 15 s per request) | `duplicate_requester`, `duplicate_reason` |
| `vision.request_selected` | chosen for a provider attempt (an unavailable request re-logs at most every 15 s) | -- |
| `vision.request_satisfied` | its position became visible | -- |
| `vision.request_deferred` | the provider refused (at most every 15 s) | -- |
| `vision.provider_selected` | an Orbital was picked | `request_id`, `provider`, `orbital_tag`, `orbital_energy` |
| `vision.scan_executed` | the scan was accepted | same |

### `engine.economy.controller`

Events carry `reason`, and where applicable `proposal_id`, `deduplication_key`,
`planner_id`, `action_kind`, `priority`, `target`, `target_count`,
`proposal_reason`, `cost`, `action_id`, `admitted_at`. A proposal's outcome
event is written only when it differs from that proposal's previous outcome,
so a purchase deferred for the same reason every frame logs once.

| Event | Reasons | Extra data |
| --- | --- | --- |
| `economic_proposal_created` | the proposal's reason (once per proposal id) | -- |
| `economic_proposal_deferred` | `insufficient_bank`, `protected_commitment_holds_resources`, `higher_priority_reservations_hold_resources` | `available_bank`, `held_cost` |
| `economic_proposal_rejected` | `duplicate_proposal_id_in_tick`, `lower_ranked_duplicate_in_tick`, `matching_economic_action_already_live`, `matching_economic_action_timed_out_this_tick` | `status` |
| `economic_action_admitted` | `resources_reserved` | -- |
| `economic_action_pending` | `waiting_for_dispatch`, or the adapter's waiting reason when it changes | `waiting_seconds`, `previous_reason`, `dispatch_attempts` |
| `economic_action_dispatched` | `ares_command_accepted` | `dispatch_attempts` |
| `economic_action_confirmed` | `target_observed_in_attention`, `ares_train_order_issued` | -- |
| `economic_action_failed` | `ares_dispatch_error:<Type>:<message>`, `proposal_withdrawn_before_dispatch` | -- |
| `economic_action_timed_out` | `dispatch_timeout`, `confirmation_timeout` | `waiting_seconds`, `dispatch_attempts`, `last_dispatch_attempt_at`, `last_dispatch_feedback_at`, `last_dispatch_reason` |
| `economic_feedback_rejected` | `duplicate_feedback_in_tick`, `unknown_economic_action`, `economic_action_already_terminal` | `feedback_kind`, `feedback_reason` |

Adapter waiting reasons: `minerals_unavailable_at_dispatch`,
`vespene_unavailable_at_dispatch`, `supply_unavailable_at_dispatch`,
`unit_tech_not_ready`, `compatible_producer_not_ready`,
`compatible_producer_busy`, `structure_tech_not_ready`,
`worker_or_placement_unavailable`,
`safe_expansion_location_or_worker_unavailable`,
`geyser_or_worker_unavailable`, `addon_parent_unavailable`,
`addon_parent_busy`, `upgrade_prerequisite_or_researcher_unavailable`,
`ares_no_progress_this_frame`.

### `macro.planner`

| Event | When | Data |
| --- | --- | --- |
| `macro.status` | demand, capacity verdicts or proposal keys change; every 10 s | `opening` {`name`, `completed`}; `resources` {`bank`, `protected`, `reserved`, `free`} as [minerals, gas]; `army` {`desired_supply`, `ready_supply`, `pending_supply`, `supply_debt`}; `unit_demand`; `tech_blocked`; `production[]` {`type`, `ready`, `idle`, `pending`, `utilization_20s`}; `capacity` {type: `demanded`, `current`, `desired`, `reason`}; `proposals[]` {`key`, `priority`, `reason`} |
| `macro.idle_producer_unexplained` | a producer idle 15 s while a unit it can build without an add-on is owed and the spendable bank could pay | `producer`, `idle`, `ready`, `utilization_20s`, `owed_units`, `spendable`, `protected`, `duration_seconds` |

### Behaviors (`behavior.*`)

Each behavior logs under its own component through `BehaviorLog`:
`behavior.standing`, `behavior.map_control`, `behavior.defense`,
`behavior.harass.reaper`, `behavior.harass.banshee`, `behavior.scouting`,
`behavior.scouting.vision`.

| Event | Data | Written by |
| --- | --- | --- |
| `behavior.assessed` | `decision` plus the assessment's `log_fields()` | standing and map control when their plan changes; Reaper and Banshee raids on every cadence-ready tick (`propose`/`withhold`); defense, scouting and scouting vision when they propose |
| `behavior.proposed` | the plan's `log_fields()`, `planner`, extras | the same moments, when a plan exists |
| `behavior.state_changed` | `state`, `reason`, `mission_id`, extras | executors on a phase change (see below) |
| `behavior.target_selection` | `change` (`SELECTED`, `KEPT`, `RETARGETED`, `REPLACED`, `LOST`, `NONE`), `selected`, `previous`, `candidates[]` | Reaper and Banshee planners on a target change, at least every 30 s |
| `map_control.spatial_candidates` | `candidate_count`; `candidate_set` (order-free digest of every sample the selection saw); `pool` (`frontier`, `safe_fallback` or `all_candidates`) and `pool_size`; `rejections` {eligibility reason: count}; `selected`, `runner_up` (best other valid anchor, or `null`) and `winning_margin` (`selected.score - runner_up.score`; negative when hysteresis held the anchor); top 5 `candidates[]`. Each candidate at machine precision: position, `score` (= `local_value` - `caution` + `strategic_value`), `opportunity`, frontier, advancement, friendly support/band, enemy control/threat, knowledge/unknown risk, choke, route, travel cost, `information_desire`, `control_objective`/`control_alignment`/`control_importance` (`null`/0 without a match), selected flag and reason | `MapControlPlanner` every selection cadence |
| `map_control.anchor_changed` | `old_anchor`, `new_anchor`, `old_score`, `new_score`, `switch_margin`, `reason` | `MapControlPlanner` when its anchor changes |
| `standing.updated` | `combat_posture`; `standing` {squad: `desired`, `assigned`}; `mission_allocation` {kind: unit count}; `squads[]`; `unassigned_eligible_units` | `StandingTelemetry`, on change and every 10 s |
| `standing.unassigned_units_persisting` | `unassigned_eligible_units`, `unassigned_unit_tags`, `duration_seconds` | when a ready combat unit has had no mission for 15 s |

`behavior.state_changed` states:

| Behavior | States |
| --- | --- |
| standing | `ANCHORED` |
| map control | `WAITING`, `PATROL`, `RETREAT`, `HOLDING_HOME` |
| Banshee raid | `ASSEMBLE`, `APPROACH`, `INFILTRATE`, `STRIKE`, `EVADE`, `REPOSITION` |
| defense | roles `SIEGE_ANCHOR`, `SCREEN`; Tank phases `MOVING_TO_ANCHOR`, `SIEGING`, `SIEGED`, `REPOSITIONING`, `UNSIEGING` |

### `strategy.director`

Strategy is live. Two events:

| Event | When | Data |
| --- | --- | --- |
| `strategy.updated` | the first update, an objective transition, and every 10 s otherwise | the change/heartbeat summary, mirroring `StrategySnapshot`: `objective`, `previous_objective`, `leader`, `confidence`, `time_in_objective`, `inputs` (the six signals), `scores` (objective -> score), `reason`, `context_revision` (in force), `shadow: false`, `mode: "live"` |
| `strategy.context` | once per `StrategicContext` revision, before the first decision that cites it | the exact, complete context: `revision`, `updated_at`, `objective`, `leader`, `confidence`, `inputs`, `assessments[]` {`objective`, `score`, `raw_score`, `contributions` {signal: value}}, `intent` {`defense`, `map_control`, `harass`, `information`, `risk_tolerance`}, `control_objectives[]` (every objective, complete: one absent from a later revision is no longer wanted) |

The viewer has a track for `strategy.updated`; an older log without
`shadow: false` is shown as shadow.

### `strategy.mission_policy`

`MissionRanker` logs one `mission.evaluated` for every candidate it
evaluates, viable or rejected. It is never change-gated: planners propose
seconds apart, so it is one line per decision. `proposal_id` joins it to the
controller's `proposal_*` and mission events; a rejected candidate has no
controller event at all. `context_revision` joins it to the
`strategy.context` it was decided under.

| Field | Meaning |
| --- | --- |
| `proposal_id`, `deduplication_key`, `planner`, `mission_kind`, `target_key`, `target` | the candidate's identity |
| `context_revision`, `policy_model`, `policy_config` | what decided it: the Strategy context revision, the valuation model (`linear_utility_v1`) and the fingerprint of `MissionPolicyConfig` |
| `viable`, `reason`, `priority` | the verdict. `reason` is `fallback_owner`, `viable_positive_utility`, `viable_by_urgency_floor`, `rejected_negative_raw_utility` or `rejected_utility_not_above_minimum`; `priority` is `null` when rejected |
| `signals` | the planner's `MissionSignals`: `activity`, `opportunity`, `urgency`, `risk`, `information_gain`, `control_objective` and `control_alignment` (both `null` without a `ControlMatch`), `signal_reason` |
| `evaluation` | the `MissionEvaluation` the verdict came from: `utility`, `raw_utility`, `urgency_floor`, `floor_applied`, `opportunity_contribution`, `information_contribution`, `control_contribution`, `urgency_contribution`, `risk_penalty`, and the Strategy inputs it read: `strategic_desirability`, `information_desire`, `risk_tolerance`, `control_importance`, `control_gap` (`null` where not read) |

## The log viewer

`logs/viewer.html` is a standalone page: open it with `python
logs/open_viewer.py` or the `log_view` VS Code launcher, then load a
`game.jsonl` -- or the whole game folder, which also loads the SVG snapshots.

- **Summary** -- the story of the game as key moments and metric cards.
- **Observation / Knowledge / Economy** -- views derived only from the events
  above (`observation.updated`, `knowledge.*`, the economic events).
- **Streams** -- the raw event timeline by component, with mission and economic
  histories kept separate.
- **Decision Timeline** -- horizontal tracks on one selected time: macro and
  combat posture, army/economy belief, relative strength and threat, missions
  by kind, behavior phases, territory and economy, strategy (when logged), plus
  the nearest `spatial/territory-*.svg`. Its logic lives in `logs/viewer/`:
  `timeline_model.js` (step-function tracks and the state at any time),
  `diagnostics.js` (explicit contradiction rules, hints rather than verdicts),
  `snapshots.js` (SVG time matching) and `decision_view.js` (rendering).

`COMPONENT_ALIASES` maps older component names (`application.runtime`,
`ego.mission_controller`, `economy.controller`, `behavior.army.disposition`,
`behavior.macro.planner`) onto the current ones, and splits a log old enough
that everything was `application.runtime` into observation/knowledge by event
name. Retired events it can still read: `attention.world_state`,
`awareness.updated`, `attention.snapshot`.

`tests/test_log_viewer.py` checks that the page covers the catalog and never
injects log values as HTML; `tests/test_decision_timeline.py` runs the
timeline modules in a headless Chromium-family browser.

## Recipes

| Question | Read |
| --- | --- |
| Why is this unit here? | `units_assigned` / `units_reassigned` for its tag -> the mission's `proposal_created` reason -> that behavior's `behavior.proposed` |
| Why did a mission never start? | `proposal_rejected`, or `mission_blocked` followed by `capability_no_suitable_candidates` |
| Why did the raid go to that base? | `behavior.target_selection` (candidate scores) and `knowledge.enemy_model` at that time |
| Why is the bot banking? | `macro.status` (`resources`, `capacity` reasons, `tech_blocked`) and `economic_proposal_deferred` reasons |
| Why is a Factory idle? | `macro.idle_producer_unexplained`, or `capacity.FACTORY.reason` in `macro.status` |
| Why did the army retreat / stop pushing? | `behavior.state_changed` (map control `RETREAT` reason), `knowledge.updated` posture, `awareness.belief_changed` |
| Did a scan fire? | `vision.request_selected` -> `vision.scan_executed` or `vision.request_deferred` |
| Who holds the map? | `knowledge.territory`, and the SVG at that time |
| Is the bot slow? | `spatial.perf` (`*_rebuilds` growing every heartbeat means a cache is not holding), `territory.perf` |
