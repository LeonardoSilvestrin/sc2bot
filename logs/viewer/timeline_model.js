// Decision timeline model: turns the structured log into time-indexed tracks,
// grouped by the bot's layers, so any instant can be queried without
// rescanning the log.
//
// Pure: no DOM. Loaded as a classic script (works over file://) and exposes
// `SC2Timeline` globally.
(function (root) {
  "use strict";

  const OWNER_ORDER = ["defense", "core_army"];
  const OWNER_LABELS = { defense: "Defense", core_army: "Core army" };

  function finite(value) {
    const number = Number(value);
    return value != null && value !== "" && Number.isFinite(number) ? number : undefined;
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
    const text = String(value);
    const last = track.points[track.points.length - 1];
    if (last && last.value === text) {
      if (detail !== undefined) last.lastDetail = detail;
      return;
    }
    if (last && last.t === time) {
      track.points.pop();
      const previous = track.points[track.points.length - 1];
      if (previous && previous.value === text) return;
    }
    track.points.push({ t: time, value: text, record, detail, lastDetail: detail });
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

  // --- interval tracks: proposals and commands, one lane per overlap ---------

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
    return Math.max(1, laneEnds.length);
  }

  function isOpenAt(item, time) {
    return item.start <= time && (item.end == null || time < item.end);
  }

  function statusAt(item, time) {
    const index = lastIndexAtOrBefore(item.statuses, time);
    return index < 0 ? undefined : item.statuses[index];
  }

  // Items keyed by id, grouped by owner: open while their value is non-null.
  function intervals() {
    const byOwner = new Map();
    const open = new Map();
    return {
      set(id, owner, time, value, reason, record) {
        let item = open.get(id);
        if (value == null) {
          if (item) {
            item.end = time;
            open.delete(id);
          }
          return;
        }
        if (!item) {
          item = { id, owner, start: time, end: null, statuses: [] };
          open.set(id, item);
          if (!byOwner.has(owner)) byOwner.set(owner, []);
          byOwner.get(owner).push(item);
        }
        const last = item.statuses[item.statuses.length - 1];
        if (!last || last.value !== value) item.statuses.push({ t: time, value, reason, record });
        else last.record = record;
      },
      openIds() {
        return [...open.keys()];
      },
      ownerOf(id) {
        return open.get(id)?.owner;
      },
      tracks(prefix, group, endTime) {
        const rank = (owner) => (OWNER_ORDER.includes(owner) ? OWNER_ORDER.indexOf(owner) : 99);
        return [...byOwner.entries()]
          .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
          .map(([owner, items]) => ({
            key: `${prefix}:${owner}`,
            label: OWNER_LABELS[owner] || owner,
            group,
            kind: "intervals",
            owner,
            items,
            lanes: assignLanes(items),
            endTime,
          }));
      },
    };
  }

  function sum(values) {
    return values.reduce((total, value) => total + (finite(value) ?? 0), 0);
  }

  function buildDecisionTimeline(records) {
    const sorted = records.every((record, index) => index === 0 || records[index - 1].game_time <= record.game_time)
      ? records
      : [...records].sort((a, b) => a.game_time - b.game_time);
    const startTime = sorted.length ? sorted[0].game_time : 0;
    const endTime = sorted.length ? sorted[sorted.length - 1].game_time : 0;

    const t = {
      objective: stateTrack("strategy.objective", "Objective", "Strategy"),
      defensePreference: seriesTrack("strategy.defense", "Defense preference", "Strategy", { min: 0, max: 1, format: 2 }),
      armyPreference: seriesTrack("strategy.army", "Army spending", "Strategy", { min: 0, max: 1, format: 2 }),
      risk: seriesTrack("strategy.risk", "Risk tolerance", "Strategy", { min: 0, max: 1, format: 2 }),
      danger: seriesTrack("awareness.danger", "Danger", "Awareness", { min: 0, max: 1, format: 2 }),
      ownPower: seriesTrack("awareness.own_power", "Power own", "Awareness", { min: 0, format: 1 }),
      enemyPower: seriesTrack("awareness.enemy_power", "Power enemy", "Awareness", { min: 0, format: 1 }),
      contacts: seriesTrack("awareness.contacts", "Contacts", "Awareness", { min: 0, format: 0 }),
      economy: stateTrack("behaviors.economy", "Economy plan", "Behaviors"),
      coreUnits: seriesTrack("engine.units.core_army", "Units core army", "Engine", { min: 0, format: 0 }),
      defenseUnits: seriesTrack("engine.units.defense", "Units defense", "Engine", { min: 0, format: 0 }),
      unassigned: seriesTrack("engine.unassigned", "Unassigned army", "Engine", { min: 0, format: 0 }),
      supply: seriesTrack("attention.supply", "Supply used", "Attention", { min: 0, format: 0 }),
      minerals: seriesTrack("attention.minerals", "Minerals", "Attention", { min: 0, format: 0 }),
      visibleEnemies: seriesTrack("attention.visible_enemies", "Visible enemies", "Attention", { min: 0, format: 0 }),
      frameMs: seriesTrack("logs.frame_ms", "Frame ms (max)", "Logs", { min: 0, format: 1 }),
    };
    const proposals = intervals();
    const commands = intervals();
    const awarenessRecords = [];
    const strategyRecords = [];
    const attentionRecords = [];
    let strategySeen = false;

    for (const record of sorted) {
      const data = record.data;
      const time = record.game_time;
      switch (record.event) {
        case "strategy.decided": {
          strategySeen = true;
          const detail = {
            objective: data.objective,
            previous: data.previous ?? null,
            since: finite(data.since),
            reason: data.reason,
            defense: finite(data.defense),
            army: finite(data.army),
            risk: finite(data.risk),
            inputs: data.inputs && typeof data.inputs === "object" ? data.inputs : {},
            scores: data.scores && typeof data.scores === "object" ? data.scores : {},
          };
          pushState(t.objective, time, data.objective, record, detail);
          pushSeries(t.defensePreference, time, data.defense);
          pushSeries(t.armyPreference, time, data.army);
          pushSeries(t.risk, time, data.risk);
          strategyRecords.push({ t: time, record });
          break;
        }
        case "awareness.updated":
          pushSeries(t.danger, time, data.danger);
          pushSeries(t.ownPower, time, data.own_power);
          pushSeries(t.enemyPower, time, data.enemy_power);
          pushSeries(t.contacts, time, data.contacts);
          awarenessRecords.push({ t: time, record });
          break;
        case "attention.observed":
          pushSeries(t.supply, time, data.supply_used);
          pushSeries(t.minerals, time, data.minerals);
          pushSeries(t.visibleEnemies, time, data.visible_enemy_units);
          attentionRecords.push({ t: time, record });
          break;
        case "behavior.proposed": {
          const present = new Set();
          for (const proposal of Array.isArray(data.proposals) ? data.proposals : []) {
            present.add(proposal.proposal_id);
            proposals.set(proposal.proposal_id, proposal.owner, time, proposal.reason || proposal.command, proposal.reason, record);
          }
          for (const id of proposals.openIds()) {
            if (!present.has(id)) proposals.set(id, proposals.ownerOf(id), time, null);
          }
          break;
        }
        case "behavior.economy_planned":
          pushState(t.economy, time, data.reason, record, data);
          break;
        case "engine.granted": {
          const grants = Array.isArray(data.grants) ? data.grants : [];
          const byOwner = { core_army: 0, defense: 0 };
          for (const grant of grants) byOwner[grant.owner] = (byOwner[grant.owner] ?? 0) + (finite(grant.granted) ?? 0);
          pushSeries(t.coreUnits, time, byOwner.core_army);
          pushSeries(t.defenseUnits, time, byOwner.defense);
          pushSeries(t.unassigned, time, Array.isArray(data.unassigned) ? data.unassigned.length : 0);
          break;
        }
        case "engine.commanded": {
          const count = Array.isArray(data.tags) ? data.tags.length : 0;
          const value = count ? `${data.command} ${count}u` : null;
          commands.set(data.proposal_id, data.owner, time, value, data.reason, record);
          break;
        }
        case "logs.frame_perf":
          pushSeries(t.frameMs, time, sum(Object.values(data.max_ms || {})));
          break;
        default:
          break;
      }
    }

    const proposalTracks = proposals.tracks("proposal", "Behaviors", endTime);
    const commandTracks = commands.tracks("command", "Engine", endTime);
    const tracks = [...Object.values(t), ...proposalTracks, ...commandTracks];
    return {
      startTime,
      endTime,
      records: sorted,
      tracks,
      byKey: new Map(tracks.map((track) => [track.key, track])),
      t,
      proposalTracks,
      commandTracks,
      awarenessRecords,
      strategyRecords,
      attentionRecords,
      strategy: { available: strategySeen },
    };
  }

  function hasData(track) {
    if (!track) return false;
    return track.kind === "intervals" ? track.items.length > 0 : track.points.length > 0;
  }

  // --- queries at a selected time --------------------------------------------

  function recordAt(list, time) {
    const index = lastIndexAtOrBefore(list, time);
    return index < 0 ? undefined : list[index].record;
  }

  function openAt(tracks, time) {
    const result = [];
    for (const track of tracks) {
      for (const item of track.items) {
        if (isOpenAt(item, time)) result.push({ item, status: statusAt(item, time) });
      }
    }
    return result;
  }

  // The world state every view shows for one instant, layer by layer.
  function snapshotAt(model, time) {
    const t = model.t;
    const objective = stateAt(t.objective, time);
    return {
      time,
      strategy: objective ? { ...(objective.lastDetail ?? objective.detail), since: objective.t } : undefined,
      strategyRecord: recordAt(model.strategyRecords, time),
      awarenessRecord: recordAt(model.awarenessRecords, time),
      attentionRecord: recordAt(model.attentionRecords, time),
      danger: valueAt(t.danger, time),
      ownPower: valueAt(t.ownPower, time),
      enemyPower: valueAt(t.enemyPower, time),
      contacts: valueAt(t.contacts, time),
      economy: stateAt(t.economy, time),
      coreUnits: valueAt(t.coreUnits, time),
      defenseUnits: valueAt(t.defenseUnits, time),
      unassigned: valueAt(t.unassigned, time),
      supply: valueAt(t.supply, time),
      minerals: valueAt(t.minerals, time),
      visibleEnemies: valueAt(t.visibleEnemies, time),
      frameMs: valueAt(t.frameMs, time),
      proposals: openAt(model.proposalTracks, time),
      commands: openAt(model.commandTracks, time),
    };
  }

  // Share of [startTime, endTime] a state track spent on `value`.
  function shareOf(model, track, value) {
    const span = model.endTime - model.startTime;
    if (!(span > 0)) return undefined;
    let total = 0;
    for (const segment of segments(track, model.endTime)) {
      if (segment.value === value) total += segment.end - segment.start;
    }
    return total / span;
  }

  // --- transitions and their causes ------------------------------------------

  function transitions(model) {
    const result = [];
    for (const name of ["objective", "economy"]) {
      const track = model.t[name];
      track.points.forEach((point, index) => {
        result.push({
          t: point.t,
          trackKey: track.key,
          label: track.label,
          from: index > 0 ? track.points[index - 1].value : null,
          to: point.value,
          detail: point.detail,
          record: point.record,
          reason: point.record?.data?.reason,
        });
      });
    }
    for (const track of model.commandTracks) {
      for (const item of track.items) {
        item.statuses.forEach((status, index) => {
          result.push({
            t: status.t,
            trackKey: track.key,
            label: `${track.label} ${item.id}`,
            from: index > 0 ? item.statuses[index - 1].value : null,
            to: status.value,
            reason: status.reason,
            record: status.record,
          });
        });
        if (item.end != null) {
          result.push({ t: item.end, trackKey: track.key, label: `${track.label} ${item.id}`, from: item.statuses[item.statuses.length - 1]?.value ?? null, to: "released", reason: "no_units_granted" });
        }
      }
    }
    return result.sort((a, b) => a.t - b.t);
  }

  // The signals that explain a change: value just before vs at the change.
  const CAUSE_SIGNALS = [
    ["danger", "danger"],
    ["ownPower", "own_power"],
    ["enemyPower", "enemy_power"],
    ["contacts", "contacts"],
    ["visibleEnemies", "visible_enemies"],
    ["defenseUnits", "defense_units"],
    ["coreUnits", "core_army_units"],
    ["unassigned", "unassigned_army"],
  ];

  function formatValue(value, digits) {
    if (value === undefined || value === null) return "N/A";
    if (typeof value === "number") return digits === 0 ? String(Math.round(value)) : value.toFixed(digits ?? 2);
    return String(value);
  }

  function causeOf(model, transition) {
    const time = transition.t;
    const signals = [];
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
      signals.push({ signal: label, before: formatValue(before, digits), after: formatValue(after, digits), changed });
    }
    const strategy = transition.trackKey === "strategy.objective" ? transition.detail : undefined;
    const command = transition.record?.event === "engine.commanded" ? transition.record.data : undefined;
    const inputs = strategy?.inputs ?? command?.inputs ?? {};
    return {
      reason: transition.reason ?? null,
      signals: signals.sort((a, b) => Number(b.changed) - Number(a.changed)),
      inputs: Object.entries(inputs).map(([signal, value]) => ({ signal, value: formatValue(finite(value) ?? value, 2) })),
      scores: Object.entries(strategy?.scores ?? {}).map(([objective, value]) => ({ objective, value: formatValue(finite(value), 2) })),
    };
  }

  const api = {
    buildDecisionTimeline,
    hasData,
    stateAt,
    valueAt,
    valueBefore,
    segments,
    statusAt,
    isOpenAt,
    lastIndexAtOrBefore,
    snapshotAt,
    shareOf,
    transitions,
    causeOf,
    formatValue,
  };
  root.SC2Timeline = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
