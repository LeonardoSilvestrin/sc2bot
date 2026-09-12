// Decision timeline model: turns structured log records into time-indexed
// tracks so any instant can be queried without rescanning the log.
//
// Pure: no DOM. Loaded as a classic script (works over file://) and exposes
// `SC2Timeline` globally.
(function (root) {
  "use strict";

  const STRATEGY_EVENTS = new Set(["strategy.updated", "strategy.objective_changed"]);
  const KNOWLEDGE_EVENTS = new Set(["knowledge.updated", "awareness.updated"]);
  const TERMINAL_STATUSES = new Set(["COMPLETED", "FAILED", "CANCELLED"]);
  const TERMINAL_EVENTS = {
    mission_completed: "COMPLETED",
    mission_failed: "FAILED",
    mission_cancelled: "CANCELLED",
  };
  // Patrol phases in which the map-control squad is home, not out on the map.
  const MAP_CONTROL_HOME_STATES = new Set(["RETREAT", "HOLDING_HOME", "WAITING"]);

  const MISSION_ROW_LABELS = {
    HOLD_RALLY: "Main army (hold)",
    SCOUT: "Scout",
    HARASS: "Reaper harass",
    AIR_HARASS: "Banshee harass",
    DEFENSE: "Defense",
    MAP_CONTROL: "Map control",
    POSITION: "Position",
  };
  const MISSION_ROW_ORDER = ["DEFENSE", "MAP_CONTROL", "HARASS", "AIR_HARASS", "SCOUT", "HOLD_RALLY", "POSITION"];

  function finite(value) {
    const number = Number(value);
    return value != null && value !== "" && Number.isFinite(number) ? number : undefined;
  }

  function get(object, path) {
    let value = object;
    for (const key of path.split(".")) {
      if (value == null || typeof value !== "object") return undefined;
      value = value[key];
    }
    return value;
  }

  // Index of the last point whose t <= time, or -1.
  function lastIndexAtOrBefore(points, time) {
    let low = 0;
    let high = points.length - 1;
    let found = -1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (points[mid].t <= time) {
        found = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return found;
  }

  function lastIndexBefore(points, time) {
    let low = 0;
    let high = points.length - 1;
    let found = -1;
    while (low <= high) {
      const mid = (low + high) >> 1;
      if (points[mid].t < time) {
        found = mid;
        low = mid + 1;
      } else {
        high = mid - 1;
      }
    }
    return found;
  }

  // --- state tracks: categorical values that hold until the next change ---

  function stateTrack(key, label, group, extra = {}) {
    return { key, label, group, kind: "state", points: [], ...extra };
  }

  // Appends only when the value changes; same-timestamp updates replace.
  function pushState(track, time, value, record, detail) {
    if (value == null || value === "") return;
    const value_ = String(value);
    const last = track.points[track.points.length - 1];
    if (last && last.value === value_) {
      if (detail !== undefined) last.lastDetail = detail;
      return;
    }
    if (last && last.t === time) {
      track.points.pop();
      const previous = track.points[track.points.length - 1];
      if (previous && previous.value === value_) return;
    }
    track.points.push({ t: time, value: value_, record, detail });
  }

  function stateAt(track, time) {
    if (!track) return undefined;
    const index = lastIndexAtOrBefore(track.points, time);
    return index < 0 ? undefined : track.points[index];
  }

  function valueAt(track, time) {
    if (!track) return undefined;
    if (track.kind === "series") {
      const index = lastIndexAtOrBefore(track.points, time);
      return index < 0 ? undefined : track.points[index].v;
    }
    return stateAt(track, time)?.value;
  }

  function valueBefore(track, time) {
    if (!track) return undefined;
    const index = lastIndexBefore(track.points, time);
    if (index < 0) return undefined;
    return track.kind === "series" ? track.points[index].v : track.points[index].value;
  }

  function segments(track, endTime) {
    return track.points.map((point, index) => ({
      start: point.t,
      end: index + 1 < track.points.length ? track.points[index + 1].t : endTime,
      value: point.value,
      point,
    }));
  }

  // --- series tracks: numbers sampled over time -----------------------------

  function seriesTrack(key, label, group, extra = {}) {
    return { key, label, group, kind: "series", points: [], ...extra };
  }

  function pushSeries(track, time, value) {
    const number = finite(value);
    if (number === undefined) return;
    const last = track.points[track.points.length - 1];
    if (last && last.t === time) {
      last.v = number;
      return;
    }
    track.points.push({ t: time, v: number });
  }

  // --- interval tracks: missions and behavior phases ------------------------

  function statusAt(item, time) {
    const index = lastIndexAtOrBefore(item.statuses, time);
    return index < 0 ? undefined : item.statuses[index].value;
  }

  function isOpenAt(item, time) {
    return item.start <= time && (item.end == null || time < item.end);
  }

  function assignLanes(items) {
    const laneEnds = [];
    for (const item of [...items].sort((a, b) => a.start - b.start)) {
      const end = item.end ?? Number.POSITIVE_INFINITY;
      let lane = laneEnds.findIndex((laneEnd) => laneEnd <= item.start);
      if (lane < 0) {
        lane = laneEnds.length;
        laneEnds.push(end);
      } else {
        laneEnds[lane] = end;
      }
      item.lane = lane;
    }
    return laneEnds.length;
  }

  function buildMissionTracks(records, endTime) {
    const byId = new Map();
    for (const record of records) {
      const data = record.data;
      const id = data.mission_id;
      if (!id || !data.mission_kind && !byId.has(id)) continue;
      let item = byId.get(id);
      if (!item) {
        item = {
          id,
          kind: data.mission_kind,
          target: data.target_key,
          planner: data.planner_id,
          start: record.game_time,
          end: null,
          statuses: [],
          unitTypes: new Set(),
          reasons: [],
        };
        byId.set(id, item);
      }
      item.kind ||= data.mission_kind;
      const status = TERMINAL_EVENTS[record.event] ?? data.status;
      if (status) {
        const last = item.statuses[item.statuses.length - 1];
        if (!last || last.value !== status) {
          item.statuses.push({ t: record.game_time, value: status, reason: data.reason, event: record.event });
        }
      }
      for (const unitType of Array.isArray(data.unit_types) ? data.unit_types : []) {
        if (unitType) item.unitTypes.add(unitType);
      }
      if (record.event.startsWith("mission_")) {
        item.reasons.push({ t: record.game_time, event: record.event, reason: data.reason });
      }
      if (status && TERMINAL_STATUSES.has(status) && item.end == null) {
        item.end = record.game_time;
        item.finalStatus = status;
      }
    }

    const byKind = new Map();
    for (const item of byId.values()) {
      const kind = item.kind || "UNKNOWN";
      if (!byKind.has(kind)) byKind.set(kind, []);
      byKind.get(kind).push(item);
    }
    const kinds = [...byKind.keys()].sort((a, b) => {
      const rank = (kind) => (MISSION_ROW_ORDER.includes(kind) ? MISSION_ROW_ORDER.indexOf(kind) : 99);
      return rank(a) - rank(b) || a.localeCompare(b);
    });
    return {
      missionsById: byId,
      tracks: kinds.map((kind) => {
        const items = byKind.get(kind);
        return {
          key: `mission:${kind}`,
          label: MISSION_ROW_LABELS[kind] || kind,
          group: "Missions",
          kind: "intervals",
          missionKind: kind,
          items,
          lanes: assignLanes(items),
          endTime,
        };
      }),
    };
  }

  function buildBehaviorTracks(records, missionsById, endTime) {
    const byComponent = new Map();
    const itemsByKey = new Map();
    for (const record of records) {
      if (record.event !== "behavior.state_changed") continue;
      const data = record.data;
      const component = record.component;
      if (component === "behavior.standing" && data.state === "ANCHORED") continue;
      const missionId = data.mission_id || "";
      // Defense logs one phase per role or per tank; keep them apart.
      const subject = data.unit_tag ?? data.role ?? "";
      const key = `${component}|${missionId}|${subject}`;
      let item = itemsByKey.get(key);
      if (!item) {
        const mission = missionsById.get(missionId);
        item = {
          id: key,
          component,
          missionId,
          missionKind: mission?.kind,
          start: record.game_time,
          end: mission?.end ?? null,
          statuses: [],
        };
        itemsByKey.set(key, item);
        if (!byComponent.has(component)) byComponent.set(component, []);
        byComponent.get(component).push(item);
      }
      const last = item.statuses[item.statuses.length - 1];
      if (!last || last.value !== data.state) {
        item.statuses.push({ t: record.game_time, value: String(data.state), reason: data.reason, event: record.event, record });
      }
    }
    return [...byComponent.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([component, items]) => ({
        key: `behavior:${component}`,
        label: component.replace(/^behavior\./, ""),
        group: "Behavior",
        kind: "intervals",
        component,
        items,
        lanes: assignLanes(items),
        endTime,
      }));
  }

  function sumForces(data) {
    const forces = Array.isArray(data.forces) ? data.forces : [];
    return forces.reduce((total, force) => total + (finite(force.strength) ?? 0), 0);
  }

  function minHeldBaseSecurity(data) {
    const values = (Array.isArray(data.bases) ? data.bases : [])
      .map((base) => finite(base.ground_security))
      .filter((value) => value !== undefined);
    return values.length ? Math.min(...values) : undefined;
  }

  // Strategy telemetry mirrors bot.strategy.StrategySnapshot. Anything not
  // explicitly marked `shadow: false` is shadow: never an executed command.
  function strategyDetail(data) {
    return {
      objective: data.objective,
      previous: data.previous_objective ?? null,
      leader: data.leader ?? null,
      confidence: finite(data.confidence),
      timeInObjective: finite(data.time_in_objective),
      shadow: data.shadow !== false,
      inputs: data.inputs && typeof data.inputs === "object" ? data.inputs : {},
      scores: data.scores && typeof data.scores === "object" ? data.scores : {},
    };
  }

  function buildDecisionTimeline(records) {
    const sorted = records.every((record, index) => index === 0 || records[index - 1].game_time <= record.game_time)
      ? records
      : [...records].sort((a, b) => a.game_time - b.game_time);
    const endTime = sorted.length ? sorted[sorted.length - 1].game_time : 0;

    const t = {
      objective: stateTrack("strategy.objective", "Objective", "Strategy"),
      macroPosture: stateTrack("posture.macro", "Macro posture", "Posture"),
      combatPosture: stateTrack("posture.combat", "Combat posture", "Posture"),
      armyBelief: stateTrack("belief.army", "Army belief", "Knowledge"),
      economyBelief: stateTrack("belief.economy", "Economy belief", "Knowledge"),
      mapControlSafe: stateTrack("map_control.safe", "Map ctrl safe?", "Knowledge"),
      strategyConfidence: seriesTrack("strategy.confidence", "Confidence", "Strategy", { min: 0, max: 1, format: 2 }),
      relativeStrength: seriesTrack("threat.relative_strength", "Relative strength", "Threat", { min: -1, max: 1, zero: 0, format: 2 }),
      ownSupply: seriesTrack("threat.own_supply", "Own army supply", "Threat", { format: 0 }),
      enemySupply: seriesTrack("threat.enemy_supply", "Enemy army supply (est)", "Threat", { format: 0 }),
      enemyForceStrength: seriesTrack("threat.enemy_force_strength", "Enemy force strength", "Threat", { format: 0 }),
      enemyNearBase: seriesTrack("threat.enemy_near_base", "Enemy near base", "Threat", { min: 0, format: 0, bars: true }),
      baseSecurity: seriesTrack("territory.base_security", "Min base security", "Territory", { min: 0, max: 1, format: 2 }),
      friendlyRegions: seriesTrack("territory.friendly_regions", "Friendly regions", "Territory", { min: 0, format: 0 }),
      enemyRegions: seriesTrack("territory.enemy_regions", "Enemy regions", "Territory", { min: 0, format: 0 }),
      supplyUsed: seriesTrack("economy.supply", "Supply used", "Economy", { min: 0, format: 0 }),
      minerals: seriesTrack("economy.minerals", "Minerals", "Economy", { min: 0, format: 0 }),
    };
    let strategySeen = false;
    let anyShadow = false;
    const beliefDetails = [];
    const assessments = [];

    for (const record of sorted) {
      const data = record.data;
      const time = record.game_time;
      const event = record.event;
      if (STRATEGY_EVENTS.has(event) && data.objective) {
        strategySeen = true;
        const detail = strategyDetail(data);
        anyShadow ||= detail.shadow;
        pushState(t.objective, time, data.objective, record, detail);
        pushSeries(t.strategyConfidence, time, detail.confidence);
      } else if (KNOWLEDGE_EVENTS.has(event)) {
        pushState(t.macroPosture, time, data.posture, record);
        pushSeries(t.relativeStrength, time, get(data, "relative_strength.score"));
        pushSeries(t.enemyNearBase, time, get(data, "threat.near_own_base_enemy_combat_units"));
      } else if (event === "standing.updated") {
        pushState(t.combatPosture, time, data.combat_posture, record);
      } else if (event === "awareness.world_belief") {
        pushState(t.armyBelief, time, get(data, "army.stable"), record, data.army);
        pushState(t.economyBelief, time, get(data, "economy.stable"), record, data.economy);
        pushSeries(t.ownSupply, time, get(data, "army.own_supply"));
        pushSeries(t.enemySupply, time, get(data, "army.enemy_estimated_supply"));
        beliefDetails.push({ t: time, army: data.army, economy: data.economy });
      } else if (event === "knowledge.enemy_model") {
        pushSeries(t.enemyForceStrength, time, sumForces(data));
      } else if (event === "knowledge.territory") {
        pushSeries(t.baseSecurity, time, minHeldBaseSecurity(data));
        pushSeries(t.friendlyRegions, time, get(data, "regions.friendly"));
        pushSeries(t.enemyRegions, time, get(data, "regions.enemy"));
      } else if (event === "observation.updated") {
        pushSeries(t.supplyUsed, time, data.supply_used);
        pushSeries(t.minerals, time, data.minerals);
      } else if (event === "behavior.assessed" && record.component === "behavior.map_control" && data.strategically_safe != null) {
        pushState(t.mapControlSafe, time, data.strategically_safe ? "SAFE" : "UNSAFE", record);
        assessments.push(record);
      }
    }

    const { missionsById, tracks: missionTracks } = buildMissionTracks(sorted, endTime);
    const behaviorTracks = buildBehaviorTracks(sorted, missionsById, endTime);

    const stateAndSeries = Object.values(t);
    const tracks = [...stateAndSeries, ...missionTracks, ...behaviorTracks];
    const byKey = new Map(tracks.map((track) => [track.key, track]));

    return {
      startTime: sorted.length ? sorted[0].game_time : 0,
      endTime,
      records: sorted,
      tracks,
      byKey,
      t,
      missionTracks,
      behaviorTracks,
      missionsById,
      strategy: { available: strategySeen, shadow: anyShadow },
      beliefDetails,
    };
  }

  function hasData(track) {
    if (!track) return false;
    return track.kind === "intervals" ? track.items.length > 0 : track.points.length > 0;
  }

  // --- queries at a selected time --------------------------------------------

  function missionsOpenAt(model, time) {
    const result = [];
    for (const track of model.missionTracks) {
      for (const item of track.items) {
        if (isOpenAt(item, time)) result.push({ item, status: statusAt(item, time) });
      }
    }
    return result;
  }

  function behaviorStatesAt(model, time) {
    const result = [];
    for (const track of model.behaviorTracks) {
      for (const item of track.items) {
        if (!isOpenAt(item, time)) continue;
        const index = lastIndexAtOrBefore(item.statuses, time);
        if (index >= 0) result.push({ item, state: item.statuses[index] });
      }
    }
    return result;
  }

  // Latest phase of a mission's behavior, across every executor that logged it.
  function behaviorStateOfMission(model, missionId, time) {
    let latest;
    for (const track of model.behaviorTracks) {
      for (const item of track.items) {
        if (item.missionId !== missionId) continue;
        const index = lastIndexAtOrBefore(item.statuses, time);
        if (index >= 0 && (!latest || item.statuses[index].t >= latest.t)) latest = item.statuses[index];
      }
    }
    return latest;
  }

  // A map-control mission that is ACTIVE and whose squad is not pulled home.
  function mapControlEngagedAt(model, time) {
    const track = model.byKey.get("mission:MAP_CONTROL");
    if (!track) return [];
    return track.items.filter((item) => {
      if (!isOpenAt(item, time) || statusAt(item, time) !== "ACTIVE") return false;
      const state = behaviorStateOfMission(model, item.id, time);
      return !state || !MAP_CONTROL_HOME_STATES.has(state.value);
    });
  }

  function activeMissionsOfKind(model, kinds, time) {
    const result = [];
    for (const kind of kinds) {
      const track = model.byKey.get(`mission:${kind}`);
      if (!track) continue;
      for (const item of track.items) {
        if (isOpenAt(item, time) && statusAt(item, time) === "ACTIVE") result.push(item);
      }
    }
    return result;
  }

  function openMissionsOfKind(model, kind, time) {
    const track = model.byKey.get(`mission:${kind}`);
    if (!track) return [];
    return track.items.filter((item) => isOpenAt(item, time)).map((item) => ({ item, status: statusAt(item, time) }));
  }

  // The world state every view shows for one instant.
  function snapshotAt(model, time) {
    const t = model.t;
    const objective = stateAt(t.objective, time);
    return {
      time,
      strategy: objective ? { ...objective.detail, since: objective.t } : undefined,
      macroPosture: valueAt(t.macroPosture, time),
      combatPosture: valueAt(t.combatPosture, time),
      armyBelief: stateAt(t.armyBelief, time),
      economyBelief: stateAt(t.economyBelief, time),
      relativeStrength: valueAt(t.relativeStrength, time),
      ownSupply: valueAt(t.ownSupply, time),
      enemySupply: valueAt(t.enemySupply, time),
      enemyForceStrength: valueAt(t.enemyForceStrength, time),
      enemyNearBase: valueAt(t.enemyNearBase, time),
      baseSecurity: valueAt(t.baseSecurity, time),
      friendlyRegions: valueAt(t.friendlyRegions, time),
      enemyRegions: valueAt(t.enemyRegions, time),
      mapControlSafe: valueAt(t.mapControlSafe, time),
      supplyUsed: valueAt(t.supplyUsed, time),
      minerals: valueAt(t.minerals, time),
      missions: missionsOpenAt(model, time),
      behaviors: behaviorStatesAt(model, time),
    };
  }

  // --- transitions and their causes ------------------------------------------

  const TRANSITION_TRACKS = ["objective", "macroPosture", "combatPosture", "armyBelief", "economyBelief"];

  function transitions(model) {
    const result = [];
    for (const name of TRANSITION_TRACKS) {
      const track = model.t[name];
      track.points.forEach((point, index) => {
        result.push({
          t: point.t,
          trackKey: track.key,
          label: track.label,
          from: index > 0 ? track.points[index - 1].value : null,
          to: point.value,
          shadow: name === "objective" ? point.detail?.shadow !== false : false,
          detail: point.detail,
          record: point.record,
          reason: point.record?.data?.reason,
        });
      });
    }
    for (const track of model.missionTracks) {
      for (const item of track.items) {
        item.statuses.forEach((status, index) => {
          if (!["ACTIVE", "BLOCKED", "COMPLETED", "FAILED", "CANCELLED"].includes(status.value)) return;
          result.push({
            t: status.t,
            trackKey: track.key,
            label: `${track.label} ${item.id}`,
            from: index > 0 ? item.statuses[index - 1].value : null,
            to: status.value,
            reason: status.reason,
            missionId: item.id,
          });
        });
      }
    }
    for (const track of model.behaviorTracks) {
      for (const item of track.items) {
        item.statuses.forEach((status, index) => {
          result.push({
            t: status.t,
            trackKey: track.key,
            label: `${track.label}${item.missionId ? ` ${item.missionId}` : ""}`,
            from: index > 0 ? item.statuses[index - 1].value : null,
            to: status.value,
            reason: status.reason,
            missionId: item.missionId,
            record: status.record,
          });
        });
      }
    }
    return result.sort((a, b) => a.t - b.t);
  }

  function strategyTransitions(model) {
    return transitions(model).filter((item) => item.trackKey === "strategy.objective" && item.from !== null);
  }

  // The few signals that explain a change: value just before vs at the change.
  const CAUSE_SIGNALS = [
    ["macroPosture", "macro_posture"],
    ["combatPosture", "combat_posture"],
    ["armyBelief", "military_position"],
    ["economyBelief", "economic_position"],
    ["relativeStrength", "relative_strength"],
    ["enemyNearBase", "enemy_near_base"],
    ["enemyForceStrength", "enemy_force_strength"],
    ["ownSupply", "own_army_supply"],
    ["enemySupply", "enemy_army_supply"],
    ["baseSecurity", "min_base_security"],
    ["mapControlSafe", "map_control_safe"],
  ];

  function formatValue(value, digits) {
    if (value === undefined || value === null) return "N/A";
    if (typeof value === "number") return digits === 0 ? String(Math.round(value)) : value.toFixed(digits ?? 2);
    return String(value);
  }

  function causeOf(model, transition) {
    const time = transition.t;
    const lines = [];
    for (const [name, label] of CAUSE_SIGNALS) {
      const track = model.t[name];
      if (!hasData(track)) continue;
      const before = valueBefore(track, time);
      const after = valueAt(track, time);
      if (before === undefined && after === undefined) continue;
      const digits = track.format;
      const changed = typeof after === "number" && typeof before === "number"
        ? Math.abs(after - before) >= (digits === 0 ? 1 : 0.05)
        : before !== after;
      lines.push({
        signal: label,
        before: formatValue(before, digits),
        after: formatValue(after, digits),
        changed,
      });
    }
    const strategy = transition.detail && transition.trackKey === "strategy.objective" ? transition.detail : undefined;
    const inputs = strategy ? Object.entries(strategy.inputs).map(([signal, value]) => ({
      signal,
      value: formatValue(finite(value) ?? value, 2),
    })) : [];
    return {
      reason: transition.reason ?? null,
      confidence: strategy?.confidence,
      shadow: strategy?.shadow,
      signals: lines.sort((a, b) => Number(b.changed) - Number(a.changed)),
      strategyInputs: inputs,
    };
  }

  const api = {
    MAP_CONTROL_HOME_STATES,
    buildDecisionTimeline,
    hasData,
    stateAt,
    valueAt,
    valueBefore,
    segments,
    statusAt,
    isOpenAt,
    lastIndexAtOrBefore,
    missionsOpenAt,
    behaviorStatesAt,
    behaviorStateOfMission,
    mapControlEngagedAt,
    activeMissionsOfKind,
    openMissionsOfKind,
    snapshotAt,
    transitions,
    strategyTransitions,
    causeOf,
    formatValue,
  };
  root.SC2Timeline = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
