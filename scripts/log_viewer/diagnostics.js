// Contradiction diagnostics over a decision timeline.
//
// Explicit, readable rules only. A diagnostic is a hint for debugging, never
// a verdict that something is a bug. Every lookup is a step function of time,
// so evaluating the rules at each change point is exact.
(function (root) {
  "use strict";

  const T = root.SC2Timeline || (typeof require !== "undefined" ? require("./timeline_model.js") : undefined);

  const THRESHOLDS = {
    // relative_strength is -1 (clearly behind) .. +1 (clearly ahead).
    harassRelativeStrength: -0.3,
    safeWhileBehindRelativeStrength: -0.5,
    enemyNearBase: 3,
  };

  const DEFENSIVE_OBJECTIVES = new Set(["STABILIZE", "RECOVER"]);
  const HARASS_KINDS = ["HARASS", "AIR_HARASS"];

  function objectiveLabel(state) {
    return `${state.strategy.objective}${state.strategy.shadow ? " [shadow]" : ""}`;
  }

  function missionIds(items) {
    return items.map((item) => item.id).join(", ");
  }

  // Each rule: (model, state) -> undefined | { title, evidence[] }.
  const RULES = [
    {
      id: "strategy_defensive_vs_map_control",
      severity: "warning",
      label: "Strategy defensive, map control out",
      check(model, state) {
        if (!state.strategy || !DEFENSIVE_OBJECTIVES.has(state.strategy.objective)) return undefined;
        const engaged = T.mapControlEngagedAt(model, state.time);
        if (!engaged.length) return undefined;
        return {
          title: `${objectiveLabel(state)} + MAP_CONTROL engaged`,
          evidence: [`objective=${objectiveLabel(state)}`, `map control engaged: ${missionIds(engaged)}`],
        };
      },
    },
    {
      id: "strategy_recover_vs_harass",
      severity: "warning",
      label: "Strategy recovering, harass active while behind",
      check(model, state) {
        if (!state.strategy || !DEFENSIVE_OBJECTIVES.has(state.strategy.objective)) return undefined;
        const harass = T.activeMissionsOfKind(model, HARASS_KINDS, state.time);
        const behind = state.relativeStrength !== undefined && state.relativeStrength <= THRESHOLDS.harassRelativeStrength;
        if (!harass.length || !behind) return undefined;
        return {
          title: `${objectiveLabel(state)} + ${harass.map((item) => item.kind).join("/")} active`,
          evidence: [
            `objective=${objectiveLabel(state)}`,
            `relative_strength=${state.relativeStrength.toFixed(2)} <= ${THRESHOLDS.harassRelativeStrength}`,
            `harass active: ${missionIds(harass)}`,
          ],
        };
      },
    },
    {
      id: "defensive_standing_vs_map_control",
      severity: "warning",
      label: "Turtling or behind, map control out",
      check(model, state) {
        const signals = [];
        if (state.combatPosture === "TURTLE") signals.push("TURTLE");
        if (state.armyBelief?.value === "BEHIND") signals.push("army BEHIND");
        if (!signals.length) return undefined;
        const engaged = T.mapControlEngagedAt(model, state.time);
        if (!engaged.length) return undefined;
        const evidence = [`map control engaged: ${missionIds(engaged)}`, `combat_posture=${state.combatPosture ?? "N/A"}`, `army_belief=${state.armyBelief?.value ?? "N/A"}`];
        if (state.relativeStrength !== undefined) evidence.push(`relative_strength=${state.relativeStrength.toFixed(2)}`);
        if (state.macroPosture) evidence.push(`macro_posture=${state.macroPosture}`);
        return { title: `${signals.join(" + ")} + MAP_CONTROL engaged`, evidence };
      },
    },
    {
      id: "threat_near_base_units_away",
      severity: "warning",
      label: "Enemy at the base, units out on the map",
      check(model, state) {
        if (state.enemyNearBase === undefined || state.enemyNearBase < THRESHOLDS.enemyNearBase) return undefined;
        const away = [...T.mapControlEngagedAt(model, state.time), ...T.activeMissionsOfKind(model, HARASS_KINDS, state.time)];
        if (!away.length) return undefined;
        return {
          title: `${state.enemyNearBase} enemies near base + ${away.map((item) => item.kind).join("/")} away`,
          evidence: [`enemy_near_base=${state.enemyNearBase} >= ${THRESHOLDS.enemyNearBase}`, `away: ${missionIds(away)}`],
        };
      },
    },
    {
      id: "threat_near_base_no_defense",
      severity: "warning",
      label: "Enemy at the base, no active defense",
      check(model, state) {
        if (state.enemyNearBase === undefined || state.enemyNearBase < THRESHOLDS.enemyNearBase) return undefined;
        const defenses = T.openMissionsOfKind(model, "DEFENSE", state.time);
        if (defenses.some((entry) => entry.status === "ACTIVE")) return undefined;
        const statuses = defenses.map((entry) => `${entry.item.id}=${entry.status}`);
        return {
          title: `${state.enemyNearBase} enemies near base, defense ${defenses.length ? defenses.map((entry) => entry.status).join("/") : "absent"}`,
          evidence: [`enemy_near_base=${state.enemyNearBase} >= ${THRESHOLDS.enemyNearBase}`, statuses.length ? `defense: ${statuses.join(", ")}` : "no DEFENSE mission open"],
        };
      },
    },
    {
      id: "map_control_safe_while_behind",
      severity: "note",
      label: "Map control judged safe while clearly behind",
      check(model, state) {
        if (state.mapControlSafe !== "SAFE" || state.armyBelief?.value !== "BEHIND") return undefined;
        if (state.relativeStrength === undefined || state.relativeStrength > THRESHOLDS.safeWhileBehindRelativeStrength) return undefined;
        return {
          title: "strategically_safe=true while army BEHIND",
          evidence: [
            "map_control strategically_safe=true",
            "army_belief=BEHIND",
            `relative_strength=${state.relativeStrength.toFixed(2)} <= ${THRESHOLDS.safeWhileBehindRelativeStrength}`,
            `macro_posture=${state.macroPosture ?? "N/A"}`,
          ],
        };
      },
    },
    {
      id: "posture_divergence",
      severity: "note",
      label: "Combat and macro postures pull opposite ways",
      check(model, state) {
        const combat = state.combatPosture;
        const macro = state.macroPosture;
        const diverges = (combat === "TURTLE" && macro === "GREED")
          || (combat === "PRESSURE" && (macro === "DEFENSE" || macro === "RECOVERY"));
        if (!diverges) return undefined;
        return { title: `combat ${combat} vs macro ${macro}`, evidence: [`combat_posture=${combat}`, `macro_posture=${macro}`] };
      },
    },
  ];

  function changeTimes(model) {
    const times = new Set([model.startTime]);
    for (const track of model.tracks) {
      if (track.kind === "intervals") {
        for (const item of track.items) {
          times.add(item.start);
          if (item.end != null) times.add(item.end);
          for (const status of item.statuses) times.add(status.t);
        }
      } else {
        for (const point of track.points) times.add(point.t);
      }
    }
    return [...times].filter(Number.isFinite).sort((a, b) => a - b);
  }

  function runDiagnostics(model, rules = RULES) {
    const results = [];
    const open = new Map();
    for (const time of changeTimes(model)) {
      const state = T.snapshotAt(model, time);
      for (const rule of rules) {
        const hit = rule.check(model, state);
        const current = open.get(rule.id);
        if (hit && !current) {
          open.set(rule.id, { rule: rule.id, severity: rule.severity, label: rule.label, title: hit.title, evidence: hit.evidence, start: time, end: null });
        } else if (!hit && current) {
          current.end = time;
          results.push(current);
          open.delete(rule.id);
        }
      }
    }
    for (const current of open.values()) {
      current.end = model.endTime;
      current.openAtEnd = true;
      results.push(current);
    }
    return results.sort((a, b) => a.start - b.start || a.rule.localeCompare(b.rule));
  }

  function diagnosticsAt(diagnostics, time) {
    return diagnostics.filter((item) => item.start <= time && (time < item.end || (item.openAtEnd && time <= item.end)));
  }

  const api = { THRESHOLDS, RULES, runDiagnostics, diagnosticsAt };
  root.SC2Diagnostics = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
